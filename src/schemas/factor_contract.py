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

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

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


class FiniteFloatMap(dict[str, float]):
    """A float mapping that refuses non-finite values on every write.

    ``allow_inf_nan=False`` only bites at field validation, so an
    in-place ``run.effective_factor_weights[key] = float("nan")``
    (or ``definition.params[key] = float("nan")``) used to be
    accepted and the dumped JSON exported the entry as null, which
    the same contract then refused to read back (OR-COR-57d4e9b1).
    This mapping enforces finiteness on every mutating write; reads
    behave like a plain dict.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        data = dict(*args, **kwargs)
        for key, value in data.items():
            self._check(key, value)
        super().__init__(data)

    @staticmethod
    def _check(key: str, value: float) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"non-finite value for {key!r}: {value!r}")

    def __setitem__(self, key: str, value: float) -> None:
        self._check(key, value)
        super().__setitem__(key, value)

    def update(self, *args: Any, **kwargs: Any) -> None:
        # Check every pair first so a rejected update applies nothing.
        data = dict(*args, **kwargs)
        for key, value in data.items():
            self._check(key, value)
        super().update(data)

    def setdefault(
        self, key: str, default: float | None = None
    ) -> float | None:
        if key in self:
            return self[key]
        if default is None:
            raise ValueError(f"cannot set {key!r} to a None value")
        self._check(key, default)
        super().__setitem__(key, default)
        return default

    def __ior__(self, other: Any) -> "FiniteFloatMap":
        data = dict(other)
        for key, value in data.items():
            self._check(key, value)
        super().__ior__(data)
        return self


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
    # validate_default=True: the default must run through the field
    # validator too — otherwise a definition built (or JSON-read)
    # with params omitted gets a plain dict, and an in-place
    # ``definition.params[key] = float("nan")`` is accepted while
    # the dumped JSON exports the entry as null and the same
    # contract refuses to read it back (OR-COR-57d4e9b1). The
    # validator installs FiniteFloatMap, so the default is guarded
    # as well.
    params: dict[str, float] = Field(default_factory=dict, validate_default=True)
    factor_set_version: str = FACTOR_SET_VERSION

    @field_validator("params", mode="after")
    @classmethod
    def _params_are_finite(
        cls, params: dict[str, float]
    ) -> dict[str, float]:
        # A field validator, not a model validator: with
        # validate_assignment=True a model validator runs after the
        # field is already set, so a rejected assignment left the
        # invalid params in place. The value is returned as a
        # FiniteFloatMap so later in-place writes
        # (``definition.params[key] = value``) keep enforcing the
        # same invariant — the validator never runs for those.
        return FiniteFloatMap(params)


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

    # Frozen: a snapshot's ``scores`` dict is keyed by ``factor_id``,
    # and the field validator only runs on construction or whole
    # replacement — a nested ``score.factor_id = ...`` assignment
    # would silently desync the key from the id and the dumped
    # snapshot would fail its own JSON round-trip (OR-COR-2f8b65a1).
    # Freezing makes the assignment raise instead; scores are built
    # once by the mapper and never mutated afterwards.
    model_config = ConfigDict(frozen=True)

    factor_id: str = Field(min_length=1)
    value: float = Field(ge=0, le=100)
    weight: float | None = None
    quality: FactorDataQuality = Field(default_factory=FactorDataQuality)
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    normalize_computed_at = field_validator("computed_at", mode="after")(
        _normalize_timestamp_field
    )


class FactorScoreMap(dict[str, CandidateFactorScore]):
    """A ``FactorSnapshot.scores`` mapping that refuses desyncing writes.

    ``scores`` is keyed by ``factor_id`` and the field validator only
    runs on construction or whole replacement, so an in-place
    ``snapshot.scores[key] = score`` with a mismatched id used to
    desync the snapshot and break its own JSON round-trip
    (OR-COR-2f8b65a1). This mapping enforces the key/id invariant on
    every mutating write; reads behave like a plain dict.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        data = dict(*args, **kwargs)
        for key, score in data.items():
            self._check(key, score)
        super().__init__(data)

    @staticmethod
    def _check(key: str, score: CandidateFactorScore) -> None:
        if key != score.factor_id:
            raise ValueError(
                f"scores key {key!r} does not match "
                f"factor_id {score.factor_id!r}"
            )

    def __setitem__(self, key: str, score: CandidateFactorScore) -> None:
        self._check(key, score)
        super().__setitem__(key, score)

    def update(self, *args: Any, **kwargs: Any) -> None:
        # Check every pair first so a rejected update applies nothing.
        data = dict(*args, **kwargs)
        for key, score in data.items():
            self._check(key, score)
        super().update(data)

    def setdefault(
        self, key: str, default: CandidateFactorScore | None = None
    ) -> CandidateFactorScore | None:
        if key in self:
            return self[key]
        if default is None:
            raise ValueError(f"scores key {key!r} cannot hold a None score")
        self._check(key, default)
        super().__setitem__(key, default)
        return default

    def __ior__(self, other: Any) -> "FactorScoreMap":
        data = dict(other)
        for key, score in data.items():
            self._check(key, score)
        super().__ior__(data)
        return self


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
    # validate_default=True: the default must run through the field
    # validator too — otherwise a snapshot built (or JSON-read) with
    # scores omitted gets a plain dict, and an in-place
    # ``snapshot.scores[key] = score`` with a mismatched id desyncs
    # the key from the id and the dumped snapshot fails its own JSON
    # round-trip (OR-COR-2f8b65a1, omitted-scores path). The validator
    # installs FactorScoreMap, so the default is guarded as well.
    scores: dict[str, CandidateFactorScore] = Field(
        default_factory=dict, validate_default=True
    )
    screen_score: float | None = None
    quality: FactorDataQuality = Field(default_factory=FactorDataQuality)
    source: str = "screening.pipeline"
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    normalize_computed_at = field_validator("computed_at", mode="after")(
        _normalize_timestamp_field
    )

    @field_validator("scores", mode="after")
    @classmethod
    def _scores_keys_match_factor_ids(
        cls, scores: dict[str, CandidateFactorScore]
    ) -> dict[str, CandidateFactorScore]:
        # A field validator, not a model validator: with
        # validate_assignment=True a model validator runs after the
        # field is already set, so a rejected assignment left the
        # invalid scores in place (and the dumped snapshot failed its
        # own round-trip). Validating the field value first means a
        # rejected assignment never mutates the snapshot. The value is
        # returned as a FactorScoreMap so later in-place writes
        # (``snapshot.scores[key] = score``) keep enforcing the same
        # invariant — the validator never runs for those.
        for key, score in scores.items():
            if key != score.factor_id:
                raise ValueError(
                    f"scores key {key!r} does not match "
                    f"factor_id {score.factor_id!r}"
                )
        return FactorScoreMap(scores)

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
    # validate_default=True: the default must run through the field
    # validator too — otherwise a run built (or JSON-read) with
    # effective_factor_weights omitted gets a plain dict, and an
    # in-place ``run.effective_factor_weights[key] = float("nan")``
    # is accepted while the dumped JSON exports the entry as null
    # and the same contract refuses to read it back
    # (OR-COR-57d4e9b1). The validator installs FiniteFloatMap, so
    # the default is guarded as well.
    effective_factor_weights: dict[str, float] = Field(
        default_factory=dict, validate_default=True
    )
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

    @field_validator("effective_factor_weights", mode="after")
    @classmethod
    def _weights_are_finite(
        cls, weights: dict[str, float]
    ) -> dict[str, float]:
        # Same pattern as FactorDefinition._params_are_finite: the
        # value is returned as a FiniteFloatMap so later in-place
        # writes (``run.effective_factor_weights[key] = value``)
        # keep enforcing finiteness — the validator never runs for
        # those.
        return FiniteFloatMap(weights)

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
