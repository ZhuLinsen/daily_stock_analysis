# -*- coding: utf-8 -*-
"""Offline contract tests for the Bot 指数入口 online E2E smoke runner
(``scripts/smoke_bot_index_entry.py``).

Covers, without touching the network or spawning real children:

* the I/O & edge-case matrix resolution (SH_ALIAS / REGISTERED_NAME /
  CSI_ALIAS -> canonical id + registered display name),
* transport independence: worker spawn kwargs never use ``PIPE``,
  POSIX uses ``start_new_session`` and Windows uses a new process group,
* failure/timeout semantics: failed tasks and incomplete completed results
  produce a ``failed`` phase event; timeout cleanup kills the process tree,
* the single-line ``E2E_EVENT {json}`` wire format.
"""

import io
import json
import os
import signal
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from scripts import smoke_bot_index_entry as smoke  # noqa: E402


class TestExpectedOutcomes(unittest.TestCase):
    """The authoritative matrix map must cover exactly the three required
    inputs and reject everything else."""

    def test_matrix_covers_three_required_scenarios(self):
        self.assertEqual(
            smoke.EXPECTED_OUTCOMES,
            {
                "SH.000016": ("sh000016", "上证50"),
                "上证50": ("sh000016", "上证50"),
                "930955.CSI": ("csi930955", "红利低波100"),
            },
        )

    def test_resolve_expected_sh_alias(self):
        self.assertEqual(
            smoke._resolve_expected("SH.000016"), ("sh000016", "上证50")
        )

    def test_resolve_expected_registered_name(self):
        self.assertEqual(
            smoke._resolve_expected("上证50"), ("sh000016", "上证50")
        )

    def test_resolve_expected_csi_alias(self):
        self.assertEqual(
            smoke._resolve_expected("930955.CSI"), ("csi930955", "红利低波100")
        )

    def test_unknown_target_is_rejected(self):
        with self.assertRaises(ValueError):
            smoke._resolve_expected("AAPL")
        with self.assertRaises(ValueError):
            smoke._resolve_expected("600519")


class TestSpawnKwargs(unittest.TestCase):
    """Worker spawn must inherit the console (no ``PIPE``) and detach into
    its own session/process group so the parent can kill the whole tree."""

    def test_posix_spawn_kwargs_use_start_new_session(self):
        kwargs = smoke._spawn_kwargs("posix")
        self.assertEqual(kwargs, {"start_new_session": True})

    def test_windows_spawn_kwargs_use_new_process_group(self):
        with patch.object(
            smoke.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, create=True
        ):
            kwargs = smoke._spawn_kwargs("nt")
        self.assertEqual(kwargs, {"creationflags": 0x00000200})

    def test_spawn_kwargs_never_use_pipe(self):
        with patch.object(
            smoke.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, create=True
        ):
            for platform in ("posix", "nt"):
                kwargs = smoke._spawn_kwargs(platform)
                self.assertNotIn("stdout", kwargs)
                self.assertNotIn("stderr", kwargs)
                self.assertNotIn("stdin", kwargs)


class TestTerminateProcessTree(unittest.TestCase):
    """Timeout cleanup must kill the whole tree: ``taskkill /T /F`` on
    Windows, the process group on POSIX. Failures must be surfaced as an
    error string — never silently swallowed as success — while an
    already-gone process counts as success."""

    @patch("subprocess.run")
    def test_windows_uses_taskkill_tree_force(self, mock_run):
        mock_run.return_value = type("R", (), {"returncode": 0})()
        proc = type("Proc", (), {"pid": 4242})()
        self.assertIsNone(smoke._terminate_process_tree(proc, "nt"))
        mock_run.assert_called_once_with(
            ["taskkill", "/T", "/F", "/PID", "4242"], timeout=30
        )

    @patch.object(os, "killpg", create=True)
    def test_posix_kills_process_group(self, mock_killpg):
        proc = type("Proc", (), {"pid": 4242})()
        self.assertIsNone(smoke._terminate_process_tree(proc, "posix"))
        # ``SIGKILL`` does not exist on Windows; the script resolves it via
        # ``getattr`` so this expectation stays portable.
        kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
        mock_killpg.assert_called_once_with(4242, kill_signal)

    @patch("subprocess.run")
    def test_windows_taskkill_failure_is_surfaced(self, mock_run):
        """A non-zero taskkill must not be reported as success: the error is
        returned (direct kill also failing keeps the error)."""
        mock_run.return_value = type("R", (), {"returncode": 1})()
        proc = type("Proc", (), {"pid": 4242, "kill": _raise_oserror})()
        error = smoke._terminate_process_tree(proc, "nt")
        self.assertIsNotNone(error)
        self.assertIn("taskkill exited 1", error or "")

    @patch("subprocess.run")
    def test_windows_taskkill_exception_is_surfaced(self, mock_run):
        mock_run.side_effect = RuntimeError("taskkill missing")
        proc = type("Proc", (), {"pid": 4242, "kill": _raise_oserror})()
        error = smoke._terminate_process_tree(proc, "nt")
        self.assertIsNotNone(error)
        self.assertIn("taskkill failed", error or "")

    @patch("subprocess.run")
    def test_windows_taskkill_failure_with_direct_kill_success(self, mock_run):
        """When taskkill fails, a successful direct kill must NOT erase the
        tree-cleanup error: direct kill only proves the worker process was
        killed, not its descendants."""
        mock_run.return_value = type("R", (), {"returncode": 1})()
        proc = type("Proc", (), {"pid": 4242, "kill": lambda self: None})()
        error = smoke._terminate_process_tree(proc, "nt")
        self.assertIsNotNone(error)
        self.assertIn("taskkill exited 1", error or "")
        self.assertIn("tree cleanup is unconfirmed", error or "")

    @patch.object(os, "killpg", create=True)
    def test_posix_killpg_failure_is_surfaced(self, mock_killpg):
        mock_killpg.side_effect = OSError("permission denied")
        proc = type("Proc", (), {"pid": 4242, "kill": _raise_oserror})()
        error = smoke._terminate_process_tree(proc, "posix")
        self.assertIsNotNone(error)
        self.assertIn("process-group kill failed", error or "")

    @patch.object(os, "killpg", create=True)
    def test_posix_killpg_failure_with_direct_kill_success_still_fails(self, mock_killpg):
        """A successful direct kill after a killpg failure must still surface
        the tree-cleanup error (descendants are unconfirmed)."""
        mock_killpg.side_effect = OSError("permission denied")
        proc = type("Proc", (), {"pid": 4242, "kill": lambda self: None})()
        error = smoke._terminate_process_tree(proc, "posix")
        self.assertIsNotNone(error)
        self.assertIn("process-group kill failed", error or "")
        self.assertIn("tree cleanup is unconfirmed", error or "")

    @patch.object(os, "killpg", create=True)
    def test_posix_already_gone_counts_as_success(self, mock_killpg):
        mock_killpg.side_effect = ProcessLookupError()
        proc = type("Proc", (), {"pid": 4242})()
        self.assertIsNone(smoke._terminate_process_tree(proc, "posix"))

    @patch.object(os, "killpg", None, create=True)
    def test_posix_without_killpg_never_claims_confirmed_tree_cleanup(self):
        """Without a process-group primitive, a direct kill only proves the
        worker itself was killed, not its descendants: the function must
        return an unconfirmed-tree-cleanup error instead of None."""
        proc = type("Proc", (), {"pid": 4242, "kill": lambda self: None})()
        error = smoke._terminate_process_tree(proc, "posix")
        self.assertIsNotNone(error)
        self.assertIn("tree cleanup is unconfirmed", error or "")


def _raise_oserror():
    raise OSError("direct kill failed")


class TestParentSpawn(unittest.TestCase):
    """The parent must spawn the worker with the explicit hidden ``--worker``
    flag (never via environment), with no ``PIPE``, and the child must not
    re-enter the parent branch when an environment role variable is preset."""

    def _patch_popen(self, target, env=None, exit_code=0):
        class _FakeProc:
            def __init__(self, args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def wait(self, timeout=None):
                return exit_code

        with patch.object(subprocess, "Popen", side_effect=_FakeProc) as mock_popen:
            try:
                result = smoke._run_parent(target, timeout=60)
            finally:
                pass
        return result, mock_popen

    def test_parent_spawns_worker_with_explicit_flag_and_no_pipe(self):
        result, mock_popen = self._patch_popen("SH.000016")
        self.assertEqual(result, 0)
        self.assertEqual(mock_popen.call_count, 1)
        args, kwargs = mock_popen.call_args
        self.assertIn("--worker", args[0])
        self.assertEqual(args[0][-1], "SH.000016")
        self.assertNotIn("stdout", kwargs)
        self.assertNotIn("stderr", kwargs)
        self.assertNotIn("stdin", kwargs)

    def test_preset_env_role_cannot_force_worker_mode(self):
        """An externally preset role variable must not switch the entrypoint
        into worker mode: without ``--worker`` the parent branch still runs."""
        with patch.dict(
            os.environ, {"DSA_SMOKE_ROLE": "worker"}, clear=False
        ):
            result, mock_popen = self._patch_popen("上证50")
        self.assertEqual(result, 0)
        self.assertEqual(mock_popen.call_count, 1)
        args, kwargs = mock_popen.call_args
        self.assertIn("--worker", args[0])
        self.assertEqual(args[0][-1], "上证50")

    def test_worker_flag_dispatches_to_worker_and_parent_flag_never_spawns(self):
        """``main(["--worker", target])`` runs the worker directly; the
        parent path (which is the only spawner) never sees ``--worker``."""
        with patch.object(smoke, "_run_worker", return_value=3) as mock_worker, patch.object(
            smoke, "_run_parent", return_value=4
        ) as mock_parent:
            self.assertEqual(smoke.main(["--worker", "SH.000016"]), 3)
            mock_worker.assert_called_once_with("SH.000016")
            mock_parent.assert_not_called()

    def test_run_parent_unsupported_target_never_spawns(self):
        """Unsupported targets are rejected before the subprocess spawn: the
        parent must raise and never reach ``Popen``."""
        def _fail_popen(*args, **kwargs):
            raise AssertionError("Popen must not be called for unsupported targets")

        with patch.object(subprocess, "Popen", side_effect=_fail_popen) as mock_popen:
            with self.assertRaises(ValueError):
                smoke._run_parent("AAPL", timeout=60)
        mock_popen.assert_not_called()

    def test_run_worker_unsupported_target_raises_before_dispatch(self):
        """``_run_worker`` defensively validates before any dispatcher
        construction: an unsupported target raises and never dispatches."""
        def _fail_dispatcher(*args, **kwargs):
            raise AssertionError("dispatcher must not be constructed")

        with patch("bot.dispatcher.CommandDispatcher", side_effect=_fail_dispatcher) as mock_disp:
            with self.assertRaises(ValueError):
                smoke._run_worker("600519")
        mock_disp.assert_not_called()

    def test_main_unsupported_target_returns_error_without_running_branches(self):
        """``main()`` must reject unsupported targets with a non-zero
        argument/input error without calling ``_run_parent`` or
        ``_run_worker`` (so nothing can submit or spawn)."""
        def _fail_worker(target):
            raise AssertionError("_run_worker must not be called")

        def _fail_parent(target, timeout):
            raise AssertionError("_run_parent must not be called")

        with patch.object(smoke, "_run_worker", side_effect=_fail_worker) as mock_worker, patch.object(
            smoke, "_run_parent", side_effect=_fail_parent
        ) as mock_parent:
            result = smoke.main(["AAPL"])
        self.assertEqual(result, 2)
        mock_worker.assert_not_called()
        mock_parent.assert_not_called()

    def test_run_parent_timeout_kills_tree_emits_event_and_exits_124(self):
        """TIMEOUT matrix row: when the worker outlives the deadline the
        parent cleans up the process tree, emits a timeout ``E2E_EVENT`` with
        the target and exits 124."""
        import io
        from contextlib import redirect_stdout

        class _NeverEndingProc:
            def __init__(self, args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("worker", timeout or 1)

            def kill(self):
                pass

        def _kill(proc, platform_name):
            killed.append((proc, platform_name))

        killed = []
        buf = io.StringIO()
        # 第一次 monotonic 调用计算 deadline；后续调用（轮询循环内）必须越过
        # deadline。用单调递增序列而非固定两项列表，容忍实现中任何无害的
        # 额外 ``time.monotonic()`` 调用。
        monotonic_values = iter([1000.0, 1061.0, 1062.0, 1063.0])
        with patch.object(
            subprocess, "Popen", side_effect=_NeverEndingProc
        ), patch.object(smoke, "_terminate_process_tree", side_effect=_kill), patch(
            "time.monotonic", side_effect=lambda: next(monotonic_values)
        ), redirect_stdout(buf):
            result = smoke._run_parent("SH.000016", timeout=60)

        self.assertEqual(result, 124)
        self.assertEqual(len(killed), 1)
        event_line = next(
            line for line in buf.getvalue().splitlines()
            if line.startswith("E2E_EVENT ")
        )
        payload = json.loads(event_line[len("E2E_EVENT "):])
        self.assertEqual(payload["phase"], "timeout")
        self.assertEqual(payload["target"], "SH.000016")

    def test_run_parent_timeout_cleanup_failure_emits_failed_and_exits_1(self):
        """When tree cleanup fails on timeout, the parent must NOT claim
        success: it emits a structured failed event with the cleanup error
        and returns 1 (not 124)."""
        import io
        from contextlib import redirect_stdout

        class _NeverEndingProc:
            def __init__(self, args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("worker", timeout or 1)

            def kill(self):
                pass

        monotonic_values = iter([1000.0, 1061.0, 1062.0])
        buf = io.StringIO()
        with patch.object(
            subprocess, "Popen", side_effect=_NeverEndingProc
        ), patch.object(
            smoke,
            "_terminate_process_tree",
            return_value="taskkill exited 128",
        ), patch(
            "time.monotonic", side_effect=lambda: next(monotonic_values)
        ), redirect_stdout(buf):
            result = smoke._run_parent("SH.000016", timeout=60)

        self.assertEqual(result, 1)
        event_line = next(
            line for line in buf.getvalue().splitlines()
            if line.startswith("E2E_EVENT ")
        )
        payload = json.loads(event_line[len("E2E_EVENT "):])
        self.assertEqual(payload["phase"], "failed")
        self.assertEqual(payload["target"], "SH.000016")
        self.assertIn("timeout cleanup failed", payload["error"])
        self.assertIn("taskkill exited 128", payload["error"])

    def test_run_parent_post_cleanup_kill_failure_emits_failed_and_exits_1(self):
        """A post-cleanup ``proc.kill()`` failure must not escape as an
        uncaught exception: it merges into the cleanup error, emits a
        structured failed event and returns 1 (never 124)."""
        import io
        from contextlib import redirect_stdout

        class _StuckProc:
            def __init__(self, args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("worker", timeout or 1)

            def kill(self):
                raise OSError("post-cleanup kill exploded")

        monotonic_values = iter([1000.0, 1061.0, 1062.0])
        buf = io.StringIO()
        with patch.object(
            subprocess, "Popen", side_effect=_StuckProc
        ), patch.object(
            smoke, "_terminate_process_tree", return_value=None
        ), patch(
            "time.monotonic", side_effect=lambda: next(monotonic_values)
        ), redirect_stdout(buf):
            result = smoke._run_parent("SH.000016", timeout=60)

        self.assertEqual(result, 1)
        event_line = next(
            line for line in buf.getvalue().splitlines()
            if line.startswith("E2E_EVENT ")
        )
        payload = json.loads(event_line[len("E2E_EVENT "):])
        self.assertEqual(payload["phase"], "failed")
        self.assertEqual(payload["target"], "SH.000016")
        self.assertIn("timeout cleanup failed", payload["error"])
        self.assertIn("post-cleanup kill failed", payload["error"])

    def test_run_parent_normalizes_unknown_worker_exit_code_to_1(self):
        """The documented runtime contract only exposes 0 / 1 / 124: any
        other worker exit code is normalized to 1."""
        result, mock_popen = self._patch_popen("SH.000016", exit_code=42)
        self.assertEqual(result, 1)
        self.assertEqual(mock_popen.call_count, 1)

    def test_run_parent_keyboard_interrupt_cleans_tree_then_reraises(self):
        """A Ctrl-C in the parent poll window must clean up the worker
        process tree before propagating the interrupt, so no orphan keeps
        running the real data/LLM/report/notification chain."""

        class _InterruptingProc:
            def __init__(self, args, **kwargs):
                self.args = args
                self.kwargs = kwargs
                self._interrupted = False

            def poll(self):
                return None

            def wait(self, timeout=None):
                if not self._interrupted:
                    self._interrupted = True
                    raise KeyboardInterrupt()
                return 0

            def kill(self):
                pass

        killed = []
        with patch.object(
            subprocess, "Popen", side_effect=_InterruptingProc
        ), patch.object(
            smoke, "_terminate_process_tree", side_effect=lambda p, n: killed.append((p, n))
        ):
            with self.assertRaises(KeyboardInterrupt):
                smoke._run_parent("SH.000016", timeout=60)
        self.assertEqual(len(killed), 1)
        self.assertEqual(killed[0][1], "nt" if os.name == "nt" else "posix")

    def test_run_parent_keyboard_interrupt_cleanup_failure_emits_failed_and_exits_1(self):
        """When tree cleanup fails on Ctrl-C, the parent must NOT silently
        swallow the failure: it emits a structured failed event with the
        cleanup error and returns 1 instead of re-raising the interrupt."""
        import io
        from contextlib import redirect_stdout

        class _InterruptingProc:
            def __init__(self, args, **kwargs):
                self.args = args
                self.kwargs = kwargs
                self._interrupted = False

            def poll(self):
                return None

            def wait(self, timeout=None):
                if not self._interrupted:
                    self._interrupted = True
                    raise KeyboardInterrupt()
                return 0

            def kill(self):
                pass

        buf = io.StringIO()
        killed = []
        with patch.object(
            subprocess, "Popen", side_effect=_InterruptingProc
        ), patch.object(
            smoke,
            "_terminate_process_tree",
            side_effect=lambda p, n: killed.append((p, n)) or "taskkill exited 128",
        ), redirect_stdout(buf):
            result = smoke._run_parent("SH.000016", timeout=60)

        self.assertEqual(result, 1)
        self.assertEqual(len(killed), 1)
        self.assertEqual(killed[0][1], "nt" if os.name == "nt" else "posix")
        event_line = next(
            line for line in buf.getvalue().splitlines()
            if line.startswith("E2E_EVENT ")
        )
        payload = json.loads(event_line[len("E2E_EVENT "):])
        self.assertEqual(payload["phase"], "failed")
        self.assertEqual(payload["target"], "SH.000016")
        self.assertIn("interrupt cleanup failed", payload["error"])
        self.assertIn("taskkill exited 128", payload["error"])

    def test_run_parent_keyboard_interrupt_post_cleanup_kill_failure_emits_failed(self):
        """A post-cleanup ``proc.kill()`` failure on the Ctrl-C path must
        merge into the cleanup error and emit a structured failed event
        (return 1), never escape as an uncaught exception."""
        import io
        from contextlib import redirect_stdout

        class _StuckInterruptingProc:
            def __init__(self, args, **kwargs):
                self.args = args
                self.kwargs = kwargs
                self._interrupted = False

            def poll(self):
                return None

            def wait(self, timeout=None):
                if not self._interrupted:
                    self._interrupted = True
                    raise KeyboardInterrupt()
                raise subprocess.TimeoutExpired("worker", timeout or 1)

            def kill(self):
                raise OSError("post-cleanup kill exploded")

        buf = io.StringIO()
        with patch.object(
            subprocess, "Popen", side_effect=_StuckInterruptingProc
        ), patch.object(
            smoke, "_terminate_process_tree", return_value=None
        ), redirect_stdout(buf):
            result = smoke._run_parent("SH.000016", timeout=60)

        self.assertEqual(result, 1)
        event_line = next(
            line for line in buf.getvalue().splitlines()
            if line.startswith("E2E_EVENT ")
        )
        payload = json.loads(event_line[len("E2E_EVENT "):])
        self.assertEqual(payload["phase"], "failed")
        self.assertEqual(payload["target"], "SH.000016")
        self.assertIn("interrupt cleanup failed", payload["error"])
        self.assertIn("post-cleanup kill failed", payload["error"])

    def test_run_parent_keyboard_interrupt_cleanup_confirmed_via_kill_reraises(self):
        """When tree cleanup succeeds but the post-cleanup wait times out and
        the follow-up kill succeeds, cleanup is still confirmed: the parent
        re-raises the interrupt instead of emitting a failed event."""
        import io
        from contextlib import redirect_stdout

        class _KillableInterruptingProc:
            def __init__(self, args, **kwargs):
                self.args = args
                self.kwargs = kwargs
                self._interrupted = False

            def poll(self):
                return None

            def wait(self, timeout=None):
                if not self._interrupted:
                    self._interrupted = True
                    raise KeyboardInterrupt()
                raise subprocess.TimeoutExpired("worker", timeout or 1)

            def kill(self):
                pass

        buf = io.StringIO()
        with patch.object(
            subprocess, "Popen", side_effect=_KillableInterruptingProc
        ), patch.object(
            smoke, "_terminate_process_tree", return_value=None
        ), redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                smoke._run_parent("SH.000016", timeout=60)
        self.assertEqual(buf.getvalue(), "")

    def test_run_parent_keyboard_interrupt_skips_cleanup_when_worker_exited(self):
        """A Ctrl-C arriving after the worker already exited must NOT run
        tree cleanup (which would misreport a spurious failure on Windows
        taskkill against a dead PID): the interrupt is propagated directly."""
        import io
        from contextlib import redirect_stdout

        class _ExitedInterruptingProc:
            def __init__(self, args, **kwargs):
                self.args = args
                self.kwargs = kwargs
                self._interrupted = False

            def poll(self):
                return 0

            def wait(self, timeout=None):
                if not self._interrupted:
                    self._interrupted = True
                    raise KeyboardInterrupt()
                return 0

            def kill(self):
                pass

        buf = io.StringIO()
        with patch.object(
            subprocess, "Popen", side_effect=_ExitedInterruptingProc
        ), patch.object(
            smoke, "_terminate_process_tree", side_effect=AssertionError(
                "cleanup must not run when the worker already exited"
            )
        ), redirect_stdout(buf):
            with self.assertRaises(KeyboardInterrupt):
                smoke._run_parent("SH.000016", timeout=60)
        self.assertEqual(buf.getvalue(), "")

    def test_run_parent_preserves_known_exit_codes(self):
        for code in (0, 1, 124):
            result, _ = self._patch_popen("SH.000016", exit_code=code)
            self.assertEqual(result, code)

    def test_run_parent_rejects_non_positive_timeout_before_spawn(self):
        """A non-positive timeout is a defensive input error: ``_run_parent``
        raises before any subprocess spawn."""
        def _fail_popen(*args, **kwargs):
            raise AssertionError("Popen must not be called for non-positive timeout")

        with patch.object(subprocess, "Popen", side_effect=_fail_popen) as mock_popen:
            with self.assertRaises(ValueError):
                smoke._run_parent("SH.000016", timeout=0)
            with self.assertRaises(ValueError):
                smoke._run_parent("SH.000016", timeout=-5)
        mock_popen.assert_not_called()

    def test_main_rejects_non_positive_timeout_without_running_branches(self):
        """``main()`` rejects ``--timeout <= 0`` as an input error (exit 2)
        without calling ``_run_parent`` or ``_run_worker`` (no spawn)."""
        def _fail_worker(target):
            raise AssertionError("_run_worker must not be called")

        def _fail_parent(target, timeout):
            raise AssertionError("_run_parent must not be called")

        with patch.object(smoke, "_run_worker", side_effect=_fail_worker) as mock_worker, patch.object(
            smoke, "_run_parent", side_effect=_fail_parent
        ) as mock_parent:
            result = smoke.main(["SH.000016", "--timeout", "0"])
        self.assertEqual(result, 2)
        mock_worker.assert_not_called()
        mock_parent.assert_not_called()


class TestWorkerCodeMismatch(unittest.TestCase):
    """When the response carries a task identity but the extra stock code
    does not match the authoritative matrix expectation, the worker must
    emit an explicit mismatch error with expected and actual values — not
    the successful response text."""

    def _run_worker_with_response(self, response):
        class _FakeDispatcher:
            def __init__(self, *args, **kwargs):
                pass

            def register(self, command):
                pass

            async def dispatch_async(self, message):
                return response

        with patch("bot.dispatcher.CommandDispatcher", side_effect=_FakeDispatcher), patch(
            "src.services.task_service.get_task_service"
        ) as mock_service:
            buf = io.StringIO()
            with redirect_stdout(buf):
                exit_code = smoke._run_worker("SH.000016")
            mock_service.assert_not_called()
        return exit_code, buf.getvalue()

    def test_code_mismatch_emits_explicit_error_with_expected_and_actual(self):
        from bot.models import BotResponse

        exit_code, output = self._run_worker_with_response(
            BotResponse(text="ok", extra={"task_id": "t1", "stock_code": "csi930955"})
        )
        self.assertEqual(exit_code, 1)
        self.assertNotIn("E2E_EVENT {\"phase\": \"completed\"", output)
        event_line = next(
            line for line in output.splitlines()
            if line.startswith("E2E_EVENT ")
        )
        payload = json.loads(event_line[len("E2E_EVENT "):])
        self.assertEqual(payload["phase"], "failed")
        self.assertEqual(payload["target"], "SH.000016")
        self.assertIn("submitted code mismatch", payload["error"])
        self.assertIn("expected 'sh000016'", payload["error"])
        self.assertIn("got 'csi930955'", payload["error"])
        # 结构化 ``stock_code`` 携带实际提交的 code（与 error 中的实际值一致）。
        self.assertEqual(payload["stock_code"], "csi930955")
        # 不是成功响应文本。
        self.assertNotIn("分析任务已提交", payload["error"])

    def test_code_mismatch_with_missing_stock_code_emits_null_structured_code(self):
        """When the response has a task id but no ``extra.stock_code``, the
        failed event still carries a structured ``stock_code`` (null) plus
        the explicit mismatch error."""
        from bot.models import BotResponse

        exit_code, output = self._run_worker_with_response(
            BotResponse(text="ok", extra={"task_id": "t1"})
        )
        self.assertEqual(exit_code, 1)
        event_line = next(
            line for line in output.splitlines()
            if line.startswith("E2E_EVENT ")
        )
        payload = json.loads(event_line[len("E2E_EVENT "):])
        self.assertEqual(payload["phase"], "failed")
        self.assertIn("submitted code mismatch", payload["error"])
        self.assertIn("got None", payload["error"])
        self.assertIsNone(payload["stock_code"])


class TestWorkerSuccessPath(unittest.TestCase):
    """Offline integration-style success path: a matching ``BotResponse.extra``
    plus a fake in-process TaskService that reaches completed must produce
    ordered ``submitted`` then ``completed`` events, poll the service, and
    exit 0."""

    def _run_worker_with_service(self, service, response=None):
        from bot.models import BotResponse

        if response is None:
            response = BotResponse(
                text="ok", extra={"task_id": "t1", "stock_code": "sh000016"}
            )

        class _FakeDispatcher:
            def __init__(self, *args, **kwargs):
                pass

            def register(self, command):
                pass

            async def dispatch_async(self, message):
                return response

        with patch("bot.dispatcher.CommandDispatcher", side_effect=_FakeDispatcher), patch(
            "src.services.task_service.get_task_service", return_value=service
        ), patch("time.sleep"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                exit_code = smoke._run_worker("SH.000016")
        return exit_code, buf.getvalue()

    def test_success_path_polls_service_and_emits_ordered_events(self):
        class _FakeService:
            def __init__(self):
                self.polls = 0

            def get_task_status(self, task_id):
                self.polls += 1
                if self.polls == 1:
                    return None  # 空初始状态：等待
                return {
                    "status": "completed",
                    "code": "sh000016",
                    "result": {
                        "code": "sh000016",
                        "name": "上证50",
                        "analysis_summary": "摘要",
                        "operation_advice": "持有",
                        "trend_prediction": "震荡",
                    },
                }

        service = _FakeService()
        exit_code, output = self._run_worker_with_service(service)
        self.assertEqual(exit_code, 0)
        self.assertEqual(service.polls, 2)
        events = [
            json.loads(line[len("E2E_EVENT "):])
            for line in output.splitlines()
            if line.startswith("E2E_EVENT ")
        ]
        self.assertEqual([e["phase"] for e in events], ["submitted", "completed"])
        self.assertEqual(events[0]["task_id"], "t1")
        self.assertEqual(events[0]["stock_code"], "sh000016")
        self.assertEqual(events[1]["result"]["code"], "sh000016")
        self.assertEqual(events[1]["result"]["name"], "上证50")

    def test_no_task_id_response_returns_1_with_failed_event(self):
        """A response without a task identity (e.g. submission failure) must
        return 1 with a failed event and never poll the service."""
        class _FakeService:
            def get_task_status(self, task_id):
                raise AssertionError("service must not be polled")

        from bot.models import BotResponse

        exit_code, output = self._run_worker_with_service(
            _FakeService(),
            response=BotResponse(text="❌ 错误：提交分析任务失败: boom"),
        )
        self.assertEqual(exit_code, 1)
        events = [
            json.loads(line[len("E2E_EVENT "):])
            for line in output.splitlines()
            if line.startswith("E2E_EVENT ")
        ]
        self.assertEqual([e["phase"] for e in events], ["failed"])
        self.assertIn("提交分析任务失败", events[0]["error"])


class TestWorkerExceptionContract(unittest.TestCase):
    """Unexpected exceptions from dispatch / poll / event serialization must
    produce a ``failed`` E2E event and exit 1 (with evidence on stderr),
    never an uncaught traceback. ``KeyboardInterrupt`` is not treated as an
    ordinary failure."""

    def _run_worker_with_dispatcher(self, dispatcher):
        with patch("bot.dispatcher.CommandDispatcher", side_effect=dispatcher):
            buf = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(buf), patch("sys.stderr", err):
                exit_code = smoke._run_worker("SH.000016")
        return exit_code, buf.getvalue(), err.getvalue()

    def test_dispatch_exception_emits_failed_event_and_exit_1(self):
        class _BoomDispatcher:
            def __init__(self, *args, **kwargs):
                pass

            def register(self, command):
                pass

            async def dispatch_async(self, message):
                raise RuntimeError("dispatch exploded")

        exit_code, output, err = self._run_worker_with_dispatcher(_BoomDispatcher)
        self.assertEqual(exit_code, 1)
        event_line = next(
            line for line in output.splitlines()
            if line.startswith("E2E_EVENT ")
        )
        payload = json.loads(event_line[len("E2E_EVENT "):])
        self.assertEqual(payload["phase"], "failed")
        self.assertEqual(payload["target"], "SH.000016")
        self.assertIn("worker exception", payload["error"])
        self.assertIn("dispatch exploded", payload["error"])
        self.assertIn("dispatch exploded", err)

    def test_poll_exception_emits_failed_event_and_exit_1(self):
        from bot.models import BotResponse

        class _BoomService:
            def get_task_status(self, task_id):
                raise RuntimeError("poll exploded")

        class _FakeDispatcher:
            def __init__(self, *args, **kwargs):
                pass

            def register(self, command):
                pass

            async def dispatch_async(self, message):
                return BotResponse(
                    text="ok", extra={"task_id": "t1", "stock_code": "sh000016"}
                )

        with patch("bot.dispatcher.CommandDispatcher", side_effect=_FakeDispatcher), patch(
            "src.services.task_service.get_task_service", return_value=_BoomService()
        ), patch("time.sleep"):
            buf = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(buf), patch("sys.stderr", err):
                exit_code = smoke._run_worker("SH.000016")
        self.assertEqual(exit_code, 1)
        events = [
            json.loads(line[len("E2E_EVENT "):])
            for line in buf.getvalue().splitlines()
            if line.startswith("E2E_EVENT ")
        ]
        self.assertEqual([e["phase"] for e in events], ["submitted", "failed"])
        self.assertIn("poll exploded", events[1]["error"])
        self.assertIn("poll exploded", err.getvalue())

    def test_keyboard_interrupt_is_not_swallowed(self):
        class _KillDispatcher:
            def __init__(self, *args, **kwargs):
                pass

            def register(self, command):
                pass

            async def dispatch_async(self, message):
                raise KeyboardInterrupt()

        with patch("bot.dispatcher.CommandDispatcher", side_effect=_KillDispatcher):
            with self.assertRaises(KeyboardInterrupt):
                smoke._run_worker("SH.000016")


class TestResultCompleteness(unittest.TestCase):
    """A completed task is only a success when the canonical code equals the
    authoritative expected code, the name equals the registered display name,
    and the three non-empty result fields (analysis_summary /
    operation_advice / trend_prediction) are present."""

    def _complete(self):
        return {
            "code": "sh000016",
            "name": "上证50",
            "analysis_summary": "摘要",
            "operation_advice": "持有",
            "trend_prediction": "震荡",
        }

    def test_complete_result_has_no_error(self):
        self.assertIsNone(
            smoke._assert_complete_result(self._complete(), "sh000016", "上证50")
        )

    def test_missing_code_is_failure(self):
        result = self._complete()
        del result["code"]
        self.assertIn("code", smoke._assert_complete_result(result, "sh000016", "上证50") or "")

    def test_wrong_code_is_failure(self):
        result = self._complete()
        result["code"] = "csi930955"
        self.assertIn("code", smoke._assert_complete_result(result, "sh000016", "上证50") or "")

    def test_missing_name_is_failure(self):
        result = self._complete()
        del result["name"]
        self.assertIn("name", smoke._assert_complete_result(result, "sh000016", "上证50") or "")

    def test_wrong_name_is_failure(self):
        result = self._complete()
        result["name"] = "红利低波100"
        self.assertIn("name", smoke._assert_complete_result(result, "sh000016", "上证50") or "")

    def test_missing_analysis_summary_is_failure(self):
        result = self._complete()
        del result["analysis_summary"]
        self.assertIn(
            "analysis_summary",
            smoke._assert_complete_result(result, "sh000016", "上证50") or "",
        )

    def test_missing_operation_advice_is_failure(self):
        result = self._complete()
        del result["operation_advice"]
        self.assertIn(
            "operation_advice",
            smoke._assert_complete_result(result, "sh000016", "上证50") or "",
        )

    def test_missing_trend_prediction_is_failure(self):
        result = self._complete()
        del result["trend_prediction"]
        self.assertIn(
            "trend_prediction",
            smoke._assert_complete_result(result, "sh000016", "上证50") or "",
        )

    def test_empty_operation_advice_is_failure(self):
        result = self._complete()
        result["operation_advice"] = ""
        self.assertIn(
            "operation_advice",
            smoke._assert_complete_result(result, "sh000016", "上证50") or "",
        )

    def test_whitespace_only_analysis_summary_is_failure(self):
        result = self._complete()
        result["analysis_summary"] = "   \t "
        self.assertIn(
            "analysis_summary",
            smoke._assert_complete_result(result, "sh000016", "上证50") or "",
        )

    def test_whitespace_only_operation_advice_is_failure(self):
        result = self._complete()
        result["operation_advice"] = " \n "
        self.assertIn(
            "operation_advice",
            smoke._assert_complete_result(result, "sh000016", "上证50") or "",
        )

    def test_whitespace_only_trend_prediction_is_failure(self):
        result = self._complete()
        result["trend_prediction"] = "  "
        self.assertIn(
            "trend_prediction",
            smoke._assert_complete_result(result, "sh000016", "上证50") or "",
        )

    def test_sentiment_score_is_not_required(self):
        """``sentiment_score`` is not part of the spec's required fields."""
        result = self._complete()
        self.assertNotIn("sentiment_score", result)
        self.assertIsNone(
            smoke._assert_complete_result(result, "sh000016", "上证50")
        )


class TestPollOnce(unittest.TestCase):
    """Empty initial state must wait (None), then surface exactly one final
    phase event: completed / failed."""

    def _service(self, status_payload):
        class _FakeService:
            def get_task_status(self, task_id):
                return status_payload

        return _FakeService()

    def test_empty_initial_state_returns_none(self):
        self.assertIsNone(
            smoke._poll_once(
                self._service(None), "t1", "SH.000016", "sh000016"
            )
        )

    def test_running_state_returns_none(self):
        self.assertIsNone(
            smoke._poll_once(
                self._service({"status": "running"}),
                "t1",
                "SH.000016",
                "sh000016",
            )
        )

    def test_completed_state_emits_completed_event(self):
        event = smoke._poll_once(
            self._service(
                {
                    "status": "completed",
                    "code": "sh000016",
                    "result": {
                        "code": "sh000016",
                        "name": "上证50",
                        "analysis_summary": "摘要",
                        "operation_advice": "持有",
                        "trend_prediction": "震荡",
                    },
                }
            ),
            "t1",
            "SH.000016",
            "sh000016",
        )
        self.assertEqual(event["phase"], "completed")
        self.assertEqual(event["target"], "SH.000016")
        self.assertEqual(event["task_id"], "t1")
        self.assertEqual(event["stock_code"], "sh000016")
        self.assertEqual(event["result"]["code"], "sh000016")

    def test_completed_with_wrong_code_emits_failed_event(self):
        """Dispatcher routed the wrong code: the completed result carries a
        different canonical, which must fail against the matrix expectation."""
        event = smoke._poll_once(
            self._service(
                {
                    "status": "completed",
                    "code": "csi930955",
                    "result": {
                        "code": "csi930955",
                        "name": "红利低波100",
                        "analysis_summary": "摘要",
                        "operation_advice": "持有",
                        "trend_prediction": "震荡",
                    },
                }
            ),
            "t1",
            "SH.000016",
            "sh000016",
        )
        self.assertEqual(event["phase"], "failed")
        self.assertIn("code", event.get("error", ""))

    def test_completed_with_wrong_name_emits_failed_event(self):
        """The pipeline reported the wrong display name: must fail."""
        event = smoke._poll_once(
            self._service(
                {
                    "status": "completed",
                    "code": "sh000016",
                    "result": {
                        "code": "sh000016",
                        "name": "红利低波100",
                        "analysis_summary": "摘要",
                        "operation_advice": "持有",
                        "trend_prediction": "震荡",
                    },
                }
            ),
            "t1",
            "SH.000016",
            "sh000016",
        )
        self.assertEqual(event["phase"], "failed")
        self.assertIn("name", event.get("error", ""))

    def test_completed_without_analysis_summary_emits_failed_event(self):
        event = smoke._poll_once(
            self._service(
                {
                    "status": "completed",
                    "code": "sh000016",
                    "result": {
                        "code": "sh000016",
                        "name": "上证50",
                        "operation_advice": "持有",
                        "trend_prediction": "震荡",
                    },
                }
            ),
            "t1",
            "SH.000016",
            "sh000016",
        )
        self.assertEqual(event["phase"], "failed")
        self.assertIn("analysis_summary", event.get("error", ""))

    def test_failed_state_emits_failed_event(self):
        event = smoke._poll_once(
            self._service({"status": "failed", "error": "数据源不可用"}),
            "t1",
            "SH.000016",
            "sh000016",
        )
        self.assertEqual(event["phase"], "failed")
        self.assertIn("数据源不可用", event.get("error", ""))

    def test_completed_but_incomplete_result_emits_failed_event(self):
        event = smoke._poll_once(
            self._service(
                {
                    "status": "completed",
                    "code": "sh000016",
                    "result": {"code": "sh000016", "name": "上证50"},
                }
            ),
            "t1",
            "SH.000016",
            "sh000016",
        )
        self.assertEqual(event["phase"], "failed")
        self.assertIn("analysis_summary", event.get("error", ""))


class TestEventEmit(unittest.TestCase):
    """Events are single-line ``E2E_EVENT {json}`` on stdout."""

    def test_emit_event_is_single_line_json(self):
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            smoke._emit_event("submitted", "SH.000016", task_id="t1")
        line = buf.getvalue().strip()
        self.assertTrue(line.startswith("E2E_EVENT "))
        payload = json.loads(line[len("E2E_EVENT "):])
        self.assertEqual(payload["phase"], "submitted")
        self.assertEqual(payload["target"], "SH.000016")
        self.assertEqual(payload["task_id"], "t1")


if __name__ == "__main__":
    unittest.main()
