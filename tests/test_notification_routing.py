# -*- coding: utf-8 -*-
"""Tests for notification route channel parsing."""

from src.notification_routing import ROUTABLE_NOTIFICATION_CHANNELS, split_notification_route_channels


def test_ntfy_and_gotify_are_routable_notification_channels() -> None:
    valid, invalid = split_notification_route_channels(["wechat", "ntfy", "gotify", "not-a-channel"])

    assert "ntfy" in ROUTABLE_NOTIFICATION_CHANNELS
    assert "gotify" in ROUTABLE_NOTIFICATION_CHANNELS
    assert valid == ["wechat", "ntfy", "gotify"]
    assert invalid == ["not-a-channel"]
