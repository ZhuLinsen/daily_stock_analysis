# -*- coding: utf-8 -*-
"""新闻面为空时必须在报告里如实标注。

背景：消息面章节原先是「有内容才渲染」，检索一条没拿到时整段直接消失，
读报告的人无从判断是确实没新闻，还是检索静默失败了（搜索源限流、
未配置可用渠道等）。这会把「抓取失败」呈现成「确实没有新闻」，
比单纯的慢更容易误导结论。

这些用例锁住三个状态：
1. 未执行检索（count is None）时，说明未配置渠道且未纳入新闻面证据；
2. 检索执行了但为空（count == 0）时，保留原有零命中提示；
3. 正常拿到新闻（count > 0）时，不出现缺失提示。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.notification import NotificationService


ZERO_HIT_DISCLOSURE = "⚠️ 本次未获取到可用的新闻面数据，以下结论未纳入新闻维度证据。"
NO_CHANNEL_DISCLOSURE = "⚠️ 未配置搜索渠道，本次分析未纳入新闻面证据。"
EN_ZERO_HIT_DISCLOSURE = (
    "⚠️ No news data could be retrieved for this run; "
    "the conclusions below do not incorporate news-based evidence."
)
EN_NO_CHANNEL_DISCLOSURE = (
    "⚠️ No news search channel is configured; "
    "this analysis does not incorporate news-based evidence."
)
KO_ZERO_HIT_DISCLOSURE = (
    "⚠️ 이번 분석에서 사용 가능한 뉴스 데이터를 가져오지 못해 "
    "아래 결론에는 뉴스 근거를 반영하지 않았습니다."
)
KO_NO_CHANNEL_DISCLOSURE = (
    "⚠️ 뉴스 검색 채널이 설정되지 않아 이번 분석에는 "
    "뉴스 근거를 반영하지 않았습니다."
)


def _make_result(
    *,
    news_summary="",
    news_result_count=None,
    report_language="zh",
    news_evidence_present=False,
):
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
        report_language=report_language,
        news_summary=news_summary,
        news_result_count=news_result_count,
        news_evidence_present=news_evidence_present,
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

        self.assertIn(ZERO_HIT_DISCLOSURE, report)
        self.assertNotIn(NO_CHANNEL_DISCLOSURE, report)
        self.assertIn("消息面", report)

    def test_discloses_when_search_was_not_performed(self):
        """未配置搜索渠道时，报告必须说明新闻面证据没有纳入。"""
        report = self._render(_make_result(news_result_count=None))

        self.assertIn(NO_CHANNEL_DISCLOSURE, report)
        self.assertNotIn(ZERO_HIT_DISCLOSURE, report)

    def test_unchanged_when_news_is_available(self):
        """拿到新闻时行为与改动前一致：渲染正文，不出现提示。"""
        report = self._render(
            _make_result(news_summary="公司发布季度财报，营收同比增长。", news_result_count=3)
        )

        self.assertIn("公司发布季度财报", report)
        self.assertNotIn(ZERO_HIT_DISCLOSURE, report)
        self.assertNotIn(NO_CHANNEL_DISCLOSURE, report)

    def test_disclosure_states_the_consequence_not_just_the_absence(self):
        """提示要说清后果，让读者知道结论该打几折，而不只是「没数据」。"""
        report = self._render(_make_result(news_result_count=0))

        self.assertIn("未纳入新闻维度证据", report)


class ResultFieldContractTestCase(unittest.TestCase):
    def test_result_defaults_to_none_not_zero(self):
        """默认必须是 None，才能与执行后零命中使用不同披露文案。"""
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

        self.assertIn(ZERO_HIT_DISCLOSURE, report)

    def test_brief_report_discloses_empty_news(self):
        report = NotificationService.generate_brief_report(
            self.service, [_make_result(news_result_count=0)], report_date="2026-08-18"
        )

        self.assertIn(ZERO_HIT_DISCLOSURE, report)

    def test_single_stock_report_discloses_empty_news(self):
        report = NotificationService.generate_single_stock_report(
            self.service, _make_result(news_result_count=0)
        )

        self.assertIn(ZERO_HIT_DISCLOSURE, report)

    def test_renderers_disclose_when_search_not_performed(self):
        for name, call in (
            ("dashboard", lambda r: NotificationService.generate_dashboard_report(
                self.service, [r], report_date="2026-08-18")),
            ("brief", lambda r: NotificationService.generate_brief_report(
                self.service, [r], report_date="2026-08-18")),
            ("single", lambda r: NotificationService.generate_single_stock_report(
                self.service, r)),
        ):
            with self.subTest(renderer=name):
                report = call(_make_result(news_result_count=None))
                self.assertIn(NO_CHANNEL_DISCLOSURE, report)
                self.assertNotIn(ZERO_HIT_DISCLOSURE, report)


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

        self.assertIn(ZERO_HIT_DISCLOSURE, report)
        self.assertIn("市场情绪偏中性", report)


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
        self.assertIn(ZERO_HIT_DISCLOSURE, out)

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
        self.assertIn(ZERO_HIT_DISCLOSURE, out)

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
        self.assertIn(ZERO_HIT_DISCLOSURE, out)

    def test_templates_disclose_when_search_not_performed(self):
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
                self.assertIn(NO_CHANNEL_DISCLOSURE, out or "")
                self.assertNotIn(ZERO_HIT_DISCLOSURE, out or "")


class WechatDashboardDiscloseTestCase(unittest.TestCase):
    """generate_wechat_dashboard 是企业微信非 brief 场景的真实入口，
    pipeline 会直接调用它，此前完全没有接入披露。"""

    def setUp(self):
        self.service = _make_service()

    def test_wechat_dashboard_discloses_empty_news(self):
        out = NotificationService.generate_wechat_dashboard(
            self.service, [_make_result(news_result_count=0)]
        )
        self.assertIn(ZERO_HIT_DISCLOSURE, out)

    def test_wechat_dashboard_discloses_when_search_not_performed(self):
        out = NotificationService.generate_wechat_dashboard(
            self.service, [_make_result(news_result_count=None)]
        )
        self.assertIn(NO_CHANNEL_DISCLOSURE, out)
        self.assertNotIn(ZERO_HIT_DISCLOSURE, out)


class NoSearchProviderDisclosureTestCase(unittest.TestCase):
    """锁住 #2225 的 fresh-clone 场景：没有 key，公共实例默认关闭。"""

    def test_no_registered_providers_discloses_missing_news_evidence(self):
        from src.search_service import SearchService

        search_service = SearchService(searxng_public_instances_enabled=False)
        self.assertEqual([], search_service._providers)
        self.assertFalse(search_service.is_available)

        report = NotificationService.generate_daily_report(
            _make_service(), [_make_result(news_result_count=None)], report_date="2026-08-18"
        )
        self.assertIn(NO_CHANNEL_DISCLOSURE, report)
        self.assertNotIn(ZERO_HIT_DISCLOSURE, report)


class SupportedLanguageDisclosureTestCase(unittest.TestCase):
    """每种受支持报告语言都必须显式映射，不能把未知语言默认为中文。"""

    EXPECTED = {
        "zh": (NO_CHANNEL_DISCLOSURE, ZERO_HIT_DISCLOSURE),
        "en": (EN_NO_CHANNEL_DISCLOSURE, EN_ZERO_HIT_DISCLOSURE),
        "ko": (KO_NO_CHANNEL_DISCLOSURE, KO_ZERO_HIT_DISCLOSURE),
    }

    def setUp(self):
        self.service = _make_service()

    def _string_renderers(self, result):
        return {
            "daily": NotificationService.generate_daily_report(
                self.service, [result], report_date="2026-08-18"
            ),
            "dashboard": NotificationService.generate_dashboard_report(
                self.service, [result], report_date="2026-08-18"
            ),
            "brief": NotificationService.generate_brief_report(
                self.service, [result], report_date="2026-08-18"
            ),
            "single": NotificationService.generate_single_stock_report(
                self.service, result
            ),
            "wechat_dashboard": NotificationService.generate_wechat_dashboard(
                self.service, [result]
            ),
            "wechat_summary": NotificationService.generate_wechat_summary(
                self.service, [result]
            ),
        }

    def test_every_supported_language_is_used_by_string_renderers(self):
        from src.report_language import SUPPORTED_REPORT_LANGUAGES

        self.assertEqual(set(SUPPORTED_REPORT_LANGUAGES), set(self.EXPECTED))
        for language in SUPPORTED_REPORT_LANGUAGES:
            for count, expected_index in ((None, 0), (0, 1)):
                expected = self.EXPECTED[language][expected_index]
                result = _make_result(
                    news_result_count=count,
                    report_language=language,
                )
                for renderer, report in self._string_renderers(result).items():
                    with self.subTest(
                        language=language,
                        count=count,
                        renderer=renderer,
                    ):
                        self.assertIn(expected, report)
                        if language != "zh":
                            self.assertNotIn(NO_CHANNEL_DISCLOSURE, report)
                            self.assertNotIn(ZERO_HIT_DISCLOSURE, report)

    def test_every_supported_language_is_used_by_templates(self):
        from src.report_language import SUPPORTED_REPORT_LANGUAGES
        from src.services.report_renderer import render

        for language in SUPPORTED_REPORT_LANGUAGES:
            result = _make_result(news_result_count=0, report_language=language)
            for platform in ("markdown", "brief", "wechat"):
                for summary_only in (False, True):
                    with self.subTest(
                        language=language,
                        platform=platform,
                        summary_only=summary_only,
                    ):
                        out = render(
                            platform=platform,
                            results=[result],
                            report_date="2026-08-18",
                            summary_only=summary_only,
                            extra_context={"report_language": language},
                        )
                        self.assertIn(self.EXPECTED[language][1], out or "")
                        if language != "zh":
                            self.assertNotIn(ZERO_HIT_DISCLOSURE, out or "")

    def test_summary_only_string_renderers_keep_disclosure(self):
        self.service._report_summary_only = True
        result = _make_result(news_result_count=0)

        for renderer, report in (
            (
                "daily",
                NotificationService.generate_daily_report(
                    self.service, [result], report_date="2026-08-18"
                ),
            ),
            (
                "dashboard",
                NotificationService.generate_dashboard_report(
                    self.service, [result], report_date="2026-08-18"
                ),
            ),
            (
                "wechat",
                NotificationService.generate_wechat_dashboard(self.service, [result]),
            ),
        ):
            with self.subTest(renderer=renderer):
                self.assertIn(ZERO_HIT_DISCLOSURE, report)

    def test_unknown_language_fails_loudly(self):
        from src.services.empty_news import empty_news_disclosure

        with self.assertRaisesRegex(ValueError, "Unsupported report language"):
            empty_news_disclosure(_make_result(news_result_count=0), "future-language")


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

    def test_post_hoc_persistence_query_does_not_write_the_count(self):
        """分析结束后的补查只为持久化情报，绝不能回写计数。

        它发生在 executor.run() 之后，与 Agent 实际消费的证据无关；用它做披露
        判定会两个方向都失真（review OR-COR-5f5d7a2e）。真正的计数由
        src/agent/news_evidence.py 的证据作用域收集。
        """
        src = self._read_pipeline_source()
        idx = src.index("Agent 模式: 新闻情报已保存")
        window = src[max(0, idx - 1200) : idx]
        # 只看代码：解释这条约束的注释本身就含有该标识符。
        code_only = "\n".join(
            line for line in window.splitlines() if not line.strip().startswith("#")
        )

        self.assertNotIn("result.news_result_count", code_only)


class _StubSearchResult:
    def __init__(self, index):
        self.title = f"标题{index}"
        self.snippet = f"摘要{index}"
        self.url = f"https://example.invalid/{index}"
        self.source = "stub"
        self.published_date = "2026-08-20"


class _StubSearchResponse:
    def __init__(self, count, *, success=True, query="stub-query"):
        self.success = success
        self.results = [_StubSearchResult(i) for i in range(count)]
        self.query = query
        self.provider = "stub"
        self.error_message = None if success else "stub failure"


class _StubSearchService:
    """只实现搜索工具真正会用到的接口。

    intel_counts 是 Agent 通过 search_comprehensive_intel 实际拿到的证据，
    news_count 是 pipeline 事后为持久化而补打的 search_stock_news 的结果 ——
    两者刻意不同，用来证明披露跟随的是前者。
    """

    def __init__(self, *, intel_counts=None, news_count=0, news_success=True, available=True):
        self._intel_counts = intel_counts or {}
        self._news_count = news_count
        self._news_success = news_success
        self._available = available

    @property
    def is_available(self):
        return self._available

    def search_comprehensive_intel(self, stock_code, stock_name, max_searches=6):
        return {
            dimension: _StubSearchResponse(count)
            for dimension, count in self._intel_counts.items()
        }

    def format_intel_report(self, intel_results, stock_name):
        return "stub intel report"

    def search_stock_news(self, stock_code, stock_name, max_results=5):
        return _StubSearchResponse(self._news_count, success=self._news_success)


class AgentNewsEvidenceTestCase(unittest.TestCase):
    """Agent 模式的披露必须跟随 Agent 真正消费的新闻证据。

    曾经的缺口（review OR-COR-5f5d7a2e）：计数取自分析结束后补打的一次
    search_stock_news()。Agent 明明通过 search_comprehensive_intel 用了新闻，
    却可能因补查失败被标成「未纳入新闻面证据」；反过来 Agent 什么都没拿到，
    也可能因补查有结果而错误地不提示。
    """

    def setUp(self):
        from src.agent import news_evidence

        self.news_evidence = news_evidence
        token = news_evidence.activate_news_evidence_scope()
        self.accumulator = news_evidence.get_current_news_evidence()
        self.addCleanup(news_evidence.reset_news_evidence_scope, token)

    def _install_service(self, service):
        from unittest.mock import patch

        patcher = patch(
            "src.agent.tools.search_tools._get_search_service", return_value=service
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        db_patcher = patch("src.agent.tools.search_tools._get_db")
        db_patcher.start()
        self.addCleanup(db_patcher.stop)

    def test_agent_evidence_survives_a_failing_post_hoc_query(self):
        """Agent 用了 6 条新闻，事后补查零命中 —— 不得谎称未纳入新闻证据。"""
        from src.agent.tools.search_tools import _handle_search_comprehensive_intel

        service = _StubSearchService(
            intel_counts={"latest_news": 4, "risk_check": 2}, news_count=0
        )
        self._install_service(service)

        _handle_search_comprehensive_intel("600519", "测试标的")

        # pipeline 事后的持久化补查返回完全不同的结果，且不经过证据作用域
        post_hoc = service.search_stock_news("600519", "测试标的", max_results=5)
        self.assertEqual(0, len(post_hoc.results))

        self.assertEqual(6, self.accumulator.resolve(search_available=True))

    def test_agent_zero_hit_is_not_masked_by_a_successful_post_hoc_query(self):
        """反方向：Agent 一条没拿到，事后补查有结果 —— 提示不得被抑制。"""
        from src.agent.tools.search_tools import _handle_search_comprehensive_intel

        service = _StubSearchService(
            intel_counts={"latest_news": 0}, news_count=5
        )
        self._install_service(service)

        _handle_search_comprehensive_intel("600519", "测试标的")

        post_hoc = service.search_stock_news("600519", "测试标的", max_results=5)
        self.assertEqual(5, len(post_hoc.results))

        self.assertEqual(0, self.accumulator.resolve(search_available=True))

    def test_failed_agent_search_records_zero_rather_than_nothing(self):
        """检索发起但失败，是「搜过但没拿到」，不是「未配置渠道」。"""
        from src.agent.tools.search_tools import _handle_search_stock_news

        service = _StubSearchService(news_count=0, news_success=False)
        self._install_service(service)

        _handle_search_stock_news("600519", "测试标的")

        self.assertEqual(0, self.accumulator.resolve(search_available=True))

    def test_unavailable_channel_resolves_to_not_configured(self):
        """渠道不可用时工具直接返回错误、不记录，计数必须是 None。"""
        from src.agent.tools.search_tools import _handle_search_stock_news

        service = _StubSearchService(available=False)
        self._install_service(service)

        _handle_search_stock_news("600519", "测试标的")

        self.assertIsNone(self.accumulator.resolve(search_available=False))

    def test_available_channel_never_searched_reports_zero_hit_not_missing_channel(self):
        """渠道可用但 Agent 一次都没搜：仍是「没拿到新闻」，不能谎称未配置渠道。"""
        self.assertEqual(0, self.accumulator.resolve(search_available=True))

    def test_tool_threads_accumulate_into_the_parent_scope(self):
        """工具在线程池中执行，累加必须对 pipeline 可见。

        src/agent/runner.py 用 contextvars.copy_context() + pool.submit(ctx.run, ...)
        提交工具调用。ContextVar 里必须是可变累加器对象，换成不可变值父线程就读不到。
        """
        import contextvars
        from concurrent.futures import ThreadPoolExecutor

        record = self.news_evidence.record_news_evidence
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = []
            for count in (2, 0, 5):
                ctx = contextvars.copy_context()
                futures.append(pool.submit(ctx.run, record, count))
            for future in futures:
                future.result()

        self.assertEqual(7, self.accumulator.resolve(search_available=True))

    def test_recording_outside_a_scope_is_ignored(self):
        """报告页的后续资讯检索等场景不得影响本次分析的披露判定。"""
        token = self.news_evidence.activate_news_evidence_scope()
        outer = self.news_evidence.get_current_news_evidence()
        self.news_evidence.reset_news_evidence_scope(token)

        self.news_evidence.record_news_evidence(99)

        self.assertEqual(0, outer.resolve(search_available=True))


class NewsEvidenceSourcesTestCase(unittest.TestCase):
    """披露断言的是「结论有没有用到新闻面证据」，不是「搜索命中了几条」。

    `news_context` 由三路来源拼成，只有实时检索会产生计数：

    1. 实时多维检索 —— 更新 news_result_count
    2. 社交情绪（美股）—— 不更新计数
    3. 本地已落库的资讯池 —— 不更新计数

    只看计数就会把后两路参与的分析误报成「未纳入新闻面证据」
    （review OR-COR-2e4b9d61 点名了第 3 路；第 2 路是同一缺陷类，一并锁住）。
    """

    def _result(self, *, count, evidence):
        return _make_result(news_result_count=count, news_evidence_present=evidence)

    def test_local_intel_without_search_channel_is_not_reported_as_missing(self):
        """本地资讯池已进入分析输入，即使没配搜索渠道也不能说未纳入新闻证据。"""
        report = NotificationService.generate_daily_report(
            _make_service(),
            [self._result(count=None, evidence=True)],
            report_date="2026-08-20",
        )
        self.assertNotIn(NO_CHANNEL_DISCLOSURE, report)
        self.assertNotIn(ZERO_HIT_DISCLOSURE, report)

    def test_social_sentiment_without_search_hits_is_not_reported_as_missing(self):
        """社交情绪同样进入 news_context，零命中也不能否认已用证据。"""
        report = NotificationService.generate_daily_report(
            _make_service(),
            [self._result(count=0, evidence=True)],
            report_date="2026-08-20",
        )
        self.assertNotIn(ZERO_HIT_DISCLOSURE, report)
        self.assertNotIn(NO_CHANNEL_DISCLOSURE, report)

    def test_no_evidence_at_all_still_discloses_with_the_right_reason(self):
        """真的没有任何证据时，原有两种原因文案必须照旧。"""
        no_channel = NotificationService.generate_daily_report(
            _make_service(),
            [self._result(count=None, evidence=False)],
            report_date="2026-08-20",
        )
        zero_hit = NotificationService.generate_daily_report(
            _make_service(),
            [self._result(count=0, evidence=False)],
            report_date="2026-08-20",
        )
        self.assertIn(NO_CHANNEL_DISCLOSURE, no_channel)
        self.assertIn(ZERO_HIT_DISCLOSURE, zero_hit)

    def test_evidence_helper_registers_sources_one_by_one(self):
        from src.services.empty_news import news_evidence_present

        # 真实命中数 / 社交情绪 / 本地资讯池，任一为真即算有证据
        self.assertTrue(news_evidence_present(4, None, None))
        self.assertTrue(news_evidence_present(0, "reddit 讨论……", None))
        self.assertTrue(news_evidence_present(0, None, "## 本地资讯证据池"))
        self.assertFalse(news_evidence_present(0, None, None))
        self.assertFalse(news_evidence_present(0, "", "   \n\t "))
        self.assertFalse(news_evidence_present(None, None, None))

    def test_zero_hit_placeholder_report_is_not_mistaken_for_evidence(self):
        """零命中时 format_intel_report 仍吐占位文本，绝不能被当成证据。

        这是真实反例（review OR-COR-8f4c2d1b）：`format_intel_report()` 即使所有
        维度都失败，也会输出「【XX 情报搜索结果】」标题和每个维度的「未找到相关
        信息」，整段永远非空。曾经的实现把整段 news_context 传进判定函数，于是
        「搜了但一条没拿到」被翻成「有证据」，恰好吞掉本 PR 要补的那条披露。
        这里用真实函数产出反例，不用 mock。
        """
        from src.search_service import SearchService
        from src.services.empty_news import news_evidence_present

        class _FailedResponse:
            success = False
            results = []
            provider = "stub"

        service = SearchService.__new__(SearchService)
        placeholder = SearchService.format_intel_report(
            service,
            {"latest_news": _FailedResponse(), "risk_check": _FailedResponse()},
            "测试标的",
        )

        # 前提：这段占位文本确实非空，否则这条反例就失去意义
        self.assertTrue(placeholder.strip())
        self.assertIn("未找到相关信息", placeholder)

        # 按来源登记：实时 0 条、无社交、无本地资讯池 —— 必须判定为没有证据
        self.assertFalse(news_evidence_present(0, None, None))

        # 端到端：这种情况报告必须出现零命中披露
        report = NotificationService.generate_daily_report(
            _make_service(),
            [_make_result(news_result_count=0, news_evidence_present=False)],
            report_date="2026-08-21",
        )
        self.assertIn(ZERO_HIT_DISCLOSURE, report)

    def test_stored_record_round_trips_the_evidence_flag(self):
        from src.services.empty_news import (
            empty_news_disclosure_from_stored,
            persisted_news_evidence_present,
        )

        stored = self._result(count=None, evidence=True).to_dict()
        self.assertIn("news_evidence_present", stored)
        self.assertTrue(persisted_news_evidence_present(stored, None))
        self.assertIsNone(empty_news_disclosure_from_stored(stored, None, "zh"))

    def test_legacy_record_without_the_flag_keeps_its_original_behaviour(self):
        """旧记录没有该字段时按计数推断，不追溯改变当时的报告表现。"""
        from src.services.empty_news import persisted_news_evidence_present

        self.assertTrue(persisted_news_evidence_present({"news_result_count": 4}, 4))
        self.assertFalse(persisted_news_evidence_present({"news_result_count": 0}, 0))

    def test_pipeline_registers_sources_and_never_passes_the_whole_context(self):
        """两条 pipeline 路径都必须按来源登记，且都不许传拼好的整段 news_context。

        源码断言：谁把整段 news_context 交回判定函数，本用例就会失败——那正是
        零命中占位文本冒充证据的入口。
        """
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "src" / "core" / "pipeline.py").read_text(
            encoding="utf-8"
        )
        code_only = "\n".join(
            line for line in src.splitlines() if not line.strip().startswith("#")
        )

        calls = code_only.count("result.news_evidence_present = news_evidence_present(")
        self.assertEqual(2, calls, "普通路径与 Agent 路径各要有一次登记")

        # 三路来源都要出现在登记参数里
        self.assertIn("social_evidence_context", code_only)
        self.assertIn("persisted_intelligence_context", code_only)

        # 整段 news_context 不许再被交给判定函数
        self.assertNotIn("news_evidence_present(\n                        news_context", code_only)
        self.assertNotIn("news_evidence_present(news_context", code_only)
        self.assertNotIn('news_evidence_present(\n                    initial_context.get("news_context")', code_only)


if __name__ == "__main__":
    unittest.main()
