"""Single-process orchestration for polling, scoring, analysis, and push."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

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
        self.repository.sync_settings(settings)

    def run_once(self) -> dict[str, int]:
        stats = {"fetched": 0, "new": 0, "duplicate": 0, "analyzed": 0, "pushed": 0, "errors": 0}
        if not self._run_lock.acquire(blocking=False):
            logger.warning("personal_news_run_skipped reason=reentrant")
            return {**stats, "skipped": 1}
        try:
            candidates = self._fetch_candidates(stats)
            for candidate in self._merge_candidates(candidates):
                article_id, created = self.repository.ingest(candidate)
                if not created:
                    stats["duplicate"] += 1
                    persisted = self.repository.get_article(article_id)
                    if (
                        persisted
                        and persisted.get("analysis")
                        and int(persisted.get("importance_score") or 0) >= self.settings.min_push_score
                    ):
                        persisted_analysis = NewsAnalysis.model_validate(persisted["analysis"])
                        stats["pushed"] += self._push(
                            article_id,
                            candidate,
                            persisted_analysis,
                            int(persisted["importance_score"]),
                        )
                    continue
                stats["new"] += 1
                score, reasons = score_importance(candidate, self.settings.watchlist)
                self.repository.set_score(article_id, score, reasons)
                if score < self.settings.min_analysis_score or self.analyzer is None:
                    continue
                try:
                    analysis = self.analyzer.analyze(candidate, data_time=datetime.now(timezone.utc))
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
                except Exception as exc:
                    stats["errors"] += 1
                    self.repository.save_analysis_error(article_id, str(exc))
                    self.repository.set_provider_status(
                        getattr(self.analyzer, "provider_name", "llm"), "llm", "error", str(exc)
                    )
                    logger.exception("personal_news_analysis_failed article_id=%s", article_id)
                    continue
                if score >= self.settings.min_push_score:
                    stats["pushed"] += self._push(article_id, candidate, analysis, score)
            logger.info("personal_news_run_complete stats=%s", stats)
            return stats
        finally:
            self._run_lock.release()

    def run_forever(self, stop_event: Optional[threading.Event] = None) -> None:
        stop = stop_event or threading.Event()
        while not stop.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("personal_news_cycle_failed")
            stop.wait(self.settings.poll_interval_minutes * 60)

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
                self.repository.set_provider_status(name, "news", "error", str(exc))
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

    def _push(self, article_id: int, candidate: NewsCandidate, analysis: NewsAnalysis, score: int) -> int:
        if self.notifier is None:
            return 0
        detail_url = f"{self.settings.public_base_url}/news/{article_id}"
        content = self._format_push(candidate, analysis, score, detail_url)
        sent = 0
        for channel in self.notifier.channels():
            if self.repository.push_succeeded(article_id, channel):
                continue
            try:
                success = bool(self.notifier.send(channel, content))
                self.repository.record_push(article_id, channel, success=success, error="provider returned false")
                self.repository.set_provider_status(channel, "push", "ok" if success else "error")
                sent += int(success)
            except Exception as exc:
                self.repository.record_push(article_id, channel, success=False, error=str(exc))
                self.repository.set_provider_status(channel, "push", "error", str(exc))
                logger.exception("personal_news_push_failed article_id=%s channel=%s", article_id, channel)
        return sent

    @staticmethod
    def _format_push(candidate: NewsCandidate, analysis: NewsAnalysis, score: int, detail_url: str) -> str:
        risks = "；".join(analysis.risks[:3]) or "暂无"
        return (
            "【重要股票新闻】\n\n"
            f"标题：{candidate.title}\n"
            f"重要性：{score}\n"
            f"涉及股票：{','.join(candidate.symbols) or '宏观'}\n"
            f"影响方向：{analysis.direction.value}\n"
            f"AI 摘要：{analysis.summary}\n"
            f"建议动作：{analysis.action.value}（{analysis.action_reason}）\n"
            f"主要风险：{risks}\n"
            f"发布时间：{candidate.published_at.isoformat() if candidate.published_at else '未知'}\n"
            f"来源：{candidate.source}\n"
            f"详情链接：{detail_url}"
        )


def build_personal_news_monitor(config: Any) -> PersonalNewsMonitor:
    from src.personal_news.providers import ExistingPushNotifier, ExistingSearchNewsSource, LiteLLMNewsAnalyzer

    settings = NewsRadarSettings.from_env(fallback_watchlist=list(config.stock_list))
    analyzer = None
    if config.openai_api_key and (config.litellm_model or config.openai_model):
        analyzer = LiteLLMNewsAnalyzer(config)
    return PersonalNewsMonitor(
        settings=settings,
        sources=[ExistingSearchNewsSource(config)],
        analyzer=analyzer,
        notifier=ExistingPushNotifier(config),
    )
