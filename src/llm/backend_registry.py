# -*- coding: utf-8 -*-
"""Generation backend resolver utilities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from src.llm.generation_backend import GenerationError, GenerationErrorCode

LITELLM_BACKEND_ID = "litellm"
CODEX_CLI_BACKEND_ID = "codex_cli"
AUTO_AGENT_BACKEND_ID = "auto"

SUPPORTED_GENERATION_BACKENDS = frozenset({LITELLM_BACKEND_ID, CODEX_CLI_BACKEND_ID})
SUPPORTED_GENERATION_FALLBACK_BACKENDS = frozenset({LITELLM_BACKEND_ID})
SUPPORTED_AGENT_GENERATION_BACKENDS = frozenset({
    AUTO_AGENT_BACKEND_ID,
    LITELLM_BACKEND_ID,
    CODEX_CLI_BACKEND_ID,
})


def _read_backend_config_value(config: Any, field_name: str, default: str) -> Any:
    """Read backend config without triggering dynamic mock attributes."""
    if isinstance(config, Mapping):
        return config.get(field_name, default)

    try:
        values = vars(config)
    except TypeError:
        values = {}
    if field_name in values:
        return values[field_name]

    try:
        return object.__getattribute__(config, field_name)
    except AttributeError:
        return default


def normalize_backend_id(value: Any, *, default: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate or default


def _unsupported_backend_error(backend_id: str, *, field: str) -> GenerationError:
    if field == "AGENT_GENERATION_BACKEND":
        supported = SUPPORTED_AGENT_GENERATION_BACKENDS
    elif field == "GENERATION_FALLBACK_BACKEND":
        supported = SUPPORTED_GENERATION_FALLBACK_BACKENDS
    else:
        supported = SUPPORTED_GENERATION_BACKENDS
    return GenerationError(
        error_code=GenerationErrorCode.BACKEND_NOT_CONFIGURED,
        stage="generation",
        retryable=False,
        fallbackable=False,
        backend=backend_id,
        provider=backend_id,
        details={
            "field": field,
            "requested_backend": backend_id,
            "supported_backends": sorted(supported),
        },
    )


def resolve_generation_backend_id(config: Any) -> str:
    """Return the configured analysis generation backend id."""
    backend_id = normalize_backend_id(
        _read_backend_config_value(config, "generation_backend", LITELLM_BACKEND_ID),
        default=LITELLM_BACKEND_ID,
    )
    if backend_id not in SUPPORTED_GENERATION_BACKENDS:
        raise _unsupported_backend_error(backend_id, field="GENERATION_BACKEND")
    return backend_id


def resolve_generation_fallback_backend_id(config: Any) -> Optional[str]:
    """Return the backend-level fallback target, or None for self/no-op."""
    primary = resolve_generation_backend_id(config)
    raw_fallback = _read_backend_config_value(
        config,
        "generation_fallback_backend",
        None,
    )
    if raw_fallback is None:
        fallback = LITELLM_BACKEND_ID
    else:
        fallback = str(raw_fallback).strip().lower()
        if not fallback:
            return None
    if fallback == primary:
        return None
    if fallback != LITELLM_BACKEND_ID:
        raise _unsupported_backend_error(fallback, field="GENERATION_FALLBACK_BACKEND")
    return fallback


def resolve_agent_generation_backend_id(config: Any) -> str:
    """Return the Agent tool-calling backend id.

    Phase 2 keeps Agent tool-calling on LiteLLM for auto. Explicit local
    backends are returned so the Agent adapter can reject or fallback
    explicitly instead of treating text-only output as successful tool use.
    """
    backend_id = normalize_backend_id(
        _read_backend_config_value(
            config,
            "agent_generation_backend",
            AUTO_AGENT_BACKEND_ID,
        ),
        default=AUTO_AGENT_BACKEND_ID,
    )
    if backend_id not in SUPPORTED_AGENT_GENERATION_BACKENDS:
        raise _unsupported_backend_error(backend_id, field="AGENT_GENERATION_BACKEND")
    if backend_id == AUTO_AGENT_BACKEND_ID:
        return LITELLM_BACKEND_ID
    return backend_id
