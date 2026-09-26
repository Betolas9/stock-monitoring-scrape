"""Process-wide handles to the background workers (set up by server.py)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .notify import Dispatcher
    from .scheduler import Scheduler

scheduler: "Scheduler | None" = None
dispatcher: "Dispatcher | None" = None
