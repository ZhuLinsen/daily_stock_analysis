# -*- coding: utf-8 -*-
"""
Shared data parsing and normalization helpers.
"""

import json
import math
from typing import Any, Dict, List, Optional, Tuple


_MODEL_PLACEHOLDER_VALUES = {"unknown", "error", "none", "null", "n/a"}
SIGNAL_ATTRIBUTION_WEIGHT_KEYS: Tuple[str, ...] = (
    "technical_indicators",
    "news_sentiment",
    "fundamentals",
    "market_conditions",
)
SIGNAL_ATTRIBUTION_SIGNAL_KEYS: Tuple[str, ...] = (
    "strongest_bullish_signal",
    "strongest_bearish_signal",
)


def normalize_model_used(value: Any) -> Optional[str]:
    """Normalize placeholder/empty model values to None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in _MODEL_PLACEHOLDER_VALUES:
        return None
    return text


def parse_json_field(value: Any) -> Any:
    """Best-effort JSON parse for string values; passthrough for others."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return value
    return value


def _non_empty_dict(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    return value if value else None


def _normalize_belong_boards(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if name is None:
            continue
        name_text = str(name).strip()
        if not name_text:
            continue
        board = {"name": name_text}
        if item.get("code") is not None:
            code_text = str(item.get("code")).strip()
            if code_text:
                board["code"] = code_text
        if item.get("type") is not None:
            type_text = str(item.get("type")).strip()
            if type_text:
                board["type"] = type_text
        normalized.append(board)
    return normalized


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if text.endswith("%"):
                text = text[:-1].strip()
            return float(text)
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_sector_ranking_items(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if name is None:
            continue
        name_text = str(name).strip()
        if not name_text:
            continue
        ranking_item: Dict[str, Any] = {"name": name_text}
        for optional_field in ("code", "source", "updated_at"):
            if item.get(optional_field) is not None:
                optional_text = str(item.get(optional_field)).strip()
                if optional_text:
                    ranking_item[optional_field] = optional_text
        change_pct = _safe_float(item.get("change_pct"))
        if change_pct is not None:
            ranking_item["change_pct"] = change_pct
        normalized.append(ranking_item)
    return normalized


def _normalize_sector_rankings(value: Any) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    if not isinstance(value, dict):
        return None

    return {
        "top": _normalize_sector_ranking_items(value.get("top")),
        "bottom": _normalize_sector_ranking_items(value.get("bottom")),
    }


def _extract_ranking_payload_from_block(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    if "top" in value or "bottom" in value:
        return value

    status = value.get("status")
    if status not in {"ok", "partial", None}:
        return None
    data = value.get("data")
    if isinstance(data, dict):
        return data
    return None


def _is_empty_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _deep_merge_dicts(*values: Any) -> Optional[Dict[str, Any]]:
    merged: Dict[str, Any] = {}
    has_value = False
    for value in values:
        obj = parse_json_field(value)
        if not isinstance(obj, dict):
            continue
        has_value = True
        for key, item in obj.items():
            if _is_empty_value(item):
                continue
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(item, dict):
                nested = _deep_merge_dicts(existing, item)
                if nested:
                    merged[key] = nested
            else:
                merged[key] = item
    return merged if has_value else None


def extract_fundamental_context(
    context_snapshot: Any,
    fallback_fundamental_payload: Any = None,
) -> Optional[Dict[str, Any]]:
    """
    Resolve fundamental_context from context snapshot, with optional fallback payload.
    """
    fallback_obj = parse_json_field(fallback_fundamental_payload)
    top_level_fundamental = None
    enhanced_fundamental = None
    snapshot_obj = parse_json_field(context_snapshot)
    if isinstance(snapshot_obj, dict):
        enhanced = snapshot_obj.get("enhanced_context")
        if isinstance(enhanced, dict):
            fundamental = enhanced.get("fundamental_context")
            if isinstance(fundamental, dict):
                enhanced_fundamental = fundamental
        raw_top_level = snapshot_obj.get("fundamental_context")
        if isinstance(raw_top_level, dict):
            top_level_fundamental = raw_top_level

    return _deep_merge_dicts(
        fallback_obj,
        top_level_fundamental,
        enhanced_fundamental,
    )


def extract_realtime_detail_fields(context_snapshot: Any) -> Dict[str, Any]:
    """
    Extract stable realtime price/change fields from persisted context snapshots.

    Supports both the standard `enhanced_context.realtime` layout and the
    agent-mode top-level `realtime_quote` compatibility shape.
    """
    snapshot_obj = parse_json_field(context_snapshot)
    if not isinstance(snapshot_obj, dict):
        return {"current_price": None, "change_pct": None}

    current_price = None
    change_pct = None

    enhanced = snapshot_obj.get("enhanced_context")
    if isinstance(enhanced, dict):
        realtime = enhanced.get("realtime")
        if isinstance(realtime, dict):
            current_price = realtime.get("price")
            change_pct = realtime.get("change_pct")

    for field in ("realtime_quote_raw", "realtime_quote"):
        realtime_payload = snapshot_obj.get(field)
        if not isinstance(realtime_payload, dict):
            continue
        if current_price is None:
            current_price = realtime_payload.get("price")
        if change_pct is None:
            change_pct = realtime_payload.get("change_pct")
        if change_pct is None:
            change_pct = realtime_payload.get("pct_chg")

    return {
        "current_price": current_price,
        "change_pct": change_pct,
    }


def extract_fundamental_detail_fields(
    context_snapshot: Any,
    fallback_fundamental_payload: Any = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Extract stable API-facing financial and dividend blocks from fundamental_context.
    """
    fundamental_ctx = extract_fundamental_context(
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental_payload,
    )
    if not isinstance(fundamental_ctx, dict):
        return {"financial_report": None, "dividend_metrics": None}

    earnings_block = fundamental_ctx.get("earnings")
    earnings_data = earnings_block.get("data") if isinstance(earnings_block, dict) else None
    if not isinstance(earnings_data, dict):
        return {"financial_report": None, "dividend_metrics": None}

    financial_report = _non_empty_dict(earnings_data.get("financial_report"))
    dividend_metrics = _non_empty_dict(earnings_data.get("dividend"))
    return {
        "financial_report": financial_report,
        "dividend_metrics": dividend_metrics,
    }


def extract_board_detail_fields(
    context_snapshot: Any,
    fallback_fundamental_payload: Any = None,
) -> Dict[str, Any]:
    """
    Extract stable board detail fields from fundamental_context.
    """
    fundamental_ctx = extract_fundamental_context(
        context_snapshot=context_snapshot,
        fallback_fundamental_payload=fallback_fundamental_payload,
    )
    if not isinstance(fundamental_ctx, dict):
        return {"belong_boards": [], "sector_rankings": None, "concept_rankings": None}

    boards_block = fundamental_ctx.get("boards")
    sector_rankings = _extract_ranking_payload_from_block(boards_block)
    concept_rankings = (
        _extract_ranking_payload_from_block(fundamental_ctx.get("concept_boards"))
        or _extract_ranking_payload_from_block(fundamental_ctx.get("concepts"))
        or _extract_ranking_payload_from_block(fundamental_ctx.get("concept_rankings"))
    )
    if concept_rankings is None and isinstance(sector_rankings, dict):
        concept_rankings = _extract_ranking_payload_from_block(sector_rankings.get("concepts"))
    return {
        "belong_boards": _normalize_belong_boards(fundamental_ctx.get("belong_boards")),
        "sector_rankings": _normalize_sector_rankings(sector_rankings),
        "concept_rankings": _normalize_sector_rankings(concept_rankings),
    }


def normalize_signal_attribution_values(signal_attr: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Normalize signal_attribution values in-place.

    - Convert string percentages like "70%" to int 70
    - Convert "N/A", "N/A%", "" to None
    - Clamp negative numbers to 0
    - Normalize four non-zero contributions to sum = 100 (only if all four are valid numbers)
    - Preserve all-zero as "no effective signal"; do not fake 25/25/25/25
    """
    if not isinstance(signal_attr, dict):
        return None

    def _parse_contribution(raw: Any) -> Optional[float]:
        """
        Parse a single contribution value.

        Returns:
            - float in [0, 100] if valid
            - None if unparsable / N/A / empty
        """
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            val = float(raw)
            if not math.isfinite(val):
                return None
            # Clamp to [0, 100] — values outside this range are invalid
            return max(0.0, min(100.0, val))
        if isinstance(raw, str):
            text = raw.strip()
            if not text or text in ("N/A", "N/A%"):
                return None
            text = text.rstrip("%").strip()
            try:
                val = float(text)
                if not math.isfinite(val):
                    return None
                # Clamp to [0, 100]
                return max(0.0, min(100.0, val))
            except ValueError:
                return None
        return None

    parsed: Dict[str, Optional[float]] = {}
    for k in SIGNAL_ATTRIBUTION_WEIGHT_KEYS:
        parsed[k] = _parse_contribution(signal_attr.get(k))

    valid_values = [v for v in parsed.values() if v is not None]
    if len(valid_values) == 4:
        total = sum(valid_values)
        if total > 0:
            normalized = [(v / total) * 100.0 for v in valid_values]
            int_values = [round(v) for v in normalized]
            diff = 100 - sum(int_values)
            if diff != 0:
                max_idx = int_values.index(max(int_values))
                int_values[max_idx] += diff
            for i, k in enumerate(SIGNAL_ATTRIBUTION_WEIGHT_KEYS):
                parsed[k] = int_values[i]
        # else: total == 0 → all contributions are 0
        #   Keep as 0 (truthful "no contribution"), do NOT fake 25/25/25/25
        #   If LLM returned None for some fields, they stay None (meaning "unable to judge")

    for k in SIGNAL_ATTRIBUTION_WEIGHT_KEYS:
        signal_attr[k] = parsed[k]

    for k in SIGNAL_ATTRIBUTION_SIGNAL_KEYS:
        v = signal_attr.get(k)
        if v is not None and isinstance(v, str) and v.strip() == "":
            signal_attr[k] = None

    return signal_attr


def normalize_dashboard_signal_attribution(dashboard: Optional[Dict[str, Any]]) -> None:
    """Normalize signal_attribution in dashboard dict (in-place)."""
    if not isinstance(dashboard, dict):
        return
    signal_attr = dashboard.get("signal_attribution")
    if signal_attr is not None:
        if not isinstance(signal_attr, dict):
            dashboard.pop("signal_attribution", None)
            return
        normalize_signal_attribution_values(signal_attr)


def normalize_report_signal_attribution(payload: Optional[Dict[str, Any]]) -> None:
    """Normalize signal attribution in either a dashboard dict or full report dict."""
    if not isinstance(payload, dict):
        return
    normalize_dashboard_signal_attribution(payload)
    dashboard = payload.get("dashboard")
    if isinstance(dashboard, dict):
        normalize_dashboard_signal_attribution(dashboard)


def signal_attribution_weight_items(signal_attr: Any) -> List[Tuple[str, int]]:
    """Return displayable attribution weights as (key, integer percent) pairs."""
    if not isinstance(signal_attr, dict):
        return []
    items: List[Tuple[str, int]] = []
    for key in SIGNAL_ATTRIBUTION_WEIGHT_KEYS:
        value = signal_attr.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            number = float(value)
            if math.isfinite(number):
                items.append((key, int(round(number))))
    return items


def signal_attribution_has_content(signal_attr: Any) -> bool:
    """Whether a signal_attribution payload has anything meaningful to render."""
    if not isinstance(signal_attr, dict):
        return False
    if any(value != 0 for _, value in signal_attribution_weight_items(signal_attr)):
        return True
    return any(bool(signal_attr.get(key)) for key in SIGNAL_ATTRIBUTION_SIGNAL_KEYS)
