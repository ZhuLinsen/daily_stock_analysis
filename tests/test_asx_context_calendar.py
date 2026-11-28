"""ASX context and real XASX-calendar regression coverage (no network calls)."""

from datetime import date, datetime, timedelta, timezone

import pytest

from src import market_context
from src.core import trading_calendar as tc


@pytest.mark.parametrize("lang", ["zh", "en", "ko"])
def test_au_prompt_uses_local_market_and_metadata_guidance(monkeypatch, lang):
    # Isolate prompt coverage from the independently maintained suffix registry.
    monkeypatch.setattr(market_context, "get_suffix_market", lambda code: "au")
    role = market_context.get_market_role("A2M.AX", lang)
    guidance = market_context.get_market_guidelines("A2M.AX", lang)
    assert "ASX" in role
    assert "ASX" in guidance
    assert "AUD" in guidance
    assert "Australia/Sydney" in guidance
    assert "ETF" in guidance
    if lang in {"en", "ko"}:
        assert "metadata" in guidance
        assert "do not apply" in guidance
        assert "US" in guidance and "China" in guidance
        assert "unknown" in guidance
    else:
        assert "元数据" in guidance
        assert "不要套用" in guidance
        assert "美股" in guidance and "A 股" in guidance
        assert "未知" in guidance


@pytest.mark.parametrize("symbol", ["BHP.AX", "A2M.AX", "VAS.AX", "3DP.AX", " hks.ax "])
def test_explicit_au_suffix_identity_is_consistent(symbol):
    assert market_context.detect_market(symbol) == "au"
    assert tc.get_market_for_stock(symbol) == "au"
    assert "ASX" in market_context.get_market_role(symbol, "en")


@pytest.mark.parametrize("symbol,market", [
    ("600519", "cn"), ("00700.HK", "hk"), ("AAPL", "us"),
    ("BRK.B", "us"), ("NXT", "us"), ("7203.T", "jp"),
    ("005930.KS", "kr"), ("247540.KQ", "kr"),
    ("2330.TW", "tw"), ("8069.TWO", "tw"),
])
def test_existing_market_detection_is_preserved(symbol, market):
    assert market_context.detect_market(symbol) == market
    assert tc.get_market_for_stock(symbol) == market


def test_au_calendar_registration_and_regions():
    assert tc.MARKET_EXCHANGE["au"] == "XASX"
    assert tc.MARKET_TIMEZONE["au"] == "Australia/Sydney"
    assert tc.compute_effective_region("au", {"au"}) == "au"
    assert tc.compute_effective_region("au", {"us"}) == ""
    assert tc.compute_effective_region("au,us,cn", {"au", "us"}) == "us,au"
    assert tc.compute_effective_region("both", {"au"}) == "au"


@pytest.fixture
def asx_calendar():
    # These tests must actually exercise the installed calendar, not silently skip.
    import exchange_calendars

    return exchange_calendars.get_calendar("XASX")


@pytest.mark.parametrize("day,expected", [
    (date(2026, 1, 23), True),
    (date(2026, 1, 24), False),
    (date(2026, 1, 26), False),  # Australia Day, not a US holiday
    (date(2026, 4, 3), False),
    (date(2026, 4, 6), False),
    (date(2026, 6, 8), False),
    (date(2026, 12, 25), False),
    (date(2026, 12, 28), False),
])
def test_au_trading_days_use_real_calendar(asx_calendar, day, expected):
    assert bool(asx_calendar.is_session(day)) is expected
    assert bool(tc.is_market_open("au", day)) is expected


def test_au_session_range_and_next_date(asx_calendar):
    days = tc.get_trading_dates("au", date(2026, 1, 23), date(2026, 1, 27))
    assert days is not None
    assert list(days.date) == [date(2026, 1, 23), date(2026, 1, 27)]
    assert tc.get_next_trading_date("au", date(2026, 1, 23)) == date(2026, 1, 27)


@pytest.mark.parametrize("instant,local_day,hour,offset", [
    (datetime(2026, 1, 22, 23, tzinfo=timezone.utc), date(2026, 1, 23), 10, 11),
    (datetime(2026, 7, 5, 23, tzinfo=timezone.utc), date(2026, 7, 6), 9, 10),
])
def test_au_local_date_and_dst(instant, local_day, hour, offset):
    local = tc.get_market_now("au", instant)
    assert local.date() == local_day
    assert local.hour == hour
    assert local.utcoffset() == timedelta(hours=offset)


@pytest.mark.parametrize("session_day", [date(2026, 1, 23), date(2026, 12, 24)])
def test_au_regular_session_phases_follow_calendar(asx_calendar, session_day):
    opening = asx_calendar.session_open(session_day).to_pydatetime()
    closing = asx_calendar.session_close(session_day).to_pydatetime()
    assert tc.infer_market_phase("au", opening - timedelta(seconds=1)) == tc.MarketPhase.PREMARKET
    assert tc.infer_market_phase("au", opening) == tc.MarketPhase.INTRADAY
    assert tc.infer_market_phase("au", closing - timedelta(seconds=1)) == tc.MarketPhase.INTRADAY
    assert tc.infer_market_phase("au", closing) == tc.MarketPhase.POSTMARKET
    context = tc.build_market_phase_context(market="au", current_time=closing - timedelta(minutes=1))
    assert context.minutes_to_close == 1
    assert context.is_partial_bar is True
    assert context.is_market_open_now is True
    assert "au_regular_session_approximation" in context.warnings


@pytest.mark.parametrize("clock,expected", [
    ("2026-01-23T09:00:00", date(2026, 1, 22)),
    ("2026-01-23T16:00:00", date(2026, 1, 22)),
    ("2026-01-23T16:10:59", date(2026, 1, 22)),
    ("2026-01-23T16:11:00", date(2026, 1, 23)),
    ("2026-01-26T18:00:00", date(2026, 1, 23)),
    # An early close is not evidence that an auction-inclusive bar is ready.
    ("2026-12-24T14:10:00", date(2026, 12, 23)),
    ("2026-12-24T16:11:00", date(2026, 12, 24)),
])
def test_au_effective_date_does_not_claim_auction_finality_early(asx_calendar, clock, expected):
    assert tc.get_effective_trading_date("au", datetime.fromisoformat(clock)) == expected


def test_au_post_continuous_session_still_has_partial_bar(asx_calendar):
    context = tc.build_market_phase_context(market="au", current_time=datetime(2026, 1, 23, 16, 5))
    assert context.phase == tc.MarketPhase.POSTMARKET
    assert context.is_partial_bar is True
    assert context.effective_daily_bar_date == date(2026, 1, 22)
    assert "au_regular_session_approximation" in context.warnings
    assert "au_daily_bar_finality_unverified" in context.warnings


def test_au_historical_postmarket_without_time_is_unproven(asx_calendar):
    assert tc.resolve_historical_daily_bar_date("au", date(2026, 1, 23), "postmarket") is None
    assert tc.resolve_historical_daily_bar_date("au", date(2026, 1, 23), "intraday") == date(2026, 1, 22)
    assert tc.resolve_historical_daily_bar_date("au", date(2026, 1, 26), "non_trading") == date(2026, 1, 23)


def test_au_calendar_unavailable_keeps_existing_failure_contract(monkeypatch):
    monkeypatch.setattr(tc, "_XCALS_AVAILABLE", False)
    assert "au" in tc.get_open_markets_today()
    assert tc.is_market_open("au", date(2026, 1, 26)) is True
    assert tc.get_trading_dates("au", date(2026, 1, 23), date(2026, 1, 27)) is None
    assert tc.get_next_trading_date("au", date(2026, 1, 23)) is None
    assert tc.infer_market_phase("au", datetime(2026, 1, 23, 12)) == tc.MarketPhase.UNKNOWN
    context = tc.build_market_phase_context(market="au", current_time=datetime(2026, 1, 23, 12))
    assert "calendar_unavailable" in context.warnings
    assert "unknown_market" not in context.warnings
