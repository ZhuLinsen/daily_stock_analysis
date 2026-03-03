# -*- coding: utf-8 -*-
"""Integration tests for system configuration API endpoints."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import src.auth as auth
from api.app import create_app
from src.config import Config


class SystemConfigApiTestCase(unittest.TestCase):
    """System config API tests run with auth disabled (test config API in isolation)."""

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
        Config.reset_instance()

        auth._auth_enabled = None
        self.auth_patcher = patch.object(auth, "_is_auth_enabled_from_env", return_value=False)
        self.auth_patcher.start()

        app = create_app(static_dir=Path(self.temp_dir.name) / "empty-static")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.auth_patcher.stop()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        self.temp_dir.cleanup()

    def test_get_config_returns_raw_secret_value(self) -> None:
        response = self.client.get("/api/v1/system/config")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        item_map = {item["key"]: item for item in payload["items"]}
        self.assertEqual(item_map["GEMINI_API_KEY"]["value"], "secret-key-value")
        self.assertFalse(item_map["GEMINI_API_KEY"]["is_masked"])

    def test_put_config_updates_secret_and_plain_field(self) -> None:
        current = self.client.get("/api/v1/system/config").json()

        response = self.client.put(
            "/api/v1/system/config",
            json={
                "config_version": current["config_version"],
                "mask_token": "******",
                "reload_now": False,
                "items": [
                    {"key": "GEMINI_API_KEY", "value": "new-secret-value"},
                    {"key": "STOCK_LIST", "value": "600519,300750"},
                ],
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["applied_count"], 2)
        self.assertEqual(payload["skipped_masked_count"], 0)

        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("STOCK_LIST=600519,300750", env_content)
        self.assertIn("GEMINI_API_KEY=new-secret-value", env_content)

    def test_put_config_returns_conflict_when_version_is_stale(self) -> None:
        response = self.client.put(
            "/api/v1/system/config",
            json={
                "config_version": "stale-version",
                "items": [{"key": "STOCK_LIST", "value": "600519"}],
            },
        )
        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertEqual(payload["error"], "config_version_conflict")


if __name__ == "__main__":
    unittest.main()
