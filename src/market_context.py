# -*- coding: utf-8 -*-
"""
Market context detection for LLM prompts.

Detects the market (A-shares, HK, US) from a stock code and returns
market-specific role descriptions so prompts are not hardcoded to a
single market.

Fixes: https://github.com/ZhuLinsen/daily_stock_analysis/issues/644
"""

import re
from typing import Optional


def detect_market(stock_code: Optional[str]) -> str:
    """Detect market from stock code.

    Returns:
        One of 'cn', 'hk', 'us', or 'cn' as fallback.
    """
    if not stock_code:
        return "cn"

    code = stock_code.strip().upper()

    # HK stocks: HK00700, 00700.HK, or 5-digit pure numbers
    if code.startswith("HK") or code.endswith(".HK"):
        return "hk"
    lower = code.lower()
    if lower.endswith(".hk"):
        return "hk"
    # 5-digit pure numbers are HK (A-shares are 6-digit)
    if code.isdigit() and len(code) == 5:
        return "hk"

    # Japan/Korea suffix-only symbols supported by Yahoo Finance.
    # Bare Korean six-digit codes remain A-share fallback to avoid collision.
    if re.match(r'^\d{4,5}\.T$', code):
        return "jp"
    if re.match(r'^\d{6}\.(KS|KQ)$', code):
        return "kr"

    # Taiwan suffix-only symbols supported by Yahoo Finance (TWSE `.TW`, TPEx `.TWO`).
    # Base is 4-6 digits (common stocks 4, ETFs/others up to 6, e.g. 00878, 006208).
    # Bare 4-digit codes remain A-share fallback to avoid collision; only the
    # explicit `.TW`/`.TWO` suffix opts a code into the Taiwan market.
    if re.match(r'^\d{4,6}\.TWO$', code):
        return "tw"
    if re.match(r'^\d{4,6}\.TW$', code):
        return "tw"

    # US stocks: 1-5 uppercase letters (AAPL, TSLA, GOOGL)
    # Also handles suffixed forms like BRK.B
    if re.match(r'^[A-Z]{1,5}(\.[A-Z]{1,2})?$', code):
        return "us"

    # Default: A-shares (6-digit numbers like 600519, 000001)
    return "cn"


# -- Market-specific role descriptions --

_MARKET_ROLES = {
    "cn": {
        "zh": " A 股",
        "en": "China A-shares",
    },
    "hk": {
        "zh": "港股",
        "en": "Hong Kong stock",
    },
    "us": {
        "zh": "美股",
        "en": "US stock",
    },
    "jp": {
        "zh": "日股",
        "en": "Japan stock",
    },
    "kr": {
        "zh": "韩股",
        "en": "Korea stock",
    },
    "tw": {
        "zh": "台股",
        "en": "Taiwan stock",
    },
}

_MARKET_GUIDELINES = {
    "cn": {
        "zh": (
            "- 本次分析对象为 **A 股**（中国沪深交易所上市股票）。\n"
            "- 请关注 A 股特有的涨跌停机制（±10%/±20%/±30%）、T+1 交易制度及相关政策因素。"
        ),
        "en": (
            "- This analysis covers a **China A-share** (listed on Shanghai/Shenzhen exchanges).\n"
            "- Consider A-share-specific rules: daily price limits (±10%/±20%/±30%), T+1 settlement, and PRC policy factors."
        ),
    },
    "hk": {
        "zh": (
            "- 本次分析对象为 **港股**（香港交易所上市股票）。\n"
            "- 港股无涨跌停限制，支持 T+0 交易，需关注港币汇率、南北向资金流及联交所特有规则。"
        ),
        "en": (
            "- This analysis covers a **Hong Kong stock** (listed on HKEX).\n"
            "- HK stocks have no daily price limits, allow T+0 trading. Consider HKD FX, Southbound/Northbound flows, and HKEX-specific rules."
        ),
    },
    "us": {
        "zh": (
            "- 本次分析对象为 **美股**（美国交易所上市股票）。\n"
            "- 美股无涨跌停限制（但有熔断机制），支持 T+0 交易和盘前盘后交易，需关注美元汇率、美联储政策及 SEC 监管动态。"
        ),
        "en": (
            "- This analysis covers a **US stock** (listed on NYSE/NASDAQ).\n"
            "- US stocks have no daily price limits (but have circuit breakers), allow T+0 and pre/after-market trading. Consider USD FX, Fed policy, and SEC regulations."
        ),
    },
    "jp": {
        "zh": (
            "- 本次分析对象为 **日股**（日本交易所上市股票，Yahoo Finance suffix 如 `.T`）。\n"
            "- 请按日本市场语境分析，关注日元汇率、日本央行政策、公司治理与行业周期；不要套用 A 股涨跌停、北向资金、龙虎榜、融资融券等 A 股专属概念。"
        ),
        "en": (
            "- This analysis covers a **Japan stock** (Yahoo Finance suffix such as `.T`).\n"
            "- Use Japan-market context: JPY FX, BOJ policy, corporate governance, and sector cycles; do not apply China A-share concepts such as daily price-limit boards, Northbound flows, Dragon Tiger lists, or margin-financing narratives."
        ),
    },
    "kr": {
        "zh": (
            "- 本次分析对象为 **韩股**（韩国交易所/KOSDAQ 上市股票，必须带 `.KS` / `.KQ` 后缀）。\n"
            "- 请按韩国市场语境分析，关注韩元汇率、韩国央行政策、半导体/互联网产业周期与韩国交易制度；不要套用 A 股涨跌停、北向资金、龙虎榜、融资融券等 A 股专属概念。"
        ),
        "en": (
            "- This analysis covers a **Korea stock** (KOSPI/KOSDAQ suffix `.KS` / `.KQ`).\n"
            "- Use Korea-market context: KRW FX, Bank of Korea policy, semiconductor/internet cycles, and local trading rules; do not apply China A-share concepts such as daily price-limit boards, Northbound flows, Dragon Tiger lists, or margin-financing narratives."
        ),
    },
    "tw": {
        "zh": (
            "- 本次分析对象为 **台股**（台湾证券交易所上市 `.TW`，或台湾柜买中心上柜 `.TWO`）。\n"
            "- 请按台湾市场语境分析，关注新台币（TWD）汇率、台湾央行政策、半导体/电子代工产业链、"
            "三大法人（外资／投信／自营商）买卖超、融资融券与当冲，以及 TWSE/TPEx ±10% 涨跌停制度；"
            "不要套用 A 股专属的北向资金、龙虎榜等概念（台股的法人结构与资金流口径与 A 股不同）。"
        ),
        "en": (
            "- This analysis covers a **Taiwan stock** (TWSE-listed `.TW`, or TPEx/OTC `.TWO`).\n"
            "- Use Taiwan-market context: TWD FX, Central Bank of the ROC policy, the semiconductor/"
            "electronics-foundry supply chain, the three institutional investor groups (foreign / "
            "investment-trust / dealer), margin trading and day trading, and the TWSE/TPEx ±10% daily "
            "price limit; do not apply China A-share-specific concepts such as Northbound flows or Dragon Tiger lists."
        ),
    },
}


def get_market_role(stock_code: Optional[str], lang: str = "zh") -> str:
    """Return market-specific role description for LLM prompt.

    Args:
        stock_code: The stock code being analyzed.
        lang: 'zh' or 'en'.

    Returns:
        Role string like 'A 股投资分析' or 'US stock investment analysis'.
    """
    market = detect_market(stock_code)
    lang_key = "en" if lang == "en" else "zh"
    return _MARKET_ROLES.get(market, _MARKET_ROLES["cn"])[lang_key]


def get_market_guidelines(stock_code: Optional[str], lang: str = "zh") -> str:
    """Return market-specific analysis guidelines for LLM prompt.

    Args:
        stock_code: The stock code being analyzed.
        lang: 'zh' or 'en'.

    Returns:
        Multi-line string with market-specific guidelines.
    """
    market = detect_market(stock_code)
    lang_key = "en" if lang == "en" else "zh"
    return _MARKET_GUIDELINES.get(market, _MARKET_GUIDELINES["cn"])[lang_key]
