# -*- coding: utf-8 -*-
"""Tests for the Agent models discovery service and endpoint."""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.v1.endpoints import agent
from src.config import Config
from src.services.agent_model_service import list_agent_model_deployments


def _build_config(**overrides):
    config = Config(
        litellm_model="gemini/gemini-2.5-flash",
        litellm_fallback_models=["openai/gpt-4o-mini"],
        llm_model_list=[],
        llm_channels=[],
        litellm_config_path=None,
        llm_models_source="legacy_env",
        openai_base_url=None,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


class AgentModelsApiTestCase(unittest.TestCase):
    def test_models_endpoint_returns_litellm_config_deployments(self) -> None:
        config = _build_config(
            litellm_config_path="config/litellm.yaml",
            llm_models_source="litellm_config",
            llm_model_list=[
                {
                    "model_name": "gemini-primary",
                    "litellm_params": {"model": "gemini/gemini-2.5-flash", "api_key": "secret-1"},
                },
                {
                    "model_name": "openai-fallback",
                    "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "secret-2"},
                },
            ],
        )

        deployments = list_agent_model_deployments(config)

        self.assertEqual(len(deployments), 2)
        self.assertEqual(deployments[0]["source"], "litellm_config")
        self.assertTrue(deployments[0]["is_primary"])
        self.assertFalse("api_key" in str(deployments))

    def test_models_endpoint_returns_channel_deployments_with_api_base(self) -> None:
        config = _build_config(
            llm_channels=[{"name": "openai"}],
            llm_models_source="llm_channels",
            llm_model_list=[
                {
                    "model_name": "openai/gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "secret-1",
                        "api_base": "https://api.example.com/v1",
                    },
                }
            ],
        )

        deployments = list_agent_model_deployments(config)

        self.assertEqual(deployments[0]["source"], "llm_channels")
        self.assertEqual(deployments[0]["api_base"], "https://api.example.com/v1")

    def test_models_endpoint_uses_agent_primary_override_for_primary_marker(self) -> None:
        config = _build_config(
            litellm_model="gemini/gemini-2.5-flash",
            litellm_fallback_models=["openai/gpt-4o-mini"],
            agent_litellm_model="openai/gpt-4o-mini",
            llm_channels=[{"name": "mixed"}],
            llm_models_source="llm_channels",
            llm_model_list=[
                {
                    "model_name": "gemini/gemini-2.5-flash",
                    "litellm_params": {"model": "gemini/gemini-2.5-flash", "api_key": "secret-g"},
                },
                {
                    "model_name": "openai/gpt-4o-mini",
                    "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "secret-o"},
                },
            ],
        )

        deployments = list_agent_model_deployments(config)
        by_model = {item["model"]: item for item in deployments}

        self.assertTrue(by_model["openai/gpt-4o-mini"]["is_primary"])
        self.assertFalse(by_model["openai/gpt-4o-mini"]["is_fallback"])
        self.assertFalse(by_model["gemini/gemini-2.5-flash"]["is_primary"])
        self.assertFalse(by_model["gemini/gemini-2.5-flash"]["is_fallback"])

    def test_models_endpoint_resolves_legacy_placeholders_to_real_models(self) -> None:
        config = _build_config(
            llm_model_list=[
                {"model_name": "__legacy_gemini__", "litellm_params": {"model": "__legacy_gemini__", "api_key": "g-1"}},
                {"model_name": "__legacy_gemini__", "litellm_params": {"model": "__legacy_gemini__", "api_key": "g-2"}},
                {"model_name": "__legacy_openai__", "litellm_params": {"model": "__legacy_openai__", "api_key": "o-1"}},
            ],
            openai_base_url="https://openai.example.com/v1",
        )

        deployments = list_agent_model_deployments(config)

        self.assertEqual(len(deployments), 3)
        self.assertEqual(deployments[0]["model"], "gemini/gemini-2.5-flash")
        self.assertEqual(deployments[1]["model"], "gemini/gemini-2.5-flash")
        self.assertEqual(deployments[2]["model"], "openai/gpt-4o-mini")
        self.assertEqual(deployments[2]["api_base"], "https://openai.example.com/v1")
        self.assertEqual(deployments[2]["source"], "legacy_env")
        self.assertTrue(all(not item["deployment_name"].startswith("__legacy_") for item in deployments))

    def test_models_endpoint_resolves_unprefixed_legacy_openai_model_names(self) -> None:
        config = _build_config(
            litellm_model="gpt-4o-mini",
            litellm_fallback_models=[],
            llm_model_list=[
                {"model_name": "__legacy_openai__", "litellm_params": {"model": "__legacy_openai__", "api_key": "o-1"}},
            ],
            openai_base_url="https://openai.example.com/v1",
        )

        deployments = list_agent_model_deployments(config)

        self.assertEqual(len(deployments), 1)
        self.assertEqual(deployments[0]["model"], "gpt-4o-mini")
        self.assertEqual(deployments[0]["provider"], "openai")
        self.assertEqual(deployments[0]["source"], "legacy_env")
        self.assertEqual(deployments[0]["api_base"], "https://openai.example.com/v1")

    def test_models_endpoint_collapses_legacy_fallbacks_to_single_runtime_deployment(self) -> None:
        config = _build_config(
            llm_model_list=[
                {"model_name": "__legacy_gemini__", "litellm_params": {"model": "__legacy_gemini__", "api_key": "g-12345678"}},
                {"model_name": "__legacy_gemini__", "litellm_params": {"model": "__legacy_gemini__", "api_key": "g-87654321"}},
                {"model_name": "__legacy_openai__", "litellm_params": {"model": "__legacy_openai__", "api_key": "o-12345678"}},
                {"model_name": "__legacy_openai__", "litellm_params": {"model": "__legacy_openai__", "api_key": "o-87654321"}},
            ],
        )

        deployments = list_agent_model_deployments(config)

        self.assertEqual(len(deployments), 3)
        primary = [item for item in deployments if item["is_primary"]]
        fallback = [item for item in deployments if item["is_fallback"]]

        self.assertEqual(len(primary), 2)
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["model"], "openai/gpt-4o-mini")
        self.assertEqual(fallback[0]["deployment_id"], "legacy:openai:0:openai/gpt-4o-mini")
        self.assertEqual(fallback[0]["deployment_name"], "legacy_openai_1")

    def test_models_endpoint_keeps_direct_env_primary_provider_in_legacy_mode(self) -> None:
        config = _build_config(
            litellm_model="cohere/command-r-plus",
            litellm_fallback_models=[],
            llm_model_list=[],
        )

        deployments = list_agent_model_deployments(config)

        self.assertEqual(len(deployments), 1)
        self.assertEqual(deployments[0]["model"], "cohere/command-r-plus")
        self.assertEqual(deployments[0]["provider"], "cohere")
        self.assertEqual(deployments[0]["source"], "legacy_env")
        self.assertTrue(deployments[0]["is_primary"])
        self.assertFalse(deployments[0]["is_fallback"])

    def test_models_endpoint_keeps_direct_env_fallback_provider_in_legacy_mode(self) -> None:
        config = _build_config(
            litellm_fallback_models=["cohere/command-r-plus"],
            llm_model_list=[
                {"model_name": "__legacy_gemini__", "litellm_params": {"model": "__legacy_gemini__", "api_key": "g-12345678"}},
                {"model_name": "__legacy_gemini__", "litellm_params": {"model": "__legacy_gemini__", "api_key": "g-87654321"}},
            ],
        )

        deployments = list_agent_model_deployments(config)

        self.assertEqual(len(deployments), 3)
        fallback = [item for item in deployments if item["is_fallback"]]
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["model"], "cohere/command-r-plus")
        self.assertEqual(fallback[0]["provider"], "cohere")
        self.assertEqual(fallback[0]["deployment_id"], "legacy:cohere:0:cohere/command-r-plus")
        self.assertEqual(fallback[0]["deployment_name"], "legacy_cohere_1")

    def test_models_endpoint_returns_empty_list_when_no_model_is_configured(self) -> None:
        config = _build_config(
            litellm_model="",
            litellm_fallback_models=[],
            llm_model_list=[],
        )

        self.assertEqual(list_agent_model_deployments(config), [])


class AgentModelsEndpointTestCase(unittest.TestCase):
    def test_endpoint_returns_sorted_models_without_secrets(self) -> None:
        config = _build_config(
            llm_channels=[{"name": "primary"}, {"name": "secondary"}],
            llm_model_list=[
                {
                    "model_name": "openai/gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "secret-openai",
                        "api_base": "https://api.openai.example/v1",
                    },
                },
                {
                    "model_name": "gemini/gemini-2.5-flash",
                    "litellm_params": {
                        "model": "gemini/gemini-2.5-flash",
                        "api_key": "secret-gemini",
                    },
                },
            ],
        )

        with patch("api.v1.endpoints.agent.get_config", return_value=config):
            payload = asyncio.run(agent.get_agent_models()).model_dump()

        self.assertEqual(len(payload["models"]), 2)
        self.assertEqual(payload["models"][0]["model"], "gemini/gemini-2.5-flash")
        self.assertTrue(payload["models"][0]["is_primary"])
        self.assertEqual(payload["models"][1]["model"], "openai/gpt-4o-mini")
        self.assertTrue(payload["models"][1]["is_fallback"])
        self.assertNotIn("api_key", str(payload))


class AgentSkillsEndpointTestCase(unittest.TestCase):
    def test_skills_endpoint_returns_skill_metadata_shape(self) -> None:
        config = _build_config()
        skill_manager = SimpleNamespace(
            list_skills=lambda: [
                SimpleNamespace(
                    name="bull_trend",
                    display_name="多头趋势",
                    description="趋势跟随",
                    user_invocable=True,
                    default_priority=20,
                    default_active=True,
                ),
                SimpleNamespace(
                    name="chan_theory",
                    display_name="缠论",
                    description="结构分析",
                    user_invocable=True,
                    default_priority=40,
                    default_active=False,
                ),
            ]
        )

        with patch("api.v1.endpoints.agent.get_config", return_value=config), patch(
            "src.agent.factory.get_skill_manager",
            return_value=skill_manager,
        ):
            payload = asyncio.run(agent.get_skills()).model_dump()

        self.assertEqual(payload["default_skill_id"], "bull_trend")
        self.assertEqual([item["id"] for item in payload["skills"]], ["bull_trend", "chan_theory"])

    def test_legacy_strategies_endpoint_preserves_legacy_field_names(self) -> None:
        config = _build_config()
        skill_manager = SimpleNamespace(
            list_skills=lambda: [
                SimpleNamespace(
                    name="bull_trend",
                    display_name="多头趋势",
                    description="趋势跟随",
                    user_invocable=True,
                    default_priority=20,
                    default_active=True,
                ),
            ]
        )

        with patch("api.v1.endpoints.agent.get_config", return_value=config), patch(
            "src.agent.factory.get_skill_manager",
            return_value=skill_manager,
        ):
            payload = asyncio.run(agent.get_strategies()).model_dump()

        self.assertNotIn("skills", payload)
        self.assertEqual(payload["default_strategy_id"], "bull_trend")
        self.assertEqual(
            payload["strategies"],
            [
                {
                    "id": "bull_trend",
                    "name": "多头趋势",
                    "description": "趋势跟随",
                }
            ],
        )

    def test_chat_request_empty_skills_clears_context_without_triggering_activate_all(self) -> None:
        config = SimpleNamespace(is_agent_available=lambda: True)
        executor = MagicMock()
        executor.chat.return_value = SimpleNamespace(success=True, content="ok", error=None)
        request = agent.ChatRequest(message="hello", skills=[], context={"skills": ["old_skill"]})
        real_get_running_loop = asyncio.get_running_loop

        class _ImmediateLoop:
            def __init__(self, loop):
                self._loop = loop

            def run_in_executor(self, _executor, func):
                future = self._loop.create_future()
                future.set_result(func())
                return future

        with patch("api.v1.endpoints.agent.get_config", return_value=config), patch(
            "api.v1.endpoints.agent._build_executor",
            return_value=executor,
        ) as mock_build_executor, patch(
            "api.v1.endpoints.agent.asyncio.get_running_loop",
            side_effect=lambda: _ImmediateLoop(real_get_running_loop()),
        ):
            payload = asyncio.run(agent.agent_chat(request)).model_dump()

        mock_build_executor.assert_called_once_with(config, None)
        executor.chat.assert_called_once()
        self.assertEqual(executor.chat.call_args.kwargs["context"]["skills"], [])
        self.assertEqual(payload["content"], "ok")
class AgentModelsSourceDetectionTestCase(unittest.TestCase):
    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_load_from_env_marks_channels_as_actual_source_after_yaml_fallback(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "LITELLM_CONFIG": "config/missing.yaml",
            "LLM_CHANNELS": "primary",
            "LLM_PRIMARY_API_KEY": "channel-secret-key",
            "LLM_PRIMARY_MODELS": "openai/gpt-4o-mini",
            "OPENAI_API_KEY": "",
            "AIHUBMIX_KEY": "",
            "GEMINI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_models_source, "llm_channels")
        self.assertEqual(config.llm_model_list[0]["litellm_params"]["model"], "openai/gpt-4o-mini")

    @patch("src.config.setup_env")
    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_load_from_env_marks_legacy_as_actual_source_after_yaml_fallback(
        self,
        _mock_parse_yaml,
        _mock_setup_env,
    ) -> None:
        env = {
            "LITELLM_CONFIG": "config/missing.yaml",
            "LLM_CHANNELS": "",
            "OPENAI_API_KEY": "legacy-openai-key",
            "LITELLM_MODEL": "gpt-4o-mini",
            "AIHUBMIX_KEY": "",
            "GEMINI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
        }

        with patch.dict(os.environ, env, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.llm_models_source, "legacy_env")
        self.assertTrue(config.llm_model_list)
        self.assertEqual(config.llm_model_list[0]["model_name"], "__legacy_openai__")


if __name__ == "__main__":
    unittest.main()
