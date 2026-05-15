# -*- coding: utf-8 -*-
"""Unit tests for system configuration service."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import Mock, patch

import requests

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.config import ANSPIRE_LLM_MODEL_DEFAULT, Config
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

    @staticmethod
    def _mock_completion_response(content: str = "OK", tool_calls=None):
        message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    def test_get_config_returns_raw_sensitive_values(self) -> None:
        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertIn("GEMINI_API_KEY", items)
        self.assertEqual(items["GEMINI_API_KEY"]["value"], "secret-key-value")
        self.assertFalse(items["GEMINI_API_KEY"]["is_masked"])
        self.assertTrue(items["GEMINI_API_KEY"]["raw_value_exists"])

    def test_get_setup_status_reports_required_gaps_for_empty_config(self) -> None:
        self._rewrite_env("")

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        self.assertFalse(status["is_complete"])
        self.assertFalse(status["ready_for_smoke"])
        self.assertEqual(status["next_step_key"], "llm_primary")
        self.assertIn("llm_primary", status["required_missing_keys"])
        self.assertIn("stock_list", status["required_missing_keys"])

    def test_get_setup_status_marks_minimal_config_complete(self) -> None:
        self._rewrite_env(
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertTrue(status["is_complete"])
        self.assertTrue(status["ready_for_smoke"])
        self.assertEqual(checks["llm_primary"]["status"], "configured")
        self.assertEqual(checks["llm_agent"]["status"], "inherited")
        self.assertEqual(checks["stock_list"]["status"], "configured")
        self.assertEqual(checks["notification"]["status"], "optional")

    def test_get_setup_status_accepts_anspire_one_key_llm(self) -> None:
        self._rewrite_env(
            "ANSPIRE_API_KEYS=sk-anspire-test-value",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertTrue(status["is_complete"])
        self.assertEqual(checks["llm_primary"]["status"], "configured")
        self.assertIn("openai/Doubao-Seed-2.0-lite", checks["llm_primary"]["message"])

    def test_get_setup_status_treats_blank_anspire_channel_enabled_as_shared_disable(self) -> None:
        self._rewrite_env(
            "LLM_CHANNELS=anspire",
            "LLM_ANSPIRE_ENABLED=",
            "ANSPIRE_LLM_ENABLED=false",
            "ANSPIRE_API_KEYS=sk-anspire-test-value",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertFalse(status["is_complete"])
        self.assertEqual(checks["llm_primary"]["status"], "needs_action")
        self.assertIn("llm_primary", status["required_missing_keys"])

    def test_get_setup_status_respects_disabled_anspire_channel_without_legacy_fallback(self) -> None:
        self._rewrite_env(
            "LLM_CHANNELS=anspire",
            "LLM_ANSPIRE_ENABLED=false",
            "ANSPIRE_API_KEYS=sk-anspire-test-value",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertFalse(status["is_complete"])
        self.assertEqual(checks["llm_primary"]["status"], "needs_action")
        self.assertIn("llm_primary", status["required_missing_keys"])

    def test_get_setup_status_accepts_direct_env_primary_without_provider_key(self) -> None:
        self._rewrite_env(
            "LITELLM_MODEL=minimax/MiniMax-M1",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertTrue(status["is_complete"])
        self.assertEqual(checks["llm_primary"]["status"], "configured")
        self.assertEqual(checks["llm_agent"]["status"], "inherited")

    def test_get_setup_status_matches_notification_channel_requirements(self) -> None:
        base_lines = [
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
            "STOCK_LIST=600519",
        ]

        self._rewrite_env(*base_lines, "PUSHOVER_USER_KEY=user-key")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        pushover_partial = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(pushover_partial["status"], "optional")

        self._rewrite_env(*base_lines, "PUSHOVER_USER_KEY=user-key", "PUSHOVER_API_TOKEN=app-token")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        pushover_complete = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(pushover_complete["status"], "configured")

        self._rewrite_env(*base_lines, "SLACK_BOT_TOKEN=xoxb-test", "SLACK_CHANNEL_ID=C123")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        slack_complete = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(slack_complete["status"], "configured")

        self._rewrite_env(*base_lines, "ASTRBOT_URL=https://astrbot.example/webhook")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        astrbot_complete = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(astrbot_complete["status"], "configured")

        self._rewrite_env(*base_lines, "NTFY_URL=https://ntfy.sh/dsa-topic")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        ntfy_complete = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(ntfy_complete["status"], "configured")

        self._rewrite_env(*base_lines, "NTFY_URL=https://ntfy.sh")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        ntfy_without_topic = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(ntfy_without_topic["status"], "optional")

        self._rewrite_env(*base_lines, "GOTIFY_URL=https://gotify.example")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        gotify_partial = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(gotify_partial["status"], "optional")

        self._rewrite_env(*base_lines, "GOTIFY_URL=https://gotify.example", "GOTIFY_TOKEN=app-token")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        gotify_complete = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(gotify_complete["status"], "configured")

        self._rewrite_env(*base_lines, "GOTIFY_URL=https://gotify.example/message", "GOTIFY_TOKEN=app-token")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        gotify_with_message = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(gotify_with_message["status"], "optional")

    def test_get_setup_status_uses_runtime_env_without_reloading_singletons(self) -> None:
        self._rewrite_env("")

        with patch.dict(
            os.environ,
            {
                "LITELLM_MODEL": "gemini/gemini-3-flash-preview",
                "GEMINI_API_KEY": "runtime-secret",
                "STOCK_LIST": "600519",
            },
            clear=True,
        ), patch("src.services.system_config_service.Config.reset_instance") as mock_reset, \
             patch("src.services.system_config_service.setup_env") as mock_setup_env:
            status = self.service.get_setup_status()

        self.assertTrue(status["is_complete"])
        mock_reset.assert_not_called()
        mock_setup_env.assert_not_called()

    def test_get_setup_status_storage_check_does_not_create_database_parent(self) -> None:
        missing_parent = Path(self.temp_dir.name) / "missing-data"
        db_path = missing_parent / "stock_analysis.db"
        self._rewrite_env(
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
            "STOCK_LIST=600519",
            f"DATABASE_PATH={db_path}",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        storage_check = next(check for check in status["checks"] if check["key"] == "storage")
        self.assertEqual(storage_check["status"], "configured")
        self.assertFalse(missing_parent.exists())

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

    def test_validate_reports_ntfy_url_without_topic(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NTFY_URL", "value": "https://ntfy.sh"}]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NTFY_URL" and issue["code"] == "invalid_ntfy_url"
                for issue in validation["issues"]
            )
        )

    def test_validate_reports_gotify_url_with_message_endpoint(self) -> None:
        validation = self.service.validate(
            items=[{"key": "GOTIFY_URL", "value": "https://gotify.example/message"}]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "GOTIFY_URL" and issue["code"] == "invalid_gotify_url"
                for issue in validation["issues"]
            )
        )

    def test_validate_reports_invalid_notification_route_channel(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NOTIFICATION_REPORT_CHANNELS", "value": "wechat,not-a-channel,email"}]
        )
        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NOTIFICATION_REPORT_CHANNELS"
                and issue["code"] == "invalid_allowed_value"
                for issue in validation["issues"]
            )
        )

    def test_validate_reports_invalid_notification_quiet_hours(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NOTIFICATION_QUIET_HOURS", "value": "9:00-18:00"}]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NOTIFICATION_QUIET_HOURS"
                and issue["code"] == "invalid_format"
                for issue in validation["issues"]
            )
        )

    def test_validate_reports_invalid_notification_timezone(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NOTIFICATION_TIMEZONE", "value": "Mars/Olympus"}]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NOTIFICATION_TIMEZONE"
                and issue["code"] == "invalid_timezone"
                for issue in validation["issues"]
            )
        )

    def test_validate_reports_invalid_notification_min_severity(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NOTIFICATION_MIN_SEVERITY", "value": "notice"}]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NOTIFICATION_MIN_SEVERITY"
                and issue["code"] == "invalid_enum"
                for issue in validation["issues"]
            )
        )

    def test_validate_warns_daily_digest_is_reserved(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NOTIFICATION_DAILY_DIGEST_ENABLED", "value": "true"}]
        )

        self.assertTrue(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NOTIFICATION_DAILY_DIGEST_ENABLED"
                and issue["code"] == "reserved_notification_daily_digest"
                and issue["severity"] == "warning"
                for issue in validation["issues"]
            )
        )

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

    def test_validate_accepts_deepseek_v4_primary_model_for_channel(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "deepseek"},
                {"key": "LLM_DEEPSEEK_PROTOCOL", "value": "deepseek"},
                {"key": "LLM_DEEPSEEK_BASE_URL", "value": "https://api.deepseek.com"},
                {"key": "LLM_DEEPSEEK_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_DEEPSEEK_MODELS", "value": "deepseek-v4-flash,deepseek-v4-pro"},
                {"key": "LITELLM_MODEL", "value": "deepseek/deepseek-v4-flash"},
            ]
        )

        self.assertTrue(validation["valid"], validation["issues"])
        self.assertEqual(validation["issues"], [])

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

    def test_validate_accepts_cohere_model_as_direct_env_provider(self) -> None:
        """cohere is NOT a managed key provider; it also uses LiteLLM direct-env routing."""
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "LITELLM_MODEL", "value": "cohere/command-r-plus"},
            ]
        )

        self.assertFalse(any(issue.get("key") == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation.get("issues", [])))

    def test_validate_accepts_google_model_as_direct_env_provider(self) -> None:
        """google prefix is not managed by project key buckets and is kept as direct provider routing."""
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "LITELLM_MODEL", "value": "google/gemini-2.5-flash"},
            ]
        )

        self.assertFalse(any(issue.get("key") == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation.get("issues", [])))

    def test_validate_accepts_xai_model_as_direct_env_provider(self) -> None:
        """xai is not a managed provider key and is also preserved as direct runtime source."""
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "LITELLM_MODEL", "value": "xai/grok-beta"},
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

    def test_validate_allows_anspire_channel_with_shared_key_defaults(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "anspire"},
                {"key": "ANSPIRE_API_KEYS", "value": "sk-anspire-test-value"},
            ]
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_treats_blank_anspire_channel_enabled_as_shared_disable(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "anspire"},
                {"key": "LLM_ANSPIRE_ENABLED", "value": "   "},
                {"key": "ANSPIRE_LLM_ENABLED", "value": "false"},
            ]
        )

        self.assertTrue(validation["valid"], validation["issues"])
        self.assertEqual(validation["issues"], [])

    def test_validate_excludes_blank_disabled_anspire_channel_from_runtime_models(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "anspire"},
                {"key": "LLM_ANSPIRE_ENABLED", "value": "   "},
                {"key": "ANSPIRE_LLM_ENABLED", "value": "false"},
                {"key": "ANSPIRE_API_KEYS", "value": "sk-anspire-test-value"},
                {"key": "LITELLM_MODEL", "value": f"openai/{ANSPIRE_LLM_MODEL_DEFAULT}"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation["issues"]))

    def test_validate_excludes_disabled_anspire_channel_from_legacy_runtime_source(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "anspire"},
                {"key": "LLM_ANSPIRE_ENABLED", "value": "false"},
                {"key": "ANSPIRE_API_KEYS", "value": "sk-anspire-test-value"},
                {"key": "LITELLM_MODEL", "value": f"openai/{ANSPIRE_LLM_MODEL_DEFAULT}"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation["issues"]))

    @staticmethod
    def _mock_http_response(status_code: int, json_body: Optional[Dict[str, Any]] = None):
        response = Mock()
        response.status_code = status_code
        response.text = "ok" if status_code == 200 else "error"
        response.json.return_value = json_body or {"errcode": 0}
        return response

    def _notification_test_env(self):
        return patch.dict(os.environ, {"ENV_FILE": str(self.env_path)}, clear=True)

    @patch("src.notification_sender.wechat_sender.requests.post")
    def test_test_notification_channel_uses_temporary_items_without_persisting(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200, {"errcode": 0})

        with self._notification_test_env():
            before_instance = Config.get_instance()
            payload = self.service.test_notification_channel(
                channel="wechat",
                items=[{"key": "WECHAT_WEBHOOK_URL", "value": "https://qyapi.example.com/cgi-bin/webhook/send?key=secret"}],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )
            self.assertIs(Config.get_instance(), before_instance)

        self.assertTrue(payload["success"])
        self.assertEqual(payload["attempts"][0]["latency_ms"] >= 0, True)
        self.assertIn("key=***", payload["attempts"][0]["target"])
        self.assertNotIn("WECHAT_WEBHOOK_URL", self.env_path.read_text(encoding="utf-8"))
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 3)

    def test_test_notification_channel_reports_missing_config(self) -> None:
        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="telegram",
                items=[{"key": "TELEGRAM_BOT_TOKEN", "value": "token"}],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "config_missing")
        self.assertIn("TELEGRAM_CHAT_ID", payload["message"])

    @patch("src.notification_sender.wechat_sender.requests.post")
    def test_test_notification_channel_skips_masked_secret_overwrite(self, mock_post) -> None:
        self._rewrite_env("WECHAT_WEBHOOK_URL=https://saved.example.com/hook?key=savedsecret")
        mock_post.return_value = self._mock_http_response(200, {"errcode": 0})

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="wechat",
                items=[{"key": "WECHAT_WEBHOOK_URL", "value": "******"}],
                mask_token="******",
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertTrue(payload["success"])
        self.assertEqual(mock_post.call_args[0][0], "https://saved.example.com/hook?key=savedsecret")

    @patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_test_notification_channel_returns_custom_webhook_attempts(self, mock_post) -> None:
        mock_post.side_effect = [
            self._mock_http_response(500),
            self._mock_http_response(200),
        ]

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="custom",
                items=[
                    {
                        "key": "CUSTOM_WEBHOOK_URLS",
                        "value": (
                            "https://example.com/robot/send?access_token=first,"
                            "https://example.com/verylongsecrettoken1234567890"
                        ),
                    }
                ],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertTrue(payload["success"])
        self.assertIn("部分成功", payload["message"])
        self.assertIn("1/2", payload["message"])
        self.assertEqual(len(payload["attempts"]), 2)
        self.assertFalse(payload["attempts"][0]["success"])
        self.assertTrue(payload["attempts"][1]["success"])
        self.assertIn("access_token=***", payload["attempts"][0]["target"])
        self.assertNotIn("verylongsecrettoken1234567890", payload["attempts"][1]["target"])
        self.assertNotIn("access_token=first", str(payload))
        self.assertEqual(mock_post.call_args_list[0].kwargs["timeout"], 4)

    @patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_test_notification_channel_custom_webhook_all_failures_are_retryable(self, mock_post) -> None:
        mock_post.side_effect = [
            self._mock_http_response(500),
            self._mock_http_response(429),
        ]

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="custom",
                items=[
                    {
                        "key": "CUSTOM_WEBHOOK_URLS",
                        "value": (
                            "https://example.com/robot/send?access_token=first,"
                            "https://example.com/robot/send?token=second"
                        ),
                    }
                ],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "send_failed")
        self.assertTrue(payload["retryable"])
        self.assertIn("失败", payload["message"])
        self.assertIn("0/2", payload["message"])
        self.assertEqual(len(payload["attempts"]), 2)
        self.assertTrue(all(attempt["retryable"] for attempt in payload["attempts"]))
        self.assertNotIn("access_token=first", str(payload))
        self.assertNotIn("token=second", str(payload))

    @patch("src.notification_sender.ntfy_sender.requests.post")
    def test_test_notification_channel_supports_ntfy_and_masks_topic_target(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200)

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="ntfy",
                items=[
                    {"key": "NTFY_URL", "value": "https://ntfy.sh/private-topic"},
                    {"key": "NTFY_TOKEN", "value": "secret-token"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertTrue(payload["success"])
        self.assertEqual(mock_post.call_args.args[0], "https://ntfy.sh")
        self.assertEqual(mock_post.call_args.kwargs["json"]["topic"], "private-topic")
        self.assertEqual(mock_post.call_args.kwargs["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 4)
        self.assertIn("https://ntfy.sh/***", payload["attempts"][0]["target"])
        self.assertNotIn("private-topic", str(payload))
        self.assertNotIn("NTFY_URL", self.env_path.read_text(encoding="utf-8"))

    @patch("src.notification_sender.ntfy_sender.requests.post")
    def test_test_notification_channel_rejects_ntfy_url_without_topic(self, mock_post) -> None:
        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="ntfy",
                items=[{"key": "NTFY_URL", "value": "https://ntfy.sh"}],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "config_invalid")
        self.assertEqual(payload["stage"], "config_validation")
        self.assertIn("NTFY_URL", payload["message"])
        mock_post.assert_not_called()

    @patch("src.notification_sender.gotify_sender.requests.post")
    def test_test_notification_channel_supports_gotify_and_keeps_token_out_of_url(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200)

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="gotify",
                items=[
                    {"key": "GOTIFY_URL", "value": "https://gotify.example"},
                    {"key": "GOTIFY_TOKEN", "value": "secret-token"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertTrue(payload["success"])
        self.assertEqual(mock_post.call_args.args[0], "https://gotify.example/message")
        self.assertEqual(mock_post.call_args.kwargs["headers"]["X-Gotify-Key"], "secret-token")
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 4)
        self.assertEqual(payload["attempts"][0]["target"], "https://gotify.example")
        self.assertNotIn("secret-token", str(payload))
        self.assertNotIn("GOTIFY_URL", self.env_path.read_text(encoding="utf-8"))

    @patch("src.notification_sender.gotify_sender.requests.post")
    def test_test_notification_channel_rejects_gotify_message_endpoint(self, mock_post) -> None:
        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="gotify",
                items=[
                    {"key": "GOTIFY_URL", "value": "https://gotify.example/message"},
                    {"key": "GOTIFY_TOKEN", "value": "secret-token"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "config_invalid")
        self.assertEqual(payload["stage"], "config_validation")
        self.assertIn("GOTIFY_URL", payload["message"])
        mock_post.assert_not_called()

    @patch(
        "src.notification_sender.WechatSender.send_to_wechat",
        side_effect=requests.exceptions.Timeout(
            "timeout for https://qyapi.example.com/cgi-bin/webhook/send?key=secret token=abc123"
        ),
    )
    def test_test_notification_channel_classifies_escaped_timeout(self, _mock_send) -> None:
        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="wechat",
                items=[
                    {
                        "key": "WECHAT_WEBHOOK_URL",
                        "value": "https://qyapi.example.com/cgi-bin/webhook/send?key=secret",
                    }
                ],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "timeout")
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["attempts"][0]["error_code"], "timeout")
        self.assertIn("key=***", payload["attempts"][0]["target"])
        self.assertNotIn("key=secret", str(payload))
        self.assertNotIn("abc123", str(payload))

    @patch("src.notification_sender.telegram_sender.requests.post")
    def test_test_notification_channel_masks_short_sensitive_target(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200, {"ok": True})

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="telegram",
                items=[
                    {"key": "TELEGRAM_BOT_TOKEN", "value": "tok123"},
                    {"key": "TELEGRAM_CHAT_ID", "value": "chat-id"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["attempts"][0]["target"], "***")
        self.assertNotIn("tok123", str(payload))

    @patch("src.notification_sender.wechat_sender.requests.post")
    def test_test_notification_channel_strips_url_userinfo_from_target(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200, {"errcode": 0})

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="wechat",
                items=[
                    {
                        "key": "WECHAT_WEBHOOK_URL",
                        "value": "https://user:password@example.com/cgi-bin/webhook/send?key=secret",
                    }
                ],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertTrue(payload["success"])
        target = payload["attempts"][0]["target"]
        self.assertIn("https://example.com/cgi-bin/webhook/send?key=***", target)
        self.assertNotIn("user", target)
        self.assertNotIn("password", target)

    @patch("src.notification_sender.discord_sender.requests.post")
    def test_test_notification_channel_prefers_discord_main_channel_alias(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200)

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="discord",
                items=[
                    {"key": "DISCORD_BOT_TOKEN", "value": "bot-token"},
                    {"key": "DISCORD_MAIN_CHANNEL_ID", "value": "main-channel"},
                    {"key": "DISCORD_CHANNEL_ID", "value": "legacy-channel"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertTrue(payload["success"])
        self.assertIn("/channels/main-channel/messages", mock_post.call_args[0][0])

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
        self.assertEqual(payload["capability_results"], {})
        self.assertEqual(mock_completion.call_count, 1)

    @patch("litellm.completion")
    def test_test_llm_channel_falls_back_to_message_content_when_content_blocks_empty(
        self,
        mock_completion,
    ) -> None:
        mock_completion.return_value = type(
            "MockResponse",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {
                            "content_blocks": [],
                            "message": type("Message", (), {"content": "OK"})(),
                        },
                    )(),
                ]
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

    @patch("litellm.completion")
    def test_test_llm_channel_normalizes_kimi_temperature(self, mock_completion) -> None:
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
            base_url="https://api.moonshot.cn/v1",
            api_key="sk-test-value",
            models=["kimi-k2.6"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_model"], "openai/kimi-k2.6")
        self.assertEqual(mock_completion.call_args.kwargs["temperature"], 1.0)

    def test_update_switching_to_kimi_does_not_rewrite_saved_llm_temperature(self) -> None:
        self._rewrite_env(
            "LITELLM_MODEL=openai/gpt-4o-mini",
            "LLM_TEMPERATURE=0.42",
        )

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "LITELLM_MODEL", "value": "openai/kimi-k2.6"}],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["LITELLM_MODEL"], "openai/kimi-k2.6")
        self.assertEqual(current_map["LLM_TEMPERATURE"], "0.42")

    @patch("litellm.completion")
    def test_test_llm_channel_does_not_persist_normalized_kimi_temperature(self, mock_completion) -> None:
        self._rewrite_env("LLM_TEMPERATURE=0.42")
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
            base_url="https://api.moonshot.cn/v1",
            api_key="sk-test-value",
            models=["kimi-k2.6"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(mock_completion.call_args.kwargs["temperature"], 1.0)
        self.assertEqual(self.manager.read_config_map()["LLM_TEMPERATURE"], "0.42")

    @patch("litellm.completion")
    @patch("src.services.system_config_service.Config._load_from_env")
    def test_test_llm_channel_uses_runtime_temperature_for_non_kimi_models(
        self,
        mock_load_config,
        mock_completion,
    ) -> None:
        mock_load_config.return_value = SimpleNamespace(llm_temperature=0.42)
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
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_model"], "openai/gpt-4o-mini")
        self.assertEqual(mock_completion.call_args.kwargs["temperature"], 0.42)

    @patch("litellm.completion")
    def test_test_llm_channel_classifies_common_failure_scenarios(self, mock_completion) -> None:
        cases = [
            (PermissionError("401 Unauthorized Bearer sk-secret-value"), "auth", "chat_completion", False),
            (TimeoutError("request timed out"), "timeout", "chat_completion", True),
            (Exception("404 model not found: gpt-4o-mini"), "model_not_found", "chat_completion", False),
            (Exception("The model `gpt-4o-mini` does not exist"), "model_not_found", "chat_completion", False),
            (Exception("404 Not Found: page not found"), "network_error", "chat_completion", False),
            (
                type("MockResponse", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": ""})()})()]})(),
                "empty_response",
                "response_parse",
                False,
            ),
            (object(), "format_error", "response_parse", False),
        ]

        for response_or_exc, error_code, stage, retryable in cases:
            with self.subTest(error_code=error_code):
                mock_completion.reset_mock()
                if isinstance(response_or_exc, Exception):
                    mock_completion.side_effect = response_or_exc
                    mock_completion.return_value = None
                else:
                    mock_completion.side_effect = None
                    mock_completion.return_value = response_or_exc

                payload = self.service.test_llm_channel(
                    name="primary",
                    protocol="openai",
                    base_url="https://api.example.com/v1",
                    api_key="sk-secret-value",
                    models=["gpt-4o-mini"],
                )

                self.assertFalse(payload["success"])
                self.assertEqual(payload["error_code"], error_code)
                self.assertEqual(payload["stage"], stage)
                self.assertEqual(payload["retryable"], retryable)
                if error_code == "auth":
                    self.assertNotIn("sk-secret-value", payload["error"])
                if error_code == "format_error":
                    self.assertIn("choices", payload["error"])

    @patch("litellm.completion")
    def test_test_llm_channel_marks_requested_capabilities_skipped_when_base_fails(self, mock_completion) -> None:
        mock_completion.side_effect = PermissionError("401 Unauthorized Bearer sk-secret-value")

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-secret-value",
            models=["gpt-4o-mini"],
            capability_checks=["json", "tools"],
        )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "auth")
        self.assertEqual(payload["details"]["reason"], "api_key_rejected")
        self.assertEqual(payload["capability_results"]["json"]["status"], "skipped")
        self.assertEqual(payload["capability_results"]["tools"]["details"]["reason"], "base_test_failed")
        self.assertEqual(mock_completion.call_count, 1)

    @patch("litellm.completion")
    def test_test_llm_channel_runs_json_and_tools_capability_checks(self, mock_completion) -> None:
        tool_call = SimpleNamespace(function=SimpleNamespace(name="dsa_probe_echo"))
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            self._mock_completion_response('{"status":"ok"}'),
            self._mock_completion_response("", tool_calls=[tool_call]),
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["tools", "json", "tools"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(list(payload["capability_results"].keys()), ["json", "tools"])
        self.assertEqual(payload["capability_results"]["json"]["status"], "passed")
        self.assertEqual(payload["capability_results"]["tools"]["status"], "passed")
        self.assertEqual(mock_completion.call_count, 3)
        self.assertEqual(mock_completion.call_args_list[1].kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(mock_completion.call_args_list[2].kwargs["tool_choice"]["function"]["name"], "dsa_probe_echo")

    @patch("litellm.completion")
    def test_test_llm_channel_reports_json_capability_failures(self, mock_completion) -> None:
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            self._mock_completion_response("not json"),
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["json"],
        )

        self.assertTrue(payload["success"])
        result = payload["capability_results"]["json"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "format_error")
        self.assertEqual(result["details"]["reason"], "non_json")

    @patch("litellm.completion")
    def test_test_llm_channel_runs_stream_capability_check_and_closes_stream(self, mock_completion) -> None:
        class _Stream:
            def __init__(self):
                self.closed = False

            def __iter__(self):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="OK"))])

            def close(self):
                self.closed = True

        stream = _Stream()
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            stream,
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["stream"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["capability_results"]["stream"]["status"], "passed")
        self.assertTrue(stream.closed)
        self.assertTrue(mock_completion.call_args_list[1].kwargs["stream"])

    @patch("litellm.completion")
    def test_test_llm_channel_ignores_stream_close_failures(self, mock_completion) -> None:
        class _Stream:
            def __init__(self):
                self.close_attempted = False

            def __iter__(self):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="OK"))])

            def close(self):
                self.close_attempted = True
                raise RuntimeError("transport already closed")

        stream = _Stream()
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            stream,
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["stream"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["capability_results"]["stream"]["status"], "passed")
        self.assertTrue(stream.close_attempted)

    @patch("litellm.completion")
    def test_test_llm_channel_runs_vision_capability_check(self, mock_completion) -> None:
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            self._mock_completion_response("OK"),
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["vision"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["capability_results"]["vision"]["status"], "passed")
        vision_content = mock_completion.call_args_list[1].kwargs["messages"][0]["content"]
        self.assertEqual(vision_content[1]["type"], "image_url")
        self.assertTrue(vision_content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    @patch("litellm.completion")
    def test_test_llm_channel_classifies_capability_unsupported(self, mock_completion) -> None:
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            Exception("response_format is not supported"),
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["json"],
        )

        result = payload["capability_results"]["json"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "capability_unsupported")
        self.assertEqual(result["details"]["reason"], "capability_unsupported")

    @patch("litellm.completion")
    def test_test_llm_channel_adds_focused_diagnostic_reasons(self, mock_completion) -> None:
        class RateLimitError(Exception):
            pass

        cases = [
            (Exception("account balance insufficient"), "quota", "insufficient_balance"),
            (RateLimitError("account balance insufficient"), "quota", "insufficient_balance"),
            (RateLimitError("insufficient_quota"), "quota", "quota_exceeded"),
            (Exception("account balance insufficient; your request was blocked"), "quota", "insufficient_balance"),
            (RateLimitError("rate limit: your request was blocked by policy"), "quota", "rate_limit"),
            (Exception("DNS lookup failed"), "network_error", "dns_error"),
            (Exception("TLS certificate verify failed"), "network_error", "tls_error"),
            (Exception("Connection refused"), "network_error", "connection_refused"),
            (Exception("connection request was blocked by firewall"), "network_error", "network_error"),
            (Exception("connection blocked by policy"), "network_error", "network_error"),
            (Exception("request blocked by firewall"), "network_error", "network_error"),
            (Exception("blocked"), "network_error", "unknown_error"),
            (Exception("model gpt-4o is not authorized for this account"), "model_not_found", "model_access_denied"),
            (Exception("litellm.APIError: APIError: OpenAIException - Model disabled."), "model_not_found", "model_access_denied"),
            (Exception("Model is disabled for this account"), "model_not_found", "model_access_denied"),
            (
                Exception("litellm.APIError: APIError: OpenAIException - Your request was blocked."),
                "request_blocked",
                "provider_blocked",
            ),
            (Exception("Forbidden: your request was blocked by content policy"), "request_blocked", "provider_blocked"),
            (Exception("blocked by policy"), "request_blocked", "provider_blocked"),
            (Exception("moderation_blocked"), "request_blocked", "provider_blocked"),
            (Exception("LLM Provider NOT provided for model foo"), "model_not_found", "provider_prefix_mismatch"),
        ]

        for exc, error_code, reason in cases:
            with self.subTest(reason=reason):
                mock_completion.reset_mock()
                mock_completion.side_effect = exc
                payload = self.service.test_llm_channel(
                    name="primary",
                    protocol="openai",
                    base_url="https://api.example.com/v1",
                    api_key="sk-test-value",
                    models=["gpt-4o-mini"],
                )

                self.assertFalse(payload["success"])
                self.assertEqual(payload["error_code"], error_code)
                self.assertEqual(payload["details"]["reason"], reason)
                if reason in {"model_access_denied", "provider_blocked"}:
                    self.assertFalse(payload["retryable"])
                    self.assertEqual(payload["details"]["model"], "openai/gpt-4o-mini")
                    self.assertEqual(payload["resolved_model"], "openai/gpt-4o-mini")

    def test_test_llm_channel_reports_comma_only_api_key_as_missing(self) -> None:
        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key=", ,",
            models=["gpt-4o-mini"],
        )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "invalid_config")
        self.assertEqual(payload["details"]["reason"], "missing_api_key")

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
    def test_discover_llm_channel_models_classifies_error_scenarios(self, mock_get) -> None:
        auth_response = Mock(ok=False, status_code=401, text="invalid api key sk-secret-value")
        auth_response.json.return_value = {"error": {"message": "invalid api key sk-secret-value"}}
        not_found_response = Mock(ok=False, status_code=404, text="not found")
        not_found_response.json.return_value = {"error": {"message": "not found"}}
        billing_response = Mock(ok=False, status_code=402, text="account balance insufficient")
        billing_response.json.return_value = {"error": {"message": "account balance insufficient"}}
        billing_rate_limit_response = Mock(ok=False, status_code=429, text="account balance insufficient")
        billing_rate_limit_response.json.return_value = {"error": {"message": "account balance insufficient"}}
        quota_exceeded_response = Mock(ok=False, status_code=429, text="insufficient_quota")
        quota_exceeded_response.json.return_value = {"error": {"message": "insufficient_quota"}}
        quota_blocked_response = Mock(ok=False, status_code=403, text="account balance insufficient; your request was blocked")
        quota_blocked_response.json.return_value = {"error": {"message": "account balance insufficient; your request was blocked"}}
        rate_limit_response = Mock(ok=False, status_code=429, text="too many requests")
        rate_limit_response.json.return_value = {"error": {"message": "too many requests"}}
        blocked_response = Mock(ok=False, status_code=403, text="Forbidden: your request was blocked by content policy")
        blocked_response.json.return_value = {"error": {"message": "Forbidden: your request was blocked by content policy"}}
        connection_blocked_response = Mock(ok=False, status_code=403, text="connection blocked by policy")
        connection_blocked_response.json.return_value = {"error": {"message": "connection blocked by policy"}}
        invalid_json_response = Mock(ok=True, status_code=200, text="<html>bad gateway</html>")
        invalid_json_response.json.side_effect = ValueError("invalid json")

        for response, error_code, stage, retryable, reason in [
            (auth_response, "auth", "model_discovery", False, "api_key_rejected"),
            (not_found_response, "network_error", "model_discovery", False, "endpoint_not_found"),
            (billing_response, "quota", "model_discovery", True, "insufficient_balance"),
            (billing_rate_limit_response, "quota", "model_discovery", True, "insufficient_balance"),
            (quota_exceeded_response, "quota", "model_discovery", True, "quota_exceeded"),
            (quota_blocked_response, "quota", "model_discovery", True, "insufficient_balance"),
            (rate_limit_response, "quota", "model_discovery", True, "rate_limit"),
            (blocked_response, "request_blocked", "model_discovery", False, "provider_blocked"),
            (connection_blocked_response, "network_error", "model_discovery", True, "network_error"),
            (invalid_json_response, "format_error", "response_parse", False, "non_json"),
        ]:
            with self.subTest(error_code=error_code):
                mock_get.return_value = response
                payload = self.service.discover_llm_channel_models(
                    name="dashscope",
                    protocol="openai",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key="sk-secret-value",
                )

                self.assertFalse(payload["success"])
                self.assertEqual(payload["error_code"], error_code)
                self.assertEqual(payload["stage"], stage)
                self.assertEqual(payload["retryable"], retryable)
                self.assertEqual(payload["details"]["reason"], reason)
                if error_code == "auth":
                    self.assertNotIn("sk-secret-value", payload["error"])

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

    def test_build_llm_models_url_supports_deepseek_root_base_url(self) -> None:
        models_url = SystemConfigService._build_llm_models_url("https://api.deepseek.com")

        self.assertEqual(models_url, "https://api.deepseek.com/models")

    def test_validate_reports_invalid_event_rule_semantics(self) -> None:
        validation = self.service.validate(items=[{
            "key": "AGENT_EVENT_ALERT_RULES_JSON",
            "value": '[{"stock_code":"600519","alert_type":"price_cross","status":"bad","direction":"above","price":1800}]',
        }])

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_event_rule" for issue in validation["issues"]))

    def test_validate_accepts_price_change_percent_event_rule(self) -> None:
        validation = self.service.validate(items=[{
            "key": "AGENT_EVENT_ALERT_RULES_JSON",
            "value": (
                '[{"stock_code":"300750","alert_type":"price_change_percent",'
                '"direction":"down","change_pct":3.0}]'
            ),
        }])

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

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

    def test_update_appends_webui_bind_restart_warning(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "WEBUI_HOST", "value": "0.0.0.0"},
                {"key": "WEBUI_PORT", "value": "18000"},
            ],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        bind_warning = next(
            warning
            for warning in response["warnings"]
            if "WEBUI_HOST" in warning and "WEBUI_PORT" in warning
        )

        self.assertIn("启动期监听配置", bind_warning)
        self.assertIn("不会因为本次保存重新绑定监听地址或端口", bind_warning)
        self.assertIn("重启当前进程、Docker 容器或服务管理器后生效", bind_warning)

    def test_update_warns_when_runtime_model_references_are_cleared(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_CHANNELS=deepseek",
            "LLM_DEEPSEEK_PROTOCOL=deepseek",
            "LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com",
            "LLM_DEEPSEEK_API_KEY=sk-test-value",
            "LLM_DEEPSEEK_MODELS=deepseek-chat,deepseek-v4-flash,deepseek-v4-pro",
            "LITELLM_MODEL=deepseek/deepseek-chat",
            "AGENT_LITELLM_MODEL=deepseek/deepseek-v4-pro",
            "LITELLM_FALLBACK_MODELS=deepseek/deepseek-v4-pro,deepseek/deepseek-chat,cohere/command-r-plus",
            "VISION_MODEL=deepseek/deepseek-v4-flash",
        )

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "LLM_DEEPSEEK_MODELS", "value": "deepseek-v4-flash,deepseek-v4-pro"},
                {"key": "LITELLM_MODEL", "value": ""},
                {"key": "AGENT_LITELLM_MODEL", "value": ""},
                {"key": "LITELLM_FALLBACK_MODELS", "value": "deepseek/deepseek-v4-pro,cohere/command-r-plus"},
                {"key": "VISION_MODEL", "value": ""},
            ],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        warning = next(
            warning
            for warning in response["warnings"]
            if "已同步清理失效的运行时模型引用" in warning
        )
        self.assertIn("主模型 / Agent 主模型 / Vision 模型 / 备选模型中的失效项", warning)
        self.assertIn("桌面端导出备份", warning)

    def test_import_desktop_env_restores_runtime_models_after_cleanup(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_CHANNELS=deepseek",
            "LLM_DEEPSEEK_PROTOCOL=deepseek",
            "LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com",
            "LLM_DEEPSEEK_API_KEY=sk-test-value",
            "LLM_DEEPSEEK_MODELS=deepseek-chat,deepseek-v4-flash,deepseek-v4-pro",
            "LITELLM_MODEL=deepseek/deepseek-chat",
            "AGENT_LITELLM_MODEL=deepseek/deepseek-v4-pro",
            "LITELLM_FALLBACK_MODELS=deepseek/deepseek-v4-pro,deepseek/deepseek-chat,cohere/command-r-plus",
            "VISION_MODEL=deepseek/deepseek-v4-flash",
        )

        backup_content = self.service.export_desktop_env()["content"]
        pre_clear_map = dict(self.manager.read_config_map())

        clear_response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "LLM_DEEPSEEK_MODELS", "value": "deepseek-v4-flash"},
                {"key": "LITELLM_MODEL", "value": ""},
                {"key": "AGENT_LITELLM_MODEL", "value": ""},
                {"key": "LITELLM_FALLBACK_MODELS", "value": "deepseek/deepseek-v4-flash"},
                {"key": "VISION_MODEL", "value": ""},
            ],
            reload_now=False,
        )
        self.assertTrue(clear_response["success"])

        cleared_map = self.manager.read_config_map()
        self.assertEqual(cleared_map["LITELLM_MODEL"], "")
        self.assertEqual(cleared_map["AGENT_LITELLM_MODEL"], "")
        self.assertEqual(cleared_map["VISION_MODEL"], "")
        self.assertEqual(cleared_map["LITELLM_FALLBACK_MODELS"], "deepseek/deepseek-v4-flash")

        restore_payload = self.service.import_desktop_env(
            config_version=self.manager.get_config_version(),
            content=backup_content,
            reload_now=False,
        )
        self.assertTrue(restore_payload["success"])

        restored_map = self.manager.read_config_map()
        self.assertEqual(restored_map["LITELLM_MODEL"], pre_clear_map["LITELLM_MODEL"])
        self.assertEqual(restored_map["AGENT_LITELLM_MODEL"], pre_clear_map["AGENT_LITELLM_MODEL"])
        self.assertEqual(restored_map["VISION_MODEL"], pre_clear_map["VISION_MODEL"])
        self.assertEqual(restored_map["LITELLM_FALLBACK_MODELS"], pre_clear_map["LITELLM_FALLBACK_MODELS"])


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
