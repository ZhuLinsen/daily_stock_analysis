from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Final, Mapping, Sequence, TypedDict, assert_never
from zoneinfo import ZoneInfo

from data_provider.us_index_mapping import is_us_stock_code
from src.core.trading_calendar import is_market_open
from src.notification import NotificationService
from src.services.stock_list_parser import split_stock_list

logger = logging.getLogger(__name__)

US_TIMEZONE: Final = ZoneInfo("America/New_York")
AFTER_HOURS_END: Final = time(20, 0)


class QuoteFields(TypedDict, total=False):
    postMarketPrice: str | int | float | None
    regularMarketPrice: str | int | float | None
    postMarketChangePercent: str | int | float | None
    postMarketTime: str | int | float | None


@dataclass(frozen=True, slots=True)
class AfterHoursQuote:
    symbol: str
    price: float
    regular_close: float | None
    change_percent: float | None
    quoted_at: datetime | None


class UnavailableReason(StrEnum):
    NO_AFTER_HOURS_TRADE = "no_after_hours_trade"
    FETCH_FAILED = "fetch_failed"


@dataclass(frozen=True, slots=True)
class QuoteUnavailable:
    symbol: str
    regular_close: float | None
    reason: UnavailableReason = UnavailableReason.NO_AFTER_HOURS_TRADE


QuoteResult = AfterHoursQuote | QuoteUnavailable


def _finite_float(value: str | int | float | None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return parsed


def parse_after_hours_quote(symbol: str, fields: QuoteFields) -> QuoteResult:
    price = _finite_float(fields.get("postMarketPrice"))
    regular_close = _finite_float(fields.get("regularMarketPrice"))
    if price is None or price <= 0:
        return QuoteUnavailable(symbol=symbol, regular_close=regular_close)

    change_percent = _finite_float(fields.get("postMarketChangePercent"))
    if change_percent is None and regular_close is not None and regular_close > 0:
        change_percent = (price - regular_close) / regular_close * 100

    timestamp = _finite_float(fields.get("postMarketTime"))
    quoted_at = (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        if timestamp is not None and timestamp > 0
        else None
    )
    return AfterHoursQuote(
        symbol=symbol,
        price=price,
        regular_close=regular_close,
        change_percent=change_percent,
        quoted_at=quoted_at,
    )


def resolve_report_session_date(us_now: datetime) -> date:
    localized_now = us_now.astimezone(US_TIMEZONE)
    candidate = localized_now.date()
    if localized_now.time() >= AFTER_HOURS_END:
        return candidate

    candidate -= timedelta(days=1)
    while not is_market_open("us", candidate):
        candidate -= timedelta(days=1)
    return candidate


def _format_price(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "-"


def _format_change(value: float | None) -> str:
    return f"{value:+.2f}%" if value is not None else "-"


def build_report(session_date: date, quotes: Sequence[QuoteResult]) -> str:
    lines = [
        f"# 美股盘后价（{session_date.isoformat()}）",
        "",
        "> 盘后价取自美股延长交易时段；常规收盘价仅作对照，不会替代缺失的盘后价。",
        "",
        "| 代码 | 盘后价（USD） | 常规收盘价（USD） | 盘后涨跌 |",
        "|---|---:|---:|---:|",
    ]
    for quote in quotes:
        match quote:
            case AfterHoursQuote():
                lines.append(
                    f"| {quote.symbol} | {_format_price(quote.price)} | "
                    f"{_format_price(quote.regular_close)} | "
                    f"{_format_change(quote.change_percent)} |"
                )
            case QuoteUnavailable(reason=UnavailableReason.NO_AFTER_HOURS_TRADE):
                lines.append(
                    f"| {quote.symbol} | 无盘后成交 | "
                    f"{_format_price(quote.regular_close)} | - |"
                )
            case QuoteUnavailable(reason=UnavailableReason.FETCH_FAILED):
                lines.append(
                    f"| {quote.symbol} | 获取失败 | "
                    f"{_format_price(quote.regular_close)} | - |"
                )
            case unreachable:
                assert_never(unreachable)
    return "\n".join(lines)


def _quote_field(value: object) -> str | int | float | None:
    if value is None or isinstance(value, (str, int, float)):
        return value
    return None


def _quote_fields(raw_info: Mapping[str, object]) -> QuoteFields:
    return {
        "postMarketPrice": _quote_field(raw_info.get("postMarketPrice")),
        "regularMarketPrice": _quote_field(raw_info.get("regularMarketPrice")),
        "postMarketChangePercent": _quote_field(
            raw_info.get("postMarketChangePercent")
        ),
        "postMarketTime": _quote_field(raw_info.get("postMarketTime")),
    }


def fetch_after_hours_quotes(symbols: Sequence[str]) -> list[QuoteResult]:
    import yfinance as yf

    quotes: list[QuoteResult] = []
    for symbol in symbols:
        try:
            raw_info = yf.Ticker(symbol).info or {}
            quotes.append(parse_after_hours_quote(symbol, _quote_fields(raw_info)))
        except Exception:  # noqa: BROAD_EXCEPT_OK
            logger.exception("Failed to fetch US after-hours quote for %s", symbol)
            quotes.append(
                QuoteUnavailable(
                    symbol=symbol,
                    regular_close=None,
                    reason=UnavailableReason.FETCH_FAILED,
                )
            )
    return quotes


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    us_now = datetime.now(tz=US_TIMEZONE)
    session_date = resolve_report_session_date(us_now)
    if not is_market_open("us", session_date):
        logger.info("US market is closed on %s; skipping after-hours email", session_date)
        return 0

    symbols = [
        symbol
        for symbol in split_stock_list(os.getenv("STOCK_LIST", ""))
        if is_us_stock_code(symbol)
    ]
    if not symbols:
        logger.info("No US symbols in STOCK_LIST; skipping after-hours email")
        return 0

    report = build_report(session_date, fetch_after_hours_quotes(symbols))
    dispatch = NotificationService().send_with_results(
        report,
        email_stock_codes=symbols,
        route_type="report",
        dedup_key=f"us-postmarket-prices:{session_date.isoformat()}",
    )
    if dispatch.success:
        logger.info("US after-hours email sent for %s", session_date)
        return 0
    logger.error("US after-hours email failed: %s", dispatch.message or dispatch.status)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
