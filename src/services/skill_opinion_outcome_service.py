# -*- coding: utf-8 -*-
"""Orchestrate locally stored daily bars into per-skill opinion outcomes."""

from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.core.skill_opinion_outcome_evaluator import (
    SUPPORTED_SKILL_OUTCOME_HORIZONS,
    SkillOpinionOutcomeEvaluation,
    SkillOpinionOutcomeEvaluator,
)
from src.market_phase_summary import extract_market_phase_summary
from src.repositories.backtest_repo import BacktestRepository
from src.repositories.skill_opinion_outcome_repo import (
    SkillOpinionOutcomeCandidate,
    SkillOpinionOutcomeRepository,
)
from src.repositories.stock_repo import StockRepository
from src.services.stock_code_utils import (
    InvalidStockCodeError,
    build_daily_code_candidates,
)
from src.services.stock_daily_window_resolver import resolve_stock_daily_window
from src.storage import (
    AnalysisHistory,
    DatabaseManager,
    SkillOpinionOutcomeRecord,
    SkillOpinionSampleRecord,
)


logger = logging.getLogger(__name__)

SKILL_OPINION_OUTCOME_ENGINE_VERSION = "skill-opinion-outcome-v1"


class SkillOpinionOutcomeService:
    """Evaluate missing and pending outcome keys without fetching external data."""

    def __init__(
        self,
        *,
        repo: Optional[SkillOpinionOutcomeRepository] = None,
        stock_repo: Optional[StockRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
    ):
        self.repo = repo or SkillOpinionOutcomeRepository(db_manager)
        self.stock_repo = stock_repo or StockRepository(db_manager)

    def run_outcomes(
        self,
        *,
        sample_id: Optional[int] = None,
        analysis_history_id: Optional[int] = None,
        skill_id: Optional[str] = None,
        stock_code: Optional[str] = None,
        horizons: Optional[Sequence[str]] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Process at most ``limit`` missing/pending sample-by-horizon keys."""

        sample_id_norm = self._optional_positive_int(sample_id, "sample_id")
        history_id_norm = self._optional_positive_int(
            analysis_history_id,
            "analysis_history_id",
        )
        skill_id_norm = self._optional_text(skill_id, "skill_id")
        stock_code_norm = self._optional_text(stock_code, "stock_code")
        horizons_norm = self._normalize_horizons(horizons)
        limit_norm = self._bounded_positive_int(limit, "limit", maximum=500)

        candidates = self.repo.list_candidate_keys(
            horizons=horizons_norm,
            engine_version=SKILL_OPINION_OUTCOME_ENGINE_VERSION,
            limit=limit_norm,
            sample_id=sample_id_norm,
            analysis_history_id=history_id_norm,
            skill_id=skill_id_norm,
            stock_code=stock_code_norm,
        )

        items: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        counts = {"created": 0, "updated": 0, "skipped": 0}
        for candidate in candidates:
            try:
                evaluation = self._evaluate_candidate(candidate)
                fields = {
                    "skill_opinion_sample_id": int(candidate.sample.id),
                    "horizon": candidate.horizon,
                    "engine_version": SKILL_OPINION_OUTCOME_ENGINE_VERSION,
                    **evaluation.to_fields(),
                }
                _, persist_status = self.repo.persist_outcome(fields)
                if persist_status == "missing_sample":
                    counts["skipped"] += 1
                    continue
                counts[persist_status] += 1
                row = self.repo.get_outcome(
                    sample_id=int(candidate.sample.id),
                    horizon=candidate.horizon,
                    engine_version=SKILL_OPINION_OUTCOME_ENGINE_VERSION,
                )
                if row is not None:
                    items.append(self._serialize_outcome(row, candidate.sample))
            except Exception as exc:
                error = {
                    "sample_id": int(candidate.sample.id),
                    "horizon": candidate.horizon,
                    "error_type": type(exc).__name__,
                }
                errors.append(error)
                logger.warning(
                    "Skill opinion outcome evaluation deferred after transient failure: "
                    "sample_id=%s horizon=%s error_type=%s",
                    error["sample_id"],
                    error["horizon"],
                    error["error_type"],
                    exc_info=True,
                )

        return {
            "items": items,
            "processed_keys": len(candidates),
            "created": counts["created"],
            "updated": counts["updated"],
            "skipped": counts["skipped"],
            "failed": len(errors),
            "errors": errors,
            "limit_unit": "outcome_key",
            "engine_version": SKILL_OPINION_OUTCOME_ENGINE_VERSION,
        }

    def _evaluate_candidate(
        self,
        candidate: SkillOpinionOutcomeCandidate,
    ) -> SkillOpinionOutcomeEvaluation:
        analysis_date, exact_start_required = self._resolve_analysis_date(candidate.history)
        try:
            daily_code_candidates = build_daily_code_candidates(
                candidate.sample.stock_code
            )
        except InvalidStockCodeError:
            return SkillOpinionOutcomeEvaluation(
                eval_status="unable",
                unable_reason="invalid_stock_code",
                analysis_date=analysis_date,
            )

        window = None
        if analysis_date is not None:
            window = resolve_stock_daily_window(
                stock_repo=self.stock_repo,
                code_candidates=daily_code_candidates,
                analysis_date=analysis_date,
                eval_window_days=SUPPORTED_SKILL_OUTCOME_HORIZONS.get(
                    candidate.horizon,
                    0,
                ),
                exact_start_required=exact_start_required,
            )

        return SkillOpinionOutcomeEvaluator.evaluate(
            signal=candidate.sample.signal,
            horizon=candidate.horizon,
            analysis_date=analysis_date,
            start_bar=window.start_bar if window is not None else None,
            forward_bars=window.forward_bars if window is not None else (),
        )

    @classmethod
    def _resolve_analysis_date(
        cls,
        history: AnalysisHistory,
    ) -> Tuple[Optional[date], bool]:
        summary = extract_market_phase_summary(history.context_snapshot)
        if isinstance(summary, dict):
            effective_date = cls._parse_date(summary.get("effective_daily_bar_date"))
            if effective_date is not None:
                return effective_date, True

        snapshot_date = BacktestRepository.parse_analysis_date_from_snapshot(
            history.context_snapshot
        )
        if snapshot_date is not None:
            return snapshot_date, False
        created_at = getattr(history, "created_at", None)
        if isinstance(created_at, datetime):
            return created_at.date(), False
        return None, False

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value.strip()[:10])
            except ValueError:
                return None
        return None

    @staticmethod
    def _normalize_horizons(values: Optional[Sequence[str]]) -> List[str]:
        if values is None:
            return list(SUPPORTED_SKILL_OUTCOME_HORIZONS)
        if not values:
            raise ValueError("horizons must not be empty")

        normalized: List[str] = []
        for value in values:
            horizon = str(value or "").strip()
            if horizon not in SUPPORTED_SKILL_OUTCOME_HORIZONS:
                raise ValueError(
                    "horizon must be one of "
                    + ", ".join(SUPPORTED_SKILL_OUTCOME_HORIZONS)
                )
            if horizon not in normalized:
                normalized.append(horizon)
        return normalized

    @staticmethod
    def _optional_positive_int(value: Any, field_name: str) -> Optional[int]:
        if value is None:
            return None
        return SkillOpinionOutcomeService._bounded_positive_int(
            value,
            field_name,
        )

    @staticmethod
    def _bounded_positive_int(
        value: Any,
        field_name: str,
        *,
        maximum: Optional[int] = None,
    ) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field_name} must be a positive integer")
        if isinstance(value, int):
            number = value
        elif isinstance(value, str) and value.strip().isdigit():
            number = int(value)
        else:
            raise ValueError(f"{field_name} must be a positive integer")
        if number <= 0 or (maximum is not None and number > maximum):
            suffix = f" no greater than {maximum}" if maximum is not None else ""
            raise ValueError(f"{field_name} must be a positive integer{suffix}")
        return number

    @staticmethod
    def _optional_text(value: Any, field_name: str) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError(f"{field_name} must not be blank")
        return text

    @staticmethod
    def _serialize_outcome(
        row: SkillOpinionOutcomeRecord,
        sample: SkillOpinionSampleRecord,
    ) -> Dict[str, Any]:
        return {
            "id": row.id,
            "skill_opinion_sample_id": row.skill_opinion_sample_id,
            "analysis_history_id": sample.analysis_history_id,
            "stock_code": sample.stock_code,
            "skill_id": sample.skill_id,
            "signal": sample.signal,
            "horizon": row.horizon,
            "engine_version": row.engine_version,
            "eval_status": row.eval_status,
            "outcome": row.outcome,
            "direction_correct": row.direction_correct,
            "unable_reason": row.unable_reason,
            "analysis_date": row.analysis_date.isoformat() if row.analysis_date else None,
            "start_trade_date": (
                row.start_trade_date.isoformat() if row.start_trade_date else None
            ),
            "end_trade_date": row.end_trade_date.isoformat() if row.end_trade_date else None,
            "start_price": row.start_price,
            "end_close": row.end_close,
            "stock_return_pct": row.stock_return_pct,
            "directional_return_pct": row.directional_return_pct,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
