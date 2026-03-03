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
import unittest
import sys
import os
from dataclasses import dataclass
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.agent.executor import AgentExecutor, AgentResult
from src.agent.llm_adapter import LLMResponse, ToolCall
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
        self.assertFalse(result.tool_calls_log[0]["success"])


# ============================================================
# Dashboard parsing
# ============================================================

class TestDashboardParsing(unittest.TestCase):
    """Test _parse_dashboard with various input formats."""

    def setUp(self):
        self.executor = AgentExecutor(
            ToolRegistry(), _make_mock_adapter(), max_steps=1
        )

    def test_parse_markdown_json_block(self):
        content = f"Here is my analysis:\n```json\n{json.dumps(SAMPLE_DASHBOARD)}\n```\nDone."
        result = self.executor._parse_dashboard(content)
        self.assertIsNotNone(result)
        self.assertEqual(result["sentiment_score"], 75)

    def test_parse_raw_json(self):
        content = json.dumps(SAMPLE_DASHBOARD)
        result = self.executor._parse_dashboard(content)
        self.assertIsNotNone(result)

    def test_parse_json_in_text(self):
        content = f"Let me present: {json.dumps(SAMPLE_DASHBOARD)} — that's all."
        result = self.executor._parse_dashboard(content)
        self.assertIsNotNone(result)

    def test_parse_empty_content(self):
        self.assertIsNone(self.executor._parse_dashboard(""))
        self.assertIsNone(self.executor._parse_dashboard(None))

    def test_parse_no_json(self):
        self.assertIsNone(self.executor._parse_dashboard("This is just plain text with no JSON"))


# ============================================================
# Serialization
# ============================================================

class TestSerializeToolResult(unittest.TestCase):
    """Test _serialize_tool_result for various types."""

    def setUp(self):
        self.executor = AgentExecutor(
            ToolRegistry(), _make_mock_adapter(), max_steps=1
        )

    def test_serialize_none(self):
        result = self.executor._serialize_tool_result(None)
        self.assertEqual(json.loads(result), {"result": None})

    def test_serialize_string(self):
        result = self.executor._serialize_tool_result("hello")
        self.assertEqual(result, "hello")

    def test_serialize_dict(self):
        d = {"key": "value", "num": 42}
        result = self.executor._serialize_tool_result(d)
        self.assertEqual(json.loads(result), d)

    def test_serialize_list(self):
        lst = [1, 2, 3]
        result = self.executor._serialize_tool_result(lst)
        self.assertEqual(json.loads(result), lst)

    def test_serialize_dataclass(self):
        @dataclass
        class Sample:
            name: str = "test"
            value: int = 42

        result = self.executor._serialize_tool_result(Sample())
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
