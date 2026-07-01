#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_symbols(raw_symbols: str | None = None) -> List[str]:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except Exception:
        pass

    raw = raw_symbols or os.getenv("STOCK_LIST", "")
    symbols = []
    seen = set()

    for item in raw.replace(";", ",").split(","):
        symbol = item.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)

    return symbols


def normalize_yfinance_history(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(col[0]).strip() for col in df.columns]

    df = df.reset_index()
    rename = {
        "Date": "date",
        "Datetime": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    }
    df = df.rename(columns=rename)

    keep = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].copy()

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    return df


def backfill_history(symbol: str, period: str = "1y") -> int:
    import yfinance as yf
    from src.storage import DatabaseManager

    raw = yf.download(
        symbol,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    df = normalize_yfinance_history(raw)
    if df.empty:
        print(f"[history] {symbol}: no data")
        return 0

    db = DatabaseManager()
    saved = db.save_daily_data(df, symbol, "yfinance")
    print(f"[history] {symbol}: rows={len(df)}, saved={saved}")
    return int(saved or 0)


def backfill_fundamental(symbol: str) -> int:
    from src.storage import DatabaseManager
    from src.services.alphasift_service import get_dsa_fundamental_context
    from src.services.us_valuation_service import enrich_us_valuation_context

    ctx = get_dsa_fundamental_context(symbol)
    ctx = enrich_us_valuation_context(symbol, ctx)

    db = DatabaseManager()
    query_id = f"stock_pool_backfill_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    saved = db.save_fundamental_snapshot(
        query_id=query_id,
        code=symbol,
        payload=ctx,
        source_chain=ctx.get("source_chain", []),
        coverage=ctx.get("coverage", {}),
    )
    valuation = (ctx.get("valuation") or {}).get("data") or {}
    print(
        f"[fundamental] {symbol}: saved={saved}, "
        f"PE={valuation.get('trailing_pe') or valuation.get('pe_ratio')}, "
        f"ForwardPE={valuation.get('forward_pe')}"
    )
    return int(saved or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill stock-pool daily bars and fundamental snapshots.")
    parser.add_argument("--symbols", help="Comma separated symbols. Default: STOCK_LIST from .env")
    parser.add_argument("--period", default="1y", help="yfinance history period, default: 1y")
    parser.add_argument("--skip-history", action="store_true")
    parser.add_argument("--skip-fundamental", action="store_true")
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()

    symbols = load_symbols(args.symbols)
    if not symbols:
        print("No symbols found. Set STOCK_LIST or pass --symbols GOOG,AAPL,TSLA")
        return 2

    print(f"Backfill symbols: {', '.join(symbols)}")

    ok = 0
    failed = 0

    for symbol in symbols:
        print(f"\n===== {symbol} =====")
        try:
            if not args.skip_history:
                backfill_history(symbol, args.period)
                time.sleep(args.sleep)
            if not args.skip_fundamental:
                backfill_fundamental(symbol)
                time.sleep(args.sleep)
            ok += 1
        except Exception as exc:
            failed += 1
            print(f"[failed] {symbol}: {exc!r}")

    print(f"\nDone. ok={ok}, failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
