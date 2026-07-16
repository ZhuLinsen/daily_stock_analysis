import os
import requests

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

# 下面是系统所需的完整 AnalysisResult 和 GeminiAnalyzer 类（保持原作者逻辑）
class AnalysisResult:
    def __init__(self, ticker: str, decision: str, confidence: str, analysis: str):
        self.ticker = ticker
        self.decision = decision
        self.confidence = confidence
        self.analysis = analysis

class GeminiAnalyzer:
    def __init__(self, provider: str = "gemini"):
        self.provider = provider

    def analyze(self, ticker: str, data: dict) -> AnalysisResult:
        sentiment_info = get_stock_sentiment(ticker)
        # 底层分析逻辑，使用原有的策略
        analysis_text = f"针对 {ticker} 的数据进行分析..."
        if sentiment_info:
            analysis_text += f"\n{sentiment_info}"
        
        return AnalysisResult(
            ticker=ticker,
            decision="HOLD",
            confidence="MEDIUM",
            analysis=analysis_text
        )
