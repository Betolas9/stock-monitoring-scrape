"""SQLite storage.

One short-lived connection per unit of work (`with db.tx() as conn:`), WAL
mode and a generous busy timeout, so the scheduler's worker threads and the
API can write concurrently without "database is locked" errors.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from .paths import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stores (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    platform             TEXT NOT NULL,
    url                  TEXT NOT NULL,          -- homepage, for display/links
    urls                 TEXT,                   -- JSON list of URLs to scrape (NULL → [url])
    options              TEXT,                   -- JSON scraper options (selectors, …)
    enabled              INTEGER NOT NULL DEFAULT 1,
    interval_min         INTEGER,                -- per-store override (seconds)
    interval_max         INTEGER,
    notes                TEXT,
    created_at           TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending',   -- pending|running|ok|error
    last_check_at        TEXT,
    last_success_at      TEXT,
    last_error           TEXT,
    last_error_at        TEXT,
    last_duration_ms     INTEGER,
    last_raw_count       INTEGER,                -- products returned before filtering
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    failure_alerted      INTEGER NOT NULL DEFAULT 0,
    next_check_at        TEXT,
    baseline_done        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sets (
    id             TEXT PRIMARY KEY,             -- e.g. pokemon-me03
    tcg            TEXT NOT NULL,
    code           TEXT,                         -- e.g. ME03, OP-13
    name           TEXT NOT NULL,
    aliases        TEXT,                         -- JSON list of extra names
    release_date   TEXT,                         -- YYYY-MM-DD
    date_confirmed INTEGER NOT NULL DEFAULT 1,
    focus          INTEGER NOT NULL DEFAULT 0,
    auto_created   INTEGER NOT NULL DEFAULT 0,
    notes          TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id              TEXT PRIMARY KEY,
    tcg             TEXT,
    set_id          TEXT,
    type            TEXT,
    lang            TEXT,
    variant         TEXT,
    title           TEXT NOT NULL,
    image           TEXT,
    manual          INTEGER NOT NULL DEFAULT 0,  -- edited by hand: matcher won't touch it
    hidden          INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    -- denormalised stats, refreshed whenever one of its listings changes
    best_price      REAL,                        -- cheapest in-stock price
    best_store      TEXT,
    min_price       REAL,                        -- cheapest listed price, any stock
    store_count     INTEGER NOT NULL DEFAULT 0,
    in_stock_count  INTEGER NOT NULL DEFAULT 0,
    change_30d      REAL,                        -- % change of min_price vs 30 days ago
    last_change     TEXT
);

CREATE TABLE IF NOT EXISTS listings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id       TEXT NOT NULL,
    external_id    TEXT NOT NULL,
    name           TEXT NOT NULL,
    url            TEXT,
    image          TEXT,
    meta           TEXT,
    price          REAL,
    original_price REAL,
    in_stock       INTEGER NOT NULL,
    present        INTEGER NOT NULL DEFAULT 1,   -- seen in the latest successful check
    preorder       INTEGER NOT NULL DEFAULT 0,
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    last_change    TEXT,
    kind           TEXT,                         -- sealed|accessory|other
    tcg            TEXT,
    lang           TEXT,
    ptype          TEXT,
    set_id         TEXT,
    product_id     TEXT,
    match_mode     TEXT NOT NULL DEFAULT 'auto', -- auto|manual|none (none = kept unmatched)
    UNIQUE(store_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_listings_product ON listings(product_id);
CREATE INDEX IF NOT EXISTS idx_listings_store   ON listings(store_id);
CREATE INDEX IF NOT EXISTS idx_listings_set     ON listings(set_id);

CREATE TABLE IF NOT EXISTS listing_history (
    listing_id INTEGER NOT NULL,
    ts         TEXT NOT NULL,
    price      REAL,
    in_stock   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_listing ON listing_history(listing_id, ts);

CREATE TABLE IF NOT EXISTS favorites (
    product_id       TEXT PRIMARY KEY,
    target_price     REAL,
    notify_restock   INTEGER NOT NULL DEFAULT 1,
    notify_price     INTEGER NOT NULL DEFAULT 1,
    notify_new_store INTEGER NOT NULL DEFAULT 1,
    note             TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    type         TEXT NOT NULL,   -- new_listing|back_in_stock|out_of_stock|price_drop|price_rise|store_failing|store_recovered
    store_id     TEXT,
    listing_id   INTEGER,
    product_id   TEXT,
    title        TEXT,
    url          TEXT,
    image        TEXT,
    price        REAL,
    old_price    REAL,
    in_stock     INTEGER,
    alert_reason TEXT              -- why it was sent (target|favorite|focus|general|system) or NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_product ON events(product_id);

CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    channel         TEXT NOT NULL,   -- telegram|discord|windows
    status          TEXT NOT NULL,   -- pending|sent|failed
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    sent_at         TEXT,
    last_error      TEXT,
    summary         TEXT,
    payload         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status, next_attempt_at);
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """A connection inside one IMMEDIATE transaction; commits on success."""
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


@contextmanager
def read() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


# Columns added after the first release: (table, column, definition)
MIGRATIONS = [
    # the seed entry last applied (JSON) — lets bootstrap 3-way-merge seed
    # updates without overwriting fields the user changed in the UI
    ("stores", "seed_json", "TEXT"),
    ("sets", "seed_json", "TEXT"),
    # recipient within a channel (Telegram chat id); NULL = the channel's only target
    ("notifications", "target", "TEXT"),
]


def init() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        for table, column, definition in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    finally:
        conn.close()


def rows(cur) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


def row(cur) -> dict[str, Any] | None:
    r = cur.fetchone()
    return dict(r) if r else None


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    r = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r["value"] if r else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def jload(value: str | None, default: Any = None) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
