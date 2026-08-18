# -*- coding: utf-8 -*-
"""新闻面为空时必须在报告里如实标注。

背景：消息面章节原先是「有内容才渲染」，检索一条没拿到时整段直接消失，
读报告的人无从判断是确实没新闻，还是检索静默失败了（搜索源限流、
未配置可用渠道等）。这会把「抓取失败」呈现成「确实没有新闻」，
比单纯的慢更容易误导结论。

这些用例锁住三件事：
1. 检索执行了但为空（count == 0）时，必须出现明确提示；
2. 未执行检索（count is None）时不得误报，那是用户没配搜索渠道，不是失败；
3. 正常拿到新闻时，行为与此前完全一致。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.notification import NotificationService


DISCLOSURE = "未获取到可用的新闻面数据"


def _make_result(*, news_summary="", news_result_count=None):
    """构造一个最小可渲染的分析结果。

    只填渲染日报必需的字段，避免与被测行为无关的细节耦合。
    """
    from src.analyzer import AnalysisResult

    return AnalysisResult(
        code="600519",
        name="测试标的",
        sentiment_score=50,
        trend_prediction="震荡",
        operation_advice="观望",
        analysis_summary="用于测试的综合分析。",
        news_summary=news_summary,
        news_result_count=news_result_count,
        success=True,
    )


class EmptyNewsDisclosureTestCase(unittest.TestCase):
    def setUp(self):
        # 只测报告渲染，不触碰任何推送渠道：用 __new__ 跳过依赖配置的初始化，
        # 再补上 generate_daily_report 实际用到的少量属性。
        self.service = NotificationService.__new__(NotificationService)
        self.service._report_summary_only = False

    def _render(self, result):
        return NotificationService.generate_daily_report(
            self.service, [result], report_date="2026-08-18"
        )

    def test_discloses_when_search_ran_but_returned_nothing(self):
        """检索执行了但零命中：报告必须说出来。"""
        report = self._render(_make_result(news_result_count=0))

        self.assertIn(DISCLOSURE, report)
        self.assertIn("消息面", report)

    def test_stays_silent_when_search_was_not_performed(self):
        """未执行检索不是失败，不该报警——否则没配搜索渠道的用户每份报告都被吓一次。"""
        report = self._render(_make_result(news_result_count=None))

        self.assertNotIn(DISCLOSURE, report)

    def test_unchanged_when_news_is_available(self):
        """拿到新闻时行为与改动前一致：渲染正文，不出现提示。"""
        report = self._render(
            _make_result(news_summary="公司发布季度财报，营收同比增长。", news_result_count=3)
        )

        self.assertIn("公司发布季度财报", report)
        self.assertNotIn(DISCLOSURE, report)

    def test_disclosure_states_the_consequence_not_just_the_absence(self):
        """提示要说清后果，让读者知道结论该打几折，而不只是「没数据」。"""
        report = self._render(_make_result(news_result_count=0))

        self.assertIn("未纳入新闻维度证据", report)


class ResultFieldContractTestCase(unittest.TestCase):
    def test_result_defaults_to_none_not_zero(self):
        """默认必须是 None：默认成 0 会让所有未检索的报告都误报失败。"""
        result = _make_result()

        self.assertIsNone(result.news_result_count)


if __name__ == "__main__":
    unittest.main()
