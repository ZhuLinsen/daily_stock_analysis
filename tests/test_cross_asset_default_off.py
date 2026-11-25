# -*- coding: utf-8 -*-
"""Default-off chain tests for cross-asset context (Issue #1910, PR #2428 r2).

Maintainer guardrail (#2428 review opinion 1): a new external-network context
must NOT be enabled by default — "不配置不影响既有主流程、显式开启后增强能力".
This file pins the whole chain to opt-in:

- ``src/config.py`` default (env unset) is ``False``;
- ``src/core/config_registry.py`` ``default_value`` is ``"false"`` (Web settings);
- ``.env.example`` ships ``CROSS_ASSET_CONTEXT_ENABLED=false`` (never ``true``);
- a real Config parsed with the flag unset makes the pipeline do zero
  cross-asset work (no service call, no fetch, no prompt keys).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestConfigDefaultOff:
    def test_env_unset_means_disabled(self, monkeypatch):
        from src.config import Config

        monkeypatch.delenv("CROSS_ASSET_CONTEXT_ENABLED", raising=False)
        config = Config._load_from_env()
        assert config.cross_asset_context_enabled is False

    def test_explicit_true_enables(self, monkeypatch):
        from src.config import Config

        monkeypatch.setenv("CROSS_ASSET_CONTEXT_ENABLED", "true")
        config = Config._load_from_env()
        assert config.cross_asset_context_enabled is True

    def test_explicit_false_disables(self, monkeypatch):
        from src.config import Config

        monkeypatch.setenv("CROSS_ASSET_CONTEXT_ENABLED", "false")
        config = Config._load_from_env()
        assert config.cross_asset_context_enabled is False


class TestRegistryAndEnvExampleDefaultOff:
    def test_registry_default_value_is_false(self):
        from src.core.config_registry import get_field_definition

        definition = get_field_definition("CROSS_ASSET_CONTEXT_ENABLED")
        assert definition["default_value"] == "false"

    def test_env_example_ships_false_never_true(self):
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        enabled_lines = [
            line
            for line in text.splitlines()
            if line.strip().startswith("CROSS_ASSET_CONTEXT_ENABLED=")
        ]
        assert enabled_lines == ["CROSS_ASSET_CONTEXT_ENABLED=false"]


class TestRealConfigUnsetDrivesZeroPipelineWork:
    """The full-chain proof: with a real Config whose flag is unset (default
    false), the pipeline performs zero cross-asset work — no service call,
    no context keys (mirrors the main baseline behaviour)."""

    def _real_config(self, monkeypatch) -> SimpleNamespace:
        from src.config import Config

        monkeypatch.delenv("CROSS_ASSET_CONTEXT_ENABLED", raising=False)
        for name in (
            "CROSS_ASSET_CONTEXT_TIMEOUT_SECONDS",
            "CROSS_ASSET_CONTEXT_STALE_DAYS",
        ):
            monkeypatch.delenv(name, raising=False)
        return Config._load_from_env()

    def test_pipeline_load_returns_none_without_service_call(self, monkeypatch):
        from src.core.pipeline import StockAnalysisPipeline

        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = self._real_config(monkeypatch)
        pipeline.analysis_skills = None

        with patch(
            "src.core.pipeline.get_default_cross_asset_context_service"
        ) as factory:
            loaded = pipeline._load_cross_asset_context(
                "cn", target_date=date(2026, 6, 6), stock_code="600519"
            )

        assert loaded is None
        factory.assert_not_called()

    def test_attach_stays_noop_for_disabled_chain(self, monkeypatch):
        from src.core.pipeline import StockAnalysisPipeline

        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.config = self._real_config(monkeypatch)
        pipeline.analysis_skills = None

        enhanced_context: dict = {"code": "600519"}
        loaded = pipeline._load_cross_asset_context(
            "cn", target_date=date(2026, 6, 6)
        )
        pipeline._attach_cross_asset_context(
            enhanced_context, loaded, report_language="zh"
        )

        assert "cross_asset_context" not in enhanced_context
        assert "cross_asset_context_summary" not in enhanced_context
        assert loaded is None

    def test_service_get_context_with_real_default_config_skips_fetch(self, monkeypatch):
        from src.services.cross_asset_context_service import CrossAssetContextService

        config = self._real_config(monkeypatch)
        fetcher = MagicMock()
        service = CrossAssetContextService(fetcher=fetcher, config=config)

        context = service.get_context("cn", date(2026, 6, 6))

        fetcher.fetch_market_snapshot.assert_not_called()
        assert context.risk_appetite == "unknown"
        assert context.data_quality.limitations
        assert "disabled" in context.data_quality.limitations[0]
