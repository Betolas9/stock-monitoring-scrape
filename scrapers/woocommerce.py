from __future__ import annotations

import html
import logging
import time
from urllib.parse import parse_qsl, urlsplit

from .base import BaseScraper, ScrapeError
from .http import JSON_HEADERS, make_session

logger = logging.getLogger(__name__)

# WooCommerce Store API caps at 100 products per page
_PAGE_LIMIT = 100
_MAX_PAGES = 80
_PAGE_DELAY_S = 0.3  # small pause between pages; the JSON APIs are cheap for the store


class WooCommerceScraper(BaseScraper):
    """Generic WooCommerce store scraper via the public Store API
    (/wp-json/wc/store/v1/products — no authentication required).

    Query parameters on the configured URL are forwarded to the API, so a
    large generalist store can be narrowed down, e.g.
    https://store.pt/?category=123 → only that category.
    """

    def __init__(self, label: str, url: str, options: dict | None = None) -> None:
        super().__init__(label, url, options)
        parts = urlsplit(url)
        self._api_url = f"{parts.scheme}://{parts.netloc}/wp-json/wc/store/v1/products"
        self._extra_params = dict(parse_qsl(parts.query))

    def fetch_products(self) -> dict:
        logger.info(f"Fetching {self.name} via WooCommerce Store API ({self._api_url})")
        session = make_session(JSON_HEADERS, impersonate=bool(self.options.get("impersonate")))
        all_products: dict = {}

        for page in range(1, _MAX_PAGES + 1):
            if page > 1:
                time.sleep(_PAGE_DELAY_S)
            try:
                resp = session.get(
                    self._api_url,
                    params={**self._extra_params, "per_page": _PAGE_LIMIT, "page": page},
                    timeout=25,
                )
                # Past the last page the Store API answers 400 on some versions
                if resp.status_code == 400 and page > 1:
                    break
                resp.raise_for_status()
                batch = resp.json()
            except Exception as e:
                raise ScrapeError(f"WooCommerce API error on page {page}: {e}") from e

            if not isinstance(batch, list):
                raise ScrapeError("WooCommerce API returned unexpected payload")
            if not batch:
                break

            logger.debug(f"{self.name}: page {page} → {len(batch)} product(s)")
            for item in batch:
                p = _parse_item(item)
                if p:
                    all_products[p["id"]] = p

            if len(batch) < _PAGE_LIMIT:
                break

        logger.info(f"{self.name}: {len(all_products)} total product(s) fetched")
        return all_products


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_item(item: dict) -> dict | None:
    product_id = item.get("id")
    name       = item.get("name")
    if not product_id or not name:
        return None

    prices = item.get("prices", {})
    price  = _minor_units_to_str(prices.get("price"), prices)

    # regular_price > price only when the product is on sale
    original_price = None
    if item.get("on_sale"):
        regular = _minor_units_to_str(prices.get("regular_price"), prices)
        if regular and price and float(regular) > float(price):
            original_price = regular

    images = item.get("images") or []
    image = (images[0].get("src") or images[0].get("thumbnail")) if images else None

    cats = [c.get("name", "") for c in item.get("categories") or []]
    tags = [t.get("name", "") for t in item.get("tags") or []]

    return {
        "id":             str(product_id),
        # Store API names are HTML-escaped ("Pok&eacute;mon")
        "name":           html.unescape(name),
        "price":          price,
        "original_price": original_price,
        "in_stock":       bool(item.get("is_in_stock", True)),
        "url":            item.get("permalink", ""),
        "image":          image,
        "meta":           html.unescape(" | ".join(x for x in [", ".join(cats), ", ".join(tags)] if x)),
    }


def _minor_units_to_str(raw, prices: dict) -> str | None:
    """Store API prices come in minor units, e.g. '2350' + minor_unit 2 → '23.50'."""
    if raw in (None, ""):
        return None
    try:
        minor = int(prices.get("currency_minor_unit", 2))
        return f"{int(raw) / 10 ** minor:.2f}"
    except (ValueError, TypeError):
        return None
