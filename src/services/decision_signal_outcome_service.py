# -*- coding: utf-8 -*-
"""DecisionSignal feedback, forward outcome, and stats service."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
import json
import logging
import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.core.backtest_engine import BacktestEngine, EvaluationConfig
from src.repositories.decision_signal_outcome_repo import DecisionSignalOutcomeRepository
from src.repositories.decision_signal_repo import DecisionSignalRepository
from src.repositories.stock_repo import StockRepository
from src.services.decision_signal_service import (
    HORIZONS,
    SIGNAL_STATUSES,
    SOURCE_TYPES,
    DecisionSignalNotFoundError,
    DecisionSignalService,
)
from src.storage import (
    DatabaseManager,
    DecisionSignalFeedbackRecord,
    DecisionSignalOutcomeRecord,
    DecisionSignalRecord,
)
from src.utils.sanitize import sanitize_decision_signal_text


logger = logging.getLogger(__name__)

DECISION_SIGNAL_OUTCOME_ENGINE_VERSION = "decision-signal-v1"
SUPPORTED_OUTCOME_HORIZONS = {
    "1d": 1,
    "3d": 3,
    "5d": 5,
    "10d": 10,
}
DEFAULT_STATS_STATUSES = ("active", "expired", "invalidated", "closed")
OUTCOME_VALUES = frozenset({"hit", "miss", "neutral"})
EVAL_STATUSES = frozenset({"completed", "unable"})
FEEDBACK_VALUES = frozenset({"useful", "not_useful"})
FEEDBACK_SOURCES = frozenset({"web", "api"})
HOLDING_STATES = frozenset({"holding", "empty", "unknown"})
RETRYABLE_UNABLE_REASONS = frozenset({
    "missing_anchor_price",
    "invalid_anchor_price",
    "insufficient_forward_bars",
    "missing_end_close",
    "invalid_end_close",
})
BATCH_CANDIDATE_SCAN_PAGE_SIZE = 500


class DecisionSignalOutcomeService:
    """Business logic for signal outcomes, stats, and feedback."""

    def __init__(
        self,
        *,
        repo: Optional[DecisionSignalOutcomeRepository] = None,
        signal_repo: Optional[DecisionSignalRepository] = None,
        stock_repo: Optional[StockRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
    ):
        self.repo = repo or DecisionSignalOutcomeRepository(db_manager)
        self.signal_repo = signal_repo or DecisionSignalRepository(db_manager)
        self.stock_repo = stock_repo or StockRepository(db_manager)

    def run_outcomes(
        self,
        *,
        signal_id: Optional[int] = None,
        horizons: Optional[List[str]] = None,
        force: bool = False,
        market: Optional[str] = None,
        stock_code: Optional[str] = None,
        action: Optional[str] = None,
        source_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        signal_id_norm = self._optional_positive_int(signal_id, "signal_id")
        market_norm = DecisionSignalService._normalize_optional_market(market)
        action_norm = DecisionSignalService._normalize_optional_action(action)
        source_type_norm = self._normalize_optional_enum(source_type, SOURCE_TYPES, "source_type")
        status_norm = self._normalize_optional_enum(status, SIGNAL_STATUSES, "status")
        stock_codes_norm = DecisionSignalService._stock_filter_codes(stock_code, market=market_norm)
        horizons_norm = self._normalize_horizons(horizons)
        safe_limit = max(1, min(int(limit), 500))

        statuses = [status_norm] if status_norm else None
        if signal_id_norm is None and statuses is None:
            statuses = list(DEFAULT_STATS_STATUSES)

        if signal_id_norm is None and not force:
            signals = self._list_actionable_candidate_signals(
                stock_codes=stock_codes_norm,
                market=market_norm,
                action=action_norm,
                source_type=source_type_norm,
                statuses=statuses,
                requested_horizons=horizons_norm,
                limit=safe_limit,
            )
        else:
            signals = self.repo.list_candidate_signals(
                signal_id=signal_id_norm,
                stock_codes=stock_codes_norm,
                market=market_norm,
                action=action_norm,
                source_type=source_type_norm,
                statuses=statuses,
                limit=safe_limit,
            )
        if signal_id_norm is not None and not signals:
            raise DecisionSignalNotFoundError(f"Decision signal not found: {signal_id_norm}")

        items: List[Dict[str, Any]] = []
        created_count = 0
        updated_count = 0
        skipped_count = 0

        for signal in signals:
            for horizon in self._horizons_for_signal(signal, horizons_norm):
                existing = self.repo.get_outcome(
                    signal_id=signal.id,
                    horizon=horizon,
                    engine_version=DECISION_SIGNAL_OUTCOME_ENGINE_VERSION,
                )
                if existing is not None and not force and not self._should_recompute_outcome(existing):
                    skipped_count += 1
                    items.append(self._serialize_outcome(existing))
                    continue

                fields = self._evaluate_signal_horizon(signal, horizon)
                row, created = self.repo.upsert_outcome(fields)
                if created:
                    created_count += 1
                else:
                    updated_count += 1
                items.append(self._serialize_outcome(row))

        return {
            "items": items,
            "evaluated": created_count + updated_count,
            "created": created_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "engine_version": DECISION_SIGNAL_OUTCOME_ENGINE_VERSION,
        }

    def _list_actionable_candidate_signals(
        self,
        *,
        stock_codes: Optional[List[str]],
        market: Optional[str],
        action: Optional[str],
        source_type: Optional[str],
        statuses: Optional[List[str]],
        requested_horizons: Optional[List[str]],
        limit: int,
    ) -> List[DecisionSignalRecord]:
        selected: List[DecisionSignalRecord] = []
        selected_ids = set()
        retryable_reserve: List[Tuple[datetime, int, DecisionSignalRecord]] = []
        retryable_ids = set()
        offset = 0

        while len(selected) < limit:
            page = self.repo.list_candidate_signals(
                stock_codes=stock_codes,
                market=market,
                action=action,
                source_type=source_type,
                statuses=statuses,
                offset=offset,
                limit=BATCH_CANDIDATE_SCAN_PAGE_SIZE,
            )
            if not page:
                break

            outcomes = self.repo.list_outcomes_for_signals(
                signal_ids=[int(signal.id) for signal in page],
                engine_version=DECISION_SIGNAL_OUTCOME_ENGINE_VERSION,
            )
            outcomes_by_key: Dict[Tuple[int, str], DecisionSignalOutcomeRecord] = {
                (int(row.signal_id), row.horizon): row
                for row in outcomes
            }

            for signal in page:
                actionability, retryable_at = self._candidate_actionability(
                    signal,
                    requested_horizons=requested_horizons,
                    outcomes_by_key=outcomes_by_key,
                )
                signal_id = int(signal.id)
                if actionability == "missing":
                    if signal_id not in selected_ids:
                        selected.append(signal)
                        selected_ids.add(signal_id)
                    if len(selected) >= limit:
                        break
                elif actionability == "retryable" and signal_id not in retryable_ids:
                    retryable_reserve.append((retryable_at, signal_id, signal))
                    retryable_ids.add(signal_id)

            offset += len(page)
            if len(page) < BATCH_CANDIDATE_SCAN_PAGE_SIZE:
                break

        if len(selected) < limit:
            retryable_reserve.sort(key=lambda item: (item[0], item[1]))
            for _retryable_at, signal_id, signal in retryable_reserve:
                signal_id = int(signal.id)
                if signal_id in selected_ids:
                    continue
                selected.append(signal)
                selected_ids.add(signal_id)
                if len(selected) >= limit:
                    break

        return selected

    def _candidate_actionability(
        self,
        signal: DecisionSignalRecord,
        *,
        requested_horizons: Optional[List[str]],
        outcomes_by_key: Dict[Tuple[int, str], DecisionSignalOutcomeRecord],
    ) -> Tuple[Optional[str], Optional[datetime]]:
        retryable_times: List[datetime] = []
        signal_id = int(signal.id)
        for horizon in self._horizons_for_signal(signal, requested_horizons):
            existing = outcomes_by_key.get((signal_id, horizon))
            if existing is None:
                return "missing", None
            if self._should_recompute_outcome(existing):
                retryable_times.append(self._outcome_retryable_sort_time(existing))
        if retryable_times:
            return "retryable", min(retryable_times)
        return None, None

    @staticmethod
    def _outcome_retryable_sort_time(row: DecisionSignalOutcomeRecord) -> datetime:
        return row.updated_at or row.created_at or datetime.min

    @staticmethod
    def _should_recompute_outcome(row: DecisionSignalOutcomeRecord) -> bool:
        return row.eval_status == "unable" and row.unable_reason in RETRYABLE_UNABLE_REASONS

    def list_outcomes(
        self,
        *,
        signal_id: Optional[int] = None,
        horizon: Optional[str] = None,
        engine_version: Optional[str] = None,
        eval_status: Optional[str] = None,
        outcome: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        signal_id_norm = self._optional_positive_int(signal_id, "signal_id")
        horizon_norm = self._normalize_optional_enum(horizon, HORIZONS, "horizon")
        engine_version_norm = str(engine_version or DECISION_SIGNAL_OUTCOME_ENGINE_VERSION).strip()
        eval_status_norm = self._normalize_optional_enum(eval_status, EVAL_STATUSES, "eval_status")
        outcome_norm = self._normalize_optional_enum(outcome, OUTCOME_VALUES, "outcome")
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        rows, total = self.repo.list_outcomes(
            signal_id=signal_id_norm,
            horizon=horizon_norm,
            engine_version=engine_version_norm,
            eval_status=eval_status_norm,
            outcome=outcome_norm,
            page=safe_page,
            page_size=safe_page_size,
        )
        return {
            "items": [self._serialize_outcome(row) for row in rows],
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
        }

    def list_signal_outcomes(self, signal_id: int) -> Dict[str, Any]:
        signal_id_norm = self._require_existing_signal(signal_id).id
        return self.list_outcomes(
            signal_id=signal_id_norm,
            engine_version=DECISION_SIGNAL_OUTCOME_ENGINE_VERSION,
            page=1,
            page_size=100,
        )

    def get_stats(
        self,
        *,
        horizons: Optional[List[str]] = None,
        engine_version: Optional[str] = None,
        statuses: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        engine_version_norm = str(engine_version or DECISION_SIGNAL_OUTCOME_ENGINE_VERSION).strip()
        horizons_norm = self._normalize_horizons(horizons)
        statuses_norm = (
            [self._normalize_enum(item, SIGNAL_STATUSES, "status") for item in statuses]
            if statuses
            else list(DEFAULT_STATS_STATUSES)
        )
        rows = self.repo.list_stats_rows(
            engine_version=engine_version_norm,
            horizons=horizons_norm,
            statuses=statuses_norm,
        )
        dimensions = (
            "action",
            "market",
            "market_phase",
            "source_type",
            "source_agent",
            "plan_quality",
            "data_quality_level",
            "holding_state",
        )
        breakdowns = {
            dimension: self._breakdown(rows, dimension)
            for dimension in dimensions
        }
        return {
            **self._aggregate(rows),
            "engine_version": engine_version_norm,
            "horizons": horizons_norm,
            "statuses": statuses_norm,
            "breakdowns": breakdowns,
        }

    def get_feedback(self, signal_id: int) -> Dict[str, Any]:
        signal = self._require_existing_signal(signal_id)
        row = self.repo.get_feedback(signal_id=signal.id)
        if row is None:
            return {
                "signal_id": signal.id,
                "feedback_value": None,
                "reason_code": None,
                "note": None,
                "source": None,
                "created_at": None,
                "updated_at": None,
            }
        return self._serialize_feedback(row)

    def put_feedback(
        self,
        signal_id: int,
        *,
        feedback_value: str,
        reason_code: Optional[str] = None,
        note: Optional[str] = None,
        source: str = "api",
    ) -> Dict[str, Any]:
        signal = self._require_existing_signal(signal_id)
        fields = {
            "signal_id": signal.id,
            "feedback_value": self._normalize_enum(feedback_value, FEEDBACK_VALUES, "feedback_value"),
            "reason_code": self._optional_public_text(reason_code, "reason_code", max_length=64),
            "note": self._optional_public_text(note, "note", max_length=1000),
            "source": self._normalize_enum(source or "api", FEEDBACK_SOURCES, "source"),
        }
        row = self.repo.upsert_feedback(fields)
        return self._serialize_feedback(row)

    def _evaluate_signal_horizon(self, signal: DecisionSignalRecord, horizon: str) -> Dict[str, Any]:
        base = self._snapshot_fields(signal, horizon)
        direction = self._direction_for_action(signal.action)
        if direction is None:
            return self._unable_fields(base, reason="non_directional_action")

        eval_days = SUPPORTED_OUTCOME_HORIZONS.get(horizon)
        if eval_days is None:
            return self._unable_fields(base, reason="unsupported_horizon", direction_expected=direction)

        anchor_date = self._anchor_date(signal)
        if anchor_date is None:
            return self._unable_fields(base, reason="missing_anchor_date", direction_expected=direction)

        start_bar = self.stock_repo.get_daily_on_date(code=signal.stock_code, target_date=anchor_date)
        start_price = getattr(start_bar, "close", None)
        if start_price is None:
            return self._unable_fields(
                base,
                reason="missing_anchor_price",
                direction_expected=direction,
                anchor_date=anchor_date,
                eval_window_days=eval_days,
            )
        if not self._is_positive_finite(start_price):
            return self._unable_fields(
                base,
                reason="invalid_anchor_price",
                direction_expected=direction,
                anchor_date=anchor_date,
                eval_window_days=eval_days,
                start_price=start_price,
            )

        forward_bars = self.stock_repo.get_forward_bars(
            code=signal.stock_code,
            analysis_date=anchor_date,
            eval_window_days=eval_days,
        )
        evaluation = BacktestEngine.evaluate_decision_signal(
            direction_expected=direction,
            anchor_date=anchor_date,
            start_price=float(start_price),
            forward_bars=forward_bars,
            config=EvaluationConfig(
                eval_window_days=eval_days,
                neutral_band_pct=2.0,
                engine_version=DECISION_SIGNAL_OUTCOME_ENGINE_VERSION,
            ),
        )
        return {
            **base,
            "eval_status": evaluation.get("eval_status"),
            "outcome": evaluation.get("outcome"),
            "direction_expected": direction,
            "direction_correct": evaluation.get("direction_correct"),
            "unable_reason": evaluation.get("unable_reason"),
            "anchor_date": anchor_date,
            "eval_window_days": eval_days,
            "start_price": evaluation.get("start_price", start_price),
            "end_close": evaluation.get("end_close"),
            "max_high": evaluation.get("max_high"),
            "min_low": evaluation.get("min_low"),
            "stock_return_pct": evaluation.get("stock_return_pct"),
        }

    @staticmethod
    def _direction_for_action(action: Optional[str]) -> Optional[str]:
        if action in {"buy", "add"}:
            return "up"
        if action == "hold":
            return "not_down"
        if action in {"reduce", "sell", "avoid"}:
            return "not_up"
        return None

    def _snapshot_fields(self, signal: DecisionSignalRecord, horizon: str) -> Dict[str, Any]:
        data_quality_level = self._data_quality_level(signal)
        holding_state = self._holding_state(signal)
        return {
            "signal_id": signal.id,
            "horizon": horizon,
            "engine_version": DECISION_SIGNAL_OUTCOME_ENGINE_VERSION,
            "action": signal.action,
            "market": signal.market,
            "market_phase": signal.market_phase,
            "source_type": signal.source_type,
            "source_agent": signal.source_agent,
            "plan_quality": signal.plan_quality,
            "data_quality_level": data_quality_level,
            "holding_state": holding_state,
        }

    @staticmethod
    def _unable_fields(
        base: Dict[str, Any],
        *,
        reason: str,
        direction_expected: Optional[str] = None,
        anchor_date: Optional[date] = None,
        eval_window_days: Optional[int] = None,
        start_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        return {
            **base,
            "eval_status": "unable",
            "outcome": None,
            "direction_expected": direction_expected,
            "direction_correct": None,
            "unable_reason": reason,
            "anchor_date": anchor_date,
            "eval_window_days": eval_window_days,
            "start_price": start_price,
            "end_close": None,
            "max_high": None,
            "min_low": None,
            "stock_return_pct": None,
        }

    def _anchor_date(self, signal: DecisionSignalRecord) -> Optional[date]:
        metadata = self._json_loads(signal.metadata_json)
        if isinstance(metadata, dict):
            summary = metadata.get("market_phase_summary")
            if isinstance(summary, dict):
                parsed = self._parse_date(summary.get("session_date"))
                if parsed is not None:
                    return parsed
        return self._parse_date(signal.created_at)

    def _data_quality_level(self, signal: DecisionSignalRecord) -> str:
        value = self._json_loads(signal.data_quality_summary_json)
        if isinstance(value, dict):
            for key in ("level", "quality_level"):
                level = value.get(key)
                if level not in (None, ""):
                    return self._short_label(level)
            nested = value.get("data_quality")
            if isinstance(nested, dict) and nested.get("level") not in (None, ""):
                return self._short_label(nested.get("level"))
        if isinstance(value, str) and value.strip():
            return self._short_label(value)
        return "unknown"

    def _holding_state(self, signal: DecisionSignalRecord) -> str:
        metadata = self._json_loads(signal.metadata_json)
        if isinstance(metadata, dict):
            value = str(metadata.get("holding_state") or "").strip().lower()
            if value in HOLDING_STATES:
                return value
        return "unknown"

    @staticmethod
    def _short_label(value: Any) -> str:
        text = str(value or "").strip().lower()
        return text[:24] or "unknown"

    @staticmethod
    def _json_loads(value: Optional[str]) -> Any:
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid decision signal sidecar source JSON: %s", exc)
            return None

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return date.fromisoformat(text[:10])
            except ValueError:
                return None
        return None

    @staticmethod
    def _is_positive_finite(value: Any) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(number) and number > 0

    def _horizons_for_signal(self, signal: DecisionSignalRecord, requested: Optional[List[str]]) -> List[str]:
        if requested:
            return requested
        horizon = str(signal.horizon or "").strip()
        if horizon:
            return [horizon]
        return list(SUPPORTED_OUTCOME_HORIZONS.keys())

    def _require_existing_signal(self, signal_id: int) -> DecisionSignalRecord:
        signal_id_norm = self._optional_positive_int(signal_id, "signal_id")
        row = self.signal_repo.get(signal_id_norm)
        if row is None:
            raise DecisionSignalNotFoundError(f"Decision signal not found: {signal_id_norm}")
        return row

    @staticmethod
    def _optional_positive_int(value: Any, field_name: str) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be an integer") from exc
        if number <= 0:
            raise ValueError(f"{field_name} must be positive")
        return number

    @staticmethod
    def _normalize_enum(value: Any, allowed: Iterable[str], field_name: str) -> str:
        text = str(value or "").strip()
        allowed_set = set(allowed)
        if text not in allowed_set:
            allowed_text = ", ".join(sorted(allowed_set))
            raise ValueError(f"{field_name} must be one of {allowed_text}")
        return text

    @classmethod
    def _normalize_optional_enum(cls, value: Any, allowed: Iterable[str], field_name: str) -> Optional[str]:
        if value in (None, ""):
            return None
        return cls._normalize_enum(value, allowed, field_name)

    def _normalize_horizons(self, values: Optional[List[str]]) -> Optional[List[str]]:
        if not values:
            return None
        out: List[str] = []
        for value in values:
            horizon = self._normalize_enum(value, HORIZONS, "horizon")
            if horizon not in out:
                out.append(horizon)
        return out

    @staticmethod
    def _optional_public_text(value: Any, field_name: str, *, max_length: int) -> Optional[str]:
        if value in (None, ""):
            return None
        text = sanitize_decision_signal_text(value)
        if not text:
            return None
        if len(text) > max_length:
            raise ValueError(f"{field_name} must be at most {max_length} characters")
        return text

    @staticmethod
    def _serialize_outcome(row: DecisionSignalOutcomeRecord) -> Dict[str, Any]:
        return {
            "id": row.id,
            "signal_id": row.signal_id,
            "horizon": row.horizon,
            "engine_version": row.engine_version,
            "eval_status": row.eval_status,
            "outcome": row.outcome,
            "direction_expected": row.direction_expected,
            "direction_correct": row.direction_correct,
            "unable_reason": row.unable_reason,
            "anchor_date": row.anchor_date.isoformat() if row.anchor_date else None,
            "eval_window_days": row.eval_window_days,
            "start_price": row.start_price,
            "end_close": row.end_close,
            "max_high": row.max_high,
            "min_low": row.min_low,
            "stock_return_pct": row.stock_return_pct,
            "action": row.action,
            "market": row.market,
            "market_phase": row.market_phase,
            "source_type": row.source_type,
            "source_agent": row.source_agent,
            "plan_quality": row.plan_quality,
            "data_quality_level": row.data_quality_level,
            "holding_state": row.holding_state,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    def _serialize_feedback(row: DecisionSignalFeedbackRecord) -> Dict[str, Any]:
        return {
            "signal_id": row.signal_id,
            "feedback_value": row.feedback_value,
            "reason_code": row.reason_code,
            "note": row.note,
            "source": row.source,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _breakdown(self, rows: List[DecisionSignalOutcomeRecord], dimension: str) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[DecisionSignalOutcomeRecord]] = defaultdict(list)
        for row in rows:
            value = getattr(row, dimension, None)
            key = str(value or "unknown")
            grouped[key].append(row)
        buckets = [
            {
                "dimension": dimension,
                "value": value,
                **self._aggregate(bucket_rows),
            }
            for value, bucket_rows in grouped.items()
        ]
        return sorted(buckets, key=lambda item: (-int(item["total"]), str(item["value"])))

    @staticmethod
    def _aggregate(rows: List[DecisionSignalOutcomeRecord]) -> Dict[str, Any]:
        total = len(rows)
        completed = [row for row in rows if row.eval_status == "completed"]
        unable = [row for row in rows if row.eval_status == "unable"]
        hit = sum(1 for row in completed if row.outcome == "hit")
        miss = sum(1 for row in completed if row.outcome == "miss")
        neutral = sum(1 for row in completed if row.outcome == "neutral")
        denominator = hit + miss
        returns = [
            float(row.stock_return_pct)
            for row in completed
            if row.stock_return_pct is not None
        ]
        unable_reasons = Counter(row.unable_reason or "unknown" for row in unable)
        return {
            "total": total,
            "completed": len(completed),
            "unable": len(unable),
            "hit": hit,
            "miss": miss,
            "neutral": neutral,
            "hit_rate_pct": round(hit / denominator * 100, 2) if denominator else None,
            "avg_stock_return_pct": round(sum(returns) / len(returns), 4) if returns else None,
            "unable_reasons": dict(sorted(unable_reasons.items())),
        }
