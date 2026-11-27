# -*- coding: utf-8 -*-
"""Offline tests for quantitative strategy metadata exposure on screening routes."""

from __future__ import annotations

import math
import os
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from api.v1.endpoints.screening import router as screening_router
from src.config import Config
from src.services.screening.filter import check_hard_filters
from src.services.screening.models import HardFilterConfig, ScreeningConfig, Strategy
from src.services.screening.scorer import normalized_factor_weights
from src.services.screening.strategy import list_strategies, load_strategy
from src.services.screening_service import ScreeningService, _normalize_strategy


def test_screening_strategies_exposes_factor_weights_filters_and_style_offline() -> None:
    cfg = Config(screening_enabled=True)
    payload = ScreeningService(config=cfg).strategies()
    assert payload["enabled"] is True
    assert payload["strategy_count"] >= 10

    by_id = {item["id"]: item for item in payload["strategies"]}
    assert "momentum_quality" in by_id
    mq = by_id["momentum_quality"]
    assert abs(sum(mq["factor_weights"].values()) - 1.0) < 0.01
    assert mq["factor_weights"]["momentum"] > 0.2
    assert len(mq["active_filters"]) > 0
    assert mq["style"]["risk_profile"] == "balanced"
    assert mq["style"]["holding_period"] == "swing"

    assert "low_volatility_quality" in by_id
    lvq = by_id["low_volatility_quality"]
    assert lvq["requires_daily_features"] is True
    assert lvq["style"]["risk_profile"] == "defensive"

    for item in payload["strategies"]:
        weights = item["factor_weights"]
        assert isinstance(weights, dict) and len(weights) > 0
        for weight_val in weights.values():
            assert isinstance(weight_val, (int, float))
            assert math.isfinite(weight_val) and weight_val >= 0
        style = item["style"]
        assert isinstance(style, dict)
        assert isinstance(style.get("risk_profile"), str) and style["risk_profile"]
        assert isinstance(style.get("holding_period"), str) and style["holding_period"]
        regimes = style.get("market_regime")
        assert isinstance(regimes, list) and len(regimes) >= 1


def test_normalize_strategy_sanitizes_bool_nonfinite_weights_and_scalar_market_regime() -> None:
    normalized = _normalize_strategy(
        {
            "id": "custom_quant",
            "name": "Custom Quant",
            "factor_weights": {
                "bad_bool": True,
                "bad_false": False,
                "bad_neg": -0.25,
                "bad_nan": float("nan"),
                "bad_inf": float("inf"),
                "momentum": 0.75,
            },
            "style": {
                "risk_profile": "balanced",
                "holding_period": "watchlist",
                "market_regime": "trend",
            },
        }
    )
    assert normalized["factor_weights"] == {"momentum": 1.0}
    assert normalized["style"]["market_regime"] == ["trend"]

    tiny = _normalize_strategy(
        {
            "id": "tiny_quant",
            "name": "Tiny Quant",
            "factor_weights": {"value": 0.00004, "momentum": 0.00006},
        }
    )
    assert tiny["factor_weights"]["value"] == pytest.approx(0.4)
    assert tiny["factor_weights"]["momentum"] == pytest.approx(0.6)

    camel_style = _normalize_strategy(
        {
            "id": "camel_quant",
            "name": "Camel Quant",
            "style": {"marketRegime": "rotation"},
        }
    )
    assert camel_style["style"]["market_regime"] == ["rotation"]
    assert "marketRegime" not in camel_style["style"]


def test_custom_yaml_strategies_expose_effective_normalized_weights_and_active_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "tiny_weights.yaml").write_text(
        """
name: tiny_weights
display_name: 微小权重策略
description: tiny positive weights
screening:
  enabled: true
  market_scope: [cn]
  hard_filters:
    exclude_st: false
    price_min: 10
    macd_status_whitelist: []
    rsi_status_whitelist: []
  factor_weights:
    value: 0.00004
    momentum: 0.00006
  max_output: 5
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "default_weights.yaml").write_text(
        """
name: default_weights
display_name: 默认权重策略
description: omitted factor weights fall back to scorer defaults
screening:
  enabled: true
  market_scope: [cn]
  tech_weight: 0.4
  hard_filters:
    exclude_st: false
  max_output: 5
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("STRATEGIES_DIR", str(tmp_path))
    cfg = Config(screening_enabled=True)
    payload = ScreeningService(config=cfg).strategies()
    by_id = {item["id"]: item for item in payload["strategies"]}

    tiny = by_id["tiny_weights"]
    assert tiny["factor_weights"]["value"] == pytest.approx(0.4)
    assert tiny["factor_weights"]["momentum"] == pytest.approx(0.6)
    assert tiny["active_filters"] == ["price_min"]
    snapshot_checks = check_hard_filters(
        {"price": 15.0},
        HardFilterConfig(
            exclude_st=False,
            price_min=10.0,
            macd_status_whitelist=[],
            rsi_status_whitelist=[],
        ),
    )
    assert [item["filter"] for item in snapshot_checks] == tiny["active_filters"]

    defaulted = by_id["default_weights"]
    assert defaulted["factor_weights"] == pytest.approx(
        normalized_factor_weights(ScreeningConfig(tech_weight=0.4))
    )
    assert defaulted["active_filters"] == []


def test_screening_strategies_endpoint_tolerates_legacy_minimal_strategy_dict() -> None:
    app = FastAPI()
    app.include_router(screening_router, prefix="/api/v1/screening")
    cfg = Config(screening_enabled=True)

    app.dependency_overrides = {}
    with (
        patch("api.v1.endpoints.screening.get_config_dep", return_value=cfg),
        patch("src.services.screening_service._ensure_screening_available_for_use"),
        patch(
            "src.services.screening_service.load_screening_strategies",
            return_value=[{"id": "legacy_one", "name": "旧版极简策略"}],
        ),
    ):
        from api.deps import get_config_dep

        app.dependency_overrides[get_config_dep] = lambda: cfg
        client = TestClient(app)
        resp = client.get("/api/v1/screening/strategies")

    assert resp.status_code == 200
    body = resp.json()
    assert body["strategy_count"] == 1
    item = body["strategies"][0]
    assert item["id"] == "legacy_one"
    assert item["factor_weights"] == {}
    assert item["active_filters"] == []
    assert item["requires_daily_features"] is False
    assert item["style"] == {}


def test_invalid_tech_weight_or_factor_weights_are_isolated_per_file_without_blocking_healthy_strategies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "healthy_quant.yaml").write_text(
        """
name: healthy_quant
display_name: 正常量化策略
description: healthy strategy alongside broken sibling configs
screening:
  enabled: true
  market_scope: [cn]
  tech_weight: 0.4
  hard_filters:
    exclude_st: false
    price_min: 10
  max_output: 5
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "quoted_numeric_weights.yaml").write_text(
        """
name: quoted_numeric_weights
display_name: 引号数字权重策略
description: valid quoted numeric weights remain backwards compatible
screening:
  enabled: true
  market_scope: [cn]
  tech_weight: "0.4"
  factor_weights:
    value: "0.6"
    momentum: 0.4
  max_output: 5
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "bad_tech_weight.yaml").write_text(
        """
name: bad_tech_weight
display_name: 错误字符串权重
description: invalid string tech_weight without factor_weights
screening:
  enabled: true
  market_scope: [cn]
  tech_weight: "not-a-number"
  max_output: 5
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "bad_tech_weight_nan.yaml").write_text(
        """
name: bad_tech_weight_nan
display_name: 非有限字符串权重
screening:
  enabled: true
  market_scope: [cn]
  tech_weight: "nan"
  max_output: 5
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "bad_factor_weight_str.yaml").write_text(
        """
name: bad_factor_weight_str
display_name: 错误因子权重字符串
screening:
  enabled: true
  market_scope: [cn]
  factor_weights:
    value: "bad"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "bad_factor_weight_inf.yaml").write_text(
        """
name: bad_factor_weight_inf
display_name: 无穷大因子权重
screening:
  enabled: true
  market_scope: [cn]
  factor_weights:
    value: "inf"
""".strip(),
        encoding="utf-8",
    )

    quoted = load_strategy(tmp_path / "quoted_numeric_weights.yaml")
    assert quoted.screening.tech_weight == pytest.approx(0.4)
    assert quoted.screening.factor_weights == pytest.approx({"value": 0.6, "momentum": 0.4})

    with pytest.raises(ValueError, match="tech_weight"):
        load_strategy(tmp_path / "bad_tech_weight.yaml")
    with pytest.raises(ValueError, match="tech_weight"):
        load_strategy(tmp_path / "bad_tech_weight_nan.yaml")
    with pytest.raises(ValueError, match="factor weight"):
        load_strategy(tmp_path / "bad_factor_weight_str.yaml")
    with pytest.raises(ValueError, match="factor weight"):
        load_strategy(tmp_path / "bad_factor_weight_inf.yaml")

    monkeypatch.setenv("STRATEGIES_DIR", str(tmp_path))
    cfg = Config(screening_enabled=True)
    service = ScreeningService(config=cfg)

    status_payload = service.status()
    assert status_payload["available"] is True
    assert status_payload["strategy_count"] == 2

    catalog_payload = service.strategies()
    assert catalog_payload["strategy_count"] == 2
    assert [s["id"] for s in catalog_payload["strategies"]] == ["healthy_quant", "quoted_numeric_weights"]
    assert catalog_payload["strategies"][0]["factor_weights"] == pytest.approx(
        normalized_factor_weights(ScreeningConfig(tech_weight=0.4))
    )
    assert catalog_payload["strategies"][1]["factor_weights"] == pytest.approx(
        {"value": 0.6, "momentum": 0.4}
    )

    app = FastAPI()
    app.include_router(screening_router, prefix="/api/v1/screening")
    from api.deps import get_config_dep

    app.dependency_overrides[get_config_dep] = lambda: cfg
    client = TestClient(app)
    check_resp = client.post(
        "/api/v1/screening/screen/check",
        json={"strategy": "quoted_numeric_weights", "market": "cn", "snapshot": {"price": 15.0, "name": "正常股"}},
    )
    assert check_resp.status_code == 200
    assert check_resp.json()["passed"] is True

    with patch(
        "src.services.screening_service._call_screening_screen",
        return_value={"candidates": [], "candidate_count": 0},
    ):
        screen_resp = service.screen(strategy="quoted_numeric_weights", market="cn", max_results=5)
    assert screen_resp["strategy"] == "quoted_numeric_weights"

    healthy_strategy = Strategy(
        name="healthy_in_memory",
        display_name="Healthy",
        description="valid",
        screening=ScreeningConfig(enabled=True, tech_weight=0.4),
    )
    broken_strategy = Strategy(
        name="broken_in_memory",
        display_name="Broken",
        description="invalid",
        screening=ScreeningConfig(enabled=True, tech_weight="not-a-number"),  # type: ignore[arg-type]
    )
    with patch(
        "src.services.screening.strategy.load_all_strategies",
        return_value={"healthy_in_memory": healthy_strategy, "broken_in_memory": broken_strategy},
    ):
        listed = list_strategies(tmp_path)
    assert [item.name for item in listed] == ["healthy_in_memory"]


def test_load_strategy_ignores_invalid_legacy_tech_weight_when_factor_weights_configured(
    tmp_path: Path,
) -> None:
    legacy_path = tmp_path / "legacy_custom.yaml"
    legacy_path.write_text(
        """
name: legacy_custom
display_name: Legacy Factor Strategy
description: custom factor weights override legacy tech_weight
screening:
  enabled: true
  market_scope: [cn]
  tech_weight: "not-used"
  factor_weights:
    value: 0.6
    momentum: 0.4
  max_output: 5
""".strip(),
        encoding="utf-8",
    )
    loaded = load_strategy(legacy_path)
    assert loaded.screening.tech_weight == pytest.approx(0.35)
    assert normalized_factor_weights(loaded.screening) == pytest.approx(
        {"value": 0.6, "momentum": 0.4}
    )

    invalid_no_weights = tmp_path / "empty_weights_bad_tech.yaml"
    invalid_no_weights.write_text(
        """
name: empty_weights_bad_tech
display_name: Invalid Tech Weight Strategy
description: empty factor weights should reject invalid tech_weight
screening:
  enabled: true
  market_scope: [cn]
  tech_weight: "not-used"
  factor_weights: {}
  max_output: 5
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="tech_weight"):
        load_strategy(invalid_no_weights)


def test_load_strategy_preserves_exact_factor_weight_keys_without_whitespace_overwrite(
    tmp_path: Path,
) -> None:
    strategy_path = tmp_path / "whitespace_factor_key.yaml"
    strategy_path.write_text(
        """
name: whitespace_factor_key
display_name: Exact Key Strategy
description: whitespace-suffixed unknown key must not overwrite valid value weight
screening:
  enabled: true
  market_scope: [cn]
  factor_weights:
    value: 0.8
    "value ": 0.2
    momentum: 0.2
  max_output: 5
""".strip(),
        encoding="utf-8",
    )
    loaded = load_strategy(strategy_path)
    assert loaded.screening.factor_weights["value"] == pytest.approx(0.8)
    assert loaded.screening.factor_weights["value "] == pytest.approx(0.2)
    assert normalized_factor_weights(loaded.screening) == pytest.approx(
        {"value": 0.8, "momentum": 0.2}
    )


def test_load_strategy_handles_oversized_integer_tech_weight_overflow(
    tmp_path: Path,
) -> None:
    huge_int = "1" + "0" * 309

    idle_overflow = tmp_path / "overflow_with_weights.yaml"
    idle_overflow.write_text(
        f"""
name: overflow_with_weights
display_name: Idle Overflow Tech Weight
screening:
  enabled: true
  market_scope: [cn]
  tech_weight: {huge_int}
  factor_weights:
    value: 0.7
    momentum: 0.3
""".strip(),
        encoding="utf-8",
    )
    loaded = load_strategy(idle_overflow)
    assert loaded.screening.tech_weight == pytest.approx(0.35)
    assert loaded.screening.factor_weights == pytest.approx({"value": 0.7, "momentum": 0.3})
    assert [item.name for item in list_strategies(tmp_path)] == ["overflow_with_weights"]

    active_overflow = tmp_path / "overflow_no_weights.yaml"
    active_overflow.write_text(
        f"""
name: overflow_no_weights
display_name: Active Overflow Tech Weight
screening:
  enabled: true
  market_scope: [cn]
  tech_weight: {huge_int}
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="tech_weight"):
        load_strategy(active_overflow)

    factor_overflow = tmp_path / "overflow_factor_weight.yaml"
    factor_overflow.write_text(
        f"""
name: overflow_factor_weight
display_name: Overflow Factor Weight
screening:
  enabled: true
  market_scope: [cn]
  factor_weights:
    value: {huge_int}
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="factor weight"):
        load_strategy(factor_overflow)


def test_load_strategy_accepts_yaml_bool_weights_and_catalog_loads_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bool_weights = tmp_path / "bool_weights.yaml"
    bool_weights.write_text(
        """
name: bool_weights
display_name: YAML Bool Weights
screening:
  enabled: true
  market_scope: [cn]
  tech_weight: false
  factor_weights:
    stability: off
    value: true
""".strip(),
        encoding="utf-8",
    )
    loaded = load_strategy(bool_weights)
    assert loaded.screening.tech_weight == pytest.approx(0.0)
    assert loaded.screening.factor_weights == pytest.approx({"stability": 0.0, "value": 1.0})
    assert normalized_factor_weights(loaded.screening) == pytest.approx(
        {"stability": 0.0, "value": 1.0}
    )

    bool_tech_only = tmp_path / "bool_tech_weight_only.yaml"
    bool_tech_only.write_text(
        """
name: bool_tech_weight_only
display_name: YAML Bool Tech Weight Only
screening:
  enabled: true
  market_scope: [cn]
  tech_weight: true
""".strip(),
        encoding="utf-8",
    )
    loaded_tech_only = load_strategy(bool_tech_only)
    assert loaded_tech_only.screening.tech_weight == pytest.approx(1.0)

    assert normalized_factor_weights(loaded_tech_only.screening) == pytest.approx(
        {"value": 0.0, "liquidity": 0.0, "stability": 0.0, "momentum": 0.55, "activity": 0.45}
    )

    monkeypatch.setenv("STRATEGIES_DIR", str(tmp_path))
    service = ScreeningService(config=Config(screening_enabled=True))
    catalog = service.strategies()
    assert catalog["strategy_count"] == 2
    by_id = {item["id"]: item for item in catalog["strategies"]}
    assert by_id["bool_weights"]["factor_weights"] == pytest.approx({"value": 1.0})
    assert by_id["bool_tech_weight_only"]["factor_weights"] == pytest.approx(
        {"momentum": 0.55, "activity": 0.45}
    )


def test_load_strategy_and_scorer_ignore_unknown_or_empty_factor_weight_placeholders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pandas as pd
    from src.services.screening.scorer import compute_screen_scores

    placeholder_path = tmp_path / "placeholder_weights.yaml"
    placeholder_path.write_text(
        """
name: placeholder_weights
display_name: Legacy Placeholder Weights
screening:
  enabled: true
  market_scope: [cn]
  factor_weights:
    value: 0.6
    momentum: 0.4
    "": 0
    legacy_note: "keep-ignored"
""".strip(),
        encoding="utf-8",
    )
    baseline_path = tmp_path / "baseline_weights.yaml"
    baseline_path.write_text(
        """
name: baseline_weights
display_name: Baseline Weights
screening:
  enabled: true
  market_scope: [cn]
  factor_weights:
    value: 0.6
    momentum: 0.4
""".strip(),
        encoding="utf-8",
    )

    loaded_placeholder = load_strategy(placeholder_path)
    loaded_baseline = load_strategy(baseline_path)
    assert normalized_factor_weights(loaded_placeholder.screening) == pytest.approx(
        {"value": 0.6, "momentum": 0.4}
    )

    df = pd.DataFrame([
        {
            "code": "600519", "name": "A", "price": 100.0, "change_pct": 3.0,
            "volume_ratio": 1.8, "turnover_rate": 2.5, "pe_ratio": 15.0, "pb_ratio": 2.5,
            "total_mv": 5e10, "circ_mv": 4e10, "amount": 5e8, "ma_bullish": True,
            "rsi_6": 55.0, "macd_hist": 0.5, "change_60d": 12.0, "volatility_60d": 20.0,
            "max_drawdown_60d": -5.0,
        },
        {
            "code": "000001", "name": "B", "price": 12.0, "change_pct": -1.5,
            "volume_ratio": 0.9, "turnover_rate": 1.2, "pe_ratio": 45.0, "pb_ratio": 5.0,
            "total_mv": 1e10, "circ_mv": 8e9, "amount": 1e8, "ma_bullish": False,
            "rsi_6": 42.0, "macd_hist": -0.2, "change_60d": -6.0, "volatility_60d": 35.0,
            "max_drawdown_60d": -15.0,
        },
    ])
    scored_placeholder = compute_screen_scores(df, loaded_placeholder.screening)
    scored_baseline = compute_screen_scores(df, loaded_baseline.screening)
    assert scored_placeholder["screen_score"].iloc[0] != scored_placeholder["screen_score"].iloc[1]
    assert scored_placeholder["screen_score"].tolist() == pytest.approx(
        scored_baseline["screen_score"].tolist()
    )

    invalid_path = tmp_path / "invalid_weights.yaml"
    invalid_path.write_text(
        """
name: invalid_weights
display_name: Invalid Factor Weight
screening:
  enabled: true
  market_scope: [cn]
  factor_weights:
    value: "not-a-number"
    momentum: 0.4
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_strategy(invalid_path)

    monkeypatch.setenv("STRATEGIES_DIR", str(tmp_path))
    catalog = ScreeningService(config=Config(screening_enabled=True)).strategies()
    by_id = {item["id"]: item for item in catalog["strategies"]}
    assert "placeholder_weights" in by_id
    assert by_id["placeholder_weights"]["factor_weights"] == pytest.approx(
        {"value": 0.6, "momentum": 0.4}
    )

    from src.services.screening import pipeline as screening_pipeline
    from src.services.screening.config import Config as RuntimeConfig

    snapshot_df = df.copy()
    snapshot_df.attrs.update({
        "snapshot_source": "test_snapshot",
        "source_errors": [],
        "fallback_used": False,
    })
    runtime_cfg = RuntimeConfig(
        strategies_dir=tmp_path,
        daily_enrich_enabled=False,
        post_analyzers=[],
        risk_enabled=False,
        portfolio_diversity_enabled=False,
    )
    monkeypatch.setattr(screening_pipeline, "fetch_snapshot_with_fallback", lambda *args, **kwargs: snapshot_df.copy())
    monkeypatch.setattr(screening_pipeline, "apply_dsa_provider_context", lambda picks, _ctx: [])

    placeholder_result = screening_pipeline.screen(
        "placeholder_weights",
        market="cn",
        use_llm=False,
        config=runtime_cfg,
    )
    baseline_result = screening_pipeline.screen(
        "baseline_weights",
        market="cn",
        use_llm=False,
        config=runtime_cfg,
    )
    assert [pick.code for pick in placeholder_result.picks] == [pick.code for pick in baseline_result.picks]
    assert [pick.screen_score for pick in placeholder_result.picks] == pytest.approx(
        [pick.screen_score for pick in baseline_result.picks]
    )


def test_pipeline_screen_preserves_tie_break_order_when_only_unknown_factor_weights(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pandas as pd
    from src.services.screening import pipeline as screening_pipeline
    from src.services.screening.config import Config as RuntimeConfig

    (tmp_path / "only_unknown_weights.yaml").write_text(
        """
name: only_unknown_weights
display_name: Only Unknown Numeric Weights
screening:
  enabled: true
  market_scope: [cn]
  max_output: 1
  factor_weights:
    legacy_note: 1
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "empty_weights.yaml").write_text(
        """
name: empty_weights
display_name: Empty Factor Weights
screening:
  enabled: true
  market_scope: [cn]
  max_output: 1
""".strip(),
        encoding="utf-8",
    )

    snapshot_df = pd.DataFrame([
        {
            "code": "600519", "name": "HighStab", "price": 100.0, "change_pct": 0.0,
            "volume_ratio": 1.0, "turnover_rate": 2.0, "pe_ratio": 20.0, "pb_ratio": 3.0,
            "total_mv": 5e10, "circ_mv": 4e10, "amount": 5e8,
        },
        {
            "code": "000001", "name": "LowStab", "price": 12.0, "change_pct": 0.0,
            "volume_ratio": 1.0, "turnover_rate": 2.0, "pe_ratio": 20.0, "pb_ratio": 3.0,
            "total_mv": 5e10, "circ_mv": 4e10, "amount": 5e8,
        },
    ])
    snapshot_df.attrs.update({
        "snapshot_source": "test_snapshot",
        "source_errors": [],
        "fallback_used": False,
    })

    def fake_compute_scores(frame: pd.DataFrame, _screening) -> pd.DataFrame:
        scored = frame.copy()
        scored["factor_value_score"] = 50.0
        scored["factor_liquidity_score"] = 50.0
        scored["factor_momentum_score"] = 50.0
        scored["factor_activity_score"] = 50.0
        scored["factor_stability_score"] = [78.0 if code == "600519" else 69.0 for code in scored["code"]]
        scored["screen_score"] = 50.0
        return scored

    runtime_cfg = RuntimeConfig(
        strategies_dir=tmp_path,
        daily_enrich_enabled=False,
        post_analyzers=[],
        risk_enabled=False,
        portfolio_diversity_enabled=False,
    )
    monkeypatch.setattr(screening_pipeline, "fetch_snapshot_with_fallback", lambda *args, **kwargs: snapshot_df.copy())
    monkeypatch.setattr(screening_pipeline, "compute_screen_scores", fake_compute_scores)
    monkeypatch.setattr(screening_pipeline, "apply_dsa_provider_context", lambda picks, _ctx: [])

    # Explicit non-empty factor_weights with only unknown keys falls back to [screen_score, code].
    unknown_only_result = screening_pipeline.screen(
        "only_unknown_weights",
        market="cn",
        use_llm=False,
        config=runtime_cfg,
    )
    assert [pick.code for pick in unknown_only_result.picks] == ["000001"]

    # Unconfigured factor_weights retains the default [stability, activity, momentum, value] tie-breaker.
    empty_result = screening_pipeline.screen(
        "empty_weights",
        market="cn",
        use_llm=False,
        config=runtime_cfg,
    )
    assert [pick.code for pick in empty_result.picks] == ["600519"]


def test_pipeline_screen_ignores_zero_and_negative_known_factor_weights_in_tie_break(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pandas as pd
    from src.services.screening import pipeline as screening_pipeline
    from src.services.screening.config import Config as RuntimeConfig

    (tmp_path / "zero_known_weights.yaml").write_text(
        """
name: zero_known_weights
display_name: Zero Known Factor Weights
screening:
  enabled: true
  market_scope: [cn]
  max_output: 1
  factor_weights:
    value: 0
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "negative_and_zero_weights.yaml").write_text(
        """
name: negative_and_zero_weights
display_name: Negative And Zero Factor Weights
screening:
  enabled: true
  market_scope: [cn]
  max_output: 1
  factor_weights:
    value: -1
    momentum: 0
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "mixed_positive_and_nonpositive_weights.yaml").write_text(
        """
name: mixed_positive_and_nonpositive_weights
display_name: Mixed Positive And Nonpositive Factor Weights
screening:
  enabled: true
  market_scope: [cn]
  max_output: 1
  factor_weights:
    value: 0
    momentum: -0.5
    stability: 0.6
""".strip(),
        encoding="utf-8",
    )

    snapshot_df = pd.DataFrame([
        {
            "code": "600519", "name": "HighZeroVal", "price": 100.0, "change_pct": 0.0,
            "volume_ratio": 1.0, "turnover_rate": 2.0, "pe_ratio": 20.0, "pb_ratio": 3.0,
            "total_mv": 5e10, "circ_mv": 4e10, "amount": 5e8,
        },
        {
            "code": "000001", "name": "LowZeroVal", "price": 12.0, "change_pct": 0.0,
            "volume_ratio": 1.0, "turnover_rate": 2.0, "pe_ratio": 20.0, "pb_ratio": 3.0,
            "total_mv": 5e10, "circ_mv": 4e10, "amount": 5e8,
        },
    ])
    snapshot_df.attrs.update({
        "snapshot_source": "test_snapshot",
        "source_errors": [],
        "fallback_used": False,
    })

    stability_scores = {"value": [40.0, 80.0]}

    def fake_compute_scores(frame: pd.DataFrame, _screening) -> pd.DataFrame:
        scored = frame.copy()
        scored["factor_value_score"] = [80.0 if code == "600519" else 20.0 for code in scored["code"]]
        scored["factor_liquidity_score"] = 50.0
        scored["factor_momentum_score"] = [90.0 if code == "600519" else 20.0 for code in scored["code"]]
        scored["factor_activity_score"] = 50.0
        scored["factor_stability_score"] = [
            stability_scores["value"][0] if code == "600519" else stability_scores["value"][1]
            for code in scored["code"]
        ]
        scored["screen_score"] = 50.0
        return scored

    runtime_cfg = RuntimeConfig(
        strategies_dir=tmp_path,
        daily_enrich_enabled=False,
        post_analyzers=[],
        risk_enabled=False,
        portfolio_diversity_enabled=False,
    )
    monkeypatch.setattr(screening_pipeline, "fetch_snapshot_with_fallback", lambda *args, **kwargs: snapshot_df.copy())
    monkeypatch.setattr(screening_pipeline, "compute_screen_scores", fake_compute_scores)
    monkeypatch.setattr(screening_pipeline, "apply_dsa_provider_context", lambda picks, _ctx: [])

    # Known factor_weights with only zero or negative weights fall back to [screen_score, code] tie-break.
    zero_result = screening_pipeline.screen(
        "zero_known_weights",
        market="cn",
        use_llm=False,
        config=runtime_cfg,
    )
    assert [pick.code for pick in zero_result.picks] == ["000001"]

    negative_result = screening_pipeline.screen(
        "negative_and_zero_weights",
        market="cn",
        use_llm=False,
        config=runtime_cfg,
    )
    assert [pick.code for pick in negative_result.picks] == ["000001"]

    # Mixed positive and non-positive weights only use positive weights (stability) for tie-breaking.
    mixed_first = screening_pipeline.screen(
        "mixed_positive_and_nonpositive_weights",
        market="cn",
        use_llm=False,
        config=runtime_cfg,
    )
    assert [pick.code for pick in mixed_first.picks] == ["000001"]

    stability_scores["value"] = [85.0, 40.0]
    mixed_reverse = screening_pipeline.screen(
        "mixed_positive_and_nonpositive_weights",
        market="cn",
        use_llm=False,
        config=runtime_cfg,
    )
    assert [pick.code for pick in mixed_reverse.picks] == ["600519"]
