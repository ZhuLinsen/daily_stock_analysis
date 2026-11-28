# -*- coding: utf-8 -*-
"""Suites 3 & 4: Per-protocol payload golden tests, 2-turn Anthropic/Gemini replay, and exhaustive SSE fuzzing."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List

import httpx
import pytest

from src.agent.llm_adapter import LLMToolAdapter
from src.config import Config
from src.llm.anthropic_transport import (
    build_anthropic_payload,
    iter_anthropic_stream_chunks,
    parse_anthropic_response,
)
from src.llm.errors import (
    call_litellm_with_param_recovery,
    classify_litellm_generation_param_error,
)
from src.llm.gemini_transport import (
    _clean_gemini_schema,
    build_gemini_payload,
    iter_gemini_stream_chunks,
    parse_gemini_response,
)
from src.llm.native_resolve import resolve_deployment
from src.llm.native_types import (
    DeploymentSpec,
    NativeAPIError,
    NativeBadRequestError,
    NativeContentFilterError,
    NativeIncompleteStreamError,
    NativeProviderBlockedError,
    NativeRateLimitError,
    classify_http_error,
)
from src.llm.openai_transport import (
    build_chat_completions_payload,
    build_responses_api_payload,
    iter_openai_stream_chunks,
    parse_chat_completion_response,
    parse_responses_api_response,
    prepare_openai_request,
)
from src.llm.sse import iter_sse_events
from src.llm.transport import create_native_transport, use_transport


# ============================================================
# Suite 3: Per-Protocol Payload Golden Tests & 2-Turn Replays
# ============================================================


def test_openai_chat_payload_max_completion_tokens_stream_options_store_and_sanitization() -> None:
    """OpenAI Chat maps max_tokens for o1/o3/o4/gpt-5, gates stream_options, preserves store, strips trace keys."""
    messages = [
        {
            "role": "assistant",
            "content": "partial",
            "reasoning_content": "step by step",
            "provider_specific_fields": {"internal": "drop"},
            "thinking_blocks": [{"type": "thinking", "thinking": "x"}],
            "_dsa_trace_provider": "deepseek",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_quote", "arguments": '{"code":"600519"}'},
                    "provider_specific_fields": {
                        "thought_signature": "sig-g",
                        "extra_content": {"google": {"thought_signature": "sig-g"}},
                    },
                }
            ],
        }
    ]

    # 1. gpt-5 on third-party relay -> max_completion_tokens, NO auto stream_options, store passed through
    relay_payload = build_chat_completions_payload(
        wire_model="gpt-5-mini",
        messages=messages,
        stream=True,
        endpoint_url="https://relay.example.com/v1/chat/completions",
        max_tokens=1024,
        store=False,
    )
    assert relay_payload["max_completion_tokens"] == 1024
    assert "max_tokens" not in relay_payload
    assert "stream_options" not in relay_payload
    assert relay_payload["store"] is False
    wire_msg = relay_payload["messages"][0]
    assert wire_msg["reasoning_content"] == "step by step"
    assert "provider_specific_fields" not in wire_msg
    assert "thinking_blocks" not in wire_msg
    assert "_dsa_trace_provider" not in wire_msg
    assert "provider_specific_fields" not in wire_msg["tool_calls"][0]
    assert wire_msg["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig-g"

    # 2. Official api.openai.com streaming -> auto include_usage
    official_payload = build_chat_completions_payload(
        wire_model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
        endpoint_url="https://api.openai.com/v1/chat/completions",
        max_tokens=256,
    )
    assert official_payload["max_tokens"] == 256
    assert official_payload["stream_options"] == {"include_usage": True}

    # 3. Response parses content_blocks and extra_content.google.thought_signature
    parsed = parse_chat_completion_response(
        {
            "id": "chatcmpl-x",
            "model": "gemini-2.5-flash",
            "choices": [
                {
                    "index": 0,
                    "content_blocks": [{"type": "thinking", "text": "t"}, {"type": "text", "text": "ans"}],
                    "message": {
                        "role": "assistant",
                        "content": "ans",
                        "tool_calls": [
                            {
                                "id": "call_g1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": "{}"},
                                "extra_content": {"google": {"thought_signature": "sig-from-google"}},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
    )
    assert parsed.choices[0].content_blocks == [{"type": "thinking", "text": "t"}, {"type": "text", "text": "ans"}]
    assert parsed.choices[0].message is not None
    assert parsed.choices[0].message.tool_calls is not None
    assert parsed.choices[0].message.tool_calls[0].thought_signature == "sig-from-google"
    assert parsed.choices[0].message.tool_calls[0].provider_specific_fields["thought_signature"] == "sig-from-google"


def test_openai_chat_request_defaults_and_400_param_recovery() -> None:
    """R8 request_defaults flow into payload (overridden by call kwargs); errors.py recovers max_tokens & stream_options."""
    spec = resolve_deployment(
        {
            "model_name": "my-gpt",
            "litellm_params": {
                "model": "openai/gpt-4o",
                "api_base": "https://relay.example.com/v1",
                "api_key": "sk-1234",
                "temperature": 0.2,
                "store": False,
                "max_tokens": 500,
            },
        }
    )
    assert isinstance(spec, DeploymentSpec)
    _url, _headers, payload, _timeout = prepare_openai_request(
        spec,
        [{"role": "user", "content": "hi"}],
        False,
        {"temperature": 0.9},
    )
    assert payload["temperature"] == 0.9
    assert payload["store"] is False
    assert payload["max_tokens"] == 500

    # errors.py one-shot 400 recovery: max_tokens -> max_completion_tokens
    rec1 = classify_litellm_generation_param_error(
        NativeBadRequestError("Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.")
    )
    assert rec1 is not None
    assert rec1.rename_params == {"max_tokens": "max_completion_tokens"}

    seen_calls: List[Dict[str, Any]] = []

    def _flaky_call(kw: Dict[str, Any]) -> str:
        seen_calls.append(dict(kw))
        if "max_tokens" in kw:
            raise NativeBadRequestError("Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens'.")
        return "ok"

    assert call_litellm_with_param_recovery(
        _flaky_call,
        model="openai/custom-reasoning",
        call_kwargs={"model": "openai/custom-reasoning", "max_tokens": 777},
        cache_recovery=False,
    ) == "ok"
    assert seen_calls[1]["max_completion_tokens"] == 777
    assert "max_tokens" not in seen_calls[1]

    # errors.py one-shot 400 recovery: stream_options unsupported
    rec2 = classify_litellm_generation_param_error(
        NativeBadRequestError("Unrecognized request argument supplied: stream_options")
    )
    assert rec2 is not None
    assert rec2.omit_params == ("stream_options",)


def test_openai_responses_store_false_encrypted_reasoning_replay_and_incomplete() -> None:
    """OpenAI Responses defaults store=False + encrypted reasoning replay, honors store=True, maps incomplete -> length."""
    payload = build_responses_api_payload(
        wire_model="gpt-5",
        messages=[{"role": "user", "content": "analyze"}],
        stream=False,
    )
    assert payload["store"] is False
    assert "reasoning.encrypted_content" in payload["include"]

    payload_stored = build_responses_api_payload(
        wire_model="gpt-5",
        messages=[{"role": "user", "content": "analyze"}],
        stream=False,
        store=True,
    )
    assert payload_stored["store"] is True
    assert "include" not in payload_stored

    # Parse response with encrypted reasoning and status=incomplete
    parsed = parse_responses_api_response(
        {
            "id": "resp_1",
            "model": "gpt-5",
            "status": "incomplete",
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs_01",
                    "summary": [{"type": "summary_text", "text": "checked PE"}],
                    "encrypted_content": "enc_blob_xyz",
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Partial answer"}],
                },
            ],
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        }
    )
    assert parsed.choices[0].finish_reason == "length"
    assert parsed.choices[0].message is not None
    assert parsed.choices[0].message.content == "Partial answer"
    assert parsed.choices[0].message.provider_blocks is not None
    assert parsed.choices[0].message.provider_blocks[0]["encrypted_content"] == "enc_blob_xyz"

    # Turn 2 replays encrypted reasoning item before assistant message
    turn2 = build_responses_api_payload(
        wire_model="gpt-5",
        messages=[
            {"role": "user", "content": "analyze"},
            {
                "role": "assistant",
                "content": parsed.choices[0].message.provider_blocks,
            },
            {"role": "user", "content": "continue"},
        ],
    )
    assert turn2["input"][1]["type"] == "reasoning"
    assert turn2["input"][1]["encrypted_content"] == "enc_blob_xyz"
    assert turn2["input"][2]["role"] == "assistant"


def test_anthropic_two_turn_thinking_and_visible_text_replay_through_llm_tool_adapter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Anthropic preserves BOTH thinking AND visible text across 2-turn LLMToolAdapter replay, joins text with ''."""
    captured_bodies: List[Dict[str, Any]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_bodies.append(body)
        if len(captured_bodies) == 1:
            return httpx.Response(
                200,
                json={
                    "id": "msg_1",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "content": [
                        {"type": "thinking", "thinking": "Checking fundamentals...", "signature": "sig_abc"},
                        {"type": "text", "text": "Let me look "},
                        {"type": "text", "text": "up 600519."},
                        {"type": "tool_use", "id": "toolu_01", "name": "get_quote", "input": {"code": "600519"}},
                    ],
                    "stop_reason": "tool_use",
                    "usage": {"input_tokens": 100, "output_tokens": 40},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "msg_2",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "Final answer"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 150, "output_tokens": 20},
            },
        )

    transport = create_native_transport(
        http_transport=httpx.MockTransport(_handler),
        fallback_to_litellm=False,
    )
    cfg = Config(
        litellm_model="anthropic/claude-sonnet-4-6",
        agent_litellm_model="anthropic/claude-sonnet-4-6",
        anthropic_api_keys=["sk-ant-test-12345678"],
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_quote",
                "description": "Get stock quote",
                "parameters": {"type": "object", "properties": {"code": {"type": "string"}}},
            },
        }
    ]
    with use_transport(transport):
        adapter = LLMToolAdapter(cfg)
        turn1 = adapter.call_with_tools(
            messages=[{"role": "user", "content": "Analyze 600519"}],
            tools=tools,
        )
        # Text blocks joined with "" (not "\n")
        assert turn1.content == "Let me look up 600519."
        assert len(turn1.tool_calls) == 1
        assert turn1.tool_calls[0].id == "toolu_01"
        # provider_blocks keeps thinking AND visible text without duplicating thinking
        thinking_blocks = [b for b in turn1.provider_blocks if b.get("type") == "thinking"]
        text_blocks = [b for b in turn1.provider_blocks if b.get("type") == "text"]
        assert len(thinking_blocks) == 1
        assert len(text_blocks) == 2

        # Turn 2 replay through LLMToolAdapter
        history = [
            {"role": "user", "content": "Analyze 600519"},
            {
                "role": "assistant",
                "content": turn1.content,
                "provider_blocks": turn1.provider_blocks,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in turn1.tool_calls
                ],
            },
            {"role": "tool", "tool_call_id": "toolu_01", "content": '{"price": 1600}'},
        ]
        turn2 = adapter.call_with_tools(messages=history, tools=tools)
        assert turn2.content == "Final answer"

    # Verify turn 2 wire payload preserved thinking + BOTH text blocks + tool_use in exact order!
    replayed_assistant = captured_bodies[1]["messages"][1]
    assert replayed_assistant["role"] == "assistant"
    block_types = [b["type"] for b in replayed_assistant["content"]]
    assert block_types == ["thinking", "text", "text", "tool_use"]
    assert replayed_assistant["content"][0]["signature"] == "sig_abc"
    assert "".join(b["text"] for b in replayed_assistant["content"] if b["type"] == "text") == "Let me look up 600519."

    # Additional Anthropic payload checks: list system cache_control, empty user text drop, leading user turn, reasoning_effort budget log
    with caplog.at_level(logging.INFO, logger="src.llm.anthropic_transport"):
        anth_body = build_anthropic_payload(
            wire_model="claude-sonnet-4-6",
            messages=[
                {
                    "role": "system",
                    "content": [
                        {"type": "text", "text": "System rules", "cache_control": {"type": "ephemeral"}},
                    ],
                },
                {"role": "assistant", "content": "Assistant first"},
                {"role": "user", "content": [{"type": "text", "text": ""}, {"type": "text", "text": "Hello"}]},
            ],
            max_tokens=1024,
            reasoning_effort="medium",
        )
    assert anth_body["system"] == [{"type": "text", "text": "System rules", "cache_control": {"type": "ephemeral"}}]
    assert anth_body["messages"][0]["role"] == "user"
    assert anth_body["thinking"] == {"type": "enabled", "budget_tokens": 4096}
    assert anth_body["max_tokens"] == 4096 + 1024
    assert "Adjusted max_tokens" in caplog.text
    # Empty user text block omitted
    last_user_blocks = anth_body["messages"][-1]["content"]
    assert all(b.get("text") != "" for b in last_user_blocks if b.get("type") == "text")


def test_gemini_two_turn_replay_thought_signature_block_reason_schema_and_extra_body() -> None:
    """Gemini preserves functionCall.id, replays thoughtSignature on any part, enforces allowlist & schema parity."""
    captured_bodies: List[Dict[str, Any]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_bodies.append(body)
        if len(captured_bodies) == 1:
            return httpx.Response(
                200,
                json={
                    "responseId": "gem_1",
                    "modelVersion": "gemini-2.5-flash",
                    "candidates": [
                        {
                            "index": 0,
                            "content": {
                                "role": "model",
                                "parts": [
                                    {"text": "Checking quote.", "thoughtSignature": "text-sig-111"},
                                    {
                                        "functionCall": {
                                            "id": "fc_native_42",
                                            "name": "get_quote",
                                            "args": {"code": "600519"},
                                        },
                                        "thoughtSignature": "fc-sig-222",
                                    },
                                ],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 15, "totalTokenCount": 65},
                },
            )
        return httpx.Response(
            200,
            json={
                "responseId": "gem_2",
                "modelVersion": "gemini-2.5-flash",
                "candidates": [
                    {
                        "index": 0,
                        "content": {"role": "model", "parts": [{"text": "Done."}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {"promptTokenCount": 80, "candidatesTokenCount": 5, "totalTokenCount": 85},
            },
        )

    transport = create_native_transport(
        http_transport=httpx.MockTransport(_handler),
        fallback_to_litellm=False,
    )
    cfg = Config(
        litellm_model="gemini/gemini-2.5-flash",
        agent_litellm_model="gemini/gemini-2.5-flash",
        gemini_api_keys=["AIzaTestKey012345678901234"],
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_quote",
                "description": "Get quote",
                "parameters": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$defs": {"Code": {"type": ["string", "null"], "additionalProperties": False}},
                    "type": "object",
                    "properties": {"code": {"$ref": "#/$defs/Code"}},
                    "additionalProperties": False,
                },
            },
        }
    ]
    with use_transport(transport):
        adapter = LLMToolAdapter(cfg)
        turn1 = adapter.call_with_tools(messages=[{"role": "user", "content": "Check 600519"}], tools=tools)
        assert turn1.tool_calls[0].id == "fc_native_42"
        assert turn1.tool_calls[0].thought_signature == "fc-sig-222"
        assert turn1.provider_blocks[0]["thoughtSignature"] == "text-sig-111"

        # Turn 2 replays BOTH text thoughtSignature AND functionCall id + thoughtSignature AND functionResponse id
        history = [
            {"role": "user", "content": "Check 600519"},
            {
                "role": "assistant",
                "content": turn1.content,
                "provider_blocks": turn1.provider_blocks,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "thought_signature": tc.thought_signature,
                        "provider_specific_fields": tc.provider_specific_fields,
                    }
                    for tc in turn1.tool_calls
                ],
            },
            {"role": "tool", "tool_call_id": "fc_native_42", "content": '{"price": 1600}'},
        ]
        turn2 = adapter.call_with_tools(messages=history, tools=tools)
        assert turn2.content == "Done."

    # Verify schema sanitization (inlined $ref, nullable type array, stripped $schema/additionalProperties)
    decl_params = captured_bodies[0]["tools"][0]["functionDeclarations"][0]["parameters"]
    assert "$schema" not in decl_params
    assert "$defs" not in decl_params
    assert "additionalProperties" not in decl_params
    assert decl_params["properties"]["code"] == {"type": "string", "nullable": True}

    # Verify Turn 2 wire replay
    model_parts = captured_bodies[1]["contents"][1]["parts"]
    assert model_parts[0]["thoughtSignature"] == "text-sig-111"
    assert model_parts[1]["functionCall"]["id"] == "fc_native_42"
    assert model_parts[1]["thoughtSignature"] == "fc-sig-222"
    tool_resp_part = captured_bodies[1]["contents"][2]["parts"][0]["functionResponse"]
    assert tool_resp_part["id"] == "fc_native_42"
    assert tool_resp_part["name"] == "get_quote"

    # Deterministic fallback ID when provider omits functionCall.id
    r_a = parse_gemini_response(
        {"candidates": [{"index": 0, "content": {"parts": [{"functionCall": {"name": "f", "args": {"x": 1}}}]}, "finishReason": "STOP"}]}
    )
    r_b = parse_gemini_response(
        {"candidates": [{"index": 0, "content": {"parts": [{"functionCall": {"name": "f", "args": {"x": 1}}}]}, "finishReason": "STOP"}]}
    )
    assert r_a.choices[0].message.tool_calls[0].id == r_b.choices[0].message.tool_calls[0].id

    # promptFeedback.blockReason raises NativeContentFilterError
    with pytest.raises(NativeContentFilterError, match="SAFETY"):
        parse_gemini_response({"promptFeedback": {"blockReason": "SAFETY"}})

    # extra_body allowlist, inlineData pass-through, reasoning_effort, reject arbitrary HTTP image URL
    gem_body = build_gemini_payload(
        wire_model="gemini-2.5-flash",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"inlineData": {"mimeType": "image/png", "data": "AAAA"}},
                ],
            }
        ],
        reasoning_effort="low",
        extra_body={
            "generationConfig": {"candidateCount": 2},
            "safetySettings": [{"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"}],
            "forbidden_top_level_key": "must_be_dropped",
        },
    )
    assert "forbidden_top_level_key" not in gem_body
    assert gem_body["generationConfig"]["candidateCount"] == 2
    assert gem_body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 1024}
    assert gem_body["contents"][0]["parts"][1] == {"inlineData": {"mimeType": "image/png", "data": "AAAA"}}

    with pytest.raises(NativeBadRequestError, match="HTTP\\(S\\) image URLs"):
        build_gemini_payload(
            wire_model="gemini-2.5-flash",
            messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}]}],
        )

    # Per-candidate streaming tool state
    stream_bytes = [
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"functionCall":{"name":"fn0","args":{}}}]}},{"index":1,"content":{"parts":[{"functionCall":{"name":"fn1","args":{}}}]}}]}\n\n',
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"functionCall":{"name":"fn0_b","args":{}}}]},"finishReason":"STOP"},{"index":1,"finishReason":"STOP"}]}\n\n',
    ]
    chunks = list(iter_gemini_stream_chunks(stream_bytes, default_model="gemini-2.5-flash"))
    assert chunks[0].choices[0].delta.tool_calls[0].index == 0
    assert chunks[0].choices[1].delta.tool_calls[0].index == 0
    assert chunks[1].choices[0].delta.tool_calls[0].index == 1


def test_all_protocols_in_band_errors_html_200_and_waf_403_classification() -> None:
    """HTTP 200 JSON error, HTTP 200 HTML, WAF 403, and Model disabled 403 are classified accurately."""
    # 1. HTTP 200 JSON {"error": ...} raises classified error (never IndexError!)
    with pytest.raises(NativeRateLimitError):
        parse_chat_completion_response({"error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}})
    with pytest.raises(NativeAPIError):
        parse_anthropic_response({"error": {"type": "overloaded_error", "message": "Overloaded"}})
    with pytest.raises(NativeRateLimitError):
        parse_gemini_response({"error": {"code": 429, "message": "Quota exceeded"}})

    # 2. HTTP 200 text/html fails fast with /v1 hint
    def _html_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<!DOCTYPE html><html><body>Landing Page</body></html>")

    transport = create_native_transport(http_transport=httpx.MockTransport(_html_handler), fallback_to_litellm=False)
    with pytest.raises(NativeBadRequestError, match="text/html"):
        transport.completion(
            model="openai/gpt-4o",
            api_base="https://relay.example.com",
            api_key="sk-1234",
            messages=[{"role": "user", "content": "hi"}],
        )

    # 3. Cloudflare/WAF HTML 403 -> NativeProviderBlockedError with truncated body <= 512 chars
    huge_html = "<!DOCTYPE html><html><title>Just a moment...</title><body>" + ("x" * 2000) + "</body></html>"
    waf_err = classify_http_error(
        403,
        huge_html,
        provider="openai",
        headers={"content-type": "text/html", "cf-ray": "abc123"},
    )
    assert isinstance(waf_err, NativeProviderBlockedError)
    assert waf_err.is_waf_blocked is True
    assert len(str(waf_err.body)) <= 512

    # 4. Model disabled 403 -> NativeProviderBlockedError (NOT AuthenticationError)
    disabled_err = classify_http_error(
        403,
        json.dumps({"error": {"message": "Model is disabled for this organization"}}),
        provider="openai",
    )
    assert isinstance(disabled_err, NativeProviderBlockedError)
    assert disabled_err.error_code == "model_access_denied"


# ============================================================
# Suite 4: Exhaustive SSE Fuzzing
# ============================================================


_OPENAI_CHAT_SSE_FIXTURE = (
    b"\xef\xbb\xbf"  # UTF-8 BOM
    b": keepalive comment\r\n\r\n"
    b'data: {"id":"c1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"\xe8\xb4\xb5\xe5\xb7\x9e"}}]}\r\n\r\n'
    b'data: {"id":"c1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"\xe8\x8c\x85\xe5\x8f\xb0"},"finish_reason":"stop"}]}\n\n'
    b"data: [DONE]\r\n\r\n"
)

_OPENAI_RESPONSES_SSE_FIXTURE = (
    b"event: response.reasoning_text.delta\r"
    b'data: {"type":"response.reasoning_text.delta","delta":"think "}\r\r'
    b"event: response.output_text.delta\n"
    b'data: {"type":"response.output_text.delta","delta":"OK"}\n\n'
    b"event: response.refusal.delta\n"
    b'data: {"type":"response.refusal.delta","delta":"!"}\n\n'
    b"event: response.incomplete\n"
    b'data: {"type":"response.incomplete","response":{"id":"r1","model":"gpt-5","status":"incomplete","usage":{"input_tokens":4,"output_tokens":2}}}\n\n'
)

_ANTHROPIC_SSE_FIXTURE = (
    b'event: message_start\ndata: {"type":"message_start","message":{"id":"m1","model":"claude-sonnet-4-6","usage":{"input_tokens":5}}}\n\n'
    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"\xe6\x88\x90\xe5\x8a\x9f"}}\n\n'
    b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":3}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)

_GEMINI_SSE_FIXTURE = (
    b'data: {"responseId":"g1","modelVersion":"gemini-2.5-flash","candidates":[{"index":0,"content":{"parts":[{"text":"Hi"}]}}]}\n\n'
    b'data: {"responseId":"g1","modelVersion":"gemini-2.5-flash","candidates":[{"index":0,"content":{"parts":[{"text":"!"}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":3,"candidatesTokenCount":2}}\n\n'
)


def _split_1_byte(raw: bytes) -> List[bytes]:
    return [raw[i : i + 1] for i in range(len(raw))]


def test_sse_fuzz_every_byte_offset_and_1_byte_chunks_all_protocols() -> None:
    """Every protocol SSE fixture parses identically across 1-byte chunks and every single split offset."""
    chat_spec = DeploymentSpec(alias="m", wire_model="gpt-4o", protocol="openai_chat", provider="openai")
    resp_spec = DeploymentSpec(alias="m", wire_model="gpt-5", protocol="openai_responses", provider="openai")

    # 1. OpenAI Chat: BOM + CRLF/LF mix + multibyte CJK split at EVERY offset & 1-byte
    expected_chat = "".join(c.choices[0].delta.content or "" for c in iter_openai_stream_chunks(chat_spec, [_OPENAI_CHAT_SSE_FIXTURE]))
    assert expected_chat == "贵州茅台"
    assert "".join(c.choices[0].delta.content or "" for c in iter_openai_stream_chunks(chat_spec, _split_1_byte(_OPENAI_CHAT_SSE_FIXTURE))) == "贵州茅台"
    for offset in range(1, len(_OPENAI_CHAT_SSE_FIXTURE)):
        parts = [_OPENAI_CHAT_SSE_FIXTURE[:offset], _OPENAI_CHAT_SSE_FIXTURE[offset:]]
        got = "".join(c.choices[0].delta.content or "" for c in iter_openai_stream_chunks(chat_spec, parts))
        assert got == "贵州茅台", f"Failed at byte offset {offset}"

    # 2. OpenAI Responses: CR-only + LF + reasoning_text + refusal + response.incomplete -> length
    resp_chunks_1b = list(iter_openai_stream_chunks(resp_spec, _split_1_byte(_OPENAI_RESPONSES_SSE_FIXTURE)))
    assert "".join(c.choices[0].delta.content or "" for c in resp_chunks_1b) == "OK!"
    assert "".join(c.choices[0].delta.reasoning_content or "" for c in resp_chunks_1b) == "think "
    assert resp_chunks_1b[-1].choices[0].finish_reason == "length"
    for offset in range(1, len(_OPENAI_RESPONSES_SSE_FIXTURE)):
        parts = [_OPENAI_RESPONSES_SSE_FIXTURE[:offset], _OPENAI_RESPONSES_SSE_FIXTURE[offset:]]
        c_list = list(iter_openai_stream_chunks(resp_spec, parts))
        assert "".join(c.choices[0].delta.content or "" for c in c_list) == "OK!"

    # 3. Anthropic: 1-byte chunks & every offset
    anth_1b = "".join(c.choices[0].delta.content or "" for c in iter_anthropic_stream_chunks(_split_1_byte(_ANTHROPIC_SSE_FIXTURE)))
    assert anth_1b == "成功"
    for offset in range(1, len(_ANTHROPIC_SSE_FIXTURE)):
        parts = [_ANTHROPIC_SSE_FIXTURE[:offset], _ANTHROPIC_SSE_FIXTURE[offset:]]
        assert "".join(c.choices[0].delta.content or "" for c in iter_anthropic_stream_chunks(parts)) == "成功"

    # 4. Gemini: 1-byte chunks & every offset
    gem_1b = "".join(c.choices[0].delta.content or "" for c in iter_gemini_stream_chunks(_split_1_byte(_GEMINI_SSE_FIXTURE)))
    assert gem_1b == "Hi!"
    for offset in range(1, len(_GEMINI_SSE_FIXTURE)):
        parts = [_GEMINI_SSE_FIXTURE[:offset], _GEMINI_SSE_FIXTURE[offset:]]
        assert "".join(c.choices[0].delta.content or "" for c in iter_gemini_stream_chunks(parts)) == "Hi!"


def test_sse_fuzz_truncated_eof_missing_terminal_and_in_band_errors_raise() -> None:
    """Truncated EOF, missing terminal markers, and in-band SSE error frames MUST raise across all 4 protocols."""
    chat_spec = DeploymentSpec(alias="m", wire_model="gpt-4o", protocol="openai_chat", provider="openai")
    resp_spec = DeploymentSpec(alias="m", wire_model="gpt-5", protocol="openai_responses", provider="openai")

    # Truncated EOF mid-line / unterminated event frame (must NOT flush!)
    with pytest.raises(NativeIncompleteStreamError):
        list(iter_sse_events([b'data: {"partial": true}']))
    with pytest.raises(NativeIncompleteStreamError):
        list(iter_sse_events([b'data: {"no_blank_line": true}\n']))

    # Missing terminal markers for each of the 4 protocols
    with pytest.raises(NativeIncompleteStreamError):
        list(iter_openai_stream_chunks(chat_spec, [b'data: {"choices":[{"index":0,"delta":{"content":"hi"}}]}\n\n']))
    with pytest.raises(NativeIncompleteStreamError):
        list(iter_openai_stream_chunks(resp_spec, [b'data: {"type":"response.output_text.delta","delta":"hi"}\n\n']))
    with pytest.raises(NativeIncompleteStreamError):
        list(iter_anthropic_stream_chunks([b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}\n\n']))
    with pytest.raises(NativeIncompleteStreamError):
        list(iter_gemini_stream_chunks([b'data: {"candidates":[{"index":0,"content":{"parts":[{"text":"hi"}]}}]}\n\n']))

    # In-band SSE error frames for all 4 protocols (with secret redaction!)
    secret = "sk-sse-super-secret-9999"
    with pytest.raises(NativeRateLimitError) as e_chat:
        list(iter_openai_stream_chunks(chat_spec, [f'data: {{"error":{{"message":"rate limit for {secret}","type":"rate_limit_error"}}}}\n\n'.encode()], secrets=[secret]))
    assert secret not in str(e_chat.value)
    assert secret not in str(e_chat.value.body)

    with pytest.raises(NativeAPIError) as e_resp:
        list(iter_openai_stream_chunks(resp_spec, [f'data: {{"type":"response.failed","response":{{"error":{{"message":"boom {secret}"}}}}}}\n\n'.encode()], secrets=[secret]))
    assert secret not in str(e_resp.value)

    with pytest.raises(NativeAPIError) as e_anth:
        list(iter_anthropic_stream_chunks([f'event: error\ndata: {{"type":"error","error":{{"type":"overloaded_error","message":"oops {secret}"}}}}\n\n'.encode()], secrets=[secret]))
    assert secret not in str(e_anth.value)

    with pytest.raises(NativeRateLimitError) as e_gem:
        list(iter_gemini_stream_chunks([f'data: {{"error":{{"code":429,"message":"quota {secret}"}}}}\n\n'.encode()], secrets=[secret]))
    assert secret not in str(e_gem.value)
