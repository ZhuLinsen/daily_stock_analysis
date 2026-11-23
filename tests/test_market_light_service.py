# -*- coding: utf-8 -*-
"""Tests for structured Market Light snapshot service."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from src.config import Config
from src.core.market_review import MARKET_REVIEW_HISTORY_CODE, MARKET_REVIEW_REPORT_TYPE
from src.market_analyzer import MarketIndex, MarketOverview
from src.services.market_light_service import (
    MARKET_LIGHT_HISTORY_BATCH_SIZE,
    build_current_snapshot,
    load_previous_snapshot,
    normalize_market_region,
)
from src.storage import AnalysisHistory, DatabaseManager


def _snapshot(region: str, trade_date: str, score: int = 50) -> dict:
    return {
        "region": region,
        "trade_date": trade_date,
        "status": "yellow",
        "score": score,
        "label": "需观察",
        "temperature_label": "震荡",
        "reasons": ["test"],
        "guidance": "test",
        "dimensions": {
            "breadth": {"score": 50, "available": True},
            "index": {"score": 50, "available": True},
            "limit": {"score": 50, "available": True},
        },
        "data_quality": "ok",
    }


class MarketLightServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "market_light.db"
        os.environ["DATABASE_PATH"] = str(self.db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def test_normalize_market_region_rejects_unknown_regions(self) -> None:
        for region in ("global", "tw"):
            with self.subTest(region=region):
                with self.assertRaisesRegex(ValueError, "cn, hk, us, jp, kr"):
                    normalize_market_region(region)

    def _add_history(self, *, created_at: datetime, context_snapshot: dict | None) -> None:
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id=f"q-{created_at.timestamp()}",
                    code=MARKET_REVIEW_HISTORY_CODE,
                    name="大盘复盘",
                    report_type=MARKET_REVIEW_REPORT_TYPE,
                    sentiment_score=50,
                    operation_advice="查看复盘",
                    trend_prediction="大盘复盘",
                    analysis_summary="summary",
                    raw_result="{}",
                    news_content="body",
                    context_snapshot=json.dumps(context_snapshot, ensure_ascii=False)
                    if context_snapshot is not None
                    else None,
                    created_at=created_at,
                )
            )
            session.commit()

    def test_load_previous_snapshot_skips_same_day_and_legacy_history(self) -> None:
        self._add_history(
            created_at=datetime(2026, 3, 7, 18, 0),
            context_snapshot={"market_light_snapshots": {"cn": _snapshot("cn", "2026-03-07", 30)}},
        )
        self._add_history(
            created_at=datetime(2026, 3, 7, 17, 0),
            context_snapshot={"report_kind": "market_review", "market_review_region": "cn"},
        )
        self._add_history(
            created_at=datetime(2026, 3, 6, 18, 0),
            context_snapshot={"market_light_snapshots": {"cn": _snapshot("cn", "2026-03-06", 72)}},
        )

        previous = load_previous_snapshot("cn", before_trade_date="2026-03-07", db_manager=self.db)

        self.assertIsNotNone(previous)
        assert previous is not None
        self.assertEqual(previous["trade_date"], "2026-03-06")
        self.assertEqual(previous["score"], 72)

    def test_load_previous_snapshot_prefers_latest_trade_date_over_newer_backfill(self) -> None:
        self._add_history(
            created_at=datetime(2026, 3, 10, 20, 0),
            context_snapshot={"market_light_snapshots": {"cn": _snapshot("cn", "2026-03-05", 99)}},
        )
        self._add_history(
            created_at=datetime(2026, 3, 9, 18, 0),
            context_snapshot={"market_light_snapshots": {"cn": _snapshot("cn", "2026-03-09", 72)}},
        )
        self._add_history(
            created_at=datetime(2026, 3, 8, 18, 0),
            context_snapshot={"market_light_snapshots": {"cn": _snapshot("cn", "2026-03-08", 80)}},
        )

        previous = load_previous_snapshot("cn", before_trade_date="2026-03-10", db_manager=self.db)

        self.assertIsNotNone(previous)
        assert previous is not None
        self.assertEqual(previous["trade_date"], "2026-03-09")
        self.assertEqual(previous["score"], 72)

    def test_load_previous_snapshot_uses_latest_valid_snapshot_for_target_trade_date(self) -> None:
        self._add_history(
            created_at=datetime(2026, 3, 9, 19, 0),
            context_snapshot={"market_light_snapshots": {"cn": _snapshot("cn", "2026-03-09", 66)}},
        )
        self._add_history(
            created_at=datetime(2026, 3, 9, 18, 0),
            context_snapshot={"market_light_snapshots": {"cn": _snapshot("cn", "2026-03-09", 72)}},
        )
        self._add_history(
            created_at=datetime(2026, 3, 10, 20, 0),
            context_snapshot={"market_light_snapshots": {"cn": _snapshot("cn", "2026-03-05", 99)}},
        )

        previous = load_previous_snapshot("cn", before_trade_date="2026-03-10", db_manager=self.db)

        self.assertIsNotNone(previous)
        assert previous is not None
        self.assertEqual(previous["trade_date"], "2026-03-09")
        self.assertEqual(previous["score"], 66)

    def test_load_previous_snapshot_degrades_when_target_trade_date_has_no_valid_snapshot(self) -> None:
        self._add_history(
            created_at=datetime(2026, 3, 8, 18, 0),
            context_snapshot={"market_light_snapshots": {"cn": _snapshot("cn", "2026-03-08", 80)}},
        )
        self._add_history(
            created_at=datetime(2026, 3, 9, 18, 0),
            context_snapshot={
                "market_light_snapshots": {
                    "cn": {
                        "region": "cn",
                        "trade_date": "2026-03-09",
                        "status": "yellow",
                        "score": 72,
                    }
                }
            },
        )

        with self.assertRaisesRegex(ValueError, "invalid persisted market light snapshot"):
            load_previous_snapshot("cn", before_trade_date="2026-03-10", db_manager=self.db)

    def test_load_previous_snapshot_scans_beyond_batch_without_default_cap(self) -> None:
        newest = datetime(2026, 3, 7, 18, 0)
        for index in range(MARKET_LIGHT_HISTORY_BATCH_SIZE + 5):
            self._add_history(
                created_at=newest - timedelta(minutes=index),
                context_snapshot={"report_kind": "market_review", "market_review_region": "cn"},
            )
        self._add_history(
            created_at=datetime(2026, 3, 6, 18, 0),
            context_snapshot={"market_light_snapshots": {"cn": _snapshot("cn", "2026-03-06", 72)}},
        )

        previous = load_previous_snapshot("cn", before_trade_date="2026-03-07", db_manager=self.db)

        self.assertIsNotNone(previous)
        assert previous is not None
        self.assertEqual(previous["trade_date"], "2026-03-06")
        self.assertEqual(previous["score"], 72)

    def test_build_current_snapshot_uses_market_analyzer_without_review(self) -> None:
        overview = MarketOverview(
            date="2026-03-07",
            indices=[MarketIndex(code="000001", name="上证指数", current=3200, change_pct=-1.0)],
            up_count=1000,
            down_count=3000,
            limit_up_count=10,
            limit_down_count=80,
        )

        with patch("src.services.market_light_service.MarketAnalyzer") as analyzer_cls:
            analyzer = analyzer_cls.return_value
            analyzer.get_market_overview.return_value = overview
            analyzer.build_market_light_snapshot.return_value = _snapshot("cn", "2026-03-07", 33)

            snapshot = build_current_snapshot("CN")

        analyzer_cls.assert_called_once_with(region="cn")
        analyzer.get_market_overview.assert_called_once()
        analyzer.build_market_light_snapshot.assert_called_once_with(overview)
        self.assertEqual(snapshot["region"], "cn")
        self.assertEqual(snapshot["score"], 33)

    def test_market_light_service_accepts_jp_kr_regions(self) -> None:
        self._add_history(
            created_at=datetime(2026, 3, 6, 18, 0),
            context_snapshot={"market_light_snapshots": {"jp": _snapshot("jp", "2026-03-06", 54)}},
        )

        previous = load_previous_snapshot("JP", before_trade_date="2026-03-07", db_manager=self.db)

        self.assertEqual(normalize_market_region("KR"), "kr")
        self.assertIsNotNone(previous)
        assert previous is not None
        self.assertEqual(previous["region"], "jp")
        self.assertEqual(previous["score"], 54)


if __name__ == "__main__":
    unittest.main()
