"""Sets = the release calendar. Each set can be marked as "focus" to get
alerts for everything that happens to its products."""
from __future__ import annotations

import logging
import re
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, timeutil
from ..matching import catalog, cleanup_orphans, rematch_all
from ..matching.rules import TCGS
from .common import not_found, set_out

router = APIRouter(prefix="/api/sets", tags=["sets"])
logger = logging.getLogger(__name__)

SET_SELECT = """
SELECT s.*,
  (SELECT COUNT(*) FROM products p WHERE p.set_id = s.id AND p.store_count > 0) AS product_count,
  (SELECT COUNT(*) FROM listings l WHERE l.set_id = s.id AND l.present = 1) AS listing_count,
  (SELECT COUNT(*) FROM listings l WHERE l.set_id = s.id AND l.present = 1 AND l.in_stock = 1) AS in_stock_count,
  (SELECT COUNT(*) FROM listings l WHERE l.set_id = s.id AND l.present = 1 AND l.preorder = 1) AS preorder_count,
  (SELECT MIN(p.best_price) FROM products p WHERE p.set_id = s.id) AS min_best_price
FROM sets s
"""


@router.get("")
def list_sets(tcg: str = "", q: str = ""):
    where, args = [], []
    if tcg:
        where.append("s.tcg = ?")
        args.append(tcg)
    if q:
        where.append("(s.name LIKE ? OR s.code LIKE ?)")
        args += [f"%{q}%", f"%{q}%"]
    sql = SET_SELECT + (" WHERE " + " AND ".join(where) if where else "") + \
        " ORDER BY s.release_date IS NULL, s.release_date DESC, s.name"
    with db.read() as conn:
        return [set_out(r) for r in db.rows(conn.execute(sql, args))]


def _get(set_id: str) -> dict:
    with db.read() as conn:
        r = db.row(conn.execute(SET_SELECT + " WHERE s.id = ?", (set_id,)))
    if not r:
        raise not_found("set")
    return set_out(r)


@router.get("/{set_id}")
def get_set(set_id: str):
    return _get(set_id)


class SetBody(BaseModel):
    tcg: str | None = None
    code: str | None = None
    name: str | None = None
    aliases: list[str] | None = None
    release_date: str | None = None
    date_confirmed: bool | None = None
    focus: bool | None = None
    notes: str | None = None


def _check(fields: dict) -> None:
    if "tcg" in fields and fields["tcg"] not in TCGS:
        raise HTTPException(400, f"unknown TCG '{fields['tcg']}'")
    d = fields.get("release_date")
    if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
        raise HTTPException(400, "release_date must be YYYY-MM-DD")


def _rematch_async() -> None:
    """New/renamed sets can match listings that were unmatched before."""
    def work():
        try:
            with db.tx() as conn:
                rematch_all(conn, only_unmatched=True)
        except Exception:
            logger.exception("re-matching after set change failed")
    threading.Thread(target=work, name="rematch", daemon=True).start()


@router.post("")
def create_set(body: SetBody):
    fields = body.model_dump(exclude_unset=True)
    if not fields.get("tcg") or not fields.get("name"):
        raise HTTPException(400, "tcg and name are required")
    _check(fields)
    sid = catalog.set_id_for(fields["tcg"], fields.get("code"), fields["name"])
    with db.tx() as conn:
        if conn.execute("SELECT 1 FROM sets WHERE id=?", (sid,)).fetchone():
            raise HTTPException(409, f"set {sid} already exists")
        conn.execute(
            "INSERT INTO sets(id, tcg, code, name, aliases, release_date, date_confirmed, focus, auto_created, notes,"
            " created_at) VALUES(?,?,?,?,?,?,?,?,0,?,?)",
            (sid, fields["tcg"], fields.get("code"), fields["name"], db.jdump(fields.get("aliases") or []),
             fields.get("release_date"), int(fields.get("date_confirmed", True)), int(fields.get("focus", False)),
             fields.get("notes"), timeutil.iso()),
        )
    catalog.invalidate()
    _rematch_async()
    return _get(sid)


@router.patch("/{set_id}")
def patch_set(set_id: str, body: SetBody):
    fields = body.model_dump(exclude_unset=True)
    _check(fields)
    fields.pop("tcg", None)  # the TCG is part of the id
    if not fields:
        return _get(set_id)
    vals = []
    for k, v in fields.items():
        if k == "aliases":
            v = db.jdump(v or [])
        elif isinstance(v, bool):
            v = int(v)
        vals.append(v)
    with db.tx() as conn:
        if not conn.execute("SELECT 1 FROM sets WHERE id=?", (set_id,)).fetchone():
            raise not_found("set")
        conn.execute(f"UPDATE sets SET {', '.join(f'{k}=?' for k in fields)}, auto_created=0 WHERE id=?",
                     vals + [set_id])
        if "name" in fields or "code" in fields:
            # keep auto-generated product titles in sync with the set name
            _retitle_products(conn, set_id)
    if {"name", "code", "aliases"} & set(fields):
        catalog.invalidate()
        _rematch_async()
    return _get(set_id)


def _retitle_products(conn, set_id: str) -> None:
    from ..matching.classify import Classification
    from ..matching.matcher import product_title_for
    catalog.invalidate()
    for p in db.rows(conn.execute("SELECT * FROM products WHERE set_id=? AND manual=0", (set_id,))):
        c = Classification(kind="sealed", tcg=p["tcg"], ptype=p["type"], lang=p["lang"] or "en",
                           set_id=set_id, variant=p["variant"] or "")
        conn.execute("UPDATE products SET title=? WHERE id=?", (product_title_for(c), p["id"]))


@router.delete("/{set_id}")
def delete_set(set_id: str):
    with db.tx() as conn:
        conn.execute("UPDATE listings SET set_id=NULL, product_id=NULL WHERE set_id=? AND match_mode='auto'", (set_id,))
        conn.execute("UPDATE products SET set_id=NULL WHERE set_id=?", (set_id,))
        conn.execute("DELETE FROM sets WHERE id=?", (set_id,))
        cleanup_orphans(conn)
    catalog.invalidate()
    return {"ok": True}
