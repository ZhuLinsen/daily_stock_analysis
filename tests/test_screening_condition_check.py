# -*- coding: utf-8 -*-
"""Offline contracts for checking every filter on a caller-supplied row."""

from dataclasses import fields, replace
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient

from api.deps import get_config_dep
from api.middlewares.error_handler import add_error_handlers
from api.v1.endpoints import screening
from src.config import Config
from src.services.screening.filter import apply_hard_filters, check_hard_filters
from src.services.screening.models import HardFilterConfig
from src.services.screening.strategy import load_all_strategies


STRATEGIES = Path(__file__).resolve().parents[1] / "src/services/screening/strategies"
SNAPSHOT = {
    "code": "600000", "name": "Example", "amount": 100000000, "price": 10,
    "total_mv": 10000000000, "pe_ratio": 8, "pb_ratio": 1, "change_pct": 0,
}
ALL_FIELDS = {
    "name": "Example", "price": 5, "amount": 5, "total_mv": 5,
    "pe_ratio": 5, "pb_ratio": 5, "volume_ratio": 5, "turnover_rate": 5,
    "change_pct": 5, "change_60d": 5, "ma_bullish": True,
    "price_above_ma20": True, "signal_score": 5, "macd_status": "bullish",
    "rsi_status": "bullish", "breakout_20d_pct": 5, "range_20d_pct": 5,
    "volume_ratio_20d": 5, "body_pct": 5, "pullback_to_ma20_pct": 5,
    "consolidation_days_20d": 5, "volatility_20d_pct": 5,
    "max_drawdown_20d_pct": 5, "atr_20_pct": 5,
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STRATEGIES_DIR", str(STRATEGIES))
    app = FastAPI()
    app.include_router(screening.router, prefix="/api/v1/screening")
    add_error_handlers(app)
    app.dependency_overrides[get_config_dep] = lambda: Config(screening_enabled=True)
    with FastAPITestClient(app) as client:
        yield client


def test_all_conditions_reuse_pipeline_predicates_without_short_circuit():
    thresholds = {}
    for field in fields(HardFilterConfig):
        if field.name.endswith("_min"):
            thresholds[field.name] = 0
        elif field.name.endswith("_max"):
            thresholds[field.name] = 10
        elif field.name.endswith("_whitelist"):
            thresholds[field.name] = ["bullish"]
        else:
            thresholds[field.name] = True
    filters = HardFilterConfig(**thresholds)
    checks = check_hard_filters(ALL_FIELDS, filters)
    assert len(checks) == len(fields(HardFilterConfig))
    assert all(item["status"] == "pass" for item in checks)
    assert [item["filter"] for item in checks] == list(thresholds)
    assert not apply_hard_filters(pd.DataFrame([ALL_FIELDS]), filters).empty
    rejected = {**ALL_FIELDS, "name": "ST Example", "atr_20_pct": 20}
    checks = check_hard_filters(rejected, filters)
    assert checks[0]["status"] == "fail"
    assert checks[-1]["status"] == "fail"
    assert checks[-1]["current_value"] == 20
    assert len(checks) == len(thresholds)
    assert apply_hard_filters(pd.DataFrame([rejected]), filters).empty
    for item in checks:
        isolated = replace(HardFilterConfig(exclude_st=False), **{item["filter"]: item["threshold"]})
        assert item["passed"] == (not apply_hard_filters(pd.DataFrame([rejected]), isolated).empty)


def test_numeric_aliases_and_zero_thresholds_preserve_pipeline_semantics():
    row = {"名称": "Example", "最新价": "0", "总市值": "100", "市盈率": "8", "市净率": "1"}
    filters = HardFilterConfig(price_min=0, price_max=0, market_cap_min=100, pe_ttm_max=8, pb_min=1)
    checks = check_hard_filters(row, filters)
    assert len(checks) == 6
    assert all(item["passed"] for item in checks)
    assert checks[1]["source_field"] == "最新价"
    assert checks[1]["current_value"] == 0
    assert checks[1]["threshold"] == 0
    assert not apply_hard_filters(pd.DataFrame([row]), filters).empty
    # The canonical column wins even when an alias contains a passing value.
    checks = check_hard_filters({**row, "price": -1}, filters)
    assert checks[1]["status"] == "fail"


@pytest.mark.parametrize("value", [None, "", " ", "bad", "NaN", "Infinity", float("nan"), float("inf"), -float("inf")])
def test_unusable_numbers_are_missing_and_json_safe(value):
    checks = check_hard_filters({"price": value}, HardFilterConfig(price_min=0, price_max=10))
    assert [item["status"] for item in checks] == ["missing", "missing", "missing"]
    assert all(item["current_value"] is None and item["passed"] is None for item in checks)
    json.dumps(checks, allow_nan=False)


def test_inactive_filters_are_not_reported_and_input_is_not_mutated():
    row = dict(SNAPSHOT)
    assert check_hard_filters(row, HardFilterConfig(exclude_st=False, macd_status_whitelist=[])) == []
    assert row == SNAPSHOT


def test_daily_features_are_missing_without_fetching():
    filters = HardFilterConfig(exclude_st=False, require_ma_bullish=True, macd_status_whitelist=["bullish"])
    checks = check_hard_filters({"code": "600000"}, filters)
    assert [item["filter"] for item in checks] == ["require_ma_bullish", "macd_status_whitelist"]
    assert all(item["status"] == "missing" for item in checks)
    checks = check_hard_filters({"ma_bullish": False, "macd_status": "bearish"}, filters)
    assert all(item["status"] == "fail" for item in checks)


def test_check_endpoint_is_deterministic_and_does_not_run_screening(client):
    with patch.object(screening.ScreeningService, "screen", side_effect=AssertionError("must not screen")), patch(
        "src.services.screening.snapshot.fetch_snapshot_with_fallback", side_effect=AssertionError("must not fetch")
    ):
        response = client.post("/api/v1/screening/screen/check", json={"snapshot": SNAPSHOT})
        again = client.post("/api/v1/screening/screen/check", json={"snapshot": SNAPSHOT})
    assert response.status_code == 200
    body = response.json()
    assert body == again.json()
    assert body["provenance"] == "supplied_snapshot"
    assert body["passed"] is True
    assert body["strategy"] == "dual_low"
    assert body["strategy_version"] == "1.2"
    expected = load_all_strategies(STRATEGIES)["dual_low"].screening.hard_filters
    assert body["checks"] == check_hard_filters(SNAPSHOT, expected)
    assert "snapshot_source" not in body and "run_id" not in body


def test_endpoint_reports_later_missing_after_an_earlier_failure(client):
    response = client.post("/api/v1/screening/screen/check", json={"snapshot": {"name": "ST Example"}})
    assert response.status_code == 200
    body = response.json()
    assert body["passed"] is False
    assert body["checks"][0]["status"] == "fail"
    assert body["checks"][-1]["status"] == "missing"
    assert len(body["checks"]) == 12


@pytest.mark.parametrize("snapshot", [{}, [], None, "bad", {"price": []}, {"price": {}},
                                       {"price": "x" * 257}, {"x" * 65: 1}, {"": 1},
                                       {str(i): i for i in range(65)}, {"price": 10 ** 1000}])
def test_invalid_snapshot_returns_bounded_error(client, snapshot):
    response = client.post("/api/v1/screening/screen/check", json={"snapshot": snapshot})
    assert response.status_code == 422
    assert response.json()["error"] == "screening_invalid_snapshot"
    assert len(response.content) < 256


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_nonfinite_json_input_is_missing_not_a_serialization_failure(client, literal):
    response = client.post("/api/v1/screening/screen/check", content='{"snapshot":{"name":"Example","price":' + literal + '}}',
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 200
    assert response.json()["passed"] is False
    price_checks = [item for item in response.json()["checks"] if item["field"] == "price"]
    assert all(item["current_value"] is None and item["status"] == "missing" for item in price_checks)


@pytest.mark.parametrize("payload,error", [
    ({"strategy": "../../etc/passwd"}, "screening_invalid_strategy"),
    ({"strategy": "unknown"}, "screening_invalid_strategy"),
    ({"market": "us"}, "screening_invalid_market"),
    ({"market": "crypto"}, "validation_error"),
])
def test_strategy_and_market_are_checked_before_evaluation(client, payload, error):
    response = client.post("/api/v1/screening/screen/check", json={"snapshot": SNAPSHOT, **payload})
    assert response.status_code == 422
    assert response.json()["error"] == error


def test_check_respects_feature_gate_and_declares_openapi_response(client):
    client.app.dependency_overrides[get_config_dep] = lambda: Config(screening_enabled=False)
    response = client.post("/api/v1/screening/screen/check", json={"snapshot": SNAPSHOT})
    assert response.status_code == 403
    assert response.json()["error"] == "screening_disabled"
    schema = client.app.openapi()
    assert schema["paths"]["/api/v1/screening/screen/check"]["post"]["responses"]["200"]


@pytest.mark.parametrize("row,reason", [
    ({"code": "600000"}, "missing_field"),
    ({"price": None}, "missing_value"),
    ({"price": "bad"}, "invalid_numeric"),
    ({"price": float("inf")}, "non_finite"),
])
def test_missing_reasons_distinguish_absent_and_unusable_values(row, reason):
    check = check_hard_filters(row, HardFilterConfig(exclude_st=False, price_min=0))[0]
    assert check["missing_reason"] == reason
    assert check["source_field"] == ("price" if "price" in row else None)


def test_false_observation_is_preserved_as_a_failed_boolean_condition():
    check = check_hard_filters({"ma_bullish": False}, HardFilterConfig(exclude_st=False, require_ma_bullish=True))[0]
    assert check["current_value"] is False
    assert check["passed"] is False
    assert check["missing_reason"] is None


@pytest.mark.parametrize("strategy,market", [("empty", "cn"), ("american", "us")])
def test_custom_catalog_strategy_with_no_conditions_passes(client, tmp_path, monkeypatch, strategy, market):
    (tmp_path / "custom.yaml").write_text(
        f"name: {strategy}\nversion: '2'\nscreening:\n  enabled: true\n"
        f"  market_scope: [{market}]\n  hard_filters:\n    exclude_st: false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STRATEGIES_DIR", str(tmp_path))
    response = client.post("/api/v1/screening/screen/check", json={
        "strategy": strategy, "market": market, "snapshot": {"code": "EXAMPLE"},
    })
    assert response.status_code == 200
    assert response.json()["checks"] == []
    assert response.json()["passed"] is True
    assert response.json()["strategy_version"] == "2"


def test_market_mismatch_does_not_evaluate_snapshot(client):
    with patch.object(screening, "check_hard_filters", side_effect=AssertionError("wrong market")):
        response = client.post("/api/v1/screening/screen/check", json={"market": "us", "snapshot": SNAPSHOT})
    assert response.status_code == 422
    assert response.json()["error"] == "screening_invalid_market"


def test_disabled_catalog_strategy_is_rejected(client, tmp_path, monkeypatch):
    (tmp_path / "disabled.yaml").write_text("name: disabled\nscreening:\n  enabled: false\n", encoding="utf-8")
    monkeypatch.setenv("STRATEGIES_DIR", str(tmp_path))
    response = client.post("/api/v1/screening/screen/check", json={"strategy": "disabled", "snapshot": SNAPSHOT})
    assert response.status_code == 422
    assert response.json()["error"] == "screening_invalid_strategy"


def test_real_app_mount_requires_auth_and_accepts_a_signed_session(tmp_path, monkeypatch):
    from api.app import create_app
    from src import auth

    monkeypatch.setattr(auth, "_auth_enabled", True)
    monkeypatch.setattr(auth, "_session_secret", b"s" * 32)
    monkeypatch.setenv("STRATEGIES_DIR", str(STRATEGIES))
    app = create_app(static_dir=tmp_path)
    app.dependency_overrides[get_config_dep] = lambda: Config(screening_enabled=True)
    mounted_client = FastAPITestClient(app)
    url = "/api/v1/screening/screen/check"
    assert url in app.openapi()["paths"]
    response = mounted_client.post(url, json={"snapshot": SNAPSHOT})
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    mounted_client.cookies.set(auth.COOKIE_NAME, "invalid-session")
    assert mounted_client.post(url, json={"snapshot": SNAPSHOT}).status_code == 401
    mounted_client.cookies.set(auth.COOKIE_NAME, auth.create_session())
    response = mounted_client.post(url, json={"snapshot": SNAPSHOT})
    assert response.status_code == 200
    assert response.json()["passed"] is True
    assert response.json()["provenance"] == "supplied_snapshot"


@pytest.mark.parametrize("value", [-6, -5, 0, 5, 6])
def test_finite_negative_values_and_inclusive_boundaries_match_pipeline(value):
    row = {"price": value}
    filters = HardFilterConfig(exclude_st=False, price_min=-5, price_max=5)
    checks = check_hard_filters(row, filters)
    assert [item["passed"] for item in checks] == [value >= -5, value <= 5]
    assert all(item["current_value"] == value for item in checks)
    assert all(item["passed"] for item in checks) == (not apply_hard_filters(pd.DataFrame([row]), filters).empty)


@pytest.mark.parametrize("row,filters", [
    ({"name": None}, HardFilterConfig()),
    ({"price": float("inf")}, HardFilterConfig(exclude_st=False, price_min=1)),
])
def test_unusable_data_is_conservatively_unknown_even_when_legacy_predicate_passes(row, filters):
    assert not apply_hard_filters(pd.DataFrame([row]), filters).empty
    checks = check_hard_filters(row, filters)
    assert checks[0]["status"] == "missing"
    assert checks[0]["passed"] is None
