# -*- coding: utf-8 -*-
"""Spanish (es) report-language coverage."""

import copy
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_analyzer_prompt_language import _cjk_chars, _make_analyzer, _rich_context

from src.core.market_review import _get_market_review_text
from src.market_context import get_market_guidelines, get_market_role
from src.report_language import (
    SUPPORTED_REPORT_LANGUAGES,
    get_no_data_text,
    get_placeholder_text,
    get_report_labels,
    get_sentiment_label,
    get_unknown_text,
    infer_decision_type_from_advice,
    localize_confidence_level,
    localize_operation_advice,
    localize_trend_prediction,
    normalize_report_language,
)
from src.schemas.decision_action import _ACTION_LABELS
from src.services.empty_news import _DISCLOSURES

_CHINESE_RE = re.compile(r"[一-鿿]")
_HANGUL_RE = re.compile(r"[가-힯]")


class SpanishReportLanguageTestCase(unittest.TestCase):
    def test_normalize_aliases(self) -> None:
        self.assertIn("es", SUPPORTED_REPORT_LANGUAGES)
        for alias in ("es", "spanish", "Español", "es-ES", "es_es", "es-419"):
            self.assertEqual(normalize_report_language(alias), "es", alias)

    def test_labels_have_same_keys_as_english_and_no_cjk(self) -> None:
        en = get_report_labels("en")
        es = get_report_labels("es")
        self.assertEqual(set(es), set(en))
        for key, value in es.items():
            self.assertFalse(_CHINESE_RE.search(value), key)
            self.assertFalse(_HANGUL_RE.search(value), key)
        self.assertEqual(es["day_range_label"], "Rango del día")
        self.assertEqual(es["shares_unit"], "acciones")
        self.assertEqual(es["stop_loss_label"], "Stop loss")

    def test_localization_to_spanish(self) -> None:
        self.assertEqual(localize_operation_advice("买入", "es"), "Comprar")
        self.assertEqual(localize_operation_advice("hold", "es"), "Mantener")
        self.assertEqual(localize_operation_advice("Reducir", "es"), "Reducir")
        self.assertEqual(localize_trend_prediction("看多", "es"), "Alcista")
        self.assertEqual(localize_trend_prediction("Bajista", "es"), "Bajista")
        self.assertEqual(localize_trend_prediction("震荡", "es"), "Lateral")
        self.assertEqual(localize_confidence_level("高", "es"), "Alta")
        self.assertEqual(infer_decision_type_from_advice("Vender"), "sell")
        self.assertEqual(infer_decision_type_from_advice("Comprar"), "buy")
        self.assertEqual(get_sentiment_label(70, "es"), "Alcista")

    def test_fallback_texts(self) -> None:
        self.assertEqual(get_placeholder_text("es"), "Pendiente")
        self.assertEqual(get_unknown_text("es"), "Desconocido")
        self.assertEqual(get_no_data_text("es"), "Datos no disponibles")

    def test_market_review_titles_spanish(self) -> None:
        text = _get_market_review_text("es")
        self.assertIn("Resumen del mercado", text["root_title"])
        self.assertEqual(text["us_title"], "# Resumen del mercado de EE. UU.")

    def test_action_labels_and_empty_news(self) -> None:
        for labels in _ACTION_LABELS.values():
            self.assertIn("es", labels)
        self.assertIn("es", _DISCLOSURES)

    def test_market_context_uses_english_text(self) -> None:
        self.assertEqual(get_market_role("AAPL", "es"), get_market_role("AAPL", "en"))
        self.assertEqual(get_market_guidelines("AAPL", "es"), get_market_guidelines("AAPL", "en"))

    def test_analyzer_prompts_use_english_scaffolding_with_spanish_directive(self) -> None:
        analyzer = _make_analyzer(legacy=True)
        fake_cfg = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short")
        with patch("src.analyzer.get_config", return_value=fake_cfg):
            es_user = analyzer._format_prompt(copy.deepcopy(_rich_context()), "Apple", report_language="es")
            en_user = analyzer._format_prompt(copy.deepcopy(_rich_context()), "Apple", report_language="en")
        es_system = analyzer._get_analysis_system_prompt("es", stock_code="AAPL")

        self.assertEqual(_cjk_chars(es_user), "")
        self.assertEqual(_cjk_chars(es_system), "")
        self.assertIn("# Decision Dashboard Analysis Request", es_user)
        self.assertIn("All human-readable JSON values must be in Spanish", es_user)
        self.assertIn("All human-readable JSON values must be written in Spanish", es_system)
        self.assertIn("Output Language (highest priority)", es_system)
        en_headers = re.findall(r"^#{1,4} .+$", en_user, re.MULTILINE)
        es_headers = re.findall(r"^#{1,4} .+$", es_user, re.MULTILINE)
        self.assertEqual(es_headers, en_headers)


if __name__ == "__main__":
    unittest.main()
