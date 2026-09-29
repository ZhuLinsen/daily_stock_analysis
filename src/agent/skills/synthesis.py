# -*- coding: utf-8 -*-
"""
Strategy synthesis helpers for skill-agent consensus.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any, Dict, Iterable, List, Optional

from src.agent.protocols import (
    AgentOpinion,
    StrategyConflict,
    StrategyOpinion,
    normalize_strategy_signal,
    strategy_signal_score,
)
from src.agent.skills.deliberation import DeliberationMediator
from src.agent.skills.defaults import extract_skill_id

_SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}
_SCORE_TO_SIGNAL = [
    (4.5, "strong_buy"),
    (3.5, "buy"),
    (2.5, "hold"),
    (1.5, "sell"),
    (0.0, "strong_sell"),
]


def strategy_opinion_from_agent_opinion(opinion: AgentOpinion) -> StrategyOpinion:
    raw_data = opinion.raw_data if isinstance(opinion.raw_data, dict) else {}
    skill_id = str(raw_data.get("skill_id") or extract_skill_id(opinion.agent_name) or opinion.agent_name)
    key_levels = opinion.key_levels or raw_data.get("key_levels") or {}
    if not isinstance(key_levels, dict):
        key_levels = {}

    # Determine raw signal: prefer opinion.signal, fall back to raw_data
    raw_signal = opinion.signal if opinion.signal else raw_data.get("signal")

    # If signal is truly missing (None), mark as invalid — no silent hold default
    if raw_signal is None:
        return StrategyOpinion(
            skill_id=skill_id,
            agent_name=opinion.agent_name,
            signal="hold",
            confidence=opinion.confidence,
            reasoning=str(opinion.reasoning or raw_data.get("reasoning") or ""),
            score_adjustment=_as_float(raw_data.get("score_adjustment"), 0.0),
            conditions_met=_as_string_list(raw_data.get("conditions_met")),
            conditions_missed=_as_string_list(raw_data.get("conditions_missed")),
            key_levels=key_levels,
            raw_data={**raw_data, "normalized_signal": "hold", "original_signal": "", "invalid_signal": True},
            original_signal="",
            invalid_signal=True,  # missing signal = invalid
        )

    signal, invalid_signal, original_signal = normalize_strategy_signal(raw_signal)

    normalized_raw_data = dict(raw_data)
    normalized_raw_data["normalized_signal"] = signal
    normalized_raw_data["original_signal"] = original_signal
    normalized_raw_data["invalid_signal"] = invalid_signal

    return StrategyOpinion(
        skill_id=skill_id,
        agent_name=opinion.agent_name,
        signal=signal,
        confidence=opinion.confidence,
        reasoning=str(opinion.reasoning or raw_data.get("reasoning") or ""),
        score_adjustment=_as_float(raw_data.get("score_adjustment"), 0.0),
        conditions_met=_as_string_list(raw_data.get("conditions_met")),
        conditions_missed=_as_string_list(raw_data.get("conditions_missed")),
        key_levels=key_levels,
        raw_data=normalized_raw_data,
        original_signal=original_signal,
        invalid_signal=invalid_signal,
    )


class ConflictDetector:
    """Detect deterministic disagreements among strategy opinions."""

    def detect(
        self,
        opinions: List[StrategyOpinion],
        *,
        final_signal: Optional[str] = None,
    ) -> List[StrategyConflict]:
        valid_opinions = [op for op in opinions if not op.invalid_signal]
        if len(valid_opinions) < 2:
            return []

        conflicts: List[StrategyConflict] = []
        conflicts.extend(self._detect_directional_opposition(valid_opinions))
        conflicts.extend(self._detect_wide_score_dispersion(valid_opinions))
        if final_signal:
            conflicts.extend(self._detect_high_confidence_dissent(valid_opinions, final_signal))
        conflicts.extend(self._detect_adjustment_contradiction(valid_opinions))
        return sorted(conflicts, key=self._sort_key)

    @staticmethod
    def _detect_directional_opposition(opinions: List[StrategyOpinion]) -> List[StrategyConflict]:
        bullish = [op for op in opinions if strategy_signal_score(op.signal) >= 4.0]
        bearish = [op for op in opinions if strategy_signal_score(op.signal) <= 2.0]
        if not bullish or not bearish:
            return []

        max_bull_conf = max(op.confidence for op in bullish)
        max_bear_conf = max(op.confidence for op in bearish)
        severity = "high" if max_bull_conf >= 0.7 and max_bear_conf >= 0.7 else "medium"
        participants = _unique_ids([*bullish, *bearish])
        return [
            StrategyConflict(
                conflict_type="directional_opposition",
                severity=severity,
                description_key="strategy_conflict.directional_opposition",
                participants=participants,
                metadata={
                    "bullish": [op.skill_id for op in bullish],
                    "bearish": [op.skill_id for op in bearish],
                    "max_bullish_confidence": round(max_bull_conf, 4),
                    "max_bearish_confidence": round(max_bear_conf, 4),
                },
            )
        ]

    @staticmethod
    def _detect_wide_score_dispersion(opinions: List[StrategyOpinion]) -> List[StrategyConflict]:
        scored = [(op, strategy_signal_score(op.signal)) for op in opinions]
        min_score = min(score for _, score in scored)
        max_score = max(score for _, score in scored)
        spread = max_score - min_score
        if spread < 2.0:
            return []

        participants = [op.skill_id for op, score in scored if score in {min_score, max_score}]
        return [
            StrategyConflict(
                conflict_type="wide_score_dispersion",
                severity="high" if spread >= 3.0 else "medium",
                description_key="strategy_conflict.wide_score_dispersion",
                participants=_unique_strings(participants),
                metadata={"min_score": min_score, "max_score": max_score, "spread": spread},
            )
        ]

    @staticmethod
    def _detect_high_confidence_dissent(
        opinions: List[StrategyOpinion],
        final_signal: str,
    ) -> List[StrategyConflict]:
        final_score = strategy_signal_score(final_signal)
        dissenters = [
            op
            for op in opinions
            if op.confidence >= 0.75 and abs(strategy_signal_score(op.signal) - final_score) >= 2.0
        ]
        if not dissenters:
            return []

        return [
            StrategyConflict(
                conflict_type="high_confidence_dissent",
                severity="medium",
                description_key="strategy_conflict.high_confidence_dissent",
                participants=[op.skill_id for op in dissenters],
                metadata={
                    "final_signal": final_signal,
                    "dissenters": [
                        {"skill_id": op.skill_id, "signal": op.signal, "confidence": round(op.confidence, 4)}
                        for op in dissenters
                    ],
                },
            )
        ]

    @staticmethod
    def _detect_adjustment_contradiction(opinions: List[StrategyOpinion]) -> List[StrategyConflict]:
        positive = [op for op in opinions if op.score_adjustment >= 8]
        negative = [op for op in opinions if op.score_adjustment <= -8]
        if not positive or not negative:
            return []

        max_positive = max(op.score_adjustment for op in positive)
        min_negative = min(op.score_adjustment for op in negative)
        severity = "high" if max_positive >= 15 and min_negative <= -15 else "medium"
        return [
            StrategyConflict(
                conflict_type="adjustment_contradiction",
                severity=severity,
                description_key="strategy_conflict.adjustment_contradiction",
                participants=_unique_ids([*positive, *negative]),
                metadata={"max_positive_adjustment": max_positive, "min_negative_adjustment": min_negative},
            )
        ]

    @staticmethod
    def _sort_key(conflict: StrategyConflict) -> tuple[int, str, str]:
        return (-_SEVERITY_RANK.get(conflict.severity, 0), conflict.conflict_type, ",".join(conflict.participants))


class StrategySynthesizer:
    """Build an explainable synthesis payload for strategy consensus."""

    def __init__(
        self,
        deliberation_mediator: Optional[Any] = None,
    ) -> None:
        self.deliberation_mediator = deliberation_mediator or DeliberationMediator()

    def synthesize(
        self,
        opinions: List[StrategyOpinion],
        *,
        weighted_score: float,
        final_signal: str,
        weighted_confidence: float,
        conflicts: List[StrategyConflict],
        insufficient_evidence: bool = False,
        invalid_count: int = 0,
    ) -> Dict[str, Any]:
        conflict_severity = _highest_severity(conflicts)
        adjusted_confidence = self.adjust_confidence(weighted_confidence, conflict_severity)
        deliberation = self.deliberation_mediator.deliberate(
            opinions,
            conflicts,
            final_signal=final_signal,
        )
        if deliberation is not None:
            adjusted_confidence = max(
                0.0,
                min(1.0, adjusted_confidence + deliberation.summary.confidence_adjustment),
            )
        revision_projection = self._build_revision_projection(opinions, deliberation)
        final_score = strategy_signal_score(final_signal)
        supporting, opposing = self._group_opinions(opinions, final_score)
        consensus_level = self._consensus_level(
            opinions,
            conflicts,
            final_signal,
            insufficient_evidence=insufficient_evidence,
        )

        valid_opinions = [op for op in opinions if not op.invalid_signal]
        # When called directly (e.g. unit tests), infer invalid_count from the opinions
        # list itself. In the E2E path the explicit partition value takes precedence.
        invalid_count = max(invalid_count, sum(1 for op in opinions if op.invalid_signal))

        payload = {
            "final_signal": final_signal,
            "weighted_score": round(weighted_score, 4),
            "confidence": round(adjusted_confidence, 4),
            "original_confidence": round(max(0.0, min(1.0, weighted_confidence)), 4),
            "conflict_count": len(conflicts),
            "conflict_severity": conflict_severity,
            "conflicts": [_conflict_to_dict(conflict) for conflict in conflicts],
            "supporting_skills": supporting,
            "opposing_skills": opposing,
            "consensus_level": consensus_level,
            "summary_key": "strategy_synthesis.with_conflicts" if conflicts else "strategy_synthesis.no_conflicts",
            "summary_params": {
                "opinion_count": len(valid_opinions),
                "total_opinion_count": len(valid_opinions) + invalid_count,
                "invalid_opinion_count": invalid_count,
                "final_signal": final_signal,
                "consensus_level": consensus_level,
                "conflict_severity": conflict_severity,
                "conflict_count": len(conflicts),
            },
        }
        if deliberation is not None:
            payload["deliberation"] = deliberation.to_dict()
        if revision_projection is not None:
            payload["revision_projection"] = revision_projection
        return payload

    @staticmethod
    def adjust_confidence(confidence: float, conflict_severity: str) -> float:
        adjusted = max(0.0, min(1.0, confidence))
        if conflict_severity == "high":
            adjusted *= 0.85
        elif conflict_severity == "medium":
            adjusted *= 0.93
        return max(0.0, min(1.0, adjusted))

    @staticmethod
    def _group_opinions(
        opinions: List[StrategyOpinion],
        final_score: float,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Dynamic bipartite grouping per multi-strategy-contract §动态二分阵营.

        Every valid opinion falls into exactly one of supporting/opposing.
        `neutral_skills` is deliberately removed to prevent render mismatch
        ("high consensus" + "supporting: none").
        """
        supporting: List[Dict[str, Any]] = []
        opposing: List[Dict[str, Any]] = []
        for op in opinions:
            if op.invalid_signal:
                continue
            score = strategy_signal_score(op.signal)
            item = _opinion_to_item(op)

            if final_score == 3.0:
                if score == 3.0:
                    supporting.append(item)
                else:
                    opposing.append(item)
            else:
                opinion_bullish = score > 3.0
                opinion_bearish = score < 3.0
                same_side = (
                    (opinion_bullish and final_score > 3.0)
                    or (opinion_bearish and final_score < 3.0)
                )
                if same_side and abs(score - final_score) <= 1.0:
                    supporting.append(item)
                else:
                    opposing.append(item)
        return supporting, opposing

    @staticmethod
    def _consensus_level(
        opinions: List[StrategyOpinion],
        conflicts: List[StrategyConflict],
        final_signal: str,
        *,
        insufficient_evidence: bool = False,
    ) -> str:
        """Consensus level per multi-strategy-contract §共识度门槛.

        Precedence:
        1. aggregator-signalled insufficient (zero valid_weight_sum) → insufficient
        2. ≤ 1 valid opinion → insufficient
        3. sum(confidence) == 0 → insufficient
        4. conflict_severity == "high" → low
        5. aligned_ratio ≥ 2/3 且 conflict_count == 0 → high
        6. conflict_severity == "medium" 且 aligned_ratio < 0.5 → low
        7. 其余 → medium
        """
        if insufficient_evidence:
            return "insufficient"

        valid_opinions = [op for op in opinions if not op.invalid_signal]
        if len(valid_opinions) <= 1:
            return "insufficient"
        if sum(op.confidence for op in valid_opinions) == 0:
            return "insufficient"

        conflict_severity = _highest_severity(conflicts)
        if conflict_severity == "high":
            return "low"

        final_score = strategy_signal_score(final_signal)
        aligned = sum(
            1
            for op in valid_opinions
            if (
                strategy_signal_score(op.signal) == final_score
                or (
                    abs(strategy_signal_score(op.signal) - final_score) <= 1.0
                    and (
                        (strategy_signal_score(op.signal) > 3.0 and final_score > 3.0)
                        or (strategy_signal_score(op.signal) < 3.0 and final_score < 3.0)
                    )
                )
            )
        )
        aligned_ratio = aligned / len(valid_opinions)

        if not conflicts and aligned_ratio >= 2 / 3:
            return "high"
        if conflict_severity == "medium" and aligned_ratio < 0.5:
            return "low"
        return "medium"

    def _build_revision_projection(
        self,
        opinions: List[StrategyOpinion],
        deliberation: Optional[Any],
    ) -> Optional[Dict[str, Any]]:
        """Preview synthesis if softened deliberation responses were accepted.

        This is intentionally preview-only: it does not mutate opinions and does
        not override the authoritative final_signal already produced upstream.
        """
        if deliberation is None:
            return None

        valid_opinions = [op for op in opinions if not op.invalid_signal]
        if not valid_opinions:
            return None

        softened_by_skill = _softened_response_by_skill(deliberation.responses)
        projected_opinions: List[StrategyOpinion] = []
        changed_skills: List[str] = []
        for opinion in valid_opinions:
            response = softened_by_skill.get(opinion.skill_id)
            if response is None or not _is_safe_projection_response(response, opinion):
                projected_opinions.append(opinion)
                continue

            projected_opinions.append(
                replace(
                    opinion,
                    signal=response.revised_signal,
                    confidence=max(0.0, min(1.0, response.revised_confidence)),
                )
            )
            if opinion.skill_id not in changed_skills:
                changed_skills.append(opinion.skill_id)

        weighted_score, weighted_confidence = _confidence_weighted_projection(projected_opinions)
        projected_signal = _signal_from_score(weighted_score)
        projected_conflicts = ConflictDetector().detect(projected_opinions, final_signal=projected_signal)
        projected_conflict_severity = _highest_severity(projected_conflicts)
        projected_confidence = self.adjust_confidence(weighted_confidence, projected_conflict_severity)

        return {
            "status": "computed",
            "mode": "preview_only",
            "source_mode": str(getattr(deliberation, "mode", "")),
            "projected_signal": projected_signal,
            "projected_weighted_score": round(weighted_score, 4),
            "projected_confidence": round(projected_confidence, 4),
            "projected_original_confidence": round(weighted_confidence, 4),
            "projected_conflict_count": len(projected_conflicts),
            "projected_conflict_severity": projected_conflict_severity,
            "projected_consensus_level": self._consensus_level(
                projected_opinions,
                projected_conflicts,
                projected_signal,
                insufficient_evidence=False,
            ),
            "changed_skill_count": len(changed_skills),
            "changed_skills": changed_skills,
            "final_signal_overridden": False,
        }


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_string_list(value: Any) -> List[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []
    return [str(item) for item in value if item is not None]


def _unique_ids(opinions: Iterable[StrategyOpinion]) -> List[str]:
    return _unique_strings(op.skill_id for op in opinions)


def _unique_strings(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _highest_severity(conflicts: List[StrategyConflict]) -> str:
    if not conflicts:
        return "none"
    return max((conflict.severity for conflict in conflicts), key=lambda severity: _SEVERITY_RANK.get(severity, 0))


def _confidence_weighted_projection(opinions: List[StrategyOpinion]) -> tuple[float, float]:
    weighted: List[tuple[StrategyOpinion, float]] = [
        (opinion, max(0.0, min(1.0, opinion.confidence)))
        for opinion in opinions
        if not opinion.invalid_signal
    ]
    weight_sum = sum(weight for _, weight in weighted)
    if weight_sum <= 0:
        return 3.0, 0.0

    weighted_score = sum(
        strategy_signal_score(opinion.signal) * weight
        for opinion, weight in weighted
    ) / weight_sum
    weighted_confidence = sum(
        max(0.0, min(1.0, opinion.confidence)) * weight
        for opinion, weight in weighted
    ) / weight_sum
    return weighted_score, weighted_confidence


def _signal_from_score(score: float) -> str:
    for threshold, signal in _SCORE_TO_SIGNAL:
        if score >= threshold:
            return signal
    return "hold"


def _softened_response_by_skill(responses: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    if not isinstance(responses, list):
        return result

    for response in responses:
        if getattr(response, "revision", "") != "softened":
            continue
        skill_id = str(getattr(response, "skill_id", "") or "")
        revised_signal = str(getattr(response, "revised_signal", "") or "")
        if not skill_id or not revised_signal:
            continue
        _, invalid, _ = normalize_strategy_signal(revised_signal)
        if invalid:
            continue

        current = result.get(skill_id)
        if current is None or _projection_preference(response) < _projection_preference(current):
            result[skill_id] = response
    return result


def _is_safe_projection_response(response: Any, opinion: StrategyOpinion) -> bool:
    """Reject projection inputs that are more aggressive than the source opinion."""
    if str(getattr(response, "original_signal", "") or "") != opinion.signal:
        return False
    revised_signal = str(getattr(response, "revised_signal", "") or "")
    if revised_signal != DeliberationMediator._softened_signal(opinion.signal):
        return False
    revised_confidence = _as_float(getattr(response, "revised_confidence", None), -1.0)
    return 0.0 <= revised_confidence <= opinion.confidence + 0.0001


def _projection_preference(response: Any) -> tuple[float, float]:
    signal = str(getattr(response, "revised_signal", "") or "hold")
    confidence = _as_float(getattr(response, "revised_confidence", 0.0), 0.0)
    return abs(strategy_signal_score(signal) - strategy_signal_score("hold")), confidence


def _opinion_to_item(opinion: StrategyOpinion) -> Dict[str, Any]:
    return {
        "skill_id": opinion.skill_id,
        "agent_name": opinion.agent_name,
        "signal": opinion.signal,
        "confidence": round(opinion.confidence, 4),
        "reasoning": opinion.reasoning,
        "score_adjustment": opinion.score_adjustment,
        "conditions_met": opinion.conditions_met,
        "invalid_signal": opinion.invalid_signal,
    }


def _conflict_to_dict(conflict: StrategyConflict) -> Dict[str, Any]:
    payload = asdict(conflict)
    payload.pop("description", None)
    return payload
