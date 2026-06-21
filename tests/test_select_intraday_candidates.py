import importlib.util
from pathlib import Path
import sys

import pandas as pd
import pytest


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "select_intraday_candidates.py"
SPEC = importlib.util.spec_from_file_location("select_intraday_candidates", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _market_frame(size=20):
    return pd.DataFrame(
        {
            "代码": [f"600{i:03d}" for i in range(size)],
            "名称": [f"测试股份{i}" for i in range(size)],
            "最新价": [10 + i for i in range(size)],
            "涨跌幅": [float(1 + (i % 5)) for i in range(size)],
            "成交额": [100_000_000 + i * 20_000_000 for i in range(size)],
            "换手率": [1 + (i % 8) for i in range(size)],
            "量比": [1 + (i % 4) * 0.5 for i in range(size)],
            "涨速": [i / 100 for i in range(size)],
        }
    )


def test_selects_requested_count_and_orders_by_score():
    selected = MODULE.select_candidates(_market_frame(), count=10)

    assert len(selected) == 10
    assert len({item.code for item in selected}) == 10
    assert [item.score for item in selected] == sorted(
        [item.score for item in selected], reverse=True
    )


def test_filters_st_and_limit_up_candidates():
    frame = _market_frame(15)
    frame.loc[14, "名称"] = "*ST测试"
    frame.loc[14, "成交额"] = 9_999_999_999
    frame.loc[13, "涨跌幅"] = 9.8
    frame.loc[13, "成交额"] = 8_999_999_999

    selected = MODULE.select_candidates(frame, count=10)

    assert "*ST测试" not in {item.name for item in selected}
    assert "600013" not in {item.code for item in selected}


def test_raises_when_not_enough_liquid_candidates():
    frame = _market_frame(5)
    frame["成交额"] = 1_000_000

    with pytest.raises(RuntimeError, match="不足 10 支"):
        MODULE.select_candidates(frame, count=10)


def test_market_snapshot_falls_back_after_primary_failure():
    calls = []

    def broken_source():
        calls.append("primary")
        raise ConnectionError("remote disconnected")

    def backup_source():
        calls.append("backup")
        return _market_frame()

    result = MODULE.fetch_market_snapshot(
        [("primary", broken_source), ("backup", backup_source)],
        attempts=1,
    )

    assert len(result) == 20
    assert calls == ["primary", "backup"]


def test_sina_style_columns_use_neutral_missing_metrics():
    frame = _market_frame().rename(
        columns={
            "代码": "symbol",
            "名称": "name",
            "最新价": "trade",
            "涨跌幅": "changepercent",
            "成交额": "amount",
            "换手率": "turnoverratio",
        }
    ).drop(columns=["量比", "涨速"])

    selected = MODULE.select_candidates(frame, count=10)

    assert len(selected) == 10
    assert all(item.volume_ratio == 1.0 for item in selected)
