# -*- coding: utf-8 -*-
"""Persistence operations for post-close sentiment reviews."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, desc, select

from src.storage import DatabaseManager, SentimentReviewDaily, SentimentReviewStock


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))


class SentimentReviewRepository:
    """Database boundary for review snapshots and their stock-level evidence."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def get_daily(self, market: str, trade_date: date) -> Optional[SentimentReviewDaily]:
        with self.db.get_session() as session:
            return session.execute(
                select(SentimentReviewDaily).where(
                    SentimentReviewDaily.market == market,
                    SentimentReviewDaily.trade_date == trade_date,
                ).limit(1)
            ).scalar_one_or_none()

    def upsert_daily(
        self,
        *,
        market: str,
        trade_date: date,
        run_status: str,
        data_quality: str,
        structured_payload: Dict[str, Any],
        llm_analysis: Optional[str] = None,
        llm_next_day_watch: Optional[str] = None,
        llm_risk_notes: Optional[str] = None,
        provider_trace: Optional[Dict[str, Any]] = None,
        completeness: Optional[Dict[str, Any]] = None,
        rule_version: int = 1,
        prompt_version: int = 1,
        task_id: Optional[str] = None,
    ) -> SentimentReviewDaily:
        with self.db.get_session() as session:
            row = session.execute(
                select(SentimentReviewDaily).where(
                    SentimentReviewDaily.market == market,
                    SentimentReviewDaily.trade_date == trade_date,
                ).limit(1)
            ).scalar_one_or_none()
            if row is not None and row.data_quality == 'complete' and data_quality != 'complete':
                session.expunge(row)
                return row
            if row is None:
                row = SentimentReviewDaily(market=market, trade_date=trade_date)
                session.add(row)
            row.run_status = run_status
            row.data_quality = data_quality
            row.structured_payload = _json(structured_payload)
            row.llm_analysis = llm_analysis
            row.llm_next_day_watch = llm_next_day_watch
            row.llm_risk_notes = llm_risk_notes
            row.provider_trace = _json(provider_trace)
            row.completeness = _json(completeness)
            row.rule_version = rule_version
            row.prompt_version = prompt_version
            row.task_id = task_id
            row.updated_at = datetime.now()
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    def replace_stocks(self, daily_id: int, stocks: Iterable[Dict[str, Any]]) -> None:
        with self.db.get_session() as session:
            session.execute(delete(SentimentReviewStock).where(SentimentReviewStock.daily_id == daily_id))
            for stock in stocks:
                payload = dict(stock)
                code = str(payload.get('code') or payload.get('stock_code') or '').strip()
                if not code:
                    continue
                name = payload.get('name') or payload.get('stock_name')
                session.add(SentimentReviewStock(
                    daily_id=daily_id,
                    stock_code=code,
                    stock_name=str(name) if name is not None else None,
                    evidence_payload=_json(payload),
                ))
            session.commit()

    def list_stocks(self, daily_id: int) -> List[SentimentReviewStock]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(SentimentReviewStock)
                .where(SentimentReviewStock.daily_id == daily_id)
                .order_by(SentimentReviewStock.stock_code)
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def list_dates(self, market: str = 'cn', limit: int = 90) -> List[SentimentReviewDaily]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(SentimentReviewDaily)
                .where(SentimentReviewDaily.market == market)
                .order_by(desc(SentimentReviewDaily.trade_date))
                .limit(max(1, min(int(limit), 500)))
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def load_trend(self, market: str, metric_path: str, window: int = 30) -> List[Dict[str, Any]]:
        rows = self.list_dates(market, window)
        points: List[Dict[str, Any]] = []
        for row in reversed(rows):
            payload = row.payload()
            value: Any = payload
            for part in metric_path.split('.'):
                value = value.get(part) if isinstance(value, dict) else None
            sample_count = payload.get('sample_count')
            if isinstance(value, dict):
                sample_count = value.get('sample_count', sample_count)
                value = value.get('value')
            points.append({
                'trade_date': row.trade_date.isoformat(),
                'value': value,
                'quality': row.data_quality,
                'sample_count': sample_count,
            })
        return points
