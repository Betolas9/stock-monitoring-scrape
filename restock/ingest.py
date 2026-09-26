"""Apply one successful store scrape to the database.

Diffs the scrape against the store's known listings, records price/stock
history, links new listings to canonical products and returns the change
events. The first scrape of a store is a silent baseline (no events).
"""
from __future__ import annotations

import html
import logging
import sqlite3

from scrapers import ScrapeError

from . import db, timeutil
from .matching import classify_fields, find_or_create_product, refresh_products
from .matching.matcher import ensure_set

logger = logging.getLogger(__name__)

# A scrape returning far fewer products than last time is almost always a
# broken page/partial response, not a mass sell-out — refuse it.
SUSPICIOUS_MIN_PREVIOUS = 20
SUSPICIOUS_RATIO = 0.3


def _price(v) -> float | None:
    try:
        return round(float(v), 2) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def keep_listing(fields: dict, require_tcg: bool = False) -> bool:
    """Only TCG products are tracked: singles, breaks and non-TCG merch are
    dropped. Sealed products are kept even when the game isn't recognised —
    unless the store sets the `require_tcg` option (generalist shops, where
    "booster" can be a face serum)."""
    if fields["kind"] in ("single", "service", "merch"):
        return False
    if require_tcg and not fields["tcg"]:
        return False
    return fields["kind"] == "sealed" or fields["tcg"] is not None


def ingest(conn: sqlite3.Connection, store: dict, scraped: dict, ignore_keywords: list[str]) -> list[dict]:
    now = timeutil.iso()
    ignore = [k.lower() for k in ignore_keywords if k]
    baseline = not store["baseline_done"]
    require_tcg = bool((db.jload(store.get("options"), {}) or {}).get("require_tcg"))

    # ---- classify & filter the fresh scrape
    fresh: dict[str, tuple[dict, dict, object]] = {}
    for ext_id, p in scraped.items():
        name = html.unescape(p.get("name") or "").strip()
        if not name or any(k in name.lower() for k in ignore):
            continue
        c, fields = classify_fields(name, p.get("meta"))
        if keep_listing(fields, require_tcg):
            fresh[str(ext_id)] = ({**p, "name": name}, fields, c)

    existing = {
        r["external_id"]: dict(r)
        for r in conn.execute("SELECT * FROM listings WHERE store_id=?", (store["id"],))
    }
    previously_present = sum(1 for r in existing.values() if r["present"])
    if not fresh and previously_present:
        raise ScrapeError(f"0 TCG products found (had {previously_present}) — page layout changed or blocked?")
    if previously_present >= SUSPICIOUS_MIN_PREVIOUS and len(fresh) < previously_present * SUSPICIOUS_RATIO:
        raise ScrapeError(
            f"only {len(fresh)} TCG products found (had {previously_present}) — refusing a probably partial scrape"
        )

    events: list[dict] = []
    touched_products: set[str] = set()

    def event(kind: str, listing: dict, **extra) -> None:
        if baseline:
            return
        events.append({
            "type": kind, "store_id": store["id"], "listing_id": listing["id"],
            "product_id": listing.get("product_id"), "title": listing["name"], "url": listing.get("url"),
            "image": listing.get("image"), "price": listing.get("price"), "in_stock": listing.get("in_stock"),
            "set_id": listing.get("set_id"), "tcg": listing.get("tcg"), "kind": listing.get("kind"),
            "preorder": listing.get("preorder"), **extra,
        })

    for ext_id, (p, fields, c) in fresh.items():
        price = _price(p.get("price"))
        orig = _price(p.get("original_price"))
        in_stock = int(bool(p.get("in_stock", True)))
        old = existing.get(ext_id)

        if old is None:
            if c.new_set:
                ensure_set(conn, c.new_set)
            product_id = find_or_create_product(conn, c, p.get("image"))
            cur = conn.execute(
                "INSERT INTO listings(store_id, external_id, name, url, image, meta, price, original_price,"
                " in_stock, present, preorder, first_seen, last_seen, last_change, kind, tcg, lang, ptype,"
                " set_id, product_id) VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?)",
                (store["id"], ext_id, p["name"], p.get("url"), p.get("image"), p.get("meta"), price, orig,
                 in_stock, fields["preorder"], now, now, now, fields["kind"], fields["tcg"], fields["lang"],
                 fields["ptype"], fields["set_id"], product_id),
            )
            listing = {"id": cur.lastrowid, "name": p["name"], "url": p.get("url"), "image": p.get("image"),
                       "price": price, "in_stock": in_stock, "product_id": product_id, **fields}
            conn.execute(
                "INSERT INTO listing_history(listing_id, ts, price, in_stock) VALUES(?,?,?,?)",
                (listing["id"], now, price, in_stock),
            )
            if product_id:
                touched_products.add(product_id)
            event("new_listing", listing)
            continue

        # ---- known listing: detect changes
        listing = dict(old)
        changed = False
        product_id = old["product_id"]
        if old["name"] != p["name"] and old["match_mode"] == "auto":
            if c.new_set:
                ensure_set(conn, c.new_set)
            product_id = find_or_create_product(conn, c, p.get("image"))
        if product_id != old["product_id"]:
            if old["product_id"]:
                touched_products.add(old["product_id"])
        listing.update({"name": p["name"], "url": p.get("url") or old["url"], "image": p.get("image") or old["image"],
                        "price": price, "in_stock": in_stock, "product_id": product_id, **fields})

        was_available = bool(old["in_stock"]) and bool(old["present"])
        if in_stock and not was_available:
            event("back_in_stock", listing, old_price=old["price"])
            changed = True
        elif not in_stock and was_available:
            event("out_of_stock", listing, old_price=old["price"])
            changed = True
        if price is not None and old["price"] is not None and abs(price - old["price"]) >= 0.01:
            event("price_drop" if price < old["price"] else "price_rise", listing, old_price=old["price"])
            changed = True
        elif price is not None and old["price"] is None:
            changed = True

        conn.execute(
            "UPDATE listings SET name=?, url=?, image=?, meta=?, price=?, original_price=?, in_stock=?, present=1,"
            " preorder=?, last_seen=?, last_change=COALESCE(?, last_change), kind=?, tcg=?, lang=?, ptype=?,"
            " set_id=?, product_id=? WHERE id=?",
            (listing["name"], listing["url"], listing["image"], p.get("meta"), price, orig, in_stock,
             fields["preorder"], now, now if changed else None, fields["kind"], fields["tcg"], fields["lang"],
             fields["ptype"], fields["set_id"], product_id, old["id"]),
        )
        if changed or not old["present"]:
            conn.execute(
                "INSERT INTO listing_history(listing_id, ts, price, in_stock) VALUES(?,?,?,?)",
                (old["id"], now, price, in_stock),
            )
        if product_id and (changed or not old["present"] or product_id != old["product_id"]):
            touched_products.add(product_id)

    # ---- listings that disappeared from the store count as sold out
    scraped_ids = {str(k) for k in scraped}
    for ext_id, old in existing.items():
        if ext_id in fresh or not old["present"]:
            continue
        if ext_id in scraped_ids:
            # Still on sale, but no longer tracked (ignore keyword added,
            # classification rules changed): drop it quietly — it didn't sell out.
            conn.execute("UPDATE listings SET present=0 WHERE id=?", (old["id"],))
            if old["product_id"]:
                touched_products.add(old["product_id"])
            continue
        conn.execute(
            "UPDATE listings SET present=0, in_stock=0, last_change=? WHERE id=?", (now, old["id"]),
        )
        conn.execute(
            "INSERT INTO listing_history(listing_id, ts, price, in_stock) VALUES(?,?,?,0)",
            (old["id"], now, old["price"]),
        )
        if old["in_stock"]:
            event("out_of_stock", {**old, "in_stock": 0}, old_price=old["price"])
        if old["product_id"]:
            touched_products.add(old["product_id"])

    refresh_products(conn, touched_products)

    # ---- persist events
    for e in events:
        cur = conn.execute(
            "INSERT INTO events(ts, type, store_id, listing_id, product_id, title, url, image, price, old_price,"
            " in_stock) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (now, e["type"], e["store_id"], e["listing_id"], e["product_id"], e["title"], e["url"], e["image"],
             e["price"], e.get("old_price"), e["in_stock"]),
        )
        e["id"] = cur.lastrowid
        e["ts"] = now

    if baseline:
        logger.info(f"[{store['id']}] baseline: {len(fresh)} TCG product(s) recorded silently")
    return events
