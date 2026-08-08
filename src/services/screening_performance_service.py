# -*- coding: utf-8 -*-
"""Forward performance tracking for persisted screening results.

This module is deliberately descriptive: it records what happened after a
screening run and never changes strategy weights, ranking, or notifications.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import select

from data_provider import DataFetcherManager
from src.storage import DatabaseManager, ScreeningPerformance

logger = logging.getLogger(__name__)

DEFAULT_HORIZONS = (1, 5, 10)
DEFAULT_BENCHMARK = "sh000300"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(SHANGHAI)
    return parsed.date()


def _current_market_date() -> date:
    return datetime.now(timezone.utc).astimezone(SHANGHAI).date()


def _normalize_rows(frame: Any) -> list[dict[str, Any]]:
    if frame is None or not hasattr(frame, "to_dict"):
        return []
    try:
        raw_rows = frame.to_dict("records")
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        row_date = _parse_date(raw.get("date") or raw.get("日期") or raw.get("trade_date"))
        close = _float(raw.get("close") if raw.get("close") is not None else raw.get("收盘"))
        low = _float(raw.get("low") if raw.get("low") is not None else raw.get("最低"))
        if row_date is None or close is None or close <= 0:
            continue
        rows.append({"date": row_date, "close": close, "low": low})
    return sorted(rows, key=lambda item: item["date"])


class ScreeningPerformanceService:
    """Evaluate stored screening candidates against forward daily bars."""

    def __init__(self, db_manager: DatabaseManager | None = None):
        self.db = db_manager or DatabaseManager.get_instance()
        self._fetcher: Any = None
        self._series_cache: dict[tuple[str, date], tuple[list[dict[str, Any]], str]] = {}

    def run(
        self,
        *,
        run_id: str = "",
        strategy: str = "",
        limit: int = 20,
        horizons: Iterable[int] = DEFAULT_HORIZONS,
        benchmark_code: str = DEFAULT_BENCHMARK,
    ) -> dict[str, Any]:
        normalized_horizons = tuple(sorted({int(item) for item in horizons if int(item) in DEFAULT_HORIZONS}))
        if not normalized_horizons:
            raise ValueError("horizons must contain one of 1, 5, 10")
        if run_id:
            run_summaries = [{"run_id": run_id}]
        else:
            run_summaries = self.db.list_screening_runs(limit=max(1, min(int(limit), 100)), strategy=strategy or None)

        processed = 0
        evaluated = 0
        pending = 0
        errors = 0
        for summary in run_summaries:
            detail = self.db.get_screening_run(str(summary.get("run_id") or "")) or {}
            result = detail.get("result") if isinstance(detail.get("result"), dict) else {}
            candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
            if not candidates:
                continue
            processed += 1
            run_result = dict(result)
            analysis_date = _parse_date(run_result.get("analysis_date") or detail.get("created_at")) or _current_market_date()
            run_strategy = str(detail.get("strategy") or run_result.get("strategy") or "unknown")
            market = str(detail.get("market") or run_result.get("market") or "cn")
            benchmark_rows, benchmark_source = self._load_series(benchmark_code, analysis_date)
            benchmark_by_date = {row["date"]: row for row in benchmark_rows}

            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                code = str(candidate.get("code") or candidate.get("symbol") or "").strip()
                if not code:
                    continue
                stock_rows, stock_source = self._load_series(code, analysis_date)
                for horizon in normalized_horizons:
                    row = self._evaluate_one(
                        run_id=str(summary.get("run_id") or run_id),
                        strategy=run_strategy,
                        market=market,
                        candidate=candidate,
                        code=code,
                        analysis_date=analysis_date,
                        horizon=horizon,
                        stock_rows=stock_rows,
                        stock_source=stock_source,
                        benchmark_rows=benchmark_by_date,
                        benchmark_source=benchmark_source,
                        benchmark_code=benchmark_code,
                    )
                    self._save(row)
                    if row["eval_status"] == "evaluated":
                        evaluated += 1
                    elif row["eval_status"] == "pending":
                        pending += 1
                    else:
                        errors += 1

        return {
            "processed_runs": processed,
            "evaluated": evaluated,
            "pending": pending,
            "errors": errors,
            "horizons": list(normalized_horizons),
            "benchmark_code": benchmark_code,
        }

    def summary(
        self,
        *,
        strategy: str = "",
        horizon: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        with self.db.get_session() as session:
            statement = select(ScreeningPerformance).where(ScreeningPerformance.eval_status == "evaluated")
            if strategy:
                statement = statement.where(ScreeningPerformance.strategy == strategy)
            if horizon is not None:
                statement = statement.where(ScreeningPerformance.horizon_days == int(horizon))
            rows = session.execute(
                statement.order_by(ScreeningPerformance.analysis_date.desc(), ScreeningPerformance.id.desc()).limit(max(1, min(int(limit), 500)))
            ).scalars().all()

        by_horizon: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.horizon_days)
            item = by_horizon.setdefault(key, {"horizon_days": row.horizon_days, "sample_count": 0, "avg_stock_return_pct": None, "avg_benchmark_return_pct": None, "avg_excess_return_pct": None, "avg_max_drawdown_pct": None})
            item["sample_count"] += 1
            for field, output in (
                ("stock_return_pct", "stock_returns"),
                ("benchmark_return_pct", "benchmark_returns"),
                ("excess_return_pct", "excess_returns"),
                ("max_drawdown_pct", "drawdowns"),
            ):
                value = _float(getattr(row, field, None))
                if value is not None:
                    item.setdefault(output, []).append(value)
        for item in by_horizon.values():
            for source, output in (("stock_returns", "avg_stock_return_pct"), ("benchmark_returns", "avg_benchmark_return_pct"), ("excess_returns", "avg_excess_return_pct"), ("drawdowns", "avg_max_drawdown_pct")):
                values = item.pop(source, [])
                item[output] = round(sum(values) / len(values), 4) if values else None
        return {"sample_count": len(rows), "horizons": sorted(by_horizon.values(), key=lambda item: item["horizon_days"]), "records": [self._row_to_dict(row) for row in rows]}

    def _load_series(self, code: str, analysis_date: date) -> tuple[list[dict[str, Any]], str]:
        key = (code, analysis_date)
        if key in self._series_cache:
            return self._series_cache[key]
        if self._fetcher is None:
            self._fetcher = DataFetcherManager()
        try:
            frame, source = self._fetcher.get_daily_data(
                code,
                start_date=(analysis_date - timedelta(days=45)).isoformat(),
                end_date=_current_market_date().isoformat(),
                days=45,
            )
            result = (_normalize_rows(frame), str(source or "unknown"))
        except Exception as exc:  # forward tracking must not affect screening.
            logger.warning("screening performance daily data failed code=%s: %s", code, exc)
            result = ([], "unavailable")
        self._series_cache[key] = result
        return result

    @staticmethod
    def _evaluate_one(*, run_id: str, strategy: str, market: str, candidate: dict[str, Any], code: str, analysis_date: date, horizon: int, stock_rows: list[dict[str, Any]], stock_source: str, benchmark_rows: dict[date, dict[str, Any]], benchmark_source: str, benchmark_code: str) -> dict[str, Any]:
        start_price = _float(candidate.get("price"))
        start_row = next((row for row in stock_rows if row["date"] == analysis_date), None)
        if start_price is None or start_price <= 0:
            start_price = _float(start_row.get("close") if start_row else None)
        forward = [row for row in stock_rows if row["date"] > analysis_date]
        target = forward[horizon - 1] if len(forward) >= horizon else None
        benchmark_start = benchmark_rows.get(analysis_date)
        benchmark_forward = [row for row in benchmark_rows.values() if row["date"] > analysis_date]
        benchmark_target = benchmark_forward[horizon - 1] if len(benchmark_forward) >= horizon else None
        status = "evaluated" if start_price and target else "pending"
        message = "数据不足，等待后续交易日补齐" if status == "pending" else ""
        stock_return = ((target["close"] / start_price) - 1.0) * 100 if status == "evaluated" else None
        benchmark_return = None
        excess = None
        if benchmark_start and benchmark_target and benchmark_start.get("close", 0) > 0:
            benchmark_return = ((benchmark_target["close"] / benchmark_start["close"]) - 1.0) * 100
            if stock_return is not None:
                excess = stock_return - benchmark_return
        drawdown = None
        if status == "evaluated":
            lows = [
                float(row["low"])
                for row in ([start_row] if start_row else []) + forward[:horizon]
                if row.get("low") is not None
            ]
            if lows:
                drawdown = (min(lows) / start_price - 1.0) * 100
        return {
            "screening_run_id": run_id,
            "strategy": strategy,
            "market": market,
            "code": code,
            "name": str(candidate.get("name") or ""),
            "rank": int(candidate.get("rank") or 0),
            "horizon_days": horizon,
            "eval_status": status,
            "analysis_date": analysis_date,
            "end_date": target["date"] if target else None,
            "start_price": start_price,
            "end_close": target["close"] if target else None,
            "stock_return_pct": stock_return,
            "benchmark_code": benchmark_code,
            "benchmark_start": benchmark_start.get("close") if benchmark_start else None,
            "benchmark_end": benchmark_target.get("close") if benchmark_target else None,
            "benchmark_return_pct": benchmark_return,
            "excess_return_pct": excess,
            "max_drawdown_pct": drawdown,
            "data_source": stock_source,
            "benchmark_source": benchmark_source,
            "message": message,
        }

    def _save(self, values: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.db.session_scope() as session:
            row = session.execute(
                select(ScreeningPerformance).where(
                    ScreeningPerformance.screening_run_id == values["screening_run_id"],
                    ScreeningPerformance.code == values["code"],
                    ScreeningPerformance.horizon_days == values["horizon_days"],
                )
            ).scalar_one_or_none()
            if row is None:
                row = ScreeningPerformance(created_at=now, **values)
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                row.updated_at = now

    @staticmethod
    def _row_to_dict(row: ScreeningPerformance) -> dict[str, Any]:
        return {
            "screening_run_id": row.screening_run_id,
            "strategy": row.strategy,
            "market": row.market,
            "code": row.code,
            "name": row.name,
            "rank": row.rank,
            "horizon_days": row.horizon_days,
            "eval_status": row.eval_status,
            "analysis_date": row.analysis_date.isoformat() if row.analysis_date else None,
            "end_date": row.end_date.isoformat() if row.end_date else None,
            "start_price": row.start_price,
            "end_close": row.end_close,
            "stock_return_pct": row.stock_return_pct,
            "benchmark_code": row.benchmark_code,
            "benchmark_return_pct": row.benchmark_return_pct,
            "excess_return_pct": row.excess_return_pct,
            "max_drawdown_pct": row.max_drawdown_pct,
            "data_source": row.data_source,
            "benchmark_source": row.benchmark_source,
            "message": row.message or "",
        }
