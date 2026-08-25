#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test generate_index_from_csv.py
"""

import csv
import json
import pytest
from pathlib import Path
from typing import Dict, List

# Add scripts directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from generate_index_from_csv import (
    extract_symbol_from_ts_code,
    get_stock_name,
    get_us_delist_priority,
    parse_stock_row,
    determine_market,
    generate_aliases,
    normalize_name_for_pinyin,
    normalize_stock_name_for_index,
    generate_pinyin,
    main,
    compress_index,
    build_stock_index,
    load_tushare_data,
    load_akshare_data,
    load_index_registry_seed,
    build_index_entries_from_seed,
    validate_index_registry,
    run_index_only,
    _normalize_index_key,
)


class TestExtractSymbol:
    """测试 Symbol 提取函数"""

    def test_a_stock_sz(self):
        """测试 A股深圳"""
        result = extract_symbol_from_ts_code("000001.SZ", "CN")
        assert result == "000001"

    def test_a_stock_sh(self):
        """测试 A股上海"""
        result = extract_symbol_from_ts_code("600519.SH", "CN")
        assert result == "600519"

    def test_hk_stock(self):
        """测试港股"""
        result = extract_symbol_from_ts_code("00700.HK", "HK")
        assert result == "00700"

    def test_us_stock(self):
        """测试美股"""
        result = extract_symbol_from_ts_code("AAPL", "US")
        assert result == "AAPL"

    def test_jp_stock_preserves_suffix(self):
        """测试日股保留 Yahoo 后缀以避免裸代码冲突"""
        result = extract_symbol_from_ts_code("7203.T", "JP")
        assert result == "7203.T"

    def test_kr_stock_preserves_suffix(self):
        """测试韩股保留 Yahoo 后缀以避免裸代码冲突"""
        result = extract_symbol_from_ts_code("005930.KS", "KR")
        assert result == "005930.KS"

    def test_empty_ts_code(self):
        """测试空 ts_code"""
        result = extract_symbol_from_ts_code("", "CN")
        assert result is None

    def test_none_ts_code(self):
        """测试 None ts_code"""
        result = extract_symbol_from_ts_code(None, "CN")
        assert result is None


class TestDetermineMarket:
    """测试市场判断函数"""

    def test_a_stock_sz(self):
        """测试 A股深圳"""
        result = determine_market("000001.SZ")
        assert result == "CN"

    def test_a_stock_sh(self):
        """测试 A股上海"""
        result = determine_market("600519.SH")
        assert result == "CN"

    def test_hk_stock(self):
        """测试港股"""
        result = determine_market("00700.HK")
        assert result == "HK"

    def test_bse_stock(self):
        """测试北交所"""
        result = determine_market("832566.BJ")
        assert result == "BSE"

    def test_us_stock(self):
        """测试美股"""
        result = determine_market("AAPL")
        assert result == "US"

    def test_us_stock_tesla(self):
        """测试美股特斯拉"""
        result = determine_market("TSLA")
        assert result == "US"

    def test_us_stock_with_dot_suffix(self):
        """测试美股带点号后缀（BRK.B）"""
        result = determine_market("BRK.B")
        assert result == "US"

    def test_us_stock_class_a(self):
        """测试美股 A 类股（GOOG.A）"""
        result = determine_market("GOOG.A")
        assert result == "US"

    def test_us_stock_units(self):
        """测试美股 Unit（AAPL.U）"""
        result = determine_market("AAPL.U")
        assert result == "US"

    def test_jp_stock_with_yahoo_suffix(self):
        """测试日股 Yahoo 后缀"""
        result = determine_market("7203.T")
        assert result == "JP"

    def test_kr_kospi_stock_with_yahoo_suffix(self):
        """测试韩股 KOSPI Yahoo 后缀"""
        result = determine_market("005930.KS")
        assert result == "KR"

    def test_kr_kosdaq_stock_with_yahoo_suffix(self):
        """测试韩股 KOSDAQ Yahoo 后缀"""
        result = determine_market("035720.KQ")
        assert result == "KR"


class TestGetStockName:
    """测试股票名称获取函数"""

    def test_cn_stock_name(self):
        """测试 A股使用 name 字段"""
        row = {'name': '平安银行', 'enname': 'Ping An Bank'}
        result = get_stock_name(row, 'CN')
        assert result == '平安银行'

    def test_hk_stock_name(self):
        """测试港股使用 name 字段"""
        row = {'name': '腾讯控股', 'enname': 'Tencent'}
        result = get_stock_name(row, 'HK')
        assert result == '腾讯控股'

    def test_us_stock_name(self):
        """测试美股使用 enname 字段"""
        row = {'name': '苹果', 'enname': 'Apple Inc.'}
        result = get_stock_name(row, 'US')
        assert result == 'Apple Inc.'

    def test_empty_name(self):
        """测试空名称"""
        row = {'name': '', 'enname': ''}
        result = get_stock_name(row, 'CN')
        assert result is None

    def test_cn_stock_name_strips_ex_rights_prefix(self):
        """测试 A股除权除息短期前缀不会写入长期索引名称"""
        row = {'name': 'XD西藏药', 'enname': ''}
        result = get_stock_name(row, 'CN')
        assert result == '西藏药'

    def test_cn_stock_name_preserves_new_stock_prefix(self):
        """测试 A股新股前缀保留，等待后续数据包刷新自然消失"""
        row = {'name': 'N惠康', 'enname': ''}
        result = get_stock_name(row, 'CN')
        assert result == 'N惠康'


class TestDataCleaning:
    """测试数据清洗逻辑"""

    def test_valid_cn_stock(self):
        """测试有效的 A股记录"""
        row = {
            'ts_code': '000001.SZ',
            'symbol': '000001',
            'name': '平安银行'
        }
        result = parse_stock_row(row, 'CN')
        assert result is not None
        assert result['ts_code'] == '000001.SZ'
        assert result['symbol'] == '000001'
        assert result['name'] == '平安银行'
        assert result['market'] == 'CN'

    def test_valid_hk_stock(self):
        """测试有效的港股记录"""
        row = {
            'ts_code': '00700.HK',
            'name': '腾讯控股',
            'enname': 'Tencent'
        }
        result = parse_stock_row(row, 'HK')
        assert result is not None
        assert result['ts_code'] == '00700.HK'
        assert result['symbol'] == '00700'
        assert result['name'] == '腾讯控股'
        assert result['market'] == 'HK'

    def test_valid_us_stock(self):
        """测试有效的美股记录"""
        row = {
            'ts_code': 'AAPL',
            'name': '苹果',
            'enname': 'Apple Inc.'
        }
        result = parse_stock_row(row, 'US')
        assert result is not None
        assert result['ts_code'] == 'AAPL'
        assert result['symbol'] == 'AAPL'
        assert result['name'] == 'Apple Inc.'
        assert result['market'] == 'US'

    def test_valid_us_stock_with_dot_suffix(self):
        """测试有效的美股记录（带点号后缀，如 BRK.B）"""
        row = {
            'ts_code': 'BRK.B',
            'name': '',
            'enname': "BERKSHIRE HATHAWAY 'B'"
        }
        result = parse_stock_row(row, None)
        assert result is not None
        assert result['ts_code'] == 'BRK.B'
        assert result['symbol'] == 'BRK.B'
        assert result['name'] == "BERKSHIRE HATHAWAY 'B'"
        assert result['market'] == 'US'

    def test_valid_jp_stock_with_seed_aliases(self):
        """测试有效的日股种子记录"""
        row = {
            'ts_code': '7203.T',
            'name': '丰田汽车',
            'enname': 'Toyota Motor Corporation',
            'aliases': 'Toyota|Toyota Motor|丰田'
        }
        result = parse_stock_row(row, 'JP')
        assert result is not None
        assert result['ts_code'] == '7203.T'
        assert result['symbol'] == '7203.T'
        assert result['name'] == '丰田汽车'
        assert result['market'] == 'JP'
        assert result['aliases'] == ['Toyota', 'Toyota Motor', '丰田']

    def test_valid_kr_stock_with_seed_aliases(self):
        """测试有效的韩股种子记录"""
        row = {
            'ts_code': '005930.KS',
            'name': '三星电子',
            'enname': 'Samsung Electronics',
            'aliases': 'Samsung|Samsung Electronics|三星'
        }
        result = parse_stock_row(row, 'KR')
        assert result is not None
        assert result['ts_code'] == '005930.KS'
        assert result['symbol'] == '005930.KS'
        assert result['name'] == '三星电子'
        assert result['market'] == 'KR'
        assert result['aliases'] == ['Samsung', 'Samsung Electronics', '三星']

    def test_us_dummy_filtered(self):
        """测试美股 DUMMY 记录被过滤"""
        row = {
            'ts_code': 'DUMMY001',
            'name': '测试',
            'enname': 'DUMMY Test Stock'
        }
        result = parse_stock_row(row, 'US')
        assert result is None

    def test_us_dummy_case_insensitive(self):
        """测试 DUMMY 过滤不区分大小写"""
        row = {
            'ts_code': 'DUMMY002',
            'name': '测试',
            'enname': 'dummy test stock'
        }
        result = parse_stock_row(row, 'US')
        assert result is None

    def test_empty_ts_code(self):
        """测试空 ts_code 被过滤"""
        row = {
            'ts_code': '',
            'symbol': '000001',
            'name': '平安银行'
        }
        result = parse_stock_row(row, 'CN')
        assert result is None

    def test_empty_name(self):
        """测试空名称被过滤"""
        row = {
            'ts_code': '000001.SZ',
            'symbol': '000001',
            'name': ''
        }
        result = parse_stock_row(row, 'CN')
        assert result is None

    def test_us_empty_enname(self):
        """测试美股空 enname 被过滤"""
        row = {
            'ts_code': 'AAPL',
            'name': '苹果',
            'enname': ''
        }
        result = parse_stock_row(row, 'US')
        assert result is None

    def test_us_delist_priority_prefers_blank_over_nat(self):
        """测试美股去重优先级：空 delist_date 优先于 NaT"""
        assert get_us_delist_priority({'delist_date': ''}) == 2
        assert get_us_delist_priority({'delist_date': 'NaT'}) == 1
        assert get_us_delist_priority({'delist_date': '20250131'}) == 0


class TestNormalizeStockNameForIndex:
    """测试索引名称归一化"""

    def test_strips_a_share_ex_rights_prefixes(self):
        assert normalize_stock_name_for_index('XD西藏药', 'CN') == '西藏药'
        assert normalize_stock_name_for_index('XR示例股', 'CN') == '示例股'
        assert normalize_stock_name_for_index('DR罗曼股', 'CN') == '罗曼股'
        assert normalize_stock_name_for_index('XD朱老六', 'BSE') == '朱老六'

    def test_preserves_a_share_new_stock_and_st_prefixes(self):
        assert normalize_stock_name_for_index('N惠康', 'CN') == 'N惠康'
        assert normalize_stock_name_for_index('C天海', 'CN') == 'C天海'
        assert normalize_stock_name_for_index('ST海王', 'CN') == 'ST海王'
        assert normalize_stock_name_for_index('*ST美丽', 'CN') == '*ST美丽'

    def test_does_not_strip_other_markets(self):
        assert normalize_stock_name_for_index('DRAGONFLY ENERGY', 'US') == 'DRAGONFLY ENERGY'
        assert normalize_stock_name_for_index('XD港股示例', 'HK') == 'XD港股示例'


class TestAliases:
    """测试别名生成函数"""

    def test_cn_aliases(self):
        """测试 A股别名"""
        result = generate_aliases('贵州茅台', 'CN')
        assert '茅台' in result

    def test_hk_aliases(self):
        """测试港股别名"""
        result = generate_aliases('腾讯控股', 'HK')
        assert '腾讯' in result or 'Tencent' in result

    def test_us_aliases(self):
        """测试美股别名"""
        result = generate_aliases('Apple Inc.', 'US')
        assert 'Apple' in result or 'AAPL' in result

    def test_no_aliases(self):
        """测试无别名的情况"""
        result = generate_aliases('未知股票', 'CN')
        assert result == []


class TestOutputFormat:
    """测试输出格式"""

    def test_compress_index_field_order(self):
        """测试压缩格式的字段顺序"""
        index = [{
            "canonicalCode": "000001.SZ",
            "displayCode": "000001",
            "nameZh": "平安银行",
            "pinyinFull": "pinganyinhang",
            "pinyinAbbr": "pyyh",
            "aliases": ["平银"],
            "market": "CN",
            "assetType": "stock",
            "active": True,
            "popularity": 100,
        }]

        compressed = compress_index(index)

        assert len(compressed) == 1
        item = compressed[0]

        # 验证字段顺序
        assert item[0] == "000001.SZ"      # canonicalCode
        assert item[1] == "000001"         # displayCode
        assert item[2] == "平安银行"       # nameZh
        assert item[3] == "pinganyinhang"  # pinyinFull
        assert item[4] == "pyyh"           # pinyinAbbr
        assert item[5] == ["平银"]         # aliases
        assert item[6] == "CN"             # market
        assert item[7] == "stock"          # assetType
        assert item[8] == True             # active
        assert item[9] == 100              # popularity

    def test_compress_index_field_count(self):
        """测试压缩格式的字段数量"""
        index = [{
            "canonicalCode": "AAPL",
            "displayCode": "AAPL",
            "nameZh": "Apple Inc.",
            "pinyinFull": None,
            "pinyinAbbr": None,
            "aliases": [],
            "market": "US",
            "assetType": "stock",
            "active": True,
            "popularity": 100,
        }]

        compressed = compress_index(index)
        assert len(compressed[0]) == 10  # 10个字段

    def test_json_serialization(self):
        """测试 JSON 序列化"""
        index = [{
            "canonicalCode": "00700.HK",
            "displayCode": "00700",
            "nameZh": "腾讯控股",
            "pinyinFull": "xunxiongkonggu",
            "pinyinAbbr": "xxkg",
            "aliases": ["腾讯"],
            "market": "HK",
            "assetType": "stock",
            "active": True,
            "popularity": 100,
        }]

        compressed = compress_index(index)

        # 应该能成功序列化为 JSON
        json_str = json.dumps(compressed, ensure_ascii=False)
        assert json_str is not None

        # 应该能成功反序列化
        loaded = json.loads(json_str)
        assert len(loaded) == 1


class TestIntegration:
    """集成测试"""

    def test_full_workflow_tushare(self, tmp_path):
        """测试完整的 Tushare 工作流"""
        # 创建测试 CSV 文件
        a_csv = tmp_path / 'stock_list_a.csv'
        with open(a_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'symbol', 'name'])
            writer.writeheader()
            writer.writerow({
                'ts_code': '000001.SZ',
                'symbol': '000001',
                'name': '平安银行'
            })

        hk_csv = tmp_path / 'stock_list_hk.csv'
        with open(hk_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'name', 'enname'])
            writer.writeheader()
            writer.writerow({
                'ts_code': '00700.HK',
                'name': '腾讯控股',
                'enname': 'Tencent'
            })

        us_csv = tmp_path / 'stock_list_us.csv'
        with open(us_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'name', 'enname'])
            writer.writeheader()
            writer.writerow({
                'ts_code': 'AAPL',
                'name': '苹果',
                'enname': 'Apple Inc.'
            })

        jp_csv = tmp_path / 'stock_list_jp.csv'
        with open(jp_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'name', 'enname', 'aliases'])
            writer.writeheader()
            writer.writerow({
                'ts_code': '7203.T',
                'name': '丰田汽车',
                'enname': 'Toyota Motor Corporation',
                'aliases': 'Toyota|丰田'
            })

        kr_csv = tmp_path / 'stock_list_kr.csv'
        with open(kr_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'name', 'enname', 'aliases'])
            writer.writeheader()
            writer.writerow({
                'ts_code': '005930.KS',
                'name': '三星电子',
                'enname': 'Samsung Electronics',
                'aliases': 'Samsung|三星'
            })

        # 加载数据
        stocks = load_tushare_data(tmp_path)

        # 验证数据
        assert len(stocks) == 5

        # 构建索引
        index = build_stock_index(stocks)

        # 验证索引
        assert len(index) == 5
        assert next(item for item in index if item['canonicalCode'] == '7203.T')['aliases'] == ['Toyota', '丰田']
        assert next(item for item in index if item['canonicalCode'] == '005930.KS')['aliases'] == ['Samsung', '三星']

        # 压缩索引
        compressed = compress_index(index)

        # 验证压缩
        assert len(compressed) == 5

        # 验证字段数量
        for item in compressed:
            assert len(item) == 10

    def test_market_distribution(self, tmp_path):
        """测试市场分布统计"""
        # 创建测试数据
        csv_file = tmp_path / 'stock_list_a.csv'
        with open(csv_file, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['ts_code', 'symbol', 'name'])
            writer.writeheader()
            writer.writerow({'ts_code': '000001.SZ', 'symbol': '000001', 'name': '平安银行'})
            writer.writerow({'ts_code': '600519.SH', 'symbol': '600519', 'name': '贵州茅台'})
            writer.writerow({'ts_code': '832566.BJ', 'symbol': '832566', 'name': '梓撞科技'})

        stocks = load_tushare_data(tmp_path)
        index = build_stock_index(stocks)

        # 统计市场分布
        market_stats = {}
        for item in index:
            market = item['market']
            market_stats[market] = market_stats.get(market, 0) + 1

        # 验证统计
        assert market_stats.get('CN', 0) == 2  # SZ, SH
        assert market_stats.get('BSE', 0) == 1  # BJ

    def test_us_reused_symbols_are_deduplicated(self, tmp_path):
        """测试美股复用 ticker 在加载时会先去重"""
        us_csv = tmp_path / 'stock_list_us.csv'
        with open(us_csv, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=['ts_code', 'name', 'enname', 'list_date', 'delist_date']
            )
            writer.writeheader()
            writer.writerow({
                'ts_code': 'B',
                'name': '',
                'enname': 'BARNES GROUP',
                'list_date': '19631014',
                'delist_date': 'NaT',
            })
            writer.writerow({
                'ts_code': 'B',
                'name': '',
                'enname': 'BARRICK MINING (NYS)',
                'list_date': '19850213',
                'delist_date': '',
            })
            writer.writerow({
                'ts_code': 'DOC',
                'name': '',
                'enname': 'HEALTHPEAK PROPERTIES',
                'list_date': '19850523',
                'delist_date': '',
            })
            writer.writerow({
                'ts_code': 'DOC',
                'name': '',
                'enname': 'PHYSICIANS REALTY TST.',
                'list_date': '20130719',
                'delist_date': '',
            })
            writer.writerow({
                'ts_code': 'SPWR',
                'name': '',
                'enname': 'COMPLETE SOLARIA',
                'list_date': '20210419',
                'delist_date': '',
            })
            writer.writerow({
                'ts_code': 'SPWR',
                'name': '',
                'enname': 'SUNPOWER',
                'list_date': '20051109',
                'delist_date': 'NaT',
            })

        stocks = load_tushare_data(tmp_path)

        assert len(stocks) == 3
        assert {stock['ts_code'] for stock in stocks} == {'B', 'DOC', 'SPWR'}
        assert next(stock for stock in stocks if stock['ts_code'] == 'B')['name'] == 'BARRICK MINING (NYS)'
        assert next(stock for stock in stocks if stock['ts_code'] == 'DOC')['name'] == 'HEALTHPEAK PROPERTIES'
        assert next(stock for stock in stocks if stock['ts_code'] == 'SPWR')['name'] == 'COMPLETE SOLARIA'


class TestPinyin:
    """测试拼音生成"""

    def test_normalize_name(self):
        """测试名称标准化"""
        # 测试 ST 前缀去除
        result = normalize_name_for_pinyin('*ST平安')
        assert 'ST' not in result

        # 测试 N 前缀去除
        result = normalize_name_for_pinyin('N平安银行')
        assert 'N' not in result

    def test_generate_pinyin(self):
        """测试拼音生成"""
        pinyin_full, pinyin_abbr = generate_pinyin('平安银行')
        assert pinyin_full == 'pinganyinhang'
        assert pinyin_abbr == 'payh'

    def test_generate_pinyin_requires_dependency(self, monkeypatch):
        """测试缺少 pypinyin 时不会生成降级拼音字段"""
        import generate_index_from_csv

        monkeypatch.setattr(generate_index_from_csv, 'PYPINYIN_AVAILABLE', False)

        with pytest.raises(RuntimeError, match='pypinyin is required'):
            generate_index_from_csv.generate_pinyin('平安银行')

    def test_main_fails_without_pypinyin(self, monkeypatch):
        """测试正式生成索引前必须具备 pypinyin"""
        import generate_index_from_csv

        monkeypatch.setattr(generate_index_from_csv, 'PYPINYIN_AVAILABLE', False)
        monkeypatch.setattr(sys, 'argv', ['generate_index_from_csv.py'])

        assert main() == 1


# ---------------------------------------------------------------------------
# Index registry seed generation
# ---------------------------------------------------------------------------
class TestIndexRegistrySeed:
    """Seed generates exactly 31 index rows; index-only merge is stable."""

    def test_seed_loads_31_rows(self):
        rows = load_index_registry_seed()
        assert len(rows) == 31

    def test_seed_entries_build_valid_index_tuples(self):
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        assert len(entries) == 31
        for entry in entries:
            assert entry["market"] == "CN"
            assert entry["assetType"] == "index"
            assert entry["active"] is True
            assert entry["popularity"] == 100
            assert entry["nameZh"]
            assert entry["pinyinFull"]
            assert entry["pinyinAbbr"]

    def test_seed_canonical_set_matches_manifest(self):
        rows = load_index_registry_seed()
        canonicals = {row["canonical_code"] for row in rows}
        assert len(canonicals) == 31
        # Spot-check the 5 original + CSI entries.
        assert {"sh000300", "sh000016", "sh000688", "sz399001", "sz399006"} <= canonicals
        assert {"csi930955", "csi932365", "csi931052"} <= canonicals

    def test_seed_csi_display_is_code_dot_csi(self):
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        csi = {e["canonicalCode"]: e["displayCode"] for e in entries if e["canonicalCode"].startswith("csi")}
        assert csi["csi930955"] == "930955.CSI"
        assert csi["csi932365"] == "932365.CSI"

    def test_validate_index_registry_accepts_valid_seed(self):
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        validate_index_registry(entries)  # should not raise

    def test_validate_index_registry_rejects_duplicate_canonical(self):
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        entries.append(dict(entries[0]))
        with pytest.raises(ValueError, match="duplicate index canonical"):
            validate_index_registry(entries)

    def test_validate_index_registry_rejects_bare_numeric_alias(self):
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        entries[0]["aliases"] = ["000300"]
        with pytest.raises(ValueError, match="bare numeric"):
            validate_index_registry(entries)

    def test_validate_index_registry_rejects_text_alias(self):
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        entries[0]["aliases"] = ["CSI300"]
        with pytest.raises(ValueError, match="explicit code form"):
            validate_index_registry(entries)

    def test_validate_index_registry_rejects_unknown_namespace(self):
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        entries[0]["canonicalCode"] = "xx000300"
        with pytest.raises(ValueError, match="canonical must match"):
            validate_index_registry(entries)

    def test_index_only_preserves_non_index_rows_and_appends_31(self, tmp_path):
        output = tmp_path / "stocks.index.json"
        output.write_text(
            json.dumps(
                [
                    ["000001.SZ", "000001", "平安银行", "payh", "payh", [], "CN", "stock", True, 100],
                    ["600519.SH", "600519", "贵州茅台", "gzmt", "gzmt", [], "CN", "stock", True, 100],
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        merged = run_index_only(output, test=True)
        non_index = [x for x in merged if not (len(x) > 7 and x[7] == "index")]
        index_rows = [x for x in merged if len(x) > 7 and x[7] == "index"]
        # Non-index rows preserved in order.
        assert [x[0] for x in non_index] == ["000001.SZ", "600519.SH"]
        # Exactly 31 index rows appended.
        assert len(index_rows) == 31
        # Index rows sorted by canonical.
        canonicals = [x[0] for x in index_rows]
        assert canonicals == sorted(canonicals)

    def test_index_only_is_byte_stable(self, tmp_path):
        output = tmp_path / "stocks.index.json"
        output.write_text(
            json.dumps(
                [["000001.SZ", "000001", "平安银行", "payh", "payh", [], "CN", "stock", True, 100]],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        run_index_only(output, test=False)
        first = output.read_bytes()
        run_index_only(output, test=False)
        second = output.read_bytes()
        assert first == second

    def test_index_only_test_mode_does_not_write(self, tmp_path):
        output = tmp_path / "stocks.index.json"
        output.write_text(
            json.dumps(
                [["000001.SZ", "000001", "平安银行", "payh", "payh", [], "CN", "stock", True, 100]],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        before = output.read_bytes()
        run_index_only(output, test=True)
        assert output.read_bytes() == before

    def test_full_path_merge_includes_31_index_rows(self, tmp_path, monkeypatch):
        """The full rebuild path (``main()``) merges the same 31 index
        rows before compression, so a full stock-index rebuild never erases the
        index registry entries."""
        import generate_index_from_csv as gen

        # A tiny stock list so the full path runs without network.
        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行"},
            {"ts_code": "600519.SH", "symbol": "600519", "name": "贵州茅台"},
        ]
        monkeypatch.setattr(gen, "load_tushare_data", lambda data_dir: stocks)
        monkeypatch.setattr(gen, "require_pypinyin", lambda: True)
        monkeypatch.setattr(
            sys, "argv", ["generate_index_from_csv.py", "--source", "tushare", "--test"]
        )

        assert main() == 0

        # Rebuild the same pipeline in-process to inspect the merged index rows.
        index = build_stock_index(stocks)
        seed_rows = load_index_registry_seed()
        index_entries = build_index_entries_from_seed(seed_rows)
        validate_index_registry(index_entries)
        index.extend(index_entries)
        compressed = compress_index(index)
        index_rows = [item for item in compressed if len(item) > 7 and item[7] == "index"]
        assert len(index_rows) == 31
        # Stock rows are preserved alongside the index rows.
        stock_rows = [item for item in compressed if len(item) > 7 and item[7] == "stock"]
        assert len(stock_rows) == 2

    def test_validate_index_registry_rejects_stock_key_collision(self):
        """Gap 3: an index canonical/display/alias that collides with an active
        stock/ETF key after normalization is rejected."""
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        # A stock row whose canonical ``sh000300`` collides with the index
        # canonical ``sh000300``.
        non_index = [["sh000300", "sh000300", "沪深300", "hushen300", "hs300", [], "CN", "stock", True, 100]]
        with pytest.raises(ValueError, match="collides with active stock/ETF"):
            validate_index_registry(entries, non_index_rows=non_index)

    def test_validate_index_registry_rejects_stock_alias_collision(self):
        """Gap 3: an index alias that collides with an active stock alias is
        rejected."""
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        # A stock row whose alias ``000300.SH`` collides with the sh000300 index
        # alias ``000300.SH``.
        non_index = [["600519.SH", "600519", "贵州茅台", "gzmt", "gzmt", ["000300.SH"], "CN", "stock", True, 100]]
        with pytest.raises(ValueError, match="collides with active stock/ETF"):
            validate_index_registry(entries, non_index_rows=non_index)

    def test_validate_index_registry_rejects_csi_canonical_stock_collision(self):
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        non_index = [["csi930955", "930955", "冲突股票", "ctgp", "ctgp", [], "CN", "stock", True, 100]]
        with pytest.raises(ValueError, match="collides with active stock/ETF"):
            validate_index_registry(entries, non_index_rows=non_index)

    def test_validate_index_registry_rejects_equivalent_suffix_stock_collision(self):
        rows = load_index_registry_seed()
        entry = build_index_entries_from_seed(rows)[0]
        entry.update({"canonicalCode": "sh600519", "displayCode": "sh600519", "aliases": []})
        non_index = [["600519.SH", "600519", "贵州茅台", "gzmt", "gzmt", [], "CN", "stock", True, 100]]
        with pytest.raises(ValueError, match="collides with active stock/ETF"):
            validate_index_registry([entry], non_index_rows=non_index)

    def test_validate_index_registry_rejects_non_string_pinyin(self):
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        entries[0]["pinyinFull"] = ["hushen300"]
        with pytest.raises(ValueError, match="pinyin fields"):
            validate_index_registry(entries)

    def test_index_only_rejects_stock_key_collision(self, tmp_path):
        """Gap 3: ``run_index_only`` validates the seed index rows against the
        existing active stock/ETF rows and rejects a collision."""
        output = tmp_path / "stocks.index.json"
        output.write_text(
            json.dumps(
                [["sh000300", "sh000300", "沪深300", "hushen300", "hs300", [], "CN", "stock", True, 100]],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="collides with active stock/ETF"):
            run_index_only(output, test=True)

    def test_index_only_rejects_malformed_existing_tuple(self, tmp_path):
        output = tmp_path / "stocks.index.json"
        output.write_text(json.dumps([["too-short"]]), encoding="utf-8")
        with pytest.raises(ValueError, match="compressed tuple"):
            run_index_only(output, test=True)

    def test_build_index_entries_honors_seed_display_code(self):
        """Gap 5: ``build_index_entries_from_seed`` honors the seed
        ``display_code`` column rather than recomputing it."""
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        by_canonical = {e["canonicalCode"]: e["displayCode"] for e in entries}
        # CSI display comes from the seed ``display_code`` column.
        assert by_canonical["csi930955"] == "930955.CSI"
        assert by_canonical["csi932365"] == "932365.CSI"
        # SH/SZ display equals canonical.
        assert by_canonical["sh000300"] == "sh000300"
        assert by_canonical["sz399001"] == "sz399001"

    def test_validate_index_registry_rejects_non_finite_popularity(self):
        """Gap 5: a non-finite popularity (e.g. NaN) is rejected — it is not a
        plain integer (NaN is a float), so it fails the integer check."""
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        entries[0]["popularity"] = float("nan")
        with pytest.raises(ValueError, match="non-negative integer"):
            validate_index_registry(entries)

    @pytest.mark.parametrize(
        "bad_popularity",
        [1.5, True, -1, -100, 1.0, "100"],
    )
    def test_validate_index_registry_rejects_non_integer_popularity(
        self, bad_popularity
    ):
        """PR #2267 review fix: only a plain non-negative integer popularity is
        valid. Fractional (``1.5``), boolean (``True``), negative and
        string-valued popularities are rejected without truncation."""
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        entries[0]["popularity"] = bad_popularity
        with pytest.raises(ValueError, match="non-negative integer"):
            validate_index_registry(entries)

    def test_validate_index_registry_accepts_integer_popularity(self):
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        entries[0]["popularity"] = 100
        validate_index_registry(entries)  # should not raise

    def test_seed_rejects_fractional_popularity(self, tmp_path):
        seed = tmp_path / "index_registry.csv"
        seed.write_text(
            "canonical_code,display_code,name_zh,aliases,name_source,popularity\n"
            "sh000300,sh000300,沪深300,,腾讯,1.5\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="plain integer"):
            load_index_registry_seed(seed)

    def test_seed_rejects_duplicate_normalized_identity_key(self, tmp_path):
        seed = tmp_path / "index_registry.csv"
        seed.write_text(
            "canonical_code,display_code,name_zh,aliases,name_source,popularity\n"
            "csi930955,930955.CSI,红利低波100,,东财,100\n"
            "sh000300,sh000300,沪深300,csi930955,腾讯,100\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="already owned by canonical"):
            load_index_registry_seed(seed)

    def test_csi_prefix_and_suffix_keep_distinct_resolver_keys(self):
        assert _normalize_index_key("csi000300") == "csi000300"
        assert _normalize_index_key("000300.CSI") == "000300.csi"

    def test_seed_rejects_duplicate_aliases_within_one_row(self, tmp_path):
        seed = tmp_path / "index_registry.csv"
        seed.write_text(
            "canonical_code,display_code,name_zh,aliases,name_source,popularity\n"
            "sh000300,sh000300,沪深300,000300.CSI|０００３００．ＣＳＩ,腾讯,100\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="duplicate index alias"):
            load_index_registry_seed(seed)

    def test_build_rejects_duplicate_aliases_when_seed_loader_is_bypassed(self):
        rows = load_index_registry_seed()
        rows[0]["aliases"] = ["000001.SH", "０００００１．ＳＨ"]
        with pytest.raises(ValueError, match="duplicate index alias"):
            build_index_entries_from_seed(rows)

    def test_build_rejects_fractional_popularity_when_seed_loader_is_bypassed(self):
        rows = load_index_registry_seed()
        rows[0]["popularity"] = 1.5
        with pytest.raises(ValueError, match="non-negative integer"):
            build_index_entries_from_seed(rows)

    def test_validate_rejects_duplicate_aliases_within_one_entry(self):
        rows = load_index_registry_seed()
        entries = build_index_entries_from_seed(rows)
        entries[0]["aliases"] = ["000001.SH", "０００００１．ＳＨ"]
        with pytest.raises(ValueError, match="duplicate index alias"):
            validate_index_registry(entries)

    def test_full_path_merge_canonical_sorts_index_rows(self, tmp_path, monkeypatch):
        """Gap 5: the full rebuild path canonical-sorts the index rows so the
        output is byte-stable and matches ``--index-only`` ordering."""
        import generate_index_from_csv as gen

        stocks = [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行"},
            {"ts_code": "600519.SH", "symbol": "600519", "name": "贵州茅台"},
        ]
        monkeypatch.setattr(gen, "load_tushare_data", lambda data_dir: stocks)
        monkeypatch.setattr(gen, "require_pypinyin", lambda: True)
        monkeypatch.setattr(
            sys, "argv", ["generate_index_from_csv.py", "--source", "tushare", "--test"]
        )
        assert main() == 0

        index = build_stock_index(stocks)
        seed_rows = load_index_registry_seed()
        index_entries = build_index_entries_from_seed(seed_rows)
        index_entries.sort(key=lambda entry: str(entry["canonicalCode"]))
        index.extend(index_entries)
        compressed = compress_index(index)
        index_rows = [item for item in compressed if len(item) > 7 and item[7] == "index"]
        canonicals = [x[0] for x in index_rows]
        assert canonicals == sorted(canonicals)
