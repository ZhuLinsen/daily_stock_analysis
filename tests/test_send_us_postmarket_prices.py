from datetime import date, datetime, timezone

from scripts.send_us_postmarket_prices import (
    AfterHoursQuote,
    QuoteUnavailable,
    US_TIMEZONE,
    build_report,
    parse_after_hours_quote,
    resolve_report_session_date,
)


def test_parse_after_hours_quote_uses_postmarket_price() -> None:
    result = parse_after_hours_quote(
        "AAPL",
        {
            "postMarketPrice": 217.45,
            "regularMarketPrice": 215.00,
            "postMarketChangePercent": 1.1395,
            "postMarketTime": 1784851200,
        },
    )

    assert result == AfterHoursQuote(
        symbol="AAPL",
        price=217.45,
        regular_close=215.00,
        change_percent=1.1395,
        quoted_at=datetime.fromtimestamp(1784851200, tz=timezone.utc),
    )


def test_parse_after_hours_quote_calculates_missing_change_percent() -> None:
    result = parse_after_hours_quote(
        "TSLA",
        {"postMarketPrice": 325.0, "regularMarketPrice": 320.0},
    )

    assert result == AfterHoursQuote(
        symbol="TSLA",
        price=325.0,
        regular_close=320.0,
        change_percent=1.5625,
        quoted_at=None,
    )


def test_missing_postmarket_price_is_not_replaced_by_regular_close() -> None:
    result = parse_after_hours_quote(
        "BRK-B",
        {"regularMarketPrice": 502.0},
    )

    assert result == QuoteUnavailable(symbol="BRK-B", regular_close=502.0)


def test_report_labels_true_after_hours_prices_and_missing_quotes() -> None:
    report = build_report(
        date(2026, 7, 23),
        [
            AfterHoursQuote(
                symbol="AAPL",
                price=217.45,
                regular_close=215.0,
                change_percent=1.1395,
                quoted_at=None,
            ),
            QuoteUnavailable(symbol="BRK-B", regular_close=502.0),
        ],
    )

    assert "美股盘后价（2026-07-23）" in report
    assert "| AAPL | 217.45 | 215.00 | +1.14% |" in report
    assert "| BRK-B | 无盘后成交 | 502.00 | - |" in report


def test_premarket_rerun_uses_previous_completed_us_session() -> None:
    us_premarket = datetime(2026, 7, 24, 4, 55, tzinfo=US_TIMEZONE)

    assert resolve_report_session_date(us_premarket) == date(2026, 7, 23)


def test_after_hours_run_preserves_current_date_for_holiday_skip() -> None:
    us_after_hours = datetime(2026, 7, 3, 21, 0, tzinfo=US_TIMEZONE)

    assert resolve_report_session_date(us_after_hours) == date(2026, 7, 3)
