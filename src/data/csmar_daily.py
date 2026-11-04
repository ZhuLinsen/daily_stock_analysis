"""Local CSMAR TRD_Dalyr reader for opt-in A-share sentiment snapshots."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
from io import BytesIO
import json
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


@dataclass
class CsmarDataset:
    days: dict[date, CsmarDay]
    as_of_sha256: str
    source_file: str
    row_count_as_of: int
    sheet_name: str
    advertised_dimension: str
    actual_columns: int


def _day(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise CsmarSourceError(f"invalid Trddt value: {value!r}") from exc


def read_csmar_daily(source: Path, *, as_of: date) -> CsmarDataset:
    """Read rows through ``as_of`` only; later rows cannot change a snapshot."""
    if not source.is_file():
        raise CsmarSourceError("configured CSMAR ZIP file does not exist")
    try:
        with zipfile.ZipFile(source) as archive:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                workbook = openpyxl.load_workbook(
                    BytesIO(archive.read("TRD_Dalyr.xlsx")),
                    read_only=True,
                    data_only=True,
                )
    except (OSError, KeyError, zipfile.BadZipFile, ValueError) as exc:
        raise CsmarSourceError("cannot read TRD_Dalyr.xlsx from CSMAR ZIP") from exc

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
    ix = {name: header.index(name) for name in REQUIRED_FIELDS}
    days: dict[date, CsmarDay] = {}
    digest = hashlib.sha256()
    row_count = 0

    for row in rows:
        if len(row) != len(header):
            raise CsmarSourceError(f"CSMAR row has {len(row)} rather than {len(header)} columns")
        trading_day = _day(row[ix["Trddt"]])
        if trading_day > as_of:
            continue
        row_count += 1
        digest.update(json.dumps(
            [row[ix[name]] for name in REQUIRED_FIELDS],
            ensure_ascii=False, default=str, separators=(",", ":"),
        ).encode("utf-8"))
        digest.update(b"\n")
        pool = days.setdefault(trading_day, CsmarDay())
        pool.row_count += 1
        code = str(row[ix["Stkcd"]]).zfill(6)
        if code in pool.seen_codes:
            pool.issues["duplicate_stock_code"] += 1
        pool.seen_codes.add(code)
        if row[ix["Markettype"]] not in (1, 4) or row[ix["Trdsta"]] != 1:
            continue
        pool.normal_main_count += 1
        volume = row[ix["Dnshrtrd"]]
        high = row[ix["Hiprc"]]
        close = row[ix["Clsprc"]]
        limit = row[ix["LimitUp"]]
        status = row[ix["LimitStatus"]]
        if volume is None or volume <= 0:
            pool.issues["normal_main_zero_volume"] += 1
            continue
        if limit is None and status is None and high is not None and close is not None:
            pool.no_price_limit_count += 1
            continue
        if limit is None or limit <= 0 or high is None or close is None or status is None:
            pool.issues["missing_price_or_status"] += 1
            continue
        if status not in (-1, 0, 1):
            pool.issues["unknown_limit_status"] += 1
            continue
        pool.eligible_count += 1
        price_at_limit = close >= limit - 1e-6
        if (status == 1) != price_at_limit:
            pool.issues["limit_status_close_conflict"] += 1
        if status == 1:
            pool.closed.add(code)
        if high >= limit - 1e-6:
            pool.touched.add(code)
            if status != 1:
                pool.broken.add(code)
        elif status == 1:
            pool.issues["closed_without_touch"] += 1

    if as_of not in days:
        raise CsmarSourceError(f"CSMAR export has no records for {as_of.isoformat()}")
    return CsmarDataset(
        days=days,
        as_of_sha256=digest.hexdigest(),
        source_file=source.name,
        row_count_as_of=row_count,
        sheet_name=sheet.title,
        advertised_dimension=advertised_dimension,
        actual_columns=len(header),
    )
