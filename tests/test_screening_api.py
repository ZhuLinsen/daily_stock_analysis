# -*- coding: utf-8 -*-
"""Tests for the built-in screening endpoints."""

from __future__ import annotations

import os
import json
import multiprocessing
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import ANY, MagicMock, patch
import threading

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pandas as pd

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from api.v1.endpoints import screening as screening_endpoint
from src.config import Config
from src.services import screening_service
from src.services.screening import REFERENCE_REVISION
from src.services.screening.config import Config as ScreeningPipelineConfig
from src.services.task_queue import TaskInfo, TaskStatus as QueueTaskStatus


def _screening_unavailable() -> HTTPException:
    return HTTPException(
        status_code=424,
        detail={"error": "screening_unavailable", "message": "Screening is unavailable"},
    )


def _raise_screening_unavailable() -> None:
    raise _screening_unavailable()


def _sleeping_constituent_source(*, symbol: str) -> pd.DataFrame:
    del symbol
    time.sleep(5)
    return pd.DataFrame()


def _make_screening_core(
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


@contextmanager
def _patch_screening_core(core: SimpleNamespace):
    """Replace native screening entry points without recreating an adapter layer."""
    with (
        patch("src.services.screening_service.run_screening_pipeline", new=core.screen),
        patch("src.services.screening_service.load_screening_strategies", new=core.list_strategies),
        patch("src.services.screening_service._call_screening_status", new=core.get_status),
    ):
        yield core


def _screening_unavailable_diagnostics() -> Dict[str, str]:
    return {
        "reason": "unexpected_exception",
        "stage": "get_status",
        "error_type": "RuntimeError",
    }


class ScreeningOpportunitiesApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        Config.reset_instance()
        self.env_patch = patch.dict(os.environ, {"SCREENING_DATA_DIR": ""}, clear=False)
        self.env_patch.start()

    def tearDown(self) -> None:
        self.env_patch.stop()
        Config.reset_instance()

    def _config(self, *, enabled: bool) -> Config:
        return Config(screening_enabled=enabled)

    @staticmethod
    def _request(cookies=None) -> SimpleNamespace:
        return SimpleNamespace(cookies=cookies or {})

    def _screen(self, config: Config, *, mock_enrichment: bool = True, **kwargs):
        if not mock_enrichment:
            return screening_endpoint.screening_screen(
                screening_endpoint.ScreeningScreenRequest(**kwargs),
                http_request=self._request(),
                config=config,
            )
        with patch(
            "src.services.screening_service._enrich_candidates_with_dsa",
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
            return screening_endpoint.screening_screen(
                screening_endpoint.ScreeningScreenRequest(**kwargs),
                http_request=self._request(),
                config=config,
            )

    def _strategies(self, config: Config):
        return screening_endpoint.screening_strategies(request=self._request(), config=config)

    def _hotspots(self, config: Config, **kwargs):
        return screening_endpoint.screening_hotspots(config=config, **kwargs)

    def _hotspot_detail(self, config: Config, **kwargs):
        if os.environ.get("SCREENING_DATA_DIR"):
            return screening_endpoint.screening_hotspot_detail(config=config, **kwargs)
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"SCREENING_DATA_DIR": str(Path(tmpdir) / "screening")}, clear=False):
                return screening_endpoint.screening_hotspot_detail(config=config, **kwargs)

    def test_builtin_screening_core_loads_bundled_strategies(self) -> None:
        status = screening_service._call_screening_status()
        strategies = screening_service._list_strategies()

        self.assertTrue(status["available"])
        self.assertEqual(status["engine"], "builtin")
        self.assertEqual(status["reference_revision"], REFERENCE_REVISION)
        self.assertEqual(status["strategy_count"], len(strategies))
        self.assertIn("dual_low", {item["id"] for item in strategies})

    def test_status_exposes_builtin_engine_provenance(self) -> None:
        payload = screening_endpoint.screening_status(config=self._config(enabled=True))

        self.assertTrue(payload["available"])
        self.assertEqual(payload["engine"], "builtin")
        self.assertEqual(payload["reference_revision"], REFERENCE_REVISION)


    def test_status_defaults_to_disabled(self) -> None:
        config = self._config(enabled=False)

        with patch("src.services.screening_service._call_screening_status", side_effect=_raise_screening_unavailable):
            payload = screening_endpoint.screening_status(config=config)

        self.assertEqual(payload["enabled"], False)
        self.assertEqual(payload["available"], False)
        self.assertEqual(payload["engine"], "builtin")
        self.assertNotIn("diagnostics", payload)


    def test_status_includes_engine_contract_metadata(self) -> None:
        config = self._config(enabled=True)

        with patch(
            "src.services.screening_service._call_screening_status",
            return_value={"available": True, "contract_version": "1", "version": "0.2.0", "strategy_count": 8},
        ):
            payload = screening_endpoint.screening_status(config=config)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["contract_version"], "1")
        self.assertEqual(payload["version"], "0.2.0")
        self.assertEqual(payload["strategy_count"], 8)

    def test_status_includes_screening_source_health_snapshot(self) -> None:
        config = self._config(enabled=True)

        with (
            patch(
                "src.services.screening_service._call_screening_status",
                return_value={"available": True, "contract_version": "1", "version": "0.2.0", "strategy_count": 8},
            ),
            patch(
                "src.services.screening_service._get_screening_source_health_snapshot",
                return_value={"snapshot": {"sina": {"failures": 2, "disabled": False}}},
            ),
        ):
            payload = screening_endpoint.screening_status(config=config)

        self.assertEqual(payload["source_health"]["snapshot"]["sina"]["failures"], 2)

    def test_status_preserves_engine_available_false_without_diagnostics(self) -> None:
        config = self._config(enabled=False)

        with patch(
            "src.services.screening_service._call_screening_status",
            return_value={"available": False, "contract_version": "1", "version": "0.2.0", "strategy_count": 0},
        ):
            payload = screening_endpoint.screening_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["contract_version"], "1")
        self.assertNotIn("diagnostics", payload)

    def test_status_logs_and_reports_strategy_load_diagnostics(self) -> None:
        config = self._config(enabled=False)

        with (
            patch(
                "src.services.screening_service.load_screening_strategies",
                side_effect=RuntimeError("strategy load failed"),
            ),
            self.assertLogs("src.services.screening_service", level="WARNING") as captured,
        ):
            payload = screening_endpoint.screening_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "strategy_load")
        self.assertEqual(payload["diagnostics"]["error_type"], "RuntimeError")
        self.assertIn("Unexpected Screening strategy_load failure", "\n".join(captured.output))

    def test_strategies_returns_native_strategy_metadata(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            list_strategies=lambda: [
                {"id": "dual_low", "name": "双低选股", "description": "value", "category": "价值"},
                {"id": "trend_quality", "title": "趋势质量", "description": "trend", "tag": "框架"},
            ],
        )

        with _patch_screening_core(fake_module):
            payload = self._strategies(config=config)

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["strategy_count"], 2)
        self.assertEqual(payload["strategies"][0]["id"], "dual_low")
        self.assertEqual(payload["strategies"][0]["name"], "双低选股")
        self.assertEqual(payload["strategies"][1]["name"], "趋势质量")

    def test_hotspots_returns_screening_hotspot_summaries(self) -> None:
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

        class FakeProvider(screening_service.DsaEastMoneyHotspotProvider):
            def hotspot_rows(self, *, top: int = 12) -> List[Dict[str, Any]]:
                return list(rows)[:top]

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "hotspots.json"
            provider = FakeProvider()
            with (
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace(discover_hotspots=discover)),
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
        self.assertEqual(discover.call_args.kwargs["top"], 3)

    def test_hotspots_default_provider_uses_dsa_eastmoney_provider(self) -> None:
        provider_name, provider = screening_service._resolve_hotspot_provider("")

        self.assertEqual(provider_name, "akshare")
        self.assertIsInstance(provider, screening_service.DsaEastMoneyHotspotProvider)

    def test_hotspots_refresh_uses_dsa_direct_rows_when_screening_rows_are_thin(self) -> None:
        config = self._config(enabled=True)

        class ThinRows(list):
            provider_used = "akshare"
            fallback_used = False
            source_errors = []
            stale = False
            stale_age_hours = None

        class FakeProvider(screening_service.DsaEastMoneyHotspotProvider):
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
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace(discover_hotspots=discover)),
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

        class FakeProvider(screening_service.DsaEastMoneyHotspotProvider):
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
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", FakeProvider())),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace(discover_hotspots=discover)),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=1, refresh=True)

        hotspot = payload["hotspots"][0]
        self.assertEqual(hotspot["name"], "工业金属 · 铜")
        self.assertEqual(hotspot["trend_score"], 99.0)
        self.assertEqual(hotspot["persistence_score"], 64.3)
        self.assertEqual(hotspot["sample_stock_count"], 11)
        self.assertEqual(hotspot["leaders"], ["嘉元科技", "方邦股份"])

    def test_hotspots_default_cache_miss_does_not_fetch_live_data(self) -> None:
        config = self._config(enabled=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing-hotspots.json"
            discover_hotspots = MagicMock(side_effect=AssertionError("default cache read must not fetch live data"))
            with (
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch(
                    "src.services.screening_service.screening_hotspot",
                    new=SimpleNamespace(discover_hotspots=discover_hotspots),
                ),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=6, refresh=False)

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["provider"], "akshare")
        self.assertEqual(payload["cache_used"], False)
        self.assertEqual(payload["hotspots"], [])
        self.assertEqual(payload["hotspot_count"], 0)
        self.assertEqual(payload["source_errors"], [])
        discover_hotspots.assert_not_called()

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
            discover_hotspots = MagicMock(side_effect=AssertionError("default cache read must not fetch live data"))
            with (
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch(
                    "src.services.screening_service.screening_hotspot",
                    new=SimpleNamespace(discover_hotspots=discover_hotspots),
                ),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=12, refresh=False)

        self.assertEqual(payload["hotspots"], [])
        self.assertEqual(payload["hotspot_count"], 0)
        discover_hotspots.assert_not_called()


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
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace(discover_hotspots=discover)),
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
            provider = screening_service.DsaEastMoneyHotspotProvider()
            provider.hotspot_rows = MagicMock(return_value=[])
            with (
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace(discover_hotspots=discover)),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=1, refresh=True)

        self.assertEqual(payload["cache_used"], True)
        self.assertEqual(payload["fallback_used"], True)
        self.assertEqual(payload["hotspot_count"], 1)
        self.assertEqual(payload["hotspots"][0]["topic"], "MLCC")
        self.assertIn("akshare returned no usable board rows", payload["source_errors"])
        discover.assert_called_once()

    def test_hotspots_refresh_applies_source_timeout_and_falls_back_to_last_good_cache(self) -> None:
        config = self._config(enabled=True)

        class HangingProvider:
            def stock_board_concept_name_em(self) -> pd.DataFrame:
                time.sleep(0.1)
                return pd.DataFrame([{"板块名称": "Should not arrive", "涨跌幅": 9.9}])

            def stock_board_industry_name_em(self) -> pd.DataFrame:
                time.sleep(0.1)
                return pd.DataFrame([{"行业名称": "Should not arrive", "涨跌幅": 8.8}])

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "screening"
            data_dir.mkdir(parents=True, exist_ok=True)
            cache_path = data_dir / "hotspots.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "generated_at": "2026-06-13T02:55:00Z",
                        "hotspots": [
                            {"topic": "Cache AI", "name": "Cache AI", "heat_score": 93.0},
                            {"topic": "Cache Chip", "name": "Cache Chip", "heat_score": 88.0},
                            {"topic": "Cache Copper", "name": "Cache Copper", "heat_score": 81.0},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with (
                patch.dict(
                    os.environ,
                    {
                        "SCREENING_DATA_DIR": str(data_dir),
                        "SCREENING_SOURCE_CALL_TIMEOUT_SEC": "0.01",
                    },
                    clear=False,
                ),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", HangingProvider())),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=1, refresh=True)

        self.assertEqual(payload["hotspot_count"], 1)
        self.assertEqual(payload["hotspots"][0]["topic"], "Cache AI")
        self.assertEqual(payload["provider_used"], "last_good_cache")
        self.assertTrue(payload["fallback_used"])
        self.assertTrue(payload["stale"])
        self.assertTrue(any("timed out after" in error for error in payload["source_errors"]))

    def test_hotspots_refresh_failure_without_cache_returns_friendly_empty_payload(self) -> None:
        config = self._config(enabled=True)
        discover = MagicMock(side_effect=RuntimeError("RemoteDisconnected('Remote end closed connection without response')"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing-hotspots.json"
            provider = screening_service.DsaEastMoneyHotspotProvider()
            with (
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace(discover_hotspots=discover)),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=1, refresh=True)

        self.assertEqual(payload["hotspots"], [])
        self.assertEqual(payload["hotspot_count"], 0)
        self.assertEqual(payload["source_errors"], ["eastmoney_hotspot_unavailable"])
        self.assertEqual(payload["message"], "热点源连接中断，暂无可用缓存。")
        self.assertNotIn("RemoteDisconnected", payload["message"])
        discover.assert_called_once()

    def test_hotspots_default_refresh_degraded_eastmoney_failure_without_cache_returns_friendly_empty_payload(self) -> None:
        config = self._config(enabled=True)

        class HotspotRows(list):
            provider_used = "DsaEastMoneyHotspotProvider"
            fallback_used = False
            source_errors = ["RemoteDisconnected('Remote end closed connection without response')"]
            stale = False
            stale_age_hours = None

        discover = MagicMock(return_value=HotspotRows())

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing-hotspots.json"
            app = FastAPI()
            app.include_router(screening_endpoint.router, prefix="/api/v1/screening")
            app.dependency_overrides[screening_endpoint.get_config_dep] = lambda: config
            with (
                patch.dict(os.environ, {"INDUSTRY_PROVIDER": ""}, clear=False),
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service.DsaEastMoneyHotspotProvider.hotspot_rows", return_value=[]),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace(discover_hotspots=discover)),
            ):
                response = TestClient(app).get("/api/v1/screening/hotspots?refresh=true&top=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["provider"], "akshare")
        self.assertEqual(payload["provider_used"], "DsaEastMoneyHotspotProvider")
        self.assertEqual(payload["hotspots"], [])
        self.assertEqual(payload["hotspot_count"], 0)
        self.assertEqual(payload["source_errors"], ["eastmoney_hotspot_unavailable"])
        self.assertEqual(payload["message"], "热点源连接中断，暂无可用缓存。")
        self.assertNotIn("RemoteDisconnected", payload["message"])
        discover.assert_called_once()

    def test_hotspots_refresh_runtime_failure_without_cache_raises_integration_error(self) -> None:
        config = self._config(enabled=True)
        discover = MagicMock(side_effect=RuntimeError("screening engine returned invalid payload"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing-hotspots.json"
            provider = screening_service.DsaEastMoneyHotspotProvider()
            with (
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace(discover_hotspots=discover)),
            ):
                with self.assertRaises(HTTPException) as caught:
                    self._hotspots(config=config, provider="akshare", top=1, refresh=True)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "screening_hotspot_refresh_failed")
        self.assertIn("screening engine returned invalid payload", caught.exception.detail["message"])
        discover.assert_called_once()

    def test_hotspots_refresh_non_akshare_failure_without_cache_raises_integration_error(self) -> None:
        config = self._config(enabled=True)
        discover = MagicMock(side_effect=RuntimeError("RemoteDisconnected('remote provider failed')"))

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "missing-hotspots.json"
            with (
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("custom", "custom")),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace(discover_hotspots=discover)),
            ):
                with self.assertRaises(HTTPException) as caught:
                    self._hotspots(config=config, provider="custom", top=1, refresh=True)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "screening_hotspot_refresh_failed")
        self.assertIn("RemoteDisconnected", caught.exception.detail["message"])
        discover.assert_called_once()

    def test_hotspot_provider_retries_transient_eastmoney_failure(self) -> None:
        import requests

        provider = screening_service.DsaEastMoneyHotspotProvider()

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
            patch("src.services.screening_service.time.sleep") as sleep_mock,
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

    def test_hotspots_respects_custom_screening_data_dir_for_cache_paths(self) -> None:
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
            data_dir = Path(tmpdir) / "persistent-screening"
            cache_path = data_dir / "hotspots.json"
            history_path = data_dir / "hotspot.history.jsonl"
            with (
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(data_dir)}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch(
                    "src.services.screening_service.screening_hotspot",
                    new=SimpleNamespace(discover_hotspots=discover),
                ),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=3, refresh=True)

            self.assertEqual(payload["hotspots"][0]["topic"], "机器人执行器")
            self.assertEqual(captured["history_path"], history_path)
            self.assertEqual(captured["fallback_cache_path"], cache_path)
            self.assertTrue(cache_path.exists())

            discover_again = MagicMock()
            with (
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(data_dir)}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch(
                    "src.services.screening_service.screening_hotspot",
                    new=SimpleNamespace(discover_hotspots=discover_again),
                ),
            ):
                cached = self._hotspots(config=config, provider="akshare", top=1, refresh=False)

            cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertEqual(cached["cache_used"], True)
        self.assertEqual(cached["hotspots"][0]["topic"], "机器人执行器")
        discover_again.assert_not_called()
        self.assertEqual(cache_payload["schema_version"], 2)
        self.assertEqual(cache_payload["hotspots"][0]["topic"], "机器人执行器")

    def test_hotspots_reads_screening_v2_hotspot_cache(self) -> None:
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
                patch("src.services.screening_service.DSA_SCREENING_HOTSPOT_CACHE_PATH", cache_path),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace(discover_hotspots=discover)),
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
            data_dir = Path(tmpdir) / "screening"
            with (
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(data_dir)}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", "akshare")),
                patch(
                    "src.services.screening_service.screening_hotspot",
                    new=SimpleNamespace(discover_hotspots=MagicMock(return_value=rows)),
                ),
                patch.object(screening_service.ScreeningService, "hotspot_detail", side_effect=detail_side_effect) as detail_mock,
            ):
                payload = self._hotspots(config=config, provider="akshare", top=2, refresh=True, include_details=True)

            cache_payload = json.loads((data_dir / "hotspots.json").read_text(encoding="utf-8"))

        self.assertEqual(set(payload["details"].keys()), {"Moly", "Copper"})
        self.assertEqual(payload["details"]["Moly"]["route"][0]["title"], "Moly event")
        self.assertEqual(cache_payload["payload"]["details"]["Copper"]["summary"], "Copper summary")
        self.assertEqual(detail_mock.call_count, 2)

    def test_hotspot_refresh_can_run_while_screening_pipeline_is_busy(self) -> None:
        config = self._config(enabled=True)
        pipeline_started = threading.Event()
        release_pipeline = threading.Event()
        errors: list[BaseException] = []

        def screen_impl(_strategy: str, **_kwargs: Any) -> Dict[str, Any]:
            pipeline_started.set()
            release_pipeline.wait(timeout=2)
            return {"candidates": []}

        def run_screen() -> None:
            try:
                screening_service._call_screening_screen(
                    "dual_low",
                    "cn",
                    5,
                    config,
                )
            except BaseException as exc:  # noqa: BLE001 - surfaced in the test thread.
                errors.append(exc)

        rows = [{"topic": "AI", "heat_score": 90.0, "change_pct": 3.0}]
        fake_core = _make_screening_core(screen=MagicMock(side_effect=screen_impl))
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(Path(tmpdir) / "screening")}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", "akshare")),
                patch(
                    "src.services.screening_service.screening_hotspot",
                    new=SimpleNamespace(discover_hotspots=MagicMock(return_value=rows)),
                ),
                _patch_screening_core(fake_core),
            ):
                worker = threading.Thread(target=run_screen)
                worker.start()
                self.assertTrue(pipeline_started.wait(timeout=1))
                try:
                    payload = screening_service.ScreeningService(config=config).hotspots(
                        provider="akshare",
                        top=1,
                        refresh=True,
                    )
                finally:
                    release_pipeline.set()
                    worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(payload["hotspots"][0]["topic"], "AI")

    def test_screening_can_start_while_hotspot_refresh_is_busy(self) -> None:
        config = self._config(enabled=True)
        hotspot_started = threading.Event()
        release_hotspot = threading.Event()
        pipeline_started = threading.Event()
        errors: list[BaseException] = []

        def discover_hotspots(**_kwargs: Any) -> list[Dict[str, Any]]:
            hotspot_started.set()
            release_hotspot.wait(timeout=2)
            return [{"topic": "AI", "heat_score": 90.0, "change_pct": 3.0}]

        def screen_impl(_strategy: str, **_kwargs: Any) -> Dict[str, Any]:
            pipeline_started.set()
            return {"candidates": []}

        def run_hotspot_refresh() -> None:
            try:
                screening_service.ScreeningService(config=config).hotspots(
                    provider="akshare",
                    top=1,
                    refresh=True,
                )
            except BaseException as exc:  # noqa: BLE001 - surfaced in the test thread.
                errors.append(exc)

        fake_core = _make_screening_core(screen=MagicMock(side_effect=screen_impl))
        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(Path(tmpdir) / "screening")}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", "akshare")),
                patch(
                    "src.services.screening_service.screening_hotspot",
                    new=SimpleNamespace(discover_hotspots=discover_hotspots),
                ),
                _patch_screening_core(fake_core),
            ):
                worker = threading.Thread(target=run_hotspot_refresh)
                worker.start()
                self.assertTrue(hotspot_started.wait(timeout=1))
                try:
                    screening_service._call_screening_screen(
                        "dual_low",
                        "cn",
                        5,
                        config,
                    )
                    self.assertTrue(pipeline_started.wait(timeout=0.5))
                finally:
                    release_hotspot.set()
                    worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

    def test_hotspots_refresh_does_not_replace_richer_cache_with_narrower_request(self) -> None:
        config = self._config(enabled=True)

        class HotspotRows(list):
            provider_used = "akshare"
            fallback_used = False
            source_errors = []
            stale = False
            stale_age_hours = None

        rows = HotspotRows([
            {"topic": "Battery", "heat_score": 98.0, "change_pct": 8.0},
        ])
        discover_hotspots = MagicMock(return_value=rows)

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "screening"
            data_dir.mkdir(parents=True, exist_ok=True)
            cache_path = data_dir / "hotspots.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "generated_at": "2026-06-13T02:55:00Z",
                        "cached_at": "2026-06-13T02:55:00Z",
                        "metadata": {
                            "schema_version": 2,
                            "asset_type": "hotspot_cache",
                            "provider": "akshare",
                            "provider_used": "akshare",
                            "row_count": 4,
                            "source_errors": [],
                        },
                        "hotspots": [
                            {"topic": "AI"},
                            {"topic": "Robotics"},
                            {"topic": "Copper"},
                            {"topic": "Chip"},
                        ],
                        "payload": {
                            "enabled": True,
                            "provider": "akshare",
                            "provider_used": "akshare",
                            "fallback_used": False,
                            "cache_used": False,
                            "cached_at": "2026-06-13T02:55:00Z",
                            "schema_version": 2,
                            "source_errors": [],
                            "stale": False,
                            "stale_age_hours": None,
                            "hotspots": [
                                {"topic": "AI"},
                                {"topic": "Robotics"},
                                {"topic": "Copper"},
                                {"topic": "Chip"},
                            ],
                            "hotspot_count": 4,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(data_dir)}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", "akshare")),
                patch(
                    "src.services.screening_service.screening_hotspot",
                    new=SimpleNamespace(discover_hotspots=discover_hotspots),
                ),
            ):
                payload = self._hotspots(config=config, provider="akshare", top=1, refresh=True)

            cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))

        discover_hotspots.assert_called_once_with(
            provider="akshare",
            top=3,
            history_path=Path(data_dir) / "hotspot.history.jsonl",
            fallback_cache_path=cache_path,
        )
        self.assertEqual(payload["hotspot_count"], 1)
        self.assertEqual(payload["hotspots"][0]["topic"], "Battery")
        self.assertEqual(len(cache_payload["payload"]["hotspots"]), 4)
        self.assertEqual(cache_payload["payload"]["hotspots"][0]["topic"], "Battery")
        self.assertIn("Battery", [item["topic"] for item in cache_payload["payload"]["hotspots"]])
        self.assertIn("Copper", [item["topic"] for item in cache_payload["payload"]["hotspots"]])

    def test_hotspot_news_local_summary_extracts_event_instead_of_truncating(self) -> None:
        text = (
            "【股商异动】钼板块异动大涨5.64%！金钼股份涨停，机构看好行业机遇。"
            "消息称以钼代钨带动小金属行情，市场关注材料替代和供需偏紧。"
            "截至10:30，相关个股现价和成交额继续变化，后续建议关注供需平衡。"
        )

        summary = screening_service._summarize_hotspot_news_event_locally(topic="钼", text=text)

        self.assertIn("以钼代钨", summary)
        self.assertIn("小金属", summary)
        self.assertNotIn("截至", summary)
        self.assertNotIn("后续建议", summary)
        self.assertLessEqual(len(summary), screening_service.DSA_SCREENING_HOTSPOT_EVENT_SUMMARY_MAX_CHARS)

    def test_hotspot_detail_uses_screening_engine_detail_cache(self) -> None:
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
            data_dir = Path(tmpdir) / "screening"
            provider = screening_service.DsaEastMoneyHotspotProvider()
            with (
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(data_dir)}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch(
                    "src.services.screening_service.screening_hotspot",
                    new=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
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

    def test_hotspot_detail_backfills_stocks_from_engine_leader_stocks(self) -> None:
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

        provider = screening_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(side_effect=AssertionError("provider route fallback should not be used"))
        with (
            patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
            patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
            patch(
                "src.services.screening_service.screening_hotspot",
                new=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
            ),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="AI算力")

        self.assertEqual(payload["stocks"][0]["name"], "算力龙头")
        self.assertEqual(payload["leader_stocks"][0]["name"], "算力龙头")
        self.assertEqual(payload["stock_count"], 1)
        provider.hotspot_detail.assert_not_called()

    def test_hotspot_detail_compat_backfills_from_summary_detail_leader_stocks(self) -> None:
        payload = screening_service._ensure_hotspot_detail_compat_fields({
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

        provider = screening_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(side_effect=AssertionError("provider route fallback should not be used"))
        with (
            patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
            patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
            patch(
                "src.services.screening_service.screening_hotspot",
                new=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
            ),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="AI算力")

        self.assertEqual(payload["stocks"][0]["name"], "嵌套龙头")
        self.assertEqual(payload["leader_stocks"][0]["name"], "嵌套龙头")
        self.assertEqual(payload["stock_count"], 1)
        provider.hotspot_detail.assert_not_called()

    def test_hotspot_detail_uses_dsa_detail_cache_after_first_fetch(self) -> None:
        config = self._config(enabled=True)
        provider = screening_service.DsaEastMoneyHotspotProvider()
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
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(Path(tmpdir) / "screening")}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace()),
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
        provider = screening_service.DsaEastMoneyHotspotProvider()
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
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(Path(tmpdir) / "screening")}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace()),
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
        config = Config(screening_enabled=True, bocha_api_keys=["test-key"])
        provider = screening_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(return_value={
            "topic": "钼",
            "summary": "钼 当前涨跌幅 10.00%。",
            "route": [{"title": "当日发酵", "description": "钼板块异动。", "source": "eastmoney_board_change"}],
            "timeline": [{"title": "原始时间线", "description": "原始详情证据。", "source": "raw_timeline"}],
            "stocks": [],
            "stock_count": 0,
            "source_errors": [],
        })
        search_service = MagicMock()
        search_service.search_topic_news_bounded.return_value = SimpleNamespace(
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
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(Path(tmpdir) / "screening")}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace()),
                patch("src.services.screening_service._get_dsa_search_service", return_value=search_service),
            ):
                payload = self._hotspot_detail(
                    config=config,
                    provider="akshare",
                    topic="钼",
                    include_search=True,
                )

        self.assertEqual(payload["route"][0]["source"], "ExampleNews")
        self.assertEqual(payload["route"][0]["title"], "以钼代钨带动小金属行情")
        self.assertEqual(payload["route"][0]["date"], "2026-06-12")
        self.assertEqual(payload["route"][0]["url"], "https://example.com/news")
        self.assertEqual(payload["timeline"][0]["source"], "ExampleNews")
        self.assertEqual(payload["timeline"][1]["source"], "raw_timeline")
        self.assertEqual(payload["timeline"][1]["title"], "原始时间线")
        self.assertEqual(payload["news_search_status"], "available")
        self.assertLessEqual(len(payload["route"][0]["description"]), 93)
        self.assertNotIn("完整产业链背景", payload["route"][0]["description"])
        search_service.search_topic_news_bounded.assert_called_once_with(
            "钼",
            max_results=3,
            focus_keywords=['"钼"', "A股", "最新消息", "催化"],
            timeout_seconds=12.0,
        )

    def test_hotspot_search_keeps_hard_deadline_when_caller_timeout_is_disabled(self) -> None:
        search_service = MagicMock(is_available=True)
        search_service.search_topic_news_bounded.return_value = SimpleNamespace(
            success=False,
            results=[],
        )

        with (
            patch.dict(os.environ, {"SCREENING_HOTSPOT_SEARCH_TIMEOUT_SEC": "off"}, clear=False),
            patch("src.services.screening_service._get_dsa_search_service", return_value=search_service),
        ):
            result = screening_service._build_hotspot_event_routes_from_search("钼")

        self.assertEqual(result.routes, [])
        self.assertEqual(result.status, "unavailable")
        search_service.search_topic_news_bounded.assert_called_once_with(
            "钼",
            max_results=3,
            focus_keywords=['"钼"', "A股", "最新消息", "催化"],
            timeout_seconds=12.0,
        )

    def test_hotspot_search_excludes_missing_and_unsafe_links(self) -> None:
        config = Config(screening_enabled=True, bocha_api_keys=["test-key"])
        provider = screening_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(return_value={
            "topic": "钼",
            "summary": "钼 当前涨跌幅 10.00%。",
            "route": [{"title": "当日发酵", "description": "钼板块异动。", "source": "eastmoney_board_change"}],
            "stocks": [],
            "stock_count": 0,
            "source_errors": [],
        })
        search_service = MagicMock()
        search_service.search_topic_news_bounded.return_value = SimpleNamespace(
            success=True,
            provider="Bocha",
            results=[
                SimpleNamespace(
                    title="没有来源链接的消息",
                    snippet="这条结果不可验证。",
                    url="",
                    source="Unknown",
                    published_date="2026-08-01",
                ),
                SimpleNamespace(
                    title="不安全链接",
                    snippet="这条结果不能作为外链展示。",
                    url="javascript:alert(1)",
                    source="Unknown",
                    published_date="2026-08-01",
                ),
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(Path(tmpdir) / "screening")}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace()),
                patch("src.services.screening_service._get_dsa_search_service", return_value=search_service),
            ):
                payload = self._hotspot_detail(
                    config=config,
                    provider="akshare",
                    topic="钼",
                    include_search=True,
                )

        self.assertEqual(payload["news_search_status"], "no_results")
        self.assertFalse(any(item.get("search_result") for item in payload["route"]))
        self.assertEqual(payload["route"][0]["source"], "eastmoney_board_change")

    def test_hotspot_search_reports_operational_failure_without_losing_base_detail(self) -> None:
        search_service = MagicMock(is_available=True)
        search_service.search_topic_news_bounded.side_effect = TimeoutError("provider timed out")
        base_detail = {
            "topic": "钼",
            "route": [{"title": "当日发酵", "source": "eastmoney_board_change"}],
            "timeline": [{"title": "原始时间线", "source": "raw_timeline"}],
            "stocks": [{"code": "601958", "name": "金钼股份"}],
        }

        with patch("src.services.screening_service._get_dsa_search_service", return_value=search_service):
            payload = screening_service._with_hotspot_search_augmentation(base_detail, topic="钼")

        self.assertEqual(payload["news_search_status"], "unavailable")
        self.assertEqual(payload["route"], base_detail["route"])
        self.assertEqual(payload["timeline"], base_detail["timeline"])
        self.assertEqual(payload["stocks"], base_detail["stocks"])

    def test_hotspot_search_skips_invalid_links_before_valid_result(self) -> None:
        search_service = MagicMock(is_available=True)
        search_service.search_topic_news_bounded.return_value = SimpleNamespace(
            success=True,
            provider="Bocha",
            results=[
                SimpleNamespace(title="无链接", snippet="不可验证", url=""),
                SimpleNamespace(title="不安全链接", snippet="不可展示", url="javascript:alert(1)"),
                SimpleNamespace(
                    title="有效消息",
                    snippet="有效且可验证的新闻事件。",
                    url="https://example.com/valid-news",
                    source="ExampleNews",
                    published_date="2026-08-01",
                ),
            ],
        )

        with patch("src.services.screening_service._get_dsa_search_service", return_value=search_service):
            result = screening_service._build_hotspot_event_routes_from_search("钼")

        self.assertEqual(result.status, "available")
        self.assertEqual(len(result.routes), 1)
        self.assertEqual(result.routes[0]["title"], "有效消息")
        self.assertEqual(result.routes[0]["url"], "https://example.com/valid-news")

    def test_hotspot_search_does_not_pollute_or_refresh_shared_detail_cache(self) -> None:
        config = Config(screening_enabled=True, bocha_api_keys=["test-key"])
        provider = screening_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(return_value={
            "topic": "钼",
            "summary": "钼 当前涨跌幅 10.00%。",
            "route": [{"title": "当日发酵", "description": "钼板块异动。", "source": "eastmoney_board_change"}],
            "stocks": [{"code": "601958", "name": "金钼股份"}],
            "stock_count": 1,
            "source_errors": [],
        })
        search_service = MagicMock()
        search_service.search_topic_news_bounded.return_value = SimpleNamespace(
            success=True,
            provider="Bocha",
            results=[
                SimpleNamespace(
                    title="钼价上涨带动板块活跃",
                    snippet="供需偏紧带动钼价上涨，板块关注度提升。",
                    url="https://example.com/molybdenum",
                    source="ExampleNews",
                    published_date="2026-08-01",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(Path(tmpdir) / "screening")}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace()),
                patch("src.services.screening_service._get_dsa_search_service", return_value=search_service),
                patch(
                    "src.services.screening_service._write_screening_hotspot_detail_cache",
                    wraps=screening_service._write_screening_hotspot_detail_cache,
                ) as cache_write,
            ):
                searched = self._hotspot_detail(
                    config=config,
                    provider="akshare",
                    topic="钼",
                    include_search=True,
                )
                searched_again = self._hotspot_detail(
                    config=config,
                    provider="akshare",
                    topic="钼",
                    include_search=True,
                )
                plain = self._hotspot_detail(config=config, provider="akshare", topic="钼")

        self.assertTrue(searched["route"][0]["search_result"])
        self.assertTrue(searched_again["route"][0]["search_result"])
        self.assertEqual(plain["route"][0]["source"], "eastmoney_board_change")
        self.assertFalse(any(item.get("search_result") for item in plain["route"]))
        self.assertNotIn("news_search_requested", plain)
        self.assertNotIn("news_search_status", plain)
        self.assertTrue(plain["cache_used"])
        self.assertEqual(cache_write.call_count, 1)
        provider.hotspot_detail.assert_called_once_with("钼")
        self.assertEqual(search_service.search_topic_news_bounded.call_count, 2)

    def test_hotspot_search_summary_does_not_call_llm(self) -> None:
        config = Config(screening_enabled=True, litellm_model="openai/gpt-5-mini")
        provider = screening_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(return_value={
            "topic": "钼",
            "summary": "钼 当前涨跌幅 10.00%。",
            "route": [{"title": "当日发酵", "description": "钼板块异动。", "source": "eastmoney_board_change"}],
            "stocks": [],
            "stock_count": 0,
            "source_errors": [],
        })
        search_service = MagicMock()
        search_service.search_topic_news_bounded.return_value = SimpleNamespace(
            success=True,
            provider="Bocha",
            results=[
                SimpleNamespace(
                    title="以钼代钨带动小金属行情",
                    snippet="以钼代钨带动小金属行情，市场关注材料替代和供需偏紧。",
                    url="https://example.com/news",
                    source="ExampleNews",
                    published_date="2026-06-12",
                )
            ],
        )
        completion = MagicMock(side_effect=AssertionError("hotspot search must not call LLM"))

        with tempfile.TemporaryDirectory() as tmpdir:
            with (
                patch.dict(os.environ, {"SCREENING_DATA_DIR": str(Path(tmpdir) / "screening")}, clear=False),
                patch.dict(sys.modules, {"litellm": SimpleNamespace(completion=completion)}, clear=False),
                patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
                patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
                patch("src.services.screening_service.screening_hotspot", new=SimpleNamespace()),
                patch("src.services.screening_service._get_dsa_search_service", return_value=search_service),
            ):
                payload = self._hotspot_detail(
                    config=config,
                    provider="akshare",
                    topic="钼",
                    include_search=True,
                )

        self.assertIn("小金属", payload["route"][0]["description"])
        completion.assert_not_called()

    def test_hotspot_detail_prefers_timeline_when_engine_route_is_empty(self) -> None:
        config = self._config(enabled=True)
        provider = screening_service.DsaEastMoneyHotspotProvider()
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
            patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
            patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
            patch(
                "src.services.screening_service.screening_hotspot",
                new=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
            ),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="AI算力")

        self.assertEqual(payload["route"][0]["title"], "AI算力催化")
        self.assertEqual(payload["route"][0]["source"], "新闻")
        provider.hotspot_detail.assert_not_called()

    def test_hotspot_detail_falls_back_to_provider_when_engine_helper_fails(self) -> None:
        config = self._config(enabled=True)
        provider = screening_service.DsaEastMoneyHotspotProvider()
        provider.hotspot_detail = MagicMock(return_value={
            "topic": "机器人执行器",
            "summary": "机器人执行器 盘中发酵。",
            "route": [{"title": "盘中发酵", "description": "provider fallback route.", "source": "eastmoney_board_change"}],
            "stocks": [{"code": "002000", "name": "旧路径个股"}],
            "stock_count": 1,
            "source_errors": [],
        })

        def get_hotspot_detail(topic: str, **_kwargs: Any) -> Dict[str, Any]:
            raise RuntimeError("engine parser broken")

        with (
            patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
            patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
            patch(
                "src.services.screening_service.screening_hotspot",
                new=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
            ),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="机器人执行器")

        self.assertEqual(payload["route"][0]["title"], "盘中发酵")
        self.assertEqual(payload["route"][0]["source"], "eastmoney_board_change")
        provider.hotspot_detail.assert_called_once_with("机器人执行器")
        self.assertEqual(
            payload["source_errors"][0],
            "screening_hotspot_detail_fallback: engine parser broken",
        )
        self.assertTrue(payload["fallback_used"])

    def test_hotspot_detail_preserves_provider_route_when_engine_detail_has_no_timeline(self) -> None:
        config = self._config(enabled=True)
        provider = screening_service.DsaEastMoneyHotspotProvider()
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
                    "source": "screening_engine",
                }],
            }

        with (
            patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
            patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
            patch(
                "src.services.screening_service.screening_hotspot",
                new=SimpleNamespace(get_hotspot_detail=get_hotspot_detail),
            ),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="机器人执行器")

        self.assertEqual(payload["route"][0]["title"], "盘中发酵")
        self.assertEqual(payload["route"][0]["source"], "eastmoney_board_change")
        self.assertEqual(payload["stocks"][0]["name"], "合约路径个股")
        provider.hotspot_detail.assert_called_once_with("机器人执行器")

    def test_hotspot_detail_returns_route_and_concept_stocks(self) -> None:
        config = self._config(enabled=True)

        class FakeProvider(screening_service.DsaEastMoneyHotspotProvider):
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
            patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
            patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", FakeProvider())),
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
        app.include_router(screening_endpoint.router, prefix="/api/v1/screening")
        app.dependency_overrides[screening_endpoint.get_config_dep] = lambda: config
        service = MagicMock()
        service.hotspot_detail.return_value = {
            "enabled": True,
            "provider": "akshare",
            "topic": "DRG/DIP",
            "route": [],
            "stocks": [],
            "stock_count": 0,
        }

        with patch("api.v1.endpoints.screening._service", return_value=service):
            response = TestClient(app).get("/api/v1/screening/hotspots/DRG%2FDIP?provider=akshare")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["topic"], "DRG/DIP")
        service.hotspot_detail.assert_called_once_with(
            topic="DRG/DIP",
            provider="akshare",
            refresh=False,
            include_search=False,
        )

    def test_hotspot_detail_falls_back_when_ths_constituents_fail(self) -> None:
        import pandas as pd

        config = self._config(enabled=True)

        class FakeProvider(screening_service.DsaEastMoneyHotspotProvider):
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
            patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
            patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", FakeProvider())),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="AI算力")

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["provider"], "akshare")
        self.assertEqual(payload["topic"], "AI算力")
        self.assertEqual(payload["stocks"][0]["name"], "中际旭创")
        self.assertEqual(payload["route"][0]["title"], "fallback")

    def test_hotspot_provider_merges_constituent_sources_before_single_leader_fallback(self) -> None:
        import pandas as pd

        class FakeProvider(screening_service.DsaEastMoneyHotspotProvider):
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

    def test_hotspot_provider_keeps_source_priority_when_secondary_finishes_first(self) -> None:
        class FakeProvider(screening_service.DsaEastMoneyHotspotProvider):
            def _fetch_eastmoney_constituents(self, topic: str, *, source: str) -> Any:
                time.sleep(0.05)
                return pd.DataFrame([{"代码": "000001", "名称": "东财名称"}])

            def _fetch_ths_constituents(self, topic: str) -> Any:
                return pd.DataFrame([
                    {"code": "000001", "name": "同花顺名称"},
                    {"code": "000002", "name": "万科A"},
                ])

            def _fallback_constituents(self, topic: str) -> Any:
                return pd.DataFrame()

            def _related_hotspot_constituents(self, topic: str) -> Any:
                return pd.DataFrame()

        frame = FakeProvider().stock_board_concept_cons_em("金融")

        self.assertEqual(list(frame["code"]), ["000001", "000002"])
        self.assertEqual(frame.iloc[0]["name"], "东财名称")

    def test_hotspot_provider_joins_all_constituent_workers_before_returning(self) -> None:
        import pandas as pd

        slow_source_finished = threading.Event()

        class FakeProvider(screening_service.DsaEastMoneyHotspotProvider):
            def _fetch_eastmoney_constituents(self, topic: str, *, source: str) -> Any:
                time.sleep(0.08)
                slow_source_finished.set()
                return pd.DataFrame()

            def _fetch_ths_constituents(self, topic: str) -> Any:
                return pd.DataFrame([{"code": "000003", "name": "国农科技"}])

            def _fallback_constituents(self, topic: str) -> Any:
                return pd.DataFrame()

            def _related_hotspot_constituents(self, topic: str) -> Any:
                return pd.DataFrame()

        started = time.monotonic()
        frame = FakeProvider().stock_board_concept_cons_em("金融")

        self.assertLess(time.monotonic() - started, 0.3)
        self.assertEqual(list(frame["code"]), ["000003"])
        self.assertTrue(slow_source_finished.is_set())
        self.assertFalse(any(
            thread.name.startswith("screening-constituents")
            for thread in threading.enumerate()
        ))

    def test_hotspot_provider_caps_and_reuses_constituent_worker_capacity(self) -> None:
        started = threading.Event()
        release = threading.Event()
        call_count = 0
        call_lock = threading.Lock()

        class FakeProvider(screening_service.DsaEastMoneyHotspotProvider):
            _CONSTITUENT_WORKER_SLOTS = threading.BoundedSemaphore(1)

            def _fetch_eastmoney_constituents(self, topic: str, *, source: str) -> Any:
                nonlocal call_count
                with call_lock:
                    call_count += 1
                started.set()
                release.wait(1)
                return pd.DataFrame([{"code": "000001", "name": "平安银行"}])

        first_provider = FakeProvider()
        second_provider = FakeProvider()
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(
                first_provider._fetch_constituent_sources,
                "金融",
                source="industry",
            )
            self.assertTrue(started.wait(0.3))
            skipped = second_provider._fetch_constituent_sources("银行", source="industry")
            self.assertEqual(skipped, [])
            release.set()
            self.assertEqual(len(first.result(timeout=0.5)), 1)

        reused = second_provider._fetch_constituent_sources("银行", source="industry")
        self.assertEqual(len(reused), 1)
        self.assertEqual(call_count, 2)

    def test_hotspot_provider_maps_cross_source_topic_alias_to_ths_concept(self) -> None:
        provider = screening_service.DsaEastMoneyHotspotProvider()
        concept_names = pd.DataFrame([
            {"name": "文化传媒概念", "code": "300806"},
            {"name": "其他概念", "code": "301000"},
        ])

        with patch.object(provider, "_fetch_ths_concept_names", return_value=concept_names):
            code = provider._resolve_ths_concept_code("文字媒体")

        self.assertEqual(code, "300806")

    def test_hotspot_provider_routes_akshare_constituents_through_bounded_process(self) -> None:
        provider = screening_service.DsaEastMoneyHotspotProvider()
        constituents = pd.DataFrame([{"代码": "000001", "名称": "平安银行"}])

        with patch(
            "data_provider.akshare_fetcher._akshare_call_with_timeout",
            return_value=constituents,
        ) as bounded_call:
            frame = provider._fetch_eastmoney_constituents("金融", source="concept")

        self.assertEqual(frame.iloc[0]["代码"], "000001")
        self.assertEqual(bounded_call.call_count, 1)
        self.assertEqual(bounded_call.call_args.kwargs["symbol"], "金融")
        self.assertEqual(
            bounded_call.call_args.kwargs["timeout"],
            provider._AKSHARE_CALL_TIMEOUT_SECONDS,
        )
        self.assertIn("stock_board_concept_cons_em", bounded_call.call_args.kwargs["call_name"])

    def test_hotspot_provider_routes_configured_budget_into_hard_deadline(self) -> None:
        provider = screening_service.DsaEastMoneyHotspotProvider()
        rankings = [{
            "name": "机器人概念",
            "change_pct": 3.5,
        }]

        with (
            patch.dict(os.environ, {"SCREENING_HOTSPOT_CALL_TIMEOUT_SEC": "0.25"}, clear=False),
            patch(
                "data_provider.akshare_fetcher._akshare_call_with_timeout",
                side_effect=[pd.DataFrame(), (rankings, [])],
            ) as bounded_call,
        ):
            frame = screening_service.screening_hotspot._call_provider_frame(
                provider,
                "stock_board_concept_name_em",
                provider_label="dsa_eastmoney",
            )

        self.assertIsNotNone(frame)
        self.assertEqual(frame.iloc[0]["name"], "机器人概念")
        self.assertEqual(bounded_call.call_count, 2)
        timeouts = [call.kwargs["timeout"] for call in bounded_call.call_args_list]
        self.assertTrue(all(0 < timeout <= 0.25 for timeout in timeouts))
        self.assertLessEqual(timeouts[1], timeouts[0])

    def test_hotspot_provider_detail_fallback_reuses_one_configured_deadline(self) -> None:
        provider = screening_service.DsaEastMoneyHotspotProvider()
        observed_timeouts: List[float] = []

        def record_remaining(value: Any) -> Any:
            observed_timeouts.append(provider._akshare_timeout_seconds())
            time.sleep(0.005)
            return value

        with (
            patch.dict(os.environ, {"SCREENING_HOTSPOT_CALL_TIMEOUT_SEC": "0.25"}, clear=False),
            patch.object(provider, "_find_board_change", side_effect=lambda _topic: record_remaining({})),
            patch.object(provider, "_is_industry_hotspot", side_effect=lambda _topic: record_remaining(False)),
            patch.object(
                provider,
                "stock_board_concept_cons_em",
                side_effect=lambda _topic: record_remaining(pd.DataFrame([{
                    "code": "000001",
                    "name": "平安银行",
                }])),
            ),
            patch.object(
                provider,
                "_fetch_ths_summary_event",
                side_effect=lambda _topic: record_remaining(""),
            ),
            patch.object(provider, "_fetch_ths_info", side_effect=lambda _topic: record_remaining({})),
            patch("src.services.screening_service._get_dsa_fetcher_manager") as fetcher_manager,
        ):
            detail = provider.hotspot_detail("机器人")

        self.assertEqual(detail["leader_stocks"][0]["code"], "000001")
        self.assertEqual(len(observed_timeouts), 5)
        self.assertTrue(all(0 < timeout <= 0.25 for timeout in observed_timeouts))
        self.assertTrue(all(
            later < earlier
            for earlier, later in zip(observed_timeouts, observed_timeouts[1:])
        ))
        fetcher_manager.assert_not_called()

    def test_hotspot_provider_routes_remaining_budget_into_http_timeout(self) -> None:
        provider = screening_service.DsaEastMoneyHotspotProvider()
        response = MagicMock()
        response.json.return_value = {
            "data": {"diff": [{"f14": "机器人概念", "f3": 3.5}]},
        }
        provider._session.get = MagicMock(return_value=response)

        with (
            patch.dict(os.environ, {"SCREENING_HOTSPOT_CALL_TIMEOUT_SEC": "0.25"}, clear=False),
            patch.object(provider, "_fetch_board_changes_with_fallback", return_value=pd.DataFrame()),
            patch.object(provider, "_fetch_rankings_with_fallback", return_value=pd.DataFrame()),
        ):
            frame = provider.stock_board_concept_name_em()

        self.assertEqual(frame.iloc[0]["板块名称"], "机器人概念")
        timeout = provider._session.get.call_args.kwargs["timeout"]
        self.assertGreater(timeout[0], 0)
        self.assertGreater(timeout[1], 0)
        self.assertLessEqual(sum(timeout), 0.25)

    def test_hotspot_provider_disabled_outer_budget_keeps_source_hard_deadline(self) -> None:
        provider = screening_service.DsaEastMoneyHotspotProvider()
        board_changes = pd.DataFrame([{
            "板块名称": "机器人",
            "涨跌幅": 3.5,
            "板块异动总次数": 20,
        }])

        with (
            patch.dict(os.environ, {"SCREENING_HOTSPOT_CALL_TIMEOUT_SEC": "off"}, clear=False),
            patch(
                "data_provider.akshare_fetcher._akshare_call_with_timeout",
                return_value=board_changes,
            ) as bounded_call,
        ):
            frame = screening_service.screening_hotspot._call_provider_frame(
                provider,
                "stock_board_concept_name_em",
                provider_label="dsa_eastmoney",
            )

        self.assertIsNotNone(frame)
        self.assertEqual(
            bounded_call.call_args.kwargs["timeout"],
            provider._AKSHARE_CALL_TIMEOUT_SECONDS,
        )

    def test_hotspot_provider_reaps_timed_out_constituent_process(self) -> None:
        import akshare as ak

        provider = screening_service.DsaEastMoneyHotspotProvider()
        provider._AKSHARE_CALL_TIMEOUT_SECONDS = 0.05
        started = time.monotonic()

        with patch.object(ak, "stock_board_concept_cons_em", new=_sleeping_constituent_source):
            with self.assertRaises(TimeoutError):
                provider._fetch_eastmoney_constituents("金融", source="concept")

        self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse(any(
            process.name == "akshare-screening.stock_board_concept_cons_em"
            for process in multiprocessing.active_children()
        ))

    def test_hotspot_provider_adds_related_metal_leaders_for_narrow_topic(self) -> None:
        import pandas as pd

        provider = screening_service.DsaEastMoneyHotspotProvider()
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
        provider = screening_service.DsaEastMoneyHotspotProvider()
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
        provider = screening_service.DsaEastMoneyHotspotProvider()
        provider._fetch_ths_summary_event = MagicMock(return_value="")

        route = provider._build_hotspot_route("钼", {})

        self.assertEqual(route[0]["source"], "fallback")
        self.assertNotIn("以钼代钨", route[0]["description"])

    def test_hotspot_detail_uses_constituent_fallback_when_board_change_summary_fails(self) -> None:
        import pandas as pd

        config = self._config(enabled=True)

        class FakeProvider(screening_service.DsaEastMoneyHotspotProvider):
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
            patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
            patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", FakeProvider())),
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

        class FakeProvider(screening_service.DsaEastMoneyHotspotProvider):
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
            patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, {})),
            patch("src.services.screening_service._resolve_hotspot_provider", return_value=("akshare", provider)),
        ):
            payload = self._hotspot_detail(config=config, provider="akshare", topic="电池")

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["topic"], "电池")
        self.assertEqual(payload["stocks"][0]["name"], "宁德时代")
        self.assertEqual(provider.constituent_sources, ["industry"])

    def test_hotspot_provider_uses_board_name_fallback_when_rankings_fail(self) -> None:
        import pandas as pd

        provider = screening_service.DsaEastMoneyHotspotProvider()
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

        provider = screening_service.DsaEastMoneyHotspotProvider()
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

        provider = screening_service.DsaEastMoneyHotspotProvider()
        with patch.object(provider, "_fetch_board_changes_raw", return_value=board_changes) as fetch_raw:
            frame = provider._fetch_board_changes()
            summary = provider._find_board_change("AI算力")

        self.assertGreaterEqual(fetch_raw.call_count, 1)
        self.assertEqual(frame.iloc[0]["name"], "AI算力")
        self.assertEqual(frame.iloc[0]["stage"], "加速发酵")
        self.assertGreater(frame.iloc[0]["trend_score"], 0)
        self.assertGreater(frame.iloc[0]["persistence_score"], 0)
        self.assertEqual(frame.iloc[0]["sample_stock_count"], 1)
        self.assertEqual(frame.iloc[0]["leaders"], ["中际旭创"])
        self.assertEqual(summary["板块名称"], "AI算力")

    def test_fetch_ths_summary_event_ignores_missing_concept_name_column(self) -> None:
        import pandas as pd

        provider = screening_service.DsaEastMoneyHotspotProvider()
        summary = pd.DataFrame([
            {"日期": "2026-06-07", "驱动事件": "行业政策利好"},
        ])

        class _MockAkshare:
            @staticmethod
            def stock_board_concept_summary_ths():
                return summary

        with (
            patch.dict("sys.modules", {"akshare": _MockAkshare()}),
            patch(
                "data_provider.akshare_fetcher._akshare_call_with_timeout",
                return_value=summary,
            ),
        ):
            text = provider._fetch_ths_summary_event("MLCC")

        self.assertEqual(text, "")

    def test_strategies_rejects_when_engine_is_unavailable(self) -> None:
        config = self._config(enabled=True)

        with (
            patch(
                "src.services.screening_service._get_screening_status_snapshot",
                return_value=({}, False, _screening_unavailable_diagnostics()),
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                self._strategies(config=config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "screening_unavailable")
        self.assertEqual(caught.exception.detail.get("diagnostics", {}).get("reason"), "unexpected_exception")

    def test_screen_rejects_when_disabled(self) -> None:
        config = self._config(enabled=False)

        with self.assertRaises(HTTPException) as caught:
            self._screen(config)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "screening_disabled")

    def test_screen_rejects_when_screening_unavailable(self) -> None:
        config = self._config(enabled=True)

        with (
            patch(
                "src.services.screening_service._get_screening_status_snapshot",
                return_value=({}, False, _screening_unavailable_diagnostics()),
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "screening_unavailable")
        self.assertEqual(caught.exception.detail.get("diagnostics", {}).get("reason"), "unexpected_exception")
        self.assertIn("选股功能初始化失败", caught.exception.detail["message"])

    def test_start_screen_task_submits_background_work(self) -> None:
        config = self._config(enabled=True)
        fake_queue = MagicMock()
        fake_queue.submit_background_task.return_value = SimpleNamespace(
            task_id="screen-task-1",
            trace_id="screen-task-1",
            status=QueueTaskStatus.PENDING,
            message="Screening 选股任务已提交",
        )

        with (
            patch("api.v1.endpoints.screening.get_task_queue", return_value=fake_queue),
            patch("api.v1.endpoints.screening.uuid.uuid4", return_value=SimpleNamespace(hex="screen-task-1")),
            patch.object(
                screening_endpoint.ScreeningService,
                "screen",
                return_value={"enabled": True, "candidates": [], "candidate_count": 0},
            ) as screen_mock,
        ):
            payload = screening_endpoint.screening_start_screen_task(
                screening_endpoint.ScreeningScreenRequest(market="cn", strategy="dual_low", max_results=3),
                http_request=self._request(),
                config=config,
            )
            run_task = fake_queue.submit_background_task.call_args.args[0]
            result = run_task()

        self.assertEqual(payload.task_id, "screen-task-1")
        self.assertEqual(payload.max_results, 3)
        fake_queue.submit_background_task.assert_called_once()
        self.assertEqual(fake_queue.submit_background_task.call_args.kwargs["report_type"], "screening_screen")
        screen_mock.assert_called_once_with(
            strategy="dual_low",
            market="cn",
            max_results=3,
            selection_seed="",
            progress_callback=ANY,
        )
        screen_mock.call_args.kwargs["progress_callback"](66, "正在执行 LLM 候选重排")
        self.assertEqual(result["candidate_count"], 0)
        fake_queue.update_task_progress.assert_any_call(
            "screen-task-1",
            20,
            "正在执行选股，外部数据源较慢时会持续后台运行",
        )
        fake_queue.update_task_progress.assert_any_call(
            "screen-task-1",
            66,
            "正在执行 LLM 候选重排",
        )

    def test_screen_task_status_returns_screening_result(self) -> None:
        task = TaskInfo(
            task_id="screen-task-1",
            trace_id="screen-task-1",
            stock_code="screening_screen",
            status=QueueTaskStatus.COMPLETED,
            progress=100,
            message="任务执行完成",
            result={"enabled": True, "candidates": [], "candidate_count": 0},
            report_type="screening_screen",
        )
        fake_queue = MagicMock()
        fake_queue.get_task.return_value = task

        with patch("api.v1.endpoints.screening.get_task_queue", return_value=fake_queue):
            payload = screening_endpoint.screening_screen_task_status("screen-task-1")

        self.assertEqual(payload.status, "completed")
        self.assertEqual(payload.result["candidate_count"], 0)

    def test_screen_task_status_rejects_non_screening_task(self) -> None:
        task = TaskInfo(
            task_id="analysis-task-1",
            stock_code="600519",
            status=QueueTaskStatus.COMPLETED,
            report_type="detailed",
        )
        fake_queue = MagicMock()
        fake_queue.get_task.return_value = task

        with patch("api.v1.endpoints.screening.get_task_queue", return_value=fake_queue):
            with self.assertRaises(HTTPException) as caught:
                screening_endpoint.screening_screen_task_status("analysis-task-1")

        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.detail["error"], "screening_screen_task_not_found")


    def test_screen_calls_pipeline_and_normalizes_llm_fields(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
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
                    "llm_model_used": "openai/gpt-4.1",
                    "llm_attempted_models": ["deepseek/deepseek-chat", "openai/gpt-4.1"],
                    "llm_failure_reason": "",
                    "ranking_mode": "llm",
                    "warnings": "fallback",
                    "degradation": ["Snapshot source fallback: em_datacenter: retry from cache"],
                    "source_errors": "sina timeout",
                    "llm_parse_errors": "retry parsed partial JSON",
                    "deep_analysis_requested": False,
                    "post_analyzers": ["scorecard"],
                    "daily_enriched": True,
                    "daily_enrich_count": 12,
                    "risk_enabled": True,
                    "portfolio_diversity_enabled": True,
                    "portfolio_concentration_notes": ["sector concentration adjusted"],
                    "result_variant_applied": True,
                    "result_variant_pool_size": 4,
                    "result_variant_rotated_slots": 1,
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

        with _patch_screening_core(fake_module):
            payload = self._screen(
                config,
                market="cn",
                strategy="dual_low",
                max_results=5,
                variant_seed="browser-a",
            )

        fake_module.screen.assert_called_once_with(
            "dual_low",
            market="cn",
            max_output=5,
            use_llm=True,
            context=ANY,
            selection_seed="browser-a",
            config=ANY,
            progress_callback=None,
            daily_history_fetcher=ANY,
        )
        self.assertEqual(fake_module.screen.call_args.kwargs["context"]["llm"]["model"], "")
        self.assertEqual(payload["run_id"], "run123")
        self.assertEqual(payload["snapshot_count"], 100)
        self.assertEqual(payload["snapshot_source"], "em_datacenter")
        self.assertEqual(payload["after_filter_count"], 5)
        self.assertEqual(payload["llm_ranked"], True)
        self.assertEqual(payload["llm_coverage"], 1.0)
        self.assertEqual(payload["llm_model_used"], "openai/gpt-4.1")
        self.assertEqual(
            payload["llm_attempted_models"],
            ["deepseek/deepseek-chat", "openai/gpt-4.1"],
        )
        self.assertEqual(payload["ranking_mode"], "llm")
        self.assertEqual(
            payload["warnings"],
            ["fallback", "Snapshot source fallback: em_datacenter: retry from cache"],
        )
        self.assertEqual(
            payload["degradation"],
            ["Snapshot source fallback: em_datacenter: retry from cache"],
        )
        self.assertEqual(payload["source_errors"], ["sina timeout"])
        self.assertEqual(payload["llm_parse_errors"], ["retry parsed partial JSON"])
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["post_analyzers"], ["scorecard"])
        self.assertEqual(payload["daily_enriched"], True)
        self.assertEqual(payload["daily_enrich_count"], 12)
        self.assertEqual(payload["portfolio_concentration_notes"], ["sector concentration adjusted"])
        self.assertEqual(payload["result_variant_applied"], True)
        self.assertEqual(payload["result_variant_pool_size"], 4)
        self.assertEqual(payload["result_variant_rotated_slots"], 1)
        self.assertEqual(payload["candidates"][0]["code"], "600519")
        self.assertEqual(payload["candidates"][0]["llm_score"], 90.0)
        self.assertEqual(payload["candidates"][0]["llm_thesis"], "LLM likes the setup")
        self.assertEqual(payload["candidates"][0]["risk_level"], "medium")
        self.assertEqual(payload["candidates"][0]["price"], 1688.0)
        self.assertEqual(payload["candidates"][0]["industry"], "Baijiu")

    def test_screen_prefers_dsa_daily_history_for_screening_enrichment(self) -> None:
        config = self._config(enabled=True)
        from src.services.screening import daily as daily_module

        builtin_daily_fetch = daily_module.fetch_daily_history
        original_daily_fetch = MagicMock(side_effect=AssertionError("Screening daily fetch should not run first"))
        captured: Dict[str, Any] = {}

        def screen_with_daily_fetch(strategy: str, **kwargs: Any) -> Dict[str, Any]:
            daily_fetcher = kwargs["daily_history_fetcher"]
            daily_df = daily_fetcher(
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

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_with_daily_fetch))

        with (
            patch.object(daily_module, "fetch_daily_history", original_daily_fetch),
            _patch_screening_core(fake_module),
            patch(
                "src.services.screening_service.get_dsa_daily_history",
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
        self.assertIs(daily_module.fetch_daily_history, builtin_daily_fetch)

    def test_screen_enriches_top_candidates_with_dsa_context(self) -> None:
        config = self._config(enabled=True)
        fake_manager = SimpleNamespace(get_stock_name=MagicMock(return_value="贵州茅台"))
        fake_module = _make_screening_core(
            screen=MagicMock(
                return_value={
                    "candidates": [
                        {
                            "code": "600519",
                            "score": 88.5,
                            "reason": "Screening pick",
                        }
                    ]
                }
            ),
        )

        with (
            _patch_screening_core(fake_module),
            patch("src.services.screening_service._get_dsa_fetcher_manager", return_value=fake_manager),
            patch(
                "src.services.screening_service.get_dsa_realtime_quote",
                return_value={"price": 1688.0, "change_pct": 1.2, "amount": 100000000.0},
            ),
            patch(
                "src.services.screening_service.get_dsa_fundamental_context",
                return_value={"market": "cn", "coverage": {"valuation": "available"}},
            ),
            patch(
                "src.services.screening_service.search_dsa_stock_news",
                return_value={
                    "success": True,
                    "provider": "test",
                    "results": [{"title": "贵州茅台最新公告", "source": "测试源"}],
                },
            ),
            patch(
                "src.services.screening_service.search_dsa_stock_events",
                return_value={
                    "success": True,
                    "provider": "test",
                    "results": [{"title": "贵州茅台年度报告", "source": "测试源"}],
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
        self.assertEqual(candidate["dsa_events"][0]["title"], "贵州茅台年度报告")
        self.assertIn("DSA行情", candidate["dsa_analysis_summary"])
        self.assertEqual(payload["dsa_enrichment"]["enriched_count"], 1)

    def test_screen_reuses_screening_dsa_context_without_refetch(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
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
                                "warnings": ["from_screening_provider"],
                            },
                            "dsa_news": [{"title": "贵州茅台最新公告", "source": "测试源"}],
                            "dsa_analysis_summary": "DSA新闻: 贵州茅台最新公告",
                        }
                    ]
                }
            ),
        )

        with (
            _patch_screening_core(fake_module),
            patch("src.services.screening_service.get_dsa_realtime_quote") as quote_mock,
            patch("src.services.screening_service.get_dsa_fundamental_context") as fundamentals_mock,
            patch("src.services.screening_service.search_dsa_stock_news") as news_mock,
            patch("src.services.screening_service.search_dsa_stock_events") as events_mock,
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
        self.assertEqual(payload["dsa_enrichment"]["warnings"], ["from_screening_provider"])
        quote_mock.assert_not_called()
        fundamentals_mock.assert_not_called()
        news_mock.assert_not_called()
        events_mock.assert_not_called()

    def test_screen_reuses_context_news_results_without_refetch(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
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
                                "warnings": ["from_screening_provider"],
                            },
                            "dsa_news": [],
                        }
                    ]
                }
            ),
        )

        with (
            _patch_screening_core(fake_module),
            patch("src.services.screening_service.get_dsa_realtime_quote") as quote_mock,
            patch("src.services.screening_service.get_dsa_fundamental_context") as fundamentals_mock,
            patch("src.services.screening_service.search_dsa_stock_news") as news_mock,
            patch("src.services.screening_service.search_dsa_stock_events") as events_mock,
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
        self.assertEqual(payload["dsa_enrichment"]["warnings"], ["from_screening_provider"])
        quote_mock.assert_not_called()
        fundamentals_mock.assert_not_called()
        news_mock.assert_not_called()
        events_mock.assert_not_called()

    def test_screen_completes_light_screening_context_with_news_only(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
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
            _patch_screening_core(fake_module),
            patch("src.services.screening_service._get_dsa_fetcher_manager", return_value=fake_manager),
            patch("src.services.screening_service.get_dsa_realtime_quote") as quote_mock,
            patch("src.services.screening_service.get_dsa_fundamental_context") as fundamentals_mock,
            patch(
                "src.services.screening_service.search_dsa_stock_news",
                return_value={
                    "success": True,
                    "provider": "test",
                    "results": [{"title": "贵州茅台最新公告", "source": "测试源"}],
                },
            ) as news_mock,
            patch(
                "src.services.screening_service.search_dsa_stock_events",
                return_value={"success": False, "results": []},
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
            patch("src.services.screening_service._get_dsa_fetcher_manager", return_value=fake_manager),
            patch(
                "src.services.screening_service.get_dsa_realtime_quote",
                return_value={"price": 1688.0, "change_pct": 1.2, "amount": 100000000.0},
            ),
            patch(
                "src.services.screening_service.get_dsa_fundamental_context",
                return_value={"market": "cn", "coverage": {"valuation": "available"}},
            ),
            patch("src.services.screening_service.search_dsa_stock_news") as news_mock,
        ):
            context = screening_service.get_dsa_candidate_context("600519", "贵州茅台")

        self.assertEqual(context["profile"], "pre_rank_light")
        self.assertFalse(context["news_included"])
        self.assertTrue(context["news"]["skipped"])
        self.assertEqual(context["quote"]["price"], 1688.0)
        self.assertEqual(context["fundamentals"]["coverage"]["valuation"], "available")
        news_mock.assert_not_called()

    def test_screen_bridges_dsa_llm_config_into_screening_runtime(self) -> None:
        config = Config(
            screening_enabled=True,
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
            captured["config"] = kwargs.get("config")
            captured["context"] = kwargs.get("context")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(
                screening_service.os.environ,
                {
                    "GEMINI_API_KEY": "outer-key",
                    "TUSHARE_TOKEN": "",
                    "SNAPSHOT_SOURCE_PRIORITY": "",
                    "LLM_CANDIDATE_CONTEXT_ENABLED": "true",
                    "LLM_CANDIDATE_MULTIPLIER": "",
                    "LLM_MAX_CANDIDATES": "",
                    "DAILY_FETCH_RETRIES": "",
                    "DAILY_FETCH_MAX_WORKERS": "",
                },
                clear=False,
            ),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)
            self.assertEqual(screening_service.os.environ.get("GEMINI_API_KEY"), "outer-key")

        pipeline_config = captured["config"]
        self.assertIsInstance(pipeline_config, ScreeningPipelineConfig)
        self.assertEqual(pipeline_config.llm_model, "gemini/gemini-2.5-flash")
        self.assertEqual(pipeline_config.llm_fallback_models, ["deepseek/deepseek-chat"])
        self.assertEqual(pipeline_config.llm_channels[0]["name"], "gemini")
        self.assertEqual(pipeline_config.llm_channels[0]["protocol"], "gemini")
        self.assertEqual(pipeline_config.llm_channels[0]["api_keys"], ["dsa-gemini-key"])
        self.assertFalse(pipeline_config.llm_candidate_context_enabled)
        self.assertEqual(pipeline_config.llm_candidate_multiplier, 2)
        self.assertEqual(pipeline_config.llm_max_candidates, 10)
        self.assertEqual(pipeline_config.daily_source, "auto")
        self.assertEqual(pipeline_config.daily_fetch_retries, 3)
        self.assertEqual(pipeline_config.daily_fetch_max_workers, 1)
        self.assertEqual(
            pipeline_config.snapshot_source_priority,
            ["sina", "efinance", "akshare_em", "em_datacenter"],
        )
        self.assertEqual(pipeline_config.data_dir, screening_service.DSA_SCREENING_DATA_DIR)
        self.assertEqual(
            pipeline_config.fallback_snapshot_path,
            screening_service.DSA_SCREENING_DATA_DIR / "snapshot.last_good.json",
        )
        self.assertEqual(
            pipeline_config.daily_history_cache_dir,
            screening_service.DSA_SCREENING_DATA_DIR / "daily_history",
        )
        self.assertEqual(
            pipeline_config.industry_provider_cache_dir,
            screening_service.DSA_SCREENING_DATA_DIR / "industry_provider_cache",
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

    def test_screen_injects_dsa_channel_headers_into_screening_litellm_calls(self) -> None:
        config = Config(
            screening_enabled=True,
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

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(completion_calls[0]["extra_headers"], {"x-tenant": "dsa"})
        self.assertIsNot(fake_litellm.completion, completion_impl)
        self.assertTrue(
            getattr(fake_litellm.completion, "_screening_litellm_completion_bridge", False),
        )

    def test_screen_bridges_legacy_openai_fields_into_screening_runtime_env(self) -> None:
        config = Config(
            screening_enabled=True,
            litellm_model="openai/gpt-4o-mini",
            openai_api_keys=["dsa-openai-key"],
            openai_base_url="https://openai-compatible.example/v1",
        )
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **kwargs):
            captured["config"] = kwargs.get("config")
            captured["context"] = kwargs.get("context")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(
                screening_service.os.environ,
                {
                    "OPENAI_API_KEY": "outer-openai-key",
                    "OPENAI_BASE_URL": "https://outer-openai.example/v1",
                },
                clear=False,
            ),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)
            self.assertEqual(screening_service.os.environ.get("OPENAI_API_KEY"), "outer-openai-key")
            self.assertEqual(screening_service.os.environ.get("OPENAI_BASE_URL"), "https://outer-openai.example/v1")

        pipeline_config = captured["config"]
        self.assertIsInstance(pipeline_config, ScreeningPipelineConfig)
        self.assertEqual(pipeline_config.llm_api_key, "dsa-openai-key")
        self.assertEqual(pipeline_config.llm_base_url, "https://openai-compatible.example/v1")
        self.assertEqual(pipeline_config.llm_model, "openai/gpt-4o-mini")

        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["channels"], [])
        self.assertEqual(context["llm"]["model_list"], [])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_injects_openai_compatible_model_headers_into_screening_litellm_calls(self) -> None:
        config = Config(
            screening_enabled=True,
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

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            _patch_screening_core(fake_module),
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
            getattr(fake_litellm.completion, "_screening_litellm_completion_bridge", False),
        )

    def test_screen_bridges_openai_channel_base_url_and_headers(self) -> None:
        config = Config(
            screening_enabled=True,
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
            captured["config"] = kwargs.get("config")
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

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(len(completion_calls), 2)
        pipeline_config = captured["config"]
        self.assertIsInstance(pipeline_config, ScreeningPipelineConfig)
        self.assertEqual(pipeline_config.llm_base_url, "https://primary-openai.example/v1")
        self.assertEqual(pipeline_config.llm_api_key, "dsa-openai-primary")
        self.assertEqual(pipeline_config.llm_channels[0]["name"], "openai")
        self.assertEqual(pipeline_config.llm_channels[0]["base_url"], "https://primary-openai.example/v1")
        self.assertEqual(pipeline_config.llm_channels[0]["api_keys"], ["dsa-openai-primary"])
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
            screening_enabled=True,
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

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            _patch_screening_core(fake_module),
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
        self.assertTrue(getattr(fake_litellm.completion, "_screening_litellm_completion_bridge", False))

    def test_screen_handles_concurrent_requests_without_litellm_header_cross_pollution(self) -> None:
        config_a = Config(
            screening_enabled=True,
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
            screening_enabled=True,
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

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        def _run_screen(config: Config) -> None:
            self._screen(config, market="cn", strategy="dual_low", max_results=5, mock_enrichment=False)

        with (
            patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False),
            _patch_screening_core(fake_module),
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
        original_env = {key: screening_service.os.environ.get(key) for key in baseline_env}

        with (
            patch.dict(screening_service.os.environ, baseline_env, clear=False),
            patch("src.services.screening_service._build_screening_runtime_env") as runtime_env_mock,
            self.assertRaises(HTTPException) as caught,
        ):
            self._screen(config, market="cn", strategy="dual_low", max_results=5)
            for key, value in baseline_env.items():
                self.assertEqual(screening_service.os.environ.get(key), value)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "screening_disabled")
        runtime_env_mock.assert_not_called()
        for key, value in baseline_env.items():
            self.assertEqual(screening_service.os.environ.get(key), original_env[key])

    def test_screen_preserves_explicit_screening_snapshot_source_priority(self) -> None:
        config = self._config(enabled=True)
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["snapshot_priority"] = screening_service.os.environ.get("SNAPSHOT_SOURCE_PRIORITY")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(screening_service.os.environ, {"SNAPSHOT_SOURCE_PRIORITY": "tushare,em_datacenter"}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["snapshot_priority"], "tushare,em_datacenter")
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_preserves_explicit_daily_source(self) -> None:
        config = self._config(enabled=True)
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["daily_source"] = screening_service.os.environ.get("DAILY_SOURCE")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(screening_service.os.environ, {"DAILY_SOURCE": "akshare"}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["daily_source"], "akshare")
        self.assertEqual(payload["candidate_count"], 0)

    def test_dsa_daily_history_bridge_preserves_cache_kwargs_for_screening_fallback(self) -> None:
        import src.services.screening.daily as daily_module

        captured: dict[str, object] = {}
        expected = object()

        def fallback_fetch(code: str, **kwargs):
            captured["code"] = code
            captured.update(kwargs)
            return expected

        with (
            patch.object(daily_module, "fetch_daily_history", new=fallback_fetch),
            patch("src.services.screening_service.get_dsa_daily_history", side_effect=RuntimeError("dsa unavailable")),
        ):
            daily_fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
            self.assertIsNotNone(daily_fetcher)
            result = daily_fetcher(
                "000001",
                lookback_days=90,
                source="auto",
                retries=4,
                cache_dir=Path("data/screening/daily_history"),
                cache_ttl_seconds=321.0,
            )

        self.assertIs(result, expected)
        self.assertEqual(captured["code"], "000001")
        self.assertEqual(captured["lookback_days"], 90)
        self.assertEqual(captured["source"], "auto")
        self.assertEqual(captured["retries"], 4)
        self.assertEqual(captured["cache_dir"], Path("data/screening/daily_history"))
        self.assertEqual(captured["cache_ttl_seconds"], 321.0)

    def test_dsa_daily_history_fetchers_are_request_local_when_calls_overlap(self) -> None:
        import src.services.screening.daily as daily_module

        builtin_fetch = daily_module.fetch_daily_history
        barrier = threading.Barrier(2)
        fallback_fetch = MagicMock(side_effect=lambda code, **_kwargs: f"fallback:{code}")

        def unavailable_dsa(code: str, *, lookback_days: int = 120):
            barrier.wait(timeout=5)
            raise RuntimeError(f"dsa unavailable for {code}:{lookback_days}")

        with (
            patch.object(daily_module, "fetch_daily_history", new=fallback_fetch),
            patch("src.services.screening_service.get_dsa_daily_history", side_effect=unavailable_dsa) as dsa_mock,
        ):
            first_fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
            second_fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
            self.assertIsNotNone(first_fetcher)
            self.assertIsNotNone(second_fetcher)

            with ThreadPoolExecutor(max_workers=2) as executor:
                first_future = executor.submit(first_fetcher, "000001", lookback_days=30)
                second_future = executor.submit(second_fetcher, "000002", lookback_days=30)

            self.assertEqual(first_future.result(), "fallback:000001")
            self.assertEqual(second_future.result(), "fallback:000002")
            self.assertIs(daily_module.fetch_daily_history, fallback_fetch)
            self.assertEqual(dsa_mock.call_count, 2)
            self.assertEqual(fallback_fetch.call_count, 2)

        self.assertIs(daily_module.fetch_daily_history, builtin_fetch)

    def test_fetch_daily_history_wraps_tencent_and_sina_with_daily_timeout(self) -> None:
        import src.services.screening.daily as daily_module

        wrapped_calls: list[dict[str, object]] = []

        def fake_wrapper(fetcher, source: str, *args, **kwargs):
            wrapped_calls.append(
                {
                    "fetcher": fetcher.__name__,
                    "source": source,
                    "args": args,
                    "kwargs": kwargs,
                }
            )
            return pd.DataFrame(
                [
                    {
                        "date": "2026-06-03",
                        "open": 10.0,
                        "high": 10.5,
                        "low": 9.8,
                        "close": 10.2,
                        "volume": 123400,
                    }
                ]
            )

        with patch.object(daily_module, "_call_daily_wrapper", side_effect=fake_wrapper):
            tencent_result = daily_module.fetch_daily_history(
                "1",
                lookback_days=20,
                source="tencent",
                retries=0,
            )
            sina_result = daily_module.fetch_daily_history(
                "2",
                lookback_days=30,
                source="sina",
                retries=0,
            )

        self.assertEqual(
            wrapped_calls,
            [
                {
                    "fetcher": "_fetch_daily_tencent",
                    "source": "tencent",
                    "args": ("000001",),
                    "kwargs": {"lookback_days": 20},
                },
                {
                    "fetcher": "_fetch_daily_sina",
                    "source": "sina",
                    "args": ("000002",),
                    "kwargs": {"lookback_days": 30},
                },
            ],
        )
        self.assertEqual(tencent_result.attrs["daily_source"], "tencent")
        self.assertEqual(sina_result.attrs["daily_source"], "sina")

    def test_dsa_daily_history_bridge_writes_last_good_cache_on_dsa_success(self) -> None:
        import src.services.screening.daily as daily_module

        cache_dir = Path("data/screening/daily_history")
        cache_path = cache_dir / "000001.auto.90.json"

        with (
            patch.object(
                daily_module,
                "fetch_daily_history",
                new=MagicMock(side_effect=AssertionError("Screening fallback should not run")),
            ),
            patch(
                "src.services.screening_service.get_dsa_daily_history",
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
            ),
            patch.object(daily_module, "_daily_history_cache_path", return_value=cache_path) as cache_path_mock,
            patch.object(daily_module, "_write_daily_history_cache") as cache_write_mock,
        ):
            daily_fetcher = screening_service._build_screening_dsa_daily_history_fetcher()
            self.assertIsNotNone(daily_fetcher)
            result = daily_fetcher(
                "000001",
                lookback_days=90,
                source="auto",
                retries=2,
                cache_dir=cache_dir,
                cache_ttl_seconds=321.0,
            )

        self.assertEqual(result.attrs["source"], "dsa:EfinanceFetcher")
        self.assertEqual(result.attrs["daily_source"], "dsa:EfinanceFetcher")
        self.assertEqual(result.attrs["daily_requested_source"], "auto")
        cache_path_mock.assert_called_once_with(
            cache_dir,
            code="000001",
            source="auto",
            lookback_days=90,
        )
        cache_write_mock.assert_called_once()
        self.assertEqual(cache_write_mock.call_args.args[0], cache_path)
        self.assertIs(cache_write_mock.call_args.args[1], result)
        self.assertEqual(cache_write_mock.call_args.kwargs["code"], "000001")
        self.assertEqual(cache_write_mock.call_args.kwargs["source"], "auto")
        self.assertEqual(cache_write_mock.call_args.kwargs["lookback_days"], 90)

    def test_screen_preserves_explicit_openai_base_url_without_openai_channel(self) -> None:
        config = Config(
            screening_enabled=True,
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
            captured["openai_base_url"] = screening_service.os.environ.get("OPENAI_BASE_URL")
            captured["llm_openai_base_url"] = screening_service.os.environ.get("LLM_OPENAI_BASE_URL")
            captured["openai_api_key"] = screening_service.os.environ.get("OPENAI_API_KEY")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(
                screening_service.os.environ,
                {
                    "OPENAI_BASE_URL": "https://outer-openai.example/v1",
                    "LLM_OPENAI_BASE_URL": "https://outer-openai-channel.example/v1",
                    "OPENAI_API_KEY": "outer-openai-key",
                },
                clear=False,
            ),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["openai_base_url"], "https://outer-openai.example/v1")
        self.assertEqual(captured["llm_openai_base_url"], "https://outer-openai-channel.example/v1")
        self.assertEqual(captured["openai_api_key"], "outer-openai-key")
        self.assertEqual(payload["candidate_count"], 0)

    def test_screening_runtime_priority_puts_tushare_before_sina_when_token_exists(self) -> None:
        config = self._config(enabled=True)
        config.tushare_token = "token-1"

        with patch.dict(screening_service.os.environ, {"SNAPSHOT_SOURCE_PRIORITY": ""}, clear=False):
            env = screening_service._build_screening_runtime_env(config)

        self.assertEqual(env["SNAPSHOT_SOURCE_PRIORITY"], "tushare,sina,efinance,akshare_em,em_datacenter")

    def test_screen_preserves_explicit_candidate_context_provider_override(self) -> None:
        config = self._config(enabled=True)
        captured: dict[str, object] = {}

        def screen_impl(_strategy: str, **_kwargs):
            captured["providers"] = screening_service.os.environ.get("LLM_CANDIDATE_CONTEXT_PROVIDERS")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with (
            patch.dict(screening_service.os.environ, {"LLM_CANDIDATE_CONTEXT_PROVIDERS": "news,announcement"}, clear=False),
            _patch_screening_core(fake_module),
        ):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(captured["providers"], "news,announcement")
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_filters_undeclared_managed_fallbacks_for_dsa_routes(self) -> None:
        config = Config(
            screening_enabled=True,
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
            captured["config"] = kwargs.get("config")
            captured["context"] = kwargs.get("context")
            return {"candidates": []}

        fake_module = _make_screening_core(screen=MagicMock(side_effect=screen_impl))

        with _patch_screening_core(fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        pipeline_config = captured["config"]
        self.assertIsInstance(pipeline_config, ScreeningPipelineConfig)
        self.assertEqual(pipeline_config.llm_model, "gemini/gemini-3-flash-preview")
        self.assertEqual(pipeline_config.llm_fallback_models, ["deepseek/deepseek-chat"])
        self.assertEqual(
            [channel["name"] for channel in pipeline_config.llm_channels],
            ["gemini", "deepseek"],
        )
        context = captured["context"]
        self.assertIsInstance(context, dict)
        self.assertEqual(context["llm"]["fallback_models"], ["deepseek/deepseek-chat"])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_does_not_run_when_engine_is_unavailable(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(screen=MagicMock(return_value={"candidates": []}))

        with (
            patch(
                "src.services.screening_service._get_screening_status_snapshot",
                return_value=({}, False, _screening_unavailable_diagnostics()),
            ),
            _patch_screening_core(fake_module),
        ):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail.get("diagnostics", {}).get("reason"), "unexpected_exception")
        fake_module.screen.assert_not_called()

    def test_screen_normalizes_non_finite_values(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            screen=MagicMock(
                return_value={
                    "picks": [
                        {
                            "code": "600519",
                            "name": "Kweichow Moutai",
                            "score": float("nan"),
                            "ranking_reason": "Screening pick",
                            "nested": {"pe": float("inf"), "pb": float("-inf"), "eps": 20.5},
                        },
                    ],
                }
            ),
        )

        with _patch_screening_core(fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertIsNone(payload["candidates"][0]["score"])
        self.assertIsNone(payload["candidates"][0]["raw"]["score"])
        self.assertIsNone(payload["candidates"][0]["raw"]["nested"]["pe"])
        self.assertIsNone(payload["candidates"][0]["raw"]["nested"]["pb"])

    def test_screen_allows_non_listed_strategy_as_custom(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            list_strategies=lambda: [{"id": "dual_low", "name": "双低选股"}],
            screen=MagicMock(return_value={"candidates": []}),
        )

        with _patch_screening_core(fake_module):
            payload = self._screen(config, market="cn", strategy="custom_alpha", max_results=5)

        fake_module.screen.assert_called_once_with(
            "custom_alpha",
            market="cn",
            max_output=5,
            use_llm=True,
            context=ANY,
            selection_seed="",
            config=ANY,
            progress_callback=None,
            daily_history_fetcher=ANY,
        )
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_rejects_unsupported_market(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            get_status=lambda: {"supported_markets": ["hk", "us"]},
            screen=MagicMock(return_value=[]),
        )

        with _patch_screening_core(fake_module):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail["error"], "screening_invalid_market")

    def test_screen_maps_pipeline_value_error_to_bad_request(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_screening_core(
            screen=MagicMock(side_effect=ValueError("Only market='cn' is currently supported")),
        )

        with _patch_screening_core(fake_module):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail["error"], "screening_screen_rejected")


if __name__ == "__main__":
    unittest.main()
