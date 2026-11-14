# -*- coding: utf-8 -*-
"""
Unit tests for the pure TDX local `.day` binary daily-line parser.

All fixtures are synthetic (`struct.pack`) written into ``tmp_path``: zero
network, zero real TDX installation dependency.
"""

import logging
import struct

import pandas as pd
import pytest

from data_provider.tdx_day_parser import (
    DAY_RECORD_STRUCT,
    build_vipdoc_day_path,
    parse_day_file,
    resolve_vipdoc_root,
)

pytestmark = pytest.mark.unit

# Independent copy of the record layout so the tests stay decoupled from the
# module constant under test:
#   date(u32 YYYYMMDD) + open/high/low/close(u32 price*100)
#   + amount(f32 yuan) + volume(u32 shares) + reserved(u32, ignored)
_DAY_RECORD_FMT = "<IIIIIfII"
_PARSER_LOGGER = "data_provider.tdx_day_parser"

# (date, open, high, low, close [price*100], amount [yuan], volume [shares])
_DEFAULT_ROWS = [
    (20260105, 1050, 1100, 1040, 1080, 1250000.5, 300000),
    (20260106, 1080, 1120, 1070, 1110, 987654.25, 250000),
    (20260107, 1110, 1150, 1100, 1140, 1500000.75, 410000),
]


def _pack_day_record(date, o, h, low, c, amount, volume, reserved=0):
    return struct.pack(_DAY_RECORD_FMT, date, o, h, low, c, amount, volume, reserved)


def _default_records():
    return [_pack_day_record(*row) for row in _DEFAULT_ROWS]


def _write_day_file(tmp_path, payload, name="sh600519.day"):
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def test_day_record_struct_is_32_bytes():
    """The record layout must be exactly the 32-byte TDX .day record."""
    assert struct.calcsize(DAY_RECORD_STRUCT) == 32
    assert DAY_RECORD_STRUCT == _DAY_RECORD_FMT


def test_parse_synthetic_fixture_roundtrip(tmp_path):
    path = _write_day_file(tmp_path, b"".join(_default_records()))
    df = parse_day_file(path)
    assert df is not None
    assert len(df) == 3
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert list(df["date"].dt.strftime("%Y%m%d")) == ["20260105", "20260106", "20260107"]
    assert df["date"].is_monotonic_increasing


def test_prices_converted_to_yuan(tmp_path):
    path = _write_day_file(tmp_path, b"".join(_default_records()))
    df = parse_day_file(path)
    assert df["open"].tolist() == pytest.approx([10.50, 10.80, 11.10], abs=1e-9)
    assert df["high"].tolist() == pytest.approx([11.00, 11.20, 11.50], abs=1e-9)
    assert df["low"].tolist() == pytest.approx([10.40, 10.70, 11.00], abs=1e-9)
    assert df["close"].tolist() == pytest.approx([10.80, 11.10, 11.40], abs=1e-9)


def test_volume_shares_and_amount_yuan_types(tmp_path):
    path = _write_day_file(tmp_path, b"".join(_default_records()))
    df = parse_day_file(path)
    assert pd.api.types.is_integer_dtype(df["volume"])
    assert (df["volume"] >= 0).all()
    assert df["volume"].tolist() == [300000, 250000, 410000]
    # f32 amount: compare with relative tolerance (f32 precision limit)
    assert df["amount"].tolist() == pytest.approx([1250000.5, 987654.25, 1500000.75], rel=1e-6)


def test_reserved_field_ignored(tmp_path):
    dirty = struct.pack(_DAY_RECORD_FMT, *_DEFAULT_ROWS[0], 0xDEADBEEF)
    df_dirty = parse_day_file(_write_day_file(tmp_path, dirty, name="dirty.day"))
    df_clean = parse_day_file(_write_day_file(tmp_path, _default_records()[0], name="clean.day"))
    pd.testing.assert_frame_equal(df_dirty, df_clean)


def test_empty_file_returns_empty_df(tmp_path):
    path = _write_day_file(tmp_path, b"")
    df = parse_day_file(path)
    assert df is not None
    assert df.empty
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]


def test_truncated_tail_dropped_with_warning(tmp_path, caplog):
    records = _default_records()
    payload = b"".join(records[:2]) + records[0][:16]  # 2.5 records = 80 bytes
    path = _write_day_file(tmp_path, payload)
    with caplog.at_level(logging.WARNING, logger=_PARSER_LOGGER):
        df = parse_day_file(path)
    assert df is not None
    assert len(df) == 2
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a truncation warning to be logged"
    assert any("truncated" in r.getMessage().lower() for r in warnings)


def test_invalid_rows_filtered(tmp_path, caplog):
    valid_1 = _pack_day_record(20260105, 1050, 1100, 1040, 1080, 100.0, 1000)
    zero_date = _pack_day_record(0, 1050, 1100, 1040, 1080, 100.0, 1000)
    zero_close = _pack_day_record(20260106, 1050, 1100, 1040, 0, 100.0, 1000)
    # 3,000,000 yuan: above the sane upper bound of 1,000,000 yuan
    crazy_price = _pack_day_record(20260107, 300000000, 300000001, 299999999, 300000000, 100.0, 1000)
    valid_2 = _pack_day_record(20260108, 1050, 1100, 1040, 1080, 100.0, 1000)
    path = _write_day_file(tmp_path, valid_1 + zero_date + zero_close + crazy_price + valid_2)
    with caplog.at_level(logging.WARNING, logger=_PARSER_LOGGER):
        df = parse_day_file(path)
    assert df is not None
    assert list(df["date"].dt.strftime("%Y%m%d")) == ["20260105", "20260108"]
    invalid_warnings = [
        r for r in caplog.records if r.levelno == logging.WARNING and "invalid" in r.getMessage().lower()
    ]
    assert invalid_warnings, "expected an invalid-record warning to be logged"


def test_invalid_nonzero_date_row_dropped(tmp_path, caplog):
    """A nonzero but impossible date (e.g. 20269999) is a dirty record: dropped
    with a warning while the remaining rows survive (D9) -- never an uncaught
    ValueError from pd.to_datetime."""
    valid_1 = _pack_day_record(20260105, 1050, 1100, 1040, 1080, 100.0, 1000)
    bad_date = _pack_day_record(20269999, 1050, 1100, 1040, 1080, 100.0, 1000)
    valid_2 = _pack_day_record(20260108, 1050, 1100, 1040, 1080, 100.0, 1000)
    path = _write_day_file(tmp_path, valid_1 + bad_date + valid_2)
    with caplog.at_level(logging.WARNING, logger=_PARSER_LOGGER):
        df = parse_day_file(path)
    assert df is not None
    assert list(df["date"].dt.strftime("%Y%m%d")) == ["20260105", "20260108"]
    invalid_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "invalid" in r.getMessage().lower()
    ]
    assert invalid_warnings, "expected an invalid-record warning to be logged"


def test_bare_code_rejects_non_numeric(tmp_path):
    """A code that is not exactly 6 digits after prefix/suffix stripping returns
    None so no path separator can escape the lday directory; the caller maps
    None to an empty frame and falls back to the network source."""
    root = tmp_path / "vipdoc"
    # Forward-slash traversal attempt must not resolve inside lday
    assert build_vipdoc_day_path(root, "6005/../../etc") is None
    # Backslash traversal attempt (Windows-style) ditto
    assert build_vipdoc_day_path(root, "6005\\..\\..\\etc") is None
    # Bare numerics that are not 6 digits are rejected as well
    assert build_vipdoc_day_path(root, "60051") is None
    assert build_vipdoc_day_path(root, "43004711") is None
    # Prefix style resolves only when the stripped code is 6 digits
    assert build_vipdoc_day_path(root, "SH.600X19") is None
    assert build_vipdoc_day_path(root, "SH600519") == root / "sh" / "lday" / "sh600519.day"


def test_parse_day_file_missing_returns_none(tmp_path):
    assert parse_day_file(tmp_path / "does_not_exist.day") is None


def test_build_vipdoc_day_path_markets(tmp_path):
    root = tmp_path / "vipdoc"
    assert build_vipdoc_day_path(root, "600519") == root / "sh" / "lday" / "sh600519.day"
    assert build_vipdoc_day_path(root, "688981") == root / "sh" / "lday" / "sh688981.day"
    assert build_vipdoc_day_path(root, "000001") == root / "sz" / "lday" / "sz000001.day"
    assert build_vipdoc_day_path(root, "300750") == root / "sz" / "lday" / "sz300750.day"
    assert build_vipdoc_day_path(root, "002415") == root / "sz" / "lday" / "sz002415.day"
    # Explicit prefix styles (see plan D8)
    assert build_vipdoc_day_path(root, "SH.600519") == root / "sh" / "lday" / "sh600519.day"
    assert build_vipdoc_day_path(root, "SS600519") == root / "sh" / "lday" / "sh600519.day"
    assert build_vipdoc_day_path(root, "SZ000001") == root / "sz" / "lday" / "sz000001.day"
    # Explicit suffix styles (D8: both styles must be supported)
    assert build_vipdoc_day_path(root, "600519.SH") == root / "sh" / "lday" / "sh600519.day"
    assert build_vipdoc_day_path(root, "000001.SZ") == root / "sz" / "lday" / "sz000001.day"


def test_resolve_vipdoc_root_auto_descend(tmp_path):
    vipdoc = tmp_path / "vipdoc"
    (vipdoc / "sh" / "lday").mkdir(parents=True)
    # TDX install root: descend one level into vipdoc/
    assert resolve_vipdoc_root(tmp_path) == vipdoc
    # Already a vipdoc root: returned as-is
    assert resolve_vipdoc_root(vipdoc) == vipdoc
    # Neither: None
    assert resolve_vipdoc_root(tmp_path / "empty") is None


def test_unicode_and_space_path_supported(tmp_path):
    target = tmp_path / "通达信 数据" / "sh"
    target.mkdir(parents=True)
    path = target / "sh600519.day"
    path.write_bytes(b"".join(_default_records()))
    df = parse_day_file(path)
    assert df is not None
    assert len(df) == 3
