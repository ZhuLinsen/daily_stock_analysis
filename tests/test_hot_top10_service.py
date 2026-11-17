# -*- coding: utf-8 -*-
"""Hot-top10 light analysis tests (Issue #1936 r2).

Priority 1 is the r1 closure blocker (OR-COR-hot-top10-marker-write-failure):
a failed dedup-marker write must NOT count the run as delivered and must NOT
lead to a same-day re-push of the same list.
"""

import json
import logging
import os
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services.hot_top10.analysis import build_hot_top10_prompt, parse_llm_summary
from src.services.hot_top10.datasource import collect_hot_list_items
from src.services.hot_top10.idempotency import (
    MARKER_SCHEMA_VERSION,
    hot_top10_already_delivered_today,
    hot_top10_marker_path,
    record_hot_top10_marker,
)
from src.services.hot_top10.service import (
    _RUN_MUTEX,
    _MARKER_WRITE_FAILED_DAYS,
    HotTop10RunResult,
    run_hot_top10_analysis,
)


def _config(tmp_dir, **overrides):
    base = {
        "database_path": str(Path(tmp_dir) / "stock_analysis.db"),
        "hot_top10_count": 10,
        "hot_top10_schedule_time": "15:35",
        "trading_day_check_enabled": False,  # most tests gate this off
        "report_language": "zh",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _hot_payload():
    return {
        "active_themes": [
            {"name": "人工智能", "change_pct": 3.2, "source": "theme", "phase": "rising",
             "reason": "资金流入"},
            {"name": "低空经济", "change_pct": 1.8, "source": "theme", "phase": "rising", "reason": ""},
        ],
        "leading_industries": [
            {"name": "半导体", "change_pct": 2.1, "source": "industry", "phase": "rising", "reason": ""},
        ],
        "leading_concepts": [
            {"name": "算力租赁", "change_pct": 2.9, "source": "concept", "phase": "rising", "reason": ""},
        ],
    }


class FakeNotifier:
    """Configurable notification double: records calls, can fail save/send."""

    def __init__(self, available=True, send_ok=True, fail_save=False):
        self.saved_files = []
        self.sent_contents = []
        self._available = available
        self._send_ok = send_ok
        self._fail_save = fail_save

    def is_available(self):
        return self._available

    def save_report_to_file(self, content, filename=None):
        if self._fail_save:
            raise OSError("simulated report dir not writable")
        self.saved_files.append(filename)
        return f"reports/{filename}"

    def send(self, content, route_type=None, **kwargs):
        self.sent_contents.append(content)
        return self._send_ok


class FakeAnalyzer:
    def __init__(self, text=None, exc=None):
        self._text = text
        self._exc = exc
        self.prompts = []

    def generate_text(self, prompt, max_tokens=2048, temperature=0.7):
        self.prompts.append(prompt)
        if self._exc:
            raise self._exc
        return self._text


_LLM_JSON = (
    '```json\n{"summary": "热点主线为AI算力", "items": ['
    '{"rank": 1, "name": "人工智能", "driver": "大模型催化", "strength": "强", '
    '"advice": "轻仓介入", "risk": "高位波动"}]}\n```'
)


def _run(config, notifier, analyzer=None, **kwargs):
    return run_hot_top10_analysis(
        config,
        notifier=notifier,
        analyzer=analyzer or FakeAnalyzer(_LLM_JSON),
        hotspot_service=SimpleNamespace(get_hotspots=lambda **kw: _hot_payload()),
        **kwargs,
    )


class MarkerWriteFailureIdempotencyTestCase(unittest.TestCase):
    """The maintainer-named r1 closure blocker: a failed marker write must
    block same-day re-delivery instead of silently re-pushing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = _config(self._tmp.name)
        _MARKER_WRITE_FAILED_DAYS.clear()

    def tearDown(self):
        _MARKER_WRITE_FAILED_DAYS.clear()
        self._tmp.cleanup()

    def test_first_delivery_with_failing_marker_is_not_delivered(self):
        notifier = FakeNotifier(send_ok=True)

        def _fail_replace(src, dst):
            raise OSError("simulated disk full")

        with patch("src.services.hot_top10.idempotency.os.replace", side_effect=_fail_replace):
            result = _run(self.config, notifier)
        self.assertFalse(result.delivered)
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "marker_write_failed")
        self.assertIsNotNone(result.report_markdown)
        self.assertEqual(result.notification_status, "sent")
        self.assertFalse(hot_top10_marker_path(self.config).exists())

    def test_failed_marker_day_is_not_repushed_on_same_day_rerun(self):
        notifier = FakeNotifier(send_ok=True)

        def _fail_replace(src, dst):
            raise OSError("simulated disk full")

        with patch("src.services.hot_top10.idempotency.os.replace", side_effect=_fail_replace):
            first = _run(self.config, notifier)
        self.assertEqual(first.reason, "marker_write_failed")
        pushes_after_first = len(notifier.sent_contents)

        # Same-day second trigger: must NOT regenerate or re-push (no LLM, no send).
        second = _run(self.config, notifier)
        self.assertTrue(second.skipped)
        self.assertEqual(second.reason, "marker_write_failed_blocked_today")
        self.assertEqual(len(notifier.sent_contents), pushes_after_first)

    def test_marker_write_failure_is_loud_not_silent(self):
        with patch(
            "src.services.hot_top10.idempotency.os.replace",
            side_effect=OSError("simulated disk full"),
        ):
            with self.assertLogs("src.services.hot_top10.idempotency", level="ERROR") as logs:
                ok = record_hot_top10_marker(self.config, llm_completed=True, notification_status="sent")
        self.assertFalse(ok)
        self.assertTrue(any("持续写入失败" in message for message in logs.output))

    def test_transient_marker_failure_retries_then_succeeds(self):
        real_replace = os.replace
        attempts = {"n": 0}

        def _flaky_replace(src, dst):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise OSError("transient I/O error")
            return real_replace(src, dst)

        with patch("src.services.hot_top10.idempotency.os.replace", side_effect=_flaky_replace):
            ok = record_hot_top10_marker(self.config, llm_completed=True, notification_status="sent")
        self.assertTrue(ok)
        self.assertTrue(hot_top10_marker_path(self.config).exists())
        self.assertEqual(attempts["n"], 3)


class DeliveryAndDedupContractTestCase(unittest.TestCase):
    """Marker semantics per OR-COR-8c2d195e + dedup gate fail-open rules."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = _config(self._tmp.name)
        _MARKER_WRITE_FAILED_DAYS.clear()

    def tearDown(self):
        _MARKER_WRITE_FAILED_DAYS.clear()
        self._tmp.cleanup()

    def _marker_exists(self):
        return hot_top10_marker_path(self.config).exists()

    def test_sent_push_records_marker(self):
        notifier = FakeNotifier(send_ok=True)
        result = _run(self.config, notifier)
        self.assertTrue(result.delivered)
        self.assertEqual(result.reason, "ok")
        self.assertTrue(self._marker_exists())

    def test_disabled_notification_with_saved_report_records_marker(self):
        notifier = FakeNotifier()
        result = run_hot_top10_analysis(
            self.config, send_notification=False, notifier=notifier,
            analyzer=FakeAnalyzer(_LLM_JSON),
            hotspot_service=SimpleNamespace(get_hotspots=lambda **kw: _hot_payload()),
        )
        self.assertTrue(result.delivered)
        self.assertEqual(result.notification_status, "disabled")
        self.assertTrue(self._marker_exists())

    def test_no_channel_with_saved_report_records_marker(self):
        notifier = FakeNotifier(available=False)
        result = _run(self.config, notifier)
        self.assertEqual(result.notification_status, "no_channel")
        self.assertTrue(self._marker_exists())
        self.assertEqual(notifier.sent_contents, [])

    def test_failed_push_does_not_record_marker_and_can_retry(self):
        notifier = FakeNotifier(send_ok=False)
        result = _run(self.config, notifier)
        self.assertEqual(result.notification_status, "failed")
        self.assertFalse(self._marker_exists())

    def test_save_failure_without_push_leaves_marker_open(self):
        notifier = FakeNotifier(fail_save=True, send_ok=False)
        result = _run(self.config, notifier)
        self.assertFalse(result.delivered)
        self.assertFalse(self._marker_exists())

    def test_already_delivered_today_skips(self):
        marker = hot_top10_marker_path(self.config)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps({
                "schema_version": MARKER_SCHEMA_VERSION,
                "run_date": date.today().isoformat(),
                "data_date": date.today().isoformat(),
                "delivered": True,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        notifier = FakeNotifier()
        result = _run(self.config, notifier)
        self.assertTrue(result.skipped)
        self.assertIn("already_delivered_today", result.reason)
        self.assertEqual(notifier.sent_contents, [])

    def test_corrupt_marker_fails_open(self):
        marker = hot_top10_marker_path(self.config)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("{not json", encoding="utf-8")
        result = _run(self.config, FakeNotifier(send_ok=True))
        self.assertFalse(result.skipped)
        self.assertTrue(self._marker_exists())

    def test_inprocess_overlap_is_serialized(self):
        with _RUN_MUTEX:
            pass
        _RUN_MUTEX.acquire()
        try:
            result = _run(self.config, FakeNotifier())
            self.assertTrue(result.skipped)
            self.assertEqual(result.reason, "already_running")
        finally:
            _RUN_MUTEX.release()

    def test_trading_day_gate_skips_and_force_run_bypasses(self):
        config = _config(self._tmp.name, trading_day_check_enabled=True)
        with patch("src.services.hot_top10.service.is_cn_trading_day_today", return_value=False):
            skipped = _run(config, FakeNotifier())
            self.assertEqual(skipped.reason, "non_trading_day")
            forced = _run(config, FakeNotifier(send_ok=True), force_run=True)
            self.assertTrue(forced.delivered)

    def test_result_is_never_raising_on_collector_crash(self):
        def _boom(**kwargs):
            raise RuntimeError("provider exploded")

        result = run_hot_top10_analysis(
            self.config, notifier=FakeNotifier(), analyzer=FakeAnalyzer(_LLM_JSON),
            hotspot_service=SimpleNamespace(get_hotspots=_boom),
        )
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, "hotspot_data_unavailable")


class OptInAndZeroBehaviorTestCase(unittest.TestCase):
    """HOT_TOP10_ENABLED defaults to false: unset means zero behavior."""

    def tearDown(self):
        from src.config import Config

        Config.reset_instance()

    def _load(self, env):
        from src.config import Config

        with patch("src.config.setup_env"), patch.object(
            Config, "_parse_litellm_yaml", return_value=[]
        ), patch.object(Config, "_parse_stock_email_groups", return_value=[]):
            with patch.dict(os.environ, env, clear=True):
                return Config._load_from_env()

    def test_unset_env_defaults_to_disabled(self):
        config = self._load({})
        self.assertFalse(config.hot_top10_enabled)
        self.assertEqual(config.hot_top10_schedule_time, "15:35")
        self.assertEqual(config.hot_top10_count, 10)

    def test_enabled_and_clamped_via_env(self):
        config = self._load({
            "HOT_TOP10_ENABLED": "true",
            "HOT_TOP10_SCHEDULE_TIME": "09:99",  # invalid -> fallback
            "HOT_TOP10_COUNT": "999",  # clamped to 30
        })
        self.assertTrue(config.hot_top10_enabled)
        self.assertEqual(config.hot_top10_schedule_time, "15:35")
        self.assertEqual(config.hot_top10_count, 30)

    def test_disabled_config_registers_no_tick(self):
        # The schedule-mode gate in main.py registers the tick only when
        # hot_top10_enabled is true; simulate the gate decision directly.
        config = self._load({})
        should_register = getattr(config, "hot_top10_enabled", False)
        self.assertFalse(should_register)
        enabled = self._load({"HOT_TOP10_ENABLED": "true"})
        self.assertTrue(getattr(enabled, "hot_top10_enabled", False))


class AnalysisLayerTestCase(unittest.TestCase):
    def test_prompt_carries_strict_json_contract(self):
        items, _ = None, None
        items = collect_hot_list_items(5, hotspot_service=SimpleNamespace(get_hotspots=lambda **kw: _hot_payload()))
        prompt = build_hot_top10_prompt(items)
        self.assertIn("严格只输出以下 JSON", prompt)
        self.assertIn('"summary"', prompt)
        self.assertIn("人工智能", prompt)

    def test_parse_llm_summary_robustness(self):
        self.assertIsNone(parse_llm_summary(None))
        self.assertIsNone(parse_llm_summary("完全没有 JSON"))
        payload = parse_llm_summary(_LLM_JSON)
        self.assertEqual(payload["summary"], "热点主线为AI算力")
        self.assertEqual(len(payload["items"]), 1)
        bare = parse_llm_summary('前置说明 {"summary": "s", "items": []} 后缀')
        self.assertEqual(bare["summary"], "s")

    def test_collect_unified_sort_across_buckets(self):
        payload = {
            "active_themes": [],
            "leading_industries": [
                {"name": "行业甲", "change_pct": -2.0, "source": "industry", "phase": "falling", "reason": ""},
                {"name": "行业乙", "change_pct": -3.0, "source": "industry", "phase": "falling", "reason": ""},
            ],
            "leading_concepts": [
                {"name": "概念甲", "change_pct": -0.1, "source": "concept", "phase": "falling", "reason": ""},
            ],
        }
        items = collect_hot_list_items(
            2, hotspot_service=SimpleNamespace(get_hotspots=lambda **kw: payload)
        )
        # OR-COR-a7e7c3a3: -0.1% concept outranks -2%/-3% industries.
        self.assertEqual([item["name"] for item in items], ["概念甲", "行业甲"])

    def test_llm_failure_degrades_to_data_only_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            _MARKER_WRITE_FAILED_DAYS.clear()
            try:
                notifier = FakeNotifier(send_ok=True)
                result = _run(config, notifier, analyzer=FakeAnalyzer(exc=RuntimeError("LLM down")))
                self.assertTrue(result.delivered)
                self.assertFalse(result.llm_completed)
                self.assertIn("降级交付", result.report_markdown)
            finally:
                _MARKER_WRITE_FAILED_DAYS.clear()

    def test_report_file_is_named_by_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _config(tmp)
            _MARKER_WRITE_FAILED_DAYS.clear()
            try:
                notifier = FakeNotifier(send_ok=True)
                _run(config, notifier)
                self.assertEqual(
                    notifier.saved_files,
                    [f"hot_top10_{date.today().strftime('%Y%m%d')}.md"],
                )
            finally:
                _MARKER_WRITE_FAILED_DAYS.clear()


class HotTop10RunResultShapeTestCase(unittest.TestCase):
    def test_result_defaults(self):
        result = HotTop10RunResult(False, True, "x")
        self.assertFalse(result.delivered)
        self.assertTrue(result.skipped)
        self.assertIsNone(result.report_markdown)
        self.assertEqual(result.notification_status, "not_attempted")


if __name__ == "__main__":
    unittest.main()
