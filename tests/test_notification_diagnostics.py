# -*- coding: utf-8 -*-
"""Tests for read-only notification diagnostics."""

import unittest

from src.config import Config
from src.notification import NotificationChannel
from src.services.notification_diagnostics import (
    CHANNEL_SPECS,
    KEY_SPECS,
    NotificationDiagnosticResult,
    format_notification_diagnostics,
    run_notification_diagnostics,
)


def _config(**overrides) -> Config:
    return Config(stock_list=[], **overrides)


class NotificationDiagnosticsTestCase(unittest.TestCase):
    def test_channel_specs_cover_all_non_unknown_enum_channels(self):
        spec_channels = {spec.channel for spec in CHANNEL_SPECS}
        expected = {
            channel.value
            for channel in NotificationChannel
            if channel is not NotificationChannel.UNKNOWN
        }

        self.assertTrue(expected.issubset(spec_channels))
        self.assertIn(NotificationChannel.UNKNOWN.value, spec_channels)
        self.assertIn("dingtalk_context", spec_channels)
        self.assertIn("feishu_context", spec_channels)

    def test_key_specs_include_minimal_and_advanced_keys(self):
        key_tiers = {(spec.key, spec.tier) for spec in KEY_SPECS}

        self.assertIn(("ASTRBOT_URL", "minimal"), key_tiers)
        self.assertIn(("ASTRBOT_TOKEN", "advanced"), key_tiers)
        self.assertIn(("CUSTOM_WEBHOOK_BODY_TEMPLATE", "advanced"), key_tiers)
        self.assertIn(("WEBHOOK_VERIFY_SSL", "advanced"), key_tiers)
        self.assertIn(("DISCORD_BOT_TOKEN", "minimal"), key_tiers)
        self.assertIn(("SLACK_BOT_TOKEN", "minimal"), key_tiers)
        self.assertNotIn(("DISCORD_BOT_TOKEN", "advanced"), key_tiers)
        self.assertNotIn(("SLACK_BOT_TOKEN", "advanced"), key_tiers)

    def test_empty_config_reports_no_channels_as_error(self):
        result = run_notification_diagnostics(_config())

        self.assertIsInstance(result, NotificationDiagnosticResult)
        self.assertEqual(result.configured_channels, ())
        self.assertFalse(result.ok)
        self.assertIn("no_channels_configured", {item.code for item in result.errors})

        output = format_notification_diagnostics(result)
        self.assertIn("已配置渠道: 0 个", output)
        self.assertIn("0 个通知渠道已配置", output)

    def test_partial_config_reports_missing_pair(self):
        result = run_notification_diagnostics(_config(telegram_bot_token="TOKEN"))

        self.assertFalse(result.ok)
        self.assertIn("TELEGRAM_CHAT_ID", {item.key for item in result.errors})

    def test_partial_alternate_bot_config_warns_when_webhook_is_configured(self):
        result = run_notification_diagnostics(
            _config(
                discord_webhook_url="https://discord.example/webhook",
                discord_bot_token="TOKEN",
            )
        )

        self.assertTrue(result.ok)
        self.assertIn("DISCORD_MAIN_CHANNEL_ID", {item.key for item in result.warnings})
        self.assertNotIn("DISCORD_MAIN_CHANNEL_ID", {item.key for item in result.errors})

    def test_configured_channels_use_runtime_detector(self):
        result = run_notification_diagnostics(
            _config(
                wechat_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=1",
                astrbot_url="https://astrbot.example/webhook",
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.configured_channels, ("wechat", "astrbot"))

    def test_advanced_key_without_minimal_warns_but_is_structured(self):
        result = run_notification_diagnostics(_config(pushplus_topic="topic-only"))

        self.assertFalse(result.ok)
        warning_keys = {item.key for item in result.warnings}
        self.assertIn("PUSHPLUS_TOKEN", warning_keys)
        self.assertIn("context_channels_runtime_only", {item.code for item in result.info})


if __name__ == "__main__":
    unittest.main()
