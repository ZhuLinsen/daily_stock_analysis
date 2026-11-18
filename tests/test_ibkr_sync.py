from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from src.brokers.ibkr import sync
from src.brokers.ibkr.flex import IbkrPortfolioError
from src.services.portfolio_service import PortfolioConflictError, PortfolioOversellError


def _trade(symbol, side, trade_id, trade_date="20260102", exchange="NASDAQ", currency="USD"):
    qty = "10" if side == "BUY" else "-5"
    return (
        '<Trade assetCategory="STK" levelOfDetail="EXECUTION" '
        f'symbol="{symbol}" listingExchange="{exchange}" currency="{currency}" '
        f'buySell="{side}" quantity="{qty}" tradePrice="230.5" '
        f'ibCommission="-1" taxes="0" tradeDate="{trade_date}" tradeID="{trade_id}" />'
    )


def _statement(*trades: str) -> bytes:
    return (
        '<FlexQueryResponse queryName="test" type="AF"><FlexStatements count="1">'
        '<FlexStatement accountId="U0000000" fromDate="20260101" toDate="20261117" period="YearToDate">'
        f"<Trades>{''.join(trades)}</Trades>"
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
            '<FlexStatement accountId="U" fromDate="20260101" toDate="20261117" period="YearToDate">'
            '<Trades>' + _trade("AAPL", "BUY", "100") + "</Trades>"
            '<CashTransactions><CashTransaction type="Deposits/Withdrawals" amount="2000" '
            'currency="EUR" dateTime="20260105" transactionID="111" description="d" />'
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
        self.assertEqual(sync._resolve_account_id(service, 8), 8)

        service.list_accounts.return_value = [{"id": 7, "broker": "A"}, {"id": 8, "broker": "B"}]
        with self.assertRaisesRegex(IbkrPortfolioError, "account-id"):
            sync._resolve_account_id(service, None)

    def test_chunk_windows_respects_365_day_limit(self) -> None:
        windows = sync._chunk_windows(date(2024, 1, 1), date(2026, 11, 18))
        self.assertEqual(len(windows), 3)
        self.assertEqual(windows[0][0], "20240101")
        self.assertEqual(windows[-1][1], "20261118")


if __name__ == "__main__":
    unittest.main()
