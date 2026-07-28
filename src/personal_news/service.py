"""Single-process orchestration for polling, scoring, analysis, and push."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from src.personal_news.repository import PersonalNewsRepository, article_hashes
from src.personal_news.schemas import NewsAnalysis, NewsCandidate, NewsRadarSettings
from src.personal_news.scoring import score_importance

logger = logging.getLogger(__name__)


class PersonalNewsMonitor:
    def __init__(
        self,
        *,
        settings: NewsRadarSettings,
        sources: Iterable[Any],
        repository: Optional[PersonalNewsRepository] = None,
        analyzer: Optional[Any] = None,
        notifier: Optional[Any] = None,
    ):
        self.settings = settings
        self.sources = list(sources)
        self.repository = repository or PersonalNewsRepository()
        self.analyzer = analyzer
        self.notifier = notifier
        self._run_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._refresh_thread: Optional[threading.Thread] = None
        self._refresh_status: dict[str, Any] = {
            "status": "completed",
            "last_refresh_at": self.repository.get_setting("last_scan_at"),
            "next_allowed_refresh_at": None,
            "error": None,
            "stats": None,
            "new_article_ids": [],
        }
        self.repository.sync_settings(settings)

    def run_once(
        self,
        *,
        trigger: str = "manual",
        symbols: Optional[Iterable[str]] = None,
    ) -> dict[str, Any]:
        stats = {"fetched": 0, "new": 0, "duplicate": 0, "analyzed": 0, "pushed": 0, "errors": 0}
        if not self._run_lock.acquire(blocking=False):
            logger.warning("personal_news_run_skipped reason=reentrant")
            return {**stats, "skipped": 1}
        try:
            active_symbols = list(symbols or self.repository.get_watchlist_symbols())
            self.settings.watchlist = active_symbols
            if not active_symbols:
                scan_time = datetime.now(timezone.utc)
                self.repository.set_setting("last_scan_at", scan_time.isoformat())
                return {**stats, "new_article_ids": [], "message": "watchlist_empty"}

            candidates = self._fetch_candidates(stats)
            new_items: list[tuple[int, NewsCandidate, int]] = []
            for candidate in self._merge_candidates(candidates):
                article_id, created = self.repository.ingest(candidate)
                if not created:
                    stats["duplicate"] += 1
                    continue
                stats["new"] += 1
                score, reasons = score_importance(candidate, self.settings.watchlist)
                self.repository.set_score(article_id, score, reasons)
                new_items.append((article_id, candidate, score))

            scan_time = datetime.now(timezone.utc)
            self.repository.set_setting("last_scan_at", scan_time.isoformat())
            analyzed_items: list[tuple[int, NewsCandidate, int, NewsAnalysis]] = []
            eligible = sorted(
                (item for item in new_items if item[2] >= self.settings.min_analysis_score),
                key=lambda item: item[2],
                reverse=True,
            )[: self.settings.max_ai_items_per_run]
            for article_id, candidate, score in eligible:
                if self.analyzer is None:
                    break
                try:
                    analysis = self.analyzer.analyze(candidate, data_time=scan_time)
                    self.repository.save_analysis(
                        article_id,
                        analysis,
                        provider=getattr(self.analyzer, "provider_name", "unknown"),
                        model=getattr(self.analyzer, "model", ""),
                    )
                    self.repository.set_provider_status(
                        getattr(self.analyzer, "provider_name", "llm"), "llm", "ok", "structured response validated"
                    )
                    stats["analyzed"] += 1
                    analyzed_items.append((article_id, candidate, score, analysis))
                except Exception as exc:
                    stats["errors"] += 1
                    error_name = type(exc).__name__
                    self.repository.save_analysis_error(article_id, error_name)
                    self.repository.set_provider_status(
                        getattr(self.analyzer, "provider_name", "llm"), "llm", "error", error_name
                    )
                    logger.exception("personal_news_analysis_failed article_id=%s", article_id)
            important_items = [item for item in analyzed_items if item[2] >= self.settings.min_push_score]
            if important_items:
                stats["pushed"] = self._push_digest(important_items, scan_time=scan_time)
            result = {**stats, "new_article_ids": [item[0] for item in new_items], "trigger": trigger}
            logger.info("personal_news_run_complete trigger=%s stats=%s", trigger, stats)
            return result
        finally:
            self._run_lock.release()

    def run_forever(self, stop_event: Optional[threading.Event] = None) -> None:
        """Run at 08:00 and 20:00 Asia/Shanghai without an initial scan."""
        del stop_event  # Existing Scheduler owns graceful SIGINT/SIGTERM handling.
        from src.scheduler import Scheduler

        scheduler = Scheduler(
            schedule_time="08:00",
            schedule_times=["08:00", "20:00"],
            timezone_name=self.settings.app_timezone,
        )
        scheduler.set_daily_task(lambda: self.run_once(trigger="schedule"), run_immediately=False)
        scheduler.run()

    def request_refresh(
        self,
        *,
        trigger: str = "manual",
        symbols: Optional[Iterable[str]] = None,
        force: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with self._status_lock:
            if self._run_lock.locked() or (self._refresh_thread and self._refresh_thread.is_alive()):
                self._refresh_status["status"] = "running"
                return dict(self._refresh_status)
            last_refresh = self._parse_timestamp(self.repository.get_setting("last_scan_at"))
            next_allowed = (
                last_refresh + timedelta(minutes=self.settings.open_refresh_cooldown_minutes)
                if last_refresh is not None
                else None
            )
            if not force and next_allowed is not None and now < next_allowed:
                self._refresh_status.update({
                    "status": "cooldown",
                    "last_refresh_at": last_refresh.isoformat(),
                    "next_allowed_refresh_at": next_allowed.isoformat(),
                    "error": None,
                })
                return dict(self._refresh_status)
            self._refresh_status.update({
                "status": "started",
                "next_allowed_refresh_at": (now + timedelta(minutes=self.settings.open_refresh_cooldown_minutes)).isoformat(),
                "error": None,
                "stats": None,
                "new_article_ids": [],
            })

            def worker() -> None:
                with self._status_lock:
                    self._refresh_status["status"] = "running"
                try:
                    result = self.run_once(trigger=trigger, symbols=symbols)
                    last_scan = self.repository.get_setting("last_scan_at")
                    with self._status_lock:
                        self._refresh_status.update({
                            "status": "completed",
                            "last_refresh_at": last_scan,
                            "next_allowed_refresh_at": (
                                self._parse_timestamp(last_scan)
                                + timedelta(minutes=self.settings.open_refresh_cooldown_minutes)
                            ).isoformat() if last_scan else None,
                            "stats": result,
                            "new_article_ids": result.get("new_article_ids", []),
                        })
                except Exception as exc:
                    logger.exception("personal_news_refresh_failed trigger=%s", trigger)
                    with self._status_lock:
                        self._refresh_status.update({"status": "failed", "error": type(exc).__name__})

            self._refresh_thread = threading.Thread(target=worker, daemon=True, name="personal-news-refresh")
            self._refresh_thread.start()
            return dict(self._refresh_status)

    def refresh_status(self) -> dict[str, Any]:
        with self._status_lock:
            if self._refresh_thread and self._refresh_thread.is_alive():
                self._refresh_status["status"] = "running"
            elif self._refresh_status["status"] == "running" and not self._run_lock.locked():
                last_scan = self.repository.get_setting("last_scan_at")
                self._refresh_status.update({
                    "status": "completed",
                    "last_refresh_at": last_scan,
                    "error": None,
                })
            return dict(self._refresh_status)

    def _fetch_candidates(self, stats: dict[str, int]) -> list[NewsCandidate]:
        candidates: list[NewsCandidate] = []
        for source in self.sources:
            name = getattr(source, "name", source.__class__.__name__)
            try:
                batch = [item if isinstance(item, NewsCandidate) else NewsCandidate.model_validate(item) for item in source.fetch(self.settings)]
                candidates.extend(batch)
                stats["fetched"] += len(batch)
                self.repository.set_provider_status(name, "news", "ok", f"fetched {len(batch)}")
            except Exception as exc:
                stats["errors"] += 1
                self.repository.set_provider_status(name, "news", "error", type(exc).__name__)
                logger.exception("personal_news_source_failed source=%s", name)
        return candidates

    @staticmethod
    def _merge_candidates(candidates: Iterable[NewsCandidate]) -> list[NewsCandidate]:
        merged: dict[str, NewsCandidate] = {}
        sources: dict[str, set[str]] = {}
        for candidate in candidates:
            event_key = article_hashes(candidate)["event"]
            if event_key not in merged:
                merged[event_key] = candidate.model_copy(deep=True)
                sources[event_key] = {candidate.source}
                continue
            current = merged[event_key]
            sources[event_key].add(candidate.source)
            current.source_count = max(current.source_count, len(sources[event_key]), candidate.source_count)
            current.symbols = list(dict.fromkeys([*current.symbols, *candidate.symbols]))
            current.is_announcement = current.is_announcement or candidate.is_announcement
            current.is_regulatory = current.is_regulatory or candidate.is_regulatory
            current.source_reliability = max(current.source_reliability, candidate.source_reliability)
            if len(candidate.summary) > len(current.summary):
                current.summary = candidate.summary
        return list(merged.values())

    def _push_digest(
        self,
        items: list[tuple[int, NewsCandidate, int, NewsAnalysis]],
        *,
        scan_time: datetime,
    ) -> int:
        if self.notifier is None:
            return 0
        channels = list(self.notifier.channels())
        if not channels:
            return 0
        channel = "feishu" if "feishu" in channels else channels[0]
        article_ids = sorted(item[0] for item in items)
        digest_id = self._digest_id(article_ids, channel)
        content = self._format_digest(items, scan_time=scan_time)
        digest = self.repository.reserve_digest(
            digest_id=digest_id,
            article_ids=article_ids,
            content=content,
            channel=channel,
        )
        if digest["status"] == "sent":
            return 0
        return self._send_reserved_digest(digest)

    def _send_reserved_digest(self, digest: dict[str, Any]) -> int:
        try:
            success = bool(self.notifier.send(digest["channel"], digest["content"]))
            self.repository.record_digest_result(
                digest["digest_id"], success=success, error="provider returned false"
            )
            for article_id in digest["article_ids"]:
                self.repository.record_push(
                    article_id,
                    digest["channel"],
                    success=success,
                    error="digest push failed",
                )
            if success:
                self.repository.set_setting("last_push_at", datetime.now(timezone.utc).isoformat())
            self.repository.set_provider_status(digest["channel"], "push", "ok" if success else "error")
            return int(success)
        except Exception as exc:
            error_name = type(exc).__name__
            self.repository.record_digest_result(digest["digest_id"], success=False, error=error_name)
            self.repository.set_provider_status(digest["channel"], "push", "error", error_name)
            logger.exception("personal_news_digest_push_failed digest_id=%s", digest["digest_id"])
            return 0

    def _format_digest(
        self,
        items: list[tuple[int, NewsCandidate, int, NewsAnalysis]],
        *,
        scan_time: datetime,
    ) -> str:
        from src.data.stock_index_loader import get_index_stock_name

        action_labels = {
            "WATCH_NOW": "重点关注",
            "WAIT_FOR_CONFIRMATION": "等待确认",
            "RISK_ALERT": "风险预警",
            "AVOID_CHASING": "避免追高",
            "POTENTIAL_OPPORTUNITY": "潜在机会",
            "NO_ACTION": "暂无操作",
            "INSUFFICIENT_EVIDENCE": "证据不足",
        }
        lines = [
            "【自选股 12 小时资讯】",
            "",
            f"检查时间：{scan_time.astimezone(ZoneInfo(self.settings.app_timezone)).isoformat()}",
            f"新增重要消息数量：{len(items)}",
        ]
        catalysts: list[str] = []
        risks: list[str] = []
        for index, (article_id, candidate, score, analysis) in enumerate(items, 1):
            symbol = candidate.symbols[0] if candidate.symbols else "宏观"
            name = get_index_stock_name(symbol) or symbol
            catalysts.extend(analysis.positive_factors[:1])
            risks.extend(analysis.risks[:1])
            lines.extend([
                "",
                f"{index}. {name}｜{symbol}",
                f"重要性：{score}",
                f"方向：{analysis.direction.value}",
                f"摘要：{analysis.summary}",
                f"观察策略：{action_labels[analysis.action.value]}",
                f"主要原因：{analysis.action_reason}",
                f"主要风险：{'；'.join(analysis.risks[:3])}",
                f"失效条件：{'；'.join(analysis.invalidation_conditions[:3])}",
                f"来源：{candidate.source} {candidate.url}",
            ])
            if self.settings.public_base_url:
                lines.append(f"详情：{self.settings.public_base_url}/news/{article_id}")
        lines.extend([
            "",
            "AI 综合观察：",
            f"- 当前主要催化因素：{'；'.join(dict.fromkeys(catalysts)) or '暂无明确催化'}",
            f"- 当前主要风险：{'；'.join(dict.fromkeys(risks)) or '暂无新增风险'}",
            "- 下一阶段重点关注：等待价格与成交量确认，避免依据单条消息追涨杀跌。",
        ])
        return "\n".join(lines)

    @staticmethod
    def _digest_id(article_ids: Iterable[int], channel: str) -> str:
        import hashlib

        payload = f"{channel}|{','.join(str(item) for item in sorted(article_ids))}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def build_personal_news_monitor(config: Any) -> PersonalNewsMonitor:
    from src.personal_news.providers import ExistingPushNotifier, ExistingSearchNewsSource, LiteLLMNewsAnalyzer

    settings = NewsRadarSettings.from_env()
    analyzer = None
    if config.openai_api_key and (config.litellm_model or config.openai_model):
        analyzer = LiteLLMNewsAnalyzer(config)
    return PersonalNewsMonitor(
        settings=settings,
        sources=[ExistingSearchNewsSource(config)],
        analyzer=analyzer,
        notifier=ExistingPushNotifier(config),
    )


_monitor_instance: Optional[PersonalNewsMonitor] = None
_monitor_instance_lock = threading.Lock()


def get_personal_news_monitor(config: Any = None) -> PersonalNewsMonitor:
    global _monitor_instance
    with _monitor_instance_lock:
        if _monitor_instance is None:
            if config is None:
                from src.config import get_config

                config = get_config()
            _monitor_instance = build_personal_news_monitor(config)
        return _monitor_instance


def reset_personal_news_monitor() -> None:
    global _monitor_instance
    with _monitor_instance_lock:
        _monitor_instance = None
