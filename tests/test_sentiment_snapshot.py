"""Offline contract checks for the opt-in CSMAR sentiment backend."""

from datetime import date
from io import BytesIO
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.data.csmar_daily import CsmarDataset, CsmarDay, CsmarSourceError, read_csmar_daily
from src.repositories.sentiment_repo import SentimentRepository, SentimentSnapshotConflict
from src.services.sentiment_snapshot_service import MARKET, compute_snapshot
from src.storage import SentimentSnapshot


FIELDS = ["Stkcd", "Trddt", "Markettype", "Trdsta", "Dnshrtrd",
          "Hiprc", "Clsprc", "LimitUp", "LimitStatus"]


def write_export(path: Path, *, include_future: bool) -> None:
    book = Workbook()
    sheet = book.active
    sheet.append(FIELDS)
    sheet.append(FIELDS)
    sheet.append([""] * len(FIELDS))
    sheet.append(["000001", "2026-10-26", 1, 1, 100, 11, 11, 11, 1])
    sheet.append(["000001", "2026-10-27", 1, 1, 100, 12, 12, 12, 1])
    sheet.append(["000002", "2026-10-27", 4, 1, 100, 10, 10, 10, 1])
    sheet.append(["000002", "2026-10-28", 4, 1, 100, 11, 11, 11, 1])
    sheet.append(["000003", "2026-10-28", 4, 1, 100, 11, 10, 11, 0])
    if include_future:
        sheet.append(["000004", "2026-10-29", 4, 1, 100, 11, 11, 11, 1])
    original = BytesIO()
    book.save(original)
    original.seek(0)
    malformed = BytesIO()
    with zipfile.ZipFile(original) as xlsx, zipfile.ZipFile(malformed, "w") as edited:
        for info in xlsx.infolist():
            data = xlsx.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A1:A8"', data)
            edited.writestr(info, data)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("TRD_Dalyr.xlsx", malformed.getvalue())


class SentimentSnapshotTests(unittest.TestCase):
    def test_malformed_dimension_and_future_rows_do_not_change_target(self):
        target = date(2026, 10, 28)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.zip"
            write_export(source, include_future=False)
            before = read_csmar_daily(source, as_of=target)
            first = compute_snapshot(before, target)
            write_export(source, include_future=True)
            after = read_csmar_daily(source, as_of=target)
            second = compute_snapshot(after, target)
        self.assertEqual(before.actual_columns, len(FIELDS))
        self.assertEqual(before.as_of_sha256, after.as_of_sha256)
        self.assertEqual(first, second)
        self.assertEqual(first["metrics"]["limit_up_count"], 1)
        self.assertEqual(first["components"]["break_numerator"], 1)
        self.assertEqual(first["components"]["break_denominator"], 2)
        self.assertEqual(first["components"]["promotion_denominator"], 1)
        self.assertEqual(first["components"]["promotion_numerator"], 1)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "missing_day.zip"
            write_export(source, include_future=True)
            with self.assertRaises(CsmarSourceError):
                read_csmar_daily(source, as_of=date(2026, 10, 30))

    def test_zero_denominators_are_null(self):
        days = {date(2026, 10, day): CsmarDay(row_count=1) for day in (26, 27, 28)}
        dataset = CsmarDataset(days, "test", "sample.zip", 3, "sheet1", "A1:A6", 9)
        snapshot = compute_snapshot(dataset, date(2026, 10, 28))
        self.assertEqual(snapshot["metrics"]["limit_up_count"], 0)
        self.assertIsNone(snapshot["metrics"]["break_rate"])
        self.assertIsNone(snapshot["metrics"]["promotion_1_to_2"])

    def test_incomplete_target_does_not_turn_missing_into_zero(self):
        days = {date(2026, 10, day): CsmarDay(row_count=1) for day in (26, 27, 28)}
        days[date(2026, 10, 28)].issues["missing_price_or_status"] += 1
        dataset = CsmarDataset(days, "test", "sample.zip", 3, "sheet1", "A1:A6", 9)
        snapshot = compute_snapshot(dataset, date(2026, 10, 28))
        self.assertEqual(snapshot["quality_status"], "partial")
        self.assertTrue(all(value is None for value in snapshot["metrics"].values()))

    def test_idempotent_save_conflict_and_as_of_query(self):
        days = {date(2026, 10, day): CsmarDay(row_count=1) for day in (26, 27, 28)}
        dataset = CsmarDataset(days, "test", "sample.zip", 3, "sheet1", "A1:A6", 9)
        snapshot = compute_snapshot(dataset, date(2026, 10, 28))
        engine = create_engine("sqlite:///:memory:")
        SentimentSnapshot.__table__.create(engine)
        with Session(engine) as session:
            repo = SentimentRepository(session)
            self.assertEqual(repo.save(snapshot)[0], "inserted")
            self.assertEqual(repo.save(snapshot)[0], "unchanged")
            self.assertEqual(len(repo.list(MARKET, end_date=date(2026, 10, 27))), 0)
            changed = {**snapshot, "metrics": {**snapshot["metrics"], "limit_up_count": 99}}
            with self.assertRaises(SentimentSnapshotConflict):
                repo.save(changed)
            self.assertEqual(len(repo.list(MARKET)), 1)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
