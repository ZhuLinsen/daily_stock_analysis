# -*- coding: utf-8 -*-
"""Futu OpenD market-data fetcher.

Read-only HK quote and daily-candlestick adapter for DSA.  Trading APIs are
intentionally not imported or exposed here.
"""

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from .base import BaseFetcher, STANDARD_COLUMNS
from .realtime_types import RealtimeSource, UnifiedRealtimeQuote, safe_float

logger = logging.getLogger(__name__)

# Futu get_market_snapshot returns update_time as a naive "yyyy-MM-dd HH:mm:ss"
# string; per the official docs HK and A-share quotes use Beijing time (UTC+8).
# DSA's _parse_realtime_timestamp treats naive values as UTC, so we attach the
# market-local offset here to keep provider_timestamp / stale_seconds correct.
_HK_UPDATE_TIME_OFFSET = timezone(timedelta(hours=8))


def _hk_provider_timestamp(value: Any) -> Optional[str]:
    """Normalize Futu snapshot update_time to an offset-aware ISO string."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_HK_UPDATE_TIME_OFFSET)
    return parsed.isoformat()


def _hk_symbol(stock_code: str) -> Optional[str]:
    code = (stock_code or "").strip().upper()
    if code.endswith(".HK"):
        digits = code[:-3]
    elif code.startswith("HK"):
        digits = code[2:]
    elif code.isdigit() and 1 <= len(code) <= 5:
        digits = code
    else:
        return None
    if not digits.isdigit() or not 1 <= len(digits) <= 5:
        return None
    return f"HK.{digits.zfill(5)}"


class FutuFetcher(BaseFetcher):
    """Futu OpenD adapter for DSA's existing provider contract."""

    name = "FutuFetcher"
    priority = int(os.getenv("FUTU_PRIORITY", "2"))
    allow_empty_daily_data = False

    def __init__(self) -> None:
        self._ctx = None
        self._ctx_lock = threading.Lock()
        self._available: Optional[bool] = None
        config = None
        try:
            from src.config import get_config
            config = get_config()
        except Exception:
            pass
        env_host = os.getenv("FUTU_OPEND_HOST")
        env_port = os.getenv("FUTU_OPEND_PORT")
        self._host = (getattr(config, "futu_opend_host", None) or env_host or "127.0.0.1").strip() or "127.0.0.1"
        try:
            self._port = int(getattr(config, "futu_opend_port", None) or env_port or 11111)
        except (TypeError, ValueError):
            self._port = 11111

    @staticmethod
    def has_configured_endpoint() -> bool:
        if (os.getenv("FUTU_OPEND_HOST") or "").strip():
            return True
        try:
            from src.config import get_config
            return bool((getattr(get_config(), "futu_opend_host", None) or "").strip())
        except Exception:
            return False

    def _is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import futu  # noqa: F401
            self._available = self.has_configured_endpoint()
        except ImportError:
            self._available = False
            logger.warning("[Futu] futu-api 未安装")
        return self._available

    def is_available_for_request(self, capability: str = "") -> bool:
        return self._is_available()

    def _get_ctx(self):
        if not self._is_available():
            return None
        if self._ctx is not None:
            return self._ctx
        with self._ctx_lock:
            if self._ctx is None:
                try:
                    from futu import OpenQuoteContext
                    self._ctx = OpenQuoteContext(host=self._host, port=self._port)
                    logger.info("[Futu] OpenQuoteContext 初始化成功: %s:%s", self._host, self._port)
                except Exception as exc:
                    self._available = False
                    logger.warning("[Futu] OpenQuoteContext 初始化失败: %s", exc)
        return self._ctx

    @staticmethod
    def _close_ctx(ctx: Any) -> None:
        try:
            ctx.close()
        except Exception:
            pass

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        symbol = _hk_symbol(stock_code)
        ctx = self._get_ctx()
        if not symbol or ctx is None:
            return None
        try:
            ret, data = ctx.get_market_snapshot([symbol])
            if ret == 0 and data is not None and not data.empty:
                return str(data.iloc[0].get("name") or "").strip() or None
        except Exception as exc:
            logger.debug("[Futu] stock name failed(%s): %s", symbol, exc)
        return None

    def get_stock_basicinfo(self, stock_code: str):
        """Return static security metadata for one HK symbol."""
        symbol = _hk_symbol(stock_code)
        ctx = self._get_ctx()
        if not symbol or ctx is None:
            return None
        try:
            import futu as ft
            ret, data = ctx.get_stock_basicinfo(ft.Market.HK, code_list=[symbol])
            return data if ret == ft.RET_OK else None
        except Exception as exc:
            logger.warning("[Futu] static info failed(%s): %s", symbol, exc)
            return None

    def request_trading_days(self, start_date: str, end_date: str):
        """Return HK trading days in the requested range."""
        ctx = self._get_ctx()
        if ctx is None:
            return []
        try:
            import futu as ft
            ret, data = ctx.request_trading_days(
                ft.TradeDateMarket.HK, start=start_date, end=end_date
            )
            return data if ret == ft.RET_OK else []
        except Exception as exc:
            logger.warning("[Futu] trading days failed: %s", exc)
            return []

    def get_trading_days(self, start_date: str, end_date: str):
        """Return normalized HK trading-day records."""
        rows = self.request_trading_days(start_date, end_date)
        return [
            {
                "date": row.get("time"),
                "trade_date_type": row.get("trade_date_type"),
            }
            for row in rows
            if isinstance(row, dict) and row.get("time")
        ]

    def get_company_profile(self, stock_code: str):
        symbol = _hk_symbol(stock_code)
        ctx = self._get_ctx()
        if not symbol or ctx is None:
            return None
        try:
            import futu as ft
            ret, data = ctx.get_company_profile(symbol)
            return data if ret == ft.RET_OK else None
        except Exception as exc:
            logger.warning("[Futu] company profile failed(%s): %s", symbol, exc)
            return None

    def get_financials_statements(self, stock_code: str, statement_type: Optional[int] = None, num: int = 8):
        symbol = _hk_symbol(stock_code)
        ctx = self._get_ctx()
        if not symbol or ctx is None:
            return None
        try:
            import futu as ft
            ret, data = ctx.get_financials_statements(
                symbol, statement_type=statement_type, num=num
            )
            return data if ret == ft.RET_OK else None
        except Exception as exc:
            logger.warning("[Futu] financial statements failed(%s): %s", symbol, exc)
            return None

    def get_corporate_actions_dividends(self, stock_code: str):
        symbol = _hk_symbol(stock_code)
        ctx = self._get_ctx()
        if not symbol or ctx is None:
            return None
        try:
            import futu as ft
            ret, data = ctx.get_corporate_actions_dividends(symbol)
            return data if ret == ft.RET_OK else None
        except Exception as exc:
            logger.warning("[Futu] dividends failed(%s): %s", symbol, exc)
            return None

    def get_corporate_actions_stock_splits(self, stock_code: str, num: int = 50):
        symbol = _hk_symbol(stock_code)
        ctx = self._get_ctx()
        if not symbol or ctx is None:
            return None
        try:
            import futu as ft
            ret, data = ctx.get_corporate_actions_stock_splits(symbol, num=num)
            return data if ret == ft.RET_OK else None
        except Exception as exc:
            logger.warning("[Futu] stock splits failed(%s): %s", symbol, exc)
            return None

    def get_capital_flow(self, stock_code: str, **kwargs):
        symbol = _hk_symbol(stock_code)
        ctx = self._get_ctx()
        if not symbol or ctx is None:
            return None
        try:
            import futu as ft
            ret, data = ctx.get_capital_flow(symbol, **kwargs)
            return data if ret == ft.RET_OK else None
        except Exception as exc:
            logger.warning("[Futu] capital flow failed(%s): %s", symbol, exc)
            return None

    def get_owner_plate(self, stock_codes):
        symbols = [_hk_symbol(code) for code in stock_codes]
        symbols = [symbol for symbol in symbols if symbol]
        ctx = self._get_ctx()
        if not symbols or ctx is None:
            return None
        try:
            import futu as ft
            ret, data = ctx.get_owner_plate(symbols)
            return data if ret == ft.RET_OK else None
        except Exception as exc:
            logger.warning("[Futu] owner plate failed: %s", exc)
            return None

    def close(self) -> None:
        if self._ctx is not None:
            self._close_ctx(self._ctx)
            self._ctx = None

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        symbol = _hk_symbol(stock_code)
        ctx = self._get_ctx()
        if not symbol or ctx is None:
            return None
        try:
            ret, rows = ctx.get_market_snapshot([symbol])
            if ret != 0 or rows is None or rows.empty:
                return None
            q = rows.iloc[0]
            price = safe_float(q.get("last_price"))
            if price is None or price <= 0:
                return None
            prev = safe_float(q.get("prev_close_price"))
            change_pct = safe_float(q.get("change_rate"))
            volume = int(q.get("volume") or 0)
            turnover = safe_float(q.get("turnover"))
            turnover_rate = safe_float(q.get("turnover_rate"))
            return UnifiedRealtimeQuote(
                code=stock_code,
                name=str(q.get("name") or ""),
                source=RealtimeSource.FUTU,
                price=price,
                change_pct=change_pct,
                change_amount=round(price - prev, 4) if prev else None,
                volume=volume or None,
                amount=turnover,
                turnover_rate=turnover_rate,
                volume_ratio=safe_float(q.get("volume_ratio")),
                amplitude=safe_float(q.get("amplitude")),
                open_price=safe_float(q.get("open_price")),
                high=safe_float(q.get("high_price")),
                low=safe_float(q.get("low_price")),
                pre_close=prev,
                pe_ratio=safe_float(q.get("pe_ttm_ratio")) or safe_float(q.get("pe_ratio")),
                pb_ratio=safe_float(q.get("pb_ratio")),
                total_mv=safe_float(q.get("total_market_val")),
                circ_mv=safe_float(q.get("circular_market_val")),
                provider_timestamp=_hk_provider_timestamp(q.get("update_time")),
            )
        except Exception as exc:
            logger.warning("[Futu] realtime quote failed(%s): %s", symbol, exc)
            return None

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = _hk_symbol(stock_code)
        ctx = self._get_ctx()
        if not symbol or ctx is None:
            return pd.DataFrame()
        try:
            import futu as ft
            ret, data, _ = ctx.request_history_kline(
                symbol,
                start=start_date,
                end=end_date,
                ktype=ft.KLType.K_DAY,
                autype=ft.AuType.NONE,
                max_count=1000,
            )
            if ret != ft.RET_OK or data is None or data.empty:
                return pd.DataFrame()
            return data.rename(columns={"time_key": "date", "turnover": "amount"})
        except Exception as exc:
            logger.warning("[Futu] daily data failed(%s): %s", symbol, exc)
            return pd.DataFrame()

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)
        out = df.copy()
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
        rename = {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}
        out = out.rename(columns=rename)
        if "pct_chg" not in out.columns:
            out["pct_chg"] = out["close"].pct_change() * 100
        for col in STANDARD_COLUMNS:
            if col not in out.columns:
                out[col] = None
        return out[STANDARD_COLUMNS]