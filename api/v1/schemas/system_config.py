# -*- coding: utf-8 -*-
"""System configuration API schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    options: List[str] = Field(default_factory=list)
    validation: Dict[str, Any] = Field(default_factory=dict)
    display_order: int


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
