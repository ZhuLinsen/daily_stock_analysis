# -*- coding: utf-8 -*-
"""Runtime helpers for Market Light alert rules."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from src.core.trading_calendar import get_open_markets_today
from src.schemas.market_light import MarketLightSnapshot
from src.services.market_light_service import (
    build_current_snapshot,
    load_previous_snapshot,
    normalize_market_region,
)
from src.services.portfolio_alerts import RuntimeAlertPayload


MARKET_ALERT_TYPES = frozenset({"market_light_status", "market_light_score_drop"})
MARKET_STATUS_VALUES = frozenset({"red", "yellow"})
MARKET_REGION_LABELS = {
    "cn": "A股大盘",
    "hk": "港股大盘",
    "us": "美股大盘",
}
MARKET_LIGHT_DATA_SOURCE = "market_light"


@dataclass
class MarketLightAlert:
    """Runtime alert for market-level Market Light rules."""

    target_scope: str
    target: str
    alert_type: str
    parameters: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    stock_code: str = ""

    def __post_init__(self) -> None:
        self.target = normalize_market_region(self.target)
        self.stock_code = self.target


def normalize_market_alert_parameters(alert_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    if alert_type not in MARKET_ALERT_TYPES:
        raise ValueError(f"unsupported market alert_type: {alert_type}")
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")

    if alert_type == "market_light_status":
        raw_statuses = parameters.get("statuses")
        if raw_statuses is None:
            raw_statuses = ["red", "yellow"]
        if isinstance(raw_statuses, str):
            raw_statuses = [raw_statuses]
        if not isinstance(raw_statuses, list) or not raw_statuses:
            raise ValueError("market_light_status statuses must be a non-empty list")
        statuses = []
        for raw_status in raw_statuses:
            status = str(raw_status or "").strip().lower()
            if status not in MARKET_STATUS_VALUES:
                raise ValueError("market_light_status statuses only supports red or yellow")
            if status not in statuses:
                statuses.append(status)
        return {"statuses": statuses}

    min_drop = _positive_float(parameters.get("min_drop"), "min_drop")
    return {"min_drop": min_drop}


def make_market_light_payload(
    *,
    parent_key: str,
    data: Dict[str, Any],
    config: Optional[Any] = None,
) -> RuntimeAlertPayload:
    region = normalize_market_region(data["target"])
    if config is None:
        from src.config import get_config

        config = get_config()
    trading_day_check_enabled = bool(getattr(config, "trading_day_check_enabled", True))
    market_is_open = True
    if trading_day_check_enabled:
        market_is_open = region in get_open_markets_today()

    display_target = MARKET_REGION_LABELS.get(region, region)
    rule = MarketLightAlert(
        target_scope=data["target_scope"],
        target=region,
        alert_type=data["alert_type"],
        parameters=dict(data.get("parameters") or {}),
        metadata={
            "persisted_rule_id": data["id"],
            "effective_target": region,
            "display_target": display_target,
            "trading_day_check_enabled": trading_day_check_enabled,
            "market_is_open": market_is_open,
        },
        description=data.get("name") or data["alert_type"],
    )
    return RuntimeAlertPayload(
        key=f"{parent_key}|{region}",
        rule=rule,
        effective_target=region,
        display_target=display_target,
    )


def evaluate_market_light_alert(
    rule: MarketLightAlert,
    *,
    current_snapshot: Optional[Dict[str, Any]] = None,
    cache: Optional[Dict[Any, Any]] = None,
) -> Dict[str, Any]:
    if rule.metadata.get("trading_day_check_enabled") and not rule.metadata.get("market_is_open", True):
        return _market_result(
            rule,
            triggered=False,
            observed_value=None,
            threshold=_threshold(rule),
            message=f"{rule.target} market is not a trading day",
            record_status="skipped",
            diagnostics={"region": rule.target, "trading_day_check": "closed"},
        )

    try:
        snapshot = current_snapshot or _cached_current_snapshot(rule.target, cache)
        current = MarketLightSnapshot.model_validate(snapshot)
        data_timestamp = parse_trade_date_to_datetime(current.trade_date)
    except Exception as exc:
        return _market_result(
            rule,
            triggered=False,
            observed_value=None,
            threshold=_threshold(rule),
            message=f"market light snapshot unavailable: {exc}",
            record_status="degraded",
            diagnostics={"region": rule.target, "error": str(exc)[:200]},
        )

    if current.data_quality == "unavailable":
        return _market_result(
            rule,
            triggered=False,
            observed_value=None,
            threshold=_threshold(rule),
            message="market light data is unavailable",
            record_status="skipped",
            data_timestamp=data_timestamp,
            diagnostics=_base_diagnostics(current),
        )

    if rule.alert_type == "market_light_status":
        return _evaluate_status(rule, current, data_timestamp)
    if rule.alert_type == "market_light_score_drop":
        return _evaluate_score_drop(rule, current, data_timestamp)

    return _market_result(
        rule,
        triggered=False,
        observed_value=None,
        threshold=None,
        message=f"unsupported market alert_type: {rule.alert_type}",
        record_status="failed",
        diagnostics={"region": rule.target, "error": "unsupported_market_alert_type"},
    )


def parse_trade_date_to_datetime(trade_date: str) -> datetime:
    return datetime.fromisoformat(str(trade_date))


def _cached_current_snapshot(region: str, cache: Optional[Dict[Any, Any]]) -> Dict[str, Any]:
    if cache is None:
        return build_current_snapshot(region)
    cache_key = ("market_light", region)
    if cache_key not in cache:
        cache[cache_key] = build_current_snapshot(region)
    return cache[cache_key]


def _evaluate_status(
    rule: MarketLightAlert,
    current: MarketLightSnapshot,
    data_timestamp: datetime,
) -> Dict[str, Any]:
    statuses = set(rule.parameters.get("statuses") or ["red", "yellow"])
    triggered = current.status in statuses
    diagnostics = _base_diagnostics(current)
    if current.data_quality == "partial":
        diagnostics["missing_dimensions"] = _missing_dimensions(current)
    return _market_result(
        rule,
        triggered=triggered,
        observed_value=float(current.score),
        threshold=None,
        message=(
            f"Market Light status {current.status} matched {sorted(statuses)}"
            if triggered
            else f"Market Light status {current.status} did not match {sorted(statuses)}"
        ),
        data_timestamp=data_timestamp,
        diagnostics=diagnostics,
    )


def _evaluate_score_drop(
    rule: MarketLightAlert,
    current: MarketLightSnapshot,
    data_timestamp: datetime,
) -> Dict[str, Any]:
    min_drop = float(rule.parameters["min_drop"])
    try:
        raw_previous = load_previous_snapshot(rule.target, before_trade_date=current.trade_date)
        previous = MarketLightSnapshot.model_validate(raw_previous) if raw_previous else None
    except Exception as exc:
        return _market_result(
            rule,
            triggered=False,
            observed_value=float(current.score),
            threshold=min_drop,
            message=f"previous market light snapshot unavailable: {exc}",
            record_status="degraded",
            data_timestamp=data_timestamp,
            diagnostics={**_base_diagnostics(current), "error": str(exc)[:200]},
        )

    if previous is None:
        return _market_result(
            rule,
            triggered=False,
            observed_value=float(current.score),
            threshold=min_drop,
            message="previous market light snapshot not found",
            record_status="skipped",
            data_timestamp=data_timestamp,
            diagnostics=_base_diagnostics(current),
        )

    if previous.trade_date >= current.trade_date:
        return _market_result(
            rule,
            triggered=False,
            observed_value=float(current.score),
            threshold=min_drop,
            message="previous market light snapshot is not before current trade_date",
            record_status="skipped",
            data_timestamp=data_timestamp,
            diagnostics={
                **_base_diagnostics(current),
                "prev_trade_date": previous.trade_date,
                "prev_score": previous.score,
            },
        )

    if previous.data_quality == "unavailable":
        return _market_result(
            rule,
            triggered=False,
            observed_value=float(current.score),
            threshold=min_drop,
            message="previous market light data is unavailable",
            record_status="skipped",
            data_timestamp=data_timestamp,
            diagnostics={
                **_base_diagnostics(current),
                "prev_trade_date": previous.trade_date,
                "prev_score": previous.score,
                "prev_data_quality": previous.data_quality,
            },
        )

    drop = float(previous.score - current.score)
    triggered = drop >= min_drop
    partial_comparison = current.data_quality == "partial" or previous.data_quality == "partial"
    diagnostics = {
        **_base_diagnostics(current),
        "prev_trade_date": previous.trade_date,
        "prev_score": previous.score,
        "drop": drop,
    }
    if partial_comparison:
        diagnostics["partial_comparison"] = True
        diagnostics["missing_dimensions"] = sorted(
            set(_missing_dimensions(current)) | set(_missing_dimensions(previous))
        )
    return _market_result(
        rule,
        triggered=triggered,
        observed_value=float(current.score),
        threshold=min_drop,
        message=(
            f"Market Light score dropped {drop:.1f} points from {previous.score} to {current.score}"
            if triggered
            else f"Market Light score drop {drop:.1f} points is below {min_drop:g}"
        ),
        data_timestamp=data_timestamp,
        diagnostics=diagnostics,
    )


def _market_result(
    rule: MarketLightAlert,
    *,
    triggered: bool,
    observed_value: Optional[float],
    threshold: Optional[float],
    message: str,
    record_status: Optional[str] = None,
    data_timestamp: Optional[datetime] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    effective_status = "triggered" if triggered else "not_triggered"
    if triggered and record_status is None:
        record_status = "triggered"
    return {
        "rule_id": int(rule.metadata.get("persisted_rule_id", 0) or 0),
        "status": effective_status,
        "record_status": record_status,
        "triggered": triggered,
        "observed_value": observed_value,
        "threshold": threshold,
        "data_source": MARKET_LIGHT_DATA_SOURCE,
        "data_timestamp": data_timestamp,
        "reason": message,
        "message": message,
        "diagnostics": json.dumps(diagnostics or {}, ensure_ascii=False, sort_keys=True),
    }


def _threshold(rule: MarketLightAlert) -> Optional[float]:
    if rule.alert_type == "market_light_score_drop":
        return float(rule.parameters.get("min_drop", 0) or 0)
    return None


def _base_diagnostics(snapshot: MarketLightSnapshot) -> Dict[str, Any]:
    return {
        "region": snapshot.region,
        "trade_date": snapshot.trade_date,
        "data_quality": snapshot.data_quality,
    }


def _missing_dimensions(snapshot: MarketLightSnapshot) -> list[str]:
    dimensions = snapshot.dimensions.model_dump()
    return sorted(name for name, item in dimensions.items() if not item.get("available"))


def _positive_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}: {value}") from exc
    if number <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return number
