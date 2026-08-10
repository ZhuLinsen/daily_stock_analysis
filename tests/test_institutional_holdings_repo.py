# -*- coding: utf-8 -*-
"""Persistence tests for SEC filing snapshots."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from src.config import Config
from src.storage import DatabaseManager

from src.repositories.institutional_holdings_repo import InstitutionalHoldingsRepository
from src.services.sec_13f_service import (
    FilingReference,
    FilingSnapshotData,
    HoldingRecord,
)


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "institutional_holdings.db")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


def _snapshot(
    *,
    accession: str,
    period: date,
    accepted_at: datetime,
    shares: int,
    source_hash: str,
) -> FilingSnapshotData:
    reference = FilingReference(
        manager_cik="0001759760",
        manager_name="H&H International Investment, LLC",
        form_type="13F-HR",
        accession_number=accession,
        report_period=period,
        filed_date=accepted_at.date(),
        accepted_at=accepted_at,
        primary_document="primary_doc.xml",
    )
    holding = HoldingRecord(
        issuer_name="APPLE INC",
        title_of_class="COM",
        cusip="037833100",
        figi="BBG001S5N8V8",
        value_usd=shares * 100,
        shares=Decimal(shares),
        share_type="SH",
        put_call="",
        investment_discretion="SOLE",
        voting_sole=shares,
        voting_shared=0,
        voting_none=0,
    )
    return FilingSnapshotData(
        reference=reference,
        manager_name=reference.manager_name,
        entry_count=1,
        total_value_usd=holding.value_usd,
        primary_document_url=f"https://example.test/{accession}/primary_doc.xml",
        information_table_url=f"https://example.test/{accession}/infotable.xml",
        source_sha256=source_hash,
        holdings=(holding,),
    )


def test_save_snapshot_is_idempotent_and_refreshes_changed_source(isolated_db) -> None:
    repo = InstitutionalHoldingsRepository(isolated_db)
    original = _snapshot(
        accession="0001759760-26-000005",
        period=date(2026, 3, 31),
        accepted_at=datetime(2026, 5, 18, 20, 22, tzinfo=timezone.utc),
        shares=10,
        source_hash="a" * 64,
    )

    created = repo.save_snapshot(original)
    duplicate = repo.save_snapshot(original)
    changed = repo.save_snapshot(
        _snapshot(
            accession=original.reference.accession_number,
            period=original.reference.report_period,
            accepted_at=original.reference.accepted_at,
            shares=12,
            source_hash="b" * 64,
        )
    )

    assert created.created is True
    assert duplicate.created is False
    assert duplicate.refreshed is False
    assert changed.refreshed is True
    assert created.snapshot_id == duplicate.snapshot_id == changed.snapshot_id
    snapshots = repo.list_effective_snapshots("1759760", limit=2)
    assert len(snapshots) == 1
    assert snapshots[0].holdings[0].shares == Decimal("12")

    table_names = set(inspect(isolated_db._engine).get_table_names())
    assert {"filing_snapshots", "filing_holdings"}.issubset(table_names)


def test_effective_snapshot_list_skips_older_accession_for_same_period(isolated_db) -> None:
    repo = InstitutionalHoldingsRepository(isolated_db)
    period = date(2026, 3, 31)
    repo.save_snapshot(
        _snapshot(
            accession="0001759760-26-000004",
            period=period,
            accepted_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
            shares=10,
            source_hash="a" * 64,
        )
    )
    repo.save_snapshot(
        _snapshot(
            accession="0001759760-26-000005",
            period=period,
            accepted_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
            shares=11,
            source_hash="b" * 64,
        )
    )
    repo.save_snapshot(
        _snapshot(
            accession="0001759760-26-000001",
            period=date(2025, 12, 31),
            accepted_at=datetime(2026, 2, 17, tzinfo=timezone.utc),
            shares=9,
            source_hash="c" * 64,
        )
    )

    snapshots = repo.list_effective_snapshots("0001759760", limit=2)
    assert [item.reference.accession_number for item in snapshots] == [
        "0001759760-26-000005",
        "0001759760-26-000001",
    ]
