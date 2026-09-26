"""HTTP POST with quick retries on connection errors.

Some networks (antivirus HTTPS inspection, corporate firewalls, flaky Wi-Fi)
randomly reset connections. A reset almost always happens before the request
reaches the server, so retrying right away is safe and turns most "network
error" failures into a short delay.
"""
from __future__ import annotations

import time

import requests

from .errors import NotifyError

ATTEMPTS = 5


def post(url: str, timeout: float = 20, **kwargs) -> requests.Response:
    last: Exception | None = None
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(0.5 * 2 ** (attempt - 1))  # 0.5, 1, 2, 4 s
        try:
            return requests.post(url, timeout=timeout, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
    raise NotifyError(f"network error after {ATTEMPTS} attempts: {last}")
