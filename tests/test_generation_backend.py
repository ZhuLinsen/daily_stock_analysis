# -*- coding: utf-8 -*-
"""Tests for generation backend contracts and backend resolver semantics."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.llm.backend_registry import (  # noqa: E402
    AGENT_CAPABLE_BACKEND_IDS,
    GENERATION_ONLY_BACKEND_IDS,
    LITELLM_BACKEND_ID,
    LOCAL_CLI_GENERATION_BACKEND_IDS,
    resolve_agent_generation_backend_id,
    resolve_generation_backend_id,
    resolve_generation_fallback_backend_id,
)
from src.llm.backend_factory import create_generation_backend  # noqa: E402
from src.llm.generation_backend import (  # noqa: E402
    GenerationCapabilities,
    GenerationError,
    GenerationErrorCode,
    GenerationResult,
)
from src.llm.litellm_backend import LiteLLMGenerationBackend  # noqa: E402
from src.llm.local_cli_backend import LocalCliGenerationBackend  # noqa: E402


def _config(**overrides):
    defaults = {
        "generation_backend": "litellm",
        "generation_fallback_backend": "litellm",
        "agent_generation_backend": "auto",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_generation_result_and_capabilities_fields_are_public_contract() -> None:
    result = GenerationResult(
        text="response",
        model="gemini/gemini-3.1-pro-preview",
        provider="gemini",
        backend="litellm",
        usage={"total_tokens": 3},
        raw={"id": "raw"},
        diagnostics={"route": "direct"},
    )
    capabilities = GenerationCapabilities(
        supports_json=True,
        supports_tools=True,
        supports_stream=True,
        supports_vision=False,
        supports_health_check=False,
        supports_smoke_test=False,
    )

    assert result.text == "response"
    assert result.model == "gemini/gemini-3.1-pro-preview"
    assert result.provider == "gemini"
    assert result.backend == "litellm"
    assert result.usage == {"total_tokens": 3}
    assert result.raw == {"id": "raw"}
    assert result.diagnostics == {"route": "direct"}
    assert capabilities.supports_json is True
    assert capabilities.supports_tools is True
    assert capabilities.supports_stream is True
    assert capabilities.supports_vision is False
    assert capabilities.supports_health_check is False
    assert capabilities.supports_smoke_test is False


def test_generation_error_codes_include_phase2_values() -> None:
    assert {code.value for code in GenerationErrorCode} == {
        "backend_not_configured",
        "command_not_found",
        "command_not_executable",
        "timeout",
        "non_zero_exit",
        "empty_output",
        "output_too_large",
        "invalid_json",
        "schema_validation_failed",
        "unsupported_tool_calling",
        "interactive_prompt_required",
        "approval_required",
        "login_required",
        "capability_unsupported",
        "unsafe_config",
        "unknown_backend_error",
    }


def test_generation_error_stage_uses_descriptive_string_contract() -> None:
    error = GenerationError(
        error_code=GenerationErrorCode.INVALID_JSON,
        stage="generation",
        retryable=True,
        fallbackable=True,
        backend="litellm",
        provider="gemini",
        details={"allowed_stages": ["generation", "configuration", "execution", "validation", "fallback"]},
    )

    assert str(error) == "invalid_json at generation for backend litellm"
    assert error.stage in {"generation", "configuration", "execution", "validation", "fallback"}
    assert error.provider == "gemini"
    assert error.details["allowed_stages"] == [
        "generation",
        "configuration",
        "execution",
        "validation",
        "fallback",
    ]


def test_litellm_backend_capabilities_and_result_normalization() -> None:
    received = {}

    def completion(prompt, generation_config, **kwargs):
        received["prompt"] = prompt
        received["generation_config"] = generation_config
        received["kwargs"] = kwargs
        return "ok", "gemini/gemini-3.1-pro-preview", {
            "provider": "gemini",
            "total_tokens": 7,
        }

    backend = LiteLLMGenerationBackend(completion)
    result = backend.generate(
        "prompt",
        {"max_tokens": 128},
        system_prompt="system",
        stream=True,
        stream_progress_callback=lambda _chars: None,
        response_validator=lambda text: None,
        audit_context={"call_type": "analysis"},
    )

    assert backend.backend_id == "litellm"
    assert backend.capabilities.supports_json is True
    assert backend.capabilities.supports_tools is True
    assert backend.capabilities.supports_stream is True
    assert backend.capabilities.supports_vision is False
    assert backend.capabilities.supports_health_check is False
    assert backend.capabilities.supports_smoke_test is False
    assert result == GenerationResult(
        text="ok",
        model="gemini/gemini-3.1-pro-preview",
        provider="gemini",
        backend="litellm",
        usage={"provider": "gemini", "total_tokens": 7},
    )
    assert received["prompt"] == "prompt"
    assert received["generation_config"] == {"max_tokens": 128}
    assert received["kwargs"]["system_prompt"] == "system"
    assert received["kwargs"]["stream"] is True
    assert callable(received["kwargs"]["stream_progress_callback"])
    assert callable(received["kwargs"]["response_validator"])
    assert received["kwargs"]["audit_context"] == {"call_type": "analysis"}


def test_litellm_backend_derives_provider_from_model_when_usage_is_empty() -> None:
    backend = LiteLLMGenerationBackend(
        lambda _prompt, _generation_config, **_kwargs: (
            "ok",
            "anthropic/claude-sonnet-4-6",
            {},
        )
    )

    result = backend.generate("prompt", {})

    assert result.provider == "anthropic"
    assert result.backend == LITELLM_BACKEND_ID
    assert result.usage == {}


def test_generation_backend_factory_dispatches_litellm_and_local_cli_backends() -> None:
    litellm_backend = create_generation_backend(
        "litellm",
        config=_config(),
        litellm_completion_callable=lambda _prompt, _cfg, **_kwargs: ("ok", "openai/gpt", {}),
    )

    assert isinstance(litellm_backend, LiteLLMGenerationBackend)
    for backend_id in sorted(LOCAL_CLI_GENERATION_BACKEND_IDS):
        local_backend = create_generation_backend(
            backend_id,
            config=_config(generation_backend=backend_id),
        )
        assert isinstance(local_backend, LocalCliGenerationBackend)
        assert local_backend.preset_id == backend_id


def test_resolvers_default_to_litellm_and_self_fallback_is_noop() -> None:
    config = _config(
        generation_backend="",
        generation_fallback_backend="",
        agent_generation_backend="",
    )

    assert resolve_generation_backend_id(config) == "litellm"
    assert resolve_generation_fallback_backend_id(config) is None
    assert resolve_agent_generation_backend_id(config) == "litellm"


def test_resolvers_treat_missing_mock_fields_as_defaults_without_hiding_strings() -> None:
    config = MagicMock()

    assert resolve_generation_backend_id(config) == "litellm"
    assert resolve_generation_fallback_backend_id(config) is None
    assert resolve_agent_generation_backend_id(config) == "litellm"

    config.generation_backend = "codex"
    with pytest.raises(GenerationError) as exc_info:
        resolve_generation_backend_id(config)

    assert exc_info.value.details["requested_backend"] == "codex"


def test_explicit_litellm_resolves_for_analysis_and_agent() -> None:
    config = _config(
        generation_backend="litellm",
        generation_fallback_backend="litellm",
        agent_generation_backend="litellm",
    )

    assert resolve_generation_backend_id(config) == "litellm"
    assert resolve_generation_fallback_backend_id(config) is None
    assert resolve_agent_generation_backend_id(config) == "litellm"


@pytest.mark.parametrize("generation_backend", sorted(LOCAL_CLI_GENERATION_BACKEND_IDS))
def test_agent_auto_does_not_inherit_local_generation_backend(generation_backend: str) -> None:
    config = _config(generation_backend=generation_backend, agent_generation_backend="auto")

    assert resolve_generation_backend_id(config) == generation_backend
    assert resolve_agent_generation_backend_id(config) == "litellm"


def test_unknown_generation_backend_raises_structured_config_error() -> None:
    with pytest.raises(GenerationError) as exc_info:
        resolve_generation_backend_id(_config(generation_backend="codex"))

    error = exc_info.value
    assert error.error_code is GenerationErrorCode.BACKEND_NOT_CONFIGURED
    assert error.stage == "generation"
    assert error.retryable is False
    assert error.fallbackable is False
    assert error.backend == "codex"
    assert error.details["field"] == "GENERATION_BACKEND"
    assert error.details["requested_backend"] == "codex"
    assert error.details["supported_backends"] == [
        "claude_code_cli",
        "codex_cli",
        "litellm",
        "opencode_cli",
    ]


def test_codex_cli_generation_backend_can_fallback_to_litellm() -> None:
    config = _config(generation_backend="codex_cli", generation_fallback_backend="litellm")

    assert resolve_generation_backend_id(config) == "codex_cli"
    assert resolve_generation_fallback_backend_id(config) == "litellm"


def test_claude_code_cli_is_supported_generation_backend() -> None:
    config = _config(generation_backend="claude_code_cli", generation_fallback_backend="litellm")

    assert resolve_generation_backend_id(config) == "claude_code_cli"
    assert resolve_generation_fallback_backend_id(config) == "litellm"


def test_opencode_cli_is_supported_generation_backend() -> None:
    config = _config(generation_backend="opencode_cli", generation_fallback_backend="litellm")

    assert resolve_generation_backend_id(config) == "opencode_cli"
    assert resolve_generation_fallback_backend_id(config) == "litellm"


def test_empty_generation_fallback_disables_backend_fallback() -> None:
    config = _config(generation_backend="codex_cli", generation_fallback_backend="")

    assert resolve_generation_fallback_backend_id(config) is None


def test_codex_cli_is_not_listed_as_supported_generation_fallback() -> None:
    with pytest.raises(GenerationError) as exc_info:
        resolve_generation_fallback_backend_id(
            _config(generation_backend="litellm", generation_fallback_backend="codex_cli")
        )

    error = exc_info.value
    assert error.details["field"] == "GENERATION_FALLBACK_BACKEND"
    assert error.details["requested_backend"] == "codex_cli"
    assert error.details["supported_backends"] == ["litellm"]


def test_unknown_agent_backend_raises_structured_config_error() -> None:
    with pytest.raises(GenerationError) as exc_info:
        resolve_agent_generation_backend_id(_config(agent_generation_backend="opencode"))

    error = exc_info.value
    assert error.error_code is GenerationErrorCode.BACKEND_NOT_CONFIGURED
    assert error.details["field"] == "AGENT_GENERATION_BACKEND"
    assert error.details["requested_backend"] == "opencode"
    assert error.details["supported_backends"] == [
        "auto",
        "claude_code_cli",
        "codex_cli",
        "litellm",
        "opencode_cli",
    ]


def test_generation_only_backends_are_not_agent_capable() -> None:
    assert GENERATION_ONLY_BACKEND_IDS.isdisjoint(AGENT_CAPABLE_BACKEND_IDS)


def test_explicit_local_agent_backends_resolve_to_unsupported_ids() -> None:
    for backend_id in sorted(GENERATION_ONLY_BACKEND_IDS):
        assert resolve_agent_generation_backend_id(
            _config(agent_generation_backend=backend_id)
        ) == backend_id


@pytest.mark.parametrize("agent_backend", sorted(GENERATION_ONLY_BACKEND_IDS))
def test_llm_tool_adapter_local_agent_backend_is_not_silent_litellm_fallback(
    agent_backend: str,
) -> None:
    from src.agent.llm_adapter import LLMToolAdapter

    with patch("src.agent.llm_adapter.litellm.register_model", create=True):
        adapter = LLMToolAdapter(_config(agent_generation_backend=agent_backend))

    assert adapter.is_available is False
    response = adapter.call_completion([])
    assert response.provider == "error"
    assert "unsupported_tool_calling" in (response.content or "")
    assert agent_backend in (response.content or "")


@pytest.mark.parametrize("generation_backend", sorted(LOCAL_CLI_GENERATION_BACKEND_IDS))
def test_agent_auto_with_local_generation_backend_returns_unsupported_when_litellm_missing(
    generation_backend: str,
) -> None:
    from src.agent.llm_adapter import LLMToolAdapter

    config = _config(
        generation_backend=generation_backend,
        agent_generation_backend="auto",
        litellm_model="",
        agent_litellm_model="",
        litellm_fallback_models=[],
        llm_model_list=[],
    )

    with patch("src.agent.llm_adapter.litellm.register_model", create=True):
        adapter = LLMToolAdapter(config)

    assert adapter.is_available is False
    response = adapter.call_completion([], tools=[{"type": "function"}])
    assert response.provider == "error"
    assert "unsupported_tool_calling" in (response.content or "")
    assert generation_backend in (response.content or "")
