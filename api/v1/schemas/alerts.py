# -*- coding: utf-8 -*-
"""Alert API schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from api.v1.schemas.history import AnalysisContextPackOverview
from api.v1.schemas.market_phase import MarketPhaseSummary


TargetScopeValue = Literal["single_symbol", "watchlist", "portfolio_holdings", "portfolio_account", "market"]
SeverityValue = Literal["info", "warning", "critical"]
DryRunStatusValue = Literal["triggered", "not_triggered", "evaluation_error"]
TargetRecordStatusValue = Literal["triggered", "skipped", "degraded", "failed"]


class AlertRuleCreateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=64)
    target_scope: TargetScopeValue = "single_symbol"
    target: str = Field(..., min_length=1, max_length=64)
    alert_type: str = Field(..., min_length=1, max_length=32)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    severity: SeverityValue = "warning"
    enabled: bool = True
    cooldown_policy: Optional[Dict[str, Any]] = None
    notification_policy: Optional[Dict[str, Any]] = None


class AlertRuleUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=64)
    target_scope: Optional[TargetScopeValue] = None
    target: Optional[str] = Field(None, min_length=1, max_length=64)
    alert_type: Optional[str] = Field(None, min_length=1, max_length=32)
    parameters: Optional[Dict[str, Any]] = None
    severity: Optional[SeverityValue] = None
    enabled: Optional[bool] = None
    cooldown_policy: Optional[Dict[str, Any]] = None
    notification_policy: Optional[Dict[str, Any]] = None


class AlertRuleItem(BaseModel):
    id: int
    name: str
    target_scope: str
    target: str
    alert_type: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    severity: str
    enabled: bool
    source: str
    cooldown_policy: Optional[Dict[str, Any]] = None
    notification_policy: Optional[Dict[str, Any]] = None
    last_triggered_at: Optional[str] = None
    cooldown_until: Optional[str] = None
    cooldown_active: Optional[bool] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AlertRuleListResponse(BaseModel):
    items: List[AlertRuleItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class AlertDeleteResponse(BaseModel):
    deleted: int


class AlertRuleTargetResult(BaseModel):
    target: str
    display_target: Optional[str] = None
    status: DryRunStatusValue
    record_status: Optional[TargetRecordStatusValue] = None
    triggered: bool
    observed_value: Optional[Any] = None
    threshold: Optional[Any] = None
    message: str


class AlertRuleTestResponse(BaseModel):
    rule_id: int
    target_scope: Optional[str] = None
    status: DryRunStatusValue
    triggered: bool
    observed_value: Optional[Any] = None
    message: str
    evaluated_count: int = 0
    triggered_count: int = 0
    degraded_count: int = 0
    skipped_count: int = 0
    target_results: List[AlertRuleTargetResult] = Field(default_factory=list)


class AlertTriggerItem(BaseModel):
    id: int
    rule_id: Optional[int] = None
    target: str
    observed_value: Optional[float] = None
    threshold: Optional[float] = None
    reason: Optional[str] = None
    data_source: Optional[str] = None
    data_timestamp: Optional[str] = None
    triggered_at: Optional[str] = None
    status: str
    diagnostics: Optional[str] = None
    market_phase_summary: Optional[MarketPhaseSummary] = None
    analysis_context_pack_overview: Optional[AnalysisContextPackOverview] = None
    analysis_visibility_source: Optional[str] = Field(
        None,
        description=(
            "公开摘要来源：alert_trigger_market_context / analysis_history_snapshot / "
            "evaluator_snapshot / legacy_text / null"
        ),
    )
    decision_signal_summary: Optional[Dict[str, Any]] = None


class AlertTriggerListResponse(BaseModel):
    items: List[AlertTriggerItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class AlertNotificationItem(BaseModel):
    id: int
    trigger_id: Optional[int] = None
    channel: str
    attempt: int
    success: bool
    error_code: Optional[str] = None
    retryable: bool
    latency_ms: Optional[int] = None
    diagnostics: Optional[str] = None
    created_at: Optional[str] = None


class AlertNotificationListResponse(BaseModel):
    items: List[AlertNotificationItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
