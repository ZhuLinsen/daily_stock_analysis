#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate Stock Index from CSV File

Input:
  - Tushare format: data/stock_list_{a,hk,us}.csv
  - AkShare format: logs/stock_basic_*.csv

Output: apps/dsa-web/public/stocks.index.json

Usage:
    python3 scripts/generate_index_from_csv.py              # 默认使用 Tushare
    python3 scripts/generate_index_from_csv.py --source akshare
    python3 scripts/generate_index_from_csv.py --test       # 测试模式
"""

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add the project root to sys.path.
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from pypinyin import lazy_pinyin, Style
    PYPINYIN_AVAILABLE = True
except ImportError:
    PYPINYIN_AVAILABLE = False
    print("[Warning] pypinyin not available, pinyin fields will be empty")
    print("[Info] Install with: pip install pypinyin")


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
    从 Tushare CSV 文件加载三个市场的股票数据

    Args:
        data_dir: 数据目录路径

    Returns:
        合并后的股票列表
    """
    all_stocks = []
    market_files = {
        'CN': data_dir / 'stock_list_a.csv',
        'HK': data_dir / 'stock_list_hk.csv',
        'US': data_dir / 'stock_list_us.csv',
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
        return (None, None)

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


def extract_symbol_from_ts_code(ts_code: str, market: str) -> Optional[str]:
    """
    从 ts_code 提取 displayCode

    - A股：000001.SZ → 000001
    - 港股：00700.HK → 00700
    - 美股：AAPL → AAPL

    Args:
        ts_code: TS代码
        market: 市场代码

    Returns:
        displayCode 或 None
    """
    if not ts_code:
        return None

    if market == 'US':
        # 美股无后缀，直接返回
        return ts_code

    if '.' in ts_code:
        # A股和港股：去除后缀
        return ts_code.split('.')[0]

    return ts_code


def get_stock_name(row: Dict[str, str], market: str) -> Optional[str]:
    """
    获取股票名称

    - A股/港股：使用 name 字段
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
        return name if name else None


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
    }


def determine_market(ts_code: str) -> str:
    """
    Determine market based on code

    Args:
        ts_code: Trading code (e.g., 000001.SZ, AAPL, BRK.B, GOOG.A)

    Returns:
        Market code (CN, HK, US, BSE)
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
        '--test', '-t',
        action='store_true',
        help='测试模式：只验证不写入文件'
    )
    args = parser.parse_args()

    print("=" * 60)
    print("股票索引生成工具（从 CSV）")
    print("=" * 60)
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

    # 生成拼音提示
    if not PYPINYIN_AVAILABLE:
        print("\n[提示] 安装 pypinyin 可获得拼音搜索功能：")
        print("       pip install pypinyin")

    print("\n[2/5] 生成索引数据...")
    index = build_stock_index(stocks)

    # 输出路径
    output_path = (
        Path(__file__).parent.parent / "apps" / "dsa-web" / "public" / "stocks.index.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

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
        print("\n[4/5] 写入文件：{output_path}")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('[\n')
            for i, item in enumerate(compressed):
                json.dump(item, f, ensure_ascii=False, separators=(',', ':'))
                if i < len(compressed) - 1:
                    f.write(',\n')
                else:
                    f.write('\n')
            f.write(']\n')

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
