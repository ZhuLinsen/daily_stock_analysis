# -*- coding: utf-8 -*-
"""Tests for CWE-345 fix: X-Forwarded-For IP spoofing prevention in get_client_ip."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.auth import get_client_ip


def _make_request(xff_value=None, client_host=None):
    """Build a minimal request-like object."""
    headers = {}
    if xff_value is not None:
        headers["X-Forwarded-For"] = xff_value
    client = SimpleNamespace(host=client_host) if client_host else None
    return SimpleNamespace(headers=headers, client=client)


class TestGetClientIpXffFix(unittest.TestCase):
    """Verify get_client_ip uses rightmost XFF entry (proxy-appended)."""

    # --- TRUST_X_FORWARDED_FOR enabled ---

    @patch.dict(os.environ, {"TRUST_X_FORWARDED_FOR": "true"})
    def test_single_ip_returns_that_ip(self):
        """Single-entry XFF should return that entry."""
        req = _make_request(xff_value="1.2.3.4")
        self.assertEqual(get_client_ip(req), "1.2.3.4")

    @patch.dict(os.environ, {"TRUST_X_FORWARDED_FOR": "true"})
    def test_multiple_ips_returns_rightmost(self):
        """Rightmost entry is the one appended by the trusted proxy."""
        req = _make_request(xff_value="spoofed.ip, 10.0.0.1, 192.168.1.1")
        self.assertEqual(get_client_ip(req), "192.168.1.1")

    @patch.dict(os.environ, {"TRUST_X_FORWARDED_FOR": "true"})
    def test_attacker_cannot_control_rate_limit_bucket(self):
        """Attacker-injected leftmost IP must NOT be selected (the old [0] bug)."""
        req = _make_request(xff_value="evil-rotated-ip, real-client-ip")
        ip = get_client_ip(req)
        self.assertNotEqual(ip, "evil-rotated-ip",
                            "Leftmost (attacker-controlled) IP must not be used")
        self.assertEqual(ip, "real-client-ip")

    @patch.dict(os.environ, {"TRUST_X_FORWARDED_FOR": "true"})
    def test_whitespace_is_stripped(self):
        req = _make_request(xff_value="10.0.0.1,  192.168.1.1  ")
        self.assertEqual(get_client_ip(req), "192.168.1.1")

    @patch.dict(os.environ, {"TRUST_X_FORWARDED_FOR": "true"})
    def test_no_xff_header_falls_back_to_client(self):
        req = _make_request(client_host="172.16.0.1")
        self.assertEqual(get_client_ip(req), "172.16.0.1")

    @patch.dict(os.environ, {"TRUST_X_FORWARDED_FOR": "true"})
    def test_no_xff_no_client_returns_localhost(self):
        req = _make_request()
        self.assertEqual(get_client_ip(req), "127.0.0.1")

    # --- TRUST_X_FORWARDED_FOR disabled (default) ---

    @patch.dict(os.environ, {"TRUST_X_FORWARDED_FOR": "false"})
    def test_xff_ignored_when_trust_disabled(self):
        """XFF header should be completely ignored when trust is off."""
        req = _make_request(xff_value="1.2.3.4", client_host="10.0.0.5")
        self.assertEqual(get_client_ip(req), "10.0.0.5")

    @patch.dict(os.environ, {}, clear=False)
    def test_xff_ignored_when_env_unset(self):
        """If TRUST_X_FORWARDED_FOR is not set, default to not trusting."""
        env = os.environ.copy()
        env.pop("TRUST_X_FORWARDED_FOR", None)
        with patch.dict(os.environ, env, clear=True):
            req = _make_request(xff_value="1.2.3.4", client_host="10.0.0.5")
            self.assertEqual(get_client_ip(req), "10.0.0.5")

    # --- Edge cases ---

    @patch.dict(os.environ, {"TRUST_X_FORWARDED_FOR": "true"})
    def test_empty_xff_header(self):
        """Empty XFF string should fall back to client."""
        req = SimpleNamespace(headers={"X-Forwarded-For": ""}, client=SimpleNamespace(host="10.0.0.1"))
        self.assertEqual(get_client_ip(req), "10.0.0.1")

    @patch.dict(os.environ, {"TRUST_X_FORWARDED_FOR": "TRUE"})
    def test_case_insensitive_trust_flag(self):
        """TRUST_X_FORWARDED_FOR=TRUE (uppercase) should still work."""
        req = _make_request(xff_value="1.1.1.1, 2.2.2.2")
        self.assertEqual(get_client_ip(req), "2.2.2.2")


if __name__ == "__main__":
    unittest.main()
