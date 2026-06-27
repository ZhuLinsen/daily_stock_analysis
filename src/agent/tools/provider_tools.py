# -*- coding: utf-8 -*-
"""Provider-specific Agent tools for EastMoney and TongHuaShun data."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List

from src.agent.tools.registry import ToolDefinition, ToolParameter

logger = logging.getLogger(__name__)


def _get_router():
    from data_provider.provider_router import get_provider_router

    return get_provider_router()


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _limit_rows(payload: Dict[str, Any], limit: int) -> Dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, list) and limit > 0:
        payload = {**payload, "data": data[-limit:]}
    return payload


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _handle_eastmoney_realtime_quote(stock_code: str) -> dict:
    return _jsonable(_get_router().get_realtime_quote(stock_code))


def _handle_eastmoney_daily_kline(stock_code: str, period: str = "daily", allow_remote: bool = True, limit: int = 120) -> dict:
    safe_limit = max(1, min(int(limit or 120), 200))
    payload = _get_router().get_daily_kline(stock_code, period=period or "daily", allow_remote=_as_bool(allow_remote, True))
    return _jsonable(_limit_rows(payload, safe_limit))


def _handle_eastmoney_money_flow(stock_code: str, allow_remote: bool = True) -> dict:
    return _jsonable(_get_router().get_money_flow(stock_code, allow_remote=_as_bool(allow_remote, True)))


def _handle_eastmoney_lhb(stock_code: str) -> dict:
    return _jsonable(_get_router().get_lhb(stock_code))


def _handle_eastmoney_limit_up_pool() -> dict:
    return _jsonable(_get_router().get_limit_up_pool())


def _handle_eastmoney_stock_news(stock_code: str, limit: int = 10) -> dict:
    safe_limit = max(1, min(int(limit or 10), 30))
    payload = _get_router().get_stock_news(stock_code)
    return _jsonable(_limit_rows(payload, safe_limit))


def _handle_ths_industry_boards() -> dict:
    return _jsonable(_get_router().get_industry_boards())


def _handle_ths_stock_snapshot(stock_code: str) -> dict:
    return _jsonable(_get_router().get_ths_stock_snapshot(stock_code))


def _handle_ths_stock_daily_kline(stock_code: str, limit: int = 120) -> dict:
    safe_limit = max(1, min(int(limit or 120), 200))
    payload = _get_router().get_ths_stock_daily_kline(stock_code)
    return _jsonable(_limit_rows(payload, safe_limit))


def _handle_ths_concept_boards() -> dict:
    return _jsonable(_get_router().get_concept_boards())


def _handle_ths_industry_constituents(board_name: str) -> dict:
    return _jsonable(_get_router().get_industry_constituents(board_name))


def _handle_ths_concept_constituents(concept_name: str) -> dict:
    return _jsonable(_get_router().get_concept_constituents(concept_name))


def _handle_ths_infer_stock_themes(stock_code: str, allow_remote: bool = False) -> dict:
    return _jsonable(_get_router().infer_stock_themes(stock_code, allow_remote=_as_bool(allow_remote, False)))


eastmoney_realtime_quote_tool = ToolDefinition(
    name="eastmoney_realtime_quote",
    description="Get an A-share realtime quote through the EastMoney workbench provider envelope. Returns source/stale/error/data.",
    parameters=[ToolParameter(name="stock_code", type="string", description="A-share stock code, e.g. 600519")],
    handler=_handle_eastmoney_realtime_quote,
    category="data",
)

eastmoney_daily_kline_tool = ToolDefinition(
    name="eastmoney_daily_kline",
    description="Get EastMoney-oriented daily K-line data with MA, MACD, KDJ, RSI and BOLL fields. Uses cache fallback and returns source/stale/error/data.",
    parameters=[
        ToolParameter(name="stock_code", type="string", description="A-share stock code, e.g. 600519"),
        ToolParameter(name="period", type="string", description="K-line period, currently only daily", required=False, default="daily", enum=["daily"]),
        ToolParameter(name="allow_remote", type="boolean", description="Whether remote provider calls are allowed; false is cache-only fast mode", required=False, default=True),
        ToolParameter(name="limit", type="integer", description="Maximum bars to return, capped at 200", required=False, default=120),
    ],
    handler=_handle_eastmoney_daily_kline,
    category="data",
)

eastmoney_money_flow_tool = ToolDefinition(
    name="eastmoney_money_flow",
    description="Get EastMoney-oriented main-force capital flow data. Returns source/stale/error/data and fails open on provider issues.",
    parameters=[
        ToolParameter(name="stock_code", type="string", description="A-share stock code, e.g. 600519"),
        ToolParameter(name="allow_remote", type="boolean", description="Whether remote provider calls are allowed; false is fast empty/cache mode", required=False, default=True),
    ],
    handler=_handle_eastmoney_money_flow,
    category="data",
)

eastmoney_lhb_tool = ToolDefinition(
    name="eastmoney_lhb",
    description="Get Dragon Tiger List context for an A-share stock through the EastMoney provider envelope.",
    parameters=[ToolParameter(name="stock_code", type="string", description="A-share stock code, e.g. 600519")],
    handler=_handle_eastmoney_lhb,
    category="data",
)

eastmoney_limit_up_pool_tool = ToolDefinition(
    name="eastmoney_limit_up_pool",
    description="Get the current A-share limit-up pool for short-term sentiment review through the EastMoney provider envelope.",
    parameters=[],
    handler=_handle_eastmoney_limit_up_pool,
    category="market",
)

eastmoney_stock_news_tool = ToolDefinition(
    name="eastmoney_stock_news",
    description="Get EastMoney stock news for an A-share symbol. Returns source/stale/error/data and should be treated as review context only.",
    parameters=[
        ToolParameter(name="stock_code", type="string", description="A-share stock code, e.g. 600519"),
        ToolParameter(name="limit", type="integer", description="Maximum news items to return, capped at 30", required=False, default=10),
    ],
    handler=_handle_eastmoney_stock_news,
    category="search",
)

ths_industry_boards_tool = ToolDefinition(
    name="ths_industry_boards",
    description="Get TongHuaShun industry boards for A-share sector review. Returns source/stale/error/data.",
    parameters=[],
    handler=_handle_ths_industry_boards,
    category="market",
)

ths_stock_snapshot_tool = ToolDefinition(
    name="ths_stock_snapshot",
    description="Get official TongHuaShun Fuyao A-share quote snapshot. Returns source/stale/error/data and fails open.",
    parameters=[ToolParameter(name="stock_code", type="string", description="A-share stock code, e.g. 600519")],
    handler=_handle_ths_stock_snapshot,
    category="data",
)

ths_stock_daily_kline_tool = ToolDefinition(
    name="ths_stock_daily_kline",
    description="Get official TongHuaShun Fuyao A-share daily K-line data enriched with MA, MACD, KDJ, RSI and BOLL fields.",
    parameters=[
        ToolParameter(name="stock_code", type="string", description="A-share stock code, e.g. 600519"),
        ToolParameter(name="limit", type="integer", description="Maximum bars to return, capped at 200", required=False, default=120),
    ],
    handler=_handle_ths_stock_daily_kline,
    category="data",
)

ths_concept_boards_tool = ToolDefinition(
    name="ths_concept_boards",
    description="Get TongHuaShun concept boards for A-share theme review. Returns source/stale/error/data.",
    parameters=[],
    handler=_handle_ths_concept_boards,
    category="market",
)

ths_industry_constituents_tool = ToolDefinition(
    name="ths_industry_constituents",
    description="Get constituents for a TongHuaShun industry board.",
    parameters=[ToolParameter(name="board_name", type="string", description="Industry board name, e.g. 半导体")],
    handler=_handle_ths_industry_constituents,
    category="market",
)

ths_concept_constituents_tool = ToolDefinition(
    name="ths_concept_constituents",
    description="Get constituents for a TongHuaShun concept board.",
    parameters=[ToolParameter(name="concept_name", type="string", description="Concept board name, e.g. 人工智能")],
    handler=_handle_ths_concept_constituents,
    category="market",
)

ths_infer_stock_themes_tool = ToolDefinition(
    name="ths_infer_stock_themes",
    description="Infer industry and concept themes for an A-share symbol. Default is fast/cache mode to avoid blocking pages.",
    parameters=[
        ToolParameter(name="stock_code", type="string", description="A-share stock code, e.g. 600519"),
        ToolParameter(name="allow_remote", type="boolean", description="Whether slow remote theme lookup is allowed", required=False, default=False),
    ],
    handler=_handle_ths_infer_stock_themes,
    category="market",
)


ALL_PROVIDER_TOOLS: List[ToolDefinition] = [
    eastmoney_realtime_quote_tool,
    eastmoney_daily_kline_tool,
    eastmoney_money_flow_tool,
    eastmoney_lhb_tool,
    eastmoney_limit_up_pool_tool,
    eastmoney_stock_news_tool,
    ths_stock_snapshot_tool,
    ths_stock_daily_kline_tool,
    ths_industry_boards_tool,
    ths_concept_boards_tool,
    ths_industry_constituents_tool,
    ths_concept_constituents_tool,
    ths_infer_stock_themes_tool,
]
