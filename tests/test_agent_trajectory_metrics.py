# -*- coding: utf-8 -*-
"""Unit tests for the agent trajectory evaluation metrics (Issue #1956).

All trajectories are synthetic ``tool_calls_log`` lists — no LLM, no network.
The golden-samples-file tests verify that the checked-in ``golden_samples.json``
stays structurally valid and that every ``expected_tools`` entry exists in the
repository's real tool registry (imported lazily so the metrics-only sections
run even without ``src/`` importable).
"""

import json

import pytest

from evals.agent_trajectory.metrics import (
    GoldenSample,
    TrajectoryMetrics,
    _args_key,
    compute_trajectory_metrics,
    format_text_report,
    load_golden_samples,
    validate_golden_sample,
)


def _entry(tool="get_realtime_quote", arguments=None, step=1, success=True, **extra):
    """Build a runner-shaped ``tool_calls_log`` entry with sensible defaults."""
    entry = {
        "step": step,
        "tool": tool,
        "arguments": arguments if arguments is not None else {"stock_code": "600519"},
        "success": success,
        "duration": 0.5,
        "result_length": 100,
        "cached": False,
    }
    entry.update(extra)
    return entry


def _golden(**overrides):
    values = dict(
        id="600519_technical",
        task_description="分析贵州茅台近期技术面走势",
        stock_code="600519",
        expected_tools=["get_realtime_quote", "get_daily_history", "analyze_trend"],
        allowed_max_steps=8,
        allow_optional_tools=True,
    )
    values.update(overrides)
    return GoldenSample(**values)


def _metrics(**overrides):
    values = dict(
        expected_hit_rate=2 / 3,
        expected_total=3,
        missing_expected=["analyze_trend"],
        optional_tools_used=[],
        redundant_calls=0,
        cached_calls=0,
        failed_calls=0,
        retries=0,
        distinct_steps=3,
        max_steps_touched=False,
        violations=[],
    )
    values.update(overrides)
    return TrajectoryMetrics(**values)


# ---------------------------------------------------------------------------
# 1. Args-key stability
# ---------------------------------------------------------------------------
class TestArgsKey:
    def test_key_stable_across_key_order_and_nested_unhashable(self):
        a = {"b": [1, 2], "a": {"x": {"y": 1}}}
        b = {"a": {"x": {"y": 1}}, "b": [1, 2]}
        assert _args_key(a) == _args_key(b)

    def test_key_differs_for_different_arguments(self):
        assert _args_key({"stock_code": "600519"}) != _args_key({"stock_code": "000001"})

    def test_none_arguments_use_empty_object(self):
        assert _args_key(None) == json.dumps({})

    def test_non_dict_arguments_serialized(self):
        assert _args_key(["600519"]) == '["600519"]'


# ---------------------------------------------------------------------------
# 2. Hit rate / expected & optional tools
# ---------------------------------------------------------------------------
class TestComputeMetricsHitRate:
    @staticmethod
    def _two_of_three_log():
        return [
            _entry(tool="get_realtime_quote", step=1),
            _entry(tool="get_daily_history", step=2),
            _entry(tool="search_stock_news", step=3),
        ]

    def test_hit_rate_missing_and_optional(self):
        m = compute_trajectory_metrics(self._two_of_three_log(), _golden())
        assert m.expected_hit_rate == pytest.approx(2 / 3)
        assert m.missing_expected == ["analyze_trend"]
        assert m.optional_tools_used == ["search_stock_news"]
        assert m.violations == []

    def test_optional_tools_not_allowed_produces_violation(self):
        m = compute_trajectory_metrics(self._two_of_three_log(), _golden(allow_optional_tools=False))
        assert m.violations == ["optional tools used but not allowed: search_stock_news"]
        assert m.expected_hit_rate == pytest.approx(2 / 3)

    def test_duplicate_tool_calls_still_full_hit(self):
        log = [
            _entry(tool="get_realtime_quote", arguments={"stock_code": "600519"}, step=1),
            _entry(tool="get_realtime_quote", arguments={"stock_code": "000001"}, step=2),
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.expected_hit_rate == 1.0
        assert m.missing_expected == []

    def test_empty_log_yields_zero_metrics(self):
        m = compute_trajectory_metrics([], _golden())
        assert m.expected_hit_rate == 0.0
        assert m.expected_total == 3
        assert m.missing_expected == ["get_realtime_quote", "get_daily_history", "analyze_trend"]
        assert m.redundant_calls == 0 and m.cached_calls == 0 and m.failed_calls == 0
        assert m.retries == 0 and m.distinct_steps == 0
        assert m.max_steps_touched is False
        assert m.violations == []

    def test_non_dict_entries_ignored(self):
        log = ["garbage", None, _entry(tool="get_realtime_quote", step=1)]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.expected_hit_rate == 1.0
        assert m.distinct_steps == 1

    def test_empty_expected_tools_yields_zero_hit_and_violation(self):
        m = compute_trajectory_metrics([_entry()], _golden(expected_tools=[]))
        assert m.expected_hit_rate == 0.0
        assert "expected_tools must be a non-empty list" in m.violations

    def test_string_expected_tools_scored_as_empty_not_as_characters(self):
        m = compute_trajectory_metrics([_entry()], _golden(expected_tools="get_realtime_quote"))
        assert m.expected_hit_rate == 0.0
        assert m.expected_total == 0
        assert "expected_tools must be a list of tool names" in m.violations

    def test_non_bool_allow_optional_tools_scores_strictly(self):
        log = [
            _entry(tool="get_realtime_quote", step=1),
            _entry(tool="search_stock_news", step=2),
        ]
        m = compute_trajectory_metrics(
            log,
            _golden(expected_tools=["get_realtime_quote"], allow_optional_tools="false"),
        )
        assert "allow_optional_tools must be a boolean" in m.violations
        assert "optional tools used but not allowed: search_stock_news" in m.violations

    def test_duplicate_expected_tools_scored_as_unique_names(self):
        # Regression: ["quote", "quote", "history"] with a single quote call
        # must read 1/2, not 2/3.
        golden = _golden(
            expected_tools=[
                "get_realtime_quote",
                "get_realtime_quote",
                "get_daily_history",
            ],
        )
        m = compute_trajectory_metrics([_entry(tool="get_realtime_quote")], golden)
        assert m.expected_total == 2
        assert m.expected_hit_rate == pytest.approx(0.5)
        assert m.missing_expected == ["get_daily_history"]
        assert "expected_tools must not contain duplicate names" in m.violations


# ---------------------------------------------------------------------------
# 2b. Direct-construction path: same structure contract as the loader
# ---------------------------------------------------------------------------
class TestDirectConstructionContract:
    def test_malformed_expected_tools_elements_are_reported(self):
        # Review counter-example: ['get_realtime_quote', ''] must not
        # silently collapse into a one-tool golden — the malformed element
        # is reported, only valid names take part in scoring.  Whitespace-
        # only elements follow the validator's predicate (t.strip()).
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": "600519"})]
        for malformed in (["get_realtime_quote", ""], ["get_realtime_quote", 1]):
            m = compute_trajectory_metrics(log, _golden(expected_tools=malformed))
            assert m.expected_hit_rate == 1.0
            assert "expected_tools must contain only non-empty strings" in m.violations

    def test_whitespace_only_expected_tool_does_not_pollute_scoring(self):
        # Review counter-example: '   ' must not enter the hit-rate
        # denominator nor show up as a missing tool — it is malformed.
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": "600519"})]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote", "   "]))
        assert m.expected_total == 1
        assert m.expected_hit_rate == 1.0
        assert m.missing_expected == []
        assert "expected_tools must contain only non-empty strings" in m.violations

    def test_non_positive_allowed_max_steps_reported_in_direct_score(self):
        # Review counter-example: allowed_max_steps=0 / -3 must report the
        # validator's wording instead of silently disabling the budget
        # assertion, no matter how many steps the trajectory takes.
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": "600519"}, step=s) for s in range(1, 100)]
        for limit in (0, -3):
            m = compute_trajectory_metrics(log, _golden(allowed_max_steps=limit))
            assert "allowed_max_steps must be >= 1" in m.violations
            assert m.max_steps_touched is False

    def test_direct_score_mirrors_validator_structure_contract(self):
        # The owner-requested parity: for each malformed golden shape the
        # validator rejects, the direct-score path must surface the same
        # issue wording in its violations.
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": "600519"})]
        cases = [
            (dict(expected_tools=["get_realtime_quote", "   "]), "expected_tools must contain only non-empty strings"),
            (dict(expected_tools=["get_realtime_quote", ""]), "expected_tools must contain only non-empty strings"),
            (dict(allowed_max_steps=0), "allowed_max_steps must be >= 1"),
            (dict(allowed_max_steps=-3), "allowed_max_steps must be >= 1"),
            (dict(allow_optional_tools="false"), "allow_optional_tools must be a boolean"),
            (dict(id=[]), "id must be a non-empty string"),
            (dict(task_description=None), "task_description must be a non-empty string"),
            (dict(stock_code=None), "stock_code must be a string"),
            (dict(stock_code="   "), "stock_code must not contain leading or trailing whitespace"),
        ]
        for overrides, issue in cases:
            golden = _golden(**overrides)
            validator_issues = validate_golden_sample(golden)
            assert any(issue in i for i in validator_issues), (issue, overrides, validator_issues)
            m = compute_trajectory_metrics(log, golden)
            assert any(issue in v for v in m.violations), (issue, overrides, m.violations)

    def test_every_validator_issue_surfaces_in_direct_score(self):
        # Structural lock: the direct-score path surfaces the validator's
        # COMPLETE issue list verbatim (this is how id / task_description /
        # stock_code and any future validator check apply to direct scoring
        # automatically).  A thoroughly malformed sample must yield every
        # validator issue in compute violations, with no duplicates from the
        # inline scoring checks.
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": "600519"})]
        golden = GoldenSample(
            id=[],
            task_description=None,
            stock_code="   ",
            expected_tools=["", "   "],
            allowed_max_steps=0,
            allow_optional_tools="false",
        )
        validator_issues = validate_golden_sample(golden)
        assert validator_issues, "the sample is thoroughly malformed"
        m = compute_trajectory_metrics(log, golden)
        for issue in validator_issues:
            assert any(issue in v for v in m.violations), (issue, m.violations)
            assert m.violations.count(issue) == 1, (issue, m.violations)


# ---------------------------------------------------------------------------
# 3. Retries, caching, failure counting
# ---------------------------------------------------------------------------
class TestRetryAndCaching:
    def test_fail_then_retry_success_counts_one_retry(self):
        log = [
            _entry(step=1, success=False),
            _entry(step=2, success=True),
        ]
        m = compute_trajectory_metrics(log, _golden())
        assert m.retries == 1
        assert m.redundant_calls == 1
        assert m.failed_calls == 1

    def test_same_tool_different_args_not_redundant(self):
        log = [
            _entry(arguments={"stock_code": "600519"}, step=1),
            _entry(arguments={"stock_code": "000001"}, step=2),
        ]
        m = compute_trajectory_metrics(log, _golden())
        assert m.redundant_calls == 0
        assert m.retries == 0

    def test_repeat_after_success_is_redundant_but_not_retry(self):
        log = [_entry(step=1, success=True), _entry(step=2, success=True)]
        m = compute_trajectory_metrics(log, _golden())
        assert m.redundant_calls == 1
        assert m.retries == 0
        assert m.failed_calls == 0

    def test_fail_fail_success_counts_two_retries(self):
        log = [
            _entry(step=1, success=False),
            _entry(step=2, success=False),
            _entry(step=3, success=True),
        ]
        m = compute_trajectory_metrics(log, _golden())
        assert m.retries == 2
        assert m.redundant_calls == 2
        assert m.failed_calls == 2

    def test_recovery_clears_failure_state(self):
        # fail -> success -> success: only the recovery attempt is a retry;
        # the repeat after success counts as redundant only.
        log = [
            _entry(step=1, success=False),
            _entry(step=2, success=True),
            _entry(step=3, success=True),
        ]
        m = compute_trajectory_metrics(log, _golden())
        assert m.retries == 1
        assert m.redundant_calls == 2
        assert m.failed_calls == 1

    def test_cached_entry_counted(self):
        m = compute_trajectory_metrics([_entry(cached=True, success=False)], _golden())
        assert m.cached_calls == 1
        assert m.failed_calls == 1


# ---------------------------------------------------------------------------
# 4. max_steps touching
# ---------------------------------------------------------------------------
class TestMaxStepsTouched:
    def test_steps_reaching_allowed_max_touched(self):
        log = [_entry(step=i) for i in range(1, 6)]
        m = compute_trajectory_metrics(log, _golden(allowed_max_steps=5))
        assert m.max_steps_touched is True
        assert "trajectory reached allowed_max_steps (5)" in m.violations

    def test_steps_below_limit_not_touched(self):
        log = [_entry(step=i) for i in range(1, 5)]
        m = compute_trajectory_metrics(log, _golden(allowed_max_steps=5))
        assert m.max_steps_touched is False
        assert m.violations == []

    def test_empty_log_not_touched(self):
        m = compute_trajectory_metrics([], _golden(allowed_max_steps=5))
        assert m.max_steps_touched is False

    def test_non_integer_limit_surfaces_violation_without_crash(self):
        log = [_entry(step=i) for i in range(1, 6)]
        m = compute_trajectory_metrics(log, _golden(allowed_max_steps="5"))
        assert m.max_steps_touched is False
        assert "allowed_max_steps must be an integer" in m.violations


# ---------------------------------------------------------------------------
# 4b. total_steps input (final answer round)
# ---------------------------------------------------------------------------
class TestTotalStepsInput:
    def test_total_steps_extends_step_metrics_beyond_log(self):
        log = [_entry(step=1), _entry(step=2)]
        m = compute_trajectory_metrics(log, _golden(allowed_max_steps=5), total_steps=4)
        assert m.distinct_steps == 4
        assert m.max_steps_touched is False

    def test_total_steps_can_touch_the_limit(self):
        log = [_entry(step=1), _entry(step=2)]
        m = compute_trajectory_metrics(log, _golden(allowed_max_steps=3), total_steps=3)
        assert m.max_steps_touched is True
        assert m.distinct_steps == 3

    def test_log_wins_when_it_reaches_further(self):
        log = [_entry(step=i) for i in range(1, 5)]
        m = compute_trajectory_metrics(log, _golden(allowed_max_steps=5), total_steps=2)
        assert m.distinct_steps == 4
        assert m.max_steps_touched is False

    def test_none_keeps_log_only_behaviour(self):
        m = compute_trajectory_metrics([_entry(step=1)], _golden())
        assert m.distinct_steps == 1

    def test_non_numeric_total_steps_ignored(self):
        m = compute_trajectory_metrics([_entry(step=1)], _golden(), total_steps="not-a-number")
        assert m.distinct_steps == 1


# ---------------------------------------------------------------------------
# 5. Tolerant entry shapes (missing fields)
# ---------------------------------------------------------------------------
class TestTolerantEntries:
    def test_missing_optional_fields_defaulted(self):
        m = compute_trajectory_metrics([{"step": 1, "tool": "get_realtime_quote"}], _golden())
        assert m.failed_calls == 0
        assert m.cached_calls == 0
        assert m.expected_hit_rate == pytest.approx(1 / 3)

    def test_entries_without_arguments_share_one_identity(self):
        # Arguments-less entries key as an empty object: a repeated call of
        # the same tool is redundant even without an arguments payload.
        log = [
            {"step": 1, "tool": "get_realtime_quote", "success": True},
            {"step": 2, "tool": "get_realtime_quote", "success": True},
        ]
        m = compute_trajectory_metrics(log, _golden())
        assert m.redundant_calls == 1
        assert m.retries == 0

    def test_invalid_step_coerced_to_zero(self):
        m = compute_trajectory_metrics([_entry(step="not-a-number")], _golden())
        assert m.distinct_steps == 0


# ---------------------------------------------------------------------------
# 6. Text report rendering
# ---------------------------------------------------------------------------
class TestFormatTextReport:
    def test_contains_hit_fraction_and_percent(self):
        text = format_text_report(_metrics())
        assert "2/3" in text
        assert "66.7%" in text

    def test_empties_render_placeholder(self):
        m = _metrics(
            expected_hit_rate=0.0,
            expected_total=3,
            missing_expected=["get_realtime_quote", "get_daily_history", "analyze_trend"],
        )
        text = format_text_report(m)
        assert "缺失期望工具: get_realtime_quote, get_daily_history, analyze_trend" in text
        assert "期望外工具: 无" in text
        assert "违规项: 无" in text
        assert "触碰 max_steps: 否" in text

    def test_violations_rendered(self):
        text = format_text_report(_metrics(violations=["trajectory reached allowed_max_steps (5)"]))
        assert "违规项: trajectory reached allowed_max_steps (5)" in text

    def test_deterministic(self):
        m = _metrics(redundant_calls=2, retries=1, max_steps_touched=True)
        assert format_text_report(m) == format_text_report(m)


# ---------------------------------------------------------------------------
# 7. Golden samples file (schema + registry membership)
# ---------------------------------------------------------------------------
def _repo_tool_names():
    """Authoritative tool names from the five tool modules (lazy import)."""
    from src.agent.tools.analysis_tools import ALL_ANALYSIS_TOOLS
    from src.agent.tools.backtest_tools import ALL_BACKTEST_TOOLS
    from src.agent.tools.data_tools import ALL_DATA_TOOLS
    from src.agent.tools.market_tools import ALL_MARKET_TOOLS
    from src.agent.tools.search_tools import ALL_SEARCH_TOOLS

    all_tools = ALL_DATA_TOOLS + ALL_ANALYSIS_TOOLS + ALL_SEARCH_TOOLS + ALL_MARKET_TOOLS + ALL_BACKTEST_TOOLS
    return {tool_def.name for tool_def in all_tools}


class TestGoldenSamplesFile:
    def test_samples_load_clean_with_registry_names(self):
        samples = load_golden_samples(known_tool_names=_repo_tool_names())
        assert len(samples) == 2
        assert [s.id for s in samples] == ["600519_technical", "000001_core_data_strict"]

    def test_each_sample_passes_structural_validation(self):
        for sample in load_golden_samples():
            assert validate_golden_sample(sample, _repo_tool_names()) == []

    def test_expected_tools_exist_in_repo_registry(self):
        known = _repo_tool_names()
        for sample in load_golden_samples():
            unknown = [t for t in sample.expected_tools if t not in known]
            assert unknown == [], f"sample '{sample.id}' expects unknown tools: {unknown}"

    def test_contains_strict_sample_without_optional_tools(self):
        samples = load_golden_samples()
        assert any(not s.allow_optional_tools for s in samples)

    def test_samples_have_required_text_fields(self):
        for sample in load_golden_samples():
            assert sample.id.strip()
            assert sample.task_description.strip()
            assert sample.stock_code.strip()
            assert sample.allowed_max_steps >= 1

    def test_empty_stock_code_is_the_valid_no_context_default(self):
        sample = GoldenSample(id="x", task_description="t", stock_code="", expected_tools=["get_realtime_quote"])
        assert validate_golden_sample(sample) == []

    def test_whitespace_only_stock_code_fails_validation(self):
        sample = GoldenSample(id="x", task_description="t", stock_code="   ", expected_tools=["get_realtime_quote"])
        issues = validate_golden_sample(sample)
        assert any("stock_code must not contain leading or trailing whitespace" in i for i in issues)

    def test_non_string_stock_code_fails_validation(self):
        sample = GoldenSample(id="x", task_description="t", stock_code=None, expected_tools=["get_realtime_quote"])
        issues = validate_golden_sample(sample)
        assert any("stock_code must be a string" in i for i in issues)

    def test_string_expected_tools_fails_validation(self):
        sample = GoldenSample(
            id="x",
            task_description="t",
            stock_code="600519",
            expected_tools="get_realtime_quote",
        )
        issues = validate_golden_sample(sample)
        assert any("must be a list" in i for i in issues)

    def test_non_bool_allow_optional_tools_fails_validation(self):
        sample = GoldenSample(
            id="x",
            task_description="t",
            stock_code="600519",
            expected_tools=["get_realtime_quote"],
            allow_optional_tools="false",
        )
        issues = validate_golden_sample(sample)
        assert any("allow_optional_tools must be a boolean" in i for i in issues)

    def test_mistyped_fields_fail_validation_not_crash(self):
        # Same defect class as the string expected_tools bug: hand-edited JSON
        # with mistyped fields must be rejected cleanly, never crash or pass.
        bad = GoldenSample(
            id=5,
            task_description=None,
            stock_code="600519",
            expected_tools=["get_realtime_quote"],
            allowed_max_steps="5",
            allow_optional_tools=1,
        )
        issues = validate_golden_sample(bad)
        assert any("id must be a non-empty string" in i for i in issues)
        assert any("task_description must be a non-empty string" in i for i in issues)
        assert any("allowed_max_steps must be an integer" in i for i in issues)
        assert any("allow_optional_tools must be a boolean" in i for i in issues)

    def test_non_iterable_expected_tools_with_known_names_does_not_crash(self):
        sample = GoldenSample(
            id="x",
            task_description="t",
            stock_code="600519",
            expected_tools=1,
        )
        issues = validate_golden_sample(sample, {"get_realtime_quote"})
        assert any("expected_tools must be a list" in i for i in issues)

    def test_registry_membership_with_one_shot_generator(self):
        # The helper accepts any Iterable[str]; a one-shot generator must be
        # materialized internally so membership checks never consume it.
        sample = GoldenSample(
            id="x",
            task_description="t",
            stock_code="600519",
            expected_tools=["b", "a"],
        )
        known = (name for name in ["a", "b"])
        assert validate_golden_sample(sample, known) == []

    def test_duplicate_expected_tools_fail_validation(self):
        sample = GoldenSample(
            id="x",
            task_description="t",
            stock_code="600519",
            expected_tools=["get_realtime_quote", "get_realtime_quote"],
        )
        issues = validate_golden_sample(sample)
        assert any("must not contain duplicate names" in i for i in issues)

    def test_loader_materializes_registry_once_for_multiple_samples(self):
        # A one-shot generator must survive loading the whole checked-in file:
        # the first sample must not exhaust it for the remaining samples.
        samples = load_golden_samples(known_tool_names=(name for name in _repo_tool_names()))
        assert len(samples) == 2


class TestLoadGoldenSamplesErrors:
    @staticmethod
    def _write_sample(tmp_path, payload, name="golden.json"):
        target = tmp_path / name
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return str(target)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_golden_samples(path="no/such/golden_samples.json")

    def test_non_list_root_raises(self, tmp_path):
        path = self._write_sample(tmp_path, {"id": "x"})
        with pytest.raises(ValueError, match="JSON list"):
            load_golden_samples(path=path)

    def test_malformed_json_raises(self, tmp_path):
        target = tmp_path / "golden.json"
        target.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            load_golden_samples(path=str(target))

    def test_duplicate_ids_raise(self, tmp_path):
        sample = {
            "id": "dup",
            "task_description": "t",
            "stock_code": "600519",
            "expected_tools": ["get_realtime_quote"],
        }
        path = self._write_sample(tmp_path, [sample, sample])
        with pytest.raises(ValueError, match="duplicate sample id: dup"):
            load_golden_samples(path=path)

    def test_unknown_expected_tool_flagged_when_names_given(self, tmp_path):
        sample = {
            "id": "x",
            "task_description": "t",
            "stock_code": "600519",
            "expected_tools": ["not_a_real_tool"],
        }
        path = self._write_sample(tmp_path, [sample])
        with pytest.raises(ValueError, match="unknown expected_tools: not_a_real_tool"):
            load_golden_samples(path=path, known_tool_names=_repo_tool_names())

    def test_unknown_expected_tool_allowed_without_names(self, tmp_path):
        sample = {
            "id": "x",
            "task_description": "t",
            "stock_code": "600519",
            "expected_tools": ["not_a_real_tool"],
        }
        path = self._write_sample(tmp_path, [sample])
        assert [s.id for s in load_golden_samples(path=path)] == ["x"]

    def test_extra_json_keys_ignored(self, tmp_path):
        sample = {
            "id": "x",
            "task_description": "t",
            "stock_code": "600519",
            "expected_tools": ["get_realtime_quote"],
            "notes": "forward-looking metadata",
        }
        path = self._write_sample(tmp_path, [sample])
        assert load_golden_samples(path=path)[0].id == "x"

    def test_invalid_max_steps_flagged(self, tmp_path):
        sample = {
            "id": "x",
            "task_description": "t",
            "stock_code": "600519",
            "expected_tools": ["get_realtime_quote"],
            "allowed_max_steps": 0,
        }
        path = self._write_sample(tmp_path, [sample])
        with pytest.raises(ValueError, match="allowed_max_steps must be >= 1"):
            load_golden_samples(path=path)

    def test_whitespace_only_stock_code_raises(self, tmp_path):
        sample = {
            "id": "x",
            "task_description": "t",
            "stock_code": "   ",
            "expected_tools": ["get_realtime_quote"],
        }
        path = self._write_sample(tmp_path, [sample])
        with pytest.raises(ValueError, match="stock_code must not contain leading or trailing whitespace"):
            load_golden_samples(path=path)

    def test_string_expected_tools_raises(self, tmp_path):
        sample = {
            "id": "x",
            "task_description": "t",
            "stock_code": "600519",
            "expected_tools": "get_realtime_quote",
        }
        path = self._write_sample(tmp_path, [sample])
        with pytest.raises(ValueError, match="expected_tools must be a list"):
            load_golden_samples(path=path)

    def test_non_list_expected_tools_with_known_names_raises_valueerror(self, tmp_path):
        # Regression for OR-COR-4e0e3cf1: the registry membership check must
        # not iterate a rejected non-list value and leak a TypeError.
        sample = {
            "id": "x",
            "task_description": "t",
            "stock_code": "600519",
            "expected_tools": 1,
        }
        path = self._write_sample(tmp_path, [sample])
        with pytest.raises(ValueError, match="expected_tools must be a list"):
            load_golden_samples(path=path, known_tool_names={"get_realtime_quote"})

    def test_unhashable_id_raises_valueerror(self, tmp_path):
        # Structural validation must run before duplicate detection: an
        # unhashable id would otherwise crash the seen_ids membership check
        # with a TypeError instead of the documented ValueError.
        sample = {
            "id": ["x"],
            "task_description": "t",
            "stock_code": "600519",
            "expected_tools": ["get_realtime_quote"],
        }
        path = self._write_sample(tmp_path, [sample])
        with pytest.raises(ValueError, match="id must be a non-empty string"):
            load_golden_samples(path=path)

    def test_non_bool_allow_optional_tools_raises(self, tmp_path):
        sample = {
            "id": "x",
            "task_description": "t",
            "stock_code": "600519",
            "expected_tools": ["get_realtime_quote"],
            "allow_optional_tools": "false",
        }
        path = self._write_sample(tmp_path, [sample])
        with pytest.raises(ValueError, match="allow_optional_tools must be a boolean"):
            load_golden_samples(path=path)

    def test_duplicate_expected_tools_raise(self, tmp_path):
        sample = {
            "id": "x",
            "task_description": "t",
            "stock_code": "600519",
            "expected_tools": ["get_realtime_quote", "get_realtime_quote"],
        }
        path = self._write_sample(tmp_path, [sample])
        with pytest.raises(ValueError, match="expected_tools must not contain duplicate names"):
            load_golden_samples(path=path)
