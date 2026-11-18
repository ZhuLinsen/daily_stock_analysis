# -*- coding: utf-8 -*-
"""Tests for [C2] report builder parity, [C3] thin `dsa` CLI, and [C4] read-only MCP surface."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.v1.endpoints.analysis import _build_analysis_report
from src.cli.app import main as cli_main
from src.cli.env import apply_dsa_home_env
from src.cli.mcp_server import McpReadOnlySurface, _build_mcp_server
from src.config import Config
from src.services.report_builder_service import build_analysis_report_payload


class ReportBuilderParityTestCase(unittest.TestCase):
    def test_rest_and_service_report_payloads_match_100_percent(self) -> None:
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
        rest_model = _build_analysis_report(
            report_data=report_data,
            query_id="q-parity-1",
            stock_code="600519",
            stock_name="贵州茅台",
        )
        rest_payload = rest_model.model_dump(mode="json")

        self.assertEqual(rest_payload["meta"], service_payload["meta"])
        self.assertEqual(rest_payload["summary"], service_payload["summary"])
        self.assertEqual(rest_payload["strategy"], service_payload["strategy"])
        self.assertEqual(rest_payload["structured_report"], service_payload["structured_report"])


class DsaHomeEnvTestCase(unittest.TestCase):
    def test_dsa_home_populates_defaults_without_overriding_explicit_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"DSA_HOME": tmpdir}
            apply_dsa_home_env(env)
            self.assertEqual(env["ENV_FILE"], f"{tmpdir}/.env")
            self.assertEqual(env["DATABASE_PATH"], f"{tmpdir}/stock_analysis.db")

            explicit_env = {
                "DSA_HOME": tmpdir,
                "ENV_FILE": "/custom/.env",
                "DATABASE_PATH": "/custom/custom.db",
            }
            apply_dsa_home_env(explicit_env)
            self.assertEqual(explicit_env["ENV_FILE"], "/custom/.env")
            self.assertEqual(explicit_env["DATABASE_PATH"], "/custom/custom.db")

    def test_unset_dsa_home_leaves_env_untouched(self) -> None:
        env = {"OTHER": "1"}
        apply_dsa_home_env(env)
        self.assertEqual(env, {"OTHER": "1"})


class ThinCliTestCase(unittest.TestCase):
    def test_dsa_doctor_json_forwards_to_main(self) -> None:
        with patch("main.main", return_value=0) as mock_main:
            code = cli_main(["doctor", "--json"])
        self.assertEqual(code, 0)
        mock_main.assert_called_once_with(["--doctor", "--json"])

    def test_dsa_analyze_defaults_notify_false_and_outputs_canonical_json(self) -> None:
        fake_raw = {
            "meta": {
                "query_id": "q-cli-1",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report_type": "detailed",
                "created_at": "2026-11-18T10:00:00",
            },
            "summary": {
                "analysis_summary": "测试结论",
                "operation_advice": "观望",
                "sentiment_score": 55,
            },
            "strategy": {"ideal_buy": "1480"},
            "details": {"raw_result": {"operation_advice": "观望", "sentiment_score": 55}},
        }
        fake_service = MagicMock()
        fake_service.analyze_stock.return_value = fake_raw

        buf = io.StringIO()
        with (
            patch("src.services.analysis_service.AnalysisService", return_value=fake_service),
            patch(
                "src.services.report_builder_service.load_sync_fundamental_sources",
                return_value=(None, None, None),
            ),
            redirect_stdout(buf),
        ):
            code = cli_main(["analyze", "600519", "--json"])

        self.assertEqual(code, 0)
        fake_service.analyze_stock.assert_called_once()
        call_kwargs = fake_service.analyze_stock.call_args.kwargs
        self.assertFalse(call_kwargs["send_notification"])
        self.assertEqual(call_kwargs["stock_code"], "600519")
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["meta"]["stock_code"], "600519")
        self.assertEqual(parsed["summary"]["operation_advice"], "观望")

    def test_dsa_signals_json_calls_decision_signal_service(self) -> None:
        fake_svc = MagicMock()
        fake_svc.list_signals.return_value = {"total": 1, "items": [{"stock_code": "600519", "action": "buy"}]}
        buf = io.StringIO()
        with (
            patch("src.services.decision_signal_service.DecisionSignalService", return_value=fake_svc),
            redirect_stdout(buf),
        ):
            code = cli_main(["signals", "--stock", "600519", "--limit", "5", "--json"])

        self.assertEqual(code, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["total"], 1)
        fake_svc.list_signals.assert_called_once_with(
            stock_code="600519",
            action=None,
            status=None,
            page=1,
            page_size=5,
        )

    def test_dsa_ask_json_reuses_agent_chat_executor(self) -> None:
        fake_exec = MagicMock()
        fake_exec.chat.return_value = SimpleNamespace(
            success=True,
            content="茅台短期震荡。",
            total_tokens=120,
            models_used=["gemini/gemini-3.6-flash"],
            error=None,
        )
        buf = io.StringIO()
        with (
            patch("src.agent.factory.build_agent_chat_executor", return_value=fake_exec),
            redirect_stdout(buf),
        ):
            code = cli_main(["ask", "怎么看趋势", "--stock", "600519", "--json"])

        self.assertEqual(code, 0)
        parsed = json.loads(buf.getvalue())
        self.assertTrue(parsed["ok"])
        self.assertIn("茅台短期震荡", parsed["content"])


class McpReadOnlySurfaceTestCase(unittest.TestCase):
    def test_mcp_surface_excludes_portfolio_and_exposes_async_trio(self) -> None:
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

        # Direct call to excluded tool is rejected.
        blocked = surface.call_tool("get_portfolio_snapshot", {})
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error"], "tool_not_allowed")

    def test_mcp_resolve_stock_and_start_analysis_defaults_no_notify(self) -> None:
        cfg = Config(stock_list=["600519"])
        surface = McpReadOnlySurface(config=cfg)

        idx = surface.call_tool("resolve_stock", {"query": "sh000016"})
        self.assertTrue(idx["ok"])
        self.assertEqual(idx["asset_type"], "index")

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

    def test_mcp_server_builder_constructs_valid_lowlevel_server(self) -> None:
        cfg = Config(stock_list=["600519"])
        surface = McpReadOnlySurface(config=cfg)
        server, _ = _build_mcp_server(surface)
        self.assertEqual(server.name, "daily-stock-analysis")


if __name__ == "__main__":
    unittest.main()
