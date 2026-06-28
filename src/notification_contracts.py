# -*- coding: utf-8 -*-
"""Shared notification configuration contracts.

This module intentionally stays lightweight: no sender imports, no SDK imports,
and no NotificationService imports. It is safe for config, diagnostics, and
runtime channel detection to share.
"""

from __future__ import annotations

from typing import Any, Mapping, Tuple


FEISHU_WEBHOOK_ENV_GROUP: Tuple[str, ...] = ("FEISHU_WEBHOOK_URL",)
FEISHU_APP_BOT_ENV_GROUP: Tuple[str, ...] = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_CHAT_ID",
)
FEISHU_STATIC_ENV_GROUPS: Tuple[Tuple[str, ...], ...] = (
    FEISHU_WEBHOOK_ENV_GROUP,
    FEISHU_APP_BOT_ENV_GROUP,
)

_FEISHU_WEBHOOK_CONFIG_GROUP: Tuple[str, ...] = ("feishu_webhook_url",)
_FEISHU_APP_BOT_CONFIG_GROUP: Tuple[str, ...] = (
    "feishu_app_id",
    "feishu_app_secret",
    "feishu_chat_id",
)
_FEISHU_STATIC_CONFIG_GROUPS: Tuple[Tuple[str, ...], ...] = (
    _FEISHU_WEBHOOK_CONFIG_GROUP,
    _FEISHU_APP_BOT_CONFIG_GROUP,
)


def _has_env_group(effective_map: Mapping[str, Any], group: Tuple[str, ...]) -> bool:
    return all(str(effective_map.get(key) or "").strip() for key in group)


def is_feishu_app_bot_env_configured(effective_map: Mapping[str, Any]) -> bool:
    """Return whether Feishu App Bot active notification is configured."""
    return _has_env_group(effective_map, FEISHU_APP_BOT_ENV_GROUP)


def is_feishu_static_env_configured(effective_map: Mapping[str, Any]) -> bool:
    """Return whether any static Feishu notification route is configured."""
    return any(_has_env_group(effective_map, group) for group in FEISHU_STATIC_ENV_GROUPS)


def _has_config_group(config: Any, group: Tuple[str, ...]) -> bool:
    return all(str(getattr(config, attr, None) or "").strip() for attr in group)


def is_feishu_app_bot_configured(config: Any) -> bool:
    """Return whether a Config-like object has the App Bot notification triad."""
    return _has_config_group(config, _FEISHU_APP_BOT_CONFIG_GROUP)


def is_feishu_static_configured(config: Any) -> bool:
    """Return whether a Config-like object has any static Feishu route."""
    return any(_has_config_group(config, group) for group in _FEISHU_STATIC_CONFIG_GROUPS)
