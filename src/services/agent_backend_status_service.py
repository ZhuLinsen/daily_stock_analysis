# -*- coding: utf-8 -*-
"""Side-effect-free compatibility status for Agent Chat backends.

Provider API (LiteLLM) is the only supported Chat backend; the experimental
Codex App Server backend was removed together with its CLI probes.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.agent.agent_backend import resolve_agent_backend_id
from src.config import Config, parse_env_bool


def evaluate_agent_backend_config(config: Config) -> Dict[str, Any]:
    """Select the backend and evaluate only request-time configuration invariants."""
    requested = str(getattr(config, "agent_backend", "auto") or "auto").strip().lower()
    try:
        selected = resolve_agent_backend_id(config)
    except ValueError as exc:
        return {
            "backend": requested or "unknown",
            "available": False,
            "error_code": getattr(exc, "code", "capability_unsupported"),
            "message": str(exc),
        }

    if getattr(config, "_agent_mode_explicit", False) and not getattr(config, "agent_mode", False):
        return {
            "backend": selected,
            "available": False,
            "error_code": "agent_mode_disabled",
            "message": "Agent mode is disabled",
        }
    if not config.is_agent_available():
        return {
            "backend": selected,
            "available": False,
            "error_code": "capability_unsupported",
            "message": "no_agent_primary",
        }
    return {
        "backend": selected,
        "available": True,
        "error_code": None,
        "message": None,
    }


class AgentBackendStatusService:
    """Evaluate whether the selected Chat backend can be attempted."""

    def __init__(self, *, effective_map: Optional[Dict[str, str]] = None, config: Optional[Config] = None) -> None:
        self._effective_map = {
            str(key).upper(): "" if value is None else str(value)
            for key, value in (effective_map or {}).items()
        }
        self._config = config

    def get_status(self) -> Dict[str, Any]:
        config = self._build_config()
        evaluation = evaluate_agent_backend_config(config)
        return self._response(
            backend=evaluation["backend"],
            available=evaluation["available"],
            error_code=evaluation["error_code"],
            message=evaluation["message"],
        )

    def _response(
        self,
        *,
        backend: str,
        available: bool,
        error_code: Optional[str] = None,
        message: Optional[str] = None,
        version: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "backend": backend,
            "available": available,
            "experimental": False,
            "version": version,
            "error_code": error_code,
            "message": message,
        }

    def _build_config(self) -> Config:
        if self._config is not None:
            return self._config
        from src.services.generation_backend_status_service import GenerationBackendStatusService

        generation_service = GenerationBackendStatusService(effective_map=self._effective_map)
        config = generation_service.build_effective_config()
        config.agent_backend = (self._effective_map.get("AGENT_BACKEND") or "auto").strip().lower()
        config.agent_litellm_model = (self._effective_map.get("AGENT_LITELLM_MODEL") or "").strip()
        config.agent_arch = (self._effective_map.get("AGENT_ARCH") or "single").strip().lower()
        config.agent_mode = parse_env_bool(self._effective_map.get("AGENT_MODE"), default=False)
        config._agent_mode_explicit = "AGENT_MODE" in self._effective_map
        return config
