# -*- coding: utf-8 -*-
"""
Shared protocols — common data structures for multi-agent communication.

Provides the foundational types that all agents, runners, and orchestrators
share.  These are intentionally plain dataclasses (no ORM dependency) so
they can be serialised, logged, and passed across process boundaries.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================
# Enums
# ============================================================

class Signal(str, Enum):
    """Standardised trading signal labels."""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


_CANONICAL_DECISION_SIGNAL_MAP: Dict[str, str] = {
    "strong_buy": "buy",
    "buy": "buy",
    "hold": "hold",
    "sell": "sell",
    "strong_sell": "sell",
}


def normalize_decision_signal(signal: Any, default: str = "hold") -> str:
    """Map model-facing signal labels to the dashboard's stable enum."""
    if not isinstance(signal, str):
        return default
    normalized = signal.strip().lower()
    return _CANONICAL_DECISION_SIGNAL_MAP.get(normalized, default)


class StageStatus(str, Enum):
    """Lifecycle status of a pipeline stage."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ============================================================
# AgentContext — shared state bag for a single analysis run
# ============================================================

@dataclass
class AgentContext:
    """Shared context carried across all agents in a single run.

    Any agent can read from / write to this context.  The orchestrator
    is responsible for seeding the initial fields and collecting
    final results.
    """

    # --- identity ---
    query: str = ""
    stock_code: str = ""
    stock_name: str = ""
    session_id: str = ""

    # --- collected data (populated by data-fetching stages) ---
    data: Dict[str, Any] = field(default_factory=dict)
    # Typical keys: "realtime_quote", "daily_history", "trend_result",
    #               "chip_distribution", "news_context"

    # --- opinions from individual agents ---
    opinions: List["AgentOpinion"] = field(default_factory=list)

    # --- risk flags raised by RiskAgent ---
    risk_flags: List[Dict[str, Any]] = field(default_factory=list)

    # --- arbitrary metadata ---
    meta: Dict[str, Any] = field(default_factory=dict)
    # e.g. {"strategies_requested": [...], "user_platform": "feishu"}

    # --- timing ---
    created_at: float = field(default_factory=time.time)

    # -----------------------------------------------------------------
    # Convenience helpers
    # -----------------------------------------------------------------

    def add_opinion(self, opinion: "AgentOpinion") -> None:
        """Append an opinion and auto-set the timestamp if missing."""
        if opinion.timestamp == 0:
            opinion.timestamp = time.time()
        self.opinions.append(opinion)

    def add_risk_flag(self, category: str, description: str, severity: str = "medium") -> None:
        self.risk_flags.append({
            "category": category,
            "description": description,
            "severity": severity,
            "timestamp": time.time(),
        })

    def get_data(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set_data(self, key: str, value: Any) -> None:
        self.data[key] = value

    @property
    def has_risk_flags(self) -> bool:
        return len(self.risk_flags) > 0


# ============================================================
# AgentOpinion — structured output from any single agent
# ============================================================

@dataclass
class AgentOpinion:
    """One agent's analysis opinion on a stock.

    Every agent that participates in a multi-agent flow is expected
    to produce one ``AgentOpinion`` appended to ``AgentContext.opinions``.
    """

    agent_name: str = ""
    signal: str = ""  # free-form or Signal enum value
    confidence: float = 0.0  # 0.0 – 1.0
    reasoning: str = ""
    key_levels: Dict[str, float] = field(default_factory=dict)
    # e.g. {"support": 1800.0, "resistance": 1950.0, "stop_loss": 1760.0}
    raw_data: Dict[str, Any] = field(default_factory=dict)
    # Any extra payload the agent wants to pass downstream
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        """Clamp confidence to [0.0, 1.0]."""
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    @property
    def signal_enum(self) -> Optional[Signal]:
        """Try to parse ``signal`` into a ``Signal`` enum; None if unknown."""
        try:
            return Signal(self.signal)
        except ValueError:
            return None


# ============================================================
# StageResult — return type from a single pipeline stage
# ============================================================

@dataclass
class StageResult:
    """Outcome of one pipeline stage (agent execution).

    Used by the orchestrator to decide whether to continue,
    retry, or abort.
    """

    stage_name: str = ""
    status: StageStatus = StageStatus.PENDING
    opinion: Optional[AgentOpinion] = None
    error: Optional[str] = None
    duration_s: float = 0.0
    tokens_used: int = 0
    tool_calls_count: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == StageStatus.COMPLETED


# ============================================================
# AgentRunStats — aggregate statistics for an entire run
# ============================================================

@dataclass
class AgentRunStats:
    """Aggregate run statistics across all agents in a pipeline.

    Collected by the orchestrator and surfaced in logs, API responses,
    and progress callbacks.
    """

    total_stages: int = 0
    completed_stages: int = 0
    failed_stages: int = 0
    skipped_stages: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    total_duration_s: float = 0.0
    models_used: List[str] = field(default_factory=list)
    stage_results: List[StageResult] = field(default_factory=list)

    def record_stage(self, result: StageResult) -> None:
        """Record a stage result and update counters.

        Handles all ``StageStatus`` values including RUNNING/PENDING
        (counted but not classified as completed/failed/skipped).
        """
        self.stage_results.append(result)
        self.total_stages += 1
        self.total_tokens += result.tokens_used
        self.total_tool_calls += result.tool_calls_count
        self.total_duration_s += result.duration_s

        if result.status == StageStatus.COMPLETED:
            self.completed_stages += 1
        elif result.status == StageStatus.FAILED:
            self.failed_stages += 1
        elif result.status == StageStatus.SKIPPED:
            self.skipped_stages += 1
        # RUNNING / PENDING are counted in total_stages but not in any sub-counter

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_stages": self.total_stages,
            "completed_stages": self.completed_stages,
            "failed_stages": self.failed_stages,
            "skipped_stages": self.skipped_stages,
            "total_tokens": self.total_tokens,
            "total_tool_calls": self.total_tool_calls,
            "total_duration_s": round(self.total_duration_s, 2),
            "models_used": self.models_used,
        }
