# -*- coding: utf-8 -*-
"""Parse an IBKR Flex statement into normalized ledger records.

Reads stock executions (Trades) and deposits/withdrawals (CashTransactions)
into the shapes consumed by :class:`PortfolioService`. Currency conversions
(FX), dividends, withholding tax, fees, corporate actions, and holdings on
unsupported exchanges are reported as skipped rather than guessed.
"""

from __future__ import annotations

import logging
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, List, Optional, Tuple

from src.brokers.ibkr.flex import IbkrPortfolioError

logger = logging.getLogger(__name__)

# IBKR ``listingExchange`` values mapped to ledger markets. Everything else is
# reported as skipped (e.g. BM / SBF / LSE / IBIS).
_EXCHANGE_MARKET = {
    "NASDAQ": "us",
    "NYSE": "us",
    "ARCA": "us",
    "AMEX": "us",
    "BATS": "us",
    "SEHK": "hk",
    "TSEJ": "jp",
}

# Cash transaction types imported into the ledger. Everything else (dividends,
# withholding tax, other fees) is skipped.
_CASH_TYPES_IMPORTED = frozenset({"Deposits/Withdrawals"})

_DATE_PATTERN = re.compile(r"^(\d{8})")


@dataclass(frozen=True)
class TradeRecord:
    symbol: str
    market: str
    currency: str
    trade_date: date
    side: str
    quantity: float
    price: float
    fee: float
    tax: float
    trade_uid: str


@dataclass(frozen=True)
class CashRecord:
    event_date: date
    direction: str
    amount: float
    currency: str
    source_uid: str
    note: Optional[str]


@dataclass
class StatementParseResult:
    trades: List[TradeRecord] = field(default_factory=list)
    cash_events: List[CashRecord] = field(default_factory=list)
    skipped_trades: List[str] = field(default_factory=list)
    skipped_cash: List[str] = field(default_factory=list)
    skipped_corporate_actions: List[str] = field(default_factory=list)


def _parse_flex_date(raw: Optional[str]) -> Optional[date]:
    """Parse IBKR's ``yyyymmdd`` or ``yyyymmdd;HHMMSS`` into a date."""
    if not raw:
        return None
    match = _DATE_PATTERN.match(raw.strip())
    if not match:
        return None
    text = match.group(1)
    try:
        return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _canonical_symbol(symbol: str, market: str) -> Optional[str]:
    """Normalize an IBKR symbol to the ledger/analysis canonical form."""
    code = (symbol or "").strip().upper()
    if not code:
        return None
    if market == "us":
        return code.replace(" ", ".")  # IBKR class shares: "BRK B" -> "BRK.B"
    if market == "hk":
        return f"HK{code.zfill(5)}" if code.isdigit() and len(code) <= 5 else None
    if market == "jp":
        return f"{code}.T" if code.isdigit() and len(code) in (4, 5) else None
    return None


def _flex_statements(xml_bytes: bytes) -> Iterable[ET.Element]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        raise IbkrPortfolioError("IBKR Flex 报表 XML 无法解析") from None
    if root.tag != "FlexQueryResponse":
        raise IbkrPortfolioError(f"IBKR Flex 报表根节点异常: {root.tag}")
    statements = root.findall("./FlexStatements/FlexStatement")
    if not statements:
        raise IbkrPortfolioError("IBKR Flex 报表中没有 FlexStatement")
    yield from statements


def _iter_trades(statement: ET.Element) -> Iterable[ET.Element]:
    section = statement.find("Trades")
    if section is None:
        return
    for row in section.findall("Trade"):
        if (row.get("assetCategory") or "").strip().upper() != "STK":
            continue
        if (row.get("levelOfDetail") or "").strip().upper() != "EXECUTION":
            continue
        yield row


def _iter_cash(statement: ET.Element) -> Iterable[ET.Element]:
    section = statement.find("CashTransactions")
    if section is None:
        return
    for row in section.findall("CashTransaction"):
        yield row


def _parse_trade(row: ET.Element) -> Tuple[Optional[TradeRecord], Optional[str]]:
    """Return ``(record, skip_reason)``; exactly one is non-None."""
    symbol = (row.get("symbol") or "").strip()
    if not symbol:
        return None, "missing symbol"
    exchange = (row.get("listingExchange") or "").strip().upper()
    market = _EXCHANGE_MARKET.get(exchange)
    if market is None:
        return None, f"{symbol}@{exchange or '?'}"

    canonical = _canonical_symbol(symbol, market)
    if canonical is None:
        return None, f"{symbol}@{exchange}"

    trade_date = _parse_flex_date(row.get("tradeDate"))
    if trade_date is None:
        return None, f"{symbol}:bad date"

    trade_uid = (row.get("tradeID") or "").strip()
    if not trade_uid:
        return None, f"{symbol}:missing tradeID"
    currency = (row.get("currency") or "").strip().upper()
    if not currency:
        return None, f"{symbol}:missing currency"

    try:
        quantity = float(row.get("quantity"))
        price = float(row.get("tradePrice"))
        fee = abs(float(row.get("ibCommission") or 0))
        tax = abs(float(row.get("taxes") or 0))
    except (TypeError, ValueError):
        return None, f"{symbol}:bad numeric field"

    side_raw = (row.get("buySell") or "").strip().upper()
    if side_raw == "BUY":
        side = "buy"
    elif side_raw == "SELL":
        side = "sell"
    elif quantity > 0:
        side = "buy"
    elif quantity < 0:
        side = "sell"
    else:
        return None, f"{symbol}:zero quantity"

    quantity = abs(quantity)
    if quantity <= 0 or price <= 0:
        return None, f"{symbol}:bad quantity/price"

    return (
        TradeRecord(
            symbol=canonical,
            market=market,
            currency=currency,
            trade_date=trade_date,
            side=side,
            quantity=quantity,
            price=price,
            fee=fee,
            tax=tax,
            trade_uid=trade_uid,
        ),
        None,
    )


def _parse_cash(row: ET.Element) -> Tuple[Optional[CashRecord], Optional[str]]:
    """Return ``(record, skip_reason)``; exactly one is non-None."""
    cash_type = (row.get("type") or "").strip()
    if cash_type not in _CASH_TYPES_IMPORTED:
        return None, f"{cash_type or 'unknown type'}"

    event_date = _parse_flex_date(row.get("dateTime") or row.get("reportDate"))
    if event_date is None:
        return None, f"{cash_type}:bad date"
    source_uid = (row.get("transactionID") or "").strip()
    if not source_uid:
        return None, f"{cash_type}:missing transactionID"
    currency = (row.get("currency") or "").strip().upper()
    if not currency:
        return None, f"{cash_type}:missing currency"

    try:
        amount = float(row.get("amount"))
    except (TypeError, ValueError):
        return None, f"{cash_type}:bad amount"

    if not math.isfinite(amount) or amount == 0:
        return None, f"{cash_type}:zero amount"
    direction = "in" if amount > 0 else "out"
    note = (row.get("description") or "ibkr_flex").strip()[:255] or None

    return (
        CashRecord(
            event_date=event_date,
            direction=direction,
            amount=abs(amount),
            currency=currency,
            source_uid=source_uid,
            note=note,
        ),
        None,
    )


def parse_statement(xml_bytes: bytes) -> StatementParseResult:
    """Parse all FlexStatement sections into normalized ledger records."""
    result = StatementParseResult()
    for statement in _flex_statements(xml_bytes):
        for row in _iter_trades(statement):
            record, reason = _parse_trade(row)
            if record is not None:
                result.trades.append(record)
            else:
                result.skipped_trades.append(reason)

        for row in _iter_cash(statement):
            record, reason = _parse_cash(row)
            if record is not None:
                result.cash_events.append(record)
            else:
                result.skipped_cash.append(reason)

        ca_section = statement.find("CorporateActions")
        if ca_section is not None:
            for ca in ca_section.findall("CorporateAction"):
                symbol = (ca.get("symbol") or "").strip()
                description = (ca.get("actionDescription") or "").strip()
                result.skipped_corporate_actions.append(
                    f"{symbol or '?'}: {description or ca.get('type') or '?'}"
                )

    return result
