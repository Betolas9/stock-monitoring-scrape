from __future__ import annotations

import logging
import time

from .base import BaseScraper, ScrapeError
from .http import JSON_HEADERS, make_session

logger = logging.getLogger(__name__)

# Shopify caps at 250 products per page
_PAGE_LIMIT = 250
_MAX_PAGES = 60  # 15k products — far beyond any store we track
_PAGE_DELAY_S = 0.3  # small pause between pages; the JSON APIs are cheap for the store


class ShopifyScraper(BaseScraper):
    """Generic Shopify store scraper via the public /products.json API.

    Works with either a whole store (https://store.com) or a single
    collection (https://store.com/collections/xyz).
    """

    def __init__(self, label: str, url: str, options: dict | None = None) -> None:
        super().__init__(label, url, options)
        self._api_base = _to_api_url(url)
        self._store_root = url.rstrip("/").split("/collections/")[0]

    def fetch_products(self) -> dict:
        logger.info(f"Fetching {self.name} via Shopify API ({self._api_base})")
        session = make_session(JSON_HEADERS, impersonate=bool(self.options.get("impersonate")))
        all_products: dict = {}

        for page in range(1, _MAX_PAGES + 1):
            if page > 1:
                time.sleep(_PAGE_DELAY_S)
            try:
                resp = session.get(
                    self._api_base,
                    params={"limit": _PAGE_LIMIT, "page": page},
                    timeout=25,
                )
                resp.raise_for_status()
                batch = resp.json().get("products", [])
            except Exception as e:
                raise ScrapeError(f"Shopify API error on page {page}: {e}") from e

            if not batch:
                break

            logger.debug(f"{self.name}: page {page} → {len(batch)} product(s)")
            for item in batch:
                p = _parse_item(item, self._store_root)
                if p:
                    all_products[p["id"]] = p

            if len(batch) < _PAGE_LIMIT:
                break

        logger.info(f"{self.name}: {len(all_products)} total product(s) fetched")
        return all_products


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_api_url(url: str) -> str:
    """Turn a store root or /collections/… URL into a products.json API URL."""
    base = url.rstrip("/").split("?")[0]
    if not base.endswith("/products.json"):
        base += "/products.json"
    return base


def _parse_item(item: dict, store_root: str) -> dict | None:
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

    images = item.get("images") or []
    image = images[0].get("src") if images else None

    tags = item.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    meta = " | ".join(
        x for x in [item.get("product_type") or "", item.get("vendor") or "", ", ".join(tags)] if x
    )

    return {
        "id":             handle,
        "name":           title,
        "price":          price,
        "original_price": original_price,
        "in_stock":       in_stock,
        "url":            f"{store_root}/products/{handle}",
        "image":          image,
        "meta":           meta,
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
