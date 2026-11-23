# -*- coding: utf-8 -*-
"""Regression tests for chip distribution provider fallback."""

from types import SimpleNamespace
from unittest.mock import patch

from data_provider.base import DataFetcherManager
from data_provider.realtime_types import ChipDistribution, get_chip_circuit_breaker


class _ChipFetcher:
    def __init__(self, name: str, priority: int, result):
        self.name = name
        self.priority = priority
        self._result = result
        self.calls = 0

    def get_chip_distribution(self, stock_code: str):
        self.calls += 1
        return self._result


class _FailingChipFetcher(_ChipFetcher):
    def __init__(self, name: str, priority: int, error: Exception):
        super().__init__(name, priority, None)
        self._error = error

    def get_chip_distribution(self, stock_code: str):
        self.calls += 1
        raise self._error


def _run_with_chip_diagnostics(manager: DataFetcherManager):
    from src.services.run_diagnostics import (
        activate_run_diagnostic_context,
        current_diagnostic_snapshot,
        reset_run_diagnostic_context,
    )

    flow_events = []
    token = activate_run_diagnostic_context(
        trace_id="trace-chip",
        task_id="task-chip",
        query_id="query-chip",
        stock_code="600519",
        trigger_source="api",
        event_sink=flow_events.append,
    )
    try:
        with patch("src.config.get_config", return_value=SimpleNamespace(enable_chip_distribution=True)):
            chip = manager.get_chip_distribution("600519")
        diagnostics = current_diagnostic_snapshot()
    finally:
        reset_run_diagnostic_context(token)
    return chip, diagnostics, flow_events


def test_manager_skips_placeholder_chip_distribution_and_tries_next_fetcher():
    get_chip_circuit_breaker().reset()
    empty_chip = ChipDistribution(code="600519")
    valid_chip = ChipDistribution(
        code="600519",
        profit_ratio=0.61,
        avg_cost=12.3,
        concentration_90=0.13,
    )
    manager = DataFetcherManager(
        fetchers=[
            _ChipFetcher("EmptyFetcher", 0, empty_chip),
            _ChipFetcher("ValidFetcher", 1, valid_chip),
        ]
    )

    chip, diagnostics, flow_events = _run_with_chip_diagnostics(manager)

    assert chip is valid_chip
    assert diagnostics is not None
    provider_runs = diagnostics["provider_runs"]
    assert [run["data_type"] for run in provider_runs] == ["chip", "chip"]
    assert [run["success"] for run in provider_runs] == [False, True]
    assert provider_runs[0]["fallback_to"] == "ValidFetcher"
    assert provider_runs[0]["record_count"] == 0
    assert provider_runs[1]["record_count"] == 1
    assert [event["type"] for event in flow_events] == [
        "provider_run_started",
        "provider_run",
        "provider_run_started",
        "provider_run",
    ]
    assert flow_events[0]["node_id"] == flow_events[1]["node_id"]
    assert flow_events[2]["node_id"] == flow_events[3]["node_id"]
    assert flow_events[0]["node_id"] == "provider_chip_emptyfetcher_1"
    assert flow_events[2]["node_id"] == "provider_chip_validfetcher_2"


def test_manager_accepts_zero_concentration_chip_distribution():
    get_chip_circuit_breaker().reset()
    zero_concentration_chip = ChipDistribution(
        code="600519",
        profit_ratio=0.61,
        avg_cost=12.3,
        concentration_90=0.0,
        concentration_70=0.0,
    )
    fallback_chip = ChipDistribution(
        code="600519",
        profit_ratio=0.62,
        avg_cost=12.5,
        concentration_90=0.13,
    )
    zero_fetcher = _ChipFetcher("ZeroConcentrationFetcher", 0, zero_concentration_chip)
    fallback_fetcher = _ChipFetcher("FallbackFetcher", 1, fallback_chip)
    manager = DataFetcherManager(fetchers=[zero_fetcher, fallback_fetcher])

    chip, diagnostics, flow_events = _run_with_chip_diagnostics(manager)

    assert chip is zero_concentration_chip
    assert zero_fetcher.calls == 1
    assert fallback_fetcher.calls == 0
    assert diagnostics is not None
    assert len(diagnostics["provider_runs"]) == 1
    assert diagnostics["provider_runs"][0]["data_type"] == "chip"
    assert diagnostics["provider_runs"][0]["success"] is True
    assert [event["type"] for event in flow_events] == ["provider_run_started", "provider_run"]
    assert flow_events[0]["node_id"] == flow_events[1]["node_id"]


def test_manager_records_failed_chip_attempt_and_falls_back_to_next_fetcher():
    get_chip_circuit_breaker().reset()
    valid_chip = ChipDistribution(
        code="600519",
        profit_ratio=0.61,
        avg_cost=12.3,
        concentration_90=0.13,
    )
    failing_fetcher = _FailingChipFetcher("FailingFetcher", 0, RuntimeError("temporary chip failure"))
    fallback_fetcher = _ChipFetcher("FallbackFetcher", 1, valid_chip)
    manager = DataFetcherManager(fetchers=[failing_fetcher, fallback_fetcher])

    chip, diagnostics, flow_events = _run_with_chip_diagnostics(manager)

    assert chip is valid_chip
    assert failing_fetcher.calls == 1
    assert fallback_fetcher.calls == 1
    assert diagnostics is not None
    provider_runs = diagnostics["provider_runs"]
    assert [run["provider"] for run in provider_runs] == ["FailingFetcher", "FallbackFetcher"]
    assert provider_runs[0]["success"] is False
    assert provider_runs[0]["error_type"] == "RuntimeError"
    assert provider_runs[0]["fallback_to"] == "FallbackFetcher"
    assert provider_runs[1]["success"] is True
    assert [event["type"] for event in flow_events] == [
        "provider_run_started",
        "provider_run",
        "provider_run_started",
        "provider_run",
    ]
