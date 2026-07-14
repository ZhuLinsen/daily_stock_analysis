# -*- coding: utf-8 -*-
"""Static checks for LLM provider channel mappings in 00-daily-analysis.yml."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT_DIR / "apps/dsa-web/src/components/settings/llmProviderTemplates.ts"
WORKFLOW_PATH = ROOT_DIR / ".github/workflows/00-daily-analysis.yml"
ENV_EXAMPLE_PATH = ROOT_DIR / ".env.example"
VERIFY_REPORTS_SCRIPT = ROOT_DIR / ".github/scripts/verify_daily_analysis_reports.sh"

EXPECTED_TEMPLATE_CHANNELS = {
    "aihubmix",
    "deepseek",
    "dashscope",
    "zhipu",
    "moonshot",
    "minimax",
    "volcengine",
    "siliconflow",
    "openrouter",
    "gemini",
    "anthropic",
    "openai",
    "ollama",
}


def _extract_provider_templates() -> dict[str, str]:
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    matches = re.findall(
        r"channelId:\s*'(?P<channel>[^']+)'.*?baseUrl:\s*'(?P<base_url>[^']*)'",
        content,
        flags=re.DOTALL,
    )
    assert matches, "No provider channelId entries were found in llmProviderTemplates.ts"

    templates = {channel: base_url for channel, base_url in matches if channel != "custom"}
    assert EXPECTED_TEMPLATE_CHANNELS.issubset(templates.keys())
    assert "ark" not in templates
    return templates


def _load_daily_analysis_env() -> dict[str, str]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["analyze"]["steps"]
    analyze_step = next((step for step in steps if step.get("name") == "执行股票分析"), None)
    available_step_names = [step.get("name", "<unnamed>") for step in steps]
    assert analyze_step is not None, (
        "Expected 00-daily-analysis.yml job analyze to include a step named "
        f"'执行股票分析'; available step names: {available_step_names}"
    )
    return analyze_step["env"]


def _load_daily_analysis_step(name: str) -> dict:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["analyze"]["steps"]
    step = next((candidate for candidate in steps if candidate.get("name") == name), None)
    available_step_names = [candidate.get("name", "<unnamed>") for candidate in steps]
    assert step is not None, (
        f"Expected 00-daily-analysis.yml job analyze to include a step named "
        f"{name!r}; available step names: {available_step_names}"
    )
    return step


def _write_outcome(
    base_dir: Path,
    *,
    status: str,
    reason: str,
    report_files: list[str],
) -> None:
    logs_dir = base_dir / "logs"
    logs_dir.mkdir()
    (logs_dir / "daily_analysis_outcome.json").write_text(
        json.dumps(
            {
                "status": status,
                "reason": reason,
                "report_files": report_files,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _run_report_verifier(base_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(VERIFY_REPORTS_SCRIPT),
            "logs/daily_analysis_outcome.json",
            "reports",
        ],
        cwd=base_dir,
        text=True,
        capture_output=True,
        check=False,
    )


def test_daily_analysis_summary_uses_report_verifier_script() -> None:
    step = _load_daily_analysis_step("显示运行结果")
    script = step["run"]

    assert step.get("if") == "always()"
    assert ".github/scripts/verify_daily_analysis_reports.sh" in script
    assert "logs/daily_analysis_outcome.json" in script
    assert "grep -R" not in script
    assert "ls -A reports" not in script


def test_daily_analysis_uploads_artifacts_before_report_verification() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["analyze"]["steps"]
    step_names = [step.get("name") for step in steps]
    upload_index = step_names.index("上传分析报告")
    summary_index = step_names.index("显示运行结果")
    upload_step = steps[upload_index]

    assert upload_index < summary_index
    assert upload_step.get("if") == "always()"
    assert "reports/" in upload_step["with"]["path"]
    assert "logs/" in upload_step["with"]["path"]


def test_daily_analysis_report_verifier_accepts_actual_report(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report_path = reports_dir / "report_20260714.md"
    report_path.write_text("# report\n", encoding="utf-8")
    _write_outcome(
        tmp_path,
        status="success",
        reason="reports_generated",
        report_files=["reports/report_20260714.md"],
    )

    result = _run_report_verifier(tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "reports/report_20260714.md" in result.stdout


def test_daily_analysis_report_verifier_rejects_empty_subdir_only(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    (reports_dir / "empty").mkdir(parents=True)
    _write_outcome(
        tmp_path,
        status="success",
        reason="reports_generated",
        report_files=[],
    )

    result = _run_report_verifier(tmp_path)

    assert result.returncode == 1
    assert "::error::未生成报告文件" in result.stdout


def test_daily_analysis_report_verifier_accepts_legitimate_skip(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    _write_outcome(
        tmp_path,
        status="skipped",
        reason="non_trading_day",
        report_files=[],
    )

    result = _run_report_verifier(tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    assert "non_trading_day" in result.stdout


def test_daily_analysis_report_verifier_rejects_failed_outcome(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()
    _write_outcome(
        tmp_path,
        status="failed",
        reason="analysis_failed",
        report_files=[],
    )

    result = _run_report_verifier(tmp_path)

    assert result.returncode == 1
    assert "status=failed" in result.stdout


def test_daily_analysis_report_verifier_rejects_missing_outcome(tmp_path: Path) -> None:
    (tmp_path / "reports").mkdir()

    result = _run_report_verifier(tmp_path)

    assert result.returncode == 1
    assert "未找到分析结果状态文件" in result.stdout


def test_daily_analysis_maps_all_provider_template_channels() -> None:
    templates = _extract_provider_templates()
    env = _load_daily_analysis_env()

    for channel in templates:
        prefix = f"LLM_{channel.upper()}_"
        for suffix in (
            "PROTOCOL",
            "BASE_URL",
            "API_KEY",
            "API_KEYS",
            "MODELS",
            "ENABLED",
            "EXTRA_HEADERS",
        ):
            assert f"{prefix}{suffix}" in env

    assert not any(key.startswith("LLM_ARK_") for key in env)


def test_daily_analysis_keeps_channel_secrets_in_secrets_context() -> None:
    templates = _extract_provider_templates()
    env = _load_daily_analysis_env()

    for channel in templates:
        upper = channel.upper()
        for suffix in ("API_KEY", "API_KEYS"):
            key = f"LLM_{upper}_{suffix}"
            assert env[key] == f"${{{{ secrets.{key} }}}}"

        for suffix in ("PROTOCOL", "BASE_URL", "MODELS", "ENABLED", "EXTRA_HEADERS"):
            key = f"LLM_{upper}_{suffix}"
            assert f"vars.{key}" in env[key]
            assert f"secrets.{key}" in env[key]


def test_daily_analysis_maps_usage_hmac_config_safely() -> None:
    env = _load_daily_analysis_env()

    assert env["LLM_USAGE_HMAC_SECRET"] == "${{ secrets.LLM_USAGE_HMAC_SECRET }}"
    assert "vars.LLM_USAGE_HMAC_SECRET" not in env["LLM_USAGE_HMAC_SECRET"]
    assert "vars.LLM_USAGE_HMAC_KEY_VERSION" in env["LLM_USAGE_HMAC_KEY_VERSION"]
    assert "secrets.LLM_USAGE_HMAC_KEY_VERSION" in env["LLM_USAGE_HMAC_KEY_VERSION"]


def test_daily_analysis_maps_prompt_cache_config() -> None:
    env = _load_daily_analysis_env()

    for key in (
        "LLM_PROMPT_CACHE_TELEMETRY_ENABLED",
        "LLM_PROMPT_CACHE_HINTS_ENABLED",
        "LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL",
    ):
        assert key in env
        assert f"vars.{key}" in env[key]
        assert f"secrets.{key}" in env[key]


def test_daily_analysis_maps_generation_backend_runtime_config() -> None:
    env = _load_daily_analysis_env()

    for key in (
        "GENERATION_BACKEND",
        "GENERATION_FALLBACK_BACKEND",
        "GENERATION_BACKEND_TIMEOUT_SECONDS",
        "GENERATION_BACKEND_MAX_OUTPUT_BYTES",
        "GENERATION_BACKEND_MAX_CONCURRENCY",
        "LOCAL_CLI_BACKEND_MAX_CONCURRENCY",
        "AGENT_GENERATION_BACKEND",
    ):
        assert key in env
        assert f"vars.{key}" in env[key]
        assert f"secrets.{key}" in env[key]


def test_daily_analysis_generation_fallback_defaults_to_litellm() -> None:
    env = _load_daily_analysis_env()
    expression = env["GENERATION_FALLBACK_BACKEND"]

    assert expression == (
        "${{ vars.GENERATION_FALLBACK_BACKEND || "
        "secrets.GENERATION_FALLBACK_BACKEND || 'litellm' }}"
    )


def test_env_example_includes_provider_template_channel_examples() -> None:
    templates = _extract_provider_templates()
    env_example = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    for channel, base_url in templates.items():
        upper = channel.upper()
        assert f"LLM_CHANNELS={channel}" in env_example
        assert f"LLM_{upper}_MODELS=" in env_example

        if channel != "ollama":
            assert f"LLM_{upper}_API_KEY=" in env_example
        if base_url:
            assert f"LLM_{upper}_BASE_URL=" in env_example
        if channel != "ollama":
            assert f"LLM_{upper}_PROTOCOL=" in env_example

    assert "LLM_CHANNELS=ark" not in env_example
    assert "LLM_ARK_" not in env_example
