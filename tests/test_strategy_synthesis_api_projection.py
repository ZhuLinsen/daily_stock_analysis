# -*- coding: utf-8 -*-
"""W2-RED tests for the typed strategy_synthesis API projection (issue #2071).

Covers the ``report.details.strategy_synthesis`` typed projection across the
construction paths plus the OpenAPI schema surface:

- path 1: sync response   -> ``_build_analysis_report`` (api/v1/endpoints/analysis.py)
- path 2: async completion -> DB rebuild inside ``get_analysis_status``
- path 3: history detail   -> ``HistoryService._record_to_detail_dict``
  (and its ``GET /history/{record_id}`` ReportDetails consumer)
- Pydantic schemas in api/v1/schemas/history.py + OpenAPI components
- gating: only ``schema_version == "strategy-synthesis-v1"`` payloads project;
  legacy (missing/None) or unknown versions project to ``strategy_synthesis=None``
- malformed payloads degrade to ``None`` / filtered entries, never a 500
- ``details.raw_result`` is preserved untouched
- no new OpenAPI paths

Plan reference: sess_bf628c30 W2 task 3 (RED list points 1-8). Point 8 (static
spec full-equality test stays green) is asserted by the directed command
``tests/test_api_schema_pydantic.py`` rather than duplicated here.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, get_args
from unittest.mock import MagicMock, patch

_ORIGINAL_ENVIRON = dict(os.environ)
_MODULE_TEMP_DIR = tempfile.TemporaryDirectory()
_MODULE_ENV_FILE = Path(_MODULE_TEMP_DIR.name) / ".env"
_MODULE_ENV_FILE.write_text("STOCK_LIST=600519,000001\n", encoding="utf-8")
os.environ["ENV_FILE"] = str(_MODULE_ENV_FILE)

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

try:
    import api.v1.schemas.history as history_schemas
    from api.v1.schemas.history import ReportDetails
except Exception:  # pragma: no cover - optional dependency environments
    history_schemas = None
    ReportDetails = None

try:
    from api.v1.endpoints.analysis import _build_analysis_report, get_analysis_status
    import api.v1.endpoints.history as history_endpoint_module
except Exception:  # pragma: no cover - optional dependency environments
    _build_analysis_report = None
    get_analysis_status = None
    history_endpoint_module = None

try:
    from src.services.history_service import HistoryService
except Exception:  # pragma: no cover - optional dependency environments
    HistoryService = None

try:
    from api.app import create_app
except Exception:  # pragma: no cover - optional dependency environments
    create_app = None


SCHEMA_VERSION = "strategy-synthesis-v1"

# The typed projection whitelist (issue #2071 field list, 15 + 2 optional).
PROJECTION_FIELDS = (
    "schema_version",
    "final_signal",
    "weighted_score",
    "confidence",
    "original_confidence",
    "consensus_level",
    "conflict_count",
    "conflict_severity",
    "summary_key",
    "summary_params",
    "signal_distribution",
    "supporting_skills",
    "opposing_skills",
    "primary_dissent",
    "conflicts",
    "deliberation",
    "revision_projection",
)

SKILL_ENTRY_FIELDS = (
    "skill_id",
    "agent_name",
    "signal",
    "confidence",
    "reasoning",
    "score_adjustment",
    "conditions_met",
    "invalid_signal",
)

DISSENT_FIELDS = ("skill_id", "agent_name", "signal", "confidence", "reasoning")

# Snapshot of create_app().openapi()["paths"] at the W2 baseline
# (branch feat/strategy-synthesis-2071, HEAD e864f3cc), re-aligned with
# upstream main 4e622643 (see UPSTREAM_RETIRED_OPENAPI_PATHS below). The
# typed projection must not add or remove any API path.
BASELINE_OPENAPI_PATHS = frozenset({
    "/api/health",
    "/api/v1/agent/chat",
    "/api/v1/agent/chat/send",
    "/api/v1/agent/chat/sessions",
    "/api/v1/agent/chat/sessions/{session_id}",
    "/api/v1/agent/chat/stream",
    "/api/v1/agent/models",
    "/api/v1/agent/research",
    "/api/v1/agent/skills",
    "/api/v1/agent/status",
    "/api/v1/alerts/notifications",
    "/api/v1/alerts/rules",
    "/api/v1/alerts/rules/{rule_id}",
    "/api/v1/alerts/rules/{rule_id}/disable",
    "/api/v1/alerts/rules/{rule_id}/enable",
    "/api/v1/alerts/rules/{rule_id}/test",
    "/api/v1/alerts/triggers",
    "/api/v1/analysis/analyze",
    "/api/v1/analysis/market-review",
    "/api/v1/analysis/status/{task_id}",
    "/api/v1/analysis/tasks",
    "/api/v1/analysis/tasks/stream",
    "/api/v1/analysis/tasks/{task_id}/flow",
    "/api/v1/auth/change-password",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
    "/api/v1/auth/settings",
    "/api/v1/auth/status",
    "/api/v1/backtest/performance",
    "/api/v1/backtest/performance/{code}",
    "/api/v1/backtest/results",
    "/api/v1/backtest/run",
    "/api/v1/data/capabilities",
    "/api/v1/data/overview",
    "/api/v1/decision-signals",
    "/api/v1/decision-signals/latest/{stock_code}",
    "/api/v1/decision-signals/outcomes",
    "/api/v1/decision-signals/outcomes/run",
    "/api/v1/decision-signals/outcomes/stats",
    "/api/v1/decision-signals/reassess",
    "/api/v1/decision-signals/stocks/{stock_code}/review",
    "/api/v1/decision-signals/{signal_id}",
    "/api/v1/decision-signals/{signal_id}/feedback",
    "/api/v1/decision-signals/{signal_id}/outcomes",
    "/api/v1/decision-signals/{signal_id}/status",
    "/api/v1/health",
    "/api/v1/history",
    "/api/v1/history/by-code/{stock_code}",
    "/api/v1/history/stocks",
    "/api/v1/history/{record_id}",
    "/api/v1/history/{record_id}/diagnostics",
    "/api/v1/history/{record_id}/flow",
    "/api/v1/history/{record_id}/markdown",
    "/api/v1/history/{record_id}/news",
    "/api/v1/history/{record_id}/share-image",
    "/api/v1/history/{record_id}/share-image-html",
    "/api/v1/intelligence/items",
    "/api/v1/intelligence/sources",
    "/api/v1/intelligence/sources/defaults",
    "/api/v1/intelligence/sources/fetch-enabled",
    "/api/v1/intelligence/sources/templates",
    "/api/v1/intelligence/sources/templates/{template_id}",
    "/api/v1/intelligence/sources/test",
    "/api/v1/intelligence/sources/{source_id}/fetch",
    "/api/v1/portfolio/accounts",
    "/api/v1/portfolio/accounts/{account_id}",
    "/api/v1/portfolio/cash-ledger",
    "/api/v1/portfolio/cash-ledger/{entry_id}",
    "/api/v1/portfolio/corporate-actions",
    "/api/v1/portfolio/corporate-actions/{action_id}",
    "/api/v1/portfolio/fx/refresh",
    "/api/v1/portfolio/imports/csv/brokers",
    "/api/v1/portfolio/imports/csv/commit",
    "/api/v1/portfolio/imports/csv/parse",
    "/api/v1/portfolio/positions/{symbol}/analysis",
    "/api/v1/portfolio/risk",
    "/api/v1/portfolio/snapshot",
    "/api/v1/portfolio/trades",
    "/api/v1/portfolio/trades/{trade_id}",
    "/api/v1/screening/history",
    "/api/v1/screening/history/{run_id}",
    "/api/v1/screening/hotspots",
    "/api/v1/screening/hotspots/{topic}",
    "/api/v1/screening/screen",
    "/api/v1/screening/screen/check",
    "/api/v1/screening/screen/tasks",
    "/api/v1/screening/screen/tasks/{task_id}",
    "/api/v1/screening/source-history",
    "/api/v1/screening/status",
    "/api/v1/screening/strategies",
    "/api/v1/stocks/extract-from-image",
    "/api/v1/stocks/parse-import",
    "/api/v1/stocks/watchlist",
    "/api/v1/stocks/watchlist/add",
    "/api/v1/stocks/watchlist/remove",
    "/api/v1/stocks/{stock_code}/history",
    "/api/v1/stocks/{stock_code}/profile",
    "/api/v1/stocks/{stock_code}/quote",
    "/api/v1/system/config",
    "/api/v1/system/config/agent-backends/status",
    "/api/v1/system/config/agent-backends/status/preview",
    "/api/v1/system/config/export",
    "/api/v1/system/config/generation-backends/smoke-test",
    "/api/v1/system/config/generation-backends/status",
    "/api/v1/system/config/generation-backends/status/preview",
    "/api/v1/system/config/import",
    "/api/v1/system/config/llm/discover-models",
    "/api/v1/system/config/llm/test-channel",
    "/api/v1/system/config/notification/test-channel",
    "/api/v1/system/config/schema",
    "/api/v1/system/config/setup/status",
    "/api/v1/system/config/validate",
    "/api/v1/system/scheduler/run-now",
    "/api/v1/system/scheduler/status",
    "/api/v1/usage/dashboard",
    "/api/v1/usage/summary",
    "/health",
})

# Upstream commit 88ec4bae (PR #2422) retired the Codex App Server
# cancellation endpoint, so create_app() exposes it only while the branch
# predates that merge. The path is filtered out of the observed route set
# before the invariant check instead of being pinned to either side of the
# merge; every other path must match the baseline exactly.
UPSTREAM_RETIRED_OPENAPI_PATHS = frozenset({
    "/api/v1/agent/chat/stream/{request_id}/cancel",
})


def tearDownModule() -> None:
    current_test = os.environ.get("PYTEST_CURRENT_TEST")
    for key in list(os.environ):
        if key == "PYTEST_CURRENT_TEST":
            continue
        if key not in _ORIGINAL_ENVIRON:
            os.environ.pop(key, None)
    os.environ.update(_ORIGINAL_ENVIRON)
    if current_test is not None:
        os.environ["PYTEST_CURRENT_TEST"] = current_test
    _MODULE_TEMP_DIR.cleanup()


def _v1_synthesis_payload() -> Dict[str, Any]:
    """A complete, well-formed strategy-synthesis-v1 payload (W1 shape)."""
    return {
        "final_signal": "hold",
        "weighted_score": 3.4545,
        "confidence": 0.6517,
        "original_confidence": 0.7545,
        "conflict_count": 1,
        "conflict_severity": "medium",
        "conflicts": [
            {
                "conflict_type": "direction",
                "severity": "medium",
                "description_key": "conflict_direction",
                "participants": ["skill_hold", "skill_buy"],
                "metadata": {},
            }
        ],
        "supporting_skills": [
            {
                "skill_id": "skill_hold",
                "agent_name": "strategy_hold",
                "signal": "hold",
                "confidence": 0.7,
                "reasoning": "区间震荡，观望",
                "score_adjustment": 0.0,
                "conditions_met": ["cond_hold_1"],
                "invalid_signal": False,
            }
        ],
        "opposing_skills": [
            {
                "skill_id": "skill_buy",
                "agent_name": "strategy_buy",
                "signal": "buy",
                "confidence": 0.9,
                "reasoning": "突破形态成立",
                "score_adjustment": 0.1,
                "conditions_met": [],
                "invalid_signal": False,
            }
        ],
        "consensus_level": "medium",
        "summary_key": "strategy_synthesis.with_conflicts",
        "summary_params": {
            "opinion_count": 2,
            "total_opinion_count": 2,
            "invalid_opinion_count": 0,
            "final_signal": "hold",
            "consensus_level": "medium",
            "conflict_severity": "medium",
            "conflict_count": 1,
        },
        "schema_version": SCHEMA_VERSION,
        "signal_distribution": {
            "bullish": {"count": 1, "weight_share": 0.6},
            "neutral": {"count": 1, "weight_share": 0.4},
            "bearish": {"count": 0, "weight_share": 0.0},
        },
        "primary_dissent": {
            "skill_id": "skill_buy",
            "agent_name": "strategy_buy",
            "signal": "buy",
            "confidence": 0.9,
            "reasoning": "突破形态成立",
        },
        "deliberation": {"summary": {"confidence_adjustment": 0.0}},
        "revision_projection": {
            "status": "preview",
            "mode": "softened",
            "projected_signal": "buy",
            "projected_confidence": 0.8,
            "final_signal_overridden": False,
        },
        # Proves the projection whitelist: this key must never appear in the
        # typed projection but must survive untouched inside details.raw_result.
        "non_whitelisted_field": "internal-only",
    }


def _raw_result_with(strategy_synthesis: Any) -> Dict[str, Any]:
    """A raw_result dict whose dashboard carries the given synthesis payload."""
    return {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "model_used": "test-model",
        "report_language": "zh",
        "analysis_summary": "多策略综合摘要",
        "operation_advice": "持有",
        "trend_prediction": "震荡",
        "sentiment_score": 55,
        "dashboard": {
            "core_conclusion": {"one_sentence": "震荡市观望"},
            "strategy_synthesis": strategy_synthesis,
        },
    }


def _expected_projection() -> Dict[str, Any]:
    """The exact typed projection dict expected for ``_v1_synthesis_payload``."""
    payload = _v1_synthesis_payload()
    payload.pop("non_whitelisted_field")
    return payload


def _collect_schema_refs(node: Any) -> set:
    refs = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            refs.add(ref)
        for value in node.values():
            refs |= _collect_schema_refs(value)
    elif isinstance(node, list):
        for value in node:
            refs |= _collect_schema_refs(value)
    return refs


def _collect_schema_types(node: Any) -> set:
    types = set()
    if isinstance(node, dict):
        if isinstance(node.get("type"), str):
            types.add(node["type"])
        for value in node.values():
            types |= _collect_schema_types(value)
    elif isinstance(node, list):
        for value in node:
            types |= _collect_schema_types(value)
    return types


class StrategySynthesisApiProjectionTestCase(unittest.TestCase):
    """Typed strategy_synthesis details projection contract (issue #2071 W2)."""

    # ------------------------------------------------------------------
    # Path drivers
    # ------------------------------------------------------------------

    def _details_via_sync_report(self, raw_result: Any):
        """Path 1: sync response -> _build_analysis_report -> ReportDetails."""
        report_data = {
            "meta": {
                "query_id": "task-synthesis-1",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report_type": "detailed",
                "created_at": "2026-10-25T03:00:00",
                "report_language": "zh",
            },
            "summary": {"analysis_summary": "多策略综合摘要", "operation_advice": "持有"},
            "details": {"raw_result": raw_result},
        }
        report = _build_analysis_report(
            report_data,
            "task-synthesis-1",
            "600519",
            stock_name="贵州茅台",
            context_snapshot=None,
        )
        self.assertIsNotNone(report)
        return report.details

    def _details_via_async_db_rebuild(self, raw_result: Any) -> Dict[str, Any]:
        """Path 2: get_analysis_status DB rebuild -> report details dict."""
        record = SimpleNamespace(
            id=11,
            code="600519",
            name="贵州茅台",
            report_type="detailed",
            raw_result=dict(raw_result) if isinstance(raw_result, dict) else raw_result,
            context_snapshot={"report_language": "zh", "skills": ["bull_trend"]},
            sentiment_score=55,
            operation_advice="持有",
            trend_prediction="震荡",
            analysis_summary="多策略综合摘要",
            ideal_buy=None,
            secondary_buy=None,
            stop_loss=None,
            take_profit=None,
            created_at=datetime(2026, 10, 25, 3, 0, 0),
            news_content=None,
        )
        mock_queue = MagicMock()
        mock_queue.get_task.return_value = None
        mock_db = MagicMock()
        mock_db.get_analysis_history.return_value = [record]
        mock_db.get_latest_fundamental_snapshot.return_value = None
        with patch(
            "api.v1.endpoints.analysis.get_task_queue", return_value=mock_queue
        ), patch(
            "src.storage.DatabaseManager.get_instance", return_value=mock_db
        ):
            status = get_analysis_status("task-synthesis-1")
        self.assertIsNotNone(status)
        self.assertIsNotNone(status.result, "async DB rebuild must produce a result")
        self.assertIsNotNone(status.result.report)
        details = status.result.report["details"]
        self.assertIsInstance(details, dict)
        return details

    def _detail_via_record_to_detail_dict(self, raw_result: Any) -> Dict[str, Any]:
        """Path 3: history service detail dict."""
        record = SimpleNamespace(
            id=11,
            query_id="task-synthesis-1",
            code="600519",
            name="贵州茅台",
            report_type="detailed",
            created_at=datetime(2026, 10, 25, 3, 0, 0),
            analysis_summary="多策略综合摘要",
            operation_advice="持有",
            trend_prediction="震荡",
            sentiment_score=55,
            news_content=None,
            context_snapshot=None,
            raw_result=(
                json.dumps(raw_result, ensure_ascii=False)
                if isinstance(raw_result, dict)
                else raw_result
            ),
        )
        service = HistoryService(MagicMock())
        return service._record_to_detail_dict(record)

    def _report_via_history_endpoint(self, detail_dict: Dict[str, Any]):
        """Path 3 consumer: GET /history/{record_id} -> AnalysisReport."""
        mock_service = MagicMock()
        mock_service.resolve_and_get_detail.return_value = detail_dict
        mock_db = MagicMock()
        mock_db.get_latest_fundamental_snapshot.return_value = None
        with patch.object(
            history_endpoint_module, "HistoryService", return_value=mock_service
        ):
            return history_endpoint_module.get_history_detail(
                "11", db_manager=mock_db
            )

    # ------------------------------------------------------------------
    # Point 1: Pydantic schema declarations
    # ------------------------------------------------------------------

    def test_1_report_details_declares_typed_strategy_synthesis(self) -> None:
        if history_schemas is None or ReportDetails is None:
            self.skipTest("history schemas unavailable in this environment")

        for name in (
            "StrategySynthesis",
            "SignalDistribution",
            "SignalDistributionBucket",
            "PrimaryDissent",
            "StrategySynthesisSkillEntry",
        ):
            self.assertIsNotNone(
                getattr(history_schemas, name, None),
                f"api.v1.schemas.history must define {name} "
                f"(issue #2071 W2 typed projection)",
            )

        strategy_synthesis_cls = history_schemas.StrategySynthesis
        self.assertEqual(
            set(strategy_synthesis_cls.model_fields),
            set(PROJECTION_FIELDS),
            "StrategySynthesis must declare exactly the issue #2071 field list",
        )

        distribution_cls = history_schemas.SignalDistribution
        self.assertEqual(
            set(distribution_cls.model_fields), {"bullish", "neutral", "bearish"}
        )
        bucket_cls = history_schemas.SignalDistributionBucket
        self.assertEqual(set(bucket_cls.model_fields), {"count", "weight_share"})

        dissent_cls = history_schemas.PrimaryDissent
        self.assertEqual(set(dissent_cls.model_fields), set(DISSENT_FIELDS))

        entry_cls = history_schemas.StrategySynthesisSkillEntry
        self.assertEqual(set(entry_cls.model_fields), set(SKILL_ENTRY_FIELDS))

        self.assertIn(
            "strategy_synthesis",
            ReportDetails.model_fields,
            "ReportDetails must declare the typed strategy_synthesis field",
        )
        field = ReportDetails.model_fields["strategy_synthesis"]
        annotation_args = set(get_args(field.annotation))
        self.assertIn(strategy_synthesis_cls, annotation_args)
        self.assertIn(type(None), annotation_args)
        self.assertIsNotNone(field.description)
        self.assertIn("低敏投影", field.description)

    # ------------------------------------------------------------------
    # Point 2: OpenAPI components declare the new schemas
    # ------------------------------------------------------------------

    def test_2_openapi_components_declare_strategy_synthesis_schemas(self) -> None:
        if create_app is None:
            self.skipTest("fastapi is not installed in this test environment")

        schemas = create_app().openapi()["components"]["schemas"]
        for name in (
            "StrategySynthesis",
            "SignalDistribution",
            "SignalDistributionBucket",
            "PrimaryDissent",
            "StrategySynthesisSkillEntry",
        ):
            self.assertIn(name, schemas, f"OpenAPI components must declare {name}")

        synthesis_schema = schemas["StrategySynthesis"]
        self.assertEqual(
            set(synthesis_schema["properties"]),
            set(PROJECTION_FIELDS),
        )
        self.assertEqual(
            _collect_schema_refs(synthesis_schema["properties"]["signal_distribution"]),
            {"#/components/schemas/SignalDistribution"},
        )
        self.assertEqual(
            _collect_schema_refs(synthesis_schema["properties"]["primary_dissent"]),
            {"#/components/schemas/PrimaryDissent"},
        )
        self.assertEqual(
            _collect_schema_refs(synthesis_schema["properties"]["supporting_skills"]),
            {"#/components/schemas/StrategySynthesisSkillEntry"},
        )
        self.assertEqual(
            _collect_schema_refs(synthesis_schema["properties"]["opposing_skills"]),
            {"#/components/schemas/StrategySynthesisSkillEntry"},
        )

        self.assertEqual(
            set(schemas["SignalDistribution"]["properties"]),
            {"bullish", "neutral", "bearish"},
        )
        for camp in ("bullish", "neutral", "bearish"):
            self.assertEqual(
                _collect_schema_refs(schemas["SignalDistribution"]["properties"][camp]),
                {"#/components/schemas/SignalDistributionBucket"},
            )
        self.assertEqual(
            set(schemas["SignalDistributionBucket"]["properties"]),
            {"count", "weight_share"},
        )
        bucket_count = schemas["SignalDistributionBucket"]["properties"]["count"]
        self.assertEqual(bucket_count.get("type"), "integer")
        bucket_share = schemas["SignalDistributionBucket"]["properties"]["weight_share"]
        self.assertEqual(_collect_schema_types(bucket_share), {"number", "null"})

        self.assertEqual(
            set(schemas["PrimaryDissent"]["properties"]), set(DISSENT_FIELDS)
        )
        self.assertEqual(
            set(schemas["StrategySynthesisSkillEntry"]["properties"]),
            set(SKILL_ENTRY_FIELDS),
        )

        report_details_schema = schemas["ReportDetails"]
        self.assertIn("strategy_synthesis", report_details_schema["properties"])
        self.assertEqual(
            _collect_schema_refs(
                report_details_schema["properties"]["strategy_synthesis"]
            ),
            {"#/components/schemas/StrategySynthesis"},
        )

    # ------------------------------------------------------------------
    # Point 3: the three construction paths agree field by field
    # ------------------------------------------------------------------

    def test_3_three_projection_paths_agree_field_by_field(self) -> None:
        guards = (
            (_build_analysis_report, "_build_analysis_report unavailable"),
            (get_analysis_status, "get_analysis_status unavailable"),
            (HistoryService, "HistoryService unavailable"),
            (history_endpoint_module, "history endpoint module unavailable"),
        )
        for guard, message in guards:
            if guard is None:
                self.skipTest(message)

        raw_result = _raw_result_with(_v1_synthesis_payload())
        expected = _expected_projection()

        # Path 1: sync response
        details_1 = self._details_via_sync_report(raw_result)
        syn_1 = getattr(details_1, "strategy_synthesis", None)
        self.assertIsNotNone(
            syn_1,
            "path 1 (_build_analysis_report) must project details.strategy_synthesis",
        )
        self.assertEqual(details_1.model_dump()["strategy_synthesis"], expected)

        # Path 2: async task completion (DB rebuild)
        details_2 = self._details_via_async_db_rebuild(raw_result)
        syn_2 = details_2.get("strategy_synthesis")
        self.assertIsNotNone(
            syn_2,
            "path 2 (async DB rebuild) must project details.strategy_synthesis",
        )
        self.assertEqual(syn_2, expected)

        # Path 3: history detail service dict
        detail_dict = self._detail_via_record_to_detail_dict(raw_result)
        syn_3 = detail_dict.get("strategy_synthesis")
        self.assertIsNotNone(
            syn_3,
            "path 3 (_record_to_detail_dict) must project details.strategy_synthesis",
        )
        self.assertEqual(syn_3, expected)

        # Path 3 consumer: the history detail endpoint must forward it.
        report_3 = self._report_via_history_endpoint(detail_dict)
        syn_3_endpoint = getattr(report_3.details, "strategy_synthesis", None)
        self.assertIsNotNone(
            syn_3_endpoint,
            "GET /history/{record_id} must forward details.strategy_synthesis",
        )
        self.assertEqual(report_3.details.model_dump()["strategy_synthesis"], expected)

    # ------------------------------------------------------------------
    # Point 4: gating — legacy/None/unknown schema_version -> None
    # ------------------------------------------------------------------

    def test_4_legacy_and_unknown_schema_versions_project_to_null(self) -> None:
        if _build_analysis_report is None or HistoryService is None:
            self.skipTest("projection helpers unavailable in this environment")

        variants = (
            (
                "missing",
                {
                    key: value
                    for key, value in _v1_synthesis_payload().items()
                    if key != "schema_version"
                },
            ),
            ("none", {**_v1_synthesis_payload(), "schema_version": None}),
            (
                "unknown",
                {**_v1_synthesis_payload(), "schema_version": "strategy-synthesis-v9"},
            ),
        )
        for variant, payload in variants:
            with self.subTest(variant=variant):
                raw_result = _raw_result_with(payload)

                details_1 = self._details_via_sync_report(raw_result)
                self.assertIsNone(
                    getattr(details_1, "strategy_synthesis", None),
                    f"path 1 must gate {variant} schema_version to None",
                )

                details_2 = self._details_via_async_db_rebuild(raw_result)
                self.assertIsNone(
                    details_2.get("strategy_synthesis"),
                    f"path 2 must gate {variant} schema_version to None",
                )

                detail_dict = self._detail_via_record_to_detail_dict(raw_result)
                self.assertIsNone(
                    detail_dict.get("strategy_synthesis"),
                    f"path 3 must gate {variant} schema_version to None",
                )

        # No dashboard at all -> None as well.
        details_no_dashboard = self._details_via_sync_report(
            {"stock_code": "600519", "analysis_summary": "s"}
        )
        self.assertIsNone(getattr(details_no_dashboard, "strategy_synthesis", None))

    # ------------------------------------------------------------------
    # Point 5: malformed payloads degrade without a 500
    # ------------------------------------------------------------------

    def test_5_malformed_payloads_degrade_without_error(self) -> None:
        if _build_analysis_report is None or HistoryService is None:
            self.skipTest("projection helpers unavailable in this environment")

        # (a) top-level payload not a dict -> strategy_synthesis None, no raise.
        for bad_payload in ("not-a-dict", 42, ["list"], None):
            with self.subTest(bad_payload=bad_payload):
                raw_result = _raw_result_with(bad_payload)
                details_1 = self._details_via_sync_report(raw_result)
                self.assertIsNone(getattr(details_1, "strategy_synthesis", None))

        # (a2) raw_result itself not a dict (legacy rows) -> None, no raise.
        detail_dict = self._detail_via_record_to_detail_dict("legacy-string-raw")
        self.assertIsNone(detail_dict.get("strategy_synthesis"))

        # (b) non-dict entries in supporting/opposing are filtered.
        payload = _v1_synthesis_payload()
        payload["supporting_skills"] = [
            payload["supporting_skills"][0],
            "junk-string",
            42,
            {"skill_id": "only_id"},
        ]
        payload["opposing_skills"] = ["bare", {"skill_id": "o1", "signal": "buy"}]
        details_1 = self._details_via_sync_report(_raw_result_with(payload))
        syn_b = getattr(details_1, "strategy_synthesis", None)
        self.assertIsNotNone(syn_b, "malformed list entries must not void the payload")
        dumped_b = details_1.model_dump()["strategy_synthesis"]
        supporting = dumped_b["supporting_skills"]
        self.assertEqual(len(supporting), 2, "non-dict entries must be filtered")
        self.assertEqual(
            supporting[0], _expected_projection()["supporting_skills"][0]
        )
        self.assertEqual(
            supporting[1],
            {
                "skill_id": "only_id",
                "agent_name": None,
                "signal": None,
                "confidence": None,
                "reasoning": None,
                "score_adjustment": None,
                "conditions_met": None,
                "invalid_signal": None,
            },
        )
        self.assertEqual(len(dumped_b["opposing_skills"]), 1)

        # (c) structurally illegal nested fields -> that field None, rest intact.
        payload = _v1_synthesis_payload()
        payload["signal_distribution"] = {
            "bullish": "oops",
            "neutral": {"count": 1, "weight_share": 0.4},
            "bearish": {"count": 0, "weight_share": 0.0},
        }
        payload["primary_dissent"] = {
            "skill_id": "skill_buy",
            "agent_name": "strategy_buy",
            "signal": "buy",
        }
        details_1 = self._details_via_sync_report(_raw_result_with(payload))
        syn_c = getattr(details_1, "strategy_synthesis", None)
        self.assertIsNotNone(
            syn_c, "illegal nested fields must not void the whole payload"
        )
        dumped_c = details_1.model_dump()["strategy_synthesis"]
        self.assertIsNone(dumped_c["signal_distribution"])
        self.assertIsNone(dumped_c["primary_dissent"])
        self.assertEqual(dumped_c["final_signal"], "hold")
        self.assertEqual(dumped_c["confidence"], 0.6517)
        self.assertEqual(dumped_c["conflict_count"], 1)
        self.assertEqual(dumped_c["supporting_skills"], _expected_projection()["supporting_skills"])
        self.assertEqual(dumped_c["signal_distribution"], None)

        # (c2) a distribution dict with a non-integer count is illegal too.
        payload = _v1_synthesis_payload()
        payload["signal_distribution"]["bearish"] = {"count": "0", "weight_share": 0.0}
        details_1 = self._details_via_sync_report(_raw_result_with(payload))
        dumped_c2 = details_1.model_dump()["strategy_synthesis"]
        self.assertIsNone(dumped_c2["signal_distribution"])
        self.assertEqual(dumped_c2["final_signal"], "hold")

        # (c3) a dissent with a non-numeric confidence is illegal.
        payload = _v1_synthesis_payload()
        payload["primary_dissent"] = {
            "skill_id": "skill_buy",
            "agent_name": "strategy_buy",
            "signal": "buy",
            "confidence": "high",
            "reasoning": "breakout",
        }
        details_1 = self._details_via_sync_report(_raw_result_with(payload))
        dumped_c3 = details_1.model_dump()["strategy_synthesis"]
        self.assertIsNone(dumped_c3["primary_dissent"])
        self.assertEqual(dumped_c3["final_signal"], "hold")

    def test_5b_nested_revision_and_conflict_fields_degrade_to_null(self) -> None:
        """OR-COR-12e5b2ef / OR-COR-4b4fdbb2: nested display fields are type-guarded.

        A malformed ``revision_projection.projected_signal`` (object instead of
        string) and malformed conflict-entry fields (``severity`` /
        ``description_key`` objects, non-list ``participants``) must project to
        ``None`` so the Web card degrades field by field instead of crashing on
        render. Sibling well-formed values and the rest of the payload stay
        intact; the schema keeps ``Dict[str, Any]`` declarations (values are
        sanitized, not reshaped).
        """
        if _build_analysis_report is None:
            self.skipTest("projection helpers unavailable in this environment")

        payload = _v1_synthesis_payload()
        payload["revision_projection"] = {
            "status": "computed",
            "mode": "preview_only",
            "projected_signal": {"bad": "buy"},
            "projected_confidence": "high",
            "projected_conflict_count": "two",
            "final_signal_overridden": "no",
        }
        payload["conflicts"] = [
            {
                "conflict_type": {"kind": "direction"},
                "severity": {"level": "high"},
                "description_key": ["strategy_conflict.directional_opposition"],
                "participants": "skill_hold,skill_buy",
                "metadata": {"keep": "me"},
            },
            "junk-entry",
            42,
        ]

        details_1 = self._details_via_sync_report(_raw_result_with(payload))
        syn = getattr(details_1, "strategy_synthesis", None)
        self.assertIsNotNone(syn, "malformed nested fields must not void the payload")
        dumped = details_1.model_dump()["strategy_synthesis"]

        revision = dumped["revision_projection"]
        self.assertIsNotNone(
            revision, "malformed nested fields must not void the preview block"
        )
        self.assertIsNone(revision["projected_signal"])
        self.assertIsNone(revision["projected_confidence"])
        self.assertIsNone(revision["projected_conflict_count"])
        self.assertIsNone(revision["final_signal_overridden"])
        self.assertEqual(revision["status"], "computed")
        self.assertEqual(revision["mode"], "preview_only")

        conflicts = dumped["conflicts"]
        self.assertEqual(len(conflicts), 1, "non-dict conflict entries must be filtered")
        conflict = conflicts[0]
        self.assertIsNone(conflict["conflict_type"])
        self.assertIsNone(conflict["severity"])
        self.assertIsNone(conflict["description_key"])
        self.assertIsNone(conflict["participants"])
        self.assertEqual(conflict["metadata"], {"keep": "me"})

        # Well-formed sibling payload fields stay intact and the JSON surface
        # serializes the sanitized nulls without raising.
        self.assertEqual(dumped["final_signal"], "hold")
        self.assertEqual(dumped["confidence"], 0.6517)
        details_1.model_dump_json()

    # ------------------------------------------------------------------
    # Point 6: raw_result is preserved untouched
    # ------------------------------------------------------------------

    def test_6_raw_result_is_preserved_untouched(self) -> None:
        if _build_analysis_report is None or get_analysis_status is None:
            self.skipTest("analysis endpoint helpers unavailable in this environment")

        raw_result = _raw_result_with(_v1_synthesis_payload())

        details_1 = self._details_via_sync_report(raw_result)
        self.assertEqual(details_1.raw_result, raw_result)
        self.assertEqual(
            details_1.raw_result["dashboard"]["strategy_synthesis"][
                "non_whitelisted_field"
            ],
            "internal-only",
            "raw_result must keep the original dashboard payload",
        )

        details_2 = self._details_via_async_db_rebuild(raw_result)
        self.assertEqual(details_2["raw_result"], raw_result)

    # ------------------------------------------------------------------
    # Point 7: no new OpenAPI paths
    # ------------------------------------------------------------------

    def test_7_no_new_openapi_paths(self) -> None:
        if create_app is None:
            self.skipTest("fastapi is not installed in this test environment")

        paths = (
            set(create_app().openapi()["paths"]) - UPSTREAM_RETIRED_OPENAPI_PATHS
        )
        self.assertEqual(
            paths,
            BASELINE_OPENAPI_PATHS,
            "the typed projection must not add or remove API paths",
        )
        self.assertNotIn("/api/v1/analysis/strategy-synthesis", paths)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
