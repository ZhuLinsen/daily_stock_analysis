# -*- coding: utf-8 -*-
"""Backtest orchestration service."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, select

from data_provider.base import canonical_stock_code, normalize_stock_code
from src.config import get_config
from src.core.backtest_engine import OVERALL_SENTINEL_CODE, BacktestEngine, EvaluationConfig
from src.market_phase_summary import extract_market_phase_summary, normalize_analysis_phase_bucket
from src.repositories.backtest_repo import BacktestRepository
from src.repositories.stock_repo import StockRepository
from src.schemas.decision_action import build_action_fields
from src.storage import BacktestResult, BacktestSummary, DatabaseManager
from src.utils.data_processing import parse_json_field
from src.services.stock_code_utils import normalize_code as normalize_backtest_code

logger = logging.getLogger(__name__)


class BacktestService:
    """Service layer to run and query backtests."""

    MAX_DYNAMIC_SUMMARY_ROWS = 2000

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()
        self.repo = BacktestRepository(self.db)
        self.stock_repo = StockRepository(self.db)

    def run_backtest(
        self,
        *,
        code: Optional[str] = None,
        force: bool = False,
        eval_window_days: Optional[int] = None,
        min_age_days: Optional[int] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        config = get_config()

        if analysis_date_from and analysis_date_to and analysis_date_from > analysis_date_to:
            raise ValueError("analysis_date_from cannot be after analysis_date_to")

        query_code = self._normalize_code(code)
        diagnostic_code = self._normalize_code_for_display(code)

        if eval_window_days is None:
            eval_window_days = getattr(config, "backtest_eval_window_days", 10)
        if min_age_days is None:
            min_age_days = getattr(config, "backtest_min_age_days", 14)

        engine_version = getattr(config, "backtest_engine_version", "v1")
        neutral_band_pct = float(getattr(config, "backtest_neutral_band_pct", 2.0))

        eval_config = EvaluationConfig(
            eval_window_days=int(eval_window_days),
            neutral_band_pct=neutral_band_pct,
            engine_version=str(engine_version),
        )

        limit_int = int(limit)
        candidates = self._get_run_candidates(
            code=query_code,
            min_age_days=int(min_age_days),
            limit=limit_int,
            eval_window_days=int(eval_window_days),
            engine_version=str(engine_version),
            force=force,
            analysis_date_from=analysis_date_from,
            analysis_date_to=analysis_date_to,
        )

        processed = 0
        completed = 0
        insufficient = 0
        errors = 0
        touched_codes: set[str] = set()

        results_to_save: List[BacktestResult] = []

        for analysis in candidates:
            processed += 1
            normalized_code = self._normalize_summary_code(analysis.code)
            if normalized_code:
                touched_codes.add(normalized_code)

            try:
                analysis_date = self._resolve_analysis_date(analysis)
                if analysis_date is None:
                    errors += 1
                    results_to_save.append(
                        BacktestResult(
                            analysis_history_id=analysis.id,
                            code=analysis.code,
                            eval_window_days=int(eval_window_days),
                            engine_version=str(engine_version),
                            eval_status="error",
                            evaluated_at=datetime.now(),
                            operation_advice=analysis.operation_advice,
                        )
                    )
                    continue
                daily_code_candidates = self._build_daily_code_candidates(analysis.code)
                start_daily = self._get_start_daily_for_candidates(
                    code_candidates=daily_code_candidates,
                    analysis_date=analysis_date,
                )

                if start_daily is None or start_daily.close is None:
                    refill_code = daily_code_candidates[0] if daily_code_candidates else analysis.code
                    self._try_fill_daily_data(
                        code=refill_code,
                        analysis_date=analysis_date,
                        eval_window_days=eval_window_days,
                    )
                    start_daily = self._get_start_daily_for_candidates(
                        code_candidates=daily_code_candidates,
                        analysis_date=analysis_date,
                    )

                if start_daily is None or start_daily.close is None:
                    insufficient += 1
                    results_to_save.append(
                        BacktestResult(
                            analysis_history_id=analysis.id,
                            code=analysis.code,
                            analysis_date=analysis_date,
                            eval_window_days=int(eval_window_days),
                            engine_version=str(engine_version),
                            eval_status="insufficient_data",
                            evaluated_at=datetime.now(),
                            operation_advice=analysis.operation_advice,
                        )
                    )
                    continue

                matched_daily_code = start_daily.code or (
                    daily_code_candidates[0] if daily_code_candidates else analysis.code
                )
                forward_bars = self._get_forward_bars_by_candidates(
                    code_candidates=daily_code_candidates,
                    analysis_date=start_daily.date,
                    eval_window_days=int(eval_window_days),
                    preferred_code=matched_daily_code,
                )

                if len(forward_bars) < int(eval_window_days):
                    for fill_code in self._ordered_daily_refill_codes(
                        code_candidates=daily_code_candidates,
                        preferred_code=matched_daily_code,
                    ):
                        self._try_fill_daily_data(
                            code=fill_code,
                            analysis_date=start_daily.date,
                            eval_window_days=eval_window_days,
                        )
                        forward_bars = self._get_forward_bars_by_candidates(
                            code_candidates=daily_code_candidates,
                            analysis_date=start_daily.date,
                            eval_window_days=int(eval_window_days),
                            preferred_code=matched_daily_code,
                        )
                        if len(forward_bars) >= int(eval_window_days):
                            break

                evaluation = BacktestEngine.evaluate_single(
                    operation_advice=analysis.operation_advice,
                    analysis_date=start_daily.date,
                    start_price=float(start_daily.close),
                    forward_bars=forward_bars,
                    stop_loss=analysis.stop_loss,
                    take_profit=analysis.take_profit,
                    config=eval_config,
                )

                status = evaluation.get("eval_status")
                if status == "insufficient_data":
                    insufficient += 1
                elif status == "completed":
                    completed += 1
                else:
                    errors += 1

                results_to_save.append(
                    BacktestResult(
                        analysis_history_id=analysis.id,
                        code=analysis.code,
                        analysis_date=analysis_date,
                        eval_window_days=int(evaluation.get("eval_window_days") or eval_window_days),
                        engine_version=str(evaluation.get("engine_version") or engine_version),
                        eval_status=str(evaluation.get("eval_status") or "error"),
                        evaluated_at=datetime.now(),
                        operation_advice=evaluation.get("operation_advice"),
                        position_recommendation=evaluation.get("position_recommendation"),
                        start_price=evaluation.get("start_price"),
                        end_close=evaluation.get("end_close"),
                        max_high=evaluation.get("max_high"),
                        min_low=evaluation.get("min_low"),
                        stock_return_pct=evaluation.get("stock_return_pct"),
                        direction_expected=evaluation.get("direction_expected"),
                        direction_correct=evaluation.get("direction_correct"),
                        outcome=evaluation.get("outcome"),
                        stop_loss=evaluation.get("stop_loss"),
                        take_profit=evaluation.get("take_profit"),
                        hit_stop_loss=evaluation.get("hit_stop_loss"),
                        hit_take_profit=evaluation.get("hit_take_profit"),
                        first_hit=evaluation.get("first_hit"),
                        first_hit_date=evaluation.get("first_hit_date"),
                        first_hit_trading_days=evaluation.get("first_hit_trading_days"),
                        simulated_entry_price=evaluation.get("simulated_entry_price"),
                        simulated_exit_price=evaluation.get("simulated_exit_price"),
                        simulated_exit_reason=evaluation.get("simulated_exit_reason"),
                        simulated_return_pct=evaluation.get("simulated_return_pct"),
                    )
                )

            except Exception as exc:
                errors += 1
                logger.error(f"回测失败: {analysis.code}#{analysis.id}: {exc}")
                results_to_save.append(
                    BacktestResult(
                        analysis_history_id=analysis.id,
                        code=analysis.code,
                        analysis_date=self._resolve_analysis_date(analysis),
                        eval_window_days=int(eval_window_days),
                        engine_version=str(engine_version),
                        eval_status="error",
                        evaluated_at=datetime.now(),
                        operation_advice=analysis.operation_advice,
                    )
                )

        saved = 0
        if results_to_save:
            saved = self.repo.save_results_batch(results_to_save, replace_existing=force)

        if saved:
            self._recompute_summaries(
                touched_codes=sorted(touched_codes),
                eval_window_days=int(eval_window_days),
                engine_version=str(engine_version),
            )

        has_matching_analysis = False
        aligned_existing_result_dates = 0
        has_analysis_date_filter = analysis_date_from is not None or analysis_date_to is not None
        if not force and has_analysis_date_filter:
            aligned_existing_result_dates = self.repo.align_existing_result_dates(
                code=query_code,
                min_age_days=int(min_age_days),
                eval_window_days=int(eval_window_days),
                engine_version=str(engine_version),
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
            )
        if not force and processed == 0:
            has_matching_analysis = self._has_matching_analysis_for_run(
                code=query_code,
                min_age_days=int(min_age_days),
                eval_window_days=int(eval_window_days),
                engine_version=str(engine_version),
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
            )

        diagnostics = self._build_run_diagnostics(
            code=diagnostic_code,
            eval_window_days=int(eval_window_days),
            min_age_days=int(min_age_days),
            limit=limit_int,
            analysis_date_from=analysis_date_from,
            analysis_date_to=analysis_date_to,
            processed=processed,
            saved=saved,
            completed=completed,
            insufficient=insufficient,
            errors=errors,
            has_matching_analysis=has_matching_analysis,
            aligned_existing_result_dates=aligned_existing_result_dates,
        )

        return {
            "processed": processed,
            "saved": saved,
            "completed": completed,
            "insufficient": insufficient,
            "errors": errors,
            "applied_eval_window_days": int(eval_window_days),
            "message": diagnostics.get("message"),
            "diagnostics": diagnostics,
        }

    def _get_run_candidates(
        self,
        *,
        code: Optional[str],
        min_age_days: int,
        limit: int,
        eval_window_days: int,
        engine_version: str,
        force: bool,
        analysis_date_from: Optional[date],
        analysis_date_to: Optional[date],
    ) -> List[Any]:
        if limit <= 0:
            return []

        if analysis_date_from is None and analysis_date_to is None:
            return self.repo.get_candidates(
                code=code,
                min_age_days=min_age_days,
                limit=limit,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                force=force,
            )

        matched: List[Any] = []
        offset = 0
        page_size = min(max(limit, 200), 1000)

        while len(matched) < limit:
            batch = self.repo.get_candidates(
                code=code,
                min_age_days=min_age_days,
                limit=page_size,
                offset=offset,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                force=force,
            )
            if not batch:
                break

            matched.extend(
                self._filter_candidates_by_analysis_date(
                    batch,
                    analysis_date_from=analysis_date_from,
                    analysis_date_to=analysis_date_to,
                )
            )
            offset += len(batch)
            if len(batch) < page_size:
                break

        return matched[:limit]

    def _has_matching_analysis_for_run(
        self,
        *,
        code: Optional[str],
        min_age_days: int,
        eval_window_days: int,
        engine_version: str,
        analysis_date_from: Optional[date],
        analysis_date_to: Optional[date],
    ) -> bool:
        """Check if historical analysis rows match the same run filters, ignoring backtest history."""
        if analysis_date_from is None and analysis_date_to is None:
            return bool(
                self.repo.get_candidates(
                    code=code,
                    min_age_days=min_age_days,
                    limit=1,
                    eval_window_days=eval_window_days,
                    engine_version=engine_version,
                    force=True,
                )
            )

        return len(
            self._get_run_candidates(
                code=code,
                min_age_days=min_age_days,
                limit=1,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                force=True,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
            )
        ) > 0

    def _filter_candidates_by_analysis_date(
        self,
        candidates: List[Any],
        *,
        analysis_date_from: Optional[date],
        analysis_date_to: Optional[date],
    ) -> List[Any]:
        if analysis_date_from is None and analysis_date_to is None:
            return candidates

        filtered: List[Any] = []
        for analysis in candidates:
            analysis_date = self._resolve_analysis_date(analysis)
            if analysis_date is None:
                continue
            if analysis_date_from is not None and analysis_date < analysis_date_from:
                continue
            if analysis_date_to is not None and analysis_date > analysis_date_to:
                continue
            filtered.append(analysis)
        return filtered

    def _get_start_daily_for_candidates(self, *, code_candidates: List[str], analysis_date: date):
        best_daily = None
        best_rank = len(code_candidates)
        for rank, candidate in enumerate(code_candidates):
            daily = self.stock_repo.get_start_daily(code=candidate, analysis_date=analysis_date)
            if daily is None:
                continue
            if best_daily is None or daily.date > best_daily.date or (
                daily.date == best_daily.date and rank < best_rank
            ):
                best_daily = daily
                best_rank = rank
        return best_daily

    @staticmethod
    def _build_daily_code_candidates(code: Optional[str]) -> List[str]:
        if not code:
            return []

        raw_code = str(code).strip()
        if not raw_code:
            return []

        raw_code = raw_code.upper()
        normalized_code = normalize_stock_code(raw_code)
        backtest_normalized_code = normalize_backtest_code(raw_code)
        candidates = [raw_code]
        for candidate in (normalized_code, backtest_normalized_code):
            if candidate and candidate != raw_code:
                candidates.append(candidate)
        for candidate in list(candidates):
            candidates.extend(BacktestRepository._build_market_code_variants(raw_code, candidate))
        return list(dict.fromkeys(candidate for candidate in candidates if candidate))

    @staticmethod
    def _normalize_code(code: Optional[str]) -> Optional[str]:
        if not code:
            return None

        normalized = normalize_backtest_code(str(code).strip())
        if normalized is None:
            raise ValueError(f"非法股票代码格式: {code}")
        return normalized

    @staticmethod
    def _normalize_summary_code(code: Optional[str]) -> Optional[str]:
        if not code:
            return None
        raw_code = str(code).strip()
        normalized = normalize_stock_code(raw_code)
        backtest_normalized = normalize_backtest_code(raw_code)
        if raw_code.upper().startswith("SS") and backtest_normalized and backtest_normalized != normalized:
            normalized = backtest_normalized
        return canonical_stock_code(normalized or raw_code)

    @staticmethod
    def _normalize_code_for_display(code: Optional[str]) -> Optional[str]:
        if not code:
            return None

        normalized = normalize_backtest_code(str(code).strip())
        if normalized is None:
            raise ValueError(f"非法股票代码格式: {code}")
        return normalized

    @staticmethod
    def _ordered_candidate_codes(
        *,
        code_candidates: List[str],
        preferred_code: Optional[str] = None,
    ) -> List[str]:
        ordered = list(dict.fromkeys(code_candidates))
        if not ordered:
            return []

        if not preferred_code:
            return ordered

        normalized_preferred = preferred_code.strip()
        if normalized_preferred and normalized_preferred in ordered:
            return [normalized_preferred] + [code for code in ordered if code != normalized_preferred]
        return ordered

    @staticmethod
    def _normalize_daily_refill_code(code: Optional[str]) -> str:
        raw_code = str(code or "").strip()
        if not raw_code:
            return ""
        return canonical_stock_code(normalize_stock_code(raw_code))

    @staticmethod
    def _ordered_daily_refill_codes(
        *,
        code_candidates: List[str],
        preferred_code: Optional[str] = None,
    ) -> List[str]:
        ordered = BacktestService._ordered_candidate_codes(
            code_candidates=code_candidates,
            preferred_code=preferred_code,
        )
        refill_codes: List[str] = []
        seen: set[str] = set()
        for code in ordered:
            refill_code = BacktestService._normalize_daily_refill_code(code)
            if not refill_code or refill_code in seen:
                continue
            seen.add(refill_code)
            refill_codes.append(refill_code)
        return refill_codes

    def _get_forward_bars_by_candidates(
        self,
        *,
        code_candidates: List[str],
        analysis_date: date,
        eval_window_days: int,
        preferred_code: Optional[str] = None,
    ) -> List[Any]:
        ordered_codes = BacktestService._ordered_candidate_codes(
            code_candidates=code_candidates,
            preferred_code=preferred_code,
        )

        if not ordered_codes:
            return []

        best_bars: List[Any] = []
        for code in ordered_codes:
            if not code:
                continue

            bars = self.stock_repo.get_forward_bars(
                code=code,
                analysis_date=analysis_date,
                eval_window_days=eval_window_days,
            )
            if len(bars) >= eval_window_days:
                return bars
            if len(bars) > len(best_bars):
                best_bars = bars
        return best_bars

    @staticmethod
    def _build_run_diagnostics(
        *,
        code: Optional[str],
        eval_window_days: int,
        min_age_days: int,
        limit: int,
        analysis_date_from: Optional[date],
        analysis_date_to: Optional[date],
        processed: int,
        saved: int,
        completed: int,
        insufficient: int,
        errors: int,
        has_matching_analysis: bool = False,
        aligned_existing_result_dates: int = 0,
    ) -> Dict[str, Any]:
        diagnostics: Dict[str, Any] = {
            "code": code,
            "eval_window_days": eval_window_days,
            "min_age_days": min_age_days,
            "limit": limit,
            "analysis_date_from": analysis_date_from.isoformat() if analysis_date_from else None,
            "analysis_date_to": analysis_date_to.isoformat() if analysis_date_to else None,
        }
        if aligned_existing_result_dates:
            diagnostics["aligned_existing_result_dates"] = aligned_existing_result_dates

        message: Optional[str] = None
        if processed == 0:
            if has_matching_analysis:
                diagnostics["empty_reason"] = "no_new_results"
                message = "历史分析记录已存在，当前筛选条件下没有新的回测任务可执行。"
            else:
                diagnostics["empty_reason"] = "no_matching_analysis"
                message = "未找到符合条件的历史分析记录，请检查股票代码、分析日期范围、最小天龄或是否已生成历史分析。"
        elif completed == 0 and insufficient > 0 and errors == 0:
            diagnostics["empty_reason"] = "insufficient_daily_data"
            message = "已找到历史分析记录，但可用日线行情不足，无法完成回测。"
        elif completed == 0 and errors > 0:
            diagnostics["empty_reason"] = "evaluation_error"
            message = "已找到历史分析记录，但回测计算失败，请查看后端日志或放宽筛选条件。"
        elif saved == 0 and completed == 0:
            diagnostics["empty_reason"] = "no_new_results"
            message = "没有写入新的回测结果；如需覆盖已有结果，请启用强制重跑。"

        if message:
            diagnostics["message"] = message
        return diagnostics

    def get_recent_evaluations(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        limit: int = 50,
        page: int = 1,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        analysis_phase: Optional[str] = None,
    ) -> Dict[str, Any]:
        config = get_config()
        engine_version = str(getattr(config, "backtest_engine_version", "v1"))
        code = self._normalize_code(code)

        phase_bucket = self._normalize_phase_filter(analysis_phase)
        if eval_window_days is None and (analysis_date_from is not None or analysis_date_to is not None or phase_bucket is not None):
            eval_window_days = self._infer_eval_window_for_query(
                code=code,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
            )
        if phase_bucket is not None:
            return self._get_recent_evaluations_by_phase(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                limit=limit,
                page=page,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                phase_bucket=phase_bucket,
            )

        offset = max(page - 1, 0) * limit
        rows, total = self.repo.get_results_paginated(
            code=code,
            eval_window_days=eval_window_days,
            engine_version=engine_version,
            analysis_date_from=analysis_date_from,
            analysis_date_to=analysis_date_to,
            days=None,
            offset=offset,
            limit=limit,
        )
        items = []
        for result, stock_name, trend_prediction, _created_at, context_snapshot, raw_result, report_type, analysis_sentiment_score in rows:
            summary = extract_market_phase_summary(context_snapshot)
            items.append(
                self._result_to_dict(
                    result,
                    stock_name,
                    trend_prediction,
                    market_phase_summary=summary,
                    market_phase=self._phase_bucket_from_summary(summary),
                    raw_result=raw_result,
                    report_type=report_type,
                    analysis_sentiment_score=analysis_sentiment_score,
                )
            )
        return {"total": total, "page": page, "limit": limit, "items": items}

    def get_summary(
        self,
        *,
        scope: str,
        code: Optional[str],
        eval_window_days: Optional[int] = None,
        analysis_date_from: Optional[date] = None,
        analysis_date_to: Optional[date] = None,
        analysis_phase: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        config = get_config()
        engine_version = str(getattr(config, "backtest_engine_version", "v1"))
        code = self._normalize_code(code)
        lookup_code = OVERALL_SENTINEL_CODE if scope == "overall" else code

        phase_bucket = self._normalize_phase_filter(analysis_phase)
        if analysis_date_from is not None or analysis_date_to is not None or phase_bucket is not None:
            if eval_window_days is None:
                eval_window_days = self._infer_eval_window_for_query(
                    code=code,
                    engine_version=engine_version,
                    analysis_date_from=analysis_date_from,
                    analysis_date_to=analysis_date_to,
                )
            ew = int(eval_window_days) if eval_window_days is not None else None
            count = self.repo.count_results(
                code=code,
                eval_window_days=ew,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
            )
            if count > self.MAX_DYNAMIC_SUMMARY_ROWS:
                if phase_bucket is not None:
                    raise ValueError(
                        "Phase-filtered summary candidate set matches too many rows; "
                        "narrow the analysis date range, stock code, or evaluation window."
                    )
                raise ValueError("Date-filtered summary matches too many rows; narrow the analysis date range or stock code.")
            if phase_bucket is not None:
                rows_with_context = self.repo.list_results_with_context(
                    code=code,
                    eval_window_days=ew,
                    engine_version=engine_version,
                    analysis_date_from=analysis_date_from,
                    analysis_date_to=analysis_date_to,
                    limit=self.MAX_DYNAMIC_SUMMARY_ROWS + 1,
                )
                if len(rows_with_context) > self.MAX_DYNAMIC_SUMMARY_ROWS:
                    raise ValueError(
                        "Phase-filtered summary matches too many rows; narrow the analysis date range or stock code."
                    )
                filtered_pairs = [
                    (row, snapshot)
                    for row, snapshot in rows_with_context
                    if self._phase_bucket_from_snapshot(snapshot) == phase_bucket
                ]
                phase_counts = self._phase_counts_from_contexts([snapshot for _, snapshot in filtered_pairs])
                filtered_rows = [row for row, _ in filtered_pairs]
                return self._build_dynamic_summary(
                    rows=filtered_rows,
                    scope=scope,
                    code=lookup_code,
                    eval_window_days=int(eval_window_days) if eval_window_days is not None else None,
                    engine_version=engine_version,
                    max_rows=self.MAX_DYNAMIC_SUMMARY_ROWS,
                    phase_breakdown=phase_counts["phase_breakdown"],
                    raw_phase_counts=phase_counts["raw_phase_counts"],
                )
            rows = self.repo.list_results(
                code=code,
                eval_window_days=ew,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
            )
            return self._build_dynamic_summary(
                rows=rows,
                scope=scope,
                code=lookup_code,
                eval_window_days=int(eval_window_days) if eval_window_days is not None else None,
                engine_version=engine_version,
                max_rows=self.MAX_DYNAMIC_SUMMARY_ROWS,
            )

        summary = self.repo.get_summary(
            scope=scope,
            code=lookup_code,
            eval_window_days=eval_window_days,
            engine_version=engine_version,
        )
        if summary is None:
            return None
        return self._summary_to_dict(summary)

    def get_global_summary(self, *, eval_window_days: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Return overall backtest metrics normalized for Agent memory consumers."""
        return self._normalize_learning_summary(
            self.get_summary(scope="overall", code=None, eval_window_days=eval_window_days)
        )

    def get_stock_summary(self, code: str, *, eval_window_days: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Return per-stock backtest metrics normalized for Agent memory consumers."""
        return self._normalize_learning_summary(
            self.get_summary(scope="stock", code=code, eval_window_days=eval_window_days)
        )

    def get_skill_summary(self, skill_id: str, *, eval_window_days: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Return skill-like summary metrics for Agent memory consumers.

        The current backtest storage layer only persists overall / per-stock rollups.
        Re-using the overall rollup here would fabricate skill-specific performance
        and mislead auto-weighting. Until real skill-tagged summaries exist, return
        ``None`` so downstream callers fall back to neutral weighting.
        """
        return None

    def get_strategy_summary(self, strategy_id: str, *, eval_window_days: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Compatibility wrapper for legacy strategy-based callers."""
        summary = self.get_skill_summary(strategy_id, eval_window_days=eval_window_days)
        if summary is None:
            return None
        normalized = dict(summary)
        normalized["strategy_id"] = strategy_id
        return normalized

    def _infer_eval_window_for_query(
        self,
        *,
        code: Optional[str],
        engine_version: str,
        analysis_date_from: Optional[date],
        analysis_date_to: Optional[date],
    ) -> Optional[int]:
        windows = self.repo.get_distinct_eval_windows(
            code=code,
            engine_version=engine_version,
            analysis_date_from=analysis_date_from,
            analysis_date_to=analysis_date_to,
        )
        return windows[0] if windows else None

    def _get_recent_evaluations_by_phase(
        self,
        *,
        code: Optional[str],
        eval_window_days: Optional[int],
        engine_version: str,
        limit: int,
        page: int,
        analysis_date_from: Optional[date],
        analysis_date_to: Optional[date],
        phase_bucket: str,
    ) -> Dict[str, Any]:
        page_offset = max(page - 1, 0) * limit
        batch_size = max(100, min(500, limit * 4))
        sql_offset = 0
        scanned = 0
        matched_total = 0
        page_rows: List[
            Tuple[
                BacktestResult,
                Optional[str],
                Optional[str],
                Optional[Dict[str, Any]],
                str,
                Optional[str],
                Optional[str],
                Optional[int],
            ]
        ] = []

        while True:
            remaining_probe_rows = self.MAX_DYNAMIC_SUMMARY_ROWS + 1 - scanned
            if remaining_probe_rows <= 0:
                raise ValueError("Phase-filtered results match too many rows; narrow the analysis date range or stock code.")
            batch_limit = min(batch_size, remaining_probe_rows)
            batch = self.repo.get_results_with_context_batch(
                code=code,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
                analysis_date_from=analysis_date_from,
                analysis_date_to=analysis_date_to,
                days=None,
                offset=sql_offset,
                limit=batch_limit,
            )
            if not batch:
                break
            scanned += len(batch)
            if scanned > self.MAX_DYNAMIC_SUMMARY_ROWS:
                raise ValueError("Phase-filtered results match too many rows; narrow the analysis date range or stock code.")
            sql_offset += len(batch)
            for (
                result,
                stock_name,
                trend_prediction,
                _created_at,
                context_snapshot,
                raw_result,
                report_type,
                analysis_sentiment_score,
            ) in batch:
                summary = extract_market_phase_summary(context_snapshot)
                bucket = self._phase_bucket_from_summary(summary)
                if bucket != phase_bucket:
                    continue
                if matched_total >= page_offset and len(page_rows) < limit:
                    page_rows.append((result, stock_name, trend_prediction, summary, bucket, raw_result, report_type, analysis_sentiment_score))
                matched_total += 1
            if len(batch) < batch_limit:
                break

        items = [
            self._result_to_dict(
                result,
                stock_name,
                trend_prediction,
                market_phase_summary=summary,
                market_phase=bucket,
                raw_result=raw_result,
                report_type=report_type,
                analysis_sentiment_score=analysis_sentiment_score,
            )
            for result, stock_name, trend_prediction, summary, bucket, raw_result, report_type, analysis_sentiment_score in page_rows
        ]
        return {"total": matched_total, "page": page, "limit": limit, "items": items}

    @staticmethod
    def _normalize_phase_filter(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value or "").strip().lower()
        if not text or text == "all":
            return None
        allowed = {"premarket", "intraday", "postmarket", "unknown"}
        if text not in allowed:
            raise ValueError("analysis_phase must be one of premarket, intraday, postmarket, unknown")
        return text

    @staticmethod
    def _phase_bucket_from_summary(summary: Optional[Dict[str, Any]]) -> str:
        if not isinstance(summary, dict):
            return "unknown"
        return normalize_analysis_phase_bucket(summary.get("phase"))

    @classmethod
    def _phase_bucket_from_snapshot(cls, context_snapshot: Optional[str]) -> str:
        return cls._phase_bucket_from_summary(extract_market_phase_summary(context_snapshot))

    @classmethod
    def _phase_counts_from_contexts(cls, snapshots: List[Optional[str]]) -> Dict[str, Dict[str, int]]:
        phase_breakdown = {"premarket": 0, "intraday": 0, "postmarket": 0, "unknown": 0}
        raw_phase_counts: Dict[str, int] = {}
        for snapshot in snapshots:
            summary = extract_market_phase_summary(snapshot)
            raw_phase = str(summary.get("phase")) if isinstance(summary, dict) and summary.get("phase") else "unknown"
            raw_phase_counts[raw_phase] = raw_phase_counts.get(raw_phase, 0) + 1
            bucket = cls._phase_bucket_from_summary(summary)
            phase_breakdown[bucket] = phase_breakdown.get(bucket, 0) + 1
        return {"phase_breakdown": phase_breakdown, "raw_phase_counts": raw_phase_counts}

    def _resolve_analysis_date(self, analysis) -> Optional[date]:
        parsed = self.repo.parse_analysis_date_from_snapshot(analysis.context_snapshot)
        if parsed:
            return parsed
        if getattr(analysis, "created_at", None):
            return analysis.created_at.date()
        logger.warning(f"无法确定分析日期，跳过记录: {analysis.code}#{getattr(analysis, 'id', '?')}")
        return None

    def _try_fill_daily_data(self, *, code: str, analysis_date: date, eval_window_days: int) -> None:
        refill_code = self._normalize_daily_refill_code(code)
        if not refill_code:
            return

        try:
            from data_provider.base import DataFetcherManager

            # fetch a window that covers start + forward bars
            end_date = analysis_date + timedelta(days=max(eval_window_days * 2, 30))
            manager = DataFetcherManager()
            df, source = manager.get_daily_data(
                stock_code=refill_code,
                start_date=analysis_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                days=eval_window_days * 2,
            )
            if df is None or df.empty:
                return
            self.db.save_daily_data(df, code=refill_code, data_source=source)
        except Exception as exc:
            logger.warning(f"补全日线数据失败({refill_code}): {exc}")

    def _recompute_summaries(self, *, touched_codes: List[str], eval_window_days: int, engine_version: str) -> None:
        with self.db.get_session() as session:
            # overall
            overall_rows = session.execute(
                select(BacktestResult).where(
                    and_(
                        BacktestResult.eval_window_days == eval_window_days,
                        BacktestResult.engine_version == engine_version,
                    )
                )
            ).scalars().all()
            overall_data = BacktestEngine.compute_summary(
                results=overall_rows,
                scope="overall",
                code=OVERALL_SENTINEL_CODE,
                eval_window_days=eval_window_days,
                engine_version=engine_version,
            )
            overall_summary = self._build_summary_model(overall_data)
            self.repo.upsert_summary(overall_summary)

            for code in touched_codes:
                normalized_code = self._normalize_summary_code(code)
                if not normalized_code:
                    continue

                code_conditions = BacktestRepository._build_code_conditions(BacktestResult.code, normalized_code)
                rows = session.execute(
                    select(BacktestResult).where(
                        and_(
                            *code_conditions,
                            BacktestResult.eval_window_days == eval_window_days,
                            BacktestResult.engine_version == engine_version,
                        )
                    )
                ).scalars().all()
                data = BacktestEngine.compute_summary(
                    results=rows,
                    scope="stock",
                    code=normalized_code,
                    eval_window_days=eval_window_days,
                    engine_version=engine_version,
                )
                summary = self._build_summary_model(data)
                self.repo.upsert_summary(summary)

    @staticmethod
    def _build_summary_model(summary_data: Dict[str, Any]) -> BacktestSummary:
        return BacktestSummary(
            scope=summary_data.get("scope"),
            code=summary_data.get("code"),
            eval_window_days=summary_data.get("eval_window_days"),
            engine_version=summary_data.get("engine_version"),
            computed_at=datetime.now(),
            total_evaluations=summary_data.get("total_evaluations") or 0,
            completed_count=summary_data.get("completed_count") or 0,
            insufficient_count=summary_data.get("insufficient_count") or 0,
            long_count=summary_data.get("long_count") or 0,
            cash_count=summary_data.get("cash_count") or 0,
            win_count=summary_data.get("win_count") or 0,
            loss_count=summary_data.get("loss_count") or 0,
            neutral_count=summary_data.get("neutral_count") or 0,
            direction_accuracy_pct=summary_data.get("direction_accuracy_pct"),
            win_rate_pct=summary_data.get("win_rate_pct"),
            neutral_rate_pct=summary_data.get("neutral_rate_pct"),
            avg_stock_return_pct=summary_data.get("avg_stock_return_pct"),
            avg_simulated_return_pct=summary_data.get("avg_simulated_return_pct"),
            stop_loss_trigger_rate=summary_data.get("stop_loss_trigger_rate"),
            take_profit_trigger_rate=summary_data.get("take_profit_trigger_rate"),
            ambiguous_rate=summary_data.get("ambiguous_rate"),
            avg_days_to_first_hit=summary_data.get("avg_days_to_first_hit"),
            advice_breakdown_json=json.dumps(summary_data.get("advice_breakdown") or {}, ensure_ascii=False),
            diagnostics_json=json.dumps(summary_data.get("diagnostics") or {}, ensure_ascii=False),
        )

    @staticmethod
    def _result_to_dict(
        row: BacktestResult,
        stock_name: Optional[str] = None,
        trend_prediction: Optional[str] = None,
        market_phase_summary: Optional[Dict[str, Any]] = None,
        market_phase: Optional[str] = None,
        raw_result: Optional[Any] = None,
        report_type: Optional[str] = None,
        analysis_sentiment_score: Optional[int] = None,
    ) -> Dict[str, Any]:
        parsed_raw_result = parse_json_field(raw_result)
        raw = parsed_raw_result if isinstance(parsed_raw_result, dict) else {}
        action_fields = build_action_fields(
            operation_advice=raw.get("operation_advice") or row.operation_advice,
            explicit_action=raw.get("action"),
            report_type=report_type or ("market_review" if row.code == "market_review" else None),
            report_language=raw.get("report_language"),
            sentiment_score=(
                raw.get("sentiment_score")
                if raw.get("sentiment_score") is not None
                else analysis_sentiment_score
            ),
            guardrail_reason=raw.get("guardrail_reason") or raw.get("downgrade_reason"),
            align_with_score=True,
        )
        return {
            "analysis_history_id": row.analysis_history_id,
            "code": row.code,
            "stock_name": stock_name,
            "analysis_date": row.analysis_date.isoformat() if row.analysis_date else None,
            "eval_window_days": row.eval_window_days,
            "engine_version": row.engine_version,
            "eval_status": row.eval_status,
            "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
            "operation_advice": row.operation_advice,
            "action": action_fields["action"],
            "action_label": action_fields["action_label"],
            "trend_prediction": trend_prediction,
            "market_phase": market_phase,
            "market_phase_summary": market_phase_summary,
            "position_recommendation": row.position_recommendation,
            "start_price": row.start_price,
            "end_close": row.end_close,
            "max_high": row.max_high,
            "min_low": row.min_low,
            "stock_return_pct": row.stock_return_pct,
            "actual_return_pct": row.stock_return_pct,
            "actual_movement": BacktestService._actual_movement_from_return(row.stock_return_pct),
            "direction_expected": row.direction_expected,
            "direction_correct": row.direction_correct,
            "outcome": row.outcome,
            "stop_loss": row.stop_loss,
            "take_profit": row.take_profit,
            "hit_stop_loss": row.hit_stop_loss,
            "hit_take_profit": row.hit_take_profit,
            "first_hit": row.first_hit,
            "first_hit_date": row.first_hit_date.isoformat() if row.first_hit_date else None,
            "first_hit_trading_days": row.first_hit_trading_days,
            "simulated_entry_price": row.simulated_entry_price,
            "simulated_exit_price": row.simulated_exit_price,
            "simulated_exit_reason": row.simulated_exit_reason,
            "simulated_return_pct": row.simulated_return_pct,
        }

    @staticmethod
    def _summary_to_dict(row: BacktestSummary) -> Dict[str, Any]:
        return {
            "scope": row.scope,
            "code": None if row.code == OVERALL_SENTINEL_CODE else row.code,
            "eval_window_days": row.eval_window_days,
            "engine_version": row.engine_version,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
            "total_evaluations": row.total_evaluations,
            "completed_count": row.completed_count,
            "insufficient_count": row.insufficient_count,
            "long_count": row.long_count,
            "cash_count": row.cash_count,
            "win_count": row.win_count,
            "loss_count": row.loss_count,
            "neutral_count": row.neutral_count,
            "direction_accuracy_pct": row.direction_accuracy_pct,
            "win_rate_pct": row.win_rate_pct,
            "neutral_rate_pct": row.neutral_rate_pct,
            "avg_stock_return_pct": row.avg_stock_return_pct,
            "avg_simulated_return_pct": row.avg_simulated_return_pct,
            "stop_loss_trigger_rate": row.stop_loss_trigger_rate,
            "take_profit_trigger_rate": row.take_profit_trigger_rate,
            "ambiguous_rate": row.ambiguous_rate,
            "avg_days_to_first_hit": row.avg_days_to_first_hit,
            "advice_breakdown": json.loads(row.advice_breakdown_json) if row.advice_breakdown_json else {},
            "diagnostics": json.loads(row.diagnostics_json) if row.diagnostics_json else {},
        }

    @staticmethod
    def _normalize_learning_summary(summary: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Normalize summary metrics to the ratio-based shape expected by Agent memory."""
        if summary is None:
            return None

        normalized = dict(summary)
        normalized["win_rate"] = BacktestService._pct_to_ratio(summary.get("win_rate_pct"), default=0.5)
        normalized["direction_accuracy"] = BacktestService._pct_to_ratio(
            summary.get("direction_accuracy_pct"),
            default=0.5,
        )

        avg_return_pct = summary.get("avg_simulated_return_pct")
        if avg_return_pct is None:
            avg_return_pct = summary.get("avg_stock_return_pct")
        normalized["avg_return"] = BacktestService._pct_to_ratio(avg_return_pct, default=0.0)
        return normalized

    @staticmethod
    def _pct_to_ratio(value: Optional[float], default: float = 0.0) -> float:
        try:
            return float(value) / 100.0
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _actual_movement_from_return(value: Optional[float]) -> Optional[str]:
        if value is None:
            return None
        try:
            actual_return = float(value)
        except (TypeError, ValueError):
            return None
        if actual_return > 0:
            return "up"
        if actual_return < 0:
            return "down"
        return "flat"

    @staticmethod
    def _build_dynamic_summary(
        *,
        rows: List[BacktestResult],
        scope: str,
        code: Optional[str],
        eval_window_days: Optional[int],
        engine_version: str,
        max_rows: Optional[int] = None,
        phase_breakdown: Optional[Dict[str, int]] = None,
        raw_phase_counts: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        filtered_rows = [row for row in rows if getattr(row, "engine_version", None) == engine_version]
        if eval_window_days is not None:
            summary_window_days = int(eval_window_days)
        else:
            window_values = sorted({
                int(row.eval_window_days)
                for row in filtered_rows
                if getattr(row, "eval_window_days", None) is not None
            })
            if len(window_values) > 1:
                logger.warning(
                    "Multiple eval_window_days values found for dynamic summary; using %s for engine_version=%s, scope=%s, code=%s",
                    window_values[0],
                    engine_version,
                    scope,
                    code,
                )
            if window_values:
                summary_window_days = window_values[0]
            else:
                summary_window_days = int(getattr(get_config(), "backtest_eval_window_days", 10))

        filtered_rows = [
            row for row in filtered_rows if getattr(row, "eval_window_days", None) == summary_window_days
        ]

        if max_rows is not None and len(filtered_rows) > max_rows:
            raise ValueError(
                "Date-filtered summary matches too many rows; narrow the analysis date range or stock code."
            )

        summary = BacktestEngine.compute_summary(
            results=filtered_rows,
            scope=scope,
            code=code,
            eval_window_days=summary_window_days,
            engine_version=engine_version,
        )
        diagnostics = summary.get("diagnostics")
        if not isinstance(diagnostics, dict):
            diagnostics = {}
        if phase_breakdown is not None:
            diagnostics["phase_breakdown"] = phase_breakdown
        if raw_phase_counts is not None:
            diagnostics["raw_phase_counts"] = raw_phase_counts
        summary["diagnostics"] = diagnostics
        summary["code"] = None if summary.get("code") == OVERALL_SENTINEL_CODE else summary.get("code")
        summary["computed_at"] = datetime.now().isoformat()
        return summary
