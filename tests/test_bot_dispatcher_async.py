# -*- coding: utf-8 -*-
"""Tests for async-friendly bot dispatcher execution."""

import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Keep tests runnable when optional deps are missing.
try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub
    ensure_litellm_stub()

from bot.commands.base import BotCommand
from bot.dispatcher import CommandDispatcher
from bot.models import BotMessage, BotResponse, ChatType


class DummyCommand(BotCommand):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def aliases(self):
        return []

    @property
    def description(self) -> str:
        return "dummy command"

    @property
    def usage(self) -> str:
        return "/dummy"

    def execute(self, message: BotMessage, args: list[str]) -> BotResponse:
        return BotResponse.text_response("dummy-ok")


def _make_message(content: str, mentioned: bool = False) -> BotMessage:
    return BotMessage(
        platform="feishu",
        message_id="m1",
        user_id="u1",
        user_name="tester",
        chat_id="c1",
        chat_type=ChatType.PRIVATE,
        content=content,
        raw_content=content,
        mentioned=mentioned,
        timestamp=datetime.now(),
    )


class TestBotCommandAsync(unittest.IsolatedAsyncioTestCase):
    async def test_execute_async_uses_to_thread(self):
        cmd = DummyCommand()
        message = _make_message("/dummy")

        with patch(
            "bot.commands.base.asyncio.to_thread",
            new=AsyncMock(return_value=BotResponse.text_response("ok")),
        ) as to_thread:
            result = await cmd.execute_async(message, [])

        self.assertEqual(result.text, "ok")
        to_thread.assert_awaited_once()


class TestCommandDispatcherAsync(unittest.IsolatedAsyncioTestCase):
    def test_nl_prefilter_matches_bse_codes(self):
        self.assertIsNotNone(CommandDispatcher._NL_PREFILTER.search("帮我分析430001"))

    def test_nl_prefilter_accepts_bare_lowercase_us_ticker(self):
        self.assertTrue(CommandDispatcher._passes_nl_prefilter("tsla"))

    def test_nl_prefilter_rejects_common_lowercase_word(self):
        self.assertFalse(CommandDispatcher._passes_nl_prefilter("hello"))

    async def test_dispatch_async_awaits_command_execute_async(self):
        dispatcher = CommandDispatcher()
        command = DummyCommand()
        command.execute_async = AsyncMock(return_value=BotResponse.text_response("async-ok"))
        dispatcher.register(command)

        result = await dispatcher.dispatch_async(_make_message("/dummy"))

        self.assertEqual(result.text, "async-ok")
        command.execute_async.assert_awaited_once()

    async def test_parse_intent_via_llm_offloads_to_thread(self):
        fake_response = SimpleNamespace(
            content='{"intent":"analysis","codes":["600519"],"strategy":null}',
            provider="gemini",
            usage={"total_tokens": 12},
        )
        config = SimpleNamespace(litellm_model="gemini/test-model")

        with patch(
            "bot.dispatcher.asyncio.to_thread",
            new=AsyncMock(side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)),
        ) as to_thread:
            with patch("src.agent.llm_adapter.LLMToolAdapter") as adapter_cls:
                adapter = MagicMock()
                adapter.call_text.return_value = fake_response
                adapter_cls.return_value = adapter
                result = await CommandDispatcher._parse_intent_via_llm("分析600519", config)

        self.assertEqual(result["intent"], "analysis")
        self.assertEqual(result["codes"], ["600519"])
        to_thread.assert_awaited_once()
        adapter.call_text.assert_called_once()

    async def test_try_nl_routing_uses_async_command_execution(self):
        dispatcher = CommandDispatcher()
        ask_command = DummyCommand()
        ask_command.execute_async = AsyncMock(return_value=BotResponse.text_response("ask-ok"))
        dispatcher.register(ask_command)
        dispatcher._commands["ask"] = ask_command

        config = SimpleNamespace(
            agent_nl_routing=True,
            agent_mode=True,
            litellm_model="gemini/test-model",
        )

        with patch("src.config.get_config", return_value=config):
            with patch.object(dispatcher, "_parse_intent_via_llm", new=AsyncMock(return_value={
                "intent": "analysis",
                "codes": ["600519"],
                "strategy": "缠论",
            })):
                result = await dispatcher._try_nl_routing(_make_message("帮我分析600519", mentioned=True))

        self.assertIsNotNone(result)
        self.assertEqual(result.text, "ask-ok")
        ask_command.execute_async.assert_awaited_once()

    async def test_try_nl_routing_resolves_name_only_analysis_request(self):
        dispatcher = CommandDispatcher()
        ask_command = DummyCommand()
        ask_command.execute_async = AsyncMock(return_value=BotResponse.text_response("ask-ok"))
        dispatcher.register(ask_command)
        dispatcher._commands["ask"] = ask_command

        config = SimpleNamespace(
            agent_nl_routing=True,
            agent_mode=True,
            litellm_model="gemini/test-model",
        )

        with patch("src.config.get_config", return_value=config):
            with patch(
                "src.services.name_to_code_resolver._get_akshare_name_to_code"
            ) as mock_akshare:
                with patch.object(
                    dispatcher,
                    "_parse_intent_via_llm",
                    new=AsyncMock(return_value={
                        "intent": "analysis",
                        "codes": [],
                        "strategy": None,
                    }),
                ):
                    result = await dispatcher._try_nl_routing(_make_message("帮我分析茅台", mentioned=True))

        self.assertIsNotNone(result)
        self.assertEqual(result.text, "ask-ok")
        ask_command.execute_async.assert_awaited_once()
        mock_akshare.assert_not_called()
        _, args = ask_command.execute_async.await_args.args
        self.assertEqual(args, ["600519"])


class TestCommandDispatcherSyncCompatibility(unittest.TestCase):
    def test_dispatch_sync_wrapper_still_works(self):
        dispatcher = CommandDispatcher()
        dispatcher.register(DummyCommand())

        result = dispatcher.dispatch(_make_message("/dummy"))

        self.assertEqual(result.text, "dummy-ok")

    def test_dispatch_sync_path_does_not_require_execute_async(self):
        dispatcher = CommandDispatcher()

        class SyncOnlyCommand(DummyCommand):
            async def execute_async(self, message, args):  # pragma: no cover - must not be called
                raise AssertionError("sync dispatch should call execute() directly")

        dispatcher.register(SyncOnlyCommand())

        result = dispatcher.dispatch(_make_message("/dummy"))

        self.assertEqual(result.text, "dummy-ok")


class TestHandleWebhookAsync(unittest.IsolatedAsyncioTestCase):
    """Test the async webhook handler path."""

    async def test_handle_webhook_async_dispatches_via_async(self):
        from bot.handler import handle_webhook_async

        fake_platform = MagicMock()
        fake_message = _make_message("/dummy")
        fake_platform.handle_webhook.return_value = (fake_message, None)
        fake_platform.format_response.return_value = MagicMock(text="ok-response")

        fake_config = MagicMock()
        fake_config.bot_enabled = True

        with patch("src.config.get_config", return_value=fake_config), \
             patch("bot.handler.get_platform", return_value=fake_platform), \
             patch("bot.handler.get_dispatcher") as mock_get_disp:
            mock_dispatcher = MagicMock()
            mock_dispatcher.dispatch_async = AsyncMock(return_value=BotResponse.text_response("async-resp"))
            mock_get_disp.return_value = mock_dispatcher

            await handle_webhook_async("feishu", {}, b'{}')

        mock_dispatcher.dispatch_async.assert_awaited_once()

    async def test_handle_webhook_async_returns_success_when_bot_disabled(self):
        from bot.handler import handle_webhook_async

        fake_config = MagicMock()
        fake_config.bot_enabled = False

        with patch("src.config.get_config", return_value=fake_config):
            result = await handle_webhook_async("feishu", {}, b'{}')

        # WebhookResponse.success() returns status_code 200
        self.assertEqual(result.status_code, 200)


class TestChatCommandCompatibility(unittest.TestCase):
    def test_chat_command_reuses_legacy_session_id_when_history_exists(self):
        from bot.commands.chat import ChatCommand

        command = ChatCommand()
        config = SimpleNamespace(agent_mode=True)
        executor = MagicMock()
        executor.chat.return_value = SimpleNamespace(success=True, content="ok", error=None)
        db = MagicMock()
        db.conversation_session_exists.side_effect = lambda session_id: session_id == "feishu_u1"

        with patch("bot.commands.chat.get_config", return_value=config), \
             patch("src.storage.get_db", return_value=db), \
             patch("src.agent.factory.build_agent_executor", return_value=executor):
            response = command.execute(_make_message("/chat hello"), ["hello"])

        self.assertEqual(response.text, "ok")
        executor.chat.assert_called_once()
        self.assertEqual(executor.chat.call_args.kwargs["session_id"], "feishu_u1")

    def test_chat_command_scopes_group_session_by_chat_id(self):
        from bot.commands.chat import ChatCommand

        command = ChatCommand()
        config = SimpleNamespace(agent_mode=True)
        executor = MagicMock()
        executor.chat.return_value = SimpleNamespace(success=True, content="ok", error=None)
        db = MagicMock()
        db.conversation_session_exists.side_effect = lambda session_id: session_id == "feishu_u1"
        message = _make_message("/chat hello")
        message.chat_type = ChatType.GROUP
        message.chat_id = "group-1"

        with patch("bot.commands.chat.get_config", return_value=config), \
             patch("src.storage.get_db", return_value=db), \
             patch("src.agent.factory.build_agent_executor", return_value=executor):
            response = command.execute(message, ["hello"])

        self.assertEqual(response.text, "ok")
        executor.chat.assert_called_once()
        self.assertEqual(executor.chat.call_args.kwargs["session_id"], "feishu_u1:group-1:chat")


class TestHistoryCommandCompatibility(unittest.TestCase):
    def test_history_clear_uses_group_scoped_session(self):
        from bot.commands.history import HistoryCommand

        command = HistoryCommand()
        db = MagicMock()
        db.delete_conversation_session.side_effect = lambda session_id: 1 if session_id == "feishu_u1:group-1:chat" else 0
        message = _make_message("/history clear")
        message.chat_type = ChatType.GROUP
        message.chat_id = "group-1"

        with patch("src.storage.get_db", return_value=db):
            response = command.execute(message, ["clear"])

        self.assertIn("1 条消息", response.text)
        db.delete_conversation_session.assert_called_once_with("feishu_u1:group-1:chat")


class TestDispatcherBaseException(unittest.TestCase):
    """Verify dispatcher thread propagates BaseException subclasses."""

    def test_error_holder_accepts_base_exception(self):
        """Ensure error_holder dict uses BaseException type hint (code review)."""
        import inspect
        from bot.dispatcher import CommandDispatcher
        source = inspect.getsource(CommandDispatcher.dispatch)
        self.assertIn("BaseException", source)
        self.assertNotIn("except Exception", source)


if __name__ == "__main__":
    unittest.main()
