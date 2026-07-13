# -*- coding: utf-8 -*-
"""Tests for Korean (ko) output-language directives in analysis prompts (#1614)."""

import unittest

from src.agent.agents.decision_agent import DecisionAgent
from src.agent.protocols import AgentContext
from src.analysis_context_pack_prompt import normalize_analysis_context_pack_language
from src.market_phase_prompt import format_market_phase_prompt_section


def _phase_ctx():
    return {
        "market": "us",
        "phase": "premarket",
        "market_local_time": "2026-06-29T08:00:00-04:00",
        "effective_daily_bar_date": "2026-06-27",
        "minutes_to_open": 90,
        "warnings": [],
    }


class DecisionAgentLanguageDirectiveTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = DecisionAgent(tool_registry=None, llm_adapter=None)

    def _system_prompt(self, language: str, *, chat: bool = False) -> str:
        meta = {"report_language": language}
        if chat:
            meta["response_mode"] = "chat"
        ctx = AgentContext(stock_code="005930.KS", stock_name="삼성전자", meta=meta)
        return self.agent.system_prompt(ctx)

    def test_korean_dashboard_directive(self) -> None:
        prompt = self._system_prompt("ko")
        self.assertIn("Write all human-readable JSON values in Korean (한국어).", prompt)
        self.assertIn("`decision_type` must remain `buy|hold|sell`.", prompt)

    def test_korean_chat_directive(self) -> None:
        prompt = self._system_prompt("ko", chat=True)
        self.assertIn("항상 한국어로 답변하세요.", prompt)

    def test_english_directive_unchanged(self) -> None:
        prompt = self._system_prompt("en")
        self.assertIn("Write all human-readable JSON values in English.", prompt)

    def test_chinese_directive_unchanged(self) -> None:
        prompt = self._system_prompt("zh")
        self.assertIn("所有面向用户的人类可读文本值必须使用中文。", prompt)


class StructuralLanguageRoutingTestCase(unittest.TestCase):
    def test_context_pack_korean_reuses_english_scaffolding(self) -> None:
        self.assertEqual(normalize_analysis_context_pack_language("ko"), "en")
        self.assertEqual(normalize_analysis_context_pack_language("en"), "en")
        self.assertEqual(normalize_analysis_context_pack_language("zh"), "zh")

    def test_market_phase_korean_matches_english_structure(self) -> None:
        ko_section = format_market_phase_prompt_section(_phase_ctx(), report_language="ko")
        en_section = format_market_phase_prompt_section(_phase_ctx(), report_language="en")
        self.assertEqual(ko_section, en_section)
        self.assertIn("## Market Phase Context", ko_section)


if __name__ == "__main__":
    unittest.main()
