# -*- coding: utf-8 -*-
"""Alert API schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


TargetScopeValue = Literal["single_symbol"]
SeverityValue = Literal["info", "warning", "critical"]
DryRunStatusValue = Literal["triggered", "not_triggered", "evaluation_error"]


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


class AlertRuleTestResponse(BaseModel):
    rule_id: int
    status: DryRunStatusValue
    triggered: bool
    observed_value: Optional[Any] = None
    message: str


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
