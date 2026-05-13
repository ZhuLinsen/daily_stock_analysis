# -*- coding: utf-8 -*-
"""Static checks for notification env mappings in daily_analysis.yml."""

from pathlib import Path

import yaml

from src.services.notification_diagnostics import (
    P0_ACTIONS_ENV_KEYS,
    P3_ROUTE_ENV_KEYS,
    P4_NOISE_ENV_KEYS,
    P6_CHANNEL_ACTIONS_ENV_KEYS,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT_DIR / ".github/workflows/daily_analysis.yml"

P0_EXCLUDED_BEHAVIOR_SWITCHES = {
    "MARKDOWN_TO_IMAGE_CHANNELS",
    "MERGE_EMAIL_NOTIFICATION",
}


def _load_daily_analysis_env() -> dict[str, str]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["analyze"]["steps"]
    analyze_step = next((step for step in steps if step.get("name") == "执行股票分析"), None)
    available_step_names = [step.get("name", "<unnamed>") for step in steps]
    assert analyze_step is not None, (
        "Expected daily_analysis.yml job analyze to include a step named "
        f"'执行股票分析'; available step names: {available_step_names}"
    )
    return analyze_step["env"]


def test_daily_analysis_maps_p0_notification_env_keys() -> None:
    env = _load_daily_analysis_env()

    for key in P0_ACTIONS_ENV_KEYS:
        assert key in env


def test_daily_analysis_maps_p3_notification_route_env_keys() -> None:
    env = _load_daily_analysis_env()

    for key in P3_ROUTE_ENV_KEYS:
        assert key in env


def test_daily_analysis_maps_p4_notification_noise_env_keys() -> None:
    env = _load_daily_analysis_env()

    for key in P4_NOISE_ENV_KEYS:
        assert key in env


def test_daily_analysis_maps_p6_channel_env_keys() -> None:
    env = _load_daily_analysis_env()

    for key in P6_CHANNEL_ACTIONS_ENV_KEYS:
        assert key in env


def test_daily_analysis_keeps_deferred_behavior_switches_unmapped() -> None:
    env = _load_daily_analysis_env()

    for key in P0_EXCLUDED_BEHAVIOR_SWITCHES:
        assert key not in env
