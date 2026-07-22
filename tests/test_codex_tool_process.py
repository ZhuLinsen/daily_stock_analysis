# -*- coding: utf-8 -*-
"""Regression contract for Codex-owned tool worker processes."""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from src.agent.codex_tool_process import MAX_TOOL_RESULT_BYTES, CodexToolProcessRunner
from src.agent.stock_scope import StockScope
from src.agent.tools.execution import ToolAccessContext


def _ok_result(tool_name: str, payload: dict) -> dict:
    return {
        "ok": True,
        "tool_name": tool_name,
        "result": payload,
        "result_text": "{}",
        "error": None,
        "audit": {},
        "diagnostics": {},
    }


def _escaped_result_worker(tool_name: str, arguments: dict, _context: ToolAccessContext) -> dict:
    size = int(arguments["size"])
    return {
        "ok": True,
        "tool_name": tool_name,
        "result_text": '"' * size,
        "error": None,
    }


def _truncated_surface_result_worker(
    tool_name: str,
    _arguments: dict,
    _context: ToolAccessContext,
) -> dict:
    return {
        "ok": True,
        "tool_name": tool_name,
        "result_text": "partial<truncated>",
        "error": None,
        "diagnostics": {"result_truncated": True},
    }


def _mark(path: str) -> None:
    Path(path).write_text(str(os.getpid()), encoding="utf-8")


def _sqlite_query_worker(tool_name: str, arguments: dict, _context: ToolAccessContext) -> dict:
    _mark(arguments["marker"])
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "WITH RECURSIVE cnt(x) AS (VALUES(0) UNION ALL SELECT x + 1 FROM cnt WHERE x < 500000000) "
            "SELECT sum(x) FROM cnt"
        ).fetchone()
    finally:
        connection.close()
    return _ok_result(tool_name, {"finished": True})


def _sqlite_lock_worker(tool_name: str, arguments: dict, _context: ToolAccessContext) -> dict:
    connection = sqlite3.connect(arguments["db_path"], timeout=30, isolation_level=None)
    try:
        _mark(arguments["marker"])
        connection.execute("INSERT INTO probe(value) VALUES (2)")
    finally:
        connection.close()
    return _ok_result(tool_name, {"finished": True})


def _pool_wait_worker(tool_name: str, arguments: dict, _context: ToolAccessContext) -> dict:
    engine = create_engine(
        f"sqlite:///{arguments['db_path']}",
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=30,
    )
    first = engine.connect()
    try:
        _mark(arguments["marker"])
        with engine.connect():
            pass
    finally:
        first.close()
        engine.dispose()
    return _ok_result(tool_name, {"finished": True})


def _crash_worker(_tool_name: str, arguments: dict, _context: ToolAccessContext) -> dict:
    _mark(arguments["marker"])
    os._exit(17)


def _ignore_term_worker(tool_name: str, arguments: dict, _context: ToolAccessContext) -> dict:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    _mark(arguments["marker"])
    while True:
        time.sleep(0.1)


def _crash_with_descendant_worker(
    _tool_name: str,
    arguments: dict,
    _context: ToolAccessContext,
) -> dict:
    descendant = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        close_fds=True,
    )
    Path(arguments["marker"]).write_text(str(descendant.pid), encoding="utf-8")
    os._exit(17)


def _wait_for_marker(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"worker did not enter blocker: {path}")


def _execute_in_thread(
    runner: CodexToolProcessRunner,
    tool_name: str,
    arguments: dict,
    context: ToolAccessContext,
) -> tuple[threading.Thread, dict]:
    output: dict = {}
    thread = threading.Thread(
        target=lambda: output.setdefault(
            "result",
            runner.execute(tool_name, arguments, context),
        )
    )
    thread.start()
    return thread, output


def test_three_production_tools_execute_through_spawned_worker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "production-tools.db"))
    runner = CodexToolProcessRunner()
    cases = (
        (
            "get_analysis_context",
            {"stock_code": "600000"},
            StockScope(expected_stock_code="600000", allowed_stock_codes={"600000"}),
        ),
        ("get_skill_backtest_summary", {"skill_id": "missing-gate-skill"}, None),
        ("get_strategy_backtest_summary", {}, None),
    )

    try:
        for tool_name, arguments, stock_scope in cases:
            result = runner.execute(
                tool_name,
                arguments,
                ToolAccessContext(
                    stock_scope=stock_scope,
                    backend="codex_app_server",
                    session_id="process-contract",
                    deadline=time.monotonic() + 30,
                    max_result_bytes=1024 * 1024,
                    redact_result=True,
                ),
            )
            assert result["ok"] is True
    finally:
        runner.close()

    records = runner.snapshot()
    assert len(records) == 3
    assert all(record["alive_after"] is False for record in records)
    assert all(record["pid_alive_after"] is False for record in records)


def test_running_sqlite_query_is_cancelled_and_reaped_three_times(tmp_path: Path) -> None:
    runner = CodexToolProcessRunner(worker=_sqlite_query_worker)
    try:
        for iteration in range(3):
            marker = tmp_path / f"query-{iteration}.marker"
            cancel_event = threading.Event()
            thread, output = _execute_in_thread(
                runner,
                "blocking_query",
                {"marker": str(marker)},
                ToolAccessContext(
                    cancel_event=cancel_event,
                    deadline=time.monotonic() + 30,
                ),
            )
            _wait_for_marker(marker)
            cancel_started = time.monotonic()
            cancel_event.set()
            thread.join(timeout=3)

            assert thread.is_alive() is False
            assert time.monotonic() - cancel_started < 1
            assert output["result"]["error"]["code"] == "cancelled"
    finally:
        runner.close()

    records = runner.snapshot()
    assert len(records) == 3
    assert all(record["termination_reason"] == "cancelled" for record in records)
    assert all(record["pid_alive_after"] is False for record in records)


def test_sqlite_lock_wait_is_cancelled_without_leaving_database_locked(tmp_path: Path) -> None:
    db_path = tmp_path / "lock.db"
    setup = sqlite3.connect(db_path, isolation_level=None)
    setup.execute("CREATE TABLE probe(value INTEGER)")
    setup.execute("INSERT INTO probe(value) VALUES (1)")
    setup.close()

    locker = sqlite3.connect(db_path, timeout=5, isolation_level=None, check_same_thread=False)
    locker.execute("PRAGMA journal_mode=DELETE")
    locker.execute("BEGIN EXCLUSIVE")
    runner = CodexToolProcessRunner(worker=_sqlite_lock_worker)
    marker = tmp_path / "lock.marker"
    cancel_event = threading.Event()
    try:
        thread, output = _execute_in_thread(
            runner,
            "blocking_lock",
            {"marker": str(marker), "db_path": str(db_path)},
            ToolAccessContext(cancel_event=cancel_event, deadline=time.monotonic() + 30),
        )
        _wait_for_marker(marker)
        cancel_event.set()
        thread.join(timeout=3)
        assert thread.is_alive() is False
        assert output["result"]["error"]["code"] == "cancelled"
    finally:
        locker.rollback()
        locker.close()
        runner.close()

    verifier = sqlite3.connect(db_path, timeout=2)
    try:
        assert verifier.execute("SELECT count(*) FROM probe").fetchone()[0] == 1
    finally:
        verifier.close()
    assert runner.snapshot()[-1]["pid_alive_after"] is False


def test_pool_wait_honors_deadline_and_releases_worker(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    sqlite3.connect(db_path).close()
    marker = tmp_path / "pool.marker"
    runner = CodexToolProcessRunner(worker=_pool_wait_worker)
    started = time.monotonic()
    try:
        result = runner.execute(
            "blocking_pool",
            {"marker": str(marker), "db_path": str(db_path)},
            ToolAccessContext(deadline=started + 1.5),
        )
    finally:
        runner.close()

    assert marker.exists()
    assert result["error"]["code"] == "timeout"
    assert 1.3 <= time.monotonic() - started < 3
    assert runner.snapshot()[-1]["pid_alive_after"] is False
    verifier = sqlite3.connect(db_path, timeout=2)
    verifier.close()


def test_child_crash_is_reported_and_reaped(tmp_path: Path) -> None:
    marker = tmp_path / "crash.marker"
    runner = CodexToolProcessRunner(worker=_crash_worker)
    try:
        result = runner.execute(
            "crash",
            {"marker": str(marker)},
            ToolAccessContext(deadline=time.monotonic() + 5),
        )
    finally:
        runner.close()

    assert marker.exists()
    assert result["error"]["code"] == "handler_error"
    record = runner.snapshot()[-1]
    assert record["exitcode"] == 17
    assert record["pid_alive_after"] is False


def test_pre_cancelled_call_never_spawns_worker() -> None:
    cancel_event = threading.Event()
    cancel_event.set()
    runner = CodexToolProcessRunner(worker=_sqlite_query_worker)
    try:
        result = runner.execute(
            "not_started",
            {"marker": "unused"},
            ToolAccessContext(cancel_event=cancel_event, deadline=time.monotonic() + 5),
        )
    finally:
        runner.close()

    assert result["error"]["code"] == "cancelled"
    assert runner.snapshot() == ()


def test_ipc_limit_is_measured_on_raw_result_bytes_not_json_escaping() -> None:
    runner = CodexToolProcessRunner(worker=_escaped_result_worker)
    try:
        result = runner.execute(
            "escaped_result",
            {"size": MAX_TOOL_RESULT_BYTES},
            ToolAccessContext(deadline=time.monotonic() + 5),
        )
    finally:
        runner.close()

    assert result["ok"] is True
    assert len(result["result_text"].encode("utf-8")) == MAX_TOOL_RESULT_BYTES


def test_ipc_reports_output_too_large_for_raw_result_over_limit() -> None:
    runner = CodexToolProcessRunner(worker=_escaped_result_worker)
    try:
        result = runner.execute(
            "oversized_result",
            {"size": MAX_TOOL_RESULT_BYTES + 1},
            ToolAccessContext(deadline=time.monotonic() + 5),
        )
    finally:
        runner.close()

    assert result["ok"] is False
    assert result["error"]["code"] == "output_too_large"


def test_ipc_rejects_tool_surface_truncation_as_output_too_large() -> None:
    runner = CodexToolProcessRunner(worker=_truncated_surface_result_worker)
    try:
        result = runner.execute(
            "truncated_result",
            {},
            ToolAccessContext(deadline=time.monotonic() + 5),
        )
    finally:
        runner.close()

    assert result["ok"] is False
    assert result["error"]["code"] == "output_too_large"


def test_runner_close_reaps_active_worker_before_returning(tmp_path: Path) -> None:
    marker = tmp_path / "close.marker"
    runner = CodexToolProcessRunner(worker=_sqlite_query_worker)
    thread, output = _execute_in_thread(
        runner,
        "blocking_close",
        {"marker": str(marker)},
        ToolAccessContext(deadline=time.monotonic() + 30),
    )
    _wait_for_marker(marker)

    started = time.monotonic()
    cleanup_ok = runner.close()
    thread.join(timeout=3)

    assert cleanup_ok is True, runner.snapshot()
    assert time.monotonic() - started < 1
    assert thread.is_alive() is False
    assert output["result"]["error"]["code"] == "cancelled"
    assert runner.snapshot()[-1]["pid_alive_after"] is False


def test_completed_cleanup_is_idempotent_for_stale_owner_reference(tmp_path: Path) -> None:
    marker = tmp_path / "close-race.marker"
    cancel_event = threading.Event()
    runner = CodexToolProcessRunner(worker=_sqlite_query_worker)
    thread, output = _execute_in_thread(
        runner,
        "blocking_close_race",
        {"marker": str(marker)},
        ToolAccessContext(cancel_event=cancel_event, deadline=time.monotonic() + 30),
    )
    _wait_for_marker(marker)
    with runner._state_lock:
        stale_owner = next(iter(runner._active.values()))

    cancel_event.set()
    thread.join(timeout=3)

    assert thread.is_alive() is False
    assert runner._terminate(stale_owner, "cancelled") is True
    assert runner.close() is True
    assert output["result"]["error"]["code"] == "cancelled"
    assert runner.snapshot()[-1]["pid_alive_after"] is False


def test_term_escalates_to_kill_and_reaps_owned_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "ignore-term.marker"
    cancel_event = threading.Event()
    runner = CodexToolProcessRunner(worker=_ignore_term_worker)
    thread, output = _execute_in_thread(
        runner,
        "ignore_term",
        {"marker": str(marker)},
        ToolAccessContext(cancel_event=cancel_event, deadline=time.monotonic() + 30),
    )
    _wait_for_marker(marker)

    started = time.monotonic()
    cancel_event.set()
    thread.join(timeout=3)
    runner.close()

    assert thread.is_alive() is False
    assert time.monotonic() - started < 2
    assert output["result"]["error"]["code"] == "cancelled"
    record = runner.snapshot()[-1]
    assert record["exitcode"] == -signal.SIGKILL
    assert record["pid_alive_after"] is False


def test_child_crash_reaps_descendant_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "descendant.pid"
    runner = CodexToolProcessRunner(worker=_crash_with_descendant_worker)
    descendant_pid = 0
    try:
        result = runner.execute(
            "crash_with_descendant",
            {"marker": str(marker)},
            ToolAccessContext(deadline=time.monotonic() + 5),
        )
        _wait_for_marker(marker)
        descendant_pid = int(marker.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(descendant_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            raise AssertionError(f"descendant process survived worker crash: {descendant_pid}")
    finally:
        runner.close()
        if descendant_pid:
            try:
                os.kill(descendant_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    assert result["error"]["code"] == "handler_error"
    record = runner.snapshot()[-1]
    assert record["exitcode"] == 17
    assert record["process_group_alive_after"] is False
