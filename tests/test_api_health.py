# -*- coding: utf-8 -*-
"""Tests for health check endpoints: /api/health and /api/v1/health."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app


def _make_client():
    temp_dir = tempfile.TemporaryDirectory()
    return temp_dir, TestClient(create_app(static_dir=Path(temp_dir.name)))


class HealthEndpointTestCase(unittest.TestCase):
    """Both /api/health and /api/v1/health should return 200 with valid payload."""

    @classmethod
    def setUpClass(cls):
        cls._temp_dir, cls.client = _make_client()

    @classmethod
    def tearDownClass(cls):
        cls._temp_dir.cleanup()

    def test_api_health_returns_200(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("timestamp", body)

    def test_api_v1_health_returns_200(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("timestamp", body)


class HealthEndpointAuthEnabledTestCase(unittest.TestCase):
    """Health endpoints must remain accessible when admin auth is enabled."""

    @classmethod
    def setUpClass(cls):
        cls._patcher = patch("api.middlewares.auth.is_auth_enabled", return_value=True)
        cls._patcher.start()
        cls._temp_dir, cls.client = _make_client()

    @classmethod
    def tearDownClass(cls):
        cls._temp_dir.cleanup()
        cls._patcher.stop()

    def test_api_health_returns_200_when_auth_enabled(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_api_v1_health_returns_200_when_auth_enabled(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")


if __name__ == "__main__":
    unittest.main()
