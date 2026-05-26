from __future__ import annotations

import logging

import requests

from .base import BaseScraper

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
    "Accept":          "application/json",
    "Accept-Language": "pt-PT,pt;q=0.9",
}

# Shopify caps at 250 products per page; we paginate just in case the
# collection grows, but for now the whole catalogue fits in one call.
_PAGE_LIMIT = 250


class CreativeToysScraper(BaseScraper):
    def __init__(self, url: str) -> None:
        super().__init__("CreativeToys", url)
        self._api_base = _collection_to_api(url)

    def fetch_products(self) -> dict:
        logger.info(f"Fetching CreativeToys via Shopify API ({self._api_base})")
        all_products: dict = {}
        page = 1

        while True:
            try:
                resp = requests.get(
                    self._api_base,
                    params={"limit": _PAGE_LIMIT, "page": page},
                    headers=_HEADERS,
                    timeout=15,
                )
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"CreativeToys API error (page={page}): {e}")
                break

            batch = resp.json().get("products", [])
            if not batch:
                break

            logger.info(f"CreativeToys: page {page} → {len(batch)} product(s)")
            for item in batch:
                p = _parse_item(item, self.url)
                if p:
                    all_products[p["id"]] = p

            if len(batch) < _PAGE_LIMIT:
                break
            page += 1

        logger.info(f"CreativeToys: {len(all_products)} total product(s) fetched")
        return all_products


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collection_to_api(url: str) -> str:
    """Turn a /collections/… storefront URL into a /products.json API URL."""
    base = url.rstrip("/").split("?")[0]
    if not base.endswith("/products.json"):
        base += "/products.json"
    return base


def _parse_item(item: dict, store_url: str) -> dict | None:
    # Use the handle as ID — human-readable and stable across price/name edits
    handle = item.get("handle")
    title  = item.get("title")
    if not handle or not title:
        return None

    variants = item.get("variants", [])

    # In stock if any variant is available
    in_stock = any(v.get("available") for v in variants)

    # Price: lowest available variant, fall back to first variant
    price = _best_price(variants)

    # compare_at_price > price means the item is currently on sale
    original_price = _original_price(variants)

    url = f"{store_url.rstrip('/').split('/collections/')[0]}/products/{handle}"

    return {
        "id":             handle,
        "name":           title,
        "price":          price,
        "original_price": original_price,
        "in_stock":       in_stock,
        "url":            url,
    }


def _best_price(variants: list[dict]) -> str | None:
    available = [v for v in variants if v.get("available")]
    source = available if available else variants
    prices = [v.get("price") for v in source if v.get("price") is not None]
    if not prices:
        return None
    return f"{min(float(p) for p in prices):.2f}"


def _original_price(variants: list[dict]) -> str | None:
    """Return the compare-at price if any variant is on sale."""
    for v in variants:
        comp  = v.get("compare_at_price")
        price = v.get("price")
        if not comp or not price:
            continue
        try:
            if float(comp) > float(price):
                return f"{float(comp):.2f}"
        except (ValueError, TypeError):
            continue
    return None
