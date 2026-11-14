# -*- coding: utf-8 -*-
"""Per-stock analysis must recover when the output budget truncates the JSON.

Reasoning models (e.g. DeepSeek V4 series) count thinking tokens against
max_output_tokens. A long chain of thought used the whole 8192 budget
(6974 reasoning tokens), cut the JSON report short and surfaced as
"LLM response is not valid JSON".
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from src.analyzer import (
    GeminiAnalyzer,
    _AllModelsFailedError,
    _is_output_truncated,
    _reasoning_tokens_from_usage,
)
from tests.test_analyzer_prompt_language import _rich_context

_VALID_JSON = json.dumps(
    {
        "stock_name": "Apple",
        "sentiment_score": 55,
        "trend_prediction": "震荡",
        "operation_advice": "观望",
        "analysis_summary": "完整报告",
    },
    ensure_ascii=False,
)
_TRUNCATED_JSON = '{\n  "stock_name": "Apple",\n  "sentiment_score": 44,\n  "dashboard": {\n    "core'


def _usage(completion_tokens: int, reasoning_tokens: int = 0) -> dict:
    return {
        "prompt_tokens": 7000,
        "completion_tokens": completion_tokens,
        "total_tokens": 7000 + completion_tokens,
        "provider_usage_json": json.dumps(
            {"completion_tokens_details": {"reasoning_tokens": reasoning_tokens}}
        ),
    }


def _make_analyzer(max_output_tokens: int = 8192) -> GeminiAnalyzer:
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._router = None
    analyzer._litellm_available = True
    analyzer._skill_instructions_override = ""
    analyzer._default_skill_policy_override = ""
    analyzer._use_legacy_default_prompt_override = True
    analyzer._config_override = SimpleNamespace(
        generation_backend="litellm",
        generation_fallback_backend="litellm",
        litellm_model="deepseek/deepseek-flash",
        litellm_fallback_models=[],
        llm_model_list=[],
        report_language="zh",
        gemini_request_delay=0,
        llm_temperature=0.7,
        llm_analysis_max_output_tokens=max_output_tokens,
        report_integrity_enabled=False,
        report_integrity_retry=0,
        news_max_age_days=3,
        news_strategy_profile="short",
    )
    return analyzer


class TruncationHelpersTestCase(unittest.TestCase):
    def test_truncated_when_completion_reaches_budget(self):
        self.assertTrue(_is_output_truncated(_usage(8192), 8192))
        self.assertFalse(_is_output_truncated(_usage(7934), 8192))
        self.assertFalse(_is_output_truncated({}, 8192))
        self.assertFalse(_is_output_truncated({"completion_tokens": "n/a"}, 8192))

    def test_reasoning_tokens_from_provider_usage(self):
        self.assertEqual(_reasoning_tokens_from_usage(_usage(8192, 6974)), 6974)
        self.assertIsNone(_reasoning_tokens_from_usage({}))
        self.assertIsNone(_reasoning_tokens_from_usage({"provider_usage_json": "not json"}))


class AnalysisTruncationRetryTestCase(unittest.TestCase):
    def _run(self, analyzer, side_effect):
        calls = []

        def _fake_call(prompt, generation_config, **kwargs):
            calls.append((prompt, dict(generation_config)))
            outcome = side_effect[len(calls) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with patch.object(analyzer, "_call_litellm", side_effect=_fake_call), \
                patch("src.analyzer.persist_llm_usage"):
            result = analyzer.analyze(_rich_context(), news_context="headline")
        return result, calls

    def test_truncated_output_is_regenerated_with_double_budget(self):
        analyzer = _make_analyzer()
        result, calls = self._run(
            analyzer,
            [
                _AllModelsFailedError(
                    "invalid json",
                    last_response_text=_TRUNCATED_JSON,
                    last_model="deepseek/deepseek-flash",
                    last_usage=_usage(8192, 6974),
                ),
                (_VALID_JSON, "deepseek/deepseek-flash", _usage(9000, 7000)),
            ],
        )

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["max_output_tokens"], 8192)
        self.assertEqual(calls[1][1]["max_output_tokens"], 16384)
        # The retry regenerates from the original prompt, not from the truncated output.
        self.assertEqual(calls[1][0], calls[0][0])
        self.assertTrue(result.success)
        self.assertEqual(result.sentiment_score, 55)

    def test_configured_budget_is_used(self):
        analyzer = _make_analyzer(max_output_tokens=32768)
        _, calls = self._run(
            analyzer,
            [(_VALID_JSON, "deepseek/deepseek-flash", _usage(5000, 2000))],
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["max_output_tokens"], 32768)

    def test_failed_escalation_keeps_first_response(self):
        analyzer = _make_analyzer()
        result, calls = self._run(
            analyzer,
            [
                (_VALID_JSON, "deepseek/deepseek-flash", _usage(8192, 3000)),
                _AllModelsFailedError("max_tokens too large"),
            ],
        )
        self.assertEqual(len(calls), 2)
        self.assertTrue(result.success)
        self.assertEqual(result.sentiment_score, 55)

    def test_escalates_only_once(self):
        analyzer = _make_analyzer()
        truncated = _AllModelsFailedError(
            "invalid json",
            last_response_text=_TRUNCATED_JSON,
            last_model="deepseek/deepseek-flash",
            last_usage=_usage(16384, 15000),
        )
        first = _AllModelsFailedError(
            "invalid json",
            last_response_text=_TRUNCATED_JSON,
            last_model="deepseek/deepseek-flash",
            last_usage=_usage(8192, 7000),
        )
        result, calls = self._run(analyzer, [first, truncated])
        self.assertEqual(len(calls), 2)
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
