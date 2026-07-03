# -*- coding: utf-8 -*-
"""Periodic (weekly/monthly) review service.

Aggregates market data over a review period (5 trading days for weekly,
~20 for monthly) and renders a Markdown report covering:

1. Index performance (cumulative change, avg turnover)
2. Sector strength ranking (top/bottom sectors)
3. Market Light sentiment trend
4. Period highlights (deterministic summary, no LLM dependency)

The service reuses ``MarketAnalyzer`` for current overview, akshare for
historical index data, and ``DatabaseManager`` for persisted Market Light
snapshots. All data sources degrade gracefully — missing data is shown as
"N/A" rather than blocking the report.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import get_config
from src.core.market_review import MARKET_REVIEW_HISTORY_CODE, MARKET_REVIEW_REPORT_TYPE
from src.schemas.periodic_review import (
    IndexPerformance,
    MarketLightTrendPoint,
    PeriodicReviewData,
    PeriodicReviewType,
    SectorPerformance,
)
from src.storage import AnalysisHistory, DatabaseManager

logger = logging.getLogger(__name__)

_WEEKLY_TRADE_DAYS = 5
_MONTHLY_TRADE_DAYS = 22
_YI = 1e8


class PeriodicReviewService:
    """Build weekly/monthly review reports from aggregated market data."""

    def __init__(self, region: str = "cn") -> None:
        self.region = region
        self.db = DatabaseManager.get_instance()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def run_weekly_review(self) -> Optional[str]:
        """Build and render a weekly review report."""
        data = self._build_review_data(_WEEKLY_TRADE_DAYS, PeriodicReviewType.WEEKLY)
        if data is None:
            return None
        return self._render_report(data)

    def run_monthly_review(self) -> Optional[str]:
        """Build and render a monthly review report."""
        data = self._build_review_data(_MONTHLY_TRADE_DAYS, PeriodicReviewType.MONTHLY)
        if data is None:
            return None
        return self._render_report(data)

    # ------------------------------------------------------------------
    # Data aggregation
    # ------------------------------------------------------------------

    def _build_review_data(
        self, trade_days: int, review_type: PeriodicReviewType
    ) -> Optional[PeriodicReviewData]:
        """Aggregate review data for the given period."""
        today = datetime.now().strftime("%Y-%m-%d")
        calendar_days = trade_days * 2 + 4  # buffer for weekends/holidays
        period_start = (datetime.now() - timedelta(days=calendar_days)).strftime("%Y-%m-%d")

        indices = self._fetch_index_performance(period_start, today, trade_days)
        market_light_trend = self._fetch_market_light_trend(calendar_days)
        sectors = self._fetch_current_sectors()

        avg_amount = 0.0
        if indices:
            avg_amount = sum(idx.avg_amount for idx in indices) / len(indices)

        rotation = self._detect_sector_rotation(market_light_trend)
        highlights = self._build_highlights(review_type, indices, market_light_trend)

        return PeriodicReviewData(
            review_type=review_type,
            region=self.region,
            period_start=period_start,
            period_end=today,
            trade_days=len(market_light_trend),
            indices=indices,
            top_sectors=sectors.get("top", []),
            bottom_sectors=sectors.get("bottom", []),
            market_light_trend=market_light_trend,
            avg_amount=avg_amount,
            sector_rotation=rotation,
            highlights=highlights,
        )

    def _fetch_index_performance(
        self, start: str, end: str, trade_days: int
    ) -> List[IndexPerformance]:
        """Fetch index performance over the period via akshare."""
        results: List[IndexPerformance] = []
        for code, name, symbol in (
            ("000001", "上证指数", "sh000001"),
            ("399001", "深证成指", "sz399001"),
            ("399006", "创业板指", "sz399006"),
        ):
            perf = self._fetch_single_index(code, name, symbol, trade_days)
            if perf:
                results.append(perf)
        return results

    def _fetch_single_index(
        self, code: str, name: str, symbol: str, trade_days: int
    ) -> Optional[IndexPerformance]:
        try:
            import akshare as ak

            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is None or df.empty:
                return None
            # Normalize column names
            close_col = self._find_column(df, ("close", "收盘", "收盘价"))
            amount_col = self._find_column(df, ("amount", "成交额", "money"))
            date_col = self._find_column(df, ("date", "日期", "trade_date"))
            if not close_col or not date_col:
                logger.warning("periodic_review: %s missing close/date column", symbol)
                return None
            df = df.sort_values(by=date_col).tail(trade_days + 2)
            if len(df) < 2:
                return None
            start_close = float(df[close_col].iloc[0])
            end_close = float(df[close_col].iloc[-1])
            change_pct = (end_close - start_close) / start_close * 100 if start_close else 0.0
            avg_amount = 0.0
            if amount_col:
                avg_amount = float(df[amount_col].tail(trade_days).mean()) / _YI
            return IndexPerformance(
                name=name,
                code=code,
                start_close=round(start_close, 2),
                end_close=round(end_close, 2),
                change_pct=round(change_pct, 2),
                avg_amount=round(avg_amount, 0),
            )
        except Exception as exc:
            logger.debug("periodic_review: index %s fetch failed: %s", symbol, exc)
            return None

    @staticmethod
    def _find_column(df, candidates) -> Optional[str]:
        for col in candidates:
            if col in df.columns:
                return col
        return None

    def _fetch_market_light_trend(self, calendar_days: int) -> List[MarketLightTrendPoint]:
        """Load persisted Market Light snapshots for the trend."""
        cutoff = datetime.now() - timedelta(days=calendar_days)
        try:
            with self.db.get_session() as session:
                rows = (
                    session.query(AnalysisHistory)
                    .filter(
                        AnalysisHistory.code == MARKET_REVIEW_HISTORY_CODE,
                        AnalysisHistory.report_type == MARKET_REVIEW_REPORT_TYPE,
                        AnalysisHistory.created_at >= cutoff,
                    )
                    .order_by(AnalysisHistory.created_at.asc())
                    .all()
                )
        except Exception as exc:
            logger.warning("periodic_review: history query failed: %s", exc)
            return []

        trend: List[MarketLightTrendPoint] = []
        seen_dates: set[str] = set()
        for row in rows:
            snapshot = self._extract_region_snapshot(row.context_snapshot)
            if not snapshot:
                continue
            trade_date = str(snapshot.get("trade_date") or "")
            if not trade_date or trade_date in seen_dates:
                continue
            seen_dates.add(trade_date)
            score = int(snapshot.get("score") or 0)
            status = str(snapshot.get("status") or "")
            trend.append(MarketLightTrendPoint(trade_date=trade_date, score=score, status=status))
        return trend

    @staticmethod
    def _extract_region_snapshot(raw_context_snapshot: Any) -> Optional[Dict[str, Any]]:
        if not raw_context_snapshot:
            return None
        try:
            payload = (
                json.loads(raw_context_snapshot)
                if isinstance(raw_context_snapshot, str)
                else raw_context_snapshot
            )
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        snapshots = payload.get("market_light_snapshots")
        if not isinstance(snapshots, dict):
            return None
        snapshot = snapshots.get("cn")
        return snapshot if isinstance(snapshot, dict) else None

    def _fetch_current_sectors(self) -> Dict[str, List[SectorPerformance]]:
        """Get current top/bottom sector rankings from MarketAnalyzer."""
        try:
            from src.market_analyzer import MarketAnalyzer

            analyzer = MarketAnalyzer(region=self.region)
            overview = analyzer.get_market_overview()
            top = [
                SectorPerformance(
                    name=str(s.get("name", "")),
                    change_pct=round(float(s.get("change_pct", 0) or 0), 2),
                    rank=i + 1,
                )
                for i, s in enumerate(overview.top_sectors[:5])
            ]
            bottom = [
                SectorPerformance(
                    name=str(s.get("name", "")),
                    change_pct=round(float(s.get("change_pct", 0) or 0), 2),
                    rank=i + 1,
                )
                for i, s in enumerate(overview.bottom_sectors[:5])
            ]
            return {"top": top, "bottom": bottom}
        except Exception as exc:
            logger.warning("periodic_review: sector fetch failed: %s", exc)
            return {"top": [], "bottom": []}

    @staticmethod
    def _detect_sector_rotation(
        trend: List[MarketLightTrendPoint],
    ) -> Optional[str]:
        """Detect sentiment rotation from the market light trend."""
        if len(trend) < 2:
            return None
        first_score = trend[0].score
        last_score = trend[-1].score
        delta = last_score - first_score
        if delta >= 15:
            return "情绪升温（score +{}）".format(delta)
        if delta <= -15:
            return "情绪降温（score {}）".format(delta)
        return "情绪平稳（score 变化 {:+d}）".format(delta)

    @staticmethod
    def _build_highlights(
        review_type: PeriodicReviewType,
        indices: List[IndexPerformance],
        trend: List[MarketLightTrendPoint],
    ) -> str:
        """Build a deterministic highlights summary (no LLM dependency)."""
        parts: List[str] = []
        label = "本周" if review_type == PeriodicReviewType.WEEKLY else "本月"
        if indices:
            up = [i for i in indices if i.change_pct > 0]
            down = [i for i in indices if i.change_pct < 0]
            if up and not down:
                parts.append("{}主要指数全线上涨，{}".format(label, "、".join(f"{i.name}+{i.change_pct}%" for i in up)))
            elif down and not up:
                parts.append("{}主要指数全线下跌，{}".format(label, "、".join(f"{i.name}{i.change_pct}%" for i in down)))
            elif up and down:
                parts.append("{}指数分化：{}上涨，{}下跌".format(
                    label,
                    "、".join(f"{i.name}+{i.change_pct}%" for i in up),
                    "、".join(f"{i.name}{i.change_pct}%" for i in down),
                ))
        if trend:
            avg_score = sum(t.score for t in trend) / len(trend)
            parts.append("{}平均 Market Light score {:.0f}，末值 {}".format(label, avg_score, trend[-1].status))
        return "；".join(parts) + "。" if parts else ""

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_report(self, data: PeriodicReviewData) -> Optional[str]:
        """Render the review data using the Jinja2 template."""
        try:
            from jinja2 import Environment, FileSystemLoader, select_autoescape
        except ImportError:
            logger.warning("jinja2 not installed, periodic review render skipped")
            return None

        base = Path(__file__).resolve().parent.parent.parent
        templates_dir = base / "templates"
        template_path = templates_dir / "periodic_review_markdown.j2"
        if not template_path.exists():
            logger.warning("periodic_review template not found: %s", template_path)
            return None

        env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html"]),
        )
        template = env.get_template("periodic_review_markdown.j2")
        return template.render(data=data.model_dump())
