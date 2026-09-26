"""Scraper registry and factory.

Stores select a scraper via their "type" (platform) field: generic platform
scrapers (shopify, woocommerce, prestashop, jumpseller, shopkit, html) work
for any store on that platform, so adding a new store of a known type is a
data-only change — no code edits.

A store may list several URLs ("urls") — e.g. a few category pages of a
generalist shop. They are scraped a few at a time and merged into a single
result; if any of them fails, the whole check fails (a partial result would
look like the missing products sold out).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .base import BaseScraper, ScrapeError
from .continente import ContinenteScraper
from .toysrus import ToysRusScraper
from .shopify import ShopifyScraper
from .woocommerce import WooCommerceScraper
from .prestashop import PrestaShopScraper
from .elcorteingles import ElCorteInglesScraper
from .conbini import ConbiniScraper
from .wix import WixStoresScraper
from .html_listing import HtmlListingScraper, JumpsellerScraper, ShopkitScraper, WooCommerceHtmlScraper

SCRAPER_TYPES: dict[str, type[BaseScraper]] = {
    "shopify":        ShopifyScraper,
    "woocommerce":    WooCommerceScraper,
    "woocommerce_html": WooCommerceHtmlScraper,
    "prestashop":     PrestaShopScraper,
    "jumpseller":     JumpsellerScraper,
    "shopkit":        ShopkitScraper,
    "html":           HtmlListingScraper,
    "continente":     ContinenteScraper,
    "toysrus":        ToysRusScraper,
    "elcorteingles":  ElCorteInglesScraper,
    "conbini":        ConbiniScraper,
    "wix":            WixStoresScraper,
}


class MultiUrlScraper(BaseScraper):
    """Runs one scraper per URL — a few at a time — and merges the results."""

    PARALLEL = 3

    def __init__(self, name: str, scrapers: list[BaseScraper]) -> None:
        super().__init__(name, scrapers[0].url if scrapers else "")
        self.scrapers = scrapers

    def fetch_products(self) -> dict:
        merged: dict = {}
        with ThreadPoolExecutor(max_workers=self.PARALLEL) as pool:
            # map() re-raises the first ScrapeError, failing the whole check
            for result in pool.map(lambda s: s.fetch_products(), self.scrapers):
                merged.update(result)
        return merged


def site_label(site_key: str, site_cfg: dict) -> str:
    return site_cfg.get("label", site_key.title())


def build_scraper(site_key: str, site_cfg: dict) -> BaseScraper | None:
    """Instantiate the scraper for a store/site config entry, or None if the
    "type" (falling back to the site key itself) is unknown."""
    scraper_type = site_cfg.get("type", site_key)
    cls = SCRAPER_TYPES.get(scraper_type)
    if cls is None:
        return None
    label = site_label(site_key, site_cfg)
    options = site_cfg.get("options") or {}
    urls = site_cfg.get("urls") or [site_cfg["url"]]
    scrapers = [cls(label, u, options) for u in urls]
    return scrapers[0] if len(scrapers) == 1 else MultiUrlScraper(label, scrapers)


__all__ = [
    "SCRAPER_TYPES",
    "BaseScraper",
    "ScrapeError",
    "MultiUrlScraper",
    "build_scraper",
    "site_label",
]
