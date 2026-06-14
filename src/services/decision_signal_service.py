# -*- coding: utf-8 -*-
"""Service layer for persisted DecisionSignal assets."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, get_args

from data_provider.base import canonical_stock_code, normalize_stock_code
from src.core.trading_calendar import MarketPhase
from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.repositories.portfolio_repo import PortfolioRepository
from src.report_language import normalize_report_language
from src.schemas.decision_action import DecisionAction, localize_action_label
from src.services.portfolio_service import VALID_MARKETS
from src.storage import (
    DatabaseManager,
    DecisionSignalRecord,
    to_utc_naive_datetime,
    utc_naive_now,
)
from src.utils.sanitize import sanitize_decision_signal_payload, sanitize_decision_signal_text


SOURCE_TYPES = frozenset({"analysis", "agent", "alert", "market_review", "manual"})
SIGNAL_STATUSES = frozenset({"active", "expired", "invalidated", "closed", "archived"})
PLAN_QUALITIES = frozenset({"complete", "partial", "minimal", "unknown"})
HORIZONS = frozenset({"intraday", "1d", "3d", "5d", "10d", "swing", "long"})
MARKET_PHASES = frozenset(phase.value for phase in MarketPhase)
DECISION_ACTIONS = frozenset(get_args(DecisionAction))
REDACTION_MARKERS = ("[REDACTED]", "[REDACTED_URL]")

logger = logging.getLogger(__name__)


class DecisionSignalNotFoundError(ValueError):
    """Raised when a requested decision signal does not exist."""


class DecisionSignalStorageError(RuntimeError):
    """Raised when persisted decision-signal data is internally inconsistent."""


class DecisionSignalService:
    """Business logic for DecisionSignal storage, querying, and serialization."""

    def __init__(
        self,
        repo: Optional[DecisionSignalRepository] = None,
        portfolio_repo: Optional[PortfolioRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
    ):
        self.repo = repo or DecisionSignalRepository(db_manager)
        self.portfolio_repo = portfolio_repo or PortfolioRepository(db_manager)

    def create_signal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        fields = self._normalize_payload(payload)
        row, created = self.repo.create_if_absent(fields)
        return {"item": self._serialize(row), "created": created}

    def get_signal(self, signal_id: int) -> Dict[str, Any]:
        row = self.repo.get(signal_id)
        if row is None:
            raise DecisionSignalNotFoundError(f"Decision signal not found: {signal_id}")
        return self._serialize(row)

    def list_signals(
        self,
        *,
        stock_code: Optional[str] = None,
        market: Optional[str] = None,
        action: Optional[str] = None,
        market_phase: Optional[str] = None,
        source_type: Optional[str] = None,
        source_report_id: Optional[Any] = None,
        trace_id: Optional[str] = None,
        trigger_source: Optional[str] = None,
        status: Optional[str] = None,
        created_from: Optional[Any] = None,
        created_to: Optional[Any] = None,
        expires_from: Optional[Any] = None,
        expires_to: Optional[Any] = None,
        holding_only: bool = False,
        account_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        market_norm = self._normalize_optional_market(market)
        action_norm = self._normalize_optional_action(action)
        market_phase_norm = self._normalize_optional_enum(market_phase, MARKET_PHASES, "market_phase")
        source_type_norm = self._normalize_optional_enum(source_type, SOURCE_TYPES, "source_type")
        source_report_id_norm = self._optional_int(source_report_id, "source_report_id")
        trace_id_norm = self._optional_identity_text(trace_id, "trace_id", max_length=64)
        status_norm = self._normalize_optional_enum(status, SIGNAL_STATUSES, "status")
        trigger_source_norm = self._normalize_optional_trigger_source(trigger_source)
        created_from_dt = self._parse_datetime(created_from)
        created_to_dt = self._parse_datetime(created_to)
        expires_from_dt = self._parse_datetime(expires_from)
        expires_to_dt = self._parse_datetime(expires_to)
        stock_codes = self._stock_filter_codes(stock_code, market=market_norm)
        stock_identities = None

        if holding_only:
            held_identities = self._cached_holding_identities(account_id=account_id)
            if market_norm:
                held_identities = {
                    identity for identity in held_identities if identity[0] == market_norm
                }
            if stock_codes:
                requested_codes = set(stock_codes)
                held_identities = {
                    identity for identity in held_identities if identity[1] in requested_codes
                }
            stock_identities = sorted(held_identities)
            stock_codes = None
            if not stock_identities:
                return {"items": [], "total": 0, "page": safe_page, "page_size": safe_page_size}

        rows, total = self.repo.list(
            stock_codes=stock_codes,
            stock_identities=stock_identities,
            market=market_norm,
            action=action_norm,
            market_phase=market_phase_norm,
            source_type=source_type_norm,
            source_report_id=source_report_id_norm,
            trace_id=trace_id_norm,
            trigger_source=trigger_source_norm,
            status=status_norm,
            created_from=created_from_dt,
            created_to=created_to_dt,
            expires_from=expires_from_dt,
            expires_to=expires_to_dt,
            page=safe_page,
            page_size=safe_page_size,
        )
        return {
            "items": [self._serialize(row) for row in rows],
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
        }

    def get_latest_active(
        self,
        *,
        stock_code: str,
        market: Optional[str] = None,
        limit: int = 1,
    ) -> Dict[str, Any]:
        market_norm = self._normalize_optional_market(market)
        rows = self.repo.get_latest_active(
            stock_codes=self._stock_filter_codes(stock_code, market=market_norm) or [
                self._normalize_stock_code(stock_code)
            ],
            market=market_norm,
            limit=limit,
        )
        return {
            "items": [self._serialize(row) for row in rows],
            "total": len(rows),
            "page": 1,
            "page_size": max(1, min(int(limit), 100)),
        }

    def update_status(
        self,
        signal_id: int,
        *,
        status: str,
        metadata: Optional[Any] = None,
        replace_metadata: bool = False,
    ) -> Dict[str, Any]:
        status_norm = self._normalize_enum(status, SIGNAL_STATUSES, "status")
        metadata_json = self._json_dumps(metadata) if replace_metadata else None
        existing = self.repo.get(signal_id)
        if existing is None:
            raise DecisionSignalNotFoundError(f"Decision signal not found: {signal_id}")
        if status_norm == "active" and (
            existing.status == "expired" or self._is_expired(existing.expires_at)
        ):
            raise ValueError("expired decision signal cannot be reactivated without extending expires_at")
        row = self.repo.update_status(
            signal_id,
            status=status_norm,
            metadata_json=metadata_json,
            replace_metadata=replace_metadata,
        )
        if row is None:
            raise DecisionSignalNotFoundError(f"Decision signal not found: {signal_id}")
        return self._serialize(row)

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        market = self._normalize_market(payload.get("market"))
        stock_code = self._normalize_stock_code(payload.get("stock_code"), market=market)
        action = self._normalize_action(payload.get("action"))
        report_language = normalize_report_language(payload.get("report_language"))
        action_label = self._optional_public_text(payload.get("action_label"), "action_label", max_length=32)
        if not action_label:
            action_label = localize_action_label(action, report_language)

        confidence = self._optional_float(payload.get("confidence"), "confidence")
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        score = self._optional_int(payload.get("score"), "score")
        if score is not None and not 0 <= score <= 100:
            raise ValueError("score must be between 0 and 100")

        fields: Dict[str, Any] = {
            "stock_code": stock_code,
            "stock_name": self._optional_public_text(payload.get("stock_name"), "stock_name", max_length=64),
            "market": market,
            "source_type": self._normalize_enum(payload.get("source_type"), SOURCE_TYPES, "source_type"),
            "source_agent": self._optional_public_text(payload.get("source_agent"), "source_agent", max_length=64),
            "source_report_id": self._optional_int(payload.get("source_report_id"), "source_report_id"),
            "trace_id": self._optional_identity_text(payload.get("trace_id"), "trace_id", max_length=64),
            "market_phase": self._normalize_optional_enum(payload.get("market_phase"), MARKET_PHASES, "market_phase"),
            "trigger_source": self._normalize_trigger_source(payload.get("trigger_source")),
            "action": action,
            "action_label": action_label,
            "confidence": confidence,
            "score": score,
            "horizon": self._normalize_optional_enum(payload.get("horizon"), HORIZONS, "horizon"),
            "entry_low": self._optional_price_float(payload.get("entry_low"), "entry_low"),
            "entry_high": self._optional_price_float(payload.get("entry_high"), "entry_high"),
            "stop_loss": self._optional_price_float(payload.get("stop_loss"), "stop_loss"),
            "target_price": self._optional_price_float(payload.get("target_price"), "target_price"),
            "invalidation": self._optional_signal_text(payload.get("invalidation")),
            "watch_conditions": self._optional_signal_text(payload.get("watch_conditions")),
            "reason": self._optional_signal_text(payload.get("reason")),
            "risk_summary": self._optional_signal_text(payload.get("risk_summary")),
            "catalyst_summary": self._optional_signal_text(payload.get("catalyst_summary")),
            "evidence_json": self._json_dumps(payload.get("evidence")),
            "data_quality_summary_json": self._json_dumps(payload.get("data_quality_summary")),
            "status": self._normalize_optional_enum(payload.get("status"), SIGNAL_STATUSES, "status") or "active",
            "expires_at": self._parse_datetime(payload.get("expires_at")),
            "metadata_json": self._json_dumps(payload.get("metadata")),
        }
        if fields["status"] == "active" and self._is_expired(fields["expires_at"]):
            fields["status"] = "expired"
        self._validate_entry_range(fields)
        fields["plan_quality"] = self._normalize_plan_quality(
            payload.get("plan_quality"),
            fields=fields,
        )
        return fields

    def _normalize_plan_quality(self, value: Any, *, fields: Dict[str, Any]) -> str:
        if value is not None:
            return self._normalize_enum(value, PLAN_QUALITIES, "plan_quality")
        has_action_or_reason = bool(fields.get("action") or fields.get("reason"))
        if not has_action_or_reason:
            return "unknown"
        slots = 0
        if fields.get("entry_low") is not None or fields.get("entry_high") is not None:
            slots += 1
        for key in ("stop_loss", "target_price", "invalidation", "watch_conditions"):
            if fields.get(key) not in (None, ""):
                slots += 1
        if slots >= 4:
            return "complete"
        if slots >= 2:
            return "partial"
        return "minimal"

    def _cached_holding_identities(self, *, account_id: Optional[int]) -> set[Tuple[str, str]]:
        identities = self.portfolio_repo.list_cached_position_identities(account_id=account_id)
        normalized: set[Tuple[str, str]] = set()
        for market, symbol in identities:
            if not str(symbol or "").strip():
                continue
            market_norm = self._normalize_market(market)
            normalized.add((market_norm, self._normalize_stock_code(symbol, market=market_norm)))
        return normalized

    @classmethod
    def _stock_filter_codes(
        cls,
        stock_code: Optional[str],
        *,
        market: Optional[str] = None,
    ) -> Optional[List[str]]:
        if not stock_code:
            return None
        normalized = cls._normalize_stock_code(stock_code, market=market)
        if market is not None:
            return [normalized]

        hk_normalized = cls._normalize_hk_stock_code(str(stock_code).strip())
        return list(dict.fromkeys([normalized, hk_normalized]))

    @classmethod
    def _normalize_stock_code(cls, value: Any, *, market: Optional[str] = None) -> str:
        raw = str(value or "").strip()
        if market == "us":
            code = canonical_stock_code(raw)
        elif market == "hk":
            code = cls._normalize_hk_stock_code(raw)
        else:
            code = canonical_stock_code(normalize_stock_code(raw))
        if not code:
            raise ValueError("stock_code is required")
        return code

    @staticmethod
    def _normalize_hk_stock_code(value: str) -> str:
        normalized = canonical_stock_code(normalize_stock_code(value))
        digits = ""
        if normalized.startswith("HK"):
            digits = normalized[2:]
        elif normalized.isdigit():
            digits = normalized
        if digits.isdigit() and 1 <= len(digits) <= 5:
            return f"HK{digits.zfill(5)}"
        return normalized

    @staticmethod
    def _normalize_market(value: Any) -> str:
        market = str(value or "").strip().lower()
        if market not in VALID_MARKETS:
            raise ValueError("market must be one of cn, hk, us")
        return market

    @classmethod
    def _normalize_optional_market(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        return cls._normalize_market(value)

    @staticmethod
    def _normalize_action(value: Any) -> str:
        action = str(value or "").strip().lower()
        if not action or action not in DECISION_ACTIONS:
            raise ValueError("action must be one of buy/add/hold/reduce/sell/watch/avoid/alert")
        return action

    @classmethod
    def _normalize_optional_action(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        return cls._normalize_action(value)

    @staticmethod
    def _normalize_enum(value: Any, allowed: frozenset[str], field_name: str) -> str:
        text = str(value or "").strip()
        if text not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            raise ValueError(f"{field_name} must be one of {allowed_text}")
        return text

    @classmethod
    def _normalize_optional_enum(
        cls,
        value: Any,
        allowed: frozenset[str],
        field_name: str,
    ) -> Optional[str]:
        if value in (None, ""):
            return None
        return cls._normalize_enum(value, allowed, field_name)

    @staticmethod
    def _normalize_trigger_source(value: Any) -> str:
        text = DecisionSignalService._public_text(value, "trigger_source", max_length=64, required=True)
        if not text:
            raise ValueError("trigger_source is required")
        return text

    @classmethod
    def _normalize_optional_trigger_source(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        return cls._normalize_trigger_source(value)

    @staticmethod
    def _optional_text(value: Any, field_name: str, *, max_length: int) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if len(text) > max_length:
            raise ValueError(f"{field_name} must be at most {max_length} characters")
        return text

    @classmethod
    def _optional_public_text(cls, value: Any, field_name: str, *, max_length: int) -> Optional[str]:
        return cls._public_text(value, field_name, max_length=max_length, required=False)

    @staticmethod
    def _public_text(value: Any, field_name: str, *, max_length: int, required: bool) -> Optional[str]:
        if value is None:
            if required:
                raise ValueError(f"{field_name} is required")
            return None
        text = sanitize_decision_signal_text(value)
        if not text:
            if required:
                raise ValueError(f"{field_name} is required")
            return None
        if len(text) > max_length:
            raise ValueError(f"{field_name} must be at most {max_length} characters")
        return text

    @classmethod
    def _optional_identity_text(cls, value: Any, field_name: str, *, max_length: int) -> Optional[str]:
        text = cls._optional_text(value, field_name, max_length=max_length)
        if text is None:
            return None
        sanitized = sanitize_decision_signal_text(text)
        if any(marker in sanitized for marker in REDACTION_MARKERS):
            raise ValueError(f"{field_name} must not contain sensitive credentials")
        return text

    @staticmethod
    def _optional_signal_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(sanitize_decision_signal_payload(value), ensure_ascii=False, sort_keys=True)
        text = sanitize_decision_signal_text(value)
        return text or None

    @staticmethod
    def _optional_float(value: Any, field_name: str) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a number") from exc

    @classmethod
    def _optional_price_float(cls, value: Any, field_name: str) -> Optional[float]:
        number = cls._optional_float(value, field_name)
        if number is None:
            return None
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"{field_name} must be a finite positive number")
        return number

    @staticmethod
    def _validate_entry_range(fields: Dict[str, Any]) -> None:
        entry_low = fields.get("entry_low")
        entry_high = fields.get("entry_high")
        if entry_low is not None and entry_high is not None and entry_low > entry_high:
            raise ValueError("entry_low must be less than or equal to entry_high")

    @staticmethod
    def _optional_int(value: Any, field_name: str) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be an integer") from exc

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return to_utc_naive_datetime(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"invalid datetime value: {value}") from exc
            return to_utc_naive_datetime(parsed)
        raise ValueError(f"invalid datetime value: {value}")

    @classmethod
    def _is_expired(cls, expires_at: Optional[datetime]) -> bool:
        normalized_expires_at = cls._parse_datetime(expires_at)
        return normalized_expires_at is not None and normalized_expires_at <= utc_naive_now()

    @staticmethod
    def _json_dumps(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        sanitized = sanitize_decision_signal_payload(value)
        return json.dumps(sanitized, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _json_loads(value: Optional[str], *, signal_id: int, field_name: str) -> Any:
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Invalid decision signal JSON: id=%s field=%s error=%s",
                signal_id,
                field_name,
                exc,
            )
            raise DecisionSignalStorageError(
                f"invalid persisted JSON for decision signal {signal_id} field {field_name}"
            ) from exc

    def _serialize(self, row: DecisionSignalRecord) -> Dict[str, Any]:
        return {
            "id": row.id,
            "stock_code": row.stock_code,
            "stock_name": row.stock_name,
            "market": row.market,
            "source_type": row.source_type,
            "source_agent": row.source_agent,
            "source_report_id": row.source_report_id,
            "trace_id": row.trace_id,
            "market_phase": row.market_phase,
            "trigger_source": row.trigger_source,
            "action": row.action,
            "action_label": row.action_label,
            "confidence": row.confidence,
            "score": row.score,
            "horizon": row.horizon,
            "entry_low": row.entry_low,
            "entry_high": row.entry_high,
            "stop_loss": row.stop_loss,
            "target_price": row.target_price,
            "invalidation": row.invalidation,
            "watch_conditions": row.watch_conditions,
            "reason": row.reason,
            "risk_summary": row.risk_summary,
            "catalyst_summary": row.catalyst_summary,
            "evidence": self._json_loads(row.evidence_json, signal_id=row.id, field_name="evidence_json"),
            "data_quality_summary": self._json_loads(
                row.data_quality_summary_json,
                signal_id=row.id,
                field_name="data_quality_summary_json",
            ),
            "plan_quality": row.plan_quality,
            "status": row.status,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "metadata": self._json_loads(row.metadata_json, signal_id=row.id, field_name="metadata_json"),
        }
