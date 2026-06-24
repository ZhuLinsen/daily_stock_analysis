# -*- coding: utf-8 -*-
"""Tests for generation backend contracts and Phase 1 LiteLLM resolver."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.llm.backend_registry import (  # noqa: E402
    LITELLM_BACKEND_ID,
    resolve_agent_generation_backend_id,
    resolve_generation_backend_id,
    resolve_generation_fallback_backend_id,
)
from src.llm.generation_backend import (  # noqa: E402
    GenerationCapabilities,
    GenerationError,
    GenerationErrorCode,
    GenerationResult,
)
from src.llm.litellm_backend import LiteLLMGenerationBackend  # noqa: E402


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


def test_generation_error_codes_include_phase1_and_reserved_values() -> None:
    assert {code.value for code in GenerationErrorCode} == {
        "backend_not_configured",
        "command_not_found",
        "timeout",
        "empty_output",
        "invalid_json",
        "schema_validation_failed",
        "unsupported_tool_calling",
        "login_required",
        "capability_unsupported",
        "unsafe_config",
    }


def test_generation_error_stage_uses_descriptive_string_contract() -> None:
    error = GenerationError(
        error_code=GenerationErrorCode.INVALID_JSON,
        stage="generation",
        retryable=True,
        fallbackable=True,
        backend="litellm",
        provider="gemini",
        details={"phase1_allowed_stages": ["generation", "validation", "fallback"]},
    )

    assert str(error) == "invalid_json at generation for backend litellm"
    assert error.stage in {"generation", "validation", "fallback"}
    assert error.provider == "gemini"
    assert error.details["phase1_allowed_stages"] == [
        "generation",
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
    assert error.details["supported_backends"] == ["litellm"]


def test_generation_backend_codex_does_not_fallback_to_litellm() -> None:
    config = _config(generation_backend="codex", generation_fallback_backend="litellm")

    with pytest.raises(GenerationError) as exc_info:
        resolve_generation_fallback_backend_id(config)

    assert exc_info.value.error_code is GenerationErrorCode.BACKEND_NOT_CONFIGURED
    assert exc_info.value.details["requested_backend"] == "codex"


def test_unknown_agent_backend_raises_structured_config_error() -> None:
    with pytest.raises(GenerationError) as exc_info:
        resolve_agent_generation_backend_id(_config(agent_generation_backend="opencode"))

    error = exc_info.value
    assert error.error_code is GenerationErrorCode.BACKEND_NOT_CONFIGURED
    assert error.details["field"] == "AGENT_GENERATION_BACKEND"
    assert error.details["requested_backend"] == "opencode"
    assert error.details["supported_backends"] == ["auto", "litellm"]


def test_llm_tool_adapter_unknown_agent_backend_is_not_silent_litellm_fallback() -> None:
    from src.agent.llm_adapter import LLMToolAdapter

    with patch("src.agent.llm_adapter.litellm.register_model", create=True):
        adapter = LLMToolAdapter(_config(agent_generation_backend="codex"))

    assert adapter.is_available is False
    response = adapter.call_completion([])
    assert response.provider == "error"
    assert "backend_not_configured" in (response.content or "")
    assert "codex" in (response.content or "")
