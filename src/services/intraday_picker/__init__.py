"""Isolated intraday stock-picking domain package.

Concrete DSA, AlphaSift and market-data integrations live under ``adapters``.
Domain modules must stay free of imports from legacy service implementations.
"""

from .config import IntradayPickerConfig
from .models import (
    DsaAnalysisSummary,
    FinalCandidate,
    IntradayCandidate,
    IntradayMetrics,
    StrategyHit,
)

__all__ = [
    "DsaAnalysisSummary",
    "FinalCandidate",
    "IntradayCandidate",
    "IntradayMetrics",
    "IntradayPickerConfig",
    "StrategyHit",
]
