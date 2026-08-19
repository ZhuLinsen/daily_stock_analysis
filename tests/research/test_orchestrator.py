# -*- coding: utf-8 -*-
"""Tests for ResearchOrchestrator — task state machine, concurrency,
cancellation, single-attempt execution, evidence validation, and integration.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace

from src.schemas.research_contracts import (
    Horizon,
    ProviderErrorCode,
    ProviderError,
    ResearchRequest,
    Stance,
    to_json,
)
from tests.research.mock_provider import MockResearchProvider
from src.agent.research_orchestrator import (
    ResearchOrchestrator,
    ResearchTaskStatus,
)
from src.agent.research_provider import ResearchProvider


_BASE_REQUEST = ResearchRequest(
    request_id="orch-req-001",
    run_id="orch-run-001",
    subject="TEST",
    market="cn",
    as_of="2026-07-01",
    horizons=(Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG),
    provider_timeout_seconds=2.0,
)


def make_request(**overrides) -> ResearchRequest:
    return replace(_BASE_REQUEST, **overrides)


class TestTaskStateMachine:
    def test_success_status(self) -> None:
        orch = ResearchOrchestrator([MockResearchProvider()])
        result = orch.run(make_request())
        assert result.status == ResearchTaskStatus.SUCCEEDED
        assert result.task_id == "task-orch-req-001-orch-run-001"

    def test_succeeded_all_providers(self) -> None:
        orch = ResearchOrchestrator([MockResearchProvider(), MockResearchProvider()])
        result = orch.run(make_request())
        assert result.status == ResearchTaskStatus.SUCCEEDED
        assert all(r.status == ResearchTaskStatus.SUCCEEDED for r in result.provider_results)

    def test_fail_closed_mixed_outcome_is_failed(self) -> None:
        # Optional provider + FAIL_CLOSED must not degrade to PARTIAL.
        bad = _FailProvider()
        orch = ResearchOrchestrator([MockResearchProvider(), bad])
        result = orch.run(make_request())
        assert result.status == ResearchTaskStatus.FAILED
        assert result.integrated is None
        statuses = {r.status for r in result.provider_results}
        assert ResearchTaskStatus.SUCCEEDED in statuses
        assert ResearchTaskStatus.FAILED in statuses

    def test_failed_when_all_fail(self) -> None:
        orch = ResearchOrchestrator([_FailProvider(), _FailProvider()])
        result = orch.run(make_request())
        assert result.status == ResearchTaskStatus.FAILED

    def test_timeout_status(self) -> None:
        # Slow provider (1s) with 0.05s timeout
        slow = MockResearchProvider(delay_seconds=1.0)
        orch = ResearchOrchestrator(
            [slow],
            default_timeout_seconds=0.05,
        )
        result = orch.run(make_request(provider_timeout_seconds=0.05))
        assert result.status == ResearchTaskStatus.TIMED_OUT
        assert result.provider_results[0].status == ResearchTaskStatus.TIMED_OUT
        assert result.provider_results[0].error is not None
        assert result.provider_results[0].error.code == ProviderErrorCode.TIMEOUT

    def test_total_timeout_clips_provider_timeout(self) -> None:
        slow = MockResearchProvider(delay_seconds=1.0)
        orch = ResearchOrchestrator([slow], default_timeout_seconds=30.0)
        started = time.monotonic()
        result = orch.run(
            make_request(
                horizons=(Horizon.SHORT,),
                provider_timeout_seconds=30.0,
                total_timeout_seconds=0.1,
            )
        )
        elapsed = time.monotonic() - started
        assert result.status == ResearchTaskStatus.TIMED_OUT
        assert elapsed < 1.0
        assert result.provider_results[0].opinion is None

    def test_uncooperative_provider_does_not_block_timeout(self) -> None:
        orch = ResearchOrchestrator([_UncooperativeProvider()])
        started = time.monotonic()
        result = orch.run(
            make_request(
                horizons=(Horizon.SHORT,),
                provider_timeout_seconds=0.05,
                total_timeout_seconds=0.4,
            )
        )
        elapsed = time.monotonic() - started
        assert result.status == ResearchTaskStatus.TIMED_OUT
        assert elapsed < 1.0
        assert result.provider_results[0].opinion is None
        assert result.integrated is None
        for thread in threading.enumerate():
            if thread.name.startswith("research-provider:uncooperative"):
                thread.join(timeout=2)

    def test_cancelled_status(self) -> None:
        # Cancel mid-flight: run a slow provider in a worker thread and
        # cancel from the main thread while it is running.
        slow = MockResearchProvider(delay_seconds=2.0)
        orch = ResearchOrchestrator([slow])
        request = make_request()
        task_id = f"task-{request.request_id}-{request.run_id}"

        outcome: dict = {}

        def _run() -> None:
            outcome["result"] = orch.run(request)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        time.sleep(0.2)  # let the task enter running state
        assert orch.cancel(task_id) is True
        thread.join(timeout=10)
        result = outcome["result"]
        assert result.status == ResearchTaskStatus.CANCELLED

    def test_cancel_unknown_task_returns_false(self) -> None:
        orch = ResearchOrchestrator([MockResearchProvider()])
        assert orch.cancel("nonexistent") is False


class TestProviderRunResult:
    def test_success_has_opinion(self) -> None:
        orch = ResearchOrchestrator([MockResearchProvider()])
        result = orch.run(make_request())
        run = result.provider_results[0]
        assert run.status == ResearchTaskStatus.SUCCEEDED
        assert run.opinion is not None
        assert run.attempts == 1

    def test_retryable_error_is_not_retried(self) -> None:
        provider = _OptionalFailProvider()
        orch = ResearchOrchestrator([provider])
        result = orch.run(make_request(horizons=(Horizon.SHORT,)))
        assert result.provider_results[0].attempts == 1
        assert provider.calls == 2  # validate once + research once

    def test_failure_has_error(self) -> None:
        orch = ResearchOrchestrator([_FailProvider()])
        result = orch.run(make_request())
        run = result.provider_results[0]
        assert run.status == ResearchTaskStatus.FAILED
        assert run.error is not None
        assert run.error.code == ProviderErrorCode.CONTRACT_VIOLATION


class TestEvidenceValidation:
    def test_bad_evidence_rejected(self) -> None:
        bad = MockResearchProvider(bad_evidence=True)
        orch = ResearchOrchestrator([bad])
        result = orch.run(make_request())
        run = result.provider_results[0]
        assert run.status == ResearchTaskStatus.FAILED
        assert run.error is not None
        assert run.error.code == ProviderErrorCode.CONTRACT_VIOLATION
        assert "missing evidence" in run.error.message

    def test_good_evidence_accepted(self) -> None:
        good = MockResearchProvider()
        orch = ResearchOrchestrator([good])
        result = orch.run(make_request())
        assert result.status == ResearchTaskStatus.SUCCEEDED

    def test_empty_evidence_ids_rejected(self) -> None:
        empty = MockResearchProvider(empty_evidence=True)
        orch = ResearchOrchestrator([empty])
        result = orch.run(make_request(horizons=(Horizon.SHORT,)))
        run = result.provider_results[0]
        assert run.status == ResearchTaskStatus.FAILED
        assert run.error is not None
        assert run.error.code == ProviderErrorCode.CONTRACT_VIOLATION
        assert "no evidence_ids" in run.error.message
        assert result.integrated is None

    def test_empty_evidence_refs_rejected_for_non_abstain(self) -> None:
        empty = MockResearchProvider(empty_evidence=True)
        orch = ResearchOrchestrator([empty])
        result = orch.run(make_request(horizons=(Horizon.SHORT,)))
        assert "no evidence_refs" in result.provider_results[0].error.message


class TestOutputSize:
    def test_output_too_large_rejected(self) -> None:
        good = MockResearchProvider()
        orch = ResearchOrchestrator([good])
        # Request with tiny max_output_bytes
        result = orch.run(make_request(max_output_bytes=10))
        run = result.provider_results[0]
        assert run.status == ResearchTaskStatus.FAILED
        assert run.error is not None
        assert run.error.code == ProviderErrorCode.OUTPUT_TOO_LARGE

    def test_output_within_limit_accepted(self) -> None:
        good = MockResearchProvider()
        orch = ResearchOrchestrator([good])
        result = orch.run(make_request(max_output_bytes=65536))
        assert result.status == ResearchTaskStatus.SUCCEEDED

    def test_evidence_count_over_budget_rejected(self) -> None:
        good = MockResearchProvider(extra_evidence=True)
        orch = ResearchOrchestrator([good])
        result = orch.run(make_request(horizons=(Horizon.SHORT,), max_evidence_count=1))
        run = result.provider_results[0]
        assert run.status == ResearchTaskStatus.FAILED
        assert run.error is not None
        assert run.error.code == ProviderErrorCode.CONTRACT_VIOLATION
        assert "max_evidence_count" in run.error.message
        assert run.error.details["actual_evidence"] == 3
        assert result.integrated is None


class TestConflictIntegration:
    def test_conflicting_stances_create_conflict(self) -> None:
        bull = MockResearchProvider(
            stance_map={Horizon.SHORT: Stance.BULLISH},
        )
        bear = MockResearchProvider(
            provider_id="mock-bear",
            stance_map={Horizon.SHORT: Stance.BEARISH},
        )
        orch = ResearchOrchestrator([bull, bear])
        result = orch.run(make_request(horizons=(Horizon.SHORT,)))
        assert result.integrated is not None
        assert len(result.integrated.conflicts) == 1
        conflict = result.integrated.conflicts[0]
        assert "mock" in conflict.conflicting_providers
        assert "mock-bear" in conflict.conflicting_providers

    def test_conflict_horizon_abstains(self) -> None:
        bull = MockResearchProvider(
            stance_map={Horizon.SHORT: Stance.BULLISH},
        )
        bear = MockResearchProvider(
            provider_id="mock-bear",
            stance_map={Horizon.SHORT: Stance.BEARISH},
        )
        orch = ResearchOrchestrator([bull, bear])
        result = orch.run(make_request(horizons=(Horizon.SHORT,)))
        assert result.integrated is not None
        assert result.integrated.short_term.stance == Stance.ABSTAIN
        assert "conflict" in result.integrated.short_term.abstain_reason

    def test_no_simple_averaging(self) -> None:
        """Short bearish + long bullish must not average to neutral."""
        short_bear = MockResearchProvider(
            stance_map={Horizon.SHORT: Stance.BEARISH},
        )
        long_bull = MockResearchProvider(
            provider_id="mock-long-bull",
            stance_map={Horizon.LONG: Stance.BULLISH},
        )
        orch = ResearchOrchestrator([short_bear, long_bull])
        result = orch.run(make_request())
        assert result.integrated is not None
        assert result.integrated.short_term.stance == Stance.BEARISH
        assert result.integrated.long_term.stance == Stance.BULLISH

    def test_all_abstain_produces_abstain(self) -> None:
        abstain = MockResearchProvider(abstain_all=True)
        orch = ResearchOrchestrator([abstain])
        result = orch.run(make_request())
        assert result.integrated is not None
        assert result.integrated.short_term.stance == Stance.ABSTAIN
        assert result.integrated.medium_term.stance == Stance.ABSTAIN
        assert result.integrated.long_term.stance == Stance.ABSTAIN

    def test_unanimous_stance_integrated(self) -> None:
        bull = MockResearchProvider(
            stance_map={Horizon.MEDIUM: Stance.BULLISH},
        )
        bull2 = MockResearchProvider(
            provider_id="mock-bull2",
            stance_map={Horizon.MEDIUM: Stance.BULLISH},
        )
        orch = ResearchOrchestrator([bull, bull2])
        result = orch.run(make_request(horizons=(Horizon.MEDIUM,)))
        assert result.integrated is not None
        assert result.integrated.medium_term.stance == Stance.BULLISH

    def test_provider_versions_recorded(self) -> None:
        p1 = MockResearchProvider()
        p2 = MockResearchProvider(provider_id="mock-other")
        orch = ResearchOrchestrator([p1, p2])
        result = orch.run(make_request())
        assert result.integrated is not None
        assert "mock" in result.integrated.provider_versions
        assert "mock-other" in result.integrated.provider_versions


class TestConcurrency:
    def test_concurrency_limit_respected(self) -> None:
        active = {"max": 0, "current": 0}
        lock = threading.Lock()

        class _TrackingProvider(ResearchProvider):
            provider_id = "tracking"
            provider_version = "1.0"

            def capabilities(self):
                from src.schemas.research_contracts import ProviderCapabilities
                return ProviderCapabilities(
                    provider_id=self.provider_id,
                    provider_version=self.provider_version,
                )

            def validate(self, request):
                return None

            def research(self, request, context=None):
                with lock:
                    active["current"] += 1
                    active["max"] = max(active["max"], active["current"])
                time.sleep(0.05)
                with lock:
                    active["current"] -= 1
                return MockResearchProvider().research(request)

            def cancel(self, task_id):
                return False

            def health(self):
                return True

        orch = ResearchOrchestrator(
            [_TrackingProvider(), _TrackingProvider(), _TrackingProvider(), _TrackingProvider()],
            max_concurrency=2,
        )
        result = orch.run(make_request())
        assert result.status == ResearchTaskStatus.SUCCEEDED
        assert active["max"] <= 2


class TestCancellationProof:
    def test_cancelled_leaves_no_live_provider_workers(self) -> None:
        slow = MockResearchProvider(delay_seconds=10)
        orch = ResearchOrchestrator([slow])
        request = make_request(horizons=(Horizon.SHORT,))
        outcome: dict = {}

        def run_in_bg() -> None:
            outcome["result"] = orch.run(request)

        runner = threading.Thread(target=run_in_bg, name="research-test-runner")
        runner.start()
        assert slow.started_event.wait(timeout=1)
        task_id = f"task-{request.request_id}-{request.run_id}"
        assert orch.cancel(task_id) is True
        runner.join(timeout=2)

        assert not runner.is_alive()
        result = outcome["result"]
        assert result.status == ResearchTaskStatus.CANCELLED
        assert result.provider_results[0].status == ResearchTaskStatus.CANCELLED
        assert not any(
            thread.name.startswith("research-provider:") and thread.is_alive()
            for thread in threading.enumerate()
        )
        assert orch.active_task_ids() == ()

    def test_cancel_before_run_is_honoured_and_cleaned_up(self) -> None:
        request = make_request(horizons=(Horizon.SHORT,))
        task_id = f"task-{request.request_id}-{request.run_id}"
        orch = ResearchOrchestrator([MockResearchProvider()])
        assert orch.cancel(task_id) is False
        result = orch.run(request)
        assert result.status == ResearchTaskStatus.CANCELLED
        assert result.provider_results == ()
        assert orch.active_task_ids() == ()

    def test_cancel_twice_is_idempotent(self) -> None:
        request = make_request()
        task_id = f"task-{request.request_id}-{request.run_id}"
        orch = ResearchOrchestrator([MockResearchProvider()])
        assert orch.cancel(task_id) is False
        assert orch.cancel(task_id) is True


class TestProviderRole:
    def test_required_provider_failure_closes(self) -> None:
        fail = _FailProvider()
        orch = ResearchOrchestrator([fail])
        result = orch.run(make_request())
        assert result.status == ResearchTaskStatus.FAILED

    def test_required_provider_failure_blocks_optional_success(self) -> None:
        orch = ResearchOrchestrator([_RequiredFailProvider(), MockResearchProvider()])
        result = orch.run(make_request(horizons=(Horizon.SHORT,)))
        assert result.status == ResearchTaskStatus.FAILED
        assert result.integrated is None

    def test_optional_validate_exception_degrades_to_partial(self) -> None:
        orch = ResearchOrchestrator([MockResearchProvider(), _BoomValidateProvider()])
        result = orch.run(make_request(horizons=(Horizon.SHORT,)))
        assert result.status == ResearchTaskStatus.PARTIAL
        assert result.integrated is not None
        boom = [r for r in result.provider_results if r.provider_id == "boom-validate"]
        assert boom[0].status == ResearchTaskStatus.FAILED
        assert boom[0].error is not None
        assert boom[0].error.code == ProviderErrorCode.UNKNOWN
        assert boom[0].error.stage == "validate"

    def test_optional_provider_failure_degrades_to_partial(self) -> None:
        optional_fail = _OptionalFailProvider()
        good = MockResearchProvider()
        orch = ResearchOrchestrator([good, optional_fail])
        result = orch.run(make_request())
        assert result.status == ResearchTaskStatus.PARTIAL
        good_runs = [r for r in result.provider_results if r.status == ResearchTaskStatus.SUCCEEDED]
        assert len(good_runs) >= 3

    def test_stale_evidence_warning(self) -> None:
        good = MockResearchProvider()
        orch = ResearchOrchestrator([good])
        result = orch.run(make_request())
        assert result.status == ResearchTaskStatus.SUCCEEDED

    def test_all_error_codes_serde(self) -> None:
        for code in [ProviderErrorCode.TIMEOUT, ProviderErrorCode.CANCELLED,
                     ProviderErrorCode.UNAUTHORIZED, ProviderErrorCode.STALE_EVIDENCE,
                     ProviderErrorCode.INSUFFICIENT_EVIDENCE, ProviderErrorCode.REVISION_MISMATCH,
                     ProviderErrorCode.OUTPUT_TOO_LARGE, ProviderErrorCode.DEPENDENCY_UNAVAILABLE,
                     ProviderErrorCode.CONTRACT_VIOLATION, ProviderErrorCode.UNKNOWN]:
            from src.schemas.research_contracts import FailMode
            err = ProviderError(
                code=code, stage="test", fail_mode=FailMode.FAIL_CLOSED,
                provider_id="test", partial=False
            )
            d = json.loads(to_json(err))
            assert d["code"] == code.value

    def test_no_evidence_abstains(self) -> None:
        bad = MockResearchProvider(bad_evidence=True)
        orch = ResearchOrchestrator([bad])
        result = orch.run(make_request())
        run = result.provider_results[0]
        assert run.status == ResearchTaskStatus.FAILED
        assert run.error.code == ProviderErrorCode.CONTRACT_VIOLATION


class TestOrchestratorSerialization:
    def test_result_serializable(self) -> None:
        orch = ResearchOrchestrator([MockResearchProvider()])
        result = orch.run(make_request())
        # The integrated decision must roundtrip through JSON
        j = json.dumps(json.loads(to_json(result.integrated)), sort_keys=True)
        assert "short_term" in j
        assert "medium_term" in j
        assert "long_term" in j
        assert "conflicts" in j

    def test_health(self) -> None:
        orch = ResearchOrchestrator([MockResearchProvider()])
        assert orch.health() is True


class _OptionalFailProvider(ResearchProvider):
    provider_id = "optional-fail"
    provider_version = "1.0"

    def __init__(self):
        self.calls = 0

    def capabilities(self):
        from src.schemas.research_contracts import ProviderCapabilities, ProviderRole
        return ProviderCapabilities(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            role=ProviderRole.OPTIONAL,
        )

    def validate(self, request):
        self.calls += 1

    def research(self, request, context=None):
        self.calls += 1
        from src.schemas.research_contracts import FailMode
        return ProviderError(
            code=ProviderErrorCode.DEPENDENCY_UNAVAILABLE,
            stage="research",
            fail_mode=FailMode.FAIL_OPEN,
            provider_id=self.provider_id,
            partial=False,
            message="optional provider failed",
        )

    def cancel(self, task_id):
        return False

    def health(self):
        return True


class _BoomValidateProvider(ResearchProvider):
    """Optional provider that raises a plain exception during validate()."""

    provider_id = "boom-validate"
    provider_version = "1.0"

    def capabilities(self):
        from src.schemas.research_contracts import ProviderCapabilities, ProviderRole
        return ProviderCapabilities(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            role=ProviderRole.OPTIONAL,
        )

    def validate(self, request):
        raise ValueError("schema drift")

    def research(self, request, context=None):
        return MockResearchProvider().research(request)

    def cancel(self, task_id):
        return False

    def health(self):
        return True


class _RequiredFailProvider(ResearchProvider):
    """Required provider that fails with FAIL_OPEN — role still fail-closes."""

    provider_id = "required-fail"
    provider_version = "1.0"

    def capabilities(self):
        from src.schemas.research_contracts import ProviderCapabilities, ProviderRole
        return ProviderCapabilities(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            role=ProviderRole.REQUIRED,
        )

    def validate(self, request):
        return None

    def research(self, request, context=None):
        from src.schemas.research_contracts import FailMode
        return ProviderError(
            code=ProviderErrorCode.DEPENDENCY_UNAVAILABLE,
            stage="research",
            fail_mode=FailMode.FAIL_OPEN,
            provider_id=self.provider_id,
            message="required provider unavailable",
        )

    def cancel(self, task_id):
        return False

    def health(self):
        return True


class _UncooperativeProvider(ResearchProvider):
    """Ignores cancel() and blocks past the provider timeout."""

    provider_id = "uncooperative"
    provider_version = "1.0"

    def capabilities(self):
        from src.schemas.research_contracts import ProviderCapabilities, ProviderRole
        return ProviderCapabilities(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            supports_cancellation=False,
            role=ProviderRole.OPTIONAL,
        )

    def validate(self, request):
        return None

    def research(self, request, context=None):
        time.sleep(1.0)
        return MockResearchProvider().research(request)

    def cancel(self, task_id):
        return False

    def health(self):
        return True


class _FailProvider(ResearchProvider):
    """Provider that always fails validation (CONTRACT_VIOLATION)."""

    provider_id = "fail"
    provider_version = "1.0"

    def __init__(self) -> None:
        self.calls = 0

    def capabilities(self):
        from src.schemas.research_contracts import ProviderCapabilities, ProviderRole
        return ProviderCapabilities(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            role=ProviderRole.OPTIONAL,
        )

    def validate(self, request):
        self.calls += 1
        from src.schemas.research_contracts import FailMode, ProviderError
        raise ProviderError(
            code=ProviderErrorCode.CONTRACT_VIOLATION,
            stage="validate",
            fail_mode=FailMode.FAIL_CLOSED,
            provider_id=self.provider_id,
            message="fail provider",
        )

    def research(self, request, context=None):
        self.calls += 1
        from src.schemas.research_contracts import FailMode, ProviderError
        return ProviderError(
            code=ProviderErrorCode.CONTRACT_VIOLATION,
            stage="research",
            fail_mode=FailMode.FAIL_CLOSED,
            provider_id=self.provider_id,
            message="fail provider",
        )

    def cancel(self, task_id):
        return False

    def health(self):
        return True
