# -*- coding: utf-8 -*-
"""
EventMonitor — lightweight event-driven alert system.

Monitors a set of stocks for threshold events and triggers
notifications when conditions are met.  Designed to run as a
background task (e.g. via ``--schedule`` or a dedicated loop).

Currently supported runtime events:
- Price crossing threshold (above / below)
- Price change percentage threshold (up / down)
- Volume spike (> N× average)

Other alert types remain defined as enum placeholders for future
extension, but config validation rejects them until the monitor can
actually evaluate them.

Usage::

    from src.agent.events import EventMonitor, PriceAlert
    monitor = EventMonitor()
    monitor.add_alert(PriceAlert(stock_code="600519", direction="above", price=1800.0))
    triggered = await monitor.check_all()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class AlertType(str, Enum):
    PRICE_CROSS = "price_cross"
    PRICE_CHANGE_PERCENT = "price_change_percent"
    VOLUME_SPIKE = "volume_spike"
    SENTIMENT_SHIFT = "sentiment_shift"
    RISK_FLAG = "risk_flag"
    CUSTOM = "custom"


class AlertStatus(str, Enum):
    ACTIVE = "active"
    TRIGGERED = "triggered"
    EXPIRED = "expired"
    DISMISSED = "dismissed"


_RUNTIME_SUPPORTED_ALERT_TYPES = frozenset({
    AlertType.PRICE_CROSS,
    AlertType.PRICE_CHANGE_PERCENT,
    AlertType.VOLUME_SPIKE,
})


def _supported_alert_type_names() -> str:
    return ", ".join(sorted(alert_type.value for alert_type in _RUNTIME_SUPPORTED_ALERT_TYPES))


def _ensure_runtime_supported_alert_type(alert_type: AlertType) -> None:
    if alert_type not in _RUNTIME_SUPPORTED_ALERT_TYPES:
        raise ValueError(
            f"unsupported alert_type for current EventMonitor runtime: {alert_type.value} "
            f"(supported: {_supported_alert_type_names()})"
        )


def _read_quote_float(quote: Any, *field_names: str) -> Optional[float]:
    """Read a numeric field from quote objects or dict-like payloads."""
    if quote is None:
        return None

    for field_name in field_names:
        if isinstance(quote, dict):
            raw_value = quote.get(field_name)
        else:
            raw_value = getattr(quote, field_name, None)

        if raw_value is None and hasattr(quote, "to_dict"):
            try:
                raw_value = quote.to_dict().get(field_name)
            except Exception:
                raw_value = None

        if raw_value is None:
            continue

        if isinstance(raw_value, str):
            raw_value = raw_value.strip().replace(",", "")
            if raw_value.endswith("%"):
                raw_value = raw_value[:-1].strip()
            if not raw_value:
                continue

        try:
            return float(raw_value)
        except (TypeError, ValueError):
            continue

    return None


@dataclass
class AlertRule:
    """Base alert rule definition."""
    stock_code: str
    alert_type: AlertType
    description: str = ""
    status: AlertStatus = AlertStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    triggered_at: Optional[float] = None
    ttl_hours: float = 24.0  # auto-expire after this many hours
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PriceAlert(AlertRule):
    """Alert when price crosses a threshold."""
    alert_type: AlertType = AlertType.PRICE_CROSS
    direction: str = "above"  # "above" or "below"
    price: float = 0.0

    def __post_init__(self):
        if not self.description:
            self.description = f"{self.stock_code} price {self.direction} {self.price}"


@dataclass
class PriceChangeAlert(AlertRule):
    """Alert when intraday price change crosses a percentage threshold."""
    alert_type: AlertType = AlertType.PRICE_CHANGE_PERCENT
    direction: str = "up"  # "up" or "down"
    change_pct: float = 3.0

    def __post_init__(self):
        if not self.description:
            self.description = f"{self.stock_code} change {self.direction} {self.change_pct}%"


@dataclass
class VolumeAlert(AlertRule):
    """Alert when volume exceeds N× average."""
    alert_type: AlertType = AlertType.VOLUME_SPIKE
    multiplier: float = 2.0  # trigger when volume > multiplier × avg

    def __post_init__(self):
        if not self.description:
            self.description = f"{self.stock_code} volume > {self.multiplier}× average"


@dataclass
class SentimentAlert(AlertRule):
    """Alert on sentiment direction change."""
    alert_type: AlertType = AlertType.SENTIMENT_SHIFT
    from_sentiment: str = "positive"  # "positive", "negative", "neutral"
    to_sentiment: str = "negative"

    def __post_init__(self):
        if not self.description:
            self.description = f"{self.stock_code} sentiment shift: {self.from_sentiment} → {self.to_sentiment}"


@dataclass
class TriggeredAlert:
    """An alert that was triggered, ready for notification."""
    rule: AlertRule
    triggered_at: float = field(default_factory=time.time)
    current_value: Any = None
    message: str = ""


class EventMonitor:
    """Monitor stocks for event-driven alerts.

    This class manages a list of :class:`AlertRule` objects and checks
    them against current market data.  Triggered alerts are collected
    and can be forwarded to the notification system.
    """

    def __init__(self):
        self.rules: List[AlertRule] = []
        self._callbacks: List[Callable[[TriggeredAlert], None]] = []

    def add_alert(self, rule: AlertRule) -> None:
        """Register a new alert rule."""
        _ensure_runtime_supported_alert_type(rule.alert_type)
        self.rules.append(rule)
        logger.info("[EventMonitor] Added alert: %s", rule.description)

    def remove_expired(self) -> int:
        """Remove alerts that have expired based on TTL.

        Returns:
            Number of expired alerts removed.
        """
        now = time.time()
        before = len(self.rules)
        self.rules = [
            r for r in self.rules
            if r.status != AlertStatus.EXPIRED
            and (now - r.created_at) < r.ttl_hours * 3600
        ]
        removed = before - len(self.rules)
        if removed:
            logger.info("[EventMonitor] Removed %d expired alerts", removed)
        return removed

    def on_trigger(self, callback: Callable[[TriggeredAlert], None]) -> None:
        """Register a callback for when an alert triggers."""
        self._callbacks.append(callback)

    async def check_all(self) -> List[TriggeredAlert]:
        """Check all active rules against current market data.

        Returns:
            List of triggered alerts.
        """
        self.remove_expired()
        triggered: List[TriggeredAlert] = []

        for rule in self.rules:
            if rule.status != AlertStatus.ACTIVE:
                continue

            try:
                result = await self._check_rule(rule)
                if result:
                    triggered.append(result)
                    rule.status = AlertStatus.TRIGGERED
                    rule.triggered_at = time.time()
                    # Notify callbacks (offload slow/sync ones to thread)
                    for cb in self._callbacks:
                        try:
                            if asyncio.iscoroutinefunction(cb):
                                await cb(result)
                            else:
                                await asyncio.to_thread(cb, result)
                        except Exception as exc:
                            logger.warning("[EventMonitor] Callback error: %s", exc)
            except Exception as exc:
                logger.debug("[EventMonitor] Check failed for %s: %s", rule.description, exc)

        return triggered

    async def _check_rule(self, rule: AlertRule) -> Optional[TriggeredAlert]:
        """Check a single rule.  Returns TriggeredAlert if condition met."""
        if isinstance(rule, PriceAlert):
            return await self._check_price(rule)
        elif isinstance(rule, PriceChangeAlert):
            return await self._check_price_change(rule)
        elif isinstance(rule, VolumeAlert):
            return await self._check_volume(rule)
        # SentimentAlert and custom alerts require more context —
        # implemented as hooks for future extension
        return None

    def _fetch_realtime_quote(self, stock_code: str) -> Any:
        from data_provider import DataFetcherManager

        return DataFetcherManager().get_realtime_quote(stock_code)

    async def _get_realtime_quote(self, stock_code: str) -> Any:
        return await asyncio.to_thread(self._fetch_realtime_quote, stock_code)

    async def _check_price(self, rule: PriceAlert) -> Optional[TriggeredAlert]:
        """Check price alert against realtime quote."""
        try:
            quote = await self._get_realtime_quote(rule.stock_code)
            if quote is None:
                return None

            current_price = float(getattr(quote, "price", 0) or 0)
            if current_price <= 0:
                return None

            triggered = False
            if rule.direction == "above" and current_price >= rule.price:
                triggered = True
            elif rule.direction == "below" and current_price <= rule.price:
                triggered = True

            if triggered:
                return TriggeredAlert(
                    rule=rule,
                    current_value=current_price,
                    message=f"🔔 {rule.stock_code} price {rule.direction} {rule.price}: "
                            f"current = {current_price}",
                )
        except Exception as exc:
            logger.debug("[EventMonitor] _check_price error: %s", exc)
        return None

    async def _check_price_change(self, rule: PriceChangeAlert) -> Optional[TriggeredAlert]:
        """Check price-change percentage alert against realtime quote."""
        try:
            quote = await self._get_realtime_quote(rule.stock_code)
            if quote is None:
                return None

            current_change_pct = _read_quote_float(
                quote,
                "change_pct",
                "change_percent",
                "pct_chg",
                "change_rate",
            )
            if current_change_pct is None:
                return None

            threshold = abs(float(rule.change_pct))
            direction = rule.direction.lower()
            triggered = False
            if direction == "up" and current_change_pct >= threshold:
                triggered = True
            elif direction == "down" and current_change_pct <= -threshold:
                triggered = True

            if triggered:
                return TriggeredAlert(
                    rule=rule,
                    current_value=current_change_pct,
                    message=f"🔔 {rule.stock_code} change {direction} {threshold:.2f}%: "
                            f"current = {current_change_pct:+.2f}%",
                )
        except Exception as exc:
            logger.debug("[EventMonitor] _check_price_change error: %s", exc)
        return None

    async def _check_volume(self, rule: VolumeAlert) -> Optional[TriggeredAlert]:
        """Check volume spike against recent average."""
        try:
            def _fetch_daily_data():
                from data_provider import DataFetcherManager

                fm = DataFetcherManager()
                return fm.get_daily_data(rule.stock_code, days=20)

            result = await asyncio.to_thread(_fetch_daily_data)
            # get_daily_data returns (df, source) tuple or None
            if result is None:
                return None
            df, _source = result
            if df is None or df.empty:
                return None

            avg_vol = df["volume"].mean()
            latest_vol = df["volume"].iloc[-1]

            if avg_vol > 0 and latest_vol > avg_vol * rule.multiplier:
                return TriggeredAlert(
                    rule=rule,
                    current_value=latest_vol,
                    message=f"📊 {rule.stock_code} volume spike: "
                            f"{latest_vol:,.0f} ({latest_vol / avg_vol:.1f}× avg)",
                )
        except Exception as exc:
            logger.debug("[EventMonitor] _check_volume error: %s", exc)
        return None

    # -----------------------------------------------------------------
    # Persistence helpers
    # -----------------------------------------------------------------

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """Serialize all rules for persistence."""
        results = []
        for rule in self.rules:
            entry: Dict[str, Any] = {
                "stock_code": rule.stock_code,
                "alert_type": rule.alert_type.value,
                "description": rule.description,
                "status": rule.status.value,
                "created_at": rule.created_at,
                "ttl_hours": rule.ttl_hours,
            }
            if isinstance(rule, PriceAlert):
                entry["direction"] = rule.direction
                entry["price"] = rule.price
            elif isinstance(rule, PriceChangeAlert):
                entry["direction"] = rule.direction
                entry["change_pct"] = rule.change_pct
            elif isinstance(rule, VolumeAlert):
                entry["multiplier"] = rule.multiplier
            results.append(entry)
        return results

    @classmethod
    def from_dict_list(cls, data: List[Dict[str, Any]]) -> "EventMonitor":
        """Restore an EventMonitor from serialized data."""
        monitor = cls()
        for index, entry in enumerate(data, start=1):
            try:
                validate_event_alert_rule(entry)

                alert_type = entry.get("alert_type", "custom")
                stock_code = entry.get("stock_code", "")
                if alert_type == AlertType.PRICE_CROSS.value:
                    rule = PriceAlert(
                        stock_code=stock_code,
                        direction=entry.get("direction", "above").lower(),
                        price=float(entry.get("price", 0.0)),
                    )
                elif alert_type == AlertType.PRICE_CHANGE_PERCENT.value:
                    rule = PriceChangeAlert(
                        stock_code=stock_code,
                        direction=entry.get("direction", "up").lower(),
                        change_pct=float(entry["change_pct"]),
                    )
                elif alert_type == AlertType.VOLUME_SPIKE.value:
                    rule = VolumeAlert(
                        stock_code=stock_code,
                        multiplier=float(entry.get("multiplier", 2.0)),
                    )
                else:
                    raise ValueError(f"unsupported alert_type: {alert_type}")
                rule.status = AlertStatus(entry.get("status", "active"))
                raw_created = entry.get("created_at")
                try:
                    rule.created_at = float(raw_created) if raw_created is not None else time.time()
                except (TypeError, ValueError):
                    rule.created_at = time.time()
                rule.ttl_hours = float(entry.get("ttl_hours", 24.0))
                monitor.add_alert(rule)
            except Exception as exc:
                logger.warning("[EventMonitor] Skip invalid rule #%d: %s", index, exc)
        return monitor


def parse_event_alert_rules(raw_rules: Any) -> List[Dict[str, Any]]:
    """Parse event alert rules from config JSON or already-loaded objects."""
    if raw_rules is None:
        return []

    parsed = raw_rules
    if isinstance(raw_rules, str):
        cleaned = raw_rules.strip()
        if not cleaned:
            return []
        parsed = json.loads(cleaned)

    if isinstance(parsed, dict):
        parsed = parsed.get("rules", [])

    if not isinstance(parsed, list):
        raise ValueError("Event alert rules must be a JSON array")

    invalid_indices = [idx for idx, entry in enumerate(parsed) if not isinstance(entry, dict)]
    if invalid_indices:
        raise ValueError(
            "Event alert rules list must contain only objects; "
            f"invalid entries at positions: {invalid_indices}"
        )

    return parsed


def validate_event_alert_rule(rule: Dict[str, Any]) -> None:
    """Validate one serialized EventMonitor rule."""
    if not isinstance(rule, dict):
        raise ValueError("Event alert rule must be an object")

    stock_code = str(rule.get("stock_code") or "").strip()
    if not stock_code:
        raise ValueError("stock_code is required")

    try:
        alert_type = AlertType(rule.get("alert_type", ""))
    except ValueError as exc:
        raise ValueError(f"invalid alert_type: {rule.get('alert_type')}") from exc
    _ensure_runtime_supported_alert_type(alert_type)

    status = rule.get("status")
    if status is not None:
        try:
            AlertStatus(status)
        except ValueError as exc:
            raise ValueError(f"invalid status: {status}") from exc

    ttl_hours = rule.get("ttl_hours")
    if ttl_hours is not None:
        try:
            ttl_value = float(ttl_hours)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid ttl_hours: {ttl_hours}") from exc
        if ttl_value <= 0:
            raise ValueError("ttl_hours must be > 0")

    if alert_type == AlertType.PRICE_CROSS:
        direction = str(rule.get("direction", "above")).lower()
        if direction not in {"above", "below"}:
            raise ValueError(f"invalid direction: {direction}")
        try:
            price = float(rule.get("price"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid price: {rule.get('price')}") from exc
        if price <= 0:
            raise ValueError("price must be > 0")
    elif alert_type == AlertType.PRICE_CHANGE_PERCENT:
        direction = str(rule.get("direction", "up")).lower()
        if direction not in {"up", "down"}:
            raise ValueError(f"invalid direction: {direction}")
        try:
            change_pct = float(rule.get("change_pct"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid change_pct: {rule.get('change_pct')}") from exc
        if change_pct <= 0:
            raise ValueError("change_pct must be > 0")
    elif alert_type == AlertType.VOLUME_SPIKE:
        try:
            multiplier = float(rule.get("multiplier", 2.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid multiplier: {rule.get('multiplier')}") from exc
        if multiplier <= 0:
            raise ValueError("multiplier must be > 0")


def build_event_monitor_from_config(config=None, notifier=None) -> Optional[EventMonitor]:
    """Build an EventMonitor from runtime config and attach notification callbacks."""
    if config is None:
        from src.config import get_config
        config = get_config()

    if not getattr(config, "agent_event_monitor_enabled", False):
        return None

    raw_rules = getattr(config, "agent_event_alert_rules_json", "")
    try:
        rules = parse_event_alert_rules(raw_rules)
    except Exception as exc:
        logger.warning("[EventMonitor] Failed to parse configured alert rules: %s", exc)
        return None

    if not rules:
        logger.info("[EventMonitor] Enabled but no alert rules configured")
        return None

    monitor = EventMonitor.from_dict_list(rules)
    if not monitor.rules:
        return None

    from src.notification import NotificationBuilder, NotificationService

    notification_service = notifier or NotificationService()

    def _notify(triggered: TriggeredAlert) -> None:
        title = f"Event Alert | {triggered.rule.stock_code}"
        content = triggered.message or triggered.rule.description or "Alert triggered"
        alert_text = NotificationBuilder.build_simple_alert(title=title, content=content, alert_type="warning")
        sent = notification_service.send(alert_text)
        if not sent:
            logger.info("[EventMonitor] No notification channel available for alert: %s", title)

    monitor.on_trigger(_notify)
    logger.info("[EventMonitor] Loaded %d configured alert rule(s)", len(monitor.rules))
    return monitor


def run_event_monitor_once(monitor: EventMonitor) -> List[TriggeredAlert]:
    """Run one synchronous monitor cycle."""
    return asyncio.run(monitor.check_all())
