from __future__ import annotations

import logging

import requests

from .base import BaseScraper

logger = logging.getLogger(__name__)

# Empathy.co search API — discovered by intercepting network calls on toysrus.pt
_API_URL = "https://api.empathy.co/search/v1/query/toysrus/search"
_API_HEADERS = {
    "Accept":          "application/json",
    "Accept-Language": "pt-PT,pt;q=0.9",
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
    "Referer":         "https://www.toysrus.pt/",
}
_API_PARAMS = {
    "internal": "true",
    "origin":   "url:external",
    "instance": "toysrus",
    "lang":     "pt",
    "scope":    "desktop",
    "currency": "EUR",
    "rows":     100,
}

# API field meanings (confirmed by inspecting 290-product response):
#   id           → SKU string, e.g. "K1043472"  (stable, use as product ID)
#   __name       → product name
#   price        → float price in EUR
#   availability → True = in stock, False = out of stock
#   url          → canonical product page URL


class ToysRusScraper(BaseScraper):
    def __init__(self, url: str) -> None:
        # url from config.json is kept for reference; we hit the API directly
        super().__init__("ToysRus", url)

    def fetch_products(self) -> dict:
        query = _extract_query(self.url)
        logger.info(f"Fetching ToysRus via Empathy API (query={query!r})")

        all_products: dict = {}
        start = 0

        while True:
            params = {**_API_PARAMS, "query": query, "start": start}
            try:
                resp = requests.get(_API_URL, params=params, headers=_API_HEADERS, timeout=15)
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"ToysRus API error (start={start}): {e}")
                break

            batch = resp.json().get("catalog", {}).get("content", [])
            if not batch:
                logger.info(f"ToysRus: no more products at start={start}")
                break

            logger.info(f"ToysRus: page start={start} → {len(batch)} product(s)")
            for item in batch:
                p = _parse_item(item)
                if p:
                    all_products[p["id"]] = p

            start += len(batch)

        logger.info(f"ToysRus: {len(all_products)} total product(s) fetched")
        return all_products


def _extract_query(url: str) -> str:
    """Pull search term from the config URL, fall back to 'pokemon'."""
    for param in ("query=", "q=", "text="):
        if param in url:
            fragment = url.split(param, 1)[1].split("&")[0]
            # strip Hybris sort prefix like ":price-asc"
            if "%" in fragment:
                from urllib.parse import unquote
                fragment = unquote(fragment)
            fragment = fragment.lstrip(":").split(":")[0]
            if fragment:
                return fragment
    return "pokemon"


def _parse_item(item: dict) -> dict | None:
    product_id = item.get("id") or item.get("__id") or item.get("__externalId")
    name       = item.get("__name") or item.get("name")
    if not product_id or not name:
        return None

    prices_block = item.get("__prices", {})
    raw_price    = item.get("price") or prices_block.get("current", {}).get("value")
    price        = f"{float(raw_price):.2f}" if raw_price is not None else None

    # Best-effort original price extraction from the Empathy API
    raw_orig = (
        item.get("originalPrice") or
        item.get("__originalPrice") or
        prices_block.get("original", {}).get("value") or
        prices_block.get("prev", {}).get("value")
    )
    original_price = None
    if raw_orig is not None and price is not None:
        try:
            if float(raw_orig) > float(price):
                original_price = f"{float(raw_orig):.2f}"
        except (ValueError, TypeError):
            pass

    in_stock = bool(item.get("availability", True))
    url      = item.get("url") or item.get("__url") or ""

    return {
        "id":             product_id,
        "name":           name,
        "price":          price,
        "original_price": original_price,
        "in_stock":       in_stock,
        "url":            url,
    }
