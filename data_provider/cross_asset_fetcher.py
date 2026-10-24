# -*- coding: utf-8 -*-
"""Cross-asset market data reader for Issue #1910 (cross-asset-v1).

This is an INDEPENDENT reader: it is deliberately NOT registered into
``DataFetcherManager``'s daily-bar routing chain so it cannot pollute the
existing stock fetch routing / circuit-breaker semantics.

Design rules (issue #1910 hard requirements):

- Every item carries ``source`` / ``as_of`` / ``stale`` / ``error``.
- Per-item ``try/except``: a single ticker failure never raises and never
  blocks sibling items; ``fetch_market_snapshot`` NEVER raises.
- Data sources: A-share indices via akshare ``stock_zh_index_daily_em``
  (one bounded subprocess batch call); HK/US/JP/KR/TW indices, VIX, US 10Y
  rates, commodities, crypto and FX via yfinance (same channel as
  ``YfinanceFetcher`` and the portfolio FX service). FX reads the portfolio
  FX cache first (``PortfolioRepository.get_latest_fx_rate``) and falls back
  to a direct yfinance fetch on cache miss/stale.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from src.schemas.cross_asset_context import CROSS_ASSET_GROUPS, CrossAssetItem

logger = logging.getLogger(__name__)

SUPPORTED_MARKETS = frozenset({"cn", "hk", "us", "jp", "kr", "tw"})

# Stale thresholds in natural days, per contract (W1-plan):
# - index/rates closing data: market trading day + 1 natural day
# - fx / volatility(VIX) / commodities / crypto: ``CROSS_ASSET_CONTEXT_STALE_DAYS`` (48h default)
_INDEX_STALE_THRESHOLD_DAYS = 1

# Fetch priority order: voting-relevant groups first (risk voting uses
# indices/fx/volatility), cheapest single-call groups before multi-call ones,
# commodities/crypto last so an exhausted budget only drops the lowest-value
# groups (they surface as error="timeout" in data_quality, never silently).
_FETCH_ORDER = ("volatility", "fx", "rates", "indices", "commodities", "crypto")

# --- yfinance symbol tables -------------------------------------------------
# HK mapping mirrors YfinanceFetcher._get_hk_main_indices (frozen by
# tests/test_yfinance_hk_indices.py): HSI->^HSI, HSTECH->HSTECH.HK, HSCEI->^HSCE.
_YF_INDEX_SYMBOLS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "hk": {
        "HSI": ("^HSI", "恒生指数"),
        "HSTECH": ("HSTECH.HK", "恒生科技指数"),
        "HSCEI": ("^HSCE", "国企指数"),
    },
    "us": {
        "SPX": ("^GSPC", "标普500"),
        "IXIC": ("^IXIC", "纳斯达克指数"),
        "DJI": ("^DJI", "道琼斯指数"),
    },
    "jp": {"N225": ("^N225", "日经225")},
    "kr": {"KS11": ("^KS11", "KOSPI")},
    "tw": {"TWII": ("^TWII", "台湾加权指数")},
}

# A-share indices via akshare stock_zh_index_daily_em (already-registered
# Eastmoney index route). Best-effort FTSE A50 via yfinance;探测失败记 not_supported.
_CN_AKSHARE_INDICES: Dict[str, str] = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000300": "沪深300",
}
_CN_YF_BEST_EFFORT_INDICES: Dict[str, Tuple[str, str]] = {
    "CHA50CFD": ("CHA50CFD", "富时中国A50期货"),
}

_GLOBAL_SYMBOLS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "volatility": {"VIX": ("^VIX", "VIX恐慌指数")},
    "rates": {"US10Y": ("^TNX", "美债10年期收益率")},  # ^TNX quotes yield*10; normalized /10 below
    "commodities": {
        "GOLD": ("GC=F", "COMEX黄金"),
        "WTI": ("CL=F", "WTI原油"),
        "COPPER": ("HG=F", "COMEX铜"),
    },
    "crypto": {"BTC": ("BTC-USD", "比特币"), "ETH": ("ETH-USD", "以太坊")},
}

# FX pairs (USD-based). Cache-first via PortfolioRepository.get_latest_fx_rate.
_FX_PAIRS: Dict[str, Tuple[Tuple[str, str, str, str], ...]] = {
    "cn": (("USD", "CNH", "USDCNH=X", "美元/离岸人民币"),),
    "hk": (
        ("USD", "HKD", "USDHKD=X", "美元/港元"),
        ("USD", "CNH", "USDCNH=X", "美元/离岸人民币"),
        ("DXY", "DXY", "DX-Y.NYB", "美元指数"),
    ),
    "us": (
        ("USD", "CNH", "USDCNH=X", "美元/离岸人民币"),
        ("DXY", "DXY", "DX-Y.NYB", "美元指数"),
    ),
    "jp": (("USD", "JPY", "USDJPY=X", "美元/日元"),),
    "kr": (("USD", "KRW", "USDKRW=X", "美元/韩元"),),
    "tw": (("USD", "TWD", "USDTWD=X", "美元/新台币"),),
}

_MAX_AKSHARE_BATCH_TIMEOUT_SECONDS = 15.0
_MIN_AKSHARE_BATCH_TIMEOUT_SECONDS = 2.0
_YF_MAX_SYMBOLS_PER_GROUP = 8


def _akshare_fetch_cn_index_batch(
    symbols: Tuple[str, ...],
    start_date: str,
    end_date: str,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Fetch several A-share index daily bars in one akshare session.

    Module-level so it stays picklable for the bounded akshare subprocess
    call (``_akshare_call_with_timeout`` spawns with the "spawn" start
    method, so this module must keep its top-level imports light).
    """

    import akshare as ak

    results: Dict[str, Optional[Dict[str, Any]]] = {}
    for symbol in symbols:
        try:
            frame = ak.stock_zh_index_daily_em(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
            results[symbol] = None
            continue
        try:
            if frame is None or getattr(frame, "empty", True) or "close" not in frame:
                results[symbol] = None
                continue
            last_row = frame.iloc[-1]
            close = float(last_row["close"])
            as_of = _coerce_date_value(last_row.get("date"))
            prev_close = close
            if len(frame) > 1:
                prev_close = float(frame.iloc[-2]["close"])
            if close <= 0:
                results[symbol] = None
                continue
            results[symbol] = {
                "as_of": as_of,
                "close": close,
                "prev_close": prev_close,
            }
        except Exception:
            results[symbol] = None
    return results


def _coerce_date_value(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()[:10]
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _index_label_date(value: Any) -> Any:
    """Unwrap a series index label to its ``.date()`` when it has one.

    OR-COR-ce1b6a21: pandas Timestamp / datetime labels expose ``.date`` as a
    bound method — it must be CALLED, not handed to ``_coerce_date_value``
    (which silently returned None for method objects and marked every
    yfinance success as as_of=None / stale=True). String labels pass through
    to the string parsing branch unchanged.
    """

    date_attr = getattr(value, "date", None)
    if callable(date_attr):
        try:
            extracted = date_attr()
        except Exception:
            return value
        if isinstance(extracted, (datetime, date)):
            return extracted
    return value


def _change_pct(last: float, prev: float) -> Optional[float]:
    if prev is None or prev == 0:
        return None
    return round((last - prev) / prev * 100.0, 2)


def _fx_pair_key(from_ccy: str, to_ccy: str) -> str:
    """Stable snapshot key for an FX pair.

    Self-pairs such as the dollar index ("DXY", "DXY") collapse to "DXY"
    instead of the meaningless "DXYDXY".
    """

    return "DXY" if from_ccy == to_ccy else f"{from_ccy}{to_ccy}"


class CrossAssetFetcher:
    """Never-raising cross-asset snapshot reader with a cooperative budget."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        stale_days: int = 2,
        fx_repo: Any = None,
    ) -> None:
        try:
            self._timeout_seconds = max(1.0, float(timeout_seconds))
        except (TypeError, ValueError):
            self._timeout_seconds = 8.0
        try:
            self._stale_days = max(0, int(stale_days))
        except (TypeError, ValueError):
            self._stale_days = 2
        self._fx_repo = fx_repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_market_snapshot(
        self,
        market: str,
        trade_date: date,
    ) -> Dict[str, Dict[str, CrossAssetItem]]:
        """Return {group: {key: CrossAssetItem}} for one market/day.

        Never raises; every failure is encoded on the item itself.
        """

        normalized = str(market or "").strip().lower()
        if normalized not in SUPPORTED_MARKETS:
            normalized = "cn"
        if not isinstance(trade_date, date):
            trade_date = date.today()
        # The budget deadline is a call-stack local (NOT instance state): the
        # fetcher is a shared singleton and task_queue runs analyze_stock on a
        # ThreadPoolExecutor, so an instance attribute would let concurrent
        # fetches overwrite each other's deadline.
        deadline = time.monotonic() + self._timeout_seconds

        snapshot: Dict[str, Dict[str, CrossAssetItem]] = {
            group: {} for group in CROSS_ASSET_GROUPS
        }
        for group in _FETCH_ORDER:
            if self._budget_exceeded(deadline):
                snapshot[group] = self._timeout_group_items(normalized, group, trade_date)
                continue
            try:
                snapshot[group] = self._fetch_group(normalized, group, trade_date, deadline)
            except Exception as exc:  # defensive: group-level backstop
                logger.warning("[CrossAssetFetcher] %s 组抓取异常: %s", group, exc)
                snapshot[group] = {
                    "_group": self._error_item(
                        name=group,
                        error=f"{type(exc).__name__}: {exc}",
                        trade_date=trade_date,
                    )
                }
        return snapshot

    # ------------------------------------------------------------------
    # Group dispatch
    # ------------------------------------------------------------------
    def _fetch_group(
        self,
        market: str,
        group: str,
        trade_date: date,
        deadline: float,
    ) -> Dict[str, CrossAssetItem]:
        if group == "indices":
            return self._fetch_indices(market, trade_date, deadline)
        if group == "fx":
            return self._fetch_fx(market, trade_date, deadline)
        if group == "volatility":
            return self._fetch_symbol_group(market, "volatility", trade_date, deadline)
        if group == "rates":
            return self._fetch_symbol_group(market, "rates", trade_date, deadline)
        if group == "commodities":
            return self._fetch_symbol_group(market, "commodities", trade_date, deadline)
        if group == "crypto":
            return self._fetch_symbol_group(market, "crypto", trade_date, deadline)
        return {}

    def _fetch_indices(
        self, market: str, trade_date: date, deadline: float
    ) -> Dict[str, CrossAssetItem]:
        items: Dict[str, CrossAssetItem] = {}
        if market == "cn":
            items.update(self._fetch_cn_akshare_indices(trade_date, deadline))
            items.update(
                self._fetch_symbol_table(
                    _CN_YF_BEST_EFFORT_INDICES,
                    trade_date,
                    stale_days=_INDEX_STALE_THRESHOLD_DAYS,
                    source="yfinance",
                    deadline=deadline,
                )
            )
        else:
            table = _YF_INDEX_SYMBOLS.get(market, {})
            items.update(
                self._fetch_symbol_table(
                    table,
                    trade_date,
                    stale_days=_INDEX_STALE_THRESHOLD_DAYS,
                    source="yfinance",
                    deadline=deadline,
                )
            )
        return items

    def _fetch_symbol_group(
        self,
        market: str,
        group: str,
        trade_date: date,
        deadline: float,
    ) -> Dict[str, CrossAssetItem]:
        table = _GLOBAL_SYMBOLS.get(group, {})
        # rates (US 10Y) uses the strict trading-day+1 threshold;
        # VIX/crypto/commodities use the 48h-style stale_days threshold.
        stale_days = _INDEX_STALE_THRESHOLD_DAYS if group == "rates" else self._stale_days
        return self._fetch_symbol_table(
            table,
            trade_date,
            stale_days=stale_days,
            source="yfinance",
            deadline=deadline,
        )

    def _fetch_symbol_table(
        self,
        table: Dict[str, Tuple[str, str]],
        trade_date: date,
        *,
        stale_days: int,
        source: str,
        deadline: float,
    ) -> Dict[str, CrossAssetItem]:
        items: Dict[str, CrossAssetItem] = {}
        for key, (symbol, name) in list(table.items())[:_YF_MAX_SYMBOLS_PER_GROUP]:
            items[key] = self._safe_yf_item(
                key=key,
                name=name,
                symbol=symbol,
                trade_date=trade_date,
                stale_days=stale_days,
                source=source,
                deadline=deadline,
            )
        return items

    # ------------------------------------------------------------------
    # A-share indices (akshare, one bounded batch subprocess)
    # ------------------------------------------------------------------
    def _fetch_cn_akshare_indices(
        self, trade_date: date, deadline: float
    ) -> Dict[str, CrossAssetItem]:
        items: Dict[str, CrossAssetItem] = {}
        if self._budget_exceeded(deadline):
            return {
                key: self._timeout_item(name=name, trade_date=trade_date)
                for key, name in _CN_AKSHARE_INDICES.items()
            }
        start = (trade_date - timedelta(days=10)).strftime("%Y%m%d")
        end = (trade_date + timedelta(days=1)).strftime("%Y%m%d")
        remaining = self._budget_remaining(deadline)
        batch_timeout = min(
            max(remaining, _MIN_AKSHARE_BATCH_TIMEOUT_SECONDS),
            _MAX_AKSHARE_BATCH_TIMEOUT_SECONDS,
        )
        batch: Dict[str, Optional[Dict[str, Any]]] = {}
        try:
            from data_provider.akshare_fetcher import _akshare_call_with_timeout

            batch = _akshare_call_with_timeout(
                _akshare_fetch_cn_index_batch,
                tuple(_CN_AKSHARE_INDICES.keys()),
                start,
                end,
                timeout=batch_timeout,
                call_name="cross_asset_cn_index_batch",
            ) or {}
        except Exception as exc:
            logger.warning("[CrossAssetFetcher] A股指数批量抓取失败: %s", exc)
            batch = {}
        for key, name in _CN_AKSHARE_INDICES.items():
            payload = batch.get(key)
            if not payload:
                items[key] = CrossAssetItem(
                    status="not_supported" if batch else "error",
                    name=name,
                    source="akshare:stock_zh_index_daily_em",
                    # not_supported must explain itself like the yfinance
                    # branch does (error="no_data"); only a dead batch is a
                    # hard failure (error="akshare_batch_failed").
                    error="no_data" if batch else "akshare_batch_failed",
                )
                continue
            as_of = payload.get("as_of")
            items[key] = CrossAssetItem(
                status="ok",
                value=float(payload.get("close") or 0.0) or None,
                change_pct=_change_pct(
                    float(payload.get("close") or 0.0),
                    float(payload.get("prev_close") or 0.0),
                ),
                name=name,
                source="akshare:stock_zh_index_daily_em",
                as_of=as_of.isoformat() if isinstance(as_of, date) else None,
                stale=self._is_stale(as_of, trade_date, _INDEX_STALE_THRESHOLD_DAYS),
            )
        return items

    # ------------------------------------------------------------------
    # FX (portfolio cache first, yfinance fallback)
    # ------------------------------------------------------------------
    def _fetch_fx(
        self, market: str, trade_date: date, deadline: float
    ) -> Dict[str, CrossAssetItem]:
        items: Dict[str, CrossAssetItem] = {}
        for from_ccy, to_ccy, symbol, name in _FX_PAIRS.get(market, ()):
            key = _fx_pair_key(from_ccy, to_ccy)
            items[key] = self._safe_fx_item(
                key=key,
                name=name,
                from_ccy=from_ccy,
                to_ccy=to_ccy,
                symbol=symbol,
                trade_date=trade_date,
                deadline=deadline,
            )
        return items

    def _safe_fx_item(
        self,
        *,
        key: str,
        name: str,
        from_ccy: str,
        to_ccy: str,
        symbol: str,
        trade_date: date,
        deadline: float,
    ) -> CrossAssetItem:
        cached = self._read_fx_cache(from_ccy=from_ccy, to_ccy=to_ccy, as_of=trade_date)
        if cached is not None:
            cache_row, cache_stale = cached
            rate_date = getattr(cache_row, "rate_date", None)
            return CrossAssetItem(
                status="ok",
                value=float(cache_row.rate),
                change_pct=None,  # a single cached rate cannot yield a change
                name=name,
                source=f"portfolio_cache:{getattr(cache_row, 'source', None) or 'unknown'}",
                as_of=rate_date.isoformat() if isinstance(rate_date, date) else None,
                stale=cache_stale,
            )
        return self._safe_yf_item(
            key=key,
            name=name,
            symbol=symbol,
            trade_date=trade_date,
            stale_days=self._stale_days,
            source="yfinance",
            deadline=deadline,
        )

    def _read_fx_cache(
        self,
        *,
        from_ccy: str,
        to_ccy: str,
        as_of: date,
    ) -> Optional[Tuple[Any, bool]]:
        repo = self._get_fx_repo()
        if repo is None:
            return None
        try:
            row = repo.get_latest_fx_rate(
                from_currency=from_ccy,
                to_currency=to_ccy,
                as_of=as_of,
            )
        except Exception as exc:
            logger.warning("[CrossAssetFetcher] FX 缓存读取失败 %s/%s: %s", from_ccy, to_ccy, exc)
            return None
        if row is None:
            return None
        try:
            rate = float(row.rate)
        except (TypeError, ValueError):
            return None
        if rate <= 0:
            return None
        rate_date = getattr(row, "rate_date", None)
        if not isinstance(rate_date, date):
            return None
        stale = (as_of - rate_date).days > self._stale_days
        return row, stale

    def _get_fx_repo(self) -> Any:
        if self._fx_repo is not None:
            return self._fx_repo
        try:
            from src.repositories.portfolio_repo import PortfolioRepository

            self._fx_repo = PortfolioRepository()
        except Exception as exc:
            logger.debug("[CrossAssetFetcher] PortfolioRepository 不可用: %s", exc)
            self._fx_repo = None
        return self._fx_repo

    # ------------------------------------------------------------------
    # yfinance item plumbing
    # ------------------------------------------------------------------
    def _safe_yf_item(
        self,
        *,
        key: str,
        name: str,
        symbol: str,
        trade_date: date,
        stale_days: int,
        source: str,
        deadline: float,
    ) -> CrossAssetItem:
        if self._budget_exceeded(deadline):
            return self._timeout_item(name=name, trade_date=trade_date)
        try:
            series = self._fetch_yf_series(symbol)
        except Exception as exc:
            return self._error_item(name=name, error=f"{type(exc).__name__}: {exc}", trade_date=trade_date)
        if series is None:
            return CrossAssetItem(
                status="not_supported",
                name=name,
                source=source,
                error="no_data",
            )
        as_of, last, prev = series
        # OR-COR-7bbac105: Yahoo Close (^TNX included) is already quoted as a
        # percent quantity (4.21 = 4.21%); no further scaling is applied.
        value = last
        return CrossAssetItem(
            status="ok",
            value=value,
            change_pct=_change_pct(last, prev),
            name=name,
            source=source,
            as_of=as_of.isoformat() if isinstance(as_of, date) else None,
            stale=self._is_stale(as_of, trade_date, stale_days),
        )

    @staticmethod
    def _fetch_yf_series(symbol: str) -> Optional[Tuple[date, float, float]]:
        """Return (as_of, last_close, prev_close) or None; may raise."""

        import yfinance as yf

        ticker = yf.Ticker(symbol)
        history = ticker.history(period="5d", auto_adjust=False)
        if history is None or getattr(history, "empty", True) or "Close" not in history:
            return None
        close = history["Close"].dropna()
        if close.empty:
            return None
        last_index = close.index[-1]
        as_of = _coerce_date_value(_index_label_date(last_index))
        last = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) > 1 else last
        if last <= 0:
            return None
        return as_of, last, prev

    # ------------------------------------------------------------------
    # Budget / quality helpers
    # ------------------------------------------------------------------
    def _budget_remaining(self, deadline: float) -> float:
        return deadline - time.monotonic()

    def _budget_exceeded(self, deadline: float) -> bool:
        return self._budget_remaining(deadline) <= 0

    def _is_stale(self, as_of: Optional[date], trade_date: date, threshold_days: int) -> bool:
        if as_of is None:
            return True
        return (trade_date - as_of).days > max(0, int(threshold_days))

    def _timeout_item(self, *, name: str, trade_date: date) -> CrossAssetItem:
        return CrossAssetItem(
            status="error",
            name=name,
            error="timeout",
            source="cross_asset_fetcher",
            as_of=trade_date.isoformat(),
        )

    def _error_item(self, *, name: str, error: str, trade_date: date) -> CrossAssetItem:
        return CrossAssetItem(
            status="error",
            name=name,
            error=str(error)[:200],
            source="cross_asset_fetcher",
            as_of=trade_date.isoformat(),
        )

    def _timeout_group_items(
        self,
        market: str,
        group: str,
        trade_date: date,
    ) -> Dict[str, CrossAssetItem]:
        """Pre-built timeout items for a group the budget can no longer cover."""

        if group == "indices":
            if market == "cn":
                names: Dict[str, str] = dict(_CN_AKSHARE_INDICES)
                names.update({key: value[1] for key, value in _CN_YF_BEST_EFFORT_INDICES.items()})
            else:
                names = {key: value[1] for key, value in _YF_INDEX_SYMBOLS.get(market, {}).items()}
            return {key: self._timeout_item(name=name, trade_date=trade_date) for key, name in names.items()}
        if group == "fx":
            names = {
                _fx_pair_key(from_ccy, to_ccy): name
                for from_ccy, to_ccy, _symbol, name in _FX_PAIRS.get(market, ())
            }
            return {key: self._timeout_item(name=name, trade_date=trade_date) for key, name in names.items()}
        names = {key: value[1] for key, value in _GLOBAL_SYMBOLS.get(group, {}).items()}
        return {key: self._timeout_item(name=name, trade_date=trade_date) for key, name in names.items()}
