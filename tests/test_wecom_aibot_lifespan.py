# -*- coding: utf-8 -*-
"""
App lifespan wiring for the WeCom AI Bot long connection (Issue #755 r4,
review OR-COR-3c2d44f1).

The uvicorn entrypoint (`uvicorn server:app` → api.app's app_lifespan) never
started the long connection — only main.py --serve/--serve-only did, so a
documented uvicorn deployment never connected (conversation + push dead).

Contract:
- WECOM_AIBOT_ENABLED=true  → lifespan calls start_wecom_aibot_background()
  once and keeps the client reference on app.state; on shutdown the client is
  stopped gracefully (once).
- WECOM_AIBOT_ENABLED=false → zero side effects (start not called, no state).
- start failing (missing SDK/credentials) → no state, no stop.
"""

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from src.services.runtime_scheduler import CLI_SCHEDULER_OWNER_ENV


class _FakeRuntimeSchedulerService:
    def __init__(self, owns_schedule=False, force_enabled=False, **kwargs):
        self.owns_schedule = owns_schedule

    def reconcile_from_config(self, **kwargs):
        return None

    def stop(self):
        return None


class _FakeSystemConfigService:
    def __init__(self, runtime_scheduler=None):
        self.runtime_scheduler = runtime_scheduler


def _run_lifespan(wecom_aibot_enabled: bool, start_result: bool = True):
    """Drive the real app_lifespan with heavy deps patched; return mocks."""
    fake_client = mock.MagicMock()
    with tempfile.TemporaryDirectory() as tmp_dir, patch.dict(
        os.environ, {CLI_SCHEDULER_OWNER_ENV: "true"}, clear=False
    ), patch(
        "src.config.get_config",
        return_value=SimpleNamespace(
            schedule_run_immediately=False,
            wecom_aibot_enabled=wecom_aibot_enabled,
        ),
    ), patch(
        "api.app.RuntimeSchedulerService", _FakeRuntimeSchedulerService
    ), patch(
        "api.app.SystemConfigService", _FakeSystemConfigService
    ), patch(
        "api.app._schedule_stock_index_background_refresh"
    ), patch(
        "bot.platforms.wecom_aibot.start_wecom_aibot_background",
        return_value=start_result,
    ) as m_start, patch(
        "bot.platforms.wecom_aibot.get_wecom_aibot_client",
        return_value=fake_client,
    ) as m_get:
        from api.app import create_app

        app = create_app(static_dir=Path(tmp_dir))
        with TestClient(app):
            started_ref = getattr(app.state, "wecom_aibot_client", None)
        yield m_start, m_get, started_ref, fake_client


class TestAppLifespanWecomAibot:
    def test_enabled_lifespan_starts_connection_and_stops_on_shutdown(self):
        """RED(OR-COR-3c2d44f1)：uvicorn 入口必须启动长连接，关闭时优雅停止。"""
        gen = _run_lifespan(wecom_aibot_enabled=True, start_result=True)
        m_start, m_get, started_ref, fake_client = next(gen)

        assert m_start.call_count == 1
        assert started_ref is fake_client

        # generator cleanup = lifespan shutdown
        try:
            next(gen)
        except StopIteration:
            pass
        fake_client.stop.assert_called_once()

    def test_disabled_lifespan_has_zero_side_effects(self):
        """WECOM_AIBOT_ENABLED=false：不启动、不引用客户端、关闭零动作。"""
        gen = _run_lifespan(wecom_aibot_enabled=False)
        m_start, m_get, started_ref, fake_client = next(gen)

        assert m_start.call_count == 0
        assert started_ref is None

        try:
            next(gen)
        except StopIteration:
            pass
        fake_client.stop.assert_not_called()

    def test_start_failure_records_no_client_and_skips_stop(self):
        """启动失败（缺 SDK/凭证）→ 不留引用、shutdown 不 stop。"""
        gen = _run_lifespan(wecom_aibot_enabled=True, start_result=False)
        m_start, m_get, started_ref, fake_client = next(gen)

        assert m_start.call_count == 1
        assert started_ref is None

        try:
            next(gen)
        except StopIteration:
            pass
        fake_client.stop.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])
