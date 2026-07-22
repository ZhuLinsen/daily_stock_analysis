# -*- coding: utf-8 -*-
"""Agent backend compatibility-status contract tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from src.services.agent_backend_status_service import AgentBackendStatusService, _run_codex_probe


_PROTOCOL_SCHEMAS = {
    "v2/ThreadStartParams.json": {"dynamicTools": {}, "runtimeWorkspaceRoots": {}},
    "v2/ThreadStartResponse.json": {"activePermissionProfile": {}, "runtimeWorkspaceRoots": {}},
    "ClientRequest.json": [
        "thread/inject_items",
        "turn/start",
        "turn/interrupt",
        "config/read",
        "mcpServerStatus/list",
    ],
    "ServerRequest.json": ["item/tool/call"],
    "ServerNotification.json": ["item/completed", "turn/completed"],
}


def _write_protocol_schemas(schema_dir: Path, *, missing: str | None = None) -> None:
    for relative_path, payload in _PROTOCOL_SCHEMAS.items():
        path = schema_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, dict):
            content = {key: value for key, value in payload.items() if key != missing}
        else:
            content = [value for value in payload if value != missing]
        path.write_text(json.dumps(content), encoding="utf-8")


def _install_successful_codex_probe(monkeypatch, *, version: str = "codex-cli test\n") -> list[list[str]]:
    monkeypatch.setattr(
        "src.services.agent_backend_status_service.resolve_command",
        lambda: ["/usr/local/bin/codex", "app-server", "--stdio"],
    )
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        if "generate-json-schema" in argv:
            _write_protocol_schemas(Path(argv[argv.index("--out") + 1]))
        return SimpleNamespace(returncode=0, stdout=version)

    monkeypatch.setattr("src.services.agent_backend_status_service._run_codex_probe", fake_run)
    return calls


def test_auto_status_keeps_litellm_route_and_flat_contract() -> None:
    payload = AgentBackendStatusService(
        effective_map={
            "AGENT_BACKEND": "auto",
            "LITELLM_MODEL": "deepseek/deepseek-chat",
            "DEEPSEEK_API_KEY": "test-key-value",
        }
    ).get_status()

    assert payload == {
        "backend": "litellm",
        "available": True,
        "experimental": False,
        "version": None,
        "error_code": None,
        "message": None,
    }


def test_litellm_status_uses_unsaved_model_draft() -> None:
    payload = AgentBackendStatusService(
        effective_map={
            "AGENT_BACKEND": "auto",
            "LITELLM_MODEL": "deepseek/deepseek-chat",
            "DEEPSEEK_API_KEY": "draft-key",
        }
    ).get_status()

    assert payload["backend"] == "litellm"
    assert payload["available"] is True


def test_codex_multi_is_rejected_without_command_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.services.agent_backend_status_service.resolve_command",
        lambda: (_ for _ in ()).throw(AssertionError("command probe must not run")),
    )
    payload = AgentBackendStatusService(
        effective_map={"AGENT_BACKEND": "codex_app_server", "AGENT_ARCH": "multi"}
    ).get_status()

    assert payload["available"] is False
    assert payload["error_code"] == "unsupported_agent_arch"


def test_explicit_agent_mode_false_remains_a_kill_switch(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.services.agent_backend_status_service.resolve_command",
        lambda: (_ for _ in ()).throw(AssertionError("command probe must not run")),
    )
    payload = AgentBackendStatusService(
        effective_map={
            "AGENT_BACKEND": "codex_app_server",
            "AGENT_ARCH": "single",
            "AGENT_MODE": "false",
        }
    ).get_status()

    assert payload["available"] is False
    assert payload["error_code"] == "agent_mode_disabled"


def test_native_windows_is_rejected_before_command_probe(monkeypatch) -> None:
    monkeypatch.setattr("src.services.agent_backend_status_service.is_native_windows", lambda: True)
    monkeypatch.setattr(
        "src.services.agent_backend_status_service.resolve_command",
        lambda: (_ for _ in ()).throw(AssertionError("command probe must not run")),
    )

    payload = AgentBackendStatusService(
        effective_map={"AGENT_BACKEND": "codex_app_server", "AGENT_ARCH": "single"}
    ).get_status()

    assert payload["available"] is False
    assert payload["error_code"] == "platform_unsupported"


def test_codex_status_checks_protocol_without_model_request_or_path_disclosure(monkeypatch) -> None:
    calls = _install_successful_codex_probe(monkeypatch)

    payload = AgentBackendStatusService(
        effective_map={"AGENT_BACKEND": "codex_app_server", "AGENT_ARCH": "single"}
    ).get_status()

    assert payload == {
        "backend": "codex_app_server",
        "available": True,
        "experimental": True,
        "version": "codex-cli test",
        "error_code": None,
        "message": None,
    }
    assert "/usr/local/bin/codex" not in json.dumps(payload)
    assert calls[0][:4] == [
        "/usr/local/bin/codex",
        "app-server",
        "generate-json-schema",
        "--experimental",
    ]
    assert calls[1] == ["/usr/local/bin/codex", "--version"]
    assert not hasattr(AgentBackendStatusService, "smoke_test")


@pytest.mark.parametrize(
    "missing",
    [
        "dynamicTools",
        "runtimeWorkspaceRoots",
        "activePermissionProfile",
        "thread/inject_items",
        "turn/start",
        "turn/interrupt",
        "config/read",
        "mcpServerStatus/list",
        "item/tool/call",
        "item/completed",
        "turn/completed",
    ],
)
def test_codex_status_rejects_each_missing_required_protocol_capability(
    monkeypatch,
    missing: str,
) -> None:
    monkeypatch.setattr(
        "src.services.agent_backend_status_service.resolve_command",
        lambda: ["codex", "app-server", "--stdio"],
    )

    def fake_run(argv, **_kwargs):
        if "generate-json-schema" in argv:
            _write_protocol_schemas(Path(argv[argv.index("--out") + 1]), missing=missing)
        return SimpleNamespace(returncode=0, stdout="codex-cli test\n")

    monkeypatch.setattr("src.services.agent_backend_status_service._run_codex_probe", fake_run)
    payload = AgentBackendStatusService(
        effective_map={"AGENT_BACKEND": "codex_app_server", "AGENT_ARCH": "single"}
    ).get_status()

    assert payload["available"] is False
    assert payload["error_code"] == "capability_unsupported"


def test_codex_status_treats_version_as_optional_display_data(monkeypatch) -> None:
    _install_successful_codex_probe(monkeypatch, version="")

    payload = AgentBackendStatusService(
        effective_map={"AGENT_BACKEND": "codex_app_server", "AGENT_ARCH": "single"}
    ).get_status()

    assert payload["available"] is True
    assert payload["version"] is None
    assert payload["error_code"] is None


def test_codex_status_does_not_fail_when_optional_version_probe_times_out(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.services.agent_backend_status_service.resolve_command",
        lambda: ["/usr/local/bin/codex", "app-server", "--stdio"],
    )

    def fake_run(argv, **_kwargs):
        if "generate-json-schema" in argv:
            _write_protocol_schemas(Path(argv[argv.index("--out") + 1]))
            return SimpleNamespace(returncode=0, stdout="")
        raise subprocess.TimeoutExpired(argv, 5)

    monkeypatch.setattr("src.services.agent_backend_status_service._run_codex_probe", fake_run)

    payload = AgentBackendStatusService(
        effective_map={"AGENT_BACKEND": "codex_app_server", "AGENT_ARCH": "single"}
    ).get_status()

    assert payload["available"] is True
    assert payload["version"] is None


@pytest.mark.skipif(os.name == "nt", reason="Codex App Server Agent excludes native Windows")
def test_timed_out_codex_probe_reclaims_the_launcher_process_group(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    launcher = (
        "import pathlib, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8'); "
        "time.sleep(30)"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        _run_codex_probe(
            [sys.executable, "-c", launcher, str(child_pid_path)],
            timeout=0.3,
        )

    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail("timed-out Codex probe left its native child running")


@pytest.mark.skipif(os.name == "nt", reason="Codex App Server Agent excludes native Windows")
def test_completed_codex_probe_reclaims_a_lingering_child(tmp_path: Path) -> None:
    child_pid_path = tmp_path / "child.pid"
    launcher = (
        "import pathlib, subprocess, sys; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')"
    )

    result = _run_codex_probe(
        [sys.executable, "-c", launcher, str(child_pid_path)],
        timeout=5,
    )

    assert result.returncode == 0
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail("completed Codex probe left its native child running")
