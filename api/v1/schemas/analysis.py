# -*- coding: utf-8 -*-
"""
===================================
分析相关模型
===================================

职责：
1. 定义分析请求和响应模型
2. 定义任务状态模型
3. 定义异步任务队列相关模型
"""

from typing import Optional, List, Any
from enum import Enum

from pydantic import BaseModel, Field


class TaskStatusEnum(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalyzeRequest(BaseModel):
    """分析请求模型"""
    
    stock_code: Optional[str] = Field(
        None, 
        description="单只股票代码", 
        example="600519"
    )
    stock_codes: Optional[List[str]] = Field(
        None, 
        description="多只股票代码（与 stock_code 二选一）",
        example=["600519", "000858"]
    )
    report_type: str = Field(
        "detailed", 
        description="报告类型",
        pattern="^(simple|detailed)$"
    )
    force_refresh: bool = Field(
        True,
        description="是否强制刷新（忽略缓存）"
    )
    async_mode: bool = Field(
        False,
        description="是否使用异步模式"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "stock_code": "600519",
                "report_type": "detailed",
                "force_refresh": False,
                "async_mode": False
            }
        }


class AnalysisResultResponse(BaseModel):
    """分析结果响应模型"""
    
    query_id: str = Field(..., description="分析记录唯一标识")
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    report: Optional[Any] = Field(None, description="分析报告")
    created_at: str = Field(..., description="创建时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query_id": "abc123def456",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report": {
                    "summary": {
                        "sentiment_score": 75,
                        "operation_advice": "持有"
                    }
                },
                "created_at": "2024-01-01T12:00:00"
            }
        }


class TaskAccepted(BaseModel):
    """异步任务接受响应"""
    
    task_id: str = Field(..., description="任务 ID，用于查询状态")
    status: str = Field(
        ..., 
        description="任务状态",
        pattern="^(pending|processing)$"
    )
    message: Optional[str] = Field(None, description="提示信息")
    
    class Config:
        json_schema_extra = {
            "example": {
                "task_id": "task_abc123",
                "status": "pending",
                "message": "Analysis task accepted"
            }
        }


class TaskStatus(BaseModel):
    """任务状态模型"""
    
    task_id: str = Field(..., description="任务 ID")
    status: str = Field(
        ..., 
        description="任务状态",
        pattern="^(pending|processing|completed|failed)$"
    )
    progress: Optional[int] = Field(
        None, 
        description="进度百分比 (0-100)",
        ge=0,
        le=100
    )
    result: Optional[AnalysisResultResponse] = Field(
        None, 
        description="分析结果（仅在 completed 时存在）"
    )
    error: Optional[str] = Field(
        None, 
        description="错误信息（仅在 failed 时存在）"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "task_id": "task_abc123",
                "status": "completed",
                "progress": 100,
                "result": None,
                "error": None
            }
        }


class TaskInfo(BaseModel):
    """
    任务详情模型
    
    用于任务列表和 SSE 事件推送
    """
    
    task_id: str = Field(..., description="任务 ID")
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    status: TaskStatusEnum = Field(..., description="任务状态")
    progress: int = Field(0, description="进度百分比 (0-100)", ge=0, le=100)
    message: Optional[str] = Field(None, description="状态消息")
    report_type: str = Field("detailed", description="报告类型")
    created_at: str = Field(..., description="创建时间")
    started_at: Optional[str] = Field(None, description="开始执行时间")
    completed_at: Optional[str] = Field(None, description="完成时间")
    error: Optional[str] = Field(None, description="错误信息（仅在 failed 时存在）")
    
    class Config:
        json_schema_extra = {
            "example": {
                "task_id": "abc123def456",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "status": "processing",
                "progress": 50,
                "message": "正在分析中...",
                "report_type": "detailed",
                "created_at": "2026-02-05T10:30:00",
                "started_at": "2026-02-05T10:30:01",
                "completed_at": None,
                "error": None
            }
        }


class TaskListResponse(BaseModel):
    """任务列表响应模型"""
    
    total: int = Field(..., description="任务总数")
    pending: int = Field(..., description="等待中的任务数")
    processing: int = Field(..., description="处理中的任务数")
    tasks: List[TaskInfo] = Field(..., description="任务列表")
    
    class Config:
        json_schema_extra = {
            "example": {
                "total": 3,
                "pending": 1,
                "processing": 2,
                "tasks": []
            }
        }


class DuplicateTaskErrorResponse(BaseModel):
    """重复任务错误响应模型"""
    
    error: str = Field("duplicate_task", description="错误类型")
    message: str = Field(..., description="错误信息")
    stock_code: str = Field(..., description="股票代码")
    existing_task_id: str = Field(..., description="已存在的任务 ID")
    
    class Config:
        json_schema_extra = {
            "example": {
                "error": "duplicate_task",
                "message": "股票 600519 正在分析中",
                "stock_code": "600519",
                "existing_task_id": "abc123def456"
            }
        }
