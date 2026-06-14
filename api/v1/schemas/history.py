# -*- coding: utf-8 -*-
"""
===================================
历史记录相关模型
===================================

职责：
1. 定义历史记录列表和详情模型
2. 定义分析报告完整模型
"""

from typing import Optional, List, Any, Dict, Literal

from pydantic import BaseModel, ConfigDict, Field

from api.v1.schemas.market_phase import MarketPhaseSummary
from src.schemas.decision_action import DecisionAction


class HistoryItem(BaseModel):
    """历史记录摘要（列表展示用）"""

    id: Optional[int] = Field(None, description="分析历史记录主键 ID")
    query_id: str = Field(..., description="分析记录关联 query_id（批量分析时重复）")
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    report_type: Optional[str] = Field(None, description="报告类型")
    trend_prediction: Optional[str] = Field(None, description="趋势预测")
    analysis_summary: Optional[str] = Field(None, description="分析摘要")
    sentiment_score: Optional[int] = Field(
        None,
        description="情绪评分（历史数据可能超出 0-100 范围，读取时不做约束）",
    )
    operation_advice: Optional[str] = Field(None, description="操作建议")
    action: Optional[DecisionAction] = Field(None, description="结构化建议动作 taxonomy")
    action_label: Optional[str] = Field(None, description="建议动作展示标签")
    current_price: Optional[float] = Field(None, description="分析时股价")
    change_pct: Optional[float] = Field(None, description="分析时涨跌幅(%)")
    volume_ratio: Optional[float] = Field(None, description="分析时量比")
    turnover_rate: Optional[float] = Field(None, description="分析时换手率")
    model_used: Optional[str] = Field(
        None,
        description="分析历史记录中的模型快照，仅用于展示历史元数据；不参与模型配置或运行时路由决策",
    )
    market_phase_summary: Optional[MarketPhaseSummary] = Field(
        None,
        description="本次分析市场阶段低敏摘要",
    )
    created_at: Optional[str] = Field(None, description="创建时间")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "id": 1234,
            "query_id": "abc123",
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "report_type": "detailed",
            "sentiment_score": 75,
            "operation_advice": "持有",
            "created_at": "2024-01-01T12:00:00"
        }
    })


class HistoryListResponse(BaseModel):
    """历史记录列表响应"""
    
    total: int = Field(..., description="总记录数")
    page: int = Field(..., description="当前页码")
    limit: int = Field(..., description="每页数量")
    items: List[HistoryItem] = Field(default_factory=list, description="记录列表")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "total": 100,
            "page": 1,
            "limit": 20,
            "items": []
        }
    })


class DeleteHistoryRequest(BaseModel):
    """删除历史记录请求"""

    record_ids: List[int] = Field(default_factory=list, description="要删除的历史记录主键 ID 列表")


class DeleteHistoryResponse(BaseModel):
    """删除历史记录响应"""

    deleted: int = Field(..., description="实际删除的历史记录数量")


class NewsIntelItem(BaseModel):
    """新闻情报条目"""

    title: str = Field(..., description="新闻标题")
    snippet: str = Field("", description="新闻摘要（最多200字）")
    url: str = Field(..., description="新闻链接")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "title": "公司发布业绩快报，营收同比增长 20%",
            "snippet": "公司公告显示，季度营收同比增长 20%...",
            "url": "https://example.com/news/123"
        }
    })


class NewsIntelResponse(BaseModel):
    """新闻情报响应"""

    total: int = Field(..., description="新闻条数")
    items: List[NewsIntelItem] = Field(default_factory=list, description="新闻列表")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "total": 2,
            "items": []
        }
    })


class ReportMeta(BaseModel):
    """报告元信息"""

    model_config = ConfigDict(protected_namespaces=("model_validate", "model_dump"))

    id: Optional[int] = Field(None, description="分析历史记录主键 ID（仅历史报告有此字段）")
    query_id: str = Field(..., description="分析记录关联 query_id（批量分析时重复）")
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    report_type: Optional[str] = Field(None, description="报告类型")
    report_language: Optional[str] = Field(None, description="报告输出语言（zh/en）")
    created_at: Optional[str] = Field(None, description="创建时间")
    current_price: Optional[float] = Field(None, description="分析时股价")
    change_pct: Optional[float] = Field(None, description="分析时涨跌幅(%)")
    model_used: Optional[str] = Field(
        None,
        description="历史报告元数据中的模型快照，仅用于展示，不影响 Provider/Model/Base URL 运行时路由",
    )
    market_phase_summary: Optional[MarketPhaseSummary] = Field(
        None,
        description="本次分析市场阶段低敏摘要",
    )


class ReportSummary(BaseModel):
    """报告概览区"""
    
    analysis_summary: Optional[str] = Field(None, description="关键结论")
    operation_advice: Optional[str] = Field(None, description="操作建议")
    action: Optional[DecisionAction] = Field(None, description="结构化建议动作 taxonomy")
    action_label: Optional[str] = Field(None, description="建议动作展示标签")
    trend_prediction: Optional[str] = Field(None, description="趋势预测")
    sentiment_score: Optional[int] = Field(
        None,
        description="情绪评分（历史数据可能超出 0-100 范围，读取时不做约束）",
    )
    sentiment_label: Optional[str] = Field(None, description="情绪标签")


class ReportStrategy(BaseModel):
    """策略点位区"""
    
    ideal_buy: Optional[str] = Field(None, description="理想买入价")
    secondary_buy: Optional[str] = Field(None, description="第二买入价")
    stop_loss: Optional[str] = Field(None, description="止损价")
    take_profit: Optional[str] = Field(None, description="止盈价")


class AnalysisContextPackOverviewSubject(BaseModel):
    """AnalysisContextPack 可见摘要标的信息"""

    code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    market: Optional[str] = Field(None, description="市场")


class AnalysisContextPackOverviewBlock(BaseModel):
    """AnalysisContextPack 可见摘要数据块"""

    key: str = Field(..., description="数据块稳定 key")
    label: str = Field(..., description="数据块展示名称")
    status: Literal[
        "available",
        "missing",
        "not_supported",
        "fallback",
        "stale",
        "estimated",
        "partial",
        "fetch_failed",
    ] = Field(..., description="数据块质量状态")
    source: Optional[str] = Field(None, description="数据来源")
    warnings: List[str] = Field(default_factory=list, description="数据块告警码")
    missing_reasons: List[str] = Field(default_factory=list, description="缺失原因")


class AnalysisContextPackOverviewCounts(BaseModel):
    """AnalysisContextPack 可见摘要状态计数"""

    available: int = 0
    missing: int = 0
    not_supported: int = 0
    fallback: int = 0
    stale: int = 0
    estimated: int = 0
    partial: int = 0
    fetch_failed: int = 0


class AnalysisContextPackOverviewMetadata(BaseModel):
    """AnalysisContextPack 可见摘要元数据"""

    trigger_source: Optional[str] = Field(None, description="触发来源")
    news_result_count: Optional[int] = Field(None, description="新闻结果数量")


class AnalysisContextPackOverviewDataQuality(BaseModel):
    """AnalysisContextPack 可见摘要数据质量评分"""

    overall_score: Optional[int] = Field(None, ge=0, le=100, description="输入数据质量总分")
    level: Optional[Literal["good", "usable", "limited", "poor"]] = Field(
        None,
        description="输入数据质量等级",
    )
    block_scores: Dict[str, int] = Field(default_factory=dict, description="固定数据块质量分")
    limitations: List[str] = Field(default_factory=list, description="低敏数据限制说明")


class AnalysisContextPackOverview(BaseModel):
    """历史/API 可见的低敏 AnalysisContextPack 摘要"""

    pack_version: str = Field(..., description="AnalysisContextPack 版本")
    created_at: Optional[str] = Field(None, description="创建时间")
    subject: AnalysisContextPackOverviewSubject
    blocks: List[AnalysisContextPackOverviewBlock] = Field(default_factory=list)
    counts: AnalysisContextPackOverviewCounts
    data_quality: Optional[AnalysisContextPackOverviewDataQuality] = Field(
        None,
        description="本次分析输入数据质量低敏摘要",
    )
    warnings: List[str] = Field(default_factory=list, description="顶层数据质量提醒")
    metadata: AnalysisContextPackOverviewMetadata = Field(default_factory=AnalysisContextPackOverviewMetadata)


class ReportDetails(BaseModel):
    """报告详情区"""
    
    news_content: Optional[str] = Field(None, description="新闻摘要")
    raw_result: Optional[Any] = Field(None, description="原始分析结果（JSON）")
    context_snapshot: Optional[Any] = Field(None, description="分析时上下文快照（JSON）")
    analysis_context_pack_overview: Optional[AnalysisContextPackOverview] = Field(
        None,
        description="本次分析输入上下文包低敏摘要",
    )
    financial_report: Optional[Any] = Field(None, description="结构化财报摘要（来自 fundamental_context）")
    dividend_metrics: Optional[Any] = Field(None, description="结构化分红指标（含 TTM 口径）")
    belong_boards: Optional[Any] = Field(None, description="关联板块列表")
    sector_rankings: Optional[Any] = Field(None, description="板块涨跌榜（结构 {top, bottom}）")


class AnalysisReport(BaseModel):
    """完整分析报告"""

    meta: ReportMeta = Field(..., description="元信息")
    summary: ReportSummary = Field(..., description="概览区")
    strategy: Optional[ReportStrategy] = Field(None, description="策略点位区")
    details: Optional[ReportDetails] = Field(None, description="详情区")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "meta": {
                "query_id": "abc123",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report_type": "detailed",
                "report_language": "zh",
                "created_at": "2024-01-01T12:00:00"
            },
            "summary": {
                "analysis_summary": "技术面向好，建议持有",
                "operation_advice": "持有",
                "trend_prediction": "看多",
                "sentiment_score": 75,
                "sentiment_label": "乐观"
            },
            "strategy": {
                "ideal_buy": "1800.00",
                "secondary_buy": "1750.00",
                "stop_loss": "1700.00",
                "take_profit": "2000.00"
            },
            "details": None
        }
    })


class MarkdownReportResponse(BaseModel):
    """Markdown 格式报告响应"""

    content: str = Field(..., description="Markdown 格式的完整报告内容")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "content": "# 📊 贵州茅台 (600519) 分析报告\n\n> 分析日期：**2024-01-01**\n\n..."
        }
    })


class StockBarItem(BaseModel):
    """个股栏条目（去重后的股票维度摘要）"""

    id: int = Field(..., description="该股最新一次分析的历史记录主键 ID")
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    report_type: Optional[str] = Field(None, description="报告类型")
    sentiment_score: Optional[int] = Field(
        None,
        description="最新情绪评分",
    )
    operation_advice: Optional[str] = Field(None, description="最新操作建议")
    action: Optional[DecisionAction] = Field(None, description="结构化建议动作 taxonomy")
    action_label: Optional[str] = Field(None, description="建议动作展示标签")
    analysis_count: int = Field(..., description="该股票的历史分析总次数")
    last_analysis_time: Optional[str] = Field(None, description="最近一次分析时间")
    model_used: Optional[str] = Field(
        None,
        description="最新分析使用的模型快照",
    )
    market_phase_summary: Optional[MarketPhaseSummary] = Field(
        None,
        description="最新分析市场阶段低敏摘要",
    )
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "id": 1234,
            "stock_code": "600519",
            "stock_name": "贵州茅台",
            "report_type": "detailed",
            "sentiment_score": 75,
            "operation_advice": "持有",
            "analysis_count": 18,
            "last_analysis_time": "2024-01-01T12:00:00",
            "model_used": "Gemini 2.5 Pro",
        }
    })


class StockBarResponse(BaseModel):
    """个股栏列表响应"""

    total: int = Field(..., description="不重复个股数")
    items: List[StockBarItem] = Field(default_factory=list, description="个股列表")


class WatchlistRequest(BaseModel):
    """自选队列操作请求"""

    stock_code: str = Field(..., description="股票代码", min_length=1)


class WatchlistResponse(BaseModel):
    """自选队列响应"""

    stock_codes: List[str] = Field(default_factory=list, description="当前自选队列股票代码列表")
    message: str = Field(..., description="操作结果描述")


class RunDiagnosticComponent(BaseModel):
    """单个运行诊断组件摘要。"""

    key: str = Field(..., description="组件键")
    label: str = Field(..., description="组件显示名称")
    status: str = Field(..., description="组件状态：ok/degraded/failed/unknown/not_configured/skipped")
    message: str = Field(..., description="用户可读摘要")
    details: Optional[Dict[str, Any]] = Field(None, description="折叠展示的诊断细节")


class RunDiagnosticSummaryResponse(BaseModel):
    """历史报告运行诊断摘要。"""

    trace_id: Optional[str] = Field(None, description="诊断 trace ID")
    task_id: Optional[str] = Field(None, description="任务 ID")
    query_id: Optional[str] = Field(None, description="分析 query ID")
    stock_code: Optional[str] = Field(None, description="股票代码")
    trigger_source: Optional[str] = Field(None, description="触发来源")
    status: str = Field(..., description="总体状态：normal/degraded/failed/unknown")
    status_label: str = Field(..., description="总体状态中文标签")
    reason: str = Field(..., description="最主要的诊断原因")
    components: Dict[str, RunDiagnosticComponent] = Field(default_factory=dict, description="关键链路诊断组件")
    copy_text: str = Field(..., description="可复制的脱敏排障文本")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "trace_id": "task_abc123",
            "query_id": "task_abc123",
            "stock_code": "600519",
            "status": "degraded",
            "status_label": "部分降级",
            "reason": "实时行情失败：timeout",
            "components": {},
            "copy_text": "trace_id: task_abc123\nstock_code: 600519\n...",
        }
    })
