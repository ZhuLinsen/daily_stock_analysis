# -*- coding: utf-8 -*-
"""Regression tests for Canada (TSX/TSX-V) suffix-only market support.

Mirrors tests/test_tw_market_support.py. Canadian common stocks use Yahoo Finance
suffix forms ``SYM.TO`` (TSX) and ``SYM.V`` (TSX Venture). The base is alphabetic
(optionally hyphenated, e.g. ``BAM-A.TO``); the ``.TO``/``.V`` check must precede
the US branch in every detector. Bare codes are unaffected.
"""

from unittest.mock import patch

import pandas as pd
import pytest
from data_provider.base import BaseFetcher, DataFetchError, DataFetcherManager, normalize_stock_code
from data_provider.yfinance_fetcher import YfinanceFetcher
from src.core.trading_calendar import MARKET_EXCHANGE, MARKET_TIMEZONE, get_market_for_stock
from src.market_context import detect_market, get_market_guidelines, get_market_role
from src.services.stock_code_utils import is_code_like, normalize_code


def test_normalize_and_detect_ca_suffix_codes() -> None:
    assert normalize_stock_code("td.to") == "TD.TO"
    assert normalize_stock_code("shop.to") == "SHOP.TO"
    assert normalize_stock_code("bam-a.to") == "BAM-A.TO"
    assert normalize_stock_code("abc.v") == "ABC.V"

    for code in ("TD.TO", "SHOP.TO", "ENB.TO", "BAM-A.TO", "ABC.V"):
        assert detect_market(code) == "ca", code
    assert detect_market("AAPL") == "us"
    assert detect_market("600519") == "cn"

    assert get_market_for_stock("TD.TO") == "ca"
    assert get_market_for_stock("ABC.V") == "ca"   # .V also collides with US single-letter suffix
    assert get_market_for_stock("AAPL") == "us"


def test_ca_code_utils_accept_and_preserve() -> None:
    assert is_code_like("TD.TO") is True
    assert is_code_like("BAM-A.TO") is True
    assert is_code_like("ABC.V") is True
    assert normalize_code("td.to") == "TD.TO"
    assert normalize_code("bam-a.to") == "BAM-A.TO"
    assert normalize_code("abc.v") == "ABC.V"
    # Invalid shapes are rejected.
    assert normalize_code("TD.TX") != "TD.TX"  # unknown suffix -> not preserved as ca
    assert is_code_like(".TO") is False


def test_trading_calendar_registers_ca_exchange_and_timezone() -> None:
    assert MARKET_EXCHANGE["ca"] == "XTSE"
    assert MARKET_TIMEZONE["ca"] == "America/Toronto"


def test_market_role_and_guidelines_for_ca_bilingual() -> None:
    assert get_market_role("TD.TO", "zh") == "加拿大股"
    assert get_market_role("TD.TO", "en") == "Canadian (TSX) stock"

    zh = get_market_guidelines("TD.TO", "zh")
    assert "加拿大" in zh and "加元" in zh
    assert "北向资金" in zh and "龙虎榜" in zh   # named in the A-share-exclusion clause

    en = get_market_guidelines("TD.TO", "en")
    assert "Canad" in en and ("CAD" in en or "Canadian dollar" in en)


class _FakeFetcher(BaseFetcher):
    def __init__(self, name: str, should_fail: bool = False):
        self.name = name
        self.priority = 0 if name != "YfinanceFetcher" else 4
        self.calls = []
        self.should_fail = should_fail

    def _fetch_raw_data(self, stock_code, start_date, end_date):
        raise NotImplementedError

    def _normalize_data(self, df, stock_code):
        raise NotImplementedError

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        self.calls.append(stock_code)
        if self.should_fail:
            raise DataFetchError(f"{self.name} should not be called for {stock_code}")
        return pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-06-23")],
                "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0],
                "volume": [100], "amount": [100.0], "pct_chg": [0.0],
            }
        )


def test_yfinance_keeps_ca_suffix_codes() -> None:
    fetcher = YfinanceFetcher()
    assert fetcher._convert_stock_code("TD.TO") == "TD.TO"
    assert fetcher._convert_stock_code("ABC.V") == "ABC.V"


def test_market_tag_classifies_ca() -> None:
    from data_provider.base import _market_tag
    assert _market_tag("TD.TO") == "ca"
    assert _market_tag("ABC.V") == "ca"
    assert _market_tag("AAPL") == "us"


def test_ca_trust_unit_canonical_form_is_ca() -> None:
    """Canonical trust/REIT 'unit' form `BASE-UN.TO` is recognized as ca (hyphenated base).

    The bare `.UN` broker shorthand (e.g. `VITL.UN` -> `VITL-UN.TO`) is a deferred
    follow-up; for now use the Yahoo `-UN.TO` form.
    """
    from data_provider.base import _market_tag

    assert detect_market("REI-UN.TO") == "ca"
    assert get_market_for_stock("REI-UN.TO") == "ca"
    assert _market_tag("REI-UN.TO") == "ca"
    assert normalize_stock_code("rei-un.to") == "REI-UN.TO"
    assert normalize_code("rei-un.to") == "REI-UN.TO"
    assert YfinanceFetcher()._convert_stock_code("REI-UN.TO") == "REI-UN.TO"


def test_data_fetcher_manager_routes_ca_daily_only_to_yfinance() -> None:
    efinance = _FakeFetcher("EfinanceFetcher", should_fail=True)
    akshare = _FakeFetcher("AkshareFetcher", should_fail=True)
    yfinance = _FakeFetcher("YfinanceFetcher")
    manager = DataFetcherManager(fetchers=[efinance, akshare, yfinance])
    with patch("data_provider.base.record_provider_run_started"), patch("data_provider.base.record_provider_run"):
        ca_df, ca_source = manager.get_daily_data("TD.TO")
    assert ca_source == "YfinanceFetcher"
    assert not ca_df.empty
    assert efinance.calls == [] and akshare.calls == []
    assert yfinance.calls == ["TD.TO"]


def test_ca_fundamentals_use_offshore_path() -> None:
    """`ca` fundamentals must take the offshore branch (yfinance), not the A-share path."""
    manager = DataFetcherManager(fetchers=[YfinanceFetcher()])
    with patch.object(manager, "_build_offshore_fundamental_context", return_value={"market": "ca", "ok": True}) as off:
        result = manager.get_fundamental_context("TD.TO")
    off.assert_called_once()
    called_market = off.call_args.kwargs.get("market")
    if called_market is None and len(off.call_args.args) > 1:
        called_market = off.call_args.args[1]
    assert called_market == "ca"
    assert result == {"market": "ca", "ok": True}


@pytest.mark.parametrize("code,is_ca", [
    ("TD.TO", True), ("BAM-A.TO", True), ("ABC.V", True), ("XIU.TO", True),
    ("REI-UN.TO", True),  # canonical trust-unit form
    (".TO", False), ("FOO..TO", False), ("TOOLONGSYMBOLX.TO", False),
    ("TD.TX", False), ("AAPL", False), ("600519", False),
])
def test_ca_symbol_recognition_consistent_across_entries(code, is_ca) -> None:
    """Every detector/normalizer agrees on what is a Canadian symbol (no base-vs-suffix drift)."""
    from data_provider.base import _is_ca_market
    assert (detect_market(code) == "ca") is is_ca
    assert (get_market_for_stock(code) == "ca") is is_ca
    assert _is_ca_market(code) is is_ca
    assert YfinanceFetcher._is_ca_suffix_stock(code) is is_ca
    if is_ca:
        assert is_code_like(code) is True
        assert normalize_code(code) == code
        assert normalize_stock_code(code) == code


def test_ca_is_first_class_on_write_paths() -> None:
    from src.services.decision_signal_service import DecisionSignalService
    from src.services.portfolio_service import VALID_MARKETS
    from src.services.intelligence_service import _ALLOWED_MARKETS

    assert get_market_for_stock("TD.TO") == "ca"
    assert DecisionSignalService._normalize_market("ca") == "ca"
    assert "ca" in VALID_MARKETS and "ca" in _ALLOWED_MARKETS


def test_ca_accepted_by_portfolio_api_schema() -> None:
    """Pydantic Literal must accept market='ca' (not just Python sets)."""
    from api.v1.schemas.portfolio import PortfolioAccountCreateRequest
    model = PortfolioAccountCreateRequest(name="RRSP", market="ca", base_currency="CAD")
    assert model.market == "ca"
