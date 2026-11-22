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

from data_provider.us_index_mapping import is_us_stock_code
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

# Prefix written to the ledger `note` for every imported IBKR row, so a bad
# import can be removed with `note LIKE 'ibkr_flex%'`.
NOTE_MARKER = "ibkr_flex"

# IBKR lets the Flex template choose the date format; both compact and
# hyphenated forms appear in real reports.
_DATE_PATTERN = re.compile(r"^(\d{8}|\d{4}-\d{2}-\d{2})")


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
    # IBKR ``openCloseIndicator``: "O" opens a position, "C" closes one, or "".
    # Kept because buy/sell direction alone cannot express a short: a BUY marked
    # "C" is a short cover, which a long-only ledger must not book as a long.
    open_close: str = ""


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
    """Parse IBKR's date formats into a date.

    Accepts ``yyyymmdd``, ``yyyy-MM-dd`` and the ``...;HHMMSS`` timestamp form;
    a template that renders dates differently would otherwise drop every row.
    """
    if not raw:
        return None
    match = _DATE_PATTERN.match(raw.strip())
    if not match:
        return None
    text = match.group(1)
    try:
        if "-" in text:
            return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
        return date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _canonical_symbol(symbol: str, market: str) -> Optional[str]:
    """Normalize an IBKR symbol to the ledger/analysis canonical form."""
    code = (symbol or "").strip().upper()
    if not code:
        return None
    if market == "us":
        if " " in code:
            return None  # IBKR class share (e.g. "BRK B") — not supported by the ledger
        # Same validation as the analysis list, so the ledger and the analysis
        # path cannot accept different symbol sets for the same statement.
        return code if is_us_stock_code(code) else None
    if market == "hk":
        return f"HK{code.zfill(5)}" if code.isdigit() and len(code) <= 5 else None
    if market == "jp":
        if len(code) not in (4, 5):
            return None
        if code.isdigit() or (code.isalnum() and any(ch.isdigit() for ch in code)):
            return f"{code}.T"
        return None
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
        asset_category = row.get("assetCategory")
        if asset_category is None:
            # Optional Flex field: absent means the query did not select Asset
            # Class, not "not a stock". Without this the whole Trades section
            # would import zero rows and still look like a clean run.
            raise IbkrPortfolioError(
                "IBKR Trades 缺少 assetCategory 字段，请在 Flex Query 中勾选 Asset Class"
            )
        if str(asset_category).strip().upper() != "STK":
            continue
        if (row.get("levelOfDetail") or "").strip().upper() != "EXECUTION":
            continue
        # Row-level account id proves a merged report is not mixing accounts.
        _require_flex_field(row, "accountId", "Trades")
        yield row


def _require_flex_field(row: ET.Element, attribute: str, section: str) -> str:
    """Return an attribute's value, or fail when the template omits it.

    Freely customisable Flex fields are absent (not empty) when the template
    does not select them. Treating "absent" as "not a stock" / "unknown
    exchange" silently drops real data, so the contract is fail-closed.
    """
    value = row.get(attribute)
    if value is None:
        raise IbkrPortfolioError(
            f"IBKR {section} 缺少 {attribute} 字段，请在 Flex Query 中勾选 {attribute}"
        )
    return value


def _iter_cash(statement: ET.Element) -> Iterable[ET.Element]:
    section = statement.find("CashTransactions")
    if section is None:
        return
    for row in section.findall("CashTransaction"):
        # The row-level account id is what proves a merged report is not mixing
        # several IBKR accounts into one local ledger.
        _require_flex_field(row, "accountId", "CashTransactions")
        yield row


def _parse_trade(row: ET.Element) -> Tuple[Optional[TradeRecord], Optional[str]]:
    """Return ``(record, skip_reason)``; exactly one is non-None."""
    symbol = (row.get("symbol") or "").strip()
    if not symbol:
        return None, "missing symbol"
    exchange = _require_flex_field(row, "listingExchange", "Trades").strip().upper()
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

    # Required, not optional: without it a short cover (BUY/C) is
    # indistinguishable from a long open (BUY/O) and would be booked as a long.
    # An empty or unexpected value is treated the same as an absent field.
    open_close = _require_flex_field(row, "openCloseIndicator", "Trades").strip().upper()
    if open_close not in ("O", "C"):
        raise IbkrPortfolioError(
            f"IBKR Trades 的 openCloseIndicator 值无效（{open_close!r}），须为 O 或 C；"
            "请在 Flex Query 中勾选 Open/Close Indicator"
        )

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
            open_close=open_close,
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
    # Always carry the marker so the documented cleanup (`note LIKE 'ibkr_flex%'`)
    # also matches cash rows that keep the broker description.
    description = (row.get("description") or "").strip()
    note = f"{NOTE_MARKER}: {description}"[:255] if description else NOTE_MARKER
    note = note or None

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
    account_ids = set()
    saw_trades_section = False
    saw_cash_section = False
    saw_trade_rows = False
    saw_execution_rows = False
    for statement in _flex_statements(xml_bytes):
        account_id = (statement.get("accountId") or "").strip()
        if account_id:
            account_ids.add(account_id)

        trades_section = statement.find("Trades")
        if trades_section is not None:
            saw_trades_section = True
            for row in trades_section.findall("Trade"):
                saw_trade_rows = True
                if (row.get("levelOfDetail") or "").strip().upper() == "EXECUTION":
                    saw_execution_rows = True
        if statement.find("CashTransactions") is not None:
            saw_cash_section = True

        for row in _iter_trades(statement):
            row_account_id = (row.get("accountId") or "").strip()
            if row_account_id:
                account_ids.add(row_account_id)
            record, reason = _parse_trade(row)
            if record is not None:
                result.trades.append(record)
            else:
                result.skipped_trades.append(reason)

        for row in _iter_cash(statement):
            row_account_id = (row.get("accountId") or "").strip()
            if row_account_id:
                account_ids.add(row_account_id)
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

    if len(account_ids) > 1:
        raise IbkrPortfolioError(
            f"IBKR Flex 报表包含多个账户（{', '.join(sorted(account_ids))}）；"
            "请为每个账户配置单独的 Flex Query"
        )

    if not saw_trades_section or not saw_cash_section:
        missing = []
        if not saw_trades_section:
            missing.append("Trades")
        if not saw_cash_section:
            missing.append("CashTransactions")
        raise IbkrPortfolioError(
            f"IBKR Flex 报表缺少 {' / '.join(missing)} 分区；"
            "账本同步需要同时包含 Trades 与 CashTransactions 的完整 Flex Query（而非仅 Open Positions）"
        )

    # A Trades section configured with the Orders detail level produces rows but
    # no EXECUTION rows; every stock trade would vanish without any error.
    if saw_trade_rows and not saw_execution_rows:
        raise IbkrPortfolioError(
            "IBKR Flex 报表的 Trades 分区没有 Executions 明细（可能只选了 Orders）；"
            "请在 Flex Query 的 Trades 分区选择 Executions 明细级别"
        )

    return result
