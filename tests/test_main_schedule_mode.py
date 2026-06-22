# -*- coding: utf-8 -*-
"""Regression tests for scheduled mode stock selection behavior."""

import json
import logging
import os
import socket
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

_ENV_BEFORE_MAIN_IMPORT = dict(os.environ)
import main
from src.config import Config

_MAIN_IMPORT_ENV_ADDITIONS = frozenset(set(os.environ) - set(_ENV_BEFORE_MAIN_IMPORT))
_MAIN_IMPORT_ENV_OVERRIDES = {
    key: value
    for key, value in _ENV_BEFORE_MAIN_IMPORT.items()
    if os.environ.get(key) != value
}


def _api_app_stub_modules():
    """sys.modules entries so ``start_api_server`` can ``from api.app import app``
    without importing the real (heavy) app tree in these isolated unit tests.

    ``start_api_server`` imports the ASGI app object in the calling thread so the
    import stays out of the uvicorn startup probe window; these control-flow tests
    stub it the same way they already stub uvicorn.
    """
    import types

    api_pkg = types.ModuleType("api")
    api_app_mod = types.ModuleType("api.app")
    api_app_mod.app = SimpleNamespace()
    api_pkg.app = api_app_mod
    return {"api": api_pkg, "api.app": api_app_mod}


class _DummyConfig(SimpleNamespace):
    def validate(self):
        return []


class MainScheduleModeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text("STOCK_LIST=600519\n", encoding="utf-8")
        self.original_cwd = os.getcwd()
        os.chdir(self.temp_dir.name)
        self.env_patch = patch.dict(os.environ, {"ENV_FILE": str(self.env_path)}, clear=False)
        self.env_patch.start()
        Config.reset_instance()
        root_logger = logging.getLogger()
        self._original_root_handlers = list(root_logger.handlers)
        self._original_root_level = root_logger.level

    def tearDown(self) -> None:
        root_logger = logging.getLogger()
        current_handlers = list(root_logger.handlers)
        for handler in current_handlers:
            if handler not in self._original_root_handlers:
                root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass
        root_logger.setLevel(self._original_root_level)
        os.chdir(self.original_cwd)
        Config.reset_instance()
        self.env_patch.stop()
        for key in _MAIN_IMPORT_ENV_ADDITIONS:
            os.environ.pop(key, None)
        for key, value in _MAIN_IMPORT_ENV_OVERRIDES.items():
            os.environ[key] = value
        self.temp_dir.cleanup()

    def _make_args(self, **overrides):
        defaults = {
            "debug": False,
            "stocks": None,
            "webui": False,
            "webui_only": False,
            "serve": False,
            "serve_only": False,
            "host": "0.0.0.0",
            "port": 8000,
            "backtest": False,
            "market_review": False,
            "schedule": False,
            "no_run_immediately": False,
            "no_notify": False,
            "check_notify": False,
            "no_market_review": False,
            "dry_run": False,
            "workers": 1,
            "force_run": False,
            "single_notify": False,
            "no_context_snapshot": False,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _make_config(self, **overrides):
        defaults = {
            "log_dir": self.temp_dir.name,
            "webui_enabled": False,
            "dingtalk_stream_enabled": False,
            "feishu_stream_enabled": False,
            "schedule_enabled": False,
            "schedule_time": "18:00",
            "schedule_run_immediately": True,
            "run_immediately": True,
            "agent_event_monitor_enabled": False,
            "agent_event_alert_rules_json": "",
            "agent_event_monitor_interval_minutes": 5,
            "daily_market_context_enabled": True,
        }
        defaults.update(overrides)
        return _DummyConfig(**defaults)

    def test_public_webui_bind_warns_when_auth_is_disabled(self) -> None:
        with patch("src.auth.is_auth_enabled", return_value=False), \
             patch("main.logger.warning") as warning_log:
            main._warn_if_public_webui_without_auth("0.0.0.0")

        warning_log.assert_called_once()
        self.assertIn("WEBUI_HOST=%s", warning_log.call_args.args[0])
        self.assertEqual(warning_log.call_args.args[1], "0.0.0.0")

    def test_loopback_webui_bind_does_not_warn_when_auth_is_disabled(self) -> None:
        with patch("src.auth.is_auth_enabled", return_value=False), \
             patch("main.logger.warning") as warning_log:
            main._warn_if_public_webui_without_auth("127.0.0.1")

        warning_log.assert_not_called()

    def test_start_api_server_fails_before_thread_when_port_is_busy(self) -> None:
        config = self._make_config(log_level="INFO")

        class BusySocket:
            def bind(self, address):
                raise OSError("address already in use")

            def close(self):
                pass

        with patch("socket.socket", return_value=BusySocket()) as socket_factory, \
             patch("threading.Thread") as thread_cls:
            with self.assertRaises(RuntimeError) as caught:
                main.start_api_server("127.0.0.1", 8000, config)

        socket_factory.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        self.assertIn("127.0.0.1:8000", str(caught.exception))
        thread_cls.assert_not_called()

    def test_start_api_server_fails_when_uvicorn_background_startup_fails(self) -> None:
        config = self._make_config(log_level="INFO")

        class _FakeUvicornServer:
            def __init__(self, config):
                self.config = config
                self.started = False

            def run(self) -> None:
                raise RuntimeError("lifespan bootstrap failed")

        class _FakeUvicornConfig:
            def __init__(self, *args, **kwargs):
                pass

        class _FakeUvicornModule:
            Config = _FakeUvicornConfig

            Server = _FakeUvicornServer

        class _UnusedSocket:
            def bind(self, address):
                pass

            def close(self):
                pass

        with patch("socket.socket", return_value=_UnusedSocket()), \
             patch.dict(
                 "sys.modules",
                 {"uvicorn": _FakeUvicornModule(), **_api_app_stub_modules()},
             ):

            with self.assertRaises(RuntimeError) as caught:
                main.start_api_server("127.0.0.1", 8000, config)

        self.assertIn("lifespan bootstrap failed", str(caught.exception))

    def test_start_api_server_compatible_with_uvicorn_install_signal_handlers_method(self) -> None:
        config = self._make_config(log_level="INFO")

        class _CompatServer:
            instance = None

            def __init__(self, config):
                type(self).instance = self
                self.config = config
                self.started = False
                self.install_signal_handlers = self._install_signal_handlers

            def _install_signal_handlers(self) -> None:
                return None

            def run(self) -> None:
                self.started = True

        class _CompatConfig:
            def __init__(self, *args, **kwargs):
                if "install_signal_handlers" in kwargs:
                    raise TypeError("install_signal_handlers is unsupported")

        class _UnusedSocket:
            def bind(self, address):
                pass

            def close(self):
                pass

        with patch("socket.socket", return_value=_UnusedSocket()), \
             patch.dict(
                 "sys.modules",
                 {
                     "uvicorn": SimpleNamespace(Config=_CompatConfig, Server=_CompatServer),
                     **_api_app_stub_modules(),
                 },
             ):
            main.start_api_server("127.0.0.1", 8000, config)

        self.assertIsNotNone(_CompatServer.instance)
        self.assertTrue(callable(_CompatServer.instance.install_signal_handlers))
        self.assertTrue(_CompatServer.instance.started)

    def test_schedule_mode_ignores_cli_stock_snapshot(self) -> None:
        args = self._make_args(schedule=True, stocks="600519,000001")
        config = self._make_config(schedule_enabled=False)
        scheduled_call = {}

        def fake_run_with_schedule(
            task,
            schedule_time,
            run_immediately,
            background_tasks=None,
            schedule_time_provider=None,
        ):
            scheduled_call["schedule_time"] = schedule_time
            scheduled_call["run_immediately"] = run_immediately
            scheduled_call["background_tasks"] = background_tasks or []
            scheduled_call["resolved_schedule_time"] = (
                schedule_time_provider() if schedule_time_provider is not None else None
            )
            task()

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main._reload_runtime_config", return_value=config), \
             patch("main._build_schedule_time_provider", return_value=lambda: "18:00"), \
             patch("main.setup_logging"), \
             patch("main.run_full_analysis") as run_full_analysis, \
             patch("main.logger.warning") as warning_log, \
             patch("src.scheduler.run_with_schedule", side_effect=fake_run_with_schedule):
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            scheduled_call,
            {
                "schedule_time": "18:00",
                "run_immediately": True,
                "background_tasks": [],
                "resolved_schedule_time": "18:00",
            },
        )
        run_full_analysis.assert_called_once_with(config, args, None)
        warning_log.assert_any_call(
            "定时模式下检测到 --stocks 参数；计划执行将忽略启动时股票快照，并在每次运行前重新读取最新的 STOCK_LIST。"
        )

    def test_standalone_run_resolves_stocks_before_run_full_analysis(self) -> None:
        args = self._make_args(stocks="005930")
        config = self._make_config(run_immediately=True)

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.setup_logging"), \
             patch("main.run_full_analysis") as run_full_analysis:
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        run_full_analysis.assert_called_once()
        _, _, stock_codes = run_full_analysis.call_args.args
        self.assertEqual(stock_codes, ["005930.KS"])

    def test_schedule_mode_reload_uses_latest_runtime_config(self) -> None:
        args = self._make_args(schedule=True)
        startup_config = self._make_config(schedule_enabled=True, schedule_time="18:00")
        runtime_config = self._make_config(schedule_enabled=True, schedule_time="09:30")
        scheduled_call = {}

        def fake_run_with_schedule(
            task,
            schedule_time,
            run_immediately,
            background_tasks=None,
            schedule_time_provider=None,
        ):
            scheduled_call["schedule_time"] = schedule_time
            scheduled_call["resolved_schedule_time"] = (
                schedule_time_provider() if schedule_time_provider is not None else None
            )
            task()

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=startup_config), \
             patch("main._reload_runtime_config", return_value=runtime_config), \
             patch("main._build_schedule_time_provider", return_value=lambda: "09:30"), \
             patch("main.setup_logging"), \
             patch("main.run_full_analysis") as run_full_analysis, \
             patch("src.scheduler.run_with_schedule", side_effect=fake_run_with_schedule):
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            scheduled_call,
            {"schedule_time": "18:00", "resolved_schedule_time": "09:30"},
        )
        run_full_analysis.assert_called_once_with(runtime_config, args, None)

    def test_schedule_mode_registers_event_monitor_background_task(self) -> None:
        args = self._make_args(schedule=True)
        config = self._make_config(
            schedule_enabled=False,
            agent_event_monitor_enabled=True,
            agent_event_monitor_interval_minutes=7,
        )
        worker = MagicMock()
        worker.run_once.return_value = {"triggered": 2}
        scheduled_call = {}

        def fake_run_with_schedule(
            task,
            schedule_time,
            run_immediately,
            background_tasks=None,
            schedule_time_provider=None,
        ):
            scheduled_call["schedule_time"] = schedule_time
            scheduled_call["run_immediately"] = run_immediately
            scheduled_call["background_tasks"] = background_tasks or []
            scheduled_call["resolved_schedule_time"] = (
                schedule_time_provider() if schedule_time_provider is not None else None
            )

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main._reload_runtime_config", return_value=config) as reload_config, \
             patch("main._build_schedule_time_provider", return_value=lambda: "18:00"), \
             patch("main.setup_logging"), \
             patch("main.run_full_analysis") as run_full_analysis, \
             patch("src.services.alert_worker.AlertWorker", return_value=worker) as worker_cls, \
             patch("src.scheduler.run_with_schedule", side_effect=fake_run_with_schedule):
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        worker_cls.assert_called_once()
        self.assertIs(worker_cls.call_args.kwargs["config_provider"], reload_config)
        run_full_analysis.assert_not_called()
        self.assertEqual(scheduled_call["schedule_time"], "18:00")
        self.assertEqual(scheduled_call["run_immediately"], True)
        self.assertEqual(scheduled_call["resolved_schedule_time"], "18:00")
        self.assertEqual(len(scheduled_call["background_tasks"]), 1)
        background_task = scheduled_call["background_tasks"][0]
        self.assertEqual(background_task["name"], "agent_event_monitor")
        self.assertEqual(background_task["interval_seconds"], 7 * 60)
        self.assertEqual(background_task["run_immediately"], True)

        with patch("main.logger.info") as info_log:
            background_task["task"]()

        worker.run_once.assert_called_once_with()
        info_log.assert_any_call("[EventMonitor] 本轮触发 %d 条提醒", 2)

    def test_schedule_mode_registers_event_monitor_worker_without_legacy_rules(self) -> None:
        args = self._make_args(schedule=True)
        config = self._make_config(
            schedule_enabled=False,
            agent_event_monitor_enabled=True,
            agent_event_alert_rules_json="",
        )
        worker = MagicMock()
        worker.run_once.return_value = {"triggered": 0}
        scheduled_call = {}

        def fake_run_with_schedule(
            task,
            schedule_time,
            run_immediately,
            background_tasks=None,
            schedule_time_provider=None,
        ):
            scheduled_call["background_tasks"] = background_tasks or []

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main._reload_runtime_config", return_value=config), \
             patch("main._build_schedule_time_provider", return_value=lambda: "18:00"), \
             patch("main.setup_logging"), \
             patch("main.run_full_analysis") as run_full_analysis, \
             patch("src.services.alert_worker.AlertWorker", return_value=worker) as worker_cls, \
             patch("src.scheduler.run_with_schedule", side_effect=fake_run_with_schedule):
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        worker_cls.assert_called_once()
        run_full_analysis.assert_not_called()
        self.assertEqual(len(scheduled_call["background_tasks"]), 1)
        self.assertEqual(scheduled_call["background_tasks"][0]["name"], "agent_event_monitor")

    def test_check_notify_returns_before_other_modes(self) -> None:
        args = self._make_args(check_notify=True, serve=True, schedule=True, market_review=True)
        config = self._make_config(webui_enabled=False)
        diagnostic_result = SimpleNamespace(ok=True)

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.setup_logging"), \
             patch("main.start_api_server") as start_api_server, \
             patch("main.run_full_analysis") as run_full_analysis, \
             patch(
                 "src.services.notification_diagnostics.run_notification_diagnostics",
                 return_value=diagnostic_result,
             ) as run_diagnostics, \
             patch(
                 "src.services.notification_diagnostics.format_notification_diagnostics",
                 return_value="通知配置诊断",
             ), \
             patch("builtins.print") as print_output:
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        run_diagnostics.assert_called_once_with(config)
        print_output.assert_called_once_with("通知配置诊断")
        start_api_server.assert_not_called()
        run_full_analysis.assert_not_called()

    def test_serve_mode_exits_when_api_server_start_fails(self) -> None:
        args = self._make_args(serve_only=True, host="127.0.0.1", port=8000)
        config = self._make_config(webui_enabled=False)

        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}, clear=False), \
             patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.prepare_webui_frontend_assets", return_value=True), \
             patch("main.start_api_server", side_effect=RuntimeError("port busy")), \
             patch("main.start_bot_stream_clients") as start_bots, \
             patch("main.logger.error") as error_log:
            exit_code = main.main()

        self.assertEqual(exit_code, 1)
        start_bots.assert_not_called()
        error_log.assert_called_once()

    def test_webui_only_maps_to_serve_only_and_exits_when_api_server_start_fails(self) -> None:
        args = self._make_args(webui_only=True, host="127.0.0.1", port=8000)
        config = self._make_config(webui_enabled=False)

        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}, clear=False), \
             patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.prepare_webui_frontend_assets", return_value=True), \
             patch("main.start_api_server", side_effect=RuntimeError("port busy")), \
             patch("main.start_bot_stream_clients") as start_bots, \
             patch("main.run_full_analysis") as run_full_analysis, \
             patch("main.logger.error") as error_log:
            exit_code = main.main()

        self.assertEqual(exit_code, 1)
        start_bots.assert_not_called()
        run_full_analysis.assert_not_called()
        error_log.assert_called_once()

    def test_serve_mode_continues_single_analysis_when_api_server_start_fails(self) -> None:
        args = self._make_args(serve=True, host="127.0.0.1", port=8000)
        config = self._make_config(webui_enabled=False, run_immediately=True)

        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}, clear=False), \
             patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.prepare_webui_frontend_assets", return_value=True), \
             patch("main.start_api_server", side_effect=RuntimeError("port busy")), \
             patch("main.start_bot_stream_clients") as start_bots, \
             patch("main.run_full_analysis") as run_full_analysis, \
             patch("main._run_analysis_with_runtime_scheduler_lock") as run_with_lock, \
             patch("main.logger.error") as error_log:
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        start_bots.assert_not_called()
        run_with_lock.assert_called_once_with(config, args, None)
        run_full_analysis.assert_not_called()
        error_log.assert_called_once()

    def test_serve_schedule_mode_continues_scheduler_when_api_server_start_fails(self) -> None:
        args = self._make_args(serve=True, schedule=True, host="127.0.0.1", port=8000)
        config = self._make_config(webui_enabled=False, schedule_enabled=False)
        scheduled_call = {}

        def fake_run_with_schedule(
            task,
            schedule_time,
            run_immediately,
            background_tasks=None,
            schedule_time_provider=None,
        ):
            scheduled_call["schedule_time"] = schedule_time
            scheduled_call["run_immediately"] = run_immediately
            scheduled_call["background_tasks"] = background_tasks or []
            task()

        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}, clear=False), \
             patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main._reload_runtime_config", return_value=config), \
             patch("main._build_schedule_time_provider", return_value=lambda: "18:00"), \
             patch("main.prepare_webui_frontend_assets", return_value=True), \
             patch("main.start_api_server", side_effect=RuntimeError("port busy")), \
             patch("main.start_bot_stream_clients") as start_bots, \
             patch("main.run_full_analysis") as run_full_analysis, \
             patch("src.scheduler.run_with_schedule", side_effect=fake_run_with_schedule), \
             patch("main.logger.error") as error_log:
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        start_bots.assert_not_called()
        run_full_analysis.assert_called_once_with(config, args, None)
        self.assertEqual(scheduled_call["schedule_time"], "18:00")
        self.assertEqual(scheduled_call["run_immediately"], True)
        self.assertEqual(scheduled_call["background_tasks"], [])
        error_log.assert_called_once()

    def test_serve_with_enabled_schedule_uses_api_runtime_scheduler(self) -> None:
        from src.services.runtime_scheduler import (
            CLI_SCHEDULER_OWNER_ENV,
            RUNTIME_SCHEDULER_ARGS_ENV,
            RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV,
        )

        args = self._make_args(
            serve=True,
            schedule=False,
            host="127.0.0.1",
            port=8000,
            no_notify=True,
            no_market_review=True,
            dry_run=True,
            force_run=True,
            single_notify=True,
            no_context_snapshot=True,
            workers=4,
        )
        config = self._make_config(webui_enabled=False, schedule_enabled=True)
        marker_seen_by_server = []
        run_immediately_seen_by_server = []
        runtime_args_seen_by_server = []

        def fake_start_api_server(host, port, config):
            marker_seen_by_server.append(os.getenv(CLI_SCHEDULER_OWNER_ENV))
            run_immediately_seen_by_server.append(os.getenv(RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV))
            runtime_args_seen_by_server.append(json.loads(os.getenv(RUNTIME_SCHEDULER_ARGS_ENV, "{}")))

        with patch.dict(
            os.environ,
            {"GITHUB_ACTIONS": "false", CLI_SCHEDULER_OWNER_ENV: "true"},
            clear=False,
        ), \
             patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.prepare_webui_frontend_assets", return_value=True), \
             patch("main.start_api_server", side_effect=fake_start_api_server), \
             patch("main.start_bot_stream_clients") as start_bots, \
             patch("main.time.sleep", side_effect=KeyboardInterrupt), \
             patch("src.scheduler.run_with_schedule") as run_with_schedule:
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(marker_seen_by_server, [None])
        self.assertEqual(run_immediately_seen_by_server, ["true"])
        self.assertEqual(runtime_args_seen_by_server, [{
            "no_notify": True,
            "no_market_review": True,
            "dry_run": True,
            "force_run": True,
            "single_notify": True,
            "no_context_snapshot": True,
            "workers": 4,
        }])
        start_bots.assert_called_once_with(config)
        run_with_schedule.assert_not_called()

    def test_serve_mode_uses_shared_analysis_lock_for_immediate_run_full_analysis(self) -> None:
        args = self._make_args(serve=True, schedule=False, host="127.0.0.1", port=8000)
        config = self._make_config(webui_enabled=False, run_immediately=True)

        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}, clear=False), \
             patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.prepare_webui_frontend_assets", return_value=True), \
             patch("main.start_api_server"), \
             patch("main.start_bot_stream_clients") as start_bots, \
             patch("main.time.sleep", side_effect=KeyboardInterrupt), \
             patch("main.run_full_analysis") as run_full_analysis, \
             patch("main._run_analysis_with_runtime_scheduler_lock") as run_with_lock:
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_with_lock.call_count, 1)
        run_with_lock.assert_called_once_with(config, args, None)
        run_full_analysis.assert_not_called()
        start_bots.assert_called_once_with(config)

    def test_serve_schedule_flag_enables_api_runtime_scheduler(self) -> None:
        from src.services.runtime_scheduler import (
            CLI_SCHEDULER_OWNER_ENV,
            RUNTIME_SCHEDULER_ARGS_ENV,
            RUNTIME_SCHEDULER_FORCE_ENABLED_ENV,
            RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV,
        )

        args = self._make_args(
            serve=True,
            schedule=True,
            host="127.0.0.1",
            port=8000,
            no_notify=True,
            no_market_review=True,
            dry_run=True,
            force_run=True,
            single_notify=True,
            no_context_snapshot=True,
            workers=4,
        )
        config = self._make_config(webui_enabled=False, schedule_enabled=False)
        marker_seen_by_server = []
        force_enabled_seen_by_server = []
        run_immediately_seen_by_server = []
        runtime_args_seen_by_server = []

        def fake_start_api_server(host, port, config):
            marker_seen_by_server.append(os.getenv(CLI_SCHEDULER_OWNER_ENV))
            force_enabled_seen_by_server.append(os.getenv(RUNTIME_SCHEDULER_FORCE_ENABLED_ENV))
            run_immediately_seen_by_server.append(os.getenv(RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV))
            runtime_args_seen_by_server.append(json.loads(os.getenv(RUNTIME_SCHEDULER_ARGS_ENV, "{}")))

        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}, clear=False), \
             patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.prepare_webui_frontend_assets", return_value=True), \
             patch("main.start_api_server", side_effect=fake_start_api_server), \
             patch("main.start_bot_stream_clients"), \
             patch("main.time.sleep", side_effect=KeyboardInterrupt), \
             patch("src.scheduler.run_with_schedule") as run_with_schedule:
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(marker_seen_by_server, [None])
        self.assertEqual(force_enabled_seen_by_server, ["true"])
        self.assertEqual(run_immediately_seen_by_server, ["true"])
        self.assertEqual(runtime_args_seen_by_server, [{
            "no_notify": True,
            "no_market_review": True,
            "dry_run": True,
            "force_run": True,
            "single_notify": True,
            "no_context_snapshot": True,
            "workers": 4,
        }])
        self.assertFalse(config.schedule_enabled)
        run_with_schedule.assert_not_called()

    def test_serve_schedule_flag_passes_no_run_immediately_to_runtime_scheduler(self) -> None:
        from src.services.runtime_scheduler import RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV

        args = self._make_args(
            serve=True,
            schedule=True,
            no_run_immediately=True,
            host="127.0.0.1",
            port=8000,
        )
        config = self._make_config(webui_enabled=False, schedule_enabled=False)
        run_immediately_seen_by_server = []

        def fake_start_api_server(host, port, config):
            run_immediately_seen_by_server.append(os.getenv(RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV))

        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}, clear=False), \
             patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.prepare_webui_frontend_assets", return_value=True), \
             patch("main.start_api_server", side_effect=fake_start_api_server), \
             patch("main.start_bot_stream_clients"), \
             patch("main.time.sleep", side_effect=KeyboardInterrupt), \
             patch("src.scheduler.run_with_schedule") as run_with_schedule:
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_immediately_seen_by_server, ["false"])
        run_with_schedule.assert_not_called()

    def test_serve_only_suppresses_startup_scheduler_without_disabling_runtime_owner(self) -> None:
        from src.services.runtime_scheduler import (
            CLI_SCHEDULER_OWNER_ENV,
            RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV,
            RUNTIME_SCHEDULER_SUPPRESS_START_ENV,
        )

        args = self._make_args(serve_only=True, host="127.0.0.1", port=8000)
        config = self._make_config(webui_enabled=False, schedule_enabled=True)
        marker_seen_by_server = []
        suppress_seen_by_server = []
        run_immediately_seen_by_server = []

        def fake_start_api_server(host, port, config):
            marker_seen_by_server.append(os.getenv(CLI_SCHEDULER_OWNER_ENV))
            suppress_seen_by_server.append(os.getenv(RUNTIME_SCHEDULER_SUPPRESS_START_ENV))
            run_immediately_seen_by_server.append(os.getenv(RUNTIME_SCHEDULER_RUN_IMMEDIATELY_ENV))

        with patch.dict(
            os.environ,
            {"GITHUB_ACTIONS": "false", CLI_SCHEDULER_OWNER_ENV: "true"},
            clear=False,
        ), \
             patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.prepare_webui_frontend_assets", return_value=True), \
             patch("main.start_api_server", side_effect=fake_start_api_server), \
             patch("main.start_bot_stream_clients") as start_bots, \
             patch("main.time.sleep", side_effect=KeyboardInterrupt), \
             patch("src.scheduler.run_with_schedule") as run_with_schedule:
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(marker_seen_by_server, [None])
        self.assertEqual(suppress_seen_by_server, ["true"])
        self.assertEqual(run_immediately_seen_by_server, [None])
        start_bots.assert_called_once_with(config)
        run_with_schedule.assert_not_called()

    def test_reload_runtime_config_preserves_process_env_overrides(self) -> None:
        self.env_path.write_text(
            "OPENAI_API_KEY=stale-file\nSCHEDULE_TIME=09:30\n",
            encoding="utf-8",
        )
        runtime_config = self._make_config(schedule_enabled=True, schedule_time="09:30")

        with patch.dict(
            os.environ,
            {
                "ENV_FILE": str(self.env_path),
                "OPENAI_API_KEY": "runtime-secret",
                "SCHEDULE_TIME": "18:00",
            },
            clear=False,
        ), patch.object(
            main,
            "_INITIAL_PROCESS_ENV",
            {"OPENAI_API_KEY": "runtime-secret"},
        ), patch.object(
            main,
            "_RUNTIME_ENV_FILE_KEYS",
            {"SCHEDULE_TIME"},
        ), patch(
            "main.get_config",
            return_value=runtime_config,
        ) as get_config_mock:
            reloaded_config = main._reload_runtime_config()
            self.assertEqual(os.environ["OPENAI_API_KEY"], "runtime-secret")
            self.assertEqual(os.environ["SCHEDULE_TIME"], "09:30")

        self.assertIs(reloaded_config, runtime_config)
        get_config_mock.assert_called_once_with()

    def test_reload_env_file_values_preserves_managed_env_vars_when_read_fails(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ENV_FILE": str(self.env_path),
                "OPENAI_API_KEY": "runtime-secret",
                "SCHEDULE_TIME": "09:30",
            },
            clear=False,
        ), patch.object(
            main,
            "_INITIAL_PROCESS_ENV",
            {},
        ), patch.object(
            main,
            "_RUNTIME_ENV_FILE_KEYS",
            {"OPENAI_API_KEY", "SCHEDULE_TIME"},
        ), patch(
            "main.dotenv_values",
            side_effect=OSError("boom"),
        ):
            main._reload_env_file_values_preserving_overrides()

            self.assertEqual(os.environ["OPENAI_API_KEY"], "runtime-secret")
            self.assertEqual(os.environ["SCHEDULE_TIME"], "09:30")
            self.assertEqual(
                main._RUNTIME_ENV_FILE_KEYS,
                {"OPENAI_API_KEY", "SCHEDULE_TIME"},
            )

    def test_reload_runtime_config_refreshes_env_before_resetting_singleton(self) -> None:
        runtime_config = self._make_config(schedule_enabled=True, schedule_time="09:30")
        call_order = []

        def fake_reload_env() -> None:
            call_order.append("reload_env")

        def fake_reset_instance() -> None:
            call_order.append("reset_instance")

        def fake_get_config():
            call_order.append("get_config")
            return runtime_config

        with patch(
            "main._reload_env_file_values_preserving_overrides",
            side_effect=fake_reload_env,
        ), patch(
            "main.Config.reset_instance",
            side_effect=fake_reset_instance,
        ), patch(
            "main.get_config",
            side_effect=fake_get_config,
        ):
            reloaded_config = main._reload_runtime_config()

        self.assertIs(reloaded_config, runtime_config)
        self.assertEqual(call_order, ["reload_env", "reset_instance", "get_config"])

    def test_schedule_time_provider_propagates_config_read_failures(self) -> None:
        with patch.object(
            main,
            "_INITIAL_PROCESS_ENV",
            {},
        ), patch(
            "src.core.config_manager.ConfigManager.read_config_map",
            side_effect=RuntimeError("boom"),
        ):
            provider = main._build_schedule_time_provider("18:00")

            with self.assertRaisesRegex(RuntimeError, "boom"):
                provider()

    def test_schedule_time_provider_respects_process_env_precedence(self) -> None:
        with patch.dict(
            os.environ,
            {"SCHEDULE_TIME": "18:00"},
            clear=False,
        ), patch.object(
            main,
            "_INITIAL_PROCESS_ENV",
            {"SCHEDULE_TIME": "18:00"},
        ), patch(
            "src.core.config_manager.ConfigManager.read_config_map",
            side_effect=AssertionError("should not read .env when process env override exists"),
        ):
            provider = main._build_schedule_time_provider("09:30")

            self.assertEqual(provider(), "18:00")

    def test_schedule_time_provider_falls_back_to_system_default_on_clear(self) -> None:
        """When SCHEDULE_TIME is cleared/removed from config, provider returns '18:00'."""
        with patch.dict(
            os.environ,
            {"SCHEDULE_TIME": "09:30"},
            clear=False,
        ), patch.object(
            main,
            "_INITIAL_PROCESS_ENV",
            {},
        ), patch(
            "src.core.config_manager.ConfigManager.read_config_map",
            return_value={},
        ):
            provider = main._build_schedule_time_provider("09:30")
            self.assertEqual(provider(), "18:00")

    def test_schedule_time_provider_falls_back_to_system_default_on_empty(self) -> None:
        """When SCHEDULE_TIME is empty string in config, provider returns '18:00'."""
        with patch.dict(
            os.environ,
            {"SCHEDULE_TIME": "09:30"},
            clear=False,
        ), patch.object(
            main,
            "_INITIAL_PROCESS_ENV",
            {},
        ), patch(
            "src.core.config_manager.ConfigManager.read_config_map",
            return_value={"SCHEDULE_TIME": "  "},
        ):
            provider = main._build_schedule_time_provider("09:30")
            self.assertEqual(provider(), "18:00")

    def test_single_run_keeps_cli_stock_override(self) -> None:
        args = self._make_args(stocks="600519,000001")
        config = self._make_config(run_immediately=True)

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.setup_logging"), \
             patch("main.run_full_analysis") as run_full_analysis:
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        run_full_analysis.assert_called_once_with(config, args, ["600519", "000001"])

    def test_run_full_analysis_skips_market_review_when_shared_lock_is_held(self) -> None:
        from src.core.market_review_lock import (
            release_market_review_lock,
            try_acquire_market_review_lock,
        )

        args = self._make_args()
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            daily_market_context_enabled=True,
            no_market_review=False,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        events = []
        pipeline_kwargs = {}

        def refresh_index(config_arg):
            events.append("refresh")

        def build_pipeline(*args, **kwargs):
            events.append("pipeline")
            pipeline_kwargs.update(kwargs)
            return pipeline

        lock_token = try_acquire_market_review_lock(config)
        self.assertIsNotNone(lock_token)
        try:
            with patch.object(main, "_refresh_stock_index_cache_for_analysis", side_effect=refresh_index) as refresh, \
                 patch("src.core.pipeline.StockAnalysisPipeline", side_effect=build_pipeline), \
                 patch("src.core.market_review.run_market_review") as run_market_review:
                main.run_full_analysis(config, args, [])
        finally:
            release_market_review_lock(lock_token)

            refresh.assert_called_once_with(config)
        self.assertEqual(events[:2], ["refresh", "pipeline"])
        self.assertTrue(pipeline_kwargs["daily_market_context_allow_generate"])
        pipeline.run.assert_called_once()
        run_market_review.assert_not_called()

    def test_run_full_analysis_disables_generation_when_no_market_review_flag_set(self) -> None:
        args = self._make_args(no_market_review=True)
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            daily_market_context_enabled=True,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        pipeline_kwargs = {}

        def build_pipeline(*args, **kwargs):
            pipeline_kwargs.update(kwargs)
            return pipeline

        with patch.object(main, "_refresh_stock_index_cache_for_analysis") as refresh, \
             patch("main._compute_trading_day_filter", return_value=([], "cn", False)), \
             patch("src.core.pipeline.StockAnalysisPipeline", side_effect=build_pipeline), \
             patch("main._prime_daily_market_context") as prime_context, \
             patch("src.core.market_review.run_market_review") as run_market_review:
            main.run_full_analysis(config, args, [])

        self.assertFalse(pipeline_kwargs["daily_market_context_allow_generate"])
        self.assertEqual(pipeline_kwargs["daily_market_context_enabled"], False)
        prime_context.assert_not_called()
        run_market_review.assert_not_called()
        refresh.assert_called_once_with(config)

    def test_run_full_analysis_defaults_daily_context_on_without_disabling_market_review(self) -> None:
        args = self._make_args()
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        pipeline_kwargs = {}

        def build_pipeline(*args, **kwargs):
            pipeline_kwargs.update(kwargs)
            return pipeline

        with patch.object(main, "_refresh_stock_index_cache_for_analysis") as refresh, \
             patch("main._compute_trading_day_filter", return_value=([], "cn", False)), \
             patch("src.core.pipeline.StockAnalysisPipeline", side_effect=build_pipeline), \
             patch("main._prime_daily_market_context", side_effect=[("", ""), ("缓存摘要", "完整复盘")]) as prime_context, \
             patch("main._run_market_review_with_shared_lock", return_value=SimpleNamespace(report="大盘复盘")) as run_with_lock:
            main.run_full_analysis(config, args, [])

        self.assertTrue(pipeline_kwargs["daily_market_context_enabled"])
        self.assertTrue(pipeline_kwargs["daily_market_context_allow_generate"])
        self.assertEqual(prime_context.call_count, 2)
        run_with_lock.assert_called_once()
        refresh.assert_called_once_with(config)

    def test_run_full_analysis_primes_daily_market_context_before_stock_analysis(self) -> None:
        args = self._make_args()
        target_date = date(2026, 3, 26)
        reference_times = []
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            daily_market_context_enabled=True,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        pipeline_kwargs = {}

        def build_pipeline(*args, **kwargs):
            pipeline_kwargs.update(kwargs)
            return pipeline

        def resolve_target_date(region, current_time):
            self.assertEqual(region, "cn")
            reference_times.append(current_time)
            return target_date

        with patch.object(main, "_refresh_stock_index_cache_for_analysis") as refresh, \
             patch("main._compute_trading_day_filter", return_value=([], "cn", False)), \
             patch("main._resolve_daily_market_context_target_date", side_effect=resolve_target_date), \
             patch("src.core.pipeline.StockAnalysisPipeline", side_effect=build_pipeline), \
             patch("main._prime_daily_market_context", return_value=("大盘退潮，高风险，建议观望，仓位上限30%。", "完整复盘正文")) as prime_context, \
             patch("main._run_market_review_with_shared_lock") as run_with_lock, \
             patch("src.core.market_review.run_market_review") as run_market_review:
            main.run_full_analysis(config, args, [])

        self.assertTrue(pipeline_kwargs["daily_market_context_allow_generate"])
        prime_context.assert_has_calls(
            [
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=False,
                ),
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=True,
                    require_current_query_match=True,
                ),
            ]
        )
        self.assertEqual(len(reference_times), 1)
        self.assertIs(pipeline.run.call_args.kwargs["current_time"], reference_times[0])
        self.assertEqual(pipeline.run.call_args.kwargs["current_time"].tzinfo, timezone.utc)
        run_with_lock.assert_called_once()
        self.assertFalse(run_with_lock.call_args.kwargs["merge_notification"])
        self.assertTrue(run_with_lock.call_args.kwargs["send_notification"])
        run_market_review.assert_not_called()
        refresh.assert_called_once_with(config)
        pipeline.run.assert_called_once()

    def test_run_full_analysis_does_not_reuse_single_context_for_multi_market_review(self) -> None:
        args = self._make_args()
        target_date = date(2026, 3, 26)
        config = self._make_config(
            trading_day_check_enabled=True,
            market_review_region="both",
            market_review_enabled=True,
            daily_market_context_enabled=True,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        pipeline_kwargs = {}

        def build_pipeline(*args, **kwargs):
            pipeline_kwargs.update(kwargs)
            return pipeline

        with patch.object(main, "_refresh_stock_index_cache_for_analysis") as refresh, \
             patch("main._compute_trading_day_filter", return_value=([], "cn,us", False)), \
             patch("main._resolve_daily_market_context_target_date", return_value=target_date), \
             patch("src.core.pipeline.StockAnalysisPipeline", side_effect=build_pipeline), \
             patch("main._prime_daily_market_context", return_value=("A股缓存摘要", "")) as prime_context, \
             patch("main._run_market_review_with_shared_lock", return_value="多市场复盘") as run_with_lock, \
             patch("src.core.market_review.run_market_review") as run_market_review:
            main.run_full_analysis(config, args, [])

        self.assertTrue(pipeline_kwargs["daily_market_context_allow_generate"])
        prime_context.assert_has_calls(
            [
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn,us",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=False,
                ),
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn,us",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=True,
                    require_current_query_match=True,
                ),
            ]
        )
        run_with_lock.assert_called_once()
        self.assertEqual(run_with_lock.call_args.kwargs["override_region"], "cn,us")
        run_market_review.assert_not_called()
        refresh.assert_called_once_with(config)
        pipeline.run.assert_called_once()

    def test_prime_daily_market_context_readonly_mode_still_reuses_cached_context(self) -> None:
        target_date = date(2026, 3, 26)
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            market_review_region="cn",
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline._daily_market_context_service = None
        pipeline.db = MagicMock()
        pipeline.query_id = "prime-query"
        context = SimpleNamespace(source="analysis_history", summary="历史复盘摘要")
        service = MagicMock()
        service.get_context.return_value = context

        with patch(
            "src.services.daily_market_context.DailyMarketContextService",
            return_value=service,
        ) as service_cls:
            summary, full_report = main._prime_daily_market_context(
                config,
                pipeline=pipeline,
                region="cn",
                no_market_review=False,
                allow_generate=False,
                target_date=target_date,
                return_full_report=True,
            )

        self.assertEqual(summary, "历史复盘摘要")
        self.assertEqual(full_report, "")
        service_cls.assert_called_once_with(db_manager=pipeline.db)
        call_kwargs = service.get_context.call_args.kwargs
        self.assertEqual(call_kwargs["region"], "cn")
        self.assertFalse(call_kwargs["force_refresh"])
        self.assertFalse(call_kwargs["allow_generate"])
        self.assertFalse(call_kwargs["persist_market_review_history"])
        self.assertEqual(call_kwargs["target_date"], target_date)
        self.assertEqual(call_kwargs["current_query_id"], "prime-query")

    def test_prime_daily_market_context_query_fallback_reuses_runtime_context(self) -> None:
        target_date = date(2026, 3, 26)
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            market_review_region="cn",
            single_stock_notify=False,
            merge_email_notification=True,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline._daily_market_context_service = None
        pipeline.db = MagicMock()
        pipeline.query_id = "prime-query"
        context = SimpleNamespace(
            source="market_review_runtime",
            summary="本轮运行时复盘摘要",
            full_report="本轮运行时完整复盘",
            query_id="prime-query",
        )
        service = MagicMock()
        service.get_context.return_value = context

        with patch(
            "src.services.daily_market_context.DailyMarketContextService",
            return_value=service,
        ):
            summary, full_report = main._prime_daily_market_context(
                config,
                pipeline=pipeline,
                region="cn",
                no_market_review=False,
                allow_generate=False,
                target_date=target_date,
                return_full_report=True,
                require_current_query_match=True,
            )

        self.assertEqual(summary, "本轮运行时复盘摘要")
        self.assertEqual(full_report, "本轮运行时完整复盘")
        self.assertTrue(service.get_context.call_args.kwargs["require_query_id_match"])

    def test_run_full_analysis_generates_full_market_review_once_after_stock_analysis(self) -> None:
        args = self._make_args()
        target_date = date(2026, 3, 26)
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            daily_market_context_enabled=True,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        events = []
        pipeline.run.side_effect = lambda **kwargs: events.append("stock-run") or []
        pipeline_kwargs = {}

        def build_pipeline(*args, **kwargs):
            events.append("pipeline")
            pipeline_kwargs.update(kwargs)
            return pipeline

        def run_with_lock(*args, **kwargs):
            events.append("market-review")
            return SimpleNamespace(report="完整复盘")

        with patch.object(main, "_refresh_stock_index_cache_for_analysis") as refresh, \
             patch("main._compute_trading_day_filter", return_value=([], "cn", False)), \
             patch("main._resolve_daily_market_context_target_date", return_value=target_date), \
             patch("src.core.pipeline.StockAnalysisPipeline", side_effect=build_pipeline), \
             patch("main._prime_daily_market_context", return_value=("", "")) as prime_context, \
             patch("main._run_market_review_with_shared_lock", side_effect=run_with_lock) as run_with_lock_mock, \
             patch("src.core.market_review.run_market_review") as run_market_review:
            main.run_full_analysis(config, args, [])

        self.assertTrue(pipeline_kwargs["daily_market_context_allow_generate"])
        self.assertEqual(events, ["pipeline", "stock-run", "market-review"])
        query_scoped_read = unittest.mock.call(
            config,
            pipeline=pipeline,
            region="cn",
            no_market_review=False,
            allow_generate=False,
            target_date=target_date,
            return_full_report=True,
            require_current_query_match=True,
        )
        self.assertEqual(
            prime_context.call_args_list,
            [
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=False,
                ),
                query_scoped_read,
                query_scoped_read,
            ],
        )
        run_with_lock_mock.assert_called_once()
        run_market_review.assert_not_called()
        refresh.assert_called_once_with(config)
        pipeline.run.assert_called_once()

    def test_run_full_analysis_reuses_runtime_market_context_after_stock_analysis(self) -> None:
        args = self._make_args()
        target_date = date(2026, 3, 26)
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            daily_market_context_enabled=True,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        pipeline.notifier = MagicMock(
            is_available=MagicMock(return_value=True),
            send=MagicMock(return_value=True),
        )
        pipeline_kwargs = {}

        def build_pipeline(*args, **kwargs):
            pipeline_kwargs.update(kwargs)
            return pipeline

        runtime_context = ("本轮运行时复盘摘要", "## 本轮运行时完整复盘")
        with patch.object(main, "_refresh_stock_index_cache_for_analysis") as refresh, \
             patch("main._compute_trading_day_filter", return_value=([], "cn", False)), \
             patch("main._resolve_daily_market_context_target_date", return_value=target_date), \
             patch("src.core.pipeline.StockAnalysisPipeline", side_effect=build_pipeline), \
             patch(
                 "main._prime_daily_market_context",
                 side_effect=[("", ""), ("", ""), runtime_context],
             ) as prime_context, \
             patch("main._run_market_review_with_shared_lock") as run_with_lock, \
             patch("src.core.market_review.run_market_review") as run_market_review:
            main.run_full_analysis(config, args, [])

        self.assertTrue(pipeline_kwargs["daily_market_context_allow_generate"])
        run_with_lock.assert_not_called()
        run_market_review.assert_not_called()
        pipeline.notifier.send.assert_called_once()
        self.assertIn("## 本轮运行时完整复盘", pipeline.notifier.send.call_args.args[0])
        self.assertEqual(pipeline.notifier.send.call_args.kwargs["route_type"], "report")
        query_scoped_read = unittest.mock.call(
            config,
            pipeline=pipeline,
            region="cn",
            no_market_review=False,
            allow_generate=False,
            target_date=target_date,
            return_full_report=True,
            require_current_query_match=True,
        )
        self.assertEqual(
            prime_context.call_args_list,
            [
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=False,
                ),
                query_scoped_read,
                query_scoped_read,
            ],
        )
        refresh.assert_called_once_with(config)
        pipeline.run.assert_called_once()

    def test_run_full_analysis_saves_reused_runtime_market_context_without_notify(self) -> None:
        args = self._make_args(no_notify=True)
        target_date = date(2026, 3, 26)
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            daily_market_context_enabled=True,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        pipeline.notifier = MagicMock()
        pipeline.notifier.save_report_to_file.return_value = "/tmp/market_review.md"

        def build_pipeline(*args, **kwargs):
            return pipeline

        runtime_context = ("本轮运行时复盘摘要", "## 本轮运行时完整复盘")
        with (
            patch.object(main, "_refresh_stock_index_cache_for_analysis") as refresh,
            patch("main._compute_trading_day_filter", return_value=([], "cn", False)),
            patch("main._resolve_daily_market_context_target_date", return_value=target_date),
            patch("src.core.pipeline.StockAnalysisPipeline", side_effect=build_pipeline),
            patch(
                "main._prime_daily_market_context",
                side_effect=[("", ""), ("", ""), runtime_context],
            ) as prime_context,
            patch("main._run_market_review_with_shared_lock") as run_with_lock,
            patch("src.core.market_review.run_market_review") as run_market_review,
        ):
            main.run_full_analysis(config, args, [])

        run_with_lock.assert_not_called()
        run_market_review.assert_not_called()
        pipeline.notifier.send.assert_not_called()
        pipeline.notifier.save_report_to_file.assert_called_once()
        saved_content, saved_filename = pipeline.notifier.save_report_to_file.call_args.args
        self.assertTrue(saved_content.startswith("# 🎯 大盘复盘\n\n"))
        self.assertIn("## 本轮运行时完整复盘", saved_content)
        self.assertTrue(saved_filename.startswith("market_review_"))
        self.assertTrue(saved_filename.endswith(".md"))
        self.assertEqual(prime_context.call_count, 3)
        refresh.assert_called_once_with(config)
        pipeline.run.assert_called_once()

    def test_run_full_analysis_still_runs_market_review_for_merge_disabled_with_reused_context(self) -> None:
        args = self._make_args()
        target_date = date(2026, 3, 26)
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            daily_market_context_enabled=True,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        pipeline_kwargs = {}

        def build_pipeline(*args, **kwargs):
            pipeline_kwargs.update(kwargs)
            return pipeline

        with patch.object(main, "_refresh_stock_index_cache_for_analysis") as refresh, \
             patch("main._compute_trading_day_filter", return_value=([], "cn", False)), \
             patch("main._resolve_daily_market_context_target_date", return_value=target_date), \
             patch("src.core.pipeline.StockAnalysisPipeline", side_effect=build_pipeline), \
             patch(
                "main._prime_daily_market_context",
                return_value=("大盘退潮，高风险，建议观望。", "## 完整大盘复盘\n市场结构偏弱，建议保守。"),
             ) as prime_context, \
             patch("main._run_market_review_with_shared_lock") as run_with_lock, \
             patch("src.core.market_review.run_market_review") as run_market_review:
            main.run_full_analysis(config, args, [])

        self.assertTrue(pipeline_kwargs["daily_market_context_allow_generate"])
        prime_context.assert_has_calls(
            [
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=False,
                ),
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=True,
                    require_current_query_match=True,
                ),
            ]
        )
        run_with_lock.assert_called_once()
        self.assertFalse(run_with_lock.call_args.kwargs["merge_notification"])
        run_market_review.assert_not_called()
        refresh.assert_called_once_with(config)
        pipeline.run.assert_called_once()

    def test_run_full_analysis_waits_for_analysis_delay_before_market_review(self) -> None:
        args = self._make_args()
        target_date = date(2026, 3, 26)
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            daily_market_context_enabled=True,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=2,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        events = []
        pipeline.run.side_effect = lambda **kwargs: events.append("stock-run") or []
        pipeline_kwargs = {}

        def build_pipeline(*args, **kwargs):
            events.append("pipeline")
            pipeline_kwargs.update(kwargs)
            return pipeline

        def run_with_lock(*args, **kwargs):
            events.append("market-review")
            return SimpleNamespace(report="完整复盘")

        with patch.object(main, "_refresh_stock_index_cache_for_analysis") as refresh, \
             patch("main._compute_trading_day_filter", return_value=([], "cn", False)), \
             patch("main._resolve_daily_market_context_target_date", return_value=target_date), \
             patch("src.core.pipeline.StockAnalysisPipeline", side_effect=build_pipeline), \
             patch("main._prime_daily_market_context", return_value=("", "")) as prime_context, \
             patch("main._run_market_review_with_shared_lock", side_effect=run_with_lock) as run_with_lock_mock, \
             patch("time.sleep") as sleep, \
             patch("src.core.market_review.run_market_review") as run_market_review:
            main.run_full_analysis(config, args, [])

        self.assertTrue(pipeline_kwargs["daily_market_context_allow_generate"])
        self.assertEqual(events, ["pipeline", "stock-run", "market-review"])
        self.assertEqual(sleep.call_count, 1)
        sleep.assert_called_once_with(2)
        self.assertEqual(
            run_with_lock_mock.call_args.kwargs["send_notification"],
            True,
        )
        run_market_review.assert_not_called()
        run_with_lock_mock.assert_called_once()
        refresh.assert_called_once_with(config)
        prime_context.assert_has_calls(
            [
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=False,
                ),
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=True,
                    require_current_query_match=True,
                ),
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=True,
                    require_current_query_match=True,
                ),
            ]
        )

    def test_run_full_analysis_reuses_cached_market_context_as_full_report(self) -> None:
        args = self._make_args()
        target_date = date(2026, 3, 26)
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            daily_market_context_enabled=True,
            single_stock_notify=False,
            merge_email_notification=True,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
            report_type="simple",
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        pipeline.notifier = MagicMock(
            is_available=MagicMock(return_value=True),
            generate_aggregate_report=MagicMock(return_value=""),
            send=MagicMock(return_value=True),
        )
        pipeline_kwargs = {}

        def build_pipeline(*args, **kwargs):
            pipeline_kwargs.update(kwargs)
            return pipeline

        with patch.object(main, "_refresh_stock_index_cache_for_analysis") as refresh, \
             patch("main._compute_trading_day_filter", return_value=([], "cn", False)), \
             patch("main._resolve_daily_market_context_target_date", return_value=target_date), \
             patch("src.core.pipeline.StockAnalysisPipeline", side_effect=build_pipeline), \
             patch(
                "main._prime_daily_market_context",
                return_value=(
                    "大盘退潮，高风险，建议观望。",
                    "## 完整大盘复盘\n市场结构偏弱，建议保守。",
                ),
             ) as prime_context, \
             patch("main._run_market_review_with_shared_lock") as run_with_lock, \
             patch("src.core.market_review.run_market_review") as run_market_review:
            main.run_full_analysis(config, args, [])

        self.assertTrue(pipeline_kwargs["daily_market_context_allow_generate"])
        prime_context.assert_has_calls(
            [
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=False,
                ),
                unittest.mock.call(
                    config,
                    pipeline=pipeline,
                    region="cn",
                    no_market_review=False,
                    allow_generate=False,
                    target_date=target_date,
                    return_full_report=True,
                    require_current_query_match=True,
                ),
            ]
        )
        run_with_lock.assert_not_called()
        run_market_review.assert_not_called()
        refresh.assert_called_once_with(config)
        pipeline.run.assert_called_once_with(
            stock_codes=[],
            dry_run=False,
            send_notification=True,
            merge_notification=True,
            current_time=unittest.mock.ANY,
        )
        notifier_message = pipeline.notifier.send.call_args.args[0]
        self.assertIn("## 完整大盘复盘", notifier_message)
        self.assertNotIn("大盘退潮，高风险，建议观望。", notifier_message)

    def test_run_market_review_with_shared_lock_forwards_request_config(self) -> None:
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            daily_market_context_enabled=True,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        run_review = MagicMock(return_value="复盘结果")

        with patch("src.core.market_review_lock.try_acquire_market_review_lock", return_value=object()) as acquire_lock, \
             patch("src.core.market_review_lock.release_market_review_lock") as release_lock:
            result = main._run_market_review_with_shared_lock(
                config,
                run_review,
                send_notification=False,
            )

        self.assertEqual(result, "复盘结果")
        acquire_lock.assert_called_once_with(config)
        run_review.assert_called_once_with(config=config, send_notification=False)
        release_lock.assert_called_once_with(unittest.mock.ANY)

    def test_prime_daily_market_context_uses_ephemeral_service_for_multi_market_region(self) -> None:
        config = self._make_config(
            trading_day_check_enabled=False,
            market_review_enabled=True,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline._daily_market_context_service = MagicMock()
        pipeline._daily_market_context_service.get_context.return_value = SimpleNamespace(
            source="analysis_history",
            summary="旧A股复盘摘要",
        )
        pipeline.db = MagicMock()
        context = SimpleNamespace(source="analysis_history", summary="多市场复盘摘要", full_report="完整复盘正文")
        regional_service = MagicMock()
        regional_service.get_context.return_value = context

        with patch("src.services.daily_market_context.DailyMarketContextService", return_value=regional_service) as service_cls:
            summary, full_report = main._prime_daily_market_context(
                config,
                pipeline=pipeline,
                region="cn,us",
                no_market_review=False,
                allow_generate=False,
                target_date=date(2026, 3, 26),
                return_full_report=True,
            )

        self.assertEqual(summary, "多市场复盘摘要")
        self.assertEqual(full_report, "完整复盘正文")
        service_cls.assert_called_once_with(db_manager=pipeline.db)
        regional_service.get_context.assert_called_once()
        self.assertIsNot(
            regional_service,
            pipeline._daily_market_context_service,
            "多市场预热必须使用独立服务避免共享缓存污染",
        )
        pipeline._daily_market_context_service.get_context.assert_not_called()

        get_context_kwargs = regional_service.get_context.call_args.kwargs
        self.assertEqual(get_context_kwargs["region"], "cn,us")
        self.assertFalse(get_context_kwargs["force_refresh"])
        self.assertFalse(get_context_kwargs["allow_generate"])
        self.assertFalse(get_context_kwargs["persist_market_review_history"])

    def test_config_enabled_schedule_marks_market_review_source_as_schedule(self) -> None:
        args = self._make_args(schedule=False)
        target_date = date(2026, 3, 26)
        config = self._make_config(
            schedule_enabled=True,
            trading_day_check_enabled=False,
            market_review_enabled=True,
            no_market_review=False,
            single_stock_notify=False,
            merge_email_notification=False,
            analysis_delay=0,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), \
             patch.object(main, "_compute_trading_day_filter", return_value=(["600519"], "cn", False)), \
             patch("main._resolve_daily_market_context_target_date", return_value=target_date), \
             patch("src.core.pipeline.StockAnalysisPipeline", return_value=pipeline), \
             patch("main._prime_daily_market_context", return_value=("", "")), \
             patch("main._run_market_review_with_shared_lock", return_value="market report") as run_with_lock, \
             patch("src.core.market_review.run_market_review") as run_market_review:
            main.run_full_analysis(config, args, ["600519"])

        pipeline.run.assert_called_once()
        run_with_lock.assert_called_once()
        call_args = run_with_lock.call_args
        self.assertIs(call_args.args[1], run_market_review)
        self.assertEqual(call_args.kwargs["trigger_source"], "schedule")

    def test_market_review_mode_uses_shared_runtime_assembly(self) -> None:
        args = self._make_args(market_review=True)
        config = self._make_config(
            trading_day_check_enabled=True,
            market_review_region="both",
            market_review_enabled=False,
            database_path=str(Path(self.temp_dir.name) / "stock_analysis.db"),
        )
        runtime_notifier = MagicMock()
        runtime_analyzer = MagicMock()
        runtime_search_service = MagicMock()

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.setup_logging"), \
             patch("main._run_market_review_with_shared_lock") as run_with_lock, \
             patch(
                 "src.core.market_review_runtime.build_market_review_runtime",
                 return_value=(
                    runtime_notifier,
                    runtime_analyzer,
                    runtime_search_service,
                 ),
             ) as runtime_builder, \
             patch("src.core.market_review.run_market_review") as run_market_review, \
             patch("src.core.trading_calendar.get_open_markets_today", return_value={"cn", "us"}), \
             patch("src.core.trading_calendar.compute_effective_region", return_value="cn,us"):
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        runtime_builder.assert_called_once_with(config)
        run_with_lock.assert_called_once()
        call_args = run_with_lock.call_args
        self.assertEqual(call_args.args[0], config)
        self.assertIs(call_args.args[1], run_market_review)
        self.assertIs(call_args.kwargs["notifier"], runtime_notifier)
        self.assertIs(call_args.kwargs["analyzer"], runtime_analyzer)
        self.assertIs(call_args.kwargs["search_service"], runtime_search_service)
        self.assertTrue(call_args.kwargs["send_notification"])
        self.assertNotIn("merge_notification", call_args.kwargs)
        self.assertEqual(call_args.kwargs["override_region"], "cn,us")
        self.assertEqual(call_args.kwargs["trigger_source"], "cli")

    def test_bootstrap_logging_persists_when_config_load_fails(self) -> None:
        """Config load failure must be logged to stderr and return exit code 1.

        Bootstrap logging is stderr-only so healthy runs never write to a
        hard-coded directory.  The error is still captured by process runners
        (e.g. GitHub Actions) that collect stderr output.
        """
        import io

        args = self._make_args()

        capture_stream = io.StringIO()
        capture_handler = logging.StreamHandler(capture_stream)
        capture_handler.setLevel(logging.DEBUG)
        capture_handler.setFormatter(logging.Formatter("%(message)s"))

        root_logger = logging.getLogger()

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", side_effect=RuntimeError("config boom")):
            root_logger.addHandler(capture_handler)
            try:
                exit_code = main.main()
            finally:
                root_logger.removeHandler(capture_handler)
                capture_handler.close()

        self.assertEqual(exit_code, 1)
        output = capture_stream.getvalue()
        self.assertIn("加载配置失败", output)
        self.assertIn("config boom", output)

    def test_bootstrap_logging_failure_does_not_block_startup(self) -> None:
        """Bootstrap log dir unwritable must not prevent startup (P1 regression)."""
        args = self._make_args()
        config = self._make_config()

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main._setup_bootstrap_logging", side_effect=OSError("read-only fs")), \
             patch("main.setup_logging"), \
             patch("main.run_full_analysis") as run_mock:
            exit_code = main.main()

        self.assertEqual(exit_code, 0)
        run_mock.assert_called_once()

    def test_runtime_file_logging_permission_error_falls_back_to_console(self) -> None:
        """Configured file logging failures should not prevent Docker startup."""
        import io

        args = self._make_args()
        config = self._make_config(log_dir="/app/logs")
        capture_stream = io.StringIO()
        capture_handler = logging.StreamHandler(capture_stream)
        capture_handler.setLevel(logging.DEBUG)
        capture_handler.setFormatter(logging.Formatter("%(message)s"))

        root_logger = logging.getLogger()

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch(
                 "main.setup_logging",
                 side_effect=PermissionError("/app/logs/stock_analysis_20260511.log"),
             ), \
             patch("main.run_full_analysis") as run_mock:
            root_logger.addHandler(capture_handler)
            try:
                exit_code = main.main()
            finally:
                root_logger.removeHandler(capture_handler)
                capture_handler.close()

        self.assertEqual(exit_code, 0)
        run_mock.assert_called_once()
        output = capture_stream.getvalue()
        self.assertIn("文件日志初始化失败，已降级为控制台日志输出", output)
        self.assertIn("/app/logs", output)
        self.assertIn("官方 Docker 镜像启动入口会自动修复默认挂载目录权限", output)

    def test_run_full_analysis_import_failure_propagates(self) -> None:
        """P1: import failures in run_full_analysis must propagate, not be swallowed."""
        args = self._make_args()
        config = self._make_config()

        with patch("main.parse_arguments", return_value=args), \
             patch("main.get_config", return_value=config), \
             patch("main.setup_logging"), \
             patch.dict("sys.modules", {"src.core.pipeline": None}):
            exit_code = main.main()

        self.assertEqual(exit_code, 1)

    def test_lazy_pipeline_triggers_env_bootstrap(self) -> None:
        """P2: lazy StockAnalysisPipeline access must call _bootstrap_environment."""
        # Reset the lazy descriptor cache so __get__ fires again
        main._LazyPipelineDescriptor._resolved = None
        main._env_bootstrapped = False

        with patch("main._bootstrap_environment", wraps=main._bootstrap_environment) as mock_boot, \
             patch("src.core.pipeline.StockAnalysisPipeline", create=True, new_callable=lambda: type("FakePipeline", (), {})):
            try:
                _ = main.StockAnalysisPipeline
            except Exception:
                pass
            mock_boot.assert_called()

        # Cleanup: reset state
        main._LazyPipelineDescriptor._resolved = None
        main._env_bootstrapped = False


if __name__ == "__main__":
    unittest.main()
