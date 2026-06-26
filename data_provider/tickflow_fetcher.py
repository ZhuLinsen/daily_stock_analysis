# -*- coding: utf-8 -*-
"""
TickFlow data source adapter.

TickFlow is optional and fail-open in this project. The fetcher supports
general A-share daily K-lines/realtime quotes, keeps the existing market review
capability, and exposes advanced TickFlow-only helpers for future consumers.
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta, timezone
from threading import RLock
from time import monotonic
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

try:
    import exchange_calendars as xcals
except ImportError:  # pragma: no cover - optional dependency in lightweight installs.
    xcals = None

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - defensive fallback for old runtimes.
    ZoneInfo = None  # type: ignore

from .base import (
    BaseFetcher,
    DataFetchError,
    STANDARD_COLUMNS,
    is_bse_code,
    is_kc_cy_stock,
    is_st_stock,
    normalize_stock_code,
)
from .realtime_types import RealtimeSource, UnifiedRealtimeQuote, safe_int


logger = logging.getLogger(__name__)

_CN_MAIN_INDEX_QUOTES = (
    ("000001.SH", "000001", "\u4e0a\u8bc1\u6307\u6570"),
    ("399001.SZ", "399001", "\u6df1\u8bc1\u6210\u6307"),
    ("399006.SZ", "399006", "\u521b\u4e1a\u677f\u6307"),
    ("000688.SH", "000688", "\u79d1\u521b50"),
    ("000016.SH", "000016", "\u4e0a\u8bc150"),
    ("000300.SH", "000300", "\u6caa\u6df1300"),
)
_CN_UNIVERSE_ID = "CN_Equity_A"
_MAX_SYMBOLS_PER_QUOTE_REQUEST = 5
_CAPABILITY_NEGATIVE_CACHE_TTL_SECONDS = 900
_MAX_DAILY_PREFETCH_LOOKBACK_DAYS = 730
_MIN_DAILY_KLINE_COUNT = 30
_MAX_DAILY_KLINE_COUNT = 10000
_DAILY_KLINE_COUNT_MULTIPLIER = 1.8
_DAILY_KLINE_COUNT_BUFFER = 20
_SUPPORTED_KLINE_ADJUSTS = {
    "none",
    "forward",
    "backward",
    "forward_additive",
    "backward_additive",
}


def _parse_env_int(name: str, default: int, minimum: int = 1) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not str(raw_value).strip():
        return default
    try:
        parsed = int(str(raw_value).strip())
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; falling back to %s", name, raw_value, default)
        return default
    return max(minimum, parsed)


class TickFlowFetcher(BaseFetcher):
    """TickFlow-backed optional A-share fetcher."""

    name = "TickFlowFetcher"
    priority = 2

    def __init__(
        self,
        api_key: Optional[str],
        timeout: float = 30.0,
        *,
        kline_adjust: Optional[str] = None,
        batch_daily_enabled: Optional[bool] = None,
        batch_size: Optional[int] = None,
        priority: Optional[int] = None,
    ):
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self.priority = self._normalize_priority(priority)
        self.kline_adjust = self._normalize_adjust(
            kline_adjust or os.getenv("TICKFLOW_KLINE_ADJUST", "none")
        )
        self.batch_daily_enabled = (
            self._parse_bool(os.getenv("TICKFLOW_BATCH_DAILY_ENABLED"), True)
            if batch_daily_enabled is None
            else bool(batch_daily_enabled)
        )
        self.batch_size = max(1, int(batch_size)) if batch_size is not None else _parse_env_int("TICKFLOW_BATCH_SIZE", 100)

        self._client = None
        self._client_lock = RLock()

        self._daily_cache: Dict[Tuple[str, str, str, str], pd.DataFrame] = {}
        self._daily_cache_lock = RLock()
        self._quote_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._quote_cache_lock = RLock()

        self._capability_lock = RLock()
        self._capability_supported: Dict[str, Optional[bool]] = {
            "batch_daily": None,
            "universe_quotes": None,
        }
        self._capability_checked_at: Dict[str, float] = {}

    def close(self) -> None:
        """Close the underlying TickFlow client if it was created."""
        with self._client_lock:
            client = self._client
            self._client = None
        with self._capability_lock:
            for key in self._capability_supported:
                self._capability_supported[key] = None
            self._capability_checked_at.clear()
        if client is not None:
            try:
                client.close()
            except Exception as exc:
                logger.debug("[TickFlowFetcher] close client failed: %s", exc)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _build_client(self):
        from tickflow import TickFlow

        return TickFlow(api_key=self.api_key, timeout=self.timeout)

    def _get_client(self):
        if not self.api_key:
            return None
        if self._client is not None:
            return self._client

        with self._client_lock:
            if self._client is None:
                self._client = self._build_client()
            return self._client

    def _fetch_raw_data(
        self, stock_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        symbol = self._to_tickflow_symbol(stock_code)
        if not symbol:
            raise DataFetchError("TickFlowFetcher only supports A-share/ETF symbols")

        cache_key = self._daily_cache_key(symbol, start_date, end_date)
        cached = self._get_daily_cache(cache_key)
        if cached is not None:
            return cached

        client = self._get_client()
        if client is None:
            raise DataFetchError("TickFlow API key is not configured")

        request_count = self._daily_kline_count(start_date, end_date)
        try:
            df = client.klines.get(
                symbol,
                period="1d",
                count=request_count,
                start_time=self._date_to_ms(start_date),
                end_time=self._date_to_ms(end_date, end_of_day=True),
                adjust=self.kline_adjust,
                as_dataframe=True,
            )
        except Exception as exc:
            raise DataFetchError(f"TickFlow daily K-line request failed: {exc}") from exc

        raw_df = self._prepare_daily_frame(
            df,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            count=request_count,
            context="single",
        )
        self._set_daily_cache(cache_key, raw_df)
        return raw_df.copy()

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raw = self._coerce_frame(df)
        if raw.empty:
            return pd.DataFrame(columns=["code", *STANDARD_COLUMNS])

        normalized = pd.DataFrame()
        normalized["date"] = self._extract_date_series(raw)
        normalized["code"] = normalize_stock_code(stock_code)
        for column in ("open", "high", "low", "close", "amount"):
            normalized[column] = pd.to_numeric(raw.get(column), errors="coerce")

        # TickFlow daily volume is in lots for A-shares; project standard is shares.
        normalized["volume"] = self._cn_lots_to_shares(raw.get("volume"))

        if "pct_chg" in raw.columns:
            normalized["pct_chg"] = pd.to_numeric(raw["pct_chg"], errors="coerce")
        elif "change_pct" in raw.columns:
            normalized["pct_chg"] = self._ratio_series_to_percent(raw["change_pct"])
        else:
            close = pd.to_numeric(normalized["close"], errors="coerce")
            normalized["pct_chg"] = close.pct_change().fillna(0.0) * 100.0

        normalized = normalized.dropna(subset=["date", "close", "volume"])
        normalized = normalized.sort_values("date", ascending=True).reset_index(drop=True)
        return normalized[["code", *STANDARD_COLUMNS]]

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        if value in (None, "", "-"):
            return None
        try:
            numeric = float(value)
            if math.isnan(numeric):
                return None
            return numeric
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_bool(value: Optional[str], default: bool) -> bool:
        if value is None:
            return default
        normalized = value.strip().lower()
        if not normalized:
            return default
        return normalized not in {"0", "false", "no", "off"}

    @staticmethod
    def _normalize_priority(value: Optional[int]) -> int:
        if value is None:
            return _parse_env_int("TICKFLOW_PRIORITY", 2, minimum=0)
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            logger.warning("Invalid TickFlow priority=%r; falling back to 2", value)
            return 2

    @staticmethod
    def _normalize_adjust(value: Optional[str]) -> str:
        normalized = (value or "none").strip().lower()
        if normalized in _SUPPORTED_KLINE_ADJUSTS:
            return normalized
        logger.warning(
            "Invalid TICKFLOW_KLINE_ADJUST=%r; falling back to none",
            value,
        )
        return "none"

    @classmethod
    def _ratio_to_percent(cls, value: Any) -> Optional[float]:
        ratio = cls._safe_float(value)
        if ratio is None:
            return None
        return ratio * 100.0

    @classmethod
    def _ratio_series_to_percent(cls, series: pd.Series) -> pd.Series:
        return pd.to_numeric(series, errors="coerce") * 100.0

    @classmethod
    def _cn_lots_to_shares(cls, lots: Any, default: Optional[int] = None) -> Any:
        if isinstance(lots, pd.Series):
            return pd.to_numeric(lots, errors="coerce") * 100
        volume = safe_int(lots, default)
        if volume is None:
            return default
        return volume * 100

    @staticmethod
    def _extract_name(quote: Dict[str, Any]) -> str:
        ext = quote.get("ext") or {}
        name = ext.get("name") or quote.get("name") or ""
        return str(name).strip()

    @staticmethod
    def _is_permission_error(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        code = str(getattr(exc, "code", "") or "").upper()
        message = f"{getattr(exc, 'message', '')} {exc}".strip().lower()

        if status_code == 403:
            return True
        if code in {"PERMISSION_DENIED", "FORBIDDEN", "UNAUTHORIZED"}:
            return True
        return any(
            keyword in message
            for keyword in (
                "permission",
                "forbidden",
                "unauthorized",
                "not entitled",
                "no access",
                "\u6743\u9650",
                "\u65e0\u6743",
                "\u5957\u9910",
            )
        )

    @classmethod
    def _is_universe_permission_error(cls, exc: Exception) -> bool:
        message = f"{getattr(exc, 'message', '')} {exc}".strip().lower()
        return cls._is_permission_error(exc) or "universe" in message or "\u6807\u7684\u6c60" in message

    @staticmethod
    def _is_cn_equity_symbol(symbol: str) -> bool:
        normalized = normalize_stock_code(symbol)
        upper_symbol = (symbol or "").strip().upper()
        return (
            normalized.isdigit()
            and len(normalized) == 6
            and upper_symbol.endswith((".SH", ".SZ", ".BJ"))
        )

    @staticmethod
    def _round_limit_price(prev_close: float, ratio: float) -> float:
        return math.floor(prev_close * (1 + ratio) * 100 + 0.5) / 100.0

    @classmethod
    def _get_limit_ratio(cls, pure_code: str, name: str) -> float:
        if is_bse_code(pure_code):
            return 0.30
        if is_kc_cy_stock(pure_code):
            return 0.20
        if is_st_stock(name):
            return 0.05
        return 0.10

    @staticmethod
    def _coerce_frame(value: Any) -> pd.DataFrame:
        if value is None:
            return pd.DataFrame()
        if isinstance(value, pd.DataFrame):
            return value.copy()
        if isinstance(value, list):
            return pd.DataFrame(value)
        if isinstance(value, dict):
            try:
                return pd.DataFrame(value)
            except ValueError as exc:
                if "all scalar values" in str(exc).lower():
                    return pd.DataFrame([value])
                raise
        return pd.DataFrame(value)

    @staticmethod
    def _exchange_from_code(stock_code: str) -> Optional[str]:
        upper = (stock_code or "").strip().upper()
        if upper.endswith(".SS"):
            return "SH"
        if upper.endswith((".SH", ".SZ", ".BJ")):
            return upper.rsplit(".", 1)[1]
        if upper.startswith(("SH.", "SS.")):
            return "SH"
        if upper.startswith("SZ."):
            return "SZ"
        if upper.startswith("BJ."):
            return "BJ"
        if upper.startswith("SH"):
            return "SH"
        if upper.startswith("SZ"):
            return "SZ"
        if upper.startswith("BJ"):
            return "BJ"
        return None

    @classmethod
    def _to_tickflow_symbol(cls, stock_code: str) -> Optional[str]:
        code = normalize_stock_code(stock_code)
        if not (code.isdigit() and len(code) == 6):
            return None

        exchange = cls._exchange_from_code(stock_code)
        if not exchange:
            if is_bse_code(code):
                exchange = "BJ"
            elif code.startswith(("6", "5")):
                exchange = "SH"
            elif code.startswith(("0", "1", "2", "3")):
                exchange = "SZ"
            else:
                return None
        return f"{code}.{exchange}"

    @staticmethod
    def _date_to_ms(date_str: str, *, end_of_day: bool = False) -> int:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if end_of_day:
            dt = dt + timedelta(days=1) - timedelta(milliseconds=1)
        if ZoneInfo is not None:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        else:
            dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
        return int(dt.timestamp() * 1000)

    @staticmethod
    def _extract_date_series(raw: pd.DataFrame) -> pd.Series:
        if "date" in raw.columns:
            return pd.to_datetime(raw["date"], errors="coerce").dt.normalize()
        if "trade_date" in raw.columns:
            return pd.to_datetime(raw["trade_date"], errors="coerce").dt.normalize()
        for column in ("timestamp", "time", "ts"):
            if column in raw.columns:
                numeric = pd.to_numeric(raw[column], errors="coerce")
                return pd.to_datetime(numeric, unit="ms", errors="coerce").dt.normalize()
        return pd.Series(pd.NaT, index=raw.index)

    @staticmethod
    def _daily_kline_count(start_date: str, end_date: str) -> int:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            calendar_days = max(1, (end - start).days + 1)
        except (TypeError, ValueError):
            calendar_days = 365
        estimated = int(calendar_days * _DAILY_KLINE_COUNT_MULTIPLIER) + _DAILY_KLINE_COUNT_BUFFER
        return max(_MIN_DAILY_KLINE_COUNT, min(_MAX_DAILY_KLINE_COUNT, estimated))

    @classmethod
    def _prepare_daily_frame(
        cls,
        value: Any,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        count: int,
        context: str,
    ) -> pd.DataFrame:
        frame = cls._coerce_frame(value)
        if frame.empty:
            return frame

        dates = cls._extract_date_series(frame)
        valid_dates = dates.dropna()
        if valid_dates.empty:
            logger.warning(
                "[TickFlowFetcher] daily K-line response has no usable dates: symbol=%s context=%s rows=%d count=%d",
                symbol,
                context,
                len(frame),
                count,
            )
            return pd.DataFrame(columns=frame.columns)

        if cls._is_daily_frame_truncated(
            dates=valid_dates,
            start_date=start_date,
            end_date=end_date,
            count=count,
            returned_rows=len(frame),
        ):
            first_date = valid_dates.min().strftime("%Y-%m-%d")
            last_date = valid_dates.max().strftime("%Y-%m-%d")
            logger.warning(
                "[TickFlowFetcher] reject incomplete daily K-line response: symbol=%s context=%s "
                "start=%s end=%s first=%s last=%s rows=%d count=%d reason=count_cap",
                symbol,
                context,
                start_date,
                end_date,
                first_date,
                last_date,
                len(frame),
                count,
            )
            raise DataFetchError(
                "TickFlow daily K-line response may be truncated by count: "
                f"symbol={symbol} start={start_date} end={end_date} rows={len(frame)} count={count}"
            )

        start = pd.Timestamp(start_date).normalize()
        end = pd.Timestamp(end_date).normalize()
        in_range = dates.notna() & (dates >= start) & (dates <= end)
        if not in_range.any():
            return pd.DataFrame(columns=frame.columns)
        return frame.loc[in_range].reset_index(drop=True)

    @classmethod
    def _is_daily_frame_truncated(
        cls,
        *,
        dates: pd.Series,
        start_date: str,
        end_date: str,
        count: int,
        returned_rows: int,
    ) -> bool:
        if returned_rows < count:
            return False
        try:
            requested_start = datetime.strptime(start_date, "%Y-%m-%d")
        except (TypeError, ValueError):
            return False

        first_expected = cls._first_trading_date_on_or_after(requested_start)
        first_returned = dates.min().to_pydatetime().replace(tzinfo=None)
        return first_returned > first_expected

    @staticmethod
    def _first_trading_date_on_or_after(start_date: datetime) -> datetime:
        if xcals is not None:
            try:
                cal = xcals.get_calendar("XSHG")
                session = cal.date_to_session(start_date.date(), direction="next")
                return datetime.combine(session.date(), datetime.min.time())
            except Exception:
                pass
        current = start_date
        while current.weekday() >= 5:
            current += timedelta(days=1)
        return current

    def _daily_cache_key(self, symbol: str, start_date: str, end_date: str) -> Tuple[str, str, str, str]:
        return (symbol.upper(), start_date, end_date, self.kline_adjust)

    def _get_daily_cache(self, cache_key: Tuple[str, str, str, str]) -> Optional[pd.DataFrame]:
        with self._daily_cache_lock:
            cached = self._daily_cache.get(cache_key)
            if cached is not None:
                return cached.copy()
        return None

    def _set_daily_cache(self, cache_key: Tuple[str, str, str, str], df: pd.DataFrame) -> None:
        with self._daily_cache_lock:
            self._daily_cache[cache_key] = self._coerce_frame(df)

    def _capability_available(self, capability: str) -> bool:
        now = monotonic()
        with self._capability_lock:
            supported = self._capability_supported.get(capability)
            if supported is not False:
                return True
            checked_at = self._capability_checked_at.get(capability, 0.0)
            if now - checked_at >= _CAPABILITY_NEGATIVE_CACHE_TTL_SECONDS:
                self._capability_supported[capability] = None
                self._capability_checked_at.pop(capability, None)
                return True
            return False

    def _mark_capability(self, capability: str, supported: bool) -> None:
        with self._capability_lock:
            self._capability_supported[capability] = supported
            self._capability_checked_at[capability] = monotonic()

    def prefetch_daily_klines(
        self,
        stock_codes: Iterable[str],
        *,
        days: int = 30,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> int:
        """Batch-prefetch daily K-lines into the per-process raw cache.

        Args:
            stock_codes: Project stock codes to prefetch.
            days: Target trading days to cover. When start_date is omitted,
                up to days * 2 calendar days are fetched, capped at 730 days.
            start_date: Optional YYYY-MM-DD lower bound.
            end_date: Optional YYYY-MM-DD upper bound.
        """
        if not self.batch_daily_enabled or not self._capability_available("batch_daily"):
            return 0

        try:
            requested_days = int(days)
        except (TypeError, ValueError):
            logger.info(
                "[TickFlowFetcher] skip daily K-line prefetch because days is invalid: %r",
                days,
            )
            return 0
        if requested_days <= 0:
            logger.info(
                "[TickFlowFetcher] skip daily K-line prefetch because days must be positive: %r",
                days,
            )
            return 0

        client = self._get_client()
        if client is None:
            return 0

        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if start_date is None:
            lookback_days = min(requested_days * 2, _MAX_DAILY_PREFETCH_LOOKBACK_DAYS)
            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=lookback_days)
            start_date = start_dt.strftime("%Y-%m-%d")

        symbols = self._dedupe_symbols(stock_codes)
        if not symbols:
            return 0

        batch_count = (len(symbols) + self.batch_size - 1) // self.batch_size
        cached_count = 0
        for offset in range(0, len(symbols), self.batch_size):
            batch_symbols = symbols[offset : offset + self.batch_size]
            try:
                request_count = self._daily_kline_count(start_date, end_date)
                batch_result = client.klines.batch(
                    batch_symbols,
                    period="1d",
                    count=request_count,
                    start_time=self._date_to_ms(start_date),
                    end_time=self._date_to_ms(end_date, end_of_day=True),
                    adjust=self.kline_adjust,
                    as_dataframe=True,
                )
                self._mark_capability("batch_daily", True)
            except Exception as exc:
                if self._is_permission_error(exc):
                    self._mark_capability("batch_daily", False)
                    logger.info(
                        "[TickFlowFetcher] batch daily K-line is not available; fallback to single requests"
                    )
                    logger.info(
                        "[TickFlowFetcher] batch daily prefetch complete: cached=%d total=%d batches=%d",
                        cached_count,
                        len(symbols),
                        batch_count,
                    )
                    return cached_count
                logger.warning("[TickFlowFetcher] batch daily K-line failed: %s", exc)
                continue

            for symbol, df in self._iter_batch_frames(batch_result):
                if not symbol:
                    continue
                cache_key = self._daily_cache_key(symbol, start_date, end_date)
                try:
                    frame = self._prepare_daily_frame(
                        df,
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        count=request_count,
                        context="batch",
                    )
                except DataFetchError:
                    continue
                if frame.empty:
                    continue
                self._set_daily_cache(cache_key, frame)
                cached_count += 1

        logger.info(
            "[TickFlowFetcher] batch daily prefetch complete: cached=%d total=%d batches=%d",
            cached_count,
            len(symbols),
            batch_count,
        )
        return cached_count

    @classmethod
    def _dedupe_symbols(cls, stock_codes: Iterable[str]) -> List[str]:
        symbols: List[str] = []
        seen = set()
        for stock_code in stock_codes:
            symbol = cls._to_tickflow_symbol(stock_code)
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
        return symbols

    @staticmethod
    def _iter_batch_frames(batch_result: Any) -> Iterable[Tuple[str, Any]]:
        if isinstance(batch_result, dict):
            for symbol, df in batch_result.items():
                yield str(symbol).upper(), df
            return

        if isinstance(batch_result, pd.DataFrame):
            if "symbol" not in batch_result.columns:
                return
            for symbol, group in batch_result.groupby("symbol"):
                yield str(symbol).upper(), group.reset_index(drop=True)
            return

        if isinstance(batch_result, list):
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for item in batch_result:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").upper()
                if not symbol:
                    continue
                grouped.setdefault(symbol, []).append(item)
            for symbol, rows in grouped.items():
                yield symbol, pd.DataFrame(rows)

    def prefetch_realtime_quotes(
        self,
        stock_codes: Iterable[str],
        *,
        batch_size: Optional[int] = None,
    ) -> int:
        """Batch-prefetch realtime quotes into the quote cache."""
        client = self._get_client()
        if client is None:
            return 0

        symbols = self._dedupe_symbols(stock_codes)
        if not symbols:
            return 0

        effective_batch_size = max(1, int(batch_size or self.batch_size))
        cached_count = 0
        for offset in range(0, len(symbols), effective_batch_size):
            batch_symbols = symbols[offset : offset + effective_batch_size]
            try:
                quotes = client.quotes.get(symbols=batch_symbols)
            except Exception as exc:
                logger.warning("[TickFlowFetcher] batch realtime quote failed: %s", exc)
                continue
            cached_count += self._store_quotes(quotes)
        return cached_count

    def _store_quotes(self, quotes: Any) -> int:
        if not quotes:
            return 0
        if isinstance(quotes, dict):
            quotes_iter = [quotes]
        else:
            quotes_iter = list(quotes)
        stored = 0
        now = monotonic()
        with self._quote_cache_lock:
            for quote in quotes_iter:
                if not isinstance(quote, dict):
                    continue
                symbol = str(quote.get("symbol") or "").upper()
                if not symbol:
                    continue
                self._quote_cache[symbol] = (now, quote)
                stored += 1
        return stored

    def _get_cached_quote(self, symbol: str, ttl_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
        ttl = 600 if ttl_seconds is None else max(0, int(ttl_seconds))
        now = monotonic()
        with self._quote_cache_lock:
            cached = self._quote_cache.get(symbol.upper())
            if not cached:
                return None
            cached_at, quote = cached
            if ttl and now - cached_at > ttl:
                self._quote_cache.pop(symbol.upper(), None)
                return None
            return dict(quote)

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        symbol = self._to_tickflow_symbol(stock_code)
        if not symbol:
            return None

        quote_ttl = self._get_realtime_cache_ttl()
        quote = self._get_cached_quote(symbol, quote_ttl)
        if quote is None:
            client = self._get_client()
            if client is None:
                return None
            try:
                quotes = client.quotes.get(symbols=[symbol])
            except Exception as exc:
                logger.warning("[TickFlowFetcher] realtime quote failed for %s: %s", symbol, exc)
                return None
            self._store_quotes(quotes)
            quote = self._get_cached_quote(symbol, quote_ttl)

        if not quote:
            return None
        return self._quote_to_unified_quote(stock_code, quote)

    @staticmethod
    def _get_realtime_cache_ttl() -> int:
        try:
            from src.config import get_config

            return int(get_config().realtime_cache_ttl)
        except Exception:
            return 600

    def _quote_to_unified_quote(
        self,
        stock_code: str,
        quote: Dict[str, Any],
    ) -> Optional[UnifiedRealtimeQuote]:
        symbol = str(quote.get("symbol") or self._to_tickflow_symbol(stock_code) or "").upper()
        code = normalize_stock_code(stock_code or symbol)
        current = self._safe_float(quote.get("last_price"))
        if current is None:
            current = self._safe_float(quote.get("price"))
        if current is None:
            return None

        ext = quote.get("ext") or {}
        prev_close = self._safe_float(quote.get("prev_close"))
        open_price = self._safe_float(quote.get("open"))
        high = self._safe_float(quote.get("high"))
        low = self._safe_float(quote.get("low"))
        volume = self._cn_lots_to_shares(quote.get("volume"), default=0)
        amount = self._safe_float(quote.get("amount")) or 0.0
        change_amount = self._safe_float(ext.get("change_amount"))
        if change_amount is None and prev_close is not None:
            change_amount = current - prev_close

        change_pct = self._ratio_to_percent(ext.get("change_pct"))
        if change_pct is None and prev_close and prev_close > 0:
            change_pct = (current - prev_close) / prev_close * 100.0

        timestamp = quote.get("timestamp") or quote.get("time") or quote.get("ts")
        provider_timestamp = self._format_provider_timestamp(timestamp)

        return UnifiedRealtimeQuote(
            code=code,
            name=self._extract_name(quote),
            price=current,
            change_pct=change_pct,
            change_amount=change_amount,
            volume=volume,
            amount=amount,
            open_price=open_price,
            high=high,
            low=low,
            pre_close=prev_close,
            source=RealtimeSource.TICKFLOW,
            provider_timestamp=provider_timestamp,
            turnover_rate=self._ratio_to_percent(ext.get("turnover_rate")),
            amplitude=self._ratio_to_percent(ext.get("amplitude")),
        )

    @staticmethod
    def _format_provider_timestamp(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        if numeric <= 0:
            return None
        if numeric > 10_000_000_000:
            numeric = numeric / 1000.0
        return datetime.fromtimestamp(numeric, timezone.utc).isoformat()

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        symbol = self._to_tickflow_symbol(stock_code)
        quote = self._get_cached_quote(symbol) if symbol else None
        name = self._extract_name(quote or {}) if quote else ""
        if name:
            return name

        client = self._get_client()
        if client is None or not symbol:
            return None

        try:
            quotes = client.quotes.get(symbols=[symbol])
            self._store_quotes(quotes)
            cached = self._get_cached_quote(symbol)
            name = self._extract_name(cached or {})
            if name:
                return name
        except Exception:
            logger.debug("[TickFlowFetcher] quote name lookup failed for %s", symbol, exc_info=True)

        try:
            instrument = client.instruments.get(symbol)
            return self._extract_instrument_name(instrument)
        except Exception:
            logger.debug("[TickFlowFetcher] instrument lookup failed for %s", symbol, exc_info=True)
        return None

    @staticmethod
    def _extract_instrument_name(instrument: Any) -> Optional[str]:
        if isinstance(instrument, list):
            if not instrument:
                return None
            instrument = instrument[0]
        if not isinstance(instrument, dict):
            return None
        name = (
            instrument.get("name")
            or instrument.get("short_name")
            or instrument.get("display_name")
            or (instrument.get("ext") or {}).get("name")
        )
        return str(name).strip() if name else None

    def get_stock_list(self) -> pd.DataFrame:
        client = self._get_client()
        if client is None:
            return pd.DataFrame(columns=["code", "name", "industry", "area", "market"])

        try:
            universe = client.universes.get(_CN_UNIVERSE_ID)
            entries = self._extract_universe_entries(universe)
        except Exception as exc:
            if self._is_universe_permission_error(exc):
                logger.info("[TickFlowFetcher] universe list is not available for current plan")
                return pd.DataFrame(columns=["code", "name", "industry", "area", "market"])
            logger.warning("[TickFlowFetcher] stock universe lookup failed: %s", exc)
            return pd.DataFrame(columns=["code", "name", "industry", "area", "market"])

        rows = []
        for entry in entries:
            symbol = entry["symbol"]
            if not self._is_cn_equity_symbol(symbol):
                continue
            rows.append(
                {
                    "code": normalize_stock_code(symbol),
                    "name": entry.get("name", ""),
                    "industry": "",
                    "area": "",
                    "market": symbol.rsplit(".", 1)[-1],
                }
            )
        return pd.DataFrame(rows, columns=["code", "name", "industry", "area", "market"])

    @staticmethod
    def _extract_universe_entries(universe: Any) -> List[Dict[str, str]]:
        if universe is None:
            return []
        if isinstance(universe, dict):
            raw_symbols = universe.get("symbols") or universe.get("data") or universe.get("items") or []
        else:
            raw_symbols = universe
        entries: List[Dict[str, str]] = []
        for item in raw_symbols:
            name = ""
            if isinstance(item, str):
                symbol = item
            elif isinstance(item, dict):
                symbol = item.get("symbol") or item.get("code") or ""
                ext = item.get("ext") or {}
                name = (
                    item.get("name")
                    or item.get("short_name")
                    or item.get("display_name")
                    or ext.get("name")
                    or ""
                )
            else:
                symbol = ""
            symbol = str(symbol).strip().upper()
            if symbol:
                entries.append({"symbol": symbol, "name": str(name).strip() if name else ""})
        return entries

    @staticmethod
    def _extract_universe_symbols(universe: Any) -> List[str]:
        return [entry["symbol"] for entry in TickFlowFetcher._extract_universe_entries(universe)]

    def get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        """Fetch main A-share indices via TickFlow quotes."""
        if region != "cn":
            return None

        client = self._get_client()
        if client is None:
            return None

        symbols = [symbol for symbol, _, _ in _CN_MAIN_INDEX_QUOTES]
        quotes: List[Dict[str, Any]] = []
        for offset in range(0, len(symbols), _MAX_SYMBOLS_PER_QUOTE_REQUEST):
            batch_symbols = symbols[offset : offset + _MAX_SYMBOLS_PER_QUOTE_REQUEST]
            batch_quotes = client.quotes.get(symbols=batch_symbols)
            if batch_quotes:
                quotes.extend(batch_quotes)
        if not quotes:
            logger.warning("[TickFlowFetcher] empty index quotes")
            return None

        quotes_by_symbol = {
            str(item.get("symbol", "")).upper(): item for item in quotes if item
        }
        results: List[Dict[str, Any]] = []

        for symbol, code, name in _CN_MAIN_INDEX_QUOTES:
            quote = quotes_by_symbol.get(symbol)
            if not quote:
                continue

            ext = quote.get("ext") or {}
            current = self._safe_float(quote.get("last_price")) or 0.0
            prev_close = self._safe_float(quote.get("prev_close")) or 0.0
            change = self._safe_float(ext.get("change_amount"))
            if change is None:
                change = current - prev_close if current or prev_close else 0.0
            amplitude = self._ratio_to_percent(ext.get("amplitude"))
            if amplitude is None and prev_close > 0:
                high = self._safe_float(quote.get("high")) or 0.0
                low = self._safe_float(quote.get("low")) or 0.0
                amplitude = (high - low) / prev_close * 100

            results.append(
                {
                    "code": code,
                    "name": name,
                    "current": current,
                    "change": change,
                    "change_pct": self._ratio_to_percent(ext.get("change_pct")) or 0.0,
                    "open": self._safe_float(quote.get("open")) or 0.0,
                    "high": self._safe_float(quote.get("high")) or 0.0,
                    "low": self._safe_float(quote.get("low")) or 0.0,
                    "prev_close": prev_close,
                    "volume": self._safe_float(quote.get("volume")) or 0.0,
                    "amount": self._safe_float(quote.get("amount")) or 0.0,
                    "amplitude": amplitude or 0.0,
                }
            )

        if len(results) != len(_CN_MAIN_INDEX_QUOTES):
            logger.warning(
                "[TickFlowFetcher] incomplete index quotes: %s/%s",
                len(results),
                len(_CN_MAIN_INDEX_QUOTES),
            )
            return None

        return results or None

    def get_market_stats(self) -> Optional[Dict[str, Any]]:
        """Calculate A-share market breadth from TickFlow universe quotes."""
        client = self._get_client()
        if client is None:
            return None

        if not self._capability_available("universe_quotes"):
            return None

        try:
            quotes = client.quotes.get(universes=[_CN_UNIVERSE_ID])
            self._mark_capability("universe_quotes", True)
        except Exception as exc:
            if self._is_universe_permission_error(exc):
                self._mark_capability("universe_quotes", False)
                logger.info(
                    "[TickFlowFetcher] universe quotes are not available; fallback to existing market stats sources"
                )
                return None
            raise
        if not quotes:
            logger.warning("[TickFlowFetcher] empty market stats quotes")
            return None

        stats = {
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "total_amount": 0.0,
        }
        valid_rows = 0

        for quote in quotes:
            if not quote:
                continue

            symbol = str(quote.get("symbol") or "").strip().upper()
            if not self._is_cn_equity_symbol(symbol):
                continue

            amount = self._safe_float(quote.get("amount"))
            if amount is not None and amount > 0:
                stats["total_amount"] += amount / 1e8

            pure_code = normalize_stock_code(symbol)
            last_price = self._safe_float(quote.get("last_price"))
            prev_close = self._safe_float(quote.get("prev_close"))

            if last_price is None or prev_close is None or amount is None or amount <= 0:
                continue

            name = self._extract_name(quote)
            ratio = self._get_limit_ratio(pure_code, name)
            limit_up = self._round_limit_price(prev_close, ratio)
            limit_down = math.floor(prev_close * (1 - ratio) * 100 + 0.5) / 100.0
            limit_up_tolerance = round(abs(prev_close * (1 + ratio) - limit_up), 10)
            limit_down_tolerance = round(
                abs(prev_close * (1 - ratio) - limit_down), 10
            )

            valid_rows += 1

            if abs(last_price - limit_up) <= limit_up_tolerance:
                stats["limit_up_count"] += 1
            if abs(last_price - limit_down) <= limit_down_tolerance:
                stats["limit_down_count"] += 1

            if last_price > prev_close:
                stats["up_count"] += 1
            elif last_price < prev_close:
                stats["down_count"] += 1
            else:
                stats["flat_count"] += 1

        if valid_rows == 0:
            logger.warning("[TickFlowFetcher] no valid A-share rows for market stats")
            return None

        return stats
