# -*- coding: utf-8 -*-
"""Decision profile domain helpers for persisted DecisionSignal identity.

SQL same-profile semantics are intentionally null-safe:

- ``profile is None`` means legacy/unknown profile and must be expressed as
  ``decision_profile IS NULL``.
- a non-null profile must be expressed as ``decision_profile = <profile>``.

Do not use bare ``None`` to mean "all profiles" in list filters. Use the
normalized filter object below so omitted/empty filters and ``unknown`` remain
distinct.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


DecisionProfile = Literal["conservative", "balanced", "aggressive"]
DecisionProfileFilterKind = Literal["all", "unknown", "profile"]

VALID_DECISION_PROFILES: tuple[DecisionProfile, ...] = (
    "conservative",
    "balanced",
    "aggressive",
)
DECISION_PROFILE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class DecisionProfileFilter:
    kind: DecisionProfileFilterKind
    profile: Optional[DecisionProfile] = None

    @property
    def is_all(self) -> bool:
        return self.kind == "all"

    @property
    def is_unknown(self) -> bool:
        return self.kind == "unknown"


DECISION_PROFILE_FILTER_ALL = DecisionProfileFilter("all")
DECISION_PROFILE_FILTER_UNKNOWN = DecisionProfileFilter("unknown")


def normalize_decision_profile(
    value: Any,
    *,
    field_name: str = "decision_profile",
) -> Optional[DecisionProfile]:
    """Return a normalized profile or raise for a non-empty invalid value."""

    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in VALID_DECISION_PROFILES:
        return text  # type: ignore[return-value]
    allowed = ", ".join(VALID_DECISION_PROFILES)
    raise ValueError(f"{field_name} must be one of: {allowed}")


def normalize_decision_profile_filter(value: Any) -> DecisionProfileFilter:
    """Normalize list-filter input while preserving all-vs-unknown semantics."""

    if value in (None, ""):
        return DECISION_PROFILE_FILTER_ALL
    text = str(value).strip().lower()
    if not text:
        return DECISION_PROFILE_FILTER_ALL
    if text == DECISION_PROFILE_UNKNOWN:
        return DECISION_PROFILE_FILTER_UNKNOWN
    profile = normalize_decision_profile(text, field_name="decision_profile")
    return DecisionProfileFilter("profile", profile)


def extract_legacy_decision_profile(metadata: Any) -> Optional[DecisionProfile]:
    """Extract a legal legacy profile from metadata; invalid values are ignored."""

    if not isinstance(metadata, dict):
        return None
    try:
        return normalize_decision_profile(metadata.get("decision_profile"))
    except ValueError:
        return None
