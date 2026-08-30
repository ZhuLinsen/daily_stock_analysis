import logging
from typing import cast
from unittest.mock import patch

import pandas as pd
import pytest

from data_provider.base import (
    BaseFetcher,
    DataFetchError,
    DataFetcherManager,
    STANDARD_COLUMNS,
)
from src.services.stock_list_parser import (
    AnalysisTarget,
    IndexEntry,
    ParseStatus,
    parse_analysis_target,
)


def _daily_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-08-21")],
            "open": [100.0],
            "high": [102.0],
            "low": [99.0],
            "close": [101.0],
            "volume": [1000],
            "amount": [101000.0],
            "pct_chg": [1.0],
        }
    )


class _FakeFetcher(BaseFetcher):
    def __init__(
        self,
        name: str,
        *,
        priority: int,
        daily_result=None,
        name_result=None,
        available: bool = True,
    ) -> None:
        self.name = name
        self.priority = priority
        self.daily_result = daily_result
        self.name_result = name_result
        self.available = available
        self.daily_calls: list[str] = []
        self.name_calls: list[str] = []

    def _fetch_raw_data(self, stock_code, start_date, end_date):
        raise NotImplementedError

    def _normalize_data(self, df, stock_code):
        raise NotImplementedError

    def is_available_for_request(self, _capability: str) -> bool:
        return self.available

    def get_daily_data(self, stock_code, start_date=None, end_date=None, days=30):
        self.daily_calls.append(stock_code)
        if isinstance(self.daily_result, Exception):
            raise self.daily_result
        if self.daily_result is None:
            return pd.DataFrame()
        return self.daily_result.copy()

    def get_stock_name(self, stock_code):
        self.name_calls.append(stock_code)
        if isinstance(self.name_result, Exception):
            raise self.name_result
        return self.name_result


def _manager_without_fetchers() -> DataFetcherManager:
    manager = DataFetcherManager.__new__(DataFetcherManager)
    manager._fetchers = []
    manager._ensure_concurrency_guards()
    return manager


@pytest.mark.parametrize(
    "stock_code",
    ["csi930956", "CSI930956", "930956.CSI", "csi93095", "93095.CSI"],
)
def test_unregistered_csi_daily_is_rejected_before_provider_calls(stock_code) -> None:
    fetcher = _FakeFetcher("YfinanceFetcher", priority=1, daily_result=_daily_frame())
    manager = DataFetcherManager(fetchers=[fetcher])

    with pytest.raises(DataFetchError, match="unregistered CSI index"):
        manager.get_daily_data(stock_code)

    assert fetcher.daily_calls == []


@pytest.mark.parametrize(
    "stock_code",
    ["csi930956", "CSI930956", "930956.CSI", "csi93095", "93095.CSI"],
)
def test_unregistered_csi_name_is_rejected_before_provider_calls(stock_code) -> None:
    fetcher = _FakeFetcher("YfinanceFetcher", priority=1, name_result="wrong")
    manager = DataFetcherManager(fetchers=[fetcher])

    assert manager.get_stock_name(stock_code) == ""
    assert fetcher.name_calls == []


def test_prefetch_stock_names_skips_unregistered_csi() -> None:
    fetcher = _FakeFetcher("YfinanceFetcher", priority=1, name_result="wrong")
    manager = DataFetcherManager(fetchers=[fetcher])

    manager.prefetch_stock_names(["csi930956", "930956.CSI"])

    assert fetcher.name_calls == []


@pytest.fixture(autouse=True)
def _reset_daily_source_health():
    DataFetcherManager.reset_daily_source_health()
    yield
    DataFetcherManager.reset_daily_source_health()


def test_index_daily_route_uses_fixed_order_symbols_and_diagnostics() -> None:
    tencent = _FakeFetcher(
        "TencentFetcher", priority=9, daily_result=RuntimeError("tencent failed")
    )
    akshare = _FakeFetcher("AkshareFetcher", priority=8, daily_result=pd.DataFrame())
    tickflow = _FakeFetcher(
        "TickFlowFetcher", priority=7, daily_result=_daily_frame(), available=False
    )
    yfinance = _FakeFetcher("YfinanceFetcher", priority=0, daily_result=_daily_frame())
    manager = DataFetcherManager(fetchers=[yfinance, tickflow, akshare, tencent])

    with patch("data_provider.base.record_provider_run") as record_run:
        df, source = manager.get_daily_data(
            "sh000016", start_date="2026-08-01", end_date="2026-08-21"
        )

    assert not df.empty
    assert source == "YfinanceFetcher"
    assert tencent.daily_calls == ["sh000016"]
    assert akshare.daily_calls == ["sh000016"]
    assert tickflow.daily_calls == []
    assert yfinance.daily_calls == ["000016.SS"]
    assert [item.kwargs["provider"] for item in record_run.call_args_list] == [
        "TencentFetcher",
        "AkshareFetcher",
        "TickFlowFetcher",
        "YfinanceFetcher",
    ]
    assert [item.kwargs.get("fallback_to") for item in record_run.call_args_list] == [
        "AkshareFetcher",
        "TickFlowFetcher",
        "YfinanceFetcher",
        None,
    ]
    assert [
        (
            item.kwargs["success"],
            item.kwargs.get("error_type"),
            item.kwargs.get("error_message"),
            item.kwargs.get("record_count"),
        )
        for item in record_run.call_args_list
    ] == [
        (False, "RuntimeError", "tencent failed", 0),
        (False, "empty", "empty result", 0),
        (False, "unavailable", "数据源未配置或暂不可用", 0),
        (True, None, None, 1),
    ]


def test_index_daily_route_short_circuits_after_tencent_success() -> None:
    tencent = _FakeFetcher("TencentFetcher", priority=9, daily_result=_daily_frame())
    akshare = _FakeFetcher("AkshareFetcher", priority=0, daily_result=_daily_frame())
    tickflow = _FakeFetcher("TickFlowFetcher", priority=1, daily_result=_daily_frame())
    yfinance = _FakeFetcher("YfinanceFetcher", priority=2, daily_result=_daily_frame())
    manager = DataFetcherManager(fetchers=[akshare, tickflow, yfinance, tencent])

    with patch("data_provider.base.record_provider_run") as record_run:
        df, source = manager.get_daily_data("sz399001")

    assert not df.empty
    assert source == "TencentFetcher"
    assert tencent.daily_calls == ["sz399001"]
    assert akshare.daily_calls == []
    assert tickflow.daily_calls == []
    assert yfinance.daily_calls == []
    assert record_run.call_args.kwargs.get("fallback_to") is None


def test_index_daily_route_short_circuits_after_akshare_success() -> None:
    tencent = _FakeFetcher("TencentFetcher", priority=0, daily_result=pd.DataFrame())
    akshare = _FakeFetcher("AkshareFetcher", priority=1, daily_result=_daily_frame())
    tickflow = _FakeFetcher("TickFlowFetcher", priority=2, daily_result=_daily_frame())
    yfinance = _FakeFetcher("YfinanceFetcher", priority=3, daily_result=_daily_frame())
    manager = DataFetcherManager(fetchers=[tencent, akshare, tickflow, yfinance])

    _, source = manager.get_daily_data("sh000016")

    assert source == "AkshareFetcher"
    assert tencent.daily_calls == ["sh000016"]
    assert akshare.daily_calls == ["sh000016"]
    assert tickflow.daily_calls == []
    assert yfinance.daily_calls == []


def test_index_daily_route_short_circuits_after_tickflow_success() -> None:
    tencent = _FakeFetcher("TencentFetcher", priority=0, daily_result=pd.DataFrame())
    akshare = _FakeFetcher("AkshareFetcher", priority=1, daily_result=pd.DataFrame())
    tickflow = _FakeFetcher("TickFlowFetcher", priority=2, daily_result=_daily_frame())
    yfinance = _FakeFetcher("YfinanceFetcher", priority=3, daily_result=_daily_frame())
    manager = DataFetcherManager(fetchers=[tencent, akshare, tickflow, yfinance])

    _, source = manager.get_daily_data("sh000016")

    assert source == "TickFlowFetcher"
    assert tencent.daily_calls == ["sh000016"]
    assert akshare.daily_calls == ["sh000016"]
    assert tickflow.daily_calls == ["000016.SH"]
    assert yfinance.daily_calls == []


def test_index_provider_symbols_cover_shanghai_and_shenzhen() -> None:
    sh_target = parse_analysis_target("sh000016")
    sz_target = parse_analysis_target("sz399001")

    assert DataFetcherManager._cn_index_provider_symbol(
        sh_target, "TencentFetcher"
    ) == "sh000016"
    assert DataFetcherManager._cn_index_provider_symbol(
        sh_target, "TickFlowFetcher"
    ) == "000016.SH"
    assert DataFetcherManager._cn_index_provider_symbol(
        sh_target, "YfinanceFetcher"
    ) == "000016.SS"
    assert DataFetcherManager._cn_index_provider_symbol(
        sz_target, "AkshareFetcher"
    ) == "sz399001"
    assert DataFetcherManager._cn_index_provider_symbol(
        sz_target, "TickFlowFetcher"
    ) == "399001.SZ"
    assert DataFetcherManager._cn_index_provider_symbol(
        sz_target, "YfinanceFetcher"
    ) == "399001.SZ"


def test_index_daily_health_is_isolated_from_regular_cn_route() -> None:
    tencent = _FakeFetcher("TencentFetcher", priority=0, daily_result=_daily_frame())
    manager = DataFetcherManager(fetchers=[tencent])
    regular_cn_key = manager._daily_health_key(tencent, "cn")
    for _ in range(3):
        manager._daily_source_health.record_failure(regular_cn_key, error="failed")

    _, source = manager.get_daily_data("sh000016")

    assert source == "TencentFetcher"
    assert tencent.daily_calls == ["sh000016"]


def test_regular_cn_daily_health_is_isolated_from_index_route() -> None:
    tencent = _FakeFetcher(
        "TencentFetcher", priority=0, daily_result=RuntimeError("index failed")
    )
    manager = DataFetcherManager(fetchers=[tencent])
    index_key = manager._daily_health_key(tencent, "cn_index")

    for _ in range(3):
        result, source = manager.get_daily_data("sh000016")
        assert result.empty
        assert source == ""

    assert not manager._daily_source_health.is_available(index_key)
    assert manager._daily_source_health.is_available(
        manager._daily_health_key(tencent, "cn")
    )

    tencent.daily_result = _daily_frame()
    _, source = manager.get_daily_data("600519")

    assert source == "TencentFetcher"
    assert tencent.daily_calls == ["sh000016", "sh000016", "sh000016", "600519"]


def test_index_daily_skips_unsupported_provider_symbols_without_health_failure() -> None:
    entry = IndexEntry(
        bare_code="000016",
        exchange="HK",
        canonical_id="hk000016",
        display_name="",
    )
    target = AnalysisTarget(
        raw_input="hk000016",
        asset_type=ParseStatus.INDEX,
        canonical_id="hk000016",
        display_code="000016.HK",
        exchange="HK",
        matched_index=entry,
    )
    fetchers = [
        _FakeFetcher("TencentFetcher", priority=0, daily_result=_daily_frame()),
        _FakeFetcher("AkshareFetcher", priority=1, daily_result=_daily_frame()),
        _FakeFetcher("TickFlowFetcher", priority=2, daily_result=_daily_frame()),
        _FakeFetcher("YfinanceFetcher", priority=3, daily_result=_daily_frame()),
    ]
    manager = DataFetcherManager(fetchers=cast(list[BaseFetcher], fetchers))

    with patch("data_provider.base.parse_analysis_target", return_value=target), patch(
        "data_provider.base.record_provider_run"
    ) as record_run, patch.object(
        DataFetcherManager, "_record_daily_source_failure"
    ) as record_health_failure:
        df, source = manager.get_daily_data("hk000016")

    assert df.empty
    assert source == ""
    assert all(fetcher.daily_calls == [] for fetcher in fetchers)
    assert [item.kwargs["error_type"] for item in record_run.call_args_list] == [
        "unsupported",
        "unsupported",
        "unsupported",
        "unsupported",
    ]
    assert all(
        "unsupported index provider symbol" in item.kwargs["error_message"]
        for item in record_run.call_args_list
    )
    assert all(item.kwargs["record_count"] == 0 for item in record_run.call_args_list)
    record_health_failure.assert_not_called()


def test_index_daily_route_returns_standard_empty_result_when_all_sources_fail(
    caplog,
) -> None:
    fetchers = [
        _FakeFetcher("TencentFetcher", priority=0, daily_result=RuntimeError("boom")),
        _FakeFetcher("AkshareFetcher", priority=1, daily_result=pd.DataFrame()),
        _FakeFetcher("TickFlowFetcher", priority=2, daily_result=RuntimeError("offline")),
        _FakeFetcher("YfinanceFetcher", priority=3, daily_result=pd.DataFrame()),
    ]
    manager = DataFetcherManager(fetchers=cast(list[BaseFetcher], fetchers))

    with caplog.at_level(logging.WARNING):
        df, source = manager.get_daily_data("sh000688")

    assert df.empty
    assert list(df.columns) == STANDARD_COLUMNS
    assert source == ""
    assert [fetcher.daily_calls for fetcher in fetchers] == [
        ["sh000688"],
        ["sh000688"],
        ["000688.SH"],
        ["000688.SS"],
    ]
    assert "sh000688" in caplog.text
    assert "所有指数日线数据源" in caplog.text


@pytest.mark.parametrize("stock_code", ["000016", "000001", "000688"])
def test_bare_conflict_codes_keep_stock_route_and_warn(stock_code, caplog) -> None:
    efinance = _FakeFetcher("EfinanceFetcher", priority=0, daily_result=_daily_frame())
    tencent = _FakeFetcher("TencentFetcher", priority=1, daily_result=_daily_frame())
    manager = DataFetcherManager(fetchers=[efinance, tencent])

    with caplog.at_level(logging.WARNING):
        _, source = manager.get_daily_data(stock_code)

    assert source == "EfinanceFetcher"
    assert efinance.daily_calls == [stock_code]
    assert tencent.daily_calls == []
    assert "裸代码" in caplog.text
    assert "股票路由" in caplog.text


@pytest.mark.parametrize(
    ("stock_code", "stock_name"),
    [
        ("000016", "深康佳A"),
        ("000001", "平安银行"),
        ("000688", "国城矿业"),
    ],
)
def test_bare_conflict_get_stock_name_keeps_stock_name_and_warns(
    stock_code, stock_name, caplog
) -> None:
    manager = _manager_without_fetchers()

    with patch.dict(
        "data_provider.base.STOCK_NAME_MAP", {stock_code: stock_name}, clear=True
    ), caplog.at_level(logging.WARNING):
        name = manager.get_stock_name(stock_code, allow_realtime=False)

    assert name == stock_name
    assert manager._stock_name_cache == {stock_code: stock_name}
    assert "裸代码" in caplog.text
    assert "股票路由" in caplog.text


def test_non_index_prefixed_stock_keeps_existing_normalized_route() -> None:
    efinance = _FakeFetcher("EfinanceFetcher", priority=0, daily_result=_daily_frame())
    tencent = _FakeFetcher("TencentFetcher", priority=1, daily_result=_daily_frame())
    manager = DataFetcherManager(fetchers=[efinance, tencent])

    _, source = manager.get_daily_data("sh600519")

    assert source == "EfinanceFetcher"
    assert efinance.daily_calls == ["600519"]
    assert tencent.daily_calls == []


def test_index_name_uses_registry_name_and_canonical_cache_without_network() -> None:
    tencent = _FakeFetcher("TencentFetcher", priority=2, name_result="错误名称")
    akshare = _FakeFetcher("AkshareFetcher", priority=1, name_result="错误名称")
    tickflow = _FakeFetcher("TickFlowFetcher", priority=0, name_result="错误名称")
    manager = DataFetcherManager(fetchers=[tickflow, akshare, tencent])
    manager._stock_name_cache["sh000016"] = "旧错误名称"

    name = manager.get_stock_name("sh000016", allow_realtime=False)

    assert name == "上证50"
    assert manager._stock_name_cache == {"sh000016": "上证50"}
    assert tencent.name_calls == []
    assert akshare.name_calls == []
    assert tickflow.name_calls == []


def test_index_name_fallback_uses_fixed_order_and_provider_symbols() -> None:
    entry = IndexEntry(
        bare_code="000016",
        exchange="SH",
        canonical_id="sh000016",
        display_name="",
    )
    target = AnalysisTarget(
        raw_input="sh000016",
        asset_type=ParseStatus.INDEX,
        canonical_id="sh000016",
        display_code="",
        exchange="SH",
        matched_index=entry,
    )
    tencent = _FakeFetcher("TencentFetcher", priority=9, name_result=None)
    akshare = _FakeFetcher("AkshareFetcher", priority=8, name_result="")
    tickflow = _FakeFetcher("TickFlowFetcher", priority=0, name_result="网络上证50")
    manager = DataFetcherManager(fetchers=[tickflow, akshare, tencent])

    with patch("data_provider.base.parse_analysis_target", return_value=target):
        name = manager.get_stock_name("sh000016", allow_realtime=False)

    assert name == "网络上证50"
    assert tencent.name_calls == ["sh000016"]
    assert akshare.name_calls == ["sh000016"]
    assert tickflow.name_calls == ["000016.SH"]
    assert manager._stock_name_cache == {"sh000016": "网络上证50"}


def test_index_name_static_fallback_uses_only_canonical_key() -> None:
    entry = IndexEntry(
        bare_code="000016",
        exchange="SH",
        canonical_id="sh000016",
        display_name="",
    )
    target = AnalysisTarget(
        raw_input="sh000016",
        asset_type=ParseStatus.INDEX,
        canonical_id="sh000016",
        display_code="",
        exchange="SH",
        matched_index=entry,
    )
    tencent = _FakeFetcher("TencentFetcher", priority=2, name_result=None)
    akshare = _FakeFetcher("AkshareFetcher", priority=1, name_result="")
    tickflow = _FakeFetcher("TickFlowFetcher", priority=0, name_result=None)
    manager = DataFetcherManager(fetchers=[tickflow, akshare, tencent])

    with patch.dict(
        "data_provider.base.STOCK_NAME_MAP",
        {"sh000016": "静态上证50", "000016": "深康佳A"},
        clear=True,
    ):
        with patch("data_provider.base.parse_analysis_target", return_value=target):
            index_name = manager.get_stock_name("sh000016", allow_realtime=False)
        stock_name = manager.get_stock_name("000016", allow_realtime=False)

    assert index_name == "静态上证50"
    assert stock_name == "深康佳A"
    assert tencent.name_calls == ["sh000016"]
    assert akshare.name_calls == ["sh000016"]
    assert tickflow.name_calls == ["000016.SH"]
    assert manager._stock_name_cache == {
        "sh000016": "静态上证50",
        "000016": "深康佳A",
    }


@pytest.mark.parametrize(
    ("stock_code", "aliases"),
    [
        (
            "sh000016",
            [
                "sh000016",
                "000016",
                "000016.SH",
                "000016.SS",
                "000016.SZ",
            ],
        ),
        ("sz399001", ["sz399001", "399001", "399001.SZ"]),
    ],
)
def test_index_name_validation_rejects_all_code_aliases(stock_code, aliases) -> None:
    target = parse_analysis_target(stock_code)

    assert all(
        not DataFetcherManager._is_meaningful_cn_index_name(alias, target)
        for alias in aliases
    )
    assert DataFetcherManager._is_meaningful_cn_index_name("有效指数名称", target)


def test_index_name_rejects_code_aliases_from_registry_cache_network_and_static() -> None:
    entry = IndexEntry(
        bare_code="000016",
        exchange="SH",
        canonical_id="sh000016",
        display_name="000016.SH",
    )
    target = AnalysisTarget(
        raw_input="sh000016",
        asset_type=ParseStatus.INDEX,
        canonical_id="sh000016",
        display_code="SSE50",
        exchange="SH",
        matched_index=entry,
    )
    tencent = _FakeFetcher("TencentFetcher", priority=0, name_result="sh000016")
    akshare = _FakeFetcher("AkshareFetcher", priority=1, name_result="000016.SS")
    tickflow = _FakeFetcher("TickFlowFetcher", priority=2, name_result="SSE50")
    manager = DataFetcherManager(fetchers=[tencent, akshare, tickflow])
    manager._stock_name_cache["sh000016"] = "000016"

    with patch.dict(
        "data_provider.base.STOCK_NAME_MAP", {"sh000016": "000016"}, clear=True
    ), patch("data_provider.base.parse_analysis_target", return_value=target):
        name = manager.get_stock_name("sh000016", allow_realtime=False)

    assert name == "sh000016"
    assert manager._stock_name_cache == {}
    assert tencent.name_calls == ["sh000016"]
    assert akshare.name_calls == ["sh000016"]
    assert tickflow.name_calls == ["000016.SH"]


def test_index_name_returns_canonical_id_when_registry_and_network_fail() -> None:
    entry = IndexEntry(
        bare_code="399001",
        exchange="SZ",
        canonical_id="sz399001",
        display_name="",
    )
    target = AnalysisTarget(
        raw_input="sz399001",
        asset_type=ParseStatus.INDEX,
        canonical_id="sz399001",
        display_code="",
        exchange="SZ",
        matched_index=entry,
    )
    fetchers = [
        _FakeFetcher("TencentFetcher", priority=0, name_result=RuntimeError("failed")),
        _FakeFetcher("AkshareFetcher", priority=1, name_result=None),
        _FakeFetcher("TickFlowFetcher", priority=2, name_result=""),
    ]
    manager = DataFetcherManager(fetchers=cast(list[BaseFetcher], fetchers))

    with patch("data_provider.base.parse_analysis_target", return_value=target):
        name = manager.get_stock_name("sz399001", allow_realtime=False)

    assert name == "sz399001"
    assert manager._stock_name_cache == {}


def test_index_and_same_bare_stock_names_use_isolated_cache_keys() -> None:
    manager = _manager_without_fetchers()

    with patch.dict(
        "data_provider.base.STOCK_NAME_MAP", {"000016": "深康佳A"}, clear=True
    ):
        stock_name = manager.get_stock_name("000016", allow_realtime=False)
        index_name = manager.get_stock_name("sh000016", allow_realtime=False)

    assert stock_name == "深康佳A"
    assert index_name == "上证50"
    assert manager._stock_name_cache == {
        "000016": "深康佳A",
        "sh000016": "上证50",
    }


# ---------------------------------------------------------------------------
# CSI provider symbol routing.
# ---------------------------------------------------------------------------
def test_csi_provider_symbols_follow_manifest_matrix() -> None:
    csi_target = parse_analysis_target("csi930955")
    assert csi_target.asset_type == ParseStatus.INDEX
    assert csi_target.exchange == "CSI"

    # AkShare is the only supported CSI daily provider.
    assert DataFetcherManager._cn_index_provider_symbol(
        csi_target, "AkshareFetcher"
    ) == "csi930955"
    # Tencent / TickFlow / Yahoo are unsupported for CSI.
    assert DataFetcherManager._cn_index_provider_symbol(
        csi_target, "TencentFetcher"
    ) == ""
    assert DataFetcherManager._cn_index_provider_symbol(
        csi_target, "TickFlowFetcher"
    ) == ""
    assert DataFetcherManager._cn_index_provider_symbol(
        csi_target, "YfinanceFetcher"
    ) == ""


def test_csi_daily_route_skips_unsupported_providers_without_health_failure() -> None:
    tencent = _FakeFetcher("TencentFetcher", priority=0, daily_result=_daily_frame())
    akshare = _FakeFetcher("AkshareFetcher", priority=1, daily_result=_daily_frame())
    tickflow = _FakeFetcher("TickFlowFetcher", priority=2, daily_result=_daily_frame())
    yfinance = _FakeFetcher("YfinanceFetcher", priority=3, daily_result=_daily_frame())
    manager = DataFetcherManager(fetchers=[tencent, akshare, tickflow, yfinance])

    with patch("data_provider.base.record_provider_run") as record_run, patch.object(
        DataFetcherManager, "_record_daily_source_failure"
    ) as record_health_failure:
        df, source = manager.get_daily_data("csi930955")

    # AkShare succeeds with the csi symbol.
    assert not df.empty
    assert source == "AkshareFetcher"
    assert tencent.daily_calls == []
    assert akshare.daily_calls == ["csi930955"]
    assert tickflow.daily_calls == []
    assert yfinance.daily_calls == []
    # Unsupported providers recorded as unsupported, no health failure.
    # AkShare's successful call short-circuits the loop, so only Tencent
    # (unsupported) and AkShare (success) are recorded.
    assert [item.kwargs.get("error_type") for item in record_run.call_args_list] == [
        "unsupported",
        None,
    ]
    record_health_failure.assert_not_called()


def test_csi_daily_route_returns_empty_when_akshare_fails() -> None:
    tencent = _FakeFetcher("TencentFetcher", priority=0, daily_result=_daily_frame())
    akshare = _FakeFetcher(
        "AkshareFetcher", priority=1, daily_result=RuntimeError("akshare failed")
    )
    tickflow = _FakeFetcher("TickFlowFetcher", priority=2, daily_result=_daily_frame())
    yfinance = _FakeFetcher("YfinanceFetcher", priority=3, daily_result=_daily_frame())
    manager = DataFetcherManager(fetchers=[tencent, akshare, tickflow, yfinance])

    with patch("data_provider.base.record_provider_run") as record_run:
        df, source = manager.get_daily_data("csi930955")

    assert df.empty
    assert source == ""
    assert tencent.daily_calls == []
    assert akshare.daily_calls == ["csi930955"]
    assert tickflow.daily_calls == []
    assert yfinance.daily_calls == []
    # Tencent/TickFlow/Yahoo are unsupported (no network), AkShare failed.
    assert [item.kwargs["error_type"] for item in record_run.call_args_list] == [
        "unsupported",
        "RuntimeError",
        "unsupported",
        "unsupported",
    ]
