# -*- coding: utf-8 -*-
"""LLM usage normalization and prompt-message HMAC telemetry."""

from __future__ import annotations

from collections.abc import Iterable as IterableABC
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

PROVIDER_USAGE_SCHEMA_NAME = "provider_usage_v1"
PROVIDER_USAGE_SCHEMA_VERSION = "2026-06-10"
PROVIDER_USAGE_MAX_SIZE_BYTES = 4096

DEFAULT_HMAC_DOMAIN = "prompt_message"
DEFAULT_HASH_SCOPE = "deployment"
DEFAULT_HMAC_KEY_VERSION = "local-v1"
LEGACY_AUDIT_MESSAGE_SEPARATOR = "\n\n---legacy-message---\n\n"

_LEGACY_AUDIT_MARKER_NAMES = frozenset(
    {
        "stock_code",
        "stock_name",
        "analysis_date",
        "market_phase",
        "daily_market_context",
        "analysis_context_pack",
        "quote",
        "news_context",
    }
)

_HMAC_SECRET_CACHE: Optional[bytes] = None
_DROP_RAW_USAGE_VALUE = object()
_OPENAI_LITELLM_PROVIDER = "openai"
_OPENAI_COMPATIBLE_PROVIDER = "openai_compatible"
_ALLOWED_RAW_USAGE_SCALAR_KEYS = {
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "prompt_token_count",
    "input_token_count",
    "candidates_token_count",
    "output_token_count",
    "total_token_count",
    "cached_tokens",
    "cached_content_token_count",
    "cache_read_tokens",
    "cache_write_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
    "estimated_prefix_tokens",
}
_ALLOWED_RAW_USAGE_DETAIL_KEYS = {
    "prompt_tokens_details",
    "completion_tokens_details",
    "input_tokens_details",
    "output_tokens_details",
    "input_token_details",
    "output_token_details",
}
_ALLOWED_RAW_USAGE_DETAIL_SCALAR_KEYS = {
    "accepted_prediction_tokens",
    "audio_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "cached_tokens",
    "image_tokens",
    "reasoning_tokens",
    "rejected_prediction_tokens",
    "text_tokens",
}
_PROVIDER_USAGE_SIGNAL_TOKEN_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "prompt_token_count",
    "input_token_count",
    "candidates_token_count",
    "output_token_count",
    "total_token_count",
    "normalized_prompt_tokens",
    "normalized_completion_tokens",
    "normalized_total_tokens",
    "normalized_cache_read_tokens",
    "normalized_cache_write_tokens",
    "normalized_cache_miss_tokens",
    "provider_reported_prompt_tokens",
    "provider_reported_cached_tokens",
)
_PROVIDER_USAGE_JSON_SIGNAL_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "prompt_token_count",
    "input_token_count",
    "candidates_token_count",
    "output_token_count",
    "total_token_count",
    "cached_tokens",
    "cached_content_token_count",
    "cache_read_tokens",
    "cache_write_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "prompt_cache_hit_tokens",
    "prompt_cache_miss_tokens",
)
_PROVIDER_USAGE_JSON_DETAIL_SIGNAL_KEYS = (
    "accepted_prediction_tokens",
    "audio_tokens",
    "cache_creation_input_tokens",
    "cache_creation_tokens",
    "cache_read_input_tokens",
    "cached_tokens",
    "image_tokens",
    "reasoning_tokens",
    "rejected_prediction_tokens",
    "text_tokens",
)
_USAGE_COUNT_SCALAR_KEYS = frozenset(_ALLOWED_RAW_USAGE_SCALAR_KEYS)
_USAGE_COUNT_DETAIL_KEYS = frozenset(_ALLOWED_RAW_USAGE_DETAIL_SCALAR_KEYS)


def extract_usage_payload(response: Any) -> Any:
    """Return usage using signal-aware public fields before private fallback.

    Order:
    1. provider/LiteLLM public ``usage`` field when it has usable signals
    2. LiteLLM public ``usage_metadata`` field when it has usable signals
    3. ``_hidden_params["usage"]`` as LiteLLM private best-effort fallback

    The private fallback is also used for LiteLLM streaming chunks where public
    usage exists but only carries zero/no-signal counts. Invalid public counts
    are preserved so downstream normalization can record diagnostics.
    """
    if response is None:
        return None
    if isinstance(response, Mapping):
        return _select_usage_payload(
            response.get("usage"),
            response.get("usage_metadata"),
            _extract_hidden_usage_payload(response.get("_hidden_params")),
        )
    return _select_usage_payload(
        getattr(response, "usage", None),
        getattr(response, "usage_metadata", None),
        _extract_hidden_usage_payload(getattr(response, "_hidden_params", None)),
    )


def _extract_hidden_usage_payload(hidden_params: Any) -> Any:
    """Return LiteLLM private/internal usage fallback, if present.

    ``_hidden_params["usage"]`` is a best-effort LiteLLM implementation detail,
    not a stable public response contract.
    """
    if isinstance(hidden_params, Mapping):
        return hidden_params.get("usage")
    return None


def _select_usage_payload(public_usage: Any, usage_metadata: Any, hidden_usage: Any) -> Any:
    public_payloads = (public_usage, usage_metadata)
    public_payload = None
    for payload in public_payloads:
        if payload is None:
            continue
        if public_payload is None:
            public_payload = payload
        if _usage_payload_has_invalid_counts(payload):
            return payload
        if _usage_payload_has_count_signal(payload):
            return payload

    if public_payload is not None and _usage_payload_has_count_signal(hidden_usage):
        return hidden_usage

    if public_payload is not None:
        return public_payload
    return hidden_usage


def _usage_payload_has_count_signal(payload: Any) -> bool:
    usage = _to_plain(payload)
    if not usage:
        return False
    for key in set(_PROVIDER_USAGE_SIGNAL_TOKEN_KEYS).union(_PROVIDER_USAGE_JSON_SIGNAL_KEYS):
        if key in usage and _usage_count_is_nonzero(usage.get(key)):
            return True
    for detail_key in _ALLOWED_RAW_USAGE_DETAIL_KEYS:
        detail = usage.get(detail_key)
        if not isinstance(detail, Mapping):
            continue
        for key in _PROVIDER_USAGE_JSON_DETAIL_SIGNAL_KEYS:
            if key in detail and _usage_count_is_nonzero(detail.get(key)):
                return True
    return False


def _usage_payload_has_invalid_counts(payload: Any) -> bool:
    usage = _to_plain(payload)
    return bool(usage) and _has_invalid_usage_count_values(usage)


def has_provider_usage_payload(usage: Mapping[str, Any] | None) -> bool:
    """Return whether a usage dict represents provider-reported token usage."""
    if not usage:
        return False

    for key in _PROVIDER_USAGE_SIGNAL_TOKEN_KEYS:
        if key in usage and _usage_value_is_nonzero(usage.get(key)):
            return True

    return _provider_usage_json_has_count_signal(usage.get("provider_usage_json"))


def should_persist_usage_telemetry(usage: Mapping[str, Any] | None) -> bool:
    """Return whether usage should be persisted as provider telemetry."""
    if not usage:
        return False
    return has_provider_usage_payload(usage) or usage.get("cache_observation") == "invalid_provider_usage"


def _provider_usage_json_has_count_signal(provider_usage_json: Any) -> bool:
    if isinstance(provider_usage_json, str):
        payload_text = provider_usage_json.strip()
        if not payload_text:
            return False
        try:
            payload = json.loads(payload_text)
        except (TypeError, ValueError):
            return False
    elif isinstance(provider_usage_json, Mapping):
        payload = provider_usage_json
    else:
        return False

    if not isinstance(payload, Mapping) or not payload:
        return False

    for key in _PROVIDER_USAGE_JSON_SIGNAL_KEYS:
        if _usage_count_is_nonzero(payload.get(key)):
            return True

    for detail_key in _ALLOWED_RAW_USAGE_DETAIL_KEYS:
        detail = payload.get(detail_key)
        if not isinstance(detail, Mapping):
            continue
        for key in _PROVIDER_USAGE_JSON_DETAIL_SIGNAL_KEYS:
            if _usage_count_is_nonzero(detail.get(key)):
                return True

    return False


def normalize_litellm_usage(
    usage_obj: Any,
    *,
    model: str = "",
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize provider usage without changing request or response behavior."""
    usage = _to_plain(usage_obj)
    provider_name = _infer_provider(model, provider)
    raw_json = _safe_provider_usage_json(usage)
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    result: Dict[str, Any] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "provider_usage_json": raw_json,
        "provider_usage_schema_name": PROVIDER_USAGE_SCHEMA_NAME if raw_json else None,
        "provider_usage_schema_version": PROVIDER_USAGE_SCHEMA_VERSION if raw_json else None,
        "provider_usage_observed_at": observed_at if raw_json else None,
        "normalized_prompt_tokens": None,
        "normalized_completion_tokens": None,
        "normalized_total_tokens": None,
        "normalized_cache_read_tokens": None,
        "normalized_cache_write_tokens": None,
        "normalized_cache_miss_tokens": None,
        "normalized_uncached_input_tokens": None,
        "normalized_cache_eligible_input_tokens": None,
        "normalized_cache_hit_ratio": None,
        "normalized_cache_write_ratio": None,
        "cache_capability": "unknown",
        "cache_eligibility": "unknown",
        "cache_observation": "no_usage" if not usage else "unknown",
        "estimated_prefix_tokens": None,
        "provider_reported_prompt_tokens": None,
        "provider_reported_cached_tokens": None,
        "provider_min_cache_tokens": None,
        "eligibility_confidence": "unknown",
        "tokenizer_name": None,
        "tokenizer_version": None,
    }

    if not usage:
        return result

    invalid_token_usage = _has_invalid_usage_count_values(usage)

    prompt_tokens = _first_int(
        usage,
        "prompt_tokens",
        "input_tokens",
        "prompt_token_count",
        "input_token_count",
    )
    completion_tokens = _first_int(
        usage,
        "completion_tokens",
        "output_tokens",
        "candidates_token_count",
        "output_token_count",
    )
    total_tokens = _first_int(usage, "total_tokens", "total_token_count")

    cache_read: Optional[int] = None
    cache_write: Optional[int] = None
    cache_miss: Optional[int] = None
    provider_min_cache_tokens: Optional[int] = None
    cache_field_observed = False
    capability = "unknown"
    has_deepseek_hit_miss_shape = _has_deepseek_hit_miss_shape(usage)

    if has_deepseek_hit_miss_shape or provider_name == "deepseek":
        hit_tokens = _first_int(usage, "prompt_cache_hit_tokens")
        miss_tokens = _first_int(usage, "prompt_cache_miss_tokens")
        if hit_tokens is not None or miss_tokens is not None:
            cache_read = hit_tokens or 0
            cache_miss = miss_tokens or 0
            cache_field_observed = True
            capability = "supported"
            if prompt_tokens is None:
                prompt_tokens = (cache_read or 0) + (cache_miss or 0)
            result["normalized_uncached_input_tokens"] = cache_miss
    elif provider_name == "openai":
        cached = _nested_int(usage, ("prompt_tokens_details", "cached_tokens"))
        if cached is not None:
            cache_read = cached
            cache_field_observed = True
            capability = "supported"
        provider_min_cache_tokens = 1024
    elif provider_name in {"glm", "qwen", "dashscope", _OPENAI_COMPATIBLE_PROVIDER}:
        cached = _nested_int(usage, ("prompt_tokens_details", "cached_tokens"))
        if cached is not None:
            cache_read = cached
            cache_field_observed = True
            capability = "supported"
    elif provider_name == "anthropic":
        read_tokens = _first_int(usage, "cache_read_input_tokens")
        creation_tokens = _first_int(usage, "cache_creation_input_tokens")
        input_tokens = _first_int(usage, "input_tokens")
        if read_tokens is not None or creation_tokens is not None:
            cache_read = read_tokens or 0
            cache_write = creation_tokens or 0
            cache_field_observed = True
            capability = "supported"
            if input_tokens is not None:
                prompt_tokens = input_tokens + (cache_read or 0) + (cache_write or 0)
                result["normalized_uncached_input_tokens"] = input_tokens
    elif provider_name in {"gemini", "vertex_ai"}:
        cached = _first_int(usage, "cache_read_input_tokens")
        if cached is None:
            cached = _nested_int(usage, ("prompt_tokens_details", "cached_tokens"))
        if cached is None:
            cached = _first_int(
                usage,
                "cached_content_token_count",
                "cache_read_tokens",
            )
        if cached is not None:
            cache_read = cached
            cache_field_observed = True
            capability = "supported"
    elif provider_name in {"kimi", "moonshot", "minimax", "stepfun"}:
        cached = _first_int(usage, "cached_tokens")
        if cached is not None:
            cache_read = cached
            cache_field_observed = True
            capability = "supported"
    elif provider_name == "openrouter":
        read_tokens = _first_int(usage, "cache_read_tokens")
        write_tokens = _first_int(usage, "cache_write_tokens")
        if read_tokens is not None or write_tokens is not None:
            cache_read = read_tokens or 0
            cache_write = write_tokens or 0
            cache_field_observed = True
            capability = "supported"

    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    result["provider_reported_prompt_tokens"] = prompt_tokens
    result["provider_reported_cached_tokens"] = cache_read
    result["provider_min_cache_tokens"] = provider_min_cache_tokens

    result["cache_capability"] = capability

    eligible_tokens = _eligible_input_tokens(prompt_tokens, provider_min_cache_tokens, capability)
    invalid_provider_usage = (
        invalid_token_usage
        or _has_impossible_total_tokens(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        or _has_invalid_cache_usage(
            prompt_tokens=prompt_tokens,
            cache_read=cache_read,
            cache_write=cache_write,
            cache_miss=cache_miss,
            capability=capability,
        )
    )
    if invalid_provider_usage:
        result["cache_eligibility"] = "unknown"
        result["cache_observation"] = "invalid_provider_usage"
        result["eligibility_confidence"] = "invalid"
        result["normalized_uncached_input_tokens"] = None
        return result

    result["prompt_tokens"] = prompt_tokens or 0
    result["completion_tokens"] = completion_tokens or 0
    result["total_tokens"] = total_tokens or 0
    result["normalized_prompt_tokens"] = prompt_tokens
    result["normalized_completion_tokens"] = completion_tokens
    result["normalized_total_tokens"] = total_tokens
    result["normalized_cache_read_tokens"] = cache_read
    result["normalized_cache_write_tokens"] = cache_write
    result["normalized_cache_miss_tokens"] = cache_miss

    if result["normalized_uncached_input_tokens"] is None and prompt_tokens is not None and cache_read is not None:
        result["normalized_uncached_input_tokens"] = max(prompt_tokens - cache_read - (cache_write or 0), 0)

    result["normalized_cache_eligible_input_tokens"] = eligible_tokens
    result["cache_eligibility"] = _cache_eligibility(prompt_tokens, provider_min_cache_tokens, capability)
    result["eligibility_confidence"] = "exact" if prompt_tokens is not None else "unknown"
    result["cache_observation"] = _cache_observation(
        has_usage=True,
        cache_field_observed=cache_field_observed,
        cache_read=cache_read,
        cache_write=cache_write,
        cache_miss=cache_miss,
        eligible_tokens=eligible_tokens,
    )
    result["normalized_cache_hit_ratio"] = _ratio(cache_read, eligible_tokens)
    result["normalized_cache_write_ratio"] = _ratio(cache_write, eligible_tokens)
    return result


def attach_message_hmacs(
    usage: Dict[str, Any],
    messages: Optional[Sequence[Mapping[str, Any]]],
    *,
    hash_scope: str = DEFAULT_HASH_SCOPE,
) -> Dict[str, Any]:
    """Attach message-level HMAC fields without storing prompt content."""
    result = dict(usage or {})
    hmac_fields = build_message_hmacs(messages, hash_scope=hash_scope)
    result.update(hmac_fields)
    return result


def attach_legacy_message_stability_audit(
    usage: Dict[str, Any],
    messages: Optional[Sequence[Mapping[str, Any]]],
    audit_context: Optional[Mapping[str, Any]] = None,
    *,
    hash_scope: str = DEFAULT_HASH_SCOPE,
) -> Dict[str, Any]:
    """Attach P0.5a legacy message stability diagnostics to usage telemetry.

    The audit reuses message HMACs and records only stable metadata plus marker
    offsets. Marker search values are never persisted.
    """
    result = attach_message_hmacs(usage, messages, hash_scope=hash_scope)
    context = audit_context or {}
    message_list = list(messages or [])
    marker_specs = context.get("known_dynamic_markers")
    if marker_specs is None:
        marker_specs = context.get("dynamic_markers")
    if marker_specs is None:
        marker_specs = context.get("markers")

    canonical_render, content_starts = _render_legacy_audit_messages(message_list)
    marker_positions, first_marker_render_offset = _legacy_marker_positions(
        message_list,
        content_starts,
        marker_specs,
    )

    approx_common_prefix_chars: Optional[int] = first_marker_render_offset
    approx_common_prefix_tokens = (
        _estimate_chars_as_tokens(approx_common_prefix_chars)
        if approx_common_prefix_chars is not None
        else None
    )
    estimated_total_prompt_tokens = _estimate_chars_as_tokens(len(canonical_render))

    result.update(
        {
            "language": _audit_scalar(context.get("language"), max_len=16),
            "market_group": _audit_scalar(context.get("market_group"), max_len=16),
            "analysis_mode": _audit_scalar(context.get("analysis_mode"), max_len=64),
            "legacy_prompt_mode": _audit_scalar(context.get("legacy_prompt_mode"), max_len=32),
            "skill_config_hmac": _legacy_skill_config_hmac(context),
            "provider": _audit_scalar(context.get("provider"), max_len=64),
            "transport": _audit_scalar(context.get("transport"), max_len=64),
            "message_count": len(message_list),
            "estimated_total_prompt_tokens": estimated_total_prompt_tokens,
            "approx_common_prefix_chars": approx_common_prefix_chars,
            "approx_common_prefix_tokens": approx_common_prefix_tokens,
            "known_dynamic_marker_positions": json.dumps(
                marker_positions,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
    )

    if result.get("eligibility_confidence") in (None, "", "unknown"):
        result["eligibility_confidence"] = "estimated"
    return result


def build_message_hmacs(
    messages: Optional[Sequence[Mapping[str, Any]]],
    *,
    hash_scope: str = DEFAULT_HASH_SCOPE,
) -> Dict[str, Any]:
    """Return HMAC-SHA256 fingerprints for full/system/user messages."""
    base = {
        "messages_hmac": None,
        "system_message_hmac": None,
        "user_message_hmac": None,
        "hmac_key_version": None,
        "hmac_domain": DEFAULT_HMAC_DOMAIN,
        "hash_scope": hash_scope,
    }
    if not messages:
        return base
    secret = _load_usage_hmac_secret()
    if not secret:
        return base
    key_version = os.getenv("LLM_USAGE_HMAC_KEY_VERSION", DEFAULT_HMAC_KEY_VERSION).strip() or DEFAULT_HMAC_KEY_VERSION
    normalized_messages = [_message_for_hmac(message) for message in messages]
    base["messages_hmac"] = _hmac_json(secret, normalized_messages)
    base["system_message_hmac"] = _role_hmac(secret, normalized_messages, "system")
    base["user_message_hmac"] = _role_hmac(secret, normalized_messages, "user")
    base["hmac_key_version"] = key_version
    return base


def build_domain_hmac(
    value: Any,
    *,
    domain: str,
    hash_scope: str = DEFAULT_HASH_SCOPE,
) -> Dict[str, Any]:
    """Return a domain-separated HMAC without exposing the raw input value."""
    normalized_domain = (domain or "").strip() or DEFAULT_HMAC_DOMAIN
    base: Dict[str, Any] = {
        "hmac": None,
        "hmac_key_version": None,
        "hmac_domain": normalized_domain,
        "hash_scope": hash_scope,
    }
    secret = _load_usage_hmac_secret()
    if secret is None:
        return base
    key_version = os.getenv("LLM_USAGE_HMAC_KEY_VERSION", DEFAULT_HMAC_KEY_VERSION).strip() or DEFAULT_HMAC_KEY_VERSION
    base["hmac"] = _hmac_json(
        secret,
        {
            "domain": normalized_domain,
            "value": value,
        },
    )
    base["hmac_key_version"] = key_version
    return base


def _role_hmac(secret: bytes, messages: Sequence[Mapping[str, Any]], role: str) -> Optional[str]:
    role_messages = [message for message in messages if message.get("role") == role]
    if not role_messages:
        return None
    return _hmac_json(secret, role_messages)


def _hmac_json(secret: bytes, value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _message_for_hmac(message: Mapping[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in message.items():
        key_text = str(key)
        if key_text.startswith("_trace_"):
            continue
        normalized[key_text] = str(value or "") if key_text == "role" else _plain_value(value)
    normalized.setdefault("role", "")
    return normalized


def _render_legacy_audit_messages(
    messages: Sequence[Mapping[str, Any]],
) -> tuple[str, Dict[int, int]]:
    parts = []
    content_starts: Dict[int, int] = {}
    cursor = 0
    for index, message in enumerate(messages):
        if index:
            parts.append(LEGACY_AUDIT_MESSAGE_SEPARATOR)
            cursor += len(LEGACY_AUDIT_MESSAGE_SEPARATOR)
        role = str(message.get("role") or "")
        content = _legacy_audit_text(message.get("content"))
        prefix = f"{role}\n"
        parts.append(prefix)
        cursor += len(prefix)
        content_starts[index] = cursor
        parts.append(content)
        cursor += len(content)
    return "".join(parts), content_starts


def _legacy_marker_positions(
    messages: Sequence[Mapping[str, Any]],
    content_starts: Mapping[int, int],
    marker_specs: Any,
) -> tuple[list[Dict[str, Any]], Optional[int]]:
    positions_with_render_offset: list[tuple[int, Dict[str, Any]]] = []

    for spec in _iter_marker_specs(marker_specs):
        marker_name = _audit_scalar(
            spec.get("marker_name") or spec.get("name"),
            max_len=96,
        )
        if marker_name not in _LEGACY_AUDIT_MARKER_NAMES:
            continue
        requested_role = _audit_scalar(
            spec.get("message_role") or spec.get("role") or "user",
            max_len=32,
        )
        for candidate_text in _iter_marker_texts(spec):
            found = _find_marker_in_messages(messages, requested_role, candidate_text)
            if found is None:
                continue
            message_index, message_role, char_offset = found
            render_offset = content_starts.get(message_index, 0) + char_offset
            positions_with_render_offset.append(
                (
                    render_offset,
                    {
                        "marker_name": marker_name,
                        "message_role": message_role,
                        "char_offset": char_offset,
                    },
                )
            )
            break

    positions_with_render_offset.sort(key=lambda item: item[0])
    marker_positions = [position for _, position in positions_with_render_offset]
    first_render_offset = positions_with_render_offset[0][0] if positions_with_render_offset else None
    return marker_positions, first_render_offset


def _legacy_skill_config_hmac(context: Mapping[str, Any]) -> Optional[str]:
    skill_config = context.get("skill_config")
    if not isinstance(skill_config, Mapping):
        return None
    secret = _load_usage_hmac_secret()
    if not secret:
        return None
    payload = {
        "domain": "legacy_skill_config",
        "skill_instructions": _legacy_audit_text(skill_config.get("skill_instructions")),
        "default_skill_policy": _legacy_audit_text(skill_config.get("default_skill_policy")),
        "use_legacy_default_prompt": bool(skill_config.get("use_legacy_default_prompt")),
    }
    return _hmac_json(secret, payload)


def _iter_marker_specs(marker_specs: Any) -> Iterable[Mapping[str, Any]]:
    if not isinstance(marker_specs, IterableABC) or isinstance(marker_specs, (str, bytes, Mapping)):
        return
    for spec in marker_specs:
        if isinstance(spec, Mapping):
            yield spec


def _iter_marker_texts(spec: Mapping[str, Any]) -> Iterable[str]:
    text = _legacy_audit_text(spec.get("text"))
    if text:
        yield text


def _find_marker_in_messages(
    messages: Sequence[Mapping[str, Any]],
    requested_role: Optional[str],
    candidate_text: str,
) -> Optional[tuple[int, str, int]]:
    for index, message in enumerate(messages):
        role = str(message.get("role") or "")
        if requested_role and role != requested_role:
            continue
        content = _legacy_audit_text(message.get("content"))
        offset = content.find(candidate_text)
        if offset >= 0:
            return index, role, offset
    return None


def _legacy_audit_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    plain = _plain_value(value)
    if isinstance(plain, str):
        return plain
    try:
        return json.dumps(plain, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(plain)


def _estimate_chars_as_tokens(chars: int) -> int:
    return int(math.ceil(max(chars, 0) / 3))


def _audit_scalar(value: Any, *, max_len: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def _load_usage_hmac_secret() -> Optional[bytes]:
    global _HMAC_SECRET_CACHE
    env_secret = os.getenv("LLM_USAGE_HMAC_SECRET")
    if env_secret:
        return env_secret.encode("utf-8")
    if _HMAC_SECRET_CACHE is not None:
        return _HMAC_SECRET_CACHE

    secret_path = _usage_hmac_secret_path()
    try:
        if secret_path.exists():
            data = secret_path.read_bytes()
            if data:
                _HMAC_SECRET_CACHE = data
                return data
            logger.warning("Invalid empty .llm_usage_hmac_secret, regenerating")
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        new_secret = secrets.token_bytes(32)
        try:
            with open(secret_path, "xb") as f:
                f.write(new_secret)
            secret_path.chmod(0o600)
        except FileExistsError:
            data = secret_path.read_bytes()
            if data:
                _HMAC_SECRET_CACHE = data
                return data
            secret_path.write_bytes(new_secret)
            secret_path.chmod(0o600)
        _HMAC_SECRET_CACHE = new_secret
        return new_secret
    except OSError as exc:
        logger.warning("[LLM usage] failed to load HMAC secret: %s", exc)
        return None


def _usage_hmac_secret_path() -> Path:
    db_path = os.getenv("DATABASE_PATH", "./data/stock_analysis.db")
    return Path(db_path).resolve().parent / ".llm_usage_hmac_secret"


def _to_plain(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(k): _plain_value(v) for k, v in value.items()}
    for method_name in ("model_dump", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                dumped = method()
                if isinstance(dumped, Mapping):
                    return {str(k): _plain_value(v) for k, v in dumped.items()}
            except Exception:
                pass
    result: Dict[str, Any] = {}
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
        "cached_tokens",
        "cached_content_token_count",
        "prompt_token_count",
        "candidates_token_count",
        "total_token_count",
        "prompt_tokens_details",
    ):
        if hasattr(value, key):
            result[key] = _plain_value(getattr(value, key))
    return result


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _plain_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    for method_name in ("model_dump", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                dumped = method()
                return _plain_value(dumped)
            except Exception:
                pass
    return str(value)


def _usage_value_is_nonzero(value: Any) -> bool:
    parsed = _as_non_negative_int(value)
    return parsed is not None and parsed != 0


def _usage_count_is_nonzero(value: Any) -> bool:
    parsed = _as_non_negative_int(value)
    return parsed is not None and parsed != 0


def _safe_provider_usage_json(usage: Mapping[str, Any]) -> Optional[str]:
    if not usage:
        return None
    sanitized = _sanitize_raw_usage(dict(usage))
    if not sanitized:
        return None
    payload = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    size = len(payload.encode("utf-8"))
    if size <= PROVIDER_USAGE_MAX_SIZE_BYTES:
        return payload
    marker = {
        "_truncated": True,
        "_original_size_bytes": size,
        "prompt_tokens": _first_int(sanitized, "prompt_tokens", "input_tokens", "prompt_token_count"),
        "completion_tokens": _first_int(
            sanitized,
            "completion_tokens",
            "output_tokens",
            "candidates_token_count",
        ),
        "total_tokens": _first_int(sanitized, "total_tokens", "total_token_count"),
    }
    return json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sanitize_raw_usage(value: Any) -> Any:
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in _ALLOWED_RAW_USAGE_DETAIL_KEYS and isinstance(item, Mapping):
                detail = _sanitize_raw_usage_detail(item)
                if detail:
                    result[key_text] = detail
                continue
            if key_text not in _ALLOWED_RAW_USAGE_SCALAR_KEYS:
                continue
            sanitized = _sanitize_raw_usage_count(item)
            if sanitized is not _DROP_RAW_USAGE_VALUE:
                result[key_text] = sanitized
        return result
    return None


def _sanitize_raw_usage_detail(value: Mapping[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        if key_text not in _ALLOWED_RAW_USAGE_DETAIL_SCALAR_KEYS:
            continue
        sanitized = _sanitize_raw_usage_count(item)
        if sanitized is not _DROP_RAW_USAGE_VALUE:
            result[key_text] = sanitized
    return result


def _sanitize_raw_usage_count(value: Any) -> Any:
    parsed = _as_non_negative_int(value)
    return parsed if parsed is not None else _DROP_RAW_USAGE_VALUE


def _has_deepseek_hit_miss_shape(usage: Mapping[str, Any]) -> bool:
    return "prompt_cache_hit_tokens" in usage or "prompt_cache_miss_tokens" in usage


def _infer_provider(model: str, provider: Optional[str]) -> str:
    normalized_model = (model or "").strip().lower()
    normalized_provider = (provider or "").strip().lower()
    try:
        from src.llm.provider_cache import infer_provider_family

        inferred = infer_provider_family(model=normalized_model, provider=normalized_provider)
        if inferred:
            return inferred
    except Exception:
        pass
    route_text = f"{normalized_provider} {normalized_model}"

    if normalized_model.startswith("openai/~") or "openrouter" in route_text:
        return "openrouter"
    if normalized_provider in {"zhipu", "bigmodel", "glm"}:
        return "glm"
    if normalized_provider in {"anthropic", "gemini", "vertex_ai", "deepseek", "stepfun"}:
        return normalized_provider
    if normalized_provider == _OPENAI_LITELLM_PROVIDER:
        return "openai" if _is_native_openai_model(normalized_model) else _OPENAI_COMPATIBLE_PROVIDER
    if normalized_model.startswith("openai/"):
        return "openai" if _is_native_openai_model(normalized_model) else _OPENAI_COMPATIBLE_PROVIDER

    if _is_glm_model(normalized_model):
        return "glm"
    if "stepfun" in normalized_model or normalized_model.startswith("step/"):
        return "stepfun"
    if normalized_model.startswith("anthropic/"):
        return "anthropic"
    if normalized_model.startswith("gemini/"):
        return "gemini"
    if normalized_model.startswith("deepseek/"):
        return "deepseek"
    if "/" in normalized_model:
        return normalized_model.split("/", 1)[0]
    return normalized_provider or "unknown"


def _is_glm_model(normalized_model: str) -> bool:
    if not normalized_model:
        return False
    return (
        normalized_model.startswith("glm")
        or normalized_model.startswith("zhipu/")
        or normalized_model.startswith("bigmodel/")
        or "/glm" in normalized_model
    )


def _is_native_openai_model(model: str) -> bool:
    normalized = (model or "").strip().lower()
    if normalized.startswith("openai/"):
        normalized = normalized.split("/", 1)[1]
    if not normalized or "/" in normalized:
        return False
    return normalized.startswith(
        (
            "gpt-",
            "gpt4",
            "gpt5",
            "chatgpt-",
            "o1",
            "o3",
            "o4",
            "text-",
            "davinci",
            "babbage",
            "curie",
            "ada",
        )
    )


def _first_int(mapping: Mapping[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = mapping.get(key)
        parsed = _as_non_negative_int(value)
        if parsed is not None:
            return parsed
    return None


def _nested_int(mapping: Mapping[str, Any], path: Iterable[str]) -> Optional[int]:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return _as_non_negative_int(current)


def _as_non_negative_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value < 0 or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if not re.fullmatch(r"\d+", text):
            return None
        return int(text)
    return None


def _is_invalid_usage_count_value(value: Any) -> bool:
    if value is None:
        return False
    return _as_non_negative_int(value) is None


def _has_invalid_usage_count_values(usage: Mapping[str, Any]) -> bool:
    for key in _USAGE_COUNT_SCALAR_KEYS:
        if key in usage and _is_invalid_usage_count_value(usage.get(key)):
            return True

    for detail_key in _ALLOWED_RAW_USAGE_DETAIL_KEYS:
        detail = usage.get(detail_key)
        if not isinstance(detail, Mapping):
            continue
        for key in _USAGE_COUNT_DETAIL_KEYS:
            if key in detail and _is_invalid_usage_count_value(detail.get(key)):
                return True
    return False


def _has_impossible_total_tokens(
    *,
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
    total_tokens: Optional[int],
) -> bool:
    if prompt_tokens is None or completion_tokens is None or total_tokens is None:
        return False
    return total_tokens < prompt_tokens + completion_tokens


def _eligible_input_tokens(
    prompt_tokens: Optional[int],
    provider_min_cache_tokens: Optional[int],
    capability: str,
) -> Optional[int]:
    if capability != "supported" or prompt_tokens is None:
        return None
    if provider_min_cache_tokens is not None and prompt_tokens < provider_min_cache_tokens:
        return None
    return prompt_tokens


def _cache_eligibility(
    prompt_tokens: Optional[int],
    provider_min_cache_tokens: Optional[int],
    capability: str,
) -> str:
    if capability != "supported":
        return "unknown"
    if prompt_tokens is None:
        return "unknown"
    if provider_min_cache_tokens is not None and prompt_tokens < provider_min_cache_tokens:
        return "below_threshold"
    return "eligible"


def _cache_observation(
    *,
    has_usage: bool,
    cache_field_observed: bool,
    cache_read: Optional[int],
    cache_write: Optional[int],
    cache_miss: Optional[int],
    eligible_tokens: Optional[int],
) -> str:
    if not has_usage:
        return "no_usage"
    if not cache_field_observed:
        return "unknown"
    read = cache_read or 0
    write = cache_write or 0
    miss = cache_miss or 0
    if read > 0 and write > 0:
        return "read_and_write"
    if write > 0:
        return "write_only"
    if read > 0:
        hit_ratio = _ratio(read, eligible_tokens)
        return "full_hit" if hit_ratio is not None and hit_ratio >= 0.9 else "partial_hit"
    if eligible_tokens is None:
        return "unknown"
    if miss > 0 or cache_field_observed:
        return "zero_hit"
    return "unknown"


def _has_invalid_cache_usage(
    *,
    prompt_tokens: Optional[int],
    cache_read: Optional[int],
    cache_write: Optional[int],
    cache_miss: Optional[int],
    capability: str,
) -> bool:
    if capability != "supported":
        return False
    values = (prompt_tokens, cache_read, cache_write, cache_miss)
    if any(value is not None and value < 0 for value in values):
        return True
    if prompt_tokens is None:
        return False
    read = cache_read or 0
    write = cache_write or 0
    miss = cache_miss or 0
    if read > prompt_tokens or write > prompt_tokens or miss > prompt_tokens:
        return True
    if read + write > prompt_tokens:
        return True
    if cache_miss is not None and read + miss > prompt_tokens:
        return True
    return False


def _ratio(numerator: Optional[int], denominator: Optional[int]) -> Optional[float]:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def _reset_usage_hmac_secret_cache_for_tests() -> None:
    global _HMAC_SECRET_CACHE
    _HMAC_SECRET_CACHE = None
