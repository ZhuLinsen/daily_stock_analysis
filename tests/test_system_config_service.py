# -*- coding: utf-8 -*-
"""Unit tests for system configuration service."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.config import Config
from src.core.config_manager import ConfigManager
from src.services.system_config_service import ConfigConflictError, ConfigImportError, SystemConfigService


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

    def _rewrite_env(self, *lines: str) -> None:
        self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        Config.reset_instance()
        self.manager = ConfigManager(env_path=self.env_path)
        self.service = SystemConfigService(manager=self.manager)

    def test_get_config_returns_raw_sensitive_values(self) -> None:
        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertIn("GEMINI_API_KEY", items)
        self.assertEqual(items["GEMINI_API_KEY"]["value"], "secret-key-value")
        self.assertFalse(items["GEMINI_API_KEY"]["is_masked"])
        self.assertTrue(items["GEMINI_API_KEY"]["raw_value_exists"])

    def test_export_desktop_env_returns_raw_text(self) -> None:
        self.env_path.write_text(
            "# Desktop config\nSTOCK_LIST=600519,000001\n\nGEMINI_API_KEY=secret-key-value\n",
            encoding="utf-8",
        )

        payload = self.service.export_desktop_env()

        self.assertEqual(
            payload["content"],
            "# Desktop config\nSTOCK_LIST=600519,000001\n\nGEMINI_API_KEY=secret-key-value\n",
        )
        self.assertEqual(payload["config_version"], self.manager.get_config_version())

    def test_import_desktop_env_merges_keys_without_deleting_unspecified_values(self) -> None:
        current_version = self.manager.get_config_version()

        payload = self.service.import_desktop_env(
            config_version=current_version,
            content="STOCK_LIST=300750\nCUSTOM_NOTE=desktop backup\n",
            reload_now=False,
        )

        self.assertTrue(payload["success"])
        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["STOCK_LIST"], "300750")
        self.assertEqual(current_map["CUSTOM_NOTE"], "desktop backup")
        self.assertEqual(current_map["GEMINI_API_KEY"], "secret-key-value")

    def test_import_desktop_env_treats_mask_token_as_literal_value(self) -> None:
        current_version = self.manager.get_config_version()

        self.service.import_desktop_env(
            config_version=current_version,
            content="GEMINI_API_KEY=******\n",
            reload_now=False,
        )

        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["GEMINI_API_KEY"], "******")

    def test_import_desktop_env_uses_last_duplicate_assignment(self) -> None:
        current_version = self.manager.get_config_version()

        self.service.import_desktop_env(
            config_version=current_version,
            content="STOCK_LIST=000001\nSTOCK_LIST=300750\n",
            reload_now=False,
        )

        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["STOCK_LIST"], "300750")

    def test_import_desktop_env_allows_empty_assignment(self) -> None:
        current_version = self.manager.get_config_version()

        self.service.import_desktop_env(
            config_version=current_version,
            content="LOG_LEVEL=\n",
            reload_now=False,
        )

        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["LOG_LEVEL"], "")

    def test_import_desktop_env_rejects_empty_or_comment_only_content(self) -> None:
        with self.assertRaises(ConfigImportError):
            self.service.import_desktop_env(
                config_version=self.manager.get_config_version(),
                content="   \n# only comments\n\n",
                reload_now=False,
            )

    def test_import_desktop_env_raises_conflict_for_stale_version(self) -> None:
        with self.assertRaises(ConfigConflictError):
            self.service.import_desktop_env(
                config_version="stale-version",
                content="STOCK_LIST=300750\n",
                reload_now=False,
            )

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

    def test_validate_reports_invalid_public_searxng_toggle(self) -> None:
        validation = self.service.validate(
            items=[{"key": "SEARXNG_PUBLIC_INSTANCES_ENABLED", "value": "maybe"}]
        )
        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_type" for issue in validation["issues"]))

    def test_validate_reports_invalid_feishu_webhook_url(self) -> None:
        validation = self.service.validate(
            items=[{"key": "FEISHU_WEBHOOK_URL", "value": "feishu-hook-without-scheme"}]
        )
        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_url" for issue in validation["issues"]))

    def test_validate_warns_when_feishu_app_credentials_are_used_without_webhook(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "FEISHU_APP_ID", "value": "cli_xxx"},
                {"key": "FEISHU_APP_SECRET", "value": "secret_xxx"},
            ]
        )
        self.assertTrue(validation["valid"])
        self.assertTrue(
            any(
                issue["code"] == "feishu_mode_mismatch"
                and issue["severity"] == "warning"
                for issue in validation["issues"]
            )
        )

    def test_validate_no_warning_when_feishu_cloud_doc_credentials_without_webhook(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "FEISHU_APP_ID", "value": "cli_xxx"},
                {"key": "FEISHU_APP_SECRET", "value": "secret_xxx"},
                {"key": "FEISHU_FOLDER_TOKEN", "value": "folder_xxx"},
            ]
        )
        self.assertTrue(validation["valid"])
        self.assertFalse(
            any(
                issue["code"] == "feishu_mode_mismatch"
                and issue["severity"] == "warning"
                for issue in validation["issues"]
            )
        )

    def test_validate_warns_when_only_folder_token_cleared_with_app_credentials(self) -> None:
        """Clearing FEISHU_FOLDER_TOKEN while app credentials remain should trigger mismatch."""
        old_version = self.manager.get_config_version()
        self.service.update(
            config_version=old_version,
            items=[
                {"key": "FEISHU_APP_ID", "value": "cli_xxx"},
                {"key": "FEISHU_APP_SECRET", "value": "secret_xxx"},
            ],
        )
        validation = self.service.validate(
            items=[
                {"key": "FEISHU_FOLDER_TOKEN", "value": ""},
            ]
        )
        self.assertTrue(validation["valid"])
        self.assertTrue(
            any(
                issue["code"] == "feishu_mode_mismatch"
                and issue["severity"] == "warning"
                for issue in validation["issues"]
            )
        )

    def test_update_persists_public_searxng_toggle(self) -> None:
        old_version = self.manager.get_config_version()
        response = self.service.update(
            config_version=old_version,
            items=[{"key": "SEARXNG_PUBLIC_INSTANCES_ENABLED", "value": "false"}],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["SEARXNG_PUBLIC_INSTANCES_ENABLED"], "false")

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

    def test_validate_preserves_model_based_protocol_inference_for_ollama_channel(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "lab"},
                {"key": "LLM_LAB_MODELS", "value": "ollama/llama3"},
                {"key": "LLM_LAB_API_KEY", "value": ""},
            ]
        )

        self.assertTrue(validation["valid"], validation["issues"])
        self.assertEqual(validation["issues"], [])

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

    def test_validate_reports_unknown_agent_primary_model_for_channels(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "AGENT_LITELLM_MODEL", "value": "openai/gpt-4o"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "AGENT_LITELLM_MODEL" and issue["code"] == "unknown_model" for issue in validation["issues"]))

    def test_validate_accepts_unprefixed_agent_model_when_channel_declares_openai_model(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "AGENT_LITELLM_MODEL", "value": "gpt-4o-mini"},
            ]
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    @patch.object(
        Config,
        "_parse_litellm_yaml",
        return_value=[
            {
                "model_name": "gpt4o",
                "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "sk-test-value"},
            }
        ],
    )
    def test_validate_accepts_unprefixed_agent_model_when_yaml_declares_alias(self, _mock_parse_yaml) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LITELLM_CONFIG", "value": "/tmp/litellm.yaml"},
                {"key": "AGENT_LITELLM_MODEL", "value": "gpt4o"},
            ]
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

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

        report_language_schema = items["REPORT_LANGUAGE"]["schema"]
        self.assertEqual(report_language_schema["validation"]["enum"], ["zh", "en"])
        self.assertEqual(report_language_schema["options"][1]["value"], "en")

        self.assertEqual(items["AGENT_ORCHESTRATOR_TIMEOUT_S"]["schema"]["default_value"], "600")
        self.assertTrue(items["AGENT_DEEP_RESEARCH_BUDGET"]["schema"]["is_editable"])
        self.assertTrue(items["AGENT_EVENT_MONITOR_ENABLED"]["schema"]["is_editable"])

    def test_validate_reports_invalid_select_option(self) -> None:
        validation = self.service.validate(items=[{"key": "AGENT_ARCH", "value": "invalid-mode"}])

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_enum" for issue in validation["issues"]))

    def test_validate_accepts_report_language_english(self) -> None:
        validation = self.service.validate(items=[{"key": "REPORT_LANGUAGE", "value": "en"}])

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_reports_invalid_json(self) -> None:
        validation = self.service.validate(items=[{"key": "AGENT_EVENT_ALERT_RULES_JSON", "value": "[invalid"}])

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_json" for issue in validation["issues"]))

    def test_validate_accepts_blank_optional_json(self) -> None:
        validation = self.service.validate(items=[{"key": "AGENT_EVENT_ALERT_RULES_JSON", "value": ""}])

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_accepts_multiline_json(self) -> None:
        validation = self.service.validate(items=[{
            "key": "AGENT_EVENT_ALERT_RULES_JSON",
            "value": (
                "[\n"
                '  {"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800}\n'
                "]"
            ),
        }])

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_update_minifies_multiline_json_before_storage(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{
                "key": "AGENT_EVENT_ALERT_RULES_JSON",
                "value": (
                    "[\n"
                    '  {"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800}\n'
                    "]"
                ),
            }],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        current_map = self.manager.read_config_map()
        self.assertEqual(
            current_map["AGENT_EVENT_ALERT_RULES_JSON"],
            '[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800}]',
        )

    def test_validate_accepts_legacy_agent_orchestrator_mode_alias(self) -> None:
        validation = self.service.validate(items=[{"key": "AGENT_ORCHESTRATOR_MODE", "value": "strategy"}])

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_get_config_projects_legacy_strategy_aliases_onto_skill_fields(self) -> None:
        self._rewrite_env(
            "AGENT_STRATEGY_DIR=legacy-strategies",
            "AGENT_STRATEGY_AUTOWEIGHT=false",
            "AGENT_STRATEGY_ROUTING=manual",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["AGENT_SKILL_DIR"]["value"], "legacy-strategies")
        self.assertEqual(items["AGENT_SKILL_AUTOWEIGHT"]["value"], "false")
        self.assertEqual(items["AGENT_SKILL_ROUTING"]["value"], "manual")
        self.assertNotIn("AGENT_STRATEGY_DIR", items)
        self.assertNotIn("AGENT_STRATEGY_AUTOWEIGHT", items)
        self.assertNotIn("AGENT_STRATEGY_ROUTING", items)

    def test_get_config_respects_empty_canonical_skill_field_over_legacy_alias(self) -> None:
        self._rewrite_env(
            "AGENT_SKILL_DIR=",
            "AGENT_STRATEGY_DIR=legacy-strategies",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["AGENT_SKILL_DIR"]["value"], "")

    def test_get_config_normalizes_legacy_orchestrator_mode_for_ui(self) -> None:
        self._rewrite_env("AGENT_ORCHESTRATOR_MODE=strategy")

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["AGENT_ORCHESTRATOR_MODE"]["value"], "specialist")
        self.assertEqual(
            items["AGENT_ORCHESTRATOR_MODE"]["schema"]["validation"]["enum"],
            ["quick", "standard", "full", "specialist", "strategy", "skill"],
        )

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

    def test_validate_accepts_minimax_model_as_direct_env_provider(self) -> None:
        """minimax is NOT a managed key provider; it uses LiteLLM direct-env routing."""
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "minimax/MiniMax-M1"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "LITELLM_MODEL", "value": "minimax/MiniMax-M1"},
            ]
        )

        self.assertFalse(any(issue.get("key") == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation.get("issues", [])))

    def test_validate_reports_stale_agent_primary_model_when_all_channels_disabled(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "AGENT_LITELLM_MODEL", "value": "openai/gpt-4o-mini"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "AGENT_LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation["issues"]))

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

    @patch("litellm.completion")
    def test_test_llm_channel_allows_ollama_prefix_without_explicit_protocol(self, mock_completion) -> None:
        mock_completion.return_value = type(
            "MockResponse",
            (),
            {
                "choices": [type("Choice", (), {"message": type("Message", (), {"content": "OK"})()})()],
            },
        )()

        payload = self.service.test_llm_channel(
            name="lab",
            protocol="",
            base_url="http://localhost:11434/v1",
            api_key="",
            models=["ollama/llama3"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_protocol"], "ollama")
        self.assertEqual(payload["resolved_model"], "ollama/llama3")

    @patch("src.services.system_config_service.requests.get")
    def test_discover_llm_channel_models_returns_deduped_ids(self, mock_get) -> None:
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "qwen-plus"},
                {"id": "qwen-plus"},
                {"id": "qwen-turbo"},
            ]
        }
        mock_get.return_value = mock_response

        payload = self.service.discover_llm_channel_models(
            name="dashscope",
            protocol="openai",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="sk-test-value",
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_protocol"], "openai")
        self.assertEqual(payload["models"], ["qwen-plus", "qwen-turbo"])
        mock_get.assert_called_once()
        self.assertEqual(
            mock_get.call_args.args[0],
            "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        )
        self.assertEqual(
            mock_get.call_args.kwargs["headers"]["Authorization"],
            "Bearer sk-test-value",
        )
        self.assertFalse(mock_get.call_args.kwargs["allow_redirects"])

    @patch("src.services.system_config_service.requests.get")
    def test_discover_llm_channel_models_rejects_redirect_responses(self, mock_get) -> None:
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 302
        mock_get.return_value = mock_response

        payload = self.service.discover_llm_channel_models(
            name="dashscope",
            protocol="openai",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="sk-test-value",
        )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["message"], "Model discovery request was redirected")
        self.assertIn("Redirect responses are not allowed", payload["error"])
        self.assertFalse(mock_get.call_args.kwargs["allow_redirects"])

    def test_discover_llm_channel_models_requires_base_url(self) -> None:
        payload = self.service.discover_llm_channel_models(
            name="primary",
            protocol="openai",
            base_url="",
            api_key="sk-test-value",
        )

        self.assertFalse(payload["success"])
        self.assertIn("base URL", payload["error"])
        self.assertEqual(payload["models"], [])

    def test_discover_llm_channel_models_rejects_unsupported_protocol(self) -> None:
        payload = self.service.discover_llm_channel_models(
            name="gemini",
            protocol="gemini",
            base_url="https://example.com/v1",
            api_key="sk-test-value",
        )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["resolved_protocol"], "gemini")
        self.assertIn("does not support /models discovery yet", payload["error"])

    def test_build_llm_models_url_strips_query_and_fragment(self) -> None:
        models_url = SystemConfigService._build_llm_models_url(
            "https://example.com/v1/chat/completions?api-version=1#frag"
        )

        self.assertEqual(models_url, "https://example.com/v1/models")

    def test_validate_reports_invalid_event_rule_semantics(self) -> None:
        validation = self.service.validate(items=[{
            "key": "AGENT_EVENT_ALERT_RULES_JSON",
            "value": '[{"stock_code":"600519","alert_type":"price_cross","status":"bad","direction":"above","price":1800}]',
        }])

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_event_rule" for issue in validation["issues"]))

    def test_validate_rejects_unsupported_event_rule_type(self) -> None:
        validation = self.service.validate(items=[{
            "key": "AGENT_EVENT_ALERT_RULES_JSON",
            "value": '[{"stock_code":"600519","alert_type":"sentiment_shift"}]',
        }])

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_event_rule" for issue in validation["issues"]))

    @patch.object(SystemConfigService, "_reload_runtime_singletons")
    def test_update_with_reload_resets_runtime_singletons(
        self,
        mock_reload_runtime_singletons,
    ) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "STOCK_LIST", "value": "600519"}],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        mock_reload_runtime_singletons.assert_called_once()

    def test_update_with_reload_applies_updated_env_file_when_process_env_is_stale(self) -> None:
        os.environ["STOCK_LIST"] = "600519,000001"

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "STOCK_LIST", "value": "300750,TSLA"}],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        self.assertEqual(Config.get_instance().stock_list, ["300750", "TSLA"])

    def test_update_raises_conflict_for_stale_version(self) -> None:
        with self.assertRaises(ConfigConflictError):
            self.service.update(
                config_version="stale-version",
                items=[{"key": "STOCK_LIST", "value": "600519"}],
                reload_now=False,
            )

    def test_update_appends_news_window_explainability_warning(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "NEWS_STRATEGY_PROFILE", "value": "ultra_short"},
                {"key": "NEWS_MAX_AGE_DAYS", "value": "7"},
            ],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        joined = " | ".join(response["warnings"])
        self.assertIn("effective_days=1", joined)
        self.assertIn("min(profile_days, NEWS_MAX_AGE_DAYS)", joined)

    def test_update_appends_max_workers_warning(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "MAX_WORKERS", "value": "1"}],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        joined = " | ".join(response["warnings"])
        self.assertIn("MAX_WORKERS=1", joined)
        self.assertIn("reload_now=false", joined)

    def test_update_appends_mode_specific_startup_warnings(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "RUN_IMMEDIATELY", "value": "false"},
                {"key": "SCHEDULE_ENABLED", "value": "true"},
                {"key": "SCHEDULE_RUN_IMMEDIATELY", "value": "true"},
            ],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        run_warning = next(
            warning
            for warning in response["warnings"]
            if "RUN_IMMEDIATELY 已写入 .env" in warning
        )
        schedule_warning = next(
            warning
            for warning in response["warnings"]
            if "SCHEDULE_ENABLED" in warning
        )

        self.assertIn("非 schedule 模式", run_warning)
        self.assertNotIn("以 schedule 模式", run_warning)
        self.assertIn("SCHEDULE_RUN_IMMEDIATELY", schedule_warning)
        self.assertIn("不会自动重建 scheduler", schedule_warning)
        self.assertIn("以 schedule 模式重新启动后生效", schedule_warning)
        self.assertNotIn("它属于启动期单次运行配置", schedule_warning)


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
