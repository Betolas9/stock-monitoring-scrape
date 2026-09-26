"""Link store listings to canonical products.

A canonical product is identified by set + type (+ variant) + language, e.g.
"pokemon-me03-etb" or "onepiece-op13-booster-box-jp". Listings that can't be
classified that precisely stay unmatched and can be linked by hand in the UI.
Manual links (match_mode='manual') and manual "keep unmatched" decisions
(match_mode='none') are never overwritten by the matcher.
"""
from __future__ import annotations

import re
import sqlite3

from .. import db, timeutil
from . import catalog, rules
from .classify import Classification, classify

JACCARD_MIN = 0.5
JACCARD_MIN_NO_SET = 0.75


def product_id_for(c: Classification) -> str:
    parts = [c.set_id or c.tcg, c.ptype]
    if c.variant:
        parts.append(c.variant)
    if c.lang and c.lang != "en":
        parts.append(c.lang)
    return "-".join(p for p in parts if p)


def product_title_for(c: Classification) -> str:
    type_label = rules.TYPE_LABELS.get(c.ptype or "other", c.ptype or "")
    if not c.set_id:
        # set-less product, e.g. "Charizard ex Special Collection"
        title = f"{c.variant.replace('-', ' ').title()} - {type_label}"
        return title + (f" [{c.lang.upper()}]" if c.lang and c.lang != "en" else "")
    s = catalog.get_set(c.set_id)
    if s is None and c.new_set:
        set_part = c.new_set["name"]
    elif s is None:
        set_part = c.set_id or "?"
    elif s.code and s.code.lower() != s.name.lower():
        set_part = f"{s.code} - {s.name}"
    else:
        set_part = s.name
    title = f"{set_part} - {type_label}"
    if c.variant:
        if c.ptype in rules.UNIQUE_TYPES:
            flags = f"-{c.variant}-"
            parts = [label for key, label, _p in rules.UNIQUE_VARIANTS if f"-{key}-" in flags]
            qty = re.search(r"-(\d+)x-", flags)
            if qty:
                parts.insert(0, f"{qty.group(1)}x")
            if parts:
                title += f" ({', '.join(parts)})"
        else:
            title += " - " + c.variant.replace("-", " ").title()
    if c.lang and c.lang != "en":
        title += f" [{c.lang.upper()}]"
    return title


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(filter(None, a.split("-"))), set(filter(None, b.split("-")))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def ensure_set(conn: sqlite3.Connection, new_set: dict) -> None:
    exists = conn.execute("SELECT 1 FROM sets WHERE id=?", (new_set["id"],)).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO sets(id, tcg, code, name, aliases, release_date, date_confirmed, focus, auto_created, created_at)"
            " VALUES(?,?,?,?,?,NULL,0,0,1,?)",
            (new_set["id"], new_set["tcg"], new_set["code"], new_set["name"], "[]", timeutil.iso()),
        )
        catalog.invalidate()


def find_or_create_product(conn: sqlite3.Connection, c: Classification, image: str | None) -> str | None:
    if c.kind != "sealed" or not c.ptype:
        return None
    if not c.set_id:
        # Without a set only distinctive non-unique products can be grouped
        # ("Charizard ex Special Collection"); a bare "Booster Pack" can't.
        if c.ptype in rules.UNIQUE_TYPES or not c.tcg or not c.variant:
            return None
    if c.new_set:
        ensure_set(conn, c.new_set)

    pid = product_id_for(c)
    if conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone():
        return pid

    if c.ptype not in rules.UNIQUE_TYPES:
        if c.set_id:
            candidates = conn.execute(
                "SELECT id, variant FROM products WHERE set_id=? AND type=? AND lang=?",
                (c.set_id, c.ptype, c.lang),
            ).fetchall()
            threshold = JACCARD_MIN
        else:
            candidates = conn.execute(
                "SELECT id, variant FROM products WHERE set_id IS NULL AND tcg=? AND type=? AND lang=?",
                (c.tcg, c.ptype, c.lang),
            ).fetchall()
            threshold = JACCARD_MIN_NO_SET
        best, score = None, 0.0
        for cand in candidates:
            s = _jaccard(c.variant, cand["variant"] or "")
            if s > score:
                best, score = cand["id"], s
        if best and score >= threshold:
            return best

    conn.execute(
        "INSERT INTO products(id, tcg, set_id, type, lang, variant, title, image, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (pid, c.tcg, c.set_id, c.ptype, c.lang, c.variant, product_title_for(c), image, timeutil.iso()),
    )
    return pid


def classify_fields(name: str, meta: str | None) -> tuple[Classification, dict]:
    c = classify(name, meta or "")
    return c, {
        "kind": c.kind, "tcg": c.tcg, "lang": c.lang, "ptype": c.ptype,
        "set_id": c.set_id, "preorder": int(c.preorder),
    }


def rematch_listing(conn: sqlite3.Connection, listing: dict) -> str | None:
    """Re-classify one listing and (if in auto mode) re-link it. Returns the
    product id it ends up linked to."""
    c, fields = classify_fields(listing["name"], listing.get("meta"))
    product_id = listing.get("product_id")
    if listing.get("match_mode", "auto") == "auto":
        product_id = find_or_create_product(conn, c, listing.get("image"))
    conn.execute(
        "UPDATE listings SET kind=:kind, tcg=:tcg, lang=:lang, ptype=:ptype, set_id=:set_id,"
        " preorder=:preorder, product_id=:pid WHERE id=:id",
        {**fields, "pid": product_id, "id": listing["id"]},
    )
    return product_id


def rematch_all(conn: sqlite3.Connection, only_unmatched: bool = False) -> dict:
    where = "WHERE match_mode='auto'" + (" AND product_id IS NULL" if only_unmatched else "")
    listings = db.rows(conn.execute(f"SELECT id, name, meta, image, product_id, match_mode FROM listings {where}"))
    touched: set[str] = set()
    for listing in listings:
        old = listing["product_id"]
        new = rematch_listing(conn, listing)
        if old:
            touched.add(old)
        if new:
            touched.add(new)
    cleanup_orphans(conn)
    refresh_products(conn, touched)
    return {"listings": len(listings), "products": len(touched)}


def cleanup_orphans(conn: sqlite3.Connection) -> None:
    """Drop auto-created products that lost all their listings (unless
    favourited or edited by hand)."""
    conn.execute(
        "DELETE FROM products WHERE manual=0"
        " AND id NOT IN (SELECT product_id FROM listings WHERE product_id IS NOT NULL)"
        " AND id NOT IN (SELECT product_id FROM favorites)"
    )


def refresh_products(conn: sqlite3.Connection, product_ids) -> None:
    """Recompute the denormalised price/stock stats of these products."""
    ids = [p for p in set(product_ids) if p]
    if not ids:
        return
    month_ago = timeutil.ago(days=30)
    for pid in ids:
        agg = conn.execute(
            "SELECT COUNT(DISTINCT store_id) AS stores, COALESCE(SUM(in_stock),0) AS in_stock,"
            " MIN(CASE WHEN in_stock=1 THEN price END) AS best, MIN(price) AS min_price,"
            " MAX(COALESCE(last_change, first_seen)) AS last_change"
            " FROM listings WHERE product_id=? AND present=1",
            (pid,),
        ).fetchone()
        best_store = None
        if agg["best"] is not None:
            r = conn.execute(
                "SELECT store_id FROM listings WHERE product_id=? AND present=1 AND in_stock=1 AND price=?"
                " ORDER BY last_seen DESC LIMIT 1",
                (pid, agg["best"]),
            ).fetchone()
            best_store = r["store_id"] if r else None

        # Cheapest listed price 30 days ago: the last known price of each
        # listing at that moment
        then = conn.execute(
            "SELECT MIN(h.price) AS p FROM listing_history h"
            " JOIN listings l ON l.id=h.listing_id"
            " WHERE l.product_id=? AND h.ts<=? AND h.price IS NOT NULL"
            " AND h.ts = (SELECT MAX(h2.ts) FROM listing_history h2 WHERE h2.listing_id=h.listing_id AND h2.ts<=?)",
            (pid, month_ago, month_ago),
        ).fetchone()["p"]
        change = None
        if then and agg["min_price"]:
            change = round((agg["min_price"] - then) / then * 100, 1)

        # Back-fill the image from any listing if the product has none
        conn.execute(
            "UPDATE products SET best_price=?, best_store=?, min_price=?, store_count=?, in_stock_count=?,"
            " change_30d=?, last_change=?,"
            " image=COALESCE(image, (SELECT image FROM listings WHERE product_id=? AND image IS NOT NULL LIMIT 1))"
            " WHERE id=?",
            (agg["best"], best_store, agg["min_price"], agg["stores"], agg["in_stock"], change,
             agg["last_change"], pid, pid),
        )
