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


def send_notification(title: str, message: str, timeout: int = 10) -> None:
    """Send a desktop notification. Uses WinRT toast on Windows, plyer elsewhere."""
    if sys.platform == "win32":
        _send_winrt_toast(title, message)
    elif _PLYER_OK and _plyer_notify is not None:
        try:
            _plyer_notify.notify(title=title[:64], message=message[:256],
                                 app_name="Stock Monitor", timeout=timeout)
        except Exception as e:
            logger.debug(f"plyer notification failed: {e}")


def _send_winrt_toast(title: str, message: str) -> None:
    """Fire a real Windows 10/11 toast notification via PowerShell WinRT."""
    def _esc(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                  .replace(">", "&gt;").replace('"', "&quot;"))

    xml = (
        '<toast><visual><binding template="ToastText02">'
        f'<text id="1">{_esc(str(title)[:64])}</text>'
        f'<text id="2">{_esc(str(message)[:256])}</text>'
        '</binding></visual></toast>'
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
        self._push(title, body)

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
        self._push(title, body, timeout=20)

        # Log each event individually so the log file has the full detail
        for e in events:
            _, individual = self._format(site_name, e)
            logger.info(f"  └─ {individual}")

    def _push(self, title: str, message: str, timeout: int = 10) -> None:
        send_notification(title, message, timeout)
