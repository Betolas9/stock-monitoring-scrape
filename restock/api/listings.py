from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import db
from ..matching import cleanup_orphans, refresh_products, rematch_listing
from .common import like, listing_out, not_found, page_params, paged

router = APIRouter(prefix="/api/listings", tags=["listings"])

SORTS = {
    "recent": "l.first_seen DESC",
    "name":   "l.name",
    "price":  "l.price IS NULL, l.price",
    "store":  "s.name, l.name",
    "change": "l.last_change IS NULL, l.last_change DESC",
}


@router.get("")
def list_listings(
    q: str = "", store: str = "", matched: str = "all", kind: str = "", tcg: str = "", stock: str = "all",
    present: bool = True, sort: str = "recent", page: int = 1, page_size: int = 50,
):
    size, offset = page_params(page, page_size)
    where, args = [], []
    if present:
        where.append("l.present = 1")
    if q:
        where.append("l.name LIKE ?")
        args.append(like(q))
    if store:
        where.append("l.store_id = ?")
        args.append(store)
    if matched == "yes":
        where.append("l.product_id IS NOT NULL")
    elif matched == "no":
        where.append("l.product_id IS NULL")
    if kind:
        where.append("l.kind = ?")
        args.append(kind)
    if tcg:
        where.append("l.tcg = ?")
        args.append(tcg)
    if stock == "in":
        where.append("l.in_stock = 1")
    elif stock == "out":
        where.append("l.in_stock = 0")
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    order = SORTS.get(sort, SORTS["recent"])
    with db.read() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM listings l{sql_where}", args).fetchone()[0]
        items = db.rows(conn.execute(
            "SELECT l.*, s.name AS store_name, p.title AS product_title FROM listings l"
            " JOIN stores s ON s.id = l.store_id LEFT JOIN products p ON p.id = l.product_id"
            f"{sql_where} ORDER BY {order} LIMIT ? OFFSET ?", args + [size, offset]))
    return paged([listing_out(r) for r in items], total, page, size)


@router.get("/{listing_id}/history")
def listing_history(listing_id: int):
    with db.read() as conn:
        return db.rows(conn.execute(
            "SELECT ts, price, in_stock FROM listing_history WHERE listing_id=? ORDER BY ts", (listing_id,)))


class ListingPatch(BaseModel):
    # product_id: link to that product; None (explicitly) → keep unmatched
    product_id: str | None = None
    # "auto" hands the listing back to the automatic matcher
    mode: str | None = None


@router.patch("/{listing_id}")
def patch_listing(listing_id: int, body: ListingPatch):
    fields = body.model_dump(exclude_unset=True)
    with db.tx() as conn:
        listing = db.row(conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)))
        if not listing:
            raise not_found("listing")
        touched = {listing["product_id"]}
        if fields.get("mode") == "auto":
            listing["match_mode"] = "auto"
            conn.execute("UPDATE listings SET match_mode='auto' WHERE id=?", (listing_id,))
            touched.add(rematch_listing(conn, listing))
        elif "product_id" in fields:
            pid = fields["product_id"]
            if pid and not conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone():
                raise not_found("product")
            conn.execute("UPDATE listings SET product_id=?, match_mode=? WHERE id=?",
                         (pid, "manual" if pid else "none", listing_id))
            touched.add(pid)
        cleanup_orphans(conn)
        refresh_products(conn, touched)
        out = db.row(conn.execute(
            "SELECT l.*, s.name AS store_name, p.title AS product_title FROM listings l"
            " JOIN stores s ON s.id = l.store_id LEFT JOIN products p ON p.id = l.product_id WHERE l.id=?",
            (listing_id,)))
    return listing_out(out)
