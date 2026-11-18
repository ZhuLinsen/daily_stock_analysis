# -*- coding: utf-8 -*-
"""Cross-asset market data reader for Issue #1910 (cross-asset-v1, phase 1).

This is an INDEPENDENT reader: it is deliberately NOT registered into
``DataFetcherManager``'s daily-bar routing chain so it cannot pollute the
existing stock fetch routing / circuit-breaker semantics.

Phase-1 provider scope (single provider, maintainer-agreed convergence):
yfinance only — hk/us/jp/kr/tw indices via the same symbol tables as
``YfinanceFetcher`` (HK mapping frozen by tests/test_yfinance_hk_indices.py),
best-effort FTSE A50 for cn, plus the global ``^VIX`` (volatility) and
``^TNX`` (US 10Y rates). FX / commodities / crypto, the akshare CN index
batch and the portfolio FX cache channel are DEFERRED to a later PR; their
contract groups stay empty (never fabricated) in phase 1.

Design rules (issue #1910 hard requirements, unchanged from the reviewed
implementation):

- Every item carries ``source`` / ``as_of`` / ``stale`` / ``error``.
- Per-item ``try/except``: a single ticker failure never raises and never
  blocks sibling items; ``fetch_market_snapshot`` NEVER raises.
- An exhausted budget surfaces ``error="timeout"`` on the pending items —
  it never silently drops a group.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

from src.schemas.cross_asset_context import CROSS_ASSET_GROUPS, CrossAssetItem

logger = logging.getLogger(__name__)

SUPPORTED_MARKETS = frozenset({"cn", "hk", "us", "jp", "kr", "tw"})

# Stale thresholds in natural days, per contract (W1-plan):
# - index/rates closing data: market trading day + 1 natural day
# - volatility(VIX): ``CROSS_ASSET_CONTEXT_STALE_DAYS`` (48h default)
_INDEX_STALE_THRESHOLD_DAYS = 1

# Fetch priority order: voting-relevant groups first (risk voting uses
# indices/volatility), so an exhausted budget only drops the lowest-value
# groups (they surface as error="timeout" in data_quality, never silently).
_FETCH_ORDER = ("volatility", "rates", "indices")

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

# A-share indices need the akshare CN batch (deferred to a later PR); phase 1
# keeps the best-effort FTSE A50 via yfinance only (探测失败记 not_supported).
_CN_YF_BEST_EFFORT_INDICES: Dict[str, Tuple[str, str]] = {
    "CHA50CFD": ("CHA50CFD", "富时中国A50期货"),
}

_GLOBAL_SYMBOLS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "volatility": {"VIX": ("^VIX", "VIX恐慌指数")},
    "rates": {"US10Y": ("^TNX", "美债10年期收益率")},  # ^TNX Close is already a percent yield; no scaling
}

_YF_MAX_SYMBOLS_PER_GROUP = 8


def _coerce_date_value(value) -> Optional[date]:
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


def _index_label_date(value) -> Any:
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


def _change_pct(last: float, prev: Optional[float]) -> Optional[float]:
    if prev is None or prev == 0:
        return None
    # OR-COR-be3a04e3: an overflow (huge ratio) or NaN input must not leak a
    # non-finite change_pct into votes / summary / quality / cache.
    change = (last - prev) / prev * 100.0
    if not math.isfinite(change):
        return None
    return round(change, 2)


def _filter_close_to_target(close, trade_date: date):
    """OR-COR-d20b0d9f: drop bars dated AFTER the analysis target date.

    - Rows whose label parses to a date on/before ``trade_date`` are kept
      (the last of them becomes the selected bar).
    - Dated rows after the target are dropped: newer-than-target data must
      never be presented as target-day data (e.g. a Monday bar during a US
      Monday session whose ``effective_daily_bar_date`` is last Friday, or a
      frozen run targeting a past date reading execution-time bars).
    - Rows with undatable labels are ignored when any dated row qualifies;
      when NO row is datable the original series is returned so quality
      degrades through ``as_of=None`` / ``stale=True`` (fail-open, unchanged
      legacy behaviour).
    - Returns ``None`` when every dated row lies after the target: the
      provider window holds no target-aligned bar, so the caller surfaces
      ``no_data`` instead of fresh target-day context.
    """

    keep: list = []
    undated: list = []
    total = 0
    for pos, label in enumerate(close.index):
        total += 1
        row_date = _coerce_date_value(_index_label_date(label))
        if row_date is None:
            undated.append(pos)
        elif row_date <= trade_date:
            keep.append(pos)
    if keep:
        return close.iloc[keep]
    if undated and len(undated) == total:
        return close
    return None


class CrossAssetFetcher:
    """Never-raising cross-asset snapshot reader with a cooperative budget."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        stale_days: int = 2,
    ) -> None:
        try:
            self._timeout_seconds = max(1.0, float(timeout_seconds))
        except (TypeError, ValueError):
            self._timeout_seconds = 8.0
        try:
            self._stale_days = max(0, int(stale_days))
        except (TypeError, ValueError):
            self._stale_days = 2

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_market_snapshot(
        self,
        market: str,
        trade_date: date,
    ) -> Dict[str, Dict[str, CrossAssetItem]]:
        """Return {group: {key: CrossAssetItem}} for one market/day.

        Never raises; every failure is encoded on the item itself. Deferred
        groups (fx/commodities/crypto) come back as empty dicts in phase 1.
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
        if group in ("volatility", "rates"):
            return self._fetch_symbol_group(market, group, trade_date, deadline)
        return {}

    def _fetch_indices(
        self, market: str, trade_date: date, deadline: float
    ) -> Dict[str, CrossAssetItem]:
        items: Dict[str, CrossAssetItem] = {}
        if market == "cn":
            table = _CN_YF_BEST_EFFORT_INDICES
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
        # VIX uses the 48h-style stale_days threshold.
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
            series = self._fetch_yf_series(symbol, trade_date)
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
    def _fetch_yf_series(symbol: str, trade_date: date) -> Optional[Tuple[date, float, float]]:
        """Return (as_of, last_close, prev_close) or None; may raise.

        ``trade_date`` is the analysis target date (the pipeline's
        ``effective_daily_bar_date``). OR-COR-d20b0d9f: only bars on/before
        the target may be selected — the previous last-row-of-5d selection
        let a bar AFTER the target (e.g. Monday data while the target is last
        Friday, or a frozen run targeting a past date) masquerade as fresh
        target-day context and then vote / enter the prompt.
        """

        import yfinance as yf

        if isinstance(trade_date, datetime):
            trade_date = trade_date.date()
        elif not isinstance(trade_date, date):
            trade_date = date.today()

        ticker = yf.Ticker(symbol)
        history = ticker.history(period="5d", auto_adjust=False)
        if history is None or getattr(history, "empty", True) or "Close" not in history:
            return None
        close = history["Close"].dropna()
        if close.empty:
            return None
        close = _filter_close_to_target(close, trade_date)
        if close is None or close.empty:
            return None
        last_index = close.index[-1]
        as_of = _coerce_date_value(_index_label_date(last_index))
        last = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) > 1 else last
        # OR-COR-be3a04e3: dropna() only removes NaN — +/-inf closes SURVIVE
        # it and used to become status="ok" items with value=inf that voted,
        # entered the summary/quality stats and were cached. Reject the bar
        # pair at the data-entry seam instead.
        if not math.isfinite(last) or not math.isfinite(prev):
            return None
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
        age_days = (trade_date - as_of).days
        if age_days < 0:
            # OR-COR-d20b0d9f: a bar dated AFTER the target can never be
            # "fresh" — the former negative-diff check read it as fresh.
            return True
        return age_days > max(0, int(threshold_days))

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
                names: Dict[str, str] = {
                    key: value[1] for key, value in _CN_YF_BEST_EFFORT_INDICES.items()
                }
            else:
                names = {key: value[1] for key, value in _YF_INDEX_SYMBOLS.get(market, {}).items()}
        else:
            names = {key: value[1] for key, value in _GLOBAL_SYMBOLS.get(group, {}).items()}
        return {key: self._timeout_item(name=name, trade_date=trade_date) for key, name in names.items()}
