# -*- coding: utf-8 -*-
"""Tests for configurable persisted intelligence sources."""

from __future__ import annotations

from dataclasses import replace
import os
import json
import socket
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import quote
from unittest.mock import Mock, patch

import requests

from src.config import Config
from src.repositories.intelligence_repo import IntelligenceRepository
from src.services.intelligence_service import IntelligenceService, IntelligenceServiceError
from src.storage import DatabaseManager, IntelligenceItem, INTELLIGENCE_ITEM_NULL_SCOPE_VALUE

RSS_FIXTURE = b'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>\n<item><title>Policy support lifts AI supply chain</title><link>https://news.example.com/a</link><description>Market-level catalyst with evidence link.</description><pubDate>Wed, 17 Jun 2026 08:00:00 GMT</pubDate></item>\n<item><title>Second item</title><link>https://news.example.com/b</link><description>Second summary.</description></item>\n</channel></rss>'
NO_URL_LINK_FIXTURE = b'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>\n<item><title>Anonymous item</title><description>No link in this item.</description></item>\n</channel></rss>'
BAD_ITEM_LINK_FIXTURE = b'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>\n<item><title>Bad mail link</title><link>mailto:tips@example.com</link><description>Should be skipped.</description></item>\n<item><title>Good public link</title><link>https://news.example.com/good</link><description>Should be saved.</description></item>\n</channel></rss>'
NEWSNOW_FIXTURE = {
    "status": "success",
    "id": "cls-hot",
    "updatedTime": 1781760000000,
    "items": [
        {
            "id": "1",
            "title": "A-share AI hardware theme heats up",
            "url": "https://news.example.com/newsnow-a",
            "pubDate": 1781760000000,
            "extra": {"info": "Capital market hot topic from NewsNow."},
        },
        {
            "id": "2",
            "title": "Second NewsNow item",
            "url": "https://news.example.com/newsnow-b",
            "extra": {"hover": "Fallback summary."},
        },
    ],
}


class IntelligenceServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._temp_dir.name, "intelligence.db")
        os.environ["NEWS_INTEL_RETENTION_DAYS"] = "30"
        os.environ["NEWS_INTEL_MAX_ITEMS_PER_SOURCE"] = "50"
        os.environ["NEWS_INTEL_FETCH_TIMEOUT_SEC"] = "3"
        Config._instance = None
        DatabaseManager.reset_instance()
        IntelligenceService.reset_auto_fetch_state()
        self.service = IntelligenceService()
        self._dns_patcher = patch(
            "src.services.intelligence_service.socket.getaddrinfo",
            side_effect=self._mock_getaddrinfo,
        )
        self._dns_patcher.start()
        self.addCleanup(self._dns_patcher.stop)

    def _mock_getaddrinfo(self, host, *_args, **_kwargs):
        host = (host or "").lower().strip()
        if host in {"localhost", "localhost.localdomain"}:
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
            ]
        if host == "shared.example.com":
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("100.64.0.1", 0)),
            ]
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        ]

    def _feed_fixture(self, source_url: str) -> bytes:
        key = quote(source_url.replace("://", "_").replace("/", "_"))
        return RSS_FIXTURE.replace(
            b"https://news.example.com/a",
            f"https://news.example.com/{key}.a".encode("utf-8"),
        ).replace(
            b"https://news.example.com/b",
            f"https://news.example.com/{key}.b".encode("utf-8"),
        )

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config._instance = None
        IntelligenceService.reset_auto_fetch_state()
        for key in [
            "DATABASE_PATH",
            "NEWS_INTEL_RETENTION_DAYS",
            "NEWS_INTEL_MAX_ITEMS_PER_SOURCE",
            "NEWS_INTEL_FETCH_TIMEOUT_SEC",
            "NEWS_INTEL_AUTO_FETCH_ENABLED",
        ]:
            os.environ.pop(key, None)
        self._temp_dir.cleanup()

    def _mock_response(self, source_url: str = "https://feeds.example.com/rss.xml"):
        response = Mock()
        response.status_code = 200
        response.url = source_url
        response.headers = {}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [self._feed_fixture(source_url)]
        return response

    def _mock_json_response(self, payload=NEWSNOW_FIXTURE, source_url: str = "https://newsnow.example.com/api/s?id=cls-hot"):
        response = Mock()
        response.status_code = 200
        response.url = source_url
        response.headers = {}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [json.dumps(payload).encode("utf-8")]
        return response

    def _mock_response_with_redirects(self, source_url: str = "https://feeds.example.com/rss.xml", next_url: str = "https://feeds.example.com/rss.xml"):
        response = Mock()
        response.url = source_url
        response.raise_for_status.return_value = None
        response.headers = {"Location": next_url}
        response.status_code = 302
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

    def test_create_fetch_and_deduplicate_rss_source(self) -> None:
        source = self.service.create_source({
            "name": "market-feed", "url": "https://feeds.example.com/rss.xml",
            "source_type": "rss", "scope_type": "market", "market": "cn",
        })
        with patch("src.services.intelligence_service.requests.get", return_value=self._mock_response()):
            first = self.service.fetch_source(source["id"])
            second = self.service.fetch_source(source["id"])
        self.assertEqual(first["fetched_count"], 2)
        self.assertEqual(first["saved_count"], 2)
        self.assertEqual(second["saved_count"], 0)
        items = self.service.list_items(scope_type="market", market="cn")
        self.assertEqual(items["total"], 2)
        self.assertEqual(items["items"][0]["scope_type"], "market")
        self.assertTrue(items["items"][0]["url"].startswith("https://news.example.com/"))

    def test_fetch_http_error_does_not_expose_source_query_secret(self) -> None:
        secret_url = "https://feeds.example.com/rss.xml?token=super-secret"
        source = self.service.create_source({
            "name": "secret-feed", "url": secret_url, "scope_type": "market",
        })

        with patch("src.services.intelligence_service.requests.get", return_value=self._mock_http_error_response(secret_url)):
            with self.assertRaises(IntelligenceServiceError) as ctx:
                self.service.fetch_source(source["id"])

        message = str(ctx.exception)
        self.assertEqual(message, "fetch failed: upstream request failed")
        self.assertNotIn(secret_url, message)
        self.assertNotIn("token=", message)
        self.assertNotIn("super-secret", message)
        saved_source = self.service.repo.get_source(source["id"])
        self.assertIsNotNone(saved_source)
        self.assertEqual(saved_source.last_error, "fetch failed: upstream request failed")

    def test_fetch_newsnow_http_error_does_not_expose_source_query_secret(self) -> None:
        secret_url = "https://newsnow.example.com/api/s?id=cls-hot&token=super-secret"
        source = self.service.create_source({
            "name": "newsnow-secret-feed",
            "url": secret_url,
            "source_type": "newsnow",
            "scope_type": "market",
            "market": "cn",
        })

        with patch("src.services.intelligence_service.requests.get", return_value=self._mock_http_error_response(secret_url)):
            with self.assertRaises(IntelligenceServiceError) as ctx:
                self.service.fetch_source(source["id"])

        message = str(ctx.exception)
        self.assertEqual(message, "fetch failed: upstream request failed")
        self.assertNotIn(secret_url, message)
        self.assertNotIn("token=", message)
        self.assertNotIn("super-secret", message)

    def test_private_network_url_is_rejected(self) -> None:
        with self.assertRaises(IntelligenceServiceError):
            self.service.create_source({"name": "bad", "url": "http://127.0.0.1:8000/rss.xml", "scope_type": "market"})

    def test_shared_address_space_url_is_rejected(self) -> None:
        with self.assertRaises(IntelligenceServiceError):
            self.service.create_source({"name": "shared", "url": "https://shared.example.com/rss.xml", "scope_type": "market"})

    def test_duplicate_source_name_is_validation_error(self) -> None:
        payload = {"name": "dupe", "url": "https://feeds.example.com/rss.xml", "scope_type": "market"}
        self.service.create_source(payload)
        with self.assertRaises(IntelligenceServiceError):
            self.service.create_source(payload)

    def test_fetch_enabled_sources_is_fail_open(self) -> None:
        self.service.create_source({"name": "good-feed", "url": "https://feeds.example.com/rss.xml", "scope_type": "market"})
        bad = self.service.create_source({"name": "bad-feed", "url": "https://bad.example.com/rss.xml", "scope_type": "market"})

        def fake_get(url, **kwargs):
            self.assertNotIn("trust_env", kwargs)
            self.assertEqual(kwargs.get("proxies"), {"http": None, "https": None})
            if "bad" in url:
                raise RuntimeError("network token=secret should not leak")
            return self._mock_response()
        with patch("src.services.intelligence_service.requests.get", side_effect=fake_get):
            result = self.service.fetch_enabled_sources()
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["saved_count"], 2)
        failures = [item for item in result["results"] if not item["ok"]]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["source_id"], bad["id"])
        self.assertNotIn("token=secret", failures[0]["error"])
        self.assertNotIn("secret", failures[0]["error"])

    def test_fetch_enabled_sources_paginates_all_enabled_sources(self) -> None:
        for index in range(150):
            self.service.create_source({
                "name": f"feed-{index}",
                "url": "https://feeds.example.com/rss.xml",
                "scope_type": "market",
                "market": "cn",
            })

        with patch("src.services.intelligence_service.requests.get", side_effect=lambda *_args, **_kwargs: self._mock_response()):
            result = self.service.fetch_enabled_sources()

        self.assertEqual(result["source_count"], 150)
        self.assertEqual(len(result["results"]), 150)
        self.assertEqual(result["saved_count"], 300)
        self.assertTrue(all(item["ok"] for item in result["results"]))

    def test_fetch_entry_redacts_no_url_link_with_placeholder(self) -> None:
        source = self.service.create_source({
            "name": "market-no-link",
            "url": "https://feeds.example.com/rss.xml",
            "scope_type": "market",
        })

        response = Mock()
        response.status_code = 200
        response.url = "https://feeds.example.com/rss.xml"
        response.headers = {}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [NO_URL_LINK_FIXTURE]

        with patch("src.services.intelligence_service.requests.get", return_value=response):
            result = self.service.fetch_source(source["id"])

        self.assertEqual(result["fetched_count"], 1)
        self.assertEqual(result["saved_count"], 1)
        self.assertIn("no-url:intel:", result["sample_items"][0]["url"])

    def test_bad_feed_item_link_is_skipped_without_failing_source(self) -> None:
        source = self.service.create_source({
            "name": "mixed-link-feed",
            "url": "https://feeds.example.com/rss.xml",
            "scope_type": "market",
        })

        response = Mock()
        response.status_code = 200
        response.url = "https://feeds.example.com/rss.xml"
        response.headers = {}
        response.raise_for_status.return_value = None
        response.iter_content.return_value = [BAD_ITEM_LINK_FIXTURE]

        with patch("src.services.intelligence_service.requests.get", return_value=response):
            result = self.service.fetch_source(source["id"])

        self.assertEqual(result["fetched_count"], 1)
        self.assertEqual(result["saved_count"], 1)
        self.assertEqual(result["sample_items"][0]["url"], "https://news.example.com/good")

    def test_source_templates_can_create_disabled_source(self) -> None:
        templates = self.service.list_source_templates(market="hk")
        self.assertGreaterEqual(templates["total"], 1)
        created = self.service.create_source_from_template("hkex-news", {"enabled": False, "name": "hkex-template-copy"})
        self.assertEqual(created["name"], "hkex-template-copy")
        self.assertEqual(created["market"], "hk")
        self.assertFalse(created["enabled"])

    def test_newsnow_source_fetches_json_items(self) -> None:
        source = self.service.create_source({
            "name": "newsnow-cls",
            "url": "https://newsnow.example.com/api/s?id=cls-hot",
            "source_type": "newsnow",
            "scope_type": "market",
            "market": "cn",
        })

        with patch("src.services.intelligence_service.requests.get", return_value=self._mock_json_response()):
            result = self.service.fetch_source(source["id"])

        self.assertEqual(result["fetched_count"], 2)
        self.assertEqual(result["saved_count"], 2)
        items = self.service.list_items(market="cn")
        self.assertEqual(items["total"], 2)
        self.assertEqual(items["items"][0]["source_type"], "newsnow")
        self.assertEqual(result["sample_items"][0]["source"], "newsnow-cls")
        self.assertEqual(result["sample_items"][0]["summary"], "Capital market hot topic from NewsNow.")

    def test_create_default_sources_is_idempotent(self) -> None:
        first = self.service.create_default_sources({"enabled": False})
        second = self.service.create_default_sources({"enabled": False})

        self.assertGreaterEqual(first["created_count"], 5)
        self.assertEqual(second["created_count"], 0)
        self.assertEqual(first["total"], second["total"])
        sources = self.service.list_sources(source_type="newsnow", market="cn")
        self.assertGreaterEqual(sources["total"], 3)
        self.assertTrue(all(not item["source"]["enabled"] for item in first["items"]))

    def test_create_default_sources_are_disabled_by_default(self) -> None:
        first = self.service.create_default_sources()
        sources = self.service.list_sources()
        self.assertEqual(first["created_count"], first["total"])
        self.assertEqual(sources["total"], first["total"])
        self.assertTrue(all(not item["enabled"] for item in sources["items"]))

    def test_refresh_auto_sources_skips_when_disabled(self) -> None:
        self.service.config.news_intel_auto_fetch_enabled = False

        with patch("src.services.intelligence_service.requests.get") as mock_get:
            result = self.service.refresh_auto_sources(force=True)

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "disabled")
        mock_get.assert_not_called()

    def test_init_accepts_explicit_config(self) -> None:
        self.service.config.news_intel_auto_fetch_enabled = True
        explicit_config = replace(self.service.config, news_intel_auto_fetch_enabled=False)

        with patch("src.services.intelligence_service.requests.get") as mock_get:
            service = IntelligenceService(config=explicit_config)
            result = service.refresh_auto_sources(force=True)

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "disabled")
        mock_get.assert_not_called()

    def test_refresh_auto_sources_bootstraps_enabled_defaults_and_fetches(self) -> None:
        self.service.config.news_intel_auto_fetch_enabled = True

        def fake_get(url, **_kwargs):
            if "newsnow" in url:
                return self._mock_json_response(source_url=url)
            return self._mock_response(source_url=url)

        with patch("src.services.intelligence_service.requests.get", side_effect=fake_get):
            result = self.service.refresh_auto_sources(force=True)

        self.assertTrue(result["ok"])
        self.assertFalse(result["skipped"])
        self.assertGreaterEqual(result["bootstrap"]["created_count"], 8)
        self.assertGreater(result["saved_count"], 0)
        sources = self.service.list_sources(enabled=True)
        self.assertEqual(sources["total"], result["fetch"]["source_count"])
        self.assertEqual(self.service.list_items()["total"], result["saved_count"])

    def test_refresh_auto_sources_enables_existing_default_sources(self) -> None:
        self.service.config.news_intel_auto_fetch_enabled = True
        created = self.service.create_default_sources()
        self.assertGreaterEqual(created["created_count"], 8)

        def fake_get(url, **_kwargs):
            if "newsnow" in url:
                return self._mock_json_response(source_url=url)
            return self._mock_response(source_url=url)

        with patch("src.services.intelligence_service.requests.get", side_effect=fake_get):
            result = self.service.refresh_auto_sources(force=True)

        self.assertEqual(result["bootstrap"]["created_count"], 0)
        self.assertEqual(result["bootstrap"]["enabled_count"], created["total"])
        self.assertEqual(self.service.list_sources(enabled=True)["total"], created["total"])

    def test_refresh_auto_sources_uses_cooldown_after_success(self) -> None:
        self.service.config.news_intel_auto_fetch_enabled = True

        def fake_get(url, **_kwargs):
            if "newsnow" in url:
                return self._mock_json_response(source_url=url)
            return self._mock_response(source_url=url)

        with patch("src.services.intelligence_service.requests.get", side_effect=fake_get):
            first = self.service.refresh_auto_sources(force=True)
        with patch("src.services.intelligence_service.requests.get") as mock_get:
            second = self.service.refresh_auto_sources()

        self.assertTrue(first["ok"])
        self.assertTrue(second["skipped"])
        self.assertEqual(second["reason"], "cooldown")
        mock_get.assert_not_called()

    def test_refresh_auto_sources_waits_for_in_flight_fetch_before_reading_items(self) -> None:
        self.service.config.news_intel_auto_fetch_enabled = True
        fetch_started = threading.Event()
        release_fetch = threading.Event()
        second_refresh_started = threading.Event()

        def fake_fetch_enabled_sources():
            fetch_started.set()
            self.assertTrue(release_fetch.wait(2))
            now = datetime.now()
            saved = self.service.repo.upsert_items([
                {
                    "source_name": "auto-feed",
                    "source_type": "rss",
                    "title": "Auto fetched market item",
                    "summary": "Available to every concurrent analysis after refresh.",
                    "url": "https://news.example.com/auto-fetch",
                    "source": "auto-feed",
                    "published_at": now,
                    "fetched_at": now,
                    "scope_type": "market",
                    "scope_value": None,
                    "market": "cn",
                }
            ])
            return {"ok": True, "source_count": 1, "results": [], "saved_count": saved}

        def refresh_then_count(started_event=None):
            if started_event is not None:
                started_event.set()
            result = self.service.refresh_auto_sources()
            total = self.service.list_items(scope_type="market", market="cn")["total"]
            return result, total

        with (
            patch.object(
                IntelligenceService,
                "ensure_default_sources_enabled",
                return_value={"created_count": 1, "enabled_count": 0, "error_count": 0},
            ),
            patch.object(
                IntelligenceService,
                "fetch_enabled_sources",
                side_effect=fake_fetch_enabled_sources,
            ) as fetch_mock,
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(refresh_then_count)
            try:
                self.assertTrue(fetch_started.wait(2))
                second = executor.submit(refresh_then_count, second_refresh_started)
                self.assertTrue(second_refresh_started.wait(2))
                time.sleep(0.1)
                self.assertFalse(second.done())
            finally:
                release_fetch.set()

            first_result, first_total = first.result(timeout=2)
            second_result, second_total = second.result(timeout=2)

        self.assertTrue(first_result["ok"])
        self.assertTrue(second_result["ok"])
        self.assertEqual(first_total, 1)
        self.assertEqual(second_total, 1)
        self.assertEqual(fetch_mock.call_count, 1)

    def test_same_url_can_be_saved_for_different_scopes(self) -> None:
        market = self.service.create_source({
            "name": "market-feed",
            "url": "https://feeds.example.com/shared.xml",
            "scope_type": "market",
            "market": "cn",
        })
        symbol = self.service.create_source({
            "name": "symbol-feed",
            "url": "https://feeds.example.com/shared.xml",
            "scope_type": "symbol",
            "scope_value": "600519",
            "market": "cn",
        })
        response = self._mock_response(source_url="https://feeds.example.com/shared.xml")
        with patch("src.services.intelligence_service.requests.get", return_value=response):
            market_result = self.service.fetch_source(market["id"])
            symbol_result = self.service.fetch_source(symbol["id"])

        self.assertEqual(market_result["saved_count"], 2)
        self.assertEqual(symbol_result["saved_count"], 2)
        rows, total = IntelligenceRepository().list_items()
        self.assertEqual(total, 4)
        scope_pairs = {(row.scope_type, row.scope_value) for row in rows}
        self.assertIn(("market", INTELLIGENCE_ITEM_NULL_SCOPE_VALUE), scope_pairs)
        self.assertIn(("symbol", "600519"), scope_pairs)

    def test_redirect_to_private_network_is_blocked(self) -> None:
        source = self.service.create_source({
            "name": "redirected-feed",
            "url": "https://feeds.example.com/rss.xml",
            "scope_type": "market",
        })

        with patch("src.services.intelligence_service.requests.get", side_effect=[
            self._mock_response_with_redirects(source_url="https://feeds.example.com/rss.xml", next_url="http://localhost/evil.xml"),
            self._mock_response(source_url="http://localhost/evil.xml"),
        ]):
            with self.assertRaises(IntelligenceServiceError):
                self.service.fetch_source(source["id"])

    def test_redirect_is_followed_after_dns_validation(self) -> None:
        source = self.service.create_source({
            "name": "follow-redirect-feed",
            "url": "https://feeds.example.com/rss.xml",
            "scope_type": "market",
        })

        with patch("src.services.intelligence_service.requests.get", side_effect=[
            self._mock_response_with_redirects(source_url="https://feeds.example.com/rss.xml", next_url="/next.xml"),
            self._mock_response(source_url="https://feeds.example.com/next.xml"),
        ]):
            result = self.service.fetch_source(source["id"])

        self.assertEqual(result["fetched_count"], 2)
        self.assertEqual(result["saved_count"], 2)

    def test_feed_response_size_limit_is_enforced(self) -> None:
        source = self.service.create_source({
            "name": "large-feed",
            "url": "https://feeds.example.com/rss.xml",
            "scope_type": "market",
        })

        large_response = Mock()
        large_response.status_code = 200
        large_response.url = "https://feeds.example.com/rss.xml"
        large_response.headers = {}
        large_response.raise_for_status.return_value = None
        large_response.iter_content.return_value = [b"x" * (2 * 1024 * 1024 + 1)]

        with patch("src.services.intelligence_service.requests.get", return_value=large_response):
            with self.assertRaises(IntelligenceServiceError):
                self.service.fetch_source(source["id"])

    def test_retention_removes_old_items(self) -> None:
        repo = IntelligenceRepository()
        old_time = datetime.now() - timedelta(days=60)
        repo.upsert_items([{"source_name": "legacy", "source_type": "rss", "title": "old", "summary": "old item", "url": "https://news.example.com/old", "source": "legacy", "published_at": old_time, "fetched_at": old_time, "scope_type": "market", "scope_value": None, "market": "cn"}])
        self.assertEqual(repo.apply_retention(30), 1)
        with DatabaseManager.get_instance().get_session() as session:
            self.assertEqual(session.query(IntelligenceItem).count(), 0)


if __name__ == "__main__":
    unittest.main()
