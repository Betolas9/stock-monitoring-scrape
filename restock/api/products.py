from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, timeutil
from ..matching import cleanup_orphans, refresh_products
from ..matching.text import slug
from .common import PRODUCT_SELECT, like, listing_out, not_found, page_params, paged, product_out

router = APIRouter(prefix="/api/products", tags=["products"])

SORTS = {
    "stock":      "(p.in_stock_count > 0) DESC, p.store_count DESC, p.title",
    "price":      "COALESCE(p.best_price, p.min_price) IS NULL, COALESCE(p.best_price, p.min_price), p.title",
    "price_desc": "COALESCE(p.best_price, p.min_price) IS NULL, COALESCE(p.best_price, p.min_price) DESC",
    "stores":     "p.store_count DESC, p.in_stock_count DESC, p.title",
    "name":       "p.title",
    "change":     "p.change_30d IS NULL, p.change_30d, p.title",
    "recent":     "p.created_at DESC",
    "release":    "s.release_date IS NULL, s.release_date DESC, p.title",
    "activity":   "p.last_change IS NULL, p.last_change DESC",
}


@router.get("")
def list_products(
    q: str = "", tcg: str = "", type: str = "", lang: str = "", set: str = "", store: str = "",
    stock: str = "all", focus: bool = False, fav: bool = False, preorder: bool = False,
    hidden: bool = False, sort: str = "stock", page: int = 1, page_size: int = 48,
):
    size, offset = page_params(page, page_size)
    where, args = ["p.hidden = ?"], [int(hidden)]
    if q:
        where.append("(p.title LIKE ? OR p.id IN (SELECT product_id FROM listings WHERE name LIKE ?))")
        args += [like(q), like(q)]
    for col, val in (("p.tcg", tcg), ("p.type", type), ("p.lang", lang), ("p.set_id", set)):
        if val:
            vals = [v for v in val.split(",") if v]
            where.append(f"{col} IN ({','.join('?' * len(vals))})")
            args += vals
    if store:
        where.append("p.id IN (SELECT product_id FROM listings WHERE store_id = ? AND present = 1)")
        args.append(store)
    if stock == "in":
        where.append("p.in_stock_count > 0")
    elif stock == "out":
        where.append("p.in_stock_count = 0")
    if focus:
        where.append("s.focus = 1")
    if fav:
        where.append("f.product_id IS NOT NULL")
    if preorder:
        where.append("p.id IN (SELECT product_id FROM listings WHERE preorder = 1 AND present = 1)")
    if not fav and not hidden:
        # products whose every listing vanished are only interesting when favourited
        where.append("(p.store_count > 0 OR f.product_id IS NOT NULL)")
    sql_where = " WHERE " + " AND ".join(where)
    order = SORTS.get(sort, SORTS["stock"])
    with db.read() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM products p LEFT JOIN sets s ON s.id=p.set_id"
            " LEFT JOIN favorites f ON f.product_id=p.id" + sql_where, args,
        ).fetchone()[0]
        items = db.rows(conn.execute(f"{PRODUCT_SELECT}{sql_where} ORDER BY {order} LIMIT ? OFFSET ?",
                                     args + [size, offset]))
    return paged([product_out(r) for r in items], total, page, size)


@router.get("/{product_id}")
def get_product(product_id: str):
    with db.read() as conn:
        p = db.row(conn.execute(f"{PRODUCT_SELECT} WHERE p.id = ?", (product_id,)))
        if not p:
            raise not_found("product")
        listings = db.rows(conn.execute(
            "SELECT l.*, s.name AS store_name, s.platform AS store_platform, s.enabled AS store_enabled"
            " FROM listings l JOIN stores s ON s.id = l.store_id WHERE l.product_id = ?"
            " ORDER BY l.present DESC, l.in_stock DESC, l.price IS NULL, l.price",
            (product_id,),
        ))
        fav = db.row(conn.execute("SELECT * FROM favorites WHERE product_id = ?", (product_id,)))
        events = db.rows(conn.execute(
            "SELECT e.*, s.name AS store_name FROM events e LEFT JOIN stores s ON s.id = e.store_id"
            " WHERE e.product_id = ? ORDER BY e.id DESC LIMIT 50",
            (product_id,),
        ))
        set_row = db.row(conn.execute("SELECT * FROM sets WHERE id = ?", (p["set_id"],))) if p["set_id"] else None
    return {
        **product_out(p),
        "listings": [listing_out(r) for r in listings],
        "favorite_settings": fav,
        "events": events,
        "set": set_row,
    }


@router.get("/{product_id}/history")
def product_history(product_id: str, days: int = 90):
    """Step series of the cheapest in-stock price (and cheapest listed price)
    over time, plus per-store series, for the price chart."""
    with db.read() as conn:
        listings = db.rows(conn.execute(
            "SELECT l.id, l.store_id, s.name AS store_name FROM listings l JOIN stores s ON s.id = l.store_id"
            " WHERE l.product_id = ?", (product_id,)))
        if not listings:
            return {"points": [], "series": [], "stats": None}
        ids = [r["id"] for r in listings]
        hist = db.rows(conn.execute(
            f"SELECT listing_id, ts, price, in_stock FROM listing_history WHERE listing_id IN ({','.join('?' * len(ids))})"
            " ORDER BY ts", ids))
    store_of = {r["id"]: (r["store_id"], r["store_name"]) for r in listings}
    since = timeutil.iso(timeutil.now() - timedelta(days=days)) if days > 0 else ""

    state: dict[int, tuple[float | None, int]] = {}
    points: list[dict] = []
    series: dict[int, list[dict]] = {i: [] for i in ids}

    def snapshot(ts: str) -> dict:
        in_stock = [(p, lid) for lid, (p, s) in state.items() if s and p is not None]
        listed = [p for p, _s in state.values() if p is not None]
        best = min(in_stock) if in_stock else None
        return {"ts": ts, "best": best[0] if best else None,
                "best_store": store_of[best[1]][1] if best else None,
                "min": min(listed) if listed else None}

    i = 0
    while i < len(hist):
        ts = hist[i]["ts"]
        while i < len(hist) and hist[i]["ts"] == ts:
            h = hist[i]
            state[h["listing_id"]] = (h["price"], h["in_stock"])
            if ts >= since:
                series[h["listing_id"]].append({"ts": ts, "price": h["price"], "in_stock": bool(h["in_stock"])})
            i += 1
        snap = snapshot(ts)
        if ts < since:
            points = [{**snap, "ts": since}]  # carry the state at the window start
            for lid, (p, s) in state.items():
                series[lid] = [{"ts": since, "price": p, "in_stock": bool(s)}]
            continue
        if points and points[-1]["best"] == snap["best"] and points[-1]["min"] == snap["min"] \
                and points[-1]["best_store"] == snap["best_store"]:
            continue
        points.append(snap)
    now = timeutil.iso()
    if points:
        points.append({**points[-1], "ts": now})

    stats = _stats(points)
    return {
        "points": points,
        "series": [
            {"listing_id": lid, "store_id": store_of[lid][0], "store_name": store_of[lid][1],
             "points": pts + ([{**pts[-1], "ts": now}] if pts else [])}
            for lid, pts in series.items() if pts
        ],
        "stats": stats,
    }


def _stats(points: list[dict]) -> dict | None:
    """Lowest / highest in-stock price in the window and the time-weighted
    median ("usual price")."""
    timed = []
    for a, b in zip(points, points[1:]):
        if a["best"] is None:
            continue
        dur = (timeutil.parse(b["ts"]) - timeutil.parse(a["ts"])).total_seconds()
        timed.append((a["best"], max(dur, 1.0), a))
    if not timed:
        return None
    low = min(timed, key=lambda t: t[0])
    high = max(timed, key=lambda t: t[0])
    total = sum(d for _p, d, _a in timed)
    acc, usual = 0.0, timed[0][0]
    for price, dur, _a in sorted(timed, key=lambda t: t[0]):
        acc += dur
        if acc >= total / 2:
            usual = price
            break
    changes = sum(1 for a, b in zip(timed, timed[1:]) if a[0] != b[0])
    return {"low": low[0], "low_ts": low[2]["ts"], "low_store": low[2]["best_store"],
            "high": high[0], "high_ts": high[2]["ts"], "usual": usual, "changes": changes}


class ProductPatch(BaseModel):
    title: str | None = None
    set_id: str | None = None
    type: str | None = None
    lang: str | None = None
    image: str | None = None
    hidden: bool | None = None


@router.patch("/{product_id}")
def patch_product(product_id: str, body: ProductPatch):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return get_product(product_id)
    with db.tx() as conn:
        if not conn.execute("SELECT 1 FROM products WHERE id=?", (product_id,)).fetchone():
            raise not_found("product")
        sets_sql = ", ".join(f"{k}=?" for k in fields)
        vals = [int(v) if isinstance(v, bool) else v for v in fields.values()]
        # Any hand edit (except just hiding) protects it from the matcher
        manual = 1 if set(fields) - {"hidden"} else None
        conn.execute(f"UPDATE products SET {sets_sql}, manual=COALESCE(?, manual) WHERE id=?",
                     vals + [manual, product_id])
    return get_product(product_id)


class ProductCreate(BaseModel):
    title: str
    tcg: str | None = None
    set_id: str | None = None
    type: str | None = None
    lang: str = "en"
    listing_ids: list[int] = []


@router.post("")
def create_product(body: ProductCreate):
    with db.tx() as conn:
        base = "custom-" + (slug(body.title) or "product")
        pid, n = base, 2
        while conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone():
            pid, n = f"{base}-{n}", n + 1
        image = None
        if body.listing_ids:
            r = conn.execute(
                f"SELECT image FROM listings WHERE id IN ({','.join('?' * len(body.listing_ids))}) AND image IS NOT NULL LIMIT 1",
                body.listing_ids).fetchone()
            image = r["image"] if r else None
        conn.execute(
            "INSERT INTO products(id, tcg, set_id, type, lang, variant, title, image, manual, created_at)"
            " VALUES(?,?,?,?,?,'',?,?,1,?)",
            (pid, body.tcg, body.set_id, body.type, body.lang, body.title.strip(), image, timeutil.iso()),
        )
        old = _link_listings(conn, body.listing_ids, pid)
        cleanup_orphans(conn)
        refresh_products(conn, old | {pid})
    return get_product(pid)


class MergeBody(BaseModel):
    into: str


@router.post("/{product_id}/merge")
def merge_product(product_id: str, body: MergeBody):
    """Move every listing of this product into another one and delete it."""
    if body.into == product_id:
        raise HTTPException(400, "cannot merge a product into itself")
    with db.tx() as conn:
        for pid in (product_id, body.into):
            if not conn.execute("SELECT 1 FROM products WHERE id=?", (pid,)).fetchone():
                raise not_found(f"product {pid}")
        conn.execute("UPDATE listings SET product_id=?, match_mode='manual' WHERE product_id=?", (body.into, product_id))
        fav = conn.execute("SELECT 1 FROM favorites WHERE product_id=?", (body.into,)).fetchone()
        if not fav:
            conn.execute("UPDATE favorites SET product_id=? WHERE product_id=?", (body.into, product_id))
        conn.execute("DELETE FROM favorites WHERE product_id=?", (product_id,))
        conn.execute("UPDATE events SET product_id=? WHERE product_id=?", (body.into, product_id))
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.execute("UPDATE products SET manual=1 WHERE id=?", (body.into,))
        refresh_products(conn, [body.into])
    return get_product(body.into)


@router.delete("/{product_id}")
def delete_product(product_id: str):
    """Delete a product; its listings become unmatched and stay that way."""
    with db.tx() as conn:
        conn.execute("UPDATE listings SET product_id=NULL, match_mode='none' WHERE product_id=?", (product_id,))
        conn.execute("DELETE FROM favorites WHERE product_id=?", (product_id,))
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
    return {"ok": True}


def _link_listings(conn, listing_ids: list[int], product_id: str) -> set[str]:
    old: set[str] = set()
    for lid in listing_ids:
        r = conn.execute("SELECT product_id FROM listings WHERE id=?", (lid,)).fetchone()
        if r and r["product_id"]:
            old.add(r["product_id"])
        conn.execute("UPDATE listings SET product_id=?, match_mode='manual' WHERE id=?", (product_id, lid))
    return old
