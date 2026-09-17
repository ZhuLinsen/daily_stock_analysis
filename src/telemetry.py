"""Optional, privacy-safe Langfuse observability helpers.

The module deliberately has no import-time dependency on Langfuse.  When the
feature is disabled, misconfigured, or the SDK/exporter is unavailable, every
helper becomes a no-op so telemetry can never block analysis.
"""

from __future__ import annotations

import functools
import logging
import os
import sys
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Mapping, Optional

logger = logging.getLogger(__name__)

_SAFE_METADATA_KEYS = frozenset(
    {
        "backend",
        "cache_hit",
        "category",
        "code_version",
        "dry_run",
        "error_type",
        "fallback_index",
        "max_results",
        "model",
        "provider",
        "report_type",
        "retry_count",
        "status",
        "stock_count",
        "tool_name",
    }
)
_TOKEN_KEYS = frozenset({"input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens"})


def _enabled() -> bool:
    return os.getenv("LANGFUSE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def safe_metadata(values: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a scalar allowlist; prompts, identifiers, holdings and secrets are dropped."""
    output: Dict[str, Any] = {}
    for key, value in (values or {}).items():
        if key not in _SAFE_METADATA_KEYS or value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            output[key] = value
    return output


def safe_usage(values: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    """Normalize token usage without copying provider payloads."""
    usage: Dict[str, int] = {}
    for key, value in (values or {}).items():
        if key not in _TOKEN_KEYS:
            continue
        try:
            usage[key] = max(0, int(value))
        except (TypeError, ValueError):
            continue
    if "input_tokens" not in usage and "prompt_tokens" in usage:
        usage["input_tokens"] = usage["prompt_tokens"]
    if "output_tokens" not in usage and "completion_tokens" in usage:
        usage["output_tokens"] = usage["completion_tokens"]
    return usage


def _client() -> Any:
    if not _enabled():
        return None
    try:
        from langfuse import get_client

        return get_client()
    except Exception as exc:  # SDK/config/export failures must be non-blocking.
        logger.warning("Langfuse telemetry unavailable: %s", type(exc).__name__)
        return None


@contextmanager
def observation(
    name: str,
    *,
    as_type: str = "span",
    metadata: Optional[Mapping[str, Any]] = None,
    model: Optional[str] = None,
) -> Iterator[Any]:
    """Start a nested Langfuse observation, yielding ``None`` on any SDK failure."""
    client = _client()
    if client is None:
        yield None
        return
    kwargs: Dict[str, Any] = {
        "name": name,
        "as_type": as_type,
        "metadata": safe_metadata(metadata),
    }
    if model:
        kwargs["model"] = model
    try:
        manager = client.start_as_current_observation(**kwargs)
        current = manager.__enter__()
    except Exception as exc:
        logger.warning("Langfuse observation failed: %s", type(exc).__name__)
        yield None
        return
    try:
        yield current
    except BaseException:
        try:
            manager.__exit__(*sys.exc_info())
        except Exception as exc:
            logger.warning("Langfuse observation close failed: %s", type(exc).__name__)
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception as exc:
            logger.warning("Langfuse observation close failed: %s", type(exc).__name__)


def update_observation(
    current: Any,
    *,
    metadata: Optional[Mapping[str, Any]] = None,
    usage: Optional[Mapping[str, Any]] = None,
    cost: Optional[float] = None,
    error: Optional[BaseException] = None,
) -> None:
    """Best-effort completion update using only approved structured fields."""
    if current is None:
        return
    kwargs: Dict[str, Any] = {"metadata": safe_metadata(metadata)}
    normalized_usage = safe_usage(usage)
    if normalized_usage:
        kwargs["usage_details"] = normalized_usage
    if cost is not None:
        try:
            kwargs["cost_details"] = {"total": max(0.0, float(cost))}
        except (TypeError, ValueError):
            pass
    if error is not None:
        kwargs.update(
            level="ERROR",
            status_message=type(error).__name__,
            metadata={**kwargs["metadata"], "status": "error", "error_type": type(error).__name__},
        )
    try:
        current.update(**kwargs)
    except Exception as exc:
        logger.warning("Langfuse observation update failed: %s", type(exc).__name__)


def observe(name: str, *, as_type: str = "span", metadata: Optional[Mapping[str, Any]] = None):
    """Decorate a synchronous boundary while preserving application exceptions."""

    def decorator(func):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            with observation(name, as_type=as_type, metadata=metadata) as current:
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    update_observation(current, error=exc)
                    raise
                update_observation(current, metadata={"status": "success"})
                return result

        return wrapped

    return decorator
