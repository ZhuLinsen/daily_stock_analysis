# -*- coding: utf-8 -*-
"""
Data tools — wraps DataFetcherManager methods as agent-callable tools.

Tools:
- get_realtime_quote: real-time stock quote
- get_daily_history: historical OHLCV data
- get_chip_distribution: chip distribution analysis
- get_analysis_context: historical analysis context from DB
"""

import json
import logging
from typing import Optional

from src.agent.tools.registry import ToolParameter, ToolDefinition

logger = logging.getLogger(__name__)


def _get_fetcher_manager():
    """Lazy import to avoid circular deps."""
    from data_provider import DataFetcherManager
    return DataFetcherManager()


def _get_db():
    """Lazy import for DatabaseManager."""
    from src.storage import get_db
    return get_db()


# ============================================================
# get_realtime_quote
# ============================================================

def _handle_get_realtime_quote(stock_code: str) -> dict:
    """Get real-time stock quote."""
    manager = _get_fetcher_manager()
    quote = manager.get_realtime_quote(stock_code)
    if quote is None:
        return {"error": f"No realtime quote available for {stock_code}"}

    return {
        "code": quote.code,
        "name": quote.name,
        "price": quote.price,
        "change_pct": quote.change_pct,
        "change_amount": quote.change_amount,
        "volume": quote.volume,
        "amount": quote.amount,
        "volume_ratio": quote.volume_ratio,
        "turnover_rate": quote.turnover_rate,
        "amplitude": quote.amplitude,
        "open": quote.open_price,
        "high": quote.high,
        "low": quote.low,
        "pre_close": quote.pre_close,
        "pe_ratio": quote.pe_ratio,
        "pb_ratio": quote.pb_ratio,
        "total_mv": quote.total_mv,
        "circ_mv": quote.circ_mv,
        "change_60d": quote.change_60d,
        "source": quote.source.value if hasattr(quote.source, 'value') else str(quote.source),
    }


get_realtime_quote_tool = ToolDefinition(
    name="get_realtime_quote",
    description="Get real-time stock quote including price, change%, volume ratio, "
                "turnover rate, PE, PB, market cap. Returns live market data.",
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="Stock code, e.g., '600519' (A-share), 'AAPL' (US), 'hk00700' (HK)",
        ),
    ],
    handler=_handle_get_realtime_quote,
    category="data",
)


# ============================================================
# get_daily_history
# ============================================================

def _handle_get_daily_history(stock_code: str, days: int = 60) -> dict:
    """Get daily OHLCV history data."""
    manager = _get_fetcher_manager()
    df, source = manager.get_daily_data(stock_code, days=days)

    if df is None or df.empty:
        return {"error": f"No historical data available for {stock_code}"}

    # Convert DataFrame to list of dicts (last N records)
    records = df.tail(min(days, len(df))).to_dict(orient="records")
    # Ensure date is string
    for r in records:
        if "date" in r:
            r["date"] = str(r["date"])

    return {
        "code": stock_code,
        "source": source,
        "total_records": len(records),
        "data": records,
    }


get_daily_history_tool = ToolDefinition(
    name="get_daily_history",
    description="Get daily OHLCV (open, high, low, close, volume) historical data "
                "with MA5/MA10/MA20 indicators. Returns the last N trading days.",
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="Stock code, e.g., '600519' (A-share), 'AAPL' (US)",
        ),
        ToolParameter(
            name="days",
            type="integer",
            description="Number of trading days to fetch (default: 60)",
            required=False,
            default=60,
        ),
    ],
    handler=_handle_get_daily_history,
    category="data",
)


# ============================================================
# get_chip_distribution
# ============================================================

def _handle_get_chip_distribution(stock_code: str) -> dict:
    """Get chip distribution data."""
    manager = _get_fetcher_manager()
    chip = manager.get_chip_distribution(stock_code)

    if chip is None:
        return {"error": f"No chip distribution data available for {stock_code}"}

    return {
        "code": chip.code,
        "date": chip.date,
        "source": chip.source,
        "profit_ratio": chip.profit_ratio,
        "avg_cost": chip.avg_cost,
        "cost_90_low": chip.cost_90_low,
        "cost_90_high": chip.cost_90_high,
        "concentration_90": chip.concentration_90,
        "cost_70_low": chip.cost_70_low,
        "cost_70_high": chip.cost_70_high,
        "concentration_70": chip.concentration_70,
    }


get_chip_distribution_tool = ToolDefinition(
    name="get_chip_distribution",
    description="Get chip distribution analysis for a stock. Returns profit ratio, "
                "average cost, chip concentration at 90% and 70% levels. "
                "Useful for judging support/resistance and holding structure.",
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="A-share stock code, e.g., '600519'",
        ),
    ],
    handler=_handle_get_chip_distribution,
    category="data",
)


# ============================================================
# get_analysis_context
# ============================================================

def _handle_get_analysis_context(stock_code: str) -> dict:
    """Get stored analysis context from database."""
    db = _get_db()
    context = db.get_analysis_context(stock_code)

    if context is None:
        return {"error": f"No analysis context in DB for {stock_code}"}

    # Return safely serializable version (remove raw_data to save tokens)
    safe_context = {}
    for k, v in context.items():
        if k == "raw_data":
            safe_context["has_raw_data"] = True
            safe_context["raw_data_count"] = len(v) if isinstance(v, list) else 0
        else:
            safe_context[k] = v

    return safe_context


get_analysis_context_tool = ToolDefinition(
    name="get_analysis_context",
    description="Get historical analysis context from the database for a stock. "
                "Returns today's and yesterday's OHLCV data, MA alignment status, "
                "volume and price changes. Provides the technical data foundation.",
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="Stock code, e.g., '600519'",
        ),
    ],
    handler=_handle_get_analysis_context,
    category="data",
)


# ============================================================
# get_stock_info
# ============================================================

def _handle_get_stock_info(stock_code: str) -> dict:
    """Get stock fundamental information including industry, financials, and valuation."""
    # Try EfinanceFetcher.get_base_info first (most complete)
    try:
        from data_provider.efinance_fetcher import EfinanceFetcher
        fetcher = EfinanceFetcher()
        info = fetcher.get_base_info(stock_code)
        if info:
            # Sanitise: convert non-serialisable types and remove NaN
            import math
            clean: dict = {}
            for k, v in info.items():
                if isinstance(v, float) and math.isnan(v):
                    clean[k] = None
                else:
                    try:
                        import json as _json
                        _json.dumps(v)       # test serialisability
                        clean[k] = v
                    except (TypeError, ValueError):
                        clean[k] = str(v)

            # Also try to get board/sector membership
            try:
                board_df = fetcher.get_belong_board(stock_code)
                if board_df is not None and not board_df.empty:
                    # Typically columns: 板块名称, 板块代码, 涨跌幅, …
                    boards = board_df.to_dict(orient="records")
                    # Keep only name + change columns to limit token usage
                    clean["belong_boards"] = [
                        {k2: (str(v2) if not isinstance(v2, (int, float, str, type(None))) else v2)
                         for k2, v2 in row.items()
                         if any(kw in str(k2) for kw in ["名称", "代码", "涨跌", "板块"])}
                        for row in boards[:10]
                    ]
            except Exception:
                pass

            return clean
    except Exception as e:
        logger.warning(f"get_stock_info via EfinanceFetcher failed for {stock_code}: {e}")

    # Fallback: derive from realtime quote (valuation metrics only)
    manager = _get_fetcher_manager()
    quote = manager.get_realtime_quote(stock_code)
    if quote:
        return {
            "code": quote.code,
            "name": quote.name,
            "pe_ratio": quote.pe_ratio,
            "pb_ratio": quote.pb_ratio,
            "total_mv": quote.total_mv,
            "circ_mv": quote.circ_mv,
            "note": "Basic info only — EfinanceFetcher unavailable",
        }
    return {"error": f"Unable to fetch stock info for {stock_code}"}


get_stock_info_tool = ToolDefinition(
    name="get_stock_info",
    description="Get stock fundamental information: industry classification, ROE, net profit margin, "
                "PE ratio, PB ratio, revenue, earnings, market cap, and sector membership. "
                "Best for fundamental analysis and background research on a stock.",
    parameters=[
        ToolParameter(
            name="stock_code",
            type="string",
            description="A-share stock code, e.g., '600519'",
        ),
    ],
    handler=_handle_get_stock_info,
    category="data",
)


# ============================================================
# Export all data tools
# ============================================================

ALL_DATA_TOOLS = [
    get_realtime_quote_tool,
    get_daily_history_tool,
    get_chip_distribution_tool,
    get_analysis_context_tool,
    get_stock_info_tool,
]
