"""Compute and store the stage-one A-share closing snapshot."""

from collections import Counter
from datetime import date, time, timedelta
import json
import math
from numbers import Integral, Real

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from data_provider import DataFetcherManager
from data_provider.market_sentiment import PROVIDER, LimitPoolUnavailable, fetch_limit_pool
from src.core.trading_calendar import get_market_now, get_trading_dates
from src.storage import MarketSentimentSnapshot


MARKET = "cn"
DEFINITION_VERSION = "a-share-limit-pool-v1"
_MARKET_CLOSE = time(15)
_BREADTH_FIELDS = ("advancing_count", "declining_count", "unchanged_count", "advancing_ratio", "turnover_yuan")


class SentimentCalendarUnavailable(ValueError):
    """Trading dates could not be verified."""


def trading_sessions(start: date, end: date) -> list[date]:
    sessions = get_trading_dates(MARKET, start, end)
    if sessions is None:
        raise SentimentCalendarUnavailable("A-share trading calendar is unavailable")
    return [session.date() for session in sessions]


def latest_closed_session() -> date:
    now = get_market_now(MARKET)
    end = now.date() - timedelta(days=now.time() < _MARKET_CLOSE)
    sessions = trading_sessions(end - timedelta(days=45), end)
    if not sessions:
        raise SentimentCalendarUnavailable("No completed A-share session found")
    return sessions[-1]


def get_snapshot(session, trade_date: date):
    return session.get(MarketSentimentSnapshot, (MARKET, trade_date))


def list_snapshots(session, end: date, *, start: date | None = None, limit: int):
    statement = select(MarketSentimentSnapshot).where(
        MarketSentimentSnapshot.market == MARKET, MarketSentimentSnapshot.trade_date <= end,
    )
    if start is not None:
        statement = statement.where(MarketSentimentSnapshot.trade_date >= start)
    return session.scalars(statement.order_by(MarketSentimentSnapshot.trade_date.desc()).limit(limit)).all()


def snapshot_data(record: MarketSentimentSnapshot) -> dict:
    payload = json.loads(record.payload)
    market_stats = payload.get("provider_trace", {}).get("market_stats", {})
    if market_stats.get("status") in ("available", "partial") and not market_stats.get("collected_at"):
        # Older snapshots could have used the shared intraday cache.
        payload["metrics"].update(dict.fromkeys(_BREADTH_FIELDS))
        payload["quality_status"] = "partial"
        market_stats["status"] = "freshness_unverified"
    return {
        "market": record.market, "trade_date": record.trade_date.isoformat(),
        "created_at": record.created_at.isoformat(), **payload,
    }


def _market_breadth(trade_date: date) -> tuple[dict, dict]:
    metrics = dict.fromkeys(_BREADTH_FIELDS)
    # The upstream stats chain supplies live aggregates without a session date.
    # Only use it within the requested local day, after the market has closed.
    requested_at = get_market_now(MARKET)
    if requested_at.date() != trade_date or requested_at.time() < _MARKET_CLOSE:
        return metrics, {"status": "not_available_for_session"}
    try:
        stats = DataFetcherManager().get_market_stats(
            purpose="market_sentiment", include_provider=True, allow_cache=False,
        )
    except Exception:
        return metrics, {"status": "source_unavailable"}
    collected_at = get_market_now(MARKET)
    if collected_at.date() != trade_date or collected_at < requested_at or not stats:
        return metrics, {"status": "source_unavailable"}
    counts = [stats.get(key) for key in ("up_count", "down_count", "flat_count")]
    if all(isinstance(n, Integral) and not isinstance(n, bool) and n >= 0 for n in counts) and sum(counts) > 0:
        metrics.update(zip(("advancing_count", "declining_count", "unchanged_count"), map(int, counts)))
        metrics["advancing_ratio"] = counts[0] / sum(counts)
    amount = stats.get("total_amount")
    if (isinstance(amount, Real) and not isinstance(amount, bool)
            and 0 < amount <= 1e10 and math.isfinite(amount)):
        metrics["turnover_yuan"] = float(amount) * 1e8
    return metrics, {
        "provider": stats.get("provider"),
        "status": "available" if all(value is not None for value in metrics.values()) else "partial",
        "requested_at": requested_at.isoformat(),
        "collected_at": collected_at.isoformat(),
        "session_date_verified": False,
    }


def compute_snapshot(trade_date: date, previous_date: date) -> dict:
    pools = {}
    pool_status = {}
    response_dates = {}
    for key, kind, day in (
        ("closed", "closed", trade_date), ("broken", "broken", trade_date),
        ("previous", "previous", trade_date), ("previous_closed", "closed", previous_date),
        ("down", "down", trade_date),
    ):
        try:
            if key == "previous_closed":
                pool = fetch_limit_pool(kind, day, corroborate_for=trade_date)
            else:
                pool = fetch_limit_pool(kind, day)
            pools[key] = pool.boards
            response_dates[key] = pool.response_date.isoformat()
            pool_status[key] = "available"
        except LimitPoolUnavailable:
            pools[key] = None
            pool_status[key] = "source_unavailable"

    closed, broken = pools["closed"], pools["broken"]
    candidates, previous_closed, down = pools["previous"], pools["previous_closed"], pools["down"]
    pool_overlap = closed is not None and broken is not None and bool(closed.keys() & broken.keys())
    if pool_overlap:
        pool_status["broken"] = "overlaps_closed"
        broken = None
    board_verified = (
        closed is not None and candidates is not None and candidates == previous_closed
        and all(board == candidates.get(code, 0) + 1 for code, board in closed.items())
    )
    promotions = {}
    if board_verified:
        for label, group in (("1_to_2", 1), ("2_to_3", 2), ("3_to_4", 3), ("4_plus", 4)):
            cohort = {code for code, board in candidates.items() if board == group or (group == 4 and board >= 4)}
            promoted = len(cohort & closed.keys())
            promotions[label] = {
                "numerator": promoted, "denominator": len(cohort),
                "rate": promoted / len(cohort) if cohort else None,
            }
    total_touched = len(closed) + len(broken) if closed is not None and broken is not None else None
    breadth, breadth_trace = _market_breadth(trade_date)
    if closed is None and all(value is None for value in breadth.values()):
        raise LimitPoolUnavailable("No verified closing pool or usable market statistics")
    return {
        "definition_version": DEFINITION_VERSION,
        "quality_status": "complete" if (
            board_verified and broken is not None and down is not None and breadth_trace["status"] == "available"
        ) else "partial",
        "metrics": {
            "limit_up_count": len(closed) if closed is not None else None,
            "limit_down_count": len(down) if down is not None else None,
            "break_rate": len(broken) / total_touched if total_touched else None,
            "broken_count": len(broken) if broken is not None else None,
            "touched_count": total_touched,
            "max_consecutive": max(closed.values(), default=0) if board_verified else None,
            "limit_up_ladder": dict(Counter(closed.values())) if board_verified else None,
            "promotions": promotions if board_verified else None,
            **breadth,
        },
        "provider_trace": {
            "limit_pools": {"provider": PROVIDER, **pool_status, "response_dates": response_dates},
            "market_stats": breadth_trace,
        },
        "completeness": {
            "board_verified": board_verified,
            "previous_closed_date_verified": response_dates.get("previous_closed") == previous_date.isoformat(),
            "broken_pool_verified": broken is not None,
        },
    }


def generate_snapshot(database, trade_date: date, previous_date: date) -> dict:
    summary = {"trade_date": trade_date.isoformat()}
    with database.session_scope() as session:
        existing = get_snapshot(session, trade_date)
        if existing is not None:
            return {**summary, "action": "unchanged", "quality_status": snapshot_data(existing)["quality_status"]}
    payload = compute_snapshot(trade_date, previous_date)
    try:
        with database.session_scope() as session:
            session.add(MarketSentimentSnapshot(market=MARKET, trade_date=trade_date, payload=json.dumps(payload)))
    except IntegrityError:
        with database.session_scope() as session:
            existing = get_snapshot(session, trade_date)
            if existing is None:
                raise
            return {**summary, "action": "unchanged", "quality_status": snapshot_data(existing)["quality_status"]}
    return {**summary, "action": "inserted", "quality_status": payload["quality_status"]}
