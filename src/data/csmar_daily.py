"""Local CSMAR TRD_Dalyr reader for opt-in A-share sentiment snapshots."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import warnings
import zipfile

import openpyxl


REQUIRED_FIELDS = (
    "Stkcd", "Trddt", "Markettype", "Trdsta", "Dnshrtrd",
    "Hiprc", "Clsprc", "LimitUp", "LimitStatus",
)


class CsmarSourceError(ValueError):
    """The local export is absent, malformed, or lacks required dates."""


@dataclass
class CsmarDay:
    row_count: int = 0
    normal_main_count: int = 0
    eligible_count: int = 0
    no_price_limit_count: int = 0
    closed: set[str] = field(default_factory=set)
    touched: set[str] = field(default_factory=set)
    broken: set[str] = field(default_factory=set)
    issues: Counter[str] = field(default_factory=Counter)
    seen_codes: set[str] = field(default_factory=set, repr=False)
    issue_codes: set[str] = field(default_factory=set, repr=False)
    global_issues: bool = False


@dataclass
class CsmarDataset:
    days: dict[date, CsmarDay]
    as_of_sha256: str
    source_file: str
    row_count_as_of: int
    sheet_name: str
    advertised_dimension: str
    actual_columns: int


def apply_csmar_row(pool: CsmarDay, values: dict) -> bool:
    """Accumulate one row using the existing snapshot scope; return eligibility."""
    pool.row_count += 1
    raw_code = values["Stkcd"]
    code = str(raw_code).strip() if raw_code is not None else ""
    if not code.isascii() or not code.isdigit() or len(code) > 6:
        _record_issue(pool, "invalid_stock_code")
        return False
    code = code.zfill(6)
    if code in pool.seen_codes:
        _record_issue(pool, "duplicate_stock_code", code)
    pool.seen_codes.add(code)
    market, trade_status = values["Markettype"], values["Trdsta"]
    if (
        not _finite_number(market) or market not in (1, 2, 4, 8, 16, 32, 64)
        or not _finite_number(trade_status) or trade_status not in range(1, 17)
    ):
        _record_issue(pool, "invalid_market_or_trade_status", code)
        return False
    if market not in (1, 4) or trade_status != 1:
        return False
    pool.normal_main_count += 1
    volume, high, close, limit, status = (values[k] for k in (
        "Dnshrtrd", "Hiprc", "Clsprc", "LimitUp", "LimitStatus"))
    if not _finite_number(volume) or volume <= 0:
        _record_issue(pool, "normal_main_zero_volume", code)
        return False
    if (
        limit is None and status is None
        and _finite_number(high) and high > 0
        and _finite_number(close) and close > 0
    ):
        pool.no_price_limit_count += 1
        # Missing source values alone do not prove that this stock had no limit.
        _record_issue(pool, "ambiguous_price_limit", code)
        return False
    if (
        not _finite_number(limit) or limit <= 0
        or not _finite_number(high) or high <= 0
        or not _finite_number(close) or close <= 0
        or not _finite_number(status)
    ):
        _record_issue(pool, "missing_price_or_status", code)
        return False
    if status not in (-1, 0, 1):
        _record_issue(pool, "unknown_limit_status", code)
        return False
    if high < close - 1e-6 or high > limit + 1e-6 or close > limit + 1e-6:
        _record_issue(pool, "inconsistent_high_close_or_limit", code)
        return False
    pool.eligible_count += 1
    if (status == 1) != (close >= limit - 1e-6):
        _record_issue(pool, "limit_status_close_conflict", code)
    if status == 1:
        pool.closed.add(code)
    if high >= limit - 1e-6:
        pool.touched.add(code)
        if status != 1:
            pool.broken.add(code)
    elif status == 1:
        _record_issue(pool, "closed_without_touch", code)
    return True


def _record_issue(pool: CsmarDay, issue: str, code: str | None = None) -> None:
    pool.issues[issue] += 1
    if code is None:
        pool.global_issues = True
    else:
        pool.issue_codes.add(code)


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _day(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise CsmarSourceError("invalid Trddt value in CSMAR export") from exc


def read_csmar_daily(source: Path, *, as_of: date) -> CsmarDataset:
    """Read rows through ``as_of`` only; later rows cannot change a snapshot."""
    if not source.is_file():
        raise CsmarSourceError("configured CSMAR ZIP file does not exist")
    try:
        with zipfile.ZipFile(source) as archive:
            files = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
            data_files = [name for name in files if name == "TRD_Dalyr.xlsx"]
            # The known CSMAR field-description text and license PDFs contain
            # metadata. Any other file could be a missing export volume.
            unexpected = [
                name for name in files
                if name != "TRD_Dalyr.xlsx"
                and name.lower() != "trd_dalyr[des][xlsx].txt"
                and not name.lower().endswith(".pdf")
            ]
            if len(data_files) != 1 or unexpected:
                raise CsmarSourceError(
                    "CSMAR ZIP must contain exactly one TRD_Dalyr.xlsx workbook; "
                    "multiple or unsupported data files are not supported"
                )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                workbook = openpyxl.load_workbook(
                    BytesIO(archive.read("TRD_Dalyr.xlsx")),
                    read_only=True,
                    data_only=True,
                )
    except CsmarSourceError:
        raise
    except (OSError, KeyError, zipfile.BadZipFile, ValueError) as exc:
        raise CsmarSourceError("cannot read TRD_Dalyr.xlsx from CSMAR ZIP") from exc

    try:
        return _read_workbook(workbook, source, as_of)
    finally:
        workbook.close()


def _read_workbook(workbook, source: Path, as_of: date) -> CsmarDataset:
    if len(workbook.sheetnames) != 1:
        raise CsmarSourceError("CSMAR workbook must contain exactly one worksheet")
    sheet = workbook.active
    advertised_dimension = sheet.calculate_dimension()
    sheet.reset_dimensions()  # CSMAR exports may incorrectly advertise only column A.
    rows = sheet.iter_rows(values_only=True)
    try:
        header = next(rows)
        next(rows)  # Chinese field labels
        next(rows)  # units
    except StopIteration as exc:
        raise CsmarSourceError("CSMAR sheet has no data header") from exc
    missing = set(REQUIRED_FIELDS) - set(header)
    if missing:
        raise CsmarSourceError(f"CSMAR export lacks columns: {sorted(missing)}")
    duplicates = [name for name in REQUIRED_FIELDS if header.count(name) > 1]
    if duplicates:
        raise CsmarSourceError(f"CSMAR export repeats columns: {duplicates}")
    # A value added in a later row must not change historical provenance.
    declared_columns = max(index for index, value in enumerate(header, 1) if value is not None)
    ix = {name: header.index(name) for name in REQUIRED_FIELDS}
    days: dict[date, CsmarDay] = {}
    digest = hashlib.sha256()
    row_count = 0

    for row in rows:
        if len(row) <= ix["Trddt"]:
            raise CsmarSourceError("CSMAR row has no trading-date column")
        trading_day = _day(row[ix["Trddt"]])
        if trading_day > as_of:
            continue
        if len(row) != len(header):
            raise CsmarSourceError(f"CSMAR row has {len(row)} rather than {len(header)} columns")
        row_count += 1
        digest.update(json.dumps(
            [row[ix[name]] for name in REQUIRED_FIELDS],
            ensure_ascii=False, default=str, separators=(",", ":"),
        ).encode("utf-8"))
        digest.update(b"\n")
        pool = days.setdefault(trading_day, CsmarDay())
        apply_csmar_row(pool, {name: row[ix[name]] for name in REQUIRED_FIELDS})

    if as_of not in days:
        raise CsmarSourceError(f"CSMAR export has no records for {as_of.isoformat()}")
    return CsmarDataset(
        days=days,
        as_of_sha256=digest.hexdigest(),
        source_file=source.name,
        row_count_as_of=row_count,
        sheet_name=sheet.title,
        advertised_dimension=advertised_dimension,
        actual_columns=declared_columns,
    )
