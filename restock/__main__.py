"""python -m restock  — start restock-monitoring (API + scheduler + web UI).

Options:
  --host 127.0.0.1   interface to bind (use 0.0.0.0 to open it from your phone on the LAN)
  --port 8765
  --no-scheduler     serve the UI/API only, don't check stores
  --open             open the browser on start
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler

import uvicorn

from . import APP_NAME
from .paths import DATA_DIR, LOG_PATH


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler = RotatingFileHandler(LOG_PATH, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [file_handler, console]
    # urllib3 retry chatter is noise at INFO
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m restock", description=APP_NAME)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-scheduler", action="store_true")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    setup_logging()
    from .server import create_app

    app = create_app(run_scheduler=not args.no_scheduler)
    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    logging.getLogger(APP_NAME).info(f"Open {url}")
    if args.open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", log_config=None)


if __name__ == "__main__":
    main()
