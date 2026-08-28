from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints.market_status import router
from src.core.trading_calendar import MarketPhase, MarketPhaseContext


def _context(market: str) -> MarketPhaseContext:
    return MarketPhaseContext(
        market=market,
        phase=MarketPhase.INTRADAY if market == "us" else MarketPhase.POSTMARKET,
        market_local_time=datetime(2026, 8, 14, 9, 45, tzinfo=timezone.utc),
        session_date=datetime(2026, 8, 14).date(),
        effective_daily_bar_date=datetime(2026, 8, 14).date(),
        is_trading_day=True,
        is_market_open_now=market == "us",
        is_partial_bar=market == "us",
        minutes_to_close=375 if market == "us" else None,
    )


class MarketStatusEndpointTestCase(unittest.TestCase):
    def test_returns_supported_markets_and_next_session(self):
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/market")

        next_open = datetime(2026, 8, 17, 9, 30, tzinfo=timezone.utc)
        with (
            patch("api.v1.endpoints.market_status.build_market_phase_context", side_effect=lambda **kwargs: _context(kwargs["market"])),
            patch("api.v1.endpoints.market_status.get_next_session_open", return_value=next_open),
        ):
            response = TestClient(app).get("/api/v1/market/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["market"] for item in payload["markets"]], ["cn", "hk", "us", "jp", "kr"])
        self.assertEqual(payload["markets"][2]["phase"], "intraday")
        self.assertEqual(payload["markets"][2]["minutes_to_close"], 375)
        self.assertEqual(payload["markets"][0]["next_session_open"], next_open.isoformat())
        self.assertTrue(payload["generated_at"].endswith("+00:00"))
