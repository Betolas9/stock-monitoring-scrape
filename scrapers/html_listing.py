"""Selector-driven scraper for server-rendered category pages.

Covers platforms without a public catalog API (Jumpseller, Shopkit, custom
shops). Each store picks a preset via its platform type and can override any
selector in its config "options", e.g.:

    "options": {
        "tile": "div.product",
        "name": "h3 a",
        "price": ".product-price",
        "oos_selector": ".product-out-of-stock"
    }

Pagination appends ?page=N (configurable via "page_param") and stops when a
page brings no new product IDs — many platforms clamp out-of-range pages to
the last page instead of returning an empty listing.
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapeError
from .http import HTML_HEADERS, make_session

logger = logging.getLogger(__name__)

# Visible texts that mean the product cannot be bought right now
OOS_MARKERS = (
    "esgotado", "esgotada", "sem stock", "sem estoque", "fora de stock", "indisponível",
    "indisponivel", "out of stock", "sold out", "agotado", "não disponível",
)

PRESETS: dict[str, dict] = {
    "shopkit": {
        "tile": "article.product-list, article.product",
        "id_attr": "data-id",
        "name": ".product-list-details h2 a, .product-info h2, h2",
        "link": "a[href*='/product/']",
        "price": ".price",
        "old_price": ".price del, .price .old-price, .price-old, .price .promo-old",
        "image": "img",
        "oos_selector": ".product-badges .out_of_stock, .product-badges .badge-danger",
        "oos_class": "out_of_stock",
        # Shopkit pages by path offset (/catalog/20, /catalog/40…)
        "pagination": "next",
    },
    "jumpseller": {
        "tile": "article.product-block, div.product-block",
        "id_attr": "data-product-id",
        "name": ".product-block__name, .product-block__title, [data-product-name]",
        "link": "a.product-block__anchor, a.product-block__name, .product-block__title a, a[href]",
        "price": ".product-block__price--new, .product-block__price",
        "old_price": ".product-block__price--old, .product-block__price del",
        "image": "img.product-block__image, img",
        "oos_selector": ".product-block__label--status",
        # Jumpseller rate-limits listing/search pages (HTTP 429)
        "delay": 2.5,
    },
    # WooCommerce shops whose Store API is disabled: classic theme loop
    "woocommerce_html": {
        "tile": "li.product, div.product.type-product",
        "id_class_prefix": "post-",
        "name": ".woocommerce-loop-product__title, h2, h3",
        "link": "a.woocommerce-LoopProduct-link, a[href]",
        "price": ".price",
        "old_price": ".price del",
        "image": "img",
        "oos_class": "outofstock",
        "meta_class_prefix": "product_cat-",
        "pagination": "next",
        "next_selector": "a.next.page-numbers",
        "max_pages": 60,
    },
    "html": {},
}

_DEFAULTS = {
    "tile": "article, .product",
    "id_attr": "",
    "name": "h2 a, h3 a, a[title]",
    "link": "a[href]",
    "price": ".price",
    "old_price": "del, .old-price",
    "image": "img",
    "oos_selector": "",
    "oos_class": "",        # a class on the tile itself that means sold out
    "id_class_prefix": "",  # take the id from a tile class, e.g. "post-" → post-1234
    "meta_class_prefix": "",  # tile classes with this prefix are passed as meta (categories)
    # "query": ?page=N  |  "next": follow the page's "next" link  |
    # "path": append page_path to the URL, e.g. "/pag{n}" → …/pag2
    "pagination": "query",
    "page_param": "page",
    "page_path": "/page/{n}",
    "name_attr": "",        # read the name from this attribute of the name element
    "next_selector": "",
    "max_pages": 30,
    "delay": 0.6,
}

_PRICE_RE = re.compile(r"(\d{1,3}(?:[.\s]\d{3})*|\d+)[,.](\d{2})(?!\d)")


class HtmlListingScraper(BaseScraper):
    preset = "html"

    def __init__(self, label: str, url: str, options: dict | None = None) -> None:
        super().__init__(label, url, options)
        self.cfg = {**_DEFAULTS, **PRESETS.get(self.preset, {}), **(options or {})}

    def fetch_products(self) -> dict:
        session = make_session(HTML_HEADERS, impersonate=bool(self.options.get("impersonate")))
        all_products: dict = {}
        max_pages = int(self.cfg["max_pages"])

        next_url: str | None = self.url
        for page in range(1, max_pages + 1):
            if self.cfg["pagination"] == "next":
                if not next_url:
                    break
                page_url = next_url
            elif self.cfg["pagination"] == "path":
                page_url = self.url if page == 1 else _with_path(self.url, self.cfg["page_path"].format(n=page))
            else:
                page_url = self.url if page == 1 else _with_param(self.url, self.cfg["page_param"], page)
            if page > 1:
                time.sleep(float(self.cfg["delay"]))
            try:
                resp = session.get(page_url, timeout=25)
                if resp.status_code == 404 and page > 1:
                    break
                resp.raise_for_status()
            except Exception as e:
                raise ScrapeError(f"request failed (page={page}): {e}") from e

            if _looks_like_challenge(resp.text):
                raise ScrapeError("blocked by an anti-bot challenge page (Cloudflare or similar)")

            soup = BeautifulSoup(resp.text, "lxml")
            next_url = _next_link(soup, page_url, self.cfg["next_selector"])
            tiles = soup.select(self.cfg["tile"])
            if not tiles:
                if page == 1:
                    logger.warning(f"{self.name}: no product tiles on {page_url}")
                break

            new = 0
            for tile in tiles:
                p = self._parse_tile(tile, page_url)
                if p and p["id"] not in all_products:
                    all_products[p["id"]] = p
                    new += 1
            logger.debug(f"{self.name}: page {page} → {len(tiles)} tile(s), {new} new")
            if new == 0:
                break

        logger.info(f"{self.name}: {len(all_products)} product(s) from {self.url}")
        return all_products

    # ------------------------------------------------------------------ parse

    def _parse_tile(self, tile, page_url: str) -> dict | None:
        cfg = self.cfg
        name_el = tile.select_one(cfg["name"])
        if name_el is None:
            return None
        name = (
            (name_el.get(cfg["name_attr"]) if cfg["name_attr"] else None)
            or name_el.get("data-product-name")
            or name_el.get_text(" ", strip=True)
            or name_el.get("title", "")
        ).strip()
        if not name:
            return None

        link_el = name_el if name_el.name == "a" and name_el.get("href") else tile.select_one(cfg["link"])
        url = urljoin(page_url, link_el.get("href")) if link_el is not None and link_el.get("href") else ""

        pid = tile.get(cfg["id_attr"]) if cfg["id_attr"] else None
        classes = tile.get("class", [])
        if not pid and cfg["id_class_prefix"]:
            pid = next((c[len(cfg["id_class_prefix"]):] for c in classes if c.startswith(cfg["id_class_prefix"])), None)
        if not pid:
            pid = _id_from_url(url) or self._generate_id(name)

        old_price = None
        price_el = tile.select_one(cfg["price"]) if cfg["price"] else None
        if price_el is not None:
            old_el = price_el.select_one(cfg["old_price"]) if cfg["old_price"] else None
            if old_el is not None:
                old_price = _parse_price(old_el.get_text(" ", strip=True))
                old_el.extract()
            price = _parse_price(price_el.get_text(" ", strip=True))
        else:
            price = None
        if old_price is None and cfg["old_price"]:
            el = tile.select_one(cfg["old_price"])
            if el is not None:
                old_price = _parse_price(el.get_text(" ", strip=True))
        if old_price and price and float(old_price) <= float(price):
            old_price = None

        return {
            "id":             str(pid),
            "name":           name,
            "price":          price,
            "original_price": old_price,
            "in_stock":       self._in_stock(tile),
            "url":            url,
            "image":          _image(tile, cfg["image"], page_url),
            "meta":           ", ".join(
                c[len(cfg["meta_class_prefix"]):].replace("-", " ")
                for c in classes if cfg["meta_class_prefix"] and c.startswith(cfg["meta_class_prefix"])
            ),
        }

    def _in_stock(self, tile) -> bool:
        if self.cfg["oos_class"] and self.cfg["oos_class"] in tile.get("class", []):
            return False
        sel = self.cfg["oos_selector"]
        if sel:
            for el in tile.select(sel):
                classes = " ".join(el.get("class", []))
                if "hidden" in classes or "d-none" in classes:
                    continue
                text = el.get_text(" ", strip=True).lower()
                # A status label only means OOS when it says so; a bare
                # out-of-stock marker element (no text) counts on its own.
                if not text or any(m in text for m in OOS_MARKERS):
                    return False
        text = tile.get_text(" ", strip=True).lower()
        return not any(m in text for m in OOS_MARKERS)


class WooCommerceHtmlScraper(HtmlListingScraper):
    preset = "woocommerce_html"


class ShopkitScraper(HtmlListingScraper):
    preset = "shopkit"


class JumpsellerScraper(HtmlListingScraper):
    preset = "jumpseller"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _with_param(url: str, key: str, value) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query[key] = str(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


_NEXT_TEXTS = {">", "»", "›", "next", "seguinte", "próxima", "proxima", "próximo", "proximo", "next page"}


def _with_path(url: str, suffix: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") + suffix, parts.query, parts.fragment))


def _next_link(soup, page_url: str, selector: str) -> str | None:
    candidates = soup.select(selector) if selector else soup.select("a[rel=next], link[rel=next]")
    if not candidates:
        for a in soup.select(".pagination a, .pages a, nav a, .pager a"):
            label = (a.get_text(strip=True) or a.get("aria-label", "")).strip().lower()
            if label in _NEXT_TEXTS:
                candidates = [a]
                break
    href = candidates[0].get("href") if candidates else None
    if not href or href.startswith("#") or href.startswith("javascript"):
        return None
    url = urljoin(page_url, href)
    return None if url == page_url else url


def _parse_price(text: str) -> str | None:
    m = _PRICE_RE.search(text or "")
    if not m:
        return None
    whole = re.sub(r"[.\s]", "", m.group(1))
    return f"{int(whole)}.{m.group(2)}"


def _id_from_url(url: str) -> str | None:
    if not url:
        return None
    path = urlsplit(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] or None


def _image(tile, selector: str, page_url: str) -> str | None:
    img = tile.select_one(selector) if selector else None
    if img is None:
        return None
    for attr in ("data-src", "data-original", "data-lazy", "src"):
        val = img.get(attr)
        if val and "no-img" not in val and not val.startswith("data:"):
            # responsive-image templates (ePages: …&width={width})
            return urljoin(page_url, val.replace("{width}", "600"))
    srcset = img.get("srcset") or img.get("data-srcset")
    if srcset:
        return urljoin(page_url, srcset.split(",")[0].split()[0])
    return None


def _looks_like_challenge(html: str) -> bool:
    head = html[:3000].lower()
    return "just a moment..." in head or "cf-challenge" in head or "attention required!" in head
