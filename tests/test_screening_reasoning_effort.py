# -*- coding: utf-8 -*-
"""Screening re-rank exposes a selectable reasoning-effort level, defaulting to high.

The re-rank compares candidates against each other and is the most reasoning-heavy
call in the screening pipeline, so it is worth spending thinking budget on. Providers
that reject the parameter must degrade (one-shot param recovery), not fail the run.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from src.llm.errors import classify_litellm_generation_param_error
from src.llm.reasoning_effort import (
    DEFAULT_ANALYSIS_REASONING_EFFORT,
    DEFAULT_SCREENING_REASONING_EFFORT,
    apply_reasoning_effort,
    resolve_reasoning_effort,
)
from src.services.screening import ranker
from src.services.screening.config import (
    DEFAULT_LLM_REASONING_EFFORT,
    LLM_REASONING_EFFORT_LEVELS,
    normalize_llm_reasoning_effort,
)


class _CapturingLiteLLM:
    """Stand-in for the ``litellm`` module that records completion kwargs."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def completion(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError("stop after capture")

    def __getattr__(self, name):
        return MagicMock()


def _capture(level: str) -> dict:
    fake = _CapturingLiteLLM()
    with patch.dict("sys.modules", {"litellm": fake}):
        try:
            ranker._call_llm(
                "prompt", "sk-test", "openai/glm-5.3", "https://example.invalid/v1",
                reasoning_effort=level,
            )
        except Exception:
            pass
    assert fake.calls, "litellm.completion 未被调用，测试桩失效"
    return fake.calls[0]


class NormalizeReasoningEffortTestCase(unittest.TestCase):
    def test_default_is_high(self) -> None:
        self.assertEqual(DEFAULT_LLM_REASONING_EFFORT, "high")

    def test_accepts_every_declared_level(self) -> None:
        for level in LLM_REASONING_EFFORT_LEVELS:
            self.assertEqual(normalize_llm_reasoning_effort(level), level)

    def test_is_case_and_space_insensitive(self) -> None:
        self.assertEqual(normalize_llm_reasoning_effort("  HIGH "), "high")
        self.assertEqual(normalize_llm_reasoning_effort("Medium"), "medium")

    def test_passthrough_values_mean_do_not_send(self) -> None:
        for value in ("", "auto", "default", None):
            self.assertEqual(normalize_llm_reasoning_effort(value), "")

    def test_none_is_a_real_level_not_a_passthrough(self) -> None:
        # 网关把 none 当成「显式不思考」的档位，与「不下发该参数」语义不同
        self.assertEqual(normalize_llm_reasoning_effort("none"), "none")

    def test_supports_the_levels_above_high(self) -> None:
        # 网关拒绝非法值时会自报合法集合：none, minimal, low, medium, high, xhigh, max
        for level in ("xhigh", "max"):
            with self.subTest(level=level):
                self.assertIn(level, LLM_REASONING_EFFORT_LEVELS)
                self.assertEqual(normalize_llm_reasoning_effort(level), level)

    def test_unknown_value_falls_back_to_default(self) -> None:
        self.assertEqual(normalize_llm_reasoning_effort("bogus"), DEFAULT_LLM_REASONING_EFFORT)


class ReasoningEffortReachesProviderTestCase(unittest.TestCase):
    def test_selected_level_is_sent(self) -> None:
        for level in LLM_REASONING_EFFORT_LEVELS:
            with self.subTest(level=level):
                self.assertEqual(_capture(level).get("reasoning_effort"), level)

    def test_param_is_explicitly_allowed_for_openai_compatible_models(self) -> None:
        # LiteLLM 只对模型表里声明支持的模型放行 reasoning_effort；OpenAI 兼容网关上的
        # 自定义模型名会在本地就抛 UnsupportedParamsError，请求根本发不出去。
        self.assertIn("reasoning_effort", _capture("high").get("allowed_openai_params", []))

    def test_passthrough_omits_both_parameters(self) -> None:
        for level in ("auto", ""):
            with self.subTest(level=level):
                kwargs = _capture(level)
                self.assertNotIn("reasoning_effort", kwargs)
                self.assertNotIn("allowed_openai_params", kwargs)


class ScreeningConfigReasoningEffortTestCase(unittest.TestCase):
    def _from_env(self, value):
        from src.services.screening.config import Config

        env = dict(os.environ)
        env.pop("LLM_REASONING_EFFORT", None)
        if value is not None:
            env["LLM_REASONING_EFFORT"] = value
        with patch.dict(os.environ, env, clear=True):
            return Config.from_env().llm_reasoning_effort

    def test_defaults_to_high_when_unset(self) -> None:
        self.assertEqual(self._from_env(None), "high")

    def test_reads_selected_level_from_env(self) -> None:
        self.assertEqual(self._from_env("minimal"), "minimal")

    def test_auto_disables_the_parameter(self) -> None:
        self.assertEqual(self._from_env("auto"), "")


class UnsupportedParamDegradesTestCase(unittest.TestCase):
    def test_provider_rejection_drops_level_and_allowlist_together(self) -> None:
        exc = Exception(
            "litellm.BadRequestError: OpenAIException - Unrecognized request argument "
            "supplied: reasoning_effort"
        )
        recovery = classify_litellm_generation_param_error(exc)

        self.assertIsNotNone(recovery, "不支持 reasoning_effort 的渠道必须能被一次性摘除后重试")
        # 两者必须同进同退，否则会把一个空放行声明发给不认识它的后端
        self.assertIn("reasoning_effort", recovery.omit_params)
        self.assertIn("allowed_openai_params", recovery.omit_params)

    def test_litellm_local_rejection_is_also_recoverable(self) -> None:
        exc = Exception(
            "litellm.UnsupportedParamsError: openai does not support parameters: "
            "['reasoning_effort'], for model=glm-5.3"
        )
        recovery = classify_litellm_generation_param_error(exc)

        self.assertIsNotNone(recovery)
        self.assertEqual(recovery.reason, "reasoning_effort_unsupported")

    def test_allowlist_rejection_is_recoverable(self) -> None:
        exc = Exception("Unrecognized request argument supplied: allowed_openai_params")
        recovery = classify_litellm_generation_param_error(exc)

        self.assertIsNotNone(recovery)
        self.assertIn("reasoning_effort", recovery.omit_params)
        self.assertIn("allowed_openai_params", recovery.omit_params)

    def test_other_param_recovery_is_unchanged(self) -> None:
        exc = Exception("openai does not support parameters: ['top_p']")
        recovery = classify_litellm_generation_param_error(exc)

        self.assertIsNotNone(recovery)
        self.assertEqual(recovery.omit_params, ("top_p",))


class GlobalReasoningEffortDefaultsTestCase(unittest.TestCase):
    """未配置时：通用分析沿用渠道默认，选股重排偏向 high。"""

    def _resolve(self, value, default):
        env = dict(os.environ)
        env.pop("LLM_REASONING_EFFORT", None)
        if value is not None:
            env["LLM_REASONING_EFFORT"] = value
        with patch.dict(os.environ, env, clear=True):
            return resolve_reasoning_effort(default=default)

    def test_unset_leaves_general_analysis_on_provider_default(self) -> None:
        self.assertEqual(DEFAULT_ANALYSIS_REASONING_EFFORT, "auto")
        self.assertEqual(self._resolve(None, DEFAULT_ANALYSIS_REASONING_EFFORT), "")

    def test_unset_still_leans_high_for_screening(self) -> None:
        self.assertEqual(DEFAULT_SCREENING_REASONING_EFFORT, "high")
        self.assertEqual(self._resolve(None, DEFAULT_SCREENING_REASONING_EFFORT), "high")

    def test_explicit_level_applies_to_both_paths(self) -> None:
        for default in (DEFAULT_ANALYSIS_REASONING_EFFORT, DEFAULT_SCREENING_REASONING_EFFORT):
            with self.subTest(default=default):
                self.assertEqual(self._resolve("medium", default), "medium")

    def test_explicit_auto_silences_both_paths(self) -> None:
        for default in (DEFAULT_ANALYSIS_REASONING_EFFORT, DEFAULT_SCREENING_REASONING_EFFORT):
            with self.subTest(default=default):
                self.assertEqual(self._resolve("auto", default), "")

    def test_apply_is_a_noop_for_blank_level(self) -> None:
        kwargs = {"model": "openai/glm-5.3"}
        apply_reasoning_effort(kwargs, "")
        self.assertEqual(kwargs, {"model": "openai/glm-5.3"})

    def test_apply_preserves_an_existing_allowlist(self) -> None:
        kwargs = {"allowed_openai_params": ["temperature"]}
        apply_reasoning_effort(kwargs, "high")
        self.assertEqual(kwargs["allowed_openai_params"], ["temperature", "reasoning_effort"])


class LevelOrderingTestCase(unittest.TestCase):
    def test_levels_are_declared_from_least_to_most_thinking(self) -> None:
        from src.llm.reasoning_effort import REASONING_EFFORT_LEVELS

        self.assertEqual(
            REASONING_EFFORT_LEVELS,
            ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
        )


class RegistryExposesReasoningEffortTestCase(unittest.TestCase):
    def test_field_is_a_select_with_high_default(self) -> None:
        from src.core.config_registry import get_field_definition

        field = get_field_definition("LLM_REASONING_EFFORT")

        self.assertEqual(field["ui_control"], "select")
        self.assertEqual(field["category"], "ai_model", "全局思考等级应归在 AI 模型分类")
        self.assertEqual(field["default_value"], "auto")
        values = [option["value"] for option in field["options"]]
        for level in LLM_REASONING_EFFORT_LEVELS:
            self.assertIn(level, values, f"下拉里缺少档位 {level}")
        self.assertIn("auto", values)
        # 下拉按「思考最深 -> 最浅」排列，auto 收尾
        self.assertEqual(values[0], "max")
        self.assertEqual(values[-1], "auto")
        self.assertEqual(field["validation"]["enum"], values)


if __name__ == "__main__":
    unittest.main()
