from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class StateManager:
    def __init__(self, path: str = "known_products.json") -> None:
        self.path = Path(path)
        self._state: dict = self._load()

    # ------------------------------------------------------------------ I/O

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load state from {self.path}: {e}")
            return {}

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state to {self.path}: {e}")

    # ----------------------------------------------------------------- Query

    def is_first_run_for_site(self, site_name: str) -> bool:
        """True when we have no baseline for this site yet."""
        return site_name not in self._state

    def get_site_state(self, site_name: str) -> dict:
        return self._state.get(site_name, {})

    # ----------------------------------------------------------------- Write

    def initialize_site(self, site_name: str, products: dict) -> None:
        """Populate baseline on first run — no events emitted."""
        now = _now()
        self._state[site_name] = {}
        for pid, product in products.items():
            self._state[site_name][pid] = {
                **product,
                "first_seen": now,
                "last_seen": now,
                "stock_history": [{"timestamp": now, "in_stock": product.get("in_stock", True)}],
            }
        logger.info(f"[{site_name}] Baseline set: {len(products)} product(s)")

    def update_site_state(self, site_name: str, new_products: dict) -> None:
        """Merge new scrape results into persisted state."""
        now = _now()
        site = self._state.setdefault(site_name, {})

        for pid, product in new_products.items():
            if pid not in site:
                site[pid] = {
                    **product,
                    "first_seen": now,
                    "last_seen": now,
                    "stock_history": [{"timestamp": now, "in_stock": product.get("in_stock", True)}],
                }
            else:
                entry = site[pid]
                old_stock = entry.get("in_stock", True)
                new_stock = product.get("in_stock", True)
                entry.update(
                    {
                        "last_seen":      now,
                        "name":           product.get("name", entry["name"]),
                        "price":          product.get("price"),
                        "original_price": product.get("original_price"),
                        "url":            product.get("url", entry.get("url")),
                        "in_stock":       new_stock,
                    }
                )
                if old_stock != new_stock:
                    entry.setdefault("stock_history", []).append(
                        {"timestamp": now, "in_stock": new_stock}
                    )

        # Products absent from the new scrape are considered sold out
        for pid, entry in site.items():
            if pid not in new_products and entry.get("in_stock", True):
                entry["in_stock"] = False
                entry["last_seen"] = now
                entry.setdefault("stock_history", []).append(
                    {"timestamp": now, "in_stock": False}
                )

    # ------------------------------------------------------------------ Diff

    def diff_products(self, old_state: dict, new_state: dict) -> list[dict]:
        """
        Compare old and new product dicts and return change events.

        Event types: new_product | back_in_stock | out_of_stock | price_change
        """
        events: list[dict] = []

        for pid, new in new_state.items():
            if pid not in old_state:
                events.append({"type": "new_product", "product": new})
            else:
                old = old_state[pid]
                was_in = old.get("in_stock", True)
                now_in = new.get("in_stock", True)
                if not was_in and now_in:
                    events.append({"type": "back_in_stock", "product": new})
                elif was_in and not now_in:
                    events.append({"type": "out_of_stock", "product": new, "old": old})
                old_price = old.get("price")
                new_price = new.get("price")
                if old_price and new_price and old_price != new_price:
                    events.append(
                        {"type": "price_change", "product": new, "old_price": old_price}
                    )

        # Products that vanished entirely from the listing
        for pid, old in old_state.items():
            if pid not in new_state and old.get("in_stock", True):
                events.append({"type": "out_of_stock", "product": old})

        return events


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
