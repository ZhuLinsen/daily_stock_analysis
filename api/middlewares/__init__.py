# -*- coding: utf-8 -*-
"""
===================================
API 中间件模块初始化
===================================

职责：
1. 导出所有中间件
"""

from api.middlewares.error_handler import ErrorHandlerMiddleware

__all__ = ["ErrorHandlerMiddleware"]
