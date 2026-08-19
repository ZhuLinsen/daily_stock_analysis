# -*- coding: utf-8 -*-
"""Test fixtures for DSA Research OS — human-made, sanitized, deterministic."""

from __future__ import annotations

from src.schemas.research_contracts import (
    EvidenceFreshness,
    EvidenceRef,
    Horizon,
    ResearchRequest,
    SensitiveLevel,
)


def make_valid_request(**overrides) -> ResearchRequest:
    """Build a valid ResearchRequest with deterministic defaults."""
    request = ResearchRequest(
        request_id="fixture-req-001",
        run_id="fixture-run-001",
        subject="TEST",
        market="cn",
        as_of="2026-07-01",
        horizons=(Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG),
    )
    for key, value in overrides.items():
        if hasattr(request, key):
            object.__setattr__(request, key, value)
    return request


def make_sanitized_evidence() -> EvidenceRef:
    """A single human-made evidence fixture with no real data."""
    return EvidenceRef(
        evidence_id="fixture-evidence-001",
        source_type="file",
        source_uri="internal://fixtures/sanitized",
        title="Sanitized fixture evidence",
        publisher="DSA Test Fixtures",
        published_at="2026-07-01T00:00:00Z",
        observed_at="2026-07-01T00:00:00Z",
        as_of="2026-07-01",
        authorization="internal",
        sensitive_level=SensitiveLevel.INTERNAL,
        license="test-fixture-only",
        freshness=EvidenceFreshness.FRESH,
        claim_ids=("fixture-claim-001",),
        locator="fixtures://evidence/001",
    )
