# -*- coding: utf-8 -*-
"""Tests for generation backend status diagnostics."""

import logging
from unittest.mock import patch
from types import SimpleNamespace

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.llm.generation_backend import GenerationError, GenerationErrorCode
from src.services.generation_backend_status_service import GenerationBackendStatusService


class _FailingBackend:
    def generate(self, *_args, **_kwargs):
        raise GenerationError(
            error_code=GenerationErrorCode.INVALID_JSON,
            stage="smoke_validation",
            retryable=False,
            fallbackable=False,
            backend="codex_cli",
            details={"reason": "invalid_json"},
        )


class _FakeAnalyzer:
    def __init__(self, _config):
        pass

    def _get_generation_backend(self, _backend_id):
        return _FailingBackend()


class _PassingBackend:
    seen_configs = []

    def __init__(self, config=None):
        self.config = config

    def generate(self, *_args, **kwargs):
        validator = kwargs.get("response_validator")
        text = '{"ok": true, "backend_smoke": "passed"}'
        if validator:
            validator(text)
        return SimpleNamespace(text=text)


class _CapturingAnalyzer:
    configs = []

    def __init__(self, config):
        self.configs.append(config)
        self.config = config

    def _get_generation_backend(self, _backend_id):
        return _PassingBackend(self.config)


def _litellm_effective_map(api_key: str = "sk-secret-value") -> dict:
    return {
        "GENERATION_BACKEND": "litellm",
        "GENERATION_FALLBACK_BACKEND": "",
        "LITELLM_MODEL": "openai/gpt-5.5",
        "OPENAI_API_KEY": api_key,
    }


def test_local_cli_missing_executable_reports_current_config_error() -> None:
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "codex_cli",
            "GENERATION_FALLBACK_BACKEND": "",
        }
    )

    with patch("src.llm.local_cli_backend.shutil.which", return_value=None):
        payload = service.get_status()

    primary = payload["primary"]
    assert primary["backend_id"] == "codex_cli"
    assert primary["available"] is False
    assert primary["health_status"] == "failed"
    assert primary["last_error_code"] == "command_not_found"
    assert primary["supports_tools"] is False


def test_local_cli_invalid_numeric_config_reports_unsafe_config() -> None:
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "codex_cli",
            "GENERATION_FALLBACK_BACKEND": "",
            "GENERATION_BACKEND_TIMEOUT_SECONDS": "not-int",
        }
    )

    payload = service.get_status()

    primary = payload["primary"]
    assert primary["available"] is False
    assert primary["health_status"] == "failed"
    assert primary["last_error_code"] == "unsafe_config"


def test_litellm_ignores_local_cli_only_numeric_config() -> None:
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "litellm",
            "LITELLM_MODEL": "gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY": "secret-key-value",
            "GENERATION_BACKEND_TIMEOUT_SECONDS": "not-int",
            "GENERATION_BACKEND_MAX_OUTPUT_BYTES": "not-int",
            "LOCAL_CLI_BACKEND_MAX_CONCURRENCY": "not-int",
        }
    )

    payload = service.get_status()

    assert payload["primary"]["available"] is True
    assert payload["primary"]["last_error_code"] is None


def test_local_cli_smoke_failure_keeps_available_true_when_cheap_check_passes() -> None:
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "codex_cli",
            "GENERATION_FALLBACK_BACKEND": "",
        },
        analyzer_factory=lambda config: _FakeAnalyzer(config),
    )

    with patch("src.llm.local_cli_backend.shutil.which", return_value="/usr/bin/codex"), \
         patch("src.llm.local_cli_backend.os.access", return_value=True):
        payload = service.smoke_test(backend_id="codex_cli", mode="json")

    status = payload["status"]
    assert payload["success"] is False
    assert status["available"] is True
    assert status["health_status"] == "failed"
    assert status["last_error_code"] == "invalid_json"
    assert status["supports_tools"] is False


def test_smoke_timeout_overrides_config_timeout_for_local_cli() -> None:
    _CapturingAnalyzer.configs = []
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "codex_cli",
            "GENERATION_FALLBACK_BACKEND": "",
            "GENERATION_BACKEND_TIMEOUT_SECONDS": "300",
        },
        analyzer_factory=lambda config: _CapturingAnalyzer(config),
    )

    with patch("src.llm.local_cli_backend.shutil.which", return_value="/usr/bin/codex"), \
         patch("src.llm.local_cli_backend.os.access", return_value=True):
        payload = service.smoke_test(backend_id="codex_cli", mode="json", timeout_seconds=1)

    assert payload["success"] is True
    assert _CapturingAnalyzer.configs[-1].generation_backend_timeout_seconds == 1


def test_litellm_smoke_timeout_reaches_final_completion_dispatch() -> None:
    captured = {}

    def _dispatch(_self, _model, call_kwargs, *, config, use_channel_router, router_model_names):
        del config, use_channel_router, router_model_names
        captured.update(call_kwargs)
        return {
            "choices": [
                {"message": {"content": '{"ok": true, "backend_smoke": "passed"}'}}
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    service = GenerationBackendStatusService(effective_map=_litellm_effective_map())

    with patch("src.analyzer.GeminiAnalyzer._dispatch_litellm_completion", new=_dispatch):
        payload = service.smoke_test(mode="json", timeout_seconds=1)

    assert payload["success"] is True
    assert captured["timeout"] == 1


def test_litellm_smoke_redacts_provider_error_from_response_and_logs(caplog) -> None:
    secret_error = (
        "provider rejected invalid api key plain-provider-secret-value and sk-secret-value "
        "Authorization: Bearer sk-review-token-abcdef"
    )

    def _dispatch(_self, _model, _call_kwargs, *, config, use_channel_router, router_model_names):
        del config, use_channel_router, router_model_names
        raise RuntimeError(secret_error)

    service = GenerationBackendStatusService(
        effective_map=_litellm_effective_map("plain-provider-secret-value")
    )
    caplog.set_level(logging.WARNING, logger="src.analyzer")

    with patch("src.analyzer.GeminiAnalyzer._dispatch_litellm_completion", new=_dispatch):
        payload = service.smoke_test(mode="json")

    assert payload["success"] is False
    visible_text = f"{payload['message']} {payload['status']['last_error_message']}"
    logged_text = "\n".join(record.getMessage() for record in caplog.records)
    for text in (visible_text, logged_text):
        assert "plain-provider-secret-value" not in text
        assert "sk-secret-value" not in text
        assert "sk-review-token-abcdef" not in text
        assert "Authorization: Bearer" not in text
    assert "[REDACTED]" in payload["message"] or "<redacted" in payload["message"]


def test_generation_fallback_self_is_noop_not_recursive() -> None:
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "codex_cli",
            "GENERATION_FALLBACK_BACKEND": "codex_cli",
        }
    )

    with patch("src.llm.local_cli_backend.shutil.which", return_value="/usr/bin/codex"), \
         patch("src.llm.local_cli_backend.os.access", return_value=True):
        payload = service.get_status()

    assert payload["primary_backend_id"] == "codex_cli"
    assert payload["fallback_backend_id"] is None
    assert payload["fallback"] is None
    assert len(payload["backends"]) == 1


def test_invalid_fallback_does_not_fail_primary() -> None:
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "codex_cli",
            "GENERATION_FALLBACK_BACKEND": "bad_backend",
        }
    )

    with patch("src.llm.local_cli_backend.shutil.which", return_value="/usr/bin/codex"), \
         patch("src.llm.local_cli_backend.os.access", return_value=True):
        payload = service.get_status()

    assert payload["primary"]["available"] is True
    assert payload["primary"]["health_status"] == "not_tested"
    assert payload["fallback"]["backend_id"] == "bad_backend"
    assert payload["fallback"]["available"] is False
    assert payload["fallback"]["health_status"] == "failed"


def test_litellm_without_model_source_is_not_available() -> None:
    service = GenerationBackendStatusService(effective_map={"GENERATION_BACKEND": "litellm"})

    payload = service.get_status()

    assert payload["primary"]["available"] is False
    assert payload["primary"]["health_status"] == "failed"
    assert payload["primary"]["last_error_code"] == "backend_not_configured"


def test_litellm_managed_model_without_provider_key_is_not_available() -> None:
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "litellm",
            "LITELLM_MODEL": "gemini/gemini-3-flash-preview",
        }
    )

    payload = service.get_status()

    assert payload["primary"]["available"] is False
    assert payload["primary"]["health_status"] == "failed"
    assert payload["primary"]["last_error_code"] == "unsafe_config"


def test_litellm_aihubmix_key_builds_openai_legacy_route() -> None:
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "litellm",
            "LITELLM_MODEL": "openai/gpt-5.5",
            "AIHUBMIX_KEY": "sk-aihubmix-secret",
        }
    )

    payload = service.get_status()

    assert payload["primary"]["available"] is True
    assert payload["primary"]["last_error_code"] is None


def test_litellm_legacy_key_infers_runtime_model_for_smoke_config() -> None:
    _CapturingAnalyzer.configs = []
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "litellm",
            "GEMINI_API_KEY": "secret-key-value",
        },
        analyzer_factory=lambda config: _CapturingAnalyzer(config),
    )

    payload = service.smoke_test(mode="json")

    assert payload["success"] is True
    assert _CapturingAnalyzer.configs[-1].litellm_model == "gemini/gemini-3.1-pro-preview"


def test_litellm_validation_issues_are_not_available() -> None:
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "litellm",
            "LLM_CHANNELS": "remote",
            "LLM_REMOTE_PROTOCOL": "openai",
            "LLM_REMOTE_BASE_URL": "https://api.example.com/v1",
            "LLM_REMOTE_API_KEY": "sk-remote",
            "LLM_REMOTE_MODELS": "gpt-4o-mini",
        },
        validation_issues=[
            {
                "key": "LITELLM_MODEL",
                "code": "unknown_model",
                "message": "unknown model",
                "severity": "error",
            }
        ],
    )

    payload = service.get_status()

    assert payload["primary"]["available"] is False
    assert payload["primary"]["health_status"] == "failed"
    assert payload["primary"]["last_error_code"] == "unsafe_config"


def test_smoke_invalid_saved_backend_returns_structured_failure() -> None:
    service = GenerationBackendStatusService(effective_map={"GENERATION_BACKEND": "bad_backend"})

    payload = service.smoke_test()

    assert payload["success"] is False
    assert payload["mode"] == "json"
    assert payload["status"]["backend_id"] == "bad_backend"
    assert payload["status"]["health_status"] == "failed"
    assert payload["status"]["last_error_code"] == "backend_not_configured"


def test_smoke_unsupported_requested_backend_returns_structured_failure() -> None:
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "litellm",
            "LITELLM_MODEL": "gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY": "secret-key-value",
        }
    )

    payload = service.smoke_test(backend_id="bad_backend")

    assert payload["success"] is False
    assert payload["mode"] == "json"
    assert payload["status"]["backend_id"] == "bad_backend"
    assert payload["status"]["is_primary"] is False
    assert payload["status"]["last_error_code"] == "backend_not_configured"


def test_litellm_channel_route_is_used_for_status_and_smoke_config() -> None:
    _CapturingAnalyzer.configs = []
    service = GenerationBackendStatusService(
        effective_map={
            "GENERATION_BACKEND": "litellm",
            "LLM_CHANNELS": "remote",
            "LLM_REMOTE_PROTOCOL": "openai",
            "LLM_REMOTE_BASE_URL": "https://api.example.com/v1",
            "LLM_REMOTE_API_KEY": "sk-remote",
            "LLM_REMOTE_MODELS": "gpt-4o-mini",
        },
        analyzer_factory=lambda config: _CapturingAnalyzer(config),
    )

    status = service.get_status()
    smoke = service.smoke_test(mode="json")

    assert status["primary"]["available"] is True
    assert smoke["success"] is True
    config = _CapturingAnalyzer.configs[-1]
    assert config.litellm_model == "openai/gpt-4o-mini"
    assert config.llm_model_list[0]["model_name"] == "openai/gpt-4o-mini"
    assert config.llm_model_list[0]["litellm_params"]["api_key"] == "sk-remote"
    assert config.llm_model_list[0]["litellm_params"]["api_base"] == "https://api.example.com/v1"
