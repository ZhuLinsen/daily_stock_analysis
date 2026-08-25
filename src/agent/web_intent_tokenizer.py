# -*- coding: utf-8 -*-
"""
Web Chat 意图识别层 — 六步分词管道（Intent Tokenizer）。

把一条用户消息切分为携带语义标签的 ``Token`` 序列，供
``web_intent_resolver.WebIntentResolver`` 做规则分类；本模块不做任何
意图判定，只负责"识别出消息里有什么"。

== 六步管道（_preprocess_text，按执行顺序）==
  Step 1   多股票实体扫描（仅全名精确匹配，8~2 字窗口，含改名旧称；入口
           extend_AkShare 把 AkShare 全量并入 stockDB——扩展点钉死在全
           管道最前）
  Step 2   特殊标点与空白切分（排除 * - .，可能出现在股票名/代码中；仅
           作用于 Step 1 的 gap）
  Step 3   代码形字符串提取（unknown_code；任意位裸数字 → unknown_number）
  Step 4   市场关键词提取（含"股"+"份"消歧）
  Step 5   无歧义关键词分词（clean 词池）
  Step 6   残存 gap 多策略匹配（关键词/精确/子串/拼音/模糊 DFS）

== 核心原则 ==
宁可不做，不可做错，放弃一切低置信度的匹配。Step 1-5 只做精确匹配；
Step 6 混合匹配但要求整段 TAG 全覆盖（交叉验证）才产出，任一片段无 tag
则整体原样返回，交下游 LLM 兜底。

== 关键不变量 ==
  - 实体扫描（Step 1）先于一切切分类步骤：全名一旦被撕裂即无法复原，
    含代码形/关键词子串的全名（"TCL科技"/"恒生电子"）必须先被整名消费。
    AkShare 扩展因此钉死在管道最前，Steps 1~6 自始面对同一合并后库视图。
  - 输入侧 NFKC 宽度归一 + 窗口匹配时删去输入端空格："贵 州 茅 台" 与
    常规书写同样整名命中（库侧源数据归一属 resolver 层，后续 PR 引入）。
  - token 层代码身份的规范拼写单一定义点 ``_canonical_stock_code``（a=6
    位裸数字、hk=HK+5 位、us=大写 ticker）：名称路径与代码路径共享同一
    拼写，下游从其它来源（LLM 输出/session 继承）构造 stocks 时必须复用，
    否则同一股票出现多重代码身份。
  - sector 系三标签词池见 web_intent_types（泛称/行业名/行业兼股票名），
    全管道不做个股名匹配；行业名+泛称相邻为高置信度板块组合。

unknown_code 由 ``_identify_stock_codes`` 辨认：库命中 → stock_code（附
三元组）；形态非法或该市场库全量未命中 → wrong_{market}_code；库非全量
未命中 → unknown_{market}_code（存疑交下游 LLM）。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from src.agent.stock_scope import extract_stock_codes  # 代码格式校验（不查库）
from src.agent.web_intent_types import (
    Market,
    TAG_FILLER,
    TAG_SECTOR,
    TAG_SECTOR_NAME,
    TAG_SECTOR_N_STOCK,
    TAG_STOCK_CODE,
    TAG_STOCK_NAME,
    TAG_SUBJECT_INDEX,
    TAG_SUBJECT_MARKET,
    TAG_SUBJECT_MARKET_BROAD,
    TAG_UNKNOWN_CODE,
    TAG_UNKNOWN_NUMBER,
    Token,
    _ASCII_KEYWORD_UPPER,
    _CLEAN_KEYWORDS_PATTERN,
    _DIGIT_KEYWORDS_RE,
    _HAS_CONTENT_PATTERN,
    _KW_TO_MARKET,
    _SPECIAL_PUNCT_RE,
    _TAG_KEYWORD_LISTS_EXTEND,
    _classify_keyword,
    _compile_kw_pattern,
    unknown_code_tag,
    wrong_code_tag,
)
from src.services.name_to_code_resolver import (
    Stock,  # (code/name/market)
    US_stock_code_match,  # 美股代码匹配
    _db_lock,  # stockDB 读锁：与下游 extend_AkShare 的并发合并串行
    extend_AkShare,  # Step 1 入口调用：合并 AkShare 全量进 stockDB（幂等）
    is_known_stock_name,  # 本地名称表成员判定（不联网）
    is_market_db_complete,  # 市场库全量判定（wrong/unknown 细分依据）
    lookup_stock_by_code,  # 代码查库（stock_code 三元组来源）
    resolver_name_to_code_list,
    stockAliases,  # 改名旧称（code→{旧名}）：实体索引与 resolver 口径对齐
    stockDB,  # 全局名称库（code→name，可被 AkShare 原地扩充）
)
from src.services.stock_code_utils import (  # 交易所推断权威实现（无 agent 反向依赖）
    _infer_cn_exchange,
)


def _extract_markets_from_tokens(tokens: List[Token]) -> List[Market]:
    """从 token 提取市场枚举（唯一提取点）：TAG_SUBJECT_MARKET → _KW_TO_MARKET，
    另识别 ASCII 简写 "us"/"hk"。消歧已在 _split_market_tokens 完成，此处仅映射。

    小写简写仅在消息含 CJK 时生效：纯英文消息里独立的小写 "us" 几乎总是
    代词；大写 US/HK 是刻意形态，不受语境限制。"""
    has_cjk = any("\u3400" <= ch <= "\u9fff" for t in tokens for ch in t.text)
    markets: List[Market] = []
    seen: set = set()
    for t in tokens:
        if t.tag == TAG_SUBJECT_MARKET:
            mkt = _KW_TO_MARKET.get(t.text.lower())
            if mkt and mkt not in seen:
                markets.append(mkt)
                seen.add(mkt)
        else:
            stripped = t.text.strip()
            shorthand = stripped.lower()
            if shorthand in ("us", "hk") and (has_cjk or shorthand != stripped):
                mkt = Market(shorthand)
                if mkt not in seen:
                    markets.append(mkt)
                    seen.add(mkt)
    return markets


def _recognition_rate(tokens: List[Token]) -> float:
    """已打标签 token 占全部 token 的比例，低则升级 LLM 兜底。"""
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if t.tag) / len(tokens)


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


def _canonical_stock_code(code: str, market: str) -> str:
    """token 层股票代码的规范拼写：hk → HK+5 位，a/us 保持 stockDB 键原样
    （6 位裸数字 / 大写 ticker）。名称路径产出的唯一归一点——不归一会与
    代码路径形成同一股票的双重身份。"""
    if market == "hk" and code.isdigit():
        return f"HK{code}"
    return code


def _canonical_stocks(stocks: List[Stock]) -> List[Stock]:
    """批量套用 _canonical_stock_code（Stock 为 frozen，需重建）。"""
    return [
        Stock(code=_canonical_stock_code(s.code, s.market), name=s.name, market=s.market)
        for s in stocks
    ]


# =========================================================================
# Step 1 — 多股票实体扫描（仅全名精确匹配，管道首步）
# =========================================================================

def _build_entity_index() -> Tuple[List[str], Dict[str, List[Tuple[str, str, str]]]]:
    """构建实体扫描索引：全名列表 + 名称 → [(code, market, 规范名)]。

    含 stockAliases 改名旧称（与 resolver 口径对齐），别名命中同样展示当前
    规范名。每消息重建一次（stockDB 可能被 AkShare 扩充改变，不能跨消息
    缓存）；只读当时的 stockDB，绝不主动发起扩展。
    """
    names: List[str] = []
    name_codes: Dict[str, List[Tuple[str, str, str]]] = {}
    # 持锁迭代：与并发请求的 extend_AkShare 原地合并串行，防 dict 迭代崩溃
    with _db_lock:
        for code, name in stockDB.items():
            if not name or not code:
                continue
            if name not in name_codes:
                names.append(name)
                name_codes[name] = []
            market = _market_of_code(code)
            if market:
                name_codes[name].append((code, market, name))
        for code, aliases in stockAliases.items():
            market = _market_of_code(code)
            canonical = stockDB.get(code) or ""
            for alias in aliases:
                if not alias:
                    continue
                if alias not in name_codes:
                    names.append(alias)
                    name_codes[alias] = []
                entry = (code, market, canonical or alias)
                if market and entry not in name_codes[alias]:
                    name_codes[alias].append(entry)
    return names, name_codes


# 实体扫描压缩长度上限：按删空格后计，与库内最长全名取小、封顶 8（9 字
# 以上 CJK 股名不存在，超长指称交 Step 6/下游 LLM）；下探到 2 字（美团/
# 快手 等港股短名）——窗口必须整体等于全名，误切风险有界
_MAX_ENTITY_LEN = 8

# sector 系词池并集：与股票名冲突时行业语义优先，全管道不做个股名匹配。
# 含恰为库中全名的词（"机器人"=300024）——Step 1 放行，交 Step 6 打 tag
_SECTOR_KEYWORD_SET = frozenset(
    kw
    for tag in (TAG_SECTOR, TAG_SECTOR_NAME, TAG_SECTOR_N_STOCK)
    for kw in _TAG_KEYWORD_LISTS_EXTEND.get(tag, [])
)

# ST 风险警示前缀（"ST德豪"/"*ST美丽"/"ST*美丽"）：前缀三型互认，AB 汉字
# 部分必须等于库中全名；Step 3 放行其 ASCII 前缀不作代码候选（见 _split_by_codes）
_ST_PREFIX_RE = re.compile(r"^(\*ST|ST\*|ST)([\u3400-\u9fff]+)$")


def _st_prefix_variants(name: str) -> set:
    """ST 前缀三型等价拼写集合：STAB / *STAB / ST*AB 互认（前缀后须为
    CJK，排除 "STO" 等普通英文词）；非该形态返回 {name} 自身。"""
    m = _ST_PREFIX_RE.match(name)
    if not m:
        return {name}
    tail = m.group(2)
    return {f"ST{tail}", f"*ST{tail}", f"ST*{tail}"}


def _split_by_stock_entities(text: str) -> List[Token]:
    """Step 1 子函数（管道首步）：多股票实体扫描（仅全名精确匹配，最长优先、
    非重叠）。

    入口先把空白（含 tab/换行）收敛为单空格，随后逐位置尝试"最宽跨度 ~ 2
    字"窗口（收敛后 max_len 字全名最宽占 2*max_len-1 个 raw 字符，跨度上界
    静态完备）；窗口删空格后必须整体等于库中全名（含改名旧称），禁止
    子串/拼音/模糊（"贵 州 茅 台"/"中 国 海 洋 石 油"→整名命中）。
    全名恰为枚举行业词（"机器人"）时放行交 Step 6
    打 sector；缩写（"茅台"）非全名，交 Step 6 多策略匹配承接。唯一命中
    → TAG_STOCK_NAME 确定实体；跨市场同名多只（"阿里巴巴"）→ 携带多候选
    交下游歧义确认。未命中片段保留为空 tag token 交后续步骤。
    """
    if not text:
        return []
    # 空白（含 tab/换行）收敛为单空格：收敛后 max_len 字全名最宽占
    # 2*max_len-1 个 raw 字符，窗口跨度上界得以静态封顶；亦统一本步
    # 删 ' ' 与 Step 2 按空白切分的两套口径（tab 分隔指称同样可命中）。
    # gap 文本随之规整——空白本就被后续步骤切分与过滤，无信息损失
    text = re.sub(r"\s+", " ", text)
    if not any("\u3400" <= ch <= "\u9fff" for ch in text):
        return [Token(text)]  # 纯英文段由 Step 6 DFS（拼音/美股代码）兜底
    names, name_codes = _build_entity_index()
    max_len = min(_MAX_ENTITY_LEN, max((len(n) for n in names), default=0))
    max_span = 2 * max_len - 1  # 收敛后最长全名的最宽 raw 跨度（静态完备）
    tokens: List[Token] = []
    i, gap_start, n = 0, 0, len(text)
    while i < n:
        matched = False
        for length in range(max_span, 1, -1):  # 最宽跨度~2 字窗口（带空格全名也整名命中）
            if i + length > n:
                continue
            window = text[i:i + length]
            if not any("\u3400" <= ch <= "\u9fff" for ch in window):
                continue  # 不含 CJK 的窗口不扫描（代码/ASCII 由其他步骤处理）
            window = window.replace(' ', '')  # 输入端删去空格再与全名比较
            if len(window) > max_len:
                continue  # 压缩后超库内最长全名（无空格文本的长跨度窗口），必不命中
            pairs = name_codes.get(window)
            if not pairs:
                for variant in _st_prefix_variants(window):
                    if variant == window:
                        continue
                    pairs = name_codes.get(variant)
                    if pairs:
                        break
            if pairs and window not in _SECTOR_KEYWORD_SET:
                stocks = [
                    Stock(code=_canonical_stock_code(code, market),
                          name=canonical, market=market)
                    for code, market, canonical in pairs
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


def _is_identified_token(token: Token) -> bool:
    """Token 是否已被前序步骤识别（有 tag 或是已知股票名/代码）。"""
    if token.tag:
        return True
    if is_known_stock_name(token.text):
        return True
    return False


def _extract_full_names_first(normalized: str) -> List[Token]:
    """Step 1: 对整条归一后消息做多股票全名精确匹配扫描（管道首步）。

    实体扫描先于一切切分类步骤（全名撕裂后无法复原，见模块 docstring）。
    入口先 ``extend_AkShare``（幂等）把 AkShare 全量并入 stockDB——首条
    冷消息即与暖态产出一致。直接以整条消息为扫描对象（不经逐 token 包装），
    实体索引每消息只构建一次。
    """
    if any("\u3400" <= ch <= "\u9fff" for ch in normalized):
        extend_AkShare()
    return _split_by_stock_entities(normalized)


# =========================================================================
# Step 4 — 市场关键词提取（"股"+"份"消歧）
# =========================================================================

# 市场相关 tag 关键词 union；"股"+"份"消歧见 _split_market_tokens
# （防 "大港股份" 中的 "港股" 子串被误提取）
_MARKET_TOKEN_PATTERN = _compile_kw_pattern(
    TAG_SUBJECT_MARKET, TAG_SUBJECT_MARKET_BROAD, TAG_SUBJECT_INDEX,
)


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


# =========================================================================
# Step 5 — 无歧义关键词分词（clean 词池）
# =========================================================================

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


# =========================================================================
# Step 6 — 多策略智能匹配（DFS 全匹配：板块词/关键词/股票名）
# =========================================================================

def _isAlpha(s: str) -> bool:
    """检测字符串是否为纯英文字母（a-z, A-Z）。"""
    return bool(s) and all(c.isascii() and c.isalpha() for c in s)


# 单字 filler 集合：全由这些字符组成的片段绝不做股票名全库扫描——否则
# "和"*200 一类刷屏文本在 DFS 逐位置触发全库扫描（5500 名库实测秒级耗时）
_SINGLE_CHAR_FILLERS = frozenset(
    kw for kw in _TAG_KEYWORD_LISTS_EXTEND[TAG_FILLER] if len(kw) == 1
)


def _is_filler_only(segment: str) -> bool:
    """片段是否完全由单字 filler 关键词字符组成（如"和和""的的"）。"""
    return bool(segment) and all(ch in _SINGLE_CHAR_FILLERS for ch in segment)


def _dfs_match(text: str) -> Optional[List[Token]]:
    """深度优先全匹配：0 位置起匹配关键词/股票名并递归剩余文本；无法全匹配
    返回 None（宁可不做也不做错）。全匹配即交叉验证。

    "XX板块"类复合词无专用正则：行业名与泛称分别在各自词池命中，DFS 自然
    产出相邻 [sector_name/sector_n_stock]+[sector] 高置信度组合；未枚举
    行业词（"预制菜板块"）无法全匹配则原样返回，交下游 LLM 兜底。
    """
    if len(text) == 0:
        return []

    # 以字母开头：提取连续英文字母组成的单词
    if _isAlpha(text[0]):
        # 直接组成连续的最大单词 例如 "Alibaba的基本面" → "Alibaba", "的基本面"
        i = 1
        while i < len(text) and _isAlpha(text[i]):
            i += 1
        segment = text[:i]
        # 纯英文做股票名拼音检测 + 美股代码检测；双源按 (code, market) 去重
        # （名称恰等于 ticker 的 AMD/Meta 两源各出一份同实体），先归一到
        # canonical 拼写使去重键与产出一致
        stock_list = _canonical_stocks(resolver_name_to_code_list(segment))
        seen = {(s.code, s.market) for s in stock_list}
        stock_list += [
            s for s in US_stock_code_match(segment)
            if (s.code, s.market) not in seen
        ]
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
        # filler 连续片段不构成股票名：跳过全库扫描，杜绝逐位置扫描失控；
        # 通用公司后缀（公司/集团…）在 extend 词池打 corp_suffix tag，tag
        # 路径同样跳过扫描（词池为单一事实源，见 web_intent_types）
        if not tag and not _is_filler_only(segment):
            stock_list = _canonical_stocks(resolver_name_to_code_list(segment))
        if tag or len(stock_list) > 0:
            rest = _dfs_match(text[length:])
            if rest is not None:
                return [Token(segment, tag or TAG_STOCK_NAME, stocks=stock_list or None)] + rest
            # 库内全名"精确"命中（别名规范名 != 输入，不计）即实体自证：
            # 直接确认返回，余文留空 tag 交 LLM；关键词/子串/拼音/模糊命中
            # 不享此待遇，维持全覆盖交叉验证
            if not tag and stock_list and all(s.name == segment for s in stock_list):
                tail = text[length:]
                return [Token(segment, TAG_STOCK_NAME, stocks=stock_list or None)] + (
                    [Token(tail)] if tail else []
                )

    return None


# Step 6 单 token 长度上限：50 字连续无标点且无前序步骤信号，即非正常
# 对话（刷屏/粘贴大段文字），整体放弃交 LLM。技术上封顶逐字符递归深入
# （实测 ~1500 字 RecursionError）与最坏线性×全库扫描，保证有界；正常
# 聊天分片经 Step 2 标点切分后远短于该上限
_MAX_MULTI_MATCH_TEXT_LEN = 50


# 动态混合匹配文本
def _multi_match(text: str) -> List[Token]:
    """Step 6 子函数：多策略智能匹配（关键词/名称库精确/子串/拼音/模糊）；
    无法完全匹配则原样返回（宁可不做也不做错）。

    前置条件：AkShare 扩展与全名精确消费由管道 Step 1 独占承担——直接
    调用本函数喂冷库长文本会重新暴露无记忆化 DFS 的指数回溯面，调用方应
    走 ``_preprocess_text``。"""
    if not text:
        return []
    if len(text) > _MAX_MULTI_MATCH_TEXT_LEN: # DFS 复杂度控制, 过长 token 交由 LLM 判断
        return [Token(text)]
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


# =========================================================================
# Step 2 — 特殊标点切分
# =========================================================================

def _split_by_special_punct(text: str) -> List[Token]:
    """Step 2: 按特殊标点与空白边界切分（排除 * - .；空白同为词界，
    "tsla aapl" 与 "tsla,aapl" 同构处理）。仅作用于 Step 1 的 gap；切分符
    留作空 tag token，由末端 _HAS_CONTENT_PATTERN 过滤。"""
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


# =========================================================================
# Step 3 — 代码形字符串提取
# =========================================================================

# ---- _CODE_CANDIDATE_PATTERNS — 代码形字符串候选正则（_split_by_codes 专用） ----
# 宽松匹配（宁多勿漏）：命中"像代码"的片段打 TAG_UNKNOWN_CODE，合法性交
# _identify_stock_codes。纯文本匹配不查库、同位置多正则取最长、不推断市场。
_CODE_CANDIDATE_PATTERNS: List[Tuple[str, int]] = [
    # 1. 交易所前缀 + 任意位数字: SH600519, HK88888, SZ123
    (r'(?<![a-zA-Z])(?:SH|SZ|BJ|HK)\d{1,}(?!\d)', re.IGNORECASE),
    # 2. 数字.交易所后缀: 123456.HK, 235454354.sh
    (r'(?<!\d)\d{1,}\.(?:SH|SZ|BJ|HK)(?!\d)', re.IGNORECASE),
    # 3. 裸任意位数字: 600519, 12（形态歧义 → unknown_number，不按位数猜测）
    (r'(?<!\d)\d{1,}(?!\d)', 0),
    # 4. 美股大写 ticker（左右不紧邻字母数字），可选交易所后缀 BRK.B——
    #    后缀与主体整体成 span，防止 "BRK" 与 ".B" 撕成两段
    (r'(?<![A-Za-z0-9.])([A-Z]{2,5}(?:\.[A-Z]{1,2})?)(?![A-Za-z0-9])', 0),
    # 5. 连续字母 + .us 后缀（大小写不敏感）: aapl.us, BABA.US
    (r'(?<![A-Za-z0-9.])([A-Za-z]{1,5}\.us)(?![A-Za-z0-9])', re.IGNORECASE),
]


def _split_by_codes(text: str) -> List[Token]:
    """Step 3 子函数：宽口径代码形字符串提取。

    5 类正则命中"像代码"的片段 → TAG_UNKNOWN_CODE，任意位裸数字 →
    TAG_UNKNOWN_NUMBER（形态歧义，交下游 LLM 辨析）；间隙保留为空 tag
    token。只做形态匹配与最大连续合并，不校验合法性、不推断市场。
    不复用 extract_stock_codes：其首码白名单会丢弃 777777 这类非法代码，
    本函数保留供下游二次确认。
    """
    if not text:
        return []

    # 阶段 1：正则独立扫描收集 span，重叠/嵌套交阶段 2 合并。两类放行保
    # 证不影响关键词语义：关键词池内纯 ASCII 词（"AI"/"PK" 大写也不作代码
    # 候选，交关键词分类）；含数字枚举指数词（"沪深300"）内的数字段（完全
    # 包含于关键词 span 才放行，部分重叠如 "沪深3000" 不适用）
    digit_keyword_spans: List[Tuple[int, int]] = (
        [(m.start(), m.end()) for m in _DIGIT_KEYWORDS_RE.finditer(text)]
        if _DIGIT_KEYWORDS_RE is not None
        else []
    )
    spans: List[Tuple[int, int]] = []
    for pattern, flags in _CODE_CANDIDATE_PATTERNS:
        for m in re.finditer(pattern, text, flags):
            if m.group().upper() in _ASCII_KEYWORD_UPPER:
                continue
            # ST 前缀放行：后继 CJK / 前邻 * / 后继 *+CJK 时 "ST" 不作代码
            # 候选，整名交 Step 1（兜底库外 ST 名不被撕走前缀）
            if m.group() == "ST" and (
                (m.end() < len(text) and "\u3400" <= text[m.end()] <= "\u9fff")
                or (m.start() > 0 and text[m.start() - 1] == "*")
                or (m.end() + 1 < len(text) and text[m.end()] == "*"
                    and "\u3400" <= text[m.end() + 1] <= "\u9fff")
            ):
                continue
            if any(ps <= m.start() and m.end() <= pe for ps, pe in digit_keyword_spans):
                continue
            spans.append((m.start(), m.end()))

    # 无命中 → 整段文本作为一个空 tag token 返回
    if not spans:
        return [Token(text)]

    # 阶段 2：最大连续合并（重叠 span 取最长，不被子串截断）
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
        if span_text.isdigit():
            # 裸数字形态歧义（代码/指数/价格/年份/日期…）→ unknown_number，
            # 不进代码校验，交下游 LLM 辨析
            tokens.append(Token(span_text, TAG_UNKNOWN_NUMBER))
        else:
            tokens.append(Token(span_text, TAG_UNKNOWN_CODE))
        pos = e
    tail = text[pos:].strip()
    if tail:
        tokens.append(Token(tail))
    return tokens


def _apply_code_extraction(tokens: List[Token]) -> List[Token]:
    """Step 3: 对空 tag token 做代码形提取（已识别 token 受保护）。"""
    result: List[Token] = []
    for t in tokens:
        if _is_identified_token(t):
            result.append(t)
        else:
            result.extend(_split_by_codes(t.text))
    return result


# =========================================================================
# _preprocess_text — 六步管道入口
# =========================================================================

def _preprocess_text(text: str) -> Tuple[str, List[Token]]:
    """六步管道分词，返回 (原文本, token列表)。步骤与不变量见模块 docstring。

    入口对工作副本做 NFKC 宽度归一（返回的原文本不变）：全角数字/字母
    （"６００５１９"/"Ａ股"）与半角同形参与全部步骤。unknown_code 随后由
    _identify_stock_codes 辨认为 stock_code / wrong_{market}_code /
    unknown_{market}_code。
    """
    # ---- 六步管道 ----
    normalized = unicodedata.normalize("NFKC", text)  # 宽度归一（工作副本，原文原样返回）
    tokens: List[Token] = []
    for t in _extract_full_names_first(normalized):   # Step 1: 全名实体扫描
        if t.tag:
            tokens.append(t)                # 已识别 token 不再切分
        else:
            tokens.extend(_split_by_special_punct(t.text))  # Step 2: 标点/空白只切 gap
    tokens = _apply_code_extraction(tokens)           # Step 3: 代码形提取
    tokens = _apply_market_extraction(tokens)         # Step 4: 市场关键词
    tokens = _apply_clean_keyword_extraction(tokens)  # Step 5: 无歧义关键词
    tokens = _apply_multi_extraction(tokens)          # Step 6: 多策略匹配

    # 过滤纯标点/空白 token
    tokens = [t for t in tokens if t.text.strip() and _HAS_CONTENT_PATTERN.search(t.text)]

    return text, tokens


# =========================================================================
# 代码辨认 — unknown_code → stock_code / wrong_{market}_code / unknown_{market}_code
# =========================================================================

def _is_valid_canonical_numeric_code(code: str) -> bool:
    """extract_stock_codes 规范化后的数字代码是否满足裸格式约束（6 位 A 股
    首码白名单 0/3/6/4/8 或 92 段、HK+5 位）。extract 只去前缀不校验白名单，
    规范化结果必须再过本闸门，否则带前缀的非法代码会绕过确认直接执行。
    """
    c = (code or "").strip().upper()
    if c.startswith("HK"):
        digits = c[2:]
        return digits.isdigit() and len(digits) == 5
    if c.isdigit():
        return len(c) == 6 and (c[0] in "03648" or c.startswith("92"))
    return False


def _shape_market(text: str, canonical: str) -> str:
    """代码市场推断：优先规范化形态（HK 前缀 → hk、6 位 → a、字母 → us），
    形态非法（canonical 为空）时回退原始文本的前缀/后缀形状；兜底 a。"""
    if canonical:
        if canonical.startswith("HK"):
            return "hk"
        m = _market_of_code(canonical)
        if m:
            return m
    t = (text or "").upper()
    if t.startswith("HK") or t.endswith(".HK"):
        return "hk"
    if _isAlpha(t.split(".", 1)[0]) and not any(ch.isdigit() for ch in t):
        return "us"
    return "a"


# 显式交易所标注解析：前缀 SH/SZ/BJ/HK 或后缀 .SH/.SZ/.BJ/.HK（大小写
# 不敏感），后缀优先。判决层权威解析，不复用 extract_stock_codes（那是
# 候选收集器，位数不符时静默放行，不适用于判决）；标注市场与数字形态
# 矛盾 → wrong_{标注市场}，绝不静默换市场解析
_EXPLICIT_MARKER_RE = re.compile(
    r"^(?P<pfx>SH|SZ|BJ|HK)?(?P<digits>[0-9]+)(?:[.](?P<sfx>SH|SZ|BJ|HK))?$",
    re.IGNORECASE,
)
_MARKER_MARKET = {"SH": "a", "SZ": "a", "BJ": "a", "HK": "hk"}


def _identify_one_code(t: Token) -> Token:
    """单个 TAG_UNKNOWN_CODE token 的辨认（_identify_stock_codes 子函数）：
    显式标注优先的确定性判决。

    标注市场/交易所与数字形态矛盾 → wrong_{标注市场}（HK600519 / SH00700 /
    SH000001 不静默改按其它市场或交易所解析）；形态合法则查库 → stock_code，
    未命中按该市场库全量与否细分 wrong/unknown。纯字母 → 美股 ticker 路径；
    无标注的防御形态走 extract 兜底（管道契约下 Step 3 不会产出该形态）。"""
    text = t.text

    # 纯字母 → 美股 ticker：仅本地库命中才认可，未命中一律存疑交 LLM
    if not any(ch.isdigit() for ch in text):
        ticker = text.split(".", 1)[0].upper()
        matched = US_stock_code_match(ticker)
        if matched:
            # 统一规范大写拼写（aapl.us → AAPL），同一股票共享同一代码身份
            return Token(ticker, TAG_STOCK_CODE, stocks=tuple(matched))
        return Token(text, unknown_code_tag("us"))

    m = _EXPLICIT_MARKER_RE.match(text)
    pfx, sfx = (m.group("pfx"), m.group("sfx")) if m else (None, None)
    if pfx and sfx and pfx.upper() != sfx.upper():
        # 前后缀双标注市场互斥（HK600519.SH）：静态规则断非法，按后缀市场
        return Token(text, wrong_code_tag(_MARKER_MARKET[sfx.upper()]))
    marker = (sfx or pfx) if m else None
    if marker is not None:
        market = _MARKER_MARKET[marker.upper()]
        digits = m.group("digits")
        # HK 短码先补零再校验（1810.HK/HK700 → HK01810/HK00700，对齐
        # stock_code_utils zfill(5) 归一口径；≥5 位 zfill 无操作，位数
        # 超标判决不受影响）
        canonical = f"HK{digits.zfill(5)}" if marker.upper() == "HK" else digits
        # 标注市场的形态闸门（HK=5 位、A 股=6 位+首码白名单）：不符即
        # wrong_{标注市场}，即使数字段恰为其它市场合法代码也不改判
        if not _is_valid_canonical_numeric_code(canonical):
            return Token(text, wrong_code_tag(market))
        if marker.upper() != "HK" and _infer_cn_exchange(digits) != marker.upper():
            # 数字形态所属交易所与标注点名矛盾（SH000001/BJ600519）：
            # wrong_{标注市场}，不得静默解析成其它交易所的同号代码
            return Token(text, wrong_code_tag(market))
        stock = lookup_stock_by_code(canonical)
        if stock is not None:
            # 规范化拼写（hk00700 → HK00700、600519.SH → 600519）
            return Token(canonical, TAG_STOCK_CODE, stocks=(stock,))
        if is_market_db_complete(market):
            # 该市场库已全量仍未命中（如 A 股 AkShare 已并入）：确定不存在
            return Token(text, wrong_code_tag(market))
        # 库非全量（A 股未扩展 / hk/us 本地精选库）：存疑交下游 LLM 判断
        return Token(text, unknown_code_tag(market))

    # 无标注防御路径（管道契约下不出现：Step 3 裸数字 → unknown_number）
    extracted = [c.upper() for c in extract_stock_codes(text)]
    canonical = extracted[0] if extracted else ""
    if not canonical or not all(_is_valid_canonical_numeric_code(c) for c in extracted):
        return Token(text, wrong_code_tag(_shape_market(text, canonical)))
    stock = lookup_stock_by_code(canonical)
    if stock is not None:
        return Token(canonical, TAG_STOCK_CODE, stocks=(stock,))
    market = _shape_market(text, canonical)
    if is_market_db_complete(market):
        return Token(text, wrong_code_tag(market))
    return Token(text, unknown_code_tag(market))


def _identify_stock_codes(tokens: List[Token]) -> List[Token]:
    """对 TAG_UNKNOWN_CODE 逐个辨认，三种产出：

    - 库命中 → ``stock_code``：``stocks`` 附完整三元组，文本用规范化拼写
      （hk00700 → HK00700、600519.SH → 600519，与名称路径
      ``_canonical_stock_code`` 同源归一，同一股票共享同一代码身份）；
    - 形态非法或该市场库已全量未命中 → ``wrong_{market}_code``：确定不存在；
    - 该市场库非全量未命中 → ``unknown_{market}_code``：存疑交下游 LLM。
    """
    result: List[Token] = []
    for t in tokens:
        if t.tag != TAG_UNKNOWN_CODE:
            result.append(t)
            continue
        result.append(_identify_one_code(t))
    return result
