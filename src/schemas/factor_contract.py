# -*- coding: utf-8 -*-
"""Internal DSA factor contract for Issue #1902 P0.

Backend-only schema and serialisation for the staged factor work in
#1902: ``FactorDefinition``, ``FactorSnapshot``, ``CandidatePoolRun``
and ``CandidateFactorScore``. The contract is purely additive — no
existing call path, API response, or default behaviour changes — and
nothing calls into it yet; P1 owns the first call site. Field
semantics and mapping rules live in ``docs/factor-contract.md``.

Note: ``model_copy(update=...)`` skips field validation (Pydantic
default, same as ``AnalysisContextPack``); only ``contract_version``
is guarded, so updates are trusted-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from src.utils.sanitize import redact_sensitive_mapping


FACTOR_CONTRACT_VERSION = "1.0"
FACTOR_SET_VERSION = "1.0"
_CONTRACT_VERSION_ADAPTER = TypeAdapter(Literal["1.0"])


def normalize_contract_timestamp(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime.

    Naive values are process-local wall time — the same clock that
    produces ``ScreenResult.created_at`` via ``datetime.now()`` (the
    deployment runs with ``TZ=Asia/Shanghai``) — so they are read on
    the local clock and converted to UTC, never just stamped ``Z``.
    The offset is resolved per the input date's local rules, so a
    daylight-saving date converts with the daylight offset even when
    the mapping runs in standard time (and vice versa); attaching
    today's fixed offset would shift cross-DST dates by an hour.
    Ambiguous or nonexistent local times at DST transitions follow
    the platform's default fold handling. Aware values are converted
    to UTC unchanged in meaning.
    """
    # astimezone() presumes a naive value is local time and resolves
    # the offset from the platform tz database per the input date;
    # aware values convert directly. One call covers both cases.
    return value.astimezone(timezone.utc)


def _normalize_timestamp_field(value: datetime) -> datetime:
    return normalize_contract_timestamp(value)

FactorId = Literal[
    "value",
    "liquidity",
    "momentum",
    "reversal",
    "activity",
    "stability",
    "size",
    "theme_heat",
    "topic_alignment",
]


class _FactorContractModel(BaseModel):
    """Base model for the internal P0 factor contract."""

    # allow_inf_nan=False rejects NaN/±Inf on every float field —
    # plain, Optional, and dict values alike (verified on pydantic
    # 2.14.3) — so no per-field finite validators are needed.
    model_config = ConfigDict(validate_assignment=True, allow_inf_nan=False)


class FactorCategory(str, Enum):
    """Descriptive grouping for the known factors; never affects scoring."""

    VALUATION = "valuation"
    LIQUIDITY = "liquidity"
    TECHNICAL = "technical"
    THEME = "theme"


class FactorFieldStatus(str, Enum):
    """Quality state of a factor observation."""

    AVAILABLE = "available"
    MISSING = "missing"
    PARTIAL = "partial"
    FALLBACK = "fallback"
    STALE = "stale"


class FactorDefinition(_FactorContractModel):
    """Identity and computation provenance of one factor.

    One per factor_id; carries no per-stock data. ``factor_id`` is a
    closed Literal: extending the scorer inventory requires a contract
    bump, which the ``factor_definitions`` guard test enforces.
    """

    factor_id: FactorId
    name: str
    category: FactorCategory
    unit: str
    definition: str
    version: str = "1"
    source: str
    window: str | None = None
    params: dict[str, float] = Field(default_factory=dict)
    factor_set_version: str = FACTOR_SET_VERSION


class FactorDataQuality(_FactorContractModel):
    """Per-observation data quality.

    ``coverage``/``missing_rate`` are ``None`` when unknown — never
    fabricated. At ``Pick`` level only presence/absence is knowable,
    so per-factor coverage stays ``None`` and only the snapshot
    aggregate carries the present/9 fraction.
    """

    coverage: float | None = Field(None, ge=0.0, le=1.0)
    missing_rate: float | None = Field(None, ge=0.0, le=1.0)
    status: FactorFieldStatus = FactorFieldStatus.AVAILABLE
    degradation_reason: str | None = None
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CandidateFactorScore(_FactorContractModel):
    """One factor value for one candidate in one run.

    The typed replacement for one ``Pick.factor_scores`` entry.
    ``factor_id`` stays a free string so observations survive scorer
    drift; unknown ids are carried with a warning by the mapper.
    """

    factor_id: str = Field(min_length=1)
    value: float = Field(ge=0, le=100)
    weight: float | None = None
    quality: FactorDataQuality = Field(default_factory=FactorDataQuality)
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    normalize_computed_at = field_validator("computed_at", mode="after")(
        _normalize_timestamp_field
    )


class FactorSnapshot(_FactorContractModel):
    """All factor scores for one candidate in one run.

    ``rank`` is the candidate's overall pool rank from ``Pick.rank``
    (1-based; every producer path assigns ``rank >= 1``). It is
    ``None`` only when the rank is unknown, never 0.
    """

    contract_version: Literal["1.0"] = FACTOR_CONTRACT_VERSION
    candidate_pool_run_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    name: str | None = None
    rank: int | None = Field(default=None, ge=1)
    factor_set_version: str = FACTOR_SET_VERSION
    scores: dict[str, CandidateFactorScore] = Field(default_factory=dict)
    screen_score: float | None = None
    quality: FactorDataQuality = Field(default_factory=FactorDataQuality)
    source: str = "screening.pipeline"
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    normalize_computed_at = field_validator("computed_at", mode="after")(
        _normalize_timestamp_field
    )

    @model_validator(mode="after")
    def _scores_keys_match_factor_ids(self) -> "FactorSnapshot":
        for key, score in self.scores.items():
            if key != score.factor_id:
                raise ValueError(
                    f"scores key {key!r} does not match "
                    f"factor_id {score.factor_id!r}"
                )
        return self

    def to_safe_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict with sensitive mapping values redacted."""
        return redact_sensitive_mapping(self.model_dump(mode="json"))

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> "FactorSnapshot":
        """Copy the snapshot without bypassing the fixed contract version."""
        if update is not None and "contract_version" in update:
            _CONTRACT_VERSION_ADAPTER.validate_python(update["contract_version"])
        return super().model_copy(update=update, deep=deep)


class CandidatePoolRun(_FactorContractModel):
    """Run envelope: a typed view over ``ScreenResult`` header fields.

    P0 does not persist this; P1 owns persistence.
    """

    contract_version: Literal["1.0"] = FACTOR_CONTRACT_VERSION
    run_id: str = Field(min_length=1)
    strategy: str
    strategy_version: str = ""
    strategy_category: str = ""
    market: str
    factor_set_version: str = FACTOR_SET_VERSION
    effective_factor_weights: dict[str, float] = Field(default_factory=dict)
    candidate_count: int = Field(default=0, ge=0)
    snapshot_count: int = Field(default=0, ge=0)
    after_filter_count: int = Field(default=0, ge=0)
    snapshot_source: str = ""
    source_errors: list[str] = Field(default_factory=list)
    degradation: list[str] = Field(default_factory=list)
    ranking_mode: str = "factor"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    normalize_created_at = field_validator("created_at", mode="after")(
        _normalize_timestamp_field
    )

    def to_safe_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dict with sensitive mapping values redacted."""
        return redact_sensitive_mapping(self.model_dump(mode="json"))

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> "CandidatePoolRun":
        """Copy the run without bypassing the fixed contract version."""
        if update is not None and "contract_version" in update:
            _CONTRACT_VERSION_ADAPTER.validate_python(update["contract_version"])
        return super().model_copy(update=update, deep=deep)
