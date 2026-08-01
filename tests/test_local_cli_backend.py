# -*- coding: utf-8 -*-
"""Tests for the restricted local CLI generation backend."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.analyzer import GeminiAnalyzer  # noqa: E402
from src.core.config_registry import _FIELD_DEFINITIONS  # noqa: E402
from src.llm import local_cli_backend as local_cli_backend_module  # noqa: E402
from src.llm.generation_backend import GenerationError, GenerationErrorCode  # noqa: E402
from src.llm.local_cli_backend import (  # noqa: E402
    CLAUDE_CODE_CLI_PRESET,
    CODEX_CLI_PRESET,
    LocalCliGenerationBackend,
    LocalCliExecutionResult,
    LocalCliExtractionError,
    LocalCliPreset,
    OPENCODE_CLI_PRESET,
    build_local_cli_env,
    effective_local_cli_concurrency,
    redact_diagnostic_text,
)


def _registered_sensitive_titles_needing_title_match() -> list[str]:
    titles = []
    for field_name, metadata in _FIELD_DEFINITIONS.items():
        if not isinstance(metadata, dict) or not metadata.get("is_sensitive"):
            continue
        title = metadata.get("title")
        if not isinstance(title, str) or not title:
            continue
        if title.upper() in {field_name.upper(), field_name.replace("_", " ").upper()}:
            continue
        titles.append(title)
    return sorted(set(titles))


def _config(**overrides):
    defaults = {
        "generation_backend_timeout_seconds": 5,
        "generation_backend_max_output_bytes": 1024 * 1024,
        "generation_backend_max_concurrency": 1,
        "local_cli_backend_max_concurrency": 1,
        "generation_backend": "codex_cli",
        "generation_fallback_backend": "",
        "report_language": "zh",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _script(tmp_path: Path, source: str) -> str:
    path = tmp_path / "mock_cli.py"
    path.write_text(source, encoding="utf-8")
    return str(path)


def _backend(tmp_path: Path, source: str, **config_overrides) -> LocalCliGenerationBackend:
    preset = LocalCliPreset(
        preset_id="codex_cli",
        executable=sys.executable,
        argv=(_script(tmp_path, source),),
        display_name="Mock CLI",
    )
    return LocalCliGenerationBackend(_config(**config_overrides), preset=preset)


def test_success_uses_stdin_temp_cwd_and_usage_unavailable(tmp_path: Path) -> None:
    backend = _backend(
        tmp_path,
        """
import json, os, sys
prompt = sys.stdin.read()
print(json.dumps({"prompt": prompt, "cwd": os.getcwd(), "sentiment_score": 70}, ensure_ascii=False))
""",
    )

    result = backend.generate("hello", {}, response_validator=lambda text: json.loads(text))
    payload = json.loads(result.text)

    assert payload["prompt"] == "hello"
    assert payload["cwd"] != os.getcwd()
    assert not Path(payload["cwd"]).exists()
    assert result.usage == {
        "usage_available": False,
        "usage_source": "unavailable",
        "backend": "codex_cli",
    }
    assert result.diagnostics["executable"]["basename"] == Path(sys.executable).name
    assert "path" not in result.diagnostics["executable"]


def test_codex_preset_reads_output_last_message_instead_of_stdout(tmp_path: Path) -> None:
    final_payload = json.dumps({"prompt": "hello", "sentiment_score": 88, "source": "last_message"})
    script = _script(
        tmp_path,
        f"""
import json, sys
args = sys.argv[1:]
output_path = args[args.index("--output-last-message") + 1]
prompt = sys.stdin.read()
with open(output_path, "w", encoding="utf-8") as handle:
    handle.write(json.dumps({{"prompt": prompt, "sentiment_score": 88, "source": "last_message"}}))
print("OpenAI Codex v0.142.0")
print("23,011")
print({final_payload!r})
""",
    )
    preset = LocalCliPreset(
        preset_id="codex_cli",
        executable=sys.executable,
        argv=(script, "-"),
        display_name="Mock Codex CLI",
        output_last_message_arg="--output-last-message",
    )
    backend = LocalCliGenerationBackend(_config(), preset=preset)

    result = backend.generate("hello", {}, response_validator=lambda text: json.loads(text))
    payload = json.loads(result.text)

    assert payload == {
        "prompt": "hello",
        "sentiment_score": 88,
        "source": "last_message",
    }
    assert result.diagnostics["output_source"] == "output_last_message"
    assert "OpenAI Codex" in result.diagnostics["stdout_preview"]
    assert "final-message omitted" in result.diagnostics["stdout_preview"]
    assert "last_message" not in result.diagnostics["stdout_preview"]


def test_codex_preset_pins_noninteractive_approval_policy_before_exec() -> None:
    assert CODEX_CLI_PRESET.argv[:3] == (
        "--ask-for-approval",
        "never",
        "exec",
    )
    assert CODEX_CLI_PRESET.argv[4:6] == ("--sandbox", "read-only")
    assert CODEX_CLI_PRESET.contract_args[:3] == CODEX_CLI_PRESET.argv[:3]


def test_claude_preset_runtime_argv_contains_contract_args(tmp_path: Path) -> None:
    argv_path = tmp_path / "argv.json"
    script = _script(
        tmp_path,
        f"""
import json, pathlib, sys
path = pathlib.Path({str(argv_path)!r})
path.write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
print(json.dumps({{"type": "result", "subtype": "success", "result": "{{\\"sentiment_score\\": 77}}"}}))
""",
    )
    preset = LocalCliPreset(
        preset_id="claude_code_cli",
        executable=sys.executable,
        argv=(script, *CLAUDE_CODE_CLI_PRESET.argv),
        display_name="Mock Claude Code CLI",
        extractor=CLAUDE_CODE_CLI_PRESET.extractor,
        contract_args=CLAUDE_CODE_CLI_PRESET.contract_args,
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend="claude_code_cli"),
        preset=preset,
    )

    result = backend.generate("prompt", {}, response_validator=lambda text: json.loads(text))
    runtime_argv = json.loads(argv_path.read_text(encoding="utf-8"))

    assert json.loads(result.text)["sentiment_score"] == 77
    for contract_arg in CLAUDE_CODE_CLI_PRESET.contract_args:
        assert contract_arg in runtime_argv


def test_missing_contract_arg_is_capability_unsupported(tmp_path: Path) -> None:
    preset = LocalCliPreset(
        preset_id="claude_code_cli",
        executable=sys.executable,
        argv=(_script(tmp_path, "print('unused')"), "--safe-mode"),
        display_name="Mock Claude Code CLI",
        contract_args=("--safe-mode", "--strict-mcp-config"),
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend="claude_code_cli"),
        preset=preset,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.CAPABILITY_UNSUPPORTED
    assert exc_info.value.details["reason"] == "missing_runtime_contract_arg"
    assert "--strict-mcp-config" in exc_info.value.details["missing_contract_args"]


def test_contract_args_must_keep_preset_order(tmp_path: Path) -> None:
    preset = LocalCliPreset(
        preset_id="claude_code_cli",
        executable=sys.executable,
        argv=(
            _script(tmp_path, "print('unused')"),
            "--strict-mcp-config",
            "--safe-mode",
        ),
        display_name="Mock Claude Code CLI",
        contract_args=("--safe-mode", "--strict-mcp-config"),
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend="claude_code_cli"),
        preset=preset,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.CAPABILITY_UNSUPPORTED
    assert exc_info.value.details["reason"] == "missing_runtime_contract_arg"
    assert "--strict-mcp-config" in exc_info.value.details["missing_contract_args"]


def test_claude_extractor_uses_structured_output_in_schema_mode() -> None:
    preset = LocalCliPreset(
        preset_id="claude_code_cli",
        executable="claude",
        argv=(),
        display_name="Mock Claude Code CLI",
        extractor=lambda result: local_cli_backend_module._extract_claude_code_json(
            result,
            schema_mode=True,
        ),
    )

    text = preset.extractor(
        LocalCliExecutionResult(
            stdout=json.dumps({
                "type": "result",
                "subtype": "success",
                "structured_output": {"sentiment_score": "70"},
            }),
            stderr="",
            returncode=0,
        )
    )

    assert text == '{"sentiment_score":"70"}'


def test_claude_extractor_rejects_tool_event() -> None:
    with pytest.raises(LocalCliExtractionError) as exc_info:
        local_cli_backend_module._extract_claude_code_json(
            LocalCliExecutionResult(
                stdout=json.dumps({"type": "tool_use", "result": "should not parse"}),
                stderr="",
                returncode=0,
            ),
            schema_mode=False,
        )

    assert exc_info.value.error_code is GenerationErrorCode.CAPABILITY_UNSUPPORTED
    assert exc_info.value.reason == "unexpected_cli_event"


def test_claude_extractor_requires_result_success_envelope() -> None:
    with pytest.raises(LocalCliExtractionError) as missing_type:
        local_cli_backend_module._extract_claude_code_json(
            LocalCliExecutionResult(
                stdout=json.dumps({"subtype": "success", "result": "should not parse"}),
                stderr="",
                returncode=0,
            ),
            schema_mode=False,
        )
    with pytest.raises(LocalCliExtractionError) as missing_subtype:
        local_cli_backend_module._extract_claude_code_json(
            LocalCliExecutionResult(
                stdout=json.dumps({"type": "result", "result": "should not parse"}),
                stderr="",
                returncode=0,
            ),
            schema_mode=False,
        )

    assert missing_type.value.error_code is GenerationErrorCode.CAPABILITY_UNSUPPORTED
    assert missing_type.value.reason == "unexpected_cli_event"
    assert missing_subtype.value.error_code is GenerationErrorCode.UNKNOWN_BACKEND_ERROR
    assert missing_subtype.value.reason == "cli_result_not_success"


def test_claude_schema_retry_exhaustion_maps_schema_validation_failed() -> None:
    with pytest.raises(LocalCliExtractionError) as exc_info:
        local_cli_backend_module._extract_claude_code_json(
            LocalCliExecutionResult(
                stdout=json.dumps({
                    "type": "result",
                    "subtype": "error_max_structured_output_retries",
                    "is_error": True,
                }),
                stderr="",
                returncode=0,
            ),
            schema_mode=True,
        )

    assert exc_info.value.error_code is GenerationErrorCode.SCHEMA_VALIDATION_FAILED


def test_opencode_preset_uses_prompt_file_and_safe_argv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-should-not-leak")
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", '{"plugin":["leak"]}')
    argv_path = tmp_path / "argv.json"
    probe_path = tmp_path / "probe.json"
    script = _script(
        tmp_path,
        f"""
import json, os, pathlib, stat, sys
argv = sys.argv[1:]
prompt_path = pathlib.Path(argv[argv.index("--file") + 1])
config_path = pathlib.Path.cwd() / "opencode.json"
probe = {{
    "argv": argv,
    "prompt": prompt_path.read_text(encoding="utf-8"),
    "prompt_mode": stat.S_IMODE(prompt_path.stat().st_mode),
    "cwd_mode": stat.S_IMODE(pathlib.Path.cwd().stat().st_mode),
    "config": config_path.read_text(encoding="utf-8"),
    "env": {{
        "DEEPSEEK_API_KEY": os.environ.get("DEEPSEEK_API_KEY"),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "OPENCODE_CONFIG_CONTENT": os.environ.get("OPENCODE_CONFIG_CONTENT"),
        "OPENCODE_CONFIG_DIR": os.environ.get("OPENCODE_CONFIG_DIR"),
    }},
}}
pathlib.Path({str(argv_path)!r}).write_text(json.dumps(argv), encoding="utf-8")
pathlib.Path({str(probe_path)!r}).write_text(json.dumps(probe), encoding="utf-8")
print(json.dumps({{"type": "step_start"}}))
print(json.dumps({{"type": "text", "part": {{"text": "{{\\"sentiment_score\\": 66}}"}}}}))
print(json.dumps({{"type": "step_finish", "reason": "stop"}}))
""",
    )
    preset = LocalCliPreset(
        preset_id="opencode_cli",
        executable=sys.executable,
        argv=(script, *OPENCODE_CLI_PRESET.argv),
        display_name="Mock OpenCode CLI",
        extractor=OPENCODE_CLI_PRESET.extractor,
        contract_args=OPENCODE_CLI_PRESET.contract_args,
        prompt_transport=OPENCODE_CLI_PRESET.prompt_transport,
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend="opencode_cli"),
        preset=preset,
    )

    result = backend.generate("prompt from dsa", {}, response_validator=lambda text: json.loads(text))
    payload = json.loads(result.text)
    argv = json.loads(argv_path.read_text(encoding="utf-8"))
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    opencode_config = json.loads(probe["config"])

    assert payload["sentiment_score"] == 66
    assert argv[:4] == ["--pure", "run", "--format", "json"]
    assert "--model" not in argv
    assert "--file" in argv
    assert argv.index("--file") > argv.index("json")
    assert "--attach" not in argv
    assert "--dangerously-skip-permissions" not in argv
    assert probe["prompt"] == "prompt from dsa"
    assert probe["prompt_mode"] == 0o600
    assert probe["cwd_mode"] == 0o700
    for tool_name in local_cli_backend_module._OPENCODE_DISABLED_TOOL_NAMES:
        assert opencode_config["tools"][tool_name] is False
    assert opencode_config["tools"]["websearch"] is False
    assert opencode_config["tools"]["question"] is False
    assert opencode_config["tools"]["skill"] is False
    assert opencode_config["tools"]["todowrite"] is False
    assert opencode_config["tools"]["lsp"] is False
    assert "sk-should-not-leak" not in probe["config"]
    assert "sk-openai-should-not-leak" not in probe["config"]
    assert probe["env"]["DEEPSEEK_API_KEY"] is None
    assert probe["env"]["OPENAI_API_KEY"] is None
    assert probe["env"]["OPENCODE_CONFIG_CONTENT"] is None
    assert probe["env"]["OPENCODE_CONFIG_DIR"] is None
    assert result.diagnostics["opencode_project_config_written"] is True
    assert "opencode_config_controlled" not in result.diagnostics
    assert result.backend == "opencode_cli"
    assert result.provider == "opencode_cli"
    assert result.model == "opencode_cli"
    assert result.usage["backend"] == "opencode_cli"


def test_opencode_static_instruction_does_not_force_stock_json_contract() -> None:
    instruction = " ".join(str(arg) for arg in OPENCODE_CLI_PRESET.argv)
    normalized_instruction = instruction.lower()

    assert "attached prompt file" in instruction
    assert "json object" not in normalized_instruction
    assert "parser contract" not in normalized_instruction
    for field_name in (
        "sentiment_score",
        "trend_prediction",
        "operation_advice",
        "analysis_summary",
        "dashboard",
    ):
        assert field_name not in instruction


def test_opencode_preset_accepts_free_text_without_json_validator(tmp_path: Path) -> None:
    review = "## 今日复盘\n\n市场震荡，保持观察。"
    script = _script(
        tmp_path,
        f"""
import json
print(json.dumps({{"type": "step_start"}}))
print(json.dumps({{"type": "text", "part": {{"text": {review!r}}}}}, ensure_ascii=False))
print(json.dumps({{"type": "step_finish", "reason": "stop"}}))
""",
    )
    preset = LocalCliPreset(
        preset_id="opencode_cli",
        executable=sys.executable,
        argv=(script, *OPENCODE_CLI_PRESET.argv),
        display_name="Mock OpenCode CLI",
        extractor=OPENCODE_CLI_PRESET.extractor,
        contract_args=OPENCODE_CLI_PRESET.contract_args,
        prompt_transport=OPENCODE_CLI_PRESET.prompt_transport,
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend="opencode_cli"),
        preset=preset,
    )

    result = backend.generate("请生成 Markdown 复盘", {}, response_validator=None)

    assert result.text == review


def test_opencode_model_override_inserts_model_arg(tmp_path: Path) -> None:
    argv_path = tmp_path / "argv.json"
    script = _script(
        tmp_path,
        f"""
import json, pathlib, sys
pathlib.Path({str(argv_path)!r}).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
print(json.dumps({{"type": "step_start"}}))
print(json.dumps({{"type": "text", "part": {{"text": "{{\\"sentiment_score\\": 67}}"}}}}))
print(json.dumps({{"type": "step_finish", "reason": "stop"}}))
""",
    )
    preset = LocalCliPreset(
        preset_id="opencode_cli",
        executable=sys.executable,
        argv=(script, *OPENCODE_CLI_PRESET.argv),
        display_name="Mock OpenCode CLI",
        extractor=OPENCODE_CLI_PRESET.extractor,
        contract_args=OPENCODE_CLI_PRESET.contract_args,
        prompt_transport=OPENCODE_CLI_PRESET.prompt_transport,
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend="opencode_cli", opencode_cli_model="provider/model"),
        preset=preset,
    )

    result = backend.generate("prompt", {}, response_validator=lambda text: json.loads(text))
    argv = json.loads(argv_path.read_text(encoding="utf-8"))

    assert json.loads(result.text)["sentiment_score"] == 67
    assert argv[:6] == ["--pure", "run", "--format", "json", "--model", "provider/model"]
    assert argv.index("--file") > argv.index("provider/model")


def test_opencode_nonzero_json_event_error_maps_unknown_backend_error(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        """
import json
print(json.dumps({"type": "error", "error": {"name": "UnknownError"}}))
raise SystemExit(1)
""",
    )
    preset = LocalCliPreset(
        preset_id="opencode_cli",
        executable=sys.executable,
        argv=(script, *OPENCODE_CLI_PRESET.argv),
        display_name="Mock OpenCode CLI",
        extractor=OPENCODE_CLI_PRESET.extractor,
        contract_args=OPENCODE_CLI_PRESET.contract_args,
        prompt_transport=OPENCODE_CLI_PRESET.prompt_transport,
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend="opencode_cli", opencode_cli_model="provider/model"),
        preset=preset,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.UNKNOWN_BACKEND_ERROR
    assert exc_info.value.details["reason"] == "cli_result_error"


def test_opencode_nonzero_pretty_json_error_maps_unknown_backend_error(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        """
import json
print(json.dumps({"type": "error", "error": {"name": "UnknownError"}}, indent=2))
raise SystemExit(1)
""",
    )
    preset = LocalCliPreset(
        preset_id="opencode_cli",
        executable=sys.executable,
        argv=(script, *OPENCODE_CLI_PRESET.argv),
        display_name="Mock OpenCode CLI",
        extractor=OPENCODE_CLI_PRESET.extractor,
        contract_args=OPENCODE_CLI_PRESET.contract_args,
        prompt_transport=OPENCODE_CLI_PRESET.prompt_transport,
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend="opencode_cli", opencode_cli_model="provider/model"),
        preset=preset,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.UNKNOWN_BACKEND_ERROR
    assert exc_info.value.details["reason"] == "cli_result_error"


@pytest.mark.parametrize(
    ("event", "stream_name"),
    [
        ({"type": "tool_use", "name": "read"}, "stdout"),
        ({"type": "websearch", "query": "AAPL"}, "stdout"),
        ({"type": "tool_result", "part": {"tool_name": "todowrite"}}, "stdout"),
        ({"type": "lsp", "name": "diagnostics"}, "stdout"),
        ({"type": "question", "text": "Continue?"}, "stdout"),
        ({"type": "permission", "name": "read"}, "stdout"),
        ({"type": "step_finish", "is_error": True}, "stdout"),
        ({"type": "step_finish", "error": {"name": "StepFailed"}}, "stdout"),
        ({"type": "error", "error": {"name": "StderrError"}}, "stderr"),
    ],
)
def test_opencode_nonzero_blocked_or_error_event_maps_unknown_backend_error(
    tmp_path: Path,
    event: dict,
    stream_name: str,
) -> None:
    target_stream = "sys.stderr" if stream_name == "stderr" else "sys.stdout"
    script = _script(
        tmp_path,
        f"""
import json, sys
print(json.dumps({event!r}), file={target_stream})
raise SystemExit(1)
""",
    )
    preset = LocalCliPreset(
        preset_id="opencode_cli",
        executable=sys.executable,
        argv=(script, *OPENCODE_CLI_PRESET.argv),
        display_name="Mock OpenCode CLI",
        extractor=OPENCODE_CLI_PRESET.extractor,
        contract_args=OPENCODE_CLI_PRESET.contract_args,
        prompt_transport=OPENCODE_CLI_PRESET.prompt_transport,
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend="opencode_cli", opencode_cli_model="provider/model"),
        preset=preset,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.UNKNOWN_BACKEND_ERROR
    assert exc_info.value.details["reason"] == "cli_result_error"


def test_opencode_runtime_rejects_unsafe_model_override(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        """
print("should not execute")
""",
    )
    preset = LocalCliPreset(
        preset_id="opencode_cli",
        executable=sys.executable,
        argv=(script, *OPENCODE_CLI_PRESET.argv),
        display_name="Mock OpenCode CLI",
        extractor=OPENCODE_CLI_PRESET.extractor,
        contract_args=OPENCODE_CLI_PRESET.contract_args,
        prompt_transport=OPENCODE_CLI_PRESET.prompt_transport,
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend="opencode_cli", opencode_cli_model="provider/$MODEL"),
        preset=preset,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.UNSAFE_CONFIG
    assert exc_info.value.details["reason"] == "unsafe_opencode_cli_model"


def test_opencode_extractor_rejects_tool_event() -> None:
    with pytest.raises(LocalCliExtractionError) as exc_info:
        local_cli_backend_module._extract_opencode_json_events(
            LocalCliExecutionResult(
                stdout="\n".join([
                    json.dumps({"type": "step_start"}),
                    json.dumps({"type": "tool_use", "name": "read"}),
                    json.dumps({"type": "step_finish", "reason": "stop"}),
                ]),
                stderr="",
                returncode=0,
            )
        )

    assert exc_info.value.error_code is GenerationErrorCode.CAPABILITY_UNSUPPORTED


@pytest.mark.parametrize(
    "event",
    [
        {"type": "websearch", "query": "AAPL"},
        {"type": "question", "text": "Continue?"},
        {"type": "skill", "name": "default"},
        {"type": "todowrite", "items": []},
        {"type": "lsp", "name": "diagnostics"},
        {"type": "tool_use", "name": "websearch"},
        {"type": "tool_result", "part": {"tool_name": "todowrite"}},
    ],
)
def test_opencode_extractor_rejects_default_tool_events(event: dict) -> None:
    with pytest.raises(LocalCliExtractionError) as exc_info:
        local_cli_backend_module._extract_opencode_json_events(
            LocalCliExecutionResult(
                stdout="\n".join([
                    json.dumps({"type": "step_start"}),
                    json.dumps(event),
                    json.dumps({"type": "step_finish", "reason": "stop"}),
                ]),
                stderr="",
                returncode=0,
            )
        )

    assert exc_info.value.error_code is GenerationErrorCode.CAPABILITY_UNSUPPORTED


def test_opencode_event_iterator_accepts_pretty_single_event_object() -> None:
    events = list(local_cli_backend_module._iter_opencode_events(
        json.dumps({"type": "step_start"}, indent=2)
    ))

    assert events == [{"type": "step_start"}]


def test_opencode_extractor_accepts_json_array_event_stream() -> None:
    result = local_cli_backend_module._extract_opencode_json_events(
        LocalCliExecutionResult(
            stdout=json.dumps([
                {"type": "step_start"},
                {"type": "text", "text": '{"sentiment_score":'},
                {"type": "text", "part": {"text": " 68}"}},
                {"type": "step_finish", "reason": "stop"},
            ], indent=2),
            stderr="",
            returncode=0,
        )
    )

    assert json.loads(result)["sentiment_score"] == 68


def test_opencode_extractor_accepts_concatenated_event_stream() -> None:
    stdout = "".join([
        json.dumps({"type": "step_start"}),
        json.dumps({"type": "text", "text": '{"sentiment_score":'}),
        json.dumps({"type": "text", "part": {"text": " 69}"}}),
        json.dumps({"type": "step_finish", "reason": "end_turn"}),
    ])

    result = local_cli_backend_module._extract_opencode_json_events(
        LocalCliExecutionResult(stdout=stdout, stderr="", returncode=0)
    )

    assert json.loads(result)["sentiment_score"] == 69


def test_opencode_extractor_rejects_trailing_non_json_garbage() -> None:
    stdout = json.dumps({"type": "step_start"}) + " trailing"

    with pytest.raises(LocalCliExtractionError) as exc_info:
        local_cli_backend_module._extract_opencode_json_events(
            LocalCliExecutionResult(stdout=stdout, stderr="", returncode=0)
        )

    assert exc_info.value.error_code is GenerationErrorCode.INVALID_JSON


def test_opencode_extractor_rejects_non_event_json_shape() -> None:
    with pytest.raises(LocalCliExtractionError) as exc_info:
        local_cli_backend_module._extract_opencode_json_events(
            LocalCliExecutionResult(stdout=json.dumps({"message": "not an event"}), stderr="", returncode=0)
        )

    assert exc_info.value.error_code is GenerationErrorCode.SCHEMA_VALIDATION_FAILED


def test_opencode_extractor_rejects_array_without_step_finish() -> None:
    with pytest.raises(LocalCliExtractionError) as exc_info:
        local_cli_backend_module._extract_opencode_json_events(
            LocalCliExecutionResult(
                stdout=json.dumps([
                    {"type": "step_start"},
                    {"type": "text", "text": "hello"},
                ]),
                stderr="",
                returncode=0,
            )
        )

    assert exc_info.value.error_code is GenerationErrorCode.SCHEMA_VALIDATION_FAILED
    assert exc_info.value.reason == "missing_step_finish"


def test_opencode_extractor_rejects_later_error_after_step_finish() -> None:
    with pytest.raises(LocalCliExtractionError) as exc_info:
        local_cli_backend_module._extract_opencode_json_events(
            LocalCliExecutionResult(
                stdout=json.dumps([
                    {"type": "step_start"},
                    {"type": "text", "text": "hello"},
                    {"type": "step_finish", "reason": "stop"},
                    {"type": "error", "error": {"name": "LaterError"}},
                ]),
                stderr="",
                returncode=0,
            )
        )

    assert exc_info.value.error_code is GenerationErrorCode.CAPABILITY_UNSUPPORTED


def test_opencode_extractor_requires_step_finish_and_text() -> None:
    with pytest.raises(LocalCliExtractionError) as missing_finish:
        local_cli_backend_module._extract_opencode_json_events(
            LocalCliExecutionResult(
                stdout=json.dumps({"type": "text", "text": "hello"}),
                stderr="",
                returncode=0,
            )
        )
    with pytest.raises(LocalCliExtractionError) as empty_text:
        local_cli_backend_module._extract_opencode_json_events(
            LocalCliExecutionResult(
                stdout="\n".join([
                    json.dumps({"type": "step_start"}),
                    json.dumps({"type": "step_finish", "reason": "stop"}),
                ]),
                stderr="",
                returncode=0,
            )
        )

    assert missing_finish.value.error_code is GenerationErrorCode.SCHEMA_VALIDATION_FAILED
    assert empty_text.value.error_code is GenerationErrorCode.EMPTY_OUTPUT


def test_output_last_message_stdout_duplicate_is_not_double_counted(tmp_path: Path) -> None:
    final_payload = json.dumps(
        {
            "sentiment_score": 70,
            "source": "last_message",
            "details": "x" * 40,
        }
    )
    script = _script(
        tmp_path,
        f"""
import sys
args = sys.argv[1:]
output_path = args[args.index("--output-last-message") + 1]
with open(output_path, "w", encoding="utf-8") as handle:
    handle.write({final_payload!r})
print({final_payload!r})
""",
    )
    preset = LocalCliPreset(
        "codex_cli",
        sys.executable,
        (script,),
        "Mock CLI",
        output_last_message_arg="--output-last-message",
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend_max_output_bytes=len(final_payload.encode("utf-8")) + 2),
        preset=preset,
    )

    result = backend.generate("prompt", {}, response_validator=lambda text: json.loads(text))

    assert json.loads(result.text)["sentiment_score"] == 70
    assert result.diagnostics["stdout_final_message_omitted"] is True
    assert "last_message" not in result.diagnostics["stdout_preview"]


def test_output_last_message_nonzero_exit_omits_duplicate_final_stdout_preview(
    tmp_path: Path,
) -> None:
    final_payload = json.dumps(
        {
            "sentiment_score": 70,
            "source": "secret_final_payload",
        }
    )
    script = _script(
        tmp_path,
        f"""
import sys
args = sys.argv[1:]
output_path = args[args.index("--output-last-message") + 1]
with open(output_path, "w", encoding="utf-8") as handle:
    handle.write({final_payload!r})
print("diagnostic: before final")
print({final_payload!r})
sys.exit(2)
""",
    )
    preset = LocalCliPreset(
        "codex_cli",
        sys.executable,
        (script,),
        "Mock CLI",
        output_last_message_arg="--output-last-message",
    )
    backend = LocalCliGenerationBackend(_config(), preset=preset)

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.NON_ZERO_EXIT
    assert "diagnostic: before final" in exc_info.value.details["stdout_preview"]
    assert "final-message omitted" in exc_info.value.details["stdout_preview"]
    assert "secret_final_payload" not in exc_info.value.details["stdout_preview"]


def test_stream_request_degrades_to_non_stream(tmp_path: Path) -> None:
    progress = []
    backend = _backend(tmp_path, "print('{\"sentiment_score\": 60}')")

    result = backend.generate(
        "prompt",
        {},
        stream=True,
        stream_progress_callback=progress.append,
    )

    assert json.loads(result.text)["sentiment_score"] == 60
    assert result.diagnostics["stream_degraded"] is True
    assert progress


def test_stderr_does_not_affect_successful_stdout_or_json_parsing(tmp_path: Path) -> None:
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._config_override = _config()
    backend = _backend(
        tmp_path,
        """
import sys
print('{"sentiment_score": 70, "trend_prediction": "看多"}')
print('{"bad": "stderr"}', file=sys.stderr)
""",
    )

    result = backend.generate(
        "prompt",
        {},
        response_validator=analyzer._validate_json_response,
    )

    assert json.loads(result.text)["sentiment_score"] == 70
    assert "stderr" in result.diagnostics["stderr_preview"]


def test_multiple_json_objects_fail_as_invalid_json_ambiguous(tmp_path: Path) -> None:
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._config_override = _config()
    backend = _backend(tmp_path, "print('{\"sentiment_score\": 70} {\"sentiment_score\": 80}')")

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {}, response_validator=analyzer._validate_json_response)

    assert exc_info.value.error_code is GenerationErrorCode.INVALID_JSON
    assert exc_info.value.details["reason"] == "ambiguous_json"


def test_command_not_executable(monkeypatch, tmp_path: Path) -> None:
    not_exec = tmp_path / "not-executable"
    not_exec.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr("src.llm.local_cli_backend.shutil.which", lambda _cmd: str(not_exec))
    preset = LocalCliPreset("codex_cli", "mock", (), "Mock CLI")
    backend = LocalCliGenerationBackend(_config(), preset=preset)

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.COMMAND_NOT_EXECUTABLE


def test_command_not_found(monkeypatch) -> None:
    monkeypatch.setattr("src.llm.local_cli_backend.shutil.which", lambda _cmd: None)
    backend = LocalCliGenerationBackend(_config())

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.COMMAND_NOT_FOUND


def test_shell_metachar_returns_unsafe_config() -> None:
    preset = LocalCliPreset("codex_cli", "mock", ("echo", "ok;rm"), "Mock CLI")
    backend = LocalCliGenerationBackend(_config(), preset=preset)

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.UNSAFE_CONFIG
    assert exc_info.value.details["reason"] == "shell_metachar"


def test_output_last_message_arg_shell_metachar_returns_unsafe_config(tmp_path: Path) -> None:
    preset = LocalCliPreset(
        "codex_cli",
        sys.executable,
        (_script(tmp_path, "print('ok')"),),
        "Mock CLI",
        output_last_message_arg="--output-last-message;rm",
    )
    backend = LocalCliGenerationBackend(_config(), preset=preset)

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.UNSAFE_CONFIG
    assert exc_info.value.details["reason"] == "shell_metachar"


def test_output_too_large(tmp_path: Path) -> None:
    backend = _backend(
        tmp_path,
        "print('x' * 100)",
        generation_backend_max_output_bytes=20,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.OUTPUT_TOO_LARGE


def test_output_stat_error_is_structured_and_kills_process_group(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pid_file = tmp_path / "child-stat-error.pid"
    backend = _backend(
        tmp_path,
        f"""
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
open({str(pid_file)!r}, "w", encoding="utf-8").write(str(child.pid))
sys.stdout.write("started")
sys.stdout.flush()
time.sleep(30)
""",
    )

    def _raise_stat_error(*_paths):
        deadline = time.time() + 3
        while not pid_file.exists() and time.time() < deadline:
            time.sleep(0.01)
        raise OSError("mock stat failure sk-secretsecretsecret")

    monkeypatch.setattr(
        "src.llm.local_cli_backend._combined_path_size_required",
        _raise_stat_error,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.UNKNOWN_BACKEND_ERROR
    assert exc_info.value.details["reason"] == "output_stat_failed"
    assert "sk-secret" not in exc_info.value.details["error"]
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            os.kill(child_pid, 0)
        except OSError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("child process was not terminated after output stat failure")


def test_output_read_error_is_structured_unknown_not_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    backend = _backend(tmp_path, "print('{\"sentiment_score\": 70}')")

    def _raise_read_error(_path):
        raise OSError("mock read failure")

    monkeypatch.setattr(
        "src.llm.local_cli_backend._read_text_file_required",
        _raise_read_error,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.UNKNOWN_BACKEND_ERROR
    assert exc_info.value.details["reason"] == "output_read_failed"


def test_stdout_output_limit_is_not_double_counted(tmp_path: Path) -> None:
    backend = _backend(
        tmp_path,
        "print('{\"sentiment_score\": 70}')",
        generation_backend_max_output_bytes=30,
    )

    result = backend.generate("prompt", {}, response_validator=lambda text: json.loads(text))

    assert json.loads(result.text)["sentiment_score"] == 70
    assert result.diagnostics["output_source"] == "stdout"


def test_output_too_large_kills_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "child-output-limit.pid"
    backend = _backend(
        tmp_path,
        f"""
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
open({str(pid_file)!r}, "w", encoding="utf-8").write(str(child.pid))
sys.stdout.write("x" * 100000)
sys.stdout.flush()
time.sleep(30)
""",
        generation_backend_max_output_bytes=20,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.OUTPUT_TOO_LARGE
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            os.kill(child_pid, 0)
        except OSError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("child process was not terminated with the process group")


def test_output_last_message_too_large(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        """
import sys
args = sys.argv[1:]
output_path = args[args.index("--output-last-message") + 1]
with open(output_path, "w", encoding="utf-8") as handle:
    handle.write("x" * 100)
""",
    )
    preset = LocalCliPreset(
        "codex_cli",
        sys.executable,
        (script,),
        "Mock CLI",
        output_last_message_arg="--output-last-message",
    )
    backend = LocalCliGenerationBackend(_config(generation_backend_max_output_bytes=20), preset=preset)

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.OUTPUT_TOO_LARGE


def test_output_last_message_total_limit_includes_stdio(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        """
import sys
args = sys.argv[1:]
output_path = args[args.index("--output-last-message") + 1]
print("stdout bytes")
with open(output_path, "w", encoding="utf-8") as handle:
    handle.write("final bytes")
""",
    )
    preset = LocalCliPreset(
        "codex_cli",
        sys.executable,
        (script,),
        "Mock CLI",
        output_last_message_arg="--output-last-message",
    )
    backend = LocalCliGenerationBackend(_config(generation_backend_max_output_bytes=20), preset=preset)

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.OUTPUT_TOO_LARGE


def test_empty_stdout_returns_empty_output(tmp_path: Path) -> None:
    backend = _backend(tmp_path, "")

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.EMPTY_OUTPUT
    assert exc_info.value.details["reason"] == "empty_stdout"


def test_missing_output_last_message_returns_empty_output(tmp_path: Path) -> None:
    preset = LocalCliPreset(
        "codex_cli",
        sys.executable,
        (_script(tmp_path, "print('metadata only')"),),
        "Mock CLI",
        output_last_message_arg="--output-last-message",
    )
    backend = LocalCliGenerationBackend(_config(), preset=preset)

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.EMPTY_OUTPUT
    assert exc_info.value.details["reason"] == "missing_last_message_output"
    assert exc_info.value.details["output_source"] == "output_last_message"


def test_non_zero_exit_maps_login_required(tmp_path: Path) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print('not authenticated, please login', file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.LOGIN_REQUIRED
    assert exc_info.value.details["returncode"] == 2


def test_non_zero_exit_maps_cli_contract_unsupported(tmp_path: Path) -> None:
    preset = LocalCliPreset(
        "codex_cli",
        sys.executable,
        (
            _script(
                tmp_path,
                """
import sys
print("error: unexpected argument '--output-last-message' found", file=sys.stderr)
raise SystemExit(2)
""",
            ),
        ),
        "Mock CLI",
        output_last_message_arg="--output-last-message",
    )
    backend = LocalCliGenerationBackend(_config(), preset=preset)

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.CAPABILITY_UNSUPPORTED
    assert exc_info.value.fallbackable is True
    assert exc_info.value.details["reason"] == "cli_contract_unsupported"
    assert exc_info.value.details["returncode"] == 2
    assert "--output-last-message" in exc_info.value.details["stderr_preview"]


def test_claude_unknown_contract_arg_is_capability_unsupported_without_retry(tmp_path: Path) -> None:
    argv_path = tmp_path / "argv.json"
    count_path = tmp_path / "count.txt"
    script = _script(
        tmp_path,
        f"""
import json, pathlib, sys
argv_path = pathlib.Path({str(argv_path)!r})
count_path = pathlib.Path({str(count_path)!r})
count = int(count_path.read_text(encoding="utf-8")) if count_path.exists() else 0
count_path.write_text(str(count + 1), encoding="utf-8")
argv = sys.argv[1:]
argv_path.write_text(json.dumps(argv), encoding="utf-8")
if "--strict-mcp-config" in argv:
    print("error: unknown option '--strict-mcp-config'", file=sys.stderr)
    raise SystemExit(2)
print(json.dumps({{"type": "result", "subtype": "success", "result": "{{\\"sentiment_score\\": 90}}"}}))
""",
    )
    preset = LocalCliPreset(
        preset_id="claude_code_cli",
        executable=sys.executable,
        argv=(script, *CLAUDE_CODE_CLI_PRESET.argv),
        display_name="Mock Claude Code CLI",
        extractor=CLAUDE_CODE_CLI_PRESET.extractor,
        contract_args=CLAUDE_CODE_CLI_PRESET.contract_args,
    )
    backend = LocalCliGenerationBackend(
        _config(generation_backend="claude_code_cli"),
        preset=preset,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    runtime_argv = json.loads(argv_path.read_text(encoding="utf-8"))
    assert exc_info.value.error_code is GenerationErrorCode.CAPABILITY_UNSUPPORTED
    assert exc_info.value.details["reason"] == "cli_contract_unsupported"
    assert "--strict-mcp-config" in runtime_argv
    assert count_path.read_text(encoding="utf-8") == "1"


def test_non_zero_exit_mentions_preset_arg_without_unknown_marker_stays_generic(tmp_path: Path) -> None:
    preset = LocalCliPreset(
        "codex_cli",
        sys.executable,
        (
            _script(
                tmp_path,
                """
import sys
print("failed while writing --output-last-message file", file=sys.stderr)
raise SystemExit(2)
""",
            ),
        ),
        "Mock CLI",
        output_last_message_arg="--output-last-message",
    )
    backend = LocalCliGenerationBackend(_config(), preset=preset)

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.NON_ZERO_EXIT
    assert exc_info.value.details["reason"] == "non_zero_exit"


def test_non_zero_exit_with_missing_last_message_still_maps_login_required(tmp_path: Path) -> None:
    preset = LocalCliPreset(
        "codex_cli",
        sys.executable,
        (
            _script(
                tmp_path,
                """
import sys
print("not authenticated, please login", file=sys.stderr)
raise SystemExit(2)
""",
            ),
        ),
        "Mock CLI",
        output_last_message_arg="--output-last-message",
    )
    backend = LocalCliGenerationBackend(_config(), preset=preset)

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.LOGIN_REQUIRED
    assert exc_info.value.details["reason"] == "login_required"


def test_process_start_error_diagnostics_are_redacted(monkeypatch) -> None:
    home_path = Path.home()
    executable_path = str(home_path / "secret" / "bin" / "codex")
    monkeypatch.setattr("src.llm.local_cli_backend.shutil.which", lambda _cmd: executable_path)
    monkeypatch.setattr("src.llm.local_cli_backend.os.access", lambda _path, _mode: True)

    def _raise_os_error(*_args, **_kwargs):
        raise OSError(f"Exec format error: {executable_path} sk-secretsecretsecret")

    monkeypatch.setattr("src.llm.local_cli_backend.subprocess.Popen", _raise_os_error)
    backend = LocalCliGenerationBackend(_config())

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.UNKNOWN_BACKEND_ERROR
    error = exc_info.value.details["error"]
    assert str(home_path) not in error
    assert "sk-secret" not in error


def test_prompt_is_passed_as_stdin_file_not_pipe(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def _raise_os_error(*_args, **kwargs):
        stdin = kwargs.get("stdin")
        captured["stdin"] = stdin
        captured["stdin_closed_at_popen"] = getattr(stdin, "closed", True)
        raise OSError("mock start failure")

    monkeypatch.setattr("src.llm.local_cli_backend.subprocess.Popen", _raise_os_error)
    backend = _backend(tmp_path, "print('unused')")

    with pytest.raises(GenerationError):
        backend.generate("x" * 200000, {})

    stdin = captured["stdin"]
    assert stdin is not subprocess.PIPE
    assert hasattr(stdin, "fileno")
    assert not captured["stdin_closed_at_popen"]


def test_timeout_kills_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    backend = _backend(
        tmp_path,
        f"""
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
open({str(pid_file)!r}, "w", encoding="utf-8").write(str(child.pid))
time.sleep(30)
""",
        generation_backend_timeout_seconds=1,
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.TIMEOUT
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            os.kill(child_pid, 0)
        except OSError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("child process was not terminated with the process group")


def test_env_allowlist_and_denylist(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/bin")
    monkeypatch.setenv("HOME", "/tmp/home")
    monkeypatch.setenv("CODEX_HOME", "/tmp/codex-home")
    monkeypatch.setenv("LC_MESSAGES", "C")
    monkeypatch.setenv("UNRELATED_VALUE", "leak")
    monkeypatch.setenv("AIHUBMIX_KEY", "aihubmix-secret")
    monkeypatch.setenv("CODEX_CLI_TOKEN", "codex-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/claude")
    monkeypatch.setenv("LONGBRIDGE_APP_KEY", "longbridge-secret")
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", "{}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "pushover-secret")
    monkeypatch.setenv("WEBHOOK_TOKEN", "token")
    monkeypatch.setenv("WECOM_ENCODING_AES_KEY", "wecom-secret")
    monkeypatch.setenv("AUTHORIZATION", "Bearer token")

    child_env = build_local_cli_env()

    assert child_env["PATH"] == "/bin"
    assert child_env["HOME"] == "/tmp/home"
    assert child_env["CODEX_HOME"] == "/tmp/codex-home"
    assert child_env["LC_MESSAGES"] == "C"
    assert "UNRELATED_VALUE" not in child_env
    assert "AIHUBMIX_KEY" not in child_env
    assert "CODEX_CLI_TOKEN" not in child_env
    assert "ANTHROPIC_API_KEY" not in child_env
    assert "ANTHROPIC_MODEL" not in child_env
    assert "CLAUDE_CONFIG_DIR" not in child_env
    assert "LONGBRIDGE_APP_KEY" not in child_env
    assert "OPENCODE_CONFIG_CONTENT" not in child_env
    assert "OPENAI_API_KEY" not in child_env
    assert "PUSHOVER_USER_KEY" not in child_env
    assert "WEBHOOK_TOKEN" not in child_env
    assert "WECOM_ENCODING_AES_KEY" not in child_env
    assert "AUTHORIZATION" not in child_env


def test_env_allowlist_preserves_windows_runtime_context() -> None:
    source = {
        "Path": r"C:\Users\tester\AppData\Local\Microsoft\WindowsApps",
        "SystemRoot": r"C:\Windows",
        "WINDIR": r"C:\Windows",
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "ComSpec": r"C:\Windows\System32\cmd.exe",
        "USERPROFILE": r"C:\Users\tester",
        "APPDATA": r"C:\Users\tester\AppData\Roaming",
        "LOCALAPPDATA": r"C:\Users\tester\AppData\Local",
        "HOMEDRIVE": "C:",
        "HOMEPATH": r"\Users\tester",
        "OPENAI_API_KEY": "sk-secret",
        "UNRELATED_VALUE": "leak",
    }

    child_env = build_local_cli_env(source)

    for key in (
        "Path",
        "SystemRoot",
        "WINDIR",
        "PATHEXT",
        "ComSpec",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
    ):
        assert child_env[key] == source[key]
    assert "APPDATA" not in child_env
    assert "LOCALAPPDATA" not in child_env
    assert "OPENAI_API_KEY" not in child_env
    assert "UNRELATED_VALUE" not in child_env


def test_generate_passes_allowlisted_windows_context_to_child_env(monkeypatch, tmp_path: Path) -> None:
    windows_context = {
        "SystemRoot": r"C:\Windows",
        "WINDIR": r"C:\Windows",
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "ComSpec": r"C:\Windows\System32\cmd.exe",
        "USERPROFILE": r"C:\Users\tester",
        "HOMEDRIVE": "C:",
        "HOMEPATH": r"\Users\tester",
    }
    for key, value in windows_context.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APPDATA", r"C:\Users\tester\AppData\Roaming")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\tester\AppData\Local")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("UNRELATED_VALUE", "leak")

    backend = _backend(
        tmp_path,
        """
import json, os
keys = [
    "SystemRoot",
    "WINDIR",
    "PATHEXT",
    "ComSpec",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "OPENAI_API_KEY",
    "UNRELATED_VALUE",
]
print(json.dumps({key: os.environ.get(key) for key in keys}, ensure_ascii=False))
""",
    )

    result = backend.generate("prompt", {})
    payload = json.loads(result.text)

    for key, value in windows_context.items():
        assert payload[key] == value
    assert payload["APPDATA"] is None
    assert payload["LOCALAPPDATA"] is None
    assert payload["OPENAI_API_KEY"] is None
    assert payload["UNRELATED_VALUE"] is None


def test_popen_session_kwargs_are_platform_specific(monkeypatch) -> None:
    monkeypatch.setattr(local_cli_backend_module.os, "name", "nt")
    monkeypatch.setattr(
        local_cli_backend_module.subprocess,
        "CREATE_NEW_PROCESS_GROUP",
        0x00000200,
        raising=False,
    )

    assert local_cli_backend_module._popen_session_kwargs() == {
        "creationflags": 0x00000200,
    }

    monkeypatch.setattr(local_cli_backend_module.os, "name", "posix")

    assert local_cli_backend_module._popen_session_kwargs() == {
        "start_new_session": True,
    }


def test_windows_terminate_process_group_prefers_ctrl_break(monkeypatch) -> None:
    class FakeProcess:
        pid = 1234

        def __init__(self) -> None:
            self.signals = []
            self.terminated = False
            self.killed = False

        def poll(self):
            return None

        def send_signal(self, sig):
            self.signals.append(sig)

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    monkeypatch.setattr(local_cli_backend_module.os, "name", "nt")
    monkeypatch.setattr(
        local_cli_backend_module.signal,
        "CTRL_BREAK_EVENT",
        1,
        raising=False,
    )
    process = FakeProcess()

    LocalCliGenerationBackend._terminate_process_group(process)

    assert process.signals == [1]
    assert process.terminated is False
    assert process.killed is False


def test_windows_terminate_process_group_falls_back_to_kill(monkeypatch) -> None:
    class FakeProcess:
        pid = 1234

        def __init__(self) -> None:
            self.signals = []
            self.terminated = False
            self.killed = False
            self._wait_calls = 0

        def poll(self):
            return None

        def send_signal(self, sig):
            self.signals.append(sig)
            raise OSError("no console")

        def wait(self, timeout=None):
            self._wait_calls += 1
            if self._wait_calls == 1:
                raise subprocess.TimeoutExpired(cmd="mock", timeout=timeout)
            return 0

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    monkeypatch.setattr(local_cli_backend_module.os, "name", "nt")
    monkeypatch.setattr(
        local_cli_backend_module.signal,
        "CTRL_BREAK_EVENT",
        1,
        raising=False,
    )
    process = FakeProcess()

    LocalCliGenerationBackend._terminate_process_group(process)

    assert process.signals == [1]
    assert process.terminated is True
    assert process.killed is True


def test_diagnostics_redaction_and_truncation() -> None:
    text = (
        "Authorization: Bearer sk-abc123456789012345678901234567890 "
        "https://user:pass@example.com/path "
        + "safe text " * 20
    )

    redacted = redact_diagnostic_text(text, home="/Users/example", limit=60)

    assert "sk-abc" not in redacted
    assert "user:pass" not in redacted
    assert "<truncated>" in redacted


def test_diagnostics_redacts_webhook_urls_and_preserves_adjacent_normal_urls() -> None:
    text = (
        "slack=https://hooks.slack.com/services/T000/B000/super-secret "
        "dingtalk=https://oapi.dingtalk.com/robot/send?access_token=abc123&foo=bar "
        "docs=https://example.com/public/docs?foo=bar"
    )

    redacted = redact_diagnostic_text(text, limit=1000)

    assert "hooks.slack.com" not in redacted
    assert "oapi.dingtalk.com" not in redacted
    assert "super-secret" not in redacted
    assert "access_token" not in redacted
    assert redacted.count("<redacted-url>") == 2
    assert "https://example.com/public/docs?foo=bar" in redacted


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("FEISHU_APP_SECRET=xxy12345abcdef", "xxy12345abcdef"),
        ("AIHUBMIX_KEY=short", "short"),
        ("CUSTOM_API_KEY=abc123xyz789short", "abc123xyz789short"),
        ("LONGBRIDGE_APP_KEY=short", "short"),
        ("NTFY_URL=https://ntfy.sh/private-topic", "https://ntfy.sh/private-topic"),
        ("API_KEYS=short", "short"),
        ("OPENAI_API_KEYS=short", "short"),
        ("MYOPENAIKEY=short", "short"),
        ("OPENAI_V2_API_KEY=short", "short"),
        (r"OPENAI_FOO=\ tiny-secret session_id=ok", "tiny-secret"),
        ("OPENAI_API_KEY=\\\ntiny-secret session_id=ok", "tiny-secret"),
        ("OPENAI_FOO=$(printf %s tiny-secret) session_id=ok", "tiny-secret"),
        ("export OPENAI_FOO=$(printf %s tiny-secret) session_id=ok", "tiny-secret"),
        ("PUSHOVER_USER_KEY=short", "short"),
        ("R2_SECRET_ACCESS_KEY=short", "short"),
        ("My_Api_Key=myvalue", "myvalue"),
        ("API Key: tiny-secret session_id=ok", "tiny-secret"),
        ("Client Secret: tiny-secret session_id=ok", "tiny-secret"),
        ("Secret Access Key: tiny-secret session_id=ok", "tiny-secret"),
        ("DingTalk App Key: tiny-secret session_id=ok", "tiny-secret"),
        ("Pushover User Key: tiny-secret session_id=ok", "tiny-secret"),
        ('{"Database URL":"tiny-secret","session_id":"ok"}', "tiny-secret"),
        ("PASSWORD='abc def ghi' next", "abc def ghi"),
        ("SESSION_SECRET='abc def ghi' next", "abc def ghi"),
        ("Authorization: Bearer tiny", "tiny"),
        ('"api_key": "short123"', "short123"),
        ('{"accessToken":"short123"}', "short123"),
        ("api_keys: short123", "short123"),
        ("bot_token: tiny", "tiny"),
        ("telegram_bot_token: tiny", "tiny"),
        ("client_secret: tiny", "tiny"),
        ("clientSecret: tiny", "tiny"),
        ("database_url: sqlite-short", "sqlite-short"),
        ("aws_secret_access_key: tiny", "tiny"),
        ("db_passwd: tiny-secret", "tiny-secret"),
        ('{"db_passwd":"tiny-secret"}', "tiny-secret"),
        ('{"set-cookie":"session=tiny-secret"}', "tiny-secret"),
        (r'{"api\u005fkey":"tiny-secret"}', "tiny-secret"),
        (r'{"api\x5fkey":"tiny-secret"}', "tiny-secret"),
        ("OPENAI_API_KEY='x'\"'\"'tiny-secret' session_id=ok", "tiny-secret"),
        ("OPENAI_API_KEY+=tiny-secret session_id=ok", "tiny-secret"),
        ("{'api_key': 'tiny-secret', 'session_id': 'ok'}", "tiny-secret"),
        ("'password': tiny-secret session_id=ok", "tiny-secret"),
    ],
)
def test_diagnostics_redacts_short_credential_assignments(text: str, secret: str) -> None:
    redacted = redact_diagnostic_text(text, limit=1000)

    assert secret not in redacted
    assert "<redacted>" in redacted


def test_diagnostics_redacts_yaml_scalars_with_spaces_and_blocks() -> None:
    text = (
        "retry: 3 password: correct horse battery staple\n"
        "backup_password: 'correct horse''s secret'\n"
        "INFO private_key: |\n"
        "  tiny-secret\n"
        "  second secret line\n"
        "token_budget: 1000\n"
    )

    redacted = redact_diagnostic_text(text, limit=1000)

    assert "correct horse battery staple" not in redacted
    assert "correct horse''s secret" not in redacted
    assert "tiny-secret" not in redacted
    assert "second secret line" not in redacted
    assert "retry: 3" in redacted
    assert "token_budget: 1000" in redacted
    assert "password: <redacted>" in redacted
    assert "backup_password: '<redacted>'\n" in redacted
    assert "''s secret" not in redacted
    assert "private_key: <redacted>" in redacted


def test_diagnostics_redacts_yaml_block_scalars_with_node_properties() -> None:
    text = (
        "private_key: !<tag:yaml.org,2002:str> &pem |\n"
        "  tiny-secret\n"
        "session_id: yaml123\n"
    )

    redacted = redact_diagnostic_text(text, limit=1000)

    assert "tiny-secret" not in redacted
    assert redacted == "private_key: <redacted>\nsession_id: yaml123\n"


def test_diagnostics_preserves_non_sensitive_spaced_key_labels() -> None:
    text = "Cache Key: shard-one\nSort Key: created-at\nsession_id: ok\n"

    assert redact_diagnostic_text(text, limit=1000) == text


@pytest.mark.parametrize(
    ("text", "secrets", "preserved"),
    [
        (
            "? api_key\n: tiny-secret\nsession_id: yaml123\n",
            ("tiny-secret",),
            "session_id: yaml123",
        ),
        (
            "? 'api_key'\n: single-quoted-secret\nsession_id: yaml123\n",
            ("single-quoted-secret",),
            "session_id: yaml123",
        ),
        (
            '? "api_key"\n: double-quoted-secret\nsession_id: yaml123\n',
            ("double-quoted-secret",),
            "session_id: yaml123",
        ),
        (
            '? "api\\x5fkey"\n: tiny-secret\nsession_id: yaml123\n',
            ("tiny-secret",),
            "session_id: yaml123",
        ),
        (
            "? credentials\n:\n- tiny-one\n- tiny-two\nsession_id: yaml123\n",
            ("tiny-one", "tiny-two"),
            "session_id: yaml123",
        ),
        (
            "? private_key\n: |\n  tiny-secret\nsession_id: yaml123\n",
            ("tiny-secret",),
            "session_id: yaml123",
        ),
        (
            "- ? api_key\n  : tiny-secret\nsession_id: yaml123\n",
            ("tiny-secret",),
            "session_id: yaml123",
        ),
        (
            "? !!str api_key\n: tiny-secret\nsession_id: yaml123\n",
            ("tiny-secret",),
            "session_id: yaml123",
        ),
        (
            "- ? &cred private_key\n  : tiny-secret\nsession_id: yaml123\n",
            ("tiny-secret",),
            "session_id: yaml123",
        ),
        (
            "- ? credentials\n  :\n  - tiny-one\n  - tiny-two\nsession_id: yaml123\n",
            ("tiny-one", "tiny-two"),
            "session_id: yaml123",
        ),
        (
            "? api_key\n# note\n: tiny-secret\nsession_id: yaml123\n",
            ("tiny-secret",),
            "session_id: yaml123",
        ),
        (
            "? api_key\n  # note\n: tiny-secret\nsession_id: yaml123\n",
            ("tiny-secret",),
            "session_id: yaml123",
        ),
        (
            "? api_key\n\n: tiny-secret\nsession_id: yaml123\n",
            ("tiny-secret",),
            "session_id: yaml123",
        ),
    ],
)
def test_diagnostics_redacts_yaml_explicit_sensitive_mappings(
    text: str,
    secrets: tuple[str, ...],
    preserved: str,
) -> None:
    redacted = redact_diagnostic_text(text, limit=1000)

    for secret in secrets:
        assert secret not in redacted
    assert ": <redacted>" in redacted
    assert preserved in redacted


def test_diagnostics_redacts_indented_values_under_empty_sensitive_yaml_field() -> None:
    text = "api_keys:\n  - tiny-one\n  - tiny-two\nsession_id: yaml123\n"

    redacted = redact_diagnostic_text(text, limit=1000)

    assert "tiny-one" not in redacted
    assert "tiny-two" not in redacted
    assert "api_keys: <redacted>\n" in redacted
    assert "session_id: yaml123\n" in redacted


def test_diagnostics_redacts_comment_only_sensitive_yaml_field_blocks() -> None:
    text = "api_keys: # configured keys\n  - tiny-one\n  - tiny-two\nsession_id: yaml123\n"

    redacted = redact_diagnostic_text(text, limit=1000)

    assert "tiny-one" not in redacted
    assert "tiny-two" not in redacted
    assert "api_keys: <redacted>\n" in redacted
    assert "session_id: yaml123\n" in redacted


def test_diagnostics_redacts_comment_lines_within_sensitive_yaml_field_blocks() -> None:
    text = "api_keys: # configured keys\n# nested note\n- tiny-one\n- tiny-two\nsession_id: yaml123\n"

    redacted = redact_diagnostic_text(text, limit=1000)

    assert "nested note" not in redacted
    assert "tiny-one" not in redacted
    assert "tiny-two" not in redacted
    assert redacted == "api_keys: <redacted>\nsession_id: yaml123\n"


def test_diagnostics_redacts_indentless_sequences_under_sensitive_yaml_field() -> None:
    text = "api_keys:\n- tiny-one\n- tiny-two\nsession_id: yaml123\n"

    redacted = redact_diagnostic_text(text, limit=1000)

    assert "tiny-one" not in redacted
    assert "tiny-two" not in redacted
    assert "api_keys: <redacted>\n" in redacted
    assert "session_id: yaml123\n" in redacted


def test_diagnostics_redacts_sensitive_collections() -> None:
    text = (
        "api_keys: [first-secret, second-secret] token_budget: 1000\n"
        '{"credentials":{"username":"alice","value":"tiny-secret"},"session_id":"abc123"}'
    )

    redacted = redact_diagnostic_text(text, limit=1000)

    assert "first-secret" not in redacted
    assert "second-secret" not in redacted
    assert "tiny-secret" not in redacted
    assert "api_keys: <redacted> token_budget: 1000" in redacted
    assert '{"credentials":<redacted>,"session_id":"abc123"}' in redacted


@pytest.mark.parametrize(
    ("text", "secret_values", "preserved"),
    [
        (
            "api_keys:\n  - tiny-one\n  - tiny-two\nsession_id: abc123\n",
            ("tiny-one", "tiny-two"),
            "session_id: abc123",
        ),
        (
            "credentials:\n  username: alice\n  value: tiny-secret\nsession_id: abc123\n",
            ("alice", "tiny-secret"),
            "session_id: abc123",
        ),
        (
            "private_key:\n  tiny-secret\nfoo: bar\n",
            ("tiny-secret",),
            "foo: bar",
        ),
        (
            "api_keys: # configured keys\n  - tiny-one\nsession_id: abc123\n",
            ("tiny-one",),
            "session_id: abc123",
        ),
        (
            "api_keys:\n- tiny-one\n- tiny-two\nsession_id: abc123\n",
            ("tiny-one", "tiny-two"),
            "session_id: abc123",
        ),
        (
            "private_key: &pem |\n  tiny-secret\nsession_id: abc123\n",
            ("tiny-secret",),
            "session_id: abc123",
        ),
        (
            "credentials: !vault &creds\n  value: tiny-secret\nsession_id: abc123\n",
            ("tiny-secret",),
            "session_id: abc123",
        ),
        (
            "cookie:\n  session: tiny-one\n  csrf: tiny-two\nsession_id: abc123\n",
            ("tiny-one", "tiny-two"),
            "session_id: abc123",
        ),
        (
            "password: correct horse\n  battery staple\nsession_id: abc123\n",
            ("correct horse", "battery staple"),
            "session_id: abc123",
        ),
        (
            '"password": correct horse\n battery staple\nsession_id: abc123\n',
            ("correct horse", "battery staple"),
            "session_id: abc123",
        ),
        (
            '"password":\n  tiny-one\n  tiny-two\nsession_id: abc123\n',
            ("tiny-one", "tiny-two"),
            "session_id: abc123",
        ),
        (
            'password: !secret "tiny-one\n  tiny-two"\nsession_id: abc123\n',
            ("tiny-one", "tiny-two"),
            "session_id: abc123",
        ),
        (
            "authorization:\n  scheme: Bearer\n  credentials: tiny-auth\nsession_id: abc123\n",
            ("Bearer", "tiny-auth"),
            "session_id: abc123",
        ),
        (
            "Authorization: Basic tiny-auth\n  continued-secret\nsession_id: abc123\n",
            ("tiny-auth", "continued-secret"),
            "session_id: abc123",
        ),
        (
            "API Key:\n  - tiny-one\n  - tiny-two\nsession_id: abc123\n",
            ("tiny-one", "tiny-two"),
            "session_id: abc123",
        ),
        (
            "'credentials':\n  username: alice\n  value: tiny-secret\nsession_id: abc123\n",
            ("alice", "tiny-secret"),
            "session_id: abc123",
        ),
    ],
)
def test_diagnostics_redacts_indented_blocks_under_empty_sensitive_yaml_fields(
    text: str,
    secret_values: tuple[str, ...],
    preserved: str,
) -> None:
    redacted = redact_diagnostic_text(text, limit=1000)

    for secret in secret_values:
        assert secret not in redacted
    assert "<redacted>" in redacted
    assert preserved in redacted


@pytest.mark.parametrize(
    ("text", "secret", "preserved"),
    [
        (
            '{"AIHUBMIX_KEY":"json-short","session_id":"json123"}',
            "json-short",
            '"session_id":"json123"',
        ),
        (
            '{"DINGTALK_APP_KEY":"ding-short","session_id":"ding123"}',
            "ding-short",
            '"session_id":"ding123"',
        ),
        (
            "WECOM_ENCODING_AES_KEY: wecom-short\nsession_id: wecom123\n",
            "wecom-short",
            "session_id: wecom123",
        ),
        (
            "PUSHOVER_USER_KEY: push-short\nsession_id: push123\n",
            "push-short",
            "session_id: push123",
        ),
        (
            '{"NTFY_URL":"private-topic","session_id":"ntfy123"}',
            "private-topic",
            '"session_id":"ntfy123"',
        ),
    ],
)
def test_diagnostics_applies_registered_sensitive_names_to_structured_fields(
    text: str,
    secret: str,
    preserved: str,
) -> None:
    redacted = redact_diagnostic_text(text, limit=1000)

    assert secret not in redacted
    assert "<redacted>" in redacted
    assert preserved in redacted


@pytest.mark.parametrize(
    "field_name",
    sorted(
        local_cli_backend_module._SENSITIVE_ENV_EXACT_NAMES
        | local_cli_backend_module._registered_sensitive_env_exact_names()
    ),
)
def test_all_registered_sensitive_exact_names_are_redacted_in_json(
    field_name: str,
) -> None:
    redacted = redact_diagnostic_text(
        json.dumps({field_name: "tinyZ9", "session_id": "json123"}),
        limit=1000,
    )

    assert "tinyZ9" not in redacted
    assert '"session_id": "json123"' in redacted


@pytest.mark.parametrize(
    "field_name",
    sorted(local_cli_backend_module._registered_sensitive_env_exact_names()),
)
def test_all_registered_sensitive_exact_names_are_redacted_as_spaced_labels(
    field_name: str,
) -> None:
    label = field_name.replace("_", " ")

    redacted = redact_diagnostic_text(
        f"{label}: tinyZ9 session_id=label123",
        limit=1000,
    )

    assert "tinyZ9" not in redacted
    assert "<redacted>" in redacted


@pytest.mark.parametrize(
    "field_title",
    _registered_sensitive_titles_needing_title_match(),
)
def test_registered_sensitive_config_titles_are_redacted_as_structured_labels(
    field_title: str,
) -> None:
    redacted = redact_diagnostic_text(
        f"{field_title}: tiny-secret session_id=label123",
        limit=1000,
    )

    assert "tiny-secret" not in redacted
    assert "<redacted>" in redacted
    assert "session_id=label123" in redacted


@pytest.mark.parametrize(
    "field_title",
    _registered_sensitive_titles_needing_title_match(),
)
def test_registered_sensitive_config_titles_are_redacted_in_json(
    field_title: str,
) -> None:
    redacted = redact_diagnostic_text(
        json.dumps({field_title: "tiny-secret", "session_id": "json123"}),
        limit=1000,
    )

    assert "tiny-secret" not in redacted
    assert "<redacted>" in redacted
    assert '"session_id": "json123"' in redacted


def test_diagnostics_redacts_ansi_prefixed_sensitive_fields() -> None:
    text = "\x1b[31mpassword: tiny\x1b[0m session_id=abc123 \x1b[32mapi_key: short123\x1b[0m"

    redacted = redact_diagnostic_text(text, limit=1000)

    assert "\x1b[" not in redacted
    assert "tiny" not in redacted
    assert "short123" not in redacted
    assert redacted == "password: <redacted>"


@pytest.mark.parametrize(
    ("text", "secret", "preserved"),
    [
        (
            "Authorization: Basic dGlueTpzZWNyZXQ= session_id=abc123",
            "dGlueTpzZWNyZXQ=",
            "session_id=abc123",
        ),
        (
            "Authorization: Token tiny-secret token_budget=1000",
            "tiny-secret",
            "token_budget=1000",
        ),
        (
            "authorization=Negotiate abc.def.ghi token_budget=1000",
            "abc.def.ghi",
            "token_budget=1000",
        ),
        (
            'Authorization: Digest username="foo", realm="example", response="tiny-secret" session_id=abc123',
            "tiny-secret",
            "session_id=abc123",
        ),
        (
            "Proxy-Authorization: Basic tiny-secret session_id=abc123",
            "tiny-secret",
            "session_id=abc123",
        ),
        (
            "proxy-authorization=Negotiate abc.def.ghi token_budget=1000",
            "abc.def.ghi",
            "token_budget=1000",
        ),
        (
            "proxy_authorization: Basic underscore-secret session_id=proxy123",
            "underscore-secret",
            "session_id=proxy123",
        ),
        (
            "'authorization': Bearer tiny-secret session_id=ok",
            "tiny-secret",
            "session_id=ok",
        ),
        (
            "'proxy_authorization': Basic tiny-secret session_id=ok",
            "tiny-secret",
            "session_id=ok",
        ),
        (
            '"authorization": Bearer tiny-secret session_id=ok',
            "tiny-secret",
            "session_id=ok",
        ),
        (
            '"proxy_authorization": Basic tiny-secret session_id=ok',
            "tiny-secret",
            "session_id=ok",
        ),
        (
            "proxyAuthorization=Negotiate camel.secret token_budget=1000",
            "camel.secret",
            "token_budget=1000",
        ),
    ],
)
def test_diagnostics_redacts_non_bearer_authorization_values(
    text: str,
    secret: str,
    preserved: str,
) -> None:
    redacted = redact_diagnostic_text(text, limit=1000)

    assert secret not in redacted
    assert preserved in redacted
    assert (
        "Authorization: <redacted>" in redacted
        or "authorization=<redacted>" in redacted
        or "Proxy-Authorization: <redacted>" in redacted
        or "proxy-authorization=<redacted>" in redacted
        or "proxy_authorization: <redacted>" in redacted
        or "'authorization': <redacted>" in redacted
        or "'proxy_authorization': <redacted>" in redacted
        or '"authorization": <redacted>' in redacted
        or '"proxy_authorization": <redacted>' in redacted
        or "proxyAuthorization=<redacted>" in redacted
    )


def test_diagnostics_redacts_parameterized_oauth_authorization_values() -> None:
    text = (
        'Authorization: OAuth oauth_consumer_key="client", '
        'oauth_signature="tiny-secret" session_id=abc123'
    )

    redacted = redact_diagnostic_text(text, limit=1000)

    assert "tiny-secret" not in redacted
    assert "Authorization: <redacted> session_id=abc123" in redacted


@pytest.mark.parametrize(
    ("text", "preserved"),
    [
        (
            "Authorization: Bearer first-secret Proxy-Authorization: Basic second-secret session_id=ok",
            "session_id=ok",
        ),
        (
            "Authorization: Bearer first-secret authorization=Basic second-secret session_id=ok",
            "session_id=ok",
        ),
    ],
)
def test_diagnostics_redacts_multiple_authorization_fields_on_one_line(
    text: str,
    preserved: str,
) -> None:
    redacted = redact_diagnostic_text(text, limit=1000)

    assert "first-secret" not in redacted
    assert "second-secret" not in redacted
    assert preserved in redacted
    assert redacted.count("<redacted>") == 2


@pytest.mark.parametrize(
    ("text", "secret", "preserved"),
    [
        (
            "Authorization: AWS4-HMAC-SHA256 Credential=AKIA/test/aws4_request, "
            "SignedHeaders=host;x-amz-date, Signature=tiny-secret session_id=aws123",
            "tiny-secret",
            "session_id=aws123",
        ),
        (
            'Authorization: Signature keyId="client",algorithm="hmac-sha256",signature="tiny-secret" '
            "token_budget=1000",
            "tiny-secret",
            "token_budget=1000",
        ),
    ],
)
def test_diagnostics_redacts_parameterized_authorization_values_for_any_scheme(
    text: str,
    secret: str,
    preserved: str,
) -> None:
    redacted = redact_diagnostic_text(text, limit=1000)

    assert secret not in redacted
    assert preserved in redacted
    assert "Authorization: <redacted>" in redacted


def test_diagnostics_redacts_unclosed_quoted_sensitive_scalar() -> None:
    redacted = redact_diagnostic_text('password: "correct horse battery staple', limit=1000)

    assert "correct horse battery staple" not in redacted
    assert redacted == "password: <redacted>"


def test_diagnostics_redacts_multiline_quoted_sensitive_scalar() -> None:
    redacted = redact_diagnostic_text(
        'password: "correct horse\n battery staple"\nsession_id=abc123\n',
        limit=1000,
    )

    assert "correct horse" not in redacted
    assert "battery staple" not in redacted
    assert redacted == "password: <redacted>\nsession_id=abc123\n"


def test_diagnostics_redacts_multiline_plain_scalar_under_double_quoted_yaml_key() -> None:
    redacted = redact_diagnostic_text(
        '"password": correct horse\n battery staple\nsession_id: abc123\n',
        limit=1000,
    )

    assert "correct horse" not in redacted
    assert "battery staple" not in redacted
    assert redacted == '"password": <redacted>\nsession_id: abc123\n'


def test_diagnostics_redacts_single_line_multiword_plain_scalar_under_double_quoted_yaml_key() -> None:
    redacted = redact_diagnostic_text(
        '"password": correct horse battery staple\nsession_id: abc123\n',
        limit=1000,
    )

    assert "correct horse" not in redacted
    assert "battery staple" not in redacted
    assert redacted == '"password": <redacted>\nsession_id: abc123\n'


def test_diagnostics_redacts_tagged_plain_scalar_under_double_quoted_yaml_key() -> None:
    redacted = redact_diagnostic_text(
        '!!str "password": correct horse battery staple\nsession_id: ok\n',
        limit=1000,
    )

    assert "correct horse" not in redacted
    assert "battery staple" not in redacted
    assert redacted == '!!str "password": <redacted>\nsession_id: ok\n'


def test_diagnostics_redacts_anchored_continued_plain_scalar_under_double_quoted_yaml_key() -> None:
    redacted = redact_diagnostic_text(
        '&pem "password": correct horse\n battery staple\nsession_id: ok\n',
        limit=1000,
    )

    assert "correct horse" not in redacted
    assert "battery staple" not in redacted
    assert redacted == '&pem "password": <redacted>\nsession_id: ok\n'


def test_diagnostics_redacts_tagged_uri_plain_scalar_under_double_quoted_yaml_key() -> None:
    redacted = redact_diagnostic_text(
        '!<tag:yaml.org,2002:str> "password": correct horse battery staple\nsession_id: ok\n',
        limit=1000,
    )

    assert "correct horse" not in redacted
    assert "battery staple" not in redacted
    assert redacted == '!<tag:yaml.org,2002:str> "password": <redacted>\nsession_id: ok\n'


def test_diagnostics_redacts_tagged_uri_continued_plain_scalar_under_double_quoted_yaml_key() -> None:
    redacted = redact_diagnostic_text(
        '!<tag:yaml.org,2002:str> "password": correct horse\n battery staple\nsession_id: ok\n',
        limit=1000,
    )

    assert "correct horse" not in redacted
    assert "battery staple" not in redacted
    assert redacted == '!<tag:yaml.org,2002:str> "password": <redacted>\nsession_id: ok\n'


def test_diagnostics_redacts_indentless_sequence_under_double_quoted_yaml_key() -> None:
    redacted = redact_diagnostic_text(
        '"password": # configured\n- tiny-one\n- tiny-two\nsession_id: abc123\n',
        limit=1000,
    )

    assert "configured" not in redacted
    assert "tiny-one" not in redacted
    assert "tiny-two" not in redacted
    assert redacted == '"password": <redacted>\nsession_id: abc123\n'


def test_diagnostics_redacts_pretty_printed_json_value_on_following_line() -> None:
    redacted = redact_diagnostic_text(
        '{\n  "api_key":\n    "tiny-secret",\n  "session_id": "json123"\n}',
        limit=1000,
    )

    assert "tiny-secret" not in redacted
    assert '"api_key":\n    "<redacted>"' in redacted
    assert '"session_id": "json123"' in redacted


@pytest.mark.parametrize(
    "text",
    [
        '{"authorization":"Bearer tiny-secret","session_id":"abc123"}',
        '{"cookie":"session=tiny-secret","session_id":"abc123"}',
    ],
)
def test_diagnostics_redacts_quoted_json_authentication_fields(text: str) -> None:
    redacted = redact_diagnostic_text(text, limit=1000)

    assert "tiny-secret" not in redacted
    assert '"<redacted>"' in redacted
    assert '"session_id":"abc123"' in redacted


def test_diagnostics_preserves_json_structure_for_quoted_authorization_fields() -> None:
    redacted = redact_diagnostic_text(
        '{"authorization":"Bearer tiny-secret","session_id":"abc123"}',
        limit=1000,
    )

    assert redacted == '{"authorization":"<redacted>","session_id":"abc123"}'


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            '{"password": correct horse battery staple, "session_id": "ok"}',
            '{"password": <redacted>, "session_id": "ok"}',
        ),
        (
            '{"api_key": correct horse, "session_id": "ok"}',
            '{"api_key": <redacted>, "session_id": "ok"}',
        ),
        (
            "{'password': correct horse battery staple, 'session_id': 'ok'}",
            "{'password': <redacted>, 'session_id': 'ok'}",
        ),
        (
            "{password: correct horse, session_id: ok}",
            "{password: <redacted>, session_id: ok}",
        ),
    ],
)
def test_diagnostics_redacts_flow_style_sensitive_keys_with_unquoted_multiword_scalars(
    text: str,
    expected: str,
) -> None:
    redacted = redact_diagnostic_text(text, limit=1000)

    assert "correct horse" not in redacted
    assert "battery staple" not in redacted
    assert redacted == expected


@pytest.mark.parametrize(
    "text",
    [
        "password: correct horse=staple session_id=abc123",
        "password: correct horse_staple=value session_id=abc123",
    ],
)
def test_diagnostics_fails_closed_for_unquoted_yaml_secret_with_assignment(
    text: str,
) -> None:
    redacted = redact_diagnostic_text(text, limit=1000)
    assert redacted == "password: <redacted>"


@pytest.mark.parametrize(
    ("text", "secret", "expected"),
    [
        ("password: abc,def session_id=abc123", "abc,def", "password: <redacted>"),
        (
            "bot_token=tiny]} token_budget: 1000",
            "tiny]}",
            "bot_token=<redacted> token_budget: 1000",
        ),
    ],
)
def test_diagnostics_redacts_sensitive_scalars_with_punctuation(
    text: str,
    secret: str,
    expected: str,
) -> None:
    redacted = redact_diagnostic_text(text, limit=1000)

    assert secret not in redacted
    assert redacted == expected


@pytest.mark.parametrize(
    "sensitive_pattern",
    local_cli_backend_module._SENSITIVE_ENV_PATTERNS,
)
def test_uppercase_diagnostic_assignment_tracks_child_env_sensitive_contract(
    sensitive_pattern: str,
) -> None:
    name_segment = sensitive_pattern.strip("_")
    text = f"DSA_{name_segment}_VALUE=tiny-value"

    redacted = redact_diagnostic_text(text, limit=1000)

    assert "tiny-value" not in redacted
    assert "<redacted>" in redacted


@pytest.mark.parametrize(
    "text",
    [
        "MONKEY=banana next",
        "KEYBOARD_LAYOUT=us next",
        "retry: 3 token_budget: 1000",
        "docs=https://example.com/public/docs?monkey=banana&foo=bar",
        "analysis_key_factor=valuation next",
        "sort_key=price primary_key=id cache_key=reports",
        "session_id=abc123 user_session: abc123",
        'message: "normal diagnostic value"',
    ],
)
def test_diagnostics_preserves_noncredential_assignments(text: str) -> None:
    assert redact_diagnostic_text(text, limit=1000) == text


def test_nonzero_exit_diagnostic_previews_redact_short_credentials(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print("CUSTOM_API_KEY=stdout-short session_id=abc123")
print("password: correct horse battery staple")
print("backup_password: 'correct horse''s secret'")
print("bot_token: tiny,trail token_budget: 1000")
print("Authorization: Basic dGlueTpzZWNyZXQ= session_id=auth123")
print('"api_keys": "stderr-short" token_budget: 1000', file=sys.stderr)
print("private_key: |\\n  tiny-secret", file=sys.stderr)
print("telegram_bot_token=tiny]} session_id=stderr123", file=sys.stderr)
print("authorization=Token tiny-secret token_budget=1000", file=sys.stderr)
print("authorization=Negotiate abc.def.ghi token_budget=2000", file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.NON_ZERO_EXIT
    stdout_preview = exc_info.value.details["stdout_preview"]
    stderr_preview = exc_info.value.details["stderr_preview"]
    assert "stdout-short" not in stdout_preview
    assert "stderr-short" not in stderr_preview
    assert "correct horse battery staple" not in stdout_preview
    assert "correct horse''s secret" not in stdout_preview
    assert "tiny-secret" not in stderr_preview
    assert "tiny,trail" not in stdout_preview
    assert "tiny]}" not in stderr_preview
    assert "dGlueTpzZWNyZXQ=" not in stdout_preview
    assert "abc.def.ghi" not in stderr_preview
    assert "CUSTOM_API_KEY=<redacted>" in stdout_preview
    assert "password: <redacted>" in stdout_preview
    assert "backup_password: '<redacted>'" in stdout_preview
    assert "bot_token: <redacted>" in stdout_preview
    assert "Authorization: <redacted>" in stdout_preview
    assert '"api_keys": "<redacted>"' in stderr_preview
    assert "private_key: <redacted>" in stderr_preview
    assert "telegram_bot_token=<redacted>" in stderr_preview
    assert "authorization=<redacted>" in stderr_preview
    assert "''s secret" not in stdout_preview
    assert "session_id=abc123" in stdout_preview
    assert "session_id=auth123" in stdout_preview
    assert "session_id=stderr123" in stderr_preview
    assert "token_budget: 1000" in stderr_preview
    assert "token_budget=1000" in stderr_preview
    assert "token_budget=2000" in stderr_preview


def test_nonzero_exit_diagnostic_previews_redact_digest_proxy_and_camelcase_credentials(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        f"""
import sys
print('Authorization: Digest username="foo", realm="example", response="tiny-secret" session_id=auth123', file=sys.stderr)
print('Proxy-Authorization: Basic proxy-short session_id=proxy123', file=sys.stderr)
print('{{"accessToken":"json-short","session_id":"camel123"}}', file=sys.stderr)
print('clientSecret: yaml-short token_budget=1000', file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.NON_ZERO_EXIT
    stderr_preview = exc_info.value.details["stderr_preview"]
    assert "tiny-secret" not in stderr_preview
    assert "proxy-short" not in stderr_preview
    assert "json-short" not in stderr_preview
    assert "yaml-short" not in stderr_preview
    assert 'Authorization: <redacted> session_id=auth123' in stderr_preview
    assert 'Proxy-Authorization: <redacted> session_id=proxy123' in stderr_preview
    assert '{"accessToken":"<redacted>","session_id":"camel123"}' in stderr_preview
    assert 'clientSecret: <redacted>\n' in stderr_preview


def test_nonzero_exit_diagnostic_previews_redact_ansi_oauth_and_multiline_quoted_secrets(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print("\\x1b[31mpassword: tiny\\x1b[0m session_id=ansi123")
print('Authorization: OAuth oauth_consumer_key="client", oauth_signature="tiny-secret" session_id=oauth123', file=sys.stderr)
print('password: "correct horse', file=sys.stderr)
print(' battery staple"', file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.NON_ZERO_EXIT
    stdout_preview = exc_info.value.details["stdout_preview"]
    stderr_preview = exc_info.value.details["stderr_preview"]
    assert "\x1b[" not in stdout_preview
    assert "tiny" not in stdout_preview
    assert "tiny-secret" not in stderr_preview
    assert "correct horse" not in stderr_preview
    assert "battery staple" not in stderr_preview
    assert "password: <redacted>\n" in stdout_preview
    assert "Authorization: <redacted> session_id=oauth123" in stderr_preview
    assert "password: <redacted>\n" in stderr_preview


def test_nonzero_exit_diagnostic_previews_redact_sensitive_collections(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print("api_keys: [first-secret, second-secret] token_budget: 1000")
print('{"credentials":{"username":"alice","value":"tiny-secret"},"session_id":"nested123"}', file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.NON_ZERO_EXIT
    stdout_preview = exc_info.value.details["stdout_preview"]
    stderr_preview = exc_info.value.details["stderr_preview"]
    assert "first-secret" not in stdout_preview
    assert "second-secret" not in stdout_preview
    assert "tiny-secret" not in stderr_preview
    assert "api_keys: <redacted> token_budget: 1000" in stdout_preview
    assert '{"credentials":<redacted>,"session_id":"nested123"}' in stderr_preview


def test_nonzero_exit_previews_redact_empty_yaml_blocks_and_registered_fields(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print("api_keys:\\n  - tiny-one\\n  - tiny-two\\nsession_id: yaml123")
print("api_keys: # configured keys\\n# nested note\\n- stdout-short\\n- stdout-short-2\\nsession_id: yaml456")
print("private_key: !<tag:yaml.org,2002:str> &pem |\\n  anchored-secret\\nsession_id: anchor123")
print("cookie:\\n  session: cookie-one\\n  csrf: cookie-two\\nsession_id: cookie-yaml")
print("password: correct horse\\n  battery staple\\nsession_id: plain-yaml")
print('"password": correct horse\\n battery staple\\nsession_id: quoted-key-yaml')
print('"password": correct horse battery staple\\nsession_id: quoted-inline-yaml')
print('"password":\\n  quoted-empty-one\\n  quoted-empty-two\\nsession_id: quoted-empty-yaml')
print('password: !secret "tagged-one\\n  tagged-two"\\nsession_id: tagged-yaml')
print('{"AIHUBMIX_KEY":"json-short","session_id":"json123"}', file=sys.stderr)
print('{"set-cookie":"session=cookie-header","session_id":"header123"}', file=sys.stderr)
print('{"api\\\\u005fkey":"escaped-json","session_id":"escaped123"}', file=sys.stderr)
print("? api_key\\n: explicit-secret\\nsession_id: explicit123", file=sys.stderr)
print("? 'api_key'\\n: quoted-explicit-secret\\nsession_id: quoted-explicit123", file=sys.stderr)
print("- ? api_key\\n  : nested-explicit-secret\\nsession_id: nested-explicit123", file=sys.stderr)
print("- ? credentials\\n  :\\n  - nested-one\\n  - nested-two\\nsession_id: nested-list123", file=sys.stderr)
print("OPENAI_API_KEY='x'\\\"'\\\"'shell-quoted' session_id=quoted123", file=sys.stderr)
print("OPENAI_API_KEY+=appended-secret session_id=append123", file=sys.stderr)
print("{'api_key': 'single-quoted', 'session_id': 'single123'}", file=sys.stderr)
print("WECOM_ENCODING_AES_KEY: yaml-short\\nsession_id: wecom123", file=sys.stderr)
print("OPENAI_FOO=\\\\ shell-short session_id=shell123", file=sys.stderr)
print("OPENAI_API_KEY=\\\\\\ncontinued-shell-secret session_id=shell456", file=sys.stderr)
print("API Key: label-short session_id=label123", file=sys.stderr)
print("OpenAI API Keys (Multi): title-short session_id=title123", file=sys.stderr)
print("? api_key\\n# note\\n: commented-explicit-secret\\nsession_id: explicit456", file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.NON_ZERO_EXIT
    stdout_preview = exc_info.value.details["stdout_preview"]
    stderr_preview = exc_info.value.details["stderr_preview"]
    for secret in (
        "tiny-one",
        "tiny-two",
        "nested note",
        "stdout-short",
        "stdout-short-2",
        "anchored-secret",
        "cookie-one",
        "cookie-two",
        "correct horse",
        "battery staple",
        "quoted-empty-one",
        "quoted-empty-two",
        "tagged-one",
        "tagged-two",
        "json-short",
        "cookie-header",
        "escaped-json",
        "explicit-secret",
        "quoted-explicit-secret",
        "nested-explicit-secret",
        "nested-one",
        "nested-two",
        "shell-quoted",
        "appended-secret",
        "single-quoted",
        "yaml-short",
        "shell-short",
        "continued-shell-secret",
        "label-short",
        "title-short",
        "commented-explicit-secret",
    ):
        assert secret not in f"{stdout_preview}\n{stderr_preview}"
    assert "api_keys: <redacted>" in stdout_preview
    assert "session_id: yaml123" in stdout_preview
    assert "session_id: yaml456" in stdout_preview
    assert "private_key: <redacted>" in stdout_preview
    assert "session_id: anchor123" in stdout_preview
    assert "cookie: <redacted>" in stdout_preview
    assert "session_id: cookie-yaml" in stdout_preview
    assert "session_id: plain-yaml" in stdout_preview
    assert "session_id: quoted-key-yaml" in stdout_preview
    assert "session_id: quoted-inline-yaml" in stdout_preview
    assert "session_id: quoted-empty-yaml" in stdout_preview
    assert "session_id: tagged-yaml" in stdout_preview
    assert '{"AIHUBMIX_KEY":"<redacted>","session_id":"json123"}' in stderr_preview
    assert '{"set-cookie":"<redacted>","session_id":"header123"}' in stderr_preview
    assert r'{"api\u005fkey":"<redacted>","session_id":"escaped123"}' in stderr_preview
    assert "? api_key\n: <redacted>\nsession_id: explicit123" in stderr_preview
    assert "? 'api_key'\n: <redacted>\nsession_id: quoted-explicit123" in stderr_preview
    assert "- ? api_key\n  : <redacted>\nsession_id: nested-explicit123" in stderr_preview
    assert "- ? credentials\n  : <redacted>\nsession_id: nested-list123" in stderr_preview
    assert "OPENAI_API_KEY='<redacted>' session_id=quoted123" in stderr_preview
    assert "OPENAI_API_KEY+=<redacted> session_id=append123" in stderr_preview
    assert "{'api_key': '<redacted>', 'session_id': 'single123'}" in stderr_preview
    assert "WECOM_ENCODING_AES_KEY: <redacted>" in stderr_preview
    assert "session_id: wecom123" in stderr_preview
    assert "OPENAI_FOO=<redacted> session_id=shell123" in stderr_preview
    assert "OPENAI_API_KEY=<redacted> session_id=shell456" in stderr_preview
    assert "API Key: <redacted>" in stderr_preview
    assert "OpenAI API Keys (Multi): <redacted>" in stderr_preview
    assert "? api_key\n: <redacted>\nsession_id: explicit456" in stderr_preview


def test_nonzero_exit_previews_redact_quoted_authorization_fields(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print("'authorization': Bearer quoted-auth-secret session_id=auth456", file=sys.stderr)
print('"proxy_authorization": Basic quoted-proxy-secret session_id=proxy456', file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    stderr_preview = exc_info.value.details["stderr_preview"]

    assert "quoted-auth-secret" not in stderr_preview
    assert "quoted-proxy-secret" not in stderr_preview
    assert "'authorization': <redacted> session_id=auth456" in stderr_preview
    assert '"proxy_authorization": <redacted> session_id=proxy456' in stderr_preview


def test_nonzero_exit_previews_redact_multiple_authorization_fields_on_one_line(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print("Authorization: Bearer first-secret Proxy-Authorization: Basic second-secret session_id=auth789", file=sys.stderr)
print("Authorization: Bearer third-secret authorization=Basic fourth-secret session_id=auth790", file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    stderr_preview = exc_info.value.details["stderr_preview"]

    for secret in ("first-secret", "second-secret", "third-secret", "fourth-secret"):
        assert secret not in stderr_preview
    assert (
        "Authorization: <redacted> Proxy-Authorization: <redacted> session_id=auth789"
        in stderr_preview
    )
    assert (
        "Authorization: <redacted> authorization=<redacted> session_id=auth790"
        in stderr_preview
    )


def test_nonzero_exit_previews_redact_explicit_yaml_with_indented_comment(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print("? api_key\\n  # indented note\\n: indented-explicit-secret\\nsession_id: explicit789", file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    stderr_preview = exc_info.value.details["stderr_preview"]

    assert "indented-explicit-secret" not in stderr_preview
    assert "? api_key\n: <redacted>\nsession_id: explicit789" in stderr_preview


def test_nonzero_exit_previews_redact_tagged_and_yaml_escaped_explicit_keys(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print('{"api\\\\x5fkey":"escaped-hex-json","session_id":"escapedhex123"}', file=sys.stderr)
print("? !!str api_key\\n: tagged-explicit-secret\\nsession_id: tagged-explicit123", file=sys.stderr)
print('- ? &cred "api\\\\x5fkey"\\n  : anchored-escaped-secret\\nsession_id: anchored-explicit123', file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.NON_ZERO_EXIT
    stderr_preview = exc_info.value.details["stderr_preview"]
    assert "escaped-hex-json" not in stderr_preview
    assert "tagged-explicit-secret" not in stderr_preview
    assert "anchored-escaped-secret" not in stderr_preview
    assert r'{"api\x5fkey":"<redacted>","session_id":"escapedhex123"}' in stderr_preview
    assert "? !!str api_key\n: <redacted>\nsession_id: tagged-explicit123" in stderr_preview
    assert (
        '- ? &cred "api\\x5fkey"\n  : <redacted>\nsession_id: anchored-explicit123'
        in stderr_preview
    )


def test_nonzero_exit_diagnostic_previews_redact_repo_env_json_and_parameterized_auth(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print("AIHUBMIX_KEY=stdout-short session_id=stdout123")
print("LONGBRIDGE_APP_KEY=stderr-short session_id=bridge123", file=sys.stderr)
print("NTFY_URL=https://ntfy.sh/private-topic session_id=ntfy123", file=sys.stderr)
print("PUSHOVER_USER_KEY=notify-short session_id=push123", file=sys.stderr)
print("proxyAuthorization: Basic proxy-short session_id=proxy123", file=sys.stderr)
print('{', file=sys.stderr)
print('  "api_key":', file=sys.stderr)
print('    "json-short",', file=sys.stderr)
print('  "session_id": "json123"', file=sys.stderr)
print('}', file=sys.stderr)
print("Authorization: AWS4-HMAC-SHA256 Credential=AKIA/20240101/test/aws4_request, SignedHeaders=host;x-amz-date, Signature=tiny-secret session_id=aws123", file=sys.stderr)
print('Authorization: Signature keyId="client",algorithm="hmac-sha256",signature="sig-short" token_budget=1000', file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.NON_ZERO_EXIT
    stdout_preview = exc_info.value.details["stdout_preview"]
    stderr_preview = exc_info.value.details["stderr_preview"]
    assert "stdout-short" not in stdout_preview
    assert "stderr-short" not in stderr_preview
    assert "https://ntfy.sh/private-topic" not in stderr_preview
    assert "notify-short" not in stderr_preview
    assert "proxy-short" not in stderr_preview
    assert "json-short" not in stderr_preview
    assert "tiny-secret" not in stderr_preview
    assert "sig-short" not in stderr_preview
    assert "AIHUBMIX_KEY=<redacted> session_id=stdout123" in stdout_preview
    assert "LONGBRIDGE_APP_KEY=<redacted> session_id=bridge123" in stderr_preview
    assert "NTFY_URL=<redacted> session_id=ntfy123" in stderr_preview
    assert "PUSHOVER_USER_KEY=<redacted> session_id=push123" in stderr_preview
    assert "proxyAuthorization: <redacted> session_id=proxy123" in stderr_preview
    assert '"api_key":\n    "<redacted>"' in stderr_preview
    assert '"session_id": "json123"' in stderr_preview
    assert "Authorization: <redacted> session_id=aws123" in stderr_preview
    assert "Authorization: <redacted> token_budget=1000" in stderr_preview


def test_nonzero_exit_previews_redact_sensitive_env_command_substitutions(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print("OPENAI_FOO=$(printf %s stdout-secret) session_id=stdout789")
print("export OPENAI_API_KEY=$(printf '%s %s' stderr tiny-secret) session_id=stderr789", file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    stdout_preview = exc_info.value.details["stdout_preview"]
    stderr_preview = exc_info.value.details["stderr_preview"]

    for secret in ("stdout-secret", "tiny-secret"):
        assert secret not in f"{stdout_preview}\n{stderr_preview}"
    assert "OPENAI_FOO=<redacted> session_id=stdout789" in stdout_preview
    assert "export OPENAI_API_KEY=<redacted> session_id=stderr789" in stderr_preview


def test_redact_diagnostic_text_multi_segment_shell_command_substitutions(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print("A=$(echo OPENAI_API_KEY=sk-12345);B=ok; tail $(printenv SECRET_TOKEN)")
print("safe=$(date); echo $(ls)", file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    stdout_preview = exc_info.value.details["stdout_preview"]
    stderr_preview = exc_info.value.details["stderr_preview"]

    for secret in ("OPENAI_API_KEY", "sk-12345", "SECRET_TOKEN"):
        assert secret not in f"{stdout_preview}\n{stderr_preview}"
    assert "<redacted>" in stdout_preview
    assert stderr_preview.count("<redacted>") == 0


@pytest.mark.parametrize(
    "diagnostic, must_keep, must_redact",
    [
        # OR-COR-7c0a5d41: export SENSITIVE=$(...) form must not drop
        # trailing non-sensitive fields like session_id when the
        # substitution body contains a sensitive uppercase token.
        # NOTE: the LHS assignment name (``OPENAI_API_KEY``) is itself
        # sensitive and intentionally displayed as the assignment
        # target — the leakage vector we guard here is the inner
        # command-substitution secret (``SECRET_TOKEN`` / ``sk-12345``)
        # and the *trailing* non-sensitive fields that the second-pass
        # scan was eaten by overlapping spans.
        (
            "export OPENAI_API_KEY=$(printenv SECRET_TOKEN) session_id=dup1 token_budget=1000",
            ["session_id=dup1", "token_budget=1000"],
            ["SECRET_TOKEN", "printenv SECRET_TOKEN"],
        ),
        (
            "export OPENAI_API_KEY=$(echo OPENAI_API_KEY=sk-12345) session_id=dup3",
            ["session_id=dup3"],
            ["sk-12345"],
        ),
        # Non-export form must continue to preserve trailing fields.
        (
            "OPENAI_API_KEY=$(printenv SECRET_TOKEN) session_id=dup4 token_budget=2000",
            ["session_id=dup4", "token_budget=2000"],
            ["SECRET_TOKEN", "printenv SECRET_TOKEN"],
        ),
    ],
)
def test_redact_diagnostic_text_export_env_preserves_trailing_fields(
    diagnostic: str, must_keep: list[str], must_redact: list[str]
) -> None:
    """``export SENSITIVE_ENV=$(printenv OTHER_SECRET) session_id=...``
    must redact the secret substitution while preserving the trailing
    non-sensitive diagnostics (session_id, token_budget, …). Regression
    for OR-COR-7c0a5d41.
    """
    redacted = redact_diagnostic_text(diagnostic, limit=1000)
    for secret in must_redact:
        assert secret not in redacted, f"leaked {secret!r}: {redacted!r}"
    for kept in must_keep:
        assert kept in redacted, f"dropped {kept!r}: {redacted!r}"
    # Sanity: the LHS assignment name (e.g. ``OPENAI_API_KEY=``) is the
    # redaction *target* marker and should remain visible so users
    # can see which env was scrubbed.
    assert "<redacted>" in redacted


def test_nonzero_exit_previews_redact_json_auth_and_embedded_assignments(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print("password: correct horse=staple session_id=abc123")
print('{"authorization":"Bearer tiny-secret","session_id":"auth123"}', file=sys.stderr)
print('{"cookie":"session=cookie-secret","session_id":"cookie123"}', file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.NON_ZERO_EXIT
    stdout_preview = exc_info.value.details["stdout_preview"]
    stderr_preview = exc_info.value.details["stderr_preview"]
    assert stdout_preview == "password: <redacted>\n"
    assert "tiny-secret" not in stderr_preview
    assert "cookie-secret" not in stderr_preview
    assert '{"authorization":"<redacted>","session_id":"auth123"}' in stderr_preview
    assert '{"cookie":"<redacted>","session_id":"cookie123"}' in stderr_preview


def test_nonzero_exit_previews_redact_flow_style_unquoted_multitoken_secrets(
    tmp_path: Path,
) -> None:
    backend = _backend(
        tmp_path,
        """
import sys
print('{"password": correct horse battery staple, "session_id": "json123"}', file=sys.stderr)
print('{"api_key": correct horse, "session_id": "api123"}', file=sys.stderr)
print("{'password': correct horse battery staple, 'session_id': 'yaml123'}", file=sys.stderr)
print('{password: correct horse, session_id: yaml456}', file=sys.stderr)
raise SystemExit(2)
""",
    )

    with pytest.raises(GenerationError) as exc_info:
        backend.generate("prompt", {})

    assert exc_info.value.error_code is GenerationErrorCode.NON_ZERO_EXIT
    stderr_preview = exc_info.value.details["stderr_preview"]
    assert "correct horse" not in stderr_preview
    assert "battery staple" not in stderr_preview
    assert '{"password": <redacted>, "session_id": "json123"}' in stderr_preview
    assert '{"api_key": <redacted>, "session_id": "api123"}' in stderr_preview
    assert "{'password': <redacted>, 'session_id': 'yaml123'}" in stderr_preview
    assert "{password: <redacted>, session_id: yaml456}" in stderr_preview


def test_preview_diagnostics_from_files_redacts_truncated_quoted_sensitive_scalar(
    tmp_path: Path,
) -> None:
    long_password = "correct horse battery staple " * 130
    stderr_text = f'password: "{long_password}"\n'
    assert len(stderr_text.encode("utf-8")) > local_cli_backend_module._PREVIEW_LIMIT * 4

    stdout_path = tmp_path / "stdout.txt"
    stderr_path = tmp_path / "stderr.txt"
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")

    previews = local_cli_backend_module._preview_diagnostics_from_files(stdout_path, stderr_path)

    assert "correct horse battery staple" not in previews["stderr_preview"]
    assert previews["stderr_preview"] == "password: <redacted>"


def test_effective_local_cli_concurrency_uses_minimum() -> None:
    assert effective_local_cli_concurrency(_config()) == 1
    assert effective_local_cli_concurrency(
        _config(generation_backend_max_concurrency=4, local_cli_backend_max_concurrency=2)
    ) == 2
    assert effective_local_cli_concurrency(
        _config(generation_backend_max_concurrency=1, local_cli_backend_max_concurrency=5)
    ) == 1
    assert effective_local_cli_concurrency(
        _config(generation_backend_max_concurrency=999, local_cli_backend_max_concurrency=999)
    ) == 4


def test_local_cli_concurrency_limit_serializes_subprocesses(tmp_path: Path) -> None:
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    backend = _backend(
        tmp_path,
        f"""
import json, os, pathlib, time
events_dir = pathlib.Path({str(events_dir)!r})
pid = os.getpid()
start = time.time()
time.sleep(0.25)
end = time.time()
(events_dir / f"{{pid}}.json").write_text(
    json.dumps({{"start": start, "end": end}}),
    encoding="utf-8",
)
print(json.dumps({{"sentiment_score": 60}}))
""",
        generation_backend_max_concurrency=4,
        local_cli_backend_max_concurrency=1,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: backend.generate("prompt", {}), range(2)))

    assert [json.loads(result.text)["sentiment_score"] for result in results] == [60, 60]
    intervals = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in events_dir.glob("*.json")
    ]
    assert len(intervals) == 2
    intervals.sort(key=lambda item: item["start"])
    assert intervals[1]["start"] >= intervals[0]["end"]
