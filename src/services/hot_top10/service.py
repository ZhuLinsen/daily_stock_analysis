# -*- coding: utf-8 -*-
"""Hot-top10 facade service + delivery contract (never raises).

- All day keying (schedule gate, dedup marker, report file names) uses the
  CN market clock (Asia/Shanghai) via ``hot_top10_data_date()`` — never the
  host clock (OR-COR-3e7f490e).
- Marker recorded ONLY when the report actually landed: push succeeded, or
  push disabled/no-channel and the local save succeeded (OR-COR-8c2d195e).
- Marker WRITE FAILURE must not count the run as delivered nor lead to a
  same-day re-push: the day is blocked in-process, logged at ERROR (r1
  closure blocker fix — r1 swallowed the failure and re-pushed the same list).
- In-process non-reentrant mutex serializes overlapping runs (OR-9a41d2ce);
  the same-day gate (delivered marker / marker-write-failure block) is
  RE-checked inside the critical section, because the pre-lock pass can go
  stale while a peer run completes delivery (OR-COR-a8bfa126,
  double-checked locking).
"""

import logging
import threading
from dataclasses import dataclass
from typing import Any, Optional, Set, Tuple

from src.services.hot_top10 import analysis as _analysis
from src.services.hot_top10.datasource import (
    collect_hot_list_items,
    hot_top10_data_date,
    is_cn_trading_day_today,
    shanghai_now,
)
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


def _scheduled_report_filename() -> str:
    """Canonical per-day report file name, keyed on the CN market data date
    (OR-COR-3e7f490e) — not the host-local date."""
    return f"hot_top10_{shanghai_now().strftime('%Y%m%d')}.md"


def _manual_report_filename() -> str:
    """Distinct file name for dedup-exempt manual runs (OR-COR-hot-top10-
    report-overwrite): a same-day manual rerun must never replace the
    delivered scheduled report file the marker still points at."""
    now = shanghai_now()
    return f"hot_top10_{now.strftime('%Y%m%d')}_manual_{now.strftime('%H%M%S')}.md"


def _deliver(
    report_markdown: str,
    send_notification: bool,
    notifier: Any = None,
    report_filename: Optional[str] = None,
) -> Tuple[str, bool]:
    """Save + push; returns ``(status, report_saved)``, no raise.

    ``report_filename`` is also passed to ``notifier.send`` so file-based
    channels (Feishu file mode) upload under the hot-top10's own file name
    instead of rewriting the shared ``report_YYYYMMDD.md`` daily-report path
    (OR-COR-hot-top10-feishu-report-overwrite).
    """
    try:
        if notifier is None:
            from src.notification import NotificationService

            notifier = NotificationService()
    except Exception as exc:
        logger.warning("[HotTop10] 通知服务初始化失败，报告未保存也未推送: %s", exc)
        return "notifier_init_failed", False
    if report_filename is None:
        report_filename = _scheduled_report_filename()
    report_saved = False
    try:
        path = notifier.save_report_to_file(report_markdown, report_filename)
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
        if notifier.send(report_markdown, route_type="report", report_filename=report_filename):
            logger.info("[HotTop10] 通知推送成功")
            return "sent", report_saved
        logger.warning("[HotTop10] 通知推送失败")
        return "failed", report_saved
    except Exception as exc:
        logger.warning("[HotTop10] 通知推送异常: %s", exc)
        return "failed", report_saved


def _same_day_gate_reason(
    config: Any, *, respect_dedup: bool, force_run: bool, today: str
) -> Optional[str]:
    """Same-day suppression reason (``None`` when the run may proceed):
    marker-write-failure block, then the delivered marker. Pure state read —
    safe to call both before and inside the run mutex. Manual one-shot runs
    (``respect_dedup=False``) are exempt: they neither read nor consume the
    same-day dedup state (OR-COR-ca43b57a)."""
    if force_run or not respect_dedup:
        return None
    if today in _MARKER_WRITE_FAILED_DAYS:
        return "marker_write_failed_blocked_today"
    skip, reason = hot_top10_already_delivered_today(config)
    if skip:
        return f"already_delivered_today: {reason}"
    return None


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
    today = hot_top10_data_date()  # CN market data date, never the host clock
    try:
        count = max(1, min(MAX_HOT_TOP10_COUNT, int(getattr(config, "hot_top10_count", DEFAULT_HOT_TOP10_COUNT))))
    except (TypeError, ValueError):
        count = DEFAULT_HOT_TOP10_COUNT
    # Fast-path gate: skip without contending the run mutex. NOT authoritative:
    # a peer run may complete delivery between this pass and the critical
    # section, so the identical gate is re-checked inside the lock
    # (OR-COR-a8bfa126, double-checked locking).
    gate_reason = _same_day_gate_reason(
        config, respect_dedup=respect_dedup, force_run=force_run, today=today
    )
    if gate_reason is not None:
        logger.info("[HotTop10] 当日门禁命中，跳过: %s", gate_reason)
        return HotTop10RunResult(False, True, gate_reason)
    if not force_run and getattr(config, "trading_day_check_enabled", True) and not is_cn_trading_day_today():
        logger.info("[HotTop10] 今日 A 股非交易日，跳过热榜分析")
        return HotTop10RunResult(False, True, "non_trading_day")
    if not _RUN_MUTEX.acquire(blocking=False):
        logger.warning("[HotTop10] 上一轮热榜分析仍在执行，本次触发跳过")
        return HotTop10RunResult(False, True, "already_running")

    try:
        # Authoritative re-check inside the mutex (OR-COR-a8bfa126): the
        # pre-lock pass above may be stale — a peer run can have written the
        # delivered marker or registered a marker-write failure in between.
        gate_reason = _same_day_gate_reason(
            config, respect_dedup=respect_dedup, force_run=force_run, today=today
        )
        if gate_reason is not None:
            logger.info("[HotTop10] 锁内复查命中当日门禁，跳过: %s", gate_reason)
            return HotTop10RunResult(False, True, gate_reason)
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
        # Scheduled (dedup-honoring) runs use the canonical per-day file name;
        # manual one-shot runs save under a distinct stamped name so they can
        # never overwrite the delivered scheduled report file
        # (OR-COR-hot-top10-report-overwrite).
        report_filename = None if respect_dedup else _manual_report_filename()
        notification_status, report_saved = _deliver(
            report_markdown, send_notification, notifier, report_filename
        )
        delivered_result = report_saved or notification_status == "sent"
        # Manual one-shot runs (respect_dedup=False) are dedup-exempt on READ
        # and stay exempt on WRITE (OR-COR-ca43b57a): recording today's marker
        # here would consume the scheduled end-of-day run's dedup quota while
        # the intraday provider data may still belong to the previous trading
        # day. Only dedup-honoring (scheduled) runs record the marker.
        marker_required = respect_dedup and (
            notification_status == "sent"
            or (notification_status in {"disabled", "no_channel"} and report_saved)
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
