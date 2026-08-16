"""Adapter from intraday candidates to the existing DSA task queue."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence

from src.services.task_queue import TaskStatus, get_task_queue

from ..config import IntradayPickerConfig
from ..models import DsaAnalysisSummary, IntradayCandidate


class DsaTaskQueueAdapter:
    def __init__(self, config: IntradayPickerConfig):
        self.config = config
        self.queue = get_task_queue()
        self._task_by_code: dict[str, tuple[str, datetime]] = {}

    def _fresh_ref(self, code: str, now: datetime) -> str | None:
        cached = self._task_by_code.get(code)
        if cached is None:
            return None
        task_id, submitted_at = cached
        if now - submitted_at > timedelta(minutes=self.config.dsa_cache_minutes):
            return None
        task = self.queue.get_task(task_id)
        if task is None:
            return None
        if task.status in {TaskStatus.PENDING, TaskStatus.PROCESSING, TaskStatus.COMPLETED}:
            return task_id
        return None

    def submit_or_reuse(self, candidates: Sequence[IntradayCandidate], now: datetime) -> dict[str, str]:
        refs: dict[str, str] = {}
        new_codes: list[str] = []
        for candidate in candidates:
            task_id = self._fresh_ref(candidate.stock_code, now)
            if task_id:
                refs[candidate.stock_code] = task_id
            else:
                new_codes.append(candidate.stock_code)

        if new_codes:
            accepted, duplicates = self.queue.submit_tasks_batch(
                stock_codes=new_codes,
                query_source="intraday_picker",
                report_type=self.config.dsa_report_type,
                analysis_phase="intraday",
                force_refresh=False,
                notify=False,
            )
            for task in accepted:
                refs[task.stock_code] = task.task_id
                self._task_by_code[task.stock_code] = (task.task_id, now)
            for duplicate in duplicates:
                refs[duplicate.stock_code] = duplicate.existing_task_id
                self._task_by_code[duplicate.stock_code] = (duplicate.existing_task_id, now)
        return refs

    @staticmethod
    def _summary(task) -> DsaAnalysisSummary:
        result = task.result if isinstance(task.result, dict) else {}
        report = result.get("report") if isinstance(result.get("report"), dict) else {}
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        details = report.get("details") if isinstance(report.get("details"), dict) else {}
        raw_score = summary.get("sentiment_score")
        try:
            score = float(raw_score) if raw_score is not None else None
        except (TypeError, ValueError):
            score = None
        risk = details.get("risk_warning")
        risk_level = "有风险提示" if risk else None
        return DsaAnalysisSummary(
            stock_code=task.stock_code,
            status=task.status.value if hasattr(task.status, "value") else str(task.status),
            dsa_score=score,
            operation_advice=summary.get("operation_advice"),
            risk_level=risk_level,
            summary=summary.get("analysis_summary"),
            task_id=task.task_id,
        )

    def collect_available(self, candidates: Sequence[IntradayCandidate], now: datetime) -> dict[str, DsaAnalysisSummary]:
        output: dict[str, DsaAnalysisSummary] = {}
        for candidate in candidates:
            task_id = self._fresh_ref(candidate.stock_code, now)
            if not task_id:
                continue
            task = self.queue.get_task(task_id)
            if task is None:
                continue
            output[candidate.stock_code] = self._summary(task)
        return output
