# -*- coding: utf-8 -*-
"""API integration tests for public institutional holdings."""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.storage import DatabaseManager

from src.services.sec_13f_service import FilingReference, FilingSnapshotData, HoldingRecord


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


@pytest.fixture()
def client_and_db(tmp_path):
    old_values = {key: os.environ.get(key) for key in ("ENV_FILE", "DATABASE_PATH", "SEC_USER_AGENT")}
    env_path = tmp_path / ".env"
    db_path = tmp_path / "institutional_holdings_api.db"
    static_dir = tmp_path / "empty-static"
    static_dir.mkdir()
    env_path.write_text(
        "\n".join(
            [
                "STOCK_LIST=AAPL",
                "GEMINI_API_KEY=test",
                "ADMIN_AUTH_ENABLED=false",
                f"DATABASE_PATH={db_path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    os.environ["ENV_FILE"] = str(env_path)
    os.environ["DATABASE_PATH"] = str(db_path)
    os.environ["SEC_USER_AGENT"] = "daily-stock-analysis tests@example.com"
    _reset_auth_globals()
    Config.reset_instance()
    DatabaseManager.reset_instance()
    app = create_app(static_dir=Path(static_dir))
    client = TestClient(app)
    db = DatabaseManager.get_instance()
    try:
        yield client, db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        _reset_auth_globals()
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _holding(issuer: str, cusip: str, shares: int, value_usd: int) -> HoldingRecord:
    return HoldingRecord(
        issuer_name=issuer,
        title_of_class="COM",
        cusip=cusip,
        figi=None,
        value_usd=value_usd,
        shares=Decimal(shares),
        share_type="SH",
        put_call="",
        investment_discretion="SOLE",
        voting_sole=shares,
        voting_shared=0,
        voting_none=0,
    )


def _snapshot(
    accession: str,
    period: date,
    accepted_at: datetime,
    holdings,
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
    return FilingSnapshotData(
        reference=reference,
        manager_name=reference.manager_name,
        entry_count=len(holdings),
        total_value_usd=sum(item.value_usd for item in holdings),
        primary_document_url=f"https://example.test/{accession}/primary_doc.xml",
        information_table_url=f"https://example.test/{accession}/infotable.xml",
        source_sha256=accession.replace("-", "").ljust(64, "0")[:64],
        holdings=tuple(holdings),
    )


def test_import_then_latest_analysis_api(client_and_db) -> None:
    client, _db = client_and_db
    previous = _snapshot(
        "0001759760-26-000001",
        date(2025, 12, 31),
        datetime(2026, 2, 17, tzinfo=timezone.utc),
        [
            _holding("APPLE INC", "037833100", 12, 600),
            _holding("EXITED CO", "000000001", 4, 400),
        ],
    )
    current = _snapshot(
        "0001759760-26-000005",
        date(2026, 3, 31),
        datetime(2026, 5, 18, 20, 22, tzinfo=timezone.utc),
        [
            _holding("APPLE INC", "037833100", 10, 800),
            _holding("NEW CO", "000000002", 5, 200),
        ],
    )

    class FakeSecClient:
        def __init__(self, *, user_agent):
            assert user_agent.endswith("tests@example.com")

        def list_recent_filings(self, cik, *, limit):
            assert cik == "0001759760"
            assert limit >= 2
            return [current.reference, previous.reference]

        def fetch_snapshot(self, reference):
            return {
                current.reference.accession_number: current,
                previous.reference.accession_number: previous,
            }[reference.accession_number]

    with patch(
        "api.v1.endpoints.institutional_holdings.Sec13FClient",
        FakeSecClient,
    ):
        imported = client.post(
            "/api/v1/institutional-holdings/import",
            json={"cik": "1759760", "max_filings": 2},
        )

    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == 2
    assert imported.json()["processed"] == 2

    response = client.get("/api/v1/institutional-holdings/1759760/latest")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["current"]["accession_number"] == current.reference.accession_number
    assert payload["previous"]["accession_number"] == previous.reference.accession_number
    assert payload["top_4_concentration_pct"] == pytest.approx(100.0)
    by_issuer = {item["issuer_name"]: item for item in payload["holdings"]}
    assert by_issuer["APPLE INC"]["status"] == "decreased"
    assert by_issuer["NEW CO"]["status"] == "new"
    assert by_issuer["EXITED CO"]["status"] == "exited"
