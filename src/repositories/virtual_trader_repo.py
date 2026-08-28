# -*- coding: utf-8 -*-
"""Virtual trader repository: DB access for accounts, trades, predictions, snapshots, runs."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, asc, desc, func, select

from src.storage import (
    DatabaseManager,
    VirtualTraderAccount,
    VirtualTraderPosition,
    VirtualTraderPrediction,
    VirtualTraderRun,
    VirtualTraderSnapshot,
    VirtualTraderTrade,
    utc_naive_now,
)


class VirtualTraderRepository:
    """DB access layer for the virtual trader feature."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------
    def get_account(self, name: str = "default") -> Optional[VirtualTraderAccount]:
        with self.db.get_session() as session:
            return session.execute(
                select(VirtualTraderAccount)
                .where(VirtualTraderAccount.name == name)
                .limit(1)
            ).scalar_one_or_none()

    def create_account(self, fields: Dict[str, Any]) -> VirtualTraderAccount:
        with self.db.get_session() as session:
            row = VirtualTraderAccount(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def update_account(
        self, account_id: int, fields: Dict[str, Any]
    ) -> Optional[VirtualTraderAccount]:
        fields = dict(fields)
        fields.pop("id", None)
        fields.pop("created_at", None)
        with self.db.get_session() as session:
            row = session.execute(
                select(VirtualTraderAccount)
                .where(VirtualTraderAccount.id == account_id)
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = utc_naive_now()
            session.commit()
            session.refresh(row)
            return row

    def delete_all(self, account_id: Optional[int] = None) -> int:
        """Delete virtual trader data. account_id=None wipes the whole feature."""
        with self.db.get_session() as session:
            removed = 0
            account_filter = (
                VirtualTraderPrediction.account_id == account_id
                if account_id is not None
                else True
            )
            for row in session.execute(
                select(VirtualTraderPrediction).where(account_filter)
            ).scalars().all():
                session.delete(row)
                removed += 1
            trade_filter = (
                VirtualTraderTrade.account_id == account_id
                if account_id is not None
                else True
            )
            for row in session.execute(
                select(VirtualTraderTrade).where(trade_filter)
            ).scalars().all():
                session.delete(row)
                removed += 1
            position_filter = (
                VirtualTraderPosition.account_id == account_id
                if account_id is not None
                else True
            )
            for row in session.execute(
                select(VirtualTraderPosition).where(position_filter)
            ).scalars().all():
                session.delete(row)
                removed += 1
            snapshot_filter = (
                VirtualTraderSnapshot.account_id == account_id
                if account_id is not None
                else True
            )
            for row in session.execute(
                select(VirtualTraderSnapshot).where(snapshot_filter)
            ).scalars().all():
                session.delete(row)
                removed += 1
            if account_id is None:
                for row in session.execute(select(VirtualTraderAccount)).scalars().all():
                    session.delete(row)
                    removed += 1
            session.commit()
            return removed

    # ------------------------------------------------------------------
    # Position
    # ------------------------------------------------------------------
    def get_open_position(
        self, account_id: int, stock_code: str
    ) -> Optional[VirtualTraderPosition]:
        with self.db.get_session() as session:
            return session.execute(
                select(VirtualTraderPosition).where(
                    and_(
                        VirtualTraderPosition.account_id == account_id,
                        VirtualTraderPosition.stock_code == stock_code,
                        VirtualTraderPosition.status == 'open',
                    )
                ).limit(1)
            ).scalar_one_or_none()

    def list_open_positions(
        self, account_id: int, market: Optional[str] = None
    ) -> List[VirtualTraderPosition]:
        conditions = [
            VirtualTraderPosition.account_id == account_id,
            VirtualTraderPosition.status == 'open',
        ]
        if market:
            conditions.append(VirtualTraderPosition.market == market)
        with self.db.get_session() as session:
            rows = session.execute(
                select(VirtualTraderPosition)
                .where(and_(*conditions))
                .order_by(asc(VirtualTraderPosition.stock_code))
            ).scalars().all()
            return list(rows)

    def list_positions(
        self, account_id: int, *, include_closed: bool = True
    ) -> List[VirtualTraderPosition]:
        """全部持仓（默认含已平仓），供绩效统计使用。"""
        conditions = [VirtualTraderPosition.account_id == account_id]
        if not include_closed:
            conditions.append(VirtualTraderPosition.status == 'open')
        with self.db.get_session() as session:
            rows = session.execute(
                select(VirtualTraderPosition)
                .where(and_(*conditions))
                .order_by(asc(VirtualTraderPosition.stock_code))
            ).scalars().all()
            return list(rows)

    def create_position(self, fields: Dict[str, Any]) -> VirtualTraderPosition:
        with self.db.get_session() as session:
            row = VirtualTraderPosition(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def update_position(
        self, position_id: int, fields: Dict[str, Any]
    ) -> Optional[VirtualTraderPosition]:
        fields = dict(fields)
        fields.pop("id", None)
        fields.pop("created_at", None)
        with self.db.get_session() as session:
            row = session.execute(
                select(VirtualTraderPosition)
                .where(VirtualTraderPosition.id == position_id)
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = utc_naive_now()
            session.commit()
            session.refresh(row)
            return row

    # ------------------------------------------------------------------
    # Trade
    # ------------------------------------------------------------------
    def create_trade(self, fields: Dict[str, Any]) -> VirtualTraderTrade:
        with self.db.get_session() as session:
            row = VirtualTraderTrade(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_trades(
        self,
        account_id: int,
        *,
        market: Optional[str] = None,
        stock_code: Optional[str] = None,
        side: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[VirtualTraderTrade], int]:
        conditions = [VirtualTraderTrade.account_id == account_id]
        if market:
            conditions.append(VirtualTraderTrade.market == market)
        if stock_code:
            conditions.append(VirtualTraderTrade.stock_code == stock_code)
        if side:
            conditions.append(VirtualTraderTrade.side == side)
        where_clause = and_(*conditions)
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        offset = (safe_page - 1) * safe_page_size
        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(VirtualTraderTrade.id))
                .select_from(VirtualTraderTrade)
                .where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(VirtualTraderTrade)
                .where(where_clause)
                .order_by(desc(VirtualTraderTrade.trade_date), desc(VirtualTraderTrade.id))
                .offset(offset)
                .limit(safe_page_size)
            ).scalars().all()
            return list(rows), int(total)

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------
    def create_prediction(self, fields: Dict[str, Any]) -> VirtualTraderPrediction:
        with self.db.get_session() as session:
            row = VirtualTraderPrediction(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def list_predictions(
        self,
        account_id: int,
        *,
        status: Optional[str] = None,
        outcome: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[VirtualTraderPrediction], int]:
        conditions = [VirtualTraderPrediction.account_id == account_id]
        if status:
            conditions.append(VirtualTraderPrediction.status == status)
        if outcome:
            conditions.append(VirtualTraderPrediction.outcome == outcome)
        where_clause = and_(*conditions)
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        offset = (safe_page - 1) * safe_page_size
        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(VirtualTraderPrediction.id))
                .select_from(VirtualTraderPrediction)
                .where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(VirtualTraderPrediction)
                .where(where_clause)
                .order_by(
                    desc(VirtualTraderPrediction.anchor_date),
                    desc(VirtualTraderPrediction.id),
                )
                .offset(offset)
                .limit(safe_page_size)
            ).scalars().all()
            return list(rows), int(total)

    def list_pending_predictions(
        self, account_id: int, *, matured_before: date
    ) -> List[VirtualTraderPrediction]:
        """Pending predictions whose evaluation window (anchor + horizon) has fully passed."""
        with self.db.get_session() as session:
            rows = session.execute(
                select(VirtualTraderPrediction)
                .where(
                    and_(
                        VirtualTraderPrediction.account_id == account_id,
                        VirtualTraderPrediction.status == 'pending',
                    )
                )
                .order_by(asc(VirtualTraderPrediction.anchor_date))
            ).scalars().all()
            from datetime import timedelta

            return [
                row
                for row in rows
                if (row.anchor_date or date.min) + timedelta(days=row.horizon_days or 1)
                <= matured_before
            ]

    def update_prediction(
        self, prediction_id: int, fields: Dict[str, Any]
    ) -> Optional[VirtualTraderPrediction]:
        fields = dict(fields)
        fields.pop("id", None)
        fields.pop("created_at", None)
        with self.db.get_session() as session:
            row = session.execute(
                select(VirtualTraderPrediction)
                .where(VirtualTraderPrediction.id == prediction_id)
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = utc_naive_now()
            session.commit()
            session.refresh(row)
            return row

    def prediction_stats(self, account_id: int) -> Dict[str, int]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(
                    VirtualTraderPrediction.status,
                    VirtualTraderPrediction.outcome,
                    func.count(VirtualTraderPrediction.id),
                )
                .where(VirtualTraderPrediction.account_id == account_id)
                .group_by(VirtualTraderPrediction.status, VirtualTraderPrediction.outcome)
            ).all()
            stats: Dict[str, int] = {"pending": 0, "hit": 0, "miss": 0, "unable": 0}
            for status, outcome, count in rows:
                if status == 'pending':
                    stats["pending"] += int(count)
                elif outcome:
                    stats[outcome] = stats.get(outcome, 0) + int(count)
            stats["total"] = sum(v for k, v in stats.items() if k != "total")
            return stats

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------
    def upsert_snapshot(self, fields: Dict[str, Any]) -> VirtualTraderSnapshot:
        account_id = fields["account_id"]
        trade_date = fields["trade_date"]
        with self.db.get_session() as session:
            row = session.execute(
                select(VirtualTraderSnapshot)
                .where(
                    and_(
                        VirtualTraderSnapshot.account_id == account_id,
                        VirtualTraderSnapshot.trade_date == trade_date,
                    )
                )
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                row = VirtualTraderSnapshot(**fields)
                session.add(row)
            else:
                for key, value in fields.items():
                    setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return row

    def list_snapshots(
        self, account_id: int, *, limit: int = 365
    ) -> List[VirtualTraderSnapshot]:
        safe_limit = max(1, min(int(limit), 1000))
        with self.db.get_session() as session:
            rows = session.execute(
                select(VirtualTraderSnapshot)
                .where(VirtualTraderSnapshot.account_id == account_id)
                .order_by(asc(VirtualTraderSnapshot.trade_date))
                .limit(safe_limit)
            ).scalars().all()
            return list(rows)

    def get_latest_snapshot(
        self, account_id: int
    ) -> Optional[VirtualTraderSnapshot]:
        with self.db.get_session() as session:
            return session.execute(
                select(VirtualTraderSnapshot)
                .where(VirtualTraderSnapshot.account_id == account_id)
                .order_by(desc(VirtualTraderSnapshot.trade_date))
                .limit(1)
            ).scalar_one_or_none()

    # ------------------------------------------------------------------
    # Run log（幂等）
    # ------------------------------------------------------------------
    def get_run(self, run_date: date, market: str) -> Optional[VirtualTraderRun]:
        with self.db.get_session() as session:
            return session.execute(
                select(VirtualTraderRun)
                .where(
                    and_(
                        VirtualTraderRun.run_date == run_date,
                        VirtualTraderRun.market == market,
                    )
                )
                .limit(1)
            ).scalar_one_or_none()

    def try_start_run(self, run_date: date, market: str) -> Optional[VirtualTraderRun]:
        """Atomically claim (run_date, market); None if already claimed."""
        with self.db.get_session() as session:
            existing = session.execute(
                select(VirtualTraderRun)
                .where(
                    and_(
                        VirtualTraderRun.run_date == run_date,
                        VirtualTraderRun.market == market,
                    )
                )
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                return None
            row = VirtualTraderRun(run_date=run_date, market=market, status='running')
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def finish_run(
        self, run_id: int, status: str, decisions: Optional[Dict[str, Any]] = None, error: Optional[str] = None
    ) -> Optional[VirtualTraderRun]:
        with self.db.get_session() as session:
            row = session.execute(
                select(VirtualTraderRun)
                .where(VirtualTraderRun.id == run_id)
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = status
            row.decisions_json = _json_dumps(decisions)
            row.error = error
            row.finished_at = utc_naive_now()
            session.commit()
            session.refresh(row)
            return row

    def list_runs(self, *, limit: int = 30) -> List[VirtualTraderRun]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(VirtualTraderRun)
                .order_by(desc(VirtualTraderRun.run_date), desc(VirtualTraderRun.market))
                .limit(max(1, min(int(limit), 100)))
            ).scalars().all()
            return list(rows)


def _json_dumps(value: Optional[Dict[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    import json

    return json.dumps(value, ensure_ascii=False, default=str)
