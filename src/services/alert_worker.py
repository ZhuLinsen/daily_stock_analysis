# -*- coding: utf-8 -*-
"""Background worker for persisted and legacy alert rules."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from src.agent.events import (
    EventMonitor,
    PriceAlert,
    PriceChangeAlert,
    VolumeAlert,
    parse_event_alert_rules,
    validate_event_alert_rule,
)
from src.services.alert_service import AlertService

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.notification import ChannelAttemptResult, NotificationDispatchResult

ALERT_WORKER_FINGERPRINT_TTL_SECONDS = 24 * 60 * 60
DEFAULT_DB_ALERT_COOLDOWN_SECONDS = 24 * 60 * 60
ALERT_WORKER_RULE_LIMIT = 1000
WRITABLE_TRIGGER_STATUSES = frozenset({"triggered", "skipped", "degraded", "failed"})


@dataclass
class RuntimeAlertRule:
    key: str
    rule: Any
    source: str
    severity: Optional[str] = None
    cooldown_policy: Optional[Dict[str, Any]] = None


@dataclass
class DBCooldownDecision:
    suppressed: bool = False
    fallback_key: Optional[str] = None
    fallback_ttl_seconds: Optional[int] = None


class AlertWorker:
    """Evaluate alert-center rules for schedule-mode background polling."""

    def __init__(
        self,
        *,
        config_provider: Optional[Callable[[], Any]] = None,
        service: Optional[AlertService] = None,
        notifier: Optional[Any] = None,
        now_provider: Optional[Callable[[], float]] = None,
        fingerprint_ttl_seconds: int = ALERT_WORKER_FINGERPRINT_TTL_SECONDS,
    ) -> None:
        self.config_provider = config_provider or self._default_config_provider
        self.service = service or AlertService()
        self.notifier = notifier
        self.now_provider = now_provider or time.time
        self.fingerprint_ttl_seconds = max(1, int(fingerprint_ttl_seconds))
        self._trigger_fingerprints: Dict[str, float] = {}
        self._trigger_fingerprint_ttls: Dict[str, int] = {}

    @staticmethod
    def _default_config_provider():
        from src.config import get_config

        return get_config()

    def run_once(self) -> Dict[str, int]:
        """Run one alert worker cycle.

        This method is intentionally exception-contained so scheduler background
        threads keep running even when one config or rule is bad.
        """
        stats = {
            "loaded": 0,
            "evaluated": 0,
            "recorded": 0,
            "triggered": 0,
            "notified": 0,
            "skipped": 0,
            "degraded": 0,
            "failed": 0,
            "notification_attempts": 0,
            "cooldown_suppressed": 0,
        }

        try:
            config = self.config_provider()
        except Exception as exc:
            logger.warning("[AlertWorker] Failed to load runtime config: %s", exc)
            return stats

        if not getattr(config, "agent_event_monitor_enabled", False):
            logger.debug("[AlertWorker] Event monitor disabled; skipping")
            return stats

        self._prune_fingerprints()
        runtime_rules = self._load_runtime_rules(config)
        stats["loaded"] = len(runtime_rules)
        if not runtime_rules:
            logger.info("[AlertWorker] No active alert rules loaded")
            return stats

        monitor = EventMonitor()
        for runtime_rule in runtime_rules:
            stats["evaluated"] += 1
            try:
                result = asyncio.run(self.service._evaluate_rule(runtime_rule.rule, monitor))
            except Exception as exc:
                result = {
                    "rule_id": self.service._runtime_rule_id(runtime_rule.rule),
                    "record_status": "failed",
                    "triggered": False,
                    "observed_value": None,
                    "threshold": self.service._threshold_for_rule(runtime_rule.rule),
                    "data_source": self.service._data_source_for_rule(runtime_rule.rule),
                    "data_timestamp": None,
                    "reason": self.service._sanitize_text(str(exc) or "Alert evaluation failed"),
                    "message": self.service._sanitize_text(str(exc) or "Alert evaluation failed"),
                }

            record_status = result.get("record_status")
            if record_status in WRITABLE_TRIGGER_STATUSES:
                trigger_id = self._record_trigger_safely(runtime_rule, result, record_status)
                if trigger_id is not None:
                    stats["recorded"] += 1
                if record_status in stats and record_status != "triggered":
                    stats[record_status] += 1
            else:
                trigger_id = None

            if record_status == "triggered":
                stats["triggered"] += 1
                if runtime_rule.source == "db":
                    cooldown_decision = self._check_db_cooldown(runtime_rule, trigger_id)
                    if cooldown_decision.suppressed:
                        stats["cooldown_suppressed"] += 1
                        stats["notification_attempts"] += 1
                        continue
                    dispatch = self._send_notification_safely(runtime_rule, result)
                    stats["notification_attempts"] += self._record_notification_attempts_safely(trigger_id, dispatch)
                    if self._dispatch_has_real_channel_success(dispatch):
                        self._upsert_db_cooldown_safely(runtime_rule, result)
                        if cooldown_decision.fallback_key:
                            self._mark_notified(
                                cooldown_decision.fallback_key,
                                ttl_seconds=cooldown_decision.fallback_ttl_seconds,
                            )
                        stats["notified"] += 1
                elif self._should_notify(runtime_rule.key):
                    dispatch = self._send_notification_safely(runtime_rule, result)
                    stats["notification_attempts"] += self._record_notification_attempts_safely(trigger_id, dispatch)
                    if bool(dispatch.success):
                        self._mark_notified(runtime_rule.key)
                        stats["notified"] += 1

        return stats

    def _load_runtime_rules(self, config: Any) -> List[RuntimeAlertRule]:
        runtime_rules: List[RuntimeAlertRule] = []
        seen_keys = set()

        for row in self.service.repo.list_enabled_rules(limit=ALERT_WORKER_RULE_LIMIT):
            try:
                rule_data = self.service._serialize_rule_base(row)
                key = self._semantic_key(
                    rule_data["target_scope"],
                    rule_data["target"],
                    rule_data["alert_type"],
                    rule_data["parameters"],
                )
                runtime_rules.append(
                    RuntimeAlertRule(
                        key=key,
                        rule=self.service._to_runtime_rule(row, rule_data),
                        source="db",
                        severity=rule_data.get("severity"),
                        cooldown_policy=rule_data.get("cooldown_policy"),
                    )
                )
                seen_keys.add(key)
            except Exception as exc:
                logger.warning("[AlertWorker] Skip invalid persisted alert rule %s: %s", getattr(row, "id", "?"), exc)

        for key, rule in self._load_legacy_rules(config):
            if key in seen_keys:
                logger.info("[AlertWorker] Skip duplicate legacy alert rule: %s", key)
                continue
            runtime_rules.append(RuntimeAlertRule(key=key, rule=rule, source="legacy_env"))
            seen_keys.add(key)

        return runtime_rules

    def _load_legacy_rules(self, config: Any) -> List[Tuple[str, Any]]:
        raw_rules = getattr(config, "agent_event_alert_rules_json", "")
        try:
            parsed_rules = parse_event_alert_rules(raw_rules)
        except Exception as exc:
            logger.warning("[AlertWorker] Failed to parse legacy alert rules: %s", exc)
            return []

        legacy_rules: List[Tuple[str, Any]] = []
        for index, entry in enumerate(parsed_rules, start=1):
            try:
                validate_event_alert_rule(entry)
                stock_code = str(entry.get("stock_code") or "").strip()
                alert_type = str(entry.get("alert_type") or "").strip().lower()
                parameters = self.service._normalize_parameters(alert_type, entry)
                key = self._semantic_key("single_symbol", stock_code, alert_type, parameters)
                metadata = {"source": "legacy_env", "legacy_rule_index": index}
                if alert_type == "price_cross":
                    rule = PriceAlert(
                        stock_code=stock_code,
                        direction=str(parameters["direction"]),
                        price=float(parameters["price"]),
                        metadata=metadata,
                    )
                elif alert_type == "price_change_percent":
                    rule = PriceChangeAlert(
                        stock_code=stock_code,
                        direction=str(parameters["direction"]),
                        change_pct=float(parameters["change_pct"]),
                        metadata=metadata,
                    )
                elif alert_type == "volume_spike":
                    rule = VolumeAlert(
                        stock_code=stock_code,
                        multiplier=float(parameters["multiplier"]),
                        metadata=metadata,
                    )
                else:
                    raise ValueError(f"unsupported alert_type: {alert_type}")
                legacy_rules.append((key, rule))
            except Exception as exc:
                logger.warning("[AlertWorker] Skip invalid legacy alert rule #%d: %s", index, exc)
        return legacy_rules

    @staticmethod
    def _semantic_key(target_scope: str, target: str, alert_type: str, parameters: Dict[str, Any]) -> str:
        canonical_params = json.dumps(parameters or {}, ensure_ascii=False, sort_keys=True)
        return f"{target_scope}:{target}:{alert_type}:{canonical_params}"

    def _record_trigger(self, runtime_rule: RuntimeAlertRule, result: Dict[str, Any], status: str) -> Optional[int]:
        try:
            rule_id = int(result.get("rule_id") or 0) or None
        except (TypeError, ValueError):
            rule_id = None

        fields = {
            "rule_id": rule_id,
            "target": runtime_rule.rule.stock_code,
            "observed_value": self._optional_float(result.get("observed_value")),
            "threshold": self._optional_float(result.get("threshold")),
            "reason": result.get("reason") or result.get("message"),
            "data_source": result.get("data_source"),
            "data_timestamp": result.get("data_timestamp"),
            "status": status,
            "diagnostics": self._diagnostics_for_status(status, result),
        }
        row = self.service.repo.create_trigger(fields)
        return int(row.id) if row and row.id is not None else None

    def _record_trigger_safely(
        self,
        runtime_rule: RuntimeAlertRule,
        result: Dict[str, Any],
        status: str,
    ) -> Optional[int]:
        try:
            return self._record_trigger(runtime_rule, result, status)
        except Exception as exc:
            logger.warning(
                "[AlertWorker] Failed to record alert trigger for %s: %s",
                getattr(runtime_rule.rule, "stock_code", "?"),
                self.service._sanitize_text(str(exc) or "trigger write failed"),
            )
            return None

    @staticmethod
    def _optional_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _diagnostics_for_status(status: str, result: Dict[str, Any]) -> Optional[str]:
        if status == "triggered":
            return None
        return result.get("message") or result.get("reason")

    def _should_notify(self, rule_key: str, *, ttl_seconds: Optional[int] = None) -> bool:
        now = self.now_provider()
        last_seen = self._trigger_fingerprints.get(rule_key)
        ttl = self._fingerprint_ttl(rule_key, ttl_seconds=ttl_seconds)
        if last_seen is not None and now - last_seen < ttl:
            return False
        return True

    def _mark_notified(self, rule_key: str, *, ttl_seconds: Optional[int] = None) -> None:
        self._trigger_fingerprints[rule_key] = self.now_provider()
        if ttl_seconds is None:
            self._trigger_fingerprint_ttls.pop(rule_key, None)
        else:
            self._trigger_fingerprint_ttls[rule_key] = max(1, int(ttl_seconds))

    def _prune_fingerprints(self) -> None:
        now = self.now_provider()
        expired_keys = [
            key
            for key, last_seen in self._trigger_fingerprints.items()
            if now - last_seen >= self._fingerprint_ttl(key)
        ]
        for key in expired_keys:
            self._trigger_fingerprints.pop(key, None)
            self._trigger_fingerprint_ttls.pop(key, None)

    def _fingerprint_ttl(self, rule_key: str, *, ttl_seconds: Optional[int] = None) -> int:
        if ttl_seconds is not None:
            return max(1, int(ttl_seconds))
        return self._trigger_fingerprint_ttls.get(rule_key, self.fingerprint_ttl_seconds)

    @staticmethod
    def _db_cooldown_fallback_key(rule_key: str) -> str:
        return f"db_cooldown:{rule_key}"

    def _send_notification(self, runtime_rule: RuntimeAlertRule, result: Dict[str, Any]) -> "NotificationDispatchResult":
        from src.notification import NotificationBuilder, NotificationService

        notification_service = self.notifier or NotificationService()
        title = f"Event Alert | {runtime_rule.rule.stock_code}"
        content = result.get("reason") or result.get("message") or runtime_rule.rule.description or "Alert triggered"
        alert_text = NotificationBuilder.build_simple_alert(title=title, content=content, alert_type="warning")

        return notification_service.send_with_results(alert_text, route_type="alert")

    def _send_notification_safely(self, runtime_rule: RuntimeAlertRule, result: Dict[str, Any]) -> "NotificationDispatchResult":
        try:
            return self._send_notification(runtime_rule, result)
        except Exception as exc:
            from src.notification import ChannelAttemptResult, NotificationDispatchResult

            sanitized = self.service._sanitize_text(str(exc) or "notification failed")
            logger.warning(
                "[AlertWorker] Failed to send alert notification for %s: %s",
                getattr(runtime_rule.rule, "stock_code", "?"),
                sanitized,
            )
            return NotificationDispatchResult(
                dispatched=False,
                success=False,
                status="exception",
                channel_results=[
                    ChannelAttemptResult(
                        channel="__dispatch__",
                        success=False,
                        error_code="exception",
                        retryable=True,
                        diagnostics=sanitized,
                    )
                ],
                message=sanitized,
            )

    def _record_notification_attempts_safely(
        self,
        trigger_id: Optional[int],
        dispatch: "NotificationDispatchResult",
    ) -> int:
        try:
            return self._record_notification_attempts(trigger_id, dispatch)
        except Exception as exc:
            logger.warning(
                "[AlertWorker] Failed to record alert notification attempt: %s",
                self.service._sanitize_text(str(exc) or "notification attempt write failed"),
            )
            return 0

    def _record_notification_attempts(self, trigger_id: Optional[int], dispatch: "NotificationDispatchResult") -> int:
        channel_results = list(dispatch.channel_results or [])
        if not channel_results:
            channel_results = [self._synthetic_attempt_for_dispatch(dispatch)]

        recorded = 0
        for attempt_index, item in enumerate(channel_results, start=1):
            fields = {
                "trigger_id": trigger_id,
                "channel": str(item.channel or "__dispatch__")[:32],
                "attempt": attempt_index,
                "success": bool(item.success),
                "error_code": item.error_code,
                "retryable": bool(item.retryable),
                "latency_ms": self._optional_int(item.latency_ms),
                "diagnostics": self.service._sanitize_text(item.diagnostics or dispatch.message),
            }
            self.service.repo.record_notification_attempt(fields)
            recorded += 1
        return recorded

    @staticmethod
    def _synthetic_attempt_for_dispatch(dispatch: "NotificationDispatchResult") -> "ChannelAttemptResult":
        from src.notification import ChannelAttemptResult

        status = str(dispatch.status or "unknown")
        channel_by_status = {
            "noise_suppressed": "__noise_suppressed__",
            "no_channel": "__no_channel__",
            "exception": "__dispatch__",
        }
        success = bool(dispatch.success)
        return ChannelAttemptResult(
            channel=channel_by_status.get(status, "__dispatch__"),
            success=success,
            error_code=None if success else status,
            retryable=status not in {"noise_suppressed", "no_channel"},
            diagnostics=dispatch.message,
        )

    @staticmethod
    def _optional_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _dispatch_has_real_channel_success(dispatch: "NotificationDispatchResult") -> bool:
        if not dispatch.dispatched:
            return False
        for item in dispatch.channel_results or []:
            channel = str(item.channel or "")
            if item.success and not channel.startswith("__"):
                return True
        return False

    def _check_db_cooldown(self, runtime_rule: RuntimeAlertRule, trigger_id: Optional[int]) -> DBCooldownDecision:
        """Return the DB cooldown decision for this trigger.

        Active persisted cooldowns record a ``__cooldown__`` synthetic
        notification attempt. If reading the cooldown state fails, the worker
        uses the process-local fingerprint as a temporary guard so DB outages
        do not turn persisted rules into one-notification-per-cycle spam.
        """
        cooldown_seconds = self._cooldown_seconds(runtime_rule)
        if cooldown_seconds <= 0:
            return DBCooldownDecision()
        rule_id = self.service._runtime_rule_id(runtime_rule.rule)
        if rule_id <= 0:
            return DBCooldownDecision()

        now_dt = self._now_datetime()
        try:
            cooldown = self.service.repo.get_active_cooldown(
                rule_id=rule_id,
                target=runtime_rule.rule.stock_code,
                severity=runtime_rule.severity,
                now=now_dt,
            )
        except Exception as exc:
            logger.warning(
                "[AlertWorker] Failed to read alert cooldown for %s: %s",
                getattr(runtime_rule.rule, "stock_code", "?"),
                self.service._sanitize_text(str(exc) or "cooldown read failed"),
            )
            fallback_key = self._db_cooldown_fallback_key(runtime_rule.key)
            if self._should_notify(fallback_key, ttl_seconds=cooldown_seconds):
                return DBCooldownDecision(
                    suppressed=False,
                    fallback_key=fallback_key,
                    fallback_ttl_seconds=cooldown_seconds,
                )
            self._record_cooldown_read_failure_suppression(trigger_id, exc)
            return DBCooldownDecision(suppressed=True)

        if cooldown is None:
            return DBCooldownDecision()

        from src.notification import ChannelAttemptResult, NotificationDispatchResult

        self._record_notification_attempts_safely(
            trigger_id,
            NotificationDispatchResult(
                dispatched=False,
                success=False,
                status="cooldown_active",
                channel_results=[
                    ChannelAttemptResult(
                        channel="__cooldown__",
                        success=False,
                        error_code="cooldown_active",
                        retryable=False,
                        diagnostics=(
                            f"cooldown_until={cooldown.cooldown_until.isoformat()}"
                            if cooldown.cooldown_until else "cooldown active"
                        ),
                    )
                ],
                message="alert cooldown active",
            ),
        )
        return DBCooldownDecision(suppressed=True)

    def _record_cooldown_read_failure_suppression(self, trigger_id: Optional[int], exc: Exception) -> None:
        from src.notification import ChannelAttemptResult, NotificationDispatchResult

        sanitized = self.service._sanitize_text(str(exc) or "cooldown read failed")
        self._record_notification_attempts_safely(
            trigger_id,
            NotificationDispatchResult(
                dispatched=False,
                success=False,
                status="cooldown_read_failed",
                channel_results=[
                    ChannelAttemptResult(
                        channel="__cooldown_read_failed__",
                        success=False,
                        error_code="cooldown_read_failed",
                        retryable=False,
                        diagnostics=sanitized,
                    )
                ],
                message=sanitized,
            ),
        )

    def _upsert_db_cooldown_safely(self, runtime_rule: RuntimeAlertRule, result: Dict[str, Any]) -> None:
        cooldown_seconds = self._cooldown_seconds(runtime_rule)
        if cooldown_seconds <= 0:
            return
        rule_id = self.service._runtime_rule_id(runtime_rule.rule)
        if rule_id <= 0:
            return
        now_dt = self._now_datetime()
        try:
            self.service.repo.upsert_cooldown(
                rule_id=rule_id,
                rule_key=runtime_rule.key,
                target=runtime_rule.rule.stock_code,
                severity=runtime_rule.severity,
                last_triggered_at=now_dt,
                cooldown_until=now_dt + timedelta(seconds=cooldown_seconds),
                reason=self.service._sanitize_text(result.get("reason") or result.get("message")),
            )
        except Exception as exc:
            logger.warning(
                "[AlertWorker] Failed to update alert cooldown for %s: %s",
                getattr(runtime_rule.rule, "stock_code", "?"),
                self.service._sanitize_text(str(exc) or "cooldown write failed"),
            )

    @staticmethod
    def _cooldown_seconds(runtime_rule: RuntimeAlertRule) -> int:
        policy = runtime_rule.cooldown_policy if isinstance(runtime_rule.cooldown_policy, dict) else None
        if not policy or "cooldown_seconds" not in policy:
            return DEFAULT_DB_ALERT_COOLDOWN_SECONDS
        try:
            return max(0, int(policy.get("cooldown_seconds") or 0))
        except (TypeError, ValueError):
            return 0

    def _now_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.now_provider())
