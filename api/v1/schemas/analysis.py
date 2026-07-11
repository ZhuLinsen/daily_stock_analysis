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

from typing import Optional, List, Any, Literal
from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from src.utils.analysis_metadata import SELECTION_SOURCE_PATTERN


class TaskStatusEnum(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


AnalysisPhase = Literal["auto", "premarket", "intraday", "postmarket"]


class AnalyzeRequest(BaseModel):
    """Analysis request parameters"""
    
    stock_code: Optional[str] = Field(
        None, 
        description="单只股票代码", 
        json_schema_extra={"example": "600519"},
    )
    stock_codes: Optional[List[str]] = Field(
        None, 
        description="多只股票代码（与 stock_code 二选一）",
        json_schema_extra={"example": ["600519", "000858"]},
    )
    report_type: str = Field(
        "detailed",
        description="报告类型：simple(精简) / detailed(完整) / full(完整) / brief(简洁)",
        pattern="^(simple|detailed|full|brief)$",
    )
    force_refresh: bool = Field(
        False,
        description="是否强制刷新（忽略缓存）"
    )
    async_mode: bool = Field(
        False,
        description="是否使用异步模式"
    )
    analysis_phase: AnalysisPhase = Field(
        "auto",
        description="分析阶段覆盖：auto(自动推断) / premarket(盘前) / intraday(盘中) / postmarket(盘后)",
    )
    stock_name: Optional[str] = Field(
        None,
        description="用户选中的股票名称（自动补全时提供）",
        json_schema_extra={"example": "贵州茅台"},
    )
    original_query: Optional[str] = Field(
        None,
        description="用户原始输入（如茅台、gzmt、600519）",
        json_schema_extra={"example": "茅台"},
    )
    selection_source: Optional[str] = Field(
        None,
        description="股票选择来源：manual(手动输入) | autocomplete(自动补全) | import(导入) | image(图片识别)",
        pattern=SELECTION_SOURCE_PATTERN,
        json_schema_extra={"example": "autocomplete"},
    )
    notify: bool = Field(
        True,
        description="是否发送推送通知（Telegram/企业微信等）"
    )
    report_language: Optional[Literal["zh", "en", "ko"]] = Field(
        None,
        validation_alias=AliasChoices("report_language", "reportLanguage"),
        description="本次分析报告输出语言；未传时使用全局 REPORT_LANGUAGE",
    )
    skills: Optional[List[str]] = Field(
        None,
        validation_alias=AliasChoices("skills", "strategies"),
        description="本次分析使用的策略 skill ID 列表；兼容 legacy strategies 字段",
        json_schema_extra={"example": ["bull_trend", "growth_quality"]},
    )

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "stock_code": "600519",
            "report_type": "detailed",
            "force_refresh": False,
            "async_mode": False,
            "analysis_phase": "auto",
            "stock_name": "贵州茅台",
            "original_query": "茅台",
            "selection_source": "autocomplete",
            "notify": True,
            "report_language": "zh",
            "skills": ["bull_trend"]
        }
    })


class MarketReviewRequest(BaseModel):
    """Market review trigger parameters."""

    send_notification: bool = Field(
        True,
        description="是否在大盘复盘完成后发送推送通知",
    )
    report_language: Optional[Literal["zh", "en", "ko"]] = Field(
        None,
        validation_alias=AliasChoices("report_language", "reportLanguage"),
        description="本次大盘复盘报告输出语言；未传时使用全局 REPORT_LANGUAGE",
    )


class MarketReviewAccepted(BaseModel):
    """Market review background task accepted response."""

    status: str = Field("accepted", description="提交状态")
    message: str = Field(..., description="提示信息")
    send_notification: bool = Field(..., description="是否发送通知")
    trace_id: Optional[str] = Field(
        None,
        description="本次后台任务的诊断 trace ID",
    )
    task_id: Optional[str] = Field(
        None,
        description="任务 ID（仅当任务实际提交时返回）",
    )


class AnalysisResultResponse(BaseModel):
    """分析结果响应模型"""
    
    query_id: str = Field(..., description="分析记录唯一标识")
    trace_id: Optional[str] = Field(None, description="诊断 trace ID")
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    report: Optional[Any] = Field(None, description="分析报告")
    diagnostic_summary: Optional[Any] = Field(None, description="运行诊断摘要")
    created_at: str = Field(..., description="创建时间")
    
    model_config = ConfigDict(json_schema_extra={
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
    })


class TaskAccepted(BaseModel):
    """异步任务接受响应"""
    
    task_id: str = Field(..., description="任务 ID，用于查询状态")
    trace_id: Optional[str] = Field(None, description="诊断 trace ID")
    status: str = Field(
        ..., 
        description="任务状态",
        pattern="^(pending|processing)$"
    )
    message: Optional[str] = Field(None, description="提示信息")
    analysis_phase: AnalysisPhase = Field("auto", description="请求的分析阶段")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "task_id": "task_abc123",
            "status": "pending",
            "message": "Analysis task accepted",
            "analysis_phase": "auto"
        }
    })


class BatchTaskAcceptedItem(BaseModel):
    """批量异步任务中的单个成功提交项。"""

    task_id: str = Field(..., description="任务 ID，用于查询状态")
    trace_id: Optional[str] = Field(None, description="诊断 trace ID")
    stock_code: str = Field(..., description="股票代码")
    status: str = Field(
        ...,
        description="任务状态",
        pattern="^(pending|processing)$"
    )
    message: Optional[str] = Field(None, description="提示信息")
    analysis_phase: AnalysisPhase = Field("auto", description="请求的分析阶段")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "task_id": "task_abc123",
            "stock_code": "600519",
            "status": "pending",
            "message": "分析任务已加入队列: 600519",
            "analysis_phase": "auto"
        }
    })


class BatchDuplicateTaskItem(BaseModel):
    """批量异步任务中的重复提交项。"""

    stock_code: str = Field(..., description="股票代码")
    existing_task_id: str = Field(..., description="已存在的任务 ID")
    message: str = Field(..., description="错误信息")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "stock_code": "600519",
            "existing_task_id": "task_existing_123",
            "message": "股票 600519 正在分析中 (task_id: task_existing_123)"
        }
    })


class BatchTaskAcceptedResponse(BaseModel):
    """批量异步任务接受响应。"""

    accepted: List[BatchTaskAcceptedItem] = Field(default_factory=list, description="成功提交的任务列表")
    duplicates: List[BatchDuplicateTaskItem] = Field(default_factory=list, description="重复而跳过的任务列表")
    message: str = Field(..., description="汇总信息")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "accepted": [
                {
                    "task_id": "task_abc123",
                    "stock_code": "600519",
                    "status": "pending",
                    "message": "分析任务已加入队列: 600519",
                    "analysis_phase": "auto"
                }
            ],
            "duplicates": [
                {
                    "stock_code": "000858",
                    "existing_task_id": "task_existing_456",
                    "message": "股票 000858 正在分析中 (task_id: task_existing_456)"
                }
            ],
            "message": "已提交 1 个任务，1 个重复跳过"
        }
    })


class TaskStatus(BaseModel):
    """Task status model"""
    
    task_id: str = Field(..., description="任务 ID")
    trace_id: Optional[str] = Field(None, description="诊断 trace ID")
    status: TaskStatusEnum = Field(
        ..., 
        description="任务状态",
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
    market_review_report: Optional[str] = Field(
        None,
        description="大盘复盘任务返回的报告文本（仅大盘复盘任务）",
    )
    market_review_payload: Optional[Any] = Field(
        None,
        description="Structured market-review payload for API/Web consumers.",
    )
    error: Optional[str] = Field(
        None, 
        description="错误信息（仅在 failed 时存在）"
    )
    stock_name: Optional[str] = Field(None, description="股票名称")
    original_query: Optional[str] = Field(None, description="用户原始输入")
    selection_source: Optional[str] = Field(
        None,
        description="选择来源",
        pattern=SELECTION_SOURCE_PATTERN,
    )
    analysis_phase: Optional[AnalysisPhase] = Field(
        None,
        description="请求的分析阶段；无持久化字段的历史 DB fallback 可能为空",
    )
    skills: Optional[List[str]] = Field(None, description="本次任务使用的策略 skill ID 列表")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "task_id": "task_abc123",
            "status": "completed",
            "progress": 100,
            "result": None,
            "market_review_report": None,
            "error": None,
            "stock_name": "贵州茅台",
            "original_query": "茅台",
            "selection_source": "autocomplete",
            "analysis_phase": "auto",
            "skills": ["bull_trend"]
        }
    })


class TaskInfo(BaseModel):
    """
    Task details model

    Used for task list and SSE event delivery
    """
    
    task_id: str = Field(..., description="任务 ID")
    trace_id: Optional[str] = Field(None, description="诊断 trace ID")
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
    original_query: Optional[str] = Field(None, description="用户原始输入")
    selection_source: Optional[str] = Field(
        None,
        description="选择来源",
        pattern=SELECTION_SOURCE_PATTERN,
    )
    analysis_phase: AnalysisPhase = Field("auto", description="请求的分析阶段")
    skills: Optional[List[str]] = Field(None, description="本次任务使用的策略 skill ID 列表")
    
    model_config = ConfigDict(json_schema_extra={
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
            "error": None,
            "original_query": "茅台",
            "selection_source": "autocomplete",
            "analysis_phase": "auto",
            "skills": ["bull_trend"]
        }
    })


class TaskListResponse(BaseModel):
    """任务列表响应模型"""
    
    total: int = Field(..., description="任务总数")
    pending: int = Field(..., description="等待中的任务数")
    processing: int = Field(..., description="处理中的任务数")
    tasks: List[TaskInfo] = Field(..., description="任务列表")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "total": 3,
            "pending": 1,
            "processing": 2,
            "tasks": []
        }
    })


class DuplicateTaskErrorResponse(BaseModel):
    """重复任务错误响应模型"""
    
    error: str = Field("duplicate_task", description="错误类型")
    message: str = Field(..., description="错误信息")
    stock_code: str = Field(..., description="股票代码")
    existing_task_id: str = Field(..., description="已存在的任务 ID")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "error": "duplicate_task",
            "message": "股票 600519 正在分析中",
            "stock_code": "600519",
            "existing_task_id": "abc123def456"
        }
    })
