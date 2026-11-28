# -*- coding: utf-8 -*-
"""Issue #1584: 大盘复盘结构化字段（summary / index comment / divergence / style_rotation / catalysts / next_day_plan）。

覆盖目标：
1. LLM 输出的结构化附录（fenced JSON）可被提取并从 Markdown 中剥离；
2. 附录畸形/缺失时逐字段降级，绝不中断复盘；
3. payload 新增字段全部可选，旧消费者/旧记录渲染零差异；
4. breadth.divergence_diagnosis 的确定性兜底组装。
"""

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core.market_profile import CN_PROFILE, JP_PROFILE, US_PROFILE
from src.core.market_strategy import get_market_strategy_blueprint
from src.core.market_review import _render_market_review_payload_markdown
from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview
from src.storage import DatabaseManager


def _make_analyzer(region="cn", profile=None, report_text="复盘报告"):
    """Mirror the factory used by test_market_analyzer_generate_text.py."""
    with patch("src.analyzer.get_config") as mock_cfg, \
         patch("src.market_analyzer.get_config") as mock_cfg2:
        cfg = MagicMock()
        cfg.litellm_model = "gemini/gemini-2.0-flash"
        cfg.litellm_fallback_models = []
        cfg.gemini_api_keys = ["sk-gemini-testkey-1234"]
        cfg.anthropic_api_keys = []
        cfg.openai_api_keys = []
        cfg.deepseek_api_keys = []
        cfg.llm_model_list = []
        cfg.openai_base_url = None
        cfg.market_review_region = region
        cfg.market_review_color_scheme = "green_up"
        cfg.report_language = "zh"
        cfg.generation_backend = "litellm"
        cfg.generation_fallback_backend = "litellm"
        mock_cfg.return_value = cfg
        mock_cfg2.return_value = cfg

        from src.analyzer import GeminiAnalyzer

        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer._router = None
        analyzer._litellm_available = True
        analyzer._config_override = cfg
        analyzer.get_generation_backend_identity = MagicMock(
            return_value=("litellm", cfg.litellm_model)
        )
        analyzer.generate_text_with_metadata = MagicMock(
            return_value=SimpleNamespace(
                text=report_text,
                provider="litellm",
                model=cfg.litellm_model,
                backend="litellm",
            )
        )

        ma = MarketAnalyzer.__new__(MarketAnalyzer)
        ma.analyzer = analyzer
        ma.config = cfg
        ma.profile = profile if profile is not None else CN_PROFILE
        ma.strategy = get_market_strategy_blueprint(region)
        ma.region = region
        # 端到端路径（_run_daily_review_parts）使用固定 overview，避免触网。
        ma.get_market_overview = MagicMock(return_value=_cn_overview())
        ma.search_market_news = MagicMock(return_value=[])
        ma._merge_persisted_market_intelligence = MagicMock(side_effect=lambda news: news)
        return ma


def _cn_overview(**overrides):
    base = dict(
        date="2026-06-05",
        indices=[
            MarketIndex(code="000001", name="上证指数", current=3372.4, change_pct=0.9),
            MarketIndex(code="399006", name="创业板指", current=2044.1, change_pct=0.7),
        ],
        up_count=1500,
        down_count=3600,
        flat_count=200,
        limit_up_count=28,
        limit_down_count=9,
        total_amount=11400.0,
    )
    base.update(overrides)
    return MarketOverview(**base)


def _appendix_report(body: dict) -> str:
    markdown = (
        "## 2026-06-05 A股大盘复盘\n\n"
        "> 权重护盘、成长杀跌。\n\n"
        "### 一、盘面总览\n"
        "市场震荡分化。\n"
    )
    if body is None:
        return markdown
    return markdown + "\n---\n\n```json\n" + json.dumps(body, ensure_ascii=False) + "\n```\n"


FULL_APPENDIX = {
    "summary": {
        "temperature": 45,
        "market_status": "震荡分化",
        "position_advice": "0-3成",
        "core_conclusion": "权重护盘、成长杀跌，风险偏好回落",
    },
    "indices": [
        {
            "code": "000001",
            "ma_status": {"ma5": "above", "ma10": "below", "ma20": "above"},
            "comment": "上证受MA10压制",
        },
        {
            "code": "399006",
            "ma_status": {"ma5": "below", "ma10": "below", "ma20": "below"},
            "comment": "",
        },
    ],
    "breadth": {"divergence_diagnosis": "指数微涨但下跌家数占优，权重护盘特征明显"},
    "style_rotation": {"signal": "成长→防御", "comment": "银行煤炭获避险资金"},
    "catalysts": [
        {
            "title": "美联储议息",
            "direction": "bearish",
            "scope": "全球风险资产",
            "persistence": "短期",
            "digested": False,
        },
        {
            "title": "国产算力订单落地",
            "direction": "bullish",
            "scope": "AI算力链",
            "persistence": "中期",
            "digested": True,
        },
    ],
    "next_day_plan": {
        "watchlist": ["上证3350支撑", "成交额能否回到1.2万亿"],
        "position_advice": "维持0-3成，等待宽度修复",
        "invalidation": "若上证放量收复MA10则可加至4-5成",
    },
    "cross_market_note": "隔夜美股纳指期货走弱，明日开盘承压概率较高",
}


class TestStructuredAppendixExtraction:
    def test_extracts_and_strips_fenced_json_appendix(self):
        ma = _make_analyzer()
        report = _appendix_report(FULL_APPENDIX)

        cleaned, data = ma._extract_structured_market_review_appendix(report)

        assert "```json" not in cleaned
        assert "### 一、盘面总览" in cleaned
        assert cleaned.rstrip().endswith("市场震荡分化。")
        assert data == FULL_APPENDIX

    def test_returns_original_text_when_appendix_is_malformed(self):
        ma = _make_analyzer()
        report = "## 报告\n\n正文。\n\n```json\n{not-valid-json}\n```"

        cleaned, data = ma._extract_structured_market_review_appendix(report)

        assert cleaned == report
        assert data is None

    def test_returns_original_text_without_appendix(self):
        ma = _make_analyzer()
        report = _appendix_report(None)

        cleaned, data = ma._extract_structured_market_review_appendix(report)

        assert cleaned == report
        assert data is None

    def test_ignores_fenced_block_without_known_keys(self):
        ma = _make_analyzer()
        report = "正文\n\n```json\n{\"unrelated\": true}\n```"

        cleaned, data = ma._extract_structured_market_review_appendix(report)

        assert cleaned == report
        assert data is None

    def test_deeply_nested_appendix_json_keeps_markdown_body(self):
        """超深嵌套附录 JSON 触发 RecursionError 时，已生成的 Markdown 正文必须保留。

        修复前 json.loads 抛出的 RecursionError 未被 _parse_market_review_json_candidate
        捕获，会从附录提取一路抛到 _run_daily_review_parts，整份复盘崩溃。
        """
        deep = "null"
        for _ in range(5000):
            deep = "[" + deep + "]"
        report = (
            "## 2026-06-05 A股大盘复盘\n\n### 一、盘面总览\n市场震荡分化。\n\n"
            "```json\n{\"summary\": " + deep + "}\n```\n"
        )
        ma = _make_analyzer(report_text="复盘")

        cleaned, data = ma._extract_structured_market_review_appendix(report)

        assert "### 一、盘面总览" in cleaned, cleaned[:200]
        assert data is None


class TestPayloadStructuredFields:
    def test_full_appendix_populates_all_new_payload_fields(self):
        ma = _make_analyzer(report_text=_appendix_report(FULL_APPENDIX))

        result = ma._run_daily_review_parts()
        payload = result.structured_payload

        # 附录从对外 Markdown 中剥离
        assert "```json" not in result.report
        assert "### 一、盘面总览" in result.report

        assert payload["summary"] == FULL_APPENDIX["summary"]
        # OR-COR-91e5bc73：指数行情与 Prompt 均未提供均线/历史收盘价，模型回传的 ma_status
        # 属未验证推断——即使模型照旧模板返回，后端也不得接受并写入 payload。
        assert "ma_status" not in payload["indices"][0], payload["indices"][0]
        assert "ma_status" not in payload["indices"][1], payload["indices"][1]
        assert payload["indices"][0]["comment"] == "上证受MA10压制"
        assert "comment" not in payload["indices"][1]
        # LLM 诊断优先于确定性兜底
        assert (
            payload["breadth"]["divergence_diagnosis"]
            == "指数微涨但下跌家数占优，权重护盘特征明显"
        )
        assert payload["style_rotation"] == FULL_APPENDIX["style_rotation"]
        assert payload["catalysts"] == FULL_APPENDIX["catalysts"]
        assert payload["next_day_plan"] == {
            **FULL_APPENDIX["next_day_plan"],
            "notes": None,
        }
        assert payload["cross_market_note"] == FULL_APPENDIX["cross_market_note"]
        # 旧字段保持不变
        assert payload["breadth"]["up_count"] == 1500
        assert payload["indices"][0]["name"] == "上证指数"

    def test_malformed_appendix_degrades_without_new_fields(self):
        ma = _make_analyzer(report_text="## 报告\n\n```json\n{broken\n```")

        result = ma._run_daily_review_parts()
        payload = result.structured_payload

        assert "summary" not in payload
        assert "catalysts" not in payload
        assert "style_rotation" not in payload
        assert "next_day_plan" not in payload
        assert "cross_market_note" not in payload
        assert "ma_status" not in payload["indices"][0]
        # 确定性分化诊断仍然兜底
        assert "背离" in payload["breadth"]["divergence_diagnosis"]

    def test_partial_fields_degrade_per_field(self):
        partial = {
            "summary": {"temperature": "not-a-number", "market_status": "震荡分化"},
            "catalysts": "should-be-a-list",
            "indices": [{"code": "000001", "ma_status": {"ma5": "nonsense"}}],
        }
        ma = _make_analyzer(report_text=_appendix_report(partial))
        light_score = ma.build_market_light_snapshot(_cn_overview())["score"]

        result = ma._run_daily_review_parts()
        payload = result.structured_payload

        assert payload["summary"]["market_status"] == "震荡分化"
        assert payload["summary"]["temperature"] == light_score  # 兜底：light score
        assert payload["summary"]["position_advice"] is None
        assert payload["summary"]["core_conclusion"] is None
        assert "catalysts" not in payload
        assert "ma_status" not in payload["indices"][0]

    def test_injected_sector_fallback_survives_appendix_extraction(self):
        """OR-COR-b33fa541：附录在末尾且无板块标题时，注入到 fence 之后的兜底表不得被剥离截断。"""
        overview = _cn_overview(
            top_sectors=[{"name": "半导体", "change_pct": 3.25}],
            bottom_sectors=[{"name": "煤炭", "change_pct": -1.12}],
            top_concepts=[{"name": "AI算力", "change_pct": 5.4}],
            bottom_concepts=[{"name": "转基因", "change_pct": -2.05}],
        )
        ma = _make_analyzer(report_text=_appendix_report({"summary": {"temperature": 45}}))
        ma.get_market_overview = MagicMock(return_value=overview)

        result = ma._run_daily_review_parts()

        # 附录 fence 已剥离，但 fence 之后注入的兜底板块/概念表必须完整保留。
        assert "```json" not in result.report
        assert "### 三、板块主线" in result.report
        assert "行业板块领涨 Top 5" in result.report
        assert "概念板块领涨 Top 5" in result.report
        assert "AI算力" in result.report
        assert "AI算力" in result.structured_payload["markdown_report"]

    def test_all_null_summary_still_falls_back_to_light_score(self):
        """OR-COR-29db920d：summary 全字段为 null 被归一化丢弃时，temperature 仍回落到市场亮灯分。"""
        appendix = {
            "summary": {
                "temperature": None,
                "market_status": None,
                "position_advice": None,
                "core_conclusion": None,
            }
        }
        ma = _make_analyzer(report_text=_appendix_report(appendix))
        light_score = ma.build_market_light_snapshot(_cn_overview())["score"]

        payload = ma._run_daily_review_parts().structured_payload

        assert payload["summary"]["temperature"] == light_score
        assert payload["summary"]["market_status"] is None
        assert payload["summary"]["position_advice"] is None
        assert payload["summary"]["core_conclusion"] is None

    def test_overflowing_temperature_string_degrades_per_field(self):
        """OR-COR-754e4921：temperature="1e309"（合法 JSON 字符串）触发 OverflowError 时，
        仅温度走降级路径，兄弟结构化字段（market_status/indices/catalysts/next_day_plan）必须保留。"""
        appendix = {
            "summary": {
                "temperature": "1e309",
                "market_status": "震荡分化",
                "position_advice": "0-3成防守",
                "core_conclusion": "指数弱势整理，等待宽度修复",
            },
            "indices": [
                {"code": "000001", "ma_status": {"ma5": "above"}, "comment": "上证站上MA5"},
            ],
            "catalysts": [{"title": "降准落地", "direction": "利好"}],
            "next_day_plan": {"position_advice": "控制仓位", "invalidation": "跌破3300"},
        }
        ma = _make_analyzer(report_text=_appendix_report(appendix))
        light_score = ma.build_market_light_snapshot(_cn_overview())["score"]

        result = ma._run_daily_review_parts()
        payload = result.structured_payload

        # 修复前：温度 OverflowError 吞掉整包 → 全部兄弟字段丢失
        assert payload["summary"]["market_status"] == "震荡分化"
        assert payload["summary"]["position_advice"] == "0-3成防守"
        assert payload["summary"]["core_conclusion"] == "指数弱势整理，等待宽度修复"
        assert payload["summary"]["temperature"] == light_score  # 降级：亮灯分兜底
        assert "ma_status" not in payload["indices"][0]  # OR-COR-91e5bc73：无均线输入支撑，丢弃
        assert payload["indices"][0]["comment"] == "上证站上MA5"
        assert payload["catalysts"][0]["title"] == "降准落地"
        assert payload["catalysts"][0]["direction"] == "bullish"
        assert payload["next_day_plan"]["position_advice"] == "控制仓位"
        assert payload["next_day_plan"]["invalidation"] == "跌破3300"

    def test_overflowing_temperature_numeric_json_bigint_degrades_per_field(self):
        """OR-COR-754e4921 补充：数值型 JSON 大数温度同样只降级该字段，不拖垮兄弟字段。"""
        appendix = {
            "summary": {
                "temperature": 10**400,
                "market_status": "普涨回暖",
            },
            "catalysts": [{"title": "两会政策预期", "direction": "bullish"}],
        }
        ma = _make_analyzer(report_text=_appendix_report(appendix))
        light_score = ma.build_market_light_snapshot(_cn_overview())["score"]

        payload = ma._run_daily_review_parts().structured_payload

        assert payload["summary"]["market_status"] == "普涨回暖"
        assert payload["summary"]["temperature"] == light_score
        assert payload["catalysts"][0]["title"] == "两会政策预期"

    def test_catalyst_direction_and_digested_localized_values_are_normalized(self):
        partial = {
            "catalysts": [
                {"title": "降准落地", "direction": "利好", "digested": "是", "scope": "全市场", "persistence": "中期"},
                {"title": "外围大跌", "direction": "利空", "digested": "否"},
                {"title": "中性事件", "direction": "中性"},
                {"direction": "bullish"},  # 无 title，丢弃
                {"title": "方向未知", "direction": "unsure"},
            ],
        }
        ma = _make_analyzer(report_text=_appendix_report(partial))

        result = ma._run_daily_review_parts()
        catalysts = result.structured_payload["catalysts"]

        assert len(catalysts) == 4
        assert catalysts[0]["direction"] == "bullish"
        assert catalysts[0]["digested"] is True
        assert catalysts[1]["direction"] == "bearish"
        assert catalysts[1]["digested"] is False
        assert catalysts[2]["direction"] == "neutral"
        assert catalysts[2]["digested"] is None
        assert catalysts[3]["title"] == "方向未知"
        assert catalysts[3]["direction"] is None

    def test_index_annotation_drops_ma_status_and_ignores_unknown_codes(self):
        """OR-COR-91e5bc73：附录仍带回 ma_status 时后端一律丢弃；未知 code 的点评不落地。"""
        partial = {
            "indices": [
                {"code": "999999", "ma_status": {"ma5": "above"}, "comment": "未知指数"},
                {"code": "000001", "ma_status": {"ma5": "above", "ma10": "hover", "ma20": "below"}},
            ],
        }
        ma = _make_analyzer(report_text=_appendix_report(partial))

        result = ma._run_daily_review_parts()
        indices = result.structured_payload["indices"]

        assert len(indices) == 2
        # 未知 code 不落地
        assert "ma_status" not in indices[1]
        assert "comment" not in indices[1]
        assert indices[0]["name"] == "上证指数"
        # 指数行情没有均线输入：无论取值是否合法，ma_status 都不得进入 payload
        assert "ma_status" not in indices[0], indices[0]
        assert "comment" not in indices[0]

    def test_us_market_without_breadth_still_carries_llm_fields(self):
        ma = _make_analyzer(
            region="us",
            profile=US_PROFILE,
            report_text=_appendix_report(
                {
                    "summary": {"market_status": "index-strong-stock-weak"},
                    "indices": [{"code": "SPX", "ma_status": {"ma5": "above"}}],
                }
            ),
        )
        ma.config.report_language = "en"
        overview = MarketOverview(
            date="2026-06-05",
            indices=[MarketIndex(code="SPX", name="S&P 500", current=5200.0, change_pct=0.6)],
        )
        ma.get_market_overview = MagicMock(return_value=overview)

        result = ma._run_daily_review_parts()
        payload = result.structured_payload

        assert "breadth" not in payload
        assert payload["summary"]["market_status"] == "index-strong-stock-weak"
        # OR-COR-91e5bc73：仅有当日行情、无任何均线输入，模型回传的 ma_status 必须丢弃
        assert "ma_status" not in payload["indices"][0], payload["indices"][0]

    def test_appendix_only_response_keeps_parsed_fields_with_template_body(self):
        """OR-COR-6c30b83b：模型只返回有效附录（无正文/章节标题）时，不得丢弃整份复盘。

        修复前：generate_market_review 将非空模型响应判为成功，附录剥离后正文为空；
        美股无行业排行兜底块、指数表也找不到可注入的标题，外层编排（market_review.py
        ``if review_report:`` / analysis.py ``if not report: raise``）随之丢弃整份结果，
        已解析的 summary 等结构化字段一并丢失。修复后回填模板报告并保留已解析字段。
        """
        appendix = json.dumps(
            {
                "summary": {
                    "temperature": 42,
                    "market_status": "appendix-only",
                    "position_advice": "1-2成",
                    "core_conclusion": "指数缩量整理",
                },
                "indices": [{"code": "SPX", "comment": "缩量整理"}],
            },
            ensure_ascii=False,
        )
        ma = _make_analyzer(region="us", profile=US_PROFILE, report_text=f"```json\n{appendix}\n```")
        ma.config.report_language = "en"
        overview = MarketOverview(
            date="2026-06-05",
            indices=[MarketIndex(code="SPX", name="S&P 500", current=5200.0, change_pct=0.6)],
        )
        ma.get_market_overview = MagicMock(return_value=overview)

        result = ma._run_daily_review_parts()

        assert result.report.strip(), "附录剥离后正文为空，整份复盘被丢弃"
        assert result.structured_payload["summary"]["market_status"] == "appendix-only", result.structured_payload.get("summary")
        assert result.structured_payload["summary"]["temperature"] == 42
        assert result.structured_payload["indices"][0]["comment"] == "缩量整理"


class TestIndexCommentMapping:
    """OR-COR-f4725a90：Prompt 必须携带指数内部代码；消费端兼容行情符号别名与名称回退。

    内部代码取自真实数据源（data_provider/yfinance_fetcher.py、efinance_fetcher.py、
    us_index_mapping.py），不再在 fixture 里预填“恰好能匹配”的代码。
    """

    @staticmethod
    def _jp_overview():
        return MarketOverview(
            date="2026-06-05",
            indices=[
                MarketIndex(code="N225", name="日经225", current=40000.0, change_pct=0.5),
                MarketIndex(code="TOPX", name="东证指数", current=2800.0, change_pct=-0.2),
            ],
        )

    @staticmethod
    def _analyzer(region, profile, appendix, overview, language="zh"):
        ma = _make_analyzer(region=region, profile=profile, report_text=_appendix_report(appendix))
        ma.config.report_language = language
        ma.get_market_overview = MagicMock(return_value=overview)
        return ma

    def test_zh_prompt_index_input_carries_internal_code(self):
        ma = self._analyzer("jp", JP_PROFILE, None, self._jp_overview())

        prompt = ma._build_review_prompt(self._jp_overview(), [])

        # 修复前仅输出“- 日经225: 40000.00 (↑0.50%)”，模型无从得知内部代码 N225
        assert "- 日经225 (N225): 40000.00 (↑0.50%)" in prompt, "主要指数输入未携带内部代码"
        assert "- 东证指数 (TOPX): 2800.00 (↓0.20%)" in prompt
        assert "原样" in prompt, "附录未要求模型原样回传内部代码"
        assert '"name"' in prompt, "附录未要求回传指数名称（名称回退的前提）"

    def test_en_prompt_index_input_carries_internal_code(self):
        ma = self._analyzer("jp", JP_PROFILE, None, self._jp_overview(), language="en")

        prompt = ma._build_review_prompt(self._jp_overview(), [])

        assert "- 日经225 (N225): 40000.00 (↑0.50%)" in prompt, "index input lacks the internal code"
        assert "verbatim" in prompt.lower(), "appendix does not ask for the code to be echoed verbatim"
        assert '"name"' in prompt

    def test_yahoo_caret_symbol_keeps_comment(self):
        """模型按常见行情符号回传 ^N225 且省略 name 时，点评不得静默丢失。"""
        comment = "日经站上四万点心理关口"
        ma = self._analyzer(
            "jp", JP_PROFILE, {"indices": [{"code": "^N225", "comment": comment}]}, self._jp_overview()
        )

        payload = ma._run_daily_review_parts().structured_payload

        assert payload["indices"][0]["comment"] == comment, payload["indices"][0]
        assert "comment" not in payload["indices"][1]

    def test_quote_symbol_aliases_match_internal_codes(self):
        overview = MarketOverview(
            date="2026-06-05",
            indices=[
                MarketIndex(code="sh000001", name="上证指数", current=3372.4, change_pct=0.9),
                MarketIndex(code="sz399001", name="深证成指", current=10200.0, change_pct=-0.3),
                MarketIndex(code="SPX", name="标普500指数", current=5200.0, change_pct=0.6),
                MarketIndex(code="HSCEI", name="国企指数", current=7000.0, change_pct=0.2),
            ],
        )
        ma = _make_analyzer(report_text="复盘")
        llm_structured = {
            "indices": [
                {"code": "000001.SH", "comment": "权重护盘"},
                {"code": "SZ399001", "comment": "中小盘走弱"},
                {"code": "^GSPC", "comment": "缩量创新高"},
                {"code": "^HSCE", "comment": "随恒指回升"},
            ]
        }

        payload = ma.build_market_review_payload(overview, [], "复盘报告", llm_structured=llm_structured)

        comments = {idx["name"]: idx.get("comment") for idx in payload["indices"]}
        assert comments == {
            "上证指数": "权重护盘",
            "深证成指": "中小盘走弱",
            "标普500指数": "缩量创新高",
            "国企指数": "随恒指回升",
        }

    def test_name_fallback_when_code_cannot_be_matched(self):
        overview = MarketOverview(
            date="2026-06-05",
            indices=[
                MarketIndex(code="SPX", name="标普500指数", current=5200.0, change_pct=0.6),
                MarketIndex(code="IXIC", name="纳斯达克综合指数", current=16300.0, change_pct=0.8),
            ],
        )
        ma = _make_analyzer(report_text="复盘")
        llm_structured = {
            "indices": [
                {"code": "S&P 500", "name": "标普500", "comment": "缩量上涨"},
                {"code": "NASDAQ_COMPOSITE", "name": "纳斯达克综合指数", "comment": "科技股领涨"},
            ]
        }

        payload = ma.build_market_review_payload(overview, [], "复盘报告", llm_structured=llm_structured)

        assert payload["indices"][0]["comment"] == "缩量上涨"  # 名称唯一包含：标普500 ⊂ 标普500指数
        assert payload["indices"][1]["comment"] == "科技股领涨"  # 名称精确匹配

    def test_ambiguous_name_fallback_attaches_nothing(self):
        overview = MarketOverview(
            date="2026-06-05",
            indices=[
                MarketIndex(code="sh000001", name="上证指数", current=3372.4, change_pct=0.9),
                MarketIndex(code="sh000016", name="上证50", current=2700.0, change_pct=0.4),
            ],
        )
        ma = _make_analyzer(report_text="复盘")

        payload = ma.build_market_review_payload(
            overview, [], "复盘报告", llm_structured={"indices": [{"name": "上证", "comment": "含糊"}]}
        )

        assert all("comment" not in idx for idx in payload["indices"]), payload["indices"]

    def test_conflicting_code_and_name_attaches_nothing(self):
        """OR-COR-835dbd99：code 与 name 各自命中不同行情时，点评必须丢弃（不挂载）。

        真实代码名取自 data_provider/yfinance_fetcher.py（sh000001 上证指数 /
        sz399001 深证成指）。附录把 code 填 sh000001、name 填深证成指，点评描述
        深证成指走势；修复前 code 命中即返回，点评挂到上证指数行并随历史快照保存。
        docs/full-guide.md 承诺“匹配不唯一/冲突时不挂载”，冲突时不得绕过该逻辑。
        """
        overview = MarketOverview(
            date="2026-06-05",
            indices=[
                MarketIndex(code="sh000001", name="上证指数", current=3372.4, change_pct=0.9),
                MarketIndex(code="sz399001", name="深证成指", current=10200.0, change_pct=-0.3),
            ],
        )
        ma = _make_analyzer(report_text="复盘")

        payload = ma.build_market_review_payload(
            overview,
            [],
            "复盘报告",
            llm_structured={
                "indices": [{"code": "sh000001", "name": "深证成指", "comment": "深证成指午后走弱"}]
            },
        )

        assert all("comment" not in idx for idx in payload["indices"]), payload["indices"]


class TestDivergenceDiagnosisFallback:
    def test_index_up_but_breadth_weak_reports_divergence(self):
        ma = _make_analyzer(report_text="复盘")
        overview = _cn_overview()

        payload = ma.build_market_review_payload(overview, [], "复盘报告")

        diagnosis = payload["breadth"]["divergence_diagnosis"]
        assert isinstance(diagnosis, str) and diagnosis
        assert "背离" in diagnosis
        assert "护盘" in diagnosis

    def test_no_breadth_data_means_no_diagnosis(self):
        ma = _make_analyzer(report_text="复盘")
        overview = _cn_overview(
            up_count=0,
            down_count=0,
            flat_count=0,
            limit_up_count=0,
            limit_down_count=0,
            total_amount=0.0,
        )

        payload = ma.build_market_review_payload(
            overview,
            [],
            "复盘报告",
            market_light_snapshot={"dimensions": {"breadth": {"score": 55, "available": False}}},
        )

        assert "breadth" not in payload

    def test_healthy_breadth_diagnosis_without_divergence_word(self):
        ma = _make_analyzer(report_text="复盘")
        overview = _cn_overview(
            up_count=4200,
            down_count=800,
            flat_count=100,
            limit_up_count=65,
            limit_down_count=2,
        )

        payload = ma.build_market_review_payload(overview, [], "复盘报告")

        diagnosis = payload["breadth"]["divergence_diagnosis"]
        assert isinstance(diagnosis, str) and diagnosis
        assert "背离" not in diagnosis
        assert "涨停" in diagnosis

    def test_missing_index_quotes_never_claims_breadth_matches_index(self):
        """OR-COR-c81484a4：指数行情全部缺失时，兜底不得声称“宽度与指数表现基本匹配”。"""
        ma = _make_analyzer(report_text="复盘")
        overview = _cn_overview(indices=[], up_count=2500, down_count=2500, flat_count=0)

        payload = ma.build_market_review_payload(overview, [], "复盘报告")

        diagnosis = payload["breadth"]["divergence_diagnosis"]
        assert isinstance(diagnosis, str) and diagnosis
        assert "匹配" not in diagnosis, diagnosis
        assert "指数行情缺失" in diagnosis, diagnosis
        assert "仅基于涨跌家数统计" in diagnosis, diagnosis

    def test_missing_index_quotes_flag_every_pure_breadth_conclusion(self):
        """指数缺失时，扩散/收缩结论同样必须标明仅基于涨跌家数、缺少指数对比。"""
        ma = _make_analyzer(report_text="复盘")

        for up_count, down_count in ((3500, 1500), (1500, 3500)):
            overview = _cn_overview(indices=[], up_count=up_count, down_count=down_count, flat_count=0)

            diagnosis = ma.build_market_review_payload(overview, [], "复盘报告")["breadth"]["divergence_diagnosis"]

            assert "指数行情缺失" in diagnosis, diagnosis
            assert "匹配" not in diagnosis, diagnosis

    def test_missing_index_quotes_diagnosis_in_english(self):
        ma = _make_analyzer(report_text="复盘")
        ma.config.report_language = "en"
        overview = _cn_overview(indices=[], up_count=2500, down_count=2500, flat_count=0)

        diagnosis = ma.build_market_review_payload(overview, [], "review")["breadth"]["divergence_diagnosis"]

        assert isinstance(diagnosis, str) and diagnosis
        assert "matches the index move" not in diagnosis, diagnosis
        assert "index quotes unavailable" in diagnosis, diagnosis

    def test_balanced_breadth_with_index_quotes_still_reports_match(self):
        """指数行情可用时既有结论保持不变：只有真正做过指数对比才允许说“基本匹配”。"""
        ma = _make_analyzer(report_text="复盘")
        overview = _cn_overview(
            indices=[MarketIndex(code="000001", name="上证指数", current=3372.4, change_pct=0.1)],
            up_count=2500,
            down_count=2500,
            flat_count=0,
        )

        diagnosis = ma.build_market_review_payload(overview, [], "复盘报告")["breadth"]["divergence_diagnosis"]

        assert "基本匹配" in diagnosis, diagnosis
        assert "指数行情缺失" not in diagnosis, diagnosis

    def test_reversed_direction_breadth_never_claims_match(self):
        """OR-COR-97335eff：指数下跌而个股多数上涨时方向相反，兜底不得定性“基本匹配”。

        bot 内存复现场景：指数平均下跌 2%，2700 家上涨、2300 家下跌（上涨占比 54%，
        未跨过 55% 背离阈值）→ 修复前落入“其余区间”分支输出“宽度与指数表现基本匹配”，
        但指数与个股涨跌方向明显相反。方向不一致时只能陈述观测值。
        """
        ma = _make_analyzer(report_text="复盘")
        overview = _cn_overview(
            indices=[
                MarketIndex(code="000001", name="上证指数", current=3280.0, change_pct=-2.0),
                MarketIndex(code="399001", name="深证成指", current=10200.0, change_pct=-2.0),
            ],
            up_count=2700,
            down_count=2300,
            flat_count=0,
        )

        diagnosis = ma.build_market_review_payload(overview, [], "复盘报告")["breadth"]["divergence_diagnosis"]

        assert "匹配" not in diagnosis, diagnosis
        assert "上涨家数占比 54%" in diagnosis, diagnosis


class TestStructuredTextSanitizing:
    """OR-COR-50abc372：附录里的未配对 UTF-16 代理码点不得进入 payload。

    JSON 解码会保留孤立代理码点；历史快照以 ensure_ascii=False 序列化后绑定 UTF-8 文本列，
    SQLite 拒绝该码点，导致整条复盘历史写入抛 UnicodeEncodeError。
    """

    @staticmethod
    def _report_with_raw_appendix(raw_json: str) -> str:
        # 直接拼接模型原始输出：JSON 文本里是字面量转义序列（模型只输出了 emoji 代理对的一半）。
        return (
            "## 2026-06-05 A股大盘复盘\n\n> 权重护盘。\n\n### 一、盘面总览\n市场震荡分化。\n\n"
            "---\n\n```json\n" + raw_json + "\n```\n"
        )

    def test_lone_surrogate_in_appendix_does_not_break_history_snapshot_write(self):
        raw_json = (
            '{"summary": {"market_status": "震荡分化", "core_conclusion": "权重护盘\\ud83d"}, '
            '"catalysts": [{"title": "降准\\udc00落地", "direction": "利好"}], '
            '"next_day_plan": {"watchlist": ["上证3350支撑\\ud83d"], "notes": "\\ud800"}}'
        )
        ma = _make_analyzer(report_text=self._report_with_raw_appendix(raw_json))

        payload = ma._run_daily_review_parts().structured_payload
        snapshot_text = DatabaseManager._safe_json_dumps({"market_review_payload": payload})

        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE TABLE analysis_history (context_snapshot TEXT)")
            try:
                conn.execute(
                    "INSERT INTO analysis_history (context_snapshot) VALUES (?)", (snapshot_text,)
                )
            except UnicodeEncodeError as exc:
                pytest.fail(f"孤立代理码点进入 payload，整条复盘历史快照写 SQLite 失败: {exc}")
        finally:
            conn.close()

        assert payload["summary"]["core_conclusion"] == "权重护盘"
        assert payload["catalysts"][0]["title"] == "降准落地"
        assert payload["next_day_plan"]["watchlist"] == ["上证3350支撑"]
        assert payload["next_day_plan"]["notes"] is None

    def test_valid_surrogate_pairs_in_appendix_are_preserved(self):
        """成对的代理转义是合法的非 BMP 字符（emoji），必须原样保留。"""
        raw_json = (
            '{"summary": {"core_conclusion": "普涨\\ud83d\\ude00"}, '
            '"cross_market_note": "外围\\ud83c\\udf0d风险偏好回升"}'
        )
        ma = _make_analyzer(report_text=self._report_with_raw_appendix(raw_json))

        payload = ma._run_daily_review_parts().structured_payload

        assert payload["summary"]["core_conclusion"] == "普涨😀"
        assert payload["cross_market_note"] == "外围🌍风险偏好回升"

    def test_clean_structured_text_strips_only_unpaired_surrogates(self):
        clean = MarketAnalyzer._clean_structured_text

        assert clean("权重护盘\ud83d", limit=200) == "权重护盘"
        assert clean("a\ud83db\ude00", limit=200) == "ab"
        assert clean("\ud800\udfff", limit=200) is None
        assert clean("普涨😀", limit=200) == "普涨😀"
        # 先剔除代理码点再截断，长度预算按清洗后的文本计算
        assert clean("ab\ud83d" + "c" * 300, limit=5) == "abccc"


class TestBackwardCompatibility:
    def test_concepts_only_payload_render_does_not_duplicate_concept_table(self):
        """OR-COR-9bf864ce：行业排行为空、概念排行可用时，正文已含概念表；
        渲染层缺失检测未识别概念标记，会把同一份概念表再追加一遍导致重复。"""
        concept_table = (
            "#### 概念板块领涨 Top 5\n"
            "| 排名 | 概念板块 | 涨跌幅 |\n|------|------|--------|\n| 1 | AI算力 | +5.40% |"
        )
        market_payload = {
            "title": "复盘报告",
            "region": "cn",
            "sectors": {},
            "concepts": {"top": [{"name": "AI算力", "change_pct": 5.4}]},
            "markdown_report": "## 复盘报告\n\n### 板块主线\n\n" + concept_table,
        }
        combined = {
            "region": "cn",
            "language": "zh",
            "markets": {"cn": market_payload},
            "markdown_report": market_payload["markdown_report"],
        }

        rendered = _render_market_review_payload_markdown(combined, wrapper_title="🎯 大盘复盘")

        # 正文概念表保留一份；兜底块不得把同一份数据再追加成第二张表
        assert rendered.count("AI算力") == 1
        assert rendered.count("领涨概念 Top 5") == 0

    def test_existing_concept_table_does_not_drop_missing_industry_fallback(self):
        """OR-COR-e7c6a2d1：正文已有概念表、payload 同时有行业+概念榜时，
        兜底应只补缺失的行业部分，行业榜不得因概念标记连坐跳过而丢失。"""
        concept_table = (
            "#### 概念板块领涨 Top 5\n"
            "| 排名 | 概念板块 | 涨跌幅 |\n|------|------|--------|\n| 1 | AI算力 | +5.40% |"
        )
        market_payload = {
            "title": "复盘报告",
            "region": "cn",
            "sectors": {"top": [{"name": "半导体", "change_pct": 3.25}]},
            "concepts": {"top": [{"name": "AI算力", "change_pct": 5.4}]},
            "markdown_report": "## 复盘报告\n\n### 板块主线\n\n" + concept_table,
        }
        combined = {
            "region": "cn",
            "language": "zh",
            "markets": {"cn": market_payload},
            "markdown_report": market_payload["markdown_report"],
        }

        rendered = _render_market_review_payload_markdown(combined, wrapper_title="🎯 大盘复盘")

        # 概念表不重复
        assert rendered.count("AI算力") == 1
        assert rendered.count("领涨概念 Top 5") == 0
        # 缺失的行业榜必须补齐（当前全局判定会把行业兜底一起跳过）
        assert "半导体" in rendered
        assert "领涨板块 Top 5" in rendered

    def test_render_ignores_new_fields_zero_diff(self):
        ma = _make_analyzer(report_text="复盘")
        overview = _cn_overview()

        base_payload = ma.build_market_review_payload(overview, [], "复盘报告")
        enriched = dict(base_payload)
        enriched.update(
            {
                "summary": {"temperature": 45, "market_status": "震荡分化"},
                "catalysts": [{"title": "x", "direction": "bullish", "digested": True}],
                "next_day_plan": {"watchlist": ["a"]},
                "cross_market_note": "note",
            }
        )
        # 历史快照可能残留已下线的 ma_status（OR-COR-91e5bc73），渲染必须继续零差异。
        enriched["indices"] = [dict(item, ma_status={"ma5": "above"}) for item in base_payload["indices"]]

        base_markdown = _render_market_review_payload_markdown(base_payload, wrapper_title="🎯 大盘复盘")
        enriched_markdown = _render_market_review_payload_markdown(enriched, wrapper_title="🎯 大盘复盘")

        assert enriched_markdown == base_markdown

    def test_payload_without_llm_structured_has_no_new_top_level_keys(self):
        ma = _make_analyzer(report_text="复盘")
        overview = _cn_overview(
            up_count=0,
            down_count=0,
            flat_count=0,
            limit_up_count=0,
            limit_down_count=0,
            total_amount=0.0,
        )

        payload = ma.build_market_review_payload(
            overview,
            [],
            "复盘报告",
            market_light_snapshot={"dimensions": {"breadth": {"score": 55, "available": False}}},
        )

        for key in (
            "summary",
            "style_rotation",
            "catalysts",
            "next_day_plan",
            "cross_market_note",
        ):
            assert key not in payload


class TestPromptAppendix:
    def test_zh_prompt_requires_structured_appendix(self):
        ma = _make_analyzer()
        prompt = ma._build_review_prompt(_cn_overview(), [])

        assert "结构化数据附录" in prompt
        for key in ("summary", "divergence_diagnosis", "style_rotation", "catalysts", "next_day_plan"):
            assert key in prompt
        assert "严禁编造" in prompt
        # OR-COR-91e5bc73：指数行情未提供均线/历史收盘价，附录模板不得再要求 ma_status
        assert "ma_status" not in prompt, "附录模板仍在要求无行情支撑的 ma_status"
        assert "均线状态" not in prompt, "附录模板仍在提及均线状态"

    def test_en_prompt_requires_structured_appendix(self):
        ma = _make_analyzer(region="us", profile=US_PROFILE)
        ma.config.report_language = "en"
        overview = MarketOverview(
            date="2026-06-05",
            indices=[MarketIndex(code="SPX", name="S&P 500", current=5200.0, change_pct=0.6)],
        )

        prompt = ma._build_review_prompt(overview, [])

        assert "structured data appendix" in prompt.lower()
        for key in ("summary", "divergence_diagnosis", "style_rotation", "catalysts", "next_day_plan"):
            assert key in prompt
        assert "never fabricate" in prompt.lower()
        # OR-COR-91e5bc73：附录模板不得再要求无行情支撑的 ma_status
        assert "ma_status" not in prompt, "appendix template still requests unsupported ma_status"
        assert "moving-average" not in prompt.lower(), "appendix template still mentions moving-average status"
