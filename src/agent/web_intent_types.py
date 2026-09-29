# -*- coding: utf-8 -*-
"""
Web Chat 意图识别层 — 分词模块的类型与常量（Intent Tokenizer Types）。

== 模块定位 ==
本模块是 ``web_intent_tokenizer.py`` 六步分词管道的"数据字典"：Token
结构、tag/关键词/正则常量。意图层定义（意图枚举、意图识别结果、置信度/
会话常量）随 ``web_intent_resolver.py`` 在后续 PR 引入。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from src.services.name_to_code_resolver import Stock

__all__ = [
    "Market",
    "Token",
    "TAG_UNKNOWN_CODE",
    "TAG_UNKNOWN_NUMBER",
    "TAG_STOCK_CODE",
    "unknown_code_tag",
    "wrong_code_tag",
    "TAG_STOCK_NAME",
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
    "TAG_SECTOR_NAME",
    "TAG_SECTOR_N_STOCK",
    "TAG_TIME",
    "TAG_FILLER",
    "TAG_CORP_SUFFIX",
]


# =========================================================================
# Token 语义标签常量 — 5 大类 21 个标签，近义词归入同一标签，供正则匹配使用
# =========================================================================

# --- 股票识别 ---
TAG_UNKNOWN_CODE = "unknown_code"      # 待验证的代码形字符串，Step 3 提取的中间态，由 _identify_stock_codes 辨认
TAG_UNKNOWN_NUMBER = "unknown_number"  # 任意位裸数字（代码/指数/价格/年份/数量/日期…形态歧义），Step 3 直接标记，不进入代码校验
TAG_STOCK_CODE = "stock_code"          # 库命中的股票代码（stocks 附完整 code/name/market 三元组）

# 代码辨认失败态按市场细分（_identify_stock_codes 产出）：
#   wrong_{market}_code   — 确定不存在：形态非法（交易所静态规则），或该市场库已
#                           全量（A 股 AkShare 已并入）仍未命中
#   unknown_{market}_code — 存疑：该市场库非全量（hk/us 本地精选库）未命中，
#                           交下游 LLM 判断，绝不硬猜


def wrong_code_tag(market: str) -> str:
    """确定非法代码的 tag（market ∈ a/hk/us → wrong_a_code / wrong_hk_code / wrong_us_code）。"""
    return f"wrong_{market}_code"


def unknown_code_tag(market: str) -> str:
    """存疑代码的 tag（market ∈ a/hk/us → unknown_a_code / unknown_hk_code / unknown_us_code）。"""
    return f"unknown_{market}_code"

TAG_STOCK_NAME = "stock_name"          # 股票实体（全名或一对一缩写），Step 1 仅全名精确匹配、Step 6 多策略匹配提取

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
TAG_SECTOR = "sector"          # 板块泛称词（板块/行业/赛道/概念/题材/龙头）+ XX+后缀 复合形态
TAG_SECTOR_NAME = "sector_name"        # 行业名（金融/建筑/证券/农业…），裸用即行业意图
TAG_SECTOR_N_STOCK = "sector_n_stock"  # 行业名兼股票全名（机器人=300024），裸用歧义交下游 LLM 消歧
TAG_TIME = "time"             # 时间指示（今天/本周/交易日/实时）
TAG_FILLER = "filler"         # 回复填充词（单字独立匹配：的/买/卖/选/那/这…）
TAG_CORP_SUFFIX = "corp_suffix"  # 通用公司后缀（公司/集团/控股/股份/国际）：零区分度，精确命中即跳过股票名匹配

class Market(str, Enum):
    """市场标识枚举（str 子类，成员可直接与字符串比较）。"""

    A = "a"    # A 股
    HK = "hk"  # 港股
    US = "us"  # 美股


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

# 按照是否影响股票实体混合匹配，关键词分两池：clean 无歧义可直接分词，置信度较高；
#       extend 可能与股票名混淆，增加分词多样性，但置信度较低，需要做交叉验证，否则宁可放弃。
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
        "上证", "深证", "创业板", 
        "恒指", "纳斯达克", "纳指",
        "标普", "道琼斯", "道指", 
        "沪指", "深成指", "深证成指",
        "科创", "科创板", "index", "indices",
        # 含数字指数词（CJK+数字复合词）：数字段与裸数字共形，Step 3 由
        # _DIGIT_KEYWORDS_RE 保护区放行，否则整词永远无法在 Step 4/5 命中
        "中证A500", "中证1000", "中证2000", "中证500", "中证800", "中证100",
        "上证50", "北证50", "深证100", "创业板50", "沪深300", "科创50",
    ],
    TAG_FOLLOWUP: [
        "继续", "接着", "刚才", "上面", "上次", "这只", "该股", "它", "他",
        "然后",
    ],
    TAG_COMPARISON: [
        "哪个好", "哪个", "哪只", "谁更", "二选一",
        "差别", "区别", "优劣", "pk", "vs",
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
        # 泛称词：XX行业名的后缀落款（板块/行业/赛道/概念/题材）+ 龙头。
        # Step 6 DFS 把"建筑板块"分解为相邻 [sector_name]+[sector] 组合，
        # 该相邻组合即高置信度板块信号（由下游消费）；龙头非后缀，指
        # 龙头个股（"白酒龙头"），不参与相邻组合语义
        "板块", "行业", "赛道", "概念", "题材", "龙头",
    ],
    TAG_SECTOR_NAME: [
        # 行业名：裸用即行业意图。含与股票名冲突的词（全量库实证："证券"⊂
        # 中信证券、"农业"⊂农业银行…）——名称库子串命中置信度极低，
        # 行业语义优先，全管道不做个股名匹配
        "新能源", "半导体", "消费", "医药", "白酒",
        "军工", "银行", "地产", "保险", "券商",
        "煤炭", "有色", "钢铁", "汽车", "光伏", "锂电",
        "芯片", "人工智能", "互联网", "金融", "科技", "AI",
        "证券", "农业", "电力", "建筑", "传媒", "教育",
        "航空", "软件", "通信", "旅游",
    ],
    TAG_SECTOR_N_STOCK: [
        # 行业名兼库中股票全名（"机器人"=300024）：精确全名命中，行业/个股
        # 双解皆合理——裸用打歧义 tag 交下游 LLM/确认消歧，不直接打
        # stock_name，也不武断打 sector_name
        "机器人",
    ],
    TAG_FILLER: [
        "和", "下", "是", "再",
        "的", "买", "卖", "选", "了", "吧", "呢",
        "那", "这", "只", "支", "啊", "呀", "咯",
        "哦", "嘛", "么", "就", "请", "第", "个",
    ],
    TAG_CORP_SUFFIX: [
        # 通用公司后缀（零区分度）：精确命中即打 corp_suffix tag 并跳过
        # 股票名扫描——子串匹配在名库必然命中带词头的全名（"公司"⊂中微
        # 公司、"集团"⊂上汽集团），命中是噪声非信号；并作为可覆盖片段
        # 参与 DFS 全覆盖（"腾讯公司"→腾讯+公司）。带区分度词头的
        # "苹果公司"/"中芯国际"不受影响。区别于 filler：语义是公司名
        # 后缀而非填充词，下游可单独识别处理。仅 extend 不入 clean
        # （clean 正则会在 Step 5 从 token 中途撕出后缀）
        "公司", "集团", "控股", "股份", "国际",
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

# 小写归一映射：关键词大小写不敏感分类的回退查询点。词池存储形态混合
# （多数 ASCII 词小写、"AI"/"中证A500" 大写），只做输入 lower 回退会让
# 大写存储词的小写形态（"ai赛道"/"中证a500"）整体失效，故关键词侧也
# 统一归一到小写。当前词池无小写同形词；若将来出现会在本表静默合并，
# 需保持词池互斥。
_KEYWORD_TAG_MAP_LOWER: Dict[str, str] = {
    kw.lower(): tag for kw, tag in _KEYWORD_TAG_MAP.items()
}

# 含数字的枚举关键词（CJK+数字复合词，如 "沪深300"/"中证1000"）：其数字段
# 与裸数字在文本中共形，若 Step 3 按裸数字提取，整词将被拆成"前缀+数字"
# 永远无法在 Step 4/5 命中。_split_by_codes 用本正则把关键词 span 标记为
# 保护区，完全落在保护区内的数字候选 span 放行（部分重叠如 "沪深3000"
# 不适用，维持裸数字行为），整词交 Step 4/5 关键词分词。
_DIGIT_KEYWORDS: Tuple[str, ...] = tuple(sorted(
    (
        kw
        for kws in _TAG_KEYWORD_LISTS.values()
        for kw in kws
        if any(ch.isdigit() for ch in kw) and any("\u3400" <= ch <= "\u9fff" for ch in kw)
    ),
    key=len,
    reverse=True,
))
# 大小写不敏感编译："中证a500" 与 "中证A500" 同受数字段保护（tag 分类侧
# 的大小写归一见 _KEYWORD_TAG_MAP_LOWER）。
_DIGIT_KEYWORDS_RE = (
    re.compile("|".join(re.escape(kw) for kw in _DIGIT_KEYWORDS), re.IGNORECASE)
    if _DIGIT_KEYWORDS
    else None
)

# 全部纯 ASCII 关键词的大写集合：Step 3 代码候选的放行谓词（大小写不敏
# 感）——"PK"/"Buy"/"AI" 等关键词形态不得被美股 ticker 正则抠走，否则
# 关键词语义丢失、误入代码辨认（含原 sector 词池精确匹配放行的 "AI"，
# 取代其职责；"HK"/"US" 非关键词，仍照常作为代码候选）
_ASCII_KEYWORD_UPPER: frozenset = frozenset(
    kw.upper() for kw in _KEYWORD_TAG_MAP if kw.isascii() and kw.isalpha()
)


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
    TAG_FOLLOWUP, TAG_COMPARISON, TAG_SECTOR, TAG_SECTOR_NAME,
    TAG_SECTOR_N_STOCK, TAG_TIME, TAG_FILLER,
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
# 空白（普通/全角空格、制表、换行）同为词界一并切分：ASCII 词与代码间
# 的分隔（"tsla aapl"）此前仅靠 Step 3 大写或标点兜底，小写多词整段漏给
# LLM；空白 token 无内容，由管道末端 _HAS_CONTENT_PATTERN 过滤丢弃
_SPECIAL_PUNCT_RE = re.compile("[" + re.escape(_SPECIAL_PUNCT_CHARS) + r"|\s]")


def _classify_keyword(token_text: str) -> str:
    """查 _KEYWORD_TAG_MAP 取语义标签；未精确命中按小写归一表回退
    （大小写不敏感与 (?i:) 编译声明同构，见 _KEYWORD_TAG_MAP_LOWER 注释）；
    未命中返回空串。"""
    tag = _KEYWORD_TAG_MAP.get(token_text)
    if tag:
        return tag
    return _KEYWORD_TAG_MAP_LOWER.get(token_text.lower(), "")


# =========================================================================
# Token — 分词结构体，text + tag
# =========================================================================


@dataclass(frozen=True)
class Token:
    """分词结构体：文本 + 语义标签 + 可选的已解析股票实体。

    frozen=True 使 Token 可哈希；tag 为空表示未识别；stocks 透传已解析实体
    避免下游重复解析。stocks 构造时传 list 会被 __post_init__ 归一为 tuple
    （frozen 字段值必须可哈希），下游按序列消费不受影响。
    """
    text: str
    tag: str = ""
    stocks: Optional[Tuple["Stock", ...]] = None

    def __post_init__(self) -> None:
        if isinstance(self.stocks, list):
            object.__setattr__(self, "stocks", tuple(self.stocks))
