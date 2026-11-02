# -*- coding: utf-8 -*-
"""Tests for the optional fastapi-guard middleware (GUARD_ENABLED, default off)."""

import asyncio
import itertools
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from api.app import create_app

GUARD_ENV_KEYS = (
    "GUARD_ENABLED",
    "GUARD_RATE_LIMIT",
    "GUARD_RATE_LIMIT_WINDOW",
    "GUARD_WHITELIST",
    "GUARD_BLACKLIST",
    "GUARD_TRUSTED_PROXIES",
    "GUARD_SCAN_BODY",
    "GUARD_PASSIVE_MODE",
    "TRUST_X_FORWARDED_FOR",
    "CORS_ALLOW_ALL",
)
ORIGIN = "http://localhost:5173"
_PEERS = itertools.count(1)


class _PeerClient:
    """Tiny sync client that fixes the TCP peer address seen by the app."""

    def __init__(self, app, peer):
        self._app = app
        self._peer = peer

    def request(self, method, path, **kwargs):
        async def _call():
            transport = httpx.ASGITransport(app=self._app, client=(self._peer, 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(_call())

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)


class SecurityGuardTestCase(unittest.TestCase):
    """The guard is opt-in and must not change the app when it is off."""

    def _build_app(self, **env):
        clean = {k: v for k, v in os.environ.items() if k not in GUARD_ENV_KEYS}
        clean.update(env)
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        with patch.dict(os.environ, clean, clear=True):
            return create_app(static_dir=Path(temp_dir.name))

    def setUp(self):
        # guard-core keeps rate-limit counters in process-wide singletons, so every
        # test gets its own TCP peer address instead of sharing one bucket.
        self.peer = f"203.0.113.{next(_PEERS)}"

    def _client(self, app, peer=None):
        return _PeerClient(app, peer or self.peer)

    @staticmethod
    def _guard_cls():
        from guard import PureASGISecurityMiddleware

        return PureASGISecurityMiddleware

    def test_disabled_adds_nothing_and_never_imports_guard(self):
        sys.modules.pop("guard", None)
        app = self._build_app()

        self.assertNotIn("guard", sys.modules)
        self.assertEqual(
            [m.cls.__name__ for m in app.user_middleware],
            ["AuthMiddleware", "CORSMiddleware"],
        )

    def test_enabled_without_package_raises_clear_error(self):
        with patch.dict(sys.modules, {"guard": None}):
            with self.assertRaises(RuntimeError) as ctx:
                self._build_app(GUARD_ENABLED="true")
        self.assertIn("fastapi-guard", str(ctx.exception))

    def test_cors_wraps_guard_and_guard_wraps_auth(self):
        app = self._build_app(GUARD_ENABLED="true")

        order = [m.cls for m in app.user_middleware]
        self.assertEqual(order[0], CORSMiddleware)
        self.assertEqual(order[1], self._guard_cls())
        self.assertFalse(issubclass(order[1], BaseHTTPMiddleware))  # streaming responses stay unbuffered
        self.assertEqual(order[2].__name__, "AuthMiddleware")

    def test_rate_limit_burst_returns_429_with_cors_headers(self):
        app = self._build_app(GUARD_ENABLED="true", GUARD_RATE_LIMIT="3", GUARD_RATE_LIMIT_WINDOW="60")
        client = self._client(app)

        codes = [client.get("/api/v1/auth/status", headers={"Origin": ORIGIN}).status_code for _ in range(5)]
        blocked = client.get("/api/v1/auth/status", headers={"Origin": ORIGIN})

        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3:], [429, 429])
        self.assertEqual(blocked.headers.get("access-control-allow-origin"), ORIGIN)

    def test_allowlist_blocks_other_ips_with_403(self):
        app = self._build_app(GUARD_ENABLED="true", GUARD_WHITELIST="198.51.100.0/24")

        self.assertEqual(self._client(app, "203.0.113.250").get("/api/v1/auth/status").status_code, 403)
        self.assertEqual(self._client(app, "198.51.100.9").get("/api/v1/auth/status").status_code, 200)

    def test_allowlisted_ip_is_exempt_from_rate_limit(self):
        app = self._build_app(GUARD_ENABLED="true", GUARD_RATE_LIMIT="2", GUARD_WHITELIST=self.peer)
        client = self._client(app)

        self.assertEqual([client.get("/api/v1/auth/status").status_code for _ in range(5)], [200] * 5)

    def test_spoofed_xff_is_ignored_from_untrusted_peer(self):
        app = self._build_app(
            GUARD_ENABLED="true",
            TRUST_X_FORWARDED_FOR="true",
            GUARD_WHITELIST="198.51.100.9",
        )
        # Untrusted peer claims to be the allowlisted address.
        spoofed = self._client(app, "203.0.113.250").get(
            "/api/v1/auth/status", headers={"X-Forwarded-For": "198.51.100.9"}
        )
        self.assertEqual(spoofed.status_code, 403)

    def test_spoofed_xff_cannot_rotate_rate_limit_bucket(self):
        app = self._build_app(GUARD_ENABLED="true", GUARD_RATE_LIMIT="2", TRUST_X_FORWARDED_FOR="true")
        client = self._client(app, "203.0.113.250")

        codes = [
            client.get("/api/v1/auth/status", headers={"X-Forwarded-For": f"198.51.100.{i}"}).status_code
            for i in range(4)
        ]
        self.assertEqual(codes, [200, 200, 429, 429])

    def test_trusted_proxy_uses_rightmost_xff_like_get_client_ip(self):
        app = self._build_app(
            GUARD_ENABLED="true",
            TRUST_X_FORWARDED_FOR="true",
            GUARD_WHITELIST="198.51.100.9",
        )
        client = self._client(app, "127.0.0.1")

        ok = client.get("/api/v1/auth/status", headers={"X-Forwarded-For": "6.6.6.6, 198.51.100.9"})
        bad = client.get("/api/v1/auth/status", headers={"X-Forwarded-For": "198.51.100.9, 6.6.6.6"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(bad.status_code, 403)

    def test_xff_ignored_when_trust_flag_is_off(self):
        app = self._build_app(GUARD_ENABLED="true", GUARD_WHITELIST="198.51.100.9")
        client = self._client(app, "127.0.0.1")

        resp = client.get("/api/v1/auth/status", headers={"X-Forwarded-For": "198.51.100.9"})
        self.assertEqual(resp.status_code, 403)

    def test_blocklist_returns_403(self):
        app = self._build_app(GUARD_ENABLED="true", GUARD_BLACKLIST=f"{self.peer},192.0.2.0/24")

        self.assertEqual(self._client(app).get("/api/v1/auth/status").status_code, 403)
        self.assertEqual(self._client(app, "192.0.2.77").get("/api/v1/auth/status").status_code, 403)
        self.assertEqual(self._client(app, "198.51.100.200").get("/api/v1/auth/status").status_code, 200)

    def test_passive_mode_does_not_block(self):
        app = self._build_app(GUARD_ENABLED="true", GUARD_PASSIVE_MODE="true", GUARD_BLACKLIST=self.peer)
        client = self._client(app)

        self.assertEqual(client.get("/api/v1/auth/status").status_code, 200)
        self.assertEqual(client.get("/api/v1/auth/status", params={"q": "<script>alert(1)</script>"}).status_code, 200)

    def test_attack_in_query_is_blocked(self):
        app = self._build_app(GUARD_ENABLED="true")
        client = self._client(app)

        resp = client.get("/api/v1/auth/status", params={"q": "<script>alert(1)</script>"})
        self.assertEqual(resp.status_code, 400)

    def test_localhost_and_lan_referers_are_not_blocked(self):
        app = self._build_app(GUARD_ENABLED="true")

        for referer in ("http://localhost:5173/", "http://127.0.0.1:8000/chat", "http://192.168.1.20:8000/"):
            with self.subTest(referer=referer):
                resp = self._client(app, f"203.0.113.{next(_PEERS) + 100}").get(
                    "/api/v1/auth/status", headers={"Referer": referer}
                )
                self.assertEqual(resp.status_code, 200)

    def test_attack_in_referer_is_still_blocked(self):
        app = self._build_app(GUARD_ENABLED="true")

        resp = self._client(app).get("/api/v1/auth/status", headers={"Referer": "<script>alert(1)</script>"})
        self.assertEqual(resp.status_code, 400)

    def test_body_is_not_scanned_by_default(self):
        app = self._build_app(GUARD_ENABLED="true")
        client = self._client(app)

        # The app (auth is not configured here) answers, so the guard let the payload through unread.
        resp = client.post("/api/v1/auth/login", json={"password": "<script>alert(1)</script>"})
        self.assertIn("auth_disabled", resp.text)

    def test_body_scan_can_be_enabled(self):
        app = self._build_app(GUARD_ENABLED="true", GUARD_SCAN_BODY="true")
        client = self._client(app)

        resp = client.post("/api/v1/auth/login", json={"password": "<script>alert(1)</script>"})
        self.assertNotIn("auth_disabled", resp.text)
        self.assertEqual(resp.status_code, 400)

    def test_invalid_integer_setting_fails_fast(self):
        with self.assertRaises(ValueError):
            self._build_app(GUARD_ENABLED="true", GUARD_RATE_LIMIT="many")


class UvicornProxyHeadersTestCase(unittest.TestCase):
    """Uvicorn rewrites the client from X-Forwarded-For before the app; the guard must still hold."""

    _build_app = SecurityGuardTestCase._build_app
    setUp = SecurityGuardTestCase.setUp
    _client = SecurityGuardTestCase._client

    def _served_app(self, use_guard_kwargs=True, **env):
        import uvicorn

        from api.middlewares.security_guard import uvicorn_proxy_kwargs

        app = self._build_app(**env)
        clean = {k: v for k, v in os.environ.items() if k not in GUARD_ENV_KEYS}
        clean.update(env, FORWARDED_ALLOW_IPS="*")
        with patch.dict(os.environ, clean, clear=True):
            kwargs = uvicorn_proxy_kwargs() if use_guard_kwargs else {}
            config = uvicorn.Config(app, log_config=None, **kwargs)
        config.load()
        return config.loaded_app

    def _rotating_codes(self, served):
        client = self._client(served)
        return [
            client.get("/api/v1/auth/status", headers={"X-Forwarded-For": f"198.18.{next(_PEERS)}.1"}).status_code
            for _ in range(4)
        ]

    def test_guard_off_leaves_uvicorn_settings_alone(self):
        from api.middlewares.security_guard import uvicorn_proxy_kwargs

        with patch.dict(os.environ, {"TRUST_X_FORWARDED_FOR": "true"}, clear=True):
            self.assertEqual(uvicorn_proxy_kwargs(), {})

    def test_rotating_xff_cannot_change_guard_identity_through_uvicorn(self):
        env = {"GUARD_ENABLED": "true", "GUARD_RATE_LIMIT": "2"}

        self.assertEqual(self._rotating_codes(self._served_app(**env)), [200, 200, 429, 429])
        # Same requests without the guard's Uvicorn settings: Uvicorn hands each one a new client address.
        self.setUp()
        self.assertEqual(self._rotating_codes(self._served_app(use_guard_kwargs=False, **env)), [200] * 4)

    def test_untrusted_peer_cannot_claim_allowlisted_ip_through_uvicorn(self):
        served = self._served_app(GUARD_ENABLED="true", TRUST_X_FORWARDED_FOR="true", GUARD_WHITELIST="198.51.100.9")

        spoofed = self._client(served, "203.0.113.250").get(
            "/api/v1/auth/status", headers={"X-Forwarded-For": "198.51.100.9"}
        )
        proxied = self._client(served, "127.0.0.1").get(
            "/api/v1/auth/status", headers={"X-Forwarded-For": "6.6.6.6, 198.51.100.9"}
        )
        self.assertEqual(spoofed.status_code, 403)
        self.assertEqual(proxied.status_code, 200)

    def test_custom_trusted_proxy_cidr(self):
        served = self._served_app(
            GUARD_ENABLED="true",
            TRUST_X_FORWARDED_FOR="true",
            GUARD_TRUSTED_PROXIES="10.0.0.0/8",
            GUARD_WHITELIST="198.51.100.9",
        )
        headers = {"X-Forwarded-For": "198.51.100.9"}

        self.assertEqual(self._client(served, "10.1.2.3").get("/api/v1/auth/status", headers=headers).status_code, 200)
        self.assertEqual(self._client(served, "127.0.0.1").get("/api/v1/auth/status", headers=headers).status_code, 403)


if __name__ == "__main__":
    unittest.main()
