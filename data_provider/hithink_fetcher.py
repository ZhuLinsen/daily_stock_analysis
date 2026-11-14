# -*- coding: utf-8 -*-
"""Optional HiThink Finance adapter for A-share stocks.

The public contract is the HiThink REST API (base ``https://fuyao.aicubes.cn``,
header ``X-api-key``). This adapter covers only the documented A-share price
endpoints:

- ``GET /api/a-share/prices/snapshot``
- ``GET /api/a-share/prices/historical``
- ``GET /api/a-share/prices/historical-batch``

Business errors use the response ``code`` while HTTP status stays 200.
Missing credentials, permission failures, rate limits, and transport errors
fail open so ``DataFetcherManager`` can continue with the existing providers.
The API key is never written into logs or exception text.
"""

from __future__ import annotations

import copy
import logging
import math
import re
import time
from datetime import datetime, timedelta, timezone
from threading import RLock, local
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from src.services.stock_list_parser import ParseStatus, parse_analysis_target

from .base import STANDARD_COLUMNS, BaseFetcher, DataFetchError, _is_etf_code
from .realtime_types import RealtimeSource, UnifiedRealtimeQuote, safe_float, safe_int

logger = logging.getLogger(__name__)
_request_budget = local()


class request_budget:
    """Bound later HTTP calls on this thread to an absolute monotonic deadline."""

    def __init__(self, deadline: Optional[float]) -> None:
        self.deadline = deadline
        self.previous = None

    def __enter__(self) -> "request_budget":
        self.previous = getattr(_request_budget, "deadline", None)
        if self.deadline is not None:
            _request_budget.deadline = self.deadline
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self.deadline is not None:
            _request_budget.deadline = self.previous
        return False


def request_budget_remaining() -> Optional[float]:
    deadline = getattr(_request_budget, "deadline", None)
    if deadline is None:
        return None
    return deadline - time.monotonic()

_BASE_URL = "https://fuyao.aicubes.cn"
_SNAPSHOT_PATH = "/api/a-share/prices/snapshot"
_HISTORICAL_PATH = "/api/a-share/prices/historical"
_HISTORICAL_BATCH_PATH = "/api/a-share/prices/historical-batch"
_ADJUSTMENTS = {"none", "forward", "backward"}
_SHANGHAI = ZoneInfo("Asia/Shanghai")
# Stay under the documented 10-year window, including the end-of-day timestamp.
_MAX_WINDOW_DAYS = 3600
_MAX_BATCH_SYMBOLS = 10
_AUTH_CODES = {2001}
_CAPABILITY_DENIED_CODE = 2003
_PERMISSION_CODE = 2004
_RATE_LIMIT_CODE = 4001
_SERVER_CODES = {5001, 5002, 5003}
_COOLDOWN_SECONDS = 60.0
_QUOTE_CACHE_SECONDS = 30.0


class HiThinkRequestError(DataFetchError):
    """Business or transport failure that must not include the API key."""

    def __init__(self, message: str, *, code: Optional[int] = None, permission: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.permission = permission


def normalize_hithink_kline_adjust(value: Optional[str]) -> str:
    """Return a documented adjustment mode, or ``none`` when the value is invalid."""
    text = (value or "none").strip().lower()
    if text in _ADJUSTMENTS:
        return text
    logger.warning("Invalid HITHINK_KLINE_ADJUST=%r; falling back to none", value)
    return "none"


class HiThinkFetcher(BaseFetcher):
    """HiThink-backed optional A-share stock fetcher."""

    name = "HiThinkFetcher"
    priority = 7

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        priority: int = 7,
        kline_adjust: str = "none",
        batch_daily_enabled: bool = True,
        batch_size: int = _MAX_BATCH_SYMBOLS,
        timeout: float = 15.0,
        retry_backoff: float = 0.2,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.priority = priority
        self.kline_adjust = normalize_hithink_kline_adjust(kline_adjust)
        self.batch_daily_enabled = bool(batch_daily_enabled)
        self.batch_size = max(1, min(int(batch_size), _MAX_BATCH_SYMBOLS))
        self.timeout = timeout
        self.retry_backoff = max(0.0, float(retry_backoff))
        self._lock = RLock()
        self._cooldown_until = 0.0
        self._batch_disabled_until = 0.0
        self._daily_disabled_until = 0.0
        self._realtime_disabled_until = 0.0
        self._fundamental_disabled_until = 0.0
        self._rank_disabled_until = 0.0
        self._index_daily_disabled_until = 0.0
        self._index_snapshot_disabled_until = 0.0
        self._directory_disabled_until = 0.0
        self._index_catalog_cache: Dict[str, Tuple[float, List[Tuple[str, str]]]] = {}
        self._last_error = ""
        self._successful = False
        self._daily_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
        self._daily_coverage: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        self._quote_cache: Dict[str, Tuple[float, UnifiedRealtimeQuote]] = {}

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def runtime_status(self) -> str:
        with self._lock:
            if not self.api_key or time.monotonic() < self._cooldown_until:
                return "unavailable"
            if self._successful:
                return "ok"
        return "unknown"

    def is_available(self, capability: str = "") -> bool:
        if not self.api_key:
            return False
        now = time.monotonic()
        with self._lock:
            if now < self._cooldown_until:
                return False
            if capability == "daily_data" and now < self._daily_disabled_until:
                return False
            if capability == "realtime_quote" and now < self._realtime_disabled_until:
                return False
            if capability == "fundamental" and now < self._fundamental_disabled_until:
                return False
            if capability == "index_rankings" and now < self._rank_disabled_until:
                return False
            if capability == "index_daily" and now < self._index_daily_disabled_until:
                return False
            if capability == "index_snapshot" and now < self._index_snapshot_disabled_until:
                return False
            if capability in {"stock_list", "stock_name"} and now < self._directory_disabled_until:
                return False
        return True

    def is_available_for_request(self, capability: str = "") -> bool:
        """Honor the manager's per-capability probe.

        ``DataFetcherManager`` passes the capability only to this method.
        A historical permission failure must not hide snapshot requests, and
        a snapshot permission failure must not hide historical requests.
        """
        if capability == "daily_batch":
            if not self.is_available():
                return False
            with self._lock:
                return time.monotonic() >= self._batch_disabled_until
        return self.is_available(capability)

    def _request_capability(self, path: str) -> str:
        if path == _HISTORICAL_PATH:
            return "daily_data"
        if path == _SNAPSHOT_PATH:
            return "realtime_quote"
        if path == _HISTORICAL_BATCH_PATH:
            return "daily_batch"
        return ""

    def _remember_error(
        self,
        message: str,
        *,
        cooldown: bool = False,
        batch_only: bool = False,
        daily_only: bool = False,
        realtime_only: bool = False,
        fundamental_only: bool = False,
        rank_only: bool = False,
        index_daily_only: bool = False,
        index_snapshot_only: bool = False,
        directory_only: bool = False,
    ) -> None:
        with self._lock:
            self._last_error = message
            deadline = time.monotonic() + _COOLDOWN_SECONDS
            if cooldown:
                self._cooldown_until = deadline
            if batch_only:
                self._batch_disabled_until = deadline
            if daily_only:
                self._daily_disabled_until = deadline
            if realtime_only:
                self._realtime_disabled_until = deadline
            if fundamental_only:
                self._fundamental_disabled_until = deadline
            if rank_only:
                self._rank_disabled_until = deadline
            if index_daily_only:
                self._index_daily_disabled_until = deadline
            if index_snapshot_only:
                self._index_snapshot_disabled_until = deadline
            if directory_only:
                self._directory_disabled_until = deadline

    def _mark_success(self) -> None:
        with self._lock:
            self._successful = True
            self._last_error = ""

    def _thscode(self, stock_code: str) -> Tuple[str, str]:
        """Map a project stock code to a documented ``thscode``.

        Exchange comes from the existing analysis-target parser. ETF, index,
        and non-A-share identities are rejected instead of being sent upstream.
        """
        target = parse_analysis_target(stock_code)
        if target.asset_type != ParseStatus.STOCK:
            raise DataFetchError("HiThink prices API supports A-share stocks only")
        if target.exchange not in {"SH", "SZ", "BJ"}:
            raise DataFetchError("HiThink prices API supports SH, SZ, and BJ stocks only")
        code = target.normalized_code
        if not re.fullmatch(r"\d{6}", code):
            raise DataFetchError("HiThink prices API supports 6-digit A-share codes only")
        if _is_etf_code(code):
            raise DataFetchError("HiThink prices API does not document ETF coverage")
        return f"{code}.{target.exchange}", code

    def _request(
        self,
        path: str,
        params: Dict[str, Any],
        capability: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send one HiThink request.

        ``capability`` is the caller's cooldown, used when the same URL serves
        more than one product. Stock snapshots stay on ``realtime_quote``.
        Index ranking snapshots and catalogs stay on ``index_rankings``.
        Index quotes use ``index_snapshot`` and index history uses ``index_daily``.
        """
        if not self.api_key:
            raise DataFetchError("HiThink API key is not configured")
        resolved_capability = self._request_capability(path) if capability is None else capability
        if not self.is_available_for_request(resolved_capability):
            raise DataFetchError("HiThink is cooling down after an authentication or rate-limit failure")

        url = f"{_BASE_URL}{path}"
        headers = {"X-api-key": self.api_key, "Accept": "application/json"}
        last_error: Optional[Exception] = None
        for attempt in range(3):
            remaining = request_budget_remaining()
            if remaining is not None and remaining <= 0:
                raise DataFetchError("HiThink request budget exhausted")
            http_timeout = self.timeout if remaining is None else min(self.timeout, remaining)
            try:
                response = requests.get(url, params=params, headers=headers, timeout=http_timeout)
            except requests.Timeout:
                last_error = HiThinkRequestError("HiThink request timed out")
                logger.warning("[HiThinkFetcher] request timed out: path=%s attempt=%s", path, attempt + 1)
                self._sleep_before_retry(attempt)
                continue
            except requests.RequestException:
                last_error = HiThinkRequestError("HiThink request failed")
                logger.warning("[HiThinkFetcher] request failed: path=%s attempt=%s", path, attempt + 1)
                self._sleep_before_retry(attempt)
                continue

            if response.status_code != 200:
                last_error = HiThinkRequestError(f"HiThink HTTP {response.status_code}")
                if response.status_code >= 500:
                    self._sleep_before_retry(attempt)
                    continue
                if response.status_code in {401, 403}:
                    self._remember_error("HiThink authentication failed", cooldown=True)
                raise last_error

            try:
                payload = response.json()
            except ValueError as exc:
                logger.warning("[HiThinkFetcher] invalid JSON: path=%s", path)
                raise HiThinkRequestError("HiThink returned invalid JSON") from exc
            if not isinstance(payload, dict):
                logger.warning("[HiThinkFetcher] response is not an object: path=%s", path)
                raise HiThinkRequestError("HiThink response is not an object")

            code = payload.get("code")
            if code == 0:
                self._mark_success()
                return payload

            request_id = payload.get("request_id")
            logger.warning(
                "[HiThinkFetcher] business error: path=%s code=%s request_id=%s",
                path,
                code,
                request_id,
            )
            error = self._error_from_code(code)
            if error.code == _RATE_LIMIT_CODE and attempt < 2:
                last_error = error
                self._sleep_before_retry(attempt)
                continue
            if error.code in _SERVER_CODES and attempt < 2:
                last_error = error
                self._sleep_before_retry(attempt)
                continue
            if error.code in _AUTH_CODES or error.code == _RATE_LIMIT_CODE:
                self._remember_error(str(error), cooldown=True)
            elif error.permission:
                self._remember_capability_denial(str(error), resolved_capability, path)
            else:
                self._remember_error(str(error))
            raise error

        if last_error is not None:
            if isinstance(last_error, HiThinkRequestError) and last_error.code == _RATE_LIMIT_CODE:
                self._remember_error(str(last_error), cooldown=True)
            raise last_error
        raise HiThinkRequestError("HiThink request failed")

    def _sleep_before_retry(self, attempt: int) -> None:
        """Wait before another attempt, never longer than the remaining budget.

        The HTTP timeout passed to ``requests`` limits each connect or read
        phase. It does not cancel a socket that has already been sent, and the
        caller-side thread join remains the isolation boundary.
        """
        if attempt >= 2 or self.retry_backoff <= 0:
            return
        delay = self.retry_backoff * (2 ** attempt)
        remaining = request_budget_remaining()
        if remaining is not None:
            if remaining <= 0:
                raise DataFetchError("HiThink request budget exhausted")
            delay = min(delay, remaining)
        time.sleep(delay)

    def _remember_capability_denial(self, message: str, capability: str, path: str) -> None:
        """Cool only the capability that returned 2003 or 2004.

        Code 2003 means this key cannot call the current capability. It is not
        an invalid-key failure, so the global cooldown stays untouched.
        """
        if capability == "daily_batch" or path == _HISTORICAL_BATCH_PATH:
            self._remember_error(message, batch_only=True)
        elif capability == "index_rankings":
            self._remember_error(message, rank_only=True)
        elif capability == "index_daily":
            self._remember_error(message, index_daily_only=True)
        elif capability == "index_snapshot":
            self._remember_error(message, index_snapshot_only=True)
        elif capability == "daily_data" or path == _HISTORICAL_PATH:
            self._remember_error(message, daily_only=True)
        elif capability == "realtime_quote" or path == _SNAPSHOT_PATH:
            self._remember_error(message, realtime_only=True)
        elif capability == "fundamental" or path.startswith("/api/a-share/financials/") or path.startswith("/api/a-share/valuations/"):
            self._remember_error(message, fundamental_only=True)
        elif capability == "stock_list" or path.startswith("/api/meta/tickers/"):
            self._remember_error(message, directory_only=True)
        else:
            self._remember_error(message)

    @staticmethod
    def _error_from_code(code: Any) -> HiThinkRequestError:
        if code in _AUTH_CODES:
            return HiThinkRequestError("HiThink authentication failed", code=int(code))
        if code in {_CAPABILITY_DENIED_CODE, _PERMISSION_CODE}:
            return HiThinkRequestError(
                "HiThink credential is not authorized for this capability",
                code=int(code),
                permission=True,
            )
        if code == _RATE_LIMIT_CODE:
            return HiThinkRequestError("HiThink rate limit", code=int(code))
        if code in _SERVER_CODES:
            return HiThinkRequestError("HiThink upstream error", code=int(code))
        if code in {1001, 1002, 1003, 1004}:
            return HiThinkRequestError(f"HiThink rejected the request parameters ({code})", code=int(code))
        if code in {3001, 3004}:
            return HiThinkRequestError("HiThink does not have this target", code=int(code))
        if code == 3002:
            return HiThinkRequestError("HiThink data is not ready", code=int(code))
        return HiThinkRequestError("HiThink returned an unsuccessful response", code=code if isinstance(code, int) else None)

    @staticmethod
    def _date_to_ms(date_str: str, *, end_of_day: bool = False) -> int:
        moment = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_SHANGHAI)
        if end_of_day:
            moment = moment + timedelta(days=1) - timedelta(milliseconds=1)
        return int(moment.timestamp() * 1000)

    @staticmethod
    def _ms_to_date(value: Any) -> Optional[str]:
        number = safe_float(value)
        if number is None:
            return None
        moment = datetime.fromtimestamp(number / 1000, tz=timezone.utc).astimezone(_SHANGHAI)
        return moment.strftime("%Y-%m-%d")

    @staticmethod
    def _windows(start_date: str, end_date: str) -> List[Tuple[str, str]]:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        if end < start:
            return []
        windows: List[Tuple[str, str]] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=_MAX_WINDOW_DAYS))
            windows.append((cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
            cursor = chunk_end + timedelta(days=1)
        return windows

    def _cache_key(self, thscode: str) -> Tuple[str, str]:
        return thscode, self.kline_adjust

    @staticmethod
    def _next_day(date_str: str) -> str:
        return (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    @classmethod
    def _merge_coverage(
        cls,
        ranges: List[Tuple[str, str]],
        start_date: str,
        end_date: str,
    ) -> List[Tuple[str, str]]:
        """Merge only overlapping or adjacent inclusive ranges.

        A later window must not stretch an earlier window across the dates in
        between. January 1–10 plus February 1–10 stays two ranges.
        """
        if end_date < start_date:
            return list(ranges)
        pending = sorted([*ranges, (start_date, end_date)])
        merged: List[Tuple[str, str]] = []
        for start, end in pending:
            if end < start:
                continue
            if not merged or start > cls._next_day(merged[-1][1]):
                merged.append((start, end))
                continue
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        return merged

    @staticmethod
    def _range_covered(ranges: List[Tuple[str, str]], start_date: str, end_date: str) -> bool:
        return any(covered_start <= start_date and covered_end >= end_date for covered_start, covered_end in ranges)

    @staticmethod
    def _has_daily_rows(frame: pd.DataFrame) -> bool:
        return (
            frame is not None
            and not frame.empty
            and "date" in frame.columns
            and bool(frame["date"].notna().any())
        )

    def _store_daily(self, thscode: str, start_date: str, end_date: str, frame: pd.DataFrame) -> bool:
        # An empty payload is a valid response, but it is not evidence that the
        # requested window can be reused. Keeping it would let later windows
        # widen the covered span without those dates ever being fetched.
        if not self._has_daily_rows(frame) or end_date < start_date:
            return False
        with self._lock:
            key = self._cache_key(thscode)
            current = self._daily_cache.get(key)
            incoming = frame.copy()
            if current is None or current.empty:
                stored = incoming
            else:
                stored = pd.concat([current, incoming], ignore_index=True)
                if "date" in stored.columns:
                    stored = stored.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
            self._daily_cache[key] = stored
            self._daily_coverage[key] = self._merge_coverage(
                self._daily_coverage.get(key, []),
                start_date,
                end_date,
            )
            return True

    def _load_daily(self, thscode: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        with self._lock:
            key = self._cache_key(thscode)
            if not self._range_covered(self._daily_coverage.get(key, []), start_date, end_date):
                return None
            cached = self._daily_cache.get(key)
            if cached is None or cached.empty:
                return None
            frame = cached.copy()
        if "date" not in frame.columns:
            return None
        dates = pd.to_datetime(frame["date"], errors="coerce")
        mask = dates.notna() & (dates >= pd.Timestamp(start_date)) & (dates <= pd.Timestamp(end_date))
        return frame.loc[mask].reset_index(drop=True)

    def _bars_frame(self, rows: Any, *, thscode: str) -> pd.DataFrame:
        if rows is None:
            return pd.DataFrame()
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise HiThinkRequestError("HiThink historical response has an invalid item list")
        frame = pd.DataFrame(rows)
        if frame.empty:
            return frame
        required = {"date_ms", "open_price", "high_price", "low_price", "close_price", "volume", "turnover"}
        if not required.issubset(frame.columns):
            raise HiThinkRequestError("HiThink historical response is missing required fields")
        frame["date"] = frame["date_ms"].map(self._ms_to_date)
        frame["thscode"] = thscode
        return frame

    def _fetch_historical_window(self, thscode: str, start_date: str, end_date: str) -> pd.DataFrame:
        payload = self._request(
            _HISTORICAL_PATH,
            {
                "thscode": thscode,
                "interval": "1d",
                "start": self._date_to_ms(start_date),
                "end": self._date_to_ms(end_date, end_of_day=True),
                "adjust": self.kline_adjust,
            },
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise HiThinkRequestError("HiThink historical response data is invalid")
        return self._bars_frame(data.get("item"), thscode=thscode)

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        thscode, _code = self._thscode(stock_code)
        cached = self._load_daily(thscode, start_date, end_date)
        if cached is not None:
            return cached
        frames: List[pd.DataFrame] = []
        for window_start, window_end in self._windows(start_date, end_date):
            window = self._fetch_historical_window(thscode, window_start, window_end)
            frames.append(window)
            self._store_daily(thscode, window_start, window_end, window)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        _thscode, code = self._thscode(stock_code)
        if df.empty:
            return pd.DataFrame(columns=["code", *STANDARD_COLUMNS])
        result = pd.DataFrame(
            {
                "date": df["date"],
                "open": pd.to_numeric(df["open_price"], errors="coerce"),
                "high": pd.to_numeric(df["high_price"], errors="coerce"),
                "low": pd.to_numeric(df["low_price"], errors="coerce"),
                "close": pd.to_numeric(df["close_price"], errors="coerce"),
                "volume": pd.to_numeric(df["volume"], errors="coerce"),
                "amount": pd.to_numeric(df["turnover"], errors="coerce"),
            }
        )
        for column in ("open", "high", "low", "close", "volume", "amount"):
            result[column] = result[column].replace([math.inf, -math.inf], pd.NA)
        result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        result = result.dropna(subset=["date", "open", "high", "low", "close", "volume"])
        result = result[(result["close"] > 0) & (result["volume"] >= 0)]
        result = result.sort_values("date").drop_duplicates("date", keep="last")
        previous = result["close"].shift(1)
        result["pct_chg"] = ((result["close"] / previous.where(previous > 0)) - 1) * 100
        result["code"] = code
        result = result[["code", *STANDARD_COLUMNS]].reset_index(drop=True)
        result.attrs["price_adjustment"] = self.kline_adjust
        return result

    def _quote_from_item(self, item: Dict[str, Any], *, code: str, thscode: str, timestamp: Any) -> UnifiedRealtimeQuote:
        returned = str(item.get("thscode") or "").upper()
        if returned != thscode.upper():
            raise DataFetchError("HiThink snapshot returned another target")
        price = safe_float(item.get("last_price"))
        if price is None or price <= 0:
            raise DataFetchError("HiThink snapshot is missing a valid price")
        volume = safe_float(item.get("volume"))
        provider_timestamp = None
        if safe_float(timestamp) is not None:
            moment = datetime.fromtimestamp(float(timestamp) / 1000, tz=timezone.utc).astimezone(_SHANGHAI)
            provider_timestamp = moment.isoformat()
        return UnifiedRealtimeQuote(
            code=code,
            source=RealtimeSource.HITHINK,
            price=price,
            change_amount=safe_float(item.get("price_change")),
            change_pct=safe_float(item.get("price_change_ratio_pct")),
            open_price=safe_float(item.get("open_price")),
            high=safe_float(item.get("high_price")),
            low=safe_float(item.get("low_price")),
            pre_close=safe_float(item.get("prev_price")),
            volume=safe_int(volume) if volume is not None and volume >= 0 else None,
            amount=safe_float(item.get("turnover")),
            provider_timestamp=provider_timestamp,
            market="cn",
            currency="CNY",
        )

    def _load_quotes(self, codes: List[Tuple[str, str]]) -> Dict[str, UnifiedRealtimeQuote]:
        quotes: Dict[str, UnifiedRealtimeQuote] = {}
        for offset in range(0, len(codes), self.batch_size):
            batch = codes[offset : offset + self.batch_size]
            try:
                payload = self._request(
                    _SNAPSHOT_PATH,
                    {"thscodes": ",".join(thscode for thscode, _code in batch)},
                )
            except HiThinkRequestError as exc:
                if exc.permission or len(batch) == 1:
                    raise
                for single in batch:
                    quotes.update(self._load_quotes([single]))
                continue
            data = payload.get("data") or {}
            if not isinstance(data, dict):
                raise HiThinkRequestError("HiThink snapshot response data is invalid")
            items = data.get("item")
            if items is None:
                items = []
            if not isinstance(items, list):
                raise HiThinkRequestError("HiThink snapshot response item is invalid")
            by_code = {
                str(item.get("thscode") or "").upper(): item
                for item in items
                if isinstance(item, dict)
            }
            for thscode, code in batch:
                item = by_code.get(thscode.upper())
                if item is None:
                    continue
                quotes[code] = self._quote_from_item(
                    item,
                    code=code,
                    thscode=thscode,
                    timestamp=data.get("timestamp"),
                )
        now = time.monotonic()
        with self._lock:
            for code, quote in quotes.items():
                self._quote_cache[code] = (now, quote)
        return quotes

    def get_realtime_quote(self, stock_code: str) -> UnifiedRealtimeQuote:
        thscode, code = self._thscode(stock_code)
        with self._lock:
            cached = self._quote_cache.get(code)
            if cached is not None and time.monotonic() - cached[0] < _QUOTE_CACHE_SECONDS:
                return copy.copy(cached[1])
        quote = self._load_quotes([(thscode, code)]).get(code)
        if quote is None:
            raise DataFetchError("HiThink snapshot returned no quote for the requested stock")
        return copy.copy(quote)

    def prefetch_realtime_quotes(self, stock_codes: Iterable[str], batch_size: Optional[int] = None) -> int:
        if batch_size is not None:
            self.batch_size = max(1, min(int(batch_size), _MAX_BATCH_SYMBOLS))
        selected: List[Tuple[str, str]] = []
        seen = set()
        for stock_code in stock_codes:
            try:
                thscode, code = self._thscode(stock_code)
            except DataFetchError:
                continue
            if code in seen:
                continue
            seen.add(code)
            selected.append((thscode, code))
        if not selected:
            return 0
        try:
            return len(self._load_quotes(selected))
        except HiThinkRequestError as exc:
            logger.info("[HiThinkFetcher] realtime prefetch failed open: %s", exc)
            return 0

    def prefetch_daily_klines(
        self,
        stock_codes: Iterable[str],
        *,
        days: int = 30,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> int:
        """Warm the daily cache through the documented batch endpoint.

        Permission failures disable only the batch path for a short cooldown
        and return the symbols already cached. Per-stock ``get_daily_data``
        remains available.
        """
        if not self.batch_daily_enabled:
            return 0
        with self._lock:
            if time.monotonic() < self._batch_disabled_until:
                return 0
        try:
            requested_days = int(days)
        except (TypeError, ValueError):
            logger.info("[HiThinkFetcher] skip daily prefetch because days is invalid: %r", days)
            return 0
        if requested_days <= 0:
            return 0
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if start_date is None:
            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=requested_days * 2)
            start_date = start_dt.strftime("%Y-%m-%d")

        selected: List[Tuple[str, str]] = []
        seen = set()
        for stock_code in stock_codes:
            try:
                thscode, _code = self._thscode(stock_code)
            except DataFetchError:
                continue
            if thscode in seen:
                continue
            seen.add(thscode)
            selected.append((thscode, stock_code))
        if not selected:
            return 0

        cached = 0
        windows = self._windows(start_date, end_date)
        for offset in range(0, len(selected), self.batch_size):
            batch = selected[offset : offset + self.batch_size]
            try:
                grouped = self._fetch_historical_batch(
                    [thscode for thscode, _stock in batch],
                    windows,
                )
            except HiThinkRequestError as exc:
                if exc.permission:
                    self._remember_error(str(exc), batch_only=True)
                    logger.info(
                        "[HiThinkFetcher] batch daily K-line is not authorized; fallback to single requests"
                    )
                    return cached
                logger.warning("[HiThinkFetcher] batch daily K-line failed: %s", exc)
                continue
            for thscode, _stock in batch:
                windows_for_symbol = grouped.get(thscode)
                if not windows_for_symbol:
                    continue
                # Store every window. any() would stop after the first success
                # and leave later 10-year chunks out of the cache.
                stored_any = False
                for window_start, window_end, frame in windows_for_symbol:
                    stored = self._store_daily(thscode, window_start, window_end, frame)
                    stored_any = stored or stored_any
                if stored_any:
                    cached += 1
        logger.info(
            "[HiThinkFetcher] batch daily prefetch complete: cached=%d total=%d",
            cached,
            len(selected),
        )
        return cached

    def _fetch_historical_batch(
        self,
        thscodes: List[str],
        windows: List[Tuple[str, str]],
    ) -> Dict[str, List[Tuple[str, str, pd.DataFrame]]]:
        grouped: Dict[str, List[Tuple[str, str, pd.DataFrame]]] = {}
        requested = set(thscodes)
        for window_start, window_end in windows:
            payload = self._request(
                _HISTORICAL_BATCH_PATH,
                {
                    "thscodes": ",".join(thscodes),
                    "interval": "1d",
                    "start": self._date_to_ms(window_start),
                    "end": self._date_to_ms(window_end, end_of_day=True),
                    "adjust": self.kline_adjust,
                },
            )
            data = payload.get("data") or {}
            if not isinstance(data, dict) or not isinstance(data.get("item"), list):
                raise HiThinkRequestError("HiThink batch historical response is invalid")
            self._require_batch_contract(data)
            # Unknown targets are omitted by the API. Do not cache those symbols,
            # so the per-stock historical call can still run. Nothing is stored
            # until every window in this call matches the requested contract.
            for group in data["item"]:
                if not isinstance(group, dict):
                    continue
                thscode = str(group.get("thscode") or "")
                if thscode not in requested:
                    continue
                grouped.setdefault(thscode, []).append(
                    (window_start, window_end, self._bars_frame(group.get("item"), thscode=thscode))
                )
        return grouped

    def _require_batch_contract(self, data: Dict[str, Any]) -> None:
        """Reject a batch payload whose shared interval or adjustment differs.

        The official batch envelope returns ``interval`` and ``adjust`` for the
        whole response. Caching that payload under another adjustment would mix
        forward-adjusted bars into the unadjusted cache.
        """
        interval = data.get("interval")
        adjust = data.get("adjust")
        if interval == "1d" and adjust == self.kline_adjust:
            return
        logger.warning(
            "[HiThinkFetcher] batch historical contract mismatch: interval=%s adjust=%s expected_interval=1d expected_adjust=%s",
            interval,
            adjust,
            self.kline_adjust,
        )
        raise HiThinkRequestError("HiThink batch historical response does not match the requested interval or adjustment")

    def get_main_indices(self, region: str = "cn"):
        from .hithink_index import main_indices

        return main_indices(self, region)

    def get_index_daily_data(self, thscode: str, start_date=None, end_date=None, days: int = 30):
        from .hithink_index import index_daily_data

        return index_daily_data(self, thscode, start_date, end_date, days)

    def get_sector_rankings(self, n: int = 5):
        from .hithink_index import rankings

        return rankings(self, "industry", n)

    def get_concept_rankings(self, n: int = 5):
        from .hithink_index import rankings

        return rankings(self, "cn_concept", n)

    def get_stock_name(self, stock_code: str):
        from .hithink_reference import stock_name

        return stock_name(self, stock_code)

    def get_stock_list(self):
        from .hithink_reference import stock_list

        return stock_list(self)

    def get_hot_stocks(self, n: int = 10):
        from .hithink_reference import hot_stocks

        return hot_stocks(self, n)

    def get_limit_up_pool(self, date=None, n: int = 20):
        from .hithink_reference import limit_up_pool

        return limit_up_pool(self, date, n)
