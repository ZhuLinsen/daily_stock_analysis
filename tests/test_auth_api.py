# -*- coding: utf-8 -*-
"""Integration tests for auth API endpoints (login, logout, change-password, API protection)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import src.auth as auth
from api.app import create_app
from src.config import Config


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


class AuthApiTestCase(unittest.TestCase):
    """Integration tests for /api/v1/auth/* and API protection."""

    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_path = self.data_dir / ".env"
        self.env_path.write_text(
            "STOCK_LIST=600519\nGEMINI_API_KEY=test\nADMIN_AUTH_ENABLED=true\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.data_dir / "test.db")
        Config.reset_instance()

        self.auth_patcher = patch.object(auth, "_is_auth_enabled_from_env", return_value=True)
        self.data_dir_patcher = patch.object(auth, "_get_data_dir", return_value=self.data_dir)
        self.auth_patcher.start()
        self.data_dir_patcher.start()

        app = create_app(static_dir=self.data_dir / "empty-static")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.auth_patcher.stop()
        self.data_dir_patcher.stop()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def test_auth_status_when_password_not_set(self) -> None:
        response = self.client.get("/api/v1/auth/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["authEnabled"])
        self.assertFalse(data["passwordSet"])
        self.assertFalse(data["loggedIn"])

    def test_login_first_time_set_initial_password(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"password": "newpass123", "passwordConfirm": "newpass123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("dsa_session", response.cookies)
        self.assertTrue(response.json().get("ok"))

    def test_login_first_time_mismatch_rejected(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"password": "pass1", "passwordConfirm": "pass2"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("password_mismatch", response.json().get("error", ""))

    def test_login_after_set_normal_login(self) -> None:
        self.client.post(
            "/api/v1/auth/login",
            json={"password": "mypass456", "passwordConfirm": "mypass456"},
        )
        response = self.client.post(
            "/api/v1/auth/login",
            json={"password": "mypass456"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

    def test_login_wrong_password_returns_401(self) -> None:
        self.client.post(
            "/api/v1/auth/login",
            json={"password": "correct", "passwordConfirm": "correct"},
        )
        response = self.client.post(
            "/api/v1/auth/login",
            json={"password": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    def test_logout_clears_cookie(self) -> None:
        self.client.post(
            "/api/v1/auth/login",
            json={"password": "passwd6", "passwordConfirm": "passwd6"},
        )
        self.assertIn("dsa_session", self.client.cookies)
        self.client.post("/api/v1/auth/logout")
        response = self.client.get("/api/v1/system/config")
        self.assertEqual(response.status_code, 401, "After logout, protected API should return 401")

    def test_change_password_requires_session(self) -> None:
        self.client.post(
            "/api/v1/auth/login",
            json={"password": "oldpass6", "passwordConfirm": "oldpass6"},
        )
        response = self.client.post(
            "/api/v1/auth/change-password",
            json={
                "currentPassword": "oldpass6",
                "newPassword": "newpass6",
                "newPasswordConfirm": "newpass6",
            },
        )
        self.assertIn(response.status_code, (200, 204))

    def test_change_password_wrong_current_rejected(self) -> None:
        self.client.post(
            "/api/v1/auth/login",
            json={"password": "actual6", "passwordConfirm": "actual6"},
        )
        response = self.client.post(
            "/api/v1/auth/change-password",
            json={
                "currentPassword": "wrong",
                "newPassword": "new123",
                "newPasswordConfirm": "new123",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_protected_api_returns_401_without_session(self) -> None:
        self.client.post(
            "/api/v1/auth/login",
            json={"password": "passwd6", "passwordConfirm": "passwd6"},
        )
        client_no_cookie = TestClient(
            create_app(static_dir=self.data_dir / "empty-static"),
            raise_server_exceptions=False,
        )
        response = client_no_cookie.get("/api/v1/system/config")
        self.assertEqual(response.status_code, 401)

    def test_protected_api_accessible_with_session(self) -> None:
        self.client.post(
            "/api/v1/auth/login",
            json={"password": "passwd6", "passwordConfirm": "passwd6"},
        )
        response = self.client.get("/api/v1/system/config")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
