"""Manual snapshot tasks and read-only A-share sentiment history."""

from datetime import date, timedelta
import logging
from threading import Lock

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.deps import get_database_manager, get_db
from api.v1.errors import api_error
from api.v1.schemas.analysis import TaskStatusEnum
from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.market_sentiment import (
    MarketSentimentAccepted,
    MarketSentimentSnapshotList,
    MarketSentimentSnapshotResponse,
    MarketSentimentTaskStatus,
    MarketSentimentTrend,
)
from data_provider.market_sentiment import LimitPoolUnavailable
from src.services import market_sentiment as sentiment
from src.services.task_queue import get_task_queue
from src.storage import DatabaseManager


router = APIRouter(responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
logger = logging.getLogger(__name__)
_GENERATION_LOCK = Lock()
_TASK_TYPE = "market_sentiment_snapshot"
_ACCEPTED_MESSAGE = "A-share sentiment snapshot task submitted"
_CALENDAR_ERROR = {"model": ErrorResponse, "description": "A-share trading calendar is unavailable"}


def _check_end_date(end_date: date | None) -> date:
    try:
        latest = sentiment.latest_closed_session()
    except sentiment.SentimentCalendarUnavailable as exc:
        raise api_error(503, "trade_calendar_unavailable", str(exc)) from exc
    if end_date is not None and end_date > latest:
        raise api_error(422, "invalid_trade_date", "Date is after the latest completed A-share session")
    return end_date or latest


@router.post(
    "/snapshots", status_code=202, response_model=MarketSentimentAccepted,
    responses={409: {"model": ErrorResponse}, 503: _CALENDAR_ERROR},
)
def trigger_snapshot(
    trade_date: date | None = None, database: DatabaseManager = Depends(get_database_manager),
) -> MarketSentimentAccepted:
    target = _check_end_date(None)
    if trade_date is not None and trade_date != target:
        raise api_error(422, "invalid_trade_date", "Only the latest completed A-share session can be generated")
    try:
        earlier = sentiment.trading_sessions(target - timedelta(days=45), target - timedelta(days=1))
    except sentiment.SentimentCalendarUnavailable as exc:
        raise api_error(503, "trade_calendar_unavailable", str(exc)) from exc
    if not earlier:
        raise api_error(503, "trade_calendar_unavailable", "Previous A-share session is unavailable")
    if not _GENERATION_LOCK.acquire(blocking=False):
        raise api_error(409, "market_sentiment_in_progress", "A sentiment snapshot task is already running")

    def run() -> dict:
        try:
            return sentiment.generate_snapshot(database, target, earlier[-1])
        except LimitPoolUnavailable:
            raise
        except Exception as exc:
            logger.error("Sentiment snapshot failed for %s (%s)", target, type(exc).__name__)
            raise RuntimeError("Unable to store or compute the sentiment snapshot") from exc
        finally:
            _GENERATION_LOCK.release()

    try:
        task = get_task_queue().submit_background_task(
            run, stock_code="market_sentiment", stock_name="A-share sentiment",
            report_type=_TASK_TYPE, region=sentiment.MARKET, message=_ACCEPTED_MESSAGE,
        )
    except Exception:
        _GENERATION_LOCK.release()
        raise
    return MarketSentimentAccepted(
        task_id=task.task_id, trace_id=task.trace_id or task.task_id,
        message=_ACCEPTED_MESSAGE, trade_date=target,
    )


@router.get("/tasks/{task_id}", response_model=MarketSentimentTaskStatus, responses={404: {"model": ErrorResponse}})
def get_snapshot_task(task_id: str) -> dict:
    task = get_task_queue().get_task(task_id)
    if task is None or task.report_type != _TASK_TYPE:
        raise api_error(404, "market_sentiment_task_not_found", "Sentiment task not found")
    return {
        "task_id": task.task_id, "trace_id": task.trace_id or task.task_id,
        "status": task.status, "progress": task.progress, "message": task.message,
        "result": task.result if task.status == TaskStatusEnum.COMPLETED else None,
        "error": task.error,
    }


@router.get("/snapshots", response_model=MarketSentimentSnapshotList, responses={503: _CALENDAR_ERROR})
def get_snapshots(
    end_date: date | None = None, limit: int = Query(30, ge=1, le=120), session: Session = Depends(get_db),
) -> dict:
    end = _check_end_date(end_date)
    return {"items": [sentiment.snapshot_data(row) for row in sentiment.list_snapshots(session, end, limit=limit)]}


@router.get(
    "/snapshots/{trade_date}", response_model=MarketSentimentSnapshotResponse,
    responses={404: {"model": ErrorResponse}, 503: _CALENDAR_ERROR},
)
def get_snapshot(trade_date: date, session: Session = Depends(get_db)) -> dict:
    _check_end_date(trade_date)
    record = sentiment.get_snapshot(session, trade_date)
    if record is None:
        raise api_error(404, "market_sentiment_snapshot_not_found", "Sentiment snapshot not found")
    return sentiment.snapshot_data(record)


@router.get("/trend", response_model=MarketSentimentTrend, responses={503: _CALENDAR_ERROR})
def get_trend(
    end_date: date, limit: int = 30, session: Session = Depends(get_db),
) -> dict:
    target = _check_end_date(end_date)
    if limit not in (10, 30, 60):
        raise api_error(422, "invalid_trend_window", "Use a 10, 30 or 60 trading-session window")
    if target.toordinal() <= 180:
        raise api_error(422, "invalid_trade_date", "Target does not have a full trading-session window")
    try:
        calendar = sentiment.trading_sessions(target - timedelta(days=180), target)
    except sentiment.SentimentCalendarUnavailable as exc:
        raise api_error(503, "trade_calendar_unavailable", str(exc)) from exc
    if not calendar or calendar[-1] != target or len(calendar) <= limit:
        raise api_error(422, "invalid_trade_date", "Target is not a session or has no full trading-session window")

    dates = calendar[-limit - 1:-1]
    records = {
        row.trade_date: sentiment.snapshot_data(row)
        for row in sentiment.list_snapshots(session, dates[-1], start=dates[0], limit=180)
    }
    target_record = sentiment.get_snapshot(session, target)
    anchor = sentiment.snapshot_data(target_record) if target_record else next(
        (records[day] for day in reversed(dates) if day in records), None,
    )
    definition_version = anchor["definition_version"] if anchor else None
    incompatible = [
        day for day in dates if day in records and records[day]["definition_version"] != definition_version
    ]
    return {
        "end_date": target, "window_sessions": limit, "definition_version": definition_version,
        "session_dates": dates,
        "missing_dates": [day for day in dates if day not in records],
        "different_definition_dates": incompatible,
        "items": [records[day] for day in dates if day in records and day not in incompatible],
    }
