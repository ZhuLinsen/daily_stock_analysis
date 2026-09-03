# -*- coding: utf-8 -*-
"""web_intent_resolver 核心解析器单测。

纯 Python 层离线测试（不依赖 agent.py / SSE / 真实网络）：
  - 规则分类：stock_analysis / sector_analysis / portfolio_analysis /
    quote_lookup / general_chat 的判定矩阵与置信度路径常量；追问走
    上下文继承（继承上轮执行类意图）；
  - 意图边界矩阵：三判别测试（个性化/深度/对象）的易混淆对照用例
    （每对 query 只差一两个字、意图完全不同），与 web_intent_types
    模块 docstring 的对照表互为基线；
  - 裸数字代码提升（6 位 + 首码白名单 + 非量词后缀 + 查库四重闸门）；
  - 歧义确认与市场消歧（ambiguous_stock_name / pending_action 形状）；
  - wrong code（stock_unresolved）与低置信（low_confidence）确认短路；
  - LLM 兜底（stub adapter）：置信度上限、幻觉代码拒收、候选消歧、
    坏输出回退、followup 伪标签继承/降级；
  - 确认消费：序号/名称/裸代码/拒绝/新话题/模糊回应的完整生命周期；
  - 会话簿记：recent_stocks 头插去重截断、pending_actions 替换式收敛、
    last_intent、ConversationSession 形态（.context dict）兼容；

AkShare 扩展 mock 为最小全量 A 股数据（与 test_web_intent_tokenizer 同
约定），保证离线确定性；LLM 由 _StubLLMAdapter 可编程返回，不触网络。
"""

import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from src.agent.llm_adapter import LLMResponse
from src.agent.web_intent_resolver import (
    LAST_INTENT_KEY,
    LAST_RESOLUTIONS_KEY,
    LLM_CONFIDENCE_CAP,
    MAX_RECENT_STOCKS,
    PENDING_ACTIONS_KEY,
    RECENT_STOCKS_KEY,
    Stock,
    TAG_STOCK_NAME,
    WebIntent,
    WebIntentResolution,
    WebIntentResolver,
    _consume_confirmations,
    _dedup_stocks,
    _disambiguate_by_market,
    _finalize_confirmation,
    _merge_llm_result,
    _normalize_pending_groups,
    _parse_llm_payload,
    _preprocess_text,
    _identify_stock_codes,
    _session_context,
    _split_sub_messages,
    apply_outcome,
    apply_pending,
    apply_resolution_to_session,
    clear_pending_actions,
)
from src.agent.web_intent_types import Market

# 与 test_web_intent_tokenizer 相同的最小全量 A 股 mock：确定、离线
_MOCK_AKSHARE_A_SHARES = {
    "酒鬼酒": "000799",
    "三花智控": "002050",
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
# 测试辅助
# =========================================================================


@dataclass
class _FakeSession:
    """ConversationSession 形态替身：bookkeeping 走 .context dict。"""

    context: Dict[str, Any] = field(default_factory=dict)


class _StubLLMAdapter:
    """可编程 LLM stub：记录调用、按脚本返回/抛错，不触网络。"""

    def __init__(
        self,
        content: Optional[str] = None,
        provider: str = "stub",
        exc: Optional[Exception] = None,
    ) -> None:
        self.content = content
        self.provider = provider
        self.exc = exc
        self.calls: List[Dict[str, Any]] = []

    def call_text(self, messages, **kwargs) -> LLMResponse:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self.exc is not None:
            raise self.exc
        return LLMResponse(content=self.content, provider=self.provider)


def _resolver(llm: Any = None) -> WebIntentResolver:
    return WebIntentResolver(llm_adapter=llm)


def _pending_ali() -> Dict[str, Any]:
    """标准阿里巴巴歧义 pending 动作（跨市场双候选）。"""
    return {
        "action": "confirm_stock",
        "intent": "stock_analysis",
        "name": "阿里巴巴",
        "candidates": [
            {"code": "HK09988", "name": "阿里巴巴", "market": "hk"},
            {"code": "BABA", "name": "阿里巴巴", "market": "us"},
        ],
        "original_request": "分析阿里巴巴",
    }


def _flat(two_dim):
    """二维任务列表（外层=子消息任务组）→ 一维任务列表（断言可读形态）。"""
    return [t for group in two_dim for t in group]


def _codes(resolution: WebIntentResolution) -> List[str]:
    return [s.code for s in resolution.stocks]


def _candidate_codes(resolution: WebIntentResolution) -> List[str]:
    return [c.code for c in resolution.candidates]


def _sub_texts(text: str) -> List[str]:
    """_split_sub_messages 二维 tokens → 子消息文本列表（断言可读形态）。"""
    return ["".join(t.text for t in sub) for sub in _split_sub_messages(text)]


# =========================================================================
# 空输入
# =========================================================================


class TestEmptyInput:
    def test_empty_string(self):
        r = _resolver().resolve_first("")
        assert r.intent == WebIntent.GENERAL_CHAT
        assert r.source == "rule"
        assert r.stocks == []
        assert not r.needs_confirmation

    def test_whitespace_only(self):
        r = _resolver().resolve_first("   \n\t ")
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_none_input(self):
        r = _resolver().resolve_first(None)  # type: ignore[arg-type]
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_punct_only(self):
        r = _resolver().resolve_first("！！！？？")
        assert r.intent == WebIntent.GENERAL_CHAT
        assert r.confidence == 0.5


# =========================================================================
# 规则分类 — stock_analysis
# =========================================================================


class TestRuleStockAnalysis:
    def test_explicit_a_code(self):
        r = _resolver().resolve_first("分析600519")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.source == "rule"
        assert r.confidence == 0.9
        assert _codes(r) == ["600519"]

    def test_bare_a_code(self):
        r = _resolver().resolve_first("600519")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["600519"]

    def test_exchange_suffixed_code(self):
        r = _resolver().resolve_first("600519.SH 怎么样")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["600519"]

    def test_hk_prefixed_code(self):
        r = _resolver().resolve_first("HK00700怎么样")
        assert _codes(r) == ["HK00700"]
        assert r.confidence == 0.9

    def test_us_ticker(self):
        r = _resolver().resolve_first("分析AAPL")
        assert _codes(r) == ["AAPL"]

    def test_full_name_with_request(self):
        r = _resolver().resolve_first("分析贵州茅台")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.confidence == 0.85
        assert _codes(r) == ["600519"]

    def test_bare_abbreviation_name(self):
        # 裸个股指称的默认归属是股票分析（T2/T3：无数据词即观点类任务）
        r = _resolver().resolve_first("茅台")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.confidence == 0.8
        assert _codes(r) == ["600519"]

    def test_comparison_two_codes(self):
        r = _resolver().resolve_first("对比000858和300750")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["000858", "300750"]
        assert r.primary_stock_code == ""  # 多股比较不锁定单一 scope

    def test_institutional_holdings_is_research(self):
        # 无第一人称领属的"持仓"是研究维度（机构/北向持仓），不是组合语境
        r = _resolver().resolve_first("分析茅台的持仓")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["600519"]

    def test_mock_akshare_name_resolvable(self):
        r = _resolver().resolve_first("分析酒鬼酒")
        assert _codes(r) == ["000799"]

    def test_function_words_do_not_block_entity(self):
        # 高频功能词（你/觉得，filler extend 池）作 DFS 全覆盖片段：
        # 实体前的口语前缀不阻断实体提取
        r = _resolver().resolve_first("你觉得茅台怎么样")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["600519"]

    def test_no_confirmation_at_high_confidence(self):
        r = _resolver().resolve_first("分析600519")
        assert not r.needs_confirmation
        assert r.pending_action is None


# =========================================================================
# 规则分类 — portfolio_analysis / quote_lookup / sector_analysis / 闲聊
# =========================================================================


class TestRulePortfolioAnalysis:
    @pytest.mark.parametrize("text", [
        "我的持仓怎么样",
        "帮我看看自选股",
        "加仓还是减仓",
        "我的仓位如何",
    ])
    def test_portfolio_inputs(self, text):
        # T1 个性化：无个股指称时持仓/自选股词即整体组合语境
        r = _resolver().resolve_first(text)
        assert r.intent == WebIntent.PORTFOLIO_ANALYSIS
        assert r.confidence == 0.85
        assert r.stocks == []

    def test_portfolio_action_with_entity(self):
        # 3a：持仓操作词 + 个股 = 组合语境下的个股评估（依赖成本/仓位）
        r = _resolver().resolve_first("我的茅台还该拿着吗")
        assert r.intent == WebIntent.PORTFOLIO_ANALYSIS
        assert _codes(r) == ["600519"]
        assert not r.needs_confirmation

    def test_portfolio_subject_with_possessive(self):
        # 3b：持仓主题 + 第一人称领属 + 无强分析词 → 组合语境
        r = _resolver().resolve_first("我的茅台仓位重不重")
        assert r.intent == WebIntent.PORTFOLIO_ANALYSIS
        assert _codes(r) == ["600519"]

    def test_possessive_with_research_subject_is_stock(self):
        # 3b 反例：句中有"我"但答案对所有用户相同 → 股票分析
        r = _resolver().resolve_first("我的茅台基本面怎么样")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["600519"]


class TestRuleQuoteLookup:
    def test_broad_market_default_quote(self):
        # 泛市场裸词默认报数（T2）：大盘不可能是股票，对象无歧义
        r = _resolver().resolve_first("今天大盘怎么样")
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert r.confidence == 0.85

    def test_market_keyword_sets_sector_slot(self):
        # 市场词的市场范围由 sectors 槽承载（"港股行情"→["港股"]）
        r = _resolver().resolve_first("港股行情")
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert r.sectors == ["港股"]

    def test_index_keyword(self):
        r = _resolver().resolve_first("上证指数怎么样")
        assert r.intent == WebIntent.QUOTE_LOOKUP

    def test_digit_index_keyword(self):
        # 含数字指数词（沪深300）：数字段受 Step 3 保护区放行
        r = _resolver().resolve_first("沪深300怎么样")
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert r.confidence == 0.85

    def test_entity_with_quote_word(self):
        # 个股路径 T2：数据词（多少钱）+ 无强分析词 → 行情查询
        r = _resolver().resolve_first("茅台多少钱")
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert _codes(r) == ["600519"]
        assert r.confidence == 0.85

    def test_now_adverb_between_entity_and_quote(self):
        # "现在"（extend，⊂"出现在"）经 DFS 全覆盖（茅台+现在）完成实体
        # 提取：实体与数据词之间的口语词不阻断识别，超串场景不被盲撕
        r = _resolver().resolve_first("茅台现在多少钱")
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert _codes(r) == ["600519"]

    def test_market_word_with_entity_is_research(self):
        r = _resolver().resolve_first("A股600519怎么样")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["600519"]


class TestRuleSectorAnalysis:
    def test_sector_combo_opinion(self):
        # "行业名+泛称"相邻组合消除对象歧义 → 高置信板块分析
        r = _resolver().resolve_first("白酒板块怎么看")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85
        assert r.stocks == []

    def test_market_opinion_upgrades_to_sector(self):
        # 泛市场 + 观点/结构判断（T2 强分析词）→ 市场结构分析归板块意图
        r = _resolver().resolve_first("大盘怎么看")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85

    def test_bare_sector_name_exact_pool_high_confidence(self):
        # 精确命中行业名词池（半导体）＝行业 vs 个股双解已消 → 0.85 直达；
        # 行业兼股票名（机器人，sector_n_stock）双解未消 → 0.5 交 LLM 裁定
        r = _resolver().resolve_first("半导体怎么样")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85
        r2 = _resolver().resolve_first("机器人怎么样")
        assert r2.intent == WebIntent.SECTOR_ANALYSIS
        assert r2.confidence == 0.5


class TestRuleGeneralChat:
    def test_greeting(self):
        r = _resolver().resolve_first("你好")
        assert r.intent == WebIntent.GENERAL_CHAT
        assert r.confidence == 0.5
        assert not r.needs_confirmation  # 闲聊非执行类，无需确认

    def test_weather(self):
        r = _resolver().resolve_first("今天天气不错")
        assert r.intent == WebIntent.GENERAL_CHAT


# =========================================================================
# 裸数字代码提升 — 四重闸门
# =========================================================================


class TestNumericCodePromotion:
    def test_promotion_with_request(self):
        r = _resolver().resolve_first("分析300750")
        assert _codes(r) == ["300750"]
        assert r.confidence == 0.9

    def test_promotion_bare(self):
        r = _resolver().resolve_first("300750怎么样")
        assert _codes(r) == ["300750"]

    def test_amount_not_promoted(self):
        # 量词后缀：金额语义，绝不当代码
        r = _resolver().resolve_first("我有300750元")
        assert r.intent == WebIntent.GENERAL_CHAT
        assert r.stocks == []

    def test_index_point_not_promoted(self):
        r = _resolver().resolve_first("上证3300点怎么样")
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert r.stocks == []

    def test_year_not_promoted(self):
        r = _resolver().resolve_first("2024年怎么样")
        assert r.stocks == []

    def test_non_whitelisted_first_digit_not_promoted(self):
        # 首码白名单（0/3/6/4/8/92）：999999 形态非法不提升
        r = _resolver().resolve_first("分析999999")
        assert r.stocks == []
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_not_in_db_not_promoted(self):
        # 白名单通过但查库未命中（本地库无此 A 股）：不虚构实体
        r = _resolver().resolve_first("分析360001")
        assert r.stocks == []

    def test_five_digit_not_promoted(self):
        # 5 位裸数字与日期/价格共形，不提升（交 LLM/确认兜底）
        r = _resolver().resolve_first("分析00700")
        assert r.stocks == []
        assert r.candidates == []


# =========================================================================
# 歧义确认与市场消歧
# =========================================================================


class TestAmbiguityConfirmation:
    def test_cross_market_name_needs_confirmation(self):
        r = _resolver().resolve_first("阿里巴巴")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.needs_confirmation
        assert r.reason == "ambiguous_stock_name"
        assert set(_candidate_codes(r)) == {"HK09988", "BABA"}
        assert r.stocks == []  # 未消解前不携带确定实体

    def test_pending_action_shape(self):
        r = _resolver().resolve_first("分析阿里巴巴")
        pa = r.pending_action
        assert pa is not None
        assert pa["action"] == "confirm_stock"
        assert pa["original_request"] == "分析阿里巴巴"
        # groups 是唯一权威结构（无顶层 name/candidates 投影）
        assert "name" not in pa and "candidates" not in pa
        assert len(pa["groups"]) == 1
        g = pa["groups"][0]
        assert g["name"] == "阿里巴巴"
        assert {c["code"] for c in g["candidates"]} == {"HK09988", "BABA"}
        for c in g["candidates"]:
            assert set(c.keys()) == {"code", "name", "market"}

    def test_market_word_disambiguates(self):
        # 市场词收窄：消解行为落在 stocks（市场范围由 sectors 槽承载）
        r = _resolver().resolve_first("港股阿里巴巴")
        assert not r.needs_confirmation
        assert _codes(r) == ["HK09988"]

    def test_us_market_word_disambiguates(self):
        r = _resolver().resolve_first("美股阿里巴巴")
        assert _codes(r) == ["BABA"]

    def test_dual_listing_a_hk(self):
        r = _resolver().resolve_first("分析中芯国际")
        assert r.needs_confirmation
        assert set(_candidate_codes(r)) == {"688981", "HK00981"}

    def test_confirmed_plus_ambiguous_mix(self):
        # 确定实体与歧义并存：stocks 带确定项，歧义仍触发确认
        r = _resolver().resolve_first("分析600519和阿里巴巴")
        assert _codes(r) == ["600519"]
        assert r.needs_confirmation
        assert set(_candidate_codes(r)) == {"HK09988", "BABA"}


# =========================================================================
# wrong code / 存疑代码 / 低置信确认
# =========================================================================


class TestWrongCodeConfirmation:
    def test_invalid_suffixed_code(self):
        # 6 位 A 股形态挂 .HK 后缀：标注市场与形态矛盾 → wrong_hk_code
        r = _resolver().resolve_first("分析600519.HK")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.needs_confirmation
        assert r.reason == "stock_unresolved"
        assert r.unresolved_names == ["600519.HK"]
        assert r.confidence == 0.9

    def test_invalid_exchange_prefix(self):
        # SH + 999999：首码白名单不过 → wrong_a_code
        r = _resolver().resolve_first("分析SH999999")
        assert r.needs_confirmation
        assert r.reason == "stock_unresolved"

    def test_wrong_code_pending_action_has_no_candidates(self):
        r = _resolver().resolve_first("分析SH999999")
        pa = r.pending_action
        assert pa["action"] == "confirm_stock"
        assert pa["groups"] == []


class TestLowConfidenceConfirmation:
    def test_unknown_us_ticker_without_llm(self):
        # 库外美股 ticker → unknown_us_code：非全量库无法判定合法与否，
        # 不做确认——未验证代码透传执行端实查（rule 直达，无 LLM）
        r = _resolver().resolve_first("分析ZZZZ")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.confidence == 0.8
        assert r.unverified_codes == ["ZZZZ"]
        assert not r.needs_confirmation

    def test_sector_only_without_llm(self):
        # 行业名兼股票全名（机器人）：意图归属无法由规则裁定 → 确认
        r = _resolver().resolve_first("分析机器人")
        assert r.needs_confirmation
        assert r.reason == "low_confidence"
        assert r.confidence < 0.6

    def test_general_chat_not_confirmed(self):
        # 闲聊虽低置信但非执行类，直接放行不确认
        r = _resolver().resolve_first("你好")
        assert not r.needs_confirmation


# =========================================================================
# LLM 兜底
# =========================================================================


def _llm_json(intent: str, confidence: float = 0.9, **extra) -> str:
    import json
    return json.dumps({"intent": intent, "confidence": confidence, **extra}, ensure_ascii=False)


class TestLLMFallback:
    def test_confidence_capped(self):
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.99))
        r = _resolver(stub).resolve_first("聊聊电影")
        assert r.source == "llm"
        assert r.confidence == LLM_CONFIDENCE_CAP

    def test_valid_stock_code_injected(self):
        stub = _StubLLMAdapter(content=_llm_json("stock_analysis", 0.8, stock_code="600519"))
        r = _resolver(stub).resolve_first("帮我看看那只白酒股")
        assert r.source == "llm"
        assert _codes(r) == ["600519"]

    def test_hallucinated_code_rejected(self):
        # LLM 给出库外代码：拒收注入、转 stock_unresolved 确认
        stub = _StubLLMAdapter(content=_llm_json("stock_analysis", 0.9, stock_code="888888"))
        r = _resolver(stub).resolve_first("随便看看")
        assert r.source == "llm"
        assert r.stocks == []
        assert r.unresolved_names == ["888888"]
        assert r.needs_confirmation
        assert r.reason == "stock_unresolved"

    def test_llm_disambiguates_candidates(self):
        # candidates 与 LLM 触发无关："阿里巴巴" tag 全识别 + 0.8 → 规则
        # 直达转用户确认，大模型零调用（歧义出口是确认，不是猜选）
        stub = _StubLLMAdapter(content=_llm_json("stock_analysis", 0.9, stock_code="HK09988"))
        r = _resolver(stub).resolve_first("阿里巴巴")
        assert stub.calls == []
        assert r.source == "rule"
        assert set(_candidate_codes(r)) == {"HK09988", "BABA"}
        assert r.needs_confirmation
        assert r.reason == "ambiguous_stock_name"

    def test_rule_entities_preserved(self):
        # 规则已解析的硬实体不因 LLM 未提及而丢失
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        r = _resolver(stub).resolve_first("600519")
        assert _codes(r) == ["600519"]

    def test_high_confidence_exempt_from_side_triggers(self):
        # 主体已高置信时附带存疑不触发 LLM 复核："顺便"切分后主任务
        # （报价）规则直达且置信度不被压低；附带是独立的第二任务，
        # 其存疑透传由该任务自身承接
        stub = _StubLLMAdapter(content='{"intent": "quote_lookup", "confidence": 0.9}')
        rs = WebIntentResolver(llm_adapter=stub).resolve("茅台多少钱顺便看下SOFI")
        # 主任务高置信直达（stub 仅被附带子消息调用一次）；附带被 LLM
        # 改判 quote 独立成任务（不折叠，LLM cap 0.75）
        assert len(stub.calls) == 1
        tasks = _flat(rs)
        assert len(tasks) == 2
        assert tasks[0].source == "rule" and tasks[0].confidence == 0.85
        assert tasks[0].intent == WebIntent.QUOTE_LOOKUP
        assert _codes(tasks[0]) == ["600519"]
        assert tasks[1].source == "llm" and tasks[1].confidence == 0.75
        assert tasks[1].unverified_codes == ["SOFI"]

    def test_unknown_code_as_subject_passes_through(self):
        # 存疑代码主体（有意图词"分析"）：hk/us 无法判定合法与否，
        # 规则直达放行（不确认不 LLM），unverified 透传执行端
        stub = _StubLLMAdapter(content='{"intent": "quote_lookup", "confidence": 0.9}')
        r = WebIntentResolver(llm_adapter=stub).resolve_first("分析下SOFI")
        assert len(stub.calls) == 0
        assert r.source == "rule"
        assert r.unverified_codes == ["SOFI"]
        assert not r.needs_confirmation

    def test_llm_failed_low_confidence_chat_not_released(self):
        # 证据状态守恒：复核被触发即证明规则不可靠，复核失败后证据
        # 未变——llm_failed 的低置信闲聊候选不放行，转澄清确认
        # （词池外板块"哈喽板块"整段 DFS 陪葬时，LLM 是唯一识别路径）
        stub = _StubLLMAdapter(exc=RuntimeError("timeout"))
        rs = WebIntentResolver(llm_adapter=stub).resolve("然后再分析一下哈喽板块")
        r = _flat(rs)[0]
        assert r.source == "llm_failed"
        assert r.intent == WebIntent.GENERAL_CHAT
        assert r.confidence == 0.5
        assert r.needs_confirmation is True
        assert r.reason == "low_confidence"

    def test_llm_failed_confident_chat_still_released(self):
        # 高置信闲聊（复核因其他条件触发但闲聊判定可靠）不受影响
        stub = _StubLLMAdapter(exc=RuntimeError("timeout"))
        rs = WebIntentResolver(llm_adapter=stub).resolve("你好呀")
        assert _flat(rs)[0].intent == WebIntent.GENERAL_CHAT
        assert _flat(rs)[0].needs_confirmation is False

    def test_llm_failed_keeps_rule_result_and_confidence(self):
        # llm_failed 与 rule 的区分：兜底已触发但失败——意图/置信度/
        # stocks 与规则判定同源（"你好"规则闲聊 0.5），仅 source 标记
        # 路径；同消息未配 LLM 时为纯 rule
        stub = _StubLLMAdapter(exc=RuntimeError("timeout"))
        r = WebIntentResolver(llm_adapter=stub).resolve_first("你好")
        assert r.source == "llm_failed"
        assert r.intent == WebIntent.GENERAL_CHAT
        assert r.confidence == 0.5
        r2 = _resolver().resolve_first("你好")
        assert r2.source == "rule"
        assert (r2.intent, r2.confidence) == (r.intent, r.confidence)

    def test_bad_json_falls_back_to_rules(self):
        stub = _StubLLMAdapter(content="我觉得是股票研究")
        r = _resolver(stub).resolve_first("你好")
        assert r.source == "llm_failed"
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_invalid_intent_falls_back(self):
        stub = _StubLLMAdapter(content=_llm_json("unknown_intent", 0.9))
        r = _resolver(stub).resolve_first("你好")
        assert r.source == "llm_failed"

    def test_exception_falls_back(self):
        stub = _StubLLMAdapter(exc=RuntimeError("boom"))
        r = _resolver(stub).resolve_first("你好")
        assert r.source == "llm_failed"

    def test_error_provider_falls_back(self):
        stub = _StubLLMAdapter(content="...", provider="error")
        r = _resolver(stub).resolve_first("你好")
        assert r.source == "llm_failed"

    def test_followup_without_context_downgraded(self):
        # LLM 返回 followup 伪标签但上轮是闲聊：无产物可追问，降级闲聊
        stub = _StubLLMAdapter(content=_llm_json("followup", 0.9))
        session = {LAST_INTENT_KEY: "general_chat"}
        r = _resolver(stub).resolve_first("继续", session_context=session)
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_followup_with_context_inherits_intent(self):
        # 规则无信号（"再展开讲讲"无 followup 词）→ LLM 判 followup 且
        # 上轮为执行类意图 → 伪标签转为继承上轮意图（不是独立意图）
        stub = _StubLLMAdapter(content=_llm_json("followup", 0.9))
        session = {LAST_INTENT_KEY: "stock_analysis"}
        r = _resolver(stub).resolve_first("再展开讲讲", session_context=session)
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.source == "llm"

    def test_prompt_carries_context(self):
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        session = {
            RECENT_STOCKS_KEY: ["600519"],
            LAST_INTENT_KEY: "stock_analysis",
        }
        _resolver(stub).resolve_first("聊聊", session_context=session)
        assert len(stub.calls) == 1
        user_body = stub.calls[0]["messages"][1]["content"]
        assert "聊聊" in user_body
        assert "600519" in user_body
        assert "stock_analysis" in user_body
        # 低温度确定性输出 + 有界超时
        assert stub.calls[0]["kwargs"]["temperature"] == 0.0

    def test_prompt_carries_chain_subject_for_fragment(self):
        # 多任务消息的子消息片段触发兜底时，prompt 携带链式主体
        # current_stock（同消息前序片段已确定的标的，查库派生三元组）：
        # 片段自身无标的（"和市盈率"），LLM 凭 current_stock 判回执行类
        # 意图并回代码，合并后报价诉求不降级闲聊
        # 无主体意图片段（"和市盈率"）默认主体为"它"走继承，
        # 链式主体在场（HK00700）→ 判定可靠 → 零调用直达
        stub = _StubLLMAdapter(content=_llm_json(
            "quote_lookup", 0.9, stock_code="HK00700"))
        rs = _resolver(stub).resolve("看下HK00700股价，和市盈率", {})
        assert stub.calls == [], "继承产物主体在场，免复核直达"
        frag = _flat(rs)[1]
        assert frag.source == "context"
        assert frag.intent == WebIntent.QUOTE_LOOKUP
        assert frag.primary_stock_code == "HK00700"
        # blob 变体（视野残缺）仍复核：prompt 携带链式主体 current_stock
        stub2 = _StubLLMAdapter(content=_llm_json(
            "quote_lookup", 0.9, stock_code="HK00700"))
        rs2 = _resolver(stub2).resolve("看下HK00700股价，和市盈率哈哈", {})
        assert len(stub2.calls) == 1, "视野残缺强制复核"
        user_body = stub2.calls[0]["messages"][1]["content"]
        assert '"current_stock": {"code": "HK00700"' in user_body
        assert _codes(_flat(rs2)[1]) == ["HK00700"],             "复核合并后市盈率诉求指向链式主体，不降级闲聊"

    def test_high_confidence_rule_skips_llm(self):
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        _resolver(stub).resolve_first("分析600519")
        assert stub.calls == []

    def test_low_confidence_rule_invokes_llm(self):
        # 行业兼股票名（双解未消，无 combo）：对象歧义 → 低置信交 LLM 裁定
        stub = _StubLLMAdapter(content=_llm_json("sector_analysis", 0.9))
        r = _resolver(stub).resolve_first("机器人怎么样")
        assert len(stub.calls) == 1
        assert r.source == "llm"
        assert r.intent == WebIntent.SECTOR_ANALYSIS

    def test_sector_combo_high_confidence_skips_llm(self):
        # "行业名+板块"相邻组合消除对象歧义 → 规则直接高置信，不打扰 LLM
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        r = _resolver(stub).resolve_first("半导体板块怎么样")
        assert stub.calls == []
        assert r.source == "rule"
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85

    def test_bare_unknown_code_skips_llm(self):
        # 裸存疑代码：tag 全识别（unknown_us_code 也是识别产物）+ 0.8 →
        # 免复核直达，unverified 透传执行端实查（与"分析下SOFI"同构）
        stub = _StubLLMAdapter(content=_llm_json("stock_analysis", 0.8, stock_code="AAPL"))
        r = _resolver(stub).resolve_first("ZZZZ")
        assert stub.calls == []
        assert r.source == "rule"
        assert r.unverified_codes == ["ZZZZ"]
        assert not r.needs_confirmation


# =========================================================================
# 确认消费 — pending confirm_stock 的响应解析
# =========================================================================


def _ali_session() -> Dict[str, Any]:
    return {
        PENDING_ACTIONS_KEY: [_pending_ali()],
        LAST_INTENT_KEY: "stock_analysis",
        RECENT_STOCKS_KEY: [],
    }


class TestConfirmationConsumption:
    @staticmethod
    def _pending_pingan() -> Dict[str, Any]:
        # "平安"歧义：平安银行 / 中国平安 双候选（同市场，全名可区分）
        return {
            "action": "confirm_stock",
            "intent": "stock_analysis",
            "name": "平安",
            "candidates": [
                {"code": "000001", "name": "平安银行", "market": "a"},
                {"code": "601318", "name": "中国平安", "market": "a"},
            ],
            "original_request": "分析平安",
        }

    def test_market_word_us_choice(self):
        # 聚合项输入：市场词把 hk/us 双候选收窄到唯一
        r = _resolver().resolve_first("美股", _ali_session())
        assert r.source == "confirmation"
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["BABA"]
        assert r.confidence == 0.9

    def test_intent_inherited_from_pending(self):
        # 确认消费继承 pending 记录的原意图：行情查询的歧义消解后仍是查询
        session = _ali_session()
        session[PENDING_ACTIONS_KEY][0]["intent"] = "quote_lookup"
        r = _resolver().resolve_first("港股", session)
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert _codes(r) == ["HK09988"]

    def test_pending_without_intent_falls_back(self):
        # 形状防御：pending 缺 intent 字段 → 回退 stock_analysis
        session = _ali_session()
        del session[PENDING_ACTIONS_KEY][0]["intent"]
        r = _resolver().resolve_first("港股", session)
        assert r.intent == WebIntent.STOCK_ANALYSIS

    def test_pending_bogus_intent_falls_back(self):
        session = _ali_session()
        session[PENDING_ACTIONS_KEY][0]["intent"] = "bogus_intent"
        r = _resolver().resolve_first("港股", session)
        assert r.intent == WebIntent.STOCK_ANALYSIS

    def test_name_plus_market_reply_picks_market(self):
        # 复述组名 + 聚合项（"阿里巴巴港股"）：市场词先于名称子串裁决，
        # 名称子串命中全部同组候选时不构成证据
        r = _resolver().resolve_first("阿里巴巴港股", _ali_session())
        assert r.source == "confirmation"
        assert _codes(r) == ["HK09988"]

    def test_full_name_exact_choice(self):
        # 同市场多候选无市场聚合项：候选全名全等命中
        r = _resolver().resolve_first("平安银行", self._pending_pingan_session())
        assert r.source == "confirmation"
        assert _codes(r) == ["000001"]

    def test_ambiguous_name_substring_not_consumed(self):
        # 歧义名本身（"平安"）命中全部候选 = 不消解：绝不取第一个，
        # 整轮按新消息解析（用户必须给出聚合项）
        r = _resolver().resolve_first("平安", self._pending_pingan_session())
        assert r.source == "rule"

    @staticmethod
    def _pending_pingan_session() -> Dict[str, Any]:
        return {PENDING_ACTIONS_KEY: [TestConfirmationConsumption._pending_pingan()]}

    def test_bare_digit_code_choice(self):
        # 裸 5 位数字按 HK 口径规范（09988 → HK09988）命中候选
        r = _resolver().resolve_first("09988", _ali_session())
        assert r.source == "confirmation"
        assert _codes(r) == ["HK09988"]

    def test_named_code_choice(self):
        # 显式代码形态解析为确定实体且在候选内 → 消费
        r = _resolver().resolve_first("HK09988", _ali_session())
        assert r.source == "confirmation"
        assert _codes(r) == ["HK09988"]

    def test_declined(self):
        r = _resolver().resolve_first("不用了", _ali_session())
        assert r.source == "confirmation"
        assert r.intent == WebIntent.GENERAL_CHAT
        assert not r.needs_confirmation

    @pytest.mark.parametrize("text", ["算了", "取消", "不需要", "算了，不用了"])
    def test_decline_variants(self, text):
        r = _resolver().resolve_first(text, _ali_session())
        assert r.intent == WebIntent.GENERAL_CHAT
        assert r.source == "confirmation"

    def test_new_topic_drops_pending(self):
        # 确定实体不在候选中 → 新话题：正常解析（pending 由 apply 收敛）
        r = _resolver().resolve_first("分析600519", _ali_session())
        assert r.source == "rule"
        assert _codes(r) == ["600519"]

    @pytest.mark.parametrize("text", ["1", "2", "5", "第一个", "二"])
    def test_numeric_reply_not_consumed(self, text):
        # 纯序号/中文序数不是合法消歧输入：零消解按新消息解析
        # （裸数字代码形态除外，见 bare_digit_code_choice）
        r = _resolver().resolve_first(text, _ali_session())
        assert r.source == "rule"
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_vague_reply_not_consumed(self):
        r = _resolver().resolve_first("嗯嗯", _ali_session())
        assert r.source == "rule"
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_malformed_pending_ignored(self):
        session = {PENDING_ACTIONS_KEY: [{"action": "confirm_stock"}]}
        r = _resolver().resolve_first("港股", session_context=session)
        assert r.source == "rule"  # 无候选可确认，直接正常解析

    def test_pending_non_list_shape_ignored(self):
        session = {PENDING_ACTIONS_KEY: "not-a-list"}
        r = _resolver().resolve_first("分析600519", session_context=session)
        assert _codes(r) == ["600519"]

    def test_market_word_hk_choice(self):
        r = _resolver().resolve_first("港股", _ali_session())
        assert r.source == "confirmation"
        assert _codes(r) == ["HK09988"]


# =========================================================================
# 会话簿记 — recent_stocks / pending_actions / last_intent
# =========================================================================


class TestSessionBookkeeping:
    def test_write_via_update_context_when_available(self):
        # ConversationSession 形态（带 update_context 簿记入口）优先走它，
        # 不绕过宿主直接改 dict（可能带持久化/脏标记钩子）
        class _Session:
            def __init__(self) -> None:
                self.context: Dict[str, Any] = {}
                self.writes: List[Any] = []

            def update_context(self, key: str, value: Any) -> None:
                self.writes.append((key, value))
                self.context[key] = value

        session = _Session()
        apply_resolution_to_session(session, WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.9, stocks=[Stock("600519", "贵州茅台", "a")]))
        written_keys = [k for k, _v in session.writes]
        # 组合入口 = apply_pending（消费即结算）→ apply_outcome（recent/last/投影）
        assert written_keys == [PENDING_ACTIONS_KEY, RECENT_STOCKS_KEY, LAST_INTENT_KEY,
                                LAST_RESOLUTIONS_KEY]
        assert session.context[LAST_INTENT_KEY] == "stock_analysis"

    def test_recent_stocks_head_insert(self):
        session: Dict[str, Any] = {}
        apply_resolution_to_session(session, WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.9, stocks=[Stock("600519", "贵州茅台", "a")]))
        apply_resolution_to_session(session, WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.9, stocks=[Stock("000858", "五粮液", "a")]))
        assert session[RECENT_STOCKS_KEY] == ["000858", "600519"]

    def test_recent_stocks_dedup_moves_to_head(self):
        session = {RECENT_STOCKS_KEY: ["600519", "000858"]}
        apply_resolution_to_session(session, WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.9, stocks=[Stock("600519", "贵州茅台", "a")]))
        assert session[RECENT_STOCKS_KEY] == ["600519", "000858"]

    def test_recent_stocks_truncated(self):
        session = {RECENT_STOCKS_KEY: [f"60000{i}" for i in range(MAX_RECENT_STOCKS)]}
        apply_resolution_to_session(session, WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.9, stocks=[Stock("300750", "宁德时代", "a")]))
        recent = session[RECENT_STOCKS_KEY]
        assert recent[0] == "300750"
        assert len(recent) == MAX_RECENT_STOCKS

    def test_candidates_not_written_to_recent(self):
        # 未确认的歧义候选不污染继承上下文
        session: Dict[str, Any] = {}
        r = _resolver().resolve_first("阿里巴巴")
        apply_resolution_to_session(session, r)
        assert session[RECENT_STOCKS_KEY] == []

    def test_confirmation_writes_pending(self):
        session: Dict[str, Any] = {}
        r = _resolver().resolve_first("分析阿里巴巴")
        apply_resolution_to_session(session, r)
        pending = session[PENDING_ACTIONS_KEY]
        assert len(pending) == 1
        assert pending[0]["action"] == "confirm_stock"

    def test_stale_pending_cleared_by_apply(self):
        # 生命周期收敛：旧 pending 存在，本轮无确认产出 → apply 后清空
        session = _ali_session()
        r = _resolver().resolve_first("分析600519", session_context=session)
        apply_resolution_to_session(session, r)
        assert session[PENDING_ACTIONS_KEY] == []

    def test_consumed_round_clears_pending(self):
        session = _ali_session()
        r = _resolver().resolve_first("港股", session_context=session)
        apply_resolution_to_session(session, r)
        assert session[PENDING_ACTIONS_KEY] == []
        assert session[RECENT_STOCKS_KEY] == ["HK09988"]
        assert session[LAST_INTENT_KEY] == "stock_analysis"

    def test_apply_writes_pending_from_non_first_task(self):
        # 多意图消息的歧义短路组结构全程保留：兄弟任务（茅台 quote）随
        # 确认任务一起返回并写入 last_resolutions（即跨轮暂存器）；apply
        # 写入确认任务的 pending，消费结算后兄弟任务经 ③ 拼接恢复——
        # 确认循环不断裂、请求不丢
        tasks = _resolver().resolve("查一下茅台股价，然后分析阿里巴巴")
        flat = _flat(tasks)
        confirming = next(t for t in flat if t.needs_confirmation)
        sibling = next(t for t in flat if not t.needs_confirmation)
        assert sibling.intent == WebIntent.QUOTE_LOOKUP
        assert _codes(sibling) == ["600519"]
        session: Dict[str, Any] = {}
        apply_resolution_to_session(session, tasks)
        assert session[PENDING_ACTIONS_KEY] == [confirming.pending_action]
        # 用户下一轮聚合项回复被正确消费，兄弟任务随 ③ 拼接恢复
        after = _resolver().resolve("港股", session)
        # ③ 拼接保 last_resolution 子消息序：兄弟（quote 茅台）在前
        assert [(t.intent, _codes(t)) for t in _flat(after)] == [
            (WebIntent.QUOTE_LOOKUP, ["600519"]),
            (WebIntent.STOCK_ANALYSIS, ["HK09988"]),
        ]

    def test_apply_pending_scans_all_positions(self):
        # apply_pending 扫描全部任务，不假设 _flat(tasks)[0]——防御
        # resolve 之外的列表构造方（SSE 集成层）
        plain = WebIntentResolution(WebIntent.QUOTE_LOOKUP, 0.9,
                                    stocks=[Stock("600519", "贵州茅台", "a")])
        confirming = WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.85, needs_confirmation=True,
            pending_action={"action": "confirm_stock", "groups": []},
        )
        session: Dict[str, Any] = {}
        apply_pending(session, [plain, confirming])
        assert session[PENDING_ACTIONS_KEY] == [confirming.pending_action]

    def test_short_circuit_round_skips_outcome(self):
        # 时机拆分：短路轮整链未执行——recent_stocks / last_intent 不得
        # 记录未执行的任务（茅台 quote 未跑、意图未跑）
        session = {RECENT_STOCKS_KEY: ["000858"], LAST_INTENT_KEY: "quote_lookup"}
        tasks = _resolver().resolve("查一下茅台股价，然后分析阿里巴巴")
        apply_resolution_to_session(session, tasks)
        assert session[PENDING_ACTIONS_KEY]  # pending 正常写入
        assert session[RECENT_STOCKS_KEY] == ["000858"]  # 未执行的茅台不入列
        assert session[LAST_INTENT_KEY] == "quote_lookup"  # 保持上一执行轮

    def test_apply_pending_and_outcome_split_entries(self):
        # 拆分入口各自独立可用：apply_pending 只动 pending，
        # apply_outcome 只动 recent/last
        session: Dict[str, Any] = {}
        apply_pending(session, WebIntentResolution(WebIntent.GENERAL_CHAT, 0.9))
        assert session[PENDING_ACTIONS_KEY] == []
        assert RECENT_STOCKS_KEY not in session
        assert LAST_INTENT_KEY not in session
        apply_outcome(session, WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.9, stocks=[Stock("600519", "贵州茅台", "a")]))
        assert session[RECENT_STOCKS_KEY] == ["600519"]
        assert session[LAST_INTENT_KEY] == "stock_analysis"

    def test_last_intent_recorded(self):
        session: Dict[str, Any] = {}
        apply_resolution_to_session(session, WebIntentResolution(
            WebIntent.PORTFOLIO_ANALYSIS, 0.85))
        assert session[LAST_INTENT_KEY] == "portfolio_analysis"

    def test_last_resolutions_recorded(self):
        # 持续性会话保留上一轮（已执行）任务列表投影：下一轮 resolve 的
        # context 可读取，含意图/标的/板块/来源子消息
        session: Dict[str, Any] = {}
        apply_resolution_to_session(session, [
            WebIntentResolution(
                WebIntent.STOCK_ANALYSIS, 0.85,
                stocks=[Stock("600519", "贵州茅台", "a")],
                source_request="分析贵州茅台"),
            WebIntentResolution(
                WebIntent.SECTOR_ANALYSIS, 0.85, sectors=["白酒"]),
        ])
        recorded = [t for g in session[LAST_RESOLUTIONS_KEY] for t in g]
        assert [t["intent"] for t in recorded] == ["stock_analysis", "sector_analysis"]
        assert recorded[0]["stocks"] == [{"code": "600519", "name": "贵州茅台", "market": "a"}]
        assert recorded[0]["source_request"] == "分析贵州茅台"
        assert recorded[1]["sectors"] == ["白酒"]

    def test_short_circuit_round_writes_last_resolutions(self):
        # 短路轮也写 last_resolutions（第五步确认消费的数据源：上轮歧义
        # 任务的 pending_action 必须跨轮可见）；last_intent 仍只记执行轮
        session: Dict[str, Any] = {}
        tasks = _resolver().resolve("查一下茅台股价，然后分析阿里巴巴")
        apply_resolution_to_session(session, tasks)
        recorded = [t for g in session[LAST_RESOLUTIONS_KEY] for t in g]
        # 组结构保留：兄弟任务与确认任务都在（last_resolution 即暂存器）
        assert [t["intent"] for t in recorded] == ["quote_lookup", "stock_analysis"]
        assert recorded[1]["needs_confirmation"] is True
        assert recorded[1]["pending_action"]["groups"][0]["name"] == "阿里巴巴"
        # last_intent 仍只记执行轮：短路轮不写（键缺失或保持旧值）
        assert session.get(LAST_INTENT_KEY) != "quote_lookup"

    def test_conversation_session_object(self):
        # ConversationSession 形态（.context dict）同样可写
        session = _FakeSession()
        apply_resolution_to_session(session, WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.9, stocks=[Stock("600519", "贵州茅台", "a")]))
        assert session.context[RECENT_STOCKS_KEY] == ["600519"]

    def test_none_session_noop(self):
        apply_resolution_to_session(None, WebIntentResolution(WebIntent.GENERAL_CHAT, 0.5))

    def test_clear_pending_actions(self):
        session = _ali_session()
        clear_pending_actions(session)
        assert session[PENDING_ACTIONS_KEY] == []

    def test_clear_pending_actions_on_object(self):
        session = _FakeSession(context=_ali_session())
        clear_pending_actions(session)
        assert session.context[PENDING_ACTIONS_KEY] == []


# =========================================================================
# 上下文继承 — inherited_stock_code / 追问继承（上下文继承机制）
# =========================================================================


class TestContextInheritance:
    def test_recent_stock_inherited(self):
        session = {RECENT_STOCKS_KEY: ["600519"]}
        r = _resolver().resolve_first("你好", session_context=session)
        assert r.inherited_stock_code == "600519"
        assert r.primary_stock_code == "600519"

    def test_current_stock_code_wins(self):
        # 锁定股置顶：inherited_stock_code 即继承主码
        session = {RECENT_STOCKS_KEY: ["600519"]}
        r = _resolver().resolve_first("你好", session_context=session, request_context={"current_stock_code": "300750"})
        assert r.inherited_stock_code == "300750"
        assert r.primary_stock_code == "300750"

    def test_followup_inherits_executing_last_intent(self):
        # 追问不占意图名额：继承上轮执行类意图（source="context"）
        session = {
            LAST_INTENT_KEY: "stock_analysis",
            RECENT_STOCKS_KEY: ["600519"],
        }
        r = _resolver().resolve_first("继续", session_context=session)
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.source == "context"
        assert r.confidence == 0.75
        assert r.inherited_stock_code == "600519"
        assert not r.needs_confirmation

    def test_followup_after_portfolio(self):
        session = {LAST_INTENT_KEY: "portfolio_analysis"}
        r = _resolver().resolve_first("接着看看", session_context=session)
        assert r.intent == WebIntent.PORTFOLIO_ANALYSIS

    def test_followup_needs_executing_last_intent(self):
        # 上轮闲聊：无产物可追问 → 不继承，按无信号解析
        session = {LAST_INTENT_KEY: "general_chat"}
        r = _resolver().resolve_first("继续", session_context=session)
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_followup_requires_session(self):
        r = _resolver().resolve_first("继续")
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_followup_with_new_entity_is_research(self):
        # followup 词 + 新股票指称 → 新的个股分析，不是追问
        session = {LAST_INTENT_KEY: "stock_analysis"}
        r = _resolver().resolve_first("继续分析600519", session_context=session)
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["600519"]


# =========================================================================
# 意图边界矩阵 — 三判别测试的易混淆对照（web_intent_types docstring 基线）
# =========================================================================


class TestIntentBoundaryMatrix:
    """每对 query 只差一两个字、意图完全不同；与 web_intent_types 模块
    docstring 的"易混淆对照"表互为基线——改边界定义必须两侧同步。"""

    @pytest.mark.parametrize("text,expected", [
        # T2 深度：报数据 vs 给观点（同一实体）
        ("茅台多少钱", WebIntent.QUOTE_LOOKUP),
        ("茅台估值贵不贵", WebIntent.STOCK_ANALYSIS),
        ("茅台的市盈率是多少", WebIntent.QUOTE_LOOKUP),
        ("茅台今天为什么大跌", WebIntent.STOCK_ANALYSIS),
        ("茅台今天跌了多少", WebIntent.QUOTE_LOOKUP),
        ("茅台能买吗", WebIntent.STOCK_ANALYSIS),
        # T2 数据词 vs 知识（查数据源 vs 纯 LLM 知识）
        ("什么是市盈率", WebIntent.GENERAL_CHAT),
        # T1 个性化：答案是否依赖用户账户数据
        ("茅台基本面怎么样", WebIntent.STOCK_ANALYSIS),
        ("我的茅台还该拿着吗", WebIntent.PORTFOLIO_ANALYSIS),
        ("我的持仓今天怎么样", WebIntent.PORTFOLIO_ANALYSIS),
        # T2+T3：集合对象的报数 vs 结构判断
        ("白酒板块今天涨了多少", WebIntent.QUOTE_LOOKUP),
        ("白酒板块怎么看", WebIntent.SECTOR_ANALYSIS),
        ("白酒板块今天领跌的是谁", WebIntent.QUOTE_LOOKUP),
        ("白酒板块哪只最有潜力", WebIntent.SECTOR_ANALYSIS),
        ("今天大盘怎么样", WebIntent.QUOTE_LOOKUP),
        ("大盘怎么看", WebIntent.SECTOR_ANALYSIS),
        # T2 深度内战：比较数字 vs 比较观点
        ("分析000858和300750谁涨得多", WebIntent.QUOTE_LOOKUP),
        ("分析000858和300750哪个好", WebIntent.STOCK_ANALYSIS),
        # T2 词序优先级：强分析词 > 数据词 > 泛动作词
        ("分析茅台的股价走势", WebIntent.STOCK_ANALYSIS),
        ("帮我查一下茅台的股价", WebIntent.QUOTE_LOOKUP),
    ])
    def test_boundary_pair(self, text, expected):
        r = _resolver().resolve_first(text)
        assert r.intent == expected, (
            f"边界矩阵失守：{text!r} 期望 {expected.value}，实际 {r.intent.value}"
        )


# =========================================================================
# extend 词池交叉验证 — 子串歧义词的防盲撕回归
# =========================================================================


class TestExtendPoolCrossValidation:
    """extend 池的子串歧义词只在 Step 6 DFS 全片段覆盖时命中：被更长
    常见词包含的场景（出现在/查一下午/他们）整段放弃交 LLM，绝不盲撕
    出错误语义的 token（"宁可不做，不可做错"）。"""

    def test_superstring_not_blind_torn(self):
        # 现在 ⊂ "出现在"："出现在龙虎榜"不得撕出时间词（无信号交 LLM）
        r = _resolver().resolve_first("出现在龙虎榜")
        assert r.intent == WebIntent.GENERAL_CHAT
        assert r.stocks == []

    def test_afternoon_query_not_torn_by_cha(self):
        # 查一下 ⊂ "查一下午"："查一下午的大盘"不撕出取数词；大盘经
        # Step 4 命中，意图仍为行情查询
        r = _resolver().resolve_first("查一下午的大盘")
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert r.stocks == []

    def test_pronoun_superstring_no_followup(self):
        # 他 ⊂ "他们"："他们说的对吗"不判追问指代，不继承上轮意图
        session = {LAST_INTENT_KEY: "stock_analysis"}
        r = _resolver().resolve_first("他们说的对吗", session_context=session)
        assert r.source != "context"
        assert r.intent == WebIntent.GENERAL_CHAT


# =========================================================================
# ASCII 全词匹配 — 连续英文字母段不切割
# =========================================================================


class TestAsciiWholeWordMatching:
    """ASCII 关键词一律全词匹配（词边界 = 空格/标点/CJK 邻接）：
    "researching" 内不撕出 research、"markets" 内不撕出 market——Step 4/5
    正则带词边界断言，与 Step 6 整词精确查表语义一致。"""

    def test_clean_pattern_whole_word_only(self):
        from src.agent.web_intent_types import _CLEAN_KEYWORDS_PATTERN as pat
        assert pat.search("research") is not None
        assert pat.search("researching") is None
        assert pat.search("analyze") is not None
        assert pat.search("analyzed") is None

    def test_market_pattern_whole_word_only(self):
        from src.agent.web_intent_tokenizer import _MARKET_TOKEN_PATTERN as pat
        assert pat.search("market") is not None
        assert pat.search("markets") is None
        # CJK 邻接不算连续英文：夹在中文里的 market 正常命中
        assert pat.search("美股market怎么样") is not None

    def test_pipeline_english_run_untouched(self):
        # 全管道：连续英文字母段整体保持未打标签（交 LLM），不产生关键词 tag
        _, tokens = _preprocess_text("researching")
        assert [(t.text, t.tag) for t in tokens] == [("researching", "")]


# =========================================================================
# WebIntentResolution 数据契约
# =========================================================================


class TestResolutionDataclass:
    def test_stock_string_normalized(self):
        r = WebIntentResolution(WebIntent.STOCK_ANALYSIS, 0.9, stocks=["600519"])
        assert r.stocks == [Stock(code="600519")]

    def test_stock_dict_normalized(self):
        # stocks 的 dict 载荷与 candidates 同口径归一为 Stock：两列表
        # 共享同一 _coerce_stock map，dict 分支显式转换、缺 code/空 code/
        # None 条目剔除——不存在"stocks 字典原样透传"路径（评审探针钉子）
        r = WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.9,
            stocks=[{"code": "600519", "name": "贵州茅台", "market": "a"},
                    {"name": "缺code"}, {"code": ""}, None, "000858"],
        )
        assert r.stocks == [
            Stock("600519", "贵州茅台", "a"), Stock(code="000858")]
        assert r.primary_stock_code == ""  # 双标的（比较场景）按契约返回空串
        single = WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.9, stocks=[{"code": "600519"}])
        assert single.primary_stock_code == "600519"

    def test_candidate_dict_normalized(self):
        r = WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.9,
            candidates=[{"code": "BABA", "name": "阿里巴巴", "market": "us"}],
        )
        assert r.candidates == [Stock("BABA", "阿里巴巴", "us")]

    def test_primary_stock_code_single(self):
        r = _resolver().resolve_first("分析600519")
        assert r.primary_stock_code == "600519"

    def test_primary_stock_code_multi_empty(self):
        r = _resolver().resolve_first("对比000858和300750")
        assert r.primary_stock_code == ""

    def test_primary_stock_code_inherited(self):
        session = {RECENT_STOCKS_KEY: ["600519"]}
        r = _resolver().resolve_first("你好", session_context=session)
        assert r.primary_stock_code == "600519"


# =========================================================================
# SSE 事件构建
# =========================================================================


class TestInternalHelpers:
    # ---- _parse_llm_payload ----

    def test_parse_payload_plain_json(self):
        assert _parse_llm_payload('{"intent": "general_chat", "confidence": 0.5}')

    def test_parse_payload_code_fence(self):
        assert _parse_llm_payload('```json\n{"intent": "general_chat"}\n```')

    def test_parse_payload_surrounding_text(self):
        assert _parse_llm_payload('好的，结果如下：{"intent": "general_chat"} 以上。')

    def test_parse_payload_invalid(self):
        assert _parse_llm_payload("not json") is None
        assert _parse_llm_payload("") is None
        assert _parse_llm_payload('{"intent": "bogus"}') is None
        assert _parse_llm_payload('["array"]') is None

    # ---- _disambiguate_by_market ----

    def test_disambiguate_no_market(self):
        cands = [Stock("HK09988", "阿里巴巴", "hk"), Stock("BABA", "阿里巴巴", "us")]
        picked, display = _disambiguate_by_market(cands, [])
        assert picked is None
        assert display == cands

    def test_disambiguate_single_hit(self):
        cands = [Stock("HK09988", "阿里巴巴", "hk"), Stock("BABA", "阿里巴巴", "us")]
        picked, display = _disambiguate_by_market(cands, [Market.HK])
        assert picked == [Stock("HK09988", "阿里巴巴", "hk")]
        assert display == cands  # 展示仍带全量候选

    def test_disambiguate_contradictory_market_keeps_all(self):
        cands = [Stock("HK09988", "阿里巴巴", "hk"), Stock("BABA", "阿里巴巴", "us")]
        picked, display = _disambiguate_by_market(cands, [Market.A])
        assert picked is None
        assert display == cands  # 市场词与候选矛盾：保守保留全部

    # ---- _dedup_stocks ----

    def test_dedup_stocks(self):
        stocks = [Stock("600519", "贵州茅台", "a"), Stock("600519", "茅台", "a")]
        assert _dedup_stocks(stocks) == [Stock("600519", "贵州茅台", "a")]

    # ---- _session_context ----

    def test_session_context_shapes(self):
        assert _session_context(None) == {}
        assert _session_context({"k": 1}) == {"k": 1}
        assert _session_context(_FakeSession(context={"k": 2})) == {"k": 2}
        assert _session_context(object()) == {}

    # ---- _token_facts 直测 ----

    def test_token_facts_unique_name_promoted(self):
        from src.agent.web_intent_resolver import _token_facts
        _, tokens = _preprocess_text("分析贵州茅台")
        f = _token_facts(_identify_stock_codes(tokens))
        assert [s.code for s in f["stocks"]] == ["600519"]
        assert f["ambiguous"] == []
        assert f["code_entity"] is False  # 名称路径不算显式代码

    def test_token_facts_sector_combo(self):
        # "行业名+泛称"相邻组合（Step 6 DFS 自然产出）→ 板块高置信事实
        from src.agent.web_intent_resolver import _token_facts
        _, tokens = _preprocess_text("建筑板块怎么样")
        f = _token_facts(_identify_stock_codes(tokens))
        assert f["sector_combo"] is True
        assert not f["has_entity"] and bool(
            {"sector", "sector_name"} & f["tags"])

    def test_token_facts_bare_sector_no_combo(self):
        # 裸行业名无泛称后缀：不构成 combo（对象歧义未消）
        from src.agent.web_intent_resolver import _token_facts
        _, tokens = _preprocess_text("半导体怎么样")
        f = _token_facts(_identify_stock_codes(tokens))
        assert f["sector_combo"] is False
        assert not f["has_entity"] and bool(
            {"sector", "sector_name"} & f["tags"])

    def test_token_facts_ambiguous_group(self):
        from src.agent.web_intent_resolver import _token_facts
        _, tokens = _preprocess_text("分析阿里巴巴")
        f = _token_facts(_identify_stock_codes(tokens))
        assert f["stocks"] == []
        assert len(f["ambiguous"]) == 1
        name, group = f["ambiguous"][0]
        assert name == "阿里巴巴"
        assert {s.code for s in group} == {"HK09988", "BABA"}

    def test_token_facts_wrong_and_unknown_codes(self):
        from src.agent.web_intent_resolver import _token_facts
        _, tokens = _preprocess_text("分析SH999999")
        f = _token_facts(_identify_stock_codes(tokens))
        assert f["wrong_codes"] == ["SH999999"]

        _, tokens = _preprocess_text("分析ZZZZ")
        f = _token_facts(_identify_stock_codes(tokens))
        # 美股精选库未命中 → 未验证透传（非全量库无判定把握）
        assert f["unverified_codes"] == ["ZZZZ"]
        assert f["unknown_codes"] == []

    def test_token_facts_numeric_promotion(self):
        from src.agent.web_intent_resolver import _token_facts
        _, tokens = _preprocess_text("300750怎么样")
        f = _token_facts(_identify_stock_codes(tokens))
        assert [s.code for s in f["stocks"]] == ["300750"]


# =========================================================================
# 实战场景回归 — 候选间比较重建 / 纯市场词重问 / 继承守卫 / 载荷健壮性
# =========================================================================


class TestConfirmationHardening:
    @staticmethod
    def _pending_pingan() -> Dict[str, Any]:
        # "平安"歧义：平安银行 / 中国平安 双候选（同市场，名称可区分）
        return {
            "action": "confirm_stock",
            "intent": "stock_analysis",
            "name": "平安",
            "candidates": [
                {"code": "000001", "name": "平安银行", "market": "a"},
                {"code": "601318", "name": "中国平安", "market": "a"},
            ],
            "original_request": "分析平安",
        }

    def test_candidate_comparison_rebuilt_by_reclassify(self):
        # 确认窗口中点名两候选 + 比较词 = 新的多股比较请求：竞争锚点
        # 拦截后按完整语义重新分类，不静默确认第一只、不丢比较语义
        session = {PENDING_ACTIONS_KEY: [self._pending_pingan()]}
        r = _resolver().resolve_first("平安银行和中国平安哪个好", session)
        assert r.source == "rule"
        assert not r.needs_confirmation
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["000001", "601318"]

    def test_comparison_with_third_stock_not_rebuilt(self):
        # 混入候选外第三标的（SOFI）的比较请求：不重建、不静默确认第一
        # 只，交正常流程重新分类（存疑代码转 LLM 兜底）
        session = {PENDING_ACTIONS_KEY: [self._pending_pingan()]}
        r = _resolver().resolve_first("平安银行和中国平安和SOFI哪个好", session)
        assert r.source == "rule"
        assert r.reason != "candidate_comparison"
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["000001", "601318"]

    def test_research_anchor_reply_not_consumed(self):
        # 带研究词的回复是新请求（竞争意图锚点）：即便点名候选也不作
        # 确认消费，交正常流程按完整语义分类
        session = {PENDING_ACTIONS_KEY: [self._pending_pingan()]}
        tasks = _flat(_resolver().resolve("再分析下平安银行最近走势", session))
        assert [(t.source, _codes(t)) for t in tasks] == [
            ("confirmation", ["000001"]), ("rule", ["000001"])]
        assert all(t.intent == WebIntent.STOCK_ANALYSIS for t in tasks)
        assert not any(t.needs_confirmation for t in tasks)

    def test_resolved_stocks_merged_on_confirmation(self):
        # 确认消费合并 pending.resolved_stocks：原请求的另一端不丢失
        pending = _pending_ali()
        pending["resolved_stocks"] = [
            {"code": "00700", "name": "腾讯控股", "market": "hk"},
        ]
        r = _resolver().resolve_first("港股", {PENDING_ACTIONS_KEY: [pending]})
        assert r.source == "confirmation"
        assert _codes(r) == ["HK09988", "00700"]

    def test_ambiguous_pending_carries_resolved_stocks(self):
        # 规则歧义确认的 pending_action 携带已解析实体
        r = _resolver().resolve_first("对比茅台和阿里巴巴")
        assert r.needs_confirmation
        pa = r.pending_action
        assert pa["resolved_stocks"][0]["code"] == "600519"
        assert {c["code"] for c in pa["groups"][0]["candidates"]} == {"HK09988", "BABA"}

    def test_entity_with_wrong_code_keeps_both(self):
        # 合法实体 + 非法代码并存：实体保留，非法代码进 unresolved 确认
        r = _resolver().resolve_first("分析600519和SH999999")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["600519"]
        assert r.unresolved_names == ["SH999999"]
        assert r.needs_confirmation
        assert r.reason == "stock_unresolved"


class TestFollowupInheritGuard:
    def test_research_with_unknown_subject_not_inherited(self):
        # "再分析一下你好股份"：名称库外 token 很可能是研究对象，
        # 不得误判为对上轮股票的追问（宁可低置信也不做错）
        session = {LAST_INTENT_KEY: "stock_analysis"}
        r = _resolver().resolve_first("再分析一下你好股份", session)
        assert r.source == "rule"
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_unknown_code_subject_not_inherited(self):
        # "再分析下SOFI"：存疑代码是带 tag 的未消化信号，不得继承上轮
        session = {LAST_INTENT_KEY: "stock_analysis"}
        r = _resolver().resolve_first("再分析下SOFI", session)
        assert r.source == "rule"
        assert r.intent == WebIntent.STOCK_ANALYSIS  # 存疑代码路径

    def test_bare_number_subject_not_inherited(self):
        # "再分析下09988"：5 位裸数字不提升为实体，但也不得当作追问继承
        session = {LAST_INTENT_KEY: "quote_lookup"}
        r = _resolver().resolve_first("再分析下09988", session)
        assert r.source == "rule"
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_clean_research_followup_still_inherits(self):
        # 全部 token 可识别的研究追问不受守卫影响，正常继承
        session = {LAST_INTENT_KEY: "stock_analysis"}
        r = _resolver().resolve_first("继续分析一下", session)
        assert r.source == "context"
        assert r.intent == WebIntent.STOCK_ANALYSIS


class TestLlmPayloadHardening:
    def test_fence_with_trailing_text(self):
        # code fence 后夹带含 } 的解释文字：深度提取不被末个 } 带偏
        raw = '好的：```json\n{"intent": "quote_lookup", "confidence": 0.9}\n``` 以上就是结果 }'
        payload = _parse_llm_payload(raw)
        assert payload is not None
        assert payload["intent"] == "quote_lookup"

    def test_bom_prefix(self):
        assert _parse_llm_payload('\ufeff{"intent": "general_chat"}') is not None

    def test_label_normalization(self):
        # 大小写/连字符/尾部标点先规范化再校验
        payload = _parse_llm_payload('{"intent": "Stock-Analysis。", "confidence": 0.9}')
        assert payload["intent"] == "stock_analysis"

    def test_market_variants_normalized(self):
        payload = _parse_llm_payload('{"intent": "general_chat", "market": "港股"}')
        assert payload["market"] == Market.HK
        payload = _parse_llm_payload('{"intent": "general_chat", "market": "USA"}')
        assert payload["market"] == Market.US

    def test_braces_inside_string_not_confused(self):
        # JSON 字符串值里的 } 不终止对象提取
        raw = '结果 {"intent": "general_chat", "note": "含}花括号"} 完毕'
        payload = _parse_llm_payload(raw)
        assert payload is not None
        assert payload["intent"] == "general_chat"

    def test_invalid_intent_rejected(self):
        assert _parse_llm_payload('{"intent": "bogus"}') is None

    @staticmethod
    def _merge(payload):
        rule = WebIntentResolution(intent=WebIntent.GENERAL_CHAT, confidence=0.5)
        return _merge_llm_result(rule, payload, {})

    def test_nan_confidence_treated_as_missing(self):
        # NaN 击穿一切比较（nan < 0.6 恒 False）会伪装成高置信跳过确认
        r = self._merge({"intent": "general_chat", "confidence": float("nan")})
        assert r.confidence == 0.5

    def test_llm_market_disambiguates_rule_candidates(self):
        # LLM 市场推断消解规则歧义候选："美股"语境下双候选收敛到 BABA。
        # 触发路径：词池外语气词留下空 tag 残段 → 非全识别豁免 → 兜底
        stub = _StubLLMAdapter(
            content='{"intent": "stock_analysis", "confidence": 0.9, "market": "us"}'
        )
        r = _resolver(stub).resolve_first("阿里巴巴哈哈哈")
        assert r.source == "llm"
        assert _codes(r) == ["BABA"]
        assert r.candidates == []
        assert not r.needs_confirmation

    def test_llm_market_pick_then_extra_code_rejected(self):
        # 市场推断消解唯一歧义组清空 candidates 后，组外库内代码
        # （600519，原文未提及）仍须拒收——闸门判据是输入属性快照，
        # 不随市场消解收缩
        stub = _StubLLMAdapter(content=(
            '{"intent": "stock_analysis", "confidence": 0.9, '
            '"market": "us", "stock_codes": ["600519"]}'))
        r = _resolver(stub).resolve_first("阿里巴巴哈哈哈")
        assert r.source == "llm"
        assert _codes(r) == ["BABA"]
        assert not r.needs_confirmation

    def test_multi_mentions_via_stock_codes(self):
        # 多标的提及（多股比较）：stock_codes 列表逐个过三道闸门
        stub = _StubLLMAdapter(content=_llm_json(
            "stock_analysis", 0.9, stock_codes=["AAPL", "600519"]))
        r = _resolver(stub).resolve_first("对比下这两只")
        assert r.source == "llm"
        assert _codes(r) == ["AAPL", "600519"]
        assert not r.needs_confirmation

    def test_adapter_unavailable_skips_llm(self):
        # is_available 为假（未配 key 等）时不发调用，规则结果直接落确认
        stub = _StubLLMAdapter(
            content='{"intent": "general_chat", "confidence": 0.9}'
        )
        stub.is_available = False
        r = _resolver(stub).resolve_first("阿里巴巴怎么样")
        assert stub.calls == []
        assert r.needs_confirmation


# =========================================================================
# 惰性 LLM adapter — 构造零成本，首次兜底才从 config 构建
# =========================================================================


class TestLazyLlmAdapter:
    """构造函数契约：config 进、adapter 不动；构建点被替换为本地桩，
    单元内不触真 litellm provider 栈。"""

    @staticmethod
    def _patch_builder(monkeypatch, builder) -> None:
        import src.agent.llm_adapter as llm_mod

        monkeypatch.setattr(llm_mod, "LLMToolAdapter", builder)

    def test_config_only_defers_build_until_first_fallback(self, monkeypatch):
        marker = object()
        built = []

        def fake_builder(config):
            built.append(config)
            return marker

        self._patch_builder(monkeypatch, fake_builder)
        config = object()
        resolver = WebIntentResolver(config)
        assert resolver._llm_adapter is None  # 构造完成 ≠ LLM 已初始化
        assert resolver._ensure_llm_adapter() is marker
        assert built == [config]
        assert resolver._ensure_llm_adapter() is marker  # 幂等复用
        assert len(built) == 1

    def test_injected_adapter_skips_lazy_build(self, monkeypatch):
        def unexpected(_config):
            raise AssertionError("injected adapter must bypass lazy build")

        self._patch_builder(monkeypatch, unexpected)
        stub = _StubLLMAdapter()
        resolver = WebIntentResolver(llm_adapter=stub)
        assert resolver._ensure_llm_adapter() is stub

    def test_init_failure_disables_fallback_permanently(self, monkeypatch):
        calls = []

        def failing_builder(_config):
            calls.append(1)
            raise RuntimeError("no api key")

        self._patch_builder(monkeypatch, failing_builder)
        resolver = WebIntentResolver(object())
        assert resolver._ensure_llm_adapter() is None
        assert resolver._ensure_llm_adapter() is None  # 失败后不再重试
        assert len(calls) == 1

    def test_no_config_no_adapter_stays_disabled(self, monkeypatch):
        def unexpected(_config):
            raise AssertionError("no-config must not reach builder")

        self._patch_builder(monkeypatch, unexpected)
        assert WebIntentResolver()._ensure_llm_adapter() is None


# =========================================================================
# 兼容 re-export — resolver 自身消费的符号经其入口可取（tokenizer 侧由
# 文件顶部 import 钉住：_preprocess_text/_identify_stock_codes）
# =========================================================================


class TestReExports:
    def test_types_symbols(self):
        from src.agent.web_intent_resolver import (  # noqa: F401
            ALL_WEB_INTENTS,
            CONFIRMATION_CONFIDENCE_THRESHOLD,
            LLM_FOLLOWUP_LABEL,
            Token as _Token,
            WebIntentResolution as _Resolution,
        )
        assert "stock_analysis" in ALL_WEB_INTENTS
        assert LLM_FOLLOWUP_LABEL == "followup"
        assert LLM_FOLLOWUP_LABEL not in ALL_WEB_INTENTS  # 伪标签不入意图枚举
        assert CONFIRMATION_CONFIDENCE_THRESHOLD == 0.6

    def test_service_symbols(self):
        from src.services.name_to_code_resolver import (
            is_known_stock_name,
            lookup_stock_by_code,
            resolver_name_to_code_list,
        )
        assert lookup_stock_by_code("600519") is not None
        assert is_known_stock_name("贵州茅台")
        assert [s.code for s in resolver_name_to_code_list("酒鬼酒")] == ["000799"]


# =========================================================================
# 板块槽位填充 — sector_analysis / 板块报数的分析对象（与 stocks 同构）
# =========================================================================


class TestSectorSlotFilling:
    def test_combo_sector_analysis_fills_slot(self):
        # "行业名+泛称"相邻组合：高置信直达，板块名入槽
        r = _resolver().resolve_first("分析一下白酒板块")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85
        assert r.sectors == ["白酒"]

    def test_combo_sector_quote_fills_slot(self):
        # 板块报数（quote_lookup）同样需要分析对象：槽位照填
        r = _resolver().resolve_first("白酒板块今天涨了多少")
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert r.sectors == ["白酒"]

    def test_bare_sector_name_fills_slot(self):
        # 裸行业名精确命中词池：0.85 直达免确认，槽位填充
        r = _resolver().resolve_first("半导体")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85
        assert r.needs_confirmation is False
        assert r.sectors == ["半导体"]

    def test_sector_n_stock_fills_slot(self):
        # 行业名兼股票全名（"机器人"）：板块语境下按板块名入槽
        r = _resolver().resolve_first("机器人板块怎么样")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.sectors == ["机器人"]
        assert r.stocks == []

    def test_multiple_sectors_kept_in_order(self):
        r = _resolver().resolve_first("白酒和半导体板块怎么样")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.sectors == ["白酒", "半导体"]

    def test_repeated_sector_deduped(self):
        r = _resolver().resolve_first("白酒白酒板块")
        assert r.sectors == ["白酒"]

    def test_broad_market_uses_market_name_slot(self):
        # 泛市场无具名板块：槽位填市场名（无限定为"大盘"，范围语义
        # 同时由 market 字段表达）
        r = _resolver().resolve_first("大盘怎么看")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.sectors == ["大盘"]

    def test_stock_intent_has_empty_sector_slot(self):
        r = _resolver().resolve_first("分析茅台")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.sectors == []
        assert _codes(r) == ["600519"]

    def test_out_of_pool_sector_before_generic_suffix(self):
        # 词池外行业名 + 泛称后缀（"CPO板块"）：回溯提取为板块名，代码
        # 身份解除，combo 高置信直达（不经存疑代码分支/LLM）
        r = _resolver().resolve_first("查一下现在CPO板块的情况")
        assert r.source == "rule"
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert r.confidence == 0.85
        assert r.sectors == ["CPO"]
        assert not r.needs_confirmation

    def test_view_phrase_rule_direct_after_pool_extension(self):
        # "看下"在 extend 词池（action_quote）：整段 DFS 全覆盖成功，
        # 双板块组合（人工智能+赛道 / AI+板块）规则 0.85 直达（交 LLM
        # 会压置信至 0.75 并引入板块名改写风险）；sectors 按原文顺序
        # 保序填充
        stub = _StubLLMAdapter(content=json.dumps({
            "intent": "sector_analysis", "confidence": 0.9,
            "sectors": ["人工智能", "AI"],
        }, ensure_ascii=False))
        r = WebIntentResolver(llm_adapter=stub).resolve_first("看下现在人工智能赛道和AI板块的走势")
        assert stub.calls == []
        assert r.source == "rule"
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85
        assert r.sectors == ["人工智能", "AI"]

    def test_stock_code_before_suffix_not_backtracked(self):
        # 显式股票代码 + 泛称（"600519板块成分"）保持股票语义：代码即
        # 标的，不回溯提取为板块名
        r = _resolver().resolve_first("分析600519板块成分")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.sectors == []
        assert _codes(r) == ["600519"]

    def test_numeric_and_short_prefix_not_backtracked(self):
        # 纯数字（"3板块"）与单字段（"看板块"）不提取为板块名
        from src.agent.web_intent_resolver import _token_facts
        f = _token_facts(_identify_stock_codes(_preprocess_text("聊聊3板块")[1]))
        assert f["sectors"] == []
        f2 = _token_facts(_identify_stock_codes(_preprocess_text("看板块怎么样")[1]))
        assert f2["sectors"] == []

    def test_hk_unverified_code_passed_through(self):
        # hk 非全量库存疑（未命中 ≠ 非法）：确认机制不适用——系统对
        # 无把握判定的指称不做确认，未验证代码透传执行端实查
        r = _resolver().resolve_first("hk66373和酒鬼酒对比分析")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["000799"]
        assert r.unverified_codes == ["hk66373"]
        assert not r.needs_confirmation

    def test_hk_unverified_before_entity_variant(self):
        r = _resolver().resolve_first("酒鬼酒和hk66373对比")
        assert r.unverified_codes == ["hk66373"]
        assert not r.needs_confirmation

    def test_aside_unknown_code_passthrough(self):
        # "顺便"切分出附带任务：规则判 stock（与主任务 quote 意图不同，
        # 不折叠）→ 两任务各自透传；附带 unverified 不影响主任务直达
        rs = _resolver().resolve("茅台多少钱顺便看下SOFI")
        assert len(_flat(rs)) == 2
        assert _flat(rs)[0].intent == WebIntent.QUOTE_LOOKUP
        assert _codes(_flat(rs)[0]) == ["600519"]
        assert not any(t.needs_confirmation for t in _flat(rs))
        assert _flat(rs)[1].unverified_codes == ["SOFI"]

    def test_broad_market_word_is_context_not_subject(self):
        # 泛市场词（行情）是 clean 池独立存活，板块 extend 词靠 DFS 全
        # 覆盖——"XX板块的行情"里泛市场信号更易存活。泛市场是兜底对象
        # 而非竞争对象：具名板块在场时落穿板块分支（不被 ['大盘'] 劫持）
        r = _resolver().resolve_first("白酒板块今天行情怎么样")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.sectors == ["白酒"]

    def test_unverified_code_with_market_context_routes_to_llm(self):
        # 未验证代码 + 泛市场语境共存（"PEEK板块的整体行情"，PEEK 未
        # 收录）：板块 tag 随 DFS 失败陪葬，规则无法判定板块 vs 个股
        # ——低置信交 LLM 读原文裁定，sectors 经原文闸门、unverified
        # 保留。（CPO 在 clean 词池：同型消息规则层直达 sectors=['CPO']）
        stub = _StubLLMAdapter(content=json.dumps({
            "intent": "sector_analysis", "confidence": 0.9,
            "sectors": ["PEEK"],
        }, ensure_ascii=False))
        r = WebIntentResolver(llm_adapter=stub).resolve_first("分析PEEK板块的整体行情")
        assert r.source == "llm"
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.sectors == ["PEEK"]
        assert r.unverified_codes == ["PEEK"]

    def test_index_product_combo_direct(self):
        # combo 白名单含指数主题：指数 + ETF 泛称组合（指数 ETF 是
        # 最大品类）高置信直达，指数文本入 sectors 槽位；裸指数（无
        # 泛称）仍走分支 4 的 index_subjects 路径，两者不冲突
        r = _resolver().resolve_first("沪深300ETF")
        assert r.source == "rule"
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85
        assert r.sectors == ["沪深300"]
        # 双指数 ETF 组合比较：主题保序直达
        r2 = _resolver().resolve_first("中证500ETF和沪深300ETF对比")
        assert r2.sectors == ["中证500", "沪深300"]
        assert r2.confidence == 0.85
        # 裸指数：仍走报数路径，槽位为指数原文
        r3 = _resolver().resolve_first("沪深300怎么样")
        assert r3.intent == WebIntent.QUOTE_LOOKUP
        assert r3.sectors == ["沪深300"]

    def test_product_suffix_forms_combo(self):
        # ETF/LOF/REITs 是产品类泛称后缀（"银行ETF"与"银行板块"结构
        # 同构）：相邻组合高置信直达（ASCII 泛称经关键词放行，不被
        # Step 3 当美股 ticker 抠走）
        r = _resolver().resolve_first("综合分析下银行ETF")
        assert r.source == "rule"
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85
        assert r.sectors == ["银行"]
        assert r.unverified_codes == []
        # 双主题 ETF 组合比较：多板块保序直达
        r2 = _resolver().resolve_first("军工ETF和银行ETF对比")
        assert r2.sectors == ["军工", "银行"]
        assert r2.confidence == 0.85
        # 裸泛称（无主题名）：泛指 ETF 产品，低置信交 LLM/确认
        r3 = _resolver().resolve_first("哪些ETF好")
        assert r3.sectors == []
        assert r3.confidence == 0.5

    def test_abbrev_concept_in_clean_pool_survives_dfs_failure(self):
        # 英文缩写概念在 clean 池独立存活（词边界全词匹配 + Step 3
        # ticker 放行）：泛称词随 DFS 失败陪葬时缩写不连带丢失
        r = _resolver().resolve_first("分析CPO板块的整体行情")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.sectors == ["CPO"]
        r2 = _resolver().resolve_first("分析AI行情")
        assert r2.sectors == ["AI"]

    def test_pure_broad_market_still_direct(self):
        # 纯泛市场（无任何具体对象残渣）：兜底对象成立，直达不变
        r = _resolver().resolve_first("今天大盘怎么样")
        assert r.source == "rule"
        assert r.sectors == ["大盘"]

    def test_broad_market_sectors_unified_slot(self):
        # 泛市场/指数的 sectors 统一槽位：指数用原文、纯泛市场用市场名
        # （无限定"大盘"）——执行端与具名板块同构，只消费 sectors
        r = _resolver().resolve_first("分析昨天大A的整体行情")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.sectors == ["A股"]
        assert _resolver().resolve_first("今天大盘怎么样").sectors == ["大盘"]
        assert _resolver().resolve_first("港股行情怎么样").sectors == ["港股"]
        assert _resolver().resolve_first("研究下上证指数").sectors == ["上证"]
        assert _resolver().resolve_first("沪深300怎么样").sectors == ["沪深300"]

    def test_action_intent_upgrades_broad_market_to_sector(self):
        # 泛市场语境的明确动作意图（分析/看看等 request）升级板块分析
        # ——"分析昨天大A的整体行情"要结构论述而非一个点位；纯疑问
        # （无动作词）"今天大盘怎么样"仍默认报数
        r = _resolver().resolve_first("分析昨天大A的整体行情")
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85
        assert _resolver().resolve_first("看看大盘行情").intent == WebIntent.SECTOR_ANALYSIS
        assert _resolver().resolve_first("今天大盘怎么样").intent == WebIntent.QUOTE_LOOKUP
        assert _resolver().resolve_first("研究下上证指数").intent == WebIntent.SECTOR_ANALYSIS

    def test_deep_verb_keeps_stock_default(self):
        # 个股语境动作词：裸个股默认分析不变
        r = _resolver().resolve_first("分析茅台")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.confidence == 0.85

    def test_coordination_unknown_name_routed_to_llm(self):
        # 并列未知名称（库中不存在）：整段 DFS 失败 → LLM 兜底裁定，
        # 茅台查库采信、西藏建工无库可验由 LLM 语境判断
        stub = _StubLLMAdapter(content=json.dumps({
            "intent": "stock_analysis", "confidence": 0.9,
            "stock_code": "600519",
        }, ensure_ascii=False))
        r = WebIntentResolver(llm_adapter=stub).resolve_first("分析茅台和西藏建工")
        assert r.source == "llm"
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["600519"]

    def test_probe_extracts_multiple_entities_per_segment(self):
        # 段内多股并列的两个实体都提取
        r = _resolver().resolve_first("分析茅台和五粮液")
        assert _codes(r) == ["600519", "000858"]
        assert not r.needs_confirmation

    def test_out_of_pool_word_routed_to_llm(self):
        # "近况"不在词池 → 整段 DFS 放弃 → LLM 兜底；"情况"在词池
        # 时 DFS 全覆盖成功，取数词与实体共现高置信直达
        stub = _StubLLMAdapter(content=json.dumps({
            "intent": "quote_lookup", "confidence": 0.9,
            "stock_code": "600519",
        }, ensure_ascii=False))
        r = WebIntentResolver(llm_adapter=stub).resolve_first("查一下现在茅台的近况")
        assert r.source == "llm"
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert _codes(r) == ["600519"]
        r2 = _resolver().resolve_first("查一下现在茅台的情况")
        assert r2.source == "rule"
        assert r2.intent == WebIntent.QUOTE_LOOKUP
        assert r2.confidence == 0.85

    def test_entity_probe_full_name_in_mixed_segment(self):
        r = _resolver().resolve_first("聊聊三花智控呗")
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["002050"]

    def test_entity_probe_ambiguous_two_candidates(self):
        # 双候选（平安银行/中国平安）保留歧义确认语义，不静默选一
        r = _resolver().resolve_first("平安的情况")
        assert _candidate_codes(r) == ["000001", "601318"]
        assert r.needs_confirmation is True
        assert r.reason == "ambiguous_stock_name"

    def test_entity_probe_generic_word_gated_by_candidates(self):
        # 泛词"中国"命中 5 候选（中国平安/中石化/…整族前缀）：歧义组
        # 候选数上限统一挡住，不触发无意义确认
        r = _resolver().resolve_first("中国的情况怎么样")
        assert r.intent == WebIntent.GENERAL_CHAT
        assert r.stocks == [] and r.candidates == []

    def test_unseen_concept_routed_to_llm(self):
        # 从未收录的概念名（词池外）+ 泛称后缀：整段 DFS 失败 → 规则
        # 低置信交 LLM 兜底，LLM 板块名经原文闸门填充槽位
        stub = _StubLLMAdapter(content=json.dumps({
            "intent": "sector_analysis", "confidence": 0.9,
            "sectors": ["固态电池"],
        }, ensure_ascii=False))
        r = WebIntentResolver(llm_adapter=stub).resolve_first("固态电池概念有哪些股票")
        assert r.source == "llm"
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.sectors == ["固态电池"]

    def test_trading_action_word_keeps_sector_tokens(self):
        # 交易决策词（抄底等）在池 → DFS 全覆盖成功，规则直达且槽位
        # 填充；词池外表述（"该止盈"的"该"不在池）整段失败交 LLM 兜底
        r = _resolver().resolve_first("白酒板块现在能抄底吗")
        assert r.source == "rule"
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85
        assert r.sectors == ["白酒"]
        stub = _StubLLMAdapter(content=json.dumps({
            "intent": "sector_analysis", "confidence": 0.9,
            "sectors": ["白酒"],
        }, ensure_ascii=False))
        r2 = WebIntentResolver(llm_adapter=stub).resolve_first("白酒板块该止盈了吗")
        assert r2.source == "llm"
        assert r2.sectors == ["白酒"]

    def test_llm_unresolved_name_channel(self):
        # LLM schema 的 unresolved_names 通道：LLM 判定意图但标的无法
        # 解析（"你好股份"生造名）时原文报告，经原文闸门后走既有
        # stock_unresolved 确认——空标的执行任务是无效产出
        stub = _StubLLMAdapter(content=json.dumps({
            "intent": "stock_analysis", "confidence": 0.9,
            "unresolved_names": ["你好股份", "编造的名称"],
        }, ensure_ascii=False))
        rs = WebIntentResolver(llm_adapter=stub).resolve("分析一下你好股份")
        r = _flat(rs)[0]
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.unresolved_names == ["你好股份"]  # 编造名被原文闸门拒
        assert r.needs_confirmation is True
        assert r.reason == "stock_unresolved"

    def test_llm_sectors_filled_with_text_gate(self):
        # 规则侧未提取到板块（长尾措辞整段 DFS 失败）时，LLM 返回的
        # 板块名经"原文出现"闸门合入：命中的保留，编造的丢弃
        stub = _StubLLMAdapter(content=json.dumps({
            "intent": "sector_analysis", "confidence": 0.9,
            "sectors": ["固态电池", "编造的板块"],
        }, ensure_ascii=False))
        r = WebIntentResolver(llm_adapter=stub).resolve_first("吧固态电池呢")
        assert r.source == "llm"
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.sectors == ["固态电池"]

    def test_llm_sectors_merge_with_rule_base(self):
        # 无泛称后缀的裸概念（规则无从提取）由 LLM 返回并过原文闸门填充；
        # 编造板块被闸门丢弃
        stub = _StubLLMAdapter(content=json.dumps({
            "intent": "sector_analysis", "confidence": 0.9,
            "sectors": ["固态电池", "编造板块"],
        }, ensure_ascii=False))
        r = WebIntentResolver(llm_adapter=stub).resolve_first("固态电池和CPO呢")
        assert r.source == "llm"
        # 规则基底（CPO 在词池）优先，LLM 补充原文出现的新板块
        assert r.sectors == ["CPO", "固态电池"]

    def test_combo_phrase_bypasses_llm(self):
        # "AI板块呢"类裸板块短语：combo 已消除对象歧义，规则 0.85 直达
        # 不进 LLM（进 LLM 会降置信至 0.75 并引入板块名重复入槽）
        r = _resolver().resolve_first("AI板块呢")
        assert r.source == "rule"
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.confidence == 0.85
        assert r.sectors == ["AI"]

    def test_llm_sector_suffix_variant_deduped(self):
        # LLM 返回"半导体板块"（带泛称后缀）与规则基底"半导体"是同一
        # 板块的两种表述：按去后缀键去重，不重复入槽；编造项仍被原文
        # 闸门丢弃
        stub = _StubLLMAdapter(content=json.dumps({
            "intent": "sector_analysis", "confidence": 0.9,
            "sectors": ["机器人板块", "编造板块"],
        }, ensure_ascii=False))
        r = WebIntentResolver(llm_adapter=stub).resolve_first("机器人呢")
        assert r.source == "llm"
        assert r.sectors == ["机器人"]

    def test_llm_override_keeps_rule_sectors(self):
        # 裸行业名走 LLM 复核改判时，规则侧提取的板块名不丢
        stub = _StubLLMAdapter(
            content='{"intent": "sector_analysis", "confidence": 0.9}',
        )
        r = WebIntentResolver(llm_adapter=stub).resolve_first("机器人")
        assert r.source == "llm"
        assert r.intent == WebIntent.SECTOR_ANALYSIS
        assert r.sectors == ["机器人"]
        assert not r.needs_confirmation

# =========================================================================
# =========================================================================
# 多意图 — 任务序列（子消息序列保序 + 同句并存分解）
# =========================================================================


class TestTaskSplitting:
    def test_heterogeneous_subjects_split_to_tasks(self):
        # 同句并存（无标点）：个股主体 + 板块对象分解为任务序列；
        # 顶层字段即首任务形态（板块对象归位到板块任务自身）
        rs = _resolver().resolve("分析茅台和白酒板块")
        assert [t.intent for t in _flat(rs)] == [
            WebIntent.STOCK_ANALYSIS, WebIntent.SECTOR_ANALYSIS,
        ]
        assert _codes(_flat(rs)[0]) == ["600519"]
        assert _flat(rs)[1].sectors == ["白酒"]

    def test_etf_subject_split_to_tasks(self):
        rs = _resolver().resolve("茅台和银行ETF对比")
        assert [t.intent for t in _flat(rs)] == [
            WebIntent.STOCK_ANALYSIS, WebIntent.SECTOR_ANALYSIS,
        ]
        assert _flat(rs)[1].sectors == ["银行"]

    def test_pure_subject_single_task(self):
        # 无并存不分解：单任务消息（resolve 返回单元素列表）
        rs = _resolver().resolve("分析茅台")
        assert len(_flat(rs)) == 1
        assert _flat(rs)[0].sectors == []
        assert len(_resolver().resolve("白酒板块怎么样")) == 1

    def test_three_intents_with_sequence(self):
        # 子消息序列 + 消息内并存叠加：按用户表达顺序保序，顶层投影
        # 为首个任务（sector＝用户说的第一件事）
        rs = _resolver().resolve("分析下CPO和AI板块，然后再分析茅台走势和我的持仓")
        assert _flat(rs)[0].intent == WebIntent.SECTOR_ANALYSIS
        assert [t.intent for t in _flat(rs)] == [
            WebIntent.SECTOR_ANALYSIS,
            WebIntent.STOCK_ANALYSIS,
            WebIntent.PORTFOLIO_ANALYSIS,
        ]
        assert _flat(rs)[0].sectors == ["CPO", "AI"]
        assert _codes(_flat(rs)[1]) == ["600519"]

    def test_pure_stock_portfolio_task(self):
        rs = _resolver().resolve("茅台走势和我的持仓")
        assert [t.intent for t in _flat(rs)] == [
            WebIntent.STOCK_ANALYSIS, WebIntent.PORTFOLIO_ANALYSIS,
        ]

    def test_portfolio_dominant_keeps_sector_task(self):
        rs = _resolver().resolve("我的持仓和白酒板块怎么样")
        assert _flat(rs)[0].intent == WebIntent.PORTFOLIO_ANALYSIS
        assert [t.intent for t in _flat(rs)] == [
            WebIntent.PORTFOLIO_ANALYSIS, WebIntent.SECTOR_ANALYSIS,
        ]
        assert _flat(rs)[1].sectors == ["白酒"]

    def test_institutional_holdings_single_task(self):
        # 领属限定："分析茅台的持仓"是机构持仓研究维度，不分解组合任务
        assert len(_resolver().resolve("分析茅台的持仓")) == 1

    def test_group_level_source_request(self):
        # 两级上下文：任务级 original_request=该子消息文本，组级
        # source_request=歧义组的来源子消息，与分歧一一对应
        # ——不折叠，每个确认任务各自携带自己的组
        rs = _resolver().resolve("阿里的走势怎么样，平安呢")
        tasks = _flat(rs)
        assert len(tasks) == 2
        pa0, pa1 = tasks[0].pending_action, tasks[1].pending_action
        assert pa0["original_request"] == "阿里的走势怎么样"
        assert pa1["original_request"] == "平安呢"
        assert [g["name"] for g in pa0["groups"]] == ["阿里"]
        assert [g["name"] for g in pa1["groups"]] == ["平安"]
        assert pa0["groups"][0]["source_request"] == "阿里的走势怎么样"
        assert pa1["groups"][0]["source_request"] == "平安呢"
        # 一条回复两组独立消解（last_resolutions 携带全部确认任务；
        # 会话经 apply 双键同步构造——pending_actions 是消费闸门的
        # 存活权威，单键手写会话不构成合法消费源）
        session: Dict[str, Any] = {}
        apply_resolution_to_session(session, rs)
        rs2 = _resolver().resolve("美股 平安银行", session)
        assert not any(t.needs_confirmation for t in _flat(rs2))

    def test_aggregated_confirmation_full_cycle(self):
        # 双歧义全聚合：一次 pending.groups 两组，用户逐组给聚合项解除
        # → tasks 汇总执行；只解除一组时未解组再次 pending（已解组暂存
        # confirmed）
        r = _resolver()
        session: Dict[str, Any] = {}
        rs = r.resolve("阿里巴巴多少钱，平安呢")
        apply_resolution_to_session(session, rs)
        confirmings = [t for t in _flat(rs) if t.needs_confirmation]
        # 两个确认任务各自独立成组，组随任务保留
        assert [g["name"] for c in confirmings
                for g in c.pending_action["groups"]] == ["阿里巴巴", "平安"]
        # 只解除阿里组（"美股"→BABA）：平安确认任务保留，阿里任务落位执行
        rs2 = r.resolve("美股", session)
        apply_resolution_to_session(session, rs2)
        p2 = next(t for t in _flat(rs2) if t.needs_confirmation).pending_action
        assert [g["name"] for g in p2["groups"]] == ["平安"]
        assert (WebIntent.QUOTE_LOOKUP, ["BABA"]) in [
            (t.intent, _codes(t)) for t in _flat(rs2)]
        # 解除平安组（"中国平安"全等命中）：全解除，任务按上轮序执行
        rs3 = r.resolve("中国平安", session)
        assert not any(t.needs_confirmation for t in _flat(rs3))
        assert [(t.intent, _codes(t)) for t in _flat(rs3)] == [
            (WebIntent.QUOTE_LOOKUP, ["BABA"]),
            (WebIntent.STOCK_ANALYSIS, ["601318"]),
        ]

    def test_chained_confirmation_decline_cancels_all(self):
        # 拒绝取消全链：全部待确认组作废，闲聊产出无确认无任务
        r = _resolver()
        rs = r.resolve("阿里巴巴多少钱，平安呢")
        rs2 = r.resolve("算了", {PENDING_ACTIONS_KEY: [_flat(rs)[0].pending_action]})
        assert _flat(rs2)[0].intent == WebIntent.GENERAL_CHAT
        assert not any(t.needs_confirmation for t in _flat(rs2))
        assert len(_flat(rs2)) == 1

    def test_single_confirmation_no_chain(self):
        # 单歧义：确认消费直接落位（pending 无链式附加结构）
        r = _resolver()
        res = r.resolve_first("阿里巴巴多少钱")
        assert "queued" not in res.pending_action
        consumed = r.resolve_first("美股", {PENDING_ACTIONS_KEY: [res.pending_action]})
        assert not consumed.needs_confirmation
        # "美股" 收窄到组内唯一的 us 候选（BABA）
        us_codes = [c["code"] for g in res.pending_action["groups"]
                    for c in g["candidates"] if c["market"] == "us"]
        assert _codes(consumed) == us_codes

    def test_confirmation_suspends_sibling_sector_task(self):
        # 确认短路期间分解出的板块任务是确认任务的兄弟任务：组结构保留
        # ——兄弟任务随确认任务一起返回/入 last_resolutions（即跨轮暂存
        # 器，不散装 sectors），结算后随 ③ 拼接恢复
        rs = _resolver().resolve("阿里巴巴和白酒板块分析")
        flat = _flat(rs)
        confirming = next(t for t in flat if t.needs_confirmation)
        sibling = next(t for t in flat if t.intent == WebIntent.SECTOR_ANALYSIS)
        assert sibling.sectors == ["白酒"]
        session: Dict[str, Any] = {}
        apply_resolution_to_session(session, rs)
        rs2 = _resolver().resolve("港股", session)
        assert not any(t.needs_confirmation for t in _flat(rs2))
        # ③ 列表合并保原序：主任务（消解后就位）在前、分解兄弟在后
        assert [(t.intent, t.sectors) for t in _flat(rs2)] == [
            (WebIntent.STOCK_ANALYSIS, []),
            (WebIntent.SECTOR_ANALYSIS, ["白酒"]),
        ]

    def test_wrong_code_confirmation_keeps_sector_sibling(self):
        # 单子消息内 wrong-code 确认与板块对象并存：医药板块作为兄弟
        # 任务随确认短路暂存，不被早返回分支吞掉
        rs = _resolver().resolve("分析医药板块和SH6005190")
        flat = _flat(rs)
        confirming = next(t for t in flat if t.needs_confirmation)
        assert confirming.intent == WebIntent.STOCK_ANALYSIS
        assert confirming.reason == "stock_unresolved"
        assert confirming.unresolved_names == ["SH6005190"]
        sector = next(t for t in flat if t.intent == WebIntent.SECTOR_ANALYSIS)
        assert sector.sectors == ["医药"]
        assert sector.stocks == []
        assert not sector.needs_confirmation

    def test_sequential_tasks_ordered(self):
        # 顺序形态：子消息按用户表达顺序，链式保序
        rs = _resolver().resolve("先看看白酒板块，然后分析贵州茅台")
        assert _flat(rs)[0].intent == WebIntent.SECTOR_ANALYSIS
        assert [t.intent for t in _flat(rs)] == [
            WebIntent.SECTOR_ANALYSIS, WebIntent.STOCK_ANALYSIS,
        ]
        assert _codes(_flat(rs)[1]) == ["600519"]

    def test_parallel_objects_not_split(self):
        # 并列对象（和/与）不切分：属于同一任务的两个标的
        rs = _resolver().resolve("茅台和五粮液对比")
        assert len(_flat(rs)) == 1
        assert len(_flat(rs)[0].stocks) == 2

    def test_quoted_code_not_split(self):
        # 英文句点是代码组成（600519.HK）不是任务边界
        sub = _split_sub_messages("分析600519.HK")
        assert len(sub) == 1

    def test_word_internal_connective_not_split(self):
        # X然复合词 + 后/悔 拼出"然后"子串：连接词切口要求"然后"是
        # token 文本起点，词内"然后"（"居|然后市"＝居然+后市）无从
        # 触发，词界不撕裂——词界完整性是"居然智家"简称提取与"后市"
        # 关键词的共同前提
        assert _sub_texts("居然后市趋势如何") == ["居然后市趋势如何"]
        assert _sub_texts("仍然后悔没买茅台") == ["仍然后悔没买茅台"]

    def test_conflicting_cut_vetoed_without_sitting_good_boundaries(self):
        # 切口独立判定：词内"然后"不构成切口，同句的逗号边界照常下刀
        assert _sub_texts("居然后市如何，分析茅台") == [
            "居然后市如何",
            "分析茅台",
        ]

    def test_connective_token_starts_new_sub_message(self):
        # 连接词切分的下刀条件是"然后"为 token 文本起点："一下"在 clean
        # 词池参与分词，"分析茅台然后看一下常山的价格"的"然后"被撕出为
        # 独立 token → 两个任务各归各组；切分只分组不改写元素（子消息
        # token 按序拼接 == 原文）。连接词真正埋在无标签 unknown_token
        # 内部无从下刀的契约由 test_probe_two_connective_cuts_in_one_
        # unknown_token 覆盖。
        subs = _split_sub_messages("分析茅台然后看一下常山的价格")
        assert ["".join(t.text for t in sub) for sub in subs] == [
            "分析茅台", "然后看一下常山的价格",
        ]
        assert [t.text for t in subs[0]] == ["分析", "茅台"]
        assert "".join(t.text for t in subs[1]) == "然后看一下常山的价格"

    def test_juran_abbreviation_resolved_end_to_end(self):
        # 端到端：词界保住后"居然"经子串匹配解析为"居然智家"（生产
        # 全量库的一对一简称），强研究信号（后市/趋势/如何）+ 实体 →
        # stock_analysis@0.85。mock 库不含该股，按 tokenizer 测试惯例
        # 原地注册并失效名称缓存（autouse fixture 负责还原）
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["000785"] = "居然智家"
        resolver_mod._names_cache[:] = [None, None, None]
        rs = _resolver().resolve("居然后市趋势如何")
        assert _flat(rs)[0].intent == WebIntent.STOCK_ANALYSIS
        assert _codes(_flat(rs)[0]) == ["000785"]
        assert not _flat(rs)[0].needs_confirmation


class TestAggregationFixRegressions:
    """聚合/消歧的回归用例（兄弟任务保留、按任务独立确认、继承码
    透传、多轮链路卫生）。"""

    def test_cross_sub_message_sibling_preserved(self):
        # 跨子消息的兄弟任务（板块）不静默丢失——组
        # 结构保留，随确认任务入 last_resolutions，结算后随 ③ 拼接恢复
        rs = _resolver().resolve("分析阿里巴巴，然后看看白酒板块")
        flat = _flat(rs)
        confirming = next(t for t in flat if t.needs_confirmation)
        sibling = next(t for t in flat if t.intent == WebIntent.SECTOR_ANALYSIS)
        assert sibling.sectors == ["白酒"]
        session: Dict[str, Any] = {}
        apply_resolution_to_session(session, rs)
        rs2 = _resolver().resolve("港股", session)
        assert not any(t.needs_confirmation for t in _flat(rs2))
        # ③ 列表合并保原序：主任务（消解后就位）在前、兄弟板块在后
        assert [(t.intent, _codes(t), t.sectors) for t in _flat(rs2)] == [
            (WebIntent.STOCK_ANALYSIS, ["HK09988"], []),
            (WebIntent.SECTOR_ANALYSIS, [], ["白酒"]),
        ]

    def test_low_confidence_confirmation_independent_tasks(self):
        # 确认按任务独立成立：裸板块任务 0.5 转 low_confidence 确认，
        # 不受同意图邻居影响
        rs = _resolver().resolve("分析白酒板块，再看看机器人")
        tasks = _flat(rs)
        assert len(tasks) == 2
        assert all(t.intent == WebIntent.SECTOR_ANALYSIS for t in tasks)
        assert tasks[0].sectors == ["白酒"] and tasks[0].confidence == 0.85
        assert not tasks[0].needs_confirmation
        assert tasks[1].sectors == ["机器人"] and tasks[1].confidence < 0.6
        assert tasks[1].needs_confirmation
        assert tasks[1].reason == "low_confidence"

    def test_unresolved_confirmation_kept(self):
        # stock_unresolved 确认与 unresolved_names 按任务独立保留——
        # 非法指称（SH999999）不静默消失
        rs = _resolver().resolve("先看看五粮液，然后分析600519和SH999999")
        tasks = _flat(rs)
        assert len(tasks) == 2
        assert _codes(tasks[0]) == ["000858"] and not tasks[0].needs_confirmation
        assert tasks[1].intent == WebIntent.STOCK_ANALYSIS
        assert tasks[1].needs_confirmation
        assert tasks[1].reason == "stock_unresolved"
        assert tasks[1].unresolved_names == ["SH999999"]
        assert _codes(tasks[1]) == ["600519"]

    def test_split_sibling_keeps_inherited_code(self):
        # 同句分解的兄弟任务透传继承代码（历史标的
        # 的持久化通道是会话键 recent_stocks，任务仅携带标量视图）
        session = {RECENT_STOCKS_KEY: ["300750"]}
        rs = _resolver().resolve(
            "港股阿里巴巴和白酒板块分析", session_context=session)
        assert [t.intent for t in _flat(rs)] == [
            WebIntent.STOCK_ANALYSIS, WebIntent.SECTOR_ANALYSIS,
        ]
        assert _codes(_flat(rs)[0]) == ["HK09988"]
        for t in _flat(rs):
            assert t.inherited_stock_code == "300750"
        assert _flat(rs)[0].primary_stock_code == "HK09988"

    def test_requeue_whitelist_no_duplicate_confirmed(self):
        # 部分消解的 pending 重建：resolved_stocks 并进 confirmed 后
        # 不随行——多轮链路不重复累积
        pending = _pending_ali()
        pending["groups"] = [
            {"name": "阿里巴巴", "candidates": pending["candidates"],
             "source_request": "分析阿里巴巴"},
            {"name": "平安", "candidates": [
                {"code": "000001", "name": "平安银行", "market": "a"},
                {"code": "601318", "name": "中国平安", "market": "a"},
            ], "source_request": "分析平安"},
        ]
        pending["resolved_stocks"] = [
            {"code": "00700", "name": "腾讯控股", "market": "hk"},
        ]
        r = _resolver()
        # 第一轮只解阿里组：确认任务自身 stocks 合并随行实体（腾讯 +
        # 消解 HK09988），confirmed 只记本轮消解——多轮不重复累积
        rs1 = r.resolve("港股", {PENDING_ACTIONS_KEY: [pending]})
        requeue = _flat(rs1)[0].pending_action
        assert sorted(_codes(_flat(rs1)[0])) == ["00700", "HK09988"]
        assert [s["code"] for c in requeue["confirmed"] for s in c["stocks"]] == ["HK09988"]
        # 第二轮解平安组：confirmed 无重复，全解结算包含全部实体
        rs2 = r.resolve("中国平安", {PENDING_ACTIONS_KEY: [requeue]})
        assert not any(t.needs_confirmation for t in _flat(rs2))
        settled = [s.code for t in _flat(rs2) for s in t.stocks]
        assert sorted(settled) == ["00700", "601318", "HK09988"]

    def test_multi_group_single_reply_resolves_all(self):
        # 一条回复携带多组聚合项：各组独立判定，一次全解；两组 intent
        # 相同（stock_analysis）时结算聚合为单任务双标的
        pending = _pending_ali()
        pending["groups"] = [
            {"name": "阿里巴巴", "candidates": pending["candidates"],
             "source_request": "分析阿里巴巴"},
            {"name": "平安", "candidates": [
                {"code": "000001", "name": "平安银行", "market": "a"},
                {"code": "601318", "name": "中国平安", "market": "a"},
            ], "source_request": "分析平安"},
        ]
        rs = _resolver().resolve("美股 平安银行", {PENDING_ACTIONS_KEY: [pending]})
        assert not any(t.needs_confirmation for t in _flat(rs))
        assert [(t.intent, _codes(t)) for t in _flat(rs)] == [
            (WebIntent.STOCK_ANALYSIS, ["BABA", "000001"]),
        ]


# =========================================================================
# last_resolution 消费链 — 用户实战样例：full_resolution = _consume_
# confirmations(last_resolution, full_resolution) 的取数与三步稳定性
# =========================================================================


class TestLastResolutionConsumption:
    """验证第五步数据链：上一轮 resolve → apply 写入 last_resolutions
    （二维组结构）→ 下一轮 resolve 的 last_resolution 正确读取 →
    _consume_confirmations 严格三步（就地消歧 / 丢弃纯消歧元素 /
    列表合并）稳定运行。"""

    @staticmethod
    def _register_changshan() -> None:
        # 常山双候选（常山北明/常山药业）——mock 库外的真实歧义形态，
        # autouse fixture 负责还原
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["000158"] = "常山北明"
        resolver_mod.stockDB["300255"] = "常山药业"
        resolver_mod._names_cache[:] = [None, None, None]

    def test_user_example_full_chain(self):
        # 用户实战样例：三子消息歧义短路 → 聚合回复逐组收窄 + 新任务
        self._register_changshan()
        r = _resolver()
        session: Dict[str, Any] = {}

        # 轮 1：三条子消息 → 短路，last_resolution 写入三组（阿里确认 /
        # 常山确认 / 医药CPO直达），tokens 与意图原样保留
        rs1 = r.resolve(
            "分析一下茅台和阿里然后看一下常山的价格，"
            "最后分析下医药和CPO板块的走势",
            session,
        )
        apply_resolution_to_session(session, rs1)
        lr = session[LAST_RESOLUTIONS_KEY]
        assert len(lr) == 3  # 二维：每子消息一组
        assert [t["needs_confirmation"] for g in lr for t in g] == [True, True, False]
        assert [g_["name"] for g in lr for t in g
                for g_ in (t.get("pending_action") or {}).get("groups", [])] \
            == ["阿里", "常山"]
        assert lr[1][0]["intent"] == WebIntent.QUOTE_LOOKUP  # 常山组属行情子消息
        assert lr[0][0]["tokens"][:2] == ["分析", "一下"]     # tokens 不缺失

        # 轮 2："港股"收窄阿里组、"常山药业"全等收窄常山组（同一条子
        # 消息的两个聚合项）、"再分析下三花"是新任务（kept）
        rs2 = r.resolve("港股和常山药业，再分析下三花", session)
        flat = _flat(rs2)
        assert not any(t.needs_confirmation for t in flat)
        # ③ 列表合并保序：上轮三组（就地消解后就位）在前、本轮 kept 在后
        assert [(t.intent, _codes(t), t.sectors) for t in flat] == [
            (WebIntent.STOCK_ANALYSIS, ["600519", "HK09988"], []),
            (WebIntent.QUOTE_LOOKUP, ["300255"], []),
            (WebIntent.SECTOR_ANALYSIS, [], ["医药", "CPO"]),
            (WebIntent.STOCK_ANALYSIS, ["002050"], []),
        ]
        # ① 就地消歧：任务原样保留——tokens / source_request 不缺失
        assert flat[0].tokens[:2] == ["分析", "一下"]
        assert flat[0].source_request == "分析一下茅台和阿里"
        assert flat[1].source_request == "然后看一下常山的价格"
        assert flat[3].source_request == "再分析下三花"

    def test_zero_interaction_returns_new_round(self):
        # 零交互（模糊回应"嗯嗯"）：本轮任务原样返回（新话题），上轮
        # 确认任务不混入——resolve_first 即本轮闲聊
        self._register_changshan()
        r = _resolver()
        session: Dict[str, Any] = {}
        rs1 = r.resolve("分析一下茅台和阿里", session)
        apply_resolution_to_session(session, rs1)
        rs2 = r.resolve("嗯嗯", session)
        assert len(_flat(rs2)) == 1
        assert _flat(rs2)[0].intent == WebIntent.GENERAL_CHAT
        assert _flat(rs2)[0].source == "rule"

    def test_decline_cancels_whole_chain(self):
        # 拒绝词：上轮整链作废，返回闲聊单任务
        r = _resolver()
        session: Dict[str, Any] = {}
        rs1 = r.resolve("分析一下茅台和阿里", session)
        apply_resolution_to_session(session, rs1)
        rs2 = r.resolve("算了", session)
        flat = _flat(rs2)
        assert len(flat) == 1
        assert flat[0].intent == WebIntent.GENERAL_CHAT
        assert flat[0].source == "confirmation"
        assert not flat[0].needs_confirmation


# =========================================================================
# 评审回归用例 — 上下文纯化 / LLM 合并闸门 / 切分契约 / 会话簿记。
# =========================================================================


class TestPRReviewProbes:
    """LLM 兜底的上下文契约：_session_context 纯归一化、上下文经
    _finalize_task/_classify_with_llm 显式传参。下列用例分别钉死
    request 上下文不覆盖会话 / 无会话零残留 / 并发不串会话与
    followup 继承的正确性。"""

    def test_probe_request_context_clobbers_llm_prompt_context(self):
        # request_context 只贡献 current_stock_code，不覆盖会话上下文
        # ——LLM 兜底 prompt 的 recent_stocks / last_intent 保持会话侧取值
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        session = {RECENT_STOCKS_KEY: ["600519"], LAST_INTENT_KEY: "stock_analysis"}
        _resolver(stub).resolve_first(
            "聊聊", session_context=session,
            request_context={"current_stock_code": "600519"},
        )
        assert len(stub.calls) == 1
        user_body = stub.calls[0]["messages"][1]["content"]
        assert "600519" in user_body, "recent_stocks 应进入 LLM prompt"
        assert "stock_analysis" in user_body, "last_intent 应进入 LLM prompt"

    def test_probe_request_context_breaks_followup_inheritance(self):
        # followup 伪标签在 _merge_llm_result 读显式传入的会话 context，
        # last_intent 正常继承上轮执行类意图
        stub = _StubLLMAdapter(content=_llm_json("followup", 0.9))
        session = {LAST_INTENT_KEY: "stock_analysis"}
        r = _resolver(stub).resolve_first(
            "再展开讲讲", session_context=session,
            request_context={"current_stock_code": "600519"},
        )
        assert r.intent == WebIntent.STOCK_ANALYSIS, "followup 应继承上轮执行类意图"

    def test_no_stale_context_across_resolves(self):
        # 无会话轮即空上下文，与上一轮无关——prompt 不残留上一轮的
        # 会话键（跨会话/跨用户零泄漏）
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        resolver = _resolver(stub)
        resolver.resolve_first("聊聊", session_context={
            RECENT_STOCKS_KEY: ["600519"], LAST_INTENT_KEY: "stock_analysis"})
        resolver.resolve_first("聊聊")  # 无会话轮：prompt 不得残留上一轮
        body = json.loads(stub.calls[1]["messages"][1]["content"])
        assert body["recent_stocks"] == []
        assert body["last_intent"] == ""

    def test_concurrent_resolves_no_cross_session_pollution(self):
        # 零共享可变状态：同一 resolver 并发复用（web 单例形态），
        # 两把 stub 各自只收到本会话的键
        import threading

        results: Dict[str, List[str]] = {}

        def _run(tag: str, code: str) -> None:
            stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
            session = {RECENT_STOCKS_KEY: [code], LAST_INTENT_KEY: "stock_analysis"}
            resolver = WebIntentResolver(llm_adapter=stub)
            threads = [
                threading.Thread(target=resolver.resolve_first, args=("聊聊", session))
                for _ in range(8)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            results[tag] = [
                recent[0]
                for c in stub.calls
                if (recent := json.loads(c["messages"][1]["content"])["recent_stocks"])
            ]

        ta = threading.Thread(target=_run, args=("A", "600519"))
        tb = threading.Thread(target=_run, args=("B", "000858"))
        ta.start(); tb.start(); ta.join(); tb.join()
        assert set(results["A"]) == {"600519"}, "A 会话 prompt 不得混入他盘"
        assert set(results["B"]) == {"000858"}, "B 会话 prompt 不得混入他盘"

    def test_probe_llm_merge_drops_prehung_multi_groups(self):
        # _merge_llm_result 以 dataclasses.replace 携带规则结果基底：预挂
        # 的多组歧义结构（每组 name/candidates/source_request）在 LLM
        # 成功路径不丢失，未指名字段自动随行、逐组确认结构原样
        stub = _StubLLMAdapter(content=_llm_json("quote_lookup", 0.9))
        rs = _resolver(stub).resolve("阿里巴巴多少钱，平安多少钱")
        confirmings = [t for t in _flat(rs) if t.needs_confirmation]
        assert len(confirmings) == 2, "两子消息歧义各自成确认任务"
        assert [[g["name"] for g in t.pending_action["groups"]]
                for t in confirmings] == [["阿里巴巴"], ["平安"]]
        assert all(len(g["candidates"]) == 2
                   for t in confirmings
                   for g in t.pending_action["groups"]), \
            "单组只含本组候选，不混入他组"

    def test_probe_llm_pick_drops_sibling_group(self):
        # LLM 在多组歧义中选定一组候选后，兄弟组保留待确认：阿里组由
        # stock_code 消解入 stocks，平安组保留（两任务各自独立）
        stub = _StubLLMAdapter(content=_llm_json(
            "quote_lookup", 0.9, stock_code="HK09988"))
        rs = _resolver(stub).resolve("阿里巴巴多少钱，平安呢")
        flat = _flat(rs)
        assert any(
            t.needs_confirmation and any(
                g["name"] == "平安" for g in (t.pending_action or {}).get("groups", []))
            for t in flat
        ), "平安组应保留待确认"

    def test_probe_sector_sibling_never_carries_main_stocks(self):
        # 板块兄弟任务不携带个股实体：stocks 按调用点显式声明，
        # primary_stock_code 不被锁定到个股（#1619 股票范围不注入
        # 错误标的）
        rs = _resolver().resolve("分析茅台和白酒板块")
        sector_task = _flat(rs)[1]
        assert sector_task.intent == WebIntent.SECTOR_ANALYSIS
        assert sector_task.sectors == ["白酒"]
        assert sector_task.stocks == [], "板块任务不应携带个股实体"
        assert sector_task.primary_stock_code == ""

    def test_probe_two_connective_cuts_in_one_unknown_token(self):
        # 契约（元素恒不变）：连接词埋在 unknown_token 内部不切分——
        # 元素改写违反不变量，同形态文本依赖标点边界表达任务边界
        from src.agent.web_intent_types import Token
        tokens = [
            Token("分析", "request"),
            Token("阿猫然后阿狗然后阿猪", ""),
        ]
        subs = _split_sub_messages(tokens, "分析阿猫然后阿狗然后阿猪")
        assert subs == [tokens], "unknown_token 不切分，元素原样归一组"
        assert ["".join(t.text for t in sub)
                for sub in _split_sub_messages("分析阿猫，然后阿狗，然后阿猪")] == [
            "分析阿猫", "然后阿狗", "然后阿猪",
        ], "标点形态（token 边界切口）正常三段"

    def test_probe_unknown_token_double_cut_keeps_middle_task(self):
        # 契约的 task 级形态：无标点时连接词埋在 unknown_token 内无从
        # 下刀，整条消息单任务（低置信交 LLM 兜底）；同形态标点版
        # （token 边界切口）三段、中段行情任务（"看下白酒板块"）存活
        # ——多任务结构由标点边界承载
        rs = _resolver().resolve("阿猫然后看下白酒板块然后聊聊")
        assert [(t.intent, t.sectors) for t in _flat(rs)] == [
            (WebIntent.GENERAL_CHAT, []),
        ]
        rs_ok = _resolver().resolve("阿猫，然后看下白酒板块，然后聊聊")
        assert [(t.intent, t.sectors) for t in _flat(rs_ok)] == [
            (WebIntent.GENERAL_CHAT, []),
            (WebIntent.QUOTE_LOOKUP, ["白酒"]),
            (WebIntent.GENERAL_CHAT, []),
        ]

    def test_probe_llm_bare_hk_code_identity(self):
        # LLM 按真实世界拼写返回裸 5 位 "09988"：闸门前经
        # _canonical_digit_code 归一到 HK+5 规范身份，直接命中组内候选、
        # 歧义收敛（与 tokenizer 规范身份同一拼写）。触发路径：空 tag
        # 残段 → 非全识别豁免
        stub = _StubLLMAdapter(content=_llm_json(
            "stock_analysis", 0.9, stock_code="09988"))
        r = _resolver(stub).resolve_first("阿里巴巴哈哈哈")
        assert _codes(r) == ["HK09988"], "HK 代码应规范化为 HK+5 位拼写"
        assert r.candidates == [], "LLM 已选定候选，歧义应收敛"

    def test_history_recorded_at_session_level(self):
        # Resolution 不携带历史标的字段：历史标的的持久化通道是会话键
        # recent_stocks（apply 头插去重，只记执行轮），任务仅携带标量
        # 视图 inherited_stock_code；需要三元组时按 code 查库派生
        # （持久化三元组会随库更新陈旧）
        session: Dict[str, Any] = {}
        rs = _resolver().resolve("茅台多少钱", session_context=session)
        r = _flat(rs)[0]
        assert not hasattr(r, "history_stocks"), "死字段应已删除"
        assert r.inherited_stock_code == ""  # 空会话：无继承
        apply_resolution_to_session(session, rs)
        assert session[RECENT_STOCKS_KEY] == ["600519"]  # 会话级记录即全部历史


# =========================================================================
# 第五步消歧路径专项 — 证据通道 / kinds 三分类 / 组结算三态（补覆盖）
# =========================================================================


class TestStep5NarrowingEvidenceChannels:
    """第五步第二趟（组 × 预消歧子消息）的逐证据通道端到端：市场词收窄
    到唯一 / 候选名全等 / 候选名唯一子串 / 确定实体命中候选 / 裸数字
    短码（全等、裸数字、市场词已有用例，此处补齐剩余通道与边界）。"""

    @staticmethod
    def _pending_pingan_session() -> Dict[str, Any]:
        # "平安"歧义：平安银行 / 中国平安（同市场双候选，全名可区分）
        return {PENDING_ACTIONS_KEY: [{
            "action": "confirm_stock", "intent": "stock_analysis", "name": "平安",
            "candidates": [
                {"code": "000001", "name": "平安银行", "market": "a"},
                {"code": "601318", "name": "中国平安", "market": "a"},
            ],
            "original_request": "分析平安",
        }]}

    @staticmethod
    def _pending_dual_cross_market() -> Dict[str, Any]:
        # 双跨市场歧义组：阿里巴巴（hk/us）+ 中芯国际（a/hk）
        return {
            "action": "confirm_stock", "intent": "stock_analysis",
            "groups": [
                {"name": "阿里巴巴",
                 "candidates": [
                     {"code": "HK09988", "name": "阿里巴巴", "market": "hk"},
                     {"code": "BABA", "name": "阿里巴巴", "market": "us"},
                 ],
                 "source_request": "分析阿里巴巴"},
                {"name": "中芯国际",
                 "candidates": [
                     {"code": "688981", "name": "中芯国际", "market": "a"},
                     {"code": "HK00981", "name": "中芯国际", "market": "hk"},
                 ],
                 "source_request": "分析中芯国际"},
            ],
            "original_request": "分析阿里巴巴和中芯国际",
        }

    def test_unique_substring_channel(self):
        # 候选名唯一子串："看下平安银行吧"（"看下"在 extend 池，无 clean
        # 意图词 → 纯消歧）。全等通道不成立（子消息非候选全名），子串
        # 通道唯一命中平安银行（中国平安不在文中）
        r = _resolver().resolve_first("看下平安银行吧", self._pending_pingan_session())
        assert r.source == "confirmation"
        assert _codes(r) == ["000001"]
        assert not r.needs_confirmation

    def test_market_word_zero_hit_is_not_evidence(self):
        # 市场词与候选矛盾（"美股" × a/a 双候选）：过滤后零只 ≠ 证据 →
        # 零交互，整轮按新消息解析，pending 由 apply 收敛。市场词是
        # 合法板块主体（见 TestMarketWordAsSectorSubject），重开的
        # "美股"按新消息落为美股行情查询——不变量是"零命中不消费确认
        # 任务"，而非重开消息的具体意图
        r = _resolver().resolve_first("美股", self._pending_pingan_session())
        assert r.source == "rule"
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert r.sectors == ["美股"]
        assert not r.needs_confirmation

    def test_contradictory_reply_reopens_as_comparison(self):
        # 矛盾弃置→整轮判新话题（模块 docstring 第五步契约）：同一条回
        # 复点名组内两个候选（无意图词）＝比较/新请求——确认任务整组
        # 弃置剔除，贡献子消息保留为双标的比较任务（不空壳放行、不回
        # 退会话陈旧标的），pending 由 apply 清空
        session = self._pending_pingan_session()
        rs = _resolver().resolve("平安银行 中国平安", session)
        assert len(_flat(rs)) == 1
        r = _flat(rs)[0]
        assert r.source == "rule"
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert _codes(r) == ["000001", "601318"]
        assert not r.needs_confirmation
        assert r.pending_action is None
        apply_resolution_to_session(session, rs)
        assert session[PENDING_ACTIONS_KEY] == []

    def test_market_word_narrows_two_groups_at_once(self):
        # 市场词可同时收窄多组："港股"对两个跨市场组各过滤出唯一 hk
        # 候选 → 组间独立结算、同 intent 聚合为单任务双标的
        rs = _resolver().resolve(
            "港股", {PENDING_ACTIONS_KEY: [self._pending_dual_cross_market()]})
        assert len(_flat(rs)) == 1
        assert _codes(_flat(rs)[0]) == ["HK09988", "HK00981"]
        assert not _flat(rs)[0].needs_confirmation

    def test_entity_resolves_one_group_and_requeues_other(self):
        # 6 位裸码提升为确定实体命中组内候选：中芯组消解、阿里组未解
        # → 重建 pending 继续等待（confirmed 记累积、resolved_stocks 随
        # 行实体），整链短路早退——第六步不跑，LLM 兜底零调用
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        rs = _resolver(stub).resolve(
            "688981", {PENDING_ACTIONS_KEY: [self._pending_dual_cross_market()]})
        assert stub.calls == []
        r = _flat(rs)[0]
        assert r.needs_confirmation
        assert _codes(r) == ["688981"]
        assert [g["name"] for g in r.pending_action["groups"]] == ["阿里巴巴"]
        assert [s["code"] for c in r.pending_action["confirmed"]
                for s in c["stocks"]] == ["688981"]
        assert [s["code"] for s in r.pending_action["resolved_stocks"]] == ["688981"]


class TestStep5ReplyKinds:
    """第五步第一趟 kinds 三分类（fresh / keep / narrow）的裁决与后果：
    fresh 不参与收窄（整轮判新话题）；keep 参与收窄且保留为新任务；
    narrow 参与收窄后被 ② 丢弃（不是任务）。"""

    def test_fresh_reply_reopens_topic(self):
        # fresh：子消息混入候选外新实体（600519）→ 整条子消息不参与收
        # 窄，零交互按新话题重析——重析自身又产生新的歧义确认
        r = _resolver().resolve_first("分析600519和阿里巴巴", _ali_session())
        assert r.source == "rule"
        assert _codes(r) == ["600519"]
        assert r.needs_confirmation
        assert r.reason == "ambiguous_stock_name"
        assert set(_candidate_codes(r)) == {"HK09988", "BABA"}

    def test_fresh_and_narrow_sub_messages_combined(self):
        # fresh + narrow 并存："分析600519，港股"——确认任务由"港股"消
        # 解，新任务（600519）保留；不折叠，两标的各自独立执行
        # （确认消解项在前、新任务在后）
        rs = _resolver().resolve("分析600519，港股", _ali_session())
        tasks = _flat(rs)
        assert len(tasks) == 2
        assert tasks[0].source == "confirmation" and _codes(tasks[0]) == ["HK09988"]
        assert tasks[1].source == "rule" and _codes(tasks[1]) == ["600519"]
        assert not any(t.needs_confirmation for t in tasks)

    def test_keep_sub_message_survives_as_task(self):
        # keep（模块 docstring 示例）："港股"（narrow，被 ② 丢弃）消解上
        # 轮确认任务，"分析医药板块"（keep，带意图词）保留为新任务，
        # ③ 拼接后上轮组序在前、本轮在后
        rs = _resolver().resolve("港股，分析医药板块", _ali_session())
        assert [(t.intent, _codes(t), t.sectors) for t in _flat(rs)] == [
            (WebIntent.STOCK_ANALYSIS, ["HK09988"], []),
            (WebIntent.SECTOR_ANALYSIS, [], ["医药"]),
        ]
        assert _flat(rs)[0].source == "confirmation"
        assert _flat(rs)[1].source == "rule"

    def test_keep_task_coexists_with_consumed_task(self):
        # keep 与消费发生在同一子消息："阿里巴巴港股怎么样"（市场词 +
        # clean 意图词"怎么样"）——确认任务消解、重析任务独立保留
        # （不折叠：同标的两任务并存，消费方可按需去重）
        rs = _resolver().resolve("阿里巴巴港股怎么样", _ali_session())
        tasks = _flat(rs)
        assert len(tasks) == 2
        assert all(_codes(t) == ["HK09988"] for t in tasks)
        assert tasks[0].source == "confirmation"
        assert tasks[1].source == "rule" and tasks[1].confidence == 0.85
        assert not any(t.needs_confirmation for t in tasks)

    def test_decline_word_with_content_is_not_decline(self):
        # 拒绝词判定是整条消息拼接的全文匹配（^...$）："算了，再看看茅
        # 台"不是拒绝——按新话题解析为 [闲聊, 个股分析]，无 confirmation
        # 产物混入
        rs = _resolver().resolve("算了，再看看茅台", _ali_session())
        assert [t.intent for t in _flat(rs)] == [
            WebIntent.GENERAL_CHAT, WebIntent.STOCK_ANALYSIS]
        assert all(t.source == "rule" for t in _flat(rs))
        assert _codes(_flat(rs)[1]) == ["600519"]
        assert not any(t.needs_confirmation for t in _flat(rs))

    def test_stale_pending_ignored_when_last_resolutions_present(self):
        # 数据源优先级：last_resolutions 在场（且无确认任务）时不读
        # pending_actions——两键失配（外部写脏）不误触发确认消费
        plain = WebIntentResolution(WebIntent.STOCK_ANALYSIS, 0.9,
                                    stocks=[Stock("600519", "贵州茅台", "a")])
        session = {LAST_RESOLUTIONS_KEY: [[asdict(plain)]],
                   PENDING_ACTIONS_KEY: [_pending_ali()]}
        r = _resolver().resolve_first("分析600519", session)
        assert r.source == "rule"
        assert _codes(r) == ["600519"]
        assert not r.needs_confirmation


class TestStep5Units:
    """第五步内部函数白盒：pending 形状归一（Stock 对象/坏条目/平铺
    兜底）与无确认任务的直通契约。"""

    def test_normalize_pending_groups_filters_malformed(self):
        # groups[].candidates 为 Stock 对象与坏条目（非 dict 组 / 无
        # code 候选 / 空候选组）混排：逐条过滤只留有效组，组内候选
        # 统一为 Stock
        groups, all_stocks = _normalize_pending_groups({
            "groups": [
                "not-a-dict",
                {"name": "阿里巴巴", "candidates": [
                    Stock("HK09988", "阿里巴巴", "hk"), {"name": "无code"}]},
                {"name": "空组", "candidates": []},
            ],
        })
        assert [g["name"] for g in groups] == ["阿里巴巴"]
        assert [s.code for s in all_stocks] == ["HK09988"]

    def test_normalize_pending_groups_non_dict_pending(self):
        # pending 自身非 dict（外部会话毒化，如字符串 pending_action）：
        # 解析器入口类型守卫 → 空列表，不击穿消费链
        groups, all_stocks = _normalize_pending_groups("confirm_stock")
        assert groups == [] and all_stocks == []

    def test_normalize_pending_groups_flat_fallback(self):
        # groups 全坏 → 顶层平铺（name/candidates）视为单组，
        # source_request 取 original_request
        groups, all_stocks = _normalize_pending_groups({
            "groups": ["bad", {"candidates": []}],
            "name": "阿里巴巴",
            "candidates": [{"code": "BABA", "name": "阿里巴巴", "market": "us"}],
            "original_request": "分析阿里巴巴",
        })
        assert [g["name"] for g in groups] == ["阿里巴巴"]
        assert groups[0]["source_request"] == "分析阿里巴巴"
        assert [s.code for s in all_stocks] == ["BABA"]

    def test_consume_no_confirmings_returns_recovered(self):
        # last_resolution 无确认任务：① 不消费，原样返回恢复后的二维结
        # 构（任务对象身份不变）
        plain = WebIntentResolution(WebIntent.STOCK_ANALYSIS, 0.9,
                                    stocks=[Stock("600519", "贵州茅台", "a")])
        new = WebIntentResolution(WebIntent.QUOTE_LOOKUP, 0.85)
        out = _consume_confirmations([[plain]], [new])
        assert out == [[plain]]
        assert out[0][0] is plain


class TestResolveOutputContract:
    """resolve 出口契约：一律二维（外层=子消息任务组），空输入同样。"""

    def test_empty_message_two_dim_shape(self):
        rs = _resolver().resolve("")
        assert isinstance(rs, list) and len(rs) == 1
        assert isinstance(rs[0], list)
        assert rs[0][0].intent == WebIntent.GENERAL_CHAT
        assert rs[0][0].source == "rule"

    def test_single_intent_message_two_dim_shape(self):
        rs = _resolver().resolve("分析600519")
        assert len(rs) == 1 and len(rs[0]) == 1
        assert _codes(rs[0][0]) == ["600519"]


# =========================================================================
# 第六步收尾专项 — LLM 兜底触发面与代码闸门 / 确认判定补齐
# =========================================================================


class TestStep6LlmFallbackChannels:
    """第六步① LLM 兜底：stock_code 三道闸门（候选命中 → 查库 → 未命中
    按形态分流）与 confirmation 产物的豁免面。"""

    def test_llm_alpha_code_not_in_db_unverified(self):
        # 查库未命中 + 纯字母形态：透传执行端实查（unverified），不做
        # 确认——LLM 代码通道无原文闸门（与 sectors/unresolved 不同）
        stub = _StubLLMAdapter(content=_llm_json(
            "stock_analysis", 0.9, stock_code="ZZZZ"))
        r = _resolver(stub).resolve_first("聊聊")
        assert r.source == "llm"
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.stocks == []
        assert r.unverified_codes == ["ZZZZ"]
        assert not r.needs_confirmation

    def test_llm_hk_code_not_in_db_unverified(self):
        # HK 前缀形态未命中：同样透传实查（hk 非全量库无判定把握）
        stub = _StubLLMAdapter(content=_llm_json(
            "stock_analysis", 0.9, stock_code="HK66373"))
        r = _resolver(stub).resolve_first("聊聊")
        assert r.source == "llm"
        assert r.unverified_codes == ["HK66373"]
        assert not r.needs_confirmation

    def test_llm_chat_with_bad_code_drops_code(self):
        # LLM 判闲聊但夹带库外代码：闲聊无执行面，坏代码不可信——
        # unresolved/unverified 清空，不转确认
        stub = _StubLLMAdapter(content=_llm_json(
            "general_chat", 0.9, stock_code="888888"))
        r = _resolver(stub).resolve_first("聊聊电影")
        assert r.source == "llm"
        assert r.intent == WebIntent.GENERAL_CHAT
        assert r.confidence == LLM_CONFIDENCE_CAP
        assert r.unresolved_names == [] and r.unverified_codes == []
        assert not r.needs_confirmation

    def test_llm_resolution_withdraws_prehung_pending(self):
        # 确认判定补齐的收尾分支：LLM 消歧清空候选后，第四步预挂的
        # pending_action 载体撤下（不携带已消解的歧义组随行）。
        # 触发路径：空 tag 残段 → 非全识别豁免 → 兜底
        stub = _StubLLMAdapter(content=_llm_json(
            "stock_analysis", 0.9, stock_code="HK09988"))
        r = _resolver(stub).resolve_first("阿里巴巴哈哈哈")
        assert _codes(r) == ["HK09988"]
        assert r.candidates == []
        assert r.pending_action is None
        assert not r.needs_confirmation

    def test_confirmation_source_exempt_from_llm(self):
        # 纯确认碎片（source=confirmation）永不触发大模型——即便携带
        # 未消解候选
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        resolver = WebIntentResolver(llm_adapter=stub)
        confirming = WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.5, source="confirmation",
            candidates=[Stock("HK09988", "阿里巴巴", "hk"),
                        Stock("BABA", "阿里巴巴", "us")])
        assert resolver._should_use_llm(confirming) is False
        same_but_rule = WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.5, source="rule",
            candidates=[Stock("HK09988", "阿里巴巴", "hk")])
        assert resolver._should_use_llm(same_but_rule) is True

    def test_fully_recognized_high_confidence_exempt(self):
        # tag 全识别 + ≥0.8：视野与判定双完备，即便携带歧义候选也不
        # 复核（candidates 不参与触发判据）；置信不足或空 tag 残段
        # 则照常触发兜底
        resolver = WebIntentResolver(llm_adapter=_StubLLMAdapter())
        base = WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.85, source="rule",
            candidates=[Stock("HK09988", "阿里巴巴", "hk")],
            all_tags_recognized=True)
        assert resolver._should_use_llm(base) is False
        assert resolver._should_use_llm(replace(base, confidence=0.75)) is True
        assert resolver._should_use_llm(
            replace(base, all_tags_recognized=False)) is True


class TestStep6Finalization:
    """收尾（LLM 改写意图 / 任务不折叠各自独立）与确认判定补齐
    （无预挂组的兜底建组 / 置信度钳制）。"""

    def test_llm_rewrite_tasks_stay_separate(self):
        # LLM 兜底改写意图（裸板块"半导体怎么样"被改判 quote）后不做
        # 同意图合并——改写产物独立成任务；主任务高置信豁免不进 LLM
        stub = _StubLLMAdapter(content=_llm_json("quote_lookup", 0.9))
        rs = _resolver(stub).resolve("查一下茅台股价，然后机器人怎么样")
        assert len(stub.calls) == 1  # 主任务高置信豁免，仅双解板块任务进 LLM
        tasks = _flat(rs)
        assert len(tasks) == 2
        assert tasks[0].source == "rule" and tasks[0].confidence == 0.85
        assert tasks[0].intent == WebIntent.QUOTE_LOOKUP
        assert _codes(tasks[0]) == ["600519"]
        assert tasks[1].source == "llm" and tasks[1].confidence == 0.75
        assert tasks[1].sectors == ["机器人"]
        assert not any(t.needs_confirmation for t in tasks)

    def test_sequential_tasks_stay_independent(self):
        # 任务不折叠、各自独立：首尾同为 stock_analysis 但中间隔着
        # quote 任务——保序返回不打乱用户的表达顺序；首任务的歧义
        # 确认使整链短路，兄弟任务随组结构返回
        rs = _resolver().resolve("分析阿里巴巴，查一下茅台股价，再看看五粮液")
        assert [t.intent for t in _flat(rs)] == [
            WebIntent.STOCK_ANALYSIS,
            WebIntent.QUOTE_LOOKUP,
            WebIntent.STOCK_ANALYSIS,
        ]
        assert _flat(rs)[0].needs_confirmation
        assert _flat(rs)[0].reason == "ambiguous_stock_name"
        assert _codes(_flat(rs)[1]) == ["600519"]
        assert _codes(_flat(rs)[2]) == ["000858"]

    def test_finalize_confirmation_builds_fallback_group(self):
        # 无预挂组时的兜底建组：候选全量进单组、组名取首候选名/代码、
        # original_request 记子消息文本（第四步规则路径恒预挂，本分支
        # 防御 resolve 之外构造 resolution 的调用方）
        res = WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.85,
            candidates=[Stock("HK09988", "阿里巴巴", "hk"),
                        Stock("BABA", "阿里巴巴", "us")],
            source_request="分析阿里巴巴", tokens=["分析", "阿里巴巴"])
        out = _finalize_confirmation(res)
        assert out.needs_confirmation
        assert out.reason == "ambiguous_stock_name"
        groups = out.pending_action["groups"]
        assert len(groups) == 1
        assert groups[0]["name"] == "阿里巴巴"
        assert {c["code"] for c in groups[0]["candidates"]} == {"HK09988", "BABA"}
        assert out.pending_action["original_request"] == "分析阿里巴巴"

    def test_finalize_confirmation_clamps_confidence(self):
        # 置信度出界钳制到 [0,1]：1.5 → 1.0（高于阈值不确认）
        res = WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 1.5,
            stocks=[Stock("600519", "贵州茅台", "a")])
        out = _finalize_confirmation(res)
        assert out.confidence == 1.0
        assert not out.needs_confirmation


# =========================================================================
# 消歧收窄与 LLM 闸门回归
# =========================================================================


class TestDeepScanProbes:
    """消歧收窄与 LLM 代码闸门的回归用例（均断言期望行为）。"""

    @staticmethod
    def _register_zhongxin_dual() -> None:
        # 中芯国际 a/hk 双上市（与 pending 组候选一致）
        from src.services import name_to_code_resolver as resolver_mod

        resolver_mod.stockDB["688981"] = "中芯国际"
        resolver_mod.stockDB["HK00981"] = "中芯国际"
        resolver_mod._names_cache[:] = [None, None, None]

    @staticmethod
    def _dual_group_pending() -> Dict[str, Any]:
        # 双歧义组 pending：阿里巴巴（hk/us）+ 中芯国际（a/hk）
        return {
            "action": "confirm_stock", "intent": "stock_analysis",
            "groups": [
                {"name": "阿里巴巴",
                 "candidates": [
                     {"code": "HK09988", "name": "阿里巴巴", "market": "hk"},
                     {"code": "BABA", "name": "阿里巴巴", "market": "us"}],
                 "source_request": "分析阿里巴巴"},
                {"name": "中芯国际",
                 "candidates": [
                     {"code": "688981", "name": "中芯国际", "market": "a"},
                     {"code": "HK00981", "name": "中芯国际", "market": "hk"}],
                 "source_request": "分析中芯国际"},
            ],
            "original_request": "分析阿里巴巴和中芯国际",
        }

    def test_probe_low_confidence_withdraws_prehung_groups(self):
        # LLM 低置信（0.5）但在候选中选了码：candidates 清空、conf <0.6
        # → low_confidence 确认。歧义已消解（stocks=[HK09988]）时预挂组
        # 撤下，确认意图只针对"意图待澄清"——残留组会被 apply_pending
        # 写回 pending_actions，弹出误导性选股确认。
        # 触发路径：空 tag 残段 → 非全识别豁免 → 兜底
        stub = _StubLLMAdapter(content=_llm_json(
            "quote_lookup", 0.5, stock_code="HK09988"))
        rs = _resolver(stub).resolve("阿里巴巴哈哈哈", {})
        t = _flat(rs)[0]
        assert t.needs_confirmation and t.reason == "low_confidence"
        assert _codes(t) == ["HK09988"]
        assert t.pending_action is None, \
            "low_confidence 不应携带 confirm_stock 载体（歧义已消解）"

    def test_probe_llm_single_code_keeps_sibling_group(self):
        # 单子消息双歧义（阿里巴巴+中芯国际）时 LLM 只回
        # stock_code=HK09988：只消解阿里组，中芯组的候选与预挂组保留
        # 转确认（candidates 整清会让兄弟组静默丢失）。
        # 触发路径：词池外语气词留下空 tag 残段 → 非全识别豁免 → 兜底
        # （两名均全名，Step 1 先行消费，不被 unknown_token 陪葬）
        self._register_zhongxin_dual()
        stub = _StubLLMAdapter(content=_llm_json(
            "quote_lookup", 0.9, stock_code="HK09988"))
        rs = _resolver(stub).resolve("阿里巴巴和中芯国际哈哈哈", {})
        t = _flat(rs)[0]
        assert _codes(t) == ["HK09988"], "阿里组由 LLM 代码消解"
        assert t.needs_confirmation, "中芯组未解，任务应转确认"
        assert [g["name"] for g in (t.pending_action or {}).get("groups", [])] \
            == ["中芯国际"], "兄弟组不得静默丢失"

    def test_probe_per_group_market_reply_scoped(self):
        # 两组各点名市场（阿里→港股、中芯→A股）。
        # 按名指向的市场词只作用于被点名组：不串扰他组（错误消解或矛盾
        # 弃置）；点名组不覆盖的市场词保留全局（"港股和常山药业"行为
        # 见 test_user_example_full_chain）
        self._register_zhongxin_dual()
        rs = _resolver().resolve(
            "阿里巴巴要港股的，中芯国际要A股的",
            {PENDING_ACTIONS_KEY: [self._dual_group_pending()]})
        t = _flat(rs)[0]
        assert not t.needs_confirmation
        assert _codes(t) == ["HK09988", "688981"], \
            "两组应各按用户所指市场消解"

    def test_probe_named_market_word_does_not_leak_to_other_group(self):
        # 回复只点名一组（"阿里巴巴要港股"）时，市场词不得把他组顶到
        # 错误市场——中芯组应保持未解重建 pending 继续等待，而非带着
        # 用户未选择的 HK00981 提前放行
        self._register_zhongxin_dual()
        session: Dict[str, Any] = {}
        r = WebIntentResolver()
        rs1 = r.resolve("分析阿里巴巴和中芯国际", session)
        apply_resolution_to_session(session, rs1)
        rs2 = r.resolve("阿里巴巴要港股", session)
        t = _flat(rs2)[0]
        assert t.needs_confirmation, "中芯组未解，确认应继续等待"
        assert [g["name"] for g in t.pending_action["groups"]] == ["中芯国际"]
        assert [s["code"] for c in t.pending_action.get("confirmed", [])
                for s in c["stocks"]] == ["HK09988"], \
            "阿里组的消解结果记入 confirmed 累积"
        assert _codes(t) == ["HK09988"], "仅阿里组按港股消解"

    def test_probe_decline_across_sub_messages(self):
        # 拒绝词逐子消息锚定匹配：全部片段为完整拒绝形才取消——整串
        # 拼接丢分隔符会把"算了，不分析了"拼成用户从未说过的"算了不
        # 分析了"。"拒绝词＋内容"非取消契约由
        # test_decline_word_with_content_is_not_decline 锁定
        session = _ali_session()
        rs = _resolver().resolve("算了，不分析了", session)
        flat_ = _flat(rs)
        assert len(flat_) == 1
        assert flat_[0].source == "confirmation", "应识别为确认链取消"
        assert flat_[0].intent == WebIntent.GENERAL_CHAT

    def test_probe_llm_code_outside_groups_rejected(self):
        # 规则侧已有歧义候选时，LLM 返回库内命中但不在任何候选组的代码
        # 是越权换标的，必须拒收——否则 fabricated 标的随 resolved_
        # stocks 骑行进任务，消歧确认后与用户所选并列执行
        stub = _StubLLMAdapter(content=_llm_json(
            "quote_lookup", 0.9, stock_code="600519"))
        rs = _resolver(stub).resolve("阿里巴巴多少钱", {})
        t = _flat(rs)[0]
        assert _codes(t) == [], "候选组外的库内代码不得注入 stocks"
        assert t.needs_confirmation, "阿里组歧义仍待确认"
        assert [g["name"] for g in t.pending_action["groups"]] == ["阿里巴巴"]
        # 对照：无候选场景（描述性指称/指代解析）注入不受影响——
        # 见 test_valid_stock_code_injected / test_multi_mentions_via_
        # stock_codes（"那只白酒股"/"这两只"→ 代码注入是设计特性）


# =========================================================================
# LLM 多意图协议与复核触发面
# =========================================================================


class TestLlmMultiIntent:
    """LLM 多意图协议：触发判据（multi_intent_hint）、载荷解析（intents
    数组优先/单对象兼容）、逐项合并护栏与保序任务列表产出。"""

    def test_multi_intent_hint_stamped_on_unexpressible_signals(self):
        # 规则自知单任务表达不完：数据对象级 quote 词与强分析词同场
        # （"股价+基本面"深度被裁决序吸收）→ hint 置位；纯取数动词
        # （看下…走势）与单意图消息不置位
        r = _resolver().resolve_first("看一下茅台股价和基本面再分析比亚迪")
        assert r.multi_intent_hint
        assert r.confidence == 0.85 and r.source == "rule", "无 LLM 时规则直达"
        assert not _resolver().resolve_first(
            "看下现在人工智能赛道和AI板块的走势").multi_intent_hint
        assert not _resolver().resolve_first("分析五粮液").multi_intent_hint

    def test_intents_array_parsed_and_invalid_items_dropped(self):
        payload = _parse_llm_payload(json.dumps({
            "intents": [
                {"intent": "quote_lookup", "confidence": 0.9, "stock_code": "600519"},
                {"intent": "bogus_intent", "confidence": 0.9},
                "not-a-dict",
                {"intent": "STOCK-Analysis。", "confidence": 0.85,
                 "stock_code": "002594"},
            ],
        }, ensure_ascii=False))
        assert [i["intent"] for i in payload["intents"]] == [
            "quote_lookup", "stock_analysis"], "非法项丢弃、标签规范化"

    def test_intents_array_all_invalid_falls_back_to_single(self):
        # 数组全非法 → 回退单对象形态判定
        payload = _parse_llm_payload(json.dumps({
            "intents": [{"intent": "bogus"}, 5],
            "intent": "general_chat", "confidence": 0.5,
        }))
        assert payload is not None and "intents" not in payload
        assert payload["intent"] == "general_chat"

    def test_multi_intent_end_to_end_ordered_task_list(self):
        # 端到端：hint 取消高置信豁免（0.85 全识别仍触发兜底），intents
        # 数组逐项过闸（实体重置基底，规则压缩的双标的不污染每张任务单），
        # 保序产出三张任务：报价茅台 / 分析茅台 / 分析比亚迪——同标的双
        # 深度与顺序动作均独立成单
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "quote_lookup", "confidence": 0.9, "stock_code": "600519"},
            {"intent": "stock_analysis", "confidence": 0.9,
             "stock_codes": ["600519"]},
            {"intent": "stock_analysis", "confidence": 0.9, "stock_code": "002594"},
        ]}, ensure_ascii=False))
        rs = _resolver(stub).resolve("看一下茅台股价和基本面再分析比亚迪")
        flat_ = _flat(rs)
        assert len(stub.calls) == 1, "hint 破除高置信豁免，兜底被触发"
        assert [(t.intent, _codes(t)) for t in flat_] == [
            (WebIntent.QUOTE_LOOKUP, ["600519"]),
            (WebIntent.STOCK_ANALYSIS, ["600519"]),
            (WebIntent.STOCK_ANALYSIS, ["002594"]),
        ]
        assert all(t.source == "llm" for t in flat_)
        assert all(t.source_request == "看一下茅台股价和基本面再分析比亚迪"
                   for t in flat_), "兄弟任务继承来源子消息"

    def test_multi_intent_hallucinated_item_code_gated(self):
        # 逐项闸门：某项返回库内命中但消息未提及的代码（幻觉）→ 拒收，
        # 该项以空标的低置信转确认（宁缺毋滥按项生效）
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "quote_lookup", "confidence": 0.9, "stock_code": "600519"},
            {"intent": "stock_analysis", "confidence": 0.9, "stock_code": "888888"},
        ]}, ensure_ascii=False))
        rs = _resolver(stub).resolve("看一下茅台股价和基本面")
        flat_ = _flat(rs)
        assert _codes(flat_[0]) == ["600519"]
        assert _codes(flat_[1]) == [] or flat_[1].needs_confirmation

    def test_multi_intent_followup_item_chains_previous(self):
        # 数组内 followup＝延续前一项意图（与规则分支6链式继承同构），
        # 不是会话级 last_intent——会话置 sector_analysis 作对照，第二
        # 项仍应继承数组首项的 quote_lookup；单元素数组的会话级继承由
        # 既有 test_followup_with_context_inherits_intent 覆盖
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "quote_lookup", "confidence": 0.9, "stock_code": "600519"},
            {"intent": "followup", "confidence": 0.9},
        ]}, ensure_ascii=False))
        rs = _resolver(stub).resolve(
            "看一下茅台股价和基本面",
            {LAST_INTENT_KEY: "sector_analysis"})
        flat_ = _flat(rs)
        assert flat_[0].intent == WebIntent.QUOTE_LOOKUP
        assert flat_[1].intent == WebIntent.QUOTE_LOOKUP, \
            "数组内 followup 延续前一项，而非会话级 last_intent"

    def test_unread_unknown_token_without_subject_triggers_llm(self):
        # 视野残缺×无主体：unknown_token 里可能正是未读出的主体或附加诉求——
        # 高置信裁决只对已读部分可靠，未读内容不得静默丢弃（"查下我持
        # 仓的股票股价"：unknown_token"的股票股价"埋着数据对象词，stocks/sectors
        # 全空无交叉验证）。conf 保持路径语义不回写，触发器消费视野轴。
        # 有主体的附带 unknown_token 维持既有豁免（"茅台多少钱顺便看下SOFI"由
        # test_high_confidence_exempt_from_side_triggers 钉住）
        stub = _StubLLMAdapter(content=_llm_json("portfolio_analysis", 0.9))
        r = _resolver(stub).resolve_first("查下我持仓的股票股价")
        assert len(stub.calls) == 1, "视野残缺×无主体破除高置信放行"
        assert r.source == "llm"
        assert r.intent == WebIntent.PORTFOLIO_ANALYSIS

    def test_group_level_review_no_duplication(self):
        # 组级收尾（sub_message 最小单位）：出口分解的兄弟任务不各自
        # 触发复核——同一条子消息至多一次多意图枚举，产出整组替换。
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "portfolio_analysis", "confidence": 0.9},
            {"intent": "quote_lookup", "confidence": 0.9},
        ]}, ensure_ascii=False))
        rs = _resolver(stub).resolve("看下我持仓的医药ETF")
        assert len(stub.calls) == 1, "一条子消息至多一次多意图枚举"
        flat_ = _flat(rs)
        assert [t.intent for t in flat_] == [
            WebIntent.PORTFOLIO_ANALYSIS, WebIntent.QUOTE_LOOKUP],             "枚举产出整组替换，不与规则兄弟拼接"

    def test_pipeline_split_on_generic_collection_subject(self):
        # 管道拆分原理（一般化契约）：显式动作词作用于账户泛指集合
        # （无显式主体）→ 交大模型拆〔持仓分析（取集合）＋作用于集合的
        # 普遍化任务〕——全识别高置信 0.85 也破除豁免（否则完全分词的
        # 管道形态会规则直达丢拆分）；主体显式（持仓的茅台股价）与
        # 中性问句（我的持仓怎么样）不触发
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "portfolio_analysis", "confidence": 0.9},
            {"intent": "stock_analysis", "confidence": 0.9},
        ]}, ensure_ascii=False))
        rs = _resolver(stub).resolve("分析我的持仓")
        assert len(stub.calls) == 1, "泛指集合×动作词破除豁免"
        flat_ = _flat(rs)
        assert [t.intent for t in flat_] == [
            WebIntent.PORTFOLIO_ANALYSIS, WebIntent.STOCK_ANALYSIS]
        assert all(t.source == "llm" for t in flat_)
        stub2 = _StubLLMAdapter(content=_llm_json("portfolio_analysis", 0.9))
        _resolver(stub2).resolve_first("我的茅台还该拿着吗")
        assert stub2.calls == [], "主体显式不触发（不需账户数据的单任务形态）"
        _resolver(stub2).resolve_first("我的持仓今天怎么样")
        assert stub2.calls == [], "中性问句不触发（终态单一持仓分析）"

    def test_subjectless_action_defaults_to_it(self):
        # 主题缺失的动作问句默认主体为"它"（＝"它现在能买吗"）走继承
        # ——上轮执行类 + 会话主体在场 → 免复核直达执行；
        # 纯疑问碎片（question 单独在场）不继承
        session = {LAST_INTENT_KEY: "quote_lookup",
                   RECENT_STOCKS_KEY: ["600519"]}
        r = _resolver().resolve_first("现在能买吗", session)
        assert r.source == "context"
        assert r.primary_stock_code == "600519"
        assert not r.needs_confirmation

    def test_sector_tag_with_code_entity_conflicts_to_llm(self):
        # 板块泛称 tag × 股票代码实体＝对象无法判定 → hint 置位
        # 强制复核，不按存疑代码分支 0.8 直达
        stub = _StubLLMAdapter(content=_llm_json(
            "stock_analysis", 0.9, stock_code="HK09988"))
        r = _resolver(stub).resolve_first("板块HK09988")
        assert len(stub.calls) == 1
        assert r.source == "llm"
        assert _codes(r) == ["HK09988"]

    def test_portfolio_quote_class_conflict_triggers_llm(self):
        # 裁决类冲突（契约：冲突意图词交大模型判定拆分还是单一）：
        # "持仓＋股价"＝报数×账户聚合——即使全识别 0.85 也破除豁免。
        # 判据纯语义（tag 级）：词打成 tag 即被看见（"股价"extend 词
        # 同样如此）；词埋进 unknown_token 则视野证兜住。单类共现与
        # 中性疑问不触发
        stub = _StubLLMAdapter(content=_llm_json(
            "portfolio_analysis", 0.9))
        rs = _resolver(stub).resolve("查下我持仓的股价")
        assert len(stub.calls) == 1, "tag 级：extend 报数词×组合类冲突"
        assert _flat(rs)[0].source == "llm"
        assert _flat(rs)[0].intent == WebIntent.PORTFOLIO_ANALYSIS
        stub2 = _StubLLMAdapter(content=_llm_json(
            "portfolio_analysis", 0.9))
        rs2 = _resolver(stub2).resolve("我持仓的市值")
        assert len(stub2.calls) == 1, "报数词×组合类冲突（tag 级）"
        assert _flat(rs2)[0].intent == WebIntent.PORTFOLIO_ANALYSIS
        stub3 = _StubLLMAdapter(content=_llm_json(
            "portfolio_analysis", 0.9))
        _resolver(stub3).resolve_first("我的持仓今天怎么样")
        assert stub3.calls == [], "中性疑问不参与，单类不触发"

    def test_strict_review_subject_unknown_token_and_inherit(self):
        # 宁可不做不可做错（默认复核）：豁免需三证齐全（视野完备＋置信
        # ≥0.8＋无多意图信号），缺一即调 LLM。①主体在场但 unknown_token
        # 陪葬——附带内容同样是未读内容；②上下文继承产物 0.75——LLM
        # 说 followup 则经会话 last_intent 链式转继承，结果同构
        stub = _StubLLMAdapter(content=_llm_json("quote_lookup", 0.9))
        rs = _resolver(stub).resolve("茅台多少钱哈哈哈")
        assert len(stub.calls) == 1, "主体在场但视野残缺，必须复核"
        t = _flat(rs)[0]
        assert t.source == "llm" and _codes(t) == ["600519"],             "复核不丢规则主体（硬信号在基底随行）"

        stub2 = _StubLLMAdapter(content=_llm_json("followup", 0.9))
        r2 = _resolver(stub2).resolve_first(
            "该股现在怎么样",
            {LAST_INTENT_KEY: "stock_analysis", RECENT_STOCKS_KEY: []})
        assert len(stub2.calls) == 1, "继承产物 0.75<0.8，同样复核"
        assert r2.source == "llm" and r2.intent == WebIntent.STOCK_ANALYSIS

    def test_verdict_class_conflict_triggers_llm_review(self):
        # 裁决类竞争触发：报数类数据对象词与强分析类词同场（"多少钱＋
        # 基本面"＝一句两个深度），即使全识别高置信也破除豁免交 LLM 多
        # 意图复核（hint 的 tag 级与文本级判据取或）。共现≠冲突：动宾
        # 搭配（分析＋走势）、同类共现（多少钱＋市盈率，同为报数）、中
        # 性疑问（怎么样）都不触发，规则直达零调用
        stub = _StubLLMAdapter(content=_llm_json(
            "quote_lookup", 0.9, stock_code="600519"))
        rs = _resolver(stub).resolve("茅台多少钱和基本面")
        assert len(stub.calls) == 1, "裁决类竞争破除高置信豁免"
        assert _flat(rs)[0].source == "llm"
        stub2 = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        _resolver(stub2).resolve_first("分析五粮液的走势")
        assert stub2.calls == [], "动宾搭配（分析＋走势）不冲突，不触发"
        _resolver(stub2).resolve_first("茅台多少钱和市盈率")
        assert stub2.calls == [], "同类共现（报数×报数）不冲突，不触发"
        _resolver(stub2).resolve_first("分析下五粮液怎么样")
        assert stub2.calls == [], "中性疑问不参与竞争，不触发"


class TestDeepScanBlockingDefects:
    """切分对齐 / 链式主体 / 矛盾结算 / LLM 闸门 / 平权构造的阻断级
    回归用例。"""

    def test_probe_lowercase_hk_prefix_keeps_tasks_separate(self):
        # 切分对齐：_identify_stock_codes 把小写交易所前缀/后缀形态
        # （hk00700 / 00700.HK）canonical 改写为 HK00700，切分定位按
        # token 文本大小写折叠 + canonical 改写代码的数字核回退，
        # 边界两侧各归各组——代码 token 不跨标点边界错归前一子消息、
        # 两个独立查询不并成一条双标的任务
        rs = _resolver().resolve("查下五粮液，hk00700也看下", {})
        flat_ = _flat(rs)
        assert len(flat_) == 2
        assert [_codes(t) for t in flat_] == [["000858"], ["HK00700"]], \
            "小写 hk 前缀代码不得跨边界并入前一任务"
        rs_suffix = _resolver().resolve("查下五粮液，00700.hk也看下", {})
        assert [_codes(t) for t in _flat(rs_suffix)] == [["000858"], ["HK00700"]], \
            "后缀重排形态（00700.HK→HK00700）经数字核回退同样不并组"

    def test_probe_trailing_followup_fragment_carries_chain_subject(self):
        # 链式主体线程：切分在"然后"token 前下刀，尾随追问片段走分支6
        # 继承前序子消息意图——前序子消息恰收敛一只标的时，追问片段经
        # inherited_stock_code 继承该标的（不折叠架构下片段仍独立成条）
        session: Dict[str, Any] = {RECENT_STOCKS_KEY: ["600519"]}
        rs = _resolver().resolve("分析五粮液，然后呢", session)
        followup = _flat(rs)[-1]
        assert followup.source == "context"
        assert followup.inherited_stock_code == "000858"
        assert followup.primary_stock_code == "000858", \
            "追问片段继承前序子消息标的，不得回退会话陈旧标的（600519）"

    def test_probe_subjectless_followup_fragment_not_executing(self):
        # 无可继承主体的追问片段：链式主体线程以 prev_subject 单一
        # 状态源投影前序状态——比较集合整体继承 stocks、板块前序继承
        # sectors，追问片段绝不以无锚点执行类任务放行（stocks/sectors/
        # 继承码全空会触发无标的 Agent 工作流）。判空口径＝无任何主体
        # 锚点（stocks/sectors/primary 全空）——多标的比较的 primary=''
        # 是设计行为（交执行端处理），不算空主体
        def _anchorless(t):
            return (t.source == "context"
                    and t.intent != WebIntent.GENERAL_CHAT
                    and not (t.primary_stock_code or t.stocks or t.sectors))

        rs = _resolver().resolve("对比茅台和五粮液，然后呢", {})
        assert not any(_anchorless(t) for t in _flat(rs)), \
            "比较前序的追问片段须继承标的集合，不得空主体执行"
        followup = _flat(rs)[-1]
        assert followup.source == "context"
        assert _codes(followup) == ["600519", "000858"], \
            "追问片段整体继承比较集合"

        rs2 = _resolver().resolve("看看白酒板块，然后呢", {})
        assert not any(_anchorless(t) for t in _flat(rs2)), \
            "板块前序的追问片段须继承板块槽位，不得空主体执行"
        followup2 = _flat(rs2)[-1]
        assert followup2.source == "context"
        assert followup2.sectors == ["白酒"], "追问片段继承前序板块槽位"

    def test_probe_contradiction_reply_reopened_as_new_topic(self):
        # 矛盾弃置不产空壳：点名双候选的回复按比较语义整轮判新话题
        # （docstring 契约），确认壳确定性剔除——primary_stock_code 不
        # 回退会话陈旧标的（600519 贵州茅台）
        r = _resolver()
        session: Dict[str, Any] = {"recent_stocks": ["600519"],
                                   "last_intent": "stock_analysis"}
        rs1 = r.resolve("分析阿里巴巴", session)
        apply_resolution_to_session(session, rs1)
        rs2 = r.resolve("BABA和HK09988", session)
        flat_ = _flat(rs2)
        assert len(flat_) == 1
        assert _codes(flat_[0]) == ["BABA", "HK09988"], \
            "点名双候选的回复应按比较语义重新开题，而非丢弃退壳"

    def test_probe_llm_extra_code_after_group_pick_rejected(self):
        # LLM 闸门判据取输入属性快照（had_candidates），不随循环中收缩
        # 的 candidates 变化——组内选中清空列表后，组外库内代码同样
        # 拒收（市场消解同样收缩列表，快照取在市场块之前）
        stub = _StubLLMAdapter(content=_llm_json(
            "quote_lookup", 0.9, stock_codes=["HK09988", "600519"]))
        rs = _resolver(stub).resolve("阿里巴巴哈哈哈", {})
        assert _codes(_flat(rs)[0]) == ["HK09988"], \
            "组内消解后，组外库内代码仍须拒收（闸门判据不得随循环收缩）"

    def test_probe_portfolio_sibling_requires_subject(self):
        # 平权构造：组合语境任务与主体任务共享实体解析——标的歧义时
        # 候选随身（同样转确认，消歧后两任务各自落位），不派生
        # 无 stocks 无候选无确认的空壳执行
        rs = _resolver().resolve("我的阿里巴巴持仓怎么看", {})
        for t in _flat(rs):
            assert (t.intent == WebIntent.GENERAL_CHAT
                    or t.stocks or t.candidates or t.needs_confirmation), \
                "执行类任务必须携带主体（stocks/candidates）或转确认"

    def test_portfolio_sibling_ambiguous_settles_both(self):
        # 消歧轮回填：平权构造下主/兄弟双确认任务各自携带候选——
        # 消歧轮必须同时落位（兄弟无候选则无从回填、空壳执行）
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("我的阿里巴巴持仓怎么看", session)
        assert [(t.intent, set(_candidate_codes(t)), t.needs_confirmation)
                for t in _flat(rs1)] == [
            (WebIntent.STOCK_ANALYSIS, {"BABA", "HK09988"}, True),
            (WebIntent.PORTFOLIO_ANALYSIS, {"BABA", "HK09988"}, True)]
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("港股", session)
        assert [(_codes(t), t.needs_confirmation) for t in _flat(rs2)] == [
            (["HK09988"], False), (["HK09988"], False)]
        apply_resolution_to_session(session, rs2)
        assert session[PENDING_ACTIONS_KEY] == []

    def test_probe_malformed_pending_action_shape_survives(self):
        # pending_action 为字符串等非 dict 形态不得进
        # _normalize_pending_groups 的 pending.get（AttributeError 击穿
        # resolve 主链）。守卫在解析器入口（覆盖 consume 两个调用点）：
        # 畸形被忽略按新消息解析，毒化条目随 apply 覆写自愈
        session: Dict[str, Any] = {
            LAST_RESOLUTIONS_KEY: [[{
                "intent": "stock_analysis", "confidence": 0.85,
                "source": "rule", "needs_confirmation": True,
                "pending_action": "confirm_stock",
                "source_request": "分析阿里巴巴",
            }]],
        }
        rs = _resolver().resolve("港股", session)
        assert rs, "畸形 pending_action 形状应被忽略（按新消息解析），不得击穿 resolve"


# =========================================================================
# 多意图协议实体完整性 / 消歧回复画像 / 确认状态迁移 / 载荷健壮性
# =========================================================================


class TestDeepScanRound3Defects:
    """多意图数组实体协议与确认链路完整性的回归用例：

    - 多意图数组实体完整性：单元素数组继承完整规则基底，多元素经
      孤儿核算（_reclaim_orphan_entities）回收未认领实体，被消解组
      的余留候选不回挂；
    - 消歧回复画像：fresh 的证据集是 stocks+candidates（_reply_profile），
      has_content 的意图信号是 token 级 tag 查表（extend 词池动作词
      同权可见）；
    - 确认状态迁移：全组落定时残留 unresolved_names 一并清空（空
      groups 的澄清轮结构上不可满足）；
    - 载荷健壮性：__post_init__ 对缺 code 的 dict 候选按
      _stock_from_payload 同口径跳过，不裸下标击穿构造。
    """

    def test_probe_intents_array_null_code_drops_ambiguity(self):
        # 单元素 intents 数组继承完整规则基底——LLM 按"代码无把握返回
        # null"的协议约束返回 null stock_code 时，规则侧识别的跨市场
        # 歧义候选随行保留并转确认（与单对象协议同语义）
        stub = _StubLLMAdapter(content=json.dumps({"intents": [{
            "intent": "stock_analysis", "confidence": 0.9, "market": None,
            "stock_code": None, "stock_codes": [], "sectors": [],
            "unresolved_names": [],
        }], "note": "x"}))
        # 空格分隔的未登录词触发 LLM 复核，规则侧保留阿里巴巴双候选
        t = _flat(_resolver(stub).resolve("分析阿里巴巴 叭叭叭", {}))[0]
        assert t.needs_confirmation, "歧义候选未随 LLM null 代码消失，须转确认"
        assert {c.code for c in t.candidates} == {"BABA", "HK09988"}

    def test_probe_intents_array_null_code_drops_resolved_stock(self):
        # 单元素 intents 数组未回填代码时，规则侧已解析的确定实体
        # （茅台→600519）随行保留——空标的执行任务不放行
        stub = _StubLLMAdapter(content=json.dumps({"intents": [{
            "intent": "stock_analysis", "confidence": 0.9, "market": None,
            "stock_code": None, "stock_codes": [], "sectors": [],
            "unresolved_names": [],
        }], "note": "x"}))
        t = _flat(_resolver(stub).resolve("分析茅台 叭叭叭", {}))[0]
        assert _codes(t) == ["600519"], "规则已解析实体不因 LLM 漏填代码丢失"

    def test_llm_multi_item_orphan_stock_reclaimed(self):
        # 多元素孤儿核算：LLM 拆分后逐项漏填代码（仅板块项带 sectors），
        # 规则侧已解析实体（600519）挂载到首个无实体执行任务——实体
        # 不因协议拆分静默蒸发
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "quote_lookup", "confidence": 0.9, "market": None,
             "stock_code": None, "stock_codes": [], "sectors": [],
             "unresolved_names": []},
            {"intent": "sector_analysis", "confidence": 0.9, "market": None,
             "stock_code": None, "stock_codes": [], "sectors": ["医药"],
             "unresolved_names": []},
        ]}, ensure_ascii=False))
        # 未登录词以空格分隔（紧贴会令 DFS 整段放弃，规则实体陪葬）
        flat_ = _flat(_resolver(stub).resolve("看下茅台股价和医药板块 叭"))
        assert _codes(flat_[0]) == ["600519"], "孤儿实体挂载到首个空执行任务"
        assert flat_[1].sectors == ["医药"]

    def test_llm_multi_item_group_resolution_not_orphaned(self):
        # 组清账口径：LLM 在元素中消解歧义组（HK09988 落位）后，兄弟
        # 候选（BABA）属被消解组余留而非未决歧义——不作为孤儿回挂，
        # 不产生二次歧义确认
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "stock_analysis", "confidence": 0.9, "market": None,
             "stock_code": "HK09988", "stock_codes": [], "sectors": [],
             "unresolved_names": []},
            {"intent": "sector_analysis", "confidence": 0.9, "market": None,
             "stock_code": None, "stock_codes": [], "sectors": ["医药"],
             "unresolved_names": []},
        ]}, ensure_ascii=False))
        # 未登录词以空格分隔：规则侧须真正提取阿里巴巴歧义（否则测试空转）
        flat_ = _flat(_resolver(stub).resolve("分析阿里巴巴和医药板块 叭"))
        assert _codes(flat_[0]) == ["HK09988"]
        assert all(not t.candidates for t in flat_)
        assert not any(t.needs_confirmation for t in flat_)

    def test_probe_confirm_reply_sibling_ambiguous_mention_dropped(self):
        # '平安银行，阿里巴巴呢'——前段正常消歧，后段新歧义提及
        # （无 stocks、'呢'非意图词）经 candidates 出圈画像（fresh）
        # 保留为自己的任务并转确认，不被判纯消歧片段丢弃
        session: Dict[str, Any] = {}
        rs = _resolver().resolve("分析平安", session)
        apply_resolution_to_session(session, rs)
        flat_ = _flat(_resolver().resolve("平安银行，阿里巴巴呢", session))
        assert len(flat_) == 2, "消歧落位任务 + 新歧义提及任务都应保留"
        assert any(t.needs_confirmation and t.candidates for t in flat_), \
            "新提及的阿里巴巴歧义须走自己的确认"

    def test_probe_confirm_reply_fetch_verb_intent_overridden(self):
        # '查一下平安银行'作为消歧回复时，'查'（extend 词池
        # action_quote_fetch）经 token 级 tag 查表构成 has_content 信号
        # → 保留为任务——原任务消解落位（stock_analysis）＋ 新任务
        # （quote_lookup）并存，取数语义不被上轮意图静默覆盖
        session: Dict[str, Any] = {}
        rs = _resolver().resolve("分析平安", session)
        apply_resolution_to_session(session, rs)
        flat_ = _flat(_resolver().resolve("查一下平安银行", session))
        assert len(flat_) == 2
        assert flat_[0].intent == WebIntent.STOCK_ANALYSIS, "原任务消解落位"
        assert _codes(flat_[0]) == ["000001"]
        assert not flat_[0].needs_confirmation
        assert flat_[1].intent == WebIntent.QUOTE_LOOKUP, "取数动词按新任务保留"
        assert _codes(flat_[1]) == ["000001"]

    def test_probe_resolved_task_reblocked_by_unsatisfiable_confirmation(self):
        # '分析平安和SH600999'首轮歧义确认；'平安银行'消解落定后残留
        # unresolved_names 随全组落定一并清空——不被结构上不可满足的
        # 坏代码澄清（空 groups pending）再次短路，消解成果 000001
        # 正常执行
        session: Dict[str, Any] = {}
        rs = _resolver().resolve("分析平安和SH600999", session)
        apply_resolution_to_session(session, rs)
        flat_ = _flat(_resolver().resolve("平安银行", session))
        assert len(flat_) == 1 and _codes(flat_[0]) == ["000001"]
        assert not flat_[0].needs_confirmation, \
            "歧义已消解、标的已落位，不得被无法满足的坏代码澄清再次阻断"

    def test_probe_candidates_dict_missing_code_crashes(self):
        # 缺 code 的 dict 候选按 _stock_from_payload 同口径跳过，不裸
        # 下标 c["code"] 击穿构造；携带 code 的正常 dict 候选仍完整
        # 转换（防过度过滤的对照断言）
        r = WebIntentResolution(
            intent=WebIntent.STOCK_ANALYSIS, confidence=0.9,
            candidates=[{"name": "某股"}])
        assert r.candidates == [], "缺 code 的 dict 候选应宽容跳过，不得击穿构造"
        r2 = WebIntentResolution(
            intent=WebIntent.STOCK_ANALYSIS, confidence=0.9,
            candidates=[{"code": "600519", "name": "贵州茅台", "market": "a"},
                        {"name": "无名"}])
        assert r2.candidates == [Stock("600519", "贵州茅台", "a")]


class TestReviewRound4BlockingDefects:
    """无锚点执行守卫的回归钉子——谓词与
    test_probe_subjectless_followup_fragment_not_executing 同源：
    执行类任务不得无锚点放行。"""

    @staticmethod
    def _anchorless(t: WebIntentResolution) -> bool:
        return (t.source in ("context", "llm")
                and t.intent != WebIntent.GENERAL_CHAT
                and not (t.primary_stock_code or t.stocks or t.sectors
                         or t.candidates or t.unverified_codes))

    def test_probe_chain_ambiguous_prev_followup_inherits_candidates(self):
        # 前序片段主体歧义（stocks 空、candidates 非空）时，链式主体
        # 线程按 _ChainSubject 三形态（stocks/sectors/ambiguous）投影：
        # 歧义前序的候选组随行继承，与主体任务共待同一次消歧
        rs = _resolver().resolve("分析阿里，然后它怎么样", {})
        flat_ = _flat(rs)
        assert len(flat_) == 2
        assert not any(self._anchorless(t) for t in flat_), \
            "前序主体歧义时，追问片段不得以无锚点执行类任务放行"
        followup = flat_[-1]
        assert followup.source == "context"
        assert set(_candidate_codes(followup)) == {"HK09988", "BABA"}, \
            "追问片段继承前序歧义候选，与主体任务共待同一次消歧"
        # 消歧轮双任务同时落位（不折叠架构下的同候选结算）
        session: Dict[str, Any] = {}
        apply_resolution_to_session(session, rs)
        rs2 = _resolver().resolve("港股", session)
        assert [(_codes(t), t.needs_confirmation) for t in _flat(rs2)] == [
            (["HK09988"], False), (["HK09988"], False)], \
            "一次消歧同时落位主体任务与追问片段"

    def test_probe_llm_followup_promotion_keeps_anchor(self):
        # LLM followup 伪标签转继承可产出无锚点执行类任务——规则路径
        # 分支6 有 prev_subject 继承，LLM 合并路径由 _finalize_
        # confirmation 的无锚点执行类守卫（所有出口的单一 choke point）
        # 收口：缺一切主体锚点时转 low_confidence 澄清。板块轮不写
        # recent_stocks，会话级追问经 LLM 兜底后 sectors/stocks 全空
        # → 守卫收口
        stub = _StubLLMAdapter(content=json.dumps(
            {"intents": [{"intent": "followup", "confidence": 0.9}]},
            ensure_ascii=False))
        rs = _resolver(stub).resolve(
            "再展开讲讲", {LAST_INTENT_KEY: "sector_analysis"})
        flat_ = _flat(rs)
        assert len(flat_) == 1
        t = flat_[0]
        assert (t.intent == WebIntent.GENERAL_CHAT
                or t.needs_confirmation
                or t.stocks or t.sectors), \
            "followup 继承产物无任何主体锚点时不得以执行类任务放行"

    def test_probe_llm_sparse_multi_intent_fill_not_stale_anchored(self):
        # 多元素拆分的基底重置一并清 inherited_stock_code——LLM 稀疏
        # 填充（第二元素 stock_code=null）时该元素不得静默回退会话陈旧
        # 标的（000858 五粮液）作 primary（单任务解读产物不随多元素
        # 拆分残留）；未填实体的执行类元素由无锚点守卫转确认
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "quote_lookup", "confidence": 0.9,
             "stock_code": "600519"},
            {"intent": "stock_analysis", "confidence": 0.9,
             "stock_code": None},
        ]}, ensure_ascii=False))
        session: Dict[str, Any] = {RECENT_STOCKS_KEY: ["000858"]}
        flat_ = _flat(_resolver(stub).resolve("看一下茅台股价和基本面", session))
        assert len(flat_) == 2
        second = flat_[1]
        assert second.primary_stock_code != "000858", \
            "拆分元素不得静默回退会话陈旧标的充当主体"
        assert (second.stocks or second.needs_confirmation), \
            "未填实体的执行类元素必须携带自身标的或转确认，不得无锚点放行"

    def test_probe_llm_followup_item_inherits_prev_subject(self):
        # 数组内 followup 主体继承：followup 元素延续前一项意图时
        # 主体槽空 → 随行补齐前一项 stocks/sectors（与规则分支6
        # 链式继承同构），不落成无锚点执行任务
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "quote_lookup", "confidence": 0.9,
             "stock_code": "600519"},
            {"intent": "followup", "confidence": 0.9},
        ]}, ensure_ascii=False))
        flat_ = _flat(_resolver(stub).resolve("看一下茅台股价和基本面", {}))
        assert [t.intent for t in flat_] == [
            WebIntent.QUOTE_LOOKUP, WebIntent.QUOTE_LOOKUP]
        assert _codes(flat_[1]) == ["600519"], \
            "followup 元素继承前一项主体标的"

    def test_probe_requeue_round_finalizes_kept_tasks(self):
        # 确认消费的重建轮：短路返回时 recovered 组原样随行（保住
        # confirmed 累积），kept 组按对象身份识别并照常收尾——本轮
        # kept 新任务的歧义/低置信确认当轮成立（裸"机器人"0.5 →
        # low_confidence 确认）
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析阿里，分析平安", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("港股，再看看机器人", session)
        flat_ = _flat(rs2)
        robot = next(
            (t for t in flat_ if t.intent == WebIntent.SECTOR_ANALYSIS), None)
        assert robot is not None, "kept 新任务（机器人板块双解）应在链上"
        assert robot.needs_confirmation, \
            "requeue 轮 kept 任务的低置信确认不得延迟一轮浮出"
        assert any(t.needs_confirmation for t in flat_), \
            "平安组未解，整链仍须短路等待"


class TestReviewRound5BlockingDefects:
    """确认消费轮收尾契约 / 继承守卫 / 组结构不变量：

    - 确认消费后的 recovered 任务不重过第六步收尾——LLM 来源任务
      （≤0.75 低于豁免线）不被再次送审，用户的消歧选择不被 LLM
      二次意见污染/改判，低置信任务不被再次短路（确认轮的置信度由
      用户选择背书）；
    - 继承守卫对动作词类不偏待：非 request 动作词（能买/多少钱）
      携带未消化主语信号（裸数字/存疑代码）时不继承，用户显式指称
      的标的不被静默丢弃；
    - 确认消费保持"组=子消息"不变量：同子消息兄弟任务不各自触发
      组级 LLM 枚举（同一原文不重复枚举产出重复任务）。
    """

    # ---- 确认消费后的 recovered 任务不重过收尾 ----

    def test_probe_resolved_task_not_re_adjudicated_by_llm(self):
        # LLM 路径产生的歧义确认任务（source=llm，0.75<0.8 豁免线）被
        # "港股"消解后，不得对原消息重跑 LLM 兜底——二次意见的
        # stock_code=BABA 会并入 stocks，污染用户已确认的 HK09988
        stub1 = _StubLLMAdapter(content=_llm_json("stock_analysis", 0.9))
        resolver = WebIntentResolver(llm_adapter=stub1)
        session: Dict[str, Any] = {}
        rs1 = resolver.resolve("阿里巴巴哈哈哈", session)
        assert rs1[0][0].needs_confirmation
        assert rs1[0][0].source == "llm"
        apply_resolution_to_session(session, rs1)

        stub2 = _StubLLMAdapter(content=_llm_json(
            "stock_analysis", 0.9, stock_code="BABA"))
        rs2 = WebIntentResolver(llm_adapter=stub2).resolve("港股", session)
        assert stub2.calls == [], "已确认任务不得重跑 LLM 兜底"
        flat_ = _flat(rs2)
        assert len(flat_) == 1
        assert _codes(flat_[0]) == ["HK09988"], \
            "用户选定标的不被 LLM 二次意见污染"
        assert not flat_[0].needs_confirmation

    def test_probe_resolved_low_confidence_task_not_reblocked(self):
        # 低置信（0.55）LLM 歧义任务消解后：用户已显式选定标的，
        # 不得再被 low_confidence 二次短路——确认轮的置信度由用户
        # 选择背书（与 pending_actions 回退路径的 confirmation/0.9
        # 契约同构）
        stub1 = _StubLLMAdapter(content=_llm_json("stock_analysis", 0.55))
        resolver = WebIntentResolver(llm_adapter=stub1)
        session: Dict[str, Any] = {}
        rs1 = resolver.resolve("阿里巴巴哈哈哈", session)
        assert rs1[0][0].reason == "ambiguous_stock_name"
        apply_resolution_to_session(session, rs1)

        stub2 = _StubLLMAdapter(content=_llm_json("stock_analysis", 0.55))
        rs2 = WebIntentResolver(llm_adapter=stub2).resolve("港股", session)
        assert stub2.calls == []
        flat_ = _flat(rs2)
        assert _codes(flat_[0]) == ["HK09988"]
        assert not flat_[0].needs_confirmation, "消解轮不得再次确认"

    def test_probe_recovered_llm_sibling_not_re_reviewed(self):
        # 上轮短路链中的非确认兄弟任务（LLM 来源，未执行）随 survivors
        # 返回时同样不得重过收尾——对上轮子消息重跑 LLM 属重复裁决，
        # 且非确定性的二次输出可能改掉上轮已敲定的任务形态
        stub1 = _StubLLMAdapter(content=_llm_json("stock_analysis", 0.9))
        resolver = WebIntentResolver(llm_adapter=stub1)
        session: Dict[str, Any] = {}
        rs1 = resolver.resolve("分析阿里，再看看茅台+哈哈哈", session)
        assert rs1[0][0].needs_confirmation  # 阿里歧义 → 整链短路
        assert rs1[1][0].source == "llm" and not rs1[1][0].needs_confirmation
        apply_resolution_to_session(session, rs1)

        stub2 = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        rs2 = WebIntentResolver(llm_adapter=stub2).resolve("港股", session)
        assert stub2.calls == [], "recovered 任务不得重过 LLM 收尾"
        flat_ = _flat(rs2)
        assert [(t.intent, _codes(t)) for t in flat_] == [
            (WebIntent.STOCK_ANALYSIS, ["HK09988"]),
            (WebIntent.STOCK_ANALYSIS, ["600519"]),
        ]

    # ---- 继承守卫：未消化信号面前宁可不做不可做错 ----

    def test_probe_action_word_with_bare_digit_not_inherited(self):
        # "现在能买09932吗"：动作词（能买）＋未消化裸数字（09932 是
        # HK 短码形态）——不得继承，09932 不被静默丢弃、不对 600519
        # 而非用户指称的 09932 作答。与 test_bare_number_subject_
        # not_inherited（带 request 词）同语义：宁可低置信也不做错
        session = {LAST_INTENT_KEY: "stock_analysis",
                   RECENT_STOCKS_KEY: ["600519"]}
        r = _resolver().resolve_first("现在能买09932吗", session)
        assert r.source == "rule", "未消化数字不得被继承吸收"
        assert r.intent == WebIntent.GENERAL_CHAT

    def test_probe_action_word_with_unknown_code_not_inherited(self):
        # "SOFI能买吗"：存疑代码是带 tag 的未消化信号，不得当作追问
        # 继承——应走存疑代码透传分支（与 test_unknown_code_subject_
        # not_inherited 同语义）
        session = {LAST_INTENT_KEY: "stock_analysis",
                   RECENT_STOCKS_KEY: ["600519"]}
        r = _resolver().resolve_first("SOFI能买吗", session)
        assert r.source == "rule"
        assert r.intent == WebIntent.STOCK_ANALYSIS
        assert r.unverified_codes == ["SOFI"], "存疑代码不得被继承静默丢弃"
        assert not r.needs_confirmation

    # ---- 确认消费保持"组=子消息"不变量 ----

    @staticmethod
    def _multi_intent_payload() -> str:
        return json.dumps({"intents": [
            {"intent": "stock_analysis", "confidence": 0.9,
             "stock_code": "600519"},
            {"intent": "sector_analysis", "confidence": 0.9,
             "sectors": ["医药"]},
        ]}, ensure_ascii=False)

    def test_probe_interacted_kept_siblings_not_split(self):
        # 消解轮 kept 的同子消息兄弟任务（个股＋板块）被拍平成单例组
        # → 各自触发组级 LLM 枚举同一原文两遍 → 任务重复。组级枚举
        # 契约（一条子消息至多一次）必须跨确认消费保持
        stub = _StubLLMAdapter(content=self._multi_intent_payload())
        resolver = WebIntentResolver(llm_adapter=stub)
        session: Dict[str, Any] = {}
        rs1 = resolver.resolve("分析阿里", session)
        apply_resolution_to_session(session, rs1)

        rs2 = resolver.resolve("港股，分析茅台和医药板块+哈哈哈", session)
        assert len(stub.calls) == 1, "同一子消息至多一次多意图枚举"
        flat_ = _flat(rs2)
        assert [(t.intent, _codes(t), t.sectors) for t in flat_] == [
            (WebIntent.STOCK_ANALYSIS, ["HK09988"], []),
            (WebIntent.STOCK_ANALYSIS, ["600519"], []),
            (WebIntent.SECTOR_ANALYSIS, [], ["医药"]),
        ], "兄弟任务不得因组结构破坏而重复产出"

    def test_probe_zero_interaction_reply_groups_preserved(self):
        # 零交互早退同样按组返回：子消息的兄弟任务保持同组，一次
        # 枚举；拍平成单例组会两遍枚举同一原文（4 任务＋2 次调用）
        stub = _StubLLMAdapter(content=self._multi_intent_payload())
        resolver = WebIntentResolver(llm_adapter=stub)
        session: Dict[str, Any] = {}
        rs1 = resolver.resolve("分析阿里", session)
        apply_resolution_to_session(session, rs1)

        rs2 = resolver.resolve("分析茅台和医药板块+哈哈哈", session)
        assert len(stub.calls) == 1, "零交互轮同样一条子消息至多一次枚举"
        flat_ = _flat(rs2)
        assert [(t.intent, _codes(t), t.sectors) for t in flat_] == [
            (WebIntent.STOCK_ANALYSIS, ["600519"], []),
            (WebIntent.SECTOR_ANALYSIS, [], ["医药"]),
        ], "零交互返回不得拆散兄弟任务导致重复产出"


# =========================================================================
# 量词闸门与组内集合提供者豁免 — 已修复缺陷的常规回归用例。
# =========================================================================


class TestReviewRound6BlockingDefects:
    """量词闸门与组内集合提供者豁免：

    - 量词闸门只拦无语义标签的量词 token：``_token_facts`` 裸数字
      四重闸门的排除条件按"下一 token 无 tag 且首字符 ∈ 量词集"判定
      ——已打标关键词（"股价"＝TAG_ACTION_QUOTE）不被首字符"股"
      误伤，"600519股价"类取数句直达行情查询（无 LLM 部署形态下
      无纠错机会，不得静默误路由闲聊）；
    - 管道拆分产物 × 组内集合提供者：``LLM_SYSTEM_PROMPT`` 的管道
      拆分原理要求"泛指持仓×动作词"拆出无需填代码的动作元素——收尾
      以组为单位识别集合提供者（组内存在 portfolio_analysis），空
      实体执行任务主体＝提供者的账户标的集合输出（任务间主体引用），
      无锚点守卫与低置信守卫对其豁免（转无选项确认＝用户任何回复
      无法消解的死锁）；无提供者的空实体任务照常拦截。
    """

    # ---- 量词闸门不误伤已打标数据词 ----

    def test_probe_code_directly_before_quote_keyword_promotes(self):
        # "600519股价"：股价是 TAG_ACTION_QUOTE 已打标关键词（非量词），
        # 四重闸门应放行提升——代码+数据词的取数句直达行情查询，
        # 不得静默误路由闲聊（无 LLM 形态下无纠错机会）
        r = _resolver().resolve_first("600519股价")
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert _codes(r) == ["600519"]

    def test_probe_fetch_verb_code_quote_promotes(self):
        # "查600519股价"：取数动词 + 代码 + 数据词的最短取数句，
        # 同样直达行情查询
        r = _resolver().resolve_first("查600519股价")
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert _codes(r) == ["600519"]

    def test_probe_amount_and_tagged_keyword_gate_regression(self):
        # 量词闸门边界钉子：未打标的量词 token（"元"/"万元"）继续阻止
        # 提升——金额/数量语义不因闸门收紧而放行；对照"的"间隔形态
        # 不受量词闸门影响
        r = _resolver().resolve_first("我有300750万元")
        assert r.stocks == [] and r.intent == WebIntent.GENERAL_CHAT
        r2 = _resolver().resolve_first("600519的股价")
        assert r2.intent == WebIntent.QUOTE_LOOKUP and _codes(r2) == ["600519"]

    # ---- 组内集合提供者豁免空实体动作元素 ----

    def test_probe_pipeline_split_action_element_executes(self):
        # prompt 管道拆分原理的直接产物（prompt 示例原句）："查下我持仓
        # 的股票的股价"＝〔portfolio_analysis（取集合）＋quote_lookup（主体
        # ＝前一意图的集合，无需填代码）〕。动作元素主体是链内主体引用
        # 而非空缺——组内存在集合提供者即标记可执行，不得转无选项确认
        # 整链死锁（用户任何回复都无法消解）
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "portfolio_analysis", "confidence": 0.9},
            {"intent": "quote_lookup", "confidence": 0.9},
        ], "note": "泛指主体拆取持仓＋报价"}, ensure_ascii=False))
        rs = _resolver(stub).resolve("查下我持仓的股票的股价")
        flat_ = _flat(rs)
        assert [t.intent for t in flat_] == [
            WebIntent.PORTFOLIO_ANALYSIS, WebIntent.QUOTE_LOOKUP]
        assert not any(t.needs_confirmation for t in flat_), \
            "拆分动作元素主体＝前序泛指集合，不得整链死锁"

    def test_probe_provider_exempts_low_confidence_element_too(self):
        # 豁免必须覆盖低置信出口：提供者在场时空实体动作元素即使置信度
        # <0.6 也不转确认（无选项确认同样是死锁形态），主体引用不受
        # 意图置信度影响
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "portfolio_analysis", "confidence": 0.9},
            {"intent": "stock_analysis", "confidence": 0.5},
        ], "note": "泛指主体拆取持仓＋分析"}, ensure_ascii=False))
        rs = _resolver(stub).resolve("分析我所有的持仓股票")
        flat_ = _flat(rs)
        assert not any(t.needs_confirmation for t in flat_)

    def test_probe_no_provider_empty_element_still_confirms(self):
        # 豁免边界钉子：组内没有集合提供者时，空实体执行类任务照常转
        # low_confidence 待澄清——守卫对"LLM 判执行类但消息无主体"等来
        # 源不变
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "stock_analysis", "confidence": 0.9},
        ], "note": "无实体单元素"}, ensure_ascii=False))
        rs = _resolver(stub).resolve("分析一下")
        flat_ = _flat(rs)
        empty_executing = [t for t in flat_
                           if t.intent == WebIntent.STOCK_ANALYSIS
                           and not (t.stocks or t.candidates or t.sectors
                                    or t.unresolved_names
                                    or t.unverified_codes)]
        assert empty_executing, "前置：stub 场景应含空实体执行任务"
        assert all(t.needs_confirmation for t in empty_executing)

    def test_probe_provider_group_still_confirms_ambiguity(self):
        # 豁免只作用于空实体守卫：同组含提供者时，携带歧义候选的其他
        # 任务照常走歧义确认（不得因提供者在场放行错误标的）
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "portfolio_analysis", "confidence": 0.9},
            {"intent": "stock_analysis", "confidence": 0.9,
             "stock_codes": ["HK09988", "BABA"]},
        ], "note": "组合＋歧义标的"}, ensure_ascii=False))
        rs = _resolver(stub).resolve("查下我持仓的股票，再分析阿里巴巴")
        flat_ = _flat(rs)
        ambiguous = [t for t in flat_ if t.candidates]
        assert ambiguous and all(t.needs_confirmation for t in ambiguous)

    def test_probe_rule_path_pipeline_split_input_executes(self):
        # 对照钉子：无 LLM 形态同一输入规则直达单一组合任务可执行
        # ——同一请求不因走 LLM 兜底反而死锁
        r = _resolver().resolve_first("查下我持仓的股票的股价")
        assert r.intent == WebIntent.PORTFOLIO_ANALYSIS
        assert not r.needs_confirmation


# =========================================================================
# 跨轮追问继承 / last_intent 落点 / 会话形状健壮性 — 常规回归用例。
# =========================================================================


class TestReviewRound7BlockingDefects:
    """跨轮追问主体继承 / last_intent 落点 / 会话形状健壮性：

    - 跨轮追问主体继承：分支6 的主体继承（sectors / 多标的 stocks /
      歧义组）由 resolve 以 _session_chain_subject 播种初值——上一
      已执行轮的落点主体（与 last_intent 落点同规则同任务，短路轮
      排除），跨轮与同消息片段走同一条继承路径，"继续"一律指向
      last_intent 的任务（板块/指数任务不写 recent_stocks，无播种
      的追问会退无选项确认死锁）；
    - last_intent 记对话落点（最后一个主体任务为执行类的组），与
      recent_stocks 头插"后写胜出"同源——意图与标的锚点出自同一
      任务，前置寒暄/拒绝词碎片不把真正的执行意图挤出；
    - 会话形状异常不击穿：resolve 读点单点归一（recent_stocks 非
      字符串元素 / current_stock_code 非文本按缺失处理），与写侧
      apply_outcome 的 isinstance(str) 过滤对称。
    """

    # ---- 跨轮追问主体继承 ----

    def test_probe_cross_round_sector_followup_inherits_subject(self):
        # "分析白酒板块"（正常执行）→"继续"：追问继承上轮落点主体的
        # 板块槽位继续板块分析，不回无选项确认让用户无解
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析白酒板块", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("继续", session)
        t = _flat(rs2)[0]
        assert t.source == "context"
        assert t.intent == WebIntent.SECTOR_ANALYSIS
        assert t.sectors == ["白酒"], "跨轮追问须继承上轮板块槽位"
        assert not t.needs_confirmation, "继承主体后不得回无选项确认"

    def test_probe_cross_round_index_followup_inherits_subject(self):
        # "查一下上证指数" → "继续"：继续查上证指数
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("查一下上证指数", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("继续", session)
        t = _flat(rs2)[0]
        assert t.source == "context"
        assert t.intent == WebIntent.QUOTE_LOOKUP
        assert t.sectors == ["上证"], "跨轮追问须继承上轮指数槽位"
        assert not t.needs_confirmation

    def test_probe_cross_round_comparison_followup_inherits_stock_set(self):
        # "对比茅台和五粮液" → "继续呢"：整体继承两只标的的比较语义，
        # 不退化为 recent_stocks[0] 单股
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("对比茅台和五粮液", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("继续呢", session)
        t = _flat(rs2)[0]
        assert t.source == "context"
        assert set(_codes(t)) == {"600519", "000858"}, \
            "跨轮追问须继承比较集合，不得静默丢失一只"

    def test_probe_no_projection_session_followup_still_guarded(self):
        # 边界钉子：无 last_resolutions 投影的会话（新会话/手工构造）
        # 不播种主体——追问仍由无锚点守卫收口，种子只来自已执行轮的
        # 会话投影
        session = {LAST_INTENT_KEY: "sector_analysis"}
        t = _flat(_resolver().resolve("继续", session))[0]
        assert t.source == "context"
        assert t.needs_confirmation and t.reason == "low_confidence"

    # ---- last_intent 记对话落点 ----

    def test_probe_leading_chat_fragment_does_not_pollute_last_intent(self):
        # 前置寒暄碎片不得把执行意图挤出 last_intent——last_intent 记
        # 对话落点（最后一个主体任务为执行类的组）
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("你好，分析茅台", session)
        apply_resolution_to_session(session, rs1)
        assert session[LAST_INTENT_KEY] == "stock_analysis", \
            "前置寒暄碎片不得把执行意图挤出 last_intent"
        rs2 = _resolver().resolve("继续", session)
        t = _flat(rs2)[0]
        assert t.intent == WebIntent.STOCK_ANALYSIS and t.source == "context"
        assert t.inherited_stock_code == "600519"

    def test_probe_landing_intent_from_last_executing_group(self):
        # 顺序叙事两任务（报价→分析）后，last_intent＝对话落点（最后的
        # 分析任务）——"继续"延续分析，且意图与标的锚点出自同一任务，
        # 不产生"任务1意图×任务2标的"的错配
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("查一下茅台股价，然后分析五粮液", session)
        apply_resolution_to_session(session, rs1)
        assert session[LAST_INTENT_KEY] == "stock_analysis"
        rs2 = _resolver().resolve("继续", session)
        t = _flat(rs2)[0]
        assert t.intent == WebIntent.STOCK_ANALYSIS
        assert t.inherited_stock_code == "000858"

    def test_probe_trailing_light_task_pairs_intent_with_subject(self):
        # 落点规则的对偶钉子：尾随轻任务（顺带查价）成为落点时，意图与
        # 标的配套（都是旁支任务的对象），而非"主诉求意图×旁支标的"的
        # 交叉错配。注意连接词用"然后"而非"顺便"："顺便"不在任何词池，
        # 其开头的片段 DFS 全覆盖失败整段陪葬（茅台/股价均不提取），
        # 是分词层"宁可不做"的既定保守行为
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析五粮液的基本面，然后查下茅台股价", session)
        apply_resolution_to_session(session, rs1)
        assert session[LAST_INTENT_KEY] == "quote_lookup"
        rs2 = _resolver().resolve("继续", session)
        t = _flat(rs2)[0]
        assert t.intent == WebIntent.QUOTE_LOOKUP
        assert t.inherited_stock_code == "600519"

    def test_probe_pure_chat_round_keeps_chat_last_intent(self):
        # 边界钉子：纯闲聊轮（无任何执行类任务）last_intent 照记
        # general_chat——落点规则只跳过闲聊碎片，不改变纯闲聊轮的口径
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("你好呀", session)
        apply_resolution_to_session(session, rs1)
        assert session[LAST_INTENT_KEY] == "general_chat"

    # ---- 会话形状异常不击穿（读点类型归一） ----

    def test_probe_malformed_recent_stocks_element_does_not_crash(self):
        # recent_stocks 混入非字符串元素（裸数字）时，低置信消息触发
        # LLM 兜底不抛 AttributeError——非字符串元素按缺失处理（归一
        # 为空继承码），与写侧过滤口径对齐
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        session = {RECENT_STOCKS_KEY: [600519]}
        rs = _resolver(stub).resolve("它怎么样呢", session)
        t = _flat(rs)[0]
        assert isinstance(t.inherited_stock_code, str)

    def test_probe_malformed_current_stock_code_does_not_crash(self):
        # 对偶入口：request_context 的 current_stock_code 为非字符串
        # 真值（裸数字）时同形归一为空继承码，不带病透传
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        rs = _resolver(stub).resolve("它怎么样呢", {}, {"current_stock_code": 600519})
        t = _flat(rs)[0]
        assert isinstance(t.inherited_stock_code, str)

    def test_probe_non_serializable_recent_element_does_not_crash(self):
        # 完整面：不可序列化元素（set/对象）会让 LLM 请求体的
        # json.dumps（try 外）以 TypeError 击穿——请求体只透传字符串
        # 元素，其余按缺失处理
        stub = _StubLLMAdapter(content=_llm_json("general_chat", 0.9))
        rs = _resolver(stub).resolve("它怎么样呢", {RECENT_STOCKS_KEY: [{1, 2}]})
        t = _flat(rs)[0]
        assert isinstance(t.inherited_stock_code, str)


# =========================================================================
# 确认回复的内容保留契约 — 纯消歧片段判定（板块/未识别内容不丢弃）。
# =========================================================================


class TestReviewRound8BlockingDefects:
    """确认回复中自带新请求的保留契约（``_reply_profile`` 的 has_content）：

    - 板块子消息是对象承载的请求：系统问"阿里巴巴指港股还是美股"，
      用户答"港股，医药板块"，医药板块的请求不因确认消费在轮而
      静默消失（同一句"医药板块"在没有待确认问题时能正常识别成
      板块分析，对照钉子见 TestSectorSlotFilling）——板块族 tag
      （板块/行业/赛道/概念…）与指数词同层级，都在自带语义集合
      ``_COMPETING_TAGS`` 中；
    - 未识别内容计入自带语义：用户答"港股，茅台和医药板块咋样呢"，
      第二段因词池外的字（咋）整段无法全覆盖分词（分词层"宁可
      不做"的既定保守行为，实体与意图词全部埋进 unknown token）——
      正常轮次这类消息交大模型复核，确认消费轮同样保留（视野轴
      兜底只在任务被保留进第六步后才可能发生）。
    判定规则＝"子消息判为纯消歧答案的必要条件是全部内容都落在待确认
    候选空间之内，消歧了才丢弃、否则保留作为新任务走完整 rule+LLM
    判定流程；充当过消歧证据不排斥请求角色"。两类信号在唯一定义点
    ``_reply_profile`` 单点补齐。
    """

    # ---- 确认回复中的板块子消息不当纯消歧片段丢弃 ----

    def test_probe_sector_submessage_survives_confirm_reply(self):
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析阿里巴巴", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("港股，医药板块", session)
        flat_ = _flat(rs2)
        sector = [t for t in flat_ if t.sectors == ["医药"]]
        assert sector, "确认消解轮不得丢弃回复中新带的板块请求子消息"
        assert sector[0].intent == WebIntent.SECTOR_ANALYSIS
        # 消歧主体照常落位（对照组：丢弃的只是不该丢弃的部分）
        resolved = [t for t in flat_ if t.source == "confirmation"]
        assert _codes(resolved[0]) == ["HK09988"]

    # ---- 确认回复中的未识别内容不静默丢弃 ----

    def test_probe_unread_submessage_survives_confirm_reply(self):
        # "咋"在词池外：第二子消息整段 DFS 放弃成单个 unknown token，
        # 实体（茅台）与意图词全部埋在里面——正常轮次交 LLM 复核的输入
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析阿里巴巴", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("港股，茅台和医药板块咋样呢", session)
        survivors = [t for t in _flat(rs2) if "茅台" in t.source_request]
        assert survivors, "整段未识别的回复子消息必须保留为任务（交 LLM 复核），不得丢弃"

    # ---- 规则钉子（判定规则的正反两面对偶） ----

    def test_dual_role_fragment_narrows_and_keeps_request(self):
        # 规则钉子（正面）：子消息可同时充当消歧证据与新请求——"港股"
        # 把阿里巴巴收窄到港股候选（① 照常消费证据），"医药板块怎么
        # 看"作为新任务保留（命中过消歧通道不排斥请求角色）
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析阿里巴巴", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("港股医药板块怎么看", session)
        flat_ = _flat(rs2)
        resolved = [t for t in flat_ if t.source == "confirmation"]
        assert _codes(resolved[0]) == ["HK09988"]
        sector = [t for t in flat_ if t.sectors == ["医药"]]
        assert sector and sector[0].intent == WebIntent.SECTOR_ANALYSIS

    def test_candidate_echo_in_compound_reply_still_dropped(self):
        # 规则钉子（反面）：候选空间内的实体提及（复述组名）是答案空间
        # 回声——另一片段已给出答案时，回声片段照旧丢弃，不得对刚消解
        # 的问题虚假重问（"所有实体参与消歧才判为答案"的边界：复述组
        # 名与候选互动＝参与，不构成证据≠不参与）
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析阿里巴巴", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("阿里巴巴，港股", session)
        flat_ = _flat(rs2)
        assert len(flat_) == 1, "回声片段不得重生为对已消解问题的重问"
        assert flat_[0].source == "confirmation"
        assert _codes(flat_[0]) == ["HK09988"]

    # ---- 边界钉子：纯答案形态照旧丢弃 ----

    def test_pure_market_reply_still_consumed(self):
        # 纯消歧片段（"港股"单独回复）照旧被消费且不多出任务——
        # 纯市场词回复不构成新话题
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析阿里巴巴", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("港股", session)
        flat_ = _flat(rs2)
        assert len(flat_) == 1 and flat_[0].source == "confirmation"

    def test_vague_single_reply_zero_interaction_unchanged(self):
        # 单条模糊回应照旧走零交互出口按新消息解析
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析阿里巴巴", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("嗯嗯", session)
        flat_ = _flat(rs2)
        assert len(flat_) == 1 and flat_[0].source == "rule"
        assert flat_[0].intent == WebIntent.GENERAL_CHAT


# =========================================================================
# 市场词作为板块主体 — 联动/消歧例外与裸数字守卫
# =========================================================================


class TestMarketWordAsSectorSubject:
    """纯市场限定词（港股/美股/a股）是句子的唯一对象解释时，与大盘/
    指数同口径进入分支4 兜底对象：默认报数、观点/动作词升级板块分析，
    槽位填市场名（MARKET_SLOT_NAMES）。两个例外钉死：

    - 联动个股实体（"港股阿里"）：市场词是限定词不是对象——分支3 按
      市场消歧个股，sectors 恒空，不产生板块任务；
    - 确认轮回复（"港股"答"哪家阿里巴巴"）：纯消歧答案被第五步消费，
      不得重开为美股/港股行情任务（test_pure_market_reply_still_
      consumed 的市场词版钉子）。

    守卫：裸数字在场（"港股00700"）时对象解释不唯一——不当板块报市场
    行情而静默丢实体，交 LLM 复核。
    """

    def test_bare_market_word_defaults_to_quote(self):
        # "港股怎么样"：市场词是唯一对象 → 行情查询，槽位"港股"，规则直达
        r = _resolver().resolve_first("港股怎么样", {})
        assert r.source == "rule"
        assert r.intent == WebIntent.QUOTE_LOOKUP
        assert r.sectors == ["港股"]
        assert r.confidence == 0.85 and not r.needs_confirmation

    def test_market_word_with_opinion_word_upgrades_to_sector_analysis(self):
        # "港股怎么看"：观点词在场 → 板块分析（与"大盘怎么看"同口径）
        r = _resolver().resolve_first("港股怎么看", {})
        assert (r.intent, r.sectors, r.source) == (
            WebIntent.SECTOR_ANALYSIS, ["港股"], "rule")

    def test_market_word_with_stock_entity_is_qualifier_not_sector(self):
        # 联动例外："港股阿里巴巴"——市场词与个股实体同场，按市场消歧
        # 个股（跨市场歧义组过滤出唯一港股候选），sectors 恒空，不产生
        # 板块任务
        rs = _resolver().resolve("港股阿里巴巴", {})
        flat_ = _flat(rs)
        assert len(flat_) == 1
        assert flat_[0].intent == WebIntent.STOCK_ANALYSIS
        assert _codes(flat_[0]) == ["HK09988"]
        assert flat_[0].sectors == []

    def test_market_word_with_named_sector_stays_qualifier(self):
        # "美股医药板块"：市场词与具名板块同场——板块槽位只收具名行业，
        # 不追加市场槽（市场词是限定不是对象）
        r = _resolver().resolve_first("美股医药板块", {})
        assert (r.intent, r.sectors) == (WebIntent.SECTOR_ANALYSIS, ["医药"])

    def test_market_word_reply_in_confirmation_consumed_not_reopened(self):
        # 参与消歧例外："分析阿里巴巴"→确认→答"港股"：回复被第五步消费
        # 落位 HK09988，不得再生成一条港股行情任务（确认轮里参与消歧的
        # 市场词不是板块主体）
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析阿里巴巴", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("港股", session)
        flat_ = _flat(rs2)
        assert len(flat_) == 1
        assert flat_[0].source == "confirmation"
        assert _codes(flat_[0]) == ["HK09988"]
        assert flat_[0].sectors == [] and not flat_[0].needs_confirmation

    def test_market_word_with_bare_digits_deferred_to_llm(self):
        # 守卫："港股00700看看"——裸数字在场（5 位 HK 短码不提升），
        # 对象解释不唯一：不得当港股行情直达而静默丢掉代码，低置信交
        # LLM 复核（无 LLM 形态退闲聊）
        r = _resolver().resolve_first("港股00700看看", {})
        assert r.intent == WebIntent.GENERAL_CHAT
        assert r.sectors == []


# =========================================================================
# 确认链回归：纠错消费 / 存活闸门 / 构造载荷归一
# =========================================================================


class TestConfirmationChainRegressions:
    """确认链语义回归：

    - stock_unresolved 纠错消费：恰一只纯形实体回复（fresh 且无
      has_content）结算原任务——原意图随任务存活、随行实体合并保留，
      不从裸消息重新分类；单个确认任务被多个实体命中＝匹配失败
      （比较/新请求语义，按新话题）；带自身语义的回复按新话题解析；
      混链已消解兄弟不因未消费的确认链连带销毁；
    - pending_actions 存活闸门：clear_pending_actions 是确认链的撤销
      协议，清空后陈旧 last_resolutions 投影不构成消费源；
    - 构造载荷归一：stocks 与 candidates 的 str/dict 载荷同口径归一为
      Stock，公开入口（primary_stock_code / 会话簿记）按 .code 契约
      消费。
    """

    # ---- stock_unresolved 纠错消费 ----

    def test_unresolved_bare_code_correction_restores_task(self):
        # 裸代码纠错：确认提示所求形状（只回正确代码）结算原任务
        # （source=confirmation），不从裸消息重新分类；"查一下"是取数
        # 动作，原意图为 quote_lookup（_depth_branch 同口径裁决）
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("查一下SH999999", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("600519", session)
        flat_ = _flat(rs2)
        assert len(flat_) == 1
        assert flat_[0].source == "confirmation"
        assert flat_[0].intent == WebIntent.QUOTE_LOOKUP
        assert _codes(flat_[0]) == ["600519"]
        assert not flat_[0].needs_confirmation
        apply_resolution_to_session(session, rs2)
        assert session[PENDING_ACTIONS_KEY] == []

    def test_unresolved_correction_preserves_intent_and_entities(self):
        # 原意图（quote_lookup）与随行实体（600519）双保留：纠错回复
        # 000858 后按原意图两只一起落位执行
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("查一下600519和SH999999的股价", session)
        assert _flat(rs1)[0].reason == "stock_unresolved"
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("000858", session)
        flat_ = _flat(rs2)
        assert len(flat_) == 1
        t = flat_[0]
        assert (t.source, t.intent) == ("confirmation", WebIntent.QUOTE_LOOKUP)
        assert _codes(t) == ["600519", "000858"]
        assert not t.needs_confirmation

    def test_unresolved_correction_bare_name_still_pure(self):
        # 裸名称纠错与裸代码同过闸：全名解析出 stocks 即纯形答案
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("查一下SH999999", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("茅台", session)
        flat_ = _flat(rs2)
        assert len(flat_) == 1
        assert flat_[0].source == "confirmation"
        assert _codes(flat_[0]) == ["600519"]
        assert not flat_[0].needs_confirmation

    def test_unresolved_correction_expressive_reply_stays_new_topic(self):
        # 带自身语义的回复不构成纠错答案：意图词在场 → 按新话题解析
        # （source=rule），纠错消费只认纯形实体回复
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("查一下SH999999", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("分析600519", session)
        flat_ = _flat(rs2)
        assert len(flat_) == 1
        assert flat_[0].source == "rule"
        assert flat_[0].intent == WebIntent.STOCK_ANALYSIS
        assert _codes(flat_[0]) == ["600519"]
        assert not any(t.needs_confirmation for t in flat_)

    def test_unresolved_mixed_chain_bare_reply_keeps_resolved_sibling(self):
        # 混链全链路：阿里歧义先落位（港股），纠错回复再结算 SH999999
        # 任务 → 已消解兄弟与纠错任务一起存活执行（未消费的确认链
        # 不连带销毁已消解任务）
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析阿里巴巴，查一下SH999999", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("港股", session)
        apply_resolution_to_session(session, rs2)
        rs3 = _resolver().resolve("600519", session)
        flat_ = _flat(rs3)
        assert not any(t.needs_confirmation for t in flat_)
        assert [(t.source, _codes(t)) for t in flat_] == [
            ("confirmation", ["HK09988"]),
            ("confirmation", ["600519"]),
        ]

    def test_zero_interaction_expressive_reply_keeps_resolved_sibling(self):
        # 零交互出口：混链等待期收到带意图词回复（不构成任何确认
        # 的答案）→ 仍在等待的确认任务作废，已消解待执行的兄弟保留
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析阿里巴巴，查一下SH999999", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("港股", session)
        apply_resolution_to_session(session, rs2)
        rs3 = _resolver().resolve("分析600519", session)
        flat_ = _flat(rs3)
        assert [(t.source, _codes(t)) for t in flat_] == [
            ("confirmation", ["HK09988"]),
            ("rule", ["600519"]),
        ]
        assert not any(t.needs_confirmation for t in flat_)

    def test_double_unresolved_correction_settles_both(self):
        # 两个 wrong-code 确认任务 × 单裸码纠错：各自结算同一实体——
        # 匹配按"每个任务 × 每个实体"独立进行，单实体命中多任务是
        # 多组同答的"各自落位"，不是匹配失败
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("查一下SH999999，再查SH999998", session)
        assert len(_flat(rs1)) == 2
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("600519", session)
        flat_ = _flat(rs2)
        assert len(flat_) == 2
        assert all(t.source == "confirmation" for t in flat_)
        assert all(_codes(t) == ["600519"] for t in flat_)

    def test_unresolved_multi_entity_reply_is_match_failure(self):
        # 恰一只闸门：多段纯实体回复（600519，000858）对单确认任务是
        # 匹配失败——比较/新请求语义，不消费，回复按新话题解析、原链
        # 按零交互出口作废（不得静默扩张原任务的标的数量）
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析SH999999", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("600519，000858", session)
        flat_ = _flat(rs2)
        assert all(t.source == "rule" for t in flat_)
        assert [_codes(t) for t in flat_] == [["600519"], ["000858"]]
        assert not any(t.needs_confirmation for t in flat_)
        apply_resolution_to_session(session, rs2)
        assert session[PENDING_ACTIONS_KEY] == []

    def test_unresolved_multi_stock_fragment_is_match_failure(self):
        # 单片段并列多股（"000858和300750"，无消息级切口）同样按匹配
        # 失败处理：并列多标的是新请求不是纠错答案
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("查一下600519和SH999999的股价", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("000858和300750", session)
        flat_ = _flat(rs2)
        assert len(flat_) == 1
        assert flat_[0].source == "rule"
        assert _codes(flat_[0]) == ["000858", "300750"]
        assert not flat_[0].needs_confirmation

    # ---- pending_actions 存活闸门 ----

    def test_clear_pending_actions_stops_stale_consumption(self):
        # Agent 失败收尾清 pending_actions 后旧确认链失效：陈旧
        # last_resolutions 不构成消费源，下一条消息按新话题解析
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("分析阿里巴巴", session)
        apply_resolution_to_session(session, rs1)
        clear_pending_actions(session)
        assert session[PENDING_ACTIONS_KEY] == []
        rs2 = _resolver().resolve("港股", session)
        flat_ = _flat(rs2)
        assert all(t.source != "confirmation" for t in flat_)
        # 新话题语义：裸市场词 → 港股行情查询（市场槽）
        assert flat_[0].intent == WebIntent.QUOTE_LOOKUP
        assert flat_[0].sectors == ["港股"]
        assert not flat_[0].needs_confirmation

    # ---- 构造载荷归一 ----

    def test_stocks_dict_payload_normalized_public_entries(self):
        # stocks 传 dict 载荷：__post_init__ 归一为 Stock——
        # primary_stock_code 与 apply_resolution_to_session 的 stock-scope
        # 簿记按 .code 契约正常工作
        res = WebIntentResolution(
            WebIntent.QUOTE_LOOKUP, 0.9,
            stocks=[{"code": "600519", "name": "贵州茅台", "market": "a"}])
        assert all(isinstance(s, Stock) for s in res.stocks)
        assert res.primary_stock_code == "600519"
        session: Dict[str, Any] = {}
        apply_resolution_to_session(session, res)
        assert session[RECENT_STOCKS_KEY] == ["600519"]

    def test_stocks_mixed_payload_and_malformed_entries(self):
        # str 代码 / dict / 混排归一；空串与缺 code 的 dict 剔除
        # （与 candidates 同口径）
        res = WebIntentResolution(
            WebIntent.STOCK_ANALYSIS, 0.9,
            stocks=["600519", {"code": "000858"}, "", {"name": "无code"}],
            candidates=["BABA"])
        assert [(s.code, s.name, s.market) for s in res.stocks] == [
            ("600519", "", ""), ("000858", "", "")]
        assert isinstance(res.candidates[0], Stock)
        assert res.candidates[0].code == "BABA"


class TestSubjectDepthBranchRegressions:
    """坏码/存疑码主体的深度语义保真：_depth_branch 单点裁决（T1 持仓
    语境 > T2 数据词 > 默认分析）对确定实体（分支3）、坏码（分支1）、
    存疑码（分支7）三类主体形状同口径——标的可疑只影响确认/透传，
    不改写请求的深度语义。"""

    def test_bad_code_subjects_keep_quote_and_portfolio_semantics(self):
        # 同句换合法代码分别是 quote_lookup / portfolio_analysis——
        # 坏码（确认短路）与存疑码（透传实查）不得丢失这些深度信号
        r = _resolver()
        t = r.resolve_first("查一下SH999999的股价")
        assert (t.intent, t.reason) == (
            WebIntent.QUOTE_LOOKUP, "stock_unresolved")
        assert t.unresolved_names == ["SH999999"]
        t = r.resolve_first("看下HK12345股价")
        assert t.intent == WebIntent.QUOTE_LOOKUP
        assert any("12345" in c for c in t.unverified_codes)
        assert not t.needs_confirmation
        t = r.resolve_first("我的SH999999还该拿着吗")
        assert (t.intent, t.reason) == (
            WebIntent.PORTFOLIO_ANALYSIS, "stock_unresolved")

    def test_bad_code_correction_executes_original_depth(self):
        # 纠错链沿原始深度意图执行：报数请求纠错后仍是报数，不落成
        # 默认个股分析
        session: Dict[str, Any] = {}
        rs1 = _resolver().resolve("查一下SH999999的股价", session)
        apply_resolution_to_session(session, rs1)
        rs2 = _resolver().resolve("600519", session)
        t = _flat(rs2)[0]
        assert (t.source, t.intent) == ("confirmation", WebIntent.QUOTE_LOOKUP)
        assert _codes(t) == ["600519"]
        assert not t.needs_confirmation


class TestMultiIntentSplitRegressions:
    """LLM 多意图拆分的实体核算与防幻觉不变量：

    - 越权代码拒收：规则侧有歧义候选时，库内命中但不在候选组 ∪ 已解
      析实体内的代码不得无确认执行（与单元素协议同口径，见
      test_probe_llm_code_outside_groups_rejected）；候选组内回显不受
      闸门误伤，元素可直接认领；
    - 规则侧指称不因拆分蒸发：坏码澄清（unresolved_names）逐元素保
      留（单元素合并同口径），存疑代码（unverified_codes）由孤儿核算
      单目标挂回随行透传；
    - 深度拆分与逗号展开同构：空主体元素平分规则侧歧义组与预挂组，
      一次市场词回复同时落位；
    - 具名指数与个股共对象经板块槽位平权分解为独立任务。
    """

    def test_multi_intent_out_of_group_code_rejected(self):
        # 规则侧阿里巴巴双候选（歧义待确认），LLM 多意图数组首元素返回
        # 库内命中但不在候选组的 600519：越权换标的代码拒收，歧义候
        # 选以确认形态保留（与单元素协议同口径）
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "stock_analysis", "confidence": 0.9,
             "stock_code": "600519"},
            {"intent": "quote_lookup", "confidence": 0.9},
        ]}, ensure_ascii=False))
        flat_ = _flat(_resolver(stub).resolve("阿里巴巴多少钱和走势", {}))
        assert len(stub.calls) == 1, "quote×research 共现触发多意图复核"
        leaking = [t for t in flat_ if "600519" in _codes(t)]
        assert not leaking or all(
            t.needs_confirmation for t in leaking
        ), "候选组外的库内代码（幻觉标的）不得无确认执行"
        assert any(
            {c.code for c in t.candidates} == {"BABA", "HK09988"}
            for t in flat_
        ), "规则侧歧义候选须以确认形态保留（孤儿核算回收）"

    def test_multi_intent_split_keeps_wrong_code_confirmation(self):
        # 规则侧识别 SH123456 为确定非法代码（stock_unresolved 待澄
        # 清），LLM 多元素拆分后即使无人回填 unresolved_names，坏码澄
        # 清也经逐元素 seed 保留，短路等待用户重给
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "quote_lookup", "confidence": 0.9,
             "stock_code": "000799"},
            {"intent": "stock_analysis", "confidence": 0.9},
        ]}, ensure_ascii=False))
        flat_ = _flat(_resolver(stub).resolve("看看SH123456和酒鬼酒哈", {}))
        assert any(
            t.unresolved_names == ["SH123456"] and t.needs_confirmation
            for t in flat_
        ), "多元素拆分不得丢弃规则侧坏码澄清（stock_unresolved 短路）"

    def test_multi_intent_split_keeps_unverified_code(self):
        # SOFI 是用户显式写出的美股存疑代码（透传执行端实查），多元
        # 素拆分后无人认领时由孤儿核算挂回执行类任务随行透传，不静默
        # 丢弃
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "stock_analysis", "confidence": 0.9},
            {"intent": "stock_analysis", "confidence": 0.9,
             "stock_code": "000799"},
        ]}, ensure_ascii=False))
        flat_ = _flat(_resolver(stub).resolve("分析SOFI呗和酒鬼酒", {}))
        assert any(
            "SOFI" in c for t in flat_ for c in t.unverified_codes
        ), "多元素拆分不得静默丢弃规则侧存疑代码"

    def test_stock_with_named_index_spawns_index_task(self):
        # 具名指数与个股共对象时经板块槽位平权分解为独立任务——与
        # "医药板块和酒鬼酒哪个好"的板块分解同构；全 token 识别 +
        # 0.85 高置信规则直达，零 LLM 调用（指数槽位与具名板块同证据
        # 权重，sibling 深度裁决同享 exact 判据，不落低置信确认）
        stub = _StubLLMAdapter(content="{}")
        flat_ = _flat(_resolver(stub).resolve("茅台和上证指数哪个好", {}))
        assert len(stub.calls) == 0, "高置信规则直达，不触发 LLM 复核"
        assert [(t.intent, _codes(t), t.sectors) for t in flat_] == [
            (WebIntent.STOCK_ANALYSIS, ["600519"], []),
            (WebIntent.SECTOR_ANALYSIS, [], ["上证"]),
        ], "指数对象不得被个股主体静默丢弃"
        assert all(t.confidence == 0.85 and not t.needs_confirmation
                   for t in flat_)

    def test_named_index_qualifier_spawns_context_task(self):
        # 限定词形态（与"医药板块的酒鬼酒"同口径）：指数作个股定语时
        # 同样生成指数上下文任务——板块/指数共有的平权分解，宁多一个
        # 上下文任务不静默丢对象
        flat_ = _flat(_resolver().resolve("创业板的酒鬼酒怎么样"))
        assert [(t.intent, _codes(t), t.sectors) for t in flat_] == [
            (WebIntent.STOCK_ANALYSIS, ["000799"], []),
            (WebIntent.SECTOR_ANALYSIS, [], ["创业板"]),
        ]

    def test_conjunction_depth_split_mirrors_comma_form(self):
        # 「阿里巴巴的股价和走势」的多意图拆分与逗号展开形「阿里巴巴
        # 的股价，阿里巴巴的走势」同构：两个空主体元素各自继承规则侧
        # 歧义候选与预挂组，一次市场词回复同时落位（无 pending 的空主
        # 体确认是死端——回复无从消费，且会连带作废已消解任务）
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "quote_lookup", "confidence": 0.9,
             "stock_code": None},
            {"intent": "stock_analysis", "confidence": 0.9,
             "stock_code": None},
        ]}, ensure_ascii=False))
        session: Dict[str, Any] = {}
        rs1 = _resolver(stub).resolve("阿里巴巴的股价和走势", session)
        apply_resolution_to_session(session, rs1)
        assert all(
            {c.code for c in t.candidates} == {"BABA", "HK09988"}
            and t.reason == "ambiguous_stock_name"
            for t in _flat(rs1)
        ), "深度拆分的每个空主体元素都应继承规则侧歧义组（逗号形同构）"
        rs2 = _resolver().resolve("港股", session)
        assert [(t.intent, _codes(t), t.needs_confirmation)
                for t in _flat(rs2)] == [
            (WebIntent.QUOTE_LOOKUP, ["HK09988"], False),
            (WebIntent.STOCK_ANALYSIS, ["HK09988"], False),
        ], "一次市场词回复应同时落位两个任务（与逗号形生命周期一致）"

    def test_multi_intent_candidate_echo_claimed(self):
        # 闸门不误伤合法回显：LLM 在候选组内做选择（HK09988）时，多
        # 元素模式下元素槽虽已重置，候选组成员代码仍可经 claimable 通
        # 道认领——两个任务各带标的直接执行，不转确认
        stub = _StubLLMAdapter(content=json.dumps({"intents": [
            {"intent": "quote_lookup", "confidence": 0.9,
             "stock_code": "HK09988"},
            {"intent": "stock_analysis", "confidence": 0.9,
             "stock_code": "HK09988"},
        ]}, ensure_ascii=False))
        flat_ = _flat(_resolver(stub).resolve("阿里巴巴多少钱和走势", {}))
        assert [(t.intent, _codes(t), t.needs_confirmation)
                for t in flat_] == [
            (WebIntent.QUOTE_LOOKUP, ["HK09988"], False),
            (WebIntent.STOCK_ANALYSIS, ["HK09988"], False),
        ]

    def test_single_element_merge_keeps_rule_unresolved_names(self):
        # 单元素合并同口径：LLM 未回填 unresolved_names 时，规则侧坏
        # 码名单仍作基底保留（stock_unresolved 短路）；unverified_codes
        # 的挂回见 test_multi_intent_split_keeps_unverified_code
        stub = _StubLLMAdapter(content=json.dumps({
            "intent": "stock_analysis", "confidence": 0.9,
            "stock_code": None}, ensure_ascii=False))
        t = _flat(_resolver(stub).resolve("看看SH123456和酒鬼酒哈", {}))[0]
        assert t.unresolved_names == ["SH123456"], \
            "规则侧坏码名单不因 LLM 未回填而丢失（stock_unresolved 短路保留）"
