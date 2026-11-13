# -*- coding: utf-8 -*-
"""
===================================
市场情绪快照 Schemas（issue #1939 Wave 5）
===================================

职责：
1. 定义 /api/v1/market-sentiment 四端点的 Pydantic 请求/响应模型
2. 请求体 camelCase alias 兼容（tradeDate 等，仿 MarketReviewRequest 先例）

契约来源：实施计划 §4（4.1 触发 / 4.2 列表 / 4.3 详情 / 4.4 趋势）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class MarketSentimentTriggerRequest(BaseModel):
    """POST /market-sentiment/snapshots 请求体（§4.1，可整体省略）。"""

    model_config = ConfigDict(populate_by_name=True)

    trade_date: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("trade_date", "tradeDate"),
        description=(
            "显式触发日（YYYY-MM-DD）。一期仅支持触发「最近已收盘交易日」单一目标："
            "显式值必须严格等于按 Asia/Shanghai 收盘规则（≥15:00 且当日交易日为当日，"
            "否则上一交易日）解析出的目标日，否则 400 invalid_target_date"
        ),
    )
    force: bool = Field(
        False,
        description=(
            "该交易日已有 complete 快照时是否强制重算；重算结果仍走幂等合并规则，"
            "partial 不会覆盖既有 complete"
        ),
    )


class MarketSentimentExistingSnapshot(BaseModel):
    """触发短路（200）时随响应返回的既有 complete 快照摘要。"""

    trade_date: str = Field(..., description="既有快照的交易日（ISO YYYY-MM-DD）")
    quality_status: str = Field(..., description="快照质量状态：complete / partial")
    completeness: float = Field(..., description="必备组粒度完整度 0~1")
    updated_at: Optional[str] = Field(
        None, description="既有快照最近更新时间（ISO 8601）"
    )


class MarketSentimentTriggerResponse(BaseModel):
    """POST /market-sentiment/snapshots 响应（202 accepted / 200 短路）。"""

    status: str = Field(
        ...,
        description="accepted（任务已受理）或 short_circuited（已有 complete 快照短路）",
    )
    trade_date: str = Field(..., description="本次触发的实际目标交易日")
    task_id: Optional[str] = Field(
        None, description="后台任务 ID（accepted 时返回；短路时为 null）"
    )
    message: str = Field(..., description="给调用方的提示信息")
    superseded_by_existing_complete: bool = Field(
        False,
        description="true 表示未启动新任务、直接复用既有 complete 快照（§3.4 规则 3）",
    )
    existing_snapshot: Optional[MarketSentimentExistingSnapshot] = Field(
        None, description="短路时返回的既有 complete 快照摘要"
    )


class MarketSentimentSnapshotSummaryItem(BaseModel):
    """GET /market-sentiment/snapshots 列表项（§4.2）。"""

    trade_date: str = Field(..., description="交易日（ISO YYYY-MM-DD）")
    quality_status: str = Field(..., description="快照质量状态：complete / partial")
    completeness: float = Field(..., description="必备组粒度完整度 0~1")
    created_at: Optional[str] = Field(None, description="首次落库时间（ISO 8601）")
    updated_at: Optional[str] = Field(None, description="最近更新时间（ISO 8601）")


class MarketSentimentSnapshotListResponse(BaseModel):
    """GET /market-sentiment/snapshots 响应（§4.2，只列实际存在的快照）。"""

    items: List[MarketSentimentSnapshotSummaryItem] = Field(
        default_factory=list, description="按 trade_date 排序的快照摘要列表，不插值不补零"
    )
    total: int = Field(..., description="该市场快照总数（不受分页影响）")


class MarketSentimentSnapshotDetailResponse(BaseModel):
    """GET /market-sentiment/snapshots/{trade_date} 响应（§4.3）。"""

    trade_date: str = Field(..., description="交易日（ISO YYYY-MM-DD）")
    market: str = Field(..., description="市场（一期仅 cn）")
    quality_status: str = Field(..., description="快照质量状态：complete / partial")
    completeness: float = Field(..., description="必备组粒度完整度 0~1")
    payload: Dict[str, Any] = Field(
        ..., description="完整指标 payload（计划 §3.2，schema_version=1；narrative 一期为 null）"
    )
    provider_trace: List[Dict[str, Any]] = Field(
        default_factory=list, description="取数轨迹（逐组 provider/api/状态/耗时）"
    )
    created_at: Optional[str] = Field(None, description="首次落库时间（ISO 8601）")
    updated_at: Optional[str] = Field(None, description="最近更新时间（ISO 8601）")


class MarketSentimentTrendPoint(BaseModel):
    """GET /market-sentiment/trend 序列点（§4.4，缺失日不伪造点）。"""

    trade_date: str = Field(..., description="交易日（ISO YYYY-MM-DD）")
    value: Optional[float] = Field(
        None, description="该日指标值；取不到时为 null（不补零）"
    )
    quality_status: str = Field(..., description="当日快照质量状态")


class MarketSentimentTrendResponse(BaseModel):
    """GET /market-sentiment/trend 响应（§4.4，空序列返回 200 不 404）。"""

    metric: str = Field(..., description="趋势指标名（§4.4 枚举之一）")
    points: List[MarketSentimentTrendPoint] = Field(
        default_factory=list, description="按 trade_date 升序的实际存在日期序列"
    )
    available_points: int = Field(..., description="序列点数")
