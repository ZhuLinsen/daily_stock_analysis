"""Write the smallest public-safe daily artifact for Finsance.

The normal report contains private trading levels and raw provider payloads.
This module deliberately builds a new allow-list payload instead of serialising
AnalysisResult.to_dict().
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


SCHEMA_VERSION = "finsance-quanttrade-daily-v1"
DEFAULT_OUTPUT_DIR = Path("reports") / "finsance"
_SECRET_RE = re.compile(r"(?i)(?:bearer\s+|sk-|AIza)[A-Za-z0-9._-]{8,}")


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _text(value: Any, limit: int = 600) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _safe_text(value: Any, limit: int = 600) -> Optional[str]:
    text = _text(value, limit)
    return _SECRET_RE.sub("[redacted]", text) if text else None


def _items(value: Any, limit: int = 5) -> list[str]:
    if value is None:
        return []
    values: Iterable[Any] = value if isinstance(value, (list, tuple, set)) else [value]
    result: list[str] = []
    for item in values:
        text = _safe_text(item, 500)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _dashboard(result: Any) -> dict[str, Any]:
    dashboard = _value(result, "dashboard", {})
    return dashboard if isinstance(dashboard, Mapping) else {}


def _market_for_ticker(ticker: str) -> str:
    code = ticker.upper()
    if code.endswith(".HK") or code.startswith("HK"):
        return "hk_stock"
    if code.endswith(".TW") or code.endswith(".TWO"):
        return "tw_stock"
    if code.isdigit() and len(code) in (4, 5, 6):
        return "cn_stock"
    return "us_stock"


def _quality(result: Any, dashboard: Mapping[str, Any]) -> dict[str, Any]:
    overview = _value(result, "analysis_context_pack_overview")
    candidates = [
        _value(result, "data_quality"),
        overview.get("data_quality") if isinstance(overview, Mapping) else None,
        dashboard.get("data_quality"),
        dashboard.get("analysis_context_pack_overview", {}).get("data_quality")
        if isinstance(dashboard.get("analysis_context_pack_overview"), Mapping)
        else None,
        _value(result, "market_snapshot"),
    ]
    quality: Mapping[str, Any] = {}
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            quality = candidate
            break
    stale = quality.get("stale")
    if not isinstance(stale, bool):
        stale = None
    bar_asof = (
        quality.get("bar_asof")
        or quality.get("effective_bar_date")
        or quality.get("asof")
        or quality.get("date")
    )
    return {"stale": stale, "bar_asof": _safe_text(bar_asof, 64)}


def _stock_payload(result: Any) -> dict[str, Any]:
    dashboard = _dashboard(result)
    core = dashboard.get("core_conclusion")
    core = core if isinstance(core, Mapping) else {}
    intelligence = dashboard.get("intelligence")
    intelligence = intelligence if isinstance(intelligence, Mapping) else {}
    phase = dashboard.get("phase_decision")
    phase = phase if isinstance(phase, Mapping) else {}

    ticker = _safe_text(_value(result, "code"), 64) or "unknown"
    success = bool(_value(result, "success", True))
    risks = _items(intelligence.get("risk_alerts"))
    for risk in _items(_value(result, "risk_warning")):
        if risk not in risks:
            risks.append(risk)
    unknowns = _items(phase.get("data_limitations"))
    error_message = _safe_text(_value(result, "error_message"), 500)
    if not success and error_message and error_message not in unknowns:
        unknowns.append(error_message)

    summary = (
        _safe_text(core.get("one_sentence"), 800)
        or _safe_text(_value(result, "analysis_summary"), 800)
        or "ยังไม่มีสรุปจาก AI"
    )
    score = _value(result, "sentiment_score")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        score = None

    return {
        "ticker": ticker,
        "name": _safe_text(_value(result, "name"), 160) or ticker,
        "market": _market_for_ticker(ticker),
        "status": "ok" if success else "unavailable",
        "decision": _safe_text(
            _value(result, "action") or _value(result, "decision_type"), 32
        ),
        "action_label": _safe_text(_value(result, "action_label"), 80),
        "score": score,
        "trend": _safe_text(_value(result, "trend_prediction"), 120),
        "confidence": _safe_text(_value(result, "confidence_level"), 40),
        "summary_th": summary,
        "catalysts": _items(intelligence.get("positive_catalysts")),
        "risks": risks[:5],
        "unknowns": unknowns[:5],
        "data_quality": _quality(result, dashboard),
        "data_sources": _safe_text(_value(result, "data_sources"), 600),
        "search_performed": bool(_value(result, "search_performed", False)),
        "model_used": _safe_text(_value(result, "model_used"), 160),
    }


def build_public_daily_payload(
    results: Iterable[Any],
    *,
    report_date: Optional[date | datetime | str] = None,
) -> dict[str, Any]:
    stocks = [_stock_payload(result) for result in results if result is not None]
    if isinstance(report_date, datetime):
        date_text = report_date.date().isoformat()
    elif isinstance(report_date, date):
        date_text = report_date.isoformat()
    elif report_date:
        date_text = str(report_date)
    else:
        date_text = date.today().isoformat()

    models = [stock["model_used"] for stock in stocks if stock["model_used"]]
    providers = sorted(
        {
            model.split("/", 1)[0]
            for model in models
            if "/" in model
        }
    )
    any_success = any(stock["status"] == "ok" for stock in stocks)
    ai_status = "ok" if any_success and models else "fallback" if any_success else "unavailable"

    commercial = os.getenv("FINSANCE_COMMERCIAL_MODE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    commercial_provider = _safe_text(os.getenv("FINSANCE_COMMERCIAL_PROVIDER"), 120)
    publication_enabled = os.getenv(
        "FINSANCE_PUBLICATION_ENABLED", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    blockers = ["provider_licensing_review", "compliance_review", "production_verification"]
    if commercial and not commercial_provider:
        blockers.append("commercial_provider_not_configured")

    return {
        "schema_version": SCHEMA_VERSION,
        "date": date_text,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "stocks": stocks,
        "ai": {
            "status": ai_status,
            "provider": ",".join(providers) or None,
            "requested_order": ["gemini", "openai"],
            "fallback": "openai",
        },
        "data_mode": {
            "commercial": commercial,
            "provider": commercial_provider,
            "free_sources": [] if commercial else ["yfinance", "akshare", "baostock"],
        },
        "publication": {
            "status": "public_candidate" if publication_enabled else "not_live",
            "enabled": publication_enabled,
            "blockers": blockers,
        },
        "disclaimer": "ข้อมูลเพื่อการศึกษาเท่านั้น ไม่ใช่คำแนะนำการลงทุน",
    }


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_bytes(data)
    temp_path.replace(path)


def _write_with_checksum(path: Path, data: bytes) -> None:
    _write_atomic(path, data)
    digest = hashlib.sha256(data).hexdigest()
    _write_atomic(path.with_name(f"{path.name}.sha256"), f"{digest}  {path.name}\n".encode())


def write_daily_export(
    results: Iterable[Any],
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    report_date: Optional[date | datetime | str] = None,
) -> Optional[Path]:
    """Write an immutable date file plus the mutable latest pointer."""
    results = [result for result in results if result is not None]
    if not results:
        return None
    payload = build_public_daily_payload(results, report_date=report_date)
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    root = Path(output_dir)
    daily_path = root / f"daily_{payload['date']}.json"
    if not daily_path.exists():
        _write_with_checksum(daily_path, data)
    elif not daily_path.with_name(f"{daily_path.name}.sha256").exists():
        _write_with_checksum(
            daily_path,
            daily_path.read_bytes(),
        )
    latest_path = root / "daily_latest.json"
    _write_with_checksum(latest_path, data)
    return latest_path


__all__ = ["SCHEMA_VERSION", "build_public_daily_payload", "write_daily_export"]
