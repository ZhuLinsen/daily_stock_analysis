# -*- coding: utf-8 -*-
"""
Aggregate pipeline routing regression for the WeCom AI Bot push channel
(Issue #755 Phase 2 r3, review OR-COR-ceb15d97).

`StockAnalysisPipeline._send_notifications` (the aggregate dispatch chain used
when SINGLE_STOCK_NOTIFY=false) must actually deliver to the WECOM_AIBOT
channel — previously it only existed in `NotificationService
._send_to_static_channel`, so the aggregate chain fell through to the
"未知通知渠道" warning and never called `WecomAibotSender`.

Tests drive the REAL pipeline dispatch chain (`_send_notifications`) with a
fake notifier that mixes in the REAL `WecomAibotSender` (chatid parsing,
shared rate limiter, `send_to_chat` delegation all real), asserting the
target chatid reaches `WecomAibotClient.send_to_chat`, and that a raising
aibot send does not affect other channels.
"""

import os
import sys
from types import SimpleNamespace
from unittest import mock
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.core.pipeline import StockAnalysisPipeline, NotificationChannel
from src.enums import ReportType
from src.notification_sender.wecom_aibot_sender import (
    WecomAibotSender,
    _reset_shared_push_rate_limiter,
)


class _FakeNotifierWithAibot(WecomAibotSender):
    """Notification surface mixing in the REAL aibot sender.

    Everything the pipeline touches is mocked except the aibot send path,
    which stays real (config parsing, shared limiter, send_to_chat
    delegation) so the assertion covers the actual chatid on the wire.
    """

    def __init__(self, channels, aibot_raise: bool = False):
        WecomAibotSender.__init__(
            self,
            SimpleNamespace(
                wecom_aibot_notify_enabled=True,
                wecom_aibot_notify_chatid="chat-aibot-1",
            ),
        )
        self._markdown_to_image_channels = set()
        self._markdown_to_image_max_chars = 15000
        self.is_available = MagicMock(return_value=True)
        self.get_available_channels = MagicMock(return_value=list(channels))
        self.get_channels_for_route = MagicMock(
            side_effect=lambda route_type, channels=None: list(
                channels if channels is not None else self.get_available_channels()
            )
        )
        self.send_to_context = MagicMock(return_value=False)
        self._should_use_image_for_channel = MagicMock(return_value=False)
        self.generate_dashboard_report = MagicMock(
            side_effect=lambda results: "report:" + ",".join(
                r.code for r in results
            )
        )
        self.send_to_astrbot = MagicMock(return_value=True)
        if aibot_raise:
            self.send_to_wecom_aibot = MagicMock(
                side_effect=RuntimeError("aibot push exploded")
            )
        else:
            self.send_to_wecom_aibot = MagicMock(
                side_effect=lambda content, **kwargs: WecomAibotSender
                .send_to_wecom_aibot(self, content, **kwargs)
            )


def _build_pipeline(notifier) -> StockAnalysisPipeline:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.notifier = notifier
    pipeline.config = SimpleNamespace(stock_email_groups=[])
    return pipeline


def _make_results():
    return [SimpleNamespace(code="000001"), SimpleNamespace(code="600519")]


@pytest.fixture(autouse=True)
def _fresh_shared_limiter():
    _reset_shared_push_rate_limiter()
    yield
    _reset_shared_push_rate_limiter()


def _running_client():
    client = MagicMock()
    client.is_running = True
    client.send_to_chat = MagicMock(return_value=True)
    return client


class TestAggregatePipelineWecomAibotRouting:
    def test_aggregate_chain_delivers_to_aibot_chatid(self):
        """RED(OR-COR-ceb15d97)：聚合分发链必须实际调用 aibot 渠道并投递到目标 chatid。"""
        notifier = _FakeNotifierWithAibot(
            channels=[NotificationChannel.ASTRBOT, NotificationChannel.WECOM_AIBOT]
        )
        pipeline = _build_pipeline(notifier)
        client = _running_client()

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client",
            return_value=client,
        ):
            pipeline._send_notifications(_make_results(), ReportType.SIMPLE)

        # aibot 渠道被分发（不再落入"未知通知渠道"分支）
        notifier.send_to_wecom_aibot.assert_called_once()
        # 目标 chatid 正确：真实 sender → client.send_to_chat
        client.send_to_chat.assert_called_once()
        chat_id, text = client.send_to_chat.call_args.args[0], client.send_to_chat.call_args.args[1]
        assert chat_id == "chat-aibot-1"
        assert "report:000001,600519" in text
        # 其它渠道不受影响
        notifier.send_to_astrbot.assert_called_once()

    def test_aibot_send_failure_does_not_block_other_channels(self):
        """失败路径：aibot 投递抛异常 → 其它渠道照常发送。"""
        notifier = _FakeNotifierWithAibot(
            channels=[NotificationChannel.ASTRBOT, NotificationChannel.WECOM_AIBOT],
            aibot_raise=True,
        )
        pipeline = _build_pipeline(notifier)
        client = _running_client()

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client",
            return_value=client,
        ):
            # 不应向外抛出（_send_channel_safely 兜底）
            pipeline._send_notifications(_make_results(), ReportType.SIMPLE)

        notifier.send_to_wecom_aibot.assert_called_once()
        # 其它渠道照常完成
        notifier.send_to_astrbot.assert_called_once()
        assert notifier.send_to_astrbot.return_value is True
        # aibot 异常时不触碰底层连接
        client.send_to_chat.assert_not_called()

    def test_aibot_channel_disabled_when_sender_reports_unavailable(self):
        """失败降级：客户端离线且惰性启动被拒（sender 降级 False，r7 惰性
        启动语义）→ 记录失败且不影响其它渠道。"""
        notifier = _FakeNotifierWithAibot(
            channels=[NotificationChannel.ASTRBOT, NotificationChannel.WECOM_AIBOT]
        )
        pipeline = _build_pipeline(notifier)
        client = MagicMock()
        client.is_running = False
        client.start_background = MagicMock(return_value=False)  # 惰性启动被拒

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client",
            return_value=client,
        ):
            pipeline._send_notifications(_make_results(), ReportType.SIMPLE)

        notifier.send_to_wecom_aibot.assert_called_once()
        notifier.send_to_astrbot.assert_called_once()
        client.send_to_chat.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])
