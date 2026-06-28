# -*- coding: utf-8 -*-
"""Tests for Issue #1386 P2-min market phase prompt rendering."""

import unittest

from src.market_phase_prompt import format_market_phase_prompt_section


def _ctx(**overrides):
    payload = {
        "market": "cn",
        "phase": "intraday",
        "market_local_time": "2026-03-27T10:00:00+08:00",
        "effective_daily_bar_date": "2026-03-26",
        "is_partial_bar": True,
        "minutes_to_open": None,
        "minutes_to_close": 300,
        "warnings": [],
        "trigger_source": "system",
        "analysis_intent": "auto",
    }
    payload.update(overrides)
    return payload


class MarketPhasePromptTestCase(unittest.TestCase):
    def test_empty_or_invalid_context_returns_empty_section(self):
        self.assertEqual(format_market_phase_prompt_section(None), "")
        self.assertEqual(format_market_phase_prompt_section({}), "")
        self.assertEqual(format_market_phase_prompt_section("intraday"), "")

    def test_premarket_mentions_opening_plan_and_completed_daily_bar(self):
        section = format_market_phase_prompt_section(
            _ctx(phase="premarket", is_partial_bar=False, minutes_to_open=30)
        )

        self.assertIn("市场阶段上下文", section)
        self.assertIn("盘前", section)
        self.assertIn("尚未开盘", section)
        self.assertIn("不得描述“今日走势已经发生”", section)
        self.assertIn("上一完整交易日", section)
        self.assertIn("2026-03-26", section)
        self.assertIn("距常规开盘约 30 分钟", section)

    def test_intraday_partial_bar_warns_against_full_daily_recap(self):
        section = format_market_phase_prompt_section(_ctx())

        self.assertIn("盘中", section)
        self.assertIn("当前不是盘后复盘", section)
        self.assertIn("最后一根日线可能尚未完成", section)
        self.assertIn("不得当作完整日线复盘", section)
        self.assertIn("距常规收盘约 300 分钟", section)

    def test_lunch_break_and_closing_auction_add_phase_specific_guidance(self):
        lunch = format_market_phase_prompt_section(_ctx(phase="lunch_break"))
        closing = format_market_phase_prompt_section(_ctx(phase="closing_auction"))

        self.assertIn("午间休市", lunch)
        self.assertIn("下午交易确认", lunch)
        self.assertIn("临近收盘", closing)
        self.assertIn("是否隔夜持仓", closing)

    def test_postmarket_keeps_recap_semantics(self):
        section = format_market_phase_prompt_section(
            _ctx(phase="postmarket", is_partial_bar=False, minutes_to_close=None)
        )

        self.assertIn("盘后", section)
        self.assertIn("完整交易日复盘语义", section)

    def test_non_trading_prevents_fake_intraday_movement(self):
        section = format_market_phase_prompt_section(
            _ctx(phase="non_trading", is_partial_bar=False, minutes_to_close=None)
        )

        self.assertIn("非交易日", section)
        self.assertIn("不得伪造今日盘中走势", section)
        self.assertIn("2026-03-26", section)

    def test_unknown_phase_and_warnings_are_conservative_without_raw_codes(self):
        section = format_market_phase_prompt_section(
            _ctx(phase="not_a_phase", warnings=["calendar_unavailable", "unknown_warning"])
        )

        self.assertIn("未知阶段", section)
        self.assertIn("不可可靠推断", section)
        self.assertIn("交易日历不可用", section)
        self.assertNotIn("calendar_unavailable", section)
        self.assertNotIn("unknown_warning", section)

    def test_missing_phase_uses_unknown_template(self):
        payload = _ctx()
        payload.pop("phase")

        section = format_market_phase_prompt_section(payload)

        self.assertIn("未知阶段", section)
        self.assertIn("不可可靠推断", section)

    def test_warnings_non_list_is_ignored(self):
        section = format_market_phase_prompt_section(_ctx(warnings="calendar_unavailable"))

        self.assertNotIn("降级说明", section)
        self.assertIn("盘中", section)

    def test_english_mode_outputs_readable_english_constraints(self):
        section = format_market_phase_prompt_section(
            _ctx(phase="premarket", is_partial_bar=False),
            report_language="en",
        )

        self.assertIn("Market Phase Context", section)
        self.assertIn("pre-market", section)
        self.assertIn("has not opened", section)
        self.assertIn("Do not describe today's price action as already happened", section)
        self.assertNotIn("(premarket)", section)

    def test_output_does_not_leak_runtime_raw_keys(self):
        section = format_market_phase_prompt_section(_ctx())

        self.assertNotIn("market_phase_context", section)
        self.assertNotIn("is_partial_bar", section)
        self.assertNotIn("trigger_source", section)
        self.assertNotIn("analysis_intent", section)
        self.assertNotIn("intraday", section)


if __name__ == "__main__":
    unittest.main()
