from __future__ import annotations

import json
import logging
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeError
from .http import make_session

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.continente.pt"

_TILE_SELECTORS = [
    "div.product-tile",
    "article.product-tile",
    "li.product-tile",
    ".ct-product-tile",
]

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8",
    "Referer":         "https://www.continente.pt/",
}


class ContinenteScraper(BaseScraper):
    def __init__(self, label: str = "Continente", url: str = "", options: dict | None = None) -> None:
        super().__init__(label, url, options)

    def fetch_products(self) -> dict:
        logger.info(f"Fetching Continente — {self.url}")
        session = make_session(_HEADERS)
        products: dict = {}
        start = 0

        while True:
            url = _set_start(self.url, start)
            try:
                resp = session.get(url, timeout=25)
                resp.raise_for_status()
                html = resp.text
            except Exception as e:
                raise ScrapeError(f"Continente request failed (start={start}): {e}") from e

            soup = BeautifulSoup(html, "lxml")
            tiles = _select_first(soup, _TILE_SELECTORS)

            if not tiles:
                if start == 0:
                    logger.warning(
                        "Continente: no product tiles found — site structure may have changed. "
                        "Enable DEBUG logging to see the page snippet."
                    )
                    logger.debug(f"Continente page snippet:\n{html[:1200]}")
                break

            logger.info(f"Continente: start={start} → {len(tiles)} tile(s)")
            for tile in tiles:
                p = _parse_tile(tile)
                if p:
                    products[p["id"]] = p

            start += len(tiles)

        logger.info(f"Continente: {len(products)} product(s) parsed")
        return products


# ---------------------------------------------------------------------------
# Parsing helpers
#
# Each tile has a data-product-tile-impression JSON attribute:
#   {"name": "Pokémon - ...", "id": "8763462", "price": 8.99, ...}
# This is far more reliable than scraping text/CSS for name, id, and price.
#
# Stock detection: OOS badges are always in the DOM but hidden with Bootstrap's
# d-none class when the product is available. We skip any OOS element that is
# hidden. The add-to-cart button being enabled is the positive confirmation.
# ---------------------------------------------------------------------------

def _set_start(url: str, start: int) -> str:
    """Overwrite (or add) the ?start= offset used for pagination."""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    query["start"] = [str(start)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                        urlencode(query, doseq=True), parts.fragment))


def _select_first(soup: BeautifulSoup, selectors: list[str]) -> list:
    for sel in selectors:
        results = soup.select(sel)
        if results:
            logger.debug(f"Continente: tile selector → {sel!r} ({len(results)} tiles)")
            return results
    return []


def _parse_tile(tile) -> dict | None:
    impression = _read_impression(tile)

    product_id = str(impression.get("id", "")) if impression else ""
    name       = impression.get("name", "") if impression else ""

    # Fallback name from anchor text if impression missing
    if not name:
        for a in tile.find_all("a", href=True):
            t = a.get_text(strip=True)
            if t and len(t) > 5:
                name = t
                break

    if not product_id or not name:
        return None

    # Price from impression (already a float), fallback to HTML
    raw_price = impression.get("price") if impression else None
    if raw_price is not None:
        price = f"{float(raw_price):.2f}"
    else:
        price = _extract_price_html(tile)

    return {
        "id":             product_id,
        "name":           name,
        "price":          price,
        "original_price": _extract_original_price_html(tile),
        "in_stock":       _is_in_stock(tile),
        "url":            _extract_url(tile),
        "image":          _extract_image(tile),
        "meta":           " | ".join(
            str(impression.get(k)) for k in ("brand", "category") if impression and impression.get(k)
        ),
    }


def _extract_image(tile) -> str | None:
    img = tile.select_one("img")
    if not img:
        return None
    return img.get("data-src") or img.get("src")


def _read_impression(tile) -> dict | None:
    raw = tile.get("data-product-tile-impression")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _extract_price_html(tile) -> str | None:
    for sel in [".ct-price-formatted", ".sales .value", ".price"]:
        el = tile.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            m = re.search(r"(\d+)[,.](\d{2})", text)
            if m:
                return f"{m.group(1)}.{m.group(2)}"
    return None


def _is_in_stock(tile) -> bool:
    # OOS badges are always present in the DOM but carry d-none when the
    # product is available — only treat them as OOS if they are visible.
    for sel in ["[class*='unavailable']", "[class*='out-of-stock']",
                "[class*='outofstock']", "[class*='esgotado']",
                ".ct-availability--outofstock", ".ct-availability--notavailable"]:
        el = tile.select_one(sel)
        if el and "d-none" not in " ".join(el.get("class", [])):
            return False

    # If add-to-cart button exists and is not disabled → in stock
    for btn in tile.find_all("button"):
        classes = " ".join(btn.get("class", [])).lower()
        if "add-to-cart" in classes or "js-add-to-cart" in classes:
            return not btn.has_attr("disabled")

    return True


def _extract_original_price_html(tile) -> str | None:
    for sel in [".ct-old-price", ".price-old", ".price--was",
                ".ct-price-was", ".ct-price__old", "del", ".price del"]:
        el = tile.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            m = re.search(r"(\d+)[,.](\d{2})", text)
            if m:
                return f"{m.group(1)}.{m.group(2)}"
    return None


def _extract_url(tile) -> str | None:
    for a in tile.select("a[href]"):
        href = a.get("href", "")
        if "/produto/" in href or "/product/" in href:
            return href if href.startswith("http") else f"{_BASE_URL}{href}"
    link = tile.select_one("a[href]")
    if link:
        href = link.get("href", "")
        return href if href.startswith("http") else f"{_BASE_URL}{href}" if href.startswith("/") else None
    return None
