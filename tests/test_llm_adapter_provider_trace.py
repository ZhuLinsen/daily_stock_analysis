# -*- coding: utf-8 -*-
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.litellm_stub import ensure_litellm_stub, remove_litellm_stub

remove_litellm_stub()
try:
    from litellm.types.utils import Usage
except ModuleNotFoundError:
    ensure_litellm_stub()
    from litellm.types.utils import Usage

from src.agent.llm_adapter import LLMToolAdapter  # noqa: E402


def test_convert_messages_preserves_reasoning_blocks_and_provider_specific_fields() -> None:
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    messages = [
        {
            "role": "assistant",
            "content": "checking",
            "_trace_provider": "anthropic",
            "_trace_model": "anthropic/claude-test",
            "provider_blocks": [
                {"type": "thinking", "thinking": "opaque"},
                {"type": "redacted_thinking", "data": "redacted"},
                {"type": "text", "text": "checking"},
            ],
            "reasoning_content": "reasoning",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "echo",
                    "arguments": {"message": "hello"},
                    "thought_signature": "sig-1",
                    "provider_specific_fields": {"thought_signature": "sig-1", "extra": "keep"},
                }
            ],
        }
    ]

    converted = adapter._convert_messages(messages)

    assert converted[0]["role"] == "assistant"
    assert converted[0]["content"][0]["type"] == "thinking"
    assert converted[0]["reasoning_content"] == "reasoning"
    assert converted[0]["tool_calls"][0]["provider_specific_fields"] == {
        "thought_signature": "sig-1",
        "extra": "keep",
    }
    assert "_trace_provider" not in converted[0]


def test_convert_messages_only_sends_provider_trace_to_matching_target_model() -> None:
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    messages = [
        {
            "role": "assistant",
            "content": "checking",
            "_trace_provider": "anthropic",
            "_trace_model": "anthropic/claude-test",
            "provider_blocks": [{"type": "thinking", "thinking": "opaque"}],
            "reasoning_content": "provider-only",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "echo",
                    "arguments": {"message": "hello"},
                    "thought_signature": "sig-1",
                    "provider_specific_fields": {"thought_signature": "sig-1"},
                }
            ],
        }
    ]

    matching = adapter._convert_messages(messages, target_model="anthropic/claude-test")
    mismatched = adapter._convert_messages(messages, target_model="openai/gpt-4o-mini")

    assert matching[0]["content"] == [{"type": "thinking", "thinking": "opaque"}]
    assert matching[0]["reasoning_content"] == "provider-only"
    assert matching[0]["tool_calls"][0]["provider_specific_fields"] == {"thought_signature": "sig-1"}

    assert mismatched == []


def test_convert_messages_skips_entire_trace_segment_for_mismatched_attempt() -> None:
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    messages = [
        {"role": "user", "content": "u1"},
        {
            "role": "assistant",
            "content": "checking",
            "_trace_provider": "deepseek",
            "_trace_model": "deepseek/deepseek-chat",
            "reasoning_content": "provider-only",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "echo",
                    "arguments": {"message": "hello"},
                    "provider_specific_fields": {"thought_signature": "sig-1"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": "tool-result",
            "_trace_provider": "deepseek",
            "_trace_model": "deepseek/deepseek-chat",
        },
        {"role": "assistant", "content": "a1-final"},
    ]

    primary = adapter._convert_messages(messages, target_model="openai/gpt-4o-mini")
    fallback = adapter._convert_messages(messages, target_model="deepseek/deepseek-chat")

    assert [msg["role"] for msg in primary] == ["user", "assistant"]
    assert primary[-1]["content"] == "a1-final"
    assert all(msg.get("tool_call_id") != "call_1" for msg in primary)

    assert [msg["role"] for msg in fallback] == ["user", "assistant", "tool", "assistant"]
    assert fallback[1]["reasoning_content"] == "provider-only"
    assert fallback[1]["tool_calls"][0]["provider_specific_fields"] == {"thought_signature": "sig-1"}
    assert fallback[2]["tool_call_id"] == "call_1"


def test_convert_messages_matches_slashless_openai_target_without_provider_leakage() -> None:
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    messages = [
        {
            "role": "assistant",
            "content": "checking",
            "_trace_provider": "openai",
            "_trace_model": "gpt-4o-mini",
            "reasoning_content": "provider-only",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "echo",
                    "arguments": {},
                    "provider_specific_fields": {"thought_signature": "sig-1"},
                }
            ],
        }
    ]

    matching = adapter._convert_messages(messages, target_model="gpt-4o-mini")
    mismatched = adapter._convert_messages(messages, target_model="claude-router")

    assert matching[0]["reasoning_content"] == "provider-only"
    assert matching[0]["tool_calls"][0]["provider_specific_fields"] == {"thought_signature": "sig-1"}
    assert mismatched == []


def test_parse_litellm_response_extracts_claude_blocks_and_tool_provider_fields() -> None:
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    blocks = [
        {"type": "thinking", "thinking": "opaque"},
        {"type": "redacted_thinking", "data": "hidden"},
        {"type": "text", "text": "Need data"},
    ]
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=blocks,
                    reasoning_content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(
                                name="echo",
                                arguments='{"message": "hello"}',
                                provider_specific_fields=None,
                            ),
                            provider_specific_fields={"thought_signature": "sig-1", "extra": "keep"},
                        )
                    ],
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )

    parsed = adapter._parse_litellm_response(response, "anthropic/claude-test")

    assert parsed.content == "Need data"
    assert parsed.provider_blocks == blocks
    assert parsed.provider == "anthropic"
    assert parsed.model == "anthropic/claude-test"
    assert parsed.tool_calls[0].thought_signature == "sig-1"
    assert parsed.tool_calls[0].provider_specific_fields == {
        "thought_signature": "sig-1",
        "extra": "keep",
    }


def test_parse_litellm_response_resolves_provider_for_slashless_router_alias() -> None:
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    adapter._config = SimpleNamespace(
        llm_model_list=[
            {
                "model_name": "claude-router",
                "litellm_params": {"model": "anthropic/claude-sonnet-test"},
            }
        ]
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="ok",
                    reasoning_content=None,
                    tool_calls=[],
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )

    parsed_alias = adapter._parse_litellm_response(response, "claude-router")
    parsed_bare_openai = adapter._parse_litellm_response(response, "gpt-4o-mini")

    assert parsed_alias.provider == "anthropic"
    assert parsed_alias.model == "claude-router"
    assert parsed_bare_openai.provider == "openai"
    assert parsed_bare_openai.model == "gpt-4o-mini"


def test_parse_litellm_response_uses_openai_wire_model_for_alias_usage_threshold() -> None:
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    adapter._config = SimpleNamespace(
        llm_model_list=[
            {
                "model_name": "fast",
                "litellm_params": {"model": "openai/gpt-4o"},
            }
        ]
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="ok",
                    reasoning_content=None,
                    tool_calls=[],
                )
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=500,
            completion_tokens=20,
            total_tokens=520,
            prompt_tokens_details={"cached_tokens": 0},
        ),
    )

    parsed = adapter._parse_litellm_response(response, "fast")

    assert parsed.provider == "openai"
    assert parsed.model == "fast"
    assert parsed.usage["provider_min_cache_tokens"] == 1024
    assert parsed.usage["cache_capability"] == "supported"
    assert parsed.usage["cache_eligibility"] == "below_threshold"
    assert parsed.usage["cache_observation"] == "unknown"
    assert parsed.usage["normalized_cache_read_tokens"] == 0
    assert parsed.usage["normalized_cache_eligible_input_tokens"] is None
    assert parsed.usage["normalized_cache_hit_ratio"] is None


def test_parse_litellm_response_normalizes_litellm_usage_object(monkeypatch) -> None:
    monkeypatch.setenv("LLM_USAGE_HMAC_SECRET", "adapter-usage-object-secret")
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    adapter._config = SimpleNamespace(llm_model_list=[])
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="ok",
                    reasoning_content=None,
                    tool_calls=[],
                )
            )
        ],
        usage=Usage(
            prompt_tokens=2000,
            completion_tokens=100,
            total_tokens=2100,
            prompt_tokens_details={"cached_tokens": 500},
        ),
    )

    parsed = adapter._parse_litellm_response(
        response,
        "openai/gpt-4o",
        [{"role": "user", "content": "hello"}],
    )

    assert parsed.provider == "openai"
    assert parsed.usage["prompt_tokens"] == 2000
    assert parsed.usage["completion_tokens"] == 100
    assert parsed.usage["total_tokens"] == 2100
    assert parsed.usage["normalized_cache_read_tokens"] == 500
    assert parsed.usage["cache_capability"] == "supported"
    assert parsed.usage["cache_observation"] == "partial_hit"
    assert parsed.usage["messages_hmac"]


def test_parse_litellm_response_reads_private_hidden_usage_best_effort(monkeypatch) -> None:
    monkeypatch.setenv("LLM_USAGE_HMAC_SECRET", "adapter-hidden-usage-secret")
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    adapter._config = SimpleNamespace(llm_model_list=[])
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="ok",
                    reasoning_content=None,
                    tool_calls=[],
                )
            )
        ],
        usage=None,
        _hidden_params={
            "usage": Usage(
                prompt_tokens=2000,
                completion_tokens=100,
                total_tokens=2100,
                prompt_tokens_details={"cached_tokens": 500},
            )
        },
    )

    parsed = adapter._parse_litellm_response(
        response,
        "openai/gpt-4o",
        [{"role": "user", "content": "hello"}],
    )

    assert parsed.usage["prompt_tokens"] == 2000
    assert parsed.usage["completion_tokens"] == 100
    assert parsed.usage["total_tokens"] == 2100
    assert parsed.usage["normalized_cache_read_tokens"] == 500
    assert parsed.usage["provider_usage_json"]
    assert parsed.usage["messages_hmac"]


def test_parse_litellm_response_preserves_anthropic_litellm_prompt_tokens_without_input_tokens(monkeypatch) -> None:
    monkeypatch.setenv("LLM_USAGE_HMAC_SECRET", "anthropic-normalized-secret")
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    adapter._config = SimpleNamespace(llm_model_list=[])
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="ok",
                    reasoning_content=None,
                    tool_calls=[],
                )
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )

    parsed = adapter._parse_litellm_response(
        response,
        "anthropic/claude-test",
        [{"role": "user", "content": "hello"}],
    )

    assert parsed.usage["prompt_tokens"] == 100
    assert parsed.usage["completion_tokens"] == 20
    assert parsed.usage["total_tokens"] == 120
    assert parsed.usage["normalized_prompt_tokens"] == 100
    assert parsed.usage["normalized_uncached_input_tokens"] == 100
    assert parsed.usage["cache_observation"] == "zero_hit"
    assert parsed.usage["hmac_key_version"]
    assert len(parsed.usage["messages_hmac"]) == 64


def test_parse_litellm_response_without_provider_usage_keeps_usage_empty() -> None:
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    adapter._config = SimpleNamespace(llm_model_list=[])
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="ok",
                    reasoning_content=None,
                    tool_calls=[],
                )
            )
        ],
    )

    parsed = adapter._parse_litellm_response(
        response,
        "openai/gpt-test",
        [{"role": "user", "content": "hello"}],
    )

    assert parsed.usage == {}


def test_parse_litellm_response_maps_zhipu_usage_to_glm_cache_shape() -> None:
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    adapter._config = SimpleNamespace(llm_model_list=[])
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="ok",
                    reasoning_content=None,
                    tool_calls=[],
                )
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=1200,
            completion_tokens=80,
            total_tokens=1280,
            prompt_tokens_details={"cached_tokens": 1200},
        ),
    )

    parsed = adapter._parse_litellm_response(response, "zhipu/glm-4.5")

    assert parsed.provider == "zhipu"
    assert parsed.usage["normalized_cache_read_tokens"] == 1200
    assert parsed.usage["cache_capability"] == "supported"
    assert parsed.usage["cache_observation"] == "full_hit"


def test_parse_litellm_response_hmac_covers_tool_call_wire_messages(monkeypatch) -> None:
    monkeypatch.setenv("LLM_USAGE_HMAC_SECRET", "agent-tool-secret")
    adapter = LLMToolAdapter.__new__(LLMToolAdapter)
    adapter._config = SimpleNamespace(llm_model_list=[])

    def _response() -> SimpleNamespace:
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="ok",
                        reasoning_content=None,
                        tool_calls=[],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )

    first_messages = [
        {
            "role": "assistant",
            "content": "same",
            "tool_calls": [
                {
                    "id": "call_a",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": "{}"},
                    "provider_specific_fields": {"thought_signature": "sig-a"},
                }
            ],
        }
    ]
    second_messages = [
        {
            "role": "assistant",
            "content": "same",
            "tool_calls": [
                {
                    "id": "call_b",
                    "type": "function",
                    "function": {"name": "lookup", "arguments": '{"n":1}'},
                    "provider_specific_fields": {"thought_signature": "sig-b"},
                }
            ],
        }
    ]

    first = adapter._parse_litellm_response(_response(), "anthropic/claude-test", first_messages)
    second = adapter._parse_litellm_response(_response(), "anthropic/claude-test", second_messages)

    assert first.usage["messages_hmac"]
    assert second.usage["messages_hmac"]
    assert first.usage["messages_hmac"] != second.usage["messages_hmac"]
