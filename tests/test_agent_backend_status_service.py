# -*- coding: utf-8 -*-
"""Agent backend compatibility-status contract tests.

Provider API (LiteLLM) is the only supported Chat backend; the former Codex
App Server probes were removed together with the backend itself.
"""

from __future__ import annotations

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
            "AGENT_BACKEND": "litellm",
            "LITELLM_MODEL": "deepseek/deepseek-chat",
            "DEEPSEEK_API_KEY": "draft-key",
        }
    ).get_status()

    assert payload["backend"] == "litellm"
    assert payload["available"] is True


def test_removed_agent_backend_is_rejected_without_probe() -> None:
    payload = AgentBackendStatusService(
        effective_map={"AGENT_BACKEND": "codex_app_server", "AGENT_ARCH": "single"}
    ).get_status()

    assert payload["available"] is False
    assert payload["error_code"] == "capability_unsupported"
    assert payload["experimental"] is False
    assert payload["version"] is None


def test_explicit_agent_mode_false_remains_a_kill_switch() -> None:
    payload = AgentBackendStatusService(
        effective_map={
            "AGENT_BACKEND": "auto",
            "AGENT_ARCH": "single",
            "AGENT_MODE": "false",
            "LITELLM_MODEL": "deepseek/deepseek-chat",
            "DEEPSEEK_API_KEY": "test-key-value",
        }
    ).get_status()

    assert payload["available"] is False
    assert payload["error_code"] == "agent_mode_disabled"


def test_missing_generation_source_reports_no_agent_primary() -> None:
    payload = AgentBackendStatusService(effective_map={"AGENT_BACKEND": "auto"}).get_status()

    assert payload["backend"] == "litellm"
    assert payload["available"] is False
    assert payload["error_code"] == "capability_unsupported"
    assert payload["message"] == "no_agent_primary"


@pytest.mark.parametrize("removed_backend", ["codex_app_server"])
def test_removed_backend_ids_never_resolve_to_litellm(removed_backend: str) -> None:
    payload = AgentBackendStatusService(
        effective_map={"AGENT_BACKEND": removed_backend}
    ).get_status()

    assert payload["backend"] == removed_backend
    assert payload["available"] is False
