# -*- coding: utf-8 -*-
"""
===================================
TDX .day parser - 通达信本地日线二进制解析（纯函数模块）
===================================

解析通达信 ``vipdoc/<market>/lday/<market><code>.day`` 二进制日线文件。
本模块是零依赖纯解析层：不依赖 ``data_provider.base``（无 BaseFetcher 契约）、
不读配置、不发网络请求，可独立单测。

二进制格式（每条记录 32 字节，小端 ``<IIIIIfII``）：
    date     u32  YYYYMMDD
    open     u32  价格 × 100
    high     u32  价格 × 100
    low      u32  价格 × 100
    close    u32  价格 × 100
    amount   f32  成交额（元，f32 有精度限制）
    volume   u32  成交量（股）
    reserved u32  保留字段，忽略

约定：
1. 价格 ÷ 100 转元（float）；volume 保持股（int64）；amount 为元（float）。
2. 尾部不足 32 字节的截断记录丢弃 + warning。
3. 脏记录（date=0 / date 非法日历日期 / close=0 / 价格超合理上界）过滤 + warning，
   不影响其余行（D9）。
4. 文件缺失返回 None（由 fetcher 层映射为空 DataFrame）；非法股票代码（剥离市场
   前后缀后非 6 位纯数字，含路径分隔符逃逸企图）同样返回 None 走网络回退。
"""

from __future__ import annotations

import datetime
import logging
import struct
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# 单条 .day 记录的小端布局：date + OHLC + amount + volume + reserved
DAY_RECORD_STRUCT = "<IIIIIfII"
DAY_RECORD_SIZE = struct.calcsize(DAY_RECORD_STRUCT)
assert DAY_RECORD_SIZE == 32, f"unexpected TDX .day record size: {DAY_RECORD_SIZE}"

# 单列价格合理上界（元）：超过视为脏数据（见计划 D9）
_MAX_SANE_PRICE_YUAN = 1_000_000.0

# 输出 DataFrame 列（date/open/high/low/close/volume/amount）
_OUTPUT_COLUMNS = ("date", "open", "high", "low", "close", "volume", "amount")

# 显式市场前缀（大写；长前缀在前，避免 "SH." 被 "SH" 先截断）
_CODE_PREFIX_MARKET: Tuple[Tuple[str, str], ...] = (
    ("SH.", "sh"),
    ("SZ.", "sz"),
    ("SS.", "sh"),
    ("SH", "sh"),
    ("SZ", "sz"),
    ("SS", "sh"),
)
# 显式市场后缀
_CODE_SUFFIX_MARKET: Tuple[Tuple[str, str], ...] = (
    (".SH", "sh"),
    (".SS", "sh"),
    (".SZ", "sz"),
)


def _split_market_and_code(stock_code: str) -> Tuple[str, str]:
    """
    把股票代码归一为 ``(market, bare_code)``，market 为 ``"sh"``/``"sz"``。

    支持 PytdxFetcher._get_market_code 同款的显式前缀（``SH.``/``SS.``/``SZ.``/
    ``SH``/``SS``/``SZ``）与后缀（``.SH``/``.SS``/``.SZ``）两种风格；裸 6 位码
    按 ``60``/``68`` 开头归 sh、其余（00/30/002 等）归 sz。
    """
    code = str(stock_code).strip().upper()
    for prefix, market in _CODE_PREFIX_MARKET:
        if code.startswith(prefix):
            return market, code[len(prefix):]
    for suffix, market in _CODE_SUFFIX_MARKET:
        if code.endswith(suffix):
            return market, code[: -len(suffix)]
    market = "sh" if code[:2] in ("60", "68") else "sz"
    return market, code


def _is_valid_yyyymmdd(date: int) -> bool:
    """
    判断 ``YYYYMMDD`` 整数是否为真实存在的日历日期。

    另限定 1900-2100 年份窗：既挡住 20269999 这类不可能日期，也保证后续
    ``pd.to_datetime`` 不会因越界年份（Timestamp ns 表示范围 1677-2262）抛错。
    """
    year, month, day = date // 10000, (date // 100) % 100, date % 100
    if not 1900 <= year <= 2100:
        return False
    try:
        datetime.date(year, month, day)
    except ValueError:
        return False
    return True


def _empty_day_frame() -> pd.DataFrame:
    """空结果 DataFrame（含全部输出列名与稳定 dtype）。"""
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "open": pd.Series(dtype="float64"),
            "high": pd.Series(dtype="float64"),
            "low": pd.Series(dtype="float64"),
            "close": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="int64"),
            "amount": pd.Series(dtype="float64"),
        }
    )


def parse_day_file(path) -> Optional[pd.DataFrame]:
    """
    解析单个通达信 ``.day`` 日线文件。

    返回含 ``date/open/high/low/close/volume/amount`` 列的 DataFrame（按文件
    顺序、即时间升序保持）；路径为 ``None``（见 ``build_vipdoc_day_path``）、
    文件缺失/不可读返回 ``None``；空文件或全部记录无效时返回空 DataFrame。
    """
    if path is None:
        return None

    file_path = Path(path)
    if not file_path.is_file():
        logger.debug("TDX .day file not found: %s", file_path)
        return None

    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        logger.warning("TDX .day file unreadable: %s (%s)", file_path, exc)
        return None

    record_count, trailing = divmod(len(raw), DAY_RECORD_SIZE)
    if trailing:
        logger.warning(
            "TDX .day file %s has a truncated tail: %d trailing byte(s) do not form a "
            "complete %d-byte record; truncated record dropped",
            file_path,
            trailing,
            DAY_RECORD_SIZE,
        )
    if record_count == 0:
        return _empty_day_frame()

    dates = []
    opens = []
    highs = []
    lows = []
    closes = []
    volumes = []
    amounts = []
    invalid_rows = []

    for index in range(record_count):
        date, o, h, low, c, amount, volume, _reserved = struct.unpack_from(
            DAY_RECORD_STRUCT, raw, index * DAY_RECORD_SIZE
        )
        reasons = []
        if date == 0:
            reasons.append("date=0")
        elif not _is_valid_yyyymmdd(date):
            reasons.append(f"date={date} not a valid calendar date")
        if c == 0:
            reasons.append("close=0")
        if max(o, h, low, c) / 100.0 > _MAX_SANE_PRICE_YUAN:
            reasons.append("price above sane upper bound")
        if reasons:
            invalid_rows.append((index, "; ".join(reasons)))
            continue
        dates.append(date)
        opens.append(o / 100.0)
        highs.append(h / 100.0)
        lows.append(low / 100.0)
        closes.append(c / 100.0)
        volumes.append(int(volume))
        amounts.append(float(amount))

    if invalid_rows:
        logger.warning(
            "TDX .day file %s: skipped %d invalid record(s) at row index(es) %s",
            file_path,
            len(invalid_rows),
            invalid_rows,
        )

    if not dates:
        return _empty_day_frame()

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(pd.Series(dates).astype(str), format="%Y%m%d"),
            "open": pd.Series(opens, dtype="float64"),
            "high": pd.Series(highs, dtype="float64"),
            "low": pd.Series(lows, dtype="float64"),
            "close": pd.Series(closes, dtype="float64"),
            "volume": pd.Series(volumes, dtype="int64"),
            "amount": pd.Series(amounts, dtype="float64"),
        }
    )
    return frame[list(_OUTPUT_COLUMNS)]


def build_vipdoc_day_path(vipdoc_root, stock_code: str) -> Optional[Path]:
    """
    由 vipdoc 根目录与股票代码得到 ``<market>/lday/<market><code>.day`` 路径。

    市场判定规则见 ``_split_market_and_code``；不检查文件是否存在。股票代码
    剥离显式市场前/后缀后必须恰为 6 位纯数字（防 ``/``、``\\`` 等分隔符逃逸
    ``lday`` 目录，北交所 8 位码等同样拒绝）；不满足时返回 ``None``，由调用方
    映射为空 DataFrame 走网络回退。
    """
    market, code = _split_market_and_code(stock_code)
    if not (len(code) == 6 and code.isdigit()):
        logger.debug(
            "TDX vipdoc path rejected unsafe stock code %r (stripped to %r)", stock_code, code
        )
        return None
    return Path(vipdoc_root) / market / "lday" / f"{market}{code}.day"


def resolve_vipdoc_root(path) -> Optional[Path]:
    """
    自动识别 TDX 本地根目录：既接受 TDX 安装根（其下有 ``vipdoc/``），也接受
    vipdoc 目录本身（其下有 ``sh/lday`` 或 ``sz/lday``）。

    两者皆非时返回 None。
    """
    root = Path(path)
    for market in ("sh", "sz"):
        if (root / market / "lday").is_dir():
            return root
    for market in ("sh", "sz"):
        if (root / "vipdoc" / market / "lday").is_dir():
            return root / "vipdoc"
    return None
