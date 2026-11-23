# -*- coding: utf-8 -*-
"""
===================================
股票代码与名称映射
===================================

Shared stock code -> name mapping, used by analyzer, data_provider, and name_to_code_resolver.
"""

from __future__ import annotations

import re
from typing import Dict, Tuple

# Stock code -> name mapping (common stocks)
STOCK_NAME_MAP = {
    # === A-shares ===
    "600519": "贵州茅台",
    "000001": "平安银行",
    "300750": "宁德时代",
    "002594": "比亚迪",
    "600036": "招商银行",
    "601318": "中国平安",
    "000858": "五粮液",
    "600276": "恒瑞医药",
    "601012": "隆基绿能",
    "002475": "立讯精密",
    "300059": "东方财富",
    "002415": "海康威视",
    "600900": "长江电力",
    "601166": "兴业银行",
    "600028": "中国石化",
    "600030": "中信证券",
    "600031": "三一重工",
    "600050": "中国联通",
    "600104": "上汽集团",
    "600111": "北方稀土",
    "600150": "中国船舶",
    "600309": "万华化学",
    "600406": "国电南瑞",
    "600690": "海尔智家",
    "600760": "中航沈飞",
    "600809": "山西汾酒",
    "600887": "伊利股份",
    "600930": "华电新能",
    "601088": "中国神华",
    "601127": "赛力斯",
    "601211": "国泰海通",
    "601225": "陕西煤业",
    "601288": "农业银行",
    "601328": "交通银行",
    "601398": "工商银行",
    "601601": "中国太保",
    "601628": "中国人寿",
    "601658": "邮储银行",
    "601668": "中国建筑",
    "601728": "中国电信",
    "601816": "京沪高铁",
    "601857": "中国石油",
    "601888": "中国中免",
    "601899": "紫金矿业",
    "601919": "中远海控",
    "601985": "中国核电",
    "601988": "中国银行",
    "603019": "中科曙光",
    "603259": "药明康德",
    "603501": "豪威集团",
    "603993": "洛阳钼业",
    "688008": "澜起科技",
    "688012": "中微公司",
    "688041": "海光信息",
    "688111": "金山办公",
    "688256": "寒武纪",
    "688981": "中芯国际",
    # === US stocks ===
    "AAPL": "苹果",
    "TSLA": "特斯拉",
    "MSFT": "微软",
    "GOOGL": "谷歌A",
    "GOOG": "谷歌C",
    "AMZN": "亚马逊",
    "NVDA": "英伟达",
    "META": "Meta",
    "AMD": "AMD",
    "INTC": "英特尔",
    "BABA": "阿里巴巴",
    "PDD": "拼多多",
    "JD": "京东",
    "BIDU": "百度",
    "NIO": "蔚来",
    "XPEV": "小鹏汽车",
    "LI": "理想汽车",
    "COIN": "Coinbase",
    "MSTR": "MicroStrategy",
    # === HK stocks (5-digit) ===
    "00700": "腾讯控股",
    "03690": "美团",
    "01810": "小米集团",
    "09988": "阿里巴巴",
    "09618": "京东集团",
    "09888": "百度集团",
    "01024": "快手",
    "00981": "中芯国际",
    "02015": "理想汽车",
    "09868": "小鹏汽车",
    "00005": "汇丰控股",
    "01299": "友邦保险",
    "00941": "中国移动",
    "00883": "中国海洋石油",
}


# ---------------------------------------------------------------------------
# Foreign-ticker English identity map (sibling of STOCK_NAME_MAP)
# ---------------------------------------------------------------------------
# Issue #2026: when STOCK_NAME_MAP maps a US/HK ticker to a Chinese display
# name (e.g. AAPL -> 苹果), ``SearchService._company_identity_terms`` cannot
# derive an English alias from that Chinese name, so English news headlines
# like "Apple reports earnings beat" never score as ``direct_company_news``.
#
# This map is the single source of truth for the English company identity
# (legal name + common media short form) of every foreign ticker currently
# mapped to Chinese by STOCK_NAME_MAP. The alias list per ticker is a tuple,
# ordered from most-specific (legal name) to least-specific (media short name)
# so callers can pick the granularity they need.
#
# Constraint (enforced by the assert below): the keys of this map are a subset
# of the foreign-ticker keys of STOCK_NAME_MAP. Adding an English alias for a
# ticker requires the ticker to already exist in STOCK_NAME_MAP, so the two
# maps cannot drift — exactly the single-source-of-truth property demanded by
# issue #2026 ("alias 来源建议不要再复制一份静态映射").
#
# Note: tickers map to a *tuple* of English names rather than a single legal
# name. ``_company_identity_terms`` only strips one legal suffix layer, so it
# cannot synthesise the common media short names ("Apple", "Amazon", "Google",
# "Alibaba", "Tencent", "Pinduoduo", "Xiaomi", ...) that journalists actually
# use in headlines. Encoding those short names explicitly here is the contract
# massif-01 asked for on PR #2047 ("将搜索 identity 建模为真实 alias 集, 不要
# 继续给 suffix stripping 堆启发式规则").
STOCK_ENGLISH_NAME_MAP: Dict[str, Tuple[str, ...]] = {
    # === US stocks ===
    "AAPL": ("Apple Inc.", "Apple"),
    "TSLA": ("Tesla, Inc.", "Tesla"),
    "MSFT": ("Microsoft Corporation", "Microsoft"),
    "GOOGL": ("Alphabet Inc.", "Google"),
    "GOOG": ("Alphabet Inc.", "Google"),
    "AMZN": ("Amazon.com, Inc.", "Amazon"),
    "NVDA": ("NVIDIA Corporation", "NVIDIA"),
    "META": ("Meta Platforms, Inc.", "Meta"),
    "AMD": ("Advanced Micro Devices, Inc.", "AMD"),
    "INTC": ("Intel Corporation", "Intel"),
    "BABA": ("Alibaba Group Holding Limited", "Alibaba"),
    "PDD": ("PDD Holdings Inc.", "Pinduoduo"),
    "JD": ("JD.com, Inc.", "JD.com"),
    "BIDU": ("Baidu, Inc.", "Baidu"),
    "NIO": ("NIO Inc.", "NIO"),
    "XPEV": ("XPeng Inc.", "XPeng"),
    "LI": ("Li Auto Inc.", "Li Auto"),
    "COIN": ("Coinbase Global, Inc.", "Coinbase"),
    "MSTR": ("MicroStrategy Incorporated", "MicroStrategy"),
    # === HK stocks (5-digit) ===
    "00700": ("Tencent Holdings", "Tencent"),
    "03690": ("Meituan",),
    "01810": ("Xiaomi Corporation", "Xiaomi"),
    "09988": ("Alibaba Group Holding", "Alibaba"),
    "09618": ("JD.com",),
    "09888": ("Baidu Inc.", "Baidu"),
    "01024": ("Kuaishou Technology", "Kuaishou"),
    "00981": ("SMIC",),
    "02015": ("Li Auto Inc.", "Li Auto"),
    "09868": ("XPeng Inc.", "XPeng"),
    "00005": ("HSBC Holdings", "HSBC"),
    "01299": ("AIA Group", "AIA"),
    "00941": ("China Mobile",),
    "00883": ("CNOOC",),
}


def _assert_foreign_english_map_invariant() -> None:
    """Verify STOCK_ENGLISH_NAME_MAP keys ⊆ foreign-ticker keys of STOCK_NAME_MAP."""
    foreign_keys_in_name_map = {
        code for code in STOCK_NAME_MAP
        if not (code.isdigit() and len(code) == 6)  # exclude A-shares
    }
    english_keys = set(STOCK_ENGLISH_NAME_MAP)
    extra = english_keys - foreign_keys_in_name_map
    missing = foreign_keys_in_name_map - english_keys
    if extra or missing:
        raise AssertionError(
            f"STOCK_ENGLISH_NAME_MAP drift detected: "
            f"extra={sorted(extra)}, missing={sorted(missing)}; "
            f"every foreign-ticker key in STOCK_NAME_MAP must have an English "
            f"alias entry here, and no foreign English entry may target a "
            f"ticker absent from STOCK_NAME_MAP."
        )


_assert_foreign_english_map_invariant()


def canonicalize_foreign_stock_code(stock_code: str) -> str:
    """Canonicalize a foreign ticker to the form used as keys in
    STOCK_NAME_MAP / STOCK_ENGLISH_NAME_MAP.

    Single canonical boundary for ``bare`` / ``prefix`` / ``suffix`` forms:

        ``AAPL``        -> ``AAPL``
        ``AAPL.US``     -> ``AAPL``
        ``AAPL.N``      -> ``AAPL``   (NYSE suffix)
        ``AAPL.O``      -> ``AAPL``   (NASDAQ suffix)
        ``00700``       -> ``00700``
        ``00700.HK``    -> ``00700``
        ``HK00700``     -> ``00700``

    A-share codes (``600519``, ``600519.SH``) and unknown forms return the
    uppercased stripped input unchanged. Callers that need to detect
    foreign-ness should call ``SearchService._is_foreign_stock`` (which now
    honours prefix/suffix forms) or check membership of the returned canonical
    key against STOCK_ENGLISH_NAME_MAP.
    """
    code = (stock_code or "").strip().upper()
    if not code:
        return ""
    # US exchange suffixes: .US / .N (NYSE) / .O (NASDAQ) / .A (AMEX)
    for suffix in (".US", ".N", ".O", ".A"):
        if code.endswith(suffix):
            return code[: -len(suffix)]
    # HK prefix: ``HK00700`` (7 chars: HK + 5 digits)
    if code.startswith("HK") and len(code) == 7 and code[2:].isdigit():
        return code[2:]
    # HK suffix: ``00700.HK``
    if code.endswith(".HK") and code[: -len(".HK")].isdigit():
        return code[: -len(".HK")]
    return code


def foreign_stock_english_aliases(stock_code: str, stock_name: str) -> Tuple[str, ...]:
    """Return English identity aliases for a foreign ticker whose
    pipeline-supplied ``stock_name`` (from STOCK_NAME_MAP) is Chinese.

    Returns an empty tuple when:
      * the stock code is not a foreign ticker covered by STOCK_ENGLISH_NAME_MAP
        (after canonicalization), or
      * the supplied ``stock_name`` is already English (no CJK chars), which
        means the data layer already returned an English display name and the
        search layer has no alias work to do.

    Keeping the alias source in ``stock_mapping`` (rather than as a private
    constant in ``SearchService``) means the data layer, the analyzer, and the
    search layer all share one foreign English-alias contract — the single
    source of truth requested in issue #2026.
    """
    raw_name = (stock_name or "").strip()
    if not raw_name:
        return ()
    # If the supplied name is already English (no CJK), no alias is needed.
    if not _CONTAINS_CJK_RE.search(raw_name):
        return ()
    canonical = canonicalize_foreign_stock_code(stock_code)
    if not canonical:
        return ()
    aliases = STOCK_ENGLISH_NAME_MAP.get(canonical)
    return tuple(aliases) if aliases else ()


_CONTAINS_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def is_meaningful_stock_name(name: str | None, stock_code: str) -> bool:
    """Return whether a stock name is useful for display or caching."""
    if not name:
        return False

    normalized_name = str(name).strip()
    if not normalized_name:
        return False

    normalized_code = (stock_code or "").strip().upper()
    if normalized_name.upper() == normalized_code:
        return False

    if normalized_name.startswith("股票"):
        return False

    placeholder_values = {
        "N/A",
        "NA",
        "NONE",
        "NULL",
        "--",
        "-",
        "UNKNOWN",
        "TICKER",
    }
    if normalized_name.upper() in placeholder_values:
        return False

    return True
