# -*- coding: utf-8 -*-
"""Persistence for immutable SEC filing snapshots and their holdings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    delete,
    desc,
    select,
)
from src.storage import Base, DatabaseManager, to_utc_naive_datetime, utc_naive_now

from src.services.sec_13f_service import (
    FilingReference,
    FilingSnapshotData,
    HoldingRecord,
    normalize_cik,
)


class FilingSnapshotRecord(Base):
    """One immutable Form 13F accession imported from SEC EDGAR."""

    __tablename__ = "filing_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    manager_cik = Column(String(10), nullable=False, index=True)
    manager_name = Column(String(255), nullable=False)
    form_type = Column(String(16), nullable=False)
    accession_number = Column(String(32), nullable=False, unique=True)
    report_period = Column(Date, nullable=False, index=True)
    filed_date = Column(Date, nullable=False)
    accepted_at = Column(DateTime, nullable=False, index=True)
    primary_document_url = Column(Text, nullable=False)
    information_table_url = Column(Text, nullable=False)
    entry_count = Column(Integer, nullable=False)
    total_value_usd = Column(BigInteger, nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    imported_at = Column(DateTime, nullable=False, default=utc_naive_now, index=True)

    __table_args__ = (
        UniqueConstraint(
            "manager_cik",
            "accession_number",
            name="uix_filing_snapshot_manager_accession",
        ),
        Index(
            "ix_filing_snapshot_manager_period",
            "manager_cik",
            "report_period",
            "accepted_at",
        ),
    )


class FilingHoldingRecord(Base):
    """Aggregated security entry belonging to one filing snapshot."""

    __tablename__ = "filing_holdings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(
        Integer,
        ForeignKey("filing_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issuer_name = Column(String(255), nullable=False)
    title_of_class = Column(String(128), nullable=False)
    cusip = Column(String(16), nullable=False, index=True)
    figi = Column(String(24))
    value_usd = Column(BigInteger, nullable=False)
    shares = Column(Numeric(30, 6), nullable=False)
    share_type = Column(String(16), nullable=False)
    put_call = Column(String(8), nullable=False, default="")
    investment_discretion = Column(String(32))
    voting_sole = Column(BigInteger, nullable=False, default=0)
    voting_shared = Column(BigInteger, nullable=False, default=0)
    voting_none = Column(BigInteger, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "cusip",
            "title_of_class",
            "put_call",
            "share_type",
            name="uix_filing_holding_security",
        ),
        Index("ix_filing_holding_snapshot_value", "snapshot_id", "value_usd"),
    )


@dataclass(frozen=True)
class SaveSnapshotResult:
    snapshot_id: int
    created: bool
    refreshed: bool
    holding_count: int


class InstitutionalHoldingsRepository:
    """Database operations with idempotency keyed by SEC accession."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()
        # The feature's models live in this isolated repository module.  Ensure
        # their tables also exist if this module was imported after DB startup.
        with self.db.get_session() as session:
            Base.metadata.create_all(
                session.get_bind(),
                tables=[FilingSnapshotRecord.__table__, FilingHoldingRecord.__table__],
                checkfirst=True,
            )

    def save_snapshot(self, snapshot: FilingSnapshotData) -> SaveSnapshotResult:
        """Create or deterministically refresh one accession and all its rows."""

        with self.db.session_scope() as session:
            record = session.execute(
                select(FilingSnapshotRecord).where(
                    FilingSnapshotRecord.accession_number == snapshot.reference.accession_number
                )
            ).scalar_one_or_none()

            if record is not None and record.source_sha256 == snapshot.source_sha256:
                count = len(
                    session.execute(select(FilingHoldingRecord.id).where(FilingHoldingRecord.snapshot_id == record.id))
                    .scalars()
                    .all()
                )
                return SaveSnapshotResult(
                    snapshot_id=int(record.id),
                    created=False,
                    refreshed=False,
                    holding_count=count,
                )

            created = record is None
            if record is None:
                record = FilingSnapshotRecord(accession_number=snapshot.reference.accession_number)
                session.add(record)

            record.manager_cik = normalize_cik(snapshot.reference.manager_cik)
            record.manager_name = snapshot.manager_name
            record.form_type = snapshot.reference.form_type
            record.report_period = snapshot.reference.report_period
            record.filed_date = snapshot.reference.filed_date
            record.accepted_at = to_utc_naive_datetime(snapshot.reference.accepted_at)
            record.primary_document_url = snapshot.primary_document_url
            record.information_table_url = snapshot.information_table_url
            record.entry_count = snapshot.entry_count
            record.total_value_usd = snapshot.total_value_usd
            record.source_sha256 = snapshot.source_sha256
            record.imported_at = utc_naive_now()
            session.flush()

            session.execute(delete(FilingHoldingRecord).where(FilingHoldingRecord.snapshot_id == record.id))
            session.add_all(
                [
                    FilingHoldingRecord(
                        snapshot_id=record.id,
                        issuer_name=holding.issuer_name,
                        title_of_class=holding.title_of_class,
                        cusip=holding.cusip,
                        figi=holding.figi,
                        value_usd=holding.value_usd,
                        shares=holding.shares,
                        share_type=holding.share_type,
                        put_call=holding.put_call,
                        investment_discretion=holding.investment_discretion,
                        voting_sole=holding.voting_sole,
                        voting_shared=holding.voting_shared,
                        voting_none=holding.voting_none,
                    )
                    for holding in snapshot.holdings
                ]
            )
            session.flush()
            return SaveSnapshotResult(
                snapshot_id=int(record.id),
                created=created,
                refreshed=not created,
                holding_count=len(snapshot.holdings),
            )

    def list_effective_snapshots(
        self,
        cik: str,
        *,
        limit: int = 2,
    ) -> List[FilingSnapshotData]:
        """Return newest accepted accession for each distinct report period."""

        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        canonical_cik = normalize_cik(cik)
        with self.db.get_session() as session:
            records = (
                session.execute(
                    select(FilingSnapshotRecord)
                    .where(FilingSnapshotRecord.manager_cik == canonical_cik)
                    .order_by(
                        desc(FilingSnapshotRecord.report_period),
                        desc(FilingSnapshotRecord.accepted_at),
                    )
                )
                .scalars()
                .all()
            )

            snapshots: List[FilingSnapshotData] = []
            seen_periods = set()
            for record in records:
                if record.report_period in seen_periods:
                    continue
                seen_periods.add(record.report_period)
                holding_records = (
                    session.execute(
                        select(FilingHoldingRecord)
                        .where(FilingHoldingRecord.snapshot_id == record.id)
                        .order_by(desc(FilingHoldingRecord.value_usd))
                    )
                    .scalars()
                    .all()
                )
                snapshots.append(self._to_snapshot(record, holding_records))
                if len(snapshots) >= limit:
                    break
            return snapshots

    @staticmethod
    def _to_snapshot(
        record: FilingSnapshotRecord,
        holding_records: List[FilingHoldingRecord],
    ) -> FilingSnapshotData:
        accepted_at = record.accepted_at
        if accepted_at.tzinfo is None:
            accepted_at = accepted_at.replace(tzinfo=timezone.utc)
        reference = FilingReference(
            manager_cik=record.manager_cik,
            manager_name=record.manager_name,
            form_type=record.form_type,
            accession_number=record.accession_number,
            report_period=record.report_period,
            filed_date=record.filed_date,
            accepted_at=accepted_at.astimezone(timezone.utc),
            primary_document=record.primary_document_url.rsplit("/", 1)[-1],
        )
        holdings = tuple(
            HoldingRecord(
                issuer_name=item.issuer_name,
                title_of_class=item.title_of_class,
                cusip=item.cusip,
                figi=item.figi,
                value_usd=int(item.value_usd),
                shares=Decimal(str(item.shares)),
                share_type=item.share_type,
                put_call=item.put_call or "",
                investment_discretion=item.investment_discretion,
                voting_sole=int(item.voting_sole or 0),
                voting_shared=int(item.voting_shared or 0),
                voting_none=int(item.voting_none or 0),
            )
            for item in holding_records
        )
        return FilingSnapshotData(
            reference=reference,
            manager_name=record.manager_name,
            entry_count=int(record.entry_count),
            total_value_usd=int(record.total_value_usd),
            primary_document_url=record.primary_document_url,
            information_table_url=record.information_table_url,
            source_sha256=record.source_sha256,
            holdings=holdings,
        )
