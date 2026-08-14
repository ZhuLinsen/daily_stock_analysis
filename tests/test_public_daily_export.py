"""Public Finsance export contract tests."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services.public_daily_export import build_public_daily_payload, write_daily_export


class PublicDailyExportTestCase(unittest.TestCase):
    def _result(self):
        return SimpleNamespace(
            code="600519",
            name="测试股票",
            success=True,
            action="watch",
            action_label="观察",
            decision_type="hold",
            sentiment_score=61,
            trend_prediction="震荡",
            confidence_level="中",
            analysis_summary="基于公开数据的观察摘要。",
            risk_warning="数据仍需继续确认。",
            search_performed=True,
            data_sources="yfinance, earnings",
            model_used="gemini/gemini-3-flash-preview",
            analysis_context_pack_overview={
                "data_quality": {"stale": False, "bar_asof": "2026-08-14"}
            },
            current_price=123.45,
            raw_response='{"secret":"do-not-publish"}',
            dashboard={
                "core_conclusion": {"one_sentence": "等待更多确认。"},
                "intelligence": {
                    "positive_catalysts": ["公开催化"],
                    "risk_alerts": ["公开风险"],
                },
                "phase_decision": {"data_limitations": ["bar freshness unavailable"]},
                "battle_plan": {
                    "sniper_points": {
                        "ideal_buy": "123.45",
                        "stop_loss": "100",
                        "take_profit": "150",
                    }
                },
            },
        )

    def test_allow_list_excludes_private_fields_and_writes_checksum(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ",
            {
                "FINSANCE_PUBLICATION_ENABLED": "false",
                "FINSANCE_COMMERCIAL_MODE": "false",
            },
            clear=False,
        ):
            path = write_daily_export(
                [self._result()],
                output_dir=Path(temp_dir),
                report_date="2026-08-14",
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            dumped = json.dumps(payload, ensure_ascii=False)

            self.assertEqual(payload["schema_version"], "finsance-quanttrade-daily-v1")
            self.assertEqual(payload["stocks"][0]["ticker"], "600519")
            self.assertFalse(payload["stocks"][0]["data_quality"]["stale"])
            self.assertEqual(payload["stocks"][0]["data_quality"]["bar_asof"], "2026-08-14")
            self.assertNotIn("battle_plan", dumped)
            self.assertNotIn("current_price", dumped)
            self.assertNotIn("123.45", dumped)
            self.assertTrue(path.with_name(f"{path.name}.sha256").exists())
            self.assertTrue(Path(temp_dir, "daily_2026-08-14.json").exists())

    def test_empty_results_do_not_publish(self):
        payload = build_public_daily_payload([])
        self.assertEqual(payload["stocks"], [])
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertIsNone(write_daily_export([], output_dir=temp_dir))


if __name__ == "__main__":
    unittest.main()
