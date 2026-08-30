# -*- coding: utf-8 -*-
"""决策仪表盘日报按市场分节展示（多市场 STOCK_LIST 场景）。

背景：STOCK_LIST 可同时混合 A 股 / 美股 / 印度股票等多个市场，日报此前
按评分单一排序，不同市场的标的会随机穿插，读者难以按市场分区阅读。
这些用例锁住两个状态：
1. 多市场混合时，报告按 MARKET_SECTION_ORDER 顺序分节，且组内仍按评分排序；
2. 单一市场时不出现分节标题，行为与既有报告保持一致（零回归）。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.notification import NotificationService
from src.report_language import get_market_section_title


def _make_result(*, code, sentiment_score, report_language="en"):
    from src.analyzer import AnalysisResult

    return AnalysisResult(
        code=code,
        name=code,
        sentiment_score=sentiment_score,
        trend_prediction="hold",
        operation_advice="watch",
        analysis_summary="test",
        report_language=report_language,
        success=True,
    )


class GroupResultsByMarketTestCase(unittest.TestCase):
    def test_groups_in_canonical_market_order_with_score_sort_preserved(self):
        results = sorted(
            [
                _make_result(code="AAPL", sentiment_score=80),
                _make_result(code="RELIANCE.NS", sentiment_score=70),
                _make_result(code="600519", sentiment_score=90),
                _make_result(code="TCS.NS", sentiment_score=60),
            ],
            key=lambda r: r.sentiment_score,
            reverse=True,
        )

        groups = NotificationService._group_results_by_market(results)

        self.assertEqual([market for market, _ in groups], ["cn", "us", "in"])
        self.assertEqual([r.code for _, group in groups for r in group][2:], ["RELIANCE.NS", "TCS.NS"])

    def test_single_market_returns_one_group(self):
        results = [_make_result(code="AAPL", sentiment_score=1), _make_result(code="TSLA", sentiment_score=2)]
        groups = NotificationService._group_results_by_market(results)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0], "us")


class DashboardReportMarketSectionsTestCase(unittest.TestCase):
    def setUp(self):
        self.service = NotificationService()

    def test_multi_market_report_shows_localized_section_headings(self):
        results = [
            _make_result(code="AAPL", sentiment_score=80),
            _make_result(code="RELIANCE.NS", sentiment_score=70),
        ]
        report = self.service.generate_dashboard_report(results, report_date="2026-08-30")

        self.assertIn(get_market_section_title("us", "en"), report)
        self.assertIn(get_market_section_title("in", "en"), report)

    def test_single_market_report_has_no_section_heading(self):
        results = [_make_result(code="AAPL", sentiment_score=80)]
        report = self.service.generate_dashboard_report(results, report_date="2026-08-30")

        self.assertNotIn(get_market_section_title("us", "en"), report)


if __name__ == "__main__":
    unittest.main()
