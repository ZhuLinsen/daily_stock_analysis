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
    monkeypatch.setenv("CODEX_CLI_TOKEN", "codex-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/claude")
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", "{}")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("WEBHOOK_TOKEN", "token")
    monkeypatch.setenv("AUTHORIZATION", "Bearer token")

    child_env = build_local_cli_env()

    assert child_env["PATH"] == "/bin"
    assert child_env["HOME"] == "/tmp/home"
    assert child_env["CODEX_HOME"] == "/tmp/codex-home"
    assert child_env["LC_MESSAGES"] == "C"
    assert "UNRELATED_VALUE" not in child_env
    assert "CODEX_CLI_TOKEN" not in child_env
    assert "ANTHROPIC_API_KEY" not in child_env
    assert "ANTHROPIC_MODEL" not in child_env
    assert "CLAUDE_CONFIG_DIR" not in child_env
    assert "OPENCODE_CONFIG_CONTENT" not in child_env
    assert "OPENAI_API_KEY" not in child_env
    assert "WEBHOOK_TOKEN" not in child_env
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
