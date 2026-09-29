from __future__ import annotations

import html

from . import net
from .errors import NotifyError, RetryLater
from .messages import REASON_LABELS, price_line

API = "https://api.telegram.org/bot{token}/{method}"
_MAX_TEXT = 4000      # Telegram's hard limit is 4096
_MAX_CAPTION = 1000   # … and 1024 for photo captions


def _call(token: str, method: str, payload: dict) -> dict:
    r = net.post(API.format(token=token, method=method), json=payload, timeout=20)
    try:
        data = r.json()
    except ValueError:
        raise NotifyError(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code == 429:
        raise RetryLater(float((data.get("parameters") or {}).get("retry_after", 30)))
    if not data.get("ok"):
        raise NotifyError(f"Telegram: {data.get('description', r.status_code)}")
    return data.get("result") or {}


def _item_html(item: dict, with_header: bool) -> str:
    esc = html.escape
    title = esc(item.get("product_title") or item["title"])
    link = f'<a href="{esc(item["url"])}">{title}</a>' if item.get("url") else f"<b>{title}</b>"
    lines = [link, f"💶 {esc(price_line(item))}"]
    if item.get("product_title") and item["product_title"] != item["title"]:
        lines.insert(1, f"<i>{esc(item['title'])}</i>")
    reason = REASON_LABELS.get(item.get("reason") or "", ("", ""))
    if reason[1]:
        lines.append(f"{reason[0]} {esc(reason[1])}")
    return "\n".join(lines)


def render(payload: dict) -> list[str]:
    esc = html.escape
    if payload["kind"] != "events":
        return [f"<b>{esc(payload['title'])}</b>\n{esc(payload.get('text', ''))}"]
    items = payload["items"]
    if len(items) == 1:
        return [f"<b>{esc(payload['title'])}</b>\n{_item_html(items[0], False)}"]
    chunks, current = [], f"<b>🔔 {esc(payload['title'])}</b>"
    for it in items:
        emoji = {"new_listing": "🆕", "back_in_stock": "✅", "price_drop": "📉", "out_of_stock": "❌"}.get(it["type"], "•")
        title = esc((it.get("product_title") or it["title"])[:90])
        name = f'<a href="{esc(it["url"])}">{title}</a>' if it.get("url") else title
        line = f"\n{emoji} {name} — {esc(price_line(it))}"
        if len(current) + len(line) > _MAX_TEXT:
            chunks.append(current)
            current = f"<b>🔔 {esc(payload['title'])} (cont.)</b>"
        current += line
    chunks.append(current)
    return chunks


def recipients(cfg: dict) -> list[dict]:
    return [r for r in cfg.get("recipients") or [] if r.get("enabled", True) and str(r.get("id", "")).strip()]


def send(payload: dict, cfg: dict, target: str | None = None) -> None:
    token = cfg.get("bot_token", "").strip()
    chat_id = str(target or "").strip()
    if not token or not chat_id:
        raise NotifyError("Telegram bot token / recipient not configured")
    items = payload.get("items") or []
    texts = render(payload)
    # Single item with a picture → photo message (much nicer on the phone)
    if len(items) == 1 and items[0].get("image") and len(texts[0]) <= _MAX_CAPTION:
        try:
            _call(token, "sendPhoto", {"chat_id": chat_id, "photo": items[0]["image"],
                                       "caption": texts[0], "parse_mode": "HTML"})
            return
        except RetryLater:
            raise
        except NotifyError:
            pass  # Telegram couldn't fetch the image (webp, hotlink protection…) → plain text
    for text in texts:
        _call(token, "sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                     "disable_web_page_preview": len(items) != 1})


def detect_chat_ids(token: str) -> list[dict]:
    """Chats that recently messaged the bot — used by the settings page to
    fill in the chat id after the user sends /start to their bot."""
    result = _call(token.strip(), "getUpdates", {"timeout": 0, "allowed_updates": ["message", "channel_post"]})
    chats: dict[str, dict] = {}
    for upd in result if isinstance(result, list) else []:
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            name = chat.get("title") or " ".join(x for x in [chat.get("first_name"), chat.get("last_name")] if x) \
                or chat.get("username") or str(chat["id"])
            chats[str(chat["id"])] = {"id": str(chat["id"]), "name": name, "type": chat.get("type")}
    return list(chats.values())


def bot_info(token: str) -> dict:
    return _call(token.strip(), "getMe", {})
