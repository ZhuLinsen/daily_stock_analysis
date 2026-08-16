"""Small SQLite cache for same-time intraday baselines."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class SqliteHistoryRepository:
    def __init__(self, path: str | Path = "data/intraday_picker/intraday_history.sqlite3", baseline_days: int = 20):
        self.path = Path(path)
        self.baseline_days = max(5, int(baseline_days))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intraday_baseline (
                    stock_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    minute_key TEXT NOT NULL,
                    cumulative_amount REAL,
                    cumulative_volume REAL,
                    close REAL,
                    PRIMARY KEY(stock_code, trade_date, minute_key)
                )
                """
            )

    def _load(self, stock_code: str, minute_key: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT trade_date, cumulative_amount, cumulative_volume, close
                FROM intraday_baseline
                WHERE stock_code=? AND minute_key=?
                ORDER BY trade_date DESC
                LIMIT ?
                """,
                (stock_code, minute_key, self.baseline_days),
            ).fetchall()
        return [
            {
                "trade_date": trade_date,
                "cumulative_amount": amount,
                "cumulative_volume": volume,
                "close": close,
            }
            for trade_date, amount, volume, close in reversed(rows)
        ]

    def _save(self, stock_code: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO intraday_baseline
                (stock_code, trade_date, minute_key, cumulative_amount, cumulative_volume, close)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        stock_code,
                        row.get("trade_date"),
                        row.get("minute_key"),
                        row.get("cumulative_amount"),
                        row.get("cumulative_volume"),
                        row.get("close"),
                    )
                    for row in rows
                    if row.get("trade_date") and row.get("minute_key")
                ],
            )

    def get_or_build_baseline(self, stock_code: str, now: datetime, market_gateway: Any) -> list[dict[str, Any]]:
        minute_key = now.strftime("%H:%M")
        cached = self._load(stock_code, minute_key)
        # Ten observations are enough for a normal-confidence RVOL baseline.
        if len(cached) >= min(10, self.baseline_days):
            return cached
        rows = market_gateway.get_historical_same_time(stock_code, now, self.baseline_days)
        self._save(stock_code, rows)
        return self._load(stock_code, minute_key) or rows
