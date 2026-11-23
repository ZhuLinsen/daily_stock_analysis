# -*- coding: utf-8 -*-
"""
===================================
API v1 模块初始化
===================================

职责：
1. 延迟导出 v1 版本 API 的路由，避免 schema import 触发整棵 endpoint 导入树
"""

from typing import Any

__all__ = ["api_v1_router"]


def __getattr__(name: str) -> Any:
    if name != "api_v1_router":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from api.v1.router import router

    return router
