# -*- coding: utf-8 -*-
"""Configuration field metadata registry.

This module is the single source of truth for configuration UI metadata,
validation hints, and category grouping.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "2026-02-09"

_CATEGORY_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "category": "base",
        "title": "Base Settings",
        "description": "Watchlist and foundational application settings.",
        "display_order": 10,
    },
    {
        "category": "ai_model",
        "title": "AI Model",
        "description": "Model providers, model names, and inference parameters.",
        "display_order": 20,
    },
    {
        "category": "data_source",
        "title": "Data Source",
        "description": "Market data provider credentials and priority settings.",
        "display_order": 30,
    },
    {
        "category": "notification",
        "title": "Notification",
        "description": "Bot, webhook, and push channel related settings.",
        "display_order": 40,
    },
    {
        "category": "system",
        "title": "System",
        "description": "Runtime and scheduling controls.",
        "display_order": 50,
    },
    {
        "category": "agent",
        "title": "Agent",
        "description": "Agent mode and strategy settings.",
        "display_order": 55,
    },
    {
        "category": "backtest",
        "title": "Backtest",
        "description": "Backtest engine behavior and evaluation parameters.",
        "display_order": 60,
    },
    {
        "category": "uncategorized",
        "title": "Uncategorized",
        "description": "Keys not mapped in the field registry.",
        "display_order": 99,
    },
]

_FIELD_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "STOCK_LIST": {
        "title": "Stock List",
        "description": "Comma-separated watchlist stock codes.",
        "category": "base",
        "data_type": "array",
        "ui_control": "textarea",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "600519,300750,002594",
        "options": [],
        "validation": {"min_items": 1},
        "display_order": 10,
    },
    "TUSHARE_TOKEN": {
        "title": "Tushare Token",
        "description": "Token for Tushare Pro API.",
        "category": "data_source",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 10,
    },
    "REALTIME_SOURCE_PRIORITY": {
        "title": "Realtime Source Priority",
        "description": "Comma-separated priority for realtime quote providers.",
        "category": "data_source",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "tencent,akshare_sina,efinance,akshare_em",
        "options": [],
        "validation": {},
        "display_order": 20,
    },
    "ENABLE_REALTIME_TECHNICAL_INDICATORS": {
        "title": "Realtime Technical Indicators",
        "description": "Use intraday realtime price for MA5/MA10/MA20 and trend analysis (Issue #234). Disable to use yesterday close.",
        "category": "data_source",
        "data_type": "boolean",
        "ui_control": "switch",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "true",
        "options": [],
        "validation": {},
        "display_order": 21,
    },
    "TAVILY_API_KEYS": {
        "title": "Tavily API Keys",
        "description": "Comma-separated Tavily API keys.",
        "category": "data_source",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {"multi_value": True, "delimiter": ","},
        "display_order": 30,
    },
    "SERPAPI_API_KEYS": {
        "title": "SerpAPI Keys",
        "description": "Comma-separated SerpAPI keys.",
        "category": "data_source",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {"multi_value": True, "delimiter": ","},
        "display_order": 40,
    },
    "BRAVE_API_KEYS": {
        "title": "Brave API Keys",
        "description": "Comma-separated Brave Search API keys.",
        "category": "data_source",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {"multi_value": True, "delimiter": ","},
        "display_order": 50,
    },
    "PYTDX_HOST": {
        "title": "Pytdx Host",
        "description": "Tongdaxin data server IP. Used with PYTDX_PORT. Overrides built-in defaults.",
        "category": "data_source",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 55,
    },
    "PYTDX_PORT": {
        "title": "Pytdx Port",
        "description": "Tongdaxin data server port (e.g. 7709). Used with PYTDX_HOST.",
        "category": "data_source",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 56,
    },
    "PYTDX_SERVERS": {
        "title": "Pytdx Servers",
        "description": "Comma-separated ip:port (e.g. 192.168.1.1:7709,10.0.0.1:7709). Overrides PYTDX_HOST+PYTDX_PORT.",
        "category": "data_source",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 57,
    },
    "GEMINI_API_KEY": {
        "title": "Gemini API Key",
        "description": "API key for Gemini service.",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 10,
    },
    "GEMINI_MODEL": {
        "title": "Gemini Model",
        "description": "Gemini model name.",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "gemini-3-flash-preview",
        "options": [],
        "validation": {},
        "display_order": 20,
    },
    "GEMINI_TEMPERATURE": {
        "title": "Gemini Temperature",
        "description": "Temperature in range [0.0, 2.0].",
        "category": "ai_model",
        "data_type": "number",
        "ui_control": "number",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "0.7",
        "options": [],
        "validation": {"min": 0.0, "max": 2.0},
        "display_order": 30,
    },
    "OPENAI_API_KEY": {
        "title": "OpenAI API Key",
        "description": "API key for OpenAI-compatible service.",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 40,
    },
    "OPENAI_BASE_URL": {
        "title": "OpenAI Base URL",
        "description": "Base URL for OpenAI-compatible endpoint.",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 50,
    },
    "OPENAI_MODEL": {
        "title": "OpenAI Model",
        "description": "Model name for OpenAI-compatible endpoint.",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "gpt-4o-mini",
        "options": [],
        "validation": {},
        "display_order": 60,
    },
    "OPENAI_VISION_MODEL": {
        "title": "OpenAI Vision Model",
        "description": "Model for image extraction (some APIs e.g. DeepSeek lack vision). Leave empty to use OPENAI_MODEL.",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 61,
    },
    "ANTHROPIC_API_KEY": {
        "title": "Anthropic API Key",
        "description": "Anthropic Claude 服务的 API Key。",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 35,
    },
    "ANTHROPIC_MODEL": {
        "title": "Anthropic Model",
        "description": "Claude 模型名称（如 claude-3-5-sonnet-20241022）。",
        "category": "ai_model",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "claude-3-5-sonnet-20241022",
        "options": [],
        "validation": {},
        "display_order": 36,
    },
    "ANTHROPIC_TEMPERATURE": {
        "title": "Anthropic Temperature",
        "description": "温度参数，范围 [0.0, 1.0]。",
        "category": "ai_model",
        "data_type": "number",
        "ui_control": "number",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "0.7",
        "options": [],
        "validation": {"min": 0.0, "max": 1.0},
        "display_order": 37,
    },
    "ANTHROPIC_MAX_TOKENS": {
        "title": "Anthropic Max Tokens",
        "description": "Anthropic API 响应最大 token 数（默认 8192）。",
        "category": "ai_model",
        "data_type": "number",
        "ui_control": "number",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "8192",
        "options": [],
        "validation": {"min": 256, "max": 8192},
        "display_order": 38,
    },
    "WECHAT_WEBHOOK_URL": {
        "title": "WeChat Webhook URL",
        "description": "Webhook URL for enterprise WeChat bot.",
        "category": "notification",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 10,
    },
    "DINGTALK_APP_KEY": {
        "title": "DingTalk App Key",
        "description": "DingTalk app key.",
        "category": "notification",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 20,
    },
    "DINGTALK_APP_SECRET": {
        "title": "DingTalk App Secret",
        "description": "DingTalk app secret.",
        "category": "notification",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 30,
    },
    "PUSHPLUS_TOKEN": {
        "title": "PushPlus Token",
        "description": "Token for PushPlus notifications.",
        "category": "notification",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 40,
    },
    "CUSTOM_WEBHOOK_URLS": {
        "title": "Custom Webhook URLs",
        "description": "Comma-separated webhook URLs for custom notifications (DingTalk, Discord, Slack, etc.).",
        "category": "notification",
        "data_type": "array",
        "ui_control": "textarea",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {"multi_value": True, "delimiter": ","},
        "display_order": 50,
    },
    "CUSTOM_WEBHOOK_BEARER_TOKEN": {
        "title": "Custom Webhook Bearer Token",
        "description": "Bearer token for authenticated custom webhooks.",
        "category": "notification",
        "data_type": "string",
        "ui_control": "password",
        "is_sensitive": True,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 51,
    },
    "WEBHOOK_VERIFY_SSL": {
        "title": "Webhook SSL Verify",
        "description": "Verify HTTPS certificates for webhook requests. Set to false ONLY for self-signed certs in trusted internal networks. WARNING: Disabling allows MITM attacks—do NOT use on public networks.",
        "category": "notification",
        "data_type": "boolean",
        "ui_control": "switch",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "true",
        "options": [],
        "validation": {},
        "display_order": 52,
    },
    "REPORT_SUMMARY_ONLY": {
        "title": "Report Summary Only",
        "description": "Push only analysis summary without per-stock details. Suitable for quick overview when tracking many stocks (Issue #262).",
        "category": "notification",
        "data_type": "boolean",
        "ui_control": "switch",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "false",
        "options": [],
        "validation": {},
        "display_order": 53,
    },
    "SCHEDULE_TIME": {
        "title": "Schedule Time",
        "description": "Daily schedule time in HH:MM format.",
        "category": "system",
        "data_type": "time",
        "ui_control": "time",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "18:00",
        "options": [],
        "validation": {"pattern": r"^([01]\d|2[0-3]):[0-5]\d$"},
        "display_order": 10,
    },
    "HTTP_PROXY": {
        "title": "HTTP Proxy",
        "description": "Optional HTTP proxy endpoint.",
        "category": "system",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 20,
    },
    "LOG_LEVEL": {
        "title": "Log Level",
        "description": "Application log level.",
        "category": "system",
        "data_type": "string",
        "ui_control": "select",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "INFO",
        "options": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        "validation": {"enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]},
        "display_order": 30,
    },
    "WEBUI_PORT": {
        "title": "Web UI Port",
        "description": "Port for Web UI service.",
        "category": "system",
        "data_type": "integer",
        "ui_control": "number",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "8000",
        "options": [],
        "validation": {"min": 1, "max": 65535},
        "display_order": 40,
    },
    "RUN_IMMEDIATELY": {
        "title": "Run Immediately",
        "description": "Whether to run analysis immediately on startup (non-schedule mode).",
        "category": "system",
        "data_type": "boolean",
        "ui_control": "switch",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "true",
        "options": [],
        "validation": {},
        "display_order": 45,
    },
    "BACKTEST_ENABLED": {
        "title": "Backtest Enabled",
        "description": "Whether backtest is enabled.",
        "category": "backtest",
        "data_type": "boolean",
        "ui_control": "switch",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "true",
        "options": [],
        "validation": {},
        "display_order": 10,
    },
    "BACKTEST_EVAL_WINDOW_DAYS": {
        "title": "Backtest Eval Window Days",
        "description": "Backtest evaluation window in trading days.",
        "category": "backtest",
        "data_type": "integer",
        "ui_control": "number",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "10",
        "options": [],
        "validation": {"min": 1, "max": 365},
        "display_order": 20,
    },
    "BACKTEST_MIN_AGE_DAYS": {
        "title": "Backtest Min Age Days",
        "description": "Only evaluate analysis records older than this threshold.",
        "category": "backtest",
        "data_type": "integer",
        "ui_control": "number",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "14",
        "options": [],
        "validation": {"min": 0, "max": 3650},
        "display_order": 30,
    },
    "BACKTEST_ENGINE_VERSION": {
        "title": "Backtest Engine Version",
        "description": "Backtest engine version label.",
        "category": "backtest",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "v1",
        "options": [],
        "validation": {},
        "display_order": 40,
    },
    "BACKTEST_NEUTRAL_BAND_PCT": {
        "title": "Backtest Neutral Band Pct",
        "description": "Neutral return band percentage for outcome labeling.",
        "category": "backtest",
        "data_type": "number",
        "ui_control": "number",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "2.0",
        "options": [],
        "validation": {"min": 0.0, "max": 100.0},
        "display_order": 50,
    },
    "AGENT_MODE": {
        "title": "Agent Mode",
        "description": "Enable ReAct Agent for stock analysis.",
        "category": "agent",
        "data_type": "boolean",
        "ui_control": "switch",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "false",
        "options": [],
        "validation": {},
        "display_order": 10,
    },
    "AGENT_MAX_STEPS": {
        "title": "Agent Max Steps",
        "description": "Maximum number of steps the agent can take.",
        "category": "agent",
        "data_type": "integer",
        "ui_control": "number",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "10",
        "options": [],
        "validation": {"min": 1, "max": 50},
        "display_order": 20,
    },
    "AGENT_SKILLS": {
        "title": "Agent Skills",
        "description": "Comma-separated list of active agent strategies. When set to specific strategies (not 'all'), scheduled tasks will automatically use the Agent pipeline.",
        "category": "agent",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "bull_trend,ma_golden_cross,volume_breakout,shrink_pullback",
        "options": [],
        "validation": {},
        "display_order": 30,
    },
    "AGENT_STRATEGY_DIR": {
        "title": "Agent Strategy Dir",
        "description": "Directory containing agent strategy YAML files.",
        "category": "agent",
        "data_type": "string",
        "ui_control": "text",
        "is_sensitive": False,
        "is_required": False,
        "is_editable": True,
        "default_value": "strategies",
        "options": [],
        "validation": {},
        "display_order": 40,
    },
}


def get_category_definitions() -> List[Dict[str, Any]]:
    """Return deep-copied category metadata."""
    return deepcopy(_CATEGORY_DEFINITIONS)


def get_registered_field_keys() -> List[str]:
    """Return all explicitly registered keys."""
    return list(_FIELD_DEFINITIONS.keys())


def get_field_definition(key: str, value_hint: Optional[str] = None) -> Dict[str, Any]:
    """Return field definition for key, including inferred fallback metadata."""
    key_upper = key.upper()
    if key_upper in _FIELD_DEFINITIONS:
        field = deepcopy(_FIELD_DEFINITIONS[key_upper])
        field["key"] = key_upper
        return field

    category = _infer_category(key_upper)
    data_type = _infer_data_type(key_upper, value_hint)
    field = {
        "key": key_upper,
        "title": key_upper.replace("_", " ").title(),
        "description": "Auto-inferred field metadata.",
        "category": category,
        "data_type": data_type,
        "ui_control": _infer_ui_control(data_type, key_upper),
        "is_sensitive": _is_sensitive_key(key_upper),
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 9000,
    }
    return field


def build_schema_response() -> Dict[str, Any]:
    """Build schema payload grouped by category."""
    category_map: Dict[str, Dict[str, Any]] = {}
    for category in get_category_definitions():
        category_map[category["category"]] = {**category, "fields": []}

    for key in sorted(_FIELD_DEFINITIONS.keys()):
        field = get_field_definition(key)
        category_map[field["category"]]["fields"].append(field)

    categories = sorted(category_map.values(), key=lambda item: item["display_order"])
    for category in categories:
        category["fields"] = sorted(
            category["fields"],
            key=lambda item: (item.get("display_order", 9999), item["key"]),
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "categories": categories,
    }


def _is_sensitive_key(key: str) -> bool:
    markers = ("KEY", "TOKEN", "SECRET", "PASSWORD")
    return any(marker in key for marker in markers)


def _infer_category(key: str) -> str:
    if key == "STOCK_LIST":
        return "base"
    if key.startswith("BACKTEST_"):
        return "backtest"
    if key.startswith(("GEMINI_", "OPENAI_", "ANTHROPIC_")):
        return "ai_model"
    if key.endswith("_PRIORITY") or key.startswith(
        (
            "TUSHARE",
            "AKSHARE",
            "EFINANCE",
            "PYTDX",
            "BAOSTOCK",
            "YFINANCE",
            "TAVILY",
            "SERPAPI",
            "BRAVE",
        )
    ):
        return "data_source"
    if key.startswith((
        "WECHAT",
        "FEISHU",
        "TELEGRAM",
        "EMAIL",
        "PUSHOVER",
        "PUSHPLUS",
        "SERVERCHAN",
        "DINGTALK",
        "DISCORD",
        "CUSTOM_WEBHOOK",
        "WECOM",
        "ASTRBOT",
    )) or "WEBHOOK" in key:
        return "notification"
    if key.startswith(("LOG_", "SCHEDULE_", "WEBUI_", "HTTP_", "HTTPS_", "MAX_", "DEBUG")):
        return "system"
    return "uncategorized"


def _infer_data_type(key: str, value_hint: Optional[str]) -> str:
    if key.endswith("_TIME"):
        return "time"
    if value_hint is None:
        return "string"

    lowered = value_hint.strip().lower()
    if lowered in {"true", "false"}:
        return "boolean"

    try:
        int(value_hint)
        return "integer"
    except (TypeError, ValueError):
        pass

    try:
        float(value_hint)
        return "number"
    except (TypeError, ValueError):
        pass

    if key in {"STOCK_LIST", "EMAIL_RECEIVERS", "CUSTOM_WEBHOOK_URLS"}:
        return "array"
    return "string"


def _infer_ui_control(data_type: str, key: str) -> str:
    if _is_sensitive_key(key):
        return "password"
    if data_type == "boolean":
        return "switch"
    if data_type in {"integer", "number"}:
        return "number"
    if data_type == "time":
        return "time"
    if data_type == "array":
        return "textarea"
    return "text"
