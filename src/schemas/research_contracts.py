# -*- coding: utf-8 -*-
"""DSA Research OS — research contract types.

All eight contract types for the ResearchProvider interface.
Every type carries ``schema_version`` for forward-compatible versioning
and serialises deterministically to JSON via ``as_json()`` / ``from_json()``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Schema version — bump when any contract type changes
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Stance(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    ABSTAIN = "abstain"


class ClaimKind(str, Enum):
    FACT = "fact"
    OPINION = "opinion"
    INFERENCE = "inference"


class ConflictType(str, Enum):
    HORIZON = "horizon"
    METHODOLOGY = "methodology"
    FACTUAL = "factual"
    VALUATION = "valuation"


class ConflictResolutionStatus(str, Enum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    ABSTAINED = "abstained"


class Horizon(str, Enum):
    SHORT = "short_term"
    MEDIUM = "medium_term"
    LONG = "long_term"


class ProviderRole(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class ProviderErrorCode(str, Enum):
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNAUTHORIZED = "unauthorized"
    STALE_EVIDENCE = "stale_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REVISION_MISMATCH = "revision_mismatch"
    OUTPUT_TOO_LARGE = "output_too_large"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    CONTRACT_VIOLATION = "contract_violation"
    UNKNOWN = "unknown"


class SensitiveLevel(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PRIVATE = "private"


class EvidenceFreshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


class FailMode(str, Enum):
    FAIL_CLOSED = "fail_closed"
    FAIL_OPEN = "fail_open"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_evidence_id() -> str:
    """Deterministic but unique evidence ID for mock."""
    return hashlib.sha256(f"{_now_iso()}-{id(object())}".encode()).hexdigest()[:16]


def _serialize(obj: Any) -> Any:
    """Recursively convert dataclasses / enums / datetimes for JSON."""
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# 1. ResearchRequest
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Reproducibility:
    dsa_sha: str
    external_revision: Optional[str] = None
    contract_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class ResearchRequest:
    schema_version: str = SCHEMA_VERSION
    request_id: str = ""
    run_id: str = ""
    subject: str = ""
    market: str = ""
    as_of: str = ""
    horizons: Tuple[Horizon, ...] = (Horizon.SHORT, Horizon.MEDIUM, Horizon.LONG)
    data_domains: Tuple[str, ...] = ("technical", "fundamental", "news")
    authorization_context: str = ""
    language: str = "zh"
    provider_timeout_seconds: float = 30.0
    total_timeout_seconds: float = 120.0
    max_output_bytes: int = 65536
    max_evidence_count: int = 100
    reproducibility: Reproducibility = field(default_factory=lambda: Reproducibility(dsa_sha=""))
    redaction_profile: str = "default"
    idempotency_key: str = ""


# ---------------------------------------------------------------------------
# 2. EvidenceRef
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceRef:
    schema_version: str = SCHEMA_VERSION
    evidence_id: str = ""
    source_type: str = ""  # e.g. "database", "api", "file", "private"
    source_uri: str = ""  # URL or opaque private:// reference
    title: str = ""
    publisher: str = ""
    published_at: str = ""
    observed_at: str = ""
    as_of: str = ""
    content_hash: str = ""  # SHA-256 of content, not content itself
    authorization: str = "public"
    sensitive_level: SensitiveLevel = SensitiveLevel.PUBLIC
    license: str = ""
    freshness: EvidenceFreshness = EvidenceFreshness.FRESH
    claim_ids: Tuple[str, ...] = ()
    locator: str = ""  # reproducible location reference


# ---------------------------------------------------------------------------
# 3. Claim
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Claim:
    claim_id: str
    claim_kind: ClaimKind
    text: str
    evidence_ids: Tuple[str, ...] = ()
    dependent_fact_ids: Tuple[str, ...] = ()  # for inferences
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# 4. FrameworkOpinion
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrameworkOpinion:
    schema_version: str = SCHEMA_VERSION
    request_id: str = ""
    run_id: str = ""
    provider_id: str = ""
    provider_version: str = ""
    framework: str = ""
    framework_version: str = ""
    as_of: str = ""
    horizon: Horizon = Horizon.SHORT
    stance: Stance = Stance.ABSTAIN
    confidence: float = 0.0
    data_quality: float = 0.0  # 0-1 scale
    claims: Tuple[Claim, ...] = ()
    evidence_refs: Tuple[EvidenceRef, ...] = ()
    risks: Tuple[str, ...] = ()
    assumptions: Tuple[str, ...] = ()
    counterarguments: Tuple[str, ...] = ()
    gaps: Tuple[str, ...] = ()
    data_cutoff: str = ""
    warnings: Tuple[str, ...] = ()
    invalidation_conditions: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# 5. ConflictItem
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConflictItem:
    schema_version: str = SCHEMA_VERSION
    request_id: str = ""
    run_id: str = ""
    claim_text: str = ""
    conflicting_providers: Tuple[str, ...] = ()
    evidence_ids: Tuple[str, ...] = ()
    conflict_type: ConflictType = ConflictType.METHODOLOGY
    resolution_status: ConflictResolutionStatus = ConflictResolutionStatus.UNRESOLVED
    reason_cannot_average: str = ""


# ---------------------------------------------------------------------------
# 6. HorizonDecision
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HorizonDecision:
    horizon: Horizon = Horizon.SHORT
    conclusion: str = ""
    stance: Stance = Stance.ABSTAIN
    action_boundary: str = ""
    confidence: float = 0.0
    evidence_ids: Tuple[str, ...] = ()
    risks: Tuple[str, ...] = ()
    abstain_reason: str = ""


# ---------------------------------------------------------------------------
# 7. IntegratedDecision
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IntegratedDecision:
    schema_version: str = SCHEMA_VERSION
    request_id: str = ""
    run_id: str = ""
    as_of: str = ""
    short_term: HorizonDecision = field(default_factory=lambda: HorizonDecision(horizon=Horizon.SHORT))
    medium_term: HorizonDecision = field(default_factory=lambda: HorizonDecision(horizon=Horizon.MEDIUM))
    long_term: HorizonDecision = field(default_factory=lambda: HorizonDecision(horizon=Horizon.LONG))
    conflicts: Tuple[ConflictItem, ...] = ()
    provider_versions: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 8. ProviderCapabilities
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderCapabilities:
    schema_version: str = SCHEMA_VERSION
    provider_id: str = ""
    provider_version: str = ""
    supported_markets: Tuple[str, ...] = ()
    supported_horizons: Tuple[Horizon, ...] = ()
    supported_evidence_types: Tuple[str, ...] = ()
    supports_sync: bool = True
    supports_background: bool = False
    supports_cancellation: bool = False
    max_budget_tokens: int = 0
    max_output_bytes: int = 65536
    requires_network: bool = False
    handles_private_data: bool = False
    reproducibility_level: str = "deterministic"
    role: ProviderRole = ProviderRole.OPTIONAL


# ---------------------------------------------------------------------------
# 9. ProviderError
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderError(Exception):
    schema_version: str = SCHEMA_VERSION
    request_id: str = ""
    run_id: str = ""
    code: ProviderErrorCode = ProviderErrorCode.UNKNOWN
    stage: str = ""
    retryable: bool = False
    fallbackable: bool = False
    fail_mode: FailMode = FailMode.FAIL_CLOSED
    provider_id: str = ""
    provider_version: str = ""
    partial: bool = False
    details: Dict[str, Any] = field(default_factory=dict)
    message: str = ""


# ---------------------------------------------------------------------------
# JSON roundtrip helpers
# ---------------------------------------------------------------------------

def to_json(obj: Any) -> str:
    """Deterministic JSON serialization."""
    return json.dumps(_serialize(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _from_dict(cls, data: dict) -> Any:
    """Construct a frozen dataclass from a dict, ignoring unknown fields."""
    import dataclasses as dc
    field_names = {f.name for f in dc.fields(cls)}
    filtered = {k: v for k, v in data.items() if k in field_names}
    return cls(**filtered)
