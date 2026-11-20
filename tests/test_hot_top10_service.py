# -*- coding: utf-8 -*-
"""Hot-top10 light analysis tests (Issue #1936 r2).

Priority 1 is the r1 closure blocker (OR-COR-hot-top10-marker-write-failure):
a failed dedup-marker write must NOT count the run as delivered and must NOT
lead to a same-day re-push of the same list.
"""

import json
import os
import tempfile
import threading
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.services.hot_top10.analysis import build_hot_top10_prompt, parse_llm_summary
from src.services.hot_top10.datasource import (
    collect_hot_list_items,
    hot_top10_data_date,
    shanghai_now,
)
from src.services.hot_top10.idempotency import (
    MARKER_SCHEMA_VERSION,
    fallback_marker_path,
    hot_top10_already_delivered_today,
    hot_top10_marker_path,
    hot_top10_state_dir,
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
                "run_date": hot_top10_data_date(),
                "data_date": hot_top10_data_date(),
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


class ManualEntryQuotaTestCase(unittest.TestCase):
    """OR-COR-ca43b57a / OR-COR-104a6e00: the manual one-shot entry runs with
    ``respect_dedup=False``. That exemption is on READ only — a manual run
    must NOT record today's delivered marker nor consume today's dedup
    quota, otherwise it suppresses the scheduled end-of-day report and
    presents possibly-stale intraday data as "today, already delivered"."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = _config(self._tmp.name)
        _MARKER_WRITE_FAILED_DAYS.clear()

    def tearDown(self):
        _MARKER_WRITE_FAILED_DAYS.clear()
        self._tmp.cleanup()

    def _manual(self, notifier):
        return run_hot_top10_analysis(
            self.config,
            notifier=notifier,
            analyzer=FakeAnalyzer(_LLM_JSON),
            hotspot_service=SimpleNamespace(get_hotspots=lambda **kw: _hot_payload()),
            respect_dedup=False,
        )

    def test_manual_run_does_not_write_marker_nor_consume_quota(self):
        notifier = FakeNotifier(send_ok=True)
        manual = self._manual(notifier)
        self.assertTrue(manual.delivered)
        self.assertFalse(
            hot_top10_marker_path(self.config).exists(),
            "manual runs must not record today's delivered marker",
        )

        # The scheduled end-of-day run must still deliver today's report.
        scheduled = _run(self.config, notifier)
        self.assertTrue(scheduled.delivered)
        self.assertNotIn("already_delivered_today", scheduled.reason)
        self.assertEqual(len(notifier.sent_contents), 2)
        self.assertTrue(hot_top10_marker_path(self.config).exists())

    def test_manual_run_ignores_marker_write_failed_block(self):
        _MARKER_WRITE_FAILED_DAYS.add(hot_top10_data_date())
        notifier = FakeNotifier(send_ok=True)
        manual = self._manual(notifier)
        self.assertTrue(manual.delivered)
        self.assertNotEqual(manual.reason, "marker_write_failed_blocked_today")


class OverlapDoubleCheckTestCase(unittest.TestCase):
    """OR-COR-a8bfa126: dedup / marker-failure state must be RE-checked inside
    the run mutex. A caller whose pre-lock checks went stale (paused between
    its checks and the critical section while a peer run completed delivery)
    must not generate and push the same-day list a second time."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = _config(self._tmp.name, trading_day_check_enabled=True)
        _MARKER_WRITE_FAILED_DAYS.clear()

    def tearDown(self):
        _MARKER_WRITE_FAILED_DAYS.clear()
        self._tmp.cleanup()

    def test_stale_prelock_pass_rechecks_inside_mutex_before_push(self):
        gate = threading.Event()       # parks call B at the pre-lock trading-day check
        b_reached = threading.Event()  # signals B finished its pre-lock dedup pass
        gate_calls = {"n": 0}
        b_outcomes = []

        def _gated_trading_day():
            gate_calls["n"] += 1
            if gate_calls["n"] == 1:  # call B: dedup already passed (no marker yet)
                b_reached.set()
                gate.wait(timeout=10)
            return True  # peer A, then resumed B

        notifier = FakeNotifier(send_ok=True)

        def _call_b():
            b_outcomes.append(
                run_hot_top10_analysis(
                    self.config,
                    notifier=notifier,
                    analyzer=FakeAnalyzer(_LLM_JSON),
                    hotspot_service=SimpleNamespace(get_hotspots=lambda **kw: _hot_payload()),
                )
            )

        with patch(
            "src.services.hot_top10.service.is_cn_trading_day_today",
            side_effect=_gated_trading_day,
        ):
            thread_b = threading.Thread(target=_call_b)
            thread_b.start()
            self.assertTrue(b_reached.wait(timeout=10), "call B never reached the pre-lock gate")
            peer = _run(self.config, notifier)  # peer A completes push + marker write
            self.assertTrue(peer.delivered)
            gate.set()  # resume B: stale checks, must re-check inside the mutex
            thread_b.join(timeout=10)

        self.assertFalse(thread_b.is_alive(), "call B dead-locked")
        self.assertEqual(len(b_outcomes), 1)
        self.assertEqual(
            len(notifier.sent_contents),
            1,
            "overlapping runs must stay at-most-once per day (double-checked locking)",
        )
        self.assertTrue(b_outcomes[0].skipped)
        self.assertIn("already_delivered_today", b_outcomes[0].reason)


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
                    [f"hot_top10_{shanghai_now().strftime('%Y%m%d')}.md"],
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


class _FixedClockDateTime(datetime):
    """``datetime`` stand-in whose ``now(tz)`` returns a fixed Shanghai instant
    while leaving everything else real."""

    _fixed = None

    @classmethod
    def now(cls, tz=None):  # noqa: D102 - see class docstring
        if tz is not None:
            return cls._fixed.astimezone(tz)
        return cls._fixed.replace(tzinfo=None)


def _shanghai_clock(at):
    """Patch ``datasource.datetime`` so the CN market clock reads ``at``."""
    cls = type("_FixedClock", (_FixedClockDateTime,), {"_fixed": at})
    return patch("src.services.hot_top10.datasource.datetime", cls)


class ShanghaiClockKeyingTestCase(unittest.TestCase):
    """OR-COR-3e7f490e: the schedule gate, dedup marker and report file names
    must all key on the CN market clock (Asia/Shanghai, the clock Tushare's
    15:30 data cut-off runs on), never on the host clock — otherwise a host
    in another timezone fires at its local 15:35 (= before Shanghai 15:30),
    receives the previous trading day's list and books it as today's."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = _config(self._tmp.name)
        _MARKER_WRITE_FAILED_DAYS.clear()

    def tearDown(self):
        _MARKER_WRITE_FAILED_DAYS.clear()
        self._tmp.cleanup()

    def test_data_date_follows_shanghai_clock(self):
        # Shanghai 2026-11-21 00:30 — a UTC host still shows 2026-11-20.
        at = datetime(2026, 11, 21, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        with _shanghai_clock(at):
            self.assertEqual(hot_top10_data_date(), "2026-11-21")
            self.assertEqual(shanghai_now().strftime("%H:%M"), "00:30")

    def test_marker_and_gate_use_shanghai_date_over_host_date(self):
        # Host clock says 2026-11-20; Shanghai clock says 2026-11-21.
        at = datetime(2026, 11, 21, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

        class _HostDate(date):
            @classmethod
            def today(cls):
                return date(2026, 11, 20)

        with _shanghai_clock(at), patch(
            "src.services.hot_top10.idempotency.date", _HostDate
        ):
            notifier = FakeNotifier(send_ok=True)
            result = _run(self.config, notifier)
            self.assertTrue(result.delivered)
            payload = json.loads(
                hot_top10_marker_path(self.config).read_text(encoding="utf-8")
            )
            # The delivery day key is the Shanghai data date, not the host date.
            self.assertEqual(payload["data_date"], "2026-11-21")
            self.assertEqual(payload["run_date"], "2026-11-20")
            self.assertEqual(
                notifier.saved_files, ["hot_top10_20261121.md"]
            )
            # Same-day gate honours the Shanghai-keyed marker.
            skip, reason = hot_top10_already_delivered_today(self.config)
            self.assertTrue(skip, reason)

    def test_marker_file_is_keyed_by_shanghai_date(self):
        at = datetime(2026, 11, 21, 0, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        with _shanghai_clock(at):
            self.assertEqual(
                hot_top10_marker_path(self.config).name, "state_2026-11-21.json"
            )


class FallbackMarkerRestartSafetyTestCase(unittest.TestCase):
    """OR-COR-hot-top10-marker-write-failure: when the primary marker
    location is unwritable (e.g. data volume full), the delivered-marker must
    persist to a fallback location so a same-day sequential process restart
    cannot re-push the already-delivered list. If NO location can be written,
    the run stays undelivered/blocked in-process (loud ERROR) — the residual
    case is physically unrecordable."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = _config(self._tmp.name)
        _MARKER_WRITE_FAILED_DAYS.clear()

    def tearDown(self):
        _MARKER_WRITE_FAILED_DAYS.clear()
        fallback = fallback_marker_path(self.config)
        try:
            fallback.unlink()
        except FileNotFoundError:
            pass
        self._tmp.cleanup()

    def test_primary_failure_persists_fallback_marker_and_restart_gate_skips(self):
        notifier = FakeNotifier(send_ok=True)
        primary_dir = str(hot_top10_state_dir(self.config))
        real_replace = os.replace

        def _fail_primary_only(src, dst):
            if str(dst).startswith(primary_dir):
                raise OSError("simulated disk full on data volume")
            return real_replace(src, dst)

        with patch(
            "src.services.hot_top10.idempotency.os.replace",
            side_effect=_fail_primary_only,
        ):
            first = _run(self.config, notifier)

        # The push landed and the fallback marker recorded the delivery.
        self.assertTrue(first.delivered)
        self.assertEqual(first.reason, "ok")
        self.assertFalse(hot_top10_marker_path(self.config).exists())
        self.assertTrue(fallback_marker_path(self.config).exists())

        # Simulate the sequential restart: the gate read is stateless, and
        # the in-memory failure set / tick last_attempt are gone — the fresh
        # process must still see today's delivery.
        skip, reason = hot_top10_already_delivered_today(self.config)
        self.assertTrue(skip, reason)
        second = _run(self.config, notifier)
        self.assertTrue(second.skipped)
        self.assertIn("already_delivered_today", second.reason)
        self.assertEqual(len(notifier.sent_contents), 1, "restart must not re-push")

    def test_total_write_failure_still_blocks_and_reports_undelivered(self):
        notifier = FakeNotifier(send_ok=True)
        with patch(
            "src.services.hot_top10.idempotency.os.replace",
            side_effect=OSError("simulated disk full everywhere"),
        ):
            result = _run(self.config, notifier)
        self.assertFalse(result.delivered)
        self.assertEqual(result.reason, "marker_write_failed")
        self.assertFalse(fallback_marker_path(self.config).exists())


class ManualRunDistinctReportFileTestCase(unittest.TestCase):
    """OR-COR-hot-top10-report-overwrite: a same-day manual run shares the
    dedup-exempt path but must NOT replace the delivered scheduled report
    file — the marker still points at the original delivery, so the only
    persisted copy of the scheduled report must survive manual reruns."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config = _config(self._tmp.name)
        _MARKER_WRITE_FAILED_DAYS.clear()

    def tearDown(self):
        _MARKER_WRITE_FAILED_DAYS.clear()
        self._tmp.cleanup()

    def test_manual_run_saves_distinct_filename(self):
        notifier = FakeNotifier(send_ok=True)
        scheduled = _run(self.config, notifier)
        manual = run_hot_top10_analysis(
            self.config,
            notifier=notifier,
            analyzer=FakeAnalyzer(_LLM_JSON),
            hotspot_service=SimpleNamespace(get_hotspots=lambda **kw: _hot_payload()),
            respect_dedup=False,
        )
        self.assertTrue(scheduled.delivered)
        self.assertTrue(manual.delivered)
        scheduled_name, manual_name = notifier.saved_files[0], notifier.saved_files[1]
        # The scheduled canonical name is untouched by the manual run.
        self.assertEqual(
            scheduled_name, f"hot_top10_{shanghai_now().strftime('%Y%m%d')}.md"
        )
        self.assertNotEqual(manual_name, scheduled_name)
        self.assertIn("manual", manual_name)


if __name__ == "__main__":
    unittest.main()
