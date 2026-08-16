"""5-minute TDX market-data adapter for intraday candidate enrichment."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from data_provider.pytdx_fetcher import PytdxFetcher


class TdxIntradayAdapter:
    """Read 5-minute bars without changing existing PytdxFetcher behaviour."""

    BAR_COUNT = 800

    def __init__(self, fetcher: PytdxFetcher | None = None):
        self.fetcher = fetcher or PytdxFetcher()

    def _bars(self, stock_code: str, count: int | None = None) -> pd.DataFrame:
        market, code = self.fetcher._get_market_code(stock_code)
        with self.fetcher._pytdx_session() as api:
            rows = api.get_security_bars(
                category=0,  # 5-minute bars
                market=market,
                code=code,
                start=0,
                count=count or self.BAR_COUNT,
            )
            if not rows:
                return pd.DataFrame()
            df = api.to_df(rows)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
            df = df.dropna(subset=["datetime"]).sort_values("datetime")
        return df

    @staticmethod
    def _cumulative_to(df: pd.DataFrame, trigger_hhmm: str) -> dict[str, Any] | None:
        if df.empty or "datetime" not in df.columns:
            return None
        work = df.copy()
        work["hhmm"] = work["datetime"].dt.strftime("%H:%M")
        work = work[(work["hhmm"] >= "09:30") & (work["hhmm"] <= trigger_hhmm)]
        if work.empty:
            return None
        first = work.iloc[0]
        last = work.iloc[-1]
        amount = pd.to_numeric(work.get("amount"), errors="coerce").fillna(0).sum() if "amount" in work else 0.0
        volume_col = "vol" if "vol" in work.columns else "volume" if "volume" in work.columns else None
        volume = pd.to_numeric(work[volume_col], errors="coerce").fillna(0).sum() if volume_col else 0.0
        return {
            "price": float(last.get("close", 0) or 0),
            "close": float(last.get("close", 0) or 0),
            "open": float(first.get("open", 0) or 0),
            "high": float(pd.to_numeric(work.get("high"), errors="coerce").max() or 0),
            "low": float(pd.to_numeric(work.get("low"), errors="coerce").min() or 0),
            "cumulative_amount": float(amount),
            "cumulative_volume": float(volume),
        }

    def get_intraday_context(self, stock_code: str, now: datetime) -> dict[str, Any]:
        df = self._bars(stock_code)
        if df.empty:
            return {}
        trade_date = now.date()
        today = df[df["datetime"].dt.date == trade_date]
        context = self._cumulative_to(today, now.strftime("%H:%M")) or {}
        quote = self.fetcher.get_realtime_quote(stock_code) or {}
        for key in ("price", "open", "high", "low", "amount"):
            if quote.get(key) not in (None, 0, 0.0, ""):
                if key == "amount":
                    context["cumulative_amount"] = float(quote[key])
                else:
                    context[key] = float(quote[key])
        return context

    def get_historical_same_time(
        self,
        stock_code: str,
        now: datetime,
        days: int,
    ) -> list[dict[str, Any]]:
        df = self._bars(stock_code)
        if df.empty:
            return []
        trigger_hhmm = now.strftime("%H:%M")
        today = now.date()
        output: list[dict[str, Any]] = []
        for trade_date, day_df in df.groupby(df["datetime"].dt.date, sort=False):
            if trade_date >= today:
                continue
            row = self._cumulative_to(day_df, trigger_hhmm)
            if row:
                row["trade_date"] = trade_date.isoformat()
                row["minute_key"] = trigger_hhmm
                output.append(row)
        return output[-days:]
