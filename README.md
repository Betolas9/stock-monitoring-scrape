# restock-monitoring

A local web app that watches ~70 Portuguese TCG stores (Pokémon, One Piece, Magic, Lorcana, …),
groups the same product across stores, keeps price and stock history, and alerts you on your
phone (Telegram / Discord) or PC (Windows toast) when something you care about restocks, drops
in price, or gets listed.

It runs entirely on your machine: a Python process (FastAPI + a background scheduler) with a
SQLite database, serving a React UI at <http://127.0.0.1:8765>.

## Quick start

```bat
start.bat
```

That creates the virtualenv if needed, installs dependencies, builds the web UI if it isn't built
yet, starts the app and opens your browser. Stop it with **Ctrl+C**.

Manual equivalent:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cd web && npm install && npm run build && cd ..
python -m restock --open          # --port 8765, --host 0.0.0.0 to open it from your phone on Wi-Fi
```

On first start the app seeds the store list and the set catalogue into `data/restock.db` and
imports your v1 data (`config.json` + `data/known_products.json`) once: ignore keywords, stores
and price/stock history carry over.

### Set up phone alerts (2 minutes)

**Settings → Telegram**: create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`), paste
the token, send your bot any message, press **Detect my chat**, **Save**, **Send test**.
Discord (webhook URL) and Windows toasts are also available. Every alert is queued in the
database and retried with backoff if a channel is down. The **Activity → Alerts sent** page shows
each delivery and lets you retry failures.

## What it does

| Page | |
|------|--|
| **Products** | One card per product across all stores: cheapest in-stock price, `in stock / stores`, 30-day price change, pre-order and focus flags. Filters for game, format, language, stock, focus releases and pre-orders. |
| **Product** | Price-history chart (cheapest in stock vs cheapest listed), "usual price / lowest was …" summary, table of every store with price/stock/link, watch settings with **target price**, edit/merge tools. |
| **Favourites** | Your watchlist with how close each product is to its target price. |
| **Releases** | Calendar of sets. Mark a release as **🔥 focus** to be alerted on *every* new listing, pre-order and restock of its products. Unknown set codes seen in stores (e.g. `OP-15`) appear here automatically, so you can name them. |
| **Stores** | Live status of every store (checking / OK / failing, with the error), enable/disable, check now, add/edit with a **Test scrape** dry run. |
| **Activity** | Every stock/price change detected, and every alert sent. |
| **Matching** | Store listings that couldn't be matched to a product, with link/create tools. |
| **Settings** | Alert channels, alert rules, check interval / parallelism, ignored keywords. |

### Alert rules (Settings → What alerts you)

- **Target price**: a favourite at or below your target at any store. Always alerts.
- **Favourites**: restock, price drop, listed by a new store (optionally: sold out).
- **Focus releases**: new listings and pre-orders, and restocks.
- **Everything else**: new products for the games you pick (default Pokémon + One Piece,
  sealed only). Restocks and drops of everything are off by default because with 70+ stores
  that gets noisy.

A store's first check is a **silent baseline**. So is its first check after you change what it
scrapes (URL, platform, options).

## How matching works

Every store listing is classified from its name (plus the store's tags/categories):
*kind* (sealed / accessory; singles, breaks and merch are dropped), *game*, *format* (booster
box, ETB, booster bundle, tin, blister, collection, …), *language* and *set* (from
`restock/seed/sets.json` + the sets you add in the calendar). Listings with the same
set + format (+ variant, e.g. Pokémon Center ETB, `10x`) + language become one product, e.g.
`pokemon-me03-etb`. Tins, collections and blisters also use their distinguishing words
(e.g. "greninja"). Fix mistakes in the UI: unlink a listing on the product page, link or create
from **Matching**, or merge duplicates via **Edit / merge**. Manual choices are never overwritten.

## Stores

`restock/seed/stores.json` holds all 75 stores (the 72 from SealedWatch's list plus Continente, Miguel TCG Breaks and Panda Collecting from v1); 72 are enabled. It is merged into the DB on every start (new stores added, updated
configs applied) — except fields you changed in the **Stores** page, which always win. Platforms (`scrapers/`):

| Platform | How | Stores |
|---|---|---|
| `shopify` | public `/products.json` API | 36 |
| `woocommerce` | public Store API (`?category=`, `category_operator=not_in` to narrow) | 8 |
| `woocommerce_html` | shop pages, for WooCommerce shops with the API disabled | 1 |
| `prestashop` | category/search pages (HTML) | 4 |
| `jumpseller`, `shopkit`, `html` | server-rendered listing pages; selectors configurable per store (`options`) | 18 |
| `wix` | Wix Stores catalogue API | 2 |
| `toysrus`, `continente`, `elcorteingles`, `conbini` | store-specific | 4 |

Store `options` that work on any platform: `"impersonate": true` sends browser-like requests
(TLS fingerprint of Chrome, via `curl_cffi`) for sites that reject plain scripts (GG Lounge, El
Corte Inglés); `"require_tcg": true` keeps only products with a recognised game, for generalist
shops where "booster" can be a face serum.

Not enabled: **Colecionar** (interactive Cloudflare challenge — not supported), **Centroxogo**
(unreachable from the network this was built on; Magento selectors are pre-filled, enable it to
try) and **Panda Collecting** (disabled in v1).

**Adding a store:** Stores → **+ Add store** → pick the platform → **Test scrape** → Save.
To find the platform: `https://store/products.json` returns JSON → Shopify;
`https://store/wp-json/wc/store/v1/products` returns JSON → WooCommerce; the page source mentions
`jumpseller`, `shopkit` or `prestashop` → that platform. For a big generalist shop, list only its
TCG category/collection pages under *Pages to scrape*.

## Project layout

```
restock/                 Python app (python -m restock)
  server.py              FastAPI app + static UI
  scheduler.py           per-store scheduling, jitter, backoff, status
  ingest.py              scrape → diff → history → events
  alerts.py              which events notify
  notify/                Telegram, Discord, Windows + retrying delivery queue
  matching/              classification rules, set catalogue, product matcher
  api/                   REST endpoints used by the UI
  seed/                  stores.json, sets.json
scrapers/                one scraper per platform
web/                     React + Vite + TypeScript UI (npm run dev / npm run build)
data/                    restock.db, restock.log (local, not in git)
```

UI development: run `python -m restock` and `npm run dev` in `web/` (Vite on :5173 proxies `/api`).

### Legacy v1

`monitor.py`, `monitor_gui.py`, `notifier.py`, `state_manager.py` and `config.json` are the
previous version. They still work but aren't needed any more. **Don't run v1 and v2 at the same
time**, or you'll get double alerts.

## Troubleshooting

- **A store shows "0 products read" or keeps failing**: open it in Stores → ✎ → **Test scrape**.
  Usually the category URL moved or the theme changed; adjust *Pages to scrape* or the selector
  options.
- **Network errors on some stores**: the scrapers retry connection resets and 429/5xx with
  backoff, and a failing store is retried later with growing delays. You're alerted if a store
  fails 5 checks in a row (configurable).
- **Wrong product grouping**: see *How matching works*. Adding the set (with its other names) in
  the calendar re-matches unmatched listings automatically.
- **Logs**: `data/restock.log`.
