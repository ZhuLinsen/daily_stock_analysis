# -*- coding: utf-8 -*-
"""Tests for the AlphaSift screening endpoints."""

from __future__ import annotations

import os
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import ANY, MagicMock, patch
import threading

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from api.v1.endpoints import alphasift as alphasift_endpoint
from src.config import Config, DEFAULT_ALPHASIFT_INSTALL_SPEC
from src.services import alphasift_service
from src.services.task_queue import TaskInfo, TaskStatus as QueueTaskStatus

DEFAULT_ALPHASIFT_TEST_SPEC = DEFAULT_ALPHASIFT_INSTALL_SPEC


def _alphasift_unavailable() -> HTTPException:
    return HTTPException(
        status_code=424,
        detail={"error": "alphasift_unavailable", "message": "AlphaSift is unavailable"},
    )


def _raise_alphasift_unavailable() -> None:
    raise _alphasift_unavailable()


def _make_adapter_module(
    *,
    screen=None,
    list_strategies=None,
    get_status=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        screen=screen or MagicMock(return_value=[]),
        list_strategies=list_strategies or (lambda: [{"id": "dual_low", "name": "双低选股", "description": "", "category": "价值"}]),
        get_status=get_status or (lambda: {"supported_markets": ["cn"], "contract_version": "1", "version": "0.2.0", "strategy_count": 1}),
    )


def _missing_alphasift_module_diagnostics() -> Dict[str, str]:
    return {
        "reason": "missing_module",
        "stage": "import_adapter",
        "error_type": "ModuleNotFoundError",
        "module": "alphasift.dsa_adapter",
    }


class AlphaSiftOpportunitiesApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        Config.reset_instance()
        self.env_patch = patch.dict(os.environ, {"ALPHASIFT_DATA_DIR": ""}, clear=False)
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        Config.reset_instance()

    def _config(self, *, enabled: bool, install_spec: str = DEFAULT_ALPHASIFT_TEST_SPEC) -> Config:
        return Config(alphasift_enabled=enabled, alphasift_install_spec=install_spec)

    @staticmethod
    def _request(cookies=None) -> SimpleNamespace:
        return SimpleNamespace(cookies=cookies or {})

    def _screen(self, config: Config, *, mock_enrichment: bool = True, **kwargs):
        if not mock_enrichment:
            return alphasift_endpoint.alphasift_screen(
                alphasift_endpoint.AlphaSiftScreenRequest(**kwargs),
                http_request=self._request(),
                config=config,
            )
        with patch(
            "src.services.alphasift_service._enrich_candidates_with_dsa",
            side_effect=lambda candidates: (
                candidates,
                {
                    "enabled": True,
                    "max_candidates": 3,
                    "requested_count": min(len(candidates), 3),
                    "enriched_count": 0,
                    "warnings": [],
                },
            ),
        ):
            return alphasift_endpoint.alphasift_screen(
                alphasift_endpoint.AlphaSiftScreenRequest(**kwargs),
                http_request=self._request(),
                config=config,
            )

    def _strategies(self, config: Config):
        return alphasift_endpoint.alphasift_strategies(request=self._request(), config=config)

    def _hotspots(self, config: Config, **kwargs):
        return alphasift_endpoint.alphasift_hotspots(config=config, **kwargs)

    def _hotspot_detail(self, config: Config, **kwargs):
        if os.environ.get("ALPHASIFT_DATA_DIR"):
            return alphasift_endpoint.alphasift_hotspot_detail(config=config, **kwargs)
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"ALPHASIFT_DATA_DIR": str(Path(tmpdir) / "alphasift")}, clear=False):
                return alphasift_endpoint.alphasift_hotspot_detail(config=config, **kwargs)

    def test_default_install_spec_is_commit_pinned(self) -> None:
        self.assertRegex(
            DEFAULT_ALPHASIFT_TEST_SPEC,
            r"^git\+https://github\.com/ZhuLinsen/alphasift\.git@[0-9a-f]{40}$",
        )

    def test_status_defaults_to_disabled(self) -> None:
        config = self._config(enabled=False)

        with patch("src.services.alphasift_service._call_alphasift_status", side_effect=_raise_alphasift_unavailable):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertEqual(payload["enabled"], False)
        self.assertEqual(payload["available"], False)
        self.assertEqual(payload["install_spec_is_default"], True)
        self.assertNotIn("diagnostics", payload)
        self.assertNotIn("install_spec", payload)

    def test_status_marks_custom_install_source(self) -> None:
        config = self._config(enabled=False, install_spec="git+https://example.com/private/alphasift.git")

        with patch("src.services.alphasift_service._call_alphasift_status", side_effect=_raise_alphasift_unavailable):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertEqual(payload["install_spec_is_default"], False)
        self.assertNotIn("install_spec", payload)

    def test_status_includes_adapter_contract_metadata(self) -> None:
        config = self._config(enabled=True)

        with patch(
            "src.services.alphasift_service._call_alphasift_status",
            return_value={"available": True, "contract_version": "1", "version": "0.2.0", "strategy_count": 8},
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["contract_version"], "1")
        self.assertEqual(payload["version"], "0.2.0")
        self.assertEqual(payload["strategy_count"], 8)

    def test_status_preserves_adapter_available_false_without_diagnostics(self) -> None:
        config = self._config(enabled=False)

        with patch(
            "src.services.alphasift_service._call_alphasift_status",
            return_value={"available": False, "contract_version": "1", "version": "0.2.0", "strategy_count": 0},
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["contract_version"], "1")
        self.assertNotIn("diagnostics", payload)

    def test_status_logs_and_reports_adapter_runtime_exception_diagnostics(self) -> None:
        config = self._config(enabled=False)
        fake_module = _make_adapter_module(get_status=MagicMock(side_effect=RuntimeError("get_status failed")))

        with (
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
            self.assertLogs("src.services.alphasift_service", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "get_status")
        self.assertEqual(payload["diagnostics"]["error_type"], "RuntimeError")
        self.assertIn("Unexpected AlphaSift get_status failure", "\n".join(captured.output))

    def test_status_logs_and_reports_unexpected_import_exception_diagnostics(self) -> None:
        config = self._config(enabled=False)
        missing_sub_dependency = ModuleNotFoundError("No module named 'optional_dep'", name="optional_dep")

        with (
            patch("src.services.alphasift_service._prepare_alphasift_runtime_env"),
            patch("src.services.alphasift_service.importlib.import_module", side_effect=missing_sub_dependency),
            self.assertLogs("src.services.alphasift_service", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "import_adapter")
        self.assertEqual(payload["diagnostics"]["error_type"], "ModuleNotFoundError")
        self.assertIn("Unexpected AlphaSift import_adapter failure", "\n".join(captured.output))

    def test_status_marks_missing_module_for_dependency_diagnostic(self) -> None:
        config = self._config(enabled=True)
        missing_module_exc = ModuleNotFoundError("No module named 'alphasift.dsa_adapter'", name="alphasift.dsa_adapter")

        with (
            patch("src.services.alphasift_service._import_alphasift", side_effect=missing_module_exc),
            self.assertLogs("src.services.alphasift_service", level="WARNING"),
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "missing_module")
        self.assertEqual(payload["diagnostics"]["stage"], "import_adapter")
        self.assertEqual(payload["diagnostics"]["error_type"], "ModuleNotFoundError")

    def test_status_logs_and_reports_invalid_get_status_result_diagnostics(self) -> None:
        config = self._config(enabled=False)
        fake_module = _make_adapter_module(get_status=lambda: ["not", "a", "dict"])

        with (
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
            self.assertLogs("src.services.alphasift_service", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "get_status_result")
        self.assertEqual(payload["diagnostics"]["error_type"], "TypeError")
        self.assertIn("Unexpected AlphaSift get_status_result failure", "\n".join(captured.output))

    def test_status_logs_and_reports_missing_get_status_callable_diagnostics(self) -> None:
        config = self._config(enabled=False)
        fake_module = SimpleNamespace(list_strategies=lambda: [], screen=MagicMock(return_value=[]))

        with (
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
            self.assertLogs("src.services.alphasift_service", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "get_status_callable")
        self.assertEqual(payload["diagnostics"]["error_type"], "HTTPException")
        self.assertIn("Unexpected AlphaSift get_status_callable failure", "\n".join(captured.output))

    def test_strategies_returns_adapter_strategies(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            list_strategies=lambda: [
                {"id": "dual_low", "name": "双低选股", "description": "value", "category": "价值"},
                {"id": "trend_quality", "title": "趋势质量", "description": "trend", "tag": "框架"},
            ],
        )

        with patch("src.services.alphasift_service._import_alphasift", return_value=fake_module):
            payload = self._strategies(config=config)

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["strategy_count"], 2)
        self.assertEqual(payload["strategies"][0]["id"], "dual_low")
        self.assertEqual(payload["strategies"][0]["name"], "双低选股")
        self.assertEqual(payload["strategies"][1]["name"], "趋势质量")

    def test_hotspots_returns_alphasift_hotspot_summaries(self) -> None:
        config = self._config(enabled=True)

        class HotspotRows(list):
            provider_used = "akshare"
            fallback_used = False
            source_errors = []
            stale = False
            stale_age_hours = None

        rows = HotspotRows([
            {
                "topic": "AI算力",
                "name": "AI算力",
                "heat_score": 88.0,
                "change_pct": 6.2,
                "stage": "加速主升",
                "leaders": ["中际旭创"],
            }
        ])
        discover = MagicMock(return_value=rows)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "hotspots.json"
            with (
                patch("src.services.alphasift_service.DSA_ALPHASIFT_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace(discover_hotspots=discover)),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=1, refresh=True)

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["provider"], "akshare")
        self.assertEqual(payload["provider_used"], "akshare")
        self.assertEqual(payload["hotspot_count"], 1)
        self.assertEqual(payload["hotspots"][0]["topic"], "AI算力")
        self.assertEqual(payload["hotspots"][0]["heat_score"], 88.0)
        discover.assert_called_once()
        provider = discover.call_args.kwargs["provider"]
        self.assertTrue(hasattr(provider, "stock_board_concept_name_em"))
        self.assertTrue(hasattr(provider, "stock_board_industry_name_em"))
        self.assertEqual(discover.call_args.kwargs["top"], 1)

    def test_hotspots_refresh_uses_dsa_direct_rows_when_alphasift_rows_are_thin(self) -> None:
        config = self._config(enabled=True)

        class ThinRows(list):
            provider_used = "akshare"
            fallback_used = False
            source_errors = []
            stale = False
            stale_age_hours = None

        class FakeProvider(alphasift_service.DsaEastMoneyHotspotProvider):
            def hotspot_rows(self, *, top: int = 12) -> List[Dict[str, Any]]:
                return [
                    {"topic": "钼", "name": "钼", "heat_score": 96.0, "change_pct": 10.0, "leaders": ["盛龙股份"]},
                    {"topic": "铅锌", "name": "铅锌", "heat_score": 92.0, "change_pct": 9.14, "leaders": ["豫光金铅"]},
                    {"topic": "铜", "name": "铜", "heat_score": 89.0, "change_pct": 7.03, "leaders": ["江西铜业"]},
                ][:top]

        discover = MagicMock(return_value=ThinRows([
            {"topic": "AI算力", "name": "AI算力", "heat_score": 88.0},
        ]))

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "hotspots.json"
            provider = FakeProvider()
            with (
                patch("src.services.alphasift_service.DSA_ALPHASIFT_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace(discover_hotspots=discover)),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=6, refresh=True)

        self.assertEqual(payload["provider_used"], "dsa_eastmoney_board_change")
        self.assertEqual(payload["hotspot_count"], 3)
        self.assertEqual([item["topic"] for item in payload["hotspots"][:3]], ["钼", "铅锌", "铜"])
        self.assertTrue(payload["fallback_used"])

    def test_hotspots_enriches_missing_metrics_from_dsa_provider(self) -> None:
        config = self._config(enabled=True)

        class HotspotRows(list):
            provider_used = "akshare"
            fallback_used = False
            source_errors = []
            stale = False
            stale_age_hours = None

        class FakeProvider(alphasift_service.DsaEastMoneyHotspotProvider):
            def hotspot_rows(self, *, top: int = 12) -> List[Dict[str, Any]]:
                return [{
                    "topic": "铜",
                    "name": "工业金属 · 铜",
                    "heat_score": 92.0,
                    "change_pct": 7.03,
                    "trend_score": 99.0,
                    "persistence_score": 64.3,
                    "sample_stock_count": 11,
                    "leaders": ["嘉元科技", "方邦股份"],
                    "theme_group": "工业金属",
                }]

        discover = MagicMock(return_value=HotspotRows([{
            "topic": "铜",
            "name": "铜",
            "heat_score": 92.0,
            "change_pct": 7.03,
        }]))

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "hotspots.json"
            with (
                patch("src.services.alphasift_service.DSA_ALPHASIFT_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", FakeProvider())),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace(discover_hotspots=discover)),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=1, refresh=True)

        hotspot = payload["hotspots"][0]
        self.assertEqual(hotspot["name"], "工业金属 · 铜")
        self.assertEqual(hotspot["trend_score"], 99.0)
        self.assertEqual(hotspot["persistence_score"], 64.3)
        self.assertEqual(hotspot["sample_stock_count"], 11)
        self.assertEqual(hotspot["leaders"], ["嘉元科技", "方邦股份"])

    def test_hotspots_default_cache_miss_does_not_import_hotspot_module(self) -> None:
        config = self._config(enabled=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing-hotspots.json"
            import_hotspot = MagicMock(side_effect=AssertionError("default cache read must not import live hotspot module"))
            with (
                patch("src.services.alphasift_service.DSA_ALPHASIFT_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._import_alphasift_hotspot", import_hotspot),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=6, refresh=False)

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["provider"], "akshare")
        self.assertEqual(payload["cache_used"], False)
        self.assertEqual(payload["hotspots"], [])
        self.assertEqual(payload["hotspot_count"], 0)
        self.assertEqual(payload["source_errors"], [])
        import_hotspot.assert_not_called()

    def test_hotspots_ignores_too_thin_default_cache(self) -> None:
        config = self._config(enabled=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "hotspots.json"
            cache_path.write_text(
                json.dumps({
                    "cached_at": "2026-06-13T08:06:50Z",
                    "payload": {
                        "enabled": True,
                        "provider": "akshare",
                        "hotspots": [{"topic": "AI算力", "name": "AI算力", "heat_score": 88.0}],
                        "hotspot_count": 1,
                    },
                }),
                encoding="utf-8",
            )
            import_hotspot = MagicMock(side_effect=AssertionError("default cache read must not import live hotspot module"))
            with (
                patch("src.services.alphasift_service.DSA_ALPHASIFT_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._import_alphasift_hotspot", import_hotspot),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=12, refresh=False)

        self.assertEqual(payload["hotspots"], [])
        self.assertEqual(payload["hotspot_count"], 0)
        import_hotspot.assert_not_called()


    def test_hotspots_uses_last_success_cache_by_default(self) -> None:
        config = self._config(enabled=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "hotspots.json"
            cache_path.write_text(
                json.dumps({
                    "cached_at": "2026-06-07T12:00:00Z",
                    "payload": {
                        "enabled": True,
                        "provider": "akshare",
                        "provider_used": "DsaEastMoneyHotspotProvider",
                        "fallback_used": False,
                        "cache_used": False,
                        "cached_at": "2026-06-07T12:00:00Z",
                        "source_errors": [],
                        "hotspots": [
                            {"topic": "玻璃基板", "heat_score": 88.0},
                            {"topic": "机器人执行器", "heat_score": 80.0},
                        ],
                        "hotspot_count": 2,
                    },
                }),
                encoding="utf-8",
            )
            discover = MagicMock()
            with (
                patch("src.services.alphasift_service.DSA_ALPHASIFT_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace(discover_hotspots=discover)),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=1, refresh=False)

        self.assertEqual(payload["cache_used"], True)
        self.assertEqual(payload["cached_at"], "2026-06-07T12:00:00Z")
        self.assertEqual(payload["hotspot_count"], 1)
        self.assertEqual(payload["hotspots"][0]["topic"], "玻璃基板")
        discover.assert_not_called()

    def test_hotspots_refresh_falls_back_to_cache_when_provider_returns_only_errors(self) -> None:
        config = self._config(enabled=True)

        class HotspotRows(list):
            provider_used = "akshare"
            fallback_used = False
            source_errors = ["akshare returned no usable board rows"]
            stale = False
            stale_age_hours = None

        rows = HotspotRows()
        discover = MagicMock(return_value=rows)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "hotspots.json"
            cache_path.write_text(
                json.dumps({
                    "cached_at": "2026-06-07T12:00:00Z",
                    "payload": {
                        "enabled": True,
                        "provider": "akshare",
                        "provider_used": "DsaEastMoneyHotspotProvider",
                        "fallback_used": False,
                        "cache_used": False,
                        "cached_at": "2026-06-07T12:00:00Z",
                        "source_errors": [],
                        "hotspots": [
                            {"topic": "MLCC", "heat_score": 91.0},
                        ],
                        "hotspot_count": 1,
                    },
                }),
                encoding="utf-8",
            )
            provider = alphasift_service.DsaEastMoneyHotspotProvider()
            provider.hotspot_rows = MagicMock(return_value=[])
            with (
                patch("src.services.alphasift_service.DSA_ALPHASIFT_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace(discover_hotspots=discover)),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=1, refresh=True)

        self.assertEqual(payload["cache_used"], True)
        self.assertEqual(payload["fallback_used"], True)
        self.assertEqual(payload["hotspot_count"], 1)
        self.assertEqual(payload["hotspots"][0]["topic"], "MLCC")
        self.assertIn("akshare returned no usable board rows", payload["source_errors"])
        discover.assert_called_once()

    def test_hotspots_refresh_failure_without_cache_returns_friendly_empty_payload(self) -> None:
        config = self._config(enabled=True)
        discover = MagicMock(side_effect=RuntimeError("RemoteDisconnected('Remote end closed connection without response')"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing-hotspots.json"
            provider = alphasift_service.DsaEastMoneyHotspotProvider()
            with (
                patch("src.services.alphasift_service.DSA_ALPHASIFT_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace(discover_hotspots=discover)),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=1, refresh=True)

        self.assertEqual(payload["hotspots"], [])
        self.assertEqual(payload["hotspot_count"], 0)
        self.assertEqual(payload["source_errors"], ["eastmoney_hotspot_unavailable"])
        self.assertEqual(payload["message"], "热点源连接中断，暂无可用缓存。")
        self.assertNotIn("RemoteDisconnected", payload["message"])
        discover.assert_called_once()

    def test_hotspots_refresh_runtime_failure_without_cache_raises_integration_error(self) -> None:
        config = self._config(enabled=True)
        discover = MagicMock(side_effect=RuntimeError("adapter contract returned invalid payload"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing-hotspots.json"
            provider = alphasift_service.DsaEastMoneyHotspotProvider()
            with (
                patch("src.services.alphasift_service.DSA_ALPHASIFT_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace(discover_hotspots=discover)),
            ):
                with self.assertRaises(HTTPException) as caught:
                    self._hotspots(config=config, provider="akshare", top=1, refresh=True)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "alphasift_hotspot_refresh_failed")
        self.assertIn("adapter contract returned invalid payload", caught.exception.detail["message"])
        discover.assert_called_once()

    def test_hotspots_refresh_non_akshare_failure_without_cache_raises_integration_error(self) -> None:
        config = self._config(enabled=True)
        discover = MagicMock(side_effect=RuntimeError("RemoteDisconnected('remote provider failed')"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing-hotspots.json"
            with (
                patch("src.services.alphasift_service.DSA_ALPHASIFT_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("custom", "custom")),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace(discover_hotspots=discover)),
            ):
                with self.assertRaises(HTTPException) as caught:
                    self._hotspots(config=config, provider="custom", top=1, refresh=True)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "alphasift_hotspot_refresh_failed")
        self.assertIn("RemoteDisconnected", caught.exception.detail["message"])
        discover.assert_called_once()

    def test_hotspot_provider_retries_transient_eastmoney_failure(self) -> None:
        import requests

        provider = alphasift_service.DsaEastMoneyHotspotProvider()

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> Dict[str, Any]:
                return {
                    "data": {
                        "diff": [
                            {"f14": "AI算力", "f3": 4.2, "f140": "工业富联", "f104": 8, "f105": 2},
                        ]
                    }
                }

        get_mock = MagicMock(side_effect=[requests.exceptions.ConnectionError("Connection aborted"), FakeResponse()])
        provider._last_request_ts = time.monotonic()
        with (
            patch("src.services.alphasift_service.time.sleep") as sleep_mock,
            patch.object(provider._session, "get", get_mock),
            patch("requests.get", side_effect=AssertionError("bare requests.get should not be used for EastMoney hotspots")) as bare_get,
        ):
            frame = provider._fetch_board_names(source_fs="m:90 t:3 f:!50")

        self.assertFalse(frame.empty)
        self.assertEqual(frame.iloc[0]["name"], "AI算力")
        self.assertEqual(get_mock.call_count, 2)
        bare_get.assert_not_called()
        sleep_values = [call.args[0] for call in sleep_mock.call_args_list if call.args]
        self.assertIn(0.3, sleep_values)
        self.assertTrue(any(0 < value <= provider._min_request_interval for value in sleep_values))

    def test_hotspots_respects_custom_alphasift_data_dir_for_cache_paths(self) -> None:
        config = self._config(enabled=True)

        class HotspotRows(list):
            provider_used = "akshare"
            fallback_used = False
            source_errors = []
            stale = False
            stale_age_hours = None

        rows = HotspotRows([
            {"topic": "机器人执行器", "heat_score": 86.0, "change_pct": 4.2},
            {"topic": "减速器", "heat_score": 82.0, "change_pct": 3.8},
            {"topic": "铜", "heat_score": 80.0, "change_pct": 3.2},
        ])
        captured: Dict[str, Any] = {}

        def discover(**kwargs):
            captured.update(kwargs)
            return rows

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "persistent-alphasift"
            cache_path = data_dir / "hotspots.json"
            history_path = data_dir / "hotspot.history.jsonl"
            with (
                patch.dict(os.environ, {"ALPHASIFT_DATA_DIR": str(data_dir)}, clear=False),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch(
                    "src.services.alphasift_service._import_alphasift_hotspot",
                    return_value=SimpleNamespace(discover_hotspots=discover),
                ),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=3, refresh=True)

            self.assertEqual(payload["hotspots"][0]["topic"], "机器人执行器")
            self.assertEqual(captured["history_path"], history_path)
            self.assertEqual(captured["fallback_cache_path"], cache_path)
            self.assertTrue(cache_path.exists())

            discover_again = MagicMock()
            with (
                patch.dict(os.environ, {"ALPHASIFT_DATA_DIR": str(data_dir)}, clear=False),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch(
                    "src.services.alphasift_service._import_alphasift_hotspot",
                    return_value=SimpleNamespace(discover_hotspots=discover_again),
                ),
            ):
                cached = self._hotspots(config=config, provider="akshare", top=1, refresh=False)

            cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertEqual(cached["cache_used"], True)
        self.assertEqual(cached["hotspots"][0]["topic"], "机器人执行器")
        discover_again.assert_not_called()
        self.assertEqual(cache_payload["schema_version"], 2)
        self.assertEqual(cache_payload["hotspots"][0]["topic"], "机器人执行器")

    def test_hotspots_reads_alphasift_v2_hotspot_cache(self) -> None:
        config = self._config(enabled=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "hotspots.json"
            cache_path.write_text(
                json.dumps({
                    "schema_version": 2,
                    "generated_at": "2026-06-13T02:55:00Z",
                    "source_errors": "provider timeout",
                    "metadata": {"schema_version": 2, "provider_used": "last_good_cache"},
                    "hotspots": [
                        {
                            "topic": "算力",
                            "canonical_topic": "算力",
                            "aliases": ["AI算力"],
                            "heat_score": 88.0,
                            "quality_status": "available",
                        }
                    ],
                }),
                encoding="utf-8",
            )
            discover = MagicMock()
            with (
                patch("src.services.alphasift_service.DSA_ALPHASIFT_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace(discover_hotspots=discover)),
            ):
                cached = self._hotspots(config=config, provider="akshare", top=1, refresh=False)

        self.assertEqual(cached["cache_used"], True)
        self.assertEqual(cached["cached_at"], "2026-06-13T02:55:00Z")
        self.assertEqual(cached["schema_version"], 2)
        self.assertEqual(cached["source_errors"], ["provider timeout"])
        self.assertEqual(cached["hotspots"][0]["canonical_topic"], "算力")
        discover.assert_not_called()

    def test_hotspots_refresh_prefetches_detail_payloads(self) -> None:
        config = self._config(enabled=True)

        class HotspotRows(list):
            provider_used = "akshare"
            fallback_used = False
            source_errors = []
            stale = False
            stale_age_hours = None

        rows = HotspotRows([
            {"topic": "Moly", "heat_score": 96.0, "change_pct": 10.0},
            {"topic": "Copper", "heat_score": 88.0, "change_pct": 6.0},
        ])

        def detail_side_effect(*, topic: str, provider: str = "", refresh: bool = False) -> Dict[str, Any]:
            return {
                "enabled": True,
                "provider": provider,
                "topic": topic,
                "summary": f"{topic} summary",
                "route": [{"title": f"{topic} event", "description": f"{topic} catalyst"}],
                "stocks": [],
                "stock_count": 0,
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "alphasift"
            with (
                patch.dict(os.environ, {"ALPHASIFT_DATA_DIR": str(data_dir)}, clear=False),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch(
                    "src.services.alphasift_service._import_alphasift_hotspot",
                    return_value=SimpleNamespace(discover_hotspots=MagicMock(return_value=rows)),
                ),
                patch.object(alphasift_service.AlphaSiftService, "hotspot_detail", side_effect=detail_side_effect) as detail_mock,
            ):
                payload = self._hotspots(config=config, provider="akshare", top=2, refresh=True, include_details=True)

            cache_payload = json.loads((data_dir / "hotspots.json").read_text(encoding="utf-8"))

        self.assertEqual(set(payload["details"].keys()), {"Moly", "Copper"})
        self.assertEqual(payload["details"]["Moly"]["route"][0]["title"], "Moly event")
        self.assertEqual(cache_payload["payload"]["details"]["Copper"]["summary"], "Copper summary")
        self.assertEqual(detail_mock.call_count, 2)

    def test_hotspot_news_local_summary_extracts_event_instead_of_truncating(self) -> None:
        text = (
            "【股商异动】钼板块异动大涨5.64%！金钼股份涨停，机构看好行业机遇。"
            "消息称以钼代钨带动小金属行情，市场关注材料替代和供需偏紧。"
            "截至10:30，相关个股现价和成交额继续变化，后续建议关注供需平衡。"
        )

        summary = alphasift_service._summarize_hotspot_news_event_locally(topic="钼", text=text)

        self.assertIn("以钼代钨", summary)
        self.assertIn("小金属", summary)
        self.assertNotIn("截至", summary)
        self.assertNotIn("后续建议", summary)
        self.assertLessEqual(len(summary), alphasift_service.DSA_ALPHASIFT_HOTSPOT_EVENT_SUMMARY_MAX_CHARS)

    def test_hotspot_detail_uses_alphasift_contract_detail_cache(self) -> None:
        config = self._config(enabled=True)
        captured: Dict[str, Any] = {}

        def get_hotspot_detail(topic: str, **kwargs: Any) -> Dict[str, Any]:
            captured.update({"topic": topic, **kwargs})
            return {
                "summary": {
                    "topic": topic,
                    "name": "算力",
                    "canonical_topic": "算力",
                    "aliases": "AI算力",
                    "heat_score": 88.0,
                    "stage": "加速主升",
                    "leaders": ["算力龙头"],
                    "quality_status": "stale",
                    "missing_fields": "live_stocks",
                    "source_errors": "none: no live detail rows",
                    "fallback_used": True,
                    "stale": True,
                    "stale_age_hours": 1.5,
                    "resolver_candidates": [{"topic": "算力", "confidence": 1.0}],
                },
                "stocks": [{
                    "code": "300001",
                    "name": "算力龙头",
                    "role": "核心龙头",
                    "source": "last_good_cache.leader_stocks",
                    "source_confidence": 0.65,
                    "fallback_used": True,
                }],
                "timeline": [{"date": "2026-06-13", "source": "新闻", "title": "AI算力催化"}],
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "alphasift"
            provider = alphasift_service.DsaEastMoneyHotspotProvider()
            with (
                patch.dict(os.environ, {"ALPHASIFT_DATA_DIR": str(data_dir)}, clear=False),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch(
                    "src.services.alphasift_service._import_alphasift_hotspot",
                    return_value=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
                ),
            ):
                payload = self._hotspot_detail(config=config, provider="akshare", topic="AI算力")

        self.assertEqual(captured["topic"], "AI算力")
        self.assertIs(captured["provider"], provider)
        self.assertEqual(captured["fallback_cache_path"], data_dir / "hotspots.json")
        self.assertEqual(captured["history_path"], data_dir / "hotspot.history.jsonl")
        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["provider"], "akshare")
        self.assertEqual(payload["topic"], "AI算力")
        self.assertEqual(payload["canonical_topic"], "算力")
        self.assertEqual(payload["quality_status"], "stale")
        self.assertEqual(payload["aliases"], ["AI算力"])
        self.assertEqual(payload["missing_fields"], ["live_stocks"])
        self.assertEqual(payload["source_errors"], ["none: no live detail rows"])
        self.assertEqual(payload["stocks"][0]["source"], "last_good_cache.leader_stocks")
        self.assertEqual(payload["leader_stocks"][0]["source"], "last_good_cache.leader_stocks")
        self.assertEqual(payload["route"][0]["title"], "AI算力催化")

    def test_hotspot_detail_backfills_stocks_from_contract_leader_stocks(self) -> None:
        config = self._config(enabled=True)

        def get_hotspot_detail(topic: str, **_kwargs: Any) -> Dict[str, Any]:
            return {
                "summary": {"topic": topic, "name": "算力"},
                "leader_stocks": [{
                    "code": "300001",
                    "name": "算力龙头",
                    "role": "核心龙头",
                    "source": "last_good_cache.leader_stocks",
                }],
                "route": [{"title": "盘中发酵", "description": "真实新闻催化", "source": "news"}],
            }

        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(side_effect=AssertionError("provider route fallback should not be used"))
        with (
            patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
            patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
            patch(
                "src.services.alphasift_service._import_alphasift_hotspot",
                return_value=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
            ),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="AI算力")

        self.assertEqual(payload["stocks"][0]["name"], "算力龙头")
        self.assertEqual(payload["leader_stocks"][0]["name"], "算力龙头")
        self.assertEqual(payload["stock_count"], 1)
        provider.hotspot_detail.assert_not_called()

    def test_hotspot_detail_compat_backfills_from_summary_detail_leader_stocks(self) -> None:
        payload = alphasift_service._ensure_hotspot_detail_compat_fields({
            "summary_detail": {
                "leader_stocks": [{
                    "code": "300001",
                    "name": "缓存龙头",
                    "source": "legacy.summary_detail.leader_stocks",
                }],
            },
        })

        self.assertEqual(payload["stocks"][0]["name"], "缓存龙头")
        self.assertEqual(payload["leader_stocks"][0]["name"], "缓存龙头")
        self.assertEqual(payload["stock_count"], 1)

    def test_hotspot_detail_backfills_stocks_from_summary_leader_stocks(self) -> None:
        config = self._config(enabled=True)

        def get_hotspot_detail(topic: str, **_kwargs: Any) -> Dict[str, Any]:
            return {
                "summary": {
                    "topic": topic,
                    "name": "算力",
                    "leader_stocks": [{
                        "code": "300001",
                        "name": "嵌套龙头",
                        "role": "缓存龙头",
                        "source": "last_good_cache.summary.leader_stocks",
                    }],
                },
                "route": [{"title": "盘中发酵", "description": "真实新闻催化", "source": "news"}],
            }

        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(side_effect=AssertionError("provider route fallback should not be used"))
        with (
            patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
            patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
            patch(
                "src.services.alphasift_service._import_alphasift_hotspot",
                return_value=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
            ),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="AI算力")

        self.assertEqual(payload["stocks"][0]["name"], "嵌套龙头")
        self.assertEqual(payload["leader_stocks"][0]["name"], "嵌套龙头")
        self.assertEqual(payload["stock_count"], 1)
        provider.hotspot_detail.assert_not_called()

    def test_hotspot_detail_uses_dsa_detail_cache_after_first_fetch(self) -> None:
        config = self._config(enabled=True)
        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(return_value={
            "topic": "钼",
            "name": "小金属 · 钼",
            "summary": "钼 当前涨跌幅 10.00%。",
            "route": [{"title": "当日发酵", "description": "钼板块异动。", "source": "eastmoney_board_change"}],
            "stocks": [{"code": "001257", "name": "盛龙股份"}],
            "stock_count": 1,
            "source_errors": [],
        })

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.dict(os.environ, {"ALPHASIFT_DATA_DIR": str(Path(tmpdir) / "alphasift")}, clear=False),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace()),
            ):
                first = self._hotspot_detail(config=config, provider="akshare", topic="钼")
                second = self._hotspot_detail(config=config, provider="akshare", topic="钼")

        provider.hotspot_detail.assert_called_once_with("钼")
        self.assertFalse(first.get("cache_used", False))
        self.assertTrue(second["cache_used"])
        self.assertEqual(second["stocks"][0]["name"], "盛龙股份")
        self.assertEqual(second["leader_stocks"][0]["name"], "盛龙股份")

    def test_hotspot_detail_refresh_bypasses_dsa_detail_cache(self) -> None:
        config = self._config(enabled=True)
        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(side_effect=[
            {
                "topic": "钼",
                "summary": "旧详情",
                "route": [{"title": "旧发酵", "description": "旧缓存", "source": "eastmoney_board_change"}],
                "stocks": [{"code": "001257", "name": "旧龙头"}],
                "stock_count": 1,
                "source_errors": [],
            },
            {
                "topic": "钼",
                "summary": "新详情",
                "route": [{"title": "新发酵", "description": "实时刷新", "source": "eastmoney_board_change"}],
                "stocks": [{"code": "001257", "name": "新龙头"}],
                "stock_count": 1,
                "source_errors": [],
            },
        ])

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.dict(os.environ, {"ALPHASIFT_DATA_DIR": str(Path(tmpdir) / "alphasift")}, clear=False),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace()),
            ):
                first = self._hotspot_detail(config=config, provider="akshare", topic="钼")
                cached = self._hotspot_detail(config=config, provider="akshare", topic="钼")
                refreshed = self._hotspot_detail(config=config, provider="akshare", topic="钼", refresh=True)

        self.assertEqual(provider.hotspot_detail.call_count, 2)
        self.assertEqual(first["stocks"][0]["name"], "旧龙头")
        self.assertEqual(cached["stocks"][0]["name"], "旧龙头")
        self.assertTrue(cached["cache_used"])
        self.assertEqual(refreshed["stocks"][0]["name"], "新龙头")
        self.assertFalse(refreshed.get("cache_used", False))

    def test_hotspot_detail_adds_real_search_event_when_configured(self) -> None:
        config = Config(alphasift_enabled=True, bocha_api_keys=["test-key"])
        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(return_value={
            "topic": "钼",
            "summary": "钼 当前涨跌幅 10.00%。",
            "route": [{"title": "当日发酵", "description": "钼板块异动。", "source": "eastmoney_board_change"}],
            "stocks": [],
            "stock_count": 0,
            "source_errors": [],
        })
        search_service = MagicMock()
        search_service.search_stock_news.return_value = SimpleNamespace(
            success=True,
            provider="Bocha",
            results=[
                SimpleNamespace(
                    title="以钼代钨带动小金属行情",
                    snippet=(
                        "以钼代钨带动小金属行情 2026-06-12 市场关注材料替代和供需偏紧。"
                        "金钼股份、盛龙股份等相关个股出现异动，报道还详细列出价格、成交、"
                        "机构观点、供需格局和完整产业链背景，后续建议继续关注供需平衡与政策动力。"
                    ),
                    url="https://example.com/news",
                    source="ExampleNews",
                    published_date="2026-06-12",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.dict(os.environ, {"ALPHASIFT_DATA_DIR": str(Path(tmpdir) / "alphasift")}, clear=False),
                patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
                patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.alphasift_service._import_alphasift_hotspot", return_value=SimpleNamespace()),
                patch("src.search_service.SearchService", return_value=search_service),
            ):
                payload = self._hotspot_detail(config=config, provider="akshare", topic="钼")

        self.assertEqual(payload["route"][0]["source"], "ExampleNews")
        self.assertEqual(payload["route"][0]["title"], "消息催化")
        self.assertEqual(payload["route"][0]["date"], "2026-06-12")
        self.assertEqual(payload["route"][0]["url"], "https://example.com/news")
        self.assertLessEqual(len(payload["route"][0]["description"]), 93)
        self.assertNotIn("完整产业链背景", payload["route"][0]["description"])
        search_service.search_stock_news.assert_called_once()

    def test_hotspot_detail_prefers_timeline_when_contract_route_is_empty(self) -> None:
        config = self._config(enabled=True)
        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(side_effect=RuntimeError("provider fallback should not be used"))

        def get_hotspot_detail(topic: str, **_kwargs: Any) -> Dict[str, Any]:
            return {
                "summary": {
                    "topic": topic,
                    "name": "算力",
                    "canonical_topic": "算力",
                    "quality_status": "available",
                },
                "stocks": [{
                    "code": "300001",
                    "name": "算力龙头",
                }],
                "timeline": [{"date": "2026-06-13", "source": "新闻", "title": "AI算力催化"}],
                "route": [],
            }

        with (
            patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
            patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
            patch(
                "src.services.alphasift_service._import_alphasift_hotspot",
                return_value=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
            ),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="AI算力")

        self.assertEqual(payload["route"][0]["title"], "AI算力催化")
        self.assertEqual(payload["route"][0]["source"], "新闻")
        provider.hotspot_detail.assert_not_called()

    def test_hotspot_detail_falls_back_to_provider_when_contract_helper_fails(self) -> None:
        config = self._config(enabled=True)
        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(return_value={
            "topic": "机器人执行器",
            "summary": "机器人执行器 盘中发酵。",
            "route": [{"title": "盘中发酵", "description": "provider fallback route.", "source": "eastmoney_board_change"}],
            "stocks": [{"code": "002000", "name": "旧路径个股"}],
            "stock_count": 1,
            "source_errors": [],
        })

        def get_hotspot_detail(topic: str, **_kwargs: Any) -> Dict[str, Any]:
            raise RuntimeError("contract parser broken")

        with (
            patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
            patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
            patch(
                "src.services.alphasift_service._import_alphasift_hotspot",
                return_value=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
            ),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="机器人执行器")

        self.assertEqual(payload["route"][0]["title"], "盘中发酵")
        self.assertEqual(payload["route"][0]["source"], "eastmoney_board_change")
        provider.hotspot_detail.assert_called_once_with("机器人执行器")
        self.assertEqual(
            payload["source_errors"][0],
            "alphasift_hotspot_detail_fallback: contract parser broken",
        )
        self.assertTrue(payload["fallback_used"])

    def test_hotspot_detail_preserves_provider_route_when_contract_detail_has_no_timeline(self) -> None:
        config = self._config(enabled=True)
        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(return_value={
            "topic": "机器人执行器",
            "summary": "机器人执行器 盘中发酵。",
            "route": [{
                "title": "盘中发酵",
                "description": "机器人执行器 当前有异动记录。",
                "source": "eastmoney_board_change",
            }],
            "stocks": [{"code": "002000", "name": "旧路径个股"}],
            "stock_count": 1,
            "source_errors": [],
        })

        def get_hotspot_detail(topic: str, **_kwargs: Any) -> Dict[str, Any]:
            return {
                "summary": {
                    "topic": topic,
                    "name": "机器人执行器",
                    "canonical_topic": "机器人执行器",
                    "quality_status": "available",
                },
                "stocks": [{
                    "code": "300000",
                    "name": "合约路径个股",
                    "source": "alphasift_contract",
                }],
            }

        with (
            patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
            patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
            patch(
                "src.services.alphasift_service._import_alphasift_hotspot",
                return_value=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
            ),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="机器人执行器")

        self.assertEqual(payload["route"][0]["title"], "盘中发酵")
        self.assertEqual(payload["route"][0]["source"], "eastmoney_board_change")
        self.assertEqual(payload["stocks"][0]["name"], "合约路径个股")
        provider.hotspot_detail.assert_called_once_with("机器人执行器")

    def test_hotspot_detail_returns_route_and_concept_stocks(self) -> None:
        config = self._config(enabled=True)

        class FakeProvider(alphasift_service.DsaEastMoneyHotspotProvider):
            def hotspot_detail(self, topic: str) -> Dict[str, Any]:
                return {
                    "topic": topic,
                    "summary": f"{topic} 盘中发酵。",
                    "route": [{"title": "盘中发酵", "description": "出现大笔买入。"}],
                    "stocks": [{"code": "920438", "name": "戈碧迦", "role": "异动核心"}],
                    "stock_count": 1,
                    "source_errors": [],
                }

        with (
            patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
            patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", FakeProvider())),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="玻璃基板")

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["provider"], "akshare")
        self.assertEqual(payload["topic"], "玻璃基板")
        self.assertEqual(payload["route"][0]["title"], "盘中发酵")
        self.assertEqual(payload["stocks"][0]["name"], "戈碧迦")
        self.assertEqual(payload["leader_stocks"][0]["name"], "戈碧迦")

    def test_hotspot_detail_route_accepts_slash_containing_topic(self) -> None:
        config = self._config(enabled=True)
        app = FastAPI()
        app.include_router(alphasift_endpoint.router, prefix="/api/v1/alphasift")
        app.dependency_overrides[alphasift_endpoint.get_config_dep] = lambda: config
        service = MagicMock()
        service.hotspot_detail.return_value = {
            "enabled": True,
            "provider": "akshare",
            "topic": "DRG/DIP",
            "route": [],
            "stocks": [],
            "stock_count": 0,
        }

        with patch("api.v1.endpoints.alphasift._service", return_value=service):
            response = TestClient(app).get("/api/v1/alphasift/hotspots/DRG%2FDIP?provider=akshare")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["topic"], "DRG/DIP")
        service.hotspot_detail.assert_called_once_with(topic="DRG/DIP", provider="akshare", refresh=False)

    def test_hotspot_detail_falls_back_when_ths_constituents_fail(self) -> None:
        import pandas as pd

        config = self._config(enabled=True)

        class FakeProvider(alphasift_service.DsaEastMoneyHotspotProvider):
            def _fetch_ths_constituents(self, topic: str) -> Any:
                raise TimeoutError("ths timeout")

            def _fallback_constituents(self, topic: str) -> Any:
                return pd.DataFrame([{
                    "code": "300000",
                    "name": "中际旭创",
                    "change_pct": None,
                    "hot_stock_score": 60.0,
                }])

            def _fetch_eastmoney_constituents(self, topic: str, *, source: str) -> Any:
                return pd.DataFrame()

            def _find_board_change(self, topic: str) -> Dict[str, Any]:
                return {}

            def _build_hotspot_route(self, topic: str, summary: Dict[str, Any]) -> Any:
                return [{"title": "fallback", "description": topic, "source": "test"}]

            def _fetch_ths_info(self, topic: str) -> Dict[str, str]:
                return {}

        with (
            patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
            patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", FakeProvider())),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="AI算力")

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["provider"], "akshare")
        self.assertEqual(payload["topic"], "AI算力")
        self.assertEqual(payload["stocks"][0]["name"], "中际旭创")
        self.assertEqual(payload["route"][0]["title"], "fallback")

    def test_hotspot_provider_merges_constituent_sources_before_single_leader_fallback(self) -> None:
        import pandas as pd

        class FakeProvider(alphasift_service.DsaEastMoneyHotspotProvider):
            def _fetch_eastmoney_constituents(self, topic: str, *, source: str) -> Any:
                return pd.DataFrame([
                    {"代码": "000001", "名称": "平安银行", "涨跌幅": 1.2},
                    {"代码": "000002", "名称": "万科A", "涨跌幅": 0.8},
                ])

            def _fetch_ths_constituents(self, topic: str) -> Any:
                return pd.DataFrame([
                    {"code": "000002", "name": "万科A"},
                    {"code": "000003", "name": "国农科技"},
                ])

            def _fallback_constituents(self, topic: str) -> Any:
                return pd.DataFrame([{
                    "code": "000001",
                    "name": "平安银行",
                    "hot_stock_score": 60.0,
                }])

        provider = FakeProvider()
        frame = provider.stock_board_concept_cons_em("金融")

        self.assertEqual(list(frame["code"]), ["000001", "000002", "000003"])
        self.assertEqual(provider.stock_board_concept_cons_em("金融").shape[0], 3)

    def test_hotspot_provider_adds_related_metal_leaders_for_narrow_topic(self) -> None:
        import pandas as pd

        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        raw = pd.DataFrame([
            {
                "板块名称": "钼",
                "涨跌幅": 10.0,
                "板块异动最频繁个股及所属类型-股票代码": "001257",
                "板块异动最频繁个股及所属类型-股票名称": "盛龙股份",
            },
            {
                "板块名称": "钴",
                "涨跌幅": 5.9,
                "板块异动最频繁个股及所属类型-股票代码": "300618",
                "板块异动最频繁个股及所属类型-股票名称": "寒锐钴业",
            },
            {
                "板块名称": "铜",
                "涨跌幅": 7.0,
                "板块异动最频繁个股及所属类型-股票代码": "600362",
                "板块异动最频繁个股及所属类型-股票名称": "江西铜业",
            },
        ])
        with patch.object(provider, "_fetch_board_changes_raw", return_value=raw):
            frame = provider._related_hotspot_constituents("钼")

        self.assertEqual(list(frame["code"]), ["001257", "300618"])
        self.assertEqual(frame.iloc[0]["role"], "小金属活跃股")

    def test_hotspot_route_is_grouped_by_daily_markers(self) -> None:
        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        provider._fetch_ths_summary_event = MagicMock(return_value="2026-06-12：政策催化")
        summary = {
            "板块名称": "AI算力",
            "涨跌幅": 4.2,
            "板块异动总次数": 186,
            "板块异动最频繁个股及所属类型-股票名称": "中际旭创",
            "板块具体异动类型列表及出现次数": [{"t": 8203, "ct": 8}, {"t": 8204, "ct": 6}],
        }

        route = provider._build_hotspot_route("AI算力", summary)

        self.assertLessEqual(len(route), 2)
        self.assertEqual(route[0]["date"], datetime.now().date().isoformat())
        self.assertEqual(route[0]["published_at"], route[0]["date"])
        self.assertIn("当日结构", route[0]["description"])
        self.assertEqual(route[1]["date"], "2026-06-12")

    def test_hotspot_route_does_not_invent_metal_catalyst_hint(self) -> None:
        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        provider._fetch_ths_summary_event = MagicMock(return_value="")

        route = provider._build_hotspot_route("钼", {})

        self.assertEqual(route[0]["source"], "fallback")
        self.assertNotIn("以钼代钨", route[0]["description"])

    def test_hotspot_detail_uses_constituent_fallback_when_board_change_summary_fails(self) -> None:
        import pandas as pd

        config = self._config(enabled=True)

        class FakeProvider(alphasift_service.DsaEastMoneyHotspotProvider):
            def _find_board_change(self, topic: str) -> Dict[str, Any]:
                raise TimeoutError("board change timeout")

            def _fetch_ths_constituents(self, topic: str) -> Any:
                return pd.DataFrame()

            def _fetch_eastmoney_constituents(self, topic: str, *, source: str) -> Any:
                return pd.DataFrame([{
                    "代码": "002138",
                    "名称": "顺络电子",
                    "涨跌幅": 3.2,
                }])

            def _fetch_ths_summary_event(self, topic: str) -> str:
                return "需求升温"

            def _fetch_ths_info(self, topic: str) -> Dict[str, str]:
                return {}

        with (
            patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
            patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", FakeProvider())),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="MLCC")

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["topic"], "MLCC")
        self.assertEqual(payload["summary"], "MLCC 当前暂无可用的板块异动摘要。")
        self.assertEqual(payload["route"][0]["source"], "ths_summary")
        self.assertEqual(payload["stocks"][0]["name"], "顺络电子")

    def test_hotspot_detail_uses_industry_constituents_for_industry_hotspots(self) -> None:
        import pandas as pd

        config = self._config(enabled=True)

        class FakeProvider(alphasift_service.DsaEastMoneyHotspotProvider):
            def __init__(self) -> None:
                self.constituent_sources = []

            def stock_board_industry_name_em(self) -> Any:
                return pd.DataFrame([{"name": "电池", "rank": 1}])

            def _fetch_eastmoney_constituents(self, topic: str, *, source: str) -> Any:
                self.constituent_sources.append(source)
                if source == "industry":
                    return pd.DataFrame([{
                        "代码": "300750",
                        "名称": "宁德时代",
                        "涨跌幅": 2.6,
                    }])
                return pd.DataFrame()

            def _fetch_ths_constituents(self, topic: str) -> Any:
                raise AssertionError("industry hotspots must not use concept constituents")

            def _find_board_change(self, topic: str) -> Dict[str, Any]:
                return {}

            def _fetch_ths_summary_event(self, topic: str) -> str:
                return ""

            def _fetch_ths_info(self, topic: str) -> Dict[str, str]:
                return {}

        provider = FakeProvider()
        with (
            patch("src.services.alphasift_service._get_alphasift_status_snapshot", return_value=({}, True, {})),
            patch("src.services.alphasift_service._resolve_hotspot_provider", return_value=("akshare", provider)),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="电池")

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["topic"], "电池")
        self.assertEqual(payload["stocks"][0]["name"], "宁德时代")
        self.assertEqual(provider.constituent_sources, ["industry"])

    def test_hotspot_provider_uses_board_name_fallback_when_rankings_fail(self) -> None:
        import pandas as pd

        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        fallback = pd.DataFrame([{"板块名称": "玻璃基板", "涨跌幅": 1.8, "序号": 1}])
        with (
            patch.object(provider, "_fetch_board_changes", return_value=pd.DataFrame()),
            patch.object(provider, "_fetch_rankings", side_effect=RuntimeError("ranking schema changed")),
            patch.object(provider, "_fetch_board_names", return_value=fallback) as fetch_board_names,
        ):
            concept = provider.stock_board_concept_name_em()
            industry = provider.stock_board_industry_name_em()

        self.assertEqual(concept.iloc[0]["板块名称"], "玻璃基板")
        self.assertEqual(industry.iloc[0]["板块名称"], "玻璃基板")
        fetch_board_names.assert_any_call(source_fs="m:90 t:3 f:!50")
        fetch_board_names.assert_any_call(source_fs="m:90 t:2 f:!50")

    def test_hotspot_provider_continues_fallback_when_board_change_fails(self) -> None:
        import pandas as pd

        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        rankings = pd.DataFrame([{"name": "减速器", "change_pct": 2.2, "rank": 1}])
        with (
            patch.object(provider, "_fetch_board_changes", side_effect=RuntimeError("akshare timeout")),
            patch.object(provider, "_fetch_rankings", return_value=rankings) as fetch_rankings,
        ):
            concept = provider.stock_board_concept_name_em()

        self.assertEqual(concept.iloc[0]["name"], "减速器")
        fetch_rankings.assert_called_once_with("concept")

    def test_hotspot_provider_derives_trend_metrics_from_board_changes(self) -> None:
        import pandas as pd

        board_changes = pd.DataFrame([
            {
                "板块名称": "AI算力",
                "涨跌幅": 4.2,
                "板块异动总次数": 186,
                "板块异动最频繁个股及所属类型-股票名称": "中际旭创",
            },
        ])

        class _MockAkshare:
            calls = 0

            @staticmethod
            def stock_board_change_em():
                _MockAkshare.calls += 1
                return board_changes

        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        with patch.dict("sys.modules", {"akshare": _MockAkshare()}):
            frame = provider._fetch_board_changes()
            summary = provider._find_board_change("AI算力")

        self.assertEqual(_MockAkshare.calls, 1)
        self.assertEqual(frame.iloc[0]["name"], "AI算力")
        self.assertEqual(frame.iloc[0]["stage"], "加速发酵")
        self.assertGreater(frame.iloc[0]["trend_score"], 0)
        self.assertGreater(frame.iloc[0]["persistence_score"], 0)
        self.assertEqual(frame.iloc[0]["sample_stock_count"], 1)
        self.assertEqual(frame.iloc[0]["leaders"], ["中际旭创"])
        self.assertEqual(summary["板块名称"], "AI算力")

    def test_fetch_ths_summary_event_ignores_missing_concept_name_column(self) -> None:
        import pandas as pd

        provider = alphasift_service.DsaEastMoneyHotspotProvider()
        summary = pd.DataFrame([
            {"日期": "2026-06-07", "驱动事件": "行业政策利好"},
        ])

        class _MockAkshare:
            @staticmethod
            def stock_board_concept_summary_ths():
                return summary

        with patch.dict("sys.modules", {"akshare": _MockAkshare()}):
            text = provider._fetch_ths_summary_event("MLCC")

        self.assertEqual(text, "")

    def test_strategies_rejects_when_enabled_but_adapter_missing(self) -> None:
        config = self._config(enabled=True)

        with (
            patch(
                "src.services.alphasift_service._get_alphasift_status_snapshot",
                return_value=({}, False, _missing_alphasift_module_diagnostics()),
            ),
            patch("src.services.alphasift_service._install_alphasift") as install_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                self._strategies(config=config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "alphasift_unavailable")
        self.assertEqual(caught.exception.detail.get("diagnostics", {}).get("reason"), "missing_module")
        install_mock.assert_not_called()

    def test_screen_rejects_when_disabled(self) -> None:
        config = self._config(enabled=False)

        with self.assertRaises(HTTPException) as caught:
            self._screen(config)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "alphasift_disabled")

    def test_screen_rejects_when_alphasift_unavailable(self) -> None:
        config = self._config(enabled=True)

        with (
            patch(
                "src.services.alphasift_service._get_alphasift_status_snapshot",
                return_value=({}, False, _missing_alphasift_module_diagnostics()),
            ),
            patch("src.services.alphasift_service._install_alphasift") as install_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "alphasift_unavailable")
        self.assertEqual(caught.exception.detail.get("diagnostics", {}).get("reason"), "missing_module")
        self.assertIn("pip install -r requirements.txt", caught.exception.detail["message"])
        install_mock.assert_not_called()

    def test_start_screen_task_submits_background_work(self) -> None:
        config = self._config(enabled=True)
        fake_queue = MagicMock()
        fake_queue.submit_background_task.return_value = SimpleNamespace(
            task_id="screen-task-1",
            trace_id="screen-task-1",
            status=QueueTaskStatus.PENDING,
            message="AlphaSift 选股任务已提交",
        )

        with (
            patch("api.v1.endpoints.alphasift.get_task_queue", return_value=fake_queue),
            patch("api.v1.endpoints.alphasift.uuid.uuid4", return_value=SimpleNamespace(hex="screen-task-1")),
            patch.object(
                alphasift_endpoint.AlphaSiftService,
                "screen",
                return_value={"enabled": True, "candidates": [], "candidate_count": 0},
            ) as screen_mock,
        ):
            payload = alphasift_endpoint.alphasift_start_screen_task(
                alphasift_endpoint.AlphaSiftScreenRequest(market="cn", strategy="dual_low", max_results=3),
                http_request=self._request(),
                config=config,
            )
            run_task = fake_queue.submit_background_task.call_args.args[0]
            result = run_task()

        self.assertEqual(payload.task_id, "screen-task-1")
        self.assertEqual(payload.max_results, 3)
        fake_queue.submit_background_task.assert_called_once()
        self.assertEqual(fake_queue.submit_background_task.call_args.kwargs["report_type"], "alphasift_screen")
        screen_mock.assert_called_once_with(strategy="dual_low", market="cn", max_results=3)
        self.assertEqual(result["candidate_count"], 0)
        fake_queue.update_task_progress.assert_any_call(
            "screen-task-1",
            20,
            "正在执行 AlphaSift 选股，外部数据源较慢时会持续后台运行",
        )

    def test_screen_task_status_returns_alphasift_result(self) -> None:
        task = TaskInfo(
            task_id="screen-task-1",
            trace_id="screen-task-1",
            stock_code="alphasift_screen",
            status=QueueTaskStatus.COMPLETED,
            progress=100,
            message="任务执行完成",
            result={"enabled": True, "candidates": [], "candidate_count": 0},
            report_type="alphasift_screen",
        )
        fake_queue = MagicMock()
        fake_queue.get_task.return_value = task

        with patch("api.v1.endpoints.alphasift.get_task_queue", return_value=fake_queue):
            payload = alphasift_endpoint.alphasift_screen_task_status("screen-task-1")

        self.assertEqual(payload.status, "completed")
        self.assertEqual(payload.result["candidate_count"], 0)

    def test_screen_task_status_rejects_non_alphasift_task(self) -> None:
        task = TaskInfo(
            task_id="analysis-task-1",
            stock_code="600519",
            status=QueueTaskStatus.COMPLETED,
            report_type="detailed",
        )
        fake_queue = MagicMock()
        fake_queue.get_task.return_value = task

        with patch("api.v1.endpoints.alphasift.get_task_queue", return_value=fake_queue):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_screen_task_status("analysis-task-1")

        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.detail["error"], "alphasift_screen_task_not_found")

    def test_screen_does_not_auto_install_when_adapter_runtime_unavailable(self) -> None:
        config = self._config(enabled=True)

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch(
                "src.services.alphasift_service._get_alphasift_status_snapshot",
                return_value=(
                    {},
                    False,
                    {"reason": "unexpected_exception", "stage": "get_status", "error_type": "RuntimeError"},
                ),
            ),
            patch("src.services.alphasift_service._install_alphasift") as install_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "alphasift_unavailable")
        self.assertEqual(caught.exception.detail.get("diagnostics", {}).get("resolution"), "no_auto_install")
        self.assertEqual(
            caught.exception.detail.get("diagnostics", {}).get("message"),
            "请先检查后端日志并修复运行时异常，当前未触发修复安装。",
        )
        install_mock.assert_not_called()

    def test_install_rejects_spoofed_localhost_without_admin_session(self) -> None:
        config = self._config(enabled=True)
        request = SimpleNamespace(
            cookies={alphasift_service.COOKIE_NAME: "invalid-session"},
            url=SimpleNamespace(hostname="localhost"),
            client=SimpleNamespace(host="127.0.0.1"),
        )

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "false"}, clear=False),
            patch("src.services.alphasift_service.refresh_auth_state") as refresh_mock,
            patch("src.services.alphasift_service.is_auth_enabled", return_value=True),
            patch("src.services.alphasift_service.verify_session", return_value=False) as verify_session_mock,
            patch("src.services.alphasift_service.subprocess.run") as run_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_install(request=request, config=config)

        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail["error"], "alphasift_install_access_denied")
        refresh_mock.assert_called_once()
        verify_session_mock.assert_called_once_with("invalid-session")
        run_mock.assert_not_called()

    def test_install_allows_valid_admin_session_outside_desktop_mode(self) -> None:
        config = self._config(enabled=True)
        request = self._request({alphasift_service.COOKIE_NAME: "valid-session"})

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "false"}, clear=False),
            patch("src.services.alphasift_service.refresh_auth_state") as refresh_mock,
            patch("src.services.alphasift_service.is_auth_enabled", return_value=True),
            patch("src.services.alphasift_service.verify_session", return_value=True) as verify_session_mock,
            patch("src.services.alphasift_service._install_alphasift", return_value={"installed": True}) as install_mock,
        ):
            payload = alphasift_endpoint.alphasift_install(request=request, config=config)

        self.assertEqual(payload["installed"], True)
        refresh_mock.assert_called_once()
        verify_session_mock.assert_called_once_with("valid-session")
        install_mock.assert_called_once_with(config)

    def test_install_rejects_when_disabled_without_side_effects(self) -> None:
        config = self._config(enabled=False)

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch("src.services.alphasift_service.subprocess.run") as run_mock,
            patch("src.services.alphasift_service._import_alphasift") as import_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_install(request=self._request(), config=config)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "alphasift_disabled")
        import_mock.assert_not_called()
        run_mock.assert_not_called()

    def test_install_invokes_pip_when_enabled_and_missing(self) -> None:
        config = self._config(enabled=True)
        completed = SimpleNamespace(returncode=0, stdout="installed", stderr="")

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch("src.services.alphasift_service._is_alphasift_available", side_effect=[False, True]),
            patch(
                "src.services.alphasift_service._call_alphasift_status",
                return_value={"available": True, "supported_markets": ["cn"], "contract_version": "1", "version": "0.2.0", "strategy_count": 1},
            ),
            patch("src.services.alphasift_service.subprocess.run", return_value=completed) as run_mock,
            patch("src.services.alphasift_service._get_dsa_adapter", return_value=_make_adapter_module()),
        ):
            payload = alphasift_endpoint.alphasift_install(request=self._request(), config=config)

        self.assertEqual(payload["installed"], True)
        self.assertEqual(payload["already_installed"], False)
        self.assertEqual(payload["install_spec_is_default"], True)
        self.assertNotIn("install_spec", payload)
        run_mock.assert_called_once()
        install_command = run_mock.call_args.args[0]
        self.assertIn("--upgrade", install_command)
        self.assertIn("--force-reinstall", install_command)
        self.assertIn(DEFAULT_ALPHASIFT_TEST_SPEC, install_command)

    def test_install_rejects_when_alphasift_adapter_reports_unavailable(self) -> None:
        config = self._config(enabled=True)
        completed = SimpleNamespace(returncode=0, stdout="installed", stderr="")

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch(
                "src.services.alphasift_service._call_alphasift_status",
                side_effect=[
                    {"available": False},
                    {"available": False},
                ],
            ),
            patch("src.services.alphasift_service.subprocess.run", return_value=completed) as run_mock,
            patch("src.services.alphasift_service._get_dsa_adapter") as get_adapter_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_install(request=self._request(), config=config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "alphasift_unavailable")
        run_mock.assert_called_once()
        get_adapter_mock.assert_not_called()

    def test_install_rejects_untrusted_spec(self) -> None:
        config = self._config(enabled=True, install_spec="git+https://example.com/private/alphasift.git")

        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "true"}, clear=False),
            patch("src.services.alphasift_service._is_alphasift_available", return_value=False),
            patch("src.services.alphasift_service.subprocess.run") as run_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_install(request=self._request(), config=config)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "alphasift_install_spec_not_allowed")
        run_mock.assert_not_called()

    def test_screen_calls_dsa_adapter_and_normalizes_llm_fields(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(
                return_value={
                    "run_id": "run123",
                    "strategy": "dual_low",
                    "market": "cn",
                    "snapshot_count": 100,
                    "snapshot_source": "em_datacenter",
                    "after_filter_count": 5,
                    "llm_ranked": True,
                    "llm_coverage": 1.0,
                    "warnings": ["fallback"],
                    "source_errors": [],
                    "deep_analysis_requested": False,
                    "post_analyzers": ["scorecard"],
                    "daily_enriched": True,
                    "daily_enrich_count": 12,
                    "risk_enabled": True,
                    "portfolio_diversity_enabled": True,
                    "portfolio_concentration_notes": ["sector concentration adjusted"],
                    "candidates": [
                        {
                            "code": "600519",
                            "name": "Kweichow Moutai",
                            "score": 88.5,
                            "llm_score": 90.0,
                            "llm_thesis": "LLM likes the setup",
                            "risk_level": "medium",
                            "risk_flags": ["valuation"],
                            "price": 1688.0,
                            "industry": "Baijiu",
                            "factor_scores": {"value": 88.0},
                        }
                    ],
                }
            ),
        )

        with patch("src.services.alphasift_service._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        fake_module.screen.assert_called_once_with(
            "dual_low",
            market="cn",
            max_results=5,
            use_llm=True,
            context=ANY,
        )
        self.assertEqual(fake_module.screen.call_args.kwargs["context"]["llm"]["model"], "")
        self.assertEqual(payload["run_id"], "run123")
        self.assertEqual(payload["snapshot_count"], 100)
        self.assertEqual(payload["snapshot_source"], "em_datacenter")
        self.assertEqual(payload["after_filter_count"], 5)
        self.assertEqual(payload["llm_ranked"], True)
        self.assertEqual(payload["llm_coverage"], 1.0)
        self.assertEqual(payload["warnings"], ["fallback"])
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["post_analyzers"], ["scorecard"])
        self.assertEqual(payload["daily_enriched"], True)
        self.assertEqual(payload["daily_enrich_count"], 12)
        self.assertEqual(payload["portfolio_concentration_notes"], ["sector concentration adjusted"])
        self.assertEqual(payload["candidates"][0]["code"], "600519")
        self.assertEqual(payload["candidates"][0]["llm_score"], 90.0)
        self.assertEqual(payload["candidates"][0]["llm_thesis"], "LLM likes the setup")
        self.assertEqual(payload["candidates"][0]["risk_level"], "medium")
        self.assertEqual(payload["candidates"][0]["price"], 1688.0)
        self.assertEqual(payload["candidates"][0]["industry"], "Baijiu")

    def test_screen_prefers_dsa_daily_history_for_alphasift_enrichment(self) -> None:
        config = self._config(enabled=True)
        parent_module = ModuleType("alphasift")
        daily_module = ModuleType("alphasift.daily")
        original_daily_fetch = MagicMock(side_effect=AssertionError("AlphaSift daily fetch should not run first"))
        daily_module.fetch_daily_history = original_daily_fetch
        parent_module.daily = daily_module
        captured: Dict[str, Any] = {}

        def screen_with_daily_fetch(strategy: str, **kwargs: Any) -> Dict[str, Any]:
            daily_df = daily_module.fetch_daily_history(
                "600519",
                lookback_days=20,
                source="akshare",
                retries=1,
            )
            captured["daily_df"] = daily_df
            captured["context"] = kwargs.get("context")
            return {
                "strategy": strategy,
                "candidates": [{"code": "600519", "score": 88.0}],
            }

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_with_daily_fetch))

        with (
            patch.dict(sys.modules, {"alphasift": parent_module, "alphasift.daily": daily_module}),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
            patch(
                "src.services.alphasift_service.get_dsa_daily_history",
                return_value=(
                    [
                        {
                            "trade_date": "20260603",
                            "close": "10.5",
                            "vol": "123400",
                        }
                    ],
                    "EfinanceFetcher",
                ),
            ) as dsa_history_mock,
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        daily_df = captured["daily_df"]
        self.assertEqual(daily_df.attrs["source"], "dsa:EfinanceFetcher")
        self.assertEqual(daily_df.loc[0, "date"], "2026-06-03")
        self.assertEqual(daily_df.loc[0, "volume"], 123400)
        self.assertEqual(daily_df.loc[0, "open"], 10.5)
        self.assertEqual(payload["candidate_count"], 1)
        self.assertIn("daily_history", captured["context"]["dsa"]["capabilities"])
        self.assertIs(captured["context"]["dsa"]["get_daily_history"], dsa_history_mock)
        dsa_history_mock.assert_called_once_with("600519", lookback_days=20)
        original_daily_fetch.assert_not_called()
        self.assertIs(daily_module.fetch_daily_history, original_daily_fetch)

    def test_screen_enriches_top_candidates_with_dsa_context(self) -> None:
        config = self._config(enabled=True)
        fake_manager = SimpleNamespace(get_stock_name=MagicMock(return_value="贵州茅台"))
        fake_module = _make_adapter_module(
            screen=MagicMock(
                return_value={
                    "candidates": [
                        {
                            "code": "600519",
                            "score": 88.5,
                            "reason": "AlphaSift pick",
                        }
                    ]
                }
            ),
        )

        with (
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
            patch("src.services.alphasift_service._get_dsa_fetcher_manager", return_value=fake_manager),
            patch(
                "src.services.alphasift_service.get_dsa_realtime_quote",
                return_value={"price": 1688.0, "change_pct": 1.2, "amount": 100000000.0},
            ),
            patch(
                "src.services.alphasift_service.get_dsa_fundamental_context",
                return_value={"market": "cn", "coverage": {"valuation": "available"}},
            ),
            patch(
                "src.services.alphasift_service.search_dsa_stock_news",
                return_value={
                    "success": True,
                    "provider": "test",
                    "results": [{"title": "贵州茅台最新公告", "source": "测试源"}],
                },
            ),
        ):
            payload = self._screen(
                config,
                market="cn",
                strategy="dual_low",
                max_results=5,
                mock_enrichment=False,
            )

        candidate = payload["candidates"][0]
        self.assertEqual(candidate["name"], "贵州茅台")
        self.assertEqual(candidate["price"], 1688.0)
        self.assertTrue(candidate["dsa_context"]["enriched"])
        self.assertEqual(candidate["dsa_news"][0]["title"], "贵州茅台最新公告")
        self.assertIn("DSA行情", candidate["dsa_analysis_summary"])
        self.assertEqual(payload["dsa_enrichment"]["enriched_count"], 1)

    def test_screen_reuses_alphasift_dsa_context_without_refetch(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(
                return_value={
                    "candidates": [
                        {
                            "code": "600519",
                            "name": "贵州茅台",
                            "score": 88.5,
                            "dsa_context": {
                                "enriched": True,
                                "quote": {"price": 1688.0, "change_pct": 1.2},
                                "warnings": ["from_alphasift_provider"],
                            },
                            "dsa_news": [{"title": "贵州茅台最新公告", "source": "测试源"}],
                            "dsa_analysis_summary": "DSA新闻: 贵州茅台最新公告",
                        }
                    ]
                }
            ),
        )

        with (
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
            patch("src.services.alphasift_service.get_dsa_realtime_quote") as quote_mock,
            patch("src.services.alphasift_service.get_dsa_fundamental_context") as fundamentals_mock,
            patch("src.services.alphasift_service.search_dsa_stock_news") as news_mock,
        ):
            payload = self._screen(
                config,
                market="cn",
                strategy="dual_low",
                max_results=5,
                mock_enrichment=False,
            )

        candidate = payload["candidates"][0]
        self.assertTrue(candidate["dsa_context"]["enriched"])
        self.assertEqual(candidate["dsa_news"][0]["title"], "贵州茅台最新公告")
        self.assertEqual(candidate["dsa_analysis_summary"], "DSA新闻: 贵州茅台最新公告")
        self.assertEqual(payload["dsa_enrichment"]["enriched_count"], 1)
        self.assertEqual(payload["dsa_enrichment"]["warnings"], ["from_alphasift_provider"])
        quote_mock.assert_not_called()
        fundamentals_mock.assert_not_called()
        news_mock.assert_not_called()

    def test_screen_reuses_context_news_results_without_refetch(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(
                return_value={
                    "candidates": [
                        {
                            "code": "600519",
                            "name": "贵州茅台",
                            "score": 88.5,
                            "dsa_context": {
                                "enriched": True,
                                "quote": {"price": 1688.0, "change_pct": 1.2},
                                "news": {
                                    "success": True,
                                    "summary": "DSA新闻：贵州茅台最新公告",
                                    "results": [{"title": "贵州茅台最新公告", "source": "测试源"}],
                                },
                                "warnings": ["from_alphasift_provider"],
                            },
                            "dsa_news": [],
                        }
                    ]
                }
            ),
        )

        with (
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
            patch("src.services.alphasift_service.get_dsa_realtime_quote") as quote_mock,
            patch("src.services.alphasift_service.get_dsa_fundamental_context") as fundamentals_mock,
            patch("src.services.alphasift_service.search_dsa_stock_news") as news_mock,
        ):
            payload = self._screen(
                config,
                market="cn",
                strategy="dual_low",
                max_results=5,
                mock_enrichment=False,
            )

        candidate = payload["candidates"][0]
        self.assertEqual(candidate["dsa_news"][0]["title"], "贵州茅台最新公告")
        self.assertEqual(candidate["dsa_analysis_summary"], "DSA新闻：贵州茅台最新公告")
        self.assertEqual(payload["dsa_enrichment"]["enriched_count"], 1)
        self.assertEqual(payload["dsa_enrichment"]["warnings"], ["from_alphasift_provider"])
        quote_mock.assert_not_called()
        fundamentals_mock.assert_not_called()
        news_mock.assert_not_called()

    def test_screen_completes_light_alphasift_context_with_news_only(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(
                return_value={
                    "candidates": [
                        {
                            "code": "600519",
                            "name": "贵州茅台",
                            "score": 88.5,
                            "dsa_context": {
                                "enriched": True,
                                "profile": "pre_rank_light",
                                "news_included": False,
                                "quote": {"price": 1688.0, "change_pct": 1.2},
                                "fundamentals": {"coverage": {"valuation": "available"}},
                                "news": {
                                    "success": False,
                                    "skipped": True,
                                    "reason": "pre_rank_light_context",
                                    "results": [],
                                },
                            },
                            "dsa_news": [],
                            "dsa_analysis_summary": "DSA行情: 现价 1688.0",
                        }
                    ]
                }
            ),
        )
        fake_manager = SimpleNamespace(get_stock_name=MagicMock(return_value="贵州茅台"))

        with (
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
            patch("src.services.alphasift_service._get_dsa_fetcher_manager", return_value=fake_manager),
            patch("src.services.alphasift_service.get_dsa_realtime_quote") as quote_mock,
            patch("src.services.alphasift_service.get_dsa_fundamental_context") as fundamentals_mock,
            patch(
                "src.services.alphasift_service.search_dsa_stock_news",
                return_value={
                    "success": True,
                    "provider": "test",
                    "results": [{"title": "贵州茅台最新公告", "source": "测试源"}],
                },
            ) as news_mock,
        ):
            payload = self._screen(
                config,
                market="cn",
                strategy="dual_low",
                max_results=5,
                mock_enrichment=False,
            )

        candidate = payload["candidates"][0]
        self.assertEqual(candidate["dsa_context"]["profile"], "post_rank_full")
        self.assertTrue(candidate["dsa_context"]["news_included"])
        self.assertEqual(candidate["dsa_context"]["quote"]["price"], 1688.0)
        self.assertEqual(candidate["dsa_context"]["fundamentals"]["coverage"]["valuation"], "available")
        self.assertEqual(candidate["dsa_news"][0]["title"], "贵州茅台最新公告")
        quote_mock.assert_not_called()
        fundamentals_mock.assert_not_called()
        news_mock.assert_called_once()

    def test_dsa_pre_rank_candidate_context_omits_news(self) -> None:
        fake_manager = SimpleNamespace(get_stock_name=MagicMock(return_value="贵州茅台"))

        with (
            patch("src.services.alphasift_service._get_dsa_fetcher_manager", return_value=fake_manager),
            patch(
                "src.services.alphasift_service.get_dsa_realtime_quote",
                return_value={"price": 1688.0, "change_pct": 1.2, "amount": 100000000.0},
            ),
            patch(
                "src.services.alphasift_service.get_dsa_fundamental_context",
                return_value={"market": "cn", "coverage": {"valuation": "available"}},
            ),
            patch("src.services.alphasift_service.search_dsa_stock_news") as news_mock,
        ):
            context = alphasift_service.get_dsa_candidate_context("600519", "贵州茅台")

        self.assertEqual(context["profile"], "pre_rank_light")
        self.assertFalse(context["news_included"])
        self.assertTrue(context["news"]["skipped"])
        self.assertEqual(context["quote"]["price"], 1688.0)
        self.assertEqual(context["fundamentals"]["coverage"]["valuation"], "available")
        news_mock.assert_not_called()

    def test_screen_bridges_dsa_llm_config_into_alphasift_runtime(self) -> None:
        config = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="gemini/gemini-2.5-flash",
            litellm_fallback_models=["deepseek/deepseek-chat"],
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "base_url": "",
                    "api_keys": ["dsa-gemini-key"],
                    "models": ["gemini/gemini-2.5-flash"],
                    "extra_headers": {"x-tenant": "dsa"},
                }
            ],
        )
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **kwargs):
            captured["env"] = {
                "LITELLM_MODEL": alphasift_service.os.environ.get("LITELLM_MODEL"),
                "LITELLM_FALLBACK_MODELS": alphasift_service.os.environ.get("LITELLM_FALLBACK_MODELS"),
                "LLM_CHANNELS": alphasift_service.os.environ.get("LLM_CHANNELS"),
                "LLM_GEMINI_PROTOCOL": alphasift_service.os.environ.get("LLM_GEMINI_PROTOCOL"),
                "LLM_GEMINI_API_KEYS": alphasift_service.os.environ.get("LLM_GEMINI_API_KEYS"),
                "LLM_GEMINI_EXTRA_HEADERS": alphasift_service.os.environ.get("LLM_GEMINI_EXTRA_HEADERS"),
                "GEMINI_API_KEY": alphasift_service.os.environ.get("GEMINI_API_KEY"),
                "LLM_CANDIDATE_CONTEXT_ENABLED": alphasift_service.os.environ.get("LLM_CANDIDATE_CONTEXT_ENABLED"),
                "LLM_CANDIDATE_CONTEXT_PROVIDERS": alphasift_service.os.environ.get("LLM_CANDIDATE_CONTEXT_PROVIDERS"),
                "LLM_CANDIDATE_MULTIPLIER": alphasift_service.os.environ.get("LLM_CANDIDATE_MULTIPLIER"),
                "LLM_MAX_CANDIDATES": alphasift_service.os.environ.get("LLM_MAX_CANDIDATES"),
                "DAILY_SOURCE": alphasift_service.os.environ.get("DAILY_SOURCE"),
                "SNAPSHOT_SOURCE_PRIORITY": alphasift_service.os.environ.get("SNAPSHOT_SOURCE_PRIORITY"),
                "ALPHASIFT_DATA_DIR": alphasift_service.os.environ.get("ALPHASIFT_DATA_DIR"),
                "ALPHASIFT_FALLBACK_SNAPSHOT_PATH": alphasift_service.os.environ.get("ALPHASIFT_FALLBACK_SNAPSHOT_PATH"),
                "ALPHASIFT_DAILY_HISTORY_CACHE_DIR": alphasift_service.os.environ.get("ALPHASIFT_DAILY_HISTORY_CACHE_DIR"),
                "ALPHASIFT_INDUSTRY_PROVIDER_CACHE_DIR": alphasift_service.os.environ.get("ALPHASIFT_INDUSTRY_PROVIDER_CACHE_DIR"),
            }
            captured["context"] = kwargs.get("context")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(
                alphasift_service.os.environ,
                {
                    "GEMINI_API_KEY": "outer-key",
                    "SNAPSHOT_SOURCE_PRIORITY": "",
                    "LLM_CANDIDATE_CONTEXT_ENABLED": "true",
                    "LLM_CANDIDATE_MULTIPLIER": "",
                    "LLM_MAX_CANDIDATES": "",
                },
                clear=False,
            ),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)
            self.assertEqual(alphasift_service.os.environ.get("GEMINI_API_KEY"), "outer-key")

        runtime_env = captured["env"]
        self.assertIsInstance(runtime_env, dict)
        self.assertEqual(runtime_env["LITELLM_MODEL"], "gemini/gemini-2.5-flash")
        self.assertEqual(runtime_env["LITELLM_FALLBACK_MODELS"], "deepseek/deepseek-chat")
        self.assertEqual(runtime_env["LLM_CHANNELS"], "gemini")
        self.assertEqual(runtime_env["LLM_GEMINI_PROTOCOL"], "gemini")
        self.assertEqual(runtime_env["LLM_GEMINI_API_KEYS"], "dsa-gemini-key")
        self.assertEqual(runtime_env["LLM_GEMINI_EXTRA_HEADERS"], '{"x-tenant": "dsa"}')
        self.assertEqual(runtime_env["GEMINI_API_KEY"], "dsa-gemini-key")
        self.assertEqual(runtime_env["LLM_CANDIDATE_CONTEXT_ENABLED"], "false")
        self.assertEqual(runtime_env["LLM_CANDIDATE_CONTEXT_PROVIDERS"], "news,fund_flow,announcement,quote")
        self.assertEqual(runtime_env["LLM_CANDIDATE_MULTIPLIER"], "2")
        self.assertEqual(runtime_env["LLM_MAX_CANDIDATES"], "10")
        self.assertEqual(runtime_env["DAILY_SOURCE"], "auto")
        self.assertEqual(runtime_env["SNAPSHOT_SOURCE_PRIORITY"], "sina,efinance,akshare_em,em_datacenter")
        self.assertEqual(runtime_env["ALPHASIFT_DATA_DIR"], str(alphasift_service.DSA_ALPHASIFT_DATA_DIR))
        self.assertEqual(
            runtime_env["ALPHASIFT_FALLBACK_SNAPSHOT_PATH"],
            str(alphasift_service.DSA_ALPHASIFT_DATA_DIR / "snapshot.last_good.json"),
        )
        self.assertEqual(
            runtime_env["ALPHASIFT_DAILY_HISTORY_CACHE_DIR"],
            str(alphasift_service.DSA_ALPHASIFT_DATA_DIR / "daily_history"),
        )
        self.assertEqual(
            runtime_env["ALPHASIFT_INDUSTRY_PROVIDER_CACHE_DIR"],
            str(alphasift_service.DSA_ALPHASIFT_DATA_DIR / "industry_provider_cache"),
        )
        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["model"], "gemini/gemini-2.5-flash")
        self.assertFalse(context["llm"]["candidate_context_enabled"])
        self.assertEqual(context["llm"]["candidate_multiplier"], 2)
        self.assertEqual(context["llm"]["max_candidates"], 10)
        self.assertEqual(context["llm"]["channels"][0]["api_keys"], ["dsa-gemini-key"])
        self.assertEqual(context["llm"]["channels"][0]["extra_headers"], {"x-tenant": "dsa"})
        self.assertEqual(context["llm"]["model_list"][0]["litellm_params"]["extra_headers"], {"x-tenant": "dsa"})
        self.assertIn("get_candidate_context", context["dsa"])
        self.assertEqual(context["dsa"]["mode"], "pre_rank_light")
        self.assertEqual(context["dsa"]["max_candidates"], 3)
        self.assertFalse(context["dsa"]["include_news"])
        self.assertNotIn("search_stock_news", context["dsa"])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_injects_dsa_channel_headers_into_alphasift_litellm_calls(self) -> None:
        config = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="gemini/gemini-2.5-flash",
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "api_keys": ["dsa-gemini-key"],
                    "models": ["gemini/gemini-2.5-flash"],
                    "extra_headers": {"x-tenant": "dsa"},
                }
            ],
        )
        completion_calls: list[dict[str, object]] = []

        def completion_impl(**kwargs):
            completion_calls.append(kwargs)
            return SimpleNamespace(choices=[])

        fake_litellm = SimpleNamespace(completion=completion_impl)

        def screen_impl(_strategy: str, **_kwargs):
            fake_litellm.completion(
                model="gemini/gemini-2.5-flash",
                api_key="dsa-gemini-key",
                messages=[{"role": "user", "content": "rank"}],
            )
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(completion_calls[0]["extra_headers"], {"x-tenant": "dsa"})
        self.assertIsNot(fake_litellm.completion, completion_impl)
        self.assertTrue(
            getattr(fake_litellm.completion, "_alphasift_litellm_completion_bridge", False),
        )

    def test_screen_bridges_legacy_openai_fields_into_alphasift_runtime_env(self) -> None:
        config = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="openai/gpt-4o-mini",
            openai_api_keys=["dsa-openai-key"],
            openai_base_url="https://openai-compatible.example/v1",
        )
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **kwargs):
            captured["env"] = {
                "OPENAI_API_KEY": alphasift_service.os.environ.get("OPENAI_API_KEY"),
                "OPENAI_API_KEYS": alphasift_service.os.environ.get("OPENAI_API_KEYS"),
                "OPENAI_BASE_URL": alphasift_service.os.environ.get("OPENAI_BASE_URL"),
                "LITELLM_MODEL": alphasift_service.os.environ.get("LITELLM_MODEL"),
            }
            captured["context"] = kwargs.get("context")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(
                alphasift_service.os.environ,
                {
                    "OPENAI_API_KEY": "outer-openai-key",
                    "OPENAI_BASE_URL": "https://outer-openai.example/v1",
                },
                clear=False,
            ),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)
            self.assertEqual(alphasift_service.os.environ.get("OPENAI_API_KEY"), "outer-openai-key")
            self.assertEqual(alphasift_service.os.environ.get("OPENAI_BASE_URL"), "https://outer-openai.example/v1")

        runtime_env = captured["env"]
        self.assertIsInstance(runtime_env, dict)
        self.assertEqual(runtime_env["OPENAI_API_KEY"], "dsa-openai-key")
        self.assertEqual(runtime_env["OPENAI_API_KEYS"], "dsa-openai-key")
        self.assertEqual(runtime_env["OPENAI_BASE_URL"], "https://openai-compatible.example/v1")
        self.assertEqual(runtime_env["LITELLM_MODEL"], "openai/gpt-4o-mini")

        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["channels"], [])
        self.assertEqual(context["llm"]["model_list"], [])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_injects_openai_compatible_model_headers_into_alphasift_litellm_calls(self) -> None:
        config = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=["openai/gpt-4o-mini"],
            llm_model_list=[
                {
                    "model_name": "openai/gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "dsa-openai-key",
                        "api_base": "https://openai-compatible.example/v1",
                        "extra_headers": {"x-tenant": "dsa"},
                    },
                },
            ],
        )
        completion_calls: list[dict[str, object]] = []

        def completion_impl(**kwargs):
            completion_calls.append(kwargs)
            return SimpleNamespace(choices=[])

        fake_litellm = SimpleNamespace(completion=completion_impl)

        def screen_impl(_strategy: str, **_kwargs):
            fake_litellm.completion(
                model="openai/gpt-4o-mini",
                api_key="dsa-openai-key",
                api_base="https://openai-compatible.example/v1",
                messages=[{"role": "user", "content": "rank"}],
            )
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(completion_calls[0]["extra_headers"], {"x-tenant": "dsa"})
        self.assertEqual(
            completion_calls[0]["api_base"],
            "https://openai-compatible.example/v1",
        )
        self.assertIsNot(fake_litellm.completion, completion_impl)
        self.assertTrue(
            getattr(fake_litellm.completion, "_alphasift_litellm_completion_bridge", False),
        )

    def test_screen_bridges_openai_channel_base_url_and_headers(self) -> None:
        config = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=["openai/gpt-4.1"],
            llm_channels=[
                {
                    "name": "openai",
                    "protocol": "openai",
                    "enabled": True,
                    "base_url": "https://primary-openai.example/v1",
                    "api_keys": ["dsa-openai-primary"],
                    "models": ["openai/gpt-4o-mini", "openai/gpt-4.1"],
                    "extra_headers": {"x-route": "primary", "x-tenant": "dsa"},
                }
            ],
        )
        completion_calls: list[Dict[str, object]] = []

        def completion_impl(**kwargs: Any) -> Any:
            completion_calls.append(kwargs)
            return SimpleNamespace(choices=[])

        fake_litellm = SimpleNamespace(completion=completion_impl)

        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **kwargs: Dict[str, Any]) -> dict[str, object]:
            captured["env"] = {
                "OPENAI_BASE_URL": alphasift_service.os.environ.get("OPENAI_BASE_URL"),
                "OPENAI_API_KEY": alphasift_service.os.environ.get("OPENAI_API_KEY"),
                "OPENAI_API_KEYS": alphasift_service.os.environ.get("OPENAI_API_KEYS"),
                "LLM_CHANNELS": alphasift_service.os.environ.get("LLM_CHANNELS"),
                "LLM_OPENAI_BASE_URL": alphasift_service.os.environ.get("LLM_OPENAI_BASE_URL"),
                "LLM_OPENAI_API_KEYS": alphasift_service.os.environ.get("LLM_OPENAI_API_KEYS"),
            }
            captured["context"] = kwargs.get("context")
            fake_litellm.completion(
                model="openai/gpt-4o-mini",
                api_key="dsa-openai-primary",
                api_base="https://primary-openai.example/v1",
                messages=[{"role": "user", "content": "primary"}],
            )
            fake_litellm.completion(
                model="openai/gpt-4.1",
                api_key="dsa-openai-primary",
                api_base="https://primary-openai.example/v1",
                messages=[{"role": "user", "content": "fallback"}],
            )
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(len(completion_calls), 2)
        self.assertEqual(captured["env"]["OPENAI_BASE_URL"], "https://primary-openai.example/v1")
        self.assertEqual(captured["env"]["OPENAI_API_KEYS"], "dsa-openai-primary")
        self.assertEqual(captured["env"]["OPENAI_API_KEY"], "dsa-openai-primary")
        self.assertEqual(captured["env"]["LLM_CHANNELS"], "openai")
        self.assertEqual(captured["env"]["LLM_OPENAI_BASE_URL"], "https://primary-openai.example/v1")
        self.assertEqual(captured["env"]["LLM_OPENAI_API_KEYS"], "dsa-openai-primary")
        self.assertEqual(completion_calls[0]["extra_headers"], {"x-route": "primary", "x-tenant": "dsa"})
        self.assertEqual(completion_calls[1]["extra_headers"], {"x-route": "primary", "x-tenant": "dsa"})
        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["channels"][0]["base_url"], "https://primary-openai.example/v1")
        self.assertEqual(context["llm"]["channels"][0]["extra_headers"], {"x-route": "primary", "x-tenant": "dsa"})
        self.assertEqual(context["llm"]["model_list"][0]["litellm_params"]["api_base"], "https://primary-openai.example/v1")
        self.assertEqual(context["llm"]["fallback_models"], ["openai/gpt-4.1"])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_injects_openai_compatible_fallback_headers_for_multiple_models(self) -> None:
        config = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=["openai/gpt-4.1"],
            llm_model_list=[
                {
                    "model_name": "openai/gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "dsa-openai-primary",
                        "api_base": "https://primary.openai.example/v1",
                        "extra_headers": {"x-route": "primary", "x-tenant": "dsa"},
                    },
                },
                {
                    "model_name": "openai/gpt-4.1",
                    "litellm_params": {
                        "model": "openai/gpt-4.1",
                        "api_key": "dsa-openai-fallback",
                        "api_base": "https://fallback.openai.example/v1",
                        "extra_headers": {"x-route": "fallback", "x-tenant": "dsa"},
                    },
                },
            ],
        )
        completion_calls: list[Dict[str, object]] = []

        def completion_impl(**kwargs: Any) -> Any:
            completion_calls.append(kwargs)
            return SimpleNamespace(choices=[])

        fake_litellm = SimpleNamespace(completion=completion_impl)

        def screen_impl(_strategy: str, **_kwargs) -> dict[str, object]:
            fake_litellm.completion(
                model="openai/gpt-4o-mini",
                api_key="dsa-openai-primary",
                api_base="https://primary.openai.example/v1",
                messages=[{"role": "user", "content": "rank-1"}],
            )
            fake_litellm.completion(
                model="openai/gpt-4.1",
                api_key="dsa-openai-fallback",
                api_base="https://fallback.openai.example/v1",
                messages=[{"role": "user", "content": "rank-2"}],
            )
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(payload["candidate_count"], 0)
        primary_call = next(
            call for call in completion_calls if call["model"] == "openai/gpt-4o-mini"
        )
        fallback_call = next(
            call for call in completion_calls if call["model"] == "openai/gpt-4.1"
        )
        self.assertEqual(primary_call["extra_headers"], {"x-route": "primary", "x-tenant": "dsa"})
        self.assertEqual(
            fallback_call["extra_headers"],
            {"x-route": "fallback", "x-tenant": "dsa"},
        )
        self.assertEqual(primary_call["api_base"], "https://primary.openai.example/v1")
        self.assertEqual(fallback_call["api_base"], "https://fallback.openai.example/v1")
        self.assertTrue(getattr(fake_litellm.completion, "_alphasift_litellm_completion_bridge", False))

    def test_screen_handles_concurrent_requests_without_litellm_header_cross_pollution(self) -> None:
        config_a = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="gemini/gemini-2.5-flash",
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "api_keys": ["dsa-gemini-key-a"],
                    "models": ["gemini/gemini-2.5-flash"],
                    "extra_headers": {"x-tenant": "tenant-a"},
                }
            ],
        )
        config_b = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="gemini/gemini-2.5-flash",
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "api_keys": ["dsa-gemini-key-b"],
                    "models": ["gemini/gemini-2.5-flash"],
                    "extra_headers": {"x-tenant": "tenant-b"},
                }
            ],
        )

        completion_calls: list[Dict[str, Any]] = []
        thread_b_ready = threading.Event()
        completion_lock = threading.Lock()

        def completion_impl(**kwargs: Any) -> Any:
            with completion_lock:
                completion_calls.append(kwargs)
            return SimpleNamespace(choices=[])

        fake_litellm = SimpleNamespace(completion=completion_impl)

        def screen_impl(_strategy: str, **kwargs: Any) -> Dict[str, Any]:
            context = kwargs.get("context") or {}
            llm = context.get("llm", {})
            channels = llm.get("channels") or []
            headers = (channels[0] if channels else {}).get("extra_headers", {})
            tenant = headers.get("x-tenant")
            if tenant == "tenant-a":
                thread_b_ready.wait(timeout=2)
            else:
                thread_b_ready.set()
            fake_litellm.completion(
                model="gemini/gemini-2.5-flash",
                api_key=(channels[0].get("api_keys") or [""])[0],
                messages=[{"role": "user", "content": "rank"}],
            )
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        def _run_screen(config: Config) -> None:
            self._screen(config, market="cn", strategy="dual_low", max_results=5, mock_enrichment=False)

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            thread_a = threading.Thread(target=_run_screen, args=(config_a,))
            thread_b = threading.Thread(target=_run_screen, args=(config_b,))
            thread_a.start()
            thread_b.start()
            thread_a.join()
            thread_b.join()

        self.assertEqual(len(completion_calls), 2)
        self.assertCountEqual(
            [call.get("extra_headers", {}).get("x-tenant") for call in completion_calls],
            ["tenant-a", "tenant-b"],
        )
        self.assertTrue(
            thread_a.is_alive() is False and thread_b.is_alive() is False,
        )

    def test_screen_disabled_preserves_existing_llm_env_state(self) -> None:
        config = self._config(enabled=False)
        baseline_env = {
            "OPENAI_API_KEY": "legacy-openai-key",
            "OPENAI_BASE_URL": "https://outer.example.com/v1",
            "LITELLM_MODEL": "openai/gpt-4o-mini",
        }
        original_env = {key: alphasift_service.os.environ.get(key) for key in baseline_env}

        with (
            patch.dict(alphasift_service.os.environ, baseline_env, clear=False),
            patch("src.services.alphasift_service._build_alphasift_runtime_env") as runtime_env_mock,
            self.assertRaises(HTTPException) as caught,
        ):
            self._screen(config, market="cn", strategy="dual_low", max_results=5)
            for key, value in baseline_env.items():
                self.assertEqual(alphasift_service.os.environ.get(key), value)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "alphasift_disabled")
        runtime_env_mock.assert_not_called()
        for key, value in baseline_env.items():
            self.assertEqual(alphasift_service.os.environ.get(key), original_env[key])

    def test_screen_preserves_explicit_alphasift_snapshot_source_priority(self) -> None:
        config = self._config(enabled=True)
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["snapshot_priority"] = alphasift_service.os.environ.get("SNAPSHOT_SOURCE_PRIORITY")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(alphasift_service.os.environ, {"SNAPSHOT_SOURCE_PRIORITY": "tushare,em_datacenter"}, clear=False),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["snapshot_priority"], "tushare,em_datacenter")
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_preserves_explicit_daily_source(self) -> None:
        config = self._config(enabled=True)
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["daily_source"] = alphasift_service.os.environ.get("DAILY_SOURCE")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(alphasift_service.os.environ, {"DAILY_SOURCE": "akshare"}, clear=False),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["daily_source"], "akshare")
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_preserves_explicit_openai_base_url_without_openai_channel(self) -> None:
        config = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="deepseek/deepseek-chat",
            llm_channels=[
                {
                    "name": "deepseek",
                    "protocol": "deepseek",
                    "enabled": True,
                    "base_url": "https://api.deepseek.example/v1",
                    "api_keys": ["runtime-deepseek-key"],
                    "models": ["deepseek/deepseek-chat"],
                }
            ],
        )
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["openai_base_url"] = alphasift_service.os.environ.get("OPENAI_BASE_URL")
            captured["llm_openai_base_url"] = alphasift_service.os.environ.get("LLM_OPENAI_BASE_URL")
            captured["openai_api_key"] = alphasift_service.os.environ.get("OPENAI_API_KEY")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(
                alphasift_service.os.environ,
                {
                    "OPENAI_BASE_URL": "https://outer-openai.example/v1",
                    "LLM_OPENAI_BASE_URL": "https://outer-openai-channel.example/v1",
                    "OPENAI_API_KEY": "outer-openai-key",
                },
                clear=False,
            ),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["openai_base_url"], "https://outer-openai.example/v1")
        self.assertEqual(captured["llm_openai_base_url"], "https://outer-openai-channel.example/v1")
        self.assertEqual(captured["openai_api_key"], "outer-openai-key")
        self.assertEqual(payload["candidate_count"], 0)

    def test_alphasift_runtime_priority_puts_tushare_before_sina_when_token_exists(self) -> None:
        config = self._config(enabled=True)
        config.tushare_token = "token-1"

        with patch.dict(alphasift_service.os.environ, {"SNAPSHOT_SOURCE_PRIORITY": ""}, clear=False):
            env = alphasift_service._build_alphasift_runtime_env(config)

        self.assertEqual(env["SNAPSHOT_SOURCE_PRIORITY"], "tushare,sina,efinance,akshare_em,em_datacenter")

    def test_screen_preserves_explicit_candidate_context_provider_override(self) -> None:
        config = self._config(enabled=True)
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["providers"] = alphasift_service.os.environ.get("LLM_CANDIDATE_CONTEXT_PROVIDERS")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(alphasift_service.os.environ, {"LLM_CANDIDATE_CONTEXT_PROVIDERS": "news,announcement"}, clear=False),
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["providers"], "news,announcement")
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_filters_undeclared_managed_fallbacks_for_dsa_routes(self) -> None:
        config = Config(
            alphasift_enabled=True,
            alphasift_install_spec=DEFAULT_ALPHASIFT_TEST_SPEC,
            litellm_model="gemini/gemini-3-flash-preview",
            litellm_fallback_models=["gemini/gemini-2.5-flash"],
            llm_channels=[
                {
                    "name": "gemini",
                    "protocol": "gemini",
                    "enabled": True,
                    "base_url": "",
                    "api_keys": ["dsa-gemini-key"],
                    "models": ["gemini/gemini-3-flash-preview"],
                },
                {
                    "name": "deepseek",
                    "protocol": "deepseek",
                    "enabled": True,
                    "base_url": "https://api.deepseek.com",
                    "api_keys": ["dsa-deepseek-key"],
                    "models": ["deepseek/deepseek-chat"],
                },
            ],
            llm_model_list=[
                {
                    "model_name": "gemini/gemini-3-flash-preview",
                    "litellm_params": {
                        "model": "gemini/gemini-3-flash-preview",
                        "api_key": "dsa-gemini-key",
                    },
                },
                {
                    "model_name": "deepseek/deepseek-chat",
                    "litellm_params": {
                        "model": "deepseek/deepseek-chat",
                        "api_key": "dsa-deepseek-key",
                        "api_base": "https://api.deepseek.com",
                    },
                },
            ],
        )
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **kwargs):
            captured["env"] = {
                "LITELLM_MODEL": alphasift_service.os.environ.get("LITELLM_MODEL"),
                "LITELLM_FALLBACK_MODELS": alphasift_service.os.environ.get("LITELLM_FALLBACK_MODELS"),
                "LLM_CHANNELS": alphasift_service.os.environ.get("LLM_CHANNELS"),
            }
            captured["context"] = kwargs.get("context")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with patch("src.services.alphasift_service._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        runtime_env = captured["env"]
        self.assertIsInstance(runtime_env, dict)
        self.assertEqual(runtime_env["LITELLM_MODEL"], "gemini/gemini-3-flash-preview")
        self.assertEqual(runtime_env["LITELLM_FALLBACK_MODELS"], "deepseek/deepseek-chat")
        self.assertEqual(runtime_env["LLM_CHANNELS"], "gemini,deepseek")
        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["fallback_models"], ["deepseek/deepseek-chat"])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_retries_without_context_for_older_adapter_kwargs_wrappers(self) -> None:
        config = self._config(enabled=True)

        def screen_impl(_strategy: str, **kwargs):
            if "context" in kwargs:
                raise TypeError("unexpected keyword argument 'context'")
            return {"candidates": []}

        fake_module = _make_adapter_module(screen=MagicMock(side_effect=screen_impl))

        with patch("src.services.alphasift_service._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(fake_module.screen.call_count, 2)
        first_kwargs = fake_module.screen.call_args_list[0].kwargs
        second_kwargs = fake_module.screen.call_args_list[1].kwargs
        self.assertIn("context", first_kwargs)
        self.assertNotIn("context", second_kwargs)
        self.assertEqual(second_kwargs["market"], "cn")
        self.assertEqual(second_kwargs["max_results"], 5)
        self.assertEqual(second_kwargs["use_llm"], True)
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_does_not_install_when_enabled_but_adapter_missing(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(screen=MagicMock(return_value={"candidates": []}))

        with (
            patch(
                "src.services.alphasift_service._get_alphasift_status_snapshot",
                return_value=({}, False, _missing_alphasift_module_diagnostics()),
            ),
            patch("src.services.alphasift_service._install_alphasift") as install_mock,
            patch("src.services.alphasift_service._import_alphasift", return_value=fake_module),
        ):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail.get("diagnostics", {}).get("reason"), "missing_module")
        install_mock.assert_not_called()
        fake_module.screen.assert_not_called()

    def test_screen_normalizes_non_finite_values(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(
                return_value={
                    "picks": [
                        {
                            "code": "600519",
                            "name": "Kweichow Moutai",
                            "score": float("nan"),
                            "ranking_reason": "AlphaSift pick",
                            "nested": {"pe": float("inf"), "pb": float("-inf"), "eps": 20.5},
                        },
                    ],
                }
            ),
        )

        with patch("src.services.alphasift_service._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertIsNone(payload["candidates"][0]["score"])
        self.assertIsNone(payload["candidates"][0]["raw"]["score"])
        self.assertIsNone(payload["candidates"][0]["raw"]["nested"]["pe"])
        self.assertIsNone(payload["candidates"][0]["raw"]["nested"]["pb"])

    def test_screen_allows_non_listed_strategy_as_custom(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            list_strategies=lambda: [{"id": "dual_low", "name": "双低选股"}],
            screen=MagicMock(return_value={"candidates": []}),
        )

        with patch("src.services.alphasift_service._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="custom_alpha", max_results=5)

        fake_module.screen.assert_called_once_with(
            "custom_alpha",
            market="cn",
            max_results=5,
            use_llm=True,
            context=ANY,
        )
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_rejects_unsupported_market(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            get_status=lambda: {"supported_markets": ["hk", "us"]},
            screen=MagicMock(return_value=[]),
        )

        with patch("src.services.alphasift_service._import_alphasift", return_value=fake_module):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail["error"], "alphasift_invalid_market")

    def test_screen_maps_adapter_value_error_to_bad_request(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(side_effect=ValueError("Only market='cn' is currently supported")),
        )

        with patch("src.services.alphasift_service._import_alphasift", return_value=fake_module):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail["error"], "alphasift_screen_rejected")


if __name__ == "__main__":
    unittest.main()
