# -*- coding: utf-8 -*-
"""web_intent_tokenizer 六步分词管道单测。

只测分词与实体提取（不涉及 WebIntentResolver 的意图判定）：
  Step 1   特殊标点切分
  Step 2   代码形提取（_split_by_codes：裸数字 → unknown_number）
  Step 3   股票全名精确扫描（_split_by_stock_entities）
  Step 4   市场词提取（_split_market_tokens，"股"+"份"消歧）
  Step 5   无歧义关键词（_tokenize_by_clean_keywords）
  Step 5.5 行业后缀复合词（_split_by_sector_compounds）
  Step 6   多策略 DFS 匹配（_multi_match）
  代码辨认 _identify_stock_codes（unknown_code → stock_code 附三元组 /
  wrong_{market}_code / unknown_{market}_code）

AkShare 扩展由下游 resolver_name_to_code_list 的 CJK 路径触发（本模块不
主动扩展），mock 为最小全量 A 股数据（_MOCK_AKSHARE_A_SHARES）保证离线
确定性；mock 之外的库外名称仍不可解析。
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
    _split_by_sector_compounds,
    _split_by_stock_entities,
    _split_market_tokens,
    _tokenize_by_clean_keywords,
)
from src.services.name_to_code_resolver import (
    Stock,
    resolver_name_to_code_list,
)
from src.agent.web_intent_types import (
    Market,
    TAG_FILLER,
    TAG_REQUEST,
    TAG_STOCK_CODE,
    TAG_STOCK_NAME,
    TAG_SUBJECT_MARKET,
    TAG_SUBJECT_MARKET_BROAD,
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
# Step 2 — 代码形提取
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
        # mock 的 AkShare 全量并入后：SH000799（酒鬼酒）辨认命中并附三元组
        resolver_name_to_code_list("酒鬼酒")  # CJK 触发下游扩展（mock 并入）
        assert self._identify("SH000799") == [
            Token("000799", TAG_STOCK_CODE, stocks=(Stock("000799", "酒鬼酒", "a"),))
        ]

    def test_untagged_tokens_pass_through(self):
        tokens = [Token("分析", TAG_REQUEST), Token("600519", TAG_UNKNOWN_NUMBER)]
        assert _identify_stock_codes(tokens) == tokens


# =========================================================================
# Step 3 — 股票全名精确扫描
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
        assert {s.code for s in tokens[0].stocks} == {"09988", "BABA"}

    def test_abbreviation_not_matched_here(self):
        # 一对一缩写（茅台）非全名，Step 3 不做匹配，交由 Step 6 承接
        assert _split_by_stock_entities("茅台") == [Token("茅台")]

    def test_non_name_text_untouched(self):
        assert _split_by_stock_entities("大港股份怎么样") == [Token("大港股份怎么样")]

    def test_pure_ascii_short_circuit(self):
        # 纯英文段直接原样返回（交 Step 6 拼音/美股代码兜底）
        assert _split_by_stock_entities("TSLA") == [Token("TSLA")]

    def test_two_char_window_not_scanned(self):
        # 窗口仅 4~3 字：2 字名称（如"美团"）不在 Step 3 扫描范围
        assert _split_by_stock_entities("美团") == [Token("美团")]


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
# Step 5.5 — 行业后缀复合词
# =========================================================================

class TestSectorCompoundSplit:
    def test_whole_compound_is_sector(self):
        # 行业词表外的"建筑"也必须整体打 sector，不得解析成"中国建筑"个股
        assert _split_by_sector_compounds("建筑板块") == [
            Token("建筑板块", "sector"),
        ]

    def test_gap_preserved(self):
        tokens = _split_by_sector_compounds("建筑板块怎么样")
        assert [(t.text, t.tag) for t in tokens] == [
            ("建筑板块", "sector"),
            ("怎么样", ""),
        ]

    def test_ascii_prefix_compound(self):
        assert _split_by_sector_compounds("AI赛道") == [Token("AI赛道", "sector")]

    def test_no_suffix_no_match(self):
        assert _split_by_sector_compounds("建筑") == [Token("建筑")]

    def test_pipeline_order_request_extracted_before_compound(self):
        # Step 5 先切出"看看"，复合词只吞并剩余行业前缀（顺序契约）
        _, tokens = _preprocess_text("看看建筑板块")
        assert ("看看", TAG_REQUEST) in [(t.text, t.tag) for t in tokens]
        assert ("建筑板块", "sector") in [(t.text, t.tag) for t in tokens]


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

    def test_one_to_one_abbreviation_resolves(self):
        tokens = _multi_match("茅台")
        assert len(tokens) == 1
        assert tokens[0].tag == TAG_STOCK_NAME
        assert [s.code for s in tokens[0].stocks] == ["600519"]

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
        assert [s.code for s in tokens[0].stocks] == ["09988", "BABA"]


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
        # "HK" Step 2 会被标成 unknown_code，但文本形态仍是市场提示
        assert _extract_markets_from_tokens([Token("HK", TAG_UNKNOWN_CODE)]) == [Market.HK]
        assert _extract_markets_from_tokens([Token("us")]) == [Market.US]

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

    def test_returns_original_text(self):
        text, _ = _preprocess_text("分析一下600519.SH")
        assert text == "分析一下600519.SH"
