# -*- coding: utf-8 -*-
"""Tests for LiteLLM generation-parameter recovery."""

from src.llm.errors import (
    call_litellm_with_param_recovery,
    classify_litellm_generation_param_error,
)
from src.llm.generation_params import (
    apply_litellm_generation_params,
    clear_litellm_generation_param_recovery_cache,
)


def test_temperature_default_only_error_sets_temperature_to_one() -> None:
    recovery = classify_litellm_generation_param_error(
        RuntimeError(
            "Unsupported value: 'temperature' does not support 0.7 with this model. "
            "Only the default (1.0) value is supported."
        )
    )

    assert recovery is not None
    assert recovery.set_params == {"temperature": 1.0}
    assert recovery.omit_params == ()


def test_temperature_default_only_error_uses_named_default_value() -> None:
    recovery = classify_litellm_generation_param_error(
        RuntimeError(
            "Unsupported value: 'temperature' does not support 1.0 with this model. "
            "Only `0.6` is allowed."
        )
    )

    assert recovery is not None
    assert recovery.set_params == {"temperature": 0.6}
    assert recovery.omit_params == ()


def test_temperature_default_only_error_without_named_value_omits_temperature() -> None:
    recovery = classify_litellm_generation_param_error(
        RuntimeError(
            "Unsupported value: 'temperature' does not support 0.7 with this model. "
            "Only the default value is supported."
        )
    )

    assert recovery is not None
    assert recovery.set_params == {}
    assert recovery.omit_params == ("temperature",)


def test_unsupported_temperature_error_retries_once_and_caches_recovery() -> None:
    clear_litellm_generation_param_recovery_cache()
    calls = []

    def _call(kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise RuntimeError("Unsupported parameter: temperature is not supported")
        return "ok"

    result = call_litellm_with_param_recovery(
        _call,
        model="openai/custom-temp-locked",
        call_kwargs={
            "model": "openai/custom-temp-locked",
            "messages": [],
            "temperature": 0.7,
        },
    )
    future_kwargs = apply_litellm_generation_params(
        {"model": "openai/custom-temp-locked", "messages": []},
        "openai/custom-temp-locked",
        0.7,
    )

    assert result == "ok"
    assert calls[0]["temperature"] == 0.7
    assert "temperature" not in calls[1]
    assert "temperature" not in future_kwargs


def test_recovery_cache_is_scoped_to_api_base() -> None:
    clear_litellm_generation_param_recovery_cache()
    calls = []

    def _call(kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise RuntimeError("Unsupported parameter: temperature is not supported")
        return "ok"

    result = call_litellm_with_param_recovery(
        _call,
        model="openai/shared-model",
        call_kwargs={
            "model": "openai/shared-model",
            "messages": [],
            "api_base": "https://strict.example/v1",
            "temperature": 0.7,
        },
    )
    strict_kwargs = apply_litellm_generation_params(
        {"model": "openai/shared-model", "messages": [], "api_base": "https://strict.example/v1"},
        "openai/shared-model",
        0.7,
    )
    flexible_kwargs = apply_litellm_generation_params(
        {"model": "openai/shared-model", "messages": [], "api_base": "https://flex.example/v1"},
        "openai/shared-model",
        0.7,
    )

    assert result == "ok"
    assert "temperature" not in strict_kwargs
    assert flexible_kwargs["temperature"] == 0.7


def test_recovery_cache_skips_ambiguous_router_endpoints() -> None:
    clear_litellm_generation_param_recovery_cache()
    model_list = [
        {
            "model_name": "openai/shared-model",
            "litellm_params": {
                "model": "openai/shared-model",
                "api_base": "https://strict.example/v1",
            },
        },
        {
            "model_name": "openai/shared-model",
            "litellm_params": {
                "model": "openai/shared-model",
                "api_base": "https://flex.example/v1",
            },
        },
    ]
    calls = []

    def _call(kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise RuntimeError("Unsupported parameter: temperature is not supported")
        return "ok"

    result = call_litellm_with_param_recovery(
        _call,
        model="openai/shared-model",
        call_kwargs={"model": "openai/shared-model", "messages": [], "temperature": 0.7},
        model_list=model_list,
    )
    future_kwargs = apply_litellm_generation_params(
        {"model": "openai/shared-model", "messages": []},
        "openai/shared-model",
        0.7,
        model_list=model_list,
    )

    assert result == "ok"
    assert future_kwargs["temperature"] == 0.7


def test_streaming_retry_does_not_cache_before_stream_is_consumed() -> None:
    clear_litellm_generation_param_recovery_cache()
    calls = []

    def _broken_stream():
        raise RuntimeError("stream failed during iteration")
        yield  # pragma: no cover

    def _call(kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise RuntimeError("Unsupported parameter: temperature is not supported")
        return _broken_stream()

    stream = call_litellm_with_param_recovery(
        _call,
        model="openai/stream-model",
        call_kwargs={
            "model": "openai/stream-model",
            "messages": [],
            "temperature": 0.7,
            "stream": True,
        },
        cache_recovery=False,
    )
    try:
        list(stream)
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("stream should fail during iteration")

    future_kwargs = apply_litellm_generation_params(
        {"model": "openai/stream-model", "messages": []},
        "openai/stream-model",
        0.7,
    )

    assert "temperature" not in calls[1]
    assert future_kwargs["temperature"] == 0.7
