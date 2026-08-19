# -*- coding: utf-8 -*-
"""DSA Research OS — DsaTechnicalProvider.

Read-only wrapper around existing DSA data/market tools. The provider is
optional and locally fail-open: a missing snapshot or analysis failure
becomes an abstain on that horizon, never a fabricated stance.

Production fetches go through injectable ``TechnicalMarketFetcher``. Tests
must inject a mock; the default suite never opens the network.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, Union

from src.agent.research_provider import ResearchProvider
from src.schemas.research_contracts import (
    Claim,
    ClaimKind,
    EvidenceFreshness,
    EvidenceRef,
    FailMode,
    FrameworkOpinion,
    Horizon,
    ProviderCapabilities,
    ProviderError,
    ProviderErrorCode,
    ProviderRole,
    ResearchRequest,
    SensitiveLevel,
    Stance,
)

PROVIDER_ID = "dsa-technical"
PROVIDER_VERSION = "0.1.0"
_FRAMEWORK = "dsa-technical"
_SHORT_BARS = 20
_MEDIUM_BARS = 60
_RETURN_THRESHOLD = 0.03


class TechnicalMarketFetcher(Protocol):
    """Snapshot source used by DsaTechnicalProvider.

    Implementations may wrap ``data_tools`` / ``market_tools``. Tests inject
    an in-memory fake and must not perform I/O.
    """

    def fetch_quote(self, stock_code: str, market: str) -> Dict[str, Any]:
        ...

    def fetch_history(self, stock_code: str, market: str, days: int) -> Dict[str, Any]:
        ...

    def fetch_indices(self, market: str) -> Dict[str, Any]:
        ...


class DataToolsMarketFetcher:
    """Lazy wrapper around existing DSA tool handlers."""

    def fetch_quote(self, stock_code: str, market: str) -> Dict[str, Any]:
        from src.agent.tools.data_tools import _handle_get_realtime_quote

        return dict(_handle_get_realtime_quote(stock_code))

    def fetch_history(self, stock_code: str, market: str, days: int) -> Dict[str, Any]:
        from src.agent.tools.data_tools import _handle_get_daily_history

        return dict(_handle_get_daily_history(stock_code, days=days))

    def fetch_indices(self, market: str) -> Dict[str, Any]:
        from src.agent.tools.market_tools import _handle_get_market_indices

        return dict(_handle_get_market_indices(region=market or "cn"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))


def _content_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _horizon_bars(horizon: Horizon) -> int:
    if horizon == Horizon.MEDIUM:
        return _MEDIUM_BARS
    return _SHORT_BARS


def _extract_closes(history: Dict[str, Any]) -> List[float]:
    rows = history.get("data") or history.get("records") or []
    if not isinstance(rows, list):
        return []
    closes: List[float] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("close", row.get("Close", row.get("price")))
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        closes.append(value)
    return closes


def _snapshot_error(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return "snapshot is not an object"
    error = payload.get("error")
    if error:
        return str(error)
    return None


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _decide_stance(closes: Sequence[float], horizon: Horizon) -> Tuple[Stance, float, float, str]:
    needed = _horizon_bars(horizon)
    if len(closes) < max(5, needed // 2):
        return Stance.ABSTAIN, 0.0, 0.0, f"need at least {max(5, needed // 2)} closes"
    window = list(closes[-needed:])
    start, end = window[0], window[-1]
    if start == 0:
        return Stance.ABSTAIN, 0.0, 0.0, "cannot compute return from zero start price"
    ret = (end - start) / start
    ma = _mean(window)
    quality = min(1.0, len(window) / float(needed))
    if ret > _RETURN_THRESHOLD and end > ma:
        return Stance.BULLISH, min(0.85, 0.55 + abs(ret)), quality, f"return {ret:.2%} above MA"
    if ret < -_RETURN_THRESHOLD and end < ma:
        return Stance.BEARISH, min(0.85, 0.55 + abs(ret)), quality, f"return {ret:.2%} below MA"
    return Stance.NEUTRAL, 0.45, quality, f"return {ret:.2%} near MA"


class DsaTechnicalProvider:
    """Optional technical / market-context provider."""

    provider_id = PROVIDER_ID
    provider_version = PROVIDER_VERSION

    def __init__(self, fetcher: Optional[TechnicalMarketFetcher] = None) -> None:
        self._fetcher = fetcher
        self._cancel_event = threading.Event()

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            supported_markets=("cn", "hk", "us", "jp", "kr"),
            supported_horizons=(Horizon.SHORT, Horizon.MEDIUM),
            supported_evidence_types=("technical", "market"),
            supports_sync=True,
            supports_background=False,
            supports_cancellation=True,
            max_output_bytes=65536,
            requires_network=True,
            reproducibility_level="snapshot",
            role=ProviderRole.OPTIONAL,
        )

    def validate(self, request: ResearchRequest) -> None:
        if not request.request_id:
            raise self._error(
                request,
                ProviderErrorCode.CONTRACT_VIOLATION,
                "validate",
                "request_id is required",
                fail_mode=FailMode.FAIL_CLOSED,
            )
        if not request.subject:
            raise self._error(
                request,
                ProviderErrorCode.CONTRACT_VIOLATION,
                "validate",
                "subject is required",
                fail_mode=FailMode.FAIL_CLOSED,
            )

    def research(
        self,
        request: ResearchRequest,
        context: Optional[Dict] = None,
    ) -> Union[FrameworkOpinion, ProviderError]:
        del context
        if self._cancel_event.is_set():
            return self._error(
                request,
                ProviderErrorCode.CANCELLED,
                "research",
                "technical research cancelled",
                fail_mode=FailMode.FAIL_OPEN,
            )
        try:
            self.validate(request)
        except ProviderError as exc:
            return exc

        horizon = request.horizons[0] if request.horizons else Horizon.SHORT
        if horizon == Horizon.LONG:
            return self._opinion(
                request,
                horizon,
                Stance.ABSTAIN,
                confidence=0.0,
                data_quality=0.0,
                claims=(),
                evidence_refs=(),
                gaps=(
                    "technical provider covers 0-20 trading days and 1-4 quarters only",
                ),
                warnings=("long-horizon technical stance is out of scope",),
            )

        fetcher = self._require_fetcher()
        days = _horizon_bars(horizon)
        try:
            history = fetcher.fetch_history(request.subject, request.market, days)
        except Exception as exc:  # noqa: BLE001 - local fail-open
            return self._abstain_unavailable(request, horizon, f"history fetch failed: {exc}")

        if self._cancel_event.is_set():
            return self._error(
                request,
                ProviderErrorCode.CANCELLED,
                "research",
                "technical research cancelled",
                fail_mode=FailMode.FAIL_OPEN,
            )

        history_error = _snapshot_error(history)
        if history_error:
            return self._abstain_unavailable(request, horizon, history_error)

        quote: Optional[Dict[str, Any]] = None
        try:
            quote_payload = fetcher.fetch_quote(request.subject, request.market)
            if not _snapshot_error(quote_payload):
                quote = quote_payload
        except Exception:
            quote = None

        indices: Optional[Dict[str, Any]] = None
        try:
            indices_payload = fetcher.fetch_indices(request.market or "cn")
            if not _snapshot_error(indices_payload):
                indices = indices_payload
        except Exception:
            indices = None

        if self._cancel_event.is_set():
            return self._error(
                request,
                ProviderErrorCode.CANCELLED,
                "research",
                "technical research cancelled",
                fail_mode=FailMode.FAIL_OPEN,
            )

        closes = _extract_closes(history)
        stance, confidence, quality, reason = _decide_stance(closes, horizon)
        observed_at = _now_iso()
        evidence_refs, claim_ids = self._build_evidence(
            request, horizon, history, quote, indices, observed_at
        )
        if stance == Stance.ABSTAIN:
            return self._opinion(
                request,
                horizon,
                stance,
                confidence=0.0,
                data_quality=quality,
                claims=(),
                evidence_refs=evidence_refs,
                gaps=(reason,),
                warnings=("insufficient technical snapshot for a directional stance",),
            )

        history_id = evidence_refs[0].evidence_id
        ret_text = reason
        fact = Claim(
            claim_id=f"dsa-tech-fact-{horizon.value}",
            claim_kind=ClaimKind.FACT,
            text=f"{request.subject} {horizon.value} snapshot: {ret_text}",
            evidence_ids=(history_id,),
            confidence=min(0.9, quality + 0.1),
        )
        inference = Claim(
            claim_id=f"dsa-tech-inference-{horizon.value}",
            claim_kind=ClaimKind.INFERENCE,
            text=f"Technical stance for {request.subject} is {stance.value} on {horizon.value}",
            evidence_ids=claim_ids,
            dependent_fact_ids=(fact.claim_id,),
            confidence=confidence,
        )
        return self._opinion(
            request,
            horizon,
            stance,
            confidence=confidence,
            data_quality=quality,
            claims=(fact, inference),
            evidence_refs=evidence_refs,
            risks=("Technical signals can reverse within the horizon window",),
            assumptions=("OHLCV snapshot is complete enough for a simple MA/return rule",),
            counterarguments=("A regime change can invalidate recent moving-average context",),
            gaps=() if quote and indices else ("quote or market-index snapshot missing",),
            warnings=("This opinion is a mechanical technical readout, not a trade order",),
            invalidation_conditions=("Underlying listing halt, data source outage, or gap beyond the snapshot",),
        )

    def cancel(self, task_id: str) -> bool:
        del task_id
        self._cancel_event.set()
        return True

    def health(self) -> bool:
        return True

    def _require_fetcher(self) -> TechnicalMarketFetcher:
        if self._fetcher is None:
            self._fetcher = DataToolsMarketFetcher()
        return self._fetcher

    def _error(
        self,
        request: ResearchRequest,
        code: ProviderErrorCode,
        stage: str,
        message: str,
        *,
        fail_mode: FailMode,
    ) -> ProviderError:
        return ProviderError(
            request_id=request.request_id,
            run_id=request.run_id,
            code=code,
            stage=stage,
            retryable=False,
            fallbackable=True,
            fail_mode=fail_mode,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            partial=True,
            message=message,
        )

    def _abstain_unavailable(
        self,
        request: ResearchRequest,
        horizon: Horizon,
        reason: str,
    ) -> FrameworkOpinion:
        return self._opinion(
            request,
            horizon,
            Stance.ABSTAIN,
            confidence=0.0,
            data_quality=0.0,
            claims=(),
            evidence_refs=(),
            gaps=(reason,),
            warnings=("technical snapshot unavailable; horizon abstains",),
        )

    def _opinion(
        self,
        request: ResearchRequest,
        horizon: Horizon,
        stance: Stance,
        *,
        confidence: float,
        data_quality: float,
        claims: Tuple[Claim, ...],
        evidence_refs: Tuple[EvidenceRef, ...],
        risks: Tuple[str, ...] = (),
        assumptions: Tuple[str, ...] = (),
        counterarguments: Tuple[str, ...] = (),
        gaps: Tuple[str, ...] = (),
        warnings: Tuple[str, ...] = (),
        invalidation_conditions: Tuple[str, ...] = (),
    ) -> FrameworkOpinion:
        return FrameworkOpinion(
            request_id=request.request_id,
            run_id=request.run_id,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            framework=_FRAMEWORK,
            framework_version=self.provider_version,
            as_of=request.as_of,
            horizon=horizon,
            stance=stance,
            confidence=confidence,
            data_quality=data_quality,
            claims=claims,
            evidence_refs=evidence_refs,
            risks=risks,
            assumptions=assumptions,
            counterarguments=counterarguments,
            gaps=gaps,
            data_cutoff=request.as_of,
            warnings=warnings,
            invalidation_conditions=invalidation_conditions,
        )

    def _build_evidence(
        self,
        request: ResearchRequest,
        horizon: Horizon,
        history: Dict[str, Any],
        quote: Optional[Dict[str, Any]],
        indices: Optional[Dict[str, Any]],
        observed_at: str,
    ) -> Tuple[Tuple[EvidenceRef, ...], Tuple[str, ...]]:
        refs: List[EvidenceRef] = []
        history_digest = _content_hash({"subject": request.subject, "horizon": horizon.value, "history": history})
        history_id = f"dsa-tech-history-{history_digest[:12]}"
        refs.append(
            EvidenceRef(
                evidence_id=history_id,
                source_type="api",
                source_uri=f"dsa://technical/daily-history/{request.subject}",
                title=f"Daily history snapshot for {request.subject}",
                publisher="DSA data tools",
                published_at=observed_at,
                observed_at=observed_at,
                as_of=request.as_of,
                content_hash=history_digest,
                authorization="internal",
                sensitive_level=SensitiveLevel.INTERNAL,
                license="internal-use-only",
                freshness=EvidenceFreshness.FRESH,
                claim_ids=(f"dsa-tech-fact-{horizon.value}", f"dsa-tech-inference-{horizon.value}"),
                locator=f"sha256:{history_digest}",
            )
        )
        if quote:
            quote_digest = _content_hash({"subject": request.subject, "quote": quote})
            quote_id = f"dsa-tech-quote-{quote_digest[:12]}"
            refs.append(
                EvidenceRef(
                    evidence_id=quote_id,
                    source_type="api",
                    source_uri=f"dsa://technical/realtime-quote/{request.subject}",
                    title=f"Realtime quote snapshot for {request.subject}",
                    publisher="DSA data tools",
                    published_at=observed_at,
                    observed_at=observed_at,
                    as_of=request.as_of,
                    content_hash=quote_digest,
                    authorization="internal",
                    sensitive_level=SensitiveLevel.INTERNAL,
                    license="internal-use-only",
                    freshness=EvidenceFreshness.FRESH,
                    claim_ids=(f"dsa-tech-inference-{horizon.value}",),
                    locator=f"sha256:{quote_digest}",
                )
            )
        if indices:
            index_digest = _content_hash({"market": request.market, "indices": indices})
            index_id = f"dsa-tech-indices-{index_digest[:12]}"
            refs.append(
                EvidenceRef(
                    evidence_id=index_id,
                    source_type="api",
                    source_uri=f"dsa://technical/market-indices/{request.market or 'cn'}",
                    title=f"Market index snapshot for {request.market or 'cn'}",
                    publisher="DSA market tools",
                    published_at=observed_at,
                    observed_at=observed_at,
                    as_of=request.as_of,
                    content_hash=index_digest,
                    authorization="internal",
                    sensitive_level=SensitiveLevel.INTERNAL,
                    license="internal-use-only",
                    freshness=EvidenceFreshness.FRESH,
                    claim_ids=(f"dsa-tech-inference-{horizon.value}",),
                    locator=f"sha256:{index_digest}",
                )
            )
        return tuple(refs), tuple(ref.evidence_id for ref in refs)


# Structural check against the Protocol (no ABC inheritance required).
def _assert_protocol() -> None:
    provider: ResearchProvider = DsaTechnicalProvider(fetcher=_NullFetcher())
    del provider


class _NullFetcher:
    def fetch_quote(self, stock_code: str, market: str) -> Dict[str, Any]:
        return {"error": "null fetcher"}

    def fetch_history(self, stock_code: str, market: str, days: int) -> Dict[str, Any]:
        return {"error": "null fetcher"}

    def fetch_indices(self, market: str) -> Dict[str, Any]:
        return {"error": "null fetcher"}
