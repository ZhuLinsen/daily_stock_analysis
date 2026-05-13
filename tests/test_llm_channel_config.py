# -*- coding: utf-8 -*-
"""Tests for env-based LLM channel parsing."""

import os
import unittest
from unittest.mock import patch

from src.config import (
    ANSPIRE_LLM_BASE_URL_DEFAULT,
    ANSPIRE_LLM_MODEL_DEFAULT,
    Config,
    get_effective_agent_models_to_try,
    get_effective_agent_primary_model,
    get_fixed_litellm_temperature,
    normalize_litellm_temperature,
)


class LLMChannelConfigTestCase(unittest.TestCase):
    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_anspire_key_enables_openai_compatible_legacy_model(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "ANSPIRE_API_KEYS": "sk-anspire-test-value",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.anspire_api_keys, ["sk-anspire-test-value"])
        self.assertEqual(config.openai_api_keys, ["sk-anspire-test-value"])
        self.assertEqual(config.openai_base_url, ANSPIRE_LLM_BASE_URL_DEFAULT)
        self.assertEqual(config.litellm_model, f"openai/{ANSPIRE_LLM_MODEL_DEFAULT}")
        self.assertEqual(config.llm_models_source, "legacy_env")
        params = config.llm_model_list[0]["litellm_params"]
        self.assertEqual(params["model"], "__legacy_openai__")
        self.assertEqual(params["api_base"], ANSPIRE_LLM_BASE_URL_DEFAULT)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_anspire_legacy_overrides_stale_openai_base_url(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "ANSPIRE_API_KEYS": "sk-anspire-test-value",
            "OPENAI_BASE_URL": "https://stale-openai-compatible.example/v1",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.openai_api_keys, ["sk-anspire-test-value"])
        self.assertEqual(config.openai_base_url, ANSPIRE_LLM_BASE_URL_DEFAULT)
        params = config.llm_model_list[0]["litellm_params"]
        self.assertEqual(params["api_base"], ANSPIRE_LLM_BASE_URL_DEFAULT)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_anspire_channel_reuses_shared_key_and_defaults(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "LLM_CHANNELS": "anspire",
            "ANSPIRE_API_KEYS": "sk-anspire-test-value",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_models_source, "llm_channels")
        self.assertEqual(config.llm_channels[0]["protocol"], "openai")
        self.assertEqual(config.llm_channels[0]["api_keys"], ["sk-anspire-test-value"])
        self.assertEqual(config.llm_channels[0]["models"], [f"openai/{ANSPIRE_LLM_MODEL_DEFAULT}"])
        params = config.llm_model_list[0]["litellm_params"]
        self.assertEqual(params["api_base"], ANSPIRE_LLM_BASE_URL_DEFAULT)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_blank_anspire_channel_enabled_uses_shared_disable_flag(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "LLM_CHANNELS": "anspire",
            "LLM_ANSPIRE_ENABLED": "   ",
            "ANSPIRE_LLM_ENABLED": "false",
            "ANSPIRE_API_KEYS": "sk-anspire-test-value",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.openai_api_keys, [])
        self.assertEqual(config.llm_channels, [])
        self.assertEqual(config.llm_model_list, [])

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_disabled_anspire_channel_does_not_fall_back_to_legacy(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "LLM_CHANNELS": "anspire",
            "LLM_ANSPIRE_ENABLED": "false",
            "ANSPIRE_API_KEYS": "sk-anspire-test-value",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.openai_api_keys, [])
        self.assertEqual(config.llm_channels, [])
        self.assertEqual(config.llm_model_list, [])

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_protocol_prefixes_bare_model_names(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "LLM_CHANNELS": "primary",
            "LLM_PRIMARY_PROTOCOL": "deepseek",
            "LLM_PRIMARY_BASE_URL": "https://api.deepseek.com/v1",
            "LLM_PRIMARY_API_KEY": "sk-test-value",
            "LLM_PRIMARY_MODELS": "deepseek-chat",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_models_source, "llm_channels")
        self.assertEqual(config.llm_channels[0]["protocol"], "deepseek")
        self.assertEqual(config.llm_channels[0]["models"], ["deepseek/deepseek-chat"])
        self.assertEqual(config.llm_model_list[0]["litellm_params"]["model"], "deepseek/deepseek-chat")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_openai_compatible_channel_prefixes_non_provider_slash_models(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "LLM_CHANNELS": "siliconflow",
            "LLM_SILICONFLOW_PROTOCOL": "openai",
            "LLM_SILICONFLOW_BASE_URL": "https://api.siliconflow.cn/v1",
            "LLM_SILICONFLOW_API_KEY": "sk-test-value",
            "LLM_SILICONFLOW_MODELS": "Qwen/Qwen3-8B,deepseek-ai/DeepSeek-V3",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(
            config.llm_channels[0]["models"],
            ["openai/Qwen/Qwen3-8B", "openai/deepseek-ai/DeepSeek-V3"],
        )

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_alias_prefixed_models_are_canonicalized_once(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "LLM_CHANNELS": "vertex",
            "LLM_VERTEX_PROTOCOL": "vertex_ai",
            "LLM_VERTEX_API_KEY": "sk-test-value",
            "LLM_VERTEX_MODELS": "vertexai/gemini-2.5-flash",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_channels[0]["models"], ["vertex_ai/gemini-2.5-flash"])
        self.assertEqual(config.llm_model_list[0]["litellm_params"]["model"], "vertex_ai/gemini-2.5-flash")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_minimax_prefixed_models_are_not_rewritten_for_openai_compatible_channels(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "LLM_CHANNELS": "primary",
            "LLM_PRIMARY_PROTOCOL": "openai",
            "LLM_PRIMARY_BASE_URL": "https://api.example.com/v1",
            "LLM_PRIMARY_API_KEY": "sk-test-value",
            "LLM_PRIMARY_MODELS": "minimax/MiniMax-M1",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_channels[0]["models"], ["minimax/MiniMax-M1"])
        self.assertEqual(config.llm_model_list[0]["litellm_params"]["model"], "minimax/MiniMax-M1")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_disabled_channel_is_skipped(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "LLM_CHANNELS": "primary",
            "LLM_PRIMARY_PROTOCOL": "openai",
            "LLM_PRIMARY_ENABLED": "false",
            "LLM_PRIMARY_API_KEY": "sk-test-value",
            "LLM_PRIMARY_MODELS": "gpt-4o-mini",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_channels, [])
        self.assertEqual(config.llm_model_list, [])

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_local_ollama_channel_can_skip_api_key(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "LLM_CHANNELS": "local",
            "LLM_LOCAL_PROTOCOL": "ollama",
            "LLM_LOCAL_BASE_URL": "http://127.0.0.1:11434",
            "LLM_LOCAL_API_KEY": "",
            "LLM_LOCAL_MODELS": "llama3.2",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_models_source, "llm_channels")
        params = config.llm_model_list[0]["litellm_params"]
        self.assertEqual(params["model"], "ollama/llama3.2")
        self.assertNotIn("api_key", params)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_llm_temperature_falls_back_to_legacy_provider_temperature(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "GEMINI_API_KEY": "secret-key-value",
            "GEMINI_TEMPERATURE": "0.15",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.litellm_model, "gemini/gemini-3.1-pro-preview")
        self.assertAlmostEqual(config.llm_temperature, 0.15)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    @patch("src.config.logger.warning")
    def test_deepseek_key_defaults_to_legacy_chat_model_with_deprecation_warning(
        self,
        mock_warning,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "DEEPSEEK_API_KEY": "sk-test-value",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.litellm_model, "deepseek/deepseek-chat")
        mock_warning.assert_called_once_with(
            "Deprecation warning:\n"
            "deepseek-chat will be deprecated on 2026-07-24,\n"
            "please migrate to deepseek-v4-flash."
        )

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    @patch("src.config.logger.warning")
    def test_explicit_deepseek_litellm_model_is_preserved(
        self,
        mock_warning,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "DEEPSEEK_API_KEY": "sk-test-value",
            "LITELLM_MODEL": "deepseek/deepseek-chat",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.litellm_model, "deepseek/deepseek-chat")
        mock_warning.assert_not_called()

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    @patch("src.config.logger.warning")
    def test_deepseek_key_does_not_warn_when_channels_take_precedence(
        self,
        mock_warning,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "DEEPSEEK_API_KEY": "sk-test-value",
            "LLM_CHANNELS": "primary",
            "LLM_PRIMARY_PROTOCOL": "deepseek",
            "LLM_PRIMARY_API_KEY": "sk-channel-value",
            "LLM_PRIMARY_MODELS": "deepseek-v4-flash",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_models_source, "llm_channels")
        mock_warning.assert_not_called()

    @patch("src.config.setup_env")
    @patch.object(
        Config,
        "_parse_litellm_yaml",
        return_value=[
            {
                "model_name": "primary",
                "litellm_params": {
                    "model": "deepseek/deepseek-v4-flash",
                    "api_key": "sk-yaml-value",
                },
            }
        ],
    )
    @patch("src.config.logger.warning")
    def test_deepseek_key_does_not_warn_when_litellm_yaml_takes_precedence(
        self,
        mock_warning,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "DEEPSEEK_API_KEY": "sk-test-value",
            "LITELLM_CONFIG": "/tmp/litellm.yaml",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_models_source, "litellm_config")
        mock_warning.assert_not_called()

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_llm_temperature_prefers_unified_setting_when_present(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "GEMINI_API_KEY": "secret-key-value",
            "GEMINI_TEMPERATURE": "0.15",
            "LLM_TEMPERATURE": "0.35",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertAlmostEqual(config.llm_temperature, 0.35)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_llm_temperature_falls_back_to_openai_temperature(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "LLM_CHANNELS": "primary",
            "LLM_PRIMARY_PROTOCOL": "openai",
            "LLM_PRIMARY_API_KEY": "sk-test",
            "LLM_PRIMARY_MODELS": "gpt-4o",
            "LITELLM_MODEL": "openai/gpt-4o",
            "OPENAI_TEMPERATURE": "0.42",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertAlmostEqual(config.llm_temperature, 0.42)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_llm_temperature_falls_back_to_any_legacy_when_provider_mismatch(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "LLM_CHANNELS": "primary",
            "LLM_PRIMARY_PROTOCOL": "openai",
            "LLM_PRIMARY_API_KEY": "sk-test",
            "LLM_PRIMARY_MODELS": "gpt-4o",
            "LITELLM_MODEL": "openai/gpt-4o",
            "ANTHROPIC_TEMPERATURE": "0.55",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertAlmostEqual(config.llm_temperature, 0.55)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_llm_temperature_ignores_invalid_value(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "GEMINI_API_KEY": "secret-key-value",
            "LLM_TEMPERATURE": "high",
            "GEMINI_TEMPERATURE": "0.25",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertAlmostEqual(config.llm_temperature, 0.25)

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_kimi_k26_keeps_raw_configured_temperature(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "OPENAI_API_KEY": "sk-test-value",
            "OPENAI_MODEL": "kimi-k2.6",
            "LLM_TEMPERATURE": "0.7",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.litellm_model, "openai/kimi-k2.6")
        self.assertAlmostEqual(config.llm_temperature, 0.7)

    def test_kimi_k26_temperature_normalization_handles_provider_wrappers(self) -> None:
        self.assertAlmostEqual(get_fixed_litellm_temperature("moonshot/kimi-k2.6"), 1.0)
        self.assertAlmostEqual(normalize_litellm_temperature("openai/moonshot/kimi-k2.6", 0.2), 1.0)
        self.assertAlmostEqual(normalize_litellm_temperature("openai/kimi-k2.6-preview", 0.2), 1.0)
        self.assertAlmostEqual(
            normalize_litellm_temperature(
                "openai/kimi-k2.6-preview",
                0.2,
                request_overrides={"extra_body": {"thinking": {"type": "disabled"}}},
            ),
            0.6,
        )
        self.assertAlmostEqual(normalize_litellm_temperature("openai/gpt-4o-mini", 0.2), 0.2)

    def test_kimi_k26_temperature_normalization_resolves_litellm_yaml_alias(self) -> None:
        model_list = [
            {
                "model_name": "kimi_router",
                "litellm_params": {
                    "model": "openai/kimi-k2.6",
                    "api_key": "sk-yaml-value",
                },
            }
        ]

        self.assertAlmostEqual(get_fixed_litellm_temperature("kimi_router", model_list=model_list), 1.0)
        self.assertAlmostEqual(
            normalize_litellm_temperature("kimi_router", 0.2, model_list=model_list),
            1.0,
        )

    def test_kimi_k26_temperature_normalization_uses_non_thinking_yaml_alias_temperature(self) -> None:
        model_list = [
            {
                "model_name": "kimi_router",
                "litellm_params": {
                    "model": "openai/kimi-k2.6",
                    "api_key": "sk-yaml-value",
                    "extra_body": {"thinking": {"type": "disabled"}},
                },
            }
        ]

        self.assertAlmostEqual(
            get_fixed_litellm_temperature("kimi_router", model_list=model_list),
            0.6,
        )
        self.assertAlmostEqual(
            normalize_litellm_temperature("kimi_router", 0.2, model_list=model_list),
            0.6,
        )

    def test_kimi_k26_temperature_normalization_uses_non_thinking_yaml_wire_model_without_model_name(self) -> None:
        model_list = [
            {
                "litellm_params": {
                    "model": "openai/kimi-k2.6",
                    "api_key": "sk-yaml-value",
                    "extra_body": {"thinking": {"type": "disabled"}},
                },
            }
        ]

        self.assertAlmostEqual(
            get_fixed_litellm_temperature("openai/kimi-k2.6", model_list=model_list),
            0.6,
        )
        self.assertAlmostEqual(
            normalize_litellm_temperature("openai/kimi-k2.6", 0.2, model_list=model_list),
            0.6,
        )

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_local_openai_compatible_channel_defaults_to_openai_protocol(self, _mock_parse_yaml, _mock_setup_env) -> None:
        """Localhost channels without explicit protocol should default to openai, not ollama."""
        env = {
            "LLM_CHANNELS": "local",
            "LLM_LOCAL_BASE_URL": "http://127.0.0.1:8000/v1",
            "LLM_LOCAL_API_KEY": "not-needed",
            "LLM_LOCAL_MODELS": "my-model",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        params = config.llm_model_list[0]["litellm_params"]
        self.assertEqual(params["model"], "openai/my-model")
        self.assertEqual(config.llm_channels[0]["protocol"], "openai")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_agent_model_empty_inherits_primary_model(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "OPENAI_API_KEY": "sk-test-value",
            "OPENAI_MODEL": "gpt-4o-mini",
            "AGENT_LITELLM_MODEL": "",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.agent_litellm_model, "")
        self.assertEqual(get_effective_agent_primary_model(config), "openai/gpt-4o-mini")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_agent_model_without_provider_prefix_is_normalized(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "OPENAI_API_KEY": "sk-test-value",
            "OPENAI_MODEL": "gpt-4o-mini",
            "AGENT_LITELLM_MODEL": "deepseek-chat",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.agent_litellm_model, "openai/deepseek-chat")
        self.assertEqual(get_effective_agent_primary_model(config), "openai/deepseek-chat")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_agent_models_to_try_are_deduped_in_order(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "OPENAI_API_KEY": "sk-test-value",
            "LITELLM_MODEL": "gemini/gemini-2.5-flash",
            "AGENT_LITELLM_MODEL": "openai/gpt-4o-mini",
            "LITELLM_FALLBACK_MODELS": "openai/gpt-4o-mini,openai/gpt-4o-mini,gemini/gemini-2.5-flash",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(
            get_effective_agent_models_to_try(config),
            ["openai/gpt-4o-mini", "gemini/gemini-2.5-flash"],
        )

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_agent_models_to_try_dedupes_semantically_equivalent_openai_models(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "OPENAI_API_KEY": "sk-test-value",
            "LITELLM_MODEL": "gemini/gemini-2.5-flash",
            "AGENT_LITELLM_MODEL": "gpt-4o-mini",
            "LITELLM_FALLBACK_MODELS": "openai/gpt-4o-mini,gpt-4o-mini",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(
            get_effective_agent_models_to_try(config),
            ["openai/gpt-4o-mini"],
        )

    @patch("src.config.setup_env")
    @patch.object(
        Config,
        "_parse_litellm_yaml",
        return_value=[
            {
                "model_name": "gpt4o",
                "litellm_params": {
                    "model": "openai/gpt-4o-mini",
                    "api_key": "sk-test-value",
                },
            }
        ],
    )
    def test_agent_model_preserves_yaml_alias_without_provider_prefix(self, _mock_parse_yaml, _mock_setup_env) -> None:
        env = {
            "LITELLM_CONFIG": "/tmp/litellm.yaml",
            "AGENT_LITELLM_MODEL": "gpt4o",
            "LITELLM_FALLBACK_MODELS": "openai/gpt-4o-mini",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.agent_litellm_model, "gpt4o")
        self.assertEqual(get_effective_agent_primary_model(config), "gpt4o")
        self.assertEqual(
            get_effective_agent_models_to_try(config),
            ["gpt4o", "openai/gpt-4o-mini"],
        )


if __name__ == "__main__":
    unittest.main()
