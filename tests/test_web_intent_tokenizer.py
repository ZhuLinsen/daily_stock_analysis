# -*- coding: utf-8 -*-
"""web_intent_tokenizer 六步分词管道单测。

只测分词与实体提取（不涉及 WebIntentResolver 的意图判定）：
  Step 1   股票全名精确扫描（_split_by_stock_entities，管道首步，入口扩展）
  Step 2   特殊标点切分（仅作用于 Step 1 的 gap）
  Step 3   代码形提取（_split_by_codes：裸数字 → unknown_number）
  Step 4   市场词提取（_split_market_tokens，"股"+"份"消歧）
  Step 5   无歧义关键词（_tokenize_by_clean_keywords）
  Step 6   多策略 DFS 匹配（_multi_match；板块词先于 DFS 整体 sector）
  代码辨认 _identify_stock_codes（unknown_code → stock_code 附三元组 /
  wrong_{market}_code / unknown_{market}_code）

AkShare 扩展在管道 Step 1 入口触发（幂等），测试 mock 为最小全量 A 股
数据（_MOCK_AKSHARE_A_SHARES）保证离线确定性；mock 之外的库外名称仍不可
解析。
"""

from unittest.mock import patch

import pytest

from src.agent.web_intent_tokenizer import (
    Token,
    _extract_markets_from_tokens,
    _identify_stock_codes,
    _is_identified_token,
    _market_of_code,
    _multi_match,
    _preprocess_text,
    _split_by_codes,
    _split_by_stock_entities,
    _split_market_tokens,
    _tokenize_by_clean_keywords,
)
from src.services.name_to_code_resolver import (
    Stock,
    is_known_stock_name,
    resolver_name_to_code_list,
)
from src.agent.web_intent_types import (
    Market,
    TAG_ACTION_RESEARCH,
    TAG_COMPARISON,
    TAG_CORP_SUFFIX,
    TAG_FILLER,
    TAG_QUESTION,
    TAG_REQUEST,
    TAG_SECTOR,
    TAG_SECTOR_NAME,
    TAG_SECTOR_N_STOCK,
    TAG_STOCK_CODE,
    TAG_STOCK_NAME,
    TAG_SUBJECT_MARKET,
    TAG_SUBJECT_MARKET_BROAD,
    TAG_SUBJECT_INDEX,
    TAG_SUBJECT_RESEARCH,
    TAG_UNKNOWN_CODE,
    TAG_UNKNOWN_NUMBER,
    unknown_code_tag,
    wrong_code_tag,
)

# AkShare 扩展由下游 resolver_name_to_code_list 的 CJK 路径触发（分词层不扩展）。
# 本测试模块 mock 一份最小全量 A 股数据：确定、离线、不依赖真实网络。
_MOCK_AKSHARE_A_SHARES = {
    "酒鬼酒": "000799",
    "三花智控": "002050",
    "中大力德": "002896",
}


@pytest.fixture(autouse=True)
def _mock_akshare_extension():
    with patch(
        "src.services.name_to_code_resolver._get_akshare_name_to_code",
        return_value=_MOCK_AKSHARE_A_SHARES,
    ):
        yield


@pytest.fixture(autouse=True)
def _restore_resolver_state():
    """快照/还原 name_to_code_resolver 模块级可变状态，用例间互不泄漏。"""
    from src.services import name_to_code_resolver as resolver_mod

    db = dict(resolver_mod.stockDB)
    aliases = {code: set(names) for code, names in resolver_mod.stockAliases.items()}
    merged = resolver_mod._akshare_merged
    yield
    resolver_mod.stockDB.clear()
    resolver_mod.stockDB.update(db)
    resolver_mod.stockAliases.clear()
    resolver_mod.stockAliases.update(aliases)
    resolver_mod._akshare_merged = merged
    # stockDB 原地增删，按对象身份缓存的名称/拼音列表可能已陈旧，强制重建
    resolver_mod._names_cache[:] = [None, None, None]
    resolver_mod._pinyin_cache[:] = [None, None]


# =========================================================================
# Step 3 — 代码形提取
# =========================================================================

class TestSplitByCodes:
    """任意位裸数字在 _split_by_codes 阶段直接打 unknown_number；
    带交易所前缀/后缀与美股 ticker 形态打 unknown_code。"""

    def test_year_tag(self):
        assert _split_by_codes("2024") == [Token("2024", TAG_UNKNOWN_NUMBER)]

    def test_month_tag(self):
        assert _split_by_codes("12") == [Token("12", TAG_UNKNOWN_NUMBER)]

    def test_bare_4digit_tag(self):
        assert _split_by_codes("0070") == [Token("0070", TAG_UNKNOWN_NUMBER)]

    def test_bare_5digit_tag(self):
        assert _split_by_codes("00700") == [Token("00700", TAG_UNKNOWN_NUMBER)]

    def test_bare_6digit_tag(self):
        assert _split_by_codes("600519") == [Token("600519", TAG_UNKNOWN_NUMBER)]

    def test_bare_7digit_tag(self):
        assert _split_by_codes("6005199") == [Token("6005199", TAG_UNKNOWN_NUMBER)]

    def test_hk_suffix_still_unknown_code(self):
        assert _split_by_codes("1234.HK") == [Token("1234.HK", TAG_UNKNOWN_CODE)]

    def test_sz_suffix_still_unknown_code(self):
        assert _split_by_codes("0070.SZ") == [Token("0070.SZ", TAG_UNKNOWN_CODE)]

    def test_hk_prefix_still_unknown_code(self):
        assert _split_by_codes("HK12") == [Token("HK12", TAG_UNKNOWN_CODE)]

    def test_sh_prefix_form(self):
        assert _split_by_codes("SH600519") == [Token("SH600519", TAG_UNKNOWN_CODE)]

    def test_us_ticker_form(self):
        assert _split_by_codes("BABA") == [Token("BABA", TAG_UNKNOWN_CODE)]

    def test_us_suffix_case_insensitive(self):
        assert _split_by_codes("aapl.us") == [Token("aapl.us", TAG_UNKNOWN_CODE)]

    def test_date_splits_into_three_number_tokens(self):
        tokens = _split_by_codes("2024-08-12")
        assert [t.tag for t in tokens if t.tag] == [TAG_UNKNOWN_NUMBER] * 3
        # "-" 不在标点切分集合（可能出现在代码/名称中），作为间隙 token 保留
        assert [t.text for t in tokens if not t.tag] == ["-", "-"]

    def test_overlapping_spans_merge_to_longest(self):
        # "HK3294384923"：前缀正则 (0,12) 与裸数字正则 (2,12) 合并为最长 span
        assert _split_by_codes("HK3294384923") == [
            Token("HK3294384923", TAG_UNKNOWN_CODE),
        ]

    def test_gap_text_preserved_as_untagged_token(self):
        tokens = _split_by_codes("分析一下600519.SH")
        assert tokens == [
            Token("分析一下"),
            Token("600519.SH", TAG_UNKNOWN_CODE),
        ]

    def test_lowercase_words_not_code_candidates(self):
        # 普通小写英文单词不是代码形候选（美股 ticker 要求大写/带 .us）
        assert _split_by_codes("tell us about") == [Token("tell us about")]

    def test_empty_text_returns_no_tokens(self):
        assert _split_by_codes("") == []


# =========================================================================
# Step 2 — 含数字指数词放行（CJK+数字复合词不被裸数字提取破坏）
# =========================================================================

class TestDigitKeywordRelease:
    """"沪深300"/"中证1000" 等含数字枚举指数词：数字段受 _DIGIT_KEYWORDS_RE
    保护区放行，整词交 Step 4/5 命中 subject_index；裸数字本身行为不变。"""

    @pytest.mark.parametrize("keyword", [
        "沪深300", "科创50",                       # 既有词池
        "中证A500", "中证1000", "中证2000",        # 本次补充（含用户指定）
        "中证500", "中证800", "中证100",
        "上证50", "北证50", "深证100", "创业板50",
    ])
    def test_digit_index_keyword_kept_whole(self, keyword):
        _, tokens = _preprocess_text(f"{keyword}怎么样")
        pairs = [(t.text, t.tag) for t in tokens]
        assert (keyword, TAG_SUBJECT_INDEX) in pairs
        # 关键词的数字段不得泄漏为独立裸数字 token
        assert all(
            t.tag != TAG_UNKNOWN_NUMBER or keyword.find(t.text) < 0
            for t in tokens
        )

    def test_hushen_300_pipeline_exact(self):
        _, tokens = _preprocess_text("沪深300怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("沪深300", TAG_SUBJECT_INDEX),
            ("怎么样", TAG_QUESTION),
        ]

    def test_zhengzheng_1000_pipeline_exact(self):
        _, tokens = _preprocess_text("中证1000走势")
        assert [(t.text, t.tag) for t in tokens] == [
            ("中证1000", TAG_SUBJECT_INDEX),
            ("走势", TAG_SUBJECT_RESEARCH),
        ]

    def test_bare_numbers_untouched(self):
        # 放行只作用于"完全包含于关键词 span"的数字段，裸数字行为不变
        assert _split_by_codes("300") == [Token("300", TAG_UNKNOWN_NUMBER)]
        assert _split_by_codes("1000") == [Token("1000", TAG_UNKNOWN_NUMBER)]
        assert _split_by_codes("50") == [Token("50", TAG_UNKNOWN_NUMBER)]

    def test_number_adjacent_to_digit_keyword(self):
        # "2024年沪深300"：年份照常裸数字，指数整词命中，互不干扰
        _, tokens = _preprocess_text("2024年沪深300")
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("2024", TAG_UNKNOWN_NUMBER) in pairs
        assert ("沪深300", TAG_SUBJECT_INDEX) in pairs

    def test_code_after_digit_keyword(self):
        _, tokens = _preprocess_text("中证1000和600519")
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("中证1000", TAG_SUBJECT_INDEX) in pairs
        assert ("600519", TAG_UNKNOWN_NUMBER) in pairs

    def test_partial_overlap_not_released(self):
        # 数字段仅部分重叠关键词（"沪深3000" ≠ "沪深300"+0）不适用保护：
        # 维持裸数字提取，前缀交下游
        tokens = _split_by_codes("沪深3000")
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("3000", TAG_UNKNOWN_NUMBER) in pairs


# =========================================================================
# 代码辨认 — unknown_code → stock_code / wrong_{market}_code / unknown_{market}_code
# =========================================================================

class TestIdentifyStockCodes:
    """库命中附完整三元组 + 规范化拼写；未命中按市场库全量与否细分 wrong/unknown。"""

    @staticmethod
    def _identify(token_text, tag=TAG_UNKNOWN_CODE):
        return _identify_stock_codes([Token(token_text, tag)])

    def test_ashare_suffix_canonicalized(self):
        assert self._identify("600519.SH") == [
            Token("600519", TAG_STOCK_CODE, stocks=(Stock("600519", "贵州茅台", "a"),))
        ]

    def test_ashare_prefix_canonicalized(self):
        assert self._identify("SH600519") == [
            Token("600519", TAG_STOCK_CODE, stocks=(Stock("600519", "贵州茅台", "a"),))
        ]

    def test_hk_suffix_canonicalized(self):
        assert self._identify("00700.HK") == [
            Token("HK00700", TAG_STOCK_CODE, stocks=(Stock("HK00700", "腾讯控股", "hk"),))
        ]

    def test_hk_prefixed_bare_key_canonicalized(self):
        assert self._identify("HK00700") == [
            Token("HK00700", TAG_STOCK_CODE, stocks=(Stock("HK00700", "腾讯控股", "hk"),))
        ]

    def test_hk_short_suffix_padded_before_validation(self):
        # 4 位短码后缀（1810.HK=小米）：构造 canonical 时先补零再过 5 位
        # 闸门，token 文本用规范拼写 HK01810（对齐 stock_code_utils zfill(5)）
        assert self._identify("1810.HK") == [
            Token("HK01810", TAG_STOCK_CODE, stocks=(Stock("HK01810", "小米集团", "hk"),))
        ]

    def test_hk_short_suffix_with_leading_zero_padded(self):
        assert self._identify("0700.HK") == [
            Token("HK00700", TAG_STOCK_CODE, stocks=(Stock("HK00700", "腾讯控股", "hk"),))
        ]

    def test_hk_short_prefix_padded(self):
        # 前缀短码同样补零：HK700 → HK00700 腾讯
        assert self._identify("HK700") == [
            Token("HK00700", TAG_STOCK_CODE, stocks=(Stock("HK00700", "腾讯控股", "hk"),))
        ]

    def test_hk_one_digit_suffix_padded(self):
        # 单位极端例：700.HK → HK00700（与 stock_scope 正则 \d{1,5}\.HK 同口径）
        assert self._identify("700.HK") == [
            Token("HK00700", TAG_STOCK_CODE, stocks=(Stock("HK00700", "腾讯控股", "hk"),))
        ]

    def test_us_ticker_in_db(self):
        assert self._identify("TSLA") == [
            Token("TSLA", TAG_STOCK_CODE, stocks=(Stock("TSLA", "特斯拉", "us"),))
        ]

    def test_us_ticker_lowercase_suffix_canonicalized(self):
        # aapl.us → 规范大写 AAPL（extract 的美股正则只认大写，回退大写拼写）
        assert self._identify("aapl.us") == [
            Token("AAPL", TAG_STOCK_CODE, stocks=(Stock("AAPL", "苹果", "us"),))
        ]

    def test_prefixed_illegal_code_is_wrong_a(self):
        # 带前缀的非法代码（SH777777）与裸 777777 一样按 A 股形态进 wrong_a_code，
        # 不得因前缀形态被放行（形态非法由交易所静态规则断定，与库状态无关）
        assert self._identify("SH777777") == [Token("SH777777", wrong_code_tag("a"))]

    def test_hk_bad_digit_count_is_wrong_hk(self):
        # HK + 11 位：位数不符形态非法 → wrong_hk_code
        assert self._identify("HK3294384923") == [
            Token("HK3294384923", wrong_code_tag("hk"))
        ]

    def test_hk_prefix_with_ashare_digits_is_wrong_hk(self):
        # HK 前缀 + 6 位（A 股位数）→ 与标注矛盾判 wrong_hk，
        # 不得静默解析成 A 股 600519 贵州茅台
        assert self._identify("HK600519") == [
            Token("HK600519", wrong_code_tag("hk"))
        ]

    def test_sh_prefix_with_hk_digits_is_wrong_a(self):
        # SH 前缀 + 5 位（港股位数）→ wrong_a，不得静默变 HK00700 腾讯
        assert self._identify("SH00700") == [
            Token("SH00700", wrong_code_tag("a"))
        ]

    def test_sz_suffix_with_hk_digits_is_wrong_a(self):
        assert self._identify("00700.SZ") == [
            Token("00700.SZ", wrong_code_tag("a"))
        ]

    def test_hk_suffix_with_ashare_digits_is_wrong_hk(self):
        # .HK 后缀 + 6 位 → wrong_hk：不得从数字中段截取片段与后缀拼接
        # 解析（多候选只取首个的顺序依赖同样不允许）
        assert self._identify("600519.HK") == [
            Token("600519.HK", wrong_code_tag("hk"))
        ]

    def test_sh_marker_with_sz_digits_is_wrong_a(self):
        # SH 前缀 + 深市代码（000001=平安银行）：交易所标注与数字形态矛盾
        # → wrong_a，不得静默解析成平安银行（SH000001 本意是上证指数）
        assert self._identify("SH000001") == [
            Token("SH000001", wrong_code_tag("a"))
        ]

    def test_bj_marker_with_sh_digits_is_wrong_a(self):
        # BJ 前缀 + 沪市代码（600519=贵州茅台）→ wrong_a，不得静默解析成茅台
        assert self._identify("BJ600519") == [
            Token("BJ600519", wrong_code_tag("a"))
        ]

    def test_sz_marker_with_sh_digits_is_wrong_a(self):
        # SZ 后缀 + 沪市代码 → wrong_a（后缀标注与形态同样受一致性闸门约束）
        assert self._identify("600519.SZ") == [
            Token("600519.SZ", wrong_code_tag("a"))
        ]

    def test_consistent_sz_marker_resolves(self):
        # 标注一致（SZ+000001 深市代码）照常命中：一致性闸门不误伤正确标注
        assert self._identify("SZ000001") == [
            Token("000001", TAG_STOCK_CODE, stocks=(Stock("000001", "平安银行", "a"),))
        ]

    def test_marker_case_insensitive(self):
        assert self._identify("hk00700") == [
            Token("HK00700", TAG_STOCK_CODE,
                  stocks=(Stock("HK00700", "腾讯控股", "hk"),))
        ]
        assert self._identify("sh600519") == [
            Token("600519", TAG_STOCK_CODE,
                  stocks=(Stock("600519", "贵州茅台", "a"),))
        ]

    def test_contradictory_double_marker_is_wrong(self):
        # 前后缀标注市场互斥：按后缀市场判 wrong，不取数字段静默解析
        assert self._identify("HK600519.SH") == [
            Token("HK600519.SH", wrong_code_tag("a"))
        ]

    def test_consistent_double_marker_resolves(self):
        assert self._identify("SH600519.SH") == [
            Token("600519", TAG_STOCK_CODE,
                  stocks=(Stock("600519", "贵州茅台", "a"),))
        ]

    def test_out_of_db_ticker_kept_unknown_us(self):
        # SOFI 不在本地库：美股库永不视为全量，存疑 unknown_us_code 交下游 LLM
        assert self._identify("SOFI") == [Token("SOFI", unknown_code_tag("us"))]

    def test_plain_english_word_kept_unknown_us(self):
        assert self._identify("OK") == [Token("OK", unknown_code_tag("us"))]

    def test_absent_ashare_code_before_extension_unknown(self, monkeypatch):
        # A 股库未扩展（_akshare_merged 为 None）：格式合法但库未命中 → 存疑
        from src.services import name_to_code_resolver as resolver_mod

        monkeypatch.setattr(resolver_mod, "_akshare_merged", None)
        assert self._identify("SH603999") == [Token("SH603999", unknown_code_tag("a"))]

    def test_absent_ashare_code_after_extension_wrong(self, monkeypatch):
        # AkShare 已并入仍命中失败 → 确定不存在 wrong_a_code
        from src.services import name_to_code_resolver as resolver_mod

        monkeypatch.setattr(resolver_mod, "_akshare_merged", {"贵州茅台": "600519"})
        assert self._identify("SH603999") == [Token("SH603999", wrong_code_tag("a"))]

    def test_hk_absent_code_always_unknown(self):
        # 港股本地库永不视为全量：格式合法但库未命中（HK39999）→ 存疑
        assert self._identify("HK39999") == [Token("HK39999", unknown_code_tag("hk"))]

    def test_mock_akshare_merge_makes_code_matched(self):
        # mock 的 AkShare 全量并入后：SZ000799（酒鬼酒，深市代码配深市标注）
        # 辨认命中并附三元组
        resolver_name_to_code_list("酒鬼酒")  # CJK 触发下游扩展（mock 并入）
        assert self._identify("SZ000799") == [
            Token("000799", TAG_STOCK_CODE, stocks=(Stock("000799", "酒鬼酒", "a"),))
        ]

    def test_untagged_tokens_pass_through(self):
        tokens = [Token("分析", TAG_REQUEST), Token("600519", TAG_UNKNOWN_NUMBER)]
        assert _identify_stock_codes(tokens) == tokens


# =========================================================================
# Step 1 — 股票全名精确扫描（管道首步）
# =========================================================================

class TestFullNameScan:
    """窗口必须整体等于库中股票全名（4~3 字）；缩写与非全名留给 Step 6。"""

    def test_full_name_inside_sentence(self):
        tokens = _split_by_stock_entities("分析贵州茅台走势")
        assert [t.text for t in tokens] == ["分析", "贵州茅台", "走势"]
        name_token = tokens[1]
        assert name_token.tag == TAG_STOCK_NAME
        assert [s.code for s in name_token.stocks] == ["600519"]

    def test_cross_market_same_name_carries_candidates(self):
        # 阿里巴巴 → hk 09988 / us BABA 同名多只，token 携带多候选
        tokens = _split_by_stock_entities("阿里巴巴")
        assert len(tokens) == 1
        assert tokens[0].tag == TAG_STOCK_NAME
        assert {s.code for s in tokens[0].stocks} == {"HK09988", "BABA"}

    def test_abbreviation_not_matched_here(self):
        # 一对一缩写（茅台）非全名，Step 1 不做匹配，交由 Step 6 承接
        assert _split_by_stock_entities("茅台") == [Token("茅台")]

    def test_non_name_text_untouched(self):
        assert _split_by_stock_entities("大港股份怎么样") == [Token("大港股份怎么样")]

    def test_intra_name_space_matched_after_compact(self):
        # 契约：窗口匹配前输入端统一删去空格（与库内压平拼写对齐），
        # 带空格指称与常规书写同样整名命中，token 文本为压平拼写
        tokens = _split_by_stock_entities("贵 州 茅 台怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("贵州茅台", TAG_STOCK_NAME), ("怎么样", "")
        ]
        assert [s.code for s in tokens[0].stocks] == ["600519"]
        assert _split_by_stock_entities("五 粮 液") == [
            Token("五粮液", TAG_STOCK_NAME, stocks=(Stock("000858", "五粮液", "a"),))
        ]

    def test_spaced_name_pipeline_resolves(self):
        # 全管道：带空格指称整名命中，余文关键词照常提取
        _, tokens = _preprocess_text("五 粮 液怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("五粮液", TAG_STOCK_NAME),
            ("怎么样", TAG_QUESTION),
        ]
        assert [s.code for s in tokens[0].stocks] == ["000858"]

    def test_pure_ascii_short_circuit(self):
        # 纯英文段直接原样返回（交 Step 6 拼音/美股代码兜底）
        assert _split_by_stock_entities("TSLA") == [Token("TSLA")]

    def test_two_char_full_name_matched(self):
        # 8~2 窗口契约（原"2 字名不扫描"已反转）：2 字全名（美团=03690）
        # 整名精确命中，不再依赖 Step 6 模糊路径
        tokens = _split_by_stock_entities("美团")
        assert [(t.text, t.tag) for t in tokens] == [("美团", TAG_STOCK_NAME)]
        assert [s.code for s in tokens[0].stocks] == ["HK03690"]

    def test_six_char_full_name_matched_whole(self):
        # 6 字全名（中国海洋石油=00883）整名命中：不再落给 DFS 拆成
        # "中国海洋"+"石油" 错误边界（"石油"子串曾带入未提及的中国石油）
        tokens = _split_by_stock_entities("中国海洋石油怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("中国海洋石油", TAG_STOCK_NAME),
            ("怎么样", ""),
        ]
        assert [s.code for s in tokens[0].stocks] == ["HK00883"]

    def test_spaced_six_char_name_matched_whole(self):
        # 单空格书写的 6 字全名（raw 11 字符，超压缩长度上限 8）：空白收敛
        # + 跨度上界（2*max_len-1）下整名命中，token 文本为压平拼写
        tokens = _split_by_stock_entities("中 国 海 洋 石 油怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("中国海洋石油", TAG_STOCK_NAME),
            ("怎么样", ""),
        ]
        assert [s.code for s in tokens[0].stocks] == ["HK00883"]

    def test_spaced_long_name_pipeline_resolves(self):
        # 全管道：带空格 6 字全名整名命中——Step 2 按空白切分会把名撕裂成
        # 单字且 Step 6 无从复原，Step 1 必须在此消费
        _, tokens = _preprocess_text("中 国 海 洋 石 油怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("中国海洋石油", TAG_STOCK_NAME),
            ("怎么样", TAG_QUESTION),
        ]
        assert [s.code for s in tokens[0].stocks] == ["HK00883"]

    def test_multi_space_and_tab_separated_name_matched(self):
        # 多空格/tab/连续空白分隔的全名同样整名命中：入口把空白收敛为单空格，
        # 统一 Step 1 删 ' ' 与 Step 2 按 \s 切分的两套口径（旧实现 tab 分
        # 隔两头落空）
        tokens = _split_by_stock_entities("贵  州\t茅   台怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("贵州茅台", TAG_STOCK_NAME),
            ("怎么样", ""),
        ]
        assert [s.code for s in tokens[0].stocks] == ["600519"]


# =========================================================================
# 港股代码身份不变量 — 名称路径与代码路径共享同一拼写
# =========================================================================

class TestHkCodeIdentityInvariant:
    """token 层代码身份契约：a=6 位裸数字、hk=HK+5 位、us=大写 ticker
    （单一定义点 _canonical_stock_code）。名称路径（Step 1 实体/别名扫描、
    Step 6 子串/拼音匹配）与代码路径（_identify_stock_codes）产出必须一致，
    否则同一股票跨轮次出现多重身份（recent_stocks 去重/事件比较失效）。
    stockDB 港股键为裸 5 位，归一化只在 token 层发生，resolver 契约不变。"""

    @pytest.mark.parametrize("name, code", [
        ("腾讯控股", "HK00700"),
        ("美团", "HK03690"),
    ])
    def test_name_path_matches_code_path(self, name, code):
        # P1-1 回归：同一条消息里名称指称与代码指称必须解析到同一代码拼写
        _, tokens = _preprocess_text(f"{name}怎么样")
        name_codes = {s.code for t in tokens if t.tag == TAG_STOCK_NAME
                      for s in (t.stocks or ())}
        out = _identify_stock_codes([Token(code.lower(), TAG_UNKNOWN_CODE)])
        code_codes = {s.code for t in out for s in (t.stocks or ())}
        assert name_codes == code_codes == {code}

    def test_step1_alias_hit_canonical(self):
        # Step 1 别名分支：命中展示当前规范名 + canonical 拼写
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockAliases.setdefault("00700", set()).add("老腾讯名")
        resolver_mod._names_cache[:] = [None, None, None]
        try:
            tokens = _split_by_stock_entities("老腾讯名怎么样")
            assert [(t.text, t.tag) for t in tokens] == [
                ("老腾讯名", TAG_STOCK_NAME), ("怎么样", "")
            ]
            assert [s.code for s in tokens[0].stocks] == ["HK00700"]
            assert tokens[0].stocks[0].name == "腾讯控股"
        finally:
            resolver_mod.stockAliases["00700"].discard("老腾讯名")
            if not resolver_mod.stockAliases["00700"]:
                del resolver_mod.stockAliases["00700"]
            resolver_mod._names_cache[:] = [None, None, None]

    def test_dfs_cjk_substring_path_canonical(self):
        # Step 6 CJK 循环经 resolver 子串命中港股（腾讯 ⊂ 腾讯控股）
        _, tokens = _preprocess_text("腾讯怎么样")
        assert [s.code for t in tokens if t.tag == TAG_STOCK_NAME
                for s in (t.stocks or ())] == ["HK00700"]

    def test_dfs_alpha_pinyin_path_canonical(self):
        # Step 6 alpha 路径经拼音命中港股（tengxun ⊂ tengxunkonggu）
        _, tokens = _preprocess_text("tengxun怎么样")
        assert [s.code for t in tokens if t.tag == TAG_STOCK_NAME
                for s in (t.stocks or ())] == ["HK00700"]

    def test_no_bare_hk_code_in_any_token(self):
        # 不变量扫描：任何 token 的 stocks 不得出现 market=="hk" 且纯数字 code
        # （跨市场名"理想汽车"= LI + 02015 同 token 内按市场逐候选归一）
        for msg in ["腾讯控股和美团对比", "阿里巴巴vs贵州茅台", "港股腾讯控股",
                    "分析hk00700和腾讯控股", "理想汽车怎么样"]:
            _, tokens = _preprocess_text(msg)
            for t in tokens:
                for s in (t.stocks or ()):
                    assert not (s.market == "hk" and s.code.isdigit()), (msg, s)


# =========================================================================
# Step 1 实体扫描前置 — 含 ASCII 大写子串的库内全名不被代码形提取撕裂
# =========================================================================

class TestAsciiContainedFullName:
    """P1-1 回归：库内全名含形同美股 ticker 的大写 ASCII 子串（"TCL科技"
    的 "TCL"）时，Step 1 实体扫描（管道首步，入口先扩展）必须整名消费。
    旧序（代码形提取先于实体扫描）会把 "TCL" 撕成 unknown_code、把
    "科技" 误打成 sector_name——实体丢失且产出错误的行业/市场信号，
    冷热库行为一致地坏。"""

    _TCL_MOCK = {"TCL科技": "000100"}

    def _run(self, msg):
        """冷启动前提：重置扩展态，首条消息即在 Step 1 入口面对扩展。"""
        from src.services import name_to_code_resolver as resolver_mod

        with patch(
            "src.services.name_to_code_resolver._get_akshare_name_to_code",
            return_value=self._TCL_MOCK,
        ):
            resolver_mod._akshare_merged = None
            resolver_mod._names_cache[:] = [None, None, None]
            _, tokens = _preprocess_text(msg)
        return _identify_stock_codes(tokens)

    def test_in_sentence_cold_start(self):
        tokens = self._run("分析TCL科技走势")
        assert [(t.text, t.tag) for t in tokens] == [
            ("分析", TAG_REQUEST),
            ("TCL科技", TAG_STOCK_NAME),
            ("走势", TAG_SUBJECT_RESEARCH),
        ]
        assert [s.code for s in tokens[1].stocks] == ["000100"]

    def test_bare_name_message(self):
        # 整条消息即全名（无标点词界）：同样必须整名消费——Step 6 DFS 的
        # 长度循环无法处理 ASCII+CJK 混段（alpha 路径只取纯字母前缀）
        tokens = self._run("TCL科技")
        assert [(t.text, t.tag) for t in tokens] == [("TCL科技", TAG_STOCK_NAME)]
        assert [(s.code, s.name, s.market) for s in tokens[0].stocks] == [
            ("000100", "TCL科技", "a")
        ]

    def test_repeated_entity(self):
        tokens = self._run("TCL科技TCL科技怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("TCL科技", TAG_STOCK_NAME),
            ("TCL科技", TAG_STOCK_NAME),
            ("怎么样", TAG_QUESTION),
        ]

    def test_market_keyword_coexists(self):
        tokens = self._run("美股TCL科技怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("美股", TAG_SUBJECT_MARKET),
            ("TCL科技", TAG_STOCK_NAME),
            ("怎么样", TAG_QUESTION),
        ]

    def test_out_of_db_ascii_name_degrades_gracefully(self):
        # 已知限制：库外含 ASCII 名（如港股 "TCL电子"）不在库中，Step 1
        # 无法整名消费，"TCL" 照旧降级为 unknown_us_code 交下游 LLM 兜底
        # （形态层面本质歧义：大写字母后接 CJK 一律放行会误伤 "TSLA怎么样"）
        tokens = self._run("TCL电子怎么样")
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("TCL", unknown_code_tag("us")) in pairs


# =========================================================================
# 关键词大小写不敏感 — 大写存储词的小写形态同构命中
# =========================================================================

class TestCaseInsensitiveKeywordClassification:
    """P1-2 回归：关键词大小写不敏感与 (?i:) 编译声明同构——存储为大写的
    关键词（"AI"/"中证A500"）的小写形态（"ai赛道"/"中证a500"）必须与
    大写原形产出完全一致，不得整体失效或被裸数字提取撕裂。"""

    def test_lowercase_ai_sector_pair(self):
        _, tokens = _preprocess_text("ai赛道")
        assert [(t.text, t.tag) for t in tokens] == [
            ("ai", TAG_SECTOR_NAME),
            ("赛道", TAG_SECTOR),
        ]

    def test_lowercase_digit_index_keyword_kept_whole(self):
        # "中证a500" 的数字段受保护区放行（大小写不敏感），整词命中
        # subject_index，不被撕成 "中证a" + "500"
        _, tokens = _preprocess_text("中证a500走势")
        assert [(t.text, t.tag) for t in tokens] == [
            ("中证a500", TAG_SUBJECT_INDEX),
            ("走势", TAG_SUBJECT_RESEARCH),
        ]

    def test_digit_keyword_release_case_insensitive(self):
        assert _split_by_codes("中证a500") == [Token("中证a500")]

    def test_uppercase_pool_keyword_original_form_unchanged(self):
        # 大写存储词的原形匹配不受归一表影响
        assert _preprocess_text("AI赛道")[1][0].tag == TAG_SECTOR_NAME


# =========================================================================
# 字母.交易所后缀代码 — 后缀与主体整体成 span
# =========================================================================

class TestSuffixedUsTicker:
    """BRK.B / AAPL.N / TSLA.N 形态（与 extract_stock_codes 的美股正则
    同构）：后缀与主体必须整体成 span，不得撕成 "BRK" + ".B" 两段——
    旧正则会把库外代码文本撕残（unknown_us_code 只剩 "BRK"）。"""

    def test_step3_keeps_suffix_whole(self):
        assert _split_by_codes("BRK.B") == [Token("BRK.B", TAG_UNKNOWN_CODE)]
        assert _split_by_codes("AAPL.N") == [Token("AAPL.N", TAG_UNKNOWN_CODE)]
        assert _split_by_codes("TSLA.N怎么样") == [
            Token("TSLA.N", TAG_UNKNOWN_CODE),
            Token("怎么样"),
        ]

    def test_identify_in_db_ticker_with_suffix(self):
        # 库内 ticker：取主体规范化大写拼写（AAPL.N → AAPL）
        assert _identify_stock_codes([Token("AAPL.N", TAG_UNKNOWN_CODE)]) == [
            Token("AAPL", TAG_STOCK_CODE, stocks=(Stock("AAPL", "苹果", "us"),))
        ]

    def test_identify_out_of_db_keeps_text_intact(self):
        # 库外带后缀代码：文本保持完整交下游确认（不再残缺成 "BRK"+".B"）
        assert _identify_stock_codes([Token("BRK.B", TAG_UNKNOWN_CODE)]) == [
            Token("BRK.B", unknown_code_tag("us"))
        ]

    def test_us_suffix_pattern_unaffected(self):
        # .us 后缀（大小写不敏感）行为不变
        assert _split_by_codes("aapl.us") == [Token("aapl.us", TAG_UNKNOWN_CODE)]
        assert _split_by_codes("BABA.US") == [Token("BABA.US", TAG_UNKNOWN_CODE)]


# =========================================================================
# Step 4 — 市场词提取
# =========================================================================

class TestMarketTokenSplit:
    """"股"后接"份"（股票名后缀）时跳过，避免"大港股份"中的"港股"被误提取。"""

    def test_market_word_tagged(self):
        tokens = _split_market_tokens("港股")
        assert [(t.text, t.tag) for t in tokens] == [("港股", TAG_SUBJECT_MARKET)]

    def test_ascii_market_case_insensitive(self):
        tokens = _split_market_tokens("A股")
        assert [(t.text, t.tag) for t in tokens] == [("A股", TAG_SUBJECT_MARKET)]

    def test_market_suffix_company_name_not_split(self):
        # "大港股份"中的"港股"子串后接"份"→ 跳过，整段保留
        assert _split_market_tokens("大港股份") == [Token("大港股份")]

    def test_broad_market_keyword(self):
        tokens = _split_market_tokens("行情怎么样")
        assert ("行情", TAG_SUBJECT_MARKET_BROAD) in [(t.text, t.tag) for t in tokens]

    def test_gap_untagged(self):
        tokens = _split_market_tokens("看看港股走势")
        assert [t.text for t in tokens] == ["看看", "港股", "走势"]
        assert tokens[1].tag == TAG_SUBJECT_MARKET


# =========================================================================
# Step 5 — 无歧义关键词
# =========================================================================

class TestCleanKeywordTokenize:
    def test_request_and_filler(self):
        tokens = _tokenize_by_clean_keywords("帮我分析一下")
        assert [(t.text, t.tag) for t in tokens] == [
            ("帮我", TAG_FILLER),
            ("分析", TAG_REQUEST),
            ("一下", TAG_FILLER),
        ]

    def test_research_subject(self):
        tokens = _tokenize_by_clean_keywords("走势")
        assert tokens == [Token("走势", TAG_SUBJECT_RESEARCH)]

    def test_ambiguous_keyword_not_in_clean_pool(self):
        # "对比"在 extend 池（可能与股票名混淆），clean 分词不提取
        assert _tokenize_by_clean_keywords("对比") == [Token("对比")]


# =========================================================================
# Step 6 板块词契约 — 板块词不做个股名匹配（Step 6 之前禁止模糊匹配）
# =========================================================================

class TestSectorWordNotStockMatched:
    """sector 系词不做个股名匹配。"XX板块/行业/赛道/概念/题材"无专用正则：
    Step 6 DFS 把词池内的行业名与泛称切为相邻 [sector_name/sector_n_stock]
    +[sector] token 对——该相邻组合即高置信度板块信号，由下游消费。
    Step 1~5 保持纯精确匹配。"""

    def test_suffix_decomposes_to_adjacent_pair(self):
        # Step 5 clean 关键词先于 Step 6；"建筑板块"→[sector_name]+[sector] 相邻
        _, tokens = _preprocess_text("看看建筑板块")
        assert [(t.text, t.tag) for t in tokens] == [
            ("看看", TAG_REQUEST),
            ("建筑", TAG_SECTOR_NAME),
            ("板块", TAG_SECTOR),
        ]

    def test_industry_prefix_never_stock_matched(self):
        # "建筑"不得经名称库子串解析成"中国建筑"个股
        _, tokens = _preprocess_text("看看建筑板块")
        assert all(t.tag != TAG_STOCK_NAME for t in tokens)

    def test_multi_match_adjacent_pair_direct(self):
        assert _multi_match("建筑板块") == [
            Token("建筑", TAG_SECTOR_NAME),
            Token("板块", TAG_SECTOR),
        ]

    def test_adjacent_pair_then_dfs_recursion(self):
        # 相邻组合命中后，余文在同一递归链内继续匹配
        tokens = _multi_match("建筑板块怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("建筑", TAG_SECTOR_NAME),
            ("板块", TAG_SECTOR),
            ("怎么样", TAG_QUESTION),
        ]

    def test_ascii_industry_word_pair(self):
        # ASCII 行业名（AI 在 TAG_SECTOR_NAME 池）同样走相邻组合
        assert _multi_match("AI赛道") == [
            Token("AI", TAG_SECTOR_NAME),
            Token("赛道", TAG_SECTOR),
        ]

    def test_bare_suffix_still_keyword_matched(self):
        # 无前缀的裸后缀"板块"由 DFS extend 精确关键词命中
        assert _multi_match("板块") == [Token("板块", TAG_SECTOR)]

    def test_unenumerated_industry_word_left_for_llm(self):
        # 未枚举行业词（预制菜）不在词池：整段无法全匹配 → 原样空 tag 交 LLM 兜底
        assert _multi_match("预制菜板块") == [Token("预制菜板块")]

    def test_enumerated_industry_word_sector_first(self):
        # "建筑"已枚举进 TAG_SECTOR_NAME 池（全量库实证 ⊂ 中国建筑）：裸词
        # 行业语义优先，打 sector_name，不解析成"中国建筑"个股
        assert _multi_match("建筑") == [Token("建筑", TAG_SECTOR_NAME)]

    def test_enumerated_word_beats_name_library_substring(self):
        # 基础库真实碰撞："农业"⊂农业银行、"证券"⊂中信证券——Step 6 关键词
        # 分类优先于名称库子串命中，裸词打 sector_name
        assert _multi_match("农业") == [Token("农业", TAG_SECTOR_NAME)]
        assert _multi_match("证券") == [Token("证券", TAG_SECTOR_NAME)]

    def test_sector_n_stock_word_ambiguous_tag(self):
        # 行业名兼股票全名（机器人=300024）：裸用打歧义 tag sector_n_stock，
        # 既不打 stock_name 也不武断打 sector_name，交下游 LLM/确认消歧
        assert _multi_match("机器人") == [Token("机器人", TAG_SECTOR_N_STOCK)]

    def test_full_name_scan_releases_enumerated_word(self):
        # "机器人"在生产全量库是 300024 的全名：注入后 Step 1 必须放行，
        # 不得在 Step 6 之前打成 stock_name，交 Step 6 关键词打歧义 tag
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["300024"] = "机器人"
        assert _split_by_stock_entities("机器人板块") == [Token("机器人板块")]
        # DFS 回归：4 字窗口"机器人板"会先被 difflib 模糊命中"机器人"
        # （ratio≈0.86），但余文"块"无法全匹配 → 回溯到 3 字关键词路径，
        # 产出 [sector_n_stock]+[sector] 高置信度相邻组合
        _, tokens = _preprocess_text("机器人板块")
        assert [(t.text, t.tag) for t in tokens] == [
            ("机器人", TAG_SECTOR_N_STOCK),
            ("板块", TAG_SECTOR),
        ]
        _, tokens = _preprocess_text("机器人怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("机器人", TAG_SECTOR_N_STOCK),
            ("怎么样", TAG_QUESTION),
        ]


# =========================================================================
# Step 6 — 多策略 DFS 匹配
# =========================================================================

class TestMultiMatch:
    def test_filler_run_split_to_single_chars(self):
        tokens = _multi_match("的的")
        assert [t.text for t in tokens] == ["的", "的"]
        assert all(t.tag == TAG_FILLER for t in tokens)

    def test_overlong_token_returned_unchanged(self):
        text = "的" * 250
        assert _multi_match(text) == [Token(text)]

    def test_length_cap_boundary_50_processed(self):
        # 恰好 50 字（≤ 上限）仍进 DFS：filler 逐字全覆盖（filler-only
        # 路径跳过全库扫描，无性能风险）
        tokens = _multi_match("的" * 50)
        assert [t.text for t in tokens] == ["的"] * 50
        assert all(t.tag == TAG_FILLER for t in tokens)

    def test_length_cap_boundary_51_abandoned(self):
        # 51 字（> 上限）：50+ 字连续无标点且不含 Steps 2~5 已提取信号，
        # 默认非正常对话，整体放弃交下游 LLM
        text = "的" * 51
        assert _multi_match(text) == [Token(text)]

    def test_length_cap_leaves_earlier_steps_intact(self):
        # 超限只作用于 Step 6：Steps 2~5 已提取的代码/全名/关键词不受影响
        _, tokens = _preprocess_text("分析600519.SH，" + "的" * 60)
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("分析", TAG_REQUEST) in pairs
        assert ("600519.SH", TAG_UNKNOWN_CODE) in pairs
        assert ("的" * 60, "") in pairs

    def test_one_to_one_abbreviation_resolves(self):
        tokens = _multi_match("茅台")
        assert len(tokens) == 1
        assert tokens[0].tag == TAG_STOCK_NAME
        assert [s.code for s in tokens[0].stocks] == ["600519"]

    def test_generic_corp_suffix_not_fabricated(self):
        # "苹果公司"不得拆成 苹果+公司 双 stock_name："公司"是零区分度通用
        # 后缀（extend 词池 corp_suffix），子串命中中微公司是噪声非信号——
        # 苹果精确命中、"公司"打 corp_suffix tag 参与 DFS 全覆盖
        tokens = _multi_match("苹果公司")
        assert [(t.text, t.tag) for t in tokens] == [
            ("苹果", TAG_STOCK_NAME), ("公司", TAG_CORP_SUFFIX)
        ]
        assert [s.code for s in tokens[0].stocks] == ["AAPL"]

    def test_suffix_tag_enables_full_coverage(self):
        # 后缀 corp_suffix 使 DFS 全覆盖成立："腾讯公司"→腾讯(腾讯控股)+
        # 公司(corp_suffix)，不再整段放弃交下游（空 tag 方案下无法覆盖）
        tokens = _multi_match("腾讯公司")
        assert [(t.text, t.tag) for t in tokens] == [
            ("腾讯", TAG_STOCK_NAME), ("公司", TAG_CORP_SUFFIX)
        ]
        assert [s.code for s in tokens[0].stocks] == ["HK00700"]

    def test_bare_generic_suffix_tagged_corp_suffix(self):
        # 纯通用后缀单独成词：不做全库扫描，打 corp_suffix tag（原实现解析
        # 成上汽/豪威/小米/京东/百度 5 候选 stock_name）
        assert _multi_match("集团") == [Token("集团", TAG_CORP_SUFFIX)]

    def test_generic_suffix_pipeline_not_injected(self):
        # 全管道回归：分析 苹果公司 走势 → 只产出苹果(AAPL)，不注入 688012
        _, tokens = _preprocess_text("分析 苹果公司 走势")
        assert [(t.text, t.tag) for t in tokens] == [
            ("分析", TAG_REQUEST),
            ("苹果", TAG_STOCK_NAME),
            ("公司", TAG_CORP_SUFFIX),
            ("走势", TAG_SUBJECT_RESEARCH),
        ]
        assert [s.code for t in tokens if t.tag == TAG_STOCK_NAME
                for s in (t.stocks or ())] == ["AAPL"]

    def test_suffix_containing_full_name_still_matched(self):
        # 防过度拦截：含后缀词头但非纯后缀的全名（中芯国际）照常整名命中，
        # 跨市场同名双候选各按 canonical 拼写（a=688981、hk=HK00981）
        tokens = _multi_match("中芯国际")
        assert [(t.text, t.tag) for t in tokens] == [("中芯国际", TAG_STOCK_NAME)]
        assert {s.code for s in tokens[0].stocks} == {"688981", "HK00981"}

    def test_space_separated_ascii_words_resolved(self):
        # 空白是词界、Step 1 切分——空格分隔的小写多词与逗号分隔同构
        # （原整段失败交 LLM；≤4 字余词靠"带空格模糊命中"侥幸通过且 token
        # 文本残留前导空格的偶然边界一并消除）
        _, tokens = _preprocess_text("tsla aapl")
        assert [(t.text, t.tag) for t in tokens] == [
            ("tsla", TAG_STOCK_NAME), ("aapl", TAG_STOCK_NAME)
        ]
        assert [s.code for t in tokens for s in (t.stocks or ())] == ["TSLA", "AAPL"]

    def test_space_equivalent_to_comma(self):
        # 空格与逗号产出同构：独立 token、无前导空格残留
        _, spaced = _preprocess_text("tsla amd")
        _, commaed = _preprocess_text("tsla,amd")
        assert [(t.text, t.tag) for t in spaced] == [(t.text, t.tag) for t in commaed]

    def test_space_separated_word_failure_not_contagious(self):
        # 词间独立：垃圾词空 tag 交 LLM，不连坐拖垮相邻已解析词
        _, tokens = _preprocess_text("tsla jkl")
        assert [(t.text, t.tag) for t in tokens] == [
            ("tsla", TAG_STOCK_NAME), ("jkl", "")
        ]

    def test_cjk_with_spaces_deterministic(self):
        # CJK 带空格（含全角）：Step 1 词界切分，不再依赖"带空格模糊命中"
        _, tokens = _preprocess_text("茅台　和　五粮液")
        assert [(t.text, t.tag) for t in tokens] == [
            ("茅台", TAG_STOCK_NAME), ("和", TAG_FILLER), ("五粮液", TAG_STOCK_NAME)
        ]

    def test_alpha_path_ascii_name_dedup(self):
        # 名称恰等于 ticker 的 ASCII 名美股（AMD）：resolver 精确名匹配与
        # US ticker 匹配双源各出一份，拼接须按 (code, market) 去重，
        # 否则 stocks 重复会被下游误判名称歧义
        tokens = _multi_match("amd")
        assert len(tokens) == 1
        assert tokens[0].tag == TAG_STOCK_NAME
        assert [(s.code, s.market) for s in tokens[0].stocks] == [("AMD", "us")]

    def test_full_pinyin_resolves(self):
        tokens = _multi_match("guizhoumaotai")
        assert len(tokens) == 1
        assert tokens[0].tag == TAG_STOCK_NAME
        assert [s.code for s in tokens[0].stocks] == ["600519"]

    @pytest.mark.parametrize("message", ["O", "K", "hi", "ai", "ma", "no", "you", "long", "open"])
    def test_common_latin_noise_not_stock(self, message):
        # 过短拼音片段不得命中股票名拼音子串（hi/long/open…）
        tokens = _multi_match(message)
        assert all(t.tag != TAG_STOCK_NAME for t in tokens)

    def test_unresolvable_text_returned_unchanged(self):
        assert _multi_match("你好股份") == [Token("你好股份")]

    def test_cjk_with_particle_not_pinyin_matched(self):
        # 回归：扩展库并入中大力德（拼音 zhongdalide）后，"阿里的"（拼音
        # alide ⊂ zhongdalide）不得经拼音子串层误命中；DFS 最长优先的
        # 3 字路径落空后必须回退到 2 字"阿里"子串 + "的"filler 的正确组合
        resolver_name_to_code_list("酒鬼酒")  # CJK 触发 mock AkShare 并入
        tokens = _multi_match("阿里的")
        assert [(t.text, t.tag) for t in tokens] == [
            ("阿里", "stock_name"),
            ("的", "filler"),
        ]
        assert [s.code for s in tokens[0].stocks] == ["HK09988", "BABA"]


# =========================================================================
# Step 6 — 冷启动 DFS 回溯预算哨兵
# =========================================================================

# 触发构造三要素：
#   1. 4 字库名（长城汽车）：同一对齐位置 len4 精确 / len3 模糊("长城汽"
#      vs "长城汽车" ratio=0.75 失败、但"长城汽"对截断名可命中)/len2 子串
#      多分支并存，回溯树分支因子 >1；
#   2. 不可被模糊吸收的尾字（"咣"："汽车咣" vs "长城汽车" ratio≈0.67
#      < 0.8）阻断首路径快速成功，迫使全树回溯；
#   3. 冷启动：该名不在本地库中，Step 1 入口扩展后中途并入——若整名消费
#      链路退化（扩展点后移/窗口收窄/别名索引移除），该名只能落给 Step 6
#      DFS 首次 CJK resolver 调用路径，指数回溯面重新暴露。
_BACKTRACK_NAME = "长城汽车"
_BACKTRACK_TAIL = "咣"


class TestDfsBacktrackingColdStart:
    """DFS 回溯预算哨兵：Step 6 长度循环多分支并存（len4 精确 / len3
    模糊 / len2 子串）时，"重复全名 + 不可吸收尾字"构造会指数回溯。
    精确全名经 Step 1（管道首步入口扩展、8~2 窗口、实体/别名索引）整名
    消费后，到达 DFS 的只剩无名 gap，调用数为常数级；无精确锚点的低置信
    路径最坏为线性×全库扫描，由 50 字上限封顶。本预算断言防止整名消费
    链路任一环节（扩展点前移、窗口宽度、别名索引、精确确认边界）退化后
    指数回溯回归。"""

    @staticmethod
    def _cold_start_run(text):
        """mock 扩展仅含触发名：调用前库中无该名（冷启动前提），
        Step 3 入口扩展后并入。返回 (tokens, resolver 调用数)。"""
        import src.agent.web_intent_tokenizer as tokenizer_mod

        calls = {"n": 0}
        orig = tokenizer_mod.resolver_name_to_code_list

        def _counting(fragment):
            calls["n"] += 1
            return orig(fragment)

        with patch(
            "src.agent.web_intent_tokenizer.resolver_name_to_code_list",
            _counting,
        ), patch(
            "src.services.name_to_code_resolver._get_akshare_name_to_code",
            return_value={_BACKTRACK_NAME: "601633"},
        ):
            _, tokens = _preprocess_text(text)
        return tokens, calls["n"]

    def test_cold_start_output_contract(self):
        # 契约：精确全名命中即实体自证——每个实体确认返回、尾部原样空
        # tag 交下游 LLM；整段放弃仅适用于非精确命中（缩写/子串/拼音/模糊）。
        # 小 n 控制用例耗时
        assert not is_known_stock_name(_BACKTRACK_NAME)  # 冷启动前提
        text = _BACKTRACK_NAME * 4 + _BACKTRACK_TAIL
        tokens, _ = self._cold_start_run(text)
        assert [(t.text, t.tag) for t in tokens] == [
            (_BACKTRACK_NAME, TAG_STOCK_NAME)
            for _ in range(4)
        ] + [(_BACKTRACK_TAIL, "")]

    def test_alias_repeat_backtracking_budget(self):
        # 别名重复预算哨兵：4 字改名旧称重复 + 不可吸收尾字是指数回溯
        # 构造；别名参与 Step 3 实体索引精确匹配后全名被整名消费，调用
        # 数应为常数级。超预算即说明别名索引被移除或失效
        from src.services import name_to_code_resolver as resolver_mod
        import src.agent.web_intent_tokenizer as tokenizer_mod

        resolver_mod.stockAliases.setdefault("601919", set()).add("中国远洋")
        resolver_mod._names_cache[:] = [None, None, None]
        try:
            calls = {"n": 0}
            orig = tokenizer_mod.resolver_name_to_code_list

            def _counting(fragment):
                calls["n"] += 1
                return orig(fragment)

            with patch(
                "src.agent.web_intent_tokenizer.resolver_name_to_code_list",
                _counting,
            ):
                text = "中国远洋" * 12 + "咣"
                _, tokens = _preprocess_text(text)
            assert calls["n"] <= 50, (
                f"别名索引失效：resolver 调用数 {calls['n']}"
            )
            pairs = [(t.text, t.tag) for t in tokens]
            assert pairs.count(("中国远洋", TAG_STOCK_NAME)) == 12
            assert pairs[-1] == ("咣", "")
            # 命中展示当前规范名（与 resolver 别名展示约定一致）
            stock_tokens = [t for t in tokens if t.tag == TAG_STOCK_NAME]
            assert all(s.name == "中远海控" and s.code == "601919"
                       for t in stock_tokens for s in (t.stocks or ()))
        finally:
            resolver_mod.stockAliases.pop("601919", None)
            resolver_mod._names_cache[:] = [None, None, None]

    def test_cold_start_resolver_call_budget(self):
        # 预算断言用确定性的 resolver 调用数（避开 wall-clock 抖动）：
        # n=12、len=49，恰在 _MAX_MULTI_MATCH_TEXT_LEN=50 限内的最坏情形
        # （>50 的输入已在上限处整体放弃）。整名消费生效时调用数为常数
        # 级，2000 已留足余量
        _, calls = self._cold_start_run(_BACKTRACK_NAME * 12 + _BACKTRACK_TAIL)
        assert calls <= 2000, (
            f"回溯预算: resolver 调用数 {calls} 超预算 2000（疑似指数回溯回归）"
        )

# =========================================================================
# DFS 耗时比哨兵 — 防指数回溯回归
# =========================================================================

class TestDfsRescanBudgetSentinel:
    """关键词链消息（无精确锚点）对同长零命中文本的耗时比上限：线性×
    全库扫描属正常代价；超限疑似指数回溯回归（Step 3 整名消费被破坏时
    比值爆到千倍级）或线性系数显著劣化（库规模叠加代码退化）。比值与
    机器速度、库规模双重无关（分子分母同库同机）。"""

    def test_keyword_chain_bounded_time(self):
        import itertools
        import time
        from src.services import name_to_code_resolver as resolver_mod

        db = dict(resolver_mod.stockDB)
        try:
            # 受控 ~4913 名合成库（≈ AkShare A 股全量规模），字符池与两个
            # 测量文本零交集，保证"零命中"基线干净
            pool = "金木水火土天地人和风云雷电山海川湖林石田"
            i = 600000
            for combo in itertools.product(pool[:17], repeat=3):
                resolver_mod.stockDB[str(i)] = "".join(combo)
                i += 1
            resolver_mod._names_cache[:] = [None, None, None]

            chain_text = "白酒板块" * 11 + "好"       # 45 字，<50 上限
            gib_text = "狐猬獾貂蚨鹉鹦鹋鹌" * 2        # 18 字、零命中、同上限内

            t0 = time.perf_counter()
            _multi_match(chain_text)
            chain = time.perf_counter() - t0
            t0 = time.perf_counter()
            _multi_match(gib_text)
            gib = time.perf_counter() - t0

            ratio = chain / max(gib, 1e-9)
            assert ratio < 60, (
                f"哨兵: 关键词链消息耗时 {chain*1000:.0f}ms，"
                f"为同长零命中文本({gib*1000:.0f}ms)的 {ratio:.0f} 倍（阈值 60）——"
                f"疑似指数回溯回归或线性系数显著劣化"
            )
        finally:
            resolver_mod.stockDB.clear()
            resolver_mod.stockDB.update(db)
            resolver_mod._names_cache[:] = [None, None, None]


# =========================================================================
# Step 3 放行 + Step 1 星号等价精确匹配 + Step 6 禁模糊
# =========================================================================

class TestStPrefixNames:
    """ST 全名 = 前缀(ST/*ST/ST* 三型互认) + AB 汉字：Step 3 不把 "ST" 当
    代码候选（三型排布均放行），Step 1 做三型互认的整名精确匹配——容差仅
    在前缀形式（省略 */星号位置各异），AB 汉字部分必须整体等于库中全名。"""

    def test_step3_releases_st_prefix(self):
        # 三型排布的 "ST" 均不作代码候选，整名保留（库外名交 Step 6 兜底，
        # 库内名已在 Step 1 整名消费）
        assert _split_by_codes("*ST美丽怎么样") == [Token("*ST美丽怎么样")]
        assert _split_by_codes("ST德豪怎么样") == [Token("ST德豪怎么样")]
        assert _split_by_codes("ST*美丽怎么样") == [Token("ST*美丽怎么样")]

    def test_step1_exact_match_with_star(self):
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["000010"] = "*ST美丽"
        try:
            tokens = _split_by_stock_entities("*ST美丽怎么样")
            assert [(t.text, t.tag) for t in tokens] == [
                ("*ST美丽", TAG_STOCK_NAME), ("怎么样", "")
            ]
            assert tokens[0].stocks == (Stock("000010", "*ST美丽", "a"),)
        finally:
            del resolver_mod.stockDB["000010"]

    def test_step1_star_equivalent_omitted_star(self):
        # 用户省略 *：窗口 "ST美丽" 命中库内 "*ST美丽"，token 保留输入拼写
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["000010"] = "*ST美丽"
        try:
            tokens = _split_by_stock_entities("ST美丽怎么样")
            assert [(t.text, t.tag) for t in tokens] == [
                ("ST美丽", TAG_STOCK_NAME), ("怎么样", "")
            ]
            assert tokens[0].stocks == (Stock("000010", "*ST美丽", "a"),)
        finally:
            del resolver_mod.stockDB["000010"]

    def test_step1_three_prefix_forms_interchangeable(self):
        # 三型互认：库内 "*ST美丽"，输入 "ST*美丽" 同样整名命中，
        # token 保留输入拼写、stocks 展示库内规范名
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["000010"] = "*ST美丽"
        try:
            tokens = _split_by_stock_entities("ST*美丽怎么样")
            assert [(t.text, t.tag) for t in tokens] == [
                ("ST*美丽", TAG_STOCK_NAME), ("怎么样", "")
            ]
            assert tokens[0].stocks == (Stock("000010", "*ST美丽", "a"),)
        finally:
            del resolver_mod.stockDB["000010"]

    def test_step1_star_equivalent_reverse(self):
        # 库名无星、用户带星：反向等价
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["002174"] = "ST德豪"
        try:
            tokens = _split_by_stock_entities("*ST德豪走势")
            assert [(t.text, t.tag) for t in tokens] == [
                ("*ST德豪", TAG_STOCK_NAME), ("走势", "")
            ]
            assert tokens[0].stocks == (Stock("002174", "ST德豪", "a"),)
        finally:
            del resolver_mod.stockDB["002174"]

    def test_library_external_st_name_left_for_llm(self):
        # 库外 ST 名：Step 3 三型互认未命中，本环境 Step 6 全策略亦无
        # 命中 → 整段空 tag 交 LLM 兜底（Step 6 无 ST 特殊分支）
        _, tokens = _preprocess_text("ST德豪怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("ST德豪", ""), ("怎么样", TAG_QUESTION)
        ]

    def test_cold_start_st_name_matched(self):
        # Step 3 入口扩展后走同一精确匹配：冷启动首条消息即整名命中
        # （验证扩展点前移覆盖 ST 形态；Step 6 已无扩展/重扫）
        from src.services import name_to_code_resolver as resolver_mod

        assert "*ST美丽" not in set(resolver_mod.stockDB.values())
        with patch(
            "src.services.name_to_code_resolver._get_akshare_name_to_code",
            return_value={"*ST美丽": "000010"},
        ):
            resolver_mod._akshare_merged = None
            _, tokens = _preprocess_text("*ST美丽怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("*ST美丽", TAG_STOCK_NAME), ("怎么样", TAG_QUESTION)
        ]


# =========================================================================
# Step 6 交叉验证 — 宁可不做，不可做错
# =========================================================================

class TestCrossValidation:
    """Step 6 交叉验证契约：多个低置信度命中组合成整段 TAG 全覆盖才产出，
    任一片段无 tag 则整体放弃（宁可不做，不可做错）。"""

    def test_full_coverage_mixed_entities(self):
        # "茅台和白酒板块"：个股缩写+filler+行业名+泛称交叉验证，TAG 全覆盖
        _, tokens = _preprocess_text("茅台和白酒板块")
        assert [(t.text, t.tag) for t in tokens] == [
            ("茅台", TAG_STOCK_NAME),
            ("和", TAG_FILLER),
            ("白酒", TAG_SECTOR_NAME),
            ("板块", TAG_SECTOR),
        ]
        assert [s.code for s in tokens[0].stocks] == ["600519"]

    def test_partial_coverage_abandoned(self):
        # "茅台你好"："茅台"子串命中属低置信度，余文"你好"无法覆盖 →
        # 整体放弃，不打任何 tag（宁可不做）
        _, tokens = _preprocess_text("茅台你好")
        assert [(t.text, t.tag) for t in tokens] == [("茅台你好", "")]

    def test_step3_releases_ascii_keywords_case_insensitive(self):
        # 关键词形态的 ASCII 片段不作代码候选（大小写不敏感）——
        # 大写形态被 ticker 正则抠走会让 keyword 语义丢失、误入美股辨认
        assert _split_by_codes("茅台PK五粮液") == [Token("茅台PK五粮液")]
        assert _split_by_codes("BUY") == [Token("BUY")]
        # 非关键词的大写词仍照常作为代码候选（宽口径不变）
        assert _split_by_codes("ROE") == [Token("ROE", TAG_UNKNOWN_CODE)]

    def test_uppercase_ascii_keyword_pipeline(self):
        # 全管道：大写关键词与实体共存，语义与实体两全
        _, tokens = _preprocess_text("茅台PK五粮液")
        assert [(t.text, t.tag) for t in tokens] == [
            ("茅台", TAG_STOCK_NAME),
            ("PK", TAG_COMPARISON),
            ("五粮液", TAG_STOCK_NAME),
        ]
        _, tokens = _preprocess_text("比亚迪BUY怎么样")
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("BUY", TAG_ACTION_RESEARCH) in pairs
        assert ("比亚迪", TAG_STOCK_NAME) in pairs

    def test_step3_releases_sector_pool_ascii_word(self):
        # Step 3 不影响板块实体识别："AI"在板块词池内，不作代码候选拦截，
        # 管道层即可产出相邻高置信度组合
        _, tokens = _preprocess_text("AI赛道")
        assert [(t.text, t.tag) for t in tokens] == [
            ("AI", TAG_SECTOR_NAME),
            ("赛道", TAG_SECTOR),
        ]


# =========================================================================
# 市场枚举提取 / 已识别判定 / 代码市场推断
# =========================================================================

class TestExtractMarketsFromTokens:
    def test_market_tag_mapped(self):
        assert _extract_markets_from_tokens(
            [Token("港股", TAG_SUBJECT_MARKET)]
        ) == [Market.HK]
        assert _extract_markets_from_tokens(
            [Token("A股", TAG_SUBJECT_MARKET)]
        ) == [Market.A]

    def test_ascii_market_shorthand(self):
        # "HK" Step 3 会被标成 unknown_code，但文本形态仍是市场提示
        assert _extract_markets_from_tokens([Token("HK", TAG_UNKNOWN_CODE)]) == [Market.HK]
        # 小写简写需 CJK 语境：中文消息里的独立 "us" 是市场提示
        assert _extract_markets_from_tokens([Token("看看"), Token("us")]) == [Market.US]

    def test_english_pronoun_us_not_market(self):
        # 纯英文消息里的小写 "us" 是代词（"tell us about…"），不是市场提示
        assert _extract_markets_from_tokens([
            Token("tell"), Token("us"), Token("about"),
        ]) == []
        # 大写简写是刻意形态，不受语境限制
        assert _extract_markets_from_tokens([Token("US")]) == [Market.US]

    def test_dedup(self):
        markets = _extract_markets_from_tokens([
            Token("港股", TAG_SUBJECT_MARKET),
            Token("香港", TAG_SUBJECT_MARKET),
        ])
        assert markets == [Market.HK]


class TestIsIdentifiedToken:
    def test_tagged_token_identified(self):
        assert _is_identified_token(Token("分析", TAG_REQUEST)) is True

    def test_known_full_name_identified(self):
        assert _is_identified_token(Token("贵州茅台")) is True

    def test_code_like_text_not_identified_as_name(self):
        # 代码键不算名称命中：裸数字必须继续进入代码提取步骤
        assert _is_identified_token(Token("600519")) is False

    def test_abbreviation_not_identified_as_name(self):
        # "茅台"是缩写不是全名：不在名称表，交 Step 6 多策略匹配
        assert _is_identified_token(Token("茅台")) is False


class TestMarketOfCode:
    @pytest.mark.parametrize("code,expected", [
        ("600519", "a"),
        ("000799", "a"),
        ("00700", "hk"),
        ("09988", "hk"),
        ("AAPL", "us"),
        ("AAPL.N", "us"),   # 单字母交易所后缀（NYSE/NASDAQ 简写）
        ("AAPL.US", ""),    # 双字母后缀不在单字母推断契约内
        ("77", ""),
        ("", ""),
    ])
    def test_inference(self, code, expected):
        assert _market_of_code(code) == expected


# =========================================================================
# _preprocess_text — 端到端管道
# =========================================================================

class TestPreprocessPipeline:
    def test_explicit_code_with_request(self):
        _, tokens = _preprocess_text("分析一下600519.SH")
        tokens = _identify_stock_codes(tokens)
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("分析", TAG_REQUEST) in pairs
        assert ("600519", TAG_STOCK_CODE) in pairs

    def test_extended_full_name_resolved_by_pipeline(self):
        # 首次解析中 Step 6 的 CJK 片段解析触发下游扩展（mock 并入 stockDB）：
        # 库外全名"酒鬼酒"以确定实体标签出现在管道产出里
        _, tokens = _preprocess_text("对比茅台和酒鬼酒的基本面")
        name_tokens = [t for t in tokens if t.tag == TAG_STOCK_NAME]
        codes = {s.code for t in name_tokens for s in (t.stocks or ())}
        assert {"600519", "000799"} <= codes

    def test_pipeline_deterministic_after_warmup(self):
        # 预先完成扩展（模拟进程 lifespan warmup）：stockDB 到达扩展终态后
        # 管道跨调用产出确定一致。未预热的首条 CJK 消息由 Step 6 在扩展库上
        # 兜底解析，resolve 级结果一致，但 token 边界可能与后续消息不同
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.extend_AkShare()
        _, tokens1 = _preprocess_text("对比茅台和酒鬼酒的基本面")
        _, tokens2 = _preprocess_text("对比茅台和酒鬼酒的基本面")
        assert [(t.text, t.tag) for t in tokens1] == [(t.text, t.tag) for t in tokens2]
        pairs = [(t.text, t.tag) for t in tokens1]
        assert ("酒鬼酒", TAG_STOCK_NAME) in pairs

    def test_punctuation_tokens_filtered(self):
        # 纯标点/空白 token 在管道末端被过滤
        _, tokens = _preprocess_text("你好，在吗？？")
        assert all(t.text.strip() for t in tokens)
        assert all(t.text not in ("，", "？") for t in tokens)

    def test_nfkc_width_normalization(self):
        # 入口 NFKC 宽度归一（工作副本）：全角数字/字母与半角同形参与全部
        # 步骤——全角数字曾被末端过滤器静默丢弃、全角 Ａ 错过市场关键词；
        # 返回的原文本保持用户输入原样
        _, tokens = _preprocess_text("Ａ股分析６００５１９")
        pairs = [(t.text, t.tag) for t in tokens]
        assert ("A股", TAG_SUBJECT_MARKET) in pairs
        assert ("分析", TAG_REQUEST) in pairs
        assert ("600519", TAG_UNKNOWN_NUMBER) in pairs
        text, _ = _preprocess_text("Ａ股分析６００５１９")
        assert text == "Ａ股分析６００５１９"

    def test_nfkc_fullwidth_suffixed_code_resolves(self):
        # 全角代码 + 交易所后缀：NFKC 归一后走标注判决，命中库即 stock_code
        _, tokens = _preprocess_text("６００５１９.SH")
        tokens = _identify_stock_codes(tokens)
        assert ("600519", TAG_STOCK_CODE) in [(t.text, t.tag) for t in tokens]

    def test_returns_original_text(self):
        text, _ = _preprocess_text("分析一下600519.SH")
        assert text == "分析一下600519.SH"
