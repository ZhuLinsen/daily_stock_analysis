"""CLI-facing runtime for the independent US macro report."""

from __future__ import annotations

import logging
from typing import Any

from src.analyzer import AnalysisResult
from src.notification import NotificationService
from src.services.feishu_report_display import build_us_macro_feishu_messages
from src.services.us_macro_report import USMacroReport, USMacroReportService

logger = logging.getLogger(__name__)

US_MACRO_HISTORY_CODE = "US_MACRO"
US_MACRO_REPORT_TYPE = "global_macro"


def run_us_macro_report(
    *,
    config: Any,
    send_notification: bool,
    save_report_file: bool,
    trigger_source: str,
    use_ai: bool = False,
    preview_notification: bool = False,
    service: USMacroReportService | None = None,
    notifier: NotificationService | None = None,
) -> USMacroReport:
    runtime_service = service or USMacroReportService(fred_api_key=getattr(config, "fred_api_key", None))
    report = runtime_service.build_report()
    if use_ai:
        from src.analyzer import GeminiAnalyzer
        report = runtime_service.add_ai_explanation(report, GeminiAnalyzer(config=config))
    report_id = _persist_report(report)
    runtime_notifier = notifier or NotificationService()
    if save_report_file:
        runtime_notifier.save_report_to_file(report.markdown, "us_macro_report.md")
    if preview_notification:
        for index, message in enumerate(build_us_macro_notification_messages(report), start=1):
            logger.info("美国宏观飞书预览: part=%s chars=%s content=%s", index, len(message), message)
    if send_notification:
        success = runtime_notifier.send(
            report.markdown,
            email_send_to_all=True,
            route_type="report",
            dedup_key=f"us_macro:{report.snapshot.as_of.date().isoformat()}",
        )
        if not success:
            logger.error("美国宏观报告通知失败: report_id=%s trigger_source=%s", report_id, trigger_source)
    logger.info("美国宏观报告完成: report_id=%s trigger_source=%s", report_id, trigger_source)
    return report


def build_us_macro_notification_messages(report: USMacroReport) -> list[str]:
    """Render display-only US macro Feishu messages; caller decides whether to send."""
    return build_us_macro_feishu_messages(report.snapshot, report.assessment, report.ai_explanation)


def _persist_report(report: USMacroReport) -> int:
    """Reuse the versioned report history boundary until macro-specific evaluation tables land."""
    from src.storage import DatabaseManager

    result = AnalysisResult(
        code=US_MACRO_HISTORY_CODE,
        name="美国宏观基础报告",
        sentiment_score=50,
        trend_prediction=report.assessment["horizons"]["未来1周"]["direction"],
        operation_advice="观望",
        analysis_summary=f"{report.assessment['regime']}；{report.assessment['horizons']['未来1周']['confidence']}置信度",
        raw_response=report.markdown,
        data_sources="FRED,Yahoo Finance",
    )
    snapshot = {
        "report_kind": US_MACRO_REPORT_TYPE,
        "snapshot": report.snapshot.model_dump(mode="json"),
        "assessment": report.assessment,
    }
    db = DatabaseManager.get_instance()
    query_id = f"us_macro_{report.snapshot.as_of.date().isoformat()}"
    return db.upsert_us_macro_report_history(
        result=result,
        query_id=query_id,
        context_snapshot=snapshot,
    )
