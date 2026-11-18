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
from src.config import Config
from src.stock_analyzer import StockTrendAnalyzer, TrendAnalysisResult, TrendStatus

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
    def test_default_prompts_use_the_computed_bias_limit_in_all_languages(self) -> None:
        for language in ("zh", "en", "ko"):
            for multiplier, status, expected_limit in (
                (0.0, TrendStatus.BULL, 5.0),
                (1.5, TrendStatus.BULL, 9.0),
                (1.5, TrendStatus.STRONG_BULL, 13.5),
            ):
                with self.subTest(language=language, multiplier=multiplier, status=status):
                    config = Config(bias_threshold=5.0, bias_atr_multiplier=multiplier)
                    trend = TrendAnalysisResult(
                        code="AAPL", current_price=10, atr14=0.6, bias_ma5=7,
                        trend_status=status, trend_strength=80,
                    )
                    with patch("src.stock_analyzer.get_config", return_value=config):
                        StockTrendAnalyzer()._generate_signal(trend)
                    self.assertEqual(trend.effective_bias_threshold, expected_limit)
                    analyzer = _make_analyzer(legacy=True)
                    analyzer._config_override = config
                    context = _rich_context()
                    context["trend_analysis"] = trend.to_dict()
                    system = analyzer._get_analysis_system_prompt(language, stock_code="AAPL")
                    user = analyzer._format_prompt(context, "Apple", report_language=language)
                    self.assertIn("effective_bias_threshold", system)
                    self.assertIn(f"effective_bias_threshold={expected_limit:g}%", user)
                    for obsolete_rule in ("乖离率 <5%", "乖离率 >5%", "超过5%", "Bias <5%", "Bias >5%", "above 5%"):
                        self.assertNotIn(obsolete_rule, system)
                        if expected_limit != 5:
                            self.assertNotIn(obsolete_rule, user)
                    if expected_limit > 7:
                        self.assertIn("Safe range" if language in ("en", "ko") else "安全范围", user)

    def test_default_prompt_without_trend_uses_configured_bias_limit(self) -> None:
        analyzer = _make_analyzer(legacy=True)
        analyzer._config_override = Config(bias_threshold=8.0)
        context = _rich_context()
        del context["trend_analysis"]
        for language in ("zh", "en"):
            user = analyzer._format_prompt(context, "Apple", report_language=language)
            self.assertIn("effective_bias_threshold=8%", user)

    def test_prompt_and_scoring_agree_at_bias_limit_boundaries(self) -> None:
        for base, multiplier, status, limit in (
            (5.0, 1.5, TrendStatus.BULL, 9.0),
            (5.0, 1.5, TrendStatus.STRONG_BULL, 13.5),
            (5.004, 0.0, TrendStatus.BULL, 5.004),
            (1.0, 0.0, TrendStatus.BULL, 1.0),
            (40.0, 0.0, TrendStatus.STRONG_BULL, 60.0),
            (50.0, 0.0, TrendStatus.STRONG_BULL, 75.0),
        ):
            config = Config(bias_threshold=base, bias_atr_multiplier=multiplier)
            for delta in (0.0, 0.001):
                trend = TrendAnalysisResult(
                    code="AAPL", current_price=10, atr14=0.6, bias_ma5=limit + delta,
                    trend_status=status, trend_strength=80,
                )
                with patch("src.stock_analyzer.get_config", return_value=config):
                    StockTrendAnalyzer()._generate_signal(trend)
                context = _rich_context()
                context["trend_analysis"] = trend.to_dict()
                analyzer = _make_analyzer(legacy=True)
                analyzer._config_override = config
                for language in ("zh", "en", "ko"):
                    with self.subTest(base=base, status=status, delta=delta, language=language):
                        prompt = analyzer._format_prompt(context, "Apple", report_language=language)
                        warning = "do not chase!" if language in ("en", "ko") else "严禁追高！"
                        has_scoring_warning = any("严禁追高" in risk for risk in trend.risk_factors)
                        self.assertEqual(has_scoring_warning, delta > 0)
                        self.assertEqual("🚨" in prompt and warning in prompt, has_scoring_warning)

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
        fake_cfg = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short", bias_threshold=5.0)
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
        fake_cfg = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short", bias_threshold=5.0)
        with patch("src.analyzer.get_config", return_value=fake_cfg):
            prompt = analyzer._format_prompt(context, "", news_context=None, report_language="en")

        self.assertIn("| Stock Name | **Stock ZZZZ** |", prompt)
        self.assertEqual(_cjk_chars(prompt), "")

    def test_korean_reuses_english_scaffolding_with_korean_directive(self) -> None:
        analyzer = _make_analyzer(legacy=True)
        fake_cfg = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short", bias_threshold=5.0)
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
        fake_cfg = SimpleNamespace(news_max_age_days=3, news_strategy_profile="short", bias_threshold=5.0)
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
            bias_threshold=5.0,
            bias_atr_multiplier=1.5,
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

        trend = TrendAnalysisResult(
            code="AAPL", current_price=10, atr14=0.6, bias_ma5=7, trend_status=TrendStatus.BULL,
        )
        with patch("src.stock_analyzer.get_config", return_value=analyzer._config_override):
            StockTrendAnalyzer()._generate_signal(trend)
        context = _rich_context()
        context["trend_analysis"] = trend.to_dict()
        with patch.object(analyzer, "_call_litellm", side_effect=_capture):
            analyzer.analyze(context, news_context="AAPL headline")

        self.assertEqual(_cjk_chars(captured["system"]), "")
        # Runtime signal reasons are authored in Chinese; only the prompt
        # scaffolding is subject to the structural language assertion.
        user_scaffolding = captured["user"]
        for reason in trend.signal_reasons + trend.risk_factors:
            user_scaffolding = user_scaffolding.replace(reason, "")
        for value in (trend.trend_status.value, trend.buy_signal.value, trend.ma_alignment, trend.volume_status.value):
            user_scaffolding = user_scaffolding.replace(value, "")
        self.assertEqual(_cjk_chars(user_scaffolding), "")
        self.assertIn("effective_bias_threshold=9%", captured["user"])
        self.assertIn("Safe range", captured["user"])
        self.assertNotIn("above 5%", captured["user"])
        self.assertNotIn("Bias >5%", captured["system"])
        self.assertIn("US stock", captured["system"])
        self.assertIn("## Output Language (highest priority)", captured["system"])
        self.assertIn("### Output language requirements (highest priority)", captured["user"])


if __name__ == "__main__":
    unittest.main()
