from __future__ import annotations

import base64
import logging
import subprocess
import sys
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from plyer import notification as _plyer_notify
    _PLYER_OK = True
except Exception:
    _plyer_notify = None  # type: ignore[assignment]
    _PLYER_OK = False


def send_notification(title: str, message: str, timeout: int = 10, sound: str | None = None) -> None:
    """Send a desktop notification. Uses WinRT toast on Windows, plyer elsewhere.

    `sound` is a `ms-winsoundevent:...` id (see _SOUNDS below) — ignored on
    the plyer fallback, which doesn't support picking a sound.
    """
    if sys.platform == "win32":
        _send_winrt_toast(title, message, sound)
    elif _PLYER_OK and _plyer_notify is not None:
        try:
            _plyer_notify.notify(title=title[:64], message=message[:256],
                                 app_name="Stock Monitor", timeout=timeout)
        except Exception as e:
            logger.debug(f"plyer notification failed: {e}")


def _send_winrt_toast(title: str, message: str, sound: str | None = None) -> None:
    """Fire a real Windows 10/11 toast notification via PowerShell WinRT."""
    def _esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                  .replace(">", "&gt;").replace('"', "&quot;"))

    # Built-in ms-winsoundevent ids work from an unpackaged Win32 app;
    # a custom .wav would need MSIX packaging, so we stick to these.
    audio_xml = f'<audio src="{_esc(sound)}" />' if sound else ""

    xml = (
        '<toast><visual><binding template="ToastText02">'
        f'<text id="1">{_esc(str(title)[:64])}</text>'
        f'<text id="2">{_esc(str(message)[:256])}</text>'
        '</binding></visual>'
        f'{audio_xml}'
        '</toast>'
    )
    b64xml = base64.b64encode(xml.encode("utf-8")).decode()

    ps = "\n".join([
        "[Windows.UI.Notifications.ToastNotificationManager,"
        " Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null",
        "[Windows.Data.Xml.Dom.XmlDocument,"
        " Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null",
        "$d = New-Object Windows.Data.Xml.Dom.XmlDocument",
        f"$d.LoadXml([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64xml}')))",
        "$t = [Windows.UI.Notifications.ToastNotification]::new($d)",
        "[Windows.UI.Notifications.ToastNotificationManager]"
        "::CreateToastNotifier('Stock Monitor').Show($t)",
    ])
    # Encode script as UTF-16LE for -EncodedCommand (avoids all quoting issues)
    encoded = base64.b64encode(ps.encode("utf-16-le")).decode()
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.debug(f"WinRT toast failed: {e}")

_ICONS = {
    "new_product": "🆕",
    "back_in_stock": "✅",
    "out_of_stock": "❌",
    "price_change": "💰",
}

# Send one grouped summary when a site has this many changes in a single check
_SUMMARY_THRESHOLD = 5

# Built-in Windows toast sound events — distinct per kind of change so you
# can tell them apart without looking at the screen. "price_change" splits
# into increase/decrease since those two are opposite news.
_SOUNDS = {
    "back_in_stock":  "ms-winsoundevent:Notification.IM",
    "new_product":    "ms-winsoundevent:Notification.Mail",
    "price_decrease": "ms-winsoundevent:Notification.Reminder",
    "price_increase": "ms-winsoundevent:Notification.SMS",
    "out_of_stock":   "ms-winsoundevent:Notification.Default",
}

# When a grouped summary spans several event types, pick one sound — the
# most actionable/exciting kind present, checked in this order.
_SOUND_PRIORITY = ["back_in_stock", "new_product", "price_decrease", "price_increase", "out_of_stock"]


def _event_sound_key(event: dict) -> str:
    t = event["type"]
    if t != "price_change":
        return t
    try:
        old = float(event.get("old_price") or 0)
        new = float(event["product"].get("price") or 0)
        if old and new and new > old:
            return "price_increase"
    except (ValueError, TypeError):
        pass
    return "price_decrease"


class Notifier:
    def notify_events(self, site_name: str, events: list[dict]) -> None:
        if not events:
            return
        if len(events) >= _SUMMARY_THRESHOLD:
            self._send_summary(site_name, events)
        else:
            for event in events:
                self._send_single(site_name, event)

    # ---------------------------------------------------------------- Format

    def _format(self, site_name: str, event: dict) -> tuple[str, str]:
        """Return (notification_title, notification_body)."""
        product = event["product"]
        name = product.get("name", "Unknown Product")
        price = product.get("price")
        price_str = f"€{price}" if price else ""
        t = event["type"]

        if t == "new_product":
            stock_label = "IN STOCK" if product.get("in_stock") else "OUT OF STOCK"
            title = f"🆕 New: {name}"
            body = f"[{site_name}] {name} - {price_str} ({stock_label})"
        elif t == "back_in_stock":
            title = "✅ Back in Stock!"
            body = f"[{site_name}] {name} - {price_str} — BACK IN STOCK"
        elif t == "out_of_stock":
            title = "❌ Out of Stock"
            body = f"[{site_name}] {name} — OUT OF STOCK"
        elif t == "price_change":
            old = event.get("old_price", "?")
            title = "💰 Price Change"
            body = f"[{site_name}] {name} — €{old} → {price_str}"
        else:
            title = "Stock change detected"
            body = f"[{site_name}] {t}: {name}"

        return title, body

    # --------------------------------------------------------------- Sending

    def _send_single(self, site_name: str, event: dict) -> None:
        title, body = self._format(site_name, event)
        ts = datetime.now().strftime("%H:%M:%S")
        logger.info(f"[{ts}] {body}")
        self._push(title, body, sound=_SOUNDS.get(_event_sound_key(event)))

    def _send_summary(self, site_name: str, events: list[dict]) -> None:
        counts: dict[str, int] = {}
        for e in events:
            counts[e["type"]] = counts.get(e["type"], 0) + 1

        parts = []
        for t, n in counts.items():
            icon = _ICONS.get(t, "•")
            label = t.replace("_", " ")
            parts.append(f"{icon} {n}x {label}")

        title = f"{site_name}: {len(events)} changes"
        body = " | ".join(parts)
        ts = datetime.now().strftime("%H:%M:%S")
        logger.info(f"[{ts}] SUMMARY [{site_name}]: {body}")

        sound_keys = {_event_sound_key(e) for e in events}
        sound = next((_SOUNDS[k] for k in _SOUND_PRIORITY if k in sound_keys), None)
        self._push(title, body, timeout=20, sound=sound)

        # Log each event individually so the log file has the full detail
        for e in events:
            _, individual = self._format(site_name, e)
            logger.info(f"  └─ {individual}")

    def _push(self, title: str, message: str, timeout: int = 10, sound: str | None = None) -> None:
        send_notification(title, message, timeout, sound=sound)
