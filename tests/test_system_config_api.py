# -*- coding: utf-8 -*-
"""Integration tests for system configuration API endpoints."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from api.v1.endpoints import system_config
from api.v1.schemas.system_config import ImportSystemConfigRequest, TestLLMChannelRequest, UpdateSystemConfigRequest
from src.config import Config
from src.core.config_manager import ConfigManager
from src.services.system_config_service import SystemConfigService


class SystemConfigApiTestCase(unittest.TestCase):
    """System config API tests in isolation without loading the full app."""

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
                    "ADMIN_AUTH_ENABLED=false",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DSA_DESKTOP_MODE"] = "true"
        Config.reset_instance()

        self.manager = ConfigManager(env_path=self.env_path)
        self.service = SystemConfigService(manager=self.manager)

    def tearDown(self) -> None:
        Config.reset_instance()
        os.environ.pop("DSA_DESKTOP_MODE", None)
        os.environ.pop("ENV_FILE", None)
        self.temp_dir.cleanup()

    def test_get_config_returns_raw_secret_value(self) -> None:
        payload = system_config.get_system_config(include_schema=True, service=self.service).model_dump(by_alias=True)
        item_map = {item["key"]: item for item in payload["items"]}
        self.assertEqual(item_map["GEMINI_API_KEY"]["value"], "secret-key-value")
        self.assertFalse(item_map["GEMINI_API_KEY"]["is_masked"])

    def test_put_config_updates_secret_and_plain_field(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()
        payload = system_config.update_system_config(
            request=UpdateSystemConfigRequest(
                config_version=current["config_version"],
                mask_token="******",
                reload_now=False,
                items=[
                    {"key": "GEMINI_API_KEY", "value": "new-secret-value"},
                    {"key": "STOCK_LIST", "value": "600519,300750"},
                ],
            ),
            service=self.service,
        ).model_dump()

        self.assertEqual(payload["applied_count"], 2)
        self.assertEqual(payload["skipped_masked_count"], 0)

        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("STOCK_LIST=600519,300750", env_content)
        self.assertIn("GEMINI_API_KEY=new-secret-value", env_content)

    def test_put_config_returns_conflict_when_version_is_stale(self) -> None:
        with self.assertRaises(HTTPException) as context:
            system_config.update_system_config(
                request=UpdateSystemConfigRequest(
                    config_version="stale-version",
                    items=[{"key": "STOCK_LIST", "value": "600519"}],
                ),
                service=self.service,
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail["error"], "config_version_conflict")

    def test_put_config_preserves_comments_and_blank_lines(self) -> None:
        self.env_path.write_text(
            "\n".join(
                [
                    "# Base settings",
                    "STOCK_LIST=600519,000001",
                    "",
                    "# Secrets",
                    "GEMINI_API_KEY=secret-key-value",
                    "ADMIN_AUTH_ENABLED=false",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()
        payload = system_config.update_system_config(
            request=UpdateSystemConfigRequest(
                config_version=current["config_version"],
                mask_token="******",
                reload_now=False,
                items=[{"key": "STOCK_LIST", "value": "600519,300750"}],
            ),
            service=self.service,
        ).model_dump()

        self.assertTrue(payload["success"])
        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("# Base settings\n", env_content)
        self.assertIn("\n\n# Secrets\n", env_content)
        self.assertIn("STOCK_LIST=600519,300750\n", env_content)

    def test_export_desktop_system_config_returns_raw_env_content(self) -> None:
        self.env_path.write_text(
            "# Desktop config\nSTOCK_LIST=600519,000001\nGEMINI_API_KEY=secret-key-value\n",
            encoding="utf-8",
        )

        payload = system_config.export_desktop_system_config(service=self.service).model_dump()

        self.assertEqual(
            payload["content"],
            "# Desktop config\nSTOCK_LIST=600519,000001\nGEMINI_API_KEY=secret-key-value\n",
        )
        self.assertEqual(payload["config_version"], self.manager.get_config_version())

    def test_import_desktop_system_config_merges_updates(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()

        payload = system_config.import_desktop_system_config(
            request=ImportSystemConfigRequest(
                config_version=current["config_version"],
                content="STOCK_LIST=300750\nCUSTOM_NOTE=desktop backup\n",
                reload_now=False,
            ),
            service=self.service,
        ).model_dump()

        self.assertTrue(payload["success"])
        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("STOCK_LIST=300750\n", env_content)
        self.assertIn("CUSTOM_NOTE=desktop backup\n", env_content)
        self.assertIn("GEMINI_API_KEY=secret-key-value\n", env_content)

    def test_import_desktop_system_config_returns_conflict_when_version_is_stale(self) -> None:
        with self.assertRaises(HTTPException) as context:
            system_config.import_desktop_system_config(
                request=ImportSystemConfigRequest(
                    config_version="stale-version",
                    content="STOCK_LIST=300750\n",
                    reload_now=False,
                ),
                service=self.service,
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail["error"], "config_version_conflict")

    def test_import_desktop_system_config_returns_bad_request_for_invalid_content(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()

        with self.assertRaises(HTTPException) as context:
            system_config.import_desktop_system_config(
                request=ImportSystemConfigRequest(
                    config_version=current["config_version"],
                    content="# comments only\n\n",
                    reload_now=False,
                ),
                service=self.service,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail["error"], "invalid_import_file")

    def test_import_desktop_system_config_returns_bad_request_for_empty_content(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()

        with self.assertRaises(HTTPException) as context:
            system_config.import_desktop_system_config(
                request=ImportSystemConfigRequest(
                    config_version=current["config_version"],
                    content="",
                    reload_now=False,
                ),
                service=self.service,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail["error"], "invalid_import_file")

    def test_desktop_env_endpoints_return_forbidden_outside_desktop_mode(self) -> None:
        os.environ["DSA_DESKTOP_MODE"] = "false"
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()

        with self.assertRaises(HTTPException) as export_context:
            system_config.export_desktop_system_config(service=self.service)
        with self.assertRaises(HTTPException) as import_context:
            system_config.import_desktop_system_config(
                request=ImportSystemConfigRequest(
                    config_version=current["config_version"],
                    content="STOCK_LIST=300750\n",
                    reload_now=False,
                ),
                service=self.service,
            )

        self.assertEqual(export_context.exception.status_code, 403)
        self.assertEqual(export_context.exception.detail["error"], "desktop_only_feature")
        self.assertEqual(import_context.exception.status_code, 403)
        self.assertEqual(import_context.exception.detail["error"], "desktop_only_feature")

    def test_test_llm_channel_endpoint_returns_service_payload(self) -> None:
        with patch.object(
            self.service,
            "test_llm_channel",
            return_value={
                "success": True,
                "message": "LLM channel test succeeded",
                "error": None,
                "resolved_protocol": "openai",
                "resolved_model": "openai/gpt-4o-mini",
                "latency_ms": 123,
            },
        ) as mock_test:
            payload = system_config.test_llm_channel(
                request=TestLLMChannelRequest(
                    name="primary",
                    protocol="openai",
                    base_url="https://api.example.com/v1",
                    api_key="sk-test",
                    models=["gpt-4o-mini"],
                ),
                service=self.service,
            ).model_dump()

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_model"], "openai/gpt-4o-mini")
        mock_test.assert_called_once()


if __name__ == "__main__":
    unittest.main()
