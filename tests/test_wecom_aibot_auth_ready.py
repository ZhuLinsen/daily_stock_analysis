# -*- coding: utf-8 -*-
"""
Auth-state readiness for the WeCom AI Bot connection (Issue #755 r8, review
OR-COR-36f9842a).

The connect flow is: TCP open → send the auth frame → async auth ack (SDK
`authenticated` event). `wait_for_ready` previously only checked
`_running && sdk_client.is_connected` (raw WebSocket open) — the client never
saved/waited the authenticated state, so during the TCP-connected-but-auth-
pending window (and reconnect/re-auth windows) readiness was reported too
early: the first `send_to_chat` of a lazy-started one-shot CLI task was
rejected pre-auth and the whole report was lost.

Contract (r8):
- The client tracks auth state with `_authenticated_event` (a threading.Event):
  set by `_on_authenticated` (SDK `authenticated` event), cleared when a new
  connection cycle is built and on disconnect (re-auth pending again).
- `wait_for_ready` / `is_transport_ready` require `_running && is_connected
  && authenticated_event.is_set()`.
- Send paths (`send_to_chat`, passive replies via the wired handler event)
  are gated on the same state: reject with zero accounting until
  authenticated.
- Standalone handlers without a wired event keep the legacy no-gate behavior
  (unit-test harness compatibility).
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
from bot.platforms.wecom_aibot import WecomAibotClient, WecomAibotHandler


def _auth_test_client(authenticated=False):
    """Client assembled via __new__ with an explicit auth event wired into
    the handler (mirrors the __init__ wiring added in r8)."""
    client = WecomAibotClient.__new__(WecomAibotClient)
    client._running = True
    client._stop_event = threading.Event()
    client._loop = None
    client._sdk_client = mock.MagicMock()
    client._sdk_client.is_connected = True
    client._sdk_client.send_message = mock.MagicMock(
        side_effect=lambda chatid, body: asyncio.sleep(0, result={"errcode": 0})
    )
    client._authenticated_event = threading.Event()
    if authenticated:
        client._authenticated_event.set()
    client._handler = WecomAibotHandler()
    client._handler._authenticated_event = client._authenticated_event
    client._handler.sdk_client = client._sdk_client
    return client


def _reply_frame(chat_id="c1"):
    return {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-1"},
        "body": {"chatid": chat_id, "from": {"userid": chat_id}},
    }


@pytest.fixture(autouse=True)
def _fresh_gate():
    wecom_aibot._reset_outbound_gate()
    yield
    wecom_aibot._reset_outbound_gate()


class TestAuthReadiness:
    def test_wait_for_ready_blocks_until_authenticated(self):
        """RED(OR-COR-36f9842a)：TCP 已连、认证事件未置 → 不得就绪。"""
        client = _auth_test_client(authenticated=False)
        assert client.wait_for_ready(0.4) is False

    def test_wait_for_ready_ready_after_auth_event_set(self):
        client = _auth_test_client(authenticated=False)
        client._on_authenticated()
        assert client._authenticated_event.is_set()
        assert client.wait_for_ready(2.0) is True

    def test_disconnect_clears_auth_and_blocks_again(self):
        client = _auth_test_client(authenticated=False)
        client._on_authenticated()
        assert client.wait_for_ready(1.0) is True
        # 重连周期/断线：清认证 → 又不就绪（重认证完成前发送被闸）
        client._authenticated_event.clear()
        assert client.wait_for_ready(0.4) is False

    def test_is_transport_ready_requires_auth(self):
        client = _auth_test_client(authenticated=False)
        assert client.is_transport_ready() is False
        client._on_authenticated()
        assert client.is_transport_ready() is True


class TestSendPathsGatedByAuth:
    def test_send_to_chat_rejected_before_auth_and_allowed_after(self):
        """RED(OR-COR-36f9842a)：认证未回时 send_to_chat 拒发（零记账）；
        认证完成后放行。一次性 CLI 任务不再丢整份报告。"""
        client = _auth_test_client(authenticated=False)
        client._loop = asyncio.new_event_loop()
        thread = threading.Thread(target=client._loop.run_forever, daemon=True)
        thread.start()
        try:
            time.sleep(0.1)
            assert client.send_to_chat("c1", "hello") is False
            client._sdk_client.send_message.assert_not_called()
            # 拒绝零记账：双窗口额度完整
            assert (
                client._handler._outbound_minute_limiter.get_remaining("c1") == 30
            )

            client._on_authenticated()
            assert client.send_to_chat("c1", "hello") is True
            client._sdk_client.send_message.assert_called_once()
        finally:
            client._loop.call_soon_threadsafe(client._loop.stop)
            thread.join(timeout=2)
            client._loop.close()

    def test_reply_rejected_before_auth_with_quota_refund(self):
        handler = WecomAibotHandler()
        handler._authenticated_event = threading.Event()  # wired, unset
        handler._loop = mock.MagicMock()
        handler._loop.is_closed.return_value = False
        handler.sdk_client = mock.MagicMock()

        assert handler._reply_to_frame(_reply_frame("c1"), "hi") is False
        handler.sdk_client.reply.assert_not_called()
        # 拒绝零记账（配额已退还）
        assert handler._outbound_minute_limiter.get_remaining("c1") == 30

        handler._authenticated_event.set()
        fake_future = mock.MagicMock()
        with mock.patch.object(handler, "_schedule_reply", return_value=fake_future) as m_sched:
            assert handler._reply_to_frame(_reply_frame("c1"), "hi") is True
        for call in m_sched.call_args_list:
            call.args[0].close()

    def test_unwired_handler_keeps_legacy_no_gate(self):
        """未接线的独立 handler（单元测试 harness）保持无闸行为。"""
        handler = WecomAibotHandler()
        assert getattr(handler, "_authenticated_event", None) is None
        handler._loop = mock.MagicMock()
        handler._loop.is_closed.return_value = False
        handler.sdk_client = mock.MagicMock()

        fake_future = mock.MagicMock()
        with mock.patch.object(handler, "_schedule_reply", return_value=fake_future):
            assert handler._reply_to_frame(_reply_frame("c1"), "hi") is True


if __name__ == "__main__":
    pytest.main([__file__])
