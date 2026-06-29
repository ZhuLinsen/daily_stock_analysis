# -*- coding: utf-8 -*-
"""Normalized domain contracts for the A-share post-close sentiment review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class SentimentStockEvidence:
    code: str
    name: str
    board_type: str
    is_st: bool = False
    is_limit_up: bool = False
    is_broken_limit: bool = False
    consecutive_boards: int = 0
    previous_consecutive_boards: int = 0
    amount: Optional[float] = None
    seal_amount: Optional[float] = None
    first_limit_time: Optional[str] = None
    last_limit_time: Optional[str] = None
    break_count: int = 0
    auction_return: Optional[float] = None
    close_return: Optional[float] = None
    industry: Optional[str] = None
    concepts: Tuple[str, ...] = ()
    provider: str = ""
    source_timestamp: Optional[datetime] = None
    quality: str = "complete"


@dataclass(frozen=True)
class SentimentReviewInput:
    trade_date: date
    up_count: int
    down_count: int
    flat_count: int
    total_amount: float
    previous_total_amount: Optional[float]
    limit_up_stocks: Tuple[SentimentStockEvidence, ...] = ()
    broken_stocks: Tuple[SentimentStockEvidence, ...] = ()
    previous_limit_stocks: Tuple[SentimentStockEvidence, ...] = ()
    historical_metrics: Tuple[dict[str, Any], ...] = ()
