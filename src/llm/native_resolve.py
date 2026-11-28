# -*- coding: utf-8 -*-
"""Single shared deployment resolver for the native 4-protocol HTTPX + SSE engine.

Implements invariants R1-R9 from Issue #2622 Phase 2:
- R1 Deterministic protocol precedence (cloud-IAM fallback first, no gpt-5/o3 auto-hijack)
- R2 Fail-closed endpoints aligned with installed LiteLLM defaults (never default non-openai to api.openai.com)
- R3 Origin-bound credentials and env fallbacks + centralized ``os.environ/VAR`` expansion
- R4 Opaque wire model pass-through (strip only single canonical wire prefix, never org namespaces)
- R5 Query-safe ``urlsplit``/``urlunsplit`` URL normalization preserving semicolon params & query args
- R8 Carry allowlisted YAML/deployment generation defaults into ``DeploymentSpec.request_defaults``
- R9 Transport-mode-independent canonical provider registry (no org prefixes)
"""

from __future__ import annotations

import copy
import math
import os
import re
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Union
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.llm.native_types import (
    DeploymentSpec,
    NativeBadRequestError,
    Unsupported,
    extract_client_overrides,
    has_header_case_insensitive,
    merge_header_overrides,
    parse_strict_bool,
)

# ============================================================
# Canonical Provider & Protocol Tables (R1, R2, R3, R4, R9)
# ============================================================

NATIVE_PROTOCOLS: frozenset[str] = frozenset(
    {
        "openai_chat",
        "openai_responses",
        "anthropic",
        "gemini",
    }
)

# Cloud-IAM / SDK-specific providers delegated to LiteLLM in ``auto`` mode and
# rejected with NativeConfigError in strict ``native`` mode (R1 step 1).
FALLBACK_ONLY_PROVIDERS: frozenset[str] = frozenset(
    {
        "azure",
        "azure_ai",
        "azure_text",
        "bedrock",
        "bedrock_mantle",
        "vertex_ai",
        "vertex_ai_beta",
        "sagemaker",
        "sagemaker_chat",
        "sagemaker_nova",
        "cohere",
        "cohere_chat",
    }
)

# Canonical LiteLLM wire prefixes that speak native OpenAI-compatible wire protocol.
# NEVER includes org/vendor namespace prefixes such as qwen, glm, zhipu, ark,
# siliconflow, google, or claude (R1, R4, R9).
NATIVE_OPENAI_WIRE_PROVIDERS: frozenset[str] = frozenset(
    {
        "openai",
        "openai_compatible",
        "openai_like",
        "custom",
        "custom_openai",
        "deepseek",
        "moonshot",
        "dashscope",
        "zai",
        "minimax",
        "volcengine",
        "openrouter",
        "ollama",
        "ollama_chat",
        "groq",
        "xai",
        "together_ai",
        "fireworks_ai",
        "mistral",
        "perplexity",
        "cerebras",
        "deepinfra",
        "novita",
        "sambanova",
        "nvidia_nim",
        "hosted_vllm",
        "vllm",
        "lm_studio",
        "github",
        "nebius",
        "hyperbolic",
        "featherless_ai",
        "xiaomi_mimo",
    }
)

NATIVE_ANTHROPIC_WIRE_PROVIDERS: frozenset[str] = frozenset({"anthropic"})
NATIVE_GEMINI_WIRE_PROVIDERS: frozenset[str] = frozenset({"gemini"})

# Static snapshot of canonical LiteLLM provider prefixes (R9: transport-mode
# independent; NEVER includes org prefixes qwen/glm/zhipu/ark/siliconflow/google/claude).
CANONICAL_LITELLM_PROVIDERS: frozenset[str] = frozenset(
    {
        "a2a",
        "a2a_agent",
        "ai21",
        "ai21_chat",
        "aiml",
        "aiohttp_openai",
        "amazon_nova",
        "anthropic",
        "anthropic_text",
        "apertis",
        "assemblyai",
        "auto_router",
        "aws_polly",
        "azure",
        "azure_ai",
        "azure_text",
        "baseten",
        "bedrock",
        "bedrock_mantle",
        "black_forest_labs",
        "bytez",
        "cerebras",
        "charity_engine",
        "chatgpt",
        "chutes",
        "clarifai",
        "cloudflare",
        "codestral",
        "cohere",
        "cohere_chat",
        "cometapi",
        "compactifai",
        "cursor",
        "custom",
        "custom_openai",
        "dashscope",
        "databricks",
        "datarobot",
        "deepgram",
        "deepinfra",
        "deepseek",
        "docker_model_runner",
        "dotprompt",
        "elevenlabs",
        "empower",
        "fal_ai",
        "featherless_ai",
        "fireworks_ai",
        "friendliai",
        "galadriel",
        "gemini",
        "gigachat",
        "github",
        "github_copilot",
        "gradient_ai",
        "groq",
        "helicone",
        "heroku",
        "hosted_vllm",
        "huggingface",
        "humanloop",
        "hyperbolic",
        "infinity",
        "jina_ai",
        "lambda_ai",
        "langfuse",
        "langgraph",
        "lemonade",
        "litellm_agent",
        "litellm_proxy",
        "llamafile",
        "lm_studio",
        "manus",
        "maritalk",
        "meta_llama",
        "milvus",
        "minimax",
        "mistral",
        "moonshot",
        "morph",
        "nano-gpt",
        "nebius",
        "nlp_cloud",
        "novita",
        "nscale",
        "nvidia_nim",
        "nvidia_riva",
        "oci",
        "ollama",
        "ollama_chat",
        "oobabooga",
        "openai",
        "openai_like",
        "openrouter",
        "ovhcloud",
        "perplexity",
        "petals",
        "pg_vector",
        "poe",
        "predibase",
        "publicai",
        "ragflow",
        "recraft",
        "reducto",
        "replicate",
        "runwayml",
        "s3_vectors",
        "sagemaker",
        "sagemaker_chat",
        "sagemaker_nova",
        "sambanova",
        "sap",
        "scaleway",
        "snowflake",
        "stability",
        "synthetic",
        "text-completion-codestral",
        "text-completion-openai",
        "together_ai",
        "topaz",
        "triton",
        "v0",
        "vercel_ai_gateway",
        "vertex_ai",
        "vertex_ai_beta",
        "vllm",
        "volcengine",
        "voyage",
        "wandb",
        "watsonx",
        "watsonx_text",
        "xai",
        "xiaomi_mimo",
        "xinference",
        "zai",
    }
)

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com"
DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Verified official default bases aligned with installed LiteLLM (R2).
# Providers omitted here (e.g. custom, openai_compatible, vllm, hosted_vllm,
# lm_studio) MUST provide an explicit api_base or env base and fail closed otherwise.
VERIFIED_DEFAULT_PROVIDER_BASES: Dict[str, str] = {
    "openai": DEFAULT_OPENAI_BASE,
    "anthropic": DEFAULT_ANTHROPIC_BASE,
    "gemini": DEFAULT_GEMINI_BASE,
    "deepseek": "https://api.deepseek.com/v1",
    "moonshot": "https://api.moonshot.ai/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zai": "https://api.z.ai/api/paas/v4",
    "minimax": "https://api.minimax.io/v1",
    "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
    "ark": "https://ark.cn-beijing.volces.com/api/v3",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "ollama_chat": "http://localhost:11434/v1",
    "groq": "https://api.groq.com/openai/v1",
    "xai": "https://api.x.ai/v1",
    "together_ai": "https://api.together.xyz/v1",
    "fireworks_ai": "https://api.fireworks.ai/inference/v1",
    "mistral": "https://api.mistral.ai/v1",
    "perplexity": "https://api.perplexity.ai",
    "cerebras": "https://api.cerebras.ai/v1",
    "deepinfra": "https://api.deepinfra.com/v1/openai",
}

# Standard provider env base URL lookup order (R2).
PROVIDER_ENV_BASES: Dict[str, Tuple[str, ...]] = {
    "openai": ("OPENAI_API_BASE", "OPENAI_BASE_URL"),
    "anthropic": ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_BASE"),
    "gemini": ("GEMINI_API_BASE", "GOOGLE_API_BASE"),
    "ollama": ("OLLAMA_API_BASE",),
    "ollama_chat": ("OLLAMA_API_BASE",),
    "openrouter": ("OPENROUTER_API_BASE",),
    "deepseek": ("DEEPSEEK_API_BASE",),
    "moonshot": ("MOONSHOT_API_BASE",),
    "dashscope": ("DASHSCOPE_API_BASE",),
    "zai": ("ZAI_API_BASE",),
    "minimax": ("MINIMAX_API_BASE",),
    "volcengine": ("VOLCENGINE_API_BASE",),
    "ark": ("VOLCENGINE_API_BASE",),
    "groq": ("GROQ_API_BASE",),
    "xai": ("XAI_API_BASE",),
    "together_ai": ("TOGETHERAI_API_BASE", "TOGETHER_API_BASE"),
    "fireworks_ai": ("FIREWORKS_AI_API_BASE",),
    "mistral": ("MISTRAL_API_BASE",),
    "perplexity": ("PERPLEXITYAI_API_BASE",),
    "cerebras": ("CEREBRAS_API_BASE",),
    "deepinfra": ("DEEPINFRA_API_BASE",),
}

# Standard LiteLLM-named provider env API key lookup order (R3).
PROVIDER_ENV_KEYS: Dict[str, Tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "moonshot": ("MOONSHOT_API_KEY",),
    "dashscope": ("DASHSCOPE_API_KEY",),
    "zai": ("ZAI_API_KEY",),
    "minimax": ("MINIMAX_API_KEY",),
    "volcengine": ("VOLCENGINE_API_KEY", "ARK_API_KEY"),
    "ark": ("ARK_API_KEY", "VOLCENGINE_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "together_ai": ("TOGETHERAI_API_KEY", "TOGETHER_API_KEY"),
    "fireworks_ai": ("FIREWORKS_AI_API_KEY", "FIREWORKS_API_KEY"),
    "mistral": ("MISTRAL_API_KEY",),
    "perplexity": ("PERPLEXITYAI_API_KEY", "PERPLEXITY_API_KEY"),
    "cerebras": ("CEREBRAS_API_KEY",),
    "deepinfra": ("DEEPINFRA_API_KEY",),
    "ollama": (),
    "ollama_chat": (),
}

ALLOWED_REQUEST_DEFAULT_KEYS: frozenset[str] = frozenset(
    {
        "temperature",
        "top_p",
        "top_k",
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
        "stop",
        "stop_sequences",
        "seed",
        "presence_penalty",
        "frequency_penalty",
        "response_format",
        "reasoning_effort",
        "thinking",
        "thinking_config",
        "generation_config",
        "store",
        "parallel_tool_calls",
        "prompt_cache_key",
        "prompt_cache_retention",
        "stream_options",
        "user",
    }
)

_LOCALHOST_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})
_GEMINI_VERSION_SEGMENT_RE = re.compile(r"/(?:v1|v1beta|v1alpha)(?:/|$)", re.IGNORECASE)


# ============================================================
# Centralized os.environ/VAR Expansion & URL Helpers (R3, R5)
# ============================================================


def find_unresolved_env_var(value: Any) -> Optional[str]:
    """Return the missing env var name if ``value`` is an unset ``os.environ/VAR`` ref."""
    if not isinstance(value, str) or not value.startswith("os.environ/"):
        return None
    env_name = value.split("/", 1)[1].strip()
    if not env_name:
        return "<empty>"
    if not os.getenv(env_name, "").strip():
        return env_name
    return None


def resolve_env_reference(value: Any) -> Any:
    """Resolve ``os.environ/VAR`` syntax used in LiteLLM YAML configs."""
    if isinstance(value, str) and value.startswith("os.environ/"):
        env_name = value.split("/", 1)[1].strip()
        return os.getenv(env_name, "") if env_name else ""
    return value


def resolve_headers_env(headers: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Copy a header mapping while resolving any ``os.environ/VAR`` values."""
    if not isinstance(headers, Mapping):
        return {}
    resolved: Dict[str, str] = {}
    for key, raw_value in headers.items():
        header_name = str(key).strip()
        if not header_name:
            continue
        value = resolve_env_reference(raw_value)
        if value is None:
            continue
        resolved[header_name] = str(value)
    return resolved


def normalize_endpoint_url(url: Any) -> str:
    """Normalize scheme/host case, implicit default port, and trailing slash via ``urlsplit``."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        split = urlsplit(raw)
        port = split.port
    except ValueError:
        return raw.rstrip("/")
    if split.scheme and split.netloc:
        scheme = split.scheme.lower()
        host = (split.hostname or "").lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        default_port = 443 if scheme == "https" else (80 if scheme == "http" else None)
        userinfo = ""
        if split.username is not None:
            userinfo = split.username
            if split.password is not None:
                userinfo = f"{userinfo}:{split.password}"
            userinfo = f"{userinfo}@"
        if host:
            if port is not None and port != default_port:
                normalized_netloc = f"{userinfo}{host}:{port}"
            else:
                normalized_netloc = f"{userinfo}{host}"
        else:
            normalized_netloc = split.netloc.lower()
        normalized_path = split.path.rstrip("/")
        return urlunsplit(
            (
                scheme,
                normalized_netloc,
                normalized_path,
                split.query,
                "",
            )
        )
    return raw.rstrip("/")


def url_origin(url: Optional[str]) -> Optional[Tuple[str, str, int]]:
    """Return canonical ``(scheme, hostname, port)`` origin tuple for a URL, or ``None``."""
    raw = str(url or "").strip()
    if not raw:
        return None
    try:
        split = urlsplit(raw)
        port = split.port
    except ValueError:
        return None
    scheme = split.scheme.lower()
    host = (split.hostname or "").strip().lower()
    if not scheme or not host:
        return None
    if port is None:
        port = 443 if scheme == "https" else (80 if scheme == "http" else 0)
    return (scheme, host, port)


def is_localhost_url(url: Optional[str]) -> bool:
    """Return True when ``url`` points at a loopback/localhost host."""
    origin = url_origin(url)
    return origin is not None and origin[1] in _LOCALHOST_HOSTS


def is_official_openai_url(url: Optional[str]) -> bool:
    """Return True when ``url`` points to official OpenAI API host."""
    origin = url_origin(url)
    return origin is not None and origin[1] == "api.openai.com"


# ============================================================
# R5 Query-Safe Protocol Endpoint URL Normalizers
# ============================================================


def resolve_openai_endpoint_url(
    api_base: str,
    protocol: str,
    *,
    provider: str = "openai",
) -> str:
    """Normalize OpenAI Chat or Responses endpoint URL via ``urlsplit``/``urlunsplit``.

    - Preserves existing query parameters and semicolon path parameters.
    - Normalizes bare Ollama origins (``http://127.0.0.1:11434``) to ``/v1/chat/completions``.
    - Deduplicates ``/chat/completions`` and ``/responses``.
    - Never rewrites an explicit full endpoint of the opposite surface (raises ValueError).
    """
    raw = str(api_base or "").strip()
    if not raw:
        raise ValueError("Missing api_base for OpenAI endpoint resolution")

    split = urlsplit(raw)
    path = split.path.rstrip("/")
    lower_path = path.lower()
    target_suffix = "/responses" if protocol == "openai_responses" else "/chat/completions"

    if protocol == "openai_responses" and lower_path.endswith("/chat/completions"):
        raise ValueError(
            "Explicit /chat/completions endpoint cannot be rewritten to OpenAI Responses surface"
        )
    if protocol == "openai_chat" and lower_path.endswith("/responses"):
        raise ValueError(
            "Explicit /responses endpoint cannot be rewritten to OpenAI Chat Completions surface"
        )

    if provider in {"ollama", "ollama_chat"} and path == "":
        path = "/v1"
        lower_path = "/v1"

    if not lower_path.endswith(target_suffix):
        path = f"{path}{target_suffix}"

    return urlunsplit((split.scheme, split.netloc, path, split.query, split.fragment))


def resolve_anthropic_endpoint_url(api_base: str) -> str:
    """Normalize Anthropic ``/v1/messages`` URL via ``urlsplit``/``urlunsplit``."""
    raw = str(api_base or "").strip()
    if not raw:
        raise ValueError("Missing api_base for Anthropic endpoint resolution")

    split = urlsplit(raw)
    path = split.path.rstrip("/")
    lower_path = path.lower()

    if lower_path.endswith("/v1/messages") or lower_path.endswith("/messages"):
        normalized_path = path
    elif lower_path.endswith("/v1"):
        normalized_path = f"{path}/messages"
    else:
        normalized_path = f"{path}/v1/messages"

    return urlunsplit((split.scheme, split.netloc, normalized_path, split.query, split.fragment))


def resolve_gemini_endpoint_url(
    api_base: str,
    wire_model: str,
    *,
    stream: bool = False,
) -> str:
    """Normalize Gemini REST URL via ``urlsplit``/``urlunsplit`` with query-safe ``alt=sse`` merge.

    Appends ``/v1beta`` for any host (official OR custom reverse proxy) whose path
    lacks ``/v1``, ``/v1beta``, ``/v1alpha``, or ``/models/``. Preserves existing
    query parameters such as ``?key=...``.
    """
    raw = str(api_base or "").strip()
    if not raw:
        raise ValueError("Missing api_base for Gemini endpoint resolution")

    split = urlsplit(raw)
    path = split.path.rstrip("/")
    query_pairs = parse_qsl(split.query, keep_blank_values=True)
    method = ":streamGenerateContent" if stream else ":generateContent"

    lower_path = path.lower()
    matched_method = False
    for existing_suffix in (":streamgeneratecontent", ":generatecontent"):
        if lower_path.endswith(existing_suffix):
            path = path[: -len(existing_suffix)] + method
            matched_method = True
            break

    if not matched_method:
        if "/models/" not in lower_path and not _GEMINI_VERSION_SEGMENT_RE.search(path):
            path = f"{path}/v1beta"
        clean_model = str(wire_model or "").strip().lstrip("/")
        if clean_model and not clean_model.startswith("models/"):
            clean_model = f"models/{clean_model}"
        if clean_model:
            if not path.lower().endswith(f"/{clean_model.lower()}"):
                path = f"{path}/{clean_model}"
        path = f"{path}{method}"

    if stream:
        query_pairs = [(k, v) for k, v in query_pairs if k.lower() != "alt"]
        query_pairs.append(("alt", "sse"))
    else:
        query_pairs = [(k, v) for k, v in query_pairs if not (k.lower() == "alt" and v.lower() == "sse")]

    merged_query = urlencode(query_pairs)
    return urlunsplit((split.scheme, split.netloc, path, merged_query, split.fragment))


# ============================================================
# Protocol, Wire Model, Base URL, and Credential Resolution
# ============================================================


def _normalize_wire_protocol(raw: Optional[str]) -> Optional[str]:
    cleaned = str(raw or "").strip().lower().replace("-", "_")
    if not cleaned:
        return None
    if cleaned in {"openai_chat", "chat", "chat_completions", "chat_completion"}:
        return "openai_chat"
    if cleaned in {"openai_responses", "responses", "response", "responses_api"}:
        return "openai_responses"
    if cleaned in {"anthropic", "anthropic_messages", "messages"}:
        return "anthropic"
    if cleaned in {"gemini", "gemini_generate_content", "google_gemini"}:
        return "gemini"
    return f"__invalid__:{cleaned}"


def _normalize_api_surface(raw: Optional[str]) -> str:
    cleaned = str(raw or "").strip().lower().replace("-", "_")
    if cleaned in {"chat", "chat_completion", "chat_completions", "completions", "openai_chat"}:
        return "chat_completions"
    if cleaned in {"response", "responses", "responses_api", "openai_responses"}:
        return "responses"
    return ""


def _parse_responses_encoding(model: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Decode ``responses/<m>``, ``openai/responses/<m>``, or ``openai_compatible/responses/<m>``.

    Returns ``(provider, wire_model, encoded_surface)`` if matched, else ``(None, None, None)``.
    """
    raw = str(model or "").strip()
    if "/" not in raw:
        return None, None, None
    prefix, rest = raw.split("/", 1)
    prefix_l = prefix.strip().lower()
    rest_clean = rest.strip()
    if prefix_l == "responses" and rest_clean:
        return None, rest_clean, "responses"
    if prefix_l in {"openai", "openai_compatible"} and rest_clean.lower().startswith("responses/"):
        inner = rest_clean.split("/", 1)[1].strip()
        if inner:
            return prefix_l, inner, "responses"
    return None, None, None


def _detect_protocol_from_api_base(api_base: str) -> Optional[str]:
    """R1 step 7: infer protocol from ``api_base`` host/path without corrupting query params."""
    raw = str(api_base or "").strip()
    if not raw:
        return None
    try:
        split = urlsplit(raw)
    except ValueError:
        return "openai_chat"
    host = (split.hostname or "").strip().lower()
    path = (split.path or "").strip().rstrip("/").lower()

    # Gemini OpenAI-compatibility endpoint or any explicit /openai path MUST win over host rules.
    if "/v1beta/openai" in path or path == "/openai" or path.endswith("/openai") or "/openai/" in path:
        return "openai_chat"
    if host == "api.anthropic.com" or host.endswith(".anthropic.com") or path.endswith("/messages"):
        return "anthropic"
    if (
        host == "generativelanguage.googleapis.com"
        or ":generatecontent" in path
        or ":streamgeneratecontent" in path
    ):
        return "gemini"
    if path.endswith("/responses"):
        return "openai_responses"
    return "openai_chat"


def _resolve_provider_env_base(provider: str) -> str:
    env_names = list(PROVIDER_ENV_BASES.get(provider, ()))
    if provider and re.fullmatch(r"[a-z0-9_]+", provider):
        generic_env = f"{provider.upper()}_API_BASE"
        if generic_env not in env_names:
            env_names.append(generic_env)
    for env_key in env_names:
        val = os.getenv(env_key, "").strip()
        if val:
            return val
    return ""


def _resolve_provider_env_key(provider: str) -> str:
    for env_key in PROVIDER_ENV_KEYS.get(provider, ()):
        val = os.getenv(env_key, "").strip()
        if val:
            return val
    return ""


def _resolve_wire_model(
    raw_model: str,
    *,
    effective_provider: str,
    custom_llm_provider: str,
    channel_protocol: str,
    protocol: str,
    has_custom_api_base: bool,
) -> str:
    """R4 opaque wire model resolution: strip ONLY one explicit canonical transport prefix."""
    model = str(raw_model or "").strip()
    if not model:
        return ""

    # Decode explicit responses encoding first.
    _enc_prov, enc_wire, enc_surface = _parse_responses_encoding(model)
    if enc_surface == "responses" and enc_wire:
        return enc_wire

    if "/" not in model:
        return model

    prefix, remainder = model.split("/", 1)
    prefix_l = prefix.strip().lower()
    remainder_clean = remainder.strip()
    if not remainder_clean:
        return model

    # OpenRouter special case matching LiteLLM: keep ``openrouter/auto`` intact,
    # strip only the single leading ``openrouter/`` for ``openrouter/anthropic/...``.
    if prefix_l == "openrouter":
        if remainder_clean.lower() == "auto":
            return model
        return remainder_clean

    # If custom_llm_provider matches the leading segment, strip that single transport prefix.
    if custom_llm_provider and prefix_l == custom_llm_provider:
        return remainder_clean

    # On an OpenAI-compatible relay (explicit openai/custom channel or custom_llm_provider=openai),
    # strip ONLY a leading openai/openai_compatible/custom transport prefix so vendor-qualified
    # relay IDs such as ``anthropic/claude-sonnet-4`` or ``Qwen/Qwen3-235B`` stay 100% opaque.
    if custom_llm_provider in {"openai", "openai_compatible", "custom", "custom_openai", "openai_like"} or (
        channel_protocol == "openai" and protocol in {"openai_chat", "openai_responses"}
    ):
        if prefix_l in {"openai", "openai_compatible", "custom", "custom_openai", "openai_like"}:
            return remainder_clean
        return model

    # Strip canonical native wire prefix ONLY when it matches the resolved protocol family.
    if protocol == "anthropic" and prefix_l in NATIVE_ANTHROPIC_WIRE_PROVIDERS:
        return remainder_clean
    if protocol == "gemini" and prefix_l in NATIVE_GEMINI_WIRE_PROVIDERS:
        return remainder_clean
    if protocol in {"openai_chat", "openai_responses"} and prefix_l in NATIVE_OPENAI_WIRE_PROVIDERS:
        return remainder_clean

    # Never strip org prefixes (Qwen/, deepseek-ai/, zhipu/, glm/, ark/, siliconflow/, google/, claude/).
    del effective_provider, has_custom_api_base
    return model


def _infer_auth_header_name(
    protocol: str,
    api_key: str,
    extra_headers: Mapping[str, str],
    endpoint_url: str,
) -> str:
    if has_header_case_insensitive(extra_headers, "authorization"):
        return "Authorization"
    if protocol == "anthropic":
        if has_header_case_insensitive(extra_headers, "x-api-key") or api_key:
            return "x-api-key"
        return ""
    if protocol == "gemini":
        if has_header_case_insensitive(extra_headers, "x-goog-api-key"):
            return "x-goog-api-key"
        # Respect explicit ?key= query auth without injecting duplicate auth header if no key.
        query_keys = {k.lower() for k, _ in parse_qsl(urlsplit(endpoint_url).query, keep_blank_values=True)}
        if api_key and "key" not in query_keys:
            return "x-goog-api-key"
        if "key" in query_keys:
            return "query:key"
        return ""
    return "Authorization" if api_key else ""


def resolve_deployment(
    entry_or_model: Union[Mapping[str, Any], str],
    *,
    deployment_id: str = "",
    alias: Optional[str] = None,
    api_base: Any = None,
    base_url: Any = None,
    api_key: Any = None,
    custom_llm_provider: Optional[str] = None,
    wire_protocol: Optional[str] = None,
    api_surface: Optional[str] = None,
    channel_protocol: Optional[str] = None,
    extra_headers: Optional[Mapping[str, Any]] = None,
    extra_body: Optional[Mapping[str, Any]] = None,
    model_info: Optional[Mapping[str, Any]] = None,
    client: Any = None,
    timeout: Any = None,
    priority: Optional[int] = None,
    params: Optional[Mapping[str, Any]] = None,
) -> Union[DeploymentSpec, Unsupported]:
    """Resolve a Router ``model_list`` entry or direct call kwargs into ``DeploymentSpec | Unsupported``.

    This is the single shared resolver used by analyzer, Agent, Vision, screening,
    and Test Channel.
    """
    raw_params: Dict[str, Any] = {}
    raw_info: Dict[str, Any] = {}
    resolved_alias = str(alias or "").strip()
    raw_model = ""

    if isinstance(entry_or_model, Mapping):
        entry_params = entry_or_model.get("litellm_params")
        if isinstance(entry_params, Mapping):
            raw_params.update(entry_params)
        entry_info = entry_or_model.get("model_info")
        if isinstance(entry_info, Mapping):
            raw_info.update(copy.deepcopy(dict(entry_info)))
        resolved_alias = resolved_alias or str(entry_or_model.get("model_name") or "").strip()
        raw_model = str(raw_params.get("model") or resolved_alias).strip()
    else:
        raw_model = str(entry_or_model or "").strip()
        if not resolved_alias:
            resolved_alias = raw_model

    if isinstance(params, Mapping):
        raw_params.update(params)
    if isinstance(model_info, Mapping):
        raw_info.update(copy.deepcopy(dict(model_info)))

    # Apply explicit keyword overrides on top of raw_params.
    if api_base is not None:
        raw_params["api_base"] = api_base
    if base_url is not None:
        raw_params["base_url"] = base_url
    if api_key is not None:
        raw_params["api_key"] = api_key
    if custom_llm_provider is not None:
        raw_params["custom_llm_provider"] = custom_llm_provider
    if wire_protocol is not None:
        raw_params["wire_protocol"] = wire_protocol
    if api_surface is not None:
        raw_params["api_surface"] = api_surface
    if extra_headers is not None:
        raw_params["extra_headers"] = extra_headers
    if extra_body is not None:
        raw_params["extra_body"] = extra_body
    if client is not None:
        raw_params["client"] = client
    if timeout is not None:
        raw_params["timeout"] = timeout

    if not raw_model:
        raw_model = str(raw_params.get("model") or resolved_alias).strip()
    if not resolved_alias:
        resolved_alias = raw_model

    # Fail closed on unresolved os.environ/VAR endpoint references (Codex #35 P0-3).
    unresolved_marker = str(raw_info.get("_dsa_unresolved_endpoint_env") or "").strip()
    if unresolved_marker:
        return Unsupported(
            reason="unresolved_endpoint_env",
            provider="unknown",
            detail=f"Endpoint environment variable is unset ({unresolved_marker})",
            model=raw_model,
        )
    for endpoint_key in ("base_url", "api_base"):
        missing_var = find_unresolved_env_var(raw_params.get(endpoint_key))
        if missing_var is not None:
            return Unsupported(
                reason="unresolved_endpoint_env",
                provider="unknown",
                detail=f"{endpoint_key} environment variable '{missing_var}' is not set",
                model=raw_model,
            )

    # Check conflicting explicit api_base vs base_url (Codex #35 P0-3 + P1-3 urlsplit).
    has_explicit_base_url = "base_url" in raw_params and raw_params.get("base_url") is not None
    resolved_base_url_val = (
        str(resolve_env_reference(raw_params.get("base_url")) or "").strip()
        if has_explicit_base_url
        else ""
    )
    resolved_api_base_val = str(resolve_env_reference(raw_params.get("api_base")) or "").strip()
    if (
        has_explicit_base_url
        and resolved_api_base_val
        and normalize_endpoint_url(resolved_base_url_val)
        != normalize_endpoint_url(resolved_api_base_val)
    ):
        return Unsupported(
            reason="conflicting_api_base",
            provider="unknown",
            detail="Deployment has conflicting api_base and base_url values",
            model=raw_model,
        )

    client_api_key, client_base_url, _client_http = extract_client_overrides(raw_params)
    explicit_api_base = (
        resolved_base_url_val
        if has_explicit_base_url
        else (resolved_api_base_val or str(client_base_url or "").strip())
    )

    # Extract provider hints & metadata.
    eff_custom_provider = str(resolve_env_reference(raw_params.get("custom_llm_provider")) or "").strip().lower()
    eff_channel_protocol = str(
        channel_protocol
        if channel_protocol is not None
        else (
            raw_info.get("dsa_channel_protocol")
            or resolve_env_reference(raw_params.get("dsa_channel_protocol"))
            or ""
        )
    ).strip().lower()
    raw_wire_protocol = str(resolve_env_reference(raw_params.get("wire_protocol")) or "").strip()
    raw_surface = str(
        raw_info.get("dsa_api_surface")
        or resolve_env_reference(raw_params.get("api_surface"))
        or ""
    ).strip()
    eff_surface = _normalize_api_surface(raw_surface)

    model_prefix = raw_model.split("/", 1)[0].strip().lower() if "/" in raw_model else ""
    all_native_wire_providers = (
        NATIVE_OPENAI_WIRE_PROVIDERS | NATIVE_ANTHROPIC_WIRE_PROVIDERS | NATIVE_GEMINI_WIRE_PROVIDERS
    )

    # ------------------------------------------------------------
    # R1 Step 1: Cloud-IAM fallback providers FIRST (before wire_protocol!)
    # ------------------------------------------------------------
    for candidate_prov in (eff_custom_provider, eff_channel_protocol, model_prefix):
        if candidate_prov and candidate_prov in FALLBACK_ONLY_PROVIDERS:
            return Unsupported(
                reason="fallback_only_provider",
                provider=candidate_prov,
                detail=f"Provider '{candidate_prov}' requires LiteLLM/cloud-IAM fallback",
                model=raw_model,
            )

    # ------------------------------------------------------------
    # R1 Steps 2-8: Deterministic Protocol Precedence
    # ------------------------------------------------------------
    enc_provider, _enc_wire, enc_surface = _parse_responses_encoding(raw_model)
    explicit_base_path = ""
    if explicit_api_base:
        try:
            explicit_base_path = (urlsplit(explicit_api_base).path or "").rstrip("/").lower()
        except ValueError:
            explicit_base_path = ""

    # Enforce provider/prefix/channel identity independently of api_surface/wire_protocol so
    # unknown non-OpenAI providers (e.g. replicate/internal-model + api_surface, or bare model
    # + dsa_channel_protocol="replicate" + wire_protocol="openai_chat" without api_base) NEVER
    # fall through to api.openai.com (P0-1).
    if eff_custom_provider and eff_custom_provider not in (all_native_wire_providers | {"ark"}):
        if not raw_wire_protocol:
            return Unsupported(
                reason="unsupported_custom_provider",
                provider=eff_custom_provider,
                detail=f"Unsupported custom_llm_provider '{eff_custom_provider}'",
                model=raw_model,
            )

    if eff_channel_protocol and eff_channel_protocol not in (all_native_wire_providers | {"ark"}):
        if not explicit_api_base:
            return Unsupported(
                reason="unsupported_channel_protocol",
                provider=eff_channel_protocol,
                detail=(
                    f"Channel protocol '{eff_channel_protocol}' is unrecognized and requires "
                    "an explicit api_base"
                ),
                model=raw_model,
            )

    if (
        "/" in raw_model
        and enc_surface is None
        and not eff_custom_provider
        and not explicit_api_base
        and model_prefix not in all_native_wire_providers
    ):
        return Unsupported(
            reason="unknown_provider_without_api_base",
            provider=model_prefix or "unknown",
            detail=(
                f"Model '{raw_model}' has non-canonical prefix '{model_prefix}' "
                "and no api_base is configured"
            ),
            model=raw_model,
        )

    protocol: Optional[str] = None

    # Step 2: Explicit wire_protocol
    norm_wp = _normalize_wire_protocol(raw_wire_protocol)
    if norm_wp is not None:
        if norm_wp.startswith("__invalid__:"):
            return Unsupported(
                reason="unsupported_wire_protocol",
                provider=eff_custom_provider or model_prefix or "unknown",
                detail=f"Unsupported wire_protocol '{raw_wire_protocol}'",
                model=raw_model,
            )
        protocol = norm_wp

    # Step 3: model_info.dsa_api_surface / api_surface
    if protocol is None and eff_surface:
        if eff_surface == "responses":
            protocol = "openai_responses"
        elif eff_surface == "chat_completions":
            protocol = "openai_chat"

    # Step 4: responses/ encoding or explicit /responses path
    if protocol is None:
        if enc_surface == "responses" or explicit_base_path.endswith("/responses"):
            protocol = "openai_responses"

    # Step 5: custom_llm_provider
    if protocol is None and eff_custom_provider:
        if eff_custom_provider in NATIVE_ANTHROPIC_WIRE_PROVIDERS:
            protocol = "anthropic"
        elif eff_custom_provider in NATIVE_GEMINI_WIRE_PROVIDERS:
            protocol = "gemini"
        elif eff_custom_provider in NATIVE_OPENAI_WIRE_PROVIDERS or eff_custom_provider == "ark":
            protocol = "openai_chat"
        else:
            return Unsupported(
                reason="unsupported_custom_provider",
                provider=eff_custom_provider,
                detail=f"Unsupported custom_llm_provider '{eff_custom_provider}'",
                model=raw_model,
            )

    # Step 6: canonical wire provider prefix (NEVER org prefixes qwen/glm/zhipu/ark/siliconflow/google/claude!)
    if protocol is None and model_prefix:
        if model_prefix in NATIVE_ANTHROPIC_WIRE_PROVIDERS:
            # If channel_protocol explicitly declares openai (e.g. OpenAI relay serving anthropic/...),
            # keep openai_chat instead of misrouting to Anthropic.
            if eff_channel_protocol == "openai" and explicit_api_base:
                protocol = "openai_chat"
            else:
                protocol = "anthropic"
        elif model_prefix in NATIVE_GEMINI_WIRE_PROVIDERS:
            if eff_channel_protocol == "openai" and explicit_api_base:
                protocol = "openai_chat"
            else:
                protocol = "gemini"
        elif model_prefix in NATIVE_OPENAI_WIRE_PROVIDERS:
            protocol = "openai_chat"

    # Also honor explicit channel_protocol if canonical and still unresolved.
    if protocol is None and eff_channel_protocol:
        if eff_channel_protocol in NATIVE_ANTHROPIC_WIRE_PROVIDERS:
            protocol = "anthropic"
        elif eff_channel_protocol in NATIVE_GEMINI_WIRE_PROVIDERS:
            protocol = "gemini"
        elif eff_channel_protocol in NATIVE_OPENAI_WIRE_PROVIDERS:
            protocol = "openai_chat"

    # Step 7: api_base host/path detection (BEFORE bare model name inference so
    # OPENAI_BASE_URL + OPENAI_MODEL=claude-sonnet-4-6 routes to openai_chat!)
    if protocol is None and explicit_api_base:
        protocol = _detect_protocol_from_api_base(explicit_api_base)

    # Step 8: bare model fallback (no '/' prefix and no api_base)
    if protocol is None:
        if "/" in raw_model:
            # Unknown non-canonical prefix (e.g. Qwen/Qwen3-235B or foo/bar) without api_base -> fail closed!
            return Unsupported(
                reason="unknown_provider_without_api_base",
                provider=model_prefix or "unknown",
                detail=(
                    f"Model '{raw_model}' has non-canonical prefix '{model_prefix}' "
                    "and no api_base is configured"
                ),
                model=raw_model,
            )
        lowered_bare = raw_model.lower()
        if lowered_bare.startswith("claude"):
            protocol = "anthropic"
        elif lowered_bare.startswith("gemini"):
            protocol = "gemini"
        else:
            protocol = "openai_chat"

    # Determine canonical effective provider for default base/env key/telemetry lookup.
    if eff_custom_provider:
        effective_provider = eff_custom_provider
    elif enc_provider:
        effective_provider = enc_provider
    elif model_prefix in all_native_wire_providers:
        if eff_channel_protocol == "openai" and protocol in {"openai_chat", "openai_responses"} and explicit_api_base:
            effective_provider = "openai"
        else:
            effective_provider = model_prefix
    elif eff_channel_protocol in (all_native_wire_providers | {"ark"}):
        effective_provider = eff_channel_protocol
    elif protocol == "anthropic":
        effective_provider = "anthropic"
    elif protocol == "gemini":
        effective_provider = "gemini"
    elif "/" not in raw_model and raw_model.lower().startswith("deepseek"):
        effective_provider = "deepseek"
    elif explicit_api_base:
        effective_provider = "openai"
    else:
        effective_provider = "openai"

    # ------------------------------------------------------------
    # R2 Fail-Closed Endpoint Resolution
    # ------------------------------------------------------------
    env_base = _resolve_provider_env_base(effective_provider)
    if explicit_api_base:
        resolved_base = explicit_api_base
        base_source = "explicit"
    elif env_base:
        resolved_base = env_base
        base_source = "env"
    elif effective_provider in VERIFIED_DEFAULT_PROVIDER_BASES:
        resolved_base = VERIFIED_DEFAULT_PROVIDER_BASES[effective_provider]
        base_source = "default"
    elif protocol == "anthropic" and effective_provider == "anthropic":
        resolved_base = DEFAULT_ANTHROPIC_BASE
        base_source = "default"
    elif protocol == "gemini" and effective_provider == "gemini":
        resolved_base = DEFAULT_GEMINI_BASE
        base_source = "default"
    else:
        # Fail closed BEFORE any network I/O! NEVER default non-openai to api.openai.com.
        return Unsupported(
            reason="missing_api_base",
            provider=effective_provider,
            detail=(
                f"Provider '{effective_provider}' requires an explicit api_base "
                "(no verified default base URL)"
            ),
            model=raw_model,
        )

    # P0-1: Guard against mismatched official default host in ALL protocol directions
    # (anthropic->anthropic, gemini->gemini, OpenAI/compat->openai_chat/openai_responses).
    if base_source == "default":
        default_compatible = (
            (effective_provider == "anthropic" and protocol == "anthropic")
            or (effective_provider == "gemini" and protocol == "gemini")
            or (
                effective_provider not in {"anthropic", "gemini"}
                and protocol in {"openai_chat", "openai_responses"}
            )
        )
        if not default_compatible:
            return Unsupported(
                reason="endpoint_surface_mismatch",
                provider=effective_provider,
                detail=(
                    f"Official '{effective_provider}' default endpoint does not serve '{protocol}' "
                    "without an explicit api_base"
                ),
                model=raw_model,
            )

    # ------------------------------------------------------------
    # R4 Opaque Wire Model
    # ------------------------------------------------------------
    wire_model = _resolve_wire_model(
        raw_model,
        effective_provider=effective_provider,
        custom_llm_provider=eff_custom_provider,
        channel_protocol=eff_channel_protocol,
        protocol=protocol,
        has_custom_api_base=bool(explicit_api_base),
    )

    # ------------------------------------------------------------
    # R5 Query-Safe Endpoint URL Normalization
    # ------------------------------------------------------------
    try:
        if protocol == "anthropic":
            endpoint_url = resolve_anthropic_endpoint_url(resolved_base)
        elif protocol == "gemini":
            endpoint_url = resolve_gemini_endpoint_url(resolved_base, wire_model, stream=False)
        else:
            endpoint_url = resolve_openai_endpoint_url(
                resolved_base,
                protocol,
                provider=effective_provider,
            )
    except ValueError as exc:
        return Unsupported(
            reason="endpoint_surface_mismatch",
            provider=effective_provider,
            detail=str(exc),
            model=raw_model,
        )

    # ------------------------------------------------------------
    # R3 Origin-Bound Credentials & Headers
    # ------------------------------------------------------------
    raw_api_key_present = "api_key" in raw_params and raw_params.get("api_key") is not None
    raw_api_key_unresolved = find_unresolved_env_var(raw_params.get("api_key"))
    resolved_explicit_key = (
        ""
        if raw_api_key_unresolved is not None
        else str(resolve_env_reference(raw_params.get("api_key")) or "").strip()
    )
    explicit_empty_key = raw_api_key_present and not resolved_explicit_key

    allow_keyless = effective_provider in {"ollama", "ollama_chat"} or is_localhost_url(resolved_base)
    target_origin = url_origin(resolved_base)
    client_origin = url_origin(client_base_url) if client_base_url else None

    has_caller_explicit_base = has_explicit_base_url or bool(resolved_api_base_val)
    effective_api_key = ""
    if resolved_explicit_key:
        effective_api_key = resolved_explicit_key
    elif client_api_key and (
        (client_origin is not None and target_origin is not None and client_origin == target_origin)
        or (client_origin is None and not has_caller_explicit_base)
    ):
        # P0-2a / P0-3c: client_api_key is strictly bound to client.base_url's origin, and an
        # originless client never binds its key to an unrelated explicit api_base.
        effective_api_key = client_api_key
    elif not explicit_empty_key and raw_api_key_unresolved is None:
        # P0-2b: Origin-bound env key fallback. When env_base is configured, the provider
        # env key belongs ONLY to env_base's origin (never also to official default origin).
        allowed_origins = set()
        if env_base:
            env_orig = url_origin(env_base)
            if env_orig is not None:
                allowed_origins.add(env_orig)
        else:
            default_base = VERIFIED_DEFAULT_PROVIDER_BASES.get(effective_provider)
            if default_base:
                def_orig = url_origin(default_base)
                if def_orig is not None:
                    allowed_origins.add(def_orig)
        if base_source in {"env", "default"} or (target_origin is not None and target_origin in allowed_origins):
            effective_api_key = _resolve_provider_env_key(effective_provider)

    # Resolve headers with os.environ/VAR expansion.
    resolved_headers: Dict[str, str] = {}
    for hdr_key in ("extra_headers", "headers", "default_headers"):
        raw_hdrs = raw_params.get(hdr_key)
        if isinstance(raw_hdrs, Mapping):
            merge_header_overrides(resolved_headers, {hdr_key: resolve_headers_env(raw_hdrs)})

    raw_extra_body = raw_params.get("extra_body")
    resolved_extra_body = (
        copy.deepcopy(dict(raw_extra_body)) if isinstance(raw_extra_body, Mapping) else {}
    )

    # R8: Carry YAML/deployment allowlisted generation defaults into request_defaults.
    request_defaults: Dict[str, Any] = {}
    for k, v in raw_params.items():
        k_lower = str(k).strip().lower()
        if k_lower in ALLOWED_REQUEST_DEFAULT_KEYS and v is not None:
            resolved_v = resolve_env_reference(v) if isinstance(v, str) else copy.deepcopy(v)
            if k_lower in {"store", "parallel_tool_calls"}:
                try:
                    resolved_v = parse_strict_bool(
                        resolved_v,
                        field_name=str(k),
                        provider=effective_provider,
                    )
                except NativeBadRequestError as exc:
                    # P1-5: Invalid deployment boolean fails closed as typed config error.
                    return Unsupported(
                        reason="invalid_deployment_param",
                        provider=effective_provider,
                        detail=str(exc),
                        model=raw_model,
                    )
            request_defaults[k] = resolved_v

    # P2: Default priority is 0 unless model_info.priority / order explicitly specified.
    if priority is not None:
        resolved_priority = int(priority)
    else:
        raw_priority = raw_info.get(
            "priority",
            raw_info.get("order", raw_params.get("priority", raw_params.get("order", 0))),
        )
        try:
            resolved_priority = int(raw_priority) if raw_priority is not None else 0
        except (TypeError, ValueError):
            resolved_priority = 0

    raw_timeout = raw_params.get("timeout")
    resolved_timeout: Optional[float] = None
    if raw_timeout is not None and raw_timeout != "":
        try:
            parsed_timeout = float(raw_timeout)
            if math.isfinite(parsed_timeout) and parsed_timeout > 0:
                resolved_timeout = parsed_timeout
        except (TypeError, ValueError):
            resolved_timeout = None

    auth_header_name = _infer_auth_header_name(
        protocol,
        effective_api_key,
        resolved_headers,
        endpoint_url,
    )

    return DeploymentSpec(
        alias=resolved_alias,
        wire_model=wire_model,
        channel_protocol=eff_channel_protocol,
        wire_protocol=raw_wire_protocol,
        custom_llm_provider=eff_custom_provider,
        api_surface=eff_surface,
        api_base=resolved_base,
        api_key=effective_api_key,
        extra_headers=resolved_headers,
        extra_body=resolved_extra_body,
        request_defaults=request_defaults,
        priority=resolved_priority,
        timeout=resolved_timeout,
        model_info=raw_info,
        deployment_id=deployment_id or resolved_alias,
        protocol=protocol,
        provider=effective_provider,
        endpoint_url=endpoint_url,
        auth_header_name=auth_header_name,
        allow_keyless=allow_keyless,
    )
