from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import requests

from src.brokers.errors import BrokerPortfolioError
from src.brokers.futu.portfolio import FutuPortfolioError
from src.brokers.ibkr import flex
from src.brokers.ibkr import portfolio as service
from src.brokers.ibkr.flex import IbkrPortfolioError

TOKEN = "123456789012345678901234"


def _position(symbol, exchange, position="10", category="STK", currency="USD", detail="LOT"):
    return (
        f'<OpenPosition accountId="U0000000" assetCategory="{category}" symbol="{symbol}" '
        f'listingExchange="{exchange}" currency="{currency}" position="{position}" '
        f'levelOfDetail="{detail}" costBasisPrice="1" markPrice="1" />'
    )


def _statement(*rows, section=True):
    body = f"<OpenPositions>{''.join(rows)}</OpenPositions>" if section else "<Trades />"
    return (
        '<FlexQueryResponse queryName="test" type="AF"><FlexStatements count="1">'
        '<FlexStatement accountId="U0000000" fromDate="20260101" toDate="20261117" period="YearToDate">'
        f"{body}</FlexStatement></FlexStatements></FlexQueryResponse>"
    ).encode()


SAMPLE_STATEMENT = _statement(
    _position("AAPL", "NASDAQ"),
    _position("AAPL", "NASDAQ", position="5"),  # second lot of the same holding
    _position("BRK B", "NYSE"),
    _position("QQQM", "NASDAQ"),
    _position("SAN", "BM", currency="EUR"),
    _position("AI", "SBF", currency="EUR"),
    _position("700", "SEHK", currency="HKD"),
    _position("7203", "TSEJ", currency="JPY"),
    _position("TSLA", "NASDAQ", position="-3"),  # short
    _position("MSFT", "NASDAQ", position="0"),
    _position("AAPL  261218C00250000", "CBOE", category="OPT"),
)


def _response(body: bytes, status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.content = body
    return response


def _send_ok(reference: str = "REF123") -> bytes:
    return (
        '<FlexStatementResponse timestamp="18 November, 2026 11:00 AM EST">'
        f"<Status>Success</Status><ReferenceCode>{reference}</ReferenceCode>"
        "<Url>https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement</Url>"
        "</FlexStatementResponse>"
    ).encode()


def _flex_error(code: str, message: str) -> bytes:
    return (
        '<FlexStatementResponse timestamp="18 November, 2026 11:00 AM EST">'
        f"<Status>Fail</Status><ErrorCode>{code}</ErrorCode><ErrorMessage>{message}</ErrorMessage>"
        "</FlexStatementResponse>"
    ).encode()


class IbkrFlexClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock()
        self.sleeps: list[float] = []

    def _download(self, **kwargs) -> bytes:
        return flex.download_flex_statement(
            TOKEN, "1712897", session=self.session, sleep=self.sleeps.append, **kwargs
        )

    def test_downloads_statement_after_generation_in_progress(self) -> None:
        self.session.get.side_effect = [
            _response(_send_ok()),
            _response(_flex_error("1019", "Statement generation in progress.")),
            _response(SAMPLE_STATEMENT),
        ]

        self.assertEqual(self._download(), SAMPLE_STATEMENT)

        send_call, first_poll, second_poll = self.session.get.call_args_list
        self.assertEqual(send_call.args[0], flex.FLEX_SEND_REQUEST_URL)
        self.assertEqual(send_call.kwargs["params"], {"t": TOKEN, "q": "1712897", "v": "3"})
        self.assertEqual(first_poll.args[0], flex.FLEX_GET_STATEMENT_URL)
        self.assertEqual(first_poll.kwargs["params"], {"t": TOKEN, "q": "REF123", "v": "3"})
        self.assertEqual(second_poll.kwargs["params"]["q"], "REF123")
        self.assertEqual(len(self.sleeps), 2)

    def test_passes_explicit_date_range(self) -> None:
        self.session.get.side_effect = [_response(_send_ok()), _response(SAMPLE_STATEMENT)]

        self._download(from_date="20250101", to_date="20251231")

        params = self.session.get.call_args_list[0].kwargs["params"]
        self.assertEqual((params["fd"], params["td"]), ("20250101", "20251231"))

    def test_retries_throttled_send_request(self) -> None:
        self.session.get.side_effect = [
            _response(_flex_error("1018", "Too many requests.")),
            _response(_send_ok()),
            _response(SAMPLE_STATEMENT),
        ]

        self.assertEqual(self._download(), SAMPLE_STATEMENT)
        self.assertEqual(self.sleeps[0], 10.0)

    def test_non_retryable_error_fails_without_retry(self) -> None:
        self.session.get.side_effect = [_response(_flex_error("1015", "Token is invalid."))]

        with self.assertRaisesRegex(IbkrPortfolioError, "1015"):
            self._download()
        self.assertEqual(self.session.get.call_count, 1)

    def test_gives_up_after_max_attempts(self) -> None:
        self.session.get.side_effect = [_response(_send_ok())] + [
            _response(_flex_error("1019", "Statement generation in progress.")) for _ in range(3)
        ]

        with self.assertRaisesRegex(IbkrPortfolioError, "1019"):
            self._download(max_attempts=3)

    def test_network_error_does_not_leak_token(self) -> None:
        self.session.get.side_effect = requests.ConnectionError(
            f"Max retries exceeded with url: /SendRequest?t={TOKEN}&q=1712897"
        )

        with self.assertRaises(IbkrPortfolioError) as ctx:
            self._download()
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)

    def test_http_error_status_fails(self) -> None:
        self.session.get.side_effect = [_response(b"", status=503)]

        with self.assertRaisesRegex(IbkrPortfolioError, "HTTP 503"):
            self._download()

    def test_rejects_invalid_arguments_before_network(self) -> None:
        cases = [
            {"query_id": "abc"},
            {"token": " "},
            {"from_date": "20250101"},
            {"from_date": "2025-01-01", "to_date": "2025-12-31"},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(IbkrPortfolioError):
                flex.download_flex_statement(
                    case.pop("token", TOKEN),
                    case.pop("query_id", "1712897"),
                    session=self.session,
                    sleep=self.sleeps.append,
                    **case,
                )
        self.session.get.assert_not_called()


class IbkrOpenPositionParserTest(unittest.TestCase):
    def test_keeps_supported_long_stock_holdings(self) -> None:
        codes, skipped = service.parse_open_position_codes(SAMPLE_STATEMENT)

        self.assertEqual(codes, ["AAPL", "BRK.B", "QQQM", "HK00700", "7203.T"])
        self.assertEqual(skipped, ["SAN@BM", "AI@SBF"])

    def test_merges_multiple_statements(self) -> None:
        one = _statement(_position("AAPL", "NASDAQ")).decode()
        two = _statement(_position("NVDA", "NASDAQ"), _position("AAPL", "NASDAQ")).decode()
        merged = one.replace(
            "</FlexStatements>",
            two[two.index("<FlexStatement "):two.index("</FlexStatements>")] + "</FlexStatements>",
        )

        codes, _ = service.parse_open_position_codes(merged.encode())

        self.assertEqual(codes, ["AAPL", "NVDA"])

    def test_empty_open_positions_section_returns_no_codes(self) -> None:
        self.assertEqual(service.parse_open_position_codes(_statement()), ([], []))

    def test_missing_open_positions_section_fails(self) -> None:
        with self.assertRaisesRegex(IbkrPortfolioError, "Open Positions"):
            service.parse_open_position_codes(_statement(section=False))

    def test_invalid_stock_rows_fail_the_whole_parse(self) -> None:
        cases = {
            "non-numeric position": _statement(_position("AAPL", "NASDAQ", position="abc")),
            "nan position": _statement(_position("AAPL", "NASDAQ", position="nan")),
            "missing symbol": _statement(_position("", "NASDAQ")),
            "not xml": b"<html>maintenance</html",
            "wrong root": b"<FlexStatementResponse />",
        }
        for name, body in cases.items():
            with self.subTest(name=name), self.assertRaises(IbkrPortfolioError):
                service.parse_open_position_codes(body)


class IbkrPortfolioLoaderTest(unittest.TestCase):
    def test_requires_token_and_query_id(self) -> None:
        for env in ({}, {"IBKR_FLEX_TOKEN": TOKEN}, {"IBKR_FLEX_QUERY_ID": "1712897"}):
            with self.subTest(env=sorted(env)), patch.dict(os.environ, env, clear=True), patch.object(
                service, "download_flex_statement"
            ) as download, self.assertRaisesRegex(IbkrPortfolioError, "IBKR_FLEX_TOKEN"):
                service.load_ibkr_stock_codes()
            download.assert_not_called()

    def test_loads_codes_from_configured_query(self) -> None:
        env = {"IBKR_FLEX_TOKEN": f" {TOKEN} ", "IBKR_FLEX_QUERY_ID": "1712897"}
        with patch.dict(os.environ, env, clear=True), patch.object(
            service, "download_flex_statement", return_value=SAMPLE_STATEMENT
        ) as download, self.assertLogs(service.logger, level="INFO") as captured:
            codes = service.load_ibkr_stock_codes()

        download.assert_called_once_with(TOKEN, "1712897")
        self.assertEqual(codes, ["AAPL", "BRK.B", "QQQM", "HK00700", "7203.T"])
        log_text = "\n".join(captured.output)
        self.assertIn("SAN@BM", log_text)
        self.assertNotIn(TOKEN, log_text)

    def test_broker_errors_share_one_base_class(self) -> None:
        self.assertTrue(issubclass(IbkrPortfolioError, BrokerPortfolioError))
        self.assertTrue(issubclass(FutuPortfolioError, BrokerPortfolioError))
        self.assertTrue(issubclass(BrokerPortfolioError, RuntimeError))


if __name__ == "__main__":
    unittest.main()
