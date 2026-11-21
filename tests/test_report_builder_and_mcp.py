# -*- coding: utf-8 -*-
"""Tests for shared report builder parity and optional read-only stdio MCP server."""

from __future__ import annotations

import builtins
import io
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.config import Config
from src.mcp_server import McpReadOnlySurface, main as mcp_main
from src.services.report_builder_service import build_analysis_report_payload


class ReportBuilderParityTestCase(unittest.TestCase):
    def test_service_and_rest_report_payloads_match(self) -> None:
        from api.v1.schemas.history import (
            AnalysisReport,
            ReportDetails,
            ReportMeta,
            ReportStrategy,
            ReportSummary,
        )

        report_data = {
            "meta": {
                "query_id": "q-parity-1",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report_type": "detailed",
                "report_language": "zh",
                "created_at": "2026-11-18T10:00:00",
                "current_price": 1500.0,
                "change_pct": 1.25,
                "model_used": "gemini/gemini-3.6-flash",
            },
            "summary": {
                "analysis_summary": "趋势稳健，关注回踩机会",
                "operation_advice": "买入",
                "trend_prediction": "看多",
                "sentiment_score": 78,
                "sentiment_label": "乐观",
            },
            "strategy": {
                "ideal_buy": 1480.0,
                "secondary_buy": "1450.0",
                "stop_loss": 1420.0,
                "take_profit": 1620.0,
            },
            "details": {
                "news_content": "基本面稳健",
                "raw_result": {
                    "operation_advice": "买入",
                    "sentiment_score": 78,
                    "action": "buy",
                },
            },
        }
        service_payload = build_analysis_report_payload(
            report_data=report_data,
            query_id="q-parity-1",
            stock_code="600519",
            stock_name="贵州茅台",
        )
        rest_model = AnalysisReport(
            meta=ReportMeta(**service_payload["meta"]),
            summary=ReportSummary(**service_payload["summary"]),
            strategy=ReportStrategy(**service_payload["strategy"]),
            details=ReportDetails(**service_payload["details"]),
            structured_report=service_payload.get("structured_report"),
        )
        rest_payload = rest_model.model_dump(mode="json")

        self.assertEqual(rest_payload["meta"], service_payload["meta"])
        self.assertEqual(rest_payload["summary"], service_payload["summary"])
        self.assertEqual(rest_payload["strategy"], service_payload["strategy"])
        self.assertEqual(rest_payload["structured_report"], service_payload["structured_report"])

        # Also validate endpoint helper directly when full API runtime deps are available.
        try:
            from api.v1.endpoints.analysis import _build_analysis_report
        except ModuleNotFoundError:
            return
        endpoint_model = _build_analysis_report(
            report_data=report_data,
            query_id="q-parity-1",
            stock_code="600519",
            stock_name="贵州茅台",
        )
        self.assertEqual(endpoint_model.model_dump(mode="json"), rest_payload)


class McpReadOnlySurfaceTestCase(unittest.TestCase):
    def test_mcp_surface_excludes_portfolio_and_macro_by_default(self) -> None:
        cfg = Config(stock_list=["600519"])
        surface = McpReadOnlySurface(config=cfg, include_macro=False)
        tool_names = {t["name"] for t in surface.list_tools()}

        self.assertNotIn("get_portfolio_snapshot", tool_names)
        self.assertFalse(any(name.startswith("fxmacrodata_") for name in tool_names))
        self.assertIn("get_realtime_quote", tool_names)
        self.assertIn("resolve_stock", tool_names)
        self.assertIn("start_stock_analysis", tool_names)
        self.assertIn("get_analysis_status", tool_names)
        self.assertIn("get_latest_report", tool_names)

        blocked = surface.call_tool("get_portfolio_snapshot", {})
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error"], "tool_not_allowed")

    def test_mcp_resolve_stock_and_start_analysis_defaults_no_notify(self) -> None:
        cfg = Config(stock_list=["600519"])
        surface = McpReadOnlySurface(config=cfg)

        idx = surface.call_tool("resolve_stock", {"query": "sh000016"})
        self.assertTrue(idx["ok"])
        self.assertEqual(idx["asset_type"], "index")

        bad_type = surface.call_tool(
            "start_stock_analysis",
            {"stock_code": "600519", "report_type": "invalid_mode"},
        )
        self.assertFalse(bad_type["ok"])
        self.assertEqual(bad_type["error"], "invalid_arguments")

        fake_task = SimpleNamespace(
            task_id="task-mcp-1",
            stock_code="600519",
            status=SimpleNamespace(value="pending"),
        )
        fake_queue = MagicMock()
        fake_queue.submit_tasks_batch.return_value = ([fake_task], [])
        with patch("src.services.task_queue.get_task_queue", return_value=fake_queue):
            started = surface.call_tool("start_stock_analysis", {"stock_code": "600519"})

        self.assertTrue(started["ok"])
        self.assertFalse(started["notify"])
        self.assertEqual(started["task_id"], "task-mcp-1")
        self.assertFalse(fake_queue.submit_tasks_batch.call_args.kwargs["notify"])

    def test_mcp_start_analysis_handles_duplicate_and_rejected_submissions(self) -> None:
        cfg = Config(stock_list=["600519"])
        surface = McpReadOnlySurface(config=cfg)

        dup = SimpleNamespace(existing_task_id="task-existing-1")
        fake_queue = MagicMock()
        fake_queue.submit_tasks_batch.return_value = ([], [dup])
        with patch("src.services.task_queue.get_task_queue", return_value=fake_queue):
            res_dup = surface.call_tool("start_stock_analysis", {"stock_code": "600519"})
        self.assertTrue(res_dup["ok"])
        self.assertTrue(res_dup["duplicate"])
        self.assertEqual(res_dup["task_id"], "task-existing-1")

        fake_queue.submit_tasks_batch.return_value = ([], [])
        with patch("src.services.task_queue.get_task_queue", return_value=fake_queue):
            res_rej = surface.call_tool("start_stock_analysis", {"stock_code": "600519"})
        self.assertFalse(res_rej["ok"])
        self.assertEqual(res_rej["error"], "submission_rejected")

    def test_mcp_get_latest_report_and_status(self) -> None:
        cfg = Config(stock_list=["600519"])
        surface = McpReadOnlySurface(config=cfg)

        fake_queue = MagicMock()
        fake_queue.get_task.return_value = None
        with patch("src.services.task_queue.get_task_queue", return_value=fake_queue):
            missing = surface.call_tool("get_analysis_status", {"task_id": "missing"})
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"], "not_found")

        found_task = MagicMock()
        found_task.to_dict.return_value = {
            "task_id": "task-mcp-2",
            "status": "completed",
            "api_key": "sk-secret-value-1234567890",
        }
        fake_queue.get_task.return_value = found_task
        with patch("src.services.task_queue.get_task_queue", return_value=fake_queue):
            found = surface.call_tool("get_analysis_status", {"task_id": "task-mcp-2"})
        self.assertTrue(found["ok"])
        self.assertEqual(found["task_id"], "task-mcp-2")
        self.assertEqual(found["status"], "completed")
        self.assertNotIn("sk-secret-value-1234567890", str(found))

        with patch(
            "src.services.report_builder_service.get_latest_analysis_report_payload",
            return_value={
                "meta": {"stock_code": "600519"},
                "summary": {"action": "buy", "api_key": "sk-report-secret-1234567890"},
            },
        ):
            latest = surface.call_tool("get_latest_report", {"stock_code": "600519"})
        self.assertTrue(latest["ok"])
        self.assertEqual(latest["report"]["meta"]["stock_code"], "600519")
        self.assertNotIn("sk-report-secret-1234567890", str(latest))

    def test_mcp_cli_reports_install_hint_when_optional_mcp_missing(self) -> None:
        real_import = builtins.__import__

        def _block_mcp(name, *args, **kwargs):
            if name == "mcp" or name.startswith("mcp."):
                raise ImportError("No module named 'mcp'")
            return real_import(name, *args, **kwargs)

        err_buf = io.StringIO()
        with patch("builtins.__import__", side_effect=_block_mcp), redirect_stderr(err_buf):
            exit_code = mcp_main([])

        self.assertEqual(exit_code, 2)
        self.assertIn('pip install "mcp>=1.0.0"', err_buf.getvalue())


if __name__ == "__main__":
    unittest.main()
