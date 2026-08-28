# -*- coding: utf-8 -*-
"""Generation backend resolver utilities.

Provider API (LiteLLM) is the only supported integration path; the former
local CLI generation backends and the Codex App Server Agent backend were
removed. Values kept for backward compatibility are rejected with a
structured error that points users back to ``litellm``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

from src.llm.generation_backend import GenerationError, GenerationErrorCode

LITELLM_BACKEND_ID = "litellm"
AUTO_AGENT_BACKEND_ID = "auto"

# Legacy ids accepted by old .env files; they no longer select a runtime and
# always resolve to a structured configuration error.
REMOVED_GENERATION_BACKEND_IDS = frozenset({
    "codex_cli",
    "claude_code_cli",
    "opencode_cli",
})
REMOVED_AGENT_BACKEND_IDS = frozenset({"codex_app_server"})

SUPPORTED_GENERATION_BACKENDS = frozenset({LITELLM_BACKEND_ID})
SUPPORTED_AGENT_UI_BACKENDS = frozenset({
    AUTO_AGENT_BACKEND_ID,
    LITELLM_BACKEND_ID,
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
            "supported_backends": sorted(SUPPORTED_GENERATION_BACKENDS),
            "reason": "removed_backend",
        },
    )


def resolve_generation_backend_id(config: Any) -> str:
    """Return the configured analysis generation backend id.

    Only the LiteLLM provider API path remains. Legacy local CLI values are
    reported as removed instead of silently falling back to litellm so stale
    .env files surface a clear diagnostic.
    """
    backend_id = normalize_backend_id(
        _read_backend_config_value(config, "generation_backend", LITELLM_BACKEND_ID),
        default=LITELLM_BACKEND_ID,
    )
    if backend_id in REMOVED_GENERATION_BACKEND_IDS or backend_id not in SUPPORTED_GENERATION_BACKENDS:
        raise _unsupported_backend_error(backend_id, field="GENERATION_BACKEND")
    return backend_id


def resolve_generation_fallback_backend_id(config: Any) -> Optional[str]:
    """Return the backend-level fallback target, or None for self/no-op.

    Backend-level fallback existed to rescue removed local CLI backends; with
    a single supported backend it is always a no-op.
    """
    resolve_generation_backend_id(config)
    return None


def resolve_agent_generation_backend_id(config: Any) -> str:
    """Return the Agent tool-calling backend id (always LiteLLM)."""
    backend_id = normalize_backend_id(
        _read_backend_config_value(
            config,
            "agent_generation_backend",
            AUTO_AGENT_BACKEND_ID,
        ),
        default=AUTO_AGENT_BACKEND_ID,
    )
    if backend_id in REMOVED_GENERATION_BACKEND_IDS or backend_id not in SUPPORTED_AGENT_UI_BACKENDS:
        raise _unsupported_backend_error(backend_id, field="AGENT_GENERATION_BACKEND")
    return LITELLM_BACKEND_ID
