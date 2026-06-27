# -*- coding: utf-8 -*-

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from data_provider.ths_provider import THSProvider


@pytest.fixture()
def local_timezone(monkeypatch):
    original = os.environ.get("TZ")

    def set_timezone(value: str) -> None:
        monkeypatch.setenv("TZ", value)
        if hasattr(time, "tzset"):
            time.tzset()

    yield set_timezone

    if original is None:
        monkeypatch.delenv("TZ", raising=False)
    else:
        monkeypatch.setenv("TZ", original)
    if hasattr(time, "tzset"):
        time.tzset()


def _shanghai_ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    dt = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(dt.timestamp() * 1000)


def test_fuyao_kline_ms_timestamp_uses_shanghai_exchange_date(local_timezone) -> None:
    local_timezone("UTC")
    rows = THSProvider._normalize_kline_items(
        [
            {
                "date_ms": _shanghai_ms(2026, 6, 27),
                "open": 10.0,
                "high": 10.8,
                "low": 9.8,
                "close": 10.5,
                "volume": 10000,
            }
        ]
    )

    assert rows[0]["date"] == "2026-06-27"


def test_fuyao_kline_explicit_trade_date_wins_over_timestamp(local_timezone) -> None:
    local_timezone("UTC")
    rows = THSProvider._normalize_kline_items(
        [
            {
                "trade_date": "2026-06-27",
                "timestamp": _shanghai_ms(2026, 6, 26),
                "open_price": 10.0,
                "high_price": 10.8,
                "low_price": 9.8,
                "close_price": 10.5,
            }
        ]
    )

    assert rows[0]["date"] == "2026-06-27"


def test_fuyao_kline_numeric_yyyymmdd_date_is_not_treated_as_epoch(local_timezone) -> None:
    local_timezone("UTC")
    rows = THSProvider._normalize_kline_items(
        [
            {
                "date": 20260627,
                "open": 10.0,
                "high": 10.8,
                "low": 9.8,
                "close": 10.5,
            }
        ]
    )

    assert rows[0]["date"] == "2026-06-27"


def test_fuyao_provider_timestamp_is_shanghai_time(local_timezone) -> None:
    local_timezone("UTC")

    assert THSProvider._timestamp_to_iso(_shanghai_ms(2026, 6, 27)) == "2026-06-27T00:00:00+08:00"
