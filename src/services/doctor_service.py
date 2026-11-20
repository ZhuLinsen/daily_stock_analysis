# -*- coding: utf-8 -*-
"""Read-only, offline diagnostic summary service for CLI/Actions `--doctor`."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

from src.config import Config, get_configured_llm_models
from src.core.config_registry import _is_sensitive_key, get_field_definition
from src.llm.local_cli_backend import redact_diagnostic_text
from src.services.notification_diagnostics import run_notification_diagnostics
from src.services.system_config_service import check_database_path_usable, check_dir_writable


_EXTRA_SENSITIVE_ATTRS = frozenset({
    "serpapi_keys",
    "tavily_api_keys",
    "bocha_api_keys",
    "brave_api_keys",
    "minimax_api_keys",
    "anspire_api_keys",
    "custom_webhook_urls",
    "custom_webhook_bearer_token",
    "feishu_app_id",
    "dingtalk_app_key",
})

_LLM_ISSUE_FIELDS = frozenset({
    "LITELLM_CONFIG",
    "LLM_CHANNELS",
    "LITELLM_MODEL",
    "LITELLM_FALLBACK_MODELS",
    "AGENT_LITELLM_MODEL",
    "VISION_MODEL",
    "GENERATION_BACKEND",
    "GENERATION_FALLBACK_BACKEND",
    "AGENT_GENERATION_BACKEND",
    "AGENT_BACKEND",
    "OPENCODE_CLI_MODEL",
})


def _is_llm_issue_field(field: Any) -> bool:
    name = str(field or "").strip().upper()
    if not name:
        return False
    return name in _LLM_ISSUE_FIELDS or name.startswith((
        "LLM_",
        "LITELLM_",
        "GENERATION_",
        "AGENT_",
        "OPENAI_",
        "GEMINI_",
        "ANTHROPIC_",
        "DEEPSEEK_",
        "OPENCODE_",
    ))


def _is_sensitive_name(name: str) -> bool:
    upper = name.upper()
    meta = get_field_definition(upper)
    if isinstance(meta, dict) and meta.get("is_sensitive"):
        return True
    return _is_sensitive_key(upper) or "WEBHOOK" in upper or name in _EXTRA_SENSITIVE_ATTRS


def _append_secret_value(out: List[str], value: Any) -> None:
    if isinstance(value, str):
        stripped = value.strip()
        if len(stripped) >= 4:
            out.append(stripped)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            if isinstance(item, str):
                stripped = item.strip()
                if len(stripped) >= 4:
                    out.append(stripped)


def _collect_secret_literals(config: Config) -> List[str]:
    literals: List[str] = []

    for env_key, env_val in os.environ.items():
        if _is_sensitive_name(env_key):
            _append_secret_value(literals, env_val)

    for attr, val in vars(config).items():
        if _is_sensitive_name(attr):
            _append_secret_value(literals, val)

    for entry in getattr(config, "llm_model_list", None) or []:
        if isinstance(entry, dict):
            params = entry.get("litellm_params")
            if isinstance(params, dict):
                _append_secret_value(literals, params.get("api_key"))

    return sorted(set(literals), key=len, reverse=True)


def _sanitize_text(text: Any, secret_literals: Iterable[str]) -> str:
    rendered = redact_diagnostic_text(str(text or ""))
    for secret in secret_literals:
        if secret and secret in rendered:
            rendered = rendered.replace(secret, "***")
    return rendered


def run_doctor_diagnostics(config: Config) -> Dict[str, Any]:
    """Run offline, redacted configuration/LLM/notification/storage diagnostics."""
    secrets = _collect_secret_literals(config)

    config_errors: List[Dict[str, Any]] = []
    config_warnings: List[Dict[str, Any]] = []
    config_info: List[Dict[str, Any]] = []
    has_llm_config_error = False

    try:
        issues = config.validate_structured()
    except Exception as exc:
        issues = []
        config_errors.append({
            "field": "CONFIG",
            "message": _sanitize_text(f"配置校验失败: {exc}", secrets),
        })

    for issue in issues:
        entry = {
            "field": issue.field,
            "message": _sanitize_text(issue.message, secrets),
        }
        if issue.severity == "error":
            config_errors.append(entry)
            if _is_llm_issue_field(issue.field):
                has_llm_config_error = True
        elif issue.severity == "warning":
            config_warnings.append(entry)
        else:
            config_info.append(entry)

    config_status = "error" if config_errors else ("warn" if config_warnings else "ok")

    generation_backend = str(getattr(config, "generation_backend", "litellm") or "litellm").strip().lower()
    configured_models = get_configured_llm_models(getattr(config, "llm_model_list", []) or [])
    llm_ready = not has_llm_config_error
    llm_status = "ok" if llm_ready else "error"

    try:
        notify_diag = run_notification_diagnostics(config)
        notify_configured_channels = list(notify_diag.configured_channels)
        notify_errors = [
            {"code": i.code, "key": i.key, "message": _sanitize_text(i.message, secrets)}
            for i in notify_diag.errors
            if i.code != "no_channels_configured"
        ]
        no_channel_warnings = [
            {"code": i.code, "key": i.key, "message": _sanitize_text(i.message, secrets)}
            for i in notify_diag.errors
            if i.code == "no_channels_configured"
        ]
        notify_warnings = no_channel_warnings + [
            {"code": i.code, "key": i.key, "message": _sanitize_text(i.message, secrets)}
            for i in notify_diag.warnings
        ]
    except Exception as exc:
        notify_configured_channels = []
        no_channel_warnings = []
        notify_errors = [{
            "code": "diagnostics_failed",
            "key": "NOTIFICATION",
            "message": _sanitize_text(f"通知诊断失败: {exc}", secrets),
        }]
        notify_warnings = []

    if notify_errors:
        notify_status = "error"
    elif notify_warnings or not notify_configured_channels:
        notify_status = "warn"
    else:
        notify_status = "ok"

    db_path = getattr(config, "database_path", None)
    db_writable = check_database_path_usable(db_path)
    log_writable = check_dir_writable(getattr(config, "log_dir", None))
    storage_status = "ok" if (db_writable and log_writable) else "error"

    watchlist_count = len(getattr(config, "stock_list", None) or [])
    watchlist_status = "ok" if watchlist_count > 0 else "warn"

    statuses = (config_status, llm_status, notify_status, storage_status, watchlist_status)
    if "error" in statuses:
        overall_status = "error"
    elif "warn" in statuses:
        overall_status = "warn"
    else:
        overall_status = "ok"

    # Deduplicate overlapping issues reported in both Config.validate_structured() and
    # downstream sections (e.g. NTFY_URL/GOTIFY_URL, no-channels, empty STOCK_LIST).
    error_fields = {
        str(item.get("field") or "").strip().upper()
        for item in config_errors
        if str(item.get("field") or "").strip()
    }
    warning_fields = {
        str(item.get("field") or "").strip().upper()
        for item in config_warnings
        if str(item.get("field") or "").strip()
    }

    extra_notify_errors = 0
    seen_notify_err_keys: set[str] = set()
    for err in notify_errors:
        key = str(err.get("key") or err.get("code") or "").strip().upper()
        if key and key in error_fields:
            continue
        if key and key in seen_notify_err_keys:
            continue
        if key:
            seen_notify_err_keys.add(key)
        extra_notify_errors += 1

    has_config_no_notify_warn = "WECHAT_WEBHOOK_URL" in warning_fields
    extra_notify_warnings = 0
    for warn in notify_warnings:
        code = str(warn.get("code") or "").strip().lower()
        key = str(warn.get("key") or "").strip().upper()
        if code == "no_channels_configured" and has_config_no_notify_warn:
            continue
        if key and (key in error_fields or key in warning_fields):
            continue
        extra_notify_warnings += 1

    extra_watchlist_warnings = 0 if (watchlist_count > 0 or "STOCK_LIST" in error_fields or "STOCK_LIST" in warning_fields) else 1

    total_errors = len(config_errors) + extra_notify_errors + (0 if storage_status == "ok" else 1)
    total_warnings = len(config_warnings) + extra_notify_warnings + extra_watchlist_warnings

    return {
        "status": overall_status,
        "summary": {
            "errors": total_errors,
            "warnings": total_warnings,
        },
        "checks": {
            "config": {
                "status": config_status,
                "errors": config_errors,
                "warnings": config_warnings,
                "info": config_info,
            },
            "llm": {
                "status": llm_status,
                "generation_backend": generation_backend,
                "configured_models_count": len(configured_models),
                "ready": llm_ready,
            },
            "notifications": {
                "status": notify_status,
                "configured_channels": notify_configured_channels,
                "errors": notify_errors,
                "warnings": notify_warnings,
            },
            "storage": {
                "status": storage_status,
                "database_dir_writable": db_writable,
                "log_dir_writable": log_writable,
            },
            "watchlist": {
                "status": watchlist_status,
                "count": watchlist_count,
            },
        },
    }


def format_doctor_report(report: Dict[str, Any]) -> str:
    """Render a human-readable, redacted doctor report."""
    checks = report.get("checks", {})
    summary = report.get("summary", {})
    status = str(report.get("status", "unknown")).upper()

    lines = [
        f"DSA Doctor Diagnostic Status: {status} "
        f"(errors={summary.get('errors', 0)}, warnings={summary.get('warnings', 0)})",
        "-" * 60,
    ]

    llm = checks.get("llm", {})
    lines.append(
        f"[llm] status={llm.get('status')} backend={llm.get('generation_backend')} "
        f"models={llm.get('configured_models_count')} ready={llm.get('ready')}"
    )

    notify = checks.get("notifications", {})
    channels = ", ".join(notify.get("configured_channels") or []) or "none"
    lines.append(f"[notifications] status={notify.get('status')} channels={channels}")
    for err in notify.get("errors", []):
        lines.append(f"  ERROR ({err.get('key') or err.get('code')}): {err.get('message')}")
    for warn in notify.get("warnings", []):
        lines.append(f"  WARN  ({warn.get('key') or warn.get('code')}): {warn.get('message')}")

    storage = checks.get("storage", {})
    lines.append(
        f"[storage] status={storage.get('status')} "
        f"db_dir_writable={storage.get('database_dir_writable')} "
        f"log_dir_writable={storage.get('log_dir_writable')}"
    )

    watchlist = checks.get("watchlist", {})
    lines.append(f"[watchlist] status={watchlist.get('status')} count={watchlist.get('count')}")

    cfg = checks.get("config", {})
    lines.append(f"[config] status={cfg.get('status')}")
    for err in cfg.get("errors", []):
        lines.append(f"  ERROR ({err.get('field')}): {err.get('message')}")
    for warn in cfg.get("warnings", []):
        lines.append(f"  WARN  ({warn.get('field')}): {warn.get('message')}")

    return "\n".join(lines)
