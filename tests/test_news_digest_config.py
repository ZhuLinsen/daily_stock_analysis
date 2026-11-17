# -*- coding: utf-8 -*-
"""消息面汇总配置面与 CLI 入口测试（issue #2184）。

- 配置：env 解析语义（默认关闭 = 不配置零行为差异；窗口/条数非法回退）。
- CLI：``--news-digest`` 分派入口、``_skips_stock_entry`` 守卫
  （OR-COR-849edf8d）与真实依赖组装（OR-COR-000c926a）。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.config import Config

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

import main  # noqa: E402  重量级导入须在 litellm stub 之后
import src.services.news_digest_service as news_digest_service  # noqa: E402

pytestmark = pytest.mark.unit

NEWS_DIGEST_ENV_KEYS = (
    "NEWS_DIGEST_ENABLED",
    "NEWS_DIGEST_PREMARKET_WINDOW",
    "NEWS_DIGEST_OFFDAY_WINDOW",
    "NEWS_DIGEST_MAX_NEWS",
)


@pytest.fixture
def news_digest_config(monkeypatch):
    """清空 NEWS_DIGEST_* env → 重置 Config 单例；返回可增量设 env 的工厂。"""
    for env_key in NEWS_DIGEST_ENV_KEYS:
        monkeypatch.delenv(env_key, raising=False)

    def _apply(**env_values):
        for suffix, value in env_values.items():
            env_key = suffix if suffix.startswith("NEWS_DIGEST_") else f"NEWS_DIGEST_{suffix}"
            monkeypatch.setenv(env_key, str(value))
        Config.reset_instance()
        return Config.get_instance()

    Config.reset_instance()
    yield _apply
    Config.reset_instance()


# ---------------------------------------------------------------------------
# 配置解析组：默认关闭 = 不配置零行为差异
# ---------------------------------------------------------------------------


def test_unconfigured_digest_defaults_off(news_digest_config):
    """第 9 节 b 条对照：不配置任何 NEWS_DIGEST_* → 全部默认值。"""
    config = news_digest_config()
    assert config.news_digest_enabled is False
    assert config.news_digest_premarket_window == "08:00-09:15"
    assert config.news_digest_offday_window == "09:00-18:00"
    assert config.news_digest_max_news == 12


def test_digest_env_true_and_max_news_clamped(news_digest_config):
    config = news_digest_config(ENABLED="true", MAX_NEWS="99")
    assert config.news_digest_enabled is True
    assert config.news_digest_max_news == 30, "越界值钳到上限 30"


def test_digest_invalid_values_fail_open_to_defaults(news_digest_config):
    config = news_digest_config(ENABLED="not-a-bool", MAX_NEWS="abc",
                               PREMARKET_WINDOW="", OFFDAY_WINDOW="")
    assert config.news_digest_enabled is False
    assert config.news_digest_max_news == 12
    assert config.news_digest_premarket_window == "08:00-09:15"
    assert config.news_digest_offday_window == "09:00-18:00"


def test_parse_arguments_has_news_digest_flag_default_false(monkeypatch):
    """argparse 默认不含 --news-digest：普通一次性运行零行为差异。"""
    monkeypatch.setattr("sys.argv", ["main.py"])
    assert getattr(main.parse_arguments(), "news_digest", None) is False
    monkeypatch.setattr("sys.argv", ["main.py", "--news-digest"])
    assert getattr(main.parse_arguments(), "news_digest") is True


# ---------------------------------------------------------------------------
# _skips_stock_entry 守卫（OR-COR-849edf8d）：--news-digest 不消费股票列表
# ---------------------------------------------------------------------------


def _args(**overrides):
    values = dict(
        backtest=False, etf_rotation=False, market_review=False,
        news_digest=False, serve_only=False, webui_only=False,
        portfolio=None, schedule=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_skips_stock_entry_covers_news_digest():
    """--news-digest 模式在股票解析前整体跳过：无关 --stocks 配置不得阻断摘要。"""
    assert main._skips_stock_entry(_args(news_digest=True),
                                   SimpleNamespace(schedule_enabled=False)) is True


def test_skips_stock_entry_plain_run_still_consumes_stocks():
    assert main._skips_stock_entry(_args(),
                                   SimpleNamespace(schedule_enabled=False)) is False


# ---------------------------------------------------------------------------
# CLI 一次性入口：打印摘要与状态行
# ---------------------------------------------------------------------------


def test_cli_news_digest_invokes_service_and_prints(capsys):
    """--news-digest：组装依赖 → run_once → Markdown 摘要打印到 stdout + 状态行。"""
    report_markdown = "# 消息面汇总（盘前）2026-10-20\n\n正文"
    fake_result = {"status": "success", "reason": None, "report": report_markdown}
    with patch(
        "src.services.news_digest_service.build_news_digest_dependencies",
        return_value={"notifier": None, "intelligence_service": None, "db": None},
    ), patch(
        "src.services.news_digest_service.run_news_digest_once",
        return_value=fake_result,
    ) as run_mock:
        exit_code = main._run_news_digest_once_cli(SimpleNamespace())

    assert run_mock.call_count == 1
    _args_, kwargs = run_mock.call_args
    assert isinstance(kwargs.get("now"), datetime)
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert report_markdown in captured, "无论推送结果，摘要必须可见"
    assert "[news-digest] status=success" in captured


def test_cli_news_digest_failed_reports_nonzero(capsys):
    fake_result = {"status": "failed", "reason": "notification_failed", "report": "# 摘要"}
    with patch(
        "src.services.news_digest_service.build_news_digest_dependencies",
        return_value={"notifier": None, "intelligence_service": None, "db": None},
    ), patch(
        "src.services.news_digest_service.run_news_digest_once",
        return_value=fake_result,
    ):
        exit_code = main._run_news_digest_once_cli(SimpleNamespace())
    assert exit_code == 1
    assert "failed" in capsys.readouterr().out


def test_cli_dependency_assembly_failure_never_raises(capsys):
    """组装器意外抛异常：CLI 兜底全量降级（空依赖），仍完成运行并打印状态。"""
    fake_result = {"status": "skipped", "reason": "disabled", "report": ""}
    with patch(
        "src.services.news_digest_service.build_news_digest_dependencies",
        side_effect=RuntimeError("assembly exploded"),
    ), patch(
        "src.services.news_digest_service.run_news_digest_once",
        return_value=fake_result,
    ) as run_mock:
        exit_code = main._run_news_digest_once_cli(SimpleNamespace())

    _args_, kwargs = run_mock.call_args
    assert kwargs.get("intelligence_service") is None
    assert kwargs.get("notifier") is None
    assert "（本次未生成消息面汇总内容）" in capsys.readouterr().out
    assert exit_code == 1


# ---------------------------------------------------------------------------
# CLI 真实依赖组装（OR-COR-000c926a：--news-digest 不得恒生成无数据模板）
# ---------------------------------------------------------------------------


class _RecordingNotifier:
    def __init__(self):
        self.calls = []

    def send(self, content, **kwargs):
        self.calls.append(dict(kwargs, content=content))
        return True


class _RecordingIntelligence:
    def __init__(self, rows):
        self._rows = rows
        self.fetch_called = False

    def fetch_enabled_sources(self):
        self.fetch_called = True
        return {"ok": True}

    class _Repo:
        def __init__(self, rows):
            self._rows = rows

        def list_items(self, **kwargs):
            return list(self._rows), len(self._rows)

    @property
    def repo(self):
        return self._Repo(self._rows)


class _FakeClock(datetime):
    """固定时钟：2026-10-20 周二 08:30（盘前窗口内）；替换 main.datetime 供 CLI 注入。"""

    @classmethod
    def now(cls, tz=None):  # noqa: ARG004 - 与 datetime.now 签名兼容
        return datetime(2026, 10, 20, 8, 30)


def test_cli_news_digest_assembles_real_dependencies(tmp_path, monkeypatch, capsys):
    """--news-digest 集成路径：CLI 必须组装真实依赖并注入服务（不 mock
    run_news_digest_once），否则生产输出恒为无数据模板（OR-COR-000c926a）。"""
    monkeypatch.setattr(main, "datetime", _FakeClock)
    digest_notifier = _RecordingNotifier()
    digest_intelligence = _RecordingIntelligence(rows=[
        SimpleNamespace(
            id=1, title="真实池内快讯", summary="池内正文", url="https://f.cn/1",
            source="华尔街见闻", published_at=datetime(2026, 10, 20, 8, 0),
            fetched_at=datetime(2026, 10, 20, 8, 10),
        ),
    ])
    config = SimpleNamespace(
        news_digest_enabled=True,
        news_digest_premarket_window="08:00-09:15",
        news_digest_offday_window="09:00-18:00",
        news_digest_max_news=12,
        database_path=str(tmp_path / "cli_digest.db"),
    )

    with patch(
        "src.core.market_review_runtime.build_market_review_runtime",
        return_value=(digest_notifier, None, None),
    ) as runtime_mock, patch(
        "src.services.intelligence_service.IntelligenceService",
        return_value=digest_intelligence,
    ):
        exit_code = main._run_news_digest_once_cli(config)

    assert runtime_mock.call_count >= 1
    assert exit_code == 0
    assert digest_intelligence.fetch_called, "资讯池依赖未组装：CLI 未传入 intelligence_service"
    assert len(digest_notifier.calls) == 1, "通知依赖未组装：真实通知服务未注入"
    captured = capsys.readouterr().out
    assert "# 消息面汇总" in captured
    assert "真实池内快讯" in captured, "真实资讯池条目应进入最终摘要而非空模板"


def test_build_news_digest_dependencies_fail_open():
    """共享组装器契约：任一依赖构造失败仅降级 None，绝不向上抛。"""
    with patch(
        "src.core.market_review_runtime.build_market_review_runtime",
        side_effect=RuntimeError("runtime down"),
    ), patch(
        "src.services.intelligence_service.IntelligenceService",
        side_effect=RuntimeError("repo down"),
    ):
        deps = news_digest_service.build_news_digest_dependencies(SimpleNamespace())
    assert deps == {"notifier": None, "intelligence_service": None}


def test_build_news_digest_dependencies_assembles_all():
    """共享组装器正常路径：两类依赖全部组装到位（CLI 与后续调度 tick 共用）。"""
    sentinel_notifier, sentinel_intelligence = object(), object()
    with patch(
        "src.core.market_review_runtime.build_market_review_runtime",
        return_value=(sentinel_notifier, None, None),
    ), patch(
        "src.services.intelligence_service.IntelligenceService",
        return_value=sentinel_intelligence,
    ):
        deps = news_digest_service.build_news_digest_dependencies(SimpleNamespace())
    assert deps["notifier"] is sentinel_notifier
    assert deps["intelligence_service"] is sentinel_intelligence
