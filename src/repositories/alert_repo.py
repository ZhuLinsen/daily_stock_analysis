# -*- coding: utf-8 -*-
"""Alert repository.

Provides DB access helpers for alert-center P1 API tables.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sqlalchemy import and_, delete, desc, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.storage import (
    AlertCooldownRecord,
    AlertNotificationRecord,
    AlertRuleRecord,
    AlertTriggerRecord,
    DatabaseManager,
)


_ACTIVE_CLAIM_ERROR_CODES = ("in_flight", "dispatch_committed")


class AlertRepository:
    """DB access layer for alert rules and read-only alert history."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def create_rule(self, fields: Dict[str, Any]) -> AlertRuleRecord:
        with self.db.get_session() as session:
            row = AlertRuleRecord(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def get_rule(self, rule_id: int) -> Optional[AlertRuleRecord]:
        with self.db.get_session() as session:
            return session.execute(
                select(AlertRuleRecord).where(AlertRuleRecord.id == rule_id).limit(1)
            ).scalar_one_or_none()

    def update_rule(self, rule_id: int, fields: Dict[str, Any]) -> Optional[AlertRuleRecord]:
        with self.db.get_session() as session:
            row = session.execute(
                select(AlertRuleRecord).where(AlertRuleRecord.id == rule_id).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = datetime.now()
            session.commit()
            session.refresh(row)
            return row

    def delete_rule(self, rule_id: int) -> bool:
        with self.db.get_session() as session:
            result = session.execute(delete(AlertRuleRecord).where(AlertRuleRecord.id == rule_id))
            session.commit()
            return bool(result.rowcount)

    def list_rules(
        self,
        *,
        enabled: Optional[bool] = None,
        alert_type: Optional[str] = None,
        target_scope: Optional[str] = None,
        target: Optional[str] = None,
        source: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AlertRuleRecord], int]:
        conditions = []
        if enabled is not None:
            conditions.append(AlertRuleRecord.enabled.is_(enabled))
        if alert_type:
            conditions.append(AlertRuleRecord.alert_type == alert_type)
        if target_scope:
            conditions.append(AlertRuleRecord.target_scope == target_scope)
        if target:
            if target_scope == "single_symbol":
                conditions.append(func.lower(AlertRuleRecord.target) == target.strip().lower())
            else:
                conditions.append(AlertRuleRecord.target == target)
        if source:
            conditions.append(AlertRuleRecord.source == source)

        where_clause = and_(*conditions) if conditions else True
        offset = (page - 1) * page_size
        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(AlertRuleRecord.id)).select_from(AlertRuleRecord).where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(AlertRuleRecord)
                .where(where_clause)
                .order_by(desc(AlertRuleRecord.updated_at), desc(AlertRuleRecord.id))
                .offset(offset)
                .limit(page_size)
            ).scalars().all()
            return list(rows), int(total)

    def list_enabled_rules(self, *, limit: int = 1000) -> List[AlertRuleRecord]:
        safe_limit = max(1, min(int(limit), 1000))
        with self.db.get_session() as session:
            rows = session.execute(
                select(AlertRuleRecord)
                .where(AlertRuleRecord.enabled.is_(True))
                .order_by(desc(AlertRuleRecord.updated_at), desc(AlertRuleRecord.id))
                .limit(safe_limit)
            ).scalars().all()
            return list(rows)

    def create_trigger(self, fields: Dict[str, Any]) -> AlertTriggerRecord:
        self._validate_trigger_fields(fields)

        with self.db.get_session() as session:
            row = AlertTriggerRecord(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    @contextmanager
    def _sqlite_immediate_session(self) -> Iterator[Tuple[Session, bool]]:
        """Serialize read-check-insert transactions across SQLite workers."""
        engine = getattr(self.db, "_engine", None)
        is_sqlite = bool(
            engine is not None
            and hasattr(engine, "url")
            and engine.url.get_backend_name() == "sqlite"
        )
        if not is_sqlite:
            with self.db.get_session() as session:
                try:
                    yield session, False
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
            return

        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            in_tx = False
            for attempt in range(20):
                try:
                    conn.exec_driver_sql("BEGIN IMMEDIATE")
                    in_tx = True
                    break
                except OperationalError as exc:
                    msg = str(getattr(exc, "orig", exc)).lower()
                    if "cannot start a transaction within a transaction" in msg:
                        in_tx = False
                        break
                    if ("locked" in msg or "busy" in msg) and attempt < 19:
                        time.sleep(min(0.01 * (attempt + 1), 0.1))
                        continue
                    raise
            session = Session(bind=conn, autocommit=False, autoflush=False)
            try:
                yield session, True
                session.flush()
                if in_tx:
                    conn.exec_driver_sql("COMMIT")
                else:
                    session.commit()
            except Exception:
                try:
                    session.rollback()
                finally:
                    if in_tx:
                        try:
                            conn.exec_driver_sql("ROLLBACK")
                        except Exception:
                            pass
                raise
            finally:
                session.close()
        finally:
            conn.close()

    def create_trigger_if_absent(self, fields: Dict[str, Any]) -> Tuple[AlertTriggerRecord, bool]:
        """Create a triggered history row unless the same DB signal already exists.

        Callers must use this only after they have decided the trigger is safe to
        deduplicate. Non-triggered or timestamp-less history should use
        ``create_trigger`` so audit rows are not silently reclassified as deduped.
        """
        self._validate_trigger_fields(fields)

        rule_id = fields.get("rule_id")
        data_timestamp = fields.get("data_timestamp")
        if fields.get("status") != "triggered" or rule_id is None or data_timestamp is None:
            raise ValueError(
                "create_trigger_if_absent requires triggered status, rule_id, and data_timestamp"
            )

        with self._sqlite_immediate_session() as (session, is_sqlite_imm):
            query = select(AlertTriggerRecord).where(
                AlertTriggerRecord.rule_id == rule_id,
                AlertTriggerRecord.target == fields.get("target"),
                AlertTriggerRecord.status == "triggered",
                AlertTriggerRecord.data_timestamp == data_timestamp,
            )
            data_source = fields.get("data_source")
            if data_source is None:
                query = query.where(AlertTriggerRecord.data_source.is_(None))
            else:
                query = query.where(AlertTriggerRecord.data_source == data_source)

            stmt = query.order_by(AlertTriggerRecord.id.asc()).limit(1)
            if not is_sqlite_imm:
                stmt = stmt.with_for_update()
            existing = session.execute(stmt).scalar_one_or_none()
            if existing is not None:
                session.expunge(existing)
                return existing, False

            row = AlertTriggerRecord(**fields)
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row, True

    @staticmethod
    def _validate_trigger_fields(fields: Dict[str, Any]) -> None:
        if not fields.get("target"):
            raise ValueError("alert trigger target is required")
        if not fields.get("status"):
            raise ValueError("alert trigger status is required")

    def record_notification_attempt(self, fields: Dict[str, Any]) -> AlertNotificationRecord:
        if not fields.get("channel"):
            raise ValueError("alert notification channel is required")

        with self.db.get_session() as session:
            row = AlertNotificationRecord(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def acquire_bar_delivery_claim(
        self,
        trigger_id: int,
        *,
        owner_token: str,
        lease_seconds: float = 300.0,
        now: Optional[datetime] = None,
    ) -> Tuple[bool, str, Optional[int]]:
        """Atomically claim completed-bar notification dispatch for ``trigger_id``."""
        if not owner_token or not str(owner_token).strip():
            raise ValueError("owner_token is required")
        now_dt = now or datetime.now()
        cutoff = now_dt - timedelta(seconds=max(0.05, float(lease_seconds)))
        owner_diag = f"owner={owner_token}"

        with self._sqlite_immediate_session() as (session, is_sqlite_imm):
            if not is_sqlite_imm:
                session.execute(
                    select(AlertTriggerRecord.id)
                    .where(AlertTriggerRecord.id == trigger_id)
                    .with_for_update()
                ).scalar_one_or_none()

            channels = session.execute(
                select(AlertNotificationRecord.channel).where(
                    AlertNotificationRecord.trigger_id == trigger_id,
                    AlertNotificationRecord.success.is_(True),
                )
            ).scalars().all()
            if any(bool(ch) and not str(ch).startswith("__") for ch in channels):
                return False, "already_delivered", None

            unrecorded = session.execute(
                select(AlertNotificationRecord.id)
                .where(
                    AlertNotificationRecord.trigger_id == trigger_id,
                    AlertNotificationRecord.channel == "__bar_delivery_claim__",
                    AlertNotificationRecord.error_code == "delivery_unrecorded",
                    AlertNotificationRecord.retryable.is_(False),
                )
                .limit(1)
            ).scalar_one_or_none()
            if unrecorded is not None:
                return False, "delivery_unrecorded", None

            committed_claims = session.execute(
                select(AlertNotificationRecord)
                .where(
                    AlertNotificationRecord.trigger_id == trigger_id,
                    AlertNotificationRecord.channel == "__bar_delivery_claim__",
                    AlertNotificationRecord.error_code == "dispatch_committed",
                    AlertNotificationRecord.retryable.is_(False),
                )
                .order_by(AlertNotificationRecord.id.asc())
            ).scalars().all()
            if committed_claims:
                if any(row.created_at is not None and row.created_at > cutoff for row in committed_claims):
                    return False, "in_flight", None
                return False, "delivery_unrecorded", None

            existing_claims = session.execute(
                select(AlertNotificationRecord)
                .where(
                    AlertNotificationRecord.trigger_id == trigger_id,
                    AlertNotificationRecord.channel == "__bar_delivery_claim__",
                    AlertNotificationRecord.error_code == "in_flight",
                    AlertNotificationRecord.retryable.is_(False),
                )
                .order_by(AlertNotificationRecord.id.asc())
            ).scalars().all()

            active_claim = False
            for row in existing_claims:
                if row.created_at is None or row.created_at <= cutoff:
                    session.delete(row)
                else:
                    active_claim = True

            if active_claim:
                return False, "in_flight", None

            claim = AlertNotificationRecord(
                trigger_id=trigger_id,
                channel="__bar_delivery_claim__",
                attempt=1,
                success=False,
                error_code="in_flight",
                retryable=False,
                latency_ms=None,
                diagnostics=owner_diag,
                created_at=now_dt,
            )
            session.add(claim)
            session.flush()
            return True, "claimed", int(claim.id)

    def commit_bar_delivery_dispatch(
        self,
        claim_id: int,
        *,
        owner_token: str,
        now: Optional[datetime] = None,
    ) -> bool:
        """Persistently transition an active pre-dispatch lease to non-reclaimable dispatch_committed."""
        if not owner_token or not str(owner_token).strip():
            raise ValueError("owner_token is required")
        now_dt = now or datetime.now()
        owner_diag = f"owner={owner_token}"
        with self._sqlite_immediate_session() as (session, _):
            row = session.execute(
                select(AlertNotificationRecord)
                .where(
                    AlertNotificationRecord.id == claim_id,
                    AlertNotificationRecord.channel == "__bar_delivery_claim__",
                    AlertNotificationRecord.error_code == "in_flight",
                    AlertNotificationRecord.retryable.is_(False),
                    AlertNotificationRecord.diagnostics == owner_diag,
                )
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return False
            row.error_code = "dispatch_committed"
            row.created_at = now_dt
            return True

    def renew_bar_delivery_claim(
        self,
        claim_id: int,
        *,
        owner_token: str,
        now: Optional[datetime] = None,
    ) -> bool:
        """Renew an active delivery claim timestamp only if still owned by ``owner_token``."""
        if not owner_token or not str(owner_token).strip():
            raise ValueError("owner_token is required")
        now_dt = now or datetime.now()
        owner_diag = f"owner={owner_token}"
        with self._sqlite_immediate_session() as (session, _):
            row = session.execute(
                select(AlertNotificationRecord)
                .where(
                    AlertNotificationRecord.id == claim_id,
                    AlertNotificationRecord.channel == "__bar_delivery_claim__",
                    AlertNotificationRecord.error_code.in_(_ACTIVE_CLAIM_ERROR_CODES),
                    AlertNotificationRecord.retryable.is_(False),
                    AlertNotificationRecord.diagnostics == owner_diag,
                )
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return False
            row.created_at = now_dt
            return True

    def release_bar_delivery_claim(
        self,
        claim_id: int,
        *,
        owner_token: Optional[str] = None,
    ) -> bool:
        """Delete an active completed-bar delivery claim row after attempt finishes."""
        with self._sqlite_immediate_session() as (session, _):
            stmt = delete(AlertNotificationRecord).where(
                AlertNotificationRecord.id == claim_id,
                AlertNotificationRecord.channel == "__bar_delivery_claim__",
                AlertNotificationRecord.error_code.in_(_ACTIVE_CLAIM_ERROR_CODES),
                AlertNotificationRecord.retryable.is_(False),
            )
            if owner_token is not None:
                stmt = stmt.where(AlertNotificationRecord.diagnostics == f"owner={owner_token}")
            res = session.execute(stmt)
            return bool(res.rowcount)

    def mark_bar_delivery_claim_unrecorded(
        self,
        trigger_id: int,
        claim_id: Optional[int],
        *,
        owner_token: str,
        detail: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> bool:
        """Convert an active delivery claim into a non-expiring reconciliation hold."""
        if not owner_token or not str(owner_token).strip():
            raise ValueError("owner_token is required")
        now_dt = now or datetime.now()
        suffix = f"; {detail}" if detail else ""
        diag = f"owner={owner_token}{suffix}"[:255]
        owner_diag = f"owner={owner_token}"
        with self._sqlite_immediate_session() as (session, _):
            if claim_id is not None:
                row = session.execute(
                    select(AlertNotificationRecord)
                    .where(
                        AlertNotificationRecord.id == claim_id,
                        AlertNotificationRecord.channel == "__bar_delivery_claim__",
                        AlertNotificationRecord.error_code.in_(_ACTIVE_CLAIM_ERROR_CODES),
                        AlertNotificationRecord.retryable.is_(False),
                        AlertNotificationRecord.diagnostics == owner_diag,
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if row is not None:
                    row.error_code = "delivery_unrecorded"
                    row.retryable = False
                    row.diagnostics = diag
                    row.created_at = now_dt
                    return True
            existing = session.execute(
                select(AlertNotificationRecord.id)
                .where(
                    AlertNotificationRecord.trigger_id == trigger_id,
                    AlertNotificationRecord.channel == "__bar_delivery_claim__",
                    AlertNotificationRecord.error_code == "delivery_unrecorded",
                    AlertNotificationRecord.retryable.is_(False),
                )
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                return True
            session.add(
                AlertNotificationRecord(
                    trigger_id=trigger_id,
                    channel="__bar_delivery_claim__",
                    attempt=1,
                    success=False,
                    error_code="delivery_unrecorded",
                    retryable=False,
                    latency_ms=None,
                    diagnostics=diag,
                    created_at=now_dt,
                )
            )
            session.flush()
            return True

    def has_successful_notification(self, trigger_id: int) -> bool:
        with self.db.get_session() as session:
            channels = session.execute(
                select(AlertNotificationRecord.channel).where(
                    AlertNotificationRecord.trigger_id == trigger_id,
                    AlertNotificationRecord.success.is_(True),
                )
            ).scalars().all()
            return any(bool(ch) and not str(ch).startswith("__") for ch in channels)

    def get_active_cooldown(
        self,
        *,
        rule_id: int,
        target: str,
        severity: Optional[str],
        now: Optional[datetime] = None,
    ) -> Optional[AlertCooldownRecord]:
        now_value = now or datetime.now()
        with self.db.get_session() as session:
            return session.execute(
                select(AlertCooldownRecord)
                .where(
                    AlertCooldownRecord.rule_id == rule_id,
                    AlertCooldownRecord.target == target,
                    AlertCooldownRecord.severity == severity,
                    AlertCooldownRecord.state == "active",
                    AlertCooldownRecord.cooldown_until > now_value,
                )
                .order_by(desc(AlertCooldownRecord.cooldown_until), desc(AlertCooldownRecord.id))
                .limit(1)
            ).scalar_one_or_none()

    def upsert_cooldown(
        self,
        *,
        rule_id: int,
        rule_key: Optional[str],
        target: str,
        severity: Optional[str],
        last_triggered_at: datetime,
        cooldown_until: datetime,
        reason: Optional[str] = None,
        state: str = "active",
    ) -> AlertCooldownRecord:
        with self.db.get_session() as session:
            row = session.execute(
                select(AlertCooldownRecord)
                .where(
                    AlertCooldownRecord.rule_id == rule_id,
                    AlertCooldownRecord.target == target,
                    AlertCooldownRecord.severity == severity,
                )
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                row = AlertCooldownRecord(
                    rule_id=rule_id,
                    rule_key=rule_key,
                    target=target,
                    severity=severity,
                )
                session.add(row)
            row.rule_key = rule_key
            row.last_triggered_at = last_triggered_at
            row.cooldown_until = cooldown_until
            row.reason = reason
            row.state = state
            row.updated_at = datetime.now()
            session.commit()
            session.refresh(row)
            return row

    def get_rule_cooldown_summary(
        self,
        *,
        rule_id: int,
        target: str,
        severity: Optional[str],
    ) -> Optional[AlertCooldownRecord]:
        with self.db.get_session() as session:
            return session.execute(
                select(AlertCooldownRecord)
                .where(
                    AlertCooldownRecord.rule_id == rule_id,
                    AlertCooldownRecord.target == target,
                    AlertCooldownRecord.severity == severity,
                )
                .order_by(desc(AlertCooldownRecord.updated_at), desc(AlertCooldownRecord.id))
                .limit(1)
            ).scalar_one_or_none()

    def list_triggers(
        self,
        *,
        rule_id: Optional[int] = None,
        target: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AlertTriggerRecord], int]:
        conditions = []
        if rule_id is not None:
            conditions.append(AlertTriggerRecord.rule_id == rule_id)
        if target:
            conditions.append(AlertTriggerRecord.target == target)
        if status:
            conditions.append(AlertTriggerRecord.status == status)

        where_clause = and_(*conditions) if conditions else True
        offset = (page - 1) * page_size
        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(AlertTriggerRecord.id)).select_from(AlertTriggerRecord).where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(AlertTriggerRecord)
                .where(where_clause)
                .order_by(desc(AlertTriggerRecord.triggered_at), desc(AlertTriggerRecord.id))
                .offset(offset)
                .limit(page_size)
            ).scalars().all()
            return list(rows), int(total)

    def list_notifications(
        self,
        *,
        trigger_id: Optional[int] = None,
        channel: Optional[str] = None,
        success: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[AlertNotificationRecord], int]:
        conditions = []
        if trigger_id is not None:
            conditions.append(AlertNotificationRecord.trigger_id == trigger_id)
        if channel:
            conditions.append(AlertNotificationRecord.channel == channel)
        if success is not None:
            conditions.append(AlertNotificationRecord.success.is_(success))

        where_clause = and_(*conditions) if conditions else True
        offset = (page - 1) * page_size
        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(AlertNotificationRecord.id))
                .select_from(AlertNotificationRecord)
                .where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(AlertNotificationRecord)
                .where(where_clause)
                .order_by(desc(AlertNotificationRecord.created_at), desc(AlertNotificationRecord.id))
                .offset(offset)
                .limit(page_size)
            ).scalars().all()
            return list(rows), int(total)
