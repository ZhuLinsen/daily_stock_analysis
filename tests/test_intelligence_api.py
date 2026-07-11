# -*- coding: utf-8 -*-
"""API contract tests for intelligence source endpoints."""

from __future__ import annotations

import os
import tempfile
import unittest
import socket
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from fastapi.testclient import TestClient

from api.app import create_app
from src.config import Config
from src.storage import DatabaseManager

RSS_FIXTURE = b'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><item><title>Market event</title><link>https://news.example.com/market-event</link><description>Evidence summary</description></item></channel></rss>'


class IntelligenceApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._temp_dir.name, "api_intel.db")
        Config._instance = None
        DatabaseManager.reset_instance()
        self._dns_patcher = patch(
            "src.services.intelligence_service.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
        )
        self._dns_patcher.start()
        self.addCleanup(self._dns_patcher.stop)
        self.client = TestClient(create_app(static_dir=Path(self._temp_dir.name)))

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config._instance = None
        os.environ.pop("DATABASE_PATH", None)
        self._temp_dir.cleanup()

    def _mock_response(self):
        response = Mock()
        response.status_code = 200
        response.url = "https://feeds.example.com/rss.xml"
        response.headers = {}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [RSS_FIXTURE]
        return response

    def _mock_http_error_response(self, source_url: str):
        response = Mock()
        response.status_code = 403
        response.url = source_url
        response.headers = {}
        response.raise_for_status.side_effect = requests.HTTPError(
            f"403 Client Error: Forbidden for url: {source_url}"
        )
        response.iter_content.return_value = []
        return response

    def test_create_fetch_and_query_items(self) -> None:
        create_resp = self.client.post("/api/v1/intelligence/sources", json={"name": "api-feed", "url": "https://feeds.example.com/rss.xml", "source_type": "rss", "scope_type": "market", "market": "cn"})
        self.assertEqual(create_resp.status_code, 200)
        source_id = create_resp.json()["id"]
        with patch("src.services.intelligence_service.requests.get", return_value=self._mock_response()):
            fetch_resp = self.client.post(f"/api/v1/intelligence/sources/{source_id}/fetch")
        self.assertEqual(fetch_resp.status_code, 200)
        self.assertEqual(fetch_resp.json()["saved_count"], 1)
        list_resp = self.client.get("/api/v1/intelligence/items", params={"scope_type": "market", "market": "cn"})
        self.assertEqual(list_resp.status_code, 200)
        body = list_resp.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["url"], "https://news.example.com/market-event")

    def test_rejects_private_source_url(self) -> None:
        resp = self.client.post("/api/v1/intelligence/sources", json={"name": "bad", "url": "http://localhost/rss.xml", "scope_type": "market"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "validation_error")

    def test_duplicate_source_name_returns_validation_error(self) -> None:
        payload = {"name": "dupe", "url": "https://feeds.example.com/rss.xml", "scope_type": "market"}
        first = self.client.post("/api/v1/intelligence/sources", json=payload)
        second = self.client.post("/api/v1/intelligence/sources", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["error"], "validation_error")

    def test_list_and_create_from_builtin_source_template(self) -> None:
        templates = self.client.get("/api/v1/intelligence/sources/templates", params={"market": "hk"})
        self.assertEqual(templates.status_code, 200)
        body = templates.json()
        self.assertGreaterEqual(body["total"], 1)
        self.assertTrue(any(item["template_id"] == "hkex-news" for item in body["items"]))

        created = self.client.post(
            "/api/v1/intelligence/sources/templates/hkex-news",
            json={"name": "hkex-copy", "enabled": False},
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["name"], "hkex-copy")
        self.assertFalse(created.json()["enabled"])

    def test_create_builtin_default_sources_is_idempotent(self) -> None:
        first = self.client.post("/api/v1/intelligence/sources/defaults", json={"enabled": False})
        second = self.client.post("/api/v1/intelligence/sources/defaults", json={"enabled": False})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertGreaterEqual(first.json()["created_count"], 5)
        self.assertEqual(second.json()["created_count"], 0)
        self.assertEqual(first.json()["total"], second.json()["total"])
        newsnow_sources = [
            item["source"] for item in first.json()["items"]
            if item["source"]["source_type"] == "newsnow"
        ]
        self.assertGreaterEqual(len(newsnow_sources), 5)
        self.assertTrue(all(not item["enabled"] for item in newsnow_sources))

    def test_fetch_source_internal_error_is_sanitized(self) -> None:
        create_resp = self.client.post("/api/v1/intelligence/sources", json={"name": "api-feed", "url": "https://feeds.example.com/rss.xml", "source_type": "rss", "scope_type": "market", "market": "cn"})
        self.assertEqual(create_resp.status_code, 200)
        source_id = create_resp.json()["id"]
        with patch("src.services.intelligence_service.IntelligenceService.fetch_source", side_effect=RuntimeError("token=secret api_key=abc12345")):
            fetch_resp = self.client.post(f"/api/v1/intelligence/sources/{source_id}/fetch")

        self.assertEqual(fetch_resp.status_code, 500)
        body = fetch_resp.json()
        self.assertEqual(body["error"], "internal_error")
        self.assertEqual(body["message"], "Fetch intelligence source failed: internal intelligence service error")

    def test_fetch_source_internal_error_without_sensitive_pattern_is_generic(self) -> None:
        create_resp = self.client.post("/api/v1/intelligence/sources", json={"name": "api-feed", "url": "https://feeds.example.com/rss.xml", "source_type": "rss", "scope_type": "market", "market": "cn"})
        self.assertEqual(create_resp.status_code, 200)
        source_id = create_resp.json()["id"]
        with patch("src.services.intelligence_service.IntelligenceService.fetch_source", side_effect=RuntimeError("unexpected runtime assertion failure: pipeline context exhausted")):
            fetch_resp = self.client.post(f"/api/v1/intelligence/sources/{source_id}/fetch")

        self.assertEqual(fetch_resp.status_code, 500)
        body = fetch_resp.json()
        self.assertEqual(body["error"], "internal_error")
        self.assertEqual(body["message"], "Fetch intelligence source failed: internal intelligence service error")
        self.assertNotIn("pipeline context exhausted", body["message"])

    def test_create_builtin_default_sources_are_disabled_by_default(self) -> None:
        default_resp = self.client.post("/api/v1/intelligence/sources/defaults")
        self.assertEqual(default_resp.status_code, 200)
        newsnow_sources = [
            item["source"] for item in default_resp.json()["items"]
            if item["source"]["source_type"] == "newsnow"
        ]
        self.assertGreaterEqual(len(newsnow_sources), 5)
        self.assertTrue(all(not item["enabled"] for item in newsnow_sources))

    def test_upstream_fetch_errors_do_not_expose_query_secret(self) -> None:
        secret_url = "https://feeds.example.com/rss.xml?token=super-secret"
        payload = {
            "name": "secret-feed",
            "url": secret_url,
            "source_type": "rss",
            "scope_type": "market",
            "market": "cn",
        }
        create_resp = self.client.post("/api/v1/intelligence/sources", json=payload)
        self.assertEqual(create_resp.status_code, 200)
        source_id = create_resp.json()["id"]

        requests_to_check = [
            ("test", lambda: self.client.post("/api/v1/intelligence/sources/test", json=payload)),
            ("fetch", lambda: self.client.post(f"/api/v1/intelligence/sources/{source_id}/fetch")),
        ]
        with patch(
            "src.services.intelligence_service.requests.get",
            side_effect=lambda url, **_kwargs: self._mock_http_error_response(url),
        ):
            for endpoint, send_request in requests_to_check:
                with self.subTest(endpoint=endpoint):
                    response = send_request()
                    self.assertEqual(response.status_code, 400)
                    body = response.json()
                    self.assertEqual(body["error"], "validation_error")
                    self.assertEqual(body["message"], "fetch failed: upstream request failed")
                    self.assertNotIn(secret_url, body["message"])
                    self.assertNotIn("token=", body["message"])
                    self.assertNotIn("super-secret", body["message"])

    def test_upstream_fetch_errors_for_newsnow_do_not_expose_query_secret(self) -> None:
        secret_url = "https://newsnow.example.com/api/s?id=cls-hot&token=super-secret"
        payload = {
            "name": "newsnow-secret-feed",
            "url": secret_url,
            "source_type": "newsnow",
            "scope_type": "market",
            "market": "cn",
        }

        create_resp = self.client.post("/api/v1/intelligence/sources", json=payload)
        self.assertEqual(create_resp.status_code, 200)
        source_id = create_resp.json()["id"]

        requests_to_check = [
            ("test", lambda: self.client.post("/api/v1/intelligence/sources/test", json=payload)),
            ("fetch", lambda: self.client.post(f"/api/v1/intelligence/sources/{source_id}/fetch")),
        ]
        with patch(
            "src.services.intelligence_service.requests.get",
            side_effect=lambda url, **_kwargs: self._mock_http_error_response(url),
        ):
            for endpoint, send_request in requests_to_check:
                with self.subTest(endpoint=endpoint):
                    response = send_request()
                    self.assertEqual(response.status_code, 400)
                    body = response.json()
                    self.assertEqual(body["error"], "validation_error")
                    self.assertEqual(body["message"], "fetch failed: upstream request failed")
                    self.assertNotIn(secret_url, body["message"])
                    self.assertNotIn("token=", body["message"])
                    self.assertNotIn("super-secret", body["message"])


if __name__ == "__main__":
    unittest.main()
