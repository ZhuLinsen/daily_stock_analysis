# -*- coding: utf-8 -*-
"""Tests for bot MarketCommand trading-day region filtering."""

import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub
    ensure_litellm_stub()

from bot.commands.market import MarketCommand
from bot.models import BotMessage, ChatType


def _make_message() -> BotMessage:
    return BotMessage(
        platform="feishu",
        message_id="m1",
        user_id="u1",
        user_name="tester",
        chat_id="c1",
        chat_type=ChatType.PRIVATE,
        content="/market",
        raw_content="/market",
        mentioned=False,
        timestamp=datetime.now(),
    )


class MarketCommandRegionFilterTestCase(unittest.TestCase):
    def _patch_dependencies(
        self,
        *,
        market_review_region: str,
        open_markets: set,
        trading_day_check_enabled: bool = True,
    ):
        config = SimpleNamespace(
            market_review_region=market_review_region,
            trading_day_check_enabled=trading_day_check_enabled,
            has_search_capability_enabled=lambda: False,
            gemini_api_key=None,
            openai_api_key=None,
        )
        notifier = MagicMock()
        notifier.is_available.return_value = True
        notifier.send.return_value = True

        notification_module = MagicMock()
        notification_module.NotificationService.return_value = notifier
        config_module = MagicMock()
        config_module.get_config.return_value = config
        runtime_module = MagicMock()
        runtime_notifier = MagicMock()
        runtime_analyzer = MagicMock()
        runtime_search = MagicMock()
        runtime_module.build_market_review_runtime.return_value = (
            runtime_notifier,
            runtime_analyzer,
            runtime_search,
        )
        market_review_module = MagicMock()
        market_review_module.run_market_review.return_value = "report"
        search_module = MagicMock()
        analyzer_module = MagicMock()
        trading_calendar_module = MagicMock()
        trading_calendar_module.get_open_markets_today.return_value = open_markets
        # Re-export the real compute_effective_region semantics
        from src.core.trading_calendar import compute_effective_region
        trading_calendar_module.compute_effective_region.side_effect = compute_effective_region

        patches = [
            patch.dict(
                sys.modules,
                {
                    "src.config": config_module,
                    "src.notification": notification_module,
                    "src.core.market_review": market_review_module,
                    "src.core.market_review_runtime": runtime_module,
                    "src.search_service": search_module,
                    "src.analyzer": analyzer_module,
                    "src.core.trading_calendar": trading_calendar_module,
                },
            )
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return (
            config,
            runtime_notifier,
            runtime_analyzer,
            runtime_search,
            market_review_module,
            runtime_module,
            notifier,
        )

    def test_both_with_cn_us_open_passes_override_region_cn_us(self) -> None:
        """MARKET_REVIEW_REGION=both + open markets {cn, us} -> override_region='cn,us'."""
        message = _make_message()
        config, notifier, runtime_analyzer, runtime_search, market_review_module, runtime_module, _ = self._patch_dependencies(
            market_review_region="both",
            open_markets={"cn", "us"},
        )

        cmd = MarketCommand()
        cmd._run_market_review(message, config, None)

        runtime_module.build_market_review_runtime.assert_called_once_with(
            config,
            source_message=message,
        )
        market_review_module.run_market_review.assert_called_once_with(
            notifier=notifier,
            analyzer=runtime_analyzer,
            search_service=runtime_search,
            send_notification=True,
            override_region="cn,us",
        )
        kwargs = market_review_module.run_market_review.call_args.kwargs
        self.assertEqual(kwargs.get("override_region"), "cn,us")

    def test_both_with_cn_hk_open_passes_override_region_cn_hk(self) -> None:
        """MARKET_REVIEW_REGION=both + open markets {cn, hk} -> override_region='cn,hk'."""
        message = _make_message()
        config, notifier, runtime_analyzer, runtime_search, market_review_module, runtime_module, _ = self._patch_dependencies(
            market_review_region="both",
            open_markets={"cn", "hk"},
        )

        cmd = MarketCommand()
        cmd._run_market_review(message, config, None)

        runtime_module.build_market_review_runtime.assert_called_once_with(
            config,
            source_message=message,
        )
        market_review_module.run_market_review.assert_called_once_with(
            notifier=notifier,
            analyzer=runtime_analyzer,
            search_service=runtime_search,
            send_notification=True,
            override_region="cn,hk",
        )
        market_review_module.run_market_review.assert_called_once()
        kwargs = market_review_module.run_market_review.call_args.kwargs
        self.assertEqual(kwargs.get("override_region"), "cn,hk")

    def test_all_relevant_markets_closed_skips_review(self) -> None:
        """If compute_effective_region returns '', skip review and notify."""
        message = _make_message()
        config, notifier, runtime_analyzer, runtime_search, market_review_module, runtime_module, notify_notifier = self._patch_dependencies(
            market_review_region="cn",
            open_markets=set(),
        )

        cmd = MarketCommand()
        cmd._run_market_review(message, config, None)

        market_review_module.run_market_review.assert_not_called()
        runtime_module.build_market_review_runtime.assert_not_called()
        notify_notifier.send.assert_called_once()
        sent = notify_notifier.send.call_args.args[0]
        self.assertIn("休市", sent)
        self.assertEqual(notify_notifier.send.call_args.kwargs["route_type"], "report")

    def test_trading_day_check_disabled_does_not_pass_override(self) -> None:
        """When TRADING_DAY_CHECK_ENABLED=false, override_region stays None."""
        message = _make_message()
        config, notifier, runtime_analyzer, runtime_search, market_review_module, runtime_module, _ = self._patch_dependencies(
            market_review_region="both",
            open_markets={"cn"},
            trading_day_check_enabled=False,
        )

        cmd = MarketCommand()
        cmd._run_market_review(message, config, None)

        runtime_module.build_market_review_runtime.assert_called_once_with(
            config,
            source_message=message,
        )
        market_review_module.run_market_review.assert_called_once_with(
            notifier=notifier,
            analyzer=runtime_analyzer,
            search_service=runtime_search,
            send_notification=True,
            override_region=None,
        )
        market_review_module.run_market_review.assert_called_once()
        kwargs = market_review_module.run_market_review.call_args.kwargs
        self.assertIsNone(kwargs.get("override_region"))

    def test_build_market_review_runtime_failure_still_releases_lock(self) -> None:
        """Runtime construction failure should still release the command-level lock token."""
        message = _make_message()
        config, notifier, runtime_analyzer, runtime_search, market_review_module, runtime_module, _ = self._patch_dependencies(
            market_review_region="cn",
            open_markets={"cn"},
        )

        cmd = MarketCommand()
        lock_token = object()
        runtime_module.build_market_review_runtime.side_effect = RuntimeError("runtime init failed")
        with patch.object(cmd, "_release_market_review_lock") as release_market_review_lock:
            cmd._run_market_review(message, config, lock_token)

        release_market_review_lock.assert_called_once_with(lock_token)
        market_review_module.run_market_review.assert_not_called()
        self.assertIsNotNone(notifier)

    def test_execute_releases_lock_when_thread_start_fails(self) -> None:
        """Thread start failure in execute() should release lock and return an error."""
        message = _make_message()
        config, _, _, _, _, _, _ = self._patch_dependencies(
            market_review_region="cn",
            open_markets={"cn"},
        )

        cmd = MarketCommand()
        lock_token = object()
        fake_thread = MagicMock()
        fake_thread.start.side_effect = RuntimeError("thread start failed")

        with patch.object(cmd, "_try_acquire_market_review_lock", return_value=lock_token), \
             patch.object(cmd, "_release_market_review_lock") as release_market_review_lock, \
             patch("bot.commands.market.threading.Thread", return_value=fake_thread):
            response = cmd.execute(message, [])

        release_market_review_lock.assert_called_once_with(lock_token)
        self.assertEqual(response.text, "❌ 错误：大盘复盘启动失败，已释放运行锁；请稍后重试")



if __name__ == "__main__":
    unittest.main()
