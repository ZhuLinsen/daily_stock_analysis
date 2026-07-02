# -*- coding: utf-8 -*-
"""
===================================
Market Review Workbench - Pydantic Schema
===================================

Defines MarketReviewJudgmentSchema for validating the JSON-only LLM
"workbench judgment" call used by the market review (Issue #1584).

Follows the same leniency conventions as src/schemas/report_schema.py:
all fields Optional, ``extra="allow"``; the business layer (deterministic
merge in src/core/market_review_workbench.py) is responsible for honesty
checks such as news_index binding and name matching.
"""

import logging
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

logger = logging.getLogger(__name__)


def _coerce_str_list(value: Any) -> Any:
    """LLMs frequently return a scalar where a list is expected."""
    if value is None or isinstance(value, list):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else None
    return value


class WorkbenchIndexComment(BaseModel):
    """Per-index judgment; matched to payload indices by ``code`` (or name)."""

    model_config = ConfigDict(extra="allow")

    code: Optional[str] = None
    name: Optional[str] = None
    comment: Optional[str] = None


class WorkbenchSectorComment(BaseModel):
    """Per-sector judgment; matched to payload sectors by exact ``name``."""

    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    persistence: Optional[str] = None
    comment: Optional[str] = None


class WorkbenchCatalyst(BaseModel):
    """News catalyst classification; must reference a provided news item."""

    model_config = ConfigDict(extra="allow")

    news_index: Optional[int] = None
    nature: Optional[str] = None
    scope: Optional[str] = None
    duration: Optional[str] = None
    digestion: Optional[str] = None
    comment: Optional[str] = None


class WorkbenchStyleRotation(BaseModel):
    """Style rotation judgment (strong vs weak styles/sectors)."""

    model_config = ConfigDict(extra="allow")

    strong: Optional[List[str]] = None
    weak: Optional[List[str]] = None
    comment: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_lists(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in ("strong", "weak"):
                data[key] = _coerce_str_list(data.get(key))
        return data


class WorkbenchNextSessionPlan(BaseModel):
    """Next-session trading plan judgment."""

    model_config = ConfigDict(extra="allow")

    position_advice: Optional[str] = None
    focus_sectors: Optional[List[str]] = None
    avoid_sectors: Optional[List[str]] = None
    key_levels: Optional[List[str]] = None
    risk_triggers: Optional[List[str]] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_lists(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in ("focus_sectors", "avoid_sectors", "key_levels", "risk_triggers"):
                data[key] = _coerce_str_list(data.get(key))
        return data


class MarketReviewJudgmentSchema(BaseModel):
    """
    Top-level schema for the market-review workbench judgment JSON.

    Deterministic fields (temperature, MA values, divergence diagnosis,
    sector leaders) are computed in Python and always win on conflict;
    this schema only carries LLM judgment fields.
    """

    model_config = ConfigDict(extra="allow")

    market_state: Optional[str] = None
    core_conclusion: Optional[str] = None
    weight_stock_note: Optional[str] = None
    style_rotation: Optional[WorkbenchStyleRotation] = None
    indices: Optional[List[WorkbenchIndexComment]] = None
    sectors: Optional[List[WorkbenchSectorComment]] = None
    catalysts: Optional[List[WorkbenchCatalyst]] = None
    next_session_plan: Optional[WorkbenchNextSessionPlan] = None


def validate_market_review_judgment(data: Any) -> Optional[dict]:
    """Validate a parsed judgment dict; return a cleaned dict or None.

    None means "judgment unavailable" — the caller degrades to the
    deterministic workbench core and records a data-quality note.
    """
    if not isinstance(data, dict):
        return None
    try:
        model = MarketReviewJudgmentSchema.model_validate(data)
    except ValidationError as exc:
        logger.warning(
            "MarketReviewJudgmentSchema validation failed; dropping LLM judgment: %s",
            str(exc)[:200],
        )
        return None
    return model.model_dump(exclude_none=True)
