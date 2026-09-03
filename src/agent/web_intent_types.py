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

== 支持的意图类型（最终方案：五个互斥意图 + 上下文继承机制）==

意图体系按三个正交判别测试划分，裁决顺序固定（个性化 → 深度 → 对象）：

  T1 个性化测试  答案是否依赖"这个用户"的自选/持仓数据？换一个用户来问，
     答案会不同吗？——会 → portfolio_analysis。判据是"答案依赖账户数据"，
     不是句子里有没有"我"："我的茅台基本面怎么样"对所有用户答案相同，
     仍是 stock_analysis。
  T2 深度测试    答案是"一个数据点"还是"一段有观点的论述"？只需报出价格、
     涨跌、成交、估值倍数、涨跌排名 → quote_lookup；需要综合多源信息做
     归因/评价/比较/预测 → 分析类意图。"为什么/怎么看"是分析意图的强
     信号词。quote_lookup 按深度定义、不限对象粒度：个股、指数、板块的
     "报数"都归它。
  T3 对象测试    主对象是个股还是集合？落脚点是谁的状态：≤3 只个股（含
     比较）→ stock_analysis；行业/概念/主题/市场整体结构 → sector_analysis。

五个意图的边界（收 = 判定条件；推 = 排除到哪）：

- ``stock_analysis`` 股票分析——"给一只股票做体检"
    收：单标的多维诊断（基本面/技术面/估值/资金面）、涨跌归因（"为什么
        跌"）、2-3 只比较（"哪个好"）、舆情资讯（作为子维度）、"能不能
        买"的合规化回答；裸个股指称的默认归属（"茅台"）。
    推：对象是用户私有集合 → portfolio_analysis；只要一个数据点 →
        quote_lookup；对象是行业/概念/市场结构 → sector_analysis。
- ``sector_analysis`` 板块分析——"看森林，不看单棵树"（含市场整体结构）
    收：行业/概念热度、资金流向、成分股分布、轮动位置、驱动逻辑、板块
        内优劣评价（"白酒板块哪只最有潜力"）、市场风格判断（"A股什么
        风格"——大盘当作"全市场板块"处理，指数/大盘的观点类问题归此）。
    推：板块的当日涨跌数据、领涨领跌排名 → quote_lookup；板块内单只
        股票的深度问题 → stock_analysis（带板块上下文）。
- ``portfolio_analysis`` 持仓/自选股分析——唯一离不开"我"的意图
    收：组合聚合诊断（整体盈亏/行业集中度/风险暴露）、自选股批量表现、
        组合语境下的个股评估（"我的茅台还该拿着吗"——需成本/仓位，答案
        因人而异；与"茅台能买吗"→ stock_analysis 是一对经典对比）、
        持仓操作词（加仓/减仓/拿着）指向的个股评估。
    推：句中提到个股但答案不依赖账户数据 → stock_analysis（"分析茅台
        的持仓"= 机构/北向持仓，是研究维度）。
- ``quote_lookup`` 行情查询——"只报仪表盘读数"（确定性数据）
    收：实时/当日价格、涨跌幅、成交量、换手、市值、市盈率等估值快照、
        指数点位、板块涨跌、领涨领跌排名（事实排序）、"查一下 XX 股价"
        类取数动作；大盘/指数无深度信号的默认归属（"今天大盘怎么样"）。
    推：一切"贵不贵/强不强/为什么/怎么看"——出现评价或归因即离开本
        意图；执行端必须直接返回工具调用的结构化结果，禁止 LLM 自由
        发挥数字。
- ``general_chat`` 闲聊——兜底但不是垃圾桶
    收：金融知识百科（"什么是市盈率"）、非金融话题、"你能干什么"类系统
        问答、不依赖行情数据源的静态公司信息（"茅台的老板是谁"）。
    推：凡需要查行情/财务/资金数据接口的，一律不归闲聊；分类器低置信
        ≠ 闲聊——低置信走 low_confidence 澄清确认，两者在日志中必须
        可区分。

== 易混淆对照（回归测试基线，见 test_web_intent_resolver 边界矩阵）==
    "茅台多少钱"            → quote_lookup      "茅台估值贵不贵"      → stock_analysis
    "茅台的市盈率是多少"    → quote_lookup      "什么是市盈率"        → general_chat
    "茅台今天为什么大跌"    → stock_analysis    "茅台今天跌了多少"    → quote_lookup
    "茅台基本面怎么样"      → stock_analysis    "我的茅台还该拿着吗"  → portfolio_analysis
    "茅台能买吗"            → stock_analysis    "我的持仓今天怎么样"  → portfolio_analysis
    "白酒板块今天涨了多少"  → quote_lookup      "白酒板块怎么看"      → sector_analysis
    "白酒板块领跌的是谁"    → quote_lookup      "白酒板块哪只最有潜力" → sector_analysis
    "今天大盘怎么样"        → quote_lookup      "大盘怎么看"          → sector_analysis
    "两只股票谁涨得多"      → quote_lookup      "两只股票哪个好"      → stock_analysis
    "分析茅台的股价走势"    → stock_analysis    "查一下茅台的股价"    → quote_lookup

== 追问不占意图名额（上下文继承机制）==
"那五粮液呢""再细一点"本身没有独立语义——它追问的是什么任务，取决于
上文。追问由上下文继承机制处理（查询改写层的轻量实现）：识别为追问
（TAG_FOLLOWUP + 无新股票指称 + 上轮为执行类意图）时直接继承上轮意图
（source="context"），意图枚举保持纯语义。LLM 兜底提示词中的 "followup"
（``LLM_FOLLOWUP_LABEL``）是同一机制的伪标签，合并时同样转为继承，绝不
写入会话上下文。

意图识别只产生一个轻量级标签 + 股票上下文，由 SSE 层据此行动：
先发送 ``intent_resolved``；置信度低或股票名称歧义时发送 ``action_required``
等待用户澄清；解析出的 ``stock_code`` 传递给 #1619 股票范围机制。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.services.name_to_code_resolver import Stock

__all__ = [
    "ALL_WEB_INTENTS",
    "CONFIRMATION_CONFIDENCE_THRESHOLD",
    "LAST_INTENT_KEY",
    "LAST_RESOLUTIONS_KEY",
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
    "TAG_ACTION_QUOTE",
    "TAG_ACTION_QUOTE_FETCH",
    "TAG_FOLLOWUP",
    "TAG_QUESTION",
    "TAG_OPINION",
    "TAG_COMPARISON",
    "TAG_SECTOR",
    "TAG_SECTOR_NAME",
    "TAG_SECTOR_N_STOCK",
    "TAG_TIME",
    "TAG_FILLER",
    "TAG_CORP_SUFFIX",
    "LLM_FOLLOWUP_LABEL",
]


# =========================================================================
# 意图常量定义
# =========================================================================

class WebIntent(str, Enum):
    """意图标签枚举（str 子类，成员可直接与字符串比较）。

    边界总纲（三判别测试 + 逐意图收/推 + 易混淆对照表）见模块 docstring；
    各成员注释只保留一句话本质与最强边界信号。追问不是意图成员——由
    上下文继承机制处理（见模块 docstring"追问不占意图名额"节）。
    """

    STOCK_ANALYSIS = "stock_analysis"           # 股票分析：单标的体检（≤3 只含比较）；裸个股指称的默认归属
    SECTOR_ANALYSIS = "sector_analysis"         # 板块分析：行业/概念/市场结构；指数/大盘的观点类问题也归此
    PORTFOLIO_ANALYSIS = "portfolio_analysis"   # 持仓/自选股分析：唯一依赖用户账户数据（T1 定义性特征）
    QUOTE_LOOKUP = "quote_lookup"               # 行情查询：报数据点，不限对象粒度；大盘/指数裸词的默认归属
    GENERAL_CHAT = "general_chat"               # 闲聊/兜底：不查数据接口的对话；低置信 ≠ 闲聊


# 所有合法意图（字符串形式），校验 LLM/session 返回
ALL_WEB_INTENTS = frozenset(w.value for w in WebIntent)

# LLM 兜底的追问伪标签：非意图枚举成员，_merge_llm_result 合并时转为
# "继承上轮意图"（上轮为执行类）或降级 general_chat，绝不写入会话上下文
LLM_FOLLOWUP_LABEL = "followup"


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


TAG_STOCK_NAME = "stock_name"          # 股票实体（全名或一对一缩写），Step 1 仅全名精确匹配、Step 6 多策略匹配提取
TAG_CODE_NAME = "code_name"            # 空 tag 经 name_code_list 解析为股票名称后打此标签

# --- 意图主题 ---
TAG_SUBJECT_RESEARCH = "subject_research"       # 研究主题（走势/趋势/技术面/基本面/筹码）
TAG_SUBJECT_PORTFOLIO = "subject_portfolio"     # 持仓主题（持仓/仓位/自选股/盈亏）
TAG_SUBJECT_MARKET = "subject_market"           # 市场标识（A股/港股/美股/沪市…）
TAG_SUBJECT_MARKET_BROAD = "subject_market_broad"  # 泛市场概念（大盘/行情/指数/两市）
TAG_SUBJECT_INDEX = "subject_index"             # 具体指数（上证/恒生/纳斯达克/沪深300…）

# --- 动作 ---
TAG_REQUEST = "request"                       # 泛分析动作（分析/看看/研究/诊断/评估）：深度上弱于数据词（T2）
TAG_ACTION_RESEARCH = "action_research"       # 研究决策（能买/可以买/止损/目标价/buy/sell）：强分析信号
TAG_ACTION_PORTFOLIO = "action_portfolio"     # 持仓操作（加仓/减仓/调仓/满仓/空仓/拿着/拿住）：组合语境信号（T1）
TAG_ACTION_QUOTE = "action_quote"             # 数据点查询（宾语侧：多少钱/股价/成交量/市盈率/收盘/领涨/新闻…）：T2 报数信号
TAG_ACTION_QUOTE_FETCH = "action_quote_fetch"  # 取数动作词（动词侧：查/查下/看/看下）——与数据对象词分立为两个 tag，下游只读 tag 即可区分"取数动词"与"数据对象"，不私设词表（多少钱/股价/涨了多少/成交量/市盈率/收盘/领涨…）：T2 报数信号

# --- 辅助 ---
TAG_FOLLOWUP = "followup"     # 追问延续（继续/刚才/这只/它/上面/上次/该股）
TAG_QUESTION = "question"     # 中性疑问（怎么样/怎么/是否/吗/？）：不构成深度信号；观点/归因问句见 TAG_OPINION
TAG_OPINION = "opinion"       # 观点/归因问句（怎么看/为什么/还会/如何/风格…）：深度测试的强分析信号
TAG_COMPARISON = "comparison"  # 对比（对比/比较/哪个好/vs/pk/二选一）：比较观点是强分析信号
TAG_SECTOR = "sector"          # 板块泛称词（板块/行业/赛道/概念/题材/龙头）+ XX+后缀 复合形态
TAG_SECTOR_NAME = "sector_name"        # 行业名（金融/建筑/证券/农业…），裸用即行业意图
TAG_SECTOR_N_STOCK = "sector_n_stock"  # 行业名兼股票全名（机器人=300024），裸用歧义交下游 LLM 消歧
TAG_TIME = "time"             # 时间指示（今天/现在/本周/最近/实时…）
TAG_FILLER = "filler"         # 高频功能词（代词/情态/否定/介词/语气：的/我/会/不/在…），零意图语义
TAG_CORP_SUFFIX = "corp_suffix"  # 通用公司后缀（公司/集团/控股/股份/国际）：零区分度，精确命中即跳过股票名匹配

# 所有合法 tag 的不可变集合
_ALL_TAGS = frozenset({
    TAG_UNKNOWN_CODE, TAG_UNKNOWN_NUMBER, TAG_STOCK_CODE,
    *(wrong_code_tag(m) for m in _CODE_TAG_MARKETS),
    *(unknown_code_tag(m) for m in _CODE_TAG_MARKETS),
    TAG_STOCK_NAME, TAG_CODE_NAME,
    TAG_SUBJECT_RESEARCH, TAG_SUBJECT_PORTFOLIO, TAG_SUBJECT_MARKET,
    TAG_SUBJECT_MARKET_BROAD, TAG_SUBJECT_INDEX,
    TAG_REQUEST, TAG_ACTION_RESEARCH, TAG_ACTION_PORTFOLIO, TAG_ACTION_QUOTE,
    TAG_ACTION_QUOTE_FETCH, TAG_FOLLOWUP, TAG_QUESTION, TAG_OPINION,
    TAG_COMPARISON, TAG_SECTOR,
    TAG_SECTOR_NAME, TAG_SECTOR_N_STOCK, TAG_TIME, TAG_FILLER, TAG_CORP_SUFFIX,
})


class Market(str, Enum):
    """市场标识枚举（str 子类，成员可直接与字符串比较）。"""

    A = "a"    # A 股
    HK = "hk"  # 港股
    US = "us"  # 美股


# 执行类意图：会触发 Agent 工作流，低置信度/股票歧义时必须先经用户确认。
# 闲聊不触发工作流；追问走上下文继承（继承产物本身必为执行类，标的歧义
# 已在上轮确认过，无独立确认需求）
_EXECUTING_INTENTS = frozenset({
    WebIntent.STOCK_ANALYSIS,
    WebIntent.SECTOR_ANALYSIS,
    WebIntent.PORTFOLIO_ANALYSIS,
    WebIntent.QUOTE_LOOKUP,
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
# 上一轮任务列表的会话投影：intent/stocks/sectors/confidence/source/
# source_request/unverified_codes 的序列化形态——供下一轮 resolve 的
# 追问主体种子（跨轮"继续"指向 last_intent 的任务）/确认消费/回看调试
# 读取（每轮写，含短路轮：确认消费的数据源；种子侧短路轮自动排除）
LAST_RESOLUTIONS_KEY = "last_resolutions"


# =========================================================================
# Tag → 关键词列表 — 所有中文关键词的唯一定义处
# =========================================================================
# 后续正则全部从这里编译，不手写中文关键词；TAG_SUBJECT_MARKET 由 _MARKET_KEYWORD_MAP 派生。
# 排除项：多 token 跨词模式（和.*比…）由 extra 参数承接；"值得"与股票名
# "值得买"冲突，不入池

_MARKET_KEYWORD_MAP: Dict[Market, tuple] = {
    Market.A: ("a股", "大a", "沪市", "深市", "沪深"),
    Market.HK: ("港股", "h股", "香港"),
    Market.US: ("美股", "美国"),
}

# 关键词分两池，划分标准是 Step 5 盲匹配（finditer 子串命中即采信）下的
# 子串歧义风险，贯彻"宁可不做，不可做错"：
#   clean — 词形无子串歧义：不被更长常见词包含（"怎么样"不会被更长词从
#           中途撕出），Step 5 直接命中即采信；
#   extend — 存在子串歧义（"现在"⊂"出现在"、"后市"⊂"午后市场"、
#           "查一下"⊂"查一下午"、"买点"="买"+量词）或可能与股票名混淆：
#           仅在 Step 6 DFS 全片段覆盖（交叉验证）时命中，覆盖不了则整段
#           放弃交下游 LLM，绝不盲撕。
# 两条硬约束：
#   - 超过 4 字符的 ASCII 关键词（research/portfolio/market…）只能留在
#     clean：Step 6 字母段整体消费 + 汉字窗口长度上限 4，使其在 extend
#     永远无法命中；
#   - 市场族 tag（subject_market / market_broad / index）在 Step 4 经合并
#     词池匹配（见 _MARKET_TOKEN_PATTERN），clean/extend 之分对其不生效。
# 另：ASCII 关键词一律全词匹配（_compile_kw_fragment 加词边界断言），
# 连续英文字母段（researching/markets）不被中途切出。
# _TAG_KEYWORD_LISTS 由两者合并，下游逻辑不变

_TAG_KEYWORD_LISTS_CLEAN: Dict[str, List[str]] = {
    TAG_REQUEST: [
        # 泛分析动作，深度上弱于数据词："看看茅台股价"按 action_quote 归
        # 行情查询；取数动作词（查一下/查下）属 TAG_ACTION_QUOTE。
        # analyze/analyse/research 超 4 字符，Step 6 无法承接，只能留 clean
        "分析", "看看", "研究", "诊断", "评估",
        "analyze", "analyse", "research",
    ],
    TAG_SUBJECT_RESEARCH: [
        # 估值是研究维度（"茅台估值贵不贵"是评价类问题），与基本面/技术面同级
        "走势", "走向", "趋势", "技术面", "基本面", "估值", "筹码",
    ],
    TAG_QUESTION: [
        # 中性疑问不构成深度信号："今天大盘怎么样"仍归行情查询；
        # 观点/归因问句（怎么看/为什么…）属 TAG_OPINION
        "怎么样", "怎么", "是否", "吗", "？", "?",
    ],
    TAG_OPINION: [
        # 观点/归因/预测问句 + 市场结构判断词（风格/轮动——观点语义非数据）。
        # 深度测试 T2 的强分析信号："为什么跌"是归因分析，"跌了多少"才是报数
        "怎么看", "为何", "为什么", "还会", "还能", "还该", "要不要",
        "能否", "能不能", "如何", "涨还是跌", "风格", "轮动",
    ],
    TAG_SUBJECT_PORTFOLIO: [
        "持仓", "仓位", "我的股票", "自选股", "盈亏", "成本价",
        "portfolio", "position",
    ],
    TAG_ACTION_PORTFOLIO: [
        # 拿着/拿住是口语化持有表述，强组合语境信号（"还该拿着吗"的答案
        # 依赖成本与仓位）；"持有"不入池——"持有茅台的基金有哪些"是研究
        # 语境而非组合语境
        "加仓", "减仓", "调仓", "满仓", "空仓", "拿着", "拿住",
    ],
    TAG_ACTION_QUOTE: [
        # 数据点查询（T2 报数侧）：价格/涨跌幅度/成交/估值快照/事实排名。
        # 与强分析词（subject_research/action_research/opinion/comparison）
        # 共现时让位——"分析茅台的股价走势"按"走势"归股票分析；与泛动作
        # 词（request）共现时获胜——"查一下茅台股价"归行情查询
        "多少钱", "多少点", "什么价", "报价",
        "涨跌幅", "涨了多少", "跌了多少", "涨了", "跌了", "涨得", "跌得",
        "成交量", "成交额", "换手", "市值", "市盈率", "市净率",
        "收盘价", "开盘价", "收盘", "开盘", "点位", "最高价", "最低价",
        "领涨", "领跌", "价格",
    ],
    TAG_SUBJECT_MARKET_BROAD: [
        "大盘", "行情", "两市", "北向", "股市", "market", "sector", "指数",
    ],
    TAG_SECTOR_NAME: [
        # 高频英文缩写概念（A 股语境）。放 clean（Step 5 盲匹配独立存活）
        # 而非与中文行业名同列 extend：ASCII 词边界断言强制全词匹配
        # （"CPOX"不命中）、无中文名库子串冲突（"证券"⊂中信证券那类），
        # 无需 DFS 全覆盖保护；且经 _ASCII_KEYWORD_UPPER 放行后 Step 3
        # 不当美股 ticker 抠走——缩写的板块语义优先于同形 ticker。
        # 数字混合词（5G/6G）会被 Step 3 数字段撕开，不收
        "CPO", "AIGC", "GPT", "GPU", "HBM", "PCB",
        "LED", "OLED", "MCU", "SOC", "AR", "VR", "MR",
        "SaaS", "IoT",
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
        "继续", "接着", "刚才", "上面", "上次", "这只", "该股",
    ],
    TAG_COMPARISON: [
        "哪个好", "哪个", "哪只", "谁更", "二选一",
        "差别", "区别", "优劣", "pk", "vs",
    ],
    TAG_TIME: [
        "今天", "本周", "交易日", "实时", "最近",
        # 目前/当前：无更长常见词包含，Step 5 直接命中安全
        "目前", "当前",
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
    TAG_TIME: [
        # 现在 ⊂ "出现在"：Step 5 盲匹配会从"出现在龙虎榜"中途撕出时间
        # 词；DFS 全覆盖下"茅台现在"（茅台+现在）正常命中，超串场景整段
        # 放弃交 LLM
        "现在", "未来",
    ],
    TAG_SUBJECT_RESEARCH: [
        # 后市 ⊂ "午后市场/最后市值"；涨势 ⊂ "上涨势头"；trend ⊂
        # "trending"。独立 gap（"后市怎么看"）或整段覆盖（"茅台后市"）
        # 时正常命中
        "后市", "涨势", "trend",
    ],
    TAG_ACTION_RESEARCH: [
        # 能买 ⊂ "才能买到"；买点/卖点存在"买+量词点"歧义（"买点茅台"
        # 是"买一点茅台"）；buy/sell ⊂ "buyer/selling"。≤4 字符 ASCII
        # 在 extend 可命中（standalone gap）。抄底/逃顶/止盈/止损是交易
        # 决策词（强分析信号）：不入池会让"现在能抄底吗"整段 DFS 放弃，
        # 板块名/时间词一并丢失
        "能买", "买点", "卖点", "buy", "sell",
        "抄底", "逃顶", "止盈", "止损",
    ],
    TAG_ACTION_QUOTE: [
        # 现价 ⊂ "兑现价值/发现价格"；股价 ⊂ "个股价值"。数据对象词
        # （取数句的宾语侧）
        "现价", "股价", "新闻",
    ],
    TAG_ACTION_QUOTE_FETCH: [
        # 取数动作词（动词侧）：查一下 ⊂ "查一下午"、查下 ⊂ "查下午盘"、
        # 看 ⊂ 更长词。真实取数句（"查一下茅台股价"）整段覆盖
        # （查一下+茅台+的+股价）正常命中
        "查", "查下", "看", "看下",
    ],
    TAG_FOLLOWUP: [
        # 它/他 ⊂ "它们/他们"：单字代词 Step 5 盲命中会把"他们说"错判
        # 追问指代；独立 gap（"它怎么样"）正常命中
        "它", "他",
        # 然后 ⊂ "居然后市/仍然后悔"（X然复合词 + 后/悔）：Step 5 盲命中
        # 会从词界中途撕出追问 tag 并毁掉紧随关键词（"后市"）。入 extend
        # 后仅 DFS 全覆盖时命中，代价见回归：句首"然后再展开讲讲"类
        # 后缀不可覆盖的追问句 followup tag 丢失，继承改由 LLM 兜底
        "然后",
    ],
    TAG_COMPARISON: [
        "对比", "比较", "多选", "选哪",
    ],
    TAG_SECTOR: [
        # 泛称词：XX行业名的后缀落款（板块/行业/赛道/概念/题材）+ 龙头。
        # Step 6 DFS 把"建筑板块"分解为相邻 [sector_name]+[sector] 组合，
        # 该相邻组合即高置信度板块信号（由下游消费）；龙头非后缀，指
        # 龙头个股（"白酒龙头"），不参与相邻组合语义。
        # ETF/LOF/REITs 是产品类泛称后缀——"银行ETF"与"银行板块"结构
        # 同构（银行主题的产品集合），同样构成相邻组合；ASCII 词经
        # _ASCII_KEYWORD_UPPER 放行后 Step 3 不当美股 ticker 抠走
        "板块", "行业", "赛道", "概念", "题材", "龙头",
        "ETF", "LOF", "REITs",
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
        # ===== 高频功能词（extend / DFS 全覆盖专用）=====
        # Step 6 DFS 要求片段全匹配才产出：gap 里出现任一词池外口语词，
        # 整段放弃打 tag，同 gap 内的股票实体/关键词一并丢失。以下收录
        # 口语中最高频、且对意图判定零语义的功能词作全覆盖 filler，保住
        # "茅台现在怎么样""你觉得呢""要不要跟一下"一类句子的实体提取。
        # 入池约束：零意图语义（有语义的词入对应 tag 词池）；与更长的
        # 关键词共形时长度优先级自动让位（"还能"≠还+能、"为什么"≠什么）。
        "和", "下", "是", "再",
        "的", "买", "卖", "选", "了", "吧", "呢",
        "那", "这", "只", "支", "啊", "呀", "咯",
        "哦", "嘛", "么", "就", "请", "第", "个",
        # 情况：泛指名词（"XX的情况/什么情况"），零意图语义
        "情况",
        # 人称/疑问代词（"我的茅台"= 我+的+茅台 三片段全覆盖，实体才能
        # 从领属短语中被提取；"帮我""我要"两字词在 clean 池优先整词命中）
        "我", "你", "我们", "什么", "谁",
        # 情态/认知动词（"你觉得""应该会涨"，对意图无增量信号）
        "觉得", "感觉", "能", "会", "可以", "应该", "可能",
        # 否定/程度/关联（"不太妙""又跌了""还是加仓"）
        "不", "没", "有", "很", "挺", "太", "还", "又", "也", "都", "还是", "或者",
        # 介词/时地（"跟茅台比""加到自选""在底部吗"）
        "跟", "给", "让", "在",
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

_TAG_KEYWORD_LISTS: Dict[str, List[str]] = {
    tag: _TAG_KEYWORD_LISTS_CLEAN.get(tag, []) + _TAG_KEYWORD_LISTS_EXTEND.get(tag, [])
    for tag in {*_TAG_KEYWORD_LISTS_CLEAN, *_TAG_KEYWORD_LISTS_EXTEND}}

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
# 关键词语义丢失、误入代码辨认（"HK"/"US" 非关键词，仍照常作为代码候选）
_ASCII_KEYWORD_UPPER: frozenset = frozenset(
    kw.upper() for kw in _KEYWORD_TAG_MAP if kw.isascii() and kw.isalpha()
)


# =========================================================================
# 正则编译工具 — 全部从 _TAG_KEYWORD_LISTS 编译
# =========================================================================

def _compile_kw_fragment(kw: str) -> str:
    """单个关键词 → regex 片段：ASCII 词包裹 (?i:) 并加词边界断言，CJK 直接 escape。

    ASCII 关键词一律全词匹配：前后不得紧邻字母/数字（"researching" 内的
    "research"、"markets" 内的 "market" 不被中途切出）。词边界由空格/标点
    （Step 2 已切分）或 CJK 邻接界定，与 Step 6 的整词精确查表语义一致。
    CJK 关键词保持子串匹配——中文无空格分词，"帮我分析一下"依赖中途命中。
    """
    if re.search(r"[A-Za-z]", kw):
        escaped = re.escape(kw)
        return f"(?i:(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9]))"
    return re.escape(kw)


def _compile_words(kws: Iterable[str], extra: str = "") -> re.Pattern:
    """关键词集合 → 单个正则：长词优先（"沪深300" 不被 "沪深" 截断），
    extra 可追加原生 regex 片段（如 vs 词边界、多 token 跨词模式）。"""
    fragments = {_compile_kw_fragment(k) for k in kws}
    if extra:
        fragments.add(extra)
    return re.compile("|".join(sorted(fragments, key=len, reverse=True)))


def _compile_kw_pattern(*tags: str, extra: str = "") -> re.Pattern:
    """从指定 tag 列表提取所有关键词编译为单个正则；市场类 tag
    （TAG_SUBJECT_MARKET）用市场词池，extra 语义同 ``_compile_words``。"""
    kws: List[str] = [
        kw for tag in tags
        for kw in (_MARKET_KW_TAG_MAP.keys() if tag == TAG_SUBJECT_MARKET
                   else _TAG_KEYWORD_LISTS.get(tag, []))
    ]
    return _compile_words(kws, extra)


# Step 5 关键词分词正则（排除市场类 tag，Step 4 独立处理，避免 "大港股份" 消歧失效）
_NON_MARKET_TAGS = frozenset({
    TAG_REQUEST, TAG_SUBJECT_RESEARCH, TAG_ACTION_RESEARCH, TAG_QUESTION,
    TAG_OPINION, TAG_SUBJECT_PORTFOLIO, TAG_ACTION_PORTFOLIO, TAG_ACTION_QUOTE,
    TAG_ACTION_QUOTE_FETCH,
    TAG_FOLLOWUP, TAG_COMPARISON, TAG_SECTOR, TAG_SECTOR_NAME,
    TAG_SECTOR_N_STOCK, TAG_TIME, TAG_FILLER,
})


def _compile_clean_kw_pattern(*tags: str) -> re.Pattern:
    """仅用 _TAG_KEYWORD_LISTS_CLEAN 编译正则，排除可能混淆股票名的扩展关键词。"""
    return _compile_words(
        kw for tag in tags for kw in _TAG_KEYWORD_LISTS_CLEAN.get(tag, []))


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
# 空白（普通/全角空格、制表、换行）同为词界一并切分：覆盖 ASCII 词与
# 代码间的分隔（"tsla aapl"，小写多词同样切分）；空白 token 无内容，
# 由管道末端 _HAS_CONTENT_PATTERN 过滤丢弃
_SPECIAL_PUNCT_RE = re.compile("[" + re.escape(_SPECIAL_PUNCT_CHARS) + r"|\s]")


# =========================================================================
# 意图层文本模式与词表 — resolver 消费的唯一定义处（本模块是数据字典，
# 中文关键词/正则/归一映射不散落在流程代码里）
# =========================================================================

# T1 第一人称领属（个股路径开关）："我的茅台"是组合语境，"帮我看看茅台"
# 的"我"是请求客套不算——限定"我"后紧邻领属/交易动词
POSSESSIVE_RE = re.compile(r"我(?:的|持|买|卖|加|减|要|想|该|算)")

# 确认轮拒绝词：取消全部待确认组
DECLINE_PATTERN = re.compile(
    r"^(?:不用了?|不需要|算了|算了吧|取消|不分析了?|错了|不是的?|换一个|无需)$"
)

# 消息消费型标点：Step 2 保证其必落在 token 边界（，；。！？不出现于
# 股票名/代码内），切分不撕裂任何 token
SUB_MESSAGE_PUNCT_RE = re.compile(r"[，。！？；,!?;]")

# 顺序连接词：之前下刀。并列连接词（和/与/跟/及）不切——并列对象属于
# 同一个任务（"茅台和五粮液"是一个任务的两个标的）
SEQUENCE_CONNECTIVES = ("然后", "其次", "接着", "顺便")
SEQUENCE_CONNECTIVE_RE = re.compile(
    "|".join(re.escape(c) for c in SEQUENCE_CONNECTIVES)
)

# 并列残留防线的连接词：空段以连接词开头且紧邻前 token 是标的类
# （"茅台|和西藏建工"）→ 剥离连接词后的文本是并列名称候选
COORDINATION_PREFIXES = ("还有", "以及", "和", "与", "跟", "及")

# 量词单位后缀：裸数字后紧邻这些字时是数量/价格语义（"我有300750元"），
# 不是股票代码——数字提升的唯一排除条件
NUMERIC_UNIT_SUFFIXES = frozenset({
    "元", "万", "块", "股", "手", "份", "倍", "点", "年", "月", "日", "号", "折",
})

# A 股裸数字代码的首码白名单（0/3/6/4/8 开头或 92 段北交所）
A_CODE_FIRST_DIGITS = frozenset("03648")

# 板块泛称后缀（TAG_SECTOR 词池同源，不含指龙头个股的"龙头"）：
# "AI板块"与"AI"是同一板块的两种表述，LLM 板块名合入时按去后缀键去重
SECTOR_GENERIC_SUFFIXES = ("板块", "行业", "赛道", "概念", "题材")

# market 字段规范化：LLM 各种变体（大小写/中英文/连字符）→ Market 枚举
MARKET_NORMALIZE: Dict[str, Optional["Market"]] = {
    "a": Market.A, "a_share": Market.A, "a股": Market.A,
    "ashare": Market.A, "a-share": Market.A, "ashares": Market.A,
    "shanghai": Market.A, "shenzhen": Market.A,
    "hk": Market.HK, "港股": Market.HK,
    "hongkong": Market.HK, "hong_kong": Market.HK,
    "h-share": Market.HK, "hshare": Market.HK,
    "us": Market.US, "美股": Market.US,
    "american": Market.US, "america": Market.US, "usa": Market.US,
}

# LLM 意图标签的尾部标点修剪集（"Stock-Analysis。" → "stock_analysis"）
# 泛市场兜底槽名：市场代码 → 中文槽名；无限定泛市场（"大盘"）
MARKET_SLOT_NAMES = {"a": "A股", "hk": "港股", "us": "美股"}
BROAD_MARKET_SLOT_NAME = "大盘"

INTENT_LABEL_TRIM_CHARS = ".,;:!?。，；：！？"

# LLM 回复的 markdown code fence 清理
LLM_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*")


def normalize_intent_label(value: Any) -> Optional[str]:
    """规范化 LLM 返回的意图标签：空白/大小写/连字符空格统一、去尾部
    标点，非法类型返回 None。"""
    if not isinstance(value, str):
        return None
    label = value.strip().lower().replace(" ", "_").replace("-", "_")
    label = label.strip(INTENT_LABEL_TRIM_CHARS)
    return label or None


def sector_dedup_key(name: str) -> str:
    """板块名去重键：剥离尾部泛称后缀并小写（"AI板块"与"AI"同键）。"""
    key = name.strip().lower()
    for suffix in SECTOR_GENERIC_SUFFIXES:
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[: -len(suffix)]
    return key


LLM_SYSTEM_PROMPT = """你是股票分析助手的意图分类器。把用户当前消息分类为以下意图之一：
- stock_analysis: 股票分析——指向具体股票的深度分析（"分析茅台""茅台为
  什么跌""茅台和五粮液哪个好"）
- sector_analysis: 板块分析——行业/概念/板块或市场整体的结构与观点
  （"白酒板块怎么看""现在什么风格"）
- portfolio_analysis: 持仓/自选数据查询——唯一需要调用用户账户数据的
  个性化任务（取账户标的集合）；对持仓的中性聚合问句（"我的持仓今天
  怎么样"）与持仓操作决策（"我的茅台还该拿着吗"）以它为终态；
  显式动作词作用于持仓泛指集合时它是管道首段（见约束）
- quote_lookup: 行情查询——只要数据点不要观点和分析（"茅台多少钱""今天大盘
  怎么样""白酒板块领跌的是谁"）
- general_chat: 闲聊、金融知识问答或与股票分析无关的请求（"什么是市盈率"）
- followup: 对上一轮分析的追问/延续（"继续""再详细说说""那五粮液呢"），
  未提及新标的

判定规则（按顺序裁决）：
- 答案依赖该用户的持仓/自选数据吗？是 → portfolio_analysis。句中有"我"
  但答案对所有用户相同（"我的茅台基本面怎么样"）→ 不是；
- 只需报出价格/涨跌/成交/估值数字或涨跌排名 → quote_lookup；需要归因、
  评价、比较、预测 → 分析类意图（"为什么"是分析信号）；
- 主对象是具体股票 → stock_analysis；是板块/行业/市场整体 →
  sector_analysis（板块内具体某只股票的深度问题仍归 stock_analysis）。

只输出一个 JSON 对象，不要输出其它文字，字段如下：
{"intents": [
  {"intent": "上述之一", "confidence": 0到1的小数, "market": "a|hk|us|null",
   "stock_code": "主股票代码或null", "stock_codes": ["提及的全部股票代码，可选"],
   "sectors": ["提及的板块/行业名，原文用词，可选"],
   "unresolved_names": ["提及但无法对应任何真实证券的名称，原文用词，可选"]}
 ],
 "note": "不超过20字的理由"}

其它约束：
- intents 按用户表达顺序保序，逐元素独立判定；一条消息含多个意图时必须
  拆成多个元素——并列的不同对象（"看医药板块，分析茅台"）、顺序动作
  （"查完A再分析B"）、同一标的的不同深度（"看股价和基本面"＝报数＋
  分析两个意图）都要拆；单一意图也输出单元素数组；
- 管道拆分原理（个人持仓/自选集合 × 显式动作/数据/深度词）：主体为
  显式标的（"持仓的茅台的股价"——执行不需账户数据）＝单一动作意图；
  主体为组合泛指（"我持仓的股票的股价""分析我所有的持仓股票""自选股
  今天涨了多少"）＝拆分为两个意图——持仓分析（取账户标的集合）在前、
  对应动作意图（行情查询/股票分析等普遍化流程，主体＝前一意图的集合，
  无需填代码）在后，保序；对持仓本身的中性问句（无显式动作词）＝
  单一持仓分析；
- "followup" 是追问伪标签（不是意图成员）：延续上一轮或数组前一个
  元素的意图，整条回复就是追问时作为唯一元素使用，与其它意图混在
  同一数组时直接写要延续的具体意图；
- message 可能是多任务消息中的一个片段：current_stock 是当前讨论标的
  （同消息前序片段已确定，或会话锁定的当前股票）；片段自身无标的而
  语义指向它（如"和市盈率"）时，按片段语义判定 intent 并在 stock_code
  返回 current_stock 的代码；
- 各意图的候选股票若有用户所指，在该元素 stock_code 返回其代码；多股
  比较/多标的在该元素 stock_codes 返回全部代码；
- 板块/行业意图在 sectors 返回原文中的板块名（不要自行改写措辞）；
- 提及的标的名若确定不是真实证券（如生造名"你好股份"），原文放入
  unresolved_names——不要为它编造代码，也不要静默忽略；
- 不要编造代码：没有把握时 stock_code 返回 null 并降低该意图置信度。

示例（输入＝user 消息的 JSON 载荷，输出＝要求的全量 JSON；代码一律规范
拼写：A股 6 位裸数字、港股 HK+5 位、美股大写 ticker）：

输入: {"message": "茅台多少钱", "current_stock": null}
输出: {"intents": [{"intent": "quote_lookup", "confidence": 0.95, "market": null, "stock_code": "600519", "stock_codes": [], "sectors": [], "unresolved_names": []}], "note": "询价"}

输入: {"message": "茅台和五粮液哪个好", "current_stock": null}
输出: {"intents": [{"intent": "stock_analysis", "confidence": 0.9, "market": null, "stock_code": null, "stock_codes": ["600519", "000858"], "sectors": [], "unresolved_names": []}], "note": "比较是一个意图，多标的入stock_codes，不拆分"}

输入: {"message": "白酒板块怎么看", "current_stock": null}
输出: {"intents": [{"intent": "sector_analysis", "confidence": 0.9, "market": null, "stock_code": null, "stock_codes": [], "sectors": ["白酒"], "unresolved_names": []}], "note": "板块观点"}

输入: {"message": "我的持仓今天怎么样", "current_stock": null}
输出: {"intents": [{"intent": "portfolio_analysis", "confidence": 0.9, "market": null, "stock_code": null, "stock_codes": [], "sectors": [], "unresolved_names": []}], "note": "依赖账户数据"}

输入: {"message": "帮我看下我持仓的股票的股价", "current_stock": null}
输出: {"intents": [{"intent": "portfolio_analysis", "confidence": 0.9, "market": null, "stock_code": null, "stock_codes": [], "sectors": [], "unresolved_names": []}, {"intent": "quote_lookup", "confidence": 0.9, "market": null, "stock_code": null, "stock_codes": [], "sectors": [], "unresolved_names": []}], "note": "泛指主体拆取持仓＋报价"}

输入: {"message": "帮我分析我所有的持仓股票", "current_stock": null}
输出: {"intents": [{"intent": "portfolio_analysis", "confidence": 0.9, "market": null, "stock_code": null, "stock_codes": [], "sectors": [], "unresolved_names": []}, {"intent": "stock_analysis", "confidence": 0.9, "market": null, "stock_code": null, "stock_codes": [], "sectors": [], "unresolved_names": []}], "note": "泛指主体拆取持仓＋分析"}

输入: {"message": "什么是市盈率", "current_stock": null}
输出: {"intents": [{"intent": "general_chat", "confidence": 0.9, "market": null, "stock_code": null, "stock_codes": [], "sectors": [], "unresolved_names": []}], "note": "知识问答"}

输入: {"message": "再展开讲讲", "current_stock": {"code": "600519", "name": "贵州茅台", "market": "a"}}
输出: {"intents": [{"intent": "followup", "confidence": 0.9, "market": null, "stock_code": null, "stock_codes": [], "sectors": [], "unresolved_names": []}], "note": "追问延续上轮"}

输入: {"message": "和市盈率", "current_stock": {"code": "HK00700", "name": "腾讯控股", "market": "hk"}}
输出: {"intents": [{"intent": "quote_lookup", "confidence": 0.85, "market": "hk", "stock_code": "HK00700", "stock_codes": [], "sectors": [], "unresolved_names": []}], "note": "片段无标的，指称current_stock"}

输入: {"message": "看一下茅台股价和基本面", "current_stock": null}
输出: {"intents": [{"intent": "quote_lookup", "confidence": 0.9, "market": null, "stock_code": "600519", "stock_codes": [], "sectors": [], "unresolved_names": []}, {"intent": "stock_analysis", "confidence": 0.9, "market": null, "stock_code": "600519", "stock_codes": [], "sectors": [], "unresolved_names": []}], "note": "同标的不同深度拆两个意图"}

输入: {"message": "查完五粮液再看下医药板块", "current_stock": null}
输出: {"intents": [{"intent": "quote_lookup", "confidence": 0.9, "market": null, "stock_code": "000858", "stock_codes": [], "sectors": [], "unresolved_names": []}, {"intent": "quote_lookup", "confidence": 0.9, "market": null, "stock_code": null, "stock_codes": [], "sectors": ["医药"], "unresolved_names": []}], "note": "顺序动作按表达顺序拆分"}"""


# 意图层文本模式与词表（resolver 消费）的补充正则 ==========================

# 意图词并集（clean 池）：文本级"有无意图信号"判据。用 clean 池而非
# 全池——extend 词（"看下"）在 unknown_token 陪葬场景仍可能出现在文本里，clean
# 命中才构成可靠意图证据（"分析ZZZZ"有信号不触发 LLM、"顺便看下SOFI"
# 的"看下"不在 clean 池→无信号触发兜底）
INTENT_WORD_RE = _compile_clean_kw_pattern(
    "request", "subject_research", "action_research", "question",
    "opinion", "subject_portfolio", "action_portfolio", "action_quote",
    "followup", "comparison",
)


# 裸数字段（确认轮短码解读："09988" → HK09988）
BARE_DIGIT_RE = re.compile(r"(?<!\d)(\d{4,6})(?!\d)")


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


# =========================================================================
# WebIntentResolution — 单次意图识别的完整结果
# =========================================================================


def _coerce_stock(entry: Any) -> Optional["Stock"]:
    """构造载荷条目（Stock / str 代码 / dict）→ Stock。

    空串与缺 code 的 dict 返回 None（形状异常剔除——与 resolver
    ``_stock_from_payload`` 的缺键守卫同口径）；其余类型原样透传：
    构造器面对的是进程内对象，不做形态审判，鸭子对象交由消费侧按
    ``.code`` 契约使用。
    """
    if isinstance(entry, str):
        return Stock(code=entry) if entry else None
    if isinstance(entry, dict):
        return (Stock(code=entry["code"], name=entry.get("name", ""),
                      market=entry.get("market", ""))
                if entry.get("code") else None)
    return entry


@dataclass
class WebIntentResolution:
    """一次 Web Chat 意图识别流程的完整产出。

    各字段的含义：
    - ``intent``: 最终的意图标签（来自 ALL_WEB_INTENTS 之一）
    - ``confidence``: 置信度 [0.0, 1.0]，影响是否需要用户确认。注意：是
      按决策路径赋的常量（显式代码 0.9、关键词独高 0.85、LLM 上限 0.75…），
      表达"路径可靠程度"而非校准概率。
    - ``source``: 意图来源标识
        - ``"rule"`` — 正则/规则直接判定（高置信直达，未调 LLM）
        - ``"llm"`` — LLM 分类结果
        - ``"llm_failed"`` — LLM 兜底已触发但调用失败（超时/异常/坏
          输出），结果退回规则判定；置信度与 stocks 与 rule 同源，
          排障时据此区分"未调 LLM"与"调了但失败"
        - ``"context"`` — 从会话上下文中继承（如继承 current_stock 推断为追问）
        - ``"confirmation"`` — 用户对上一个待确认动作的响应
    - ``stocks``: 已解析出的置信度较高的股票或板块实体——能精确解析出
      的股票列表（已去重），每项为 Stock(code, name, market)
    - ``sectors``: 板块槽位——执行端统一消费的板块/市场对象（去重保序）：
      具名板块用板块名（"分析白酒板块" → ["白酒"]）；泛市场/指数场景
      用指数名原文（"研究上证指数" → ["上证"]）或市场名（"分析大A行情"
      → ["A股"]，无限定 → ["大盘"]）；个股路径为空列表
    - ``candidates``: 已解析出的带有歧义的股票实体——能解析名字，但
      股票名称有歧义时的候选列表，每项为 Stock(code, name, market)
    - ``unresolved_names``: 未知的股票名——确定不存在的指称（A 股全量
      库未命中的错误代码、并列未知名称）：确认机制仅收录可判定市场的
      确定非法指称，前提是系统有把握判定用户错了
    - ``unverified_codes``: 未知的股票代码——非全量库市场（hk/us 精选
      库）未命中的存疑代码：无法判定合法与否，不做确认，作为未验证
      标的透传执行端实查（行情工具/Futu 数据源有真实判定能力）；
      查无此股由 Agent 回复
    - ``needs_confirmation``: True 表示该意图需要用户确认后才能执行
    - ``reason``: 需要确认时的原因说明（如 "ambiguous_stock_name" / "low_confidence" / "stock_unresolved"）
    - ``pending_action``: 需要用户执行的确认动作描述，供 SSE 层发送
      action_required 事件。多轮确认链路的运行时键（original_request /
      resolved_stocks / confirmed）寄生在其内部
    - ``source_request``: 当前的 sub_message 文本——该任务的来源子消息
      （多任务切分/同句分解的任务各自携带；确认产物无当前子消息，
      为空串）
    - ``all_tags_recognized``: 子消息全部 token 均带语义标签（分词层无
      空 tag 残段）——规则视野完备性判据，由第四步单源设置，与置信度
      联合构成 LLM 兜底豁免（``_should_use_llm``）
    """

    intent: WebIntent
    confidence: float
    source: str = "rule"       # 默认为规则来源
    stocks: List[Stock] = field(default_factory=list)
    sectors: List[str] = field(default_factory=list)   # 板块名槽位（去重保序）
    candidates: List[Stock] = field(default_factory=list)
    unresolved_names: List[str] = field(default_factory=list)
    unverified_codes: List[str] = field(default_factory=list)  # hk/us 存疑代码，透传执行端实查
    needs_confirmation: bool = False
    reason: str = ""
    pending_action: Optional[Dict[str, Any]] = None
    source_request: str = ""             # 当前的 sub_message（任务来源子消息）
    tokens: List[str] = field(default_factory=list)  # 对应的tokens
    # 子消息全部 token 均带语义标签（分词层无空 tag 残段）——规则视野
    # 完备性判据，由第四步单源设置，与置信度联合构成 LLM 兜底豁免
    # （见 resolver _should_use_llm）
    all_tags_recognized: bool = True
    # 规则裁决自知"单任务表达不完"：quote 词与强分析词共存（深度被裁决
    # 序吸收）——由第四步单源设置，_should_use_llm 见它即取消高置信豁
    # 免，交 LLM 多意图复核
    multi_intent_hint: bool = False
    inherited_stock_code: str = ""    # 从会话/请求上下文继承的当前股票代码（#1619）；历史标的的持久化通道是会话键 recent_stocks，任务不携带副本

    def __post_init__(self) -> None:
        """stocks/candidates 统一过 ``_coerce_stock``：str 代码与 dict 载荷
        归一为 Stock，形状异常条目剔除（两个列表同一契约、同一口径）。"""
        self.stocks = [s for s in map(_coerce_stock, self.stocks) if s]
        self.candidates = [s for s in map(_coerce_stock, self.candidates) if s]

    @property
    def primary_stock_code(self) -> str:
        """注入 stock-scope 的主股票代码。

        单代码直接返回；多代码（比较场景）返回空串交执行端处理——绝不
        返回历史标的，否则"对比000858和300750"会错误锁定上一轮的股票；
        无代码时返回 inherited_stock_code（#1619 锁定股置顶，退
        recent_stocks[0]）保持锁定。
        """
        if len(self.stocks) == 1:
            return self.stocks[0].code
        if len(self.stocks) >= 2:
            return ""
        return self.inherited_stock_code
