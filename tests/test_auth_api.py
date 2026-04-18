# -*- coding: utf-8 -*-
"""Integration tests for auth API endpoints (login, logout, change-password, API protection)."""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from dotenv import dotenv_values
from fastapi.responses import Response
from starlette.requests import Request

# Keep this test runnable when optional LLM runtime deps are not installed.
try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.middlewares.auth import AuthMiddleware
from api.v1.endpoints import auth as auth_endpoint
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

    def tearDown(self) -> None:
        self.auth_patcher.stop()
        self.data_dir_patcher.stop()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def _read_auth_enabled_from_env(self) -> bool:
        values = dotenv_values(self.env_path)
        return (values.get("ADMIN_AUTH_ENABLED") or "").strip().lower() in ("true", "1", "yes")

    @staticmethod
    def _build_request(cookies=None):
        return SimpleNamespace(
            headers={},
            url=SimpleNamespace(scheme="http"),
            cookies=cookies or {},
            client=SimpleNamespace(host="127.0.0.1"),
        )

    def test_auth_status_when_password_not_set(self) -> None:
        data = asyncio.run(auth_endpoint.auth_status(self._build_request()))
        self.assertTrue(data["authEnabled"])
        self.assertFalse(data["passwordSet"])
        self.assertFalse(data["loggedIn"])

    def test_login_first_time_set_initial_password(self) -> None:
        response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(password="newpass123", passwordConfirm="newpass123"),
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("dsa_session=", response.headers["set-cookie"])
        self.assertIn(b'"ok":true', response.body)

    def test_login_first_time_mismatch_rejected(self) -> None:
        response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(password="pass1", passwordConfirm="pass2"),
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'"error":"password_mismatch"', response.body)

    def test_login_after_set_normal_login(self) -> None:
        first_response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(password="mypass456", passwordConfirm="mypass456"),
            )
        )
        self.assertEqual(first_response.status_code, 200)

        response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(password="mypass456"),
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"ok":true', response.body)

    def test_login_wrong_password_returns_401(self) -> None:
        first_response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(password="correct", passwordConfirm="correct"),
            )
        )
        self.assertEqual(first_response.status_code, 200)

        response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(password="wrong"),
            )
        )
        self.assertEqual(response.status_code, 401)

    def test_logout_clears_cookie(self) -> None:
        response = asyncio.run(auth_endpoint.auth_logout(self._build_request()))
        self.assertEqual(response.status_code, 204)
        self.assertIn("dsa_session=", response.headers["set-cookie"])

    def test_logout_invalidates_existing_session(self) -> None:
        login_response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(password="passwd6", passwordConfirm="passwd6"),
            )
        )
        self.assertEqual(login_response.status_code, 200)
        cookie_header = login_response.headers["set-cookie"]
        session_cookie = cookie_header.split("dsa_session=", 1)[1].split(";", 1)[0]
        self.assertTrue(auth.verify_session(session_cookie))

        logout_response = asyncio.run(auth_endpoint.auth_logout(self._build_request()))

        self.assertEqual(logout_response.status_code, 204)
        self.assertFalse(auth.verify_session(session_cookie))

    def test_logout_returns_500_when_session_invalidation_fails(self) -> None:
        with patch.object(auth_endpoint, "rotate_session_secret", return_value=False):
            response = asyncio.run(auth_endpoint.auth_logout(self._build_request()))

        self.assertEqual(response.status_code, 500)
        self.assertIn(b'"error":"internal_error"', response.body)

    def test_change_password_requires_session(self) -> None:
        first_response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(password="oldpass6", passwordConfirm="oldpass6"),
            )
        )
        self.assertEqual(first_response.status_code, 200)

        response = asyncio.run(
            auth_endpoint.auth_change_password(
                auth_endpoint.ChangePasswordRequest(
                    currentPassword="oldpass6",
                    newPassword="newpass6",
                    newPasswordConfirm="newpass6",
                )
            )
        )
        self.assertIn(response.status_code, (200, 204))

    def test_change_password_wrong_current_rejected(self) -> None:
        first_response = asyncio.run(
            auth_endpoint.auth_login(
                self._build_request(),
                auth_endpoint.LoginRequest(password="actual6", passwordConfirm="actual6"),
            )
        )
        self.assertEqual(first_response.status_code, 200)

        response = asyncio.run(
            auth_endpoint.auth_change_password(
                auth_endpoint.ChangePasswordRequest(
                    currentPassword="wrong",
                    newPassword="new123",
                    newPasswordConfirm="new123",
                )
            )
        )
        self.assertEqual(response.status_code, 400)

    def test_protected_api_returns_401_without_session(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/system/config",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        }
        request = Request(scope)
        middleware = AuthMiddleware(app=MagicMock())

        with patch("api.middlewares.auth.is_auth_enabled", return_value=True):
            response = asyncio.run(middleware.dispatch(request, AsyncMock(return_value=Response(status_code=200))))

        self.assertEqual(response.status_code, 401)

    def test_logout_requires_session_when_auth_enabled(self) -> None:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/logout",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        }
        request = Request(scope)
        middleware = AuthMiddleware(app=MagicMock())
        call_next = AsyncMock(return_value=Response(status_code=204))

        with patch("api.middlewares.auth.is_auth_enabled", return_value=True):
            response = asyncio.run(middleware.dispatch(request, call_next))

        self.assertEqual(response.status_code, 401)
        call_next.assert_not_awaited()

    def test_protected_api_accessible_with_session(self) -> None:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/system/config",
            "headers": [(b"cookie", b"dsa_session=test-session")],
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        }
        request = Request(scope)
        middleware = AuthMiddleware(app=MagicMock())
        next_response = Response(status_code=200)
        call_next = AsyncMock(return_value=next_response)

        with patch("api.middlewares.auth.is_auth_enabled", return_value=True):
            with patch("api.middlewares.auth.verify_session", return_value=True):
                response = asyncio.run(middleware.dispatch(request, call_next))

        self.assertEqual(response.status_code, 200)
        call_next.assert_awaited_once()

    def test_auth_settings_requires_session_when_auth_enabled(self) -> None:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/settings",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        }
        request = Request(scope)
        middleware = AuthMiddleware(app=MagicMock())

        with patch("api.middlewares.auth.is_auth_enabled", return_value=True):
            response = asyncio.run(middleware.dispatch(request, AsyncMock(return_value=Response(status_code=200))))

        self.assertEqual(response.status_code, 401)

    def test_auth_settings_is_reachable_when_auth_disabled(self) -> None:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/settings",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        }
        request = Request(scope)
        middleware = AuthMiddleware(app=MagicMock())
        next_response = Response(status_code=200)
        call_next = AsyncMock(return_value=next_response)

        with patch("api.middlewares.auth.is_auth_enabled", return_value=False):
            response = asyncio.run(middleware.dispatch(request, call_next))

        self.assertEqual(response.status_code, 200)
        call_next.assert_awaited_once()

    def test_auth_settings_enable_sets_initial_password_and_logs_in(self) -> None:
        self.env_path.write_text(
            "STOCK_LIST=600519\nGEMINI_API_KEY=test\nADMIN_AUTH_ENABLED=false\n",
            encoding="utf-8",
        )
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            auth.refresh_auth_state()

            response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(
                        authEnabled=True,
                        password="initpass123",
                        passwordConfirm="initpass123",
                    ),
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"authEnabled":true', response.body)
        self.assertIn(b'"loggedIn":true', response.body)
        self.assertIn(b'"passwordSet":true', response.body)
        self.assertIn("dsa_session=", response.headers["set-cookie"])
        self.assertIn("ADMIN_AUTH_ENABLED=true", self.env_path.read_text(encoding="utf-8"))

    def test_auth_settings_enable_requires_password_when_missing(self) -> None:
        self.env_path.write_text(
            "STOCK_LIST=600519\nGEMINI_API_KEY=test\nADMIN_AUTH_ENABLED=false\n",
            encoding="utf-8",
        )
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            auth.refresh_auth_state()

            response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(authEnabled=True),
                )
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b'"error":"password_required"', response.body)

    def test_auth_settings_rechecks_password_before_initial_write(self) -> None:
        self.env_path.write_text(
            "STOCK_LIST=600519\nGEMINI_API_KEY=test\nADMIN_AUTH_ENABLED=false\n",
            encoding="utf-8",
        )
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            auth.refresh_auth_state()

            with patch.object(
                auth_endpoint,
                "has_stored_password",
                side_effect=[False, True],
            ) as has_password_mock:
                with patch.object(auth_endpoint, "set_initial_password") as set_password_mock:
                    response = asyncio.run(
                        auth_endpoint.auth_update_settings(
                            self._build_request(),
                            auth_endpoint.AuthSettingsRequest(
                                authEnabled=True,
                                password="initpass123",
                                passwordConfirm="initpass123",
                            ),
                        )
                    )

        self.assertEqual(has_password_mock.call_count, 2)
        set_password_mock.assert_not_called()
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'"error":"password_already_set"', response.body)

    def test_auth_settings_disable_clears_cookie_and_hides_password_state(self) -> None:
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            auth.set_initial_password("passwd6")
            response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(authEnabled=False, currentPassword="passwd6"),
                )
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"authEnabled":false', response.body)
        self.assertIn(b'"loggedIn":false', response.body)
        self.assertIn(b'"passwordSet":false', response.body)
        self.assertIn("ADMIN_AUTH_ENABLED=false", self.env_path.read_text(encoding="utf-8"))
        self.assertIn("dsa_session=", response.headers["set-cookie"])

        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            status_response = asyncio.run(auth_endpoint.auth_status(self._build_request()))
        self.assertFalse(status_response["authEnabled"])
        self.assertFalse(status_response["passwordSet"])

    def test_auth_settings_disable_requires_current_password_when_auth_enabled(self) -> None:
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            auth.set_initial_password("passwd6")
            response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(authEnabled=False),
                )
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b'"error":"current_required"', response.body)
        self.assertIn("ADMIN_AUTH_ENABLED=true", self.env_path.read_text(encoding="utf-8"))

    def test_auth_settings_toggle_fails_when_secret_rotation_fails(self) -> None:
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            auth.set_initial_password("passwd6")
            with patch.object(auth_endpoint, "rotate_session_secret", return_value=False):
                response = asyncio.run(
                    auth_endpoint.auth_update_settings(
                        self._build_request(),
                        auth_endpoint.AuthSettingsRequest(authEnabled=False, currentPassword="passwd6"),
                    )
                )

        self.assertEqual(response.status_code, 500)
        self.assertIn(b'"error":"internal_error"', response.body)
        self.assertIn("ADMIN_AUTH_ENABLED=true", self.env_path.read_text(encoding="utf-8"))

    def test_auth_settings_enable_with_existing_password_reuses_stored_password(self) -> None:
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            auth.set_initial_password("passwd6")
            disable_response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(authEnabled=False, currentPassword="passwd6"),
                )
            )
        self.assertEqual(disable_response.status_code, 200)

        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            enable_response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(authEnabled=True, currentPassword="passwd6"),
                )
            )

        self.assertEqual(enable_response.status_code, 200)
        self.assertIn(b'"authEnabled":true', enable_response.body)
        self.assertIn(b'"passwordSet":true', enable_response.body)
        self.assertIn(b'"loggedIn":true', enable_response.body)
        self.assertIn("dsa_session=", enable_response.headers["set-cookie"])

    def test_auth_settings_enable_with_existing_password_requires_current_password(self) -> None:
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            auth.set_initial_password("passwd6")
            disable_response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(authEnabled=False, currentPassword="passwd6"),
                )
            )
        self.assertEqual(disable_response.status_code, 200)

        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(authEnabled=True),
                )
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b'"error":"current_required"', response.body)
        self.assertIn("ADMIN_AUTH_ENABLED=false", self.env_path.read_text(encoding="utf-8"))

    def test_auth_settings_enable_with_existing_password_rejects_wrong_current_password(self) -> None:
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            auth.set_initial_password("passwd6")
            disable_response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(authEnabled=False, currentPassword="passwd6"),
                )
            )
        self.assertEqual(disable_response.status_code, 200)

        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(authEnabled=True, currentPassword="wrongpass"),
                )
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn(b'"error":"invalid_password"', response.body)
        self.assertIn("ADMIN_AUTH_ENABLED=false", self.env_path.read_text(encoding="utf-8"))

    def test_auth_settings_enable_rolls_back_when_session_creation_fails(self) -> None:
        self.env_path.write_text(
            "STOCK_LIST=600519\nGEMINI_API_KEY=test\nADMIN_AUTH_ENABLED=false\n",
            encoding="utf-8",
        )
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            auth.refresh_auth_state()
            with patch.object(auth_endpoint, "create_session", return_value=""):
                response = asyncio.run(
                    auth_endpoint.auth_update_settings(
                        self._build_request(),
                        auth_endpoint.AuthSettingsRequest(
                            authEnabled=True,
                            password="initpass123",
                            passwordConfirm="initpass123",
                        ),
                    )
                )

        self.assertEqual(response.status_code, 500)
        self.assertIn(b'"error":"internal_error"', response.body)
        self.assertIn("ADMIN_AUTH_ENABLED=false", self.env_path.read_text(encoding="utf-8"))

    def test_auth_settings_rejects_overwriting_existing_password(self) -> None:
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            auth.set_initial_password("passwd6")
            disable_response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(authEnabled=False, currentPassword="passwd6"),
                )
            )
            self.assertEqual(disable_response.status_code, 200)

        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(),
                    auth_endpoint.AuthSettingsRequest(
                        authEnabled=True,
                        password="newpass123",
                        passwordConfirm="newpass123",
                    ),
                )
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b'"error":"password_already_set"', response.body)

    def test_auth_settings_enable_requires_valid_session_cookie_against_toctou(self) -> None:
        """Verify fix for P1 vulnerability: passing authEnabled=True without currentPassword
        must be rejected if the caller lacks a cryptographically valid session, even if
        is_auth_enabled() evaluates to True during handler execution (TOCTOU race condition).
        """
        self.env_path.write_text(
            "STOCK_LIST=600519\nGEMINI_API_KEY=test\nADMIN_AUTH_ENABLED=false\n",
            encoding="utf-8",
        )
        with patch.object(auth, "_is_auth_enabled_from_env", side_effect=self._read_auth_enabled_from_env):
            # 1. Setup an existing password, auth is currently disabled
            auth.set_initial_password("passwd6")
            
            # 2. Simulate the race condition:
            # The middleware let the request through because auth was supposedly False.
            # But just before the handler runs, another thread enables auth.
            self.env_path.write_text(
                "STOCK_LIST=600519\nGEMINI_API_KEY=test\nADMIN_AUTH_ENABLED=true\n",
                encoding="utf-8",
            )
            auth.refresh_auth_state() # simulate the flip to True

            # 3. The attacker tries to re-enable auth without a password or valid cookie
            response = asyncio.run(
                auth_endpoint.auth_update_settings(
                    self._build_request(cookies={"dsa_session": "invalid"}),
                    auth_endpoint.AuthSettingsRequest(authEnabled=True),
                )
            )

        # 4. Must be rejected because they lack a valid session + NO current_password
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'"error":"current_required"', response.body)


if __name__ == "__main__":
    unittest.main()
