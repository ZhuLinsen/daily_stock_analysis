# -*- coding: utf-8 -*-
"""Master debate record repository for the master toolkit feature set."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc, func, select

from src.storage import (
    DatabaseManager,
    MasterDebateRecord,
    to_utc_naive_datetime,
    utc_naive_now,
)


class MasterDebateRepository:
    """DB access layer for persisted master debate records."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def create(self, fields: Dict[str, Any]) -> MasterDebateRecord:
        fields = self._normalize_datetime_fields(fields)
        with self.db.get_session() as session:
            row = MasterDebateRecord(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def get(self, record_id: int) -> Optional[MasterDebateRecord]:
        with self.db.get_session() as session:
            return session.execute(
                select(MasterDebateRecord).where(MasterDebateRecord.id == record_id).limit(1)
            ).scalar_one_or_none()

    def list(
        self,
        *,
        market: Optional[str] = None,
        code: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[MasterDebateRecord], int]:
        conditions = []
        if market:
            conditions.append(MasterDebateRecord.market == market)
        if code:
            conditions.append(MasterDebateRecord.code == code)
        where_clause = and_(*conditions) if conditions else True
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        offset = (safe_page - 1) * safe_page_size

        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(MasterDebateRecord.id))
                .select_from(MasterDebateRecord)
                .where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(MasterDebateRecord)
                .where(where_clause)
                .order_by(desc(MasterDebateRecord.created_at), desc(MasterDebateRecord.id))
                .offset(offset)
                .limit(safe_page_size)
            ).scalars().all()
            return list(rows), int(total)

    def _normalize_datetime_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(fields)
        if isinstance(result.get("created_at"), datetime):
            result["created_at"] = to_utc_naive_datetime(result["created_at"])
        return result
