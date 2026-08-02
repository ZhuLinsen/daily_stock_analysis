"""Shared HTTP utilities for free A-share data sources.

This module ports the operational rules from the a-stock-data skill into the
project codebase: zero-key sources first, explicit source metadata, bounded
timeouts, retries for transient failures, and conservative Eastmoney throttling.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Mapping, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class FreeSourceError(RuntimeError):
    """Raised when a free A-share source cannot return usable data."""


@dataclass(frozen=True)
class FreeSourceRequestPolicy:
    timeout: float = float(os.getenv("FREE_SOURCE_TIMEOUT", "15") or 15)
    eastmoney_min_interval: float = float(os.getenv("EASTMONEY_MIN_INTERVAL", "1.2") or 1.2)
    eastmoney_jitter: float = float(os.getenv("EASTMONEY_JITTER", "0.5") or 0.5)
    max_retries: int = int(os.getenv("EASTMONEY_MAX_RETRIES", "3") or 3)


class FreeSourceHttpClient:
    """Small wrapper around requests.Session with source-aware throttling."""

    def __init__(self, policy: Optional[FreeSourceRequestPolicy] = None):
        self.policy = policy or FreeSourceRequestPolicy()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        self._eastmoney_lock = threading.Lock()
        self._eastmoney_last_call = 0.0

        retry = Retry(
            total=self.policy.max_retries,
            connect=self.policy.max_retries,
            read=self.policy.max_retries,
            backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> requests.Response:
        if "eastmoney.com" in url:
            self._throttle_eastmoney()
        merged_headers = {"User-Agent": DEFAULT_USER_AGENT}
        if headers:
            merged_headers.update(dict(headers))
        try:
            response = self.session.request(
                method,
                url,
                headers=merged_headers,
                timeout=timeout or self.policy.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            raise FreeSourceError(f"free source request failed: {url}: {exc}") from exc

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def _throttle_eastmoney(self) -> None:
        with self._eastmoney_lock:
            elapsed = time.time() - self._eastmoney_last_call
            wait = self.policy.eastmoney_min_interval - elapsed
            if wait > 0:
                time.sleep(wait + random.uniform(0.1, max(0.1, self.policy.eastmoney_jitter)))
            self._eastmoney_last_call = time.time()


default_free_source_client = FreeSourceHttpClient()
