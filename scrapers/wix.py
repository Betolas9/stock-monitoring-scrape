"""Wix Stores sites.

Wix renders store galleries in the browser; the data comes from the site's
storefront GraphQL API, authorised with the public per-visitor "instance"
token that every Wix site hands out at /_api/v1/access-tokens.
Configure the site root (e.g. https://www.arkay.pt); all visible products of
the store are read, 100 per request.
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit

from .base import BaseScraper, ScrapeError
from .http import JSON_HEADERS, make_session

logger = logging.getLogger(__name__)

_STORES_APP_ID = "1380b703-ce81-ff05-f115-39571d94dfcd"
_ALL_PRODUCTS = "00000000-000000-000000-000000000001"
_PAGE = 100
_QUERY = """query getFilteredProducts($mainCollectionId: String!, $offset: Int, $limit: Int) {
  catalog { category(categoryId: $mainCollectionId) {
    productsWithMetaData(limit: $limit, offset: $offset, onlyVisible: true) {
      totalCount
      list { id name urlPart isInStock price comparePrice media { url } }
    } } } }"""


class WixStoresScraper(BaseScraper):
    def fetch_products(self) -> dict:
        parts = urlsplit(self.url)
        site = f"{parts.scheme}://{parts.netloc}"
        session = make_session(JSON_HEADERS)
        try:
            tokens = session.get(f"{site}/_api/v1/access-tokens", timeout=25).json()
            instance = tokens["apps"][_STORES_APP_ID]["instance"]
        except Exception as e:
            raise ScrapeError(f"could not get the Wix Stores access token: {e}") from e

        products: dict = {}
        offset, total = 0, None
        while total is None or offset < total:
            if offset:
                time.sleep(0.3)
            try:
                resp = session.post(
                    f"{site}/_api/wix-ecommerce-storefront-web/api",
                    json={"query": _QUERY, "operationName": "getFilteredProducts",
                          "variables": {"mainCollectionId": _ALL_PRODUCTS, "offset": offset, "limit": _PAGE}},
                    headers={"Authorization": instance}, timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()["data"]["catalog"]["category"]["productsWithMetaData"]
            except Exception as e:
                raise ScrapeError(f"Wix Stores API error (offset={offset}): {e}") from e
            total = int(data.get("totalCount") or 0)
            batch = data.get("list") or []
            if not batch:
                break
            for item in batch:
                p = _parse(item, site)
                if p:
                    products[p["id"]] = p
            offset += len(batch)
        logger.info(f"{self.name}: {len(products)} product(s)")
        return products


def _parse(item: dict, site: str) -> dict | None:
    if not item.get("id") or not item.get("name"):
        return None
    price = item.get("price")
    compare = item.get("comparePrice")
    media = item.get("media") or []
    image = None
    if media and media[0].get("url"):
        url = media[0]["url"]
        image = url if url.startswith("http") else f"https://static.wixstatic.com/media/{url}"
    return {
        "id": item["id"],
        "name": item["name"].strip(),
        # 0.0 means "price on request" in these stores
        "price": f"{float(price):.2f}" if price else None,
        "original_price": f"{float(compare):.2f}" if compare and price and compare > price else None,
        "in_stock": bool(item.get("isInStock")),
        "url": f"{site}/product-page/{item.get('urlPart', '')}",
        "image": image,
        "meta": "",
    }
