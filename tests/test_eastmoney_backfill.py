"""Offline tests of recent Eastmoney backfill and safe retries."""

from contextlib import redirect_stdout
from datetime import date, timedelta
from io import StringIO
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scripts.backfill_sentiment import main
from src.data.csmar_daily import CsmarSourceError
from src.services.eastmoney_sentiment import EASTMONEY_MARKET, EASTMONEY_VERSION
from src.services.sentiment_backfill_service import iter_eastmoney_backfill
from src.storage import SentimentSnapshot


def snapshot(day, value=2):
    return {"market": EASTMONEY_MARKET, "trade_date": day, "previous_trade_date": day - timedelta(days=1),
            "definition_version": EASTMONEY_VERSION, "quality_status": "complete",
            "metrics": {"limit_up_count": value}, "components": {},
            "provider_trace": {"provider": "eastmoney_akshare", "as_of_sha256": str(value)},
            "completeness": {}}


class EastmoneyBackfillTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SentimentSnapshot.__table__.create(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_missing_session_retry_idempotence_and_conflict(self):
        def build(day):
            if day == date(2026, 10, 20):
                raise CsmarSourceError("source unavailable")
            return snapshot(day)
        options = dict(start_date=date(2026, 10, 19), end_date=date(2026, 10, 21),
                       dry_run=False, session_factory=lambda: Session(self.engine))
        with patch("src.services.eastmoney_sentiment.build_eastmoney_snapshot", side_effect=build):
            first = list(iter_eastmoney_backfill(**options))
            second = list(iter_eastmoney_backfill(**options))
        self.assertEqual([r.status for r in first], ["inserted", "failed", "inserted"])
        self.assertEqual([r.status for r in second], ["unchanged", "failed", "unchanged"])
        with patch("src.services.eastmoney_sentiment.build_eastmoney_snapshot", side_effect=lambda day: snapshot(day, 3)):
            conflict = list(iter_eastmoney_backfill(start_date=date(2026, 10, 19), end_date=date(2026, 10, 19),
                                                     dry_run=False, session_factory=lambda: Session(self.engine)))
        self.assertEqual(conflict[0].status, "conflict")
        with Session(self.engine) as session:
            rows = session.execute(select(SentimentSnapshot)).scalars().all()
            self.assertEqual(len(rows), 2)
            self.assertEqual(json.loads(rows[0].metrics_json)["limit_up_count"], 2)

    def test_eastmoney_dry_run_needs_no_csmar_file_or_database(self):
        output = StringIO()
        with patch("scripts.backfill_sentiment.get_config", return_value=SimpleNamespace(csmar_zip_path="")), \
             patch("scripts.backfill_sentiment.DatabaseManager.get_instance", side_effect=AssertionError("database opened")), \
             patch("src.services.eastmoney_sentiment.build_eastmoney_snapshot", side_effect=snapshot), \
             redirect_stdout(output):
            code = main(["--source", "eastmoney", "--start-date", "2026-10-19", "--end-date", "2026-10-19", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue().splitlines()[0])["status"], "dry-run")


if __name__ == "__main__":
    unittest.main()
