# -*- coding: utf-8 -*-
"""Tests for main(argv=...) compatibility and unified `--doctor [--json]` diagnostics."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import main
from src.config import Config
from src.services.doctor_service import format_doctor_report, run_doctor_diagnostics


class DoctorCliTestCase(unittest.TestCase):
    def test_parse_arguments_accepts_explicit_argv(self) -> None:
        args = main.parse_arguments(["--doctor", "--json", "--debug"])
        self.assertTrue(args.doctor)
        self.assertTrue(args.json)
        self.assertTrue(args.debug)

    def test_doctor_outputs_valid_json_and_redacts_secrets(self) -> None:
        secret_key = "sk-super-secret-gemini-token-9999"
        webhook_url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret-hook-12345"

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=["600519"],
                gemini_api_keys=[secret_key],
                litellm_model="gemini/gemini-3.6-flash",
                llm_model_list=[
                    {
                        "model_name": "gemini/gemini-3.6-flash",
                        "litellm_params": {
                            "model": "gemini/gemini-3.6-flash",
                            "api_key": secret_key,
                        },
                    }
                ],
                wechat_webhook_url=webhook_url,
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            buf = io.StringIO()
            with patch("main.get_config", return_value=cfg):
                with redirect_stdout(buf):
                    exit_code = main.main(["--doctor", "--json"])

        raw_out = buf.getvalue()
        self.assertNotIn(secret_key, raw_out)
        self.assertNotIn("secret-hook-12345", raw_out)
        parsed = json.loads(raw_out)
        self.assertEqual(exit_code, 0)
        self.assertIn(parsed["status"], ("ok", "warn"))
        self.assertTrue(parsed["checks"]["llm"]["ready"])
        self.assertTrue(parsed["checks"]["storage"]["database_dir_writable"])
        self.assertEqual(parsed["checks"]["watchlist"]["count"], 1)

    def test_doctor_returns_nonzero_when_llm_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=["600519"],
                gemini_api_keys=[],
                llm_model_list=[],
                litellm_model="",
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            buf = io.StringIO()
            with patch("main.get_config", return_value=cfg):
                with redirect_stdout(buf):
                    exit_code = main.main(["--doctor"])

        self.assertEqual(exit_code, 1)
        out = buf.getvalue()
        self.assertIn("DSA Doctor Diagnostic Status: ERROR", out)
        self.assertIn("[llm] status=error", out)

    def test_format_doctor_report_handles_clean_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=["600519"],
                gemini_api_keys=["AIzaFakeKey1234567890"],
                litellm_model="gemini/gemini-3.6-flash",
                wechat_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            report = run_doctor_diagnostics(cfg)
            text = format_doctor_report(report)
            self.assertNotIn("AIzaFakeKey1234567890", text)
            self.assertIn("DSA Doctor Diagnostic Status:", text)

    def test_json_without_doctor_fails_fast_with_exit_code_2(self) -> None:
        err_buf = io.StringIO()
        with patch("sys.stderr", err_buf):
            code = main.main(["--json"])
        self.assertEqual(code, 2)
        self.assertIn("--doctor", err_buf.getvalue())

    def test_doctor_llm_ready_matches_validate_structured_and_no_double_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=["600519"],
                litellm_model="gemini/gemini-3.6-flash",
                llm_model_list=[],
                gemini_api_keys=[],
                wechat_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            report = run_doctor_diagnostics(cfg)
        self.assertFalse(report["checks"]["llm"]["ready"])
        self.assertEqual(report["checks"]["llm"]["status"], "error")
        self.assertEqual(report["summary"]["errors"], len(report["checks"]["config"]["errors"]))

    def test_doctor_redacts_serpapi_and_litellm_model_list_keys(self) -> None:
        serp_secret = "serp-secret-token-xyz"
        router_secret = "sk-router-secret-9999"
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=["600519"],
                serpapi_keys=[serp_secret],
                llm_model_list=[
                    {
                        "model_name": "gemini/gemini-3.6-flash",
                        "litellm_params": {"model": "gemini/gemini-3.6-flash", "api_key": router_secret},
                    }
                ],
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            with patch(
                "src.services.doctor_service.run_notification_diagnostics",
                side_effect=lambda _c: run_doctor_diagnostics_stub_notify(serp_secret, router_secret),
            ):
                report = run_doctor_diagnostics(cfg)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(serp_secret, serialized)
        self.assertNotIn(router_secret, serialized)

    def test_doctor_treats_unconfigured_notifications_as_warning_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=["600519"],
                gemini_api_keys=["AIzaFakeKey1234567890"],
                litellm_model="gemini/gemini-3.6-flash",
                llm_model_list=[
                    {
                        "model_name": "gemini/gemini-3.6-flash",
                        "litellm_params": {
                            "model": "gemini/gemini-3.6-flash",
                            "api_key": "AIzaFakeKey1234567890",
                        },
                    }
                ],
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            buf = io.StringIO()
            with patch("main.get_config", return_value=cfg):
                with redirect_stdout(buf):
                    exit_code = main.main(["--doctor", "--json"])

        parsed = json.loads(buf.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(parsed["status"], "warn")
        self.assertEqual(parsed["summary"]["errors"], 0)
        self.assertEqual(parsed["summary"]["warnings"], 1)
        self.assertEqual(parsed["checks"]["notifications"]["status"], "warn")
        self.assertEqual(parsed["checks"]["notifications"]["errors"], [])

    def test_doctor_flags_partially_configured_notification_channel_as_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=["600519"],
                gemini_api_keys=["AIzaFakeKey1234567890"],
                litellm_model="gemini/gemini-3.6-flash",
                llm_model_list=[
                    {
                        "model_name": "gemini/gemini-3.6-flash",
                        "litellm_params": {
                            "model": "gemini/gemini-3.6-flash",
                            "api_key": "AIzaFakeKey1234567890",
                        },
                    }
                ],
                telegram_bot_token="123456:ABCDEF-secret-token",
                telegram_chat_id=None,
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            buf = io.StringIO()
            with patch("main.get_config", return_value=cfg):
                with redirect_stdout(buf):
                    exit_code = main.main(["--doctor", "--json"])

        parsed = json.loads(buf.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(parsed["status"], "error")
        self.assertEqual(parsed["checks"]["notifications"]["status"], "error")
        self.assertGreaterEqual(len(parsed["checks"]["notifications"]["errors"]), 1)

    def test_doctor_allows_market_review_without_a_watchlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=[],
                llm_model_list=[{
                    "model_name": "test-model",
                    "litellm_params": {"model": "gemini/test-model", "api_key": "test-api-key"},
                }],
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            self.assertTrue(any(i.field == "STOCK_LIST" and i.severity == "error"
                                for i in cfg.validate_structured()))
            buf = io.StringIO()
            with patch("main.get_config", return_value=cfg), redirect_stdout(buf):
                exit_code = main.main(["--doctor", "--json"])

        parsed = json.loads(buf.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(parsed["status"], "warn")
        self.assertEqual(parsed["summary"]["errors"], 0)
        self.assertEqual(parsed["summary"]["warnings"], 2)
        self.assertEqual(parsed["checks"]["watchlist"]["status"], "warn")
        self.assertIn("STOCK_LIST", parsed["checks"]["watchlist"]["message"])
        self.assertIn("STOCK_LIST", format_doctor_report(parsed))


def run_doctor_diagnostics_stub_notify(serp_secret: str, router_secret: str):
    from src.services.notification_diagnostics import NotificationDiagnosticIssue, NotificationDiagnosticResult

    return NotificationDiagnosticResult(
        configured_channels=(),
        errors=(
            NotificationDiagnosticIssue(
                severity="error",
                code="test",
                key="TEST",
                message=f"leaked {serp_secret} and {router_secret}",
            ),
        ),
        warnings=(),
        info=(),
    )


if __name__ == "__main__":
    unittest.main()
