"""Offline contract checks for the opt-in CSMAR sentiment backend."""

from datetime import date
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import tempfile
import unittest
import zipfile

from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.data.csmar_daily import CsmarDataset, CsmarDay, CsmarSourceError, apply_csmar_row, read_csmar_daily
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
    def test_unsupported_data_files_or_worksheets_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.zip"
            for extra in ("TRD_Dalyr1.xlsx", "nested/TRD_Dalyr1.csv", "other.xlsm",
                          "TRD_Dalyr1.txt", "TRD_Dalyr2.dat", "unknown.json"):
                write_export(source, include_future=False)
                with zipfile.ZipFile(source, "a") as archive:
                    archive.writestr(extra, b"not parsed")
                with self.subTest(extra=extra), self.assertRaisesRegex(CsmarSourceError, "exactly one"):
                    read_csmar_daily(source, as_of=date(2026, 10, 28))
            write_export(source, include_future=False)
            with zipfile.ZipFile(source, "a") as archive:
                archive.writestr("TRD_Dalyr[DES][xlsx].txt", b"field descriptions")
                archive.writestr("license.pdf", b"metadata")
            self.assertEqual(read_csmar_daily(source, as_of=date(2026, 10, 28)).row_count_as_of, 5)
            write_export(source, include_future=False)
            with zipfile.ZipFile(source) as archive:
                data = archive.read("TRD_Dalyr.xlsx")
            from openpyxl import load_workbook
            workbook = load_workbook(BytesIO(data))
            workbook.create_sheet("additional records")
            buffer = BytesIO()
            workbook.save(buffer)
            workbook.close()
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("TRD_Dalyr.xlsx", buffer.getvalue())
            with self.assertRaisesRegex(CsmarSourceError, "exactly one worksheet"):
                read_csmar_daily(source, as_of=date(2026, 10, 28))

    def test_duplicate_required_column_is_rejected(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.zip"
            write_export(source, include_future=False)
            with zipfile.ZipFile(source) as archive:
                workbook = load_workbook(BytesIO(archive.read("TRD_Dalyr.xlsx")))
            workbook.active.cell(row=1, column=10, value="Stkcd")
            buffer = BytesIO()
            workbook.save(buffer)
            workbook.close()
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("TRD_Dalyr.xlsx", buffer.getvalue())
            with self.assertRaisesRegex(CsmarSourceError, "repeats columns"):
                read_csmar_daily(source, as_of=date(2026, 10, 28))

    def test_ambiguous_or_invalid_source_rows_do_not_become_valid_zeroes(self):
        normal = dict(Stkcd="000001", Markettype=1, Trdsta=1, Dnshrtrd=100,
                      Hiprc=11, Clsprc=11, LimitUp=11, LimitStatus=1)
        malformed = [
            {"Stkcd": None}, {"Markettype": None}, {"Trdsta": None},
            {"Dnshrtrd": float("nan")}, {"Hiprc": float("nan")},
            {"Clsprc": -1}, {"LimitUp": float("inf")}, {"LimitStatus": None},
            {"Hiprc": 10, "Clsprc": 11}, {"Hiprc": 12},
            {"LimitUp": None, "LimitStatus": None},
        ]
        for change in malformed:
            pool = CsmarDay()
            with self.subTest(change=change):
                self.assertFalse(apply_csmar_row(pool, {**normal, **change}))
                self.assertTrue(pool.issues)
                self.assertEqual(pool.eligible_count, 0)
        pool = CsmarDay()
        self.assertTrue(apply_csmar_row(pool, normal))
        self.assertTrue(apply_csmar_row(pool, normal))
        self.assertEqual(pool.issues["duplicate_stock_code"], 1)

    def test_as_of_fingerprint_keeps_the_existing_nine_field_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.zip"
            write_export(source, include_future=True)
            actual = read_csmar_daily(source, as_of=date(2026, 10, 28))
            rows = [
                ["000001", "2026-10-26", 1, 1, 100, 11, 11, 11, 1],
                ["000001", "2026-10-27", 1, 1, 100, 12, 12, 12, 1],
                ["000002", "2026-10-27", 4, 1, 100, 10, 10, 10, 1],
                ["000002", "2026-10-28", 4, 1, 100, 11, 11, 11, 1],
                ["000003", "2026-10-28", 4, 1, 100, 11, 10, 11, 0],
            ]
            digest = hashlib.sha256()
            for row in rows:
                digest.update(json.dumps(row, ensure_ascii=False, default=str,
                                         separators=(",", ":")).encode("utf-8"))
                digest.update(b"\n")
            self.assertEqual(actual.as_of_sha256, digest.hexdigest())

    def test_dimension_metadata_distinguishes_column_a_from_aa(self):
        days = {date(2026, 10, day): CsmarDay(row_count=1) for day in (26, 27, 28)}
        for advertised, expected in (("A1:A9", True), ("A1:AA9", False), ("A1:AZ9", False)):
            dataset = CsmarDataset(days, "test", "sample.zip", 3, "sheet1", advertised, 27)
            with self.subTest(advertised=advertised):
                snapshot = compute_snapshot(dataset, date(2026, 10, 28))
                self.assertEqual(snapshot["provider_trace"]["dimension_repaired"], expected)

    def test_future_extra_column_does_not_change_historical_snapshot(self):
        from openpyxl import load_workbook
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.zip"
            write_export(source, include_future=True)
            with zipfile.ZipFile(source) as archive:
                workbook = load_workbook(BytesIO(archive.read("TRD_Dalyr.xlsx")))

            def save():
                buffer = BytesIO()
                workbook.save(buffer)
                with zipfile.ZipFile(source, "w") as archive:
                    archive.writestr("TRD_Dalyr.xlsx", buffer.getvalue())

            save()
            target = date(2026, 10, 28)
            before = compute_snapshot(read_csmar_daily(source, as_of=target), target)
            workbook.active.cell(row=9, column=10, value="later-only extra value")
            save()
            after = compute_snapshot(read_csmar_daily(source, as_of=target), target)
            workbook.close()
            self.assertEqual(before, after)

    def test_future_repair_of_excel_dimension_does_not_cause_a_conflict(self):
        from openpyxl import load_workbook
        target = date(2026, 10, 28)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.zip"
            write_export(source, include_future=True)
            before = compute_snapshot(read_csmar_daily(source, as_of=target), target)
            with zipfile.ZipFile(source) as archive:
                workbook = load_workbook(BytesIO(archive.read("TRD_Dalyr.xlsx")))
            workbook.active.cell(row=9, column=10, value="later-only extra value")
            buffer = BytesIO()
            workbook.save(buffer)
            workbook.close()
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("TRD_Dalyr.xlsx", buffer.getvalue())
            after = compute_snapshot(read_csmar_daily(source, as_of=target), target)
            self.assertTrue(before["provider_trace"]["dimension_repaired"])
            self.assertFalse(after["provider_trace"]["dimension_repaired"])
            self.assertEqual(before["provider_trace"]["as_of_sha256"],
                             after["provider_trace"]["as_of_sha256"])
            self.assertEqual(before["metrics"], after["metrics"])
            engine = create_engine("sqlite:///:memory:")
            SentimentSnapshot.__table__.create(engine)
            with Session(engine) as session:
                repo = SentimentRepository(session)
                self.assertEqual(repo.save(before)[0], "inserted")
                action, stored = repo.save(after)
                self.assertEqual(action, "unchanged")
                self.assertTrue(json.loads(stored.provider_trace_json)["dimension_repaired"])
            engine.dispose()

    def test_streak_only_ignores_a_specific_unrelated_source_issue(self):
        days = {date(2026, 10, day): CsmarDay(row_count=1) for day in (23, 26, 27, 28)}
        days[date(2026, 10, 26)].closed.add("000001")
        days[date(2026, 10, 27)].closed.add("000001")
        days[date(2026, 10, 28)].closed.add("000001")
        for day in (26, 27, 28):
            days[date(2026, 10, day)].touched.add("000001")
        issue_day = days[date(2026, 10, 26)]
        issue_day.issues["ambiguous_price_limit"] = 1
        issue_day.issue_codes.add("000002")
        dataset = CsmarDataset(days, "test", "sample.zip", 4, "sheet1", "A1:I9", 9)
        self.assertEqual(compute_snapshot(dataset, date(2026, 10, 28))["metrics"]["max_consecutive"], 3)
        issue_day.issue_codes.add("000001")
        self.assertIsNone(compute_snapshot(dataset, date(2026, 10, 28))["metrics"]["max_consecutive"])

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

    def test_truncated_prior_board_marks_snapshot_partial(self):
        dates = [date(2026, 10, day) for day in (26, 27, 28)]
        days = {day: CsmarDay(row_count=1) for day in dates}
        for day, code in zip(dates, ("000001", "000001", "000002")):
            days[day].closed.add(code)
            days[day].touched.add(code)
        dataset = CsmarDataset(days, "test", "sample.zip", 3, "sheet1", "A1:I6", 9)
        snapshot = compute_snapshot(dataset, dates[-1])
        self.assertEqual(snapshot["quality_status"], "partial")
        self.assertFalse(snapshot["completeness"]["prior_streak_available"])
        self.assertIsNone(snapshot["metrics"]["higher_board_promotions"])
        self.assertEqual(snapshot["metrics"]["max_consecutive"], 1)

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

    def test_inconsistent_stock_sets_make_affected_metrics_null(self):
        days = {date(2026, 10, day): CsmarDay(row_count=1) for day in (26, 27, 28)}
        days[date(2026, 10, 28)].closed.add("000001")
        dataset = CsmarDataset(days, "test", "sample.zip", 3, "sheet1", "A1:A6", 9)
        snapshot = compute_snapshot(dataset, date(2026, 10, 28))
        self.assertEqual(snapshot["quality_status"], "partial")
        self.assertFalse(snapshot["completeness"]["closed_plus_broken_equals_touched"])
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
