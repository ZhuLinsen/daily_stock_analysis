# -*- coding: utf-8 -*-
"""
Web Chat 意图识别层 — 六步分词管道（Intent Tokenizer）。

== 模块定位 ==
把一条用户消息切分为携带语义标签的 ``Token`` 序列，供
``web_intent_resolver.WebIntentResolver`` 做规则分类；本模块不做任何
意图判定，只负责"识别出消息里有什么"。

== 六步管道（_preprocess_text）==
  Step 1   特殊标点切分（排除 * - .，可能出现在股票名/代码中）
  Step 2   代码形字符串提取（unknown_code；任意位裸数字 → unknown_number）
  Step 3   多股票实体扫描（仅全名精确匹配，最长优先、非重叠）
  Step 4   市场关键词提取（含"股"+"份"消歧）
  Step 5   无歧义关键词分词（clean 词池）
  Step 5.5 行业后缀复合词（XX板块/行业/赛道/概念/题材 → sector）
  Step 6   多策略智能匹配（关键词 + 名称库精确/子串/拼音/模糊 DFS）

AkShare 扩展统一由下游服务层拥有：``resolver_name_to_code_list`` 对 CJK
输入自扩展（进程启动 warmup 预热 + stale-while-revalidate，30 分钟缓存），
本模块绝不主动调用 extend_AkShare，只读当时点的 stockDB。管道产出后由
``_identify_stock_codes`` 把 unknown_code 辨认为 stock_code（库命中，附完整
三元组）/ wrong_{market}_code（确定不存在）/ unknown_{market}_code（存疑交
下游 LLM）。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from src.agent.stock_scope import extract_stock_codes  # 代码格式校验（不查库）
from src.agent.web_intent_types import (
    Market,
    TAG_FILLER,
    TAG_SECTOR,
    TAG_STOCK_CODE,
    TAG_STOCK_NAME,
    TAG_SUBJECT_INDEX,
    TAG_SUBJECT_MARKET,
    TAG_SUBJECT_MARKET_BROAD,
    TAG_UNKNOWN_CODE,
    TAG_UNKNOWN_NUMBER,
    Token,
    _CLEAN_KEYWORDS_PATTERN,
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
    is_known_stock_name,  # 本地名称表成员判定（不联网）
    is_market_db_complete,  # 市场库全量判定（wrong/unknown 细分依据）
    lookup_stock_by_code,  # 代码查库（stock_code 三元组来源）
    resolver_name_to_code_list,
    stockDB,  # 全局名称库（code→name，可被 AkShare 原地扩充）
)


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


# =========================================================================
# Step 3 — 多股票实体扫描（仅全名精确匹配）
# =========================================================================

def _build_entity_index() -> Tuple[List[str], Dict[str, List[Tuple[str, str]]]]:
    """构建实体扫描用的名称索引：全名去重保序列表 + 全名 → [(code, market)]。

    每个待扫描 token 重建一次（stockDB 可能被下游 CJK 解析触发的 AkShare
    扩充改变，不能跨消息缓存）。本函数只读当时的 stockDB，绝不主动发起扩展。
    """
    names: List[str] = []
    name_codes: Dict[str, List[Tuple[str, str]]] = {}
    # 持锁迭代：本函数跑在 asyncio.to_thread 工作线程，可能与另一请求的
    # extend_AkShare 原地合并并发，不加锁会触发 dict changed size 迭代崩溃
    with _db_lock:
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


def _is_identified_token(token: Token) -> bool:
    """Token 是否已被前序步骤识别（有 tag 或是已知股票名/代码）。"""
    if token.tag:
        return True
    if is_known_stock_name(token.text):
        return True
    return False


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


# =========================================================================
# Step 4 — 市场关键词提取（"股"+"份"消歧）
# =========================================================================

# 市场分词 pattern = 市场相关 tag 关键词 union。"股"+"份" 消歧见 _split_market_tokens，
# 避免 "大港股份" 中的 "港股" 子串被误提取
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
# Step 5.5 — 行业后缀复合词提取
# =========================================================================

# "XX板块/XX行业/XX赛道/XX概念/XX题材"：前缀自由（CJK/ASCII），整体是行业
# 泛称。行业词表永远不全（电力/能源/软件/建筑/家电/旅游/航空/物流/农业/
# 传媒/通信/纺织……），靠词表枚举会把"建筑板块"静默解析成"中国建筑"个股；
# 以后缀复合形态整体打 TAG_SECTOR，行业语境优先于个股解析。
_SECTOR_SUFFIX_COMPOUND_PATTERN = re.compile(
    r"[\u3400-\u9fffA-Za-z]{1,10}(?:板块|行业|赛道|概念|题材)"
)


def _split_by_sector_compounds(text: str) -> List[Token]:
    """Step 5.5 子函数：行业后缀复合词整体打 TAG_SECTOR，间隙保留为空 tag token。"""
    if not text:
        return []
    tokens: List[Token] = []
    pos = 0
    for m in _SECTOR_SUFFIX_COMPOUND_PATTERN.finditer(text):
        if pos < m.start():
            gap = text[pos:m.start()].strip()
            if gap:
                tokens.append(Token(gap))
        tokens.append(Token(m.group(), TAG_SECTOR))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        tokens.append(Token(tail))
    return tokens


def _apply_sector_compound_extraction(tokens: List[Token]) -> List[Token]:
    """Step 5.5: 对未识别 token 提取行业后缀复合词，已打 tag 的 token 受保护。

    必须位于 Step 5 之后：clean 关键词（分析/看看/怎么样…）已先行切出，
    复合词只吞并剩余的行业泛称前缀；也必须位于 Step 6 之前：否则行业词
    （建筑/电力/家电…）会先被多策略匹配解析成个股名/缩写。
    """
    result: List[Token] = []
    for t in tokens:
        if t.tag:
            result.append(t)
        else:
            result.extend(_split_by_sector_compounds(t.text))
    return result


# =========================================================================
# Step 6 — 多策略智能匹配（DFS 全匹配）
# =========================================================================

def _isAlpha(s: str) -> bool:
    """检测字符串是否为纯英文字母（a-z, A-Z）。"""
    return bool(s) and all(c.isascii() and c.isalpha() for c in s)


# 单字 filler 关键词集合：完全由这些字符组成的片段信息量过低，绝不作为
# 股票名参与 Step 6 的全库扫描。否则"和"*200 一类 filler 刷屏文本在 DFS
# 每个位置都会对 2~4 字片段触发精确/子串/拼音/模糊全库扫描（库约 5500 名
# 时 200 字消息实测秒级耗时），足以拖垮 asyncio.to_thread 工作线程。
_SINGLE_CHAR_FILLERS = frozenset(
    kw for kw in _TAG_KEYWORD_LISTS_EXTEND[TAG_FILLER] if len(kw) == 1
)


def _is_filler_only(segment: str) -> bool:
    """片段是否完全由单字 filler 关键词字符组成（如"和和""的的"）。"""
    return bool(segment) and all(ch in _SINGLE_CHAR_FILLERS for ch in segment)


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
        stock_list = resolver_name_to_code_list(segment) + US_stock_code_match(segment) # 疑似未去重？
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
        # filler 连续片段（"和和""的的"）不可能构成股票名：跳过全库扫描，
        # 由 1 字 filler 关键词路径继续递归，杜绝逐位置全库扫描的复杂度失控
        if not tag and not _is_filler_only(segment):
            stock_list = resolver_name_to_code_list(segment)
        if tag or len(stock_list) > 0:
            rest = _dfs_match(text[length:])
            if rest is not None:
                return [Token(segment, tag or TAG_STOCK_NAME, stocks=stock_list or None)] + rest

    return None


# Step 6 DFS 的单 token 输入长度上限：超长无标点文本（填充词刷屏/粘贴
# 大段文字）会让逐字符递归线性深入（实测 ~1500 字即 RecursionError），
# 且每个递归层对 4/3/2 字片段触发全库精确/子串/拼音/模糊扫描。超过上限
# 的 token 原样返回（视为未识别，交由下游 LLM 兜底）；Steps 2~5 已提取
# 的代码/全名/市场/关键词信号不受影响。Step 1 已按标点切分，正常聊天
# 分片远短于该上限。
_MAX_MULTI_MATCH_TEXT_LEN = 200


# 动态混合匹配文本
def _multi_match(text: str) -> List[Token]:
    """多策略智能匹配：DFS 匹配 2~4 字关键词/名字子串；无法完全匹配则原样返回（宁可不做也不做错）。"""
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
# Step 1 — 特殊标点切分
# =========================================================================

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


# =========================================================================
# Step 2 — 代码形字符串提取
# =========================================================================

# ---- _CODE_CANDIDATE_PATTERNS — 代码形字符串候选正则（_split_by_codes 专用） ----
# 宽松匹配（宁多勿漏）：找出所有"看起来像股票代码"的片段打 TAG_UNKNOWN_CODE，
# 合法性交给下游 _identify_stock_codes。唯一例外：任意位裸数字由 _split_by_codes
# 直接标记为 TAG_UNKNOWN_NUMBER，不进入代码校验——裸数字可能是代码/指数/价格/
# 年份/数量/日期，形态本身无法定论，交由下游 LLM 结合上下文辨析。
# 设计要点：纯文本匹配不查库；同位置多正则命中取最长；不做市场推断。
# 覆盖形态：
#   1. 交易所前缀+数字        SH600519 / HK88888（SH/SZ/BJ/HK）
#   2. 数字.交易所后缀        123456.HK / 235454354.sh
#   3. 裸数字                 600519 / 12 / 6005199（全部 → unknown_number）
#   4. 美股连续大写 ticker    BABA / TSLA（左右不紧邻字母数字）
#   5. 连续字母 + .us 后缀    aapl.us / BABA.US（大小写不敏感）
_CODE_CANDIDATE_PATTERNS: List[Tuple[str, int]] = [
    # 1. 交易所前缀 + 任意位数字: SH600519, HK88888, SZ123
    (r'(?<![a-zA-Z])(?:SH|SZ|BJ|HK)\d{1,}(?!\d)', re.IGNORECASE),
    # 2. 数字.交易所后缀: 123456.HK, 235454354.sh
    (r'(?<!\d)\d{1,}\.(?:SH|SZ|BJ|HK)(?!\d)', re.IGNORECASE),
    # 3. 裸任意位数字: 600519, 12, 6005199（裸数字形态歧义，统一在 _split_by_codes 标记为 unknown_number，不按位数猜测）
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
      "HK3294384923"/"TSLA" → unknown_code；"600519"/"12" → unknown_number

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
        if span_text.isdigit():
            # 任意位裸数字 → unknown_number：可能是代码/指数/价格/年份/数量/
            # 日期，形态本身无法定论，不进入代码校验，交由下游 LLM 结合上下文
            # 辨析（纯数字 span 只可能来自裸数字正则）
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


# =========================================================================
# _preprocess_text — 六步管道入口
# =========================================================================

def _preprocess_text(text: str) -> Tuple[str, List[Token]]:
    """六步管道分词，返回 (原文本, token列表)。

    Step 1 标点切分 → Step 2 代码形（unknown_code，任意位裸数字 → unknown_number）→
    Step 3 多股票实体扫描（全名精确匹配）→ Step 4 市场关键词 → Step 5 无歧义
    关键词 → Step 5.5 行业后缀复合词（XX板块，整体 TAG_SECTOR，先于个股解析）→
    Step 6 多策略匹配。unknown_code 由 _identify_stock_codes 辨认为
    stock_code（附三元组）/wrong_{market}_code/unknown_{market}_code。

    AkShare 扩展不在本管道内执行：Step 6 的 resolver_name_to_code_list 对
    CJK 片段自扩展（下游唯一扩展时机：warmup 预热 + stale-while-revalidate，
    详见 name_to_code_resolver），Step 3 只扫描当时点的 stockDB（进程预热后
    即含 AkShare 全量名称）。库外全名由 Step 6 在扩展库上解析承接。
    """
    # ---- 六步管道 ----
    tokens = _split_by_special_punct(text)          # Step 1: 特殊标点符号提取和分词（排除 * - .）
    tokens = _apply_code_extraction(tokens)         # Step 2: 代码形字符串（unknown_code）
    tokens = _apply_full_name_extraction(tokens)    # Step 3: 股票全名匹配（当时点 stockDB）
    tokens = _apply_market_extraction(tokens)       # Step 4: 市场关键词
    tokens = _apply_clean_keyword_extraction(tokens)  # Step 5: 无歧义关键词
    tokens = _apply_sector_compound_extraction(tokens)  # Step 5.5: 行业后缀复合词（XX板块）
    tokens = _apply_multi_extraction(tokens)        # Step 6: 多策略子串智能匹配（CJK 片段触发下游扩展）

    # 过滤纯标点/空白 token
    tokens = [t for t in tokens if t.text.strip() and _HAS_CONTENT_PATTERN.search(t.text)]

    return text, tokens


# =========================================================================
# 代码辨认 — unknown_code → stock_code / wrong_{market}_code / unknown_{market}_code
# =========================================================================

def _is_valid_canonical_numeric_code(code: str) -> bool:
    """extract_stock_codes 规范化后的数字代码是否满足裸格式约束。

    extract 的交易所前缀/后缀形态（SH777777 / 777777.SH）只做去前缀规范化，
    不校验 A 股首码白名单；规范化结果必须再过一次裸格式校验（6 位 A 股首码
    0/3/6/4/8 或 92 开头北交所段、HK+5 位港股），否则带前缀的非法代码会
    规范化成"777777"后绕过确认闸门直接执行。
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


def _identify_one_code(t: Token) -> Token:
    """单个 TAG_UNKNOWN_CODE token 的辨认（_identify_stock_codes 子函数）。"""
    text = t.text

    # 纯字母 → 美股 ticker（含 .us 后缀）：仅本地库命中才认可；
    # 库外美股库永不全量，未命中一律存疑交 LLM，绝不硬猜
    if not any(ch.isdigit() for ch in text):
        ticker = text.split(".", 1)[0].upper()
        matched = US_stock_code_match(ticker)
        if matched:
            # extract 的美股正则只认大写，统一用规范大写拼写
            # （aapl.us → AAPL），同一股票在任何轮次共享同一代码身份。
            return Token(ticker, TAG_STOCK_CODE, stocks=tuple(matched))
        return Token(text, unknown_code_tag("us"))

    extracted = [c.upper() for c in extract_stock_codes(text)]
    canonical = extracted[0] if extracted else ""
    # 形态非法（777777 首码白名单 / SH1 / HK3294384923 位数不符）：交易所
    # 静态规则即可断定非法，与库状态无关 → wrong_{market}_code
    if not canonical or not all(_is_valid_canonical_numeric_code(c) for c in extracted):
        return Token(text, wrong_code_tag(_shape_market(text, canonical)))

    stock = lookup_stock_by_code(canonical)
    if stock is not None:
        # 规范化拼写（hk00700/00700.HK → HK00700，600519.SH → 600519）：
        # 同一股票在不同轮次/事件中共享同一代码身份
        return Token(canonical, TAG_STOCK_CODE, stocks=(stock,))

    market = _shape_market(text, canonical)
    if is_market_db_complete(market):
        # 该市场库已全量仍未命中（如 A 股 AkShare 已并入）：确定不存在
        return Token(text, wrong_code_tag(market))
    # 库非全量（A 股未扩展 / hk/us 本地精选库）：存疑交下游 LLM 判断
    return Token(text, unknown_code_tag(market))


def _identify_stock_codes(tokens: List[Token]) -> List[Token]:
    """对 TAG_UNKNOWN_CODE 逐个辨认，三种产出：

    - 库命中 → ``stock_code``：``stocks`` 附完整 (code/name/market) 三元组，
      文本用规范化拼写（hk00700/00700.HK → HK00700，600519.SH/SH600519 →
      600519），同一股票在不同轮次/事件中必须共享同一代码身份，否则
      recent_stocks 去重、intent_resolved 事件与前端代码比较都会出现同一
      股票的多重拼写；
    - 未命中 + 形态非法或该市场库已全量 → ``wrong_{market}_code``：确定不
      存在，下游走待确认流程；
    - 未命中 + 该市场库非全量 → ``unknown_{market}_code``：存疑交下游 LLM
      判断（宁可不做也不做错）。

    市场由代码形态推断：字母 → us，HK 前缀/后缀 → hk，其余 → a。
    任意位裸数字不会到达本函数（已在 _split_by_codes 标记为 unknown_number）。
    """
    result: List[Token] = []
    for t in tokens:
        if t.tag != TAG_UNKNOWN_CODE:
            result.append(t)
            continue
        result.append(_identify_one_code(t))
    return result
