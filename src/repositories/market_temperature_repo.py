# -*- coding: utf-8 -*-
"""Market temperature snapshot repository for the master toolkit feature set."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc, func, select

from src.storage import (
    DatabaseManager,
    MarketTemperatureSnapshot,
    to_utc_naive_datetime,
    utc_naive_now,
)


class MarketTemperatureRepository:
    """DB access layer for persisted market temperature snapshots."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def upsert(self, fields: Dict[str, Any]) -> MarketTemperatureSnapshot:
        fields = self._normalize_datetime_fields(fields)
        with self.db.get_session() as session:
            existing = session.execute(
                select(MarketTemperatureSnapshot)
                .where(
                    MarketTemperatureSnapshot.market == fields["market"],
                    MarketTemperatureSnapshot.trade_date == fields["trade_date"],
                )
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                for key, value in fields.items():
                    if key in ("id", "created_at"):
                        continue
                    setattr(existing, key, value)
                session.commit()
                session.refresh(existing)
                return existing
            row = MarketTemperatureSnapshot(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def get(self, snapshot_id: int) -> Optional[MarketTemperatureSnapshot]:
        with self.db.get_session() as session:
            return session.execute(
                select(MarketTemperatureSnapshot)
                .where(MarketTemperatureSnapshot.id == snapshot_id)
                .limit(1)
            ).scalar_one_or_none()

    def get_latest(self, market: str) -> Optional[MarketTemperatureSnapshot]:
        with self.db.get_session() as session:
            return session.execute(
                select(MarketTemperatureSnapshot)
                .where(MarketTemperatureSnapshot.market == market)
                .order_by(
                    desc(MarketTemperatureSnapshot.trade_date),
                    desc(MarketTemperatureSnapshot.id),
                )
                .limit(1)
            ).scalar_one_or_none()

    def list(
        self,
        *,
        market: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[MarketTemperatureSnapshot], int]:
        conditions = []
        if market:
            conditions.append(MarketTemperatureSnapshot.market == market)
        where_clause = and_(*conditions) if conditions else True
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        offset = (safe_page - 1) * safe_page_size

        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(MarketTemperatureSnapshot.id))
                .select_from(MarketTemperatureSnapshot)
                .where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(MarketTemperatureSnapshot)
                .where(where_clause)
                .order_by(
                    desc(MarketTemperatureSnapshot.trade_date),
                    desc(MarketTemperatureSnapshot.id),
                )
                .offset(offset)
                .limit(safe_page_size)
            ).scalars().all()
            return list(rows), int(total)

    def _normalize_datetime_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(fields)
        if isinstance(result.get("created_at"), datetime):
            result["created_at"] = to_utc_naive_datetime(result["created_at"])
        return result
