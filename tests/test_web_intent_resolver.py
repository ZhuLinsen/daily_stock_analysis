# -*- coding: utf-8 -*-
"""web_intent_resolver 规则路径回归测试。

只测 _classify_by_rules 规则层（WebIntentResolver(None)：无 LLM 适配器、
无 config，resolve() 不会发起任何 LLM 调用）。规则无法定论的消息会走
rule_fallback（general_chat），因此断言以"不等于误判的意图"为主。

分词管道 Step 6 前的 AkShare 扩展在测试中 mock 为最小全量 A 股数据
（_MOCK_AKSHARE_A_SHARES），保证离线确定性；mock 之外的库外名称仍走
规则不定论路径。
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from src.agent.web_intent_resolver import (
    WebIntent, WebIntentResolver,
    _split_by_codes, TAG_UNKNOWN_CODE, TAG_UNKNOWN_NUMBER, Token,
)

INHERIT_CTX = {"recent_stocks": ["600519"], "last_intent": "stock_research"}

# 上一轮"再分析下阿里最近的走势"遗留的待确认动作（hk 09988 / us BABA）
CONFIRM_CTX = {
    "pending_actions": [
        {
            "action": "confirm_stock",
            "candidates": [
                {"code": "09988", "name": "阿里巴巴", "market": "hk"},
                {"code": "BABA", "name": "阿里巴巴", "market": "us"},
            ],
        }
    ]
}


# AkShare 扩展在分词管道 Step 6 前统一执行（extend_AkShare，30 分钟缓存）。
# 规则路径测试 mock 一份最小全量 A 股数据：确定、离线、不依赖真实网络；
# mock 之外的库外名称（你好股份/SOFI 等）仍走"规则不定论"原路径。
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
    cache = resolver_mod._akshare_cache
    merged = resolver_mod._akshare_merged
    yield
    resolver_mod.stockDB.clear()
    resolver_mod.stockDB.update(db)
    resolver_mod._akshare_cache = cache
    resolver_mod._akshare_merged = merged
    # stockDB 原地增删，按对象身份缓存的名称/拼音列表可能已陈旧，强制重建
    resolver_mod._database_names_cache[:] = [None, None, None]


@pytest.fixture(scope="module")
def resolver():
    # config=None + 无 llm_adapter → resolve() 不创建 LLM，规则层可独立判定
    return WebIntentResolver(None)


def _resolve(resolver, message, session=INHERIT_CTX):
    return resolver.resolve(message, session_context=session, request_context={})


class TestResearchRequestWithUnresolvedToken:
    """研究请求中含未识别 token（关键位置解析失败，如"你好股份"）时，
    规则不得定论为对当前股票的追问，应升级 LLM 兜底。"""

    def test_unknown_name_after_request(self, resolver):
        res = _resolve(resolver, "再分析一下你好股份基本面")
        assert res.intent != WebIntent.HISTORY_FOLLOWUP

    def test_unknown_name_before_request(self, resolver):
        res = _resolve(resolver, "你好股份分析一下")
        assert res.intent != WebIntent.HISTORY_FOLLOWUP

    def test_unknown_name_with_research_subject(self, resolver):
        res = _resolve(resolver, "研究一下你好股份的基本面")
        assert res.intent != WebIntent.HISTORY_FOLLOWUP


class TestFollowupPreserved:
    """真正的追问（无新股票名称）仍走 followup 规则路径，不回归。"""

    def test_re_analysis(self, resolver):
        res = _resolve(resolver, "再分析一下")
        assert res.intent == WebIntent.HISTORY_FOLLOWUP
        assert res.inherited_stock_code == "600519"

    def test_continue_analysis(self, resolver):
        res = _resolve(resolver, "继续分析")
        assert res.intent == WebIntent.HISTORY_FOLLOWUP

    def test_pronoun_anchor(self, resolver):
        res = _resolve(resolver, "它还能涨吗")
        assert res.intent == WebIntent.HISTORY_FOLLOWUP

    def test_re_analysis_with_topic(self, resolver):
        res = _resolve(resolver, "再分析一下它的基本面")
        assert res.intent == WebIntent.HISTORY_FOLLOWUP

    def test_no_inherited_stock_not_followup(self, resolver):
        res = _resolve(resolver, "再分析一下", session={})
        assert res.intent != WebIntent.HISTORY_FOLLOWUP


class TestUsTickerIdentification:
    """美股识别优化：本地库命中的 ticker 才辨认为 stock_code；
    库外美股保留 unknown_code 交由下游 LLM 判断（宁可不做也不做错）。

    resolver 无 LLM 适配器，升级 LLM 的消息会降级 rule_fallback(general_chat)，
    因此断言以"不等于误判的意图"为主。
    """

    def test_us_ticker_in_db_is_stock(self, resolver):
        res = _resolve(resolver, "研究一下TSLA", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.stocks and res.stocks[0].code == "TSLA"

    def test_us_ticker_with_us_suffix_in_db(self, resolver):
        res = _resolve(resolver, "看看AAPL.us", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.stocks and res.stocks[0].code == "AAPL.us"

    def test_us_ticker_not_in_db_not_stock(self, resolver):
        # SOFI 不在本地库：不得辨认为股票，规则无法定论 → 无 LLM 时降级 general_chat
        res = _resolve(resolver, "研究一下SOFI", session={})
        assert res.intent != WebIntent.STOCK_RESEARCH

    def test_english_word_not_stock(self, resolver):
        # 普通英文单词（OK）不得被当成美股代码 → 不能是 stock_research
        res = _resolve(resolver, "OK", session={})
        assert res.intent != WebIntent.STOCK_RESEARCH

    def test_us_ticker_outside_db_with_inherited_not_followup(self, resolver):
        # 库外美股 + 追问锚点 + 继承股票：不得误判为对 600519 的追问
        res = _resolve(resolver, "再分析一下SOFI", session=INHERIT_CTX)
        assert res.intent != WebIntent.HISTORY_FOLLOWUP

    def test_us_ticker_not_poisoning_explicit_code(self, resolver):
        # 有效代码 + 库外美股比较：升级 LLM，规则不定论（不静默丢弃存疑股）
        res = _resolve(resolver, "600519和SOFI哪个好", session={})
        assert res.intent != WebIntent.HISTORY_FOLLOWUP


class TestNumericCodeIdentificationPreserved:
    """A 股/港股数字代码识别保持原行为，不回归。"""

    def test_ashare_6digit(self, resolver):
        res = _resolve(resolver, "分析一下600519", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.stocks and res.stocks[0].code == "600519"

    def test_hk_5digit_bare(self, resolver):
        # 5 位裸数字（港股 00700）原行为：直接辨认为股票代码
        res = _resolve(resolver, "分析一下00700", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.stocks and res.stocks[0].code == "00700"

    def test_hk_suffix_form(self, resolver):
        res = _resolve(resolver, "00700.HK分析一下", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.stocks and res.stocks[0].code == "00700.HK"

    def test_wrong_code_still_unresolved(self, resolver):
        # 明确非法代码形字符串仍走 wrong_code → 待确认流程
        res = _resolve(resolver, "看一下777777的趋势", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.needs_confirmation
        assert "777777" in (res.unresolved_names or [])


class TestBareShortNumberTag:
    """≤4 位裸数字在 _split_by_codes 阶段直接打 unknown_number。"""

    def test_year_tag(self):
        assert _split_by_codes("2024") == [Token("2024", TAG_UNKNOWN_NUMBER)]

    def test_month_tag(self):
        assert _split_by_codes("12") == [Token("12", TAG_UNKNOWN_NUMBER)]

    def test_bare_4digit_tag(self):
        assert _split_by_codes("0070") == [Token("0070", TAG_UNKNOWN_NUMBER)]

    def test_bare_5digit_still_unknown_code(self):
        assert _split_by_codes("00700") == [Token("00700", TAG_UNKNOWN_CODE)]

    def test_bare_6digit_still_unknown_code(self):
        assert _split_by_codes("600519") == [Token("600519", TAG_UNKNOWN_CODE)]

    def test_bare_7digit_still_unknown_code(self):
        assert _split_by_codes("6005199") == [Token("6005199", TAG_UNKNOWN_CODE)]

    def test_hk_suffix_still_unknown_code(self):
        assert _split_by_codes("1234.HK") == [Token("1234.HK", TAG_UNKNOWN_CODE)]

    def test_sz_suffix_still_unknown_code(self):
        assert _split_by_codes("0070.SZ") == [Token("0070.SZ", TAG_UNKNOWN_CODE)]

    def test_hk_prefix_still_unknown_code(self):
        assert _split_by_codes("HK12") == [Token("HK12", TAG_UNKNOWN_CODE)]

    def test_date_splits_into_three_number_tokens(self):
        tokens = _split_by_codes("2024-08-12")
        assert [t.tag for t in tokens if t.tag] == [TAG_UNKNOWN_NUMBER] * 3


class TestBareShortNumberNotStock:
    """≤4 位裸数字（年份/月份/日期/价格）不得触发 stock_unresolved 确认流程。"""

    def test_year_alone_no_confirmation(self, resolver):
        res = _resolve(resolver, "2024", session={})
        assert res.intent != WebIntent.STOCK_RESEARCH
        assert not res.needs_confirmation

    def test_year_with_request_word_no_confirmation(self, resolver):
        res = _resolve(resolver, "看一下2024", session={})
        assert res.intent != WebIntent.STOCK_RESEARCH
        assert not res.needs_confirmation

    def test_year_with_research_subject_and_inherited_stock(self, resolver):
        res = _resolve(resolver, "2024年走势怎么样", session=INHERIT_CTX)
        assert res.intent != WebIntent.STOCK_RESEARCH
        assert res.intent != WebIntent.HISTORY_FOLLOWUP
        assert not res.needs_confirmation

    def test_month_no_confirmation(self, resolver):
        res = _resolve(resolver, "12月", session={})
        assert not res.needs_confirmation

    def test_date_no_confirmation(self, resolver):
        res = _resolve(resolver, "2024-08-12", session={})
        assert not res.needs_confirmation

    def test_csi300_index_still_market_overview(self, resolver):
        # "沪深300" 的 300 现在是 unknown_number，仍必须命中 market_keyword → 大盘行情
        res = _resolve(resolver, "沪深300", session={})
        assert res.intent == WebIntent.MARKET_OVERVIEW


class TestStockResearchExamples:
    """个股研究样例的规则路径回归：歧义待确认、真实股票名守卫、
    多股比较、ASCII 市场词边界、确认消费、唯一名称直判。"""

    def test_ambiguous_name_needs_confirmation(self, resolver):
        # "再分析下阿里最近的走势"：阿里 → hk 09988 / us BABA 多候选 → 待确认
        res = _resolve(resolver, "再分析下阿里最近的走势", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.needs_confirmation
        assert res.pending_action and res.pending_action.get("action") == "confirm_stock"
        codes = [c["code"] for c in res.pending_action["candidates"]]
        assert codes == ["09988", "BABA"]

    def test_real_stock_name_not_followup_guard(self, resolver):
        # 追问短路真实股票名守卫：上一轮研究茅台后"比亚迪怎么样？" → 个股研究
        res = _resolve(resolver, "比亚迪怎么样？", session=INHERIT_CTX)
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.intent != WebIntent.HISTORY_FOLLOWUP
        assert res.stocks and res.stocks[0].code == "002594"

    def test_multi_stock_comparison_no_inherited_code(self, resolver):
        # 多股比较：primary_stock_code 返回空串，绝不注入继承码 600519
        res = _resolve(resolver, "对比000858和300750", session=INHERIT_CTX)
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert [s.code for s in (res.stocks or [])] == ["000858", "300750"]
        assert res.primary_stock_code == ""

    def test_ascii_market_word_boundary(self, resolver):
        # ASCII 市场词边界：英文句中的代词 "us" 不误判为美股指示，由 TSLA 显式代码定论
        res = _resolve(resolver, "tell us about TSLA", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.stocks and res.stocks[0].code == "TSLA"

    def test_confirmation_consumed_by_market_word(self, resolver):
        # 步骤 3 消费确认："港股"市场词把候选收窄到唯一一只 → 确认港股阿里
        res = _resolve(resolver, "港股阿里", session=CONFIRM_CTX)
        assert res.source == "confirmation"
        assert res.confidence == 0.95
        assert res.stocks and res.stocks[0].code == "09988"

    def test_ambiguity_preserves_resolved_stocks_in_pending(self, resolver):
        # 混合歧义 + 已解析股票："对比阿里巴巴和腾讯控股"中的腾讯 00700 必须
        # 保留在 stocks 和 pending_action.resolved_stocks 中，确认后不得丢失
        res = _resolve(resolver, "对比阿里巴巴和腾讯控股", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.needs_confirmation
        assert [s.code for s in res.stocks] == ["00700"]
        assert res.pending_action["action"] == "confirm_stock"
        assert {c["code"] for c in res.pending_action["candidates"]} == {"09988", "BABA"}
        assert [s["code"] for s in res.pending_action["resolved_stocks"]] == ["00700"]
        assert res.pending_action["original_request"] == "对比阿里巴巴和腾讯控股"

    def test_confirmation_merges_selected_candidate_with_resolved(self, resolver):
        # 确认消费后重放比较请求：选中港股阿里 09988 时，必须与已解析的
        # 腾讯 00700 合并，primary_stock_code 保持空串（多股比较语义）；
        # original_request 必须随确认结果带出，供 SSE 层恢复比较语义
        ctx = {
            "pending_actions": [
                {
                    "action": "confirm_stock",
                    "candidates": [
                        {"code": "09988", "name": "阿里巴巴", "market": "hk"},
                        {"code": "BABA", "name": "阿里巴巴", "market": "us"},
                    ],
                    "resolved_stocks": [
                        {"code": "00700", "name": "腾讯控股", "market": "hk"}
                    ],
                    "original_request": "对比阿里巴巴和腾讯控股",
                }
            ]
        }
        res = _resolve(resolver, "港股", session=ctx)
        assert res.source == "confirmation"
        assert res.confidence == 0.95
        assert [s.code for s in res.stocks] == ["09988", "00700"]
        assert res.primary_stock_code == ""
        assert res.original_request == "对比阿里巴巴和腾讯控股"

    def test_unique_known_name_direct(self, resolver):
        # 唯一已解析名称（腾讯 → 00700）显式名称分支直接定论
        res = _resolve(resolver, "研究一下腾讯基本面以及它最近的走势", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.stocks and res.stocks[0].code == "00700"


class TestConfirmationConsumptionNegative:
    """待确认动作消费的反例回归（OR-COR-91d4de84）。

    上一轮遗留的歧义候选（hk 09988 / us BABA 都叫"阿里巴巴"）在用户下一条
    消息中再次出现时，不得静默确认第一只 09988：
      - 带市场提示（"美股阿里巴巴"）必须按市场收窄 → BABA；
      - 带新请求（"再分析下阿里巴巴最近走势"）或比较（"阿里巴巴和腾讯对比
        一下"）必须按新消息重新分类，跳过确认消费。
    """

    def test_market_hint_narrows_cross_market_candidate(self, resolver):
        # "美股"提示必须把候选收窄到唯一美股 BABA，而不是子串抢先命中 09988
        res = _resolve(resolver, "美股阿里巴巴", session=CONFIRM_CTX)
        assert res.source == "confirmation"
        assert res.stocks and res.stocks[0].code == "BABA"

    def test_research_request_with_ambiguous_name_reclassified(self, resolver):
        # 研究请求 + 歧义名称再次出现 → 按新消息重新分类，不消费为确认
        res = _resolve(resolver, "再分析下阿里巴巴最近走势", session=CONFIRM_CTX)
        assert res.source != "confirmation"
        assert not (res.stocks and res.stocks[0].code == "09988")

    def test_comparison_with_ambiguous_name_reclassified(self, resolver):
        # 比较请求 + 歧义名称再次出现 → 按新消息重新分类，不消费为确认
        res = _resolve(resolver, "阿里巴巴和腾讯对比一下", session=CONFIRM_CTX)
        assert res.source != "confirmation"
        assert not (res.stocks and res.stocks[0].code == "09988")

    def test_new_request_with_market_word_not_hijacked(self, resolver):
        # 新研究请求 + 市场词 + 其他股票（"帮我分析一下港股腾讯"）不得被市场词
        # 收窄分支抢先确认成 09988（港股阿里），必须按新消息重新分类解析腾讯
        res = _resolve(resolver, "帮我分析一下港股腾讯", session=CONFIRM_CTX)
        assert res.source != "confirmation"
        assert res.stocks and res.stocks[0].code == "00700"

    def test_market_word_plus_same_name_still_confirms(self, resolver):
        # 同一歧义股票 + 市场词（"看一下港股阿里巴巴"）仍是确认：按市场收窄 → 09988
        res = _resolve(resolver, "看一下港股阿里巴巴", session=CONFIRM_CTX)
        assert res.source == "confirmation"
        assert res.stocks and res.stocks[0].code == "09988"


class TestMultiStockEntityRecognition:
    """多股票实体识别：一句话识别多只股票（全名 + 一对一缩写），
    与单 token 多候选的歧义（阿里）严格区分。

    - 多只确定实体 → stocks（primary_stock_code 为空串，绝不注入继承码）；
    - 单 token 多候选 → candidates + needs_confirmation（歧义确认路径）。
    Step 3 仅做全名精确匹配（窗口必须整体等于库中股票全名），一对一缩写
    （茅台/比亚迪）非全名，交由 Step 6 多策略匹配承接。
    分词管道 Step 6 前统一执行 AkShare 扩展（extend_AkShare，全模块唯一
    调用点；本测试模块 mock 为最小全量 A 股数据，见 _MOCK_AKSHARE_A_SHARES）：
    酒鬼酒/三花智控/中大力德等本地静态库外真实 A 股由此在规则路径直接定论；
    mock 之外的库外名称（你好股份等）仍升级 LLM（无 LLM 时降级 rule_fallback），
    绝不静默解析成唯一单只或误判为对上一轮的追问。
    """

    def test_extended_full_name_resolved_by_rule_path(self, resolver):
        # "酒鬼酒"本地映射外、AkShare 扩展后全名精确命中（Step 3 重扫）：
        # 与茅台一起由规则直接定论双股比较，不再升级 LLM
        res = _resolve(resolver, "对比茅台和酒鬼酒的基本面", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert [s.code for s in (res.stocks or [])] == ["600519", "000799"]
        assert not res.needs_confirmation

    def test_extended_abbreviation_resolved_by_multi_match(self, resolver):
        # "三花/中大力德"本地库外一对一缩写：Step 6 多策略匹配在扩展库命中，
        # 规则直接定论双股比较，不再升级 LLM
        res = _resolve(resolver, "对比三花和中大力德的趋势", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert [s.code for s in (res.stocks or [])] == ["002050", "002896"]
        assert not res.needs_confirmation

    def test_extended_names_no_inherited_code(self, resolver):
        # 扩展库命中双股：primary_stock_code 为空串，绝不注入上一轮继承码
        # 600519，也不误判为对它的追问
        res = _resolve(resolver, "对比茅台和酒鬼酒的基本面", session=INHERIT_CTX)
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.primary_stock_code == ""
        assert [s.code for s in (res.stocks or [])] == ["600519", "000799"]

    def test_single_abbreviation_is_definite(self, resolver):
        # 一对一缩写（茅台→600519）直接定论，不触发确认
        res = _resolve(resolver, "帮我看看茅台", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert [s.code for s in (res.stocks or [])] == ["600519"]
        assert not res.needs_confirmation

    def test_local_unique_name_direct(self, resolver):
        # "东方"在本地库唯一解析为东方财富（东方雨虹/东方航空/京东方A 在库外，
        # 真实歧义交由 LLM 兜底路径处理）→ 唯一已解析名称直接定论
        res = _resolve(resolver, "研究一下东方", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert [s.code for s in (res.stocks or [])] == ["300059"]
        assert not res.needs_confirmation

    def test_ambiguous_alias_still_confirmation(self, resolver):
        # 既有歧义回归：阿里 → hk09988 / us BABA 仍是歧义确认，不回归
        res = _resolve(resolver, "再分析下阿里最近的走势", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert res.needs_confirmation
        codes = [c["code"] for c in res.pending_action["candidates"]]
        assert codes == ["09988", "BABA"]

    def test_multi_stock_with_comparison_keyword(self, resolver):
        res = _resolve(resolver, "茅台和比亚迪哪个好", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert [s.code for s in (res.stocks or [])] == ["600519", "002594"]

    def test_common_suffix_not_silently_definite(self, resolver):
        # 通用后缀"股份"命中多只（伊利股份/凌云股份）→ 歧义确认，
        # 绝不静默解析成唯一命中的单只股票
        res = _resolve(resolver, "再分析一下你好股份基本面", session=INHERIT_CTX)
        assert res.intent != WebIntent.HISTORY_FOLLOWUP
        assert not (res.stocks and [s.code for s in res.stocks] == ["600887"])


class TestPortfolioReviewExamples:
    """持仓回顾样例：持仓关键词优先级最高，即使与疑问词/显式代码并存。"""

    def test_portfolio_with_question_word(self, resolver):
        res = _resolve(resolver, "我的持仓今天怎么样", session={})
        assert res.intent == WebIntent.PORTFOLIO_REVIEW
        assert res.reason == "portfolio_keyword"

    def test_portfolio_wins_over_explicit_code(self, resolver):
        # 持仓词 + 显式代码并存：持仓意图胜出（持仓分支在代码分支之前）
        res = _resolve(resolver, "看看我的持仓 600519", session={})
        assert res.intent == WebIntent.PORTFOLIO_REVIEW


class TestMarketOverviewExamples:
    """大盘行情样例：指数词/板块语境/市场词 → market_overview，携带市场推断。"""

    def test_index_keyword(self, resolver):
        res = _resolve(resolver, "上证指数今天涨了多少", session={})
        assert res.intent == WebIntent.MARKET_OVERVIEW
        assert res.reason == "market_keyword"

    def test_sector_context_unknown_code(self, resolver):
        # "AI" 是库外 unknown_code，但带板块语境 → 升级保护豁免 → 大盘行情
        res = _resolve(resolver, "AI板块怎么样", session={})
        assert res.intent == WebIntent.MARKET_OVERVIEW

    def test_market_word_with_market_inference(self, resolver):
        res = _resolve(resolver, "港股最近行情和趋势怎么样", session={})
        assert res.intent == WebIntent.MARKET_OVERVIEW
        assert res.market == "hk"


class TestHistoryFollowupExamples:
    """追问样例：追问锚点 + 继承代码，含研究决策词但无 request 词时不误升级。"""

    def test_followup_with_decision_word(self, resolver):
        res = _resolve(resolver, "那它在支撑位可以抄底吗", session=INHERIT_CTX)
        assert res.intent == WebIntent.HISTORY_FOLLOWUP
        assert res.inherited_stock_code == "600519"
        assert res.primary_stock_code == "600519"


class TestGeneralChatExamples:
    """闲聊样例：无信号与空消息短路。"""

    def test_no_signal(self, resolver):
        res = _resolve(resolver, "你好", session={})
        assert res.intent == WebIntent.GENERAL_CHAT
        assert res.reason == "no_signal"

    def test_empty_message_short_circuit(self, resolver):
        res = _resolve(resolver, "", session={})
        assert res.intent == WebIntent.GENERAL_CHAT
        assert res.confidence == 1.0
        assert res.reason == "empty_message"


class TestAkShareExtensionSinglePoint:
    """AkShare 扩展是全模块唯一调用点：只在分词管道 Step 6 前执行；
    LLM 提及解析（_resolve_mentions）只查已扩充的库，绝不再次扩展。"""

    def test_preprocess_extension_reaches_rule_path(self, resolver):
        # 首次解析触发扩展（mock 数据并入 stockDB），库外全名在规则路径直接定论；
        # 重复解析零新条目、幂等，不改变定论
        res = _resolve(resolver, "对比茅台和酒鬼酒的基本面", session={})
        assert res.intent == WebIntent.STOCK_RESEARCH
        assert [s.code for s in (res.stocks or [])] == ["600519", "000799"]
        res2 = _resolve(resolver, "对比茅台和酒鬼酒的基本面", session={})
        assert res2.intent == WebIntent.STOCK_RESEARCH
        assert [s.code for s in (res2.stocks or [])] == ["600519", "000799"]

    def test_resolve_mentions_never_fetches_akshare(self, monkeypatch):
        from src.services import name_to_code_resolver as resolver_mod

        calls = {"n": 0}

        def fake_get():
            calls["n"] += 1
            return {"酒鬼酒": "000799"}

        monkeypatch.setattr(resolver_mod, "_get_akshare_name_to_code", fake_get)
        stocks, candidates, unresolved = WebIntentResolver._resolve_mentions(["酒鬼酒"])
        assert calls["n"] == 0  # 库外名称也只查库，绝不发起 AkShare 拉取
        assert not stocks and not candidates
        assert unresolved == ["酒鬼酒"]
