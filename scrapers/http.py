"""Shared HTTP session for the requests-based scrapers.

Connection resets and TLS hiccups are common enough (flaky Wi-Fi, antivirus
HTTPS inspection, Shopify rate limits) that a single failed request must not
fail a whole store check — every scraper gets a session that retries
connection errors and 429/5xx responses with backoff, honouring Retry-After.
"""
from __future__ import annotations

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

HTML_HEADERS = {
    "User-Agent":      USER_AGENT,
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}

JSON_HEADERS = {
    "User-Agent":      USER_AGENT,
    "Accept":          "application/json",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}

DEFAULT_TIMEOUT = 25


class ImpersonatingSession:
    """Browser-impersonating session (curl_cffi: real Chrome TLS/HTTP2
    fingerprint). Gets past bot filters that reject python-requests, e.g.
    Cloudflare's passive checks or Akamai. Same retry policy as make_session.
    """

    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, headers: dict | None = None) -> None:
        from curl_cffi import requests as curl_requests  # optional dependency

        self._session = curl_requests.Session(impersonate="chrome")
        # keep the impersonated browser's own User-Agent / Accept headers
        self.headers = {k: v for k, v in (headers or {}).items() if k.lower() in ("accept-language", "referer")}

    def get(self, url: str, params: dict | None = None, timeout: float = DEFAULT_TIMEOUT, **kwargs):
        last_exc: Exception | None = None
        for attempt in range(5):
            if attempt:
                time.sleep(1.5 * 2 ** (attempt - 1))
            try:
                resp = self._session.get(url, params=params, timeout=timeout, headers=self.headers, **kwargs)
            except Exception as e:  # noqa: BLE001 — connection resets, TLS errors, timeouts
                last_exc = e
                continue
            if resp.status_code in self.RETRY_STATUS and attempt < 4:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(min(int(retry_after), 60))
                continue
            return resp
        raise last_exc or RuntimeError(f"giving up on {url}")


def make_session(headers: dict | None = None, impersonate: bool = False):
    if impersonate:
        return ImpersonatingSession(headers)
    return _requests_session(headers)


def _requests_session(headers: dict | None = None) -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=3,
        status=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(headers or HTML_HEADERS)
    return session
