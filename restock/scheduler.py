"""Background store checker.

Every enabled store has its own next_check_at. A loop picks due stores and
runs them on a thread pool, respecting the global concurrency limit and never
hitting the same domain twice at once. After each check the store is
rescheduled at a random delay within its interval (jitter), with exponential
backoff while it keeps failing.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from scrapers import build_scraper

from . import alerts, db, notify, settings, timeutil
from .health import HealthReporter
from .ingest import ingest

logger = logging.getLogger(__name__)

MAX_BACKOFF_S = 1800


def _domain(store: dict) -> str:
    urls = db.jload(store.get("urls"), None) or [store["url"]]
    return urlsplit(urls[0]).netloc.lower().removeprefix("www.")


def next_delay(store: dict, cfg: dict, failures: int) -> float:
    lo = store.get("interval_min") or cfg["scheduler"]["interval_min"]
    hi = store.get("interval_max") or cfg["scheduler"]["interval_max"]
    lo, hi = min(lo, hi), max(lo, hi)
    delay = random.uniform(lo, hi)
    if failures:
        delay = min(delay * 2 ** min(failures - 1, 5), MAX_BACKOFF_S)
    return delay


class Scheduler:
    def __init__(self, dispatcher: notify.Dispatcher | None = None) -> None:
        self._dispatcher = dispatcher
        self._pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="store-check")
        self._running: dict[str, str] = {}      # store id → domain
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)
        self.started_at = timeutil.iso()
        self._health = HealthReporter()

    # ------------------------------------------------------------------ control

    def start(self) -> None:
        with db.tx() as conn:
            # Checks interrupted by a restart
            conn.execute(
                "UPDATE stores SET status = CASE"
                " WHEN last_success_at IS NULL AND last_error_at IS NULL THEN 'pending'"
                " WHEN last_error_at IS NOT NULL AND (last_success_at IS NULL OR last_error_at > last_success_at) THEN 'error'"
                " ELSE 'ok' END WHERE status='running'"
            )
            # Spread the first round of checks out instead of starting all at once
            due = conn.execute(
                "SELECT id FROM stores WHERE enabled=1 AND (next_check_at IS NULL OR next_check_at < ?)"
                " ORDER BY last_check_at IS NOT NULL, last_check_at",
                (timeutil.iso(),),
            ).fetchall()
            for i, r in enumerate(due):
                conn.execute("UPDATE stores SET next_check_at=? WHERE id=?", (timeutil.later(2 + i * 2), r["id"]))
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def wake(self) -> None:
        self._wake.set()

    def check_now(self, store_id: str) -> None:
        with db.tx() as conn:
            conn.execute("UPDATE stores SET next_check_at=? WHERE id=?", (timeutil.iso(), store_id))
        self._wake.set()

    def check_all_now(self) -> None:
        with db.tx() as conn:
            ids = [r["id"] for r in conn.execute("SELECT id FROM stores WHERE enabled=1 ORDER BY name")]
            for i, sid in enumerate(ids):
                conn.execute("UPDATE stores SET next_check_at=? WHERE id=?", (timeutil.later(i * 0.5), sid))
        self._wake.set()

    def running(self) -> list[str]:
        with self._lock:
            return list(self._running)

    # ------------------------------------------------------------------ loop

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
                self._health.flush_if_due()
            except Exception:
                logger.exception("scheduler tick failed")
            self._wake.wait(1.0)
            self._wake.clear()

    def _tick(self) -> None:
        cfg = settings.get()
        if cfg["scheduler"]["paused"]:
            return
        limit = max(1, int(cfg["scheduler"]["concurrency"]))
        with db.read() as conn:
            due = db.rows(conn.execute(
                "SELECT * FROM stores WHERE enabled=1 AND next_check_at IS NOT NULL AND next_check_at<=?"
                " ORDER BY next_check_at",
                (timeutil.iso(),),
            ))
        for store in due:
            with self._lock:
                if len(self._running) >= limit:
                    return
                domain = _domain(store)
                if store["id"] in self._running or domain in self._running.values():
                    continue
                self._running[store["id"]] = domain
            self._pool.submit(self._check, store["id"])

    # ------------------------------------------------------------------ one check

    def _check(self, store_id: str) -> None:
        started = time.monotonic()
        try:
            with db.tx() as conn:
                store = db.row(conn.execute("SELECT * FROM stores WHERE id=?", (store_id,)))
                if not store or not store["enabled"]:
                    return
                conn.execute("UPDATE stores SET status='running', last_check_at=? WHERE id=?",
                             (timeutil.iso(), store_id))
            self._do_check(store, started)
        except Exception:
            logger.exception(f"[{store_id}] unexpected error during check")
        finally:
            with self._lock:
                self._running.pop(store_id, None)
            self._wake.set()
            if self._dispatcher:
                self._dispatcher.wake()

    def _do_check(self, store: dict, started: float) -> None:
        cfg = settings.get()
        scraper = build_scraper(store["id"], {
            "type": store["platform"], "label": store["name"], "url": store["url"],
            "urls": db.jload(store["urls"], None), "options": db.jload(store["options"], {}),
        })
        try:
            if scraper is None:
                raise RuntimeError(f"unknown platform '{store['platform']}'")
            scraped = scraper.fetch_products()
            with db.tx() as conn:
                events = ingest(conn, store, scraped, cfg.get("ignore_keywords", []))
                to_send = alerts.evaluate(conn, events, cfg)
                notify.enqueue_events(conn, store["name"], to_send)
                conn.execute(
                    "UPDATE stores SET status='ok', last_success_at=?, last_duration_ms=?, last_raw_count=?,"
                    " consecutive_failures=0, failure_alerted=0, baseline_done=1, next_check_at=? WHERE id=?",
                    (timeutil.iso(), int((time.monotonic() - started) * 1000), len(scraped),
                     timeutil.later(next_delay(store, cfg, 0)), store["id"]),
                )
            if store["failure_alerted"]:
                self._health.recovered(store["id"], store["name"])
            logger.info(f"[{store['id']}] ok: {len(scraped)} scraped, {len(events)} event(s), {len(to_send)} alert(s)")
        except Exception as e:  # noqa: BLE001 — every failure becomes a visible store error
            failures = store["consecutive_failures"] + 1
            msg = f"{type(e).__name__}: {e}" if not str(e).startswith(type(e).__name__) else str(e)
            health = cfg["alerts"]["store_health"]
            threshold = int(health["after_failures"])
            with db.tx() as conn:
                alert = health["enabled"] and failures >= max(1, threshold) and not store["failure_alerted"]
                conn.execute(
                    "UPDATE stores SET status='error', last_error=?, last_error_at=?, last_duration_ms=?,"
                    " consecutive_failures=?, failure_alerted=?, next_check_at=? WHERE id=?",
                    (msg[:1000], timeutil.iso(), int((time.monotonic() - started) * 1000), failures,
                     int(alert or store["failure_alerted"]), timeutil.later(next_delay(store, cfg, failures)),
                     store["id"]),
                )
            if alert:
                self._health.failing(store["id"], store["name"], msg, failures)
            logger.warning(f"[{store['id']}] check failed ({failures}x): {msg}")
