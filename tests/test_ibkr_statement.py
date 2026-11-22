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
        "accountId": "U0000000",
        "openCloseIndicator": "O",
    }
    attrs.update(overrides)
    # Default mirrors a long-only ledger: buys open, sells close.
    if "openCloseIndicator" not in overrides:
        attrs["openCloseIndicator"] = "C" if attrs.get("buySell") == "SELL" else "O"
    return "<Trade " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) + " />"


def _cash(**overrides) -> str:
    attrs = {
        "type": "Deposits/Withdrawals",
        "amount": "2000",
        "currency": "EUR",
        "dateTime": "20260105",
        "transactionID": "5186967799",
        "description": "CASH RECEIPTS / ELECTRONIC FUND TRANSFERS",
        "accountId": "U0000000",
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
    # A valid ledger statement always carries both required sections.
    return _statement(
        f"<Trades>{''.join(trades)}</Trades><CashTransactions></CashTransactions>"
    )


def _with_cash(*rows: str) -> bytes:
    return _statement(
        f"<Trades></Trades><CashTransactions>{''.join(rows)}</CashTransactions>"
    )


class IbkrStatementParseTest(unittest.TestCase):
    def test_parse_date_accepts_date_and_datetime(self) -> None:
        self.assertEqual(s._parse_flex_date("20260102"), date(2026, 1, 2))
        self.assertEqual(s._parse_flex_date("20260102;032459"), date(2026, 1, 2))
        self.assertIsNone(s._parse_flex_date(""))
        self.assertIsNone(s._parse_flex_date("not-a-date"))

    def test_canonical_symbol_by_market(self) -> None:
        self.assertIsNone(s._canonical_symbol("BRK B", "us"))  # class share unsupported
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

    def test_class_share_symbol_is_skipped(self) -> None:
        result = s.parse_statement(
            _with_trades(_trade(symbol="BRK B", listingExchange="NYSE"))
        )
        self.assertEqual(result.trades, [])
        self.assertEqual(result.skipped_trades, ["BRK B@NYSE"])

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
            "bad date": _trade(tradeDate="not-a-date"),
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
        result = s.parse_statement(
            _statement(
                "<Trades></Trades><CashTransactions></CashTransactions>"
                "<CorporateActions>" + _ca() + "</CorporateActions>"
            )
        )
        self.assertEqual(result.skipped_corporate_actions, ["AMP: AMP SPLIT 1 FOR 25"])

    def test_orders_detail_level_fails_instead_of_dropping_trades(self) -> None:
        # Trades configured with the Orders detail level yields rows but no
        # EXECUTION rows; every stock trade would otherwise vanish silently.
        xml = _statement(
            "<Trades>"
            + _trade(levelOfDetail="ORDER")
            + "</Trades><CashTransactions></CashTransactions>"
        )
        with self.assertRaisesRegex(IbkrPortfolioError, "Executions"):
            s.parse_statement(xml)

    def test_empty_trades_section_is_still_valid(self) -> None:
        result = s.parse_statement(_statement("<Trades></Trades><CashTransactions></CashTransactions>"))
        self.assertEqual(result.trades, [])

    def test_short_cover_buy_is_recorded_with_open_close(self) -> None:
        result = s.parse_statement(
            _with_trades(_trade(buySell="BUY", quantity="10", openCloseIndicator="C"))
        )
        self.assertEqual(result.trades[0].open_close, "C")

    def test_positions_only_statement_fails(self) -> None:
        xml = _statement(
            '<OpenPositions><OpenPosition assetCategory="STK" symbol="AAPL" '
            'listingExchange="NASDAQ" position="10" /></OpenPositions>'
        )
        with self.assertRaisesRegex(IbkrPortfolioError, "Trades / CashTransactions"):
            s.parse_statement(xml)

    def test_trades_only_statement_fails(self) -> None:
        xml = _statement(f"<Trades>{_trade()}</Trades>")
        with self.assertRaisesRegex(IbkrPortfolioError, "CashTransactions"):
            s.parse_statement(xml)

    def test_cash_only_statement_fails(self) -> None:
        xml = _statement(f"<CashTransactions>{_cash()}</CashTransactions>")
        with self.assertRaisesRegex(IbkrPortfolioError, "Trades"):
            s.parse_statement(xml)

    def test_jp_alphanumeric_trade_symbol(self) -> None:
        result = s.parse_statement(
            _with_trades(_trade(symbol="130A", listingExchange="TSEJ", currency="JPY"))
        )
        self.assertEqual(result.trades[0].symbol, "130A.T")
        self.assertEqual(result.trades[0].market, "jp")

    def test_multi_account_rows_fail(self) -> None:
        xml = _statement(
            "<Trades>"
            + _trade(accountId="A111")
            + _trade(symbol="NVDA", accountId="B222")
            + "</Trades><CashTransactions></CashTransactions>"
        )
        with self.assertRaisesRegex(IbkrPortfolioError, "多个账户"):
            s.parse_statement(xml)

    def test_invalid_xml_or_root_fails(self) -> None:
        for bad in (b"<html>x</html>", b"<FlexStatementResponse />"):
            with self.subTest(bad=bad), self.assertRaises(IbkrPortfolioError):
                s.parse_statement(bad)

    def test_multiple_accounts_fail(self) -> None:
        one = (
            '<FlexQueryResponse queryName="t" type="AF"><FlexStatements count="2">'
            '<FlexStatement accountId="A111" fromDate="20260101" toDate="20261117" period="YearToDate">'
            f'<Trades>{_trade()}</Trades></FlexStatement>'
            '<FlexStatement accountId="B222" fromDate="20260101" toDate="20261117" period="YearToDate">'
            f'<Trades>{_trade(symbol="NVDA")}</Trades></FlexStatement>'
            '</FlexStatements></FlexQueryResponse>'
        ).encode()
        with self.assertRaisesRegex(IbkrPortfolioError, "多个账户"):
            s.parse_statement(one)


if __name__ == "__main__":
    unittest.main()


class IbkrStatementStrictnessTest(unittest.TestCase):
    def test_missing_asset_category_on_trades_raises(self) -> None:
        row = (
            '<Trade levelOfDetail="EXECUTION" symbol="AAPL" listingExchange="NASDAQ" '
            'currency="USD" buySell="BUY" quantity="10" tradePrice="100" '
            'tradeDate="20260102" tradeID="1" />'
        )
        with self.assertRaisesRegex(IbkrPortfolioError, "assetCategory"):
            s.parse_statement(_statement(f"<Trades>{row}</Trades><CashTransactions></CashTransactions>"))

    def test_us_symbol_is_validated_not_taken_verbatim(self) -> None:
        # A non-US-shaped code must not slip into the ledger just because IBKR
        # listed it on a US exchange.
        self.assertIsNone(s._canonical_symbol("SPX", "us"))
        self.assertEqual(s._canonical_symbol("AAPL", "us"), "AAPL")


class IbkrRequiredFieldContractTest(unittest.TestCase):
    """The ledger parser must fail closed on Flex fields it depends on."""

    def _one(self, **trade_overrides) -> bytes:
        row = _trade(**trade_overrides)
        return _statement(f"<Trades>{row}</Trades><CashTransactions></CashTransactions>")

    def test_missing_open_close_indicator_raises(self) -> None:
        row = _trade()
        row = row.replace(' openCloseIndicator="O"', "")
        with self.assertRaisesRegex(IbkrPortfolioError, "openCloseIndicator"):
            s.parse_statement(
                _statement(f"<Trades>{row}</Trades><CashTransactions></CashTransactions>")
            )

    def test_missing_listing_exchange_raises(self) -> None:
        row = _trade().replace(' listingExchange="NASDAQ"', "")
        with self.assertRaisesRegex(IbkrPortfolioError, "listingExchange"):
            s.parse_statement(
                _statement(f"<Trades>{row}</Trades><CashTransactions></CashTransactions>")
            )

    def test_missing_row_account_id_raises(self) -> None:
        row = _trade().replace(' accountId="U0000000"', "")
        with self.assertRaisesRegex(IbkrPortfolioError, "accountId"):
            s.parse_statement(
                _statement(f"<Trades>{row}</Trades><CashTransactions></CashTransactions>")
            )

    def test_hyphenated_dates_are_accepted(self) -> None:
        result = s.parse_statement(self._one(tradeDate="2026-01-02"))
        self.assertEqual(result.trades[0].trade_date, date(2026, 1, 2))

    def test_flex_datetime_form_is_accepted(self) -> None:
        self.assertEqual(s._parse_flex_date("20260102;032459"), date(2026, 1, 2))
        self.assertEqual(s._parse_flex_date("2026-01-02;032459"), date(2026, 1, 2))

    def test_cash_note_keeps_the_cleanup_marker(self) -> None:
        result = s.parse_statement(_with_cash(_cash()))
        note = result.cash_events[0].note
        self.assertTrue(note.startswith(s.NOTE_MARKER), note)
        self.assertIn("ELECTRONIC FUND TRANSFER", note)


class IbkrOpenCloseValidationTest(unittest.TestCase):
    def _with_value(self, value: str) -> bytes:
        row = _trade().replace('openCloseIndicator="O"', f'openCloseIndicator="{value}"')
        return _statement(f"<Trades>{row}</Trades><CashTransactions></CashTransactions>")

    def test_empty_open_close_is_rejected(self) -> None:
        with self.assertRaisesRegex(IbkrPortfolioError, "openCloseIndicator"):
            s.parse_statement(self._with_value(""))

    def test_unexpected_open_close_is_rejected(self) -> None:
        with self.assertRaisesRegex(IbkrPortfolioError, "openCloseIndicator"):
            s.parse_statement(self._with_value("X"))

    def test_lowercase_open_close_is_accepted(self) -> None:
        result = s.parse_statement(self._with_value("c"))
        self.assertEqual(result.trades[0].open_close, "C")
