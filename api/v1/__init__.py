# -*- coding: utf-8 -*-
"""
===================================
API v1 模块初始化
===================================

职责：
1. 导出 v1 版本 API 的路由
"""

from api.v1.router import router as api_v1_router

__all__ = ["api_v1_router"]
