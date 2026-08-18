# -*- coding: utf-8 -*-
"""
Web Chat 意图识别层（Intent Resolution Layer）。

== 模块定位 ==
本模块与 Bot 分发器（``bot/dispatcher.py``）的自然语言路由并行工作，
在 Web Chat 的 SSE 流（``POST /api/v1/agent/chat/stream``）中插入一步意图识别。

== 支持的意图类型 ==
- ``stock_research``     — 个股研究/分析
- ``portfolio_review``   — 持仓回顾
- ``market_overview``    — 大盘行情
- ``history_followup``   — 对上一轮分析的追问
- ``general_chat``       — 闲聊/与股票分析无关的问题

== 设计边界 ==
这不是一个完整的 Agent 规划器。意图识别只产生一个轻量级标签 + 股票上下文，
由 SSE 层据此行动：
  1. 先发送 ``intent_resolved`` 事件；
  2. 当置信度低或股票名称歧义时，发送 ``action_required`` 事件中断流程等待用户澄清；
  3. 将解析出的 ``stock_code`` 传递给 #1619 股票范围（stock-scope）机制。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.agent.stream_events import stream_event  # SSE 事件工厂
from src.agent.stock_scope import extract_stock_codes  # 代码格式校验（不查库）
from src.services.name_to_code_resolver import (
    Stock,  # (code/name/market)
    US_stock_code_match,  # 美股代码匹配
    extend_AkShare,  # AkShare 全量 A 股扩展（30 分钟缓存，_preprocess_text Step 6 前调用）
    is_known_stock_name,
    resolver_name_to_code_list,
    stockDB,  # 全局名称库（code→name，可被 AkShare 原地扩充）
)
from src.data.stock_mapping import STOCK_NAME_MAP  # 代码→名称映射

logger = logging.getLogger(__name__)


# =========================================================================
# 意图常量定义
# =========================================================================

class WebIntent(str, Enum):
    """意图标签枚举（str 子类，成员可直接与字符串比较）。"""

    STOCK_RESEARCH = "stock_research"       # 个股研究
    PORTFOLIO_REVIEW = "portfolio_review"   # 持仓回顾
    MARKET_OVERVIEW = "market_overview"     # 大盘行情
    HISTORY_FOLLOWUP = "history_followup"   # 对上一轮分析的追问（未提及新股票）
    GENERAL_CHAT = "general_chat"           # 闲聊


# 所有合法意图（字符串形式），校验 LLM/session 返回
ALL_WEB_INTENTS = frozenset(w.value for w in WebIntent)


# =========================================================================
# Token 语义标签常量 — 5 大类 20 个标签，近义词归入同一标签，供正则匹配使用
# =========================================================================

# --- 股票识别 ---
TAG_UNKNOWN_CODE = "unknown_code"      # 待验证的代码形字符串，Step 2 提取，后续辨认为 stock_code/wrong_code，或保留交由下游 LLM 判断
TAG_UNKNOWN_NUMBER = "unknown_number"  # ≤4 位裸数字（年份/月份/日期/价格…），非代码候选，Step 2 直接标记，不进入代码校验
TAG_STOCK_CODE = "stock_code"          # 已验证有效的股票代码（高置信度格式/本地库命中）
TAG_WRONG_CODE = "wrong_code"          # 无效/非法代码形字符串
TAG_STOCK_NAME = "stock_name"          # 股票实体（全名或一对一缩写），Step 3 仅全名精确匹配、Step 6 多策略匹配提取
TAG_CODE_NAME = "code_name"            # 空 tag 经 name_code_list 解析为股票名称后打此标签

# --- 意图主题 ---
TAG_SUBJECT_RESEARCH = "subject_research"       # 研究主题（走势/趋势/技术面/基本面/筹码）
TAG_SUBJECT_PORTFOLIO = "subject_portfolio"     # 持仓主题（持仓/仓位/自选股/盈亏）
TAG_SUBJECT_MARKET = "subject_market"           # 市场标识（A股/港股/美股/沪市…）
TAG_SUBJECT_MARKET_BROAD = "subject_market_broad"  # 泛市场概念（大盘/行情/指数/两市）
TAG_SUBJECT_INDEX = "subject_index"             # 具体指数（上证/恒生/纳斯达克/沪深300…）

# --- 动作 ---
TAG_REQUEST = "request"                 # 分析动作词（分析/看看/研究/诊断/查一下/评估）
TAG_ACTION_RESEARCH = "action_research"     # 研究决策（能买/可以买/止损/目标价/buy/sell）
TAG_ACTION_PORTFOLIO = "action_portfolio"   # 持仓操作（加仓/减仓/调仓/满仓/空仓）

# --- 辅助 ---
TAG_FOLLOWUP = "followup"               # 追问延续（继续/刚才/这只/它/上面/上次/该股）
TAG_QUESTION = "question"               # 疑问（怎么看/怎么样/涨还是跌/怎么/为何/吗/呢）
TAG_COMPARISON = "comparison"           # 对比（对比/比较/哪个好/vs/pk/二选一）
TAG_SECTOR = "sector"                   # 板块/行业（新能源/半导体/消费/医药/AI…）
TAG_TIME = "time"                       # 时间指示（今天/本周/交易日/实时）
TAG_FILLER = "filler"                   # 回复填充词（单字独立匹配：的/买/卖/选/那/这…）

# 所有合法 tag 的不可变集合
_ALL_TAGS = frozenset({
    TAG_UNKNOWN_CODE, TAG_UNKNOWN_NUMBER, TAG_STOCK_CODE, TAG_WRONG_CODE, TAG_STOCK_NAME, TAG_CODE_NAME,
    TAG_SUBJECT_RESEARCH, TAG_SUBJECT_PORTFOLIO, TAG_SUBJECT_MARKET,
    TAG_SUBJECT_MARKET_BROAD, TAG_SUBJECT_INDEX,
    TAG_REQUEST, TAG_ACTION_RESEARCH, TAG_ACTION_PORTFOLIO,
    TAG_FOLLOWUP, TAG_QUESTION, TAG_COMPARISON, TAG_SECTOR, TAG_TIME, TAG_FILLER,
})


class Market(str, Enum):
    """市场标识枚举（str 子类，成员可直接与字符串比较）。"""

    A = "a"    # A 股
    HK = "hk"  # 港股
    US = "us"  # 美股

# 执行类意图：会触发 Agent 工作流，低置信度/股票歧义时必须先经用户确认
_EXECUTING_INTENTS = frozenset({
    WebIntent.STOCK_RESEARCH,
    WebIntent.PORTFOLIO_REVIEW,
    WebIntent.MARKET_OVERVIEW,
})

# 执行类意图低于此置信度 → 转用户确认
CONFIRMATION_CONFIDENCE_THRESHOLD = 0.6

# LLM 兜底路径的置信度上限（规则路径 0.8~0.9，LLM 统一压低，避免过度自信）
LLM_CONFIDENCE_CAP = 0.75

# 会话上下文最多保留的"最近关注股票"数量
MAX_RECENT_STOCKS = 10

# apply_resolution_to_session() 写入会话上下文时使用的 key
RECENT_STOCKS_KEY = "recent_stocks"       # 最近关注股票代码列表
PENDING_ACTIONS_KEY = "pending_actions"   # 待确认动作列表（仅 confirm_stock）
LAST_INTENT_KEY = "last_intent"           # 上一轮意图标签


# =========================================================================
# Tag → 关键词列表 — 所有中文关键词的唯一定义处
# =========================================================================
# 后续正则全部从这里编译，不手写中文关键词；TAG_SUBJECT_MARKET 由 _MARKET_KEYWORD_MAP 派生。
# 排除项：多 token 跨词模式（和.*比…）→ extra 参数；"值得" → 与股票名"值得买"冲突，已删除

_MARKET_KEYWORD_MAP: Dict[Market, tuple] = {
    Market.A: ("a股", "大a", "沪市", "深市", "沪深"),
    Market.HK: ("港股", "h股", "香港"),
    Market.US: ("美股", "美国"),
}

# 关键词分两池：clean 无歧义可直接分词；extend 可能与股票名混淆，增加分词多样性。
# _TAG_KEYWORD_LISTS 由两者合并，下游逻辑不变

_TAG_KEYWORD_LISTS_CLEAN: Dict[str, List[str]] = {
    TAG_REQUEST: [
        "分析", "看看", "研究", "诊断", "评估", "查一下", "查下",
        "analyze", "analyse", "research",
    ],
    TAG_SUBJECT_RESEARCH: [
        "走势", "走向", "趋势", "技术面", "基本面", "筹码", "后市", "trend",
    ],
    TAG_ACTION_RESEARCH: [
        "能买", "可以买", "目标价", "止损", "买点", "卖点", "抄底", "buy", "sell",
    ],
    TAG_QUESTION: [
        "涨还是跌", "怎么看", "怎么样", "怎么", "是否",
        "为何", "为什么", "还会", "要不要",
        "能否", "能不能", "如何", "吗", "？", "?",
    ],
    TAG_SUBJECT_PORTFOLIO: [
        "持仓", "仓位", "我的股票", "自选股", "盈亏", "成本价",
        "portfolio", "position",
    ],
    TAG_ACTION_PORTFOLIO: [
        "加仓", "减仓", "调仓", "满仓", "空仓",
    ],
    TAG_SUBJECT_MARKET_BROAD: [
        "大盘", "行情", "两市", "北向", "股市", "market", "sector", "指数",
    ],
    TAG_SUBJECT_INDEX: [
        "上证", "深证", "创业板", "科创板",
        "恒指", "纳斯达克", "纳指",
        "标普", "道琼斯", "道指", "沪深300",
        "沪指", "深成指", "深证成指", "创业板指", 
        "科创50", "科创", "index", "indices",
    ],
    TAG_FOLLOWUP: [
        "继续", "接着", "刚才", "上面", "上次", "这只", "该股", "它", "他",
        "然后",
    ],
    TAG_COMPARISON: [
        "哪个好", "哪个", "哪只", "谁更", "二选一",
        "差别", "区别", "优劣", "pk",
    ],
    TAG_TIME: [
        "今天", "本周", "交易日", "实时", "最近", 
    ],
    TAG_FILLER: [
        "那个", "这个", "一只", "一下", "帮我", "我要", "我想", "以及", 
        "其他", "其它",
    ],
}

_TAG_KEYWORD_LISTS_EXTEND: Dict[str, List[str]] = {
    TAG_SUBJECT_INDEX: [
        "恒生",  # 与股票名"恒生电子"混淆
    ],
    TAG_COMPARISON: [
        "对比", "比较", "多选", "选哪",
    ],
    TAG_SECTOR: [
        "板块", "行业", "赛道", "概念", "题材", "龙头",
        "新能源", "半导体", "消费", "医药", "白酒",
        "军工", "银行", "地产", "保险", "券商",
        "煤炭", "有色", "钢铁", "汽车", "光伏", "锂电",
        "芯片", "人工智能", "互联网", "金融", "科技股", "AI",
    ],
    TAG_FILLER: [
        "和", "下", "是", "再",
        "的", "买", "卖", "选", "了", "吧", "呢",
        "那", "这", "只", "支", "啊", "呀", "咯",
        "哦", "嘛", "么", "就", "请", "第", "个",
    ],
}

_TAG_KEYWORD_LISTS: Dict[str, List[str]] = {}
for _tag in set(_TAG_KEYWORD_LISTS_CLEAN) | set(_TAG_KEYWORD_LISTS_EXTEND):
    _TAG_KEYWORD_LISTS[_tag] = (
        _TAG_KEYWORD_LISTS_CLEAN.get(_tag, []) +
        _TAG_KEYWORD_LISTS_EXTEND.get(_tag, [])
    )

# 市场标识关键词 → tag（从 _MARKET_KEYWORD_MAP 派生）
_MARKET_KW_TAG_MAP: Dict[str, str] = {
    kw: TAG_SUBJECT_MARKET
    for keywords in _MARKET_KEYWORD_MAP.values()
    for kw in keywords
}

# market keyword → Market 枚举（反转，O(1) 查询）
_KW_TO_MARKET: Dict[str, Market] = {
    kw: mkt for mkt, keywords in _MARKET_KEYWORD_MAP.items() for kw in keywords
}

# keyword → tag（反转 + 市场词合并，供 _classify_keyword O(1) 查询）
_KEYWORD_TAG_MAP: Dict[str, str] = {
    kw: tag for tag, kws in _TAG_KEYWORD_LISTS.items() for kw in kws
}
_KEYWORD_TAG_MAP.update(_MARKET_KW_TAG_MAP)



# =========================================================================
# 正则编译工具 — 全部从 _TAG_KEYWORD_LISTS 编译
# =========================================================================

def _compile_kw_fragment(kw: str) -> str:
    """单个关键词 → regex 片段：ASCII 包裹 (?i:)，CJK 直接 escape。"""
    if re.search(r"[A-Za-z]", kw):
        return f"(?i:{re.escape(kw)})"
    return re.escape(kw)


def _compile_kw_pattern(*tags: str, extra: str = "") -> re.Pattern:
    """从指定 tag 列表提取所有关键词，编译为单个正则。

    按长度降序排列确保长关键词优先（"沪深300" 不被 "沪深" 截断）。
    extra 参数可追加原生 regex 片段（如 vs 词边界、多 token 跨词模式）。
    """
    kws: List[str] = []
    for tag in tags:
        if tag == TAG_SUBJECT_MARKET:
            kws.extend(_MARKET_KW_TAG_MAP.keys())
        else:
            kws.extend(_TAG_KEYWORD_LISTS.get(tag, []))
    fragments = sorted(
        ({_compile_kw_fragment(k) for k in kws} |
         ({extra} if extra else set())),
        key=len, reverse=True,
    )
    return re.compile("|".join(fragments))


# Step 5 关键词分词正则（排除市场类 tag，Step 4 独立处理，避免 "大港股份" 消歧失效）
_NON_MARKET_TAGS = frozenset({
    TAG_REQUEST, TAG_SUBJECT_RESEARCH, TAG_ACTION_RESEARCH, TAG_QUESTION,
    TAG_SUBJECT_PORTFOLIO, TAG_ACTION_PORTFOLIO,
    TAG_FOLLOWUP, TAG_COMPARISON, TAG_SECTOR, TAG_TIME, TAG_FILLER,
})


def _compile_clean_kw_pattern(*tags: str) -> re.Pattern:
    """仅用 _TAG_KEYWORD_LISTS_CLEAN 编译正则，排除可能混淆股票名的扩展关键词。"""
    kws: List[str] = []
    for tag in tags:
        kws.extend(_TAG_KEYWORD_LISTS_CLEAN.get(tag, []))
    fragments = sorted({_compile_kw_fragment(k) for k in kws}, key=len, reverse=True)
    return re.compile("|".join(fragments))


# Step 5 无歧义关键词分词正则（如"分析""走势""持仓"等不可能混淆股票名的词）
_CLEAN_KEYWORDS_PATTERN = _compile_clean_kw_pattern(*_NON_MARKET_TAGS)


# 纯标点/空白过滤：至少含一个 CJK/字母/数字
_HAS_CONTENT_PATTERN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")

# 特殊标点集合（Step 1 分词边界）。排除 * - .：可能出现在股票名/代码中（ST*、600519.SH）
_SPECIAL_PUNCT_CHARS = (
    "\uff0c\u3002\uff01\uff1f\uff1b\uff1a\u3001\u201c\u201d\u2018\u2019"
    "\uff08\uff09\u3010\u3011\u300a\u300b\u2026\uff5e\u2014\uff0f\uff20"
    "\uff03\uff04\uff05\uff3e\uff06\uff0b\uff1d"
    ",!?;:\"'()[]{}<>/@#$%^&+=~`|\\\\"
)
_SPECIAL_PUNCT_RE = re.compile("[" + re.escape(_SPECIAL_PUNCT_CHARS) + "]")


def _classify_keyword(token_text: str) -> str:
    """查 _KEYWORD_TAG_MAP 取语义标签；混合大小写 token 做 lower() 回退；未命中返回空串。"""
    tag = _KEYWORD_TAG_MAP.get(token_text)
    if tag:
        return tag
    lowered = token_text.lower()
    if lowered != token_text:
        return _KEYWORD_TAG_MAP.get(lowered, "")
    return ""


# =========================================================================
# LLM 意图分类 Prompt — 仅在规则无法判定时调用
# =========================================================================

_INTENT_PARSE_PROMPT = """\
You are the intent classifier for a stock-analysis assistant web chat.

Classify the user message into exactly one intent:
- "stock_research": research/analyze specific stock(s) — price, trend,
  buy/sell advice, technicals, fundamentals, news
- "portfolio_review": review the user's own holdings / positions / P&L
- "market_overview": overall market, indices, sectors
- "history_followup": follow-up about the previous analysis turn, with no
  new stock mentioned
- "general_chat": chit-chat or questions unrelated to stock analysis

Also extract every stock mentioned in the message into "stock_mentions".
Resolve each mention to its canonical code using the "Stock mapping" section
appended below whenever the stock appears there, and use the code exactly as
written in the mapping — do NOT add exchange prefixes like "HK" or "SH", and
do NOT invent codes that are not listed. When a mentioned stock is absent from
the mapping, fall back to its Chinese name (e.g. "贵州茅台"); when only a
ticker or English name is known, return it as written (e.g. "TSLA", "Tesla").

The user message may be followed by a "Conversation context" section listing:
- previous_intent: the intent of the previous turn
- recent_stocks: stock codes recently discussed
- current_focus_stock: the stock currently locked in the UI
Use it ONLY to resolve pronouns and ellipsis ("它", "这只", "还会涨吗"):
choose "history_followup" only when the message continues the previous
analysis subject and names no new stock; if the message names a different
stock, choose "stock_research" and extract that name instead.

Return a JSON object and NOTHING else:
{"intent": "...", "stock_mentions": ["canonical code or Chinese name or ticker", ...], "confidence": 0.0-1.0, "market": "a"/"hk"/"us"/null}

The "market" field indicates which market the user is referring to, 
set null if no specific market or not applicable (portfolio_review, general_chat, etc.)
For market_overview, always infer the market if possible (e.g. "大盘" → "a", "港股行情" → "hk", "美股走势" → "us"). 
For stock_research, infer from the stock mentioned or conversation context.

Examples:
User: "帮我分析一下贵州茅台"
{"intent":"stock_research","stock_mentions":["600519"],"confidence":0.9,"market":"a"}

User: "研究一下腾讯最近的走势"
{"intent":"stock_research","stock_mentions":["00700"],"confidence":0.9,"market":"hk"}

User: "我的持仓今天怎么样"
{"intent":"portfolio_review","stock_mentions":[],"confidence":0.9,"market":null}

User: "今天大盘走势如何"
{"intent":"market_overview","stock_mentions":[],"confidence":0.9,"market":"a"}

User: "港股最近行情怎么样"
{"intent":"market_overview","stock_mentions":[],"confidence":0.9,"market":"hk"}

User: "它还能涨吗"
{"intent":"history_followup","stock_mentions":[],"confidence":0.8,"market":null}

User: "你好，在吗"
{"intent":"general_chat","stock_mentions":[],"confidence":0.95,"market":null}

User: "compare AAPL and TSLA"
{"intent":"stock_research","stock_mentions":["AAPL","TSLA"],"confidence":0.9,"market":"us"}
"""


# =========================================================================
# WebIntentResolution — 单次意图识别的完整结果
# =========================================================================

@dataclass
class WebIntentResolution:
    """一次 Web Chat 意图识别流程的完整产出。

    各字段的含义：
    - ``intent``: 最终的意图标签（来自 ALL_WEB_INTENTS 之一）
    - ``confidence``: 置信度 [0.0, 1.0]，影响是否需要用户确认。
      注意：本层输出的置信度是**按决策路径赋的常量**（显式代码 0.9、关键词独高
      0.85、LLM 上限 0.75…），用于表达"这条路径的可靠程度"，并非从打分分差
      导出的校准概率；前端展示时不应将其解读为统计意义的成功概率。
    - ``source``: 意图来源标识
        - ``"rule"`` — 正则/规则直接判定
        - ``"llm"`` — LLM 分类结果
        - ``"context"`` — 从会话上下文中继承（如继承 current_stock 推断为追问）
        - ``"confirmation"`` — 用户对上一个待确认动作的响应
    - ``stocks``: 能精确解析出的股票列表（已去重），每项为 Stock(code, name, market)
    - ``candidates``: 能解析名字，但股票名称有歧义时的候选列表，每项为 Stock(code, name, market)
    - ``unresolved_names``: 无法解析为任何代码的股票名称（用户可能拼错了）
    - ``inherited_stock_code``: 从会话/请求上下文中继承的当前股票代码（#1619 机制）
    - ``needs_confirmation``: True 表示该意图需要用户确认后才能执行
    - ``reason``: 需要确认时的原因说明（如 "ambiguous_stock_name" / "low_confidence" / "stock_unresolved"）
    - ``pending_action``: 需要用户执行的确认动作描述，供 SSE 层发送 action_required 事件
    - ``market``: LLM 推断的市场上下文（Market 枚举），无法推断时为 None。
      主要用于 market_overview 指定市场范围，以及辅助跨市场股票名称消歧。
    """

    intent: WebIntent
    confidence: float
    source: str = "rule"       # 默认为规则来源
    stocks: List[Stock] = field(default_factory=list)
    candidates: List[Stock] = field(default_factory=list)
    unresolved_names: List[str] = field(default_factory=list)
    inherited_stock_code: str = ""
    needs_confirmation: bool = False
    reason: str = ""
    pending_action: Optional[Dict[str, Any]] = None
    market: Optional[Market] = None      # LLM 市场推断，无法推断时为 None
    original_request: str = ""           # 确认消费轮：待确认动作对应的原请求文本

    def __post_init__(self) -> None:
        """将 stocks/candidates 中的字符串或 dict 条目统一转为 Stock。"""
        self.stocks = [
            Stock(code=s) if isinstance(s, str) else s
            for s in self.stocks
        ]
        self.candidates = [
            Stock(code=c["code"], name=c.get("name", ""), market=c.get("market", ""))
            if isinstance(c, dict) else c
            for c in self.candidates
        ]

    @property
    def primary_stock_code(self) -> str:
        """返回注入 stock-scope 的主股票代码。

        单代码直接返回；多代码（比较场景）返回空串交执行端处理——绝不能返回
        继承代码，否则"对比000858和300750"会错误锁定上一轮的 600519；
        无代码时返回继承代码保持锁定。
        """
        if len(self.stocks) == 1:
            return self.stocks[0].code
        if len(self.stocks) >= 2:
            return ""
        return self.inherited_stock_code


# =========================================================================
# 意图决策辅助
# =========================================================================

def _log_resolution(path: str, resolution: "WebIntentResolution") -> None:
    """记录意图决策 info 日志（一行），打分明细在 debug 级。"""
    logger.info(
        "[WebIntent] resolved via %s: intent=%s confidence=%.2f source=%s reason=%s codes=%s inherited=%s confirm=%s",
        path,
        resolution.intent,
        resolution.confidence,
        resolution.source,
        resolution.reason or "-",
        ",".join(s.code for s in resolution.stocks) or "-",
        resolution.inherited_stock_code or "-",
        resolution.needs_confirmation,
    )


# =========================================================================
# Token — 分词结构体，text + tag
# =========================================================================


@dataclass(frozen=True)
class Token:
    """分词结构体：文本 + 语义标签 + 可选的已解析股票实体。

    frozen=True 使 Token 可哈希；tag 为空表示未识别；stocks 透传已解析实体避免下游重复解析。
    """
    text: str
    tag: str = ""
    stocks: Optional[List["Stock"]] = None


def _extract_markets_from_tokens(tokens: List[Token]) -> List[Market]:
    """从 token 中提取市场枚举（唯一提取点）：TAG_SUBJECT_MARKET → _KW_TO_MARKET，
    另识别 ASCII 简写 "us"/"hk"。消歧已在 _split_market_tokens 完成，此处仅映射。"""
    markets: List[Market] = []
    seen: set = set()
    for t in tokens:
        if t.tag == TAG_SUBJECT_MARKET:
            mkt = _KW_TO_MARKET.get(t.text.lower())
            if mkt and mkt not in seen:
                markets.append(mkt)
                seen.add(mkt)
        elif t.text.strip().lower() in ("us", "hk"):
            mkt = Market(t.text.strip().lower())
            if mkt not in seen:
                markets.append(mkt)
                seen.add(mkt)
    return markets


def _detect_markets(text: str) -> List[str]:
    """文本级市场检测（确认流程快速回复用）。

    整条消息为 "us"/"hk" → 直接返回；否则扫描中文市场关键词。英文句中的代词
    "us"（"tell us"）不做子串匹配，不会误命中。
    """
    stripped = (text or "").strip()
    lowered = stripped.lower()
    if lowered in ("us", "hk"):
        return [lowered]
    markets: List[str] = []
    seen: set = set()
    for kw, mkt in _KW_TO_MARKET.items():
        if kw in stripped and mkt.value not in seen:
            markets.append(mkt.value)
            seen.add(mkt.value)
    return markets


def _recognition_rate(tokens: List[Token]) -> float:
    """已打标签 token 占全部 token 的比例，低则升级 LLM 兜底。"""
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if t.tag) / len(tokens)


def _dedup_stocks(stocks: List[Stock]) -> List[Stock]:
    """按 code 去重并保持出现顺序。"""
    seen: set = set()
    result: List[Stock] = []
    for s in stocks:
        if s.code not in seen:
            seen.add(s.code)
            result.append(s)
    return result


def _research_request_with_unresolved(tokens: List[Token]) -> bool:
    """研究请求中是否仍有未识别 token。

    股票名千变万化，名称库覆盖有限：研究请求（分析/看看…）下未识别的 token 很可能
    就是研究对象（"再分析一下你好股份"中的"你好股份"），规则无法定论 → 升级 LLM，
    不能误判为对上一轮股票的追问。
    """
    has_request = False
    has_unresolved = False
    for t in tokens:
        if t.tag == TAG_REQUEST:
            has_request = True
        elif not t.tag or t.tag == TAG_UNKNOWN_NUMBER:  # 空tag/None 未识别；4位裸数字（年份/日期/价格）同样不落规则，交给LLM
            has_unresolved = True
    return has_request and has_unresolved


# =========================================================================
# _preprocess_text 六步管道辅助函数
# =========================================================================

# 市场分词 pattern = 市场相关 tag 关键词 union。"股"+"份" 消歧见 _split_market_tokens，
# 避免 "大港股份" 中的 "港股" 子串被误提取
_MARKET_TOKEN_PATTERN = _compile_kw_pattern(
    TAG_SUBJECT_MARKET, TAG_SUBJECT_MARKET_BROAD, TAG_SUBJECT_INDEX,
)


# ---- _CODE_CANDIDATE_PATTERNS — 代码形字符串候选正则（_split_by_codes 专用） ----
# 宽松匹配（宁多勿漏）：找出所有"看起来像股票代码"的片段打 TAG_UNKNOWN_CODE，
# 合法性交给下游 _identify_stock_codes。唯一例外：≤4 位裸数字由 _split_by_codes
# 直接标记为 TAG_UNKNOWN_NUMBER，不进入代码校验。
# 设计要点：纯文本匹配不查库；同位置多正则命中取最长；不做市场推断。
# 覆盖形态：
#   1. 交易所前缀+数字        SH600519 / HK88888（SH/SZ/BJ/HK）
#   2. 数字.交易所后缀        123456.HK / 235454354.sh
#   3. 裸数字                 600519 / 12（≤4 位 → unknown_number）
#   4. 美股连续大写 ticker    BABA / TSLA（左右不紧邻字母数字）
#   5. 连续字母 + .us 后缀    aapl.us / BABA.US（大小写不敏感）
_CODE_CANDIDATE_PATTERNS: List[Tuple[str, int]] = [
    # 1. 交易所前缀 + 任意位数字: SH600519, HK88888, SZ123
    (r'(?<![a-zA-Z])(?:SH|SZ|BJ|HK)\d{1,}(?!\d)', re.IGNORECASE),
    # 2. 数字.交易所后缀: 123456.HK, 235454354.sh
    (r'(?<!\d)\d{1,}\.(?:SH|SZ|BJ|HK)(?!\d)', re.IGNORECASE),
    # 3. 裸任意位数字: 600519, 12, 6005199（≤4 位裸数字可能并非代码意图，会在 _split_by_codes 直接标记为 unknown_number）
    (r'(?<!\d)\d{1,}(?!\d)', 0),
    # 4. 美股连续大写 ticker: BABA, TSLA（左右边界为汉字/标点，不得紧邻小写字母）
    (r'(?<![A-Za-z0-9.])([A-Z]{2,5})(?![A-Za-z0-9])', 0),
    # 5. 连续字母 + .us 后缀（大小写不敏感）: aapl.us, BABA.US, Tsla.us
    (r'(?<![A-Za-z0-9.])([A-Za-z]{1,5}\.us)(?![A-Za-z0-9])', re.IGNORECASE),
]


def _split_by_codes(text: str) -> List[Token]:
    """宽口径代码形字符串提取（Step 2 对空 tag token 调用）。

    扫描 5 类正则命中"像代码"的片段 → TAG_UNKNOWN_CODE，间隙文本保留为空 tag token。
    此阶段只做形态匹配与最大连续合并，不校验合法性、不推断市场：
      "600519"/"HK3294384923"/"TSLA" → unknown_code；"12" → unknown_number

    不复用 extract_stock_codes：它内置首码白名单（0/3/6/4/8），会丢弃 777777 这类
    非法代码；本函数保留非法代码形字符串，供下游 SSE 二次确认。
    """
    if not text:
        return []

    # 阶段 1：全部正则独立扫描收集 span，重叠/嵌套交由阶段 2 合并
    spans: List[Tuple[int, int]] = []
    for pattern, flags in _CODE_CANDIDATE_PATTERNS:
        for m in re.finditer(pattern, text, flags):
            spans.append((m.start(), m.end()))

    # 无命中 → 整段文本作为一个空 tag token 返回
    if not spans:
        return [Token(text)]

    # 阶段 2：最大连续合并。重叠 span 扩展右边界取最长字母/数字片段
    # （"HK3294384923" 的 (0,12)/(2,12) → (0,12)，不被子串截断）
    spans.sort()
    merged: List[Tuple[int, int]] = []
    for s, e in spans:
        if merged and s < merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))

    # 阶段 3：按合并后 span 切分：候选 → unknown_code；间隙 → 空 tag token
    tokens: List[Token] = []
    pos = 0
    for s, e in merged:
        if pos < s:
            gap = text[pos:s].strip()
            if gap:
                tokens.append(Token(gap))
        span_text = text[s:e]
        if span_text.isdigit() and len(span_text) <= 4:
            # ≤4 位裸数字 → unknown_number（纯数字 span 只可能来自裸数字正则）
            tokens.append(Token(span_text, TAG_UNKNOWN_NUMBER))
        else:
            tokens.append(Token(span_text, TAG_UNKNOWN_CODE))
        pos = e
    tail = text[pos:].strip()
    if tail:
        tokens.append(Token(tail))
    return tokens


def _apply_code_extraction(tokens: List[Token]) -> List[Token]:
    """Step 2: 对空 tag token 做代码形提取（已识别 token 受保护）。"""
    result: List[Token] = []
    for t in tokens:
        if _is_identified_token(t):
            result.append(t)
        else:
            result.extend(_split_by_codes(t.text))
    return result


def _market_of_code(code: str) -> str:
    """从代码形态推断市场：6 位→a、5 位→hk、字母 ticker→us（与
    name_to_code_resolver._infer_code_market 语义一致）。"""
    c = (code or "").strip().upper()
    if not c:
        return ""
    if c.isdigit():
        if len(c) == 5:
            return "hk"
        if len(c) == 6:
            return "a"
        return ""
    if re.match(r"^[A-Z]{1,5}(\.[A-Z])?$", c):
        return "us"
    return ""


def _build_entity_index() -> Tuple[List[str], Dict[str, List[Tuple[str, str]]]]:
    """构建实体扫描用的名称索引：全名去重保序列表 + 全名 → [(code, market)]。

    每个待扫描 token 重建一次（stockDB 可能被 AkShare 扩充，不能跨消息缓存）。
    AkShare 扩展统一在 _preprocess_text Step 6 前执行（extend_AkShare）；
    本函数只读当时的 stockDB，绝不主动发起扩展。
    """
    names: List[str] = []
    name_codes: Dict[str, List[Tuple[str, str]]] = {}
    for code, name in stockDB.items():
        if not name or not code:
            continue
        if name not in name_codes:
            names.append(name)
            name_codes[name] = []
        market = _market_of_code(code)
        if market:
            name_codes[name].append((code, market))
    return names, name_codes


# 实体扫描窗口长度：固定 4~3 字精确匹配；超过 4 字的名字由 Step 6
# resolver_name_to_code_list 承接
_MAX_ENTITY_LEN = 4


def _split_by_stock_entities(text: str) -> List[Token]:
    """Step 3 子函数：多股票实体扫描（仅全名精确匹配，最长优先、非重叠）。

    逐位置尝试 4~3 字窗口：窗口必须整体等于库中股票全名，禁止子串/拼音/模糊
    等其它形式；一对一缩写（"茅台""三花"）非全名不做匹配，交由 Step 6 多策略
    匹配承接。
      - 窗口恰好等于库中全名且唯一 1 只 → TAG_STOCK_NAME 确定实体；
      - 跨市场同名多只（"阿里巴巴"→hk 09988/us BABA）→ TAG_STOCK_NAME
        携带多候选，下游 _classify_by_rules 走歧义确认；
    未命中片段保留为空 tag token 交后续步骤（宁可不做也不做错）。
    """
    if not text:
        return []
    if not any("\u3400" <= ch <= "\u9fff" for ch in text):
        return [Token(text)]  # 纯英文段由 Step 6 DFS（拼音/美股代码）兜底
    names, name_codes = _build_entity_index()
    max_len = min(_MAX_ENTITY_LEN, max((len(n) for n in names), default=0))
    tokens: List[Token] = []
    i, gap_start, n = 0, 0, len(text)
    while i < n:
        matched = False
        for length in range(max_len, 2, -1):
            if i + length > n:
                continue
            window = text[i:i + length]
            if not any("\u3400" <= ch <= "\u9fff" for ch in window):
                continue  # 不含 CJK 的窗口不扫描（代码/ASCII 由其他步骤处理）
            pairs = name_codes.get(window)  # 仅全名精确匹配：窗口必须整体等于库中股票全名
            if pairs:
                stocks = [
                    Stock(code=code, name=window, market=market)
                    for code, market in pairs
                ]
                if gap_start < i:
                    tokens.append(Token(text[gap_start:i]))
                tokens.append(Token(window, TAG_STOCK_NAME, stocks=stocks))
                i += length
                gap_start = i
                matched = True
                break
        if not matched:
            i += 1
    if gap_start < n:
        tokens.append(Token(text[gap_start:]))
    return tokens


def _apply_full_name_extraction(tokens: List[Token]) -> List[Token]:
    """Step 3: 对非代码 token 做多股票全名精确匹配扫描（仅全名）。

    一对一缩写（"茅台""三花"）非全名不做匹配，交由 Step 6 多策略匹配承接；
    已识别 token（代码/已知名称）保持原样，未被前序步骤识别的 token 交给
    _split_by_stock_entities 做仅全名精确匹配扫描。
    """
    result: List[Token] = []
    for t in tokens:
        if _is_identified_token(t):
            result.append(t)
        else:
            result.extend(_split_by_stock_entities(t.text))
    return result


def _split_market_tokens(text: str) -> List[Token]:
    """Step 4 子函数：提取市场关键词打 tag。"股"后接"份"（股票名后缀）跳过不上报。"""
    if not text:
        return []
    tokens: List[Token] = []
    pos = 0
    for m in _MARKET_TOKEN_PATTERN.finditer(text):
        s, e = m.start(), m.end()
        matched = m.group()
        if matched.endswith("股") and e < len(text) and text[e] == "份":
            continue
        if pos < s:
            gap = text[pos:s].strip()
            if gap:
                tokens.append(Token(gap))
        tag = _classify_keyword(matched)
        tokens.append(Token(matched, tag))
        pos = e
    tail = text[pos:].strip()
    if tail:
        tokens.append(Token(tail))
    return tokens


def _apply_market_extraction(tokens: List[Token]) -> List[Token]:
    """Step 4: 对非代码/非全名 token 做市场关键词提取 + 股份消歧。"""
    result: List[Token] = []
    for t in tokens:
        if _is_identified_token(t):
            result.append(t)
        else:
            result.extend(_split_market_tokens(t.text))
    return result


# ── Step 5: 无歧义关键词提取 ──────────────────────────────────────────────

def _tokenize_by_clean_keywords(text: str) -> List[Token]:
    """Step 5 子函数：无歧义关键词分词，间隙保留为空 tag token 交 Step 6。"""
    tokens: List[Token] = []
    pos = 0
    for m in _CLEAN_KEYWORDS_PATTERN.finditer(text):
        gap = text[pos:m.start()].strip()
        if gap:
            tokens.append(Token(gap))
        tokens.append(Token(m.group(), _classify_keyword(m.group())))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        tokens.append(Token(tail))
    return tokens


def _apply_clean_keyword_extraction(tokens: List[Token]) -> List[Token]:
    """Step 5: 对未识别 token 用无歧义关键词（如"分析""走势""怎样"）分词。"""
    result: List[Token] = []
    for t in tokens:
        if _is_identified_token(t):
            result.append(t)
        else:
            result.extend(_tokenize_by_clean_keywords(t.text))
    return result


# ── Step 6 调用入口 — 直接走多策略智能匹配 ──────────────────


def _isAlpha(s: str) -> bool:
    """检测字符串是否为纯英文字母（a-z, A-Z）。"""
    return bool(s) and all(c.isascii() and c.isalpha() for c in s)


def _dfs_match(text: str) -> Optional[List[Token]]:
    """深度优先全匹配：0 位置起匹配关键词/股票名并递归剩余文本；无法全匹配返回 None（宁可不做也不做错）。"""
    if len(text) == 0:
        return []
    
    # 以字母开头：提取连续英文字母组成的单词
    if _isAlpha(text[0]):
        # 直接组成连续的最大单词 例如 "Alibaba的基本面" → "Alibaba", "的基本面"
        i = 1
        while i < len(text) and _isAlpha(text[i]):
            i += 1
        segment = text[:i]
        # 纯英文 做 股票名拼音检测 和 美国股票代码检测
        stock_list = resolver_name_to_code_list(segment) + US_stock_code_match(segment)
        if stock_list:
            rest = _dfs_match(text[i:])
            if rest is not None:
                return [Token(segment, TAG_STOCK_NAME, stocks=stock_list)] + rest

    # 尝试连续 2~4 汉字片段（优先长匹配）
    for length in (4, 3, 2, 1):
        if length > len(text):
            continue
        segment = text[:length]

        # 不分割连续的字母
        if _isAlpha(segment[-1]) and length < len(text) and _isAlpha(text[length]):
            continue

        # 递归搜索匹配，策略不变
        tag = _classify_keyword(segment)  # 全部关键词（clean + extend）
        stock_list = []
        if not tag:
            stock_list = resolver_name_to_code_list(segment)
        if tag or len(stock_list) > 0:
            rest = _dfs_match(text[length:])
            if rest is not None:
                return [Token(segment, tag or TAG_STOCK_NAME, stocks=stock_list or None)] + rest

    return None


# 动态混合匹配文本
def _multi_match(text: str) -> List[Token]:
    """多策略智能匹配：DFS 匹配 2~4 字关键词/名字子串；无法完全匹配则原样返回（宁可不做也不做错）。"""
    if not text:
        return []
    result = _dfs_match(text)
    return result if result is not None else [Token(text)]

def _apply_multi_extraction(tokens: List[Token]) -> List[Token]:
    """Step 6: 对每个空 tag token 做多策略智能匹配，已打 tag 的 token 受保护。"""
    result: List[Token] = []
    for t in tokens:
        if t.tag:
            result.append(t)
        else:
            result.extend(_multi_match(t.text))
    return result


def _is_identified_token(token: Token) -> bool:
    """Token 是否已被前序步骤识别（有 tag 或是已知股票名/代码）。"""
    if token.tag:
        return True
    if is_known_stock_name(token.text):
        return True
    return False


def _split_by_special_punct(text: str) -> List[Token]:
    """按特殊标点边界切分（排除 * 和 -）；标点本身留作空 tag token，后续 _HAS_CONTENT_PATTERN 过滤。"""
    if not text:
        return []
    tokens: List[Token] = []
    pos = 0
    for m in _SPECIAL_PUNCT_RE.finditer(text):
        if pos < m.start():
            gap = text[pos:m.start()].strip()
            if gap:
                tokens.append(Token(gap))
        tokens.append(Token(m.group()))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        tokens.append(Token(tail))
    return tokens


def _preprocess_text(text: str) -> Tuple[str, List[Token]]:
    """六步管道分词，返回 (原文本, token列表)。

    Step 1 标点切分 → Step 2 代码形（unknown_code，≤4 位裸数字 → unknown_number）→
    Step 3 多股票实体扫描（全名精确匹配）→ Step 4 市场关键词 → Step 5 无歧义
    关键词 → Step 6 多策略匹配。unknown_code 由 _identify_stock_codes 辨认为
    stock_code/wrong_code，或保留交 LLM。

    Step 6 前先用 AkShare 全量 A 股扩充本地名称库（extend_AkShare，30 分钟缓存，
    全模块唯一的扩展调用点）：首次扩展并入新条目（返回 True）时，对未识别 token
    重跑 Step 3 全名精确扫描，库外真实 A 股（酒鬼酒/三花智控等）以确定实体标签
    进入 Step 6；已扩展过（返回 False）直接跳过，零网络、零重复遍历。
    """
    # ---- 六步管道 ----
    tokens = _split_by_special_punct(text)          # Step 1: 特殊标点符号提取和分词（排除 * - .）
    tokens = _apply_code_extraction(tokens)         # Step 2: 代码形字符串（unknown_code）
    tokens = _apply_full_name_extraction(tokens)    # Step 3: 股票全名匹配（本地静态库）
    tokens = _apply_market_extraction(tokens)       # Step 4: 市场关键词
    tokens = _apply_clean_keyword_extraction(tokens)  # Step 5: 无歧义关键词
    # Step 6 前：AkShare 扩展本地名称库。首次扩展并入新条目（True）时对未识别
    # token 重跑全名精确扫描，扩展名以确定实体标签进入 Step 6；已扩展（False）跳过。
    if extend_AkShare():
        tokens = _apply_full_name_extraction(tokens)
    tokens = _apply_multi_extraction(tokens)        # Step 6: 多策略子串智能匹配

    # 过滤纯标点/空白 token
    tokens = [t for t in tokens if t.text.strip() and _HAS_CONTENT_PATTERN.search(t.text)]

    return text, tokens

def _validate_code_candidate(text: str) -> Optional[bool]:
    """单个代码形字符串的合法性校验（_identify_stock_codes 专用）。

    数字代码沿用 extract_stock_codes 格式判定（6 位 A 股 0/3/6/4/8 首码、5 位港股、
    显式交易所形态 → stock_code；777777/SH1 等 → wrong_code）。
    美股 ticker 仅本地库命中（US_stock_code_match）→ stock_code；库外（SOFI）→
    None 保留 unknown_code 交 LLM，绝不硬猜。
    ≤4 位裸数字不会到达本函数（已在 _split_by_codes 标记为 unknown_number）。

    Returns: True → stock_code；False → wrong_code；None → 保持 unknown_code
    """
    if any(ch.isdigit() for ch in text):
        # 数字代码：沿用原 extract_stock_codes 格式判定（不查库，纯格式）
        return True if extract_stock_codes(text) else False

    # 纯字母 → 美股 ticker（含 .us/.X 后缀）：仅本地库命中才认可，
    # 库外美股（如 SOFI）保留 unknown_code 交由下游 LLM 判断。
    ticker = text.split(".", 1)[0].upper()
    return True if US_stock_code_match(ticker) else None


def _identify_stock_codes(tokens: List[Token]) -> List[Token]:
    """对 TAG_UNKNOWN_CODE 做格式校验 → stock_code / wrong_code，或保留 unknown_code 交 LLM。"""
    result: List[Token] = []
    for t in tokens:
        if t.tag != TAG_UNKNOWN_CODE:
            result.append(t)
            continue
        verdict = _validate_code_candidate(t.text)
        if verdict is True:
            result.append(Token(t.text, TAG_STOCK_CODE))
        elif verdict is False:
            result.append(Token(t.text, TAG_WRONG_CODE))
        else:
            result.append(t)  # 存疑：保持 unknown_code，交由下游 LLM 判断
    return result


def _normalize_intent_label(value: Any) -> Optional[str]:
    """规范化 LLM 返回的意图标签（去首尾空白、转小写、连字符/空格统一为下划线、去尾部标点）。"""
    if not isinstance(value, str):
        return None
    label = value.strip().lower().replace(" ", "_").replace("-", "_")
    label = label.strip(".,;:!?。，；：！？")
    return label or None


def _extract_json_object(text: str) -> Optional[str]:
    """从 LLM 噪声输出中提取第一个完整 JSON 对象（处理嵌套与字符串内花括号）。"""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _load_json_object(text: str) -> Any:
    """先严格 json.loads，失败再回退到提取内容中的 JSON 对象。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fragment = _extract_json_object(text)
    if fragment is None:
        return None
    try:
        return json.loads(fragment)
    except json.JSONDecodeError:
        return None


def _parse_llm_payload(raw: str) -> Optional[Dict[str, Any]]:
    """解析 LLM 返回的 JSON 负载：处理空串/BOM/markdown 围栏/夹杂文字，
    规范化 market（变体统一为 Market 枚举）与 stock_mentions（字符串转列表、
    过滤空白）。无 intent 字段或解析失败 → 记告警返回 None。
    """

    # market 字段规范化：LLM 各种变体 → Market 枚举
    _MARKET_NORMALIZE: Dict[str, Optional[Market]] = {
        "a": Market.A, "a_share": Market.A, "a股": Market.A,
        "ashare": Market.A, "a-share": Market.A, "ashares": Market.A,
        "shanghai": Market.A, "shenzhen": Market.A,
        "hk": Market.HK, "港股": Market.HK,
        "hongkong": Market.HK, "hong_kong": Market.HK,
        "h-share": Market.HK, "hshare": Market.HK,
        "us": Market.US, "美股": Market.US,
        "american": Market.US, "america": Market.US, "usa": Market.US,
    }

    cleaned = (raw or "").strip().lstrip("\ufeff")
    if not cleaned:
        return None
    # 处理 LLM 常见的 markdown 代码块包裹（可能带 ```json 前缀，或结尾夹带解释文字）
    if "```" in cleaned:
        cleaned = re.sub(r"```(?:json|JSON)?\s*", "", cleaned).strip()
    result = _load_json_object(cleaned)
    if result is None:
        logger.warning("[WebIntent] unparseable LLM payload: %s", cleaned[:200])
        return None
    # 最终校验：必须是一个包含 "intent" 键的字典
    if isinstance(result, dict) and "intent" in result:
        # 规范化 market 字段
        if "market" in result and result["market"]:
            raw_market = str(result["market"]).strip().lower()
            result["market"] = _MARKET_NORMALIZE.get(raw_market)
        else:
            result["market"] = None
        # 规范化 stock_mentions：字符串单提及 → 列表；过滤非字符串/空白条目
        mentions = result.get("stock_mentions")
        if isinstance(mentions, str):
            mentions = [mentions]
        if isinstance(mentions, list):
            result["stock_mentions"] = [
                m.strip() for m in mentions if isinstance(m, str) and m.strip()
            ]
        else:
            result["stock_mentions"] = []
        return result
    logger.warning("[WebIntent] unexpected LLM payload: %s", cleaned[:200])
    return None


def _has_competing_intent(tokens: List[Token], candidate_codes: set) -> bool:
    """弱子串确认的守卫：消息是否携带与"确认"竞争的意图锚点。

    仅"包含"候选名称的消息若同时带研究/追问/对比/提问等意图关键词，或提及
    候选以外的股票（代码/名称），说明它不是纯粹的确认回复（如"再分析下阿里
    巴巴最近走势"、"阿里巴巴和腾讯对比一下"），应按新消息重新分类，绝不静默
    确认候选列表中的第一只。
    """
    for t in tokens:
        if t.tag in (
            TAG_REQUEST, TAG_SUBJECT_RESEARCH, TAG_ACTION_RESEARCH,
            TAG_FOLLOWUP, TAG_COMPARISON, TAG_QUESTION,
        ):
            return True
        if t.tag in (TAG_STOCK_CODE, TAG_WRONG_CODE):
            if t.text.lower() not in candidate_codes:
                return True
        elif t.tag == TAG_STOCK_NAME and t.stocks:
            if any(s.code.lower() not in candidate_codes for s in t.stocks):
                return True
    return False


# =========================================================================
# WebIntentResolver — 核心意图解析器
# =========================================================================

class WebIntentResolver:
    """Web Chat 单条消息的意图解析器。

    == 整体流程（六步管道）==
    resolve() 采用"廉价优先、逐层升级"的级联架构：

      1. 空消息短路 → general_chat（置信度 1.0），最廉价、最确定的短路路径。
      2. 分词 + 实体识别（_preprocess_text 六步管道）：
         产出代码（stock_code/wrong_code）、已知名称（含歧义候选）、
         市场、意图关键词等 token 与实体信号。
      3. 消费待确认动作：用户对上一轮 action_required 的回复（选代码/名称/
         市场）直接确认，仅消费紧邻的下一轮。
      4. 基于 token 的规则分类：证据充分（识别率全 + 置信度高）时直接定论
         返回，绝不调用 LLM；证据不足时返回 None 升级 LLM。
      5. LLM 兜底：仅规则无解时调用，单次、超时即止损，超时/失败静默降级。
      6. 规则兜底：规则与 LLM 均无法判定时，返回最保守的 general_chat，
         不阻塞对话、不改变原有行为。
    """

    def __init__(self, config: Any = None, *, llm_adapter: Any = None, llm_timeout: float = 8.0):
        """config: 全局配置（懒加载 LLM 适配器）；llm_adapter: 预建适配器（测试注入）；
        llm_timeout: 意图分类超时秒数（在首 token 延迟关键路径上，超时自动降级规则兜底）。"""
        self._config = config
        self._llm_adapter = llm_adapter        # 可注入的 LLM 适配器（便于测试）
        self.llm_timeout = llm_timeout

    # ------------------------------------------------------------------
    # resolve() — 主入口
    # ------------------------------------------------------------------

    def resolve(
        self,
        message: str,
        *,
        session_context: Optional[Dict[str, Any]] = None,
        request_context: Optional[Dict[str, Any]] = None,
    ) -> WebIntentResolution:
        """解析一条用户消息的意图（模块主入口，SSE 层调用后据此执行/确认/提示）。

        session_context: 会话级上下文（pending_actions / recent_stocks）。
        request_context: 单次请求上下文，stock_code 为 #1619 当前锁定值，优先级高于 session。
        """
        # ===== 输入规范化 =====

        # None → 空串并去空白
        text = (message or "").strip()
        # 防御非 dict 的调用方
        session_context = session_context if isinstance(session_context, dict) else {}
        request_context = request_context if isinstance(request_context, dict) else {}

        # ===== 步骤 1: 空消息短路 → 闲聊（最廉价、最确定的路径） =====

        if not text:
            empty = WebIntentResolution(
                intent=WebIntent.GENERAL_CHAT,
                confidence=1.0,          # 无歧义，置信度最高
                reason="empty_message",
            )
            _log_resolution("empty", empty)
            return empty

        # ===== 步骤 2: 分词 + 实体识别（六步管道） =====
        text, tokens = _preprocess_text(text)
        tokens = _identify_stock_codes(tokens)  # 可能耗时

        # ===== 步骤 3: 消费待确认动作（仅紧邻的下一轮，未命中按新消息处理） =====
        confirmed = self._consume_pending_action(text, tokens, session_context)
        if confirmed is not None:
            _log_resolution("confirmation", confirmed)
            return confirmed

        # ===== 步骤 4: 规则分类（证据充分直接定论，否则升级 LLM） =====
        logger.debug(
            "[WebIntent] tokens=%s rate=%.2f",
            [t.text for t in tokens], _recognition_rate(tokens),
        )
        rule_result = self._classify_by_rules(tokens, text, session_context, request_context)
        if rule_result is not None:
            _log_resolution("rule", rule_result)
            return rule_result

        # ===== 步骤 5: LLM 兜底（单次、超时即止损） =====
        llm_result = self._classify_by_llm(text, session_context, request_context)
        if llm_result is not None:
            _log_resolution("llm", llm_result)
            return llm_result

        # ===== 步骤 6: 静默降级 → 最保守 general_chat，不阻塞对话 =====
        fallback = WebIntentResolution(
            intent=WebIntent.GENERAL_CHAT,
            confidence=0.6,
            reason="rule_fallback",
        )
        _log_resolution("fallback", fallback)
        return fallback

    # ------------------------------------------------------------------
    # 步骤 3 辅助 — 待确认动作消费
    # ------------------------------------------------------------------

    def _consume_pending_action(
        self,
        text: str,
        tokens: List[Token],
        session_context: Dict[str, Any],
    ) -> Optional[WebIntentResolution]:
        """消费上一轮遗留的 confirm_stock 待确认动作。

        判定顺序（证据强度递减）：
          1. 整条回复精确等于候选代码 → 直接确认；
          2. 整条回复精确等于候选名称 → 名称在候选中唯一时确认
             （同名跨市场候选无法靠名称区分，不确认）；
          3. 市场词把候选收窄到唯一一只 → 确认（优先于弱子串匹配，
             "美股阿里巴巴"不会被"阿里巴巴"子串抢先命中成 09988）；
          4. 回复仅"包含"候选名称 → 仅当其不含其他意图锚点（研究/追问/
             对比/提问/其他股票）时才视为确认，否则按新消息重新分类
             （"阿里巴巴和腾讯对比一下"、"再分析下阿里巴巴最近走势"），
             绝不静默选第一只。
        未命中返回 None，动作按新消息自然清空。
        """
        pending = session_context.get(PENDING_ACTIONS_KEY) or []
        if not pending:
            return None
        action = pending[0]
        if not isinstance(action, dict) or action.get("action") != "confirm_stock":
            return None
        candidates = [
            Stock(c["code"], c.get("name", ""), c.get("market", ""))
            for c in (action.get("candidates") or [])
            if isinstance(c, dict) and c.get("code")
        ]
        # 原请求中已解析的股票（如"对比阿里巴巴和腾讯控股"中的腾讯 00700）在
        # 确认后必须保留，否则确认消费只注入被选中的候选，比较/多股语义丢失
        resolved_stocks = [
            Stock(c["code"], c.get("name", ""), c.get("market", ""))
            for c in (action.get("resolved_stocks") or [])
            if isinstance(c, dict) and c.get("code")
        ]
        if not candidates:
            # 低置信度确认（无候选）→ 用户的下一条消息按新消息重新分类
            return None
        original_request = action.get("original_request") or ""
        stripped = text.strip()

        # 1) 整条消息精确等于候选代码 → 无歧义，直接确认
        for cand in candidates:
            if stripped.lower() == cand.code.lower():
                return self._confirmed_resolution(cand, resolved_stocks, original_request)

        # 2) 整条消息精确等于候选名称 → 仅当该名称在候选中唯一（同名跨市场
        #    候选如 09988/BABA 都叫"阿里巴巴"无法靠名称区分，不确认）
        named = [c for c in candidates if c.name and stripped == c.name]
        if len(named) == 1:
            return self._confirmed_resolution(named[0], resolved_stocks, original_request)

        # 3) 市场词收窄：回复含明确市场信号且收窄到唯一候选 → 确认。
        #    必须优先于"名称子串"匹配，否则"美股阿里巴巴"会被第一只候选
        #    的"阿里巴巴"子串抢先确认，忽略美股提示。
        #    同时必须跳过带竞争意图锚点的消息（研究/追问/对比/其他股票），
        #    否则"帮我分析一下港股腾讯"会被"港股"抢先确认成 09988，把用户
        #    对腾讯的新请求吞掉（与分支 4 一致）。
        markets = _detect_markets(text)
        if markets and not _has_competing_intent(tokens, {c.code.lower() for c in candidates}):
            filtered = [c for c in candidates if c.market in markets]
            if len(filtered) == 1:
                return self._confirmed_resolution(filtered[0], resolved_stocks, original_request)

        # 4) 弱子串匹配：消息包含候选名称 → 仅当无竞争意图锚点时才视为确认；
        #    含研究/追问/对比/提问/其他股票 → 按新消息重新分类，绝不静默猜第一只
        if not _has_competing_intent(tokens, {c.code.lower() for c in candidates}):
            for cand in candidates:
                if cand.name and cand.name in text:
                    same_name = [c for c in candidates if c.name == cand.name]
                    if len(same_name) > 1:
                        # 同名跨市场候选无法由名称区分 → 不确认，交由重分类
                        return None
                    return self._confirmed_resolution(cand, resolved_stocks, original_request)
        return None

    @staticmethod
    def _confirmed_resolution(
        cand: Stock,
        resolved_stocks: List[Stock],
        original_request: str = "",
    ) -> WebIntentResolution:
        """用户确认候选股票后的确定性结果。

        确认的候选与原请求中已解析的股票合并保留（如"对比阿里巴巴和腾讯控股"
        确认港股阿里后仍保留腾讯 00700，多股比较语义不丢失）；original_request
        携带原请求文本，供 SSE 层把比较语义显式传入本轮执行。
        """
        stocks = _dedup_stocks([cand] + list(resolved_stocks))
        return WebIntentResolution(
            intent=WebIntent.STOCK_RESEARCH,
            confidence=0.95,
            source="confirmation",
            stocks=stocks,
            reason="confirmed_stock",
            original_request=original_request,
        )

    # ------------------------------------------------------------------
    # 步骤 4 辅助 — 规则分类
    # ------------------------------------------------------------------

    def _classify_by_rules(
        self,
        tokens: List[Token],
        text: str,
        session_context: Dict[str, Any],
        request_context: Dict[str, Any],
    ) -> Optional[WebIntentResolution]:
        """基于 token 的规则分类，按证据强度递减判定。

        命中明确证据即返回定论（置信度为路径常量）；无证据返回 None 交 LLM。规则路径绝不产生模糊结果。
        """
        # 持仓优先级最高
        if any(t.tag in (TAG_SUBJECT_PORTFOLIO, TAG_ACTION_PORTFOLIO) for t in tokens):
            return WebIntentResolution(
                intent=WebIntent.PORTFOLIO_REVIEW,
                confidence=0.85,           # 关键词命中
                reason="portfolio_keyword",
            )

        # 存疑代码 token（unknown_code）且带研究/追问等股票锚点 → 规则无法安全定论，
        # 升级 LLM（宁可不做也不做错）；纯板块/市场语境不升级
        if any(t.tag == TAG_UNKNOWN_CODE for t in tokens):
            has_stock_anchor = any(
                t.tag in (TAG_REQUEST, TAG_FOLLOWUP, TAG_STOCK_CODE, TAG_WRONG_CODE, TAG_STOCK_NAME)
                for t in tokens
            )
            has_market_context = any(
                t.tag in (TAG_SECTOR, TAG_SUBJECT_MARKET_BROAD, TAG_SUBJECT_INDEX)
                for t in tokens
            )
            if has_stock_anchor and not has_market_context:
                return None

        stocks: List[Stock] = []
        candidates: List[Stock] = []
        wrong_codes: List[str] = []
        for t in tokens:
            if t.tag == TAG_STOCK_CODE:
                stocks.append(Stock(t.text))
            elif t.tag == TAG_STOCK_NAME and t.stocks:
                if len(t.stocks) == 1:
                    stocks.append(t.stocks[0])
                else:
                    candidates.extend(t.stocks)
            elif t.tag == TAG_WRONG_CODE:
                wrong_codes.append(t.text)

        # 名称歧义 → 待确认
        if candidates:
            candidates = _dedup_stocks(candidates)
            stocks = _dedup_stocks(stocks)
            pending = {
                "action": "confirm_stock",
                "candidates": _candidates_to_dicts(candidates),
            }
            if stocks:
                # 原请求中已解析的股票（如"对比阿里巴巴和腾讯控股"中的腾讯 00700）
                # 必须在确认后保留，否则确认消费只注入被选中的候选、比较语义丢失
                pending["resolved_stocks"] = _candidates_to_dicts(stocks)
            if text:
                # 保留原始请求文本，确认消费后执行端可据此还原多股比较语义
                pending["original_request"] = text
            return WebIntentResolution(
                intent=WebIntent.STOCK_RESEARCH,
                confidence=0.85,
                stocks=stocks,
                candidates=candidates,
                needs_confirmation=True,
                reason="ambiguous_stock_name",
                pending_action=pending,
            )

        # 显式代码/唯一已解析名称 → 直接定论个股研究
        if stocks:
            return WebIntentResolution(
                intent=WebIntent.STOCK_RESEARCH,
                confidence=0.9,            # 显式代码
                stocks=_dedup_stocks(stocks),
                reason="explicit_stock",
            )

        # 无效代码/裸数字 → 个股研究但无法解析，需确认；旁有市场/指数上下文
        # （"沪深300" 被拆成 沪深+300）→ 大盘行情；无市场上下文不触发确认，绝不把数字当股票代码
        if wrong_codes or any(t.tag == TAG_UNKNOWN_NUMBER for t in tokens):
            if any(t.tag in (TAG_SUBJECT_MARKET, TAG_SUBJECT_MARKET_BROAD, TAG_SUBJECT_INDEX) for t in tokens):
                markets = _extract_markets_from_tokens(tokens)
                return WebIntentResolution(
                    intent=WebIntent.MARKET_OVERVIEW,
                    confidence=0.85,
                    reason="market_keyword",
                    market=markets[0] if markets else None,
                )
            if wrong_codes:
                return WebIntentResolution(
                    intent=WebIntent.STOCK_RESEARCH,
                    confidence=0.8,
                    unresolved_names=wrong_codes,
                    needs_confirmation=True,
                    reason="stock_unresolved",
                    pending_action={"action": "confirm_stock", "unresolved_names": wrong_codes},
                )

        # 市场/指数/板块关键词 → 大盘行情
        if any(t.tag in (TAG_SUBJECT_MARKET_BROAD, TAG_SUBJECT_INDEX, TAG_SECTOR) for t in tokens):
            markets = _extract_markets_from_tokens(tokens)
            return WebIntentResolution(
                intent=WebIntent.MARKET_OVERVIEW,
                confidence=0.85,
                reason="market_keyword",
                market=markets[0] if markets else None,
            )

        # 追问/研究 + 继承股票 → 对上一轮分析的追问
        inherited = self._inherit_current_stock(session_context, request_context)
        if inherited and any(
            t.tag in (TAG_FOLLOWUP, TAG_REQUEST) for t in tokens
        ):
            # 例外：研究请求含未识别 token（如"你好股份"）→ 升级 LLM，不误继承当前股票
            if _research_request_with_unresolved(tokens):
                return None
            return WebIntentResolution(
                intent=WebIntent.HISTORY_FOLLOWUP,
                confidence=0.8,
                inherited_stock_code=inherited,
                reason="followup_inherit",
            )

        # 完全无识别：无上下文 → 闲聊；有上下文（可能追问）→ 升级 LLM
        if _recognition_rate(tokens) == 0.0:
            if not self._inherit_current_stock(session_context, request_context) \
                    and not session_context.get(LAST_INTENT_KEY):
                return WebIntentResolution(
                    intent=WebIntent.GENERAL_CHAT,
                    confidence=0.9,
                    reason="no_signal",
                )
            return None

        # 证据不足 → 升级 LLM
        return None

    @staticmethod
    def _inherit_current_stock(
        session_context: Dict[str, Any],
        request_context: Dict[str, Any],
    ) -> str:
        """继承当前关注股票：#1619 请求级 stock_code 优先，其次 session recent_stocks 首位。
        规则分类的股票分支在前，天然排除本轮显式代码。"""
        code = (request_context.get("stock_code") or "").strip()
        if code:
            return code
        recent = session_context.get(RECENT_STOCKS_KEY) or []
        return recent[0] if recent and isinstance(recent[0], str) else ""

    # ------------------------------------------------------------------
    # 步骤 5 辅助 — LLM 兜底
    # ------------------------------------------------------------------

    def _get_llm_adapter(self) -> Any:
        """懒加载 LLM 适配器（仅规则无解时才创建，避免无谓初始化 litellm）。"""
        if self._llm_adapter is None and self._config is not None:
            from src.agent.llm_adapter import LLMToolAdapter
            self._llm_adapter = LLMToolAdapter(self._config)
        return self._llm_adapter

    def _classify_by_llm(
        self,
        text: str,
        session_context: Dict[str, Any],
        request_context: Dict[str, Any],
    ) -> Optional[WebIntentResolution]:
        """LLM 意图分类兜底：单次调用、超时即止损，任何失败返回 None 静默降级。"""
        adapter = self._get_llm_adapter()
        if adapter is None:
            return None
        try:
            # is_available 在真实适配器上是 property（返回 bool），
            # 兼容方法形态（旧版/测试桩）两种接口
            available = getattr(adapter, "is_available", True)
            if callable(available):
                available = available()
            if not available:
                return None
            ctx_lines = []
            prev = session_context.get(LAST_INTENT_KEY)
            if prev:
                ctx_lines.append(f"- previous_intent: {prev}")
            recent = session_context.get(RECENT_STOCKS_KEY) or []
            if recent:
                ctx_lines.append(f"- recent_stocks: {', '.join(str(c) for c in recent[:5])}")
            focus = (request_context.get("stock_code") or "").strip()
            if focus:
                ctx_lines.append(f"- current_focus_stock: {focus}")
            user_content = f"User: {text}"
            if ctx_lines:
                user_content += "\n\nConversation context:\n" + "\n".join(ctx_lines)

            # 将 src.data.stock_mapping 的 STOCK_NAME_MAP，塞进 prompt 辅助命名实体识别(槽位识别)
            system_prompt = _INTENT_PARSE_PROMPT + "\n\nStock mapping (code - name):\n" + json.dumps(STOCK_NAME_MAP, ensure_ascii=False)

            resp = self._call_llm_with_retry(adapter, system_prompt, user_content)
            payload = _parse_llm_payload(resp.content)
            if payload is None:
                return None
            return self._build_llm_resolution(payload, session_context, request_context)
        except Exception as exc:
            # 静默降级：只记一行告警（异常类型即可），不输出完整堆栈，不阻塞对话
            logger.warning("[WebIntent] LLM classification failed (%s), falling back to rules", exc.__class__.__name__)
            return None

    def _call_llm_with_retry(
        self,
        adapter: Any,
        system_prompt: str,
        user_content: str,
    ) -> Any:
        """单次意图分类调用，瞬断（超时）错误重试一次；鉴权/配置等永久性错误不重试。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        for attempt in range(2):
            resp = adapter.call_text(messages, timeout=self.llm_timeout)
            if not self._is_transient_llm_error(resp):
                return resp
            if attempt == 0:
                logger.warning(
                    "[WebIntent] LLM call transient failure, retrying once: %s",
                    (getattr(resp, "content", "") or "")[:120],
                )
        return resp

    @staticmethod
    def _is_transient_llm_error(resp: Any) -> bool:
        """判断 LLM 响应是否为可重试的瞬断错误（连接/读写超时）。"""
        if resp is None or getattr(resp, "provider", "") != "error":
            return False
        text = (getattr(resp, "content", "") or "").lower()
        return "timeout" in text or "timed out" in text

    def _build_llm_resolution(
        self,
        payload: Dict[str, Any],
        session_context: Dict[str, Any],
        request_context: Dict[str, Any],
    ) -> Optional[WebIntentResolution]:
        """将 LLM JSON 负载组装为 WebIntentResolution。

        意图标签规范化；置信度封顶 LLM_CONFIDENCE_CAP（非数值按 0.5）；执行类意图
        低置信度（<0.6）转确认；提及歧义/解析不出进 unresolved（AkShare 全量 A 股
        已在分词阶段并入本地库，此处只查库，绝不虚构代码）；追问意图未提及新股票
        时继承当前股票。
        """
        intent = _normalize_intent_label(payload.get("intent"))
        if intent not in ALL_WEB_INTENTS:
            logger.warning("[WebIntent] LLM returned invalid intent %r", payload.get("intent"))
            return None
        try:
            confidence = min(float(payload.get("confidence") or 0.5), LLM_CONFIDENCE_CAP)
        except (TypeError, ValueError):
            confidence = min(0.5, LLM_CONFIDENCE_CAP)
        # stock_mentions 已是 LLM 识别结果，本地库解析只做规范化与消歧增强
        market = payload.get("market")
        stocks, candidates, unresolved = self._resolve_mentions(
            payload.get("stock_mentions") or []
        )
        # 用 LLM 市场推断打破跨市场同名歧义：候选恰好只有一只与推断市场一致时直接采纳
        if market and candidates and not stocks:
            market_filtered = [c for c in candidates if c.market == market]
            if len(market_filtered) == 1:
                candidates = []
                stocks = market_filtered
        resolution = WebIntentResolution(
            intent=WebIntent(intent),
            confidence=confidence,
            source="llm",
            stocks=stocks,
            candidates=candidates,
            unresolved_names=unresolved,
            market=payload.get("market"),
        )
        if (
            resolution.intent == WebIntent.HISTORY_FOLLOWUP
            and not stocks
            and not candidates
        ):
            # 追问且未提及新股票：继承当前股票，保持 #1619 股票锁定
            resolution.inherited_stock_code = self._inherit_current_stock(
                session_context, request_context
            )
        if resolution.intent in _EXECUTING_INTENTS and confidence < CONFIRMATION_CONFIDENCE_THRESHOLD:
            resolution.needs_confirmation = True
            resolution.reason = "low_confidence"
            resolution.pending_action = {"action": "confirm_stock", "reason": "low_confidence"}
        elif (
            resolution.intent == WebIntent.STOCK_RESEARCH
            and (candidates or unresolved)
        ):
            # 与规则路径（_classify_by_rules 歧义分支）保持同一契约：提及有歧义/
            # 未解析股票即转确认，且已解析的股票一并保留在 pending_action 中，
            # 确认消费后与所选候选合并，不静默丢失多股比较的其它标的。
            resolution.needs_confirmation = True
            resolution.reason = "ambiguous_stock_name" if candidates else "stock_unresolved"
            pending = {
                "action": "confirm_stock",
                "candidates": _candidates_to_dicts(candidates),
                "unresolved_names": unresolved,
            }
            if stocks:
                pending["resolved_stocks"] = _candidates_to_dicts(stocks)
            resolution.pending_action = pending
        return resolution

    @staticmethod
    def _resolve_mentions(
        mentions: List[str],
    ) -> Tuple[List[Stock], List[Stock], List[str]]:
        """将 LLM 提取的股票提及转为 (唯一股票, 歧义候选, 未解析名称)。

        AkShare 全量 A 股已在分词阶段（_preprocess_text Step 6 前）并入本地库，
        这里只查库、不再次扩展；解析不出进 unresolved，绝不虚构代码。
        """
        stocks: List[Stock] = []
        candidates: List[Stock] = []
        unresolved: List[str] = []
        for mention in mentions:
            mention = (mention or "").strip()
            if not mention:
                continue
            codes = extract_stock_codes(mention)
            if codes:
                stocks.extend(Stock(code) for code in codes)
                continue
            matches = resolver_name_to_code_list(mention) + US_stock_code_match(mention)
            if len(matches) == 1:
                stocks.append(matches[0])
            elif len(matches) > 1:
                candidates.extend(matches)
            else:
                unresolved.append(mention)
        return _dedup_stocks(stocks), _dedup_stocks(candidates), unresolved
        

# =========================================================================
# 会话上下文持久化（conversation.py 的 session sink）
# =========================================================================


def apply_resolution_to_session(session: Any, resolution: WebIntentResolution) -> None:
    """将意图识别结果写入会话上下文（供下一轮步骤 3/4 读取）。

    - recent_stocks: 新代码 + 继承代码 + 已有代码，去重取前 MAX_RECENT_STOCKS 条，
      新代码在前保证最近使用的优先被继承。
    - last_intent: 本轮意图标签。
    - pending_actions: needs_confirmation 时写入确认动作，否则清空。
    session 用鸭子类型（getattr），避免循环依赖。
    """

    # 鸭子类型检测：确保 session 有 context 属性且为 dict
    context = getattr(session, "context", None)
    if not isinstance(context, dict):
        return  # 不兼容的 session 对象，静默跳过

    # 过滤非法元素后取已有最近股票
    existing = [
        code
        for code in (context.get(RECENT_STOCKS_KEY) or [])
        if isinstance(code, str) and code
    ]

    # 新代码 + 继承代码
    new_codes = [s.code for s in resolution.stocks]
    if resolution.inherited_stock_code:
        new_codes.append(resolution.inherited_stock_code)

    # 去重合并（保持插入顺序，新代码在前）
    merged: List[str] = []
    for code in new_codes + existing:
        if code not in merged:
            merged.append(code)

    # 写入上下文并裁剪上限
    session.update_context(RECENT_STOCKS_KEY, merged[:MAX_RECENT_STOCKS])
    session.update_context(LAST_INTENT_KEY, resolution.intent)

    # 待确认动作：有则写入覆盖，无则清空
    if resolution.needs_confirmation and resolution.pending_action:
        session.update_context(PENDING_ACTIONS_KEY, [resolution.pending_action])
    else:
        session.update_context(PENDING_ACTIONS_KEY, [])


def clear_pending_actions(session: Any) -> None:
    """清除会话中残留的待确认动作（确认流程失败时的清理入口）。

    apply_resolution_to_session 在 needs_confirmation 时先把 pending_actions
    写入会话；若随后澄清文本构建 / 会话历史写入失败，端点短路返回错误，
    必须同步清掉已写入的待确认状态，否则下一轮消息会被 _consume_pending_action
    误当成上一轮失败确认流程的回复，执行旧的歧义请求。
    """
    context = getattr(session, "context", None)
    if not isinstance(context, dict):
        return
    session.update_context(PENDING_ACTIONS_KEY, [])


# =========================================================================
# SSE 事件构建器（#1871 叠加合约）
# =========================================================================


def _candidates_to_dicts(candidates: List[Stock]) -> List[Dict[str, str]]:
    """将 Stock 候选列表转为前端可序列化的 dict 列表。"""
    return [{"code": stock.code, "name": stock.name, "market": stock.market} for stock in candidates]


def build_intent_resolved_event(resolution: WebIntentResolution) -> Dict[str, Any]:
    """构建 intent_resolved SSE 事件（Agent 开始工作前发送给前端）。

    约定：空列表字段序列化为 None 减少体积；confidence 保留两位小数去噪。
    """

    return stream_event(
        "intent_resolved",
        intent=resolution.intent,
        confidence=round(resolution.confidence, 2),
        source=resolution.source,
        stock_codes=[s.code for s in resolution.stocks] or None,
        candidates=_candidates_to_dicts(resolution.candidates) or None,
        inherited_stock_code=resolution.inherited_stock_code or None,
        needs_confirmation=resolution.needs_confirmation or None,
        market=resolution.market or None,
    )


def build_action_required_event(resolution: WebIntentResolution) -> Dict[str, Any]:
    """构建 action_required SSE 事件（needs_confirmation=True 时发送，前端展示确认界面）。

    message 由 build_clarification_message 生成，可直接展示给用户。
    """

    return stream_event(
        "action_required",
        action="confirm_stock",
        intent=resolution.intent,
        reason=resolution.reason or None,
        candidates=_candidates_to_dicts(resolution.candidates) or None,
        unresolved_names=resolution.unresolved_names or None,
        message=build_clarification_message(resolution),
    )


# 市场 → 中文标签（澄清提示用）
_MARKET_LABELS: Dict[Market, str] = {Market.A: "A股", Market.HK: "港股", Market.US: "美股"}


def build_clarification_message(resolution: WebIntentResolution) -> str:
    """构建面向用户的澄清提示文本。

    按优先级：1) 名称歧义 → 列出候选（最多 5 个）；2) 名称无法识别 → 提示检查拼写；
    3) 低置信度 → 引导补充意图方向；4) 默认 → 引导提供股票名称/代码。
    """

    # 场景 1: 歧义候选
    if resolution.candidates:
        lines = ["你说的股票可能指以下几只，请回复股票代码或名称确认："]
        for cand in resolution.candidates[:5]:  # 最多 5 个，避免信息过载
            label = _MARKET_LABELS.get(cand.market, cand.market)
            suffix = f"（{label}）" if label else ""
            lines.append(f"- {cand.code} {cand.name or ''}{suffix}".rstrip())
        return "\n".join(lines)

    # 场景 2: 名称无法识别
    if resolution.unresolved_names:
        names = "、".join(resolution.unresolved_names)
        return (
            f"没有查到「{names}」对应的股票，请确认名称是否正确，"
            "或直接提供股票代码（如 600519、hk00700、AAPL）。"
        )

    # 场景 3: 低置信度
    if resolution.reason == "low_confidence":
        return "我没有完全理解你的需求，请补充说明：想分析具体股票、查看持仓，还是了解大盘行情？"

    # 场景 4: 默认兜底
    return "请补充你想分析的股票名称或代码（如 600519、hk00700、AAPL）。"
