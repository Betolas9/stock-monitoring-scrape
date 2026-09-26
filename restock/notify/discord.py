from __future__ import annotations

from . import net
from .errors import NotifyError, RetryLater
from .messages import EVENT_LABELS, REASON_LABELS, money, price_line

_COLORS = {
    "new_listing": 0x3B82F6, "back_in_stock": 0x22C55E, "price_drop": 0xF59E0B,
    "out_of_stock": 0xEF4444, "price_rise": 0x94A3B8, "target": 0xE11D48,
}
_MAX_EMBEDS = 10


def _embed(item: dict) -> dict:
    emoji, label = EVENT_LABELS.get(item["type"], ("🔔", item["type"]))
    r_emoji, r_label = REASON_LABELS.get(item.get("reason") or "", ("", ""))
    embed = {
        "title": (item.get("product_title") or item["title"])[:250],
        "description": f"{emoji} **{label}** · {item['store']}\n💶 {price_line(item)}"
                       + (f"\n{r_emoji} {r_label}" if r_label else ""),
        "color": _COLORS.get("target" if item.get("reason") == "target" else item["type"], 0x64748B),
    }
    if item.get("url"):
        embed["url"] = item["url"]
    if item.get("image"):
        embed["thumbnail"] = {"url": item["image"]}
    if item.get("product_title") and item["product_title"] != item["title"]:
        embed["footer"] = {"text": item["title"][:200]}
    return embed


def _post(url: str, body: dict) -> None:
    r = net.post(url, json=body, params={"wait": "true"}, timeout=20)
    if r.status_code == 429:
        try:
            wait = float(r.json().get("retry_after", 5))
        except ValueError:
            wait = 5.0
        raise RetryLater(wait)
    if r.status_code >= 300:
        raise NotifyError(f"Discord HTTP {r.status_code}: {r.text[:200]}")


def send(payload: dict, cfg: dict) -> None:
    url = (cfg.get("webhook_url") or "").strip()
    if not url:
        raise NotifyError("Discord webhook URL not configured")
    mention = (cfg.get("mention") or "").strip() or None
    base = {"username": "restock-monitoring"}

    if payload["kind"] != "events":
        _post(url, {**base, "content": f"**{payload['title']}**\n{payload.get('text', '')}"})
        return

    items = payload["items"]
    if len(items) <= _MAX_EMBEDS:
        _post(url, {**base, "content": mention, "embeds": [_embed(i) for i in items]})
        return

    # Big summaries: compact text list, split under Discord's 2000-char limit
    lines = []
    for it in items:
        name = (it.get("product_title") or it["title"])[:80]
        link = f"[{name}](<{it['url']}>)" if it.get("url") else name
        lines.append(f"{EVENT_LABELS.get(it['type'], ('•', ''))[0]} {link} — {money(it['price'])}")
    chunk = f"**🔔 {payload['title']}**" + (f" {mention}" if mention else "")
    for line in lines:
        if len(chunk) + len(line) + 1 > 1900:
            _post(url, {**base, "content": chunk})
            chunk = ""
        chunk += "\n" + line
    if chunk:
        _post(url, {**base, "content": chunk})
