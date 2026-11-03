# -*- coding: utf-8 -*-
"""Temperature omission for model families that reject sampling parameters."""

import unittest

from src.llm.generation_params import resolve_litellm_temperature_directive


class TemperatureOmissionTestCase(unittest.TestCase):
    def assert_omitted(self, model: str) -> None:
        directive = resolve_litellm_temperature_directive(model)
        self.assertTrue(directive.omit_temperature, model)
        self.assertEqual(directive.reason, "provider_default_temperature", model)

    def assert_kept(self, model: str) -> None:
        directive = resolve_litellm_temperature_directive(model)
        self.assertFalse(directive.omit_temperature, model)

    def test_openai_reasoning_families_omit_temperature(self) -> None:
        for model in (
            "openai/gpt-5.5",
            "openai/gpt-6.1-sol",
            "openai/gpt-6.1-terra",
            "gpt-6.1-sol",
            "openai/responses/gpt-6.1-sol",
            "o3-mini",
        ):
            self.assert_omitted(model)

    def test_older_openai_models_keep_temperature(self) -> None:
        for model in ("openai/gpt-4o-mini", "openai/gpt-4.1"):
            self.assert_kept(model)

    def test_claude_models_from_opus_4_7_omit_temperature(self) -> None:
        for model in (
            "anthropic/claude-sonnet-5-5",
            "anthropic/claude-opus-5-5",
            "anthropic/claude-haiku-5-5",
            "anthropic/claude-sonnet-5",
            "anthropic/claude-opus-4-7",
            "anthropic/claude-opus-4-8",
            "anthropic/claude-fable-5-1",
            "bedrock/anthropic.claude-opus-5-5",
            "vertex_ai/claude-opus-5-5@default",
            "openai/claude-sonnet-5-5",
        ):
            self.assert_omitted(model)

    def test_claude_models_before_4_7_keep_temperature(self) -> None:
        for model in (
            "anthropic/claude-sonnet-4-6",
            "anthropic/claude-opus-4-6",
            "anthropic/claude-haiku-4-5",
            "anthropic/claude-sonnet-4-5-20250929",
            "vertex_ai/claude-opus-4-5@20251101",
            "anthropic/claude-3-5-sonnet-20241022",
        ):
            self.assert_kept(model)

    def test_other_providers_keep_temperature(self) -> None:
        for model in (
            "gemini/gemini-3.6-flash",
            "deepseek/deepseek-v4-flash",
            "openai/qwen3.6-plus",
        ):
            self.assert_kept(model)


if __name__ == "__main__":
    unittest.main()
