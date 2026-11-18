# -*- coding: utf-8 -*-
"""消息面汇总 · 门面服务（issue #2184）。

``run_news_digest_once``：enabled → 窗口判定 → claim-first → 资讯池采集
（published_at 口径，OR-COR-e5070d9a）→ 模板摘要 → 推送；永不向上抛。
claim（OR-COR-4c0e3220/e2e5dd13/860c1e1a）：同日至多一次由持久化 claim 保证，
失败释放待补发；OR-COR-7f5b2d19（历史重复落库）v2 不写分析历史——结构性
消除；依赖组装（OR-COR-000c926a）供 CLI 注入真实服务。搜索腿/LLM/EN/调度
挂载为后续 PR。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.services.news_digest_render import generate_template_digest
from src.services.news_digest_sources import collect_feed_entries
from src.services.news_digest_window import (
    DEFAULT_NEWS_DIGEST_OFFDAY_WINDOW, DEFAULT_NEWS_DIGEST_PREMARKET_WINDOW,
    claim_news_digest_date, merge_entries, release_news_digest_date,
    resolve_news_digest_context,
)

logger = logging.getLogger(__name__)

DEFAULT_NEWS_DIGEST_DATABASE_PATH = "./data/stock_analysis.db"


def build_news_digest_dependencies(config: Any) -> Dict[str, Any]:
    """组装真实依赖（OR-COR-000c926a）：notifier / intelligence_service；任一失败降级 None，永不抛。"""
    deps: Dict[str, Any] = {"notifier": None, "intelligence_service": None}
    try:
        from src.core.market_review_runtime import build_market_review_runtime

        deps["notifier"] = build_market_review_runtime(config)[0]
    except Exception as exc:  # noqa: BLE001 - 通知腿构造失败降级
        logger.warning("NEWS_DIGEST notifier 构造失败（降级）: %s", exc)
    try:
        from src.services.intelligence_service import IntelligenceService

        deps["intelligence_service"] = IntelligenceService(repository=None, config=config)
    except Exception as exc:  # noqa: BLE001 - 资讯池腿构造失败降级
        logger.warning("NEWS_DIGEST intelligence_service 构造失败（降级）: %s", exc)
    return deps


def run_news_digest_once(
    config: Any,
    *,
    now: datetime,
    intelligence_service: Any = None,
    notifier: Any = None,
    no_notify: bool = False,
) -> Dict[str, Any]:
    """跑一次消息面汇总；永不向上抛，返回状态字典（含 report 全文供 CLI 打印）。"""
    region = "cn"
    date_key = now.strftime("%Y-%m-%d")

    def _res(status: str, reason: Optional[str], **extra: Any) -> Dict[str, Any]:
        return {"status": status, "reason": reason, "region": region, "date": date_key, **extra}

    if not bool(getattr(config, "news_digest_enabled", False)):
        logger.info("NEWS_DIGEST 未启用，跳过")
        return _res("skipped", "disabled")

    pre = str(getattr(config, "news_digest_premarket_window", "") or DEFAULT_NEWS_DIGEST_PREMARKET_WINDOW)
    off = str(getattr(config, "news_digest_offday_window", "") or DEFAULT_NEWS_DIGEST_OFFDAY_WINDOW)
    context = resolve_news_digest_context(now, region=region, premarket_window=pre, offday_window=off)
    if context is None:
        logger.info("NEWS_DIGEST 当前不在汇总窗口，跳过")
        return _res("skipped", "outside_window")

    if no_notify:
        # --no-notify 契约（OR-COR-940607c8）：明确禁止推送时绝不发送，也
        # 不占用当日 claim；仅生成摘要供 CLI 本地查看。
        logger.info("NEWS_DIGEST --no-notify：仅生成摘要，不推送、不占用当日名额")
        max_news = max(1, min(int(getattr(config, "news_digest_max_news", 12) or 12), 30))
        feed_entries, feed_ok, fallback_count = collect_feed_entries(intelligence_service, now=now)
        entries = merge_entries(feed_entries, limit=max_news)
        report = generate_template_digest(
            entries, context, now=now, feed_count=len(feed_entries), fallback_count=fallback_count,
        )
        return _res(
            "success", "no_notify", context=context.kind, entries_count=len(entries),
            feed_ok=feed_ok, fallback_count=fallback_count, notified=False, report=report,
        )

    database_path = Path(getattr(config, "database_path", DEFAULT_NEWS_DIGEST_DATABASE_PATH))
    try:
        acquired = claim_news_digest_date(database_path, date_key, region, context.kind)
    except Exception as exc:  # noqa: BLE001 - claim 失败宁可不出也不重复推送
        logger.error("NEWS_DIGEST claim 失败，本次不出汇总: %s", exc)
        return _res("failed", "claim_error", context=context.kind)
    if not acquired:
        logger.info("NEWS_DIGEST 本自然日已出汇总，跳过（claim 命中）")
        return _res("skipped", "already_claimed", context=context.kind)

    def _release_claim_safely() -> None:
        # 到达失败路径必为本运行所 claim，释放后窗口内可补发。
        try:
            release_news_digest_date(database_path, date_key, region, context.kind)
        except Exception as release_exc:  # noqa: BLE001 - release best-effort
            logger.warning("NEWS_DIGEST 释放 claim 失败: %s", release_exc)

    try:
        max_news = max(1, min(int(getattr(config, "news_digest_max_news", 12) or 12), 30))
        feed_entries, feed_ok, fallback_count = collect_feed_entries(intelligence_service, now=now)
        if not feed_ok:
            # 资讯池读取失败（OR-COR-28338a9e）：绝不把失败伪装成“空池摘要”
            # 推送并占用当日名额；释放 claim，窗口内恢复后可补发真实新闻。
            logger.error("NEWS_DIGEST 资讯池读取失败，本次不出摘要、释放 claim 待补发")
            _release_claim_safely()
            return _res(
                "failed", "feed_unavailable", context=context.kind,
                entries_count=0, feed_ok=False, fallback_count=0, notified=False, report="",
            )
        entries = merge_entries(feed_entries, limit=max_news)
        report = generate_template_digest(
            entries, context, now=now, feed_count=len(feed_entries), fallback_count=fallback_count,
        )
        if notifier is None:
            logger.warning("NEWS_DIGEST 通知服务不可用，跳过推送")
            notified = False
        else:
            notified = bool(notifier.send(
                report, email_send_to_all=True, route_type="report",
                dedup_key=f"news_digest:{region}:{date_key}",  # 第二层每日一份防线
            ))
        if not notified:
            # 发送失败视为本次出报失败：释放 claim，窗口内下一轮询可重新补发。
            logger.error("NEWS_DIGEST 通知发送失败，释放 claim 待窗口内补发: date_key=%s", date_key)
            _release_claim_safely()
        return _res(
            "success" if notified else "failed",
            None if notified else "notification_failed",
            context=context.kind, entries_count=len(entries), feed_ok=feed_ok,
            fallback_count=fallback_count, notified=notified, report=report,
        )
    except Exception as exc:  # noqa: BLE001 - 未预期异常：释放本次 claim，不上抛
        logger.error("NEWS_DIGEST 未预期异常，释放 claim 待窗口内重试: %s", exc)
        _release_claim_safely()
        return _res("failed", f"unexpected_error: {type(exc).__name__}", context=context.kind)
