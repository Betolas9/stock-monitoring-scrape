from __future__ import annotations

from fastapi import APIRouter

from .. import db, runtime, timeutil
from .common import page_params, paged

router = APIRouter(prefix="/api", tags=["activity"])


@router.get("/events")
def list_events(type: str = "", store: str = "", product: str = "", alerted: bool = False,
                page: int = 1, page_size: int = 50):
    size, offset = page_params(page, page_size)
    where, args = [], []
    if type:
        types = [t for t in type.split(",") if t]
        where.append(f"e.type IN ({','.join('?' * len(types))})")
        args += types
    if store:
        where.append("e.store_id = ?")
        args.append(store)
    if product:
        where.append("e.product_id = ?")
        args.append(product)
    if alerted:
        where.append("e.alert_reason IS NOT NULL")
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    with db.read() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM events e{sql_where}", args).fetchone()[0]
        items = db.rows(conn.execute(
            "SELECT e.*, s.name AS store_name, p.title AS product_title, p.image AS product_image"
            " FROM events e LEFT JOIN stores s ON s.id = e.store_id LEFT JOIN products p ON p.id = e.product_id"
            f"{sql_where} ORDER BY e.id DESC LIMIT ? OFFSET ?", args + [size, offset]))
    for it in items:
        it["in_stock"] = bool(it["in_stock"]) if it["in_stock"] is not None else None
    return paged(items, total, page, size)


@router.get("/notifications")
def list_notifications(status: str = "", channel: str = "", page: int = 1, page_size: int = 50):
    size, offset = page_params(page, page_size)
    where, args = [], []
    if status:
        where.append("status = ?")
        args.append(status)
    if channel:
        where.append("channel = ?")
        args.append(channel)
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    with db.read() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM notifications{sql_where}", args).fetchone()[0]
        items = db.rows(conn.execute(
            f"SELECT id, created_at, channel, target, status, attempts, next_attempt_at, sent_at, last_error, summary"
            f" FROM notifications{sql_where} ORDER BY id DESC LIMIT ? OFFSET ?", args + [size, offset]))
    return paged(items, total, page, size)


@router.post("/notifications/{notification_id}/retry")
def retry_notification(notification_id: int):
    with db.tx() as conn:
        conn.execute("UPDATE notifications SET status='pending', attempts=0, next_attempt_at=?,"
                     " created_at=? WHERE id=?", (timeutil.iso(), timeutil.iso(), notification_id))
    if runtime.dispatcher:
        runtime.dispatcher.wake()
    return {"ok": True}


@router.post("/notifications/retry-failed")
def retry_failed():
    with db.tx() as conn:
        n = conn.execute("UPDATE notifications SET status='pending', attempts=0, next_attempt_at=?, created_at=?"
                         " WHERE status='failed'", (timeutil.iso(), timeutil.iso())).rowcount
    if runtime.dispatcher:
        runtime.dispatcher.wake()
    return {"ok": True, "count": n}
