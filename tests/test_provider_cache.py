# -*- coding: utf-8 -*-
"""Tests for provider prompt-cache capability registry and hint lowering."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.llm.provider_cache import (
    DeepSeekCaps,
    DirectiveSupport,
    ProviderCacheCaps,
    ProviderCacheRouteContext,
    RetentionPolicySupport,
    apply_prompt_cache_hints,
    build_provider_cache_route_context,
    filter_prompt_cache_telemetry,
    infer_provider_family,
    resolve_provider_cache_caps,
)
from src.llm.usage import build_domain_hmac


def _config(**kwargs):
    defaults = {
        "llm_prompt_cache_telemetry_enabled": True,
        "llm_prompt_cache_hints_enabled": False,
        "llm_prompt_cache_diagnostics_level": "off",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _verified_caps(
    provider: str,
    directive_support: DirectiveSupport,
    *,
    api_surface: str | None = None,
    gateway: str | None = None,
    model_pattern: str = "*",
) -> ProviderCacheCaps:
    return ProviderCacheCaps(
        schema_version="provider_cache_caps_v1",
        provider=provider,
        api_surface=api_surface or ("chat_completions" if provider != "anthropic" else "anthropic_messages"),
        gateway=gateway,
        cloud_platform="none",
        model_pattern=model_pattern,
        verification_status="smoke_tested",
        cache_activation="routing_hint_only" if provider == "openai" else "explicit_breakpoint",
        directive_support=directive_support,
        retention_policy_support=RetentionPolicySupport(),
        usage_paths={},
        rate_limit_semantics="unknown",
        cost_model="unknown",
        doc_sources=("https://example.test/docs",),
        last_verified_at="2026-06-20",
        deepseek_caps=DeepSeekCaps(user_id_supported=True, user_id_enabled_by_default=True)
        if provider == "deepseek"
        else None,
    )


def test_registry_returns_unknown_for_unregistered_openai_compatible_gateway():
    caps = resolve_provider_cache_caps(
        ProviderCacheRouteContext(
            model="openai/some-proxy-model",
            provider="openai_compatible",
            api_base="https://unknown-gateway.example/v1",
        )
    )

    assert caps.provider == "unknown"
    assert not caps.directive_support.prompt_cache_key


def test_registry_does_not_match_qwen_openai_compatible_route_to_dashscope_native_caps():
    route_context = build_provider_cache_route_context(model="openai/qwen-max", provider="openai_compatible")

    caps = resolve_provider_cache_caps(route_context)

    assert route_context.api_surface == "chat_completions"
    assert caps.provider == "unknown"


def test_registry_matches_dashscope_native_surface_only_for_native_route():
    caps = resolve_provider_cache_caps(
        ProviderCacheRouteContext(
            model="qwen-max",
            provider="dashscope",
            api_surface="dashscope_native",
        )
    )

    assert caps.provider == "dashscope"
    assert caps.api_surface == "dashscope_native"


def test_registry_rejects_openrouter_when_gateway_context_is_missing():
    caps = resolve_provider_cache_caps(
        ProviderCacheRouteContext(
            model="openai/~anthropic/claude-sonnet",
            provider="openrouter",
            api_surface="openrouter_chat_completions",
            gateway=None,
        )
    )

    assert caps.provider == "unknown"


def test_registry_honors_exact_and_prefix_model_patterns():
    prefix_caps = _verified_caps(
        "openai",
        DirectiveSupport(prompt_cache_key=True),
        model_pattern="openai/gpt-4*",
    )

    with patch("src.llm.provider_cache.PROVIDER_CACHE_REGISTRY", (prefix_caps,)):
        matched = resolve_provider_cache_caps(
            ProviderCacheRouteContext(
                model="openai/gpt-4o",
                provider="openai",
                api_surface="chat_completions",
            )
        )
        rejected = resolve_provider_cache_caps(
            ProviderCacheRouteContext(
                model="openai/o3",
                provider="openai",
                api_surface="chat_completions",
            )
        )

    assert matched.provider == "openai"
    assert rejected.provider == "unknown"


def test_provider_family_resolver_preserves_wrapped_openai_compatible_families():
    assert infer_provider_family(model="openai/qwen-max") == "qwen"
    assert infer_provider_family(model="openai/kimi-k2") == "kimi"
    assert infer_provider_family(model="openai/moonshot-v1-128k") == "moonshot"
    assert infer_provider_family(model="openai/minimax-text-01") == "minimax"
    assert infer_provider_family(model="openai/~anthropic/claude-sonnet") == "openrouter"


def test_provider_family_resolver_does_not_infer_family_from_unknown_api_base_substrings():
    assert (
        infer_provider_family(
            model="custom-model",
            provider="openai_compatible",
            api_base="https://openrouter.ai/api/v1",
        )
        == "openrouter"
    )
    assert (
        infer_provider_family(
            model="openai/custom-model",
            provider="openai_compatible",
            api_base="https://gateway.qwen-proxy.example/v1",
        )
        == "openai_compatible"
    )
    assert (
        infer_provider_family(
            model="custom-model",
            provider="openai_compatible",
            api_base="https://deepseek-compatible.internal/v1",
        )
        == "openai_compatible"
    )


def test_hints_disabled_preserves_request_shape_and_input_object():
    original = {
        "model": "openai/gpt-4o",
        "messages": [{"role": "user", "content": "hello"}],
        "extra_body": {"thinking": {"type": "enabled"}},
    }
    before = copy.deepcopy(original)

    result = apply_prompt_cache_hints(
        original,
        ProviderCacheRouteContext(model="openai/gpt-4o", provider="openai"),
        _config(llm_prompt_cache_hints_enabled=False),
    )

    assert result.call_kwargs == before
    assert original == before
    assert not result.hint_applied
    assert result.disabled_reason == "hints_disabled"


def test_openai_doc_only_caps_do_not_emit_prompt_cache_key_until_verified():
    original = {"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hello"}]}

    result = apply_prompt_cache_hints(
        original,
        ProviderCacheRouteContext(model="openai/gpt-4o", provider="openai", api_surface="chat_completions"),
        _config(llm_prompt_cache_hints_enabled=True, llm_prompt_cache_diagnostics_level="basic"),
    )

    assert "prompt_cache_key" not in result.call_kwargs
    assert not result.hint_applied
    assert result.disabled_reason == "capability_not_verified"
    assert result.diagnostics["verification_status"] == "doc_only"


def test_verified_openai_prompt_cache_key_uses_hmac_without_mutating_input(monkeypatch):
    monkeypatch.setenv("LLM_USAGE_HMAC_SECRET", "cache-secret")
    monkeypatch.setenv("LLM_USAGE_HMAC_KEY_VERSION", "cache-v1")
    original = {"model": "openai/gpt-4o", "messages": [{"role": "user", "content": "hello"}]}
    before = copy.deepcopy(original)
    caps = _verified_caps("openai", DirectiveSupport(prompt_cache_key=True))

    with patch("src.llm.provider_cache.resolve_provider_cache_caps", return_value=caps):
        result = apply_prompt_cache_hints(
            original,
            ProviderCacheRouteContext(model="openai/gpt-4o", provider="openai"),
            _config(llm_prompt_cache_hints_enabled=True, llm_prompt_cache_diagnostics_level="debug"),
        )

    assert result.hint_applied
    assert len(result.call_kwargs["prompt_cache_key"]) == 64
    assert result.call_kwargs["prompt_cache_key"] != "hello"
    assert original == before
    assert result.diagnostics["route_key_hmac"]


def test_anthropic_lowering_adds_cache_control_to_system_prefix_only():
    original = {
        "model": "anthropic/claude-sonnet-4-6",
        "messages": [
            {"role": "system", "content": "stable rules"},
            {"role": "user", "content": "dynamic quote 600519"},
        ],
    }
    caps = _verified_caps("anthropic", DirectiveSupport(block_cache_control=True))

    with patch("src.llm.provider_cache.resolve_provider_cache_caps", return_value=caps):
        result = apply_prompt_cache_hints(
            original,
            ProviderCacheRouteContext(model="anthropic/claude-sonnet-4-6", provider="anthropic"),
            _config(llm_prompt_cache_hints_enabled=True),
        )

    assert result.hint_applied
    lowered_messages = result.call_kwargs["messages"]
    assert lowered_messages[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert lowered_messages[0]["content"][0]["text"] == "stable rules"
    assert lowered_messages[1]["content"] == "dynamic quote 600519"
    assert original["messages"][0]["content"] == "stable rules"


def test_repeated_lowering_from_shared_input_does_not_cross_pollute_results():
    original = {
        "model": "anthropic/claude-sonnet-4-6",
        "messages": [
            {"role": "system", "content": "stable rules"},
            {"role": "user", "content": "dynamic quote 600519"},
        ],
    }
    before = copy.deepcopy(original)
    caps = _verified_caps("anthropic", DirectiveSupport(block_cache_control=True))

    with patch("src.llm.provider_cache.resolve_provider_cache_caps", return_value=caps):
        first = apply_prompt_cache_hints(
            original,
            ProviderCacheRouteContext(model="anthropic/claude-sonnet-4-6", provider="anthropic"),
            _config(llm_prompt_cache_hints_enabled=True),
        )
        second = apply_prompt_cache_hints(
            original,
            ProviderCacheRouteContext(model="anthropic/claude-sonnet-4-6", provider="anthropic"),
            _config(llm_prompt_cache_hints_enabled=True),
        )

    assert original == before
    assert first.call_kwargs is not second.call_kwargs
    assert first.call_kwargs["messages"] is not second.call_kwargs["messages"]
    first.call_kwargs["messages"][0]["content"][0]["text"] = "mutated first result"
    assert second.call_kwargs["messages"][0]["content"][0]["text"] == "stable rules"
    assert original["messages"][0]["content"] == "stable rules"


def test_litellm_openai_prompt_cache_key_is_not_passed_through_without_verified_capture():
    sanitized_env = os.environ.copy()
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_API_TYPE",
        "OPENAI_API_VERSION",
        "AZURE_API_KEY",
        "AZURE_API_BASE",
        "AZURE_OPENAI_ENDPOINT",
        "LITELLM_API_KEY",
        "LITELLM_BASE_URL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        sanitized_env.pop(key, None)
    sanitized_env["NO_PROXY"] = "127.0.0.1,localhost"
    sanitized_env["no_proxy"] = "127.0.0.1,localhost"

    script = textwrap.dedent(
        """
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        try:
            import litellm
        except ModuleNotFoundError:
            print("LITELLM_MISSING")
            raise SystemExit(77)

        captured = {}
        request_seen = threading.Event()

        class CaptureHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("content-length", "0") or "0")
                captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
                request_seen.set()
                payload = {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
                response = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, *args):
                return

        try:
            server = HTTPServer(("127.0.0.1", 0), CaptureHandler)
        except PermissionError as exc:
            print(f"LOCAL_SOCKET_UNAVAILABLE={exc}")
            raise SystemExit(78)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            litellm.completion(
                model="openai/test-model",
                api_base=f"http://127.0.0.1:{server.server_port}/v1",
                api_key="sk-test",
                messages=[{"role": "user", "content": "hello"}],
                prompt_cache_key="cache-key",
                max_tokens=1,
                timeout=5,
                num_retries=0,
            )
            if not request_seen.wait(timeout=10):
                raise AssertionError("LiteLLM did not send request to local capture server")
        finally:
            server.shutdown()
            thread.join(timeout=5)

        print("CAPTURED_BODY=" + json.dumps(captured["body"], sort_keys=True))
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        env=sanitized_env,
        text=True,
        timeout=15,
    )
    if completed.returncode == 77:
        if "LOCAL_SOCKET_UNAVAILABLE" in completed.stdout + completed.stderr:
            pytest.skip("local loopback sockets are unavailable")
        pytest.skip("litellm is not installed")
    if completed.returncode == 78:
        pytest.skip("local socket creation is not permitted in this environment")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    captured_line = next(
        (line for line in completed.stdout.splitlines() if line.startswith("CAPTURED_BODY=")),
        None,
    )
    assert captured_line, completed.stdout + completed.stderr
    body = json.loads(captured_line.removeprefix("CAPTURED_BODY="))
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert "prompt_cache_key" not in body


def test_domain_hmac_separates_prompt_cache_route_and_deepseek_domains(monkeypatch):
    monkeypatch.setenv("LLM_USAGE_HMAC_SECRET", "same-secret")
    value = {"provider": "deepseek", "call_type": "analysis"}

    prompt_key = build_domain_hmac(value, domain="prompt_cache_key")
    route_key = build_domain_hmac(value, domain="route_key")
    deepseek_id = build_domain_hmac(value, domain="deepseek_session_isolation")

    assert prompt_key["hmac"] != route_key["hmac"]
    assert route_key["hmac"] != deepseek_id["hmac"]
    assert prompt_key["hmac_key_version"] == "local-v1"


def test_debug_diagnostics_do_not_include_raw_prompt_or_request_body(monkeypatch):
    monkeypatch.setenv("LLM_USAGE_HMAC_SECRET", "cache-secret")
    original = {
        "model": "openai/gpt-4o",
        "messages": [{"role": "user", "content": "SECRET_PROMPT 600519 https://hooks.example"}],
    }
    caps = _verified_caps("openai", DirectiveSupport(prompt_cache_key=True))

    with patch("src.llm.provider_cache.resolve_provider_cache_caps", return_value=caps):
        result = apply_prompt_cache_hints(
            original,
            ProviderCacheRouteContext(model="openai/gpt-4o", provider="openai"),
            _config(llm_prompt_cache_hints_enabled=True, llm_prompt_cache_diagnostics_level="debug"),
        )

    diagnostics_text = str(result.diagnostics)
    assert "SECRET_PROMPT" not in diagnostics_text
    assert "600519" not in diagnostics_text
    assert "hooks.example" not in diagnostics_text


def test_filter_prompt_cache_telemetry_removes_provider_cache_fields_when_disabled():
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
        "provider_usage_json": '{"prompt_tokens":10}',
        "normalized_cache_read_tokens": 5,
        "cache_capability": "supported",
        "cache_observation": "partial_hit",
        "messages_hmac": "a" * 64,
    }

    filtered = filter_prompt_cache_telemetry(
        usage,
        _config(llm_prompt_cache_telemetry_enabled=False),
    )

    assert filtered["prompt_tokens"] == 10
    assert filtered["messages_hmac"] == "a" * 64
    assert getattr(filtered, "prompt_cache_telemetry_disabled", False)
    assert "prompt_cache_telemetry_disabled" not in filtered
    assert "provider_usage_json" not in filtered
    assert "normalized_cache_read_tokens" not in filtered
    assert "cache_capability" not in filtered
