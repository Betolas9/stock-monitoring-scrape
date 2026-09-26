from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import db, timeutil
from .common import PRODUCT_SELECT, not_found, product_out

router = APIRouter(prefix="/api/favorites", tags=["favorites"])


@router.get("")
def list_favorites():
    with db.read() as conn:
        rows = db.rows(conn.execute(
            f"SELECT x.*, fv.notify_restock, fv.notify_price, fv.notify_new_store, fv.note,"
            f" fv.created_at AS fav_created_at FROM ({PRODUCT_SELECT}) x JOIN favorites fv ON fv.product_id = x.id"
            " ORDER BY (x.in_stock_count > 0) DESC, fv.created_at DESC"))
    out = []
    for r in rows:
        p = product_out(r)
        p["favorite_settings"] = {
            "target_price": r["target_price"], "notify_restock": bool(r["notify_restock"]),
            "notify_price": bool(r["notify_price"]), "notify_new_store": bool(r["notify_new_store"]),
            "note": r["note"], "created_at": r["fav_created_at"],
        }
        out.append(p)
    return out


class FavoriteBody(BaseModel):
    target_price: float | None = None
    notify_restock: bool = True
    notify_price: bool = True
    notify_new_store: bool = True
    note: str | None = None


@router.put("/{product_id}")
def put_favorite(product_id: str, body: FavoriteBody):
    with db.tx() as conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise not_found("product")
        conn.execute(
            "INSERT INTO favorites(product_id, target_price, notify_restock, notify_price, notify_new_store, note,"
            " created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET"
            " target_price=excluded.target_price, notify_restock=excluded.notify_restock,"
            " notify_price=excluded.notify_price, notify_new_store=excluded.notify_new_store, note=excluded.note",
            (product_id, body.target_price, int(body.notify_restock), int(body.notify_price),
             int(body.notify_new_store), body.note, timeutil.iso()),
        )
    return {"ok": True}


@router.delete("/{product_id}")
def delete_favorite(product_id: str):
    with db.tx() as conn:
        conn.execute("DELETE FROM favorites WHERE product_id=?", (product_id,))
    return {"ok": True}
