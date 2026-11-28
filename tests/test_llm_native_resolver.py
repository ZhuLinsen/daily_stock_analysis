# -*- coding: utf-8 -*-
"""Suite 1: Resolver golden table (~45 rows), R1-R9 invariants, fail-closed zero-HTTP checks, and edge cases."""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock

import httpx
import pytest

from src.config import Config, get_litellm_model_providers, normalize_llm_channel_model
from src.llm.native_resolve import (
    CANONICAL_LITELLM_PROVIDERS,
    normalize_endpoint_url,
    resolve_deployment,
    resolve_gemini_endpoint_url,
)
from src.llm.native_types import (
    DeploymentSpec,
    NativeBadRequestError,
    NativeConfigError,
    Unsupported,
)
from src.llm.transport import (
    NativeUnifiedRouter,
    NativeUnifiedTransport,
    create_native_transport,
    reset_transport_cache,
)
from src.services import image_stock_extractor, screening_service
from src.services.screening import ranker


def _fail_if_called_transport() -> httpx.MockTransport:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected HTTP call made for fail-closed deployment: {request.method} {request.url}")

    return httpx.MockTransport(_handler)


_GOLDEN_RESOLVED_ROWS: List[Dict[str, Any]] = [
    # --- R1: No gpt-5 / o3 / o4 / codex auto-hijack to /responses ---
    {
        "id": "gpt5_official_defaults_to_chat",
        "model": "openai/gpt-5",
        "params": {"api_key": "sk-test-11111111"},
        "expected": ("openai_chat", "https://api.openai.com/v1/chat/completions", "Authorization", "gpt-5"),
    },
    {
        "id": "gpt5_relay_explicit_chat_surface",
        "model": "openai/gpt-5",
        "params": {"api_base": "https://relay.example.com/v1", "api_key": "sk-relay-1234", "api_surface": "chat_completions"},
        "expected": ("openai_chat", "https://relay.example.com/v1/chat/completions", "Authorization", "gpt-5"),
    },
    {
        "id": "o3_relay_stays_chat",
        "model": "openai/o3-mini",
        "params": {"api_base": "https://relay.example.com/v1", "api_key": "sk-relay-1234"},
        "expected": ("openai_chat", "https://relay.example.com/v1/chat/completions", "Authorization", "o3-mini"),
    },
    {
        "id": "o4_official_stays_chat",
        "model": "openai/o4-mini",
        "params": {"api_key": "sk-test-11111111"},
        "expected": ("openai_chat", "https://api.openai.com/v1/chat/completions", "Authorization", "o4-mini"),
    },
    {
        "id": "codex_model_stays_chat",
        "model": "openai/codex-mini-latest",
        "params": {"api_key": "sk-test-11111111"},
        "expected": ("openai_chat", "https://api.openai.com/v1/chat/completions", "Authorization", "codex-mini-latest"),
    },
    # --- R1: Explicit Responses paths & precedence ---
    {
        "id": "explicit_wire_protocol_responses",
        "model": "openai/gpt-4o",
        "params": {"wire_protocol": "openai_responses", "api_key": "sk-test-11111111"},
        "expected": ("openai_responses", "https://api.openai.com/v1/responses", "Authorization", "gpt-4o"),
    },
    {
        "id": "explicit_dsa_api_surface_responses",
        "model": "openai/gpt-5.6-sol",
        "params": {"api_base": "https://open-gateway.anspire.cn/v6", "api_key": "sk-anspire-1234"},
        "model_info": {"dsa_api_surface": "responses"},
        "expected": ("openai_responses", "https://open-gateway.anspire.cn/v6/responses", "Authorization", "gpt-5.6-sol"),
    },
    {
        "id": "openai_responses_wire_encoding",
        "model": "openai/responses/gpt-5",
        "params": {"api_key": "sk-test-11111111"},
        "expected": ("openai_responses", "https://api.openai.com/v1/responses", "Authorization", "gpt-5"),
    },
    {
        "id": "bare_responses_encoding",
        "model": "responses/gpt-5-mini",
        "params": {"api_base": "https://relay.example.com/v1", "api_key": "sk-relay-1234"},
        "expected": ("openai_responses", "https://relay.example.com/v1/responses", "Authorization", "gpt-5-mini"),
    },
    {
        "id": "responses_url_path_detection",
        "model": "openai/gpt-5",
        "params": {"api_base": "https://relay.example.com/v1/responses", "api_key": "sk-relay-1234"},
        "expected": ("openai_responses", "https://relay.example.com/v1/responses", "Authorization", "gpt-5"),
    },
    # --- R1 + R4: Opaque relay model IDs (never strip org/vendor namespaces!) ---
    {
        "id": "relay_qwen_org_preserved",
        "model": "Qwen/Qwen3-235B",
        "params": {"api_base": "https://api.siliconflow.cn/v1", "api_key": "sk-sf-1234"},
        "expected": ("openai_chat", "https://api.siliconflow.cn/v1/chat/completions", "Authorization", "Qwen/Qwen3-235B"),
    },
    {
        "id": "relay_openai_prefixed_qwen_strips_single_openai",
        "model": "openai/Qwen/Qwen3-235B",
        "params": {"api_base": "https://api.siliconflow.cn/v1", "api_key": "sk-sf-1234"},
        "expected": ("openai_chat", "https://api.siliconflow.cn/v1/chat/completions", "Authorization", "Qwen/Qwen3-235B"),
    },
    {
        "id": "relay_deepseek_ai_org_preserved",
        "model": "deepseek-ai/DeepSeek-V3.2",
        "params": {"api_base": "https://api.siliconflow.cn/v1", "api_key": "sk-sf-1234"},
        "expected": ("openai_chat", "https://api.siliconflow.cn/v1/chat/completions", "Authorization", "deepseek-ai/DeepSeek-V3.2"),
    },
    {
        "id": "relay_anthropic_behind_openai_channel",
        "model": "anthropic/claude-sonnet-4",
        "params": {"api_base": "https://api.x6.ai/v1", "api_key": "sk-x6-1234"},
        "model_info": {"dsa_channel_protocol": "openai", "dsa_api_surface": "chat_completions"},
        "expected": ("openai_chat", "https://api.x6.ai/v1/chat/completions", "Authorization", "anthropic/claude-sonnet-4"),
    },
    {
        "id": "relay_openai_anthropic_double_prefix",
        "model": "openai/anthropic/claude-sonnet-4",
        "params": {"api_base": "https://router.requesty.ai/v1", "api_key": "sk-req-1234"},
        "expected": ("openai_chat", "https://router.requesty.ai/v1/chat/completions", "Authorization", "anthropic/claude-sonnet-4"),
    },
    {
        "id": "relay_openai_openai_double_prefix",
        "model": "openai/openai/gpt-4o-mini",
        "params": {"api_base": "https://api.x6.ai/v1", "api_key": "sk-x6-1234"},
        "expected": ("openai_chat", "https://api.x6.ai/v1/chat/completions", "Authorization", "openai/gpt-4o-mini"),
    },
    {
        "id": "relay_bare_claude_on_custom_openai_base",
        "model": "claude-sonnet-4-6",
        "params": {"api_base": "https://oneapi.example.com/v1", "api_key": "sk-one-1234"},
        "expected": ("openai_chat", "https://oneapi.example.com/v1/chat/completions", "Authorization", "claude-sonnet-4-6"),
    },
    # --- R2: Verified LiteLLM-aligned official default bases ---
    {
        "id": "deepseek_default_base",
        "model": "deepseek/deepseek-chat",
        "params": {"api_key": "sk-ds-1234"},
        "expected": ("openai_chat", "https://api.deepseek.com/v1/chat/completions", "Authorization", "deepseek-chat"),
    },
    {
        "id": "moonshot_default_ai_domain",
        "model": "moonshot/kimi-k2.6",
        "params": {"api_key": "sk-ms-1234"},
        "expected": ("openai_chat", "https://api.moonshot.ai/v1/chat/completions", "Authorization", "kimi-k2.6"),
    },
    {
        "id": "minimax_default_io_domain",
        "model": "minimax/MiniMax-M3.1-Flash",
        "params": {"api_key": "sk-mm-1234"},
        "expected": ("openai_chat", "https://api.minimax.io/v1/chat/completions", "Authorization", "MiniMax-M3.1-Flash"),
    },
    {
        "id": "dashscope_default_base",
        "model": "dashscope/qwen-plus",
        "params": {"api_key": "sk-qwen-1234"},
        "expected": ("openai_chat", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", "Authorization", "qwen-plus"),
    },
    {
        "id": "zai_default_base",
        "model": "zai/glm-4.5",
        "params": {"api_key": "sk-zai-1234"},
        "expected": ("openai_chat", "https://api.z.ai/api/paas/v4/chat/completions", "Authorization", "glm-4.5"),
    },
    {
        "id": "together_ai_default_base",
        "model": "together_ai/meta-llama/Llama-3-8b",
        "params": {"api_key": "sk-tog-1234"},
        "expected": ("openai_chat", "https://api.together.xyz/v1/chat/completions", "Authorization", "meta-llama/Llama-3-8b"),
    },
    {
        "id": "fireworks_ai_default_base",
        "model": "fireworks_ai/accounts/fireworks/models/llama-v3",
        "params": {"api_key": "sk-fw-1234"},
        "expected": ("openai_chat", "https://api.fireworks.ai/inference/v1/chat/completions", "Authorization", "accounts/fireworks/models/llama-v3"),
    },
    {
        "id": "volcengine_default_base",
        "model": "volcengine/ep-20260101",
        "params": {"api_key": "sk-volc-1234"},
        "expected": ("openai_chat", "https://ark.cn-beijing.volces.com/api/v3/chat/completions", "Authorization", "ep-20260101"),
    },
    {
        "id": "openrouter_vendor_model",
        "model": "openrouter/anthropic/claude-3.5-sonnet",
        "params": {"api_key": "sk-or-1234"},
        "expected": ("openai_chat", "https://openrouter.ai/api/v1/chat/completions", "Authorization", "anthropic/claude-3.5-sonnet"),
    },
    {
        "id": "openrouter_auto_preserved",
        "model": "openrouter/auto",
        "params": {"api_key": "sk-or-1234"},
        "expected": ("openai_chat", "https://openrouter.ai/api/v1/chat/completions", "Authorization", "openrouter/auto"),
    },
    {
        "id": "groq_default_base",
        "model": "groq/llama-3.3-70b-versatile",
        "params": {"api_key": "gsk_test1234"},
        "expected": ("openai_chat", "https://api.groq.com/openai/v1/chat/completions", "Authorization", "llama-3.3-70b-versatile"),
    },
    {
        "id": "xai_default_base",
        "model": "xai/grok-2",
        "params": {"api_key": "xai-test1234"},
        "expected": ("openai_chat", "https://api.x.ai/v1/chat/completions", "Authorization", "grok-2"),
    },
    {
        "id": "mistral_default_base",
        "model": "mistral/mistral-large-latest",
        "params": {"api_key": "sk-mis-1234"},
        "expected": ("openai_chat", "https://api.mistral.ai/v1/chat/completions", "Authorization", "mistral-large-latest"),
    },
    {
        "id": "perplexity_default_base",
        "model": "perplexity/sonar",
        "params": {"api_key": "pplx-test1234"},
        "expected": ("openai_chat", "https://api.perplexity.ai/chat/completions", "Authorization", "sonar"),
    },
    # --- R5: Ollama, Anthropic, Gemini & Query-Safe URL Normalization ---
    {
        "id": "ollama_bare_origin_adds_v1",
        "model": "ollama/qwen3:8b",
        "params": {"api_base": "http://127.0.0.1:11434"},
        "expected": ("openai_chat", "http://127.0.0.1:11434/v1/chat/completions", "", "qwen3:8b"),
    },
    {
        "id": "anthropic_official_default",
        "model": "anthropic/claude-sonnet-4-6",
        "params": {"api_key": "sk-ant-1234"},
        "expected": ("anthropic", "https://api.anthropic.com/v1/messages", "x-api-key", "claude-sonnet-4-6"),
    },
    {
        "id": "anthropic_proxy_with_v1_no_double_v1",
        "model": "anthropic/claude-sonnet-4-6",
        "params": {"api_base": "https://claude-proxy.example.com/v1", "api_key": "sk-ant-1234"},
        "expected": ("anthropic", "https://claude-proxy.example.com/v1/messages", "x-api-key", "claude-sonnet-4-6"),
    },
    {
        "id": "anthropic_proxy_bearer_override",
        "model": "anthropic/claude-sonnet-4-6",
        "params": {
            "api_base": "https://claude-proxy.example.com",
            "api_key": "sk-ant-1234",
            "extra_headers": {"Authorization": "Bearer custom-tok-9999"},
        },
        "expected": ("anthropic", "https://claude-proxy.example.com/v1/messages", "Authorization", "claude-sonnet-4-6"),
    },
    {
        "id": "gemini_official_default",
        "model": "gemini/gemini-2.5-flash",
        "params": {"api_key": "AIzaTestKey012345678901234"},
        "expected": (
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            "x-goog-api-key",
            "gemini-2.5-flash",
        ),
    },
    {
        "id": "gemini_custom_proxy_appends_v1beta_and_preserves_query_key",
        "model": "gemini/gemini-2.5-flash",
        "params": {"api_base": "https://gem-proxy.example.com/proxy?key=query-secret-9999"},
        "expected": (
            "gemini",
            "https://gem-proxy.example.com/proxy/v1beta/models/gemini-2.5-flash:generateContent?key=query-secret-9999",
            "query:key",
            "gemini-2.5-flash",
        ),
    },
    {
        "id": "gemini_v1beta_openai_path_routes_to_openai_chat",
        "model": "gemini-2.5-flash",
        "params": {
            "api_base": "https://generativelanguage.googleapis.com/v1beta/openai",
            "api_key": "AIzaTestKey012345678901234",
        },
        "expected": (
            "openai_chat",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "Authorization",
            "gemini-2.5-flash",
        ),
    },
    {
        "id": "openai_chat_preserves_query_and_semicolon_params",
        "model": "openai/gpt-4o",
        "params": {"api_base": "https://relay.example.com/v1;tenant=alpha?api-version=2", "api_key": "sk-test-1234"},
        "expected": (
            "openai_chat",
            "https://relay.example.com/v1;tenant=alpha/chat/completions?api-version=2",
            "Authorization",
            "gpt-4o",
        ),
    },
    {
        "id": "openai_chat_dedups_chat_completions",
        "model": "openai/gpt-4o",
        "params": {"api_base": "https://relay.example.com/v1/chat/completions", "api_key": "sk-test-1234"},
        "expected": ("openai_chat", "https://relay.example.com/v1/chat/completions", "Authorization", "gpt-4o"),
    },
]

_GOLDEN_UNSUPPORTED_ROWS: List[Dict[str, Any]] = [
    # --- R1 step 1: Cloud-IAM fallback providers FIRST (even with wire_protocol!) ---
    {"id": "azure_fallback", "model": "azure/my-deployment", "params": {"api_key": "k-12345678"}, "reason": "fallback_only_provider"},
    {"id": "azure_overrides_wire_protocol", "model": "azure/my-deployment", "params": {"wire_protocol": "openai_chat", "api_base": "https://my.openai.azure.com"}, "reason": "fallback_only_provider"},
    {"id": "bedrock_fallback", "model": "bedrock/anthropic.claude-3-5-sonnet", "params": {}, "reason": "fallback_only_provider"},
    {"id": "vertex_ai_fallback", "model": "vertex_ai/gemini-2.5-flash", "params": {}, "reason": "fallback_only_provider"},
    {"id": "sagemaker_fallback", "model": "sagemaker/my-ep", "params": {}, "reason": "fallback_only_provider"},
    {"id": "cohere_chat_fallback", "model": "cohere_chat/command-r", "params": {}, "reason": "fallback_only_provider"},
    # --- R2: Fail-closed missing api_base (ZERO calls to api.openai.com!) ---
    {"id": "custom_without_base_fails_closed", "model": "custom/my-model", "params": {"api_key": "sk-12345678"}, "reason": "missing_api_base"},
    {"id": "openai_compatible_without_base_fails_closed", "model": "openai_compatible/my-model", "params": {"api_key": "sk-12345678"}, "reason": "missing_api_base"},
    {"id": "vllm_without_base_fails_closed", "model": "vllm/llama-3", "params": {}, "reason": "missing_api_base"},
    {"id": "hosted_vllm_without_base_fails_closed", "model": "hosted_vllm/qwen", "params": {}, "reason": "missing_api_base"},
    {"id": "qwen_org_without_base_fails_closed", "model": "Qwen/Qwen3-235B", "params": {"api_key": "sk-12345678"}, "reason": "unknown_provider_without_api_base"},
    {"id": "zhipu_without_base_fails_closed", "model": "zhipu/glm-4", "params": {"api_key": "sk-12345678"}, "reason": "unknown_provider_without_api_base"},
    {"id": "siliconflow_without_base_fails_closed", "model": "siliconflow/deepseek-ai/DeepSeek-V3", "params": {"api_key": "sk-12345678"}, "reason": "unknown_provider_without_api_base"},
    # --- R5: Contradictory explicit full endpoint vs surface ---
    {
        "id": "chat_endpoint_with_responses_surface_fails_closed",
        "model": "openai/gpt-5",
        "params": {"api_base": "https://relay.example.com/v1/chat/completions", "api_surface": "responses", "api_key": "sk-1234"},
        "reason": "endpoint_surface_mismatch",
    },
    {
        "id": "responses_endpoint_with_chat_surface_fails_closed",
        "model": "openai/gpt-5",
        "params": {"api_base": "https://relay.example.com/v1/responses", "api_surface": "chat_completions", "api_key": "sk-1234"},
        "reason": "endpoint_surface_mismatch",
    },
    # --- Codex #35: Unset os.environ/VAR endpoint & conflicting base_url/api_base ---
    {
        "id": "unset_env_endpoint_fails_closed",
        "model": "openai/gpt-4o",
        "params": {"api_base": "os.environ/UNSET_DSA_ENDPOINT_VAR_XYZ", "api_key": "sk-1234"},
        "reason": "unresolved_endpoint_env",
    },
    {
        "id": "conflicting_base_url_and_api_base_fails_closed",
        "model": "openai/gpt-4o",
        "params": {
            "api_base": "https://a.example.com/v1;tenant=A",
            "base_url": "https://a.example.com/v1;tenant=B",
            "api_key": "sk-1234",
        },
        "reason": "conflicting_api_base",
    },
]


@pytest.mark.parametrize("row", _GOLDEN_RESOLVED_ROWS, ids=[r["id"] for r in _GOLDEN_RESOLVED_ROWS])
def test_resolver_golden_table_resolved_rows(row: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify deterministic (protocol, URL, auth header, wire_model) across ~40 golden rows."""
    for env_key in (
        "OPENAI_API_BASE",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_BASE",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_BASE",
        "GOOGLE_API_BASE",
        "GEMINI_API_KEY",
        "OLLAMA_API_BASE",
        "OPENROUTER_API_BASE",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(env_key, raising=False)

    res = resolve_deployment(
        row["model"],
        params=row.get("params"),
        model_info=row.get("model_info"),
    )
    assert isinstance(res, DeploymentSpec), f"Expected DeploymentSpec for {row['id']}, got {res}"
    exp_proto, exp_url, exp_auth, exp_wire = row["expected"]
    assert (res.protocol, res.endpoint_url, res.auth_header_name, res.wire_model) == (
        exp_proto,
        exp_url,
        exp_auth,
        exp_wire,
    )


@pytest.mark.parametrize("row", _GOLDEN_UNSUPPORTED_ROWS, ids=[r["id"] for r in _GOLDEN_UNSUPPORTED_ROWS])
def test_resolver_golden_table_fail_closed_zero_http_calls(
    row: Dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed rows return Unsupported and raise NativeConfigError with ZERO HTTP calls."""
    monkeypatch.delenv("UNSET_DSA_ENDPOINT_VAR_XYZ", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)

    res = resolve_deployment(row["model"], params=row.get("params"))
    assert isinstance(res, Unsupported), f"Expected Unsupported for {row['id']}, got {res}"
    assert res.reason == row["reason"]

    transport = create_native_transport(
        http_transport=_fail_if_called_transport(),
        fallback_to_litellm=False,
    )
    with pytest.raises(NativeConfigError):
        transport.completion(
            model=row["model"],
            messages=[{"role": "user", "content": "hi"}],
            **dict(row.get("params") or {}),
        )


def test_resolver_env_bases_env_keys_os_environ_refs_and_origin_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2 & R3: honor provider env bases/keys, os.environ/VAR, and keep credentials origin-bound."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_env_secret_1234")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-secret-9999")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://127.0.0.1:11435")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://anth-env.example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-secret-8888")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-prod-secret-7777")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.setenv("MY_CUSTOM_HEADER_TOKEN", "hdr-secret-5555")
    monkeypatch.setenv("MY_CUSTOM_RELAY_URL", "https://custom-env.example.com/v1")

    # 1. Standard provider env keys
    groq_spec = resolve_deployment("groq/llama-3.3-70b-versatile")
    assert isinstance(groq_spec, DeploymentSpec)
    assert groq_spec.api_key == "gsk_env_secret_1234"
    assert groq_spec.endpoint_url == "https://api.groq.com/openai/v1/chat/completions"

    or_spec = resolve_deployment("openrouter/anthropic/claude-3.5-sonnet")
    assert isinstance(or_spec, DeploymentSpec)
    assert or_spec.api_key == "sk-or-env-secret-9999"
    assert or_spec.wire_model == "anthropic/claude-3.5-sonnet"

    # 2. Provider env bases
    ollama_spec = resolve_deployment("ollama/qwen3:8b")
    assert isinstance(ollama_spec, DeploymentSpec)
    assert ollama_spec.endpoint_url == "http://127.0.0.1:11435/v1/chat/completions"
    assert ollama_spec.api_key == ""

    anth_spec = resolve_deployment("anthropic/claude-sonnet-4-6")
    assert isinstance(anth_spec, DeploymentSpec)
    assert anth_spec.endpoint_url == "https://anth-env.example.com/v1/messages"
    assert anth_spec.api_key == "sk-ant-env-secret-8888"

    # 3. Centralized os.environ/VAR in api_base, api_key, extra_headers
    yaml_spec = resolve_deployment(
        {
            "model_name": "my-yaml-alias",
            "litellm_params": {
                "model": "openai/Qwen/Qwen3-235B",
                "api_base": "os.environ/MY_CUSTOM_RELAY_URL",
                "api_key": "os.environ/OPENAI_API_KEY",
                "extra_headers": {"X-Relay-Auth": "os.environ/MY_CUSTOM_HEADER_TOKEN"},
                "temperature": 0.2,
                "max_tokens": 512,
                "store": False,
            },
        }
    )
    assert isinstance(yaml_spec, DeploymentSpec)
    assert yaml_spec.endpoint_url == "https://custom-env.example.com/v1/chat/completions"
    assert yaml_spec.api_key == "sk-openai-prod-secret-7777"
    assert yaml_spec.extra_headers == {"X-Relay-Auth": "hdr-secret-5555"}
    assert yaml_spec.wire_model == "Qwen/Qwen3-235B"
    # R8: YAML generation defaults carried into request_defaults
    assert yaml_spec.request_defaults["temperature"] == 0.2
    assert yaml_spec.request_defaults["max_tokens"] == 512
    assert yaml_spec.request_defaults["store"] is False

    # 4. R3 origin-binding: OPENAI_API_KEY MUST NOT leak to an unrelated custom host or keyless localhost
    local_spec = resolve_deployment("openai/local-llama", params={"api_base": "http://127.0.0.1:8000/v1"})
    assert isinstance(local_spec, DeploymentSpec)
    assert local_spec.api_key == ""

    unrelated_host_spec = resolve_deployment("openai/gpt-4o", params={"api_base": "https://other-host.example.com/v1"})
    assert isinstance(unrelated_host_spec, DeploymentSpec)
    assert unrelated_host_spec.api_key == ""


def test_gemini_url_stream_merges_alt_sse_preserving_existing_query() -> None:
    """R5: Gemini streaming URL merges alt=sse cleanly via parse_qsl/urlencode without duplicating ?."""
    url = resolve_gemini_endpoint_url(
        "https://gem-proxy.example.com/proxy?key=k123&foo=bar",
        "gemini-2.5-flash",
        stream=True,
    )
    assert url == "https://gem-proxy.example.com/proxy/v1beta/models/gemini-2.5-flash:streamGenerateContent?key=k123&foo=bar&alt=sse"
    assert url.count("?") == 1


def test_r6_exact_alias_matching_and_r7_per_alias_hybrid_routing() -> None:
    """R6 rejects misses on populated routers; R7 delegates only unsupported alias groups in auto mode."""
    native_hits: List[str] = []
    fallback_hits: List[str] = []

    def _native_handler(request: httpx.Request) -> httpx.Response:
        native_hits.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "model": "gpt-4o",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "native-ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            },
        )

    class _FakeFallbackTransport:
        def create_router(self, model_list: List[Dict[str, Any]], **kwargs: Any) -> Any:
            del kwargs

            class _SubRouter:
                def completion(self, **call_kwargs: Any) -> Any:
                    fallback_hits.append(str(call_kwargs.get("model")))
                    return {
                        "choices": [{"message": {"content": "fallback-ok"}}],
                        "model": call_kwargs.get("model"),
                    }

            return _SubRouter()

        def can_register_model(self) -> bool:
            return False

    model_list = [
        {
            "model_name": "alias-native",
            "litellm_params": {"model": "openai/gpt-4o", "api_key": "sk-native-1234"},
        },
        {
            "model_name": "alias-bedrock",
            "litellm_params": {"model": "bedrock/anthropic.claude-3-5-sonnet"},
        },
    ]

    # Auto mode: hybrid per-alias router keeps alias-native on HTTPX and delegates alias-bedrock.
    auto_router = NativeUnifiedRouter(
        model_list=model_list,
        fallback_transport=_FakeFallbackTransport(),
        http_transport=httpx.MockTransport(_native_handler),
    )
    assert auto_router.fallback_aliases == frozenset({"alias-bedrock"})
    resp_native = auto_router.completion(model="alias-native", messages=[{"role": "user", "content": "hi"}])
    assert resp_native.choices[0].message.content == "native-ok"
    assert len(native_hits) == 1
    assert fallback_hits == []

    resp_fb = auto_router.completion(model="alias-bedrock", messages=[{"role": "user", "content": "hi"}])
    assert resp_fb["choices"][0]["message"]["content"] == "fallback-ok"
    assert fallback_hits == ["alias-bedrock"]

    # R6: wire_model ("gpt-4o" / "openai/gpt-4o") does NOT match "alias-native"; populated router raises!
    with pytest.raises(NativeBadRequestError):
        auto_router.completion(model="openai/gpt-4o", messages=[{"role": "user", "content": "hi"}])
    with pytest.raises(NativeBadRequestError):
        auto_router.completion(model="nonexistent-alias", messages=[{"role": "user", "content": "hi"}])

    # Strict native mode: fails closed on construction with NativeConfigError.
    with pytest.raises(NativeConfigError):
        NativeUnifiedRouter(
            model_list=model_list,
            fallback_transport=None,
            http_transport=_fail_if_called_transport(),
        )


def test_r9_provider_registry_is_mode_independent_and_excludes_org_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R9: get_model_providers() never injects qwen/glm/zhipu/ark/siliconflow/google/claude."""
    forbidden_org_prefixes = {"qwen", "glm", "zhipu", "ark", "siliconflow", "google", "claude"}
    assert CANONICAL_LITELLM_PROVIDERS.isdisjoint(forbidden_org_prefixes)

    native_transport = NativeUnifiedTransport()
    assert native_transport.get_model_providers() == CANONICAL_LITELLM_PROVIDERS
    assert native_transport.get_model_providers().isdisjoint(forbidden_org_prefixes)

    monkeypatch.setenv("LLM_TRANSPORT_MODE", "native")
    reset_transport_cache()
    try:
        providers = get_litellm_model_providers()
        assert providers.isdisjoint(forbidden_org_prefixes)
        assert normalize_llm_channel_model("Qwen/Qwen3-235B", "openai") == "openai/Qwen/Qwen3-235B"
        assert normalize_llm_channel_model("deepseek-ai/DeepSeek-V3", "openai") == "openai/deepseek-ai/DeepSeek-V3"
    finally:
        monkeypatch.delenv("LLM_TRANSPORT_MODE", raising=False)
        reset_transport_cache()


def test_codex_edge_cases_vision_url_conflict_semicolon_params_and_ranker_yaml_env(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fold Codex #35 edge cases cleanly: Vision unmatched conflict, urlsplit semicolons, ranker YAML fail-closed."""
    # 1. urlsplit preserves semicolon params in Vision & screening normalization
    assert normalize_endpoint_url("https://Host.Example.COM/v1;tenant=A/") == "https://host.example.com/v1;tenant=A"
    assert normalize_endpoint_url("https://Host.Example.COM/v1;tenant=B/") == "https://host.example.com/v1;tenant=B"
    assert (
        screening_service._normalize_screening_api_base("https://host.example.com/v1;tenant=A")
        != screening_service._normalize_screening_api_base("https://host.example.com/v1;tenant=B")
    )

    # 2. Vision unmatched deployment conflict (api_base="http://127.0.0.1:11434" + explicit base_url="")
    cfg = Config(
        vision_model="openai/local-vision",
        openai_api_keys=["sk-legacy-should-not-be-used-1234"],
        llm_model_list=[
            {
                "model_name": "openai/local-vision",
                "litellm_params": {
                    "model": "openai/local-vision",
                    "api_base": "http://127.0.0.1:11434/v1",
                    "base_url": "",
                },
            }
        ],
    )
    monkeypatch.setattr(image_stock_extractor, "get_config", lambda: cfg)
    with pytest.raises(ValueError, match="conflicting api_base and base_url"):
        image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png")

    # 3. Ranker YAML loader fails closed when endpoint os.environ/VAR is unset
    monkeypatch.delenv("UNSET_RANKER_BASE_VAR_XYZ", raising=False)
    yaml_file = tmp_path / "litellm.yaml"
    yaml_file.write_text(
        json.dumps(
            {
                "model_list": [
                    {
                        "model_name": "openai/rank-model",
                        "litellm_params": {
                            "model": "openai/rank-model",
                            "api_base": "os.environ/UNSET_RANKER_BASE_VAR_XYZ",
                            "api_key": "sk-rank-1234",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="UNSET_RANKER_BASE_VAR_XYZ"):
        ranker._call_litellm_router(
            config_path=str(yaml_file),
            model_chain=["openai/rank-model"],
            messages=[{"role": "user", "content": "rank"}],
            temperature=0.1,
            json_mode=True,
            timeout_sec=10.0,
        )


def test_p0_1_explicit_api_surface_never_routes_unknown_provider_to_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P0-1: Explicit api_surface/wire_protocol must never send unknown non-OpenAI prefixes to api.openai.com."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-should-not-leak-1234")
    for raw_kwargs in (
        {"api_surface": "chat_completions"},
        {"api_surface": "responses"},
        {"wire_protocol": "openai_chat"},
    ):
        res = resolve_deployment("replicate/internal-model", **raw_kwargs)
        assert isinstance(res, Unsupported), f"Expected Unsupported for {raw_kwargs}, got {res}"
        assert res.reason == "unknown_provider_without_api_base"
        assert res.provider == "replicate"

    # Known provider without verified default base + explicit api_surface must also fail closed.
    vllm_res = resolve_deployment("hosted_vllm/llama3", api_surface="chat_completions")
    assert isinstance(vllm_res, Unsupported)
    assert vllm_res.reason == "missing_api_base"
    assert vllm_res.provider == "hosted_vllm"

    # Anthropic/Gemini official default endpoints must not be targeted with OpenAI Chat via api_surface.
    anth_mismatch = resolve_deployment("anthropic/claude-sonnet-4-6", api_surface="chat_completions")
    assert isinstance(anth_mismatch, Unsupported)
    assert anth_mismatch.reason == "endpoint_surface_mismatch"

    # Strict native transport must raise NativeConfigError with ZERO HTTP calls.
    transport = NativeUnifiedTransport(http_transport=_fail_if_called_transport())
    with pytest.raises(NativeConfigError):
        transport.completion(
            model="replicate/internal-model",
            api_surface="chat_completions",
            messages=[{"role": "user", "content": "hi"}],
        )


def test_p0_2_origin_bound_client_key_and_env_key_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P0-2a/b: client_api_key binds to client.base_url origin; env key binds ONLY to env_base when env_base is set."""
    from types import SimpleNamespace

    # P0-2a: client bound to origin A; explicit api_base overrides to origin B -> must NOT copy origin A's key.
    origin_a_client = SimpleNamespace(
        api_key="sk-origin-a-secret-9999",
        base_url="https://origin-a.example/v1",
        _client=None,
    )
    res_cross = resolve_deployment(
        "openai/gpt-4o",
        api_base="https://origin-b.example/v1",
        client=origin_a_client,
    )
    assert isinstance(res_cross, DeploymentSpec)
    assert res_cross.api_key == ""

    # Same origin: client_api_key IS used.
    res_same = resolve_deployment(
        "openai/gpt-4o",
        api_base="https://origin-a.example/v1",
        client=origin_a_client,
    )
    assert isinstance(res_same, DeploymentSpec)
    assert res_same.api_key == "sk-origin-a-secret-9999"

    # P0-2b: When OPENAI_API_BASE is set to a proxy, OPENAI_API_KEY belongs ONLY to that proxy origin
    # and must NOT leak to an explicit https://api.openai.com/v1 call.
    monkeypatch.setenv("OPENAI_API_BASE", "https://proxy.corp.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-corp-proxy-key-8888")
    res_official = resolve_deployment("openai/gpt-4o", api_base="https://api.openai.com/v1")
    assert isinstance(res_official, DeploymentSpec)
    assert res_official.api_key == ""

    res_proxy = resolve_deployment("openai/gpt-4o", api_base="https://proxy.corp.example/v1")
    assert isinstance(res_proxy, DeploymentSpec)
    assert res_proxy.api_key == "sk-corp-proxy-key-8888"


def test_p0_3_strict_bool_store_env_expansion_and_invalid_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P0-3: store: os.environ/STORE='false' parses to False; invalid bool strings fail closed."""
    from src.llm.native_types import NativeBadRequestError

    monkeypatch.setenv("DSA_STORE_FLAG_TEST", "false")
    res_false = resolve_deployment(
        {
            "model_name": "openai/responses/gpt-5",
            "litellm_params": {
                "model": "openai/responses/gpt-5",
                "api_base": "https://relay.example/v1",
                "api_key": "sk-1234",
                "store": "os.environ/DSA_STORE_FLAG_TEST",
            },
        }
    )
    assert isinstance(res_false, DeploymentSpec)
    assert res_false.request_defaults["store"] is False

    monkeypatch.setenv("DSA_STORE_FLAG_TEST", "maybe-store")
    with pytest.raises(NativeBadRequestError):
        resolve_deployment(
            {
                "model_name": "openai/responses/gpt-5",
                "litellm_params": {
                    "model": "openai/responses/gpt-5",
                    "api_base": "https://relay.example/v1",
                    "api_key": "sk-1234",
                    "store": "os.environ/DSA_STORE_FLAG_TEST",
                },
            }
        )


def test_p1_1_p1_2_p1_11_default_litellm_and_strict_screening_regressions(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-1: unused YAML alias unset env doesn't break screening; P1-2: exact alias Responses check; P1-11: propagate native errors."""
    from types import SimpleNamespace
    from src.llm.transport import _validate_prebuilt_router_api_surface, use_transport

    # P1-1: Unused alias has unset env var, requested alias is valid -> must NOT raise!
    monkeypatch.delenv("UNUSED_ALIAS_BASE_XYZ", raising=False)
    yaml_file = tmp_path / "litellm_unused.yaml"
    yaml_file.write_text(
        json.dumps(
            {
                "model_list": [
                    {
                        "model_name": "openai/unused-alias",
                        "litellm_params": {
                            "model": "openai/unused-alias",
                            "api_base": "os.environ/UNUSED_ALIAS_BASE_XYZ",
                            "api_key": "sk-unused",
                        },
                    },
                    {
                        "model_name": "openai/active-rank",
                        "litellm_params": {
                            "model": "openai/active-rank",
                            "api_base": "https://active.example/v1",
                            "api_key": "sk-active",
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    class _DummyRouter:
        def __init__(self, model_list, **_kw):
            self.model_list = model_list

        def completion(self, **_kw):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ranked": []}'))]
            )

    out = ranker._call_litellm_router(
        litellm=SimpleNamespace(Router=_DummyRouter),
        config_path=str(yaml_file),
        model_chain=["openai/active-rank"],
        messages=[{"role": "user", "content": "rank"}],
        temperature=0.1,
        json_mode=False,
        timeout_sec=10.0,
    )
    assert out == '{"ranked": []}'

    # P1-2: Unrelated Chat alias sharing wire name must NOT reject a valid Responses alias.
    prebuilt = SimpleNamespace(
        model_list=[
            {"model_name": "gpt-5-resp", "litellm_params": {"model": "openai/responses/gpt-5"}},
            {"model_name": "other-chat", "litellm_params": {"model": "gpt-5-resp"}},
        ]
    )
    _validate_prebuilt_router_api_surface(prebuilt, "gpt-5-resp", "responses")

    # P1-11: Strict native mode screening propagates NativeConfigError & unknown_router_alias (no silent fallback).
    bad_yaml = tmp_path / "strict_native.yaml"
    bad_yaml.write_text(
        json.dumps(
            {
                "model_list": [
                    {
                        "model_name": "bedrock/claude-3-5",
                        "litellm_params": {"model": "bedrock/claude-3-5", "api_key": "sk-1"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    strict_transport = NativeUnifiedTransport(fallback_transport=None, http_transport=_fail_if_called_transport())
    with use_transport(strict_transport):
        with pytest.raises(NativeConfigError):
            ranker._call_litellm_router(
                config_path=str(bad_yaml),
                model_chain=["bedrock/claude-3-5"],
                messages=[{"role": "user", "content": "rank"}],
                temperature=0.1,
                json_mode=False,
                timeout_sec=10.0,
            )

    miss_yaml = tmp_path / "strict_miss.yaml"
    miss_yaml.write_text(
        json.dumps(
            {
                "model_list": [
                    {
                        "model_name": "openai/registered-only",
                        "litellm_params": {
                            "model": "openai/registered-only",
                            "api_base": "https://relay.example/v1",
                            "api_key": "sk-1",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    from src.llm.native_types import NativeBadRequestError
    with use_transport(strict_transport):
        with pytest.raises(NativeBadRequestError) as exc_miss:
            ranker._call_litellm_router(
                config_path=str(miss_yaml),
                model_chain=["openai/not-in-router"],
                messages=[{"role": "user", "content": "rank"}],
                temperature=0.1,
                json_mode=False,
                timeout_sec=10.0,
            )
        assert exc_miss.value.error_code == "unknown_router_alias"


def test_p1_12_vision_metadata_and_p2_gemini_alt_override_generic_env_base_and_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-12: Vision preserves wire_protocol/custom_llm_provider/dsa_channel_protocol; P2: alt=json->sse & unified providers."""
    from types import SimpleNamespace
    from src.llm.transport import LiteLLMTransport, use_transport

    # 1. Gemini ?alt=json overrides cleanly to alt=sse on stream=True
    gem_stream_url = resolve_gemini_endpoint_url(
        "https://proxy.example/v1beta?alt=json&key=abc",
        "gemini-2.5-flash",
        stream=True,
    )
    assert "alt=sse" in gem_stream_url
    assert "alt=json" not in gem_stream_url
    assert "key=abc" in gem_stream_url

    # 2. Generic <PROVIDER>_API_BASE fallback (e.g. NOVITA_API_BASE)
    monkeypatch.setenv("NOVITA_API_BASE", "https://api.novita.ai/v3/openai")
    novita_spec = resolve_deployment("novita/qwen-3", api_key="sk-novita")
    assert isinstance(novita_spec, DeploymentSpec)
    assert novita_spec.endpoint_url == "https://api.novita.ai/v3/openai/chat/completions"

    # 3. Unified get_model_providers() across LiteLLMTransport and NativeUnifiedTransport
    assert LiteLLMTransport().get_model_providers() == NativeUnifiedTransport().get_model_providers()

    # 4. Vision forwards wire_protocol, custom_llm_provider, dsa_channel_protocol
    captured: Dict[str, Any] = {}

    class _CaptureTransport:
        def completion(self, **kw: Any) -> Any:
            captured.update(kw)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='[{"code":"600519"}]'))]
            )

    cfg = Config(
        vision_model="openai/relay-vision",
        llm_model_list=[
            {
                "model_name": "openai/relay-vision",
                "litellm_params": {
                    "model": "openai/relay-vision",
                    "api_base": "https://relay.example/v1",
                    "api_key": "sk-vis-1234",
                    "wire_protocol": "openai_chat",
                    "custom_llm_provider": "openai",
                },
                "model_info": {"dsa_channel_protocol": "openai"},
            }
        ],
    )
    monkeypatch.setattr(image_stock_extractor, "get_config", lambda: cfg)
    with use_transport(_CaptureTransport()):
        out = image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png")
    assert "600519" in out
    assert captured["wire_protocol"] == "openai_chat"
    assert captured["custom_llm_provider"] == "openai"
    assert captured["dsa_channel_protocol"] == "openai"
