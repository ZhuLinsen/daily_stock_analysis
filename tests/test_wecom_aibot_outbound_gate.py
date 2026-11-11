# -*- coding: utf-8 -*-
"""
Shared per-chat outbound concurrency gate for the WeCom AI Bot (Issue #755
r4, review OR-COR-f5a96c8b).

Official cap: at most 3 concurrent in-flight messages per chat. Before r4 the
cap was only enforced inside the static push sender's local limiter — passive
replies (aibot_respond_msg) and source-conversation pushes (send_to_chat)
bypassed it entirely, so reply + context-push + static-push combined could
exceed 3 concurrent in-flight messages on the same chat.

Contract:
- The gate is a transport-layer singleton shared by ALL three outbound paths:
  passive replies (`WecomAibotHandler._reply_to_frame`), source-conversation
  pushes and the aggregate/static push (both via `WecomAibotClient
  .send_to_chat`).
- Rejection semantics match quota rejection: acquire failure → send refused
  with a warning log, zero accounting (dual-window quota untouched), other
  channels unaffected.
- A gate slot is released when its send completes (ack received, success or
  failure) — release is idempotent.
"""

import asyncio
import os
import sys
import threading
import time
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bot.platforms.wecom_aibot as wecom_aibot
from bot.platforms.wecom_aibot import (
    WecomAibotHandler,
    WecomAibotOutboundGate,
    _WECOM_AIBOT_OUTBOUND_GATE,
)


def _ack_coro():
    return asyncio.sleep(0, result={"errcode": 0})


def _real_send_client():
    """Client assembled for real send_to_chat execution (running loop)."""
    client = wecom_aibot.WecomAibotClient.__new__(wecom_aibot.WecomAibotClient)
    client._running = True
    client._loop = asyncio.new_event_loop()
    client._sdk_client = mock.MagicMock()
    client._sdk_client.send_message = mock.MagicMock(
        side_effect=lambda chatid, body: _ack_coro()
    )
    client._handler = WecomAibotHandler()
    thread = threading.Thread(target=client._loop.run_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    def _shutdown():
        client._loop.call_soon_threadsafe(client._loop.stop)
        thread.join(timeout=2)
        client._loop.close()

    return client, _shutdown


def _reply_frame(chat_id="c1"):
    return {
        "headers": {"req_id": "req-1"},
        "body": {"chatid": chat_id, "from": {"userid": chat_id}},
    }


@pytest.fixture(autouse=True)
def _fresh_gate():
    wecom_aibot._reset_outbound_gate()
    yield
    wecom_aibot._reset_outbound_gate()


class TestOutboundGate:
    def test_gate_rejects_fourth_concurrent_same_chat(self):
        gate = WecomAibotOutboundGate(max_concurrent_per_chat=3)
        slots = [gate.try_acquire("c1") for _ in range(3)]
        assert all(slot is not None for slot in slots)
        assert gate.try_acquire("c1") is None
        slots[0].release()
        assert gate.try_acquire("c1") is not None

    def test_gate_release_is_idempotent(self):
        gate = WecomAibotOutboundGate()
        slot = gate.try_acquire("c1")
        slot.release()
        slot.release()
        assert gate.try_acquire("c1") is not None

    def test_gate_is_per_chat(self):
        gate = WecomAibotOutboundGate()
        held = [gate.try_acquire("c1") for _ in range(3)]
        assert all(slot is not None for slot in held)
        # c1 满，c2 不受影响
        assert gate.try_acquire("c2") is not None

    def test_module_singleton_shared_cap_three(self):
        assert _WECOM_AIBOT_OUTBOUND_GATE.try_acquire("c1") is not None
        assert _WECOM_AIBOT_OUTBOUND_GATE.try_acquire("c1") is not None
        assert _WECOM_AIBOT_OUTBOUND_GATE.try_acquire("c1") is not None
        assert _WECOM_AIBOT_OUTBOUND_GATE.try_acquire("c1") is None


class TestSendToChatGating:
    def test_send_to_chat_rejected_when_gate_full(self):
        """RED(OR-COR-f5a96c8b)：闸满时 send_to_chat 拒绝且双窗口零记账。"""
        client, shutdown = _real_send_client()
        try:
            slots = [
                _WECOM_AIBOT_OUTBOUND_GATE.try_acquire("c1") for _ in range(3)
            ]
            assert all(slot is not None for slot in slots)

            assert client.send_to_chat("c1", "hello") is False
            client._sdk_client.send_message.assert_not_called()
            # 拒绝零记账：双窗口额度完整
            assert (
                client._handler._outbound_minute_limiter.get_remaining("c1") == 30
            )
            assert (
                client._handler._outbound_hour_limiter.get_remaining("c1") == 1000
            )

            slots[0].release()
            assert client.send_to_chat("c1", "hello") is True
            client._sdk_client.send_message.assert_called_once()
        finally:
            shutdown()

    def test_send_to_chat_releases_gate_slot_after_completion(self):
        client, shutdown = _real_send_client()
        try:
            assert client.send_to_chat("c1", "hello") is True
            # 发送完成后闸槽已释放
            assert _WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1") == 0
            # 失败路径同样释放：ack errcode != 0
            client._sdk_client.send_message = mock.MagicMock(
                side_effect=lambda chatid, body: asyncio.sleep(
                    0, result={"errcode": 90001, "errmsg": "no session"}
                )
            )
            assert client.send_to_chat("c1", "hello") is False
            assert _WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1") == 0
        finally:
            shutdown()


class TestReplyPathGating:
    def test_reply_rejected_when_gate_full(self):
        """RED(OR-COR-f5a96c8b)：被动回复路径统一经共享闸。"""
        handler = WecomAibotHandler()
        handler._loop = mock.MagicMock()
        handler._loop.is_closed.return_value = False
        handler.sdk_client = mock.MagicMock()

        slots = [
            _WECOM_AIBOT_OUTBOUND_GATE.try_acquire("c1") for _ in range(3)
        ]
        assert all(slot is not None for slot in slots)

        assert handler._reply_to_frame(_reply_frame("c1"), "hello") is False
        handler.sdk_client.reply.assert_not_called()
        # 拒绝零记账（配额已退还）
        assert handler._outbound_minute_limiter.get_remaining("c1") == 30

        slots[0].release()
        fake_future = mock.MagicMock()
        with mock.patch.object(handler, "_schedule_reply", return_value=fake_future) as m_sched:
            assert handler._reply_to_frame(_reply_frame("c1"), "hello") is True
        # 调度后的协程不再需要（future 为 mock，未真正运行）
        for call in m_sched.call_args_list:
            call.args[0].close()

    def test_reply_gate_slot_released_after_send_completes(self):
        handler = WecomAibotHandler()
        client = wecom_aibot.WecomAibotClient.__new__(wecom_aibot.WecomAibotClient)
        client._running = True
        client._loop = asyncio.new_event_loop()
        client._sdk_client = mock.MagicMock()
        handler._loop = client._loop
        handler.sdk_client = client._sdk_client
        ack_ready = asyncio.Event()

        async def _held_ack():
            await ack_ready.wait()
            return {"errcode": 0}

        client._sdk_client.reply = mock.MagicMock(
            side_effect=lambda frame, body: _held_ack()
        )
        thread = threading.Thread(target=client._loop.run_forever, daemon=True)
        thread.start()
        try:
            time.sleep(0.1)
            assert handler._reply_to_frame(_reply_frame("c1"), "hello") is True
            # 回执未到：在途槽位被持有
            assert _WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1") == 1
            client._loop.call_soon_threadsafe(ack_ready.set)
            deadline = time.time() + 2
            while _WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1") > 0:
                if time.time() > deadline:
                    break
                time.sleep(0.05)
            # 回执到达（成败皆然）：槽位已释放
            assert _WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1") == 0
        finally:
            client._loop.call_soon_threadsafe(client._loop.stop)
            thread.join(timeout=2)
            client._loop.close()


class TestMixedPathAccounting:
    def test_reply_and_context_and_static_count_together(self):
        """RED(OR-COR-f5a96c8b)：回复 + 回推 + 静态推送在共享闸合计 ≤3。"""
        client, shutdown = _real_send_client()
        ack_ready = asyncio.Event()

        async def _held_ack():
            await ack_ready.wait()
            return {"errcode": 0}

        client._sdk_client.send_message = mock.MagicMock(
            side_effect=lambda chatid, body: _held_ack()
        )
        try:
            # 1 条 in-flight 被动回复 + 1 条 in-flight 来源会话回推（持槽模拟）
            reply_slot = _WECOM_AIBOT_OUTBOUND_GATE.try_acquire("c1")
            context_slot = _WECOM_AIBOT_OUTBOUND_GATE.try_acquire("c1")
            assert reply_slot is not None and context_slot is not None

            # 第 3 个并发位：静态推送在途（ack 阻塞，后台线程发送）
            result = {}

            def _bg():
                result["m1"] = client.send_to_chat("c1", "m1")

            t = threading.Thread(target=_bg, daemon=True)
            t.start()
            deadline = time.time() + 2
            while _WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1") < 3:
                if time.time() > deadline:
                    break
                time.sleep(0.02)
            assert _WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1") == 3

            # 第 4 个：拒绝（零记账）
            assert client.send_to_chat("c1", "m2") is False

            # 放行被阻塞的回执 → 在途回落
            client._loop.call_soon_threadsafe(ack_ready.set)
            t.join(timeout=3)
            assert result["m1"] is True
            assert _WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1") == 2

            reply_slot.release()
            context_slot.release()
            assert _WECOM_AIBOT_OUTBOUND_GATE.in_flight("c1") == 0
        finally:
            shutdown()


class TestStaticSenderWindowLimiterMigrated:
    """AibotPushRateLimiter 语义迁移：仅双窗口（并发计数下沉共享闸）。"""

    def test_push_limiter_is_windows_only(self):
        from src.notification_sender.wecom_aibot_sender import AibotPushRateLimiter

        limiter = AibotPushRateLimiter()
        for _ in range(30):
            assert limiter.acquire("c1") is not None
        # 分钟窗耗尽（无并发槽参与——旧实现此处会被并发上限提前拦截）
        assert limiter.acquire("c1") is None

    def test_sender_static_push_still_rejected_on_full_gate(self):
        """静态推送经 send_to_chat 的共享闸：闸满 → 渠道失败、SDK 零调用。"""
        from src.notification_sender.wecom_aibot_sender import WecomAibotSender
        from src.config import Config

        sender = WecomAibotSender(
            Config(
                stock_list=[],
                wecom_aibot_notify_enabled=True,
                wecom_aibot_notify_chatid="c1",
            )
        )
        client, shutdown = _real_send_client()
        try:
            slots = [
                _WECOM_AIBOT_OUTBOUND_GATE.try_acquire("c1") for _ in range(3)
            ]
            with mock.patch(
                "bot.platforms.wecom_aibot.get_wecom_aibot_client",
                return_value=client,
            ):
                assert sender.send_to_wecom_aibot("daily report") is False
            client._sdk_client.send_message.assert_not_called()
            slots[0].release()
            with mock.patch(
                "bot.platforms.wecom_aibot.get_wecom_aibot_client",
                return_value=client,
            ):
                assert sender.send_to_wecom_aibot("daily report") is True
        finally:
            shutdown()


if __name__ == "__main__":
    pytest.main([__file__])
