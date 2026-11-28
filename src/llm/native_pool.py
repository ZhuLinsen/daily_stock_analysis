# -*- coding: utf-8 -*-
"""Thread-safe multi-deployment cooldown pool and equal-priority round-robin balancer.

Implements engine invariants P1, P2, and R6:
- R6: Exact alias (``spec.alias``) matching only (no fallback ``wire_model`` matching).
- P1: Skip cooling deployments whenever at least one healthy deployment exists;
  parse both numeric seconds and RFC 7231/9110 HTTP-date ``Retry-After`` headers.
- P2: Default priority 0 within an alias with per-(alias, priority) round-robin
  rotation so equal-tier keys distribute evenly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import threading
import time
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from src.llm.native_types import DeploymentSpec


def parse_retry_after(
    value: Optional[str],
    *,
    now_wall: Optional[Callable[[], float]] = None,
    max_seconds: float = 300.0,
) -> Optional[float]:
    """Parse numeric seconds or HTTP-date ``Retry-After`` header, clamped to ``(0, max_seconds]``."""
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None

    # 1. Numeric delay-seconds
    try:
        seconds = float(cleaned)
    except ValueError:
        seconds = math.nan
    if math.isfinite(seconds):
        if seconds <= 0:
            return None
        return min(seconds, max_seconds)

    # 2. HTTP-date (RFC 7231 / RFC 9110)
    try:
        parsed_dt = parsedate_to_datetime(cleaned)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed_dt is None:
        return None
    if parsed_dt.tzinfo is None:
        parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
    current_ts = float(now_wall()) if now_wall is not None else datetime.now(timezone.utc).timestamp()
    delta = parsed_dt.timestamp() - current_ts
    if not math.isfinite(delta) or delta <= 0:
        return None
    return min(delta, max_seconds)


@dataclass
class _DeploymentState:
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    last_status_code: Optional[int] = None


class DeploymentPool:
    """Thread-safe priority + round-robin deployment pool with explicit cooldown exclusion."""

    def __init__(
        self,
        deployments: Optional[Iterable[DeploymentSpec]] = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        base_cooldown_seconds: float = 30.0,
        max_cooldown_seconds: float = 300.0,
    ) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._base_cooldown_seconds = max(1.0, float(base_cooldown_seconds))
        self._max_cooldown_seconds = max(self._base_cooldown_seconds, float(max_cooldown_seconds))
        self._deployments: List[DeploymentSpec] = list(deployments or [])
        self._states: Dict[str, _DeploymentState] = {
            dep.deployment_id: _DeploymentState() for dep in self._deployments
        }
        self._tier_cursors: Dict[Tuple[str, int], int] = {}

    @property
    def deployments(self) -> List[DeploymentSpec]:
        """Return a shallow copy of registered deployments."""
        with self._lock:
            return list(self._deployments)

    def add_deployment(self, spec: DeploymentSpec) -> None:
        """Register or replace a deployment cleanly."""
        with self._lock:
            self._deployments = [d for d in self._deployments if d.deployment_id != spec.deployment_id]
            self._deployments.append(spec)
            self._states.setdefault(spec.deployment_id, _DeploymentState())

    def has_alias(self, alias: str) -> bool:
        """Return True if at least one deployment matches ``alias`` exactly."""
        target = str(alias or "").strip()
        if not target:
            return False
        with self._lock:
            return any(d.alias == target for d in self._deployments)

    def get_alias_deployments(self, model_name: Optional[str] = None) -> List[DeploymentSpec]:
        """Return ALL registered deployments for ``model_name`` regardless of cooldown (P0-2)."""
        target = str(model_name or "").strip()
        with self._lock:
            if not target:
                return list(self._deployments)
            return [d for d in self._deployments if d.alias == target]

    def peek_candidates(
        self,
        model_name: Optional[str] = None,
        *,
        exclude_ids: Optional[Iterable[str]] = None,
    ) -> List[DeploymentSpec]:
        """Return ordered candidate deployments WITHOUT advancing round-robin cursors."""
        return self.select_candidates(
            model_name,
            exclude_ids=exclude_ids,
            advance_cursor=False,
        )

    def select_candidates(
        self,
        model_name: Optional[str] = None,
        *,
        exclude_ids: Optional[Iterable[str]] = None,
        advance_cursor: bool = True,
    ) -> List[DeploymentSpec]:
        """Return candidate deployments for exact ``model_name`` alias.

        - R6: Exact alias match only (never matches ``wire_model``).
        - P1: Returns ONLY healthy deployments when at least one healthy deployment
          exists; falls back to cooling deployments (sorted by soonest expiry) ONLY
          when every matching deployment is cooling.
        - P2: Rotates equal-priority tiers via per-(alias, priority) round-robin cursor
          when ``advance_cursor=True``.
        """
        excluded = set(exclude_ids or ())
        with self._lock:
            now = self._clock()
            target = str(model_name or "").strip()
            matching = [
                d
                for d in self._deployments
                if (not target or d.alias == target) and d.deployment_id not in excluded
            ]
            if not matching:
                return []

            healthy: List[DeploymentSpec] = []
            cooling: List[Tuple[float, int, int, DeploymentSpec]] = []

            for idx, dep in enumerate(matching):
                state = self._states.setdefault(dep.deployment_id, _DeploymentState())
                if state.cooldown_until <= now:
                    healthy.append(dep)
                else:
                    cooling.append((state.cooldown_until, dep.priority, idx, dep))

            if healthy:
                ordered_healthy: List[DeploymentSpec] = []
                tiers: Dict[int, List[DeploymentSpec]] = {}
                for dep in healthy:
                    tiers.setdefault(dep.priority, []).append(dep)
                for priority in sorted(tiers.keys()):
                    bucket = tiers[priority]
                    cursor_key = (target, priority)
                    cursor = self._tier_cursors.get(cursor_key, 0) % len(bucket)
                    ordered_healthy.extend(bucket[cursor:] + bucket[:cursor])
                    if advance_cursor:
                        self._tier_cursors[cursor_key] = (cursor + 1) % len(bucket)
                return ordered_healthy

            # All matching deployments are cooling: return soonest-expiring first.
            cooling.sort(key=lambda item: (item[0], item[1], item[2]))
            return [item[3] for item in cooling]

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
