# -*- coding: utf-8 -*-
"""PR2 tests for portfolio CSV import, risk thresholds and FX stale fallback."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from fastapi.testclient import TestClient

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.services.portfolio_import_service import PortfolioImportService
from src.services.portfolio_risk_service import PortfolioRiskService
from src.services.portfolio_service import PortfolioService
from src.storage import DatabaseManager


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


class PortfolioPr2TestCase(unittest.TestCase):
    """End-to-end style tests for PR2 import, dedup, risk and fx behavior."""

    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        self.env_path = data_dir / ".env"
        self.db_path = data_dir / "portfolio_pr2_test.db"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519",
                    "GEMINI_API_KEY=test",
                    "ADMIN_AUTH_ENABLED=false",
                    "PORTFOLIO_RISK_CONCENTRATION_ALERT_PCT=70.0",
                    "PORTFOLIO_RISK_DRAWDOWN_ALERT_PCT=10.0",
                    "PORTFOLIO_RISK_STOP_LOSS_ALERT_PCT=25.0",
                    "PORTFOLIO_RISK_STOP_LOSS_NEAR_RATIO=0.8",
                    "PORTFOLIO_RISK_LOOKBACK_DAYS=365",
                    f"DATABASE_PATH={self.db_path}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()

        self.db = DatabaseManager.get_instance()
        self.service = PortfolioService()
        self.import_service = PortfolioImportService(portfolio_service=self.service)
        self.risk_service = PortfolioRiskService(portfolio_service=self.service)
        self._board_fetch_patcher = patch.object(PortfolioRiskService, "_fetch_belong_boards", return_value=[])
        self._board_fetch_patcher.start()
        self.client = TestClient(create_app(static_dir=data_dir / "empty-static"))

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self._board_fetch_patcher.stop()
        self.temp_dir.cleanup()

    def _save_close(self, symbol: str, on_date: date, close: float) -> None:
        df = pd.DataFrame(
            [
                {
                    "date": on_date,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1.0,
                    "amount": close,
                    "pct_chg": 0.0,
                }
            ]
        )
        self.db.save_daily_data(df, code=symbol, data_source="portfolio-pr2-test")

    @staticmethod
    def _csv_bytes(with_trade_uid: bool = True) -> bytes:
        if with_trade_uid:
            csv_text = (
                "成交日期,证券代码,买卖标志,成交数量,成交均价,成交编号,手续费,印花税\n"
                "2026-01-02,600519,买入,10,100,HT-001,1,0\n"
            )
        else:
            csv_text = (
                "成交日期,证券代码,买卖标志,成交数量,成交均价,手续费,印花税\n"
                "2026-01-02,600519,买入,10,100,1,0\n"
            )
        return csv_text.encode("utf-8")

    def test_import_dedup_trade_uid_and_hash(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]

        parsed_uid = self.import_service.parse_trade_csv(broker="huatai", content=self._csv_bytes(with_trade_uid=True))
        first_uid = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed_uid["records"],
        )
        second_uid = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed_uid["records"],
        )
        self.assertEqual(first_uid["inserted_count"], 1)
        self.assertEqual(second_uid["duplicate_count"], 1)

        parsed_hash = self.import_service.parse_trade_csv(
            broker="huatai",
            content=self._csv_bytes(with_trade_uid=False),
        )
        first_hash = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed_hash["records"],
        )
        second_hash = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed_hash["records"],
        )
        self.assertEqual(first_hash["inserted_count"], 0)
        self.assertEqual(first_hash["duplicate_count"], 1)
        self.assertEqual(second_hash["inserted_count"], 0)

    def test_import_side_parser_avoids_false_sell_match(self) -> None:
        csv_text = (
            "成交日期,证券代码,买卖标志,成交数量,成交均价,成交编号\n"
            "2026-01-02,600519,Asset Transfer,10,100,HT-002\n"
        )
        parsed = self.import_service.parse_trade_csv(
            broker="huatai",
            content=csv_text.encode("utf-8"),
        )
        self.assertEqual(parsed["record_count"], 0)

    def test_import_supported_broker_registry(self) -> None:
        items = self.import_service.list_supported_brokers()
        broker_map = {item["broker"]: item for item in items}
        self.assertIn("huatai", broker_map)
        self.assertIn("citic", broker_map)
        self.assertIn("cmb", broker_map)
        self.assertIn("zhongxin", broker_map["citic"]["aliases"])
        self.assertIn("zhaoshang", broker_map["cmb"]["aliases"])

    def test_import_preserves_leading_zero_symbol(self) -> None:
        csv_text = (
            "成交日期,证券代码,买卖标志,成交数量,成交均价,成交编号\n"
            "2026-01-02,000001,买入,10,100,HT-003\n"
        )
        parsed = self.import_service.parse_trade_csv(
            broker="huatai",
            content=csv_text.encode("utf-8"),
        )
        self.assertEqual(parsed["record_count"], 1)
        self.assertEqual(parsed["records"][0]["symbol"], "000001")

    def test_import_dry_run_counts_in_file_duplicates(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        csv_text = (
            "成交日期,证券代码,买卖标志,成交数量,成交均价,成交编号,手续费,印花税\n"
            "2026-01-02,600519,买入,10,100,HT-004,1,0\n"
            "2026-01-02,600519,买入,10,100,HT-004,1,0\n"
        )
        parsed = self.import_service.parse_trade_csv(
            broker="huatai",
            content=csv_text.encode("utf-8"),
        )
        result = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed["records"],
            dry_run=True,
        )
        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(result["duplicate_count"], 1)

    def test_import_allows_identical_split_fills_without_trade_uid(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        csv_text = (
            "成交日期,证券代码,买卖标志,成交数量,成交均价,手续费,印花税\n"
            "2026-01-02,600519,买入,10,100,1,0\n"
            "2026-01-02,600519,买入,10,100,1,0\n"
        )
        parsed = self.import_service.parse_trade_csv(
            broker="huatai",
            content=csv_text.encode("utf-8"),
        )
        self.assertEqual(parsed["record_count"], 2)
        self.assertEqual(len({item["dedup_hash"] for item in parsed["records"]}), 2)

        first_commit = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed["records"],
        )
        second_commit = self.import_service.commit_trade_records(
            account_id=aid,
            broker="huatai",
            records=parsed["records"],
        )

        self.assertEqual(first_commit["inserted_count"], 2)
        self.assertEqual(first_commit["duplicate_count"], 0)
        self.assertEqual(second_commit["inserted_count"], 0)
        self.assertEqual(second_commit["duplicate_count"], 2)

    def test_risk_threshold_boundary(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=20000,
            currency="CNY",
        )
        self.service.record_trade(
            account_id=aid,
            symbol="600519",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=100,
            price=100,
            market="cn",
            currency="CNY",
        )
        self.service.record_trade(
            account_id=aid,
            symbol="000001",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=100,
            price=20,
            market="cn",
            currency="CNY",
        )

        self._save_close("600519", date(2026, 1, 1), 100.0)
        self._save_close("000001", date(2026, 1, 1), 20.0)
        self.service.get_portfolio_snapshot(account_id=aid, as_of=date(2026, 1, 1), cost_method="fifo")

        self._save_close("600519", date(2026, 1, 2), 70.0)
        self._save_close("000001", date(2026, 1, 2), 20.0)
        report = self.risk_service.get_risk_report(account_id=aid, as_of=date(2026, 1, 2), cost_method="fifo")

        self.assertTrue(report["concentration"]["alert"])
        self.assertTrue(report["drawdown"]["alert"])
        self.assertTrue(report["stop_loss"]["near_alert"])
        self.assertGreaterEqual(report["stop_loss"]["triggered_count"], 1)
        self.assertAlmostEqual(report["thresholds"]["drawdown_alert_pct"], 10.0, places=6)

    def test_risk_drawdown_backfills_snapshot_window_on_first_call(self) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=20000,
            currency="CNY",
        )
        self.service.record_trade(
            account_id=aid,
            symbol="600519",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=100,
            price=100,
            market="cn",
            currency="CNY",
        )
        self._save_close("600519", date(2026, 1, 1), 100.0)
        self._save_close("600519", date(2026, 1, 2), 70.0)

        report = self.risk_service.get_risk_report(account_id=aid, as_of=date(2026, 1, 2), cost_method="fifo")
        self.assertGreaterEqual(report["drawdown"]["series_points"], 2)
        self.assertGreater(report["drawdown"]["max_drawdown_pct"], 10.0)
        self.assertTrue(report["drawdown"]["alert"])

    def test_concentration_uses_cny_normalized_exposure(self) -> None:
        cn_account = self.service.create_account(name="CN", broker="Demo", market="cn", base_currency="CNY")
        us_account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="USD")
        cn_id = cn_account["id"]
        us_id = us_account["id"]

        self.service.record_cash_ledger(
            account_id=cn_id,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=1000.0,
            currency="CNY",
        )
        self.service.record_trade(
            account_id=cn_id,
            symbol="600519",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=10,
            price=100,
            market="cn",
            currency="CNY",
        )

        self.service.record_cash_ledger(
            account_id=us_id,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=100.0,
            currency="USD",
        )
        self.service.record_trade(
            account_id=us_id,
            symbol="AAPL",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=1,
            price=100,
            market="us",
            currency="USD",
        )
        self._save_close("600519", date(2026, 1, 1), 100.0)
        self._save_close("AAPL", date(2026, 1, 1), 100.0)
        self.service.repo.save_fx_rate(
            from_currency="USD",
            to_currency="CNY",
            rate_date=date(2026, 1, 1),
            rate=7.0,
            source="manual",
            is_stale=False,
        )
        self.service.get_portfolio_snapshot(as_of=date(2026, 1, 1), cost_method="fifo")

        report = self.risk_service.get_risk_report(as_of=date(2026, 1, 1), cost_method="fifo")
        positions = {item["symbol"]: item for item in report["concentration"]["top_positions"]}
        self.assertIn("AAPL", positions)
        self.assertAlmostEqual(positions["AAPL"]["market_value_base"], 700.0, places=6)

    def test_sector_concentration_uses_unclassified_for_non_cn(self) -> None:
        us_account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="USD")
        us_id = us_account["id"]
        self.service.record_cash_ledger(
            account_id=us_id,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=100.0,
            currency="USD",
        )
        self.service.record_trade(
            account_id=us_id,
            symbol="AAPL",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=1,
            price=100,
            market="us",
            currency="USD",
        )
        self._save_close("AAPL", date(2026, 1, 1), 100.0)
        report = self.risk_service.get_risk_report(account_id=us_id, as_of=date(2026, 1, 1), cost_method="fifo")
        self.assertIn("sector_concentration", report)
        sectors = report["sector_concentration"]["top_sectors"]
        self.assertTrue(len(sectors) >= 1)
        self.assertEqual(sectors[0]["sector"], "UNCLASSIFIED")

    @patch.object(PortfolioRiskService, "_fetch_belong_boards", return_value=[{"name": "白酒", "type": "行业"}])
    def test_sector_concentration_cn_board_mapping(self, _mock_fetch) -> None:
        account = self.service.create_account(name="Main", broker="Demo", market="cn", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=10000.0,
            currency="CNY",
        )
        self.service.record_trade(
            account_id=aid,
            symbol="600519",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=100,
            price=100,
            market="cn",
            currency="CNY",
        )
        self._save_close("600519", date(2026, 1, 1), 100.0)
        report = self.risk_service.get_risk_report(account_id=aid, as_of=date(2026, 1, 1), cost_method="fifo")
        sectors = report["sector_concentration"]["top_sectors"]
        self.assertTrue(len(sectors) >= 1)
        self.assertEqual(sectors[0]["sector"], "白酒")

    def test_snapshot_does_not_trigger_online_fx_refresh(self) -> None:
        account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=1000.0,
            currency="USD",
        )
        self.service.record_trade(
            account_id=aid,
            symbol="AAPL",
            trade_date=date(2026, 1, 1),
            side="buy",
            quantity=1,
            price=100,
            market="us",
            currency="USD",
        )
        self._save_close("AAPL", date(2026, 1, 1), 100.0)
        self.service.repo.save_fx_rate(
            from_currency="USD",
            to_currency="CNY",
            rate_date=date(2026, 1, 1),
            rate=7.0,
            source="manual",
            is_stale=False,
        )

        with patch.object(PortfolioService, "_fetch_fx_rate_from_yfinance", side_effect=AssertionError("should not call")):
            self.service.get_portfolio_snapshot(account_id=aid, as_of=date(2026, 1, 1), cost_method="fifo")

    def test_fx_refresh_fallback_marks_stale(self) -> None:
        account = self.service.create_account(name="US", broker="Demo", market="us", base_currency="CNY")
        aid = account["id"]
        self.service.record_cash_ledger(
            account_id=aid,
            event_date=date(2026, 1, 1),
            direction="in",
            amount=1000.0,
            currency="USD",
        )
        self.service.repo.save_fx_rate(
            from_currency="USD",
            to_currency="CNY",
            rate_date=date(2026, 1, 1),
            rate=7.0,
            source="manual",
            is_stale=False,
        )

        with patch.object(PortfolioService, "_fetch_fx_rate_from_yfinance", return_value=None):
            summary = self.service.refresh_fx_rates(account_id=aid, as_of=date(2026, 1, 2))

        self.assertEqual(summary["pair_count"], 1)
        self.assertEqual(summary["updated_count"], 0)
        self.assertEqual(summary["stale_count"], 1)
        latest = self.service.repo.get_latest_fx_rate(
            from_currency="USD",
            to_currency="CNY",
            as_of=date(2026, 1, 2),
        )
        self.assertIsNotNone(latest)
        self.assertTrue(bool(latest.is_stale))
        self.assertAlmostEqual(float(latest.rate), 7.0, places=6)

    def test_import_and_risk_endpoints(self) -> None:
        create_resp = self.client.post(
            "/api/v1/portfolio/accounts",
            json={"name": "Main", "broker": "Demo", "market": "cn", "base_currency": "CNY"},
        )
        self.assertEqual(create_resp.status_code, 200)
        account_id = create_resp.json()["id"]

        import_resp = self.client.post(
            "/api/v1/portfolio/imports/csv/commit",
            data={"account_id": str(account_id), "broker": "huatai", "dry_run": "false"},
            files={"file": ("huatai.csv", self._csv_bytes(with_trade_uid=True), "text/csv")},
        )
        self.assertEqual(import_resp.status_code, 200)
        self.assertEqual(import_resp.json()["inserted_count"], 1)

        self._save_close("600519", date(2026, 1, 2), 95.0)
        self.service.get_portfolio_snapshot(account_id=account_id, as_of=date(2026, 1, 2), cost_method="fifo")
        risk_resp = self.client.get(
            "/api/v1/portfolio/risk",
            params={"account_id": account_id, "as_of": "2026-01-02", "cost_method": "fifo"},
        )
        self.assertEqual(risk_resp.status_code, 200)
        payload = risk_resp.json()
        self.assertEqual(payload["cost_method"], "fifo")
        self.assertIn("concentration", payload)
        self.assertIn("sector_concentration", payload)
        self.assertIn("drawdown", payload)
        self.assertIn("stop_loss", payload)


if __name__ == "__main__":
    unittest.main()
