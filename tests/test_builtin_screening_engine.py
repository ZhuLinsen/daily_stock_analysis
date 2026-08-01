# -*- coding: utf-8 -*-
"""Regression contracts for the DSA-owned screening implementation."""

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient

from api.v1.router import router
from src.services.screening import REFERENCE_REVISION
from src.services.screening.dsa_provider import apply_dsa_provider_context
from src.services.screening import pipeline as screening_pipeline
from src.services.screening.filter import apply_hard_filters
from src.services.screening.config import Config as ScreeningRuntimeConfig
from src.services.screening.models import HardFilterConfig, Pick, ScreeningConfig, Strategy
from src.services.screening.scorer import compute_screen_scores
from src.services.screening import snapshot as screening_snapshot
from src.services.screening.strategy import list_strategies, load_all_strategies


REPO_ROOT = Path(__file__).resolve().parents[1]
SCREENING_ROOT = REPO_ROOT / "src" / "services" / "screening"


def test_screening_engine_is_collected_from_the_internal_package() -> None:
    requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")

    assert "alphasift.git" not in requirements
    assert "#egg=alphasift" not in requirements
    assert "import src.services.screening.pipeline" in dockerfile


def test_screening_routes_have_a_primary_prefix_and_no_install_endpoint() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    schema_paths = app.openapi()["paths"]
    assert "/api/v1/screening/status" in schema_paths
    assert "/api/v1/alphasift/status" not in schema_paths

    client = FastAPITestClient(app)
    assert client.request("OPTIONS", "/api/v1/screening/status").status_code != 404
    assert client.request("OPTIONS", "/api/v1/alphasift/status").status_code == 404
    assert client.request("POST", "/api/v1/screening/install").status_code == 404


def test_bundled_engine_keeps_source_and_license_notices() -> None:
    notice = (REPO_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    license_text = (SCREENING_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert REFERENCE_REVISION in notice
    assert "Apache License" in license_text
    derived_files = [
        *SCREENING_ROOT.glob("*.py"),
        *(SCREENING_ROOT / "strategies").glob("*.yaml"),
    ]
    assert derived_files
    for path in derived_files:
        source = path.read_text(encoding="utf-8")
        assert f"Derived from AlphaSift revision {REFERENCE_REVISION}." in source


def test_bundled_strategies_are_loaded_from_the_internal_package() -> None:
    strategies = load_all_strategies(SCREENING_ROOT / "strategies")

    assert set(strategies) == {
        "balanced_alpha",
        "blue_chip_income",
        "capital_heat",
        "dual_low",
        "low_volatility_quality",
        "momentum_quality",
        "oversold_reversal",
        "quality_value",
        "shrink_pullback",
        "volume_breakout",
    }
    assert strategies["dual_low"].screening.factor_weights["value"] < 0.40


def test_list_strategies_preserves_legacy_strategies_dir_override() -> None:
    strategy_yaml = """
name: custom_demo
display_name: 自定义策略
description: custom strategy
screening:
  enabled: true
  market_scope: [cn]
  hard_filters: {}
  factor_weights:
    value: 1.0
  max_output: 3
""".strip()

    with tempfile.TemporaryDirectory() as temp_dir:
        strategy_path = Path(temp_dir) / "custom_demo.yaml"
        strategy_path.write_text(strategy_yaml, encoding="utf-8")

        with patch.dict(os.environ, {"STRATEGIES_DIR": temp_dir}, clear=False):
            config = ScreeningRuntimeConfig.from_env()
            strategies = list_strategies()

    assert config.strategies_dir == Path(temp_dir)
    assert [item.name for item in strategies] == ["custom_demo"]


def test_pipeline_passes_daily_history_cache_settings_to_enrichment(monkeypatch) -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "code": "000001",
                "name": "Ping An",
                "price": 10.0,
                "change_pct": 1.2,
                "amount": 200_000_000.0,
            }
        ]
    )
    snapshot_df.attrs.update({
        "snapshot_source": "sina",
        "source_errors": [],
        "fallback_used": False,
    })
    strategy = Strategy(
        name="demo",
        display_name="Demo",
        description="demo",
        screening=ScreeningConfig(
            enabled=True,
            market_scope=["cn"],
            hard_filters=HardFilterConfig(),
            factor_weights={"value": 1.0},
            max_output=3,
        ),
    )
    config = ScreeningRuntimeConfig(
        strategies_dir=SCREENING_ROOT / "strategies",
        daily_enrich_enabled=True,
        daily_history_cache_dir=Path("/tmp/daily-history-cache"),
        daily_history_cache_ttl_hours=6,
        post_analyzers=[],
        risk_enabled=False,
        portfolio_diversity_enabled=False,
    )
    captured: dict[str, object] = {}

    def fake_enrich_daily_features(df: pd.DataFrame, **kwargs):
        captured.update(kwargs)
        enriched = df.copy()
        enriched["daily_source"] = "cache"
        enriched.attrs["daily_errors"] = []
        enriched.attrs["daily_success_count"] = len(enriched)
        enriched.attrs["daily_source_counts"] = {"cache": len(enriched)}
        enriched.attrs["daily_quality_flag_counts"] = {}
        enriched.attrs["daily_source_order_notes"] = []
        enriched.attrs["daily_source_health"] = {}
        return enriched

    monkeypatch.setattr(screening_pipeline, "load_all_strategies", lambda _path: {"demo": strategy})
    monkeypatch.setattr(screening_pipeline, "fetch_snapshot_with_fallback", lambda *args, **kwargs: snapshot_df.copy())
    monkeypatch.setattr(screening_pipeline, "apply_hard_filters", lambda df, _filters: df.copy())
    monkeypatch.setattr(
        screening_pipeline,
        "compute_screen_scores",
        lambda df, _screening: df.assign(screen_score=88.0),
    )
    monkeypatch.setattr(screening_pipeline, "enrich_daily_features", fake_enrich_daily_features)
    monkeypatch.setattr(screening_pipeline, "apply_dsa_provider_context", lambda picks, _context: [])
    monkeypatch.setattr(screening_pipeline, "apply_risk_overlay", lambda picks, **kwargs: (picks, []))
    monkeypatch.setattr(screening_pipeline, "apply_portfolio_overlay", lambda picks, **kwargs: (picks, []))
    monkeypatch.setattr(screening_pipeline, "run_post_analyzers", lambda picks, **kwargs: (picks, []))

    result = screening_pipeline.screen("demo", use_llm=False, config=config)

    assert captured["cache_dir"] == Path("/tmp/daily-history-cache")
    assert captured["cache_ttl_seconds"] == 6 * 60 * 60
    assert result.daily_enriched is True


def test_pipeline_uses_ranker_success_flag_instead_of_partial_llm_scores(monkeypatch) -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "code": "000001",
                "name": "Ping An",
                "price": 10.0,
                "change_pct": 1.2,
                "amount": 200_000_000.0,
            }
        ]
    )
    snapshot_df.attrs.update({
        "snapshot_source": "sina",
        "source_errors": [],
        "fallback_used": False,
    })
    strategy = Strategy(
        name="demo",
        display_name="Demo",
        description="demo",
        screening=ScreeningConfig(
            enabled=True,
            market_scope=["cn"],
            hard_filters=HardFilterConfig(),
            factor_weights={"value": 1.0},
            max_output=3,
        ),
    )
    config = ScreeningRuntimeConfig(
        strategies_dir=SCREENING_ROOT / "strategies",
        llm_model="openai/gpt-5-mini",
        llm_api_key="test-key",
        post_analyzers=[],
        risk_enabled=False,
        portfolio_diversity_enabled=False,
    )

    def fake_ranker(picks, *_args, **_kwargs):
        leaked_pick = picks[0]
        leaked_pick.llm_score = 99.0
        return SimpleNamespace(
            picks=picks,
            ranked=False,
            market_view="",
            selection_logic="",
            portfolio_risk="",
            coverage=0.5,
            errors=["coverage below threshold"],
        )

    monkeypatch.setattr(screening_pipeline, "load_all_strategies", lambda _path: {"demo": strategy})
    monkeypatch.setattr(screening_pipeline, "fetch_snapshot_with_fallback", lambda *args, **kwargs: snapshot_df.copy())
    monkeypatch.setattr(screening_pipeline, "apply_hard_filters", lambda df, _filters: df.copy())
    monkeypatch.setattr(
        screening_pipeline,
        "compute_screen_scores",
        lambda df, _screening: df.assign(screen_score=88.0),
    )
    monkeypatch.setattr(screening_pipeline, "apply_dsa_provider_context", lambda picks, _context: [])
    monkeypatch.setattr(screening_pipeline, "rank_candidates_with_metadata", fake_ranker)
    monkeypatch.setattr(screening_pipeline, "apply_risk_overlay", lambda picks, **kwargs: (picks, []))
    monkeypatch.setattr(screening_pipeline, "apply_portfolio_overlay", lambda picks, **kwargs: (picks, []))
    monkeypatch.setattr(screening_pipeline, "run_post_analyzers", lambda picks, **kwargs: (picks, []))

    result = screening_pipeline.screen("demo", use_llm=True, config=config)

    assert result.llm_ranked is False
    assert result.picks[0].llm_score is None
    assert result.picks[0].final_score == result.picks[0].screen_score
    assert "LLM ranking failed: fell back to screen_score" in result.degradation


def test_dsa_provider_context_respects_host_max_candidates_setting() -> None:
    picks = [
        Pick(rank=index + 1, code=f"00000{index + 1}", name=f"Stock {index + 1}", final_score=90.0, screen_score=90.0)
        for index in range(5)
    ]
    requested_codes: list[str] = []

    def get_candidate_context(code: str, _name: str) -> dict[str, object]:
        requested_codes.append(code)
        return {"enriched": True, "quote": {"price": 10.0}}

    notes = apply_dsa_provider_context(
        picks,
        {"dsa": {"max_candidates": 3, "get_candidate_context": get_candidate_context}},
    )

    assert requested_codes == ["000001", "000002", "000003"]
    assert all(pick.dsa_context.get("enriched") is True for pick in picks[:3])
    assert all(pick.dsa_context == {} for pick in picks[3:])
    assert notes == ["DSA provider context applied 3 of 3 candidates"]


def test_hard_filter_and_factor_scoring_keep_core_semantics() -> None:
    frame = pd.DataFrame(
        [
            {
                "code": "low_value",
                "name": "Low Value",
                "price": 10.0,
                "amount": 200_000_000,
                "pe_ratio": 5.0,
                "pb_ratio": 0.6,
                "turnover_rate": 2.0,
                "volume_ratio": 1.2,
                "change_pct": 0.0,
            },
            {
                "code": "high_value",
                "name": "High Value",
                "price": 10.0,
                "amount": 20_000_000,
                "pe_ratio": 15.0,
                "pb_ratio": 2.0,
                "turnover_rate": 2.0,
                "volume_ratio": 1.2,
                "change_pct": 0.0,
            },
        ]
    )

    filtered = apply_hard_filters(frame, HardFilterConfig(amount_min=100_000_000))
    assert filtered["code"].tolist() == ["low_value"]

    scored = compute_screen_scores(
        frame,
        ScreeningConfig(factor_weights={"value": 1.0}),
    ).set_index("code")
    assert scored.loc["low_value", "screen_score"] > scored.loc["high_value", "screen_score"]


def test_snapshot_schema_mismatch_counts_toward_source_circuit_breaker(
    monkeypatch,
) -> None:
    bad_snapshot = pd.DataFrame([{"code": "000001", "name": "Ping An", "price": 10.0}])
    good_snapshot = pd.DataFrame(
        [{"code": "000001", "name": "Ping An", "price": 10.0, "volume_ratio": 1.5}]
    )
    source_health: dict[str, dict[str, object]] = {}
    calls: list[str] = []

    def fake_fetch(source: str) -> pd.DataFrame:
        calls.append(source)
        if source == "sina":
            return bad_snapshot
        if source == "efinance":
            return good_snapshot.copy()
        raise AssertionError(f"unexpected source {source}")

    monkeypatch.setattr(screening_snapshot, "_SOURCE_HEALTH", source_health)
    monkeypatch.setattr(screening_snapshot, "fetch_cn_snapshot", fake_fetch)

    for _ in range(3):
        result = screening_snapshot.fetch_snapshot_with_fallback(
            ["sina", "efinance"],
            required_columns=["volume_ratio"],
        )
        assert result.attrs["snapshot_source"] == "efinance"

    health = screening_snapshot.snapshot_source_health_snapshot(["sina"])
    assert health["sina"]["failures"] == 3
    assert health["sina"]["disabled"] is True

    calls.clear()
    result = screening_snapshot.fetch_snapshot_with_fallback(
        ["sina", "efinance"],
        required_columns=["volume_ratio"],
    )

    assert calls == ["efinance"]
    assert result.attrs["snapshot_source"] == "efinance"
    assert "temporarily disabled" in result.attrs["source_errors"][0]


def test_sina_snapshot_uses_timeout_wrapper(monkeypatch) -> None:
    expected = pd.DataFrame([{"code": "000001"}])
    captured: dict[str, object] = {}

    def fake_wrapper(fetcher, *, source: str) -> pd.DataFrame:
        captured["fetcher"] = fetcher
        captured["source"] = source
        return expected

    monkeypatch.setattr(screening_snapshot, "_call_snapshot_wrapper", fake_wrapper)
    monkeypatch.setattr(screening_snapshot, "_fetch_sina", lambda: expected)

    result = screening_snapshot.fetch_cn_snapshot("sina")

    assert result is expected
    assert captured["source"] == "sina"
    assert captured["fetcher"] is screening_snapshot._fetch_sina


def test_em_datacenter_snapshot_uses_timeout_wrapper(monkeypatch) -> None:
    expected = pd.DataFrame([{"code": "000001"}])
    captured: dict[str, object] = {}

    def fake_wrapper(fetcher, *, source: str) -> pd.DataFrame:
        captured["fetcher"] = fetcher
        captured["source"] = source
        return expected

    monkeypatch.setattr(screening_snapshot, "_call_snapshot_wrapper", fake_wrapper)
    monkeypatch.setattr(screening_snapshot, "_fetch_em_datacenter", lambda: expected)

    result = screening_snapshot.fetch_cn_snapshot("em_datacenter")

    assert result is expected
    assert captured["source"] == "em_datacenter"
    assert captured["fetcher"] is screening_snapshot._fetch_em_datacenter


def test_em_datacenter_timeout_falls_back_to_last_good_snapshot(tmp_path, monkeypatch) -> None:
    cached = pd.DataFrame(
        [{"code": "000001", "name": "Ping An", "price": 10.0, "volume_ratio": 1.5}]
    )
    cached.attrs["snapshot_source"] = "cached:last_good"
    cache_path = tmp_path / "snapshot-cache.json"
    screening_snapshot._write_last_good_snapshot(cache_path, cached)

    def fake_wrapper(fetcher, *, source: str) -> pd.DataFrame:
        assert source == "em_datacenter"
        assert fetcher is screening_snapshot._fetch_em_datacenter
        raise RuntimeError("snapshot source em_datacenter timed out")

    monkeypatch.setattr(screening_snapshot, "_call_snapshot_wrapper", fake_wrapper)

    result = screening_snapshot.fetch_snapshot_with_fallback(
        ["em_datacenter"],
        required_columns=["volume_ratio"],
        fallback_snapshot_path=cache_path,
    )

    assert result.attrs["fallback_used"] is True
    assert result.attrs["snapshot_source"] == "last_good_cache"
    assert result.loc[0, "code"] == "000001"
