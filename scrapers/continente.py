from __future__ import annotations

import json
import logging
import re

import requests
from bs4 import BeautifulSoup

from .base import BaseScraper

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
    def __init__(self, url: str) -> None:
        super().__init__("Continente", url)

    def fetch_products(self) -> dict:
        logger.info(f"Fetching Continente — {self.url}")
        try:
            resp = requests.get(self.url, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            logger.error(f"Continente request failed: {e}")
            return {}

        soup = BeautifulSoup(html, "lxml")
        tiles = _select_first(soup, _TILE_SELECTORS)

        if not tiles:
            logger.warning(
                "Continente: no product tiles found — site structure may have changed. "
                "Enable DEBUG logging to see the page snippet."
            )
            logger.debug(f"Continente page snippet:\n{html[:1200]}")
            return {}

        logger.info(f"Continente: {len(tiles)} tile(s) found")
        products: dict = {}
        for tile in tiles:
            p = _parse_tile(tile)
            if p:
                products[p["id"]] = p

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
    }


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
