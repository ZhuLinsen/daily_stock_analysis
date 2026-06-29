# -*- coding: utf-8 -*-
"""Post-close sentiment review API."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_database_manager
from api.v1.schemas.sentiment_review import SentimentReviewRunRequest
from src.core.sentiment_review import SentimentReviewRunner
from src.core.trading_calendar import get_effective_trading_date
from src.repositories.sentiment_review_repo import SentimentReviewRepository
from src.storage import DatabaseManager

router = APIRouter()


def _json_text(value: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(value or '{}')
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _serialize(row: Any) -> Dict[str, Any]:
    return {
        'id': row.id,
        'market': row.market,
        'trade_date': row.trade_date.isoformat(),
        'run_status': row.run_status,
        'data_quality': row.data_quality,
        'payload': row.payload(),
        'narrative': {
            'analysis': row.llm_analysis,
            'next_day_watch': row.llm_next_day_watch,
            'risk_notes': row.llm_risk_notes,
        },
        'provider_trace': _json_text(row.provider_trace),
        'completeness': _json_text(row.completeness),
        'updated_at': row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post('/run')
def run_review(
    request: SentimentReviewRunRequest,
    db: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    effective_date = get_effective_trading_date(request.market)
    target = request.trade_date or effective_date
    if target > effective_date:
        raise HTTPException(400, detail='只能生成已收盘交易日的复盘')
    return SentimentReviewRunner(repository=SentimentReviewRepository(db)).run(
        target, market=request.market, force=request.force
    )


@router.get('/dates')
def list_review_dates(
    market: str = 'cn',
    limit: int = Query(90, ge=1, le=500),
    db: DatabaseManager = Depends(get_database_manager),
) -> List[Dict[str, Any]]:
    return [{
        'trade_date': row.trade_date.isoformat(),
        'run_status': row.run_status,
        'data_quality': row.data_quality,
        'updated_at': row.updated_at.isoformat() if row.updated_at else None,
    } for row in SentimentReviewRepository(db).list_dates(market, limit)]


@router.get('/trend')
def get_review_trend(
    metric: str = Query(..., min_length=1, max_length=100),
    market: str = 'cn',
    window: int = Query(30, ge=1, le=60),
    db: DatabaseManager = Depends(get_database_manager),
) -> List[Dict[str, Any]]:
    return SentimentReviewRepository(db).load_trend(market, metric, window)


@router.get('/{trade_date}')
def get_review(
    trade_date: date,
    market: str = 'cn',
    db: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    row = SentimentReviewRepository(db).get_daily(market, trade_date)
    if row is None:
        raise HTTPException(404, detail='复盘记录不存在')
    return _serialize(row)


@router.get('/{trade_date}/stocks')
def get_review_stocks(
    trade_date: date,
    market: str = 'cn',
    db: DatabaseManager = Depends(get_database_manager),
) -> List[Dict[str, Any]]:
    repo = SentimentReviewRepository(db)
    row = repo.get_daily(market, trade_date)
    if row is None:
        raise HTTPException(404, detail='复盘记录不存在')
    return [stock.evidence() for stock in repo.list_stocks(row.id)]
