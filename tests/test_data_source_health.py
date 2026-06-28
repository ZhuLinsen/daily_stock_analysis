# -*- coding: utf-8 -*-
"""数据源健康追踪（src/services/data_source_health.py）单元测试。"""

import pytest

from src.services import data_source_health as dsh


@pytest.fixture(autouse=True)
def _reset_tracker():
    dsh.reset()
    yield
    dsh.reset()


def test_no_outcomes_means_no_warning():
    assert dsh.summarize_collective_failures() == []
    assert dsh.format_health_warning("zh") == ""


def test_all_success_is_not_collective_failure():
    dsh.record_market_data_outcome("cn", True)
    dsh.record_market_data_outcome("cn", True)
    assert dsh.summarize_collective_failures() == []
    assert dsh.format_health_warning("zh") == ""


def test_mixed_success_and_failure_is_not_collective_failure():
    # 个别股票失败但市场整体有成功 -> 视为单票问题，不告警
    dsh.record_market_data_outcome("cn", True)
    dsh.record_market_data_outcome("cn", False)
    assert dsh.summarize_collective_failures() == []
    assert dsh.format_health_warning("zh") == ""


def test_zero_success_with_failures_is_collective_failure():
    dsh.record_market_data_outcome("cn", False)
    dsh.record_market_data_outcome("cn", False)
    failures = dsh.summarize_collective_failures()
    assert failures == [{"market": "cn", "attempts": 2, "failures": 2}]


def test_warning_text_lists_only_collectively_failed_markets():
    dsh.record_market_data_outcome("cn", False)  # 集体失效
    dsh.record_market_data_outcome("us", True)   # 正常
    dsh.record_market_data_outcome("us", False)  # 个别失败但有成功
    warning_zh = dsh.format_health_warning("zh")
    assert "A股" in warning_zh
    assert "美股" not in warning_zh
    assert "TUSHARE_TOKEN" in warning_zh


def test_warning_text_english():
    dsh.record_market_data_outcome("us", False)
    warning_en = dsh.format_health_warning("en")
    assert "US" in warning_en
    assert "FINNHUB_API_KEY" in warning_en


def test_reset_clears_state():
    dsh.record_market_data_outcome("hk", False)
    assert dsh.summarize_collective_failures()
    dsh.reset()
    assert dsh.summarize_collective_failures() == []


def test_empty_market_is_ignored():
    dsh.record_market_data_outcome("", False)
    assert dsh.summarize_collective_failures() == []
