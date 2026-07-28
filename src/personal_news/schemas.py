"""Contracts for the personal news radar."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Direction(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    MIXED = "MIXED"
    UNCERTAIN = "UNCERTAIN"


class TimeHorizon(str, Enum):
    INTRADAY = "INTRADAY"
    ONE_TO_FIVE_DAYS = "ONE_TO_FIVE_DAYS"
    ONE_TO_THREE_MONTHS = "ONE_TO_THREE_MONTHS"
    LONG_TERM = "LONG_TERM"
    UNKNOWN = "UNKNOWN"


class Action(str, Enum):
    WATCH_NOW = "WATCH_NOW"
    WAIT_FOR_CONFIRMATION = "WAIT_FOR_CONFIRMATION"
    RISK_ALERT = "RISK_ALERT"
    AVOID_CHASING = "AVOID_CHASING"
    POTENTIAL_OPPORTUNITY = "POTENTIAL_OPPORTUNITY"
    NO_ACTION = "NO_ACTION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class Market(str, Enum):
    A_SHARE = "A_SHARE"
    HK = "HK"
    US = "US"


def parse_stock_symbol(value: str) -> tuple[str, Market]:
    symbol = (value or "").strip().upper()
    explicit_a_share = re.fullmatch(r"(?:(SH|SZ|BJ)[.]?)?(\d{6})(?:[.](SH|SZ|BJ))?", symbol)
    if explicit_a_share:
        prefix, digits, suffix = explicit_a_share.groups()
        exchange = suffix or prefix
        if exchange is None:
            if digits.startswith(("92", "43", "81", "82", "83", "87", "88")):
                exchange = "BJ"
            elif digits.startswith("6"):
                exchange = "SH"
            elif digits.startswith(("0", "2", "3")):
                exchange = "SZ"
            else:
                raise ValueError(f"cannot infer A-share exchange: {value}")
        return f"{digits}.{exchange}", Market.A_SHARE
    if re.fullmatch(r"(?:HK)?\d{5}(?:\.HK)?", symbol):
        digits = symbol.removeprefix("HK").removesuffix(".HK")
        return f"{digits}.HK", Market.HK
    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}(?:\.US)?", symbol):
        return symbol.removesuffix(".US"), Market.US
    raise ValueError(f"unsupported stock symbol: {value}")


class NewsAnalysis(BaseModel):
    """Strict, source-grounded model output."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=1200)
    direction: Direction
    confidence: int = Field(ge=0, le=100)
    time_horizon: TimeHorizon
    positive_factors: List[str]
    negative_factors: List[str]
    risks: List[str]
    action: Action
    action_reason: str = Field(min_length=1, max_length=1000)
    invalidation_conditions: List[str]
    source_urls: List[str]
    data_time: datetime

    @field_validator("source_urls")
    @classmethod
    def require_sources(cls, value: List[str]) -> List[str]:
        clean = list(dict.fromkeys(item.strip() for item in value if item and item.strip()))
        if not clean:
            raise ValueError("source_urls must contain at least one source")
        return clean

    @model_validator(mode="after")
    def require_balanced_factors(self) -> "NewsAnalysis":
        if not self.positive_factors or not self.negative_factors or not self.risks:
            raise ValueError("positive_factors, negative_factors, and risks are required")
        if not self.invalidation_conditions:
            raise ValueError("invalidation_conditions is required")
        return self


class NewsCandidate(BaseModel):
    """Normalized input emitted by any news source adapter."""

    model_config = ConfigDict(extra="allow")

    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=1000)
    source: str = Field(default="unknown", max_length=100)
    summary: str = ""
    published_at: Optional[datetime] = None
    symbols: List[str] = Field(default_factory=list)
    is_announcement: bool = False
    is_regulatory: bool = False
    source_reliability: int = Field(default=50, ge=0, le=100)
    source_count: int = Field(default=1, ge=1)
    price_change_percent: Optional[float] = None
    volume_change_percent: Optional[float] = None
    entity_confidence: int = Field(default=70, ge=0, le=100)
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: List[str]) -> List[str]:
        parsed = [parse_stock_symbol(item)[0] for item in value if item and item.strip()]
        return list(dict.fromkeys(parsed))


class NewsRadarSettings(BaseModel):
    watchlist: List[str] = Field(default_factory=list)
    macro_keywords: List[str] = Field(default_factory=list)
    min_analysis_score: int = Field(default=60, ge=0, le=100)
    min_push_score: int = Field(default=75, ge=0, le=100)
    app_timezone: str = "Asia/Shanghai"
    news_push_interval_hours: int = Field(default=12, ge=1, le=24)
    refresh_on_open: bool = True
    open_refresh_cooldown_minutes: int = Field(default=10, ge=1, le=1440)
    max_ai_items_per_run: int = Field(default=5, ge=1, le=20)
    public_base_url: str = ""

    @model_validator(mode="after")
    def validate_thresholds(self) -> "NewsRadarSettings":
        if self.min_push_score < self.min_analysis_score:
            raise ValueError("MIN_PUSH_SCORE must be greater than or equal to MIN_ANALYSIS_SCORE")
        return self

    @classmethod
    def from_env(cls, *, fallback_watchlist: Optional[List[str]] = None) -> "NewsRadarSettings":
        def split(name: str, fallback: Optional[List[str]] = None) -> List[str]:
            raw = os.getenv(name, "")
            if not raw:
                return list(fallback or [])
            return [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]

        def boolean(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        return cls(
            watchlist=[parse_stock_symbol(item)[0] for item in split("WATCHLIST", fallback_watchlist)],
            macro_keywords=split("MACRO_KEYWORDS"),
            min_analysis_score=int(os.getenv("MIN_ANALYSIS_SCORE", "60")),
            min_push_score=int(os.getenv("MIN_PUSH_SCORE", "75")),
            app_timezone=os.getenv("APP_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai",
            news_push_interval_hours=int(os.getenv("NEWS_PUSH_INTERVAL_HOURS", "12")),
            refresh_on_open=boolean("REFRESH_ON_OPEN", True),
            open_refresh_cooldown_minutes=int(os.getenv("OPEN_REFRESH_COOLDOWN_MINUTES", "10")),
            max_ai_items_per_run=int(os.getenv("MAX_AI_ITEMS_PER_RUN", "5")),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/"),
        )


def parse_watchlist_input(value: str) -> List[str]:
    """Parse comma, whitespace, newline, and Chinese punctuation separated symbols."""
    raw_items = re.split(r"[,，;；\s]+", value or "")
    normalized = [parse_stock_symbol(item)[0] for item in raw_items if item.strip()]
    return list(dict.fromkeys(normalized))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
