# -*- coding: utf-8 -*-
"""Agent-safe LiteLLM route resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.config import (
    get_effective_agent_models_to_try,
    get_effective_agent_primary_model,
    get_configured_llm_models,
)
from src.llm.backend_registry import AUTO_AGENT_BACKEND_ID, GENERATION_ONLY_BACKEND_IDS
from src.llm.hermes import (
    build_route_provenance_map,
    filter_non_hermes_deployments,
    route_deployment_origins,
    route_identity_candidates,
)


@dataclass(frozen=True)
class AgentLiteLLMRouteResolution:
    available: bool
    primary_model: str = ""
    models_to_try: List[str] = field(default_factory=list)
    model_list: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""


def _is_model_agent_safe(config: Any, model: str, provenance: Dict[str, Any]) -> bool:
    if not model:
        return False
    route = route_deployment_origins(getattr(config, "llm_model_list", []) or [], model)
    if route.has_hermes or route.has_non_hermes:
        return route.has_non_hermes
    route = provenance.get(model)
    if route is not None:
        return route.has_non_hermes
    return True


def _matched_route_alias(model: str, provenance: Dict[str, Any]) -> str:
    for candidate in route_identity_candidates(model):
        if candidate in provenance:
            return candidate
    return (model or "").strip()


def resolve_agent_litellm_route(config: Any) -> AgentLiteLLMRouteResolution:
    """Resolve the Agent LiteLLM route without allowing Hermes-only deployments."""

    agent_backend = str(
        getattr(config, "agent_generation_backend", AUTO_AGENT_BACKEND_ID)
        or AUTO_AGENT_BACKEND_ID
    ).strip().lower()
    if agent_backend in GENERATION_ONLY_BACKEND_IDS:
        return AgentLiteLLMRouteResolution(False, reason="unsupported_agent_backend")

    primary = get_effective_agent_primary_model(config)
    if not primary:
        return AgentLiteLLMRouteResolution(False, reason="no_agent_primary")

    model_list = list(getattr(config, "llm_model_list", []) or [])
    provenance = build_route_provenance_map(model_list)
    filtered_model_list = filter_non_hermes_deployments(model_list)
    configured_models = set(get_configured_llm_models(model_list))
    configured_agent_model = bool((getattr(config, "agent_litellm_model", "") or "").strip())

    primary_route = route_deployment_origins(model_list, primary)
    if primary_route is not None and primary_route.has_hermes and not primary_route.has_non_hermes:
        return AgentLiteLLMRouteResolution(
            False,
            primary_model=primary,
            model_list=filtered_model_list,
            reason=(
                "explicit_agent_model_no_safe_deployment"
                if configured_agent_model
                else "hermes_primary_not_agent_safe"
            ),
        )
    safe_models: List[str] = []
    seen = set()
    for model in get_effective_agent_models_to_try(config):
        normalized = (model or "").strip()
        if not normalized or normalized in seen:
            continue
        if not _is_model_agent_safe(config, normalized, provenance):
            continue
        safe_model = _matched_route_alias(normalized, provenance)
        if safe_model in seen:
            continue
        seen.add(safe_model)
        safe_models.append(safe_model)

    if not safe_models:
        return AgentLiteLLMRouteResolution(
            False,
            primary_model=primary,
            model_list=filtered_model_list,
            reason="no_safe_agent_models",
        )

    return AgentLiteLLMRouteResolution(
        True,
        primary_model=safe_models[0],
        models_to_try=safe_models,
        model_list=filtered_model_list,
        reason="",
    )
