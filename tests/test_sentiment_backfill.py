"""Offline checks for historical CSMAR backfill and calendar gaps."""

from contextlib import redirect_stdout
from datetime import date
from io import BytesIO, StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from scripts.backfill_sentiment import main
from src.core.trading_calendar import get_trading_dates
from src.data.csmar_daily import CsmarDataset, CsmarDay, read_csmar_daily
from src.services.sentiment_backfill_service import BackfillCalendarError, iter_backfill
from src.services.sentiment_snapshot_service import compute_snapshot
from src.storage import SentimentSnapshot


FIELDS = ["Stkcd", "Trddt", "Markettype", "Trdsta", "Dnshrtrd",
          "Hiprc", "Clsprc", "LimitUp", "LimitStatus"]


def write_export(path: Path, *, future_close: float | None = None,
                 target_closed: bool = True, weekend_row: bool = False) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(FIELDS)
    sheet.append(FIELDS)
    sheet.append([""] * len(FIELDS))
    sheet.append(["000002", "2026-10-15", 1, 1, 100, 9, 9, 10, 0])
    sheet.append(["000001", "2026-10-16", 1, 1, 100, 10, 10, 10, 1])
    if weekend_row:
        sheet.append(["000003", "2026-10-17", 1, 1, 100, 10, 10, 10, 1])
    sheet.append([
        "000001", "2026-10-19", 1, 1, 100, 10,
        10 if target_closed else 9, 10, 1 if target_closed else 0,
    ])
    # 2026-10-20 is intentionally absent in gap tests.
    sheet.append(["000001", "2026-10-21", 1, 1, 100, 10, 10, 10, 1])
    if future_close is not None:
        sheet.append(["000004", "2026-10-29", 4, 1, 100, 11, future_close, 11, 1])
    data = BytesIO()
    workbook.save(data)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("TRD_Dalyr.xlsx", data.getvalue())


class SentimentBackfillTests(unittest.TestCase):
    def test_real_october_range_uses_exchange_sessions(self):
        sessions = get_trading_dates("cn", date(2026, 10, 16), date(2026, 10, 29))
        self.assertIsNotNone(sessions)
        self.assertEqual(
            [value.date().isoformat() for value in sessions],
            ["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21",
             "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27",
             "2026-10-28", "2026-10-29"],
        )

    def test_missing_session_fails_that_day_and_breaks_later_streak(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.zip"
            write_export(source)
            results = list(iter_backfill(
                source, start_date=date(2026, 10, 19), end_date=date(2026, 10, 21),
                dry_run=True,
            ))
            self.assertEqual([item.status for item in results], ["dry-run", "failed", "partial"])
            self.assertIn("2026-10-20", results[1].message)
            dataset = read_csmar_daily(source, as_of=date(2026, 10, 21))
            from src.services.sentiment_backfill_service import _validate_and_pad_history
            _validate_and_pad_history(dataset, date(2026, 10, 21), get_trading_dates)
            snapshot = compute_snapshot(dataset, date(2026, 10, 21))
            self.assertIn("2026-10-20", snapshot["completeness"]["source_issues_through_target"])
            self.assertIsNone(snapshot["metrics"]["max_consecutive"])
            self.assertIsNone(snapshot["metrics"]["promotion_1_to_2"])
            self.assertEqual(snapshot["metrics"]["limit_up_count"], 1)

    def test_non_session_source_row_is_not_treated_as_trading_day(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "weekend.zip"
            write_export(source, weekend_row=True)
            result = list(iter_backfill(
                source, start_date=date(2026, 10, 19), end_date=date(2026, 10, 19),
                dry_run=True,
            ))[0]
            self.assertEqual(result.status, "failed")
            self.assertIn("non-session", result.message)

    def test_daily_as_of_hash_ignores_future_rows_and_save_is_idempotent(self):
        engine = create_engine("sqlite:///:memory:")
        SentimentSnapshot.__table__.create(engine)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.zip"
            write_export(source, future_close=11)
            expected_hash = read_csmar_daily(source, as_of=date(2026, 10, 19)).as_of_sha256
            def run():
                return list(iter_backfill(
                    source, start_date=date(2026, 10, 19), end_date=date(2026, 10, 19),
                    dry_run=False, session_factory=lambda: Session(engine),
                ))[0]

            self.assertEqual(run().status, "inserted")
            with Session(engine) as session:
                record = session.execute(select(SentimentSnapshot)).scalar_one()
                self.assertEqual(json.loads(record.provider_trace_json)["as_of_sha256"], expected_hash)
            write_export(source, future_close=10)
            self.assertEqual(run().status, "unchanged")
            write_export(source, future_close=10, target_closed=False)
            self.assertEqual(run().status, "conflict")
            with Session(engine) as session:
                self.assertEqual(len(session.execute(select(SentimentSnapshot)).scalars().all()), 1)
        engine.dispose()

    def test_partial_gap_snapshot_is_saved_once_without_overwrite(self):
        engine = create_engine("sqlite:///:memory:")
        SentimentSnapshot.__table__.create(engine)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "gap.zip"
            write_export(source)
            def run():
                return list(iter_backfill(
                    source, start_date=date(2026, 10, 21), end_date=date(2026, 10, 21),
                    dry_run=False, session_factory=lambda: Session(engine),
                ))[0]

            first, second = run(), run()
            self.assertEqual((first.status, first.save_action), ("partial", "inserted"))
            self.assertEqual((second.status, second.save_action), ("partial", "unchanged"))
            with Session(engine) as session:
                self.assertEqual(len(session.execute(select(SentimentSnapshot)).scalars().all()), 1)
        engine.dispose()

    def test_dry_run_cli_never_initializes_database(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "sample.zip"
            write_export(source)
            output = StringIO()
            with patch("scripts.backfill_sentiment.get_config", return_value=SimpleNamespace(
                csmar_zip_path=str(source), database_path=str(Path(folder) / "should-not-exist.db"),
            )), patch("scripts.backfill_sentiment.DatabaseManager.get_instance",
                      side_effect=AssertionError("database opened during dry-run")), redirect_stdout(output):
                exit_code = main(["--source", "csmar", "--start-date", "2026-10-19", "--end-date", "2026-10-19", "--dry-run"])
            self.assertEqual(exit_code, 0)
            self.assertFalse((Path(folder) / "should-not-exist.db").exists())
            self.assertEqual(json.loads(output.getvalue().splitlines()[0])["status"], "dry-run")

    def test_old_issue_does_not_poison_later_clean_streak(self):
        days = {date(2026, 10, day): CsmarDay(row_count=1) for day in (15, 16, 19, 20, 21, 22)}
        days[date(2026, 10, 15)].issues["missing_price_or_status"] = 1
        days[date(2026, 10, 21)].closed.add("000001")
        days[date(2026, 10, 22)].closed.add("000001")
        days[date(2026, 10, 21)].touched.add("000001")
        days[date(2026, 10, 22)].touched.add("000001")
        dataset = CsmarDataset(days, "test", "sample.zip", 6, "sheet1", "A1:I9", 9)
        snapshot = compute_snapshot(dataset, date(2026, 10, 22))
        self.assertEqual(snapshot["metrics"]["max_consecutive"], 2)
        self.assertEqual(snapshot["quality_status"], "complete")
        self.assertIn("2026-10-15", snapshot["completeness"]["source_issues_through_target"])

    def test_source_start_truncation_and_calendar_unavailable(self):
        days = {date(2026, 10, day): CsmarDay(row_count=1) for day in (19, 20, 21)}
        for pool in days.values():
            pool.closed.add("000001")
            pool.touched.add("000001")
        dataset = CsmarDataset(days, "test", "sample.zip", 3, "sheet1", "A1:I6", 9)
        snapshot = compute_snapshot(dataset, date(2026, 10, 21))
        self.assertIsNone(snapshot["metrics"]["max_consecutive"])
        self.assertEqual(snapshot["quality_status"], "partial")
        with self.assertRaises(BackfillCalendarError):
            list(iter_backfill(Path("unused.zip"), start_date=date(2026, 10, 19),
                               end_date=date(2026, 10, 21), dry_run=True,
                               calendar_getter=lambda *_: None))

    def test_unexpected_error_message_does_not_expose_path_or_stock_rows(self):
        with patch("src.services.sentiment_backfill_service.read_csmar_daily",
                   side_effect=RuntimeError("private-path-stock-000001")):
            result = list(iter_backfill(
                Path("unused.zip"), start_date=date(2026, 10, 19),
                end_date=date(2026, 10, 19), dry_run=True,
            ))[0]
        self.assertEqual(result.status, "failed")
        self.assertNotIn("private-path-stock-000001", result.message)


if __name__ == "__main__":
    unittest.main()
