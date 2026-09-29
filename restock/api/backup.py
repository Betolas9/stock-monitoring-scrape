"""Export / import everything you configured, to move it to another computer.

The export holds: app settings (alert channels incl. Telegram token and
recipients, alert rules, intervals, ignore list), favourites with target
prices, the release calendar (focus flags, dates, sets you added) and the
store list with your changes (on/off, edited or added stores). It does NOT
hold scraped data or price history — copy data/restock.db for that.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import APP_NAME, db, runtime, settings, timeutil
from ..matching import catalog, refresh_products
from .sets import _rematch_async

router = APIRouter(prefix="/api/backup", tags=["backup"])

FORMAT = "settings-export"
VERSION = 1
STORE_FIELDS = ("name", "platform", "url", "urls", "options", "enabled", "interval_min", "interval_max",
                "notes", "seed_json")
SCRAPE_FIELDS = {"platform", "url", "urls", "options"}
SET_FIELDS = ("tcg", "code", "name", "aliases", "release_date", "date_confirmed", "focus", "auto_created",
              "notes", "seed_json")
PRODUCT_FIELDS = ("tcg", "set_id", "type", "lang", "variant", "title", "image", "manual")


@router.get("/export")
def export_config():
    with db.read() as conn:
        stores = db.rows(conn.execute(f"SELECT id, {', '.join(STORE_FIELDS)} FROM stores ORDER BY id"))
        sets = db.rows(conn.execute(f"SELECT id, {', '.join(SET_FIELDS)} FROM sets ORDER BY id"))
        favorites = db.rows(conn.execute(
            "SELECT f.*, " + ", ".join(f"p.{c} AS p_{c}" for c in PRODUCT_FIELDS) +
            " FROM favorites f JOIN products p ON p.id = f.product_id"))
    for f in favorites:
        f["product"] = {c: f.pop(f"p_{c}") for c in PRODUCT_FIELDS}
    return {
        "app": APP_NAME, "format": FORMAT, "version": VERSION, "exported_at": timeutil.iso(),
        "settings": settings.get(), "stores": stores, "sets": sets, "favorites": favorites,
    }


@router.post("/import")
def import_config(data: dict):
    if data.get("format") != FORMAT:
        raise HTTPException(400, "this is not a restock-monitoring settings export")
    counts = {"stores_added": 0, "stores_updated": 0, "sets_added": 0, "sets_updated": 0, "favorites": 0}

    if isinstance(data.get("settings"), dict):
        settings.update(data["settings"])

    now = timeutil.iso()
    touched_products: set[str] = set()
    with db.tx() as conn:
        for s in data.get("stores") or []:
            if not s.get("id") or not s.get("platform") or not s.get("url"):
                continue
            cur = db.row(conn.execute("SELECT * FROM stores WHERE id=?", (s["id"],)))
            vals = {f: s.get(f) for f in STORE_FIELDS}
            if cur is None:
                conn.execute(
                    f"INSERT INTO stores(id, {', '.join(STORE_FIELDS)}, created_at, next_check_at)"
                    f" VALUES(?, {', '.join('?' * len(STORE_FIELDS))}, ?, ?)",
                    [s["id"], *vals.values(), now, now])
                counts["stores_added"] += 1
                continue
            changed = [f for f in STORE_FIELDS if cur[f] != vals[f]]
            if not changed:
                continue
            extra = ", baseline_done=0, next_check_at=?" if SCRAPE_FIELDS & set(changed) else ""
            conn.execute(
                f"UPDATE stores SET {', '.join(f'{f}=?' for f in changed)}{extra} WHERE id=?",
                [vals[f] for f in changed] + ([now] if extra else []) + [s["id"]])
            counts["stores_updated"] += 1

        for st in data.get("sets") or []:
            if not st.get("id") or not st.get("tcg") or not st.get("name"):
                continue
            vals = {f: st.get(f) for f in SET_FIELDS}
            cur = db.row(conn.execute("SELECT * FROM sets WHERE id=?", (st["id"],)))
            if cur is None:
                conn.execute(
                    f"INSERT INTO sets(id, {', '.join(SET_FIELDS)}, created_at) VALUES(?, {', '.join('?' * len(SET_FIELDS))}, ?)",
                    [st["id"], *vals.values(), now])
                counts["sets_added"] += 1
            elif any(cur[f] != vals[f] for f in SET_FIELDS):
                conn.execute(f"UPDATE sets SET {', '.join(f'{f}=?' for f in SET_FIELDS)} WHERE id=?",
                             [*vals.values(), st["id"]])
                counts["sets_updated"] += 1

        for fav in data.get("favorites") or []:
            pid = fav.get("product_id")
            product = fav.get("product") or {}
            if not pid or not product.get("title"):
                continue
            # The product may not exist yet on a fresh install (stores not read
            # yet): create it, listings with the same id attach to it later.
            if not conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone():
                conn.execute(
                    f"INSERT INTO products(id, {', '.join(PRODUCT_FIELDS)}, created_at)"
                    f" VALUES(?, {', '.join('?' * len(PRODUCT_FIELDS))}, ?)",
                    [pid, *(product.get(c) for c in PRODUCT_FIELDS), now])
            conn.execute(
                "INSERT INTO favorites(product_id, target_price, notify_restock, notify_price, notify_new_store,"
                " note, created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET"
                " target_price=excluded.target_price, notify_restock=excluded.notify_restock,"
                " notify_price=excluded.notify_price, notify_new_store=excluded.notify_new_store, note=excluded.note",
                (pid, fav.get("target_price"), int(fav.get("notify_restock", 1)), int(fav.get("notify_price", 1)),
                 int(fav.get("notify_new_store", 1)), fav.get("note"), fav.get("created_at") or now))
            touched_products.add(pid)
            counts["favorites"] += 1
        refresh_products(conn, touched_products)

    catalog.invalidate()
    if counts["sets_added"] or counts["sets_updated"]:
        _rematch_async()
    if runtime.scheduler:
        runtime.scheduler.wake()
    return {"ok": True, **counts}
