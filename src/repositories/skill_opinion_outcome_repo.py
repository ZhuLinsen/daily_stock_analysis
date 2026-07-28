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


@dataclass(frozen=True)
class SkillOpinionPerformanceBucket:
    """Raw persisted counts for one skill, horizon, and engine version."""

    skill_id: str
    horizon: str
    engine_version: str
    total: int
    pending: int
    evaluated: int
    observational: int
    unable: int
    hit: int
    miss: int
    avg_directional_return_pct: Optional[float]


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
                self._candidate_time(item),
                int(item.sample.id),
                horizon_rank[item.horizon],
                item.existing_outcome is not None,
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

    def list_performance_buckets(
        self,
        *,
        engine_version: str,
        skill_id: Optional[str] = None,
        horizons: Optional[Sequence[str]] = None,
    ) -> List[SkillOpinionPerformanceBucket]:
        """Aggregate persisted outcome facts without applying sample policy."""

        status = SkillOpinionOutcomeRecord.eval_status
        outcome = SkillOpinionOutcomeRecord.outcome
        conditions = [
            SkillOpinionOutcomeRecord.engine_version == engine_version
        ]
        if skill_id is not None:
            conditions.append(SkillOpinionSampleRecord.skill_id == skill_id)
        if horizons is not None:
            conditions.append(
                SkillOpinionOutcomeRecord.horizon.in_(list(horizons))
            )
        with self.db.get_session() as session:
            rows = session.execute(
                select(
                    SkillOpinionSampleRecord.skill_id,
                    SkillOpinionOutcomeRecord.horizon,
                    SkillOpinionOutcomeRecord.engine_version,
                    func.count(SkillOpinionOutcomeRecord.id),
                    func.sum(case((status == "pending", 1), else_=0)),
                    func.sum(case((status == "evaluated", 1), else_=0)),
                    func.sum(case((status == "observational", 1), else_=0)),
                    func.sum(case((status == "unable", 1), else_=0)),
                    func.sum(case((outcome == "hit", 1), else_=0)),
                    func.sum(case((outcome == "miss", 1), else_=0)),
                    func.avg(
                        case(
                            (
                                status == "evaluated",
                                SkillOpinionOutcomeRecord.directional_return_pct,
                            ),
                            else_=None,
                        )
                    ),
                )
                .join(
                    SkillOpinionSampleRecord,
                    SkillOpinionSampleRecord.id
                    == SkillOpinionOutcomeRecord.skill_opinion_sample_id,
                )
                .where(and_(*conditions))
                .group_by(
                    SkillOpinionSampleRecord.skill_id,
                    SkillOpinionOutcomeRecord.horizon,
                    SkillOpinionOutcomeRecord.engine_version,
                )
            ).all()

        return [
            SkillOpinionPerformanceBucket(
                skill_id=str(row[0]),
                horizon=str(row[1]),
                engine_version=str(row[2]),
                total=int(row[3] or 0),
                pending=int(row[4] or 0),
                evaluated=int(row[5] or 0),
                observational=int(row[6] or 0),
                unable=int(row[7] or 0),
                hit=int(row[8] or 0),
                miss=int(row[9] or 0),
                avg_directional_return_pct=(
                    float(row[10]) if row[10] is not None else None
                ),
            )
            for row in rows
        ]

    @staticmethod
    def _candidate_time(candidate: SkillOpinionOutcomeCandidate) -> datetime:
        outcome = candidate.existing_outcome
        return (
            (outcome.updated_at if outcome is not None else None)
            or candidate.sample.created_at
            or datetime.min
        )
