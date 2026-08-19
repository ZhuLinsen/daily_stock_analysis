# -*- coding: utf-8 -*-
"""DSA Research OS — MockResearchProvider for deterministic testing.

Returns hand-crafted, sanitized opinions for any valid request.
All data is fabricated; no network calls.  Fails on invalid requests
(fail-closed for contract violations).

Scenarios (constructor options, test-only):
- ``delay_seconds``: simulate slow providers (timeout tests)
- ``stance_map``: override per-horizon stance (conflict tests)
- ``abstain_all``: force abstain opinions (abstain tests)
- ``bad_evidence``: emit claims referencing missing evidence (validation tests)
- ``empty_evidence``: emit a non-abstain opinion with empty evidence lists
- ``extra_evidence``: attach all mock evidence refs to one opinion (budget tests)
"""

from __future__ import annotations

import threading
from typing import Dict, Optional, Tuple

from src.schemas.research_contracts import (
    Claim,
    ClaimKind,
    EvidenceFreshness,
    EvidenceRef,
    FailMode,
    FrameworkOpinion,
    Horizon,
    ProviderCapabilities,
    ProviderErrorCode,
    ProviderError,
    ProviderRole,
    ResearchRequest,
    SensitiveLevel,
    Stance,
)
from src.agent.research_provider import ResearchProvider


_MOCK_VERSION = "0.2.0"
_MOCK_PROVIDER_ID = "mock"

# Human-made, sanitized evidence templates — no real company data
_MOCK_EVIDENCE = (
    EvidenceRef(
        evidence_id="mock-tech-001",
        source_type="database",
        source_uri="internal://mock/technical-indicators",
        title="Mock technical indicator snapshot",
        publisher="DSA Mock Engine",
        published_at="2026-07-01T00:00:00Z",
        observed_at="2026-07-01T00:00:00Z",
        as_of="2026-07-01",
        authorization="internal",
        sensitive_level=SensitiveLevel.INTERNAL,
        license="internal-use-only",
        freshness=EvidenceFreshness.FRESH,
        claim_ids=("mock-claim-short",),
        locator="mock://tech-indicators/snapshot",
    ),
    EvidenceRef(
        evidence_id="mock-fund-001",
        source_type="file",
        source_uri="internal://mock/fundamentals",
        title="Mock fundamental data snapshot",
        publisher="DSA Mock Engine",
        published_at="2026-06-30T00:00:00Z",
        observed_at="2026-07-01T00:00:00Z",
        as_of="2026-07-01",
        authorization="internal",
        sensitive_level=SensitiveLevel.INTERNAL,
        license="internal-use-only",
        freshness=EvidenceFreshness.FRESH,
        claim_ids=("mock-claim-mid",),
        locator="mock://fundamentals/snapshot",
    ),
    EvidenceRef(
        evidence_id="mock-thesis-001",
        source_type="file",
        source_uri="internal://mock/thesis",
        title="Mock long-term thesis document",
        publisher="DSA Mock Engine",
        published_at="2026-06-15T00:00:00Z",
        observed_at="2026-07-01T00:00:00Z",
        as_of="2026-07-01",
        authorization="internal",
        sensitive_level=SensitiveLevel.INTERNAL,
        license="internal-use-only",
        freshness=EvidenceFreshness.FRESH,
        claim_ids=("mock-claim-long",),
        locator="mock://thesis/document",
    ),
)


class MockResearchProvider(ResearchProvider):
    """Deterministic mock provider for contract testing.

    Returns a structured opinion based on the request subject and horizon.
    Fails immediately on invalid requests (fail-closed).
    """

    def __init__(
        self,
        *,
        provider_id: str = _MOCK_PROVIDER_ID,
        delay_seconds: float = 0.0,
        stance_map: Optional[Dict[Horizon, Stance]] = None,
        abstain_all: bool = False,
        bad_evidence: bool = False,
        empty_evidence: bool = False,
        extra_evidence: bool = False,
    ) -> None:
        self._provider_id = provider_id
        self._delay_seconds = max(0.0, delay_seconds)
        self._stance_map = stance_map or {
            Horizon.SHORT: Stance.NEUTRAL,
            Horizon.MEDIUM: Stance.BULLISH,
            Horizon.LONG: Stance.BULLISH,
        }
        self._abstain_all = abstain_all
        self._bad_evidence = bad_evidence
        self._empty_evidence = empty_evidence
        self._extra_evidence = extra_evidence
        self.started_event = threading.Event()
        self._cancel_event = threading.Event()

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def provider_version(self) -> str:
        return _MOCK_VERSION

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self._provider_id,
            provider_version=_MOCK_VERSION,
            supported_markets=("cn", "hk", "us", "jp", "kr"),
            supported_horizons=(Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG),
            supported_evidence_types=("technical", "fundamental", "thesis"),
            supports_sync=True,
            supports_background=False,
            supports_cancellation=True,
            max_output_bytes=65536,
            reproducibility_level="deterministic",
            role=ProviderRole.REQUIRED,
        )

    def validate(self, request: ResearchRequest) -> None:
        if not request.request_id:
            raise ProviderError(
                code=ProviderErrorCode.CONTRACT_VIOLATION,
                stage="validate",
                fail_mode=FailMode.FAIL_CLOSED,
                provider_id=self._provider_id,
                provider_version=_MOCK_VERSION,
                message="request_id is required",
            )
        if not request.subject:
            raise ProviderError(
                code=ProviderErrorCode.CONTRACT_VIOLATION,
                stage="validate",
                fail_mode=FailMode.FAIL_CLOSED,
                provider_id=self._provider_id,
                provider_version=_MOCK_VERSION,
                message="subject is required",
            )

    def research(
        self,
        request: ResearchRequest,
        context: Optional[Dict] = None,
    ) -> FrameworkOpinion | ProviderError:
        try:
            self.validate(request)
        except ProviderError as exc:
            return exc

        self.started_event.set()
        if self._delay_seconds > 0 and self._cancel_event.wait(self._delay_seconds):
            return ProviderError(
                request_id=request.request_id,
                run_id=request.run_id,
                code=ProviderErrorCode.CANCELLED,
                stage="research",
                fail_mode=FailMode.FAIL_CLOSED,
                provider_id=self._provider_id,
                provider_version=_MOCK_VERSION,
                message="mock research cancelled",
            )

        horizon = request.horizons[0] if request.horizons else Horizon.SHORT

        stance = (
            Stance.ABSTAIN
            if self._abstain_all
            else self._stance_map.get(horizon, Stance.ABSTAIN)
        )

        claims: Tuple[Claim, ...]
        evidence_refs: Tuple[EvidenceRef, ...]
        if self._abstain_all:
            claims = ()
            evidence_refs = ()
        elif self._empty_evidence:
            claims = (
                Claim(
                    claim_id=f"mock-claim-{horizon.value}",
                    claim_kind=ClaimKind.OPINION,
                    text=f"Unsupported {stance.value} claim for {request.subject}",
                    evidence_ids=(),
                    confidence=0.7,
                ),
            )
            evidence_refs = ()
        else:
            evidence = _MOCK_EVIDENCE[0] if horizon == Horizon.SHORT else (
                _MOCK_EVIDENCE[1] if horizon == Horizon.MEDIUM else _MOCK_EVIDENCE[2]
            )
            claim_texts = {
                Horizon.SHORT: f"Mock technical analysis for {request.subject}: {stance.value} in short term",
                Horizon.MEDIUM: f"Mock fundamental inference for {request.subject}: {stance.value}",
                Horizon.LONG: f"Mock long-term thesis for {request.subject}: {stance.value}",
            }
            claim_kinds = {
                Horizon.SHORT: ClaimKind.FACT,
                Horizon.MEDIUM: ClaimKind.INFERENCE,
                Horizon.LONG: ClaimKind.OPINION,
            }
            evidence_id = evidence.evidence_id
            if self._bad_evidence:
                evidence_id = "missing-evidence-ref"
            claims = (
                Claim(
                    claim_id=f"mock-claim-{horizon.value}",
                    claim_kind=claim_kinds[horizon],
                    text=claim_texts[horizon],
                    evidence_ids=(evidence_id,),
                    dependent_fact_ids=(
                        ("mock-claim-short",) if horizon == Horizon.MEDIUM else ()
                    ),
                    confidence=0.7,
                ),
            )
            evidence_refs = _MOCK_EVIDENCE if self._extra_evidence else (evidence,)

        return FrameworkOpinion(
            request_id=request.request_id,
            run_id=request.run_id,
            provider_id=self._provider_id,
            provider_version=_MOCK_VERSION,
            framework="mock",
            framework_version=_MOCK_VERSION,
            as_of=request.as_of,
            horizon=horizon,
            stance=stance,
            confidence=0.7 if not self._abstain_all else 0.0,
            data_quality=0.8,
            claims=claims,
            evidence_refs=evidence_refs,
            risks=("Mock risk: data is fabricated",),
            assumptions=("Mock assumption: deterministic engine",),
            counterarguments=("Mock counterargument: not real research",),
            gaps=("Mock gap: no network data",),
            data_cutoff=request.as_of,
            warnings=("This is mock data for testing only",),
            invalidation_conditions=("Subject company delisted",),
        )

    def cancel(self, task_id: str) -> bool:
        self._cancel_event.set()
        return True

    def health(self) -> bool:
        return True
