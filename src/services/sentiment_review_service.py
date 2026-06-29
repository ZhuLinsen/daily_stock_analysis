# -*- coding: utf-8 -*-
"""Collect and aggregate deterministic post-close sentiment review metrics."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Dict, Iterable, Optional

from src.services.sentiment_review_calculator import (
    auction_stats,
    broken_board_rate,
    classify_emotion,
    empirical_percentile,
    promotion_rates,
    safe_ratio,
)


class SentimentReviewService:
    def __init__(self, data_provider: Any, repository: Any):
        self.provider = data_provider
        self.repository = repository

    @staticmethod
    def _board_ladder(rows: Iterable[Dict[str, Any]], field: str = 'consecutive_boards') -> Dict[int, int]:
        counts = Counter(max(1, int(row.get(field) or 1)) for row in rows)
        return dict(sorted(counts.items()))

    def calculate_for_date(self, trade_date: date, market: str = 'cn') -> Dict[str, Any]:
        query_date = trade_date.strftime('%Y%m%d')
        stats = self.provider.get_sentiment_market_stats(query_date)
        raw_limit_rows = self.provider.get_limit_up_pool(date=query_date, n=10000)
        raw_broken_rows = self.provider.get_broken_limit_pool(query_date)
        raw_previous_rows = self.provider.get_previous_limit_up_pool(query_date)
        limit_rows = list(raw_limit_rows or [])
        broken_rows = list(raw_broken_rows or [])
        previous_rows = list(raw_previous_rows or [])

        completeness = {
            'market_breadth': stats is not None,
            'limit_pool': raw_limit_rows is not None,
            'broken_pool': raw_broken_rows is not None,
            'previous_limit_feedback': raw_previous_rows is not None,
        }
        quality = 'complete' if all(completeness.values()) else 'partial'
        current_ladder = self._board_ladder(limit_rows)
        previous_ladder = self._board_ladder(previous_rows, 'previous_consecutive_boards')
        auction_values = [row['auction_return'] for row in previous_rows if row.get('auction_return') is not None]
        close_values = [row['close_return'] for row in previous_rows if row.get('close_return') is not None]
        auction = auction_stats(auction_values)
        close = auction_stats(close_values)

        history = list(self.repository.list_dates(market, 60))
        previous_amount: Optional[float] = None
        historical_deltas = []
        for row in history:
            old_payload = row.payload()
            if previous_amount is None:
                previous_amount = old_payload.get('breadth', {}).get('total_amount')
            old_delta = old_payload.get('breadth', {}).get('delta')
            if old_delta is not None:
                historical_deltas.append(float(old_delta))

        up_count = int((stats or {}).get('up_count') or 0)
        down_count = int((stats or {}).get('down_count') or 0)
        flat_count = int((stats or {}).get('flat_count') or 0)
        total_amount = (stats or {}).get('total_amount')
        breadth_delta = up_count - down_count if stats is not None else None
        breadth_percentile = (
            empirical_percentile(historical_deltas, float(breadth_delta))
            if breadth_delta is not None else None
        )
        industries = Counter(
            str(row.get('industry')).strip()
            for row in limit_rows
            if str(row.get('industry') or '').strip()
        )

        payload: Dict[str, Any] = {
            'version': 1,
            'kind': 'sentiment_review',
            'market': market,
            'trade_date': trade_date.isoformat(),
            'quality': quality,
            'breadth': {
                'up_count': up_count if stats is not None else None,
                'down_count': down_count if stats is not None else None,
                'flat_count': flat_count if stats is not None else None,
                'delta': breadth_delta,
                'total_amount': total_amount,
                'turnover_change': safe_ratio(total_amount, previous_amount, subtract_one=True)
                if total_amount is not None and previous_amount is not None else None,
                'percentile_30d': breadth_percentile,
            },
            'boards': {
                'limit_up_count': len(limit_rows),
                'broken_count': len(broken_rows),
                'broken_rate': broken_board_rate(len(limit_rows), len(broken_rows)),
                'highest': max(current_ladder, default=None),
                'ladder': {str(key): value for key, value in current_ladder.items()},
                'promotion_rates': promotion_rates(current_ladder, previous_ladder),
            },
            'next_day_feedback': {
                'sample_count': len(previous_rows),
                'auction_median': auction['median'],
                'auction_stdev': auction['stdev'],
                'close_median': close['median'],
                'close_stdev': close['stdev'],
                'close_positive_rate': safe_ratio(sum(value > 0 for value in close_values), len(close_values)),
            },
            'themes': [
                {'name': name, 'limit_up_count': count}
                for name, count in industries.most_common(12)
            ],
            'activity': [],
            'emotion_state': classify_emotion(breadth_percentile, breadth_delta) if quality == 'complete' else None,
            'completeness': completeness,
            'provider_trace': {
                'market': (stats or {}).get('source'),
                'limit_pool': 'akshare',
                'broken_pool': 'akshare',
                'previous_limit_feedback': 'akshare',
            },
        }
        evidence_by_code: Dict[str, Dict[str, Any]] = {}
        for kind, rows in (('limit_up', limit_rows), ('broken', broken_rows), ('previous_limit', previous_rows)):
            for row in rows:
                item = dict(row)
                code = str(item.get('code') or '').strip()
                if not code:
                    continue
                existing = evidence_by_code.setdefault(code, {'code': code, 'evidence_types': []})
                existing.update(item)
                existing['evidence_types'].append(kind)
        evidence = list(evidence_by_code.values())
        return {
            'structured_payload': payload,
            'stock_evidence': evidence,
            'provider_trace': payload['provider_trace'],
            'completeness': completeness,
            'quality': quality,
        }
