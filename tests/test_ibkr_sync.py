from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from src.brokers.ibkr import sync
from src.brokers.ibkr.flex import IbkrPortfolioError
from src.services.portfolio_service import PortfolioConflictError, PortfolioOversellError


def _trade(symbol, side, trade_id, trade_date="20260102", exchange="NASDAQ", currency="USD",
           open_close=None, account="U0000000"):
    qty = "10" if side == "BUY" else "-5"
    # Default mirrors a long-only ledger: buys open, sells close.
    if open_close is None:
        open_close = "O" if side == "BUY" else "C"
    return (
        '<Trade assetCategory="STK" levelOfDetail="EXECUTION" '
        f'symbol="{symbol}" listingExchange="{exchange}" currency="{currency}" '
        f'buySell="{side}" quantity="{qty}" tradePrice="230.5" '
        f'ibCommission="-1" taxes="0" tradeDate="{trade_date}" tradeID="{trade_id}" '
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
