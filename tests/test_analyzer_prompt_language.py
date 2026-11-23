# -*- coding: utf-8 -*-
"""Regression tests for full-language stock analysis prompt templates (#2352).

With ``REPORT_LANGUAGE=en`` the per-stock Decision Dashboard prompt used to be a
Chinese template with only a trailing English output-language block, so smaller
local models (e.g. ``ollama/qwen3:14b``) kept answering in Chinese. English mode
must now use complete English system + user templates while keeping JSON keys,
enum values and the Chinese template unchanged.
"""

import copy
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from src.agent.skills.defaults import CORE_TRADING_SKILL_POLICY_EN, CORE_TRADING_SKILL_POLICY_ZH
from src.analyzer import GeminiAnalyzer, _legacy_audit_marker_specs

# CJK ideographs plus full-width punctuation/forms. Hangul is intentionally not
# matched so the Korean output directive does not count as Chinese template text.
_CJK_RE = re.compile(r"[　-〿㐀-䶿一-鿿＀-￯]")
_JSON_KEY_RE = re.compile(r'^\s*"([a-z_0-9]+)":', re.MULTILINE)


def _cjk_chars(text: str) -> str:
    return "".join(_CJK_RE.findall(text))


def _rich_context() -> dict:
    """A context that exercises every optional prompt block with ASCII-only data."""
    return {
        "code": "AAPL",
        "stock_name": "Apple",
        "date": "2026-03-16",
        "today": {
            "close": 10.5, "open": 10.1, "high": 10.8, "low": 10.0, "pct_chg": 1.2,
            "volume": 123456789, "amount": 987654321, "ma5": 10.2, "ma10": 10.0, "ma20": 9.8,
        },
        "ma_status": "bullish",
        "realtime": {
            "price": 10.5, "volume_ratio": 1.3, "volume_ratio_desc": "normal", "turnover_rate": 2.1,
            "pe_ratio": 20, "pb_ratio": 3, "total_mv": 1.2e11, "circ_mv": 1.0e11, "change_60d": 5.5,
        },
        "fundamental_context": {
            "earnings": {
                "data": {
                    "financial_report": {"report_date": "2025-12-31", "revenue": 1000, "roe": 12},
                    "dividend": {"ttm_cash_dividend_per_share": 1.2, "ttm_dividend_yield_pct": 2.4},
                }
            },
            "capital_flow": {
                "data": {
                    "stock_flow": {"main_net_inflow": 1000, "inflow_5d": 2000, "inflow_10d": 3000},
                    "sector_rankings": {"top": [{"name": "Semis"}, {"name": "Banks"}], "bottom": [{"name": "Coal"}]},
                }
            },
            "institution": {
                "status": "ok",
                "data": {"foreign_net": 1, "trust_net": 2, "dealer_net": 3, "total_net": 6, "date": "2026-03-16"},
            },
        },
        "chip": {"profit_ratio": 0.8, "avg_cost": 9.5, "concentration_90": 0.12, "concentration_70": 0.08},
        "trend_analysis": {
            "trend_status": "bullish", "ma_alignment": "MA5>MA10>MA20", "trend_strength": 70,
            "bias_ma5": 6.2, "bias_ma10": 3.1, "volume_status": "normal", "buy_signal": "buy",
            "signal_score": 72, "signal_reasons": ["reason a"], "risk_factors": ["risk b"],
        },
        "yesterday": {"close": 10.3},
        "volume_change_ratio": 12.5,
        "price_change_ratio": 1.9,
        "news_window_days": 5,
        "data_missing": True,
        "is_index_etf": True,
    }


def _make_analyzer(*, legacy: bool, skill_instructions: str = "", default_skill_policy: str = ""):
    with patch.object(GeminiAnalyzer, "_init_litellm", return_value=None):
        return GeminiAnalyzer(
            skill_instructions=skill_instructions,
            default_skill_policy=default_skill_policy,
            use_legacy_default_prompt=legacy,
        )


class EnglishStockPromptTemplateTestCase(unittest.TestCase):
    def test_english_system_prompt_has_no_chinese_template_text(self) -> None:
        for legacy in (True, False):
            analyzer = _make_analyzer(legacy=legacy, skill_instructions="### Skill 1: swing\n- watch support")
            for code in ("600519", "AAPL", "hk00700"):
                with self.subTest(legacy=legacy, code=code):
                    prompt = analyzer._get_analysis_system_prompt("en", stock_code=code)
                    self.assertEqual(_cjk_chars(prompt), "")
                    self.assertIn("Decision Dashboard", prompt)
                    self.assertIn('"decision_type": "buy/hold/sell"', prompt)
                    self.assertIn("## Output Language (highest priority)", prompt)

    def test_english_system_prompt_keeps_json_keys_of_chinese_template(self) -> None:
        for legacy in (True, False):
            analyzer = _make_analyzer(legacy=legacy)
            with self.subTest(legacy=legacy):
                zh_keys = _JSON_KEY_RE.findall(analyzer._get_analysis_system_prompt("zh", stock_code="600519"))
                en_keys = _JSON_KEY_RE.findall(analyzer._get_analysis_system_prompt("en", stock_code="600519"))
                self.assertGreater(len(zh_keys), 50)
                self.assertEqual(en_keys, zh_keys)

    def test_english_skill_prompt_uses_english_default_skill_baseline(self) -> None:
        analyzer = _make_analyzer(legacy=False, default_skill_policy=CORE_TRADING_SKILL_POLICY_ZH)

        en_prompt = analyzer._get_analysis_system_prompt("en", stock_code="AAPL")
        zh_prompt = analyzer._get_analysis_system_prompt("zh", stock_code="AAPL")

        self.assertIn(CORE_TRADING_SKILL_POLICY_EN, en_prompt)
        self.assertEqual(_cjk_chars(en_prompt), "")
        self.assertIn(CORE_TRADING_SKILL_POLICY_ZH, zh_prompt)

    def test_english_skill_prompt_keeps_builtin_skill_text_as_runtime_data(self) -> None:
        """Language boundary: English mode translates the analyzer template, not skill content.

        Built-in (and custom) skill instructions are loaded from YAML and rendered by
        ``SkillManager``; they are injected verbatim in their authored language. Everything
        outside that injected block must be English.
        """
        from src.agent.skills.base import SkillManager

        manager = SkillManager()
        self.assertGreater(manager.load_builtin_skills(), 0)
        manager.activate(["chan_theory", "volume_breakout"])
        skill_instructions = manager.get_skill_instructions()
        # The built-in skill YAML is authored in Chinese; this is what makes the boundary visible.
        self.assertNotEqual(_cjk_chars(skill_instructions), "")

        analyzer = _make_analyzer(legacy=False, skill_instructions=skill_instructions)
        prompt = analyzer._get_analysis_system_prompt("en", stock_code="600519")

        self.assertIn(f"## Active Trading Skills\n\n{skill_instructions}\n", prompt)
        self.assertEqual(_cjk_chars(prompt.replace(skill_instructions, "")), "")
        self.assertIn("## Output Language (highest priority)", prompt)

    def test_english_user_prompt_has_no_chinese_template_text(self) -> None:
        fake_cfg = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short")
        for legacy in (True, False):
            analyzer = _make_analyzer(legacy=legacy)
            for news in ("AAPL headline", None):
                with self.subTest(legacy=legacy, news=bool(news)), \
                        patch("src.analyzer.get_config", return_value=fake_cfg):
                    prompt = analyzer._format_prompt(
                        _rich_context(), "Apple", news_context=news, report_language="en"
                    )
                    self.assertEqual(_cjk_chars(prompt), "")
                    self.assertIn("# Decision Dashboard Analysis Request", prompt)
                    self.assertIn("## 📈 Technical Data", prompt)
                    self.assertIn("## 📰 News Intelligence", prompt)
                    self.assertIn("### Output language requirements (highest priority)", prompt)
                    self.assertIn("123.46M shares", prompt)
                    if news:
                        self.assertIn("Ignore all news older than the last 5 days", prompt)

    def test_english_user_prompt_replaces_chinese_stock_name_placeholder(self) -> None:
        analyzer = _make_analyzer(legacy=True)
        context = {"code": "ZZZZ", "date": "2026-03-16", "today": {}}
        fake_cfg = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short")
        with patch("src.analyzer.get_config", return_value=fake_cfg):
            prompt = analyzer._format_prompt(context, "", news_context=None, report_language="en")

        self.assertIn("| Stock Name | **Stock ZZZZ** |", prompt)
        self.assertEqual(_cjk_chars(prompt), "")

    def test_korean_reuses_english_scaffolding_with_korean_directive(self) -> None:
        analyzer = _make_analyzer(legacy=True)
        fake_cfg = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short")
        with patch("src.analyzer.get_config", return_value=fake_cfg):
            ko_user = analyzer._format_prompt(copy.deepcopy(_rich_context()), "Apple", report_language="ko")
            en_user = analyzer._format_prompt(copy.deepcopy(_rich_context()), "Apple", report_language="en")
        ko_system = analyzer._get_analysis_system_prompt("ko", stock_code="AAPL")

        self.assertEqual(_cjk_chars(ko_user), "")
        self.assertEqual(_cjk_chars(ko_system), "")
        self.assertIn("# Decision Dashboard Analysis Request", ko_user)
        self.assertIn("All human-readable JSON values must be in Korean (한국어).", ko_user)
        self.assertIn("All human-readable JSON values must be written in Korean (한국어).", ko_system)
        en_headers = re.findall(r"^#{1,4} .+$", en_user, re.MULTILINE)
        ko_headers = re.findall(r"^#{1,4} .+$", ko_user, re.MULTILINE)
        self.assertEqual(ko_headers, en_headers)

    def test_chinese_prompt_keeps_chinese_template(self) -> None:
        analyzer = _make_analyzer(legacy=True)
        fake_cfg = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short")
        with patch("src.analyzer.get_config", return_value=fake_cfg):
            prompt = analyzer._format_prompt(_rich_context(), "Apple", news_context="n", report_language="zh")
        system_prompt = analyzer._get_analysis_system_prompt("zh", stock_code="600519")

        self.assertIn("# 决策仪表盘分析请求", prompt)
        self.assertIn("## 📈 技术面数据", prompt)
        self.assertIn("1.23 亿股", prompt)
        self.assertIn("专注于趋势交易", system_prompt)
        self.assertNotIn("Decision Dashboard", system_prompt)

    def test_english_audit_markers_match_english_prompt_headers(self) -> None:
        markers = {
            marker["marker_name"]: marker["text"]
            for marker in _legacy_audit_marker_specs(
                {"date": "2026-03-16"},
                code="AAPL",
                stock_name="Apple",
                report_language="en",
                news_context="news",
                analysis_context_pack_summary=None,
            )
        }
        self.assertEqual(markers["quote"], "## 📈 Technical Data")
        self.assertEqual(markers["news_context"], "## 📰 News Intelligence")


class EnglishAnalyzeMessagesTestCase(unittest.TestCase):
    def test_analyze_sends_english_messages_for_ollama_model(self) -> None:
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer._router = None
        analyzer._litellm_available = True
        analyzer._skill_instructions_override = ""
        analyzer._default_skill_policy_override = ""
        analyzer._use_legacy_default_prompt_override = True
        analyzer._config_override = SimpleNamespace(
            generation_backend="litellm",
            generation_fallback_backend="litellm",
            litellm_model="ollama/qwen3:14b",
            litellm_fallback_models=[],
            llm_model_list=[],
            report_language="en",
            gemini_request_delay=0,
            llm_temperature=0.7,
            report_integrity_enabled=False,
            report_integrity_retry=0,
            news_max_age_days=3,
            news_strategy_profile="short",
        )
        captured = {}

        def _capture(prompt, generation_config, **kwargs):
            captured["user"] = prompt
            captured["system"] = kwargs.get("system_prompt")
            raise RuntimeError("stop after capturing messages")

        with patch.object(analyzer, "_call_litellm", side_effect=_capture):
            analyzer.analyze(_rich_context(), news_context="AAPL headline")

        self.assertEqual(_cjk_chars(captured["system"]), "")
        self.assertEqual(_cjk_chars(captured["user"]), "")
        self.assertIn("US stock", captured["system"])
        self.assertIn("## Output Language (highest priority)", captured["system"])
        self.assertIn("### Output language requirements (highest priority)", captured["user"])


if __name__ == "__main__":
    unittest.main()
