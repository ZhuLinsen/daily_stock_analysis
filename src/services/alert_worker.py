# -*- coding: utf-8 -*-
"""Background worker for persisted and legacy alert rules."""

from __future__ import annotations

import asyncio
import hashlib
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
from data_provider.base import normalize_stock_code
from data_provider.us_index_mapping import is_us_index_code
from src.analysis_context_pack_overview import (
    ANALYSIS_CONTEXT_PACK_OVERVIEW_KEY,
    extract_analysis_context_pack_overview,
)
from src.core.trading_calendar import build_market_phase_context, get_market_for_stock
from src.market_phase_summary import (
    format_public_phase_pack_excerpt,
    render_market_phase_summary,
)
from src.services.alert_service import AlertService
from src.services.decision_signal_service import DecisionSignalService
from src.services.decision_signal_summary import (
    format_decision_signal_excerpt,
    summarize_decision_signal,
)
from src.services.history_service import HistoryService
from src.services.market_light_service import normalize_market_region

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
    effective_target: Optional[str] = None
    display_target: Optional[str] = None


@dataclass
class DBCooldownDecision:
    suppressed: bool = False
    fallback_key: Optional[str] = None
    fallback_ttl_seconds: Optional[int] = None


@dataclass
class TriggerWriteResult:
    trigger_id: Optional[int] = None
    created: bool = False


class AlertWorker:
    """Evaluate alert-center rules for schedule-mode background polling."""

    def __init__(
        self,
        *,
        config_provider: Optional[Callable[[], Any]] = None,
        service: Optional[AlertService] = None,
        decision_signal_service: Optional[DecisionSignalService] = None,
        notifier: Optional[Any] = None,
        now_provider: Optional[Callable[[], float]] = None,
        fingerprint_ttl_seconds: int = ALERT_WORKER_FINGERPRINT_TTL_SECONDS,
    ) -> None:
        self.config_provider = config_provider or self._default_config_provider
        self.service = service or AlertService()
        self.decision_signal_service = decision_signal_service or DecisionSignalService()
        self.notifier = notifier
        self.now_provider = now_provider or time.time
        self.fingerprint_ttl_seconds = max(1, int(fingerprint_ttl_seconds))
        self._trigger_fingerprints: Dict[str, float] = {}
        self._trigger_fingerprint_ttls: Dict[str, int] = {}
        self._analysis_visibility_cache: Dict[str, Optional[Dict[str, Any]]] = {}

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
        daily_cache: Dict[Any, Any] = {}
        self._analysis_visibility_cache = {}
        for runtime_rule in runtime_rules:
            stats["evaluated"] += 1
            try:
                result = asyncio.run(self.service._evaluate_rule(runtime_rule.rule, monitor, daily_cache=daily_cache))
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
            if record_status == "triggered":
                self._attach_decision_signal_summary_safely(runtime_rule, result)
            if record_status in WRITABLE_TRIGGER_STATUSES:
                trigger_write = self._record_trigger_safely(runtime_rule, result, record_status)
                trigger_id = trigger_write.trigger_id
                if trigger_write.created:
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
                cooldown_policy = self.service._load_json(row.cooldown_policy, default=None)
                for payload in self.service.build_runtime_payloads(row, config=config, include_overflow_payload=False):
                    if len(runtime_rules) >= ALERT_WORKER_RULE_LIMIT:
                        logger.warning(
                            "[AlertWorker] Runtime rule limit reached at %s; skipping remaining expanded rules",
                            ALERT_WORKER_RULE_LIMIT,
                        )
                        break
                    runtime_rules.append(
                        RuntimeAlertRule(
                            key=payload.key,
                            rule=payload.rule,
                            source="db",
                            severity=row.severity,
                            cooldown_policy=cooldown_policy,
                            effective_target=payload.effective_target,
                            display_target=payload.display_target,
                        )
                    )
                    seen_keys.add(payload.key)
                if len(runtime_rules) >= ALERT_WORKER_RULE_LIMIT:
                    break
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

    def _record_trigger(self, runtime_rule: RuntimeAlertRule, result: Dict[str, Any], status: str) -> TriggerWriteResult:
        try:
            rule_id = int(result.get("rule_id") or 0) or None
        except (TypeError, ValueError):
            rule_id = None

        fields = {
            "rule_id": rule_id,
            "target": self._effective_target(runtime_rule),
            "observed_value": self._optional_float(result.get("observed_value")),
            "threshold": self._optional_float(result.get("threshold")),
            "reason": result.get("reason") or result.get("message"),
            "data_source": result.get("data_source"),
            "data_timestamp": result.get("data_timestamp"),
            "status": status,
            "diagnostics": self._diagnostics_for_status(status, result, runtime_rule),
        }
        if self._should_deduplicate_trigger(runtime_rule, fields):
            row, created = self.service.repo.create_trigger_if_absent(fields)
        else:
            row = self.service.repo.create_trigger(fields)
            created = True
        trigger_id = int(row.id) if row and row.id is not None else None
        return TriggerWriteResult(trigger_id=trigger_id, created=created)

    def _record_trigger_safely(
        self,
        runtime_rule: RuntimeAlertRule,
        result: Dict[str, Any],
        status: str,
    ) -> TriggerWriteResult:
        try:
            return self._record_trigger(runtime_rule, result, status)
        except Exception as exc:
            logger.warning(
                "[AlertWorker] Failed to record alert trigger for %s: %s",
                self._display_target(runtime_rule),
                self.service._sanitize_text(str(exc) or "trigger write failed"),
            )
            return TriggerWriteResult()

    @staticmethod
    def _should_deduplicate_trigger(runtime_rule: RuntimeAlertRule, fields: Dict[str, Any]) -> bool:
        return (
            runtime_rule.source == "db"
            and fields.get("status") == "triggered"
            and fields.get("rule_id") is not None
            and fields.get("data_timestamp") is not None
        )

    @staticmethod
    def _optional_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _diagnostics_for_status(
        self,
        status: str,
        result: Dict[str, Any],
        runtime_rule: RuntimeAlertRule,
    ) -> Optional[str]:
        if status == "triggered":
            payload = self._diagnostics_payload(result.get("diagnostics"))
            payload["analysis_visibility"] = self._build_analysis_visibility(runtime_rule, result)
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return result.get("message") or result.get("reason")

    @staticmethod
    def _diagnostics_payload(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                return {"legacy_diagnostics": value}
            return dict(parsed) if isinstance(parsed, dict) else {"legacy_diagnostics": value}
        return {}

    def _attach_decision_signal_summary_safely(
        self,
        runtime_rule: RuntimeAlertRule,
        result: Dict[str, Any],
    ) -> None:
        try:
            summary = self._resolve_decision_signal_summary(runtime_rule, result)
            if not summary:
                return
            payload = self._diagnostics_payload(result.get("diagnostics"))
            payload["decision_signal_summary"] = summary
            result["diagnostics"] = payload
        except Exception as exc:
            logger.debug(
                "[AlertWorker] decision signal summary unavailable for %s: %s",
                self._display_target(runtime_rule),
                self.service._sanitize_text(str(exc) or "decision signal summary failed"),
            )

    def _resolve_decision_signal_summary(
        self,
        runtime_rule: RuntimeAlertRule,
        result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        identity = self._symbol_identity_for_decision_signal(runtime_rule)
        if identity is None:
            return None
        stock_code, market = identity
        latest = self.decision_signal_service.get_latest_active(
            stock_code=stock_code,
            market=market,
            limit=1,
        )
        items = latest.get("items") if isinstance(latest, dict) else None
        if items:
            return summarize_decision_signal(items[0])

        created = self.decision_signal_service.create_signal(
            self._alert_decision_signal_payload(
                runtime_rule,
                result,
                stock_code=stock_code,
                market=market,
            )
        )
        item = created.get("item") if isinstance(created, dict) else None
        return summarize_decision_signal(item)

    def _symbol_identity_for_decision_signal(self, runtime_rule: RuntimeAlertRule) -> Optional[Tuple[str, str]]:
        rule = getattr(runtime_rule, "rule", runtime_rule)
        metadata = getattr(rule, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
        target_scope = str(
            getattr(rule, "target_scope", None)
            or metadata.get("target_scope")
            or ""
        ).strip()
        if target_scope in {"market", "portfolio_account"}:
            return None
        target = str(
            metadata.get("effective_target")
            or runtime_rule.effective_target
            or getattr(rule, "stock_code", "")
            or ""
        ).strip()
        if not target or ":" in target:
            return None
        stock_code = normalize_stock_code(target)
        if is_us_index_code(stock_code):
            return None
        market = get_market_for_stock(stock_code)
        if market not in {"cn", "hk", "us"}:
            return None
        return stock_code, market

    def _alert_decision_signal_payload(
        self,
        runtime_rule: RuntimeAlertRule,
        result: Dict[str, Any],
        *,
        stock_code: str,
        market: str,
    ) -> Dict[str, Any]:
        rule = getattr(runtime_rule, "rule", runtime_rule)
        metadata = getattr(rule, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
        alert_type = self._public_alert_type(getattr(rule, "alert_type", None) or result.get("alert_type"))
        key_hash = hashlib.sha1(str(runtime_rule.key or "").encode("utf-8")).hexdigest()
        return {
            "stock_code": stock_code,
            "stock_name": getattr(rule, "stock_name", None),
            "market": market,
            "source_type": "alert",
            "source_agent": "alert_worker",
            "trace_id": f"alert-rule-{key_hash[:32]}",
            "trigger_source": "alert",
            "action": "alert",
            "reason": result.get("reason") or result.get("message") or getattr(rule, "description", None),
            "watch_conditions": self._alert_watch_conditions(runtime_rule, result, alert_type),
            "risk_summary": self._alert_risk_summary(runtime_rule, result),
            "metadata": {
                "rule_id": self.service._runtime_rule_id(rule),
                "alert_type": alert_type,
                "severity": runtime_rule.severity,
                "observed_value": result.get("observed_value"),
                "threshold": result.get("threshold"),
                "data_source": result.get("data_source"),
                "data_timestamp": self._iso_or_text(result.get("data_timestamp")),
                "rule_key_hash": key_hash,
            },
        }

    @staticmethod
    def _public_alert_type(value: Any) -> str:
        raw = getattr(value, "value", value)
        return str(raw or "").strip()[:64]

    def _alert_watch_conditions(
        self,
        runtime_rule: RuntimeAlertRule,
        result: Dict[str, Any],
        alert_type: str,
    ) -> str:
        threshold = result.get("threshold")
        observed = result.get("observed_value")
        target = self._display_target(runtime_rule)
        parts = [part for part in (target, alert_type) if part]
        if threshold not in (None, ""):
            parts.append(f"threshold={threshold}")
        if observed not in (None, ""):
            parts.append(f"observed={observed}")
        return " | ".join(str(part) for part in parts)

    def _alert_risk_summary(self, runtime_rule: RuntimeAlertRule, result: Dict[str, Any]) -> str:
        severity = str(runtime_rule.severity or "warning")
        reason = result.get("reason") or result.get("message") or "Alert triggered"
        return f"{severity}: {reason}"

    @staticmethod
    def _iso_or_text(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _build_analysis_visibility(
        self,
        runtime_rule: RuntimeAlertRule,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        phase_summary = self._alert_market_phase_summary(runtime_rule)
        overview = self._evaluator_pack_overview(result)
        source = "evaluator_snapshot" if overview is not None else None
        if overview is None:
            overview = self._recent_history_pack_overview(runtime_rule)
            if overview is not None:
                source = "analysis_history_snapshot"
        return {
            "market_phase_summary": phase_summary,
            "analysis_context_pack_overview": overview,
            "source": source or "alert_trigger_market_context",
        }

    def _alert_market_phase_summary(self, runtime_rule: RuntimeAlertRule) -> Optional[Dict[str, Any]]:
        try:
            rule = getattr(runtime_rule, "rule", runtime_rule)
            target_scope = str(getattr(rule, "target_scope", "") or "")
            if target_scope == "market":
                market = normalize_market_region(getattr(rule, "target", self._effective_target(runtime_rule)))
            elif target_scope in {"portfolio_account"}:
                market = None
            else:
                market = get_market_for_stock(normalize_stock_code(self._effective_target(runtime_rule)))
            context = build_market_phase_context(
                market=market,
                trigger_source="alert",
                analysis_phase="auto",
            )
            payload = context.to_dict() if hasattr(context, "to_dict") else context
            return render_market_phase_summary(payload)
        except Exception as exc:
            logger.debug("[AlertWorker] phase summary unavailable: %s", exc)
            return None

    @staticmethod
    def _evaluator_pack_overview(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        overview = result.get("analysis_context_pack_overview")
        if overview is None:
            diagnostics = result.get("diagnostics")
            if isinstance(diagnostics, str):
                try:
                    diagnostics = json.loads(diagnostics)
                except (TypeError, ValueError, json.JSONDecodeError):
                    diagnostics = None
            if isinstance(diagnostics, dict):
                overview = diagnostics.get("analysis_context_pack_overview")
        return extract_analysis_context_pack_overview({ANALYSIS_CONTEXT_PACK_OVERVIEW_KEY: overview})

    def _recent_history_pack_overview(self, runtime_rule: RuntimeAlertRule) -> Optional[Dict[str, Any]]:
        rule = getattr(runtime_rule, "rule", runtime_rule)
        target_scope = str(getattr(rule, "target_scope", "") or "")
        if target_scope in {"market", "portfolio_account"}:
            return None
        target = self._effective_target(runtime_rule)
        if not target or target == "?":
            return None
        cache_key = str(target).upper()
        if cache_key in self._analysis_visibility_cache:
            return self._analysis_visibility_cache[cache_key]
        overview: Optional[Dict[str, Any]] = None
        try:
            candidates = HistoryService._history_code_filter_candidates(target)
            records: List[Any] = []
            for candidate in candidates:
                records.extend(self.service.db.get_analysis_history(code=candidate, days=30, limit=1))
            records = sorted(records, key=lambda item: getattr(item, "created_at", None) or datetime.min, reverse=True)
            if records:
                overview = extract_analysis_context_pack_overview(getattr(records[0], "context_snapshot", None))
        except Exception as exc:
            logger.debug("[AlertWorker] recent history overview unavailable for %s: %s", target, exc)
            overview = None
        self._analysis_visibility_cache[cache_key] = overview
        return overview

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
        title = f"Event Alert | {self._display_target(runtime_rule)}"
        content = result.get("reason") or result.get("message") or runtime_rule.rule.description or "Alert triggered"
        diagnostics = self._diagnostics_payload(result.get("diagnostics"))
        visibility = diagnostics.get("analysis_visibility") if isinstance(diagnostics.get("analysis_visibility"), dict) else None
        if visibility is None:
            visibility = self._build_analysis_visibility(runtime_rule, result)
        excerpt = format_public_phase_pack_excerpt(
            visibility.get("market_phase_summary"),
            visibility.get("analysis_context_pack_overview"),
            source=visibility.get("source"),
        )
        if excerpt:
            content = f"{content}\n\n{excerpt}"
        signal_excerpt = format_decision_signal_excerpt(diagnostics.get("decision_signal_summary"))
        if signal_excerpt:
            content = f"{content}\n\n{signal_excerpt}"
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
                self._display_target(runtime_rule),
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
                target=self._effective_target(runtime_rule),
                severity=runtime_rule.severity,
                now=now_dt,
            )
        except Exception as exc:
            logger.warning(
                "[AlertWorker] Failed to read alert cooldown for %s: %s",
                self._display_target(runtime_rule),
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
                target=self._effective_target(runtime_rule),
                severity=runtime_rule.severity,
                last_triggered_at=now_dt,
                cooldown_until=now_dt + timedelta(seconds=cooldown_seconds),
                reason=self.service._sanitize_text(result.get("reason") or result.get("message")),
            )
        except Exception as exc:
            logger.warning(
                "[AlertWorker] Failed to update alert cooldown for %s: %s",
                self._display_target(runtime_rule),
                self.service._sanitize_text(str(exc) or "cooldown write failed"),
            )

    @staticmethod
    def _effective_target(runtime_rule: RuntimeAlertRule) -> str:
        return str(runtime_rule.effective_target or getattr(runtime_rule.rule, "stock_code", "") or "?")

    @staticmethod
    def _display_target(runtime_rule: RuntimeAlertRule) -> str:
        return str(runtime_rule.display_target or runtime_rule.effective_target or getattr(runtime_rule.rule, "stock_code", "") or "?")

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
