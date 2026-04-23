# -*- coding: utf-8 -*-
"""Unit tests for Auth setupState contract in /auth/status and /auth/settings."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

import src.auth as auth
from api.v1.endpoints.auth import AuthSettingsRequest, auth_status, auth_update_settings


def _reset_auth_globals() -> None:
    """Reset auth module globals for test isolation."""
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


def _make_request(*, cookies: dict[str, str] | None = None) -> Request:
    """Create a minimal Starlette request for endpoint unit tests."""
    headers: list[tuple[bytes, bytes]] = []
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        headers.append((b"cookie", cookie_header.encode("utf-8")))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/auth/status",
        "raw_path": b"/api/v1/auth/status",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope)


class AuthStatusSetupStateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)

        self._data_dir_patcher = patch.object(auth, "_get_data_dir", return_value=self.data_dir)
        self._data_dir_patcher.start()

        self.env_path = self.data_dir / ".env"
        self.env_path.write_text("ADMIN_AUTH_ENABLED=false\n", encoding="utf-8")
        self._env_patcher = patch.dict(os.environ, {"ENV_FILE": str(self.env_path)})
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()
        self._data_dir_patcher.stop()
        _reset_auth_globals()
        self.temp_dir.cleanup()

    def test_status_no_password(self) -> None:
        """Scenario: Auth disabled and no password set."""
        request = _make_request()
        with patch("api.v1.endpoints.auth.is_auth_enabled", return_value=False):
            with patch("src.auth.is_auth_enabled", return_value=False):
                data = asyncio.run(auth_status(request))
                self.assertEqual(data["setupState"], "no_password")
                self.assertFalse(data["authEnabled"])

    def test_status_password_retained(self) -> None:
        """Scenario: Auth disabled but password exists on disk."""
        auth.set_initial_password("password123")
        request = _make_request()

        with patch("api.v1.endpoints.auth.is_auth_enabled", return_value=False):
            with patch("src.auth.is_auth_enabled", return_value=False):
                data = asyncio.run(auth_status(request))
                self.assertEqual(data["setupState"], "password_retained")
                self.assertFalse(data["authEnabled"])
                self.assertFalse(data["passwordSet"])

    def test_status_enabled(self) -> None:
        """Scenario: Auth enabled."""
        auth.set_initial_password("password123")
        request = _make_request()

        with patch("api.v1.endpoints.auth.is_auth_enabled", return_value=True):
            with patch("src.auth.is_auth_enabled", return_value=True):
                data = asyncio.run(auth_status(request))
                self.assertEqual(data["setupState"], "enabled")
                self.assertTrue(data["authEnabled"])
                self.assertTrue(data["passwordSet"])

    def test_settings_update_returns_setup_state(self) -> None:
        """Verify that /auth/settings also returns setupState in response."""
        request = _make_request()
        body = AuthSettingsRequest(
            authEnabled=True,
            password="newpassword123",
            passwordConfirm="newpassword123",
        )

        with patch("api.v1.endpoints.auth.is_auth_enabled") as mock_endpoint_enabled:
            with patch("src.auth.is_auth_enabled") as mock_src_enabled:
                mock_src_enabled.return_value = False
                mock_endpoint_enabled.return_value = False

                with patch("api.v1.endpoints.auth._apply_auth_enabled", return_value=True):
                    with patch("api.v1.endpoints.auth.rotate_session_secret", return_value=True):
                        with patch("api.v1.endpoints.auth.create_session", return_value="mock.session.sig"):
                            with patch("api.v1.endpoints.auth._get_auth_status_dict") as mock_status_dict:
                                mock_status_dict.return_value = {
                                    "authEnabled": True,
                                    "loggedIn": True,
                                    "passwordSet": True,
                                    "passwordChangeable": True,
                                    "setupState": "enabled",
                                }

                                response = asyncio.run(auth_update_settings(request, body))

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.body)
        self.assertEqual(data["setupState"], "enabled")
        self.assertTrue(data["authEnabled"])


if __name__ == "__main__":
    unittest.main()
