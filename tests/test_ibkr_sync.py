from __future__ import annotations

import os
import unittest
from datetime import date, time
from unittest.mock import MagicMock, patch

from src.brokers.ibkr import sync
from src.brokers.ibkr.flex import IbkrPortfolioError
from src.services.portfolio_service import PortfolioConflictError, PortfolioOversellError


def _trade(symbol, side, trade_id, trade_date="20260102", exchange="NASDAQ", currency="USD",
           open_close=None, account="U0000000", trade_time="093000"):
    qty = "10" if side == "BUY" else "-5"
    # Default mirrors a long-only ledger: buys open, sells close.
    if open_close is None:
        open_close = "O" if side == "BUY" else "C"
    return (
        '<Trade assetCategory="STK" levelOfDetail="EXECUTION" '
        f'symbol="{symbol}" listingExchange="{exchange}" currency="{currency}" '
        f'buySell="{side}" quantity="{qty}" tradePrice="230.5" '
        f'ibCommission="-1" taxes="0" tradeDate="{trade_date}" '
        f'dateTime="{trade_date};{trade_time}" tradeID="{trade_id}" '
        f'accountId="{account}" openCloseIndicator="{open_close}" />'
    )


def _statement(*trades: str) -> bytes:
    return (
        '<FlexQueryResponse queryName="test" type="AF"><FlexStatements count="1">'
        '<FlexStatement accountId="U0000000" fromDate="20260101" toDate="20261117" period="YearToDate">'
        f"<Trades>{''.join(trades)}</Trades><CashTransactions></CashTransactions>"
        "</FlexStatement></FlexStatements></FlexQueryResponse>"
    ).encode()


class IbkrSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            "os.environ",
            {"IBKR_FLEX_TOKEN": "tok", "IBKR_FLEX_STATEMENT_QUERY_ID": "1712897"},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def _service(self) -> MagicMock:
        service = MagicMock()
        service.list_accounts.return_value = [{"id": 1, "broker": "IBKR"}]
        service.has_trade_uid.return_value = False
        service.find_same_day_trade_conflicts.return_value = []
        service.record_trade.return_value = {"id": 1}
        service.record_cash_ledger.return_value = {"id": 1}
        return service

    def test_imports_trades_in_chronological_order(self) -> None:
        service = self._service()
        statement = _statement(
            _trade("AAPL", "SELL", "200"),  # deliberately out of order
            _trade("AAPL", "BUY", "100"),
        )
        with patch.object(sync, "PortfolioService", return_value=service), patch.object(
            sync, "download_flex_statement", side_effect=[statement, _statement()]
        ):
            summary = sync.sync_ibkr_portfolio()

        sides = [c.kwargs["side"] for c in service.record_trade.call_args_list]
        self.assertEqual(sides, ["buy", "sell"])
        self.assertEqual(summary["trades_inserted"], 2)
        self.assertEqual(summary["trades_duplicate"], 0)

    def test_duplicate_trades_and_cash_are_counted_not_errors(self) -> None:
        service = self._service()
        service.record_trade.side_effect = PortfolioConflictError("dup")

        body = (
            '<FlexQueryResponse queryName="t" type="AF"><FlexStatements count="1">'
            '<FlexStatement accountId="U0000000" fromDate="20260101" toDate="20261117" period="YearToDate">'
            '<Trades>' + _trade("AAPL", "BUY", "100") + "</Trades>"
            '<CashTransactions><CashTransaction type="Deposits/Withdrawals" amount="2000" '
            'currency="EUR" dateTime="20260105" transactionID="111" description="d" '
            'accountId="U0000000" />'
            "</CashTransactions></FlexStatement></FlexStatements></FlexQueryResponse>"
        ).encode()
        service.record_cash_ledger.side_effect = PortfolioConflictError("dup")

        with patch.object(sync, "PortfolioService", return_value=service), patch.object(
            sync, "download_flex_statement", side_effect=[body, _statement()]
        ):
            summary = sync.sync_ibkr_portfolio()

        self.assertEqual(summary["trades_duplicate"], 1)
        self.assertEqual(summary["cash_duplicate"], 1)
        self.assertEqual(summary["trades_inserted"], 0)
        self.assertEqual(summary["cash_inserted"], 0)
        self.assertEqual(summary["errors"], [])

    def test_oversell_is_reported_as_error_and_sync_continues(self) -> None:
        service = self._service()
        service.record_trade.side_effect = PortfolioOversellError(
            symbol="AAPL", trade_date=date(2026, 1, 2), requested_quantity=5, available_quantity=0
        )
        with patch.object(sync, "PortfolioService", return_value=service), patch.object(
            sync, "download_flex_statement", side_effect=[_statement(_trade("AAPL", "SELL", "100")), _statement()]
        ):
            summary = sync.sync_ibkr_portfolio()

        self.assertTrue(any("oversell" in e for e in summary["errors"]))
        self.assertEqual(summary["trades_inserted"], 0)

    def test_symbol_is_blocked_after_oversell_to_avoid_phantom_long(self) -> None:
        # Short open fails as oversell, then the buy-to-cover must NOT be imported.
        service = self._service()
        service.record_trade.side_effect = PortfolioOversellError(
            symbol="AAPL", trade_date=date(2026, 1, 2), requested_quantity=10, available_quantity=0
        )
        statement = _statement(
            _trade("AAPL", "SELL", "100", trade_date="20260102"),
            _trade("AAPL", "BUY", "101", trade_date="20260103"),
        )
        with patch.object(sync, "PortfolioService", return_value=service), patch.object(
            sync, "download_flex_statement", side_effect=[statement, _statement()]
        ):
            summary = sync.sync_ibkr_portfolio()

        # Only the first (failing) attempt reached record_trade; the cover was skipped.
        self.assertEqual(service.record_trade.call_count, 1)
        self.assertEqual(summary["trades_inserted"], 0)
        self.assertEqual(summary["trades_skipped_unbalanced"], 1)

    def test_dry_run_parses_but_does_not_write(self) -> None:
        service = self._service()
        with patch.object(sync, "PortfolioService", return_value=service), patch.object(
            sync, "download_flex_statement", side_effect=[_statement(_trade("AAPL", "BUY", "100")), _statement()]
        ):
            summary = sync.sync_ibkr_portfolio(dry_run=True)

        service.record_trade.assert_not_called()
        service.record_cash_ledger.assert_not_called()
        self.assertEqual(summary["dry_run"], True)
        self.assertEqual(summary["trades_inserted"], 1)

    def test_requires_credentials(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(IbkrPortfolioError, "IBKR_FLEX_TOKEN"):
                sync._resolve_credentials()

    def test_resolve_account_id(self) -> None:
        service = MagicMock()
        service.list_accounts.return_value = [{"id": 7, "broker": "IBKR"}, {"id": 8, "broker": "Demo"}]
        self.assertEqual(sync._resolve_account_id(service, None), 7)
        # An explicit id must still be an IBKR account.
        self.assertEqual(sync._resolve_account_id(service, 7), 7)
        with self.assertRaisesRegex(IbkrPortfolioError, "不是 broker=IBKR"):
            sync._resolve_account_id(service, 8)

        service.list_accounts.return_value = [{"id": 7, "broker": "A"}, {"id": 8, "broker": "B"}]
        with self.assertRaisesRegex(IbkrPortfolioError, "broker=IBKR"):
            sync._resolve_account_id(service, None)

    def test_dry_run_does_not_construct_the_ledger_service(self) -> None:
        # Constructing PortfolioService initializes the DB and runs migrations,
        # so a preview must never reach it.
        with patch.object(sync, "PortfolioService") as service_cls, patch.object(
            sync, "download_flex_statement", side_effect=[_statement(_trade("AAPL", "BUY", "1")), _statement()]
        ):
            summary = sync.sync_ibkr_portfolio(dry_run=True)

        service_cls.assert_not_called()
        self.assertIsNone(summary["account_id"])
        self.assertEqual(summary["trades_inserted"], 1)

    def test_short_cover_buy_is_skipped_outside_the_sync_window(self) -> None:
        # The short opened before --since, so only the closing BUY is in the
        # window; booking it as a long would be a phantom position.
        service = self._service()
        cover = _trade("AAPL", "BUY", "100", open_close="C")
        with patch.object(sync, "PortfolioService", return_value=service), patch.object(
            sync, "download_flex_statement", side_effect=[_statement(cover), _statement()]
        ):
            summary = sync.sync_ibkr_portfolio()

        service.record_trade.assert_not_called()
        self.assertEqual(summary["trades_inserted"], 0)
        self.assertEqual(summary["trades_skipped_unbalanced"], 1)

    def test_resolve_account_id_never_uses_a_non_ibkr_account(self) -> None:
        service = MagicMock()
        # A sole active account belonging to another broker must not be reused.
        service.list_accounts.return_value = [{"id": 3, "broker": "Futu"}]
        with self.assertRaisesRegex(IbkrPortfolioError, "broker=IBKR"):
            sync._resolve_account_id(service, None)

    def test_resolve_account_id_rejects_multiple_ibkr_accounts(self) -> None:
        service = MagicMock()
        service.list_accounts.return_value = [
            {"id": 1, "broker": "IBKR"},
            {"id": 2, "broker": "IBKR"},
        ]
        with self.assertRaisesRegex(IbkrPortfolioError, "多个 IBKR"):
            sync._resolve_account_id(service, None)

    def test_chunk_windows_respects_365_day_limit(self) -> None:
        windows = sync._chunk_windows(date(2024, 1, 1), date(2026, 11, 18))
        self.assertEqual(len(windows), 3)
        self.assertEqual(windows[0][0], "20240101")
        self.assertEqual(windows[-1][1], "20261118")


if __name__ == "__main__":
    unittest.main()


class IbkrSyncShortSymmetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            "os.environ",
            {"IBKR_FLEX_TOKEN": "tok", "IBKR_FLEX_STATEMENT_QUERY_ID": "1712897"},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def _service(self):
        service = MagicMock()
        service.list_accounts.return_value = [{"id": 1, "broker": "IBKR"}]
        service.has_trade_uid.return_value = False
        service.find_same_day_trade_conflicts.return_value = []
        service.record_trade.return_value = {"id": 1}
        service.record_cash_ledger.return_value = {"id": 1}
        return service

    def test_short_open_sell_is_skipped_not_booked_as_a_sale(self) -> None:
        service = self._service()
        short_open = _trade("AAPL", "SELL", "100", open_close="O")
        with patch.object(sync, "PortfolioService", return_value=service), patch.object(
            sync, "download_flex_statement", side_effect=[_statement(short_open), _statement()]
        ):
            summary = sync.sync_ibkr_portfolio()

        service.record_trade.assert_not_called()
        self.assertEqual(summary["trades_skipped_unbalanced"], 1)

    def test_long_sale_marked_close_is_still_imported(self) -> None:
        service = self._service()
        long_sale = _trade("AAPL", "SELL", "100", open_close="C")
        with patch.object(sync, "PortfolioService", return_value=service), patch.object(
            sync, "download_flex_statement", side_effect=[_statement(long_sale), _statement()]
        ):
            summary = sync.sync_ibkr_portfolio()

        self.assertEqual(service.record_trade.call_count, 1)
        self.assertEqual(summary["trades_inserted"], 1)


class IbkrSyncShortOpenThenLongTest(unittest.TestCase):
    """A skipped short cover must not block a later genuine long open."""

    def setUp(self) -> None:
        self.env = patch.dict(
            "os.environ",
            {"IBKR_FLEX_TOKEN": "tok", "IBKR_FLEX_STATEMENT_QUERY_ID": "1712897"},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def test_cover_then_open_long_imports_the_long(self) -> None:
        service = MagicMock()
        service.list_accounts.return_value = [{"id": 1, "broker": "IBKR"}]
        service.has_trade_uid.return_value = False
        service.find_same_day_trade_conflicts.return_value = []
        service.record_trade.return_value = {"id": 1}
        service.record_cash_ledger.return_value = {"id": 1}
        statement = _statement(
            _trade("AAPL", "BUY", "100", trade_date="20260102", open_close="C"),
            _trade("AAPL", "BUY", "101", trade_date="20260103", open_close="O"),
        )
        with patch.object(sync, "PortfolioService", return_value=service), patch.object(
            sync, "download_flex_statement", side_effect=[statement, _statement()]
        ):
            summary = sync.sync_ibkr_portfolio()

        self.assertEqual(service.record_trade.call_count, 1)
        self.assertEqual(summary["trades_inserted"], 1)
        self.assertEqual(summary["trades_skipped_unbalanced"], 1)


class IbkrSameDayOrderingTest(unittest.TestCase):
    """Same-day executions commit in time order, not trade-id order (PR #2565 review)."""

    def setUp(self) -> None:
        self.env = patch.dict(
            "os.environ",
            {"IBKR_FLEX_TOKEN": "tok", "IBKR_FLEX_STATEMENT_QUERY_ID": "1712897"},
            clear=False,
        )
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()

    def _service(self):
        service = MagicMock()
        service.list_accounts.return_value = [{"id": 1, "broker": "IBKR"}]
        service.has_trade_uid.return_value = False
        service.find_same_day_trade_conflicts.return_value = []
        service.record_trade.return_value = {"id": 1}
        service.record_cash_ledger.return_value = {"id": 1}
        return service

    def _sync(self, service, *trades):
        with patch.object(sync, "PortfolioService", return_value=service), patch.object(
            sync, "download_flex_statement", side_effect=[_statement(*trades), _statement()]
        ):
            return sync.sync_ibkr_portfolio()

    def test_intraday_buy_then_sell_with_reversed_trade_ids(self) -> None:
        # The reported blocker: a 09:30 buy and a 15:30 sell whose trade ids run
        # backwards. Sorting by id would commit the sell first, report an
        # oversell and skip the real buy.
        service = self._service()
        summary = self._sync(
            service,
            _trade("AAPL", "BUY", "900", trade_time="093000"),
            _trade("AAPL", "SELL", "100", trade_time="153000"),
        )

        sides = [c.kwargs["side"] for c in service.record_trade.call_args_list]
        self.assertEqual(sides, ["buy", "sell"])
        self.assertEqual(summary["errors"], [])
        self.assertEqual(summary["trades_skipped_unbalanced"], 0)
        self.assertEqual(summary["trades_inserted"], 2)

    def test_non_numeric_trade_ids_still_order_by_time(self) -> None:
        service = self._service()
        self._sync(
            service,
            _trade("MSFT", "SELL", "exec-b", trade_time="100000"),
            _trade("MSFT", "BUY", "exec-a", trade_time="093000"),
        )

        self.assertEqual(
            [c.kwargs["side"] for c in service.record_trade.call_args_list], ["buy", "sell"]
        )

    def test_trade_id_breaks_ties_at_the_same_second(self) -> None:
        service = self._service()
        self._sync(
            service,
            _trade("AAPL", "SELL", "200", trade_time="093000"),
            _trade("AAPL", "BUY", "100", trade_time="093000"),
        )

        self.assertEqual(
            [c.kwargs["side"] for c in service.record_trade.call_args_list], ["buy", "sell"]
        )

    def test_sort_key_uses_date_then_time_then_id(self) -> None:
        from src.brokers.ibkr.statement import TradeRecord

        def record(day, clock, uid):
            return TradeRecord(
                symbol="AAPL", market="us", currency="USD", trade_date=day, trade_time=clock,
                side="buy", quantity=1.0, price=1.0, fee=0.0, tax=0.0, trade_uid=uid,
            )

        early = record(date(2026, 1, 2), time(9, 30), "900")
        late = record(date(2026, 1, 2), time(15, 30), "100")
        next_day = record(date(2026, 1, 3), time(9, 0), "1")

        self.assertEqual(
            sorted([late, next_day, early], key=sync._trade_sort_key),
            [early, late, next_day],
        )


class IbkrSameDayLedgerConflictTest(unittest.TestCase):
    """Guard against mixing a new import with same-day rows already in the ledger.

    These run against a real SQLite ledger, because the ordering the guard
    protects is decided by stored ids on replay, not by the import batch.
    """

    def setUp(self) -> None:
        self.env = patch.dict(
            "os.environ",
            {"IBKR_FLEX_TOKEN": "tok", "IBKR_FLEX_STATEMENT_QUERY_ID": "1712897"},
            clear=False,
        )
        self.env.start()

        import tempfile
        from pathlib import Path

        from src.config import Config
        from src.storage import DatabaseManager

        self.temp_dir = tempfile.TemporaryDirectory()
        env_path = Path(self.temp_dir.name) / ".env"
        db_path = Path(self.temp_dir.name) / "ibkr_guard.db"
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
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        from src.config import Config
        from src.storage import DatabaseManager

        self.env.stop()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.temp_dir.cleanup()

    def _ledger(self):
        from src.services.portfolio_service import PortfolioService

        service = PortfolioService()
        account = service.create_account(name="IBKR", broker="IBKR", market="us", base_currency="USD")
        return service, account["id"]

    def _sync(self, *trades):
        with patch.object(sync, "download_flex_statement", side_effect=[_statement(*trades), _statement()]):
            return sync.sync_ibkr_portfolio()

    def test_existing_same_day_row_refuses_the_import(self) -> None:
        from src.brokers.ibkr.flex import IbkrPortfolioError

        service, account_id = self._ledger()
        # A row already in the ledger for that symbol and date, written earlier
        # and therefore with a lower id than anything this import would add.
        service.record_trade(
            account_id=account_id, symbol="AAPL", trade_date=date(2026, 1, 2),
            side="buy", quantity=10, price=200.0, trade_uid="manual-1",
        )

        with self.assertRaises(IbkrPortfolioError) as ctx:
            self._sync(_trade("AAPL", "BUY", "900", trade_time="093000"))

        self.assertIn("AAPL@2026-01-02", str(ctx.exception))
        self.assertEqual(len(service.repo.list_trades(account_id, date(2026, 1, 2))), 1)

    def test_other_date_or_symbol_does_not_refuse(self) -> None:
        service, account_id = self._ledger()
        service.record_trade(
            account_id=account_id, symbol="AAPL", trade_date=date(2025, 12, 31),
            side="buy", quantity=10, price=200.0, trade_uid="older",
        )
        service.record_trade(
            account_id=account_id, symbol="MSFT", trade_date=date(2026, 1, 2),
            side="buy", quantity=5, price=300.0, trade_uid="other-symbol",
        )

        summary = self._sync(_trade("AAPL", "BUY", "900", trade_time="093000"))

        self.assertEqual(summary["trades_inserted"], 1)
        self.assertEqual(summary["errors"], [])

    def test_rerun_of_the_same_trades_is_still_idempotent(self) -> None:
        # Everything this sync would write already exists, so there is nothing to
        # order: the guard must not turn a no-op re-run into a failure.
        service, account_id = self._ledger()
        service.record_trade(
            account_id=account_id, symbol="AAPL", trade_date=date(2026, 1, 2),
            side="buy", quantity=10, price=230.5, trade_uid="100",
        )

        summary = self._sync(_trade("AAPL", "BUY", "100", trade_time="093000"))

        self.assertEqual(summary["trades_inserted"], 0)
        self.assertEqual(summary["trades_duplicate"], 1)
        self.assertEqual(summary["errors"], [])

    def test_dry_run_never_touches_the_ledger_or_the_guard(self) -> None:
        statement = _statement(_trade("AAPL", "BUY", "900", trade_time="093000"))
        with patch.object(sync, "PortfolioService") as service_cls, patch.object(
            sync, "download_flex_statement", side_effect=[statement, _statement()]
        ):
            summary = sync.sync_ibkr_portfolio(dry_run=True)

        service_cls.assert_not_called()
        self.assertEqual(summary["trades_inserted"], 1)
