# -*- coding: utf-8 -*-
"""
===================================
Social Sentiment Intelligence Service
===================================

Fetches Reddit / X (Twitter) / Polymarket social sentiment data
from api.adanos.org for US stock tickers.

Optional — requires SOCIAL_SENTIMENT_API_KEY.
Only activates for US stock codes (AAPL, TSLA, etc.).
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

_TRANSIENT_EXCEPTIONS = (
    requests.exceptions.SSLError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

_REQUEST_TIMEOUT = 8  # seconds
_REQUEST_RETRY_ATTEMPTS = 2
_REQUEST_RETRY_WAIT_CAP = 5  # wait_exponential(..., max=5)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type(_TRANSIENT_EXCEPTIONS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _get_with_retry(url: str, *, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None,
                    timeout: int = _REQUEST_TIMEOUT) -> requests.Response:
    """GET with retry on transient network errors."""
    return requests.get(url, headers=headers, params=params or {}, timeout=timeout)


class SocialSentimentService:
    """
    Social Sentiment Intelligence — Reddit / X / Polymarket.

    Fetches social-media sentiment data from api.adanos.org and formats
    it as a text block suitable for injection into the LLM analysis prompt.

    Usage::

        svc = SocialSentimentService(api_key="sk_live_...", api_url="https://api.adanos.org")
        if svc.is_available:
            context = svc.get_social_context("TSLA")
    """

    # Cache TTL for trending endpoints (seconds)
    _TRENDING_CACHE_TTL = 600  # 10 minutes

    def __init__(self, api_key: Optional[str] = None, api_url: str = "https://api.adanos.org"):
        self._api_key = (api_key or "").strip() or None
        self._api_url = (api_url or "https://api.adanos.org").rstrip("/")
        # Simple in-memory cache: {"key": (timestamp, data)}
        self._cache: Dict[str, tuple] = {}
        self._cache_lock = threading.RLock()
        self._cache_inflight: Dict[str, threading.Event] = {}

    @property
    def is_available(self) -> bool:
        return self._api_key is not None

    @property
    def _headers(self) -> Dict[str, str]:
        return {"X-API-Key": self._api_key or "", "Accept": "application/json"}

    # ------------------------------------------------------------------
    # API calls
    # ------------------------------------------------------------------

    def _fetch_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
        """Fetch JSON from API, return None on any error."""
        try:
            resp = _get_with_retry(url, headers=self._headers, params=params)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("Social sentiment API %s returned %s", url, resp.status_code)
        except _TRANSIENT_EXCEPTIONS as e:
            logger.warning("Social sentiment API %s network error: %s", url, e)
        except Exception as e:
            logger.warning("Social sentiment API %s unexpected error: %s", url, e)
        return None

    @classmethod
    def _cache_wait_timeout_seconds(cls) -> float:
        request_budget = (_REQUEST_TIMEOUT * _REQUEST_RETRY_ATTEMPTS) + _REQUEST_RETRY_WAIT_CAP
        return max(1.0, min(float(cls._TRENDING_CACHE_TTL), float(request_budget), 30.0))

    def _fetch_cached(self, cache_key: str, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """Fetch with simple TTL cache (for trending endpoints)."""
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and (now - cached[0]) < self._TRENDING_CACHE_TTL:
                return cached[1]
            inflight = self._cache_inflight.get(cache_key)
            if inflight is None:
                inflight = threading.Event()
                self._cache_inflight[cache_key] = inflight
                owner = True
            else:
                owner = False

        if not owner:
            inflight.wait(timeout=self._cache_wait_timeout_seconds())
            now = time.monotonic()
            with self._cache_lock:
                cached = self._cache.get(cache_key)
                if cached and (now - cached[0]) < self._TRENDING_CACHE_TTL:
                    return cached[1]

            data = self._fetch_json(url, params)
            if data is not None:
                with self._cache_lock:
                    self._cache[cache_key] = (time.monotonic(), data)
            return data

        try:
            data = self._fetch_json(url, params)
            if data is not None:
                with self._cache_lock:
                    self._cache[cache_key] = (time.monotonic(), data)
            return data
        finally:
            with self._cache_lock:
                current = self._cache_inflight.get(cache_key)
                if current is inflight:
                    self._cache_inflight.pop(cache_key, None)
                    inflight.set()

    def fetch_reddit_report(self, ticker: str) -> Optional[Dict]:
        """Fetch detailed Reddit report for a single ticker."""
        url = f"{self._api_url}/reddit/stocks/v1/report/{ticker.upper()}"
        return self._fetch_json(url)

    def fetch_reddit_trending(self) -> Optional[List[Dict]]:
        """Fetch Reddit trending stocks (cached)."""
        url = f"{self._api_url}/reddit/stocks/v1/trending"
        data = self._fetch_cached("reddit_trending", url)
        if isinstance(data, dict):
            return data.get("trending", data.get("data", []))
        if isinstance(data, list):
            return data
        return None

    def fetch_x_trending(self) -> Optional[List[Dict]]:
        """Fetch X/Twitter trending stocks (cached)."""
        url = f"{self._api_url}/x/stocks/v1/trending"
        data = self._fetch_cached("x_trending", url)
        if isinstance(data, dict):
            return data.get("trending", data.get("data", []))
        if isinstance(data, list):
            return data
        return None

    def fetch_polymarket_trending(self) -> Optional[List[Dict]]:
        """Fetch Polymarket trending stocks (cached)."""
        url = f"{self._api_url}/polymarket/stocks/v1/trending"
        data = self._fetch_cached("polymarket_trending", url)
        if isinstance(data, dict):
            return data.get("trending", data.get("data", []))
        if isinstance(data, list):
            return data
        return None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def get_social_context(self, ticker: str) -> Optional[str]:
        """
        Fetch social sentiment from all platforms and return a formatted
        text block for the LLM prompt.  Returns None if no data found.
        """
        if not self.is_available:
            return None

        ticker_upper = ticker.upper()

        # 1. Reddit per-ticker report (richest data)
        reddit_data = self.fetch_reddit_report(ticker_upper)

        # 2. X trending (filter for this ticker)
        x_entry = None
        x_trending = self.fetch_x_trending()
        if x_trending:
            x_entry = self._find_ticker_in_trending(x_trending, ticker_upper)

        # 3. Polymarket trending (filter for this ticker)
        poly_entry = None
        poly_trending = self.fetch_polymarket_trending()
        if poly_trending:
            poly_entry = self._find_ticker_in_trending(poly_trending, ticker_upper)

        # If no data from any source, skip
        if not reddit_data and not x_entry and not poly_entry:
            return None

        return self._format_social_intel(ticker_upper, reddit_data, x_entry, poly_entry)

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _find_ticker_in_trending(trending: List[Dict], ticker: str) -> Optional[Dict]:
        """Find a ticker entry in a trending list."""
        for entry in trending:
            code = (entry.get("ticker") or entry.get("symbol") or entry.get("code") or "").upper()
            if code == ticker:
                return entry
        return None

    @staticmethod
    def _coalesce(*values):
        """Return the first value that is not None (preserves 0 and 0.0)."""
        for v in values:
            if v is not None:
                return v
        return None

    @staticmethod
    def _format_social_intel(
        ticker: str,
        reddit_data: Optional[Dict],
        x_entry: Optional[Dict],
        poly_entry: Optional[Dict],
    ) -> str:
        """Format social sentiment data as a prompt-ready text block."""
        lines = [f"📱 Social Sentiment Intelligence for {ticker} (Reddit / X / Polymarket)"]
        lines.append("=" * 60)

        # --- Reddit ---
        if reddit_data:
            lines.append("\n🔴 Reddit Community Sentiment:")
            report = reddit_data.get("report", reddit_data)

            # Buzz score
            buzz = SocialSentimentService._coalesce(report.get("buzz_score"), report.get("buzz"))
            if buzz is not None:
                trend_label = report.get("trend", "")
                lines.append(f"  Buzz Score: {buzz}/100 ({trend_label})" if trend_label
                             else f"  Buzz Score: {buzz}/100")

            # Sentiment (0 is a valid neutral value, must not be dropped)
            sentiment = SocialSentimentService._coalesce(report.get("sentiment_score"), report.get("sentiment"))
            if sentiment is not None:
                lines.append(f"  Sentiment Score: {sentiment}")

            # Mentions
            mentions = SocialSentimentService._coalesce(report.get("total_mentions"), report.get("mentions"))
            if mentions is not None:
                subs = SocialSentimentService._coalesce(report.get("subreddit_count"), report.get("subreddits"))
                sub_str = f" across {subs} subreddits" if subs else ""
                lines.append(f"  Mentions: {mentions}{sub_str} (7-day)")

            # Top mentions
            top_mentions = report.get("top_mentions", [])
            if top_mentions:
                lines.append("  Top Mentions:")
                for i, m in enumerate(top_mentions[:5], 1):
                    text = (m.get("text") or m.get("title") or "")[:120]
                    sub = m.get("subreddit", "")
                    score = SocialSentimentService._coalesce(m.get("sentiment_score"), m.get("sentiment"))
                    upvotes = m.get("upvotes", "")
                    meta_parts = []
                    if score is not None:
                        meta_parts.append(f"sentiment: {score}")
                    if sub:
                        meta_parts.append(f"r/{sub}")
                    if upvotes:
                        meta_parts.append(f"{upvotes} upvotes")
                    meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
                    lines.append(f"    {i}. \"{text}\"{meta}")

            # Daily stats
            daily = report.get("daily_stats", [])
            if daily:
                lines.append("  Recent Daily Activity:")
                for d in daily[:5]:
                    day = d.get("date", "")
                    day_mentions = d.get("mentions", "?")
                    day_sentiment = d.get("avg_sentiment", "?")
                    lines.append(f"    {day}: {day_mentions} mentions, avg sentiment {day_sentiment}")
        else:
            lines.append("\n🔴 Reddit: No data available")

        # --- X / Twitter ---
        if x_entry:
            lines.append("\n🐦 X (Twitter) Sentiment:")
            x_buzz = SocialSentimentService._coalesce(x_entry.get("buzz_score"), x_entry.get("buzz"))
            x_sentiment = SocialSentimentService._coalesce(x_entry.get("sentiment_score"), x_entry.get("sentiment"))
            x_mentions = SocialSentimentService._coalesce(x_entry.get("total_mentions"), x_entry.get("mentions"))
            x_trend = x_entry.get("trend", "")
            if x_buzz is not None:
                lines.append(f"  Buzz Score: {x_buzz}/100 ({x_trend})" if x_trend
                             else f"  Buzz Score: {x_buzz}/100")
            if x_sentiment is not None:
                lines.append(f"  Sentiment Score: {x_sentiment}")
            if x_mentions is not None:
                lines.append(f"  Mentions: {x_mentions} (7-day)")
        else:
            lines.append("\n🐦 X (Twitter): No data available")

        # --- Polymarket ---
        if poly_entry:
            lines.append("\n🔮 Polymarket (Prediction Markets):")
            poly_buzz = SocialSentimentService._coalesce(poly_entry.get("buzz_score"), poly_entry.get("buzz"))
            poly_sentiment = SocialSentimentService._coalesce(poly_entry.get("sentiment_score"), poly_entry.get("sentiment"))
            poly_trades = SocialSentimentService._coalesce(poly_entry.get("trade_count"), poly_entry.get("trades"))
            if poly_buzz is not None:
                lines.append(f"  Buzz Score: {poly_buzz}/100")
            if poly_sentiment is not None:
                lines.append(f"  Market Sentiment: {poly_sentiment}")
            if poly_trades is not None:
                lines.append(f"  Trade Count: {poly_trades}")
        else:
            lines.append("\n🔮 Polymarket: No active prediction markets found")

        lines.append("")
        lines.append("Source: api.adanos.org — Real-time social sentiment aggregation")
        return "\n".join(lines)
