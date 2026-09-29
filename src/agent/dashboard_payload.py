# -*- coding: utf-8 -*-
"""Shared sanitization for model-authored Agent dashboard payloads."""

from __future__ import annotations

from typing import Any, Dict


RESERVED_EXPLANATION_FIELD = "agent_disagreement_explanation"


def sanitize_agent_dashboard_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Remove fields reserved for deterministic post-processing.

    Both supported forged locations are removed at the shared LLM dashboard
    boundary.  The input mapping and nested dashboard mapping are not mutated.
    """
    sanitized = dict(payload)
    sanitized.pop(RESERVED_EXPLANATION_FIELD, None)

    nested = sanitized.get("dashboard")
    if isinstance(nested, dict):
        nested = dict(nested)
        nested.pop(RESERVED_EXPLANATION_FIELD, None)
        sanitized["dashboard"] = nested
    return sanitized


__all__ = ["RESERVED_EXPLANATION_FIELD", "sanitize_agent_dashboard_payload"]
