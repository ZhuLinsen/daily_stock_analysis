# -*- coding: utf-8 -*-
"""Unit tests for the hot-top10 light analysis service (Issue #1936).

Covers the key behaviors of ``src/services/hot_top10_service.py``:

- normal path: hotspots -> single LLM summary -> rendered report -> push
- fewer hotspots than the configured count
- LLM failure degrades to a data-only report instead of raising
- notification failure never raises (and does not record the daily marker)
- daily dedup marker: a second run on the same day is skipped
- corrupt marker fails open (the run executes)
- trading-day gate skips the scheduled run when the CN market is closed
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest import mock

from src.services.hot_top10_service import (
    HotTop10RunResult,
    hot_top10_already_delivered_today,
    hot_top10_marker_path,
    record_hot_top10_marker,
    run_hot_top10_analysis,
)


def _hotspot_payload(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "status": "ok",
        "market": "cn",
        "trade_date": date.today().isoformat(),
        "active_themes": items,
        "leading_industries": [],
        "leading_concepts": [],
        "lagging_themes": [],
        "data_quality": {"status": "ok", "missing_fields": [], "sources": [], "errors": []},
    }


def _theme_items(count: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for index in range(1, count + 1):
        items.append(
            {
                "name": f"主题{index}",
                "code": f"BK{index:04d}",
                "change_pct": 3.2 - index * 0.1,
                "rank": index,
                "source": "industry" if index % 2 else "concept",
                "phase": "accelerating",
                "strength_score": 80 - index,
                "reason": "industry/concept ranking gain",
            }
        )
    return items


def _llm_json() -> str:
    return json.dumps(
        {
            "summary": "今日热点集中在科技主线。",
            "items": [
                {
                    "rank": 1,
                    "name": "主题1",
                    "driver": "政策催化叠加资金流入（推测）",
                    "strength": "强",
                    "advice": "轻仓介入",
                    "risk": "短期涨幅较大，注意回撤风险",
                }
            ],
        },
        ensure_ascii=False,
    )


class _FakeAnalyzer:
    """Minimal stand-in for GeminiAnalyzer.generate_text."""

    def __init__(self, text: Optional[str] = None, raise_error: bool = False) -> None:
        self.text = text
        self.raise_error = raise_error
        self.calls: List[str] = []

    def generate_text(self, prompt: str, **kwargs: Any) -> Optional[str]:
        self.calls.append(prompt)
        if self.raise_error:
            raise RuntimeError("llm backend down")
        return self.text


class _FakeHotspotService:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self.payload = payload

    def get_hotspots(self, **kwargs: Any) -> Dict[str, Any]:
        return self.payload


class _FakeNotifier:
    def __init__(self, available: bool = True, send_ok: bool = True, raise_on_send: bool = False) -> None:
        self.available_flag = available
        self.send_ok = send_ok
        self.raise_on_send = raise_on_send
        self.sent: List[str] = []
        self.saved: List[str] = []

    def is_available(self) -> bool:
        return self.available_flag

    def save_report_to_file(self, content: str, filename: str) -> str:
        self.saved.append(filename)
        return filename

    def send(self, content: str, **kwargs: Any) -> bool:
        if self.raise_on_send:
            raise RuntimeError("channel down")
        self.sent.append(content)
        return self.send_ok


def _config(tmp_dir: str, **overrides: Any) -> SimpleNamespace:
    base = {
        "hot_top10_enabled": True,
        "hot_top10_schedule_time": "15:10",
        "hot_top10_count": 10,
        "report_language": "zh",
        "trading_day_check_enabled": True,
        "database_path": str(Path(tmp_dir) / "stock_analysis.db"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class HotTop10ServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Default: CN market open so the trading-day gate passes.
        patcher = mock.patch(
            "src.core.trading_calendar.get_open_markets_today",
            return_value={"cn"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    # ------------------------------------------------------------------ helpers

    def _run(self, config, *, analyzer=None, notifier=None, hotspot_items=None, **kwargs) -> HotTop10RunResult:
        analyzer = analyzer or _FakeAnalyzer(text=_llm_json())
        notifier = notifier or _FakeNotifier()
        items = _theme_items(hotspot_items if hotspot_items is not None else 3)
        service = _FakeHotspotService(_hotspot_payload(items))
        with mock.patch(
            "src.services.hot_top10_service._build_analyzer", return_value=analyzer
        ):
            return run_hot_top10_analysis(
                config,
                notifier=notifier,
                hotspot_service=service,
                **kwargs,
            )

    # ------------------------------------------------------------------ tests

    def test_normal_path_renders_report_and_pushes(self):
        config = _config(self._tmp.name)
        notifier = _FakeNotifier()
        result = self._run(config, notifier=notifier, hotspot_items=3)

        self.assertTrue(result.delivered)
        self.assertFalse(result.skipped)
        self.assertTrue(result.llm_completed)
        self.assertIn("主题1", result.report_markdown)
        self.assertIn("轻仓介入", result.report_markdown)
        # Report header carries generation timestamp and data-source note.
        self.assertIn("数据来源", result.report_markdown)
        self.assertEqual(len(notifier.sent), 1)
        self.assertTrue(notifier.saved)
        # Daily marker recorded after a successful push.
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertTrue(skip)

    def test_second_run_same_day_is_skipped(self):
        config = _config(self._tmp.name)
        self._run(config)
        notifier = _FakeNotifier()
        result = self._run(config, notifier=notifier)

        self.assertTrue(result.skipped)
        self.assertFalse(result.delivered)
        self.assertIsNone(result.report_markdown)
        self.assertEqual(notifier.sent, [])

    def test_fewer_hotspots_than_count_uses_available_items(self):
        config = _config(self._tmp.name, hot_top10_count=10)
        notifier = _FakeNotifier()
        result = self._run(config, notifier=notifier, hotspot_items=2)

        self.assertTrue(result.delivered)
        self.assertIn("主题1", result.report_markdown)
        self.assertNotIn("主题10", result.report_markdown)

    def test_llm_failure_degrades_to_data_only_report(self):
        config = _config(self._tmp.name)
        analyzer = _FakeAnalyzer(text=None)
        notifier = _FakeNotifier()
        result = self._run(config, analyzer=analyzer, notifier=notifier)

        self.assertTrue(result.delivered)
        self.assertFalse(result.llm_completed)
        self.assertIn("主题1", result.report_markdown)
        # The degraded report still goes out through the notification channel.
        self.assertEqual(len(notifier.sent), 1)
        self.assertIn("AI", result.report_markdown)

    def test_notification_failure_never_raises_and_marker_not_recorded(self):
        config = _config(self._tmp.name)
        notifier = _FakeNotifier(raise_on_send=True)
        result = self._run(config, notifier=notifier)

        self.assertTrue(result.delivered)
        self.assertIsNotNone(result.report_markdown)
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)

    def test_send_returning_false_marker_not_recorded(self):
        config = _config(self._tmp.name)
        notifier = _FakeNotifier(send_ok=False)
        result = self._run(config, notifier=notifier)

        self.assertTrue(result.delivered)
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)

    def test_corrupt_marker_fails_open(self):
        config = _config(self._tmp.name)
        marker = hot_top10_marker_path(config)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{not json", encoding="utf-8")

        skip, reason = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)
        self.assertIn("fail-open", reason)

        notifier = _FakeNotifier()
        result = self._run(config, notifier=notifier)
        self.assertFalse(result.skipped)
        self.assertEqual(len(notifier.sent), 1)

    def test_non_trading_day_skips_scheduled_run(self):
        config = _config(self._tmp.name)
        with mock.patch(
            "src.core.trading_calendar.get_open_markets_today",
            return_value={"us"},
        ):
            result = self._run(config, notifier=_FakeNotifier())

        self.assertTrue(result.skipped)
        self.assertIn("trading", result.reason.lower())

    def test_force_run_bypasses_trading_day_gate(self):
        config = _config(self._tmp.name)
        with mock.patch(
            "src.core.trading_calendar.get_open_markets_today",
            return_value=set(),
        ):
            result = self._run(config, force_run=True)

        self.assertFalse(result.skipped)
        self.assertTrue(result.delivered)

    def test_hotspots_unavailable_reports_failure(self):
        config = _config(self._tmp.name)
        analyzer = _FakeAnalyzer(text=_llm_json())
        notifier = _FakeNotifier()
        service = _FakeHotspotService(
            {
                "status": "unknown",
                "market": "cn",
                "trade_date": None,
                "active_themes": [],
                "leading_industries": [],
                "leading_concepts": [],
                "lagging_themes": [],
                "data_quality": {"status": "unknown", "missing_fields": [], "sources": [], "errors": ["x"]},
            }
        )
        with mock.patch(
            "src.services.hot_top10_service._build_analyzer", return_value=analyzer
        ):
            result = run_hot_top10_analysis(
                config, notifier=notifier, hotspot_service=service
            )

        self.assertFalse(result.delivered)
        self.assertTrue(result.skipped)
        self.assertIn("hotspot", result.reason.lower())
        self.assertEqual(notifier.sent, [])

    def test_english_report_language_renders_english_labels(self):
        config = _config(self._tmp.name, report_language="en")
        result = self._run(config)

        self.assertTrue(result.delivered)
        self.assertIn("Data source", result.report_markdown)

    def test_record_marker_swallows_write_errors(self):
        config = _config(self._tmp.name)
        # Point the marker at a path that cannot be a file.
        with mock.patch(
            "src.services.hot_top10_service.hot_top10_marker_path",
            return_value=Path(self._tmp.name) / "reserved" / "state.json",
        ):
            record_hot_top10_marker(config, llm_completed=True, notification_status="sent")
        # No exception raised is the contract.

    def test_marker_respects_dedup_disabled(self):
        config = _config(self._tmp.name)
        self._run(config)
        notifier = _FakeNotifier()
        result = self._run(config, notifier=notifier, respect_dedup=False)

        self.assertFalse(result.skipped)
        self.assertEqual(len(notifier.sent), 1)


class HotTop10ConfigContractTest(unittest.TestCase):
    """Config parse + registry registration contract for the HOT_TOP10_* keys."""

    def test_config_defaults_are_off(self):
        from src.config import Config

        config = Config._load_from_env()
        self.assertFalse(config.hot_top10_enabled)
        self.assertEqual(config.hot_top10_schedule_time, "15:10")
        self.assertEqual(config.hot_top10_count, 10)

    def test_config_env_overrides(self):
        from src.config import Config

        with mock.patch.dict(
            "os.environ",
            {
                "HOT_TOP10_ENABLED": "true",
                "HOT_TOP10_SCHEDULE_TIME": "09:40",
                "HOT_TOP10_COUNT": "5",
            },
        ):
            config = Config._load_from_env()
        self.assertTrue(config.hot_top10_enabled)
        self.assertEqual(config.hot_top10_schedule_time, "09:40")
        self.assertEqual(config.hot_top10_count, 5)

    def test_invalid_schedule_time_falls_back(self):
        from src.config import Config

        with mock.patch.dict(
            "os.environ",
            {"HOT_TOP10_SCHEDULE_TIME": "not-a-time", "HOT_TOP10_COUNT": "999"},
        ):
            config = Config._load_from_env()
        self.assertEqual(config.hot_top10_schedule_time, "15:10")
        self.assertEqual(config.hot_top10_count, 30)

    def test_registry_keys_are_registered_with_help_metadata(self):
        from src.core.config_registry import get_field_definition

        expected = {
            "HOT_TOP10_ENABLED": ("boolean", "switch", "false"),
            "HOT_TOP10_SCHEDULE_TIME": ("string", "text", "15:10"),
            "HOT_TOP10_COUNT": ("integer", "number", "10"),
        }
        for key, (data_type, ui_control, default_value) in expected.items():
            field = get_field_definition(key)
            self.assertEqual(field["data_type"], data_type, key)
            self.assertEqual(field["ui_control"], ui_control, key)
            self.assertEqual(field["default_value"], default_value, key)
            self.assertTrue(field.get("help_key"), key)
            self.assertTrue(field.get("examples"), key)
            self.assertTrue(field.get("docs"), key)
            self.assertEqual(field["category"], "system", key)


class HotTop10SchedulerWiringTest(unittest.TestCase):
    """The generic extra-daily-job hook used by the hot-top10 schedule."""

    def test_add_daily_task_registers_fail_open_job(self):
        from src.scheduler import Scheduler

        scheduler = Scheduler(register_signals=False, schedule_time="23:59")
        calls = []

        def job():
            calls.append(1)
            raise RuntimeError("auxiliary job failed")

        self.assertTrue(scheduler.add_daily_task(job, "15:10", name="hot_top10"))
        self.assertEqual(len(scheduler._extra_daily_jobs), 1)
        # The registered wrapper swallows the exception (fail-open).
        scheduler._extra_daily_jobs[0].job_func()
        self.assertEqual(len(calls), 1)

    def test_add_daily_task_rejects_invalid_time(self):
        from src.scheduler import Scheduler

        scheduler = Scheduler(register_signals=False, schedule_time="23:59")
        self.assertFalse(scheduler.add_daily_task(lambda: None, "25:00"))
        self.assertEqual(scheduler._extra_daily_jobs, [])


if __name__ == "__main__":
    unittest.main()
