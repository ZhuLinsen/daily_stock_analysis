# -*- coding: utf-8 -*-
"""Tests for minimal .env config generator and `--init` CLI wizard."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from dotenv import dotenv_values

import main
from src.services.init_config_service import (
    PROVIDER_ORDER,
    NOTIFY_ORDER,
    generate_minimal_env_content,
    run_init_wizard,
    write_minimal_env,
)


class InitConfigServiceTestCase(unittest.TestCase):
    def test_generate_minimal_env_supports_all_providers_and_notifications(self) -> None:
        for provider in PROVIDER_ORDER:
            for notify in NOTIFY_ORDER:
                content = generate_minimal_env_content(
                    provider=provider,
                    stocks="600519,hk00700,AAPL",
                    notify=notify,
                )
                self.assertIn("STOCK_LIST=600519,hk00700,AAPL", content)
                self.assertNotIn("your_api_key", content.lower())
                self.assertNotIn("xxxx", content.lower())

                with tempfile.TemporaryDirectory() as tmpdir:
                    path = Path(tmpdir) / ".env"
                    path.write_text(content, encoding="utf-8")
                    parsed = dotenv_values(path)
                    self.assertEqual(parsed.get("STOCK_LIST"), "600519,hk00700,AAPL")

    def test_sanitizes_newlines_to_prevent_env_injection(self) -> None:
        content = generate_minimal_env_content(
            provider="deepseek",
            api_key="sk-123\nADMIN_AUTH_ENABLED=false",
            stocks="600519\nEVIL=1",
        )
        self.assertNotIn("\nADMIN_AUTH_ENABLED=", content)
        self.assertNotIn("\nEVIL=", content)

    def test_write_refuses_overwrite_unless_forced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / ".env"
            target.write_text("STOCK_LIST=000001\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                write_minimal_env(target, "STOCK_LIST=600519\n", force=False)

            res = write_minimal_env(target, "STOCK_LIST=600519\n", force=True)
            self.assertTrue(res["ok"])
            self.assertTrue(res["overwritten"])
            self.assertEqual(target.read_text(encoding="utf-8"), "STOCK_LIST=600519\n")

    def test_interactive_wizard_accepts_mock_prompts(self) -> None:
        answers = iter(["deepseek", "sk-real-demo-123", "600519,AAPL", "feishu", "https://open.feishu.cn/hook/abc"])
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / ".env.test"
            res = run_init_wizard(
                output_path=out_file,
                non_interactive=False,
                input_fn=lambda _prompt: next(answers),
            )
            self.assertTrue(res["ok"])
            self.assertTrue(res["interactive"])
            self.assertEqual(res["provider"], "deepseek")
            self.assertEqual(res["notify"], "feishu")
            written = out_file.read_text(encoding="utf-8")
            self.assertIn("DEEPSEEK_API_KEY=sk-real-demo-123", written)
            self.assertIn("FEISHU_WEBHOOK_URL=https://open.feishu.cn/hook/abc", written)

    def test_cli_init_non_interactive_json_and_overwrite_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / ".env"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main.main([
                    "--init",
                    "--non-interactive",
                    "--init-provider",
                    "modelflare",
                    "--stocks",
                    "600519,hk00700",
                    "--init-output",
                    str(out_file),
                    "--json",
                ])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["provider"], "modelflare")
            self.assertEqual(payload["stocks"], "600519,hk00700")
            self.assertIn("MODELFLARE_KEY=", out_file.read_text(encoding="utf-8"))

            rc_conflict = main.main([
                "--init",
                "--non-interactive",
                "--init-output",
                str(out_file),
            ])
            self.assertEqual(rc_conflict, 2)
