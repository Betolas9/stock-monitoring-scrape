from __future__ import annotations

from fastapi import HTTPException

from .. import db


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def page_params(page: int, page_size: int, max_size: int = 200) -> tuple[int, int]:
    page = max(1, page)
    page_size = max(1, min(page_size, max_size))
    return page_size, (page - 1) * page_size


def paged(items: list, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def like(q: str) -> str:
    return "%" + q.strip().replace("%", "").replace("_", "") + "%"


PRODUCT_SELECT = """
SELECT p.*, s.name AS set_name, s.code AS set_code, s.release_date AS release_date,
       COALESCE(s.focus, 0) AS focus,
       (f.product_id IS NOT NULL) AS favorite, f.target_price AS target_price,
       st.name AS best_store_name,
       (SELECT MAX(l.preorder) FROM listings l WHERE l.product_id = p.id AND l.present = 1) AS preorder
FROM products p
LEFT JOIN sets s ON s.id = p.set_id
LEFT JOIN favorites f ON f.product_id = p.id
LEFT JOIN stores st ON st.id = p.best_store
"""


def product_out(r: dict) -> dict:
    r = dict(r)
    for k in ("favorite", "focus", "hidden", "manual", "preorder"):
        if k in r:
            r[k] = bool(r[k])
    return r


def listing_out(r: dict) -> dict:
    r = dict(r)
    for k in ("in_stock", "present", "preorder"):
        if k in r:
            r[k] = bool(r[k])
    return r


def store_out(r: dict) -> dict:
    r = dict(r)
    r["urls"] = db.jload(r.get("urls"), None) or [r["url"]]
    r["options"] = db.jload(r.get("options"), {}) or {}
    for k in ("enabled", "baseline_done", "failure_alerted"):
        if k in r:
            r[k] = bool(r[k])
    return r


def set_out(r: dict) -> dict:
    r = dict(r)
    r["aliases"] = db.jload(r.get("aliases"), []) or []
    for k in ("focus", "auto_created", "date_confirmed"):
        if k in r:
            r[k] = bool(r[k])
    return r
