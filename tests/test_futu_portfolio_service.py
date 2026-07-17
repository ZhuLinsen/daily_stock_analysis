from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from src.brokers.futu import portfolio as service


class _TradeContext:
    def __init__(
        self,
        *,
        filter_trdmarket,
        host,
        port,
        security_firm,
        accounts=None,
        positions_by_account=None,
    ) -> None:
        self.closed = False
        self.position_queries = []
        self.accounts = accounts
        self.positions_by_account = positions_by_account
        self.open_arguments = {
            "filter_trdmarket": filter_trdmarket,
            "host": host,
            "port": port,
            "security_firm": security_firm,
        }

    def get_acc_list(self):
        if self.accounts is not None:
            return 0, pd.DataFrame(self.accounts)
        return 0, pd.DataFrame([
            {
                "acc_id": 1001,
                "trd_env": "REAL",
                "acc_role": "NORMAL",
                "acc_status": "ACTIVE",
                "security_firm": "FUTUSECURITIES",
            },
            {
                "acc_id": 2002,
                "trd_env": "SIMULATE",
                "acc_role": "NORMAL",
                "acc_status": "ACTIVE",
                "security_firm": "FUTUSECURITIES",
            },
        ])

    def position_list_query(self, **kwargs):
        self.position_queries.append(kwargs)
        if self.positions_by_account is not None:
            return 0, pd.DataFrame(
                self.positions_by_account.get(kwargs["acc_id"], [])
            )
        return 0, pd.DataFrame([
            {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
            {"code": "US.DRAM", "qty": 3, "position_side": "LONG"},
            {
                "code": "US.AAPL261218C200000",
                "qty": -1,
                "position_side": "LONG",
            },
            {"code": "HK.00700", "qty": 20, "position_side": "LONG"},
            {"code": "SH.600519", "qty": 0, "position_side": "LONG"},
            {"code": "JP.7203", "qty": 5, "position_side": "LONG"},
        ])

    def close(self) -> None:
        self.closed = True


class _QuoteContext:
    def __init__(self, *, host, port) -> None:
        self.closed = False
        self.open_arguments = {"host": host, "port": port}

    def get_stock_basicinfo(self, market, *, stock_type, code_list):
        stock_types = {
            "US.AAPL": "STOCK",
            "US.DRAM": "ETF",
            "US.AAPL261218C200000": "DRVT",
            "HK.00700": "STOCK",
            "JP.7203": "STOCK",
        }
        return 0, pd.DataFrame([
            {"code": code, "stock_type": stock_types[code]}
            for code in code_list
        ])

    def close(self) -> None:
        self.closed = True


def _fake_api(
    trade_contexts,
    quote_contexts,
    *,
    accounts=None,
    positions_by_account=None,
):
    def open_trade_context(*, filter_trdmarket, host, port, security_firm):
        context = _TradeContext(
            filter_trdmarket=filter_trdmarket,
            host=host,
            port=port,
            security_firm=security_firm,
            accounts=accounts,
            positions_by_account=positions_by_account,
        )
        trade_contexts.append(context)
        return context

    def open_quote_context(*, host, port):
        context = _QuoteContext(host=host, port=port)
        quote_contexts.append(context)
        return context

    return service._FutuApi(
        OpenQuoteContext=open_quote_context,
        OpenSecTradeContext=open_trade_context,
        Market=SimpleNamespace(US="US", HK="HK", SH="SH", SZ="SZ", JP="JP"),
        RET_OK=0,
        SecurityFirm=SimpleNamespace(
            NONE="N/A",
            FUTUSECURITIES="FUTUSECURITIES",
            FUTUSG="FUTUSG",
        ),
        SecurityType=SimpleNamespace(STOCK="STOCK"),
        TrdEnv=SimpleNamespace(REAL="REAL"),
        TrdMarket=SimpleNamespace(NONE="NONE"),
    )


def _account(
    acc_id,
    acc_role,
    *,
    acc_status="ACTIVE",
    security_firm="FUTUSECURITIES",
):
    return {
        "acc_id": acc_id,
        "trd_env": "REAL",
        "acc_role": acc_role,
        "acc_status": acc_status,
        "security_firm": security_firm,
    }


def _load_codes_for_accounts(accounts, positions_by_account):
    trade_contexts = []
    quote_contexts = []
    api = _fake_api(
        trade_contexts,
        quote_contexts,
        accounts=accounts,
        positions_by_account=positions_by_account,
    )
    with patch.dict(
        "os.environ",
        {},
        clear=True,
    ), patch.object(service, "_load_futu_api", return_value=api):
        result = service.load_futu_stock_codes()
    return result, trade_contexts


class FutuPortfolioServiceTest(unittest.TestCase):
    def test_sdk_initialization_failure_uses_portfolio_error_boundary(self):
        with patch(
            "builtins.__import__",
            side_effect=PermissionError("log directory denied"),
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "加载 Futu OpenAPI SDK 失败: log directory denied",
        ):
            service._load_futu_api()

    def test_load_futu_stock_codes_uses_real_accounts_and_keeps_only_stocks(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(trade_contexts, quote_contexts)

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(service, "_load_futu_api", return_value=api):
            result = service.load_futu_stock_codes()

        self.assertEqual(result, ["AAPL", "HK00700", "7203.T"])
        position_contexts = [ctx for ctx in trade_contexts if ctx.position_queries]
        self.assertEqual(len(position_contexts), 1)
        self.assertEqual(
            position_contexts[0].position_queries,
            [{"trd_env": "REAL", "acc_id": 1001, "refresh_cache": True}],
        )
        self.assertTrue(all(ctx.closed for ctx in trade_contexts))
        self.assertTrue(quote_contexts and all(ctx.closed for ctx in quote_contexts))

    def test_default_firm_uses_one_official_none_discovery_context(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(trade_contexts, quote_contexts)

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(service, "_load_futu_api", return_value=api):
            service.load_futu_stock_codes()

        self.assertEqual(
            [context.open_arguments for context in trade_contexts],
            [
                {
                    "filter_trdmarket": "NONE",
                    "host": "127.0.0.1",
                    "port": 11111,
                    "security_firm": "N/A",
                },
                {
                    "filter_trdmarket": "NONE",
                    "host": "127.0.0.1",
                    "port": 11111,
                    "security_firm": "FUTUSECURITIES",
                },
            ],
        )
        self.assertEqual(
            [context.open_arguments for context in quote_contexts],
            [{"host": "127.0.0.1", "port": 11111}],
        )

    def test_configured_security_firm_replaces_auto_detection(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[
                _account(
                    1001,
                    "NORMAL",
                    security_firm="FUTUSG",
                )
            ],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"}
                ]
            },
        )

        with patch.dict(
            "os.environ",
            {"FUTU_SECURITY_FIRM": "FUTUSG"},
            clear=True,
        ), patch.object(service, "_load_futu_api", return_value=api):
            result = service.load_futu_stock_codes()

        self.assertEqual(result, ["AAPL"])
        self.assertEqual(
            trade_contexts[0].open_arguments["security_firm"],
            "FUTUSG",
        )

    def test_unknown_security_firm_fails_before_opening_context(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(trade_contexts, quote_contexts)

        with patch.dict(
            "os.environ",
            {"FUTU_SECURITY_FIRM": "UNKNOWN"},
            clear=True,
        ), patch.object(service, "_load_futu_api", return_value=api), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "不支持的 FUTU_SECURITY_FIRM: UNKNOWN",
        ):
            service.load_futu_stock_codes()

        self.assertEqual(trade_contexts, [])
        self.assertEqual(quote_contexts, [])

    def test_account_discovery_failure_is_not_retried_or_partially_ignored(self):
        trade_contexts = []
        quote_contexts = []
        base_api = _fake_api(trade_contexts, quote_contexts)
        context = SimpleNamespace(
            get_acc_list=MagicMock(return_value=(1, "broker unavailable")),
            close=MagicMock(),
        )
        open_calls = []

        def open_trade_context(**kwargs):
            open_calls.append(kwargs)
            return context

        api = SimpleNamespace(**base_api.__dict__)
        api.OpenSecTradeContext = open_trade_context

        with patch.dict("os.environ", {}, clear=True), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "查询 Futu 真实账户失败: broker unavailable",
        ):
            service.load_futu_stock_codes()

        self.assertEqual(len(open_calls), 1)
        self.assertEqual(open_calls[0]["security_firm"], "N/A")
        context.close.assert_called_once_with()
        self.assertEqual(quote_contexts, [])

    def test_real_accounts_require_explicit_active_status(self):
        cases = {
            "missing": None,
            "n/a": "N/A",
            "unknown": "UNKNOWN",
            "disabled": "DISABLED",
        }
        for label, status in cases.items():
            with self.subTest(status=label):
                account = _account(1001, "NORMAL", acc_status=status)
                if label == "missing":
                    account.pop("acc_status")
                trade_contexts = []
                quote_contexts = []
                api = _fake_api(
                    trade_contexts,
                    quote_contexts,
                    accounts=[account],
                    positions_by_account={
                        1001: [
                            {
                                "code": "US.AAPL",
                                "qty": 10,
                                "position_side": "LONG",
                            }
                        ]
                    },
                )

                with patch.dict("os.environ", {}, clear=True), patch.object(
                    service,
                    "_load_futu_api",
                    return_value=api,
                ), self.assertRaisesRegex(
                    service.FutuPortfolioError,
                    "未找到状态为 ACTIVE",
                ):
                    service.load_futu_stock_codes()

                self.assertFalse(any(ctx.position_queries for ctx in trade_contexts))
                self.assertEqual(quote_contexts, [])

    def test_load_futu_stock_codes_keeps_read_only_master_account(self):
        result, trade_contexts = _load_codes_for_accounts(
            [_account(3003, "MASTER")],
            {
                3003: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"}
                ],
            },
        )

        self.assertEqual(result, ["AAPL"])
        position_contexts = [ctx for ctx in trade_contexts if ctx.position_queries]
        self.assertEqual(len(position_contexts), 1)
        self.assertEqual(position_contexts[0].position_queries[0]["acc_id"], 3003)

    def test_load_futu_stock_codes_merges_master_and_normal_accounts(self):
        result, trade_contexts = _load_codes_for_accounts(
            [_account(1001, "NORMAL"), _account(3003, "MASTER")],
            {
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"}
                ],
                3003: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "HK.00700", "qty": 20, "position_side": "LONG"},
                ],
            },
        )

        self.assertEqual(result, ["AAPL", "HK00700"])
        queried_account_ids = [
            context.position_queries[0]["acc_id"]
            for context in trade_contexts
            if context.position_queries
        ]
        self.assertEqual(queried_account_ids, [1001, 3003])

    def test_load_futu_stock_codes_skips_short_positions_before_deduplication(self):
        result, trade_contexts = _load_codes_for_accounts(
            [_account(1001, "NORMAL"), _account(3003, "MASTER")],
            {
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "SHORT"},
                    {"code": "HK.00700", "qty": 20, "position_side": "SHORT"},
                ],
                3003: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"}
                ],
            },
        )

        self.assertEqual(result, ["AAPL"])
        queried_account_ids = [
            context.position_queries[0]["acc_id"]
            for context in trade_contexts
            if context.position_queries
        ]
        self.assertEqual(queried_account_ids, [1001, 3003])

    def test_load_futu_stock_codes_skips_unknown_position_sides(self):
        result, _ = _load_codes_for_accounts(
            [_account(1001, "NORMAL")],
            {
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "N/A"},
                    {"code": "HK.00700", "qty": 20},
                    {"code": "JP.7203", "qty": 5, "position_side": "NONE"},
                ],
            },
        )

        self.assertEqual(result, [])

    def test_load_futu_stock_codes_skips_non_finite_quantities(self):
        result, _ = _load_codes_for_accounts(
            [_account(1001, "NORMAL")],
            {
                1001: [
                    {
                        "code": "US.AAPL",
                        "qty": float("nan"),
                        "position_side": "LONG",
                    }
                ],
            },
        )

        self.assertEqual(result, [])

    def test_load_futu_stock_codes_skips_malaysian_ipo_accounts(self):
        result, trade_contexts = _load_codes_for_accounts(
            [_account(1001, "NORMAL"), _account(4004, "IPO")],
            {
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"}
                ],
                4004: [
                    {"code": "HK.00700", "qty": 20, "position_side": "LONG"}
                ],
            },
        )

        self.assertEqual(result, ["AAPL"])
        queried_account_ids = [
            context.position_queries[0]["acc_id"]
            for context in trade_contexts
            if context.position_queries
        ]
        self.assertEqual(queried_account_ids, [1001])

    def test_invalid_futu_account_id_fails_before_position_query(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(trade_contexts, quote_contexts)

        with patch.dict(
            "os.environ",
            {
                "FUTU_SECURITY_FIRM": "FUTUSECURITIES",
                "FUTU_ACC_ID": "9999",
            },
            clear=True,
        ), patch.object(service, "_load_futu_api", return_value=api), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "FUTU_ACC_ID 未匹配",
        ):
            service.load_futu_stock_codes()

        self.assertFalse(any(ctx.position_queries for ctx in trade_contexts))

    def test_to_analysis_code(self):
        cases = [
            ("US.MSFT", "MSFT"),
            ("HK.01810", "HK01810"),
            ("SZ.000001", "000001"),
            ("JP.9984", "9984.T"),
            ("SG.D05", None),
        ]
        for futu_code, expected in cases:
            with self.subTest(futu_code=futu_code):
                self.assertEqual(service._to_analysis_code(futu_code), expected)

    def test_connection_settings_accepts_ipv4_and_hostnames(self):
        cases = {
            "default": (None, "127.0.0.1"),
            "explicit_ipv4": ("127.0.0.1", "127.0.0.1"),
            "remote_ipv4": ("192.168.1.10", "192.168.1.10"),
            "hostname": ("localhost", "localhost"),
            "remote_hostname": ("opend.internal", "opend.internal"),
            "padded": (" 127.0.0.1 ", "127.0.0.1"),
        }
        for label, (configured, expected_host) in cases.items():
            with self.subTest(host=label):
                env = {} if configured is None else {"FUTU_OPEND_HOST": configured}
                with patch.dict("os.environ", env, clear=True):
                    host, port = service._connection_settings()
                self.assertEqual(host, expected_host)
                self.assertEqual(port, 11111)

    def test_connection_settings_rejects_ipv6_literal(self):
        for host in ("::1", "[::1]", "2001:db8::1"):
            with self.subTest(host=host):
                with patch.dict(
                    "os.environ",
                    {"FUTU_OPEND_HOST": host},
                    clear=True,
                ), self.assertRaisesRegex(
                    service.FutuPortfolioError,
                    "网络层仅支持 IPv4",
                ):
                    service._connection_settings()


if __name__ == "__main__":
    unittest.main()
