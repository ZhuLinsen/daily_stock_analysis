# -*- coding: utf-8 -*-
"""Wave 2 调度面用例（issue #2184）：``build_news_digest_background_task``、
RuntimeSchedulerService 按名合并后台任务、main.py 挂载与 CLI 一次性入口（D10/D11）。

- 时间相关断言一律注入固定 datetime 或捕获调用参数，不依赖真实时钟。
- scheduler 断言用 fake scheduler 捕获 ``add_background_task`` 调用
  （样板 tests/test_runtime_scheduler_service.py:677-756）。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import src.services.news_digest_service as news_digest_service
from src.services.runtime_scheduler import RuntimeSchedulerService

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

import main  # noqa: E402  重量级导入须在 litellm stub 之后


# ---------------------------------------------------------------------------
# fakes（样板 tests/test_runtime_scheduler_service.py:677-756）
# ---------------------------------------------------------------------------


class _NoopThread:
    def __init__(self, target=None, **kwargs):
        self.target = target
        self.kwargs = kwargs

    def start(self):
        return None

    def is_alive(self):
        return False


class _FakeScheduler:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.background_tasks = []
        self.daily_task = None
        self.daily_task_run_immediately = None
        self._jobs = []

    def set_daily_task(self, task, run_immediately: bool) -> None:
        self.daily_task = task
        self.daily_task_run_immediately = run_immediately

    def add_background_task(
        self,
        task,
        interval_seconds: int,
        run_immediately: bool,
        name=None,
    ) -> None:
        self.background_tasks.append(
            {
                "task": task,
                "interval_seconds": interval_seconds,
                "run_immediately": run_immediately,
                "name": name,
            }
        )

    def run(self) -> None:
        return None

    def stop(self) -> None:
        return None

    @property
    def schedule(self):
        class _Namespace:
            @staticmethod
            def get_jobs():
                return []

        return _Namespace

    @property
    def schedule_time(self):
        return self.kwargs.get("schedule_time")


def _start_service_with_fakes(service: RuntimeSchedulerService):
    with patch(
        "src.services.runtime_scheduler.Scheduler", _FakeScheduler
    ), patch("src.services.runtime_scheduler.threading.Thread", _NoopThread):
        service.start()
    return service._scheduler


def _make_service(config):
    service = RuntimeSchedulerService(config_provider=lambda: config)
    service._reload_config = lambda: config
    return service


def _base_config(**overrides):
    values = {
        "schedule_enabled": True,
        "schedule_time": "18:00",
        "schedule_times": ["18:00"],
        "agent_event_monitor_enabled": False,
        "agent_event_monitor_interval_minutes": 5,
        "news_digest_enabled": True,
        "news_digest_interval_minutes": 10,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ---------------------------------------------------------------------------
# build_news_digest_background_task（D10，服务层）
# ---------------------------------------------------------------------------


def test_build_background_task_disabled_returns_none():
    build = news_digest_service.build_news_digest_background_task
    config = SimpleNamespace(news_digest_enabled=False)
    assert build(config_provider=lambda: config) is None


def test_build_background_task_enabled_shape():
    build = news_digest_service.build_news_digest_background_task
    config = SimpleNamespace(news_digest_enabled=True, news_digest_interval_minutes=10)
    entry = build(config_provider=lambda: config)
    assert entry is not None
    assert entry["name"] == "news_digest"
    assert entry["interval_seconds"] == 10 * 60
    assert entry["run_immediately"] is True
    assert callable(entry["task"])


def test_build_background_task_invalid_interval_falls_back():
    build = news_digest_service.build_news_digest_background_task
    for bad_interval in (0, None):
        config = SimpleNamespace(
            news_digest_enabled=True,
            news_digest_interval_minutes=bad_interval,
        )
        entry = build(config_provider=lambda: config)
        assert entry is not None, f"interval={bad_interval!r}"
        assert entry["interval_seconds"] == 600, f"interval={bad_interval!r} 应回退 10 分钟"


# ---------------------------------------------------------------------------
# RuntimeSchedulerService 按名合并（D10(b)）
# ---------------------------------------------------------------------------


def test_runtime_scheduler_registers_news_digest_when_enabled():
    config = _base_config()
    scheduler = _start_service_with_fakes(_make_service(config))
    assert scheduler is not None
    assert len(scheduler.background_tasks) == 1
    entry = scheduler.background_tasks[0]
    assert entry["name"] == "news_digest"
    assert entry["interval_seconds"] == 600
    assert entry["run_immediately"] is True
    assert callable(entry["task"])


def test_runtime_scheduler_registers_both_tasks():
    config = _base_config(agent_event_monitor_enabled=True)
    scheduler = _start_service_with_fakes(_make_service(config))
    assert scheduler is not None
    assert len(scheduler.background_tasks) == 2
    names = {entry["name"] for entry in scheduler.background_tasks}
    assert names == {"agent_event_monitor", "news_digest"}


def test_runtime_scheduler_digest_disabled_keeps_monitor_only():
    """digest 关闭时与既有单任务行为完全一致（守 tests/test_runtime_scheduler_service.py:748 len==1）。"""
    config = _base_config(
        agent_event_monitor_enabled=True,
        news_digest_enabled=False,
    )
    scheduler = _start_service_with_fakes(_make_service(config))
    assert scheduler is not None
    assert len(scheduler.background_tasks) == 1
    assert scheduler.background_tasks[0]["name"] == "agent_event_monitor"


def test_runtime_scheduler_interval_refresh_from_config():
    """样板 :827-836：interval 7→11 分钟，重建后 660s 且 run_immediately 仅首次。"""
    schedulers = []

    class _RecordingScheduler(_FakeScheduler):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            schedulers.append(self)

    config = _base_config(agent_event_monitor_enabled=True, news_digest_interval_minutes=7)
    service = _make_service(config)

    with patch(
        "src.services.runtime_scheduler.Scheduler", _RecordingScheduler
    ), patch("src.services.runtime_scheduler.threading.Thread", _NoopThread):
        service.reconcile_from_config()
        config.news_digest_interval_minutes = 11
        service.reconcile_from_config()
        config.schedule_times = ["19:00"]
        service.reconcile_from_config()

    assert len(schedulers) == 3
    for index, scheduler in enumerate(schedulers):
        digest_entries = [
            entry for entry in scheduler.background_tasks if entry["name"] == "news_digest"
        ]
        assert len(digest_entries) == 1
        entry = digest_entries[0]
        assert entry["interval_seconds"] == (7 * 60 if index == 0 else 11 * 60)
        assert entry["run_immediately"] is (index == 0)


# ---------------------------------------------------------------------------
# main.py 接线（D10(a) 挂载 + D11 CLI 一次性入口）
# ---------------------------------------------------------------------------


def test_main_background_tasks_include_news_digest():
    """monkeypatch build 函数，断言 main 组装路径 append（disabled → 不 append）。"""
    sentinel_entry = {"task": lambda: None, "interval_seconds": 600,
                      "run_immediately": True, "name": "news_digest"}
    provider = lambda: SimpleNamespace()  # noqa: E731

    with patch(
        "src.services.news_digest_service.build_news_digest_background_task",
        return_value=dict(sentinel_entry),
    ) as build_mock:
        tasks = []
        main._append_news_digest_background_task(tasks, provider)
        assert build_mock.call_count == 1
        assert tasks == [sentinel_entry]

    with patch(
        "src.services.news_digest_service.build_news_digest_background_task",
        return_value=None,
    ):
        tasks = []
        main._append_news_digest_background_task(tasks, provider)
        assert tasks == []


def test_main_background_tasks_build_failure_never_raises():
    """build 抛异常时挂载路径吞掉（不影响定时模式启动）。"""
    with patch(
        "src.services.news_digest_service.build_news_digest_background_task",
        side_effect=RuntimeError("boom"),
    ):
        tasks = []
        main._append_news_digest_background_task(tasks, lambda: SimpleNamespace())
    assert tasks == []


_EMPTY_DEPS = {
    "notifier": None,
    "search_service": None,
    "intelligence_service": None,
    "summarizer": None,
    "db": None,
}


def test_cli_news_digest_invokes_service_force(capsys):
    """--news-digest：force=True（跳过窗口/已推送短路）+ Markdown 摘要打印到
    stdout（D11/MINOR-1）；依赖组装链路另有集成用例覆盖。"""
    report_markdown = "# 消息面汇总（盘前）2026-10-25\n\n正文"
    fake_result = {
        "status": "success",
        "reason": None,
        "entries_count": 3,
        "notified": True,
        "report": report_markdown,
    }
    with patch(
        "src.services.news_digest_service.build_news_digest_dependencies",
        return_value=dict(_EMPTY_DEPS),
    ), patch(
        "src.services.news_digest_service.run_news_digest_once",
        return_value=fake_result,
    ) as run_mock:
        exit_code = main._run_news_digest_once_cli(SimpleNamespace())

    assert run_mock.call_count == 1
    _args, kwargs = run_mock.call_args
    assert kwargs.get("force") is True
    now_value = kwargs.get("now")
    assert isinstance(now_value, datetime)
    assert exit_code == 0

    captured = capsys.readouterr().out
    assert report_markdown in captured  # 无论推送结果，摘要必须可见
    assert "success" in captured  # 推送状态行随后输出


def test_cli_news_digest_failed_reports_nonzero(monkeypatch, capsys):
    fake_result = {"status": "failed", "reason": "unexpected_error: Boom", "report": ""}
    with patch(
        "src.services.news_digest_service.build_news_digest_dependencies",
        return_value=dict(_EMPTY_DEPS),
    ), patch(
        "src.services.news_digest_service.run_news_digest_once",
        return_value=fake_result,
    ):
        exit_code = main._run_news_digest_once_cli(SimpleNamespace())
    assert exit_code == 1
    assert "failed" in capsys.readouterr().out


def test_cli_news_digest_dependency_assembly_failure_never_raises(capsys):
    """组装器意外抛异常：CLI 兜底全量降级（空依赖），仍完成运行并打印状态。"""
    fake_result = {"status": "success", "reason": None, "notified": True, "report": "# 摘要"}
    with patch(
        "src.services.news_digest_service.build_news_digest_dependencies",
        side_effect=RuntimeError("assembly exploded"),
    ), patch(
        "src.services.news_digest_service.run_news_digest_once",
        return_value=fake_result,
    ) as run_mock:
        exit_code = main._run_news_digest_once_cli(SimpleNamespace())

    assert exit_code == 0
    _args, kwargs = run_mock.call_args
    assert kwargs.get("search_service") is None
    assert kwargs.get("notifier") is None
    assert "# 摘要" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# CLI 真实依赖组装（OR-COR-000c926a：--news-digest 不得恒生成无数据模板）
# ---------------------------------------------------------------------------


class _RecordingNotifier:
    def __init__(self):
        self.calls = []

    def send(self, content, **kwargs):
        self.calls.append(dict(kwargs, content=content))
        return True


class _RecordingSearch:
    is_available = True

    def __init__(self):
        self.calls = []

    def search_topic_news_bounded(self, topic, max_results=5, **kwargs):
        self.calls.append(topic)

        class _Item:
            title = f"{topic}要闻"
            snippet = "盘前快讯正文"
            url = f"https://news.cn/{topic}"
            source = "新华社"
            published_date = None

        class _Response:
            success = True
            results = [_Item()]

        return _Response()


class _RecordingIntelligence:
    def __init__(self):
        self.fetch_called = False
        self.repo = SimpleNamespace(list_items=self._list_items)

    def fetch_enabled_sources(self):
        self.fetch_called = True
        return {"ok": True, "source_count": 0, "results": [], "saved_count": 0}

    def _list_items(self, **kwargs):
        return [], 0


class _RecordingDb:
    def __init__(self):
        self.saved = []

    def save_analysis_history(self, **kwargs):
        self.saved.append(kwargs)
        return 77


def test_cli_news_digest_assembles_real_dependencies(tmp_path, capsys):
    """--news-digest 集成路径：CLI 必须组装真实依赖并注入服务（不 mock
    run_news_digest_once），否则生产输出恒为无数据模板（OR-COR-000c926a）。"""
    digest_notifier = _RecordingNotifier()
    digest_search = _RecordingSearch()
    digest_intelligence = _RecordingIntelligence()
    digest_db = _RecordingDb()
    config = SimpleNamespace(
        news_digest_enabled=True,
        news_digest_premarket_window="08:00-09:15",
        news_digest_offday_window="09:00-18:00",
        news_digest_topics="宏观政策",
        news_digest_region="cn",
        report_language="zh",
        database_path=str(tmp_path / "cli_digest.db"),
    )

    with patch(
        "src.core.market_review_runtime.build_market_review_runtime",
        return_value=(digest_notifier, None, digest_search),
    ) as runtime_mock, patch(
        "src.services.intelligence_service.IntelligenceService",
        return_value=digest_intelligence,
    ), patch(
        "src.storage.DatabaseManager"
    ) as database_manager_cls, patch(
        "src.notification.NotificationService"
    ) as fallback_notifier_cls:
        database_manager_cls.get_instance.return_value = digest_db
        exit_code = main._run_news_digest_once_cli(config)

    assert runtime_mock.call_count >= 1
    assert exit_code == 0
    assert digest_search.calls, "搜索腿依赖未组装：CLI 未向服务传入 search_service"
    assert digest_intelligence.fetch_called, "资讯池依赖未组装：CLI 未传入 intelligence_service"
    assert len(digest_notifier.calls) == 1, (
        "通知依赖未组装：发送走了服务内 NotificationService 回退构造"
    )
    assert fallback_notifier_cls.call_count == 0, (
        "notifier 应由 CLI 组装注入，而非触发服务内回退构造"
    )
    assert len(digest_db.saved) == 1
    captured = capsys.readouterr().out
    assert "# 消息面汇总" in captured
    assert "盘前快讯正文" in captured, "真实搜索结果应进入最终摘要而非空模板"


def test_build_news_digest_dependencies_fail_open():
    """共享组装器契约：任一依赖构造失败仅降级 None，绝不向上抛。"""
    with patch(
        "src.core.market_review_runtime.build_market_review_runtime",
        side_effect=RuntimeError("runtime down"),
    ), patch(
        "src.services.intelligence_service.IntelligenceService",
        side_effect=RuntimeError("repo down"),
    ), patch(
        "src.storage.DatabaseManager"
    ) as database_manager_cls:
        database_manager_cls.get_instance.side_effect = RuntimeError("db down")
        deps = news_digest_service.build_news_digest_dependencies(SimpleNamespace())
    assert deps == {
        "notifier": None,
        "search_service": None,
        "intelligence_service": None,
        "summarizer": None,
        "db": None,
    }


def test_build_news_digest_dependencies_assembles_all():
    """共享组装器正常路径：四类依赖全部组装到位（tick 与 CLI 共用）。"""
    sentinel_notifier, sentinel_search = object(), object()
    sentinel_intelligence, sentinel_db = object(), object()
    with patch(
        "src.core.market_review_runtime.build_market_review_runtime",
        return_value=(sentinel_notifier, object(), sentinel_search),
    ), patch(
        "src.services.intelligence_service.IntelligenceService",
        return_value=sentinel_intelligence,
    ), patch(
        "src.storage.DatabaseManager"
    ) as database_manager_cls:
        database_manager_cls.get_instance.return_value = sentinel_db
        deps = news_digest_service.build_news_digest_dependencies(SimpleNamespace())
    assert deps["notifier"] is sentinel_notifier
    assert deps["search_service"] is sentinel_search
    assert deps["intelligence_service"] is sentinel_intelligence
    assert deps["db"] is sentinel_db
    assert callable(deps["summarizer"])


# ---------------------------------------------------------------------------
# tick 真实执行链（W1 hand-off：tick 必须注入真实服务）
# ---------------------------------------------------------------------------


def test_tick_calls_run_once_with_now():
    """task["task"]() 触发一次 run_news_digest_once，参数含 datetime now 与注入服务。"""
    build = news_digest_service.build_news_digest_background_task
    config = SimpleNamespace(news_digest_enabled=True, news_digest_interval_minutes=10)
    entry = build(config_provider=lambda: config)
    assert entry is not None
    assert callable(entry["task"])

    sentinel_notifier = object()
    sentinel_search = object()
    sentinel_intelligence = object()
    sentinel_db = object()
    fake_runtime_result = {"status": "skipped", "reason": "outside_window"}

    with patch(
        "src.core.market_review_runtime.build_market_review_runtime",
        return_value=(sentinel_notifier, object(), sentinel_search),
    ) as runtime_mock, patch(
        "src.services.intelligence_service.IntelligenceService"
    ) as intelligence_cls, patch(
        "src.storage.DatabaseManager"
    ) as database_manager_cls, patch(
        "src.services.news_digest_service.run_news_digest_once",
        return_value=fake_runtime_result,
    ) as run_once_mock:
        intelligence_cls.return_value = sentinel_intelligence
        database_manager_cls.get_instance.return_value = sentinel_db
        entry["task"]()

    assert runtime_mock.call_count >= 1  # 共享运行时（notifier/analyzer/search）
    assert run_once_mock.call_count == 1
    _args, kwargs = run_once_mock.call_args
    assert isinstance(kwargs.get("now"), datetime)
    assert kwargs.get("notifier") is sentinel_notifier
    assert kwargs.get("search_service") is sentinel_search
    assert kwargs.get("intelligence_service") is sentinel_intelligence
    assert kwargs.get("db") is sentinel_db
    # summarizer 可为 None（LLM 不可用时模板降级），但键必须参与注入
    assert "summarizer" in kwargs


def test_tick_config_provider_failure_is_swallowed():
    """config_provider 抛异常：tick 记录后返回，不向上抛（等下一 tick）。"""
    build = news_digest_service.build_news_digest_background_task

    def _broken_provider():
        raise RuntimeError("config unavailable")

    entry = build(config_provider=_broken_provider)
    # enabled 判定读不到配置时按 disabled 处理：build 阶段即返回 None
    assert entry is None


def test_tick_run_once_exception_never_raises():
    """run_news_digest_once 自身永不抛（契约），tick 对其意外异常也要兜底。"""
    build = news_digest_service.build_news_digest_background_task
    config = SimpleNamespace(news_digest_enabled=True, news_digest_interval_minutes=10)
    entry = build(config_provider=lambda: config)
    assert entry is not None

    with patch(
        "src.core.market_review_runtime.build_market_review_runtime",
        return_value=(None, None, None),
    ), patch(
        "src.services.intelligence_service.IntelligenceService"
    ), patch(
        "src.storage.DatabaseManager"
    ), patch(
        "src.services.news_digest_service.run_news_digest_once",
        side_effect=RuntimeError("contract violation"),
    ):
        entry["task"]()  # 不应抛异常
