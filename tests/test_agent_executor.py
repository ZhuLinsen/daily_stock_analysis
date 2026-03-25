# -*- coding: utf-8 -*-
"""
Tests for AgentExecutor with mocked LLM adapter.

Covers:
- ReAct loop: tool-calling → result feedback → final answer
- Dashboard JSON parsing (markdown blocks, raw JSON, json_repair)
- Max step limit
- Tool execution error handling
- _serialize_tool_result for various types
- _build_user_message formatting
"""

import json
import time
import unittest
import sys
import os
from dataclasses import dataclass
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Keep this test runnable when optional LLM runtime deps are not installed.
try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from src.agent.executor import AgentExecutor, AgentResult
from src.agent.llm_adapter import LLMResponse, ToolCall
from src.agent.runner import parse_dashboard_json, run_agent_loop, serialize_tool_result
from src.agent.tools.registry import ToolRegistry, ToolDefinition, ToolParameter


# ============================================================
# Helpers
# ============================================================

def _make_registry_with_echo():
    """Create a registry with a simple echo tool."""
    registry = ToolRegistry()
    tool = ToolDefinition(
        name="echo",
        description="Echoes back the input",
        parameters=[
            ToolParameter(name="message", type="string", description="Message to echo"),
        ],
        handler=lambda message: {"echo": message},
    )
    registry.register(tool)
    return registry


def _make_mock_adapter():
    """Create a MagicMock LLMToolAdapter."""
    adapter = MagicMock()
    return adapter


SAMPLE_DASHBOARD = {
    "stock_name": "贵州茅台",
    "sentiment_score": 75,
    "trend_prediction": "看多",
    "operation_advice": "持有",
    "decision_type": "hold",
    "confidence_level": "中",
    "dashboard": {
        "core_conclusion": {
            "one_sentence": "茅台近期震荡走强",
            "signal_type": "🟡持有观望",
        },
    },
    "analysis_summary": "Overall bullish trend",
    "key_points": "Strong revenue growth",
    "risk_warning": "High valuation",
    "buy_reason": "Sector leader",
    "trend_analysis": "Upward trend",
    "technical_analysis": "MACD golden cross",
}


# ============================================================
# AgentExecutor Tests
# ============================================================

class TestAgentExecutor(unittest.TestCase):
    """Test the ReAct loop logic."""

    def test_prompt_omits_hardcoded_trend_baseline_when_default_policy_is_empty(self):
        """Explicit skill runs should not silently keep the legacy trend baseline."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()
        adapter.call_with_tools.return_value = LLMResponse(
            content=json.dumps(SAMPLE_DASHBOARD, ensure_ascii=False),
            tool_calls=[],
            usage={"total_tokens": 50},
            provider="openai",
        )

        executor = AgentExecutor(
            registry,
            adapter,
            skill_instructions="### 技能 1: 缠论\n- 关注中枢与背驰",
            default_skill_policy="",
            max_steps=2,
        )
        result = executor.run("Analyze 600519")

        self.assertTrue(result.success)
        prompt = adapter.call_with_tools.call_args.args[0][0]["content"]
        self.assertIn("### 技能 1: 缠论", prompt)
        self.assertNotIn("专注于趋势交易", prompt)
        self.assertNotIn("多头排列：MA5 > MA10 > MA20", prompt)

    def test_prompt_keeps_injected_default_policy_for_implicit_default_run(self):
        """Implicit default runs can still inject the default bull-trend baseline explicitly."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()
        adapter.call_with_tools.return_value = LLMResponse(
            content=json.dumps(SAMPLE_DASHBOARD, ensure_ascii=False),
            tool_calls=[],
            usage={"total_tokens": 50},
            provider="openai",
        )

        executor = AgentExecutor(
            registry,
            adapter,
            skill_instructions="### 技能 1: 默认多头趋势",
            default_skill_policy="## 默认技能基线（必须严格遵守）\n- **多头排列必须条件**：MA5 > MA10 > MA20",
            use_legacy_default_prompt=True,
            max_steps=2,
        )
        result = executor.run("Analyze 600519")

        self.assertTrue(result.success)
        prompt = adapter.call_with_tools.call_args.args[0][0]["content"]
        self.assertIn("### 技能 1: 默认多头趋势", prompt)
        self.assertIn("专注于趋势交易", prompt)
        self.assertIn("多头排列必须条件", prompt)
        self.assertIn("多头排列：MA5 > MA10 > MA20", prompt)

    def test_simple_text_response(self):
        """Agent returns text immediately (no tool calls) with JSON dashboard."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()

        # LLM returns a text response with the dashboard JSON
        adapter.call_with_tools.return_value = LLMResponse(
            content=json.dumps(SAMPLE_DASHBOARD, ensure_ascii=False),
            tool_calls=[],
            usage={"total_tokens": 100},
            provider="openai",
        )

        executor = AgentExecutor(registry, adapter, max_steps=5)
        result = executor.run("Analyze 600519")

        self.assertTrue(result.success)
        self.assertIsNotNone(result.dashboard)
        self.assertEqual(result.dashboard["sentiment_score"], 75)
        self.assertEqual(result.total_steps, 1)
        self.assertEqual(result.provider, "openai")
        self.assertEqual(len(result.tool_calls_log), 0)

    def test_tool_call_then_text(self):
        """Agent calls a tool, gets result, then returns final answer."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()

        # Step 1: LLM requests tool call
        step1_response = LLMResponse(
            content="Let me check the data.",
            tool_calls=[
                ToolCall(id="call_1", name="echo", arguments={"message": "hello"}),
            ],
            usage={"total_tokens": 50},
            provider="gemini",
        )
        # Step 2: LLM returns final text
        step2_response = LLMResponse(
            content=json.dumps(SAMPLE_DASHBOARD, ensure_ascii=False),
            tool_calls=[],
            usage={"total_tokens": 80},
            provider="gemini",
        )
        adapter.call_with_tools.side_effect = [step1_response, step2_response]

        executor = AgentExecutor(registry, adapter, max_steps=5)
        result = executor.run("Analyze 600519")

        self.assertTrue(result.success)
        self.assertEqual(result.total_steps, 2)
        self.assertEqual(result.total_tokens, 130)
        self.assertEqual(len(result.tool_calls_log), 1)
        self.assertEqual(result.tool_calls_log[0]["tool"], "echo")
        self.assertTrue(result.tool_calls_log[0]["success"])

    def test_multiple_tool_calls_in_one_step(self):
        """Agent requests multiple tool calls in a single response."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()

        step1 = LLMResponse(
            content="Gathering data.",
            tool_calls=[
                ToolCall(id="c1", name="echo", arguments={"message": "a"}),
                ToolCall(id="c2", name="echo", arguments={"message": "b"}),
            ],
            usage={"total_tokens": 40},
            provider="openai",
        )
        step2 = LLMResponse(
            content=json.dumps(SAMPLE_DASHBOARD),
            tool_calls=[],
            usage={"total_tokens": 60},
            provider="openai",
        )
        adapter.call_with_tools.side_effect = [step1, step2]

        executor = AgentExecutor(registry, adapter, max_steps=5)
        result = executor.run("Analyze 600519")

        self.assertTrue(result.success)
        self.assertEqual(len(result.tool_calls_log), 2)

    def test_max_steps_exceeded(self):
        """Agent keeps calling tools until max_steps is hit."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()

        # Always return tool calls, never final text
        tool_response = LLMResponse(
            content="Still working.",
            tool_calls=[
                ToolCall(id="c1", name="echo", arguments={"message": "loop"}),
            ],
            usage={"total_tokens": 20},
            provider="openai",
        )
        adapter.call_with_tools.return_value = tool_response

        executor = AgentExecutor(registry, adapter, max_steps=3)
        result = executor.run("Analyze loop")

        self.assertFalse(result.success)
        self.assertIn("max steps", result.error.lower())
        self.assertEqual(result.total_steps, 3)

    def test_tool_execution_error(self):
        """Tool raises exception — should be logged and error sent to LLM."""
        def _always_fail():
            raise RuntimeError("db down")

        registry = ToolRegistry()
        tool = ToolDefinition(
            name="failing_tool",
            description="Always fails",
            parameters=[],
            handler=_always_fail,
        )
        registry.register(tool)
        adapter = _make_mock_adapter()

        step1 = LLMResponse(
            content="",
            tool_calls=[
                ToolCall(id="f1", name="failing_tool", arguments={}),
            ],
            usage={"total_tokens": 30},
            provider="openai",
        )
        step2 = LLMResponse(
            content=json.dumps(SAMPLE_DASHBOARD),
            tool_calls=[],
            usage={"total_tokens": 50},
            provider="openai",
        )
        adapter.call_with_tools.side_effect = [step1, step2]

        executor = AgentExecutor(registry, adapter, max_steps=5)
        result = executor.run("Test error handling")

        # Should still succeed overall (agent handles tool errors gracefully)
        self.assertTrue(result.success)
        # The failing tool call should be logged as failure
        self.assertEqual(len(result.tool_calls_log), 1)
        self.assertFalse(result.tool_calls_log[0]["success"])

    def test_unknown_tool_called(self):
        """LLM requests a tool not in the registry — should handle gracefully."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()

        step1 = LLMResponse(
            content="",
            tool_calls=[
                ToolCall(id="u1", name="nonexistent_tool", arguments={}),
            ],
            usage={"total_tokens": 20},
            provider="openai",
        )
        step2 = LLMResponse(
            content=json.dumps(SAMPLE_DASHBOARD),
            tool_calls=[],
            usage={"total_tokens": 50},
            provider="openai",
        )
        adapter.call_with_tools.side_effect = [step1, step2]

        executor = AgentExecutor(registry, adapter, max_steps=5)
        result = executor.run("Test unknown tool")

        self.assertTrue(result.success)
        self.assertEqual(len(result.tool_calls_log), 1)
        self.assertFalse(result.tool_calls_log[0]["success"])
        self.assertFalse(result.tool_calls_log[0]["cached"])

    def test_non_retriable_tool_failure_is_cached_across_hk_variants(self):
        """Equivalent HK code variants should not re-execute a non-retriable failing tool."""
        calls = []

        def _quote(stock_code):
            calls.append(stock_code)
            return {
                "error": f"No realtime quote available for {stock_code}",
                "retriable": False,
                "note": "Skip retry",
            }

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="get_realtime_quote",
                description="Get realtime quote",
                parameters=[
                    ToolParameter(name="stock_code", type="string", description="Stock code"),
                ],
                handler=_quote,
            )
        )
        adapter = _make_mock_adapter()

        adapter.call_with_tools.side_effect = [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="q1", name="get_realtime_quote", arguments={"stock_code": "hk01810"}),
                ],
                usage={"total_tokens": 10},
                provider="openai",
            ),
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="q2", name="get_realtime_quote", arguments={"stock_code": "1810.HK"}),
                ],
                usage={"total_tokens": 10},
                provider="openai",
            ),
            LLMResponse(
                content=json.dumps(SAMPLE_DASHBOARD, ensure_ascii=False),
                tool_calls=[],
                usage={"total_tokens": 10},
                provider="openai",
            ),
        ]

        executor = AgentExecutor(registry, adapter, max_steps=5)
        result = executor.run("Analyze HK01810")

        self.assertTrue(result.success)
        self.assertEqual(calls, ["hk01810"])
        self.assertEqual(len(result.tool_calls_log), 2)
        self.assertFalse(result.tool_calls_log[0]["cached"])
        self.assertTrue(result.tool_calls_log[1]["cached"])

    def test_model_trace_deduplicates_and_keeps_order(self):
        """Model trace should keep call order and de-duplicate repeated models."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()

        step1 = LLMResponse(
            content="first tool call",
            tool_calls=[ToolCall(id="m1", name="echo", arguments={"message": "a"})],
            usage={"total_tokens": 10},
            provider="gemini",
            model="gemini/gemini-2.0-flash",
        )
        step2 = LLMResponse(
            content="second tool call",
            tool_calls=[ToolCall(id="m2", name="echo", arguments={"message": "b"})],
            usage={"total_tokens": 10},
            provider="gemini",
            model="gemini/gemini-2.0-flash",
        )
        step3 = LLMResponse(
            content=json.dumps(SAMPLE_DASHBOARD, ensure_ascii=False),
            tool_calls=[],
            usage={"total_tokens": 10},
            provider="openai",
            model="openai/gpt-4o-mini",
        )
        adapter.call_with_tools.side_effect = [step1, step2, step3]

        executor = AgentExecutor(registry, adapter, max_steps=5)
        result = executor.run("Analyze 600519")

        self.assertTrue(result.success)
        self.assertEqual(result.model, "gemini/gemini-2.0-flash, openai/gpt-4o-mini")

    def test_model_trace_skips_error_provider(self):
        """Error provider placeholder should not appear in model trace."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()
        adapter.call_with_tools.return_value = LLMResponse(
            content="llm failed",
            tool_calls=[],
            usage={"total_tokens": 3},
            provider="error",
            model="",
        )

        executor = AgentExecutor(registry, adapter, max_steps=2)
        result = executor.run("Analyze 600519")

        self.assertFalse(result.success)
        self.assertEqual(result.model, "")

    def test_timeout_budget_aborts_single_agent_loop(self):
        """Single-agent executor should stop once the configured timeout budget is exhausted."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()

        def _slow_llm(*_args, **_kwargs):
            time.sleep(0.03)
            return LLMResponse(
                content=json.dumps(SAMPLE_DASHBOARD, ensure_ascii=False),
                tool_calls=[],
                usage={"total_tokens": 10},
                provider="openai",
            )

        adapter.call_with_tools.side_effect = _slow_llm

        executor = AgentExecutor(registry, adapter, max_steps=2, timeout_seconds=0.01)
        result = executor.run("Analyze 600519")

        self.assertFalse(result.success)
        self.assertIn("timed out", (result.error or "").lower())

    def test_parallel_tool_timeout_marks_only_pending_calls(self):
        """Parallel tool batches should emit timeout errors for unfinished tools."""
        registry = ToolRegistry()

        def _maybe_slow_echo(message):
            if message == "slow":
                time.sleep(0.05)
            return {"echo": message}

        registry.register(
            ToolDefinition(
                name="echo",
                description="Echoes back the input",
                parameters=[
                    ToolParameter(name="message", type="string", description="Message to echo"),
                ],
                handler=_maybe_slow_echo,
            )
        )
        adapter = _make_mock_adapter()
        adapter.call_with_tools.side_effect = [
            LLMResponse(
                content="Gathering data.",
                tool_calls=[
                    ToolCall(id="fast", name="echo", arguments={"message": "fast"}),
                    ToolCall(id="slow", name="echo", arguments={"message": "slow"}),
                ],
                usage={"total_tokens": 10},
                provider="openai",
            ),
            LLMResponse(
                content=json.dumps(SAMPLE_DASHBOARD, ensure_ascii=False),
                tool_calls=[],
                usage={"total_tokens": 10},
                provider="openai",
            ),
        ]

        result = run_agent_loop(
            messages=[
                {"role": "system", "content": "system"},
                {"role": "user", "content": "Analyze"},
            ],
            tool_registry=registry,
            llm_adapter=adapter,
            max_steps=3,
            tool_call_timeout_seconds=0.01,
        )

        self.assertTrue(result.success)
        self.assertEqual(len(result.tool_calls_log), 2)
        timeout_logs = [log for log in result.tool_calls_log if log.get("timeout")]
        self.assertEqual(len(timeout_logs), 1)
        self.assertEqual(timeout_logs[0]["arguments"]["message"], "slow")

    def test_single_tool_timeout_marks_tool_failed(self):
        """Single tool calls should also respect the configured tool timeout."""
        registry = ToolRegistry()

        def _slow_echo(message):
            time.sleep(0.05)
            return {"echo": message}

        registry.register(
            ToolDefinition(
                name="echo",
                description="Echoes back the input",
                parameters=[
                    ToolParameter(name="message", type="string", description="Message to echo"),
                ],
                handler=_slow_echo,
            )
        )
        adapter = _make_mock_adapter()
        adapter.call_with_tools.side_effect = [
            LLMResponse(
                content="Gathering data.",
                tool_calls=[ToolCall(id="slow", name="echo", arguments={"message": "slow"})],
                usage={"total_tokens": 10},
                provider="openai",
            ),
            LLMResponse(
                content=json.dumps(SAMPLE_DASHBOARD, ensure_ascii=False),
                tool_calls=[],
                usage={"total_tokens": 10},
                provider="openai",
            ),
        ]

        result = run_agent_loop(
            messages=[
                {"role": "system", "content": "system"},
                {"role": "user", "content": "Analyze"},
            ],
            tool_registry=registry,
            llm_adapter=adapter,
            max_steps=3,
            tool_call_timeout_seconds=0.01,
        )

        self.assertTrue(result.success)
        self.assertEqual(len(result.tool_calls_log), 1)
        self.assertTrue(result.tool_calls_log[0].get("timeout"))
        self.assertEqual(result.tool_calls_log[0]["arguments"]["message"], "slow")

    def test_llm_call_receives_remaining_timeout_budget(self):
        """LLM tool calls should receive the remaining wall-clock budget."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()
        captured = {}

        def _capture_timeout(*_args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return LLMResponse(
                content=json.dumps(SAMPLE_DASHBOARD, ensure_ascii=False),
                tool_calls=[],
                usage={"total_tokens": 10},
                provider="openai",
            )

        adapter.call_with_tools.side_effect = _capture_timeout

        executor = AgentExecutor(registry, adapter, max_steps=2, timeout_seconds=1.0)
        result = executor.run("Analyze 600519")

        self.assertTrue(result.success)
        self.assertIsNotNone(captured.get("timeout"))
        self.assertGreater(captured["timeout"], 0.0)
        self.assertLessEqual(captured["timeout"], 1.0)


# ============================================================
# Dashboard parsing
# ============================================================

class TestDashboardParsing(unittest.TestCase):
    """Test parse_dashboard_json with various input formats."""

    def test_parse_markdown_json_block(self):
        content = f"Here is my analysis:\n```json\n{json.dumps(SAMPLE_DASHBOARD)}\n```\nDone."
        result = parse_dashboard_json(content)
        self.assertIsNotNone(result)
        self.assertEqual(result["sentiment_score"], 75)

    def test_parse_raw_json(self):
        content = json.dumps(SAMPLE_DASHBOARD)
        result = parse_dashboard_json(content)
        self.assertIsNotNone(result)

    def test_parse_json_in_text(self):
        content = f"Let me present: {json.dumps(SAMPLE_DASHBOARD)} — that's all."
        result = parse_dashboard_json(content)
        self.assertIsNotNone(result)

    def test_parse_empty_content(self):
        self.assertIsNone(parse_dashboard_json(""))
        self.assertIsNone(parse_dashboard_json(None))

    def test_parse_no_json(self):
        self.assertIsNone(parse_dashboard_json("This is just plain text with no JSON"))


# ============================================================
# Serialization
# ============================================================

class TestSerializeToolResult(unittest.TestCase):
    """Test serialize_tool_result for various types."""

    def test_serialize_none(self):
        result = serialize_tool_result(None)
        self.assertEqual(json.loads(result), {"result": None})

    def test_serialize_string(self):
        result = serialize_tool_result("hello")
        self.assertEqual(result, "hello")

    def test_serialize_dict(self):
        d = {"key": "value", "num": 42}
        result = serialize_tool_result(d)
        self.assertEqual(json.loads(result), d)

    def test_serialize_list(self):
        lst = [1, 2, 3]
        result = serialize_tool_result(lst)
        self.assertEqual(json.loads(result), lst)

    def test_serialize_dataclass(self):
        @dataclass
        class Sample:
            name: str = "test"
            value: int = 42

        result = serialize_tool_result(Sample())
        parsed = json.loads(result)
        self.assertEqual(parsed["name"], "test")
        self.assertEqual(parsed["value"], 42)


# ============================================================
# User message builder
# ============================================================

class TestBuildUserMessage(unittest.TestCase):
    """Test _build_user_message formatting."""

    def setUp(self):
        self.executor = AgentExecutor(
            ToolRegistry(), _make_mock_adapter(), max_steps=1
        )

    def test_basic_message(self):
        msg = self.executor._build_user_message("Analyze 600519")
        self.assertIn("Analyze 600519", msg)
        self.assertIn("决策仪表盘", msg)

    def test_message_with_context(self):
        msg = self.executor._build_user_message(
            "Analyze",
            context={"stock_code": "600519", "report_type": "daily"},
        )
        self.assertIn("股票代码: 600519", msg)
        self.assertIn("报告类型: daily", msg)


# ============================================================
# AgentResult dataclass
# ============================================================

class TestAgentResult(unittest.TestCase):
    """Test AgentResult defaults."""

    def test_defaults(self):
        r = AgentResult()
        self.assertFalse(r.success)
        self.assertEqual(r.content, "")
        self.assertIsNone(r.dashboard)
        self.assertEqual(r.tool_calls_log, [])
        self.assertEqual(r.total_steps, 0)
        self.assertEqual(r.total_tokens, 0)
        self.assertIsNone(r.error)


if __name__ == '__main__':
    unittest.main()
