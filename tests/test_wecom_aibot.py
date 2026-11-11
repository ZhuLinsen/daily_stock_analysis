# -*- coding: utf-8 -*-
"""
Unit tests for the WeCom AI Bot (企业微信智能机器人) WebSocket long-connection
adapter (bot/platforms/wecom_aibot.py), Issue #755 Phase 1.

Coverage matrix (per plan 默认值 3 / Wave 2 任务 7):
- SDK-missing degradation: module imports, WECOM_AIBOT_SDK_AVAILABLE=False,
  graceful refusal on start (install hint logged).
- Config gating: disabled / missing credentials -> no client, zero side effects.
- Auth failure degradation: subscribe errcode!=0 -> no crash, exponential
  backoff, give-up after max attempts; non-auth errors do not consume budget.
- Single-connection mutex: start_background twice never spawns a second thread.
- msgid dedup: duplicate callback frames are dropped.
- Conversation rate limiting: reuses dispatcher RateLimiter at 30/min.
- Text frame -> BotMessage -> dispatcher -> AnalyzeCommand mapping round trip,
  reply via aibot_respond_msg with callback req_id passthrough.
- reply_stream opt-in (default off).
- Config chain: src/config.py keys, config_registry metadata (help_key /
  examples / docs), .env.example contract.

The local venv intentionally does NOT install wecom-aibot-python-sdk (shared
uv-managed venv). SDK-present paths are guarded with skipif so CI (which
installs requirements.txt) covers them.
"""

import asyncio
import os
import sys
import unittest
from unittest import mock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bot.platforms.wecom_aibot as wecom_aibot
from bot.models import BotResponse, ChatType

SDK_PRESENT = bool(getattr(wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", False))

WECOM_AIBOT_KEYS = (
    "WECOM_AIBOT_ENABLED",
    "WECOM_AIBOT_BOT_ID",
    "WECOM_AIBOT_SECRET",
    "WECOM_AIBOT_REPLY_STREAM",
    # Phase 2 (issue #755): notification push channel via aibot_send_msg
    "WECOM_AIBOT_NOTIFY_ENABLED",
    "WECOM_AIBOT_NOTIFY_CHATID",
)


def _text_frame(
    msgid="msg-1",
    content="分析 600519",
    userid="encrypted-userid",
    chatid=None,
    chattype="single",
    req_id="aibot_msg_callback_1700000000_abcdef",
):
    """Build an aibot_msg_callback text frame per the official wire format."""
    body = {
        "msgtype": "text",
        "msgid": msgid,
        "aibotid": "bot-abc",
        "chattype": chattype,
        "text": {"content": content},
        "from": {"userid": userid},
    }
    if chatid is not None:
        body["chatid"] = chatid
    return {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": req_id},
        "body": body,
    }


def _handler(**kwargs):
    """Build a handler with a mocked SDK client (no real SDK needed)."""
    sdk_client = mock.MagicMock()
    defaults = dict(
        sdk_client=sdk_client,
        reply_stream_enabled=False,
    )
    defaults.update(kwargs)
    return wecom_aibot.WecomAibotHandler(**defaults), sdk_client


# ---------------------------------------------------------------------------
# SDK-missing degradation (runs where the SDK is NOT installed; skipped in CI)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    wecom_aibot.WECOM_AIBOT_SDK_AVAILABLE,
    reason="wecom-aibot-python-sdk installed; SDK-missing path not applicable",
)
class TestSdkMissingDegradation:
    def test_module_imports_and_flags_unavailable(self):
        assert wecom_aibot.WECOM_AIBOT_SDK_AVAILABLE is False

    def test_platforms_package_exports_flag_even_without_sdk(self):
        import bot.platforms as platforms

        assert platforms.WECOM_AIBOT_SDK_AVAILABLE is False
        assert callable(platforms.start_wecom_aibot_background)

    def test_enabled_without_sdk_refuses_gracefully(self, caplog):
        with mock.patch.object(wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", False):
            with mock.patch.object(
                wecom_aibot, "get_config", return_value=mock.MagicMock()
            ):
                started = wecom_aibot.start_wecom_aibot_background()

        assert started is False
        assert "pip install wecom-aibot-python-sdk" in caplog.text


# ---------------------------------------------------------------------------
# SDK-present sanity (runs in CI where requirements.txt installs the SDK)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not SDK_PRESENT,
    reason="wecom-aibot-python-sdk not installed in local venv",
)
class TestSdkPresentSanity:
    def test_client_options_protocol_defaults(self):
        from aibot import WSClientOptions

        options = WSClientOptions(bot_id="b", secret="s")
        assert options.heartbeat_interval == 30000
        assert options.reconnect_interval == 1000
        assert options.max_reconnect_attempts == 10


# ---------------------------------------------------------------------------
# Config gating: unconfigured -> client never starts, zero side effects
# ---------------------------------------------------------------------------


class TestUnconfiguredZeroSideEffects:
    def _config(self, **overrides):
        base = dict(
            wecom_aibot_enabled=False,
            wecom_aibot_bot_id=None,
            wecom_aibot_secret=None,
            wecom_aibot_reply_stream=False,
        )
        base.update(overrides)
        return mock.MagicMock(**base)

    def test_disabled_config_creates_no_client(self, caplog):
        with mock.patch.object(wecom_aibot, "get_config", return_value=self._config()), \
                mock.patch.object(wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch.object(wecom_aibot, "aibot", create=True) as aibot:
            wecom_aibot._reset_wecom_aibot_client()
            client = wecom_aibot.get_wecom_aibot_client()

            assert client is None
            aibot.WSClient.assert_not_called()
        wecom_aibot._reset_wecom_aibot_client()

    def test_enabled_without_credentials_raises_value_error(self):
        with mock.patch.object(wecom_aibot, "get_config", return_value=self._config(
            wecom_aibot_enabled=True
        )), mock.patch.object(wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch.object(wecom_aibot, "aibot", create=True):
            with pytest.raises(ValueError):
                wecom_aibot.WecomAibotClient()
        wecom_aibot._reset_wecom_aibot_client()

    def test_get_client_returns_none_when_credentials_missing(self, caplog):
        with mock.patch.object(wecom_aibot, "get_config", return_value=self._config(
            wecom_aibot_enabled=True
        )), mock.patch.object(wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch.object(wecom_aibot, "aibot", create=True) as aibot:
            wecom_aibot._reset_wecom_aibot_client()
            assert wecom_aibot.get_wecom_aibot_client() is None
            aibot.WSClient.assert_not_called()
        wecom_aibot._reset_wecom_aibot_client()

    def test_start_background_disabled_config_is_noop(self, caplog):
        with mock.patch.object(wecom_aibot, "get_config", return_value=self._config()), \
                mock.patch.object(wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch.object(wecom_aibot, "aibot", create=True), \
                mock.patch.object(wecom_aibot.threading, "Thread") as thread_cls:
            started = wecom_aibot.start_wecom_aibot_background()

            assert started is False
            thread_cls.assert_not_called()
        wecom_aibot._reset_wecom_aibot_client()


# ---------------------------------------------------------------------------
# Auth failure degradation (subscribe errcode != 0)
# ---------------------------------------------------------------------------


class TestAuthFailureDegradation:
    def _client(self):
        config = mock.MagicMock(
            wecom_aibot_enabled=True,
            wecom_aibot_bot_id="bot-abc",
            wecom_aibot_secret="secret-xyz",
            wecom_aibot_reply_stream=False,
        )
        with mock.patch.object(wecom_aibot, "get_config", return_value=config), \
                mock.patch.object(wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch.object(wecom_aibot, "aibot", create=True):
            client = wecom_aibot.WecomAibotClient()
        wecom_aibot._reset_wecom_aibot_client()
        return client

    def test_auth_failure_does_not_crash_and_starts_backoff(self, caplog):
        client = self._client()

        # SDK emits Exception("Authentication failed: ... (code: 40001)") when
        # the subscribe frame answers errcode != 0. Must not raise.
        client._handle_auth_error(Exception("Authentication failed: bad secret (code: 40001)"))

        assert client._auth_attempts == 1
        assert client._planned_auth_delay == client._auth_backoff_delay(1)
        assert client._auth_backoff_delay(1) > 0
        assert "重试" in caplog.text or "retry" in caplog.text.lower()

    def test_auth_backoff_is_exponential_with_cap(self):
        client = self._client()

        delays = []
        for _ in range(client._auth_max_attempts):
            delay = client._next_auth_retry_delay()
            assert delay is not None
            delays.append(delay)

        assert delays == sorted(delays)
        assert delays[-1] == client._AUTH_RETRY_MAX_DELAY_SECONDS
        # Exponential growth until the cap.
        assert delays[1] == delays[0] * 2

    def test_auth_gives_up_after_max_attempts(self, caplog):
        client = self._client()

        for _ in range(client._AUTH_RETRY_MAX_ATTEMPTS):
            assert client._next_auth_retry_delay() is not None

        delay = client._next_auth_retry_delay()
        assert delay is None
        client._handle_auth_error(Exception("Authentication failed: again"))
        assert client._running is False
        assert "放弃" in caplog.text or "give up" in caplog.text.lower()

    def test_non_auth_error_does_not_consume_auth_budget(self):
        client = self._client()

        client._handle_auth_error(Exception("WebSocket error: connection reset"))

        assert client._auth_attempts == 0
        assert client._auth_failed is False

    def test_authenticated_event_resets_auth_budget(self):
        client = self._client()

        client._handle_auth_error(Exception("Authentication failed: x"))
        assert client._auth_attempts == 1

        client._on_authenticated()
        assert client._auth_attempts == 0

    def test_auth_failure_stops_event_loop_request(self):
        client = self._client()

        loop = asyncio.new_event_loop()
        try:
            client._loop = loop
            with mock.patch.object(loop, "call_soon_threadsafe") as schedule_stop:
                client._handle_auth_error(Exception("Authentication failed: x"))

            schedule_stop.assert_called_once()
            assert schedule_stop.call_args[0][0] == loop.stop
        finally:
            client._loop = None
            loop.close()


# ---------------------------------------------------------------------------
# Single-connection mutex (reconnect-storm protection)
# ---------------------------------------------------------------------------


class TestSingleConnectionMutex:
    def _client(self):
        config = mock.MagicMock(
            wecom_aibot_enabled=True,
            wecom_aibot_bot_id="bot-abc",
            wecom_aibot_secret="secret-xyz",
            wecom_aibot_reply_stream=False,
        )
        with mock.patch.object(wecom_aibot, "get_config", return_value=config), \
                mock.patch.object(wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch.object(wecom_aibot, "aibot", create=True):
            client = wecom_aibot.WecomAibotClient()
        wecom_aibot._reset_wecom_aibot_client()
        return client

    def test_start_background_twice_never_spawns_second_thread(self, caplog):
        client = self._client()

        alive_thread = mock.MagicMock()
        alive_thread.is_alive.return_value = True
        client._background_thread = alive_thread

        with mock.patch.object(wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch.object(wecom_aibot.threading, "Thread") as thread_cls:
            started = client.start_background()

        assert started is False
        thread_cls.assert_not_called()
        assert "单连接" in caplog.text or "已在运行" in caplog.text

    def test_start_background_creates_exactly_one_thread(self):
        client = self._client()

        with mock.patch.object(wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch.object(wecom_aibot.threading, "Thread") as thread_cls, \
                mock.patch.object(client, "_run_background", lambda: None):
            assert client.start_background() is True
            assert thread_cls.call_count == 1

            # Simulate the thread having exited: a restart is allowed again,
            # but while it is alive the mutex holds.
            assert client.start_background() is False
            assert thread_cls.call_count == 1  # still alive -> no second Thread

    def test_module_singleton_is_single_instance(self):
        config = mock.MagicMock(
            wecom_aibot_enabled=True,
            wecom_aibot_bot_id="bot-abc",
            wecom_aibot_secret="secret-xyz",
            wecom_aibot_reply_stream=False,
        )
        with mock.patch.object(wecom_aibot, "get_config", return_value=config), \
                mock.patch.object(wecom_aibot, "WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch.object(wecom_aibot, "aibot", create=True):
            wecom_aibot._reset_wecom_aibot_client()
            first = wecom_aibot.get_wecom_aibot_client()
            second = wecom_aibot.get_wecom_aibot_client()

            assert first is second
        wecom_aibot._reset_wecom_aibot_client()


# ---------------------------------------------------------------------------
# msgid dedup
# ---------------------------------------------------------------------------


class TestMsgidDedup:
    def test_duplicate_msgid_dropped(self, caplog):
        handler, _ = _handler()
        frame = _text_frame(msgid="dup-1")

        with mock.patch.object(handler, "_enqueue_message") as enqueue:
            handler.handle_frame(frame)
            handler.handle_frame(frame)

        assert enqueue.call_count == 1
        assert "重复" in caplog.text or "duplicate" in caplog.text.lower()

    def test_distinct_msgids_both_processed(self):
        handler, _ = _handler()

        with mock.patch.object(handler, "_enqueue_message") as enqueue:
            handler.handle_frame(_text_frame(msgid="a"))
            handler.handle_frame(_text_frame(msgid="b"))

        assert enqueue.call_count == 2

    def test_dedup_cache_is_bounded(self):
        handler, _ = _handler()

        for i in range(handler._MSGID_CACHE_SIZE + 10):
            handler._is_duplicate_msgid(f"m{i}")

        assert len(handler._seen_msgids) <= handler._MSGID_CACHE_SIZE
        # Oldest entry was evicted: it can be processed again.
        assert handler._is_duplicate_msgid("m0") is False

    def test_missing_msgid_is_not_deduplicated(self):
        handler, _ = _handler()
        frame = _text_frame(msgid="")
        frame["body"].pop("msgid")

        assert handler._is_duplicate_msgid("") is False


# ---------------------------------------------------------------------------
# Conversation rate limiting (30/min, reuses dispatcher RateLimiter)
# ---------------------------------------------------------------------------


class TestConversationRateLimit:
    def test_rate_limiter_is_dispatcher_rate_limiter_at_30_per_minute(self):
        from bot.dispatcher import RateLimiter

        handler, _ = _handler()
        assert isinstance(handler._rate_limiter, RateLimiter)
        assert handler._rate_limiter.max_requests == 30
        assert handler._rate_limiter.window_seconds == 60

    def test_31st_message_in_same_conversation_dropped(self, caplog):
        handler, _ = _handler()
        frames = [_text_frame(msgid=f"m{i}") for i in range(31)]

        with mock.patch.object(handler, "_enqueue_message") as enqueue:
            for frame in frames:
                handler.handle_frame(frame)

        assert enqueue.call_count == 30
        assert "频率" in caplog.text or "rate" in caplog.text.lower()

    def test_rate_limit_is_per_conversation(self):
        handler, _ = _handler()

        for i in range(30):
            assert handler._allow_conversation("chat-a") is True
        assert handler._allow_conversation("chat-a") is False
        # A different conversation is unaffected.
        assert handler._allow_conversation("chat-b") is True


# ---------------------------------------------------------------------------
# Text frame -> BotMessage -> dispatcher -> AnalyzeCommand mapping round trip
# ---------------------------------------------------------------------------


class TestTextMessageRoundTrip:
    def test_parse_frame_maps_to_unified_message(self):
        handler, _ = _handler()
        frame = _text_frame(
            msgid="m-9",
            content="@股票助手 分析 600519",
            userid="enc-user-1",
            chatid="wrk-group-1",
            chattype="group",
        )

        message = handler._parse_frame(frame)

        assert message is not None
        assert message.platform == "wecom"
        assert message.message_id == "m-9"
        assert message.user_id == "enc-user-1"
        assert message.chat_id == "wrk-group-1"
        assert message.chat_type == ChatType.GROUP
        # @机器人 prefix stripped, command resolvable.
        assert message.content == "分析 600519"
        # Callback req_id kept for aibot_respond_msg passthrough.
        assert message.raw_data["_wecom_req_id"] == (
            "aibot_msg_callback_1700000000_abcdef"
        )

    def test_single_chat_uses_userid_as_chat_id(self):
        handler, _ = _handler()
        message = handler._parse_frame(_text_frame(chattype="single"))
        assert message.chat_type == ChatType.PRIVATE
        assert message.chat_id == "encrypted-userid"

    def test_non_text_frame_ignored(self):
        handler, _ = _handler()
        frame = _text_frame()
        frame["body"]["msgtype"] = "image"
        assert handler._parse_frame(frame) is None

    def test_userid_passthrough_no_decryption_attempt(self):
        """Non-superadmin bots receive encrypted from.userid; the adapter must
        pass it through verbatim (documented Phase 1 limitation — conversion
        requires the official self-built-app/robot linking API and is out of
        Phase 1 scope)."""
        handler, _ = _handler()
        message = handler._parse_frame(_text_frame(userid="EncryptedB64Payload=="))
        assert message.user_id == "EncryptedB64Payload=="

    def test_command_mapping_resolves_analyze(self):
        handler, _ = _handler()
        message = handler._parse_frame(_text_frame(content="分析 600519"))
        command, args = message.get_command_and_args("/")
        assert command == "analyze"
        assert args == ["600519"]

    def test_dispatch_and_reply_round_trip(self):
        handler, sdk_client = _handler()
        bot_message = handler._parse_frame(_text_frame(content="/analyze 600519"))

        async def _fake_dispatch(msg):
            assert msg.platform == "wecom"
            assert msg.content == "/analyze 600519"
            return BotResponse.markdown_response("✅ 分析任务已提交")

        dispatcher = mock.MagicMock()
        dispatcher.dispatch_async = _fake_dispatch

        scheduled_coros = []

        def _capture_schedule(coro):
            scheduled_coros.append(coro)

        with mock.patch(
            "bot.dispatcher.get_dispatcher", return_value=dispatcher
        ), mock.patch.object(handler, "_schedule_reply", _capture_schedule):
            handler._process_message(bot_message)

        # One reply coroutine scheduled for the dispatcher response...
        assert len(scheduled_coros) == 1
        scheduled_coros[0].close()

        # ...and the reply path uses aibot_respond_msg with req_id passthrough.
        sdk_client.reply.reset_mock()
        with mock.patch.object(handler, "_schedule_reply", side_effect=lambda coro: coro.close()):
            handler._reply_to_frame(
                {"headers": {"req_id": "req-42"}}, "✅ 分析任务已提交"
            )
        sdk_client.reply.assert_called_once()
        args, kwargs = sdk_client.reply.call_args
        frame_arg, body_arg = args[0], args[1]
        assert frame_arg["headers"]["req_id"] == "req-42"
        assert body_arg["msgtype"] == "markdown"
        assert "分析任务已提交" in body_arg["markdown"]["content"]
        assert kwargs.get("cmd", wecom_aibot.AIBOT_RESPOND_CMD) == wecom_aibot.AIBOT_RESPOND_CMD

    def test_empty_response_not_replied(self):
        handler, sdk_client = _handler()
        bot_message = handler._parse_frame(_text_frame(content="闲聊文本"))

        async def _empty_dispatch(msg):
            return BotResponse.text_response("")

        dispatcher = mock.MagicMock()
        dispatcher.dispatch_async = _empty_dispatch

        with mock.patch(
            "bot.dispatcher.get_dispatcher", return_value=dispatcher
        ), mock.patch.object(handler, "_schedule_reply"):
            handler._process_message(bot_message)

        sdk_client.reply.assert_not_called()

    def test_reply_stream_opt_in_uses_stream_frame(self):
        handler, sdk_client = _handler(reply_stream_enabled=True)

        with mock.patch.object(handler, "_schedule_reply", side_effect=lambda coro: coro.close()):
            handler._reply_to_frame({"headers": {"req_id": "req-7"}}, "hello")

        sdk_client.reply_stream.assert_called_once()
        args, _ = sdk_client.reply_stream.call_args
        frame_arg, stream_id, content, finish = args[0], args[1], args[2], args[3]
        assert frame_arg["headers"]["req_id"] == "req-7"
        assert stream_id
        assert content == "hello"
        assert finish is True

    def test_schedule_reply_without_loop_logs_and_skips(self, caplog):
        handler, _ = _handler()
        handler._loop = None

        async def _noop():
            pass

        coro = _noop()
        handler._schedule_reply(coro)
        coro.close()
        assert "事件循环不可用" in caplog.text


# ---------------------------------------------------------------------------
# main.py lifecycle integration point
# ---------------------------------------------------------------------------


class TestMainLifecycleHook:
    def _config(self, wecom_enabled):
        return mock.MagicMock(
            dingtalk_stream_enabled=False,
            feishu_stream_enabled=False,
            wecom_aibot_enabled=wecom_enabled,
        )

    def test_wecom_enabled_without_sdk_logs_install_hint(self, caplog):
        import main

        with mock.patch("bot.platforms.WECOM_AIBOT_SDK_AVAILABLE", False):
            main.start_bot_stream_clients(self._config(True))

        assert "pip install wecom-aibot-python-sdk" in caplog.text

    def test_wecom_enabled_with_sdk_starts_background(self, caplog):
        import logging

        import main

        caplog.set_level(logging.INFO)
        with mock.patch("bot.platforms.WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch("bot.platforms.start_wecom_aibot_background",
                           return_value=True) as start_bg:
            main.start_bot_stream_clients(self._config(True))

        start_bg.assert_called_once_with()
        assert "WeCom AI Bot" in caplog.text

    def test_wecom_disabled_is_silent(self, caplog):
        import main

        with mock.patch("bot.platforms.WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch("bot.platforms.start_wecom_aibot_background") as start_bg:
            main.start_bot_stream_clients(self._config(False))

        start_bg.assert_not_called()

    def test_wecom_start_failure_does_not_crash(self, caplog):
        import main

        with mock.patch("bot.platforms.WECOM_AIBOT_SDK_AVAILABLE", True), \
                mock.patch("bot.platforms.start_wecom_aibot_background",
                           side_effect=RuntimeError("boom")):
            main.start_bot_stream_clients(self._config(True))

        assert "Failed to start WeCom AI Bot" in caplog.text


# ---------------------------------------------------------------------------
# Config chain: dataclass keys + env parsing + registry metadata
# ---------------------------------------------------------------------------


class TestConfigChain:
    def test_config_dataclass_defaults_off(self):
        from src.config import Config

        config = Config(stock_list=[])
        assert config.wecom_aibot_enabled is False
        assert config.wecom_aibot_bot_id is None
        assert config.wecom_aibot_secret is None
        assert config.wecom_aibot_reply_stream is False

    def test_config_from_env(self, monkeypatch):
        from src.config import Config

        monkeypatch.setenv("WECOM_AIBOT_ENABLED", "true")
        monkeypatch.setenv("WECOM_AIBOT_BOT_ID", "bot-abc")
        monkeypatch.setenv("WECOM_AIBOT_SECRET", "secret-xyz")
        monkeypatch.setenv("WECOM_AIBOT_REPLY_STREAM", "true")

        config = Config._load_from_env()
        assert config.wecom_aibot_enabled is True
        assert config.wecom_aibot_bot_id == "bot-abc"
        assert config.wecom_aibot_secret == "secret-xyz"
        assert config.wecom_aibot_reply_stream is True

    def test_registry_metadata_complete(self):
        from src.core.config_registry import get_field_definition

        for key in WECOM_AIBOT_KEYS:
            field = get_field_definition(key)
            assert field["category"] == "notification", key
            assert field["help_key"] == f"settings.notification.{key}", key
            assert field["examples"], f"{key} missing examples"
            assert field["docs"], f"{key} missing docs"

    def test_env_example_keys_are_registered(self):
        import re
        from pathlib import Path

        from src.core.config_registry import (
            WEB_SETTINGS_HIDDEN_FROM_UI,
            get_registered_field_keys,
        )

        env_example = Path(__file__).resolve().parents[1] / ".env.example"
        active = {
            m.group(1)
            for line in env_example.read_text(encoding="utf-8").splitlines()
            for m in [re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip())]
            if m
        }
        wecom_active = {k for k in active if k.startswith("WECOM_AIBOT_")}
        assert wecom_active == set(WECOM_AIBOT_KEYS)
        registered = set(get_registered_field_keys())
        assert wecom_active - registered - WEB_SETTINGS_HIDDEN_FROM_UI == set()

    def test_settings_help_locales_cover_help_keys(self):
        import re
        from pathlib import Path

        help_file = (
            Path(__file__).resolve().parents[1]
            / "apps/dsa-web/src/locales/settingsHelp.ts"
        )
        content = help_file.read_text(encoding="utf-8")
        locale_keys = set(re.findall(r"^\s*'([^']+)'\s*:\s*\{", content, flags=re.MULTILINE))

        zh_count = content.count("const settingsHelpZhCN")
        en_count = content.count("const settingsHelpEnUS")
        assert zh_count == 1 and en_count == 1

        for key in WECOM_AIBOT_KEYS:
            help_key = f"settings.notification.{key}"
            assert help_key in locale_keys, f"{help_key} missing in settingsHelp.ts"

    def test_requirements_pin_declared(self):
        from pathlib import Path

        requirements = (
            Path(__file__).resolve().parents[1] / "requirements.txt"
        ).read_text(encoding="utf-8")
        assert "wecom-aibot-python-sdk" in requirements


if __name__ == "__main__":
    unittest.main()
