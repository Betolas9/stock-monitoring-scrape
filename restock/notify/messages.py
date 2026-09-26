"""Channel-independent notification payloads.

payload = {
  "kind":  "events" | "system" | "test",
  "title": short headline,
  "items": [ {type, title, product_title, url, image, price, old_price, store, reason, preorder, in_stock} ],
  "text":  free text (system/test messages)
}
"""
from __future__ import annotations

EVENT_LABELS = {
    "new_listing":     ("🆕", "New"),
    "back_in_stock":   ("✅", "Back in stock"),
    "out_of_stock":    ("❌", "Sold out"),
    "price_drop":      ("📉", "Price drop"),
    "price_rise":      ("📈", "Price up"),
    "store_failing":   ("⚠️", "Store failing"),
    "store_recovered": ("🔧", "Store recovered"),
}

REASON_LABELS = {
    "target":   ("🎯", "Target price"),
    "favorite": ("⭐", "Favourite"),
    "focus":    ("🔥", "Focus release"),
    "general":  ("", ""),
}


def money(v) -> str:
    if v is None:
        return "?"
    return f"{v:,.2f} €".replace(",", " ").replace(".", ",")


def item_from_event(e: dict, store_name: str, product_title: str | None) -> dict:
    return {
        "type": e["type"], "title": e.get("title") or "", "product_title": product_title,
        "url": e.get("url"), "image": e.get("image"), "price": e.get("price"),
        "old_price": e.get("old_price"), "store": store_name, "reason": e.get("alert_reason"),
        "preorder": bool(e.get("preorder")), "in_stock": bool(e.get("in_stock")),
    }


def build_event_payloads(store_name: str, items: list[dict], group_threshold: int) -> list[dict]:
    """One payload per item, or one summary when a check produced many."""
    if not items:
        return []
    # Target-price and favourite hits always get their own message
    priority = [i for i in items if i["reason"] in ("target", "favorite")]
    rest = [i for i in items if i["reason"] not in ("target", "favorite")]
    payloads = [{"kind": "events", "title": headline(i), "items": [i]} for i in priority]
    if len(rest) >= max(2, group_threshold):
        payloads.append({"kind": "events", "title": f"{store_name}: {len(rest)} updates", "items": rest})
    else:
        payloads += [{"kind": "events", "title": headline(i), "items": [i]} for i in rest]
    return payloads


def headline(item: dict) -> str:
    emoji, label = EVENT_LABELS.get(item["type"], ("🔔", item["type"]))
    r_emoji, r_label = REASON_LABELS.get(item.get("reason") or "", ("", ""))
    prefix = f"{r_emoji} " if r_emoji else ""
    return f"{prefix}{emoji} {label} · {item['store']}"


def price_line(item: dict) -> str:
    line = money(item["price"])
    if item.get("old_price") and item["type"] in ("price_drop", "price_rise", "back_in_stock") \
            and item["old_price"] != item["price"]:
        line += f" (was {money(item['old_price'])})"
    if item.get("preorder"):
        line += " · pre-order"
    if not item.get("in_stock") and item["type"] != "out_of_stock":
        line += " · not buyable yet"
    return line


def summary_text(payload: dict) -> str:
    """Plain one-line summary, used for the notifications log."""
    if payload.get("items"):
        first = payload["items"][0]
        more = f" (+{len(payload['items']) - 1})" if len(payload["items"]) > 1 else ""
        return f"{payload['title']} — {first['title']} {money(first['price'])}{more}"
    return f"{payload.get('title', '')} — {payload.get('text', '')}"[:300]
