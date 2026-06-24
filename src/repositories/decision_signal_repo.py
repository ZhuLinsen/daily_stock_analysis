# -*- coding: utf-8 -*-
"""Decision signal repository for Issue #1390 P1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc, func, or_, select

from src.storage import (
    DatabaseManager,
    DecisionSignalRecord,
    to_utc_naive_datetime,
    utc_naive_now,
)


@dataclass
class DecisionSignalCreateResult:
    """Outcome of an idempotent DecisionSignal create attempt."""

    row: DecisionSignalRecord
    created: bool
    refreshed: bool = False
    duplicate: bool = False
    invalidation_reference_at: Optional[datetime] = None

    def __iter__(self):
        yield self.row
        yield self.created


class DecisionSignalRepository:
    """DB access layer for persisted AI decision signals."""

    _RELAXED_MERGE_STATUSES = frozenset({"active", "expired"})
    _IMMUTABLE_REFRESH_FIELDS = frozenset({
        "id",
        "created_at",
        "source_report_id",
        "source_type",
        "source_agent",
        "trace_id",
        "trigger_source",
        "market",
        "stock_code",
        "action",
        "horizon",
        "market_phase",
    })

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def create(self, fields: Dict[str, Any]) -> DecisionSignalRecord:
        fields = self._normalize_datetime_fields(fields)
        with self.db.get_session() as session:
            row = DecisionSignalRecord(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def create_if_absent(
        self,
        fields: Dict[str, Any],
        *,
        allow_relaxed_horizon_fill: bool = False,
    ) -> DecisionSignalCreateResult:
        self.expire_due_signals()
        fields = self._normalize_datetime_fields(fields)
        with self.db.get_session() as session:
            existing = self._find_existing_in_session(session=session, fields=fields)
            if existing is not None:
                if self._should_refresh_existing(existing, fields):
                    self._refresh_existing_in_session(existing, fields)
                    session.commit()
                    session.refresh(existing)
                    return DecisionSignalCreateResult(
                        row=existing,
                        created=False,
                        refreshed=True,
                        invalidation_reference_at=existing.updated_at,
                    )
                return DecisionSignalCreateResult(
                    row=existing,
                    created=False,
                    duplicate=True,
                    invalidation_reference_at=existing.created_at,
                )

            relaxed_existing = self._find_relaxed_existing_in_session(
                session=session,
                fields=fields,
                allow_relaxed_horizon_fill=allow_relaxed_horizon_fill,
            )
            if relaxed_existing is not None:
                if self._should_refresh_existing(relaxed_existing, fields):
                    self._refresh_existing_in_session(relaxed_existing, fields)
                    self._fill_relaxed_dimensions_in_session(
                        relaxed_existing,
                        fields,
                        allow_horizon_fill=allow_relaxed_horizon_fill,
                    )
                    session.commit()
                    session.refresh(relaxed_existing)
                    return DecisionSignalCreateResult(
                        row=relaxed_existing,
                        created=False,
                        refreshed=True,
                        invalidation_reference_at=relaxed_existing.updated_at,
                    )
                if relaxed_existing.status == "active":
                    changed = self._fill_relaxed_dimensions_in_session(
                        relaxed_existing,
                        fields,
                        allow_horizon_fill=allow_relaxed_horizon_fill,
                    )
                    if changed:
                        session.commit()
                        session.refresh(relaxed_existing)
                        return DecisionSignalCreateResult(
                            row=relaxed_existing,
                            created=False,
                            refreshed=True,
                            invalidation_reference_at=relaxed_existing.created_at,
                        )
                return DecisionSignalCreateResult(
                    row=relaxed_existing,
                    created=False,
                    duplicate=True,
                    invalidation_reference_at=relaxed_existing.created_at,
                )

            row = DecisionSignalRecord(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return DecisionSignalCreateResult(
                row=row,
                created=True,
                invalidation_reference_at=row.created_at,
            )

    def get(self, signal_id: int) -> Optional[DecisionSignalRecord]:
        self.expire_due_signals()
        with self.db.get_session() as session:
            return session.execute(
                select(DecisionSignalRecord).where(DecisionSignalRecord.id == signal_id).limit(1)
            ).scalar_one_or_none()

    def list(
        self,
        *,
        stock_codes: Optional[List[str]] = None,
        stock_identities: Optional[List[Tuple[str, str]]] = None,
        market: Optional[str] = None,
        action: Optional[str] = None,
        market_phase: Optional[str] = None,
        source_type: Optional[str] = None,
        source_report_id: Optional[int] = None,
        trace_id: Optional[str] = None,
        trigger_source: Optional[str] = None,
        status: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        expires_from: Optional[datetime] = None,
        expires_to: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[DecisionSignalRecord], int]:
        self.expire_due_signals()
        created_from = self._normalize_optional_datetime(created_from)
        created_to = self._normalize_optional_datetime(created_to)
        expires_from = self._normalize_optional_datetime(expires_from)
        expires_to = self._normalize_optional_datetime(expires_to)
        conditions = self._build_conditions(
            stock_codes=stock_codes,
            stock_identities=stock_identities,
            market=market,
            action=action,
            market_phase=market_phase,
            source_type=source_type,
            source_report_id=source_report_id,
            trace_id=trace_id,
            trigger_source=trigger_source,
            status=status,
            created_from=created_from,
            created_to=created_to,
            expires_from=expires_from,
            expires_to=expires_to,
        )
        where_clause = and_(*conditions) if conditions else True
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        offset = (safe_page - 1) * safe_page_size

        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(DecisionSignalRecord.id))
                .select_from(DecisionSignalRecord)
                .where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(DecisionSignalRecord)
                .where(where_clause)
                .order_by(desc(DecisionSignalRecord.created_at), desc(DecisionSignalRecord.id))
                .offset(offset)
                .limit(safe_page_size)
            ).scalars().all()
            return list(rows), int(total)

    def get_latest_active(
        self,
        *,
        stock_codes: List[str],
        market: Optional[str] = None,
        limit: int = 1,
    ) -> List[DecisionSignalRecord]:
        self.expire_due_signals()
        safe_limit = max(1, min(int(limit), 100))
        conditions = [
            DecisionSignalRecord.status == "active",
            DecisionSignalRecord.stock_code.in_(stock_codes),
        ]
        if market:
            conditions.append(DecisionSignalRecord.market == market)
        with self.db.get_session() as session:
            rows = session.execute(
                select(DecisionSignalRecord)
                .where(and_(*conditions))
                .order_by(desc(DecisionSignalRecord.created_at), desc(DecisionSignalRecord.id))
                .limit(safe_limit)
            ).scalars().all()
            return list(rows)

    def list_active_by_stock_actions(
        self,
        *,
        market: str,
        stock_code: str,
        actions: List[str],
        exclude_signal_id: Optional[int] = None,
    ) -> List[DecisionSignalRecord]:
        self.expire_due_signals()
        if not actions:
            return []
        conditions = [
            DecisionSignalRecord.status == "active",
            DecisionSignalRecord.market == market,
            DecisionSignalRecord.stock_code == stock_code,
            DecisionSignalRecord.action.in_(actions),
        ]
        if exclude_signal_id is not None:
            conditions.append(DecisionSignalRecord.id != exclude_signal_id)
        with self.db.get_session() as session:
            rows = session.execute(
                select(DecisionSignalRecord)
                .where(and_(*conditions))
                .order_by(desc(DecisionSignalRecord.created_at), desc(DecisionSignalRecord.id))
            ).scalars().all()
            return list(rows)

    def update_status(
        self,
        signal_id: int,
        *,
        status: str,
        metadata_json: Optional[str] = None,
        replace_metadata: bool = False,
    ) -> Optional[DecisionSignalRecord]:
        with self.db.get_session() as session:
            row = session.execute(
                select(DecisionSignalRecord).where(DecisionSignalRecord.id == signal_id).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = status
            if replace_metadata:
                row.metadata_json = metadata_json
            row.updated_at = utc_naive_now()
            session.commit()
            session.refresh(row)
            return row

    def expire_due_signals(self, now: Optional[datetime] = None) -> int:
        now_value = to_utc_naive_datetime(now) if now is not None else utc_naive_now()
        with self.db.get_session() as session:
            rows = session.execute(
                select(DecisionSignalRecord).where(
                    DecisionSignalRecord.status == "active",
                    DecisionSignalRecord.expires_at.is_not(None),
                    DecisionSignalRecord.expires_at <= now_value,
                )
            ).scalars().all()
            for row in rows:
                row.status = "expired"
                row.updated_at = now_value
            session.commit()
            return len(rows)

    @staticmethod
    def _normalize_datetime_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(fields)
        for field_name in ("expires_at", "created_at", "updated_at"):
            value = normalized.get(field_name)
            if isinstance(value, datetime):
                normalized[field_name] = to_utc_naive_datetime(value)
        return normalized

    @staticmethod
    def _normalize_optional_datetime(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        return to_utc_naive_datetime(value)

    @classmethod
    def _should_refresh_existing(cls, existing: DecisionSignalRecord, fields: Dict[str, Any]) -> bool:
        expires_at = fields.get("expires_at")
        return (
            existing.status == "expired"
            and fields.get("status") == "active"
            and expires_at is not None
            and expires_at > utc_naive_now()
        )

    @classmethod
    def _refresh_existing_in_session(cls, existing: DecisionSignalRecord, fields: Dict[str, Any]) -> None:
        for field_name, value in fields.items():
            if field_name in cls._IMMUTABLE_REFRESH_FIELDS:
                continue
            setattr(existing, field_name, value)
        existing.updated_at = utc_naive_now()

    @staticmethod
    def _find_existing_in_session(*, session: Any, fields: Dict[str, Any]) -> Optional[DecisionSignalRecord]:
        source_report_id = fields.get("source_report_id")
        trace_id = fields.get("trace_id")
        source_type = fields.get("source_type")
        stock_code = fields.get("stock_code")
        market = fields.get("market")
        action = fields.get("action")
        horizon = fields.get("horizon")
        market_phase = fields.get("market_phase")
        if source_report_id is not None:
            conditions = [
                DecisionSignalRecord.source_report_id == source_report_id,
                DecisionSignalRecord.source_type == source_type,
                DecisionSignalRecord.market == market,
                DecisionSignalRecord.stock_code == stock_code,
                DecisionSignalRecord.action == action,
                DecisionSignalRecord.horizon == horizon,
                DecisionSignalRecord.market_phase == market_phase,
            ]
        elif trace_id:
            conditions = [
                DecisionSignalRecord.trace_id == trace_id,
                DecisionSignalRecord.source_type == source_type,
                DecisionSignalRecord.market == market,
                DecisionSignalRecord.stock_code == stock_code,
                DecisionSignalRecord.action == action,
                DecisionSignalRecord.horizon == horizon,
                DecisionSignalRecord.market_phase == market_phase,
            ]
        else:
            return None
        return session.execute(
            select(DecisionSignalRecord)
            .where(and_(*conditions))
            .order_by(DecisionSignalRecord.id.asc())
            .limit(1)
        ).scalar_one_or_none()

    @classmethod
    def _find_relaxed_existing_in_session(
        cls,
        *,
        session: Any,
        fields: Dict[str, Any],
        allow_relaxed_horizon_fill: bool,
    ) -> Optional[DecisionSignalRecord]:
        source_report_id = fields.get("source_report_id")
        trace_id = fields.get("trace_id")
        if source_report_id is None and not trace_id:
            return None

        conditions = [
            DecisionSignalRecord.source_type == fields.get("source_type"),
            DecisionSignalRecord.market == fields.get("market"),
            DecisionSignalRecord.stock_code == fields.get("stock_code"),
            DecisionSignalRecord.action == fields.get("action"),
        ]
        if source_report_id is not None:
            conditions.append(DecisionSignalRecord.source_report_id == source_report_id)
        else:
            conditions.append(DecisionSignalRecord.trace_id == trace_id)

        candidates = session.execute(
            select(DecisionSignalRecord)
            .where(and_(*conditions))
            .order_by(DecisionSignalRecord.id.asc())
        ).scalars().all()
        for candidate in candidates:
            if candidate.status not in cls._RELAXED_MERGE_STATUSES:
                continue
            if cls._can_relaxed_merge(
                candidate,
                fields,
                allow_horizon_fill=allow_relaxed_horizon_fill,
            ):
                return candidate
        return None

    @classmethod
    def _can_relaxed_merge(
        cls,
        existing: DecisionSignalRecord,
        fields: Dict[str, Any],
        *,
        allow_horizon_fill: bool,
    ) -> bool:
        new_horizon = fields.get("horizon")
        new_phase = fields.get("market_phase")

        horizon_fill = existing.horizon is None and new_horizon is not None
        if horizon_fill and not allow_horizon_fill:
            return False
        if existing.horizon is not None and existing.horizon != new_horizon:
            return False

        phase_fill = existing.market_phase is None and new_phase is not None
        if existing.market_phase is not None and existing.market_phase != new_phase:
            return False

        return horizon_fill or phase_fill

    @classmethod
    def _fill_relaxed_dimensions_in_session(
        cls,
        existing: DecisionSignalRecord,
        fields: Dict[str, Any],
        *,
        allow_horizon_fill: bool,
    ) -> bool:
        changed = False
        new_horizon = fields.get("horizon")
        new_phase = fields.get("market_phase")
        if existing.horizon is None and new_horizon is not None and allow_horizon_fill:
            existing.horizon = new_horizon
            changed = True
        if existing.market_phase is None and new_phase is not None:
            existing.market_phase = new_phase
            changed = True
        if changed:
            existing.updated_at = utc_naive_now()
        return changed

    @staticmethod
    def _build_conditions(
        *,
        stock_codes: Optional[List[str]],
        stock_identities: Optional[List[Tuple[str, str]]],
        market: Optional[str],
        action: Optional[str],
        market_phase: Optional[str],
        source_type: Optional[str],
        source_report_id: Optional[int],
        trace_id: Optional[str],
        trigger_source: Optional[str],
        status: Optional[str],
        created_from: Optional[datetime],
        created_to: Optional[datetime],
        expires_from: Optional[datetime],
        expires_to: Optional[datetime],
    ) -> List[Any]:
        conditions: List[Any] = []
        if stock_identities:
            identity_conditions = [
                and_(
                    DecisionSignalRecord.market == identity_market,
                    DecisionSignalRecord.stock_code == identity_code,
                )
                for identity_market, identity_code in stock_identities
            ]
            conditions.append(or_(*identity_conditions))
        elif stock_codes:
            conditions.append(DecisionSignalRecord.stock_code.in_(stock_codes))
        if market:
            conditions.append(DecisionSignalRecord.market == market)
        if action:
            conditions.append(DecisionSignalRecord.action == action)
        if market_phase:
            conditions.append(DecisionSignalRecord.market_phase == market_phase)
        if source_type:
            conditions.append(DecisionSignalRecord.source_type == source_type)
        if source_report_id is not None:
            conditions.append(DecisionSignalRecord.source_report_id == source_report_id)
        if trace_id:
            conditions.append(DecisionSignalRecord.trace_id == trace_id)
        if trigger_source:
            conditions.append(DecisionSignalRecord.trigger_source == trigger_source)
        if status:
            conditions.append(DecisionSignalRecord.status == status)
        if created_from:
            conditions.append(DecisionSignalRecord.created_at >= created_from)
        if created_to:
            conditions.append(DecisionSignalRecord.created_at <= created_to)
        if expires_from:
            conditions.append(DecisionSignalRecord.expires_at >= expires_from)
        if expires_to:
            conditions.append(DecisionSignalRecord.expires_at <= expires_to)
        return conditions
