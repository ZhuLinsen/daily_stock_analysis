# -*- coding: utf-8 -*-
"""State-machine tests for the research job table and scheduler hook."""

from __future__ import annotations

import os
from dataclasses import replace

from src.agent.research_jobs import (
    ResearchJobService,
    build_stock_request,
    maybe_run_scheduled_research,
    public_decision,
    reset_research_job_service,
    run_scheduled_research,
    strip_order_fields,
)
from src.agent.research_orchestrator import ResearchOrchestrator, ResearchTaskStatus
from src.agent.research_registry import build_research_providers
from src.schemas.research_contracts import Horizon, ResearchRequest
from tests.research.mock_provider import MockResearchProvider
from tests.research.test_orchestrator import _OptionalFailProvider


def make_request(**overrides) -> ResearchRequest:
    base = ResearchRequest(
        request_id="job-req-001",
        run_id="job-run-001",
        subject="TEST",
        market="cn",
        as_of="2026-07-01",
        horizons=(Horizon.SHORT,),
        idempotency_key="job-key-1",
        total_timeout_seconds=2.0,
        provider_timeout_seconds=1.0,
    )
    return replace(base, **overrides)


class TestRegistry:
    def test_xiaolonglong_requires_grants(self) -> None:
        providers = build_research_providers(include_technical=True, include_xiaolonglong=True)
        ids = [p.provider_id for p in providers]
        assert "dsa-technical" in ids
        assert "xiaolonglong" not in ids

    def test_mock_is_test_only(self) -> None:
        providers = build_research_providers(include_mock=True, include_technical=False)
        assert [p.provider_id for p in providers] == ["mock"]


class TestJobStateMachine:
    def test_success_and_idempotency(self) -> None:
        service = ResearchJobService(ResearchOrchestrator([MockResearchProvider()]))
        first = service.submit(make_request())
        second = service.submit(make_request())
        assert first.job_id == second.job_id
        assert first.status == ResearchTaskStatus.SUCCEEDED
        public = first.to_public_dict()
        assert public["status"] == "succeeded"
        assert public["decision"]["short_term"]["stance"]
        assert "order" not in public
        assert "broker" not in public

    def test_cancel_queued_job(self) -> None:
        service = ResearchJobService(ResearchOrchestrator([MockResearchProvider()]))
        queued = service.enqueue(make_request(idempotency_key="queued"))
        assert queued.status == ResearchTaskStatus.QUEUED
        assert service.cancel(queued.job_id) is True
        current = service.get(queued.job_id)
        assert current is not None
        assert current.status == ResearchTaskStatus.CANCELLED
        executed = service.execute(queued.job_id)
        assert executed.status == ResearchTaskStatus.CANCELLED

    def test_cancel_running_slow_provider(self) -> None:
        slow = MockResearchProvider(delay_seconds=0.4)
        service = ResearchJobService(ResearchOrchestrator([slow]))
        job = service.submit(
            make_request(idempotency_key="slow", provider_timeout_seconds=2.0),
            wait=False,
        )
        slow.started_event.wait(timeout=1.0)
        assert service.cancel(job.job_id) is True
        # Wait for the worker to finish mapping the orchestrator result.
        for _ in range(50):
            current = service.get(job.job_id)
            if current and current.status != ResearchTaskStatus.RUNNING:
                break
            slow.started_event.wait(timeout=0.02)
        current = service.get(job.job_id)
        assert current is not None
        assert current.status in {
            ResearchTaskStatus.CANCELLED,
            ResearchTaskStatus.SUCCEEDED,
        }

    def test_timeout_status(self) -> None:
        slow = MockResearchProvider(delay_seconds=1.0)
        service = ResearchJobService(
            ResearchOrchestrator([slow], default_timeout_seconds=0.05)
        )
        job = service.submit(
            make_request(
                idempotency_key="timeout",
                provider_timeout_seconds=0.05,
                total_timeout_seconds=0.1,
            )
        )
        assert job.status == ResearchTaskStatus.TIMED_OUT

    def test_partial_status(self) -> None:
        service = ResearchJobService(
            ResearchOrchestrator([MockResearchProvider(), _OptionalFailProvider()])
        )
        job = service.submit(make_request(idempotency_key="partial"))
        assert job.status == ResearchTaskStatus.PARTIAL

    def test_public_payload_strips_order_fields(self) -> None:
        dirty = {"short_term": {"stance": "bullish"}, "order": {"qty": 1}, "broker": "x"}
        clean = strip_order_fields(dirty)
        assert "order" not in clean
        assert "broker" not in clean
        assert public_decision(None) is None


class TestScheduledEntry:
    def test_run_scheduled_research_is_idempotent_per_day(self) -> None:
        service = ResearchJobService(ResearchOrchestrator([MockResearchProvider()]))
        first = run_scheduled_research(["TEST"], service=service, as_of="2026-07-01")
        second = run_scheduled_research(["TEST"], service=service, as_of="2026-07-01")
        assert len(first) == 1
        assert first[0].job_id == second[0].job_id
        assert first[0].request.horizons == (Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG)

    def test_schedule_hook_off_by_default(self, monkeypatch) -> None:
        reset_research_job_service()
        monkeypatch.delenv("DSA_RESEARCH_OS_SCHEDULE", raising=False)
        assert maybe_run_scheduled_research(["TEST"]) == []

    def test_build_stock_request_has_deadline(self) -> None:
        request = build_stock_request("TEST", as_of="2026-07-01", total_timeout_seconds=30)
        assert request.total_timeout_seconds == 30
        assert request.idempotency_key == "TEST:2026-07-01" or request.idempotency_key == "sched-TEST-2026-07-01"
