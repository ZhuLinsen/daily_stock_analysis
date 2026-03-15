# -*- coding: utf-8 -*-
"""
===================================
名称→代码解析引擎
===================================

Resolve stock name to code: local mapping + pinyin + AkShare fallback + fuzzy matching.
"""

from __future__ import annotations

import difflib
import logging
import time
from typing import Dict, Optional, Set

from src.data.stock_mapping import STOCK_NAME_MAP
from src.services.stock_code_utils import is_code_like, normalize_code

logger = logging.getLogger(__name__)

# AkShare result cache: (timestamp, name_to_code_dict)
_akshare_cache: Optional[tuple[float, Dict[str, str]]] = None
_AKSHARE_CACHE_TTL = 3600  # 1 hour


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


def resolve_name_to_code(name: str) -> Optional[str]:
    """
    Resolve stock name to code.

    Strategy (in order):
    1. If input looks like a code (5-6 digits or 1-5 letters), return it normalized.
    2. Local STOCK_NAME_MAP reverse (exclude ambiguous names).
    3. Pinyin match against local names.
    4. AkShare online fallback (A-shares).
    5. Fuzzy match (difflib).
    6. Return None.

    Args:
        name: Stock name or code string.

    Returns:
        Resolved stock code, or None if ambiguous/failed.
    """
    if not name or not isinstance(name, str):
        return None
    s = name.strip()
    if not s:
        return None

    # 1. Input looks like code
    if _is_code_like(s):
        return _normalize_code(s)

    # 2. Local reverse map (no duplicates)
    local_reverse = _build_reverse_map_no_duplicates(STOCK_NAME_MAP)
    if s in local_reverse:
        return local_reverse[s]

    # 3. Pinyin match (exact)
    try:
        from pypinyin import lazy_pinyin

        input_pinyin = "".join(lazy_pinyin(s)).lower()
        for local_name, code in local_reverse.items():
            local_pinyin = "".join(lazy_pinyin(local_name)).lower()
            if input_pinyin == local_pinyin:
                return code
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[NameResolver] Pinyin match failed: {e}")

    # 4. AkShare fallback
    akshare_map = _get_akshare_name_to_code()
    if akshare_map and s in akshare_map:
        logger.debug(f"[NameResolver] 命中 AkShare 映射: {s} -> {akshare_map[s]}")
        return akshare_map[s]

    # 5. Fuzzy match (local + akshare, local takes precedence)
    all_name_to_code = dict(local_reverse)
    if akshare_map:
        all_name_to_code.update(akshare_map)
    # Skip fuzzy matching for very short inputs (<=2 chars) to avoid false positives,
    # e.g. '中国' matching arbitrary company names in a pool of 5000+ stocks.
    # Use a higher cutoff (0.8) to reduce mis-hits on longer inputs as well.
    if len(s) > 2:
        matches = difflib.get_close_matches(s, list(all_name_to_code.keys()), n=1, cutoff=0.8)
        if matches:
            logger.debug(f"[NameResolver] 命中模糊匹配: input={s}, matched={matches[0]}")
            return all_name_to_code[matches[0]]

    logger.debug(f"[NameResolver] 解析失败: {s}")
    return None
