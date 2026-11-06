# -*- coding: utf-8 -*-
"""Unit tests for the runnable agent trajectory eval entry (Issue #1956).

All tests are offline: ``run_eval._build_executor`` is monkeypatched with a
duck-typed stub, and the three checked-in fixtures provide real-shaped
``tool_calls_log`` payloads covering the positive path, the negative path
(missing expected tool + cached failure + max_steps) and the retry path.
The two runtime-seam guards (multi-arch acceptance and golden validation
against the real tool registry) are exercised via monkeypatched config /
registry access plus one lazy real-registry check.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from evals.agent_trajectory import run_eval
from evals.agent_trajectory.metrics import GoldenSample, load_golden_samples

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "agent_trajectory"


def _stub_executor(log, total_steps=None, stage_trajectories=None):
    """Duck-typed executor recording its run calls (no src/ import)."""

    class _Stub:
        def __init__(self):
            self.calls = []

        def run(self, task, context=None):
            self.calls.append((task, context))
            return SimpleNamespace(
                tool_calls_log=list(log),
                total_steps=total_steps,
                stage_trajectories=list(stage_trajectories or []),
            )

    return _Stub()


def _fixture(name):
    """Load a checked-in fixture payload: (tool_calls_log, total_steps)."""
    payload = json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return payload["tool_calls_log"], payload["total_steps"]


def _result_executor(result):
    """Duck-typed executor whose run always returns a fixed result object."""
    return SimpleNamespace(run=lambda task, context=None: result)


def _goldens():
    return {sample.id: sample for sample in load_golden_samples()}


# ---------------------------------------------------------------------------
# 1. run_sample: positive path
# ---------------------------------------------------------------------------
class TestRunSamplePositive:
    def test_full_hit_and_clean_metrics(self):
        log, total_steps = _fixture("positive_600519_technical")
        executor = _stub_executor(log, total_steps)
        m = run_eval.run_sample(executor, _goldens()["600519_technical"])
        assert m.expected_hit_rate == 1.0
        assert m.missing_expected == []
        assert m.optional_tools_used == ["search_stock_news"]
        assert m.distinct_steps == 5
        assert m.violations == []

    def test_json_report_contract(self, tmp_path):
        log, total_steps = _fixture("positive_600519_technical")
        out = tmp_path / "report.json"
        m = run_eval.run_sample(_stub_executor(log, total_steps), _goldens()["600519_technical"], json_out=out)
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["sample_id"] == "600519_technical"
        assert report["task_description"]
        assert report["stock_code"] == "600519"
        assert report["violations"] == m.violations
        metrics = report["metrics"]
        expected_fields = {
            "expected_hit_rate",
            "expected_total",
            "missing_expected",
            "optional_tools_used",
            "redundant_calls",
            "cached_calls",
            "failed_calls",
            "retries",
            "distinct_steps",
            "max_steps_touched",
            "violations",
        }
        assert set(metrics) == expected_fields
        assert metrics["expected_hit_rate"] == 1.0

    def test_text_summary_printed(self, capsys):
        log, total_steps = _fixture("positive_600519_technical")
        run_eval.run_sample(_stub_executor(log, total_steps), _goldens()["600519_technical"])
        out = capsys.readouterr().out
        assert "Agent Trajectory 评估报告" in out
        assert "3/3" in out
        assert "违规项: 无" in out

    def test_context_carries_stock_code(self):
        executor = _stub_executor([], total_steps=1)
        run_eval.run_sample(executor, _goldens()["600519_technical"])
        assert len(executor.calls) == 1
        task, context = executor.calls[0]
        assert context == {"stock_code": "600519"}
        assert "600519" in task

    def test_empty_stock_code_passes_no_context(self):
        executor = _stub_executor([], total_steps=1)
        sample = GoldenSample(
            id="no_context",
            task_description="t",
            stock_code="",
            expected_tools=["get_realtime_quote"],
        )
        run_eval.run_sample(executor, sample)
        _, context = executor.calls[0]
        assert context is None


# ---------------------------------------------------------------------------
# 2. run_sample: negative path (violations are findings, not exceptions)
# ---------------------------------------------------------------------------
class TestRunSampleNegative:
    def test_missing_tool_and_max_steps_violations(self):
        log, total_steps = _fixture("negative_600519_technical")
        m = run_eval.run_sample(_stub_executor(log, total_steps), _goldens()["600519_technical"])
        assert m.expected_hit_rate == pytest.approx(2 / 3)
        assert m.missing_expected == ["analyze_trend"]
        assert m.redundant_calls == 1
        assert m.cached_calls == 1
        assert m.failed_calls == 1
        assert m.max_steps_touched is True
        assert "trajectory reached allowed_max_steps (8)" in m.violations

    def test_violations_do_not_raise(self):
        log, total_steps = _fixture("negative_600519_technical")
        m = run_eval.run_sample(_stub_executor(log, total_steps), _goldens()["600519_technical"])
        assert m.violations  # the eval is a reporter, not a gate

    def test_executor_without_total_steps_still_scores(self):
        # A result without total_steps keeps the log-only step behaviour.
        log, _ = _fixture("negative_600519_technical")
        m = run_eval.run_sample(_stub_executor(log, None), _goldens()["600519_technical"])
        assert m.distinct_steps == 4
        assert m.max_steps_touched is False


# ---------------------------------------------------------------------------
# 3. run_sample: retry path (fail -> success -> success contract)
# ---------------------------------------------------------------------------
class TestRunSampleRetry:
    def test_fail_success_success_counts_one_retry(self):
        log, total_steps = _fixture("retry_000001_core_data_strict")
        m = run_eval.run_sample(_stub_executor(log, total_steps), _goldens()["000001_core_data_strict"])
        assert m.expected_hit_rate == 1.0
        assert m.retries == 1
        assert m.redundant_calls == 2
        assert m.failed_calls == 1
        assert m.cached_calls == 0
        assert m.optional_tools_used == []
        assert m.violations == []


# ---------------------------------------------------------------------------
# 3.5 run failure: results carrying an explicit success=False
# ---------------------------------------------------------------------------
class TestRunFailure:
    def test_unsuccessful_single_agent_result_raises_without_report(self, capsys):
        # Single-agent failure behavior stays unchanged when no stage trace exists.
        executor = _result_executor(SimpleNamespace(success=False, error="boom", tool_calls_log=[], total_steps=0))
        with pytest.raises(RuntimeError, match="boom"):
            run_eval.run_sample(executor, _goldens()["600519_technical"])
        assert "Agent Trajectory 评估报告" not in capsys.readouterr().out

    def test_unsuccessful_result_without_error_raises(self):
        executor = _result_executor(SimpleNamespace(success=False, tool_calls_log=[], total_steps=0))
        with pytest.raises(RuntimeError, match="success=false"):
            run_eval.run_sample(executor, _goldens()["600519_technical"])

    def test_explicit_success_true_scores_normally(self):
        log, total_steps = _fixture("positive_600519_technical")
        result = SimpleNamespace(success=True, tool_calls_log=list(log), total_steps=total_steps)
        m = run_eval.run_sample(_result_executor(result), _goldens()["600519_technical"])
        assert m.expected_hit_rate == 1.0

    def test_missing_success_field_is_tolerated(self):
        # Duck-typed stubs without a success attribute keep the old behaviour.
        log, total_steps = _fixture("positive_600519_technical")
        result = SimpleNamespace(tool_calls_log=list(log), total_steps=total_steps)
        m = run_eval.run_sample(_result_executor(result), _goldens()["600519_technical"])
        assert m.expected_hit_rate == 1.0

    def test_success_none_is_tolerated(self):
        log, total_steps = _fixture("positive_600519_technical")
        result = SimpleNamespace(success=None, tool_calls_log=list(log), total_steps=total_steps)
        m = run_eval.run_sample(_result_executor(result), _goldens()["600519_technical"])
        assert m.expected_hit_rate == 1.0

    def test_failed_multi_agent_result_writes_stage_report_before_raising(self, tmp_path, capsys):
        stage_log = [{"step": 1, "tool": "get_realtime_quote", "success": False}]
        result = SimpleNamespace(
            success=False,
            error="Stage 'technical' failed: provider timeout",
            tool_calls_log=stage_log,
            total_steps=1,
            stage_trajectories=[
                {
                    "stage_name": "technical",
                    "status": "failed",
                    "failure_reason": "timeout",
                    "total_steps": 3,
                    "tool_calls_log": stage_log,
                }
            ],
        )
        sample = GoldenSample(
            id="failed_multi",
            task_description="multi-agent failure",
            expected_tools=["get_realtime_quote"],
            expected_stages=["technical", "decision"],
        )
        out = tmp_path / "failed-multi.json"

        with pytest.raises(RuntimeError, match="provider timeout"):
            run_eval.run_sample(_result_executor(result), sample, json_out=out)

        report = json.loads(out.read_text(encoding="utf-8"))
        stage_metrics = report["stage_metrics"]
        assert report["run_status"] == "failed"
        assert stage_metrics["failed_stages"] == 1
        assert stage_metrics["missing_expected_stages"] == ["decision"]
        assert stage_metrics["cumulative_steps"] == 3
        assert stage_metrics["stage_metrics"][0]["failure_reason"] == "timeout"
        output = capsys.readouterr().out
        assert "阶段 technical: 状态=failed" in output
        assert "局部步数=3" in output
        assert "缺失期望阶段: decision" in output
        assert "失败原因=timeout" in output

    def test_orchestrator_critical_failure_reaches_stage_report(self, tmp_path, capsys):
        try:
            import litellm  # noqa: F401
        except ModuleNotFoundError:
            sys.modules["litellm"] = MagicMock()

        from src.agent.orchestrator import AgentOrchestrator
        from src.agent.protocols import StageFailureReason, StageResult, StageStatus

        tool_log = [{"step": 1, "tool": "get_realtime_quote", "success": False}]
        technical = MagicMock(agent_name="technical")
        technical.run.return_value = StageResult(
            stage_name="technical",
            status=StageStatus.FAILED,
            failure_reason=StageFailureReason.TIMEOUT,
            total_steps=3,
            meta={"tool_calls_log": tool_log},
        )
        orchestrator = AgentOrchestrator(tool_registry=MagicMock(), llm_adapter=MagicMock())
        sample = GoldenSample(
            id="orchestrator_failure",
            task_description="critical stage failure",
            expected_tools=["get_realtime_quote"],
            expected_stages=["technical", "decision"],
        )
        report_path = tmp_path / "orchestrator-failure.json"

        with patch.object(orchestrator, "_build_agent_chain", return_value=[technical]):
            result = orchestrator.run(sample.task_description)

        assert result.success is False
        assert result.stage_trajectories[0]["status"] == "failed"
        assert result.stage_trajectories[0]["failure_reason"] == "timeout"
        with pytest.raises(RuntimeError, match="Stage 'technical' failed"):
            run_eval.run_sample(_result_executor(result), sample, json_out=report_path)

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["run_status"] == "failed"
        assert report["stage_metrics"]["failed_stages"] == 1
        assert report["stage_metrics"]["missing_expected_stages"] == ["decision"]
        assert report["stage_metrics"]["cumulative_steps"] == 3
        output = capsys.readouterr().out
        assert "阶段 technical: 状态=failed" in output
        assert "失败原因=timeout" in output

    def test_orchestrator_stage_loop_totals_drive_global_budget_metrics(self, tmp_path, capsys):
        try:
            import litellm  # noqa: F401
        except ModuleNotFoundError:
            sys.modules["litellm"] = MagicMock()

        from src.agent.orchestrator import AgentOrchestrator
        from src.agent.protocols import StageResult, StageStatus

        quote_log = [{"step": 1, "tool": "quote", "success": True}]
        news_log = [{"step": 1, "tool": "news", "success": True}]
        technical = MagicMock(agent_name="technical")
        technical.run.return_value = StageResult(
            stage_name="technical",
            status=StageStatus.COMPLETED,
            total_steps=3,
            meta={"tool_calls_log": quote_log},
        )
        intel = MagicMock(agent_name="intel")
        intel.run.return_value = StageResult(
            stage_name="intel",
            status=StageStatus.COMPLETED,
            total_steps=3,
            meta={"tool_calls_log": news_log},
        )
        orchestrator = AgentOrchestrator(tool_registry=MagicMock(), llm_adapter=MagicMock())
        with (
            patch.object(orchestrator, "_build_agent_chain", return_value=[technical, intel]),
            patch.object(
                orchestrator,
                "_resolve_final_output",
                return_value=({"ok": True}, "final report"),
            ),
        ):
            result = orchestrator.run("analyze one stock")

        # Keep the runtime's established stage-count contract; the evaluator
        # must derive loop totals from the explicit stage snapshots instead.
        assert result.total_steps == 2
        assert [item["total_steps"] for item in result.stage_trajectories] == [3, 3]
        sample = GoldenSample(
            id="multi_aggregate_steps",
            task_description="analyze one stock",
            expected_tools=["quote", "news"],
            allowed_max_steps=5,
            expected_stages=["technical", "intel"],
        )
        report_path = tmp_path / "aggregate-steps.json"

        run_eval.run_sample(_result_executor(result), sample, json_out=report_path)

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["stage_metrics"]["cumulative_steps"] == 6
        assert report["metrics"]["distinct_steps"] == 6
        assert report["metrics"]["max_steps_touched"] is True
        assert report["violations"] == ["trajectory reached allowed_max_steps (5)"]
        assert "消耗步数: 6 (触碰 max_steps: 是)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 4. runtime-seam guards: multi-arch rejection + golden registry validation
# ---------------------------------------------------------------------------
class TestArchGuard:
    def test_multi_arch_is_allowed(self, monkeypatch):
        import src.config

        monkeypatch.setattr(src.config, "get_config", lambda: SimpleNamespace(agent_arch="multi"))
        assert run_eval._check_agent_arch() == "multi"

    def test_single_arch_passes(self, monkeypatch):
        import src.config

        monkeypatch.setattr(src.config, "get_config", lambda: SimpleNamespace(agent_arch="single"))
        run_eval._check_agent_arch()  # no raise


class TestGoldenRegistryValidation:
    def test_unknown_expected_tools_exit_one(self, tmp_path, monkeypatch, capsys):
        # A misspelled expected tool must fail as an invalid sample, not score low.
        custom = [
            {
                "id": "typo_sample",
                "task_description": "t",
                "stock_code": "",
                "expected_tools": ["get_daily_histroy"],
                "allowed_max_steps": 10,
                "allow_optional_tools": True,
            }
        ]
        golden_path = tmp_path / "golden.json"
        golden_path.write_text(json.dumps(custom, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(run_eval, "_known_tool_names", lambda: {"get_realtime_quote"})
        assert run_eval.main(["--sample", "typo_sample", "--golden-path", str(golden_path)]) == 1
        err = capsys.readouterr().err
        assert "unknown expected_tools" in err
        assert "get_daily_histroy" in err

    def test_checked_in_goldens_pass_real_registry(self):
        known = run_eval._known_tool_names()
        assert len(known) > 5  # sanity: the real registry is non-trivial
        load_golden_samples(known_tool_names=known)  # must not raise

    def test_registry_load_failure_exit_one(self, monkeypatch, capsys):
        def _boom():
            raise ImportError("no tool modules")

        monkeypatch.setattr(run_eval, "_known_tool_names", _boom)
        assert run_eval.main(["--sample", "600519_technical"]) == 1
        assert "failed to load tool registry" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 5. CLI (main): exit codes, selection, JSON output
# ---------------------------------------------------------------------------
class TestMainCli:
    @pytest.fixture(autouse=True)
    def _stub_builder(self, monkeypatch):
        executor = _stub_executor([], total_steps=1)
        monkeypatch.setattr(run_eval, "_build_executor", lambda: executor)
        return executor

    def test_exit_zero_successful_sample(self, capsys):
        assert run_eval.main(["--sample", "600519_technical"]) == 0
        out = capsys.readouterr().out
        assert "[eval] sample: 600519_technical" in out
        assert "Agent Trajectory 评估报告" in out

    def test_unknown_sample_id_exit_one(self, capsys):
        assert run_eval.main(["--sample", "no-such-id"]) == 1
        err = capsys.readouterr().err
        assert "unknown sample id 'no-such-id'" in err
        assert "600519_technical" in err and "000001_core_data_strict" in err

    def test_missing_arguments_exit_two(self):
        with pytest.raises(SystemExit) as excinfo:
            run_eval.main([])
        assert excinfo.value.code == 2

    def test_both_flags_exit_two(self):
        with pytest.raises(SystemExit) as excinfo:
            run_eval.main(["--sample", "600519_technical", "--all"])
        assert excinfo.value.code == 2

    def test_build_failure_exit_one(self, monkeypatch, capsys):
        def _boom():
            raise RuntimeError("no api key configured")

        monkeypatch.setattr(run_eval, "_build_executor", _boom)
        assert run_eval.main(["--sample", "600519_technical"]) == 1
        assert "failed to build agent executor" in capsys.readouterr().err

    def test_multi_arch_result_emits_stage_report(self, tmp_path, capsys):
        log, total_steps = _fixture("positive_600519_technical")
        result = SimpleNamespace(
            success=True,
            tool_calls_log=list(log),
            total_steps=total_steps,
            stage_trajectories=[
                {
                    "stage_name": "technical",
                    "status": "completed",
                    "total_steps": 2,
                    "tool_calls_log": list(log),
                },
                {
                    "stage_name": "decision",
                    "status": "skipped",
                    "total_steps": 0,
                    "tool_calls_log": [],
                    "failure_reason": "budget_skip",
                },
            ],
        )
        out = tmp_path / "multi.json"
        run_eval.run_sample(
            _result_executor(result),
            GoldenSample(
                id="multi",
                task_description="multi task",
                expected_tools=["get_realtime_quote", "get_daily_history", "analyze_trend"],
                expected_stages=["technical", "decision"],
            ),
            json_out=out,
        )

        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["stage_metrics"]["expected_stage_hit_rate"] == 1.0
        assert report["stage_metrics"]["skipped_stages"] == 1
        assert "Multi-Agent 阶段轨迹" in capsys.readouterr().out

    def test_multi_agent_tool_metrics_are_local_while_golden_scoring_is_global(self, tmp_path, capsys):
        quote_failed = {
            "step": 1,
            "tool": "quote",
            "arguments": {"symbol": "600519"},
            "success": False,
            "cached": False,
        }
        quote_retry = {
            "step": 2,
            "tool": "quote",
            "arguments": {"symbol": "600519"},
            "success": True,
            "cached": False,
        }
        news_call = {
            "step": 1,
            "tool": "news",
            "arguments": {"symbol": "600519"},
            "success": True,
            "cached": True,
        }
        result = SimpleNamespace(
            success=True,
            tool_calls_log=[quote_failed, quote_retry, news_call],
            total_steps=6,
            stage_trajectories=[
                {
                    "stage_name": "technical",
                    "status": "completed",
                    "total_steps": 3,
                    "tool_calls_log": [quote_failed, quote_retry],
                },
                {
                    "stage_name": "intel",
                    "status": "completed",
                    "total_steps": 3,
                    "tool_calls_log": [news_call],
                },
            ],
        )
        sample = GoldenSample(
            id="multi_stage_tool_expectations",
            task_description="Use quote in technical and news in intel",
            expected_tools=["quote", "news"],
            allowed_max_steps=3,
            allow_optional_tools=False,
            expected_stages=["technical", "intel"],
        )
        out = tmp_path / "multi-stage-tools.json"

        run_eval.run_sample(_result_executor(result), sample, json_out=out)

        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["metrics"]["expected_hit_rate"] == 1.0
        assert report["metrics"]["missing_expected"] == []
        assert report["metrics"]["optional_tools_used"] == []
        assert report["metrics"]["max_steps_touched"] is True
        assert report["violations"] == ["trajectory reached allowed_max_steps (3)"]

        stages = report["stage_metrics"]["stage_metrics"]
        technical_tools = stages[0]["tool_metrics"]
        intel_tools = stages[1]["tool_metrics"]
        assert technical_tools == {
            "tool_calls": 2,
            "tools_used": ["quote"],
            "redundant_calls": 1,
            "cached_calls": 0,
            "failed_calls": 1,
            "retries": 1,
        }
        assert intel_tools == {
            "tool_calls": 1,
            "tools_used": ["news"],
            "redundant_calls": 0,
            "cached_calls": 1,
            "failed_calls": 0,
            "retries": 0,
        }
        assert report["stage_metrics"]["violations"] == []
        output = capsys.readouterr().out
        assert "工具调用=2 | 工具失败=1 | 重试=1" in output
        assert "工具调用=1 | 工具失败=0 | 重试=0" in output

    def test_failed_multi_agent_cli_writes_json_and_returns_one(self, tmp_path, monkeypatch, capsys):
        golden_path = tmp_path / "golden.json"
        golden_path.write_text(
            json.dumps(
                [
                    {
                        "id": "failed_multi",
                        "task_description": "multi-agent failure",
                        "stock_code": "",
                        "expected_tools": ["get_realtime_quote"],
                        "expected_stages": ["technical", "decision"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        stage_log = [{"step": 1, "tool": "get_realtime_quote", "success": False}]
        failed_result = SimpleNamespace(
            success=False,
            error="technical provider timeout",
            tool_calls_log=stage_log,
            total_steps=1,
            stage_trajectories=[
                {
                    "stage_name": "technical",
                    "status": "failed",
                    "failure_reason": "timeout",
                    "total_steps": 2,
                    "tool_calls_log": stage_log,
                }
            ],
        )
        out = tmp_path / "cli-report.json"
        monkeypatch.setattr(run_eval, "_known_tool_names", lambda: {"get_realtime_quote"})
        monkeypatch.setattr(run_eval, "_build_executor", lambda: _result_executor(failed_result))

        assert run_eval.main(
            ["--sample", "failed_multi", "--golden-path", str(golden_path), "--json-out", str(out)]
        ) == 1

        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["run_status"] == "failed"
        assert report["stage_metrics"]["missing_expected_stages"] == ["decision"]
        assert "状态=failed" in capsys.readouterr().out

    def test_run_failure_exit_one(self, monkeypatch, capsys):
        class _Exploding:
            def run(self, task, context=None):
                raise RuntimeError("llm timeout")

        monkeypatch.setattr(run_eval, "_build_executor", lambda: _Exploding())
        assert run_eval.main(["--sample", "600519_technical"]) == 1
        assert "sample '600519_technical' failed" in capsys.readouterr().err

    def test_unsuccessful_result_exit_one(self, monkeypatch, capsys):
        # Owner repro: a result object with success=False is a run failure.
        result = SimpleNamespace(success=False, error="boom", tool_calls_log=[], total_steps=0)
        monkeypatch.setattr(run_eval, "_build_executor", lambda: _result_executor(result))
        assert run_eval.main(["--sample", "600519_technical"]) == 1
        err = capsys.readouterr().err
        assert "sample '600519_technical' failed" in err
        assert "boom" in err

    def test_all_returns_one_when_a_sample_result_is_unsuccessful(self, monkeypatch, capsys):
        result = SimpleNamespace(success=False, tool_calls_log=[], total_steps=0)
        monkeypatch.setattr(run_eval, "_build_executor", lambda: _result_executor(result))
        assert run_eval.main(["--all"]) == 1
        assert "failed" in capsys.readouterr().err

    def test_violations_still_exit_zero(self, monkeypatch, capsys):
        log, total_steps = _fixture("negative_600519_technical")
        monkeypatch.setattr(run_eval, "_build_executor", lambda: _stub_executor(log, total_steps))
        assert run_eval.main(["--sample", "600519_technical"]) == 0
        assert "trajectory reached allowed_max_steps (8)" in capsys.readouterr().out

    def test_all_writes_keyed_json(self, tmp_path, capsys):
        out = tmp_path / "all.json"
        assert run_eval.main(["--all", "--json-out", str(out)]) == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert set(report) == {"600519_technical", "000001_core_data_strict"}
        for sample_report in report.values():
            assert set(sample_report) == {"sample_id", "task_description", "stock_code", "metrics", "violations"}

    def test_single_sample_json_out_is_not_keyed(self, tmp_path):
        out = tmp_path / "one.json"
        assert run_eval.main(["--sample", "600519_technical", "--json-out", str(out)]) == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["sample_id"] == "600519_technical"

    def test_utf8_chinese_roundtrip(self, tmp_path):
        out = tmp_path / "utf8.json"
        assert run_eval.main(["--sample", "600519_technical", "--json-out", str(out)]) == 0
        text = out.read_text(encoding="utf-8")
        assert "贵州茅台" in text
        json.loads(text)  # valid JSON with raw UTF-8 content

    def test_golden_path_override(self, tmp_path, capsys):
        custom = [
            {
                "id": "custom_sample",
                "task_description": "自定义任务",
                "stock_code": "",
                "expected_tools": ["get_realtime_quote"],
                "allowed_max_steps": 3,
                "allow_optional_tools": True,
            }
        ]
        golden_path = tmp_path / "golden.json"
        golden_path.write_text(json.dumps(custom, ensure_ascii=False), encoding="utf-8")
        assert run_eval.main(["--sample", "custom_sample", "--golden-path", str(golden_path)]) == 0
        assert "[eval] sample: custom_sample" in capsys.readouterr().out

    def test_load_failure_exit_one(self, capsys):
        assert run_eval.main(["--sample", "x", "--golden-path", "no/such/file.json"]) == 1
        assert "failed to load golden samples" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 6. Checked-in fixtures end to end (the owner-requested real-entry coverage)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "fixture_name,golden_id,expected",
    [
        (
            "positive_600519_technical",
            "600519_technical",
            dict(
                expected_hit_rate=1.0,
                missing_expected=[],
                redundant_calls=0,
                cached_calls=0,
                failed_calls=0,
                retries=0,
                distinct_steps=5,
                max_steps_touched=False,
                violations=[],
            ),
        ),
        (
            "negative_600519_technical",
            "600519_technical",
            dict(
                expected_hit_rate=pytest.approx(2 / 3),
                missing_expected=["analyze_trend"],
                redundant_calls=1,
                cached_calls=1,
                failed_calls=1,
                retries=0,
                distinct_steps=8,
                max_steps_touched=True,
            ),
        ),
        (
            "retry_000001_core_data_strict",
            "000001_core_data_strict",
            dict(
                expected_hit_rate=1.0,
                missing_expected=[],
                redundant_calls=2,
                cached_calls=0,
                failed_calls=1,
                retries=1,
                distinct_steps=5,
                max_steps_touched=False,
                violations=[],
            ),
        ),
    ],
)
def test_fixtures_end_to_end(fixture_name, golden_id, expected):
    log, total_steps = _fixture(fixture_name)
    m = run_eval.run_sample(_stub_executor(log, total_steps), _goldens()[golden_id])
    for field, value in expected.items():
        assert getattr(m, field) == value, (fixture_name, field)
    if "violations" in expected:
        assert m.violations == expected["violations"]
    else:
        assert m.violations and "trajectory reached allowed_max_steps (8)" in m.violations
