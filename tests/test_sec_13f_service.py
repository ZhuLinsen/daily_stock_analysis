# -*- coding: utf-8 -*-
"""Offline contract tests for SEC Form 13F parsing and share deltas."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from src.services.sec_13f_service import (
    SEC_SUBMISSIONS_URL,
    FilingReference,
    FilingSnapshotData,
    HoldingRecord,
    Sec13FClient,
    analyze_latest_holdings,
    normalize_cik,
    parse_filing_snapshot,
    select_effective_filings,
)

PRIMARY_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <headerData><submissionType>13F-HR</submissionType></headerData>
  <formData>
    <coverPage>
      <reportCalendarOrQuarter>03-31-2026</reportCalendarOrQuarter>
      <filingManager><name>H&amp;H International Investment, LLC</name></filingManager>
    </coverPage>
    <summaryPage>
      <tableEntryTotal>3</tableEntryTotal>
      <tableValueTotal>350</tableValueTotal>
    </summaryPage>
  </formData>
  <periodOfReport>2026-03-31</periodOfReport>
</edgarSubmission>
"""


INFORMATION_TABLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip><figi>BBG001S5N8V8</figi><value>200</value>
    <shrsOrPrnAmt><sshPrnamt>8</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority><Sole>8</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip><figi>BBG001S5N8V8</figi><value>50</value>
    <shrsOrPrnAmt><sshPrnamt>2</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority><Sole>2</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>NEW CO</nameOfIssuer><titleOfClass>CL A</titleOfClass>
    <cusip>000000002</cusip><value>100</value>
    <shrsOrPrnAmt><sshPrnamt>5</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority><Sole>5</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
</informationTable>
"""


class _FakeResponse:
    def __init__(self, *, payload=None, content=b""):
        self._payload = payload
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses[url]


def _reference(**overrides) -> FilingReference:
    values = {
        "manager_cik": "0001759760",
        "manager_name": "H&H International Investment, LLC",
        "form_type": "13F-HR",
        "accession_number": "0001759760-26-000005",
        "report_period": date(2026, 3, 31),
        "filed_date": date(2026, 5, 19),
        "accepted_at": datetime(2026, 5, 18, 20, 22, 8, tzinfo=timezone.utc),
        "primary_document": "primary_doc.xml",
    }
    values.update(overrides)
    return FilingReference(**values)


def _holding(
    issuer: str,
    cusip: str,
    *,
    shares: int,
    value: int,
) -> HoldingRecord:
    return HoldingRecord(
        issuer_name=issuer,
        title_of_class="COM",
        cusip=cusip,
        figi=None,
        value_usd=value,
        shares=Decimal(shares),
        share_type="SH",
        put_call="",
        investment_discretion="SOLE",
        voting_sole=shares,
        voting_shared=0,
        voting_none=0,
    )


def _snapshot(period: date, accession: str, holdings) -> FilingSnapshotData:
    reference = _reference(
        accession_number=accession,
        report_period=period,
        filed_date=period,
        accepted_at=datetime.combine(period, datetime.min.time(), tzinfo=timezone.utc),
    )
    return FilingSnapshotData(
        reference=reference,
        manager_name=reference.manager_name,
        entry_count=len(holdings),
        total_value_usd=sum(item.value_usd for item in holdings),
        primary_document_url="https://example.test/primary.xml",
        information_table_url="https://example.test/info.xml",
        source_sha256="a" * 64,
        holdings=tuple(holdings),
    )


def test_normalize_cik_is_strict_and_canonical() -> None:
    assert normalize_cik("1759760") == "0001759760"
    assert normalize_cik("CIK0001759760") == "0001759760"
    with pytest.raises(ValueError, match="CIK"):
        normalize_cik("17x9760")


def test_sec_client_requires_contact_identity() -> None:
    with pytest.raises(ValueError, match="contact email"):
        Sec13FClient(user_agent="daily-stock-analysis")


def test_sec_client_lists_only_13f_filings_and_sends_identity_header() -> None:
    submissions_url = SEC_SUBMISSIONS_URL.format(cik="0001759760")
    session = _FakeSession(
        {
            submissions_url: _FakeResponse(
                payload={
                    "name": "H&H International Investment, LLC",
                    "filings": {
                        "recent": {
                            "form": ["N-PX", "13F-HR", "13F-HR/A"],
                            "accessionNumber": [
                                "0001759760-26-000006",
                                "0001759760-26-000004",
                                "0001759760-26-000005",
                            ],
                            "reportDate": ["2026-06-30", "2026-03-31", "2026-03-31"],
                            "filingDate": ["2026-07-07", "2026-05-15", "2026-05-19"],
                            "acceptanceDateTime": [
                                "2026-07-07T12:00:00Z",
                                "2026-05-15T12:00:00Z",
                                "2026-05-18T20:22:08Z",
                            ],
                            "primaryDocument": ["primary.xml", "primary.xml", "primary_doc.xml"],
                        }
                    },
                }
            )
        }
    )
    client = Sec13FClient(
        user_agent="daily-stock-analysis tests@example.com",
        session=session,
        min_request_interval_seconds=0,
    )

    filings = client.list_recent_filings("1759760")
    assert [item.form_type for item in filings] == ["13F-HR/A", "13F-HR"]
    assert session.calls[0][1]["headers"]["User-Agent"].endswith("tests@example.com")


def test_sec_client_fetches_information_table_selected_from_directory_index() -> None:
    reference = _reference()
    directory_url = reference.archive_directory_url
    session = _FakeSession(
        {
            f"{directory_url}/index.json": _FakeResponse(
                payload={
                    "directory": {
                        "item": [
                            {"name": "primary_doc.xml"},
                            {"name": "infotable.xml"},
                            {"name": "0001759760-26-000005.txt"},
                        ]
                    }
                }
            ),
            f"{directory_url}/primary_doc.xml": _FakeResponse(content=PRIMARY_XML),
            f"{directory_url}/infotable.xml": _FakeResponse(content=INFORMATION_TABLE_XML),
        }
    )
    client = Sec13FClient(
        user_agent="daily-stock-analysis tests@example.com",
        session=session,
        min_request_interval_seconds=0,
    )

    snapshot = client.fetch_snapshot(reference)
    assert snapshot.information_table_url.endswith("/infotable.xml")
    assert snapshot.holdings[0].issuer_name == "APPLE INC"


def test_parse_snapshot_merges_equivalent_rows_and_preserves_reported_totals() -> None:
    snapshot = parse_filing_snapshot(
        _reference(),
        primary_xml=PRIMARY_XML,
        information_table_xml=INFORMATION_TABLE_XML,
        primary_document_url="https://example.test/primary.xml",
        information_table_url="https://example.test/infotable.xml",
    )

    assert snapshot.manager_name == "H&H International Investment, LLC"
    assert snapshot.entry_count == 3
    assert snapshot.total_value_usd == 350
    assert len(snapshot.holdings) == 2
    assert snapshot.holdings[0].issuer_name == "APPLE INC"
    assert snapshot.holdings[0].shares == Decimal("10")
    assert snapshot.holdings[0].value_usd == 250
    assert snapshot.source_sha256 != ""


def test_parse_snapshot_rejects_period_mismatch() -> None:
    with pytest.raises(ValueError, match="period does not match"):
        parse_filing_snapshot(
            _reference(report_period=date(2025, 12, 31)),
            primary_xml=PRIMARY_XML,
            information_table_xml=INFORMATION_TABLE_XML,
            primary_document_url="https://example.test/primary.xml",
            information_table_url="https://example.test/infotable.xml",
        )


def test_pre_2023_reported_values_are_scaled_from_thousands_to_usd() -> None:
    snapshot = parse_filing_snapshot(
        _reference(
            accession_number="0001759760-22-000005",
            report_period=date(2022, 3, 31),
            filed_date=date(2022, 5, 16),
        ),
        primary_xml=PRIMARY_XML.replace(b"2026-03-31", b"2022-03-31"),
        information_table_xml=INFORMATION_TABLE_XML,
        primary_document_url="https://example.test/primary.xml",
        information_table_url="https://example.test/infotable.xml",
    )

    assert snapshot.total_value_usd == 350_000
    assert snapshot.holdings[0].value_usd == 250_000


def test_select_effective_filings_uses_newest_amendment_per_period() -> None:
    original = _reference(
        accession_number="0001759760-26-000004",
        accepted_at=datetime(2026, 5, 15, tzinfo=timezone.utc),
    )
    amendment = _reference(
        accession_number="0001759760-26-000005",
        form_type="13F-HR/A",
        accepted_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
    )
    prior = _reference(
        accession_number="0001759760-26-000001",
        report_period=date(2025, 12, 31),
        accepted_at=datetime(2026, 2, 17, tzinfo=timezone.utc),
    )

    selected = select_effective_filings([original, prior, amendment], limit=2)
    assert [item.accession_number for item in selected] == [
        amendment.accession_number,
        prior.accession_number,
    ]


def test_analysis_uses_share_changes_for_status_and_values_for_weights() -> None:
    previous = _snapshot(
        date(2025, 12, 31),
        "0001759760-26-000001",
        [
            _holding("APPLE INC", "037833100", shares=12, value=600),
            _holding("EXITED CO", "000000001", shares=4, value=400),
        ],
    )
    current = _snapshot(
        date(2026, 3, 31),
        "0001759760-26-000005",
        [
            _holding("APPLE INC", "037833100", shares=10, value=800),
            _holding("NEW CO", "000000002", shares=5, value=200),
        ],
    )

    analysis = analyze_latest_holdings(current, previous)
    by_issuer = {item.issuer_name: item for item in analysis.deltas}
    assert by_issuer["APPLE INC"].status == "decreased"
    assert by_issuer["APPLE INC"].share_delta == Decimal("-2")
    assert by_issuer["APPLE INC"].share_delta_pct == pytest.approx(-16.6666667)
    assert by_issuer["APPLE INC"].current_weight_pct == pytest.approx(80.0)
    assert by_issuer["NEW CO"].status == "new"
    assert by_issuer["EXITED CO"].status == "exited"
    assert by_issuer["EXITED CO"].current_weight_pct is None
    assert analysis.top_4_concentration_pct == pytest.approx(100.0)
    assert analysis.top_6_concentration_pct == pytest.approx(100.0)
