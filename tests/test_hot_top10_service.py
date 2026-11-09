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
import threading
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest import mock

from src.services.hot_top10_service import (
    HotTop10RunResult,
    _collect_hot_list_items,
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
    def __init__(
        self,
        available: bool = True,
        send_ok: bool = True,
        raise_on_send: bool = False,
        raise_on_save: bool = False,
    ) -> None:
        self.available_flag = available
        self.send_ok = send_ok
        self.raise_on_send = raise_on_send
        self.raise_on_save = raise_on_save
        self.sent: List[str] = []
        self.saved: List[str] = []

    def is_available(self) -> bool:
        return self.available_flag

    def save_report_to_file(self, content: str, filename: str) -> str:
        if self.raise_on_save:
            raise PermissionError("report directory is read-only")
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

    def test_save_failure_with_no_channel_keeps_marker_open_for_retry(self):
        """OR-COR-8c2d195e: a save failure with no notification channel
        delivers nothing, so the day's dedup marker must stay open and the
        next occurrence must retry once storage recovers."""
        config = _config(self._tmp.name)
        broken = _FakeNotifier(available=False, raise_on_save=True)
        first = self._run(config, notifier=broken)

        self.assertEqual(first.notification_status, "no_channel")
        self.assertFalse(first.delivered)
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)

        # Storage recovered on the next occurrence: the report is saved and
        # the marker is recorded even though no notification channel exists.
        recovered = _FakeNotifier(available=False)
        second = self._run(config, notifier=recovered)

        self.assertEqual(second.notification_status, "no_channel")
        self.assertTrue(second.delivered)
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertTrue(skip)

    def test_save_failure_with_disabled_notification_keeps_marker_open(self):
        """OR-COR-8c2d195e: --no-notify runs rely on the local save, so a
        failed save must not consume the day's dedup slot either."""
        config = _config(self._tmp.name)
        broken = _FakeNotifier(raise_on_save=True)
        result = self._run(config, notifier=broken, send_notification=False)

        self.assertEqual(result.notification_status, "disabled")
        self.assertFalse(result.delivered)
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)

    def test_save_failure_with_successful_push_still_records_marker(self):
        """OR-COR-8c2d195e (boundary): a successful notification push is a
        real delivery, so the marker is recorded even when the local save
        failed."""
        config = _config(self._tmp.name)
        broken = _FakeNotifier(raise_on_save=True)
        result = self._run(config, notifier=broken)

        self.assertEqual(result.notification_status, "sent")
        self.assertTrue(result.delivered)
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertTrue(skip)

    def test_overlapping_trigger_skips_without_push_or_marker(self):
        """OR-COR-9a41d2ce: a trigger fired while another hot-top10 run is
        still in flight (slow LLM, e.g. the 15:10 primary still running at
        15:35) must exit immediately — no push, no marker — and the
        in-flight run completes alone. The two triggers are NOT joined
        between occurrences."""
        config = _config(self._tmp.name)
        release_llm = threading.Event()

        class _BlockingAnalyzer:
            def __init__(self, text: str) -> None:
                self.text = text
                self.entered = threading.Event()

            def generate_text(self, prompt: str, **kwargs: Any) -> str:
                self.entered.set()
                release_llm.wait(timeout=10)
                return self.text

        analyzer = _BlockingAnalyzer(_llm_json())
        service = _FakeHotspotService(_hotspot_payload(_theme_items(3)))
        first_notifier = _FakeNotifier()
        first_results: Dict[str, HotTop10RunResult] = {}

        def _primary_run() -> None:
            first_results["run"] = run_hot_top10_analysis(
                config,
                notifier=first_notifier,
                hotspot_service=service,
                analyzer=analyzer,
            )

        primary = threading.Thread(target=_primary_run, daemon=True)
        primary.start()
        self.assertTrue(analyzer.entered.wait(timeout=5))

        # The second slot fires while the first run is still inside the LLM
        # call — no join between the two occurrences.
        second_notifier = _FakeNotifier()
        second = run_hot_top10_analysis(
            config,
            notifier=second_notifier,
            hotspot_service=service,
            analyzer=_FakeAnalyzer(text=_llm_json()),
        )

        self.assertFalse(second.delivered)
        self.assertTrue(second.skipped)
        self.assertEqual(second.reason, "already_running")
        self.assertEqual(second_notifier.sent, [])
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)  # the overlapping trigger consumed nothing

        release_llm.set()
        primary.join(timeout=10)
        self.assertTrue(first_results["run"].delivered)
        self.assertEqual(len(first_notifier.sent), 1)
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertTrue(skip)  # the in-flight run recorded the marker

    def test_concurrent_triggers_deliver_exactly_once(self):
        """OR-COR-9a41d2ce: two slots firing near-simultaneously (e.g. both
        schedule times set to the same HH:MM) must yield exactly ONE
        delivery — the loser exits with reason=already_running and writes
        nothing."""
        config = _config(self._tmp.name)
        release_llm = threading.Event()

        class _BlockingAnalyzer:
            def generate_text(self, prompt: str, **kwargs: Any) -> str:
                release_llm.wait(timeout=10)
                return _llm_json()

        service = _FakeHotspotService(_hotspot_payload(_theme_items(3)))
        notifier_a = _FakeNotifier()
        notifier_b = _FakeNotifier()
        results: Dict[str, HotTop10RunResult] = {}

        def _trigger(tag: str, notifier: _FakeNotifier) -> None:
            results[tag] = run_hot_top10_analysis(
                config,
                notifier=notifier,
                hotspot_service=service,
                analyzer=_BlockingAnalyzer(),
            )

        thread_a = threading.Thread(
            target=_trigger, args=("a", notifier_a), daemon=True
        )
        thread_b = threading.Thread(
            target=_trigger, args=("b", notifier_b), daemon=True
        )
        thread_a.start()
        thread_b.start()

        # The trigger that loses the mutex exits immediately instead of
        # waiting inside the LLM call with the winner.
        deadline = time.time() + 5
        while time.time() < deadline and len(results) < 1:
            time.sleep(0.02)
        self.assertGreaterEqual(
            len(results), 1, "both triggers stayed blocked inside the run"
        )

        release_llm.set()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)
        self.assertEqual(len(results), 2)

        delivered = [r for r in results.values() if r.delivered]
        overlapped = [
            r for r in results.values() if r.reason == "already_running"
        ]
        self.assertEqual(len(delivered), 1)
        self.assertEqual(len(overlapped), 1)
        self.assertEqual(len(notifier_a.sent) + len(notifier_b.sent), 1)
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertTrue(skip)

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
        self.assertEqual(config.hot_top10_data_ready_schedule_time, "15:35")
        self.assertEqual(config.hot_top10_count, 10)

    def test_config_env_overrides(self):
        from src.config import Config

        with mock.patch.dict(
            "os.environ",
            {
                "HOT_TOP10_ENABLED": "true",
                "HOT_TOP10_SCHEDULE_TIME": "09:40",
                "HOT_TOP10_DATA_READY_SCHEDULE_TIME": "16:05",
                "HOT_TOP10_COUNT": "5",
            },
        ):
            config = Config._load_from_env()
        self.assertTrue(config.hot_top10_enabled)
        self.assertEqual(config.hot_top10_schedule_time, "09:40")
        self.assertEqual(config.hot_top10_data_ready_schedule_time, "16:05")
        self.assertEqual(config.hot_top10_count, 5)

    def test_invalid_schedule_time_falls_back(self):
        from src.config import Config

        with mock.patch.dict(
            "os.environ",
            {
                "HOT_TOP10_SCHEDULE_TIME": "not-a-time",
                "HOT_TOP10_DATA_READY_SCHEDULE_TIME": "also-bad",
                "HOT_TOP10_COUNT": "999",
            },
        ):
            config = Config._load_from_env()
        self.assertEqual(config.hot_top10_schedule_time, "15:10")
        self.assertEqual(config.hot_top10_data_ready_schedule_time, "15:35")
        self.assertEqual(config.hot_top10_count, 30)

    def test_registry_keys_are_registered_with_help_metadata(self):
        from src.core.config_registry import get_field_definition

        expected = {
            "HOT_TOP10_ENABLED": ("boolean", "switch", "false"),
            "HOT_TOP10_SCHEDULE_TIME": ("string", "text", "15:10"),
            "HOT_TOP10_DATA_READY_SCHEDULE_TIME": ("string", "text", "15:35"),
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


class HotTop10MergedSelectionTest(unittest.TestCase):
    """OR-COR-a7e7c3a3: candidates from all buckets compete by change_pct.

    The old collector read buckets sequentially and stopped once ``count``
    items were gathered. Because ``active_themes`` only keeps positive
    gainers, a day where the top industries are deeply negative used to
    evict small-negative concepts from the list even though they ranked
    higher by change_pct.
    """

    @staticmethod
    def _review_payload() -> Dict[str, Any]:
        return {
            "status": "partial",
            "market": "cn",
            "trade_date": date.today().isoformat(),
            "active_themes": [],
            "leading_industries": [
                {"name": "行业A", "code": "BKI1", "change_pct": -2.0, "rank": 1},
                {"name": "行业B", "code": "BKI2", "change_pct": -3.0, "rank": 2},
            ],
            "leading_concepts": [
                {"name": "概念C", "code": "BKC1", "change_pct": -0.1, "rank": 1},
                {"name": "概念D", "code": "BKC2", "change_pct": -0.2, "rank": 2},
            ],
            "lagging_themes": [],
            "data_quality": {"status": "partial", "missing_fields": [], "sources": [], "errors": []},
        }

    def test_negative_industries_do_not_evict_small_negative_concepts(self):
        service = _FakeHotspotService(self._review_payload())
        items, _ranking_date = _collect_hot_list_items(2, hotspot_service=service)
        self.assertIsNotNone(items)
        self.assertEqual([item["name"] for item in items], ["概念C", "概念D"])
        self.assertEqual([item["rank"] for item in items], [1, 2])
        self.assertEqual([item["kind"] for item in items], ["concept", "concept"])

    def test_merged_candidates_sorted_by_change_pct_descending(self):
        service = _FakeHotspotService(self._review_payload())
        items, _ranking_date = _collect_hot_list_items(4, hotspot_service=service)
        self.assertIsNotNone(items)
        self.assertEqual(
            [item["name"] for item in items],
            ["概念C", "概念D", "行业A", "行业B"],
        )
        self.assertEqual([item["rank"] for item in items], [1, 2, 3, 4])

    def test_items_without_change_pct_sort_after_numbered_items(self):
        payload = self._review_payload()
        payload["leading_concepts"].append(
            {"name": "概念E", "code": "BKC3", "change_pct": None, "rank": 3}
        )
        service = _FakeHotspotService(payload)
        items, _ranking_date = _collect_hot_list_items(5, hotspot_service=service)
        self.assertIsNotNone(items)
        self.assertEqual(
            [item["name"] for item in items],
            ["概念C", "概念D", "行业A", "行业B", "概念E"],
        )


class HotTop10RankingDateTest(unittest.TestCase):
    """OR-COR-3e7f490e: the real ranking date must survive the whole chain.

    Tushare serves the previous trading day's board rankings before the
    daily data cut. A delivered report must be labeled with the actual
    ranking date, and a stale (previous-day) delivery must not consume
    today's dedup marker so the regular entry can re-deliver once today's
    data becomes available.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch(
            "src.core.trading_calendar.get_open_markets_today",
            return_value={"cn"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.yesterday = (date.today() - timedelta(days=1)).isoformat()

    def _run_with_payload(self, config, payload, analyzer=None, notifier=None):
        analyzer = analyzer or _FakeAnalyzer(text=_llm_json())
        notifier = notifier or _FakeNotifier()
        service = _FakeHotspotService(payload)
        with mock.patch(
            "src.services.hot_top10_service._build_analyzer", return_value=analyzer
        ):
            result = run_hot_top10_analysis(
                config, notifier=notifier, hotspot_service=service
            )
        return result, analyzer, notifier

    def test_stale_ranking_date_labeled_and_marker_kept_open(self):
        config = _config(self._tmp.name)
        payload = _hotspot_payload(_theme_items(3))
        payload["trade_date"] = self.yesterday

        result, analyzer, _notifier = self._run_with_payload(config, payload)

        self.assertTrue(result.delivered)
        self.assertEqual(result.ranking_date, self.yesterday)
        # Prompt tells the model the list is from the ranking date, not today.
        self.assertIn("榜单日期", analyzer.calls[0])
        self.assertIn(self.yesterday, analyzer.calls[0])
        # Report prominently labels the actual ranking date.
        self.assertIn("榜单日期", result.report_markdown)
        self.assertIn(self.yesterday, result.report_markdown)
        # Stale delivery must not consume today's dedup marker.
        skip, reason = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)
        # The marker still records the data date for auditability.
        marker_payload = json.loads(
            hot_top10_marker_path(config).read_text(encoding="utf-8")
        )
        self.assertEqual(marker_payload.get("data_date"), self.yesterday)
        self.assertEqual(marker_payload.get("run_date"), date.today().isoformat())

    def test_fresh_data_after_stale_delivery_still_delivers(self):
        config = _config(self._tmp.name)
        stale_payload = _hotspot_payload(_theme_items(3))
        stale_payload["trade_date"] = self.yesterday
        stale_result, _, _ = self._run_with_payload(config, stale_payload)
        self.assertTrue(stale_result.delivered)

        fresh_payload = _hotspot_payload(_theme_items(3))
        fresh_result, _, notifier = self._run_with_payload(
            config, fresh_payload, notifier=_FakeNotifier()
        )
        self.assertTrue(fresh_result.delivered)
        self.assertEqual(len(notifier.sent), 1)
        self.assertEqual(fresh_result.ranking_date, date.today().isoformat())

        # Once today's data is delivered, the same-day dedup marker holds.
        third_result, _, notifier2 = self._run_with_payload(
            config, fresh_payload, notifier=_FakeNotifier()
        )
        self.assertTrue(third_result.skipped)
        self.assertEqual(len(notifier2.sent), 0)

    def test_same_stale_data_date_not_delivered_twice_same_day(self):
        """Data-ready follow-up slot: still-stale data must not re-push.

        When the data-ready occurrence fires but the provider still serves
        the previous trading day's rankings (the very list already delivered
        by the primary slot), the run must skip instead of pushing the same
        stale report a second time.
        """
        config = _config(self._tmp.name)
        stale_payload = _hotspot_payload(_theme_items(3))
        stale_payload["trade_date"] = self.yesterday
        first_result, _, _ = self._run_with_payload(config, stale_payload)
        self.assertTrue(first_result.delivered)

        second_result, _, notifier = self._run_with_payload(
            config, stale_payload, notifier=_FakeNotifier()
        )
        self.assertFalse(second_result.delivered)
        self.assertTrue(second_result.skipped)
        self.assertIn(
            "same_data_date_delivered_today", second_result.reason
        )
        self.assertEqual(len(notifier.sent), 0)
        # The marker still records the stale data date (unchanged).
        marker_payload = json.loads(
            hot_top10_marker_path(config).read_text(encoding="utf-8")
        )
        self.assertEqual(marker_payload.get("data_date"), self.yesterday)

    def test_stale_redelivery_allowed_when_marker_from_earlier_day(self):
        """The same-data-date guard is strictly SAME-DAY (review scope).

        A marker left by an earlier run date must not block a delivery, so
        the pre-existing fail-open behavior for old markers is unchanged.
        """
        config = _config(self._tmp.name)
        marker_path = hot_top10_marker_path(config)
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    # Same stale data date, but recorded on an earlier run
                    # date: the guard is same-day only and must fail open.
                    "run_date": (date.today() - timedelta(days=1)).isoformat(),
                    "data_date": self.yesterday,
                    "delivered": True,
                    "llm_completed": True,
                    "notification_status": "sent",
                }
            ),
            encoding="utf-8",
        )

        stale_payload = _hotspot_payload(_theme_items(3))
        stale_payload["trade_date"] = self.yesterday
        result, _, notifier = self._run_with_payload(
            config, stale_payload, notifier=_FakeNotifier()
        )
        self.assertTrue(result.delivered)
        self.assertEqual(len(notifier.sent), 1)

    def test_collect_returns_payload_ranking_date(self):
        payload = _hotspot_payload(_theme_items(2))
        payload["trade_date"] = self.yesterday
        service = _FakeHotspotService(payload)
        items, ranking_date = _collect_hot_list_items(2, hotspot_service=service)
        self.assertIsNotNone(items)
        self.assertEqual(ranking_date, self.yesterday)

    def test_collect_falls_back_to_item_trade_date(self):
        payload = _hotspot_payload([])
        payload["trade_date"] = None
        payload["active_themes"] = [
            {
                "name": "主题X",
                "code": "BKX1",
                "change_pct": 1.5,
                "rank": 1,
                "source": "industry",
                "trade_date": self.yesterday,
            }
        ]
        service = _FakeHotspotService(payload)
        items, ranking_date = _collect_hot_list_items(2, hotspot_service=service)
        self.assertIsNotNone(items)
        self.assertEqual(ranking_date, self.yesterday)


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
        # The registered wrapper dispatches to a background thread (the
        # scheduler loop must not block) and swallows the exception there.
        scheduler._extra_daily_jobs[0].job_func()
        scheduler._join_extra_daily_job_workers(timeout=5)
        self.assertEqual(len(calls), 1)
        # The in-flight slot is released once the worker finished.
        self.assertEqual(scheduler._extra_job_workers, {})

    def test_add_daily_task_rejects_invalid_time(self):
        from src.scheduler import Scheduler

        scheduler = Scheduler(register_signals=False, schedule_time="23:59")
        self.assertFalse(scheduler.add_daily_task(lambda: None, "25:00"))
        self.assertEqual(scheduler._extra_daily_jobs, [])


if __name__ == "__main__":
    unittest.main()
