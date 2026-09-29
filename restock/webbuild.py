"""Is the built web UI (web/dist) older than its source?

`python -m restock.webbuild` exits with 1 when web/dist must be rebuilt
(missing, or any source file newer than it) and 2 when `npm install` is
needed first — start.bat uses it so a `git pull` always gets a fresh UI.
"""
from __future__ import annotations

import hashlib
import sys

from .paths import ROOT

WEB = ROOT / "web"
SOURCES = ["src", "index.html", "package.json", "package-lock.json", "vite.config.ts", "public",
           "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json"]


def _newest(paths) -> float:
    newest = 0.0
    for p in paths:
        p = WEB / p
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    newest = max(newest, f.stat().st_mtime)
        elif p.exists():
            newest = max(newest, p.stat().st_mtime)
    return newest


_INSTALL_MARKER = WEB / "node_modules" / ".restock-installed"


def _lock_hash() -> str:
    lock = WEB / "package-lock.json"
    return hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else ""


def needs_install() -> bool:
    """npm packages missing, or package-lock.json content changed since the
    last install (content, not mtime: git touches files it rewrites)."""
    if not (WEB / "node_modules").is_dir():
        return True
    if not _INSTALL_MARKER.exists():
        # installed before this check existed: trust it and start tracking
        mark_installed()
        return False
    return _INSTALL_MARKER.read_text().strip() != _lock_hash()


def mark_installed() -> None:
    _INSTALL_MARKER.write_text(_lock_hash())


def needs_build() -> bool:
    index = WEB / "dist" / "index.html"
    return not index.exists() or _newest(SOURCES) > index.stat().st_mtime


def is_stale() -> bool:
    """Used by the server to warn when it is about to serve an outdated UI."""
    return needs_build()


if __name__ == "__main__":
    if "--mark-installed" in sys.argv:
        mark_installed()
        sys.exit(0)
    if needs_install():
        sys.exit(2)
    sys.exit(1 if needs_build() else 0)
