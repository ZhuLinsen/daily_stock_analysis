# -*- coding: utf-8 -*-
"""Shared generation backend contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Protocol


class GenerationErrorCode(str, Enum):
    """Structured generation backend error codes.

    Shared across LiteLLM and local CLI generation backends.
    """

    BACKEND_NOT_CONFIGURED = "backend_not_configured"
    COMMAND_NOT_FOUND = "command_not_found"
    COMMAND_NOT_EXECUTABLE = "command_not_executable"
    TIMEOUT = "timeout"
    NON_ZERO_EXIT = "non_zero_exit"
    EMPTY_OUTPUT = "empty_output"
    OUTPUT_TOO_LARGE = "output_too_large"
    INVALID_JSON = "invalid_json"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    UNSUPPORTED_TOOL_CALLING = "unsupported_tool_calling"
    INTERACTIVE_PROMPT_REQUIRED = "interactive_prompt_required"
    APPROVAL_REQUIRED = "approval_required"
    LOGIN_REQUIRED = "login_required"
    CAPABILITY_UNSUPPORTED = "capability_unsupported"
    UNSAFE_CONFIG = "unsafe_config"
    UNKNOWN_BACKEND_ERROR = "unknown_backend_error"


@dataclass(frozen=True)
class GenerationCapabilities:
    """Backend capability flags surfaced to resolvers and diagnostics."""

    supports_json: bool
    supports_tools: bool
    supports_stream: bool
    supports_vision: bool
    supports_health_check: bool
    supports_smoke_test: bool


@dataclass
class GenerationResult:
    """Normalized result returned by generation backends."""

    text: str
    model: str
    provider: str
    backend: str
    usage: Dict[str, Any]
    raw: Any = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationError(Exception):
    """Structured generation backend failure.

    ``stage`` is intentionally descriptive rather than a closed enum. Current
    generation paths use values such as ``generation``, ``configuration``,
    ``execution``, ``validation``, and ``fallback``.
    """

    error_code: GenerationErrorCode
    stage: str
    retryable: bool
    fallbackable: bool
    backend: str
    provider: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider:
            self.provider = self.backend
        Exception.__init__(self, self.message)

    @property
    def message(self) -> str:
        return f"{self.error_code.value} at {self.stage} for backend {self.backend}"


class GenerationBackend(Protocol):
    """Protocol implemented by generation backends."""

    backend_id: str
    capabilities: GenerationCapabilities

    def generate(
        self,
        prompt: str,
        generation_config: Dict[str, Any],
        *,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        stream_progress_callback: Optional[Callable[[int], None]] = None,
        response_validator: Optional[Callable[[str], None]] = None,
        audit_context: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """Generate text with the backend."""
