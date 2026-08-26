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

from src.services.market_symbol_utils import get_suffix_market


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

    # Suffix-only Yahoo symbols for JP/KR/TW. Bare Korean/Taiwan numeric
    # codes keep existing fallback semantics to avoid cross-market collisions.
    suffix_market = get_suffix_market(code)
    if suffix_market:
        return suffix_market

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
        "ko": "중국 A주",
    },
    "hk": {
        "zh": "港股",
        "en": "Hong Kong stock",
        "ko": "홍콩 주식",
    },
    "us": {
        "zh": "美股",
        "en": "US stock",
        "ko": "미국 주식",
    },
    "jp": {
        "zh": "日股",
        "en": "Japan stock",
        "ko": "일본 주식",
    },
    "kr": {
        "zh": "韩股",
        "en": "Korea stock",
        "ko": "한국 주식",
    },
    "tw": {
        "zh": "台股",
        "en": "Taiwan stock",
        "ko": "대만 주식",
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
        "ko": (
            "- 이번 분석 대상은 **중국 A주**(상하이·선전 거래소 상장 종목)입니다.\n"
            "- A주 고유의 일일 가격제한(±10%/±20%/±30%), T+1 결제, 중국 정책 요인을 고려하세요."
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
        "ko": (
            "- 이번 분석 대상은 **홍콩 주식**(HKEX 상장 종목)입니다.\n"
            "- 홍콩 주식은 일일 가격제한이 없고 T+0 거래가 가능합니다. HKD 환율, 남·북향 자금 흐름, HKEX 고유 규정을 고려하세요."
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
        "ko": (
            "- 이번 분석 대상은 **미국 주식**(NYSE/NASDAQ 상장 종목)입니다.\n"
            "- 미국 주식은 가격제한은 없지만 서킷브레이커가 있으며 T+0·장전·시간외 거래가 가능합니다. USD 환율, 연준 정책, SEC 규정을 고려하세요."
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
        "ko": (
            "- 이번 분석 대상은 **일본 주식**(Yahoo Finance 접미사 예: `.T`)입니다.\n"
            "- JPY 환율, 일본은행 정책, 기업지배구조, 업종 사이클을 반영하세요. 중국 A주의 가격제한, 북향자금, 용호방, 신용거래 같은 개념은 적용하지 마세요."
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
        "ko": (
            "- 이번 분석 대상은 **한국 주식**(KOSPI/KOSDAQ, 접미사 `.KS` / `.KQ`)입니다.\n"
            "- KRW 환율, 한국은행 정책, 반도체·인터넷 업종 사이클, 국내 거래 규정을 반영하세요. 중국 A주의 가격제한, 북향자금, 용호방, 신용거래 같은 개념은 적용하지 마세요."
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
        "ko": (
            "- 이번 분석 대상은 **대만 주식**(TWSE 상장 `.TW` 또는 TPEx/OTC `.TWO`)입니다.\n"
            "- TWD 환율, 대만 중앙은행 정책, 반도체·전자 위탁생산 공급망, 외국인·투신·딜러의 3대 기관 흐름, 신용·당일매매, TWSE/TPEx ±10% 가격제한을 고려하세요. 중국 A주 전용 북향자금·용호방 개념은 적용하지 마세요."
        ),
    },
}


def get_market_role(stock_code: Optional[str], lang: str = "zh") -> str:
    """Return market-specific role description for LLM prompt.

    Args:
        stock_code: The stock code being analyzed.
        lang: 'zh', 'en', or 'ko'.

    Returns:
        Role string like 'A 股投资分析' or 'US stock investment analysis'.
    """
    market = detect_market(stock_code)
    lang_key = lang if lang in ("zh", "en", "ko") else "zh"
    return _MARKET_ROLES.get(market, _MARKET_ROLES["cn"])[lang_key]


def get_market_guidelines(stock_code: Optional[str], lang: str = "zh") -> str:
    """Return market-specific analysis guidelines for LLM prompt.

    Args:
        stock_code: The stock code being analyzed.
        lang: 'zh', 'en', or 'ko'.

    Returns:
        Multi-line string with market-specific guidelines.
    """
    market = detect_market(stock_code)
    lang_key = lang if lang in ("zh", "en", "ko") else "zh"
    return _MARKET_GUIDELINES.get(market, _MARKET_GUIDELINES["cn"])[lang_key]
