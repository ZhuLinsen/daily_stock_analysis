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


def _codex_entry(tool="get_realtime_quote", summary="600519", step=1, success=True, **extra):
    """Build a Codex App Server-shaped entry (``arguments_summary`` only)."""
    entry = {
        "step": step,
        "tool": tool,
        "arguments_summary": summary,
        "success": success,
    }
    entry.update(extra)
    return entry


def _golden(**overrides):
    values = dict(
        id="600519_technical",
        task_description="分析贵州茅台近期技术面走势",
        stock_code="600519",
        expected_tools=["get_realtime_quote", "get_daily_history", "analyze_trend"],
        skills=[],
        allowed_max_steps=8,
        allow_optional_tools=True,
        expected_outcomes=[],
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

    def test_stock_code_aliases_share_a_key(self):
        # Mirroring _build_tool_cache_key: the stock_code field is
        # canonicalized before serialization, so runtime-equivalent alias
        # forms share one call identity.
        assert _args_key({"stock_code": "SH600519"}) == _args_key({"stock_code": "600519"})
        assert _args_key({"stock_code": "600519.SH"}) == _args_key({"stock_code": "sh600519"})
        assert _args_key({"stock_code": "HK00700"}) == _args_key({"stock_code": "700.HK"})

    def test_other_arguments_stay_raw_in_the_key(self):
        assert _args_key({"stock_code": "SH600519", "period": "daily"}) != _args_key(
            {"stock_code": "600519", "period": "weekly"}
        )

    def test_numeric_stock_code_stays_distinct_from_string(self):
        # The production normalizer returns non-string values unchanged, so a
        # JSON number and a string must remain two different call identities.
        assert _args_key({"stock_code": 600519}) != _args_key({"stock_code": "600519"})
        assert _args_key({"stock_code": 600519}) == json.dumps({"stock_code": 600519}, sort_keys=True)


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

    def test_malformed_expected_outcomes_elements_are_reported(self):
        # Review counter-example: expected_outcomes=[1, ''] must not
        # silently drop the requirement — the malformed elements are
        # reported instead of vanishing from the required set.
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": "600519"})]
        for malformed in ([1, ""], [1], [""]):
            m = compute_trajectory_metrics(log, _golden(expected_outcomes=malformed))
            assert "expected_outcomes must contain only non-empty strings" in m.violations
            assert "expected outcomes not observed" not in " ".join(m.violations)

    def test_whitespace_only_outcome_gets_structural_violation(self):
        # Review counter-example: '   ' must be reported as a malformed
        # element, not misrouted into the unknown-tag violation type.
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": "600519"})]
        m = compute_trajectory_metrics(log, _golden(expected_outcomes=["   "]))
        assert "expected_outcomes must contain only non-empty strings" in m.violations
        assert not any("unknown expected_outcomes" in v for v in m.violations)

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
            (dict(expected_outcomes=["   "]), "expected_outcomes must contain only non-empty strings"),
            (dict(expected_outcomes=[1, ""]), "expected_outcomes must contain only non-empty strings"),
            (dict(expected_outcomes="guarded"), "expected_outcomes must be a list of outcome tags"),
            (dict(allowed_max_steps=0), "allowed_max_steps must be >= 1"),
            (dict(allowed_max_steps=-3), "allowed_max_steps must be >= 1"),
            (dict(allow_optional_tools="false"), "allow_optional_tools must be a boolean"),
            (dict(id=[]), "id must be a non-empty string"),
            (dict(task_description=None), "task_description must be a non-empty string"),
            (dict(skills="trading"), "skills must be a list of strings"),
            (dict(skills=["", "trading"]), "skills must contain only non-empty strings"),
            (
                dict(expected_guarded_stock="600036"),
                "expected_guarded_stock requires guarded_retry in expected_outcomes",
            ),
            (
                dict(
                    stock_code="600036",
                    expected_tools=["get_stock_info"],
                    expected_outcomes=["guarded_retry"],
                    expected_guarded_stock="SH600036",
                ),
                "expected_guarded_stock must name a different stock than stock_code after canonicalization (it names the out-of-scope call)",
            ),
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
        # skills and any future validator check apply to direct scoring
        # automatically).  A thoroughly malformed sample must yield every
        # validator issue in compute violations, with no duplicates from the
        # inline scoring checks.
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": "600519"})]
        golden = GoldenSample(
            id=[],
            task_description=None,
            stock_code=None,
            expected_tools=["", "   "],
            skills=["", "trading"],
            allowed_max_steps=0,
            allow_optional_tools="false",
            expected_outcomes=[1],
        )
        validator_issues = validate_golden_sample(golden)
        assert validator_issues, "the sample is thoroughly malformed"
        m = compute_trajectory_metrics(log, golden)
        for issue in validator_issues:
            assert any(issue in v for v in m.violations), (issue, m.violations)
            assert m.violations.count(issue) == 1, (issue, m.violations)

    def test_unpaired_guarded_stock_reported_and_exemption_disabled(self):
        # Review counter-example: expected_guarded_stock without guarded_retry
        # is a malformed sample; it must be reported and must not erase the
        # wrong-stock violation for the blocked out-of-scope probe.
        golden = GoldenSample(
            id="x",
            task_description="t",
            stock_code="600036",
            expected_tools=["get_stock_info"],
            skills=[],
            expected_outcomes=[],
            expected_guarded_stock="600519",
        )
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(
                tool="get_stock_info",
                arguments={"stock_code": "600519"},
                step=2,
                success=False,
                guarded=True,
            ),
        ]
        m = compute_trajectory_metrics(log, golden)
        assert m.expected_hit_rate == 1.0
        assert "expected_guarded_stock requires guarded_retry in expected_outcomes" in m.violations
        assert any("different stock than 600036: get_stock_info" in v for v in m.violations)

    def test_same_stock_pinned_guard_reported_in_direct_score(self):
        # A pinned stock that canonicalizes back to golden.stock_code is a
        # dead configuration the validator rejects; the direct-score path
        # reports it too (canonicalized comparison, so 'SH600036' counts).
        golden = _golden(
            stock_code="600036",
            expected_tools=["get_stock_info"],
            expected_outcomes=["guarded_retry"],
            expected_guarded_stock="SH600036",
        )
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(
                tool="get_stock_info",
                arguments={"stock_code": "600519"},
                step=2,
                success=False,
                guarded=True,
            ),
        ]
        m = compute_trajectory_metrics(log, golden)
        assert any("expected_guarded_stock must name a different stock than stock_code" in v for v in m.violations)
        assert any("different stock than 600036: get_stock_info" in v for v in m.violations)


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

    def test_guarded_entry_counts_as_failed(self):
        entry = _entry(
            success=False,
            guarded=True,
            expected_stock_code="600519",
            requested_stock_code="000001",
            allowed_stock_codes=["600519"],
        )
        m = compute_trajectory_metrics([entry], _golden())
        assert m.failed_calls == 1


# ---------------------------------------------------------------------------
# 3b. Expected outcomes (guarded / cached / retry contract)
# ---------------------------------------------------------------------------
class TestExpectedOutcomes:
    @staticmethod
    def _guarded_sample(**overrides):
        values = dict(
            id="600036_guarded_retry",
            task_description="guard / cached retry boundary",
            stock_code="600036",
            expected_tools=["get_stock_info", "get_daily_history"],
            skills=[],
            allowed_max_steps=10,
            allow_optional_tools=True,
            expected_outcomes=["guarded_retry"],
            expected_guarded_stock="600519",
        )
        values.update(overrides)
        return GoldenSample(**values)

    @staticmethod
    def _faithful_log():
        """In-scope calls succeed; the out-of-scope call is guarded and its
        same-args retry hits the non-retriable cache."""
        return [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=3,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=4,
                success=False,
                cached=True,
            ),
        ]

    def test_faithful_guard_retry_log_satisfies_outcomes(self):
        m = compute_trajectory_metrics(self._faithful_log(), self._guarded_sample())
        assert "expected outcomes not observed" not in m.violations
        assert m.retries == 1
        assert m.cached_calls == 1
        assert m.failed_calls == 2

    def test_skipping_the_out_of_scope_call_violates_the_contract(self):
        # Review counter-example: hitting every expected tool without ever
        # attempting the out-of-scope call must not score clean.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert m.expected_hit_rate == 1.0
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_guarded_without_follow_up_reports_missing_guarded_retry(self):
        log = [
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=1,
                success=False,
                guarded=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_guarded_retry_of_a_different_stock_does_not_satisfy(self):
        # Review counter-example: two guarded calls for 000001 form a
        # repeated key, which the bound outcome used to accept even though
        # the task requires attempting the pinned out-of-scope stock 600519.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "000001"},
                step=3,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "000001"},
                step=4,
                success=False,
                guarded=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert m.expected_hit_rate == 1.0
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_alias_guard_and_retry_share_one_call_identity(self):
        # Review counter-example: the runtime cache key normalizes the
        # stock_code argument, so a guarded SH600519 call retried as 600519
        # is the same (tool, args-key) pair and must count as a retry —
        # previously the raw-argument key split it into two fresh calls and
        # reported guarded_retry as missing.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "SH600519"},
                step=3,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=4,
                success=False,
                cached=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "expected outcomes not observed" not in m.violations
        assert m.retries == 1
        assert m.redundant_calls == 1

    def test_alias_retry_counts_toward_retry_and_redundancy(self):
        # A failed 600519.SH call retried as 600519 is one identity: the
        # second occurrence is both redundant and a retry.
        log = [
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519.SH"},
                step=1,
                success=False,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=2,
                success=True,
            ),
        ]
        m = compute_trajectory_metrics(log, _golden())
        assert m.retries == 1
        assert m.redundant_calls == 1

    def test_identity_normalization_only_touches_the_stock_code_field(self):
        # Mirroring _build_tool_cache_key: other arguments stay raw, so a
        # different period still splits the identity even when the stock
        # codes are aliases of each other.
        log = [
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "SH600519", "period": "daily"},
                step=1,
                success=False,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519", "period": "weekly"},
                step=2,
                success=True,
            ),
        ]
        m = compute_trajectory_metrics(log, _golden())
        assert m.retries == 0
        assert m.redundant_calls == 0

    def test_number_and_string_stock_codes_do_not_merge_identity(self):
        # The runtime cache key preserves the JSON number type, so a failed
        # number call followed by a string call is not "the same call" — no
        # retry, no redundancy.
        log = [
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": 600519},
                step=1,
                success=False,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=2,
                success=True,
            ),
        ]
        m = compute_trajectory_metrics(log, _golden())
        assert m.retries == 0
        assert m.redundant_calls == 0

    def test_number_then_string_guard_retry_stays_distinct(self):
        # A guarded number call followed by a cached string call is not the
        # same (tool, args-key) in the runtime cache, so guarded_retry must
        # not be observed from that pair.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": 600519},
                step=3,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=4,
                success=False,
                cached=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "expected outcomes not observed: guarded_retry" in m.violations
        assert m.retries == 0
        assert m.redundant_calls == 0

    def test_clean_success_before_guard_still_escapes(self):
        # Review counter-example: the out-of-scope key succeeded before ever
        # being guarded — the call provably gets through the scope guard, so
        # a later guarded occurrence plus a blocked repeat must not satisfy
        # the golden contract.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=3,
                success=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=4,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=5,
                success=False,
                cached=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "expected outcomes not observed: guarded_retry" in m.violations
        assert m.retries == 1
        assert m.cached_calls == 1

    def test_success_on_a_different_key_does_not_escape(self):
        # Escape tracking is per (tool, args-key): a clean success of an
        # unrelated out-of-scope key leaves the pinned 600519 guard/retry
        # sequence intact.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "000001"},
                step=3,
                success=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=4,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=5,
                success=False,
                cached=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "expected outcomes not observed" not in m.violations

    def test_expected_tool_blocked_probe_of_pinned_stock_is_exempt(self):
        # Review counter-example: the sample pins only the out-of-scope
        # stock, not a tool — the deliberate 600519 probe may use any
        # expected tool, and while it stays blocked (guarded / cached) it
        # must not surface as a wrong-stock violation.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_stock_info",
                arguments={"stock_code": "600519"},
                step=3,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_stock_info",
                arguments={"stock_code": "600519"},
                step=4,
                success=False,
                cached=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert m.expected_hit_rate == 1.0
        assert m.retries == 1
        assert m.cached_calls == 1
        assert not any("different stock" in v for v in m.violations)
        assert m.violations == []

    def test_alias_pinned_stock_probe_is_exempt(self):
        # The exemption compares canonicalized identities like every other
        # stock comparison: an SH600519 probe of the 600519-pinned sample is
        # the required out-of-scope call, not a wrong-stock call.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_stock_info",
                arguments={"stock_code": "SH600519"},
                step=3,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_stock_info",
                arguments={"stock_code": "600519"},
                step=4,
                success=False,
                cached=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert m.expected_hit_rate == 1.0
        assert not any("different stock" in v for v in m.violations)
        assert m.violations == []

    def test_clean_success_on_pinned_stock_is_still_wrong_stock(self):
        # The exemption covers blocked probes only: an expected-tool call
        # that cleanly succeeds on the pinned stock is still a wrong-stock
        # call, and with no guarded occurrence at all the sample's
        # guarded_retry stays unobserved.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_stock_info",
                arguments={"stock_code": "600519"},
                step=3,
                success=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert m.expected_hit_rate == 1.0
        assert any("different stock than 600036: get_stock_info" in v for v in m.violations)
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_blocked_probe_of_another_stock_is_still_wrong_stock(self):
        # Only the pinned stock is exempt: an expected-tool probe of a third
        # stock stays a wrong-stock call even while guarded.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_stock_info",
                arguments={"stock_code": "000001"},
                step=3,
                success=False,
                guarded=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert any("different stock than 600036: get_stock_info" in v for v in m.violations)

    def test_without_pinned_stock_blocked_probes_stay_wrong_stock(self):
        # No expected_guarded_stock means no exemption: a blocked call to
        # another stock is wrong-stock exactly like before.
        log = [
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "000001"},
                step=1,
                success=False,
                guarded=True,
            ),
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.expected_hit_rate == 0.0
        assert any("different stock than 600519: get_realtime_quote" in v for v in m.violations)

    def test_malformed_guarded_probe_does_not_satisfy_guarded_retry(self):
        # Review counter-example: a guarded call whose stock evidence is
        # explicitly malformed (stock_code=None, empty requested_stock_code)
        # never proves the required 600519 probe, so it must not seed the
        # pinned guard outcome — not even when a cached repeat follows.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": None},
                step=3,
                success=False,
                guarded=True,
                requested_stock_code="",
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": None},
                step=4,
                success=False,
                cached=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_guarded_probe_without_stock_evidence_does_not_satisfy(self):
        # Review counter-example: a blocked call with no stock evidence at
        # all (arguments={}) cannot prove the pinned 600519 probe, so the
        # name-only tolerance must not seed a stock-pinned guarded_retry.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={},
                step=3,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={},
                step=4,
                success=False,
                cached=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert m.expected_hit_rate == 1.0
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_guarded_probe_without_any_arguments_does_not_satisfy(self):
        # Minimal entries with no arguments payload at all must not seed the
        # pinned outcome through the trailing name-only tolerance either.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            {"step": 3, "tool": "get_realtime_quote", "success": False, "guarded": True},
            {"step": 4, "tool": "get_realtime_quote", "success": False, "cached": True},
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_guarded_probe_without_stock_field_does_not_satisfy(self):
        # A structured payload without a stock_code field ({"days": 30})
        # carries no stock evidence either and must not satisfy the pin.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={"days": 30},
                step=3,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"days": 30},
                step=4,
                success=False,
                cached=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_injected_normalizer_drives_call_identity(self):
        # Call identity follows the injected normalizer, not the mirror: a
        # constant normalizer merges every stock code into one identity.
        log = [
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=1,
                success=False,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "000001"},
                step=2,
                success=True,
            ),
        ]
        m = compute_trajectory_metrics(log, _golden(), stock_code_normalizer=lambda v: "SAME")
        assert m.retries == 1
        assert m.redundant_calls == 1

    def test_clean_success_after_guard_is_an_escape(self):
        # Review counter-example: the guarded call is retried and the retry
        # succeeds without cache — the guard was bypassed, so guarded_retry
        # must not be observed.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=3,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=4,
                success=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert m.expected_hit_rate == 1.0
        assert m.retries == 1
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_blocked_retry_variants_stay_satisfied(self):
        # The retry may fail again or hit the non-retriable cache — both are
        # blocked outcomes and satisfy the sample.
        for extra in ({"success": False}, {"cached": True, "success": False}):
            log = [
                _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
                _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
                _entry(
                    tool="get_realtime_quote",
                    arguments={"stock_code": "600519"},
                    step=3,
                    success=False,
                    guarded=True,
                ),
                _entry(
                    tool="get_realtime_quote",
                    arguments={"stock_code": "600519"},
                    step=4,
                    **extra,
                ),
            ]
            m = compute_trajectory_metrics(log, self._guarded_sample())
            assert "expected outcomes not observed" not in m.violations, extra

    def test_escape_after_a_blocked_retry_still_violates(self):
        # guard -> blocked retry -> clean success: the guard boundary was
        # breached eventually, so the outcome must not be observed.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=3,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=4,
                success=False,
            ),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=5,
                success=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_unrelated_retry_does_not_satisfy_guarded_retry(self):
        # Review counter-example: a guard on the out-of-scope quote plus a
        # retry of an unrelated news call must not satisfy the bound outcome.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=3,
                success=False,
                guarded=True,
            ),
            _entry(
                tool="search_stock_news",
                arguments={"query": "招商银行"},
                step=4,
                success=False,
            ),
            _entry(
                tool="search_stock_news",
                arguments={"query": "招商银行"},
                step=5,
                success=True,
            ),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert m.retries == 1
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_unknown_outcome_tag_flagged_once(self):
        m = compute_trajectory_metrics(
            self._faithful_log(),
            self._guarded_sample(expected_outcomes=["guarded", "warp"]),
        )
        assert "unknown expected_outcomes: warp" in m.violations
        assert not any("not observed" in v for v in m.violations)

    def test_non_list_expected_outcomes_surfaces_violation(self):
        m = compute_trajectory_metrics(
            self._faithful_log(),
            self._guarded_sample(expected_outcomes="guarded"),
        )
        assert "expected_outcomes must be a list of outcome tags" in m.violations

    def test_duplicate_outcome_tags_normalized_with_violation(self):
        m = compute_trajectory_metrics(
            self._faithful_log(),
            self._guarded_sample(expected_outcomes=["guarded_retry", "guarded_retry"]),
        )
        assert "expected_outcomes must not contain duplicate tags" in m.violations
        assert "expected outcomes not observed" not in m.violations

    def test_successful_guarded_entry_escapes_and_reports_wrong_stock(self):
        # Review counter-example (success is authoritative): a success=True
        # entry carrying guarded=True did NOT stay blocked — it must keep its
        # wrong-stock violation on the pinned stock and must not satisfy
        # guarded_retry, even when the same-args retry is a blocked cache hit.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(tool="get_stock_info", arguments={"stock_code": "600519"}, step=3, guarded=True),
            _entry(tool="get_stock_info", arguments={"stock_code": "600519"}, step=4, success=False, cached=True),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "expected tools called for a different stock than 600036: get_stock_info" in m.violations
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_successful_cached_retry_is_an_escape(self):
        # A cache-hit retry marked success=True executed cleanly, so the pair
        # escaped: guarded_retry must not be observed.
        log = [
            _entry(
                tool="get_stock_info",
                arguments={"stock_code": "600519"},
                step=1,
                success=False,
                guarded=True,
            ),
            _entry(tool="get_stock_info", arguments={"stock_code": "600519"}, step=2, cached=True),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_successful_guarded_entry_does_not_count_as_interception(self):
        # success is authoritative for the observed-outcome counters too: a
        # successful guarded entry neither counts as a guard interception nor
        # observes the guarded outcome.
        golden = _golden(expected_outcomes=["guarded"])
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": "600519"}, guarded=True)]
        m = compute_trajectory_metrics(log, golden)
        assert "expected outcomes not observed: guarded" in m.violations

    def test_successful_cached_entry_does_not_count_as_cache_reuse(self):
        # Same authority for the cached marker: a successful cached entry
        # neither counts as cache reuse nor observes the cached outcome.
        golden = _golden(expected_outcomes=["cached"])
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": "600519"}, cached=True)]
        m = compute_trajectory_metrics(log, golden)
        assert m.cached_calls == 0
        assert "expected outcomes not observed: cached" in m.violations

    def test_optional_tool_clean_success_on_guarded_stock_reports_escape(self):
        # Review counter-example: the runtime guard intercepts every
        # stock-scoped tool alike, so an OPTIONAL tool that cleanly reaches
        # the pinned out-of-scope stock is a scope escape too — it must be
        # reported and must break guarded_retry even though the guarded pair
        # itself stayed blocked.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(tool="get_stock_info", arguments={"stock_code": "600519"}, step=3, success=False, guarded=True),
            _entry(tool="get_stock_info", arguments={"stock_code": "600519"}, step=4, success=False, cached=True),
            _entry(tool="get_realtime_quote", arguments={"stock_code": "600519"}, step=5),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "optional tools escaped the guarded stock 600519: get_realtime_quote" in m.violations
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_integral_float_clean_success_on_guarded_stock_reports_escape(self):
        # Review counter-example: get_realtime_quote(stock_code=600519.0,
        # success=True) is a clean success on the pinned stock even though
        # the argument is a JSON float — the escape and the guarded_retry
        # break must both be reported, not silently missed as invalid
        # evidence.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(tool="get_stock_info", arguments={"stock_code": "600519"}, step=3, success=False, guarded=True),
            _entry(tool="get_stock_info", arguments={"stock_code": "600519"}, step=4, success=False, cached=True),
            _entry(tool="get_realtime_quote", arguments={"stock_code": 600519.0}, step=5),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert "optional tools escaped the guarded stock 600519: get_realtime_quote" in m.violations
        assert "expected outcomes not observed: guarded_retry" in m.violations

    def test_blocked_optional_probe_on_guarded_stock_stays_clean(self):
        # The deliberate-probe exemption spans tools: a blocked optional
        # probe of the pinned stock is as legitimate as an expected one and
        # must not be reported as an escape.
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(tool="get_stock_info", arguments={"stock_code": "600519"}, step=3, success=False, guarded=True),
            _entry(tool="get_stock_info", arguments={"stock_code": "600519"}, step=4, success=False, cached=True),
            _entry(tool="get_realtime_quote", arguments={"stock_code": "600519"}, step=5, success=False, cached=True),
        ]
        m = compute_trajectory_metrics(log, self._guarded_sample())
        assert not any("escaped the guarded stock" in v for v in m.violations)
        assert "expected outcomes not observed" not in m.violations

    def test_optional_escape_and_tool_disallowance_are_independent(self):
        # A disallowed optional tool that also escapes the guarded stock
        # violates two contracts at once; both must be reported.
        golden = self._guarded_sample(allow_optional_tools=False)
        log = [
            _entry(tool="get_stock_info", arguments={"stock_code": "600036"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600036"}, step=2),
            _entry(tool="get_realtime_quote", arguments={"stock_code": "600519"}, step=3),
        ]
        m = compute_trajectory_metrics(log, golden)
        assert "optional tools used but not allowed: get_realtime_quote" in m.violations
        assert "optional tools escaped the guarded stock 600519: get_realtime_quote" in m.violations


# ---------------------------------------------------------------------------
# 2b. Stock-scoped hit semantics (golden.stock_code)
# ---------------------------------------------------------------------------
class TestStockCodeScoping:
    @staticmethod
    def _wrong_stock_log():
        return [
            _entry(tool="get_realtime_quote", arguments={"stock_code": "000001"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "000001"}, step=2),
            _entry(tool="analyze_trend", arguments={"stock_code": "000001"}, step=3),
        ]

    def test_expected_tools_called_for_wrong_stock_score_zero(self):
        # Review counter-example: tool names all correct but every call
        # targets 000001, so the 600519_technical sample must not score a
        # full hit.
        m = compute_trajectory_metrics(self._wrong_stock_log(), _golden())
        assert m.expected_hit_rate == 0.0
        assert m.missing_expected == [
            "get_realtime_quote",
            "get_daily_history",
            "analyze_trend",
        ]
        assert any("called for a different stock than 600519" in v for v in m.violations)

    def test_mixed_stock_calls_score_partial(self):
        log = [
            _entry(tool="get_realtime_quote", arguments={"stock_code": "600519"}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "000001"}, step=2),
            _entry(tool="analyze_trend", arguments={"stock_code": "600519"}, step=3),
        ]
        m = compute_trajectory_metrics(log, _golden())
        assert m.expected_hit_rate == pytest.approx(2 / 3)
        assert m.missing_expected == ["get_daily_history"]
        assert any("different stock than 600519: get_daily_history" in v for v in m.violations)

    def test_integral_float_stock_argument_counts_as_hit(self):
        # Review counter-example: the runner records arguments verbatim, so a
        # JSON-parsed code can arrive as 600519.0; the guard chain coerces
        # integral floats to int before normalization
        # (_normalize_guard_stock_code), so the metrics layer must read it
        # as 600519 instead of rejecting the evidence.
        golden = _golden(expected_tools=["get_realtime_quote"])
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": 600519.0}, step=1)]
        m = compute_trajectory_metrics(log, golden)
        assert m.expected_hit_rate == 1.0
        assert m.missing_expected == []
        assert m.violations == []

    def test_integral_float_wrong_stock_is_reported(self):
        # The coercion must reach the mismatch side too: 600000.0 reads as
        # 600000, a different code, so analyze_trend scores no hit and
        # reports a wrong-stock violation even though its argument is a
        # float.
        log = [
            _entry(tool="get_realtime_quote", arguments={"stock_code": 600519.0}, step=1),
            _entry(tool="get_daily_history", arguments={"stock_code": "600519"}, step=2),
            _entry(tool="analyze_trend", arguments={"stock_code": 600000.0}, step=3),
        ]
        m = compute_trajectory_metrics(log, _golden())
        assert m.expected_hit_rate == pytest.approx(2 / 3)
        assert m.missing_expected == ["analyze_trend"]
        assert any("different stock than 600519: analyze_trend" in v for v in m.violations)

    def test_non_integral_float_stock_is_a_distinct_code(self):
        # Guard-chain parity for the non-integral branch: the guard compares
        # str(600519.5) = "600519.5", which never canonicalizes to 600519 —
        # it is evidence of a different code, so no hit and a wrong-stock
        # violation.
        golden = _golden(expected_tools=["get_realtime_quote"])
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": 600519.5}, step=1)]
        m = compute_trajectory_metrics(log, golden)
        assert m.expected_hit_rate == 0.0
        assert m.missing_expected == ["get_realtime_quote"]
        assert any("different stock than 600519: get_realtime_quote" in v for v in m.violations)

    def test_codex_summary_matching_the_stock_counts(self):
        log = [
            {
                "step": 1,
                "tool": "get_realtime_quote",
                "arguments_summary": "600519",
                "success": True,
            },
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.expected_hit_rate == 1.0

    def test_codex_summary_without_the_stock_does_not_count(self):
        log = [
            {
                "step": 1,
                "tool": "get_realtime_quote",
                "arguments_summary": "000001",
                "success": True,
            },
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.expected_hit_rate == 0.0
        assert m.missing_expected == ["get_realtime_quote"]

    def test_codex_summary_alias_resolves_to_canonical_golden(self):
        # Review counter-example: the backend keeps the original spelling in
        # arguments_summary, so the structured value must be recovered and
        # canonicalized — hk700 matches an HK00700 golden, aapl matches AAPL.
        for summary_code, golden_code in (("hk700", "HK00700"), ("aapl", "AAPL")):
            log = [
                {
                    "step": 1,
                    "tool": "get_realtime_quote",
                    "arguments_summary": json.dumps({"stock_code": summary_code}),
                    "success": True,
                },
            ]
            m = compute_trajectory_metrics(log, _golden(stock_code=golden_code, expected_tools=["get_realtime_quote"]))
            assert m.expected_hit_rate == 1.0, (summary_code, golden_code)
            assert m.missing_expected == []

    def test_codex_summary_structured_different_stock_reports_wrong_stock(self):
        # A well-formed summary recovers to concrete evidence, so it must be
        # treated like a runner argument: a different code is a wrong-stock
        # call, not silent tolerance.
        log = [
            {
                "step": 1,
                "tool": "get_realtime_quote",
                "arguments_summary": json.dumps({"stock_code": "000001"}),
                "success": True,
            },
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.expected_hit_rate == 0.0
        assert any("different stock than 600519: get_realtime_quote" in v for v in m.violations)

    def test_unparsable_summary_falls_back_to_substring_no_evidence(self):
        # Truncated previews cannot recover a structured value: they fall
        # back to the substring scan for matching and stay "no evidence" for
        # wrong-stock reporting.
        log = [
            {
                "step": 1,
                "tool": "get_realtime_quote",
                "arguments_summary": '{"stock_code": "6005...<truncated 12 chars>',
                "success": True,
            },
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.expected_hit_rate == 0.0
        assert not any("different stock" in v for v in m.violations)

    def test_stock_code_field_matched_exactly_not_substring(self):
        # Review counter-example: {"stock_code": "1600519"} contains the
        # golden code as a substring but must not satisfy the 600519 golden.
        m = compute_trajectory_metrics(
            [
                _entry(
                    tool="get_realtime_quote",
                    arguments={"stock_code": "1600519"},
                    step=1,
                )
            ],
            _golden(expected_tools=["get_realtime_quote"]),
        )
        assert m.expected_hit_rate == 0.0
        assert m.missing_expected == ["get_realtime_quote"]
        assert any("different stock than 600519: get_realtime_quote" in v for v in m.violations)

    def test_integer_stock_code_argument_counts_after_normalization(self):
        m = compute_trajectory_metrics(
            [_entry(tool="get_realtime_quote", arguments={"stock_code": 600519}, step=1)],
            _golden(expected_tools=["get_realtime_quote"]),
        )
        assert m.expected_hit_rate == 1.0
        assert m.missing_expected == []

    def test_equivalent_stock_code_forms_count_as_hit(self):
        # Review counter-example (inverse): production accepts SH600519 /
        # 600519.SH / lowercase etc. as the same stock, so the metrics layer
        # must too — via runtime-equivalent canonicalization, not raw
        # equality.
        for form in ("SH600519", "sh600519", "600519.SH", "SS600519", "SH.600519", " 600519 "):
            m = compute_trajectory_metrics(
                [_entry(tool="get_realtime_quote", arguments={"stock_code": form}, step=1)],
                _golden(expected_tools=["get_realtime_quote"]),
            )
            assert m.expected_hit_rate == 1.0, form
            assert m.violations == [], form

    def test_hk_variant_forms_share_one_identity(self):
        golden = _golden(stock_code="HK00700", expected_tools=["get_realtime_quote"])
        for form in ("HK00700", "hk700", "700.HK", "00700"):
            m = compute_trajectory_metrics(
                [_entry(tool="get_realtime_quote", arguments={"stock_code": form}, step=1)],
                golden,
            )
            assert m.expected_hit_rate == 1.0, form
            assert m.violations == [], form

    def test_sz_prefix_and_suffix_forms_match_their_golden(self):
        golden = _golden(stock_code="000001", expected_tools=["get_realtime_quote"])
        for form in ("SZ000001", "000001.SZ", "SZ.000001", "sz000001"):
            m = compute_trajectory_metrics(
                [_entry(tool="get_realtime_quote", arguments={"stock_code": form}, step=1)],
                golden,
            )
            assert m.expected_hit_rate == 1.0, form
            assert m.violations == [], form

    def test_each_wrong_stock_call_of_an_expected_tool_is_reported(self):
        # Review counter-example: the correct call used to set
        # stock_hit[tool], which legitimized every other call of the same
        # tool — the mismatching call must now surface in a violation.
        log = [
            _entry(tool="get_realtime_quote", arguments={"stock_code": "600519"}, step=1),
            _entry(tool="get_realtime_quote", arguments={"stock_code": "000001"}, step=2),
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.expected_hit_rate == 1.0
        assert any("different stock than 600519: get_realtime_quote" in v for v in m.violations)

    def test_arguments_without_stock_field_keep_name_only_tolerance(self):
        # No stock evidence at all: the entry still counts (documented
        # tolerance) and never produces a wrong-stock violation.
        m = compute_trajectory_metrics(
            [_entry(tool="get_realtime_quote", arguments={"days": 60}, step=1)],
            _golden(expected_tools=["get_realtime_quote"]),
        )
        assert m.expected_hit_rate == 1.0
        assert m.violations == []

    def test_requested_stock_code_guard_metadata_counts(self):
        entry = {
            "step": 1,
            "tool": "get_realtime_quote",
            "success": False,
            "guarded": True,
            "requested_stock_code": "600519",
            "expected_stock_code": "600519",
        }
        m = compute_trajectory_metrics([entry], _golden(expected_tools=["get_realtime_quote"]))
        assert m.expected_hit_rate == 1.0

    def test_explicit_malformed_stock_evidence_does_not_hit(self):
        # Review counter-example: an explicitly present but invalid
        # stock_code (null / boolean / non-scalar) proves nothing about the
        # call's target, so it must not earn name-only hit credit — the
        # tolerance is reserved for entries with no stock evidence at all.
        for bad in (None, False, [], {}):
            m = compute_trajectory_metrics(
                [_entry(tool="get_realtime_quote", arguments={"stock_code": bad}, step=1)],
                _golden(expected_tools=["get_realtime_quote"]),
            )
            assert m.expected_hit_rate == 0.0, bad
            assert m.missing_expected == ["get_realtime_quote"], bad
            assert not any("different stock" in v for v in m.violations), bad

    def test_malformed_requested_stock_code_does_not_hit(self):
        # Guard metadata is authoritative: a present but invalid (or empty)
        # requested_stock_code is a non-match, not name-only tolerance.
        for bad in (None, "", [], True):
            entry = {
                "step": 1,
                "tool": "get_realtime_quote",
                "success": False,
                "guarded": True,
                "requested_stock_code": bad,
            }
            m = compute_trajectory_metrics([entry], _golden(expected_tools=["get_realtime_quote"]))
            assert m.expected_hit_rate == 0.0, bad
            assert m.missing_expected == ["get_realtime_quote"], bad

    def test_codex_summary_malformed_stock_evidence_does_not_hit(self):
        # A well-formed summary whose stock_code recovers to JSON null /
        # false / an array is explicit invalid evidence: a non-match, not
        # name-only tolerance.
        for bad in (None, False, []):
            log = [
                _codex_entry(
                    tool="get_realtime_quote",
                    summary=json.dumps({"stock_code": bad}),
                    step=1,
                ),
            ]
            m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
            assert m.expected_hit_rate == 0.0, bad
            assert m.missing_expected == ["get_realtime_quote"], bad
            assert not any("different stock" in v for v in m.violations), bad

    def test_invalid_golden_stock_code_falls_back_to_name_only(self):
        m = compute_trajectory_metrics(
            [_entry(tool="get_realtime_quote")],
            _golden(expected_tools=["get_realtime_quote"], stock_code=None),
        )
        assert "stock_code must be a non-empty string" in m.violations
        assert m.expected_hit_rate == 1.0


# ---------------------------------------------------------------------------
# 2d. Codex arguments_summary call identity (recovered structured payloads)
# ---------------------------------------------------------------------------
class TestCodexSummaryIdentity:
    def test_alias_summaries_share_one_call_identity(self):
        # Review counter-example: a failed call summarized with the alias
        # hk700 followed by the same call summarized as HK00700 is one
        # (tool, args-key) — the recovered dict goes through the same
        # stock_code canonicalization as a runner payload.
        log = [
            _codex_entry(
                tool="get_realtime_quote",
                summary=json.dumps({"stock_code": "hk700"}),
                step=1,
                success=False,
            ),
            _codex_entry(
                tool="get_realtime_quote",
                summary=json.dumps({"stock_code": "HK00700"}),
                step=2,
            ),
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.retries == 1
        assert m.redundant_calls == 1

    def test_key_order_summaries_share_one_call_identity(self):
        # Review counter-example: the recovered dict is serialized with
        # sort_keys=True, so argument insertion order must not split call
        # identity.
        log = [
            _codex_entry(
                tool="get_realtime_quote",
                summary=json.dumps({"stock_code": "600519", "days": 30}),
                step=1,
                success=False,
            ),
            _codex_entry(
                tool="get_realtime_quote",
                summary=json.dumps({"days": 30, "stock_code": "600519"}),
                step=2,
            ),
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.retries == 1
        assert m.redundant_calls == 1

    def test_number_and_string_summaries_do_not_merge_identity(self):
        # The recovered payload preserves the JSON number type exactly like
        # the runtime cache key: 600519 and "600519" stay two identities.
        log = [
            _codex_entry(
                tool="get_realtime_quote",
                summary=json.dumps({"stock_code": 600519}),
                step=1,
                success=False,
            ),
            _codex_entry(
                tool="get_realtime_quote",
                summary=json.dumps({"stock_code": "600519"}),
                step=2,
            ),
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.retries == 0
        assert m.redundant_calls == 0

    def test_other_summary_arguments_stay_raw_in_the_identity(self):
        # Only the string stock_code field is canonicalized — a different
        # period still splits the identity even for alias spellings.
        log = [
            _codex_entry(
                tool="get_realtime_quote",
                summary=json.dumps({"stock_code": "SH600519", "period": "daily"}),
                step=1,
                success=False,
            ),
            _codex_entry(
                tool="get_realtime_quote",
                summary=json.dumps({"stock_code": "600519", "period": "weekly"}),
                step=2,
            ),
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.retries == 0
        assert m.redundant_calls == 0

    def test_truncated_previews_keep_the_raw_preview_identity(self):
        # A preview that no longer parses to an object falls back to the
        # raw-preview wrapper, so it never merges with an intact summary of
        # the same call (documented best-effort limit).
        log = [
            _codex_entry(
                tool="get_realtime_quote",
                summary='{"stock_code": "6005...<truncated 12 chars>',
                step=1,
                success=False,
            ),
            _codex_entry(
                tool="get_realtime_quote",
                summary=json.dumps({"stock_code": "600519"}),
                step=2,
            ),
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"]))
        assert m.retries == 0
        assert m.redundant_calls == 0


# ---------------------------------------------------------------------------
# 2c. Stock-code canonicalization (runtime-equivalent mirror)
# ---------------------------------------------------------------------------
class TestStockCanonicalization:
    def test_mirror_matches_production_normalization(self):
        # The mirror must track the runtime chain exactly; if production
        # changes and this parity test fails, update the mirror.
        from src.agent.tools.execution import _normalize_tool_stock_code

        from evals.agent_trajectory.metrics import _canonicalize_stock_code

        forms = [
            "600519",
            "sh600519",
            "SH600519",
            "SH.600519",
            "600519.SH",
            "600519.SS",
            "SS600519",
            "SZ000001",
            "sz000001",
            "000001.SZ",
            "SZ.000001",
            "BJ920748",
            "920748.BJ",
            "HK00700",
            "hk700",
            "700.HK",
            "1810.HK",
            "00700",
            "7203.T",
            "005930.KS",
            "035720.KQ",
            "2330.TW",
            "6505.TWO",
            "AAPL",
            "aapl",
            " 600519 ",
            "1600519",
            "000001",
            "HK.700",
            "600519.SH ",
        ]
        for form in forms:
            assert _canonicalize_stock_code(form) == _normalize_tool_stock_code(form), form

    def test_float_evidence_matches_production_guard_coercion(self):
        # Guard-chain parity for float-shaped stock evidence: the coercion
        # step plus the mirror must agree with
        # execution._normalize_guard_stock_code on both branches (integral
        # float -> int, any other float -> str), so a value the runtime
        # guard reads as a code scores identically here.
        from src.agent.tools.execution import _normalize_guard_stock_code

        from evals.agent_trajectory.metrics import _canonicalize_stock_code, _coerce_guard_float

        for value in [600519.0, 600036.0, 600519.5, 600036.5]:
            coerced = _coerce_guard_float(value)
            assert _canonicalize_stock_code(coerced) == _normalize_guard_stock_code(coerced), value
            assert _normalize_guard_stock_code(value) == _normalize_guard_stock_code(coerced), value

    def test_injected_normalizer_overrides_the_mirror(self):
        golden = _golden(expected_tools=["get_realtime_quote"])
        log = [_entry(tool="get_realtime_quote", arguments={"stock_code": "SH600519"}, step=1)]
        # A strict identity normalizer must see SH600519 as a different
        # stock, while the default mirror resolves it to 600519.
        strict = compute_trajectory_metrics(log, golden, stock_code_normalizer=lambda v: str(v))
        assert strict.expected_hit_rate == 0.0
        assert strict.missing_expected == ["get_realtime_quote"]
        default = compute_trajectory_metrics(log, golden)
        assert default.expected_hit_rate == 1.0
        assert default.violations == []

    def test_identity_key_matches_production_cache_key_payload(self):
        # The identity payload must mirror src/agent/tools/execution.
        # _build_tool_cache_key byte for byte — alias folding for strings,
        # type preservation for JSON numbers.
        from src.agent.tools.execution import _build_tool_cache_key

        from evals.agent_trajectory.metrics import _args_key

        forms = [
            600519,
            "600519",
            "SH600519",
            "600519.SH",
            "sh600519",
            "HK00700",
            "700.HK",
            "00700",
            "SZ000001",
            " 600519 ",
        ]
        for form in forms:
            production = _build_tool_cache_key("get_realtime_quote", {"stock_code": form})
            mirrored = "get_realtime_quote:" + _args_key({"stock_code": form})
            assert mirrored == production, form

    def test_non_callable_normalizer_surfaces_violation(self):
        m = compute_trajectory_metrics([_entry()], _golden(), stock_code_normalizer="nope")
        assert "stock_code_normalizer is not callable" in m.violations
        assert m.expected_hit_rate == pytest.approx(1 / 3)


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
# 4c. Codex App Server step accounting
# ---------------------------------------------------------------------------
class TestCodexStepMetrics:
    @staticmethod
    def _codex_entries(n):
        return [
            {"step": 1, "tool": "get_realtime_quote", "arguments_summary": "600519", "success": True} for _ in range(n)
        ]

    def test_codex_shaped_log_suppresses_step_metrics(self):
        # The Codex backend records step=1 for every call in a turn and
        # total_steps=1 on success; feeding 8 such entries must not silently
        # read as a normal one-step run below the budget.
        m = compute_trajectory_metrics(
            self._codex_entries(8),
            _golden(expected_tools=["get_realtime_quote"], allowed_max_steps=8),
            total_steps=1,
        )
        assert m.distinct_steps == 0
        assert m.max_steps_touched is False
        assert any("step metrics are unsupported for Codex App Server logs" in v for v in m.violations)

    def test_runner_shaped_log_keeps_step_metrics(self):
        log = [_entry(step=i) for i in range(1, 9)]
        m = compute_trajectory_metrics(
            log,
            _golden(expected_tools=["get_realtime_quote"], allowed_max_steps=8),
        )
        assert m.distinct_steps == 8
        assert m.max_steps_touched is True
        assert not any("unsupported for Codex" in v for v in m.violations)

    def test_entries_without_any_arguments_are_not_codex_shaped(self):
        # Missing-argument tolerance must not trip the Codex detection.
        m = compute_trajectory_metrics([{"step": 3, "tool": "get_realtime_quote"}], _golden())
        assert m.distinct_steps == 1
        assert not any("unsupported for Codex" in v for v in m.violations)


# ---------------------------------------------------------------------------
# 4d. Codex outcome support (guard-dependent tags are unobservable)
# ---------------------------------------------------------------------------
class TestCodexOutcomeSupport:
    def test_guard_dependent_outcomes_marked_unsupported_for_codex_logs(self):
        # The Codex backend drops guarded/cached metadata, so a Codex-shaped
        # log can never observe guard-dependent tags; declaring them must
        # surface an explicit unsupported violation instead of a false
        # "expected outcomes not observed" regression.
        for tag in ("guarded", "cached", "guarded_retry"):
            log = [_codex_entry(tool="get_realtime_quote", step=1)]
            m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"], expected_outcomes=[tag]))
            assert not any("not observed" in v for v in m.violations), tag
            assert any("unsupported for Codex App Server logs" in v and tag in v for v in m.violations), tag

    def test_retry_stays_scoreable_for_codex_logs(self):
        # retry derives from (tool, args-key) repeats, which Codex entries
        # do carry: a failed call retried as the same recovered payload must
        # still satisfy the sample.
        log = [
            _codex_entry(
                tool="get_realtime_quote",
                summary=json.dumps({"stock_code": "600519"}),
                step=1,
                success=False,
            ),
            _codex_entry(
                tool="get_realtime_quote",
                summary=json.dumps({"stock_code": "600519"}),
                step=2,
            ),
        ]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"], expected_outcomes=["retry"]))
        assert m.retries == 1
        assert "expected outcomes not observed" not in m.violations
        assert not any("expected outcomes unsupported" in v for v in m.violations)

    def test_missing_retry_still_reported_for_codex_logs(self):
        # An observable outcome that is genuinely absent stays a real
        # regression for Codex logs too.
        log = [_codex_entry(tool="get_realtime_quote", step=1)]
        m = compute_trajectory_metrics(log, _golden(expected_tools=["get_realtime_quote"], expected_outcomes=["retry"]))
        assert "expected outcomes not observed: retry" in m.violations

    def test_runner_logs_keep_guard_outcome_scoring(self):
        # Runner-shaped logs carry the metadata, so guard-dependent tags are
        # scored normally and never marked unsupported.
        log = [
            _entry(
                tool="get_realtime_quote",
                arguments={"stock_code": "600519"},
                step=1,
                success=False,
                guarded=True,
            ),
        ]
        m = compute_trajectory_metrics(
            log, _golden(expected_tools=["get_realtime_quote"], expected_outcomes=["guarded"])
        )
        assert "expected outcomes not observed" not in m.violations
        assert not any("expected outcomes unsupported" in v for v in m.violations)


# ---------------------------------------------------------------------------
# 5. Tolerant entry shapes (Codex backend / missing fields)
# ---------------------------------------------------------------------------
class TestTolerantEntries:
    def test_missing_optional_fields_defaulted(self):
        m = compute_trajectory_metrics([{"step": 1, "tool": "get_realtime_quote"}], _golden())
        assert m.failed_calls == 0
        assert m.cached_calls == 0
        assert m.expected_hit_rate == pytest.approx(1 / 3)

    def test_codex_style_entries_keyed_by_arguments_summary(self):
        entry = {"step": 1, "tool": "get_stock_info", "arguments_summary": "600519", "success": True}
        m = compute_trajectory_metrics([entry, dict(entry, step=2)], _golden())
        assert m.redundant_calls == 1
        other = compute_trajectory_metrics(
            [entry, {**entry, "arguments_summary": "000001", "step": 2}],
            _golden(),
        )
        assert other.redundant_calls == 0

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
        assert len(samples) == 3
        assert [s.id for s in samples] == ["600519_technical", "000001_core_data_strict", "600036_guarded_retry"]

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
            skills="trading",
            allowed_max_steps="5",
            allow_optional_tools=1,
        )
        issues = validate_golden_sample(bad)
        assert any("id must be a non-empty string" in i for i in issues)
        assert any("task_description must be a non-empty string" in i for i in issues)
        assert any("skills must be a list" in i for i in issues)
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

    def test_guarded_retry_sample_declares_bound_guard_retry_outcome(self):
        sample = next(s for s in load_golden_samples() if s.id == "600036_guarded_retry")
        assert sample.expected_outcomes == ["guarded_retry"]
        assert sample.expected_guarded_stock == "600519"

    def test_expected_guarded_stock_validation(self):
        base = dict(
            id="x",
            task_description="t",
            stock_code="600036",
            expected_tools=["get_stock_info"],
            expected_outcomes=["guarded_retry"],
        )
        mistyped = GoldenSample(**base, expected_guarded_stock=600519)
        assert any("expected_guarded_stock must be a non-empty string" in i for i in validate_golden_sample(mistyped))
        same_stock = GoldenSample(**base, expected_guarded_stock="600036")
        assert any("must name a different stock than stock_code" in i for i in validate_golden_sample(same_stock))
        # Review counter-example: canonicalization must catch alias spellings
        # of the in-scope stock, not just identical strings.
        for alias in ("SH600036", "600036.SH", "SS600036", " 600036 "):
            alias_sample = GoldenSample(**base, expected_guarded_stock=alias)
            assert any(
                "must name a different stock than stock_code" in i for i in validate_golden_sample(alias_sample)
            ), alias
        no_outcome = GoldenSample(
            id="x",
            task_description="t",
            stock_code="600036",
            expected_tools=["get_stock_info"],
            expected_guarded_stock="600519",
        )
        assert any("requires guarded_retry in expected_outcomes" in i for i in validate_golden_sample(no_outcome))
        pinned = GoldenSample(**base, expected_guarded_stock="600519")
        assert validate_golden_sample(pinned) == []
        # A guarded stock that canonicalizes to a different code stays valid,
        # alias spelling or not.
        alias_other = GoldenSample(**base, expected_guarded_stock="SH600519")
        assert validate_golden_sample(alias_other) == []

    def test_unknown_expected_outcome_fails_validation(self):
        sample = GoldenSample(
            id="x",
            task_description="t",
            stock_code="600519",
            expected_tools=["get_realtime_quote"],
            expected_outcomes=["warp"],
        )
        issues = validate_golden_sample(sample)
        assert any("unknown expected_outcomes: warp" in i for i in issues)

    def test_duplicate_or_mistyped_expected_outcomes_fail_validation(self):
        dup = GoldenSample(
            id="x",
            task_description="t",
            stock_code="600519",
            expected_tools=["get_realtime_quote"],
            expected_outcomes=["guarded", "guarded"],
        )
        assert any("must not contain duplicate tags" in i for i in validate_golden_sample(dup))
        mistyped = GoldenSample(
            id="x",
            task_description="t",
            stock_code="600519",
            expected_tools=["get_realtime_quote"],
            expected_outcomes="guarded",
        )
        assert any("must be a list of outcome tags" in i for i in validate_golden_sample(mistyped))

    def test_loader_materializes_registry_once_for_multiple_samples(self):
        # A one-shot generator must survive loading the whole checked-in file:
        # the first sample must not exhaust it for the remaining samples.
        samples = load_golden_samples(known_tool_names=(name for name in _repo_tool_names()))
        assert len(samples) == 3


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

    def test_unknown_expected_outcome_raises(self, tmp_path):
        sample = {
            "id": "x",
            "task_description": "t",
            "stock_code": "600519",
            "expected_tools": ["get_realtime_quote"],
            "expected_outcomes": ["warp"],
        }
        path = self._write_sample(tmp_path, [sample])
        with pytest.raises(ValueError, match="unknown expected_outcomes: warp"):
            load_golden_samples(path=path)
