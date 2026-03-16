# -*- coding: utf-8 -*-
"""Portfolio repository.

Provides DB access helpers for portfolio account/events/snapshot tables.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import and_, delete, desc, func, select
from sqlalchemy.exc import IntegrityError

from src.storage import (
    DatabaseManager,
    PortfolioAccount,
    PortfolioCashLedger,
    PortfolioCorporateAction,
    PortfolioDailySnapshot,
    PortfolioFxRate,
    PortfolioPosition,
    PortfolioPositionLot,
    PortfolioTrade,
    StockDaily,
)

logger = logging.getLogger(__name__)


class DuplicateTradeUidError(Exception):
    """Raised when trade_uid conflicts with existing record in one account."""


class DuplicateTradeDedupHashError(Exception):
    """Raised when dedup hash conflicts with existing record in one account."""


class PortfolioRepository:
    """DB access layer for portfolio P0 domain."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    # ------------------------------------------------------------------
    # Account CRUD
    # ------------------------------------------------------------------
    def create_account(
        self,
        *,
        name: str,
        broker: Optional[str],
        market: str,
        base_currency: str,
        owner_id: Optional[str] = None,
    ) -> PortfolioAccount:
        with self.db.get_session() as session:
            row = PortfolioAccount(
                owner_id=owner_id,
                name=name,
                broker=broker,
                market=market,
                base_currency=base_currency,
                is_active=True,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def get_account(self, account_id: int, include_inactive: bool = False) -> Optional[PortfolioAccount]:
        with self.db.get_session() as session:
            conditions = [PortfolioAccount.id == account_id]
            if not include_inactive:
                conditions.append(PortfolioAccount.is_active.is_(True))
            return session.execute(
                select(PortfolioAccount).where(and_(*conditions)).limit(1)
            ).scalar_one_or_none()

    def list_accounts(self, include_inactive: bool = False) -> List[PortfolioAccount]:
        with self.db.get_session() as session:
            query = select(PortfolioAccount)
            if not include_inactive:
                query = query.where(PortfolioAccount.is_active.is_(True))
            rows = session.execute(query.order_by(PortfolioAccount.id.asc())).scalars().all()
            return list(rows)

    def update_account(self, account_id: int, fields: Dict[str, Any]) -> Optional[PortfolioAccount]:
        with self.db.get_session() as session:
            row = session.execute(
                select(PortfolioAccount).where(PortfolioAccount.id == account_id).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = datetime.now()
            session.commit()
            session.refresh(row)
            return row

    def deactivate_account(self, account_id: int) -> bool:
        with self.db.get_session() as session:
            row = session.execute(
                select(PortfolioAccount).where(PortfolioAccount.id == account_id).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return False
            row.is_active = False
            row.updated_at = datetime.now()
            session.commit()
            return True

    # ------------------------------------------------------------------
    # Event writes
    # ------------------------------------------------------------------
    def add_trade(
        self,
        *,
        account_id: int,
        trade_uid: Optional[str],
        symbol: str,
        market: str,
        currency: str,
        trade_date: date,
        side: str,
        quantity: float,
        price: float,
        fee: float,
        tax: float,
        note: Optional[str] = None,
        dedup_hash: Optional[str] = None,
    ) -> PortfolioTrade:
        with self.db.get_session() as session:
            row = PortfolioTrade(
                account_id=account_id,
                trade_uid=trade_uid,
                symbol=symbol,
                market=market,
                currency=currency,
                trade_date=trade_date,
                side=side,
                quantity=quantity,
                price=price,
                fee=fee,
                tax=tax,
                note=note,
                dedup_hash=dedup_hash,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                err_text = str(getattr(exc, "orig", exc)).lower()
                if trade_uid and ("uix_portfolio_trade_uid" in err_text or "unique" in err_text):
                    raise DuplicateTradeUidError(
                        f"Duplicate trade_uid for account_id={account_id}: {trade_uid}"
                    ) from exc
                if dedup_hash and (
                    "uix_portfolio_trade_dedup_hash" in err_text
                    or "portfolio_trades.account_id, portfolio_trades.dedup_hash" in err_text
                    or ("unique" in err_text and "dedup_hash" in err_text)
                ):
                    raise DuplicateTradeDedupHashError(
                        f"Duplicate dedup_hash for account_id={account_id}: {dedup_hash}"
                    ) from exc
                raise
            session.refresh(row)
            return row

    def add_cash_ledger(
        self,
        *,
        account_id: int,
        event_date: date,
        direction: str,
        amount: float,
        currency: str,
        note: Optional[str] = None,
    ) -> PortfolioCashLedger:
        with self.db.get_session() as session:
            row = PortfolioCashLedger(
                account_id=account_id,
                event_date=event_date,
                direction=direction,
                amount=amount,
                currency=currency,
                note=note,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def add_corporate_action(
        self,
        *,
        account_id: int,
        symbol: str,
        market: str,
        currency: str,
        effective_date: date,
        action_type: str,
        cash_dividend_per_share: Optional[float] = None,
        split_ratio: Optional[float] = None,
        note: Optional[str] = None,
    ) -> PortfolioCorporateAction:
        with self.db.get_session() as session:
            row = PortfolioCorporateAction(
                account_id=account_id,
                symbol=symbol,
                market=market,
                currency=currency,
                effective_date=effective_date,
                action_type=action_type,
                cash_dividend_per_share=cash_dividend_per_share,
                split_ratio=split_ratio,
                note=note,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def has_trade_uid(self, account_id: int, trade_uid: Optional[str]) -> bool:
        """Return True when trade_uid already exists in the account."""
        uid = (trade_uid or "").strip()
        if not uid:
            return False
        with self.db.get_session() as session:
            row = session.execute(
                select(PortfolioTrade.id).where(
                    and_(
                        PortfolioTrade.account_id == account_id,
                        PortfolioTrade.trade_uid == uid,
                    )
                ).limit(1)
            ).scalar_one_or_none()
            return row is not None

    def has_trade_dedup_hash(self, account_id: int, dedup_hash: Optional[str]) -> bool:
        """Return True when dedup hash already exists in the account."""
        hash_value = (dedup_hash or "").strip()
        if not hash_value:
            return False
        with self.db.get_session() as session:
            row = session.execute(
                select(PortfolioTrade.id).where(
                    and_(
                        PortfolioTrade.account_id == account_id,
                        PortfolioTrade.dedup_hash == hash_value,
                    )
                ).limit(1)
            ).scalar_one_or_none()
            return row is not None

    # ------------------------------------------------------------------
    # Event reads
    # ------------------------------------------------------------------
    def list_trades(self, account_id: int, as_of: date) -> List[PortfolioTrade]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(PortfolioTrade)
                .where(
                    and_(
                        PortfolioTrade.account_id == account_id,
                        PortfolioTrade.trade_date <= as_of,
                    )
                )
                .order_by(PortfolioTrade.trade_date.asc(), PortfolioTrade.id.asc())
            ).scalars().all()
            return list(rows)

    def list_cash_ledger(self, account_id: int, as_of: date) -> List[PortfolioCashLedger]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(PortfolioCashLedger)
                .where(
                    and_(
                        PortfolioCashLedger.account_id == account_id,
                        PortfolioCashLedger.event_date <= as_of,
                    )
                )
                .order_by(PortfolioCashLedger.event_date.asc(), PortfolioCashLedger.id.asc())
            ).scalars().all()
            return list(rows)

    def list_corporate_actions(self, account_id: int, as_of: date) -> List[PortfolioCorporateAction]:
        with self.db.get_session() as session:
            rows = session.execute(
                select(PortfolioCorporateAction)
                .where(
                    and_(
                        PortfolioCorporateAction.account_id == account_id,
                        PortfolioCorporateAction.effective_date <= as_of,
                    )
                )
                .order_by(PortfolioCorporateAction.effective_date.asc(), PortfolioCorporateAction.id.asc())
            ).scalars().all()
            return list(rows)

    def get_first_activity_date(self, *, account_id: int, as_of: date) -> Optional[date]:
        """Return earliest event date (trade/cash/corporate action) for one account."""
        with self.db.get_session() as session:
            first_trade = session.execute(
                select(func.min(PortfolioTrade.trade_date)).where(
                    and_(
                        PortfolioTrade.account_id == account_id,
                        PortfolioTrade.trade_date <= as_of,
                    )
                )
            ).scalar_one()
            first_cash = session.execute(
                select(func.min(PortfolioCashLedger.event_date)).where(
                    and_(
                        PortfolioCashLedger.account_id == account_id,
                        PortfolioCashLedger.event_date <= as_of,
                    )
                )
            ).scalar_one()
            first_action = session.execute(
                select(func.min(PortfolioCorporateAction.effective_date)).where(
                    and_(
                        PortfolioCorporateAction.account_id == account_id,
                        PortfolioCorporateAction.effective_date <= as_of,
                    )
                )
            ).scalar_one()

            candidates = [item for item in (first_trade, first_cash, first_action) if item is not None]
            if not candidates:
                return None
            return min(candidates)

    def query_trades(
        self,
        *,
        account_id: Optional[int],
        date_from: Optional[date],
        date_to: Optional[date],
        symbol: Optional[str],
        side: Optional[str],
        page: int,
        page_size: int,
    ) -> Tuple[List[PortfolioTrade], int]:
        with self.db.get_session() as session:
            conditions = []
            if account_id is not None:
                conditions.append(PortfolioTrade.account_id == account_id)
            if date_from is not None:
                conditions.append(PortfolioTrade.trade_date >= date_from)
            if date_to is not None:
                conditions.append(PortfolioTrade.trade_date <= date_to)
            if symbol:
                conditions.append(PortfolioTrade.symbol == symbol)
            if side:
                conditions.append(PortfolioTrade.side == side)

            data_query = select(PortfolioTrade)
            count_query = select(func.count()).select_from(PortfolioTrade)
            if conditions:
                where_clause = and_(*conditions)
                data_query = data_query.where(where_clause)
                count_query = count_query.where(where_clause)

            total = int(session.execute(count_query).scalar_one() or 0)
            rows = session.execute(
                data_query
                .order_by(PortfolioTrade.trade_date.desc(), PortfolioTrade.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).scalars().all()
            return list(rows), total

    def query_cash_ledger(
        self,
        *,
        account_id: Optional[int],
        date_from: Optional[date],
        date_to: Optional[date],
        direction: Optional[str],
        page: int,
        page_size: int,
    ) -> Tuple[List[PortfolioCashLedger], int]:
        with self.db.get_session() as session:
            conditions = []
            if account_id is not None:
                conditions.append(PortfolioCashLedger.account_id == account_id)
            if date_from is not None:
                conditions.append(PortfolioCashLedger.event_date >= date_from)
            if date_to is not None:
                conditions.append(PortfolioCashLedger.event_date <= date_to)
            if direction:
                conditions.append(PortfolioCashLedger.direction == direction)

            data_query = select(PortfolioCashLedger)
            count_query = select(func.count()).select_from(PortfolioCashLedger)
            if conditions:
                where_clause = and_(*conditions)
                data_query = data_query.where(where_clause)
                count_query = count_query.where(where_clause)

            total = int(session.execute(count_query).scalar_one() or 0)
            rows = session.execute(
                data_query
                .order_by(PortfolioCashLedger.event_date.desc(), PortfolioCashLedger.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).scalars().all()
            return list(rows), total

    def query_corporate_actions(
        self,
        *,
        account_id: Optional[int],
        date_from: Optional[date],
        date_to: Optional[date],
        symbol: Optional[str],
        action_type: Optional[str],
        page: int,
        page_size: int,
    ) -> Tuple[List[PortfolioCorporateAction], int]:
        with self.db.get_session() as session:
            conditions = []
            if account_id is not None:
                conditions.append(PortfolioCorporateAction.account_id == account_id)
            if date_from is not None:
                conditions.append(PortfolioCorporateAction.effective_date >= date_from)
            if date_to is not None:
                conditions.append(PortfolioCorporateAction.effective_date <= date_to)
            if symbol:
                conditions.append(PortfolioCorporateAction.symbol == symbol)
            if action_type:
                conditions.append(PortfolioCorporateAction.action_type == action_type)

            data_query = select(PortfolioCorporateAction)
            count_query = select(func.count()).select_from(PortfolioCorporateAction)
            if conditions:
                where_clause = and_(*conditions)
                data_query = data_query.where(where_clause)
                count_query = count_query.where(where_clause)

            total = int(session.execute(count_query).scalar_one() or 0)
            rows = session.execute(
                data_query
                .order_by(PortfolioCorporateAction.effective_date.desc(), PortfolioCorporateAction.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).scalars().all()
            return list(rows), total

    # ------------------------------------------------------------------
    # Price / FX
    # ------------------------------------------------------------------
    def get_latest_close(self, symbol: str, as_of: date) -> Optional[float]:
        with self.db.get_session() as session:
            row = session.execute(
                select(StockDaily)
                .where(
                    and_(
                        StockDaily.code == symbol,
                        StockDaily.date <= as_of,
                    )
                )
                .order_by(desc(StockDaily.date))
                .limit(1)
            ).scalar_one_or_none()
            if row is None or row.close is None:
                return None
            return float(row.close)

    def save_fx_rate(
        self,
        *,
        from_currency: str,
        to_currency: str,
        rate_date: date,
        rate: float,
        source: str = "manual",
        is_stale: bool = False,
    ) -> None:
        with self.db.get_session() as session:
            existing = session.execute(
                select(PortfolioFxRate).where(
                    and_(
                        PortfolioFxRate.from_currency == from_currency,
                        PortfolioFxRate.to_currency == to_currency,
                        PortfolioFxRate.rate_date == rate_date,
                    )
                ).limit(1)
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    PortfolioFxRate(
                        from_currency=from_currency,
                        to_currency=to_currency,
                        rate_date=rate_date,
                        rate=rate,
                        source=source,
                        is_stale=is_stale,
                    )
                )
            else:
                existing.rate = rate
                existing.source = source
                existing.is_stale = is_stale
                existing.updated_at = datetime.now()
            session.commit()

    def get_latest_fx_rate(
        self,
        *,
        from_currency: str,
        to_currency: str,
        as_of: date,
    ) -> Optional[PortfolioFxRate]:
        with self.db.get_session() as session:
            row = session.execute(
                select(PortfolioFxRate)
                .where(
                    and_(
                        PortfolioFxRate.from_currency == from_currency,
                        PortfolioFxRate.to_currency == to_currency,
                        PortfolioFxRate.rate_date <= as_of,
                    )
                )
                .order_by(desc(PortfolioFxRate.rate_date))
                .limit(1)
            ).scalar_one_or_none()
            return row

    def list_daily_snapshots_for_risk(
        self,
        *,
        as_of: date,
        cost_method: str,
        account_id: Optional[int] = None,
        lookback_days: int = 180,
    ) -> List[PortfolioDailySnapshot]:
        """Load snapshot rows in ascending date order for risk monitoring."""
        with self.db.get_session() as session:
            query = select(PortfolioDailySnapshot).where(
                and_(
                    PortfolioDailySnapshot.snapshot_date <= as_of,
                    PortfolioDailySnapshot.cost_method == cost_method,
                )
            )
            if account_id is not None:
                query = query.where(PortfolioDailySnapshot.account_id == account_id)
            rows = session.execute(
                query.order_by(
                    PortfolioDailySnapshot.snapshot_date.asc(),
                    PortfolioDailySnapshot.account_id.asc(),
                )
            ).scalars().all()
            if lookback_days <= 0:
                return list(rows)
            # Keep only the latest N calendar days window for risk calculations.
            cutoff_ordinal = as_of.toordinal() - lookback_days
            return [row for row in rows if row.snapshot_date.toordinal() >= cutoff_ordinal]

    # ------------------------------------------------------------------
    # Snapshot / position cache
    # ------------------------------------------------------------------
    def replace_positions_and_lots(
        self,
        *,
        account_id: int,
        cost_method: str,
        positions: Iterable[Dict[str, Any]],
        lots: Iterable[Dict[str, Any]],
        valuation_currency: str,
    ) -> None:
        with self.db.get_session() as session:
            session.execute(
                delete(PortfolioPosition).where(
                    and_(
                        PortfolioPosition.account_id == account_id,
                        PortfolioPosition.cost_method == cost_method,
                    )
                )
            )
            session.execute(
                delete(PortfolioPositionLot).where(
                    and_(
                        PortfolioPositionLot.account_id == account_id,
                        PortfolioPositionLot.cost_method == cost_method,
                    )
                )
            )

            for item in positions:
                session.add(
                    PortfolioPosition(
                        account_id=account_id,
                        cost_method=cost_method,
                        symbol=item["symbol"],
                        market=item["market"],
                        currency=item["currency"],
                        quantity=float(item["quantity"]),
                        avg_cost=float(item["avg_cost"]),
                        total_cost=float(item["total_cost"]),
                        last_price=float(item["last_price"]),
                        market_value_base=float(item["market_value_base"]),
                        unrealized_pnl_base=float(item["unrealized_pnl_base"]),
                        valuation_currency=valuation_currency,
                    )
                )

            for lot in lots:
                session.add(
                    PortfolioPositionLot(
                        account_id=account_id,
                        cost_method=cost_method,
                        symbol=lot["symbol"],
                        market=lot["market"],
                        currency=lot["currency"],
                        open_date=lot["open_date"],
                        remaining_quantity=float(lot["remaining_quantity"]),
                        unit_cost=float(lot["unit_cost"]),
                        source_trade_id=lot.get("source_trade_id"),
                    )
                )

            session.commit()

    def upsert_daily_snapshot(
        self,
        *,
        account_id: int,
        snapshot_date: date,
        cost_method: str,
        base_currency: str,
        total_cash: float,
        total_market_value: float,
        total_equity: float,
        unrealized_pnl: float,
        realized_pnl: float,
        fee_total: float,
        tax_total: float,
        fx_stale: bool,
        payload: str,
    ) -> None:
        with self.db.get_session() as session:
            existing = session.execute(
                select(PortfolioDailySnapshot).where(
                    and_(
                        PortfolioDailySnapshot.account_id == account_id,
                        PortfolioDailySnapshot.snapshot_date == snapshot_date,
                        PortfolioDailySnapshot.cost_method == cost_method,
                    )
                ).limit(1)
            ).scalar_one_or_none()

            if existing is None:
                session.add(
                    PortfolioDailySnapshot(
                        account_id=account_id,
                        snapshot_date=snapshot_date,
                        cost_method=cost_method,
                        base_currency=base_currency,
                        total_cash=total_cash,
                        total_market_value=total_market_value,
                        total_equity=total_equity,
                        unrealized_pnl=unrealized_pnl,
                        realized_pnl=realized_pnl,
                        fee_total=fee_total,
                        tax_total=tax_total,
                        fx_stale=fx_stale,
                        payload=payload,
                    )
                )
            else:
                existing.base_currency = base_currency
                existing.total_cash = total_cash
                existing.total_market_value = total_market_value
                existing.total_equity = total_equity
                existing.unrealized_pnl = unrealized_pnl
                existing.realized_pnl = realized_pnl
                existing.fee_total = fee_total
                existing.tax_total = tax_total
                existing.fx_stale = fx_stale
                existing.payload = payload
                existing.updated_at = datetime.now()
            session.commit()

    def replace_positions_lots_and_snapshot(
        self,
        *,
        account_id: int,
        snapshot_date: date,
        cost_method: str,
        base_currency: str,
        total_cash: float,
        total_market_value: float,
        total_equity: float,
        unrealized_pnl: float,
        realized_pnl: float,
        fee_total: float,
        tax_total: float,
        fx_stale: bool,
        payload: str,
        positions: Iterable[Dict[str, Any]],
        lots: Iterable[Dict[str, Any]],
        valuation_currency: str,
    ) -> None:
        """Atomically refresh position cache and daily snapshot in one transaction."""
        with self.db.get_session() as session:
            session.execute(
                delete(PortfolioPosition).where(
                    and_(
                        PortfolioPosition.account_id == account_id,
                        PortfolioPosition.cost_method == cost_method,
                    )
                )
            )
            session.execute(
                delete(PortfolioPositionLot).where(
                    and_(
                        PortfolioPositionLot.account_id == account_id,
                        PortfolioPositionLot.cost_method == cost_method,
                    )
                )
            )

            for item in positions:
                session.add(
                    PortfolioPosition(
                        account_id=account_id,
                        cost_method=cost_method,
                        symbol=item["symbol"],
                        market=item["market"],
                        currency=item["currency"],
                        quantity=float(item["quantity"]),
                        avg_cost=float(item["avg_cost"]),
                        total_cost=float(item["total_cost"]),
                        last_price=float(item["last_price"]),
                        market_value_base=float(item["market_value_base"]),
                        unrealized_pnl_base=float(item["unrealized_pnl_base"]),
                        valuation_currency=valuation_currency,
                    )
                )

            for lot in lots:
                session.add(
                    PortfolioPositionLot(
                        account_id=account_id,
                        cost_method=cost_method,
                        symbol=lot["symbol"],
                        market=lot["market"],
                        currency=lot["currency"],
                        open_date=lot["open_date"],
                        remaining_quantity=float(lot["remaining_quantity"]),
                        unit_cost=float(lot["unit_cost"]),
                        source_trade_id=lot.get("source_trade_id"),
                    )
                )

            existing = session.execute(
                select(PortfolioDailySnapshot).where(
                    and_(
                        PortfolioDailySnapshot.account_id == account_id,
                        PortfolioDailySnapshot.snapshot_date == snapshot_date,
                        PortfolioDailySnapshot.cost_method == cost_method,
                    )
                ).limit(1)
            ).scalar_one_or_none()

            if existing is None:
                session.add(
                    PortfolioDailySnapshot(
                        account_id=account_id,
                        snapshot_date=snapshot_date,
                        cost_method=cost_method,
                        base_currency=base_currency,
                        total_cash=total_cash,
                        total_market_value=total_market_value,
                        total_equity=total_equity,
                        unrealized_pnl=unrealized_pnl,
                        realized_pnl=realized_pnl,
                        fee_total=fee_total,
                        tax_total=tax_total,
                        fx_stale=fx_stale,
                        payload=payload,
                    )
                )
            else:
                existing.base_currency = base_currency
                existing.total_cash = total_cash
                existing.total_market_value = total_market_value
                existing.total_equity = total_equity
                existing.unrealized_pnl = unrealized_pnl
                existing.realized_pnl = realized_pnl
                existing.fee_total = fee_total
                existing.tax_total = tax_total
                existing.fx_stale = fx_stale
                existing.payload = payload
                existing.updated_at = datetime.now()

            session.commit()
