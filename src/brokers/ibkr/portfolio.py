# -*- coding: utf-8 -*-
"""Read real stock holdings from an IBKR Flex query (Open Positions section)."""

from __future__ import annotations

import logging
import math
import os
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Iterable, List, Optional, Tuple

from data_provider.us_index_mapping import is_us_stock_code
from src.brokers.ibkr.flex import IbkrPortfolioError, download_flex_statement

logger = logging.getLogger(__name__)

# IBKR ``listingExchange`` values mapped to analysis markets. Holdings listed
# elsewhere (e.g. BM, SBF, LSE, IBIS) are logged and skipped.
_US_EXCHANGES = frozenset({"NASDAQ", "NYSE", "ARCA", "AMEX", "BATS"})
_HK_EXCHANGES = frozenset({"SEHK"})
_JP_EXCHANGES = frozenset({"TSEJ"})


def _to_analysis_code(symbol: str, listing_exchange: str) -> Optional[str]:
    """Convert an IBKR stock symbol into the analysis pipeline format."""

    exchange = (listing_exchange or "").strip().upper()
    code = (symbol or "").strip().upper()
    if not code:
        return None
    if exchange in _US_EXCHANGES:
        if " " in code:
            return None  # IBKR class share (e.g. "BRK B") — not supported by the analysis pipeline
        return code if is_us_stock_code(code) else None
    if exchange in _HK_EXCHANGES:
        return f"HK{code.zfill(5)}" if code.isdigit() and len(code) <= 5 else None
    if exchange in _JP_EXCHANGES:
        return f"{code}.T" if code.isdigit() and len(code) in (4, 5) else None
    return None


def _open_position_rows(xml_bytes: bytes) -> Iterable[ET.Element]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        raise IbkrPortfolioError("IBKR Flex 报表 XML 无法解析") from None
    if root.tag != "FlexQueryResponse":
        raise IbkrPortfolioError(f"IBKR Flex 报表根节点异常: {root.tag}")
    statements = root.findall("./FlexStatements/FlexStatement")
    if not statements:
        raise IbkrPortfolioError("IBKR Flex 报表中没有 FlexStatement")
    for statement in statements:
        section = statement.find("OpenPositions")
        if section is None:
            raise IbkrPortfolioError(
                "IBKR Flex 查询未包含 Open Positions 分区，请在 Flex Query 中勾选后重试"
            )
        yield from section.findall("OpenPosition")


def parse_open_position_codes(xml_bytes: bytes) -> Tuple[List[str], List[str]]:
    """Return ``(analysis_codes, skipped_holdings)`` for LONG stock positions.

    Only ``assetCategory=STK`` rows with a positive ``position`` are kept;
    lot-level and summary rows for the same holding are deduplicated. A stock
    row with a missing symbol or non-numeric position fails the whole parse.
    """
    codes: List[str] = []
    skipped: List[str] = []
    for row in _open_position_rows(xml_bytes):
        asset_category = row.get("assetCategory")
        if asset_category is None:
            raise IbkrPortfolioError(
                "IBKR Open Positions 缺少 assetCategory 字段，请在 Flex Query 中勾选 Asset Class"
            )
        if str(asset_category).strip().upper() != "STK":
            continue
        symbol = (row.get("symbol") or "").strip()
        if not symbol:
            raise IbkrPortfolioError("IBKR 股票持仓缺少 symbol")
        try:
            quantity = float(row.get("position") or "")
        except ValueError:
            raise IbkrPortfolioError(f"IBKR 持仓数量无效: {symbol}") from None
        if not math.isfinite(quantity):
            raise IbkrPortfolioError(f"IBKR 持仓数量无效: {symbol}")
        if quantity <= 0:
            continue
        exchange = (row.get("listingExchange") or "").strip().upper()
        if not exchange:
            raise IbkrPortfolioError(
                "IBKR Open Positions 缺少 listingExchange 字段，请在 Flex Query 中勾选 Listing Exchange"
            )
        code = _to_analysis_code(symbol, exchange)
        if code is None:
            label = f"{symbol}@{exchange}"
            if label not in skipped:
                skipped.append(label)
            continue
        if code not in codes:
            codes.append(code)
    return codes, skipped


_STATEMENT_MAX_AGE_DAYS = 3


def _validate_statement_freshness(xml_bytes: bytes) -> None:
    """Fail when the Flex statement period ends too far in the past.

    A Flex query preset to e.g. "Last Month" yields a ``toDate`` a month old;
    holdings would silently reflect that stale point in time. Reject it so the
    caller is told to set the query period to the latest business day.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        raise IbkrPortfolioError("IBKR Flex 报表 XML 无法解析") from None
    to_dates = [
        (statement.get("toDate") or "").strip()
        for statement in root.findall("./FlexStatements/FlexStatement")
    ]
    today = date.today()
    for to_date in to_dates:
        try:
            parsed = datetime.strptime(to_date[:8], "%Y%m%d").date()
        except ValueError:
            continue
        if (today - parsed).days > _STATEMENT_MAX_AGE_DAYS:
            raise IbkrPortfolioError(
                f"IBKR Flex 报表期间过旧（toDate={parsed}，距今 {(today - parsed).days} 天）；"
                "请把 Flex Query 期间设为最近交易日"
            )


def load_ibkr_stock_codes() -> List[str]:
    """Return deduplicated analysis codes from the configured IBKR Flex query.

    Requires ``IBKR_FLEX_TOKEN`` and ``IBKR_FLEX_QUERY_ID``. Positions are
    downloaded on every call; IBKR generates Open Positions as of the latest
    statement date (usually the previous trading day). A statement whose period
    ends too far in the past is rejected so a stale "Last Month" query cannot
    silently feed old holdings into the analysis list.
    """
    token = (os.getenv("IBKR_FLEX_TOKEN") or "").strip()
    query_id = (os.getenv("IBKR_FLEX_QUERY_ID") or "").strip()
    if not token or not query_id:
        raise IbkrPortfolioError("--portfolio ibkr 需要配置 IBKR_FLEX_TOKEN 与 IBKR_FLEX_QUERY_ID")

    statement = download_flex_statement(token, query_id)
    _validate_statement_freshness(statement)
    codes, skipped = parse_open_position_codes(statement)
    if skipped:
        logger.info("跳过 %d 个暂不支持市场的 IBKR 持仓: %s", len(skipped), ", ".join(skipped))
    logger.info("已从 IBKR Flex 加载 %d 只正股: %s", len(codes), ", ".join(codes))
    return codes
