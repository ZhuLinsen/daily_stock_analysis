# -*- coding: utf-8 -*-
"""Tests for the Phase 25.6 four-masters commentary supplement.

覆蓋面：
- schema roundtrip（AnalysisResult.to_dict / report_schema / history rebuild）
- prompt 段落的旗標 gating（analyzer 直呼叫 + agent executor 兩條路徑）
- 驗證器行為（枚舉收斂、行動欄位剝除、HTML 淨化、畸形降級）
- Markdown 渲染（含免責聲明、缺失時不出段、不引入不安全 HTML）
- 不覆蓋原始欄位（operation_advice / trend_prediction / sentiment_score / buy zone）
"""

import unittest

from src.services.four_masters_commentary import (
    DISCLAIMER_ZH,
    build_four_masters_prompt_sections,
    render_four_masters_markdown,
    validate_four_masters_commentary,
)


def _valid_commentary() -> dict:
    return {
        "buffett": {
            "summary": "營運現金流穩定且護城河仍在，股價回檔並非價值受損。",
            "supports_original_view": "challenge",
            "key_question": "目前價格相對內在價值是否有足夠折讓？",
            "blind_spot_in_original_report": "以技術位取代估值依據。",
            "margin_of_safety_comment": "以本益比區間看安全邊際不足。",
            "what_would_change_this_view": "獲利結構性下修。",
        },
        "munger": {
            "summary": "報告結論與近期價格方向高度一致，需檢查敘事是否被價格驅動。",
            "supports_original_view": "mixed",
            "inversion_question": "這筆投資最可能怎麼失敗？",
            "biggest_failure_mode": "產業景氣反轉而報告仍外推近期趨勢。",
            "psychological_bias_warning": "近因偏誤。",
            "what_would_change_this_view": "出現與價格無關的基本面證據。",
        },
        "duan_yongping": {
            "summary": "生意模式與客戶黏著未變，短期波動不等於生意變壞。",
            "supports_original_view": "support",
            "business_quality_comment": "商業模式健康。",
            "product_or_customer_value_comment": "產品競爭力未見惡化。",
            "long_term_holding_condition": "客戶價值持續成長。",
            "what_would_change_this_view": "核心客戶流失。",
        },
        "li_lu": {
            "summary": "長期確定性仍高，但需明確的失效紅線。",
            "supports_original_view": "support",
            "certainty_comment": "產業地位帶來高確定性。",
            "downside_risk_comment": "極端情境下回撤可能超過三成。",
            "red_lines": ["市占率跌破關鍵水準", "自由現金流轉負"],
            "what_would_change_this_view": "紅線被觸發。",
        },
        "synthesis": {
            "main_disagreement": "價值視角質疑買進區間的估值依據。",
            "most_useful_supplement_to_original_report": "把技術位買區改為估值錨定的觀察區。",
            "confidence_adjustment": "lower",
            "does_not_override_original_action": True,
        },
    }


class ValidateFourMastersCommentaryTestCase(unittest.TestCase):
    def test_valid_payload_roundtrips(self) -> None:
        cleaned = validate_four_masters_commentary(_valid_commentary())
        self.assertIsNotNone(cleaned)
        assert cleaned is not None
        self.assertEqual(cleaned["buffett"]["supports_original_view"], "challenge")
        self.assertEqual(cleaned["li_lu"]["red_lines"], ["市占率跌破關鍵水準", "自由現金流轉負"])
        self.assertEqual(cleaned["synthesis"]["confidence_adjustment"], "lower")

    def test_none_and_non_dict_return_none(self) -> None:
        self.assertIsNone(validate_four_masters_commentary(None))
        self.assertIsNone(validate_four_masters_commentary("not a dict"))
        self.assertIsNone(validate_four_masters_commentary([1, 2]))
        self.assertIsNone(validate_four_masters_commentary({}))

    def test_missing_all_summaries_returns_none(self) -> None:
        raw = {"buffett": {"key_question": "?"}, "synthesis": {}}
        self.assertIsNone(validate_four_masters_commentary(raw))

    def test_partial_masters_are_kept(self) -> None:
        raw = {"buffett": _valid_commentary()["buffett"]}
        cleaned = validate_four_masters_commentary(raw)
        assert cleaned is not None
        self.assertIn("buffett", cleaned)
        self.assertNotIn("munger", cleaned)
        # synthesis 缺失時仍補上 override 保證
        self.assertTrue(cleaned["synthesis"]["does_not_override_original_action"])

    def test_invalid_enum_coerced(self) -> None:
        raw = _valid_commentary()
        raw["buffett"]["supports_original_view"] = "BUY NOW"
        raw["synthesis"]["confidence_adjustment"] = "sell"
        cleaned = validate_four_masters_commentary(raw)
        assert cleaned is not None
        self.assertEqual(cleaned["buffett"]["supports_original_view"], "mixed")
        self.assertEqual(cleaned["synthesis"]["confidence_adjustment"], "unchanged")

    def test_llm_supplied_action_fields_are_stripped(self) -> None:
        raw = _valid_commentary()
        raw["buffett"]["operation_advice"] = "買進"
        raw["buffett"]["final_action"] = "ACCUMULATE"
        raw["buffett"]["buy_zone"] = {"low": 900, "high": 950}
        raw["synthesis"]["suggested_action"] = "加倉"
        raw["synthesis"]["does_not_override_original_action"] = False
        cleaned = validate_four_masters_commentary(raw)
        assert cleaned is not None
        self.assertNotIn("operation_advice", cleaned["buffett"])
        self.assertNotIn("final_action", cleaned["buffett"])
        self.assertNotIn("buy_zone", cleaned["buffett"])
        self.assertNotIn("suggested_action", cleaned["synthesis"])
        # override 保證恆為 True，不信任 LLM 值
        self.assertTrue(cleaned["synthesis"]["does_not_override_original_action"])

    def test_html_is_sanitized(self) -> None:
        raw = _valid_commentary()
        raw["buffett"]["summary"] = '<script>alert(1)</script>穩健 <b>加粗</b> <img src=x>'
        cleaned = validate_four_masters_commentary(raw)
        assert cleaned is not None
        self.assertNotIn("<", cleaned["buffett"]["summary"])
        self.assertNotIn(">", cleaned["buffett"]["summary"])
        self.assertIn("穩健", cleaned["buffett"]["summary"])

    def test_oversized_text_is_truncated(self) -> None:
        raw = _valid_commentary()
        raw["buffett"]["summary"] = "長" * 5000
        cleaned = validate_four_masters_commentary(raw)
        assert cleaned is not None
        self.assertLessEqual(len(cleaned["buffett"]["summary"]), 600)

    def test_red_lines_non_list_degrades_gracefully(self) -> None:
        raw = _valid_commentary()
        raw["li_lu"]["red_lines"] = "單一字串紅線"
        cleaned = validate_four_masters_commentary(raw)
        assert cleaned is not None
        self.assertEqual(cleaned["li_lu"]["red_lines"], ["單一字串紅線"])
        raw["li_lu"]["red_lines"] = {"not": "a list"}
        cleaned2 = validate_four_masters_commentary(raw)
        assert cleaned2 is not None
        self.assertNotIn("red_lines", cleaned2["li_lu"])


class RenderFourMastersMarkdownTestCase(unittest.TestCase):
    def test_renders_full_section_with_disclaimer(self) -> None:
        lines = render_four_masters_markdown(_valid_commentary(), "zh_TW")
        text = "\n".join(lines)
        self.assertIn("## 四大師視角補充", text)
        self.assertIn("### 巴菲特視角：價值與安全邊際", text)
        self.assertIn("### 蒙格視角：反向思考與誤判檢查", text)
        self.assertIn("### 段永平視角：生意模式與用戶價值", text)
        self.assertIn("### 李錄視角：長期確定性與風險紅線", text)
        self.assertIn(DISCLAIMER_ZH, text)
        self.assertIn("不改變原始操作建議", text)

    def test_invalid_input_renders_nothing(self) -> None:
        self.assertEqual(render_four_masters_markdown(None), [])
        self.assertEqual(render_four_masters_markdown({}), [])
        self.assertEqual(render_four_masters_markdown("bad"), [])

    def test_no_unsafe_html_in_output(self) -> None:
        raw = _valid_commentary()
        raw["munger"]["summary"] = "<iframe src='x'></iframe>提防敘事 <a href='j'>連結</a>"
        text = "\n".join(render_four_masters_markdown(raw, "zh_TW"))
        self.assertNotIn("<iframe", text)
        self.assertNotIn("<a ", text)
        self.assertNotIn("</", text)

    def test_english_rendering(self) -> None:
        text = "\n".join(render_four_masters_markdown(_valid_commentary(), "en"))
        self.assertIn("## Four Masters Commentary", text)
        self.assertIn("Buffett Lens", text)
        self.assertIn("does not override the original recommendation", text)


class PromptSectionsTestCase(unittest.TestCase):
    def test_disabled_returns_empty(self) -> None:
        self.assertEqual(build_four_masters_prompt_sections(False), ("", ""))

    def test_enabled_returns_schema_and_instructions(self) -> None:
        schema_field, section = build_four_masters_prompt_sections(True)
        self.assertIn("four_masters_commentary", schema_field)
        self.assertIn("四大師視角補充", section)
        self.assertIn("不得出現任何買進/賣出", section)
        self.assertIn("模擬點評", section)

    def test_analyzer_system_prompt_gated_by_flag(self) -> None:
        from src.analyzer import GeminiAnalyzer

        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer._skill_instructions_override = ""
        analyzer._default_skill_policy_override = ""
        analyzer._use_legacy_default_prompt_override = False
        analyzer._resolved_prompt_state = None

        class _Cfg:
            enable_value_network_mermaid = False
            enable_four_masters_commentary = True

        analyzer._config_override = _Cfg()
        prompt = analyzer._get_analysis_system_prompt("zh_TW", "2330")
        self.assertIn("four_masters_commentary", prompt)

        class _CfgOff(_Cfg):
            enable_four_masters_commentary = False

        analyzer._config_override = _CfgOff()
        prompt_off = analyzer._get_analysis_system_prompt("zh_TW", "2330")
        self.assertNotIn("four_masters_commentary", prompt_off)


class SchemaAndPersistenceTestCase(unittest.TestCase):
    def test_analysis_result_roundtrip(self) -> None:
        from src.analyzer import AnalysisResult

        result = AnalysisResult(
            code="2330", name="台積電",
            sentiment_score=60, trend_prediction="震盪", operation_advice="觀望",
            four_masters_commentary=_valid_commentary(),
        )
        data = result.to_dict()
        self.assertEqual(data["four_masters_commentary"], _valid_commentary())
        empty = AnalysisResult(
            code="0050", name="元大台灣50",
            sentiment_score=50, trend_prediction="震盪", operation_advice="觀望",
        )
        self.assertIsNone(empty.to_dict()["four_masters_commentary"])

    def test_report_schema_accepts_field(self) -> None:
        from src.schemas.report_schema import AnalysisReportSchema

        base = {
            "stock_name": "台積電",
            "sentiment_score": 55,
            "trend_prediction": "震盪",
            "operation_advice": "觀望",
            "decision_type": "hold",
            "confidence_level": "中",
        }
        payload = AnalysisReportSchema.model_validate(
            {**base, "four_masters_commentary": _valid_commentary()}
        )
        self.assertIsNotNone(payload.four_masters_commentary)
        # 舊 payload（無此欄位）仍可通過
        legacy = AnalysisReportSchema.model_validate(base)
        self.assertIsNone(legacy.four_masters_commentary)

    def test_commentary_does_not_mutate_original_fields(self) -> None:
        from src.analyzer import AnalysisResult

        result = AnalysisResult(
            code="2330", name="台積電",
            sentiment_score=62, trend_prediction="看多", operation_advice="持有",
            four_masters_commentary=_valid_commentary(),
        )
        render_four_masters_markdown(result.four_masters_commentary, "zh_TW")
        self.assertEqual(result.sentiment_score, 62)
        self.assertEqual(result.trend_prediction, "看多")
        self.assertEqual(result.operation_advice, "持有")


class FullReportRenderingTestCase(unittest.TestCase):
    """透過 HistoryService 的完整報告生成器驗證段落插入與降級。"""

    def _render(self, commentary) -> str:
        from src.analyzer import AnalysisResult
        from src.services.history_service import HistoryService

        result = AnalysisResult(
            code="2330", name="台積電",
            sentiment_score=60, trend_prediction="震盪", operation_advice="觀望",
            analysis_summary="測試摘要",
            four_masters_commentary=commentary,
        )

        class _Record:
            stock_code = "2330"
            stock_name = "台積電"
            news_content = ""
            analysis_summary = ""
            sentiment_score = 60
            trend_prediction = "震盪"
            operation_advice = "觀望"
            created_at = None

        service = HistoryService.__new__(HistoryService)
        return service._generate_single_stock_markdown(result, _Record())

    def test_report_with_commentary_contains_section(self) -> None:
        markdown = self._render(_valid_commentary())
        self.assertIn("## 四大師視角補充", markdown)
        self.assertIn(DISCLAIMER_ZH, markdown)
        # 原始欄位仍在
        self.assertIn("觀望", markdown)

    def test_report_without_commentary_unchanged(self) -> None:
        markdown = self._render(None)
        self.assertNotIn("四大師視角補充", markdown)

    def test_report_with_malformed_commentary_degrades_safely(self) -> None:
        for bad in ("字串", 123, ["list"], {"buffett": "not a dict"}, {"buffett": {"key_question": "?"}}):
            markdown = self._render(bad)
            self.assertNotIn("四大師視角補充", markdown)

    def test_etf_and_leveraged_payloads_render(self) -> None:
        raw = _valid_commentary()
        raw["buffett"]["summary"] = "0050 追蹤台灣50指數，費用低、折溢價收斂，屬核心工具。"
        raw["li_lu"]["red_lines"] = ["槓桿 ETF 波動衰減超出預期", "追蹤誤差擴大"]
        markdown = self._render(raw)
        self.assertIn("四大師視角補充", markdown)
        self.assertIn("波動衰減", markdown)


if __name__ == "__main__":
    unittest.main()
