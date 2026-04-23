# -*- coding: utf-8 -*-
"""
===================================
健康检查接口
===================================

职责：
1. 提供 /api/v1/health 健康检查接口
2. 用于负载均衡器和监控系统
"""

from datetime import datetime

from fastapi import APIRouter

from api.v1.schemas.common import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    健康检查接口
    
    用于负载均衡器或监控系统检查服务状态
    
    Returns:
        HealthResponse: 包含服务状态和时间戳
    """
    return HealthResponse(
        status="ok",
        timestamp=datetime.now().isoformat()
    )
