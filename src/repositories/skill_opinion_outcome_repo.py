# -*- coding: utf-8 -*-
"""Repository for per-sample skill opinion forward outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, case, desc, func, select

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

        safe_limit = max(1, min(int(limit), 500))
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
                if skill_id:
                    conditions.append(SkillOpinionSampleRecord.skill_id == skill_id)
                if stock_code:
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
                    .limit(safe_limit)
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
        return candidates[:safe_limit]

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

    def list_outcomes(
        self,
        *,
        sample_id: Optional[int] = None,
        analysis_history_id: Optional[int] = None,
        skill_id: Optional[str] = None,
        stock_code: Optional[str] = None,
        horizon: Optional[str] = None,
        engine_version: Optional[str] = None,
        eval_status: Optional[str] = None,
        outcome: Optional[str] = None,
        offset: int = 0,
        limit: int = 100,
    ) -> List[Tuple[SkillOpinionOutcomeRecord, SkillOpinionSampleRecord]]:
        conditions = []
        if sample_id is not None:
            conditions.append(SkillOpinionSampleRecord.id == sample_id)
        if analysis_history_id is not None:
            conditions.append(
                SkillOpinionSampleRecord.analysis_history_id == analysis_history_id
            )
        if skill_id:
            conditions.append(SkillOpinionSampleRecord.skill_id == skill_id)
        if stock_code:
            conditions.append(SkillOpinionSampleRecord.stock_code == stock_code)
        if horizon:
            conditions.append(SkillOpinionOutcomeRecord.horizon == horizon)
        if engine_version:
            conditions.append(SkillOpinionOutcomeRecord.engine_version == engine_version)
        if eval_status:
            conditions.append(SkillOpinionOutcomeRecord.eval_status == eval_status)
        if outcome:
            conditions.append(SkillOpinionOutcomeRecord.outcome == outcome)

        query = (
            select(SkillOpinionOutcomeRecord, SkillOpinionSampleRecord)
            .join(
                SkillOpinionSampleRecord,
                SkillOpinionSampleRecord.id
                == SkillOpinionOutcomeRecord.skill_opinion_sample_id,
            )
            .order_by(
                desc(SkillOpinionOutcomeRecord.updated_at),
                desc(SkillOpinionOutcomeRecord.id),
            )
            .offset(max(0, int(offset)))
            .limit(max(1, min(int(limit), 500)))
        )
        if conditions:
            query = query.where(and_(*conditions))
        with self.db.get_session() as session:
            return list(session.execute(query).all())

    def count_outcomes(
        self,
        *,
        sample_id: Optional[int] = None,
        analysis_history_id: Optional[int] = None,
        skill_id: Optional[str] = None,
        stock_code: Optional[str] = None,
        horizon: Optional[str] = None,
        engine_version: Optional[str] = None,
        eval_status: Optional[str] = None,
        outcome: Optional[str] = None,
    ) -> int:
        conditions = []
        if sample_id is not None:
            conditions.append(SkillOpinionSampleRecord.id == sample_id)
        if analysis_history_id is not None:
            conditions.append(
                SkillOpinionSampleRecord.analysis_history_id == analysis_history_id
            )
        if skill_id:
            conditions.append(SkillOpinionSampleRecord.skill_id == skill_id)
        if stock_code:
            conditions.append(SkillOpinionSampleRecord.stock_code == stock_code)
        if horizon:
            conditions.append(SkillOpinionOutcomeRecord.horizon == horizon)
        if engine_version:
            conditions.append(SkillOpinionOutcomeRecord.engine_version == engine_version)
        if eval_status:
            conditions.append(SkillOpinionOutcomeRecord.eval_status == eval_status)
        if outcome:
            conditions.append(SkillOpinionOutcomeRecord.outcome == outcome)

        query = (
            select(func.count(SkillOpinionOutcomeRecord.id))
            .select_from(SkillOpinionOutcomeRecord)
            .join(
                SkillOpinionSampleRecord,
                SkillOpinionSampleRecord.id
                == SkillOpinionOutcomeRecord.skill_opinion_sample_id,
            )
        )
        if conditions:
            query = query.where(and_(*conditions))
        with self.db.get_session() as session:
            return int(session.execute(query).scalar() or 0)

    @staticmethod
    def _candidate_time(candidate: SkillOpinionOutcomeCandidate) -> datetime:
        outcome = candidate.existing_outcome
        return (
            (outcome.updated_at if outcome is not None else None)
            or candidate.sample.created_at
            or datetime.min
        )
