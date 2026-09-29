import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_provider.akshare_fetcher import AkshareFetcher
from data_provider.base import DataFetchError, RateLimitError, STANDARD_COLUMNS


def _make_fetcher() -> AkshareFetcher:
    with patch(
        "data_provider.akshare_fetcher.get_config",
        return_value=SimpleNamespace(enable_eastmoney_patch=False),
    ):
        return AkshareFetcher(sleep_min=0, sleep_max=0)


def _call_akshare_inline(func, *args, timeout=None, call_name="", **kwargs):
    return func(*args, **kwargs)


def test_akshare_recognized_index_uses_index_daily_api_and_standard_columns() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-08-20", "2026-08-21"],
            "open": [100.0, 101.0],
            "close": [101.0, 102.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "volume": [1000, 1100],
            "amount": [101000.0, 112200.0],
        }
    )
    index_daily = MagicMock(return_value=raw)
    fake_akshare = types.SimpleNamespace(stock_zh_index_daily_em=index_daily)
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
        fetcher, "_set_random_user_agent"
    ), patch.object(fetcher, "_enforce_rate_limit"), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ) as timeout_call:
        df = fetcher.get_daily_data(
            "sh000016", start_date="2026-08-01", end_date="2026-08-21"
        )

    index_daily.assert_called_once_with(
        symbol="sh000016", start_date="20260801", end_date="20260821"
    )
    timeout_call.assert_called_once_with(
        index_daily,
        timeout=fetcher._history_call_timeout,
        call_name="ak.stock_zh_index_daily_em",
        symbol="sh000016",
        start_date="20260801",
        end_date="20260821",
    )
    assert set(STANDARD_COLUMNS).issubset(df.columns)
    assert set(["code", "ma5", "ma10", "ma20"]).issubset(df.columns)
    assert df["code"].tolist() == ["sh000016", "sh000016"]
    assert df["pct_chg"].round(2).tolist() == [0.0, 0.99]


def test_akshare_index_daily_sorts_and_handles_missing_amount_and_infinite_pct() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-08-21", "2026-08-20"],
            "open": [10.0, 0.0],
            "close": [10.0, 0.0],
            "high": [11.0, 0.0],
            "low": [9.0, 0.0],
            "volume": [1000, 900],
        }
    )
    fake_akshare = types.SimpleNamespace(
        stock_zh_index_daily_em=MagicMock(return_value=raw)
    )
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ), patch.object(fetcher, "_set_random_user_agent"), patch.object(
        fetcher, "_enforce_rate_limit"
    ):
        result = fetcher._fetch_index_data(
            "sh000016", "2026-08-01", "2026-08-21"
        )

    assert result["date"].tolist() == ["2026-08-20", "2026-08-21"]
    assert "amount" in result.columns
    assert result["amount"].isna().all()
    assert result["pct_chg"].iloc[0] == 0.0
    assert pd.isna(result["pct_chg"].iloc[1])


def test_akshare_index_daily_rejects_invalid_required_schema() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-08-21"],
            "open": [10.0],
            "close": [10.0],
            "high": [11.0],
            "low": [9.0],
        }
    )
    fake_akshare = types.SimpleNamespace(
        stock_zh_index_daily_em=MagicMock(return_value=raw)
    )
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ), patch.object(fetcher, "_set_random_user_agent"), patch.object(
        fetcher, "_enforce_rate_limit"
    ), pytest.raises(DataFetchError, match="volume"):
        fetcher._fetch_index_data("sh000016", "2026-08-01", "2026-08-21")


def test_akshare_index_daily_rejects_unparseable_dates() -> None:
    raw = pd.DataFrame(
        {
            "date": ["2026-08-20", "not-a-date"],
            "open": [10.0, 10.1],
            "close": [10.1, 10.2],
            "high": [10.2, 10.3],
            "low": [9.9, 10.0],
            "volume": [1000, 1100],
        }
    )
    fake_akshare = types.SimpleNamespace(
        stock_zh_index_daily_em=MagicMock(return_value=raw)
    )
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ), patch.object(fetcher, "_set_random_user_agent"), patch.object(
        fetcher, "_enforce_rate_limit"
    ), pytest.raises(DataFetchError, match="date"):
        fetcher._fetch_index_data("sh000016", "2026-08-01", "2026-08-21")


@pytest.mark.parametrize("error_type", [ConnectionError, TimeoutError])
def test_akshare_index_daily_preserves_retryable_builtin_errors(error_type) -> None:
    fake_akshare = types.SimpleNamespace(stock_zh_index_daily_em=object())
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=error_type("retry me"),
    ), patch.object(fetcher, "_set_random_user_agent"), patch.object(
        fetcher, "_enforce_rate_limit"
    ), pytest.raises(error_type, match="retry me"):
        fetcher._fetch_index_data("sh000016", "2026-08-01", "2026-08-21")


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        (RuntimeError("rate limit reached"), RateLimitError),
        (ValueError("bad payload"), DataFetchError),
    ],
)
def test_akshare_index_daily_classifies_non_retryable_errors(
    error, expected_type
) -> None:
    fake_akshare = types.SimpleNamespace(stock_zh_index_daily_em=object())
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=error,
    ), patch.object(fetcher, "_set_random_user_agent"), patch.object(
        fetcher, "_enforce_rate_limit"
    ), pytest.raises(expected_type):
        fetcher._fetch_index_data("sh000016", "2026-08-01", "2026-08-21")


def test_akshare_generic_normalization_does_not_fill_index_only_columns() -> None:
    fetcher = _make_fetcher()
    raw = pd.DataFrame(
        {
            "日期": ["2026-08-21"],
            "开盘": [10.0],
            "收盘": [10.2],
            "最高": [10.5],
            "最低": [9.8],
            "成交量": [1000],
        }
    )

    result = fetcher._normalize_data(raw, "600519")

    assert "amount" not in result.columns
    assert "pct_chg" not in result.columns


def test_akshare_bare_conflict_code_stays_on_stock_api() -> None:
    fetcher = _make_fetcher()
    stock_result = pd.DataFrame({"日期": ["2026-08-21"]})

    with patch.object(
        fetcher, "_fetch_stock_data", return_value=stock_result
    ) as fetch_stock, patch.object(
        fetcher, "_fetch_index_data", return_value=pd.DataFrame()
    ) as fetch_index:
        result = fetcher._fetch_raw_data("000016", "2026-08-01", "2026-08-21")

    assert result is stock_result
    fetch_stock.assert_called_once_with("000016", "2026-08-01", "2026-08-21")
    fetch_index.assert_not_called()


def test_akshare_index_name_filters_exchange_spot_table() -> None:
    spot = MagicMock(
        return_value=pd.DataFrame(
            {
                "代码": ["000001", "000016"],
                "名称": ["上证指数", "上证50"],
            }
        )
    )
    fake_akshare = types.SimpleNamespace(stock_zh_index_spot_em=spot)
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
        fetcher, "_set_random_user_agent"
    ), patch.object(fetcher, "_enforce_rate_limit"), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ) as timeout_call:
        name = fetcher.get_stock_name("sh000016")

    assert name == "上证50"
    spot.assert_called_once_with(symbol="上证系列指数")
    timeout_call.assert_called_once_with(
        spot,
        timeout=fetcher._history_call_timeout,
        call_name="ak.stock_zh_index_spot_em",
        symbol="上证系列指数",
    )


def test_akshare_index_name_uses_shenzhen_spot_table() -> None:
    spot = MagicMock(
        return_value=pd.DataFrame({"代码": [399001], "名称": ["深证成指"]})
    )
    fake_akshare = types.SimpleNamespace(stock_zh_index_spot_em=spot)
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
        fetcher, "_set_random_user_agent"
    ), patch.object(fetcher, "_enforce_rate_limit"), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ):
        name = fetcher.get_stock_name("sz399001")

    assert name == "深证成指"
    spot.assert_called_once_with(symbol="深证系列指数")


def test_akshare_index_name_rejects_missing_name_value() -> None:
    spot = MagicMock(
        return_value=pd.DataFrame({"代码": ["000016"], "名称": [pd.NA]})
    )
    fake_akshare = types.SimpleNamespace(stock_zh_index_spot_em=spot)
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
        fetcher, "_set_random_user_agent"
    ), patch.object(fetcher, "_enforce_rate_limit"), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ):
        name = fetcher.get_stock_name("sh000016")

    assert name is None


def test_akshare_index_name_uses_first_non_blank_duplicate() -> None:
    spot = MagicMock(
        return_value=pd.DataFrame(
            {
                "代码": ["000016", "000016", "000016"],
                "名称": [pd.NA, "   ", "上证50"],
            }
        )
    )
    fake_akshare = types.SimpleNamespace(stock_zh_index_spot_em=spot)
    fetcher = _make_fetcher()

    with patch.dict(sys.modules, {"akshare": fake_akshare}), patch.object(
        fetcher, "_set_random_user_agent"
    ), patch.object(fetcher, "_enforce_rate_limit"), patch(
        "data_provider.akshare_fetcher._akshare_call_with_timeout",
        side_effect=_call_akshare_inline,
    ):
        name = fetcher.get_stock_name("sh000016")

    assert name == "上证50"
