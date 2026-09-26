"""Grouped store-health alerts.

Store failures/recoveries are collected for a short window and sent as one
message, so a network hiccup that breaks 60 stores at once produces one
"60 stores failing — network problem?" alert instead of 60 (and one
"working again" message afterwards instead of 60 more). A store that fails
and recovers within the same window is not reported at all.
"""
from __future__ import annotations

import threading
import time

from . import db, notify, settings

WINDOW_S = 60          # collect changes for this long before sending
MAX_NAMES = 25         # store names listed in one message


class HealthReporter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failing: dict[str, tuple[str, str, int]] = {}   # id → (name, error, failures)
        self._recovered: dict[str, str] = {}                  # id → name
        self._first_at: float | None = None
        # stores whose "failing" alert was actually sent (only those get a
        # "working again"); restored from the DB so it survives restarts
        with db.read() as conn:
            self._reported: set[str] = {r["id"] for r in conn.execute("SELECT id FROM stores WHERE failure_alerted=1")}

    def failing(self, store_id: str, name: str, error: str, failures: int) -> None:
        with self._lock:
            self._recovered.pop(store_id, None)
            self._failing[store_id] = (name, error, failures)
            self._first_at = self._first_at or time.monotonic()

    def recovered(self, store_id: str, name: str) -> None:
        with self._lock:
            if self._failing.pop(store_id, None) is not None:
                return  # failed and recovered within one window: nothing to tell
            if store_id not in self._reported:
                return  # its failure was never announced
            self._recovered[store_id] = name
            self._first_at = self._first_at or time.monotonic()

    def flush_if_due(self) -> None:
        with self._lock:
            if self._first_at is None or time.monotonic() - self._first_at < WINDOW_S:
                return
            failing, recovered = self._failing, self._recovered
            self._failing, self._recovered, self._first_at = {}, {}, None
            cfg = settings.get()["alerts"]["store_health"]
            if not cfg["enabled"]:
                self._reported.clear()
                return
            self._reported |= set(failing)
            self._reported -= set(recovered)
        payloads = []
        if failing:
            payloads.append(_failing_payload(failing))
        if recovered and cfg["notify_recovered"]:
            payloads.append(_recovered_payload(recovered))
        if payloads:
            with db.tx() as conn:
                for p in payloads:
                    notify.enqueue(conn, p)


def _names(names: list[str]) -> str:
    names = sorted(names, key=str.lower)
    text = ", ".join(names[:MAX_NAMES])
    return text + (f" and {len(names) - MAX_NAMES} more" if len(names) > MAX_NAMES else "")


def _failing_payload(failing: dict[str, tuple[str, str, int]]) -> dict:
    if len(failing) == 1:
        name, error, failures = next(iter(failing.values()))
        return {"kind": "system", "title": f"⚠️ {name} keeps failing",
                "text": f"{failures} failed checks in a row. Last error: {error[:300]}"}
    with db.read() as conn:
        enabled = conn.execute("SELECT COUNT(*) FROM stores WHERE enabled=1").fetchone()[0] or 1
    hint = ""
    if len(failing) >= max(5, enabled // 3):
        hint = " — probably a network problem on the PC running restock-monitoring"
    return {"kind": "system", "title": f"⚠️ {len(failing)} stores failing{hint}",
            "text": _names([v[0] for v in failing.values()])}


def _recovered_payload(recovered: dict[str, str]) -> dict:
    if len(recovered) == 1:
        return {"kind": "system", "title": f"🔧 {next(iter(recovered.values()))} is working again",
                "text": "Checks are succeeding again."}
    return {"kind": "system", "title": f"🔧 {len(recovered)} stores working again",
            "text": _names(list(recovered.values()))}
