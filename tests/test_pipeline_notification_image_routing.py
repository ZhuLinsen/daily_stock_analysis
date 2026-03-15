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
from src.enums import ReportType


class _FakeNotifier:
    def __init__(self):
        self._markdown_to_image_channels = {"email"}
        self._markdown_to_image_max_chars = 15000
        self.generate_dashboard_report = MagicMock(side_effect=self._generate_dashboard_report)
        self.save_report_to_file = MagicMock(return_value="/tmp/report.md")
        self.is_available = MagicMock(return_value=True)
        self.get_available_channels = MagicMock(return_value=[NotificationChannel.EMAIL])
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


class _FakeWechatNotifier:
    def __init__(self):
        self._markdown_to_image_channels = {"wechat"}
        self._markdown_to_image_max_chars = 15000
        self.generate_dashboard_report = MagicMock(return_value="dashboard-report")
        self.save_report_to_file = MagicMock(return_value="/tmp/report.md")
        self.is_available = MagicMock(return_value=True)
        self.get_available_channels = MagicMock(return_value=[NotificationChannel.WECHAT])
        self.send_to_context = MagicMock(return_value=False)
        self.generate_wechat_dashboard = MagicMock(return_value="wechat-dashboard")
        self._should_use_image_for_channel = MagicMock(
            side_effect=lambda channel, image_bytes: (
                channel.value in self._markdown_to_image_channels and image_bytes is not None
            )
        )
        self._send_wechat_image = MagicMock(return_value=True)
        self.send_to_wechat = MagicMock(return_value=True)


class TestPipelineWechatOnlyImageRouting(unittest.TestCase):
    def test_send_notifications_wechat_only_skips_full_report_conversion(self):
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.notifier = _FakeWechatNotifier()
        pipeline.config = SimpleNamespace(stock_email_groups=[])
        results = [SimpleNamespace(code="000001")]

        with patch("src.md2img.markdown_to_image", return_value=b"wechat-image") as mock_md2img:
            pipeline._send_notifications(results, ReportType.SIMPLE)

        mock_md2img.assert_called_once_with(
            "wechat-dashboard", max_chars=pipeline.notifier._markdown_to_image_max_chars
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
        pipeline.notifier.send_to_wechat.assert_called_once_with("wechat-dashboard")
        self.assertTrue(
            any("企业微信 Markdown 转图片失败" in str(call.args[0]) for call in mock_warning.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
