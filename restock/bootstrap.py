"""First-start setup: create the schema, seed stores and sets, and import the
v1 data (config.json + data/known_products.json) exactly once."""
from __future__ import annotations

import html
import json
import logging
import sqlite3

from . import db, settings, timeutil
from .matching import catalog, classify_fields, find_or_create_product, refresh_products
from .ingest import keep_listing
from .paths import LEGACY_CONFIG, LEGACY_STATE, SEED_DIR

logger = logging.getLogger(__name__)

# v1 site keys → store ids. Several v1 "sites" were category pages of one store.
LEGACY_STORE_MAP = {
    "trapcardtcg": "trapcard",
    "creativetoys": "creative-toys",
    "toysrus_tcg": "toys-r-us",
    "toysrus_cartaspokemon": "toys-r-us",
    "ptmerch": "ptmerch",
    "ptmerch_boosterboxes": "ptmerch",
    "ptmerch_boosters": "ptmerch",
    "ptmerch_playmats": "ptmerch",
    "ptmerch_specialboxsets": "ptmerch",
}


def run() -> None:
    db.init()
    with db.tx() as conn:
        seed_sets(conn)
        seed_stores(conn)
    catalog.invalidate()
    with db.tx() as conn:
        if not db.get_meta(conn, "legacy_imported"):
            import_legacy(conn)
            db.set_meta(conn, "legacy_imported", timeutil.iso())
    catalog.invalidate()


# Seed data is merged, not just inserted: when a newer seed changes a field
# (a store's URLs, a set's release date…), the DB value is updated — unless
# the user changed that field in the UI (it no longer equals the previously
# applied seed value, kept in the row's seed_json).
STORE_FIELDS = ("name", "platform", "url", "urls", "options", "enabled", "interval_min", "interval_max", "notes")
STORE_SCRAPE_FIELDS = {"platform", "url", "urls", "options"}
SET_FIELDS = ("name", "aliases", "release_date", "date_confirmed", "notes")
_JSON_FIELDS = {"urls", "options", "aliases"}


def _store_seed(s: dict) -> dict:
    return {
        "name": s["name"], "platform": s["platform"], "url": s["url"], "urls": s.get("urls") or None,
        "options": s.get("options") or None, "enabled": bool(s.get("enabled", True)),
        "interval_min": s.get("interval_min"), "interval_max": s.get("interval_max"), "notes": s.get("notes"),
    }


def _set_seed(s: dict) -> dict:
    return {"name": s["name"], "aliases": s.get("aliases") or [], "release_date": s.get("release_date"),
            "date_confirmed": bool(s.get("date_confirmed", True)), "notes": s.get("notes")}


def _row_values(row: dict, fields) -> dict:
    out = {}
    for f in fields:
        v = row[f]
        if f in _JSON_FIELDS:
            v = db.jload(v, None) or ([] if f == "aliases" else None)
        elif f in ("enabled", "date_confirmed"):
            v = bool(v)
        out[f] = v
    return out


def _db_value(field: str, v):
    if field in _JSON_FIELDS:
        return db.jdump(v) if v else (db.jdump([]) if field == "aliases" else None)
    if isinstance(v, bool):
        return int(v)
    return v


def _merge(conn, table: str, key: str, fields, new: dict, now: str) -> set[str]:
    """Apply seed changes to one existing row; returns the changed fields."""
    row = db.row(conn.execute(f"SELECT * FROM {table} WHERE id=?", (key,)))
    current = _row_values(row, fields)
    previous = db.jload(row.get("seed_json"), None) or current  # pre-merge rows: assume untouched
    changed = {f for f in fields if current[f] == previous.get(f) and new[f] != current[f]}
    sets_sql = [f"{f}=?" for f in changed] + ["seed_json=?"]
    vals = [_db_value(f, new[f]) for f in changed] + [db.jdump(new)]
    conn.execute(f"UPDATE {table} SET {', '.join(sets_sql)} WHERE id=?", vals + [key])
    return changed


def seed_sets(conn: sqlite3.Connection) -> None:
    data = json.loads((SEED_DIR / "sets.json").read_text(encoding="utf-8"))
    now = timeutil.iso()
    for s in data["sets"]:
        sid = catalog.set_id_for(s["tcg"], s.get("code"), s["name"])
        new = _set_seed(s)
        if conn.execute("SELECT 1 FROM sets WHERE id=?", (sid,)).fetchone():
            changed = _merge(conn, "sets", sid, SET_FIELDS, new, now)
            if changed:
                logger.info(f"set {sid}: updated {sorted(changed)} from seed")
            continue
        conn.execute(
            "INSERT INTO sets(id, tcg, code, name, aliases, release_date, date_confirmed, focus,"
            " auto_created, notes, created_at, seed_json) VALUES(?,?,?,?,?,?,?,0,0,?,?,?)",
            (sid, s["tcg"], s.get("code"), new["name"], db.jdump(new["aliases"]), new["release_date"],
             int(new["date_confirmed"]), new["notes"], now, db.jdump(new)),
        )


def seed_stores(conn: sqlite3.Connection) -> None:
    data = json.loads((SEED_DIR / "stores.json").read_text(encoding="utf-8"))
    now = timeutil.iso()
    for s in data["stores"]:
        new = _store_seed(s)
        if conn.execute("SELECT 1 FROM stores WHERE id=?", (s["id"],)).fetchone():
            changed = _merge(conn, "stores", s["id"], STORE_FIELDS, new, now)
            if changed & STORE_SCRAPE_FIELDS:
                # what gets scraped changed → silent re-baseline, check soon
                conn.execute("UPDATE stores SET baseline_done=0, next_check_at=?, consecutive_failures=0"
                             " WHERE id=?", (now, s["id"]))
            elif "enabled" in changed:
                conn.execute("UPDATE stores SET next_check_at=? WHERE id=?", (now, s["id"]))
            if changed:
                logger.info(f"store {s['id']}: updated {sorted(changed)} from seed")
            continue
        conn.execute(
            "INSERT INTO stores(id, name, platform, url, urls, options, enabled, interval_min,"
            " interval_max, notes, created_at, seed_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (s["id"], new["name"], new["platform"], new["url"], _db_value("urls", new["urls"]),
             _db_value("options", new["options"]), int(new["enabled"]), new["interval_min"],
             new["interval_max"], new["notes"], now, db.jdump(new)),
        )


# --------------------------------------------------------------------------- v1 import

def import_legacy(conn: sqlite3.Connection) -> None:
    cfg: dict = {}
    if LEGACY_CONFIG.exists():
        try:
            cfg = json.loads(LEGACY_CONFIG.read_text(encoding="utf-8"))
        except ValueError as e:
            logger.warning(f"Could not read legacy config.json: {e}")
            cfg = {}
        if cfg.get("ignore_keywords"):
            settings_patch = {"ignore_keywords": cfg["ignore_keywords"]}
            # settings.update opens its own transaction — write directly here
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('app', ?) ON CONFLICT(key) DO NOTHING",
                (db.jdump(settings_patch),),
            )
            settings._cache = None  # noqa: SLF001 — force reload after import
        for key, site in (cfg.get("sites") or {}).items():
            store_id = LEGACY_STORE_MAP.get(key, key)
            if not conn.execute("SELECT 1 FROM stores WHERE id=?", (store_id,)).fetchone():
                conn.execute(
                    "INSERT INTO stores(id, name, platform, url, enabled, notes, created_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (store_id, site.get("label", key), site.get("type", key), site["url"],
                     int(site.get("enabled", True)), "Imported from v1 config.json", timeutil.iso()),
                )

    if not LEGACY_STATE.exists():
        return
    try:
        state = json.loads(LEGACY_STATE.read_text(encoding="utf-8"))
    except ValueError as e:
        logger.warning(f"Could not read legacy known_products.json: {e}")
        return

    ignore = [k.lower() for k in cfg.get("ignore_keywords", [])]
    imported = 0
    touched: set[str] = set()
    baselined: set[str] = set()
    for key, products in state.items():
        store_id = LEGACY_STORE_MAP.get(key, key)
        if not conn.execute("SELECT 1 FROM stores WHERE id=?", (store_id,)).fetchone():
            continue
        baselined.add(store_id)
        for ext_id, p in products.items():
            name = html.unescape(p.get("name") or "").strip()
            if not name or any(k in name.lower() for k in ignore):
                continue
            c, fields = classify_fields(name, "")
            if not keep_listing(fields):
                continue
            first_seen = timeutil.iso(timeutil.parse(p.get("first_seen")) or timeutil.now())
            last_seen = timeutil.iso(timeutil.parse(p.get("last_seen")) or timeutil.now())
            price = _f(p.get("price"))
            cur = conn.execute(
                "INSERT OR IGNORE INTO listings(store_id, external_id, name, url, price, original_price, in_stock,"
                " present, preorder, first_seen, last_seen, kind, tcg, lang, ptype, set_id)"
                " VALUES(?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?)",
                (store_id, str(ext_id), name, p.get("url"), price, _f(p.get("original_price")),
                 int(bool(p.get("in_stock", True))), fields["preorder"], first_seen, last_seen,
                 fields["kind"], fields["tcg"], fields["lang"], fields["ptype"], fields["set_id"]),
            )
            if not cur.rowcount:
                continue
            listing_id = cur.lastrowid
            for h in p.get("stock_history") or []:
                ts = timeutil.parse(h.get("timestamp"))
                if ts:
                    conn.execute(
                        "INSERT INTO listing_history(listing_id, ts, price, in_stock) VALUES(?,?,?,?)",
                        (listing_id, timeutil.iso(ts), price, int(bool(h.get("in_stock")))),
                    )
            pid = find_or_create_product(conn, c, None)
            if pid:
                conn.execute("UPDATE listings SET product_id=? WHERE id=?", (pid, listing_id))
                touched.add(pid)
            imported += 1
    # The stores' first check in v2 stays a silent baseline (baseline_done=0):
    # v2 scrapes more pages for some of them, and everything newly seen would
    # otherwise be reported as "new". The imported history is kept either way.
    refresh_products(conn, touched)
    logger.info(f"Imported {imported} listing(s) from v1 state for {len(baselined)} store(s)")


def _f(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
