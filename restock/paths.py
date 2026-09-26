from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RESTOCK_DATA_DIR", ROOT / "data"))
DB_PATH = DATA_DIR / "restock.db"
LOG_PATH = DATA_DIR / "restock.log"
SEED_DIR = Path(__file__).resolve().parent / "seed"
WEB_DIST = ROOT / "web" / "dist"

# Legacy (v1) files, imported once on first start
LEGACY_CONFIG = ROOT / "config.json"
LEGACY_STATE = DATA_DIR / "known_products.json"
