from __future__ import annotations

import abc
import hashlib
import logging

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class BaseScraper(abc.ABC):
    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url

    def _get_page_content(
        self,
        url: str,
        wait_selectors: list[str] | None = None,
        extra_wait_ms: int = 2500,
    ) -> str:
        html = ""
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            ctx = browser.new_context(
                locale="pt-PT",
                timezone_id="Europe/Lisbon",
                user_agent=_USER_AGENT,
                extra_http_headers={
                    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;"
                        "q=0.9,image/avif,image/webp,*/*;q=0.8"
                    ),
                    "DNT": "1",
                },
            )
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass  # networkidle timeout is acceptable — page may still be usable

                self._try_dismiss_cookies(page)

                if wait_selectors:
                    for sel in wait_selectors:
                        try:
                            page.wait_for_selector(sel, timeout=8_000)
                            logger.debug(f"[{self.name}] Wait selector matched: {sel}")
                            break
                        except Exception:
                            pass

                # Scroll to trigger lazy-loaded product tiles
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
                page.wait_for_timeout(extra_wait_ms // 2)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(extra_wait_ms // 2)

                html = page.content()
                logger.debug(f"[{self.name}] Fetched {len(html):,} chars from {url}")
            except Exception as e:
                logger.error(f"[{self.name}] Playwright error: {e}")
            finally:
                browser.close()
        return html

    def _try_dismiss_cookies(self, page) -> None:
        candidates = [
            "button:has-text('Aceitar todos')",
            "button:has-text('Aceitar')",
            "button:has-text('Accept All')",
            "button:has-text('Accept')",
            "#onetrust-accept-btn-handler",
            "[id*='accept'][class*='cookie']",
            "[class*='cookie'][class*='accept']",
            "[class*='cookie-accept']",
        ]
        for sel in candidates:
            try:
                page.click(sel, timeout=2_000)
                page.wait_for_timeout(800)
                logger.debug(f"[{self.name}] Cookie banner dismissed ({sel})")
                return
            except Exception:
                pass

    def _generate_id(self, text: str) -> str:
        return hashlib.md5(text.lower().strip().encode()).hexdigest()[:12]

    @abc.abstractmethod
    def fetch_products(self) -> dict:
        """Return {product_id: product_dict} for all products found on the page."""
