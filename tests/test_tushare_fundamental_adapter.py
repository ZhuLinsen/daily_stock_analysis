# -*- coding: utf-8 -*-
"""Tests for the Tushare fundamental adapter and preferred-source wiring.

The A-share fundamental bundle used to be served exclusively by AkShare's
Eastmoney endpoints, which take ~15s per bundle and frequently exceed the stage
budget, leaving reports with a partial fundamental block. The Tushare adapter
mirrors the AkShare adapter's public surface so ``get_fundamental_context`` can
prefer Tushare (fast, paid) and fall back to AkShare.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_provider.tushare_fundamental_adapter import (
    TushareFundamentalAdapter,
    _normalize_code,
    _safe_float,
    _to_ts_code,
)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

class TestCodeHelpers:
    def test_normalize_code(self):
        assert _normalize_code("605090.SH") == "605090"
        assert _normalize_code("000001") == "000001"

    def test_to_ts_code_sh(self):
        assert _to_ts_code("605090") == "605090.SH"
        assert _to_ts_code("600519.SH") == "600519.SH"

    def test_to_ts_code_sz(self):
        assert _to_ts_code("000001") == "000001.SZ"
        assert _to_ts_code("300829.SZ") == "300829.SZ"

    def test_to_ts_code_invalid(self):
        assert _to_ts_code("") is None
        assert _to_ts_code("abc") is None

    def test_safe_float(self):
        assert _safe_float("12.5") == 12.5
        assert _safe_float(None) is None
        assert _safe_float("abc") is None


# ---------------------------------------------------------------------------
# adapter (mocked Tushare pro)
# ---------------------------------------------------------------------------

class TestTushareFundamentalAdapter:
    def _adapter(self, **query_results):
        adapter = TushareFundamentalAdapter()
        pro = MagicMock()

        def fake_query(api_name, **kwargs):
            if api_name in query_results:
                return query_results[api_name]
            return None

        pro.query.side_effect = fake_query
        adapter._pro = pro
        return adapter

    def test_bundle_full_success(self):
        fin = pd.DataFrame([
            {"ts_code": "605090.SH", "end_date": "20260331", "roe": 3.77,
             "grossprofit_margin": 8.1, "tr_yoy": 12.3, "netprofit_yoy": -5.2,
             "revenue": 1000.0, "profit_dedt": 200.0},
        ])
        basic = pd.DataFrame([
            {"ts_code": "605090.SH", "trade_date": "20260811", "pe_ttm": 16.92,
             "pb": 1.5, "total_mv": 50000.0, "circ_mv": 40000.0},
        ])
        holders = pd.DataFrame([
            {"ts_code": "605090.SH", "end_date": "20260331", "holder_name": "A",
             "hold_ratio": 28.4, "change_ratio": 0.5},
            {"ts_code": "605090.SH", "end_date": "20260331", "holder_name": "B",
             "hold_ratio": 9.2, "change_ratio": -0.1},
        ])
        div = pd.DataFrame([
            {"ts_code": "605090.SH", "end_date": "20251231", "cash_div": 0.5,
             "ex_date": "20260601", "div_proc": "实施"},
        ])
        adapter = self._adapter(
            fina_indicator=fin,
            daily_basic=basic,
            top10_holders=holders,
            dividend=div,
        )
        result = adapter.get_fundamental_bundle("605090")
        assert result["status"] == "partial"
        assert result["growth"]["roe"] == 3.77
        assert result["growth"]["revenue_yoy"] == 12.3
        assert result["valuation"]["pe_ratio"] == 16.92
        assert result["institution"]["top10_holder_count"] == 2
        assert result["earnings"]["dividend"]["events"][0]["cash_dividend_per_share"] == 0.5
        assert any("tushare" in s for s in result["source_chain"])

    def test_bundle_not_supported_when_no_token(self):
        adapter = TushareFundamentalAdapter()
        with patch.object(adapter, "_get_pro", return_value=None):
            result = adapter.get_fundamental_bundle("605090")
        assert result["status"] == "not_supported"

    def test_capital_flow(self):
        mf = pd.DataFrame([
            {"ts_code": "605090.SH", "trade_date": "20260811",
             "net_mf_amount": 12345.6, "net_mf_amount_ratio": 2.3},
        ])
        adapter = self._adapter(moneyflow=mf)
        result = adapter.get_capital_flow("605090")
        assert result["status"] == "partial"
        assert result["stock_flow"]["main_net_inflow"] == 12345.6

    def test_dragon_tiger_on_list(self):
        tl = pd.DataFrame([
            {"ts_code": "605090.SH", "trade_date": "20260810"},
        ])
        adapter = self._adapter(top_list=tl)
        result = adapter.get_dragon_tiger_flag("605090", lookback_days=20)
        assert result["status"] == "ok"
        assert result["is_on_list"] is True
        assert result["recent_count"] == 1

    def test_dragon_tiger_empty_window_is_ok(self):
        adapter = self._adapter(top_list=pd.DataFrame())
        result = adapter.get_dragon_tiger_flag("605090", lookback_days=20)
        assert result["status"] == "ok"
        assert result["is_on_list"] is False


# ---------------------------------------------------------------------------
# preferred-source wiring (Tushare first, AkShare fallback)
# ---------------------------------------------------------------------------

class TestPreferredWiring:
    def test_bundle_prefers_tushare(self):
        from data_provider.base import DataFetcherManager
        m = DataFetcherManager(fetchers=[])
        tushare = MagicMock()
        tushare.get_fundamental_bundle.return_value = {
            "status": "partial", "growth": {"roe": 3.77}, "earnings": {}, "valuation": {},
        }
        m._tushare_fundamental_adapter = tushare
        akshare = MagicMock()
        akshare.get_fundamental_bundle.return_value = {"status": "failed"}
        m._fundamental_adapter = akshare
        result = m._get_fundamental_bundle_preferred("605090")
        assert result["growth"]["roe"] == 3.77
        akshare.get_fundamental_bundle.assert_not_called()

    def test_bundle_falls_back_to_akshare_on_not_supported(self):
        from data_provider.base import DataFetcherManager
        m = DataFetcherManager(fetchers=[])
        tushare = MagicMock()
        tushare.get_fundamental_bundle.return_value = {"status": "not_supported"}
        m._tushare_fundamental_adapter = tushare
        akshare = MagicMock()
        akshare.get_fundamental_bundle.return_value = {"status": "partial", "growth": {"roe": 1.0}}
        m._fundamental_adapter = akshare
        result = m._get_fundamental_bundle_preferred("605090")
        assert result["status"] == "partial"
        akshare.get_fundamental_bundle.assert_called_once()

    def test_capital_flow_prefers_tushare(self):
        from data_provider.base import DataFetcherManager
        m = DataFetcherManager(fetchers=[])
        tushare = MagicMock()
        tushare.get_capital_flow.return_value = {"status": "partial", "stock_flow": {"main_net_inflow": 1.0}}
        m._tushare_fundamental_adapter = tushare
        akshare = MagicMock()
        m._fundamental_adapter = akshare
        result = m._get_capital_flow_preferred("605090")
        assert result["stock_flow"]["main_net_inflow"] == 1.0
        akshare.get_capital_flow.assert_not_called()

    def test_dragon_tiger_prefers_tushare(self):
        from data_provider.base import DataFetcherManager
        m = DataFetcherManager(fetchers=[])
        tushare = MagicMock()
        tushare.get_dragon_tiger_flag.return_value = {"status": "ok", "is_on_list": True}
        m._tushare_fundamental_adapter = tushare
        akshare = MagicMock()
        m._fundamental_adapter = akshare
        result = m._get_dragon_tiger_preferred("605090")
        assert result["is_on_list"] is True
        akshare.get_dragon_tiger_flag.assert_not_called()
