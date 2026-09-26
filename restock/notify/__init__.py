"""Notification queue + delivery worker.

Every message is first written to the `notifications` table (one row per
enabled channel), then delivered by a background thread that retries
failures with backoff. Nothing is lost if a channel is down or the app
restarts, and every attempt is visible in the Activity page.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time

from .. import db, settings, timeutil
from . import discord, telegram, windows
from .errors import NotifyError, RetryLater
from .messages import build_event_payloads, item_from_event, summary_text

logger = logging.getLogger(__name__)

SENDERS = {"telegram": telegram.send, "discord": discord.send, "windows": windows.send}
RETRY_DELAYS = [15, 60, 300, 900, 1800]   # seconds between attempts; then give up
MAX_AGE_S = 6 * 3600                      # stale alerts are useless — stop retrying after this


def enabled_channels(cfg: dict) -> list[str]:
    ch = cfg["channels"]
    out = []
    if ch["telegram"]["enabled"] and ch["telegram"]["bot_token"] and ch["telegram"]["chat_id"]:
        out.append("telegram")
    if ch["discord"]["enabled"] and ch["discord"]["webhook_url"]:
        out.append("discord")
    if ch["windows"]["enabled"]:
        out.append("windows")
    return out


def enqueue(conn: sqlite3.Connection, payload: dict, channels: list[str] | None = None) -> int:
    cfg = settings.get()
    channels = channels if channels is not None else enabled_channels(cfg)
    now = timeutil.iso()
    for ch in channels:
        conn.execute(
            "INSERT INTO notifications(created_at, channel, status, attempts, next_attempt_at, summary, payload)"
            " VALUES(?,?,'pending',0,?,?,?)",
            (now, ch, now, summary_text(payload), db.jdump(payload)),
        )
    return len(channels)


def enqueue_events(conn: sqlite3.Connection, store_name: str, events: list[dict]) -> None:
    if not events:
        return
    cfg = settings.get()
    pids = {e["product_id"] for e in events if e.get("product_id")}
    titles: dict[str, str] = {}
    if pids:
        q = ",".join("?" * len(pids))
        titles = {r["id"]: r["title"] for r in conn.execute(f"SELECT id, title FROM products WHERE id IN ({q})", tuple(pids))}
    items = [item_from_event(e, store_name, titles.get(e.get("product_id") or "")) for e in events]
    for payload in build_event_payloads(store_name, items, int(cfg["alerts"]["group_threshold"])):
        enqueue(conn, payload)


def send_now(channel: str, payload: dict, cfg: dict | None = None) -> None:
    """Synchronous send (used by the settings page "Send test" buttons)."""
    cfg = cfg or settings.get()
    SENDERS[channel](payload, cfg["channels"][channel])


class Dispatcher:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="notify-dispatcher", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                logger.exception("notification dispatcher error")
            self._wake.wait(2)
            self._wake.clear()

    def _tick(self) -> None:
        now = timeutil.iso()
        with db.read() as conn:
            due = db.rows(conn.execute(
                "SELECT * FROM notifications WHERE status='pending' AND (next_attempt_at IS NULL OR next_attempt_at<=?)"
                " ORDER BY id LIMIT 20",
                (now,),
            ))
        cfg = settings.get()
        for n in due:
            if self._stop.is_set():
                return
            self._deliver(n, cfg)

    def _deliver(self, n: dict, cfg: dict) -> None:
        payload = db.jload(n["payload"], {})
        attempts = n["attempts"] + 1
        try:
            SENDERS[n["channel"]](payload, cfg["channels"][n["channel"]])
        except Exception as e:  # noqa: BLE001 — any failure is retried/logged, never fatal
            created = timeutil.parse(n["created_at"])
            too_old = created and (timeutil.now() - created).total_seconds() > MAX_AGE_S
            if isinstance(e, RetryLater):
                delay = e.seconds + 1
            else:
                delay = RETRY_DELAYS[min(attempts - 1, len(RETRY_DELAYS) - 1)]
            give_up = too_old or (attempts > len(RETRY_DELAYS) and not isinstance(e, RetryLater))
            err = str(e) if isinstance(e, NotifyError) else f"{type(e).__name__}: {e}"
            with db.tx() as conn:
                conn.execute(
                    "UPDATE notifications SET attempts=?, last_error=?, status=?, next_attempt_at=? WHERE id=?",
                    (attempts, err[:500], "failed" if give_up else "pending", timeutil.later(delay), n["id"]),
                )
            logger.warning(f"{n['channel']} notification #{n['id']} failed (attempt {attempts}): {err}")
            return
        with db.tx() as conn:
            conn.execute(
                "UPDATE notifications SET attempts=?, status='sent', sent_at=?, last_error=NULL WHERE id=?",
                (attempts, timeutil.iso(), n["id"]),
            )
        # Telegram allows ~1 msg/s per chat; stay well under it
        time.sleep(0.4)


__all__ = ["Dispatcher", "enqueue", "enqueue_events", "enabled_channels", "send_now", "telegram"]
