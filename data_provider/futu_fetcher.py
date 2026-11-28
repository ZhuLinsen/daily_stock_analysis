# -*- coding: utf-8 -*-
"""Futu OpenD market-data fetcher.

Read-only HK / A-share / US quote and daily-candlestick adapter for DSA.
Trading APIs are intentionally not imported or exposed here.
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from .base import BaseFetcher, STANDARD_COLUMNS
from .realtime_types import RealtimeSource, UnifiedRealtimeQuote, safe_float

logger = logging.getLogger(__name__)

# Futu get_market_snapshot returns update_time as a naive "yyyy-MM-dd HH:mm:ss"
# string; per the official docs HK and A-share quotes use Beijing time (UTC+8),
# while US quotes use the exchange's local time (America/New_York, DST-aware).
# DSA's _parse_realtime_timestamp treats naive values as UTC, so we attach the
# market-local offset here to keep provider_timestamp / stale_seconds correct.
_CN_HK_UPDATE_TIME_OFFSET = timezone(timedelta(hours=8))
_US_UPDATE_TIME_ZONE = "America/New_York"

_SH_CN_PREFIXES = ("600", "601", "603", "605", "688", "689")
_SZ_CN_PREFIXES = ("000", "001", "002", "003", "200", "300", "301")

# futu-api's synchronous OpenQuoteContext constructor retries forever while
# OpenD is unreachable, so connect asynchronously and wait a bounded time for
# the protocol handshake (status READY), then skip Futu for a cooldown window.
_CONNECT_TIMEOUT_SECONDS = 5.0
_CONNECT_POLL_SECONDS = 0.05
_CONNECT_RETRY_COOLDOWN_SECONDS = 300.0


def _market_tz(market: str):
    if market == "us":
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(_US_UPDATE_TIME_ZONE)
        except Exception:  # noqa: BLE001 - fall back to fixed DST-agnostic offset
            return timezone(timedelta(hours=-4))
    return _CN_HK_UPDATE_TIME_OFFSET


def _provider_timestamp(value: Any, market: str = "hk") -> Optional[str]:
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
        parsed = parsed.replace(tzinfo=_market_tz(market))
    return parsed.isoformat()


# Backward-compatible alias: existing callers/tests used the HK-only name
# before multi-market support landed.
_hk_provider_timestamp = _provider_timestamp


def _hk_symbol(stock_code: str) -> Optional[str]:
    code = (stock_code or "").strip().upper()
    if code.endswith(".HK"):
        digits = code[:-3]
    elif code.startswith("HK."):
        digits = code[3:]
    elif code.startswith("HK"):
        digits = code[2:]
    elif code.isdigit() and 1 <= len(code) <= 5:
        digits = code
    else:
        return None
    if not digits.isdigit() or not 1 <= len(digits) <= 5:
        return None
    return f"HK.{digits.zfill(5)}"


def _futu_market(stock_code: str) -> Optional[str]:
    """Return 'hk' / 'cn' / 'us' for a DSA stock code, or None if unsupported."""
    code = (stock_code or "").strip().upper()
    if not code:
        return None
    if code.endswith(".HK") or code.startswith("HK") or (code.isdigit() and 1 <= len(code) <= 5):
        return "hk"
    if code.endswith(".US") or code.startswith("US."):
        return "us"
    if code.endswith((".SH", ".SZ", ".SS")) or code.startswith(("SH.", "SZ.")):
        return "cn"
    if code.startswith(("SH", "SZ")) and code[2:].isdigit():
        return "cn"
    if code.isdigit() and len(code) == 6:
        return "cn"
    if _is_letter_ticker(code):
        return "us"
    return None


def _is_letter_ticker(code: str) -> bool:
    if not 1 <= len(code) <= 10:
        return False
    core = code
    for suffix in (".US",):
        if core.endswith(suffix):
            core = core[: -len(suffix)]
    if core.startswith("US."):
        core = core[3:]
    if not core:
        return False
    return all(ch.isalpha() or ch in {".", "-"} for ch in core) and any(ch.isalpha() for ch in core)


def _cn_symbol(stock_code: str) -> Optional[str]:
    """Map an A-share code to Futu form, accepting every alias DSA normalizes.

    Supported inputs: SH.600519 / SZ.300750, SH600519 / SZ300750, 600519.SH /
    600519.SS / 300750.SZ, and bare 6-digit codes.
    """
    code = (stock_code or "").strip().upper()
    exchange = None
    digits = ""
    if code.startswith(("SH.", "SZ.")):
        exchange, digits = code[:2], code[3:]
    elif code.startswith(("SH", "SZ")) and code[2:].isdigit():
        exchange, digits = code[:2], code[2:]
    elif code.endswith((".SH", ".SS", ".SZ")):
        suffix = code.rsplit(".", 1)[1]
        exchange = "SH" if suffix in {"SH", "SS"} else "SZ"
        digits = code[: -(len(suffix) + 1)]
    else:
        digits = code
    if not digits.isdigit() or len(digits) != 6:
        return None
    if exchange is None:
        if digits.startswith(_SH_CN_PREFIXES):
            exchange = "SH"
        elif digits.startswith(_SZ_CN_PREFIXES):
            exchange = "SZ"
        else:
            return None
    return f"{exchange}.{digits}"


def _us_symbol(stock_code: str) -> Optional[str]:
    code = (stock_code or "").strip().upper()
    if not code:
        return None
    if code.startswith("US."):
        code = code[3:]
    if code.endswith(".US"):
        code = code[:-3]
    if not _is_letter_ticker(code):
        return None
    return f"US.{code}"


def _futu_symbol(stock_code: str) -> Optional[str]:
    """Map a DSA code to Futu's symbol form: HK.09618 / SH.600519 / SZ.300750 / US.AAPL."""
    market = _futu_market(stock_code)
    if market == "hk":
        return _hk_symbol(stock_code)
    if market == "cn":
        return _cn_symbol(stock_code)
    if market == "us":
        return _us_symbol(stock_code)
    return None


class FutuFetcher(BaseFetcher):
    """Futu OpenD adapter for DSA's existing provider contract."""

    name = "FutuFetcher"
    priority = int(os.getenv("FUTU_PRIORITY", "2"))
    allow_empty_daily_data = False

    def __init__(self) -> None:
        self._ctx = None
        self._ctx_lock = threading.Lock()
        self._available: Optional[bool] = None
        self._retry_after = 0.0
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
            logger.warning("[Futu] futu-api is not installed")
        return self._available

    def _in_connect_cooldown(self) -> bool:
        return self._ctx is None and time.monotonic() < self._retry_after

    def is_available_for_request(self, capability: str = "") -> bool:
        return self._is_available() and not self._in_connect_cooldown()

    def _get_ctx(self):
        if not self._is_available():
            return None
        if self._ctx is not None:
            return self._ctx
        if self._in_connect_cooldown():
            return None
        with self._ctx_lock:
            if self._ctx is None and not self._in_connect_cooldown():
                self._ctx = self._connect()
        return self._ctx

    def _connect(self):
        """Open a quote context, or return None within a bounded time."""
        ctx = None
        try:
            from futu import ContextStatus, OpenQuoteContext
            ctx = OpenQuoteContext(host=self._host, port=self._port, is_async_connect=True)
            deadline = time.monotonic() + _CONNECT_TIMEOUT_SECONDS
            while ctx.status != ContextStatus.READY:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"OpenD 未在 {_CONNECT_TIMEOUT_SECONDS:g}s 内就绪 (status={ctx.status})"
                    )
                time.sleep(_CONNECT_POLL_SECONDS)
            logger.info("[Futu] OpenQuoteContext initialized successfully: %s:%s", self._host, self._port)
            return ctx
        except Exception as exc:
            # close() turns off the SDK's background auto-reconnect.
            if ctx is not None:
                self._close_ctx(ctx)
            self._retry_after = time.monotonic() + _CONNECT_RETRY_COOLDOWN_SECONDS
            logger.warning(
                "[Futu] Failed to connect to OpenD %s:%s; skipping Futu for %d min "
                "and falling back to other data sources: %s",
                self._host,
                self._port,
                _CONNECT_RETRY_COOLDOWN_SECONDS // 60,
                exc,
            )
            return None

    @staticmethod
    def _close_ctx(ctx: Any) -> None:
        try:
            ctx.close()
        except Exception:
            pass

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        symbol = _futu_symbol(stock_code)
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
        """Return static security metadata for one HK / A-share / US symbol."""
        symbol = _futu_symbol(stock_code)
        ctx = self._get_ctx()
        if not symbol or ctx is None:
            return None
        try:
            import futu as ft
            market = _futu_market(stock_code)
            ft_market = ft.Market.HK
            if market == "us":
                ft_market = ft.Market.US
            elif market == "cn":
                ft_market = ft.Market.SH if symbol.startswith("SH.") else ft.Market.SZ
            ret, data = ctx.get_stock_basicinfo(ft_market, code_list=[symbol])
            return data if ret == ft.RET_OK else None
        except Exception as exc:
            logger.warning("[Futu] static info failed(%s): %s", symbol, exc)
            return None

    def request_trading_days(self, start_date: str, end_date: str, market: str = "hk"):
        """Return trading days of the given market (hk / cn / us) in the range."""
        ctx = self._get_ctx()
        if ctx is None:
            return []
        try:
            import futu as ft
            ft_market = {
                "hk": ft.TradeDateMarket.HK,
                "cn": ft.TradeDateMarket.CN,
                "us": ft.TradeDateMarket.US,
            }.get((market or "hk").lower())
            if ft_market is None:
                return []
            ret, data = ctx.request_trading_days(
                ft_market, start=start_date, end=end_date
            )
            return data if ret == ft.RET_OK else []
        except Exception as exc:
            logger.warning("[Futu] trading days failed: %s", exc)
            return []

    def get_trading_days(self, start_date: str, end_date: str, market: str = "hk"):
        """Return normalized trading-day records for the given market."""
        rows = self.request_trading_days(start_date, end_date, market=market)
        return [
            {
                "date": row.get("time"),
                "trade_date_type": row.get("trade_date_type"),
            }
            for row in rows
            if isinstance(row, dict) and row.get("time")
        ]

    def get_company_profile(self, stock_code: str):
        symbol = _futu_symbol(stock_code)
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
        symbol = _futu_symbol(stock_code)
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
        symbol = _futu_symbol(stock_code)
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
        symbol = _futu_symbol(stock_code)
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
        symbol = _futu_symbol(stock_code)
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
        # Futu's owner-plate (industry/concept) data only covers HK listings.
        symbols = [_futu_symbol(code) for code in stock_codes]
        symbols = [symbol for symbol in symbols if symbol and symbol.startswith("HK.")]
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
        symbol = _futu_symbol(stock_code)
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
            # Without an LV1/LV2 quote subscription Futu returns an empty
            # change_rate; derive it from the previous close instead.
            if change_pct is None and prev:
                change_pct = round((price - prev) / prev * 100, 4)
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
                provider_timestamp=_provider_timestamp(
                    q.get("update_time"), _futu_market(stock_code) or "hk"
                ),
            )
        except Exception as exc:
            logger.warning("[Futu] realtime quote failed(%s): %s", symbol, exc)
            return None

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        symbol = _futu_symbol(stock_code)
        ctx = self._get_ctx()
        if not symbol or ctx is None:
            return pd.DataFrame()
        try:
            import futu as ft
            market = _futu_market(stock_code)
            # Daily candles follow the repository-wide convention: A-shares and
            # US stocks use front-adjusted prices (AkShare/Tushare/Longbridge/
            # YFinance all adjust), otherwise a split shows up as a -75% crash
            # and poisons MAs, alerts and the stored daily window. HK keeps the
            # unadjusted series to stay consistent with the HK routes.
            autype = ft.AuType.NONE if market == "hk" else ft.AuType.QFQ
            ret, data, _ = ctx.request_history_kline(
                symbol,
                start=start_date,
                end=end_date,
                ktype=ft.KLType.K_DAY,
                autype=autype,
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