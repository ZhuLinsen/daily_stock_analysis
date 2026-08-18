# -*- coding: utf-8 -*-
"""
===================================
Name-to-Code Resolution Engine
===================================

Resolve stock name to code: local mapping + list resolution (exact/substring/
pinyin/fuzzy) over an AkShare-extended stock database.
"""

from __future__ import annotations

import difflib
import logging
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from src.data.stock_mapping import STOCK_NAME_MAP
from src.services.stock_code_utils import is_code_like, normalize_code

logger = logging.getLogger(__name__)

# AkShare result cache: (timestamp, name_to_code_dict)
_akshare_cache: Optional[tuple[float, Dict[str, str]]] = None
_AKSHARE_CACHE_TTL = 1800  # 30 MIN

# AkShare merge guard: _get_akshare_name_to_code() 返回同一缓存 dict（30 分钟 TTL）。
# 已合并过该对象则直接跳过，避免对同一份数据重复遍历/扩展。
_akshare_merged: object = None


def _contains_cjk(text: str) -> bool:
    """Return True when text contains CJK characters."""
    return any("\u3400" <= ch <= "\u9fff" for ch in text)


def _is_code_like(s: str) -> bool:
    """Backward-compatible wrapper of shared code-like check."""
    return is_code_like(s)


def _normalize_code(raw: str) -> Optional[str]:
    """Backward-compatible wrapper of shared code normalization."""
    return normalize_code(raw)


def _build_reverse_map_no_duplicates(
    code_to_name: Dict[str, str],
) -> Dict[str, str]:
    """
    Build name -> code map. If a name maps to multiple codes (ambiguous), exclude it.
    """
    name_to_codes: Dict[str, Set[str]] = {}
    for code, name in code_to_name.items():
        if not name or not code:
            continue
        name = name.strip()
        if name not in name_to_codes:
            name_to_codes[name] = set()
        name_to_codes[name].add(code)
    # Only include names with exactly one code
    return {name: next(iter(codes)) for name, codes in name_to_codes.items() if len(codes) == 1}


def _get_akshare_name_to_code() -> Optional[Dict[str, str]]:
    """Fetch A-share name->code from AkShare, with cache."""
    global _akshare_cache
    now = time.time()
    if _akshare_cache is not None and (now - _akshare_cache[0]) < _AKSHARE_CACHE_TTL:
        return _akshare_cache[1]
    try:
        import akshare as ak

        df = ak.stock_info_a_code_name()
        if df is None or df.empty:
            return None
        code_to_name = {}
        for _, row in df.iterrows():
            code = row.get("code")
            name = row.get("name")
            if code is None or name is None:
                continue
            code_str = str(code).strip()
            # Strip .SH/.SZ suffix
            if "." in code_str:
                base, suffix = code_str.rsplit(".", 1)
                if suffix.upper() in ("SH", "SZ", "SS") and base.isdigit():
                    code_str = base
            code_to_name[code_str] = str(name).strip()
        result = _build_reverse_map_no_duplicates(code_to_name)
        _akshare_cache = (now, result)
        logger.info(f"[NameResolver] AkShare cache loaded: {len(result)} name->code mappings")
        return result
    except Exception as e:
        logger.warning(f"[NameResolver] AkShare fallback failed: {e}")
        return None


# =========================================================================
# Stock dataclass — code/name/market triple, dict-compatible for back compat
# =========================================================================


@dataclass
class Stock:
    """Stock entry with code, name, market.

    Supports dict-style access (``s["code"]``) and equality with dict/str.
    """

    code: str
    name: str = ""
    market: str = ""

    def __getitem__(self, key: str) -> str:
        if key == "code":
            return self.code
        if key == "name":
            return self.name
        if key == "market":
            return self.market
        raise KeyError(key)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Stock):
            return (self.code, self.name, self.market) == (other.code, other.name, other.market)
        if isinstance(other, dict):
            return (self.code, self.name, self.market) == (
                other.get("code", ""), other.get("name", ""), other.get("market", "")
            )
        if isinstance(other, str):
            return self.code == other
        return NotImplemented


# =========================================================================
# stockDB — global stock database, initialized from STOCK_NAME_MAP
# =========================================================================

stockDB: Dict[str, str] = dict(STOCK_NAME_MAP)

_MARKET_ORDER: Dict[str, int] = {"a": 0, "hk": 1, "us": 2}


def extend_AkShare() -> bool:
    """用 AkShare 全量 A 股数据扩充 stockDB（30 分钟缓存）。

    返回值契约（供 _preprocess_text 决定是否重跑全名扫描）：
      - True  — 首次扩展：stockDB 实际并入了新条目（下游名称/拼音缓存已同步失效）；
      - False — 不需要再扩展：同一份缓存数据已合并过（幂等短路），或 AkShare
                获取失败/返回空数据/无任何新条目（数据库未发生变化）。
    已扩展后重复调用零网络开销（命中内存缓存），TTL 过期后才重新拉取。
    """
    global _akshare_merged
    akshare_map = _get_akshare_name_to_code()
    if not akshare_map:
        return False  # 获取失败/空数据：无可扩展
    if _akshare_merged is akshare_map:
        return False  # 同一份缓存已合并过：不需要再扩展（幂等）
    added = 0
    # _get_akshare_name_to_code() 返回 name→code 反向映射，而 stockDB 是
    # code→name：按名称遍历、以代码为键写入，保持方向一致。
    for name, code in akshare_map.items():
        if code not in stockDB:
            stockDB[code] = name
            added += 1
    _akshare_merged = akshare_map
    if not added:
        return False  # 缓存数据无新条目：数据库未变化，无需重扫
    # stockDB 原地扩充，模块内按对象身份缓存的名称列表/拼音列表已失效，
    # 需重置，否则 resolver_name_to_code_list 等下游看不到新增名称。
    _database_names_cache[:] = [None, None, None]
    return True


# =========================================================================
# Name matching helpers
# =========================================================================


_database_names_cache: List = [None, None, None]  # [database_obj, names_list, pinyins_list]


def _database_names(database: Dict[str, str]) -> List[str]:
    """Deduplicated, order-preserving list of stock names from a database (cached by object identity)."""
    if _database_names_cache[0] is database:
        return _database_names_cache[1]
    names = list(dict.fromkeys(database.values()))
    _database_names_cache[0] = database
    _database_names_cache[1] = names
    _database_names_cache[2] = None
    return names


def _database_pinyins(database: Dict[str, str]) -> List[str]:
    """Lowercased full pinyin of every name, aligned with ``_database_names`` (cached)."""
    pinyins = _database_names_cache[2]
    if pinyins is None:
        try:
            from pypinyin import lazy_pinyin

            pinyins = [
                "".join(lazy_pinyin(name)).lower()
                for name in _database_names(database)
            ]
        except (ImportError, Exception):
            pinyins = [""] * len(_database_names(database))
        _database_names_cache[2] = pinyins
    return pinyins


def _is_exact_name_hit(query: str, name: str) -> bool:
    """Case-insensitive exact equality between a query and a stock name."""
    return name.strip().lower() == query.strip().lower()


def _is_single_char_typo(input_name: str, candidate_name: str) -> bool:
    """Return True when two names only differ by one character position."""
    if not input_name or not candidate_name:
        return False
    if len(input_name) != len(candidate_name):
        return False
    # Keep typo fallback conservative: only for names with enough signal.
    if len(input_name) < 3:
        return False
    diff = sum(1 for a, b in zip(input_name, candidate_name) if a != b)
    return diff == 1


def _fix_name(fragment: str, database: Dict[str, str]) -> List[str]:
    """Resolve a name fragment to full stock names.

    Strategy chain (inherits the original resolve_name_to_code flow):
    1. Exact match (case-insensitive)
    2. Substring match (case-insensitive; only for fragments with >= 2 CJK
       chars, e.g. 茅台 -> 贵州茅台)
    3. Pinyin-based matching (lazy_pinyin on both sides, substring comparison;
       same method as the original backup)
    4. difflib fuzzy match (cutoff 0.8, plus a conservative single-char-typo
       fallback at 0.7; same method as the original backup)
    """
    if not fragment:
        return []
    fragment_lower = fragment.lower()
    names = _database_names(database)

    # 1. Exact match (case-insensitive)
    for name in names:
        if name.lower() == fragment_lower:
            return [name]

    matches: List[str] = []

    # 2. Substring match (case-insensitive, fragments with >= 2 CJK chars,
    #    e.g. 茅台 ⊂ 贵州茅台)
    if sum(1 for ch in fragment if '\u3400' <= ch <= '\u9fff') >= 2:
        matches = [name for name in names if fragment_lower in name.lower()]
        if matches:
            return matches

    # 3. Pinyin-based matching (lazy_pinyin on both sides, substring,
    #    case-insensitive; e.g. "maotai" ⊂ "guizhoumaotai" 贵州茅台)
    try:
        from pypinyin import lazy_pinyin

        fragment_pinyin = "".join(lazy_pinyin(fragment)).lower()
    except (ImportError, Exception):
        fragment_pinyin = ""
    if fragment_pinyin:
        for name, name_pinyin in zip(names, _database_pinyins(database)):
            if fragment_pinyin in name_pinyin:
                matches.append(name)
        if matches:
            return matches

    # 4. difflib fuzzy match (only for fragments > 2 chars; strict cutoff 0.8,
    #    plus a single-char-typo fallback at 0.7, e.g. "贵州茅苔" -> 贵州茅台)
    if len(fragment) > 2:
        dl_matches = difflib.get_close_matches(fragment, names, n=5, cutoff=0.8)
        if dl_matches:
            return dl_matches
        typo_matches = difflib.get_close_matches(fragment, names, n=5, cutoff=0.7)
        typo_hits = [m for m in typo_matches if _is_single_char_typo(fragment, m)]
        if typo_hits:
            return typo_hits

    return []


def _infer_code_market(code: str) -> Optional[str]:
    """Infer market from code format: 6-digit→a, 5-digit→hk, letters→us."""
    if not code:
        return None
    c = code.strip().upper()
    if c.isdigit():
        if len(c) == 5:
            return "hk"
        if len(c) == 6:
            return "a"
        return None
    if re.match(r"^[A-Z]{1,5}(\.[A-Z])?$", c):
        return "us"
    return None


def _find_codes_for_name(name: str, database: Dict[str, str]) -> List[Tuple[str, str]]:
    """Find all (code, market) pairs for a given stock name in the database."""
    results: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    for code, mapped_name in database.items():
        if mapped_name == name:
            m = _infer_code_market(code)
            if m and code not in seen:
                results.append((code, m))
                seen.add(code)
    return results


# =========================================================================
# is_known_stock_name — lightweight boolean check (no network)
# =========================================================================


def is_known_stock_name(fragment: str) -> bool:
    """Check whether *fragment* is a real stock name (or substring of one) in the local database.

    Cheap, pure-local, no network. Only exact/substring match — no pinyin, no fuzzy,
    no AkShare. Safe to call per-message in rule paths.
    """
    if not fragment or not isinstance(fragment, str):
        return False
    s = fragment.strip()
    if len(s) < 2:
        return False
    names = _database_names(stockDB)
    return any(s in name for name in names)


# =========================================================================
# Public API
# =========================================================================


def _stocks_for_name(name: str) -> List[Stock]:
    """Resolve a known stock name to its Stock objects (code + name + market)."""
    return [
        Stock(code=code, name=name, market=market)
        for code, market in _find_codes_for_name(name, stockDB)
    ]


def extract_stock_name(text: str) -> List[Tuple[str, Optional[List[Stock]]]]:
    """Segment *text* into (fragment, stocks_or_none) pairs.

    Uses the global ``stockDB`` to identify stock names. Longer names are matched
    first to prevent partial matches (e.g. "贵州茅台" before "茅台").
    Each matched name is resolved to ``Stock`` objects via ``_find_codes_for_name``.

    Returns:
        List of ``(fragment, stocks_or_none)`` tuples.  *stocks_or_none* is a
        ``List[Stock]`` when the fragment was matched as a known stock name,
        ``None`` otherwise.
    """
    if not text or not isinstance(text, str):
        return []

    names = _database_names(stockDB)
    names_sorted = sorted(names, key=len, reverse=True)

    # Collect all non-overlapping matches with resolved Stock objects
    matches: List[Tuple[int, int, str, List[Stock]]] = []  # (start, end, name, stocks)

    for name in names_sorted:
        start = 0
        while True:
            idx = text.find(name, start)
            if idx < 0:
                break
            end = idx + len(name)
            if not any(
                m_start < end and idx < m_end
                for m_start, m_end, _, _ in matches
            ):
                matches.append((idx, end, name, _stocks_for_name(name)))
            start = idx + 1

    if not matches:
        return [(text, None)] if text else []

    matches.sort(key=lambda x: x[0])

    segments: List[Tuple[str, Optional[List[Stock]]]] = []
    pos = 0
    for start, end, name, stocks in matches:
        if start > pos:
            segments.append((text[pos:start], None))
        segments.append((name, stocks))
        pos = end
    if pos < len(text):
        segments.append((text[pos:], None))

    return segments


def resolver_name_to_code_list(name: str) -> List[Stock]:
    """Resolve a stock name to a list of matching ``Stock`` entries (max 5).

    Only processes pure Chinese names. The name is matched against the global
    ``stockDB`` via exact, substring, pinyin, and fuzzy matching.

    Results are sorted A-share → HK → US.

    Examples:
        "阿里巴巴"  → [Stock("09988", "阿里巴巴", "hk"), Stock("BABA", "阿里巴巴", "us")]
        "阿里"      → [Stock("09988", "阿里巴巴", "hk"), Stock("BABA", "阿里巴巴", "us")]
        "茅台"      → [Stock("600519", "贵州茅台", "a")]
        "你好世界"   → []
    """
    if not name or not isinstance(name, str):
        return []
    s = name.strip()
    if not s:
        return []
    # 单个汉字不可能是股票名称，直接短路避免后续无意义的查表
    if len(s) == 1 and '\u4e00' <= s <= '\u9fff':
        return []

    full_names = _fix_name(s, stockDB)
    if not full_names:
        return []

    results: List[Stock] = []
    seen: Set[str] = set()
    for full_name in full_names:
        for code, market in _find_codes_for_name(full_name, stockDB):
            if code in seen:
                continue
            seen.add(code)
            results.append(Stock(code=code, name=full_name, market=market))

    results.sort(key=lambda r: _MARKET_ORDER.get(r.market, 99))
    return results[:5]


def US_stock_code_match(segment: str) -> List[Stock]:
    """匹配美国股票代码：1~5 个大写英文字母组成的 ticker symbol。

    仅在股票数据库中存在对应代码时才返回结果，避免将普通英文单词误判为股票代码。
    返回 Stock 列表，market 固定为 "us"。
    """
    if not segment or not segment.isascii() or not segment.isalpha():
        return []
    if not (1 <= len(segment) <= 5):
        return []
    upper = segment.upper()
    name = stockDB.get(upper, "")
    if name:
        return [Stock(code=upper, name=name, market="us")]
    return []


# =========================================================================
# Single-code resolution — thin orchestration over the list resolver
# =========================================================================


def resolve_name_to_code(name: str) -> Optional[str]:
    """
    Resolve stock name to code.

    Strategy (in order):
    1. If input looks like a code (5-6 digits or 1-5 letters), return it normalized.
    2. Resolve via ``resolver_name_to_code_list`` against the current ``stockDB``.
       Any multi-candidate result (exact duplicate names, substring, pinyin,
       fuzzy matches, e.g. "阿里巴巴" -> BABA/09988 or "阿里" -> BABA/09988)
       returns None so callers ask the user to disambiguate. A singleton from
       an exact name match is trusted as-is; a singleton from substring/
       pinyin/fuzzy matching may be a local near-match, so it must first
       yield to an exact AkShare-only A-share name before being returned.
    3. Extend ``stockDB`` with AkShare A-share data (idempotent), then
       resolve again — ``_fix_name`` prefers the exact name, so an exact
       AkShare entry beats the local near-match; otherwise the local
       near-match singleton is kept.

    Args:
        name: Stock name or code string.

    Returns:
        Resolved stock code, or None if unresolved/ambiguous.
    """
    if not name or not isinstance(name, str):
        return None
    s = name.strip()
    if not s:
        return None

    # 1. Input looks like code
    if _is_code_like(s):
        return _normalize_code(s)

    # 2. List resolution against the current stockDB (local data first).
    stocks = resolver_name_to_code_list(s)
    if stocks:
        # 任何多候选结果（精确同名多市场、子串、拼音、模糊匹配）都是歧义：
        # 单代码入口绝不静默挑选排序后的第一只，返回 None 交由调用方澄清。
        # 此前仅拦截精确同名歧义，子串/拼音/模糊产生的多候选会直接落到
        # stocks[0].code，例如"阿里"→09988、"银行"→000001。
        if len(stocks) > 1:
            logger.debug(
                f"[NameResolver] 命中歧义名称（{len(stocks)} 个候选），返回 None: {s}"
            )
            return None
        singleton = stocks[0]
        # 本地非精确 singleton（子串/拼音/模糊命中）可能只是近似：本地库缺失、
        # AkShare 独有的精确 A 股名必须先于本地近似名胜出，否则会被解析到
        # 相近的本地股票（OR-COR-a2d5f6b9）。_fix_name 精确优先，扩展重解析
        # 后精确名自然置顶；AkShare 无精确名时维持本地近似结果（保留既有
        # 容错行为）。extend_AkShare() 返回 False 表示数据未变，无需重解析。
        if (
            not _is_exact_name_hit(s, singleton.name)
            and _contains_cjk(s)
            and extend_AkShare()
        ):
            retry = resolver_name_to_code_list(s)
            exact_hits = [st for st in retry if _is_exact_name_hit(s, st.name)]
            if len(exact_hits) == 1:
                return exact_hits[0].code
        return singleton.code

    # Non-CJK input can never be helped by AkShare A-share data (all Chinesenames); 
    # skip the fetch and the retry for random Latin free text.
    if not _contains_cjk(s):
        logger.debug(f"[NameResolver] Skip AkShare extension for non-CJK input: {s}")
        return None

    # 3. Extend the local DB with AkShare A-share data (idempotent)
    extend_AkShare()
    
    # 4. resolve again — the retry sees A-share names beyond the local map.
    stocks = resolver_name_to_code_list(s)
    if stocks:
        # 与本地解析一致的歧义契约：AkShare 扩展后出现多候选（如子串命中
        # 多只 A 股）同样返回 None，绝不静默取第一只。
        if len(stocks) > 1:
            logger.debug(
                f"[NameResolver] AkShare 扩展后仍歧义（{len(stocks)} 个候选），返回 None: {s}"
            )
            return None
        return stocks[0].code

    logger.debug(f"[NameResolver] 解析失败: {s}")
    return None
