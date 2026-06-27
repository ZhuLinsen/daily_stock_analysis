# -*- coding: utf-8 -*-
"""EastMoney-oriented provider helpers for the stock workbench MVP.

This module intentionally wraps existing daily_stock_analysis data routes first
and only reaches into AkShare EastMoney endpoints for the incremental workbench
data that is not exposed by the generic manager. All public methods are
fail-open and return a uniform envelope containing source/stale/error.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import date, datetime, timedelta
from threading import Lock
from typing import Any, Dict, List, Optional

import pandas as pd

from data_provider.base import DataFetcherManager, normalize_stock_code, _is_etf_code
from src.data.stock_index_loader import get_index_stock_name
from src.data.stock_mapping import STOCK_NAME_MAP, is_meaningful_stock_name
from src.repositories.stock_repo import StockRepository

logger = logging.getLogger(__name__)

_ETF_REALTIME_CACHE: Dict[str, Any] = {"data": None, "timestamp": 0.0, "ttl": 30}
_ETF_REALTIME_CACHE_LOCK = Lock()
_ETF_REALTIME_TIMEOUT_SECONDS = 3.0

_ETF_NAME_MAP = {
    "589020": "科创半导体设备ETF鹏华",
    "589090": "科创AIETF鹏华",
    "159516": "半导体设备ETF国泰",
    "159558": "半导体设备ETF易方达",
    "159310": "芯片ETF天弘",
    "159997": "电子ETF天弘",
    "159813": "半导体ETF鹏华",
    "159538": "信创ETF富国",
    "159995": "芯片ETF华夏",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace("%", "").replace(",", "")
            if not value or value in {"-", "--"}:
                return None
        parsed = float(value)
        return parsed if parsed == parsed else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    parsed = _safe_float(value)
    return int(parsed) if parsed is not None else None


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def _empty_payload(source: str, *, error: Optional[str] = None, stale: bool = False, data: Any = None) -> Dict[str, Any]:
    return {
        "source": source,
        "stale": stale,
        "error": error,
        "updated_at": _now_iso(),
        "data": data,
    }


def _local_stock_name(code: str) -> str:
    etf_name = _ETF_NAME_MAP.get(code)
    if etf_name:
        return etf_name
    static_name = STOCK_NAME_MAP.get(code)
    if is_meaningful_stock_name(static_name, code):
        return str(static_name)
    index_name = get_index_stock_name(code)
    if is_meaningful_stock_name(index_name, code):
        return str(index_name)
    return ""


class EastMoneyProvider:
    """Thin EastMoney provider with stable workbench response envelopes."""

    source = "eastmoney"

    def __init__(self, manager: Optional[DataFetcherManager] = None, stock_repo: Optional[StockRepository] = None):
        self.manager = manager or DataFetcherManager()
        self.stock_repo = stock_repo or StockRepository()

    def get_realtime_quote(self, symbol: str) -> Dict[str, Any]:
        """Return a realtime quote, falling back to the latest SQLite daily bar."""
        code = normalize_stock_code(symbol)
        try:
            quote = self.manager.get_realtime_quote(code, log_final_failure=False)
            if quote is not None:
                return _empty_payload(
                    self._quote_source(quote),
                    stale=bool(getattr(quote, "is_stale", False)),
                    data={
                        "code": getattr(quote, "code", code) or code,
                        "name": getattr(quote, "name", "") or _local_stock_name(code),
                        "price": getattr(quote, "price", None),
                        "change_pct": getattr(quote, "change_pct", None),
                        "change_amount": getattr(quote, "change_amount", None),
                        "volume": getattr(quote, "volume", None),
                        "amount": getattr(quote, "amount", None),
                        "volume_ratio": getattr(quote, "volume_ratio", None),
                        "turnover_rate": getattr(quote, "turnover_rate", None),
                        "amplitude": getattr(quote, "amplitude", None),
                        "open": getattr(quote, "open_price", None),
                        "high": getattr(quote, "high", None),
                        "low": getattr(quote, "low", None),
                        "pre_close": getattr(quote, "pre_close", None),
                        "pe_ratio": getattr(quote, "pe_ratio", None),
                        "pb_ratio": getattr(quote, "pb_ratio", None),
                        "total_mv": getattr(quote, "total_mv", None),
                        "circ_mv": getattr(quote, "circ_mv", None),
                        "provider_timestamp": getattr(quote, "provider_timestamp", None),
                        "fetched_at": getattr(quote, "fetched_at", None),
                    },
                )
            return self._fallback_quote_from_sqlite(code, error="realtime_quote_unavailable")
        except Exception as exc:
            logger.warning("EastMoney realtime quote failed for %s: %s", code, exc, exc_info=True)
            return self._fallback_quote_from_sqlite(code, error=str(exc) or type(exc).__name__)

    def get_cached_quote(self, symbol: str, *, error: str = "remote_quote_unavailable") -> Dict[str, Any]:
        """Return only the latest local quote-like daily bar without remote calls."""
        code = normalize_stock_code(symbol)
        return self._fallback_quote_from_sqlite(code, error=error)

    def get_etf_quote(self, symbol: str, *, allow_remote: bool = True) -> Dict[str, Any]:
        """Return an ETF quote payload with a cached realtime path and daily fallback."""
        code = normalize_stock_code(symbol)
        if not _is_etf_code(code):
            return _empty_payload(self.source, error="not_etf_code", stale=True, data=None)

        if allow_remote:
            realtime = self._get_etf_realtime_quote(code)
            if self._has_quote_data(realtime):
                return realtime

        cached = self._fallback_quote_from_sqlite(code, error="etf_quote_cache_unavailable")
        if self._has_quote_data(cached):
            return self._mark_etf_quote(cached, source="sqlite.stock_daily.etf", error=None)

        if allow_remote:
            kline = self.get_etf_daily_kline(code, allow_remote=True)
            quote = self._quote_from_kline_payload(code, kline)
            if self._has_quote_data(quote):
                return quote

        return self._mark_etf_quote(cached, source="sqlite.stock_daily.etf", error="etf_quote_unavailable")

    def get_etf_daily_kline(self, symbol: str, period: str = "daily", *, allow_remote: bool = True) -> Dict[str, Any]:
        """Return ETF daily K-line bars through the existing ETF-capable data manager."""
        code = normalize_stock_code(symbol)
        if not _is_etf_code(code):
            return _empty_payload(self.source, error="not_etf_code", stale=True, data=[])
        return self.get_daily_kline(code, period=period, allow_remote=allow_remote)

    def _get_etf_realtime_quote(self, code: str) -> Dict[str, Any]:
        try:
            df = self._get_etf_realtime_frame()
            if df is None or df.empty:
                return _empty_payload("eastmoney.efinance.etf", error="empty_etf_realtime", stale=True, data=None)
            code_col = "股票代码" if "股票代码" in df.columns else "code"
            code_series = df[code_col].astype(str).str.zfill(6)
            row = df[code_series == code]
            if row.empty:
                return _empty_payload("eastmoney.efinance.etf", error="etf_realtime_not_found", stale=True, data=None)
            return _empty_payload("eastmoney.efinance.etf", data=self._normalize_etf_realtime_row(code, row.iloc[0]))
        except Exception as exc:
            logger.warning("ETF realtime quote failed for %s: %s", code, exc)
            return _empty_payload("eastmoney.efinance.etf", error=str(exc) or type(exc).__name__, stale=True, data=None)

    @staticmethod
    def _get_etf_realtime_frame() -> Optional[pd.DataFrame]:
        now = time.time()
        cached = _ETF_REALTIME_CACHE.get("data")
        if cached is not None and now - float(_ETF_REALTIME_CACHE.get("timestamp") or 0) < float(_ETF_REALTIME_CACHE.get("ttl") or 30):
            return cached

        with _ETF_REALTIME_CACHE_LOCK:
            now = time.time()
            cached = _ETF_REALTIME_CACHE.get("data")
            if cached is not None and now - float(_ETF_REALTIME_CACHE.get("timestamp") or 0) < float(_ETF_REALTIME_CACHE.get("ttl") or 30):
                return cached
            try:
                import efinance as ef

                executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="workbench-etf-realtime")
                future = executor.submit(ef.stock.get_realtime_quotes, ["ETF"])
                try:
                    df = future.result(timeout=_ETF_REALTIME_TIMEOUT_SECONDS)
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
            except FuturesTimeoutError:
                _ETF_REALTIME_CACHE["data"] = cached
                _ETF_REALTIME_CACHE["timestamp"] = time.time()
                logger.warning("ETF realtime quote timeout after %.0fs", _ETF_REALTIME_TIMEOUT_SECONDS)
                return cached if cached is not None else None
            except Exception as exc:
                _ETF_REALTIME_CACHE["data"] = cached
                _ETF_REALTIME_CACHE["timestamp"] = time.time()
                logger.warning("ETF realtime quote fetch failed: %s", exc)
                return cached if cached is not None else None
            if df is not None and not getattr(df, "empty", True):
                _ETF_REALTIME_CACHE["data"] = df
                _ETF_REALTIME_CACHE["timestamp"] = time.time()
                return df
            return cached if cached is not None else df

    @staticmethod
    def _normalize_etf_realtime_row(code: str, row: Any) -> Dict[str, Any]:
        def pick(*names: str) -> Any:
            for name in names:
                if name in row:
                    value = row.get(name)
                    if value is not None and not (isinstance(value, float) and value != value):
                        return value
            return None

        return {
            "code": code,
            "name": _text(pick("股票名称", "名称", "name")) or _local_stock_name(code) or code,
            "asset_type": "ETF",
            "quote_type": "realtime",
            "price": _safe_float(pick("最新价", "price")),
            "change_pct": _safe_float(pick("涨跌幅", "pct_chg", "change_pct")),
            "change_amount": _safe_float(pick("涨跌额", "change", "change_amount")),
            "volume": _safe_int(pick("成交量", "volume")),
            "amount": _safe_float(pick("成交额", "amount")),
            "volume_ratio": _safe_float(pick("量比", "volume_ratio")),
            "turnover_rate": _safe_float(pick("换手率", "turnover_rate")),
            "amplitude": _safe_float(pick("振幅", "amplitude")),
            "open": _safe_float(pick("今开", "开盘", "open")),
            "high": _safe_float(pick("最高", "high")),
            "low": _safe_float(pick("最低", "low")),
            "pre_close": _safe_float(pick("昨收", "pre_close")),
            "pe_ratio": _safe_float(pick("动态市盈率", "市盈率", "pe_ratio")),
            "total_mv": _safe_float(pick("总市值", "total_mv")),
            "circ_mv": _safe_float(pick("流通市值", "circ_mv")),
            "fetched_at": _now_iso(),
        }

    def get_daily_kline(self, symbol: str, period: str = "daily", *, allow_remote: bool = True) -> Dict[str, Any]:
        """Return daily K-line bars with MA/MACD/KDJ/RSI/BOLL fields."""
        code = normalize_stock_code(symbol)
        if period != "daily":
            return _empty_payload(self.source, error=f"unsupported period: {period}", stale=True, data=[])
        if not allow_remote:
            return self._fallback_kline_from_sqlite(code, error="remote_fetch_skipped_for_fast_view")
        try:
            df, provider = self.manager.get_daily_data(code, days=160)
            if df is not None and not df.empty:
                try:
                    self.stock_repo.save_dataframe(df, code, data_source=provider)
                except Exception as cache_exc:
                    logger.debug("Failed to cache kline for %s: %s", code, cache_exc)
                enriched = self._enrich_indicators(df)
                return _empty_payload(provider or self.source, stale=False, data=self._df_to_records(enriched))
            return self._fallback_kline_from_sqlite(code, error="daily_kline_empty")
        except Exception as exc:
            logger.warning("EastMoney daily kline failed for %s: %s", code, exc, exc_info=True)
            return self._fallback_kline_from_sqlite(code, error=str(exc) or type(exc).__name__)

    @staticmethod
    def _has_quote_data(payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        data = payload.get("data")
        return isinstance(data, dict) and data.get("price") is not None

    @staticmethod
    def _mark_etf_quote(payload: Dict[str, Any], *, source: str, error: Optional[str]) -> Dict[str, Any]:
        data = dict(payload.get("data") or {}) if isinstance(payload.get("data"), dict) else None
        if data is not None:
            data["asset_type"] = "ETF"
            data["quote_type"] = "daily_close"
        return {**payload, "source": source, "stale": True, "error": error, "data": data}

    def _quote_from_kline_payload(self, code: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        bars = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(bars, list) or not bars:
            return _empty_payload(
                payload.get("source", "eastmoney.etf_daily") if isinstance(payload, dict) else "eastmoney.etf_daily",
                error=(payload.get("error") if isinstance(payload, dict) else None) or "empty_etf_kline",
                stale=True,
                data=None,
            )
        latest = bars[-1]
        previous = bars[-2] if len(bars) > 1 else {}
        close = _safe_float(latest.get("close"))
        prev_close = _safe_float(previous.get("close"))
        change_pct = _safe_float(latest.get("pct_chg"))
        change_amount = None
        if close is not None and prev_close not in (None, 0):
            change_amount = close - prev_close
            if change_pct is None:
                change_pct = change_amount / prev_close * 100
        source = str(payload.get("source") or "eastmoney.etf_daily") if isinstance(payload, dict) else "eastmoney.etf_daily"
        return _empty_payload(
            f"{source}.etf_quote",
            stale=True,
            data={
                "code": code,
                "name": _local_stock_name(code) or code,
                "asset_type": "ETF",
                "quote_type": "daily_close",
                "price": close,
                "change_pct": change_pct,
                "change_amount": change_amount,
                "volume": _safe_float(latest.get("volume")),
                "amount": _safe_float(latest.get("amount")),
                "turnover_rate": _safe_float(latest.get("turnover_rate")),
                "open": _safe_float(latest.get("open")),
                "high": _safe_float(latest.get("high")),
                "low": _safe_float(latest.get("low")),
                "pre_close": prev_close,
                "provider_timestamp": _text(latest.get("date")),
                "fetched_at": _now_iso(),
            },
        )

    def get_money_flow(self, symbol: str, *, allow_remote: bool = True) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        if not allow_remote:
            return _empty_payload(self.source, error="remote_fetch_skipped_for_fast_view", stale=True, data={})
        try:
            context = self.manager.get_capital_flow_context(code)
            data = context.get("data") if isinstance(context, dict) else {}
            status = context.get("status") if isinstance(context, dict) else "failed"
            errors = context.get("errors") if isinstance(context, dict) else []
            return _empty_payload(
                self.source,
                stale=status not in {"ok", "partial"},
                error="; ".join(str(e) for e in errors if e) or (None if status in {"ok", "partial"} else status),
                data=data or {},
            )
        except Exception as exc:
            logger.warning("EastMoney money flow failed for %s: %s", code, exc, exc_info=True)
            return _empty_payload(self.source, error=str(exc) or type(exc).__name__, stale=True, data={})

    def get_lhb(self, symbol: str) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        try:
            context = self.manager.get_dragon_tiger_context(code)
            data = context.get("data") if isinstance(context, dict) else {}
            status = context.get("status") if isinstance(context, dict) else "failed"
            errors = context.get("errors") if isinstance(context, dict) else []
            return _empty_payload(
                self.source,
                stale=status not in {"ok", "partial"},
                error="; ".join(str(e) for e in errors if e) or (None if status in {"ok", "partial"} else status),
                data=data or {},
            )
        except Exception as exc:
            logger.warning("EastMoney LHB failed for %s: %s", code, exc, exc_info=True)
            return _empty_payload(self.source, error=str(exc) or type(exc).__name__, stale=True, data={})

    def get_limit_up_pool(self) -> Dict[str, Any]:
        try:
            data = self.manager.get_limit_up_pool(n=30)
            return _empty_payload(self.source, stale=not bool(data), error=None if data else "empty_limit_up_pool", data=data or [])
        except Exception as exc:
            logger.warning("EastMoney limit-up pool failed: %s", exc, exc_info=True)
            return _empty_payload(self.source, error=str(exc) or type(exc).__name__, stale=True, data=[])

    def get_stock_news(self, symbol: str) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        try:
            import akshare as ak

            rows: List[Dict[str, Any]] = []
            calls = (
                ("stock_news_em", {"symbol": code}),
                ("stock_news_em", {"stock": code}),
            )
            last_error = ""
            for func_name, kwargs in calls:
                func = getattr(ak, func_name, None)
                if not callable(func):
                    continue
                try:
                    df = func(**kwargs)
                    rows = self._normalize_news_frame(df)
                    if rows:
                        return _empty_payload(f"{self.source}.{func_name}", data=rows[:20])
                    last_error = "empty news"
                except Exception as call_exc:
                    last_error = str(call_exc) or type(call_exc).__name__
                    logger.debug("%s(%s) failed: %s", func_name, kwargs, call_exc)
            return _empty_payload(self.source, error=last_error or "news_unavailable", stale=True, data=[])
        except Exception as exc:
            logger.warning("EastMoney stock news failed for %s: %s", code, exc, exc_info=True)
            return _empty_payload(self.source, error=str(exc) or type(exc).__name__, stale=True, data=[])

    @staticmethod
    def _quote_source(quote: Any) -> str:
        source = getattr(quote, "source", None)
        if hasattr(source, "value"):
            return str(source.value)
        return str(source or "realtime_quote")

    def _fallback_quote_from_sqlite(self, code: str, *, error: str) -> Dict[str, Any]:
        try:
            latest = self.stock_repo.get_latest(code, days=2)
            if not latest:
                return _empty_payload("sqlite.stock_daily", error=error, stale=True, data=None)
            current = latest[0]
            previous = latest[1] if len(latest) > 1 else None
            prev_close = getattr(previous, "close", None) if previous is not None else None
            close = getattr(current, "close", None)
            change_pct = getattr(current, "pct_chg", None)
            change_amount = None
            if close is not None and prev_close not in (None, 0):
                change_amount = close - prev_close
                if change_pct is None:
                    change_pct = change_amount / prev_close * 100
            return _empty_payload(
                "sqlite.stock_daily",
                error=error,
                stale=True,
                data={
                    "code": code,
                    "name": _local_stock_name(code),
                    "price": close,
                    "change_pct": change_pct,
                    "change_amount": change_amount,
                    "volume": getattr(current, "volume", None),
                    "amount": getattr(current, "amount", None),
                    "volume_ratio": getattr(current, "volume_ratio", None),
                    "turnover_rate": None,
                    "open": getattr(current, "open", None),
                    "high": getattr(current, "high", None),
                    "low": getattr(current, "low", None),
                    "pre_close": prev_close,
                    "provider_timestamp": getattr(current, "date", None).isoformat() if getattr(current, "date", None) else None,
                },
            )
        except Exception as exc:
            logger.debug("SQLite quote fallback failed for %s: %s", code, exc)
            return _empty_payload("sqlite.stock_daily", error=error, stale=True, data=None)

    def _fallback_kline_from_sqlite(self, code: str, *, error: str) -> Dict[str, Any]:
        try:
            end = date.today()
            start = end - timedelta(days=320)
            bars = self.stock_repo.get_range(code, start, end)
            if not bars:
                return _empty_payload("sqlite.stock_daily", error=error, stale=True, data=[])
            df = pd.DataFrame([bar.to_dict() for bar in bars])
            enriched = self._enrich_indicators(df)
            return _empty_payload("sqlite.stock_daily", error=error, stale=True, data=self._df_to_records(enriched))
        except Exception as exc:
            logger.debug("SQLite kline fallback failed for %s: %s", code, exc)
            return _empty_payload("sqlite.stock_daily", error=error, stale=True, data=[])

    def enrich_kline_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Add common indicators to provider-normalized K-line records."""
        try:
            if not records:
                return []
            df = pd.DataFrame(records)
            enriched = self._enrich_indicators(df)
            return self._df_to_records(enriched)
        except Exception as exc:
            logger.debug("Failed to enrich kline records: %s", exc)
            return records

    @staticmethod
    def _enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
        work = df.copy()
        if "date" in work.columns:
            work["date"] = pd.to_datetime(work["date"], errors="coerce")
        for col in ("open", "high", "low", "close", "volume", "amount", "pct_chg"):
            if col in work.columns:
                work[col] = pd.to_numeric(work[col], errors="coerce")
        work = work.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)

        for window in (5, 10, 20, 60):
            work[f"ma{window}"] = work["close"].rolling(window=window, min_periods=1).mean()

        ema12 = work["close"].ewm(span=12, adjust=False).mean()
        ema26 = work["close"].ewm(span=26, adjust=False).mean()
        work["macd_dif"] = ema12 - ema26
        work["macd_dea"] = work["macd_dif"].ewm(span=9, adjust=False).mean()
        work["macd"] = (work["macd_dif"] - work["macd_dea"]) * 2

        low_n = work["low"].rolling(window=9, min_periods=1).min()
        high_n = work["high"].rolling(window=9, min_periods=1).max()
        rsv = (work["close"] - low_n) / (high_n - low_n).replace(0, pd.NA) * 100
        work["kdj_k"] = rsv.ewm(com=2, adjust=False).mean().fillna(50)
        work["kdj_d"] = work["kdj_k"].ewm(com=2, adjust=False).mean().fillna(50)
        work["kdj_j"] = 3 * work["kdj_k"] - 2 * work["kdj_d"]

        delta = work["close"].diff()
        gain = delta.clip(lower=0).rolling(window=14, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14, min_periods=1).mean()
        rs = gain / loss.replace(0, pd.NA)
        work["rsi"] = (100 - (100 / (1 + rs))).fillna(50)

        mid = work["close"].rolling(window=20, min_periods=1).mean()
        std = work["close"].rolling(window=20, min_periods=1).std().fillna(0)
        work["boll_mid"] = mid
        work["boll_upper"] = mid + 2 * std
        work["boll_lower"] = mid - 2 * std

        numeric_cols = work.select_dtypes(include="number").columns
        work.loc[:, numeric_cols] = work.loc[:, numeric_cols].round(4)
        return work

    @staticmethod
    def _df_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for row in df.to_dict(orient="records"):
            item: Dict[str, Any] = {}
            for key, value in row.items():
                if key == "date":
                    item[key] = value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else _text(value)
                elif isinstance(value, float) and value != value:
                    item[key] = None
                else:
                    item[key] = value
            records.append(item)
        return records

    @staticmethod
    def _normalize_news_frame(df: Any) -> List[Dict[str, Any]]:
        if df is None or getattr(df, "empty", True):
            return []
        rows: List[Dict[str, Any]] = []
        for _, row in df.head(30).iterrows():
            title = _text(row.get("新闻标题") or row.get("标题") or row.get("title"))
            if not title:
                continue
            rows.append({
                "title": title,
                "url": _text(row.get("新闻链接") or row.get("链接") or row.get("url")),
                "source": _text(row.get("文章来源") or row.get("来源") or row.get("source") or "东方财富"),
                "published_at": _text(row.get("发布时间") or row.get("时间") or row.get("datetime")),
            })
        return rows
