# -*- coding: utf-8 -*-
"""Tests for name_to_code_resolver.

Covers:
- Local mapping (STOCK_NAME_MAP reverse)
- Code format boundary (_is_code_like, _normalize_code)
- Pinyin match (when pypinyin available)
- AkShare fallback (mocked)
- Fuzzy match (difflib)
- Ambiguous names return None
- Stock dataclass / resolver_name_to_code_list / US_stock_code_match / extend_AkShare
"""

import threading
import time
from typing import Optional
from unittest.mock import patch

import pandas as pd
import pytest

from src.data.stock_mapping import STOCK_NAME_MAP
from src.services import name_to_code_resolver as ntc
from src.services.name_to_code_resolver import (
    Stock,
    resolve_name_to_code,
    resolver_name_to_code_list,
    US_stock_code_match,
    _is_code_like,
    _normalize_code,
    _build_reverse_map_no_duplicates,
)


@pytest.fixture()
def clean_db(request):
    """Isolate the global stockDB/caches; the AkShare fetch is mocked offline
    by default. Parametrize with ``indirect=True`` to inject a fake map."""
    fake_map = getattr(request, "param", None)
    with patch.object(ntc, "_get_akshare_name_to_code", return_value=fake_map):
        yield
    # 恢复用归一后的本地映射（与模块初值同构，见 _normalize_stock_name）
    ntc.stockDB.clear()
    ntc.stockDB.update(
        {c: ntc._normalize_stock_name(n) for c, n in STOCK_NAME_MAP.items()}
    )
    ntc._names_cache[:] = [None, None, None]
    ntc._pinyin_cache[:] = [None, None]
    ntc._akshare_merged = None
    ntc._akshare_cache = None
    ntc._akshare_failure_cache = None
    ntc._akshare_inflight = None
    ntc.stockAliases.clear()


# ---------------------------------------------------------------------------
# _is_code_like
# ---------------------------------------------------------------------------

class TestIsCodeLike:
    def test_a_share_5_digits(self):
        assert _is_code_like("60051") is True
        assert _is_code_like("600519") is True

    def test_a_share_6_digits(self):
        assert _is_code_like("300750") is True

    def test_bse_with_exchange_hint(self):
        assert _is_code_like("920493.BJ") is True
        assert _is_code_like("BJ920493") is True

    def test_bj_exchange_hint_rejects_non_bse_code(self):
        assert _is_code_like("600519.BJ") is False
        assert _is_code_like("BJ600519") is False

    def test_hk_5_digits(self):
        assert _is_code_like("00700") is True

    def test_us_stock_letters(self):
        assert _is_code_like("AAPL") is True
        assert _is_code_like("TSLA") is True
        assert _is_code_like("BRK.B") is True

    def test_rejects_non_code(self):
        assert _is_code_like("贵州茅台") is False
        assert _is_code_like("1234") is False  # too short
        assert _is_code_like("1234567") is False  # too long
        assert _is_code_like("") is False
        assert _is_code_like("   ") is False


# ---------------------------------------------------------------------------
# _normalize_code
# ---------------------------------------------------------------------------

class TestNormalizeCode:
    def test_preserves_valid_a_share(self):
        assert _normalize_code("600519") == "600519"
        assert _normalize_code("  600519  ") == "600519"

    def test_strips_suffix(self):
        assert _normalize_code("600519.SH") == "600519"
        assert _normalize_code("000001.SZ") == "000001"
        assert _normalize_code("920493.BJ") == "920493"

    def test_strips_bse_prefix(self):
        assert _normalize_code("BJ920493") == "920493"

    def test_bj_exchange_hint_rejects_non_bse_code(self):
        assert _normalize_code("600519.BJ") is None
        assert _normalize_code("BJ600519") is None

    def test_preserves_us_stock(self):
        assert _normalize_code("AAPL") == "AAPL"
        assert _normalize_code("brk.b") == "BRK.B"

    def test_returns_none_for_invalid(self):
        assert _normalize_code("") is None
        assert _normalize_code("1234") is None
        assert _normalize_code("贵州茅台") is None


# ---------------------------------------------------------------------------
# _build_reverse_map_no_duplicates
# ---------------------------------------------------------------------------

class TestBuildReverseMapNoDuplicates:
    def test_excludes_ambiguous_names(self):
        # "阿里巴巴" maps to both BABA and 09988
        code_to_name = {"BABA": "阿里巴巴", "09988": "阿里巴巴", "600519": "贵州茅台"}
        result = _build_reverse_map_no_duplicates(code_to_name)
        assert "阿里巴巴" not in result
        assert result.get("贵州茅台") == "600519"

    def test_includes_unique_names(self):
        code_to_name = {"600519": "贵州茅台", "00700": "腾讯控股"}
        result = _build_reverse_map_no_duplicates(code_to_name)
        assert result["贵州茅台"] == "600519"
        assert result["腾讯控股"] == "00700"


# ---------------------------------------------------------------------------
# resolve_name_to_code
# ---------------------------------------------------------------------------

class TestResolveNameToCode:
    def test_code_like_input_returned_normalized(self):
        assert resolve_name_to_code("600519") == "600519"
        assert resolve_name_to_code("600519.SH") == "600519"
        assert resolve_name_to_code("920493.BJ") == "920493"
        assert resolve_name_to_code("  AAPL  ") == "AAPL"

    def test_local_map_exact_match(self):
        assert resolve_name_to_code("贵州茅台") == "600519"
        assert resolve_name_to_code("腾讯控股") == "00700"

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_local_hit_does_not_trigger_akshare(self, mock_akshare):
        # 本地表精确命中必须零网络：既有调用方（API/Bot/导入）保持
        # 离线低延迟契约，不被 AkShare 冷启动等待拖住。
        assert resolve_name_to_code("贵州茅台") == "600519"
        assert resolve_name_to_code("腾讯控股") == "00700"
        mock_akshare.assert_not_called()

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_local_hit_wins_over_akshare_same_name(self, mock_akshare):
        # 兼容性契约：本地表唯一命中的名字直接返回本地代码，不做跨市场
        # 合并判定（中国移动：本地仅港股 00941，AkShare 有同名 A 股 600941）。
        # 完整跨市场候选由 resolver_name_to_code_list 提供。
        mock_akshare.return_value = {"中国移动": "600941"}
        assert resolve_name_to_code("中国移动") == "00941"
        mock_akshare.assert_not_called()

    def test_returns_none_for_empty_or_invalid_input(self):
        assert resolve_name_to_code("") is None
        assert resolve_name_to_code("   ") is None
        assert resolve_name_to_code(None) is None  # type: ignore

    def test_ambiguous_name_returns_none(self):
        # "阿里巴巴" maps to both BABA and 09988 in STOCK_NAME_MAP
        assert resolve_name_to_code("阿里巴巴") is None

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_akshare_fallback_when_not_in_local(self, mock_akshare):
        mock_akshare.return_value = {"平安银行": "000001"}
        # 000001 is in local map as 平安银行, so we use a name that's only in akshare
        # Actually local has 000001 -> 平安银行. So "平安银行" would hit local first.
        # Use a name not in STOCK_NAME_MAP - e.g. some A-share only in AkShare
        mock_akshare.return_value = {"浦发银行": "600000"}
        result = resolve_name_to_code("浦发银行")
        assert result == "600000"
        mock_akshare.assert_called()

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_fuzzy_match_fallback(self, mock_akshare):
        mock_akshare.return_value = {"贵州茅台": "600519"}
        # Typo: 贵州茅苔 -> should fuzzy match 贵州茅台
        result = resolve_name_to_code("贵州茅苔")
        assert result == "600519"

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_returns_none_when_no_match(self, mock_akshare):
        mock_akshare.return_value = {}
        result = resolve_name_to_code("不存在的股票名称xyz")
        assert result is None

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_skips_akshare_for_non_cjk_garbage_input(self, mock_akshare):
        result = resolve_name_to_code("aaaaaaa")
        assert result is None
        mock_akshare.assert_not_called()

    @pytest.mark.parametrize("clean_db", [{"三一重能": "688349"}], indirect=True)
    def test_akshare_exact_fallback_beats_fuzzy_for_non_local_name(self, clean_db):
        # 本地未收录的 CJK 名称：AkShare 精确命中（第 4 步）优先于模糊
        # 匹配（第 5 步），"三一重能" 不会被误配到相近的 三一重工。
        assert resolve_name_to_code("三一重能") == "688349"


# ---------------------------------------------------------------------------
# Stock dataclass
# ---------------------------------------------------------------------------

class TestStock:
    def test_fields(self):
        s = Stock(code="600519", name="贵州茅台", market="a")
        assert (s.code, s.name, s.market) == ("600519", "贵州茅台", "a")

    def test_value_equality(self):
        assert Stock("600519", "贵州茅台", "a") == Stock("600519", "贵州茅台", "a")
        assert Stock("600519", "贵州茅台", "a") != Stock("00700", "腾讯控股", "hk")


# ---------------------------------------------------------------------------
# resolver_name_to_code_list
# ---------------------------------------------------------------------------

class TestResolverNameToCodeList:
    @pytest.mark.usefixtures("clean_db")
    def test_exact_match(self):
        assert resolver_name_to_code_list("贵州茅台") == [Stock("600519", "贵州茅台", "a")]

    @pytest.mark.usefixtures("clean_db")
    def test_exact_match_cross_market_sorted(self):
        # 阿里巴巴 in STOCK_NAME_MAP: BABA (us) + 09988 (hk) → hk before us
        assert resolver_name_to_code_list("阿里巴巴") == [
            Stock("09988", "阿里巴巴", "hk"),
            Stock("BABA", "阿里巴巴", "us"),
        ]

    @pytest.mark.usefixtures("clean_db")
    def test_substring_match(self):
        assert resolver_name_to_code_list("茅台") == [Stock("600519", "贵州茅台", "a")]

    @pytest.mark.usefixtures("clean_db")
    def test_pinyin_substring_match(self):
        # Non-CJK input: resolved locally via pinyin, without AkShare fetch
        assert resolver_name_to_code_list("maotai") == [Stock("600519", "贵州茅台", "a")]

    @pytest.mark.usefixtures("clean_db")
    def test_cjk_fragment_skips_pinyin_layer(self):
        # 回归：CJK 片段不得走拼音子串层。"平果"拼音 pingguo 与苹果全名
        # 拼音完全相撞，预修复会经策略 3 误命中苹果；CJK 片段的拼音粒度
        # 失控（实义字+助词转拼音后可与不相干全名碰撞，如"阿里的"→
        # "alide" ⊂ "zhongdalide" 中大力德），仅 ASCII 拼音输入走该层。
        assert resolver_name_to_code_list("平果") == []

    @pytest.mark.usefixtures("clean_db")
    def test_fuzzy_typo_match(self):
        assert resolver_name_to_code_list("贵州茅苔") == [Stock("600519", "贵州茅台", "a")]

    @pytest.mark.usefixtures("clean_db")
    def test_no_match_returns_empty(self):
        assert resolver_name_to_code_list("你好世界") == []

    @pytest.mark.usefixtures("clean_db")
    def test_invalid_input_returns_empty(self):
        assert resolver_name_to_code_list("") == []
        assert resolver_name_to_code_list(None) == []  # type: ignore
        assert resolver_name_to_code_list("茅") == []  # single char is never a name

    @pytest.mark.parametrize("clean_db", [{"浦发银行": "600000"}], indirect=True)
    def test_akshare_extension_visible_after_retry(self, clean_db):
        # Exact match against the AkShare-extended database
        assert resolver_name_to_code_list("浦发银行") == [Stock("600000", "浦发银行", "a")]


    @pytest.mark.parametrize("clean_db", [{"阿里巴巴": "600000"}], indirect=True)
    def test_local_exact_hit_still_merges_akshare_same_name_a_share(self, clean_db):
        # 本地已有同名港股/美股时，AkShare 中的同名 A 股也必须被并入。
        ntc.stockDB.clear()
        ntc.stockDB.update({"09988": "阿里巴巴", "BABA": "阿里巴巴"})
        ntc._names_cache[:] = [None, None, None]
        ntc._pinyin_cache[:] = [None, None]
        ntc._akshare_merged = None
        ntc.stockAliases.clear()
        assert resolver_name_to_code_list("阿里巴巴") == [
            Stock("600000", "阿里巴巴", "a"),
            Stock("09988", "阿里巴巴", "hk"),
            Stock("BABA", "阿里巴巴", "us"),
        ]

    @pytest.mark.parametrize("clean_db", [{"阿里巴巴": "600000"}], indirect=True)
    def test_local_single_candidate_gets_a_share_candidate_after_akshare_merge(self, clean_db):
        # 本地只有单一市场记录时，AkShare 补齐同名 A 股后候选变完整。
        ntc.stockDB.clear()
        ntc.stockDB.update({"09988": "阿里巴巴"})
        ntc._names_cache[:] = [None, None, None]
        ntc._pinyin_cache[:] = [None, None]
        ntc._akshare_merged = None
        ntc.stockAliases.clear()
        assert resolver_name_to_code_list("阿里巴巴") == [
            Stock("600000", "阿里巴巴", "a"),
            Stock("09988", "阿里巴巴", "hk"),
        ]

class TestCompactLookupInputs:
    """查询侧同源压平：带内嵌空格的"源形态"输入（如自 AkShare 数据复制的
    "五 粮 液"）与常规无空格拼写同样可解析——入库压平后查询入口若只做
    首尾 strip，源形态输入会在精确/子串/模糊全部层级落空。"""

    @pytest.mark.parametrize("clean_db", [{"五 粮 液": "000858"}], indirect=True)
    def test_spaced_input_resolves_via_list(self, clean_db):
        ntc.extend_AkShare()
        assert resolver_name_to_code_list("五 粮 液") == [
            Stock("000858", "五粮液", "a")
        ]

    @pytest.mark.parametrize("clean_db", [{"五 粮 液": "000858"}], indirect=True)
    def test_spaced_input_is_known_name(self, clean_db):
        ntc.extend_AkShare()
        assert ntc.is_known_stock_name("五 粮 液") is True

    def test_spaced_input_resolves_legacy(self):
        # 本地映射已有无空格拼写：legacy 入口对带空格输入同样命中
        assert resolve_name_to_code("五 粮 液") == "000858"


# ---------------------------------------------------------------------------
# US_stock_code_match
# ---------------------------------------------------------------------------

class TestUSStockCodeMatch:
    def test_known_ticker(self):
        assert US_stock_code_match("AAPL") == [Stock("AAPL", "苹果", "us")]
        assert US_stock_code_match("aapl") == [Stock("AAPL", "苹果", "us")]

    def test_unknown_word_returns_empty(self):
        assert US_stock_code_match("HELLO") == []  # ordinary English word
        assert US_stock_code_match("TOOLONGTICKER") == []
        assert US_stock_code_match("贵州茅台") == []


# ---------------------------------------------------------------------------
# extend_AkShare
# ---------------------------------------------------------------------------

class TestExtendAkShare:
    @pytest.mark.parametrize("clean_db", [{"浦发银行": "600000"}], indirect=True)
    def test_merges_new_entries_idempotently(self, clean_db):
        assert ntc.extend_AkShare() is True
        assert ntc.stockDB["600000"] == "浦发银行"
        # Same cached map object is not merged twice
        assert ntc.extend_AkShare() is False

    @pytest.mark.parametrize("clean_db", [{"贵州茅台": "600519"}], indirect=True)
    def test_no_new_entries_returns_false(self, clean_db):
        # All entries already in the local database
        assert ntc.extend_AkShare() is False

    @pytest.mark.usefixtures("clean_db")
    def test_fetch_failure_returns_false(self):
        assert ntc.extend_AkShare() is False


    @pytest.mark.parametrize("clean_db", [{"新名称": "600000"}], indirect=True)
    def test_rename_existing_code_updates_canonical_name_and_keeps_alias(self, clean_db):
        ntc.stockDB.clear()
        ntc.stockDB.update({"600000": "旧名称"})
        ntc._names_cache[:] = [None, None, None]
        ntc._pinyin_cache[:] = [None, None]
        ntc._akshare_merged = None
        ntc.stockAliases.clear()
        assert ntc.extend_AkShare() is True
        assert ntc.stockDB["600000"] == "新名称"
        assert ntc.stockAliases["600000"] == {"旧名称"}
        # 新名称作为当前官方名称可解析
        assert resolver_name_to_code_list("新名称") == [Stock("600000", "新名称", "a")]
        # 旧名称作为别名仍然可解析，且展示当前官方名称
        assert resolver_name_to_code_list("旧名称") == [Stock("600000", "新名称", "a")]


class TestCompactStockNameMerge:
    """AkShare 名称内嵌空白压平：stockDB 只存无空格拼写。

    带空格名称（"五 粮 液"）与本地无空格拼写（"五粮液"）语义相同：
    压平后比较相等 → 不触发假性改名/别名；全名精确匹配对常规输入可见。
    """

    @pytest.mark.parametrize("clean_db", [{"五 粮 液": "600000"}], indirect=True)
    def test_spaced_akshare_name_compacted(self, clean_db):
        # 600000 不在本地映射：新条目以压平拼写写入（000858 本地已有、
        # 压平后相等属"无变更"路径，见下一条用例）
        assert ntc.extend_AkShare() is True
        assert ntc.stockDB["600000"] == "五粮液"

    @pytest.mark.parametrize("clean_db", [{"五 粮 液": "000858"}], indirect=True)
    def test_spaced_name_vs_local_no_spurious_alias(self, clean_db):
        # 本地已有无空格拼写：压平后相等，不得制造假性别名/假性改名
        ntc.stockDB.clear()
        ntc.stockDB.update({"000858": "五粮液"})
        ntc._names_cache[:] = [None, None, None]
        ntc._akshare_merged = None
        ntc.stockAliases.clear()
        assert ntc.extend_AkShare() is False
        assert ntc.stockDB["000858"] == "五粮液"
        assert "000858" not in ntc.stockAliases

    @pytest.mark.parametrize("clean_db", [{"五 粮 液": "000858"}], indirect=True)
    def test_spaced_name_exact_match_after_merge(self, clean_db):
        # 压平后的规范名对常规无空格输入整名可见（含 Step 3 精确匹配口径）
        ntc.extend_AkShare()
        assert ntc.is_known_stock_name("五粮液") is True
        assert resolver_name_to_code_list("五粮液") == [Stock("000858", "五粮液", "a")]

    @pytest.mark.parametrize(
        "clean_db", [{"   ": "600000", "万  科Ａ": "000002"}], indirect=True
    )
    def test_whitespace_only_name_skipped(self, clean_db):
        # 压平后为空的名称条目跳过，不写入空串；"万  科Ａ" 归一后为
        # "万科A"（NFKC 宽度归一 + 去空白）
        assert ntc.extend_AkShare() is True
        assert ntc.stockDB["000002"] == "万科A"
        assert "600000" not in ntc.stockDB or ntc.stockDB["600000"] != ""


class TestStockNameWidthNormalization:
    """库名宽度归一（_normalize_stock_name = NFKC + 去空白）：源数据的
    全角拼写（AkShare "京东方Ａ"、磁盘缓存历史数据）与 NFKC 归一后的
    用户输入（"京东方A"）必须同源同变换——否则全名精确匹配落空，且会被
    更短的库内名误切（"京东"）。"""

    @pytest.mark.parametrize("clean_db", [{"京东方Ａ": "000725"}], indirect=True)
    def test_akshare_fullwidth_name_normalized_on_merge(self, clean_db):
        # 合并入口归一：全角Ａ名称以半角拼写写入 stockDB
        assert ntc.extend_AkShare() is True
        assert ntc.stockDB["000725"] == "京东方A"

    @pytest.mark.parametrize("clean_db", [{"京东方Ａ": "000725"}], indirect=True)
    def test_fullwidth_and_halfwidth_queries_both_resolve(self, clean_db):
        ntc.extend_AkShare()
        # 查询入口同源归一：全角/半角输入皆可解析，展示名统一为归一拼写
        assert ntc.resolver_name_to_code_list("京东方A") == [
            Stock("000725", "京东方A", "a")
        ]
        assert ntc.resolver_name_to_code_list("京东方Ａ") == [
            Stock("000725", "京东方A", "a")
        ]
        assert ntc.is_known_stock_name("京东方Ａ") is True

    @pytest.mark.parametrize("clean_db", [{"京东方A": "000725"}], indirect=True)
    def test_legacy_fullwidth_input_resolves(self, clean_db):
        # legacy 入口查询归一（生产缓存侧名称经 _build_name_map_from_df
        # 已归一，mock 按生产形态给出半角键）
        assert ntc.resolve_name_to_code("京东方Ａ") == "000725"

    def test_local_name_indexes_normalized(self):
        # 构建器内部归一：全角拼写输入的索引键为半角
        unique, ambiguous = ntc._build_local_name_indexes({"000725": "京东方Ａ"})
        assert unique == {"京东方A": "000725"}
        assert ambiguous == set()

    @pytest.mark.usefixtures("real_akshare_path")
    def test_disk_cache_names_normalized_on_load(self):
        # 磁盘缓存里的历史未归一名称：加载即归一（零网络，落盘时间戳新鲜）
        import json
        import time as time_mod

        ntc._akshare_disk_checked = False
        ntc._AKSHARE_DISK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ntc._AKSHARE_DISK_CACHE_PATH.write_text(
            json.dumps(
                {"ts": time_mod.time(), "map": {"京东方Ａ": "000725"}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        assert ntc._get_akshare_name_to_code() == {"京东方A": "000725"}

# ---------------------------------------------------------------------------
# AkShare 单飞并发：真实 _get_akshare_name_to_code + _fetch_akshare_df 假拉取
# ---------------------------------------------------------------------------


class _FakeAkShareFetch:
    """确定性的 _fetch_akshare_df 替身。

    每次调用先置位 fetch_started（证明拉取已在后台线程开始），再阻塞在
    release_fetch 上——测试据此精确控制拉取窗口，不依赖 sleep 计时。
    """

    def __init__(self, fail: bool = False, rows: Optional[dict] = None):
        self.fetch_started = threading.Event()
        self.release_fetch = threading.Event()
        self.fail = fail
        self.rows = rows or {"code": ["600000"], "name": ["浦发银行"]}
        self.calls = 0

    def fetch(self):
        self.calls += 1
        self.fetch_started.set()
        # 30s 兜底：用例逻辑正确时总会在收尾前 set，防自身缺陷挂死线程
        self.release_fetch.wait(timeout=30)
        if self.fail:
            raise RuntimeError("simulated akshare failure")
        return pd.DataFrame(self.rows)


@pytest.fixture()
def real_akshare_path(monkeypatch, tmp_path):
    """复位 AkShare 拉取相关全局态，走真实 _get_akshare_name_to_code 路径。

    磁盘缓存指向临时路径：既隔离仓库 data/cache 下的真实文件，也让
    落盘/懒加载用例可以安全读写。
    """
    saved = (
        ntc._akshare_cache,
        ntc._akshare_failure_cache,
        ntc._akshare_merged,
        ntc._akshare_inflight,
        ntc._akshare_disk_checked,
    )
    ntc._akshare_cache = None
    ntc._akshare_failure_cache = None
    ntc._akshare_merged = None
    ntc._akshare_inflight = None
    ntc._akshare_disk_checked = False
    monkeypatch.setattr(ntc, "_AKSHARE_DISK_CACHE_PATH", tmp_path / "akshare_name_map.json")
    yield monkeypatch
    # 等待在途刷新收尾（正常用例在 finally 里已 release，这里毫秒级通过），
    # 避免迟到的 worker 把缓存写进下一个用例
    deadline = time.time() + 5
    while ntc._akshare_inflight is not None and time.time() < deadline:
        time.sleep(0.05)
    ntc._akshare_cache, ntc._akshare_failure_cache, ntc._akshare_merged = saved[:3]
    ntc._akshare_inflight, ntc._akshare_disk_checked = saved[3:]
    ntc.stockDB.clear()
    ntc.stockDB.update(
        {c: ntc._normalize_stock_name(n) for c, n in STOCK_NAME_MAP.items()}
    )
    ntc._names_cache[:] = [None, None, None]
    ntc._pinyin_cache[:] = [None, None]
    ntc.stockAliases.clear()


def _run_resolver_in_thread(query: str):
    """在 daemon 线程里执行解析，捕获返回值/异常。"""
    outcome = {}

    def _worker():
        try:
            outcome["value"] = ntc.resolver_name_to_code_list(query)
        except BaseException as exc:  # noqa: BLE001 - 线程异常兜底
            outcome["error"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t, outcome


def _wait_until(condition, timeout: float = 5.0) -> bool:
    """有界轮询等待条件成立（后台刷新收尾是确定性事件，仅耗时不定）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


class TestAkShareSingleFlightConcurrency:
    @pytest.mark.usefixtures("real_akshare_path")
    def test_waiter_resolves_after_inflight_fetch_completes(self, monkeypatch):
        fake = _FakeAkShareFetch()
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)

        t1, r1 = _run_resolver_in_thread("浦发银行")
        t2 = None
        try:
            assert fake.fetch_started.wait(timeout=5)
            t2, r2 = _run_resolver_in_thread("浦发银行")
            # 旧实现（非阻塞放弃）在此窗口内立即返回空结果；新实现持续等待
            t2.join(timeout=2)
            # 释放前两个线程必须仍在等待（而非已带空结果返回）——漏解 bug 的核心
            assert t1.is_alive() and t2.is_alive()
        finally:
            fake.release_fetch.set()
            t1.join(timeout=10)
            if t2 is not None:
                t2.join(timeout=10)
        assert not t1.is_alive() and not t2.is_alive()
        # 等待者命中在途拉取的结果（本 bug 的核心断言），且全进程只拉取一次
        assert r1.get("value") == [Stock("600000", "浦发银行", "a")]
        assert r2.get("value") == [Stock("600000", "浦发银行", "a")]
        assert fake.calls == 1

    @pytest.mark.usefixtures("real_akshare_path")
    def test_waiter_returns_empty_after_inflight_failure_and_no_refetch(self, monkeypatch):
        fake = _FakeAkShareFetch(fail=True)
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)

        t1, r1 = _run_resolver_in_thread("浦发银行")
        t2 = None
        try:
            assert fake.fetch_started.wait(timeout=5)
            t2, r2 = _run_resolver_in_thread("浦发银行")
            t2.join(timeout=2)
        finally:
            fake.release_fetch.set()
            t1.join(timeout=10)
            if t2 is not None:
                t2.join(timeout=10)
        assert not t1.is_alive() and not t2.is_alive()
        # 在途拉取失败：等待者醒来命中失败退避（而非重试风暴），本地空库返回 []
        assert r1.get("value") == []
        assert r2.get("value") == []
        assert fake.calls == 1
        assert ntc._akshare_failure_cache is not None

    @pytest.mark.usefixtures("real_akshare_path")
    def test_cold_waiters_degrade_after_timeout_but_fetch_lands(self, monkeypatch):
        # worker 违约（超清账余量仍未 resolve）时的兜底路径：等待者按死线
        # 自行降级，后台拉取不受影响仍单次完成落地
        monkeypatch.setattr(ntc, "_AKSHARE_WAIT_COLD_START", 0.2)
        fake = _FakeAkShareFetch()
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)

        t1, r1 = _run_resolver_in_thread("浦发银行")
        t2 = None
        try:
            assert fake.fetch_started.wait(timeout=5)
            t2, r2 = _run_resolver_in_thread("浦发银行")
            # 拉取持续挂起时，所有冷启动等待者（含触发拉取的那一个）都必须
            # 在超时上界内自行返回，而非无限等待
            t1.join(timeout=10)
            t2.join(timeout=10)
            # 必须在放行抓取前确认两个等待者均已降级；仅等待 t2 不能
            # 保证 t1 已返回，否则 finally 放行后 t1 可能拿到成功结果。
            assert not t1.is_alive() and not t2.is_alive()
            assert r1.get("value") == []
            assert r2.get("value") == []
        finally:
            fake.release_fetch.set()
            t1.join(timeout=10)
            if t2 is not None:
                t2.join(timeout=10)
        assert not t1.is_alive() and not t2.is_alive()
        # 后台拉取不受等待者超时影响，仍单次完成
        assert fake.calls == 1
        assert _wait_until(
            lambda: ntc._akshare_cache is not None
            and ntc._akshare_cache[1] == {"浦发银行": "600000"}
        )
        # 拉取落地后，后续请求立即命中新缓存
        assert ntc.resolver_name_to_code_list("浦发银行") == [Stock("600000", "浦发银行", "a")]

    @pytest.mark.usefixtures("real_akshare_path")
    def test_slow_persist_does_not_delay_waiter_wakeup(self, monkeypatch):
        # 唤醒在落盘之前：慢磁盘不得拖住等待者拿结果（缓存已就绪、
        # 等待者却超时漏解曾是真实回归）
        fake = _FakeAkShareFetch()
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)
        release_persist = threading.Event()
        monkeypatch.setattr(
            ntc, "_persist_akshare_map", lambda map_: release_persist.wait(timeout=30)
        )

        t1, r1 = _run_resolver_in_thread("浦发银行")
        try:
            assert fake.fetch_started.wait(timeout=5)
            fake.release_fetch.set()
            # 拉取完成即唤醒并返回，不等落盘
            t1.join(timeout=5)
            assert not t1.is_alive()
            assert r1.get("value") == [Stock("600000", "浦发银行", "a")]
            assert not release_persist.is_set()  # 落盘仍挂着，等待者已返回
        finally:
            release_persist.set()
            t1.join(timeout=10)

    @pytest.mark.usefixtures("real_akshare_path")
    def test_base_exception_still_clears_inflight_and_arms_backoff(self, monkeypatch):
        # finally 兜底：BaseException（如 KeyboardInterrupt/SystemExit）逃逸
        # 时也必须清在途句柄、武装退避并唤醒等待者，不留死句柄
        class _Bomb(BaseException):
            pass

        def bomb():
            raise _Bomb

        # 接管 excepthook：既静音 worker 死亡时的未处理异常输出，又给出
        # "worker 已带着 _Bomb 死亡"的确定性信号（不依赖全局线程状态，
        # 避免被其他用例泄漏的后台刷新线程干扰）
        hook_calls: list = []
        monkeypatch.setattr(threading, "excepthook", lambda args: hook_calls.append(args))
        monkeypatch.setattr(ntc, "_fetch_akshare_df", bomb)
        t1, r1 = _run_resolver_in_thread("浦发银行")
        t1.join(timeout=10)
        assert not t1.is_alive()
        assert _wait_until(lambda: hook_calls)  # worker 已触发 excepthook
        assert r1.get("value") == []  # 等待者被 finally 唤醒后拿到 None
        assert ntc._akshare_inflight is None  # 无死句柄
        assert ntc._akshare_failure_cache is not None  # 退避已武装
        assert ntc._get_akshare_name_to_code() is None  # 退避窗口内不再触网


# ---------------------------------------------------------------------------
# Stale-while-revalidate：TTL 过期必须立即返回旧值（零等待），刷新在后台
# 完成；网络故障的退避窗口内旧值继续服务（可用性），仅冷启动才退化。
# ---------------------------------------------------------------------------


class TestAkShareStaleWhileRevalidate:
    @pytest.mark.usefixtures("real_akshare_path")
    def test_stale_served_immediately_while_refresh_inflight(self, monkeypatch):
        # 先用立即返回的假拉取把缓存填充为 v1
        primed = {"浦发银行": "600000"}

        def fetch_v1():
            return pd.DataFrame({"code": ["600000"], "name": ["浦发银行"]})

        monkeypatch.setattr(ntc, "_fetch_akshare_df", fetch_v1)
        assert ntc._get_akshare_name_to_code() == primed
        # 强制过期：时间戳拨回 TTL 之前
        ntc._akshare_cache = (time.time() - ntc._AKSHARE_CACHE_TTL - 10, primed)

        # 换成阻塞版拉取（v2：600000 改名为 新名称银行）
        fake = _FakeAkShareFetch(rows={"code": ["600000"], "name": ["新名称银行"]})
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)

        started = time.monotonic()
        result = ntc._get_akshare_name_to_code()
        elapsed = time.monotonic() - started
        try:
            # 核心断言：stale 值立即返回，没有等待在途拉取
            assert result == primed
            assert elapsed < 2
            # 后台刷新确实已发起且尚未完成（fake 仍被挂起）
            assert fake.fetch_started.wait(timeout=5)
            assert not fake.release_fetch.is_set()
        finally:
            fake.release_fetch.set()
        # 刷新收尾后新缓存可见，且全进程只拉取一次
        v2 = {"新名称银行": "600000"}
        assert _wait_until(lambda: ntc._akshare_cache is not None and ntc._akshare_cache[1] == v2)
        assert fake.calls == 1
        assert ntc._get_akshare_name_to_code() == v2

    @pytest.mark.usefixtures("real_akshare_path")
    def test_backoff_window_serves_stale_during_outage(self, monkeypatch):
        # 预热缓存 v1 并强制过期
        primed = {"浦发银行": "600000"}

        def fetch_ok():
            return pd.DataFrame({"code": ["600000"], "name": ["浦发银行"]})

        monkeypatch.setattr(ntc, "_fetch_akshare_df", fetch_ok)
        assert ntc._get_akshare_name_to_code() == primed
        ntc._akshare_cache = (time.time() - ntc._AKSHARE_CACHE_TTL - 10, primed)

        # 换成立即失败的拉取：第一次 stale 调用会发起后台刷新并失败
        calls = {"n": 0}

        def fetch_fail():
            calls["n"] += 1
            raise RuntimeError("simulated outage")

        monkeypatch.setattr(ntc, "_fetch_akshare_df", fetch_fail)
        assert ntc._get_akshare_name_to_code() == primed  # 故障期间旧值仍可用
        assert _wait_until(lambda: ntc._akshare_failure_cache is not None)
        # 退避窗口内再次调用：继续服务 stale，且不再发起新的拉取
        assert ntc._get_akshare_name_to_code() == primed
        assert calls["n"] == 1


# ---------------------------------------------------------------------------
# 磁盘缓存：成功拉取后原子落盘；重启（全局态复位）后懒加载，零网络。
# ---------------------------------------------------------------------------


class TestAkShareDiskCache:
    @pytest.mark.usefixtures("real_akshare_path")
    def test_persist_and_reload_without_network(self, monkeypatch):
        def fetch_ok():
            return pd.DataFrame({"code": ["600000"], "name": ["浦发银行"]})

        monkeypatch.setattr(ntc, "_fetch_akshare_df", fetch_ok)
        assert ntc._get_akshare_name_to_code() == {"浦发银行": "600000"}
        assert _wait_until(lambda: ntc._AKSHARE_DISK_CACHE_PATH.is_file())

        # 模拟重启：内存态全部复位，磁盘保留
        ntc._akshare_cache = None
        ntc._akshare_failure_cache = None
        ntc._akshare_disk_checked = False

        never = _FakeAkShareFetch()
        monkeypatch.setattr(ntc, "_fetch_akshare_df", never.fetch)
        # 懒加载直接命中（落盘时间戳新鲜），全程零网络
        assert ntc._get_akshare_name_to_code() == {"浦发银行": "600000"}
        assert never.calls == 0

    @pytest.mark.usefixtures("real_akshare_path")
    def test_corrupt_disk_cache_ignored(self, monkeypatch):
        ntc._AKSHARE_DISK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ntc._AKSHARE_DISK_CACHE_PATH.write_text("not-a-json{", encoding="utf-8")

        calls = {"n": 0}

        def fetch_ok():
            calls["n"] += 1
            return pd.DataFrame({"code": ["600000"], "name": ["浦发银行"]})

        monkeypatch.setattr(ntc, "_fetch_akshare_df", fetch_ok)
        # 损坏的磁盘缓存被忽略，正常走冷启动拉取
        assert ntc._get_akshare_name_to_code() == {"浦发银行": "600000"}
        assert calls["n"] == 1


# ---------------------------------------------------------------------------
# 预热：幂等——并发/重复调用共享同一在途句柄，只触发一次网络拉取。
# ---------------------------------------------------------------------------


class TestWarmupIdempotent:
    @pytest.mark.usefixtures("real_akshare_path")
    def test_double_warmup_shares_single_fetch(self, monkeypatch):
        fake = _FakeAkShareFetch()
        monkeypatch.setattr(ntc, "_fetch_akshare_df", fake.fetch)

        ntc.warmup_akshare_cache()
        assert fake.fetch_started.wait(timeout=5)  # 在途句柄已登记
        ntc.warmup_akshare_cache()  # 第二次：共享 Future，不再拉取
        fake.release_fetch.set()

        assert _wait_until(
            lambda: ntc._akshare_cache is not None
            and ntc._akshare_cache[1] == {"浦发银行": "600000"}
        )
        assert fake.calls == 1


# ---------------------------------------------------------------------------
# 挂起（非失败）场景：子进程超时包装以 TimeoutError 抛出后，必须走
# 常规失败路径武装退避，而非无限持有单飞锁。
# ---------------------------------------------------------------------------


class TestAkShareHangBackoff:
    @pytest.mark.usefixtures("real_akshare_path")
    def test_timeout_error_arms_failure_backoff(self, monkeypatch):
        calls = []

        def hang():
            calls.append(1)
            # 与 _akshare_call_with_timeout 超时抛出的异常同型
            raise TimeoutError("stock_info_a_code_name 调用超过 25s，已放弃等待")

        monkeypatch.setattr(ntc, "_fetch_akshare_df", hang)
        assert ntc._get_akshare_name_to_code() is None
        assert ntc._akshare_failure_cache is not None  # 退避已武装
        # 退避窗口内再次解析：命中失败缓存快路径，不再触网
        assert ntc._get_akshare_name_to_code() is None
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# _fetch_akshare_df 接线：必须经子进程超时包装调用 worker（挂起封顶）。
# ---------------------------------------------------------------------------


class TestFetchAkshareDfWiring:
    def test_delegates_to_subprocess_timeout_wrapper(self, monkeypatch):
        import data_provider.akshare_fetcher as af

        captured = {}

        def fake_wrapper(func, *args, **kwargs):
            captured["func"] = func
            captured["timeout"] = kwargs.get("timeout")
            captured["call_name"] = kwargs.get("call_name")
            return pd.DataFrame({"code": ["600000"], "name": ["浦发银行"]})

        monkeypatch.setattr(af, "_akshare_call_with_timeout", fake_wrapper)
        df = ntc._fetch_akshare_df()
        assert captured["func"] is ntc._akshare_stock_info_worker
        assert captured["timeout"] == ntc._AKSHARE_FETCH_TIMEOUT
        assert captured["call_name"] == "stock_info_a_code_name"
        assert list(df["name"]) == ["浦发银行"]

