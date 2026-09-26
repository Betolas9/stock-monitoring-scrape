# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**restock-monitoring**: a personal, local-only tracker for sealed TCG products (Pokémon, One Piece, MTG, Lorcana…) across ~70 Portuguese web shops. One Python process runs a FastAPI server, a background scheduler that scrapes the stores, and a notification dispatcher (Telegram / Discord / Windows toast). The React UI (in `web/`) is built to static files and served by the same process. Storage is one SQLite file, `data/restock.db`.

There is no test suite and no lint config — don't invent `pytest`/`ruff` commands. Verify changes by running the app, or by running scrapers/classifier directly from a small script.

## Commands

```bash
# Backend
venv\Scripts\activate
pip install -r requirements.txt
python -m restock                 # http://127.0.0.1:8765  (--port, --host 0.0.0.0, --no-scheduler, --open)
start.bat                         # does setup + build + run

# Frontend (web/)
npm install
npm run build                     # → web/dist, served by the Python app
npm run dev                       # Vite on :5173, proxies /api to :8765
npx tsc -b                        # type-check
```

`RESTOCK_DATA_DIR=<dir>` points the app at another data directory: use a scratch dir to experiment without touching the real DB or firing real alerts. Windows toasts are **on** by default, so disable them via `restock.settings.update({'channels': {'windows': {'enabled': False}}})` in scratch runs.

## Architecture

**Flow:** `scheduler.Scheduler` picks due stores (per-store `next_check_at`, global concurrency, one check per domain at a time) → `scrapers.build_scraper()` → `fetch_products()` → `ingest.ingest()` classifies, filters and diffs against the store's `listings`, writes `listing_history` + `events`, links listings to canonical `products` → `alerts.evaluate()` decides which events notify → `notify.enqueue_events()` writes `notifications` rows → `notify.Dispatcher` thread delivers them with retries.

- **`scrapers/`** — one class per *platform*, registered in `SCRAPER_TYPES` (`shopify`, `woocommerce`, `woocommerce_html`, `prestashop`, `jumpseller`, `shopkit`, `html`, `wix`, plus store-specific `toysrus`, `continente`, `elcorteingles`, `conbini`). Store option `impersonate` switches HTTP to a curl_cffi Chrome-impersonating session (`http.ImpersonatingSession`); `require_tcg` (read in `ingest`) drops listings without a recognised game. Constructors take `(label, url, options)`. A store may have several `urls`, which are wrapped in `MultiUrlScraper`. Scrapers **must raise `ScrapeError`** on failure: returning a partial/empty dict would look like a mass sell-out. HTTP goes through `scrapers/http.make_session()` (retries connection resets and 429/5xx). `html_listing.py` is the selector-driven scraper for server-rendered listing pages; presets per platform, overridable per store via `options` (`tile`, `name`, `link`, `price`, `old_price`, `oos_selector`, `oos_class`, `id_attr`, `pagination` = `query`|`next`|`path`, `page_param`, `page_path`, `name_attr`, `id_class_prefix`, `meta_class_prefix`). Product dicts: `id, name, price, original_price, in_stock, url, image, meta` (`meta` = tags/categories, used only for classification).
- **`restock/matching/`** — `rules.py` (regex keyword tables: games, formats, languages, singles/services/merch/accessories), `classify.py` (name → kind/tcg/ptype/lang/set/variant/preorder), `catalog.py` (in-memory alias index over the `sets` table; call `catalog.invalidate()` after changing sets), `matcher.py` (product id = `{set_id}-{type}[-{variant}][-{lang}]`, fuzzy variant match for non-unique types, `refresh_products()` recomputes the denormalised price/stock stats on `products`). All regexes run on `text.norm()` output (lowercase, no accents, punctuation → spaces). When editing rules, write patch scripts with the Write tool or use Edit — shell heredocs have corrupted `\b` into backspace characters here before.
- **`restock/ingest.py`** — first check of a store (`baseline_done=0`) is silent. Guards: 0 results, or <30% of the previous count, raise `ScrapeError` instead of marking everything sold out. Listings missing from a scrape become `present=0, in_stock=0` (out_of_stock event). Listings still scraped but now filtered out are dropped silently.
- **`restock/alerts.py`** — reasons: `target` > `favorite` > `focus` (set marked focus in the calendar) > `general` (configured TCGs). Settings live in `settings.DEFAULTS` (one JSON doc in the `settings` table, deep-merged).
- **`restock/api/`** — REST endpoints for the UI (products, listings, stores, sets, favorites, events/notifications, settings/meta/summary). Sync `def` handlers; DB access through `db.tx()` (IMMEDIATE transaction) / `db.read()`.
- **`restock/bootstrap.py`** — creates the schema, merges `seed/stores.json` + `seed/sets.json` into the DB on every start: a 3-way merge per field using the row's `seed_json` (last applied seed entry), so seed updates reach existing installs but fields the user edited in the UI are never overwritten, and imports v1 `config.json` + `data/known_products.json` once (`meta.legacy_imported`).
- **`web/`** — React 19 + Vite + TypeScript, TanStack Query, react-router, Recharts. Pages in `web/src/pages/`, API types in `web/src/types.ts`. Filters live in URL search params.

## Gotchas

- The store **id** is the key for all its listings/history. Changing a store's `urls`/`platform`/`options` via the API resets `baseline_done`, so the next check is silent.
- Product ids depend on set ids (`catalog.set_id_for`): renaming a set's *code* changes future product ids. Prefer adding aliases.
- Some stores sit behind Cloudflare or render with JavaScript. `html_listing` detects challenge pages and raises. `BaseScraper._get_page_content()` (Playwright, needs `playwright install chromium`) is available for a future rendered scraper.
- Legacy v1 (`monitor.py`, `monitor_gui.py`, `notifier.py`, `state_manager.py`, `config.json`) is kept but superseded. Running both sends double alerts.
