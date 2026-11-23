# -*- coding: utf-8 -*-
"""Lightweight Agent status, legacy values and default routing."""
import subprocess
import pytest
from src.services.agent_backend_status_service import AgentBackendStatusService


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



@pytest.mark.parametrize("value,code", [("codex_app_server", "backend_removed"), ("unknown", "capability_unsupported")])
@pytest.mark.parametrize("arch", ["single", "multi"])
def test_unsupported_status_never_starts_subprocess(monkeypatch, value, code, arch):
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("status must not launch a process"))
    status = AgentBackendStatusService(effective_map={"AGENT_BACKEND": value, "AGENT_ARCH": arch}).get_status()
    assert status["backend"] == value and status["available"] is False
    assert status["error_code"] == code and status["experimental"] is False
    assert status["version"] is None
    if code == "backend_removed":
        assert "已移除" in status["message"]


def test_explicit_agent_mode_false_remains_a_kill_switch():
    status = AgentBackendStatusService(effective_map={"AGENT_BACKEND": "auto", "AGENT_MODE": "false"}).get_status()
    assert status["error_code"] == "agent_mode_disabled"


def test_missing_litellm_primary_is_still_unavailable():
    status = AgentBackendStatusService(effective_map={"AGENT_BACKEND": "litellm"}).get_status()
    assert status["error_code"] == "capability_unsupported"
    assert status["message"] == "no_agent_primary"
