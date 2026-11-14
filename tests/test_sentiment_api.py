"""End-to-end sentiment API checks using synthetic local CSMAR workbooks."""

from contextlib import closing
from datetime import date, datetime
from io import BytesIO
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import pandas as pd

from fastapi.testclient import TestClient as ApiTestClient
from openpyxl import Workbook, load_workbook

from api.app import create_app
from src.config import Config, get_config
from src.storage import DatabaseManager
from src.services.eastmoney_sentiment import MARKET_TZ, EASTMONEY_DAILY_VERSION
from src.data.csmar_daily import CsmarSourceError


FIELDS = [
    "Stkcd", "Trddt", "Markettype", "Trdsta", "Dnshrtrd",
    "Hiprc", "Clsprc", "LimitUp", "LimitStatus",
]


def write_export(path: Path, *, changed_target: bool = False, future_close: int = 10,
                 missing_session: bool = False) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(FIELDS)
    sheet.append(FIELDS)
    sheet.append([""] * len(FIELDS))
    if missing_session:
        rows = [
            ["000009", "2026-10-15", 1, 1, 100, 9, 9, 10, 0],
            ["000001", "2026-10-16", 1, 1, 100, 10, 10, 10, 1],
            ["000001", "2026-10-19", 1, 1, 100, 10, 10, 10, 1],
            ["000001", "2026-10-21", 1, 1, 100, 10, 10, 10, 1],
        ]
    else:
        rows = [
            ["000009", "2026-10-23", 1, 1, 100, 9, 9, 10, 0],
            ["000001", "2026-10-26", 1, 1, 100, 10, 10, 10, 1],
            ["000001", "2026-10-27", 1, 1, 100, 11, 11, 11, 1],
            ["000002", "2026-10-27", 4, 1, 100, 10, 10, 10, 1],
            ["000002", "2026-10-28", 4, 1, 100, 11, 11, 11, 1],
            ["000003", "2026-10-28", 4, 1, 100, 10, 9, 10, 0],
            ["000004", "2026-10-28", 4, 1, 100, 10, 9 if changed_target else 10,
             10, 0 if changed_target else 1],
            ["000005", "2026-10-29", 1, 1, 100, 10, future_close, 10, 1 if future_close == 10 else 0],
        ]
    for values in rows:
        sheet.append(values)
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("TRD_Dalyr.xlsx", buffer.getvalue())


class SentimentApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        folder = Path(self.directory.name)
        self.source = folder / "synthetic.zip"
        self.database = folder / "test.sqlite3"
        write_export(self.source)
        self.environment = patch.dict(os.environ, {
            "DATABASE_PATH": str(self.database),
            "CSMAR_ZIP_PATH": str(self.source),
            "ADMIN_AUTH_ENABLED": "false",
            "STOCK_INDEX_REMOTE_UPDATE_ENABLED": "false",
            "DSA_RUNTIME_SCHEDULER_SUPPRESS_START": "true",
        })
        self.environment.start()
        DatabaseManager.reset_instance()
        Config.reset_instance()
        self.client = ApiTestClient(create_app())
        self.addCleanup(self.clean_up)

    def clean_up(self):
        close = getattr(self.client, "close", None)
        if close:
            close()
        DatabaseManager.reset_instance()
        Config.reset_instance()
        self.environment.stop()
        self.directory.cleanup()

    def test_generate_read_list_trend_idempotency_conflict_and_as_of(self):
        base = "/api/v1/sentiment"
        first = self.client.post(f"{base}/snapshots/2026-10-28/generate?source=csmar")
        self.assertEqual(first.status_code, 200, first.text)
        first_data = first.json()
        self.assertEqual(first_data["action"], "inserted")
        snapshot = first_data["snapshot"]
        self.assertEqual(snapshot["quality_status"], "complete")
        self.assertEqual(snapshot["metrics"]["limit_up_count"], 2)
        self.assertEqual(snapshot["metrics"]["max_consecutive"], 2)
        self.assertAlmostEqual(snapshot["metrics"]["break_rate"], 1 / 3)
        self.assertEqual(snapshot["metrics"]["promotion_1_to_2"], 1)
        self.assertEqual((snapshot["break_numerator"], snapshot["break_denominator"]), (1, 3))
        self.assertNotIn("components", snapshot)
        self.assertNotIn("source_file", snapshot["provider_trace"])
        self.assertNotIn("000001", first.text)
        self.assertNotIn(str(self.source), first.text)

        write_export(self.source, future_close=9)
        repeated = self.client.post(f"{base}/snapshots/2026-10-28/generate?source=csmar")
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["action"], "unchanged")
        self.assertEqual(repeated.json()["snapshot"], snapshot)
        detail = self.client.get(f"{base}/snapshots/2026-10-28?source=csmar").json()
        self.assertEqual(detail, snapshot)

        future = self.client.post(f"{base}/snapshots/2026-10-29/generate?source=csmar")
        self.assertEqual(future.status_code, 200, future.text)
        listed = self.client.get(f"{base}/snapshots", params={"end_date": "2026-10-28", "source": "csmar"}).json()["items"]
        self.assertEqual([item["trade_date"] for item in listed], ["2026-10-28"])
        ordered = self.client.get(f"{base}/trend", params={"end_date": "2026-10-29", "source": "csmar"}).json()["items"]
        self.assertEqual([item["trade_date"] for item in ordered], ["2026-10-28"])
        earlier = self.client.get(f"{base}/trend", params={"end_date": "2026-10-28", "source": "csmar"}).json()["items"]
        self.assertEqual(earlier, [])

        write_export(self.source, changed_target=True, future_close=9)
        conflict = self.client.post(f"{base}/snapshots/2026-10-28/generate?source=csmar")
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["error"], "snapshot_conflict")
        self.assertEqual(self.client.get(f"{base}/snapshots/2026-10-28?source=csmar").json()["metrics"], snapshot["metrics"])
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sentiment_snapshots").fetchone()[0], 2)

    def test_eastmoney_source_separate_idempotent_and_conflict_safe(self):
        pools = {
            ("closed", "2026-10-26"): pd.DataFrame({"代码": ["000003"], "连板数": [1]}),
            ("closed", "2026-10-27"): pd.DataFrame({"代码": ["000001", "000003"], "连板数": [1, 2]}),
            ("closed", "2026-10-28"): pd.DataFrame({"代码": ["000001", "000002"], "连板数": [2, 1]}),
            ("previous", "2026-10-28"): pd.DataFrame({"代码": ["000001", "000003"]}),
            ("broken", "2026-10-28"): pd.DataFrame({"代码": ["000004"]}),
        }
        def fetch(kind, day):
            return pools[(kind, day.isoformat())].copy()
        base = "/api/v1/sentiment/snapshots"
        csmar = self.client.post(f"{base}/2026-10-28/generate?source=csmar")
        self.assertEqual(csmar.status_code, 200, csmar.text)
        get_config().csmar_zip_path = ""
        with patch("src.services.eastmoney_sentiment._fetch_pool", side_effect=fetch):
            result = self.client.post(f"{base}/2026-10-28/generate")
            self.assertEqual(result.status_code, 200, result.text)
            snapshot = result.json()["snapshot"]
            self.assertEqual(snapshot["market"], "CN_A_EASTMONEY_POOL")
            self.assertEqual(snapshot["metrics"]["limit_up_count"], 2)
            self.assertAlmostEqual(snapshot["metrics"]["break_rate"], 1 / 3)
            self.assertEqual(snapshot["metrics"]["limit_up_ladder"], {"1": 1, "2": 1})
            self.assertIsNone(snapshot["metrics"]["turnover_yuan"])
            self.assertFalse(snapshot["completeness"]["independent_market_coverage_verified"])
            self.assertNotIn("000001", result.text)
            again = self.client.post(f"{base}/2026-10-28/generate?source=eastmoney")
            self.assertEqual(again.json()["action"], "unchanged")
            detail = self.client.get(f"{base}/2026-10-28").json()
            self.assertEqual(detail, snapshot)
            self.assertEqual(self.client.get(f"{base}/2026-10-28?source=csmar").json()["market"], csmar.json()["snapshot"]["market"])
            self.assertEqual(len(self.client.get(base, params={"source": "eastmoney"}).json()["items"]), 1)
            self.assertEqual(len(self.client.get("/api/v1/sentiment/trend", params={"source": "eastmoney", "end_date": "2026-10-29"}).json()["items"]), 1)
            pools[("broken", "2026-10-28")] = pd.DataFrame({"代码": ["000004", "000005"]})
            conflict = self.client.post(f"{base}/2026-10-28/generate?source=eastmoney")
            self.assertEqual(conflict.status_code, 409, conflict.text)
            self.assertEqual(self.client.get(f"{base}/2026-10-28").json()["metrics"], snapshot["metrics"])

    def test_same_day_breadth_source_failure_preserves_valid_core_metrics(self):
        now = datetime(2026, 10, 28, 18, tzinfo=MARKET_TZ)
        pools = {
            "closed": pd.DataFrame({"代码": ["000001"], "连板数": [1], "最新价": [11]}),
            "previous": pd.DataFrame({"代码": ["000003"], "昨日连板数": [1]}),
            "broken": pd.DataFrame({"代码": ["000002"]}),
        }
        with patch("src.services.eastmoney_sentiment.datetime", wraps=datetime) as clock, \
             patch("src.services.eastmoney_sentiment._fetch_pool", side_effect=lambda kind, _: pools[kind]), \
             patch("src.services.eastmoney_sentiment._fetch_spot", side_effect=CsmarSourceError("timeout")):
            clock.now.return_value = now
            response = self.client.post(f"/api/v1/sentiment/snapshots/{now.date()}/generate")
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = response.json()["snapshot"]
        self.assertEqual(snapshot["quality_status"], "partial")
        self.assertEqual(snapshot["metrics"]["limit_up_count"], 1)
        self.assertEqual(snapshot["metrics"]["break_rate"], 1 / 2)
        self.assertIsNone(snapshot["metrics"]["advancing_ratio"])
        self.assertIsNone(snapshot["metrics"]["limit_down_coverage"])
        self.assertIsNone(snapshot["eligible_quote_count"])

    def test_manual_daily_ladder_promotions_and_turnover(self):
        base = "/api/v1/sentiment/snapshots"
        fixtures = (
            (date(2026, 10, 27), {"000001": 1, "000003": 2, "000009": 3, "000010": 4},
             {"000003": 1, "000009": 2, "000010": 3}, 80),
            (date(2026, 10, 28), {"000001": 2, "000003": 3, "000010": 5, "000002": 1},
             {"000001": 1, "000003": 2, "000009": 3, "000010": 4}, 100),
        )
        for day, today, prior, amount in fixtures:
            pools = {
                "closed": pd.DataFrame({"代码": list(today), "连板数": list(today.values()), "最新价": [10] * 4}),
                "previous": pd.DataFrame({"代码": list(prior), "昨日连板数": list(prior.values())}),
                "broken": pd.DataFrame({"代码": ["000004"]}),
                "down": pd.DataFrame({"代码": ["000005"]}),
            }
            spot = pd.DataFrame({"代码": [*today, "000004", "000005", "000006", "000007"],
                                 "最新价": [10] * 8, "涨跌幅": [10] * 4 + [3, -10, 0, 0],
                                 "成交量": [1] * 7 + [0], "成交额": [amount] * 7 + [900]})
            with patch("src.services.eastmoney_sentiment.datetime", wraps=datetime) as clock, \
                 patch("src.services.eastmoney_sentiment._fetch_pool", side_effect=lambda kind, _: pools[kind]), \
                 patch("src.services.eastmoney_sentiment._fetch_spot", return_value=spot):
                clock.now.return_value = datetime.combine(day, datetime.min.time(), MARKET_TZ).replace(hour=18)
                response = self.client.post(f"{base}/{day}/generate")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["snapshot"]["quality_status"], "complete")
            self.assertEqual(response.json()["snapshot"]["definition_version"], EASTMONEY_DAILY_VERSION)
        first = self.client.get(f"{base}/2026-10-27").json()["metrics"]
        self.assertEqual(first["turnover_yuan"], 560)
        self.assertIsNone(first["turnover_change_ratio"])
        result = self.client.get(f"{base}/2026-10-28").json()
        self.assertEqual((result["advancing_count"], result["limit_down_count"], result["eligible_quote_count"]), (5, 1, 7))
        metrics = result["metrics"]
        self.assertEqual(metrics["limit_up_ladder"], {"1": 1, "2": 1, "3": 1, "5": 1})
        self.assertEqual(metrics["higher_board_promotions"], {
            "2_to_3": {"numerator": 1, "denominator": 1, "rate": 1.0},
            "3_to_4": {"numerator": 0, "denominator": 1, "rate": 0.0},
            "4_plus_to_5_plus": {"numerator": 1, "denominator": 1, "rate": 1.0},
        })
        self.assertEqual((metrics["turnover_yuan"], metrics["previous_turnover_yuan"],
                          metrics["turnover_change_yuan"], metrics["turnover_change_ratio"]), (700, 560, 140, 0.25))
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE sentiment_snapshots SET definition_version = 'legacy' WHERE trade_date = '2026-10-27'")
            db.commit()
        self.assertIsNone(self.client.get(f"{base}/2026-10-28").json()["metrics"]["turnover_change_ratio"])
        trend = self.client.get("/api/v1/sentiment/trend", params={"end_date": "2026-10-28", "limit": 10})
        self.assertEqual(trend.status_code, 200, trend.text)
        data = trend.json()
        self.assertEqual(len(data["session_dates"]), 10)
        self.assertEqual(data["session_dates"][-1], "2026-10-27")
        self.assertEqual(len(data["missing_dates"]), 9)
        self.assertEqual(data["different_definition_dates"], ["2026-10-27"])
        self.assertEqual(data["items"], [])

    def test_empty_down_pool_requires_same_day_provider_confirmation(self):
        from src.services.eastmoney_sentiment import _fetch_down_codes

        day = date(2026, 10, 28)
        with patch("src.services.eastmoney_sentiment._fetch_pool", return_value=pd.DataFrame()), \
             patch("requests.get") as get:
            payload = {"rc": 0, "data": {"qdate": 20261028, "tc": 0, "pool": []}}
            get.return_value.json.return_value = payload
            self.assertEqual(_fetch_down_codes(day), set())
            payload["data"]["qdate"] = 20261027
            with self.assertRaises(CsmarSourceError):
                _fetch_down_codes(day)
            get.return_value.json.return_value = {"rc": 102, "data": None}
            with self.assertRaises(CsmarSourceError):
                _fetch_down_codes(day)

    def test_eastmoney_inconsistent_pool_fails_without_writing(self):
        def fetch(kind, day):
            if kind == "closed":
                return pd.DataFrame({"代码": ["000001"], "连板数": [1]})
            return pd.DataFrame({"代码": ["000002"]})
        with patch("src.services.eastmoney_sentiment._fetch_pool", side_effect=fetch):
            response = self.client.post("/api/v1/sentiment/snapshots/2026-10-28/generate?source=eastmoney")
        self.assertEqual(response.status_code, 422, response.text)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sentiment_snapshots").fetchone()[0], 0)

    def test_eastmoney_streak_disagreement_fails_without_writing(self):
        def fetch(kind, day):
            if kind == "closed" and day.isoformat() == "2026-10-28":
                return pd.DataFrame({"代码": ["000001"], "连板数": [2]})
            if kind == "closed" or kind == "previous":
                return pd.DataFrame({"代码": ["000002"], "连板数": [1]})
            return pd.DataFrame({"代码": ["000003"]})
        with patch("src.services.eastmoney_sentiment._fetch_pool", side_effect=fetch):
            response = self.client.post("/api/v1/sentiment/snapshots/2026-10-28/generate?source=eastmoney")
        self.assertEqual(response.status_code, 422, response.text)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sentiment_snapshots").fetchone()[0], 0)

    def test_eastmoney_future_date_does_not_fetch(self):
        with patch("src.services.eastmoney_sentiment._fetch_pool") as fetch:
            response = self.client.post("/api/v1/sentiment/snapshots/2099-01-05/generate?source=eastmoney")
            self.assertEqual(response.status_code, 422, response.text)
            fetch.assert_not_called()

    def test_eastmoney_retries_once_and_never_treats_failure_as_empty_market(self):
        from src.data.csmar_daily import CsmarSourceError
        from src.services.eastmoney_sentiment import _fetch_pool
        valid = pd.DataFrame({"代码": ["000001"]})
        with patch("data_provider.akshare_fetcher._akshare_call_with_timeout", side_effect=[TimeoutError(), valid]) as call:
            self.assertEqual(len(_fetch_pool("closed", date(2026, 10, 28))), 1)
            self.assertEqual(call.call_count, 2)
        with patch("data_provider.akshare_fetcher._akshare_call_with_timeout", return_value=pd.DataFrame()) as call:
            with self.assertRaises(CsmarSourceError):
                _fetch_pool("closed", date(2026, 10, 28))
            self.assertEqual(call.call_count, 2)

    def test_eastmoney_duplicate_error_identifies_date_without_stock_codes(self):
        from src.data.csmar_daily import CsmarSourceError
        from src.services.eastmoney_sentiment import _codes
        with self.assertRaises(CsmarSourceError) as raised:
            _codes(pd.DataFrame({"代码": ["000001", "000001"]}), "closed", date(2026, 10, 28))
        self.assertIn("2026-10-28", str(raised.exception))
        self.assertIn("duplicate", str(raised.exception))
        self.assertNotIn("000001", str(raised.exception))

    def test_missing_session_makes_only_affected_indicators_partial(self):
        write_export(self.source, missing_session=True)
        base = "/api/v1/sentiment/snapshots"
        response = self.client.post(f"{base}/2026-10-21/generate?source=csmar")
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = response.json()["snapshot"]
        self.assertEqual(snapshot["quality_status"], "partial")
        self.assertEqual(snapshot["metrics"]["limit_up_count"], 1)
        self.assertIsNone(snapshot["metrics"]["max_consecutive"])
        self.assertIsNone(snapshot["metrics"]["promotion_1_to_2"])
        self.assertIn("2026-10-20", snapshot["completeness"]["source_issues_through_target"])
        absent = self.client.post(f"{base}/2026-10-20/generate?source=csmar")
        self.assertEqual(absent.status_code, 422, absent.text)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sentiment_snapshots").fetchone()[0], 1)

    def test_partial_retry_cannot_overwrite_a_complete_snapshot(self):
        url = "/api/v1/sentiment/snapshots/2026-10-28"
        first = self.client.post(f"{url}/generate?source=csmar")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["snapshot"]["quality_status"], "complete")
        with zipfile.ZipFile(self.source) as archive:
            workbook = load_workbook(BytesIO(archive.read("TRD_Dalyr.xlsx")))
        workbook.active.append(["000002", "2026-10-28", 4, 1, 100, 11, 11, 11, 1])
        buffer = BytesIO()
        workbook.save(buffer)
        workbook.close()
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("TRD_Dalyr.xlsx", buffer.getvalue())
        retry = self.client.post(f"{url}/generate?source=csmar")
        self.assertEqual(retry.status_code, 409, retry.text)
        self.assertEqual(retry.json()["error"], "snapshot_conflict")
        self.assertEqual(self.client.get(f"{url}?source=csmar").json()["metrics"], first.json()["snapshot"]["metrics"])
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sentiment_snapshots").fetchone()[0], 1)

    def test_unconfigured_source_and_unsupported_multivolume_fail_without_writes(self):
        base = "/api/v1/sentiment/snapshots"
        config = get_config()
        config.csmar_zip_path = ""
        with patch("src.services.sentiment_snapshot_service.read_csmar_daily") as read:
            response = self.client.post(f"{base}/2026-10-28/generate?source=csmar")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"], "source_not_configured")
            read.assert_not_called()
        config.csmar_zip_path = str(self.source)
        with zipfile.ZipFile(self.source, "a") as archive:
            archive.writestr("TRD_Dalyr1.xlsx", b"additional workbook")
        unsupported = self.client.post(f"{base}/2026-10-28/generate?source=csmar")
        self.assertEqual(unsupported.status_code, 422, unsupported.text)
        self.assertIn("exactly one", unsupported.json()["message"])
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sentiment_snapshots").fetchone()[0], 0)

    def test_default_startup_and_reads_do_not_fetch_sentiment(self):
        get_config().csmar_zip_path = ""
        with patch.dict(os.environ, {"DSA_RUNTIME_SCHEDULER_SUPPRESS_START": "false"}), \
             patch.object(get_config(), "schedule_enabled", False), \
             patch.object(get_config(), "schedule_run_immediately", False), \
             patch("src.services.sentiment_snapshot_service.read_csmar_daily") as read, \
             patch("src.services.eastmoney_sentiment._fetch_pool") as fetch, \
             patch("api.app._schedule_stock_index_background_refresh"), \
             patch("src.services.name_to_code_resolver.warmup_akshare_cache"):
            with ApiTestClient(create_app()) as client:
                response = client.get("/api/v1/sentiment/snapshots")
                self.assertEqual(response.status_code, 200, response.text)
            read.assert_not_called()
            fetch.assert_not_called()

    def test_enabled_admin_auth_protects_sentiment_without_reading_source(self):
        with patch("api.middlewares.auth.is_auth_enabled", return_value=True), \
             patch("src.services.sentiment_snapshot_service.read_csmar_daily") as read, \
             patch("src.services.eastmoney_sentiment._fetch_pool") as fetch:
            response = self.client.post("/api/v1/sentiment/snapshots/2026-10-28/generate?source=csmar")
            self.assertEqual(response.status_code, 401, response.text)
            response = self.client.get("/api/v1/sentiment/snapshots")
            self.assertEqual(response.status_code, 401, response.text)
            response = self.client.post("/api/v1/sentiment/snapshots/2026-10-28/generate?source=eastmoney")
            self.assertEqual(response.status_code, 401, response.text)
            response = self.client.get("/api/v1/sentiment/trend?end_date=2026-10-28&source=eastmoney")
            self.assertEqual(response.status_code, 401, response.text)
            read.assert_not_called()
            fetch.assert_not_called()

    def test_unexpected_exception_does_not_expose_local_or_licensed_data(self):
        secret = "private-path-stock-000001"
        with patch("api.v1.endpoints.sentiment.generate_snapshot", side_effect=RuntimeError(secret)), \
             self.assertLogs("api.v1.endpoints.sentiment", level="ERROR") as logs:
            response = self.client.post("/api/v1/sentiment/snapshots/2026-10-28/generate?source=csmar")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "internal_error")
        self.assertNotIn(secret, response.text)
        self.assertNotIn(secret, "\n".join(logs.output))

    def test_unavailable_calendar_fails_closed_without_writing(self):
        with patch("src.core.trading_calendar._XCALS_AVAILABLE", False):
            response = self.client.post("/api/v1/sentiment/snapshots/2026-10-28/generate?source=csmar")
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["error"], "source_unavailable")
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sentiment_snapshots").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
