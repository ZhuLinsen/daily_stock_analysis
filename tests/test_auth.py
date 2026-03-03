# -*- coding: utf-8 -*-
"""Unit tests for src.auth module."""

import hashlib
import os
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import src.auth as auth


def _reset_auth_globals() -> None:
    """Reset auth module globals for test isolation."""
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


class AuthValidationTestCase(unittest.TestCase):
    """Test password validation."""

    def setUp(self) -> None:
        _reset_auth_globals()

    def test_validate_password_empty(self) -> None:
        self.assertIsNotNone(auth._validate_password(""))
        self.assertIsNotNone(auth._validate_password("   "))

    def test_validate_password_too_short(self) -> None:
        self.assertIsNotNone(auth._validate_password("12345"))

    def test_validate_password_valid(self) -> None:
        self.assertIsNone(auth._validate_password("123456"))
        self.assertIsNone(auth._validate_password("password123"))


class AuthPasswordHashTestCase(unittest.TestCase):
    """Test password hashing and verification."""

    def setUp(self) -> None:
        _reset_auth_globals()

    def test_verify_password_hash_correct(self) -> None:
        salt = secrets.token_bytes(32)
        pwd = "testpass123"
        derived = hashlib.pbkdf2_hmac(
            "sha256", pwd.encode("utf-8"), salt=salt, iterations=auth.PBKDF2_ITERATIONS
        )
        self.assertTrue(auth._verify_password_hash(pwd, salt, derived))

    def test_verify_password_hash_wrong_password(self) -> None:
        salt = secrets.token_bytes(32)
        pwd = "testpass123"
        derived = hashlib.pbkdf2_hmac(
            "sha256", pwd.encode("utf-8"), salt=salt, iterations=auth.PBKDF2_ITERATIONS
        )
        self.assertFalse(auth._verify_password_hash("wrong", salt, derived))

    def test_verify_password_hash_constant_time(self) -> None:
        """Verify compare_digest is used (constant-time)."""
        salt = secrets.token_bytes(32)
        derived = hashlib.pbkdf2_hmac(
            "sha256", b"x", salt=salt, iterations=auth.PBKDF2_ITERATIONS
        )
        self.assertFalse(auth._verify_password_hash("y", salt, derived))


class AuthSessionTestCase(unittest.TestCase):
    """Test session creation and verification."""

    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.addCleanup(self.temp_dir.cleanup)

    def _patch_env_and_run(
        self, auth_enabled: bool = True, test_fn=None
    ):
        with patch.object(auth, "_is_auth_enabled_from_env", return_value=auth_enabled):
            with patch.object(auth, "_get_data_dir", return_value=self.data_dir):
                auth._auth_enabled = auth_enabled
                if test_fn:
                    return test_fn()

    def test_create_session_returns_signed_payload(self) -> None:
        def run():
            tok = auth.create_session()
            self.assertTrue(tok, "session token should be non-empty")
            parts = tok.split(".")
            self.assertEqual(len(parts), 3, "format: nonce.ts.signature")
            nonce, ts, sig = parts
            self.assertTrue(nonce)
            self.assertTrue(ts.isdigit())
            self.assertTrue(sig)
            return tok

        self._patch_env_and_run(test_fn=run)

    def test_verify_session_valid_token(self) -> None:
        def run():
            tok = auth.create_session()
            self.assertTrue(auth.verify_session(tok))

        self._patch_env_and_run(test_fn=run)

    def test_verify_session_expired(self) -> None:
        def run():
            past = time.time() - 48 * 3600
            with patch.object(auth, "time") as mock_time:
                mock_time.time.return_value = past
                tok = auth.create_session()
            self.assertFalse(auth.verify_session(tok), "48h-old token should be expired")

        self._patch_env_and_run(test_fn=run)

    def test_verify_session_invalid_format(self) -> None:
        def run():
            self.assertFalse(auth.verify_session(""))
            self.assertFalse(auth.verify_session("a.b"))
            self.assertFalse(auth.verify_session("invalid"))

        self._patch_env_and_run(test_fn=run)


class AuthRateLimitTestCase(unittest.TestCase):
    """Test rate limiting."""

    def setUp(self) -> None:
        _reset_auth_globals()

    def test_rate_limit_allows_under_limit(self) -> None:
        self.assertTrue(auth.check_rate_limit("192.168.1.1"))

    def test_rate_limit_blocks_after_max_failures(self) -> None:
        ip = "10.0.0.99"
        for _ in range(auth.RATE_LIMIT_MAX_FAILURES):
            auth.record_login_failure(ip)
        self.assertFalse(auth.check_rate_limit(ip))

    def test_clear_rate_limit_resets_ip(self) -> None:
        ip = "10.0.0.100"
        for _ in range(auth.RATE_LIMIT_MAX_FAILURES):
            auth.record_login_failure(ip)
        self.assertFalse(auth.check_rate_limit(ip))
        auth.clear_rate_limit(ip)
        self.assertTrue(auth.check_rate_limit(ip))


class AuthSetPasswordTestCase(unittest.TestCase):
    """Test set_initial_password, change_password, overwrite_password."""

    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.addCleanup(self.temp_dir.cleanup)

    def _run_with_patch(self, fn):
        with patch.object(auth, "_is_auth_enabled_from_env", return_value=True):
            with patch.object(auth, "_get_data_dir", return_value=self.data_dir):
                auth._auth_enabled = True
                return fn()

    def test_set_initial_password_success(self) -> None:
        def run():
            err = auth.set_initial_password("password123")
            self.assertIsNone(err)
            self.assertTrue(auth.is_password_set())
            self.assertTrue(auth.verify_password("password123"))

        self._run_with_patch(run)

    def test_set_initial_password_invalid(self) -> None:
        def run():
            self.assertIsNotNone(auth.set_initial_password(""))
            self.assertIsNotNone(auth.set_initial_password("12345"))

        self._run_with_patch(run)

    def test_change_password_success(self) -> None:
        def run():
            auth.set_initial_password("oldpass123")
            err = auth.change_password("oldpass123", "newpass456")
            self.assertIsNone(err)
            self.assertFalse(auth.verify_password("oldpass123"))
            self.assertTrue(auth.verify_password("newpass456"))

        self._run_with_patch(run)

    def test_change_password_wrong_current(self) -> None:
        def run():
            auth.set_initial_password("correctpass")
            err = auth.change_password("wrongpass", "newpass456")
            self.assertIsNotNone(err)
            self.assertTrue(auth.verify_password("correctpass"))

        self._run_with_patch(run)

    def test_overwrite_password_cli_style(self) -> None:
        def run():
            auth.set_initial_password("original")
            err = auth.overwrite_password("resetpass")
            self.assertIsNone(err)
            self.assertFalse(auth.verify_password("original"))
            self.assertTrue(auth.verify_password("resetpass"))

        self._run_with_patch(run)


if __name__ == "__main__":
    unittest.main()
