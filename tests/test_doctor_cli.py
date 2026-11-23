# -*- coding: utf-8 -*-
"""Tests for main(argv=...) compatibility and unified `--doctor [--json]` diagnostics."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
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

    def test_doctor_reports_missing_local_cli_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=["600519"],
                generation_backend="codex_cli",
                generation_fallback_backend="",
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            with patch("src.llm.local_cli_backend.shutil.which", return_value=None):
                report = run_doctor_diagnostics(cfg)

        self.assertEqual(report["status"], "error")
        self.assertEqual(report["checks"]["llm"]["status"], "error")
        self.assertFalse(report["checks"]["llm"]["ready"])
        self.assertEqual(report["checks"]["config"]["status"], "error")
        self.assertTrue(any(
            item["field"] == "GENERATION_BACKEND"
            for item in report["checks"]["config"]["errors"]
        ))

    def test_doctor_rejects_malformed_llm_channel_without_legacy_fallback(self) -> None:
        env = {
            "LLM_CHANNELS": "custom",
            "LLM_CUSTOM_BASE_URL": "http://localhost:bad/v1",
            "LLM_CUSTOM_API_KEY": "sk-channel-secret-123456789",
            "LLM_CUSTOM_MODELS": "openai/test-model",
            "LITELLM_MODEL": "openai/test-model",
            "STOCK_LIST": "600519",
        }
        Config.reset_instance()
        try:
            with patch.dict(os.environ, env, clear=True):
                cfg = Config.get_instance()
                report = run_doctor_diagnostics(cfg)
        finally:
            Config.reset_instance()

        self.assertEqual(report["status"], "error")
        self.assertFalse(report["checks"]["llm"]["ready"])
        self.assertTrue(any(
            item["field"] == "LLM_CUSTOM_BASE_URL"
            for item in report["checks"]["config"]["errors"]
        ))
        rendered = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("sk-channel-secret-123456789", rendered)

    def test_doctor_promotes_notification_partial_configuration_to_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=["600519"],
                ntfy_token="ntfy-secret-123456789",
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            report = run_doctor_diagnostics(cfg)

        self.assertEqual(report["checks"]["notifications"]["status"], "error")
        self.assertEqual(report["status"], "error")
        self.assertTrue(any(
            item["key"] == "NTFY_URL"
            for item in report["checks"]["notifications"]["errors"]
        ))
        self.assertNotIn("ntfy-secret-123456789", json.dumps(report, ensure_ascii=False))

    def test_doctor_reflects_primary_model_and_generation_backend_errors_in_llm_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=["600519"],
                gemini_api_keys=["AIzaFakeKey1234567890"],
                generation_backend="invalid_backend",
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
                wechat_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            report = run_doctor_diagnostics(cfg)

        self.assertEqual(report["status"], "error")
        self.assertFalse(report["checks"]["llm"]["ready"])
        self.assertEqual(report["checks"]["llm"]["status"], "error")

    def test_doctor_rejects_regular_file_parent_and_directory_database_path(self) -> None:
        """Counterexample from PR #2560 review: DATABASE_PATH=./main.py/stock_analysis.db."""
        with tempfile.TemporaryDirectory() as tmpdir:
            blocker_file = Path(tmpdir) / "main.py"
            blocker_file.write_text("# regular file", encoding="utf-8")

            cfg_file_parent = Config(
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
                wechat_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
                database_path=str(blocker_file / "stock_analysis.db"),
                log_dir=tmpdir,
            )
            buf = io.StringIO()
            with patch("main.get_config", return_value=cfg_file_parent):
                with redirect_stdout(buf):
                    exit_code = main.main(["--doctor", "--json"])

            parsed = json.loads(buf.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertEqual(parsed["status"], "error")
            self.assertEqual(parsed["checks"]["storage"]["status"], "error")
            self.assertFalse(parsed["checks"]["storage"]["database_dir_writable"])
            self.assertGreaterEqual(parsed["summary"]["errors"], 1)

            # DATABASE_PATH pointing directly to a directory must also fail storage check.
            cfg_dir_db = Config(
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
                wechat_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
                database_path=tmpdir,
                log_dir=tmpdir,
            )
            report_dir_db = run_doctor_diagnostics(cfg_dir_db)
            self.assertEqual(report_dir_db["checks"]["storage"]["status"], "error")
            self.assertFalse(report_dir_db["checks"]["storage"]["database_dir_writable"])

    def test_doctor_handles_malformed_ipv6_webhook_url_without_crashing(self) -> None:
        """Counterexample from PR #2560 review: WECHAT_WEBHOOK_URL=https://[ must yield JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_overrides = {
                "STOCK_LIST": "600519",
                "GEMINI_API_KEY": "AIzaFakeKey1234567890",
                "LITELLM_MODEL": "gemini/gemini-3.6-flash",
                "WECHAT_WEBHOOK_URL": "https://[",
                "NTFY_URL": "https://[",
                "GOTIFY_URL": "https://[",
                "DATABASE_PATH": f"{tmpdir}/stock_analysis.db",
                "LOG_DIR": tmpdir,
            }
            Config.reset_instance()
            try:
                with patch.dict(os.environ, env_overrides, clear=False):
                    Config.reset_instance()
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        exit_code = main.main(["--doctor", "--json"])
            finally:
                Config.reset_instance()

        parsed = json.loads(buf.getvalue())
        self.assertIn(exit_code, (0, 1))
        self.assertIn("checks", parsed)
        warning_fields = {w.get("field") for w in parsed["checks"]["config"]["warnings"]}
        self.assertIn("WECHAT_WEBHOOK_URL", warning_fields)

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
                side_effect=lambda _c: _stub_notify(serp_secret, router_secret),
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

    def test_doctor_deduplicates_invalid_ntfy_port_and_empty_stock_list(self) -> None:
        """Invalid ntfy port and empty STOCK_LIST must not crash or double-count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=[],
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
                ntfy_url="http://host:99999/topic",
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            report = run_doctor_diagnostics(cfg)

        error_fields = {e.get("field") for e in report["checks"]["config"]["errors"]}
        self.assertIn("STOCK_LIST", error_fields)
        self.assertIn("NTFY_URL", error_fields)
        self.assertEqual(report["summary"]["errors"], len(report["checks"]["config"]["errors"]))
        self.assertEqual(report["summary"]["warnings"], len(report["checks"]["config"]["warnings"]))

    def test_doctor_standalone_notice_keeps_json_stdout_clean(self) -> None:
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
                wechat_webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
                database_path=f"{tmpdir}/stock_analysis.db",
                log_dir=tmpdir,
            )
            out_buf = io.StringIO()
            err_buf = io.StringIO()
            with patch("main.get_config", return_value=cfg):
                with redirect_stdout(out_buf), patch("sys.stderr", err_buf):
                    exit_code = main.main(["--doctor", "--json", "--stocks", "600519"])

        self.assertEqual(exit_code, 0)
        parsed = json.loads(out_buf.getvalue())
        self.assertEqual(parsed["status"], "ok")
        self.assertIn("--stocks", err_buf.getvalue())

    def test_system_doctor_api_endpoint_returns_redacted_summary(self) -> None:
        from fastapi.testclient import TestClient
        from api.app import create_app

        secret_key = "sk-doctor-api-secret-key-88888"
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(
                stock_list=["600519"],
                gemini_api_keys=[secret_key],
                litellm_model="gemini/gemini-2.5-flash",
                llm_model_list=[
                    {
                        "model_name": "gemini/gemini-2.5-flash",
                        "litellm_params": {"model": "gemini/gemini-2.5-flash", "api_key": secret_key},
                    }
                ],
                database_path=f"{tmpdir}/doctor.db",
                log_dir=tmpdir,
            )
            client = TestClient(create_app())
            with patch("src.config.get_config", return_value=cfg):
                resp = client.get("/api/v1/system/doctor")

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(secret_key, resp.text)
        payload = resp.json()
        self.assertTrue(payload["checks"]["llm"]["ready"])
        self.assertEqual(payload["checks"]["watchlist"]["count"], 1)

    def test_doctor_subprocess_with_llm_channels_makes_zero_network_requests(self) -> None:
        repo_root = str(Path(__file__).resolve().parents[1])
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("", encoding="utf-8")
            probe_code = """
import json, os, socket
def _blocked_connect(*args, **kwargs):
    raise AssertionError(f"unexpected outbound network connect: {args!r}")
socket.socket.connect = _blocked_connect
try:
    import httpx
    httpx.get = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("unexpected httpx.get"))
except Exception:
    pass
import main
raise SystemExit(main.main(["--doctor", "--json"]))
"""
            env = {k: v for k, v in os.environ.items() if k != "LITELLM_LOCAL_MODEL_COST_MAP"}
            env.update({
                "PYTHONPATH": repo_root,
                "ENV_FILE": str(env_file),
                "STOCK_LIST": "600519",
                "LLM_CHANNELS": "custom",
                "LLM_CUSTOM_PROTOCOL": "openai",
                "LLM_CUSTOM_BASE_URL": "https://api.example.com/v1",
                "LLM_CUSTOM_API_KEY": "sk-cold-start-offline-secret-1234",
                "LLM_CUSTOM_MODELS": "gpt-4o-mini",
                "DATABASE_PATH": f"{tmpdir}/doctor.db",
                "LOG_DIR": tmpdir,
            })
            proc = subprocess.run(
                [sys.executable, "-c", probe_code],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, msg=f"stderr={proc.stderr}\nstdout={proc.stdout}")
            parsed = json.loads(proc.stdout)
            self.assertIn(parsed["status"], ("ok", "warn"))
            self.assertTrue(parsed["checks"]["llm"]["ready"])
            self.assertNotIn("sk-cold-start-offline-secret-1234", proc.stdout)


def _stub_notify(serp_secret: str, router_secret: str):
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
