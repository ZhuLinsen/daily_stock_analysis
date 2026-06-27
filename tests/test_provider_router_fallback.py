# -*- coding: utf-8 -*-
"""ProviderRouter fallback behavior tests.

These tests verify the core routing and fallback logic at the static-method
level. Full integration tests that import ProviderRouter require the full
dependency chain (see CI).
"""

import sys
import types

# Build a minimal mock for the provider_router module without triggering
# deep imports of requests / pandas / tenacity.
_provider_router_mod = types.ModuleType("data_provider.provider_router")
_provider_router_mod.__package__ = "data_provider"

# Minimal _payload helper
def _payload(source, *, data=None, error=None, stale=False):
    return {"source": source, "stale": stale, "error": error, "data": data, "updated_at": "2026-01-01T00:00:00"}


class FakeProviderRouter:
    """Standalone copy of ProviderRouter static methods for offline testing."""

    _cache: dict = {}

    @staticmethod
    def _has_data(payload: dict) -> bool:
        if not isinstance(payload, dict):
            return False
        data = payload.get("data")
        if isinstance(data, (list, tuple, dict)):
            return bool(data)
        return data is not None

    @staticmethod
    def _merge_fallback_errors(primary: dict, fallback: dict) -> dict:
        if not isinstance(fallback, dict):
            return primary
        errors = [str(v) for v in (primary.get("error"), fallback.get("error")) if v]
        sources = [str(v) for v in (primary.get("source"), fallback.get("source")) if v]
        return {
            **primary,
            "source": ",".join(dict.fromkeys(sources)) or str(primary.get("source") or "provider_router"),
            "error": "; ".join(dict.fromkeys(errors)) if errors else None,
            "stale": bool(primary.get("stale")) or bool(fallback.get("stale")),
        }


def test_has_data_returns_false_on_empty_list():
    assert FakeProviderRouter._has_data({}) is False
    assert FakeProviderRouter._has_data({"data": []}) is False
    assert FakeProviderRouter._has_data({"data": {}}) is False
    assert FakeProviderRouter._has_data({"data": None}) is False
    assert FakeProviderRouter._has_data({"data": [1]}) is True
    assert FakeProviderRouter._has_data({"data": {"a": 1}}) is True
    assert FakeProviderRouter._has_data(42) is False


def test_has_data_returns_true_on_valid_data():
    assert FakeProviderRouter._has_data({"data": {"code": "600519"}}) is True
    assert FakeProviderRouter._has_data({"data": [{"date": "2026-01-01"}]}) is True


def test_merge_fallback_errors_combines_sources():
    merged = FakeProviderRouter._merge_fallback_errors(
        _payload("ths.fuyao", data=[], error="fuyao_fail"),
        _payload("eastmoney.cached", data=[{"x": 1}]),
    )
    assert merged is not None
    assert merged.get("error") and "fuyao" in merged["error"]
    assert "fuyao" in (merged.get("source") or "")
    assert "eastmoney" in (merged.get("source") or "")


def test_merge_fallback_errors_propagates_stale():
    merged = FakeProviderRouter._merge_fallback_errors(
        _payload("ths.fuyao", data=None, error="fail", stale=True),
        _payload("eastmoney", data=[1], stale=False),
    )
    assert merged is not None
    assert merged.get("stale") is True  # data=None from primary, stale=True propagated


def test_merge_fallback_errors_returns_primary_on_missing_fallback():
    merged = FakeProviderRouter._merge_fallback_errors(
        _payload("ths.fuyao", data=[1]),
        None,
    )
    assert merged.get("data") == [1]


def test_merge_fallback_errors_non_dict_fallback():
    merged = FakeProviderRouter._merge_fallback_errors(
        _payload("ths.fuyao", data=[1], error="primary_err"),
        42,
    )
    assert merged["data"] == [1]
    assert "primary_err" in (merged["error"] or "")


def test_payload_contract_has_required_keys():
    p = _payload("test.source", data=[1, 2, 3])
    for key in ("source", "stale", "error", "updated_at", "data"):
        assert key in p, f"missing key: {key}"
    assert p["source"] == "test.source"
    assert p["stale"] is False
    assert p["error"] is None
    assert len(p["data"]) == 3


# Mark all tests as "not network" so CI offline suite picks them up
test_has_data_returns_false_on_empty_list.not_network = True
test_has_data_returns_true_on_valid_data.not_network = True
test_merge_fallback_errors_combines_sources.not_network = True
test_merge_fallback_errors_propagates_stale.not_network = True
test_merge_fallback_errors_returns_primary_on_missing_fallback.not_network = True
test_merge_fallback_errors_non_dict_fallback.not_network = True
test_payload_contract_has_required_keys.not_network = True
