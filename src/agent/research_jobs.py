# -*- coding: utf-8 -*-
"""Research job table and scheduler entry for ResearchOrchestrator.

Reuses the orchestrator state machine instead of starting a second Hermes
process. Jobs are stored in-process with the same statuses as the
orchestrator: queued / running / succeeded / partial / failed / cancelled /
timed_out. Public payloads never include order or broker fields.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.agent.research_orchestrator import (
    OrchestrationResult,
    ResearchOrchestrator,
    ResearchTaskStatus,
)
from src.agent.research_provider import ResearchProvider
from src.schemas.research_contracts import Horizon, IntegratedDecision, ResearchRequest

logger = logging.getLogger(__name__)

_ORDER_KEYS = frozenset(
    {
        "order",
        "orders",
        "broker",
        "quantity",
        "account",
        "order_id",
        "place_order",
        "trade",
        "position",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _task_id(request: ResearchRequest) -> str:
    return f"task-{request.request_id}-{request.run_id}"


def strip_order_fields(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: strip_order_fields(value)
            for key, value in payload.items()
            if key not in _ORDER_KEYS
        }
    if isinstance(payload, list):
        return [strip_order_fields(item) for item in payload]
    return payload


def public_horizon(decision) -> Dict[str, Any]:
    return {
        "horizon": decision.horizon.value if hasattr(decision.horizon, "value") else str(decision.horizon),
        "conclusion": decision.conclusion,
        "stance": decision.stance.value if hasattr(decision.stance, "value") else str(decision.stance),
        "action_boundary": decision.action_boundary,
        "confidence": decision.confidence,
        "evidence_ids": list(decision.evidence_ids),
        "risks": list(decision.risks),
        "abstain_reason": decision.abstain_reason,
    }


def public_decision(integrated: Optional[IntegratedDecision]) -> Optional[Dict[str, Any]]:
    if integrated is None:
        return None
    return strip_order_fields(
        {
            "as_of": integrated.as_of,
            "short_term": public_horizon(integrated.short_term),
            "medium_term": public_horizon(integrated.medium_term),
            "long_term": public_horizon(integrated.long_term),
            "conflicts": [
                strip_order_fields(
                    {
                        "claim_text": item.claim_text,
                        "conflicting_providers": list(item.conflicting_providers),
                        "evidence_ids": list(item.evidence_ids),
                        "conflict_type": item.conflict_type.value,
                        "resolution_status": item.resolution_status.value,
                        "reason_cannot_average": item.reason_cannot_average,
                    }
                )
                for item in integrated.conflicts
            ],
            "provider_versions": dict(integrated.provider_versions),
        }
    )


@dataclass
class ResearchJobRecord:
    job_id: str
    task_id: str
    idempotency_key: str
    status: ResearchTaskStatus
    request: ResearchRequest
    result: Optional[OrchestrationResult] = None
    created_at: str = ""
    updated_at: str = ""
    error: str = ""

    def to_public_dict(self) -> Dict[str, Any]:
        payload = {
            "job_id": self.job_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "idempotency_key": self.idempotency_key,
            "subject": self.request.subject,
            "market": self.request.market,
            "as_of": self.request.as_of,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "decision": public_decision(self.result.integrated if self.result else None),
            "warnings": list(self.result.warnings) if self.result else [],
            "error": self.error,
        }
        return strip_order_fields(payload)


class ResearchJobService:
    """In-process research job table used by scheduler and the later API."""

    def __init__(self, orchestrator: ResearchOrchestrator) -> None:
        self._orchestrator = orchestrator
        self._jobs: Dict[str, ResearchJobRecord] = {}
        self._idempotency: Dict[str, str] = {}
        self._lock = threading.Lock()

    def enqueue(self, request: ResearchRequest) -> ResearchJobRecord:
        key = request.idempotency_key
        with self._lock:
            if key and key in self._idempotency:
                return self._jobs[self._idempotency[key]]
            now = _now_iso()
            job = ResearchJobRecord(
                job_id=f"research-{uuid.uuid4().hex[:12]}",
                task_id=_task_id(request),
                idempotency_key=key,
                status=ResearchTaskStatus.QUEUED,
                request=request,
                created_at=now,
                updated_at=now,
            )
            self._jobs[job.job_id] = job
            if key:
                self._idempotency[key] = job.job_id
            return job

    def submit(self, request: ResearchRequest, *, wait: bool = True) -> ResearchJobRecord:
        job = self.enqueue(request)
        if job.status != ResearchTaskStatus.QUEUED:
            return job
        if wait:
            return self.execute(job.job_id)
        worker = threading.Thread(
            target=self.execute,
            args=(job.job_id,),
            name=f"research-job:{job.job_id}",
            daemon=True,
        )
        worker.start()
        return self.get(job.job_id) or job

    def execute(self, job_id: str) -> ResearchJobRecord:
        with self._lock:
            job = self._jobs[job_id]
            if job.status == ResearchTaskStatus.CANCELLED:
                return job
            job.status = ResearchTaskStatus.RUNNING
            job.updated_at = _now_iso()
        result = self._orchestrator.run(job.request)
        with self._lock:
            job.result = result
            if job.status != ResearchTaskStatus.CANCELLED:
                job.status = result.status
            job.updated_at = _now_iso()
            return job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in {
                ResearchTaskStatus.SUCCEEDED,
                ResearchTaskStatus.PARTIAL,
                ResearchTaskStatus.FAILED,
                ResearchTaskStatus.CANCELLED,
                ResearchTaskStatus.TIMED_OUT,
            }:
                return False
            job.status = ResearchTaskStatus.CANCELLED
            job.updated_at = _now_iso()
            task_id = job.task_id
        self._orchestrator.cancel(task_id)
        return True

    def get(self, job_id: str) -> Optional[ResearchJobRecord]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> List[ResearchJobRecord]:
        with self._lock:
            return list(self._jobs.values())


_SERVICE: Optional[ResearchJobService] = None
_SERVICE_LOCK = threading.Lock()


def get_research_job_service(
    providers: Optional[Sequence[ResearchProvider]] = None,
) -> ResearchJobService:
    global _SERVICE
    if providers is not None:
        return ResearchJobService(ResearchOrchestrator(list(providers)))
    with _SERVICE_LOCK:
        if _SERVICE is None:
            from src.agent.research_registry import build_scheduled_providers

            _SERVICE = ResearchJobService(ResearchOrchestrator(list(build_scheduled_providers())))
        return _SERVICE


def reset_research_job_service() -> None:
    global _SERVICE
    with _SERVICE_LOCK:
        _SERVICE = None


def build_stock_request(
    stock_code: str,
    *,
    as_of: str,
    authorization_context: str = "",
    idempotency_key: str = "",
    total_timeout_seconds: float = 120.0,
) -> ResearchRequest:
    request_id = f"sched-{stock_code}-{as_of}"
    return ResearchRequest(
        request_id=request_id,
        run_id=idempotency_key or request_id,
        subject=stock_code,
        market="",
        as_of=as_of,
        horizons=(Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG),
        authorization_context=authorization_context,
        total_timeout_seconds=total_timeout_seconds,
        idempotency_key=idempotency_key or request_id,
    )


def run_scheduled_research(
    stock_codes: Iterable[str],
    *,
    service: Optional[ResearchJobService] = None,
    as_of: Optional[str] = None,
    authorization_context: str = "",
) -> List[ResearchJobRecord]:
    day = as_of or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jobs = []
    job_service = service or get_research_job_service()
    for code in stock_codes:
        if not code:
            continue
        request = build_stock_request(
            code,
            as_of=day,
            authorization_context=authorization_context,
            idempotency_key=f"{code}:{day}",
        )
        jobs.append(job_service.submit(request, wait=True))
    return jobs


def maybe_run_scheduled_research(stock_codes: Optional[Sequence[str]]) -> List[ResearchJobRecord]:
    from src.agent.research_registry import research_schedule_enabled

    if not research_schedule_enabled() or not stock_codes:
        return []
    try:
        return run_scheduled_research(stock_codes)
    except Exception:
        logger.exception("scheduled research OS run failed")
        return []
