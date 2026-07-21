# -*- coding: utf-8 -*-
"""Repository for immutable skill opinion samples."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.storage import DatabaseManager, SkillOpinionSampleRecord


class SkillOpinionSampleRepository:
    """Persist low-sensitivity samples without mutating an existing sample."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def insert_missing(self, rows: Iterable[Dict[str, Any]]) -> int:
        values = list(rows)
        if not values:
            return 0

        statement = sqlite_insert(SkillOpinionSampleRecord).values(values)
        statement = statement.on_conflict_do_nothing(
            index_elements=[
                "analysis_history_id",
                "skill_id",
                "sample_schema_version",
            ]
        )
        with self.db.session_scope() as session:
            result = session.execute(statement)
            return result.rowcount or 0

    def list_for_history(self, analysis_history_id: int) -> List[SkillOpinionSampleRecord]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(SkillOpinionSampleRecord)
                .where(SkillOpinionSampleRecord.analysis_history_id == analysis_history_id)
                .order_by(SkillOpinionSampleRecord.id)
            ).scalars().all()
            return list(rows)
