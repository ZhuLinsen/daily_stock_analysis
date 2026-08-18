# -*- coding: utf-8 -*-
"""Tests for name_to_code_resolver.

Covers:
- Local mapping (STOCK_NAME_MAP reverse)
- Code format boundary (_is_code_like, _normalize_code)
- Pinyin match (when pypinyin available)
- AkShare fallback (mocked)
- Fuzzy match (difflib)
- Ambiguous names return None
- List resolver (resolver_name_to_code_list: exact/substring/sorting/limits)
- US ticker match (US_stock_code_match)
- Stock dataclass (dict-style access, equality)
- is_known_stock_name / extract_stock_name (pure-local name recognition)
- extend_AkShare (stockDB merge + idempotency)
"""

import pytest
from unittest.mock import patch

import src.services.name_to_code_resolver as resolver_mod

from src.services.name_to_code_resolver import (
    resolve_name_to_code,
    resolver_name_to_code_list,
    US_stock_code_match,
    Stock,
    is_known_stock_name,
    extract_stock_name,
    extend_AkShare,
    _is_code_like,
    _normalize_code,
    _build_reverse_map_no_duplicates,
)


def _pypinyin_available() -> bool:
    try:
        import pypinyin  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture(autouse=True)
def _restore_name_resolver_state():
    """Snapshot and restore module-level mutable state around each test.

    name_to_code_resolver keeps a process-wide stockDB plus an AkShare
    cache/merge guard; tests that mock AkShare data would otherwise leak
    entries into the shared database and break later tests.
    """
    db = dict(resolver_mod.stockDB)
    cache = resolver_mod._akshare_cache
    merged = resolver_mod._akshare_merged
    yield
    resolver_mod.stockDB.clear()
    resolver_mod.stockDB.update(db)
    resolver_mod._akshare_cache = cache
    resolver_mod._akshare_merged = merged


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

    def test_returns_none_for_empty_or_invalid_input(self):
        assert resolve_name_to_code("") is None
        assert resolve_name_to_code("   ") is None
        assert resolve_name_to_code(None) is None  # type: ignore

    def test_ambiguous_name_returns_none(self):
        # "阿里巴巴" maps to both BABA and 09988 in STOCK_NAME_MAP
        assert resolve_name_to_code("阿里巴巴") is None

    def test_ambiguous_substring_multi_candidate_returns_none(self):
        # 子串匹配产生的多候选同样必须返回 None：
        # 修复前仅拦截精确同名歧义，以下输入会静默返回排序后第一只
        # （"阿里"→09988、"银行"→000001、"汽车"→09868）。
        assert resolve_name_to_code("阿里") is None
        assert resolve_name_to_code("银行") is None
        assert resolve_name_to_code("汽车") is None

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_akshare_extension_multi_candidate_returns_none(self, mock_akshare):
        # AkShare 扩展后子串命中多只 → 同样必须返回 None，绝不取第一只
        # （本地库外的名称只有扩展后才出现多候选）。
        mock_akshare.return_value = {
            "测试银行甲": "999990",
            "测试银行乙": "999991",
        }
        assert resolve_name_to_code("测试银行") is None

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_akshare_exact_name_beats_local_fuzzy_singleton(self, mock_akshare, monkeypatch):
        # OR-COR-a2d5f6b9：本地库里的近似名（单字之差）不得抢占本地缺失、
        # AkShare 独有的精确 A 股名——修复前"测试银行乙"被本地模糊匹配
        # 静默解析到"测试银行甲"的代码，AkShare 精确条目永远没机会胜出。
        monkeypatch.setattr(resolver_mod, "stockDB", {"111111": "测试银行甲"})
        mock_akshare.return_value = {"测试银行乙": "222222"}
        assert resolve_name_to_code("测试银行乙") == "222222"

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_local_fuzzy_singleton_kept_when_akshare_lacks_exact_name(self, mock_akshare, monkeypatch):
        # 反向保护：AkShare 没有精确名时，本地模糊 singleton 容错行为保留
        # （与 test_fuzzy_match_fallback 的"贵州茅苔"→600519 契约一致）。
        monkeypatch.setattr(resolver_mod, "stockDB", {"111111": "测试银行甲"})
        mock_akshare.return_value = {"无关个股": "333333"}
        assert resolve_name_to_code("测试银行乙") == "111111"

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


# ---------------------------------------------------------------------------
# Pinyin match (skipped when pypinyin is unavailable)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _pypinyin_available(), reason="pypinyin not installed")
class TestPinyinMatch:
    def test_resolves_full_pinyin(self):
        # maotai ⊂ guizhoumaotai (贵州茅台)
        assert resolve_name_to_code("maotai") == "600519"

    def test_resolves_concatenated_pinyin(self):
        assert resolve_name_to_code("guizhoumaotai") == "600519"

    def test_list_resolver_pinyin(self):
        stocks = resolver_name_to_code_list("maotai")
        assert [(s.code, s.market) for s in stocks] == [("600519", "a")]

    def test_list_resolver_pinyin_case_insensitive(self):
        stocks = resolver_name_to_code_list("MAOTAI")
        assert [(s.code, s.market) for s in stocks] == [("600519", "a")]


# ---------------------------------------------------------------------------
# resolver_name_to_code_list
# ---------------------------------------------------------------------------

class TestResolverNameToCodeList:
    def test_exact_name_single_result(self):
        stocks = resolver_name_to_code_list("贵州茅台")
        assert [(s.code, s.market) for s in stocks] == [("600519", "a")]

    def test_substring_match(self):
        # 茅台 ⊂ 贵州茅台
        stocks = resolver_name_to_code_list("茅台")
        assert [(s.code, s.market) for s in stocks] == [("600519", "a")]

    def test_ambiguous_exact_name_all_candidates_sorted(self):
        # Sorted A → HK → US: 09988(hk) before BABA(us)
        stocks = resolver_name_to_code_list("阿里巴巴")
        assert [(s.code, s.market) for s in stocks] == [("09988", "hk"), ("BABA", "us")]

    def test_ambiguous_substring_all_candidates_sorted(self):
        stocks = resolver_name_to_code_list("阿里")
        assert [(s.code, s.market) for s in stocks] == [("09988", "hk"), ("BABA", "us")]

    def test_single_cjk_char_short_circuits(self):
        assert resolver_name_to_code_list("好") == []

    def test_empty_and_none_input(self):
        assert resolver_name_to_code_list("") == []
        assert resolver_name_to_code_list(None) == []
        assert resolver_name_to_code_list("   ") == []

    def test_truncates_to_five_results(self, monkeypatch):
        fake_db = {f"1{i:05d}": "多码股" for i in range(1, 9)}
        monkeypatch.setattr(resolver_mod, "stockDB", fake_db)
        stocks = resolver_name_to_code_list("多码股")
        assert len(stocks) == 5
        assert all(s.market == "a" for s in stocks)


# ---------------------------------------------------------------------------
# US_stock_code_match
# ---------------------------------------------------------------------------

class TestUSStockCodeMatch:
    def test_known_ticker(self):
        stocks = US_stock_code_match("TSLA")
        assert [(s.code, s.market) for s in stocks] == [("TSLA", "us")]

    def test_lowercase_ticker_uppercased(self):
        stocks = US_stock_code_match("tsla")
        assert [(s.code, s.market) for s in stocks] == [("TSLA", "us")]

    def test_unknown_ticker_not_in_db(self):
        assert US_stock_code_match("SOFI") == []

    def test_ordinary_word_not_treated_as_code(self):
        assert US_stock_code_match("OK") == []

    def test_rejects_invalid_format(self):
        assert US_stock_code_match("AAPL1") == []  # not pure alpha
        assert US_stock_code_match("ABCDEF") == []  # > 5 letters
        assert US_stock_code_match("") == []
        assert US_stock_code_match("   ") == []


# ---------------------------------------------------------------------------
# Stock dataclass
# ---------------------------------------------------------------------------

class TestStockDataclass:
    def test_dict_style_access(self):
        stock = Stock("600519", "贵州茅台", "a")
        assert stock["code"] == "600519"
        assert stock["name"] == "贵州茅台"
        assert stock["market"] == "a"

    def test_key_error_on_unknown_key(self):
        with pytest.raises(KeyError):
            _ = Stock("600519", "贵州茅台", "a")["unknown"]

    def test_equality(self):
        stock = Stock("600519", "贵州茅台", "a")
        assert stock == Stock("600519", "贵州茅台", "a")
        assert stock == {"code": "600519", "name": "贵州茅台", "market": "a"}
        assert stock == "600519"

    def test_inequality(self):
        stock = Stock("600519", "贵州茅台", "a")
        assert stock != Stock("00700", "腾讯控股", "hk")
        assert stock != {"code": "00700", "name": "腾讯控股", "market": "hk"}
        assert stock != "00700"
        assert stock != 123

    def test_repr(self):
        assert repr(Stock("600519", "贵州茅台", "a")) == "Stock(code='600519', name='贵州茅台', market='a')"


# ---------------------------------------------------------------------------
# is_known_stock_name
# ---------------------------------------------------------------------------

class TestIsKnownStockName:
    def test_exact_name(self):
        assert is_known_stock_name("贵州茅台") is True

    def test_substring_of_stock_name(self):
        assert is_known_stock_name("茅台") is True

    def test_unknown_name(self):
        assert is_known_stock_name("你好股份") is False

    def test_invalid_inputs(self):
        assert is_known_stock_name("") is False
        assert is_known_stock_name("   ") is False
        assert is_known_stock_name("贵") is False  # too short
        assert is_known_stock_name(None) is False
        assert is_known_stock_name(123) is False


# ---------------------------------------------------------------------------
# extract_stock_name
# ---------------------------------------------------------------------------

class TestExtractStockName:
    def test_segments_known_and_unknown(self):
        segments = extract_stock_name("分析下贵州茅台")
        assert segments[0] == ("分析下", None)
        fragment, stocks = segments[1]
        assert fragment == "贵州茅台"
        assert [(s.code, s.market) for s in stocks] == [("600519", "a")]

    def test_longest_name_matched_first(self):
        # 茅台 is not a standalone entry, only the full 贵州茅台 is matched
        segments = extract_stock_name("贵州茅台怎么样")
        assert [(f, [(s.code, s.market) for s in st] if st else None) for f, st in segments] == [
            ("贵州茅台", [("600519", "a")]),
            ("怎么样", None),
        ]

    def test_no_match_passthrough(self):
        assert extract_stock_name("你好呀") == [("你好呀", None)]

    def test_empty_input(self):
        assert extract_stock_name("") == []
        assert extract_stock_name(None) == []


# ---------------------------------------------------------------------------
# extend_AkShare
# ---------------------------------------------------------------------------

class TestExtendAkShare:
    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_adds_new_entries(self, mock_get):
        mock_get.return_value = {"新股票": "888888"}
        assert extend_AkShare() is True
        assert resolver_mod.stockDB.get("888888") == "新股票"

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_idempotent_same_data(self, mock_get):
        data = {"新股票": "888888"}
        mock_get.return_value = data
        assert extend_AkShare() is True
        assert extend_AkShare() is False  # same dict object already merged

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_no_data_returns_false(self, mock_get):
        mock_get.return_value = None
        assert extend_AkShare() is False
        mock_get.return_value = {}
        assert extend_AkShare() is False

    @patch("src.services.name_to_code_resolver._get_akshare_name_to_code")
    def test_refreshed_cache_without_new_entries_returns_false(self, mock_get):
        mock_get.return_value = {"新股票": "888888"}
        assert extend_AkShare() is True
        # TTL 过期后重新拉取返回新 dict 但无新条目：不需要再扩展 → False
        mock_get.return_value = dict({"新股票": "888888"})
        assert extend_AkShare() is False
        assert resolver_mod.stockDB.get("888888") == "新股票"
