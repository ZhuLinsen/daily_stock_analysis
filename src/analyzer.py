# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - AI分析层
===================================
"""
import os
import requests
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple, Callable
import litellm
from json_repair import repair_json
from litellm import Router

# 从你本地现有的文件里安全导入
from src.config import (
    Config,
    extra_litellm_params,
    get_api_keys_for_model,
    get_config,
)
from src.report_language import (
    get_unknown_text,
    get_chip_unavailable_text,
    infer_decision_type_from_advice,
    is_chip_placeholder_value,
    localize_chip_health,
    localize_confidence_level,
    normalize_report_language
)

# 核心交易策略
CORE_TRADING_SKILL_POLICY_ZH = """
你是一个资深美股交易专家。在分析个股时，必须严格执行以下三条底线原则：
1. **防守第一**：任何时候，首要任务是识别潜在风险，防范重大亏损，而不仅仅是寻找上涨机会。
2. **趋势为主**：顺应市场的大趋势和个股的中期趋势，绝不盲目逆势操作。
3. **分批建仓，分批止盈**：在买入时必须分批建仓，严格执行止损线；在实现盈利时分批止盈，锁定利润，绝不贪婪。
"""

def get_stock_sentiment(ticker: str) -> str:
    """从 Alpha Vantage 获取个股最新的网络舆情与情绪得分"""
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        return ""

    url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&apikey={api_key}"

    try:
        response = requests.get(url).json()
        feed = response.get("feed", [])
        if not feed:
            return f"\n### {ticker} 暂无近期网络舆情"

        sentiment_summary = [f"\n### {ticker} 舆情风向标："]
        for item in feed[:3]:
            title = item.get("title")
            ticker_data = item.get("ticker_sentiment", [])
            label = "Neutral"
            for t in ticker_data:
                if t.get("ticker").upper() == ticker.upper():
                    label = t.get("ticker_sentiment_label")
                    break
            sentiment_summary.append(f"- 【{label}】{title}")

        return "\n".join(sentiment_summary)
    except Exception:
        return ""

@dataclass
class AnalysisResult:
    ticker: str
    decision: str     # BUY, SELL, HOLD
    confidence: str   # HIGH, MEDIUM, LOW
    analysis: str     # 具体的分析内容

def fill_price_position_if_needed(target_pct: float, current_price: float, current_position_pct: float) -> str:
    """根据目标仓位和当前仓位计算操作逻辑，防止报错"""
    if target_pct > current_position_pct:
        return f"建议在 {current_price} 附近逢低买入，目标建仓至 {target_pct}%"
    elif target_pct < current_position_pct:
        return f"建议在 {current_price} 附近逢高减仓，目标降至 {target_pct}%"
    return "维持现有仓位不变"

def normalize_chip_structure_availability(chip_data: Optional[Dict[str, Any]] = None) -> bool:
    if not chip_data:
        return False
    return not is_chip_placeholder_value(chip_data.get("winner_ratio"))

def localize_chip_structure(chip_data: Optional[Dict[str, Any]] = None, language: str = "zh") -> str:
    if not normalize_chip_structure_availability(chip_data):
        return get_chip_unavailable_text(language)
    winner_ratio = chip_data.get("winner_ratio", 0)
    return f"获利盘比例: {winner_ratio * 100:.2f}%"

class GeminiAnalyzer:
    def __init__(self, provider: str = "gemini"):
        self.provider = provider

    def analyze(self, ticker: str, data: dict) -> AnalysisResult:
        sentiment_info = get_stock_sentiment(ticker)
        analysis_text = f"针对 {ticker} 的数据进行分析..."
        if sentiment_info:
            analysis_text += f"\n{sentiment_info}"
        
        return AnalysisResult(
            ticker=ticker,
            decision="HOLD",
            confidence="MEDIUM",
            analysis=analysis_text
        )
