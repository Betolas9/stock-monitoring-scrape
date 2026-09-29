"""Native Windows toasts via a PowerShell WinRT snippet (plyer is unreliable
for real Action Center toasts on Windows)."""
from __future__ import annotations

import base64
import subprocess
import sys

from .errors import NotifyError
from .messages import price_line

# Built-in ms-winsoundevent ids work from an unpackaged Win32 app
_SOUNDS = {
    "back_in_stock": "ms-winsoundevent:Notification.IM",
    "new_listing":   "ms-winsoundevent:Notification.Mail",
    "price_drop":    "ms-winsoundevent:Notification.Reminder",
    "out_of_stock":  "ms-winsoundevent:Notification.Default",
}


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def toast(title: str, message: str, sound: str | None = None) -> None:
    if sys.platform != "win32":
        raise NotifyError("Windows toasts are only available on Windows")
    audio_xml = f'<audio src="{_esc(sound)}" />' if sound else ""
    xml = (
        '<toast><visual><binding template="ToastText02">'
        f'<text id="1">{_esc(str(title)[:64])}</text>'
        f'<text id="2">{_esc(str(message)[:256])}</text>'
        "</binding></visual>"
        f"{audio_xml}"
        "</toast>"
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
        "::CreateToastNotifier('restock-monitoring').Show($t)",
    ])
    encoded = base64.b64encode(ps.encode("utf-16-le")).decode()
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        raise NotifyError(f"could not start PowerShell: {e}") from e


def send(payload: dict, cfg: dict, target: str | None = None) -> None:
    items = payload.get("items") or []
    if payload["kind"] != "events":
        toast(payload["title"], payload.get("text", ""))
    elif len(items) == 1:
        it = items[0]
        toast(payload["title"], f"{it.get('product_title') or it['title']}\n{price_line(it)}", _SOUNDS.get(it["type"]))
    else:
        body = "\n".join(f"• {(i.get('product_title') or i['title'])[:50]}" for i in items[:5])
        if len(items) > 5:
            body += f"\n… and {len(items) - 5} more"
        toast(payload["title"], body, _SOUNDS.get(items[0]["type"]))
