# -*- coding: utf-8 -*-
"""Korean (ko) deterministic fallback coverage for the report-language sweep (#1614)."""

import unittest

from src.core.market_review import _get_market_review_text
from src.report_language import (
    get_no_data_text,
    get_placeholder_text,
    get_unknown_text,
    localize_strategy_skill,
    localize_strategy_skill_description,
)


class KoreanFallbackTextTestCase(unittest.TestCase):
    def test_placeholder_unknown_no_data_have_korean(self) -> None:
        self.assertEqual(get_placeholder_text("ko"), "미정")
        self.assertEqual(get_unknown_text("ko"), "알 수 없음")
        self.assertEqual(get_no_data_text("ko"), "데이터 없음")

    def test_market_review_titles_korean(self) -> None:
        text = _get_market_review_text("ko")
        self.assertEqual(text["push_title"], "🎯 시황 리뷰")
        self.assertIn("시황 리뷰", text["root_title"])
        self.assertIn("한국", text["kr_title"])

    def test_market_review_titles_unchanged_for_en_zh(self) -> None:
        self.assertEqual(_get_market_review_text("en")["push_title"], "🎯 Market Review")
        self.assertEqual(_get_market_review_text("zh")["push_title"], "🎯 大盘复盘")

    def test_builtin_strategy_alias_and_description_are_korean(self) -> None:
        self.assertEqual(localize_strategy_skill("一阳夹三阴", "ko"), "일양협삼음")
        self.assertEqual(localize_strategy_skill("龙头策略", "ko"), "대장주 전략")
        self.assertEqual(
            localize_strategy_skill_description(
                "emotion_cycle",
                "基于市场情绪、换手率与量价结构，识别情绪低点（恐慌底）与情绪高点（狂热顶），逆情绪布局。",
                "ko",
            ),
            "시장 심리, 회전율, 거래량·가격 구조를 바탕으로 공포 저점과 과열 고점을 식별해 역심리 관점의 진입 기회를 찾습니다.",
        )


if __name__ == "__main__":
    unittest.main()
