"""In-memory index of known sets (from the `sets` table) for name matching.

Rebuilt lazily whenever sets change (invalidate()), so a release added in
the calendar is picked up by the next store check.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from .. import db
from .text import norm


@dataclass(frozen=True)
class SetInfo:
    id: str
    tcg: str
    code: str | None
    name: str


@dataclass(frozen=True)
class Alias:
    phrase: str      # norm()-ed
    set: SetInfo
    strong: bool     # distinctive enough to imply the TCG on its own


_lock = threading.Lock()
_aliases: list[Alias] | None = None
_sets: dict[str, SetInfo] = {}


def invalidate() -> None:
    global _aliases
    with _lock:
        _aliases = None


def set_id_for(tcg: str, code: str | None, name: str) -> str:
    """ ("onepiece", "OP-13") → "onepiece-op13"; ("pokemon", "ME02.5") → "pokemon-me02-5" """
    if code:
        c = re.sub(r"([a-z]) (\d)", r"\1\2", norm(code))
        return f"{tcg}-{c.replace(' ', '-')}"
    return f"{tcg}-{norm(name).replace(' ', '-')}"


def code_variants(code: str) -> set[str]:
    """ "SV08.5" → {"sv08 5", "sv8 5", "sv8pt5", "sv085"}; "OP-13" → {"op 13", "op13"} """
    out: set[str] = set()
    c = norm(code)
    if not c:
        return out
    out.add(c)
    out.add(c.replace(" ", ""))
    m = re.fullmatch(r"([a-z]+) ?0*(\d+)(?: (\d+))?([a-z])?", c)
    if m:
        prefix, num, half, suffix = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        for n in {num, num.zfill(2)}:
            if half:
                out.update({f"{prefix}{n} {half}{suffix}", f"{prefix} {n} {half}{suffix}", f"{prefix}{n}pt{half}{suffix}"})
            else:
                out.update({f"{prefix}{n}{suffix}", f"{prefix} {n}{suffix}"})
    return {v.strip() for v in out if v.strip()}


def _build() -> list[Alias]:
    global _sets
    with db.read() as conn:
        sets = db.rows(conn.execute("SELECT id, tcg, code, name, aliases FROM sets"))
    aliases: list[Alias] = []
    _sets = {}
    for s in sets:
        info = SetInfo(s["id"], s["tcg"], s["code"], s["name"])
        _sets[info.id] = info
        phrases: set[str] = {norm(s["name"])}
        phrases.update(norm(a) for a in db.jload(s["aliases"], []) or [])
        if s["code"]:
            phrases.update(code_variants(s["code"]))
        for p in phrases:
            if not p:
                continue
            # "151" or "Fusion" alone must not pull random products into a set
            strong = len(p) >= 8 and " " in p and not p.replace(" ", "").isdigit()
            aliases.append(Alias(p, info, strong))
    # Longest first, so "black bolt" beats "black" and "ascended heroes" beats "heroes"
    aliases.sort(key=lambda a: len(a.phrase), reverse=True)
    return aliases


def aliases() -> list[Alias]:
    global _aliases
    with _lock:
        if _aliases is None:
            _aliases = _build()
        return _aliases


def get_set(set_id: str | None) -> SetInfo | None:
    aliases()  # make sure the index is loaded
    return _sets.get(set_id) if set_id else None
