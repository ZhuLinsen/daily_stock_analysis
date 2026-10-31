# -*- coding: utf-8 -*-
"""Issue #1584: 大盘复盘结构化字段（summary / ma_status / divergence / style_rotation / catalysts / next_day_plan）。

覆盖目标：
1. LLM 输出的结构化附录（fenced JSON）可被提取并从 Markdown 中剥离；
2. 附录畸形/缺失时逐字段降级，绝不中断复盘；
3. payload 新增字段全部可选，旧消费者/旧记录渲染零差异；
4. breadth.divergence_diagnosis 的确定性兜底组装。
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.core.market_profile import CN_PROFILE, US_PROFILE
from src.core.market_strategy import get_market_strategy_blueprint
from src.core.market_review import _render_market_review_payload_markdown
from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview


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


class TestPayloadStructuredFields:
    def test_full_appendix_populates_all_new_payload_fields(self):
        ma = _make_analyzer(report_text=_appendix_report(FULL_APPENDIX))

        result = ma._run_daily_review_parts()
        payload = result.structured_payload

        # 附录从对外 Markdown 中剥离
        assert "```json" not in result.report
        assert "### 一、盘面总览" in result.report

        assert payload["summary"] == FULL_APPENDIX["summary"]
        assert payload["indices"][0]["ma_status"] == {
            "ma5": "above",
            "ma10": "below",
            "ma20": "above",
        }
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

    def test_ma_status_ignores_unknown_codes_and_invalid_states(self):
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
        # 上证按 code 匹配；非法状态 "hover" 被剔除
        assert indices[0]["name"] == "上证指数"
        assert indices[0]["ma_status"] == {"ma5": "above", "ma20": "below"}
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
        assert payload["indices"][0]["ma_status"] == {"ma5": "above"}


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


class TestBackwardCompatibility:
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
        for key in ("summary", "ma_status", "divergence_diagnosis", "style_rotation", "catalysts", "next_day_plan"):
            assert key in prompt
        assert "严禁编造" in prompt

    def test_en_prompt_requires_structured_appendix(self):
        ma = _make_analyzer(region="us", profile=US_PROFILE)
        ma.config.report_language = "en"
        overview = MarketOverview(
            date="2026-06-05",
            indices=[MarketIndex(code="SPX", name="S&P 500", current=5200.0, change_pct=0.6)],
        )

        prompt = ma._build_review_prompt(overview, [])

        assert "structured data appendix" in prompt.lower()
        for key in ("summary", "ma_status", "divergence_diagnosis", "style_rotation", "catalysts", "next_day_plan"):
            assert key in prompt
        assert "never fabricate" in prompt.lower()
