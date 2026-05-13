# -*- coding: utf-8 -*-
"""Notification route configuration helpers.

This module intentionally works with plain strings only. Importing
``NotificationChannel`` here would create a dependency cycle with the runtime
notification service.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

ROUTABLE_NOTIFICATION_CHANNELS: Tuple[str, ...] = (
    "wechat",
    "feishu",
    "telegram",
    "email",
    "pushover",
    "ntfy",
    "pushplus",
    "serverchan3",
    "custom",
    "discord",
    "slack",
    "astrbot",
)
ROUTABLE_NOTIFICATION_CHANNEL_SET = frozenset(ROUTABLE_NOTIFICATION_CHANNELS)

NOTIFICATION_ROUTE_CONFIGS: Dict[str, Dict[str, str]] = {
    "report": {
        "env_key": "NOTIFICATION_REPORT_CHANNELS",
        "config_attr": "notification_report_channels",
        "description": "Routes stock, daily, and market-review report notifications.",
    },
    "alert": {
        "env_key": "NOTIFICATION_ALERT_CHANNELS",
        "config_attr": "notification_alert_channels",
        "description": "Routes event-driven alert notifications.",
    },
    "system_error": {
        "env_key": "NOTIFICATION_SYSTEM_ERROR_CHANNELS",
        "config_attr": "notification_system_error_channels",
        "description": "Routes future system error notifications.",
    },
}


def parse_notification_route_channels(raw_value: object) -> List[str]:
    """Parse comma-separated route channel strings without dropping invalid tokens."""
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        items: Iterable[object] = raw_value.split(",")
    elif isinstance(raw_value, (list, tuple, set)):
        items = raw_value
    else:
        items = [raw_value]

    channels: List[str] = []
    for item in items:
        token = str(item).strip().lower()
        if token:
            channels.append(token)
    return channels


def split_notification_route_channels(channels: Iterable[object]) -> Tuple[List[str], List[str]]:
    """Return unique valid and invalid route channels while preserving input order."""
    valid: List[str] = []
    invalid: List[str] = []
    seen_valid = set()
    seen_invalid = set()

    for channel in parse_notification_route_channels(channels):
        if channel in ROUTABLE_NOTIFICATION_CHANNEL_SET:
            if channel not in seen_valid:
                valid.append(channel)
                seen_valid.add(channel)
        elif channel not in seen_invalid:
            invalid.append(channel)
            seen_invalid.add(channel)
    return valid, invalid


def get_notification_route_config(route_type: Optional[str]) -> Optional[Dict[str, str]]:
    """Return route metadata for a normalized route type, or None for unknown routes."""
    if route_type is None:
        return None
    return NOTIFICATION_ROUTE_CONFIGS.get(str(route_type).strip().lower())
