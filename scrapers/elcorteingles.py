"""El Corte Inglés Portugal.

The site blocks plain python-requests (Akamai), so this uses the
browser-impersonating session. Product data (name, price, buy status) sits in
the page state `window.__MOONSHINE_STATE__` embedded in every listing page —
the visible tiles only get their prices via JavaScript later.

Configure search/category URLs, e.g. https://www.elcorteingles.pt/search-nwx/?s=pokemon
Pages are addressed as a path segment: /search-nwx/2/?s=pokemon
"""
from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import urlsplit, urlunsplit

from .base import BaseScraper, ScrapeError
from .http import HTML_HEADERS, make_session

logger = logging.getLogger(__name__)

_BASE = "https://www.elcorteingles.pt"
_MAX_PAGES = 30
_PAGE_DELAY_S = 0.8
_IN_STOCK_STATUSES = {"ADD"}   # other statuses: sold out / notify me / unavailable


class ElCorteInglesScraper(BaseScraper):
    def __init__(self, label: str = "El Corte Inglés", url: str = "", options: dict | None = None) -> None:
        super().__init__(label, url, options)

    def fetch_products(self) -> dict:
        session = make_session(HTML_HEADERS, impersonate=True)
        products: dict = {}
        total_pages = 1
        page = 1
        while page <= min(total_pages, _MAX_PAGES):
            if page > 1:
                time.sleep(_PAGE_DELAY_S)
            url = _page_url(self.url, page)
            try:
                resp = session.get(url, timeout=40)
                resp.raise_for_status()
            except Exception as e:
                raise ScrapeError(f"El Corte Inglés request failed (page={page}): {e}") from e
            listing = _find_listing(_state(resp.text))
            if listing is None:
                if page == 1:
                    raise ScrapeError("product data not found in the page (layout changed or blocked)")
                break
            total_pages = int((listing.get("page") or {}).get("total_pages") or 1)
            links = _links(resp.text)
            for item in listing["products"]:
                p = _parse(item, links)
                if p:
                    products[p["id"]] = p
            page += 1
        logger.info(f"{self.name}: {len(products)} product(s) from {self.url}")
        return products


def _page_url(url: str, page: int) -> str:
    if page == 1:
        return url
    parts = urlsplit(url)
    path = re.sub(r"/\d+/?$", "/", parts.path.rstrip("/") + "/")
    return urlunsplit((parts.scheme, parts.netloc, f"{path}{page}/", parts.query, ""))


def _state(html: str) -> dict:
    i = html.find("__MOONSHINE_STATE__ =")
    if i < 0:
        return {}
    j = html.find("{", i)
    try:
        return json.JSONDecoder().raw_decode(html[j:])[0]
    except ValueError:
        return {}


def _find_listing(obj):
    """The dict holding {"page": {...}, "products": [{code_a, name, price…}]}."""
    if isinstance(obj, dict):
        prods = obj.get("products")
        if isinstance(prods, list) and prods and isinstance(prods[0], dict) and "code_a" in prods[0]:
            return obj
        for v in obj.values():
            found = _find_listing(v)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_listing(v)
            if found is not None:
                return found
    return None


def _links(html: str) -> dict[str, str]:
    """code_a → product URL, from the tiles' anchors."""
    out: dict[str, str] = {}
    for href, code in re.findall(r'href="(/[^"?]*/(A\d+)-[^"?]*/)', html):
        out.setdefault(code, _BASE + href)
    return out


def _parse(item: dict, links: dict[str, str]) -> dict | None:
    code = item.get("code_a")
    name = item.get("name")
    if not code or not name:
        return None
    price_info = item.get("price") or {}
    price = price_info.get("f_price")
    original = price_info.get("o_price")
    return {
        "id": code,
        "name": name.strip(),
        "price": f"{float(price):.2f}" if price is not None else None,
        "original_price": f"{float(original):.2f}" if original and price and float(original) > float(price) else None,
        "in_stock": item.get("status") in _IN_STOCK_STATUSES,
        "url": links.get(code, f"{_BASE}/search-nwx/?s={code}"),
        "image": None,
        "meta": " | ".join([item.get("brand") or "", ", ".join(item.get("category") or [])]),
    }
