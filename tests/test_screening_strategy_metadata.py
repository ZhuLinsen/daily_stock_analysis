# -*- coding: utf-8 -*-
"""Offline tests for quantitative strategy metadata exposure on screening routes."""

from __future__ import annotations

import math
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.endpoints.screening import router as screening_router
from src.config import Config
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
    assert normalized["factor_weights"] == {"momentum": 0.75}
    assert normalized["style"]["market_regime"] == ["trend"]

    camel_style = _normalize_strategy(
        {
            "id": "camel_quant",
            "name": "Camel Quant",
            "style": {"marketRegime": "rotation"},
        }
    )
    assert camel_style["style"]["market_regime"] == ["rotation"]
    assert "marketRegime" not in camel_style["style"]


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
