# -*- coding: utf-8 -*-
"""
WeCom AI Bot Phase 2 测试：通知推送渠道（aibot_send_msg）+ 配置链。

验收映射（issue #755 正文「### 验收要求」）：
- ⑤ 保持现有企微通知推送行为 + 失败路径回归：
  * 既有 webhook 渠道检测/发送回归：test_acc5_wechat_webhook_channel_*；
    既有 tests/test_notification_sender.py::TestWechatSender 原样跑绿
    （webhook sender 文件零改动）。
  * aibot 渠道失败降级：未启用/未配置 chatid/SDK 缺失/客户端未运行/
    限流/回执错误/异常 全部返回 False 且不抛。

推送渠道契约（官方协议约束，PR body 同步标注）：
- 前置条件：目标用户须先与机器人建过会话（aibot_send_msg 只能推送到
  已存在会话）；推送目标为 chatid（单聊=userid，群聊=chatid）。
- 限流：30 条/分钟、1000 条/小时、同会话并发 3 条。渠道限流器为进程级
  共享单例（跨 sender 实例共享预算，OR-COR-4c720f93），且静态推送经
  WecomAibotClient.send_to_chat 复用 handler 级双窗口配额（真实总量口径，
  与回复/上下文推送同账本，Phase 1 r2 基底）。
- 默认关：WECOM_AIBOT_NOTIFY_ENABLED=false；须同时配置
  WECOM_AIBOT_NOTIFY_CHATID 才被视为已配置渠道。
"""

import os
import re
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.notification_sender.wecom_aibot_sender import (
    AibotPushRateLimiter,
    WecomAibotSender,
)

# Phase 2 新增配置键（默认关）。
WECOM_AIBOT_NOTIFY_KEYS = (
    "WECOM_AIBOT_NOTIFY_ENABLED",
    "WECOM_AIBOT_NOTIFY_CHATID",
)
# 全量 aibot 键 = Phase 1 四键 + Phase 2 两键（test_wecom_aibot.py 的
# WECOM_AIBOT_KEYS 与此处共同构成闭集断言）。
WECOM_AIBOT_ALL_KEYS = (
    "WECOM_AIBOT_ENABLED",
    "WECOM_AIBOT_BOT_ID",
    "WECOM_AIBOT_SECRET",
    "WECOM_AIBOT_REPLY_STREAM",
) + WECOM_AIBOT_NOTIFY_KEYS


def _config(**overrides):
    from src.config import Config

    defaults = dict(stock_list=[])
    defaults.update(overrides)
    return Config(**defaults)


def _running_client(chat_id="chat-1", result_frame=None):
    """Mock a running WecomAibotClient whose send_to_chat succeeds (r2 base)."""
    client = mock.MagicMock()
    client.is_running = True
    client.send_to_chat.return_value = True
    return client


# ---------------------------------------------------------------------------
# Acceptance ⑤: existing WeChat webhook behaviour unchanged
# ---------------------------------------------------------------------------


class TestAcc5WechatWebhookRegression:
    def test_acc5_wechat_webhook_channel_detection_unchanged(self):
        """验收⑤：webhook 已配置 + aibot 推送未启用 => 检测结果与 Phase 1 前一致。"""
        from src.notification import NotificationChannel, NotificationService

        config = _config(wechat_webhook_url="https://qyapi.weixin.qq.com/hook")
        channels = NotificationService.detect_configured_channels(config)

        assert NotificationChannel.WECHAT in channels
        assert NotificationChannel.WECOM_AIBOT not in channels

    def test_acc5_wechat_webhook_send_path_untouched(self):
        """验收⑤：WechatSender.send_to_wechat 请求行为回归（webhook 文件零改动）。"""
        from src.notification_sender.wechat_sender import WechatSender

        config = _config(wechat_webhook_url="https://qyapi.weixin.qq.com/hook")
        sender = WechatSender(config)

        with mock.patch("src.notification_sender.wechat_sender.requests.post") as m_post:
            m_post.return_value.status_code = 200
            m_post.return_value.json.return_value = {"errcode": 0}
            ok = sender.send_to_wechat("hello")
            assert ok is True
            args, kwargs = m_post.call_args
            assert args[0] == "https://qyapi.weixin.qq.com/hook"
            assert kwargs["json"] == {
                "msgtype": "markdown",
                "markdown": {"content": "hello"},
            }

    def test_acc5_aibot_channel_does_not_hijack_webhook_channel(self):
        """验收⑤：aibot 渠道是新增并存渠道，不替换 WECHAT 渠道。"""
        from src.notification import NotificationChannel, NotificationService

        config = _config(
            wechat_webhook_url="https://qyapi.weixin.qq.com/hook",
            wecom_aibot_notify_enabled=True,
            wecom_aibot_notify_chatid="chat-1",
        )
        channels = NotificationService.detect_configured_channels(config)

        assert NotificationChannel.WECHAT in channels
        assert NotificationChannel.WECOM_AIBOT in channels


# ---------------------------------------------------------------------------
# Push channel sender — degraded / failure paths (all must return False)
# ---------------------------------------------------------------------------


class TestAcc5PushFailureDegradation:
    def test_acc5_push_disabled_by_default(self):
        """验收⑤：默认关——未启用时零副作用返回 False。"""
        sender = WecomAibotSender(_config())

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client"
        ) as m_get:
            ok = sender.send_to_wecom_aibot("daily report")

        assert ok is False
        m_get.assert_not_called()

    def test_push_enabled_without_chatid_is_noop(self):
        sender = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid=None)
        )

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client"
        ) as m_get:
            ok = sender.send_to_wecom_aibot("daily report")

        assert ok is False
        m_get.assert_not_called()

    def test_push_sdk_missing_degrades_to_false(self):
        """SDK 缺失：get_wecom_aibot_client 返回 None（含安装提示），渠道降级。"""
        sender = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1")
        )

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client",
            return_value=None,
        ):
            ok = sender.send_to_wecom_aibot("daily report")

        assert ok is False

    def test_push_when_client_absent_returns_false(self):
        """前置条件未满足：客户端未创建（目标会话/长连接未就绪）。"""
        sender = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1")
        )

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=None
        ):
            ok = sender.send_to_wecom_aibot("daily report")

        assert ok is False

    def test_push_when_client_not_running_returns_false(self):
        """前置条件未满足：长连接未运行（连接断开/未启动）。"""
        sender = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1")
        )
        client = mock.MagicMock()
        client.is_running = False

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=client
        ):
            ok = sender.send_to_wecom_aibot("daily report")

        assert ok is False
        client.send_to_chat.assert_not_called()

    def test_push_empty_content_is_noop(self):
        sender = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1")
        )

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client"
        ) as m_get:
            ok = sender.send_to_wecom_aibot("   \n  ")

        assert ok is False
        m_get.assert_not_called()

    def test_push_ack_error_reports_failure(self):
        """回执 errcode!=0 / 配额丢弃（r2 send_to_chat 返回 False）→ 渠道报失败。"""
        sender = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1")
        )
        client = _running_client()
        client.send_to_chat.return_value = False

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=client
        ):
            ok = sender.send_to_wecom_aibot("daily report")

        assert ok is False

    def test_push_exception_reports_failure_not_raise(self):
        sender = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1")
        )
        client = _running_client()
        client.send_to_chat.side_effect = RuntimeError("ws gone")

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=client
        ):
            ok = sender.send_to_wecom_aibot("daily report")

        assert ok is False

    def test_push_multi_chatid_failure_is_reported(self):
        sender = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1,c2")
        )
        client = _running_client()
        # c1 成功，c2 失败 -> 整体 False。
        client.send_to_chat.side_effect = [True, False]

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=client
        ):
            ok = sender.send_to_wecom_aibot("daily report")

        assert ok is False
        pushed = [call.args[0] for call in client.send_to_chat.call_args_list]
        assert pushed == ["c1", "c2"]


# ---------------------------------------------------------------------------
# Push channel sender — success path & frame shape
# ---------------------------------------------------------------------------


class TestPushSuccessPath:
    @pytest.fixture(autouse=True)
    def _fresh_shared_limiter(self):
        from src.notification_sender.wecom_aibot_sender import (
            _reset_shared_push_rate_limiter,
        )

        _reset_shared_push_rate_limiter()
        yield
        _reset_shared_push_rate_limiter()

    def test_push_success_sends_content_to_chatid_via_shared_client(self):
        """静态推送复用 r2 的 send_to_chat（共享 handler 双窗口配额 = 真实总量）。"""
        sender = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="user-9")
        )
        client = _running_client()

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=client
        ):
            ok = sender.send_to_wecom_aibot("## 每日报告\n内容")

        assert ok is True
        client.send_to_chat.assert_called_once()
        args, kwargs = client.send_to_chat.call_args
        chat_id, text = args[0], args[1]
        assert chat_id == "user-9"
        assert "每日报告" in text

    def test_push_multiple_chatids_all_succeed(self):
        sender = WecomAibotSender(
            _config(
                wecom_aibot_notify_enabled=True,
                wecom_aibot_notify_chatid="c1, c2",
            )
        )
        client = _running_client()

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=client
        ):
            ok = sender.send_to_wecom_aibot("report")

        assert ok is True
        assert client.send_to_chat.call_count == 2

    def test_push_respects_timeout_parameter(self):
        sender = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1")
        )
        client = _running_client()

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=client
        ):
            sender.send_to_wecom_aibot("report", timeout_seconds=3.5)

        args, kwargs = client.send_to_chat.call_args
        assert kwargs.get("timeout_seconds") == 3.5


# ---------------------------------------------------------------------------
# Push rate limiting: 30/min, 1000/hour, 3 concurrent per chat
# ---------------------------------------------------------------------------


class TestPushRateLimiting:
    @pytest.fixture(autouse=True)
    def _fresh_shared_limiter(self):
        from src.notification_sender.wecom_aibot_sender import (
            _reset_shared_push_rate_limiter,
        )

        _reset_shared_push_rate_limiter()
        yield
        _reset_shared_push_rate_limiter()

    def test_31st_push_in_one_minute_is_rejected(self):
        sender = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1")
        )
        client = _running_client()

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=client
        ):
            results = [sender.send_to_wecom_aibot(f"msg-{i}") for i in range(31)]

        assert all(results[:30])
        assert results[30] is False
        assert client.send_to_chat.call_count == 30

    def test_rate_limit_is_per_chat(self):
        """分钟预算按会话隔离（r4 起 limiter 仅双窗口；并发下沉共享闸）。"""
        limiter = AibotPushRateLimiter()
        for _ in range(30):
            assert limiter.acquire("c1") is not None
        # c1 分钟预算耗尽
        assert limiter.acquire("c1") is None
        # c2 有独立预算
        assert limiter.acquire("c2") is not None

    def test_hour_limit_1000_rejects_1001st(self):
        # 分钟预算调大以隔离小时口径
        limiter = AibotPushRateLimiter(max_per_minute=2000, max_per_hour=1000)
        for _ in range(1000):
            assert limiter.acquire("c1") is not None
        assert limiter.acquire("c1") is None

    # 并发上限（同会话 ≤3）自 r4 起由传输层共享闸统一执行，覆盖回复、
    # 回推与静态推送三路合计——语义迁移测试见
    # tests/test_wecom_aibot_outbound_gate.py（TestOutboundGate /
    # TestSendToChatGating / TestReplyPathGating / TestMixedPathAccounting）。

    def test_push_rate_budget_shared_across_sender_instances(self):
        """(e) OR-COR-4c720f93：同一机器人/会话的推送预算跨发送器实例共享。

        所有 WecomAibotSender 共用全局长连接客户端，限流预算不得随
        NotificationService/Pipeline 实例重建而重置。
        """
        s1 = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1")
        )
        s2 = WecomAibotSender(
            _config(wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1")
        )
        client = _running_client()

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client", return_value=client
        ):
            for _ in range(30):
                assert s1.send_to_wecom_aibot("s1")
            # s2 不得获得新预算：第 31 条（总口径）必须被拒。
            assert s2.send_to_wecom_aibot("s2") is False

        assert client.send_to_chat.call_count == 30


class TestNotificationIntegration:
    def test_notification_channel_enum_member_and_name(self):
        from src.notification import ChannelDetector, NotificationChannel

        assert NotificationChannel.WECOM_AIBOT.value == "wecom_aibot"
        assert (
            ChannelDetector.get_channel_name(NotificationChannel.WECOM_AIBOT)
            != "未知渠道"
        )

    def test_sender_is_part_of_notification_service_family(self):
        """与渠道族同接口：NotificationService 继承 WecomAibotSender 并分发。"""
        from src.notification import NotificationService
        from src.notification_sender.wecom_aibot_sender import WecomAibotSender

        assert issubclass(NotificationService, WecomAibotSender)

    def test_static_channel_dispatch_routes_to_aibot_sender(self):
        from src.notification import NotificationChannel, NotificationService

        service = NotificationService.__new__(NotificationService)
        service._config = _config(
            wecom_aibot_notify_enabled=True, wecom_aibot_notify_chatid="c1"
        )
        # __new__ 跳过 __init__；补齐图片路由所需的实例属性
        service._markdown_to_image_channels = set()
        service.send_to_wecom_aibot = mock.MagicMock(return_value=True)

        ok = service._send_to_static_channel(
            NotificationChannel.WECOM_AIBOT,
            "content",
            image_bytes=None,
            email_stock_codes=None,
            email_send_to_all=False,
        )

        assert ok is True
        service.send_to_wecom_aibot.assert_called_once_with("content")


# ---------------------------------------------------------------------------
# Config chain: src/config.py + config_registry + .env.example + settingsHelp
# ---------------------------------------------------------------------------


class TestConfigChainPhase2:
    def test_config_dataclass_defaults_off(self):
        config = _config()
        assert config.wecom_aibot_notify_enabled is False
        assert config.wecom_aibot_notify_chatid is None

    def test_config_from_env(self, monkeypatch):
        from src.config import Config

        monkeypatch.setenv("WECOM_AIBOT_NOTIFY_ENABLED", "true")
        monkeypatch.setenv("WECOM_AIBOT_NOTIFY_CHATID", "chat-a,chat-b")

        config = Config._load_from_env()
        assert config.wecom_aibot_notify_enabled is True
        assert config.wecom_aibot_notify_chatid == "chat-a,chat-b"

    def test_registry_metadata_complete(self):
        from src.core.config_registry import get_field_definition

        for key in WECOM_AIBOT_NOTIFY_KEYS:
            field = get_field_definition(key)
            assert field["category"] == "notification", key
            assert field["help_key"] == f"settings.notification.{key}", key
            assert field["examples"], f"{key} missing examples"
            assert field["docs"], f"{key} missing docs"
            assert field["default_value"] in (None, "false"), key

    def test_env_example_keys_are_registered(self):
        from src.core.config_registry import (
            WEB_SETTINGS_HIDDEN_FROM_UI,
            get_registered_field_keys,
        )

        env_example = (
            Path(__file__).resolve().parents[1] / ".env.example"
        )
        active = {
            m.group(1)
            for line in env_example.read_text(encoding="utf-8").splitlines()
            for m in [re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip())]
            if m
        }
        wecom_active = {k for k in active if k.startswith("WECOM_AIBOT_")}
        assert wecom_active == set(WECOM_AIBOT_ALL_KEYS)
        registered = set(get_registered_field_keys())
        assert wecom_active - registered - WEB_SETTINGS_HIDDEN_FROM_UI == set()

    def test_settings_help_locales_cover_help_keys(self):
        help_file = (
            Path(__file__).resolve().parents[1]
            / "apps/dsa-web/src/locales/settingsHelp.ts"
        )
        content = help_file.read_text(encoding="utf-8")
        locale_keys = set(
            re.findall(r"^\s*'([^']+)'\s*:\s*\{", content, flags=re.MULTILINE)
        )
        for key in WECOM_AIBOT_NOTIFY_KEYS:
            assert (
                f"settings.notification.{key}" in locale_keys
            ), f"settings.notification.{key} missing in settingsHelp.ts"

    def test_channel_registered_in_diagnostics_specs(self):
        from src.notification import NotificationChannel
        from src.services.notification_diagnostics import CHANNEL_SPECS

        spec_channels = {spec.channel for spec in CHANNEL_SPECS}
        assert NotificationChannel.WECOM_AIBOT.value in spec_channels

    def test_channel_is_routable(self):
        from src.notification_routing import ROUTABLE_NOTIFICATION_CHANNEL_SET

        assert "wecom_aibot" in ROUTABLE_NOTIFICATION_CHANNEL_SET

    def test_notification_test_target_keys_cover_aibot(self):
        from src.services.system_config_service import SystemConfigService

        keys = SystemConfigService._NOTIFICATION_TEST_TARGET_KEYS.get("wecom_aibot")
        assert keys == ("WECOM_AIBOT_NOTIFY_CHATID",)


# ---------------------------------------------------------------------------
# (d) r2: settings-page "test notification" button must pass the real config
#     through to the aibot channel (review OR-COR-429107a0 / OR-COR-c10b8a42)
# ---------------------------------------------------------------------------


class TestSettingsTestButtonConfigParity:
    def _service(self):
        from src.services.system_config_service import SystemConfigService

        return SystemConfigService()

    def test_test_button_passes_enabled_and_chatid_to_sender(self):
        """提供真实配置时，测试入口必须以 enabled=True + chatid 构造发送器并探测。"""
        service = self._service()
        constructed_configs = []

        class _SpySender:
            def __init__(self, config):
                constructed_configs.append(config)

            def send_to_wecom_aibot(self, content, *, timeout_seconds=None):
                return True

        with mock.patch(
            "src.notification_sender.WecomAibotSender", _SpySender
        ):
            result = service.test_notification_channel(
                channel="wecom_aibot",
                items=[
                    {"key": "WECOM_AIBOT_NOTIFY_ENABLED", "value": "true"},
                    {"key": "WECOM_AIBOT_NOTIFY_CHATID", "value": "chat-9"},
                ],
            )

        assert result["success"] is True, result
        assert len(constructed_configs) == 1
        assert constructed_configs[0].wecom_aibot_notify_enabled is True
        assert constructed_configs[0].wecom_aibot_notify_chatid == "chat-9"

    def test_test_button_reports_missing_chatid_config(self):
        """缺 CHATID 时必须报 config_missing 且点名缺失键（必填组注册）。"""
        service = self._service()

        result = service.test_notification_channel(
            channel="wecom_aibot",
            items=[{"key": "WECOM_AIBOT_NOTIFY_ENABLED", "value": "true"}],
        )

        assert result["success"] is False
        assert result.get("error_code") == "config_missing"
        assert "WECOM_AIBOT_NOTIFY_CHATID" in (result.get("message") or "")


if __name__ == "__main__":
    pytest.main([__file__])
