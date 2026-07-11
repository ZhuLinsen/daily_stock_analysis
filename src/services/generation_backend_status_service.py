# -*- coding: utf-8 -*-
"""Read-only diagnostics for configured generation backends."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.analyzer import GeminiAnalyzer
from src.config import (
    ANSPIRE_LLM_BASE_URL_DEFAULT,
    ANSPIRE_LLM_MODEL_DEFAULT,
    Config,
    _get_litellm_provider,
    _uses_direct_env_provider,
    channel_allows_empty_api_key,
    get_configured_llm_models,
    normalize_llm_channel_model,
    parse_env_bool,
    resolve_llm_channel_protocol,
)
from src.llm.backend_registry import (
    LOCAL_CLI_GENERATION_BACKEND_IDS,
    LITELLM_BACKEND_ID,
    SUPPORTED_GENERATION_BACKENDS,
    normalize_backend_id,
    resolve_generation_backend_id,
    resolve_generation_fallback_backend_id,
)
from src.llm.generation_backend import GenerationCapabilities, GenerationError, GenerationErrorCode
from src.llm.hermes import (
    HERMES_DEFAULT_BASE_URL,
    HERMES_DEFAULT_MODEL,
    HERMES_DEFAULT_PROTOCOL,
    is_reserved_hermes_name,
    parse_hermes_channel,
)
from src.llm.local_cli_backend import (
    DEFAULT_GENERATION_BACKEND_MAX_CONCURRENCY,
    DEFAULT_LOCAL_CLI_BACKEND_MAX_CONCURRENCY,
    DEFAULT_LOCAL_CLI_MAX_OUTPUT_BYTES,
    DEFAULT_LOCAL_CLI_TIMEOUT_SECONDS,
    MAX_GENERATION_BACKEND_MAX_CONCURRENCY,
    MAX_LOCAL_CLI_BACKEND_MAX_CONCURRENCY,
    MAX_LOCAL_CLI_OUTPUT_BYTES,
    MAX_LOCAL_CLI_TIMEOUT_SECONDS,
    LocalCliGenerationBackend,
    effective_local_cli_concurrency,
    redact_diagnostic_text,
    resolve_local_cli_preset,
)

HealthStatus = str


@dataclass(frozen=True)
class _SmokeRequest:
    backend_id: str
    mode: str
    timeout_seconds: int


@dataclass(frozen=True)
class _NumericConfigSpec:
    key: str
    default: int
    minimum: int
    maximum: int


_GENERATION_BACKEND_MAX_CONCURRENCY_SPEC = _NumericConfigSpec(
    "GENERATION_BACKEND_MAX_CONCURRENCY",
    DEFAULT_GENERATION_BACKEND_MAX_CONCURRENCY,
    1,
    MAX_GENERATION_BACKEND_MAX_CONCURRENCY,
)
_LOCAL_CLI_NUMERIC_SPECS = (
    _NumericConfigSpec(
        "GENERATION_BACKEND_TIMEOUT_SECONDS",
        DEFAULT_LOCAL_CLI_TIMEOUT_SECONDS,
        1,
        MAX_LOCAL_CLI_TIMEOUT_SECONDS,
    ),
    _NumericConfigSpec(
        "GENERATION_BACKEND_MAX_OUTPUT_BYTES",
        DEFAULT_LOCAL_CLI_MAX_OUTPUT_BYTES,
        1,
        MAX_LOCAL_CLI_OUTPUT_BYTES,
    ),
    _GENERATION_BACKEND_MAX_CONCURRENCY_SPEC,
    _NumericConfigSpec(
        "LOCAL_CLI_BACKEND_MAX_CONCURRENCY",
        DEFAULT_LOCAL_CLI_BACKEND_MAX_CONCURRENCY,
        1,
        MAX_LOCAL_CLI_BACKEND_MAX_CONCURRENCY,
    ),
)
_LITELLM_NUMERIC_SPECS = (_GENERATION_BACKEND_MAX_CONCURRENCY_SPEC,)


def _as_error_code(value: Any) -> Optional[str]:
    if isinstance(value, GenerationErrorCode):
        return value.value
    if value is None:
        return None
    return str(value)


def _numeric_config_error(*, backend_id: str, spec: _NumericConfigSpec, value: Any, reason: str) -> GenerationError:
    return GenerationError(
        error_code=GenerationErrorCode.UNSAFE_CONFIG,
        stage="configuration",
        retryable=False,
        fallbackable=False,
        backend=backend_id,
        details={
            "field": spec.key,
            "reason": reason,
            "minimum": spec.minimum,
            "maximum": spec.maximum,
            "actual": "" if value is None else str(value),
        },
    )


def _parse_int_config_value(value: Any, spec: _NumericConfigSpec) -> int:
    raw_value = "" if value is None else str(value).strip()
    if not raw_value:
        return spec.default
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return spec.default
    if parsed < spec.minimum or parsed > spec.maximum:
        return spec.default
    return parsed


def _validate_int_config_value(*, backend_id: str, value: Any, spec: _NumericConfigSpec) -> Optional[GenerationError]:
    raw_value = "" if value is None else str(value).strip()
    if not raw_value:
        return None
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return _numeric_config_error(backend_id=backend_id, spec=spec, value=value, reason="invalid_integer")
    if parsed < spec.minimum or parsed > spec.maximum:
        return _numeric_config_error(backend_id=backend_id, spec=spec, value=value, reason="out_of_range")
    return None


def _parse_smoke_timeout(value: Optional[float], *, backend_id: str) -> int:
    spec = _NumericConfigSpec(
        "timeout_seconds",
        DEFAULT_LOCAL_CLI_TIMEOUT_SECONDS,
        1,
        MAX_LOCAL_CLI_TIMEOUT_SECONDS,
    )
    if value is None:
        return spec.default
    if isinstance(value, float) and not value.is_integer():
        raise _numeric_config_error(backend_id=backend_id, spec=spec, value=value, reason="invalid_integer")
    error = _validate_int_config_value(backend_id=backend_id, value=value, spec=spec)
    if error is not None:
        raise error
    return int(value)


class GenerationBackendStatusService:
    """Build current generation backend status without persisting state."""

    _TEXT_SMOKE_PROMPT = "Reply exactly: DSA_GENERATION_BACKEND_SMOKE_OK"
    _JSON_SMOKE_PROMPT = (
        "Return only a JSON object with exactly these keys and values: "
        '{"ok": true, "backend_smoke": "passed"}.'
    )

    def __init__(
        self,
        *,
        effective_map: Dict[str, str],
        validation_issues: Optional[List[Dict[str, Any]]] = None,
        analyzer_factory: Optional[Callable[[Config], GeminiAnalyzer]] = None,
    ) -> None:
        self._effective_map = {str(k).upper(): "" if v is None else str(v) for k, v in effective_map.items()}
        self._validation_issues = list(validation_issues or [])
        self._analyzer_factory = analyzer_factory or (lambda config: GeminiAnalyzer(config=config))

    def get_status(self) -> Dict[str, Any]:
        config = self._build_backend_config()
        try:
            primary_id = resolve_generation_backend_id(config)
        except GenerationError as exc:
            primary_id = str(exc.details.get("requested_backend") or exc.backend or "")
            primary = self._status_for_error(
                backend_id=primary_id or "unknown",
                is_primary=True,
                fallback_target=None,
                error=exc,
            )
            return {
                "primary_backend_id": primary["backend_id"],
                "fallback_backend_id": None,
                "primary": primary,
                "fallback": None,
                "backends": [primary],
            }

        fallback_error: Optional[GenerationError] = None
        try:
            fallback_id = resolve_generation_fallback_backend_id(config)
        except GenerationError as exc:
            fallback_id = str(
                exc.details.get("requested_backend")
                or exc.backend
                or getattr(config, "generation_fallback_backend", "")
                or "unknown"
            )
            fallback_error = exc

        primary = self._build_status(
            backend_id=primary_id,
            is_primary=True,
            fallback_target=fallback_id,
            health_status="not_tested",
        )
        if fallback_error is not None:
            fallback = self._status_for_error(
                backend_id=fallback_id,
                is_primary=False,
                fallback_target=None,
                error=fallback_error,
            )
        elif fallback_id:
            fallback = self._build_status(
                backend_id=fallback_id,
                is_primary=False,
                fallback_target=None,
                health_status="not_tested",
            )
        else:
            fallback = None
        backends = [primary]
        if fallback is not None:
            backends.append(fallback)
        return {
            "primary_backend_id": primary_id,
            "fallback_backend_id": fallback_id,
            "primary": primary,
            "fallback": fallback,
            "backends": backends,
        }

    def smoke_test(
        self,
        *,
        backend_id: Optional[str] = None,
        mode: str = "json",
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        request: Optional[_SmokeRequest] = None
        try:
            request = self._normalize_smoke_request(
                backend_id=backend_id,
                mode=mode,
                timeout_seconds=timeout_seconds,
            )
            self._run_smoke(request)
        except GenerationError as exc:
            failed_backend_id = str(
                exc.details.get("requested_backend")
                or exc.backend
                or backend_id
                or self._primary_backend_id()
                or "unknown"
            )
            normalized_mode = str(mode or "json").strip().lower() or "json"
            if normalized_mode not in {"text", "json"}:
                normalized_mode = "json"
            status = self._build_status(
                backend_id=failed_backend_id,
                is_primary=failed_backend_id == self._primary_backend_id(),
                fallback_target=None,
                health_status="failed",
                error=exc,
            )
            return {
                "success": False,
                "mode": normalized_mode,
                "message": exc.message,
                "status": status,
            }
        except Exception as exc:
            failed_backend_id = request.backend_id if request is not None else str(
                backend_id or self._primary_backend_id() or "unknown"
            )
            normalized_mode = request.mode if request is not None else str(mode or "json").strip().lower() or "json"
            if normalized_mode not in {"text", "json"}:
                normalized_mode = "json"
            error = GenerationError(
                error_code=GenerationErrorCode.UNKNOWN_BACKEND_ERROR,
                stage="smoke_test",
                retryable=False,
                fallbackable=False,
                backend=failed_backend_id,
                details={"reason": type(exc).__name__},
            )
            status = self._build_status(
                backend_id=failed_backend_id,
                is_primary=failed_backend_id == self._primary_backend_id(),
                fallback_target=None,
                health_status="failed",
                error=error,
            )
            return {
                "success": False,
                "mode": normalized_mode,
                "message": redact_diagnostic_text(str(exc) or error.message, limit=500),
                "status": status,
            }

        status = self._build_status(
            backend_id=request.backend_id,
            is_primary=request.backend_id == self._primary_backend_id(),
            fallback_target=None,
            health_status="passed",
        )
        return {
            "success": True,
            "mode": request.mode,
            "message": "生成后端冒烟测试通过",
            "status": status,
        }

    def _primary_backend_id(self) -> str:
        return normalize_backend_id(self._effective_map.get("GENERATION_BACKEND"), default=LITELLM_BACKEND_ID)

    def _normalize_smoke_request(
        self,
        *,
        backend_id: Optional[str],
        mode: str,
        timeout_seconds: Optional[float],
    ) -> _SmokeRequest:
        config = self._build_backend_config()
        requested_backend = normalize_backend_id(backend_id, default=resolve_generation_backend_id(config))
        if requested_backend not in SUPPORTED_GENERATION_BACKENDS:
            raise GenerationError(
                error_code=GenerationErrorCode.BACKEND_NOT_CONFIGURED,
                stage="configuration",
                retryable=False,
                fallbackable=False,
                backend=requested_backend,
                details={
                    "field": "backend_id",
                    "requested_backend": requested_backend,
                    "supported_backends": sorted(SUPPORTED_GENERATION_BACKENDS),
                },
            )
        normalized_mode = str(mode or "json").strip().lower() or "json"
        if normalized_mode not in {"text", "json"}:
            raise GenerationError(
                error_code=GenerationErrorCode.UNSAFE_CONFIG,
                stage="configuration",
                retryable=False,
                fallbackable=False,
                backend=requested_backend,
                details={"field": "mode", "requested_mode": mode, "supported_modes": ["text", "json"]},
            )
        timeout = _parse_smoke_timeout(timeout_seconds, backend_id=requested_backend)
        return _SmokeRequest(backend_id=requested_backend, mode=normalized_mode, timeout_seconds=timeout)

    def _run_smoke(self, request: _SmokeRequest) -> None:
        config = self._build_config(
            self._effective_map,
            backend_id=request.backend_id,
            timeout_seconds=request.timeout_seconds,
        )
        preflight_error = self._cheap_check_error(request.backend_id, config)
        if preflight_error is not None:
            raise preflight_error
        analyzer = self._analyzer_factory(config)
        prompt = self._JSON_SMOKE_PROMPT if request.mode == "json" else self._TEXT_SMOKE_PROMPT
        result = analyzer._get_generation_backend(request.backend_id).generate(
            prompt,
            {
                "max_tokens": 128,
                "temperature": 0,
                "timeout": request.timeout_seconds,
            },
            response_validator=self._json_smoke_validator if request.mode == "json" else self._text_smoke_validator,
            audit_context={"call_type": "generation_backend_smoke", "backend": request.backend_id},
        )
        if request.mode == "json":
            self._json_smoke_validator(result.text)
        else:
            self._text_smoke_validator(result.text)

    @classmethod
    def _json_smoke_validator(cls, text: str) -> None:
        try:
            payload = json.loads((text or "").strip())
        except Exception as exc:
            raise GenerationError(
                error_code=GenerationErrorCode.INVALID_JSON,
                stage="smoke_validation",
                retryable=False,
                fallbackable=False,
                backend="generation_backend",
                details={"reason": "invalid_json"},
            ) from exc
        if payload != {"ok": True, "backend_smoke": "passed"}:
            raise GenerationError(
                error_code=GenerationErrorCode.SCHEMA_VALIDATION_FAILED,
                stage="smoke_validation",
                retryable=False,
                fallbackable=False,
                backend="generation_backend",
                details={"reason": "unexpected_smoke_payload"},
            )

    @classmethod
    def _text_smoke_validator(cls, text: str) -> None:
        if (text or "").strip() != "DSA_GENERATION_BACKEND_SMOKE_OK":
            raise GenerationError(
                error_code=GenerationErrorCode.SCHEMA_VALIDATION_FAILED,
                stage="smoke_validation",
                retryable=False,
                fallbackable=False,
                backend="generation_backend",
                details={"reason": "unexpected_smoke_text"},
            )

    def _build_status(
        self,
        *,
        backend_id: str,
        is_primary: bool,
        fallback_target: Optional[str],
        health_status: HealthStatus,
        error: Optional[GenerationError] = None,
    ) -> Dict[str, Any]:
        config = self._build_backend_config()
        try:
            cheap_error = self._cheap_check_error(backend_id, config)
        except GenerationError as exc:
            cheap_error = exc
        status_error = error or cheap_error
        available = cheap_error is None
        current_health = health_status
        if health_status == "not_tested" and cheap_error is not None:
            current_health = "failed"
        capabilities = self._capabilities_for_backend(backend_id)
        backend_type = "local_cli" if backend_id in LOCAL_CLI_GENERATION_BACKEND_IDS else "litellm"
        return {
            "backend_id": backend_id,
            "backend_type": backend_type,
            "provider_id": backend_id,
            "available": available,
            "health_status": current_health,
            "supports_json": capabilities.supports_json,
            "supports_tools": capabilities.supports_tools,
            "supports_stream": capabilities.supports_stream,
            "supports_vision": capabilities.supports_vision,
            "is_primary": is_primary,
            "fallback_target": fallback_target,
            "max_concurrency": self._max_concurrency_for_backend(backend_id, config),
            "usage_available": backend_id == LITELLM_BACKEND_ID,
            "last_error_code": _as_error_code(status_error.error_code) if status_error else None,
            "last_error_message": status_error.message if status_error else None,
        }

    def _status_for_error(
        self,
        *,
        backend_id: str,
        is_primary: bool,
        fallback_target: Optional[str],
        error: GenerationError,
    ) -> Dict[str, Any]:
        return self._build_status(
            backend_id=backend_id,
            is_primary=is_primary,
            fallback_target=fallback_target,
            health_status="failed",
            error=error,
        )

    def _cheap_check_error(self, backend_id: str, config: Any) -> Optional[GenerationError]:
        numeric_error = self._numeric_config_error_for_backend(backend_id)
        if numeric_error is not None:
            return numeric_error
        if backend_id in LOCAL_CLI_GENERATION_BACKEND_IDS:
            preset = resolve_local_cli_preset(backend_id)
            return LocalCliGenerationBackend(config, preset_id=backend_id, preset=preset).get_config_error()
        if backend_id == LITELLM_BACKEND_ID:
            validation_error = self._validation_issue_error(backend_id)
            if validation_error is not None:
                return validation_error
            route_error = self._litellm_route_error(config)
            if route_error is not None:
                return route_error
            model = str(getattr(config, "litellm_model", "") or "").strip()
            model_list = getattr(config, "llm_model_list", []) or []
            has_model_list = bool(model_list)
            has_keys = any(
                getattr(config, attr, None)
                for attr in ("gemini_api_keys", "anthropic_api_keys", "openai_api_keys", "deepseek_api_keys")
            )
            if model or has_model_list or has_keys:
                return None
            return GenerationError(
                error_code=GenerationErrorCode.BACKEND_NOT_CONFIGURED,
                stage="configuration",
                retryable=False,
                fallbackable=False,
                backend=backend_id,
                details={"reason": "litellm_model_not_configured"},
            )
        return GenerationError(
            error_code=GenerationErrorCode.BACKEND_NOT_CONFIGURED,
            stage="configuration",
            retryable=False,
            fallbackable=False,
            backend=backend_id,
            details={"reason": "unsupported_generation_backend"},
        )

    def _litellm_route_error(self, config: Any) -> Optional[GenerationError]:
        model = str(getattr(config, "litellm_model", "") or "").strip()
        model_list = getattr(config, "llm_model_list", []) or []
        route_models = set(get_configured_llm_models(model_list))
        uses_legacy_router = any(str(route).startswith("__legacy_") for route in route_models)
        fallback_models = self._split_csv(self._effective_map.get("LITELLM_FALLBACK_MODELS") or "")

        if route_models and not uses_legacy_router:
            invalid_primary = model and model not in route_models and not _uses_direct_env_provider(model)
            if invalid_primary:
                return self._litellm_runtime_source_error(
                    field="LITELLM_MODEL",
                    model=model,
                    reason="unknown_model",
                )
            invalid_fallbacks = [
                fallback for fallback in fallback_models
                if fallback not in route_models and not _uses_direct_env_provider(fallback)
            ]
            if invalid_fallbacks:
                return self._litellm_runtime_source_error(
                    field="LITELLM_FALLBACK_MODELS",
                    model=invalid_fallbacks[0],
                    reason="unknown_model",
                )
            return None

        for field, candidates in (
            ("LITELLM_MODEL", [model] if model else []),
            ("LITELLM_FALLBACK_MODELS", fallback_models),
        ):
            for candidate in candidates:
                if not self._has_litellm_runtime_source(candidate):
                    return self._litellm_runtime_source_error(
                        field=field,
                        model=candidate,
                        reason="missing_runtime_source",
                    )
        return None

    def _has_litellm_runtime_source(self, model: str) -> bool:
        if not model or _uses_direct_env_provider(model):
            return True
        provider = _get_litellm_provider(model)
        if provider in {"gemini", "vertex_ai"}:
            return bool(
                self._split_csv(
                    self._effective_map.get("GEMINI_API_KEYS")
                    or self._effective_map.get("GEMINI_API_KEY")
                    or ""
                )
            )
        if provider == "anthropic":
            return bool(
                self._split_csv(
                    self._effective_map.get("ANTHROPIC_API_KEYS")
                    or self._effective_map.get("ANTHROPIC_API_KEY")
                    or ""
                )
            )
        if provider == "deepseek":
            return bool(
                self._split_csv(
                    self._effective_map.get("DEEPSEEK_API_KEYS")
                    or self._effective_map.get("DEEPSEEK_API_KEY")
                    or ""
                )
            )
        if provider == "openai":
            return bool(self._openai_keys_from_map(self._effective_map))
        return False

    @staticmethod
    def _litellm_runtime_source_error(*, field: str, model: str, reason: str) -> GenerationError:
        return GenerationError(
            error_code=GenerationErrorCode.UNSAFE_CONFIG,
            stage="configuration",
            retryable=False,
            fallbackable=False,
            backend=LITELLM_BACKEND_ID,
            details={
                "field": field,
                "reason": reason,
                "model": model,
            },
        )

    def _numeric_config_error_for_backend(self, backend_id: str) -> Optional[GenerationError]:
        specs = _LOCAL_CLI_NUMERIC_SPECS if backend_id in LOCAL_CLI_GENERATION_BACKEND_IDS else _LITELLM_NUMERIC_SPECS
        for spec in specs:
            error = _validate_int_config_value(
                backend_id=backend_id,
                value=self._effective_map.get(spec.key),
                spec=spec,
            )
            if error is not None:
                return error
        return None

    def _validation_issue_error(self, backend_id: str) -> Optional[GenerationError]:
        if backend_id != LITELLM_BACKEND_ID:
            return None
        errors = [
            issue for issue in self._validation_issues
            if str(issue.get("severity", "")).lower() == "error"
        ]
        if not errors:
            return None
        first = errors[0]
        return GenerationError(
            error_code=GenerationErrorCode.UNSAFE_CONFIG,
            stage="configuration",
            retryable=False,
            fallbackable=False,
            backend=backend_id,
            details={
                "field": first.get("key") or "generation_backend_config",
                "reason": first.get("code") or "validation_failed",
                "message": first.get("message") or "",
            },
        )

    @staticmethod
    def _capabilities_for_backend(backend_id: str) -> GenerationCapabilities:
        if backend_id in LOCAL_CLI_GENERATION_BACKEND_IDS:
            return LocalCliGenerationBackend.capabilities
        return GenerationCapabilities(
            supports_json=True,
            supports_tools=True,
            supports_stream=True,
            supports_vision=False,
            supports_health_check=False,
            supports_smoke_test=True,
        )

    @staticmethod
    def _max_concurrency_for_backend(backend_id: str, config: Any) -> int:
        if backend_id in LOCAL_CLI_GENERATION_BACKEND_IDS:
            return effective_local_cli_concurrency(config)
        return _parse_int_config_value(
            getattr(config, "generation_backend_max_concurrency", None),
            _GENERATION_BACKEND_MAX_CONCURRENCY_SPEC,
        )

    def _build_backend_config(self) -> SimpleNamespace:
        model_list = self._build_litellm_model_list(self._effective_map)
        route_models = get_configured_llm_models(model_list)
        litellm_model = (self._effective_map.get("LITELLM_MODEL") or "").strip()
        uses_legacy_router = bool(model_list) and all(
            str(entry.get("model_name") or "").startswith("__legacy_")
            for entry in model_list
            if isinstance(entry, dict)
        )
        if not litellm_model and route_models and not uses_legacy_router:
            litellm_model = route_models[0]
        if not litellm_model and uses_legacy_router:
            litellm_model = self._infer_legacy_litellm_model(self._effective_map)
        return SimpleNamespace(
            generation_backend=normalize_backend_id(
                self._effective_map.get("GENERATION_BACKEND"),
                default=LITELLM_BACKEND_ID,
            ),
            generation_fallback_backend=self._fallback_from_map(),
            generation_backend_timeout_seconds=_parse_int_config_value(
                self._effective_map.get("GENERATION_BACKEND_TIMEOUT_SECONDS"),
                _LOCAL_CLI_NUMERIC_SPECS[0],
            ),
            generation_backend_max_output_bytes=_parse_int_config_value(
                self._effective_map.get("GENERATION_BACKEND_MAX_OUTPUT_BYTES"),
                _LOCAL_CLI_NUMERIC_SPECS[1],
            ),
            generation_backend_max_concurrency=_parse_int_config_value(
                self._effective_map.get("GENERATION_BACKEND_MAX_CONCURRENCY"),
                _GENERATION_BACKEND_MAX_CONCURRENCY_SPEC,
            ),
            local_cli_backend_max_concurrency=_parse_int_config_value(
                self._effective_map.get("LOCAL_CLI_BACKEND_MAX_CONCURRENCY"),
                _LOCAL_CLI_NUMERIC_SPECS[3],
            ),
            opencode_cli_model=(self._effective_map.get("OPENCODE_CLI_MODEL") or "").strip(),
            litellm_model=litellm_model,
            llm_model_list=model_list,
        )

    def _fallback_from_map(self) -> str:
        if "GENERATION_FALLBACK_BACKEND" not in self._effective_map:
            return LITELLM_BACKEND_ID
        return (self._effective_map.get("GENERATION_FALLBACK_BACKEND") or "").strip().lower()

    def _build_config(
        self,
        effective_map: Dict[str, str],
        *,
        backend_id: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ) -> Config:
        config = self._build_backend_config()
        primary = backend_id or config.generation_backend
        openai_keys = self._openai_keys_from_map(effective_map)
        return Config(
            generation_backend=primary,
            generation_fallback_backend="",
            generation_backend_timeout_seconds=timeout_seconds or config.generation_backend_timeout_seconds,
            generation_backend_max_output_bytes=config.generation_backend_max_output_bytes,
            generation_backend_max_concurrency=config.generation_backend_max_concurrency,
            local_cli_backend_max_concurrency=config.local_cli_backend_max_concurrency,
            opencode_cli_model=config.opencode_cli_model,
            litellm_model=config.litellm_model,
            litellm_fallback_models=self._split_csv(effective_map.get("LITELLM_FALLBACK_MODELS") or ""),
            llm_model_list=config.llm_model_list,
            gemini_api_keys=self._split_csv(
                effective_map.get("GEMINI_API_KEYS")
                or effective_map.get("GEMINI_API_KEY")
                or ""
            ),
            anthropic_api_keys=self._split_csv(
                effective_map.get("ANTHROPIC_API_KEYS")
                or effective_map.get("ANTHROPIC_API_KEY")
                or ""
            ),
            openai_api_keys=openai_keys,
            deepseek_api_keys=self._split_csv(
                effective_map.get("DEEPSEEK_API_KEYS")
                or effective_map.get("DEEPSEEK_API_KEY")
                or ""
            ),
            gemini_api_key=(effective_map.get("GEMINI_API_KEY") or None),
            anthropic_api_key=(effective_map.get("ANTHROPIC_API_KEY") or None),
            openai_api_key=(openai_keys[0] if openai_keys else None),
            openai_base_url=self._openai_base_url_from_map(effective_map),
        )

    @classmethod
    def _build_litellm_model_list(cls, effective_map: Dict[str, str]) -> List[Dict[str, Any]]:
        litellm_config_path = (effective_map.get("LITELLM_CONFIG") or "").strip()
        if litellm_config_path:
            return Config._parse_litellm_yaml(litellm_config_path)

        channels = cls._parse_llm_channels_from_map(effective_map)
        if channels:
            return Config._channels_to_model_list(channels)

        return Config._legacy_keys_to_model_list(
            cls._split_csv(effective_map.get("GEMINI_API_KEYS") or effective_map.get("GEMINI_API_KEY") or ""),
            cls._split_csv(effective_map.get("ANTHROPIC_API_KEYS") or effective_map.get("ANTHROPIC_API_KEY") or ""),
            cls._openai_keys_from_map(effective_map),
            cls._openai_base_url_from_map(effective_map),
            cls._split_csv(effective_map.get("DEEPSEEK_API_KEYS") or effective_map.get("DEEPSEEK_API_KEY") or ""),
        )

    @classmethod
    def _openai_keys_from_map(cls, effective_map: Dict[str, str]) -> List[str]:
        openai_keys = cls._split_csv(effective_map.get("OPENAI_API_KEYS") or "")
        if openai_keys:
            return openai_keys
        aihubmix_key = (effective_map.get("AIHUBMIX_KEY") or "").strip()
        if aihubmix_key:
            return [aihubmix_key]
        return cls._split_csv(effective_map.get("OPENAI_API_KEY") or "")

    @staticmethod
    def _openai_base_url_from_map(effective_map: Dict[str, str]) -> Optional[str]:
        explicit = (effective_map.get("OPENAI_BASE_URL") or "").strip()
        if explicit:
            return explicit
        return "https://aihubmix.com/v1" if (effective_map.get("AIHUBMIX_KEY") or "").strip() else None

    @classmethod
    def _infer_legacy_litellm_model(cls, effective_map: Dict[str, str]) -> str:
        gemini_keys = cls._split_csv(effective_map.get("GEMINI_API_KEYS") or effective_map.get("GEMINI_API_KEY") or "")
        if gemini_keys:
            model = (effective_map.get("GEMINI_MODEL") or "gemini-3.1-pro-preview").strip()
            return model if "/" in model else f"gemini/{model}"

        anthropic_keys = cls._split_csv(
            effective_map.get("ANTHROPIC_API_KEYS")
            or effective_map.get("ANTHROPIC_API_KEY")
            or ""
        )
        if anthropic_keys:
            model = (effective_map.get("ANTHROPIC_MODEL") or "claude-sonnet-4-6").strip()
            return model if "/" in model else f"anthropic/{model}"

        deepseek_keys = cls._split_csv(
            effective_map.get("DEEPSEEK_API_KEYS")
            or effective_map.get("DEEPSEEK_API_KEY")
            or ""
        )
        if deepseek_keys:
            return "deepseek/deepseek-chat"

        if cls._openai_keys_from_map(effective_map):
            model = (effective_map.get("OPENAI_MODEL") or "gpt-5.5").strip()
            return model if "/" in model else f"openai/{model}"

        return ""

    @classmethod
    def _parse_llm_channels_from_map(cls, effective_map: Dict[str, str]) -> List[Dict[str, Any]]:
        channels: List[Dict[str, Any]] = []
        for raw_name in cls._split_csv(effective_map.get("LLM_CHANNELS") or ""):
            name = raw_name.strip()
            if not name:
                continue
            lower = name.lower()
            prefix = f"LLM_{name.upper()}"
            enabled_raw = effective_map.get(f"{prefix}_ENABLED")
            if lower == "anspire" and not (enabled_raw or "").strip():
                enabled_raw = effective_map.get("ANSPIRE_LLM_ENABLED")
            if not parse_env_bool(enabled_raw, default=True):
                continue

            base_url = (effective_map.get(f"{prefix}_BASE_URL") or "").strip() or None
            if lower == "anspire" and not base_url:
                base_url = (effective_map.get("ANSPIRE_LLM_BASE_URL") or ANSPIRE_LLM_BASE_URL_DEFAULT).strip() or None
            protocol_raw = (effective_map.get(f"{prefix}_PROTOCOL") or "").strip()
            if lower == "anspire" and not protocol_raw:
                protocol_raw = "openai"

            api_keys = cls._split_csv(effective_map.get(f"{prefix}_API_KEYS") or "")
            single_key = (effective_map.get(f"{prefix}_API_KEY") or "").strip()
            if not api_keys and single_key:
                api_keys = [single_key]
            if lower == "anspire" and not api_keys:
                api_keys = cls._split_csv(effective_map.get("ANSPIRE_API_KEYS") or "")

            raw_models = cls._split_csv(effective_map.get(f"{prefix}_MODELS") or "")
            if lower == "anspire" and not raw_models:
                raw_models = [(effective_map.get("ANSPIRE_LLM_MODEL") or ANSPIRE_LLM_MODEL_DEFAULT).strip()]

            if is_reserved_hermes_name(name):
                result = parse_hermes_channel(
                    enabled=True,
                    protocol=protocol_raw or HERMES_DEFAULT_PROTOCOL,
                    base_url=base_url or HERMES_DEFAULT_BASE_URL,
                    api_key=single_key,
                    api_keys_raw=(effective_map.get(f"{prefix}_API_KEYS") or "").strip(),
                    extra_headers_raw=(effective_map.get(f"{prefix}_EXTRA_HEADERS") or "").strip(),
                    models=raw_models or [HERMES_DEFAULT_MODEL],
                )
                if result.channel is not None:
                    channels.append(result.channel)
                continue

            protocol = resolve_llm_channel_protocol(protocol_raw, base_url=base_url, models=raw_models, channel_name=name)
            models = [normalize_llm_channel_model(model, protocol, base_url) for model in raw_models]
            if not api_keys and channel_allows_empty_api_key(protocol, base_url):
                api_keys = [""]
            if not api_keys or not models:
                continue

            extra_headers = cls._parse_json_object(effective_map.get(f"{prefix}_EXTRA_HEADERS") or "")
            channels.append(
                {
                    "name": lower,
                    "protocol": protocol,
                    "enabled": True,
                    "base_url": base_url,
                    "api_keys": api_keys,
                    "models": models,
                    "extra_headers": extra_headers,
                }
            )
        return channels

    @staticmethod
    def _parse_json_object(value: str) -> Optional[Dict[str, Any]]:
        raw = (value or "").strip()
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _split_csv(value: str) -> List[str]:
        return [item.strip() for item in (value or "").split(",") if item.strip()]
