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
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import date, datetime, timedelta
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
from src.services import hot_top10_service as hot_top10_svc
from src.services.hot_top10_service import (
    HOT_TOP10_CLAIM_STALE_AFTER,
    acquire_hot_top10_delivery_claim,
    hot_top10_claim_path,
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

    def test_pending_followup_delivers_fresh_data_after_overlap(self):
        """OR-COR-7c92a610 probe: the primary run is still in flight (slow
        LLM) when the data-ready trigger fires, and the provider has already
        switched to today's rankings. The losing trigger must not be dropped:
        the service keeps a one-shot pending follow-up, and after the primary
        delivers the stale list the follow-up re-executes, fetches the fresh
        data and delivers it (marker = new data date). The two triggers are
        NOT joined between occurrences."""
        config = _config(self._tmp.name)
        release_llm = threading.Event()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        payload_holder = {
            "payload": _hotspot_payload(_theme_items(3)),
        }
        payload_holder["payload"]["trade_date"] = yesterday

        class _BlockingAnalyzer:
            def __init__(self) -> None:
                self.entered = threading.Event()

            def generate_text(self, prompt: str, **kwargs: Any) -> str:
                self.entered.set()
                release_llm.wait(timeout=10)
                return _llm_json()

        class _HolderHotspotService:
            def get_hotspots(self, **kwargs: Any) -> Dict[str, Any]:
                return payload_holder["payload"]

        analyzer = _BlockingAnalyzer()
        notifier = _FakeNotifier()
        primary_results: Dict[str, HotTop10RunResult] = {}

        def _primary_run() -> None:
            primary_results["run"] = run_hot_top10_analysis(
                config,
                notifier=notifier,
                hotspot_service=_HolderHotspotService(),
                analyzer=analyzer,
            )

        primary = threading.Thread(target=_primary_run, daemon=True)
        primary.start()
        self.assertTrue(analyzer.entered.wait(timeout=5))

        # The data cut passes and the provider now serves TODAY's rankings
        # while the primary is still inside its LLM call.
        payload_holder["payload"] = _hotspot_payload(_theme_items(3))
        payload_holder["payload"]["trade_date"] = date.today().isoformat()

        # The data-ready trigger fires — no join before this point.
        overlap = run_hot_top10_analysis(
            config,
            notifier=_FakeNotifier(),
            hotspot_service=_HolderHotspotService(),
            analyzer=_FakeAnalyzer(text=_llm_json()),
        )
        self.assertFalse(overlap.delivered)
        self.assertEqual(overlap.reason, "already_running")

        # The primary finishes and the retained follow-up request must be
        # consumed automatically: fresh data is fetched, dedup passes (the
        # marker only covers the stale data date) and today's list ships.
        release_llm.set()
        primary.join(timeout=15)

        self.assertTrue(primary_results["run"].delivered)
        self.assertEqual(len(notifier.sent), 2)  # stale, then fresh
        marker_payload = json.loads(
            hot_top10_marker_path(config).read_text(encoding="utf-8")
        )
        self.assertEqual(marker_payload.get("data_date"), date.today().isoformat())
        self.assertEqual(marker_payload.get("run_date"), date.today().isoformat())
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
        # The marker still records the data date for auditability (its own
        # per-date file since r7, OR-COR-341d7b5a).
        marker_payload = json.loads(
            hot_top10_marker_path(
                config, self.yesterday
            ).read_text(encoding="utf-8")
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
        # The marker still records the stale data date (unchanged, in its
        # own per-date file since r7).
        marker_payload = json.loads(
            hot_top10_marker_path(
                config, self.yesterday
            ).read_text(encoding="utf-8")
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


# Child script for the cross-process claim regression: two REAL processes
# contend for the same data date through a shared marker directory.
_CLAIM_RUNNER_SCRIPT = """
import json
import os
import sys
import time

sys.path.insert(0, sys.argv[1])

from types import SimpleNamespace

from src.services import hot_top10_service as svc

config = SimpleNamespace(
    database_path=sys.argv[2],
    trading_day_check_enabled=False,
    hot_top10_count=10,
    report_language="zh",
)
data_date = sys.argv[3]
go_file = sys.argv[4]
llm_block_file = os.environ.get("HOT_TOP10_TEST_LLM_BLOCK", "")
pid = os.getpid()


class _Hotspots:
    def get_hotspots(self, **kwargs):
        return {
            "status": "ok",
            "market": "cn",
            "trade_date": data_date,
            "active_themes": [
                {
                    "name": f"主题-{pid}",
                    "code": "BK0001",
                    "change_pct": 1.0,
                    "rank": 1,
                    "source": "industry",
                }
            ],
            "leading_industries": [],
            "leading_concepts": [],
        }


class _Analyzer:
    def generate_text(self, prompt, **kwargs):
        deadline = time.time() + 30
        while llm_block_file and not os.path.exists(llm_block_file):
            if time.time() >= deadline:
                break
            time.sleep(0.02)
        return json.dumps({"summary": "s", "items": []}, ensure_ascii=False)


class _Notifier:
    def is_available(self):
        return True

    def save_report_to_file(self, content, filename):
        return filename

    def send(self, content, **kwargs):
        return True


print("READY", flush=True)
deadline = time.time() + 30
while not os.path.exists(go_file):
    if time.time() >= deadline:
        break
    time.sleep(0.02)

result = svc.run_hot_top10_analysis(
    config,
    notifier=_Notifier(),
    analyzer=_Analyzer(),
    hotspot_service=_Hotspots(),
)
print(
    "RESULT:"
    + json.dumps(
        {
            "delivered": result.delivered,
            "skipped": result.skipped,
            "reason": result.reason,
        }
    ),
    flush=True,
)
"""


class HotTop10CrossProcessClaimTest(unittest.TestCase):
    """OR-COR-5c51e8d7: the daily dedup had no cross-process mutual
    exclusion — two scheduler processes sharing the same DATABASE_PATH both
    passed the empty-marker check and pushed the same list twice, because
    the run's critical section was only protected by a per-process
    ``threading.Lock``. A per-data-date atomic claim file must make
    check -> generate -> save -> push -> marker exclusive across processes."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch(
            "src.core.trading_calendar.get_open_markets_today",
            return_value={"cn"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _start_children(
        self, db_path: Path, data_date: str, go_file: Path, llm_release: Path
    ):
        repo_root = str(Path(__file__).resolve().parents[1])
        child_script = Path(self._tmp.name) / "claim_runner.py"
        child_script.write_text(_CLAIM_RUNNER_SCRIPT, encoding="utf-8")
        procs = []
        for _ in range(2):
            env = dict(os.environ)
            env["HOT_TOP10_TEST_LLM_BLOCK"] = str(llm_release)
            env["PYTHONIOENCODING"] = "utf-8"
            procs.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(child_script),
                        repo_root,
                        str(db_path),
                        data_date,
                        str(go_file),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    env=env,
                    cwd=repo_root,
                )
            )
        self.addCleanup(self._drain_children, procs, llm_release)
        return procs

    @staticmethod
    def _drain_children(procs, llm_release: Path) -> None:
        try:
            llm_release.write_text("release", encoding="utf-8")
        except OSError:
            pass
        for proc in procs:
            if proc.poll() is None:
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_two_processes_deliver_same_data_date_exactly_once(self):
        db_path = Path(self._tmp.name) / "stock_analysis.db"
        data_date = date.today().isoformat()
        claim_path = db_path.parent / f"hot_top10_claim_{data_date}.lock"
        go_file = Path(self._tmp.name) / "go"
        llm_release = Path(self._tmp.name) / "llm_release"
        procs = self._start_children(db_path, data_date, go_file, llm_release)

        for proc in procs:
            ready = proc.stdout.readline().strip()
            self.assertEqual(ready, "READY", "child failed to boot")
        go_file.write_text("go", encoding="utf-8")

        # The winning process holds the claim while blocked in the LLM call,
        # so the loser must deterministically observe the claim.
        deadline = time.time() + 15
        while time.time() < deadline and not claim_path.exists():
            time.sleep(0.02)
        self.assertTrue(claim_path.exists(), "no claim file appeared")
        llm_release.write_text("release", encoding="utf-8")

        results = []
        for proc in procs:
            line = proc.stdout.readline().strip()
            self.assertTrue(
                line.startswith("RESULT:"), f"child produced no result: {line!r}"
            )
            results.append(json.loads(line[len("RESULT:") :]))
        for proc in procs:
            proc.wait(timeout=30)

        delivered = [r for r in results if r["delivered"]]
        claimed = [r for r in results if r["reason"] == "already_claimed"]
        self.assertEqual(
            len(delivered), 1, f"exactly one process may deliver: {results}"
        )
        self.assertEqual(len(claimed), 1, f"loser must report claim: {results}")
        self.assertEqual(delivered[0]["reason"], "ok")

        marker_payload = json.loads(
            (
                db_path.parent / f"hot_top10_state_{data_date}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(marker_payload.get("data_date"), data_date)
        self.assertTrue(marker_payload.get("delivered"))
        # The claim is released once the marker landed.
        self.assertFalse(claim_path.exists())

    def test_stale_claim_from_crashed_process_is_taken_over(self):
        """A claim file older than the TTL (crashed process residue) must be
        taken over instead of blocking the day's delivery forever."""
        from src.services.hot_top10_service import hot_top10_claim_path

        config = _config(self._tmp.name)
        stale_time = (
            datetime.now() - timedelta(hours=3)
        ).isoformat(timespec="seconds")
        claim_path = hot_top10_claim_path(config, date.today().isoformat())
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        claim_path.write_text(f"{stale_time}\n999999", encoding="utf-8")

        result = run_hot_top10_analysis(
            config,
            notifier=_FakeNotifier(),
            hotspot_service=_FakeHotspotService(
                _hotspot_payload(_theme_items(3))
            ),
            analyzer=_FakeAnalyzer(text=_llm_json()),
        )

        self.assertTrue(result.delivered)
        # Taken over for the run, then released after the marker landed.
        self.assertFalse(claim_path.exists())

    def test_fresh_claim_from_other_process_blocks_delivery(self):
        """A live (< TTL) claim from another process must skip this run:
        no push, no marker, retry on the next trigger."""
        from src.services.hot_top10_service import hot_top10_claim_path

        config = _config(self._tmp.name)
        claim_path = hot_top10_claim_path(config, date.today().isoformat())
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        claim_path.write_text(
            datetime.now().isoformat(timespec="seconds") + "\n424242",
            encoding="utf-8",
        )

        notifier = _FakeNotifier()
        result = run_hot_top10_analysis(
            config,
            notifier=notifier,
            hotspot_service=_FakeHotspotService(
                _hotspot_payload(_theme_items(3))
            ),
            analyzer=_FakeAnalyzer(text=_llm_json()),
        )

        self.assertFalse(result.delivered)
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "already_claimed")
        self.assertEqual(notifier.sent, [])
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)
        # The other process's claim file is untouched.
        self.assertTrue(claim_path.exists())

    def test_failed_delivery_releases_claim_for_retry(self):
        """Push failure keeps the claim from poisoning the retry: the file is
        released even though no marker was recorded."""
        from src.services.hot_top10_service import hot_top10_claim_path

        config = _config(self._tmp.name)
        claim_path = hot_top10_claim_path(config, date.today().isoformat())
        release = threading.Event()
        entered = threading.Event()

        class _BlockingAnalyzer:
            def generate_text(self, prompt: str, **kwargs: Any) -> str:
                entered.set()
                release.wait(timeout=10)
                return _llm_json()

        analyzer = _BlockingAnalyzer()
        broken = _FakeNotifier(raise_on_send=True)
        first_results: Dict[str, HotTop10RunResult] = {}

        def _first_run() -> None:
            first_results["run"] = run_hot_top10_analysis(
                config,
                notifier=broken,
                hotspot_service=_FakeHotspotService(
                    _hotspot_payload(_theme_items(3))
                ),
                analyzer=analyzer,
            )

        worker = threading.Thread(target=_first_run, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(timeout=5))
        self.assertTrue(
            claim_path.exists(), "claim file must exist while the run delivers"
        )
        release.set()
        worker.join(timeout=10)

        # Failed push: no marker, but the claim was released for the retry.
        self.assertFalse(claim_path.exists())
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)

        retry = run_hot_top10_analysis(
            config,
            notifier=_FakeNotifier(),
            hotspot_service=_FakeHotspotService(
                _hotspot_payload(_theme_items(3))
            ),
            analyzer=_FakeAnalyzer(text=_llm_json()),
        )
        self.assertTrue(retry.delivered)
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertTrue(skip)


# Child script for the OR-COR-5c51e8d7 r5 double-steal race regression: two
# REAL processes contend for the same data date while the claim TTL is
# collapsed to zero, so the second process deterministically steals the claim
# the first process is holding.
_OWNERSHIP_RUNNER_SCRIPT = """
import json
import os
import sys
import time
from datetime import timedelta

sys.path.insert(0, sys.argv[1])

from types import SimpleNamespace

from src.services import hot_top10_service as svc

ttl_text = os.environ.get("HOT_TOP10_TEST_CLAIM_TTL_SECONDS", "")
if ttl_text:
    svc.HOT_TOP10_CLAIM_STALE_AFTER = timedelta(seconds=float(ttl_text))

# r7: force the explicitly-degraded (no OS locking) path when the parent
# test asks for it; unset in every other test, so this is behavior-neutral.
if os.environ.get("HOT_TOP10_TEST_CLAIM_LOCK_DISABLE", ""):
    svc._CLAIM_LOCKING_AVAILABLE = False

config = SimpleNamespace(
    database_path=sys.argv[2],
    trading_day_check_enabled=False,
    hot_top10_count=10,
    report_language="zh",
)
data_date = sys.argv[3]
go_file = sys.argv[4]
llm_block_file = os.environ.get("HOT_TOP10_TEST_LLM_BLOCK", "")
pid = os.getpid()


class _Hotspots:
    def get_hotspots(self, **kwargs):
        return {
            "status": "ok",
            "market": "cn",
            "trade_date": data_date,
            "active_themes": [
                {
                    "name": f"主题-{pid}",
                    "code": "BK0001",
                    "change_pct": 1.0,
                    "rank": 1,
                    "source": "industry",
                }
            ],
            "leading_industries": [],
            "leading_concepts": [],
        }


class _Analyzer:
    def generate_text(self, prompt, **kwargs):
        deadline = time.time() + 30
        while llm_block_file and not os.path.exists(llm_block_file):
            if time.time() >= deadline:
                break
            time.sleep(0.02)
        return json.dumps({"summary": "s", "items": []}, ensure_ascii=False)


class _Notifier:
    def is_available(self):
        return True

    def save_report_to_file(self, content, filename):
        return filename

    def send(self, content, **kwargs):
        return True


print("READY", flush=True)
deadline = time.time() + 30
while not os.path.exists(go_file):
    if time.time() >= deadline:
        break
    time.sleep(0.02)

result = svc.run_hot_top10_analysis(
    config,
    notifier=_Notifier(),
    analyzer=_Analyzer(),
    hotspot_service=_Hotspots(),
)
print(
    "RESULT:"
    + json.dumps(
        {
            "delivered": result.delivered,
            "skipped": result.skipped,
            "reason": result.reason,
        }
    ),
    flush=True,
)
"""


class HotTop10ClaimOwnershipProtocolTest(unittest.TestCase):
    """OR-COR-5c51e8d7 r5: the cross-process claim primitive must be a FULL
    ownership protocol. r4 defects covered here:

    1. initialization window: between exclusive-create and the timestamp
       write the file was visible but empty, and readers treated empty as
       stale and DELETED a live claim. Empty/unparseable files are live.
    2. takeover was unlink-then-create: two processes both reading a stale
       timestamp each unlinked the other's fresh claim and both delivered.
       Takeover is an atomic rename and the loser detects its lost token
       before any side effect (reason=lost_claim).
    3. release unlinked by path only: an old holder deleted the new owner's
       claim. Release re-verifies ownership (token; for legacy token-less
       files, the first-line timestamp we wrote) before deleting.
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

    # ------------------------------------------------------------------ helpers

    def _run(self, config, notifier=None) -> HotTop10RunResult:
        notifier = notifier or _FakeNotifier()
        with mock.patch(
            "src.services.hot_top10_service._build_analyzer",
            return_value=_FakeAnalyzer(text=_llm_json()),
        ):
            return run_hot_top10_analysis(
                config,
                notifier=notifier,
                hotspot_service=_FakeHotspotService(
                    _hotspot_payload(_theme_items(3))
                ),
            )

    @staticmethod
    def _drain(proc: subprocess.Popen, llm_release: Optional[Path]) -> None:
        try:
            if llm_release is not None:
                llm_release.write_text("release", encoding="utf-8")
        except OSError:
            pass
        if proc.poll() is None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _read_result(self, proc: subprocess.Popen) -> Dict[str, Any]:
        line = proc.stdout.readline().strip()
        if not line.startswith("RESULT:"):
            self.fail(f"child produced no result: {line!r}")
        return json.loads(line[len("RESULT:") :])

    # ------------------------------------------------------------------- tests

    def test_empty_or_unparseable_claim_is_live_and_never_deleted(self):
        """Initialization window: a claim file that exists but is not (yet)
        parseable must be treated LIVE — the run skips with
        ``already_claimed`` and NEVER deletes the file. r4 read the empty
        file as stale and deleted a live claim mid-initialization."""
        config = _config(self._tmp.name)
        claim_path = hot_top10_claim_path(config, date.today().isoformat())
        claim_path.parent.mkdir(parents=True, exist_ok=True)

        # The initialization window: file visible but empty.
        claim_path.write_text("", encoding="utf-8")
        notifier = _FakeNotifier()
        result = self._run(config, notifier=notifier)

        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "already_claimed")
        self.assertEqual(notifier.sent, [])
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)
        self.assertTrue(claim_path.exists(), "live claim must not be deleted")
        self.assertEqual(claim_path.read_text(encoding="utf-8"), "")

        # Same reader semantics for unparseable content (external occupant).
        claim_path.write_text("not-a-timestamp\n", encoding="utf-8")
        result2 = self._run(config)

        self.assertTrue(result2.skipped)
        self.assertEqual(result2.reason, "already_claimed")
        self.assertTrue(claim_path.exists())
        self.assertEqual(
            claim_path.read_text(encoding="utf-8"), "not-a-timestamp\n"
        )

    def test_unparseable_claim_staleness_falls_back_to_mtime(self):
        """Staleness for empty/unparseable claim files falls back to the
        file mtime: freshly touched garbage is live (an occupant), garbage
        older than the TTL is crash residue and is taken over."""
        config = _config(self._tmp.name)
        data_date = date.today().isoformat()
        claim_path = hot_top10_claim_path(config, data_date)
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        claim_path.write_text("garbage", encoding="utf-8")

        claim = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNone(claim, "fresh garbage must count as live")
        self.assertTrue(claim_path.exists())
        self.assertEqual(claim_path.read_text(encoding="utf-8"), "garbage")

        # Push the mtime beyond the TTL: crash residue, takeover wins.
        old_stamp = (
            time.time() - HOT_TOP10_CLAIM_STALE_AFTER.total_seconds() - 300
        )
        os.utime(claim_path, (old_stamp, old_stamp))
        stolen = acquire_hot_top10_delivery_claim(config, data_date)

        self.assertIsNotNone(stolen)
        lines = claim_path.read_text(encoding="utf-8").strip().splitlines()
        # The takeover published the full serialization: ts / token / pid.
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(lines[1]), 32)  # uuid4 hex owner token
        stolen.release()
        self.assertFalse(claim_path.exists())

    @mock.patch.object(
        hot_top10_svc, "_CLAIM_LOCKING_AVAILABLE", False, create=True
    )
    def test_release_does_not_delete_claim_of_new_owner(self):
        """r4 release unlinked by path only, so an old holder deleted the
        new owner's claim after a takeover. Release must re-verify
        ownership and leave a foreign claim byte-identical.

        (r7: runs on the explicitly degraded no-OS-locking path — the TTL-0
        takeover of a SURVIVING holder is impossible under the delivery
        lock, so this interleaving is only reachable without OS locking,
        where the ownership verdict is the only guard.)"""
        config = _config(self._tmp.name)
        data_date = date.today().isoformat()
        claim_path = hot_top10_claim_path(config, data_date)

        holder = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(holder)
        self.assertTrue(claim_path.exists())

        # A competing acquirer steals the claim (TTL collapsed to zero —
        # the double-steal race winner now owns the file).
        with mock.patch.object(
            hot_top10_svc, "HOT_TOP10_CLAIM_STALE_AFTER", timedelta(seconds=0)
        ):
            new_owner = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(new_owner)
        content_after_steal = claim_path.read_text(encoding="utf-8")

        # The old holder's release must NOT delete the new owner's claim.
        holder.release()
        self.assertTrue(claim_path.exists(), "release deleted a foreign claim")
        self.assertEqual(
            claim_path.read_text(encoding="utf-8"), content_after_steal
        )

        # The new owner's own release does remove it.
        new_owner.release()
        self.assertFalse(claim_path.exists())

    @mock.patch.object(
        hot_top10_svc, "_CLAIM_LOCKING_AVAILABLE", False, create=True
    )
    def test_side_effects_aborted_when_claim_lost_before_delivery(self):
        """The final arbiter of the double-steal race: a holder overtaken
        while generating the report must abort before ANY side effect — no
        save, no push, no marker — with reason=lost_claim, and the thief's
        claim must survive the aborted run's cleanup.

        (r7: runs on the explicitly degraded no-OS-locking path — under the
        delivery lock a surviving holder cannot be overtaken at all; the
        per-side-effect re-verification verified here is exactly the
        defence-in-depth that remains on degraded platforms.)"""
        config = _config(self._tmp.name)
        data_date = date.today().isoformat()
        claim_path = hot_top10_claim_path(config, data_date)
        release_llm = threading.Event()

        class _BlockingAnalyzer:
            def __init__(self) -> None:
                self.entered = threading.Event()

            def generate_text(self, prompt: str, **kwargs: Any) -> str:
                self.entered.set()
                release_llm.wait(timeout=10)
                return _llm_json()

        analyzer = _BlockingAnalyzer()
        notifier = _FakeNotifier()
        results: Dict[str, HotTop10RunResult] = {}

        def _holder_run() -> None:
            with mock.patch(
                "src.services.hot_top10_service._build_analyzer",
                return_value=analyzer,
            ):
                results["run"] = run_hot_top10_analysis(
                    config,
                    notifier=notifier,
                    hotspot_service=_FakeHotspotService(
                        _hotspot_payload(_theme_items(3))
                    ),
                )

        worker = threading.Thread(target=_holder_run, daemon=True)
        worker.start()
        self.assertTrue(analyzer.entered.wait(timeout=5))

        # The live claim carries the owner token (ts / token / pid lines).
        live_lines = (
            claim_path.read_text(encoding="utf-8").strip().splitlines()
        )
        self.assertEqual(len(live_lines), 3)
        self.assertEqual(len(live_lines[1]), 32)

        # A competing process steals the held claim (TTL collapsed to zero).
        with mock.patch.object(
            hot_top10_svc, "HOT_TOP10_CLAIM_STALE_AFTER", timedelta(seconds=0)
        ):
            thief = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(thief)

        release_llm.set()
        worker.join(timeout=15)
        result = results["run"]

        self.assertFalse(result.delivered)
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "lost_claim")
        self.assertEqual(notifier.sent, [])
        self.assertEqual(notifier.saved, [])
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)
        # The thief's claim survived the aborted run's release ...
        self.assertTrue(claim_path.exists())
        # ... and is removed only by its rightful owner.
        thief.release()
        self.assertFalse(claim_path.exists())

    def test_legacy_claim_takeover_and_release_timestamp_double_check(self):
        """Backward compatibility with r4 claim files (``{ts}\\n{pid}``, no
        token line): a stale legacy claim is taken over like any other crash
        residue, and release of a token-less (legacy-rewritten) file uses
        the path + first-line timestamp double check."""
        config = _config(self._tmp.name)
        data_date = date.today().isoformat()
        claim_path = hot_top10_claim_path(config, data_date)
        claim_path.parent.mkdir(parents=True, exist_ok=True)

        # (a) A stale legacy-format claim is taken over by a normal run.
        stale_time = (
            datetime.now() - timedelta(hours=3)
        ).isoformat(timespec="seconds")
        claim_path.write_text(f"{stale_time}\n999999", encoding="utf-8")
        result = self._run(config)

        self.assertTrue(result.delivered)
        self.assertFalse(claim_path.exists())

        # (b) Same first line, token stripped: still recognized as ours and
        # deleted by release.
        holder = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(holder)
        first_line = claim_path.read_text(encoding="utf-8").splitlines()[0]
        claim_path.write_text(f"{first_line}\n12345", encoding="utf-8")
        holder.release()
        self.assertFalse(claim_path.exists())

        # (c) A foreign legacy rewrite (different first line) survives the
        # old holder's release.
        holder2 = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(holder2)
        foreign_time = (
            datetime.now() - timedelta(hours=3)
        ).isoformat(timespec="seconds")
        claim_path.write_text(f"{foreign_time}\n777", encoding="utf-8")
        holder2.release()
        self.assertTrue(claim_path.exists())

        # (d) A foreign tokened rewrite survives as well.
        holder3 = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(holder3)
        fresh_time = datetime.now().isoformat(timespec="seconds")
        claim_path.write_text(
            f"{fresh_time}\n{'a' * 32}\n888", encoding="utf-8"
        )
        holder3.release()
        self.assertTrue(claim_path.exists())

    def test_double_steal_race_delivers_exactly_once_loser_reports_lost_claim(
        self,
    ):
        """OR-COR-5c51e8d7 takeover race, end to end in two REAL processes:
        the thief steals the claim the holder is holding (TTL collapsed to
        zero), so the holder must abort before its side effects with
        reason=lost_claim and the thief delivers alone. The r4
        unlink-then-create takeover let BOTH processes deliver."""
        db_path = Path(self._tmp.name) / "stock_analysis.db"
        data_date = date.today().isoformat()
        claim_path = db_path.parent / f"hot_top10_claim_{data_date}.lock"
        go_a = Path(self._tmp.name) / "go_a"
        go_b = Path(self._tmp.name) / "go_b"
        llm_release = Path(self._tmp.name) / "llm_release"
        repo_root = str(Path(__file__).resolve().parents[1])
        child_script = Path(self._tmp.name) / "ownership_runner.py"
        child_script.write_text(_OWNERSHIP_RUNNER_SCRIPT, encoding="utf-8")

        def _spawn(go_file: Path, llm_block: str) -> subprocess.Popen:
            env = dict(os.environ)
            env["HOT_TOP10_TEST_CLAIM_TTL_SECONDS"] = "0"
            # r7: this test pins the r6-era save/notify fences of the
            # double-steal race, which are only reachable without OS
            # locking (under the delivery lock a surviving holder is
            # refused at takeover). Children run the explicit degraded path.
            env["HOT_TOP10_TEST_CLAIM_LOCK_DISABLE"] = "1"
            env["HOT_TOP10_TEST_LLM_BLOCK"] = llm_block
            env["PYTHONIOENCODING"] = "utf-8"
            return subprocess.Popen(
                [
                    sys.executable,
                    str(child_script),
                    repo_root,
                    str(db_path),
                    data_date,
                    str(go_file),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
                cwd=repo_root,
            )

        holder = _spawn(go_a, str(llm_release))
        self.addCleanup(self._drain, holder, llm_release)
        ready = holder.stdout.readline().strip()
        self.assertEqual(ready, "READY", "holder child failed to boot")
        go_a.write_text("go", encoding="utf-8")

        # Deterministic fence: the holder owns the claim while it is blocked
        # inside the LLM call.
        deadline = time.time() + 15
        while time.time() < deadline and not claim_path.exists():
            time.sleep(0.02)
        self.assertTrue(claim_path.exists(), "holder claim never appeared")
        holder_claim_content = claim_path.read_text(encoding="utf-8")

        # The thief starts with its gate already open: it observes the held
        # claim as stale (TTL=0) and steals it via atomic rename.
        go_b.write_text("go", encoding="utf-8")
        thief = _spawn(go_b, "")
        self.addCleanup(self._drain, thief, None)
        ready = thief.stdout.readline().strip()
        self.assertEqual(ready, "READY", "thief child failed to boot")

        # Second fence: wait until the claim file CONTENT changed (or the
        # file is gone because the thief already finished) — the thief's
        # steal landed while the holder still blocks in LLM.
        def _claim_state() -> str:
            try:
                return claim_path.read_text(encoding="utf-8")
            except OSError:
                return "<missing>"

        deadline = time.time() + 15
        while time.time() < deadline:
            if _claim_state() != holder_claim_content:
                break
            time.sleep(0.02)
        self.assertNotEqual(
            _claim_state(),
            holder_claim_content,
            "thief never stole the held claim",
        )

        # Now wake the holder: it must detect the lost token and abort.
        llm_release.write_text("release", encoding="utf-8")
        thief_result = self._read_result(thief)
        holder_result = self._read_result(holder)
        thief.wait(timeout=30)
        holder.wait(timeout=30)

        both = [thief_result, holder_result]
        delivered = [r for r in both if r["delivered"]]
        lost = [r for r in both if r["reason"] == "lost_claim"]
        self.assertEqual(
            len(delivered), 1, f"exactly one process may deliver: {both}"
        )
        self.assertEqual(
            len(lost), 1, f"the loser must abort with lost_claim: {both}"
        )
        winner = delivered[0]
        self.assertEqual(winner["reason"], "ok")
        marker_payload = json.loads(
            (
                db_path.parent / f"hot_top10_state_{data_date}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(marker_payload.get("data_date"), data_date)
        self.assertTrue(marker_payload.get("delivered"))
        self.assertFalse(claim_path.exists())


class HotTop10ClaimMutualExclusionR6Test(unittest.TestCase):
    """OR-COR-5c51e8d7 r6 (review #10): three residual interleavings left
    by the r5 protocol, each pinned with a deterministic fence.

    1. Steal ABA: the takeover replaced whatever was on disk instead of the
       exact stale claim it inspected; a late contender could clobber a
       rival's FRESH takeover. r6 gates the replace on a byte-for-byte
       compare-and-set.
    2. Single delivery-path verdict: ownership was checked once before the
       whole delivery, so a takeover DURING the report save still pushed.
       r6 re-verifies independently before the save AND before the notify.
    3. Release CAS gap: the ownership verdict and the unlink are separated
       by a real (if tiny) window; a steal landing inside it loses its file.
       The window cannot be closed without OS locks — this test pins the
       self-healing invariant: the victim fails its own notify-time
       re-verification, so exactly-once delivery is never broken.
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

    # ------------------------------------------------------------------ helpers

    def _run(self, config, notifier=None) -> HotTop10RunResult:
        notifier = notifier or _FakeNotifier()
        with mock.patch(
            "src.services.hot_top10_service._build_analyzer",
            return_value=_FakeAnalyzer(text=_llm_json()),
        ):
            return run_hot_top10_analysis(
                config,
                notifier=notifier,
                hotspot_service=_FakeHotspotService(
                    _hotspot_payload(_theme_items(3))
                ),
            )

    def _write_stale_legacy_claim(self, config) -> Path:
        claim_path = hot_top10_claim_path(config, date.today().isoformat())
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        stale_time = (
            datetime.now() - timedelta(hours=3)
        ).isoformat(timespec="seconds")
        claim_path.write_text(f"{stale_time}\n999999", encoding="utf-8")
        return claim_path

    # ------------------------------------------------------------------- tests

    @mock.patch.object(
        hot_top10_svc, "_CLAIM_LOCKING_AVAILABLE", False, create=True
    )
    def test_delayed_steal_cas_refuses_to_clobber_rival_takeover(self):
        """Review #10 probe 1: two contenders read the same stale claim;
        the late one parks between its staleness verdict and its replace
        while the rival completes a FULL takeover-and-delivery run. The
        late contender's replace must be refused (compare-and-set) — it
        must not clobber the rival, must not deliver, and the day's
        delivery stays exactly-once."""
        config = _config(self._tmp.name)
        claim_path = self._write_stale_legacy_claim(config)
        entered, resume = threading.Event(), threading.Event()
        real_steal = hot_top10_svc._steal_claim_atomically

        def pausing_steal(*args, **kwargs):
            # Only the LOSER (worker thread) parks here; the rival's steal,
            # running later in the main thread, passes straight through.
            if threading.current_thread() is not threading.main_thread():
                if not entered.is_set():
                    entered.set()
                    resume.wait(timeout=10)
            return real_steal(*args, **kwargs)

        loser: Dict[str, Any] = {}

        def _late_contender() -> None:
            with mock.patch.object(
                hot_top10_svc,
                "_steal_claim_atomically",
                side_effect=pausing_steal,
            ):
                loser["claim"] = acquire_hot_top10_delivery_claim(
                    config, date.today().isoformat()
                )

        worker = threading.Thread(target=_late_contender, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(timeout=5))

        # The rival takes the same stale claim over and runs the WHOLE
        # delivery (steal -> verify -> save -> notify -> marker -> release)
        # while the late contender is parked before its replace.
        rival_notifier = _FakeNotifier()
        rival_result = self._run(config, notifier=rival_notifier)

        self.assertTrue(rival_result.delivered)
        self.assertEqual(len(rival_notifier.sent), 1)
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertTrue(skip)

        # Now the late contender resumes: its compare-and-set must detect
        # that the bytes on disk are no longer the stale claim it inspected.
        resume.set()
        worker.join(timeout=10)

        self.assertIsNone(
            loser["claim"], "CAS steal must abort on a rival takeover"
        )
        # The refused steal left NOTHING behind: the rival's release already
        # removed the claim and the loser must not resurrect a file there.
        self.assertFalse(
            claim_path.exists(),
            "a refused steal must not clobber or recreate the claim",
        )

    @mock.patch.object(
        hot_top10_svc, "_CLAIM_LOCKING_AVAILABLE", False, create=True
    )
    def test_notify_reverify_aborts_when_claim_lost_during_save(self):
        """Review #10 probe 2 (the load-bearing fix): the holder passes the
        save-side ownership check, saves the report, and is overtaken while
        parked between save and notify. The notify-time re-verification
        must abort the push (reason=lost_claim) — the rival is the only
        deliverer, so the mutual exclusion survives a mid-save takeover."""
        config = _config(self._tmp.name)
        data_date = date.today().isoformat()
        claim_path = hot_top10_claim_path(config, data_date)
        save_entered, save_resume = threading.Event(), threading.Event()

        class _ParkingNotifier(_FakeNotifier):
            def save_report_to_file(self, content, filename):
                saved = super().save_report_to_file(content, filename)
                save_entered.set()
                save_resume.wait(timeout=10)
                return saved

        holder_notifier = _ParkingNotifier()
        results: Dict[str, HotTop10RunResult] = {}

        def _holder_run() -> None:
            with mock.patch(
                "src.services.hot_top10_service._build_analyzer",
                return_value=_FakeAnalyzer(text=_llm_json()),
            ):
                results["run"] = run_hot_top10_analysis(
                    config,
                    notifier=holder_notifier,
                    hotspot_service=_FakeHotspotService(
                        _hotspot_payload(_theme_items(3))
                    ),
                )

        worker = threading.Thread(target=_holder_run, daemon=True)
        worker.start()
        # Fence: wait until the holder has PASSED the save-side ownership
        # verdict and completed the save (parked right after it) — the
        # theft must land exactly in the save-to-notify gap.
        self.assertTrue(save_entered.wait(timeout=5))

        # A competing process steals the claim right now (TTL collapsed to
        # zero): AFTER the save-side verdict, BEFORE the notify.
        with mock.patch.object(
            hot_top10_svc, "HOT_TOP10_CLAIM_STALE_AFTER", timedelta(seconds=0)
        ):
            thief = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(thief)

        save_resume.set()
        worker.join(timeout=15)
        result = results["run"]

        # The notify-time re-verification must abort the holder's push.
        self.assertEqual(holder_notifier.sent, [])
        self.assertFalse(result.delivered)
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "lost_claim")
        self.assertEqual(result.notification_status, "lost_claim_before_notify")
        skip, _ = hot_top10_already_delivered_today(config)
        self.assertFalse(skip)  # the loser recorded no marker
        # The thief's claim survived the loser's release ...
        self.assertTrue(claim_path.exists())
        thief.release()
        self.assertFalse(claim_path.exists())

        # Mutual exclusion self-heals: the next full run delivers exactly
        # once (the loser never pushed, so no duplicate is possible).
        retry_notifier = _FakeNotifier()
        retry = self._run(config, notifier=retry_notifier)
        self.assertTrue(retry.delivered)
        self.assertEqual(len(retry_notifier.sent), 1)

    @mock.patch.object(
        hot_top10_svc, "_CLAIM_LOCKING_AVAILABLE", False, create=True
    )
    def test_release_clobber_keeps_exactly_once_invariant(self):
        """Review #10 probe 3: a steal landing between the release's
        ownership verdict and its unlink still deletes the successor's file
        (the honest residual gap of a lock-free release). This pins the
        self-healing invariant: the victim can no longer pass its own
        ownership checks, so no double delivery is possible, and the next
        full run delivers exactly once."""
        config = _config(self._tmp.name)
        data_date = date.today().isoformat()
        claim_path = hot_top10_claim_path(config, data_date)

        victim = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(victim)

        entered, resume = threading.Event(), threading.Event()
        # r6 release reads once and runs the ownership verdict
        # (_text_is_ours) back-to-back with the unlink — the pause hooks the
        # verdict itself, i.e. the instant AFTER it passed.
        real_check = hot_top10_svc._HotTop10DeliveryClaim._text_is_ours

        def pausing_check(self, text):
            result = real_check(self, text)
            if result and not entered.is_set():
                entered.set()
                resume.wait(timeout=10)
            return result

        def _releaser() -> None:
            with mock.patch.object(
                hot_top10_svc._HotTop10DeliveryClaim,
                "_text_is_ours",
                autospec=True,
                side_effect=pausing_check,
            ):
                victim.release()

        worker = threading.Thread(target=_releaser, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(timeout=5))

        # The thief replaces the claim right after the victim passed the
        # release-time ownership verdict (TTL collapsed to zero).
        with mock.patch.object(
            hot_top10_svc, "HOT_TOP10_CLAIM_STALE_AFTER", timedelta(seconds=0)
        ):
            thief = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(thief)

        resume.set()
        worker.join(timeout=10)

        # The residual gap is real: the victim's unlink removed the
        # thief's claim (documented in the PR body — not fixable without
        # OS-level locks).
        self.assertFalse(claim_path.exists())

        # The invariant holds: the victim of the clobber can no longer pass
        # any ownership check, so it can never deliver on top of the next
        # owner — no double delivery is possible.
        self.assertFalse(thief.verify_owner())
        thief.release()  # safe: file already gone

        # Self-healing: the next full run delivers exactly once.
        notifier = _FakeNotifier()
        result = self._run(config, notifier=notifier)
        self.assertTrue(result.delivered)
        self.assertEqual(len(notifier.sent), 1)


class HotTop10ClaimOsLockR7Test(unittest.TestCase):
    """OR-COR-5c51e8d7 r7 (review #11) + OR-COR-341d7b5a.

    Review #11 verdict on the lock-free protocol: user-space read-compare-
    write can NEVER make read and replace atomic (three CAS probe rounds
    were each defeated), so the protocol upgrades to an OS advisory lock
    held for the whole delivery — takeover = lock success (process death
    releases the lock, which is the liveness oracle), release = verify ->
    unlock -> close -> unlink. The r5/r6 owner token, per-side-effect
    re-verification and release ownership checks are kept as defence in
    depth INSIDE the lock. Platforms without OS locking degrade explicitly
    to the r6 compare-and-set path (loud warning, never silent).

    OR-COR-341d7b5a: the single-blob dedup marker was overwritten by a late
    stale delivery, so the retained pending follow-up re-pushed today's
    list. Markers are now one file per data date.
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

    # ------------------------------------------------------------------ helpers

    def _stale_legacy_claim(self, config) -> Path:
        claim_path = hot_top10_claim_path(config, date.today().isoformat())
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        stale_time = (
            datetime.now() - timedelta(hours=3)
        ).isoformat(timespec="seconds")
        claim_path.write_text(f"{stale_time}\n999999", encoding="utf-8")
        return claim_path

    # ------------------------------------------------------------------- tests

    def test_surviving_holder_cannot_be_taken_over(self):
        """Review #11 blocker 1, minimal deterministic form: the holder
        exists and is alive (in r7 it holds the delivery lock); a contender
        judging the claim stale (TTL collapsed to zero) attempts takeover.
        v3 refuses it at the LOCK — r6 RED: the takeover replaced the
        surviving holder's claim and handed the contender a handle."""
        config = _config(self._tmp.name)
        data_date = date.today().isoformat()
        claim_path = self._stale_legacy_claim(config)

        holder = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(holder)
        holder_content = claim_path.read_text(encoding="utf-8")

        # The contender collapses the TTL and attempts the takeover of a
        # SURVIVING holder's claim.
        with mock.patch.object(
            hot_top10_svc, "HOT_TOP10_CLAIM_STALE_AFTER", timedelta(seconds=0)
        ):
            contender = acquire_hot_top10_delivery_claim(config, data_date)

        self.assertIsNone(
            contender, "a surviving holder must refuse takeover at the lock"
        )
        self.assertTrue(claim_path.exists())
        self.assertEqual(
            claim_path.read_text(encoding="utf-8"), holder_content
        )
        holder.release()
        self.assertFalse(claim_path.exists())

    def test_parked_contender_cannot_clobber_surviving_holder(self):
        """Review #11 probe, paused-resume form: the contender parks after
        its staleness verdict and before its takeover action; the surviving
        holder takes the claim over and KEEPS holding the delivery lock. On
        resume the contender must still be refused — under v3 the refusal
        happens at the lock NO MATTER where the contender was parked (the
        window-free property the review demanded); on r6 the CAS happened
        to refuse this exact parking point, which is why the review's own
        probe parked one step later."""
        config = _config(self._tmp.name)
        data_date = date.today().isoformat()
        claim_path = self._stale_legacy_claim(config)
        entered, resume = threading.Event(), threading.Event()
        real_stale = hot_top10_svc._claim_is_stale

        def pausing_stale(path, text):
            result = real_stale(path, text)
            if result and not entered.is_set():
                entered.set()
                resume.wait(timeout=10)
            return result

        loser: Dict[str, Any] = {}

        def _late_contender() -> None:
            with mock.patch.object(
                hot_top10_svc,
                "_claim_is_stale",
                autospec=True,
                side_effect=pausing_stale,
            ):
                loser["claim"] = acquire_hot_top10_delivery_claim(
                    config, data_date
                )

        worker = threading.Thread(target=_late_contender, daemon=True)
        worker.start()
        self.assertTrue(entered.wait(timeout=5))

        # The surviving holder takes the same stale claim over and keeps
        # holding it (delivery in progress — no release yet).
        holder = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(holder)
        holder_content = claim_path.read_text(encoding="utf-8")

        resume.set()
        worker.join(timeout=10)

        self.assertIsNone(
            loser["claim"], "surviving holder must not be clobbered"
        )
        self.assertEqual(
            claim_path.read_text(encoding="utf-8"), holder_content
        )
        holder.release()
        self.assertFalse(claim_path.exists())

    @unittest.skipUnless(
        getattr(hot_top10_svc, "_CLAIM_LOCKING_AVAILABLE", False),
        "OS file locking unavailable on this platform",
    )
    def test_claim_lock_is_exclusive_within_process(self):
        """Lock semantics for both platform branches (CI=ubuntu exercises
        fcntl, Windows local exercises msvcrt): a held delivery lock refuses
        a second handle EVEN IN THE SAME PROCESS; unlocking makes the file
        lockable again."""
        path = Path(self._tmp.name) / "lock_probe.lock"
        path.write_text("payload", encoding="utf-8")
        first = open(path, "r+b")
        second = open(path, "r+b")
        try:
            self.assertTrue(hot_top10_svc._lock_claim_file(first))
            self.assertFalse(hot_top10_svc._lock_claim_file(second))
            hot_top10_svc._unlock_claim_file(first)
            self.assertTrue(hot_top10_svc._lock_claim_file(second))
            hot_top10_svc._unlock_claim_file(second)
        finally:
            first.close()
            second.close()

    def test_lock_unavailable_degrades_to_cas_explicitly(self):
        """Platforms without OS locking degrade EXPLICITLY to the r6 CAS
        path with a loud warning — never a silent pretend-success."""
        config = _config(self._tmp.name)
        data_date = date.today().isoformat()
        claim_path = self._stale_legacy_claim(config)
        with mock.patch.object(
            hot_top10_svc, "_CLAIM_LOCKING_AVAILABLE", False, create=True
        ):
            with self.assertLogs(
                "src.services.hot_top10_service", level="WARNING"
            ) as captured:
                claim = acquire_hot_top10_delivery_claim(config, data_date)
        self.assertIsNotNone(claim)
        self.assertTrue(
            any("CAS" in line or "退化" in line for line in captured.output),
            f"degradation must be logged loudly: {captured.output}",
        )
        lines = claim_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)  # takeover rewrote as ours (tokened)
        claim.release()
        self.assertFalse(claim_path.exists())

    def test_per_date_marker_blocks_stale_overwrite_double_delivery(self):
        """Review #11 OR-COR-341d7b5a deterministic interleaving: B delivers
        today elsewhere (its marker is recorded); A — already in flight on
        the previous trading day's rankings with a slow LLM — delivers
        afterwards; the retained pending follow-up must observe that
        today's marker already exists and skip. Notifications stop at
        [B(today), A(yesterday)] with NO second today push. r6 RED: A's
        single-blob marker overwrote B's record, so the follow-up pushed
        today's list a second time."""
        config = _config(self._tmp.name)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        today = date.today().isoformat()

        class _BlockingAnalyzer:
            def __init__(self) -> None:
                self.entered = threading.Event()

            def generate_text(self, prompt: str, **kwargs: Any) -> str:
                self.entered.set()
                release_a.wait(timeout=10)
                return _llm_json()

        release_a = threading.Event()
        analyzer_a = _BlockingAnalyzer()
        notifier_a = _FakeNotifier()
        notifier_c = _FakeNotifier()
        service_a = _FakeHotspotService(_hotspot_payload(_theme_items(3)))
        service_a.payload["trade_date"] = yesterday

        # A is already in flight on the stale rankings, parked in the LLM.
        results_a: Dict[str, HotTop10RunResult] = {}

        def _a_run() -> None:
            results_a["run"] = run_hot_top10_analysis(
                config,
                notifier=notifier_a,
                analyzer=analyzer_a,
                hotspot_service=service_a,
            )

        worker = threading.Thread(target=_a_run, daemon=True)
        worker.start()
        self.assertTrue(analyzer_a.entered.wait(timeout=5))

        # B (another process) completed today's delivery meanwhile: its
        # marker is recorded. (Simulated at the marker boundary — the exact
        # mechanism under review.)
        record_hot_top10_marker(
            config,
            llm_completed=True,
            notification_status="sent",
            data_date=today,
        )

        # C: an overlapping trigger is mutex-skipped and retains the
        # one-shot pending follow-up.
        result_c = run_hot_top10_analysis(
            config,
            notifier=notifier_c,
            analyzer=_FakeAnalyzer(text=_llm_json()),
            hotspot_service=_FakeHotspotService(_hotspot_payload(_theme_items(3))),
        )
        self.assertTrue(result_c.skipped)
        self.assertEqual(result_c.reason, "already_running")

        release_a.set()
        worker.join(timeout=15)
        result_a = results_a["run"]

        # A delivers the stale list once ...
        self.assertTrue(result_a.delivered)
        self.assertEqual(result_a.ranking_date, yesterday)
        # ... and the pending follow-up must NOT re-push today's list.
        self.assertEqual(
            len(notifier_a.sent),
            1,
            "pending follow-up must observe today's marker and skip",
        )
        self.assertEqual(len(notifier_c.sent), 0)
        # B's marker survived A's stale delivery.
        marker_today = json.loads(
            hot_top10_marker_path(config, today).read_text(encoding="utf-8")
        )
        self.assertEqual(marker_today.get("data_date"), today)
        self.assertTrue(marker_today.get("delivered"))

    def test_expired_per_date_markers_are_pruned_lazily(self):
        """Cleanup policy: per-date marker files older than the retention
        window are removed lazily after each successful write; the fresh
        marker survives."""
        config = _config(self._tmp.name)
        old_date = (
            date.today()
            - timedelta(days=hot_top10_svc.MARKER_RETENTION_DAYS + 1)
        ).isoformat()
        old_marker = hot_top10_marker_path(config, old_date)
        old_marker.parent.mkdir(parents=True, exist_ok=True)
        old_marker.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "run_date": old_date,
                    "data_date": old_date,
                    "delivered": True,
                }
            ),
            encoding="utf-8",
        )

        record_hot_top10_marker(
            config, llm_completed=True, notification_status="sent"
        )

        self.assertFalse(
            old_marker.exists(), "expired marker must be pruned lazily"
        )
        today_marker = hot_top10_marker_path(config)
        self.assertTrue(today_marker.exists())
        payload = json.loads(today_marker.read_text(encoding="utf-8"))
        self.assertEqual(payload.get("data_date"), date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
