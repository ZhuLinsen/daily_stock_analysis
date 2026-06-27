# -*- coding: utf-8 -*-
"""Schemas for the AI stock workbench MVP."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class WorkbenchBaseResponse(BaseModel):
    """Common response envelope for workbench pages.

    Extra fields are intentionally allowed because each workbench page returns a
    page-specific aggregate while preserving the shared source/stale/error
    contract.
    """

    source: str = Field(..., description="数据来源")
    stale: bool = Field(False, description="是否为延迟或降级数据")
    error: Optional[str] = Field(None, description="接口异常或降级原因")
    disclaimer: str = Field(..., description="AI 分析免责声明")

    model_config = ConfigDict(extra="allow")


class WorkbenchDashboardResponse(WorkbenchBaseResponse):
    pass


class WorkbenchWatchlistResponse(WorkbenchBaseResponse):
    pass


class WorkbenchStockDetailResponse(WorkbenchBaseResponse):
    pass


class WorkbenchDailyReviewResponse(WorkbenchBaseResponse):
    pass


class WorkbenchMarkdownResponse(BaseModel):
    markdown: str = Field(..., description="Markdown 复盘内容")
    filename: str = Field(..., description="建议文件名")
    source: str = Field(..., description="数据来源")
    stale: bool = Field(False, description="是否为延迟或降级数据")
    error: Optional[str] = Field(None, description="接口异常或降级原因")
    meta: Dict[str, Any] = Field(default_factory=dict, description="导出元信息")
