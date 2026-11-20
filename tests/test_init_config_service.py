# -*- coding: utf-8 -*-
"""Tests for minimal .env config generator and `--init` CLI wizard."""

from __future__ import annotations

import io
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from dotenv import dotenv_values

import main
from src.services.init_config_service import (
    PROVIDER_ORDER,
    NOTIFY_ORDER,
    _init_launch_command,
    generate_minimal_env_content,
    run_init_wizard,
    write_minimal_env,
)


class InitConfigServiceTestCase(unittest.TestCase):
    def test_generate_minimal_env_supports_all_providers_and_notifications(self) -> None:
        for provider in PROVIDER_ORDER:
            for notify in NOTIFY_ORDER:
                provider_args = {
                    "base_url": "https://gateway.example/v1",
                    "model": "demo-model",
                } if provider == "openai-compatible" else {}
                notify_args = {
                    "notify_target": "123456:demo-token",
                    "extra_notify_id": "-1001234567890",
                } if notify == "telegram" else {}
                content = generate_minimal_env_content(
                    provider=provider,
                    stocks="600519,hk00700,AAPL",
                    notify=notify,
                    **provider_args,
                    **notify_args,
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
            stocks="600519\u001cEVIL=1",
        )
        self.assertNotIn("\nADMIN_AUTH_ENABLED=", content)
        self.assertNotIn("\nEVIL=", content)
        self.assertIn("STOCK_LIST=600519", content)
        self.assertNotIn("EVIL=1", dotenv_values(stream=io.StringIO(content)))

    @unittest.skipIf(os.name == "nt", "POSIX mode bits")
    def test_generated_file_is_private_and_force_replace_preserves_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / ".env"
            result = write_minimal_env(target, "STOCK_LIST=600519\n")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(result["bytes"], target.stat().st_size)

            write_minimal_env(target, "STOCK_LIST=300750\n", force=True)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(target.read_text(encoding="utf-8"), "STOCK_LIST=300750\n")

    @unittest.skipIf(os.name == "nt", "POSIX mode bits")
    def test_posix_write_aborts_if_filesystem_keeps_read_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / ".env"
            chmod = os.fchmod
            with mock.patch("os.fchmod", side_effect=lambda fd, _mode: chmod(fd, 0o644)):
                with self.assertRaisesRegex(OSError, "did not apply private file permissions"):
                    write_minimal_env(target, "GEMINI_API_KEY=test-key\n")
            self.assertEqual(list(target.parent.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "Windows file ACLs")
    def test_windows_acl_excludes_inherited_readers_for_create_and_force(self) -> None:
        acl_check = """
        $dir = Get-Acl -LiteralPath $env:TEST_INIT_DIRECTORY
        $everyone = [Security.Principal.SecurityIdentifier]::new('S-1-1-0')
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $everyone, 'Read', 'ObjectInherit', 'None', 'Allow')
        $dir.AddAccessRule($rule)
        Set-Acl -LiteralPath $env:TEST_INIT_DIRECTORY -AclObject $dir
        """
        verify_acl = """
        $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $acl = Get-Acl -LiteralPath $env:TEST_INIT_FILE
        $rules = $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])
        if (!$acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]) -ne $sid -or
            $rules.Count -ne 1 -or $rules[0].IdentityReference -ne $sid -or $rules[0].IsInherited) { exit 1 }
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.env"
            env = {**os.environ, "TEST_INIT_DIRECTORY": tmpdir, "TEST_INIT_FILE": str(target)}

            def powershell(script):
                subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "$ErrorActionPreference = 'Stop'; " + script],
                    env=env, check=True, capture_output=True, text=True, timeout=30,
                )

            powershell(acl_check)
            write_minimal_env(target, "DEEPSEEK_API_KEY=first-test-key\n")
            powershell(verify_acl)
            result = write_minimal_env(target, "DEEPSEEK_API_KEY=replacement-test-key\n", force=True)
            self.assertTrue(result["overwritten"])
            powershell(verify_acl)

    def test_interrupted_write_leaves_destination_untouched_and_allows_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.env"
            argv = ["--init", "--non-interactive", "--init-output", str(target)]
            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()), mock.patch(
                "src.services.init_config_service.os.fsync", side_effect=KeyboardInterrupt,
            ):
                self.assertEqual(main.main(argv), 130)
                self.assertEqual(list(target.parent.iterdir()), [])
            self.assertEqual(stdout.getvalue(), "")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main.main(argv), 0)
            original = target.read_bytes()

            with mock.patch("src.services.init_config_service.os.fsync", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    write_minimal_env(target, "STOCK_LIST=AAPL\n", force=True)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_first_write_cannot_replace_a_concurrent_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.env"

            def create_competing_file(_fd):
                target.write_text("STOCK_LIST=AAPL\n", encoding="utf-8")

            with mock.patch("src.services.init_config_service.os.fsync", side_effect=create_competing_file):
                with self.assertRaises(FileExistsError):
                    write_minimal_env(target, "STOCK_LIST=600519\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "STOCK_LIST=AAPL\n")
            self.assertEqual(list(target.parent.iterdir()), [target])

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
        answers = iter(["deepseek", "sk-real-demo-123", "600519\u2028hk00700", "AAPL", "",
                        "feishu", "https://open.feishu.cn/hook/abc"])
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
            self.assertEqual(res["stocks"], "600519,hk00700,AAPL")
            written = out_file.read_text(encoding="utf-8")
            self.assertIn("LLM_DEEPSEEK_API_KEY=sk-real-demo-123", written)
            self.assertIn("FEISHU_WEBHOOK_URL=https://open.feishu.cn/hook/abc", written)

    @unittest.skipUnless(os.name == "posix", "Requires a POSIX pseudo-terminal")
    def test_interactive_cli_hides_secrets_and_keeps_json_on_stdout(self) -> None:
        import pty
        import select
        import time

        def read_prompt(pipe, suffix):
            deadline = time.monotonic() + 20
            output = bytearray()
            while not output.endswith(suffix):
                ready, _, _ = select.select([pipe], [], [], max(0, deadline - time.monotonic()))
                self.assertTrue(ready, f"Prompt {suffix!r} timed out. Received {output!r}")
                chunk = os.read(pipe.fileno(), 4096)
                self.assertTrue(chunk, f"Prompt {suffix!r} missing. Received {output!r}")
                output.extend(chunk)
            return output

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / ".env.test"
            master, slave = pty.openpty()
            try:
                with subprocess.Popen(
                    [sys.executable, "main.py", "--init", "--json", "--init-output", str(out_file)],
                    cwd=Path(__file__).resolve().parents[1], stdin=slave,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                    env={**os.environ, "ENV_FILE": str(Path(tmpdir) / "active.env")},
                ) as process:
                    prompts = bytearray()
                    try:
                        for prompt, answer in (
                            (b"(default: gemini): ", b"\n"),
                            (b"fill later): ", b"gemini-test-secret\n"),
                            (b"(blank line to finish, default: 600519,hk00700,AAPL): ", b"600519\nAAPL\n\n"),
                            (b"(default: none): ", b"telegram\n"),
                            (b"TELEGRAM_BOT_TOKEN (required): ", b"321:telegram-test-secret\n"),
                            (b"TELEGRAM_CHAT_ID (required): ", b"-12345\n"),
                        ):
                            prompts.extend(read_prompt(process.stderr, prompt))
                            os.write(master, answer)
                        stdout, stderr = process.communicate(timeout=20)
                    finally:
                        if process.poll() is None:
                            process.kill()

                echoed = bytearray()
                while select.select([master], [], [], 0)[0]:
                    echoed.extend(os.read(master, 4096))
            finally:
                os.close(slave)
                os.close(master)

            self.assertEqual(process.returncode, 0, bytes(prompts) + stderr)
            self.assertEqual(json.loads(stdout)["stocks"], "600519,AAPL")
            self.assertIn(b"telegram", echoed)
            for secret in (b"gemini-test-secret", b"321:telegram-test-secret"):
                self.assertNotIn(secret, stdout + prompts + stderr + echoed)
            parsed = dotenv_values(out_file)
            self.assertEqual(parsed["GEMINI_API_KEY"], "gemini-test-secret")
            self.assertEqual(parsed["TELEGRAM_BOT_TOKEN"], "321:telegram-test-secret")

    def test_cli_stops_if_terminal_cannot_hide_credential(self) -> None:
        from getpass import GetPassWarning
        import warnings

        def insecure_getpass(*args, **kwargs):
            warnings.warn("Password input may be echoed", GetPassWarning)
            self.fail("getpass fallback would read an echoed credential")

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / ".env"
            stderr = io.StringIO()
            with mock.patch("sys.stdin.isatty", return_value=True), mock.patch("builtins.input", return_value=""), \
                    mock.patch("getpass.getpass", side_effect=insecure_getpass), redirect_stderr(stderr):
                self.assertEqual(main.main(["--init", "--init-output", str(target)]), 2)
            self.assertIn("Cannot hide credential input", stderr.getvalue())
            self.assertFalse(target.exists())

    def test_openai_compatible_and_telegram_require_complete_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / ".env"
            with self.assertRaises(ValueError):
                run_init_wizard(
                    default_provider="openai-compatible",
                    output_path=target,
                    non_interactive=True,
                )
            result = run_init_wizard(
                default_provider="openai-compatible",
                output_path=target,
                non_interactive=True,
                base_url="https://gateway.example/v1",
                model="demo-model",
            )
            self.assertTrue(result["ok"])

            answers = iter(["gemini", "sk-demo", "600519", "", "telegram", "token-only", ""])
            with self.assertRaises(ValueError):
                run_init_wizard(
                    output_path=target.with_name("telegram.env"),
                    input_fn=lambda _prompt: next(answers),
                )

            content = generate_minimal_env_content(
                provider="openai-compatible",
                api_key="sk-demo",
                base_url="https://gateway.example/v1",
                model="demo-model",
            )
            parsed = dotenv_values(stream=io.StringIO(content))
            self.assertEqual(parsed["LLM_COMPATIBLE_BASE_URL"], "https://gateway.example/v1")
            self.assertEqual(parsed["LLM_COMPATIBLE_MODELS"], "openai/demo-model")

    def test_compatible_interactive_keeps_cli_gateway_defaults(self) -> None:
        answers = iter(["", "test-gateway-key", "", "", "", ""])
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / ".env"
            run_init_wizard(
                default_provider="openai-compatible", output_path=target,
                base_url="https://gateway.example/v1", model="vendor/demo-model",
                input_fn=lambda _prompt: next(answers),
            )
            parsed = dotenv_values(target)
            self.assertEqual(parsed["LLM_COMPATIBLE_BASE_URL"], "https://gateway.example/v1")
            self.assertEqual(parsed["LLM_COMPATIBLE_MODELS"], "openai/vendor/demo-model")

    def test_invalid_compatible_endpoint_does_not_create_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / ".env"
            for endpoint in ("gateway.example/v1", "https://", "https://user:password@gateway.example/v1"):
                with self.subTest(endpoint=endpoint), self.assertRaisesRegex(ValueError, r"HTTP\(S\) base URL"):
                    run_init_wizard(
                        default_provider="openai-compatible", output_path=target, non_interactive=True,
                        base_url=endpoint, model="demo-model",
                    )
                self.assertFalse(target.exists())

    def test_cli_init_non_interactive_json_and_overwrite_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "alternate 'quoted $name'.env"
            buf = io.StringIO()
            argv = ["--init", "--non-interactive", "--init-provider", "modelflare",
                    "--stocks", "600519\nhk00700\u2028AAPL", "--init-output", str(out_file)]
            active_file = Path(tmpdir) / "active.env"
            with mock.patch.dict(os.environ, {"ENV_FILE": str(active_file)}), redirect_stdout(buf):
                rc = main.main([*argv, "--json"])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["provider"], "modelflare")
            self.assertEqual(payload["stocks"], "600519,hk00700,AAPL")
            self.assertIn("MODELFLARE_KEY=", out_file.read_text(encoding="utf-8"))
            command = "python main.py --serve-only"
            if os.name == "nt":
                quoted_path = str(out_file.resolve()).replace("'", "''")
                expected = f"$env:ENV_FILE = '{quoted_path}'; {command}"
            else:
                expected = f"ENV_FILE={shlex.quote(str(out_file.resolve()))} {command}"
            self.assertEqual(payload["next_steps"][-1], expected)
            self.assertNotIn(command, payload["next_steps"])

            plain = io.StringIO()
            with mock.patch.dict(os.environ, {"ENV_FILE": str(active_file)}), redirect_stdout(plain):
                self.assertEqual(main.main([*argv, "--init-force"]), 0)
            self.assertEqual(plain.getvalue().splitlines()[1:], payload["next_steps"])
            self.assertFalse(active_file.exists())

            rc_conflict = main.main([
                "--init",
                "--non-interactive",
                "--init-output",
                str(out_file),
            ])
            self.assertEqual(rc_conflict, 2)

    def test_powershell_launch_command_quotes_alternate_path(self) -> None:
        alternate = Path(r"C:\Work Folder\it's $literal‘’‚‛.env")
        command = _init_launch_command(alternate, windows=True)
        self.assertEqual(command, r"$env:ENV_FILE = 'C:\Work Folder\it''s $literal‘‘’’‚‚‛‛.env'; python main.py --serve-only")

    def test_default_output_follows_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            active_file = Path(tmpdir) / "active.env"
            with mock.patch.dict(os.environ, {"ENV_FILE": str(active_file)}, clear=False):
                result = run_init_wizard(non_interactive=True)
            self.assertEqual(Path(result["path"]).resolve(), active_file.resolve())
            self.assertEqual(dotenv_values(active_file).get("STOCK_LIST"), "600519,hk00700,AAPL")
            self.assertEqual(result["next_steps"][-1], "python main.py --serve-only")

    def test_first_analysis_uses_generated_provider_credentials_and_wire_model(self) -> None:
        # A fresh process keeps other test modules' LiteLLM stubs out of this test.
        repo = Path(__file__).resolve().parents[1]
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
        env.update(LITELLM_LOCAL_MODEL_COST_MAP="True", LITELLM_TELEMETRY="False")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, "-m", "tests.test_init_config_service", "--transport-contract", tmpdir],
                cwd=repo, env={**env, "TMPDIR": tmpdir}, capture_output=True, text=True, timeout=90,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def _run_transport_contract(temp_dir: Path) -> None:
    import httpx
    from openai._base_client import SyncAPIClient
    from src.analyzer import GeminiAnalyzer
    from src.config import Config

    # Older OpenAI SDKs call httpx directly. Newer SDKs can use a different
    # HTTP client and expose a shared send method on SyncAPIClient.
    if hasattr(SyncAPIClient, "_send_request"):
        transport, send_method = SyncAPIClient, "_send_request"
    else:
        transport, send_method = httpx.Client, "send"

    template_lines = Path(".env.minimal.example").read_text(encoding="utf-8").splitlines()
    deepseek_block = []
    for line in template_lines[template_lines.index("# LLM_CHANNELS=deepseek"):]:
        if not line.startswith("# LLM_"):
            break
        deepseek_block.append(line.removeprefix("# "))
    test_key = "test-provider-key"
    deepseek_template = "\n".join(deepseek_block).replace("LLM_DEEPSEEK_API_KEY=", f"LLM_DEEPSEEK_API_KEY={test_key}")
    answers = iter(["deepseek", test_key, "AAPL", "", "none"])
    wizard_file = temp_dir / "deepseek-wizard.env"
    run_init_wizard(output_path=wizard_file, input_fn=lambda _prompt: next(answers))

    cases = [
        (deepseek_template, "https://api.deepseek.com", "deepseek-flash", False),
        (wizard_file.read_text(encoding="utf-8"), "https://api.deepseek.com", "deepseek-flash", False),
    ]
    gateway = "https://example.invalid/v1"
    for raw_model in ("deepseek-ai/DeepSeek-V4-Flash", "anthropic/vendor-model", "openai/vendor-model"):
        generated = generate_minimal_env_content(
            provider="openai-compatible", api_key=test_key, base_url=gateway, model=raw_model,
        )
        cases.extend((generated, gateway, raw_model, direct) for direct in (False, True))

    analysis_text = json.dumps({
        "sentiment_score": 72, "trend_prediction": "震荡", "operation_advice": "持有", "analysis_summary": "fixture",
    })
    for index, (content, endpoint, expected_model, direct) in enumerate(cases):
        path = temp_dir / f"case-{index}.env"
        path.write_text(content, encoding="utf-8")
        requests = []

        def send_request(_client, request, **_kwargs):
            body = json.loads(request.read())
            requests.append((str(request.url), request.headers.get("authorization"), body["model"]))
            chunk = {
                "id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1,
                "model": expected_model, "choices": [{"index": 0, "finish_reason": "stop",
                    "delta": {"role": "assistant", "content": analysis_text}}],
            }
            return httpx.Response(200, request=request, headers={"Content-Type": "text/event-stream"},
                                  content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n")

        env = {
            "ENV_FILE": str(path),
            "AIHUBMIX_KEY": "test-stale-aihubmix-key",
            "OPENAI_BASE_URL": "https://legacy.example.invalid/v1",
            "GEMINI_REQUEST_DELAY": "0",
            "REPORT_INTEGRITY_ENABLED": "false",
        }
        router = mock.patch("src.analyzer.Router", side_effect=TypeError) if direct else nullcontext()
        with mock.patch.dict(os.environ, env), mock.patch.object(transport, send_method, send_request), \
                mock.patch("socket.socket.connect", side_effect=AssertionError("Unexpected network access")):
            config = Config._load_from_env()
            assert config.llm_models_source == "llm_channels"
            with router:
                analyzer = GeminiAnalyzer(config=config, skills=[])
            assert (analyzer._router is None) == direct
            result = analyzer.analyze({"code": "AAPL", "stock_name": "Apple"})
        assert result.success and result.sentiment_score == 72, result.error_message
        assert requests == [(endpoint + "/chat/completions", f"Bearer {test_key}", expected_model)], requests


if __name__ == "__main__" and "--transport-contract" in sys.argv:
    _run_transport_contract(Path(sys.argv[-1]))
