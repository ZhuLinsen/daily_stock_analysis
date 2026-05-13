# -*- coding: utf-8 -*-
"""Tests for notification route channel parsing."""

from src.notification_routing import ROUTABLE_NOTIFICATION_CHANNELS, split_notification_route_channels


def test_ntfy_is_a_routable_notification_channel() -> None:
    valid, invalid = split_notification_route_channels(["wechat", "ntfy", "not-a-channel"])

    assert "ntfy" in ROUTABLE_NOTIFICATION_CHANNELS
    assert valid == ["wechat", "ntfy"]
    assert invalid == ["not-a-channel"]
