# -*- coding: utf-8 -*-
"""Pure metric functions for market sentiment snapshots (issue #1939 Wave 3).

Zero IO / zero network: every function takes DataFrames or plain dicts
(already fetched) and returns a payload-section dict per plan §3.2.
Calibre rules follow plan §2 as finalized by the Wave 1 probe
(akshare 1.18.97, see ``.omz/research/.../w1-probe/conclusions.md``):

- Limit-up pool keeps the full eastmoney universe (ST / BSE / new stocks are
  NOT removed); the breakdown ``st_count`` / ``bse_count`` / ``new_stock_count``
  is attached instead (W1 §2 verdict).
- M12 is close-based via previous_em's ``涨跌幅`` column; the M13 auction
  sub-block is omitted with ``auction_missing_reason='field_unavailable'``
  (previous_em has no auction/open fields — W1 §1 verdict).
- Missing discipline: never zero-fill. ``None`` inputs (fetch failed) ->
  values ``None`` + ``missing_reason='source_error'``; zero denominators ->
  ``None`` + ``'zero_denominator'`` (M2 ratio, M7 rate, M10 per board,
  M11 overall); empty pool where a max makes no sense -> ``'empty_pool'``
  (M8); cold-start turnover MoM -> ``'missing_prev'``.
- Beyond-retention pool dates surface as silent empty DataFrames (W1 §3);
  the fetcher layer judges them by row count and hands ``None`` to these
  functions — an empty-but-valid pool (0 limit-down stocks) is passed
  through as an empty DataFrame and reported as 0, not as missing.

Expected-missing reasons (``zero_denominator`` / ``empty_pool`` /
``missing_prev`` / ``field_unavailable``) do NOT downgrade a group's
metric_status; only ``source_error`` does.
"""

from typing import Any, Dict, Mapping, Optional, Tuple

import pandas as pd

from data_provider.base import is_bse_code, is_st_stock

# --- missing_reason vocabulary (payload contract, §2/§3.2) ---
ZERO_DENOMINATOR = "zero_denominator"
EMPTY_POOL = "empty_pool"
SOURCE_ERROR = "source_error"
MISSING_PREV = "missing_prev"
FIELD_UNAVAILABLE = "field_unavailable"

# --- group taxonomy (must stay in sync with market_sentiment_repo) ---
REQUIRED_GROUPS: Tuple[str, ...] = (
    "breadth",
    "limit_up_pool",
    "broken_pool",
    "turnover",
    "promotion",
    "prev_feedback",
)
ENHANCED_GROUPS: Tuple[str, ...] = ("sector",)

POOL_UNIVERSE_NOTE = (
    "eastmoney 涨停池全量口径：不剔除 ST/北交所/新股，"
    "附 st_count/bse_count/new_stock_count 分解（W1 定案）"
)
BREADTH_UNIVERSE_NOTE = (
    "spot 全市场口径（东财→新浪 fallback，含北交/含ST），"
    "剔除停牌/价格缺失/成交额为 0；涨跌停为价差推算口径（仅交叉校验）"
)

_STATUS_OK = "ok"
_STATUS_SOURCE_ERROR = "source_error"


def _int_or_none(value: Any) -> Optional[int]:
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_new_listing(name: Any) -> bool:
    """New-listing flag per W1 probe calibre: name starts with 'N' or 'C'."""
    text = str(name or "").strip()
    return bool(text) and text[0] in ("N", "C")


def _pool_breakdown(df: Optional[pd.DataFrame]) -> Dict[str, int]:
    """st/bse/new-stock decomposition over a pool DataFrame (full universe)."""
    counts = {"st_count": 0, "bse_count": 0, "new_stock_count": 0, "rows": 0}
    if df is None or df.empty:
        return counts
    counts["rows"] = int(len(df))
    for name, code in zip(df.get("名称", pd.Series(dtype=object)),
                          df.get("代码", pd.Series(dtype=object))):
        if is_st_stock(name):
            counts["st_count"] += 1
        if is_bse_code(str(code or "").strip()):
            counts["bse_count"] += 1
        if _is_new_listing(name):
            counts["new_stock_count"] += 1
    return counts


def _board_series(df: pd.DataFrame) -> pd.Series:
    """Numeric 连板数 column, NaN dropped."""
    if "连板数" not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df["连板数"], errors="coerce").dropna()


def compute_breadth(stats: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """M1/M2 from ``get_market_stats()`` output (price-rule spot calibre).

    ``advance_decline_ratio`` is null with ``zero_denominator`` when
    ``down_count`` is 0 — that does not make the group fail (§2 M2).
    """
    if not stats:
        return {
            "up_count": None,
            "down_count": None,
            "flat_count": None,
            "sample_size": None,
            "advance_decline_diff": None,
            "advance_decline_ratio": None,
            "advance_decline_ratio_missing_reason": SOURCE_ERROR,
            "limit_up_count_by_price": None,
            "limit_down_count_by_price": None,
            "universe_note": BREADTH_UNIVERSE_NOTE,
            "missing_reason": SOURCE_ERROR,
        }
    up = _int_or_none(stats.get("up_count"))
    down = _int_or_none(stats.get("down_count"))
    flat = _int_or_none(stats.get("flat_count"))
    if up is None or down is None or flat is None:
        return compute_breadth(None)
    if down > 0:
        ratio = up / down
        ratio_reason: Optional[str] = None
    else:
        ratio = None
        ratio_reason = ZERO_DENOMINATOR
    return {
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "sample_size": up + down + flat,
        "advance_decline_diff": up - down,
        "advance_decline_ratio": ratio,
        "advance_decline_ratio_missing_reason": ratio_reason,
        "limit_up_count_by_price": _int_or_none(stats.get("limit_up_count")),
        "limit_down_count_by_price": _int_or_none(stats.get("limit_down_count")),
        "universe_note": BREADTH_UNIVERSE_NOTE,
        "missing_reason": None,
    }


def compute_limit_up_section(
    today_pool: Optional[pd.DataFrame],
    limit_down_pool: Optional[pd.DataFrame],
    stats: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """M3/M4/M8/M9 (+ ST/BSE/new breakdown) over today's pools.

    M4 prefers the dtgc pool; when the pool is unavailable it falls back to
    the price-rule value from spot stats (``limit_down_source='price_rule'``,
    §2 M4 fallback clause). An empty dtgc DataFrame is a valid 0-limit-down
    market state and reports 0 with the pool calibre.
    """
    section: Dict[str, Any] = {
        "count": None,
        "max_boards": None,
        "max_boards_missing_reason": None,
        "ladder": {},
        "limit_down_count": None,
        "limit_down_source": None,
        "limit_down_missing_reason": None,
        "st_count": 0,
        "bse_count": 0,
        "new_stock_count": 0,
        "pool_sample_size": None,
        "pool_universe_note": POOL_UNIVERSE_NOTE,
        "missing_reason": None,
    }
    if today_pool is None:
        section["missing_reason"] = SOURCE_ERROR
    else:
        boards = _board_series(today_pool)
        breakdown = _pool_breakdown(today_pool)
        section["count"] = int(len(today_pool))
        section["pool_sample_size"] = int(len(today_pool))
        section["st_count"] = breakdown["st_count"]
        section["bse_count"] = breakdown["bse_count"]
        section["new_stock_count"] = breakdown["new_stock_count"]
        ladder: Dict[str, int] = {}
        for board, group_size in boards[boards >= 2].value_counts().items():
            ladder[str(int(board))] = int(group_size)
        section["ladder"] = ladder
        if boards.empty:
            section["max_boards"] = None
            section["max_boards_missing_reason"] = EMPTY_POOL
        else:
            section["max_boards"] = int(boards.max())

    if limit_down_pool is not None:
        section["limit_down_count"] = int(len(limit_down_pool))
        section["limit_down_source"] = "pool"
    else:
        price_rule = _int_or_none((stats or {}).get("limit_down_count"))
        if price_rule is not None:
            section["limit_down_count"] = price_rule
            section["limit_down_source"] = "price_rule"
        else:
            section["limit_down_missing_reason"] = SOURCE_ERROR
    return section


def compute_broken_pool(
    broken_pool: Optional[pd.DataFrame],
    today_limit_up_count: Optional[int],
) -> Dict[str, Any]:
    """M7 broken-board rate: failed / (sealed + failed).

    ``today_limit_up_count`` is passed in separately (today's pool row count)
    because the denominator spans both pools (§2 M7: 当日曾封板家数).
    """
    if broken_pool is None:
        return {
            "failed_count": None,
            "failure_rate": None,
            "denominator": None,
            "missing_reason": SOURCE_ERROR,
        }
    failed = int(len(broken_pool))
    if today_limit_up_count is None:
        return {
            "failed_count": failed,
            "failure_rate": None,
            "denominator": None,
            "missing_reason": SOURCE_ERROR,
        }
    denominator = int(today_limit_up_count) + failed
    if denominator == 0:
        return {
            "failed_count": failed,
            "failure_rate": None,
            "denominator": 0,
            "missing_reason": ZERO_DENOMINATOR,
        }
    return {
        "failed_count": failed,
        "failure_rate": failed / denominator,
        "denominator": denominator,
        "missing_reason": None,
    }


def compute_promotion(
    today_pool: Optional[pd.DataFrame],
    prev_pool: Optional[pd.DataFrame],
    prev_pool_date: Optional[str],
) -> Dict[str, Any]:
    """M10 per-board promotion rates (N=2..today max board) and M11 overall.

    Per board N: rate = today N-board count / yesterday (N-1)-board count;
    denominator 0 -> that board is null + ``zero_denominator``. Overall:
    today boards>=2 count / yesterday pool rows.
    """
    section: Dict[str, Any] = {
        "by_board": {},
        "overall": {
            "rate": None,
            "numerator": None,
            "denominator": None,
            "missing_reason": None,
        },
        "prev_pool_date": prev_pool_date,
        "missing_reason": None,
    }
    today_boards = _board_series(today_pool) if today_pool is not None else None
    if today_boards is not None:
        today_counts = today_boards.value_counts()
        section["overall"]["numerator"] = int((today_boards >= 2).sum())
        section["overall"]["denominator"] = (
            int(len(prev_pool)) if prev_pool is not None else None
        )
        if section["overall"]["denominator"]:
            section["overall"]["rate"] = (
                section["overall"]["numerator"] / section["overall"]["denominator"]
            )
        elif section["overall"]["denominator"] == 0:
            section["overall"]["missing_reason"] = ZERO_DENOMINATOR
        if prev_pool is not None:
            prev_boards = _board_series(prev_pool)
            prev_counts = prev_boards.value_counts()
            max_board = int(today_boards.max()) if not today_boards.empty else 1
            by_board: Dict[str, Dict[str, Any]] = {}
            for n in range(2, max_board + 1):
                numerator = int(today_counts.get(n, 0))
                denominator = int(prev_counts.get(n - 1, 0))
                if denominator > 0:
                    by_board[str(n)] = {
                        "rate": numerator / denominator,
                        "numerator": numerator,
                        "denominator": denominator,
                        "missing_reason": None,
                    }
                else:
                    by_board[str(n)] = {
                        "rate": None,
                        "numerator": numerator,
                        "denominator": denominator,
                        "missing_reason": ZERO_DENOMINATOR,
                    }
            section["by_board"] = by_board
    if today_pool is None or prev_pool is None:
        section["missing_reason"] = SOURCE_ERROR
    return section


def compute_turnover(
    stats: Optional[Dict[str, Any]],
    prev_total_amount_yi: Optional[float],
) -> Dict[str, Any]:
    """M5 total amount + M6 MoM vs the snapshot table's previous record.

    Cold start (``prev_total_amount_yi`` None) -> ``mom_change_pct`` null +
    ``missing_prev`` (§2 M6; expected, does not fail the group).
    """
    if not stats:
        return {
            "total_amount_yi": None,
            "prev_total_amount_yi": prev_total_amount_yi,
            "mom_change_pct": None,
            "mom_missing_reason": SOURCE_ERROR,
            "prev_source": None,
            "missing_reason": SOURCE_ERROR,
        }
    total = _float_or_none(stats.get("total_amount"))
    if total is None:
        return compute_turnover(None, prev_total_amount_yi)
    mom: Optional[float] = None
    mom_reason: Optional[str] = None
    prev_source: Optional[str] = None
    if prev_total_amount_yi is None:
        mom_reason = MISSING_PREV
    elif float(prev_total_amount_yi) == 0.0:
        mom_reason = ZERO_DENOMINATOR
    else:
        mom = (total / float(prev_total_amount_yi) - 1.0) * 100.0
        prev_source = "snapshot_table"
    return {
        "total_amount_yi": total,
        "prev_total_amount_yi": (
            float(prev_total_amount_yi) if prev_total_amount_yi is not None else None
        ),
        "mom_change_pct": mom,
        "mom_missing_reason": mom_reason,
        "prev_source": prev_source,
        "missing_reason": None,
    }


def compute_prev_feedback(previous_pool: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """M12 yesterday-limit-up close feedback + M13 auction block placeholder.

    previous_em(date=T) holds T-1 limit-up stocks' performance on day T
    (W1 §1 reconciliation). No auction/open fields exist (W1 verdict), so the
    auction sub-block is always omitted with ``field_unavailable``.
    """
    section: Dict[str, Any] = {
        "sample_size": 0,
        "avg_change_pct": None,
        "median_change_pct": None,
        "red_ratio": None,
        "stats_missing_reason": None,
        "auction": None,
        "auction_missing_reason": FIELD_UNAVAILABLE,
        "missing_reason": None,
    }
    if previous_pool is None:
        section["missing_reason"] = SOURCE_ERROR
        return section
    if previous_pool.empty or "涨跌幅" not in previous_pool.columns:
        section["stats_missing_reason"] = EMPTY_POOL
        return section
    changes = pd.to_numeric(previous_pool["涨跌幅"], errors="coerce").dropna()
    sample_size = int(len(changes))
    section["sample_size"] = sample_size
    if sample_size == 0:
        section["stats_missing_reason"] = EMPTY_POOL
        return section
    section["avg_change_pct"] = float(changes.mean())
    section["median_change_pct"] = float(changes.median())
    section["red_ratio"] = float((changes > 0).sum()) / sample_size
    return section


def compute_sector_strength(
    rankings: Optional[Tuple[Any, Any]],
) -> Dict[str, Any]:
    """M14 industry sector Top5/Bottom5 (enhanced group, §2 M14)."""
    if not rankings:
        return {
            "top5": [],
            "bottom5": [],
            "missing_reason": SOURCE_ERROR,
        }
    top, bottom = rankings
    return {
        "top5": [dict(item) for item in list(top)[:5]],
        "bottom5": [dict(item) for item in list(bottom)[:5]],
        "missing_reason": None,
    }


def derive_metric_status(sections: Mapping[str, Dict[str, Any]]) -> Dict[str, str]:
    """Per-group metric_status (§3.2): 'ok' unless the group's data chain broke.

    A group is ``source_error`` only when its deciding missing_reason equals
    ``source_error``. Expected-missing reasons (zero_denominator / empty_pool /
    missing_prev / field_unavailable) leave the group 'ok' — the metric was
    produced honestly per the missing discipline.
    """
    status: Dict[str, str] = {}
    for group in list(REQUIRED_GROUPS) + list(ENHANCED_GROUPS):
        section = sections.get(group) or {}
        reason = section.get("missing_reason")
        if group == "limit_up_pool":
            reason = reason or section.get("limit_down_missing_reason")
        status[group] = _STATUS_SOURCE_ERROR if reason == SOURCE_ERROR else _STATUS_OK
    return status
