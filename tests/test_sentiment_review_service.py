from __future__ import annotations

from datetime import date

import pytest

from src.services.sentiment_review_service import SentimentReviewService


class FakeProvider:
    def get_sentiment_market_stats(self, value):
        return {"up_count": 1152, "down_count": 4791, "flat_count": 60, "total_amount": 35523.0, "source": "fake"}

    def get_limit_up_pool(self, date=None, n=20):
        return [
            {"code": "1", "name": "A", "consecutive_boards": 2, "industry": "电子"},
            {"code": "2", "name": "B", "consecutive_boards": 3, "industry": "电子"},
            {"code": "3", "name": "C", "consecutive_boards": 6, "industry": "医药"},
        ]

    def get_broken_limit_pool(self, value):
        return [{"code": "4", "name": "D", "industry": "电子"}]

    def get_previous_limit_up_pool(self, value):
        return [
            {"code": "5", "name": "E", "auction_return": .1, "close_return": .03, "previous_consecutive_boards": 1},
            {"code": "6", "name": "F", "auction_return": -.02, "close_return": -.01, "previous_consecutive_boards": 2},
        ]


class FakeRepo:
    def list_dates(self, market="cn", limit=90):
        return []


def test_calculate_for_date_builds_stable_deterministic_payload() -> None:
    result = SentimentReviewService(FakeProvider(), FakeRepo()).calculate_for_date(date(2026, 6, 26))
    payload = result["structured_payload"]
    assert payload["breadth"]["delta"] == -3639
    assert payload["boards"]["highest"] == 6
    assert payload["boards"]["broken_rate"] == pytest.approx(0.25)
    assert payload["next_day_feedback"]["auction_median"] == pytest.approx(0.04)
    assert payload["next_day_feedback"]["close_positive_rate"] == pytest.approx(0.5)
    assert payload["quality"] == "complete"
    assert len(result["stock_evidence"]) == 6


def test_missing_market_stats_marks_partial_and_suppresses_emotion_state() -> None:
    provider = FakeProvider()
    provider.get_sentiment_market_stats = lambda value: None
    result = SentimentReviewService(provider, FakeRepo()).calculate_for_date(date(2026, 6, 26))
    payload = result["structured_payload"]
    assert payload["quality"] == "partial"
    assert payload["emotion_state"] is None
    assert payload["completeness"]["market_breadth"] is False


def test_stock_evidence_merges_multiple_roles_by_stock_code() -> None:
    provider = FakeProvider()
    provider.get_limit_up_pool = lambda date=None, n=20: [
        {"code": "600001", "name": "重叠股票", "consecutive_boards": 2},
    ]
    provider.get_broken_limit_pool = lambda value: []
    provider.get_previous_limit_up_pool = lambda value: [
        {"code": "600001", "name": "重叠股票", "close_return": .03},
    ]
    evidence = SentimentReviewService(provider, FakeRepo()).calculate_for_date(
        date(2026, 6, 26)
    )["stock_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["evidence_types"] == ["limit_up", "previous_limit"]
    assert evidence[0]["consecutive_boards"] == 2
    assert evidence[0]["close_return"] == pytest.approx(.03)
