from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeError
from .http import HTML_HEADERS, make_session

logger = logging.getLogger(__name__)

_TILE_SELECTORS = [
    "article.product-miniature",
    ".js-product-miniature",
    ".product-miniature",
]

# Visible flag texts that mean the product cannot be bought right now
_OOS_MARKERS = ("esgotado", "out of stock", "out-of-stock", "indisponível", "fora de stock")

_MAX_PAGES = 20  # safety cap


class PrestaShopScraper(BaseScraper):
    """Generic PrestaShop category-page scraper (requests + BeautifulSoup).

    PrestaShop has no public catalog API, so this parses the standard
    'classic' theme product-miniature tiles and paginates with ?page=N.
    """

    def __init__(self, label: str, url: str, options: dict | None = None) -> None:
        super().__init__(label, url, options)
        parts = urlsplit(url)
        self._base_url = f"{parts.scheme}://{parts.netloc}"

    def fetch_products(self) -> dict:
        logger.info(f"Fetching {self.name} — {self.url}")
        session = make_session(HTML_HEADERS, impersonate=bool(self.options.get("impersonate")))
        all_products: dict = {}
        prev_first_id: str | None = None

        for page in range(1, _MAX_PAGES + 1):
            sep = "&" if "?" in self.url else "?"
            page_url = self.url if page == 1 else f"{self.url}{sep}page={page}"
            if page > 1:
                time.sleep(0.6)
            try:
                resp = session.get(page_url, timeout=25)
                resp.raise_for_status()
            except Exception as e:
                raise ScrapeError(f"PrestaShop request failed (page={page}): {e}") from e

            soup = BeautifulSoup(resp.text, "lxml")
            tiles = _select_first(soup, _TILE_SELECTORS)
            if not tiles:
                if page == 1:
                    logger.warning(
                        f"{self.name}: no product tiles found — site structure may "
                        "have changed. Enable DEBUG logging to see the page snippet."
                    )
                    logger.debug(f"{self.name} page snippet:\n{resp.text[:1200]}")
                break

            batch = [p for p in (self._parse_tile(t) for t in tiles) if p]

            # PrestaShop clamps out-of-range pages to the last page instead of
            # returning an empty listing — detect the repeat and stop.
            first_id = batch[0]["id"] if batch else None
            if first_id and first_id == prev_first_id:
                break
            prev_first_id = first_id

            logger.info(f"{self.name}: page {page} → {len(batch)} product(s)")
            for p in batch:
                all_products[p["id"]] = p

            # Fewer tiles than a full PrestaShop page (usually 12+) → last page
            if len(tiles) < 12:
                break

        logger.info(f"{self.name}: {len(all_products)} total product(s) fetched")
        return all_products

    def _parse_tile(self, tile) -> dict | None:
        link = tile.select_one(".product-title a") or tile.select_one("h2 a, h3 a")
        if not link:
            return None
        name = link.get_text(strip=True)
        # Many themes truncate long names in the tile ("… Booster...") — the
        # link title / image alt usually carry the full one.
        if name.endswith(("...", "…")):
            img = tile.select_one("img")
            full = link.get("title") or (img.get("alt") if img else None) or (img.get("title") if img else None)
            if full and not full.strip().endswith(("...", "…")) and len(full.strip()) > len(name) - 3:
                name = full.strip()
        url  = link.get("href", "")
        if name.endswith(("...", "…")):
            # last resort: /15508-booster-saiyan-showdown-b15.html → words
            m = re.search(r"/\d+-([a-z0-9-]+?)(?:-\d{8,14})?\.html", url)
            if m and len(m.group(1)) > len(name) - 3:
                name = m.group(1).replace("-", " ").strip().title()
        if not name:
            return None
        if url and not url.startswith("http"):
            url = f"{self._base_url}{url}"

        # Numeric product ID is embedded in the URL path: /15508-product-name.html
        m = re.search(r"/(\d+)-", urlsplit(url).path)
        product_id = m.group(1) if m else self._generate_id(name)

        return {
            "id":             product_id,
            "name":           name,
            "price":          _extract_price(tile, ".price, .product-price-and-shipping"),
            "original_price": _extract_price(tile, ".regular-price"),
            "in_stock":       _is_in_stock(tile),
            "url":            url,
            "image":          _extract_image(tile),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select_first(soup: BeautifulSoup, selectors: list[str]) -> list:
    for sel in selectors:
        results = soup.select(sel)
        if results:
            logger.debug(f"PrestaShop tile selector → {sel!r} ({len(results)} tiles)")
            return results
    return []


def _extract_price(tile, selector: str) -> str | None:
    el = tile.select_one(selector)
    if el:
        m = re.search(r"(\d+)[,.](\d{2})", el.get_text(strip=True))
        if m:
            return f"{m.group(1)}.{m.group(2)}"
    return None


def _extract_image(tile) -> str | None:
    img = tile.select_one("img")
    if not img:
        return None
    return (
        img.get("data-full-size-image-url")
        or img.get("data-src")
        or img.get("src")
    )


def _is_in_stock(tile) -> bool:
    flags = tile.select_one(".product-flags")
    if flags:
        text = flags.get_text(" ", strip=True).lower()
        if any(marker in text for marker in _OOS_MARKERS):
            return False
    return True
