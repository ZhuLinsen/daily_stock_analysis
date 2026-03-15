# -*- coding: utf-8 -*-
"""Unit tests for system configuration service."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.config import Config
from src.core.config_manager import ConfigManager
from src.services.system_config_service import ConfigConflictError, SystemConfigService


class SystemConfigServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519,000001",
                    "GEMINI_API_KEY=secret-key-value",
                    "SCHEDULE_TIME=18:00",
                    "LOG_LEVEL=INFO",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        Config.reset_instance()

        self.manager = ConfigManager(env_path=self.env_path)
        self.service = SystemConfigService(manager=self.manager)

    def tearDown(self) -> None:
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        self.temp_dir.cleanup()

    def test_get_config_returns_raw_sensitive_values(self) -> None:
        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertIn("GEMINI_API_KEY", items)
        self.assertEqual(items["GEMINI_API_KEY"]["value"], "secret-key-value")
        self.assertFalse(items["GEMINI_API_KEY"]["is_masked"])
        self.assertTrue(items["GEMINI_API_KEY"]["raw_value_exists"])

    def test_update_preserves_masked_secret(self) -> None:
        old_version = self.manager.get_config_version()
        response = self.service.update(
            config_version=old_version,
            items=[
                {"key": "GEMINI_API_KEY", "value": "******"},
                {"key": "STOCK_LIST", "value": "600519,300750"},
            ],
            mask_token="******",
            reload_now=False,
        )

        self.assertTrue(response["success"])
        self.assertEqual(response["applied_count"], 1)
        self.assertEqual(response["skipped_masked_count"], 1)
        self.assertIn("STOCK_LIST", response["updated_keys"])

        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["STOCK_LIST"], "600519,300750")
        self.assertEqual(current_map["GEMINI_API_KEY"], "secret-key-value")

    def test_validate_reports_invalid_time(self) -> None:
        validation = self.service.validate(items=[{"key": "SCHEDULE_TIME", "value": "25:70"}])
        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_format" for issue in validation["issues"]))

    def test_validate_reports_invalid_searxng_url(self) -> None:
        validation = self.service.validate(items=[{"key": "SEARXNG_BASE_URLS", "value": "searx.local,https://ok.example"}])
        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_url" for issue in validation["issues"]))

    def test_validate_reports_invalid_llm_channel_definition(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_API_KEY", "value": ""},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "missing_api_key" for issue in validation["issues"]))

    def test_validate_reports_unknown_primary_model_for_channels(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LITELLM_MODEL", "value": "openai/gpt-4o"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "LITELLM_MODEL" and issue["code"] == "unknown_model" for issue in validation["issues"]))

    @patch.object(
        Config,
        "_parse_litellm_yaml",
        return_value=[{"model_name": "gemini/gemini-2.5-flash", "litellm_params": {"model": "gemini/gemini-2.5-flash"}}],
    )
    def test_validate_skips_channel_checks_when_litellm_yaml_is_active(self, _mock_parse_yaml) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LITELLM_CONFIG", "value": "/tmp/litellm.yaml"},
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_API_KEY", "value": ""},
                {"key": "LITELLM_MODEL", "value": "gemini/gemini-2.5-flash"},
            ]
        )
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_get_config_preserves_labeled_select_options_and_enum_validation(self) -> None:
        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        agent_arch_schema = items["AGENT_ARCH"]["schema"]
        self.assertEqual(agent_arch_schema["options"][0]["value"], "single")
        self.assertEqual(agent_arch_schema["options"][1]["label"], "Multi Agent (Orchestrator)")
        self.assertEqual(agent_arch_schema["validation"]["enum"], ["single", "multi"])

    def test_validate_reports_invalid_select_option(self) -> None:
        validation = self.service.validate(items=[{"key": "AGENT_ARCH", "value": "invalid-mode"}])

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_enum" for issue in validation["issues"]))

    @patch.object(
        Config,
        "_parse_litellm_yaml",
        return_value=[{"model_name": "gemini/gemini-2.5-flash", "litellm_params": {"model": "gemini/gemini-2.5-flash"}}],
    )
    def test_validate_reports_unknown_primary_model_for_litellm_yaml(self, _mock_parse_yaml) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LITELLM_CONFIG", "value": "/tmp/litellm.yaml"},
                {"key": "LITELLM_MODEL", "value": "openai/gpt-4o-mini"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "LITELLM_MODEL" and issue["code"] == "unknown_model" for issue in validation["issues"]))

    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_validate_keeps_channel_checks_when_litellm_yaml_has_no_models(self, _mock_parse_yaml) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LITELLM_CONFIG", "value": "/tmp/litellm.yaml"},
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_API_KEY", "value": ""},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "missing_api_key" for issue in validation["issues"]))

    def test_validate_reports_stale_primary_model_when_all_channels_disabled(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "LITELLM_MODEL", "value": "openai/gpt-4o-mini"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation["issues"]))

    def test_validate_allows_primary_model_when_all_channels_disabled_but_legacy_key_exists(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "OPENAI_API_KEY", "value": "sk-legacy-value"},
                {"key": "LITELLM_MODEL", "value": "openai/gpt-4o-mini"},
            ]
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    @patch("litellm.completion")
    def test_test_llm_channel_returns_success_payload(self, mock_completion) -> None:
        mock_completion.return_value = type(
            "MockResponse",
            (),
            {
                "choices": [type("Choice", (), {"message": type("Message", (), {"content": "OK"})()})()],
            },
        )()

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.deepseek.com/v1",
            api_key="sk-test-value",
            models=["deepseek-chat"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_protocol"], "openai")
        self.assertEqual(payload["resolved_model"], "openai/deepseek-chat")

    @patch("src.search_service.reset_search_service")
    def test_update_with_reload_resets_search_service_singleton(self, mock_reset_search_service) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "STOCK_LIST", "value": "600519"}],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        mock_reset_search_service.assert_called_once()

    def test_update_raises_conflict_for_stale_version(self) -> None:
        with self.assertRaises(ConfigConflictError):
            self.service.update(
                config_version="stale-version",
                items=[{"key": "STOCK_LIST", "value": "600519"}],
                reload_now=False,
            )


    def test_validate_rejects_comma_only_api_key(self) -> None:
        """Whitespace/comma-only api_key must fail validation (P2: parsed-segment check)."""
        for bad_key in (",", " , ", "  ,  ,  "):
            with self.subTest(api_key=bad_key):
                validation = self.service.validate(
                    items=[
                        {"key": "LLM_CHANNELS", "value": "primary"},
                        {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                        {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                        {"key": "LLM_PRIMARY_API_KEY", "value": bad_key},
                    ]
                )
                self.assertFalse(validation["valid"])
                self.assertTrue(
                    any(issue["code"] == "missing_api_key" for issue in validation["issues"]),
                    f"Expected missing_api_key for api_key={bad_key!r}, got: {validation['issues']}",
                )

    def test_validate_rejects_ssrf_metadata_base_url(self) -> None:
        """base_url pointing to cloud metadata service must be blocked (P1: SSRF guard)."""
        for bad_url in (
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://100.100.100.200/latest/meta-data/",
        ):
            with self.subTest(base_url=bad_url):
                validation = self.service.validate(
                    items=[
                        {"key": "LLM_CHANNELS", "value": "primary"},
                        {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                        {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                        {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test"},
                        {"key": "LLM_PRIMARY_BASE_URL", "value": bad_url},
                    ]
                )
                self.assertFalse(validation["valid"])
                self.assertTrue(
                    any(issue["code"] == "ssrf_blocked" for issue in validation["issues"]),
                    f"Expected ssrf_blocked for base_url={bad_url!r}, got: {validation['issues']}",
                )

    def test_validate_allows_localhost_base_url(self) -> None:
        """localhost/LAN base_url must not be blocked (legitimate Ollama endpoints)."""
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "local"},
                {"key": "LLM_LOCAL_PROTOCOL", "value": "ollama"},
                {"key": "LLM_LOCAL_MODELS", "value": "llama3"},
                {"key": "LLM_LOCAL_API_KEY", "value": ""},
                {"key": "LLM_LOCAL_BASE_URL", "value": "http://localhost:11434"},
            ]
        )
        self.assertFalse(any(issue["code"] == "ssrf_blocked" for issue in validation["issues"]))


if __name__ == "__main__":
    unittest.main()
