# -*- coding: utf-8 -*-
"""Wave 2 tests: TdxLocalFetcher registration / behavior / config surface.

Plan: .omz/plans/sess_e87ee49d-53a9-4947-bffc-95ef3ff5f852-issue2143-local-cache.md (Wave 2).

Global test conventions (critic blocker fixes, mandatory):
- Every case touching TDX_* config must monkeypatch.setenv/delenv FIRST and then
  call ``Config.reset_instance()`` (src/config.py) -- ``Config.get_instance()``
  only reads env on first instantiation, so a stale singleton makes registration
  and config assertions lie. An autouse fixture resets the singleton again after
  each test (post-monkeypatch-undo safety for other test files).
- Cases that may touch manager circuit-breaker health reset
  ``DataFetcherManager.reset_daily_source_health()`` in the autouse fixture
  (``_daily_source_health`` is class-level state persisting across tests).
"""

import logging
import os
import shutil
import struct
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from data_provider.base import (
    STANDARD_COLUMNS,
    BaseFetcher,
    DataFetcherManager,
    is_bse_code,
)
from data_provider.tdx_day_parser import DAY_RECORD_STRUCT
from src.config import Config, get_config

pytestmark = pytest.mark.unit


# === 合成 fixture 工具（与 Wave 1 同款：struct.pack 合成字节，零真实 TDX 依赖） ===


def _pack_record(
    date_int: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    amount: float,
    volume: int,
    reserved: int = 0,
) -> bytes:
    return struct.pack(
        DAY_RECORD_STRUCT,
        date_int,
        int(round(open_ * 100)),
        int(round(high * 100)),
        int(round(low * 100)),
        int(round(close * 100)),
        float(amount),
        int(volume),
        reserved,
    )


def _records_for_dates(dates, base_price: float = 10.0):
    """Deterministic OHLCV records: prices drift +0.1 yuan per bar."""
    records = []
    for index, day in enumerate(dates):
        open_ = base_price + index * 0.1
        records.append(
            _pack_record(
                int(day.strftime("%Y%m%d")),
                open_,
                open_ + 0.5,
                open_ - 0.2,
                open_ + 0.3,
                1_000_000.0 + index * 1000,
                100_000 + index * 100,
            )
        )
    return records


def _write_day_file(path: Path, records) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(records))
    return path


def _make_tdx_tree(tmp_path: Path, style: str = "install") -> Path:
    """Build a minimal vipdoc tree.

    style="install": returns the TDX install root containing ``vipdoc/``.
    style="vipdoc": returns the vipdoc directory itself (``sh/lday`` inside).
    """
    if style == "install":
        root = tmp_path / "new_tdx"
        vipdoc = root / "vipdoc"
    else:
        root = tmp_path
        vipdoc = root
    (vipdoc / "sh" / "lday").mkdir(parents=True, exist_ok=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True, exist_ok=True)
    return root


def _make_fetcher(tmp_path: Path, monkeypatch) -> BaseFetcher:
    """Construct a TdxLocalFetcher bound to a synthetic vipdoc tree.

    Layout: TDX_LOCAL_PATH points at ``tmp_path`` (install-root style) whose
    ``vipdoc/`` holds ``sh|sz/lday`` -- behavior tests then write day files at
    ``tmp_path/vipdoc/<mkt>/lday/<mkt><code>.day``. Exercises the
    resolve_vipdoc_root auto-descend branch on every fetch.
    """
    from data_provider.tdx_local_fetcher import TdxLocalFetcher

    vipdoc = tmp_path / "vipdoc"
    (vipdoc / "sh" / "lday").mkdir(parents=True, exist_ok=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TDX_LOCAL_PATH", str(tmp_path))
    monkeypatch.delenv("TDX_LOCAL_PRIORITY", raising=False)
    monkeypatch.delenv("TDX_LOCAL_MAX_STALE_DAYS", raising=False)
    Config.reset_instance()
    return TdxLocalFetcher()


@pytest.fixture(autouse=True)
def _isolate_global_state(monkeypatch):
    """Global test conventions (plan Wave 2, critic blocker fix)."""
    from data_provider.base import DataFetcherManager as _Manager

    Config.reset_instance()
    _Manager.reset_daily_source_health()
    yield
    Config.reset_instance()
    _Manager.reset_daily_source_health()


# === 注册面（5 例） ===


def test_not_registered_without_env(monkeypatch):
    """默认环境（不设 TDX_LOCAL_PATH）不注册本地源：CI 排序与改动前完全一致。"""
    monkeypatch.delenv("TDX_LOCAL_PATH", raising=False)
    Config.reset_instance()
    manager = DataFetcherManager()
    assert "TdxLocalFetcher" not in manager.available_fetchers


def test_not_registered_when_path_missing(monkeypatch, tmp_path):
    """TDX_LOCAL_PATH 指向不存在的目录 → 不注册（D4 门槛 a）。"""
    monkeypatch.setenv("TDX_LOCAL_PATH", str(tmp_path / "no_such_tdx"))
    Config.reset_instance()
    manager = DataFetcherManager()
    assert "TdxLocalFetcher" not in manager.available_fetchers


def test_registered_first_by_default_when_path_exists(monkeypatch, tmp_path):
    """路径存在 → 注册且排序后居首位（优先级 0 + 列表序稳定排序，D7）。"""
    root = _make_tdx_tree(tmp_path, style="install")
    monkeypatch.setenv("TDX_LOCAL_PATH", str(root))
    monkeypatch.delenv("TDX_LOCAL_PRIORITY", raising=False)
    Config.reset_instance()
    manager = DataFetcherManager()
    names = manager.available_fetchers
    assert "TdxLocalFetcher" in names
    assert names[0] == "TdxLocalFetcher"
    # 同优先级 0 的 Efinance 严格排在其后（稳定排序保持列表序）
    assert names.index("TdxLocalFetcher") < names.index("EfinanceFetcher")


def test_priority_env_override_reorders(monkeypatch, tmp_path):
    """TDX_LOCAL_PRIORITY=5 → 排到 efinance/akshare/pytdx 之后。"""
    root = _make_tdx_tree(tmp_path)
    monkeypatch.setenv("TDX_LOCAL_PATH", str(root))
    monkeypatch.setenv("TDX_LOCAL_PRIORITY", "5")
    Config.reset_instance()
    manager = DataFetcherManager()
    names = manager.available_fetchers
    local_index = names.index("TdxLocalFetcher")
    assert local_index > names.index("EfinanceFetcher")
    assert local_index > names.index("AkshareFetcher")
    assert local_index > names.index("PytdxFetcher")


def test_is_available_for_request_false_when_dir_removed(monkeypatch, tmp_path):
    """构造后删除目录 → is_available_for_request 返回 False（D4 门槛 b）。"""
    from data_provider.tdx_local_fetcher import TdxLocalFetcher

    root = _make_tdx_tree(tmp_path)
    monkeypatch.setenv("TDX_LOCAL_PATH", str(root))
    Config.reset_instance()
    fetcher = TdxLocalFetcher()
    assert fetcher.is_available_for_request("daily_data") is True
    shutil.rmtree(root)
    assert fetcher.is_available_for_request("daily_data") is False


# === 行为面（6 例） ===


def test_get_daily_data_reads_local_file(tmp_path, monkeypatch):
    """合成 sh600519.day（30 条）→ get_daily_data 返回 ['code']+STANDARD_COLUMNS 契约。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=i) for i in range(30)]
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    df = fetcher.get_daily_data("600519", start_date="2026-01-01", end_date="2026-01-30")

    assert len(df) == 30
    assert list(df.columns)[:9] == ["code"] + STANDARD_COLUMNS
    assert (df["code"] == "600519").all()
    # 价格 ÷100 转元（首条 open=10.0, close=10.3）
    assert df["open"].iloc[0] == pytest.approx(10.0, abs=1e-9)
    assert df["close"].iloc[0] == pytest.approx(10.3, abs=1e-9)
    assert df["volume"].iloc[0] == 100_000
    # pct_chg 首行为 0（.day 无涨跌幅列，由 close 计算并 fillna(0)）
    assert df["pct_chg"].iloc[0] == 0
    # ma5/ma20 由基类 _calculate_indicators 生成，本 fetcher 不自己算
    assert df["ma5"].iloc[0] == pytest.approx(df["close"].iloc[0])
    assert df["ma20"].iloc[4] == pytest.approx(df["close"].iloc[:5].mean(), abs=0.01)


def test_window_filtering_start_end(tmp_path, monkeypatch):
    """文件 60 条、请求窗口只覆盖中段 20 天 → 只返回窗口内行。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    start = date(2026, 3, 1)
    dates = [start + timedelta(days=i) for i in range(60)]
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    df = fetcher.get_daily_data(
        "600519",
        start_date=(start + timedelta(days=20)).isoformat(),
        end_date=(start + timedelta(days=39)).isoformat(),
    )

    assert len(df) == 20
    assert df["date"].iloc[0] == pd.Timestamp(start + timedelta(days=20))
    assert df["date"].iloc[-1] == pd.Timestamp(start + timedelta(days=39))


def test_days_semantics_matches_base_contract(tmp_path, monkeypatch):
    """只传 days=5 → 窗口 = today-10d..today（base.py:467-500 契约）。

    fixture 日期按 datetime.now() 动态回溯生成，断言集合相等，不写死日期
    （避免午夜/周末漂移误挂）。
    """
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    today = datetime.now().date()
    dates = [today - timedelta(days=offset) for offset in range(20, -1, -1)]
    _write_day_file(
        tmp_path / "vipdoc" / "sz" / "lday" / "sz000001.day",
        _records_for_dates(dates),
    )

    df = fetcher.get_daily_data("000001", days=5)

    window_start = today - timedelta(days=10)
    expected = [d for d in dates if d >= window_start]
    returned = [d.date() if hasattr(d, "date") else d for d in df["date"]]
    assert returned == expected


def test_bse_code_returns_empty(tmp_path, monkeypatch):
    """BSE 码 → _fetch_raw_data 空 + allow_empty_daily_data True → 空 df 不抛（D6/D8）。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    assert is_bse_code("920748")
    assert fetcher.allow_empty_daily_data is True

    raw = fetcher._fetch_raw_data("920748", "2026-01-01", "2026-01-30")
    assert raw is not None and raw.empty

    df = fetcher.get_daily_data("920748", start_date="2026-01-01", end_date="2026-01-30")
    assert df.empty


def test_hk_code_returns_empty_defensively(tmp_path, monkeypatch):
    """港股码直接调 fetcher → 空（manager 层另有市场表过滤，D8 防御）。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    raw = fetcher._fetch_raw_data("00700", "2026-01-01", "2026-01-30")
    assert raw is not None and raw.empty

    df = fetcher.get_daily_data("00700", start_date="2026-01-01", end_date="2026-01-30")
    assert df.empty


def test_support_table_entry():
    """市场支持表：TdxLocalFetcher 仅支持 cn（base.py:801 按 name 查表）。"""
    assert DataFetcherManager._DAILY_MARKET_FETCHER_SUPPORT["TdxLocalFetcher"] == {"cn"}


# === 配置面（3 例） ===


def test_config_defaults_when_unset(monkeypatch):
    """清 env → path None / priority 0 / max_stale_days 10。"""
    monkeypatch.delenv("TDX_LOCAL_PATH", raising=False)
    monkeypatch.delenv("TDX_LOCAL_PRIORITY", raising=False)
    monkeypatch.delenv("TDX_LOCAL_MAX_STALE_DAYS", raising=False)
    Config.reset_instance()
    config = get_config()
    assert config.tdx_local_path is None
    assert config.tdx_local_priority == 0
    assert config.tdx_local_max_stale_days == 10


def test_config_env_parsing(monkeypatch, tmp_path):
    """setenv 三键 → 正确解析；TDX_LOCAL_PRIORITY=-1 走 parse_env_int 最小值钳制。"""
    monkeypatch.setenv("TDX_LOCAL_PATH", str(tmp_path))
    monkeypatch.setenv("TDX_LOCAL_PRIORITY", "3")
    monkeypatch.setenv("TDX_LOCAL_MAX_STALE_DAYS", "20")
    Config.reset_instance()
    config = get_config()
    assert config.tdx_local_path == str(tmp_path)
    assert config.tdx_local_priority == 3
    assert config.tdx_local_max_stale_days == 20

    # 对齐 TICKFLOW_PRIORITY 样板（config.py:1915）：minimum=0 时负值钳制为 0
    monkeypatch.setenv("TDX_LOCAL_PRIORITY", "-1")
    Config.reset_instance()
    config = get_config()
    assert config.tdx_local_priority == 0


def test_config_registry_contains_tdx_keys():
    """registry 三个 key 存在、category == data_source、help_key 指向 settings.data_source.*。"""
    from src.core.config_registry import get_field_definition, get_registered_field_keys

    registered = set(get_registered_field_keys())
    for key in ("TDX_LOCAL_PATH", "TDX_LOCAL_PRIORITY", "TDX_LOCAL_MAX_STALE_DAYS"):
        assert key in registered, f"{key} not registered in _FIELD_DEFINITIONS"
        field = get_field_definition(key)
        assert field["category"] == "data_source", f"{key} category"
        assert field["help_key"] == f"settings.data_source.{key}", f"{key} help_key"


# === Wave 3：过期回退（D5）与对抗组（14 例） ===


class _FakeNetworkFetcher(BaseFetcher):
    """管理器回退测试用的网络源替身：记录调用并返回窗口末日单行数据。"""

    name = "FakeNetworkFetcher"
    priority = 1

    def __init__(self, priority: int = 1):
        super().__init__()
        self.priority = priority
        self.calls = []

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.calls.append((stock_code, start_date, end_date))
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp(end_date),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1000,
                    "amount": 100500.0,
                }
            ]
        )

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        df = df.copy()
        df["code"] = stock_code
        keep = ["code"] + [c for c in STANDARD_COLUMNS if c in df.columns]
        return df[keep]


class _FullWindowNetworkFetcher(BaseFetcher):
    """管理器回退测试用的网络源替身：返回请求窗口内每一天一行的完整数据。"""

    name = "FakeFullNetworkFetcher"
    priority = 1

    def __init__(self, priority: int = 1):
        super().__init__()
        self.priority = priority
        self.calls = []

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.calls.append((stock_code, start_date, end_date))
        span = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days
        dates = [
            pd.Timestamp(start_date) + pd.Timedelta(days=offset)
            for offset in range(span + 1)
        ]
        return pd.DataFrame(
            [
                {
                    "date": day,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1000,
                    "amount": 100500.0,
                }
                for day in dates
            ]
        )

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        df = df.copy()
        df["code"] = stock_code
        keep = ["code"] + [c for c in STANDARD_COLUMNS if c in df.columns]
        return df[keep]


def _consecutive_dates(end_day, count: int):
    """以 ``end_day`` 结尾的 ``count`` 个连续日历日（最新 bar 即 end_day）。"""
    return [end_day - timedelta(days=offset) for offset in range(count - 1, -1, -1)]


def test_stale_local_falls_back_to_network_via_manager(tmp_path, monkeypatch):
    """本地最新 bar 落后 end_date 15 天（> 默认 10）→ 管理器回退网络源且网络源确被调用。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    end_day = date(2026, 6, 15)
    dates = _consecutive_dates(end_day, 15)  # 最新 bar 06-15，end 06-30，滞后 15 天
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    fake = _FakeNetworkFetcher(priority=1)
    manager = DataFetcherManager([fetcher, fake])
    df, source = manager.get_daily_data(
        "600519", start_date="2026-06-01", end_date="2026-06-30"
    )

    assert source == "FakeNetworkFetcher"
    assert len(fake.calls) == 1
    assert not df.empty


def test_fresh_local_within_stale_threshold_served_locally(tmp_path, monkeypatch):
    """最新 bar 落后 8 天（< 10，模拟长假）→ 本地源服务，不调用网络源。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    dates = _consecutive_dates(date(2026, 6, 22), 15)  # 最新 bar 06-22，end 06-30，滞后 8 天
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    fake = _FakeNetworkFetcher(priority=1)
    manager = DataFetcherManager([fetcher, fake])
    df, source = manager.get_daily_data(
        "600519", start_date="2026-06-08", end_date="2026-06-30"
    )

    assert source == "TdxLocalFetcher"
    assert fake.calls == []
    assert len(df) == 15


def test_stale_boundary_exactly_10_days_served_locally(tmp_path, monkeypatch):
    """最新 bar 落后恰 10 天 → 不回退（D5 用 > 不含等号，固化边界）。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    dates = _consecutive_dates(date(2026, 6, 20), 15)  # 最新 bar 06-20，end 06-30，滞后恰 10 天
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    fake = _FakeNetworkFetcher(priority=1)
    manager = DataFetcherManager([fetcher, fake])
    df, source = manager.get_daily_data(
        "600519", start_date="2026-06-06", end_date="2026-06-30"
    )

    assert source == "TdxLocalFetcher"
    assert fake.calls == []
    assert len(df) == 15


def test_stale_threshold_env_override(tmp_path, monkeypatch):
    """TDX_LOCAL_MAX_STALE_DAYS=2 时 8 天旧的本地数据也回退网络源。"""
    from data_provider.tdx_local_fetcher import TdxLocalFetcher

    vipdoc = tmp_path / "vipdoc"
    (vipdoc / "sh" / "lday").mkdir(parents=True, exist_ok=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TDX_LOCAL_PATH", str(tmp_path))
    monkeypatch.delenv("TDX_LOCAL_PRIORITY", raising=False)
    monkeypatch.setenv("TDX_LOCAL_MAX_STALE_DAYS", "2")
    Config.reset_instance()
    fetcher = TdxLocalFetcher()

    dates = _consecutive_dates(date(2026, 6, 22), 15)  # 最新 bar 06-22，end 06-30，滞后 8 天
    _write_day_file(vipdoc / "sh" / "lday" / "sh600519.day", _records_for_dates(dates))

    fake = _FakeNetworkFetcher(priority=1)
    manager = DataFetcherManager([fetcher, fake])
    _, source = manager.get_daily_data(
        "600519", start_date="2026-06-08", end_date="2026-06-30"
    )

    assert source == "FakeNetworkFetcher"


def test_zero_stale_threshold_rejects_stale_local(tmp_path, monkeypatch):
    """TDX_LOCAL_MAX_STALE_DAYS=0（config/registry 均允许的合法值）不被替换为默认 10：滞后 3 天即回退。

    OpenReview OR-COR-81538099 回归：旧实现 `配置值 or _DEFAULT_MAX_STALE_DAYS`
    把 0 静默替换为 10，用户要求的"零容忍滞后"失效。
    """
    from data_provider.tdx_local_fetcher import TdxLocalFetcher

    vipdoc = tmp_path / "vipdoc"
    (vipdoc / "sh" / "lday").mkdir(parents=True, exist_ok=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TDX_LOCAL_PATH", str(tmp_path))
    monkeypatch.delenv("TDX_LOCAL_PRIORITY", raising=False)
    monkeypatch.setenv("TDX_LOCAL_MAX_STALE_DAYS", "0")
    Config.reset_instance()
    fetcher = TdxLocalFetcher()
    assert fetcher._max_stale_days == 0  # 合法阈值 0 被保留

    dates = _consecutive_dates(date(2026, 6, 27), 15)  # 最新 bar 06-27，end 06-30，滞后 3 天
    _write_day_file(vipdoc / "sh" / "lday" / "sh600519.day", _records_for_dates(dates))

    fake = _FakeNetworkFetcher(priority=1)
    manager = DataFetcherManager([fetcher, fake])
    _, source = manager.get_daily_data(
        "600519", start_date="2026-06-13", end_date="2026-06-30"
    )

    assert source == "FakeNetworkFetcher"


def test_zero_stale_threshold_still_serves_fresh_local(tmp_path, monkeypatch):
    """阈值 0 时滞后恰 0 天（最新 bar == end_date）仍用本地数据（边界语义不变）。"""
    from data_provider.tdx_local_fetcher import TdxLocalFetcher

    vipdoc = tmp_path / "vipdoc"
    (vipdoc / "sh" / "lday").mkdir(parents=True, exist_ok=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TDX_LOCAL_PATH", str(tmp_path))
    monkeypatch.delenv("TDX_LOCAL_PRIORITY", raising=False)
    monkeypatch.setenv("TDX_LOCAL_MAX_STALE_DAYS", "0")
    Config.reset_instance()
    fetcher = TdxLocalFetcher()

    dates = _consecutive_dates(date(2026, 6, 30), 15)  # 最新 bar == end 06-30，滞后 0 天
    _write_day_file(vipdoc / "sh" / "lday" / "sh600519.day", _records_for_dates(dates))

    fake = _FakeNetworkFetcher(priority=1)
    manager = DataFetcherManager([fetcher, fake])
    df, source = manager.get_daily_data(
        "600519", start_date="2026-06-16", end_date="2026-06-30"
    )

    assert source == "TdxLocalFetcher"
    assert fake.calls == []
    assert len(df) == 15


def test_historical_end_date_uses_end_not_today(tmp_path, monkeypatch):
    """end_date 设为过去且本地覆盖 → 不判过期（回测场景；禁止拿今天当基准）。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    # 本地数据 2026-01-01..01-30：相对"今天"已陈旧数月，但请求窗口的 end_date
    # 是 2026-01-30 且本地覆盖 → 以 end_date 为基准，滞后 0 天，不判过期。
    dates = _consecutive_dates(date(2026, 1, 30), 30)
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    df = fetcher.get_daily_data("600519", start_date="2026-01-01", end_date="2026-01-30")

    assert len(df) == 30


def test_head_gap_returns_empty_to_continue_fallback(tmp_path, monkeypatch, caplog):
    """窗口起点早于本地最早 bar（头部缺口）→ 本源返回空结果，不以部分数据"成功"终止回退。

    OpenReview OR-COR-364fe4b2 回归：旧实现返回窗口内已有行，管理器视作
    成功立即结束回退，网络源没有机会补齐不足历史。
    """
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    dates = _consecutive_dates(date(2026, 1, 30), 11)  # 本地仅 01-20..01-30，窗口 01-01 起
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    with caplog.at_level(logging.WARNING, logger="data_provider.tdx_local_fetcher"):
        df = fetcher.get_daily_data(
            "600519", start_date="2026-01-01", end_date="2026-01-30"
        )

    assert df.empty
    assert any("头部缺口" in record.getMessage() for record in caplog.records)


def test_head_gap_manager_falls_back_to_full_network_window(tmp_path, monkeypatch):
    """本地仅最新 11 根 bar、趋势工具请求 60 天 → 管理器回退网络源拿全窗口 60 天。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    # 本地尾部新鲜（最新 bar == end 06-30，滞后 0 天不判过期），头部只有 11 个日历日
    dates = _consecutive_dates(date(2026, 6, 30), 11)
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    fake = _FullWindowNetworkFetcher(priority=1)
    manager = DataFetcherManager([fetcher, fake])
    df, source = manager.get_daily_data(
        "600519", start_date="2026-05-02", end_date="2026-06-30"
    )

    assert source == "FakeFullNetworkFetcher"
    assert len(df) == 60  # 完整 60 天窗口，而非本地 11 天
    assert len(fake.calls) == 1


def test_missing_day_file_returns_empty_not_raise(tmp_path, monkeypatch):
    """代码无对应 .day 文件 → fetcher 空 df 不抛；管理器继续下一源。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)  # 树存在但不写任何 .day 文件

    df = fetcher.get_daily_data("600519", start_date="2026-01-01", end_date="2026-01-30")
    assert df.empty

    fake = _FakeNetworkFetcher(priority=1)
    manager = DataFetcherManager([fetcher, fake])
    manager_df, source = manager.get_daily_data(
        "600519", start_date="2026-01-01", end_date="2026-01-30"
    )
    assert source == "FakeNetworkFetcher"
    assert not manager_df.empty


def test_empty_result_does_not_trip_circuit_breaker(tmp_path, monkeypatch):
    """连续 4 次空结果后健康探针 _is_daily_source_available 仍 True（D6：空不进熔断）。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)  # 树存在但无 .day 文件 → 每次空结果
    fake = _FakeNetworkFetcher(priority=1)
    manager = DataFetcherManager([fetcher, fake])

    for _ in range(4):
        df, source = manager.get_daily_data(
            "600519", start_date="2026-01-01", end_date="2026-01-30"
        )
        assert source == "FakeNetworkFetcher"

    # 熔断探针用 _is_daily_source_available（查 _daily_source_health，base.py:848-859），
    # 不是 fetcher 层的 is_available_for_request（critic 修正项 3）。
    assert DataFetcherManager._is_daily_source_available(fetcher, "cn") is True


def test_path_is_file_not_dir_not_registered(monkeypatch, tmp_path):
    """TDX_LOCAL_PATH 指向普通文件 → 不注册（D4 门槛 a 要求目录）。"""
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("TDX_LOCAL_PATH", str(file_path))
    Config.reset_instance()
    manager = DataFetcherManager()
    assert "TdxLocalFetcher" not in manager.available_fetchers


def test_unreadable_dir_returns_empty(tmp_path, monkeypatch):
    """目录存在但无 sh/lday 结构（Windows 下模拟内容损坏）→ 空结果、回退网络源。"""
    from data_provider.tdx_local_fetcher import TdxLocalFetcher

    bare = tmp_path / "broken_tdx"
    bare.mkdir()  # 存在但内部无 sh/lday，resolve_vipdoc_root 应返回 None
    monkeypatch.setenv("TDX_LOCAL_PATH", str(bare))
    Config.reset_instance()
    fetcher = TdxLocalFetcher()

    df = fetcher.get_daily_data("600519", start_date="2026-01-01", end_date="2026-01-30")
    assert df.empty

    fake = _FakeNetworkFetcher(priority=1)
    manager = DataFetcherManager([fetcher, fake])
    _, source = manager.get_daily_data(
        "600519", start_date="2026-01-01", end_date="2026-01-30"
    )
    assert source == "FakeNetworkFetcher"


def test_corrupt_records_skipped_not_fatal(tmp_path, monkeypatch):
    """文件中段夹一条 date=0 脏记录 → 其余行正常返回（R3 fetcher 级集成）。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    dates = _consecutive_dates(date(2026, 6, 5), 5)  # 06-01..06-05 共 5 条有效
    records = _records_for_dates(dates)
    dirty = _pack_record(0, 10.0, 10.5, 9.8, 10.3, 1000.0, 100)  # date=0 脏记录
    corrupted = records[:2] + [dirty] + records[2:]
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        corrupted,
    )

    df = fetcher.get_daily_data("600519", start_date="2026-06-01", end_date="2026-06-05")

    assert len(df) == 5
    assert df["date"].is_monotonic_increasing
    assert df["close"].notna().all()


@pytest.mark.skipif(os.name != "nt", reason="缺盘符路径语义仅在 Windows 可模拟")
def test_nonexistent_drive_graceful(monkeypatch):
    """TDX_LOCAL_PATH 指向不存在盘符 → 不注册/空结果，不抛 OSError 出管理器边界（R5）。"""
    if Path("Z:/").exists():
        pytest.skip("宿主机存在 Z: 盘，无法模拟缺失盘符")

    monkeypatch.setenv("TDX_LOCAL_PATH", "Z:\\nonexistent\\vipdoc")
    Config.reset_instance()
    manager = DataFetcherManager()  # 注册门槛 is_dir() 为 False，不抛 OSError
    assert "TdxLocalFetcher" not in manager.available_fetchers


def test_start_end_days_combinations_contract(tmp_path, monkeypatch):
    """(start,end) / (days) / (start+days) / (end only) 四组合窗口符合 base.py:467-500 契约。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    today = datetime.now().date()
    dates = _consecutive_dates(today, 41)  # today-40..today 共 41 条
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    def returned_dates(df):
        return [d.date() if hasattr(d, "date") else d for d in df["date"]]

    def expected_window(window_start, window_end):
        span = (window_end - window_start).days
        return [window_end - timedelta(days=offset) for offset in range(span, -1, -1)]

    # A: (start, end)
    start_a = today - timedelta(days=20)
    end_a = today - timedelta(days=5)
    df = fetcher.get_daily_data(
        "600519", start_date=start_a.isoformat(), end_date=end_a.isoformat()
    )
    assert returned_dates(df) == expected_window(start_a, end_a)

    # B: (days=5) → end=今天、start=今天-10（days*2 日历日）
    df = fetcher.get_daily_data("600519", days=5)
    assert returned_dates(df) == expected_window(today - timedelta(days=10), today)

    # C: (start + days) → start 已给，days 不参与默认推导，end=今天
    start_c = today - timedelta(days=20)
    df = fetcher.get_daily_data("600519", start_date=start_c.isoformat(), days=5)
    assert returned_dates(df) == expected_window(start_c, today)

    # D: (end only) → end 已给、start=end-days*2
    end_d = today - timedelta(days=5)
    df = fetcher.get_daily_data("600519", end_date=end_d.isoformat(), days=5)
    assert returned_dates(df) == expected_window(end_d - timedelta(days=10), end_d)


def test_non_trading_day_end_date(tmp_path, monkeypatch):
    """end_date 为周日、本地最新 bar 为周五 → 滞后 2 天 ≤ N，不判过期（R12）。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    # 2026-01-05(周一)..2026-01-09(周五) 共 5 条；end_date=2026-01-11(周日)
    dates = _consecutive_dates(date(2026, 1, 9), 5)
    assert dates[0] == date(2026, 1, 5)
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    # 窗口起点取本地最早 bar（头部完整性语义独立于过期判定：起点早于本地最早
    # bar 属头部缺口，走 OR-COR-364fe4b2 的空结果回退路径，与本例无关）。
    df = fetcher.get_daily_data("600519", start_date="2026-01-05", end_date="2026-01-11")

    assert len(df) == 5
    assert df["date"].iloc[-1] == pd.Timestamp("2026-01-09")
