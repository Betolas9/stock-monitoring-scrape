"""Settings, notification channel tests, matching and app-wide status."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scrapers import SCRAPER_TYPES

from .. import APP_NAME, __version__, db, notify, runtime, settings, timeutil
from ..matching import rematch_all
from ..matching.rules import LANGS, TCGS, TYPE_LABELS
from ..notify.errors import NotifyError

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/meta")
def meta():
    return {"app": APP_NAME, "version": __version__, "tcgs": TCGS, "types": TYPE_LABELS, "langs": LANGS,
            "platforms": sorted(SCRAPER_TYPES)}


@router.get("/summary")
def summary():
    with db.read() as conn:
        stores = db.row(conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(enabled),0) AS enabled,"
            " COALESCE(SUM(enabled AND status='ok'),0) AS ok, COALESCE(SUM(enabled AND status='error'),0) AS error,"
            " COALESCE(SUM(enabled AND status='pending'),0) AS pending, MAX(last_success_at) AS last_success"
            " FROM stores"))
        counts = db.row(conn.execute(
            "SELECT (SELECT COUNT(*) FROM products WHERE hidden=0 AND store_count>0) AS products,"
            " (SELECT COUNT(*) FROM products WHERE hidden=0 AND in_stock_count>0) AS products_in_stock,"
            " (SELECT COUNT(*) FROM listings WHERE present=1) AS listings,"
            " (SELECT COUNT(*) FROM listings WHERE present=1 AND product_id IS NULL AND kind='sealed') AS unmatched,"
            " (SELECT COUNT(*) FROM favorites) AS favorites,"
            " (SELECT COUNT(*) FROM sets WHERE focus=1) AS focus_sets,"
            " (SELECT COUNT(*) FROM events WHERE ts >= ?) AS events_24h,"
            " (SELECT COUNT(*) FROM events WHERE ts >= ? AND alert_reason IS NOT NULL) AS alerts_24h,"
            " (SELECT COUNT(*) FROM notifications WHERE status='failed') AS notifications_failed,"
            " (SELECT COUNT(*) FROM notifications WHERE status='pending') AS notifications_pending",
            (timeutil.ago(hours=24), timeutil.ago(hours=24))))
    cfg = settings.get()
    running = runtime.scheduler.running() if runtime.scheduler else []
    return {
        "stores": {**stores, "running": len(running)},
        **counts,
        "paused": cfg["scheduler"]["paused"],
        "channels": notify.enabled_channels(cfg),
        "started_at": runtime.scheduler.started_at if runtime.scheduler else None,
    }


@router.get("/settings")
def get_settings():
    return settings.get()


@router.put("/settings")
def put_settings(patch: dict):
    s = settings.update(patch)
    if runtime.scheduler:
        runtime.scheduler.wake()  # apply pause/concurrency right away
    return s


class TestBody(BaseModel):
    channel: str
    settings: dict | None = None  # unsaved channel config from the form


@router.post("/settings/test")
def test_channel(body: TestBody):
    if body.channel not in notify.SENDERS:
        raise HTTPException(400, "unknown channel")
    cfg = settings.get()
    if body.settings:
        cfg["channels"][body.channel] = {**cfg["channels"][body.channel], **body.settings}
    payload = {
        "kind": "events", "title": "🧪 Test · restock-monitoring",
        "items": [{
            "type": "back_in_stock", "title": "Perfect Order Elite Trainer Box (test)",
            "product_title": "ME03 - Perfect Order - Elite Trainer Box", "url": "https://sealedwatch.com/products",
            "image": None, "price": 64.99, "old_price": 69.99, "store": "Test Store", "reason": "favorite",
            "preorder": False, "in_stock": True,
        }],
    }
    try:
        notify.send_now(body.channel, payload, cfg)
    except NotifyError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return {"ok": True}


class TelegramDetect(BaseModel):
    bot_token: str | None = None


@router.post("/settings/telegram/detect")
def telegram_detect(body: TelegramDetect):
    token = (body.bot_token or settings.get()["channels"]["telegram"]["bot_token"] or "").strip()
    if not token:
        raise HTTPException(400, "enter the bot token first")
    try:
        bot = notify.telegram.bot_info(token)
        chats = notify.telegram.detect_chat_ids(token)
    except NotifyError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "bot": {"username": bot.get("username"), "name": bot.get("first_name")}, "chats": chats}


class RematchBody(BaseModel):
    only_unmatched: bool = False


@router.post("/matching/rerun")
def rerun_matching(body: RematchBody):
    with db.tx() as conn:
        return rematch_all(conn, only_unmatched=body.only_unmatched)


@router.get("/health")
def health():
    return {"ok": True, "time": timeutil.iso()}
