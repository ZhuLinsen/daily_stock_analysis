from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.config import Config
from src.personal_news.providers import LiteLLMNewsAnalyzer
from src.personal_news.repository import PersonalNewsRepository, canonicalize_url, normalize_title
from src.personal_news.schemas import (
    Action,
    Direction,
    Market,
    NewsAnalysis,
    NewsCandidate,
    NewsRadarSettings,
    TimeHorizon,
    parse_stock_symbol,
    parse_watchlist_input,
)
from src.personal_news.scoring import score_importance
from src.personal_news.service import PersonalNewsMonitor
from src.scheduler import Scheduler
from src.storage import DatabaseManager


@pytest.fixture()
def repository(tmp_path: Path) -> PersonalNewsRepository:
    Config._instance = Config()
    DatabaseManager.reset_instance()
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'personal-news.db'}")
    yield PersonalNewsRepository(db)
    DatabaseManager.reset_instance()
    Config._instance = None


def candidate(**overrides) -> NewsCandidate:
    values = {
        "title": "英伟达上调下一季度收入指引",
        "url": "https://example.com/news/1?utm_source=test",
        "source": "公司公告",
        "summary": "公司公布正式指引，同时提醒供应风险。",
        "published_at": datetime.now(timezone.utc),
        "symbols": ["NVDA"],
        "is_announcement": True,
        "source_reliability": 95,
        "entity_confidence": 95,
        "price_change_percent": 4.2,
        "volume_change_percent": 80,
    }
    values.update(overrides)
    return NewsCandidate(**values)


def analysis() -> NewsAnalysis:
    return NewsAnalysis(
        summary="公司上调收入指引，但短线需关注预期兑现和供应约束。",
        direction=Direction.POSITIVE,
        confidence=78,
        time_horizon=TimeHorizon.ONE_TO_FIVE_DAYS,
        positive_factors=["收入指引高于此前预期"],
        negative_factors=["消息公布前股价已上涨"],
        risks=["供应约束可能影响兑现"],
        action=Action.WATCH_NOW,
        action_reason="基本面信息偏正面，但不适合高开追涨。",
        invalidation_conditions=["公司撤回或下调本次指引"],
        source_urls=["https://example.com/news/1"],
        data_time=datetime.now(timezone.utc),
    )


def test_title_and_url_normalization() -> None:
    assert normalize_title("  英伟达：上调 指引！ ") == normalize_title("英伟达 上调指引")
    assert canonicalize_url("HTTPS://EXAMPLE.COM/a/?utm_source=x&b=2") == "https://example.com/a?b=2"


def test_a_hk_us_symbol_parsing() -> None:
    assert parse_stock_symbol("600519") == ("600519.SH", Market.A_SHARE)
    assert parse_stock_symbol("300750") == ("300750.SZ", Market.A_SHARE)
    assert parse_stock_symbol("920000") == ("920000.BJ", Market.A_SHARE)
    assert parse_stock_symbol("hk00700") == ("00700.HK", Market.HK)
    assert parse_stock_symbol("00700.HK") == ("00700.HK", Market.HK)
    assert parse_stock_symbol("aapl.us") == ("AAPL", Market.US)
    assert parse_watchlist_input("600519，300750\n00700 nvda") == [
        "600519.SH", "300750.SZ", "00700.HK", "NVDA"
    ]


def test_repository_deduplicates_url_and_similar_event(repository: PersonalNewsRepository) -> None:
    article_id, created = repository.ingest(candidate())
    assert created is True
    same_url_id, created = repository.ingest(candidate(title="另一标题", url="https://example.com/news/1"))
    assert (same_url_id, created) == (article_id, False)
    same_event_id, created = repository.ingest(candidate(url="https://mirror.example.com/1"))
    assert (same_event_id, created) == (article_id, False)
    assert len(repository.list_articles()) == 1


def test_importance_score_is_deterministic_and_llm_independent() -> None:
    score, reasons = score_importance(candidate(), ["NVDA"])
    assert score >= 75
    assert any("命中自选股" in reason for reason in reasons)
    assert any("成交量" in reason for reason in reasons)


def test_analysis_schema_rejects_missing_sources_and_unbalanced_output() -> None:
    payload = analysis().model_dump(mode="json")
    payload["source_urls"] = []
    with pytest.raises(ValidationError):
        NewsAnalysis.model_validate(payload)
    payload = analysis().model_dump(mode="json")
    payload["negative_factors"] = []
    with pytest.raises(ValidationError):
        NewsAnalysis.model_validate(payload)


def test_llm_invalid_json_retries_once() -> None:
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        content = "not-json" if len(calls) == 1 else analysis().model_dump_json()
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    config = SimpleNamespace(litellm_model="openai/test", openai_model="test", openai_api_key="fake", openai_base_url="https://example.test/v1")
    analyzer = LiteLLMNewsAnalyzer(config, completion_fn=fake_completion)
    assert analyzer.analyze(candidate(), data_time=datetime.now(timezone.utc)).action == Action.WATCH_NOW
    assert len(calls) == 2


def test_llm_prompt_is_conservative_and_risk_first() -> None:
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=analysis().model_dump_json()))]
        )

    config = SimpleNamespace(
        litellm_model="openai/test",
        openai_model="test",
        openai_api_key="fake",
        openai_base_url="https://example.test/v1",
    )
    analyzer = LiteLLMNewsAnalyzer(config, completion_fn=fake_completion)
    analyzer.analyze(candidate(), data_time=datetime.now(timezone.utc))

    system_prompt = calls[0]["messages"][0]["content"]
    user_prompt = calls[0]["messages"][1]["content"]
    assert "风险优先、偏保守" in system_prompt
    assert "不要把利好新闻直接等同于买入机会" in system_prompt
    assert "默认优先考虑 WAIT_FOR_CONFIRMATION、NO_ACTION 或 INSUFFICIENT_EVIDENCE" in system_prompt
    assert "不得写成直接买入、加仓或追涨指令" in user_prompt
    assert calls[0]["temperature"] == 0.1


def test_llm_rejects_hallucinated_source_urls_after_retry() -> None:
    invalid = analysis().model_copy(update={"source_urls": ["https://invented.example/fact"]})
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=invalid.model_dump_json()))])

    config = SimpleNamespace(litellm_model="openai/test", openai_model="test", openai_api_key="fake", openai_base_url="https://example.test/v1")
    analyzer = LiteLLMNewsAnalyzer(config, completion_fn=fake_completion)
    with pytest.raises(ValueError, match="invalid structured analysis"):
        analyzer.analyze(candidate(), data_time=datetime.now(timezone.utc))
    assert len(calls) == 2


class FakeSource:
    def __init__(self, name: str, items=None, error: Exception | None = None):
        self.name = name
        self.items = items or []
        self.error = error

    def fetch(self, _settings):
        if self.error:
            raise self.error
        return self.items


class FakeAnalyzer:
    provider_name = "fake-llm"
    model = "fixture"

    def analyze(self, _candidate, *, data_time):
        result = analysis()
        return result.model_copy(update={"data_time": data_time})


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def channels(self):
        return ["wechat", "feishu"]

    def send(self, channel, content):
        self.sent.append((channel, content))
        return True


def test_fixture_e2e_merges_sources_pushes_once_and_renders_detail(repository: PersonalNewsRepository) -> None:
    notifier = FakeNotifier()
    first = candidate()
    second = candidate(url="https://mirror.example.com/news/1", source="财经媒体")
    settings = NewsRadarSettings(watchlist=["NVDA"], min_analysis_score=60, min_push_score=75)
    monitor = PersonalNewsMonitor(
        settings=settings,
        sources=[FakeSource("source-a", [first]), FakeSource("source-b", [second])],
        repository=repository,
        analyzer=FakeAnalyzer(),
        notifier=notifier,
    )

    first_run = monitor.run_once()
    assert first_run["new"] == 1
    assert first_run["analyzed"] == 1
    assert first_run["pushed"] == 1
    assert {channel for channel, _ in notifier.sent} == {"feishu"}
    item = repository.list_articles()[0]
    assert item["source_count"] == 2
    assert item["analysis"]["action"] == "WATCH_NOW"
    assert repository.get_article(item["id"])["url"] == "https://example.com/news/1"

    DatabaseManager.reset_instance()
    reopened = PersonalNewsRepository(DatabaseManager(db_url=repository.db._db_url))
    restarted = PersonalNewsMonitor(
        settings=settings,
        sources=[FakeSource("source-a", [first])],
        repository=reopened,
        analyzer=FakeAnalyzer(),
        notifier=notifier,
    )
    second_run = restarted.run_once()
    assert second_run["new"] == 0
    assert second_run["pushed"] == 0
    assert len(notifier.sent) == 1


def test_single_source_failure_does_not_stop_other_sources(repository: PersonalNewsRepository) -> None:
    monitor = PersonalNewsMonitor(
        settings=NewsRadarSettings(watchlist=["NVDA"]),
        sources=[FakeSource("broken", error=RuntimeError("offline")), FakeSource("working", [candidate()])],
        repository=repository,
    )
    stats = monitor.run_once()
    assert stats["errors"] == 1
    assert stats["new"] == 1


def test_no_new_articles_skips_ai_and_push(repository: PersonalNewsRepository) -> None:
    notifier = FakeNotifier()
    analyzer = FakeAnalyzer()
    monitor = PersonalNewsMonitor(
        settings=NewsRadarSettings(watchlist=["NVDA"], min_analysis_score=60, min_push_score=75),
        sources=[FakeSource("source", [candidate()])],
        repository=repository,
        analyzer=analyzer,
        notifier=notifier,
    )
    assert monitor.run_once()["pushed"] == 1
    second = monitor.run_once()
    assert second["new"] == second["analyzed"] == second["pushed"] == 0
    assert len(notifier.sent) == 1


def test_watchlist_is_persisted_and_preserves_hk_leading_zero(repository: PersonalNewsRepository) -> None:
    repository.add_watchlist_symbols(parse_watchlist_input("00700 NVDA"))
    assert repository.get_watchlist_symbols() == ["00700.HK", "NVDA"]
    repository.remove_watchlist_symbol("00700.HK")
    assert repository.get_watchlist_symbols() == ["NVDA"]


def test_only_top_five_new_items_are_analyzed_and_one_digest_is_sent(repository: PersonalNewsRepository) -> None:
    class CountingAnalyzer(FakeAnalyzer):
        def __init__(self):
            self.calls = 0

        def analyze(self, item, *, data_time):
            self.calls += 1
            return super().analyze(item, data_time=data_time)

    analyzer = CountingAnalyzer()
    notifier = FakeNotifier()
    items = [candidate(title=f"英伟达重要公告 {index}", url=f"https://example.com/{index}") for index in range(7)]
    monitor = PersonalNewsMonitor(
        settings=NewsRadarSettings(watchlist=["NVDA"], max_ai_items_per_run=5),
        sources=[FakeSource("source", items)], repository=repository, analyzer=analyzer, notifier=notifier,
    )
    result = monitor.run_once()
    assert result["new"] == 7
    assert result["analyzed"] == analyzer.calls == 5
    assert result["pushed"] == 1
    assert len(notifier.sent) == 1
    assert "【自选股 12 小时资讯】" in notifier.sent[0][1]
    assert "观察策略：重点关注" in notifier.sent[0][1]


def test_refresh_cooldown_and_process_lock(repository: PersonalNewsRepository) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingSource(FakeSource):
        def fetch(self, settings):
            entered.set()
            release.wait(timeout=2)
            return []

    monitor = PersonalNewsMonitor(
        settings=NewsRadarSettings(watchlist=["NVDA"]),
        sources=[BlockingSource("blocking")], repository=repository,
    )
    assert monitor.request_refresh()["status"] == "started"
    assert entered.wait(timeout=1)
    assert monitor.request_refresh()["status"] == "running"
    release.set()
    assert monitor._refresh_thread is not None
    monitor._refresh_thread.join(timeout=2)
    assert monitor.refresh_status()["status"] == "completed"
    assert monitor.request_refresh()["status"] == "cooldown"


def test_personal_schedule_uses_exact_china_times_without_startup_run(monkeypatch) -> None:
    scheduled: list[tuple[str, str]] = []
    callback_calls: list[str] = []

    class FakeJob:
        @property
        def day(self):
            return self

        def at(self, value, timezone_name):
            scheduled.append((value, timezone_name))
            return self

        def do(self, callback):
            self.callback = callback
            return self

    monkeypatch.setitem(sys.modules, "schedule", SimpleNamespace(every=FakeJob, cancel_job=lambda _job: None))
    scheduler = Scheduler(
        schedule_times=["08:00", "20:00"], timezone_name="Asia/Shanghai", register_signals=False
    )
    scheduler.set_daily_task(lambda: callback_calls.append("ran"), run_immediately=False)

    assert scheduled == [("08:00", "Asia/Shanghai"), ("20:00", "Asia/Shanghai")]
    assert callback_calls == []


def test_pwa_manifest_and_service_worker_exist() -> None:
    root = Path(__file__).parents[1] / "apps" / "dsa-web" / "public"
    manifest = json.loads((root / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone"
    assert {icon["sizes"] for icon in manifest["icons"]} == {"192x192", "512x512"}
    worker = (root / "service-worker.js").read_text(encoding="utf-8")
    assert "/api/v1/personal-news" in worker
