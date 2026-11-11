# -*- coding: utf-8 -*-
"""
Issue #2420 r2：加拿大代码贯通公共校验/路由入口的回归测试

逐条对应 PR #2493 首评 blocker：
- OR-COR-f0d0e95a / OR-COR-fde50ca9: config_registry 值域缺 ca
- OR-COR-3681f2bb / OR-COR-86f7c03a: 日线/基本面/_market_tag/Stooq fallback
- OR-COR-9a7fa646: get_market_for_stock 个股交易日识别
- OR-COR-0a575f94: is_code_like/_normalize/API 正则/profile/backtest 公共入口
- OR-COM-bfe7c5f7: 小写 .v 的 US 身份在公共入口规范化后丢失

身份语义（所有入口一致）：``.TO`` 大小写不敏感为 TSX；原始大写 ``.V`` 为
TSXV；原始小写 ``.v`` 保持既有 US 语义，且规范形保留大小写
（``shop.v``，仿 ``csi930955`` 小写规范形先例），使下游逐层路由不再翻转为 ca。
"""
import sys
import os
from unittest.mock import MagicMock, patch

# Stub heavy dependencies before project imports（与 test_market_analyzer_generate_text.py 同法）
for _mod in ("litellm", "google.generativeai", "google.genai", "anthropic"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pytest


# ---------------------------------------------------------------------------
# OR-COR-f0d0e95a / fde50ca9: registry 值域
# ---------------------------------------------------------------------------
class TestRegistryAcceptsCa:
    """MARKET_REVIEW_REGION 注册表 options/allowed_values 必须包含 ca"""

    def test_registry_options_contain_ca(self):
        from src.core.config_registry import get_field_definition

        field = get_field_definition("MARKET_REVIEW_REGION")
        assert "ca" in field["options"]

    def test_registry_allowed_values_contain_ca(self):
        from src.core.config_registry import get_field_definition

        field = get_field_definition("MARKET_REVIEW_REGION")
        assert "ca" in field["validation"]["allowed_values"]

    def test_validate_value_accepts_single_ca(self):
        from src.core.config_registry import get_field_definition
        from src.services.system_config_service import SystemConfigService

        field_schema = get_field_definition("MARKET_REVIEW_REGION")
        issues = SystemConfigService._validate_value(
            key="MARKET_REVIEW_REGION", value="ca", field_schema=field_schema
        )
        assert issues == []

    def test_validate_value_accepts_comma_combo_cn_ca(self):
        from src.core.config_registry import get_field_definition
        from src.services.system_config_service import SystemConfigService

        field_schema = get_field_definition("MARKET_REVIEW_REGION")
        issues = SystemConfigService._validate_value(
            key="MARKET_REVIEW_REGION", value="cn,ca", field_schema=field_schema
        )
        assert issues == []

    def test_validate_value_still_rejects_unknown_token(self):
        from src.core.config_registry import get_field_definition
        from src.services.system_config_service import SystemConfigService

        field_schema = get_field_definition("MARKET_REVIEW_REGION")
        issues = SystemConfigService._validate_value(
            key="MARKET_REVIEW_REGION", value="cn,xx", field_schema=field_schema
        )
        assert issues, "未知 token 仍须被拒绝"
        assert any(issue["code"] == "invalid_allowed_value" for issue in issues)


# ---------------------------------------------------------------------------
# OR-COR-3681f2bb / 86f7c03a: 日线/基本面/_market_tag/Stooq fallback
# ---------------------------------------------------------------------------
class TestMarketTagAndDailyRouting:
    """_market_tag / 日线能力表 / 基本面分流须认识 ca"""

    def test_market_tag_shop_to_is_ca(self):
        from data_provider.base import _market_tag

        assert _market_tag("SHOP.TO") == "ca"

    def test_market_tag_shop_v_is_ca(self):
        from data_provider.base import _market_tag

        assert _market_tag("SHOP.V") == "ca"

    def test_market_tag_lowercase_v_is_us(self):
        from data_provider.base import _market_tag

        assert _market_tag("shop.v") == "us"

    def test_market_tag_existing_markets_unchanged(self):
        from data_provider.base import _market_tag

        assert _market_tag("600519") == "cn"
        assert _market_tag("7203.T") == "jp"
        assert _market_tag("005930.KS") == "kr"
        assert _market_tag("2330.TW") == "tw"
        assert _market_tag("AAPL") == "us"

    def test_non_cn_request_recognizes_ca(self):
        from data_provider.base import _is_non_cn_request

        assert _is_non_cn_request("SHOP.TO") is True
        assert _is_non_cn_request("SHOP.V") is True

    def test_daily_fetcher_support_table_includes_ca(self):
        from data_provider.base import DataFetcherManager

        supported = DataFetcherManager._DAILY_MARKET_FETCHER_SUPPORT["YfinanceFetcher"]
        assert "ca" in supported

    def test_daily_filter_keeps_yfinance_for_ca(self):
        from data_provider.base import DataFetcherManager

        yf_fetcher = MagicMock()
        yf_fetcher.name = "YfinanceFetcher"
        ak_fetcher = MagicMock()
        ak_fetcher.name = "AkshareFetcher"
        kept = DataFetcherManager._filter_daily_fetchers_for_market(
            [yf_fetcher, ak_fetcher], "ca"
        )
        assert [f.name for f in kept] == ["YfinanceFetcher"]

    def test_fundamental_context_reports_ca_market(self):
        """基本面管道关闭时 not-supported 上下文的 market 标签应为 ca（分流入口）"""
        from types import SimpleNamespace

        from data_provider.base import DataFetcherManager

        manager = DataFetcherManager()
        with patch("src.config.get_config", return_value=SimpleNamespace(
            enable_fundamental_pipeline=False
        )):
            ctx = manager.get_fundamental_context("SHOP.TO")
        assert ctx["market"] == "ca"

    def test_us_stock_code_still_matches_shop_v_shape(self):
        """``SHOP.V``/``shop.v`` 大写化后命中美股形态——路由去歧义靠原始大小写"""
        from data_provider.us_index_mapping import is_us_stock_code

        assert is_us_stock_code("SHOP.V") is True


class TestStooqFallbackExcludesCa:
    """CA 身份代码不得落入 Stooq 美股兜底（OR-COR-3681f2bb）"""

    def _make_fetcher(self):
        from data_provider.yfinance_fetcher import YfinanceFetcher

        return YfinanceFetcher()

    def test_ca_code_skips_stooq_on_empty_history(self):
        fetcher = self._make_fetcher()

        mock_ticker = MagicMock()
        mock_ticker.fast_info = None  # 触发回退到 history
        mock_ticker.history.return_value = __import__("pandas").DataFrame()
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            with patch.object(
                fetcher,
                "_get_us_stock_quote_from_stooq",
                side_effect=AssertionError("CA 代码不得请求 Stooq"),
            ) as stooq:
                quote = fetcher.get_realtime_quote("SHOP.V")

        assert quote is None
        stooq.assert_not_called()

    def test_ca_code_skips_stooq_on_exception(self):
        fetcher = self._make_fetcher()

        mock_ticker = MagicMock()
        mock_ticker.fast_info = MagicMock()
        type(mock_ticker).fast_info = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            with patch.object(
                fetcher,
                "_get_us_stock_quote_from_stooq",
                side_effect=AssertionError("CA 代码不得请求 Stooq"),
            ) as stooq:
                quote = fetcher.get_realtime_quote("SHOP.V")

        assert quote is None
        stooq.assert_not_called()

    def test_us_lowercase_v_keeps_stooq_fallback(self):
        """小写 .v 是 US 身份——Stooq 兜底语义保持既有不变"""
        fetcher = self._make_fetcher()

        mock_ticker = MagicMock()
        mock_ticker.fast_info = None
        mock_ticker.history.return_value = __import__("pandas").DataFrame()
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            with patch.object(
                fetcher,
                "_get_us_stock_quote_from_stooq",
                return_value=MagicMock(name="stooq-quote"),
            ) as stooq:
                quote = fetcher.get_realtime_quote("shop.v")

        assert quote is not None
        stooq.assert_called_once()


# ---------------------------------------------------------------------------
# OR-COR-9a7fa646: 个股交易日识别
# ---------------------------------------------------------------------------
class TestGetMarketForStockCa:
    """get_market_for_stock 必须把 .TO/大写 .V 识别为 ca（先于美股形态）"""

    def test_shop_to_is_ca(self):
        from src.core.trading_calendar import get_market_for_stock

        assert get_market_for_stock("SHOP.TO") == "ca"

    def test_shop_v_is_ca(self):
        from src.core.trading_calendar import get_market_for_stock

        assert get_market_for_stock("SHOP.V") == "ca"

    def test_lowercase_v_is_us(self):
        from src.core.trading_calendar import get_market_for_stock

        assert get_market_for_stock("shop.v") == "us"

    def test_existing_markets_unchanged(self):
        from src.core.trading_calendar import get_market_for_stock

        assert get_market_for_stock("7203.T") == "jp"
        assert get_market_for_stock("005930.KS") == "kr"
        assert get_market_for_stock("AAPL") == "us"
        assert get_market_for_stock("600519") == "cn"


# ---------------------------------------------------------------------------
# OR-COR-0a575f94: 公共校验与身份解析入口
# ---------------------------------------------------------------------------
class TestPublicEntrancesAcceptCa:
    """is_code_like / _normalize_code_and_exchange / API 正则 / profile / backtest"""

    def test_is_code_like_ca_forms(self):
        from src.services.stock_code_utils import is_code_like

        assert is_code_like("SHOP.TO") is True
        assert is_code_like("shop.to") is True
        assert is_code_like("SHOP.V") is True

    def test_normalize_code_and_exchange_ca(self):
        from src.services.stock_code_utils import _normalize_code_and_exchange

        assert _normalize_code_and_exchange("SHOP.TO") == ("SHOP.TO", "TO")
        assert _normalize_code_and_exchange("shop.to") == ("SHOP.TO", "TO")
        assert _normalize_code_and_exchange("SHOP.V") == ("SHOP.V", "")
        # 小写 .v：规范形保留大小写，身份不变
        assert _normalize_code_and_exchange("shop.v") == ("shop.v", "")

    def test_normalize_code_and_exchange_existing_forms_unchanged(self):
        from src.services.stock_code_utils import _normalize_code_and_exchange

        assert _normalize_code_and_exchange("7203.T") == ("7203.T", "T")
        assert _normalize_code_and_exchange("005930.KS") == ("005930.KS", "KS")
        assert _normalize_code_and_exchange("AAPL") == ("AAPL", "")
        assert _normalize_code_and_exchange("BRK.B") == ("BRK.B", "")

    def test_resolve_daily_stock_identity_ca(self):
        from src.services.stock_code_utils import resolve_daily_stock_identity

        identity = resolve_daily_stock_identity("SHOP.TO")
        assert identity is not None
        assert identity.market == "ca"
        assert identity.normalized_code == "SHOP.TO"

    def test_resolve_daily_stock_identity_shop_v_is_ca(self):
        from src.services.stock_code_utils import resolve_daily_stock_identity

        identity = resolve_daily_stock_identity("SHOP.V")
        assert identity is not None
        assert identity.market == "ca"

    def test_resolve_daily_stock_identity_lowercase_v_is_us(self):
        from src.services.stock_code_utils import resolve_daily_stock_identity

        identity = resolve_daily_stock_identity("shop.v")
        assert identity is not None
        assert identity.market == "us"
        assert identity.normalized_code == "shop.v"

    def test_canonical_stock_code_preserves_lowercase_v(self):
        from data_provider.base import canonical_stock_code

        assert canonical_stock_code("shop.v") == "shop.v"
        assert canonical_stock_code("SHOP.V") == "SHOP.V"
        assert canonical_stock_code("aapl") == "AAPL"
        assert canonical_stock_code("7203.t") == "7203.T"

    def test_stocks_api_regex_accepts_ca(self):
        from api.v1.endpoints.stocks import _STOCK_CODE_RE

        assert _STOCK_CODE_RE.match("SHOP.TO")
        assert _STOCK_CODE_RE.match("shop.to")
        assert _STOCK_CODE_RE.match("SHOP.V")
        assert not _STOCK_CODE_RE.match("7203.TO"), "数字 base 的 .TO 不是 TSX ticker"

    def test_resolve_index_stock_code_for_analysis_keeps_ca(self):
        from src.services.stock_code_utils import resolve_index_stock_code_for_analysis

        assert resolve_index_stock_code_for_analysis("SHOP.TO") == "SHOP.TO"
        assert resolve_index_stock_code_for_analysis("shop.to") == "SHOP.TO"
        assert resolve_index_stock_code_for_analysis("shop.v") == "shop.v"

    def test_stock_profile_canonicalize_code_ca(self):
        from src.services.stock_profile_service import StockProfileService

        assert StockProfileService.canonicalize_code("SHOP.TO") == "SHOP.TO"
        assert StockProfileService.market_for_code("SHOP.TO") == "ca"

    def test_backtest_normalize_code_ca(self):
        from src.services.backtest_service import BacktestService

        assert BacktestService._normalize_code("SHOP.TO") == "SHOP.TO"
        assert BacktestService._normalize_code("SHOP.V") == "SHOP.V"

    def test_analysis_input_resolution_routes_ca_code(self):
        """分析 API 入口：SHOP.TO 走代码解析（不再落入名称解析）"""
        from api.v1.endpoints.analysis import _resolve_analysis_input

        code, target = _resolve_analysis_input("SHOP.TO")
        assert code == "SHOP.TO"
        assert "贵州茅台" not in code and "name" not in code.lower()

    def test_analysis_input_resolution_preserves_lowercase_v_identity(self):
        """OR-COM-bfe7c5f7：shop.v 经 API 入口后仍是 US 身份（不再翻转为 ca）"""
        from api.v1.endpoints.analysis import _resolve_analysis_input
        from data_provider.base import _is_ca_market

        code, _target = _resolve_analysis_input("shop.v")
        assert code == "shop.v"
        assert _is_ca_market(code) is False


# ---------------------------------------------------------------------------
# PR #2493 复审 #2（OR-COM-bfe7c5f7 重开）：Web/自选入口的大写化再次抹掉
# 小写 .v 身份。评审场景 = shop.v 与 SHOP.V 必须可在自选共存且移除精确命中。
# ---------------------------------------------------------------------------
class TestWatchlistCaseSensitiveIdentity:
    """自选匹配键对 .V/.v 族大小写敏感；其余代码维持现行为"""

    def test_match_key_preserves_v_suffix_case(self):
        from api.v1.endpoints.stocks import _watchlist_match_key

        assert _watchlist_match_key("shop.v") == "shop.v"
        assert _watchlist_match_key("SHOP.V") == "SHOP.V"
        assert _watchlist_match_key("Shop.v") == "Shop.v"

    def test_match_key_distinguishes_the_two_identities(self):
        from api.v1.endpoints.stocks import _watchlist_match_key

        assert _watchlist_match_key("shop.v") != _watchlist_match_key("SHOP.V"), (
            "shop.v（美股）与 SHOP.V（TSXV）必须是两个身份，否则无法共存"
        )

    def test_match_key_other_codes_unchanged(self):
        from api.v1.endpoints.stocks import _watchlist_match_key

        assert _watchlist_match_key("AAPL") == "AAPL"
        assert _watchlist_match_key("aapl") == "AAPL"
        assert _watchlist_match_key("600519.SH") == "600519"
        assert _watchlist_match_key("hk00700") == "HK00700"
        assert _watchlist_match_key("00700") == "HK00700"
        assert _watchlist_match_key("7203.T") == "7203.T"


class _FakeWatchlistConfigService:
    """仅实现 watchlist 端点用到的 get_config/update 两个面。"""

    def __init__(self, seed):
        self._codes = list(seed)

    def get_config(self, include_schema=False):
        return {
            "config_version": "v-test",
            "items": [{"key": "STOCK_LIST", "value": ",".join(self._codes)}],
        }

    def update(self, config_version, items, mask_token, reload_now):
        for item in items:
            if item.get("key") == "STOCK_LIST":
                self._codes = [c for c in str(item.get("value", "")).split(",") if c]
        return {"updated_keys": [item.get("key") for item in items]}


def _make_watchlist_client(seed):
    """Return (TestClient, fake_service) with the config-service dependency overridden."""
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.deps import get_system_config_service

    fake = _FakeWatchlistConfigService(seed)
    app = create_app(static_dir=None)
    app.dependency_overrides[get_system_config_service] = lambda: fake
    return TestClient(app), fake


class TestWatchlistEndpointsCoexistence:
    """端点层：shop.v 与 SHOP.V 共存、移除精确命中（评审场景②）"""

    def test_remove_shop_v_keeps_shop_v_upper(self):
        client, fake = _make_watchlist_client(["AAPL", "shop.v", "SHOP.V"])
        resp = client.post("/api/v1/stocks/watchlist/remove", json={"stock_code": "shop.v"})
        assert resp.status_code == 200, resp.text
        assert fake._codes == ["AAPL", "SHOP.V"], "remove shop.v 必须精确移除 shop.v、保留 SHOP.V"

    def test_remove_shop_v_upper_keeps_lowercase(self):
        client, fake = _make_watchlist_client(["shop.v", "SHOP.V"])
        resp = client.post("/api/v1/stocks/watchlist/remove", json={"stock_code": "SHOP.V"})
        assert resp.status_code == 200, resp.text
        assert fake._codes == ["shop.v"], "remove SHOP.V 必须精确移除 SHOP.V、保留 shop.v"

    def test_add_lowercase_v_coexists_with_upper(self):
        client, fake = _make_watchlist_client(["SHOP.V"])
        resp = client.post("/api/v1/stocks/watchlist/add", json={"stock_code": "shop.v"})
        assert resp.status_code == 200, resp.text
        assert fake._codes == ["SHOP.V", "shop.v"], "add shop.v 须与既有 SHOP.V 共存为两个条目"

    def test_add_same_form_still_dedupes(self):
        client, fake = _make_watchlist_client(["shop.v"])
        resp = client.post("/api/v1/stocks/watchlist/add", json={"stock_code": "shop.v"})
        assert resp.status_code == 200, resp.text
        assert fake._codes == ["shop.v"], "同形态重复 add 仍按原语义去重"


if __name__ == "__main__":
    pytest.main([__file__])
