# -*- coding: utf-8 -*-
"""
Strategy deliberation mediators for material skill-agent conflicts.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.agent.protocols import (
    StrategyConflict,
    StrategyOpinion,
    normalize_strategy_signal,
    strategy_signal_score,
)

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}
_DELIBERATION_TRIGGER_TYPES = {"directional_opposition", "high_confidence_dissent"}
_DELIBERATION_RESPONSE_CONFIDENCE_FLOOR = 0.3
_DELIBERATION_SOFTEN_FACTOR = 0.9
_DELIBERATION_ALLOWED_REVISIONS = {"unchanged", "softened"}
_DELIBERATION_ALLOWED_RESOLUTION_STATUS = {"unresolved", "partially_resolved"}


@dataclass
class DeliberationAgendaItem:
    agenda_id: str = ""
    conflict_type: str = ""
    severity: str = "medium"
    participants: List[str] = field(default_factory=list)
    question_key: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeliberationResponse:
    agenda_id: str = ""
    skill_id: str = ""
    stance: str = "defend"
    revision: str = "unchanged"
    original_signal: str = ""
    revised_signal: str = ""
    original_confidence: float = 0.0
    revised_confidence: float = 0.0
    critique_key: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeliberationSummary:
    resolution_status: str = "unresolved"
    resolved_conflict_count: int = 0
    unresolved_conflict_count: int = 0
    minority_view_preserved: bool = False
    confidence_adjustment: float = 0.0
    confidence_adjustment_reason_key: str = ""


@dataclass
class StrategyDeliberationResult:
    status: str = "skipped"
    mode: str = "mediator_v0"
    rounds: int = 0
    agenda: List[DeliberationAgendaItem] = field(default_factory=list)
    responses: List[DeliberationResponse] = field(default_factory=list)
    summary: DeliberationSummary = field(default_factory=DeliberationSummary)
    round_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "status": self.status,
            "mode": self.mode,
            "rounds": self.rounds,
            "agenda": [asdict(item) for item in self.agenda],
            "responses": [asdict(response) for response in self.responses],
            "summary": asdict(self.summary),
        }
        if self.round_history:
            payload["round_history"] = [dict(item) for item in self.round_history]
        return payload


class DeliberationMediator:
    """Produce deterministic one-round deliberation for material strategy conflicts."""

    def deliberate(
        self,
        opinions: List[StrategyOpinion],
        conflicts: List[StrategyConflict],
        *,
        final_signal: str,
    ) -> Optional[StrategyDeliberationResult]:
        valid_opinions = [op for op in opinions if not op.invalid_signal]
        material_conflicts = self._material_conflicts(conflicts)
        if len(valid_opinions) < 2 or not material_conflicts:
            return None

        by_skill = {op.skill_id: op for op in valid_opinions if op.skill_id}
        agenda: List[DeliberationAgendaItem] = []
        responses: List[DeliberationResponse] = []

        for conflict in material_conflicts[:3]:
            participants = [
                participant
                for participant in _unique_strings(conflict.participants)
                if participant in by_skill
            ]
            if len(participants) < 1:
                continue

            item = DeliberationAgendaItem(
                agenda_id=self._agenda_id(conflict, participants),
                conflict_type=conflict.conflict_type,
                severity=conflict.severity,
                participants=participants,
                question_key=f"deliberation.{conflict.conflict_type}",
                metadata=dict(conflict.metadata or {}),
            )
            agenda.append(item)
            for participant in participants:
                responses.append(
                    self._response_for(
                        item,
                        by_skill[participant],
                        final_signal=final_signal,
                    )
                )

        if not agenda:
            return None

        summary = self._summarize(agenda, responses, conflicts, final_signal=final_signal)
        return StrategyDeliberationResult(
            status="completed",
            mode="mediator_v0",
            rounds=1,
            agenda=agenda,
            responses=responses,
            summary=summary,
        )

    @staticmethod
    def _material_conflicts(conflicts: List[StrategyConflict]) -> List[StrategyConflict]:
        return [
            conflict
            for conflict in conflicts
            if (
                conflict.severity in {"medium", "high"}
                or conflict.conflict_type in _DELIBERATION_TRIGGER_TYPES
            )
        ]

    @staticmethod
    def _agenda_id(conflict: StrategyConflict, participants: List[str]) -> str:
        return ":".join([conflict.conflict_type, *participants])

    def _response_for(
        self,
        agenda: DeliberationAgendaItem,
        opinion: StrategyOpinion,
        *,
        final_signal: str,
    ) -> DeliberationResponse:
        revision = self._revision_for(agenda, opinion)
        revised_signal = self._softened_signal(opinion.signal) if revision == "softened" else opinion.signal
        revised_confidence = (
            self._softened_confidence(opinion.confidence)
            if revision == "softened"
            else opinion.confidence
        )
        stance = "defend" if self._same_side(opinion.signal, final_signal) else "challenge"
        return DeliberationResponse(
            agenda_id=agenda.agenda_id,
            skill_id=opinion.skill_id,
            stance=stance,
            revision=revision,
            original_signal=opinion.signal,
            revised_signal=revised_signal,
            original_confidence=round(opinion.confidence, 4),
            revised_confidence=round(revised_confidence, 4),
            critique_key=f"deliberation.critique.{agenda.conflict_type}.{stance}",
            metadata={
                "agent_name": opinion.agent_name,
                "score_adjustment": opinion.score_adjustment,
            },
        )

    @staticmethod
    def _revision_for(agenda: DeliberationAgendaItem, opinion: StrategyOpinion) -> str:
        if agenda.severity == "high":
            return "softened"
        if agenda.conflict_type == "directional_opposition" and opinion.confidence < 0.75:
            return "softened"
        return "unchanged"

    @staticmethod
    def _softened_signal(signal: str) -> str:
        if signal == "strong_buy":
            return "buy"
        if signal == "strong_sell":
            return "sell"
        return signal

    @staticmethod
    def _softened_confidence(confidence: float) -> float:
        bounded = max(0.0, min(1.0, confidence))
        if bounded <= _DELIBERATION_RESPONSE_CONFIDENCE_FLOOR:
            return bounded
        return max(_DELIBERATION_RESPONSE_CONFIDENCE_FLOOR, bounded * _DELIBERATION_SOFTEN_FACTOR)

    @staticmethod
    def _same_side(signal: str, final_signal: str) -> bool:
        signal_score = strategy_signal_score(signal)
        final_score = strategy_signal_score(final_signal)
        if final_score == 3.0:
            return signal_score == 3.0
        return (
            (signal_score > 3.0 and final_score > 3.0)
            or (signal_score < 3.0 and final_score < 3.0)
        )

    @staticmethod
    def _summarize(
        agenda: List[DeliberationAgendaItem],
        responses: List[DeliberationResponse],
        conflicts: List[StrategyConflict],
        *,
        final_signal: str,
    ) -> DeliberationSummary:
        by_agenda: Dict[str, List[DeliberationResponse]] = {}
        for response in responses:
            by_agenda.setdefault(response.agenda_id, []).append(response)

        partially_resolved = any(
            item_responses
            and all(response.revision == "softened" for response in item_responses)
            for item_responses in by_agenda.values()
        )
        highest = _highest_severity(conflicts)
        if highest == "high":
            adjustment = -0.06 if partially_resolved else -0.08
            reason_key = (
                "deliberation.confidence.high_partially_resolved"
                if partially_resolved
                else "deliberation.confidence.high_unresolved_conflict"
            )
        elif highest == "medium":
            adjustment = -0.04 if partially_resolved else -0.05
            reason_key = (
                "deliberation.confidence.medium_partially_resolved"
                if partially_resolved
                else "deliberation.confidence.medium_unresolved_conflict"
            )
        else:
            adjustment = 0.0
            reason_key = ""

        final_score = strategy_signal_score(final_signal)
        minority_view_preserved = any(
            conflict.conflict_type == "high_confidence_dissent"
            for conflict in conflicts
        ) or any(
            response.original_confidence >= 0.75
            and abs(strategy_signal_score(response.original_signal) - final_score) >= 2.0
            for response in responses
        )

        return DeliberationSummary(
            resolution_status="partially_resolved" if partially_resolved else "unresolved",
            resolved_conflict_count=0,
            unresolved_conflict_count=len(agenda),
            minority_view_preserved=minority_view_preserved,
            confidence_adjustment=round(adjustment, 4),
            confidence_adjustment_reason_key=reason_key,
        )


class LLMDeliberationMediator:
    """Schema-guarded LLM mediator with deterministic mediator_v0 fallback."""

    def __init__(
        self,
        text_completion: Callable[[List[Dict[str, str]]], Any],
        *,
        fallback: Optional[DeliberationMediator] = None,
    ) -> None:
        self.text_completion = text_completion
        self.fallback = fallback or DeliberationMediator()

    def deliberate(
        self,
        opinions: List[StrategyOpinion],
        conflicts: List[StrategyConflict],
        *,
        final_signal: str,
    ) -> Optional[StrategyDeliberationResult]:
        baseline = self.fallback.deliberate(opinions, conflicts, final_signal=final_signal)
        if baseline is None:
            return None

        try:
            raw = self.text_completion(
                self._build_messages(
                    baseline,
                    opinions,
                    conflicts,
                    final_signal=final_signal,
                )
            )
            parsed = _parse_deliberation_json(raw)
            result = self._coerce_result(parsed, baseline)
            if result is None:
                return baseline
            return result
        except Exception as exc:
            logger.warning("[StrategyDeliberation] LLM mediator failed; falling back to mediator_v0: %s", exc)
            return baseline

    @staticmethod
    def _build_messages(
        baseline: StrategyDeliberationResult,
        opinions: List[StrategyOpinion],
        conflicts: List[StrategyConflict],
        *,
        final_signal: str,
    ) -> List[Dict[str, str]]:
        payload = {
            "final_signal": final_signal,
            "allowed_revisions": sorted(_DELIBERATION_ALLOWED_REVISIONS),
            "forbidden_revisions": ["reversed"],
            "baseline_deliberation": baseline.to_dict(),
            "opinions": [
                {
                    "skill_id": op.skill_id,
                    "signal": op.signal,
                    "confidence": round(op.confidence, 4),
                    "score_adjustment": op.score_adjustment,
                    "conditions_met": list(op.conditions_met or [])[:5],
                    "conditions_missed": list(op.conditions_missed or [])[:5],
                }
                for op in opinions
                if not op.invalid_signal
            ],
            "conflicts": [_conflict_to_dict(conflict) for conflict in conflicts],
        }
        system = (
            "You are a constrained strategy deliberation mediator. "
            "Return only one JSON object. Do not add prose. "
            "Do not change final_signal. Do not use reversed. "
            "Allowed response.revision values: unchanged, softened. "
            "Do not undo a baseline softened revision, restore its original signal, "
            "raise its revised confidence, or make the summary confidence adjustment less conservative."
        )
        user = (
            "Refine this strategy deliberation while preserving the schema and IDs. "
            "You may update response stance/revision/confidence/critique_key metadata "
            "and summary fields, but agenda IDs and participants must stay aligned.\n\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _coerce_result(
        payload: Optional[Dict[str, Any]],
        baseline: StrategyDeliberationResult,
    ) -> Optional[StrategyDeliberationResult]:
        if not isinstance(payload, dict):
            return None

        baseline_dict = baseline.to_dict()
        baseline_agenda = {
            item["agenda_id"]: item
            for item in baseline_dict["agenda"]
            if isinstance(item, dict) and item.get("agenda_id")
        }
        if not baseline_agenda:
            return None

        agenda_payload = payload.get("agenda")
        if not isinstance(agenda_payload, list):
            return None
        agenda = LLMDeliberationMediator._coerce_agenda(agenda_payload, baseline_agenda)
        if agenda is None:
            return None

        response_payload = payload.get("responses")
        if not isinstance(response_payload, list):
            return None
        responses = LLMDeliberationMediator._coerce_responses(
            response_payload,
            baseline,
            baseline_agenda,
        )
        if responses is None:
            return None

        summary_payload = payload.get("summary")
        if not isinstance(summary_payload, dict):
            return None
        summary = LLMDeliberationMediator._coerce_summary(summary_payload, baseline.summary)
        if summary is None:
            return None

        return StrategyDeliberationResult(
            status="completed",
            mode="llm_mediator_v1",
            rounds=1,
            agenda=agenda,
            responses=responses,
            summary=summary,
        )

    @staticmethod
    def _coerce_agenda(
        items: List[Any],
        baseline_agenda: Dict[str, Dict[str, Any]],
    ) -> Optional[List[DeliberationAgendaItem]]:
        coerced: List[DeliberationAgendaItem] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                return None
            agenda_id = str(item.get("agenda_id") or "").strip()
            baseline_item = baseline_agenda.get(agenda_id)
            if not baseline_item or agenda_id in seen:
                return None
            seen.add(agenda_id)
            coerced.append(
                DeliberationAgendaItem(
                    agenda_id=agenda_id,
                    conflict_type=str(baseline_item.get("conflict_type") or ""),
                    severity=str(baseline_item.get("severity") or "medium"),
                    participants=list(baseline_item.get("participants") or []),
                    question_key=str(item.get("question_key") or baseline_item.get("question_key") or ""),
                    metadata=_dict_or_empty(item.get("metadata")),
                )
            )
        if set(seen) != set(baseline_agenda):
            return None
        return coerced

    @staticmethod
    def _coerce_responses(
        items: List[Any],
        baseline: StrategyDeliberationResult,
        baseline_agenda: Dict[str, Dict[str, Any]],
    ) -> Optional[List[DeliberationResponse]]:
        baseline_responses = {
            (response.agenda_id, response.skill_id): response
            for response in baseline.responses
        }
        coerced: List[DeliberationResponse] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            if not isinstance(item, dict):
                return None
            agenda_id = str(item.get("agenda_id") or "").strip()
            skill_id = str(item.get("skill_id") or "").strip()
            key = (agenda_id, skill_id)
            baseline_response = baseline_responses.get(key)
            baseline_item = baseline_agenda.get(agenda_id)
            if baseline_response is None or baseline_item is None or key in seen:
                return None
            if skill_id not in set(baseline_item.get("participants") or []):
                return None
            seen.add(key)

            revision = str(item.get("revision") or baseline_response.revision).strip()
            if revision not in _DELIBERATION_ALLOWED_REVISIONS:
                return None
            if baseline_response.revision == "softened" and revision != "softened":
                return None
            original_signal = baseline_response.original_signal
            revised_signal = _coerce_revised_signal(
                item.get("revised_signal"),
                original_signal=original_signal,
                revision=revision,
            )
            if revised_signal is None:
                return None
            if (
                baseline_response.revision == "softened"
                and revised_signal != baseline_response.revised_signal
            ):
                return None
            revised_confidence = _coerce_revised_confidence(
                item.get("revised_confidence"),
                original=baseline_response.original_confidence,
                revision=revision,
            )
            if revised_confidence is None:
                return None
            if revised_confidence > baseline_response.revised_confidence + 0.0001:
                return None

            stance = str(item.get("stance") or baseline_response.stance).strip()
            if stance not in {"defend", "challenge"}:
                return None
            coerced.append(
                DeliberationResponse(
                    agenda_id=agenda_id,
                    skill_id=skill_id,
                    stance=stance,
                    revision=revision,
                    original_signal=original_signal,
                    revised_signal=revised_signal,
                    original_confidence=baseline_response.original_confidence,
                    revised_confidence=round(revised_confidence, 4),
                    critique_key=str(item.get("critique_key") or baseline_response.critique_key),
                    metadata=_dict_or_empty(item.get("metadata")),
                )
            )
        if set(seen) != set(baseline_responses):
            return None
        return coerced

    @staticmethod
    def _coerce_summary(
        payload: Dict[str, Any],
        baseline: DeliberationSummary,
    ) -> Optional[DeliberationSummary]:
        resolution_status = str(payload.get("resolution_status") or baseline.resolution_status).strip()
        if resolution_status not in _DELIBERATION_ALLOWED_RESOLUTION_STATUS:
            return None

        adjustment = _as_float(payload.get("confidence_adjustment"), baseline.confidence_adjustment)
        # Every mediated layer is monotonic relative to its validated baseline.
        if adjustment > baseline.confidence_adjustment + 0.0001:
            return None
        adjustment = max(-0.1, adjustment)

        resolved = _as_non_negative_int(payload.get("resolved_conflict_count"), baseline.resolved_conflict_count)
        unresolved = _as_non_negative_int(
            payload.get("unresolved_conflict_count"),
            baseline.unresolved_conflict_count,
        )
        minority = payload.get("minority_view_preserved", baseline.minority_view_preserved)
        if not isinstance(minority, bool):
            return None

        return DeliberationSummary(
            resolution_status=resolution_status,
            resolved_conflict_count=resolved,
            unresolved_conflict_count=unresolved,
            minority_view_preserved=minority,
            confidence_adjustment=round(adjustment, 4),
            confidence_adjustment_reason_key=str(
                payload.get("confidence_adjustment_reason_key")
                or baseline.confidence_adjustment_reason_key
            ),
        )


class StrategySelfReviewMediator:
    """Schema-guarded participant self-review mediator with fallback.

    v2 is the first contract layer that can ask conflict participants to review
    their own stance.  The callable is intentionally narrow and can be backed
    by a real strategy agent later:
    ``self_review(skill_id, messages) -> JSON/text response``.
    """

    def __init__(
        self,
        self_review: Callable[[str, List[Dict[str, str]]], Any],
        *,
        fallback: Optional[Any] = None,
    ) -> None:
        self.self_review = self_review
        self.fallback = fallback or DeliberationMediator()

    def deliberate(
        self,
        opinions: List[StrategyOpinion],
        conflicts: List[StrategyConflict],
        *,
        final_signal: str,
    ) -> Optional[StrategyDeliberationResult]:
        baseline = self.fallback.deliberate(opinions, conflicts, final_signal=final_signal)
        if baseline is None:
            return None

        by_skill = {op.skill_id: op for op in opinions if not op.invalid_signal and op.skill_id}
        baseline_dict = baseline.to_dict()
        agenda_by_id = {
            item["agenda_id"]: item
            for item in baseline_dict["agenda"]
            if isinstance(item, dict) and item.get("agenda_id")
        }
        response_payloads: List[Dict[str, Any]] = []

        try:
            for response in baseline.responses:
                agenda = agenda_by_id.get(response.agenda_id)
                opinion = by_skill.get(response.skill_id)
                if not isinstance(agenda, dict) or opinion is None:
                    return baseline
                raw = self.self_review(
                    response.skill_id,
                    self._build_messages(
                        response,
                        agenda,
                        opinion,
                        final_signal=final_signal,
                    ),
                )
                parsed = _parse_deliberation_json(raw)
                if not isinstance(parsed, dict):
                    return baseline
                response_payloads.append(parsed)

            responses = LLMDeliberationMediator._coerce_responses(
                response_payloads,
                baseline,
                agenda_by_id,
            )
            if responses is None:
                return baseline

            summary = DeliberationMediator._summarize(
                baseline.agenda,
                responses,
                conflicts,
                final_signal=final_signal,
            )
            if summary.confidence_adjustment > baseline.summary.confidence_adjustment + 0.0001:
                summary.confidence_adjustment = baseline.summary.confidence_adjustment
                summary.confidence_adjustment_reason_key = (
                    baseline.summary.confidence_adjustment_reason_key
                )
            return StrategyDeliberationResult(
                status="completed",
                mode="self_review_v2",
                rounds=1,
                agenda=list(baseline.agenda),
                responses=responses,
                summary=summary,
            )
        except Exception as exc:
            logger.warning("[StrategyDeliberation] self-review mediator failed; falling back: %s", exc)
            return baseline

    @staticmethod
    def _build_messages(
        baseline_response: DeliberationResponse,
        agenda: Dict[str, Any],
        opinion: StrategyOpinion,
        *,
        final_signal: str,
    ) -> List[Dict[str, str]]:
        payload = {
            "final_signal": final_signal,
            "allowed_revisions": sorted(_DELIBERATION_ALLOWED_REVISIONS),
            "forbidden_revisions": ["reversed"],
            "agenda": agenda,
            "baseline_response": asdict(baseline_response),
            "self_opinion": {
                "skill_id": opinion.skill_id,
                "signal": opinion.signal,
                "confidence": round(opinion.confidence, 4),
                "reasoning": opinion.reasoning,
                "score_adjustment": opinion.score_adjustment,
                "conditions_met": list(opinion.conditions_met or [])[:5],
                "conditions_missed": list(opinion.conditions_missed or [])[:5],
            },
        }
        system = (
            "You are reviewing only your own strategy opinion for one conflict agenda. "
            "Return one JSON object matching baseline_response. "
            "Allowed revision values are unchanged and softened. Never use reversed. "
            "Do not change agenda_id, skill_id, original_signal, or final_signal. "
            "Do not undo a baseline softened revision, restore its original signal, "
            "or raise its revised confidence."
        )
        user = (
            "Return your self-review response. You may adjust stance, revision, "
            "revised_signal, revised_confidence, critique_key, and metadata only within "
            "the allowed schema.\n\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]


class MultiRoundDeliberationMediator:
    """Configurable schema-guarded multi-round deliberation mediator.

    v4 keeps the same safety contract as earlier mediators: it can only refine
    already structured responses, cannot reverse a signal, and cannot overwrite
    the final synthesis signal.
    """

    def __init__(
        self,
        round_completion: Callable[[int, List[Dict[str, str]]], Any],
        *,
        fallback: Optional[Any] = None,
        max_rounds: int = 2,
        stop_when_stable: bool = True,
    ) -> None:
        self.round_completion = round_completion
        self.fallback = fallback or DeliberationMediator()
        self.max_rounds = _clamp_int(max_rounds, minimum=1, maximum=4)
        self.stop_when_stable = bool(stop_when_stable)

    def deliberate(
        self,
        opinions: List[StrategyOpinion],
        conflicts: List[StrategyConflict],
        *,
        final_signal: str,
    ) -> Optional[StrategyDeliberationResult]:
        current = self.fallback.deliberate(opinions, conflicts, final_signal=final_signal)
        if current is None or self.max_rounds <= current.rounds:
            return current

        accepted_rounds = 0
        history = [
            {
                "round": current.rounds or 1,
                "source_mode": current.mode,
                "status": "baseline",
                "changed_response_count": _changed_response_count(current.responses),
                "confidence_adjustment": current.summary.confidence_adjustment,
            }
        ]

        try:
            for round_index in range((current.rounds or 1) + 1, self.max_rounds + 1):
                raw = self.round_completion(
                    round_index,
                    self._build_messages(
                        current,
                        opinions,
                        conflicts,
                        final_signal=final_signal,
                        round_index=round_index,
                    ),
                )
                parsed = _parse_deliberation_json(raw)
                next_result = self._coerce_round_result(parsed, current)
                if next_result is None:
                    break

                changed_count = _round_changed_response_count(current.responses, next_result.responses)
                current = StrategyDeliberationResult(
                    status="completed",
                    mode="multi_round_v4",
                    rounds=round_index,
                    agenda=next_result.agenda,
                    responses=next_result.responses,
                    summary=next_result.summary,
                )
                accepted_rounds += 1
                history.append({
                    "round": round_index,
                    "source_mode": "multi_round_v4",
                    "status": "accepted",
                    "changed_response_count": changed_count,
                    "confidence_adjustment": current.summary.confidence_adjustment,
                })
                if self.stop_when_stable and changed_count == 0:
                    break
        except Exception as exc:
            logger.warning("[StrategyDeliberation] multi-round mediator failed; using last valid round: %s", exc)

        if accepted_rounds == 0:
            return current
        current.round_history = history
        return current

    @staticmethod
    def _build_messages(
        current: StrategyDeliberationResult,
        opinions: List[StrategyOpinion],
        conflicts: List[StrategyConflict],
        *,
        final_signal: str,
        round_index: int,
    ) -> List[Dict[str, str]]:
        payload = {
            "final_signal": final_signal,
            "round_index": round_index,
            "allowed_revisions": sorted(_DELIBERATION_ALLOWED_REVISIONS),
            "forbidden_revisions": ["reversed"],
            "current_deliberation": current.to_dict(),
            "opinions": [
                {
                    "skill_id": op.skill_id,
                    "signal": op.signal,
                    "confidence": round(op.confidence, 4),
                    "score_adjustment": op.score_adjustment,
                    "conditions_met": list(op.conditions_met or [])[:5],
                    "conditions_missed": list(op.conditions_missed or [])[:5],
                }
                for op in opinions
                if not op.invalid_signal
            ],
            "conflicts": [_conflict_to_dict(conflict) for conflict in conflicts],
        }
        system = (
            "You are a constrained multi-round strategy deliberation mediator. "
            "Return only one JSON object. Do not add prose. Do not change final_signal. "
            "Do not use reversed. Do not add or remove agenda/responses. "
            "Do not undo a previous softened revision or raise revised confidence."
        )
        user = (
            "Refine the current deliberation for the next round while preserving "
            "the schema and IDs. You may keep responses unchanged or further "
            "soften confidence within the allowed schema.\n\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _coerce_round_result(
        payload: Optional[Dict[str, Any]],
        previous: StrategyDeliberationResult,
    ) -> Optional[StrategyDeliberationResult]:
        if not isinstance(payload, dict):
            return None

        previous_dict = previous.to_dict()
        previous_agenda = {
            item["agenda_id"]: item
            for item in previous_dict["agenda"]
            if isinstance(item, dict) and item.get("agenda_id")
        }
        if not previous_agenda:
            return None

        agenda_payload = payload.get("agenda")
        if not isinstance(agenda_payload, list):
            return None
        agenda = LLMDeliberationMediator._coerce_agenda(agenda_payload, previous_agenda)
        if agenda is None:
            return None

        response_payload = payload.get("responses")
        if not isinstance(response_payload, list):
            return None
        responses = MultiRoundDeliberationMediator._coerce_round_responses(
            response_payload,
            previous,
            previous_agenda,
        )
        if responses is None:
            return None

        summary_payload = payload.get("summary")
        if not isinstance(summary_payload, dict):
            return None
        summary = LLMDeliberationMediator._coerce_summary(summary_payload, previous.summary)
        if summary is None:
            return None
        if summary.confidence_adjustment > previous.summary.confidence_adjustment + 0.0001:
            return None

        return StrategyDeliberationResult(
            status="completed",
            mode="multi_round_v4",
            rounds=previous.rounds + 1,
            agenda=agenda,
            responses=responses,
            summary=summary,
        )

    @staticmethod
    def _coerce_round_responses(
        items: List[Any],
        previous: StrategyDeliberationResult,
        previous_agenda: Dict[str, Dict[str, Any]],
    ) -> Optional[List[DeliberationResponse]]:
        return LLMDeliberationMediator._coerce_responses(
            items,
            previous,
            previous_agenda,
        )


def _highest_severity(conflicts: List[StrategyConflict]) -> str:
    if not conflicts:
        return "none"
    return max((conflict.severity for conflict in conflicts), key=lambda severity: _SEVERITY_RANK.get(severity, 0))


def _unique_strings(values: Any) -> List[str]:
    result: List[str] = []
    for value in values or []:
        if value and value not in result:
            result.append(value)
    return result


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _clamp_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    return max(minimum, min(maximum, parsed))


def _changed_response_count(responses: List[DeliberationResponse]) -> int:
    return sum(1 for response in responses if response.revision == "softened")


def _round_changed_response_count(
    previous: List[DeliberationResponse],
    current: List[DeliberationResponse],
) -> int:
    previous_by_key = {
        (response.agenda_id, response.skill_id): response
        for response in previous
    }
    changed = 0
    for response in current:
        previous_response = previous_by_key.get((response.agenda_id, response.skill_id))
        if previous_response is None:
            continue
        if (
            response.revision != previous_response.revision
            or response.revised_signal != previous_response.revised_signal
            or abs(response.revised_confidence - previous_response.revised_confidence) > 0.0001
            or response.critique_key != previous_response.critique_key
        ):
            changed += 1
    return changed


def _dict_or_empty(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _conflict_to_dict(conflict: StrategyConflict) -> Dict[str, Any]:
    payload = asdict(conflict)
    payload.pop("description", None)
    return payload


def _parse_deliberation_json(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, dict):
        return raw
    content = getattr(raw, "content", raw)
    if not isinstance(content, str):
        return None
    candidates: List[str] = []
    stripped = content.strip()
    if stripped:
        candidates.append(stripped)
    if stripped.startswith("```"):
        unfenced = re.sub(r'^```(?:json)?\s*', '', stripped)
        unfenced = re.sub(r'\s*```$', '', unfenced)
        if unfenced.strip():
            candidates.append(unfenced.strip())
    for block in re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL):
        if block.strip():
            candidates.append(block.strip())
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        candidates.append(content[start:end + 1].strip())

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _coerce_revised_signal(value: Any, *, original_signal: str, revision: str) -> Optional[str]:
    candidate = str(value or original_signal).strip()
    signal, invalid, _ = normalize_strategy_signal(candidate)
    if invalid:
        return None
    if revision == "unchanged":
        return original_signal if signal == original_signal else None
    if revision == "softened":
        return signal if signal == DeliberationMediator._softened_signal(original_signal) else None
    return None


def _coerce_revised_confidence(value: Any, *, original: float, revision: str) -> Optional[float]:
    confidence = _as_float(value, original)
    if confidence < 0 or confidence > 1:
        return None
    if revision == "unchanged" and abs(confidence - original) > 0.0001:
        return None
    if revision == "softened" and confidence > original + 0.0001:
        return None
    return confidence
