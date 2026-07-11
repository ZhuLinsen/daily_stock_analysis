# -*- coding: utf-8 -*-
"""Canonical score-to-decision scale shared by reports and DecisionSignal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


CANONICAL_DECISION_SCALE_VERSION = "decision-scale-v1"


@dataclass(frozen=True)
class DecisionScaleBand:
    min_score: int
    max_score: int
    signal_key: str
    action: str
    decision_type: str
    label_zh: str
    description_zh: str


CANONICAL_DECISION_SCALE: tuple[DecisionScaleBand, ...] = (
    DecisionScaleBand(80, 100, "strong_buy", "buy", "buy", "强烈买入", "高胜率机会，可执行买入/加仓计划"),
    DecisionScaleBand(60, 79, "buy", "buy", "buy", "买入", "偏积极机会，允许少量待确认项"),
    DecisionScaleBand(40, 59, "watch", "watch", "hold", "观望", "信号分歧或确认不足，等待触发条件"),
    DecisionScaleBand(20, 39, "reduce", "reduce", "sell", "减仓", "风险明显抬升，优先降低暴露"),
    DecisionScaleBand(0, 19, "sell", "sell", "sell", "卖出", "趋势或风险显著恶化，优先退出"),
)


CANONICAL_DECISION_SCALE_PROMPT_ZH = """## Canonical 评分与动作口径

- `sentiment_score`、`operation_advice`、三态 `decision_type` 与八态 `action` 必须按同一口径表达。
- 80-100：强烈买入，`action=buy`，`decision_type=buy`。
- 60-79：买入，`action=buy`，`decision_type=buy`。
- 40-59：观望，`action=watch`，`decision_type=hold`。
- 20-39：减仓，`action=reduce`，`decision_type=sell`。
- 0-19：卖出，`action=sell`，`decision_type=sell`。
- `decision_type` 只保留 `buy|hold|sell` 兼容统计；更细建议必须写入 `action`。
- 若 score >= 60 但最终 `action` 是 `hold/watch`，或 score < 40 但最终 `action` 是 `hold/watch`，必须在 `guardrail_reason` 或 `dashboard.decision_stability.reason` 中说明降级原因。"""


def normalize_score(value: Any) -> Optional[int]:
    """Return a bounded integer score when possible."""

    try:
        score = int(float(value))
    except (TypeError, ValueError):
        return None
    if 0 <= score <= 100:
        return score
    return None


def decision_band_for_score(value: Any) -> Optional[DecisionScaleBand]:
    """Return the canonical decision band for a 0-100 score."""

    score = normalize_score(value)
    if score is None:
        return None
    for band in CANONICAL_DECISION_SCALE:
        if band.min_score <= score <= band.max_score:
            return band
    return None


def signal_key_for_score(value: Any) -> Optional[str]:
    band = decision_band_for_score(value)
    return band.signal_key if band else None


def action_for_score(value: Any) -> Optional[str]:
    band = decision_band_for_score(value)
    return band.action if band else None


def decision_type_for_score(value: Any) -> Optional[str]:
    band = decision_band_for_score(value)
    return band.decision_type if band else None


def score_band_metadata(value: Any) -> dict[str, Any]:
    """Return stable metadata for persistence and diagnostics."""

    score = normalize_score(value)
    band = decision_band_for_score(score)
    if score is None or band is None:
        return {}
    return {
        "scale_version": CANONICAL_DECISION_SCALE_VERSION,
        "score": score,
        "score_band": f"{band.min_score}-{band.max_score}",
        "signal_key": band.signal_key,
        "canonical_action": band.action,
        "canonical_decision_type": band.decision_type,
    }


def score_action_conflicts_without_guardrail(
    *,
    score: Any,
    action: Any,
    guardrail_reason: Any = None,
) -> bool:
    """Return True when a neutral action conflicts with a directional score."""

    if str(guardrail_reason or "").strip():
        return False
    normalized_action = str(action or "").strip().lower()
    if normalized_action not in {"hold", "watch"}:
        return False
    score_action = action_for_score(score)
    return score_action in {"buy", "reduce", "sell"}
