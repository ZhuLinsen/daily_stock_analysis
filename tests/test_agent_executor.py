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
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Keep this test runnable when optional LLM runtime deps are not installed.
try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from src.agent.executor import (
    AGENT_SYSTEM_PROMPT,
    LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT,
    AgentExecutor,
    AgentResult,
)
from src.agent.llm_adapter import LLMResponse, ToolCall
from src.agent.runner import parse_dashboard_json, run_agent_loop, serialize_tool_result
from src.agent.tools.registry import ToolRegistry, ToolDefinition, ToolParameter
from src.analysis_context_pack_prompt import format_analysis_context_pack_prompt_section
from src.config import Config
from src.services.analysis_context_builder import (
    AnalysisContextBuilder,
    PipelineAnalysisArtifacts,
)
from src.storage import DatabaseManager


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


def _build_analysis_context_pack_summary(
    *,
    realtime_quote=None,
    fundamental_context=None,
) -> str:
    artifacts = PipelineAnalysisArtifacts(
        code="600519",
        stock_name="贵州茅台",
        market="cn",
        phase=None,
        base_context={
            "today": {"close": 1880.0},
            "yesterday": {"close": 1870.0},
            "date": "2026-03-26",
        },
        enhanced_context={},
        realtime_quote=realtime_quote
        if realtime_quote is not None
        else {"price": 1880.0, "source": "mock_quote"},
        trend_result={"trend_status": "available"},
        chip_data={"source": "mock_chip", "date": "2026-03-26"},
        fundamental_context=fundamental_context
        if fundamental_context is not None
        else {
            "status": "ok",
            "coverage": {"valuation": "ok"},
            "source_chain": [{"provider": "fundamental_pipeline"}],
        },
        news_context="新闻摘要",
        news_result_count=1,
        metadata={"trigger_source": "api"},
    )
    return format_analysis_context_pack_prompt_section(
        AnalysisContextBuilder.build(artifacts),
        report_language="zh",
    )


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


def test_agent_system_prompts_require_phase_decision_contract() -> None:
    for prompt in (LEGACY_DEFAULT_AGENT_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT):
        assert '"phase_decision"' in prompt
        assert '"watch_conditions"' in prompt
        assert '"data_limitations"' in prompt
        assert "quote/daily_bars/technical 存在 stale、fallback、missing、fetch_failed、partial 或 estimated" in prompt
        assert "`confidence_level` 不得为高" in prompt


# ============================================================
# AgentExecutor Tests
# ============================================================

class TestAgentExecutor(unittest.TestCase):
    """Test the ReAct loop logic."""

    def test_chat_injects_compressed_history_before_report_context_and_current_user(self):
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()
        adapter._config = MagicMock()
        executor = AgentExecutor(registry, adapter, max_steps=2)
        captured = {}

        def fake_run_loop(messages, tool_decls, parse_dashboard, progress_callback=None):
            captured["messages"] = messages
            return AgentResult(success=True, content="assistant reply")

        compressed_history = [
            {"role": "user", "content": "[系统生成的历史对话摘要，仅供延续本会话]\n旧摘要"},
            {"role": "assistant", "content": "最近回复"},
        ]

        with patch.object(executor, "_run_loop", side_effect=fake_run_loop):
            with patch(
                "src.agent.executor.build_agent_chat_context_bundle",
                return_value=SimpleNamespace(context_messages=compressed_history, diagnostics={}),
            ):
                with patch("src.agent.conversation.conversation_manager.get_or_create"):
                    with patch("src.agent.conversation.conversation_manager.add_message"):
                        executor.chat(
                            "当前问题",
                            "session-1",
                            context={
                                "stock_code": "600519",
                                "stock_name": "贵州茅台",
                                "previous_price": 1800,
                            },
                        )

        messages = captured["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1:3] == compressed_history
        assert messages[3]["role"] == "user"
        assert messages[3]["content"].startswith("[系统提供的历史分析上下文，可供参考对比]")
        assert messages[4]["role"] == "assistant"
        assert messages[-1] == {"role": "user", "content": "当前问题"}

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

    def test_run_agent_loop_replays_reasoning_and_provider_specific_fields_on_followup_call(self):
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()
        adapter.call_with_tools.side_effect = [
            LLMResponse(
                content="Checking.",
                tool_calls=[
                    ToolCall(
                        id="call_reason",
                        name="echo",
                        arguments={"message": "hello"},
                        thought_signature="sig-1",
                        provider_specific_fields={"thought_signature": "sig-1", "extra": "keep"},
                    )
                ],
                reasoning_content="deepseek reasoning",
                usage={"total_tokens": 10},
                provider="deepseek",
                model="deepseek/deepseek-chat",
            ),
            LLMResponse(
                content=json.dumps(SAMPLE_DASHBOARD, ensure_ascii=False),
                tool_calls=[],
                usage={"total_tokens": 20},
                provider="deepseek",
                model="deepseek/deepseek-chat",
            ),
        ]

        result = run_agent_loop(
            messages=[{"role": "user", "content": "Analyze"}],
            tool_registry=registry,
            llm_adapter=adapter,
            max_steps=2,
        )

        self.assertTrue(result.success)
        followup_messages = adapter.call_with_tools.call_args_list[1].args[0]
        assistant_msg = followup_messages[-2]
        tool_msg = followup_messages[-1]
        self.assertEqual(assistant_msg["role"], "assistant")
        self.assertEqual(assistant_msg["reasoning_content"], "deepseek reasoning")
        self.assertEqual(assistant_msg["_trace_provider"], "deepseek")
        self.assertEqual(assistant_msg["_trace_model"], "deepseek/deepseek-chat")
        self.assertEqual(
            assistant_msg["tool_calls"][0]["provider_specific_fields"],
            {"thought_signature": "sig-1", "extra": "keep"},
        )
        self.assertEqual(assistant_msg["tool_calls"][0]["thought_signature"], "sig-1")
        self.assertEqual(tool_msg["role"], "tool")
        self.assertEqual(tool_msg["tool_call_id"], "call_reason")

    def test_chat_persists_single_provider_trace_and_reinjects_without_duplication(self):
        DatabaseManager.reset_instance()
        Config.reset_instance()
        db = DatabaseManager(db_url="sqlite:///:memory:")
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()
        adapter._config = SimpleNamespace(
            agent_context_compression_enabled=False,
            agent_context_compression_profile="balanced",
            agent_context_compression_trigger_tokens=999999,
            agent_context_protected_turns=1,
            llm_model_list=[],
            agent_litellm_model="deepseek/deepseek-chat",
            litellm_model="deepseek/deepseek-chat",
            litellm_fallback_models=[],
        )
        adapter.call_with_tools.side_effect = [
            LLMResponse(
                content="Checking.",
                tool_calls=[ToolCall(id="call_1", name="echo", arguments={"message": "first"})],
                reasoning_content="r1",
                usage={"total_tokens": 10},
                provider="deepseek",
                model="deepseek/deepseek-chat",
            ),
            LLMResponse(
                content="first final",
                tool_calls=[],
                usage={"total_tokens": 5},
                provider="deepseek",
                model="deepseek/deepseek-chat",
            ),
            LLMResponse(
                content="second final",
                tool_calls=[],
                usage={"total_tokens": 5},
                provider="deepseek",
                model="deepseek/deepseek-chat",
            ),
        ]

        executor = AgentExecutor(registry, adapter, max_steps=3)

        first = executor.chat("first question", "executor-trace")
        second = executor.chat("second question", "executor-trace")

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertEqual(len(db.get_agent_provider_turns("executor-trace")), 1)
        second_request_messages = adapter.call_with_tools.call_args_list[2].args[0]
        ordered_roles = [msg["role"] for msg in second_request_messages[-5:]]
        self.assertEqual(ordered_roles, ["user", "assistant", "tool", "assistant", "user"])
        self.assertEqual(second_request_messages[-4]["reasoning_content"], "r1")
        self.assertEqual(second_request_messages[-3]["tool_call_id"], "call_1")
        self.assertEqual(second_request_messages[-2]["content"], "first final")
        self.assertEqual(second_request_messages[-1]["content"], "second question")

        DatabaseManager.reset_instance()
        Config.reset_instance()

    def test_persist_provider_trace_logs_save_failure_without_failing_chat(self):
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()
        executor = AgentExecutor(registry, adapter, max_steps=2)
        messages = [
            {"role": "user", "content": "question"},
            {
                "role": "assistant",
                "content": "checking",
                "_trace_provider": "deepseek",
                "_trace_model": "deepseek/deepseek-chat",
                "reasoning_content": "r1",
                "tool_calls": [{"id": "call_1", "name": "echo", "arguments": {"message": "x"}}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "tool-result"},
        ]
        db = SimpleNamespace(save_agent_provider_turn=MagicMock(side_effect=RuntimeError("db down")))

        with patch("src.agent.executor.get_db", return_value=db):
            with self.assertLogs("src.agent.executor", level="WARNING") as logs:
                executor._persist_provider_trace(
                    session_id="executor-trace-fail-open",
                    run_id="run-1",
                    messages=messages,
                    baseline_len=1,
                    user_message_id=10,
                    assistant_message_id=11,
                )

        self.assertIn("Provider trace persistence failed", "\n".join(logs.output))

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

    def test_error_provider_preserves_failure_reason_in_agent_result(self):
        """LLM adapter error responses must surface as failed Agent results, not final answers."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()
        adapter.call_with_tools.return_value = LLMResponse(
            content="No LLM configured. Please set LITELLM_MODEL, LLM_CHANNELS, or provider API keys before using Agent.",
            tool_calls=[],
            usage={"total_tokens": 1},
            provider="error",
            model="",
        )

        executor = AgentExecutor(registry, adapter, max_steps=2)
        result = executor.run("Analyze 600519")

        self.assertFalse(result.success)
        self.assertEqual(result.content, "")
        self.assertEqual(
            result.error,
            "No LLM configured. Please set LITELLM_MODEL, LLM_CHANNELS, or provider API keys before using Agent.",
        )
        self.assertEqual(result.total_steps, 1)
        self.assertEqual(result.total_tokens, 1)
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
        with patch("src.agent.runner.time.time", return_value=1000.0):
            result = executor.run("Analyze 600519")

        self.assertTrue(result.success)
        self.assertIsNotNone(captured.get("timeout"))
        self.assertGreater(captured["timeout"], 0.0)
        self.assertLessEqual(captured["timeout"], 1.0)

    def test_min_step_budget_skips_followup_llm_call(self):
        """When step>0 and remaining budget is too small, no extra LLM call should be made."""
        registry = _make_registry_with_echo()
        adapter = _make_mock_adapter()
        adapter.call_with_tools.return_value = LLMResponse(
            content="Need one tool first.",
            tool_calls=[ToolCall(id="echo_1", name="echo", arguments={"message": "hello"})],
            usage={"total_tokens": 10},
            provider="openai",
        )

        with patch(
            "src.agent.runner._remaining_timeout_seconds",
            side_effect=[9.0, 9.0, 7.5, 7.5],
        ):
            result = run_agent_loop(
                messages=[
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": "Analyze"},
                ],
                tool_registry=registry,
                llm_adapter=adapter,
                max_steps=3,
                max_wall_clock_seconds=10.0,
            )

        self.assertFalse(result.success)
        self.assertIn("insufficient budget", (result.error or "").lower())
        self.assertEqual(adapter.call_with_tools.call_count, 1)
        self.assertEqual(len(result.tool_calls_log), 1)
        self.assertEqual(result.total_steps, 1)


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

    def test_message_renders_readable_market_phase_context_without_raw_keys(self):
        summary = _build_analysis_context_pack_summary(
            realtime_quote={
                "price": 1880.0,
                "source": "fallback",
                "fallback_from": "primary_realtime_provider",
            },
        )
        msg = self.executor._build_user_message(
            "Analyze",
            context={
                "stock_code": "600519",
                "report_language": "zh",
                "market_phase_context": {
                    "phase": "intraday",
                    "market": "cn",
                    "market_local_time": "2026-03-27T10:00:00+08:00",
                    "effective_daily_bar_date": "2026-03-26",
                    "is_partial_bar": True,
                },
                "analysis_context_pack_summary": summary,
                "realtime_quote": {"price": 1880.0},
            },
        )
        self.assertIn("股票代码: 600519", msg)
        self.assertIn("市场阶段上下文", msg)
        self.assertIn("分析上下文包摘要", msg)
        self.assertIn("数据限制", msg)
        self.assertIn("已知限制：行情：降级", msg)
        self.assertIn("confidence_level 不得为高", msg)
        self.assertIn("盘中", msg)
        self.assertIn("不得当作完整日线复盘", msg)
        self.assertLess(msg.index("市场阶段上下文"), msg.index("分析上下文包摘要"))
        self.assertLess(msg.index("分析上下文包摘要"), msg.index("[系统已获取的实时行情]"))
        self.assertNotIn("market_phase_context", msg)
        self.assertNotIn("analysis_context_pack_summary", msg)
        self.assertNotIn("is_partial_bar", msg)
        self.assertNotIn("is_market_open_now", msg)


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
