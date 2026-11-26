# -*- coding: utf-8 -*-
"""Explicit thread-safe multi-deployment / multi-key cooldown pool."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

_BEARER_TOKEN_RE = re.compile(r"(Bearer\s+)[^\s\"',;]+", re.IGNORECASE)
_SK_TOKEN_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{6,}")
_QUERY_SECRET_RE = re.compile(r"([?&](?:api_?key|key|token|secret)=)[^&\s\"']+", re.IGNORECASE)
_HEADER_SECRET_RE = re.compile(
    r"((?:x-api-key|x-goog-api-key|authorization|api-key)\s*[:=]\s*)[^\s\"',;]+",
    re.IGNORECASE,
)


def sanitize_error_message(text: Any, secrets: Iterable[str] = ()) -> str:
    """Redact API keys, Bearer tokens, and explicit secret values from error text."""
    raw = str(text or "")
    for secret in secrets:
        s = str(secret or "").strip()
        if len(s) >= 4:
            raw = raw.replace(s, "***")
    raw = _BEARER_TOKEN_RE.sub(r"\1***", raw)
    raw = _SK_TOKEN_RE.sub("sk-***", raw)
    raw = _QUERY_SECRET_RE.sub(r"\1***", raw)
    raw = _HEADER_SECRET_RE.sub(r"\1***", raw)
    return raw


def parse_retry_after(value: Optional[str], *, max_seconds: float = 300.0) -> Optional[float]:
    """Parse numeric ``Retry-After`` header seconds clamped to ``(0, max_seconds]``."""
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    try:
        seconds = float(cleaned)
    except ValueError:
        return None
    if seconds <= 0:
        return None
    return min(seconds, max_seconds)


class NativeHTTPStatusError(Exception):
    """Sanitized HTTP status error raised before higher-level provider classification."""

    def __init__(self, status_code: int, message: str, *, retry_after: Optional[float] = None) -> None:
        self.status_code = int(status_code)
        self.retry_after = retry_after
        super().__init__(message)


@dataclass
class DeploymentEntry:
    """Single API key / endpoint deployment participating in pooled routing."""

    deployment_id: str
    model_name: str
    wire_model: str
    api_base: str
    api_key: Optional[str] = None
    protocol: str = "openai_chat"
    provider: str = "openai"
    extra_headers: Dict[str, str] = field(default_factory=dict)
    extra_body: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    timeout: Optional[float] = None


@dataclass
class _DeploymentState:
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    last_status_code: Optional[int] = None


class DeploymentPool:
    """Thread-safe priority + round-robin deployment pool with explicit cooldown tracking."""

    def __init__(
        self,
        deployments: Optional[Iterable[DeploymentEntry]] = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        base_cooldown_seconds: float = 30.0,
        max_cooldown_seconds: float = 300.0,
    ) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._base_cooldown_seconds = max(1.0, float(base_cooldown_seconds))
        self._max_cooldown_seconds = max(self._base_cooldown_seconds, float(max_cooldown_seconds))
        self._deployments: List[DeploymentEntry] = list(deployments or [])
        self._states: Dict[str, _DeploymentState] = {
            dep.deployment_id: _DeploymentState() for dep in self._deployments
        }
        self._tier_cursors: Dict[int, int] = {}

    @property
    def deployments(self) -> List[DeploymentEntry]:
        """Return a shallow copy of registered deployments."""
        with self._lock:
            return list(self._deployments)

    def add_deployment(self, entry: DeploymentEntry) -> None:
        """Register or replace a deployment entry cleanly."""
        with self._lock:
            self._deployments = [d for d in self._deployments if d.deployment_id != entry.deployment_id]
            self._deployments.append(entry)
            self._states.setdefault(entry.deployment_id, _DeploymentState())

    def _matches_model(self, entry: DeploymentEntry, model_name: Optional[str]) -> bool:
        if not model_name:
            return True
        target = model_name.strip()
        return entry.model_name == target or entry.wire_model == target

    def select_candidates(self, model_name: Optional[str] = None) -> List[DeploymentEntry]:
        """Return candidate deployments ordered by priority tier & healthy round-robin rotation."""
        with self._lock:
            now = self._clock()
            matching = [d for d in self._deployments if self._matches_model(d, model_name)]
            if not matching:
                return []

            healthy: List[DeploymentEntry] = []
            cooling: List[tuple[float, int, int, DeploymentEntry]] = []

            for idx, dep in enumerate(matching):
                state = self._states.setdefault(dep.deployment_id, _DeploymentState())
                if state.cooldown_until <= now:
                    healthy.append(dep)
                else:
                    cooling.append((state.cooldown_until, dep.priority, idx, dep))

            ordered_healthy: List[DeploymentEntry] = []
            if healthy:
                tiers: Dict[int, List[DeploymentEntry]] = {}
                for dep in healthy:
                    tiers.setdefault(dep.priority, []).append(dep)
                for priority in sorted(tiers.keys()):
                    bucket = tiers[priority]
                    cursor = self._tier_cursors.get(priority, 0) % len(bucket)
                    ordered_healthy.extend(bucket[cursor:] + bucket[:cursor])
                    self._tier_cursors[priority] = (cursor + 1) % len(bucket)

            cooling.sort(key=lambda item: (item[0], item[1], item[2]))
            ordered_cooling = [item[3] for item in cooling]
            return ordered_healthy + ordered_cooling

    def mark_failure(
        self,
        deployment_id: str,
        *,
        status_code: Optional[int] = None,
        retry_after: Optional[float] = None,
    ) -> float:
        """Record a deployment failure and return applied cooldown duration in seconds."""
        with self._lock:
            now = self._clock()
            state = self._states.setdefault(deployment_id, _DeploymentState())
            state.consecutive_failures += 1
            state.last_status_code = status_code

            if retry_after is not None and retry_after > 0:
                cooldown = min(float(retry_after), self._max_cooldown_seconds)
            elif status_code in (401, 403):
                cooldown = min(
                    max(self._base_cooldown_seconds * 4.0, 60.0),
                    self._max_cooldown_seconds,
                )
            else:
                exponent = min(state.consecutive_failures - 1, 5)
                cooldown = min(
                    self._base_cooldown_seconds * (2.0 ** exponent),
                    self._max_cooldown_seconds,
                )

            state.cooldown_until = now + cooldown
            return cooldown

    def mark_success(self, deployment_id: str) -> None:
        """Reset failure counters and active cooldown for a healthy deployment."""
        with self._lock:
            state = self._states.setdefault(deployment_id, _DeploymentState())
            state.consecutive_failures = 0
            state.cooldown_until = 0.0
            state.last_status_code = 200

    def get_health_snapshot(self) -> List[Dict[str, Any]]:
        """Return sanitized deployment health state without exposing API keys."""
        with self._lock:
            now = self._clock()
            snapshot: List[Dict[str, Any]] = []
            for dep in self._deployments:
                state = self._states.setdefault(dep.deployment_id, _DeploymentState())
                remaining = max(0.0, state.cooldown_until - now)
                snapshot.append(
                    {
                        "deployment_id": dep.deployment_id,
                        "model_name": dep.model_name,
                        "wire_model": dep.wire_model,
                        "protocol": dep.protocol,
                        "priority": dep.priority,
                        "healthy": remaining <= 0.0,
                        "cooldown_remaining_seconds": round(remaining, 2),
                        "consecutive_failures": state.consecutive_failures,
                        "last_status_code": state.last_status_code,
                    }
                )
            return snapshot
