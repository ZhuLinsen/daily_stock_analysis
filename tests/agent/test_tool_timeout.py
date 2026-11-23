# -*- coding: utf-8 -*-
"""Unit tests for agent tool timeout resolution (Issue #1890).

Covers:
- registry / policy / definition timeout fields
- ``_resolve_per_tool_timeout`` wiring (first-wins precedence)
- end-to-end ``_execute_tools`` per-tool timeout + fail-open behaviour
- cooperative-cancel wiring into ``check_tool_execution``

NOTE: ``ToolRegistry`` defines ``__len__`` but not ``__bool__``, so an *empty*
registry is falsy in Python and ``@tool(registry=empty)`` falls back to the
global default registry.  These tests therefore register tools directly via
``ToolDefinition`` (the same path ``factory.get_tool_registry`` uses) instead
of relying on the decorator's registry fallback.
"""
import gc
import json
import re
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.agent.factory import _build_category_timeout_map

# Mock heavy optional deps before importing agent modules (mirrors
# tests/agent/test_runtime_facts.py so the suite runs without litellm).
sys.modules.setdefault("litellm", MagicMock())

from src.agent.tools.registry import (
    ToolDefinition,
    ToolPolicy,
    ToolRegistry,
    tool,
)
from src.agent.runner import _execute_tools, _resolve_per_tool_timeout
from src.agent.tools.execution import _build_tool_cache_key


# ---------------------------------------------------------------------------
# 1. Registry / policy / definition fields
# ---------------------------------------------------------------------------
class TestRegistryTimeoutFields:
    def test_category_default_timeout_lookup(self):
        reg = ToolRegistry(category_timeout_map={"data": 30.0, "action": 5.0})
        assert reg.category_default_timeout("data") == 30.0
        assert reg.category_default_timeout("action") == 5.0
        assert reg.category_default_timeout("analysis") is None

    def test_policy_declared_carries_timeout(self):
        assert ToolPolicy.declared(read_only=True, timeout_seconds=7.0).timeout_seconds == 7.0
        assert ToolPolicy.declared(read_only=True).timeout_seconds is None

    def test_definition_carries_timeout(self):
        d = ToolDefinition(
            name="x", description="x", parameters=[], handler=lambda: None,
            timeout_seconds=3.0,
        )
        assert d.timeout_seconds == 3.0

    def test_decorator_exposes_timeout(self):
        reg = ToolRegistry()

        @tool(name="sample", category="data", description="sample", registry=reg, timeout_seconds=4.0)
        def sample():
            return 1

        assert getattr(sample, "_tool_definition", None) is not None
        assert sample._tool_definition.timeout_seconds == 4.0


# ---------------------------------------------------------------------------
# 3. Runner wiring
# ---------------------------------------------------------------------------
def _make_tool_call(name, args=None, tc_id="call_1"):
    return SimpleNamespace(name=name, arguments=args or {}, id=tc_id)


def _register(reg, name, fn, *, category="data", timeout_seconds=None):
    reg.register(ToolDefinition(
        name=name, description=name, parameters=[], handler=fn,
        category=category, timeout_seconds=timeout_seconds,
    ))


class TestResolvePerToolTimeout:
    def test_per_tool_overrides_category(self):
        reg = ToolRegistry(category_timeout_map={"data": 30.0})
        _register(reg, "t", lambda: None, category="data", timeout_seconds=2.0)
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg) == 2.0

    def test_category_used_when_no_per_tool(self):
        reg = ToolRegistry(category_timeout_map={"data": 30.0})
        _register(reg, "t", lambda: None, category="data")
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg) == 30.0

    def test_explicit_per_run_beats_per_tool_and_category(self):
        reg = ToolRegistry(category_timeout_map={"data": 30.0})
        _register(reg, "t", lambda: None, category="data", timeout_seconds=2.0)
        # first-wins: explicit tool_call_timeout_seconds is the highest priority.
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg, 60.0) == 60.0

    def test_wall_clock_budget_caps_everything(self):
        reg = ToolRegistry(category_timeout_map={"data": 30.0})
        _register(reg, "t", lambda: None, category="data", timeout_seconds=2.0)
        # remaining budget of 1.0 caps the resolved timeout.
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg, 60.0, 1.0) == 1.0

    def test_no_limits_returns_budget_or_none(self):
        reg = ToolRegistry()
        _register(reg, "t", lambda: None, category="data")
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg) is None
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg, None, 5.0) == 5.0


# ---------------------------------------------------------------------------
# 4. End-to-end _execute_tools
# ---------------------------------------------------------------------------
class TestExecuteToolsTimeout:
    def test_per_tool_timeout_fires_and_fail_open(self):
        reg = ToolRegistry(category_timeout_map={"data": 0.2})

        def slow():
            time.sleep(1.0)
            return {"ok": True}

        _register(reg, "slow", slow, category="data")
        log = []
        results = _execute_tools(
            [_make_tool_call("slow")], reg, step=1,
            progress_callback=None, tool_calls_log=log,
            tool_wait_timeout_seconds=None,
        )
        assert len(results) == 1
        parsed = json.loads(results[0]["result_str"])
        assert parsed.get("timeout") is True
        assert any(e.get("timeout") is True for e in log)

    def test_no_timeout_when_fast_enough(self):
        reg = ToolRegistry(category_timeout_map={"data": 2.0})

        def fast():
            return {"ok": True}

        _register(reg, "fast", fast, category="data")
        log = []
        results = _execute_tools(
            [_make_tool_call("fast")], reg, step=1,
            progress_callback=None, tool_calls_log=log,
            tool_wait_timeout_seconds=None,
        )
        assert json.loads(results[0]["result_str"]).get("ok") is True
        assert not any(e.get("timeout") for e in log)

    def test_backward_compat_no_limits_runs_inline(self):
        # No category map, no global timeout -> tool executes inline, no
        # spurious timeout.
        reg = ToolRegistry()

        def plain():
            return {"ok": True}

        _register(reg, "plain", plain, category="data")
        log = []
        results = _execute_tools(
            [_make_tool_call("plain")], reg, step=1,
            progress_callback=None, tool_calls_log=log,
            tool_wait_timeout_seconds=None,
        )
        assert json.loads(results[0]["result_str"]).get("ok") is True

    def test_parallel_per_tool_timeout(self):
        reg = ToolRegistry(category_timeout_map={"data": 0.2})

        def slowA():
            time.sleep(1.0)
            return {"a": True}

        def slowB():
            time.sleep(1.0)
            return {"b": True}

        _register(reg, "slowA", slowA, category="data")
        _register(reg, "slowB", slowB, category="data")
        log = []
        results = _execute_tools(
            [_make_tool_call("slowA", tc_id="c1"), _make_tool_call("slowB", tc_id="c2")],
            reg, step=1, progress_callback=None, tool_calls_log=log,
            tool_wait_timeout_seconds=None,
        )
        assert len(results) == 2
        assert all(json.loads(r["result_str"]).get("timeout") is True for r in results)

    def test_mixed_fast_and_slow_parallel(self):
        """Regression (review): a parallel batch mixing a fast and a slow tool
        must let the fast one succeed while the slow one times out at its own
        limit — the fast result is not blocked, the batch is bounded by the slow
        tool's timeout, and each duration is accurate (the slow entry reports its
        own per-tool timeout, not a batch-wide value).
        """
        reg = ToolRegistry(category_timeout_map={"data": 0.3})

        def fast():
            return {"ok": True}

        def slow():
            time.sleep(2.0)
            return {"ok": True}

        _register(reg, "fast", fast, category="data")
        _register(reg, "slow", slow, category="data")
        log = []
        start = time.time()
        results = _execute_tools(
            [_make_tool_call("fast", tc_id="c1"), _make_tool_call("slow", tc_id="c2")],
            reg, step=1, progress_callback=None, tool_calls_log=log,
            tool_wait_timeout_seconds=None,
        )
        elapsed = time.time() - start

        fast_res = next(r for r in results if r["tc"].name == "fast")
        slow_res = next(r for r in results if r["tc"].name == "slow")
        assert json.loads(fast_res["result_str"]).get("ok") is True
        assert json.loads(slow_res["result_str"]).get("timeout") is True

        fast_entry = next(e for e in log if e["tool"] == "fast")
        slow_entry = next(e for e in log if e["tool"] == "slow")
        assert fast_entry["success"] is True
        assert slow_entry["timeout"] is True
        assert slow_entry["duration"] == 0.3   # the slow tool's own limit, accurate
        assert elapsed < 1.5                    # bounded by 0.3s, not the 2s body

    def test_queued_call_does_not_burn_timeout_before_start(self):
        """Review OR-COM-3d6b61f8: with the pool capped at 5, a 6th queued call
        must not time out from a deadline that started at *submission*.  The fast
        6th tool waits behind five slow (timeout-bound) siblings, then starts and
        completes within its own limit.
        """
        reg = ToolRegistry(category_timeout_map={"data": 0.2})

        def slow():
            time.sleep(0.5)
            return {"ok": True}

        def fast():
            return {"ok": True}

        _register(reg, "slow", slow, category="data")
        _register(reg, "fast", fast, category="data")
        tool_calls = [_make_tool_call("slow", tc_id=f"s{i}") for i in range(5)] + [
            _make_tool_call("fast", tc_id="f1")
        ]
        results = _execute_tools(
            tool_calls, reg, step=1, progress_callback=None, tool_calls_log=[],
            tool_wait_timeout_seconds=None,
        )
        fast_res = next(r for r in results if r["tc"].name == "fast")
        # The queued fast tool must run and succeed — never a false timeout that
        # started counting before it got a worker.
        assert json.loads(fast_res["result_str"]).get("ok") is True
        # All 5 slow siblings timed out at their own 0.2s limit.
        slow_ress = [r for r in results if r["tc"].name == "slow"]
        assert len(slow_ress) == 5
        assert all(json.loads(r["result_str"]).get("timeout") is True for r in slow_ress)


# ---------------------------------------------------------------------------
# 5. Config env contract (Issue #1890 test point 1: AGENT_DATA_TOOL_TIMEOUT_S=20)
# ---------------------------------------------------------------------------
class TestConfigEnvContract:
    def test_field_names_match_issue_contract(self):
        # Issue #1890 specifies env names like AGENT_DATA_TOOL_TIMEOUT_S.
        from src.config import Config

        names = {f.name for f in Config.__dataclass_fields__.values()}
        assert "agent_data_tool_timeout_s" in names
        assert "agent_search_tool_timeout_s" in names
        assert "agent_analysis_tool_timeout_s" in names
        assert "agent_action_tool_timeout_s" in names

    def test_field_default_is_zero_backward_compatible(self):
        # No env set -> 0.0 -> category default disabled -> behaves like today.
        from src.config import Config

        default = Config.__dataclass_fields__["agent_data_tool_timeout_s"].default
        assert default == 0.0

    def test_env_value_is_parsed(self, monkeypatch):
        import os

        import src.config as cfg

        monkeypatch.setenv("AGENT_DATA_TOOL_TIMEOUT_S", "20")
        val = cfg.parse_env_float(
            os.getenv("AGENT_DATA_TOOL_TIMEOUT_S"),
            0.0,
            field_name="AGENT_DATA_TOOL_TIMEOUT_S",
            minimum=0.0,
        )
        assert val == 20.0


# ---------------------------------------------------------------------------
# 6. Category coverage (Issue #1890 review: market tools must get a ceiling)
# ---------------------------------------------------------------------------
class TestCategoryTimeoutMap:
    def test_market_tools_share_data_timeout(self):
        from src.agent.factory import _build_category_timeout_map

        config = SimpleNamespace(
            agent_data_tool_timeout_s=15.0,
            agent_search_tool_timeout_s=0.0,
            agent_analysis_tool_timeout_s=0.0,
            agent_action_tool_timeout_s=0.0,
        )
        mapping = _build_category_timeout_map(config)
        assert mapping["data"] == 15.0
        assert mapping["market"] == 15.0
        assert "search" not in mapping


# ---------------------------------------------------------------------------
# 7. Tool registry cache invalidation (Issue #1890 follow-up review)
# ---------------------------------------------------------------------------
class TestToolRegistryCacheInvalidation:
    """The module-level ``_TOOL_REGISTRY`` cache must not shadow a reloaded
    ``Config`` instance.  These tests pin the contract:

    * ``reset_tool_registry`` empties the cache.
    * ``get_tool_registry(config)`` rebuilds when the resolved per-category
      timeouts differ from the ones the cached registry was built with, and
      does so even when the new ``Config`` instance happens to reuse the
      collected instance's ``id()``.
    * ``SystemConfigService._reload_runtime_singletons`` actually invokes
      ``reset_tool_registry`` so API/scheduler/bot entry-points observe the
      fresh ``AGENT_*_TOOL_TIMEOUT_S`` values.
    """

    @pytest.fixture(autouse=True)
    def _isolate_factory_module_state(self):
        """Snapshot/restore ``factory._TOOL_REGISTRY`` so this class cannot
        bleed cache state across other tests in the same pytest process.
        """
        from src.agent import factory

        saved_registry = factory._TOOL_REGISTRY
        saved_timeout_map = factory._CACHED_TIMEOUT_MAP
        factory.reset_tool_registry()
        try:
            yield
        finally:
            factory._TOOL_REGISTRY = saved_registry
            factory._CACHED_TIMEOUT_MAP = saved_timeout_map

    def _empty_tool_lists(self):
        """Patch the ALL_*_TOOLS module-level names on ``factory`` so the
        rebuild loop is a no-op and the test stays independent of the
        full tool-registration chain.
        """
        from src.agent import factory

        return (
            patch.object(factory, "ALL_DATA_TOOLS", [], create=True),
            patch.object(factory, "ALL_ANALYSIS_TOOLS", [], create=True),
            patch.object(factory, "ALL_SEARCH_TOOLS", [], create=True),
            patch.object(factory, "ALL_MARKET_TOOLS", [], create=True),
            patch.object(factory, "ALL_BACKTEST_TOOLS", [], create=True),
        )

    def test_reset_tool_registry_clears_module_cache(self):
        from src.agent import factory

        # Sanity: initial reset empties the module-level cache.
        factory.reset_tool_registry()
        assert factory._TOOL_REGISTRY is None
        assert factory._CACHED_TIMEOUT_MAP is None

        # Idempotent: calling reset on an empty cache is a no-op.
        factory.reset_tool_registry()
        assert factory._TOOL_REGISTRY is None
        assert factory._CACHED_TIMEOUT_MAP is None

    def test_get_tool_registry_rebuilds_when_config_changes(self):
        """Two callers passing two *distinct* ``Config`` instances must
        observe the matching per-category timeouts on each rebuild — never
        a stale view from the first build.
        """
        from src.agent import factory

        config_a = SimpleNamespace(
            agent_data_tool_timeout_s=10.0,
            agent_search_tool_timeout_s=0.0,
            agent_analysis_tool_timeout_s=0.0,
            agent_action_tool_timeout_s=0.0,
        )
        config_b = SimpleNamespace(
            agent_data_tool_timeout_s=25.0,
            agent_search_tool_timeout_s=5.0,
            agent_analysis_tool_timeout_s=0.0,
            agent_action_tool_timeout_s=0.0,
        )
        # Force the configs to be distinct objects (SimpleNamespace instances
        # already have distinct id() unless they're literal `()`).
        assert id(config_a) != id(config_b)

        empty_lists = self._empty_tool_lists()
        with patch.object(
            factory, "_build_category_timeout_map"
        ) as build_map, patch(
            "src.agent.tools.registry.ToolRegistry"
        ) as registry_cls, empty_lists[0], empty_lists[1], empty_lists[2], empty_lists[3], empty_lists[4]:
            registry_instance_a = MagicMock(name="registry_a")
            registry_instance_b = MagicMock(name="registry_b")
            registry_cls.side_effect = [registry_instance_a, registry_instance_b]
            build_map.side_effect = lambda cfg: _build_category_timeout_map(cfg)

            first = factory.get_tool_registry(config_a)
            second = factory.get_tool_registry(config_b)

            # Two distinct registry objects — never the cached first build.
            assert first is registry_instance_a
            assert second is registry_instance_b
            assert first is not second
            # And the cache now points at the *second* one.
            assert factory._TOOL_REGISTRY is registry_instance_b
            assert factory._CACHED_TIMEOUT_MAP == {
                "data": 25.0,
                "search": 5.0,
                "market": 25.0,
            }
            # ToolRegistry was constructed with the *matching* timeout map.
            assert registry_cls.call_args_list[0].kwargs["category_timeout_map"] == {
                "data": 10.0,
                "market": 10.0,
            }
            assert registry_cls.call_args_list[1].kwargs["category_timeout_map"] == {
                "data": 25.0,
                "search": 5.0,
                "market": 25.0,
            }

    def test_get_tool_registry_reuses_cache_for_equivalent_config(self):
        """Repeated calls carrying the same effective timeouts must reuse the
        cache so the tool-registration cost is paid at most once.

        The final call passes a *different object* with identical values: the
        registry only depends on the resolved timeout map, so rebuilding it
        would be pure waste on every request.
        """
        from src.agent import factory

        config = SimpleNamespace(
            agent_data_tool_timeout_s=10.0,
            agent_search_tool_timeout_s=0.0,
            agent_analysis_tool_timeout_s=0.0,
            agent_action_tool_timeout_s=0.0,
        )
        equivalent_config = SimpleNamespace(
            agent_data_tool_timeout_s=10.0,
            agent_search_tool_timeout_s=0.0,
            agent_analysis_tool_timeout_s=0.0,
            agent_action_tool_timeout_s=0.0,
        )
        empty_lists = self._empty_tool_lists()
        with patch.object(
            factory, "_build_category_timeout_map"
        ) as build_map, patch(
            "src.agent.tools.registry.ToolRegistry"
        ) as registry_cls, empty_lists[0], empty_lists[1], empty_lists[2], empty_lists[3], empty_lists[4]:
            registry_instance = MagicMock(name="registry")
            registry_cls.return_value = registry_instance
            build_map.side_effect = lambda cfg: _build_category_timeout_map(cfg)

            first = factory.get_tool_registry(config)
            second = factory.get_tool_registry(config)
            third = factory.get_tool_registry(equivalent_config)

            assert first is second is third is registry_instance
            # ToolRegistry was instantiated exactly once across three calls.
            assert registry_cls.call_count == 1

    def test_build_agent_executor_forwards_config_to_registry(self):
        """Regression for review blockers OR-COM-dd1e8fa7 / OR-COM-bff42110: the
        builder must hand its *caller-supplied* ``config`` to
        ``get_tool_registry`` so a distinct / updated config actually re-binds
        the category timeouts instead of silently reusing the first cached
        registry built from a frozen default config.
        """
        from src.agent import factory

        config = SimpleNamespace(
            agent_data_tool_timeout_s=12.0,
            agent_search_tool_timeout_s=0.0,
            agent_analysis_tool_timeout_s=0.0,
            agent_action_tool_timeout_s=0.0,
            agent_arch="single",
        )
        with patch.object(factory, "get_tool_registry") as gtr, patch.object(
            factory, "resolve_skill_prompt_state"
        ) as rsp, patch("src.agent.llm_adapter.LLMToolAdapter"), patch(
            "src.agent.executor.AgentExecutor"
        ) as ae_cls:
            gtr.return_value = MagicMock(name="registry")
            rsp.return_value = MagicMock(skill_manager=MagicMock())
            factory.build_agent_executor(config)
            # The registry is (re)built from THIS config, not a frozen default.
            assert gtr.call_args == ((config,),)
            assert ae_cls.call_args.kwargs["tool_registry"] is gtr.return_value

    def test_rebuild_survives_config_instance_id_reuse(self):
        """A reloaded ``Config`` must be honoured even when CPython hands the
        new instance the *same* ``id()`` as the collected one.

        ``Config.reset_instance()`` drops the only strong reference, so the
        allocator frequently reuses that address for the replacement instance.
        Keying the cache on ``id(config)`` would read that as "unchanged" and
        keep serving the stale registry — exactly the bug this class guards.
        """
        from src.agent import factory

        empty_lists = self._empty_tool_lists()
        with patch.object(
            factory, "_build_category_timeout_map"
        ) as build_map, patch(
            "src.agent.tools.registry.ToolRegistry"
        ) as registry_cls, empty_lists[0], empty_lists[1], empty_lists[2], empty_lists[3], empty_lists[4]:
            registry_old = MagicMock(name="registry_old")
            registry_new = MagicMock(name="registry_new")
            registry_cls.side_effect = [registry_old, registry_new]
            build_map.side_effect = lambda cfg: _build_category_timeout_map(cfg)

            config_old = SimpleNamespace(
                agent_data_tool_timeout_s=10.0,
                agent_search_tool_timeout_s=0.0,
                agent_analysis_tool_timeout_s=0.0,
                agent_action_tool_timeout_s=0.0,
            )
            factory.get_tool_registry(config_old)
            assert factory._TOOL_REGISTRY is registry_old

            # Simulate the worst case rather than relying on the allocator:
            # a new config whose id() collides with the collected instance.
            stale_id = id(config_old)
            del config_old
            gc.collect()

            config_new = SimpleNamespace(
                agent_data_tool_timeout_s=45.0,
                agent_search_tool_timeout_s=0.0,
                agent_analysis_tool_timeout_s=0.0,
                agent_action_tool_timeout_s=0.0,
            )
            # Force a deterministic id() collision so this doubles as a real
            # regression guard: a future implementation that re-keys the cache
            # on ``id(config)`` would read the new config as "unchanged" and
            # wrongly reuse ``registry_old``.  Patching ``builtins.id`` (not
            # ``factory.id``) is required because ``get_tool_registry`` uses the
            # builtin directly.
            with patch("builtins.id", return_value=stale_id):
                rebuilt = factory.get_tool_registry(config_new)

            # Value-keyed cache still notices the change.
            assert rebuilt is registry_new
            assert registry_cls.call_args_list[-1].kwargs["category_timeout_map"] == {
                "data": 45.0,
                "market": 45.0,
            }

    def test_get_tool_registry_tolerates_partial_config_objects(self):
        """Callers hand ``get_tool_registry`` whatever config they hold, which
        in tests is routinely a ``MagicMock`` or a stub missing the timeout
        attributes.  Neither may explode: ``MagicMock() > 0`` raises
        ``TypeError`` and a bare stub raises ``AttributeError``, so the
        resolver coerces both to "no category limit".
        """

        class _StubConfig:
            """No AGENT_*_TOOL_TIMEOUT_S attributes at all."""

        assert _build_category_timeout_map(MagicMock()) == {}
        assert _build_category_timeout_map(_StubConfig()) == {}

        # Garbage values degrade to "no limit" rather than propagating.
        noisy = SimpleNamespace(
            agent_data_tool_timeout_s="not-a-number",
            agent_search_tool_timeout_s=None,
            agent_analysis_tool_timeout_s=7.5,
            agent_action_tool_timeout_s=-3.0,
        )
        assert _build_category_timeout_map(noisy) == {"analysis": 7.5}

    def test_reload_runtime_singletons_drops_registry(self):
        """``SystemConfigService._reload_runtime_singletons`` must include
        ``reset_tool_registry``; otherwise long-running API/scheduler/bot
        processes will keep using the first build's per-category timeouts.
        """
        from src.agent import factory
        from src.services import system_config_service

        with patch.object(factory, "reset_tool_registry") as reset_mock:
            system_config_service.SystemConfigService._reload_runtime_singletons()

        reset_mock.assert_called_once()

    def test_reload_runtime_singletons_actually_invalidates_cached_registry(self):
        """End-to-end: with the cache populated against config_old, calling
        ``_reload_runtime_singletons`` must clear it so the next
        ``get_tool_registry(config_new)`` rebuilds against the new config.
        """
        from src.agent import factory

        config_old = SimpleNamespace(
            agent_data_tool_timeout_s=10.0,
            agent_search_tool_timeout_s=0.0,
            agent_analysis_tool_timeout_s=0.0,
            agent_action_tool_timeout_s=0.0,
        )
        config_new = SimpleNamespace(
            agent_data_tool_timeout_s=99.0,
            agent_search_tool_timeout_s=0.0,
            agent_analysis_tool_timeout_s=0.0,
            agent_action_tool_timeout_s=0.0,
        )

        empty_lists = self._empty_tool_lists()
        with patch.object(
            factory, "_build_category_timeout_map"
        ) as build_map, patch(
            "src.agent.tools.registry.ToolRegistry"
        ) as registry_cls, empty_lists[0], empty_lists[1], empty_lists[2], empty_lists[3], empty_lists[4]:
            registry_old = MagicMock(name="registry_old")
            registry_new = MagicMock(name="registry_new")
            registry_cls.side_effect = [registry_old, registry_new]
            build_map.side_effect = lambda cfg: _build_category_timeout_map(cfg)

            from src.services import system_config_service

            # 1) Prime the cache against the old config.
            factory.get_tool_registry(config_old)
            assert factory._TOOL_REGISTRY is registry_old

            # 2) Simulate a runtime reload — the service-side hook clears
            #    the cache (real call, not mocked, so we exercise the wiring).
            system_config_service.SystemConfigService._reload_runtime_singletons()
            assert factory._TOOL_REGISTRY is None
            assert factory._CACHED_TIMEOUT_MAP is None

            # 3) Next access, with the new config, must rebuild and observe
            #    the new timeout.
            rebuilt = factory.get_tool_registry(config_new)
            assert rebuilt is registry_new
            assert factory._TOOL_REGISTRY is registry_new
            assert registry_cls.call_args_list[-1].kwargs["category_timeout_map"] == {
                "data": 99.0,
                "market": 99.0,
            }


# ---------------------------------------------------------------------------
# 8. Maintainer review blockers (first-wins precedence, non-retriable timeouts,
#    finite validation, cache thread-safety)
# ---------------------------------------------------------------------------
class TestFirstWinsTimeoutPrecedence:
    """Blocker: first-wins precedence — explicit per-run
    ``tool_call_timeout_seconds`` > per-tool declaration > category default >
    none — with the remaining wall-clock budget as an unbreakable outer cap.
    The previous ``min()`` across all levels let a smaller category default
    override an explicit declaration and made an explicit per-run value unable
    to relax a stricter per-tool timeout.
    """

    def test_explicit_per_tool_beats_smaller_category(self):
        reg = ToolRegistry(category_timeout_map={"data": 10.0})
        _register(reg, "t", lambda: None, category="data", timeout_seconds=30.0)
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg) == 30.0

    def test_explicit_per_tool_beats_larger_category(self):
        reg = ToolRegistry(category_timeout_map={"data": 50.0})
        _register(reg, "t", lambda: None, category="data", timeout_seconds=20.0)
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg) == 20.0

    def test_explicit_per_run_overrides_per_tool_and_category(self):
        reg = ToolRegistry(category_timeout_map={"data": 10.0})
        _register(reg, "t", lambda: None, category="data", timeout_seconds=30.0)
        # the caller's explicit per-run value relaxes a stricter per-tool 30s.
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg, 60.0) == 60.0
        # and overrides a larger category default too.
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg, 15.0) == 15.0

    def test_wall_clock_budget_is_outer_cap_only(self):
        reg = ToolRegistry(category_timeout_map={"data": 10.0})
        _register(reg, "t", lambda: None, category="data", timeout_seconds=30.0)
        # base 30 capped to the 15s remaining budget.
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg, None, 15.0) == 15.0
        # explicit 60 also capped by the remaining budget.
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg, 60.0, 15.0) == 15.0
        # budget disabled -> the first-wins winner stands.
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg, None, None) == 30.0

    def test_explicit_per_run_relaxes_per_tool_end_to_end(self):
        reg = ToolRegistry(category_timeout_map={"data": 0.2})
        calls = {"n": 0}

        def slow():
            calls["n"] += 1
            time.sleep(0.8)
            return {"ok": True}

        _register(reg, "slow", slow, category="data", timeout_seconds=0.1)
        results = _execute_tools(
            [_make_tool_call("slow")], reg, step=1,
            progress_callback=None, tool_calls_log=[],
            tool_call_timeout_seconds=0.6,   # explicit override > per-tool 0.1s
            tool_wait_timeout_seconds=None,
        )
        parsed = json.loads(results[0]["result_str"])
        assert parsed.get("timeout") is True
        # The effective timeout is the explicit 0.6s, not the 0.1s per-tool
        # declaration — proving the explicit value won the first-wins chain.
        match = re.search(r"after ([\d.]+)s", results[0]["result_str"])
        assert match and abs(float(match.group(1)) - 0.6) < 0.05


class TestFilteredRegistryCarriesTimeoutMap:
    """Review OR-COM-7f3d3f5b: a filtered registry (``BaseAgent._filtered_registry``)
    must retain the source registry's per-category timeout map, otherwise the
    category ceilings silently stop applying on tool subsets.
    """

    def test_category_timeout_map_property(self):
        reg = ToolRegistry(category_timeout_map={"data": 5.0, "search": 10.0})
        assert reg.category_timeout_map == {"data": 5.0, "search": 10.0}
        # returns a copy, not the internal dict
        reg.category_timeout_map["data"] = 99.0
        assert reg.category_default_timeout("data") == 5.0

    def test_filtered_copy_keeps_category_default(self):
        reg = ToolRegistry(category_timeout_map={"data": 5.0})
        _register(reg, "t", lambda: None, category="data")
        # Mimic BaseAgent._filtered_registry: rebuild with the source map.
        from src.agent.tools.registry import ToolRegistry as TR

        filtered = TR(category_timeout_map=reg.category_timeout_map)
        for name in reg.list_names():
            filtered.register(reg.get(name))
        # The category ceiling still applies on the filtered subset.
        assert _resolve_per_tool_timeout(_make_tool_call("t"), filtered, None, None) == 5.0


class TestTimeoutResultNonRetriable:
    """Blocker: a timed-out call must be marked ``retriable: False`` *and*
    recorded in ``non_retriable_tool_results`` so an LLM retry of the same call
    reuses the cached failure instead of spinning up a second (side-effecting)
    execution.  Python cannot forcibly cancel an already-started tool thread, so
    this is the best-effort guard against duplicate work.
    """

    def test_timeout_result_is_marked_non_retriable(self):
        reg = ToolRegistry(category_timeout_map={"data": 0.2})

        def slow():
            time.sleep(1.0)
            return {"ok": True}

        _register(reg, "slow", slow, category="data")
        results = _execute_tools(
            [_make_tool_call("slow")], reg, step=1,
            progress_callback=None, tool_calls_log=[],
            tool_wait_timeout_seconds=None,
        )
        parsed = json.loads(results[0]["result_str"])
        assert parsed.get("timeout") is True
        assert parsed.get("retriable") is False

    def test_timed_out_tool_not_re_executed_on_retry(self):
        reg = ToolRegistry(category_timeout_map={"data": 0.2})
        calls = {"n": 0}

        def slow():
            calls["n"] += 1
            time.sleep(1.0)
            return {"ok": True}

        _register(reg, "slow", slow, category="data")
        shared_non_retriable = {}

        # First call times out and is recorded as non-retriable.
        res1 = _execute_tools(
            [_make_tool_call("slow", tc_id="c1")], reg, step=1,
            progress_callback=None, tool_calls_log=[],
            tool_wait_timeout_seconds=None,
            non_retriable_tool_results=shared_non_retriable,
        )
        assert json.loads(res1[0]["result_str"]).get("timeout") is True
        assert _build_tool_cache_key("slow", {}) in shared_non_retriable  # keyed by name+args

        first_calls = calls["n"]
        # Identical retry: must NOT spin up a second execution.
        res2 = _execute_tools(
            [_make_tool_call("slow", tc_id="c1")], reg, step=2,
            progress_callback=None, tool_calls_log=[],
            tool_wait_timeout_seconds=None,
            non_retriable_tool_results=shared_non_retriable,
        )
        assert json.loads(res2[0]["result_str"]).get("timeout") is True
        assert calls["n"] == first_calls  # handler never ran again

    def test_timeout_with_non_dict_arguments_does_not_write_none_key(self):
        """Regression: a timeout payload built from non-dict ``arguments``
        (cache key ``None``) must not write a shared ``None`` entry into
        ``non_retriable_tool_results``, which could alias unrelated no-arg calls.
        """
        reg = ToolRegistry(category_timeout_map={"data": 0.2})

        def slow():
            time.sleep(1.0)
            return {"ok": True}

        _register(reg, "slow", slow, category="data")
        shared_non_retriable = {}
        results = _execute_tools(
            [_make_tool_call("slow", args=None)], reg, step=1,
            progress_callback=None, tool_calls_log=[],
            tool_wait_timeout_seconds=None,
            non_retriable_tool_results=shared_non_retriable,
        )
        assert json.loads(results[0]["result_str"]).get("timeout") is True
        assert None not in shared_non_retriable


class TestTimeoutFiniteValidation:
    """Blocker: ``inf``/``nan``/negative ``AGENT_*_TOOL_TIMEOUT_S`` must degrade
    to "no limit" rather than raising ``OverflowError`` at
    ``future.result(timeout=inf)``.
    """

    def test_config_inf_degrades_to_no_limit(self):
        from src.agent.factory import _coerce_config_timeout

        cfg = SimpleNamespace(agent_data_tool_timeout_s=float("inf"))
        assert _coerce_config_timeout(cfg, "agent_data_tool_timeout_s") == 0.0

    def test_config_nan_degrades_to_no_limit(self):
        from src.agent.factory import _coerce_config_timeout

        cfg = SimpleNamespace(agent_data_tool_timeout_s=float("nan"))
        assert _coerce_config_timeout(cfg, "agent_data_tool_timeout_s") == 0.0

    def test_config_excessive_value_is_clamped(self):
        from src.agent.factory import _coerce_config_timeout, _MAX_TOOL_TIMEOUT_S

        cfg = SimpleNamespace(agent_data_tool_timeout_s=999999.0)
        assert _coerce_config_timeout(cfg, "agent_data_tool_timeout_s") == _MAX_TOOL_TIMEOUT_S

    def test_per_tool_inf_is_not_a_valid_timeout(self):
        reg = ToolRegistry(category_timeout_map={})
        _register(reg, "t", lambda: None, category="data", timeout_seconds=float("inf"))
        # inf must not survive into the resolved timeout.
        assert _resolve_per_tool_timeout(_make_tool_call("t"), reg, None) is None


class TestToolRegistryCacheThreadSafety:
    """Blocker: ``get_tool_registry`` / ``reset_tool_registry`` must be safe
    under concurrent requests with different ``Config`` objects — no partial
    assignment of the shared ``_TOOL_REGISTRY`` / ``_CACHED_TIMEOUT_MAP`` pair.
    """

    @pytest.fixture(autouse=True)
    def _isolate_factory_module_state(self):
        from src.agent import factory

        saved_registry = factory._TOOL_REGISTRY
        saved_timeout_map = factory._CACHED_TIMEOUT_MAP
        factory.reset_tool_registry()
        try:
            yield
        finally:
            factory._TOOL_REGISTRY = saved_registry
            factory._CACHED_TIMEOUT_MAP = saved_timeout_map

    def test_lock_is_present(self):
        from src.agent import factory

        assert isinstance(factory._tool_registry_lock, type(threading.Lock()))

    def test_fast_path_returns_cached_registry_consistently(self):
        """Review OR-COM-a1e8b0c2: the locked fast path must hand back the same
        registry on a cache hit and a valid (non-None) one after a reset — no
        check-then-use window against ``reset_tool_registry()``.
        """
        from src.agent.factory import get_tool_registry, reset_tool_registry

        config = SimpleNamespace(
            agent_data_tool_timeout_s=5.0,
            agent_search_tool_timeout_s=0.0,
            agent_analysis_tool_timeout_s=0.0,
            agent_action_tool_timeout_s=0.0,
        )
        r1 = get_tool_registry(config)
        r2 = get_tool_registry(config)  # cache hit via the locked fast path
        assert r1 is r2
        reset_tool_registry()
        r3 = get_tool_registry(config)
        assert r3 is not None
        assert r3.category_default_timeout("data") == 5.0

    def test_concurrent_builds_do_not_raise(self):
        from src.agent import factory
        import threading

        config_a = SimpleNamespace(
            agent_data_tool_timeout_s=10.0,
            agent_search_tool_timeout_s=0.0,
            agent_analysis_tool_timeout_s=0.0,
            agent_action_tool_timeout_s=0.0,
        )
        config_b = SimpleNamespace(
            agent_data_tool_timeout_s=25.0,
            agent_search_tool_timeout_s=0.0,
            agent_analysis_tool_timeout_s=0.0,
            agent_action_tool_timeout_s=0.0,
        )

        errors = []

        def worker(idx):
            try:
                cfg = config_a if idx % 2 == 0 else config_b
                for _ in range(25):
                    reg = factory.get_tool_registry(cfg)
                    assert reg is not None
            except Exception as exc:  # pragma: no cover
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"concurrent get_tool_registry raised: {errors}"


# ---------------------------------------------------------------------------
# 9. Maintainer review follow-up: cooperative cancel + local-registry return
# ---------------------------------------------------------------------------
class TestTimeoutCooperativeCancel:
    """Blocker: a tool handler may keep running after its timeout fires (Python
    cannot forcibly stop an already-started thread).  The runner must (a) mark
    the result non-retriable (covered by ``TestTimeoutResultNonRetriable``) and
    (b) arm a cooperative-cancel signal that opt-in handlers can poll via
    ``is_tool_cancellation_requested`` so they can abort early.
    """

    def test_helper_defaults_false(self):
        from src.agent.tools.execution import is_tool_cancellation_requested

        assert is_tool_cancellation_requested() is False

    def test_helper_true_when_armed(self):
        from src.agent.tools.execution import (
            TOOL_CANCEL_EVENT,
            is_tool_cancellation_requested,
        )

        import threading

        event = threading.Event()
        token = TOOL_CANCEL_EVENT.set(event)
        try:
            assert is_tool_cancellation_requested() is False
            event.set()
            assert is_tool_cancellation_requested() is True
        finally:
            TOOL_CANCEL_EVENT.reset(token)

    def test_runner_arms_cancel_on_timeout(self):
        from src.agent.tools.execution import is_tool_cancellation_requested

        import time as _time

        captured = {"requested": None}

        def slow_handler(**kwargs):
            # Poll cancellation the way an opt-in handler would.
            deadline = _time.time() + 3.0
            while _time.time() < deadline:
                if is_tool_cancellation_requested():
                    captured["requested"] = True
                    return {"ok": True}
                _time.sleep(0.02)
            captured["requested"] = is_tool_cancellation_requested()
            return {"ok": True}

        reg = ToolRegistry()
        reg.register(ToolDefinition(
            name="slow_tool", description="s", parameters=[],
            handler=slow_handler, category="data",
        ))
        tool_calls = [SimpleNamespace(name="slow_tool", arguments={})]
        results = _execute_tools(
            tool_calls, reg, 1, None, [],
            non_retriable_tool_results={},
            tool_wait_timeout_seconds=0.1,
        )
        # Give the still-running background handler time to observe the armed signal.
        _time.sleep(0.8)
        assert len(results) == 1
        parsed = json.loads(results[0]["result_str"])
        assert parsed.get("timeout") is True
        assert parsed.get("retriable") is False
        assert captured["requested"] is True

    def test_check_tool_execution_honors_runner_cancel(self):
        """Regression: ``check_tool_execution()`` — the checkpoint real
        data/backtest/tool-surface tools already call — must observe the
        runner-armed ``TOOL_CANCEL_EVENT`` and abort a timed-out handler early,
        instead of letting it run to completion in the background thread.
        """
        from src.agent.tools.execution import check_tool_execution

        import time as _time

        captured = {"completed": False}

        def slow_handler(**kwargs):
            # Poll the checkpoint the way data_tools / backtest_tools do.
            deadline = _time.time() + 3.0
            while _time.time() < deadline:
                check_tool_execution()
                _time.sleep(0.02)
            captured["completed"] = True
            return {"ok": True}

        reg = ToolRegistry()
        reg.register(ToolDefinition(
            name="checkpoint_tool", description="s", parameters=[],
            handler=slow_handler, category="data",
        ))
        tool_calls = [SimpleNamespace(name="checkpoint_tool", arguments={})]
        results = _execute_tools(
            tool_calls, reg, 1, None, [],
            non_retriable_tool_results={},
            tool_wait_timeout_seconds=0.1,
        )
        # The handler aborts at its next checkpoint shortly after the 0.1s
        # timeout; it must NOT run its full 3s body to completion.
        _time.sleep(0.8)
        assert len(results) == 1
        parsed = json.loads(results[0]["result_str"])
        assert parsed.get("timeout") is True
        assert captured["completed"] is False


class TestGetToolRegistryReturnsLocalRegistry:
    """Blocker: ``get_tool_registry`` must return the registry it just built for
    the caller's timeout map (not the shared global), so a concurrent rebuild
    for a different ``Config`` cannot leak a mismatched registry into this call.
    """

    @pytest.fixture(autouse=True)
    def _isolate(self):
        from src.agent import factory

        saved_registry = factory._TOOL_REGISTRY
        saved_timeout_map = factory._CACHED_TIMEOUT_MAP
        factory.reset_tool_registry()
        try:
            yield
        finally:
            factory._TOOL_REGISTRY = saved_registry
            factory._CACHED_TIMEOUT_MAP = saved_timeout_map

    def test_returns_locally_built_registry(self, monkeypatch):
        from src.agent import factory

        sentinel = ToolRegistry({"data": 11})
        monkeypatch.setattr(factory, "_build_tool_registry", lambda m: sentinel)
        cfg = SimpleNamespace(agent_data_tool_timeout_s=11)
        assert factory.get_tool_registry(cfg) is sentinel
