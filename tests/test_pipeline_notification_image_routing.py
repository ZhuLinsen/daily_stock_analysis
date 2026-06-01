# -*- coding: utf-8 -*-
"""
Regression tests for pipeline email image routing with stock email groups.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.core.pipeline import StockAnalysisPipeline, NotificationChannel
from src.services.run_diagnostics import (
    activate_run_diagnostic_context,
    build_run_diagnostic_summary,
    current_diagnostic_snapshot,
    reset_run_diagnostic_context,
)
from src.enums import ReportType


class _FakeNotifier:
    def __init__(self):
        self._markdown_to_image_channels = {"email"}
        self._markdown_to_image_max_chars = 15000
        self.generate_dashboard_report = MagicMock(side_effect=self._generate_dashboard_report)
        self.save_report_to_file = MagicMock(return_value="/tmp/report.md")
        self.is_available = MagicMock(return_value=True)
        self.get_available_channels = MagicMock(return_value=[NotificationChannel.EMAIL])
        self.get_channels_for_route = MagicMock(
            side_effect=lambda route_type, channels=None: list(
                channels if channels is not None else self.get_available_channels()
            )
        )
        self.send_to_context = MagicMock(return_value=False)
        self._should_use_image_for_channel = MagicMock(
            side_effect=lambda channel, image_bytes: (
                channel.value in self._markdown_to_image_channels and image_bytes is not None
            )
        )
        self._send_email_with_inline_image = MagicMock(return_value=True)
        self.send_to_email = MagicMock(return_value=True)

    @staticmethod
    def _generate_dashboard_report(results):
        return "report:" + ",".join(r.code for r in results)


class TestPipelineEmailGroupImageRouting(unittest.TestCase):
    def _build_pipeline(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeNotifier()
        pipeline.config = SimpleNamespace(
            stock_email_groups=[
                (["000001"], ["group@example.com"]),
            ]
        )
        return pipeline

    def _make_results(self):
        return [
            SimpleNamespace(code="000001"),
            SimpleNamespace(code="600519"),
        ]

    @patch("src.md2img.markdown_to_image", return_value=b"png-bytes")
    def test_send_notifications_email_group_uses_inline_image_when_enabled(self, _mock_md2img):
        pipeline = self._build_pipeline()
        results = self._make_results()

        pipeline._send_notifications(results, ReportType.SIMPLE)

        self.assertEqual(pipeline.notifier._send_email_with_inline_image.call_count, 2)
        pipeline.notifier.send_to_email.assert_not_called()
        called_receivers = [kwargs.get("receivers") for _, kwargs in pipeline.notifier._send_email_with_inline_image.call_args_list]
        self.assertIn(["group@example.com"], called_receivers)
        self.assertIn(None, called_receivers)

    @patch("src.md2img.markdown_to_image", return_value=None)
    def test_send_notifications_email_group_falls_back_to_text_when_image_unavailable(self, _mock_md2img):
        pipeline = self._build_pipeline()
        results = self._make_results()

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier._send_email_with_inline_image.assert_not_called()
        self.assertEqual(pipeline.notifier.send_to_email.call_count, 2)
        called_receivers = [kwargs.get("receivers") for _, kwargs in pipeline.notifier.send_to_email.call_args_list]
        self.assertIn(["group@example.com"], called_receivers)
        self.assertIn(None, called_receivers)

    @patch("src.md2img.markdown_to_image", return_value=None)
    def test_send_notifications_email_group_failure_does_not_skip_later_group(self, _mock_md2img):
        pipeline = self._build_pipeline()
        pipeline.notifier.send_to_email.side_effect = [RuntimeError("group failed"), True]
        results = self._make_results()

        pipeline._send_notifications(results, ReportType.SIMPLE)

        self.assertEqual(pipeline.notifier.send_to_email.call_count, 2)
        called_receivers = [kwargs.get("receivers") for _, kwargs in pipeline.notifier.send_to_email.call_args_list]
        self.assertIn(["group@example.com"], called_receivers)
        self.assertIn(None, called_receivers)

    @patch("src.md2img.markdown_to_image", return_value=None)
    def test_email_group_diagnostics_only_patch_group_results(self, _mock_md2img):
        pipeline = self._build_pipeline()
        pipeline.save_context_snapshot = True
        pipeline.db = MagicMock()
        pipeline.notifier.send_to_email.side_effect = [RuntimeError("group failed"), True]
        results = self._make_results()
        results[0].query_id = "query-group"
        results[1].query_id = "query-default"

        pipeline._send_notifications(results, ReportType.SIMPLE)

        calls = pipeline.db.update_analysis_history_diagnostics.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs["query_id"], "query-group")
        self.assertEqual(calls[0].kwargs["code"], "000001")
        self.assertEqual(calls[0].kwargs["notification_runs"][0]["status"], "failed")
        self.assertEqual(calls[0].kwargs["notification_runs"][0]["channel"], "email:group@example.com")
        self.assertEqual(calls[1].kwargs["query_id"], "query-default")
        self.assertEqual(calls[1].kwargs["code"], "600519")
        self.assertEqual(calls[1].kwargs["notification_runs"][0]["status"], "success")
        self.assertEqual(calls[1].kwargs["notification_runs"][0]["channel"], "email:default")


class _FakeWechatNotifier:
    def __init__(self):
        self._markdown_to_image_channels = {"wechat"}
        self._markdown_to_image_max_chars = 15000
        self.generate_dashboard_report = MagicMock(return_value="dashboard-report")
        self.generate_wechat_dashboard = MagicMock(return_value="dashboard-report")
        self.save_report_to_file = MagicMock(return_value="/tmp/report.md")
        self.is_available = MagicMock(return_value=True)
        self.get_available_channels = MagicMock(return_value=[NotificationChannel.WECHAT])
        self.get_channels_for_route = MagicMock(
            side_effect=lambda route_type, channels=None: list(
                channels if channels is not None else self.get_available_channels()
            )
        )
        self.send_to_context = MagicMock(return_value=False)
        self.generate_brief_report = MagicMock(return_value="brief-report")
        self._should_use_image_for_channel = MagicMock(
            side_effect=lambda channel, image_bytes: (
                channel.value in self._markdown_to_image_channels and image_bytes is not None
            )
        )
        self._send_wechat_image = MagicMock(return_value=True)
        self.send_to_wechat = MagicMock(return_value=True)


class TestPipelineWechatOnlyImageRouting(unittest.TestCase):
    def test_send_notifications_wechat_only_converts_legacy_dashboard_for_image(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeWechatNotifier()
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        with patch("src.md2img.markdown_to_image", return_value=b"wechat-image") as mock_md2img:
            pipeline._send_notifications(results, ReportType.SIMPLE)

        mock_md2img.assert_called_once_with(
            "dashboard-report", max_chars=pipeline.notifier._markdown_to_image_max_chars
        )
        pipeline.notifier._send_wechat_image.assert_called_once()
        pipeline.notifier.send_to_wechat.assert_not_called()

    def test_send_notifications_wechat_only_logs_hint_and_falls_back_to_text(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeWechatNotifier()
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        with patch("src.md2img.markdown_to_image", return_value=None), patch(
            "src.core.pipeline.get_config", return_value=SimpleNamespace(md2img_engine="wkhtmltoimage")
        ), patch("src.core.pipeline.logger.warning") as mock_warning:
            pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier._send_wechat_image.assert_not_called()
        pipeline.notifier.send_to_wechat.assert_called_once_with("dashboard-report")
        self.assertTrue(
            any("企业微信 Markdown 转图片失败" in str(call.args[0]) for call in mock_warning.call_args_list)
        )


class _FakeRoutedNotifier:
    def __init__(self, routed_channels, image_channels=None, noise_should_send=True):
        self._markdown_to_image_channels = set(image_channels or [])
        self._markdown_to_image_max_chars = 15000
        self.generate_dashboard_report = MagicMock(side_effect=self._generate_dashboard_report)
        self.generate_wechat_dashboard = MagicMock(side_effect=self._generate_dashboard_report)
        self.save_report_to_file = MagicMock(return_value="/tmp/report.md")
        self.is_available = MagicMock(return_value=True)
        self.get_available_channels = MagicMock(
            return_value=[
                NotificationChannel.WECHAT,
                NotificationChannel.TELEGRAM,
                NotificationChannel.EMAIL,
                NotificationChannel.NTFY,
                NotificationChannel.GOTIFY,
            ]
        )
        self.get_channels_for_route = MagicMock(return_value=list(routed_channels))
        self.send_to_context = MagicMock(return_value=False)
        self.evaluate_noise_control = MagicMock(
            return_value=SimpleNamespace(
                should_send=noise_should_send,
                message="noise suppressed" if not noise_should_send else "",
            )
        )
        self.record_noise_control = MagicMock()
        self.release_noise_control = MagicMock()
        self._should_use_image_for_channel = MagicMock(
            side_effect=lambda channel, image_bytes: (
                channel.value in self._markdown_to_image_channels and image_bytes is not None
            )
        )
        self.generate_brief_report = MagicMock(return_value="brief-report")
        self._send_wechat_image = MagicMock(return_value=True)
        self.send_to_wechat = MagicMock(return_value=True)
        self._send_telegram_photo = MagicMock(return_value=True)
        self.send_to_telegram = MagicMock(return_value=True)
        self._send_email_with_inline_image = MagicMock(return_value=True)
        self.send_to_email = MagicMock(return_value=True)
        self.send_to_ntfy = MagicMock(return_value=True)
        self.send_to_gotify = MagicMock(return_value=True)

    @staticmethod
    def _generate_dashboard_report(results):
        return "report:" + ",".join(r.code for r in results)


class TestPipelineReportRouteFiltering(unittest.TestCase):
    def test_send_notifications_applies_report_route_before_channel_iteration(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.TELEGRAM])
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier.get_channels_for_route.assert_called_once_with(
            "report",
            channels=[
                NotificationChannel.WECHAT,
                NotificationChannel.TELEGRAM,
                NotificationChannel.EMAIL,
                NotificationChannel.NTFY,
                NotificationChannel.GOTIFY,
            ],
        )
        pipeline.notifier.send_to_telegram.assert_called_once_with("report:000001")
        pipeline.notifier.send_to_wechat.assert_not_called()
        pipeline.notifier.send_to_email.assert_not_called()
        pipeline.notifier.evaluate_noise_control.assert_called_once()
        noise_kwargs = pipeline.notifier.evaluate_noise_control.call_args.kwargs
        self.assertEqual(noise_kwargs["dedup_key"], "report:aggregate:simple:000001")
        self.assertEqual(noise_kwargs["cooldown_key"], "report:aggregate:simple:000001")
        pipeline.notifier.record_noise_control.assert_called_once()

    def test_markdown_to_image_uses_route_filtered_channels(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier(
            [NotificationChannel.EMAIL],
            image_channels={"telegram"},
        )
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        with patch("src.md2img.markdown_to_image", return_value=b"png") as mock_md2img:
            pipeline._send_notifications(results, ReportType.SIMPLE)

        mock_md2img.assert_not_called()
        pipeline.notifier.send_to_email.assert_called_once_with("report:000001")
        pipeline.notifier.send_to_telegram.assert_not_called()

    def test_telegram_image_route_converts_full_report(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier(
            [NotificationChannel.TELEGRAM],
            image_channels={"telegram"},
        )
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        with patch("src.md2img.markdown_to_image", return_value=b"png") as mock_md2img:
            pipeline._send_notifications(results, ReportType.SIMPLE)

        mock_md2img.assert_called_once_with(
            "report:000001", max_chars=pipeline.notifier._markdown_to_image_max_chars
        )
        pipeline.notifier._send_telegram_photo.assert_called_once_with(b"png")
        pipeline.notifier.send_to_telegram.assert_not_called()

    def test_ntfy_route_uses_text_report_without_image_conversion(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier(
            [NotificationChannel.NTFY],
            image_channels={"ntfy"},
        )
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        with patch("src.md2img.markdown_to_image", return_value=b"png") as mock_md2img:
            pipeline._send_notifications(results, ReportType.SIMPLE)

        mock_md2img.assert_not_called()
        pipeline.notifier.send_to_ntfy.assert_called_once_with("report:000001")
        pipeline.notifier._send_email_with_inline_image.assert_not_called()
        pipeline.notifier._send_telegram_photo.assert_not_called()

    def test_gotify_route_uses_text_report_without_image_conversion(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier(
            [NotificationChannel.GOTIFY],
            image_channels={"gotify"},
        )
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        with patch("src.md2img.markdown_to_image", return_value=b"png") as mock_md2img:
            pipeline._send_notifications(results, ReportType.SIMPLE)

        mock_md2img.assert_not_called()
        pipeline.notifier.send_to_gotify.assert_called_once_with("report:000001")
        pipeline.notifier._send_email_with_inline_image.assert_not_called()
        pipeline.notifier._send_telegram_photo.assert_not_called()

    def test_noise_suppression_happens_before_markdown_to_image(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier(
            [NotificationChannel.TELEGRAM],
            image_channels={"telegram"},
            noise_should_send=False,
        )
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        with patch("src.md2img.markdown_to_image", return_value=b"png") as mock_md2img:
            pipeline._send_notifications(results, ReportType.SIMPLE)

        mock_md2img.assert_not_called()
        pipeline.notifier.send_to_telegram.assert_not_called()
        pipeline.notifier.record_noise_control.assert_not_called()

    def test_noise_reservation_released_when_pipeline_static_send_raises(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.TELEGRAM])
        pipeline.notifier.send_to_telegram.side_effect = RuntimeError("send failed")
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier.record_noise_control.assert_not_called()
        pipeline.notifier.release_noise_control.assert_called_once()

    def test_channel_exception_does_not_skip_later_channel_and_records_noise(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.TELEGRAM, NotificationChannel.EMAIL])
        pipeline.notifier.send_to_telegram.side_effect = RuntimeError("telegram failed")
        pipeline.notifier.send_to_email.return_value = True
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier.send_to_telegram.assert_called_once_with("report:000001")
        pipeline.notifier.send_to_email.assert_called_once_with("report:000001")
        pipeline.notifier.record_noise_control.assert_called_once()
        pipeline.notifier.release_noise_control.assert_not_called()

    def test_all_static_channel_failures_release_noise_reservation(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.TELEGRAM, NotificationChannel.EMAIL])
        pipeline.notifier.send_to_telegram.side_effect = RuntimeError("telegram failed")
        pipeline.notifier.send_to_email.return_value = False
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier.send_to_telegram.assert_called_once_with("report:000001")
        pipeline.notifier.send_to_email.assert_called_once_with("report:000001")
        pipeline.notifier.record_noise_control.assert_not_called()
        pipeline.notifier.release_noise_control.assert_called_once()

    def test_context_delivery_counts_as_success_and_is_recorded_with_routed_failures(self):
        token = activate_run_diagnostic_context(
            trace_id="trace-context",
            query_id="query-context",
            stock_code="000001",
            trigger_source="bot",
        )
        try:
            pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
            pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.TELEGRAM])
            pipeline.notifier.send_to_context.return_value = True
            pipeline.notifier.send_to_telegram.return_value = False
            pipeline.config = SimpleNamespace(stock_email_groups=[])
            pipeline.save_context_snapshot = True
            pipeline.db = MagicMock()
            results = [SimpleNamespace(code="000001", query_id="query-context")]

            with patch("src.core.pipeline.logger.info") as mock_info:
                pipeline._send_notifications(results, ReportType.SIMPLE)
            snapshot = current_diagnostic_snapshot() or {}
        finally:
            reset_run_diagnostic_context(token)

        notification_runs = snapshot.get("notification_runs", [])
        self.assertEqual([run.get("channel") for run in notification_runs], ["__context__", "telegram"])
        self.assertTrue(notification_runs[0]["success"])
        self.assertFalse(notification_runs[1]["success"])
        self.assertTrue(
            any(
                call.args and call.args[0] == "决策仪表盘推送成功"
                for call in mock_info.call_args_list
            )
        )
        final_update = pipeline.db.update_analysis_history_diagnostics.call_args_list[-1]
        persisted_runs = final_update.kwargs["diagnostics"]["notification_runs"]
        self.assertEqual([run.get("channel") for run in persisted_runs], ["__context__", "telegram"])

    def test_context_only_delivery_skips_static_channels_in_aggregate_path(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.TELEGRAM])
        pipeline.notifier.send_to_context.return_value = True
        pipeline.notifier.should_broadcast_static_channels = MagicMock(return_value=False)
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier.should_broadcast_static_channels.assert_called_once_with()
        pipeline.notifier.send_to_telegram.assert_not_called()
        pipeline.notifier.evaluate_noise_control.assert_not_called()
        pipeline.notifier.record_noise_control.assert_not_called()
        pipeline.notifier.release_noise_control.assert_not_called()

    def test_dingtalk_context_only_delivery_skips_static_channels_in_aggregate_path(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.TELEGRAM])
        pipeline.notifier.send_to_context.return_value = True
        pipeline.notifier.should_broadcast_static_channels = MagicMock(return_value=False)
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier.should_broadcast_static_channels.assert_called_once_with()
        pipeline.notifier.send_to_telegram.assert_not_called()
        pipeline.notifier.evaluate_noise_control.assert_not_called()
        pipeline.notifier.record_noise_control.assert_not_called()
        pipeline.notifier.release_noise_control.assert_not_called()

    def test_telegram_context_only_delivery_skips_static_channels_in_aggregate_path(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.TELEGRAM])
        pipeline.notifier.send_to_context.return_value = True
        pipeline.notifier.should_broadcast_static_channels = MagicMock(return_value=False)
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        pipeline._send_notifications(results, ReportType.SIMPLE)

        pipeline.notifier.should_broadcast_static_channels.assert_called_once_with()
        pipeline.notifier.send_to_telegram.assert_not_called()
        pipeline.notifier.evaluate_noise_control.assert_not_called()
        pipeline.notifier.record_noise_control.assert_not_called()
        pipeline.notifier.release_noise_control.assert_not_called()

    def test_send_notifications_records_each_channel_run_rather_than_aggregating(self):
        token = activate_run_diagnostic_context(trace_id="trace-notify")
        try:
            pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
            pipeline.notifier = _FakeRoutedNotifier(
                [NotificationChannel.WECHAT, NotificationChannel.TELEGRAM]
            )
            pipeline.notifier.send_to_telegram.side_effect = False
            pipeline.notifier.send_to_wechat.return_value = True
            pipeline.config = SimpleNamespace(stock_email_groups=[])
            results = [SimpleNamespace(code="000001")]

            pipeline._send_notifications(results, ReportType.SIMPLE)

            snapshot = current_diagnostic_snapshot() or {}
            notification_runs = snapshot.get("notification_runs", [])
            channels = [run.get("channel") for run in notification_runs]
            self.assertEqual(len(channels), 2)
            self.assertIn("wechat", channels)
            self.assertIn("telegram", channels)
            self.assertNotIn("report", channels)
        finally:
            reset_run_diagnostic_context(token)

    def test_notification_summary_degraded_when_only_partial_channels_fail(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeRoutedNotifier([NotificationChannel.WECHAT, NotificationChannel.TELEGRAM])
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        pipeline.notifier.send_to_wechat.return_value = True
        pipeline.notifier.send_to_telegram.return_value = False
        results = [SimpleNamespace(code="000001")]

        token = activate_run_diagnostic_context(
            trace_id="trace-notify",
            query_id="query-notify",
            stock_code="000001",
            trigger_source="api",
        )
        try:
            pipeline._send_notifications(results, ReportType.SIMPLE)
            snapshot = current_diagnostic_snapshot()
        finally:
            reset_run_diagnostic_context(token)

        self.assertEqual(snapshot["notification_runs"][0]["channel"], "wechat")
        self.assertEqual(snapshot["notification_runs"][0]["success"], True)
        self.assertEqual(snapshot["notification_runs"][1]["channel"], "telegram")
        self.assertEqual(snapshot["notification_runs"][1]["success"], False)

        summary = build_run_diagnostic_summary(
            context_snapshot={"diagnostics": snapshot},
            raw_result={"success": True, "model_used": "deepseek-chat"},
            report_saved=True,
        )

        self.assertEqual(summary["components"]["notification"]["status"], "degraded")
        self.assertIn(
            "telegram",
            summary["components"]["notification"]["details"]["failed"],
        )


if __name__ == "__main__":
    unittest.main()
