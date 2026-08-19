# -*- coding: utf-8 -*-
"""Tests for MockResearchProvider — behaviour and contract compliance."""

from __future__ import annotations

import json
import pytest

from src.schemas.research_contracts import (
    FrameworkOpinion,
    Horizon,
    ProviderErrorCode,
    ProviderError,
    ProviderRole,
    ResearchRequest,
    Stance,
    to_json,
)
from tests.research.mock_provider import MockResearchProvider


@pytest.fixture
def provider() -> MockResearchProvider:
    return MockResearchProvider()


@pytest.fixture
def valid_request() -> ResearchRequest:
    return ResearchRequest(
        request_id="test-req-001",
        run_id="test-run-001",
        subject="TEST",
        market="cn",
        as_of="2026-07-01",
    )


class TestMockProviderIdentity:
    def test_provider_id(self, provider: MockResearchProvider) -> None:
        assert provider.provider_id == "mock"

    def test_provider_version(self, provider: MockResearchProvider) -> None:
        assert provider.provider_version == "0.2.0"

    def test_health(self, provider: MockResearchProvider) -> None:
        assert provider.health() is True

    def test_cancel_is_supported(self, provider: MockResearchProvider) -> None:
        assert provider.cancel("any-task") is True


class TestMockProviderCapabilities:
    def test_role_is_required(self, provider: MockResearchProvider) -> None:
        caps = provider.capabilities()
        assert caps.role == ProviderRole.REQUIRED
        assert caps.provider_id == "mock"
        assert caps.supports_sync is True
        assert caps.supports_cancellation is True

    def test_supported_horizons(self, provider: MockResearchProvider) -> None:
        caps = provider.capabilities()
        assert Horizon.SHORT in caps.supported_horizons
        assert Horizon.MEDIUM in caps.supported_horizons
        assert Horizon.LONG in caps.supported_horizons


class TestMockProviderValidation:
    def test_valid_request_passes(self, provider: MockResearchProvider, valid_request: ResearchRequest) -> None:
        provider.validate(valid_request)  # should not raise

    def test_missing_request_id_raises(self, provider: MockResearchProvider) -> None:
        r = ResearchRequest(subject="TEST")
        with pytest.raises(ProviderError) as exc_info:
            provider.validate(r)
        assert exc_info.value.code == ProviderErrorCode.CONTRACT_VIOLATION
        assert "request_id" in exc_info.value.message

    def test_missing_subject_raises(self, provider: MockResearchProvider) -> None:
        r = ResearchRequest(request_id="r1")
        with pytest.raises(ProviderError) as exc_info:
            provider.validate(r)
        assert exc_info.value.code == ProviderErrorCode.CONTRACT_VIOLATION
        assert "subject" in exc_info.value.message


class TestMockProviderResearch:
    def test_returns_opinion(self, provider: MockResearchProvider, valid_request: ResearchRequest) -> None:
        result = provider.research(valid_request)
        assert isinstance(result, FrameworkOpinion)
        assert result.provider_id == "mock"
        assert result.request_id == "test-req-001"
        assert result.stance in (Stance.BULLISH, Stance.NEUTRAL, Stance.BEARISH, Stance.ABSTAIN)

    def test_invalid_request_returns_error(self, provider: MockResearchProvider) -> None:
        r = ResearchRequest()  # missing request_id and subject
        result = provider.research(r)
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.CONTRACT_VIOLATION

    def test_evidence_attached(self, provider: MockResearchProvider, valid_request: ResearchRequest) -> None:
        result = provider.research(valid_request)
        assert isinstance(result, FrameworkOpinion)
        assert len(result.evidence_refs) > 0
        assert result.evidence_refs[0].evidence_id != ""

    def test_claims_attached(self, provider: MockResearchProvider, valid_request: ResearchRequest) -> None:
        result = provider.research(valid_request)
        assert isinstance(result, FrameworkOpinion)
        assert len(result.claims) > 0

    def test_warnings_present(self, provider: MockResearchProvider, valid_request: ResearchRequest) -> None:
        result = provider.research(valid_request)
        assert isinstance(result, FrameworkOpinion)
        assert any("mock" in w.lower() for w in result.warnings)

    def test_each_horizon(self, provider: MockResearchProvider) -> None:
        for horizon in [Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG]:
            r = ResearchRequest(
                request_id=f"test-{horizon.value}",
                subject="TEST",
                horizons=(horizon,),
                as_of="2026-07-01",
            )
            result = provider.research(r)
            assert isinstance(result, FrameworkOpinion)
            assert result.horizon == horizon

    def test_result_is_serializable(self, provider: MockResearchProvider, valid_request: ResearchRequest) -> None:
        result = provider.research(valid_request)
        j = to_json(result)
        d = json.loads(j)
        assert d["provider_id"] == "mock"
        assert "claims" in d
        assert "evidence_refs" in d


class TestMockProviderFailClosed:
    """Mock provider must fail-closed on contract violations."""

    def test_empty_request_id_is_fail_closed(self, provider: MockResearchProvider) -> None:
        result = provider.research(ResearchRequest(subject="TEST"))
        assert isinstance(result, ProviderError)
        assert result.fail_mode.value == "fail_closed"

    def test_empty_subject_is_fail_closed(self, provider: MockResearchProvider) -> None:
        result = provider.research(ResearchRequest(request_id="r1"))
        assert isinstance(result, ProviderError)
        assert result.fail_mode.value == "fail_closed"
