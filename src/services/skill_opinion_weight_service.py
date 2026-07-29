# -*- coding: utf-8 -*-
"""Conservative runtime weights from attributable Skill Opinion outcomes."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from src.core.skill_opinion_outcome_evaluator import (
    SUPPORTED_SKILL_OUTCOME_HORIZONS,
)
from src.services.skill_opinion_outcome_service import (
    SKILL_OPINION_OUTCOME_ENGINE_VERSION,
)
from src.services.skill_opinion_performance_service import (
    MIN_SKILL_OUTCOME_SAMPLE_SIZE,
    SkillOpinionPerformanceService,
)


logger = logging.getLogger(__name__)

_BETA_PRIOR_HITS = 15
_BETA_PRIOR_MISSES = 15
_BETA_PRIOR_SIZE = _BETA_PRIOR_HITS + _BETA_PRIOR_MISSES
_UNABLE_PENALTY = 0.25
MAX_SKILL_OPINION_WEIGHT_FACTOR = 1.2
MIN_SKILL_OPINION_WEIGHT_FACTOR = (
    1.0 / MAX_SKILL_OPINION_WEIGHT_FACTOR
)


class SkillOpinionWeightService:
    """Convert sufficient Outcome statistics into bounded Skill factors."""

    def __init__(
        self,
        *,
        performance_service: Optional[SkillOpinionPerformanceService] = None,
        engine_version: str = SKILL_OPINION_OUTCOME_ENGINE_VERSION,
    ):
        self.performance_service = (
            performance_service or SkillOpinionPerformanceService()
        )
        self.engine_version = str(engine_version or "").strip()

    def compute_weights(
        self,
        skill_ids: Sequence[str],
    ) -> Dict[str, float]:
        """Return one fail-neutral performance factor per requested Skill."""

        requested = self._normalize_skill_ids(skill_ids)
        neutral = {skill_id: 1.0 for skill_id in requested}
        if not requested or not self.engine_version:
            return neutral

        try:
            stats = self.performance_service.get_stats(
                engine_version=self.engine_version,
                skill_ids=requested,
            )
            if not isinstance(stats, dict):
                return neutral
            if stats.get("engine_version") != self.engine_version:
                return neutral
            buckets = stats.get("buckets")
            if not isinstance(buckets, list):
                return neutral
        except Exception:
            logger.debug(
                "Failed to read Skill Opinion performance statistics",
                exc_info=True,
            )
            return neutral

        requested_set = set(requested)
        scored: Dict[str, List[Tuple[float, float]]] = {
            skill_id: [] for skill_id in requested
        }
        invalid_skills: Set[str] = set()
        seen_buckets: Set[Tuple[str, str]] = set()

        for bucket in buckets:
            skill_id = self._bucket_skill_id(bucket)
            if skill_id not in requested_set:
                continue
            if not self._bucket_identity_is_current(bucket):
                continue

            horizon = str(bucket.get("horizon") or "").strip()
            bucket_key = (skill_id, horizon)
            if bucket_key in seen_buckets:
                invalid_skills.add(skill_id)
                continue
            seen_buckets.add(bucket_key)

            if not self._declares_sufficient_sample(bucket):
                continue

            score = self._score_bucket(bucket)
            if score is None:
                invalid_skills.add(skill_id)
                continue
            scored[skill_id].append(score)

        for skill_id, bucket_scores in scored.items():
            if skill_id in invalid_skills or not bucket_scores:
                continue
            evidence_total = sum(
                evidence_strength
                for _, evidence_strength in bucket_scores
            )
            if not math.isfinite(evidence_total) or evidence_total <= 0:
                continue
            combined_score = sum(
                bucket_score * evidence_strength
                for bucket_score, evidence_strength in bucket_scores
            ) / evidence_total
            factor = math.exp(
                math.log(MAX_SKILL_OPINION_WEIGHT_FACTOR)
                * combined_score
            )
            if not math.isfinite(factor):
                continue
            neutral[skill_id] = min(
                MAX_SKILL_OPINION_WEIGHT_FACTOR,
                max(MIN_SKILL_OPINION_WEIGHT_FACTOR, factor),
            )

        return neutral

    def _bucket_identity_is_current(self, bucket: Any) -> bool:
        if not isinstance(bucket, dict):
            return False
        horizon = str(bucket.get("horizon") or "").strip()
        return (
            bucket.get("engine_version") == self.engine_version
            and horizon in SUPPORTED_SKILL_OUTCOME_HORIZONS
        )

    @staticmethod
    def _bucket_skill_id(bucket: Any) -> str:
        if not isinstance(bucket, dict):
            return ""
        return str(bucket.get("skill_id") or "").strip()

    @staticmethod
    def _declares_sufficient_sample(bucket: Dict[str, Any]) -> bool:
        return bucket.get("sample_sufficient") is True

    @staticmethod
    def _score_bucket(
        bucket: Dict[str, Any],
    ) -> Optional[Tuple[float, float]]:
        evaluated = SkillOpinionWeightService._count(
            bucket.get("evaluated")
        )
        hit = SkillOpinionWeightService._count(bucket.get("hit"))
        miss = SkillOpinionWeightService._count(bucket.get("miss"))
        observational = SkillOpinionWeightService._count(
            bucket.get("observational")
        )
        unable = SkillOpinionWeightService._count(bucket.get("unable"))
        if None in (evaluated, hit, miss, observational, unable):
            return None
        if evaluated < MIN_SKILL_OUTCOME_SAMPLE_SIZE:
            return None
        if hit + miss != evaluated:
            return None

        posterior_hit_rate = (
            hit + _BETA_PRIOR_HITS
        ) / (evaluated + _BETA_PRIOR_SIZE)
        direction_score = 2.0 * posterior_hit_rate - 1.0
        terminal_count = evaluated + observational + unable
        if terminal_count <= 0:
            return None
        unable_rate = unable / terminal_count
        bucket_score = min(
            1.0,
            max(
                -1.0,
                direction_score - _UNABLE_PENALTY * unable_rate,
            ),
        )
        evidence_strength = evaluated / (
            evaluated + _BETA_PRIOR_SIZE
        )
        if not all(
            math.isfinite(value)
            for value in (bucket_score, evidence_strength)
        ):
            return None
        return bucket_score, evidence_strength

    @staticmethod
    def _count(value: Any) -> Optional[int]:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if value >= 0 else None

    @staticmethod
    def _normalize_skill_ids(values: Sequence[str]) -> List[str]:
        normalized: List[str] = []
        for value in values:
            skill_id = str(value or "").strip()
            if skill_id and skill_id not in normalized:
                normalized.append(skill_id)
        return normalized
