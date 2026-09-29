# -*- coding: utf-8 -*-
"""Hermes local HTTP generation helpers.

Hermes Phase 3 is intentionally narrow: a reserved local OpenAI-compatible
generation channel with no tools, streaming, vision, remote hosts, or key
load-balancing support.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple
from urllib.parse import quote, unquote, urlparse, urlunparse


HERMES_CHANNEL_NAME = "hermes"
HERMES_DEPLOYMENT_MARKER_KEY = "dsa_channel"
HERMES_DEPLOYMENT_MARKER_VALUE = "hermes"
HERMES_DEFAULT_PROTOCOL = "openai"
HERMES_DEFAULT_BASE_URL = "http://127.0.0.1:8642/v1"
HERMES_DEFAULT_MODEL = "hermes-agent"
MASKED_SECRET_TOKENS = {"******"}


@dataclass(frozen=True)
class HermesConfigIssue:
    """Structured Hermes channel parse issue."""

    field: str
    code: str
    message: str
    severity: str = "error"

    def as_dict(self) -> Dict[str, str]:
        return {
            "field": self.field,
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class HermesChannelParseResult:
    """Atomic result of parsing a reserved Hermes channel."""

    channel: Optional[Dict[str, Any]]
    issues: Tuple[HermesConfigIssue, ...] = ()
    blocks_legacy_fallback: bool = False
    blocked_route_names: Tuple[str, ...] = ()


@dataclass(frozen=True)
class HermesModelRef:
    """Hermes model names split by routing identity and UI display label."""

    route_model: str
    wire_model: str
    display_model: str


@dataclass(frozen=True)
class RouteDeploymentOrigins:
    """Origin classification for all deployments under one Router route alias."""

    route_name: str
    has_hermes: bool
    has_non_hermes: bool
    hermes_deployments: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)
    non_hermes_deployments: Tuple[Dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def is_hermes_only(self) -> bool:
        return self.has_hermes and not self.has_non_hermes

    @property
    def is_mixed(self) -> bool:
        return self.has_hermes and self.has_non_hermes


def is_reserved_hermes_name(name: str) -> bool:
    return (name or "").strip().lower() == HERMES_CHANNEL_NAME


def is_masked_secret_placeholder(value: str) -> bool:
    return str(value or "").strip() in MASKED_SECRET_TOKENS


def build_hermes_redaction_values(*values: Any) -> Set[str]:
    redactions: Set[str] = set()
    for value in values:
        if value is None:
            continue
        raw_value = str(value).strip()
        if raw_value:
            redactions.add(raw_value)
            redactions.add(f"Bearer {raw_value}")
            redactions.add(f"Authorization: Bearer {raw_value}")
        for segment in str(value).split(","):
            token = segment.strip()
            if token:
                redactions.add(token)
                redactions.add(f"Bearer {token}")
                redactions.add(f"Authorization: Bearer {token}")
    return redactions


def _comma_flexible_secret_pattern(secret: str) -> Optional[re.Pattern[str]]:
    normalized = re.sub(r"(?i)^\s*authorization\s*[:=]\s*", "", str(secret or "").strip())
    normalized = re.sub(r"(?i)^\s*bearer\s+", "", normalized)
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    if len(parts) <= 1:
        return None
    return re.compile(
        r"(?i)(?:authorization\s*[:=]\s*)?(?:bearer\s+)?"
        + r"\s*,\s*".join(re.escape(part) for part in parts)
    )


def sanitize_hermes_error_text(
    text: Any,
    *,
    redaction_values: Optional[Iterable[str]] = None,
) -> str:
    if text is None:
        return ""
    sanitized = str(text).strip()
    if not sanitized:
        return ""
    values = set(redaction_values or set())
    for secret in sorted(values, key=len, reverse=True):
        pattern = _comma_flexible_secret_pattern(secret)
        if pattern is not None:
            sanitized = pattern.sub("[REDACTED]", sanitized)
    for secret in sorted(values, key=len, reverse=True):
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    patterns = [
        (r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?([^\s,;]+)", r"\1[REDACTED]"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)([^\s,;]+)", r"\1[REDACTED]"),
        (r"(?i)(cookie\s*[:=]\s*)([^\s,;]+)", r"\1[REDACTED]"),
        (r"(?i)bearer\s+[a-z0-9._\-]+", "Bearer [REDACTED]"),
        (r"(?i)sk-[a-z0-9_\-]+", "[REDACTED]"),
    ]
    for pattern, replacement in patterns:
        sanitized = re.sub(pattern, replacement, sanitized)
    return " ".join(sanitized.split())[:300]


def canonicalize_hermes_protocol(protocol: str) -> str:
    normalized = (protocol or HERMES_DEFAULT_PROTOCOL).strip().lower() or HERMES_DEFAULT_PROTOCOL
    if normalized != HERMES_DEFAULT_PROTOCOL:
        raise ValueError("Hermes only supports PROTOCOL=openai")
    return HERMES_DEFAULT_PROTOCOL


def canonicalize_hermes_base_url(base_url: str) -> str:
    """Return canonical Hermes base URL or raise ValueError.

    Allowed forms are loopback HTTP(S) URLs whose path is exactly /v1 or /v1/.
    localhost is canonicalized to 127.0.0.1 to avoid DNS/hosts ambiguity.
    """

    raw = (base_url or HERMES_DEFAULT_BASE_URL).strip() or HERMES_DEFAULT_BASE_URL
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Hermes BASE_URL must use http or https")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("Hermes BASE_URL must include a loopback host")
    if parsed.username or parsed.password:
        raise ValueError("Hermes BASE_URL must not include userinfo")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError("Hermes BASE_URL must not include params, query, or fragment")

    raw_path = parsed.path or ""
    decoded_path = unquote(raw_path)
    if decoded_path not in {"/v1", "/v1/"}:
        raise ValueError("Hermes BASE_URL path must be /v1")
    if quote(decoded_path, safe="/") != raw_path.rstrip("/") and raw_path not in {"/v1", "/v1/"}:
        raise ValueError("Hermes BASE_URL path must not contain encoded segments")

    hostname = parsed.hostname.strip().lower()
    if hostname == "localhost":
        hostname = "127.0.0.1"
    elif hostname not in {"127.0.0.1", "::1"}:
        raise ValueError("Hermes BASE_URL must point to 127.0.0.1, localhost, or [::1]")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Hermes BASE_URL contains an invalid port") from exc

    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunparse(parsed._replace(netloc=netloc, path="/v1", params="", query="", fragment=""))


def canonicalize_hermes_model_ref(raw_model: str) -> HermesModelRef:
    """Return the canonical DSA route and LiteLLM wire model for Hermes.

    Hermes is OpenAI-compatible over local HTTP, so both route identity and
    outbound wire model use LiteLLM's openai/ namespace.  The display label is
    only UI metadata and must not be used for routing or provider detection.
    """

    display_model = str(raw_model or "").strip() or HERMES_DEFAULT_MODEL
    if display_model.startswith("openai/"):
        canonical = display_model
    else:
        canonical = f"openai/{display_model}"
    return HermesModelRef(
        route_model=canonical,
        wire_model=canonical,
        display_model=display_model,
    )


def hermes_blocked_route_candidates(raw_model: str) -> set[str]:
    """Return route identities used only to match invalid Hermes selections."""

    text = str(raw_model or "").strip()
    if not text:
        return set()
    candidates = {text}
    if text.startswith("openai/"):
        candidates.add(text)
    else:
        candidates.add(f"openai/{text}")
    return candidates


def route_identity_candidates(model: str) -> set[str]:
    """Return route aliases that should share Hermes safety decisions.

    This helper is for route provenance lookups, not invalid raw Hermes model
    blocking. Keep provider-looking route aliases such as ``anthropic/foo``
    distinct from ``openai/anthropic/foo`` so valid non-Hermes routes are not
    marked as Hermes by a separate Hermes channel. Invalid Hermes raw tokens use
    hermes_blocked_route_candidates(), which intentionally matches more broadly.
    """

    text = str(model or "").strip()
    if not text:
        return set()
    candidates = {text}
    if not text.startswith("openai/") and "/" not in text:
        candidates.add(f"openai/{text}")
    return candidates


def normalize_hermes_models(models: Sequence[str]) -> Tuple[List[HermesModelRef], List[str]]:
    normalized: List[HermesModelRef] = []
    seen = set()
    errors: List[str] = []
    for raw in models:
        model = str(raw or "").strip()
        if not model:
            continue
        if any(ch.isspace() for ch in model) or "," in model or model.startswith("-"):
            errors.append(model)
            continue
        ref = canonicalize_hermes_model_ref(model)
        if ref.route_model in seen:
            continue
        seen.add(ref.route_model)
        normalized.append(ref)
    if not normalized:
        normalized = [canonicalize_hermes_model_ref(HERMES_DEFAULT_MODEL)]
    return normalized, errors


def parse_hermes_channel(
    *,
    enabled: bool,
    protocol: str,
    base_url: str,
    api_key: str,
    api_keys_raw: str,
    extra_headers_raw: str,
    models: Sequence[str],
) -> HermesChannelParseResult:
    """Parse the reserved Hermes channel atomically."""

    raw_model_tokens = [str(raw or "").strip() for raw in models if str(raw or "").strip()]
    resolved_models, malformed_models = normalize_hermes_models(models)
    blocked_candidates: List[str] = []
    if raw_model_tokens:
        for raw_model in raw_model_tokens:
            for candidate in hermes_blocked_route_candidates(raw_model):
                if candidate not in blocked_candidates:
                    blocked_candidates.append(candidate)
    else:
        blocked_candidates = [ref.route_model for ref in resolved_models]
    blocked_route_names = tuple(blocked_candidates)

    if not enabled:
        # Disabled Hermes is an intentional absence of deployment, not invalid
        # configuration, and therefore does not block lower-priority legacy env.
        return HermesChannelParseResult(
            channel=None,
            issues=(),
            blocks_legacy_fallback=False,
            blocked_route_names=(),
        )

    issues: List[HermesConfigIssue] = []
    try:
        resolved_protocol = canonicalize_hermes_protocol(protocol)
    except ValueError as exc:
        issues.append(HermesConfigIssue("LLM_HERMES_PROTOCOL", "invalid_protocol", str(exc)))
        resolved_protocol = HERMES_DEFAULT_PROTOCOL

    try:
        resolved_base_url = canonicalize_hermes_base_url(base_url)
    except ValueError as exc:
        issues.append(HermesConfigIssue("LLM_HERMES_BASE_URL", "invalid_base_url", str(exc)))
        resolved_base_url = ""

    single_key = (api_key or "").strip()
    has_unsupported_api_keys = bool((api_keys_raw or "").strip())
    if not single_key and not has_unsupported_api_keys:
        issues.append(HermesConfigIssue("LLM_HERMES_API_KEY", "missing_api_key", "Hermes requires one non-empty API key"))
    if is_masked_secret_placeholder(single_key):
        issues.append(HermesConfigIssue("LLM_HERMES_API_KEY", "masked_secret_not_reusable", "Hermes API key is a masked placeholder; re-enter the real key"))
    if "," in single_key:
        issues.append(HermesConfigIssue("LLM_HERMES_API_KEY", "multiple_api_keys", "Hermes API key must not contain commas"))
    if has_unsupported_api_keys:
        issues.append(HermesConfigIssue(
            "LLM_HERMES_API_KEYS",
            "unsupported_api_keys",
            "Hermes Phase 3 only supports single LLM_HERMES_API_KEY. Move the value from LLM_HERMES_API_KEYS to LLM_HERMES_API_KEY.",
        ))
    if (extra_headers_raw or "").strip():
        issues.append(HermesConfigIssue("LLM_HERMES_EXTRA_HEADERS", "unsupported_extra_headers", "Hermes does not support EXTRA_HEADERS in Phase 3"))

    if malformed_models:
        issues.append(HermesConfigIssue("LLM_HERMES_MODELS", "invalid_model", "Hermes model IDs must be non-empty IDs without whitespace or commas"))

    if issues:
        return HermesChannelParseResult(
            channel=None,
            issues=tuple(issues),
            blocks_legacy_fallback=True,
            blocked_route_names=blocked_route_names,
        )

    return HermesChannelParseResult(
        channel={
            "name": HERMES_CHANNEL_NAME,
            "protocol": resolved_protocol,
            "enabled": True,
            "base_url": resolved_base_url,
            "api_keys": [single_key],
            "models": [ref.route_model for ref in resolved_models],
            "model_refs": [
                {
                    "route_model": ref.route_model,
                    "wire_model": ref.wire_model,
                    "display_model": ref.display_model,
                }
                for ref in resolved_models
            ],
            "extra_headers": None,
            "is_hermes": True,
        },
        issues=(),
        blocks_legacy_fallback=False,
        blocked_route_names=(),
    )


def hermes_model_info(display_model: str = "") -> Dict[str, str]:
    info = {HERMES_DEPLOYMENT_MARKER_KEY: HERMES_DEPLOYMENT_MARKER_VALUE}
    if display_model:
        info["dsa_display_model"] = display_model
    return info


def is_hermes_deployment(deployment: Dict[str, Any]) -> bool:
    model_info = deployment.get("model_info") if isinstance(deployment, dict) else None
    if not isinstance(model_info, dict):
        return False
    return str(model_info.get(HERMES_DEPLOYMENT_MARKER_KEY, "")).lower() == HERMES_DEPLOYMENT_MARKER_VALUE


def route_deployment_origins(model_list: Sequence[Dict[str, Any]], route_name: str) -> RouteDeploymentOrigins:
    hermes: List[Dict[str, Any]] = []
    non_hermes: List[Dict[str, Any]] = []
    candidates = route_identity_candidates(route_name)
    for deployment in model_list or []:
        if not isinstance(deployment, dict):
            continue
        deployment_route_name = str(deployment.get("model_name") or "").strip()
        if deployment_route_name not in candidates:
            continue
        if is_hermes_deployment(deployment):
            hermes.append(deployment)
        else:
            non_hermes.append(deployment)
    return RouteDeploymentOrigins(
        route_name=route_name,
        has_hermes=bool(hermes),
        has_non_hermes=bool(non_hermes),
        hermes_deployments=tuple(hermes),
        non_hermes_deployments=tuple(non_hermes),
    )


def build_route_provenance_map(model_list: Sequence[Dict[str, Any]]) -> Dict[str, RouteDeploymentOrigins]:
    route_names: List[str] = []
    seen = set()
    for deployment in model_list or []:
        if not isinstance(deployment, dict):
            continue
        route_name = str(deployment.get("model_name") or "").strip()
        if route_name and route_name not in seen:
            seen.add(route_name)
            route_names.append(route_name)
    return {route_name: route_deployment_origins(model_list, route_name) for route_name in route_names}


def route_has_hermes(model_list: Sequence[Dict[str, Any]], route_name: str) -> bool:
    """Whether a route alias or display/raw candidate has a Hermes deployment.

    The lookup uses route_identity_candidates() so bare UI values and canonical
    OpenAI-compatible route aliases share the same safety result.
    """
    return route_deployment_origins(model_list, route_name).has_hermes


def filter_non_hermes_deployments(model_list: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [deployment for deployment in (model_list or []) if not is_hermes_deployment(deployment)]


@contextmanager
def open_hermes_no_proxy_client(*, api_key: str, base_url: str, timeout: float) -> Iterator[Any]:
    """Yield an OpenAI client with a no-proxy httpx transport and close it."""

    import httpx
    import openai

    canonical_base_url = canonicalize_hermes_base_url(base_url)
    http_client = httpx.Client(
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
    )
    client = openai.OpenAI(
        api_key=api_key,
        base_url=canonical_base_url,
        http_client=http_client,
    )
    try:
        yield client
    finally:
        http_client.close()
