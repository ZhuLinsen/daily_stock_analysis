# -*- coding: utf-8 -*-
"""Trade journal repository for the master toolkit feature set."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, asc, desc, func, select

from src.storage import (
    DatabaseManager,
    TradeJournalEntry,
    to_utc_naive_datetime,
    utc_naive_now,
)


class TradeJournalRepository:
    """DB access layer for personal trade journal entries."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def create(self, fields: Dict[str, Any]) -> TradeJournalEntry:
        fields = self._normalize_datetime_fields(fields)
        with self.db.get_session() as session:
            row = TradeJournalEntry(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def get(self, entry_id: int) -> Optional[TradeJournalEntry]:
        with self.db.get_session() as session:
            return session.execute(
                select(TradeJournalEntry).where(TradeJournalEntry.id == entry_id).limit(1)
            ).scalar_one_or_none()

    def update(self, entry_id: int, fields: Dict[str, Any]) -> Optional[TradeJournalEntry]:
        fields = self._normalize_datetime_fields(fields)
        fields.pop("id", None)
        fields.pop("created_at", None)
        with self.db.get_session() as session:
            row = session.execute(
                select(TradeJournalEntry).where(TradeJournalEntry.id == entry_id).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = utc_naive_now()
            session.commit()
            session.refresh(row)
            return row

    def delete(self, entry_id: int) -> bool:
        with self.db.get_session() as session:
            row = session.execute(
                select(TradeJournalEntry).where(TradeJournalEntry.id == entry_id).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def list(
        self,
        *,
        market: Optional[str] = None,
        code: Optional[str] = None,
        side: Optional[str] = None,
        strategy: Optional[str] = None,
        emotion: Optional[str] = None,
        trade_date_from: Optional[date] = None,
        trade_date_to: Optional[date] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[TradeJournalEntry], int]:
        conditions = []
        if market:
            conditions.append(TradeJournalEntry.market == market)
        if code:
            conditions.append(TradeJournalEntry.code == code)
        if side:
            conditions.append(TradeJournalEntry.side == side)
        if strategy:
            conditions.append(TradeJournalEntry.strategy == strategy)
        if emotion:
            conditions.append(TradeJournalEntry.emotion == emotion)
        if trade_date_from:
            conditions.append(TradeJournalEntry.trade_date >= trade_date_from)
        if trade_date_to:
            conditions.append(TradeJournalEntry.trade_date <= trade_date_to)

        where_clause = and_(*conditions) if conditions else True
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        offset = (safe_page - 1) * safe_page_size

        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(TradeJournalEntry.id))
                .select_from(TradeJournalEntry)
                .where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(TradeJournalEntry)
                .where(where_clause)
                .order_by(desc(TradeJournalEntry.trade_date), desc(TradeJournalEntry.id))
                .offset(offset)
                .limit(safe_page_size)
            ).scalars().all()
            return list(rows), int(total)

    def list_by_code_market(
        self,
        *,
        market: str,
        code: str,
        side: Optional[str] = None,
    ) -> List[TradeJournalEntry]:
        """Return all entries for one position ordered by (trade_date, id) for FIFO matching."""
        conditions = [
            TradeJournalEntry.market == market,
            TradeJournalEntry.code == code,
        ]
        if side:
            conditions.append(TradeJournalEntry.side == side)
        with self.db.get_session() as session:
            rows = session.execute(
                select(TradeJournalEntry)
                .where(and_(*conditions))
                .order_by(asc(TradeJournalEntry.trade_date), asc(TradeJournalEntry.id))
            ).scalars().all()
            return list(rows)

    def list_distinct_emotions(self) -> List[str]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(TradeJournalEntry.emotion)
                .where(TradeJournalEntry.emotion.is_not(None))
                .distinct()
            ).scalars().all()
            return [str(r) for r in rows if r]

    def _normalize_datetime_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(fields)
        for key in ("created_at", "updated_at"):
            if key in result and isinstance(result[key], datetime):
                result[key] = to_utc_naive_datetime(result[key])
        return result
