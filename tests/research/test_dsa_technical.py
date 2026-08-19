# -*- coding: utf-8 -*-
"""Offline tests for DsaTechnicalProvider.

All snapshots are fabricated. The default suite never constructs
DataToolsMarketFetcher and never opens the network.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List

import pytest

from src.agent.providers.dsa_technical import DsaTechnicalProvider
from src.agent.research_orchestrator import ResearchOrchestrator, ResearchTaskStatus
from src.schemas.research_contracts import (
    Horizon,
    ProviderError,
    ProviderErrorCode,
    ProviderRole,
    ResearchRequest,
    Stance,
)


def _bars(start: float, step: float, count: int) -> List[Dict[str, Any]]:
    rows = []
    price = start
    for i in range(count):
        rows.append(
            {
                "date": f"2026-06-{(i % 28) + 1:02d}",
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 1000 + i,
            }
        )
        price = round(price + step, 4)
    return rows


class MockMarketFetcher:
    def __init__(
        self,
        *,
        history: Dict[str, Any] | None = None,
        quote: Dict[str, Any] | None = None,
        indices: Dict[str, Any] | None = None,
        history_error: str | None = None,
        raise_history: bool = False,
        calls: Dict[str, int] | None = None,
    ) -> None:
        self.history = history if history is not None else {"data": _bars(10.0, 0.4, 20)}
        self.quote = quote if quote is not None else {"code": "TEST", "price": 17.6, "source": "mock"}
        self.indices = indices if indices is not None else {"region": "cn", "indices": [{"name": "MOCK", "change_pct": 0.5}]}
        self.history_error = history_error
        self.raise_history = raise_history
        self.last_days: int | None = None
        self.calls = calls if calls is not None else {"history": 0, "quote": 0, "indices": 0}

    def fetch_quote(self, stock_code: str, market: str) -> Dict[str, Any]:
        self.calls["quote"] += 1
        return dict(self.quote)

    def fetch_history(self, stock_code: str, market: str, days: int) -> Dict[str, Any]:
        self.calls["history"] += 1
        if self.raise_history:
            raise RuntimeError("mock network forbidden")
        self.last_days = days
        if self.history_error:
            return {"error": self.history_error}
        return dict(self.history)

    def fetch_indices(self, market: str) -> Dict[str, Any]:
        self.calls["indices"] += 1
        return dict(self.indices)


def make_request(**overrides) -> ResearchRequest:
    base = ResearchRequest(
        request_id="tech-req-001",
        run_id="tech-run-001",
        subject="TEST",
        market="cn",
        as_of="2026-07-01",
        horizons=(Horizon.SHORT,),
    )
    return replace(base, **overrides)


class TestCapabilities:
    def test_optional_short_medium_only(self) -> None:
        provider = DsaTechnicalProvider(fetcher=MockMarketFetcher())
        caps = provider.capabilities()
        assert caps.role == ProviderRole.OPTIONAL
        assert caps.supports_cancellation is True
        assert Horizon.SHORT in caps.supported_horizons
        assert Horizon.MEDIUM in caps.supported_horizons
        assert Horizon.LONG not in caps.supported_horizons

    def test_health_does_not_fetch(self) -> None:
        calls = {"history": 0, "quote": 0, "indices": 0}
        provider = DsaTechnicalProvider(fetcher=MockMarketFetcher(calls=calls))
        assert provider.health() is True
        assert calls == {"history": 0, "quote": 0, "indices": 0}


class TestValidation:
    def test_missing_request_id(self) -> None:
        provider = DsaTechnicalProvider(fetcher=MockMarketFetcher())
        with pytest.raises(ProviderError) as exc:
            provider.validate(make_request(request_id=""))
        assert exc.value.code == ProviderErrorCode.CONTRACT_VIOLATION

    def test_missing_subject(self) -> None:
        provider = DsaTechnicalProvider(fetcher=MockMarketFetcher())
        with pytest.raises(ProviderError) as exc:
            provider.validate(make_request(subject=""))
        assert exc.value.code == ProviderErrorCode.CONTRACT_VIOLATION


class TestResearch:
    def test_bullish_history_has_hashed_evidence(self) -> None:
        provider = DsaTechnicalProvider(fetcher=MockMarketFetcher())
        opinion = provider.research(make_request())
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.BULLISH
        assert opinion.evidence_refs
        assert all(ref.content_hash and ref.observed_at and ref.source_uri for ref in opinion.evidence_refs)
        assert all(ref.source_uri.startswith("dsa://technical/") for ref in opinion.evidence_refs)
        assert opinion.claims
        assert all(claim.evidence_ids for claim in opinion.claims)
        valid = {ref.evidence_id for ref in opinion.evidence_refs}
        for claim in opinion.claims:
            assert set(claim.evidence_ids) <= valid

    def test_bearish_history(self) -> None:
        fetcher = MockMarketFetcher(history={"data": _bars(20.0, -0.5, 20)})
        provider = DsaTechnicalProvider(fetcher=fetcher)
        opinion = provider.research(make_request())
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.BEARISH

    def test_fetch_error_abstains(self) -> None:
        provider = DsaTechnicalProvider(
            fetcher=MockMarketFetcher(history_error="No historical data available for TEST")
        )
        opinion = provider.research(make_request())
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.ABSTAIN
        assert opinion.claims == ()
        assert "unavailable" in " ".join(opinion.warnings).lower() or opinion.gaps

    def test_history_exception_abstains(self) -> None:
        provider = DsaTechnicalProvider(fetcher=MockMarketFetcher(raise_history=True))
        opinion = provider.research(make_request())
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.ABSTAIN

    def test_insufficient_bars_abstain(self) -> None:
        provider = DsaTechnicalProvider(fetcher=MockMarketFetcher(history={"data": _bars(10.0, 0.1, 3)}))
        opinion = provider.research(make_request())
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.ABSTAIN

    def test_long_horizon_abstains_without_fetch(self) -> None:
        calls = {"history": 0, "quote": 0, "indices": 0}
        provider = DsaTechnicalProvider(fetcher=MockMarketFetcher(calls=calls))
        opinion = provider.research(make_request(horizons=(Horizon.LONG,)))
        assert not isinstance(opinion, ProviderError)
        assert opinion.stance == Stance.ABSTAIN
        assert calls["history"] == 0
        assert "0-20" in " ".join(opinion.gaps)

    def test_cancel_before_research(self) -> None:
        provider = DsaTechnicalProvider(fetcher=MockMarketFetcher())
        assert provider.cancel("task-1") is True
        result = provider.research(make_request())
        assert isinstance(result, ProviderError)
        assert result.code == ProviderErrorCode.CANCELLED

    def test_medium_requests_sixty_bars(self) -> None:
        fetcher = MockMarketFetcher(history={"data": _bars(10.0, 0.2, 60)})
        provider = DsaTechnicalProvider(fetcher=fetcher)
        opinion = provider.research(make_request(horizons=(Horizon.MEDIUM,)))
        assert not isinstance(opinion, ProviderError)
        assert opinion.horizon == Horizon.MEDIUM
        assert fetcher.last_days == 60


class TestOrchestratorIntegration:
    def test_optional_technical_can_succeed(self) -> None:
        provider = DsaTechnicalProvider(fetcher=MockMarketFetcher())
        orch = ResearchOrchestrator([provider])
        result = orch.run(make_request())
        assert result.status == ResearchTaskStatus.SUCCEEDED
        assert result.integrated is not None
        assert result.integrated.short_term.stance == Stance.BULLISH
