# -*- coding: utf-8 -*-
"""
===================================
API v1 路由聚合
===================================

职责：
1. 聚合 v1 版本的所有 endpoint 路由
2. 统一添加 /api/v1 前缀
"""

import os

from fastapi import APIRouter

from api.v1.endpoints import (
    agent,
    alerts,
    screening,
    analysis,
    auth,
    backtest,
    data,
    decision_signals,
    health,
    history,
    intelligence,
    market_sentiment,
    portfolio,
    stocks,
    system_config,
    usage,
)


def is_market_sentiment_snapshot_enabled() -> bool:
    """市场情绪快照路由开关（issue #1939 Wave 6）。

    默认关闭（仓库"新功能默认关闭"惯例，#2432/#2439 同款评审要求）：关闭时
    /market-sentiment 路由在本模块导入（挂载）阶段即不注册，OpenAPI 文档与
    实际路径都不可见（404），零后台成本；开启仅暴露只读查询与手动触发端点。

    读取顺序：进程环境变量优先（os.getenv 直读，与 src/config.py 的 env 解析
    同源）；未设置时回退 Config 单例（默认同为 false）。路由挂载发生在模块
    导入期，因此修改开关需重启进程生效（registry 已标注 restart_required）。
    """
    raw = os.getenv("MARKET_SENTIMENT_SNAPSHOT_ENABLED")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() == "true"
    try:
        from src.config import get_config

        return bool(getattr(get_config(), "market_sentiment_snapshot_enabled", False))
    except Exception:  # 配置不可用时按默认关闭处理，绝不阻断其余路由挂载
        return False


# 创建 v1 版本主路由。
# /api/v1 前缀在 api.app 挂载，避免新版 FastAPI 误判子路由 "" 为 empty path。
router = APIRouter()

router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Auth"]
)

router.include_router(
    agent.router,
    prefix="/agent",
    tags=["Agent"]
)

router.include_router(
    analysis.router,
    prefix="/analysis",
    tags=["Analysis"]
)

router.include_router(
    history.router,
    prefix="/history",
    tags=["History"]
)

router.include_router(
    stocks.router,
    prefix="/stocks",
    tags=["Stocks"]
)

router.include_router(
    backtest.router,
    prefix="/backtest",
    tags=["Backtest"]
)

router.include_router(
    system_config.router,
    prefix="/system",
    tags=["SystemConfig"]
)

router.include_router(
    usage.router,
    prefix="/usage",
    tags=["Usage"]
)

router.include_router(
    portfolio.router,
    prefix="/portfolio",
    tags=["Portfolio"]
)

router.include_router(
    alerts.router,
    prefix="/alerts",
    tags=["Alerts"]
)

router.include_router(
    decision_signals.router,
    prefix="/decision-signals",
    tags=["DecisionSignals"]
)

router.include_router(
    screening.router,
    prefix="/screening",
    tags=["Screening"]
)

router.include_router(
    data.router,
    prefix="/data",
    tags=["Data"]
)

router.include_router(
    intelligence.router,
    prefix="/intelligence",
    tags=["Intelligence"]
)

# 市场情绪快照路由按开关条件挂载（issue #1939）：默认关闭时不注册，
# OpenAPI 与实际路径均不可见（404）；开启后暴露只读端点 + 手动触发。
# 仓库无现成的 router 级开关先例（screening 是端点内 403 门），故在此处做
# 挂载期条件判断，语义见 is_market_sentiment_snapshot_enabled docstring。
if is_market_sentiment_snapshot_enabled():
    router.include_router(
        market_sentiment.router,
        prefix="/market-sentiment",
        tags=["MarketSentiment"]
    )

router.include_router(
    health.router,
    tags=["Health"]
)
