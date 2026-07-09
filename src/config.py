# -*- coding: utf-8 -*-
"""
===================================
台股 / 美股自選股智慧分析系統 - 配置管理模組
===================================

職責：
1. 使用單例模式管理全域性配置
2. 從 .env 檔案載入敏感配置
3. 提供型別安全的配置訪問介面
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import unquote, urlparse
from dotenv import load_dotenv, dotenv_values
from dataclasses import dataclass, field

from src.report_language import (
    is_supported_report_language_value,
    normalize_report_language,
)
from src.notification_routing import parse_notification_route_channels
from src.notification_noise import (
    NOTIFICATION_SEVERITIES,
    is_supported_notification_severity,
    parse_notification_quiet_hours,
    validate_notification_timezone,
)
from src.llm import generation_params as llm_generation_params

logger = logging.getLogger(__name__)

DEFAULT_ALPHASIFT_INSTALL_SPEC = (
    "git+https://github.com/ZhuLinsen/alphasift.git@b2ca66dd47001b9a09890cfe21c2b18c7219ccf5"
)


@dataclass
class ConfigIssue:
    """Structured configuration validation issue with a severity level.

    Attributes:
        severity: One of "error", "warning", or "info".
        message:  Human-readable description of the issue.
        field:    The environment variable / config field name most relevant to
                  this issue (empty string when not applicable).
    """

    severity: Literal["error", "warning", "info"]
    message: str
    field: str = ""

    def __str__(self) -> str:  # noqa: D105
        return self.message


_MANAGED_LITELLM_KEY_PROVIDERS = {"gemini", "vertex_ai", "anthropic", "openai", "deepseek"}
SUPPORTED_LLM_CHANNEL_PROTOCOLS = ("openai", "anthropic", "gemini", "vertex_ai", "deepseek", "ollama")
_FALSEY_ENV_VALUES = {"0", "false", "no", "off"}
# Fallback defaults used when ANSPIRE_API_KEYS is reused as legacy OpenAI-compatible source.
# These are compatibility examples; actual availability should be validated by Anspire console/model entitlement.
ANSPIRE_LLM_BASE_URL_DEFAULT = "https://open-gateway.anspire.cn/v6"
ANSPIRE_LLM_MODEL_DEFAULT = "Doubao-Seed-2.0-lite"


def _has_ntfy_topic_endpoint(value: Optional[str]) -> bool:
    """Return whether an ntfy URL points at a concrete topic endpoint."""
    raw_url = (value or "").strip()
    if not raw_url:
        return False
    parsed = urlparse(raw_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return False
    return any(unquote(segment).strip() for segment in parsed.path.split("/") if segment)


def _has_gotify_base_url(value: Optional[str]) -> bool:
    """Return whether a Gotify URL points at a server base URL, not /message."""
    raw_url = (value or "").strip().rstrip("/")
    if not raw_url:
        return False
    parsed = urlparse(raw_url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.query or parsed.fragment:
        return False
    path_segments = [segment for segment in parsed.path.split("/") if segment]
    return not (path_segments and path_segments[-1].lower() == "message")


AGENT_MAX_STEPS_DEFAULT = 10
FUNDAMENTAL_STAGE_TIMEOUT_SECONDS_DEFAULT = 8.0
NEWS_STRATEGY_WINDOWS: Dict[str, int] = {
    "ultra_short": 1,
    "short": 3,
    "medium": 7,
    "long": 30,
}


@dataclass(frozen=True)
class AgentContextCompressionPreset:
    """Preset values for visible chat history compression."""

    trigger_tokens: int
    protected_turns: int
    summary_target_tokens: int
    # P1 reserves this budget for future prompt-size controls; it is not
    # enforced by the current rolling-summary state table.
    history_budget_tokens: int


AGENT_CONTEXT_COMPRESSION_DEFAULT_PROFILE = "balanced"
AGENT_CONTEXT_COMPRESSION_PROFILES: Dict[str, AgentContextCompressionPreset] = {
    "cost": AgentContextCompressionPreset(
        trigger_tokens=6000,
        protected_turns=2,
        summary_target_tokens=900,
        history_budget_tokens=4000,
    ),
    "balanced": AgentContextCompressionPreset(
        trigger_tokens=12000,
        protected_turns=4,
        summary_target_tokens=1500,
        history_budget_tokens=8000,
    ),
    "long_context_raw_first": AgentContextCompressionPreset(
        trigger_tokens=24000,
        protected_turns=6,
        summary_target_tokens=2600,
        history_budget_tokens=14000,
    ),
}


def parse_env_bool(value: Optional[str], default: bool = False) -> bool:
    """Parse common truthy/falsey environment-style values."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized not in _FALSEY_ENV_VALUES


def parse_env_int(
    value: Optional[str],
    default: int,
    *,
    field_name: str,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    """Parse an integer env value with warning + fallback semantics."""
    raw_value = value
    if raw_value is None or not str(raw_value).strip():
        parsed = int(default)
    else:
        try:
            parsed = int(str(raw_value).strip())
        except (TypeError, ValueError):
            logger.warning(
                "%s=%r is not a valid integer; falling back to %s",
                field_name,
                raw_value,
                default,
            )
            parsed = int(default)

    if minimum is not None and parsed < minimum:
        logger.warning(
            "%s=%r is below minimum %s; clamping to %s",
            field_name,
            parsed,
            minimum,
            minimum,
        )
        parsed = minimum
    if maximum is not None and parsed > maximum:
        logger.warning(
            "%s=%r is above maximum %s; clamping to %s",
            field_name,
            parsed,
            maximum,
            maximum,
        )
        parsed = maximum
    return parsed


def parse_env_float(
    value: Optional[str],
    default: float,
    *,
    field_name: str,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    """Parse a float env value with warning + fallback semantics."""
    raw_value = value
    if raw_value is None or not str(raw_value).strip():
        parsed = float(default)
    else:
        try:
            parsed = float(str(raw_value).strip())
        except (TypeError, ValueError):
            logger.warning(
                "%s=%r is not a valid number; falling back to %s",
                field_name,
                raw_value,
                default,
            )
            parsed = float(default)

    if minimum is not None and parsed < minimum:
        logger.warning(
            "%s=%r is below minimum %s; clamping to %s",
            field_name,
            parsed,
            minimum,
            minimum,
        )
        parsed = minimum
    if maximum is not None and parsed > maximum:
        logger.warning(
            "%s=%r is above maximum %s; clamping to %s",
            field_name,
            parsed,
            maximum,
            maximum,
        )
        parsed = maximum
    return parsed


def normalize_news_strategy_profile(value: Optional[str]) -> str:
    """Normalize news strategy profile to known values."""
    candidate = (value or "short").strip().lower()
    return candidate if candidate in NEWS_STRATEGY_WINDOWS else "short"


def resolve_news_window_days(news_max_age_days: int, news_strategy_profile: Optional[str]) -> int:
    """Resolve effective news window days from profile and global max-age."""
    profile = normalize_news_strategy_profile(news_strategy_profile)
    profile_days = NEWS_STRATEGY_WINDOWS.get(profile, NEWS_STRATEGY_WINDOWS["short"])
    return max(1, min(max(1, int(news_max_age_days)), profile_days))


def normalize_agent_context_compression_profile(value: Optional[str]) -> str:
    """Normalize visible-chat context compression profile values."""
    candidate = (value or AGENT_CONTEXT_COMPRESSION_DEFAULT_PROFILE).strip().lower()
    if candidate in AGENT_CONTEXT_COMPRESSION_PROFILES:
        return candidate
    logger.warning(
        "Invalid AGENT_CONTEXT_COMPRESSION_PROFILE=%r; falling back to %s",
        value,
        AGENT_CONTEXT_COMPRESSION_DEFAULT_PROFILE,
    )
    return AGENT_CONTEXT_COMPRESSION_DEFAULT_PROFILE


def get_agent_context_compression_preset(profile: Optional[str]) -> AgentContextCompressionPreset:
    """Return the preset for a normalized profile, falling back to balanced."""
    normalized = normalize_agent_context_compression_profile(profile)
    return AGENT_CONTEXT_COMPRESSION_PROFILES[normalized]


def parse_agent_context_compression_int(
    value: Optional[str],
    default: int,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    """Parse compression integers; empty/invalid/out-of-range values follow preset defaults."""
    raw_value = value
    if raw_value is None or not str(raw_value).strip():
        return int(default)
    try:
        parsed = int(str(raw_value).strip())
    except (TypeError, ValueError):
        logger.warning(
            "%s=%r is not a valid integer; falling back to preset default %s",
            field_name,
            raw_value,
            default,
        )
        return int(default)
    if parsed < minimum or parsed > maximum:
        logger.warning(
            "%s=%r is outside supported range [%s, %s]; falling back to preset default %s",
            field_name,
            parsed,
            minimum,
            maximum,
            default,
        )
        return int(default)
    return parsed


def canonicalize_llm_channel_protocol(value: Optional[str]) -> str:
    """Normalize a protocol label into a LiteLLM provider identifier."""
    candidate = (value or "").strip().lower().replace("-", "_")
    aliases = {
        "openai_compatible": "openai",
        "openai_compat": "openai",
        "claude": "anthropic",
        "google": "gemini",
        "vertex": "vertex_ai",
        "vertexai": "vertex_ai",
    }
    return aliases.get(candidate, candidate)


def resolve_llm_channel_protocol(
    protocol: Optional[str],
    *,
    base_url: Optional[str] = None,
    models: Optional[List[str]] = None,
    channel_name: Optional[str] = None,
) -> str:
    """Resolve the effective protocol for a channel."""
    explicit = canonicalize_llm_channel_protocol(protocol)
    if explicit in SUPPORTED_LLM_CHANNEL_PROTOCOLS:
        return explicit

    for model in models or []:
        if "/" not in model:
            continue
        prefix = canonicalize_llm_channel_protocol(model.split("/", 1)[0])
        if prefix in SUPPORTED_LLM_CHANNEL_PROTOCOLS:
            return prefix

    # Infer from channel name (e.g. "deepseek" -> deepseek, "gemini" -> gemini)
    if channel_name:
        name_protocol = canonicalize_llm_channel_protocol(channel_name)
        if name_protocol in SUPPORTED_LLM_CHANNEL_PROTOCOLS:
            return name_protocol

    if base_url:
        parsed = urlparse(base_url)
        if parsed.hostname in {"127.0.0.1", "localhost", "0.0.0.0"}:
            # Default to openai for local servers (vLLM, LM Studio, LocalAI, etc.).
            # Ollama users should set PROTOCOL=ollama explicitly or name the channel "ollama".
            return "openai"
        return "openai"

    return ""


def channel_allows_empty_api_key(protocol: Optional[str], base_url: Optional[str]) -> bool:
    """Return True when a channel can run without an API key."""
    resolved_protocol = resolve_llm_channel_protocol(protocol, base_url=base_url)
    if resolved_protocol == "ollama":
        return True
    parsed = urlparse(base_url or "")
    return parsed.hostname in {"127.0.0.1", "localhost", "0.0.0.0"}


def normalize_llm_channel_model(model: str, protocol: Optional[str], base_url: Optional[str] = None) -> str:
    """Attach a provider prefix when the model omits it."""
    normalized_model = model.strip()
    if not normalized_model:
        return normalized_model

    resolved_protocol = resolve_llm_channel_protocol(protocol, base_url=base_url, models=[normalized_model])

    if "/" in normalized_model:
        # The model already has a slash, e.g. 'deepseek-ai/DeepSeek-V3'.
        # Check if the prefix is a known LiteLLM provider; if so, keep it.
        # Otherwise (e.g. HuggingFace-style IDs on SiliconFlow), prepend
        # the resolved protocol so LiteLLM routes via the correct handler.
        raw_prefix, remainder = normalized_model.split("/", 1)
        prefix = raw_prefix.lower()
        canonical_prefix = canonicalize_llm_channel_protocol(prefix)
        known_providers = _MANAGED_LITELLM_KEY_PROVIDERS | set(SUPPORTED_LLM_CHANNEL_PROTOCOLS) | {
            "minimax",
            "cohere", "huggingface", "bedrock", "sagemaker", "azure",
            "replicate", "together_ai", "palm", "text-completion-openai",
            "command-r", "groq", "cerebras", "fireworks_ai", "friendliai",
        }
        if prefix in known_providers:
            return normalized_model
        if canonical_prefix in known_providers:
            return f"{canonical_prefix}/{remainder}"
        # Not a real provider prefix — add one so LiteLLM routes correctly.
        if resolved_protocol:
            return f"{resolved_protocol}/{normalized_model}"
        return normalized_model

    if not resolved_protocol:
        return normalized_model
    return f"{resolved_protocol}/{normalized_model}"


def get_configured_llm_models(model_list: List[Dict[str, Any]]) -> List[str]:
    """Return non-legacy model names declared in Router model_list order.

    Uses the top-level ``model_name`` (the routing alias that users set in
    LITELLM_MODEL) rather than ``litellm_params.model`` (the wire-level
    model identifier).  For channel-built entries both are identical, but
    YAML configs may define a friendly alias that differs from the
    underlying provider/model path.
    """
    models: List[str] = []
    seen: set = set()
    for entry in model_list or []:
        # Prefer top-level model_name (router routing key); fall back to
        # litellm_params.model for entries that omit it.
        name = str(entry.get("model_name") or "").strip()
        if not name:
            params = entry.get("litellm_params", {}) or {}
            name = str(params.get("model") or "").strip()
        if not name or name.startswith("__legacy_") or name in seen:
            continue
        seen.add(name)
        models.append(name)
    return models


def resolve_litellm_wire_model(
    model: str,
    model_list: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Resolve a router alias to its underlying LiteLLM wire model."""
    return llm_generation_params.resolve_litellm_wire_model(model, model_list)


def resolve_litellm_thinking_enabled(
    model: str,
    model_list: Optional[List[Dict[str, Any]]] = None,
    request_overrides: Optional[Dict[str, Any]] = None,
) -> Optional[bool]:
    """Resolve whether the outgoing LiteLLM request explicitly enables thinking."""
    return llm_generation_params.resolve_litellm_thinking_enabled(
        model,
        model_list=model_list,
        request_overrides=request_overrides,
    )


def get_fixed_litellm_temperature(
    model: str,
    model_list: Optional[List[Dict[str, Any]]] = None,
    request_overrides: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    """Return a provider-mandated temperature for known strict models."""
    return llm_generation_params.get_fixed_litellm_temperature(
        model,
        model_list=model_list,
        request_overrides=request_overrides,
    )


def normalize_litellm_temperature(
    model: str,
    temperature: Optional[float],
    *,
    default: float = 0.7,
    model_list: Optional[List[Dict[str, Any]]] = None,
    request_overrides: Optional[Dict[str, Any]] = None,
) -> float:
    """Normalize temperature before sending a LiteLLM request."""
    return llm_generation_params.normalize_litellm_temperature(
        model,
        temperature,
        default=default,
        model_list=model_list,
        request_overrides=request_overrides,
    )


def resolve_unified_llm_temperature(model: str) -> float:
    """Resolve the raw unified LLM temperature with backward-compatible fallbacks."""
    llm_temperature_raw = os.getenv("LLM_TEMPERATURE")
    if llm_temperature_raw and llm_temperature_raw.strip():
        try:
            return float(llm_temperature_raw)
        except (ValueError, TypeError):
            pass

    provider_temperature_env = {
        "gemini": "GEMINI_TEMPERATURE",
        "vertex_ai": "GEMINI_TEMPERATURE",
        "anthropic": "ANTHROPIC_TEMPERATURE",
        "openai": "OPENAI_TEMPERATURE",
        "deepseek": "OPENAI_TEMPERATURE",
    }
    preferred_env = provider_temperature_env.get(_get_litellm_provider(model))
    if preferred_env:
        preferred_value = os.getenv(preferred_env)
        if preferred_value and preferred_value.strip():
            try:
                return float(preferred_value)
            except (ValueError, TypeError):
                pass

    for env_name in ("GEMINI_TEMPERATURE", "ANTHROPIC_TEMPERATURE", "OPENAI_TEMPERATURE"):
        env_value = os.getenv(env_name)
        if env_value and env_value.strip():
            try:
                return float(env_value)
            except (ValueError, TypeError):
                continue

    return 0.7


def _get_litellm_provider(model: str) -> str:
    """Extract the LiteLLM provider prefix from a model string."""
    if not model:
        return ""
    if "/" in model:
        return model.split("/", 1)[0]
    return "openai"


def _uses_direct_env_provider(model: str) -> bool:
    """Whether runtime handles the model via direct litellm env/provider resolution."""
    provider = _get_litellm_provider(model)
    return bool(provider) and provider not in _MANAGED_LITELLM_KEY_PROVIDERS


def normalize_agent_litellm_model(
    model: str,
    configured_models: Optional[set[str]] = None,
) -> str:
    """Normalize AGENT_LITELLM_MODEL while preserving configured router aliases."""
    normalized_model = (model or "").strip()
    if not normalized_model:
        return ""
    if "/" not in normalized_model:
        if configured_models and normalized_model in configured_models:
            return normalized_model
        return f"openai/{normalized_model}"
    return normalized_model


def get_effective_agent_primary_model(config: "Config") -> str:
    """Return the effective Agent primary model with fallback inheritance."""
    configured_router_models = set(
        get_configured_llm_models(getattr(config, "llm_model_list", []) or [])
    )
    configured_agent_model = normalize_agent_litellm_model(
        getattr(config, "agent_litellm_model", ""),
        configured_models=configured_router_models,
    )
    if configured_agent_model:
        return configured_agent_model
    return (getattr(config, "litellm_model", "") or "").strip()


def get_effective_agent_models_to_try(config: "Config") -> List[str]:
    """Return Agent model try-order: primary + global fallbacks (deduped)."""
    configured_router_models = set(
        get_configured_llm_models(getattr(config, "llm_model_list", []) or [])
    )
    raw_models = [get_effective_agent_primary_model(config)] + (
        getattr(config, "litellm_fallback_models", []) or []
    )
    seen = set()
    ordered_models: List[str] = []
    for model in raw_models:
        normalized_model = (model or "").strip()
        if not normalized_model:
            continue
        dedupe_key = normalize_agent_litellm_model(
            normalized_model,
            configured_models=configured_router_models,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        ordered_models.append(normalized_model)
    return ordered_models


def setup_env(override: bool = False):
    """
    Initialize environment variables from .env file.

    Args:
        override: If True, overwrite existing environment variables with values
                  from .env file. Set to True when reloading config after updates.
                  Default is False to preserve behavior on initial load where
                  system environment variables take precedence.
    """
    Config._capture_bootstrap_runtime_env_overrides()
    # src/config.py -> src/ -> root
    env_file = os.getenv("ENV_FILE")
    if env_file:
        env_path = Path(env_file)
    else:
        env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(dotenv_path=env_path, override=override)


@dataclass
class Config:
    """
    系統配置類 - 單例模式
    
    設計說明：
    - 使用 dataclass 簡化配置屬性定義
    - 所有配置項從環境變數讀取，支援預設值
    - 類方法 get_instance() 實現單例訪問
    """
    
    # === 自選股配置 ===
    stock_list: List[str] = field(default_factory=list)

    # === 飛書雲文件配置 ===
    feishu_app_id: Optional[str] = None
    feishu_app_secret: Optional[str] = None
    feishu_folder_token: Optional[str] = None  # 目標資料夾 Token

    # === 資料來源 API Token ===
    tushare_token: Optional[str] = None
    tickflow_api_key: Optional[str] = None
    finnhub_api_key: Optional[str] = None
    alphavantage_api_key: Optional[str] = None
    longbridge_app_key: Optional[str] = None
    longbridge_app_secret: Optional[str] = None
    longbridge_access_token: Optional[str] = None
    longbridge_oauth_client_id: Optional[str] = None
    stock_index_remote_update_enabled: bool = False

    # === AlphaSift optional stock screening integration ===
    alphasift_route_enabled: bool = False
    alphasift_enabled: bool = False
    alphasift_install_spec: str = DEFAULT_ALPHASIFT_INSTALL_SPEC

    # === AI 分析配置 ===
    # LiteLLM unified model config (provider/model format, e.g. gemini/gemini-3.1-pro-preview)
    litellm_model: str = ""  # Primary model; must include provider prefix when set explicitly
    litellm_fallback_models: List[str] = field(default_factory=list)  # Cross-model fallback list

    # Unified temperature for all LLM calls (LLM_TEMPERATURE); legacy per-provider temps are fallback only
    llm_temperature: float = 0.7

    # --- Multi-channel LLM config (new) ---
    # LITELLM_CONFIG: path to a standard litellm_config.yaml file (most powerful)
    litellm_config_path: Optional[str] = None
    # Internal metadata: which config layer actually produced llm_model_list
    llm_models_source: str = "legacy_env"
    # LLM_CHANNELS: list of channel dicts, each with name/base_url/api_keys/models
    llm_channels: List[Dict[str, Any]] = field(default_factory=list)
    # Raw channel names requested through LLM_CHANNELS, including channels that
    # were skipped during parsing because required channel fields were missing.
    llm_channel_names: List[str] = field(default_factory=list)
    # Pre-built LiteLLM Router model_list (populated from channels, YAML, or legacy keys)
    llm_model_list: List[Dict[str, Any]] = field(default_factory=list)

    # Multi-key support: each list is parsed from *_API_KEYS (comma-separated) with single-key fallback
    gemini_api_keys: List[str] = field(default_factory=list)
    anthropic_api_keys: List[str] = field(default_factory=list)
    openai_api_keys: List[str] = field(default_factory=list)
    deepseek_api_keys: List[str] = field(default_factory=list)

    # Legacy single-key fields (kept for backward compatibility; gemini_api_keys[0] when set)
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-3.1-pro-preview"  # 主模型
    gemini_model_fallback: str = "gemini-3-flash-preview"  # 備選模型
    gemini_temperature: float = 0.7  # 溫度引數（0.0-2.0，控制輸出隨機性，預設0.7）

    # Gemini API 請求配置（防止 429 限流）
    gemini_request_delay: float = 2.0  # 請求間隔（秒）
    gemini_max_retries: int = 5  # 最大重試次數
    gemini_retry_delay: float = 5.0  # 重試基礎延時（秒）

    # Anthropic Claude API（備選，當 Gemini 不可用時使用）
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4-6"  # Claude model name
    anthropic_temperature: float = 0.7  # Anthropic temperature (0.0-1.0, default 0.7)
    anthropic_max_tokens: int = 8192  # Max tokens for Anthropic responses

    # OpenAI 相容 API（備選，當 Gemini/Anthropic 不可用時使用）
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None  # 如: https://api.openai.com/v1
    openai_model: str = "gpt-5.5"  # OpenAI 相容模型名稱
    openai_vision_model: Optional[str] = None  # Deprecated: use VISION_MODEL instead
    openai_temperature: float = 0.7  # OpenAI 溫度引數（0.0-2.0，預設0.7）

    # === Vision 配置 ===
    # VISION_MODEL: litellm model string used for image understanding calls.
    # Fallback chain: VISION_MODEL → OPENAI_VISION_MODEL → gemini/gemini-2.0-flash
    vision_model: str = ""
    # VISION_PROVIDER_PRIORITY: comma-separated provider order for Vision fallback.
    vision_provider_priority: str = "gemini,anthropic,openai"

    # === 搜尋引擎配置（支援多 Key 負載均衡）===
    anspire_api_keys: List[str] = field(default_factory=list)  # Anspire Search API Keys
    bocha_api_keys: List[str] = field(default_factory=list)  # Bocha API Keys
    minimax_api_keys: List[str] = field(default_factory=list)  # MiniMax API Keys
    tavily_api_keys: List[str] = field(default_factory=list)  # Tavily API Keys
    brave_api_keys: List[str] = field(default_factory=list)  # Brave Search API Keys
    serpapi_keys: List[str] = field(default_factory=list)  # SerpAPI Keys
    searxng_base_urls: List[str] = field(default_factory=list)  # SearXNG instance URLs (self-hosted, no quota)
    searxng_public_instances_enabled: bool = False  # Auto-discover public SearXNG instances when base URLs are absent

    # === Social Sentiment (US stocks only, api.adanos.org) ===
    social_sentiment_api_key: Optional[str] = None
    social_sentiment_api_url: str = "https://api.adanos.org"

    # === 新聞與分析篩選配置 ===
    news_max_age_days: int = 3   # 新聞最大時效（天）
    news_strategy_profile: str = "short"  # 新聞視窗策略檔位：ultra_short/short/medium/long
    bias_threshold: float = 5.0  # 乖離率閾值（%），超過此值提示不追高

    # === Agent 模式配置 ===
    agent_litellm_model: str = ""  # Optional Agent-only primary model; empty inherits LITELLM_MODEL
    agent_mode: bool = False
    _agent_mode_explicit: bool = False  # True when AGENT_MODE was explicitly set in env
    agent_max_steps: int = AGENT_MAX_STEPS_DEFAULT
    agent_skills: List[str] = field(default_factory=list)
    agent_skill_dir: Optional[str] = None
    agent_nl_routing: bool = False  # Enable natural language routing in bot dispatcher
    agent_arch: str = "single"     # Agent architecture: 'single' (legacy) or 'multi' (orchestrator)
    agent_orchestrator_mode: str = "standard"  # Orchestrator mode: quick/standard/full/specialist
    agent_orchestrator_timeout_s: int = 600  # Cooperative timeout budget for the whole multi-agent pipeline
    agent_risk_override: bool = True  # Allow risk agent to veto buy signals
    agent_deep_research_budget: int = 30000  # Max token budget for deep research
    agent_deep_research_timeout: int = 180  # Max seconds for /research command before returning timeout
    agent_memory_enabled: bool = False  # Enable memory & calibration system
    agent_skill_autoweight: bool = True  # Auto-weight skills by backtest performance
    agent_skill_routing: str = "auto"  # Skill routing: 'auto' (regime-based) or 'manual'
    agent_context_compression_enabled: bool = False  # Compress visible chat history before Agent calls
    agent_context_compression_profile: str = AGENT_CONTEXT_COMPRESSION_DEFAULT_PROFILE
    agent_context_compression_trigger_tokens: int = 12000
    agent_context_protected_turns: int = 4
    agent_event_monitor_enabled: bool = False  # Enable periodic event-driven alert checks in schedule mode
    agent_event_monitor_interval_minutes: int = 5  # Polling interval for event monitor background checks
    agent_event_alert_rules_json: str = ""  # JSON array of serialized EventMonitor rules

    # === 通知配置（可同時配置多個，全部推送）===
    
    # 企業微信 Webhook
    wechat_webhook_url: Optional[str] = None
    
    # 飛書 Webhook
    feishu_webhook_url: Optional[str] = None
    feishu_webhook_secret: Optional[str] = None  # 自定義機器人簽名金鑰（可選）
    feishu_webhook_keyword: Optional[str] = None  # 自定義機器人關鍵詞（可選）
    
    # Telegram 配置（需要同時配置 Bot Token 和 Chat ID）
    telegram_bot_token: Optional[str] = None  # Bot Token（@BotFather 獲取）
    telegram_chat_id: Optional[str] = None  # Chat ID
    telegram_message_thread_id: Optional[str] = None  # Topic ID (Message Thread ID) for groups
    
    # 郵件配置（只需郵箱和授權碼，SMTP 自動識別）
    email_sender: Optional[str] = None  # 發件人郵箱
    email_sender_name: str = "daily_stock_analysis股票分析助手"  # 發件人顯示名稱
    email_password: Optional[str] = None  # 郵箱密碼/授權碼
    email_receivers: List[str] = field(default_factory=list)  # 收件人列表（留空則發給自己）

    # Stock-to-email group routing (Issue #268): STOCK_GROUP_N + EMAIL_GROUP_N
    # When configured, each group's report is sent to that group's emails only.
    stock_email_groups: List[Tuple[List[str], List[str]]] = field(default_factory=list)

    # Pushover 配置（手機/桌面推送通知）
    pushover_user_key: Optional[str] = None  # 使用者 Key（https://pushover.net 獲取）
    pushover_api_token: Optional[str] = None  # 應用 API Token

    # ntfy 配置（完整 topic endpoint，例如 https://ntfy.sh/my-topic）
    ntfy_url: Optional[str] = None
    ntfy_token: Optional[str] = None

    # Gotify 配置（server base URL；sender 會拼接 /message）
    gotify_url: Optional[str] = None
    gotify_token: Optional[str] = None
    
    # 自定義 Webhook（支援多個，逗號分隔）
    # 適用於：釘釘、Discord、Slack、自建服務等任意支援 POST JSON 的 Webhook
    custom_webhook_urls: List[str] = field(default_factory=list)
    custom_webhook_bearer_token: Optional[str] = None  # Bearer Token（用於需要認證的 Webhook）
    custom_webhook_body_template: Optional[str] = None  # 自定義 Webhook JSON body 模板
    webhook_verify_ssl: bool = True  # Webhook HTTPS 證書校驗，false 可支援自簽名（有 MITM 風險）

    # Discord 通知配置
    discord_bot_token: Optional[str] = None  # Discord Bot Token
    discord_main_channel_id: Optional[str] = None  # Discord 主頻道 ID
    discord_webhook_url: Optional[str] = None  # Discord Webhook URL
    discord_interactions_public_key: Optional[str] = None  # Discord Interaction 入站驗籤公鑰

    # Slack 通知配置
    slack_webhook_url: Optional[str] = None  # Slack Incoming Webhook URL
    slack_bot_token: Optional[str] = None  # Slack Bot Token (xoxb-...)
    slack_channel_id: Optional[str] = None  # Slack 頻道 ID (Bot 模式必填)

    # AstrBot 通知配置
    astrbot_token: Optional[str] = None
    astrbot_url: Optional[str] = None

    # 通知路由策略（Issue #1200 P3）：留空表示該型別使用全部已配置通道
    notification_report_channels: List[str] = field(default_factory=list)
    notification_alert_channels: List[str] = field(default_factory=list)
    notification_system_error_channels: List[str] = field(default_factory=list)

    # 通知降噪機制（Issue #1200 P4）：預設全部關閉，僅對靜態通知通道生效
    notification_dedup_ttl_seconds: int = 0
    notification_cooldown_seconds: int = 0
    notification_quiet_hours: str = ""
    notification_timezone: str = ""
    notification_min_severity: str = ""
    notification_daily_digest_enabled: bool = False

    # 單股推送模式：每分析完一隻股票立即推送，而不是彙總後推送
    single_stock_notify: bool = False

    # 報告型別：simple(精簡) 或 full(完整)
    report_type: str = "simple"
    report_language: str = "zh_TW"

    # 僅分析結果摘要：true 時只推送彙總，不含個股詳情（Issue #262）
    report_summary_only: bool = False
    report_show_llm_model: bool = True

    # Report Engine P0: Jinja2 renderer and integrity checks
    report_templates_dir: str = "templates"  # Template directory (relative to project root)
    report_renderer_enabled: bool = False  # Enable Jinja2 rendering (default off for zero regression)
    report_integrity_enabled: bool = True  # Content integrity validation after LLM output
    report_integrity_retry: int = 1  # Retry count when mandatory fields missing (0 = placeholder only)
    llm_provider_timeout_seconds: int = 45  # Per-provider LLM call timeout; exceed → timeout logged + fallback
    search_total_timeout_seconds: int = 8  # Total search/news budget; exceed → degrade to no-search
    data_fetch_timeout_seconds: int = 120  # Daily data fetch timeout; exceed → return partial or fail
    report_history_compare_n: int = 0  # History comparison count (0 = disabled)

    # PushPlus 推送配置
    pushplus_token: Optional[str] = None  # PushPlus Token
    pushplus_topic: Optional[str] = None  # PushPlus 群組編碼（一對多推送）

    # Server醬3 推送配置
    serverchan3_sendkey: Optional[str] = None  # Server醬3 SendKey

    # 分析間隔時間（秒）- 用於避免API限流
    analysis_delay: float = 0.0  # 個股分析與大盤分析之間的延遲

    # Merge stock + market report into one notification (Issue #190)
    merge_email_notification: bool = False

    # 訊息長度限制（位元組）- 超長自動分批傳送
    feishu_max_bytes: int = 20000  # 飛書限制約 20KB，預設 20000 位元組
    wechat_max_bytes: int = 4000   # 企業微信限制 4096 位元組，預設 4000 位元組
    discord_max_words: int = 2000  # Discord 限制 2000 字，預設 2000 字
    wechat_msg_type: str = "markdown"  # 企業微信訊息型別，預設 markdown 型別

    # Markdown 轉圖片（Issue #289）：對不支援 Markdown 的通道以圖片傳送
    markdown_to_image_channels: List[str] = field(default_factory=list)  # 逗號分隔：telegram,wechat,custom,email
    markdown_to_image_max_chars: int = 15000  # 超過此長度不轉換，避免超大圖片
    md2img_engine: str = "wkhtmltoimage"  # wkhtmltoimage | markdown-to-file (Issue #455, better emoji support)

    # 實時行情預取（Issue #455）：設為 false 可禁用，避免 efinance/akshare_em 全市場拉取
    prefetch_realtime_quotes: bool = True

    # === 資料庫配置 ===
    database_path: str = "./data/stock_analysis.db"
    sqlite_wal_enabled: bool = True
    sqlite_busy_timeout_ms: int = 5000
    sqlite_write_retry_max: int = 3
    sqlite_write_retry_base_delay: float = 0.1

    # 是否儲存分析上下文快照（用於歷史回溯）
    save_context_snapshot: bool = True

    # === 回測配置 ===
    backtest_enabled: bool = True
    backtest_eval_window_days: int = 10
    backtest_min_age_days: int = 14
    backtest_engine_version: str = "v1"
    backtest_neutral_band_pct: float = 2.0
    
    # === 日誌配置 ===
    log_dir: str = "./logs"  # 日誌檔案目錄
    log_level: str = "INFO"  # 日誌級別
    
    # === 系統配置 ===
    max_workers: int = 3  # 低併發防封禁
    debug: bool = False
    http_proxy: Optional[str] = None  # HTTP 代理 (例如: http://127.0.0.1:10809)
    https_proxy: Optional[str] = None # HTTPS 代理
    
    # === 定時任務配置 ===
    schedule_enabled: bool = False            # 是否啟用定時任務
    schedule_time: str = "18:00"              # 每日推送時間（HH:MM 格式）
    schedule_run_immediately: bool = True     # 啟動時是否立即執行一次
    run_immediately: bool = True              # 啟動時是否立即執行一次（非定時模式）
    market_review_enabled: bool = True        # 是否啟用大盤覆盤
    # 大盤覆盤市場區域：tw(台股)、us(美股)、all(台股+美股)；both 只作為舊值別名
    market_review_region: str = "tw"
    # 多市場大盤覆盤區域列表（MARKET_REVIEW_REGIONS=TW,US）；優先順序高於 market_review_region
    # 內部使用小寫區域碼：tw / us / cn / hk；空列表表示回退到 market_review_region
    market_review_regions: List[str] = field(default_factory=list)
    market_review_color_scheme: str = "green_up"
    # 交易日檢查：預設啟用，非交易日跳過執行；設為 false 或 --force-run 可強制執行（Issue #373）
    trading_day_check_enabled: bool = True

    # === Route B TW/US runtime scope enforcement ===
    # ROUTE_B_ENFORCE_MARKET_SCOPE=true 時，只允許 TW/US 股票分析和大盤覆盤
    route_b_enforce_market_scope: bool = False
    # ROUTE_B_MARKETS=TW,US 指定允許的市場（大寫，逗號分隔）
    route_b_markets: List[str] = field(default_factory=lambda: ["TW", "US"])

    # === 實時行情增強資料配置 ===
    # 實時行情開關（關閉後使用歷史收盤價進行分析）
    enable_realtime_quote: bool = True
    # 盤中實時技術面：啟用時用實時價計算 MA/多頭排列（Issue #234）；關閉則用昨日收盤
    enable_realtime_technical_indicators: bool = True
    # 籌碼分佈已從 Route B TW/US 分析路徑移除；保留欄位僅供舊設定相容。
    enable_chip_distribution: bool = False
    # 東財介面補丁開關
    enable_eastmoney_patch: bool = False
    # 實時行情資料來源優先順序（逗號分隔）
    # 推薦順序：tencent > akshare_sina > efinance > akshare_em > tushare
    # - tencent: 第三方財經資料源，有量比/換手率/市盈率等，單股查詢穩定（推薦）
    # - akshare_sina: 新浪財經，基本行情穩定，但無量比
    # - efinance/akshare_em: 東財全量介面，資料最全但容易被封
    # - tushare: Tushare Pro，需要2000積分，資料全面（付費使用者可優先使用）
    realtime_source_priority: str = "tencent,akshare_sina,efinance,akshare_em"
    # 實時行情快取時間（秒）
    realtime_cache_ttl: int = 600
    # 熔斷器冷卻時間（秒）
    circuit_breaker_cooldown: int = 300

    # === Phase 18D 價值網路圖 Mermaid 附錄（預設開啟，可用 ENABLE_VALUE_NETWORK_MERMAID=false 關閉）===
    enable_value_network_mermaid: bool = True

    # === Phase 25.6 四大師視角補充（預設開啟，可用 ENABLE_FOUR_MASTERS_COMMENTARY=false 關閉）===
    # 個股完整報告附加四個具名投資框架（巴菲特/蒙格/段永平/李錄）的點評式補充段；
    # 僅為評論，不輸出行動、不覆蓋原始 operation_advice / trend_prediction / 買賣區間。
    enable_four_masters_commentary: bool = True

    # === 基本面聚合開關與降級保護 ===
    # 全域性總開關；關閉時返回 not_supported 並保持主流程無變化
    enable_fundamental_pipeline: bool = True
    # 基本面階段總預算（秒）
    fundamental_stage_timeout_seconds: float = FUNDAMENTAL_STAGE_TIMEOUT_SECONDS_DEFAULT
    # 單能力源呼叫超時（秒）
    fundamental_fetch_timeout_seconds: float = 3.0
    # 單能力失敗重試次數（已包含首次）
    fundamental_retry_max: int = 1
    # 基本面上下文短 TTL（秒）
    fundamental_cache_ttl_seconds: int = 120
    # 基本面快取最大條目數（避免長時間執行記憶體增長）
    fundamental_cache_max_entries: int = 256

    # === Portfolio PR2: import/risk/fx settings ===
    portfolio_risk_concentration_alert_pct: float = 35.0
    portfolio_risk_drawdown_alert_pct: float = 15.0
    portfolio_risk_stop_loss_alert_pct: float = 10.0
    portfolio_risk_stop_loss_near_ratio: float = 0.8
    portfolio_risk_lookback_days: int = 180
    portfolio_fx_update_enabled: bool = True

    # Discord 機器人狀態
    discord_bot_status: str = "台股 / 美股智慧分析 | /help"

    # === 流控配置（防封禁關鍵引數）===
    # Akshare 請求間隔範圍（秒）
    akshare_sleep_min: float = 2.0
    akshare_sleep_max: float = 5.0
    
    # Tushare 每分鐘最大請求數（免費配額）
    tushare_rate_limit_per_minute: int = 80
    
    # 重試配置
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    
    # === WebUI 配置 ===
    webui_enabled: bool = False
    webui_host: str = "127.0.0.1"
    webui_port: int = 8000
    
    # === 機器人配置 ===
    bot_enabled: bool = True              # 是否啟用機器人功能
    bot_command_prefix: str = "/"         # 命令字首
    bot_rate_limit_requests: int = 10     # 頻率限制：視窗內最大請求數
    bot_rate_limit_window: int = 60       # 頻率限制：視窗時間（秒）
    bot_admin_users: List[str] = field(default_factory=list)  # 管理員使用者 ID 列表
    
    # 飛書機器人（事件訂閱）- 已有 feishu_app_id, feishu_app_secret
    feishu_verification_token: Optional[str] = None  # 事件訂閱驗證 Token
    feishu_encrypt_key: Optional[str] = None         # 訊息加密金鑰（可選）
    feishu_stream_enabled: bool = False              # 是否啟用 Stream 長連線模式（無需公網IP）
    
    # 釘釘機器人
    dingtalk_app_key: Optional[str] = None      # 應用 AppKey
    dingtalk_app_secret: Optional[str] = None   # 應用 AppSecret
    dingtalk_stream_enabled: bool = False       # 是否啟用 Stream 模式（無需公網IP）
    
    # 企業微信機器人（回撥模式）
    wecom_corpid: Optional[str] = None              # 企業 ID
    wecom_token: Optional[str] = None               # 回撥 Token
    wecom_encoding_aes_key: Optional[str] = None    # 訊息加解密金鑰
    wecom_agent_id: Optional[str] = None            # 應用 AgentId
    
    # Telegram 機器人 - 已有 telegram_bot_token, telegram_chat_id
    telegram_webhook_secret: Optional[str] = None   # Webhook 金鑰

    # === 配置校驗模式 ===
    # CONFIG_VALIDATE_MODE=warn (default): log all issues but always continue startup
    # CONFIG_VALIDATE_MODE=strict: exit(1) when any "error" severity issue is found
    config_validate_mode: str = "warn"

    # --- Post-init validation ---------------------------------------------------
    _VALID_AGENT_ARCH = {"single", "multi"}
    _VALID_ORCHESTRATOR_MODES = {"quick", "standard", "full", "specialist"}
    _VALID_SKILL_ROUTING = {"auto", "manual"}
    _WEBUI_RUNTIME_ENV_FILE_PRIORITY_KEYS = frozenset(
        {
            "STOCK_LIST",
            "RUN_IMMEDIATELY",
            "SCHEDULE_ENABLED",
            "SCHEDULE_TIME",
            "SCHEDULE_RUN_IMMEDIATELY",
        }
    )
    _BOOTSTRAP_RUNTIME_ENV_OVERRIDES_CAPTURED = False
    _BOOTSTRAP_RUNTIME_ENV_OVERRIDES = frozenset()
    _BOOTSTRAP_RUNTIME_ENV_PRESENT_KEYS = frozenset()

    def __post_init__(self) -> None:
        _log = logging.getLogger(__name__)
        if self.agent_arch not in self._VALID_AGENT_ARCH:
            _log.warning(
                "Invalid AGENT_ARCH=%r, falling back to 'single'. Valid: %s",
                self.agent_arch, self._VALID_AGENT_ARCH,
            )
            object.__setattr__(self, "agent_arch", "single")
        if self.agent_orchestrator_mode in {"strategy", "skill"}:
            _log.info(
                "AGENT_ORCHESTRATOR_MODE=%s is deprecated; normalizing to 'specialist'",
                self.agent_orchestrator_mode,
            )
            object.__setattr__(self, "agent_orchestrator_mode", "specialist")
        if self.agent_orchestrator_mode not in self._VALID_ORCHESTRATOR_MODES:
            _log.warning(
                "Invalid AGENT_ORCHESTRATOR_MODE=%r, falling back to 'standard'. Valid: %s",
                self.agent_orchestrator_mode, self._VALID_ORCHESTRATOR_MODES,
            )
            object.__setattr__(self, "agent_orchestrator_mode", "standard")
        if self.agent_skill_routing not in self._VALID_SKILL_ROUTING:
            _log.warning(
                "Invalid AGENT_SKILL_ROUTING=%r, falling back to 'auto'. Valid: %s",
                self.agent_skill_routing, self._VALID_SKILL_ROUTING,
            )
            object.__setattr__(self, "agent_skill_routing", "auto")
        normalized_profile = normalize_agent_context_compression_profile(
            self.agent_context_compression_profile
        )
        if normalized_profile != self.agent_context_compression_profile:
            object.__setattr__(self, "agent_context_compression_profile", normalized_profile)

    # 單例例項儲存
    _instance: Optional['Config'] = None
    
    @classmethod
    def get_instance(cls) -> 'Config':
        """
        獲取配置單例例項
        
        單例模式確保：
        1. 全域性只有一個配置例項
        2. 配置只從環境變數載入一次
        3. 所有模組共享相同配置
        """
        if cls._instance is None:
            cls._instance = cls._load_from_env()
        return cls._instance
    
    @classmethod
    def _load_from_env(cls) -> 'Config':
        """
        從 .env 檔案載入配置
        
        載入優先順序：
        1. 大多數配置保持系統環境變數優先
        2. WebUI 可寫的執行期關鍵鍵優先複用持久化 `.env`，但保留啟動時顯式程序環境變數的 override
        3. 程式碼中的預設值
        """
        cls._capture_bootstrap_runtime_env_overrides()
        preexisting_report_language = os.environ.get("REPORT_LANGUAGE")

        # 確保環境變數已載入
        setup_env()

        # === 智慧代理配置 (關鍵修復) ===
        # 如果配置了代理，自動設定 NO_PROXY 以排除國內資料來源，避免行情獲取失敗
        http_proxy = os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
        if http_proxy:
            # 國內金融資料來源域名列表
            domestic_domains = [
                'eastmoney.com',   # 東方財富 (Efinance/Akshare)
                'sina.com.cn',     # 新浪財經 (Akshare)
                '163.com',         # 網易財經 (Akshare)
                'tushare.pro',     # Tushare
                'baostock.com',    # Baostock
                'sse.com.cn',      # 上交所
                'szse.cn',         # 深交所
                'csindex.com.cn',  # 中證指數
                'cninfo.com.cn',   # 巨潮資訊
                'localhost',
                '127.0.0.1'
            ]

            # 獲取現有的 no_proxy
            current_no_proxy = os.getenv('NO_PROXY') or os.getenv('no_proxy') or ''
            existing_domains = current_no_proxy.split(',') if current_no_proxy else []

            # 合併去重
            final_domains = list(set(existing_domains + domestic_domains))
            final_no_proxy = ','.join(filter(None, final_domains))

            # 設定環境變數 (requests/urllib3/aiohttp 都會遵守此設定)
            os.environ['NO_PROXY'] = final_no_proxy
            os.environ['no_proxy'] = final_no_proxy

            # 確保 HTTP_PROXY 也被正確設定（以防僅在 .env 中定義但未匯出）
            os.environ['HTTP_PROXY'] = http_proxy
            os.environ['http_proxy'] = http_proxy

            # HTTPS_PROXY 同理
            https_proxy = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')
            if https_proxy:
                os.environ['HTTPS_PROXY'] = https_proxy
                os.environ['https_proxy'] = https_proxy

        
        # 解析自選股列表（逗號分隔，統一為大寫 Issue #355）
        stock_list_str = cls._resolve_env_value(
            'STOCK_LIST',
            default='',
            prefer_env_file=True,
        )
        stock_list = [
            (c or "").strip().upper()
            for c in stock_list_str.split(',')
            if (c or "").strip()
        ]
        
        # === LiteLLM multi-key parsing ===
        # GEMINI_API_KEYS (comma-separated) > GEMINI_API_KEY (single)
        _gemini_keys_raw = os.getenv('GEMINI_API_KEYS', '')
        gemini_api_keys = [k.strip() for k in _gemini_keys_raw.split(',') if k.strip()]
        _single_gemini = os.getenv('GEMINI_API_KEY', '').strip()
        if not gemini_api_keys and _single_gemini:
            gemini_api_keys = [_single_gemini]

        # ANTHROPIC_API_KEYS > ANTHROPIC_API_KEY
        _anthropic_keys_raw = os.getenv('ANTHROPIC_API_KEYS', '')
        anthropic_api_keys = [k.strip() for k in _anthropic_keys_raw.split(',') if k.strip()]
        _single_anthropic = os.getenv('ANTHROPIC_API_KEY', '').strip()
        if not anthropic_api_keys and _single_anthropic:
            anthropic_api_keys = [_single_anthropic]

        # OPENAI_API_KEYS > AIHUBMIX_KEY > OPENAI_API_KEY
        _aihubmix = os.getenv('AIHUBMIX_KEY', '').strip()
        _openai_keys_raw = os.getenv('OPENAI_API_KEYS', '')
        openai_api_keys = [k.strip() for k in _openai_keys_raw.split(',') if k.strip()]
        if not openai_api_keys:
            _single_openai = os.getenv('OPENAI_API_KEY', '').strip()
            _fallback_key = _aihubmix or _single_openai
            if _fallback_key:
                openai_api_keys = [_fallback_key]
        openai_base_url = os.getenv('OPENAI_BASE_URL') or (
            'https://aihubmix.com/v1' if _aihubmix else None
        )

        # DEEPSEEK_API_KEYS > DEEPSEEK_API_KEY (independent from OpenAI-compatible layer)
        _deepseek_keys_raw = os.getenv('DEEPSEEK_API_KEYS', '')
        deepseek_api_keys = [k.strip() for k in _deepseek_keys_raw.split(',') if k.strip()]
        if not deepseek_api_keys:
            _single_deepseek = os.getenv('DEEPSEEK_API_KEY', '').strip()
            if _single_deepseek:
                deepseek_api_keys = [_single_deepseek]

        # Anspire Open shares the same key as Anspire Search and exposes an
        # OpenAI-compatible LLM gateway.  When no other OpenAI-compatible key is
        # configured, use ANSPIRE_API_KEYS as the legacy openai-compatible
        # provider so "one key" setups work without LLM_CHANNELS.
        anspire_keys_str = os.getenv('ANSPIRE_API_KEYS', '')
        anspire_api_keys = [k.strip() for k in anspire_keys_str.split(',') if k.strip()]
        anspire_llm_enabled = parse_env_bool(os.getenv('ANSPIRE_LLM_ENABLED'), default=True)
        anspire_llm_base_url = (
            os.getenv('ANSPIRE_LLM_BASE_URL') or ANSPIRE_LLM_BASE_URL_DEFAULT
        ).strip()
        _anspire_llm_model_env = os.getenv('ANSPIRE_LLM_MODEL', '').strip()
        anspire_channel_disabled = False
        for _raw_channel in os.getenv('LLM_CHANNELS', '').split(','):
            if _raw_channel.strip().lower() != "anspire":
                continue
            _channel_enabled_raw = os.getenv('LLM_ANSPIRE_ENABLED')
            if _channel_enabled_raw is not None and _channel_enabled_raw.strip():
                anspire_channel_disabled = not parse_env_bool(_channel_enabled_raw, default=True)
            else:
                anspire_channel_disabled = not anspire_llm_enabled
            break
        using_anspire_llm_legacy = bool(
            anspire_llm_enabled
            and not anspire_channel_disabled
            and anspire_api_keys
            and not openai_api_keys
        )
        if using_anspire_llm_legacy:
            openai_api_keys = list(anspire_api_keys)
            openai_base_url = anspire_llm_base_url

        # LITELLM_MODEL: explicit config takes precedence; else infer from available keys
        litellm_model = os.getenv('LITELLM_MODEL', '').strip()
        inferred_legacy_deepseek_model = False
        _openai_model_env = os.getenv('OPENAI_MODEL', '').strip()
        if using_anspire_llm_legacy:
            _openai_model_name = _anspire_llm_model_env or _openai_model_env or ANSPIRE_LLM_MODEL_DEFAULT
        else:
            _openai_model_name = _openai_model_env or 'gpt-5.5'
        if not litellm_model:
            _gemini_model_name = os.getenv('GEMINI_MODEL', 'gemini-3.1-pro-preview').strip()
            _anthropic_model_name = os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-6').strip()
            if gemini_api_keys:
                litellm_model = f'gemini/{_gemini_model_name}'
            elif anthropic_api_keys:
                litellm_model = f'anthropic/{_anthropic_model_name}'
            elif deepseek_api_keys:
                litellm_model = 'deepseek/deepseek-chat'
                inferred_legacy_deepseek_model = True
            elif openai_api_keys:
                # For openai-compatible models, add prefix only if not already prefixed
                if '/' not in _openai_model_name:
                    litellm_model = f'openai/{_openai_model_name}'
                else:
                    litellm_model = _openai_model_name

        # LITELLM_FALLBACK_MODELS: comma-separated list of fallback models
        _fallback_str = os.getenv('LITELLM_FALLBACK_MODELS', '')
        if _fallback_str.strip():
            litellm_fallback_models = [m.strip() for m in _fallback_str.split(',') if m.strip()]
        else:
            # Backward compat: use gemini_model_fallback when primary is gemini
            _gemini_fallback = os.getenv('GEMINI_MODEL_FALLBACK', 'gemini-3-flash-preview').strip()
            if litellm_model.startswith('gemini/') and _gemini_fallback:
                _fb = f'gemini/{_gemini_fallback}' if '/' not in _gemini_fallback else _gemini_fallback
                litellm_fallback_models = [_fb]
            else:
                litellm_fallback_models = []

        # === LLM Channels + YAML config ===
        litellm_config_path = os.getenv('LITELLM_CONFIG', '').strip() or None
        llm_models_source = "legacy_env"
        llm_channels: List[Dict[str, Any]] = []
        llm_channel_names: List[str] = []
        llm_model_list: List[Dict[str, Any]] = []

        # Priority 1: LITELLM_CONFIG (standard LiteLLM YAML config file)
        if litellm_config_path:
            llm_model_list = cls._parse_litellm_yaml(litellm_config_path)
            if llm_model_list:
                llm_models_source = "litellm_config"

        # Priority 2: LLM_CHANNELS (env var based channel config)
        if not llm_model_list:
            _channels_str = os.getenv('LLM_CHANNELS', '').strip()
            if _channels_str:
                llm_channel_names = [
                    ch.strip().lower()
                    for ch in _channels_str.split(',')
                    if ch.strip()
                ]
                llm_channels = cls._parse_llm_channels(_channels_str)
                llm_model_list = cls._channels_to_model_list(llm_channels)
                if llm_model_list:
                    llm_models_source = "llm_channels"

        # Priority 3: Legacy env vars → auto-build model_list (backward compatible)
        if not llm_model_list:
            llm_model_list = cls._legacy_keys_to_model_list(
                gemini_api_keys, anthropic_api_keys, openai_api_keys,
                openai_base_url,
                deepseek_api_keys,
            )
            if llm_model_list:
                llm_models_source = "legacy_env"

        if (
            inferred_legacy_deepseek_model
            and llm_models_source == "legacy_env"
            and litellm_model == 'deepseek/deepseek-chat'
        ):
            logger.warning(
                "Deprecation warning:\n"
                "deepseek-chat will be deprecated on 2026-07-24,\n"
                "please migrate to deepseek-v4-flash."
            )

        # Auto-infer LITELLM_MODEL from channels when not explicitly set
        if not litellm_model and llm_channels:
            for _ch in llm_channels:
                if _ch.get('models'):
                    litellm_model = _ch['models'][0]
                    break

        # Auto-infer LITELLM_FALLBACK_MODELS from channels when not explicitly set
        if not litellm_fallback_models and llm_channels and litellm_model:
            _all_ch_models: List[str] = []
            for _ch in llm_channels:
                _all_ch_models.extend(_ch.get('models', []))
            _seen = {litellm_model}
            litellm_fallback_models = [
                m for m in _all_ch_models
                if m not in _seen and not _seen.add(m)  # type: ignore[func-returns-value]
            ]

        agent_litellm_model = normalize_agent_litellm_model(
            os.getenv('AGENT_LITELLM_MODEL', ''),
            configured_models=set(get_configured_llm_models(llm_model_list)),
        )
        agent_context_compression_profile = normalize_agent_context_compression_profile(
            os.getenv('AGENT_CONTEXT_COMPRESSION_PROFILE')
        )
        agent_context_compression_preset = get_agent_context_compression_preset(
            agent_context_compression_profile
        )
        agent_context_compression_trigger_tokens = parse_agent_context_compression_int(
            os.getenv('AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS'),
            agent_context_compression_preset.trigger_tokens,
            field_name='AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS',
            minimum=1000,
            maximum=200000,
        )
        agent_context_protected_turns = parse_agent_context_compression_int(
            os.getenv('AGENT_CONTEXT_PROTECTED_TURNS'),
            agent_context_compression_preset.protected_turns,
            field_name='AGENT_CONTEXT_PROTECTED_TURNS',
            minimum=1,
            maximum=20,
        )

        # 解析搜尋引擎 API Keys（支援多個 key，逗號分隔）
        bocha_keys_str = os.getenv('BOCHA_API_KEYS', '')
        bocha_api_keys = [k.strip() for k in bocha_keys_str.split(',') if k.strip()]

        minimax_keys_str = os.getenv('MINIMAX_API_KEYS', '')
        minimax_api_keys = [k.strip() for k in minimax_keys_str.split(',') if k.strip()]
        
        tavily_keys_str = os.getenv('TAVILY_API_KEYS', '')
        tavily_api_keys = [k.strip() for k in tavily_keys_str.split(',') if k.strip()]
        
        serpapi_keys_str = os.getenv('SERPAPI_API_KEYS', '')
        serpapi_keys = [k.strip() for k in serpapi_keys_str.split(',') if k.strip()]

        brave_keys_str = os.getenv('BRAVE_API_KEYS', '')
        brave_api_keys = [k.strip() for k in brave_keys_str.split(',') if k.strip()]

        _raw_urls = [u.strip() for u in os.getenv('SEARXNG_BASE_URLS', '').split(',') if u.strip()]
        searxng_base_urls = []
        invalid_searxng_urls = []
        for u in _raw_urls:
            p = urlparse(u)
            if p.scheme in ('http', 'https') and p.netloc:
                searxng_base_urls.append(u)
            else:
                invalid_searxng_urls.append(u)
        if invalid_searxng_urls:
            logger.warning(
                "SEARXNG_BASE_URLS 中存在無效 URL，已忽略: %s",
                ", ".join(invalid_searxng_urls[:3]),
            )
        searxng_public_instances_enabled = parse_env_bool(
            os.getenv('SEARXNG_PUBLIC_INSTANCES_ENABLED'),
            default=False,
        )

        # 企微訊息型別與最大位元組數邏輯
        wechat_msg_type = os.getenv('WECHAT_MSG_TYPE', 'markdown')
        wechat_msg_type_lower = wechat_msg_type.lower()
        wechat_max_bytes_env = os.getenv('WECHAT_MAX_BYTES')
        if wechat_max_bytes_env not in (None, ''):
            wechat_max_bytes = parse_env_int(
                wechat_max_bytes_env,
                2048 if wechat_msg_type_lower == 'text' else 4000,
                field_name='WECHAT_MAX_BYTES',
                minimum=1,
            )
        else:
            # 未顯式配置時，根據訊息型別選擇預設位元組數
            wechat_max_bytes = 2048 if wechat_msg_type_lower == 'text' else 4000

        # Preserve historical semantics for startup flags: only an explicit
        # literal "true" enables immediate execution; empty strings stay False.
        legacy_run_immediately_env = cls._resolve_env_value(
            'RUN_IMMEDIATELY',
            prefer_env_file=True,
        )
        legacy_run_immediately = (
            legacy_run_immediately_env.lower() == 'true'
            if legacy_run_immediately_env is not None
            else True
        )

        schedule_run_immediately_env = cls._resolve_env_value(
            'SCHEDULE_RUN_IMMEDIATELY',
            prefer_env_file=True,
        )
        # Keep backward compatibility for container/process overrides:
        # when RUN_IMMEDIATELY is explicitly provided by the runtime but the
        # schedule-specific alias is absent, schedule mode should inherit the
        # legacy process value instead of being pulled back to the persisted
        # `.env` copy of SCHEDULE_RUN_IMMEDIATELY.
        if (
            not cls._had_bootstrap_runtime_env_key('SCHEDULE_RUN_IMMEDIATELY')
            and cls._has_bootstrap_runtime_env_override('RUN_IMMEDIATELY')
        ):
            schedule_run_immediately = legacy_run_immediately
        else:
            schedule_run_immediately = (
                schedule_run_immediately_env.lower() == 'true'
                if schedule_run_immediately_env is not None
                else legacy_run_immediately
            )
        schedule_time_value = cls._resolve_env_value(
            'SCHEDULE_TIME',
            default='18:00',
            prefer_env_file=True,
        )

        report_language_raw = cls._resolve_report_language_env_value(
            preexisting_report_language
        )
        report_show_llm_model_raw = os.getenv('REPORT_SHOW_LLM_MODEL')
        report_show_llm_model = parse_env_bool(report_show_llm_model_raw, default=True)
        if report_show_llm_model_raw is not None and not report_show_llm_model_raw.strip():
            report_show_llm_model = False

        return cls(
            stock_list=stock_list,
            feishu_app_id=os.getenv('FEISHU_APP_ID'),
            feishu_app_secret=os.getenv('FEISHU_APP_SECRET'),
            feishu_folder_token=os.getenv('FEISHU_FOLDER_TOKEN'),
            tushare_token=os.getenv('TUSHARE_TOKEN'),
            tickflow_api_key=os.getenv('TICKFLOW_API_KEY'),
            finnhub_api_key=os.getenv('FINNHUB_API_KEY') or None,
            alphavantage_api_key=os.getenv('ALPHAVANTAGE_API_KEY') or None,
            longbridge_app_key=os.getenv('LONGBRIDGE_APP_KEY') or None,
            longbridge_app_secret=os.getenv('LONGBRIDGE_APP_SECRET') or None,
            longbridge_access_token=os.getenv('LONGBRIDGE_ACCESS_TOKEN') or None,
            longbridge_oauth_client_id=os.getenv('LONGBRIDGE_OAUTH_CLIENT_ID') or None,
            stock_index_remote_update_enabled=parse_env_bool(
                os.getenv('STOCK_INDEX_REMOTE_UPDATE_ENABLED'),
                default=False,
            ),
            litellm_model=litellm_model,
            litellm_fallback_models=litellm_fallback_models,
            llm_temperature=resolve_unified_llm_temperature(litellm_model),
            litellm_config_path=litellm_config_path,
            llm_models_source=llm_models_source,
            llm_channels=llm_channels,
            llm_channel_names=llm_channel_names,
            llm_model_list=llm_model_list,
            gemini_api_keys=gemini_api_keys,
            anthropic_api_keys=anthropic_api_keys,
            openai_api_keys=openai_api_keys,
            deepseek_api_keys=deepseek_api_keys,
            gemini_api_key=os.getenv('GEMINI_API_KEY'),
            gemini_model=os.getenv('GEMINI_MODEL', 'gemini-3.1-pro-preview'),
            gemini_model_fallback=os.getenv('GEMINI_MODEL_FALLBACK', 'gemini-3-flash-preview'),
            gemini_temperature=parse_env_float(os.getenv('GEMINI_TEMPERATURE'), 0.7, field_name='GEMINI_TEMPERATURE'),
            gemini_request_delay=parse_env_float(os.getenv('GEMINI_REQUEST_DELAY'), 2.0, field_name='GEMINI_REQUEST_DELAY', minimum=0.0),
            gemini_max_retries=parse_env_int(os.getenv('GEMINI_MAX_RETRIES'), 5, field_name='GEMINI_MAX_RETRIES', minimum=0),
            gemini_retry_delay=parse_env_float(os.getenv('GEMINI_RETRY_DELAY'), 5.0, field_name='GEMINI_RETRY_DELAY', minimum=0.0),
            anthropic_api_key=os.getenv('ANTHROPIC_API_KEY'),
            anthropic_model=os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-6'),
            anthropic_temperature=parse_env_float(os.getenv('ANTHROPIC_TEMPERATURE'), 0.7, field_name='ANTHROPIC_TEMPERATURE'),
            anthropic_max_tokens=parse_env_int(os.getenv('ANTHROPIC_MAX_TOKENS'), 8192, field_name='ANTHROPIC_MAX_TOKENS', minimum=1),
            # AIHubmix is the preferred OpenAI-compatible provider (one key, all models, no VPN required).
            # Within the OpenAI-compatible layer: AIHUBMIX_KEY takes priority over OPENAI_API_KEY.
            # Overall provider fallback order: Gemini > Anthropic > OpenAI-compatible (incl. AIHubmix).
            # base_url is auto-set to aihubmix.com/v1 when AIHUBMIX_KEY is used and no explicit
            # OPENAI_BASE_URL override is provided.
            # Model names match upstream (e.g. gemini-3.1-pro-preview, gpt-5.5, deepseek-v4-flash).
            openai_api_key=openai_api_keys[0] if openai_api_keys else None,
            openai_base_url=openai_base_url,
            openai_model=_openai_model_name,
            openai_vision_model=os.getenv('OPENAI_VISION_MODEL') or None,
            openai_temperature=parse_env_float(os.getenv('OPENAI_TEMPERATURE'), 0.7, field_name='OPENAI_TEMPERATURE'),
            # Vision model: VISION_MODEL > OPENAI_VISION_MODEL (alias) > default
            vision_model=(
                os.getenv('VISION_MODEL')
                or os.getenv('OPENAI_VISION_MODEL')
                or ""
            ),
            vision_provider_priority=os.getenv('VISION_PROVIDER_PRIORITY', 'gemini,anthropic,openai'),
            anspire_api_keys=anspire_api_keys,
            bocha_api_keys=bocha_api_keys,
            minimax_api_keys=minimax_api_keys,
            tavily_api_keys=tavily_api_keys,
            brave_api_keys=brave_api_keys,
            serpapi_keys=serpapi_keys,
            searxng_base_urls=searxng_base_urls,
            searxng_public_instances_enabled=searxng_public_instances_enabled,
            social_sentiment_api_key=os.getenv('SOCIAL_SENTIMENT_API_KEY') or None,
            social_sentiment_api_url=os.getenv('SOCIAL_SENTIMENT_API_URL', 'https://api.adanos.org').rstrip('/'),
            news_max_age_days=parse_env_int(os.getenv('NEWS_MAX_AGE_DAYS'), 3, field_name='NEWS_MAX_AGE_DAYS', minimum=1),
            news_strategy_profile=cls._parse_news_strategy_profile(
                os.getenv('NEWS_STRATEGY_PROFILE', 'short')
            ),
            bias_threshold=parse_env_float(os.getenv('BIAS_THRESHOLD'), 5.0, field_name='BIAS_THRESHOLD', minimum=1.0),
            agent_litellm_model=agent_litellm_model,
            agent_mode=os.getenv('AGENT_MODE', 'false').lower() == 'true',
            _agent_mode_explicit=os.getenv('AGENT_MODE') is not None,
            agent_max_steps=parse_env_int(
                os.getenv('AGENT_MAX_STEPS'),
                AGENT_MAX_STEPS_DEFAULT,
                field_name='AGENT_MAX_STEPS',
                minimum=1,
            ),
            agent_skills=[s.strip() for s in os.getenv('AGENT_SKILLS', '').split(',') if s.strip()],
            agent_skill_dir=os.getenv('AGENT_SKILL_DIR') or os.getenv('AGENT_STRATEGY_DIR'),
            agent_nl_routing=os.getenv('AGENT_NL_ROUTING', 'false').lower() == 'true',
            agent_arch=os.getenv('AGENT_ARCH', 'single').lower(),
            agent_orchestrator_mode=os.getenv('AGENT_ORCHESTRATOR_MODE', 'standard').lower(),
            agent_orchestrator_timeout_s=parse_env_int(
                os.getenv('AGENT_ORCHESTRATOR_TIMEOUT_S'),
                600,
                field_name='AGENT_ORCHESTRATOR_TIMEOUT_S',
                minimum=0,
            ),
            agent_risk_override=os.getenv('AGENT_RISK_OVERRIDE', 'true').lower() == 'true',
            agent_deep_research_budget=parse_env_int(
                os.getenv('AGENT_DEEP_RESEARCH_BUDGET'),
                30000,
                field_name='AGENT_DEEP_RESEARCH_BUDGET',
                minimum=5000,
            ),
            agent_deep_research_timeout=parse_env_int(
                os.getenv('AGENT_DEEP_RESEARCH_TIMEOUT'),
                180,
                field_name='AGENT_DEEP_RESEARCH_TIMEOUT',
                minimum=30,
            ),
            agent_memory_enabled=os.getenv('AGENT_MEMORY_ENABLED', 'false').lower() == 'true',
            agent_skill_autoweight=(
                os.getenv('AGENT_SKILL_AUTOWEIGHT')
                or os.getenv('AGENT_STRATEGY_AUTOWEIGHT', 'true')
            ).lower() == 'true',
            agent_skill_routing=(
                os.getenv('AGENT_SKILL_ROUTING')
                or os.getenv('AGENT_STRATEGY_ROUTING', 'auto')
            ).lower(),
            agent_context_compression_enabled=parse_env_bool(
                os.getenv('AGENT_CONTEXT_COMPRESSION_ENABLED'),
                default=False,
            ),
            agent_context_compression_profile=agent_context_compression_profile,
            agent_context_compression_trigger_tokens=agent_context_compression_trigger_tokens,
            agent_context_protected_turns=agent_context_protected_turns,
            agent_event_monitor_enabled=os.getenv('AGENT_EVENT_MONITOR_ENABLED', 'false').lower() == 'true',
            agent_event_monitor_interval_minutes=parse_env_int(
                os.getenv('AGENT_EVENT_MONITOR_INTERVAL_MINUTES'),
                5,
                field_name='AGENT_EVENT_MONITOR_INTERVAL_MINUTES',
                minimum=1,
            ),
            agent_event_alert_rules_json=os.getenv('AGENT_EVENT_ALERT_RULES_JSON', ''),
            wechat_webhook_url=os.getenv('WECHAT_WEBHOOK_URL'),
            feishu_webhook_url=os.getenv('FEISHU_WEBHOOK_URL'),
            feishu_webhook_secret=os.getenv('FEISHU_WEBHOOK_SECRET'),
            feishu_webhook_keyword=os.getenv('FEISHU_WEBHOOK_KEYWORD'),
            telegram_bot_token=os.getenv('TELEGRAM_BOT_TOKEN'),
            telegram_chat_id=os.getenv('TELEGRAM_CHAT_ID'),
            telegram_message_thread_id=os.getenv('TELEGRAM_MESSAGE_THREAD_ID'),
            email_sender=os.getenv('EMAIL_SENDER'),
            email_sender_name=os.getenv('EMAIL_SENDER_NAME', 'daily_stock_analysis股票分析助手'),
            email_password=os.getenv('EMAIL_PASSWORD'),
            email_receivers=[r.strip() for r in os.getenv('EMAIL_RECEIVERS', '').split(',') if r.strip()],
            stock_email_groups=cls._parse_stock_email_groups(),
            pushover_user_key=os.getenv('PUSHOVER_USER_KEY'),
            pushover_api_token=os.getenv('PUSHOVER_API_TOKEN'),
            ntfy_url=os.getenv('NTFY_URL'),
            ntfy_token=os.getenv('NTFY_TOKEN'),
            gotify_url=os.getenv('GOTIFY_URL'),
            gotify_token=os.getenv('GOTIFY_TOKEN'),
            pushplus_token=os.getenv('PUSHPLUS_TOKEN'),
            pushplus_topic=os.getenv('PUSHPLUS_TOPIC'),
            serverchan3_sendkey=os.getenv('SERVERCHAN3_SENDKEY'),
            custom_webhook_urls=[u.strip() for u in os.getenv('CUSTOM_WEBHOOK_URLS', '').split(',') if u.strip()],
            custom_webhook_bearer_token=os.getenv('CUSTOM_WEBHOOK_BEARER_TOKEN'),
            custom_webhook_body_template=os.getenv('CUSTOM_WEBHOOK_BODY_TEMPLATE'),
            webhook_verify_ssl=os.getenv('WEBHOOK_VERIFY_SSL', 'true').lower() == 'true',
            discord_bot_token=os.getenv('DISCORD_BOT_TOKEN'),
            discord_main_channel_id=(
                os.getenv('DISCORD_MAIN_CHANNEL_ID')
                or os.getenv('DISCORD_CHANNEL_ID')
            ),
            discord_webhook_url=os.getenv('DISCORD_WEBHOOK_URL'),
            discord_interactions_public_key=os.getenv('DISCORD_INTERACTIONS_PUBLIC_KEY'),
            slack_webhook_url=os.getenv('SLACK_WEBHOOK_URL'),
            slack_bot_token=os.getenv('SLACK_BOT_TOKEN'),
            slack_channel_id=os.getenv('SLACK_CHANNEL_ID'),
            astrbot_url=os.getenv('ASTRBOT_URL'),
            astrbot_token=os.getenv('ASTRBOT_TOKEN'),
            notification_report_channels=parse_notification_route_channels(
                os.getenv('NOTIFICATION_REPORT_CHANNELS')
            ),
            notification_alert_channels=parse_notification_route_channels(
                os.getenv('NOTIFICATION_ALERT_CHANNELS')
            ),
            notification_system_error_channels=parse_notification_route_channels(
                os.getenv('NOTIFICATION_SYSTEM_ERROR_CHANNELS')
            ),
            notification_dedup_ttl_seconds=parse_env_int(
                os.getenv('NOTIFICATION_DEDUP_TTL_SECONDS'),
                0,
                field_name='NOTIFICATION_DEDUP_TTL_SECONDS',
                minimum=0,
            ),
            notification_cooldown_seconds=parse_env_int(
                os.getenv('NOTIFICATION_COOLDOWN_SECONDS'),
                0,
                field_name='NOTIFICATION_COOLDOWN_SECONDS',
                minimum=0,
            ),
            notification_quiet_hours=(os.getenv('NOTIFICATION_QUIET_HOURS') or '').strip(),
            notification_timezone=(os.getenv('NOTIFICATION_TIMEZONE') or '').strip(),
            notification_min_severity=(os.getenv('NOTIFICATION_MIN_SEVERITY') or '').strip().lower(),
            notification_daily_digest_enabled=parse_env_bool(
                os.getenv('NOTIFICATION_DAILY_DIGEST_ENABLED'),
                default=False,
            ),
            single_stock_notify=os.getenv('SINGLE_STOCK_NOTIFY', 'false').lower() == 'true',
            report_type=cls._parse_report_type(os.getenv('REPORT_TYPE', 'simple')),
            report_language=cls._parse_report_language(report_language_raw),
            report_summary_only=os.getenv('REPORT_SUMMARY_ONLY', 'false').lower() == 'true',
            report_show_llm_model=report_show_llm_model,
            report_templates_dir=os.getenv('REPORT_TEMPLATES_DIR', 'templates'),
            report_renderer_enabled=os.getenv('REPORT_RENDERER_ENABLED', 'false').lower() == 'true',
            report_integrity_enabled=os.getenv('REPORT_INTEGRITY_ENABLED', 'true').lower() == 'true',
            report_integrity_retry=parse_env_int(os.getenv('REPORT_INTEGRITY_RETRY'), 1, field_name='REPORT_INTEGRITY_RETRY', minimum=0),
        llm_provider_timeout_seconds=parse_env_int(os.getenv('LLM_PROVIDER_TIMEOUT_SECONDS'), 45, field_name='LLM_PROVIDER_TIMEOUT_SECONDS', minimum=5),
        search_total_timeout_seconds=parse_env_int(os.getenv('SEARCH_TOTAL_TIMEOUT_SECONDS'), 8, field_name='SEARCH_TOTAL_TIMEOUT_SECONDS', minimum=3),
        data_fetch_timeout_seconds=parse_env_int(os.getenv('DATA_FETCH_TIMEOUT_SECONDS'), 120, field_name='DATA_FETCH_TIMEOUT_SECONDS', minimum=5),
            report_history_compare_n=parse_env_int(os.getenv('REPORT_HISTORY_COMPARE_N'), 0, field_name='REPORT_HISTORY_COMPARE_N', minimum=0),
            analysis_delay=parse_env_float(os.getenv('ANALYSIS_DELAY'), 0.0, field_name='ANALYSIS_DELAY', minimum=0.0),
            merge_email_notification=os.getenv('MERGE_EMAIL_NOTIFICATION', 'false').lower() == 'true',
            feishu_max_bytes=parse_env_int(os.getenv('FEISHU_MAX_BYTES'), 20000, field_name='FEISHU_MAX_BYTES', minimum=1),
            wechat_max_bytes=wechat_max_bytes,
            wechat_msg_type=wechat_msg_type_lower,
            discord_max_words=parse_env_int(os.getenv('DISCORD_MAX_WORDS'), 2000, field_name='DISCORD_MAX_WORDS', minimum=1),
            markdown_to_image_channels=[
                c.strip().lower()
                for c in os.getenv('MARKDOWN_TO_IMAGE_CHANNELS', '').split(',')
                if c.strip()
            ],
            markdown_to_image_max_chars=parse_env_int(
                os.getenv('MARKDOWN_TO_IMAGE_MAX_CHARS'),
                15000,
                field_name='MARKDOWN_TO_IMAGE_MAX_CHARS',
                minimum=1,
            ),
            md2img_engine=cls._parse_md2img_engine(os.getenv('MD2IMG_ENGINE', 'wkhtmltoimage')),
            prefetch_realtime_quotes=os.getenv('PREFETCH_REALTIME_QUOTES', 'true').lower() == 'true',
            database_path=os.getenv('DATABASE_PATH', './data/stock_analysis.db'),
            sqlite_wal_enabled=os.getenv('SQLITE_WAL_ENABLED', 'true').lower() == 'true',
            sqlite_busy_timeout_ms=parse_env_int(
                os.getenv('SQLITE_BUSY_TIMEOUT_MS'),
                5000,
                field_name='SQLITE_BUSY_TIMEOUT_MS',
                minimum=0,
            ),
            sqlite_write_retry_max=parse_env_int(
                os.getenv('SQLITE_WRITE_RETRY_MAX'),
                3,
                field_name='SQLITE_WRITE_RETRY_MAX',
                minimum=0,
            ),
            sqlite_write_retry_base_delay=parse_env_float(
                os.getenv('SQLITE_WRITE_RETRY_BASE_DELAY'),
                0.1,
                field_name='SQLITE_WRITE_RETRY_BASE_DELAY',
                minimum=0.0,
            ),
            save_context_snapshot=os.getenv('SAVE_CONTEXT_SNAPSHOT', 'true').lower() == 'true',
            backtest_enabled=os.getenv('BACKTEST_ENABLED', 'true').lower() == 'true',
            backtest_eval_window_days=parse_env_int(os.getenv('BACKTEST_EVAL_WINDOW_DAYS'), 10, field_name='BACKTEST_EVAL_WINDOW_DAYS', minimum=1),
            backtest_min_age_days=parse_env_int(os.getenv('BACKTEST_MIN_AGE_DAYS'), 14, field_name='BACKTEST_MIN_AGE_DAYS', minimum=1),
            backtest_engine_version=os.getenv('BACKTEST_ENGINE_VERSION', 'v1'),
            backtest_neutral_band_pct=parse_env_float(
                os.getenv('BACKTEST_NEUTRAL_BAND_PCT'),
                2.0,
                field_name='BACKTEST_NEUTRAL_BAND_PCT',
                minimum=0.0,
            ),
            log_dir=os.getenv('LOG_DIR', './logs'),
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            max_workers=parse_env_int(os.getenv('MAX_WORKERS'), 3, field_name='MAX_WORKERS', minimum=1),
            debug=os.getenv('DEBUG', 'false').lower() == 'true',
            config_validate_mode=os.getenv('CONFIG_VALIDATE_MODE', 'warn').lower(),
            http_proxy=os.getenv('HTTP_PROXY'),
            https_proxy=os.getenv('HTTPS_PROXY'),
            schedule_enabled=cls._resolve_env_value(
                'SCHEDULE_ENABLED',
                default='false',
                prefer_env_file=True,
            ).lower() == 'true',
            schedule_time=(schedule_time_value or '18:00').strip() or '18:00',
            schedule_run_immediately=schedule_run_immediately,
            run_immediately=legacy_run_immediately,
            market_review_enabled=os.getenv('MARKET_REVIEW_ENABLED', 'true').lower() == 'true',
            market_review_region=cls._parse_market_review_region(
                os.getenv('MARKET_REVIEW_REGION', 'tw')
            ),
            market_review_regions=cls._parse_market_review_regions_multi(
                os.getenv('MARKET_REVIEW_REGIONS', '')
            ),
            market_review_color_scheme=cls._parse_market_review_color_scheme(
                os.getenv('MARKET_REVIEW_COLOR_SCHEME', 'green_up')
            ),
            trading_day_check_enabled=os.getenv('TRADING_DAY_CHECK_ENABLED', 'true').lower() != 'false',
            route_b_enforce_market_scope=parse_env_bool(
                os.getenv('ROUTE_B_ENFORCE_MARKET_SCOPE'), default=False
            ),
            route_b_markets=cls._parse_route_b_markets(
                os.getenv('ROUTE_B_MARKETS', 'TW,US')
            ),
            webui_enabled=os.getenv('WEBUI_ENABLED', 'false').lower() == 'true',
            webui_host=os.getenv('WEBUI_HOST', '127.0.0.1'),
            webui_port=parse_env_int(os.getenv('WEBUI_PORT'), 8000, field_name='WEBUI_PORT', minimum=1, maximum=65535),
            # 機器人配置
            bot_enabled=os.getenv('BOT_ENABLED', 'true').lower() == 'true',
            bot_command_prefix=os.getenv('BOT_COMMAND_PREFIX', '/'),
            bot_rate_limit_requests=parse_env_int(os.getenv('BOT_RATE_LIMIT_REQUESTS'), 10, field_name='BOT_RATE_LIMIT_REQUESTS', minimum=1),
            bot_rate_limit_window=parse_env_int(os.getenv('BOT_RATE_LIMIT_WINDOW'), 60, field_name='BOT_RATE_LIMIT_WINDOW', minimum=1),
            bot_admin_users=[u.strip() for u in os.getenv('BOT_ADMIN_USERS', '').split(',') if u.strip()],
            # 飛書機器人
            feishu_verification_token=os.getenv('FEISHU_VERIFICATION_TOKEN'),
            feishu_encrypt_key=os.getenv('FEISHU_ENCRYPT_KEY'),
            feishu_stream_enabled=os.getenv('FEISHU_STREAM_ENABLED', 'false').lower() == 'true',
            # 釘釘機器人
            dingtalk_app_key=os.getenv('DINGTALK_APP_KEY'),
            dingtalk_app_secret=os.getenv('DINGTALK_APP_SECRET'),
            dingtalk_stream_enabled=os.getenv('DINGTALK_STREAM_ENABLED', 'false').lower() == 'true',
            # 企業微信機器人
            wecom_corpid=os.getenv('WECOM_CORPID'),
            wecom_token=os.getenv('WECOM_TOKEN'),
            wecom_encoding_aes_key=os.getenv('WECOM_ENCODING_AES_KEY'),
            wecom_agent_id=os.getenv('WECOM_AGENT_ID'),
            # Telegram
            telegram_webhook_secret=os.getenv('TELEGRAM_WEBHOOK_SECRET'),
            # Discord 機器人擴充套件配置
            discord_bot_status=os.getenv('DISCORD_BOT_STATUS', '台股 / 美股智慧分析 | /help'),
            # 實時行情增強資料配置
            enable_realtime_quote=os.getenv('ENABLE_REALTIME_QUOTE', 'true').lower() == 'true',
            enable_realtime_technical_indicators=os.getenv(
                'ENABLE_REALTIME_TECHNICAL_INDICATORS', 'true'
            ).lower() == 'true',
            enable_chip_distribution=os.getenv('ENABLE_CHIP_DISTRIBUTION', 'false').lower() == 'true',
            enable_value_network_mermaid=os.getenv('ENABLE_VALUE_NETWORK_MERMAID', 'true').lower() == 'true',
            enable_four_masters_commentary=os.getenv('ENABLE_FOUR_MASTERS_COMMENTARY', 'true').lower() == 'true',
            # 東財介面補丁開關
            enable_eastmoney_patch=os.getenv('ENABLE_EASTMONEY_PATCH', 'false').lower() == 'true',
            # 實時行情資料來源優先順序：
            # - tencent: 第三方財經資料源，有量比/換手率/PE/PB等，單股查詢穩定（推薦）
            # - akshare_sina: 新浪財經，基本行情穩定，但無量比
            # - efinance/akshare_em: 東財全量介面，資料最全但容易被封
            # - tushare: Tushare Pro，需要2000積分，資料全面
            realtime_source_priority=cls._resolve_realtime_source_priority(),
            realtime_cache_ttl=parse_env_int(os.getenv('REALTIME_CACHE_TTL'), 600, field_name='REALTIME_CACHE_TTL', minimum=0),
            circuit_breaker_cooldown=parse_env_int(os.getenv('CIRCUIT_BREAKER_COOLDOWN'), 300, field_name='CIRCUIT_BREAKER_COOLDOWN', minimum=0),
            enable_fundamental_pipeline=os.getenv('ENABLE_FUNDAMENTAL_PIPELINE', 'true').lower() == 'true',
            fundamental_stage_timeout_seconds=parse_env_float(
                os.getenv('FUNDAMENTAL_STAGE_TIMEOUT_SECONDS'),
                FUNDAMENTAL_STAGE_TIMEOUT_SECONDS_DEFAULT,
                field_name='FUNDAMENTAL_STAGE_TIMEOUT_SECONDS',
                minimum=0.0,
            ),
            fundamental_fetch_timeout_seconds=parse_env_float(
                os.getenv('FUNDAMENTAL_FETCH_TIMEOUT_SECONDS'),
                3.0,
                field_name='FUNDAMENTAL_FETCH_TIMEOUT_SECONDS',
                minimum=0.0,
            ),
            fundamental_retry_max=parse_env_int(os.getenv('FUNDAMENTAL_RETRY_MAX'), 1, field_name='FUNDAMENTAL_RETRY_MAX', minimum=0),
            fundamental_cache_ttl_seconds=parse_env_int(
                os.getenv('FUNDAMENTAL_CACHE_TTL_SECONDS'),
                120,
                field_name='FUNDAMENTAL_CACHE_TTL_SECONDS',
                minimum=0,
            ),
            fundamental_cache_max_entries=parse_env_int(
                os.getenv('FUNDAMENTAL_CACHE_MAX_ENTRIES'),
                256,
                field_name='FUNDAMENTAL_CACHE_MAX_ENTRIES',
                minimum=1,
            ),
            portfolio_risk_concentration_alert_pct=parse_env_float(
                os.getenv('PORTFOLIO_RISK_CONCENTRATION_ALERT_PCT'),
                35.0,
                field_name='PORTFOLIO_RISK_CONCENTRATION_ALERT_PCT',
                minimum=0.0,
            ),
            portfolio_risk_drawdown_alert_pct=parse_env_float(
                os.getenv('PORTFOLIO_RISK_DRAWDOWN_ALERT_PCT'),
                15.0,
                field_name='PORTFOLIO_RISK_DRAWDOWN_ALERT_PCT',
                minimum=0.0,
            ),
            portfolio_risk_stop_loss_alert_pct=parse_env_float(
                os.getenv('PORTFOLIO_RISK_STOP_LOSS_ALERT_PCT'),
                10.0,
                field_name='PORTFOLIO_RISK_STOP_LOSS_ALERT_PCT',
                minimum=0.0,
            ),
            portfolio_risk_stop_loss_near_ratio=parse_env_float(
                os.getenv('PORTFOLIO_RISK_STOP_LOSS_NEAR_RATIO'),
                0.8,
                field_name='PORTFOLIO_RISK_STOP_LOSS_NEAR_RATIO',
                minimum=0.0,
            ),
            portfolio_risk_lookback_days=parse_env_int(
                os.getenv('PORTFOLIO_RISK_LOOKBACK_DAYS'),
                180,
                field_name='PORTFOLIO_RISK_LOOKBACK_DAYS',
                minimum=1,
            ),
            portfolio_fx_update_enabled=os.getenv('PORTFOLIO_FX_UPDATE_ENABLED', 'true').lower() == 'true',
            alphasift_route_enabled=parse_env_bool(os.getenv('ALPHASIFT_ROUTE_ENABLED'), default=False),
            alphasift_enabled=parse_env_bool(os.getenv('ALPHASIFT_ENABLED'), default=False),
            alphasift_install_spec=(
                DEFAULT_ALPHASIFT_INSTALL_SPEC
                if os.getenv('ALPHASIFT_INSTALL_SPEC') is None
                else os.getenv('ALPHASIFT_INSTALL_SPEC', '').strip()
            ),
        )
    
    @classmethod
    def _parse_litellm_yaml(cls, config_path: str) -> List[Dict[str, Any]]:
        """Parse a standard LiteLLM config YAML file into Router model_list.

        Supports the ``os.environ/VAR_NAME`` syntax for secret references.
        Returns an empty list on any error (logged, never raises).
        """
        import logging
        _logger = logging.getLogger(__name__)
        try:
            import yaml
        except ImportError:
            _logger.warning("PyYAML not installed; LITELLM_CONFIG ignored. Install with: pip install pyyaml")
            return []

        path = Path(config_path)
        if not path.is_absolute():
            path = Path(__file__).parent.parent / path
        if not path.exists():
            _logger.warning(f"LITELLM_CONFIG file not found: {path}")
            return []

        try:
            with open(path, encoding='utf-8') as f:
                yaml_config = yaml.safe_load(f) or {}
        except Exception as e:
            _logger.warning(f"Failed to parse LITELLM_CONFIG: {e}")
            return []

        model_list = yaml_config.get('model_list', [])
        if not isinstance(model_list, list):
            _logger.warning("LITELLM_CONFIG: model_list must be a list")
            return []

        # Resolve os.environ/ references in string params
        for entry in model_list:
            params = entry.get('litellm_params', {})
            for key in list(params.keys()):
                val = params.get(key)
                if isinstance(val, str) and val.startswith('os.environ/'):
                    env_name = val.split('/', 1)[1]
                    params[key] = os.getenv(env_name, '')

        _logger.info(f"LITELLM_CONFIG: loaded {len(model_list)} model deployment(s) from {path}")
        return model_list

    @classmethod
    def _parse_llm_channels(cls, channels_str: str) -> List[Dict[str, Any]]:
        """Parse LLM_CHANNELS env var and per-channel env vars.

        Format:
            LLM_CHANNELS=aihubmix,deepseek,gemini
            LLM_AIHUBMIX_PROTOCOL=openai
            LLM_AIHUBMIX_BASE_URL=https://aihubmix.com/v1
            LLM_AIHUBMIX_API_KEY=sk-xxx           (or LLM_AIHUBMIX_API_KEYS=k1,k2)
            LLM_AIHUBMIX_MODELS=gpt-5.5,claude-sonnet-4-6
            LLM_AIHUBMIX_ENABLED=true
        """
        import logging
        _logger = logging.getLogger(__name__)

        channels: List[Dict[str, Any]] = []
        for raw_name in channels_str.split(','):
            ch_name = raw_name.strip()
            if not ch_name:
                continue
            ch_lower = ch_name.lower()
            ch_upper = ch_name.upper()

            base_url = os.getenv(f'LLM_{ch_upper}_BASE_URL', '').strip() or None
            if ch_lower == "anspire" and not base_url:
                base_url = (
                    os.getenv('ANSPIRE_LLM_BASE_URL') or ANSPIRE_LLM_BASE_URL_DEFAULT
                ).strip() or None
            protocol_raw = os.getenv(f'LLM_{ch_upper}_PROTOCOL', '').strip()
            if ch_lower == "anspire" and not protocol_raw:
                protocol_raw = "openai"
            enabled_raw = os.getenv(f'LLM_{ch_upper}_ENABLED')
            if ch_lower == "anspire" and (enabled_raw is None or not enabled_raw.strip()):
                enabled_raw = os.getenv('ANSPIRE_LLM_ENABLED')
            enabled = parse_env_bool(enabled_raw, default=True)

            # API keys: LLM_{NAME}_API_KEYS (multi) > LLM_{NAME}_API_KEY (single)
            api_keys_raw = os.getenv(f'LLM_{ch_upper}_API_KEYS', '')
            api_keys = [k.strip() for k in api_keys_raw.split(',') if k.strip()]
            if not api_keys:
                single_key = os.getenv(f'LLM_{ch_upper}_API_KEY', '').strip()
                if single_key:
                    api_keys = [single_key]
            if not api_keys and ch_lower == "anspire":
                anspire_keys_raw = os.getenv('ANSPIRE_API_KEYS', '')
                api_keys = [k.strip() for k in anspire_keys_raw.split(',') if k.strip()]

            # Models
            models_raw = os.getenv(f'LLM_{ch_upper}_MODELS', '')
            raw_models = [m.strip() for m in models_raw.split(',') if m.strip()]
            if not raw_models and ch_lower == "anspire":
                anspire_model = (
                    os.getenv('ANSPIRE_LLM_MODEL') or ANSPIRE_LLM_MODEL_DEFAULT
                ).strip()
                if anspire_model:
                    raw_models = [anspire_model]
            protocol = resolve_llm_channel_protocol(protocol_raw, base_url=base_url, models=raw_models, channel_name=ch_name)
            models = [normalize_llm_channel_model(m, protocol, base_url) for m in raw_models]

            # Extra headers (JSON string, optional)
            extra_headers_raw = os.getenv(f'LLM_{ch_upper}_EXTRA_HEADERS', '').strip()
            extra_headers = None
            if extra_headers_raw:
                try:
                    extra_headers = json.loads(extra_headers_raw)
                except json.JSONDecodeError:
                    _logger.warning(f"LLM_{ch_upper}_EXTRA_HEADERS: invalid JSON, ignored")

            if not enabled:
                _logger.info(f"LLM channel '{ch_name}': disabled, skipped")
                continue

            if protocol_raw and canonicalize_llm_channel_protocol(protocol_raw) not in SUPPORTED_LLM_CHANNEL_PROTOCOLS:
                _logger.warning(
                    "LLM_%s_PROTOCOL=%s is unsupported; auto-detected protocol=%s",
                    ch_upper,
                    protocol_raw,
                    protocol or "unknown",
                )

            if not api_keys and channel_allows_empty_api_key(protocol, base_url):
                api_keys = [""]

            if not api_keys:
                _logger.warning(f"LLM channel '{ch_name}': no API key configured, skipped")
                continue
            if not models:
                _logger.warning(f"LLM channel '{ch_name}': no models configured, skipped")
                continue

            channels.append({
                'name': ch_name.lower(),
                'protocol': protocol,
                'enabled': enabled,
                'base_url': base_url,
                'api_keys': api_keys,
                'models': models,
                'extra_headers': extra_headers,
            })
            _logger.info(f"LLM channel '{ch_name}': {len(models)} model(s), {len(api_keys)} key(s)")

        return channels

    @classmethod
    def _channels_to_model_list(cls, channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert parsed LLM channels to LiteLLM Router model_list format."""
        model_list: List[Dict[str, Any]] = []
        for ch in channels:
            for model_name in ch['models']:
                for api_key in ch['api_keys']:
                    litellm_params: Dict[str, Any] = {
                        'model': model_name,
                    }
                    if api_key:
                        litellm_params['api_key'] = api_key
                    if ch['base_url']:
                        litellm_params['api_base'] = ch['base_url']
                    # Auto-inject aihubmix sponsored header
                    headers = dict(ch.get('extra_headers') or {})
                    if ch['base_url'] and 'aihubmix.com' in ch['base_url']:
                        headers.setdefault('APP-Code', 'GPIJ3886')
                    if headers:
                        litellm_params['extra_headers'] = headers

                    model_list.append({
                        'model_name': model_name,
                        'litellm_params': litellm_params,
                    })
        return model_list

    @classmethod
    def _legacy_keys_to_model_list(
        cls,
        gemini_keys: List[str],
        anthropic_keys: List[str],
        openai_keys: List[str],
        openai_base_url: Optional[str],
        deepseek_keys: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Build Router model_list from legacy per-provider keys (backward compat).

        Returns a model_list where each provider's keys are expanded into
        deployments, keyed by placeholder model_name tokens.  The analyzer
        resolves actual model_names at call time from LITELLM_MODEL /
        LITELLM_FALLBACK_MODELS.
        """
        model_list: List[Dict[str, Any]] = []

        # Gemini keys
        for k in gemini_keys:
            if k and len(k) >= 8:
                model_list.append({
                    'model_name': '__legacy_gemini__',
                    'litellm_params': {'model': '__legacy_gemini__', 'api_key': k},
                })

        # Anthropic keys
        for k in anthropic_keys:
            if k and len(k) >= 8:
                model_list.append({
                    'model_name': '__legacy_anthropic__',
                    'litellm_params': {'model': '__legacy_anthropic__', 'api_key': k},
                })

        # OpenAI-compatible keys
        for k in openai_keys:
            if k and len(k) >= 8:
                params: Dict[str, Any] = {'model': '__legacy_openai__', 'api_key': k}
                if openai_base_url:
                    params['api_base'] = openai_base_url
                if openai_base_url and 'aihubmix.com' in openai_base_url:
                    params['extra_headers'] = {'APP-Code': 'GPIJ3886'}
                model_list.append({
                    'model_name': '__legacy_openai__',
                    'litellm_params': params,
                })

        # DeepSeek keys (native litellm provider — auto-resolves api_base)
        for k in (deepseek_keys or []):
            if k and len(k) >= 8:
                model_list.append({
                    'model_name': '__legacy_deepseek__',
                    'litellm_params': {
                        'model': '__legacy_deepseek__',
                        'api_key': k,
                    },
                })

        return model_list

    @classmethod
    def _parse_stock_email_groups(cls) -> List[Tuple[List[str], List[str]]]:
        """
        Parse STOCK_GROUP_N and EMAIL_GROUP_N from environment.
        Returns [(stocks, emails), ...] ordered by group index.
        Stock codes are canonicalized via normalize_stock_code so that
        runtime routing matches the same equivalence used in validation.
        """
        from data_provider.base import normalize_stock_code

        groups: dict = {}
        stock_re = re.compile(r'^STOCK_GROUP_(\d+)$', re.IGNORECASE)
        email_re = re.compile(r'^EMAIL_GROUP_(\d+)$', re.IGNORECASE)
        for key in os.environ:
            m = stock_re.match(key)
            if m:
                idx = int(m.group(1))
                val = os.environ[key].strip()
                groups.setdefault(idx, {})['stocks'] = [
                    normalize_stock_code(c.strip())
                    for c in val.split(',') if c.strip()
                ]
            m = email_re.match(key)
            if m:
                idx = int(m.group(1))
                val = os.environ[key].strip()
                groups.setdefault(idx, {})['emails'] = [e.strip() for e in val.split(',') if e.strip()]
        result = []
        for idx in sorted(groups.keys()):
            g = groups[idx]
            if 'stocks' in g and 'emails' in g and g['stocks'] and g['emails']:
                result.append((g['stocks'], g['emails']))
        return result

    @classmethod
    def _parse_report_type(cls, value: str) -> str:
        """Parse REPORT_TYPE, fallback to simple for invalid values (supports brief)."""
        v = (value or 'simple').strip().lower()
        if v in ('simple', 'full', 'brief'):
            return v
        import logging
        logging.getLogger(__name__).warning(
            f"REPORT_TYPE '{value}' invalid, fallback to 'simple' (valid: simple/full/brief)"
        )
        return 'simple'

    @classmethod
    def _get_env_file_value(cls, key: str) -> Optional[str]:
        """Read one config key directly from the active `.env` file."""
        env_file = os.getenv("ENV_FILE")
        env_path = Path(env_file) if env_file else (Path(__file__).parent.parent / ".env")
        if not env_path.exists():
            return None

        try:
            env_values = dotenv_values(env_path)
        except Exception as exc:  # pragma: no cover - defensive branch
            logging.getLogger(__name__).warning(
                "Failed to read %s while resolving %s: %s",
                env_path,
                key,
                exc,
            )
            return None

        value = env_values.get(key)
        if value is None:
            return None
        return str(value)

    @classmethod
    def _resolve_env_value(
        cls,
        key: str,
        *,
        default: Optional[str] = None,
        prefer_env_file: bool = False,
    ) -> Optional[str]:
        """Resolve one env value, optionally preferring the persisted `.env` copy."""
        env_value = os.getenv(key)
        file_value = cls._get_env_file_value(key)

        should_prefer_file = prefer_env_file or key in cls._WEBUI_RUNTIME_ENV_FILE_PRIORITY_KEYS
        if should_prefer_file and file_value is not None:
            if env_value is not None and cls._has_bootstrap_runtime_env_override(key):
                return env_value
            return file_value
        if env_value is not None:
            return env_value
        if file_value is not None:
            return file_value
        return default

    @classmethod
    def _capture_bootstrap_runtime_env_overrides(cls) -> None:
        """Remember process-provided runtime env overrides before dotenv mutates os.environ.

        Called by ``setup_env()`` **before** ``load_dotenv()``, so ``os.environ``
        only contains genuine process-level values (Docker ``environment:``,
        Dockerfile ``ENV``, shell exports, etc.).

        A key is treated as an explicit override when it is present in
        ``os.environ`` and either:
        * absent from the persisted ``.env`` file, **or**
        * present with a **different** value.

        When both values are identical, the distinction is irrelevant and we
        do **not** flag the key, so that a later ``.env`` update by WebUI can
        take effect on config reload without requiring a container restart.
        """
        if cls._BOOTSTRAP_RUNTIME_ENV_OVERRIDES_CAPTURED:
            return

        explicit_overrides = set()
        present_keys = set()
        for key in cls._WEBUI_RUNTIME_ENV_FILE_PRIORITY_KEYS:
            env_value = os.environ.get(key)
            if env_value is None:
                continue

            present_keys.add(key)
            file_value = cls._get_env_file_value(key)
            if file_value is None or env_value != file_value:
                explicit_overrides.add(key)

        cls._BOOTSTRAP_RUNTIME_ENV_OVERRIDES = frozenset(explicit_overrides)
        cls._BOOTSTRAP_RUNTIME_ENV_PRESENT_KEYS = frozenset(present_keys)
        cls._BOOTSTRAP_RUNTIME_ENV_OVERRIDES_CAPTURED = True

    @classmethod
    def _has_bootstrap_runtime_env_override(cls, key: str) -> bool:
        cls._capture_bootstrap_runtime_env_overrides()
        return key in cls._BOOTSTRAP_RUNTIME_ENV_OVERRIDES

    @classmethod
    def _had_bootstrap_runtime_env_key(cls, key: str) -> bool:
        cls._capture_bootstrap_runtime_env_overrides()
        return key in cls._BOOTSTRAP_RUNTIME_ENV_PRESENT_KEYS

    @classmethod
    def _resolve_report_language_env_value(
        cls,
        preexisting_env_value: Optional[str],
    ) -> str:
        """Resolve REPORT_LANGUAGE while preserving real process env overrides."""
        file_value = cls._get_env_file_value("REPORT_LANGUAGE")
        env_value = os.getenv("REPORT_LANGUAGE")

        if preexisting_env_value is not None:
            env_text = preexisting_env_value.strip()
            file_text = (file_value or "").strip()
            if file_text and env_text and env_text.lower() != file_text.lower():
                env_file = os.getenv("ENV_FILE") or str(Path(__file__).parent.parent / ".env")
                logging.getLogger(__name__).warning(
                    "REPORT_LANGUAGE environment value '%s' overrides %s ('%s')",
                    preexisting_env_value,
                    env_file,
                    file_value,
                )
            return preexisting_env_value

        if file_value is not None:
            return file_value

        return env_value or "zh_TW"

    @classmethod
    def _parse_report_language(cls, value: Optional[str]) -> str:
        """Parse REPORT_LANGUAGE, fallback to zh_TW for invalid values."""
        normalized = normalize_report_language(value, default="zh_TW")
        raw = (value or "").strip()
        if raw and not is_supported_report_language_value(raw):
            logging.getLogger(__name__).warning(
                "REPORT_LANGUAGE '%s' invalid, fallback to 'zh_TW' (valid: zh/zh_TW/en)",
                value,
            )
        return normalized

    @classmethod
    def _parse_news_strategy_profile(cls, value: Optional[str]) -> str:
        """Parse NEWS_STRATEGY_PROFILE, fallback to short for invalid values."""
        normalized = normalize_news_strategy_profile(value)
        raw = (value or "short").strip().lower()
        if raw != normalized:
            logging.getLogger(__name__).warning(
                "NEWS_STRATEGY_PROFILE '%s' invalid, fallback to 'short' "
                "(valid: ultra_short/short/medium/long)",
                value,
            )
        return normalized

    def get_effective_news_window_days(self) -> int:
        """Return effective news window days after profile + max-age merge."""
        return resolve_news_window_days(
            news_max_age_days=self.news_max_age_days,
            news_strategy_profile=self.news_strategy_profile,
        )

    @classmethod
    def _parse_market_review_region(cls, value: str) -> str:
        """解析大盤覆盤市場區域，非法值記錄警告後回退為 tw"""
        import logging
        v = (value or 'tw').strip().lower()
        if v in ('tw', 'us', 'all'):
            return v
        if v == 'both':
            return 'all'
        logging.getLogger(__name__).warning(
            f"MARKET_REVIEW_REGION 配置值 '{value}' 無效，已回退為預設值 'tw'（合法值：tw / us / all）"
        )
        return 'tw'

    @classmethod
    def _parse_market_review_regions_multi(cls, value: str) -> List[str]:
        """Parse MARKET_REVIEW_REGIONS (e.g. 'TW,US') into internal region codes.

        Accepted values (case-insensitive): tw, us, cn, hk.
        Returns an empty list when value is blank (falls back to market_review_region).
        """
        _map = {"tw": "tw", "us": "us", "cn": "cn", "hk": "hk"}
        if not value or not value.strip():
            return []
        regions: List[str] = []
        for item in value.split(","):
            item = item.strip().lower()
            if not item:
                continue
            mapped = _map.get(item)
            if mapped:
                regions.append(mapped)
            else:
                logger.warning(
                    "MARKET_REVIEW_REGIONS 中未知區域值 %r，已忽略（合法值：tw / us / cn / hk）",
                    item,
                )
        return regions

    @classmethod
    def _parse_route_b_markets(cls, value: str) -> List[str]:
        """Parse ROUTE_B_MARKETS (e.g. 'TW,US') into uppercase market codes.

        Falls back to ['TW', 'US'] when value is blank or invalid.
        """
        if not value or not value.strip():
            return ["TW", "US"]
        _valid = {"TW", "US", "HK", "CN"}
        markets: List[str] = []
        for item in value.split(","):
            item = item.strip().upper()
            if not item:
                continue
            if item in _valid:
                markets.append(item)
            else:
                logger.warning(
                    "ROUTE_B_MARKETS 中未知市場值 %r，已忽略（合法值：TW / US / HK / CN）",
                    item,
                )
        return markets if markets else ["TW", "US"]

    @classmethod
    def _parse_market_review_color_scheme(cls, value: str) -> str:
        """Parse market-review index change color scheme."""
        import logging
        v = (value or 'green_up').strip().lower().replace('-', '_')
        if v in ('green_up', 'red_up'):
            return v
        logging.getLogger(__name__).warning(
            "MARKET_REVIEW_COLOR_SCHEME 配置值 '%s' 無效，已回退為預設值 'green_up'（合法值：green_up / red_up）",
            value,
        )
        return 'green_up'

    @classmethod
    def _parse_md2img_engine(cls, value: str) -> str:
        """Parse MD2IMG_ENGINE, fallback to wkhtmltoimage for invalid values (Issue #455)."""
        v = (value or 'wkhtmltoimage').strip().lower()
        if v in ('wkhtmltoimage', 'markdown-to-file'):
            return v
        if v:
            import logging
            logging.getLogger(__name__).warning(
                f"MD2IMG_ENGINE '{value}' invalid, fallback to 'wkhtmltoimage' "
                "(valid: wkhtmltoimage | markdown-to-file)"
            )
        return 'wkhtmltoimage'

    @classmethod
    def _resolve_realtime_source_priority(cls) -> str:
        """
        Resolve realtime source priority with automatic tushare injection.

        When TUSHARE_TOKEN is configured but REALTIME_SOURCE_PRIORITY is not
        explicitly set, automatically prepend 'tushare' to the default priority
        so that the paid data source is utilized for realtime quotes as well.
        """
        explicit = os.getenv('REALTIME_SOURCE_PRIORITY')
        default_priority = 'tencent,akshare_sina,efinance,akshare_em'

        if explicit:
            # User explicitly set priority, respect it
            return explicit

        tushare_token = os.getenv('TUSHARE_TOKEN', '').strip()
        if tushare_token:
            # Token configured but no explicit priority override
            # Prepend tushare so the paid source is tried first
            import logging
            logger = logging.getLogger(__name__)
            resolved = f'tushare,{default_priority}'
            logger.info(
                f"TUSHARE_TOKEN detected, auto-injecting tushare into realtime priority: {resolved}"
            )
            return resolved

        return default_priority

    @classmethod
    def reset_instance(cls) -> None:
        """重置單例（主要用於測試）"""
        cls._instance = None
        cls._BOOTSTRAP_RUNTIME_ENV_OVERRIDES_CAPTURED = False
        cls._BOOTSTRAP_RUNTIME_ENV_OVERRIDES = frozenset()
        cls._BOOTSTRAP_RUNTIME_ENV_PRESENT_KEYS = frozenset()

    def has_searxng_enabled(self) -> bool:
        """Whether SearXNG fallback is enabled via self-hosted or public mode."""
        return bool(self.searxng_base_urls) or bool(self.searxng_public_instances_enabled)

    def has_search_capability_enabled(self) -> bool:
        """Whether any search provider is configured or SearXNG fallback is enabled."""
        return bool(
            self.anspire_api_keys
            or self.bocha_api_keys
            or self.minimax_api_keys
            or self.tavily_api_keys
            or self.brave_api_keys
            or self.serpapi_keys
            or self.has_searxng_enabled()
        )

    def is_agent_available(self) -> bool:
        """Check whether agent capabilities are usable.

        Decision table:

        +-----------------------+----------------------------------+---------+
        | AGENT_MODE env        | effective Agent primary model set| Result  |
        +-----------------------+----------------------------------+---------+
        | ``true``              | any                              | True    |
        | ``false`` (explicit)  | any                              | False   |
        | not set (default)     | yes                              | True    |
        | not set (default)     | no                               | False   |
        +-----------------------+----------------------------------+---------+

        This keeps backward compatibility: users who never touch
        ``AGENT_MODE`` get agent features automatically once they configure an
        Agent-effective model, while ``AGENT_MODE=false`` acts as an explicit
        kill-switch.
        """
        # Explicit AGENT_MODE takes full precedence
        if self._agent_mode_explicit:
            return self.agent_mode
        # Auto-detect: Agent inherits global model when AGENT_LITELLM_MODEL is empty.
        return bool(get_effective_agent_primary_model(self))

    def refresh_stock_list(self) -> None:
        """
        熱讀取 STOCK_LIST 環境變數並更新配置中的自選股列表
        
        支援兩種配置方式：
        1. .env 檔案（本地開發、定時任務模式） - 修改後下次執行自動生效
        2. 系統環境變數（GitHub Actions、Docker） - 啟動時固定，執行中不變
        """
        # 優先從 .env 檔案讀取最新配置，這樣即使在容器環境中修改了 .env 檔案，
        # 也能獲取到最新的股票列表配置
        env_file = os.getenv("ENV_FILE")
        env_path = Path(env_file) if env_file else (Path(__file__).parent.parent / '.env')
        stock_list_str = ''
        if env_path.exists():
            # 直接從 .env 檔案讀取最新的配置
            env_values = dotenv_values(env_path)
            stock_list_str = (env_values.get('STOCK_LIST') or '').strip()

        # 如果 .env 檔案不存在或未配置，才嘗試從系統環境變數讀取
        if not stock_list_str:
            stock_list_str = os.getenv('STOCK_LIST', '')

        stock_list = [
            (c or "").strip().upper()
            for c in stock_list_str.split(',')
            if (c or "").strip()
        ]

        self.stock_list = stock_list
    
    def validate_structured(self) -> List[ConfigIssue]:
        """Return structured validation issues with severity levels.

        Covers all three LLM configuration tiers introduced by PR #494:
        - LITELLM_CONFIG (YAML)
        - LLM_CHANNELS (env)
        - Legacy per-provider keys

        Returns:
            List of ConfigIssue objects, each carrying a severity
            ("error" | "warning" | "info"), a human-readable message, and the
            primary environment variable / field name it relates to.
        """
        issues: List[ConfigIssue] = []

        # --- Stock list ---
        if not self.stock_list:
            issues.append(ConfigIssue(
                severity="error",
                message="未配置 STOCK_LIST。請設定至少一個股票代號，例如：2330,2454,AAPL,NVDA。",
                field="STOCK_LIST",
            ))
        elif self.stock_email_groups:
            from data_provider.base import normalize_stock_code
            configured_stock_set = {
                normalize_stock_code(code)
                for code in self.stock_list
                if (code or "").strip()
            }
            missing_group_stocks_dict: Dict[str, None] = {}
            for stocks, _emails in self.stock_email_groups:
                for stock in stocks:
                    raw = (stock or "").strip()
                    if not raw:
                        continue
                    normalized_stock = normalize_stock_code(stock)
                    if normalized_stock in configured_stock_set:
                        continue
                    if normalized_stock in missing_group_stocks_dict:
                        continue
                    missing_group_stocks_dict[normalized_stock] = None
            missing_group_stocks = list(missing_group_stocks_dict.keys())
            if missing_group_stocks:
                issues.append(ConfigIssue(
                    severity="warning",
                    message=(
                        "檢測到 STOCK_GROUP_N 中存在未包含在 STOCK_LIST 內的股票："
                        f"{', '.join(missing_group_stocks[:6])}。"
                        "STOCK_GROUP_N 僅用於郵件路由，不會擴大分析範圍；"
                        "請先將這些股票加入 STOCK_LIST。"
                    ),
                    field="STOCK_GROUP_N",
                ))

        # --- Data sources (informational only) ---
        if not self.tushare_token:
            issues.append(ConfigIssue(
                severity="info",
                message="未配置 Tushare Token，將使用其他資料來源",
                field="TUSHARE_TOKEN",
            ))

        # --- LLM availability ---
        # llm_model_list is populated for YAML / channels / managed legacy keys.
        # Other LiteLLM-native providers (for example cohere/*) run through the
        # direct litellm env path and therefore do not populate llm_model_list.
        has_direct_env_model = bool(self.litellm_model) and _uses_direct_env_provider(self.litellm_model)
        if not self.llm_model_list and not has_direct_env_model:
            if self.litellm_config_path:
                issues.append(ConfigIssue(
                    severity="error",
                    message=(
                        "已配置 LITELLM_CONFIG，但未解析出可用模型。"
                        "請檢查 YAML 中的 model_list、litellm_params 和環境變數引用。"
                    ),
                    field="LITELLM_CONFIG",
                ))
            elif self.llm_channel_names:
                issues.append(ConfigIssue(
                    severity="error",
                    message=(
                        "已配置 LLM_CHANNELS，但未解析出可用模型通道。"
                        "請檢查對應 LLM_<CHANNEL>_API_KEY(S)、"
                        "LLM_<CHANNEL>_MODELS、LLM_<CHANNEL>_PROTOCOL 或 Base URL。"
                    ),
                    field="LLM_CHANNELS",
                ))
            else:
                issues.append(ConfigIssue(
                    severity="error",
                    message=(
                        "未配置任何可用的 AI 模型接入。請至少配置 ANSPIRE_API_KEYS、"
                        "AIHUBMIX_KEY、GEMINI_API_KEY、ANTHROPIC_API_KEY、"
                        "OPENAI_API_KEY 或 DEEPSEEK_API_KEY 中的一個，或配置 "
                        "LITELLM_CONFIG / LLM_CHANNELS 可用模型通道。"
                    ),
                    field="LITELLM_CONFIG",
                ))
        elif not self.litellm_model:
            issues.append(ConfigIssue(
                severity="info",
                message=(
                    "尚未明確指定主模型，系統將自動從可用 API Key 推斷。"
                    "建議儘早配置主模型（格式如 gemini/gemini-3.1-pro-preview）"
                ),
                field="LITELLM_MODEL",
            ))

        available_router_models = get_configured_llm_models(self.llm_model_list)
        available_router_model_set = set(available_router_models)

        def _has_runtime_source_for_model(model: str) -> bool:
            if not model or _uses_direct_env_provider(model):
                return True
            provider = _get_litellm_provider(model)
            if provider in {"gemini", "vertex_ai"}:
                return any(k and len(k) >= 8 for k in (self.gemini_api_keys or []))
            if provider == "anthropic":
                return any(k and len(k) >= 8 for k in (self.anthropic_api_keys or []))
            if provider == "deepseek":
                return any(k and len(k) >= 8 for k in (self.deepseek_api_keys or []))
            if provider == "openai":
                return any(k and len(k) >= 8 for k in (self.openai_api_keys or []))
            return False

        configured_agent_primary_model = bool((self.agent_litellm_model or "").strip())
        effective_agent_primary_model = get_effective_agent_primary_model(self)

        if available_router_model_set:
            if (
                self.litellm_model
                and not _uses_direct_env_provider(self.litellm_model)
                and self.litellm_model not in available_router_model_set
            ):
                issues.append(ConfigIssue(
                    severity="error",
                    message=(
                        "已配置的主模型未出現在當前通道或高階模型路由配置中。"
                        f" 當前可用模型：{', '.join(available_router_models[:6])}"
                    ),
                    field="LITELLM_MODEL",
                ))

            if (
                configured_agent_primary_model
                and effective_agent_primary_model
                and not _uses_direct_env_provider(effective_agent_primary_model)
                and effective_agent_primary_model not in available_router_model_set
            ):
                issues.append(ConfigIssue(
                    severity="error",
                    message=(
                        "已配置的 Agent 主模型未出現在當前通道或高階模型路由配置中。"
                        f" 當前可用模型：{', '.join(available_router_models[:6])}"
                    ),
                    field="AGENT_LITELLM_MODEL",
                ))

            invalid_fallbacks = [
                model for model in (self.litellm_fallback_models or [])
                if model and model not in available_router_model_set
                and not _uses_direct_env_provider(model)
            ]
            if invalid_fallbacks:
                issues.append(ConfigIssue(
                    severity="warning",
                    message=(
                        "備選模型中包含未在當前通道或高階模型路由配置中宣告的模型："
                        f"{', '.join(invalid_fallbacks[:3])}"
                    ),
                    field="LITELLM_FALLBACK_MODELS",
                ))

            if (
                self.vision_model
                and not _uses_direct_env_provider(self.vision_model)
                and self.vision_model not in available_router_model_set
            ):
                issues.append(ConfigIssue(
                    severity="warning",
                    message=(
                        "VISION_MODEL 未出現在當前通道宣告中。"
                        f" 當前可用模型：{', '.join(available_router_models[:6])}"
                    ),
                    field="VISION_MODEL",
                ))
        elif (
            configured_agent_primary_model
            and effective_agent_primary_model
            and not _has_runtime_source_for_model(effective_agent_primary_model)
        ):
            issues.append(ConfigIssue(
                severity="error",
                message=(
                    "已配置 Agent 主模型，但未找到可用的執行時來源"
                    "（啟用通道或匹配的 API Key）。"
                ),
                field="AGENT_LITELLM_MODEL",
            ))

        # --- Search engine (informational only) ---
        if not self.has_search_capability_enabled():
            issues.append(ConfigIssue(
                severity="info",
                message="未配置搜尋引擎能力 (Bocha/MiniMax/Tavily/Brave/SerpAPI/SearXNG)，新聞搜尋功能將不可用",
                field="BOCHA_API_KEYS",
            ))

        # --- Notification channels ---
        has_notification = bool(
            self.wechat_webhook_url
            or self.feishu_webhook_url
            or (self.telegram_bot_token and self.telegram_chat_id)
            or (self.email_sender and self.email_password)
            or (self.pushover_user_key and self.pushover_api_token)
            or _has_ntfy_topic_endpoint(self.ntfy_url)
            or (
                self.gotify_url
                and (self.gotify_token or "").strip()
                and _has_gotify_base_url(self.gotify_url)
            )
            or self.pushplus_token
            or self.serverchan3_sendkey
            or self.custom_webhook_urls
            or self.astrbot_url
            or (self.discord_bot_token and self.discord_main_channel_id)
            or self.discord_webhook_url
            or self.slack_webhook_url
            or (self.slack_bot_token and self.slack_channel_id)
        )

        if not has_notification:
            issues.append(ConfigIssue(
                severity="warning",
                message="未配置通知通道，將不傳送推送通知",
                field="WECHAT_WEBHOOK_URL",
            ))

        has_telegram_token = bool((self.telegram_bot_token or "").strip())
        has_telegram_chat_id = bool((self.telegram_chat_id or "").strip())
        if has_telegram_token != has_telegram_chat_id:
            issues.append(ConfigIssue(
                severity="error",
                message="Telegram 通知配置不完整：TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID 必須同時配置。",
                field="TELEGRAM_CHAT_ID" if has_telegram_token else "TELEGRAM_BOT_TOKEN",
            ))

        has_email_sender = bool((self.email_sender or "").strip())
        has_email_password = bool((self.email_password or "").strip())
        if has_email_sender != has_email_password:
            issues.append(ConfigIssue(
                severity="error",
                message="郵件通知配置不完整：EMAIL_SENDER 和 EMAIL_PASSWORD 必須同時配置。",
                field="EMAIL_PASSWORD" if has_email_sender else "EMAIL_SENDER",
            ))

        def _warn_if_webhook_url_invalid(field: str, value: Optional[str]) -> None:
            raw_url = (value or "").strip()
            if not raw_url:
                return
            parsed = urlparse(raw_url)
            if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
                return
            issues.append(ConfigIssue(
                severity="warning",
                message=f"{field} 看起來不是有效 URL，請確認是否以 http:// 或 https:// 開頭。",
                field=field,
            ))

        for field, value in (
            ("WECHAT_WEBHOOK_URL", self.wechat_webhook_url),
            ("FEISHU_WEBHOOK_URL", self.feishu_webhook_url),
            ("DISCORD_WEBHOOK_URL", self.discord_webhook_url),
            ("SLACK_WEBHOOK_URL", self.slack_webhook_url),
            ("ASTRBOT_URL", self.astrbot_url),
        ):
            _warn_if_webhook_url_invalid(field, value)

        for custom_url in self.custom_webhook_urls:
            _warn_if_webhook_url_invalid("CUSTOM_WEBHOOK_URLS", custom_url)

        if self.ntfy_url and not _has_ntfy_topic_endpoint(self.ntfy_url):
            issues.append(ConfigIssue(
                severity="error",
                message="NTFY_URL 必須包含 topic path，例如 https://ntfy.sh/my-topic",
                field="NTFY_URL",
            ))

        if self.gotify_url and not _has_gotify_base_url(self.gotify_url):
            issues.append(ConfigIssue(
                severity="error",
                message="GOTIFY_URL 必須是 Gotify server base URL，不包含 /message，例如 https://gotify.example",
                field="GOTIFY_URL",
            ))

        if (
            self.gotify_url
            and _has_gotify_base_url(self.gotify_url)
            and not (self.gotify_token or "").strip()
        ):
            issues.append(ConfigIssue(
                severity="warning",
                message="已配置 GOTIFY_URL，但缺少 GOTIFY_TOKEN，Gotify 通道不會啟用",
                field="GOTIFY_TOKEN",
            ))

        if self.notification_quiet_hours:
            try:
                parse_notification_quiet_hours(self.notification_quiet_hours)
            except ValueError as exc:
                issues.append(ConfigIssue(
                    severity="error",
                    message=f"通知靜默時段配置無效：{exc}",
                    field="NOTIFICATION_QUIET_HOURS",
                ))

        if self.notification_timezone:
            try:
                validate_notification_timezone(self.notification_timezone)
            except ValueError as exc:
                issues.append(ConfigIssue(
                    severity="error",
                    message=f"通知時區配置無效：{exc}",
                    field="NOTIFICATION_TIMEZONE",
                ))

        if self.notification_min_severity and not is_supported_notification_severity(self.notification_min_severity):
            issues.append(ConfigIssue(
                severity="error",
                message=(
                    "通知最低階別配置無效，允許值："
                    f"{', '.join(NOTIFICATION_SEVERITIES)}"
                ),
                field="NOTIFICATION_MIN_SEVERITY",
            ))

        if self.notification_daily_digest_enabled:
            issues.append(ConfigIssue(
                severity="warning",
                message=(
                    "NOTIFICATION_DAILY_DIGEST_ENABLED 當前為預留配置；"
                    "P4 不會傳送每日摘要或持久化摘要內容。"
                ),
                field="NOTIFICATION_DAILY_DIGEST_ENABLED",
            ))

        has_feishu_app_id = bool((self.feishu_app_id or "").strip())
        has_feishu_app_secret = bool((self.feishu_app_secret or "").strip())
        has_feishu_app_credentials = has_feishu_app_id or has_feishu_app_secret
        has_feishu_doc_token = bool((self.feishu_folder_token or "").strip())
        has_feishu_full_cloud_doc_credentials = (
            has_feishu_app_id
            and has_feishu_app_secret
            and has_feishu_doc_token
        )
        if (
            has_feishu_app_credentials
            and not has_feishu_full_cloud_doc_credentials
            and not self.feishu_webhook_url
            and not (self.feishu_stream_enabled and has_feishu_app_id and has_feishu_app_secret)
        ):
            issues.append(ConfigIssue(
                severity="warning",
                message=(
                    "僅配置 FEISHU_APP_ID / FEISHU_APP_SECRET 不會開啟飛書群 Webhook 推送；"
                    "如需群訊息通知，請配置 FEISHU_WEBHOOK_URL。若要使用應用機器人，請同時開啟 "
                    "FEISHU_STREAM_ENABLED 並完成應用釋出與許可權配置。"
                ),
                field="FEISHU_WEBHOOK_URL",
            ))

        # --- Deprecated field migration hints ---
        if os.getenv("OPENAI_VISION_MODEL"):
            issues.append(ConfigIssue(
                severity="info",
                message=(
                    "OPENAI_VISION_MODEL 已廢棄，請改用 VISION_MODEL。"
                    "當前值已自動遷移，建議更新配置檔案以消除此提示。"
                ),
                field="OPENAI_VISION_MODEL",
            ))

        # --- Vision key availability ---
        # Only warn when user explicitly set VISION_MODEL (or OPENAI_VISION_MODEL alias).
        # Skipped when vision_model is empty (Vision not intentionally configured).
        if self.vision_model:
            # Maps provider prefix → the corresponding key list tracked by Config.
            # vertex_ai shares gemini keys; other LiteLLM-native providers are not
            # in this map (their keys come from env vars, which we cannot inspect here).
            _VISION_KEY_MAP = {
                "gemini": self.gemini_api_keys,
                "vertex_ai": self.gemini_api_keys,
                "anthropic": self.anthropic_api_keys,
                "openai": self.openai_api_keys,
                "deepseek": self.deepseek_api_keys,
            }
            # Derive the primary model's provider prefix so that its key is also
            # checked even when the provider is absent from VISION_PROVIDER_PRIORITY.
            _primary_prefix = (
                self.vision_model.split("/")[0]
                if "/" in self.vision_model
                else "openai"
            )
            _priority_providers = [
                p.strip().lower()
                for p in self.vision_provider_priority.split(",")
                if p.strip()
            ]
            # Union: fallback providers + primary model's own provider
            _all_providers = {_primary_prefix} | set(_priority_providers)

            # Align with get_api_keys_for_model: keys must be non-empty and len >= 8
            _has_any_key = any(
                any(k and len(k) >= 8 for k in (_VISION_KEY_MAP.get(p) or []))
                for p in _all_providers
                if p in _VISION_KEY_MAP
            )
            if not _has_any_key:
                _checked = sorted(_all_providers & _VISION_KEY_MAP.keys())
                issues.append(ConfigIssue(
                    severity="warning",
                    message=(
                        "VISION_MODEL 已配置，但未找到可用的 Vision API Key "
                        f"（已檢查：{', '.join(_checked)}）。"
                        "圖片股票代號提取功能將不可用，請配置對應的 API Key。"
                    ),
                    field="VISION_MODEL",
                ))

        return issues

    def validate(self) -> List[str]:
        """Return validation messages as plain strings (backward-compatible).

        Internally delegates to validate_structured().  Callers that only need
        the human-readable strings can continue to use this method unchanged.

        Returns:
            List of message strings, one per ConfigIssue.
        """
        return [issue.message for issue in self.validate_structured()]
    
    def get_db_url(self) -> str:
        """
        獲取 SQLAlchemy 資料庫連線 URL
        
        自動建立資料庫目錄（如果不存在）
        """
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path.absolute()}"


# === 便捷的配置訪問函式 ===
def get_config() -> Config:
    """獲取全域性配置例項的快捷方式"""
    return Config.get_instance()


# ============================================================
# Shared LLM helpers (used by both analyzer and agent/llm_adapter)
# ============================================================

def get_api_keys_for_model(model: str, config: Config) -> List[str]:
    """Return explicitly managed API keys for a litellm model (legacy path only).

    When llm_model_list is populated (channels / YAML), the Router handles key
    selection, so this function is not needed.  Kept for backward compat when
    no Router is built and a direct litellm.completion() call is needed.
    """
    provider = _get_litellm_provider(model)
    if provider in {"gemini", "vertex_ai"}:
        return [k for k in config.gemini_api_keys if k and len(k) >= 8]
    if provider == "anthropic":
        return [k for k in config.anthropic_api_keys if k and len(k) >= 8]
    if provider == "deepseek":
        return [k for k in config.deepseek_api_keys if k and len(k) >= 8]
    if provider == "openai":
        return [k for k in config.openai_api_keys if k and len(k) >= 8]
    # Other LiteLLM-native providers – API key resolved from env vars
    return []


def extra_litellm_params(model: str, config: Config) -> Dict[str, Any]:
    """Build extra litellm params for a model (legacy path only).

    When llm_model_list is populated, the Router already carries api_base
    and headers per-deployment, so this is not called.
    """
    params: Dict[str, Any] = {}
    # deepseek/ provider: litellm auto-resolves api_base, no manual override needed
    if model.startswith("deepseek/"):
        return params
    if model.startswith("openai/") or "/" not in model:
        if config.openai_base_url:
            params["api_base"] = config.openai_base_url
        if config.openai_base_url and "aihubmix.com" in config.openai_base_url:
            params["extra_headers"] = {"APP-Code": "GPIJ3886"}
    return params


if __name__ == "__main__":
    # 測試配置載入
    config = get_config()
    print("=== 配置載入測試 ===")
    print(f"自選股列表: {config.stock_list}")
    print(f"資料庫路徑: {config.database_path}")
    print(f"最大併發數: {config.max_workers}")
    print(f"除錯模式: {config.debug}")
    
    # 驗證配置
    warnings = config.validate()
    if warnings:
        print("\n配置驗證結果:")
        for w in warnings:
            print(f"  - {w}")
