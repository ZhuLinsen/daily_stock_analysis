# -*- coding: utf-8 -*-
"""System configuration API schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

LLMCapabilityCheck = Literal["json", "tools", "vision", "stream"]
NotificationTestChannel = Literal[
    "wechat",
    "feishu",
    "telegram",
    "email",
    "pushover",
    "ntfy",
    "gotify",
    "pushplus",
    "serverchan3",
    "custom",
    "discord",
    "slack",
    "astrbot",
]


class SystemConfigOption(BaseModel):
    """Select option metadata for frontend rendering."""

    label: str
    value: str


class SystemConfigDocLink(BaseModel):
    """Documentation link metadata for field help panels."""

    label: str
    href: str


class SystemConfigFieldSchema(BaseModel):
    """Metadata schema for a single config field."""

    key: str = Field(..., description="Configuration key name")
    title: Optional[str] = Field(None, description="Display title")
    description: Optional[str] = Field(None, description="Field description")
    category: Literal["base", "data_source", "ai_model", "notification", "system", "agent", "backtest", "uncategorized"]
    data_type: Literal["string", "integer", "number", "boolean", "array", "json", "time"]
    ui_control: Literal["text", "password", "number", "select", "textarea", "switch", "time"]
    is_sensitive: bool
    is_required: bool
    is_editable: bool
    default_value: Optional[str] = None
    options: List[str | SystemConfigOption] = Field(default_factory=list)
    validation: Dict[str, Any] = Field(default_factory=dict)
    display_order: int
    help_key: Optional[str] = Field(None, description="Stable localization key for detailed help content")
    examples: List[str] = Field(default_factory=list, description="Safe example values for help panels")
    docs: List[SystemConfigDocLink] = Field(default_factory=list, description="Related documentation links")
    warning_codes: List[str] = Field(default_factory=list, description="Stable warning identifiers for help panels")


class SystemConfigCategorySchema(BaseModel):
    """Category grouping metadata."""

    category: str
    title: str
    description: Optional[str] = None
    display_order: int
    fields: List[SystemConfigFieldSchema]


class SystemConfigSchemaResponse(BaseModel):
    """Metadata response for dynamic frontend rendering."""

    schema_version: str
    categories: List[SystemConfigCategorySchema]


class SystemConfigItem(BaseModel):
    """Config value entry with optional schema metadata."""

    model_config = ConfigDict(populate_by_name=True)

    key: str
    value: str
    raw_value_exists: bool
    is_masked: bool
    schema_: Optional[SystemConfigFieldSchema] = Field(default=None, alias="schema")


class SystemConfigResponse(BaseModel):
    """Read response for current configuration values."""

    config_version: str
    mask_token: str
    items: List[SystemConfigItem]
    updated_at: Optional[str] = None


class SetupStatusCheck(BaseModel):
    """One first-run setup readiness check."""

    key: str
    title: str
    category: Literal["base", "ai_model", "agent", "notification", "system"]
    required: bool
    status: Literal["configured", "inherited", "optional", "needs_action"]
    message: str
    next_step: Optional[str] = None


class SetupStatusResponse(BaseModel):
    """Read-only first-run setup status."""

    is_complete: bool
    ready_for_smoke: bool
    required_missing_keys: List[str] = Field(default_factory=list)
    next_step_key: Optional[str] = None
    checks: List[SetupStatusCheck] = Field(default_factory=list)


class ExportSystemConfigResponse(BaseModel):
    """Export payload for raw `.env` backups."""

    content: str
    config_version: str
    updated_at: Optional[str] = None


class SystemConfigUpdateItem(BaseModel):
    """Single key-value update item."""

    key: str
    value: str


class UpdateSystemConfigRequest(BaseModel):
    """Update request payload."""

    config_version: str
    mask_token: str = "******"
    reload_now: bool = True
    items: List[SystemConfigUpdateItem] = Field(..., min_length=1)


class UpdateSystemConfigResponse(BaseModel):
    """Update operation result payload."""

    success: bool
    config_version: str
    applied_count: int
    skipped_masked_count: int
    reload_triggered: bool
    updated_keys: List[str]
    warnings: List[str] = Field(default_factory=list)


class ValidateSystemConfigRequest(BaseModel):
    """Validation request payload."""

    items: List[SystemConfigUpdateItem] = Field(..., min_length=1)


class ImportSystemConfigRequest(BaseModel):
    """Import request payload for raw `.env` backups."""

    config_version: str
    content: str
    reload_now: bool = True


class ConfigValidationIssue(BaseModel):
    """Validation issue details."""

    key: str
    code: str
    message: str
    severity: Literal["error", "warning"]
    expected: Optional[str] = None
    actual: Optional[str] = None


class ValidateSystemConfigResponse(BaseModel):
    """Validation result payload."""

    valid: bool
    issues: List[ConfigValidationIssue]


class TestLLMChannelRequest(BaseModel):
    """Request payload for testing one LLM channel."""

    name: str = "channel"
    protocol: str = "openai"
    base_url: str = ""
    api_key: str = ""
    models: List[str] = Field(default_factory=list)
    enabled: bool = True
    timeout_seconds: float = 20.0
    capability_checks: List[LLMCapabilityCheck] = Field(default_factory=list)


class LLMCapabilityCheckResult(BaseModel):
    """Runtime capability smoke result for one requested check."""

    status: Literal["passed", "failed", "skipped"]
    message: str
    error_code: Optional[str] = None
    stage: str
    retryable: bool = False
    latency_ms: Optional[int] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class TestLLMChannelResponse(BaseModel):
    """Response payload for one LLM channel connectivity test."""

    success: bool
    message: str
    error: Optional[str] = None
    error_code: Optional[str] = None
    stage: Optional[str] = None
    retryable: Optional[bool] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    resolved_protocol: Optional[str] = None
    resolved_model: Optional[str] = None
    latency_ms: Optional[int] = None
    capability_results: Dict[str, LLMCapabilityCheckResult] = Field(default_factory=dict)


class NotificationTestAttempt(BaseModel):
    """One notification delivery attempt result."""

    channel: NotificationTestChannel
    success: bool
    message: str
    target: Optional[str] = None
    error_code: Optional[str] = None
    stage: str = "notification_send"
    retryable: bool = False
    latency_ms: Optional[int] = None
    http_status: Optional[int] = None


class TestNotificationChannelRequest(BaseModel):
    """Request payload for testing one notification channel."""

    channel: NotificationTestChannel
    items: List[SystemConfigUpdateItem] = Field(default_factory=list)
    mask_token: str = "******"
    title: str = Field(default="DSA 通知测试", min_length=1, max_length=80)
    content: str = Field(default="这是一条来自 DSA Web 设置页的通知测试消息。", min_length=1, max_length=1000)
    timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)


class TestNotificationChannelResponse(BaseModel):
    """Response payload for one notification channel connectivity test."""

    success: bool
    message: str
    error_code: Optional[str] = None
    stage: Optional[str] = None
    retryable: bool = False
    latency_ms: Optional[int] = None
    attempts: List[NotificationTestAttempt] = Field(default_factory=list)


class DiscoverLLMChannelModelsRequest(BaseModel):
    """Request payload for discovering models from one LLM channel."""

    name: str = "channel"
    protocol: str = "openai"
    base_url: str = ""
    api_key: str = ""
    models: List[str] = Field(default_factory=list)
    timeout_seconds: float = 20.0


class DiscoverLLMChannelModelsResponse(BaseModel):
    """Response payload for one LLM channel model discovery request."""

    success: bool
    message: str
    error: Optional[str] = None
    error_code: Optional[str] = None
    stage: Optional[str] = None
    retryable: Optional[bool] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    resolved_protocol: Optional[str] = None
    models: List[str] = Field(default_factory=list)
    latency_ms: Optional[int] = None


class SystemConfigValidationErrorResponse(BaseModel):
    """Error payload for failed update validation."""

    error: str
    message: str
    issues: List[ConfigValidationIssue]


class SystemConfigConflictResponse(BaseModel):
    """Error payload for optimistic lock conflict."""

    error: str
    message: str
    current_config_version: str
