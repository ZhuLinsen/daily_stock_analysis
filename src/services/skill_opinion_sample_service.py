# -*- coding: utf-8 -*-
"""Capture immutable, low-sensitivity skill opinion samples."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Iterable, Optional

from src.agent.protocols import normalize_strategy_signal
from src.agent.runtime_facts import SkillOpinionFact
from src.repositories.skill_opinion_sample_repo import SkillOpinionSampleRepository
from src.storage import DatabaseManager


SKILL_OPINION_SAMPLE_SCHEMA_VERSION = "skill-opinion-sample-v1"
_QUALITY_LEVELS = frozenset({"good", "usable", "limited", "poor"})


class SkillOpinionSampleService:
    """Validate and persist samples; outcome evaluation is intentionally out of scope."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        repo: Optional[SkillOpinionSampleRepository] = None,
    ):
        self.repo = repo or SkillOpinionSampleRepository(db_manager)

    def persist(
        self,
        *,
        analysis_history_id: int,
        stock_code: str,
        opinions: Iterable[SkillOpinionFact],
        data_quality_level: Optional[str] = None,
    ) -> int:
        try:
            normalized_history_id = int(analysis_history_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("analysis_history_id must be a positive integer") from exc
        if isinstance(analysis_history_id, bool) or normalized_history_id <= 0:
            raise ValueError("analysis_history_id must be a positive integer")
        normalized_code = str(stock_code or "").strip()
        if not normalized_code:
            raise ValueError("stock_code is required")
        if len(normalized_code) > 16:
            raise ValueError("stock_code exceeds 16 characters")

        quality = str(data_quality_level or "").strip().lower()
        if quality not in _QUALITY_LEVELS:
            quality = None

        rows = []
        for opinion in opinions:
            skill_id = str(opinion.skill_id or "").strip()
            signal, invalid, _ = normalize_strategy_signal(opinion.signal)
            if not skill_id or invalid:
                raise ValueError("skill opinion requires a valid skill_id and signal")
            if len(skill_id) > 128:
                raise ValueError("skill_id exceeds 128 characters")
            if isinstance(opinion.confidence, bool):
                raise ValueError("skill opinion confidence must be numeric")
            try:
                confidence = float(opinion.confidence)
            except (OverflowError, TypeError, ValueError) as exc:
                raise ValueError("skill opinion confidence must be numeric") from exc
            if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                raise ValueError("skill opinion confidence must be between 0 and 1")
            rows.append(
                {
                    "analysis_history_id": normalized_history_id,
                    "stock_code": normalized_code,
                    "skill_id": skill_id,
                    "skill_version": _optional_text(opinion.skill_version, 64),
                    "signal": signal,
                    "confidence": confidence,
                    "horizon": _optional_text(opinion.horizon, 16),
                    "data_quality_level": quality,
                    "opinion_created_at": _timestamp_to_datetime(opinion.observed_at),
                    "sample_schema_version": SKILL_OPINION_SAMPLE_SCHEMA_VERSION,
                }
            )
        return self.repo.insert_missing(rows) if rows else 0


def _optional_text(value: object, max_length: int) -> Optional[str]:
    text = str(value or "").strip()
    return text[:max_length] if text else None


def _timestamp_to_datetime(value: Optional[float]) -> Optional[datetime]:
    if value is None:
        return None
    try:
        timestamp = float(value)
        if not math.isfinite(timestamp) or timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, TypeError, ValueError):
        return None
