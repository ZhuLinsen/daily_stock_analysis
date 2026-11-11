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
import threading
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


# ---------------------------------------------------------------------------
# r2 OR-COR-a12b0edd: reconnect-budget exhaustion must self-heal via the
# outer supervision loop (no dead-but-alive thread, no manual restart)
# ---------------------------------------------------------------------------


class _StubSdkClient:
    """Stub faithful to the real SDK WSClient surface used by the adapter."""

    instances = []

    def __init__(self, options):
        self.options = options
        self._handlers = {}
        self.connect_count = 0
        self.disconnect_count = 0
        _StubSdkClient.instances.append(self)

    def on(self, event, handler=None):
        if handler is not None:
            self._handlers.setdefault(event, []).append(handler)
            return handler

        def _deco(handler_):
            self._handlers.setdefault(event, []).append(handler_)
            return handler_

        return _deco

    def emit(self, event, *args):
        for handler in list(self._handlers.get(event, [])):
            handler(*args)

    async def connect(self):
        self.connect_count += 1
        # Simulate: network drop -> SDK internal reconnect budget exhausted.
        self.emit("error", Exception("Max reconnect attempts exceeded"))
        await asyncio.sleep(3600)  # never completes; the loop gets stopped

    def disconnect(self):
        self.disconnect_count += 1


class TestReconnectBudgetSelfHealing:
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

    def test_exhaustion_error_ends_cycle_and_plans_rebuild(self):
        client = self._client()

        loop = asyncio.new_event_loop()
        try:
            client._loop = loop
            with mock.patch.object(loop, "call_soon_threadsafe") as schedule_stop:
                client._handle_auth_error(Exception("Max reconnect attempts exceeded"))

            schedule_stop.assert_called_once()
            assert schedule_stop.call_args[0][0] == loop.stop
        finally:
            client._loop = None
            loop.close()

        assert client._cycle_failed is True
        assert client._planned_cycle_delay == client._CYCLE_RETRY_BASE_DELAY_SECONDS
        # Budget exhaustion is a runtime failure, not an auth failure.
        assert client._auth_attempts == 0
        assert client._auth_failed is False

    def test_cycle_backoff_is_exponential_capped_and_never_gives_up(self):
        client = self._client()

        delays = [client._next_cycle_retry_delay() for _ in range(12)]

        assert delays[0] == client._CYCLE_RETRY_BASE_DELAY_SECONDS
        assert delays == sorted(delays)
        assert delays[-1] == client._CYCLE_RETRY_MAX_DELAY_SECONDS
        # Self-heal requirement: never returns None (no give-up on rebuilds).
        assert all(d > 0 for d in delays)

    def test_cycle_budget_resets_on_authenticated(self):
        client = self._client()

        client._next_cycle_retry_delay()
        client._next_cycle_retry_delay()
        assert client._cycle_attempts == 2

        client._on_authenticated()
        assert client._cycle_attempts == 0

    def test_supervision_loop_rebuilds_connection_cycle_after_exhaustion(self):
        client = self._client()
        client._running = True

        # Stub factory: build the stub and register the REAL adapter event
        # handlers on it, so the emitted "Max reconnect attempts exceeded"
        # flows through the production error path.
        def _make_stub():
            stub = _StubSdkClient(None)
            client._register_sdk_events(stub)
            return stub

        # Watchdog: without the fix the supervision loop hangs forever in the
        # dead-idle run_forever (exactly the reviewer-reported defect); the
        # join timeout turns that into a deterministic RED failure.
        threads_before = threading.active_count()
        with mock.patch.object(client, "_create_sdk_client",
                               side_effect=_make_stub), \
                mock.patch.object(client._stop_event, "wait",
                                  side_effect=[False, True]):
            worker = threading.Thread(target=client._run_background, daemon=True)
            worker.start()
            worker.join(timeout=15)
            if worker.is_alive():
                client.stop()
                worker.join(timeout=5)
        assert not worker.is_alive(), (
            "supervision loop did not rebuild the connection cycle after "
            "SDK reconnect budget exhaustion (dead-but-alive thread)"
        )

        # Two connection cycles were built by the supervision loop: the first
        # exhausted the SDK budget, the outer loop rebuilt a fresh cycle (new
        # SDK client instance = fresh internal reconnect budget).
        assert len(_StubSdkClient.instances) == 2
        assert _StubSdkClient.instances[0].connect_count == 1
        assert _StubSdkClient.instances[1].connect_count == 1
        # Old clients were disconnected during teardown.
        assert all(inst.disconnect_count == 1 for inst in _StubSdkClient.instances)
        # No thread leak: both cycles ran inside the single supervision thread.
        assert threading.active_count() == threads_before
        assert client._cycle_attempts >= 1

    def test_auth_success_clears_cycle_failure_state(self):
        client = self._client()
        client._cycle_failed = True
        client._planned_cycle_delay = 8.0

        client._on_authenticated()

        assert client._cycle_failed is False
        assert client._planned_cycle_delay is None


# ---------------------------------------------------------------------------
# r2 OR-COM-62e2b418: dual-window (minute + hour) per-conversation reply quota
# ---------------------------------------------------------------------------


class TestHourlyConversationQuota:
    def _handler(self):
        handler, sdk_client = _handler()
        return handler, sdk_client

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

    def test_outbound_limiters_are_dual_window(self):
        from bot.dispatcher import RateLimiter

        handler, _ = self._handler()
        assert isinstance(handler._outbound_minute_limiter, RateLimiter)
        assert handler._outbound_minute_limiter.max_requests == 30
        assert handler._outbound_minute_limiter.window_seconds == 60
        assert isinstance(handler._outbound_hour_limiter, RateLimiter)
        assert handler._outbound_hour_limiter.max_requests == 1000
        assert handler._outbound_hour_limiter.window_seconds == 3600

    def test_reply_hourly_quota_probe_17_per_minute_for_an_hour(self, caplog):
        """Reviewer probe: 17 msgs/min sustained for an hour must stop at the
        1000th reply (minute window untouched, hourly window rejects)."""
        handler, sdk_client = self._handler()

        clock = [1_000_000.0]

        with mock.patch("bot.dispatcher.time.time", side_effect=lambda: clock[0]), \
                mock.patch.object(handler, "_schedule_reply",
                                  side_effect=lambda coro: coro.close()):
            for i in range(1020):
                handler._reply_to_frame(
                    _text_frame(msgid=f"m{i}", chatid="chat-hour"), f"r{i}"
                )
                if (i + 1) % 17 == 0:
                    clock[0] += 61  # advance past the minute window every 17 sends

        # First 1000 replies went out; replies 1001..1020 dropped by the hour.
        assert sdk_client.reply.call_count == 1000
        assert "超限" in caplog.text or "1000" in caplog.text

    def test_outbound_gate_hour_exhaustion_rejects(self):
        handler, _ = self._handler()

        # Isolate the hour window: pin the minute limiter open.
        minute_stub = mock.MagicMock()
        minute_stub.would_allow.return_value = True
        minute_stub.is_allowed.return_value = True
        with mock.patch.object(handler, "_outbound_minute_limiter", minute_stub):
            # Hour exhausted -> reject even when the minute window is wide open.
            for _ in range(handler._outbound_hour_limiter.max_requests):
                assert handler._allow_outbound_reply("chat-x") is True
            assert handler._allow_outbound_reply("chat-x") is False
            # A different conversation is unaffected.
            assert handler._allow_outbound_reply("chat-y") is True

    def test_passive_reply_path_gated_by_dual_window(self):
        handler, sdk_client = self._handler()
        frame = _text_frame(msgid="m", chatid="chat-g")

        with mock.patch.object(handler, "_schedule_reply",
                               side_effect=lambda coro: coro.close()):
            for _ in range(30):
                assert handler._reply_to_frame(frame, "r") is True
            # Minute window now full for this conversation.
            assert handler._reply_to_frame(frame, "r") is False

        assert sdk_client.reply.call_count == 30

    def test_proactive_send_path_gated_and_checks_ack(self, caplog):
        client = self._client()
        handler = client._handler
        client._running = True
        client._sdk_client = mock.MagicMock()

        # Exhaust the hourly quota for the conversation (direct window fill).
        for _ in range(1000):
            handler._outbound_hour_limiter.is_allowed("chat-pro")
        assert client.send_to_chat("chat-pro", "report") is False
        assert "超限" in caplog.text

        caplog.clear()
        # Quota open + loop unavailable -> quota passed, loop missing rejects.
        assert client.send_to_chat("chat-other", "report") is False
        assert "事件循环不可用" in caplog.text

    def test_send_to_chat_happy_path_and_errcode_ack(self, caplog):
        client = self._client()
        client._running = True

        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        try:
            client._loop = loop
            client._handler._loop = loop
            sdk_client = mock.MagicMock()

            async def _ack_ok(chatid, body):
                return {"errcode": 0, "errmsg": "ok"}

            async def _ack_err(chatid, body):
                return {"errcode": 44002, "errmsg": "user never messaged the bot"}

            client._sdk_client = sdk_client
            sdk_client.send_message = _ack_ok
            assert client.send_to_chat("chat-ok", "📊 报告") is True

            sdk_client.send_message = _ack_err
            assert client.send_to_chat("chat-ok", "📊 报告") is False
            assert "会话" in caplog.text  # precondition hint on non-zero errcode
        finally:
            client._loop = None
            client._handler._loop = None
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            loop.close()

    def test_send_to_chat_refuses_when_client_not_running(self, caplog):
        client = self._client()
        client._running = False

        assert client.send_to_chat("chat-a", "x") is False
        assert "未运行" in caplog.text


# ---------------------------------------------------------------------------
# r2 OR-COR-26fa4c23: /analyze results must return to the WeCom source
# conversation via the source-context notification channel
# ---------------------------------------------------------------------------


def _make_wecom_message():
    from bot.models import BotMessage

    return BotMessage(
        platform="wecom",
        message_id="msg-wx-1",
        user_id="enc-user-9",
        user_name="enc-user-9",
        chat_id="wrk-group-9",
        chat_type=ChatType.GROUP,
        content="/analyze 600519",
        raw_data={
            "_wecom_req_id": "req-9",
            "_wecom_frame": {"cmd": "aibot_msg_callback", "headers": {"req_id": "req-9"}},
        },
    )


def _pure_wecom_config(**overrides):
    """Config with zero static notification channels (pure WeCom aibot setup)."""
    from src.config import Config

    base = dict(
        stock_list=[],
        wechat_webhook_url=None,
        dingtalk_app_key=None,
        dingtalk_app_secret=None,
        dingtalk_webhook_url=None,
        feishu_webhook_url=None,
        feishu_app_id=None,
        feishu_app_secret=None,
        telegram_bot_token=None,
        telegram_chat_id=None,
        email_sender=None,
        email_password=None,
        email_receivers=[],
    )
    base.update(overrides)
    return Config(**base)


class TestSourceContextNotification:
    """OR-COR-26fa4c23: WeCom aibot registered as a source-context channel."""

    def _service(self, config):
        from src.notification import NotificationService

        with mock.patch("src.notification.get_config", return_value=config):
            return NotificationService(source_message=_make_wecom_message())

    def test_wecom_source_message_is_context_channel(self):
        service = self._service(_pure_wecom_config())

        assert service._has_context_channel() is True
        # Pure WeCom setup: no static channel configured, yet available.
        assert service.is_available() is True
        # And the source conversation must NOT broadcast static channels.
        assert service.should_broadcast_static_channels() is False

    def test_extract_wecom_context_chat_id(self):
        service = self._service(_pure_wecom_config())

        context = service._extract_wecom_aibot_context()
        assert context == {"chat_id": "wrk-group-9"}

    def test_send_to_context_routes_to_wecom_client(self):
        service = self._service(_pure_wecom_config())

        with mock.patch.object(service, "_send_wecom_aibot_reply",
                               return_value=True) as send_reply:
            assert service.send_to_context("📊 报告") is True
        send_reply.assert_called_once_with("wrk-group-9", "📊 报告")

    def test_non_wecom_platform_has_no_wecom_context(self):
        from src.notification import NotificationService

        config = _pure_wecom_config()
        dingtalk_message = mock.MagicMock()
        dingtalk_message.platform = "dingtalk"
        with mock.patch("src.notification.get_config", return_value=config):
            service = NotificationService(source_message=dingtalk_message)

        assert service._extract_wecom_aibot_context() is None

    def test_wecom_context_response_skips_static_channels(self):
        from src.notification import NotificationService

        config = _pure_wecom_config(
            wechat_webhook_url="https://wechat.example/hook",
        )
        with mock.patch("src.notification.get_config", return_value=config):
            service = NotificationService(source_message=_make_wecom_message())

        with mock.patch.object(service, "_send_wecom_aibot_reply",
                               return_value=True), \
                mock.patch.object(service, "send_to_wechat",
                                  return_value=True) as mock_wechat:
            result = service.send_with_results("content", route_type="report")

        assert result.dispatched is True
        assert result.success is True
        assert [item.channel for item in result.channel_results] == ["__context__"]
        mock_wechat.assert_not_called()

    def test_send_wecom_aibot_reply_calls_adapter_send_to_chat(self):
        from src.notification import NotificationService

        service = NotificationService(source_message=_make_wecom_message())
        adapter_client = mock.MagicMock()
        adapter_client.send_to_chat.return_value = True

        with mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client",
            return_value=adapter_client,
        ), mock.patch(
            "bot.platforms.wecom_aibot.WECOM_AIBOT_SDK_AVAILABLE", True
        ):
            assert service._send_wecom_aibot_reply("wrk-group-9", "📊 报告") is True

        adapter_client.send_to_chat.assert_called_once_with("wrk-group-9", "📊 报告")

    def test_send_wecom_aibot_reply_without_sdk_returns_false(self):
        from src.notification import NotificationService

        service = NotificationService(source_message=_make_wecom_message())

        with mock.patch(
            "bot.platforms.wecom_aibot.WECOM_AIBOT_SDK_AVAILABLE", False
        ), mock.patch(
            "bot.platforms.wecom_aibot.get_wecom_aibot_client"
        ) as get_client:
            assert service._send_wecom_aibot_reply("wrk-group-9", "x") is False
        get_client.assert_not_called()

    def test_full_round_trip_report_returns_to_source_conversation(self):
        """/analyze 提交 → 任务完成 → 报告回到企微来源会话（mock
        TaskService / NotificationService 协作的端到端断言）。"""
        handler, _ = _handler()
        frame = _text_frame(
            msgid="rt-1", content="/analyze 600519",
            chatid="wrk-group-9", chattype="group",
        )
        bot_message = handler._parse_frame(frame)

        captured = {}

        async def _fake_dispatch(msg):
            # AnalyzeCommand semantics: submit the task carrying the source
            # message so the completion notification can route back.
            captured["source_message"] = msg
            return BotResponse.markdown_response("✅ 分析任务已提交")

        dispatcher = mock.MagicMock()
        dispatcher.dispatch_async = _fake_dispatch

        with mock.patch(
            "bot.dispatcher.get_dispatcher", return_value=dispatcher
        ), mock.patch.object(handler, "_schedule_reply",
                             side_effect=lambda coro: coro.close()):
            handler._process_message(bot_message)

        assert "source_message" in captured

        from src.notification import NotificationService

        adapter_client = mock.MagicMock()
        adapter_client.send_to_chat.return_value = True

        with mock.patch("src.notification.get_config",
                        return_value=_pure_wecom_config()), \
                mock.patch("bot.platforms.wecom_aibot.get_wecom_aibot_client",
                           return_value=adapter_client), \
                mock.patch("bot.platforms.wecom_aibot.WECOM_AIBOT_SDK_AVAILABLE", True):
            service = NotificationService(source_message=captured["source_message"])
            assert service.is_available() is True
            assert service.should_broadcast_static_channels() is False

            result = service.send_with_results("📊 600519 分析报告", route_type="report")

            assert result.dispatched is True
            assert result.success is True
            adapter_client.send_to_chat.assert_called_once()
            chat_id_arg, content_arg = adapter_client.send_to_chat.call_args[0]
            assert chat_id_arg == "wrk-group-9"
            assert "分析报告" in content_arg

    def test_wecom_context_push_failure_does_not_broadcast_static(self):
        from src.notification import NotificationService

        config = _pure_wecom_config(
            wechat_webhook_url="https://wechat.example/hook",
        )
        with mock.patch("src.notification.get_config", return_value=config):
            service = NotificationService(source_message=_make_wecom_message())

        with mock.patch.object(service, "_send_wecom_aibot_reply",
                               return_value=False), \
                mock.patch.object(service, "send_to_wechat",
                                  return_value=True) as mock_wechat:
            result = service.send_with_results("content", route_type="report")

        assert result.dispatched is True
        assert result.success is False
        mock_wechat.assert_not_called()


# ---------------------------------------------------------------------------
# r3 OR-COM-62e2b418 (refined): outbound dual-window quota must be atomic —
# check both windows read-only in one critical section, record both only when
# both allow, minute rejection must not burn hour quota.
# ---------------------------------------------------------------------------


class TestRateLimiterAtomicPrimitives:
    """would_allow/record must split check from accounting (additive API)."""

    def test_would_allow_does_not_record(self):
        from bot.dispatcher import RateLimiter

        limiter = RateLimiter(max_requests=2, window_seconds=60)
        assert limiter.would_allow("u") is True
        # Read-only: nothing recorded yet.
        assert len(limiter._requests["u"]) == 0
        assert limiter.get_remaining("u") == 2

    def test_would_allow_rejects_at_capacity_without_recording(self):
        from bot.dispatcher import RateLimiter

        limiter = RateLimiter(max_requests=2, window_seconds=60)
        limiter.record("u")
        limiter.record("u")
        assert limiter.would_allow("u") is False
        assert len(limiter._requests["u"]) == 2  # rejection added nothing

    def test_record_after_would_allow_matches_is_allowed(self):
        from bot.dispatcher import RateLimiter

        reference = RateLimiter(max_requests=3, window_seconds=60)
        split = RateLimiter(max_requests=3, window_seconds=60)

        for _ in range(3):
            assert reference.is_allowed("u") is True
        assert reference.is_allowed("u") is False

        for _ in range(3):
            assert split.would_allow("u") is True
            split.record("u")
        assert split.would_allow("u") is False

        assert len(split._requests["u"]) == len(reference._requests["u"]) == 3
        assert split.get_remaining("u") == reference.get_remaining("u") == 0


class _GateHourLimiter:
    """Deterministic race injector standing in for the hour window.

    Both callers' window checks complete before either caller records — the
    reproducible form of the concurrent-overshoot race the reviewer
    described (hour=999, two concurrent callers). Delegates window state to
    a real RateLimiter so counts are directly inspectable.
    """

    def __init__(self, real):
        self._real = real
        self._pending_checks = 0
        self._lock = threading.Lock()
        self._checks_gate = threading.Event()

    @property
    def _requests(self):
        return self._real._requests

    def _gated_check(self, user_id):
        allowed = self._real.would_allow(user_id)
        with self._lock:
            self._pending_checks += 1
            if self._pending_checks >= 2:
                self._checks_gate.set()
        # Hold until every racing caller has completed its window check.
        self._checks_gate.wait(timeout=2)
        return allowed

    def would_allow(self, user_id):
        return self._gated_check(user_id)

    def is_allowed(self, user_id):
        allowed = self._gated_check(user_id)
        if allowed:
            self.record(user_id)
        return allowed

    def record(self, user_id):
        self._real.record(user_id)


class TestOutboundQuotaAtomicity:
    def _handler(self):
        handler, sdk_client = _handler()
        return handler, sdk_client

    def test_concurrent_callers_cannot_overshoot_hour_quota(self):
        """反例①：小时额度 999 时两线程并发决策 → 恰一个 True、小时计 1000。"""
        handler, _ = self._handler()

        gate_limiter = _GateHourLimiter(handler._outbound_hour_limiter)

        # Pin the minute window open so the race isolates the hour decision.
        minute_stub = mock.MagicMock()
        minute_stub.would_allow.return_value = True
        minute_stub.is_allowed.return_value = True

        # Preset: hour window at 999/1000 for the conversation.
        for _ in range(999):
            handler._outbound_hour_limiter.is_allowed("chat-x")

        with mock.patch.object(handler, "_outbound_minute_limiter", minute_stub), \
                mock.patch.object(handler, "_outbound_hour_limiter", gate_limiter,
                                  create=True):
            start = threading.Barrier(2, timeout=5)
            results = []
            errors = []

            def _caller():
                try:
                    start.wait()
                    results.append(handler._allow_outbound_reply("chat-x"))
                except Exception as exc:  # pragma: no cover
                    errors.append(exc)

            threads = [threading.Thread(target=_caller) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

        assert errors == []
        # Exactly one caller wins the last hour slot.
        assert results.count(True) == 1, f"overshoot: {results}"
        assert len(handler._outbound_hour_limiter._requests["chat-x"]) == 1000

    def test_minute_rejection_does_not_burn_hour_quota(self):
        """反例②：分钟窗口满后的尝试不得消耗小时额度；窗口恢复后额度完整。"""
        import time as _time

        handler, _ = self._handler()

        # All quota decisions run under one controlled clock so the +61s
        # advance genuinely slides the minute window past the fill timestamps.
        clock = [_time.time()]

        def _now():
            return clock[0]

        with mock.patch("bot.dispatcher.time.time", side_effect=_now):
            # Fill the minute window (30) for the conversation; hour untouched.
            for _ in range(30):
                assert handler._outbound_minute_limiter.is_allowed("chat-m") is True
            assert len(
                handler._outbound_hour_limiter._requests.get("chat-m", [])
            ) == 0

            for _ in range(20):
                assert handler._allow_outbound_reply("chat-m") is False

            hour_after = len(
                handler._outbound_hour_limiter._requests.get("chat-m", [])
            )
            assert hour_after == 0, (
                "minute rejection burned hour quota: "
                f"{hour_after} slots"
            )

            # Window recovered -> full quota available again, hour debits 1.
            clock[0] += 61
            assert handler._allow_outbound_reply("chat-m") is True
            assert len(
                handler._outbound_hour_limiter._requests["chat-m"]
            ) == 1


if __name__ == "__main__":
    unittest.main()
