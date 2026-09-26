from __future__ import annotations

from datetime import datetime, timedelta, timezone


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    """UTC ISO-8601 timestamp — the only timestamp format stored in the DB."""
    return (dt or now()).astimezone(timezone.utc).isoformat(timespec="seconds")


def parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:  # legacy v1 timestamps were naive local time
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc)


def ago(**kwargs) -> str:
    return iso(now() - timedelta(**kwargs))


def later(seconds: float) -> str:
    return iso(now() + timedelta(seconds=seconds))
