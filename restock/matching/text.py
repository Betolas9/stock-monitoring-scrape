from __future__ import annotations

import html
import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def fold(text: str) -> str:
    """Lowercase and strip accents, keeping punctuation ("Pokémon" → "pokemon").
    HTML entities some stores leave in names ("&#8211;") are decoded first."""
    text = unicodedata.normalize("NFKD", html.unescape(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def norm(text: str) -> str:
    """fold() + every run of non-alphanumerics becomes one space.

    "Pokémon TCG: SV08.5 Prismatic Evolutions — ETB (Pré-venda)"
      → "pokemon tcg sv08 5 prismatic evolutions etb pre venda"
    """
    text = fold(text).replace("&", " and ")
    return _NON_ALNUM.sub(" ", text).strip()


def slug(text: str) -> str:
    return norm(text).replace(" ", "-")


def has_phrase(normed: str, phrase: str) -> bool:
    """Whole-word phrase containment on norm()-ed text."""
    return f" {phrase} " in f" {normed} "


def remove_phrase(normed: str, phrase: str) -> str:
    return f" {normed} ".replace(f" {phrase} ", " ").strip()
