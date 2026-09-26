"""Decide which change events are worth a notification.

Three layers, strongest first:
  target    — a favourite at or below its target price (and buyable)
  favorite  — restock / price drop / new store for a favourited product
  focus     — anything happening to a product of a "focus" set (calendar)
  general   — new listings / restocks / drops for the configured TCGs
Price rises never notify. Out-of-stock only notifies for favourites, when
alerts.out_of_stock is on.
"""
from __future__ import annotations

import sqlite3

REASON_ORDER = ["target", "favorite", "focus", "general"]


def _drop_pct(e: dict) -> float:
    if not e.get("old_price") or e.get("price") is None:
        return 0.0
    return (e["old_price"] - e["price"]) / e["old_price"] * 100


def evaluate(conn: sqlite3.Connection, events: list[dict], cfg: dict) -> list[dict]:
    """Annotates each event with 'alert_reason' (or None) and returns the
    events that should notify."""
    if not events:
        return []
    a = cfg["alerts"]
    product_ids = {e["product_id"] for e in events if e.get("product_id")}
    favorites: dict[str, dict] = {}
    if product_ids:
        q = ",".join("?" * len(product_ids))
        favorites = {
            r["product_id"]: dict(r)
            for r in conn.execute(f"SELECT * FROM favorites WHERE product_id IN ({q})", tuple(product_ids))
        }
    focus_sets = {r["id"] for r in conn.execute("SELECT id FROM sets WHERE focus=1")}

    out = []
    for e in events:
        reason = _reason(e, favorites.get(e.get("product_id") or ""), focus_sets, a)
        e["alert_reason"] = reason
        if reason:
            conn.execute("UPDATE events SET alert_reason=? WHERE id=?", (reason, e["id"]))
            out.append(e)
    # A restock at a new price is one piece of news, not two messages: the
    # restock alert already shows "(was …)".
    restocked = {e["listing_id"] for e in out if e["type"] in ("back_in_stock", "new_listing")}
    return [e for e in out if not (e["type"] == "price_drop" and e["listing_id"] in restocked)]


def _reason(e: dict, fav: dict | None, focus_sets: set[str], a: dict) -> str | None:
    t = e["type"]
    if t == "price_rise":
        return None
    buyable = bool(e.get("in_stock"))
    drop = _drop_pct(e)
    big_drop = t == "price_drop" and drop >= float(a.get("min_drop_pct", 0))

    if fav:
        target = fav.get("target_price")
        if target is not None and buyable and e.get("price") is not None and e["price"] <= target \
                and t in ("new_listing", "back_in_stock", "price_drop"):
            return "target"
        if t == "back_in_stock" and fav["notify_restock"]:
            return "favorite"
        if t == "price_drop" and fav["notify_price"] and big_drop and buyable:
            return "favorite"
        if t == "new_listing" and fav["notify_new_store"]:
            return "favorite"
        if t == "out_of_stock" and a.get("out_of_stock"):
            return "favorite"

    if t == "out_of_stock":
        return None

    if e.get("set_id") and e["set_id"] in focus_sets and e.get("kind") == "sealed":
        f = a["focus"]
        if (t == "new_listing" and f["new_listing"]) or (t == "back_in_stock" and f["restock"]) \
                or (t == "price_drop" and f["price_drop"] and big_drop and buyable):
            return "focus"

    g = a["general"]
    if e.get("tcg") not in (g.get("tcgs") or []):
        return None
    kind = e.get("kind")
    if kind == "accessory" and not g.get("include_accessories"):
        return None
    # "other" = listings the matcher couldn't classify (often merch named
    # after a game, sometimes a product type it doesn't know yet)
    if kind not in ("sealed", "accessory") and not g.get("include_other"):
        return None
    if t == "new_listing" and g["new_listing"] and (buyable or e.get("preorder")):
        return "general"
    if t == "back_in_stock" and g["restock"]:
        return "general"
    if t == "price_drop" and g["price_drop"] and big_drop and buyable:
        return "general"
    return None
