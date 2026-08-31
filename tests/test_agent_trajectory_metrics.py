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
        assert "golden sample has no expected_tools" in m.violations

    def test_string_expected_tools_scored_as_empty_not_as_characters(self):
        m = compute_trajectory_metrics([_entry()], _golden(expected_tools="get_realtime_quote"))
        assert m.expected_hit_rate == 0.0
        assert m.expected_total == 0
        assert "golden sample has no expected_tools" in m.violations

    def test_non_bool_allow_optional_tools_scores_strictly(self):
        log = [
            _entry(tool="get_realtime_quote", step=1),
            _entry(tool="search_stock_news", step=2),
        ]
        m = compute_trajectory_metrics(
            log,
            _golden(expected_tools=["get_realtime_quote"], allow_optional_tools="false"),
        )
        assert "allow_optional_tools is not a boolean" in m.violations
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
        assert "expected_tools contains duplicate names" in m.violations


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
        assert "unknown expected outcome tags: warp" in m.violations
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
        assert "expected_outcomes contains duplicate tags" in m.violations
        assert "expected outcomes not observed" not in m.violations


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

    def test_invalid_golden_stock_code_falls_back_to_name_only(self):
        m = compute_trajectory_metrics(
            [_entry(tool="get_realtime_quote")],
            _golden(expected_tools=["get_realtime_quote"], stock_code=None),
        )
        assert "golden.stock_code is not a non-empty string" in m.violations
        assert m.expected_hit_rate == 1.0


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
        assert "allowed_max_steps is not an integer" in m.violations


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
        assert any("must differ from stock_code" in i for i in validate_golden_sample(same_stock))
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
