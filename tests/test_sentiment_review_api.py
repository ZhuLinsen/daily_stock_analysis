from __future__ import annotations

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_database_manager
from api.v1.endpoints import sentiment_review
from src.repositories.sentiment_review_repo import SentimentReviewRepository
from src.storage import DatabaseManager


def test_detail_dates_and_trend_endpoints(tmp_path) -> None:
    DatabaseManager.reset_instance()
    db = DatabaseManager(f"sqlite:///{tmp_path / 'api.db'}")
    SentimentReviewRepository(db).upsert_daily(
        market="cn", trade_date=date(2026, 6, 26), run_status="success",
        data_quality="complete", structured_payload={"boards": {"highest": 6}},
    )
    app = FastAPI()
    app.include_router(sentiment_review.router, prefix="/sentiment-review")
    app.dependency_overrides[get_database_manager] = lambda: db
    client = TestClient(app)

    assert client.get("/sentiment-review/dates").json()[0]["trade_date"] == "2026-06-26"
    assert client.get("/sentiment-review/2026-06-26").json()["payload"]["boards"]["highest"] == 6
    point = client.get("/sentiment-review/trend", params={"metric": "boards.highest", "window": 30}).json()[0]
    assert point["value"] == 6
    DatabaseManager.reset_instance()
