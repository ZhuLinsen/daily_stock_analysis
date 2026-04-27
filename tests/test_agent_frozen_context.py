# -*- coding: utf-8 -*-
"""Verify that runner._execute_tools propagates ContextVar state (Issue #1066)."""
from __future__ import annotations

import json
import threading
import unittest
from datetime import date

from src.agent.tools.registry import ToolDefinition, ToolRegistry
from src.services.history_loader import (
    get_frozen_target_date,
    reset_frozen_target_date,
    set_frozen_target_date,
)


class _FakeToolCall:
    """Minimal stand-in for the ToolCall dataclass used by runner."""

    def __init__(self, name: str, arguments: dict | None = None):
        self.name = name
        self.arguments = arguments or {}
        self.id = f"fake_{name}"


def _make_spy_registry(tool_names: list[str], observed: list):
    """Build a ToolRegistry with spy tools that record frozen_target_date."""

    def _spy_handler(**kwargs):
        observed.append(get_frozen_target_date())
        return json.dumps({"ok": True})

    registry = ToolRegistry()
    for name in tool_names:
        td = ToolDefinition(name=name, description="spy", parameters=[], handler=_spy_handler)
        registry.register(td)
    return registry


class ExecuteToolsFrozenContextTestCase(unittest.TestCase):
    """Test ContextVar propagation through _execute_tools ThreadPoolExecutor."""

    def test_contextvar_propagates_to_single_tool_thread(self):
        """Single-tool path with timeout uses copy_context().run()."""
        from src.agent.runner import _execute_tools

        frozen_date = date(2026, 4, 15)
        observed: list[date | None] = []
        registry = _make_spy_registry(["spy_tool"], observed)

        tc = _FakeToolCall("spy_tool")
        token = set_frozen_target_date(frozen_date)
        try:
            _execute_tools(
                tool_calls=[tc],
                tool_registry=registry,
                step=1,
                progress_callback=None,
                tool_calls_log=[],
                tool_wait_timeout_seconds=5.0,
            )
        finally:
            reset_frozen_target_date(token)

        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0], frozen_date)

    def test_contextvar_propagates_to_parallel_tool_threads(self):
        """Multi-tool path propagates ContextVar to all concurrent worker threads.

        Uses a Barrier to force genuine overlap: every spy handler blocks
        until all workers have entered ctx.run(), so if a shared Context
        were reused the second enter would raise RuntimeError.
        """
        from src.agent.runner import _execute_tools

        frozen_date = date(2026, 4, 16)
        num_tools = 3
        barrier = threading.Barrier(num_tools, timeout=5)
        observed: list[date | None] = []

        def _slow_spy(**kwargs):
            barrier.wait()
            observed.append(get_frozen_target_date())
            return json.dumps({"ok": True})

        registry = ToolRegistry()
        names = [f"spy_{i}" for i in range(num_tools)]
        for name in names:
            td = ToolDefinition(name=name, description="spy", parameters=[], handler=_slow_spy)
            registry.register(td)

        tool_calls = [_FakeToolCall(n) for n in names]
        token = set_frozen_target_date(frozen_date)
        try:
            _execute_tools(
                tool_calls=tool_calls,
                tool_registry=registry,
                step=1,
                progress_callback=None,
                tool_calls_log=[],
                tool_wait_timeout_seconds=10.0,
            )
        finally:
            reset_frozen_target_date(token)

        self.assertEqual(len(observed), num_tools)
        self.assertTrue(all(d == frozen_date for d in observed))


if __name__ == "__main__":
    unittest.main()
