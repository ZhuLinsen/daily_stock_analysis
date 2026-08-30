#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate Stock Index from CSV File

Input:
  - Tushare format: data/stock_list_{a,hk,us}.csv
  - Seed format: scripts/stock_index_seeds/stock_list_{jp,kr}.csv
  - AkShare format: logs/stock_basic_*.csv

Output: apps/dsa-web/public/stocks.index.json

Usage:
    python scripts/generate_index_from_csv.py              # 默认使用 Tushare
    python scripts/generate_index_from_csv.py --source akshare
    python scripts/generate_index_from_csv.py --test       # 测试模式
    python scripts/generate_index_from_csv.py --index-only --test  # 仅合并指数 seed
"""

import argparse
import csv
import json
import math
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add the project root to sys.path.
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.stock_index_remote_service import validate_stock_index_payload

try:
    from pypinyin import lazy_pinyin, Style
    PYPINYIN_AVAILABLE = True
except ImportError:
    lazy_pinyin = None
    Style = None
    PYPINYIN_AVAILABLE = False


def require_pypinyin() -> bool:
    """Ensure pypinyin is available before generating autocomplete assets."""
    if PYPINYIN_AVAILABLE:
        return True

    print("[Error] pypinyin not available; cannot generate stock autocomplete index.")
    print("[Info] Install dependencies with: pip install -r requirements.txt")
    return False


def load_csv_data(csv_path: Path) -> List[Dict[str, Any]]:
    """
    Load stock data from AkShare format CSV file

    Args:
        csv_path: CSV file path

    Returns:
        List of stock data
    """
    stocks = []

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        for row in reader:
            ts_code = row['ts_code'].strip()
            symbol = row['symbol'].strip()
            name = row['name'].strip()

            # Skip invalid rows.
            if not ts_code or not symbol or not name:
                continue

            stocks.append({
                'ts_code': ts_code,
                'symbol': symbol,
                'name': name,
                'area': row.get('area', ''),
                'industry': row.get('industry', ''),
                'list_date': row.get('list_date', ''),
            })

    return stocks


def load_tushare_data(data_dir: Path) -> List[Dict[str, Any]]:
    """
    从 Tushare CSV 文件加载多市场股票数据

    Args:
        data_dir: 数据目录路径

    Returns:
        合并后的股票列表
    """
    all_stocks = []
    seed_dir = Path(__file__).parent / 'stock_index_seeds'
    default_data_dir = Path(__file__).parent.parent / 'data'
    use_seed_fallback = data_dir.resolve() == default_data_dir.resolve()

    def _csv_path(file_name: str) -> Path:
        data_path = data_dir / file_name
        if data_path.exists() or not use_seed_fallback:
            return data_path
        return seed_dir / file_name

    market_files = {
        'CN': data_dir / 'stock_list_a.csv',
        'HK': data_dir / 'stock_list_hk.csv',
        'US': data_dir / 'stock_list_us.csv',
        'JP': _csv_path('stock_list_jp.csv'),
        'KR': _csv_path('stock_list_kr.csv'),
    }

    for market_name, csv_file in market_files.items():
        if not csv_file.exists():
            print(f"[Warning] 未找到文件：{csv_file}")
            continue

        print(f"  正在读取 {market_name} 市场数据：{csv_file.name}")

        try:
            file_stocks = []
            selected_us_stocks: Dict[str, tuple[Dict[str, Any], int]] = {}
            with open(csv_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)

                for row in reader:
                    # 传入市场参数以优化判断（对于特殊格式如 DUMMY）
                    parsed = parse_stock_row(row, market_name)
                    if not parsed:
                        continue

                    if market_name == 'US':
                        # Tushare us_basic may include historical rows for a reused ticker.
                        # Keep one deterministic row per ts_code before generating the index.
                        delist_priority = get_us_delist_priority(row)
                        existing = selected_us_stocks.get(parsed['ts_code'])
                        if existing is None or delist_priority > existing[1]:
                            selected_us_stocks[parsed['ts_code']] = (parsed, delist_priority)
                        continue

                    if parsed:
                        all_stocks.append(parsed)
                        file_stocks.append(parsed)

            if market_name == 'US':
                file_stocks = [item for item, _priority in selected_us_stocks.values()]
                all_stocks.extend(file_stocks)

            print(f"    ✓ {market_name} 市场读取完成：{len(file_stocks)} 只股票")

        except Exception as e:
            print(f"    [Error] 读取 {csv_file.name} 失败：{e}")

    return all_stocks


def get_us_delist_priority(row: Dict[str, str]) -> int:
    """
    为复用 ticker 的美股记录生成去重优先级。

    Tushare us_basic 导出的 delist_date 对当前记录并不总是稳定：
    - 空字符串通常表示当前仍在使用的 ticker
    - ``NaT`` 多见于历史记录或日期占位值
    - 实际日期表示明确退市

    因此前置去重时优先选择：
    1. delist_date 为空
    2. delist_date 为 NaT
    3. delist_date 为实际日期

    同优先级时保留 CSV 中最先出现的记录，避免在信息不足时随意切换名称。
    """
    delist_date = (row.get('delist_date') or '').strip()
    if not delist_date:
        return 2
    if delist_date.upper() == 'NAT':
        return 1
    return 0


def load_akshare_data(logs_dir: Path) -> List[Dict[str, Any]]:
    """
    从 AkShare CSV 文件加载股票数据

    Args:
        logs_dir: 日志目录路径

    Returns:
        股票列表

    说明：
        AkShare 这条输入路径保留其原始 name 字段，不额外套用
        Tushare A 股那套 XD / XR / DR 状态前缀修正逻辑。这里的目标是
        复用 AkShare 已输出的展示名，而不是对其做二次归一化。
    """
    csv_files = list(logs_dir.glob("stock_basic_*.csv"))

    if not csv_files:
        print("[Error] 未找到 CSV 文件：logs/stock_basic_*.csv")
        return []

    # 使用最新的 CSV 文件
    csv_file = sorted(csv_files)[-1]
    print(f"  正在读取 AkShare 数据：{csv_file.name}")

    stocks = []
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        for row in reader:
            ts_code = row['ts_code'].strip()
            symbol = row['symbol'].strip()
            name = row['name'].strip()

            # Skip invalid rows.
            if not ts_code or not symbol or not name:
                continue

            stocks.append({
                'ts_code': ts_code,
                'symbol': symbol,
                'name': name,
                'area': row.get('area', ''),
                'industry': row.get('industry', ''),
                'list_date': row.get('list_date', ''),
            })

    print(f"    ✓ 共读取 {len(stocks)} 只股票")
    return stocks


def generate_pinyin(name: str) -> tuple:
    """
    Generate pinyin for stock name

    Args:
        name: Stock name

    Returns:
        Tuple of (pinyin_full, pinyin_abbr)
    """
    if not PYPINYIN_AVAILABLE:
        raise RuntimeError("pypinyin is required to generate stock autocomplete index")

    try:
        normalized_name = normalize_name_for_pinyin(name)

        # Full pinyin spelling.
        py_full = lazy_pinyin(normalized_name, style=Style.NORMAL)
        pinyin_full = ''.join(py_full)

        # Pinyin abbreviation.
        py_abbr = lazy_pinyin(normalized_name, style=Style.FIRST_LETTER)
        pinyin_abbr = ''.join(py_abbr)

        return (pinyin_full, pinyin_abbr)
    except Exception as e:
        print(f"[Warning] Failed to generate pinyin for {name}: {e}")
        return (None, None)


def normalize_name_for_pinyin(name: str) -> str:
    """
    Normalize stock name to avoid special prefixes and full-width characters polluting pinyin index

    Args:
        name: Original stock name

    Returns:
        Normalized name for pinyin generation
    """
    normalized = unicodedata.normalize('NFKC', name).strip()

    # Strip common A-share prefixes while preserving the core name.
    normalized = re.sub(r'^(?:\*?ST|N)+', '', normalized, flags=re.IGNORECASE)

    return normalized.strip() or unicodedata.normalize('NFKC', name).strip()


def normalize_stock_name_for_index(name: str, market: str) -> str:
    """
    Normalize stock names before writing the long-lived autocomplete index.

    For A-shares (including BSE), ``XD``/``XR``/``DR`` are
    ex-dividend/ex-rights trading-day prefixes. They should not be stored in
    the official static index because they can become stale almost immediately.
    New-stock prefixes such as ``N``/``C`` and risk-warning prefixes such as
    ``ST``/``*ST`` are preserved; they should be refreshed by the next
    stock-list update.
    """
    normalized = unicodedata.normalize('NFKC', str(name or '')).strip()
    if market in {'CN', 'BSE'}:
        normalized = re.sub(r'^(?:XD|XR|DR)\s*', '', normalized, flags=re.IGNORECASE)
    return normalized.strip()


def extract_symbol_from_ts_code(ts_code: str, market: str) -> Optional[str]:
    """
    从 ts_code 提取 displayCode

    - A股：000001.SZ → 000001
    - 港股：00700.HK → 00700
    - 美股：AAPL → AAPL
    - 日股/韩股：7203.T / 005930.KS → 保留后缀，避免与其他市场裸代码冲突

    Args:
        ts_code: TS代码
        market: 市场代码

    Returns:
        displayCode 或 None
    """
    if not ts_code:
        return None

    if market in {'US', 'JP', 'KR'}:
        # 美股常见 class/share 后缀、日韩 Yahoo 后缀都是代码身份的一部分。
        return ts_code

    if '.' in ts_code:
        # A股和港股：去除后缀
        return ts_code.split('.')[0]

    return ts_code


def get_stock_name(row: Dict[str, str], market: str) -> Optional[str]:
    """
    获取股票名称

    - A股/港股/日股/韩股：使用 name 字段
    - 美股：使用 enname 字段（英文名称）

    Args:
        row: CSV 行数据
        market: 市场代码

    Returns:
        股票名称或 None
    """
    if market == 'US':
        # 美股使用英文名称
        name = row.get('enname', '').strip()
        return name if name else None
    else:
        # A股和港股使用中文名称
        name = row.get('name', '').strip()
        name = normalize_stock_name_for_index(name, market)
        return name if name else None


def parse_aliases(row: Dict[str, str]) -> List[str]:
    """Parse optional seed aliases from a CSV row."""
    raw_aliases = (row.get('aliases') or row.get('alias') or '').strip()
    if not raw_aliases:
        return []

    aliases: List[str] = []
    for alias in re.split(r'[|;,，、]+', raw_aliases):
        normalized = unicodedata.normalize('NFKC', alias).strip()
        if normalized and normalized not in aliases:
            aliases.append(normalized)
    return aliases


def parse_stock_row(row: Dict[str, str], preferred_market: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    解析单行股票数据

    - 美股 DUMMY 过滤（严格过滤）
    - 空值校验
    - 自动判断市场类型（当无法判断时使用 preferred_market）
    - 返回统一格式的字典

    Args:
        row: CSV 行数据
        preferred_market: 当 ts_code 无法判断市场时使用（如美股 DUMMY 记录）

    Returns:
        解析后的股票字典，无效数据返回 None
    """
    ts_code = row.get('ts_code', '').strip()

    if not ts_code:
        return None

    # 自动判断市场类型
    market = determine_market(ts_code)

    # 如果 ts_code 没有后缀（无法准确判断），且提供了 preferred_market，则使用它
    # 这主要用于处理美股的特殊格式（如 DUMMY 记录）
    if '.' not in ts_code and preferred_market:
        market = preferred_market

    # 美股特殊处理：严格过滤 DUMMY 记录
    if market == 'US':
        enname = row.get('enname', '').strip()
        if not enname or 'DUMMY' in enname.upper():
            return None

    # 获取股票名称
    name = get_stock_name(row, market)
    if not name:
        return None

    # 提取 displayCode
    display_code = extract_symbol_from_ts_code(ts_code, market)
    if not display_code:
        return None

    return {
        'ts_code': ts_code,
        'symbol': display_code,
        'name': name,
        'market': market,
        'aliases': parse_aliases(row),
    }


def determine_market(ts_code: str) -> str:
    """
    Determine market based on code

    Args:
        ts_code: Trading code (e.g., 000001.SZ, AAPL, BRK.B, 7203.T, 005930.KS)

    Returns:
        Market code (CN, HK, US, BSE, JP, KR)
    """
    if '.' in ts_code:
        # 有后缀的情况
        suffix = ts_code.split('.')[1]
        # 检查是否为中国市场后缀
        if suffix in ['SH', 'SZ']:
            return 'CN'
        elif suffix == 'HK':
            return 'HK'
        elif suffix == 'BJ':
            return 'BSE'
        elif suffix == 'T':
            return 'JP'
        elif suffix in ['KS', 'KQ']:
            return 'KR'
        # 有后缀但不是中国市场后缀，检查是否为美股
        # 美股可能有点号后缀（如 BRK.B, GOOG.A, AAPL.U）
        prefix = ts_code.split('.')[0]
        if prefix.isalpha():
            return 'US'
    else:
        # 无后缀的情况
        # 纯字母代码为美股
        if ts_code.isalpha():
            return 'US'

    # 默认为 A股
    return 'CN'


def generate_aliases(name: str, market: str) -> List[str]:
    """
    Generate stock aliases

    Args:
        name: Stock name
        market: Market code

    Returns:
        List of aliases
    """
    aliases = []

    # A股常见别名
    cn_alias_map = {
        '贵州茅台': ['茅台'],
        '中国平安': ['平安'],
        '平安银行': ['平银'],
        '招商银行': ['招行'],
        '五粮液': ['五粮'],
        '宁德时代': ['宁德'],
        '比亚迪': ['比亚'],
        '工商银行': ['工行'],
        '建设银行': ['建行'],
        '农业银行': ['农行'],
        '中国银行': ['中行'],
        '交通银行': ['交行'],
        '兴业银行': ['兴业'],
        '浦发银行': ['浦发'],
        '民生银行': ['民生'],
        '中信证券': ['中信'],
        '东方财富': ['东财'],
        '海康威视': ['海康'],
        '隆基绿能': ['隆基'],
        '中国神华': ['神华'],
        '长江电力': ['长电'],
        '中国石化': ['石化'],
        '中国石油': ['石油'],
    }

    # 港股常见别名
    hk_alias_map = {
        '腾讯控股': ['腾讯', 'Tencent'],
        '阿里巴巴-SW': ['阿里', '阿里巴巴', 'Alibaba'],
        '美团-W': ['美团', 'Meituan'],
        '小米集团-W': ['小米', 'Xiaomi'],
        '京东集团-SW': ['京东', 'JD'],
        '网易-S': ['网易', 'NetEase'],
        '百度集团-SW': ['百度', 'Baidu'],
        '中芯国际': ['中芯', 'SMIC'],
        '中国移动': ['中移动', 'China Mobile'],
        '中国海洋石油': ['中海油', 'CNOOC'],
    }

    # 美股常见别名
    us_alias_map = {
        'Apple Inc.': ['Apple', 'AAPL'],
        'Microsoft Corporation': ['Microsoft', 'MSFT'],
        'Amazon.com, Inc.': ['Amazon', 'AMZN'],
        'Tesla Inc.': ['Tesla', 'TSLA'],
        'Meta Platforms, Inc.': ['Meta', 'Facebook', 'META'],
        'Alphabet Inc.': ['Google', 'Alphabet', 'GOOGL'],
        'NVIDIA Corporation': ['NVIDIA', 'NVDA'],
        'Netflix Inc.': ['Netflix', 'NFLX'],
        'Intel Corporation': ['Intel', 'INTC'],
        'Advanced Micro Devices': ['AMD', 'AMD'],
    }

    # 根据市场选择映射表
    if market == 'CN':
        alias_map = cn_alias_map
    elif market == 'HK':
        alias_map = hk_alias_map
    elif market == 'US':
        alias_map = us_alias_map
    else:
        alias_map = {}

    if name in alias_map:
        aliases.extend(alias_map[name])

    return aliases


def build_stock_index(stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build the stock index.

    Args:
        stocks: Raw stock rows（已包含 market 字段）

    Returns:
        Stock index entries
    """
    index = []

    for stock in stocks:
        ts_code = stock['ts_code']
        symbol = stock['symbol']
        name = stock['name']
        market = stock.get('market', 'CN')  # 优先使用已解析的市场，否则从 ts_code 判断

        # 如果没有 market 字段，从 ts_code 判断
        if market == 'CN' and '.' not in ts_code:
            market = determine_market(ts_code)

        # Generate pinyin fields.
        pinyin_full, pinyin_abbr = generate_pinyin(name)

        # Generate aliases.
        aliases = generate_aliases(name, market)
        for alias in stock.get('aliases', []):
            if alias != name and alias not in aliases:
                aliases.append(alias)

        index.append({
            "canonicalCode": ts_code,    # Example: 000001.SZ, AAPL
            "displayCode": symbol,       # Example: 000001, AAPL
            "nameZh": name,
            "pinyinFull": pinyin_full,
            "pinyinAbbr": pinyin_abbr,
            "aliases": aliases,
            "market": market,
            "assetType": "stock",
            "active": True,
            "popularity": 100,
        })

    return index


def compress_index(index: List[Dict[str, Any]]) -> List[List]:
    """
    压缩索引为数组格式以减少文件大小

    Args:
        index: 原始索引

    Returns:
        压缩后的索引
    """
    compressed = []
    for item in index:
        compressed.append([
            item["canonicalCode"],
            item["displayCode"],
            item["nameZh"],
            item.get("pinyinFull"),
            item.get("pinyinAbbr"),
            item.get("aliases", []),
            item["market"],
            item["assetType"],
            item["active"],
            item.get("popularity", 0),
        ])
    return compressed


# ---------------------------------------------------------------------------
# Index registry seed — build-time manifest merge.
# ---------------------------------------------------------------------------
_INDEX_REGISTRY_SEED_PATH = Path(__file__).parent / "stock_index_seeds" / "index_registry.csv"
_INDEX_NAMESPACE_RE = re.compile(r"^(sh|sz|csi)\d{6}$")
_EXPLICIT_INDEX_ALIAS_RE = re.compile(
    r"^(?:(?:sh|sz|csi)\d{6}|\d{6}\.(?:sh|sz|csi))$"
)


def load_index_registry_seed(seed_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load the approved index-registry seed CSV into raw row dicts.

    Columns: ``canonical_code,display_code,name_zh,aliases,name_source,popularity``.
    ``aliases`` uses the existing ``|``-separated ``parse_aliases()`` convention.
    """
    path = seed_path or _INDEX_REGISTRY_SEED_PATH
    if not path.is_file():
        raise FileNotFoundError(f"index registry seed not found: {path}")

    rows: List[Dict[str, Any]] = []
    # Normalized identity keys must not map to more than one canonical within
    # the seed. A NFKC/casefold-equivalent duplicate alias owned by two entries
    # (e.g. ``csi930955`` and ``CSI930955`` split across rows) would otherwise
    # silently overwrite one identity, so it is rejected at the build-time
    # boundary instead of at runtime. A key that equals its own row's canonical
    # (e.g. alias ``000300.SH`` on row ``sh000300``) is legitimate and skipped.
    seen_identity_keys: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            canonical = (row.get("canonical_code") or "").strip()
            display = (row.get("display_code") or "").strip()
            name = (row.get("name_zh") or "").strip()
            if not canonical or not display or not name:
                raise ValueError(f"index registry seed row missing required field: {row}")

            raw_aliases = [
                alias.strip()
                for alias in str(row.get("aliases") or "").split("|")
                if alias.strip()
            ]
            _validate_unique_index_aliases(raw_aliases, canonical)
            aliases = parse_aliases(row)
            _validate_unique_index_aliases(aliases, canonical)
            popularity_raw = (row.get("popularity") or "100").strip() or "100"
            try:
                popularity = int(popularity_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"index registry seed popularity must be a plain integer, "
                    f"got {popularity_raw!r} for canonical {canonical!r}"
                ) from exc
            if popularity < 0:
                raise ValueError(
                    f"index registry seed popularity must be non-negative: "
                    f"{popularity!r} for canonical {canonical!r}"
                )

            # Reject a normalized identity key that maps to a different canonical.
            for key in [canonical, display] + aliases:
                norm_key = _normalize_index_key(key)
                if not norm_key:
                    continue
                existing = seen_identity_keys.get(norm_key)
                if existing is not None and existing != canonical:
                    raise ValueError(
                        f"seed identity key {key!r} normalizes to {norm_key!r} "
                        f"already owned by canonical {existing!r}"
                    )
                seen_identity_keys[norm_key] = canonical

            rows.append({
                "canonical_code": canonical,
                "display_code": display,
                "name_zh": name,
                "aliases": aliases,
                "name_source": (row.get("name_source") or "").strip(),
                "popularity": popularity,
            })
    return rows


def _normalize_index_key(value: str) -> str:
    """Normalize resolver keys while keeping CSI suffix aliases distinct."""
    normalized = unicodedata.normalize(
        "NFKC", str(value or "")
    ).strip().casefold()
    prefix_match = re.fullmatch(r"(sh|sz)(\d{6})", normalized)
    if prefix_match:
        return f"{prefix_match.group(1)}{prefix_match.group(2)}"
    suffix_match = re.fullmatch(r"(\d{6})\.(sh|sz)", normalized)
    if suffix_match:
        return f"{suffix_match.group(2)}{suffix_match.group(1)}"
    return normalized


def _validate_unique_index_aliases(aliases: Any, canonical: str) -> None:
    """Reject duplicate aliases after NFKC/case-insensitive normalization."""
    if not isinstance(aliases, list):
        raise ValueError(f"index aliases must be a list: {canonical!r}")
    seen: set[str] = set()
    for alias in aliases:
        if not isinstance(alias, str):
            raise ValueError(f"index alias must be a string: {canonical!r}")
        normalized = _normalize_index_key(alias)
        if normalized in seen:
            raise ValueError(
                f"duplicate index alias after normalization for {canonical!r}: {alias!r}"
            )
        seen.add(normalized)


def build_index_entries_from_seed(seed_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert seed rows into the 10-column index tuple dicts.

    ``display_code`` is honored from the seed (SH/SZ display equals canonical;
    CSI display is ``{code}.CSI``). All rows are ``market=CN``,
    ``assetType=index``, ``active=True``, ``popularity`` from seed.
    """
    entries: List[Dict[str, Any]] = []
    for row in seed_rows:
        canonical = row["canonical_code"]
        _validate_unique_index_aliases(row.get("aliases"), canonical)
        popularity = row.get("popularity", 100)
        if (
            isinstance(popularity, bool)
            or not isinstance(popularity, int)
            or popularity < 0
        ):
            raise ValueError(
                f"index popularity must be a non-negative integer: {canonical!r}"
            )
        display = (row.get("display_code") or "").strip() or canonical
        pinyin_full, pinyin_abbr = generate_pinyin(row["name_zh"])
        entries.append({
            "canonicalCode": canonical,
            "displayCode": display,
            "nameZh": row["name_zh"],
            "pinyinFull": pinyin_full,
            "pinyinAbbr": pinyin_abbr,
            "aliases": list(row["aliases"]),
            "market": "CN",
            "assetType": "index",
            "active": True,
            "popularity": popularity,
        })
    return entries


def validate_index_registry(
    entries: List[Dict[str, Any]],
    non_index_rows: Optional[List[List[Any]]] = None,
) -> None:
    """Semantic validation for the index registry (build-time and candidates).

    Rules (implementation-contracts.md §Semantic Validation):
      1. canonical matches ``^(sh|sz|csi)\\d{6}$``; SH/SZ display == canonical,
         CSI display == ``{code}.CSI``.
      2. market=CN, assetType=index, active=True, non-empty name, valid pinyin,
         finite numeric popularity.
      3. canonical/display/alias normalize to exactly one canonical within the set.
      4. Index explicit keys must not collide with active stock/ETF keys; bare
         numeric display/alias rejected.
      5. Text aliases rejected from identity resolver seed.
      6. Each namespace has at least one daily provider in the manifest matrix.

    ``non_index_rows`` carries the active stock/ETF compressed tuples from the
    same payload so rule 4 can reject an index canonical/display/alias that
    collides with a stock/ETF identity after normalization.
    """
    if not entries:
        return

    canonical_map: Dict[str, str] = {}
    resolver_map: Dict[str, str] = {}
    bare_conflicts: Dict[str, str] = {}

    # Active stock/ETF identity keys (canonical/display/aliases) that an index
    # explicit key must never collide with after normalization.
    stock_keys: Dict[str, str] = {}
    for row in non_index_rows or []:
        if not isinstance(row, list) or len(row) < 10:
            continue
        if str(row[7] or "").strip() == "index":
            continue
        if row[8] is not True:
            continue
        stock_canonical = str(row[0] or "").strip()
        for key in [row[0], row[1]] + list(row[5] if isinstance(row[5], list) else []):
            norm_key = _normalize_index_key(key)
            if norm_key:
                stock_keys.setdefault(norm_key, stock_canonical)

    for entry in entries:
        canonical = str(entry["canonicalCode"] or "").strip()
        display = str(entry["displayCode"] or "").strip()
        name = str(entry["nameZh"] or "").strip()
        market = str(entry["market"] or "").strip()
        asset_type = str(entry["assetType"] or "").strip()
        active = entry["active"]
        popularity = entry["popularity"]
        aliases = entry.get("aliases")

        if not _INDEX_NAMESPACE_RE.match(canonical):
            raise ValueError(f"index canonical must match ^(sh|sz|csi)\\d{{6}}$: {canonical!r}")
        namespace = canonical[:3] if canonical.startswith("csi") else canonical[:2]
        if namespace in {"sh", "sz"}:
            if display != canonical:
                raise ValueError(f"SH/SZ index display must equal canonical: {canonical!r} != {display!r}")
        elif namespace == "csi":
            expected_display = f"{canonical[3:]}.CSI"
            if display != expected_display:
                raise ValueError(f"CSI index display must be {expected_display!r}, got {display!r}")

        if market != "CN":
            raise ValueError(f"index market must be CN: {canonical!r}")
        if asset_type != "index":
            raise ValueError(f"index asset_type must be index: {canonical!r}")
        if active is not True:
            raise ValueError(f"index active must be True: {canonical!r}")
        if not name:
            raise ValueError(f"index name must be non-empty: {canonical!r}")
        pinyin_full = entry.get("pinyinFull")
        pinyin_abbr = entry.get("pinyinAbbr")
        if (
            not isinstance(pinyin_full, str)
            or not pinyin_full.strip()
            or not isinstance(pinyin_abbr, str)
            or not pinyin_abbr.strip()
        ):
            raise ValueError(f"index pinyin fields must be non-empty: {canonical!r}")
        if not isinstance(aliases, list):
            raise ValueError(f"index aliases must be a list: {canonical!r}")
        _validate_unique_index_aliases(aliases, canonical)
        # Popularity must be a plain non-negative integer. Fractional
        # (``1.5``), boolean (``True``) and negative values are rejected
        # without truncation — only an integer value like ``100`` is valid.
        if (
            isinstance(popularity, bool)
            or not isinstance(popularity, int)
            or not math.isfinite(float(popularity))
            or popularity < 0
        ):
            raise ValueError(f"index popularity must be a non-negative integer: {canonical!r}")

        if namespace not in {"sh", "sz", "csi"}:
            raise ValueError(f"index namespace has no provider mapping: {namespace!r}")

        # canonical uniqueness
        norm_canonical = _normalize_index_key(canonical)
        if norm_canonical in canonical_map:
            raise ValueError(f"duplicate index canonical: {canonical!r}")
        canonical_map[norm_canonical] = canonical

        for alias in aliases:
            norm_alias = _normalize_index_key(alias)
            if norm_alias.isdigit():
                raise ValueError(f"bare numeric display/alias rejected for index: {alias!r}")
            if not _EXPLICIT_INDEX_ALIAS_RE.fullmatch(norm_alias):
                raise ValueError(
                    f"index aliases must use an explicit code form: {alias!r}"
                )

        # canonical + display + aliases must resolve to exactly one canonical
        for key in [canonical, display] + aliases:
            norm_key = _normalize_index_key(key)
            if not norm_key:
                continue
            if norm_key.isdigit():
                raise ValueError(f"bare numeric display/alias rejected for index: {key!r}")
            if norm_key in resolver_map and resolver_map[norm_key] != canonical:
                raise ValueError(
                    f"index resolver key {key!r} maps to multiple canonicals "
                    f"({resolver_map[norm_key]} vs {canonical})"
                )
            if norm_key in stock_keys:
                raise ValueError(
                    f"index resolver key {key!r} collides with active stock/ETF "
                    f"identity {stock_keys[norm_key]!r}"
                )
            resolver_map[norm_key] = canonical

        # bare-conflict map: numeric base of explicit aliases, for matched_index
        for alias in aliases:
            base = "".join(ch for ch in alias if ch.isdigit())
            if base and base.isdigit() and len(base) == 6:
                bare_conflicts.setdefault(base, canonical)

    return


def _load_existing_payload(output_path: Path) -> List[List[Any]]:
    """Load the existing compressed JSON payload (must be a list)."""
    with open(output_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, list):
        raise ValueError(f"existing payload is not a list: {output_path}")
    return payload


def _atomic_write_json(output_path: Path, compressed: List[List[Any]]) -> None:
    """Write the compressed payload atomically (temp file + os.replace)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write("[\n")
            for i, item in enumerate(compressed):
                json.dump(item, f, ensure_ascii=False, separators=(",", ":"))
                if i < len(compressed) - 1:
                    f.write(",\n")
                else:
                    f.write("\n")
            f.write("]\n")
        os.replace(temp_path, output_path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def run_index_only(output_path: Path, *, test: bool = False) -> List[List[Any]]:
    """Merge the approved index-registry seed into the existing compressed JSON.

    Preserves all non-index tuples in their original order, removes any old
    index tuples, appends seed-generated index rows sorted by canonicalCode,
    validates, and atomically replaces the output (unless ``test``).
    """
    seed_rows = load_index_registry_seed()
    index_entries = build_index_entries_from_seed(seed_rows)

    existing = _load_existing_payload(output_path)
    validate_stock_index_payload(existing, min_items=0)
    non_index = [item for item in existing if not (len(item) > 7 and item[7] == "index")]
    # Validate the seed index rows against the existing active stock/ETF rows so
    # an index identity that collides with a stock/ETF key is rejected.
    validate_index_registry(index_entries, non_index_rows=non_index)

    index_compressed = compress_index(index_entries)
    index_compressed.sort(key=lambda item: str(item[0]))

    merged = non_index + index_compressed
    if not test:
        _atomic_write_json(output_path, merged)
    return merged


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='从 CSV 生成股票自动补全索引')
    parser.add_argument(
        '--source',
        choices=['tushare', 'akshare'],
        default='tushare',
        help='数据源选择（默认: tushare）'
    )
    parser.add_argument(
        '--index-only',
        action='store_true',
        help='仅合并指数注册表 seed 到现有压缩 JSON，不重建股票索引'
    )
    parser.add_argument(
        '--test', '-t',
        action='store_true',
        help='测试模式：只验证不写入文件'
    )
    args = parser.parse_args()

    print("=" * 60)
    print("股票索引生成工具（从 CSV）")
    print("=" * 60)

    if not require_pypinyin():
        return 1

    # 输出路径
    output_path = (
        Path(__file__).parent.parent / "apps" / "dsa-web" / "public" / "stocks.index.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # --index-only: 只合并指数 seed，不重建股票索引。
    if args.index_only:
        print(f"数据源：index-only（合并指数注册表 seed）")
        print("\n[1/3] 读取指数注册表 seed...")
        merged = run_index_only(output_path, test=args.test)
        print(f"      合并后共 {len(merged)} 条记录")
        index_rows = [item for item in merged if len(item) > 7 and item[7] == "index"]
        print(f"      其中指数 {len(index_rows)} 条")
        if args.test:
            print("\n[2/3] 测试模式：跳过写入文件")
        else:
            print(f"\n[2/3] 写入文件：{output_path}")
            file_size = output_path.stat().st_size
            print(f"      文件大小：{file_size / 1024:.2f} KB")
        print("\n[3/3] 验证合并结果...")
        # In test mode the output file is untouched, so validate/report the
        # would-be merged payload returned by ``run_index_only`` rather than
        # reopening the unchanged file.
        print(f"      验证通过：{len(merged)} 条记录")
        return 0

    print(f"数据源：{args.source}")

    # 加载数据
    print("\n[1/5] 读取 CSV 数据...")
    if args.source == 'tushare':
        data_dir = Path(__file__).parent.parent / 'data'
        stocks = load_tushare_data(data_dir)
    elif args.source == 'akshare':
        logs_dir = Path(__file__).parent.parent / 'logs'
        stocks = load_akshare_data(logs_dir)
    else:
        print(f"[Error] 不支持的数据源：{args.source}")
        return 1

    if not stocks:
        print("[Error] 未加载到任何股票数据")
        return 1

    print(f"      共读取 {len(stocks)} 只股票")

    print("\n[2/5] 生成索引数据...")
    index = build_stock_index(stocks)

    # 合并指数注册表 seed，防止后续重建擦除 index 行。
    print("\n[2.5/5] 合并指数注册表 seed...")
    seed_rows = load_index_registry_seed()
    index_entries = build_index_entries_from_seed(seed_rows)
    # Validate the seed index rows against the freshly built stock/ETF rows so
    # an index identity that collides with a stock/ETF key is rejected.
    validate_index_registry(
        index_entries,
        non_index_rows=compress_index(index),
    )
    # Canonical-sort the index rows so the full rebuild is byte-stable and
    # matches the ``--index-only`` ordering; non-index rows keep build order.
    index_entries.sort(key=lambda entry: str(entry["canonicalCode"]))
    index.extend(index_entries)

    print("\n[3/5] 压缩索引数据...")
    compressed = compress_index(index)

    if args.test:
        print("\n[4/5] 测试模式：跳过写入文件")
        print(f"      输出路径：{output_path}")

        # 验证数据
        print("\n[5/5] 验证数据...")
        print(f"      压缩前：{len(index)} 条记录")
        print(f"      压缩后：{len(compressed)} 条记录")

        # 显示前5条示例
        if compressed:
            print("\n      前5条示例：")
            for i, item in enumerate(compressed[:5]):
                print(f"        {i + 1}. {item}")
    else:
        print(f"\n[4/5] 写入文件：{output_path}")
        _atomic_write_json(output_path, compressed)

        file_size = output_path.stat().st_size
        print(f"      文件大小：{file_size / 1024:.2f} KB")

        # 验证文件
        print("\n[5/5] 验证文件...")
        with open(output_path, 'r', encoding='utf-8') as f:
            test_data = json.load(f)
            print(f"      验证通过：{len(test_data)} 条记录")

    # 统计信息
    market_stats = {}
    for item in index:
        market = item['market']
        market_stats[market] = market_stats.get(market, 0) + 1

    print(f"\n{'=' * 60}")
    print("生成完成！市场分布：")
    for market, count in sorted(market_stats.items()):
        print(f"  - {market}: {count} 只")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
