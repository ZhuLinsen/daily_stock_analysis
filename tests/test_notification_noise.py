from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.notification_noise import (
    evaluate_notification_noise,
    record_notification_noise,
    release_notification_noise,
    reset_notification_noise_state,
)


def _config(**overrides):
    defaults = {
        "notification_dedup_ttl_seconds": 0,
        "notification_cooldown_seconds": 0,
        "notification_quiet_hours": "",
        "notification_timezone": "",
        "notification_min_severity": "",
        "notification_daily_digest_enabled": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def setup_function():
    reset_notification_noise_state()


def test_dedup_ttl_suppresses_until_expiry_with_explicit_key():
    config = _config(notification_dedup_ttl_seconds=60)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    first = evaluate_notification_noise(
        config,
        content="content at 12:00",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=now,
    )
    assert first.should_send
    record_notification_noise(first, now=now)

    duplicate = evaluate_notification_noise(
        config,
        content="content at 12:01",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=now + timedelta(seconds=10),
    )
    assert not duplicate.should_send
    assert duplicate.reason_code == "dedup"

    expired = evaluate_notification_noise(
        config,
        content="content at 12:02",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=now + timedelta(seconds=61),
    )
    assert expired.should_send


def test_cooldown_keys_are_independent():
    config = _config(notification_cooldown_seconds=60)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    first = evaluate_notification_noise(
        config,
        content="one",
        route_type="report",
        cooldown_key="report:single:600519:simple",
        now=now,
    )
    assert first.should_send
    record_notification_noise(first, now=now)

    same_key = evaluate_notification_noise(
        config,
        content="two",
        route_type="report",
        cooldown_key="report:single:600519:simple",
        now=now + timedelta(seconds=1),
    )
    other_key = evaluate_notification_noise(
        config,
        content="three",
        route_type="report",
        cooldown_key="report:single:000001:simple",
        now=now + timedelta(seconds=1),
    )

    assert not same_key.should_send
    assert same_key.reason_code == "cooldown"
    assert other_key.should_send


def test_inflight_reservation_suppresses_same_key_until_released():
    config = _config(notification_dedup_ttl_seconds=60)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    first = evaluate_notification_noise(
        config,
        content="first",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=now,
    )
    assert first.should_send

    duplicate = evaluate_notification_noise(
        config,
        content="second",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=now + timedelta(seconds=1),
    )
    assert not duplicate.should_send
    assert duplicate.reason_code == "dedup_inflight"

    release_notification_noise(first)
    retried = evaluate_notification_noise(
        config,
        content="retry",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=now + timedelta(seconds=2),
    )
    assert retried.should_send


def test_cooldown_inflight_reservation_suppresses_same_key_until_released():
    config = _config(notification_cooldown_seconds=60)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    first = evaluate_notification_noise(
        config,
        content="first",
        route_type="report",
        cooldown_key="report:single:600519:simple",
        now=now,
    )
    assert first.should_send

    duplicate = evaluate_notification_noise(
        config,
        content="second",
        route_type="report",
        cooldown_key="report:single:600519:simple",
        now=now + timedelta(seconds=1),
    )
    assert not duplicate.should_send
    assert duplicate.reason_code == "cooldown_inflight"

    release_notification_noise(first)
    retried = evaluate_notification_noise(
        config,
        content="retry",
        route_type="report",
        cooldown_key="report:single:600519:simple",
        now=now + timedelta(seconds=2),
    )
    assert retried.should_send


def test_record_uses_success_time_for_expiry_not_evaluate_time():
    config = _config(notification_dedup_ttl_seconds=60)
    evaluated_at = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    success_at = evaluated_at + timedelta(minutes=5)

    first = evaluate_notification_noise(
        config,
        content="content",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=evaluated_at,
    )
    assert first.should_send
    record_notification_noise(first, now=success_at)

    duplicate = evaluate_notification_noise(
        config,
        content="content",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=success_at + timedelta(seconds=59),
    )
    assert not duplicate.should_send
    assert duplicate.reason_code == "dedup"

    expired = evaluate_notification_noise(
        config,
        content="content",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=success_at + timedelta(seconds=61),
    )
    assert expired.should_send


def test_stale_release_does_not_clear_newer_inflight_reservation():
    config = _config(notification_dedup_ttl_seconds=60)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    first = evaluate_notification_noise(
        config,
        content="content",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=now,
    )
    assert first.should_send

    newer = evaluate_notification_noise(
        config,
        content="content",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=now + timedelta(seconds=301),
    )
    assert newer.should_send

    release_notification_noise(first)
    duplicate = evaluate_notification_noise(
        config,
        content="content",
        route_type="report",
        dedup_key="report:aggregate:simple:600519",
        now=now + timedelta(seconds=302),
    )
    assert not duplicate.should_send
    assert duplicate.reason_code == "dedup_inflight"


def test_quiet_hours_same_day_and_overnight():
    same_day = _config(notification_quiet_hours="09:00-17:00", notification_timezone="UTC")
    assert not evaluate_notification_noise(
        same_day,
        content="quiet",
        route_type="report",
        now=datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc),
    ).should_send
    assert evaluate_notification_noise(
        same_day,
        content="loud",
        route_type="report",
        now=datetime(2026, 5, 10, 18, 0, tzinfo=timezone.utc),
    ).should_send

    overnight = _config(notification_quiet_hours="22:00-06:00", notification_timezone="UTC")
    assert not evaluate_notification_noise(
        overnight,
        content="late",
        route_type="report",
        now=datetime(2026, 5, 10, 23, 0, tzinfo=timezone.utc),
    ).should_send
    assert not evaluate_notification_noise(
        overnight,
        content="early",
        route_type="report",
        now=datetime(2026, 5, 11, 5, 30, tzinfo=timezone.utc),
    ).should_send
    assert evaluate_notification_noise(
        overnight,
        content="day",
        route_type="report",
        now=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
    ).should_send


def test_invalid_timezone_fails_open():
    config = _config(
        notification_quiet_hours="00:00-23:59",
        notification_timezone="Mars/Olympus",
    )

    decision = evaluate_notification_noise(
        config,
        content="content",
        route_type="report",
        now=datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc),
    )

    assert decision.should_send
    assert decision.reason_code == "noise_check_failed_open"


def test_min_severity_filters_lower_severity_only():
    config = _config(notification_min_severity="warning")

    report = evaluate_notification_noise(config, content="report", route_type="report")
    alert = evaluate_notification_noise(config, content="alert", route_type="alert")
    system_error = evaluate_notification_noise(config, content="error", route_type="system_error")

    assert not report.should_send
    assert report.reason_code == "min_severity"
    assert alert.should_send
    assert system_error.should_send


def test_daily_digest_reserved_flag_does_not_change_runtime_decision():
    config = _config(notification_daily_digest_enabled=True)

    decision = evaluate_notification_noise(config, content="content", route_type="report")

    assert decision.should_send
