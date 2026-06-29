from __future__ import annotations

from datetime import date

import pytest

from src.repositories.sentiment_review_repo import SentimentReviewRepository
from src.storage import DatabaseManager


@pytest.fixture()
def repository(tmp_path):
    DatabaseManager.reset_instance()
    db = DatabaseManager(f"sqlite:///{tmp_path / 'sentiment.db'}")
    repo = SentimentReviewRepository(db)
    yield repo
    DatabaseManager.reset_instance()


def test_upsert_daily_is_unique_by_market_and_trade_date(repository) -> None:
    first = repository.upsert_daily(
        market="cn",
        trade_date=date(2026, 6, 26),
        run_status="success",
        data_quality="complete",
        structured_payload={"breadth_delta": -3639},
    )
    second = repository.upsert_daily(
        market="cn",
        trade_date=date(2026, 6, 26),
        run_status="success",
        data_quality="complete",
        structured_payload={"breadth_delta": -3600},
    )
    assert first.id == second.id
    assert repository.get_daily("cn", date(2026, 6, 26)).payload()["breadth_delta"] == -3600


def test_imported_record_cannot_replace_complete_record(repository) -> None:
    repository.upsert_daily(
        market="cn",
        trade_date=date(2026, 6, 26),
        run_status="success",
        data_quality="complete",
        structured_payload={"breadth_delta": -3639},
    )
    repository.upsert_daily(
        market="cn",
        trade_date=date(2026, 6, 26),
        run_status="partial",
        data_quality="imported",
        structured_payload={"breadth_delta": -1577},
    )
    row = repository.get_daily("cn", date(2026, 6, 26))
    assert row.data_quality == "complete"
    assert row.payload()["breadth_delta"] == -3639


def test_complete_record_can_upgrade_imported_record(repository) -> None:
    repository.upsert_daily(
        market="cn",
        trade_date=date(2026, 6, 26),
        run_status="partial",
        data_quality="imported",
        structured_payload={"breadth_delta": -1577},
    )
    repository.upsert_daily(
        market="cn",
        trade_date=date(2026, 6, 26),
        run_status="success",
        data_quality="complete",
        structured_payload={"breadth_delta": -3639},
    )
    row = repository.get_daily("cn", date(2026, 6, 26))
    assert row.data_quality == "complete"
    assert row.payload()["breadth_delta"] == -3639


def test_replace_stocks_and_load_trend_preserve_null_values(repository) -> None:
    daily = repository.upsert_daily(
        market="cn",
        trade_date=date(2026, 6, 26),
        run_status="success",
        data_quality="complete",
        structured_payload={"boards": {"highest": None}},
    )
    repository.replace_stocks(
        daily.id,
        [{"code": "600001", "name": "示例股份", "consecutive_boards": 2}],
    )
    assert repository.list_stocks(daily.id)[0].evidence()["consecutive_boards"] == 2
    points = repository.load_trend("cn", "boards.highest", 30)
    assert points == [{
        "trade_date": "2026-06-26",
        "value": None,
        "quality": "complete",
        "sample_count": None,
    }]
