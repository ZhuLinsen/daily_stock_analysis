"""Configuration for the isolated intraday picker.

The public environment surface is intentionally small. Detailed scoring
thresholds remain code/profile settings so normal operation is simple.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class IntradayPickerConfig:
    enabled: bool = False
    profile: str = "strong_start"
    schedule_times: tuple[str, ...] = ("09:35", "09:45", "09:55")
    top_n: int = 10
    final_top_n: int = 5
    baseline_days: int = 20
    dsa_enabled: bool = True
    dsa_report_type: str = "brief"
    dsa_cache_minutes: int = 20
    notify_preliminary: bool = True
    notify_final: bool = True
    candidate_limit_per_strategy: int = 30

    @classmethod
    def from_env(cls) -> "IntradayPickerConfig":
        times = tuple(
            item.strip()
            for item in os.getenv("INTRADAY_PICKER_TIMES", "09:35,09:45,09:55").split(",")
            if item.strip()
        ) or ("09:35", "09:45", "09:55")
        report_type = os.getenv("INTRADAY_DSA_REPORT_TYPE", "brief").strip().lower()
        if report_type not in {"brief", "simple", "detailed", "full"}:
            report_type = "brief"
        return cls(
            enabled=_bool_env("INTRADAY_PICKER_ENABLED", False),
            profile=os.getenv("INTRADAY_PICKER_PROFILE", "strong_start").strip() or "strong_start",
            schedule_times=times,
            top_n=_int_env("INTRADAY_PICKER_TOP_N", 10),
            final_top_n=_int_env("INTRADAY_FINAL_TOP_N", 5),
            baseline_days=_int_env("INTRADAY_BASELINE_DAYS", 20, 5),
            dsa_enabled=_bool_env("INTRADAY_DSA_ENABLED", True),
            dsa_report_type=report_type,
            dsa_cache_minutes=_int_env("INTRADAY_DSA_CACHE_MINUTES", 20),
            notify_preliminary=_bool_env("INTRADAY_NOTIFY_PRELIMINARY", True),
            notify_final=_bool_env("INTRADAY_NOTIFY_FINAL", True),
        )
