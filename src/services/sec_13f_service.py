# -*- coding: utf-8 -*-
"""SEC Form 13F ingestion and deterministic holding-delta analysis.

The module deliberately keeps network parsing independent from persistence so
the SEC wire contract can be tested offline.  Values are interpreted exactly as
reported by the current Form 13F XML schema (nearest US dollar).
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_USER_AGENT_ENV = "SEC_USER_AGENT"
SUPPORTED_13F_FORMS = frozenset({"13F-HR", "13F-HR/A"})
FORM_13F_DOLLAR_VALUES_EFFECTIVE_DATE = date(2023, 1, 3)
_ACCESSION_PATTERN = re.compile(r"^\d{10}-\d{2}-\d{6}$")


@dataclass(frozen=True)
class FilingReference:
    """Location and filing-time facts from the SEC submissions feed."""

    manager_cik: str
    manager_name: str
    form_type: str
    accession_number: str
    report_period: date
    filed_date: date
    accepted_at: datetime
    primary_document: str

    @property
    def accession_compact(self) -> str:
        return self.accession_number.replace("-", "")

    @property
    def archive_directory_url(self) -> str:
        return f"{SEC_ARCHIVES_URL}/{int(self.manager_cik)}/{self.accession_compact}"


@dataclass(frozen=True)
class HoldingRecord:
    """One security row after equivalent information-table rows are merged."""

    issuer_name: str
    title_of_class: str
    cusip: str
    figi: Optional[str]
    value_usd: int
    shares: Decimal
    share_type: str
    put_call: str
    investment_discretion: Optional[str]
    voting_sole: int
    voting_shared: int
    voting_none: int

    @property
    def security_key(self) -> Tuple[str, str, str, str]:
        return (
            self.cusip.upper(),
            self.title_of_class.upper(),
            self.put_call.upper(),
            self.share_type.upper(),
        )


@dataclass(frozen=True)
class FilingSnapshotData:
    """Parsed, immutable facts for one SEC accession."""

    reference: FilingReference
    manager_name: str
    entry_count: int
    total_value_usd: int
    primary_document_url: str
    information_table_url: str
    source_sha256: str
    holdings: Tuple[HoldingRecord, ...]


@dataclass(frozen=True)
class HoldingDelta:
    """Share-count change between two effective quarterly snapshots."""

    issuer_name: str
    title_of_class: str
    cusip: str
    put_call: str
    status: str
    current_shares: Optional[Decimal]
    previous_shares: Optional[Decimal]
    share_delta: Optional[Decimal]
    share_delta_pct: Optional[float]
    current_value_usd: Optional[int]
    previous_value_usd: Optional[int]
    current_weight_pct: Optional[float]


@dataclass(frozen=True)
class PortfolioAnalysis:
    """Latest disclosure plus its prior-quarter comparison."""

    current: FilingSnapshotData
    previous: Optional[FilingSnapshotData]
    deltas: Tuple[HoldingDelta, ...]
    top_4_concentration_pct: float
    top_6_concentration_pct: float


def normalize_cik(value: str) -> str:
    """Return the SEC's canonical ten-digit CIK representation."""

    raw = str(value or "").strip().upper()
    if raw.startswith("CIK"):
        raw = raw[3:]
    if not raw.isdigit() or len(raw) > 10:
        raise ValueError("CIK must contain between 1 and 10 digits")
    return raw.zfill(10)


def select_effective_filings(
    references: Iterable[FilingReference],
    *,
    limit: int,
) -> List[FilingReference]:
    """Select the newest accession per report period.

    Amendments are separate accessions.  Treating an amendment as a new quarter
    would compare it with the original filing from the same period, so the
    newest accepted accession wins for each period.
    """

    if limit < 1:
        raise ValueError("limit must be at least 1")
    by_period: Dict[date, FilingReference] = {}
    for reference in references:
        current = by_period.get(reference.report_period)
        if current is None or reference.accepted_at > current.accepted_at:
            by_period[reference.report_period] = reference
    return sorted(
        by_period.values(),
        key=lambda item: (item.report_period, item.accepted_at),
        reverse=True,
    )[:limit]


class Sec13FClient:
    """Small SEC client honoring fair-access identity and request pacing."""

    def __init__(
        self,
        *,
        user_agent: str,
        session: Optional[Any] = None,
        timeout_seconds: int = 30,
        min_request_interval_seconds: float = 0.12,
    ) -> None:
        identity = str(user_agent or "").strip()
        if not identity or "@" not in identity:
            raise ValueError("SEC_USER_AGENT must identify the application and include a contact email")
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if min_request_interval_seconds < 0:
            raise ValueError("min_request_interval_seconds cannot be negative")

        self.user_agent = identity
        self.timeout_seconds = int(timeout_seconds)
        self.min_request_interval_seconds = float(min_request_interval_seconds)
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

        if session is None:
            configured_session = requests.Session()
            retry = Retry(
                total=3,
                connect=3,
                read=3,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                respect_retry_after_header=True,
            )
            adapter = HTTPAdapter(max_retries=retry)
            configured_session.mount("https://", adapter)
            self.session = configured_session
        else:
            self.session = session

    def list_recent_filings(self, cik: str, *, limit: int = 20) -> List[FilingReference]:
        canonical_cik = normalize_cik(cik)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        payload = self._get_json(SEC_SUBMISSIONS_URL.format(cik=canonical_cik))
        manager_name = str(payload.get("name") or "").strip()
        recent = payload.get("filings", {}).get("recent", {})
        if not isinstance(recent, dict):
            raise ValueError("SEC submissions response is missing filings.recent")

        forms = recent.get("form") or []
        references: List[FilingReference] = []
        for index, form in enumerate(forms):
            normalized_form = str(form or "").strip().upper()
            if normalized_form not in SUPPORTED_13F_FORMS:
                continue
            try:
                accession_number = str(recent["accessionNumber"][index]).strip()
                if not _ACCESSION_PATTERN.fullmatch(accession_number):
                    raise ValueError("invalid accession number")
                report_period = _parse_date(recent["reportDate"][index], "reportDate")
                filed_date = _parse_date(recent["filingDate"][index], "filingDate")
                acceptance_values = recent.get("acceptanceDateTime") or []
                acceptance_value = (
                    acceptance_values[index]
                    if index < len(acceptance_values)
                    else f"{filed_date.isoformat()}T00:00:00Z"
                )
                primary_document = str(recent["primaryDocument"][index]).strip()
                if not primary_document or "/" in primary_document or "\\" in primary_document:
                    raise ValueError("invalid primary document name")
            except (IndexError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid SEC filing metadata at index {index}: {exc}") from exc

            references.append(
                FilingReference(
                    manager_cik=canonical_cik,
                    manager_name=manager_name,
                    form_type=normalized_form,
                    accession_number=accession_number,
                    report_period=report_period,
                    filed_date=filed_date,
                    accepted_at=_parse_datetime(acceptance_value, "acceptanceDateTime"),
                    primary_document=primary_document,
                )
            )

        references.sort(key=lambda item: item.accepted_at, reverse=True)
        return references[:limit]

    def fetch_snapshot(self, reference: FilingReference) -> FilingSnapshotData:
        directory_url = reference.archive_directory_url
        index_payload = self._get_json(f"{directory_url}/index.json")
        information_table_name = _select_information_table_name(index_payload)
        primary_url = f"{directory_url}/{reference.primary_document}"
        information_table_url = f"{directory_url}/{information_table_name}"
        primary_xml = self._get_bytes(primary_url)
        information_table_xml = self._get_bytes(information_table_url)
        return parse_filing_snapshot(
            reference,
            primary_xml=primary_xml,
            information_table_xml=information_table_xml,
            primary_document_url=primary_url,
            information_table_url=information_table_url,
        )

    def _get_json(self, url: str) -> Dict[str, Any]:
        response = self._get(url)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"SEC response is not an object: {url}")
        return payload

    def _get_bytes(self, url: str) -> bytes:
        response = self._get(url)
        content = bytes(response.content)
        if not content:
            raise ValueError(f"SEC response is empty: {url}")
        return content

    def _get(self, url: str):
        with self._request_lock:
            elapsed = time.monotonic() - self._last_request_at
            delay = self.min_request_interval_seconds - elapsed
            if delay > 0:
                time.sleep(delay)
            response = self.session.get(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept-Encoding": "gzip, deflate",
                    "Accept": "application/json, application/xml, text/xml, */*",
                },
                timeout=(5, self.timeout_seconds),
            )
            self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response


def parse_filing_snapshot(
    reference: FilingReference,
    *,
    primary_xml: bytes,
    information_table_xml: bytes,
    primary_document_url: str,
    information_table_url: str,
) -> FilingSnapshotData:
    """Parse one filing without performing network or database operations."""

    try:
        primary_root = ElementTree.fromstring(primary_xml)
        table_root = ElementTree.fromstring(information_table_xml)
    except ElementTree.ParseError as exc:
        raise ValueError(f"invalid SEC 13F XML: {exc}") from exc

    filing_manager = _first_element(primary_root, "filingManager")
    manager_name = (
        _descendant_text(filing_manager, "name") if filing_manager is not None else None
    ) or reference.manager_name

    period_text = _descendant_text(primary_root, "periodOfReport")
    if period_text:
        parsed_period = _parse_date(period_text, "periodOfReport")
        if parsed_period != reference.report_period:
            raise ValueError(
                "SEC primary document period does not match submissions metadata: "
                f"{parsed_period} != {reference.report_period}"
            )

    value_scale = 1 if reference.filed_date >= FORM_13F_DOLLAR_VALUES_EFFECTIVE_DATE else 1000
    raw_rows = [item for item in table_root.iter() if _local_name(item.tag) == "infoTable"]
    aggregates: Dict[Tuple[str, str, str, str], HoldingRecord] = {}
    for row_index, row in enumerate(raw_rows):
        issuer_name = _required_text(row, "nameOfIssuer", row_index)
        title_of_class = _required_text(row, "titleOfClass", row_index)
        cusip = _required_text(row, "cusip", row_index).upper()
        figi = _descendant_text(row, "figi")
        value_usd = _parse_int(_required_text(row, "value", row_index), "value") * value_scale
        shares = _parse_decimal(
            _required_text(row, "sshPrnamt", row_index),
            "sshPrnamt",
        )
        share_type = (_descendant_text(row, "sshPrnamtType") or "SH").upper()
        put_call = (_descendant_text(row, "putCall") or "").upper()
        discretion = _descendant_text(row, "investmentDiscretion")
        voting_sole = _parse_optional_int(_descendant_text(row, "Sole"))
        voting_shared = _parse_optional_int(_descendant_text(row, "Shared"))
        voting_none = _parse_optional_int(_descendant_text(row, "None"))

        candidate = HoldingRecord(
            issuer_name=issuer_name,
            title_of_class=title_of_class,
            cusip=cusip,
            figi=figi,
            value_usd=value_usd,
            shares=shares,
            share_type=share_type,
            put_call=put_call,
            investment_discretion=discretion,
            voting_sole=voting_sole,
            voting_shared=voting_shared,
            voting_none=voting_none,
        )
        existing = aggregates.get(candidate.security_key)
        if existing is None:
            aggregates[candidate.security_key] = candidate
        else:
            aggregates[candidate.security_key] = HoldingRecord(
                issuer_name=existing.issuer_name,
                title_of_class=existing.title_of_class,
                cusip=existing.cusip,
                figi=existing.figi or candidate.figi,
                value_usd=existing.value_usd + candidate.value_usd,
                shares=existing.shares + candidate.shares,
                share_type=existing.share_type,
                put_call=existing.put_call,
                investment_discretion=existing.investment_discretion,
                voting_sole=existing.voting_sole + candidate.voting_sole,
                voting_shared=existing.voting_shared + candidate.voting_shared,
                voting_none=existing.voting_none + candidate.voting_none,
            )

    holdings = tuple(sorted(aggregates.values(), key=lambda item: item.value_usd, reverse=True))
    reported_entry_count = _parse_optional_int(_descendant_text(primary_root, "tableEntryTotal"))
    reported_total_value = _parse_optional_int(_descendant_text(primary_root, "tableValueTotal")) * value_scale
    source_sha256 = hashlib.sha256(primary_xml + b"\0" + information_table_xml).hexdigest()
    return FilingSnapshotData(
        reference=reference,
        manager_name=manager_name,
        entry_count=reported_entry_count or len(raw_rows),
        total_value_usd=reported_total_value or sum(item.value_usd for item in holdings),
        primary_document_url=primary_document_url,
        information_table_url=information_table_url,
        source_sha256=source_sha256,
        holdings=holdings,
    )


def analyze_latest_holdings(
    current: FilingSnapshotData,
    previous: Optional[FilingSnapshotData],
) -> PortfolioAnalysis:
    """Calculate weights and share-count deltas without inferring trades from value."""

    current_by_key = {item.security_key: item for item in current.holdings}
    previous_by_key = {item.security_key: item for item in previous.holdings} if previous else {}
    total_current_value = sum(item.value_usd for item in current.holdings)
    deltas: List[HoldingDelta] = []

    for key in current_by_key.keys() | previous_by_key.keys():
        current_holding = current_by_key.get(key)
        previous_holding = previous_by_key.get(key)
        if current_holding is None:
            status = "exited"
            share_delta = -previous_holding.shares if previous_holding else None
        elif previous_holding is None:
            status = "new"
            share_delta = current_holding.shares
        else:
            share_delta = current_holding.shares - previous_holding.shares
            if share_delta > 0:
                status = "increased"
            elif share_delta < 0:
                status = "decreased"
            else:
                status = "unchanged"

        share_delta_pct: Optional[float] = None
        if previous_holding is not None and previous_holding.shares != 0 and share_delta is not None:
            share_delta_pct = float((share_delta / previous_holding.shares) * Decimal("100"))
        current_weight_pct: Optional[float] = None
        if current_holding is not None and total_current_value > 0:
            current_weight_pct = current_holding.value_usd / total_current_value * 100

        representative = current_holding or previous_holding
        if representative is None:  # pragma: no cover - union guarantees one side.
            continue
        deltas.append(
            HoldingDelta(
                issuer_name=representative.issuer_name,
                title_of_class=representative.title_of_class,
                cusip=representative.cusip,
                put_call=representative.put_call,
                status=status,
                current_shares=current_holding.shares if current_holding else None,
                previous_shares=previous_holding.shares if previous_holding else None,
                share_delta=share_delta,
                share_delta_pct=share_delta_pct,
                current_value_usd=current_holding.value_usd if current_holding else None,
                previous_value_usd=previous_holding.value_usd if previous_holding else None,
                current_weight_pct=current_weight_pct,
            )
        )

    deltas.sort(
        key=lambda item: (
            0 if item.current_value_usd is not None else 1,
            -(item.current_value_usd or item.previous_value_usd or 0),
            item.issuer_name,
        )
    )
    return PortfolioAnalysis(
        current=current,
        previous=previous,
        deltas=tuple(deltas),
        top_4_concentration_pct=_concentration(current.holdings, 4),
        top_6_concentration_pct=_concentration(current.holdings, 6),
    )


def _concentration(holdings: Sequence[HoldingRecord], count: int) -> float:
    total = sum(item.value_usd for item in holdings)
    if total <= 0:
        return 0.0
    largest = sorted((item.value_usd for item in holdings), reverse=True)[:count]
    return sum(largest) / total * 100


def _select_information_table_name(index_payload: Dict[str, Any]) -> str:
    items = index_payload.get("directory", {}).get("item", [])
    names = [str(item.get("name") or "").strip() for item in items if isinstance(item, dict)]
    names = [name for name in names if name and "/" not in name and "\\" not in name]
    preferred = [
        name for name in names if name.lower().endswith(".xml") and "info" in name.lower() and "table" in name.lower()
    ]
    fallback = [name for name in names if name.lower().endswith(".xml") and not name.lower().startswith("primary")]
    candidates = preferred or fallback
    if not candidates:
        raise ValueError("SEC filing directory has no information-table XML")
    return sorted(candidates, key=lambda name: (len(name), name.lower()))[0]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_element(root: ElementTree.Element, name: str) -> Optional[ElementTree.Element]:
    return next((item for item in root.iter() if _local_name(item.tag) == name), None)


def _descendant_text(root: Optional[ElementTree.Element], name: str) -> Optional[str]:
    if root is None:
        return None
    element = _first_element(root, name)
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _required_text(root: ElementTree.Element, name: str, row_index: int) -> str:
    value = _descendant_text(root, name)
    if value is None:
        raise ValueError(f"SEC information-table row {row_index} is missing {name}")
    return value


def _parse_date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc


def _parse_datetime(value: Any, field: str) -> datetime:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"invalid {field}: {value!r}")
    return parsed


def _parse_int(value: Any, field: str) -> int:
    parsed = _parse_decimal(value, field)
    integral = parsed.to_integral_value()
    if parsed != integral:
        raise ValueError(f"{field} must be an integer: {value!r}")
    return int(integral)


def _parse_optional_int(value: Optional[str]) -> int:
    return 0 if value in (None, "") else _parse_int(value, "integer")
