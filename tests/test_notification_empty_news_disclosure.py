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


def _make_service():
    """造一个用于渲染的 NotificationService。

    走真实 __init__ 以拿到全部渲染所需属性；本测试只读取返回的报告文本，
    不调用任何推送方法，因此不会向外发送。
    """
    return NotificationService()


class EmptyNewsDisclosureTestCase(unittest.TestCase):
    def setUp(self):
        self.service = _make_service()

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


class ActiveRenderersDiscloseTestCase(unittest.TestCase):
    """真实流程走的是 dashboard / brief / single_stock，不是 generate_daily_report。

    只在 generate_daily_report 里加提示等于没加——标准 REPORT_TYPE 一个都覆盖不到。
    这些用例锁住四个渲染器全部接入同一个共享判定。
    """

    def setUp(self):
        self.service = _make_service()

    def test_dashboard_report_discloses_empty_news(self):
        report = NotificationService.generate_dashboard_report(
            self.service, [_make_result(news_result_count=0)], report_date="2026-08-18"
        )

        self.assertIn(DISCLOSURE, report)

    def test_brief_report_discloses_empty_news(self):
        report = NotificationService.generate_brief_report(
            self.service, [_make_result(news_result_count=0)], report_date="2026-08-18"
        )

        self.assertIn(DISCLOSURE, report)

    def test_single_stock_report_discloses_empty_news(self):
        report = NotificationService.generate_single_stock_report(
            self.service, _make_result(news_result_count=0)
        )

        self.assertIn(DISCLOSURE, report)

    def test_renderers_stay_silent_when_search_not_performed(self):
        for name, call in (
            ("dashboard", lambda r: NotificationService.generate_dashboard_report(
                self.service, [r], report_date="2026-08-18")),
            ("brief", lambda r: NotificationService.generate_brief_report(
                self.service, [r], report_date="2026-08-18")),
            ("single", lambda r: NotificationService.generate_single_stock_report(
                self.service, r)),
        ):
            with self.subTest(renderer=name):
                self.assertNotIn(DISCLOSURE, call(_make_result(news_result_count=None)))


class DisclosureIndependentOfModelTextTestCase(unittest.TestCase):
    """最糟的组合：检索零命中，但模型仍按 schema 写出了情绪判断。

    此时若以「消息面文字是否为空」决定是否提示，报告会展示模型生成的情绪，
    同时隐瞒没有新闻证据这一事实。判定必须独立于模型输出。
    """

    def setUp(self):
        self.service = _make_service()

    def test_warns_even_when_model_supplied_sentiment(self):
        result = _make_result(news_result_count=0)
        result.market_sentiment = "市场情绪偏中性。"
        result.hot_topics = "暂无明显热点。"

        report = NotificationService.generate_daily_report(
            self.service, [result], report_date="2026-08-18"
        )

        self.assertIn(DISCLOSURE, report)
        self.assertIn("市场情绪偏中性", report)



if __name__ == "__main__":
    unittest.main()


class TemplateRendererDiscloseTestCase(unittest.TestCase):
    """REPORT_RENDERER_ENABLED=true 时走模板链路，会在 render() 处提前返回。

    此前只修了字符串拼接分支，模板链路一路沉默——同一份分析结果在部分渠道
    披露、在另一些渠道不披露，跨渠道事实呈现不一致。
    """

    def setUp(self):
        self.service = _make_service()

    def _render_with_templates(self, method, result, platform_hint=""):
        from unittest.mock import patch
        from src.config import get_config

        cfg = get_config()
        with patch.object(type(cfg), "report_renderer_enabled", True, create=True):
            return method(self.service, [result], report_date="2026-08-18")

    def test_markdown_template_discloses_empty_news(self):
        from src.services.report_renderer import render

        out = render(
            platform="markdown",
            results=[_make_result(news_result_count=0)],
            report_date="2026-08-18",
            summary_only=False,
            extra_context={"report_language": "zh"},
        )
        self.assertTrue(out)
        self.assertIn(DISCLOSURE, out)

    def test_brief_template_discloses_empty_news(self):
        from src.services.report_renderer import render

        out = render(
            platform="brief",
            results=[_make_result(news_result_count=0)],
            report_date="2026-08-18",
            summary_only=False,
            extra_context={"report_language": "zh"},
        )
        self.assertTrue(out)
        self.assertIn(DISCLOSURE, out)

    def test_wechat_template_discloses_empty_news(self):
        from src.services.report_renderer import render

        out = render(
            platform="wechat",
            results=[_make_result(news_result_count=0)],
            report_date="2026-08-18",
            summary_only=False,
            extra_context={"report_language": "zh"},
        )
        self.assertTrue(out)
        self.assertIn(DISCLOSURE, out)

    def test_templates_stay_silent_when_search_not_performed(self):
        from src.services.report_renderer import render

        for platform in ("markdown", "brief", "wechat"):
            with self.subTest(platform=platform):
                out = render(
                    platform=platform,
                    results=[_make_result(news_result_count=None)],
                    report_date="2026-08-18",
                    summary_only=False,
                    extra_context={"report_language": "zh"},
                )
                self.assertNotIn(DISCLOSURE, out or "")


class WechatDashboardDiscloseTestCase(unittest.TestCase):
    """generate_wechat_dashboard 是企业微信非 brief 场景的真实入口，
    pipeline 会直接调用它，此前完全没有接入披露。"""

    def setUp(self):
        self.service = _make_service()

    def test_wechat_dashboard_discloses_empty_news(self):
        out = NotificationService.generate_wechat_dashboard(
            self.service, [_make_result(news_result_count=0)]
        )
        self.assertIn(DISCLOSURE, out)

    def test_wechat_dashboard_silent_when_search_not_performed(self):
        out = NotificationService.generate_wechat_dashboard(
            self.service, [_make_result(news_result_count=None)]
        )
        self.assertNotIn(DISCLOSURE, out)


class PipelineCountSemanticsTestCase(unittest.TestCase):
    """计数的三态语义必须在 pipeline 侧就正确产生，否则展示层再周全也无用。

    两个曾经的缺口：
    1. 搜索服务整体失败（intel_results 为空）时计数停留在 None，
       于是「所有搜索源全线失败」这一最该提示的场景反而不提示；
    2. Agent 模式（_analyze_with_agent）自行检索却从不记录计数，
       该路径下零命中永远静默。
    """

    def _read_pipeline_source(self):
        from pathlib import Path

        return (Path(__file__).resolve().parents[1] / "src" / "core" / "pipeline.py").read_text(
            encoding="utf-8"
        )

    def test_count_set_to_zero_once_search_is_attempted(self):
        """检索一旦发起就置 0，不能等到拿到结果对象才赋值。"""
        src = self._read_pipeline_source()
        idx = src.index("开始多维度情报搜索")
        window = src[idx : idx + 600]

        self.assertIn("news_result_count = 0", window)
        self.assertLess(
            window.index("news_result_count = 0"),
            window.index("search_comprehensive_intel"),
            "计数必须在发起检索之前置 0，否则整体失败时会落回 None",
        )

    def test_agent_path_records_count(self):
        """Agent 模式自行检索后必须回写计数。"""
        src = self._read_pipeline_source()
        idx = src.index("Agent 模式: 新闻情报已保存")
        window = src[max(0, idx - 1200) : idx]

        self.assertIn("result.news_result_count", window)
