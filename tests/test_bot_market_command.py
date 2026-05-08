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
                    "src.search_service": search_module,
                    "src.analyzer": analyzer_module,
                    "src.core.trading_calendar": trading_calendar_module,
                },
            )
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return notifier, market_review_module

    def test_both_with_cn_us_open_passes_override_region_cn_us(self) -> None:
        """MARKET_REVIEW_REGION=both + open markets {cn, us} -> override_region='cn,us'."""
        notifier, market_review_module = self._patch_dependencies(
            market_review_region="both",
            open_markets={"cn", "us"},
        )

        cmd = MarketCommand()
        cmd._run_market_review(_make_message())

        market_review_module.run_market_review.assert_called_once()
        kwargs = market_review_module.run_market_review.call_args.kwargs
        self.assertEqual(kwargs.get("override_region"), "cn,us")

    def test_both_with_cn_hk_open_passes_override_region_cn_hk(self) -> None:
        """MARKET_REVIEW_REGION=both + open markets {cn, hk} -> override_region='cn,hk'."""
        notifier, market_review_module = self._patch_dependencies(
            market_review_region="both",
            open_markets={"cn", "hk"},
        )

        cmd = MarketCommand()
        cmd._run_market_review(_make_message())

        market_review_module.run_market_review.assert_called_once()
        kwargs = market_review_module.run_market_review.call_args.kwargs
        self.assertEqual(kwargs.get("override_region"), "cn,hk")

    def test_all_relevant_markets_closed_skips_review(self) -> None:
        """If compute_effective_region returns '', skip review and notify."""
        notifier, market_review_module = self._patch_dependencies(
            market_review_region="cn",
            open_markets=set(),
        )

        cmd = MarketCommand()
        cmd._run_market_review(_make_message())

        market_review_module.run_market_review.assert_not_called()
        notifier.send.assert_called_once()
        sent = notifier.send.call_args.args[0]
        self.assertIn("休市", sent)

    def test_trading_day_check_disabled_does_not_pass_override(self) -> None:
        """When TRADING_DAY_CHECK_ENABLED=false, override_region stays None."""
        notifier, market_review_module = self._patch_dependencies(
            market_review_region="both",
            open_markets={"cn"},
            trading_day_check_enabled=False,
        )

        cmd = MarketCommand()
        cmd._run_market_review(_make_message())

        market_review_module.run_market_review.assert_called_once()
        kwargs = market_review_module.run_market_review.call_args.kwargs
        self.assertIsNone(kwargs.get("override_region"))


if __name__ == "__main__":
    unittest.main()
