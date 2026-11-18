# -*- coding: utf-8 -*-
"""Sync an IBKR Flex statement into the portfolio ledger (idempotent).

Imports stock executions (Trades) as trades and deposits/withdrawals
(CashTransactions) as cash events. Currency conversions, dividends,
withholding tax, fees, corporate actions, and unsupported-exchange holdings
are reported as skipped. Re-runs are safe: trades dedup on IBKR ``tradeID``
and cash events on IBKR ``transactionID``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from src.brokers.ibkr.flex import IbkrPortfolioError, download_flex_statement
from src.brokers.ibkr.statement import StatementParseResult, TradeRecord, parse_statement
from src.services.portfolio_service import (
    PortfolioConflictError,
    PortfolioOversellError,
    PortfolioService,
)

logger = logging.getLogger(__name__)

_STATEMENT_LOOKBACK_DAYS = 400
_WINDOW_MAX_DAYS = 365


def _yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _chunk_windows(since: date, to_date: date) -> List[Tuple[str, str]]:
    """Split ``[since, to_date]`` into IBKR windows of at most 365 days."""
    windows: List[Tuple[str, str]] = []
    cursor = since
    while cursor <= to_date:
        end = min(cursor + timedelta(days=_WINDOW_MAX_DAYS - 1), to_date)
        windows.append((_yyyymmdd(cursor), _yyyymmdd(end)))
        cursor = end + timedelta(days=1)
    return windows


def _resolve_account_id(service: PortfolioService, account_id: Optional[int]) -> int:
    if account_id is not None:
        return int(account_id)

    accounts = service.list_accounts(include_inactive=False)
    if not accounts:
        raise IbkrPortfolioError("没有可用的持仓账户，请先创建 IBKR 账户")
    if len(accounts) == 1:
        return int(accounts[0]["id"])

    ibkr_accounts = [
        a for a in accounts if (a.get("broker") or "").strip().lower() == "ibkr"
    ]
    if len(ibkr_accounts) == 1:
        return int(ibkr_accounts[0]["id"])
    raise IbkrPortfolioError(
        "存在多个持仓账户，请用 --account-id 指定目标账户"
    )


def _resolve_credentials() -> Tuple[str, str]:
    token = (os.getenv("IBKR_FLEX_TOKEN") or "").strip()
    query_id = (
        os.getenv("IBKR_FLEX_STATEMENT_QUERY_ID")
        or os.getenv("IBKR_FLEX_QUERY_ID")
        or ""
    ).strip()
    if not token or not query_id:
        raise IbkrPortfolioError(
            "IBKR 同步需要配置 IBKR_FLEX_TOKEN 与 IBKR_FLEX_STATEMENT_QUERY_ID"
        )
    return token, query_id


def _download_and_parse(
    token: str,
    query_id: str,
    *,
    since: Optional[date],
    to_date: date,
) -> StatementParseResult:
    since = since or (to_date - timedelta(days=_STATEMENT_LOOKBACK_DAYS))
    if since > to_date:
        raise IbkrPortfolioError("--since 不能晚于今天")

    merged = StatementParseResult()
    for from_date, to_date_str in _chunk_windows(since, to_date):
        statement = download_flex_statement(
            token,
            query_id,
            from_date=from_date,
            to_date=to_date_str,
        )
        parsed = parse_statement(statement)
        merged.trades.extend(parsed.trades)
        merged.cash_events.extend(parsed.cash_events)
        merged.skipped_trades.extend(parsed.skipped_trades)
        merged.skipped_cash.extend(parsed.skipped_cash)
        merged.skipped_corporate_actions.extend(parsed.skipped_corporate_actions)
    return merged


def _trade_sort_key(record: TradeRecord) -> Tuple[date, int]:
    uid_int = int(record.trade_uid) if record.trade_uid.isdigit() else 0
    return (record.trade_date, uid_int)


def sync_ibkr_portfolio(
    *,
    account_id: Optional[int] = None,
    since: Optional[date] = None,
    dry_run: bool = False,
) -> Dict[str, object]:
    """Download and commit the IBKR Flex statement into the ledger."""
    service = PortfolioService()
    resolved_account_id = _resolve_account_id(service, account_id)
    token, query_id = _resolve_credentials()

    parsed = _download_and_parse(
        token, query_id, since=since, to_date=date.today()
    )

    trades = sorted(parsed.trades, key=_trade_sort_key)

    summary: Dict[str, object] = {
        "account_id": resolved_account_id,
        "dry_run": dry_run,
        "trades_total": len(trades),
        "trades_inserted": 0,
        "trades_duplicate": 0,
        "cash_total": len(parsed.cash_events),
        "cash_inserted": 0,
        "cash_duplicate": 0,
        "skipped_trades": parsed.skipped_trades[:20],
        "skipped_trades_count": len(parsed.skipped_trades),
        "skipped_cash": parsed.skipped_cash[:20],
        "skipped_cash_count": len(parsed.skipped_cash),
        "skipped_corporate_actions": parsed.skipped_corporate_actions[:20],
        "skipped_corporate_actions_count": len(parsed.skipped_corporate_actions),
        "errors": [],
    }

    for record in trades:
        if dry_run:
            summary["trades_inserted"] += 1
            continue
        try:
            service.record_trade(
                account_id=resolved_account_id,
                symbol=record.symbol,
                trade_date=record.trade_date,
                side=record.side,
                quantity=record.quantity,
                price=record.price,
                fee=record.fee,
                tax=record.tax,
                market=record.market,
                currency=record.currency,
                trade_uid=record.trade_uid,
                note="ibkr_flex",
            )
            summary["trades_inserted"] += 1
        except PortfolioConflictError:
            summary["trades_duplicate"] += 1
        except PortfolioOversellError as exc:
            summary["errors"].append(f"oversell {record.symbol}@{record.trade_date}: {exc}")
        except Exception as exc:  # defensive: one bad row must not abort the sync
            summary["errors"].append(f"trade {record.symbol}: {exc}")

    for record in parsed.cash_events:
        if dry_run:
            summary["cash_inserted"] += 1
            continue
        try:
            service.record_cash_ledger(
                account_id=resolved_account_id,
                event_date=record.event_date,
                direction=record.direction,
                amount=record.amount,
                currency=record.currency,
                note=record.note,
                source_uid=record.source_uid,
            )
            summary["cash_inserted"] += 1
        except PortfolioConflictError:
            summary["cash_duplicate"] += 1
        except Exception as exc:  # defensive
            summary["errors"].append(f"cash {record.source_uid}: {exc}")

    summary["errors"] = summary["errors"][:20]  # type: ignore[assignment]
    logger.info(
        "IBKR 同步完成: account=%s dry_run=%s trades=%s(inserted)/%s(dup)/%s(skip) "
        "cash=%s(inserted)/%s(dup)/%s(skip) ca_skip=%s errors=%s",
        resolved_account_id,
        dry_run,
        summary["trades_inserted"],
        summary["trades_duplicate"],
        summary["skipped_trades_count"],
        summary["cash_inserted"],
        summary["cash_duplicate"],
        summary["skipped_cash_count"],
        summary["skipped_corporate_actions_count"],
        len(summary["errors"]),
    )
    return summary


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync IBKR Flex statement into the portfolio ledger")
    parser.add_argument("--account-id", type=int, default=None, help="Target ledger account id")
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Backfill start date (YYYY-MM-DD); default is the last ~400 days",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    since = date.fromisoformat(args.since) if args.since else None
    summary = sync_ibkr_portfolio(account_id=args.account_id, since=since, dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
