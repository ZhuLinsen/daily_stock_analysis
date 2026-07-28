# -*- coding: utf-8 -*-
"""Repository for per-sample skill opinion forward outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, case, func, select

from src.storage import (
    AnalysisHistory,
    DatabaseManager,
    SkillOpinionOutcomeRecord,
    SkillOpinionSampleRecord,
    utc_naive_now,
)


_TERMINAL_EVAL_STATUSES = frozenset({"evaluated", "observational", "unable"})


@dataclass(frozen=True)
class SkillOpinionOutcomeCandidate:
    sample: SkillOpinionSampleRecord
    history: AnalysisHistory
    horizon: str
    existing_outcome: Optional[SkillOpinionOutcomeRecord]


class SkillOpinionOutcomeRepository:
    """Read candidates and persist outcomes through the shared write guard."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def list_candidate_keys(
        self,
        *,
        horizons: Sequence[str],
        engine_version: str,
        limit: int,
        sample_id: Optional[int] = None,
        analysis_history_id: Optional[int] = None,
        skill_id: Optional[str] = None,
        stock_code: Optional[str] = None,
    ) -> List[SkillOpinionOutcomeCandidate]:
        """Return at most ``limit`` missing or pending sample-by-horizon keys."""

        candidates: List[SkillOpinionOutcomeCandidate] = []
        with self.db.get_session() as session:
            for horizon in horizons:
                join_condition = and_(
                    SkillOpinionOutcomeRecord.skill_opinion_sample_id
                    == SkillOpinionSampleRecord.id,
                    SkillOpinionOutcomeRecord.horizon == horizon,
                    SkillOpinionOutcomeRecord.engine_version == engine_version,
                )
                conditions = [
                    (
                        SkillOpinionOutcomeRecord.id.is_(None)
                        | (SkillOpinionOutcomeRecord.eval_status == "pending")
                    )
                ]
                if sample_id is not None:
                    conditions.append(SkillOpinionSampleRecord.id == sample_id)
                if analysis_history_id is not None:
                    conditions.append(
                        SkillOpinionSampleRecord.analysis_history_id == analysis_history_id
                    )
                if skill_id is not None:
                    conditions.append(SkillOpinionSampleRecord.skill_id == skill_id)
                if stock_code is not None:
                    conditions.append(SkillOpinionSampleRecord.stock_code == stock_code)

                rows = session.execute(
                    select(
                        SkillOpinionSampleRecord,
                        AnalysisHistory,
                        SkillOpinionOutcomeRecord,
                    )
                    .join(
                        AnalysisHistory,
                        AnalysisHistory.id == SkillOpinionSampleRecord.analysis_history_id,
                    )
                    .outerjoin(SkillOpinionOutcomeRecord, join_condition)
                    .where(and_(*conditions))
                    .order_by(
                        case(
                            (SkillOpinionOutcomeRecord.id.is_(None), 0),
                            else_=1,
                        ),
                        func.coalesce(
                            SkillOpinionOutcomeRecord.updated_at,
                            SkillOpinionSampleRecord.created_at,
                        ),
                        SkillOpinionSampleRecord.id,
                    )
                    .limit(limit)
                ).all()
                candidates.extend(
                    SkillOpinionOutcomeCandidate(
                        sample=sample,
                        history=history,
                        horizon=horizon,
                        existing_outcome=outcome,
                    )
                    for sample, history, outcome in rows
                )

        horizon_rank = {horizon: index for index, horizon in enumerate(horizons)}
        candidates.sort(
            key=lambda item: (
                item.existing_outcome is not None,
                self._candidate_time(item),
                int(item.sample.id),
                horizon_rank[item.horizon],
            )
        )
        return candidates[:limit]

    def persist_outcome(self, fields: Dict[str, Any]) -> Tuple[Optional[int], str]:
        """Insert a missing key or update pending; never overwrite terminal rows."""

        def _write(session) -> Tuple[Optional[int], str]:
            sample_id = int(fields["skill_opinion_sample_id"])
            sample_exists = session.execute(
                select(SkillOpinionSampleRecord.id)
                .where(SkillOpinionSampleRecord.id == sample_id)
                .limit(1)
            ).scalar_one_or_none()
            if sample_exists is None:
                return None, "missing_sample"

            existing = session.execute(
                select(SkillOpinionOutcomeRecord)
                .where(
                    SkillOpinionOutcomeRecord.skill_opinion_sample_id == sample_id,
                    SkillOpinionOutcomeRecord.horizon == fields["horizon"],
                    SkillOpinionOutcomeRecord.engine_version == fields["engine_version"],
                )
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None and existing.eval_status in _TERMINAL_EVAL_STATUSES:
                return int(existing.id), "skipped"

            if existing is None:
                row = SkillOpinionOutcomeRecord(**fields)
                session.add(row)
                session.flush()
                return int(row.id), "created"

            for key, value in fields.items():
                if key in {
                    "id",
                    "skill_opinion_sample_id",
                    "horizon",
                    "engine_version",
                    "created_at",
                }:
                    continue
                setattr(existing, key, value)
            existing.updated_at = utc_naive_now()
            session.flush()
            return int(existing.id), "updated"

        return self.db._run_write_transaction(
            "persist skill opinion outcome",
            _write,
        )

    def get_outcome(
        self,
        *,
        sample_id: int,
        horizon: str,
        engine_version: str,
    ) -> Optional[SkillOpinionOutcomeRecord]:
        with self.db.get_session() as session:
            return session.execute(
                select(SkillOpinionOutcomeRecord)
                .where(
                    SkillOpinionOutcomeRecord.skill_opinion_sample_id == sample_id,
                    SkillOpinionOutcomeRecord.horizon == horizon,
                    SkillOpinionOutcomeRecord.engine_version == engine_version,
                )
                .limit(1)
            ).scalar_one_or_none()

    @staticmethod
    def _candidate_time(candidate: SkillOpinionOutcomeCandidate) -> datetime:
        outcome = candidate.existing_outcome
        return (
            (outcome.updated_at if outcome is not None else None)
            or candidate.sample.created_at
            or datetime.min
        )
