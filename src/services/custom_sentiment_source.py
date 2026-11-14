"""Operator-configured adapters for manual A-share sentiment snapshots."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re

from src.data.csmar_daily import CsmarDataset, CsmarDay, CsmarSourceError
from src.repositories.sentiment_repo import SentimentRepository
from src.services.sentiment_calendar import validate_and_pad_history
from src.services.sentiment_snapshot_service import compute_snapshot


SOURCE_ID = r"[a-z][a-z0-9_-]{0,31}"
CUSTOM_SOURCE_PREFIX = "custom:"
MARKET_TZ = timezone(timedelta(hours=8))
SOURCE_PATTERN = rf"^(eastmoney|csmar|{CUSTOM_SOURCE_PREFIX}{SOURCE_ID})$"


@dataclass(frozen=True)
class CustomSentimentDay:
    closed: tuple[str, ...]
    touched: tuple[str, ...]


@dataclass(frozen=True)
class CustomSentimentData:
    scope: str
    revision: str
    days: dict[date, CustomSentimentDay]


class CustomSourceNotConfigured(ValueError):
    """The requested adapter is not enabled by the server operator."""


def register_sentiment_source(app, source_id: str, adapter: Callable[[date], CustomSentimentData]) -> None:
    """Register a preinstalled adapter from trusted application startup code."""
    if re.fullmatch(SOURCE_ID, source_id) is None or not callable(adapter):
        raise ValueError("Invalid sentiment source ID or adapter")
    sources = getattr(app.state, "sentiment_sources", {})
    if source_id in sources:
        raise ValueError("Sentiment source is already registered")
    app.state.sentiment_sources = {**sources, source_id: adapter}


def custom_market(source: str) -> str:
    return "CN_A_CUSTOM:" + source.removeprefix(CUSTOM_SOURCE_PREFIX)


def _pool_codes(codes: tuple[str, ...]) -> set[str]:
    if not isinstance(codes, tuple) or any(
        not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None
        for code in codes
    ):
        raise CsmarSourceError("Custom source must supply six-digit stock codes")
    unique = set(codes)
    if len(unique) != len(codes):
        raise CsmarSourceError("Custom source supplied duplicate stock codes")
    return unique


def _build_snapshot(data: CustomSentimentData, source: str, trade_date: date) -> dict:
    if (
        not isinstance(data, CustomSentimentData)
        or not isinstance(data.scope, str) or not 0 < len(data.scope.strip()) <= 160
        or not data.scope.isprintable()
        or not isinstance(data.revision, str) or re.fullmatch(SOURCE_ID, data.revision) is None
        or not isinstance(data.days, dict)
    ):
        raise CsmarSourceError("Custom source returned invalid scope, revision or history")
    if any(type(day) is not date or day > trade_date for day in data.days):
        raise CsmarSourceError("Custom source returned invalid dates or data after the target date")
    if trade_date not in data.days:
        raise CsmarSourceError("Custom source has no data for the target session")

    scope = data.scope.strip()
    days = {}
    inputs = []
    for day, pools in sorted(data.days.items()):
        if not isinstance(pools, CustomSentimentDay):
            raise CsmarSourceError("Custom source returned invalid daily pools")
        closed, touched = _pool_codes(pools.closed), _pool_codes(pools.touched)
        if not closed <= touched:
            raise CsmarSourceError("Custom source closed pool must be a subset of the touched pool")
        days[day] = CsmarDay(closed=closed, touched=touched, broken=touched - closed)
        inputs.append((day.isoformat(), sorted(closed), sorted(touched)))

    payload = json.dumps([scope, data.revision, inputs], separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    scope_key = hashlib.sha256(scope.encode()).hexdigest()[:12]
    # Reuse the existing market-session and pool-based metric implementation.
    dataset = CsmarDataset(days, digest, "", 0, "", "A1:B1", 2)
    validate_and_pad_history(dataset, trade_date)
    snapshot = compute_snapshot(dataset, trade_date)
    completeness = snapshot["completeness"]
    snapshot.update(
        market=custom_market(source),
        definition_version=f"custom-pool-v1:{data.revision}:{scope_key}",
        provider_trace={"provider": source, "as_of_sha256": digest},
        completeness={
            "scope": scope,
            "date_min": completeness["date_min"],
            "date_max": completeness["date_max"],
            "date_count": completeness["date_count"],
            "source_issues_through_target": completeness["source_issues_through_target"],
            "streak_not_cut_by_source_start": completeness["streak_not_cut_by_source_start"],
            "prior_streak_available": completeness["prior_streak_available"],
        },
    )
    return snapshot


def generate_custom_snapshot(session, *, source: str, sources: dict, trade_date: date):
    adapter = sources.get(source.removeprefix(CUSTOM_SOURCE_PREFIX))
    if adapter is None:
        raise CustomSourceNotConfigured("Requested custom sentiment source is not configured")
    now = datetime.now(MARKET_TZ)
    if trade_date > now.date() or (trade_date == now.date() and now.hour < 15):
        raise CsmarSourceError("Custom sentiment requires a completed trading session")
    try:
        data = adapter(trade_date)
    except Exception as exc:
        # Adapter errors may include credentials, URLs or local file paths.
        raise CsmarSourceError("Custom sentiment adapter failed") from exc
    return SentimentRepository(session).save(_build_snapshot(data, source, trade_date))
