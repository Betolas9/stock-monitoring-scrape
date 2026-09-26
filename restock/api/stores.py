from __future__ import annotations

import collections
import re
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scrapers import SCRAPER_TYPES, build_scraper

from .. import db, runtime, timeutil
from ..ingest import keep_listing
from ..matching import classify_fields, cleanup_orphans, refresh_products
from ..matching.text import slug
from .common import not_found, store_out

router = APIRouter(prefix="/api/stores", tags=["stores"])

STORE_SELECT = """
SELECT s.*,
  (SELECT COUNT(*) FROM listings l WHERE l.store_id = s.id AND l.present = 1) AS listing_count,
  (SELECT COUNT(*) FROM listings l WHERE l.store_id = s.id AND l.present = 1 AND l.in_stock = 1) AS in_stock_count,
  (SELECT COUNT(*) FROM listings l WHERE l.store_id = s.id AND l.present = 1 AND l.product_id IS NOT NULL) AS matched_count
FROM stores s
"""


def _with_runtime(r: dict) -> dict:
    out = store_out(r)
    running = runtime.scheduler.running() if runtime.scheduler else []
    if out["id"] in running:
        out["status"] = "running"
    return out


@router.get("")
def list_stores():
    with db.read() as conn:
        rows = db.rows(conn.execute(STORE_SELECT + " ORDER BY s.name COLLATE NOCASE"))
    return [_with_runtime(r) for r in rows]


@router.get("/{store_id}")
def get_store(store_id: str):
    with db.read() as conn:
        r = db.row(conn.execute(STORE_SELECT + " WHERE s.id = ?", (store_id,)))
    if not r:
        raise not_found("store")
    return _with_runtime(r)


class StoreBody(BaseModel):
    name: str | None = None
    platform: str | None = None
    url: str | None = None
    urls: list[str] | None = None
    options: dict | None = None
    enabled: bool | None = None
    interval_min: int | None = None
    interval_max: int | None = None
    notes: str | None = None


def _validate(fields: dict) -> None:
    if "platform" in fields and fields["platform"] not in SCRAPER_TYPES:
        raise HTTPException(400, f"unknown platform '{fields['platform']}'")
    for u in ([fields["url"]] if fields.get("url") else []) + (fields.get("urls") or []):
        if not re.match(r"^https?://", u):
            raise HTTPException(400, f"not a URL: {u}")


@router.post("")
def create_store(body: StoreBody):
    fields = body.model_dump(exclude_unset=True)
    if not fields.get("name") or not fields.get("url") or not fields.get("platform"):
        raise HTTPException(400, "name, url and platform are required")
    _validate(fields)
    with db.tx() as conn:
        base = slug(fields["name"]) or "store"
        sid, n = base, 2
        while conn.execute("SELECT 1 FROM stores WHERE id=?", (sid,)).fetchone():
            sid, n = f"{base}-{n}", n + 1
        urls = [u for u in (fields.get("urls") or []) if u.strip()]
        conn.execute(
            "INSERT INTO stores(id, name, platform, url, urls, options, enabled, interval_min, interval_max, notes,"
            " created_at, next_check_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, fields["name"], fields["platform"], fields["url"], db.jdump(urls) if urls else None,
             db.jdump(fields["options"]) if fields.get("options") else None, int(fields.get("enabled", True)),
             fields.get("interval_min"), fields.get("interval_max"), fields.get("notes"), timeutil.iso(),
             timeutil.iso()),
        )
    return get_store(sid)


@router.patch("/{store_id}")
def patch_store(store_id: str, body: StoreBody):
    fields = body.model_dump(exclude_unset=True)
    _validate(fields)
    with db.tx() as conn:
        cur = db.row(conn.execute("SELECT * FROM stores WHERE id=?", (store_id,)))
        if not cur:
            raise not_found("store")
        updates: dict = {}
        for k, v in fields.items():
            if k == "urls":
                urls = [u for u in (v or []) if u.strip()]
                updates["urls"] = db.jdump(urls) if urls else None
            elif k == "options":
                updates["options"] = db.jdump(v) if v else None
            elif k == "enabled":
                updates["enabled"] = int(v)
                if v and not cur["enabled"]:
                    updates["next_check_at"] = timeutil.iso()
                    updates["consecutive_failures"] = 0
            else:
                updates[k] = v
        # What gets scraped changed → the next check re-baselines silently
        # instead of reporting everything outside the new scope as sold out.
        if any(k in updates and updates[k] != cur[k] for k in ("platform", "url", "urls", "options")):
            updates["baseline_done"] = 0
            updates["next_check_at"] = timeutil.iso()
        if updates:
            conn.execute(f"UPDATE stores SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?",
                         list(updates.values()) + [store_id])
    return get_store(store_id)


@router.delete("/{store_id}")
def delete_store(store_id: str):
    with db.tx() as conn:
        touched = [r["product_id"] for r in conn.execute(
            "SELECT DISTINCT product_id FROM listings WHERE store_id=? AND product_id IS NOT NULL", (store_id,))]
        conn.execute("DELETE FROM listing_history WHERE listing_id IN (SELECT id FROM listings WHERE store_id=?)",
                     (store_id,))
        conn.execute("DELETE FROM listings WHERE store_id=?", (store_id,))
        conn.execute("DELETE FROM stores WHERE id=?", (store_id,))
        cleanup_orphans(conn)
        refresh_products(conn, touched)
    return {"ok": True}


@router.post("/check-all")
def check_all():
    if runtime.scheduler:
        runtime.scheduler.check_all_now()
    return {"ok": True}


@router.post("/{store_id}/check")
def check_now(store_id: str):
    if runtime.scheduler:
        runtime.scheduler.check_now(store_id)
    return get_store(store_id)


@router.post("/{store_id}/rebaseline")
def rebaseline(store_id: str):
    with db.tx() as conn:
        conn.execute("UPDATE stores SET baseline_done=0, next_check_at=? WHERE id=?", (timeutil.iso(), store_id))
    return get_store(store_id)


@router.post("/{store_id}/test")
def test_store(store_id: str, body: StoreBody | None = None):
    """Dry run: scrape now (optionally with unsaved edits) and report what
    would be tracked, without touching the database."""
    store = get_store(store_id)
    overrides = body.model_dump(exclude_unset=True) if body else {}
    cfg = {
        "type": overrides.get("platform", store["platform"]), "label": store["name"],
        "url": overrides.get("url", store["url"]),
        "urls": overrides.get("urls", store["urls"]) or None,
        "options": overrides.get("options", store["options"]),
    }
    return run_test(cfg)


class TestBody(BaseModel):
    platform: str
    url: str
    urls: list[str] | None = None
    options: dict | None = None


@router.post("/test")
def test_new_store(body: TestBody):
    return run_test({"type": body.platform, "label": "test", "url": body.url, "urls": body.urls or None,
                     "options": body.options or {}})


def run_test(cfg: dict) -> dict:
    if cfg["type"] not in SCRAPER_TYPES:
        raise HTTPException(400, f"unknown platform '{cfg['type']}'")
    t0 = time.monotonic()
    try:
        scraped = build_scraper("test", cfg).fetch_products()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "seconds": round(time.monotonic() - t0, 1)}
    kinds: collections.Counter = collections.Counter()
    sample = []
    kept = 0
    for p in scraped.values():
        c, fields = classify_fields(p.get("name") or "", p.get("meta"))
        keep = keep_listing(fields, bool((cfg.get('options') or {}).get('require_tcg')))
        kept += keep
        kinds[fields["kind"] if keep else f"dropped:{fields['kind']}"] += 1
        if keep and len(sample) < 25:
            sample.append({"name": p["name"], "price": p.get("price"), "in_stock": p.get("in_stock"),
                           "url": p.get("url"), "kind": fields["kind"], "tcg": fields["tcg"],
                           "type": fields["ptype"], "set_id": fields["set_id"]})
    return {"ok": True, "scraped": len(scraped), "kept": kept, "kinds": dict(kinds),
            "in_stock": sum(1 for p in scraped.values() if p.get("in_stock")),
            "seconds": round(time.monotonic() - t0, 1), "sample": sample}
