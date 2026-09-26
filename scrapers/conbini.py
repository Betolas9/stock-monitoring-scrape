"""Conbini (conbini.pt).

Listing pages are rendered client-side (Alpine.js) from data embedded in the
page: `productHTML: "<escaped html>"`, whose tiles each carry a `product`
attribute with the product as JSON (name, price, discount, stock count).
Configure listing URLs such as https://conbini.pt/products/Pokemon%20Card%20Game
"""
from __future__ import annotations

import json
import logging

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeError
from .http import HTML_HEADERS, make_session

logger = logging.getLogger(__name__)

_BASE = "https://conbini.pt"


class ConbiniScraper(BaseScraper):
    def fetch_products(self) -> dict:
        session = make_session(HTML_HEADERS, impersonate=bool(self.options.get("impersonate")))
        try:
            resp = session.get(self.url, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            raise ScrapeError(f"Conbini request failed: {e}") from e

        html = resp.text
        i = html.find("productHTML:")
        if i < 0:
            raise ScrapeError("product data not found in the page (layout changed?)")
        j = html.find('"', i)
        try:
            fragment = json.JSONDecoder().raw_decode(html[j:])[0]  # the JS string literal
        except ValueError as e:
            raise ScrapeError(f"could not decode the embedded product list: {e}") from e

        products: dict = {}
        soup = BeautifulSoup(fragment, "lxml")
        for tile in soup.select("[product]"):
            try:
                item = json.loads(tile["product"])
            except (ValueError, KeyError):
                continue
            p = _parse(item, tile)
            if p:
                products[p["id"]] = p
        logger.info(f"{self.name}: {len(products)} product(s) from {self.url}")
        return products


def _parse(item: dict, tile) -> dict | None:
    ref = str(item.get("reference") or item.get("id") or "")
    name = (item.get("name") or "").strip()
    if not ref or not name or not item.get("enabled", 1):
        return None
    try:
        pvp = float(item.get("pvp"))
    except (TypeError, ValueError):
        pvp = None
    discount = float(item.get("discount") or 0)
    price = round(pvp * (1 - discount / 100), 2) if pvp is not None else None
    link = tile.select_one("a[href]")
    url = link["href"] if link else f"{_BASE}/product/{item.get('slug', ref)}"
    if url.startswith("/"):
        url = _BASE + url
    img = tile.select_one("img[src]")
    availability = (item.get("availability") or "").lower()
    in_stock = (item.get("stock") or 0) > 0 or "pre" in availability  # pre-orders are buyable
    return {
        "id": ref,
        "name": name,
        "price": f"{price:.2f}" if price is not None else None,
        "original_price": f"{pvp:.2f}" if discount and pvp is not None else None,
        "in_stock": bool(in_stock),
        "url": url,
        "image": img["src"] if img else None,
        "meta": item.get("brand") or "",
    }
