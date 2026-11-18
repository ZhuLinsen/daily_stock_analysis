from __future__ import annotations

import unittest
from datetime import date

from src.brokers.ibkr import statement as s
from src.brokers.ibkr.flex import IbkrPortfolioError


def _trade(**overrides) -> str:
    attrs = {
        "assetCategory": "STK",
        "levelOfDetail": "EXECUTION",
        "symbol": "AAPL",
        "listingExchange": "NASDAQ",
        "currency": "USD",
        "buySell": "BUY",
        "quantity": "10",
        "tradePrice": "230.5",
        "ibCommission": "-1",
        "taxes": "0",
        "tradeDate": "20260102",
        "tradeID": "12345",
    }
    attrs.update(overrides)
    return "<Trade " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + " />"


def _cash(**overrides) -> str:
    attrs = {
        "type": "Deposits/Withdrawals",
        "amount": "2000",
        "currency": "EUR",
        "dateTime": "20260105",
        "transactionID": "5186967799",
        "description": "CASH RECEIPTS / ELECTRONIC FUND TRANSFERS",
    }
    attrs.update(overrides)
    return "<CashTransaction " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + " />"


def _ca(**overrides) -> str:
    attrs = {
        "type": "RS",
        "symbol": "AMP",
        "actionDescription": "AMP SPLIT 1 FOR 25",
    }
    attrs.update(overrides)
    return "<CorporateAction " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + " />"


def _statement(*sections: str) -> bytes:
    return (
        '<FlexQueryResponse queryName="test" type="AF"><FlexStatements count="1">'
        '<FlexStatement accountId="U0000000" fromDate="20260101" toDate="20261117" period="YearToDate">'
        + "".join(sections)
        + "</FlexStatement></FlexStatements></FlexQueryResponse>"
    ).encode()


def _with_trades(*trades: str) -> bytes:
    return _statement(f"<Trades>{''.join(trades)}</Trades>")


def _with_cash(*rows: str) -> bytes:
    return _statement(f"<CashTransactions>{''.join(rows)}</CashTransactions>")


class IbkrStatementParseTest(unittest.TestCase):
    def test_parse_date_accepts_date_and_datetime(self) -> None:
        self.assertEqual(s._parse_flex_date("20260102"), date(2026, 1, 2))
        self.assertEqual(s._parse_flex_date("20260102;032459"), date(2026, 1, 2))
        self.assertIsNone(s._parse_flex_date(""))
        self.assertIsNone(s._parse_flex_date("not-a-date"))

    def test_canonical_symbol_by_market(self) -> None:
        self.assertEqual(s._canonical_symbol("BRK B", "us"), "BRK.B")
        self.assertEqual(s._canonical_symbol("AAPL", "us"), "AAPL")
        self.assertEqual(s._canonical_symbol("700", "hk"), "HK00700")
        self.assertEqual(s._canonical_symbol("7203", "jp"), "7203.T")
        self.assertIsNone(s._canonical_symbol("ABC", "hk"))
        self.assertIsNone(s._canonical_symbol("12", "jp"))

    def test_parses_supported_us_trade(self) -> None:
        result = s.parse_statement(_with_trades(_trade()))
        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.symbol, "AAPL")
        self.assertEqual(trade.market, "us")
        self.assertEqual(trade.side, "buy")
        self.assertEqual(trade.quantity, 10)
        self.assertEqual(trade.price, 230.5)
        self.assertEqual(trade.fee, 1)
        self.assertEqual(trade.tax, 0)
        self.assertEqual(trade.trade_uid, "12345")
        self.assertEqual(trade.trade_date, date(2026, 1, 2))

    def test_class_share_symbol_becomes_dot_form(self) -> None:
        result = s.parse_statement(
            _with_trades(_trade(symbol="BRK B", listingExchange="NYSE"))
        )
        self.assertEqual(result.trades[0].symbol, "BRK.B")

    def test_hk_and_jp_trades(self) -> None:
        result = s.parse_statement(
            _with_trades(
                _trade(symbol="700", listingExchange="SEHK", currency="HKD"),
                _trade(symbol="7203", listingExchange="TSEJ", currency="JPY"),
            )
        )
        self.assertEqual(
            [(t.symbol, t.market) for t in result.trades],
            [("HK00700", "hk"), ("7203.T", "jp")],
        )

    def test_sell_with_negative_quantity_uses_buysell(self) -> None:
        result = s.parse_statement(
            _with_trades(_trade(buySell="SELL", quantity="-4", tradeID="999"))
        )
        self.assertEqual(result.trades[0].side, "sell")
        self.assertEqual(result.trades[0].quantity, 4)

    def test_unsupported_exchange_skipped(self) -> None:
        result = s.parse_statement(
            _with_trades(_trade(symbol="SAN", listingExchange="BM", currency="EUR"))
        )
        self.assertEqual(result.trades, [])
        self.assertIn("SAN@BM", result.skipped_trades)

    def test_fx_and_summary_rows_are_skipped(self) -> None:
        result = s.parse_statement(
            _with_trades(
                _trade(assetCategory="CASH", symbol="EUR.USD"),
                _trade(levelOfDetail="SYMBOL_SUMMARY", tradeID="111"),
            )
        )
        self.assertEqual(result.trades, [])
        self.assertEqual(result.skipped_trades, [])

    def test_malformed_trades_skipped_with_reason(self) -> None:
        cases = {
            "missing symbol": _trade(symbol=""),
            "bad date": _trade(tradeDate="2026-01-02"),
            "missing tradeID": _trade(tradeID=""),
            "bad quantity": _trade(quantity="abc"),
            "zero quantity": _trade(buySell="BUY", quantity="0"),
        }
        for name, xml in cases.items():
            with self.subTest(name=name):
                result = s.parse_statement(_with_trades(xml))
                self.assertEqual(result.trades, [])
                self.assertTrue(result.skipped_trades, name)

    def test_deposit_and_withdrawal(self) -> None:
        result = s.parse_statement(
            _with_cash(_cash(), _cash(amount="-500", transactionID="2", description="WITHDRAWAL"))
        )
        self.assertEqual(len(result.cash_events), 2)
        self.assertEqual(result.cash_events[0].direction, "in")
        self.assertEqual(result.cash_events[0].amount, 2000)
        self.assertEqual(result.cash_events[1].direction, "out")
        self.assertEqual(result.cash_events[1].amount, 500)

    def test_non_deposit_cash_skipped(self) -> None:
        result = s.parse_statement(
            _with_cash(
                _cash(type="Dividends", transactionID="3"),
                _cash(type="Withholding Tax", transactionID="4"),
                _cash(type="Other Fees", transactionID="5"),
            )
        )
        self.assertEqual(result.cash_events, [])
        self.assertEqual(len(result.skipped_cash), 3)

    def test_corporate_actions_reported_as_skipped(self) -> None:
        result = s.parse_statement(_statement("<CorporateActions>" + _ca() + "</CorporateActions>"))
        self.assertEqual(result.skipped_corporate_actions, ["AMP: AMP SPLIT 1 FOR 25"])

    def test_invalid_xml_or_root_fails(self) -> None:
        for bad in (b"<html>x</html>", b"<FlexStatementResponse />"):
            with self.subTest(bad=bad), self.assertRaises(IbkrPortfolioError):
                s.parse_statement(bad)


if __name__ == "__main__":
    unittest.main()
