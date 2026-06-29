# -*- coding: utf-8 -*-
"""Orchestration for one idempotent post-close sentiment review run."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import date
from typing import Any, Callable, Dict, Optional

from data_provider.akshare_fetcher import AkshareFetcher
from data_provider.tushare_fetcher import TushareFetcher
from src.repositories.sentiment_review_repo import SentimentReviewRepository
from src.services.sentiment_review_service import SentimentReviewService

logger = logging.getLogger(__name__)
_run_lock = threading.Lock()


class _SentimentDataProvider:
    """AkShare primary provider with token-aware Tushare breadth fallback."""

    def __init__(self) -> None:
        self.akshare = AkshareFetcher(sleep_min=0, sleep_max=0)
        self.tushare = TushareFetcher()

    def get_sentiment_market_stats(self, value: str):
        from src.core.trading_calendar import get_effective_trading_date

        effective = get_effective_trading_date('cn').strftime('%Y%m%d')
        if value != effective:
            # AkShare's spot endpoint has no historical-date semantics; using it
            # here would silently mix today's breadth into an old review.
            return self.tushare.get_sentiment_market_stats(value)
        return self.akshare.get_sentiment_market_stats(value) or self.tushare.get_sentiment_market_stats(value)

    def get_limit_up_pool(self, **kwargs):
        return self.akshare.get_limit_up_pool(**kwargs)

    def get_broken_limit_pool(self, value: str):
        return self.akshare.get_broken_limit_pool(value)

    def get_previous_limit_up_pool(self, value: str):
        return self.akshare.get_previous_limit_up_pool(value)


def _extract_json(text: str) -> Dict[str, Any]:
    cleaned = (text or '').strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {'analysis': cleaned} if cleaned else {}


def generate_narrative(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the configured LLM for prose only; numeric metrics remain immutable."""
    from src.analyzer import GeminiAnalyzer

    prompt = (
        "你是A股收盘复盘助手。只能解释给定的规则计算结果，不得修改、补造任何数字。"
        "请输出JSON对象，字段为 analysis、next_day_watch、risk_notes，均为中文字符串。\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    analyzer = GeminiAnalyzer()
    text, _model, _usage = analyzer._call_litellm(
        prompt,
        {'temperature': 0.2, 'max_tokens': 1200},
        audit_context={'call_type': 'sentiment_review'},
    )
    return _extract_json(text)


class SentimentReviewRunner:
    def __init__(
        self,
        *,
        repository: Optional[SentimentReviewRepository] = None,
        service: Optional[SentimentReviewService] = None,
        narrative_generator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = generate_narrative,
    ):
        self.repository = repository or SentimentReviewRepository()
        self.service = service or SentimentReviewService(_SentimentDataProvider(), self.repository)
        self.narrative_generator = narrative_generator

    @staticmethod
    def serialize(row: Any, status: str = 'success') -> Dict[str, Any]:
        return {
            'id': row.id,
            'status': status,
            'run_status': row.run_status,
            'data_quality': row.data_quality,
            'trade_date': row.trade_date.isoformat(),
            'payload': row.payload(),
            'narrative': {
                'analysis': row.llm_analysis,
                'next_day_watch': row.llm_next_day_watch,
                'risk_notes': row.llm_risk_notes,
            },
        }

    def run(self, trade_date: date, *, market: str = 'cn', force: bool = False) -> Dict[str, Any]:
        existing = self.repository.get_daily(market, trade_date)
        if existing is not None and existing.data_quality == 'complete' and not force:
            return self.serialize(existing, 'existing')
        if not _run_lock.acquire(blocking=False):
            return {'status': 'running', 'trade_date': trade_date.isoformat()}
        try:
            result = self.service.calculate_for_date(trade_date, market)
            narrative: Dict[str, Any] = {}
            llm_error: Optional[str] = None
            if self.narrative_generator is not None:
                try:
                    narrative = self.narrative_generator(result['structured_payload']) or {}
                except Exception as exc:
                    llm_error = str(exc)
                    logger.warning("Sentiment review narrative generation failed: %s", exc)
            payload = dict(result['structured_payload'])
            if llm_error:
                payload['llm_status'] = 'failed'
                payload['llm_error'] = llm_error[:500]
            else:
                payload['llm_status'] = 'success' if narrative else 'skipped'
            row = self.repository.upsert_daily(
                market=market,
                trade_date=trade_date,
                run_status='success',
                data_quality=result['quality'],
                structured_payload=payload,
                llm_analysis=narrative.get('analysis'),
                llm_next_day_watch=narrative.get('next_day_watch'),
                llm_risk_notes=narrative.get('risk_notes'),
                provider_trace=result['provider_trace'],
                completeness=result['completeness'],
                task_id=f"sentiment_{uuid.uuid4().hex}",
            )
            self.repository.replace_stocks(row.id, result['stock_evidence'])
            return self.serialize(row)
        finally:
            _run_lock.release()
