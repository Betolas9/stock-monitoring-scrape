"""App settings: one JSON document in the settings table, deep-merged over
DEFAULTS so new keys added in code always have a value."""
from __future__ import annotations

import copy
import threading
from typing import Any

from . import db

DEFAULTS: dict[str, Any] = {
    "scheduler": {
        # Each store waits a random time in [min, max] between checks —
        # jitter avoids a fixed, bot-like polling cadence.
        "interval_min": 45,
        "interval_max": 90,
        "concurrency": 8,
        "paused": False,
    },
    "ignore_keywords": [],
    "channels": {
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "discord":  {"enabled": False, "webhook_url": "", "mention": ""},
        "windows":  {"enabled": True},
    },
    "alerts": {
        # Favourited products
        "favorites": {"restock": True, "price_drop": True, "new_store": True},
        # Products of sets marked as "focus" in the release calendar
        "focus":     {"new_listing": True, "restock": True, "price_drop": False},
        # Everything else, limited to these TCGs
        "general":   {
            "new_listing": True,
            "restock": False,
            "price_drop": False,
            "tcgs": ["pokemon", "onepiece"],
            "include_accessories": False,
            "include_other": False,
        },
        "out_of_stock": False,       # also alert when a favourite sells out
        "min_drop_pct": 3,           # ignore price drops smaller than this
        "group_threshold": 5,        # ≥ this many alerts from one check → one summary message
        # Alerts about the stores themselves (grouped into one message per minute)
        "store_health": {
            "enabled": True,
            "after_failures": 5,      # consecutive failed checks before a store counts as failing
            "notify_recovered": True, # also say when failing stores work again
        },
    },
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _upgrade(saved: dict) -> dict:
    """Carry old settings over to their new shape."""
    alerts = saved.get("alerts") or {}
    if "store_failure_after" in alerts and "store_health" not in alerts:
        n = int(alerts.get("store_failure_after") or 0)
        alerts["store_health"] = {"enabled": n > 0, "after_failures": n or 5}
    alerts.pop("store_failure_after", None)
    return saved


def get() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is None:
            with db.read() as conn:
                r = conn.execute("SELECT value FROM settings WHERE key='app'").fetchone()
            _cache = _merge(DEFAULTS, _upgrade(db.jload(r["value"], {}) if r else {}))
        return copy.deepcopy(_cache)


def update(patch: dict[str, Any]) -> dict[str, Any]:
    global _cache
    with _lock:
        with db.tx() as conn:
            r = conn.execute("SELECT value FROM settings WHERE key='app'").fetchone()
            current = _merge(DEFAULTS, _upgrade(db.jload(r["value"], {}) if r else {}))
            merged = _merge(current, patch)
            conn.execute(
                "INSERT INTO settings(key, value) VALUES('app', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (db.jdump(merged),),
            )
        _cache = merged
        return copy.deepcopy(merged)
