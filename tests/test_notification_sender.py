# -*- coding: utf-8 -*-
"""
Unit tests for src.notification_sender module.

Tests sender classes in isolation (config, request shape, error handling).
Does not duplicate test_notification.py which tests NotificationService.send() flow.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import unittest
from email.header import decode_header, make_header
from email.utils import parseaddr
from unittest import mock
from typing import Optional

import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import Config
from src.notification_sender import (
    AstrbotSender,
    CustomWebhookSender,
    DiscordSender,
    EmailSender,
    FeishuSender,
    NtfySender,
    PushoverSender,
    PushplusSender,
    Serverchan3Sender,
    SlackSender,
    TelegramSender,
    WechatSender,
    WECHAT_IMAGE_MAX_BYTES,
)


def _config(**overrides):
    """Minimal Config for sender tests."""
    return Config(stock_list=[], **overrides)


def _response(status_code: int, json_body: Optional[dict] = None):
    resp = mock.MagicMock()
    resp.status_code = status_code
    if status_code == 200:
        resp.text = "ok"
    else:
        resp.text = "error"
    if json_body is not None:
        resp.json.return_value = json_body
    return resp


class TestDiscordSender(unittest.TestCase):
    """Unit tests for DiscordSender."""

    def test_send_returns_false_when_not_configured(self):
        cfg = _config()
        sender = DiscordSender(cfg)
        result = sender.send_to_discord("hello")
        self.assertFalse(result)

    def test_is_discord_configured_webhook_only(self):
        cfg = _config(discord_webhook_url="https://discord.com/webhook/1")
        sender = DiscordSender(cfg)
        self.assertTrue(sender._is_discord_configured())

    def test_is_discord_configured_bot_only(self):
        cfg = _config(discord_bot_token="T", discord_main_channel_id="123")
        sender = DiscordSender(cfg)
        self.assertTrue(sender._is_discord_configured())

    def test_is_discord_configured_neither(self):
        cfg = _config()
        sender = DiscordSender(cfg)
        self.assertFalse(sender._is_discord_configured())

    @mock.patch("src.notification_sender.discord_sender.requests.post")
    def test_send_webhook_success_builds_correct_payload(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(discord_webhook_url="https://discord.com/webhook/1")
        sender = DiscordSender(cfg)
        result = sender.send_to_discord("content")
        self.assertTrue(result)
        mock_post.assert_called_once()
        call_kw = mock_post.call_args[1]
        self.assertEqual(call_kw["json"]["content"], "content")
        self.assertIn("username", call_kw["json"])

    @mock.patch("src.notification_sender.discord_sender.requests.post")
    def test_send_webhook_http_error_returns_false(self, mock_post):
        mock_post.return_value = _response(400)
        cfg = _config(discord_webhook_url="https://discord.com/webhook/1")
        sender = DiscordSender(cfg)
        result = sender.send_to_discord("content")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.discord_sender.requests.post")
    def test_send_bot_success_uses_channel_url(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(discord_bot_token="TOKEN", discord_main_channel_id="CH123")
        sender = DiscordSender(cfg)
        result = sender.send_to_discord("content")
        self.assertTrue(result)
        self.assertIn("discord.com/api/v10/channels/CH123/messages", mock_post.call_args[0][0])
        call_kw = mock_post.call_args[1]
        self.assertEqual(call_kw["headers"]["Authorization"], "Bot TOKEN")


class TestWechatSender(unittest.TestCase):
    """Unit tests for WechatSender."""

    def test_send_returns_false_when_no_webhook_url(self):
        cfg = _config()
        sender = WechatSender(cfg)
        result = sender.send_to_wechat("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.wechat_sender.requests.post")
    def test_send_success_returns_true(self, mock_post):
        mock_post.return_value = _response(200, {"errcode": 0})
        cfg = _config(wechat_webhook_url="https://wechat.example/hook")
        sender = WechatSender(cfg)
        result = sender.send_to_wechat("hello")
        self.assertTrue(result)

    def test_gen_wechat_payload_markdown(self):
        cfg = _config(wechat_webhook_url="u", wechat_msg_type="markdown")
        sender = WechatSender(cfg)
        payload = sender._gen_wechat_payload("## title\nbody")
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertEqual(payload["markdown"]["content"], "## title\nbody")

    def test_gen_wechat_payload_text(self):
        cfg = _config(wechat_webhook_url="u", wechat_msg_type="text")
        sender = WechatSender(cfg)
        payload = sender._gen_wechat_payload("plain")
        self.assertEqual(payload["msgtype"], "text")
        self.assertEqual(payload["text"]["content"], "plain")

    @mock.patch("src.notification_sender.wechat_sender.requests.post")
    def test_send_wechat_image_over_limit_returns_false(self, mock_post):
        cfg = _config(wechat_webhook_url="https://wechat.example/hook")
        sender = WechatSender(cfg)
        big = b"x" * (WECHAT_IMAGE_MAX_BYTES + 1)
        result = sender._send_wechat_image(big)
        self.assertFalse(result)
        mock_post.assert_not_called()


class TestFeishuSender(unittest.TestCase):
    """Unit tests for FeishuSender."""

    def test_send_returns_false_when_no_webhook_url(self):
        cfg = _config()
        sender = FeishuSender(cfg)
        result = sender.send_to_feishu("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.feishu_sender.requests.post")
    def test_send_success_returns_true(self, mock_post):
        mock_post.return_value = _response(200, {"code": 0})
        cfg = _config(feishu_webhook_url="https://feishu.example/hook")
        sender = FeishuSender(cfg)
        result = sender.send_to_feishu("hello")
        self.assertTrue(result)

    @mock.patch("src.notification_sender.feishu_sender.requests.post")
    def test_send_http_error_returns_false(self, mock_post):
        mock_post.return_value = _response(400)
        cfg = _config(feishu_webhook_url="https://feishu.example/hook")
        sender = FeishuSender(cfg)
        result = sender.send_to_feishu("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.feishu_sender.time.time", return_value=1700000000)
    @mock.patch("src.notification_sender.feishu_sender.requests.post")
    def test_send_with_secret_and_keyword_builds_signed_payload(self, mock_post, _mock_time):
        mock_post.return_value = _response(200, {"code": 0})
        cfg = _config(
            feishu_webhook_url="https://feishu.example/hook",
            feishu_webhook_secret="secret-token",
            feishu_webhook_keyword="股票日报",
        )
        sender = FeishuSender(cfg)

        result = sender.send_to_feishu("hello")

        self.assertTrue(result)
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["timestamp"], "1700000000")
        expected_sign = base64.b64encode(
            hmac.new(
                b"1700000000\nsecret-token",
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        self.assertEqual(payload["sign"], expected_sign)
        self.assertEqual(
            payload["card"]["elements"][0]["text"]["content"],
            "股票日报\nhello",
        )

    @mock.patch("src.notification_sender.feishu_sender.requests.post")
    def test_send_error_response_returns_false(self, mock_post):
        mock_post.return_value = _response(200, {"code": 19024, "msg": "keyword not found"})
        cfg = _config(feishu_webhook_url="https://feishu.example/hook")
        sender = FeishuSender(cfg)

        result = sender.send_to_feishu("hello")

        self.assertFalse(result)
        self.assertEqual(mock_post.call_count, 2)

    @mock.patch("src.notification_sender.feishu_sender.requests.post")
    def test_send_with_keyword_that_leaves_too_little_chunk_budget_returns_false(self, mock_post):
        cfg = _config(
            feishu_webhook_url="https://feishu.example/hook",
            feishu_webhook_keyword="abcd",
            feishu_max_bytes=60,
        )
        sender = FeishuSender(cfg)

        result = sender.send_to_feishu("x" * 100)

        self.assertFalse(result)
        mock_post.assert_not_called()


class TestEmailSender(unittest.TestCase):
    """Unit tests for EmailSender (config and receiver logic; send path covered via service)."""

    def test_send_returns_false_when_not_configured(self):
        cfg = _config()
        sender = EmailSender(cfg)
        result = sender.send_to_email("body")
        self.assertFalse(result)

    def test_get_receivers_for_stocks_no_groups_returns_default(self):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["b@qq.com", "c@qq.com"],
        )
        sender = EmailSender(cfg)
        self.assertEqual(
            sender.get_receivers_for_stocks(["000001"]),
            ["b@qq.com", "c@qq.com"],
        )

    def test_get_receivers_for_stocks_with_matching_group(self):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["default@qq.com"],
            stock_email_groups=[(["000001", "600519"], ["group1@qq.com"])],
        )
        sender = EmailSender(cfg)
        self.assertEqual(
            sender.get_receivers_for_stocks(["000001"]),
            ["group1@qq.com"],
        )

    def test_get_receivers_for_stocks_no_match_falls_back_to_default(self):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["default@qq.com"],
            stock_email_groups=[(["000001"], ["group@qq.com"])],
        )
        sender = EmailSender(cfg)
        self.assertEqual(
            sender.get_receivers_for_stocks(["999999"]),
            ["default@qq.com"],
        )

    def test_get_all_email_receivers_returns_union(self):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["default@qq.com"],
            stock_email_groups=[
                (["000001"], ["g1@qq.com"]),
                (["600519"], ["g2@qq.com"]),
            ],
        )
        sender = EmailSender(cfg)
        receivers = sender.get_all_email_receivers()
        self.assertIn("g1@qq.com", receivers)
        self.assertIn("g2@qq.com", receivers)
        self.assertIn("default@qq.com", receivers)

    @mock.patch("smtplib.SMTP_SSL")
    def test_send_to_email_encodes_non_ascii_sender_name(self, mock_smtp_ssl):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["b@qq.com"],
            email_sender_name="daily_stock_analysis股票分析助手",
        )
        sender = EmailSender(cfg)

        result = sender.send_to_email("body", subject="测试主题")

        self.assertTrue(result)
        server = mock_smtp_ssl.return_value
        server.send_message.assert_called_once()
        msg = server.send_message.call_args[0][0]
        realname, addr = parseaddr(msg["From"])
        self.assertEqual(addr, "a@qq.com")
        self.assertEqual(
            str(make_header(decode_header(realname))),
            "daily_stock_analysis股票分析助手",
        )
        server.quit.assert_called_once()

    @mock.patch("smtplib.SMTP_SSL")
    def test_send_image_email_encodes_non_ascii_sender_name(self, mock_smtp_ssl):
        cfg = _config(
            email_sender="a@qq.com",
            email_password="p",
            email_receivers=["b@qq.com"],
            email_sender_name="daily_stock_analysis股票分析助手",
        )
        sender = EmailSender(cfg)

        result = sender._send_email_with_inline_image(b"PNG_BYTES", receivers=["b@qq.com"])

        self.assertTrue(result)
        server = mock_smtp_ssl.return_value
        server.send_message.assert_called_once()
        msg = server.send_message.call_args[0][0]
        realname, addr = parseaddr(msg["From"])
        self.assertEqual(addr, "a@qq.com")
        self.assertEqual(
            str(make_header(decode_header(realname))),
            "daily_stock_analysis股票分析助手",
        )
        server.quit.assert_called_once()


class TestNtfySender(unittest.TestCase):
    """Unit tests for NtfySender."""

    def test_send_returns_false_when_not_configured(self):
        cfg = _config()
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("hello")

        self.assertFalse(result)

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
    def test_send_success_uses_json_publish_with_topic_endpoint(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(
            ntfy_url="https://ntfy.sh/dsa-topic",
            ntfy_token="secret-token",
            webhook_verify_ssl=False,
        )
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("正文 **Markdown**", title="中文标题", timeout_seconds=5)

        self.assertTrue(result)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.args[0], "https://ntfy.sh")
        call_kw = mock_post.call_args.kwargs
        self.assertEqual(
            call_kw["json"],
            {
                "topic": "dsa-topic",
                "title": "中文标题",
                "message": "正文 **Markdown**",
                "markdown": True,
            },
        )
        self.assertEqual(call_kw["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(call_kw["timeout"], 5)
        self.assertFalse(call_kw["verify"])

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
    def test_send_supports_self_hosted_path_prefix(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(ntfy_url="https://example.com/ntfy/dsa-topic")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body", title="title")

        self.assertTrue(result)
        self.assertEqual(mock_post.call_args.args[0], "https://example.com/ntfy")
        self.assertEqual(mock_post.call_args.kwargs["json"]["topic"], "dsa-topic")

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
    def test_send_returns_false_when_url_has_no_topic(self, mock_post):
        cfg = _config(ntfy_url="https://ntfy.sh")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body")

        self.assertFalse(result)
        mock_post.assert_not_called()

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
    def test_send_returns_false_when_url_scheme_is_not_http(self, mock_post):
        cfg = _config(ntfy_url="ftp://ntfy.example/dsa-topic")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body")

        self.assertFalse(result)
        mock_post.assert_not_called()

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
    def test_send_http_error_returns_false(self, mock_post):
        mock_post.return_value = _response(500)
        cfg = _config(ntfy_url="https://ntfy.sh/dsa-topic")
        sender = NtfySender(cfg)

        result = sender.send_to_ntfy("body")

        self.assertFalse(result)

    @mock.patch("src.notification_sender.ntfy_sender.requests.post")
    def test_send_timeout_does_not_log_token_value(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("secret-token")
        cfg = _config(ntfy_url="https://ntfy.sh/dsa-topic", ntfy_token="secret-token")
        sender = NtfySender(cfg)

        with self.assertLogs("src.notification_sender.ntfy_sender", level="ERROR") as captured:
            result = sender.send_to_ntfy("body")

        self.assertFalse(result)
        self.assertNotIn("secret-token", "\n".join(captured.output))


class TestAstrbotSender(unittest.TestCase):
    """Unit tests for AstrbotSender."""

    def test_send_returns_false_when_no_url(self):
        cfg = _config()
        sender = AstrbotSender(cfg)
        result = sender.send_to_astrbot("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.astrbot_sender.requests.post")
    def test_send_success_returns_true(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(astrbot_url="https://astrbot.example/api")
        sender = AstrbotSender(cfg)
        result = sender.send_to_astrbot("hello")
        self.assertTrue(result)
        self.assertEqual(mock_post.call_args[0][0], "https://astrbot.example/api")


class TestCustomWebhookSender(unittest.TestCase):
    """Unit tests for CustomWebhookSender."""

    def test_send_returns_false_when_no_urls(self):
        cfg = _config()
        sender = CustomWebhookSender(cfg)
        result = sender.send_to_custom("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_send_success_payload_has_text_and_content(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(custom_webhook_urls=["https://example.com/webhook"])
        sender = CustomWebhookSender(cfg)
        result = sender.send_to_custom("hello")
        self.assertTrue(result)
        body = mock_post.call_args[1]["data"].decode("utf-8")
        self.assertIn("hello", body)

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_send_returns_true_when_one_custom_webhook_succeeds(self, mock_post):
        mock_post.side_effect = [_response(500), _response(200)]
        cfg = _config(
            custom_webhook_urls=[
                "https://example.com/fail",
                "https://example.com/ok",
            ]
        )
        sender = CustomWebhookSender(cfg)

        result = sender.send_to_custom("hello")

        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 2)

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_test_custom_webhooks_returns_ordered_attempts(self, mock_post):
        mock_post.side_effect = [_response(500), _response(200)]
        cfg = _config(
            custom_webhook_urls=[
                "https://example.com/fail?access_token=secret",
                "https://example.com/ok",
            ]
        )
        sender = CustomWebhookSender(cfg)

        attempts = sender.test_custom_webhooks("hello", timeout_seconds=7)

        self.assertEqual(len(attempts), 2)
        self.assertFalse(attempts[0]["success"])
        self.assertTrue(attempts[1]["success"])
        self.assertEqual(attempts[0]["http_status"], 500)
        self.assertEqual(mock_post.call_args_list[0].kwargs["timeout"], 7)

    def test_bark_payload_shape_is_stable(self):
        sender = CustomWebhookSender(_config())

        payload = sender._build_custom_webhook_payload("https://api.day.app/key", "hello")

        self.assertEqual(
            payload,
            {
                "title": "股票分析报告",
                "body": "hello",
                "group": "stock",
            },
        )

    def test_bark_payload_truncates_long_content(self):
        sender = CustomWebhookSender(_config())

        payload = sender._build_custom_webhook_payload("https://api.day.app/key", "x" * 5000)

        self.assertEqual(len(payload["body"]), 4000)
        self.assertEqual(payload["body"], "x" * 4000)

    def test_custom_body_template_overrides_bark_auto_payload(self):
        cfg = _config(
            custom_webhook_body_template=(
                '{"title":$title_json,"body":$content_json,"sound":"bell"}'
            ),
        )
        sender = CustomWebhookSender(cfg)

        payload = sender._build_custom_webhook_payload("https://api.day.app/key", "hello")

        self.assertEqual(
            payload,
            {
                "title": "股票分析报告",
                "body": "hello",
                "sound": "bell",
            },
        )
        self.assertNotIn("group", payload)

    def test_custom_body_template_json_placeholders_escape_content(self):
        cfg = _config(
            custom_webhook_body_template=(
                '{"title":$title_json,"content":$content_json}'
            ),
        )
        sender = CustomWebhookSender(cfg)

        payload = sender._build_custom_webhook_payload(
            "https://example.com/webhook",
            'line 1\nline "2"',
        )

        self.assertEqual(
            payload,
            {
                "title": "股票分析报告",
                "content": 'line 1\nline "2"',
            },
        )

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_send_uses_custom_body_template(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(
            custom_webhook_urls=["https://example.com/webhook"],
            custom_webhook_body_template='{"msg_type":"text","content":$content_json}',
        )
        sender = CustomWebhookSender(cfg)

        result = sender.send_to_custom('hello "world"')

        self.assertTrue(result)
        body = mock_post.call_args[1]["data"].decode("utf-8")
        self.assertEqual(
            json.loads(body),
            {"msg_type": "text", "content": 'hello "world"'},
        )

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_dingtalk_send_uses_custom_body_template(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(
            custom_webhook_urls=["https://oapi.dingtalk.com/robot/send?access_token=token"],
            custom_webhook_body_template='{"msgtype":"text","text":{"content":$content_json}}',
        )
        sender = CustomWebhookSender(cfg)

        result = sender.send_to_custom("hello dingtalk")

        self.assertTrue(result)
        mock_post.assert_called_once()
        body = mock_post.call_args[1]["data"].decode("utf-8")
        self.assertEqual(
            json.loads(body),
            {"msgtype": "text", "text": {"content": "hello dingtalk"}},
        )

    @mock.patch("time.sleep", return_value=None)
    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_dingtalk_template_failure_falls_back_to_chunked_send(
        self, mock_post, _mock_sleep
    ):
        mock_post.side_effect = [_response(400), _response(200), _response(200), _response(200)]
        cfg = _config(
            custom_webhook_urls=["https://oapi.dingtalk.com/robot/send?access_token=token"],
            custom_webhook_body_template='{"msgtype":"text","text":{"content":$content_json}}',
        )
        sender = CustomWebhookSender(cfg)

        result = sender.send_to_custom("A" * 40000)

        self.assertTrue(result)
        self.assertGreater(mock_post.call_count, 1)
        first_body = json.loads(mock_post.call_args_list[0].kwargs["data"].decode("utf-8"))
        fallback_body = json.loads(mock_post.call_args_list[1].kwargs["data"].decode("utf-8"))
        self.assertEqual(first_body["msgtype"], "text")
        self.assertEqual(fallback_body["msgtype"], "markdown")
        self.assertIn("markdown", fallback_body)

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_invalid_custom_body_template_falls_back(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(
            custom_webhook_urls=["https://example.com/webhook"],
            custom_webhook_body_template='{"content": $content',
        )
        sender = CustomWebhookSender(cfg)

        result = sender.send_to_custom("hello")

        self.assertTrue(result)
        body = mock_post.call_args[1]["data"].decode("utf-8")
        self.assertIn("hello", body)

    @mock.patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_non_object_custom_body_template_falls_back(self, mock_post):
        mock_post.return_value = _response(200)
        cfg = _config(
            custom_webhook_urls=["https://example.com/webhook"],
            custom_webhook_body_template='["not", "object"]',
        )
        sender = CustomWebhookSender(cfg)

        result = sender.send_to_custom("hello")

        self.assertTrue(result)
        body = json.loads(mock_post.call_args[1]["data"].decode("utf-8"))
        self.assertEqual(body["content"], "hello")
        self.assertEqual(body["message"], "hello")


class TestPushoverSender(unittest.TestCase):
    """Unit tests for PushoverSender."""

    def test_send_returns_false_when_not_configured(self):
        cfg = _config()
        sender = PushoverSender(cfg)
        result = sender.send_to_pushover("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.pushover_sender.requests.post")
    def test_send_success_returns_true(self, mock_post):
        mock_post.return_value = _response(200, {"status": 1})
        cfg = _config(pushover_user_key="U", pushover_api_token="T")
        sender = PushoverSender(cfg)
        result = sender.send_to_pushover("hello")
        self.assertTrue(result)
        call_data = mock_post.call_args[1]["data"]
        self.assertEqual(call_data["user"], "U")
        self.assertEqual(call_data["token"], "T")

    @mock.patch("time.sleep")
    @mock.patch("src.notification_sender.pushover_sender.requests.post")
    def test_send_chunked_uses_test_timeout(self, mock_post, _mock_sleep):
        mock_post.return_value = _response(200, {"status": 1})
        cfg = _config(pushover_user_key="U", pushover_api_token="T")
        sender = PushoverSender(cfg)

        result = sender.send_to_pushover("\n\n".join(["A" * 800, "B" * 800, "C" * 800]), timeout_seconds=9)

        self.assertTrue(result)
        self.assertGreaterEqual(mock_post.call_count, 2)
        self.assertTrue(all(call.kwargs["timeout"] == 9 for call in mock_post.call_args_list))


class TestPushplusSender(unittest.TestCase):
    """Unit tests for PushplusSender."""

    def test_send_returns_false_when_no_token(self):
        cfg = _config()
        sender = PushplusSender(cfg)
        result = sender.send_to_pushplus("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.pushplus_sender.requests.post")
    def test_send_success_returns_true(self, mock_post):
        mock_post.return_value = _response(200, {"code": 200})
        cfg = _config(pushplus_token="TOKEN")
        sender = PushplusSender(cfg)
        result = sender.send_to_pushplus("hello")
        self.assertTrue(result)

    @mock.patch("src.notification_sender.pushplus_sender.time.sleep")
    @mock.patch("src.notification_sender.pushplus_sender.requests.post")
    def test_send_long_message_chunks_pushplus_requests(self, mock_post, _mock_sleep):
        mock_post.return_value = _response(200, {"code": 200})
        cfg = _config(pushplus_token="TOKEN")
        sender = PushplusSender(cfg)

        result = sender.send_to_pushplus("A" * 25000)

        self.assertTrue(result)
        self.assertGreaterEqual(mock_post.call_count, 2)


class TestServerchan3Sender(unittest.TestCase):
    """Unit tests for Serverchan3Sender."""

    def test_send_returns_false_when_no_sendkey(self):
        cfg = _config()
        sender = Serverchan3Sender(cfg)
        result = sender.send_to_serverchan3("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.serverchan3_sender.requests.post")
    def test_send_success_returns_true(self, mock_post):
        mock_post.return_value = _response(200, {"code": 0})
        cfg = _config(serverchan3_sendkey="SCT123")
        sender = Serverchan3Sender(cfg)
        result = sender.send_to_serverchan3("hello")
        self.assertTrue(result)


class TestSlackSender(unittest.TestCase):
    """Unit tests for SlackSender."""

    def test_send_returns_false_when_not_configured(self):
        cfg = _config()
        sender = SlackSender(cfg)
        result = sender.send_to_slack("hello")
        self.assertFalse(result)

    def test_is_slack_configured_webhook_only(self):
        cfg = _config(slack_webhook_url="https://hooks.slack.com/services/T/B/xxx")
        sender = SlackSender(cfg)
        self.assertTrue(sender._is_slack_configured())

    def test_is_slack_configured_bot_only(self):
        cfg = _config(slack_bot_token="xoxb-test", slack_channel_id="C123")
        sender = SlackSender(cfg)
        self.assertTrue(sender._is_slack_configured())

    def test_is_slack_configured_neither(self):
        cfg = _config()
        sender = SlackSender(cfg)
        self.assertFalse(sender._is_slack_configured())

    @mock.patch("src.notification_sender.slack_sender.requests.post")
    def test_send_webhook_success(self, mock_post):
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        mock_post.return_value = resp
        cfg = _config(slack_webhook_url="https://hooks.slack.com/services/T/B/xxx")
        sender = SlackSender(cfg)
        result = sender.send_to_slack("hello")
        self.assertTrue(result)
        mock_post.assert_called_once()

    @mock.patch("src.notification_sender.slack_sender.requests.post")
    def test_send_webhook_http_error_returns_false(self, mock_post):
        resp = mock.MagicMock()
        resp.status_code = 400
        resp.text = "invalid_payload"
        mock_post.return_value = resp
        cfg = _config(slack_webhook_url="https://hooks.slack.com/services/T/B/xxx")
        sender = SlackSender(cfg)
        result = sender.send_to_slack("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.slack_sender.requests.post")
    def test_send_bot_success(self, mock_post):
        mock_post.return_value = _response(200, {"ok": True})
        cfg = _config(slack_bot_token="xoxb-test", slack_channel_id="C123")
        sender = SlackSender(cfg)
        result = sender.send_to_slack("hello")
        self.assertTrue(result)
        self.assertIn("chat.postMessage", mock_post.call_args[0][0])

    @mock.patch("src.notification_sender.slack_sender.requests.post")
    def test_send_bot_error_returns_false(self, mock_post):
        mock_post.return_value = _response(200, {"ok": False, "error": "channel_not_found"})
        cfg = _config(slack_bot_token="xoxb-test", slack_channel_id="C123")
        sender = SlackSender(cfg)
        result = sender.send_to_slack("hello")
        self.assertFalse(result)

    def test_build_blocks_splits_long_content(self):
        cfg = _config(slack_webhook_url="https://hooks.slack.com/services/T/B/xxx")
        sender = SlackSender(cfg)
        content = "A" * 6500  # > 3000 * 2, should produce 3 blocks
        blocks = sender._build_blocks(content)
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0]["type"], "section")
        self.assertEqual(blocks[0]["text"]["type"], "mrkdwn")

    @mock.patch("src.notification_sender.slack_sender.requests.post")
    def test_send_text_prefers_bot_when_both_configured(self, mock_post):
        """When both webhook and bot are configured, text must go via bot
        so it lands in the same channel as images."""
        mock_post.return_value = _response(200, {"ok": True})
        cfg = _config(
            slack_webhook_url="https://hooks.slack.com/services/T/B/xxx",
            slack_bot_token="xoxb-test",
            slack_channel_id="C123",
        )
        sender = SlackSender(cfg)
        result = sender.send_to_slack("hello")
        self.assertTrue(result)
        self.assertIn("chat.postMessage", mock_post.call_args[0][0])

    @mock.patch("src.notification_sender.slack_sender.requests.post")
    def test_send_image_bot_success(self, mock_post):
        # Mock three sequential calls: getUploadURLExternal, PUT upload, completeUploadExternal
        mock_post.side_effect = [
            _response(200, {"ok": True, "upload_url": "https://files.slack.com/upload/v1/test", "file_id": "F123"}),
            _response(200, {}),
            _response(200, {"ok": True}),
        ]
        cfg = _config(slack_bot_token="xoxb-test", slack_channel_id="C123")
        sender = SlackSender(cfg)
        result = sender._send_slack_image(b"PNG_BYTES")
        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 3)
        self.assertIn("getUploadURLExternal", mock_post.call_args_list[0][0][0])
        # Step 2: upload must send raw bytes (not multipart) to match declared length
        upload_call_kwargs = mock_post.call_args_list[1][1]
        self.assertEqual(upload_call_kwargs.get("data"), b"PNG_BYTES")
        self.assertNotIn("files", upload_call_kwargs)
        self.assertIn("completeUploadExternal", mock_post.call_args_list[2][0][0])

    @mock.patch("src.notification_sender.slack_sender.requests.post")
    def test_send_image_fallback_to_text_when_no_bot(self, mock_post):
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.text = "ok"
        mock_post.return_value = resp
        cfg = _config(slack_webhook_url="https://hooks.slack.com/services/T/B/xxx")
        sender = SlackSender(cfg)
        result = sender._send_slack_image(b"PNG_BYTES", fallback_content="fallback text")
        self.assertTrue(result)


class TestTelegramSender(unittest.TestCase):
    """Unit tests for TelegramSender."""

    def test_send_returns_false_when_not_configured(self):
        cfg = _config()
        sender = TelegramSender(cfg)
        result = sender.send_to_telegram("hello")
        self.assertFalse(result)

    @mock.patch("src.notification_sender.telegram_sender.requests.post")
    def test_send_success_returns_true(self, mock_post):
        mock_post.return_value = _response(200, {"ok": True})
        cfg = _config(telegram_bot_token="BOT", telegram_chat_id="CHAT")
        sender = TelegramSender(cfg)
        result = sender.send_to_telegram("hello")
        self.assertTrue(result)
        self.assertIn("sendMessage", mock_post.call_args[0][0])

    @mock.patch("src.notification_sender.telegram_sender.requests.post")
    def test_send_retries_plain_text_when_markdown_http_400(self, mock_post):
        markdown_error = _response(400)
        markdown_error.text = (
            '{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse entities"}'
        )
        plain_text_success = _response(200, {"ok": True})
        mock_post.side_effect = [markdown_error, plain_text_success]

        cfg = _config(telegram_bot_token="BOT", telegram_chat_id="CHAT")
        sender = TelegramSender(cfg)
        result = sender.send_to_telegram("*ST宝实")

        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 2)
        first_payload = mock_post.call_args_list[0][1]["json"]
        second_payload = mock_post.call_args_list[1][1]["json"]
        self.assertEqual(first_payload["parse_mode"], "Markdown")
        self.assertNotIn("parse_mode", second_payload)
        self.assertEqual(second_payload["text"], "*ST宝实")

    @mock.patch("src.notification_sender.telegram_sender.requests.post")
    def test_send_plain_text_fallback_handles_non_json_200(self, mock_post):
        markdown_error = _response(400)
        markdown_error.text = (
            '{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse entities"}'
        )
        plain_text_non_json = _response(200)
        plain_text_non_json.text = "upstream proxy error"
        plain_text_non_json.json.side_effect = ValueError("invalid json")
        mock_post.side_effect = [markdown_error, plain_text_non_json]

        cfg = _config(telegram_bot_token="BOT", telegram_chat_id="CHAT")
        sender = TelegramSender(cfg)
        result = sender.send_to_telegram("*ST宝实")

        self.assertFalse(result)
        self.assertEqual(mock_post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
