# -*- coding: utf-8 -*-
"""
===================================
LongbridgeFetcher - 长桥兜底数据源 (Priority 5)
===================================

数据来源：长桥 OpenAPI (https://open.longbridge.com)
特点：覆盖美股 + 港股，可计算量比/换手率/PE 等 yfinance 缺失字段
定位：美股/港股最后兜底数据源

关键策略：
1. 组合 quote + static_info 接口计算 turnover_rate / pe_ratio / total_mv
2. 通过 history_candlesticks 计算 volume_ratio（近5日均量比）
3. 懒加载 QuoteContext，首次调用时才建立连接
4. static_info 进程内短缓存，减少重复请求（默认 24h，可调；见 LONGBRIDGE_STATIC_INFO_TTL_SECONDS）

凭证：`LONGBRIDGE_APP_KEY` / `LONGBRIDGE_APP_SECRET` / `LONGBRIDGE_ACCESS_TOKEN`。
可选：`LONGBRIDGE_STATIC_INFO_TTL_SECONDS`；SDK `language` 取自 `REPORT_LANGUAGE`，`log_path` 为 `{LOG_DIR}/longbridge_sdk.log`；
`LONGBRIDGE_HTTP_URL` / `LONGBRIDGE_QUOTE_WS_URL` / `LONGBRIDGE_TRADE_WS_URL` / `LONGBRIDGE_REGION` （见官方文档默认值）。
"""

import logging
import os
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd

from .base import BaseFetcher, STANDARD_COLUMNS
from .realtime_types import UnifiedRealtimeQuote, RealtimeSource, safe_float
from .us_index_mapping import is_us_stock_code, is_us_index_code

logger = logging.getLogger(__name__)

_DEFAULT_STATIC_INFO_TTL = 86400  # 24h


def _static_info_ttl_seconds() -> int:
    """TTL for static_info cache; 0 disables caching (always fetch)."""
    raw = os.getenv("LONGBRIDGE_STATIC_INFO_TTL_SECONDS", "").strip()
    if raw == "":
        return _DEFAULT_STATIC_INFO_TTL
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_STATIC_INFO_TTL


_REGION_URL_MAP: Dict[str, Dict[str, str]] = {
    "cn": {
        "http_url": "https://openapi.longbridge.cn",
        "quote_ws_url": "wss://openapi-quote.longbridge.cn/v2",
        "trade_ws_url": "wss://openapi-trade.longbridge.cn/v2",
    },
    "hk": {
        "http_url": "https://openapi.longbridge.com",
        "quote_ws_url": "wss://openapi-quote.longbridge.com/v2",
        "trade_ws_url": "wss://openapi-trade.longbridge.com/v2",
    },
}


def _sanitize_longbridge_env() -> None:
    """Remove empty-string LONGBRIDGE_*_URL env vars.

    GitHub Actions sets ``LONGBRIDGE_HTTP_URL: ${{ vars.X || secrets.X }}``
    which resolves to an empty string ``""`` when neither var nor secret is
    configured.  The Rust SDK's ``Config.from_apikey()`` auto-reads these
    env vars, and an empty string is *not* the same as "unset" — it causes
    the SDK to use a blank URL, which breaks the WebSocket handshake and
    results in "context dropped" / "Client is closed" within milliseconds.

    Also mirrors ``LONGBRIDGE_REGION`` → ``LONGPORT_REGION`` because the
    Rust SDK's internal ``is_cn()`` function only checks ``LONGPORT_REGION``
    (not ``LONGBRIDGE_REGION``) when deciding which default endpoints to use.
    """
    for key in (
        "LONGBRIDGE_HTTP_URL",
        "LONGBRIDGE_QUOTE_WS_URL",
        "LONGBRIDGE_TRADE_WS_URL",
        "LONGBRIDGE_ENABLE_OVERNIGHT",
        "LONGBRIDGE_PUSH_CANDLESTICK_MODE",
        "LONGBRIDGE_PRINT_QUOTE_PACKAGES",
        "LONGBRIDGE_REGION",
        "LONGBRIDGE_STATIC_INFO_TTL_SECONDS",
        "LONGBRIDGE_LOG_PATH",
    ):
        val = os.environ.get(key)
        if val is not None and val.strip() == "":
            del os.environ[key]
            logger.debug("[Longbridge] 删除空环境变量 %s", key)

    # App default: quiet (false). Matches README / docs/full-guide / .env.example; SDK alone may default verbose.
    if "LONGBRIDGE_PRINT_QUOTE_PACKAGES" not in os.environ:
        os.environ["LONGBRIDGE_PRINT_QUOTE_PACKAGES"] = "false"

    if not os.environ.get("LONGBRIDGE_LOG_PATH"):
        try:
            log_dir = (os.getenv("LOG_DIR") or "./logs").strip() or "./logs"
            p = Path(log_dir).expanduser()
            p.mkdir(parents=True, exist_ok=True)
            os.environ["LONGBRIDGE_LOG_PATH"] = str(p / "longbridge_sdk.log")
            logger.debug("[Longbridge] 设置 LONGBRIDGE_LOG_PATH=%s",
                         os.environ["LONGBRIDGE_LOG_PATH"])
        except Exception:
            pass

    region = (os.getenv("LONGBRIDGE_REGION") or "").strip().lower()
    if region:
        if not os.environ.get("LONGPORT_REGION"):
            os.environ["LONGPORT_REGION"] = region
            logger.debug("[Longbridge] 同步 LONGPORT_REGION=%s", region)

        urls = _REGION_URL_MAP.get(region, {})
        for env_name, default_url in (
            ("LONGBRIDGE_HTTP_URL", urls.get("http_url")),
            ("LONGBRIDGE_QUOTE_WS_URL", urls.get("quote_ws_url")),
            ("LONGBRIDGE_TRADE_WS_URL", urls.get("trade_ws_url")),
        ):
            if default_url and not os.environ.get(env_name):
                os.environ[env_name] = default_url
                logger.debug("[Longbridge] 根据 REGION=%s 设置 %s=%s",
                             region, env_name, default_url)


def _longbridge_config_kwargs() -> Dict[str, Any]:
    """Optional kwargs for ``Config.from_apikey`` (Longbridge OpenAPI SDK)."""
    try:
        import inspect
        from longbridge.openapi import Config, Language, PushCandlestickMode
    except Exception:
        return {}

    try:
        params = inspect.signature(Config.from_apikey).parameters
    except Exception:
        return {}

    kw: Dict[str, Any] = {}

    if "enable_print_quote_packages" in params:
        # Unset / empty → False (quiet); SDK default would be verbose — we opt in explicitly.
        raw = os.getenv("LONGBRIDGE_PRINT_QUOTE_PACKAGES")
        if raw is None or not str(raw).strip():
            kw["enable_print_quote_packages"] = False
        else:
            raw_norm = str(raw).strip().lower()
            kw["enable_print_quote_packages"] = raw_norm not in ("0", "false", "no")

    for pname, envname in (
        ("http_url", "LONGBRIDGE_HTTP_URL"),
        ("quote_ws_url", "LONGBRIDGE_QUOTE_WS_URL"),
        ("trade_ws_url", "LONGBRIDGE_TRADE_WS_URL"),
    ):
        if pname in params:
            v = os.getenv(envname, "").strip()
            if v:
                kw[pname] = v

    if "language" in params:
        try:
            from src.report_language import normalize_report_language

            rl = normalize_report_language(os.getenv("REPORT_LANGUAGE"), default="zh")
            if rl == "zh":
                kw["language"] = Language.ZH_CN
            elif rl == "en":
                kw["language"] = Language.EN
        except Exception as e:
            logger.debug("Longbridge language from REPORT_LANGUAGE skipped: %s", e)

    if "enable_overnight" in params:
        o = os.getenv("LONGBRIDGE_ENABLE_OVERNIGHT", "").strip().lower()
        if o:
            kw["enable_overnight"] = o in ("1", "true", "yes")

    if "push_candlestick_mode" in params:
        cm = os.getenv("LONGBRIDGE_PUSH_CANDLESTICK_MODE", "").strip().lower()
        if cm == "realtime":
            kw["push_candlestick_mode"] = PushCandlestickMode.Realtime
        elif cm == "confirmed":
            kw["push_candlestick_mode"] = PushCandlestickMode.Confirmed
        elif cm:
            logger.warning(
                "Unknown LONGBRIDGE_PUSH_CANDLESTICK_MODE=%r; use realtime or confirmed", cm
            )

    if "log_path" in params:
        try:
            log_dir = (os.getenv("LOG_DIR") or "./logs").strip() or "./logs"
            p = Path(log_dir).expanduser()
            p.mkdir(parents=True, exist_ok=True)
            kw["log_path"] = str(p / "longbridge_sdk.log")
        except Exception as e:
            logger.debug("Longbridge log_path from LOG_DIR skipped: %s", e)

    return kw


def _is_us_code(stock_code: str) -> bool:
    normalized = stock_code.strip().upper()
    return is_us_stock_code(normalized) or is_us_index_code(normalized)


def _is_hk_code(stock_code: str) -> bool:
    normalized = (stock_code or "").strip().upper()
    if normalized.startswith("HK"):
        digits = normalized[2:]
        return digits.isdigit() and 1 <= len(digits) <= 5
    if normalized.endswith(".HK"):
        return True
    if normalized.isdigit() and len(normalized) == 5:
        return True
    return False


def _to_longbridge_symbol(stock_code: str) -> Optional[str]:
    """Convert internal stock code to Longbridge symbol format.

    Examples:
        AAPL      -> AAPL.US
        HK00700   -> 0700.HK
        00700     -> 0700.HK (5-digit pure number treated as HK)
    """
    code = stock_code.strip()
    upper = code.upper()

    if upper.endswith(".US"):
        return upper
    if upper.endswith(".HK"):
        return upper

    if _is_us_code(code):
        return f"{upper}.US"

    if _is_hk_code(code):
        upper = code.upper()
        if upper.startswith("HK"):
            digits = upper[2:]
        else:
            digits = upper
        digits = digits.lstrip("0") or "0"
        return f"{digits.zfill(4)}.HK"

    return None


class LongbridgeFetcher(BaseFetcher):
    """
    长桥 OpenAPI 数据源实现

    优先级: 5（最低，作为美股/港股最后兜底）
    数据来源: Longbridge OpenAPI

    通过组合多个 API 计算 yfinance 缺失的指标:
    - turnover_rate = volume / circulating_shares * 100
    - volume_ratio = today_volume / avg_5day_volume
    - pe_ratio = price / eps_ttm
    """

    name = "LongbridgeFetcher"
    priority = int(os.getenv("LONGBRIDGE_PRIORITY", "5"))

    _CONNECTION_ERRORS = ("client is closed", "context closed", "connection closed")

    def __init__(self):
        self._ctx = None
        self._config = None
        self._ctx_lock = threading.Lock()
        self._available = None
        # {symbol: (StaticInfo, timestamp)}
        self._static_cache: Dict[str, Any] = {}
        self._static_cache_lock = threading.Lock()

    def _is_connection_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(s in msg for s in self._CONNECTION_ERRORS)

    def _invalidate_ctx(self):
        """Reset cached context so the next call rebuilds the connection."""
        with self._ctx_lock:
            self._ctx = None
            self._config = None

    def _is_available(self) -> bool:
        """Check if Longbridge credentials are configured."""
        if self._available is not None:
            return self._available
        try:
            from src.config import get_config
            config = get_config()
            has_creds = bool(
                config.longbridge_app_key
                and config.longbridge_app_secret
                and config.longbridge_access_token
            )
        except Exception:
            has_creds = bool(
                os.getenv("LONGBRIDGE_APP_KEY")
                and os.getenv("LONGBRIDGE_APP_SECRET")
                and os.getenv("LONGBRIDGE_ACCESS_TOKEN")
            )
        self._available = has_creds
        return has_creds

    def _get_ctx(self):
        """Lazy-init the QuoteContext (thread-safe)."""
        if self._ctx is not None:
            return self._ctx
        with self._ctx_lock:
            if self._ctx is not None:
                return self._ctx
            if not self._is_available():
                return None
            try:
                from longbridge.openapi import QuoteContext, Config

                # ── 1. Clean up empty URL env vars & apply REGION mapping ──
                _sanitize_longbridge_env()

                # ── 2. Ensure credentials are available in env ──
                try:
                    from src.config import get_config
                    app_config = get_config()
                    app_key = app_config.longbridge_app_key
                    app_secret = app_config.longbridge_app_secret
                    access_token = app_config.longbridge_access_token
                except Exception:
                    app_key = os.getenv("LONGBRIDGE_APP_KEY")
                    app_secret = os.getenv("LONGBRIDGE_APP_SECRET")
                    access_token = os.getenv("LONGBRIDGE_ACCESS_TOKEN")

                for k, v in {
                    "LONGBRIDGE_APP_KEY": app_key,
                    "LONGBRIDGE_APP_SECRET": app_secret,
                    "LONGBRIDGE_ACCESS_TOKEN": access_token,
                }.items():
                    if v and not os.environ.get(k):
                        os.environ[k] = v

                # ── 3. Build Config ──
                extra_kw = _longbridge_config_kwargs()
                lb_config = None

                # Prefer from_apikey_env() — reads all LONGBRIDGE_* env vars
                # (credentials + URLs + options) including .env files.
                # Available in longbridge >= 4.x.  from_env() only exists on
                # the unreleased master branch.
                for factory_name in ("from_apikey_env", "from_env"):
                    factory = getattr(Config, factory_name, None)
                    if factory is None:
                        continue
                    try:
                        lb_config = factory()
                        logger.info("[Longbridge] Config.%s() 成功", factory_name)
                        break
                    except Exception as e:
                        logger.debug(
                            "[Longbridge] Config.%s() 失败: %s", factory_name, e
                        )

                if lb_config is None:
                    lb_config = Config.from_apikey(
                        app_key,
                        app_secret,
                        access_token,
                        **extra_kw,
                    )
                    logger.info("[Longbridge] Config.from_apikey() 创建成功")

                # Diagnostic logging
                region = os.getenv("LONGBRIDGE_REGION") or os.getenv("LONGPORT_REGION") or "(auto)"
                logger.info(
                    "[Longbridge] 配置: region=%s, http=%s, quote_ws=%s",
                    region,
                    os.getenv("LONGBRIDGE_HTTP_URL", "(default)"),
                    os.getenv("LONGBRIDGE_QUOTE_WS_URL", "(default)"),
                )

                self._config = lb_config
                self._ctx = QuoteContext(lb_config)
                logger.info("[Longbridge] QuoteContext 初始化成功")
                return self._ctx
            except Exception as e:
                logger.warning("[Longbridge] QuoteContext 初始化失败: %s", e)
                self._available = False
                return None

    # ------------------------------------------------------------------
    # static_info with cache
    # ------------------------------------------------------------------

    def _get_static_info(self, symbol: str) -> Optional[Any]:
        """Fetch static info (shares, EPS, BPS, name) with optional in-process TTL cache."""
        ttl = _static_info_ttl_seconds()
        now = time.time()
        if ttl > 0:
            with self._static_cache_lock:
                cached = self._static_cache.get(symbol)
                if cached and (now - cached[1]) < ttl:
                    return cached[0]

        ctx = self._get_ctx()
        if ctx is None:
            return None
        try:
            infos = ctx.static_info([symbol])
            if infos:
                info = infos[0]
                if ttl > 0:
                    with self._static_cache_lock:
                        self._static_cache[symbol] = (info, now)
                return info
        except Exception as e:
            logger.debug(f"[Longbridge] static_info({symbol}) 失败: {e}")
            if self._is_connection_error(e):
                self._invalidate_ctx()
        return None

    # ------------------------------------------------------------------
    # get_stock_name via static_info
    # ------------------------------------------------------------------

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """Return stock name from Longbridge static_info (name_cn or name_en)."""
        symbol = _to_longbridge_symbol(stock_code)
        if symbol is None:
            return None
        info = self._get_static_info(symbol)
        if info is None:
            return None
        name = getattr(info, "name_cn", "") or getattr(info, "name_en", "") or ""
        return name.strip() or None

    # ------------------------------------------------------------------
    # volume_ratio from history
    # ------------------------------------------------------------------

    def _ts_sort_key(self, candle: Any) -> float:
        """Monotonic sort key for a candle timestamp (UTC seconds or datetime)."""
        ts = getattr(candle, "timestamp", None)
        if ts is None:
            return 0.0
        if hasattr(ts, "timestamp"):
            return float(ts.timestamp())
        return float(int(ts))

    def _compute_volume_ratio(self, symbol: str, today_volume: int) -> Optional[float]:
        """Compute volume_ratio = today_volume / avg(recent completed daily volumes).

        Uses the most recent daily bar as \"today/incomplete\" reference window: average
        volume of the next 5 older daily bars. Avoids local `date.today()` matching, which
        breaks for US symbols when the shell runs in CN timezone.
        """
        if not today_volume or today_volume <= 0:
            return None
        ctx = self._get_ctx()
        if ctx is None:
            return None
        try:
            from longbridge.openapi import Period, AdjustType

            candles = ctx.history_candlesticks_by_offset(
                symbol,
                Period.Day,
                AdjustType.NoAdjust,
                False,
                6,
                datetime.now(),
            )
            if not candles or len(candles) < 2:
                return None

            ordered = sorted(candles, key=self._ts_sort_key, reverse=True)
            past_vols: list = []
            for c in ordered[1:6]:
                vol = int(getattr(c, "volume", 0) or 0)
                if vol > 0:
                    past_vols.append(vol)

            if not past_vols:
                return None

            avg_vol = sum(past_vols) / len(past_vols)
            if avg_vol <= 0:
                return None

            return round(today_volume / avg_vol, 2)
        except Exception as e:
            logger.debug(f"[Longbridge] 计算量比失败({symbol}): {e}")
            return None

    # ------------------------------------------------------------------
    # get_realtime_quote
    # ------------------------------------------------------------------

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """Fetch realtime quote from Longbridge, computing derived fields."""
        if not self._is_available():
            return None

        symbol = _to_longbridge_symbol(stock_code)
        if symbol is None:
            logger.debug(f"[Longbridge] 无法转换代码: {stock_code}")
            return None

        ctx = self._get_ctx()
        if ctx is None:
            return None

        try:
            quotes = ctx.quote([symbol])
            if not quotes:
                return None
            q = quotes[0]
        except Exception as e:
            logger.info(f"[Longbridge] quote({symbol}) 失败: {e}")
            if self._is_connection_error(e):
                logger.warning("[Longbridge] 检测到连接已断开，将在下次调用时重建连接")
                self._invalidate_ctx()
            return None

        price = safe_float(getattr(q, "last_done", None))
        if price is None or price <= 0:
            return None

        prev_close = safe_float(getattr(q, "prev_close", None))
        open_price = safe_float(getattr(q, "open", None))
        high = safe_float(getattr(q, "high", None))
        low = safe_float(getattr(q, "low", None))
        volume = int(getattr(q, "volume", 0) or 0)
        turnover = safe_float(getattr(q, "turnover", None))

        change_amount = None
        change_pct = None
        amplitude = None
        if prev_close and prev_close > 0:
            change_amount = round(price - prev_close, 4)
            change_pct = round((price - prev_close) / prev_close * 100, 2)
            if high is not None and low is not None:
                amplitude = round((high - low) / prev_close * 100, 2)

        # Fetch static info for derived fields
        static = self._get_static_info(symbol)

        turnover_rate = None
        pe_ratio = None
        pb_ratio = None
        total_mv = None
        circ_mv = None
        name = ""

        if static is not None:
            name = getattr(static, "name_cn", "") or getattr(static, "name_en", "") or ""
            circulating = int(getattr(static, "circulating_shares", 0) or 0)
            total_shares = int(getattr(static, "total_shares", 0) or 0)
            eps_ttm = safe_float(getattr(static, "eps_ttm", None))
            eps_plain = safe_float(getattr(static, "eps", None))
            bps = safe_float(getattr(static, "bps", None))

            # US names often report circulating_shares=0 while total_shares is set — use total for turnover.
            shares_for_turnover = circulating if circulating > 0 else total_shares
            if shares_for_turnover > 0 and volume > 0:
                turnover_rate = round(volume / shares_for_turnover * 100, 4)
            elif volume > 0:
                logger.debug(
                    "[Longbridge] %s 无法计算换手率: volume=%s circulating=%s total_shares=%s",
                    symbol,
                    volume,
                    circulating,
                    total_shares,
                )

            eps_for_pe = None
            if eps_ttm is not None and eps_ttm > 0:
                eps_for_pe = eps_ttm
            elif eps_plain is not None and eps_plain > 0:
                eps_for_pe = eps_plain
            if eps_for_pe:
                pe_ratio = round(price / eps_for_pe, 2)

            if bps is not None and bps > 0:
                pb_ratio = round(price / bps, 2)
            if total_shares > 0:
                total_mv = round(price * total_shares, 2)
            if circulating > 0:
                circ_mv = round(price * circulating, 2)

        volume_ratio = self._compute_volume_ratio(symbol, volume)

        quote = UnifiedRealtimeQuote(
            code=stock_code,
            name=name,
            source=RealtimeSource.LONGBRIDGE,
            price=price,
            change_pct=change_pct,
            change_amount=change_amount,
            volume=volume if volume > 0 else None,
            amount=turnover,
            volume_ratio=volume_ratio,
            turnover_rate=turnover_rate,
            amplitude=amplitude,
            open_price=open_price,
            high=high,
            low=low,
            pre_close=prev_close,
            pe_ratio=pe_ratio,
            pb_ratio=pb_ratio,
            total_mv=total_mv,
            circ_mv=circ_mv,
        )

        logger.info(
            f"[Longbridge] {symbol} 行情获取成功: "
            f"价格={price}, 量比={volume_ratio}, 换手率={turnover_rate}"
        )
        return quote

    # ------------------------------------------------------------------
    # BaseFetcher abstract methods (historical daily data)
    # ------------------------------------------------------------------

    def _fetch_raw_data(
        self, stock_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Fetch historical candlesticks from Longbridge."""
        symbol = _to_longbridge_symbol(stock_code)
        if symbol is None:
            raise ValueError(f"Cannot convert {stock_code} to Longbridge symbol")

        ctx = self._get_ctx()
        if ctx is None:
            raise RuntimeError("Longbridge QuoteContext not available")

        from longbridge.openapi import Period, AdjustType

        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

        try:
            candles = ctx.history_candlesticks_by_date(
                symbol,
                Period.Day,
                AdjustType.ForwardAdjust,
                start_dt,
                end_dt,
            )
        except Exception as e:
            if self._is_connection_error(e):
                logger.warning("[Longbridge] 检测到连接已断开，将在下次调用时重建连接")
                self._invalidate_ctx()
            raise

        if not candles:
            return pd.DataFrame()

        rows = []
        for c in candles:
            ts = getattr(c, "timestamp", None)
            if ts is None:
                continue
            if hasattr(ts, "date"):
                dt = ts.date()
            else:
                dt = datetime.fromtimestamp(int(ts)).date()

            rows.append({
                "date": dt.strftime("%Y-%m-%d"),
                "open": safe_float(getattr(c, "open", None)),
                "high": safe_float(getattr(c, "high", None)),
                "low": safe_float(getattr(c, "low", None)),
                "close": safe_float(getattr(c, "close", None)),
                "volume": int(getattr(c, "volume", 0) or 0),
                "turnover": safe_float(getattr(c, "turnover", None)),
            })

        return pd.DataFrame(rows)

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Normalize column names to standard format."""
        if df.empty:
            return pd.DataFrame(columns=STANDARD_COLUMNS)

        rename_map = {"turnover": "amount"}
        df = df.rename(columns=rename_map)

        if "pct_chg" not in df.columns and "close" in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100

        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = None

        return df[STANDARD_COLUMNS]
