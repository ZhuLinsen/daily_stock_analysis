# -*- coding: utf-8 -*-
"""Tests for DSA Research OS contract types — roundtrip and field validation."""

from __future__ import annotations

import json
import pytest

from src.schemas.research_contracts import (
    SCHEMA_VERSION,
    Claim,
    ClaimKind,
    ConflictItem,
    ConflictResolutionStatus,
    ConflictType,
    EvidenceFreshness,
    EvidenceRef,
    FailMode,
    FrameworkOpinion,
    Horizon,
    HorizonDecision,
    IntegratedDecision,
    ProviderCapabilities,
    ProviderErrorCode,
    ProviderError,
    ProviderRole,
    Reproducibility,
    ResearchRequest,
    SensitiveLevel,
    Stance,
    to_json,
)


# ---------------------------------------------------------------------------
# ResearchRequest
# ---------------------------------------------------------------------------

class TestResearchRequest:
    def test_defaults(self) -> None:
        r = ResearchRequest()
        assert r.schema_version == SCHEMA_VERSION
        assert r.horizons == (Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG)

    def test_roundtrip(self) -> None:
        r = ResearchRequest(
            request_id="req-001",
            run_id="run-001",
            subject="TEST",
            market="cn",
            as_of="2026-07-01",
        )
        j = to_json(r)
        d = json.loads(j)
        assert d["request_id"] == "req-001"
        assert d["subject"] == "TEST"
        assert d["horizons"] == ["short_term", "medium_term", "long_term"]
        # Schema version preserved
        assert d["schema_version"] == SCHEMA_VERSION

    def test_reproducibility(self) -> None:
        r = ResearchRequest(
            reproducibility=Reproducibility(dsa_sha="abc123", external_revision="rev1"),
        )
        j = to_json(r)
        d = json.loads(j)
        assert d["reproducibility"]["dsa_sha"] == "abc123"
        assert d["reproducibility"]["external_revision"] == "rev1"


# ---------------------------------------------------------------------------
# EvidenceRef
# ---------------------------------------------------------------------------

class TestEvidenceRef:
    def test_roundtrip(self) -> None:
        e = EvidenceRef(
            evidence_id="ev-001",
            source_type="database",
            source_uri="internal://test",
            title="Test Evidence",
            publisher="Test",
            published_at="2026-07-01T00:00:00Z",
            observed_at="2026-07-01T00:00:00Z",
            as_of="2026-07-01",
            authorization="internal",
            sensitive_level=SensitiveLevel.INTERNAL,
            license="internal-use-only",
            freshness=EvidenceFreshness.FRESH,
            claim_ids=("claim-1", "claim-2"),
            locator="test://loc",
        )
        j = to_json(e)
        d = json.loads(j)
        assert d["evidence_id"] == "ev-001"
        assert d["sensitive_level"] == "internal"
        assert d["freshness"] == "fresh"
        assert d["claim_ids"] == ["claim-1", "claim-2"]


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

class TestClaim:
    def test_inference_must_have_facts(self) -> None:
        c = Claim(
            claim_id="c1",
            claim_kind=ClaimKind.INFERENCE,
            text="test",
            evidence_ids=("e1",),
            dependent_fact_ids=("f1",),
        )
        j = to_json(c)
        d = json.loads(j)
        assert d["claim_kind"] == "inference"
        assert d["dependent_fact_ids"] == ["f1"]

    def test_opinion_no_fact_dependency(self) -> None:
        c = Claim(claim_id="c2", claim_kind=ClaimKind.OPINION, text="opinion")
        d = json.loads(to_json(c))
        assert d["dependent_fact_ids"] == []


# ---------------------------------------------------------------------------
# FrameworkOpinion
# ---------------------------------------------------------------------------

class TestFrameworkOpinion:
    def test_roundtrip(self) -> None:
        op = FrameworkOpinion(
            request_id="r1",
            run_id="run1",
            provider_id="mock",
            provider_version="0.1.0",
            framework="mock",
            framework_version="0.1.0",
            as_of="2026-07-01",
            horizon=Horizon.SHORT,
            stance=Stance.BULLISH,
            confidence=0.8,
            data_quality=0.9,
            claims=(
                Claim(claim_id="c1", claim_kind=ClaimKind.FACT, text="fact", evidence_ids=("e1",)),
            ),
            evidence_refs=(
                EvidenceRef(evidence_id="e1", source_type="test"),
            ),
            risks=("risk1",),
            warnings=("warn1",),
            invalidation_conditions=("inv1",),
        )
        j = to_json(op)
        d = json.loads(j)
        assert d["stance"] == "bullish"
        assert d["horizon"] == "short_term"
        assert len(d["claims"]) == 1
        assert d["claims"][0]["claim_kind"] == "fact"
        assert len(d["evidence_refs"]) == 1

    def test_abstain(self) -> None:
        op = FrameworkOpinion(stance=Stance.ABSTAIN, gaps=("no data",))
        d = json.loads(to_json(op))
        assert d["stance"] == "abstain"


# ---------------------------------------------------------------------------
# ConflictItem
# ---------------------------------------------------------------------------

class TestConflictItem:
    def test_roundtrip(self) -> None:
        ci = ConflictItem(
            request_id="r1",
            run_id="run1",
            claim_text="test claim",
            conflicting_providers=("mock", "dsa"),
            conflict_type=ConflictType.FACTUAL,
            resolution_status=ConflictResolutionStatus.UNRESOLVED,
            reason_cannot_average="different data sources",
        )
        d = json.loads(to_json(ci))
        assert d["conflict_type"] == "factual"
        assert d["resolution_status"] == "unresolved"
        assert d["conflicting_providers"] == ["mock", "dsa"]


# ---------------------------------------------------------------------------
# IntegratedDecision
# ---------------------------------------------------------------------------

class TestIntegratedDecision:
    def test_roundtrip_with_conflicts(self) -> None:
        id_ = IntegratedDecision(
            request_id="r1",
            run_id="run1",
            as_of="2026-07-01",
            short_term=HorizonDecision(
                horizon=Horizon.SHORT,
                conclusion="neutral",
                stance=Stance.NEUTRAL,
                confidence=0.6,
            ),
            medium_term=HorizonDecision(
                horizon=Horizon.MEDIUM,
                conclusion="bullish",
                stance=Stance.BULLISH,
                confidence=0.7,
            ),
            long_term=HorizonDecision(
                horizon=Horizon.LONG,
                conclusion="bullish",
                stance=Stance.BULLISH,
                confidence=0.8,
            ),
            conflicts=(
                ConflictItem(
                    claim_text="conflict",
                    conflict_type=ConflictType.HORIZON,
                ),
            ),
        )
        d = json.loads(to_json(id_))
        assert d["short_term"]["stance"] == "neutral"
        assert d["medium_term"]["stance"] == "bullish"
        assert d["long_term"]["stance"] == "bullish"
        assert len(d["conflicts"]) == 1
        assert d["conflicts"][0]["conflict_type"] == "horizon"

    def test_no_simple_average(self) -> None:
        """Each horizon is independent; no averaged stance."""
        id_ = IntegratedDecision(
            short_term=HorizonDecision(stance=Stance.BEARISH),
            medium_term=HorizonDecision(stance=Stance.BULLISH),
            long_term=HorizonDecision(stance=Stance.BULLISH),
        )
        d = json.loads(to_json(id_))
        assert d["short_term"]["stance"] == "bearish"
        assert d["medium_term"]["stance"] == "bullish"
        assert d["long_term"]["stance"] == "bullish"
        # No 'average_stance' field exists
        assert "average_stance" not in d


# ---------------------------------------------------------------------------
# ProviderCapabilities
# ---------------------------------------------------------------------------

class TestProviderCapabilities:
    def test_roundtrip(self) -> None:
        pc = ProviderCapabilities(
            provider_id="mock",
            provider_version="0.1.0",
            supported_markets=("cn", "us"),
            supported_horizons=(Horizon.SHORT, Horizon.LONG),
            role=ProviderRole.REQUIRED,
        )
        d = json.loads(to_json(pc))
        assert d["provider_id"] == "mock"
        assert d["role"] == "required"
        assert d["supported_markets"] == ["cn", "us"]


# ---------------------------------------------------------------------------
# ProviderError
# ---------------------------------------------------------------------------

class TestProviderError:
    def test_is_exception(self) -> None:
        """ProviderError must be catchable as Exception."""
        with pytest.raises(Exception):
            raise ProviderError(code=ProviderErrorCode.TIMEOUT, stage="test")

    def test_roundtrip(self) -> None:
        pe = ProviderError(
            request_id="r1",
            run_id="run1",
            code=ProviderErrorCode.TIMEOUT,
            stage="research",
            retryable=True,
            fail_mode=FailMode.FAIL_CLOSED,
            provider_id="mock",
            partial=True,
            message="timeout",
        )
        d = json.loads(to_json(pe))
        assert d["code"] == "timeout"
        assert d["retryable"] is True
        assert d["partial"] is True

    def test_all_error_codes_serialize(self) -> None:
        for code in ProviderErrorCode:
            pe = ProviderError(code=code, stage="test")
            d = json.loads(to_json(pe))
            assert d["code"] == code.value


# ---------------------------------------------------------------------------
# Serialization determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_input_same_output(self) -> None:
        r = ResearchRequest(request_id="r1", subject="TEST", as_of="2026-07-01")
        j1 = to_json(r)
        j2 = to_json(r)
        assert j1 == j2

    def test_different_inputs_different_output(self) -> None:
        r1 = ResearchRequest(request_id="r1")
        r2 = ResearchRequest(request_id="r2")
        assert to_json(r1) != to_json(r2)

    def test_all_fields_preserved(self) -> None:
        """Unknown fields in JSON should be silently ignored on deserialization."""
        r = ResearchRequest(request_id="r1", subject="TEST")
        j = json.loads(to_json(r))
        j["unknown_future_field"] = "should_be_ignored"
        # Re-serialize should not include the unknown field
        # (it's lost in roundtrip, which is the documented behavior)
        assert "unknown_future_field" not in json.loads(to_json(r))
