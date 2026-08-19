# -*- coding: utf-8 -*-
"""DSA Research OS — ResearchOrchestrator.

Orchestrates multiple ``ResearchProvider`` instances for a single
``ResearchRequest``:

- task state machine: queued / running / succeeded / partial / failed /
  cancelled / timed_out
- per-provider timeout and total deadline
- concurrency limit
- cancellation propagation with worker quiescence
- evidence validation (every claim must reference existing evidence)
- output size enforcement
- conflict-aware integration into an ``IntegratedDecision`` with
  independent short / medium / long horizons (no simple averaging)

The orchestrator is synchronous and thread-based, uses only the standard
library, and never makes network calls itself.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from src.agent.research_provider import ResearchProvider
from src.schemas.research_contracts import (
    ConflictItem,
    ConflictResolutionStatus,
    ConflictType,
    FrameworkOpinion,
    Horizon,
    HorizonDecision,
    IntegratedDecision,
    ProviderError,
    ProviderErrorCode,
    ResearchRequest,
    Stance,
    to_json,
)


class ResearchTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class ProviderRunResult:
    """Outcome of a single provider execution within a task."""

    provider_id: str
    status: ResearchTaskStatus
    opinion: Optional[FrameworkOpinion] = None
    error: Optional[ProviderError] = None
    started_at: str = ""
    finished_at: str = ""
    attempts: int = 1


@dataclass(frozen=True)
class OrchestrationResult:
    """Full outcome of an orchestrated research task."""

    task_id: str
    request_id: str
    run_id: str
    status: ResearchTaskStatus
    as_of: str
    provider_results: Tuple[ProviderRunResult, ...] = ()
    integrated: Optional[IntegratedDecision] = None
    warnings: Tuple[str, ...] = ()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _opinion_bytes(op: FrameworkOpinion) -> int:
    return len(to_json(op).encode("utf-8"))


def _evidence_ids(op: FrameworkOpinion) -> frozenset:
    return frozenset(e.evidence_id for e in op.evidence_refs)


class _Worker(threading.Thread):
    """Runs a single provider.research() call and captures the outcome."""

    def __init__(
        self,
        provider: ResearchProvider,
        request: ResearchRequest,
    ) -> None:
        super().__init__(name=f"research-provider:{provider.provider_id}", daemon=False)
        self._provider = provider
        self._request = request
        self.result: Optional[FrameworkOpinion | ProviderError] = None
        self.exception: Optional[BaseException] = None

    def run(self) -> None:
        try:
            self.result = self._provider.research(self._request)
        except BaseException as exc:  # noqa: BLE001 - captured for error reporting
            self.exception = exc


class ResearchOrchestrator:
    """Orchestrates providers for a research request with full lifecycle."""

    def __init__(
        self,
        providers: Sequence[ResearchProvider],
        *,
        max_concurrency: int = 3,
        default_timeout_seconds: float = 30.0,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be > 0")
        self._providers: List[ResearchProvider] = list(providers)
        self._max_concurrency = max_concurrency
        self._default_timeout = default_timeout_seconds
        self._semaphore = threading.BoundedSemaphore(max_concurrency)
        self._cancelled: Dict[str, bool] = {}
        self._active_tasks: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, request: ResearchRequest) -> OrchestrationResult:
        """Execute the full orchestration synchronously."""
        task_id = f"task-{request.request_id}-{request.run_id}"
        with self._lock:
            # Preserve a pre-existing cancel request (do not clobber it).
            if task_id not in self._cancelled:
                self._cancelled[task_id] = False
            self._active_tasks.add(task_id)
        status = ResearchTaskStatus.RUNNING
        results: List[ProviderRunResult] = []
        warnings: List[str] = []
        integrated: Optional[IntegratedDecision] = None
        deadline = time.monotonic() + request.total_timeout_seconds

        try:
            for provider in self._providers:
                if time.monotonic() >= deadline:
                    status = ResearchTaskStatus.TIMED_OUT
                    break
                if self._is_cancelled(task_id):
                    status = ResearchTaskStatus.CANCELLED
                    break
                # An opinion is single-horizon; fan out per horizon so every
                # requested horizon is covered by every provider.
                for horizon in request.horizons or (Horizon.SHORT,):
                    if self._is_cancelled(task_id):
                        status = ResearchTaskStatus.CANCELLED
                        break
                    horizon_request = replace(request, horizons=(horizon,))
                    result = self._run_provider(provider, horizon_request, task_id)
                    results.append(result)
                    if result.error is not None:
                        warnings.append(
                            f"provider {result.provider_id}/{horizon.value}: "
                            f"{result.error.code.value}"
                        )
                    if result.status in {
                        ResearchTaskStatus.TIMED_OUT,
                        ResearchTaskStatus.CANCELLED,
                    }:
                        break
                if status == ResearchTaskStatus.CANCELLED:
                    break
            # Integration
            if results and any(r.opinion is not None for r in results):
                integrated = self.integrate(request, results)
            # Final status
            status = self._final_status(results, status)
        except Exception as exc:  # noqa: BLE001 - orchestrator must not raise
            warnings.append(f"orchestrator error: {exc}")
            status = ResearchTaskStatus.FAILED
        finally:
            with self._lock:
                self._cancelled.pop(task_id, None)
                self._active_tasks.discard(task_id)

        return OrchestrationResult(
            task_id=task_id,
            request_id=request.request_id,
            run_id=request.run_id,
            status=status,
            as_of=request.as_of,
            provider_results=tuple(results),
            integrated=integrated,
            warnings=tuple(warnings),
        )

    def cancel(self, task_id: str) -> bool:
        """Request cancellation of a task.

        If the task is already registered, marks it cancelled and returns True.
        If not yet registered (cancel before run), pre-registers the flag so
        run() will see it immediately.  Returns True in both cases.
        """
        with self._lock:
            existed = task_id in self._cancelled
            self._cancelled[task_id] = True
        for provider in self._providers:
            provider.cancel(task_id)
        return existed

    def active_task_ids(self) -> Tuple[str, ...]:
        """Return a stable snapshot of currently executing task IDs."""
        with self._lock:
            return tuple(sorted(self._active_tasks))

    def health(self) -> bool:
        """Check orchestrator health (no network, no secrets)."""
        return all(p.health() for p in self._providers)

    # ------------------------------------------------------------------
    # Integration (conflict-aware, per-horizon, no averaging)
    # ------------------------------------------------------------------

    def integrate(
        self,
        request: ResearchRequest,
        results: Sequence[ProviderRunResult],
    ) -> IntegratedDecision:
        """Integrate provider opinions into an IntegratedDecision.

        Each horizon is resolved independently.  Conflicting stances within
        a horizon produce an explicit ``ConflictItem`` and the horizon is
        marked abstain (fail-closed).  No simple averaging is performed.
        """
        opinions: List[FrameworkOpinion] = [
            r.opinion for r in results if r.opinion is not None
        ]
        if not opinions:
            return IntegratedDecision(
                request_id=request.request_id,
                run_id=request.run_id,
                as_of=request.as_of,
                short_term=HorizonDecision(
                    horizon=Horizon.SHORT,
                    stance=Stance.ABSTAIN,
                    abstain_reason="no provider returned an opinion",
                ),
                medium_term=HorizonDecision(
                    horizon=Horizon.MEDIUM,
                    stance=Stance.ABSTAIN,
                    abstain_reason="no provider returned an opinion",
                ),
                long_term=HorizonDecision(
                    horizon=Horizon.LONG,
                    stance=Stance.ABSTAIN,
                    abstain_reason="no provider returned an opinion",
                ),
            )

        decisions: Dict[Horizon, HorizonDecision] = {}
        conflicts: List[ConflictItem] = []

        for horizon in (Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG):
            horizon_opinions = [o for o in opinions if o.horizon == horizon]
            if not horizon_opinions:
                decisions[horizon] = HorizonDecision(
                    horizon=horizon,
                    stance=Stance.ABSTAIN,
                    abstain_reason=f"no opinion for {horizon.value}",
                )
                continue

            non_abstain = [o for o in horizon_opinions if o.stance != Stance.ABSTAIN]
            if not non_abstain:
                decisions[horizon] = HorizonDecision(
                    horizon=horizon,
                    stance=Stance.ABSTAIN,
                    abstain_reason="all providers abstained",
                    evidence_ids=tuple(
                        e.evidence_id for o in horizon_opinions for e in o.evidence_refs
                    ),
                )
                continue

            stances = {o.stance for o in non_abstain}
            if len(stances) > 1:
                # Conflict: keep it explicitly, do not average
                conflict = ConflictItem(
                    request_id=request.request_id,
                    run_id=request.run_id,
                    claim_text=f"{horizon.value} stance conflict: {sorted(s.value for s in stances)}",
                    conflicting_providers=tuple(sorted(o.provider_id for o in non_abstain)),
                    evidence_ids=tuple(
                        e.evidence_id for o in non_abstain for e in o.evidence_refs
                    ),
                    conflict_type=ConflictType.HORIZON,
                    resolution_status=ConflictResolutionStatus.UNRESOLVED,
                    reason_cannot_average="conflicting stances cannot be averaged",
                )
                conflicts.append(conflict)
                decisions[horizon] = HorizonDecision(
                    horizon=horizon,
                    stance=Stance.ABSTAIN,
                    abstain_reason="conflicting provider stances, unresolved",
                    evidence_ids=conflict.evidence_ids,
                )
                continue

            stance = next(iter(stances))
            chosen = [o for o in non_abstain if o.stance == stance]
            decisions[horizon] = HorizonDecision(
                horizon=horizon,
                stance=stance,
                conclusion=chosen[0].claims[0].text if chosen[0].claims else "",
                confidence=max(o.confidence for o in chosen),
                evidence_ids=tuple(
                    e.evidence_id for o in chosen for e in o.evidence_refs
                ),
                risks=tuple(r for o in chosen for r in o.risks),
            )

        provider_versions = {
            r.provider_id: r.opinion.provider_version
            for r in results
            if r.opinion is not None
        }
        return IntegratedDecision(
            request_id=request.request_id,
            run_id=request.run_id,
            as_of=request.as_of,
            short_term=decisions[Horizon.SHORT],
            medium_term=decisions[Horizon.MEDIUM],
            long_term=decisions[Horizon.LONG],
            conflicts=tuple(conflicts),
            provider_versions=provider_versions,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_provider(
        self,
        provider: ResearchProvider,
        request: ResearchRequest,
        task_id: str,
    ) -> ProviderRunResult:
        return self._run_provider_once(provider, request, task_id, attempt=1)

    def _run_provider_once(
        self,
        provider: ResearchProvider,
        request: ResearchRequest,
        task_id: str,
        attempt: int,
    ) -> ProviderRunResult:
        started = _now_iso()
        timeout = request.provider_timeout_seconds or self._default_timeout

        # Validate first (fail-closed for contract violations)
        try:
            provider.validate(request)
        except ProviderError as exc:
            return ProviderRunResult(
                provider_id=provider.provider_id,
                status=ResearchTaskStatus.FAILED,
                error=exc,
                started_at=started,
                finished_at=_now_iso(),
                attempts=attempt,
            )

        worker = _Worker(provider, request)
        deadline = time.monotonic() + timeout
        timed_out = False
        with self._semaphore:
            if self._is_cancelled(task_id):
                return ProviderRunResult(
                    provider_id=provider.provider_id,
                    status=ResearchTaskStatus.CANCELLED,
                    started_at=started,
                    finished_at=_now_iso(),
                    attempts=attempt,
                )
            worker.start()
            while worker.is_alive():
                if self._is_cancelled(task_id):
                    provider.cancel(task_id)
                    worker.join()
                    return ProviderRunResult(
                        provider_id=provider.provider_id,
                        status=ResearchTaskStatus.CANCELLED,
                        started_at=started,
                        finished_at=_now_iso(),
                        attempts=attempt,
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    provider.cancel(task_id)
                    worker.join()
                    break
                worker.join(timeout=min(0.01, remaining))

        if self._is_cancelled(task_id):
            return ProviderRunResult(
                provider_id=provider.provider_id,
                status=ResearchTaskStatus.CANCELLED,
                started_at=started,
                finished_at=_now_iso(),
                attempts=attempt,
            )
        if timed_out:
            return ProviderRunResult(
                provider_id=provider.provider_id,
                status=ResearchTaskStatus.TIMED_OUT,
                error=ProviderError(
                    request_id=request.request_id,
                    run_id=request.run_id,
                    code=ProviderErrorCode.TIMEOUT,
                    stage="research",
                    retryable=True,
                    fallbackable=True,
                    provider_id=provider.provider_id,
                    provider_version=provider.provider_version,
                    partial=False,
                    message=f"provider timed out after {timeout}s",
                ),
                started_at=started,
                finished_at=_now_iso(),
                attempts=attempt,
            )
        if worker.exception is not None:
            return ProviderRunResult(
                provider_id=provider.provider_id,
                status=ResearchTaskStatus.FAILED,
                error=ProviderError(
                    request_id=request.request_id,
                    run_id=request.run_id,
                    code=ProviderErrorCode.UNKNOWN,
                    stage="research",
                    retryable=False,
                    fallbackable=True,
                    provider_id=provider.provider_id,
                    provider_version=provider.provider_version,
                    partial=False,
                    message=str(worker.exception)[:500],
                ),
                started_at=started,
                finished_at=_now_iso(),
                attempts=attempt,
            )

        outcome = worker.result
        if isinstance(outcome, ProviderError):
            return ProviderRunResult(
                provider_id=provider.provider_id,
                status=ResearchTaskStatus.FAILED,
                error=outcome,
                started_at=started,
                finished_at=_now_iso(),
                attempts=attempt,
            )
        if not isinstance(outcome, FrameworkOpinion):
            return ProviderRunResult(
                provider_id=provider.provider_id,
                status=ResearchTaskStatus.FAILED,
                error=ProviderError(
                    request_id=request.request_id,
                    run_id=request.run_id,
                    code=ProviderErrorCode.CONTRACT_VIOLATION,
                    stage="research",
                    retryable=False,
                    fallbackable=True,
                    provider_id=provider.provider_id,
                    provider_version=provider.provider_version,
                    partial=False,
                    message="provider returned unexpected type",
                ),
                started_at=started,
                finished_at=_now_iso(),
                attempts=attempt,
            )

        # Evidence validation: every claim must reference existing evidence
        violations = self._validate_evidence(outcome)
        if violations:
            return ProviderRunResult(
                provider_id=provider.provider_id,
                status=ResearchTaskStatus.FAILED,
                error=ProviderError(
                    request_id=request.request_id,
                    run_id=request.run_id,
                    code=ProviderErrorCode.CONTRACT_VIOLATION,
                    stage="evidence_validation",
                    retryable=False,
                    fallbackable=True,
                    provider_id=provider.provider_id,
                    provider_version=provider.provider_version,
                    partial=False,
                    details={"violations": list(violations)},
                    message="opinion claims reference missing evidence",
                ),
                started_at=started,
                finished_at=_now_iso(),
                attempts=attempt,
            )

        # Output size enforcement
        if _opinion_bytes(outcome) > request.max_output_bytes:
            return ProviderRunResult(
                provider_id=provider.provider_id,
                status=ResearchTaskStatus.FAILED,
                error=ProviderError(
                    request_id=request.request_id,
                    run_id=request.run_id,
                    code=ProviderErrorCode.OUTPUT_TOO_LARGE,
                    stage="output_validation",
                    retryable=False,
                    fallbackable=True,
                    provider_id=provider.provider_id,
                    provider_version=provider.provider_version,
                    partial=False,
                    details={
                        "actual_bytes": _opinion_bytes(outcome),
                        "max_bytes": request.max_output_bytes,
                    },
                    message="opinion exceeds max_output_bytes",
                ),
                started_at=started,
                finished_at=_now_iso(),
                attempts=attempt,
            )

        return ProviderRunResult(
            provider_id=provider.provider_id,
            status=ResearchTaskStatus.SUCCEEDED,
            opinion=outcome,
            started_at=started,
            finished_at=_now_iso(),
            attempts=attempt,
        )

    def _validate_evidence(self, op: FrameworkOpinion) -> Tuple[str, ...]:
        """Return violations where a claim references missing evidence."""
        valid_ids = _evidence_ids(op)
        violations: List[str] = []
        for claim in op.claims:
            missing = [e for e in claim.evidence_ids if e not in valid_ids]
            for m in missing:
                violations.append(f"claim {claim.claim_id} references missing evidence {m}")
        return tuple(violations)

    def _final_status(
        self,
        results: List[ProviderRunResult],
        running_status: ResearchTaskStatus,
    ) -> ResearchTaskStatus:
        if running_status in {
            ResearchTaskStatus.CANCELLED,
            ResearchTaskStatus.TIMED_OUT,
        }:
            return running_status
        if any(r.status == ResearchTaskStatus.CANCELLED for r in results):
            return ResearchTaskStatus.CANCELLED
        if not results:
            return ResearchTaskStatus.FAILED
        statuses = {r.status for r in results}
        if statuses == {ResearchTaskStatus.SUCCEEDED}:
            return ResearchTaskStatus.SUCCEEDED
        if statuses == {ResearchTaskStatus.TIMED_OUT}:
            return ResearchTaskStatus.TIMED_OUT
        if statuses == {ResearchTaskStatus.FAILED}:
            return ResearchTaskStatus.FAILED
        # Mixed outcome: at least one success/timed-out among failures.
        if statuses & {ResearchTaskStatus.SUCCEEDED, ResearchTaskStatus.TIMED_OUT}:
            return ResearchTaskStatus.PARTIAL
        return ResearchTaskStatus.FAILED

    def _is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            return self._cancelled.get(task_id, False)
