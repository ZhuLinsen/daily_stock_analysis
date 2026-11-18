# -*- coding: utf-8 -*-
"""Read-only, offline diagnostic summary service for CLI/Actions `--doctor`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from src.config import Config, get_configured_llm_models
from src.core.config_registry import _is_sensitive_key, get_field_definition
from src.llm.local_cli_backend import redact_diagnostic_text
from src.services.notification_diagnostics import run_notification_diagnostics


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


def _check_dir_writable(path_value: Optional[str]) -> bool:
    if not path_value:
        return False
    try:
        target = Path(path_value).expanduser()
        probe = target if target.is_dir() else target.parent
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        return probe.exists() and os.access(probe, os.W_OK | os.X_OK)
    except OSError:
        return False


def run_doctor_diagnostics(config: Config) -> Dict[str, Any]:
    """Run offline, redacted configuration/LLM/notification/storage diagnostics."""
    secrets = _collect_secret_literals(config)
    issues = config.validate_structured()

    config_errors: List[Dict[str, Any]] = []
    config_warnings: List[Dict[str, Any]] = []
    config_info: List[Dict[str, Any]] = []
    has_llm_config_error = False
    for issue in issues:
        entry = {
            "field": issue.field,
            "message": _sanitize_text(issue.message, secrets),
        }
        if issue.severity == "error":
            config_errors.append(entry)
            if issue.field in ("LITELLM_CONFIG", "LLM_CHANNELS"):
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

    notify_diag = run_notification_diagnostics(config)
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
    if notify_errors:
        notify_status = "error"
    elif notify_warnings or not notify_diag.configured_channels:
        notify_status = "warn"
    else:
        notify_status = "ok"

    db_path = getattr(config, "database_path", None)
    db_parent = str(Path(db_path).expanduser().parent) if db_path else None
    db_writable = _check_dir_writable(db_parent)
    log_writable = _check_dir_writable(getattr(config, "log_dir", None))
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

    # LLM errors are already included in `config_errors`; `no_channels_configured`
    # overlaps with `WECHAT_WEBHOOK_URL` in `config_warnings` — do not double-count.
    has_config_no_notify_warn = any(w.get("field") == "WECHAT_WEBHOOK_URL" for w in config_warnings)
    dedup_notify_warn_count = len(notify_warnings) - (
        len(no_channel_warnings) if has_config_no_notify_warn else 0
    )
    total_errors = len(config_errors) + len(notify_errors) + (0 if storage_status == "ok" else 1)
    total_warnings = len(config_warnings) + max(0, dedup_notify_warn_count) + (0 if watchlist_count > 0 else 1)

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
                "configured_channels": list(notify_diag.configured_channels),
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
