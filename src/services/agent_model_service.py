# -*- coding: utf-8 -*-
"""Helpers for exposing configured Agent model deployments."""

from __future__ import annotations

from typing import Any, Dict, List

from src.config import get_effective_agent_models_to_try, get_effective_agent_primary_model


_PLACEHOLDER_TO_PROVIDER = {
    "__legacy_gemini__": "gemini",
    "__legacy_anthropic__": "anthropic",
    "__legacy_openai__": "openai",
    "__legacy_deepseek__": "deepseek",
}
_MANAGED_LEGACY_PROVIDERS = set(_PLACEHOLDER_TO_PROVIDER.values())


def _get_models_source(config) -> str:
    source = getattr(config, "llm_models_source", "")
    if source in {"litellm_config", "llm_channels", "legacy_env"}:
        return source
    return "legacy_env"


def _get_model_provider(model_name: str) -> str:
    if not model_name:
        return "unknown"
    if "/" in model_name:
        return model_name.split("/", 1)[0]
    return "openai"


def _build_non_legacy_deployments(config) -> List[Dict[str, Any]]:
    source = _get_models_source(config)
    primary_model = get_effective_agent_primary_model(config)
    fallback_models = set(get_effective_agent_models_to_try(config)[1:])
    deployments: List[Dict[str, Any]] = []

    for index, entry in enumerate(getattr(config, "llm_model_list", []) or []):
        params = entry.get("litellm_params", {}) or {}
        model_name = str(params.get("model") or "").strip()
        if not model_name or model_name.startswith("__legacy_"):
            continue

        api_base = params.get("api_base")
        deployment_name = entry.get("model_name")
        deployments.append(
            {
                "deployment_id": f"{source}:{index}",
                "model": model_name,
                "provider": _get_model_provider(model_name),
                "source": source,
                "api_base": str(api_base).strip() if api_base else None,
                "deployment_name": str(deployment_name).strip() if deployment_name else None,
                "is_primary": model_name == primary_model,
                "is_fallback": model_name in fallback_models,
            }
        )

    return deployments


def _build_legacy_deployments(config) -> List[Dict[str, Any]]:
    primary_model = get_effective_agent_primary_model(config)
    ordered_models = get_effective_agent_models_to_try(config)
    if not ordered_models:
        return []

    placeholder_counts = {provider: 0 for provider in _PLACEHOLDER_TO_PROVIDER.values()}
    for entry in getattr(config, "llm_model_list", []) or []:
        provider = _PLACEHOLDER_TO_PROVIDER.get(entry.get("model_name"))
        if provider:
            placeholder_counts[provider] += 1

    deployments: List[Dict[str, Any]] = []
    seen_models = set()
    fallback_set = set(ordered_models[1:])
    for model_name in ordered_models:
        if model_name in seen_models:
            continue
        seen_models.add(model_name)

        provider = _get_model_provider(model_name)
        deployment_count = placeholder_counts.get(provider, 0)
        if deployment_count <= 0:
            # Legacy runtime still supports direct litellm calls for providers
            # whose credentials/base are resolved from environment variables
            # instead of managed placeholder deployments.
            if provider in _MANAGED_LEGACY_PROVIDERS:
                continue
            deployment_count = 1

        api_base = getattr(config, "openai_base_url", None) if provider == "openai" else None
        # Legacy runtime only load-balances the primary model via Router.
        # Fallback models call litellm directly with the first configured key,
        # so they expose at most one reachable deployment per model.
        if model_name == primary_model:
            deployment_indexes = range(deployment_count)
        else:
            deployment_indexes = range(1)

        for index in deployment_indexes:
            deployments.append(
                {
                    "deployment_id": f"legacy:{provider}:{index}:{model_name}",
                    "model": model_name,
                    "provider": provider,
                    "source": "legacy_env",
                    "api_base": api_base,
                    "deployment_name": f"legacy_{provider}_{index + 1}",
                    "is_primary": model_name == primary_model,
                    "is_fallback": model_name in fallback_set,
                }
            )

    return deployments


def list_agent_model_deployments(config) -> List[Dict[str, Any]]:
    """Return configured Agent model deployments without exposing secrets."""
    deployments = _build_non_legacy_deployments(config)
    if not deployments:
        deployments = _build_legacy_deployments(config)

    return sorted(
        deployments,
        key=lambda item: (
            not item["is_primary"],
            not item["is_fallback"],
            item["source"],
            item["model"],
            item["api_base"] or "",
            item["deployment_name"] or "",
            item["deployment_id"],
        ),
    )
