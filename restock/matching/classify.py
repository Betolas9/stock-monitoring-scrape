"""Turn a raw store listing name into structured facts:
kind (sealed / accessory / single / other), TCG, product type, language,
set and pre-order flag."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import catalog, rules
from .text import fold, has_phrase, norm, remove_phrase

_QTY = re.compile(
    r"\b(\d{1,2}) ?x\b|\bx ?(\d{1,2})\b(?! (?:cards?|cartas?))"
    r"|\b(?:pack|lote|conjunto) (?:of|de) (\d{1,2})\b(?! (?:cards?|cartas?))"
)

# Set codes printed on the box. An unknown code creates a placeholder set
# (named after the code — rename it in the calendar). (tcg, pattern, implies_tcg)
_SET_CODES: list[tuple[str, re.Pattern, bool]] = [
    ("onepiece", re.compile(r"\b(op|eb|prb) ?(\d{2})\b"), True),
    ("onepiece", re.compile(r"\b(st) ?(\d{2})\b"), False),
    ("dbs",      re.compile(r"\b(fb) ?(\d{2})\b"), True),
    ("dbs",      re.compile(r"\b(sb) ?(\d{2})\b"), False),
    ("digimon",  re.compile(r"\b(bt|ex|eb) ?(\d{1,2})\b"), False),
    ("gundam",   re.compile(r"\b(gd|st) ?(\d{2})\b"), False),
]


@dataclass
class Classification:
    kind: str                       # sealed|accessory|single|other
    tcg: str | None = None
    ptype: str | None = None
    lang: str = "en"
    set_id: str | None = None
    preorder: bool = False
    variant: str = ""               # distinguishing words for non-unique types
    new_set: dict | None = None     # set to auto-create (unknown One Piece code)
    matched_phrases: list[str] = field(default_factory=list)


def _first(patterns, text: str) -> tuple[str | None, int]:
    """Pattern key whose earliest match comes first in the text."""
    best, pos = None, 10**9
    for key, pat in patterns:
        m = pat.search(text)
        if m and m.start() < pos:
            best, pos = key, m.start()
    return best, pos


def detect_tcg(n: str, meta_n: str) -> str | None:
    tcg, _ = _first(rules.TCG_PATTERNS, n)
    if tcg:
        return tcg
    for key, pat in rules.TCG_IMPLIED_BY_TYPE:
        if pat.search(n):
            return key
    if meta_n:
        tcg, _ = _first(rules.TCG_PATTERNS, meta_n)
    return tcg


def detect_lang(n: str, meta_n: str) -> str:
    found = [k for k, pat in rules.LANG_PATTERNS if pat.search(n)]
    non_en = [k for k in found if k != "en"]
    if non_en:
        return non_en[0]
    if found:
        return "en"
    if meta_n:
        meta_found = {k for k, pat in rules.LANG_PATTERNS if pat.search(meta_n)}
        # Only trust tags when they name exactly one language
        if len(meta_found) == 1:
            return meta_found.pop()
    return "en"


def detect_type(n: str) -> tuple[str | None, str | None]:
    for key, pat in rules.TYPE_PATTERNS:
        m = pat.search(n)
        if m:
            return key, m.group(0)
    return None, None


def detect_set(n: str, tcg: str | None) -> tuple[catalog.SetInfo | None, str | None]:
    def scan(text: str):
        for alias in catalog.aliases():
            if tcg and alias.set.tcg != tcg:
                continue
            if not tcg and not alias.strong:
                continue
            if has_phrase(text, alias.phrase):
                return alias.set, alias.phrase
        return None, None

    stripped = n
    for series in rules.SERIES_PHRASES:
        stripped = remove_phrase(stripped, series)
    found = scan(stripped)
    if found[0] is None and stripped != n:
        found = scan(n)
    return found


def classify(name: str, meta: str = "") -> Classification:
    raw = fold(name)
    n = norm(name)
    meta_n = norm(meta or "")

    if rules.SINGLE_RAW.search(raw) or rules.SINGLE_NORM.search(n) or rules.SINGLE_META.search(meta_n):
        return Classification(kind="single")
    if rules.SERVICE.search(n):
        return Classification(kind="service")
    if rules.MERCH.search(n) and not rules.MERCH_UNLESS.search(n):
        return Classification(kind="merch")

    tcg = detect_tcg(n, meta_n)
    lang = detect_lang(n, meta_n)
    preorder = bool(rules.PREORDER.search(n))

    if rules.ACCESSORY.search(n) and not rules.ACCESSORY_UNLESS.search(n):
        return Classification(kind="accessory", tcg=tcg, lang=lang, preorder=preorder)

    ptype, type_phrase = detect_type(n)
    set_info, set_phrase = detect_set(n, tcg)
    if set_info and not tcg:
        tcg = set_info.tcg

    new_set = None
    if set_info is None:
        for code_tcg, pat, implies in _SET_CODES:
            if tcg != code_tcg and not (implies and tcg is None):
                continue
            m = pat.search(n)
            if not m:
                continue
            tcg = code_tcg
            prefix, num = m.group(1), m.group(2).zfill(2)
            code = f"{prefix.upper()}-{num}"
            existing = catalog.get_set(f"{tcg}-{prefix}{num}")
            if existing:
                set_info = existing
            else:
                new_set = {"id": f"{tcg}-{prefix}{num}", "tcg": tcg, "code": code, "name": code}
            set_phrase = m.group(0)
            if prefix == "st":
                ptype = ptype or "deck"
            break

    c = Classification(
        kind="sealed" if ptype else "other",
        tcg=tcg,
        ptype=ptype,
        lang=lang,
        set_id=set_info.id if set_info else (new_set["id"] if new_set else None),
        preorder=preorder,
        new_set=new_set,
        matched_phrases=[p for p in (set_phrase, type_phrase) if p],
    )
    if ptype:
        c.variant = _variant(n, c)
    return c


def _variant(n: str, c: Classification) -> str:
    """Words that tell apart products sharing set + type + language."""
    if c.ptype in rules.UNIQUE_TYPES:
        flags = [key for key, _label, pat in rules.UNIQUE_VARIANTS if pat.search(n)]
        # "10x Booster Packs", "Pack of 3 ETBs" are bundles, not the single item
        m = _QTY.search(n)
        qty = next((int(g) for g in (m.groups() if m else ()) if g), 1)
        if 1 < qty <= 50 and not (c.ptype == "booster-box" and qty in (18, 24, 30, 36)):
            flags.append(f"{qty}x")
        # "mini" only matters for booster boxes (mini tins are their own type)
        return "-".join(f for f in flags if not (f == "mini" and c.ptype != "booster-box"))

    text = n
    for phrase in c.matched_phrases + rules.SERIES_PHRASES:
        text = remove_phrase(text, phrase)
    # Words of the set's own name/code ("… | 30th" suffixes, "Perfect Order")
    set_info = catalog.get_set(c.set_id)
    set_words: set[str] = set()
    if set_info:
        set_words.update(norm(set_info.name).split())
        if set_info.code:
            for v in catalog.code_variants(set_info.code):
                set_words.update(v.split())
    for _key, pat in rules.TYPE_PATTERNS:
        text = pat.sub(" ", text)
    for _key, pat in rules.LANG_PATTERNS:
        text = pat.sub(" ", text)
    text = rules.PREORDER.sub(" ", text)
    for _key, pat in rules.TCG_PATTERNS:
        text = pat.sub(" ", text)
    words = [
        w for w in text.split()
        if w not in rules.STOPWORDS and w not in set_words and not (w.isdigit() and len(w) > 3)
    ]
    # keep order but drop duplicates
    seen: list[str] = []
    for w in words:
        if w not in seen:
            seen.append(w)
    return "-".join(seen[:5])
