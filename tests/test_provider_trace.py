# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.agent.provider_trace import (  # noqa: E402
    extract_provider_trace_turns,
    provider_namespace,
    resolved_model_provider_identity,
    resolved_provider_namespace,
    trace_model_matches,
)


def test_trace_model_matches_slashless_openai_namespace_without_widening_model_match() -> None:
    assert provider_namespace("gpt-4o-mini") == "openai"
    assert trace_model_matches("openai", "gpt-4o-mini", "gpt-4o-mini") is True
    assert trace_model_matches("anthropic", "gpt-4o-mini", "gpt-4o-mini") is False
    assert trace_model_matches("openai", "gpt-4o-mini", "openai/gpt-4o-mini") is False
    assert trace_model_matches(
        "anthropic",
        "claude-router",
        "claude-router",
        current_provider="anthropic",
    ) is True


def test_resolved_provider_namespace_uses_router_alias_before_slashless_default() -> None:
    model_list = [
        {
            "model_name": "claude-router",
            "litellm_params": {"model": "anthropic/claude-sonnet-test"},
        }
    ]

    assert resolved_provider_namespace("claude-router", model_list) == "anthropic"
    assert resolved_provider_namespace("gpt-4o-mini", model_list) == "openai"


def test_resolved_model_provider_identity_returns_wire_model_and_provider() -> None:
    model_list = [
        {
            "model_name": "fast",
            "litellm_params": {"model": "openai/gpt-4o"},
        }
    ]

    assert resolved_model_provider_identity("fast", model_list) == ("openai/gpt-4o", "openai")
    assert resolved_model_provider_identity("gpt-4o-mini", model_list) == ("gpt-4o-mini", "openai")


def test_extract_trace_scans_only_current_run_and_keeps_multi_step_tool_loop() -> None:
    messages = [
        {
            "role": "assistant",
            "_trace_provider": "deepseek",
            "_trace_model": "deepseek/deepseek-chat",
            "reasoning_content": "old",
            "tool_calls": [{"id": "old", "name": "echo", "arguments": {}}],
        },
        {"role": "tool", "tool_call_id": "old", "content": "old-result"},
        {"role": "user", "content": "current"},
        {
            "role": "assistant",
            "_trace_provider": "deepseek",
            "_trace_model": "deepseek/deepseek-chat",
            "content": "step1",
            "reasoning_content": "r1",
            "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "result1"},
        {
            "role": "assistant",
            "_trace_provider": "deepseek",
            "_trace_model": "deepseek/deepseek-chat",
            "content": "step2",
            "reasoning_content": "r2",
            "tool_calls": [{"id": "c2", "name": "echo", "arguments": {}}],
        },
        {"role": "tool", "tool_call_id": "c2", "content": "result2"},
    ]

    turns, diagnostics = extract_provider_trace_turns(
        messages,
        baseline_len=3,
        run_id="run-1",
        anchor_user_message_id=10,
        anchor_assistant_message_id=11,
    )

    assert diagnostics.trace_dropped_reason == ""
    assert len(turns) == 1
    assert [msg["role"] for msg in turns[0].messages] == ["assistant", "tool", "assistant", "tool"]
    assert turns[0].messages[0]["reasoning_content"] == "r1"
    assert turns[0].messages[2]["reasoning_content"] == "r2"
    assert "_trace_provider" not in turns[0].messages[0]
    assert turns[0].must_roundtrip is True


def test_extract_trace_drops_deepseek_without_required_tool_reasoning_pair_and_mixed_model() -> None:
    no_tool_turns, no_tool_diag = extract_provider_trace_turns(
        [
            {"role": "user", "content": "u"},
            {
                "role": "assistant",
                "_trace_provider": "deepseek",
                "_trace_model": "deepseek/deepseek-chat",
                "reasoning_content": "reasoning-only",
                "content": "final",
            },
        ],
        baseline_len=1,
    )

    assert no_tool_turns == []
    assert no_tool_diag.trace_dropped_reason == ""

    no_reasoning_turns, no_reasoning_diag = extract_provider_trace_turns(
        [
            {"role": "user", "content": "u"},
            {
                "role": "assistant",
                "_trace_provider": "deepseek",
                "_trace_model": "deepseek/deepseek-chat",
                "tool_calls": [
                    {
                        "id": "c0",
                        "name": "echo",
                        "arguments": {},
                        "provider_specific_fields": {"extra": "not-enough"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c0", "content": "result"},
        ],
        baseline_len=1,
    )

    assert no_reasoning_turns == []
    assert no_reasoning_diag.trace_dropped_reason == "not_required"

    mixed_turns, mixed_diag = extract_provider_trace_turns(
        [
            {"role": "user", "content": "u"},
            {
                "role": "assistant",
                "_trace_provider": "deepseek",
                "_trace_model": "deepseek/deepseek-chat",
                "reasoning_content": "r1",
                "tool_calls": [{"id": "c1", "name": "echo", "arguments": {}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "result1"},
            {
                "role": "assistant",
                "_trace_provider": "deepseek",
                "_trace_model": "deepseek/deepseek-reasoner",
                "reasoning_content": "r2",
                "tool_calls": [{"id": "c2", "name": "echo", "arguments": {}}],
            },
        ],
        baseline_len=1,
    )

    assert mixed_turns == []
    assert mixed_diag.mixed_model_trace is True
    assert mixed_diag.trace_dropped_reason == "mixed_model_trace"
