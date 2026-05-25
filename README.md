# Restock Monitor

Monitors e-commerce websites every 2 minutes for new products, restocked items, and out-of-stock events. Sends native Windows desktop notifications for all changes.

## Sites monitored

| Site | Search |
|------|--------|
| Continente | Pokémon TCG |
| ToysRus Portugal | Pokémon TCG |

---

## Setup

### 1. Create a virtual environment (recommended)

```bash
python -m venv venv
venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Run

```bash
cd restock-monitor
python monitor.py
```

Press **Ctrl+C** to stop.

---

## Events tracked

| Icon | Event | When |
|------|-------|------|
| 🆕 | New product | Product appears for the first time |
| ✅ | Back in stock | Previously OOS product is now available |
| ❌ | Out of stock | Product disappears or is marked unavailable |
| 💰 | Price change | Price changed between checks |

---

## First run behaviour

On the **first run**, all current products are saved silently as the baseline — no notifications are sent. From the **second check** onwards, every change triggers a notification.

To reset the baseline: delete `known_products.json`.  
To reset one site only: remove its key from the JSON file.

---

## Configuration (`config.json`)

```json
{
  "check_interval_seconds": 120,
  "sites": {
    "continente": {
      "enabled": true,
      "url": "https://..."
    },
    "toysrus": {
      "enabled": false
    }
  }
}
```

Set `"enabled": false` to pause a site without removing it.

---

## File overview

```
restock-monitor/
├── monitor.py            # Entry point — run this
├── config.json           # Site URLs and check interval
├── known_products.json   # Persisted product state (auto-created)
├── monitor.log           # Full timestamped event log (auto-created)
├── notifier.py           # Desktop notifications + log output
├── state_manager.py      # State persistence and change detection
├── requirements.txt
└── scrapers/
    ├── base.py           # Playwright + BeautifulSoup base class
    ├── continente.py     # Continente-specific HTML parser
    └── toysrus.py        # ToysRus-specific HTML parser
```

---

## Adding a new site

1. Copy `scrapers/continente.py` → `scrapers/mysite.py`
2. Implement `fetch_products()` returning `{product_id: product_dict}`
3. Register it in `monitor.py`:
   ```python
   _SCRAPER_MAP = {
       "continente": ContinenteScraper,
       "toysrus": ToysRusScraper,
       "mysite": MySiteScraper,   # add here
   }
   ```
4. Add the site entry to `config.json`

---

## Troubleshooting

**No products found on a site**

The site HTML structure may not match the expected selectors. Enable DEBUG logging to see what the page looks like:

```python
# In monitor.py, change:
logging.basicConfig(level=logging.DEBUG, ...)
```

Re-run and look for `Page snippet:` lines in the log. Inspect the site in DevTools, find the correct CSS selector for product tiles, and update `_TILE_SELECTORS` in the relevant scraper.

**`playwright install chromium` fails**

Make sure `playwright` is installed first (`pip install playwright`), then run `playwright install chromium`.

**Notifications not appearing**

Verify plyer works:
```python
from plyer import notification
notification.notify(title="Test", message="Stock Monitor works!", timeout=5)
```

Check Windows Settings → Notifications — ensure Python/notifications are not blocked. Also confirm Focus Assist is off.

**Site blocks the scraper**

Increase `extra_wait_ms` in `BaseScraper._get_page_content()` (default: 2500 ms) to give the page more render time, or raise `check_interval_seconds` to reduce request frequency.
# stock-monitoring-scrape
