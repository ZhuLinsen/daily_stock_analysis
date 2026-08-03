# -*- coding: utf-8 -*-
"""Unit tests for report language helpers."""

import unittest

from src.report_language import (
    SUPPORTED_REPORT_LANGUAGES,
    get_bias_status_emoji,
    get_localized_stock_name,
    get_report_labels,
    get_sentiment_label,
    get_signal_level,
    infer_decision_type_from_advice,
    localize_bias_status,
    localize_operation_advice,
    localize_strategy_conflict_description,
    localize_strategy_skill,
    localize_strategy_synthesis_summary,
    localize_trend_prediction,
    normalize_report_language,
)


class ReportLanguageTestCase(unittest.TestCase):
    def test_get_signal_level_handles_compound_sell_advice(self) -> None:
        signal_text, emoji, signal_tag = get_signal_level("卖出/观望", 60, "zh")

        self.assertEqual(signal_text, "卖出")
        self.assertEqual(emoji, "🔴")
        self.assertEqual(signal_tag, "sell")

    def test_get_signal_level_handles_compound_buy_advice_in_english(self) -> None:
        signal_text, emoji, signal_tag = get_signal_level("Buy / Watch", 40, "en")

        self.assertEqual(signal_text, "Buy")
        self.assertEqual(emoji, "🟢")
        self.assertEqual(signal_tag, "buy")

    def test_get_signal_level_score_fallback_uses_canonical_scale(self) -> None:
        self.assertEqual(get_signal_level("", 28, "zh"), ("减仓", "🟠", "reduce"))
        self.assertEqual(get_signal_level("", 38, "zh"), ("减仓", "🟠", "reduce"))
        self.assertEqual(get_signal_level("", 42, "zh"), ("观望", "⚪", "watch"))
        self.assertEqual(get_signal_level("", 55, "zh"), ("观望", "⚪", "watch"))
        self.assertEqual(get_signal_level("", 60, "zh"), ("买入", "🟢", "buy"))
        self.assertEqual(get_signal_level("", 66, "zh"), ("买入", "🟢", "buy"))
        self.assertEqual(get_signal_level("", 72, "zh"), ("买入", "🟢", "buy"))

    def test_get_localized_stock_name_replaces_placeholder_for_english(self) -> None:
        self.assertEqual(
            get_localized_stock_name("股票AAPL", "AAPL", "en"),
            "Unnamed Stock",
        )

    def test_get_sentiment_label_preserves_higher_band_thresholds(self) -> None:
        self.assertEqual(get_sentiment_label(80, "en"), "Very Bullish")
        self.assertEqual(get_sentiment_label(60, "en"), "Bullish")
        self.assertEqual(get_sentiment_label(40, "zh"), "中性")
        self.assertEqual(get_sentiment_label(20, "zh"), "悲观")

    def test_localize_trend_prediction_preserves_fine_grain_zh_states(self) -> None:
        self.assertEqual(localize_trend_prediction("多头排列", "zh"), "多头排列")
        self.assertEqual(localize_trend_prediction("弱势空头", "zh"), "弱势空头")

    def test_localize_trend_prediction_still_translates_english_input_for_zh(self) -> None:
        self.assertEqual(localize_trend_prediction("bullish", "zh"), "看多")
        self.assertEqual(localize_trend_prediction("very bearish", "zh"), "强烈看空")

    def test_bias_status_helpers_support_english_values(self) -> None:
        self.assertEqual(localize_bias_status("Safe", "en"), "Safe")
        self.assertEqual(localize_bias_status("警戒", "en"), "Caution")
        self.assertEqual(get_bias_status_emoji("Safe"), "✅")
        self.assertEqual(get_bias_status_emoji("Caution"), "⚠️")

    def test_infer_decision_type_from_advice_matches_chinese_phrases(self) -> None:
        self.assertEqual(infer_decision_type_from_advice("建议买入"), "buy")
        self.assertEqual(infer_decision_type_from_advice("建议持有"), "hold")
        self.assertEqual(infer_decision_type_from_advice("建议减仓"), "sell")
        self.assertEqual(infer_decision_type_from_advice("继续持有"), "hold")
        self.assertEqual(infer_decision_type_from_advice("建议洗盘观察"), "hold")
        self.assertEqual(infer_decision_type_from_advice("洗盘观察", default=""), "hold")
        self.assertEqual(infer_decision_type_from_advice("观察", default=""), "hold")
        self.assertEqual(infer_decision_type_from_advice("不建议买入"), "hold")
        self.assertEqual(
            infer_decision_type_from_advice("当前不跌破支撑位继续持有"),
            "hold",
        )
        self.assertEqual(
            infer_decision_type_from_advice("不破支撑后仍可持有"),
            "hold",
        )


class GermanReportLanguageTestCase(unittest.TestCase):
    def test_german_is_supported(self) -> None:
        self.assertIn("de", SUPPORTED_REPORT_LANGUAGES)

    def test_normalize_german_aliases(self) -> None:
        self.assertEqual(normalize_report_language("de"), "de")
        self.assertEqual(normalize_report_language("german"), "de")
        self.assertEqual(normalize_report_language("de-DE"), "de")
        self.assertEqual(normalize_report_language("de_DE"), "de")
        self.assertEqual(normalize_report_language("de-ch"), "de")

    def test_unknown_language_falls_back_to_default(self) -> None:
        self.assertEqual(normalize_report_language("fr"), "zh")
        self.assertEqual(normalize_report_language(None), "zh")

    def test_german_labels_cover_full_english_key_set(self) -> None:
        de_labels = get_report_labels("de")
        en_labels = get_report_labels("en")
        zh_labels = get_report_labels("zh")
        self.assertEqual(set(de_labels.keys()), set(en_labels.keys()))
        self.assertEqual(set(de_labels.keys()), set(zh_labels.keys()))
        self.assertEqual(de_labels["dashboard_title"], "Entscheidungs-Dashboard")
        self.assertEqual(de_labels["stop_loss_label"], "Stop-Loss")
        self.assertEqual(de_labels["not_investment_advice"], "KI-generiert, nur zu Referenzzwecken. Keine Anlageberatung.")

    def test_german_sentiment_label_bands(self) -> None:
        self.assertEqual(get_sentiment_label(80, "de"), "Sehr Bullisch")
        self.assertEqual(get_sentiment_label(60, "de"), "Bullisch")
        self.assertEqual(get_sentiment_label(40, "de"), "Neutral")
        self.assertEqual(get_sentiment_label(20, "de"), "Bärisch")
        self.assertEqual(get_sentiment_label(0, "de"), "Sehr Bärisch")

    def test_german_operation_advice_and_trend(self) -> None:
        self.assertEqual(localize_operation_advice("买入", "de"), "Kaufen")
        self.assertEqual(localize_operation_advice("strong sell", "de"), "Starker Verkauf")
        self.assertEqual(localize_trend_prediction("bullish", "de"), "Bullisch")
        self.assertEqual(localize_trend_prediction("震荡", "de"), "Seitwärts")

    def test_german_localized_stock_name_placeholder(self) -> None:
        self.assertEqual(
            get_localized_stock_name("股票AAPL", "AAPL", "de"),
            "Unbestätigte Aktie",
        )

    def test_german_strategy_skill_and_conflict(self) -> None:
        self.assertEqual(localize_strategy_skill("箱体震荡", "de"), "Box-Konsolidierung")
        conflict = localize_strategy_conflict_description("directional_opposition", "de")
        self.assertIn("bullisch", conflict)
        self.assertIn("bärisch", conflict)

    def test_german_strategy_synthesis_summary(self) -> None:
        payload = {
            "summary_params": {"opinion_count": 3, "invalid_opinion_count": 0},
            "final_signal": "买入",
            "consensus_level": "高",
            "conflict_severity": "无",
            "conflict_count": 0,
            "supporting_skills": [],
            "opposing_skills": [],
        }
        summary = localize_strategy_synthesis_summary(payload, "de")
        self.assertIn("Synthese aus 3 Strategien", summary)
        self.assertIn("Kaufen", summary)

    def test_existing_languages_unchanged(self) -> None:
        self.assertEqual(get_sentiment_label(80, "en"), "Very Bullish")
        self.assertEqual(get_sentiment_label(40, "zh"), "中性")
        self.assertEqual(get_sentiment_label(80, "ko"), "매우 낙관")

    def test_german_advice_canonicalizes_to_decision_type(self) -> None:
        self.assertEqual(infer_decision_type_from_advice("Kaufen"), "buy")
        self.assertEqual(infer_decision_type_from_advice("Verkaufen"), "sell")
        self.assertEqual(infer_decision_type_from_advice("Halten"), "hold")
        self.assertEqual(infer_decision_type_from_advice("Beobachten"), "hold")

    def test_german_advice_resolves_signal_level(self) -> None:
        self.assertEqual(get_signal_level("Kaufen", 72, "de"), ("Kaufen", "🟢", "buy"))
        self.assertEqual(get_signal_level("Verkaufen", 30, "de"), ("Verkaufen", "🔴", "sell"))

    def test_german_values_canonicalize_back_for_other_languages(self) -> None:
        self.assertEqual(localize_trend_prediction("Bullisch", "en"), "Bullish")
        self.assertEqual(localize_operation_advice("Kaufen", "zh"), "买入")


class KoreanReportLanguageTestCase(unittest.TestCase):
    def test_korean_is_supported(self) -> None:
        self.assertIn("ko", SUPPORTED_REPORT_LANGUAGES)

    def test_normalize_korean_aliases(self) -> None:
        self.assertEqual(normalize_report_language("ko"), "ko")
        self.assertEqual(normalize_report_language("korean"), "ko")
        self.assertEqual(normalize_report_language("ko-KR"), "ko")
        self.assertEqual(normalize_report_language("kr"), "ko")

    def test_unknown_language_falls_back_to_default(self) -> None:
        self.assertEqual(normalize_report_language("fr"), "zh")
        self.assertEqual(normalize_report_language(None), "zh")

    def test_korean_labels_cover_full_english_key_set(self) -> None:
        ko_labels = get_report_labels("ko")
        en_labels = get_report_labels("en")
        self.assertEqual(set(ko_labels.keys()), set(en_labels.keys()))
        self.assertEqual(ko_labels["dashboard_title"], "결정 대시보드")
        self.assertEqual(ko_labels["risk_alerts_label"], "리스크 경보")

    def test_korean_sentiment_label_bands(self) -> None:
        self.assertEqual(get_sentiment_label(80, "ko"), "매우 낙관")
        self.assertEqual(get_sentiment_label(40, "ko"), "중립")
        self.assertEqual(get_sentiment_label(0, "ko"), "매우 비관")

    def test_korean_operation_advice_and_trend(self) -> None:
        self.assertEqual(localize_operation_advice("买入", "ko"), "매수")
        self.assertEqual(localize_operation_advice("strong sell", "ko"), "적극 매도")
        self.assertEqual(localize_trend_prediction("bullish", "ko"), "상승")

    def test_korean_localized_stock_name_placeholder(self) -> None:
        self.assertEqual(
            get_localized_stock_name("股票AAPL", "AAPL", "ko"),
            "미확인 종목",
        )

    def test_existing_languages_unchanged(self) -> None:
        self.assertEqual(get_sentiment_label(80, "en"), "Very Bullish")
        self.assertEqual(get_sentiment_label(40, "zh"), "中性")

    def test_korean_advice_canonicalizes_to_decision_type(self) -> None:
        self.assertEqual(infer_decision_type_from_advice("매수"), "buy")
        self.assertEqual(infer_decision_type_from_advice("매도"), "sell")
        self.assertEqual(infer_decision_type_from_advice("보유"), "hold")
        self.assertEqual(infer_decision_type_from_advice("관망"), "hold")

    def test_korean_advice_resolves_signal_level(self) -> None:
        self.assertEqual(get_signal_level("매수", 72, "ko"), ("매수", "🟢", "buy"))
        self.assertEqual(get_signal_level("매도", 30, "ko"), ("매도", "🔴", "sell"))

    def test_korean_values_canonicalize_back_for_other_languages(self) -> None:
        self.assertEqual(localize_trend_prediction("상승", "en"), "Bullish")
        self.assertEqual(localize_operation_advice("적극 매도", "zh"), "强烈卖出")


if __name__ == "__main__":
    unittest.main()
