"""Composition root for the intraday picker.

Only this module wires domain orchestration to concrete legacy adapters.
"""

from __future__ import annotations

from .adapters.alphasift_adapter import AlphaSiftStrategyAdapter
from .adapters.dsa_task_queue_adapter import DsaTaskQueueAdapter
from .adapters.notification_adapter import DsaNotificationAdapter
from .adapters.run_state_repository import JsonRunStateRepository
from .adapters.sqlite_history_repository import SqliteHistoryRepository
from .adapters.tdx_intraday_adapter import TdxIntradayAdapter
from .config import IntradayPickerConfig
from .orchestrator import IntradayPickerOrchestrator


def build_intraday_picker(config: IntradayPickerConfig | None = None) -> IntradayPickerOrchestrator:
    config = config or IntradayPickerConfig.from_env()
    market_gateway = TdxIntradayAdapter()
    return IntradayPickerOrchestrator(
        config=config,
        strategy_gateway=AlphaSiftStrategyAdapter(config),
        market_gateway=market_gateway,
        history_repository=SqliteHistoryRepository(baseline_days=config.baseline_days),
        dsa_gateway=DsaTaskQueueAdapter(config),
        notification_gateway=DsaNotificationAdapter(),
        run_state=JsonRunStateRepository(),
    )
