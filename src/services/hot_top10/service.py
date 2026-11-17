# -*- coding: utf-8 -*-
"""Hot-top10 facade service + delivery contract (never raises).

- Marker recorded ONLY when the report actually landed: push succeeded, or
  push disabled/no-channel and the local save succeeded (OR-COR-8c2d195e).
- Marker WRITE FAILURE must not count the run as delivered nor lead to a
  same-day re-push: the day is blocked in-process, logged at ERROR (r1
  closure blocker fix — r1 swallowed the failure and re-pushed the same list).
- In-process non-reentrant mutex serializes overlapping runs (OR-9a41d2ce).
"""

import logging
import threading
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, Set, Tuple

from src.services.hot_top10 import analysis as _analysis
from src.services.hot_top10.datasource import collect_hot_list_items, is_cn_trading_day_today
from src.services.hot_top10.idempotency import (
    hot_top10_already_delivered_today,
    record_hot_top10_marker,
)

logger = logging.getLogger(__name__)

DEFAULT_HOT_TOP10_COUNT = 10
MAX_HOT_TOP10_COUNT = 30
LLM_MAX_TOKENS = 3000
LLM_TEMPERATURE = 0.3

_RUN_MUTEX = threading.Lock()
_MARKER_WRITE_FAILED_DAYS: Set[str] = set()  # marker-write-failed days


@dataclass
class HotTop10RunResult:
    """Outcome of one hot-top10 run (never raises)."""

    delivered: bool
    skipped: bool
    reason: str
    report_markdown: Optional[str] = None
    llm_completed: bool = False
    notification_status: str = "not_attempted"


def _deliver(report_markdown: str, send_notification: bool, notifier: Any = None) -> Tuple[str, bool]:
    """Save + push; returns ``(status, report_saved)``, no raise."""
    try:
        if notifier is None:
            from src.notification import NotificationService

            notifier = NotificationService()
    except Exception as exc:
        logger.warning("[HotTop10] 通知服务初始化失败，报告未保存也未推送: %s", exc)
        return "notifier_init_failed", False
    report_saved = False
    try:
        path = notifier.save_report_to_file(
            report_markdown, f"hot_top10_{date.today().strftime('%Y%m%d')}.md"
        )
        logger.info("[HotTop10] 报告已保存: %s", path)
        report_saved = True
    except Exception as exc:
        logger.error("[HotTop10] 报告保存失败（不落标记，等待重试）: %s", exc)
    if not send_notification:
        logger.info("[HotTop10] 通知推送已禁用（--no-notify）")
        return "disabled", report_saved
    try:
        if not notifier.is_available():
            logger.info("[HotTop10] 未配置通知渠道，跳过推送（报告仅落盘）")
            return "no_channel", report_saved
        if notifier.send(report_markdown, route_type="report"):
            logger.info("[HotTop10] 通知推送成功")
            return "sent", report_saved
        logger.warning("[HotTop10] 通知推送失败")
        return "failed", report_saved
    except Exception as exc:
        logger.warning("[HotTop10] 通知推送异常: %s", exc)
        return "failed", report_saved


def run_hot_top10_analysis(
    config: Any,
    *,
    send_notification: bool = True,
    notifier: Any = None,
    analyzer: Any = None,
    hotspot_service: Any = None,
    respect_dedup: bool = True,
    force_run: bool = False,
) -> HotTop10RunResult:
    """One hot-top10 run; serialized in-process, deduped per day."""
    today = date.today().isoformat()
    try:
        count = max(1, min(MAX_HOT_TOP10_COUNT, int(getattr(config, "hot_top10_count", DEFAULT_HOT_TOP10_COUNT))))
    except (TypeError, ValueError):
        count = DEFAULT_HOT_TOP10_COUNT
    if not force_run and today in _MARKER_WRITE_FAILED_DAYS:
        return HotTop10RunResult(False, True, "marker_write_failed_blocked_today")
    if respect_dedup and not force_run:
        skip, reason = hot_top10_already_delivered_today(config)
        if skip:
            logger.info("[HotTop10] 当日报告已投递，跳过: %s", reason)
            return HotTop10RunResult(False, True, f"already_delivered_today: {reason}")
    if not force_run and getattr(config, "trading_day_check_enabled", True) and not is_cn_trading_day_today():
        logger.info("[HotTop10] 今日 A 股非交易日，跳过热榜分析")
        return HotTop10RunResult(False, True, "non_trading_day")
    if not _RUN_MUTEX.acquire(blocking=False):
        logger.warning("[HotTop10] 上一轮热榜分析仍在执行，本次触发跳过")
        return HotTop10RunResult(False, True, "already_running")

    try:
        items = collect_hot_list_items(count, hotspot_service=hotspot_service)
        if not items:
            logger.warning("[HotTop10] 热榜数据获取失败，本轮不生成报告")
            return HotTop10RunResult(False, True, "hotspot_data_unavailable")

        summary = None
        try:
            if analyzer is None:
                analyzer = _analysis.build_analyzer(config)
            summary = _analysis.parse_llm_summary(
                analyzer.generate_text(
                    _analysis.build_hot_top10_prompt(items),
                    max_tokens=LLM_MAX_TOKENS,
                    temperature=LLM_TEMPERATURE,
                )
            )
            if summary is None:
                logger.warning("[HotTop10] AI 摘要生成/解析失败，降级为数据概览")
        except Exception as exc:
            logger.warning("[HotTop10] AI 摘要生成异常，降级为数据概览: %s", exc)
        llm_completed = summary is not None

        report_markdown = _analysis.render_hot_top10_report(items, summary, llm_completed)
        notification_status, report_saved = _deliver(report_markdown, send_notification, notifier)
        delivered_result = report_saved or notification_status == "sent"
        marker_required = notification_status == "sent" or (
            notification_status in {"disabled", "no_channel"} and report_saved
        )
        if marker_required:
            # Idempotency fix: marker write failure -> not delivered + same-day
            # re-push blocked (the r1 code swallowed the failure and re-pushed).
            if not record_hot_top10_marker(
                config, llm_completed=llm_completed, notification_status=notification_status
            ):
                _MARKER_WRITE_FAILED_DAYS.add(today)
                return HotTop10RunResult(
                    False, True, "marker_write_failed", report_markdown,
                    llm_completed, notification_status,
                )
        elif notification_status in {"failed", "notifier_init_failed"} or not report_saved:
            logger.warning(
                "[HotTop10] 交付未成功（status=%s saved=%s），不记录当日标记，等待重试",
                notification_status, report_saved,
            )
        return HotTop10RunResult(
            delivered_result,
            False,
            "ok" if delivered_result else f"delivery_failed: {notification_status}",
            report_markdown, llm_completed, notification_status,
        )
    finally:
        _RUN_MUTEX.release()
