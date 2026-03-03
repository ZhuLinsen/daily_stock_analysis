# -*- coding: utf-8 -*-
"""
===================================
API v1 Endpoints 模块初始化
===================================

职责：
1. 导出所有 endpoint 路由模块
"""

from api.v1.endpoints import health, analysis, history, stocks, backtest, system_config

__all__ = ["health", "analysis", "history", "stocks", "backtest", "system_config"]
