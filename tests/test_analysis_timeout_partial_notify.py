# -*- coding: utf-8 -*-
"""Unit tests for timeout partial delivery helpers."""

from __future__ import annotations

import os
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.services.analysis_timeout_partial import (
    CompletedAnalysisSummary,
    TIMEOUT_PARTIAL_NOTIFY_ENV,
    build_partial_timeout_report,
    collect_completed_analyses_since,
    format_timeout_error_message,
    handle_runtime_analysis_timeout,
    is_timeout_partial_notify_enabled,
    resolve_expected_stock_codes,
    send_partial_timeout_notification,
)


class TimeoutPartialHelpersTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop(TIMEOUT_PARTIAL_NOTIFY_ENV, None)

    def test_env_defaults_enabled_and_parses_false(self) -> None:
        os.environ.pop(TIMEOUT_PARTIAL_NOTIFY_ENV, None)
        self.assertTrue(is_timeout_partial_notify_enabled())
        os.environ[TIMEOUT_PARTIAL_NOTIFY_ENV] = "false"
        self.assertFalse(is_timeout_partial_notify_enabled())

    def test_resolve_expected_stock_codes_prefers_explicit_list(self) -> None:
        config = SimpleNamespace(stock_list=["000001", "000002"])
        self.assertEqual(
            resolve_expected_stock_codes(["600519", "600519", ""], config=config),
            ["600519"],
        )
        self.assertEqual(
            resolve_expected_stock_codes(None, config=config),
            ["000001", "000002"],
        )

    def test_format_timeout_error_message_includes_counts(self) -> None:
        completed = [
            CompletedAnalysisSummary(code="600519", name="贵州茅台"),
            CompletedAnalysisSummary(code="000001", name="平安银行"),
        ]
        message = format_timeout_error_message(
            timeout_seconds=90,
            completed=completed,
            pending_codes=["300750"],
        )
        self.assertIn("timed out after 90s", message)
        self.assertIn("completed=2", message)
        self.assertIn("pending=1", message)
        self.assertIn("completed_codes=600519,000001", message)
        self.assertIn("pending_codes=300750", message)

    def test_build_partial_timeout_report_lists_completed_and_pending(self) -> None:
        report = build_partial_timeout_report(
            timeout_seconds=120,
            completed=[
                CompletedAnalysisSummary(
                    code="600519",
                    name="贵州茅台",
                    operation_advice="买入",
                    sentiment_score=80,
                )
            ],
            pending_codes=["300750"],
        )
        self.assertIn("部分完成", report)
        self.assertIn("600519", report)
        self.assertIn("300750", report)
        self.assertIn("120", report)

    def test_summaries_from_history_rows_keeps_latest_per_code(self) -> None:
        from src.services.analysis_timeout_partial import _summaries_from_history_rows

        older = SimpleNamespace(
            id=1,
            code="600519",
            name="old",
            operation_advice="持有",
            sentiment_score=50,
            created_at=datetime(2026, 1, 1, 10, 0, 0),
        )
        newer = SimpleNamespace(
            id=2,
            code="600519",
            name="new",
            operation_advice="买入",
            sentiment_score=70,
            created_at=datetime(2026, 1, 1, 11, 0, 0),
        )
        rows = _summaries_from_history_rows(
            [newer, older],
            ["600519", "300750"],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].code, "600519")
        self.assertEqual(rows[0].name, "new")
        self.assertEqual(rows[0].history_id, 2)

    def test_timeout_partial_notify_registry_uses_switch_ui_control(self) -> None:
        from api.v1.schemas.system_config import SystemConfigFieldSchema
        from src.core.config_registry import get_field_definition

        field = get_field_definition("DSA_TIMEOUT_PARTIAL_NOTIFY")
        self.assertEqual(field["data_type"], "boolean")
        self.assertEqual(field["ui_control"], "switch")
        self.assertEqual(field["default_value"], "true")
        SystemConfigFieldSchema.model_validate(field)

    def test_collect_completed_analyses_since_fail_open(self) -> None:
        with patch(
            "src.services.analysis_timeout_partial._query_history_rows_since",
            side_effect=RuntimeError("db down"),
        ):
            rows = collect_completed_analyses_since(
                run_started_at=datetime.now(),
                expected_codes=["600519"],
            )
        self.assertEqual(rows, [])

    def test_resolve_storage_module_cleans_partial_import_on_failure(self) -> None:
        import sys

        from src.services.analysis_timeout_partial import _resolve_storage_module

        original = {
            name: module
            for name, module in sys.modules.items()
            if name == "src.storage" or name.startswith("src.storage.")
        }
        for name in list(original):
            sys.modules.pop(name, None)

        def _boom(name: str, *args, **kwargs):
            if name == "src.storage":
                sys.modules["src.storage"] = object()
                sys.modules["src.storage.models"] = object()
                raise ImportError("broken storage")
            raise AssertionError(f"unexpected import: {name}")

        try:
            with patch("importlib.import_module", side_effect=_boom):
                with self.assertRaises(RuntimeError) as ctx:
                    _resolve_storage_module()
            self.assertIn("storage unavailable", str(ctx.exception))
            self.assertNotIn("src.storage", sys.modules)
            self.assertFalse(
                any(name.startswith("src.storage.") for name in sys.modules)
            )
        finally:
            for name in list(sys.modules):
                if name == "src.storage" or name.startswith("src.storage."):
                    sys.modules.pop(name, None)
            sys.modules.update(original)

    def test_collect_fail_open_when_storage_import_fails(self) -> None:
        with patch(
            "src.services.analysis_timeout_partial._resolve_storage_module",
            side_effect=RuntimeError("storage unavailable for timeout partial collect"),
        ):
            rows = collect_completed_analyses_since(
                run_started_at=datetime.now(),
                expected_codes=["600519"],
            )
        self.assertEqual(rows, [])

    def test_send_respects_no_notify_and_env(self) -> None:
        self.assertFalse(
            send_partial_timeout_notification(
                "hello",
                completed_codes=["600519"],
                no_notify=True,
            )
        )
        os.environ[TIMEOUT_PARTIAL_NOTIFY_ENV] = "0"
        self.assertFalse(
            send_partial_timeout_notification(
                "hello",
                completed_codes=["600519"],
                no_notify=False,
            )
        )

    def test_send_swallows_channel_exception_and_returns_false(self) -> None:
        notification_mod = MagicMock()
        notification_mod.NotificationService.return_value.send.side_effect = RuntimeError(
            "webhook 500"
        )
        with patch.dict("sys.modules", {"src.notification": notification_mod}):
            self.assertFalse(
                send_partial_timeout_notification(
                    "hello",
                    completed_codes=["600519"],
                    no_notify=False,
                )
            )
        notification_mod.NotificationService.return_value.send.assert_called_once()

    @patch("src.services.analysis_timeout_partial.collect_completed_analyses_since")
    def test_handle_keeps_error_message_when_channel_raises(
        self,
        collect_mock: MagicMock,
    ) -> None:
        collect_mock.return_value = [
            CompletedAnalysisSummary(code="600519", name="贵州茅台"),
        ]
        notification_mod = MagicMock()
        notification_mod.NotificationService.return_value.send.side_effect = RuntimeError(
            "channel down"
        )

        with patch.dict("sys.modules", {"src.notification": notification_mod}):
            outcome = handle_runtime_analysis_timeout(
                timeout_seconds=60,
                run_started_at=datetime(2026, 1, 1, 12, 0, 0),
                stock_codes=["600519", "300750"],
                no_notify=False,
            )

        self.assertFalse(outcome.notified)
        self.assertEqual(outcome.notify_skipped_reason, "send_failed")
        self.assertIn("completed=1", outcome.error_message)
        self.assertIn("pending=1", outcome.error_message)

    @patch("src.services.analysis_timeout_partial.send_partial_timeout_notification")
    @patch("src.services.analysis_timeout_partial.collect_completed_analyses_since")
    def test_handle_runtime_analysis_timeout_notifies_when_completed(
        self,
        collect_mock: MagicMock,
        send_mock: MagicMock,
    ) -> None:
        collect_mock.return_value = [
            CompletedAnalysisSummary(code="600519", name="贵州茅台"),
        ]
        send_mock.return_value = True

        outcome = handle_runtime_analysis_timeout(
            timeout_seconds=60,
            run_started_at=datetime(2026, 1, 1, 12, 0, 0),
            stock_codes=["600519", "300750"],
            no_notify=False,
            config=SimpleNamespace(stock_list=[]),
            db=MagicMock(),
        )

        self.assertTrue(outcome.notified)
        self.assertEqual(outcome.pending_codes, ["300750"])
        self.assertIn("completed=1", outcome.error_message)
        self.assertIn("pending=1", outcome.error_message)
        send_mock.assert_called_once()

    @patch("src.services.analysis_timeout_partial.send_partial_timeout_notification")
    @patch("src.services.analysis_timeout_partial.collect_completed_analyses_since")
    def test_handle_skips_notify_without_completed(
        self,
        collect_mock: MagicMock,
        send_mock: MagicMock,
    ) -> None:
        collect_mock.return_value = []
        outcome = handle_runtime_analysis_timeout(
            timeout_seconds=60,
            run_started_at=datetime.now(),
            stock_codes=["600519"],
            no_notify=False,
        )
        self.assertFalse(outcome.notified)
        self.assertEqual(outcome.notify_skipped_reason, "no_completed_results")
        send_mock.assert_not_called()


class RuntimeSchedulerTimeoutPartialIntegrationTests(unittest.TestCase):
    def test_build_timeout_last_error_uses_partial_helper(self) -> None:
        from src.services.runtime_scheduler import RuntimeSchedulerService

        config = SimpleNamespace(stock_list=["600519", "300750"])
        service = RuntimeSchedulerService(config_provider=lambda: config)
        completed = [CompletedAnalysisSummary(code="600519", name="贵州茅台")]

        with patch(
            "src.services.analysis_timeout_partial.collect_completed_analyses_since",
            return_value=completed,
        ), patch(
            "src.services.analysis_timeout_partial.send_partial_timeout_notification",
            return_value=True,
        ):
            message = service._build_timeout_last_error(
                timeout_seconds=90,
                run_started_at=datetime(2026, 1, 1, 12, 0, 0),
                stock_codes=["600519", "300750"],
            )

        self.assertIn("timed out after 90s", message)
        self.assertIn("completed=1", message)
        self.assertIn("pending=1", message)
        self.assertIn("completed_codes=600519", message)
        self.assertIn("pending_codes=300750", message)

    def test_timeout_branch_sets_structured_last_error(self) -> None:
        from src.services.runtime_scheduler import RuntimeSchedulerService

        config = SimpleNamespace(stock_list=["600519", "300750"])
        service = RuntimeSchedulerService(config_provider=lambda: config)
        service._analysis_timeout_seconds = lambda: 1

        class _AliveProcess:
            def __init__(self, *args, **kwargs):
                self.pid = 424242
                self.exitcode = None
                self._alive = True

            def start(self) -> None:
                return None

            def is_alive(self) -> bool:
                return self._alive

            def join(self, timeout=None) -> None:
                return None

            def terminate(self) -> None:
                self._alive = False

            def kill(self) -> None:
                self._alive = False

        class _EmptyQueue:
            def get(self, timeout=None):
                from queue import Empty

                raise Empty

            def cancel_join_thread(self) -> None:
                return None

            def close(self) -> None:
                return None

        fake_context = SimpleNamespace(
            Queue=lambda: _EmptyQueue(),
            Process=_AliveProcess,
        )

        with patch(
            "src.services.runtime_scheduler.multiprocessing.get_context",
            return_value=fake_context,
        ), patch(
            "src.services.runtime_scheduler._terminate_analysis_process_tree",
        ), patch.object(
            service,
            "_build_timeout_last_error",
            return_value=(
                "runtime scheduled analysis timed out after 1s; "
                "completed=1; pending=1; completed_codes=600519; pending_codes=300750"
            ),
        ):
            # Watchdog finally always releases the shared lock.
            self.assertTrue(service._run_lock.acquire(blocking=False))
            service._run_analysis_with_watchdog(
                ["600519", "300750"],
                lock_held=True,
            )

        deadline = time.time() + 2
        last_error = service.status()["last_error"]
        while (
            last_error is None or "completed=1" not in last_error
        ) and time.time() < deadline:
            time.sleep(0.02)
            last_error = service.status()["last_error"]

        self.assertIsNotNone(last_error)
        self.assertIn("timed out after 1s", last_error)
        self.assertIn("completed=1", last_error)
        self.assertIn("pending_codes=300750", last_error)


if __name__ == "__main__":
    unittest.main()
