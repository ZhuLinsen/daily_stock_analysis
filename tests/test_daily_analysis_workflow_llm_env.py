# -*- coding: utf-8 -*-
"""Static checks for LLM provider channel mappings in 00-daily-analysis.yml."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT_DIR / "apps/dsa-web/src/components/settings/llmProviderTemplates.ts"
WORKFLOW_PATH = ROOT_DIR / ".github/workflows/00-daily-analysis.yml"
ENV_EXAMPLE_PATH = ROOT_DIR / ".env.example"

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
    "requesty",
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


def test_daily_analysis_maps_all_provider_template_channels() -> None:
    templates = _extract_provider_templates()
    env = _load_daily_analysis_env()

    for channel in templates:
        prefix = f"LLM_{channel.upper()}_"
        for suffix in (
            "PROTOCOL",
            "API_SURFACE",
            "BASE_URL",
            "API_KEY",
            "API_KEYS",
            "MODELS",
            "ENABLED",
            "EXTRA_HEADERS",
        ):
            assert f"{prefix}{suffix}" in env

    assert not any(key.startswith("LLM_ARK_") for key in env)


def test_daily_analysis_accepts_modelflare_one_key_from_secrets() -> None:
    assert _load_daily_analysis_env()["MODELFLARE_KEY"] == "${{ secrets.MODELFLARE_KEY }}"
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    analyze = next(step for step in workflow["jobs"]["analyze"]["steps"] if step.get("name") == "执行股票分析")
    assert '[ -n "$MODELFLARE_KEY" ]' in analyze["run"]


def test_daily_analysis_keeps_channel_secrets_in_secrets_context() -> None:
    templates = _extract_provider_templates()
    env = _load_daily_analysis_env()

    for channel in templates:
        upper = channel.upper()
        for suffix in ("API_KEY", "API_KEYS"):
            key = f"LLM_{upper}_{suffix}"
            assert env[key] == f"${{{{ secrets.{key} }}}}"

        for suffix in ("PROTOCOL", "API_SURFACE", "BASE_URL", "MODELS", "ENABLED", "EXTRA_HEADERS"):
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


def test_daily_analysis_maps_custom_channel_and_accurate_ai_status_log() -> None:
    env = _load_daily_analysis_env()
    for suffix in ("API_KEY", "API_KEYS"):
        key = f"LLM_CUSTOM_{suffix}"
        assert env[key] == f"${{{{ secrets.{key} }}}}"
    for suffix in ("PROTOCOL", "API_SURFACE", "BASE_URL", "MODELS", "ENABLED", "EXTRA_HEADERS"):
        key = f"LLM_CUSTOM_{suffix}"
        assert f"vars.{key}" in env[key]
        assert f"secrets.{key}" in env[key]

    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    analyze = next(step for step in workflow["jobs"]["analyze"]["steps"] if step.get("name") == "执行股票分析")
    run_script = analyze["run"]
    assert "AI 模型:" in run_script
    assert "✅ 已配置（传输模式: $TRANSPORT_LABEL）" in run_script
    assert "resolve_llm_transport_mode" in run_script
    assert "LLM_CHANNELS" in run_script
    assert "LLM_CUSTOM_API_KEY" in run_script
    assert "LiteLLM: ❌ 未配置" not in run_script


def test_daily_analysis_status_logic_handles_lone_keys_and_trimmed_transport_mode() -> None:
    import os
    from unittest.mock import patch
    from src.config import Config
    from src.llm.transport import resolve_llm_transport_mode

    with patch("src.config.setup_env"), patch.object(Config, "_parse_litellm_yaml", return_value=[]):
        # Lone LLM_CUSTOM_API_KEY without LLM_CHANNELS/models is NOT ready.
        with patch.dict(os.environ, {"LLM_CUSTOM_API_KEY": "sk-orphan"}, clear=True):
            cfg = Config._load_from_env()
            assert not (cfg.llm_model_list or cfg.litellm_model)

        # Trimmed whitespace in LLM_TRANSPORT_MODE=" native " resolves accurately to "native".
        with patch.dict(
            os.environ,
            {
                "LLM_CHANNELS": "custom",
                "LLM_CUSTOM_PROTOCOL": "openai",
                "LLM_CUSTOM_BASE_URL": "https://relay.example/v1",
                "LLM_CUSTOM_API_KEY": "sk-relay",
                "LLM_CUSTOM_MODELS": "gpt-4o-mini",
                "LLM_TRANSPORT_MODE": " native ",
            },
            clear=True,
        ):
            cfg = Config._load_from_env()
            assert bool(cfg.llm_model_list)
            assert resolve_llm_transport_mode(config=cfg) == "native"


def test_daily_analysis_conditionally_installs_optional_litellm_extra(tmp_path: Path) -> None:
    import os
    import re
    import subprocess
    import sys

    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    analyze = next(step for step in workflow["jobs"]["analyze"]["steps"] if step.get("name") == "执行股票分析")
    run_script = analyze["run"]
    assert "_find_routes_requiring_litellm" in run_script
    assert "pip install -r requirements-litellm.txt" in run_script
    # P1-2: Do NOT swallow probe stderr or silently mask failures with fallback echo.
    assert "2>/dev/null || echo" not in run_script
    assert "LLM_PROBE_OUTPUT=$(python -c \"" in run_script

    match = re.search(r'LLM_PROBE_OUTPUT=\$\(python -c "\n(.*?)\n\s*"\)', run_script, re.DOTALL)
    assert match is not None, "Could not locate embedded Python probe in 00-daily-analysis.yml"
    probe_lines = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    probe_code = "\n".join(probe_lines)

    repo_root = WORKFLOW_PATH.parents[2]
    empty_env_file = tmp_path / "empty.env"
    empty_env_file.write_text("", encoding="utf-8")

    def _run_real_probe(env_overrides: dict[str, str]) -> tuple[str, str, str]:
        env = {
            key: val
            for key, val in os.environ.items()
            if not key.startswith(
                (
                    "LLM_",
                    "LITELLM_",
                    "OPENAI_",
                    "GEMINI_",
                    "ANTHROPIC_",
                    "DEEPSEEK_",
                    "VISION_",
                    "AGENT_LITELLM_",
                    "GENERATION_",
                    "MODELFLARE_",
                    "AIHUBMIX_",
                    "ANSPIRE_",
                )
            )
        }
        env["ENV_FILE"] = str(empty_env_file)
        env["PYTHONPATH"] = str(repo_root)
        env.update(env_overrides)
        res = subprocess.run(
            [sys.executable, "-c", probe_code],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"Probe failed: rc={res.returncode} stderr={res.stderr}"
        raw_lines = res.stdout.splitlines()
        assert len(raw_lines) == 1, f"Expected exact single-line probe output for Bash read, got: {res.stdout!r}"
        parts = raw_lines[0].split()
        assert len(parts) == 3, f"Unexpected probe output: {res.stdout!r}"
        return parts[0], parts[1], parts[2]

    # Standard native OpenAI-compatible relay -> ready=1, mode=auto, needs_litellm=0.
    assert _run_real_probe({
        "LLM_CHANNELS": "custom",
        "LLM_CUSTOM_PROTOCOL": "openai",
        "LLM_CUSTOM_BASE_URL": "https://relay.example/v1",
        "LLM_CUSTOM_API_KEY": "sk-relay",
        "LLM_CUSTOM_MODELS": "gpt-4o-mini",
    }) == ("1", "auto", "0")

    # P1-5 & P1-6: Direct relay VISION_MODEL=Qwen/Qwen-VL + OPENAI_BASE_URL stays native
    # even when a shadowed legacy OPENAI_VISION_MODEL=bedrock/example is also set -> needs_litellm=0.
    assert _run_real_probe({
        "OPENAI_API_KEY": "sk-vision-relay-1234",
        "OPENAI_BASE_URL": "https://relay.example/v1",
        "OPENAI_MODEL": "Qwen/Qwen-VL",
        "VISION_MODEL": "Qwen/Qwen-VL",
        "OPENAI_VISION_MODEL": "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
    }) == ("1", "auto", "0")

    # Explicit rollback LLM_TRANSPORT_MODE=litellm -> needs_litellm=1.
    assert _run_real_probe({
        "LLM_TRANSPORT_MODE": "litellm",
        "OPENAI_API_KEY": "sk-test-key-1234",
    }) == ("1", "litellm", "1")

    # Auto mode with Cloud IAM or non-native provider -> needs_litellm=1.
    assert _run_real_probe({"LITELLM_MODEL": "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"}) == ("1", "auto", "1")
    assert _run_real_probe({"LITELLM_MODEL": "replicate/demo"}) == ("1", "auto", "1")

    # Probe failure must fail loud with non-zero exit & visible stderr (not swallowed to "0 auto 0").
    broken_env = dict(os.environ)
    broken_env["PYTHONPATH"] = str(tmp_path)
    broken_res = subprocess.run(
        [sys.executable, "-c", probe_code],
        cwd=tmp_path,
        env=broken_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert broken_res.returncode != 0
    assert broken_res.stderr.strip() != ""
