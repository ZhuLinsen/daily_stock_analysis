"""DB-first K-line history loader for Agent tools.

Provides:
- ContextVar-based frozen target_date propagation across threads
- ``load_history_df``: read from DB first, DataFetcherManager fallback

Fixes #1066 – eliminates 45+ redundant HTTP requests per stock in Agent mode.
"""
from __future__ import annotations

import contextvars
import logging
from datetime import date, datetime, timedelta
from threading import Lock
from typing import Any, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)
_CACHE_MIN_RECORDS = 30


class HistoryIdentityError(ValueError):
    """A strict tool identity cannot be preserved by the history read path."""

# ---------------------------------------------------------------------------
# Frozen target date (ContextVar) – set once per stock in pipeline, read by
# all agent tool threads via copy_context().run().
# ---------------------------------------------------------------------------
_frozen_target_date: contextvars.ContextVar[Optional[date]] = contextvars.ContextVar(
    "_frozen_target_date", default=None,
)


def set_frozen_target_date(d: date) -> contextvars.Token:
    return _frozen_target_date.set(d)


def get_frozen_target_date() -> Optional[date]:
    return _frozen_target_date.get()


def reset_frozen_target_date(token: contextvars.Token) -> None:
    _frozen_target_date.reset(token)


# ---------------------------------------------------------------------------
# Internal DataFetcherManager singleton (fallback only)
# ---------------------------------------------------------------------------
_fetcher_singleton = None
_fetcher_lock = Lock()


def _get_fetcher_manager():
    global _fetcher_singleton
    if _fetcher_singleton is None:
        with _fetcher_lock:
            if _fetcher_singleton is None:
                from data_provider import DataFetcherManager
                _fetcher_singleton = DataFetcherManager()
    return _fetcher_singleton


# ---------------------------------------------------------------------------
# DB-first history loader
# ---------------------------------------------------------------------------
def _history_code_candidates(stock_code: str, stock_identity=None) -> Tuple[List[str], str]:
    from data_provider.base import canonical_stock_code, normalize_stock_code
    from src.services.stock_list_parser import ParseStatus, parse_analysis_target

    raw_code = str(stock_code or "").strip()
    if stock_identity is not None:
        if raw_code != stock_identity.stock_code:
            raise HistoryIdentityError("History identity does not match the bound tool code")
        return [stock_identity.stock_code], stock_identity.stock_code
    target = parse_analysis_target(raw_code)
    if target.asset_type == ParseStatus.INDEX:
        # Explicit index identities keep their canonical bucket (``sh000016``
        # / ``csi930955``) so index bars never land in the colliding stock
        # bucket (Story 1.5).
        return [target.canonical_id], target.canonical_id
    normalized_code = canonical_stock_code(normalize_stock_code(raw_code))
    candidates: List[str] = []
    for candidate in (canonical_stock_code(raw_code), normalized_code):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates, normalized_code


def _coerce_bar_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return date.min
    if hasattr(value, "date"):
        try:
            coerced = value.date()
            return coerced if isinstance(coerced, date) else date.min
        except Exception:
            return date.min
    return date.min


def _bar_date(bar: Any) -> date:
    row_date = _coerce_bar_date(getattr(bar, "date", None))
    if row_date != date.min:
        return row_date
    if hasattr(bar, "to_dict"):
        try:
            return _coerce_bar_date((bar.to_dict() or {}).get("date"))
        except Exception:
            return date.min
    return date.min


def _select_best_bars(db, stock_code: str, start: date, end: date, stock_identity=None) -> Tuple[Optional[str], list]:
    candidates, normalized_code = _history_code_candidates(stock_code, stock_identity)
    best_code = None
    best_bars = []
    best_key = None

    for candidate in candidates:
        bars = list(db.get_data_range(candidate, start, end) or [])
        if not bars:
            continue
        latest_date = max(_bar_date(bar) for bar in bars)
        key = (latest_date, len(bars), candidate == normalized_code)
        if best_key is None or key > best_key:
            best_key = key
            best_code = candidate
            best_bars = bars

    return best_code, best_bars


def load_history_df(
    stock_code: str,
    days: int = 60,
    target_date: Optional[date] = None,
    *,
    min_records: Optional[int] = None,
) -> Tuple[Optional[pd.DataFrame], str]:
    """Load K-line history, DB first with DataFetcherManager fallback.

    Returns ``(df, source)`` where *source* is ``"db_cache"`` on DB hit or the
    actual provider name on network fallback.  Returns ``(None, "none")`` when
    both paths fail.
    """
    from src.storage import get_db
    from src.agent.tools.execution import get_tool_stock_identity, get_tool_analysis_target

    # Resolve before the cache/provider exception boundaries. A lost strict
    # binding is not a cache miss and must never enter untyped fallback.
    identity = get_tool_stock_identity(stock_code)
    analysis_target = get_tool_analysis_target(stock_code)

    # Resolve effective end date
    if target_date is not None:
        end = target_date
    else:
        frozen = get_frozen_target_date()
        end = frozen if frozen else date.today()

    # Calendar-day buffer: ~1.8x trading days + margin for long holidays
    start = end - timedelta(days=int(days * 1.8) + 10)
    db_df: Optional[pd.DataFrame] = None
    db_latest_date = date.min

    # --- 1. DB lookup (canonical code, then prefix-stripped fallback) ------
    try:
        db = get_db()
        _code, bars = _select_best_bars(db, stock_code, start, end, identity)
        min_threshold = min_records if min_records is not None else _CACHE_MIN_RECORDS
        required_records = max(min(days, min_threshold), 1)
        latest_date = max((_bar_date(bar) for bar in bars), default=date.min)
        if bars:
            db_df = pd.DataFrame([b.to_dict() for b in bars])
            db_latest_date = latest_date
        if bars and latest_date >= end and len(bars) >= required_records:
            logger.debug(
                "load_history_df(%s): %d bars from DB (requested %d)",
                stock_code, len(db_df), days,
            )
            return db_df, "db_cache"
    except HistoryIdentityError:
        raise
    except Exception as e:
        logger.debug("load_history_df(%s): DB read failed: %s", stock_code, e)

    # --- 2. Network fallback via singleton DataFetcherManager -------------
    fallback_kwargs = {}
    if identity is not None:
        fallback_kwargs["analysis_target"] = analysis_target
    try:
        manager = _get_fetcher_manager()
        df, source = manager.get_daily_data(
            stock_code,
            end_date=end.isoformat(),
            days=days,
            **fallback_kwargs,
        )
        if df is not None and not df.empty:
            fetched_latest_date = date.min
            if "date" in df.columns:
                parsed_dates = pd.to_datetime(df["date"], errors="coerce").dt.date
                if bool((parsed_dates.notna() & (parsed_dates > end)).any()):
                    df = df[parsed_dates.isna() | (parsed_dates <= end)].reset_index(drop=True)
                    parsed_dates = (
                        pd.to_datetime(df["date"], errors="coerce").dt.date
                        if not df.empty
                        else pd.Series([], dtype="object")
                    )
                valid_dates = parsed_dates.dropna()
                if not valid_dates.empty:
                    fetched_latest_date = valid_dates.max()
            if not df.empty and (
                db_df is None
                or (fetched_latest_date, len(df)) >= (db_latest_date, len(db_df))
            ):
                return df, source
    except Exception as e:
        logger.warning("load_history_df(%s): DataFetcherManager failed: %s", stock_code, e)

    if db_df is not None and not db_df.empty:
        return db_df, ("db_cache" if db_latest_date >= end else "db_cache_stale")

    return None, "none"
