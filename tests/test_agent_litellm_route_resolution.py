# -*- coding: utf-8 -*-
"""Tests for Agent-safe LiteLLM route resolution."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.llm_adapter import LLMToolAdapter
from src.agent.litellm_route_resolution import resolve_agent_litellm_route
from src.llm.backend_registry import LOCAL_CLI_GENERATION_BACKEND_IDS

LOCAL_CLI_BACKENDS = sorted(LOCAL_CLI_GENERATION_BACKEND_IDS)


def _config(**overrides):
    base = {
        "agent_generation_backend": "auto",
        "generation_backend": "litellm",
        "agent_litellm_model": "",
        "litellm_model": "",
        "litellm_fallback_models": [],
        "llm_model_list": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _hermes_deployment(model_name: str):
    return {
        "model_name": model_name,
        "litellm_params": {
            "model": model_name,
            "api_key": "sk-hermes",
            "api_base": "http://127.0.0.1:8642/v1",
        },
        "model_info": {"dsa_channel": "hermes"},
    }


def _remote_deployment(model_name: str):
    return {
        "model_name": model_name,
        "litellm_params": {
            "model": "openai/gpt-4o-mini",
            "api_key": "sk-remote",
        },
    }


def test_agent_resolver_rejects_hermes_only_route() -> None:
    resolution = resolve_agent_litellm_route(
        _config(
            litellm_model="openai/hermes-agent",
            llm_model_list=[_hermes_deployment("openai/hermes-agent")],
        )
    )

    assert not resolution.available
    assert resolution.primary_model == "openai/hermes-agent"
    assert resolution.reason == "hermes_primary_not_agent_safe"
    assert resolution.models_to_try == []
    assert resolution.model_list == []


def test_agent_resolver_filters_mixed_route_but_keeps_route_alias() -> None:
    resolution = resolve_agent_litellm_route(
        _config(
            litellm_model="shared-route",
            llm_model_list=[
                _hermes_deployment("shared-route"),
                _remote_deployment("shared-route"),
            ],
        )
    )

    assert resolution.available
    assert resolution.primary_model == "shared-route"
    assert resolution.models_to_try == ["shared-route"]
    assert resolution.model_list == [_remote_deployment("shared-route")]


def test_agent_resolver_explicit_hermes_alias_is_not_reinterpreted_as_direct_openai() -> None:
    resolution = resolve_agent_litellm_route(
        _config(
            agent_litellm_model="openai/hermes-agent",
            litellm_model="openai/gpt-4o-mini",
            llm_model_list=[_hermes_deployment("openai/hermes-agent")],
        )
    )

    assert not resolution.available
    assert resolution.primary_model == "openai/hermes-agent"
    assert resolution.reason == "explicit_agent_model_no_safe_deployment"


def test_agent_resolver_reports_no_safe_models_after_filtering_fallbacks() -> None:
    resolution = resolve_agent_litellm_route(
        _config(
            litellm_model="openai/hermes-agent",
            litellm_fallback_models=["openai/hermes-fallback"],
            llm_model_list=[
                _hermes_deployment("openai/hermes-agent"),
                _hermes_deployment("openai/hermes-fallback"),
            ],
        )
    )

    assert not resolution.available
    assert resolution.primary_model == "openai/hermes-agent"
    assert resolution.reason == "hermes_primary_not_agent_safe"


def test_agent_resolver_reports_no_safe_models_when_only_fallback_is_hermes() -> None:
    with patch(
        "src.agent.litellm_route_resolution.get_effective_agent_models_to_try",
        return_value=["openai/hermes-fallback"],
    ):
        resolution = resolve_agent_litellm_route(
            _config(
                litellm_model="openai/remote-primary",
                litellm_fallback_models=["openai/hermes-fallback"],
                llm_model_list=[_hermes_deployment("openai/hermes-fallback")],
            )
        )

    assert not resolution.available
    assert resolution.primary_model == "openai/remote-primary"
    assert resolution.reason == "no_safe_agent_models"


def test_agent_resolver_drops_bare_hermes_fallback_from_non_hermes_primary() -> None:
    resolution = resolve_agent_litellm_route(
        _config(
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=["hermes-agent"],
            llm_model_list=[
                _remote_deployment("openai/gpt-4o-mini"),
                _hermes_deployment("openai/hermes-agent"),
            ],
        )
    )

    assert resolution.available
    assert resolution.models_to_try == ["openai/gpt-4o-mini"]
    assert resolution.model_list == [_remote_deployment("openai/gpt-4o-mini")]


def test_agent_resolver_keeps_bare_mixed_fallback_as_canonical_safe_route() -> None:
    resolution = resolve_agent_litellm_route(
        _config(
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=["shared-route"],
            llm_model_list=[
                _remote_deployment("openai/gpt-4o-mini"),
                _hermes_deployment("openai/shared-route"),
                _remote_deployment("openai/shared-route"),
            ],
        )
    )

    assert resolution.available
    assert resolution.models_to_try == ["openai/gpt-4o-mini", "openai/shared-route"]
    assert resolution.model_list == [
        _remote_deployment("openai/gpt-4o-mini"),
        _remote_deployment("openai/shared-route"),
    ]


def test_agent_resolver_preserves_direct_model_without_preflight_credentials() -> None:
    resolution = resolve_agent_litellm_route(
        _config(
            agent_litellm_model="gpt-4o-mini",
            litellm_model="gemini/gemini-2.5-flash",
            litellm_fallback_models=["anthropic/claude-3-5-sonnet-20241022"],
        )
    )

    assert resolution.available
    assert resolution.models_to_try == [
        "openai/gpt-4o-mini",
        "anthropic/claude-3-5-sonnet-20241022",
    ]


@pytest.mark.parametrize("generation_backend", LOCAL_CLI_BACKENDS)
def test_agent_auto_ignores_local_generation_backend_when_litellm_route_exists(
    generation_backend: str,
) -> None:
    config = _config(
        generation_backend=generation_backend,
        agent_generation_backend="auto",
        litellm_model="cohere/command-r-plus",
    )

    resolution = resolve_agent_litellm_route(config)

    assert resolution.available
    assert resolution.primary_model == "cohere/command-r-plus"
    assert resolution.reason == ""


@pytest.mark.parametrize("agent_backend", LOCAL_CLI_BACKENDS)
def test_agent_explicit_local_cli_backend_remains_unsupported(agent_backend: str) -> None:
    resolution = resolve_agent_litellm_route(
        _config(
            generation_backend="litellm",
            agent_generation_backend=agent_backend,
            litellm_model="cohere/command-r-plus",
        )
    )

    assert not resolution.available
    assert resolution.reason == "unsupported_agent_backend"


@pytest.mark.parametrize("generation_backend", LOCAL_CLI_BACKENDS)
def test_llm_tool_adapter_available_for_agent_auto_with_local_generation_backend(
    generation_backend: str,
) -> None:
    adapter = LLMToolAdapter(
        _config(
            generation_backend=generation_backend,
            agent_generation_backend="auto",
            litellm_model="cohere/command-r-plus",
        )
    )

    assert adapter.is_available is True
    assert adapter._litellm_available is True
    assert adapter._backend_error is None


def test_llm_tool_adapter_unavailable_when_channel_deployments_filter_to_empty() -> None:
    config = _config(
        litellm_model="openai/remote-primary",
        litellm_fallback_models=["openai/hermes-fallback"],
        llm_model_list=[_hermes_deployment("openai/hermes-fallback")],
    )

    with patch(
        "src.agent.litellm_route_resolution.get_effective_agent_models_to_try",
        return_value=["openai/remote-primary"],
    ):
        adapter = LLMToolAdapter(config)

    assert adapter.is_available is False
    assert adapter._litellm_available is False
    assert adapter._backend_error is not None
    assert adapter._backend_error.details["reason"] == "no_safe_agent_models"


def test_llm_tool_adapter_does_not_direct_call_dropped_bare_hermes_fallback() -> None:
    config = _config(
        litellm_model="openai/gpt-4o-mini",
        litellm_fallback_models=["hermes-agent"],
        llm_model_list=[
            _remote_deployment("openai/gpt-4o-mini"),
            _hermes_deployment("openai/hermes-agent"),
        ],
    )
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    adapter._config = config
    adapter._backend_error = None
    adapter._route_resolution = resolve_agent_litellm_route(config)

    with patch.object(
        adapter,
        "_call_litellm_model",
        side_effect=RuntimeError("primary failed"),
    ) as call_model:
        response = adapter.call_completion([{"role": "user", "content": "hello"}])

    assert response.provider == "error"
    assert [call.args[2] for call in call_model.call_args_list] == ["openai/gpt-4o-mini"]


def test_call_completion_does_not_overwrite_adapter_route_resolution() -> None:
    config = _config(litellm_model="openai/test-model")
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    adapter._config = config
    adapter._backend_error = None
    adapter._route_resolution = resolve_agent_litellm_route(config)

    original_resolution = adapter._route_resolution
    dynamic_resolution = type(original_resolution)(
        available=False,
        primary_model="openai/test-model",
        models_to_try=[],
        model_list=[],
        reason="no_safe_agent_models",
    )

    with patch("src.agent.llm_adapter.resolve_agent_litellm_route", return_value=dynamic_resolution):
        response = adapter.call_completion([{"role": "user", "content": "hello"}])

    assert response.provider == "error"
    assert adapter._route_resolution is original_resolution
