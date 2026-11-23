# -*- coding: utf-8 -*-
"""
Web Chat 意图识别层 — 主解析器（Intent Resolver）。

按六步流水线把一条用户消息解析为**二维任务组列表**（保序、可含确认
短路；外层组=子消息，形状契约见 ``resolve`` docstring）：
  - ``web_intent_types.py``     — 意图枚举、WebIntentResolution、Token、
                                  tag/关键词/正则常量（共享数据字典）；
  - ``web_intent_tokenizer.py`` — 六步分词管道与实体提取（本层只消费其
                                  产物，绝不重跑全管道）；
  - ``web_intent_resolver.py``  — 本模块：主流程、规则/LLM/确认消费、
                                  session/SSE 辅助。

== 六步流程（resolve 主链，顺序固定）==

  第一步 上下文准备与空输入短路
     继承股票（request_context.current_stock_code 优先，退
     recent_stocks[0]）；空/非文本/纯标点 → 闲聊 0.5 规则直达（带继承
     股票，不动 pending——空消息不是确认响应）。

  第二步 全消息分词（仅此一次）
     ``_preprocess_text`` + ``_identify_stock_codes`` 全局各调用一次，
     之后所有阶段只消费这份 tokens，禁止重复冗余调用。

  第三步 消息级多任务切分 ``_split_sub_messages(tokens, message)``
     输出 tokens 二维列表（第一维 = 一条子消息的 token 序列），元素
     恒不变——只按序分组，绝不重分词/改写 token。两类切口：消息消费
     型标点（，。！？；）落在相邻 token 的原文间隙即下刀（token 文本
     大小写折叠定位，canonical 改写的代码退用数字核）；顺序连接词
     （然后/其次/接着/顺便）开头的 token 前下刀。切口全部落在 token
     边界，词内"然后"（"居然后市"= 居然+后市）无从触发；并列连接词
     （和/与/跟/及）不切——并列对象属于同一个任务。

  第四步 逐子消息规则级解析（多意图任务列表）
     对每条子消息跑"规则阶段"（``_classify_rule``），产出【平权】任务
     列表（无主次）：主体判定梯选出主体对象任务（个股/泛市场·指数·纯
     市场词/板块独占/追问继承/存疑代码/闲聊——纯市场限定词是唯一对象
     解释时同大盘口径进兜底对象，槽位填市场名；与个股实体联动时是限
     定词交分支3 消歧），板块对象与组合语境未被主体消费
     时各自独立生成任务（板块任务/组合任务，与主体任务共享实体解析）
     ——组 = 子消息。歧义组/候选/裸数字等信号随身携带。大模型兜底
     【延后不跑】。

  第五步 确认消费（pending confirm_stock 存在时）
     无 ambiguity_group 直接跳过。回复子消息画像：fresh＝点名候选外新
     entity；has_content＝候选空间外的自带语义（意图类 token／板块指
     数对象／未识别名／存疑代码／未识别内容）。保留是默认、丢弃是例
     外：判为纯消歧答案的必要条件是子消息的全部内容都落在待确认候选
     空间之内，部分内容充当消歧证据不排斥请求角色。非 fresh 一律参
     与收窄（组 × 子消息 × entity 三重循环，复述组名跳过）；保留为任
     务＝fresh／has_content／矛盾贡献者。无候选组的 stock_unresolved
     链以同口径判答：恰一只纯形实体回复（fresh 且无 has_content）结算
     为纠正标的（原意图与随行实体保留）；单个确认任务被多个实体命中
     ＝匹配失败（比较/新请求，按新话题），带自身语义的回复按新话题。
     结算（组间独立）：answers 去重后 0 个 → 未解；>1 个 → 矛盾（用户
     在同一条回复里点名多个候选＝比较/新请求）——该组弃置且贡献子消
     息整轮判新话题；恰 1 个 →
     消解记入 confirmed。出口：全部 answers 为空 → 未消解确认作废、
     已消解兄弟随行，按新
     话题解析；全部消解 → 确认解除就地落位 ＋ 保留任务；存在未解 →
     重建 pending_action（未解组 ＋ confirmed 累积 ＋ resolved_stocks
     随行）继续等待。消费出口统一身份选择式收尾：recovered 组（重建的
     未消解任务／已消解任务／随行兄弟）一律原样随行——它们上轮已收尾，
     重过收尾会对已确认任务重跑 LLM 兜底（二次意见污染用户消歧结果）、
     对低置信来源任务二次短路；本轮 kept 组按子消息分组照常过第六步
     收尾（组=子消息不变量跨消费保持，一条子消息至多一次多意图枚举），
     确认状态与日志当轮浮出。

  第六步 幸存任务收尾 ``_finalize_task()``
     ① 补跑 LLM 兜底：低置信/无信号才触发，tag 全识别的高置信结果
        （≥0.8）与高置信主体豁免（candidates 不参与触发判据——歧义
        出口是用户确认）；失败退回规则结果（source=llm_failed），
        代码须过查库闸门防编造。
     ② 确认判定补齐（``_finalize_confirmation``）：无锚点执行类 → 低
        置信守卫收口；歧义候选非空 → 建 ambiguity_group；无法解析名
        称 → 等用户重给；置信度 <0.6 → 低置信。

     确认收口：任一任务待确认 → 整链短路（判定权在消费方 any()）。
     不做同意图折叠——多标的任务（"阿里的走势，平安呢"两个标的）各自
     独立执行、各自锁定 stock scope，聚合不改变 Agent 输出质量。

意图边界总纲（三判别测试 + 逐意图收/推）见 web_intent_types 模块
docstring；本模块注释只保留分支级依据。
"""

from __future__ import annotations

import json
import logging
import math
import threading
import unicodedata
from collections import defaultdict
from dataclasses import asdict, fields, replace
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from src.agent.web_intent_tokenizer import (
    _extract_markets_from_tokens, _identify_stock_codes, _preprocess_text,
)
from src.agent.web_intent_types import (
    A_CODE_FIRST_DIGITS, ALL_WEB_INTENTS, BARE_DIGIT_RE,
    BROAD_MARKET_SLOT_NAME, CONFIRMATION_CONFIDENCE_THRESHOLD,
    COORDINATION_PREFIXES, DECLINE_PATTERN, INTENT_WORD_RE, LAST_INTENT_KEY,
    LAST_RESOLUTIONS_KEY, LLM_CONFIDENCE_CAP, LLM_FENCE_RE, LLM_FOLLOWUP_LABEL,
    LLM_SYSTEM_PROMPT, MARKET_NORMALIZE, MARKET_SLOT_NAMES, Market,
    MAX_RECENT_STOCKS, NUMERIC_UNIT_SUFFIXES, PENDING_ACTIONS_KEY,
    POSSESSIVE_RE, RECENT_STOCKS_KEY, SEQUENCE_CONNECTIVE_RE,
    SUB_MESSAGE_PUNCT_RE, TAG_ACTION_PORTFOLIO,
    TAG_ACTION_QUOTE, TAG_ACTION_QUOTE_FETCH, TAG_ACTION_RESEARCH, TAG_COMPARISON,
    TAG_FOLLOWUP,
    TAG_OPINION, TAG_QUESTION, TAG_REQUEST, TAG_SECTOR, TAG_SECTOR_NAME,
    TAG_SECTOR_N_STOCK, TAG_STOCK_CODE, TAG_STOCK_NAME, TAG_SUBJECT_INDEX,
    TAG_SUBJECT_MARKET_BROAD, TAG_SUBJECT_PORTFOLIO, TAG_SUBJECT_RESEARCH,
    TAG_UNKNOWN_NUMBER, Token, WebIntent, WebIntentResolution,
    _EXECUTING_INTENTS, _MARKET_KEYWORD_MAP, _classify_keyword,
    is_unknown_code_tag, is_wrong_code_tag, normalize_intent_label,
    sector_dedup_key, unknown_code_tag,
)
from src.services.name_to_code_resolver import Stock, lookup_stock_by_code

logger = logging.getLogger("web_intent")

__all__ = [
    "WebIntentResolver", "WebIntentResolution", "WebIntent", "Token", "Stock",
    "Market", "ALL_WEB_INTENTS", "LLM_FOLLOWUP_LABEL",
    "CONFIRMATION_CONFIDENCE_THRESHOLD", "LLM_CONFIDENCE_CAP",
    "MAX_RECENT_STOCKS", "RECENT_STOCKS_KEY", "PENDING_ACTIONS_KEY",
    "LAST_INTENT_KEY", "lookup_stock_by_code", "_preprocess_text",
    "_identify_stock_codes", "_extract_markets_from_tokens", "_dedup_stocks",
    "_disambiguate_by_market", "_merge_llm_result", "_parse_llm_payload",
    "_session_context", "_split_sub_messages", "apply_pending",
    "apply_outcome", "apply_resolution_to_session", "clear_pending_actions",
]


# =========================================================================
# 置信度表 — 按决策路径赋常量（表达"路径可靠程度"而非校准概率）
# =========================================================================


_CONFIDENCE_EXPLICIT_CODE = 0.9     # 显式代码（含交易所标注形态）：代码即标的
_CONFIDENCE_KEYWORD_STRONG = 0.85   # 意图关键词与实体共现（"分析茅台"）
_CONFIDENCE_BARE_NAME = 0.8         # 裸唯一名称（"茅台"）／存疑代码主体
_CONFIDENCE_CONTEXT_INHERIT = 0.75  # 上下文继承（追问/LLM followup 伪标签）
_CONFIDENCE_FALLBACK = 0.5          # 规则无可靠结论：必须 LLM 兜底或确认
_CONFIDENCE_LLM_EXEMPT = 0.8        # tag 全识别 + 该置信度以上：规则视野与判定双完备，免 LLM 复核
_CONFIDENCE_CONFIRMATION = 0.9      # 确认消费轮：用户已显式选定标的

# 规则分类查看的"意图标签"集合：出现即构成意图信号。filler/time/market
# 等辅助标签不单独构成意图（market 只提供范围与消歧）
_INTENT_TAGS = frozenset({
    TAG_REQUEST, TAG_SUBJECT_RESEARCH, TAG_ACTION_RESEARCH,
    TAG_QUESTION, TAG_OPINION, TAG_COMPARISON,
    TAG_SUBJECT_PORTFOLIO, TAG_ACTION_PORTFOLIO, TAG_ACTION_QUOTE,
    TAG_ACTION_QUOTE_FETCH, TAG_SUBJECT_MARKET_BROAD, TAG_SUBJECT_INDEX,
    TAG_FOLLOWUP,
})

# T2 强分析信号（"给观点"侧）：归因/评价/比较/预测。与数据词共现时获胜
_STRONG_RESEARCH_TAGS = frozenset({
    TAG_SUBJECT_RESEARCH, TAG_ACTION_RESEARCH, TAG_OPINION, TAG_COMPARISON,
})

# T2 数据点信号（"报数据"侧）。与泛动作词（request）共现时获胜，与强分析词共现时让位
_QUOTE_TAGS = frozenset({TAG_ACTION_QUOTE, TAG_ACTION_QUOTE_FETCH})

# 报数信号双 tag：action_quote（数据对象词）＋ action_quote_fetch（取数
# 动词）——词形区分在上游词池完成，下游只读 tag（T2 深度裁决两者同权，
# multi_intent_hint 只认数据对象侧）

# T1 个性化信号：持仓/自选股主题与操作
_PORTFOLIO_TAGS = frozenset({TAG_SUBJECT_PORTFOLIO, TAG_ACTION_PORTFOLIO})

# 确认轮的候选空间外锚点：这些 tag 出现说明回复子消息携带候选空间
# 之外的内容——分析/比较/提问请求，或板块/指数对象（板块裸提是对象
# 承载的请求，无动词形态）。保留是
# 默认：任一锚点在场，子消息保留为新任务走完整第六步收尾，⑤② 只丢弃
# 全部内容都落在待确认候选空间内的纯答案片段（单消费点：_reply_profile）
_COMPETING_TAGS = frozenset({
    TAG_REQUEST, TAG_SUBJECT_RESEARCH, TAG_ACTION_RESEARCH,
    TAG_ACTION_QUOTE, TAG_ACTION_QUOTE_FETCH, TAG_FOLLOWUP, TAG_COMPARISON,
    TAG_QUESTION,
    TAG_OPINION, TAG_SUBJECT_PORTFOLIO, TAG_ACTION_PORTFOLIO,
    TAG_SUBJECT_MARKET_BROAD, TAG_SUBJECT_INDEX,
    TAG_SECTOR, TAG_SECTOR_NAME, TAG_SECTOR_N_STOCK,
})

# 歧义组候选数上限：超过视为泛词噪声丢弃（"中国"命中中国平安/中石化/
# 中国联通等整族前缀 5 候选——跨市场同名歧义至多 3 候选 a/hk/us，
# 合法歧义不受影响）
_AMBIGUOUS_MAX_CANDIDATES = 3

# 并列残留防线的锚点：空段以连接词开头且紧邻前 token 是标的类
# （"茅台|和西藏建工"）→ 剥离连接词后的文本是并列名称候选，交确认轮补正
# （连接词前缀表 COORDINATION_PREFIXES 定义于 web_intent_types）
_COORDINATION_ANCHOR_TAGS = frozenset({
    TAG_STOCK_NAME, TAG_STOCK_CODE, TAG_SECTOR_NAME, TAG_SECTOR_N_STOCK,
})

# 非全量库市场的存疑代码 tag（未命中 ≠ 非法，透传执行端实查）
_UNVERIFIED_MARKET_TAGS = frozenset({
    unknown_code_tag("hk"), unknown_code_tag("us"),
})

# 链式主体线程的状态形态：上一子消息主体任务的三种
# 主体形态——确定标的集合 / 板块槽位 / 待消歧歧义组（名称+候选随行）。
# 追问片段（_classify_rule 分支6）据此继承：多标的整体继承 stocks、
# 板块前序继承 sectors、歧义前序继承候选组（与主体任务共待同一次消歧）；
# 单标的前序走 inherited_stock_code 通道（#1619 语义）
_ChainSubject = Tuple[List[Stock], List[str], List[Tuple[str, List[Stock]]]]


# =========================================================================
# 共享辅助 — Stock 载荷 / 去重 / 枚举安全（各步通用）
# =========================================================================


def _dedup_stocks(stocks: Iterable[Stock]) -> List[Stock]:
    """按 (code, market) 去重保序（首个出现者胜出）。"""
    firsts: Dict[Tuple[str, str], Stock] = {}
    for s in stocks:
        firsts.setdefault((s.code, s.market), s)
    return list(firsts.values())

def _stock_payload(stock: Stock) -> Dict[str, Any]:
    """Stock → SSE/会话可序列化 dict（json 兼容形态）。"""
    return {"code": stock.code, "name": stock.name, "market": stock.market}

def _stock_from_payload(entry: Any) -> Optional[Stock]:
    """会话/LLM 载荷条目（dict 或 Stock）→ Stock；形状异常（缺 code 的
    dict / 其它类型）返回 None。"""
    if isinstance(entry, Stock):
        return entry
    if isinstance(entry, dict) and entry.get("code"):
        return Stock(code=entry.get("code", ""), name=entry.get("name", ""),
                     market=entry.get("market", ""))
    return None

def _payload_stocks(entries: Any) -> List[Stock]:
    """载荷列表 → Stock 列表（逐条过 ``_stock_from_payload``，异常剔除）。"""
    return [s for s in map(_stock_from_payload, entries or []) if s]

def _group_payload(
    name: str, candidates: List[Stock], intent: str, source_request: str,
) -> Dict[str, Any]:
    """歧义组的可序列化投影（预挂/重建/兜底建组三处共用的构造点）。"""
    return {
        "name": name,
        "candidates": [_stock_payload(c) for c in candidates],
        "intent": intent,
        "source_request": source_request,
    }


def _group_codes(g: Dict[str, Any]) -> set:
    """歧义组载荷的候选代码集合（dict 候选缺 code 记 None，集合运算自然忽略）。"""
    return {c.get("code") for c in g.get("candidates", [])
            if isinstance(c, dict)}


def _prehung_groups(
    ambiguous: List[Tuple[str, List[Stock]]],
    candidates: List[Stock],
    intent: str,
    source_request: str,
) -> Optional[Dict[str, Any]]:
    """歧义未消解时预挂的组级 pending_action（不置确认——第六步职责）。
    只收录仍处歧义的组（候选已被市场词消解的组随之剔除），与 candidates
    保持同一扩张收缩视图；无候选返回 None。"""
    if not candidates:
        return None
    cand_codes = {c.code for c in candidates}
    return {
        "action": "confirm_stock",
        "intent": intent,
        "groups": [
            _group_payload(name, group, intent, source_request)
            for name, group in ambiguous
            if any(c.code in cand_codes for c in group)
        ],
    }

def _safe_web_intent(label: str) -> WebIntent:
    """pending 中的意图标签 → 枚举；形状异常（bogus）回退 stock_analysis。"""
    try:
        return WebIntent(label)
    except ValueError:
        return WebIntent.STOCK_ANALYSIS


# =========================================================================
# 第一步 — 上下文准备：会话归一 + 决策日志（空输入短路在 resolve 内）
# =========================================================================


def _session_context(source: Any) -> Dict[str, Any]:
    """任意会话形态（dict / 带 .context 的对象 / 其他）→ 可读 dict。
    纯归一化无副作用：LLM 兜底的会话上下文由 resolve 经 context 形参
    显式传递，不经模块级全局通道。"""
    if isinstance(source, dict):
        return source
    ctx = getattr(source, "context", None)
    return ctx if isinstance(ctx, dict) else {}


def _log_resolution(path: str, resolution: WebIntentResolution) -> None:
    """每次意图决策一行 info 日志（SSE 链路排障的主线索）。"""
    logger.info(
        "[WebIntent] resolved via %s: intent=%s confidence=%.2f source=%s "
        "reason=%s codes=%s inherited=%s confirm=%s",
        path,
        resolution.intent.value,
        resolution.confidence,
        resolution.source,
        resolution.reason or "-",
        ",".join(s.code for s in resolution.stocks) or "-",
        resolution.inherited_stock_code or "-",
        resolution.needs_confirmation,
    )


# =========================================================================
# 第三步 — 消息级多任务切分（tokens 二维；元素恒不变，仅按序分组）
# =========================================================================

def _split_sub_messages(
    tokens: Union[str, List[Token]],
    message: Optional[str] = None,
) -> List[List[Token]]:
    """消息级多任务切分（第三步，切口规则与不变量见模块 docstring）：
    全局 tokens → 子消息 tokens 二维列表，元素恒不变，只按序分组。
    单参数形态（传文本）为独立入口：内部自跑全管道。
    """
    if message is None or isinstance(tokens, str):
        message = tokens if isinstance(tokens, str) else (message or "")
        tokens = _identify_stock_codes(_preprocess_text(message)[1])
    token_list: List[Token] = list(tokens)  # type: ignore[arg-type]
    if not token_list:
        return [token_list]
    low = unicodedata.normalize("NFKC", message or "").lower()
    subs: List[List[Token]] = [[]]
    pos = 0
    for t in token_list:
        needle = t.text.lower()
        start = low.find(needle, pos) if needle else -1
        step = len(needle)
        if start < 0:  # canonical 改写代码：数字核回退（hk00700 / 00700.HK）
            needle = "".join(ch for ch in t.text if ch.isdigit())
            step = len(needle)
            start = low.find(needle, pos) if needle else -1
        cut = (start >= 0
               and bool(SUB_MESSAGE_PUNCT_RE.search(low[pos:start])))
        if start >= 0:
            pos = start + step
        cut = cut or bool(SEQUENCE_CONNECTIVE_RE.match(t.text))
        if cut:
            subs.append([])
        subs[-1].append(t)
    subs = [s for s in subs if s]
    return subs if subs else [token_list]


# =========================================================================
# 第四步 — 规则级解析：tokens 进、规则态 resolution 出（LLM 延后不跑）
# =========================================================================


def _token_facts(sub_tokens: List[Token]) -> Dict[str, Any]:
    """一次遍历收集判定树所需的全部事实：标签集合、确定实体、歧义组、
    代码辨认失败/存疑、裸数字（含四重闸门提升）、板块槽位（含泛称回溯
    与 combo）、指数、市场词。
    """
    tags: set = set()
    stocks: List[Stock] = []
    seen: set = set()

    def _add_stock(s: Stock) -> None:
        key = (s.code, s.market)
        if key not in seen:
            seen.add(key)
            stocks.append(s)

    ambiguous: List[Tuple[str, List[Stock]]] = []
    wrong_codes: List[str] = []
    unknown_codes: List[str] = []
    unverified_codes: List[str] = []
    unknown_numbers: List[str] = []
    unresolved_names: List[str] = []
    index_subjects: List[str] = []
    named_sectors: List[Tuple[int, str]] = []
    sector_names: set = set()
    sector_combo = False
    code_entity = False

    def _add_sector(index: int, name: str) -> None:
        if name and name not in sector_names:
            sector_names.add(name)
            named_sectors.append((index, name))

    for i, t in enumerate(sub_tokens):
        if t.tag:
            tags.add(t.tag)
        # 泛称后缀回溯——词池外行业名提取（"固态电池概念"）：无语义/
        # 代码形 token 紧邻板块泛称 → 入板块槽并置 combo；该 token 不
        # 按坏代码/存疑代码记账
        nxt = sub_tokens[i + 1] if i + 1 < len(sub_tokens) else None
        label = t.text.strip()
        backtracked = bool(
            nxt is not None and nxt.tag == TAG_SECTOR
            and len(label) >= 2 and not label.isdigit()
            and (not t.tag or is_unknown_code_tag(t.tag)
                 or is_wrong_code_tag(t.tag)))
        if backtracked:
            _add_sector(i, label)
            sector_combo = True
        if t.tag == TAG_STOCK_CODE:
            code_entity = True
            for s in t.stocks or ():
                _add_stock(s)
        elif t.tag == TAG_STOCK_NAME:
            group = list(t.stocks or ())
            if len(group) == 1:
                _add_stock(group[0])
            elif group and len(group) <= _AMBIGUOUS_MAX_CANDIDATES:
                ambiguous.append((t.text, group))
        elif is_wrong_code_tag(t.tag) and not backtracked:
            wrong_codes.append(t.text)
        elif is_unknown_code_tag(t.tag) and not backtracked:
            if t.tag in _UNVERIFIED_MARKET_TAGS:
                unverified_codes.append(t.text)
            else:
                unknown_codes.append(t.text)
        elif t.tag == TAG_UNKNOWN_NUMBER:
            unknown_numbers.append(t.text)
            # 量词闸门只拦无语义标签的量词 token（万元/点/年/股…）；
            # 已打标签的词是语义成分不是量词——"股价"（action_quote）首字
            # 撞量词"股"不得误伤代码提升
            has_unit = (nxt is not None and not nxt.tag
                        and nxt.text[:1] in NUMERIC_UNIT_SUFFIXES)
            # 裸数字四重闸门提升：6 位 + 首码白名单 + 非量词后缀 + 查库命中
            digits = t.text
            if (not has_unit and len(digits) == 6
                    and (digits[0] in A_CODE_FIRST_DIGITS
                         or digits.startswith("92"))):
                stock = lookup_stock_by_code(digits)
                if stock is not None:
                    code_entity = True
                    _add_stock(stock)
        elif (not t.tag and i > 0
                and sub_tokens[i - 1].tag in _COORDINATION_ANCHOR_TAGS):
            name = next(
                (t.text[len(p):].strip()
                 for p in COORDINATION_PREFIXES if t.text.startswith(p)), "")
            if (len(name) >= 2 and not name.isdigit()
                    and name not in unresolved_names):
                unresolved_names.append(name)
        # 具名指数与具名板块同入板块槽（"上证"）：未被主体消费的对象独
        # 立成任务（_tasks 平权分解），不因与个股/坏码等主体共存而静默
        # 丢弃；tag 保持 SUBJECT_INDEX 不变，分支4 的路由与置信不受影响
        if t.tag in (TAG_SECTOR_NAME, TAG_SECTOR_N_STOCK, TAG_SUBJECT_INDEX):
            _add_sector(i, t.text)
            if nxt is not None and nxt.tag == TAG_SECTOR:
                sector_combo = True
        if t.tag == TAG_SUBJECT_INDEX and t.text not in index_subjects:
            index_subjects.append(t.text)

    return {
        "tags": tags, "stocks": stocks, "ambiguous": ambiguous,
        "wrong_codes": wrong_codes, "unknown_codes": unknown_codes,
        "unverified_codes": unverified_codes, "unknown_numbers": unknown_numbers,
        "unresolved_names": unresolved_names, "index_subjects": index_subjects,
        "sectors": [n for _i, n in sorted(named_sectors)],
        "sector_combo": sector_combo, "code_entity": code_entity,
        "markets": _extract_markets_from_tokens(sub_tokens),
        "has_entity": bool(stocks or ambiguous),
    }


def _disambiguate_by_market(
    candidates: List[Stock], markets: List[Any]
) -> Tuple[Optional[List[Stock]], List[Stock]]:
    """市场词消歧：候选按市场过滤后恰剩一只 → 采信；零只（矛盾）或
    多只 → None（保守保留全量候选交确认/LLM）。展示列表恒为全量候选。"""
    if not markets:
        return None, candidates
    market_values = {m.value if hasattr(m, "value") else str(m) for m in markets}
    hits = [c for c in candidates if c.market in market_values]
    if len(hits) == 1:
        return hits, candidates
    return None, candidates


def _sector_branch(
    f: Dict[str, Any], sub_tokens: List[Token],
) -> Tuple[WebIntent, float]:
    """板块类任务的深度小梯子（主体判定分支5 与板块对象任务同口径）：
    数据词且无强分析词 → 行情查询；其余板块分析（精确池命中或相邻
    组合 0.85，双解未消 0.5）。"""
    if (_QUOTE_TAGS & f["tags"]) and not (_STRONG_RESEARCH_TAGS & f["tags"]):
        return WebIntent.QUOTE_LOOKUP, _CONFIDENCE_KEYWORD_STRONG
    # 指数槽位与具名板块同证据权重："指数"后缀是 market_broad 非 sector
    # 泛称，combo 判据覆盖不到，须显式计入 exact 判据
    exact_sector = any(t.tag in (TAG_SECTOR_NAME, TAG_SUBJECT_INDEX)
                       for t in sub_tokens)
    confidence = (_CONFIDENCE_KEYWORD_STRONG
                  if (f["sector_combo"] or exact_sector) else _CONFIDENCE_FALLBACK)
    return WebIntent.SECTOR_ANALYSIS, confidence


def _depth_branch(tags: set, text: str) -> WebIntent:
    """个股主体的 T1/T2 深度裁决（主体判定分支 1/3/7 单点共用）：
    T1 持仓操作词指向个股＝组合语境下的个股评估，持仓主题＋第一人称
    领属＋无强分析词（"我的茅台仓位重不重"）同——强分析词在场则是
    答案人人相同的研究维度；T2 强分析词 > 数据词 > 泛动作词，裸个股
    默认分析。坏码/存疑码主体同享此梯：标的可疑只影响确认/透传，
    不改写请求的深度语义。"""
    if (TAG_ACTION_PORTFOLIO in tags
            or (TAG_SUBJECT_PORTFOLIO in tags
                and POSSESSIVE_RE.search(text)
                and not (_STRONG_RESEARCH_TAGS & tags))):
        return WebIntent.PORTFOLIO_ANALYSIS
    if not (_STRONG_RESEARCH_TAGS & tags) and (_QUOTE_TAGS & tags):
        return WebIntent.QUOTE_LOOKUP
    return WebIntent.STOCK_ANALYSIS


def _classify_rule(
    sub_tokens: List[Token],
    last_intent: str = "",
    inherited_stock_code: str = "",
    prev_subject: Optional[_ChainSubject] = None,
) -> List[WebIntentResolution]:
    """规则优先的意图判定（第四步：tokens 进、平权任务列表出；整体契约
    见模块 docstring）。

    主体判定梯产出首个任务，裁决序固定：wrong code 确认 → T1 个性化
    （无个股指称）→ T3 个股 [T1 组合语境 / T2 深度：强分析词 > 数据词 >
    泛动作词 > 默认分析] → 泛市场指数 [兜底对象：默认报数，观点/动作词
    升级板块] → 板块 → 追问继承 → 存疑代码 → 无信号闲聊（边界总纲见
    web_intent_types）。板块对象/组合语境未被主体消费时各自独立生成平权
    任务（板块任务不携带 stocks——板块语义排斥个股实体；组合任务与主体
    任务共享实体解析，"分析茅台的持仓"无领属不生成，是机构持仓研究
    维度）。prev_subject 是链式主体线程状态源（上一子消息主体任务的
    (stocks, sectors, ambiguous) 三形态，首片段 None）——追问继承（分支6）
    据此继承前序主体状态。
    """
    f = _token_facts(sub_tokens)
    text = "".join(t.text for t in sub_tokens)
    tokens_payload = [t.text for t in sub_tokens]
    # 视野完备性：任一空 tag 残段（词池外口语/刷屏 unknown_token）即
    # False，与置信度联合构成第六步 LLM 兜底的豁免判据
    all_tagged = all(t.tag for t in sub_tokens)

    def _task(
        intent: WebIntent, confidence: float, multi_hint: bool,
        source: str = "rule",
        ambiguous: Optional[List[Tuple[str, List[Stock]]]] = None,
        **extra: Any,
    ) -> WebIntentResolution:
        """平权任务公共构造器：子消息级共享上下文（文本/tokens/继承码/
        视野完备性）单点装配；歧义未消解时预挂组级 pending_action（不置
        确认——第六步职责）。组来源默认取本子消息事实，追问继承任务
        显式携带前序片段的歧义组。"""
        res = WebIntentResolution(
            intent=intent, confidence=confidence, source=source,
            inherited_stock_code=inherited_stock_code,
            tokens=tokens_payload, source_request=text,
            all_tags_recognized=all_tagged,
            multi_intent_hint=multi_hint, **extra)
        res.pending_action = _prehung_groups(
            f["ambiguous"] if ambiguous is None else ambiguous,
            res.candidates, res.intent.value, text)
        return res

    def _tasks(verdict: WebIntentResolution) -> List[WebIntentResolution]:
        """主体任务 ＋ 未被主体消费的并存对象任务（板块/组合语境）。"""
        tasks = [verdict]
        if f["sectors"] and not verdict.sectors:
            sector_intent, sector_conf = _sector_branch(f, sub_tokens)
            tasks.append(_task(
                sector_intent, sector_conf, verdict.multi_intent_hint,
                sectors=list(f["sectors"])))
        if (TAG_SUBJECT_PORTFOLIO in f["tags"]
                and POSSESSIVE_RE.search(text)
                and verdict.intent != WebIntent.PORTFOLIO_ANALYSIS):
            tasks.append(_task(
                WebIntent.PORTFOLIO_ANALYSIS, _CONFIDENCE_KEYWORD_STRONG,
                verdict.multi_intent_hint,
                stocks=list(verdict.stocks), candidates=list(verdict.candidates)))
        return tasks

    tags = f["tags"]
    # multi_intent_hint＝"单任务表达不完"的自首：数据对象级 quote 词与强
    # 分析/组合词同场（纯取数动词"看下…走势"不算）、组合泛指×显式动作
    # 词（主体显式如"持仓的茅台股价"不触发）、个股代码×板块对象——
    # resolution 只有一个 intent 字段，这类并存交 LLM 多意图复核拆分
    # （多标的单任务由 stocks[] 原生承载，不算自首）
    quote_obj = TAG_ACTION_QUOTE in tags
    action_cls = (_INTENT_TAGS - _PORTFOLIO_TAGS - {
        TAG_QUESTION, TAG_FOLLOWUP, TAG_SUBJECT_MARKET_BROAD,
        TAG_SUBJECT_INDEX})
    multi_hint = bool(
        (quote_obj and ((_STRONG_RESEARCH_TAGS & tags) or (_PORTFOLIO_TAGS & tags)))
        or ((not f["has_entity"]) and (_PORTFOLIO_TAGS & tags)
            and (action_cls & tags))
        or (TAG_SECTOR in tags and bool(
            f["code_entity"] or f["unverified_codes"] or f["unknown_codes"]))
    )
    markets = f["markets"]
    market_value = markets[0].value if len(markets) == 1 else None

    # 1) 确定不存在的代码：直接以确认收尾，不走 LLM（LLM 也无法凭空造股）；
    #    深度语义照常过 _depth_branch——标的可疑只影响确认，不改写请求意图
    if f["wrong_codes"] and not f["has_entity"]:
        return _tasks(_task(
            _depth_branch(tags, text), _CONFIDENCE_EXPLICIT_CODE, multi_hint,
            unresolved_names=list(f["wrong_codes"])))

    # 2) T1 个性化（无个股指称）：整体组合语境，深度测试不介入
    #    （sectors 槽位由各执行类分支统一投影补挂）
    if _PORTFOLIO_TAGS & tags and not f["has_entity"]:
        return _tasks(_task(
            WebIntent.PORTFOLIO_ANALYSIS, _CONFIDENCE_KEYWORD_STRONG,
            multi_hint))

    # 3) T3 对象=个股：T1 定组合语境，T2 定深度
    if f["has_entity"]:
        confidence = (_CONFIDENCE_EXPLICIT_CODE if f["code_entity"]
                      else _CONFIDENCE_KEYWORD_STRONG if tags & _INTENT_TAGS
                      else _CONFIDENCE_BARE_NAME)

        stocks = list(f["stocks"])
        candidates: List[Stock] = []
        for _name, group in f["ambiguous"]:
            picked, display = _disambiguate_by_market(group, markets)
            if picked:
                stocks.extend(picked)
            else:
                candidates = _dedup_stocks(candidates + display)
        # T1/T2 深度裁决走 _depth_branch（判据注释见该函数，与坏码/存
        # 疑码主体同口径）；板块/ETF 对象同句时由 _tasks 再分解
        return _tasks(_task(
            _depth_branch(tags, text), confidence, multi_hint,
            stocks=stocks, candidates=candidates,
            unresolved_names=[*f["wrong_codes"], *f["unresolved_names"]],
            unverified_codes=list(f["unverified_codes"])))

    # 4) 泛市场/指数/纯市场词：兜底对象——仅当市场词是句子的唯一对象
    #    解释时直达（具名板块/存疑代码在场时"行情"是语境而非对象；与
    #    个股实体联动时是市场限定词而非对象——"港股阿里"由分支3按市场
    #    消歧消费；裸数字在场（"港股00700"）时对象解释不唯一，交 LLM
    #    复核，绝不当板块报市场行情而静默丢实体）；sectors 统一槽位用
    #    指数名原文，纯泛市场用市场名（"大盘"），纯市场限定词用市场
    #    槽（"港股"）；观点/动作词升级板块分析，默认报数
    _has_specific_subject = (
        f["unverified_codes"] or f["unknown_codes"]
        or bool({TAG_SECTOR, TAG_SECTOR_NAME, TAG_SECTOR_N_STOCK} & tags)
    )
    _market_only_subject = bool(markets) and not f["unknown_numbers"]
    if ((TAG_SUBJECT_MARKET_BROAD in tags or TAG_SUBJECT_INDEX in tags
         or _market_only_subject)
            and not _has_specific_subject):
        broad_sectors = (list(f["index_subjects"]) if f["index_subjects"]
                         else [MARKET_SLOT_NAMES.get(market_value or "",
                                                      BROAD_MARKET_SLOT_NAME)])
        branch = (WebIntent.SECTOR_ANALYSIS
                  if (_STRONG_RESEARCH_TAGS & tags) or (TAG_REQUEST in tags)
                  else WebIntent.QUOTE_LOOKUP)
        return _tasks(_task(branch, _CONFIDENCE_KEYWORD_STRONG, multi_hint,
                            sectors=broad_sectors))

    # 5) 板块/行业：数据词报数，其余板块分析（``_sector_branch`` 同口径）。
    #    行业名精确命中词池或"行业名+泛称"相邻组合消除双解 → 0.85；仅回
    #    溯提取的词外语与行业兼股票名（"机器人"）双解未消 → 0.5 交 LLM。
    #    unverified 只随分析路径携带（报数路径不透传存疑代码）
    if not f["has_entity"] and bool(
            {TAG_SECTOR, TAG_SECTOR_NAME, TAG_SECTOR_N_STOCK} & tags):
        intent, confidence = _sector_branch(f, sub_tokens)
        extra = ({"unverified_codes": list(f["unverified_codes"])}
                 if intent is WebIntent.SECTOR_ANALYSIS
                 and f["unverified_codes"] else {})
        return _tasks(_task(intent, confidence, multi_hint,
                            sectors=list(f["sectors"]), **extra))

    # 6) 追问继承：无新股票 +（followup 词或无主体意图句——主题缺失默认
    #    主体为"它"；要求动作类意图词在场，纯疑问碎片不继承）+ 上轮执行
    #    类意图。守卫：消息含"未消化"信号（空 tag 段/存疑代码/裸数字）时
    #    不得继承——门控对动作词类不偏待，否则"现在能买09932吗"类消息被
    #    继承吸收、用户显式指称的标的被静默丢弃；被拦截的消息交 LLM 复核
    #    或存疑代码透传分支（宁可不做，不可做错）
    unresolved_subject = (
        any(not t.tag for t in sub_tokens)
        or bool(f["unknown_numbers"]) or bool(f["unknown_codes"])
        or bool(f["unverified_codes"])
    )
    subjectless_intent = bool((_INTENT_TAGS - {TAG_QUESTION}) & tags)
    if ((TAG_FOLLOWUP in tags or subjectless_intent)
            and last_intent in ALL_WEB_INTENTS
            and WebIntent(last_intent) in _EXECUTING_INTENTS
            and not unresolved_subject):
        # 前序主体状态继承：多标的（比较）整体继承 stocks、板块前序继承
        # sectors、歧义前序继承候选组（组结构随行，与主体任务共待同一次
        # 消歧，一次答复各自落位）；单标的前序走 inherited_stock_code 通道
        # （#1619 语义）——三形态覆盖主体全部在场形态，追问
        # 片段绝不以无锚点执行类任务放行（触发无标的 Agent 工作流）
        inherit_stocks, inherit_sectors, inherit_ambiguous = [], [], []
        if prev_subject is not None:
            prev_stocks, prev_sectors, prev_ambiguous = prev_subject
            if len(prev_stocks) >= 2:
                inherit_stocks = list(prev_stocks)
            elif prev_sectors:
                inherit_sectors = list(prev_sectors)
            elif prev_ambiguous:
                inherit_ambiguous = [(n, list(g)) for n, g in prev_ambiguous]
        return _tasks(_task(
            WebIntent(last_intent), _CONFIDENCE_CONTEXT_INHERIT, multi_hint,
            source="context", sectors=inherit_sectors,
            stocks=inherit_stocks,
            candidates=_dedup_stocks(
                [c for _n, group in inherit_ambiguous for c in group]),
            ambiguous=inherit_ambiguous or None))

    # 7) 存疑代码主体：hk/us 非全量库未命中无法判定合法与否——用户显式
    #    写出代码即强指称，高置信放行透传实查（深度语义照常过
    #    _depth_branch）；与泛市场语境共存时对象无法判定（"板块"tag 已
    #    随 DFS 失败陪葬）——低置信交 LLM 裁定
    if f["unverified_codes"]:
        broad_ctx = (TAG_SUBJECT_MARKET_BROAD in tags
                     or TAG_SUBJECT_INDEX in tags)
        return _tasks(_task(
            _depth_branch(tags, text),
            _CONFIDENCE_FALLBACK if broad_ctx else _CONFIDENCE_BARE_NAME,
            multi_hint,
            unverified_codes=list(f["unverified_codes"])))
    if f["unknown_codes"]:
        return _tasks(_task(
            _depth_branch(tags, text), _CONFIDENCE_FALLBACK, multi_hint,
            unverified_codes=list(f["unknown_codes"])))

    # 8) 无信号：闲聊兜底（低置信触发 LLM 复核；非执行类不确认）
    return _tasks(_task(WebIntent.GENERAL_CHAT, _CONFIDENCE_FALLBACK, multi_hint))


# =========================================================================
# 第五步 — 确认消费：上轮确认任务 × 本轮规则态任务 → 就地消歧合并（二维进出）
# =========================================================================


def _pending_confirming_tasks(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """pending_actions 会话键 → 确认任务投影：确认存活的唯一权威
    （resolve 的消费闸门）＋ last_resolutions 缺失时的兼容载荷，包装为
    last_resolution 元素形态供消费链无感读取。"""
    pending_list = context.get(PENDING_ACTIONS_KEY)
    pending = next(
        (item for item in (pending_list if isinstance(pending_list, list) else [])
         if isinstance(item, dict) and item.get("action") == "confirm_stock"),
        None,
    )
    if pending is None:
        return []
    return [{
        "intent": str(pending.get("intent") or "stock_analysis"),
        "confidence": _CONFIDENCE_CONFIRMATION,
        "source": "confirmation",
        "needs_confirmation": True,
        "pending_action": pending,
        "source_request": str(pending.get("original_request") or ""),
    }]


def _canonical_digit_code(raw: str) -> str:
    """裸数字 → 规范代码形态：5 位纯数字补 HK 前缀（与 tokenizer
    ``_canonical_stock_code`` 同口径）；非纯数字形态（如 "GOOGL"）原样
    返回，不误加前缀。"""
    digits = raw.strip()
    if len(digits) == 5 and digits.isdigit():
        return f"HK{digits}"
    return digits


def _normalize_pending_groups(
    pending: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Stock]]:
    """pending → (有效歧义组列表, 组内全部候选)。兼容 groups 组式与顶层
    平铺（name/candidates 直接挂 pending 顶层）两类形状；候选逐条过
    ``_payload_stocks``（Stock 对象透传）。形状异常（非 dict／无候选）
    返回空列表——会话投影可能携带畸形 pending_action，解析器不得被击穿。"""
    if not isinstance(pending, dict):
        return [], []
    groups: List[Dict[str, Any]] = [
        {
            "name": str(g.get("name") or ""),
            "candidates": cands,
            "intent": str(g.get("intent") or ""),
            "source_request": str(g.get("source_request") or ""),
        }
        for g in pending.get("groups") or [] if isinstance(g, dict)
        and (cands := _payload_stocks(g.get("candidates")))
    ]
    if not groups and (flat := _payload_stocks(pending.get("candidates"))):
        groups = [{
            "name": str(pending.get("name") or ""),
            "candidates": flat,
            "intent": "",
            "source_request": str(pending.get("original_request") or ""),
        }]
    return groups, [s for g in groups for s in g["candidates"]]


def _sub_names_group(group: Dict[str, Any], sub_text: str) -> bool:
    """子消息是否点名该组主体（组名或任一候选名出现在文中，子串口径）。"""
    name = group.get("name") or ""
    return bool(name) and name in sub_text or any(
        c.name and c.name in sub_text for c in group["candidates"])


def _narrow_group_entities(
    group: Dict[str, Any],
    resolution: WebIntentResolution,
    all_groups: Optional[List[Dict[str, Any]]] = None,
) -> List[Stock]:
    """一个歧义组 × 一条子消息的收窄。证据通道（独立产出，重复指向
    同一候选由结算去重）：市场词收窄到唯一 > 候选名全等 > 候选名唯一
    子串 > 确定实体命中候选 > 裸数字短码；复述组名与多命中不构成证据。
    返回本组收窄到的候选列表（可空）。
    """
    cands: List[Stock] = group["candidates"]
    out: List[Stock] = []
    group_name = group.get("name") or ""
    sub_text = resolution.source_request or "".join(resolution.tokens)
    # 市场词从文本词池恢复（resolution.tokens 只存文本无 tag）
    low = sub_text.lower()
    markets = [mkt for mkt, kws in _MARKET_KEYWORD_MAP.items()
               if any(kw.lower() in low for kw in kws)]

    # 市场词：候选按市场过滤后恰剩一只（可同时收窄多组）。多组场景的
    # 作用域：子消息点名了它组主体时，被点名组候选覆盖的市场词已绑定
    # 该组、不作用于本组（按名指向的市场词串扰他组会造成错误消解或
    # 矛盾弃置）；点名组不覆盖的市场词保留全局证据
    if markets:
        market_values = {m.value for m in markets}
        if all_groups and not _sub_names_group(group, sub_text):
            market_values -= {
                c.market for g in all_groups
                if g is not group and _sub_names_group(g, sub_text)
                for c in g["candidates"]
            }
        filtered = [c for c in cands if c.market in market_values]
        if len(filtered) == 1:
            out.append(filtered[0])

    stripped = sub_text.strip()
    # 候选名全等（整条子消息就是一个候选全名）
    out += [c for c in cands
            if c.name and c.name == stripped and stripped != group_name]
    # 候选名唯一子串（"阿里巴巴港股"里的"阿里巴巴"命中全部同组候选 ≠ 证据）
    sub_hits = [c for c in cands
                if c.name and c.name in sub_text and stripped != group_name]
    if len(sub_hits) == 1:
        out.append(sub_hits[0])

    # 确定实体命中候选（"平安银行"解析为 000001 且在组内）＋ 裸数字短码
    # （"09988" → HK09988，扫描 4-6 位数字段）：按代码等值直查（同码取首个）
    by_code: Dict[str, Stock] = {}
    for c in cands:
        by_code.setdefault(c.code, c)
    out += [by_code[s.code] for s in resolution.stocks if s.code in by_code]
    out += [by_code[code]
            for code in map(_canonical_digit_code,
                            set(BARE_DIGIT_RE.findall(sub_text)))
            if code in by_code]
    return out


def _reply_profile(
    resolution: WebIntentResolution, universe: set,
) -> Tuple[bool, bool]:
    """消歧回复子消息画像（契约见模块 docstring 第五步）。

    - ``fresh``＝点名候选外实体（不参与收窄，整轮判新话题）：确定实体
      或歧义候选的代码不在待确认候选全集（``universe``）——候选空间
      内的实体提及（复述组名/点名候选）是答案空间回声，不构成保留理由；
    - ``has_content``＝候选空间外的自带语义：未识别名/存疑代码、板块/
      指数对象、意图词（token 级 tag 查表，clean+extend 全池）、未读
      内容（all_tags_recognized=False——保留后 LLM 视野轴兜底才可达）。
    两者皆 False＝纯消歧片段（市场词/候选名/裸数字/复述组名），已被
    ① 消费，不构成任务。
    """
    fresh = any(e.code not in universe
                for e in (*resolution.stocks, *resolution.candidates))
    has_content = bool(
        resolution.unresolved_names or resolution.unverified_codes
        or not resolution.all_tags_recognized
        or any(_classify_keyword(tok) in _COMPETING_TAGS
               for tok in resolution.tokens))
    return fresh, has_content


def _iter_tasks(tasks: Any):
    """任务集合 → 任务迭代器（一律二维契约下的兼容展平：二维组列表 /
    一维任务列表 / 单个 resolution 对象 / dict 与对象混合形态）。"""
    if isinstance(tasks, (list, tuple)):
        if tasks and isinstance(tasks[0], (list, tuple)):
            yield from (r for group in tasks for r in group)
        else:
            yield from tasks
    elif tasks is not None:
        yield tasks


def _as_task_groups(tasks: Any) -> List[List[Any]]:
    """任务集合 → 二维组列表：二维原样返回；一维非空列表整体视为单组
    （保持上轮组序，区别于逐元素成组）；空/非列表 → []（调用方兜底）。"""
    if isinstance(tasks, list) and tasks:
        return tasks if isinstance(tasks[0], list) else [tasks]
    return []


def _has_pending_action(task: Any) -> bool:
    """任务是否携带可消费的确认动作（needs_confirmation 且有 pending；
    low_confidence 确认无 pending 不算）。兼容对象与 asdict dict 投影。"""
    if isinstance(task, dict):
        return bool(task.get("needs_confirmation") and task.get("pending_action"))
    return bool(getattr(task, "needs_confirmation", False)
                and getattr(task, "pending_action", None))


def _is_pending_action(resolutions: Any) -> bool:
    """二维任务列表中是否存在待确认动作（判定权在消费方 any()；兼容
    一维/对象/dict 混合形态）。"""
    return any(_has_pending_action(r) for r in _iter_tasks(resolutions))


def _recover_resolution(payload: Dict[str, Any]) -> WebIntentResolution:
    """last_resolution 会话投影（asdict dict）→ WebIntentResolution：
    按 dataclass 字段反射取值（缺键落字段默认），仅 intent 与 Stock
    列表字段显式转换——字段增删无需同步本函数。"""
    stock_lists = {"stocks", "candidates"}
    kwargs: Dict[str, Any] = {}
    for f in fields(WebIntentResolution):
        raw = payload.get(f.name)
        if f.name == "intent":
            # 兼容 str / str-Enum（asdict 投影保留枚举实例，str() 会得到
            # "WebIntent.X" 形态——直接按值构造，不自作 str 包装）
            kwargs[f.name] = (raw if isinstance(raw, WebIntent)
                              else _safe_web_intent(raw or "stock_analysis"))
        elif f.name in stock_lists:
            kwargs[f.name] = _payload_stocks(raw)
        elif isinstance(raw, list):
            kwargs[f.name] = list(raw)
        elif raw is not None:
            kwargs[f.name] = raw
    return WebIntentResolution(**kwargs)


def _session_chain_subject(context: Dict[str, Any]) -> Optional[_ChainSubject]:
    """上一已执行轮落点主体的会话种子（跨轮追问的继承源）。落点＝最后
    一个执行类组的组首（与 apply_outcome 的 last_intent 同规则——意图
    与主体锚点出自同一任务）；短路轮不作种子；无可继承主体（stocks/
    sectors 皆空）返回 None，锚点退 recent_stocks 通道。"""
    groups = [
        [_recover_resolution(r) if isinstance(r, dict) else r for r in g]
        for g in _as_task_groups(context.get(LAST_RESOLUTIONS_KEY)) if g
    ]
    if not groups or any(t.needs_confirmation for g in groups for t in g):
        return None
    landing = next((g[0] for g in reversed(groups)
                    if g[0].intent in _EXECUTING_INTENTS), None)
    if landing is None:
        return None
    subject = (list(landing.stocks), list(landing.sectors), [])
    return subject if subject[0] or subject[1] else None


def _consume_confirmations(
    last_resolution: List[List[Any]],
    reply_groups: List[List[WebIntentResolution]],
) -> List[List[WebIntentResolution]]:
    """第五步（三步契约与结算规则见模块 docstring）：上轮确认任务 × 本轮
    规则态任务 → 证据驱动结算，二维进出、严格就地。

        last_resolution  = "分析茅台和阿里"        （上轮短路任务，整链未执行）
        reply_groups     = "港股，分析医药板块"      （聚合项 + 新任务）
        返回              ≈ "分析茅台和阿里(港股)，分析医药板块"

        特殊出口：拒绝词（逐子消息锚定、全部片段为完整拒绝形）→ [闲聊]
        （上轮整链作废）；全部确认任务零交互（纯模糊回应）→ 丢弃仍在
        等待的确认任务、已消解兄弟随行 ＋ 本轮任务原样（新话题，二维
        组结构保持）；stock_unresolved 链（无候选组）恰一只纯形实体回复
        按纠正标的结算原任务（intent 不从回复重推；单任务被多实体命中
        ＝匹配失败，按新话题）。
    """
    # 输入归一：二维组列表，dict 投影恢复为对象（字段完整：tokens 等）
    recovered = [[_recover_resolution(r) if isinstance(r, dict) else r
                  for r in g] for g in _as_task_groups(last_resolution)]
    reply_groups = _as_task_groups(reply_groups)
    reply_tasks = [t for g in reply_groups for t in g]
    confirmings = [t for g in recovered for t in g if _has_pending_action(t)]
    if not confirmings:
        return recovered
    all_candidate_codes = {
        s.code for task in confirmings
        for g in _normalize_pending_groups(task.pending_action)[0]
        for s in g["candidates"]
    }
    # 拒绝判定逐子消息锚定匹配（整串拼接丢分隔符会把"算了，不分析
    # 了"拼成用户从未说过的"算了不分析了"）：全部片段都是完整拒绝
    # 词形才取消——"算了，再看看茅台"类拒绝词＋内容仍按新话题解析
    texts = [(r.source_request or "".join(r.tokens)).strip()
             for r in reply_tasks]
    if texts and all(DECLINE_PATTERN.match(t) for t in texts):
        logger.info("confirm_stock declined by user")
        return [[WebIntentResolution(
            intent=WebIntent.GENERAL_CHAT, source="confirmation",
            confidence=_CONFIDENCE_CONFIRMATION)]]

    # 回复子消息画像：非 fresh 一律参与收窄；是否保留为任务由此画像＋
    # ① 的矛盾事实共同决定
    profiles = [_reply_profile(res, all_candidate_codes)
                for res in reply_tasks]

    # ---- ① 对 last_resolution 消歧聚合（逐确认任务，就地落位）----
    interacted = False
    voided_tasks: List[WebIntentResolution] = []
    contradiction_sources: set = set()  # 矛盾组贡献子消息（比较/新请求重开）
    correction_sources: set = set()  # 已被纠错消费的回复子消息（不保留为新任务）
    for task in confirmings:
        pending = task.pending_action
        groups, _all = _normalize_pending_groups(pending)
        if not groups:
            # stock_unresolved 纠错链：pending 无候选组，判答口径与歧义
            # 收窄同哲学——子消息全部内容就是候选空间外的实体指称
            # （fresh 且无 has_content）才算答案；带自身语义（意图词/
            # 板块/疑问）的回复按新话题走原路径。非 dict 的畸形 pending
            # 按形状异常跳过（不得击穿消费链）
            if (not isinstance(pending, dict)
                    or not pending.get("unresolved_names")):
                continue
            pure = [si for si, (res, (fr, hc)) in
                    enumerate(zip(reply_tasks, profiles))
                    if fr and not hc and res.stocks]
            # 恰一只才算纠正答案（每个确认任务 × 每个实体互相匹配）：
            # 单个任务被多个实体命中＝匹配失败——多实体并列是比较/新
            # 请求语义（与歧义组 ">1＝矛盾弃置" 同裁决），不消费；0 只
            # 纯片段同交零交互出口按新话题处理
            corrected = _dedup_stocks(
                s for si in pure for s in reply_tasks[si].stocks)
            if len(corrected) != 1:
                continue
            # 结算与"全部组落定"同口径：原意图随任务对象存活（不从回复
            # 重推）、随行实体合并保留、确认产物盖戳
            task.stocks = _dedup_stocks(task.stocks + corrected)
            task.candidates = []
            task.needs_confirmation = False
            task.reason = ""
            task.unresolved_names = []
            task.pending_action = None
            task.source = "confirmation"
            task.confidence = max(task.confidence, _CONFIDENCE_CONFIRMATION)
            correction_sources.update(pure)
            interacted = True
            continue
        answers: Dict[int, List[Stock]] = defaultdict(list)
        sources: Dict[int, List[int]] = defaultdict(list)
        for gi, group in enumerate(groups):
            for si, (fresh, _has_content) in enumerate(profiles):
                if not fresh and (hits := _narrow_group_entities(
                        group, reply_tasks[si], groups)):
                    answers[gi].extend(hits)
                    sources[gi].append(si)

        resolved: List[Stock] = []
        unresolved_groups: List[Dict[str, Any]] = []
        dropped_groups: List[int] = []
        for gi, group in enumerate(groups):
            uniq = _dedup_stocks(answers[gi])
            if len(uniq) == 1:
                resolved.append(uniq[0])
            elif len(uniq) > 1:
                dropped_groups.append(gi)  # 矛盾弃置：该组退出等待
            else:
                unresolved_groups.append(group)

        if not resolved and not dropped_groups:
            continue  # 零交互：该确认任务原样保留
        interacted = True
        # 矛盾＝同一条回复点名多个候选＝比较/新请求：贡献子消息整轮判新话题
        contradiction_sources.update(
            si for gi in dropped_groups for si in sources[gi])
        # 组全部矛盾弃置且无消解/随行实体：请求整体作废——用户已在同一
        # 条回复里给出新语义，空壳执行任务不产出
        voided = (bool(dropped_groups) and not unresolved_groups
                  and not resolved and not task.stocks)

        # 消解就地落位：原 stocks + 消解 + resolved_stocks 随行实体合并，去重保序
        carried = _payload_stocks(pending.get("resolved_stocks"))
        task.stocks = _dedup_stocks(task.stocks + resolved + carried)

        if unresolved_groups:
            # 歧义聚合不完全：未解组 + confirmed 累积随 pending_action 更新
            base_intent = str(pending.get("intent") or task.intent.value)
            confirmed = [c for c in pending.get("confirmed", [])
                         if isinstance(c, dict)]
            if resolved:
                confirmed.append({
                    "intent": base_intent,
                    "name": str(pending.get("name") or ""),
                    "stocks": [_stock_payload(s) for s in resolved],
                })
            task.pending_action = {
                "action": "confirm_stock",
                "intent": base_intent,
                "groups": [
                    _group_payload(
                        g.get("name", ""), g["candidates"],
                        g.get("intent") or base_intent,
                        g.get("source_request", ""))
                    for g in unresolved_groups
                ],
                "confirmed": confirmed,
                "original_request": str(pending.get("original_request") or ""),
                # 已落位实体随行（下轮消费合并回 stocks，多轮链不丢）
                "resolved_stocks": [_stock_payload(s) for s in task.stocks],
            }
        else:
            # 全部组落定：确认状态解除，任务就位为普通执行任务。
            # unresolved_names 一并清空——用户已通过标的交互给出主体，
            # 坏代码澄清轮结构上不可满足，保留只会把已消解标的重新短路
            task.candidates = []
            task.needs_confirmation = False
            task.reason = ""
            task.unresolved_names = []
            task.pending_action = None
            # 确认产物盖戳：用户显式选定标的是终局裁决，置信度抬升到
            # 确认档（来源路径的低置信标签不保留）
            task.source = "confirmation"
            task.confidence = max(task.confidence, _CONFIDENCE_CONFIRMATION)
            logger.info("confirm_stock resolved: %d group(s)", len(resolved))

        if voided:
            voided_tasks.append(task)

    if not interacted:
        # 全部确认任务零收窄：纯模糊回应。仍在等待的确认任务按"跑题即
        # 作废"丢弃；已消解待执行的兄弟任务保留（混链不因未消费的确认
        # 链连带销毁）；本轮任务原样随行（新话题，组结构保持）
        survivors = [g for g in (
            [t for t in g if not t.needs_confirmation] for g in recovered) if g]
        return survivors + reply_groups

    # ---- ② 丢弃本轮的纯消歧元素（fresh／自带语义／矛盾贡献者保留）----
    # 按子消息分组保留——"组=子消息"不变量保持，第六步的组级 LLM 枚举
    # 据此维持一条子消息至多一次；已被纠错消费的纯答案片段一并排除
    # （答案不双跑）
    keep_flags = [((fresh or has_content) and si not in correction_sources)
                  or si in contradiction_sources
                  for si, (fresh, has_content) in enumerate(profiles)]
    kept: List[List[WebIntentResolution]] = []
    cursor = 0
    for group in reply_groups:
        members = [res for res, keep in zip(group, keep_flags[cursor:]) if keep]
        cursor += len(group)
        if members:
            kept.append(members)

    # ---- ③ 一个列表合并：上轮（消歧后就位、作废壳剔除）＋ 本轮保留 ----
    survivors = [g for g in (
        [t for t in g if t not in voided_tasks] for g in recovered) if g]
    return survivors + kept


# =========================================================================
# 第六步 — 幸存任务收尾：LLM 兜底 → 确认判定
# =========================================================================


def _extract_json_object(text: str) -> Optional[str]:
    """从 LLM 噪声输出中提取第一个完整 JSON 对象：深度计数 + 字符串状态
    机，正确处理嵌套与字符串内花括号，不误并 JSON 之后的解释文字。"""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if escaped:  # 转义字符无条件跳过（escaped 只在字符串内置位）
            escaped = False
        elif in_string:
            if ch == "\\":
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


def _normalize_llm_item(item: Any) -> Optional[Dict[str, Any]]:
    """多意图数组单项 → 规范化载荷（与单对象形态同构）：intent 规范化
    校验、market 归一、sectors/unresolved_names 清洗。非法项 None。"""
    if not isinstance(item, dict):
        return None
    intent = normalize_intent_label(item.get("intent"))
    if intent is None or (intent != LLM_FOLLOWUP_LABEL
                          and intent not in ALL_WEB_INTENTS):
        return None
    item = dict(item)
    item["intent"] = intent
    raw_market = item.get("market")
    if isinstance(raw_market, str):
        item["market"] = MARKET_NORMALIZE.get(raw_market.strip().lower())
    elif not isinstance(raw_market, Market):
        item["market"] = None
    for list_field in ("sectors", "unresolved_names"):
        raw_list = item.get(list_field)
        if isinstance(raw_list, list):
            stripped_iter = (s.strip() for s in raw_list if isinstance(s, str))
            item[list_field] = [s for s in dict.fromkeys(stripped_iter) if s]
        else:
            item[list_field] = []
    return item


def _parse_llm_payload(content: str) -> Optional[Dict[str, Any]]:
    """从 LLM 文本回复解析 JSON 载荷；非 JSON/缺字段/非法 intent 返回 None
    （宁缺毋滥）。容错：首尾空白/BOM、code fence、JSON 前后噪声（深度
    计数提取）；``intents`` 数组优先（非法项丢弃，全非法回退单对象形态）。
    """
    cleaned = (content or "").strip().lstrip("\ufeff")
    if not cleaned:
        return None
    if "```" in cleaned:
        cleaned = LLM_FENCE_RE.sub("", cleaned).strip()
    result: Any = None
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        fragment = _extract_json_object(cleaned)
        if fragment is None:
            return None
        try:
            result = json.loads(fragment)
        except json.JSONDecodeError:
            return None
    if not isinstance(result, dict):
        return None
    raw_items = result.get("intents")
    if isinstance(raw_items, list):
        items = [i for i in map(_normalize_llm_item, raw_items) if i]
        if items:
            result["intents"] = items
            return result
        # 数组全非法：弹掉残键再回退单对象形态判定（下游只见规范化
        # 数组或不见该键，原始非法数组绝不流入多模式合并）
        result.pop("intents", None)
    # 单对象形态与数组元素共用同一规范化（_normalize_llm_item 是唯一
    # 规范化点，两条协议路径字段契约同构）
    item = _normalize_llm_item(result)
    if item is None:
        return None
    result.update(item)
    return result


def _drop_resolved_group(
    candidates: List[Stock], picked: List[Stock],
    pending: Optional[Dict[str, Any]],
) -> List[Stock]:
    """组感知候选收敛：剔除被选中代码所属歧义组的候选，兄弟组保留
    （整清会让未消解组静默丢失）；无预挂组结构退化为整清。"""
    groups = [g for g in (pending or {}).get("groups") or []
              if isinstance(g, dict)]
    if not groups:
        return []
    picked_codes = {c.code for c in picked}
    drop = set(picked_codes)
    for g in groups:
        g_codes = _group_codes(g)
        if g_codes & picked_codes:
            drop |= g_codes
    return [c for c in candidates if c.code not in drop]


def _merge_llm_result(
    rule_resolution: WebIntentResolution,
    payload: Dict[str, Any],
    context: Dict[str, Any],
    rule_view: Optional[WebIntentResolution] = None,
) -> WebIntentResolution:
    """LLM 载荷 → WebIntentResolution：校验、压置信度（≤ LLM_CONFIDENCE_CAP）、
    防幻觉合并。followup 伪标签转继承上轮意图（非执行类降闲聊）；stock_code
    三道闸门（∈ 歧义候选 → 查库命中 → 未命中按市场分流：hk/us 透传实查、
    a 股记 unresolved 交确认）；规则侧硬信号（实体/板块）保留，LLM 板块名/
    未解名以"原文出现"为闸门合入（板块无注册表，防编造）。

    ``rule_resolution`` 是元素基座：多元素拆分时其实体槽已被重置，只承担
    链路字段与继承；``rule_view`` 是防幻觉闸门的事实源（原始规则任务，
    缺省回退基座，单元素路径两者为同一对象）。闸门判据必须读原始规则
    任务——重置后的基座在多元素模式下恒判"无歧义候选"，越权换标的的
    代码会被采信执行，故多元素调用方必须显式回传。
    """
    try:
        raw_confidence = float(payload.get("confidence", 0.5))
        # NaN/Inf 按缺失处理（0.5）：NaN 会击穿一切比较，把"毫无把握"伪装
        # 成"高于确认阈值"跳过确认
        if not math.isfinite(raw_confidence):
            raise ValueError
    except (TypeError, ValueError):
        raw_confidence = 0.5
    confidence = min(LLM_CONFIDENCE_CAP, max(0.0, raw_confidence))

    if payload["intent"] == LLM_FOLLOWUP_LABEL:
        last_intent = context.get(LAST_INTENT_KEY, "")
        intent = (WebIntent(last_intent)
                  if last_intent in ALL_WEB_INTENTS
                  and WebIntent(last_intent) in _EXECUTING_INTENTS
                  else WebIntent.GENERAL_CHAT)
    else:
        intent = WebIntent(payload["intent"])

    # LLM 市场推断仅用于打破跨市场同名歧义（规则市场词已在分类层完成
    # 同样的消歧，能走到这里的歧义说明规则侧无市场证据）
    market = payload.get("market")
    if not isinstance(market, Market):
        market = None

    stocks = list(rule_resolution.stocks)
    sectors = list(rule_resolution.sectors)
    candidates = list(rule_resolution.candidates)
    # 跨组采信闸门的判据是"规则侧是否有歧义候选"——输入属性，不随消
    # 费收缩：市场消解/组内选中清空列表后，后续库内命中的组外代码仍
    # 须拒收（幻觉标的不因先前的合法消解而洗白）；判据读 rule_view，
    # 不随多元素基座重置失明
    gate = rule_view if rule_view is not None else rule_resolution
    had_candidates = bool(gate.candidates)
    # 元素可经库内通道认领的规则侧代码：恒含确定实体（消息中真实出现
    # 的标的，元素认领是分发不是幻觉）；多元素模式（基座已重置，据对
    # 象身份判别）追加歧义候选组成员——单元素模式的候选只走
    # in_candidates 受控通道（含选中组收缩语义），不在此列
    claimable = {s.code for s in gate.stocks}
    if gate is not rule_resolution:
        claimable |= {c.code for c in gate.candidates}
    unverified = list(rule_resolution.unverified_codes)
    # 规则侧坏码名单是硬信号（形态非法/全量库未命中的确定性判定，存在
    # 性不依赖 LLM 回填）：作基底 seed，LLM 回填名经原文闸门去重合并
    # （下游循环的 in unresolved 判重天然衔接）；读 gate 与
    # had_candidates 同源，多元素基座的实体槽已重置
    unresolved = list(gate.unresolved_names)

    # 用 LLM 市场推断打破跨市场同名歧义：无确定实体时候选中恰有一只与
    # 推断市场一致 → 采纳（"美股阿里巴巴"语境下 LLM 回 market=us）
    if market is not None and candidates and not stocks:
        market_filtered = [c for c in candidates if c.market == market.value]
        if len(market_filtered) == 1:
            stocks = market_filtered
            candidates = _drop_resolved_group(
                candidates, market_filtered, rule_resolution.pending_action)

    # stock_code / stock_codes 统一过三道闸门，多标的提及逐个过闸
    extra_codes = payload.get("stock_codes")
    raw_codes = [
        c.strip()
        for c in [payload.get("stock_code"),
                  *(extra_codes if isinstance(extra_codes, list) else [])]
        if isinstance(c, str) and c.strip()
    ]
    seen_codes: set = set()
    for raw in raw_codes:
        # LLM 常按真实世界拼写返回裸 5 位 HK 码（"09988"）：先归一到
        # HK+5 规范身份，与候选匹配/查库/确认轮共用同一代码拼写
        code = _canonical_digit_code(raw.upper())
        if code in seen_codes:
            continue
        seen_codes.add(code)
        in_candidates = [c for c in candidates if c.code == code]
        if in_candidates:
            # LLM 在歧义候选中做了选择：被选中组整体收敛，兄弟组保留交确认
            stocks = _dedup_stocks(stocks + in_candidates)
            candidates = _drop_resolved_group(
                candidates, in_candidates, rule_resolution.pending_action)
        else:
            stock = lookup_stock_by_code(code)
            if stock is not None:
                if not had_candidates or code in claimable:
                    stocks = _dedup_stocks(stocks + [stock])
                else:
                    # 跨组采信闸门：规则侧已有歧义候选时，库内命中但不在
                    # 规则侧标的宇宙（候选组 ∪ 已解析实体）内的代码是越
                    # 权换标的，拒收
                    logger.info(
                        "LLM stock_code %s rejected: outside ambiguity groups",
                        raw)
            else:
                if code.isalpha() or code.upper().startswith("HK"):
                    if code not in unverified:
                        unverified.append(code)
                else:
                    unresolved.append(raw)
                logger.info("LLM stock_code %s rejected: not in stockDB", raw)

    # LLM 报告的无法解析标的名称（"你好股份"类生造名）：过原文闸门后并入
    # unresolved，走既有 stock_unresolved 确认——空标的执行任务是无效产出
    # 原文闸门用小写归一比对（str.lower 逐码点映射保持子串包含，单一
    # 小写比对即覆盖原样命中）
    low_text_llm = str(payload.get("message_text") or "").lower()

    def in_text(name: str) -> bool:
        """原文闸门：LLM 返回的名称（小写归一）出现在消息原文里。"""
        return name.lower() in low_text_llm

    for name in payload.get("unresolved_names") or []:
        if name in unresolved:
            continue
        if in_text(name):
            unresolved.append(name)
        else:
            logger.info("LLM unresolved_name %r rejected: not in message text", name)

    if (unresolved or unverified) and intent == WebIntent.GENERAL_CHAT:
        # LLM 提到股票但判成闲聊且代码不可信：保持闲聊，忽略坏代码
        unresolved = []
        unverified = []

    # LLM 板块名合入（规则侧为基底）：防幻觉闸门"原文出现"；同义去重按
    # 去后缀键——"AI板块"与基底"AI"是同一板块的两种表述
    sector_keys = {sector_dedup_key(s) for s in sectors}
    for name in payload.get("sectors") or []:
        key = sector_dedup_key(name)
        if key in sector_keys:
            continue
        if in_text(name):
            sectors.append(name)
            sector_keys.add(key)
        else:
            logger.info("LLM sector %r rejected: not in message text", name)

    # 以规则结果为基底做 replace 而非手抄字段重建：未指名字段（预挂
    # 歧义组等）自动随行，手抄清单漏字段的漂移从结构上不可能发生
    return replace(
        rule_resolution,
        intent=intent,
        confidence=confidence,
        source="llm",
        stocks=stocks,
        sectors=sectors,
        candidates=candidates,
        unresolved_names=unresolved,
        unverified_codes=unverified,
    )


def _merge_llm_tasks(
    rule_resolution: WebIntentResolution,
    payload: Dict[str, Any],
    context: Dict[str, Any],
) -> List[WebIntentResolution]:
    """LLM 载荷 → 任务列表（合并入口单路径）：单对象载荷视同单元素
    intents 数组，逐项过 ``_merge_llm_result`` 闸门。单元素继承完整规则
    基底（LLM 漏填代码不构成实体丢失）；多元素实体槽重置（逐项继承会把
    全部标的污染进每个任务；继承码随之一并重置，残留会让未填实体的元素
    静默回退会话陈旧标的）——重置只作用于继承槽位，防幻觉闸门的事实源
    经 ``rule_view`` 读原始规则任务，不随重置失明；链路字段
    （source_request/tokens）随行。数组内 followup＝延续前一项意图与
    主体，保序输出。多元素孤儿核算见
    ``_reclaim_orphan_entities``——规则侧实体绝不因协议拆分静默蒸发。
    """
    items = payload.get("intents") or [payload]
    base = rule_resolution if len(items) == 1 else replace(
        rule_resolution,
        stocks=[], candidates=[], sectors=[],
        unresolved_names=[], unverified_codes=[],
        needs_confirmation=False, reason="", pending_action=None,
        multi_intent_hint=False, inherited_stock_code="",
    )
    out: List[WebIntentResolution] = []
    prev_intent_value = ""
    prev_stocks: List[Stock] = []
    prev_sectors: List[str] = []
    for item in items:
        sub = dict(item)
        sub["message_text"] = payload.get("message_text")
        # 数组内 followup＝延续前一项意图与主体：意图经改写 context 复用
        # _merge_llm_result 的转换逻辑；主体槽空时随行补齐前一项对应槽，
        # 追问元素不落成无锚点执行任务
        is_followup = sub.get("intent") == LLM_FOLLOWUP_LABEL
        item_context = ({**context, LAST_INTENT_KEY: prev_intent_value}
                        if is_followup and prev_intent_value else context)
        merged = _merge_llm_result(
            base, sub, item_context, rule_view=rule_resolution)
        if (is_followup and (prev_stocks or prev_sectors)
                and not merged.stocks and not merged.sectors):
            merged = replace(
                merged, stocks=prev_stocks, sectors=prev_sectors)
        prev_stocks, prev_sectors = list(merged.stocks), list(merged.sectors)
        prev_intent_value = merged.intent.value
        out.append(merged)
    if len(items) > 1:
        _reclaim_orphan_entities(out, rule_resolution)
    return out


def _subject_anchor_empty(r: WebIntentResolution) -> bool:
    """六槽主体锚点全空（孤儿回填目标与 finalize 空锚点守卫同口径）。"""
    return not any((r.stocks, r.candidates, r.sectors, r.unresolved_names,
                    r.unverified_codes, r.inherited_stock_code))


def _first_open_executing(out: List[WebIntentResolution]) -> Optional[WebIntentResolution]:
    """首个无 stocks/candidates 的执行类元素（孤儿单目标挂载点）。"""
    return next((t for t in out if t.intent in _EXECUTING_INTENTS
                 and not t.stocks and not t.candidates), None)


def _warn_unclaimed(codes: List[str]) -> None:
    """孤儿主体无挂载目标的显式丢弃告警（宁可显式损失不误挂）。"""
    logger.warning(
        "LLM multi-intent split left rule entities unclaimed with no "
        "empty executing task to attach: %s", ",".join(codes))


def _reclaim_orphan_entities(
    out: List[WebIntentResolution],
    rule_resolution: WebIntentResolution,
) -> None:
    """多元素主体核算（就地）：规则侧主体如何落位到拆分元素。

    单一主体单元（个股/歧义组/板块槽）＝子消息主体，可安全平分给全部
    无主体执行元素——"X的股价和走势"的多元素拆分与逗号展开形同构；
    个股/板块单元被认领后不回填（防同标的重复执行），歧义组例外——
    认领者已解自己那份，无主体元素仍需各自的消歧问答。多主体混合视图
    ＝协议层信息不足（无法确定性分发）：单目标孤儿回收（挂载到首
    个无 stocks/candidates 的执行元素），无目标时显式 warning 丢弃——
    宁可显式损失不误挂；候选挂载时预挂组结构随行（歧义组任一成员被
    认领即整组清账）。unverified 认领按大小写折叠的代码等值（规则侧原
    始拼写 vs 元素侧归一拼写）、恒单目标挂载防重复实查——与
    unresolved_names 的逐元素 seed（澄清请求幂等）刻意不对称。
    """
    rule = rule_resolution
    if not (rule.stocks or rule.candidates
            or rule.unverified_codes or rule.sectors):
        return
    claimed = ({e.code for t in out for e in (*t.stocks, *t.candidates)}
               | {c.upper() for t in out for c in t.unverified_codes})
    groups = [g for g in (rule.pending_action or {}).get("groups") or []
              if isinstance(g, dict)]

    # unverified 单目标回收先行：目标谓词（无 stocks/candidates）与主
    # 体回填互不侵占目标
    orphan_unverified = [c for c in rule.unverified_codes
                         if c.upper() not in claimed]
    if orphan_unverified:
        target = _first_open_executing(out)
        if target is not None:
            target.unverified_codes = list(dict.fromkeys(
                list(target.unverified_codes) + orphan_unverified))
        else:
            _warn_unclaimed(orphan_unverified)

    # 单元计数：个股逐只、候选按预挂组（组边界即歧义问句边界）、板块
    # 逐槽；无主体元素＝六槽全空（与 finalize 的空锚点同口径）
    unit_count = (len(rule.stocks)
                  + ((len(groups) or 1) if rule.candidates else 0)
                  + len(rule.sectors))
    subjectless = [t for t in out
                   if t.intent in _EXECUTING_INTENTS
                   and _subject_anchor_empty(t)]
    if subjectless and unit_count == 1:
        if rule.stocks and rule.stocks[0].code not in claimed:
            for t in subjectless:
                t.stocks = _dedup_stocks(list(t.stocks) + rule.stocks)
        elif rule.candidates:
            for t in subjectless:
                t.candidates = _dedup_stocks(
                    list(t.candidates) + rule.candidates)
                if rule.pending_action:
                    t.pending_action = rule.pending_action
        elif rule.sectors and not any(
                sector_dedup_key(s) == sector_dedup_key(rule.sectors[0])
                for t in out for s in t.sectors):
            for t in subjectless:
                t.sectors = list(dict.fromkeys(
                    list(t.sectors) + rule.sectors[:1]))
        return

    # 多主体混合视图：保守单目标孤儿回收
    group_peers: Dict[str, set] = {}
    for g in groups:
        codes = _group_codes(g)
        for code in codes:
            group_peers.setdefault(code, set()).update(codes)

    def _orphaned(entity: Stock) -> bool:
        peers = group_peers.get(entity.code, set())
        return not (entity.code in claimed or peers & claimed)

    orphan_stocks = [s for s in rule.stocks if _orphaned(s)]
    orphan_candidates = [c for c in rule.candidates if _orphaned(c)]
    if not orphan_stocks and not orphan_candidates:
        return
    target = _first_open_executing(out)
    if target is None:
        _warn_unclaimed(
            [e.code for e in (*orphan_stocks, *orphan_candidates)])
        return
    if orphan_stocks:
        target.stocks = _dedup_stocks(list(target.stocks) + orphan_stocks)
    if orphan_candidates:
        target.candidates = _dedup_stocks(
            list(target.candidates) + orphan_candidates)
        if rule.pending_action:
            target.pending_action = rule.pending_action


def _pending_skeleton(
    resolution: WebIntentResolution,
    sub_text: str,
    groups: List[Dict[str, Any]],
    unresolved_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """确认动作 pending_action 构造骨架：action/intent/groups/
    original_request + resolved_stocks（原请求已解析实体，消费轮合并回
    stocks，比较语义不丢）+ 可选 unresolved_names。"""
    pending: Dict[str, Any] = {
        "action": "confirm_stock",
        "intent": resolution.intent.value,
        "groups": groups,
        "original_request": sub_text,
    }
    if resolution.stocks:
        pending["resolved_stocks"] = [_stock_payload(s) for s in resolution.stocks]
    if unresolved_names:
        pending["unresolved_names"] = unresolved_names
    return pending


def _mark_confirm(r: WebIntentResolution, reason: str) -> None:
    """置确认标志（needs_confirmation + reason）——各收口分支的公共落点。"""
    r.needs_confirmation = True
    r.reason = reason


def _finalize_confirmations(
    resolutions: List[WebIntentResolution],
) -> List[WebIntentResolution]:
    """第六步②组级入口：一条子消息（组）全部任务的确认判定。歧义组优先
    消费第四步预挂的 pending_action.groups，无预挂按 candidates 兜底建组；
    仅执行类意图需要确认（三/四类 reason 见模块 docstring）。

    集合提供者（组内存在 portfolio_analysis）是组级事实：空主体锚点的
    执行类任务主体＝提供者的账户标的集合输出（任务间主体引用），无锚点
    守卫与低置信守卫对其豁免——对空实体动作元素转无选项确认会死锁（用户
    重说同一句原样重入管道，任何回复无法消解）。执行端契约：空实体执行
    任务绑定同组组合任务的输出，不得做"沿用上一只股票"之类兜底。
    """
    has_provider = any(
        r.intent is WebIntent.PORTFOLIO_ANALYSIS for r in resolutions)

    def _finalize(resolution: WebIntentResolution) -> WebIntentResolution:
        resolution.confidence = max(0.0, min(1.0, resolution.confidence))
        sub_text = resolution.source_request or "".join(resolution.tokens)
        if resolution.intent not in _EXECUTING_INTENTS:
            # 有意图信号但对象未解的闲聊候选（"分析…哈喽板块"）是实义
            # 请求黑洞，转澄清确认；完全无信号的寒暄（"你好呀"）放行
            if (resolution.source == "llm_failed"
                    and INTENT_WORD_RE.search(sub_text)
                    and resolution.confidence < CONFIRMATION_CONFIDENCE_THRESHOLD):
                _mark_confirm(resolution, "low_confidence")
            return resolution

        # 无锚点执行类守卫：执行类任务缺一切主体锚点时转低置信澄清——
        # followup 意图提升与多意图拆分的未填实体元素在此单点收口；
        # 组内存在集合提供者时豁免（空实体任务主体＝其输出，转无选项
        # 确认会让用户任何回复都无法消解）
        empty_anchor = _subject_anchor_empty(resolution)
        if (resolution.intent != WebIntent.PORTFOLIO_ANALYSIS
                and empty_anchor and not has_provider):
            _mark_confirm(resolution, "low_confidence")
            resolution.pending_action = None
            return resolution

        if resolution.candidates:
            _mark_confirm(resolution, "ambiguous_stock_name")
            # 权威结构 groups：优先消费第四步预挂的组（已被 LLM 消解的组
            # 其候选不在 candidates 中，随之过滤），无预挂按候选兜底
            cand_codes = {c.code for c in resolution.candidates}
            groups = [
                g for g in (resolution.pending_action or {}).get("groups", [])
                if isinstance(g, dict) and (_group_codes(g) & cand_codes)
            ] or [
                _group_payload(
                    resolution.candidates[0].name or resolution.candidates[0].code,
                    resolution.candidates, resolution.intent.value, sub_text)
            ]
            # 原请求中已解析的确定实体随 pending 保留（消费轮合并回 stocks）
            resolution.pending_action = _pending_skeleton(
                resolution, sub_text, groups,
                unresolved_names=list(resolution.unresolved_names) or None)
            return resolution

        if resolution.unresolved_names:
            _mark_confirm(resolution, "stock_unresolved")
            # groups 为空：无歧义候选，等待用户重新提供名称/代码
            resolution.pending_action = _pending_skeleton(
                resolution, sub_text, [],
                unresolved_names=list(resolution.unresolved_names))
            return resolution

        if (resolution.confidence < CONFIRMATION_CONFIDENCE_THRESHOLD
                and not (has_provider and empty_anchor)):
            # low_confidence 不产生 pending_action（意图待澄清而非选标的），
            # 预挂载体一并撤下——残留组会被 apply_pending 写回，弹出误导性
            # 选股确认；提供者在场的空实体任务不走此出口（转无选项确认同
            # 样会死锁）
            _mark_confirm(resolution, "low_confidence")
            resolution.pending_action = None
        elif resolution.pending_action and not resolution.needs_confirmation:
            # 预挂组已随 LLM 消歧/市场收窄清空候选：撤下预挂载体
            resolution.pending_action = None
        return resolution

    return [_finalize(r) for r in resolutions]


def _finalize_confirmation(
    resolution: WebIntentResolution,
) -> WebIntentResolution:
    """第六步②的单任务便捷入口（无组上下文＝无提供者，守卫原口径）。"""
    return _finalize_confirmations([resolution])[0]


# =========================================================================
# 主类 — 六步流水线宿主（类内方法即执行序：构造/LLM/收尾/主入口）
# =========================================================================


class WebIntentResolver:
    """Web Chat 意图识别器：token 序列 → 二维任务组列表（组=子消息）。

    LLM adapter 惰性构建（litellm provider 栈加载昂贵）：首次真正触发
    兜底的 resolve 才构建，失败永久禁用（兜底退化为低置信转确认），
    构建受锁保护可全局复用。config 与 llm_adapter 均省略则禁用兜底。
    """

    # request_context 中当前股票（#1619 股票范围机制）的读取键
    CURRENT_STOCK_CODE_KEY = "current_stock_code"

    def __init__(
        self,
        config: Optional[Any] = None,
        *,
        llm_adapter: Optional[Any] = None,
        llm_timeout: float = 45.0,
    ) -> None:
        """config 传入即启用 LLM 兜底（adapter 惰性构建，失败永久禁用）；
        llm_adapter 直接注入则跳过构建（测试/复用场景）。"""
        self._config = config
        self._llm_adapter = llm_adapter
        self._llm_timeout = llm_timeout
        self._llm_init_failed = False
        self._llm_init_lock = threading.Lock()

    # ------------------------------------------------------------------
    # LLM 兜底（第六步①）
    # ------------------------------------------------------------------

    def _ensure_llm_adapter(self) -> Optional[Any]:
        """返回可用的 LLM adapter；从 config 按需构建（首次兜底才
        import，litellm 栈加载昂贵），失败置 ``_llm_init_failed`` 永久
        禁用——初始化问题不击穿解析主链路。
        """
        if self._llm_adapter is not None or self._llm_init_failed:
            return self._llm_adapter
        with self._llm_init_lock:
            if (self._llm_adapter is None
                    and not self._llm_init_failed
                    and self._config is not None):
                from src.agent.llm_adapter import LLMToolAdapter

                try:
                    self._llm_adapter = LLMToolAdapter(self._config)
                except Exception as exc:  # noqa: BLE001 — 初始化失败不该击穿意图层
                    logger.warning(
                        "web intent LLM fallback disabled (adapter init failed): %s",
                        exc,
                    )
                    self._llm_init_failed = True
        return self._llm_adapter

    def _should_use_llm(
        self, resolution: WebIntentResolution,
    ) -> bool:
        """LLM 兜底触发条件（宁可不做不可做错：默认复核，豁免需三证
        齐全；adapter 不可用时恒 False——规则结果是唯一防线）。

        豁免三证（缺一即复核）：
          ① 视野完备——``all_tags_recognized``（未读内容可能藏着主体/
             附加诉求，不得静默丢弃）；
          ② 判定可靠——置信度 ≥ ``_CONFIDENCE_LLM_EXEMPT``（0.8：关键词
             共现 0.85 / 显式代码 0.9 达标；继承 0.75 不达标）；
          ③ 表达完备——无 multi_intent_hint：数据对象词 × 强分析/组合类
             同场（"多少钱＋基本面"＝一句两个深度）交 LLM 判定拆分还是
             单一。
        继承产物主体在场同享豁免（继承机制确定性；歧义候选同为主体
        在场——消歧是用户确认事务）。纯确认碎片（source="confirmation"）
        与 hk/us 存疑代码永不触发。
        """
        if resolution.source == "confirmation":
            return False
        # 继承产物主体在场同享豁免（继承机制确定性，0.75 是路径标签非
        # 疑义信号；歧义候选同为主体在场——消歧是用户确认事务；空主体
        # 继承无锚点，仍复核）
        subject_backed = (resolution.source == "context" and bool(
            resolution.stocks or resolution.sectors
            or resolution.candidates or resolution.inherited_stock_code))
        if (resolution.all_tags_recognized
                and not resolution.multi_intent_hint
                and (resolution.confidence >= _CONFIDENCE_LLM_EXEMPT
                     or subject_backed)):
            return False
        return self._ensure_llm_adapter() is not None

    def _classify_with_llm(
        self,
        resolution: WebIntentResolution,
        context: Dict[str, Any],
    ) -> Optional[List[WebIntentResolution]]:
        """调用 LLM 做意图分类并合并结果（多意图协议下为任务列表，保
        序）；任何失败返回 None（用规则结果，由收尾链标记
        source="llm_failed"）。失败面全覆盖：adapter 异常、超时、error
        provider、非 JSON 回复、非法 intent——宁可退回规则低置信（转
        确认）也不被坏输出污染。
        """
        adapter = self._ensure_llm_adapter()
        if adapter is None:
            return None
        # is_available 在真实适配器上是 property（返回 bool），兼容方法
        # 形态两种接口；不可用（如未配 API key）时跳过调用
        available = getattr(adapter, "is_available", True)
        if callable(available):
            available = available()
        if not available:
            logger.info("web intent LLM fallback skipped: adapter unavailable")
            return None
        text = resolution.source_request or "".join(resolution.tokens)
        recent = context.get(RECENT_STOCKS_KEY) or []
        # 继承码随 prompt 下发为 current_stock：无自身标的的片段（"和市盈
        # 率"）只有拿到 current_stock 才能判回执行类意图
        current_stock = None
        if resolution.inherited_stock_code:
            stock = lookup_stock_by_code(resolution.inherited_stock_code)
            current_stock = (_stock_payload(stock) if stock is not None
                             else {"code": resolution.inherited_stock_code})
        request_body = {
            "message": text,
            "current_stock": current_stock,
            "resolved_stocks": [_stock_payload(s) for s in resolution.stocks],
            "ambiguous_candidates": [_stock_payload(c)
                                     for c in resolution.candidates],
            "unresolved_codes": list(resolution.unresolved_names),
            # 读点归一：不可序列化元素（set/对象）会让 json.dumps 在 try
            # 外以 TypeError 击穿，只透传字符串元素
            "recent_stocks": ([c for c in recent if isinstance(c, str)]
                              if isinstance(recent, list) else []),
            "last_intent": context.get(LAST_INTENT_KEY, ""),
        }
        messages = [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(request_body, ensure_ascii=False)},
        ]
        try:
            # max_tokens=5000：思考型模型（deepseek 系）思考 token 与正文
            # 共享预算，200 会被思考烧光、正文恒空 → 兜底确定性失败
            response = adapter.call_text(
                messages, temperature=0.0, max_tokens=5000,
                timeout=self._llm_timeout)
        except Exception as exc:  # noqa: BLE001 — LLM 栈任意异常都不该击穿意图层
            logger.warning("web intent LLM fallback failed: %s", exc)
            return None
        if response is None or getattr(response, "provider", "") == "error":
            return None
        payload = _parse_llm_payload(getattr(response, "content", None) or "")
        if payload is None:
            logger.warning("web intent LLM returned unparseable payload")
            return None
        # 原文随载荷传递：merge 侧用它对 LLM 返回的板块名做原文出现校验
        payload["message_text"] = text
        return _merge_llm_tasks(resolution, payload, context)

    # ------------------------------------------------------------------
    # 第六步 — 幸存任务收尾
    # ------------------------------------------------------------------

    @staticmethod
    def _group_base(group: List[WebIntentResolution],
                    ) -> WebIntentResolution:
        """组视图并集基底：链路字段全组同源（同一子消息），取首任务
        即取代表（无主次语义）；实体槽按任务对象归属分布在各组员上，
        并集才是该子消息的完整规则视野。"""
        first = group[0]
        if len(group) == 1:
            return first
        return replace(
            first,
            stocks=_dedup_stocks(s for r in group for s in r.stocks),
            candidates=_dedup_stocks(c for r in group for c in r.candidates),
            sectors=list(dict.fromkeys(x for r in group for x in r.sectors)),
            unresolved_names=list(dict.fromkeys(
                x for r in group for x in r.unresolved_names)),
            unverified_codes=list(dict.fromkeys(
                x for r in group for x in r.unverified_codes)),
        )

    def _finalize_task(
        self,
        group: List[WebIntentResolution],
        context: Dict[str, Any],
    ) -> List[WebIntentResolution]:
        """一条子消息（组）的收尾——sub_message 是收尾的最小单位：
        ① 组级复核：组内任一任务触发 → 以组视图并集为基底发起一次 LLM
        调用，产出即该子消息的全部任务，【整组替换】（一条子消息至多
        一次多意图枚举）；失败退回规则任务逐任务收尾并标 llm_failed；
        ② 逐任务确认判定补齐（``_finalize_confirmations``）与日志。
        """
        resolutions = list(group)
        if any(self._should_use_llm(r) for r in group):
            llm_tasks = self._classify_with_llm(
                self._group_base(group), context)
            if llm_tasks:
                resolutions = llm_tasks
            else:
                # 复核调用失败：整组退回规则判定，source 标记区分"未调"
                # 的 rule（组内成员同属这次失败复核）
                for r in group:
                    r.source = "llm_failed"

        out = _finalize_confirmations(resolutions)
        for r in out:
            _log_resolution(r.source, r)
        return out

    # ------------------------------------------------------------------
    # 主入口 — 六步流水线
    # ------------------------------------------------------------------

    def resolve(
        self,
        message: str,
        session_context: Any = None,
        request_context: Any = None,
    ) -> List[List[WebIntentResolution]]:
        """解析一条用户消息，返回**二维任务组列表**（按用户表达顺序保
        序）。

        外层 = 子消息任务组（一条消费型标点/顺序连接词切开的一段），
        组内是平权任务（主体任务＋未被消费的板块/指数/组合兄弟任务）；
        单意图消息同样是双层结构 ``[[task]]``。确认状态在需确认任务自
        身：任一组的任一任务 ``needs_confirmation=True`` 即
        整条消息短路（消费方 ``any()`` 判断），链式确认的 confirmed
        寄生在该任务的 ``pending_action`` 上。
        session_context 提供 recent_stocks / pending_actions / last_intent；
        request_context 提供 ``current_stock_code``（#1619）
        """
        # ---- 第一步：上下文准备与空输入短路 ----
        context = _session_context(session_context)
        request = _session_context(request_context)
        recent = context.get(RECENT_STOCKS_KEY) or []
        # 会话形状异常不击穿（与写侧 apply_outcome 的 str 过滤同口径）：
        # 继承码来源值非文本按缺失处理，不带病流入查库/LLM 兜底路径
        raw_current = request.get(self.CURRENT_STOCK_CODE_KEY, "")
        current_stock_code = raw_current if isinstance(raw_current, str) else ""
        first_recent = (recent[0] if isinstance(recent, list) and recent
                        and isinstance(recent[0], str) else "")
        inherited_stock_code = current_stock_code or first_recent
        # 确认存活的唯一权威是 pending_actions（clear_pending_actions 的
        # 清理协议只作用于它）；last_resolutions 是消费载荷投影——开关
        # 关闭时陈旧投影不得被消费（Agent 失败收尾后旧确认链立即失效）
        pending_gate = _pending_confirming_tasks(context)
        last_resolution = (context.get(LAST_RESOLUTIONS_KEY) or pending_gate
                           ) if pending_gate else []

        if not isinstance(message, str) or not message.strip():
            # 空/非文本：闲聊直达（带继承股票；空消息不清 pending——
            # 它不是确认响应，pending 留待真正回复时消费）
            empty = WebIntentResolution(
                intent=WebIntent.GENERAL_CHAT,
                confidence=_CONFIDENCE_FALLBACK,
                source="rule",
                inherited_stock_code=inherited_stock_code,
            )
            _log_resolution("rule", empty)
            return [[empty]]  # 一律二维

        # ---- 第二步：全消息分词（_preprocess_text / _identify_stock_codes
        #      全局仅此一次，后续各阶段只消费这份 tokens）----
        _, tokens = _preprocess_text(message)
        tokens = _identify_stock_codes(tokens)

        # ---- 第三步：消息级多任务切分（tokens 二维）----
        sub_token_lists = _split_sub_messages(tokens, message)

        # ---- 第四步：逐子消息规则级解析（多意图任务列表；LLM 延后不跑）----
        full_resolution: List[List[WebIntentResolution]] = []
        prev_intent = context.get(LAST_INTENT_KEY, "")
        prev_subject: Optional[_ChainSubject] = _session_chain_subject(context)
        for i, sub_tokens in enumerate(sub_token_lists):
            chain_code = inherited_stock_code if i == 0 else (
                prev_subject[0][0].code if len(prev_subject[0]) == 1 else "")
            tasks = _classify_rule(
                sub_tokens,
                prev_intent,
                chain_code,
                prev_subject,)
            full_resolution.append(tasks)
            verdict = tasks[0]
            prev_intent = verdict.intent.value   # 继承意图＝上组主体任务意图
            prev_ambiguous = [
                (str(g.get("name") or ""),
                 [s for s in map(_stock_from_payload, g.get("candidates", []))
                  if s])
                for g in (verdict.pending_action or {}).get("groups", [])
                if isinstance(g, dict)
            ]
            prev_subject = (list(verdict.stocks), list(verdict.sectors),
                            prev_ambiguous)

        # ---- 第五步：确认消费（pending 存在时优先判定本轮是否为确认响应）----
        if _is_pending_action(last_resolution):  # 有歧义需要消歧
            reply_tasks = [t for g in full_resolution for t in g]
            full_resolution = _consume_confirmations(last_resolution, full_resolution)
            this_round = {id(t) for t in reply_tasks}
            return [
                self._finalize_task(group, context)
                if group and all(id(t) in this_round for t in group)
                else group
                for group in _as_task_groups(full_resolution)
            ]

        # ---- 第六步：逐幸存任务收尾（LLM 兜底 → 确认判定）----
        # ---- 确认收口（判定权在消费方）----
        # 不做同意图折叠：多标的任务各自独立执行、各自锁定 stock scope，
        # 聚合不改变 Agent 输出质量；任一任务待确认即整链短路（消费方
        # any() 判定），确认任务与其余任务随组结构写入 last_resolutions
        return [self._finalize_task(group, context) for group in full_resolution]

    def resolve_first(
        self,
        message: str,
        session_context: Any = None,
        request_context: Any = None,
    ) -> WebIntentResolution:
        """单任务便捷视图：二维任务列表的首组首任务（首子消息首个任务）。"""
        return self.resolve(message, session_context, request_context)[0][0]


# =========================================================================
# 会话簿记 — resolve 之后的出口写回（pending 结算 / recent / last_intent）
# =========================================================================


def _writable_context(session: Any) -> Optional[Dict[str, Any]]:
    """簿记目标 dict：None session / 无 context 对象返回 None（no-op）。
    空 dict 会话与空 .context 同为有效目标——宿主可能挂 update_context
    持久化钩子，真值判断会误伤（getattr(None) 得 None，免显式判空）。"""
    if isinstance(session, dict):
        return session
    context = getattr(session, "context", None)
    return context if isinstance(context, dict) else None


def _write_context(
    session: Any, context: Dict[str, Any], key: str, value: Any
) -> None:
    """写会话键：宿主对象提供 ``update_context``（ConversationSession 的
    簿记入口，可能带持久化钩子）时走它，否则直接写 context dict。"""
    updater = getattr(session, "update_context", None)
    if callable(updater):
        updater(key, value)
    else:
        context[key] = value


def apply_pending(
    session: Any,
    tasks: "Union[WebIntentResolution, List[WebIntentResolution],"
           " List[List[WebIntentResolution]]]",
) -> None:
    """resolve 边界同步调用：写/清 pending_actions（消费即结算，替换式
    ——确认任务存在则写其 pending_action，否则清空，旧 pending 绝不跨轮
    残留）。必须在 SSE 层发出 action_required 之前完成，否则用户下一条
    回复会先于 pending 落库、被当成新消息解析；空输入轮由调用方跳过
    （空消息不得清 pending）。确认任务扫描全部组全部位置——多意图消息
    的确认任务可以不在首组，只看首位会把 pending 写丢。入参以 resolve
    的二维产出为主形态（兼容一维任务列表/单个 resolution，经
    ``_iter_tasks`` 展平——组结构不影响本函数，扫描本就按全部位置）。
    """
    task_list = list(_iter_tasks(tasks))
    context = _writable_context(session)
    if context is None:
        return
    confirming = next(
        (t for t in task_list if _has_pending_action(t)), None)
    _write_context(session, context, PENDING_ACTIONS_KEY,
                   [confirming.pending_action] if confirming else [])


def apply_outcome(
    session: Any,
    executed_tasks: "Union[WebIntentResolution, List[WebIntentResolution],"
                    " List[List[WebIntentResolution]]]",
) -> None:
    """任务执行完成后调用：recent_stocks 头插去重截断（候选/未解析标的
    不入列）+ last_intent（落点＝最后一个执行类组的组首，与头插"后写胜
    出"同源；无执行类组退末位）。只记真正执行的任务——短路轮不写，
    未执行的 stocks/意图不得污染继承上下文。入参以执行端实际执行的
    resolve 原始二维形态为主（组结构是落点判定的输入，展平即丢）；
    兼容一维任务列表/单个 resolution。
    """
    task_list = list(_iter_tasks(executed_tasks))
    context = _writable_context(session)
    if context is None:
        return
    recent = [c for c in context.get(RECENT_STOCKS_KEY) or [] if isinstance(c, str)]
    for code in [s.code for t in task_list for s in t.stocks if s.code]:
        if code in recent:
            recent.remove(code)
        recent.insert(0, code)
    _write_context(session, context, RECENT_STOCKS_KEY, recent[:MAX_RECENT_STOCKS])
    if task_list:
        # last_intent＝对话落点（最后一个执行类主体任务的组首），与 recent_stocks 头插"后写胜出"同源；无执行类组退末位（纯闲聊轮）
        landing = next((g[0] for g in reversed(_as_task_groups(executed_tasks))
                        if g and g[0].intent in _EXECUTING_INTENTS),
                       task_list[-1])
        _write_context(session, context, LAST_INTENT_KEY, landing.intent.value)


def apply_resolution_to_session(
    session: Any,
    resolution: "Union[WebIntentResolution, List[WebIntentResolution],"
                " List[List[WebIntentResolution]]]",
) -> None:
    """把一次解析结果写入会话上下文（组合入口 = apply_pending +
    apply_outcome）。入参以 resolve 的二维任务组产出为主形态
    （兼容一维任务列表/单个 resolution，经 ``_iter_tasks`` 展平），
    确认任务可位于任意组任意位置。短路轮（存在任一 needs_confirmation
    任务）整链未执行：只结算 pending，recent_stocks / last_intent 不写；
    last_resolutions 每轮二维投影——第五步确认消费的数据源，上轮歧义
    任务的 pending_action 必须跨轮可见。
    """
    tasks = list(_iter_tasks(resolution))
    short_circuited = any(t.needs_confirmation for t in tasks)
    apply_pending(session, tasks)
    # 传原始（二维）结构：组结构是 last_intent 落点判定的输入，展平即丢
    apply_outcome(session, [] if short_circuited else resolution)
    # last_resolutions 每轮写（含短路轮，信息不缺失）：二维组结构原样
    # 投影——第五步确认消费的数据源，上轮歧义任务的 pending_action
    # 必须跨轮可见；分组信息（子消息边界）随链路保留
    if (ctx := _writable_context(session)) is not None:
        two_dim = _as_task_groups(resolution) or [tasks]
        _write_context(session, ctx, LAST_RESOLUTIONS_KEY,
                       [[asdict(t) for t in g] for g in two_dim])


def clear_pending_actions(session: Any) -> None:
    """清空待确认动作（Agent 失败路径的显式收尾；正常轮由 apply 替换）。
    pending_actions 是确认存活的唯一权威：清空即旧确认链失效（消费
    闸门关闭，陈旧 last_resolutions 投影惰性化，下轮写侧覆写自愈）。"""
    if (context := _writable_context(session)) is not None:
        _write_context(session, context, PENDING_ACTIONS_KEY, [])
