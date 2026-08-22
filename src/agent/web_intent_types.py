# -*- coding: utf-8 -*-
"""
Web Chat 意图识别层 — 类型与常量定义（Intent Types）。

== 模块定位 ==
web_intent 拆分为三模块，本模块是三者共享的"数据字典"：
  - ``web_intent_types.py``     — 意图枚举、WebIntentResolution、Token、
                                  tag/关键词/正则常量（本模块）；
  - ``web_intent_tokenizer.py`` — 六步分词管道与实体提取；
  - ``web_intent_resolver.py``  — WebIntentResolver 主流程、规则/LLM/确认消费、
                                  session/SSE 辅助（兼容入口 re-export 本模块）。

== 支持的意图类型 ==
- ``stock_research``     — 个股研究/分析
- ``portfolio_review``   — 持仓回顾
- ``market_overview``    — 大盘行情
- ``history_followup``   — 对上一轮分析的追问
- ``general_chat``       — 闲聊/与股票分析无关的问题

意图识别只产生一个轻量级标签 + 股票上下文，由 SSE 层据此行动：
先发送 ``intent_resolved``；置信度低或股票名称歧义时发送 ``action_required``
等待用户澄清；解析出的 ``stock_code`` 传递给 #1619 股票范围机制。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.services.name_to_code_resolver import Stock

__all__ = [
    "ALL_WEB_INTENTS",
    "CONFIRMATION_CONFIDENCE_THRESHOLD",
    "LAST_INTENT_KEY",
    "LLM_CONFIDENCE_CAP",
    "Market",
    "MAX_RECENT_STOCKS",
    "PENDING_ACTIONS_KEY",
    "RECENT_STOCKS_KEY",
    "Token",
    "WebIntent",
    "WebIntentResolution",
    "TAG_UNKNOWN_CODE",
    "TAG_UNKNOWN_NUMBER",
    "TAG_STOCK_CODE",
    "is_wrong_code_tag",
    "unknown_code_tag",
    "wrong_code_tag",
    "is_unknown_code_tag",
    "TAG_STOCK_NAME",
    "TAG_CODE_NAME",
    "TAG_SUBJECT_RESEARCH",
    "TAG_SUBJECT_PORTFOLIO",
    "TAG_SUBJECT_MARKET",
    "TAG_SUBJECT_MARKET_BROAD",
    "TAG_SUBJECT_INDEX",
    "TAG_REQUEST",
    "TAG_ACTION_RESEARCH",
    "TAG_ACTION_PORTFOLIO",
    "TAG_FOLLOWUP",
    "TAG_QUESTION",
    "TAG_COMPARISON",
    "TAG_SECTOR",
    "TAG_TIME",
    "TAG_FILLER",
]


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
TAG_UNKNOWN_CODE = "unknown_code"      # 待验证的代码形字符串，Step 2 提取的中间态，由 _identify_stock_codes 辨认
TAG_UNKNOWN_NUMBER = "unknown_number"  # 任意位裸数字（代码/指数/价格/年份/数量/日期…形态歧义），Step 2 直接标记，不进入代码校验
TAG_STOCK_CODE = "stock_code"          # 库命中的股票代码（stocks 附完整 code/name/market 三元组）

# 代码辨认失败态按市场细分（_identify_stock_codes 产出）：
#   wrong_{market}_code   — 确定不存在：形态非法（交易所静态规则），或该市场库已
#                           全量（A 股 AkShare 已并入）仍未命中
#   unknown_{market}_code — 存疑：该市场库非全量（hk/us 本地精选库）未命中，
#                           交下游 LLM 判断，绝不硬猜
_CODE_TAG_MARKETS = ("a", "hk", "us")


def wrong_code_tag(market: str) -> str:
    """确定非法代码的 tag（market ∈ a/hk/us → wrong_a_code / wrong_hk_code / wrong_us_code）。"""
    return f"wrong_{market}_code"


def unknown_code_tag(market: str) -> str:
    """存疑代码的 tag（market ∈ a/hk/us → unknown_a_code / unknown_hk_code / unknown_us_code）。"""
    return f"unknown_{market}_code"


def is_wrong_code_tag(tag: str) -> bool:
    """tag 是否属于确定非法代码族（wrong_{market}_code）。"""
    return isinstance(tag, str) and tag.startswith("wrong_") and tag.endswith("_code")


def is_unknown_code_tag(tag: str) -> bool:
    """tag 是否属于存疑代码族（Step 2 中间态 unknown_code + unknown_{market}_code）。"""
    return isinstance(tag, str) and tag.startswith("unknown_") and tag.endswith("_code")
TAG_STOCK_NAME = "stock_name"          # 股票实体（全名或一对一缩写），Step 3 仅全名精确匹配、Step 6 多策略匹配提取
TAG_CODE_NAME = "code_name"            # 空 tag 经 name_code_list 解析为股票名称后打此标签

# --- 意图主题 ---
TAG_SUBJECT_RESEARCH = "subject_research"       # 研究主题（走势/趋势/技术面/基本面/筹码）
TAG_SUBJECT_PORTFOLIO = "subject_portfolio"     # 持仓主题（持仓/仓位/自选股/盈亏）
TAG_SUBJECT_MARKET = "subject_market"           # 市场标识（A股/港股/美股/沪市…）
TAG_SUBJECT_MARKET_BROAD = "subject_market_broad"  # 泛市场概念（大盘/行情/指数/两市）
TAG_SUBJECT_INDEX = "subject_index"             # 具体指数（上证/恒生/纳斯达克/沪深300…）

# --- 动作 ---
TAG_REQUEST = "request"                       # 分析动作词（分析/看看/研究/诊断/查一下/评估）
TAG_ACTION_RESEARCH = "action_research"       # 研究决策（能买/可以买/止损/目标价/buy/sell）
TAG_ACTION_PORTFOLIO = "action_portfolio"     # 持仓操作（加仓/减仓/调仓/满仓/空仓）

# --- 辅助 ---
TAG_FOLLOWUP = "followup"     # 追问延续（继续/刚才/这只/它/上面/上次/该股）
TAG_QUESTION = "question"     # 疑问（怎么看/怎么样/涨还是跌/怎么/为何/吗/呢）
TAG_COMPARISON = "comparison"  # 对比（对比/比较/哪个好/vs/pk/二选一）
TAG_SECTOR = "sector"         # 板块/行业（新能源/半导体/消费/医药/AI…）
TAG_TIME = "time"             # 时间指示（今天/本周/交易日/实时）
TAG_FILLER = "filler"         # 回复填充词（单字独立匹配：的/买/卖/选/那/这…）

# 所有合法 tag 的不可变集合
_ALL_TAGS = frozenset({
    TAG_UNKNOWN_CODE, TAG_UNKNOWN_NUMBER, TAG_STOCK_CODE,
    *(wrong_code_tag(m) for m in _CODE_TAG_MARKETS),
    *(unknown_code_tag(m) for m in _CODE_TAG_MARKETS),
    TAG_STOCK_NAME, TAG_CODE_NAME,
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
        "走势", "走向", "涨势", "趋势", "技术面", "基本面", "筹码", "后市", "trend",
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
# Token — 分词结构体，text + tag
# =========================================================================


@dataclass(frozen=True)
class Token:
    """分词结构体：文本 + 语义标签 + 可选的已解析股票实体。

    frozen=True 使 Token 可哈希；tag 为空表示未识别；stocks 透传已解析实体避免下游重复解析。
    stocks 内部存 tuple（frozen 字段值必须可哈希，list 会让 hash(Token) 抛 TypeError），
    构造时传 list 会被 __post_init__ 归一，下游按序列消费不受影响。
    """
    text: str
    tag: str = ""
    stocks: Optional[Tuple["Stock", ...]] = None

    def __post_init__(self) -> None:
        if isinstance(self.stocks, list):
            object.__setattr__(self, "stocks", tuple(self.stocks))


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
