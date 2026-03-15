# -*- coding: utf-8 -*-
"""
===================================
通用响应模型
===================================

职责：
1. 定义通用的响应模型（HealthResponse, ErrorResponse 等）
2. 提供统一的响应格式
"""

from typing import Optional, Any

from pydantic import BaseModel, Field


class RootResponse(BaseModel):
    """API 根路由响应"""
    
    message: str = Field(..., description="API 运行状态消息", example="Daily Stock Analysis API is running")
    version: Optional[str] = Field(None, description="API 版本", example="1.0.0")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "Daily Stock Analysis API is running",
                "version": "1.0.0"
            }
        }


class HealthResponse(BaseModel):
    """健康检查响应"""
    
    status: str = Field(..., description="服务状态", example="ok")
    timestamp: Optional[str] = Field(None, description="时间戳")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "ok",
                "timestamp": "2024-01-01T12:00:00"
            }
        }


class ErrorResponse(BaseModel):
    """错误响应"""
    
    error: str = Field(..., description="错误类型", example="validation_error")
    message: str = Field(..., description="错误详情", example="请求参数错误")
    detail: Optional[Any] = Field(None, description="附加错误信息")
    
    class Config:
        json_schema_extra = {
            "example": {
                "error": "not_found",
                "message": "资源不存在",
                "detail": None
            }
        }


class SuccessResponse(BaseModel):
    """通用成功响应"""
    
    success: bool = Field(True, description="是否成功")
    message: Optional[str] = Field(None, description="成功消息")
    data: Optional[Any] = Field(None, description="响应数据")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "操作成功",
                "data": None
            }
        }
