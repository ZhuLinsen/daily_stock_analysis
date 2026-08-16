"""Ports used by the intraday picker domain.

Only adapters may bind these interfaces to concrete AlphaSift, Pytdx, DSA,
notification or persistence implementations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, Sequence

from .models import DsaAnalysisSummary, IntradayCandidate, StrategyHit


class StrategyGateway(Protocol):
    def screen(self, profile: str, now: datetime) -> list[StrategyHit]: ...


class IntradayMarketGateway(Protocol):
    def get_intraday_context(self, stock_code: str, now: datetime) -> dict[str, Any]: ...


class HistoryRepository(Protocol):
    def get_or_build_baseline(
        self, stock_code: str, now: datetime, market_gateway: IntradayMarketGateway
    ) -> list[dict[str, Any]]: ...


class DsaAnalysisGateway(Protocol):
    def submit_or_reuse(self, candidates: Sequence[IntradayCandidate], now: datetime) -> dict[str, str]: ...
    def collect_available(self, candidates: Sequence[IntradayCandidate], now: datetime) -> dict[str, DsaAnalysisSummary]: ...


class NotificationGateway(Protocol):
    def send_preliminary(self, run_id: str, candidates: Sequence[IntradayCandidate]) -> None: ...
    def send_final(self, run_id: str, candidates: Sequence[Any]) -> None: ...


class RunStateRepository(Protocol):
    def is_completed(self, run_id: str) -> bool: ...
    def save_preliminary(self, run_id: str, candidates: Sequence[IntradayCandidate], metadata: dict[str, Any]) -> None: ...
    def save_dsa_tasks(self, run_id: str, task_refs: dict[str, str]) -> None: ...
    def save_final(self, run_id: str, candidates: Sequence[Any]) -> None: ...
