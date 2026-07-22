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
            {"code": "SZ.000001", "qty": 8, "position_side": "LONG"},
        ])

    def close(self) -> None:
        self.closed = True


class _QuoteContext:
    def __init__(self, *, host, port, stock_types=None) -> None:
        self.closed = False
        self.open_arguments = {"host": host, "port": port}
        self.stock_types = {
            "US.AAPL": "STOCK",
            "US.DRAM": "ETF",
            "US.AAPL261218C200000": "DRVT",
            "HK.00700": "STOCK",
            "SZ.000001": "STOCK",
            "JP.7203": "STOCK",
            "JP.130A": "STOCK",
        } if stock_types is None else stock_types

    def get_stock_basicinfo(self, market, *, stock_type, code_list):
        return 0, pd.DataFrame([
            {"code": code, "stock_type": self.stock_types[code]}
            for code in code_list
            if code in self.stock_types
        ])

    def close(self) -> None:
        self.closed = True


def _fake_api(
    trade_contexts,
    quote_contexts,
    *,
    accounts=None,
    positions_by_account=None,
    stock_types=None,
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
        context = _QuoteContext(host=host, port=port, stock_types=stock_types)
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
    def test_missing_sdk_uses_actionable_install_error(self):
        with patch(
            "builtins.__import__",
            side_effect=ImportError("No module named 'futu'"),
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "未安装 Futu OpenAPI SDK",
        ) as raised:
            service._load_futu_api()

        self.assertIn('pip install "futu-api==10.8.6808"', str(raised.exception))

    def test_sdk_initialization_failure_uses_portfolio_error_boundary(self):
        with patch(
            "builtins.__import__",
            side_effect=PermissionError("log directory denied"),
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "加载 Futu OpenAPI SDK 失败: log directory denied",
        ):
            service._load_futu_api()

    def test_load_futu_stock_codes_keeps_only_supported_a_hk_us_stocks(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(trade_contexts, quote_contexts)

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(service, "_load_futu_api", return_value=api):
            result = service.load_futu_stock_codes()

        self.assertEqual(result, ["AAPL", "HK00700", "000001"])
        position_contexts = [ctx for ctx in trade_contexts if ctx.position_queries]
        self.assertEqual(len(position_contexts), 1)
        self.assertEqual(
            position_contexts[0].position_queries,
            [{"trd_env": "REAL", "acc_id": 1001, "refresh_cache": True}],
        )
        self.assertTrue(all(ctx.closed for ctx in trade_contexts))
        self.assertTrue(quote_contexts and all(ctx.closed for ctx in quote_contexts))

    def test_load_futu_stock_codes_reports_unsupported_jp_holdings(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "JP.7203", "qty": 5, "position_side": "LONG"},
                    {"code": "JP.130A", "qty": 3, "position_side": "LONG"},
                ]
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertLogs(service.logger, level="WARNING") as captured:
            result = service.load_futu_stock_codes()

        self.assertEqual(result, [])
        warning_text = "\n".join(captured.output)
        self.assertIn("JP.7203", warning_text)
        self.assertIn("JP.130A", warning_text)

    def test_load_futu_stock_codes_keeps_supported_holdings_when_jp_is_present(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "JP.7203", "qty": 5, "position_side": "LONG"},
                ]
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertLogs(service.logger, level="WARNING") as captured:
            result = service.load_futu_stock_codes()

        self.assertEqual(result, ["AAPL"])
        self.assertIn("JP.7203", "\n".join(captured.output))

    def test_load_futu_stock_codes_rejects_stock_code_outside_analysis_contract(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "HK.BAD", "qty": 3, "position_side": "LONG"},
                ]
            },
            stock_types={"HK.BAD": "STOCK"},
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "无法转换.*HK.BAD",
        ):
            service.load_futu_stock_codes()

    def test_load_futu_stock_codes_reports_unsupported_b_shares(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "SH.900901", "qty": 5, "position_side": "LONG"},
                    {"code": "SZ.200012", "qty": 8, "position_side": "LONG"},
                ]
            },
            stock_types={
                "US.AAPL": "STOCK",
                "SH.900901": "STOCK",
                "SZ.200012": "STOCK",
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertLogs(
            service.logger,
            level="WARNING",
        ) as captured:
            result = service.load_futu_stock_codes()

        self.assertEqual(result, ["AAPL"])
        warning_text = "\n".join(captured.output)
        self.assertIn("SH.900901", warning_text)
        self.assertIn("SZ.200012", warning_text)

    def test_load_futu_stock_codes_rejects_partial_static_info_response(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "US.MSFT", "qty": 4, "position_side": "LONG"},
                ]
            },
            stock_types={"US.AAPL": "STOCK"},
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "无法确认证券类型.*US.MSFT",
        ):
            service.load_futu_stock_codes()

    def test_load_futu_stock_codes_rejects_unknown_static_security_type(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "US.MSFT", "qty": 4, "position_side": "LONG"},
                ]
            },
            stock_types={"US.AAPL": "STOCK", "US.MSFT": "N/A"},
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "无法确认证券类型.*US.MSFT",
        ):
            service.load_futu_stock_codes()

    def test_load_futu_stock_codes_rejects_invalid_eligible_account_id(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[
                _account("invalid", "NORMAL"),
                _account(1001, "NORMAL"),
            ],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                ]
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "账户查询返回了无效账户 ID",
        ):
            service.load_futu_stock_codes()

        self.assertFalse(any(ctx.position_queries for ctx in trade_contexts))
        self.assertEqual(quote_contexts, [])

    def test_load_futu_stock_codes_rejects_nonpositive_or_fractional_account_id(self):
        for invalid_acc_id in (0, -1, 1001.5, True):
            with self.subTest(acc_id=invalid_acc_id):
                trade_contexts = []
                quote_contexts = []
                api = _fake_api(
                    trade_contexts,
                    quote_contexts,
                    accounts=[
                        _account(invalid_acc_id, "NORMAL"),
                        _account(1001, "NORMAL"),
                    ],
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

                with patch.dict(
                    "os.environ",
                    {},
                    clear=True,
                ), patch.object(
                    service,
                    "_load_futu_api",
                    return_value=api,
                ), self.assertRaisesRegex(
                    service.FutuPortfolioError,
                    "账户查询返回了无效账户 ID",
                ):
                    service.load_futu_stock_codes()

                self.assertFalse(any(ctx.position_queries for ctx in trade_contexts))
                self.assertEqual(quote_contexts, [])

    def test_load_futu_stock_codes_rejects_invalid_position_quantity(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "US.MSFT", "qty": "bad", "position_side": "LONG"},
                ]
            },
            stock_types={
                "US.AAPL": "STOCK",
                "US.MSFT": "STOCK",
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "持仓数量无效.*US.MSFT",
        ):
            service.load_futu_stock_codes()

        self.assertEqual(quote_contexts, [])

    def test_load_futu_stock_codes_rejects_blank_nonzero_position_code(self):
        trade_contexts = []
        quote_contexts = []
        api = _fake_api(
            trade_contexts,
            quote_contexts,
            accounts=[_account(1001, "NORMAL")],
            positions_by_account={
                1001: [
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                    {"code": "", "qty": 5, "position_side": "LONG"},
                ]
            },
        )

        with patch.dict(
            "os.environ",
            {},
            clear=True,
        ), patch.object(
            service,
            "_load_futu_api",
            return_value=api,
        ), self.assertRaisesRegex(
            service.FutuPortfolioError,
            "非零持仓返回了空证券代码",
        ):
            service.load_futu_stock_codes()

        self.assertEqual(quote_contexts, [])

    def test_load_futu_stock_codes_rejects_missing_nonzero_long_code(self):
        with self.assertRaisesRegex(
            service.FutuPortfolioError,
            "非零持仓返回了无效证券代码",
        ):
            _load_codes_for_accounts(
                [_account(1001, "NORMAL")],
                {
                    1001: [
                        {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                        {"qty": 5, "position_side": "LONG"},
                    ]
                },
            )

    def test_load_futu_stock_codes_rejects_unqualified_nonzero_long_code(self):
        with self.assertRaisesRegex(
            service.FutuPortfolioError,
            "非零持仓返回了无效证券代码",
        ):
            _load_codes_for_accounts(
                [_account(1001, "NORMAL")],
                {
                    1001: [
                        {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                        {"code": "AAPL", "qty": 5, "position_side": "LONG"},
                    ]
                },
            )

    def test_load_futu_stock_codes_rejects_non_string_nonzero_long_codes(self):
        for invalid_code in (True, 123, b"US.AAPL"):
            with self.subTest(code=invalid_code), self.assertRaisesRegex(
                service.FutuPortfolioError,
                "非零持仓返回了无效证券代码",
            ):
                _load_codes_for_accounts(
                    [_account(1001, "NORMAL")],
                    {
                        1001: [
                            {
                                "code": "US.AAPL",
                                "qty": 10,
                                "position_side": "LONG",
                            },
                            {
                                "code": invalid_code,
                                "qty": 5,
                                "position_side": "LONG",
                            },
                        ]
                    },
                )

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

    def test_configured_account_id_must_be_a_positive_integer(self):
        for configured_acc_id in ("0", "-1", "1.5"):
            with self.subTest(acc_id=configured_acc_id):
                trade_contexts = []
                quote_contexts = []
                api = _fake_api(trade_contexts, quote_contexts)

                with patch.dict(
                    "os.environ",
                    {"FUTU_ACC_ID": configured_acc_id},
                    clear=True,
                ), patch.object(
                    service,
                    "_load_futu_api",
                    return_value=api,
                ), self.assertRaisesRegex(
                    service.FutuPortfolioError,
                    "FUTU_ACC_ID 必须是正整数账户 ID",
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

    def test_load_futu_stock_codes_keeps_active_master_account(self):
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

    def test_load_futu_stock_codes_skips_non_long_before_validating_fields(self):
        result, _ = _load_codes_for_accounts(
            [_account(1001, "NORMAL")],
            {
                1001: [
                    {"qty": "bad", "position_side": "SHORT"},
                    {"qty": None, "position_side": "N/A"},
                    {"code": "US.AAPL", "qty": 10, "position_side": "LONG"},
                ]
            },
        )

        self.assertEqual(result, ["AAPL"])

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

    def test_load_futu_stock_codes_rejects_non_finite_or_missing_quantities(self):
        for quantity in (float("nan"), float("inf"), float("-inf"), None, True):
            with self.subTest(quantity=quantity), self.assertRaisesRegex(
                service.FutuPortfolioError,
                "持仓数量无效.*US.AAPL",
            ):
                _load_codes_for_accounts(
                    [_account(1001, "NORMAL")],
                    {
                        1001: [
                            {
                                "code": "US.AAPL",
                                "qty": quantity,
                                "position_side": "LONG",
                            }
                        ],
                    },
                )

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
            ("US.BRK.B", "BRK.B"),
            ("HK.01810", "HK01810"),
            ("HK.700", "HK00700"),
            ("SZ.000001", "000001"),
            ("SH.600519", "600519"),
            ("HK.123456", None),
            ("HK.BAD", None),
            ("SH.1", None),
            ("SZ.1234567", None),
            ("US.AAICPRC", None),
            ("US.SPX", None),
            ("JP.9984", None),
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
