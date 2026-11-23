# -*- coding: utf-8 -*-
"""Contract isolation tests for #1390 P1 DecisionSignal fields."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from api.v1.schemas.backtest import BacktestResultItem
from api.v1.schemas.history import (
    AnalysisReport,
    HistoryItem,
    ReportDetails,
    ReportMeta,
    ReportStrategy,
    ReportSummary,
    StockBarItem,
)


# Only check top-level Pydantic fields on the primary history/report/stock
# bar/backtest contracts listed below. These names are not globally reserved:
# nested schemas such as MarketPhaseSummary and AnalysisContextPackOverview,
# plus unrelated diagnostics contracts, intentionally expose fields like
# trigger_source, status, or reason for their own contracts. raw_result and
# context_snapshot are Any payloads and cannot be constrained by this test.
FORBIDDEN_PRIMARY_CONTRACT_SIGNAL_FIELDS = {
    "decision_signals",
    "plan_quality",
    "horizon",
    "source_type",
    "source_agent",
    "source_report_id",
    "trace_id",
    "trigger_source",
    "expires_at",
    "invalidation",
    "watch_conditions",
    "reason",
    "risk_summary",
    "catalyst_summary",
    "evidence",
    "data_quality_summary",
    "status",
    "confidence",
    "score",
    "entry_low",
    "entry_high",
    "target_price",
    "metadata",
}

ALLOWED_SHARED_FIELDS = {
    "action",
    "action_label",
    "operation_advice",
    "market_phase",
    "stop_loss",
    "take_profit",
}


@pytest.mark.parametrize(
    "schema_model",
    [
        HistoryItem,
        StockBarItem,
        BacktestResultItem,
        AnalysisReport,
        ReportMeta,
        ReportSummary,
        ReportStrategy,
        ReportDetails,
    ],
)
def test_decision_signal_fields_do_not_leak_into_primary_contracts(schema_model: type[BaseModel]) -> None:
    fields = set(schema_model.model_fields)

    assert not fields & FORBIDDEN_PRIMARY_CONTRACT_SIGNAL_FIELDS


def test_contract_isolation_guard_does_not_forbid_existing_shared_fields() -> None:
    assert not ALLOWED_SHARED_FIELDS & FORBIDDEN_PRIMARY_CONTRACT_SIGNAL_FIELDS
