from __future__ import annotations

import json
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
)
from src.personal_news.scoring import score_importance
from src.personal_news.service import PersonalNewsMonitor
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
        source_urls=["https://example.com/news/1"],
        data_time=datetime.now(timezone.utc),
    )


def test_title_and_url_normalization() -> None:
    assert normalize_title("  英伟达：上调 指引！ ") == normalize_title("英伟达 上调指引")
    assert canonicalize_url("HTTPS://EXAMPLE.COM/a/?utm_source=x&b=2") == "https://example.com/a?b=2"


def test_a_hk_us_symbol_parsing() -> None:
    assert parse_stock_symbol("600519") == ("600519", Market.A_SHARE)
    assert parse_stock_symbol("hk00700") == ("HK00700", Market.HK)
    assert parse_stock_symbol("00700.HK") == ("HK00700", Market.HK)
    assert parse_stock_symbol("aapl.us") == ("AAPL", Market.US)


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
    assert first_run["pushed"] == 2
    assert {channel for channel, _ in notifier.sent} == {"wechat", "feishu"}
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
    assert len(notifier.sent) == 2


def test_single_source_failure_does_not_stop_other_sources(repository: PersonalNewsRepository) -> None:
    monitor = PersonalNewsMonitor(
        settings=NewsRadarSettings(watchlist=["NVDA"]),
        sources=[FakeSource("broken", error=RuntimeError("offline")), FakeSource("working", [candidate()])],
        repository=repository,
    )
    stats = monitor.run_once()
    assert stats["errors"] == 1
    assert stats["new"] == 1


def test_failed_push_retries_without_replaying_successful_channel(repository: PersonalNewsRepository) -> None:
    class RetryNotifier(FakeNotifier):
        def __init__(self):
            super().__init__()
            self.feishu_attempts = 0

        def send(self, channel, content):
            self.sent.append((channel, content))
            if channel == "feishu":
                self.feishu_attempts += 1
                return self.feishu_attempts > 1
            return True

    notifier = RetryNotifier()
    monitor = PersonalNewsMonitor(
        settings=NewsRadarSettings(watchlist=["NVDA"], min_analysis_score=60, min_push_score=75),
        sources=[FakeSource("source", [candidate()])],
        repository=repository,
        analyzer=FakeAnalyzer(),
        notifier=notifier,
    )
    assert monitor.run_once()["pushed"] == 1
    assert monitor.run_once()["pushed"] == 1
    assert [channel for channel, _ in notifier.sent].count("wechat") == 1
    assert [channel for channel, _ in notifier.sent].count("feishu") == 2


def test_pwa_manifest_and_service_worker_exist() -> None:
    root = Path(__file__).parents[1] / "apps" / "dsa-web" / "public"
    manifest = json.loads((root / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone"
    assert {icon["sizes"] for icon in manifest["icons"]} == {"192x192", "512x512"}
    worker = (root / "service-worker.js").read_text(encoding="utf-8")
    assert "/api/v1/personal-news" in worker
