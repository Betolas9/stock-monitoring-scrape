"""
Stock Monitor — entry point.

Usage:  python monitor.py
Stop:   Ctrl+C
"""
from __future__ import annotations

import json
import logging
import random
import signal
import sys
import time
from pathlib import Path

from notifier import Notifier
from state_manager import StateManager
from scrapers.continente import ContinenteScraper
from scrapers.toysrus import ToysRusScraper
from scrapers.creativetoys import CreativeToysScraper

# ---------------------------------------------------------------------------
# Logging — UTF-8 on both handlers so emoji survive on Windows
# ---------------------------------------------------------------------------
_file_handler = logging.FileHandler("monitor.log", encoding="utf-8")
_console_handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[_file_handler, _console_handler],
)
logger = logging.getLogger("monitor")

# Map config site keys → scraper classes
_SCRAPER_MAP = {
    "continente":  ContinenteScraper,
    "toysrus":     ToysRusScraper,
    "creativetoys": CreativeToysScraper,
}


def load_config(path: str = "config.json") -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_check(config: dict, state: StateManager, notifier: Notifier) -> None:
    for site_name, site_cfg in config.get("sites", {}).items():
        if not site_cfg.get("enabled", True):
            logger.debug(f"[{site_name}] disabled, skipping")
            continue

        scraper_cls = _SCRAPER_MAP.get(site_name)
        if not scraper_cls:
            logger.warning(f"No scraper registered for '{site_name}', skipping")
            continue

        try:
            logger.info(f"--- Checking {site_name} ---")
            scraper = scraper_cls(site_cfg["url"])
            new_products = scraper.fetch_products()

            # Apply ignore-keyword filter (case-insensitive substring match)
            ignore = [kw.lower() for kw in config.get("ignore_keywords", [])]
            if ignore and new_products:
                new_products = {
                    pid: p for pid, p in new_products.items()
                    if not any(kw in p.get("name", "").lower() for kw in ignore)
                }

            if not new_products:
                logger.warning(
                    f"[{site_name}] 0 products returned — skipping state update "
                    "(site may be down or selectors need updating)"
                )
                time.sleep(random.uniform(1, 3))
                continue

            if state.is_first_run_for_site(site_name):
                state.initialize_site(site_name, new_products)
            else:
                old = state.get_site_state(site_name)
                if ignore:
                    old = {pid: p for pid, p in old.items()
                           if not any(kw in p.get("name", "").lower()
                                      for kw in ignore)}
                events = state.diff_products(old, new_products)
                if events:
                    logger.info(f"[{site_name}] {len(events)} change(s) detected")
                    notifier.notify_events(site_name, events)
                else:
                    logger.info(f"[{site_name}] No changes")
                state.update_site_state(site_name, new_products)

        except Exception as e:
            logger.error(f"[{site_name}] Unexpected error: {e}", exc_info=True)

        # Random jitter between site requests to avoid burst traffic
        time.sleep(random.uniform(1, 3))

    state.save()


def main() -> None:
    config = load_config()
    state = StateManager("known_products.json")
    notifier = Notifier()
    interval_min = config.get("check_interval_min_seconds", config.get("check_interval_seconds", 90))
    interval_max = config.get("check_interval_max_seconds", config.get("check_interval_seconds", 150))

    active_sites = [
        name
        for name, cfg in config.get("sites", {}).items()
        if cfg.get("enabled", True)
    ]

    logger.info("=" * 60)
    logger.info("Stock Monitor started")
    logger.info(f"Sites      : {', '.join(active_sites)}")
    logger.info(f"Interval   : {interval_min}–{interval_max}s (randomised)")
    logger.info(f"State file : {Path('known_products.json').resolve()}")
    logger.info(f"Log file   : {Path('monitor.log').resolve()}")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)

    def _shutdown(sig, frame):  # noqa: ANN001
        logger.info("Shutdown signal received. Goodbye.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    try:
        signal.signal(signal.SIGTERM, _shutdown)
    except (OSError, ValueError):
        pass  # SIGTERM unavailable on Windows — Ctrl+C (SIGINT) is the stop mechanism

    while True:
        try:
            run_check(config, state, notifier)
        except Exception as e:
            logger.error(f"Unexpected error in check cycle: {e}", exc_info=True)

        sleep_for = random.uniform(interval_min, interval_max)
        logger.info(f"Sleeping {sleep_for:.0f}s until next check…")
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
