# -*- coding: utf-8 -*-
"""Backtest repository.

Provides database access helpers for backtest tables.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import and_, delete, desc, func, or_, select

from data_provider.base import is_bse_code
from src.core.backtest_engine import OVERALL_SENTINEL_CODE
from src.services.stock_code_utils import normalize_code as normalize_backtest_code

from src.storage import BacktestResult, BacktestSummary, DatabaseManager, AnalysisHistory

logger = logging.getLogger(__name__)

MARKET_REVIEW_REPORT_TYPE = "market_review"
BacktestResultContextRow = Tuple[
    BacktestResult,
    Optional[str],
    Optional[str],
    Optional[datetime],
    Optional[str],
    Optional[str],
    Optional[str],
]


class BacktestRepository:
    """DB access layer for backtesting."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def get_candidates(
        self,
        *,
        code: Optional[str],
        min_age_days: int,
        limit: int,
        offset: int = 0,
        eval_window_days: int,
        engine_version: str,
        force: bool,
    ) -> List[AnalysisHistory]:
        """Return AnalysisHistory rows eligible for backtest."""
        cutoff_dt = datetime.now() - timedelta(days=min_age_days)

        with self.db.get_session() as session:
            conditions = [AnalysisHistory.created_at <= cutoff_dt]
            if code:
                conditions.extend(self._build_code_conditions(AnalysisHistory.code, code))
            conditions.append(
                or_(
                    AnalysisHistory.report_type.is_(None),
                    AnalysisHistory.report_type != MARKET_REVIEW_REPORT_TYPE,
                )
            )

            query = select(AnalysisHistory).where(and_(*conditions))

            if not force:
                existing_ids = select(BacktestResult.analysis_history_id).where(
                    and_(
                        BacktestResult.eval_window_days == eval_window_days,
                        BacktestResult.engine_version == engine_version,
                    )
                )
                query = query.where(AnalysisHistory.id.not_in(existing_ids))

            query = query.order_by(desc(AnalysisHistory.created_at)).offset(offset).limit(limit)
            rows = session.execute(query).scalars().all()
            return list(rows)

    def align_existing_result_dates(
        self,
        *,
        code: Optional[str],
        min_age_days: int,
        eval_window_days: int,
        engine_version: str,
        analysis_date_from: Optional[date],
        analysis_date_to: Optional[date],
    ) -> int:
        """Align legacy result dates to their linked analysis snapshot date.

        Older backtest rows may have stored the trading/start daily date instead
        of the historical analysis snapshot date. When a date-filtered run skips
        already-existing rows, those legacy rows would remain invisible to the
        same date-filtered result query. Updating the stored result date keeps
        rerun and query semantics aligned without inserting duplicate rows.
        """
        cutoff_dt = datetime.now() - timedelta(days=min_age_days)

        with self.db.get_session() as session:
            conditions = [
                AnalysisHistory.created_at <= cutoff_dt,
                BacktestResult.eval_window_days == eval_window_days,
                BacktestResult.engine_version == engine_version,
                or_(
                    AnalysisHistory.report_type.is_(None),
                    AnalysisHistory.report_type != MARKET_REVIEW_REPORT_TYPE,
                ),
            ]
            if code:
                conditions.extend(self._build_code_conditions(AnalysisHistory.code, code))

            rows = session.execute(
                select(BacktestResult, AnalysisHistory)
                .join(AnalysisHistory, AnalysisHistory.id == BacktestResult.analysis_history_id)
                .where(and_(*conditions))
            ).all()

            updated = 0
            for result, analysis in rows:
                analysis_date = self.parse_analysis_date_from_snapshot(analysis.context_snapshot)
                if analysis_date is None and analysis.created_at is not None:
                    analysis_date = analysis.created_at.date()
                if analysis_date is None:
                    continue
                if analysis_date_from is not None and analysis_date < analysis_date_from:
                    continue
                if analysis_date_to is not None and analysis_date > analysis_date_to:
                    continue
                if result.analysis_date != analysis_date:
                    result.analysis_date = analysis_date
                    updated += 1

            if updated:
                session.commit()
            return updated

    def save_result(self, result: BacktestResult) -> None:
        with self.db.get_session() as session:
            session.add(result)
            session.commit()

    def save_results_batch(self, results: List[BacktestResult], *, replace_existing: bool = False) -> int:
        if not results:
            return 0

        with self.db.get_session() as session:
            try:
                if replace_existing:
                    analysis_ids = sorted({r.analysis_history_id for r in results if r.analysis_history_id is not None})
                    key_pairs = sorted({(r.eval_window_days, r.engine_version) for r in results})

                    if analysis_ids and key_pairs:
                        for window_days, engine_version in key_pairs:
                            session.execute(
                                delete(BacktestResult).where(
                                    and_(
                                        BacktestResult.analysis_history_id.in_(analysis_ids),
                                        BacktestResult.eval_window_days == window_days,
                                        BacktestResult.engine_version == engine_version,
                                    )
                                )
                            )

                session.add_all(results)
                session.commit()
                return len(results)
            except Exception as exc:
                session.rollback()
                logger.error(f"批量保存回测结果失败: {exc}")
                raise

    def get_results_paginated(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        days: Optional[int],
        offset: int,
        limit: int,
    ) -> Tuple[List[BacktestResultContextRow], int]:
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=days,
            )

            where_clause = and_(*conditions) if conditions else True

            total = session.execute(
                select(func.count(BacktestResult.id))
                .select_from(BacktestResult)
                .join(AnalysisHistory, AnalysisHistory.id == BacktestResult.analysis_history_id)
                .where(where_clause)
            ).scalar() or 0
            rows = session.execute(
                select(
                    BacktestResult,
                    AnalysisHistory.name,
                    AnalysisHistory.trend_prediction,
                    AnalysisHistory.created_at,
                    AnalysisHistory.context_snapshot,
                    AnalysisHistory.raw_result,
                    AnalysisHistory.report_type,
                )
                .join(AnalysisHistory, AnalysisHistory.id == BacktestResult.analysis_history_id)
                .where(where_clause)
                .order_by(desc(BacktestResult.analysis_date), desc(BacktestResult.evaluated_at))
                .offset(offset)
                .limit(limit)
            ).all()
            return list(rows), int(total)

    def get_results_with_context_batch(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        days: Optional[int],
        offset: int,
        limit: int,
    ) -> List[BacktestResultContextRow]:
        """Return result rows plus AnalysisHistory.context_snapshot for dynamic filtering."""
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=days,
            )
            where_clause = and_(*conditions) if conditions else True
            rows = session.execute(
                select(
                    BacktestResult,
                    AnalysisHistory.name,
                    AnalysisHistory.trend_prediction,
                    AnalysisHistory.created_at,
                    AnalysisHistory.context_snapshot,
                    AnalysisHistory.raw_result,
                    AnalysisHistory.report_type,
                )
                .join(AnalysisHistory, AnalysisHistory.id == BacktestResult.analysis_history_id)
                .where(where_clause)
                .order_by(desc(BacktestResult.analysis_date), desc(BacktestResult.evaluated_at))
                .offset(offset)
                .limit(limit)
            ).all()
            return list(rows)

    def list_results_with_context(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        days: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[Tuple[BacktestResult, Optional[str]]]:
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=days,
            )
            where_clause = and_(*conditions) if conditions else True
            query = (
                select(BacktestResult, AnalysisHistory.context_snapshot)
                .join(AnalysisHistory, AnalysisHistory.id == BacktestResult.analysis_history_id)
                .where(where_clause)
                .order_by(desc(BacktestResult.analysis_date), desc(BacktestResult.evaluated_at))
            )
            if limit is not None:
                query = query.limit(limit)
            return list(session.execute(query).all())

    def count_results(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        days: Optional[int] = None,
    ) -> int:
        """Return the number of matching BacktestResult rows without loading them."""
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=days,
            )
            where_clause = and_(*conditions) if conditions else True
            count = session.execute(
                select(func.count(BacktestResult.id))
                .select_from(BacktestResult)
                .where(where_clause)
            ).scalar() or 0
            return int(count)

    def list_results(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        days: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[BacktestResult]:
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=days,
            )
            where_clause = and_(*conditions) if conditions else True
            query = (
                select(BacktestResult)
                .where(where_clause)
                .order_by(desc(BacktestResult.analysis_date), desc(BacktestResult.evaluated_at))
            )
            if limit is not None:
                query = query.limit(limit)
            rows = session.execute(query).scalars().all()
            return list(rows)

    def upsert_summary(self, summary: BacktestSummary) -> None:
        """Insert or replace summary row by unique key."""
        with self.db.get_session() as session:
            existing = session.execute(
                select(BacktestSummary)
                .where(
                    and_(
                        BacktestSummary.scope == summary.scope,
                        BacktestSummary.code == summary.code,
                        BacktestSummary.eval_window_days == summary.eval_window_days,
                        BacktestSummary.engine_version == summary.engine_version,
                    )
                )
                .limit(1)
            ).scalar_one_or_none()

            if existing:
                for attr in (
                    "computed_at",
                    "total_evaluations",
                    "completed_count",
                    "insufficient_count",
                    "long_count",
                    "cash_count",
                    "win_count",
                    "loss_count",
                    "neutral_count",
                    "direction_accuracy_pct",
                    "win_rate_pct",
                    "neutral_rate_pct",
                    "avg_stock_return_pct",
                    "avg_simulated_return_pct",
                    "stop_loss_trigger_rate",
                    "take_profit_trigger_rate",
                    "ambiguous_rate",
                    "avg_days_to_first_hit",
                    "advice_breakdown_json",
                    "diagnostics_json",
                ):
                    setattr(existing, attr, getattr(summary, attr))
                session.commit()
                return

            session.add(summary)
            session.commit()

    def get_summary(
        self,
        *,
        scope: str,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        engine_version: str,
    ) -> Optional[BacktestSummary]:
        with self.db.get_session() as session:
            conditions = [
                BacktestSummary.scope == scope,
                BacktestSummary.engine_version == engine_version,
            ]
            if code:
                conditions.extend(self._build_code_conditions(BacktestSummary.code, code))
            if eval_window_days is not None:
                conditions.append(BacktestSummary.eval_window_days == eval_window_days)

            row = session.execute(
                select(BacktestSummary)
                .where(and_(*conditions))
                .order_by(desc(BacktestSummary.computed_at))
                .limit(1)
            ).scalar_one_or_none()
            return row

    @staticmethod
    def parse_analysis_date_from_snapshot(context_snapshot: Optional[str]) -> Optional[date]:
        if not context_snapshot:
            return None

        try:
            payload = json.loads(context_snapshot)
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None

        enhanced = payload.get("enhanced_context")
        if not isinstance(enhanced, dict):
            return None

        date_str = enhanced.get("date")
        if not date_str:
            return None

        try:
            return datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        except Exception:
            return None

    def get_distinct_eval_windows(
        self,
        *,
        code: Optional[str],
        engine_version: Optional[str] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
    ) -> List[int]:
        """Return sorted distinct eval_window_days for matching results."""
        with self.db.get_session() as session:
            conditions = self._build_result_conditions(
                code=code,
                eval_window_days=None,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=None,
            )
            where_clause = and_(*conditions) if conditions else True
            rows = session.execute(
                select(BacktestResult.eval_window_days)
                .where(where_clause)
                .distinct()
                .order_by(BacktestResult.eval_window_days)
            ).scalars().all()
            return [int(w) for w in rows if w is not None]

    @staticmethod
    def _build_result_conditions(
        *,
        code: Optional[str],
        eval_window_days: Optional[int],
        engine_version: Optional[str],
        analysis_date_from: Optional[date],
        analysis_date_to: Optional[date],
        days: Optional[int],
    ) -> List[object]:
        conditions = []
        if code:
            conditions.extend(BacktestRepository._build_code_conditions(BacktestResult.code, code))
        if eval_window_days is not None:
            conditions.append(BacktestResult.eval_window_days == eval_window_days)
        if engine_version:
            conditions.append(BacktestResult.engine_version == engine_version)
        if analysis_date_from is not None:
            conditions.append(BacktestResult.analysis_date >= analysis_date_from)
        if analysis_date_to is not None:
            conditions.append(BacktestResult.analysis_date <= analysis_date_to)
        if days:
            cutoff = datetime.now() - timedelta(days=int(days))
            conditions.append(BacktestResult.evaluated_at >= cutoff)
        return conditions

    @staticmethod
    def _build_code_conditions(column, code: str) -> List[object]:
        if not code:
            return []

        raw_code = str(code).strip()
        if raw_code.lower() == OVERALL_SENTINEL_CODE.lower():
            raw_code = OVERALL_SENTINEL_CODE
        else:
            raw_code = raw_code.upper()

        normalized_code = normalize_backtest_code(raw_code)

        candidates = [raw_code]
        if normalized_code and normalized_code != raw_code:
            candidates.append(normalized_code)
        candidates.extend(BacktestRepository._build_market_code_variants(raw_code, normalized_code))

        if len(candidates) == 1:
            return [column == candidates[0]]

        unique = list(dict.fromkeys(candidates))
        return [or_(*[column == candidate for candidate in unique])]

    @staticmethod
    def _build_hk_market_variants(hk_digits: str) -> List[str]:
        """Build normalized HK variants for padded/unpadded code shapes."""
        if not hk_digits.isdigit() or not hk_digits:
            return []

        padded = hk_digits.zfill(5)
        unpadded = padded.lstrip("0") or "0"

        variants: List[str] = [
            f"HK{padded}",
            f"{padded}.HK",
            padded,
            f"HK{unpadded}",
            f"{unpadded}.HK",
            f"HK.{padded}",
        ]
        if unpadded == padded:
            variants.pop(3)
            variants.pop(3)

        # Keep legacy no-leading-zero bare form for 1-3 digit inputs.
        if len(unpadded) <= 3 and unpadded != padded:
            variants.append(unpadded)
            variants.append(f"HK.{unpadded}")

        return variants

    @staticmethod
    def _build_market_code_variants(raw_code: str, normalized_code: str) -> List[str]:
        """Return additional market-formatted variants for safe stock-code matching."""
        variants: List[str] = []
        if not raw_code:
            return variants

        raw_code_upper = raw_code.upper()
        normalized_upper = normalized_code.upper() if normalized_code else ""

        def _add_us_variants(code: str) -> None:
            if not code:
                return
            if code.endswith(".US"):
                bare = code[:-3]
                if bare.isalpha() and 1 <= len(bare) <= 5:
                    variants.append(bare)
                return
            if "." not in code and code.isalpha() and 1 <= len(code) <= 5:
                variants.append(f"{code}.US")

        _add_us_variants(raw_code_upper)
        if normalized_upper != raw_code_upper:
            _add_us_variants(normalized_upper)

        def _explicit_exchange() -> Optional[str]:
            if raw_code_upper.startswith(("SH", "SS")) or raw_code_upper.endswith((".SH", ".SS")):
                return "SH"
            if raw_code_upper.startswith("SZ") or raw_code_upper.endswith(".SZ"):
                return "SZ"
            if raw_code_upper.startswith("BJ") or raw_code_upper.endswith(".BJ"):
                return "BJ"
            return None

        def _exchange_by_code(base: str) -> str:
            if is_bse_code(base):
                return "BJ"
            if base.startswith(("5", "6")):
                return "SH"
            return "SZ"

        if normalized_upper.isdigit() and len(normalized_upper) == 6:
            explicit_exchange = _explicit_exchange()
            if explicit_exchange is not None and explicit_exchange != _exchange_by_code(normalized_upper):
                return []

            if raw_code_upper.startswith(("SH", "SS")) or raw_code_upper.endswith(".SH") or raw_code_upper.endswith(".SS"):
                exchange = "SH"
            elif raw_code_upper.startswith("SZ") or raw_code_upper.endswith(".SZ"):
                exchange = "SZ"
            elif raw_code_upper.startswith("BJ") or raw_code_upper.endswith(".BJ") or is_bse_code(normalized_upper):
                exchange = "BJ"
            elif normalized_upper.startswith(("5", "6", "9")):
                exchange = "SH"
            else:
                exchange = "SZ"

            variants.append(f"{exchange}{normalized_upper}")
            variants.append(f"{normalized_upper}.{exchange}")
            variants.append(f"{exchange}.{normalized_upper}")
            if exchange == "SH":
                variants.append(f"SS{normalized_upper}")
                variants.append(f"{normalized_upper}.SS")
                variants.append(f"SS.{normalized_upper}")

        if (
            normalized_upper.startswith("HK")
            and len(normalized_upper) > 2
            and normalized_upper[2:].isdigit()
            and len(normalized_upper[2:]) <= 5
        ):
            variants.extend(BacktestRepository._build_hk_market_variants(normalized_upper[2:]))

        if (
            raw_code_upper.startswith("HK.")
            and raw_code_upper[3:].isdigit()
            and len(raw_code_upper[3:]) <= 5
        ):
            variants.extend(BacktestRepository._build_hk_market_variants(raw_code_upper[3:]))

        if (
            raw_code_upper.endswith(".HK")
            and raw_code_upper[:-3].isdigit()
            and 1 <= len(raw_code_upper[:-3]) <= 5
        ):
            hk_digits = raw_code_upper.rsplit(".", 1)[0]
            variants.extend(BacktestRepository._build_hk_market_variants(hk_digits))

        if raw_code_upper.isdigit() and len(raw_code_upper) in (4, 5):
            variants.extend(BacktestRepository._build_hk_market_variants(raw_code_upper))

        return variants
