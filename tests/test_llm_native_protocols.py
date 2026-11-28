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


def test_p0_3_and_p1_15_openai_store_precedence_trace_sanitizer_and_responses_stream_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P0-3: caller store=False wins over deployment_extra_body; P1-15: Responses stream preserves encrypted reasoning."""
    from src.llm.native_types import NativeBadRequestError
    from src.llm.openai_transport import (
        build_chat_completions_payload,
        build_responses_api_payload,
        prepare_openai_request,
    )

    # P0-3 Chat: explicit caller store=False stays authoritative over deployment_extra_body["store"]=True
    chat_body = build_chat_completions_payload(
        wire_model="gpt-4o",
        messages=[
            {
                "role": "assistant",
                "content": "hello",
                "_trace_provider": "openai",
                "_trace_model": "gpt-4o",
            },
            {"role": "user", "content": "next"},
        ],
        deployment_extra_body={"store": True},
        store=False,
    )
    assert chat_body["store"] is False
    # P2: _trace_provider and _trace_model are stripped from wire messages
    assert "_trace_provider" not in chat_body["messages"][0]
    assert "_trace_model" not in chat_body["messages"][0]

    # P0-3 Responses: string "false" -> False + encrypted reasoning preserved; invalid string raises
    resp_body = build_responses_api_payload(
        wire_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        deployment_extra_body={"store": True},
        store="false",
        parallel_tool_calls=False,
    )
    assert resp_body["store"] is False
    assert "reasoning.encrypted_content" in resp_body["include"]
    assert resp_body["parallel_tool_calls"] is False

    with pytest.raises(NativeBadRequestError):
        build_responses_api_payload(
            wire_model="gpt-5",
            messages=[{"role": "user", "content": "hi"}],
            store="definitely-not-a-bool",
        )

    # P2: direct-call extra_headers resolves os.environ/VAR instead of overwriting with raw ref
    monkeypatch.setenv("DSA_CUSTOM_HDR_VAL", "resolved-token-42")
    spec = DeploymentSpec(
        alias="openai/gpt-4o",
        wire_model="gpt-4o",
        protocol="openai_chat",
        provider="openai",
        api_base="https://relay.example/v1",
        api_key="sk-1234",
        endpoint_url="https://relay.example/v1/chat/completions",
        extra_headers={"X-Custom": "resolved-token-42"},
    )
    _url, hdrs, _payload, _timeout = prepare_openai_request(
        spec,
        [{"role": "user", "content": "hi"}],
        False,
        {"extra_headers": {"X-Custom": "os.environ/DSA_CUSTOM_HDR_VAL"}},
    )
    assert hdrs["X-Custom"] == "resolved-token-42"

    # P1-15 + P2: Responses streaming preserves encrypted reasoning items once in order & returns immediately on completed
    resp_spec = DeploymentSpec(alias="m", wire_model="gpt-5", protocol="openai_responses", provider="openai")
    sse_payload = (
        b'data: {"type":"response.output_item.done","output_index":0,"item":{"type":"reasoning","id":"rs_1","summary":[{"type":"summary_text","text":"step1"}],"encrypted_content":"ENC_BLOB_1"}}\n\n'
        b'data: {"type":"response.output_text.delta","delta":"done"}\n\n'
        b'data: {"type":"response.completed","response":{"id":"r1","model":"gpt-5","status":"completed","output":[{"type":"reasoning","id":"rs_1","encrypted_content":"ENC_BLOB_1"},{"type":"reasoning","id":"rs_2","encrypted_content":"ENC_BLOB_2"}],"usage":{"input_tokens":5,"output_tokens":2}}}\n\n'
        b'data: {"type":"response.output_text.delta","delta":"TRAILING_AFTER_COMPLETED"}\n\n'
    )
    chunks = list(iter_openai_stream_chunks(resp_spec, [sse_payload]))
    collected_blocks = [
        blk
        for ch in chunks
        for blk in (ch.choices[0].delta.provider_blocks or [])
    ]
    assert [b["id"] for b in collected_blocks] == ["rs_1", "rs_2"]
    assert [b["encrypted_content"] for b in collected_blocks] == ["ENC_BLOB_1", "ENC_BLOB_2"]
    assert "".join(c.choices[0].delta.content or "" for c in chunks) == "done"


def test_p1_16_and_p1_17_anthropic_interleaved_replay_response_format_and_thinking_guards() -> None:
    """P1-16: [thinking, tool_use, text] & [tool_use, text] keep wire order; P1-17: response_format handled; P2 guards."""
    from src.agent.llm_adapter import LLMToolAdapter
    from src.config import Config
    from src.llm.anthropic_transport import build_anthropic_payload, parse_anthropic_response
    from src.llm.native_types import NativeBadRequestError

    adapter = LLMToolAdapter(Config())

    # 1. [thinking, tool_use, text] replays in exact order through LLMToolAdapter
    raw_interleaved = {
        "id": "msg_order_1",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "content": [
            {"type": "thinking", "thinking": "plan", "signature": "sig_plan"},
            {"type": "tool_use", "id": "toolu_mid", "name": "lookup", "input": {"code": "600519"}},
            {"type": "text", "text": "After tool call."},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    parsed1 = parse_anthropic_response(raw_interleaved)
    llm_resp1 = adapter._parse_litellm_response(parsed1, "anthropic/claude-sonnet-4-6")
    history = [
        {"role": "user", "content": "analyze"},
        {
            "role": "assistant",
            "content": llm_resp1.content,
            "provider_blocks": llm_resp1.provider_blocks,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in llm_resp1.tool_calls
            ],
        },
        {"role": "tool", "tool_call_id": "toolu_mid", "content": '{"ok": true}'},
    ]
    openai_msgs = adapter._convert_messages(history)
    replayed = build_anthropic_payload(wire_model="claude-sonnet-4-6", messages=openai_msgs)
    assistant_blocks = replayed["messages"][1]["content"]
    assert [b["type"] for b in assistant_blocks] == ["thinking", "tool_use", "text"]
    assert assistant_blocks[1]["id"] == "toolu_mid"

    # 2. [tool_use, text] WITHOUT thinking also preserves exact order
    raw_no_think = {
        "id": "msg_order_2",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "content": [
            {"type": "tool_use", "id": "toolu_first", "name": "lookup", "input": {"code": "000001"}},
            {"type": "text", "text": "Tail text"},
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 5, "output_tokens": 3},
    }
    parsed2 = parse_anthropic_response(raw_no_think)
    assert [b["type"] for b in (parsed2.choices[0].message.provider_blocks or [])] == ["tool_use", "text"]
    replayed2 = build_anthropic_payload(
        wire_model="claude-sonnet-4-6",
        messages=[
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "Tail text",
                "provider_blocks": parsed2.choices[0].message.provider_blocks,
                "tool_calls": [
                    {"id": "toolu_first", "type": "function", "function": {"name": "lookup", "arguments": '{"code":"000001"}'}}
                ],
            },
        ],
    )
    assert [b["type"] for b in replayed2["messages"][1]["content"]] == ["tool_use", "text"]

    # 3. P1-17: response_format json_schema translates to output_config; json_object raises typed error
    schema_payload = build_anthropic_payload(
        wire_model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "hi"}],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "out",
                "schema": {"type": "object", "properties": {"score": {"type": "number"}}},
            },
        },
        tools=[{"type": "function", "function": {"name": "f", "description": "d", "parameters": {"type": "object"}}}],
        parallel_tool_calls=False,
    )
    assert schema_payload["output_config"]["format"]["type"] == "json_schema"
    assert schema_payload["output_config"]["format"]["schema"]["properties"]["score"]["type"] == "number"
    assert schema_payload["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}

    with pytest.raises(NativeBadRequestError, match="response_format"):
        build_anthropic_payload(
            wire_model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "hi"}],
            response_format={"type": "json_object"},
        )

    # 4. P2: Post-merge extra_body.temperature != 1.0 and thinking+forced-tool raise NativeBadRequestError
    with pytest.raises(NativeBadRequestError, match="temperature=1.0"):
        build_anthropic_payload(
            wire_model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "hi"}],
            reasoning_effort="low",
            extra_body={"temperature": 0.3},
        )
    with pytest.raises(NativeBadRequestError, match="forced tool_choice"):
        build_anthropic_payload(
            wire_model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "hi"}],
            reasoning_effort="low",
            tools=[{"type": "function", "function": {"name": "f", "description": "d", "parameters": {"type": "object"}}}],
            tool_choice="required",
        )

    # 5. P2: Anthropic stream stops immediately on message_stop
    anth_sse = (
        b'data: {"type":"message_start","message":{"id":"m1","model":"claude-sonnet-4-6","usage":{"input_tokens":1}}}\n\n'
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"OK"}}\n\n'
        b'data: {"type":"message_stop"}\n\n'
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"TRAILING"}}\n\n'
    )
    assert "".join(c.choices[0].delta.content or "" for c in iter_anthropic_stream_chunks([anth_sse])) == "OK"


def test_p1_18_to_p1_21_gemini_parts_replay_schema_properties_finish_and_partial_args() -> None:
    """P1-18..P1-21 + P2: Gemini thought/sig parts order, properties.title/default, multi-cand EOF, partialArgs."""
    from src.agent.llm_adapter import LLMToolAdapter
    from src.config import Config
    from src.llm.gemini_transport import (
        _clean_gemini_schema,
        build_gemini_payload,
        parse_gemini_response,
        parse_gemini_usage,
    )
    from src.llm.native_types import NativeBadRequestError

    adapter = LLMToolAdapter(Config())

    # P1-18: thought: true + thoughtSignature + signature-only + [functionCall, signed_text] exact order
    raw_gem = {
        "responseId": "gem_order",
        "modelVersion": "gemini-2.5-pro",
        "candidates": [
            {
                "index": 0,
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "hidden thought", "thought": True, "thoughtSignature": "SIG_THOUGHT"},
                        {"thoughtSignature": "SIG_ONLY"},
                        {"functionCall": {"id": "fc_1", "name": "quote", "args": {"code": "600519"}}, "thoughtSignature": "SIG_FC"},
                        {"text": "Visible tail", "thoughtSignature": "SIG_TEXT"},
                    ],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 20,
            "candidatesTokenCount": 10,
            "thoughtsTokenCount": 7,
            "toolUsePromptTokenCount": 5,
        },
    }
    parsed = parse_gemini_response(raw_gem)
    # P2: completion_tokens includes thoughtsTokenCount; total includes toolUsePromptTokenCount
    assert parsed.usage.completion_tokens == 17
    assert parsed.usage.total_tokens == 42

    llm_resp = adapter._parse_litellm_response(parsed, "gemini/gemini-2.5-pro")
    assert llm_resp.content == "Visible tail"
    history = [
        {"role": "user", "content": "check"},
        {
            "role": "assistant",
            "content": llm_resp.content,
            "provider_blocks": llm_resp.provider_blocks,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "thought_signature": tc.thought_signature,
                    "provider_specific_fields": tc.provider_specific_fields,
                }
                for tc in llm_resp.tool_calls
            ],
        },
        {"role": "tool", "tool_call_id": "fc_1", "name": "quote", "content": '{"p":1500}'},
    ]
    replayed = build_gemini_payload(
        wire_model="gemini-2.5-pro",
        messages=adapter._convert_messages(history),
        reasoning_effort="none",  # P2: Gemini 2.5 Pro must NOT emit thinkingBudget=0
    )
    assert "thinkingConfig" not in replayed.get("generationConfig", {})
    replayed_parts = replayed["contents"][1]["parts"]
    assert len(replayed_parts) == 4
    assert replayed_parts[0] == {"thought": True, "text": "hidden thought", "thoughtSignature": "SIG_THOUGHT"}
    assert replayed_parts[1] == {"thoughtSignature": "SIG_ONLY"}
    assert replayed_parts[2]["functionCall"]["id"] == "fc_1"
    assert replayed_parts[2]["thoughtSignature"] == "SIG_FC"
    assert replayed_parts[3] == {"text": "Visible tail", "thoughtSignature": "SIG_TEXT"}

    # P1-19: _clean_gemini_schema MUST preserve user properties named 'title', 'default', 'strict'
    schema = {
        "type": "object",
        "title": "OuterSchemaTitleToStrip",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string", "title": "InnerTitleToStrip"},
            "default": {"type": "string", "default": "fallback"},
            "strict": {"type": "boolean"},
        },
        "required": ["title", "default", "strict"],
    }
    cleaned = _clean_gemini_schema(schema)
    assert "title" not in cleaned
    assert "additionalProperties" not in cleaned
    assert set(cleaned["properties"].keys()) == {"title", "default", "strict"}
    assert "title" not in cleaned["properties"]["title"]
    assert "default" not in cleaned["properties"]["default"]
    assert cleaned["required"] == ["title", "default", "strict"]

    # P2: fileData with arbitrary HTTP URL raises NativeBadRequestError
    with pytest.raises(NativeBadRequestError):
        build_gemini_payload(
            wire_model="gemini-2.5-flash",
            messages=[{"role": "user", "content": [{"fileData": {"fileUri": "https://evil.example/img.png"}}]}],
        )

    # P2: MALFORMED_FUNCTION_CALL surfaces distinctly (not disguised as "stop")
    malformed_resp = parse_gemini_response(
        {"candidates": [{"index": 0, "content": {"parts": []}, "finishReason": "MALFORMED_FUNCTION_CALL"}]}
    )
    assert malformed_resp.choices[0].finish_reason == "malformed_function_call"

    # P1-20: No premature finish_reason="tool_calls" before provider finishReason; per-candidate EOF check
    stream_mid_tool = (
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"functionCall":{"id":"fc1","name":"f","args":{"x":1}}}]}}]}\n\n'
        b'data: {"candidates":[{"index":0,"content":{"parts":[]},"finishReason":"STOP"}]}\n\n'
    )
    chunks_mid = list(iter_gemini_stream_chunks([stream_mid_tool]))
    assert chunks_mid[0].choices[0].finish_reason is None
    assert chunks_mid[-1].choices[0].finish_reason == "tool_calls"

    multi_cand_truncated = (
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"text":"a"}]},"finishReason":"STOP"},{"index":1,"content":{"parts":[{"text":"b"}]}}]}\n\n'
    )
    with pytest.raises(NativeIncompleteStreamError):
        list(iter_gemini_stream_chunks([multi_cand_truncated]))

    # P1-21: Streamed partialArgs / willContinue assemble into ONE single complete tool call
    partial_sse = (
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"functionCall":{"id":"fc_p1","name":"get_quote","partialArgs":[{"jsonPath":"$.code","stringValue":"600"}],"willContinue":true},"thoughtSignature":"SIG_P"}]}}]}\n\n'
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"functionCall":{"partialArgs":[{"jsonPath":"$.code","stringValue":"519"},{"jsonPath":"$.days","numberValue":5}],"willContinue":false}}]},"finishReason":"STOP"}]}\n\n'
    )
    partial_chunks = list(iter_gemini_stream_chunks([partial_sse]))
    emitted_tcs = [
        tc
        for ch in partial_chunks
        for tc in (ch.choices[0].delta.tool_calls or [])
    ]
    assert len(emitted_tcs) == 1
    assert emitted_tcs[0].id == "fc_p1"
    assert emitted_tcs[0].function.name == "get_quote"
    assert json.loads(emitted_tcs[0].function.arguments) == {"code": "600519", "days": 5}
    assert emitted_tcs[0].thought_signature == "SIG_P"


def test_p2_sse_empty_data_preserved_and_buffer_caps_enforced() -> None:
    """P2: iter_sse_events preserves empty data: frames while bounding pathological line/event buffers."""
    from src.llm.sse import iter_sse_json_events

    events = list(iter_sse_events([b"data:\n\ndata: {\"ok\": 1}\n\n"]))
    assert len(events) == 2
    assert events[0].data == ""
    assert events[1].data == '{"ok": 1}'

    json_events = list(iter_sse_json_events([b"data:\n\ndata: {\"ok\": 1}\n\n"]))
    assert len(json_events) == 1
    assert json_events[0][1] == {"ok": 1}

    with pytest.raises(NativeAPIError) as exc_line:
        list(iter_sse_events([b"data: " + b"a" * 2048 + b"\n\n"], max_line_chars=1024))
    assert exc_line.value.error_code == "sse_frame_too_large"

    with pytest.raises(NativeAPIError) as exc_ev:
        list(iter_sse_events([b"data: " + b"a" * 700 + b"\ndata: " + b"b" * 700 + b"\n\n"], max_event_chars=1024))
    assert exc_ev.value.error_code == "sse_frame_too_large"


def test_round2_p0_4_p1_6a_p1_8_p1_9_p2_openai_precedence_filtering_and_interleaved_replay() -> None:
    """Round 2 P0-4, P1-6a, P1-8, P1-9, P2: Responses store precedence, _dsa_* filtering, mutual max_tokens, interleaved replay & stream ciphertext upgrade."""
    # P0-4: Deployment request_defaults store=True vs caller extra_body={"store": False} -> store=False + encrypted_content!
    resp_spec = DeploymentSpec(
        alias="openai/responses/gpt-5",
        wire_model="gpt-5",
        protocol="openai_responses",
        provider="openai",
        api_base="https://relay.example/v1",
        api_key="sk-1234",
        endpoint_url="https://relay.example/v1/responses",
        request_defaults={"store": True, "response_format": {"type": "json_object"}},
        extra_body={"parallel_tool_calls": True, "_dsa_leaked_dep": "nope"},
    )
    _u, _h, resp_body, _t = prepare_openai_request(
        resp_spec,
        [{"role": "user", "content": "hi"}],
        False,
        {
            "extra_body": {"store": False, "_dsa_leaked_caller": "nope"},
            "parallel_tool_calls": False,
            "_dsa_disable_response_format": True,
        },
    )
    assert resp_body["store"] is False
    assert "reasoning.encrypted_content" in resp_body.get("include", [])
    assert resp_body["parallel_tool_calls"] is False
    assert "text" not in resp_body
    assert not any(k.startswith("_dsa_") for k in resp_body)

    # Top-level caller store=False also beats caller extra_body={"store": True} in Chat Completions
    chat_top = build_chat_completions_payload(
        wire_model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        deployment_extra_body={"max_completion_tokens": 500, "_dsa_dep_flag": 1},
        deployment_request_defaults={"response_format": {"type": "json_object"}},
        extra_body={"store": True, "_dsa_caller_flag": 2},
        store=False,
        max_tokens=100,
        _dsa_disable_response_format=True,
    )
    assert chat_top["store"] is False
    assert chat_top["max_tokens"] == 100
    assert "max_completion_tokens" not in chat_top
    assert "response_format" not in chat_top
    assert not any(k.startswith("_dsa_") for k in chat_top)

    # P1-8: gpt-5 with deployment extra_body.max_completion_tokens + caller max_tokens sends ONLY max_completion_tokens
    chat_gpt5 = build_chat_completions_payload(
        wire_model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        deployment_extra_body={"max_completion_tokens": 500},
        max_tokens=100,
    )
    assert chat_gpt5["max_completion_tokens"] == 100
    assert "max_tokens" not in chat_gpt5

    # P1-9 Responses: interleaved [reasoning_1, function_call_1, reasoning_2, function_call_2] round-trips in exact order
    raw_interleaved = {
        "id": "resp_interleaved",
        "model": "gpt-5",
        "status": "completed",
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "r1"}], "encrypted_content": "ENC_1"},
            {"type": "function_call", "call_id": "call_1", "name": "f1", "arguments": '{"a":1}'},
            {"type": "reasoning", "id": "rs_2", "summary": [{"type": "summary_text", "text": "r2"}], "encrypted_content": "ENC_2"},
            {"type": "function_call", "call_id": "call_2", "name": "f2", "arguments": '{"b":2}'},
        ],
    }
    parsed = parse_responses_api_response(raw_interleaved)
    replayed = build_responses_api_payload(
        wire_model="gpt-5",
        messages=[
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": parsed.choices[0].message.content or "",
                "provider_blocks": parsed.choices[0].message.provider_blocks,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in (parsed.choices[0].message.tool_calls or [])
                ],
            },
        ],
    )
    # input[0] is user message; input[1..4] must preserve exact interleaved order!
    wire_items = replayed["input"][1:]
    assert [(it.get("type"), it.get("id") or it.get("call_id")) for it in wire_items] == [
        ("reasoning", "rs_1"),
        ("function_call", "call_1"),
        ("reasoning", "rs_2"),
        ("function_call", "call_2"),
    ]
    assert wire_items[0]["encrypted_content"] == "ENC_1"
    assert wire_items[2]["encrypted_content"] == "ENC_2"

    # P1-9 Responses SSE: output_item.done without ciphertext upgraded by response.completed ciphertext for same ID!
    sse_upgrade = (
        b'data: {"type":"response.output_item.done","output_index":0,"item":{"type":"reasoning","id":"rs_up","summary":[{"type":"summary_text","text":"s1"}]}}\n\n'
        b'data: {"type":"response.output_text.delta","delta":"ok"}\n\n'
        b'data: {"type":"response.completed","response":{"id":"r_up","model":"gpt-5","status":"completed","output":[{"type":"reasoning","id":"rs_up","summary":[{"type":"summary_text","text":"s1"}],"encrypted_content":"ENC_UPGRADED"}]}}\n\n'
    )
    up_chunks = list(iter_openai_stream_chunks(resp_spec, [sse_upgrade]))
    up_blocks = [b for ch in up_chunks for b in (ch.choices[0].delta.provider_blocks or [])]
    assert any(b.get("id") == "rs_up" and b.get("encrypted_content") == "ENC_UPGRADED" for b in up_blocks)


def test_round2_p1_9_p1_10_p2_anthropic_sse_block_order_output_config_merge_and_guards() -> None:
    """Round 2 P1-9, P1-10, P2: Anthropic SSE block order, output_config deep merge, _dsa_disable_response_format, top_p & parallel_tool_calls guards."""
    # P1-9 Anthropic SSE: [thinking, tool_use, text] emit completed provider_blocks in wire order
    sse_anth = (
        b'data: {"type":"message_start","message":{"id":"m_ord","model":"claude-sonnet-4-6","usage":{"input_tokens":5}}}\n\n'
        b'data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}\n\n'
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"plan"}}\n\n'
        b'data: {"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"sig_1"}}\n\n'
        b'data: {"type":"content_block_stop","index":0}\n\n'
        b'data: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_1","name":"quote","input":{}}}\n\n'
        b'data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"code\\":\\"600519\\"}"}}\n\n'
        b'data: {"type":"content_block_stop","index":1}\n\n'
        b'data: {"type":"content_block_start","index":2,"content_block":{"type":"text","text":""}}\n\n'
        b'data: {"type":"content_block_delta","index":2,"delta":{"type":"text_delta","text":"done"}}\n\n'
        b'data: {"type":"content_block_stop","index":2}\n\n'
        b'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":4}}\n\n'
        b'data: {"type":"message_stop"}\n\n'
    )
    anth_chunks = list(iter_anthropic_stream_chunks([sse_anth]))
    emitted_blocks = [b for ch in anth_chunks for b in (ch.choices[0].delta.provider_blocks or [])]
    assert [b["type"] for b in emitted_blocks] == ["thinking", "tool_use", "text"]
    assert emitted_blocks[0]["signature"] == "sig_1"
    assert emitted_blocks[1]["input"] == {"code": "600519"}
    assert emitted_blocks[2]["text"] == "done"

    # P1-10: output_config deep merge preserves existing {"effort": "low"} alongside json_schema format
    merged_oc_body = build_anthropic_payload(
        wire_model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "hi"}],
        extra_body={"output_config": {"effort": "low"}, "tool_choice": {"type": "auto"}},
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "s", "schema": {"type": "object", "properties": {"x": {"type": "integer"}}}},
        },
        tools=[{"type": "function", "function": {"name": "f", "description": "d", "parameters": {"type": "object"}}}],
        parallel_tool_calls=False,
    )
    assert merged_oc_body["output_config"]["effort"] == "low"
    assert merged_oc_body["output_config"]["format"]["type"] == "json_schema"
    # P2: caller parallel_tool_calls=False survives extra_body.tool_choice override
    assert merged_oc_body["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}

    # P1-10: _dsa_disable_response_format suppresses response_format
    suppressed_anth = build_anthropic_payload(
        wire_model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
        _dsa_disable_response_format=True,
    )
    assert "output_config" not in suppressed_anth

    # P2: post-merge top_p outside [0.95, 1.0] under extended thinking raises NativeBadRequestError
    with pytest.raises(NativeBadRequestError, match="top_p"):
        build_anthropic_payload(
            wire_model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": "hi"}],
            reasoning_effort="low",
            extra_body={"top_p": 0.5},
        )


def test_round2_p1_9_p1_11_p2_gemini_sse_order_quoted_jsonpath_sparse_array_and_finish_reason() -> None:
    """Round 2 P1-9, P1-11a/b, P2: Gemini SSE ordered parts, quoted/sparse/malformed JSONPath, leaf willContinue, FINISH_REASON_UNSPECIFIED, tightened fileUri."""
    # P1-9 Gemini SSE: unsigned functionCall precedes signed text -> ordered provider_blocks emitted for BOTH!
    sse_order = (
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"functionCall":{"id":"fc_u","name":"lookup","args":{"c":"1"}}}]}}]}\n\n'
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"text":"tail","thoughtSignature":"SIG_T"}]},"finishReason":"STOP"}]}\n\n'
    )
    ord_chunks = list(iter_gemini_stream_chunks([sse_order]))
    ord_blocks = [b for ch in ord_chunks for b in (ch.choices[0].delta.provider_blocks or [])]
    assert len(ord_blocks) == 2
    assert ord_blocks[0]["functionCall"]["id"] == "fc_u"
    assert ord_blocks[1] == {"text": "tail", "thoughtSignature": "SIG_T"}

    # P1-11a: Quoted bracket key $['target.symbol'] + sparse array out-of-order $.rows[1].code then $.rows[0].code
    sse_jsonpath = (
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"functionCall":{"id":"fc_jp","name":"scan","partialArgs":[{"jsonPath":"$[\'target.symbol\']","stringValue":"600519"},{"jsonPath":"$.rows[1].code","stringValue":"000002"}],"willContinue":true}}]}}]}\n\n'
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"functionCall":{"partialArgs":[{"jsonPath":"$.rows[0].code","stringValue":"000001"}],"willContinue":false}}]},"finishReason":"STOP"}]}\n\n'
    )
    jp_chunks = list(iter_gemini_stream_chunks([sse_jsonpath]))
    jp_tcs = [tc for ch in jp_chunks for tc in (ch.choices[0].delta.tool_calls or [])]
    assert len(jp_tcs) == 1
    assert json.loads(jp_tcs[0].function.arguments) == {
        "target.symbol": "600519",
        "rows": [{"code": "000001"}, {"code": "000002"}],
    }

    # P1-11a: Malformed JSONPath & huge array index (>1024) raise NativeBadRequestError
    for bad_path in ("$..wild", "$.rows[abc]", "$.rows[2048].code", "no_dollar"):
        bad_sse = (
            f'data: {{"candidates":[{{"index":0,"content":{{"parts":[{{"functionCall":{{"id":"fc_b","name":"f","partialArgs":[{{"jsonPath":"{bad_path}","stringValue":"x"}}],"willContinue":false}}}}]}},"finishReason":"STOP"}}]}}\n\n'
        ).encode("utf-8")
        with pytest.raises(NativeBadRequestError):
            list(iter_gemini_stream_chunks([bad_sse]))

    # P1-11a: Unfinished leaf-level willContinue: true at EOF raises NativeIncompleteStreamError
    unfinished_leaf_sse = (
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"functionCall":{"id":"fc_lf","name":"f","partialArgs":[{"jsonPath":"$.code","stringValue":"600","willContinue":true}],"willContinue":false}}]},"finishReason":"STOP"}]}\n\n'
    )
    with pytest.raises(NativeIncompleteStreamError):
        list(iter_gemini_stream_chunks([unfinished_leaf_sse]))

    # P1-11b: FINISH_REASON_UNSPECIFIED and whitespace finishReason are non-terminal -> raise NativeIncompleteStreamError on EOF
    for non_term in ("FINISH_REASON_UNSPECIFIED", "   ", ""):
        non_term_sse = (
            f'data: {{"candidates":[{{"index":0,"content":{{"parts":[{{"text":"hi"}}]}},"finishReason":"{non_term}"}}]}}\n\n'
        ).encode("utf-8")
        with pytest.raises(NativeIncompleteStreamError):
            list(iter_gemini_stream_chunks([non_term_sse]))

    # P2: Tightened _is_gemini_file_uri validation
    for bad_uri in (
        "http://generativelanguage.googleapis.com/v1beta/files/abc",
        "https://generativelanguage.googleapis.com/other/abc",
        "gs://bucket-only",
        "gs://bucket-only/",
    ):
        with pytest.raises(NativeBadRequestError):
            build_gemini_payload(
                wire_model="gemini-2.5-flash",
                messages=[{"role": "user", "content": [{"fileData": {"fileUri": bad_uri}}]}],
            )
    for good_uri in (
        "https://generativelanguage.googleapis.com/v1beta/files/abc123",
        "gs://my-bucket/folder/image.png",
    ):
        ok_payload = build_gemini_payload(
            wire_model="gemini-2.5-flash",
            messages=[{"role": "user", "content": [{"fileData": {"fileUri": good_uri}}]}],
        )
        assert ok_payload["contents"][0]["parts"][0]["fileData"]["fileUri"] == good_uri


def test_round3_f7_f8_responses_sse_dedup_gemini_leading_text_and_jsonpath_escapes() -> None:
    """Round 3 F7 & F8: Responses SSE deduplicates upgraded reasoning IDs & preserves store=True reasoning; Gemini SSE preserves leading unsigned text in provider_blocks; JSONPath decodes escapes and rejects malformed ones."""
    # 1. F7 Responses SSE: output_item.done has r1 without ciphertext, r2 with ciphertext,
    # then response.completed has [r1(ENC_1), r2(ENC_2)] -> MUST emit [r1(ENC_1), r2(ENC_2)] once with ZERO duplicates!
    resp_spec = DeploymentSpec(alias="m", wire_model="gpt-5", protocol="openai_responses", provider="openai")
    sse_dedup = (
        b'data: {"type":"response.output_item.done","output_index":0,"item":{"type":"reasoning","id":"r1","summary":[{"type":"summary_text","text":"s1"}]}}\n\n'
        b'data: {"type":"response.output_item.done","output_index":1,"item":{"type":"reasoning","id":"r2","summary":[{"type":"summary_text","text":"s2"}],"encrypted_content":"ENC_2"}}\n\n'
        b'data: {"type":"response.output_text.delta","delta":"done"}\n\n'
        b'data: {"type":"response.completed","response":{"id":"resp_dedup","model":"gpt-5","status":"completed","output":[{"type":"reasoning","id":"r1","summary":[{"type":"summary_text","text":"s1"}],"encrypted_content":"ENC_1"},{"type":"reasoning","id":"r2","summary":[{"type":"summary_text","text":"s2"}],"encrypted_content":"ENC_2"}]}}\n\n'
    )
    dedup_chunks = list(iter_openai_stream_chunks(resp_spec, [sse_dedup]))
    dedup_blocks = [b for ch in dedup_chunks for b in (ch.choices[0].delta.provider_blocks or [])]
    assert [(b["id"], b.get("encrypted_content")) for b in dedup_blocks] == [("r1", "ENC_1"), ("r2", "ENC_2")]

    # F7 micro-fix: If response.completed omits encrypted_content that was already present on deferred r2, preserve prior ciphertext!
    sse_keep_prior = (
        b'data: {"type":"response.output_item.done","output_index":0,"item":{"type":"reasoning","id":"r1","summary":[{"type":"summary_text","text":"s1"}]}}\n\n'
        b'data: {"type":"response.output_item.done","output_index":1,"item":{"type":"reasoning","id":"r2","summary":[{"type":"summary_text","text":"s2"}],"encrypted_content":"ENC_2_PRIOR"}}\n\n'
        b'data: {"type":"response.completed","response":{"id":"resp_kp","model":"gpt-5","status":"completed","output":[{"type":"reasoning","id":"r1","summary":[{"type":"summary_text","text":"s1"}],"encrypted_content":"ENC_1"},{"type":"reasoning","id":"r2","summary":[{"type":"summary_text","text":"s2"}]}]}}\n\n'
    )
    kp_chunks = list(iter_openai_stream_chunks(resp_spec, [sse_keep_prior]))
    kp_blocks = [b for ch in kp_chunks for b in (ch.choices[0].delta.provider_blocks or [])]
    assert [(b["id"], b.get("encrypted_content")) for b in kp_blocks] == [("r1", "ENC_1"), ("r2", "ENC_2_PRIOR")]

    # F7 Responses store=True non-stream preserves reasoning items even without encrypted_content
    parsed_store_true = parse_responses_api_response(
        {
            "id": "resp_st",
            "model": "gpt-5",
            "status": "completed",
            "output": [
                {"type": "reasoning", "id": "rs_st1", "summary": [{"type": "summary_text", "text": "think"}]},
                {"type": "function_call", "call_id": "call_st1", "name": "f", "arguments": "{}"},
            ],
        }
    )
    assert parsed_store_true.choices[0].message.provider_blocks is not None
    assert [b["type"] for b in parsed_store_true.choices[0].message.provider_blocks] == ["reasoning", "function_call"]

    # 2. F7 Gemini SSE: leading unsigned "lead" text in frame 1 + tool_call & signed "tail" in frame 2
    # MUST preserve "lead" in ordered provider_blocks so turn-2 replay does not drop it!
    sse_gem_lead = (
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"text":"lead"}]}}]}\n\n'
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"functionCall":{"id":"fc_l","name":"lookup","args":{"c":"1"}}},{"text":"tail","thoughtSignature":"SIG_TAIL"}]},"finishReason":"STOP"}]}\n\n'
    )
    lead_chunks = list(iter_gemini_stream_chunks([sse_gem_lead]))
    assert lead_chunks[0].choices[0].delta.content == "lead"
    assert lead_chunks[0].choices[0].delta.provider_blocks is None
    all_gem_blocks = [b for ch in lead_chunks for b in (ch.choices[0].delta.provider_blocks or [])]
    assert len(all_gem_blocks) == 3
    assert all_gem_blocks[0] == {"text": "lead"}
    assert all_gem_blocks[1]["functionCall"]["id"] == "fc_l"
    assert all_gem_blocks[2] == {"text": "tail", "thoughtSignature": "SIG_TAIL"}

    replayed_gem = build_gemini_payload(
        wire_model="gemini-2.5-pro",
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "leadtail", "provider_blocks": all_gem_blocks},
        ],
    )
    assert replayed_gem["contents"][1]["parts"][0] == {"text": "lead"}
    assert replayed_gem["contents"][1]["parts"][1]["functionCall"]["id"] == "fc_l"
    assert replayed_gem["contents"][1]["parts"][2] == {"text": "tail", "thoughtSignature": "SIG_TAIL"}

    # 3. F8 Gemini JSONPath escape decoding (\u002e, surrogate pairs, standard escapes) & malformed escape rejection
    sse_escapes = (
        b'data: {"candidates":[{"index":0,"content":{"parts":[{"functionCall":{"id":"fc_esc","name":"scan","partialArgs":[{"jsonPath":"$[\'target\\\\u002esymbol\']","stringValue":"600519"},{"jsonPath":"$[\\"line\\\\nbreak\\"]","stringValue":"ok"},{"jsonPath":"$[\'\\\\uD83D\\\\uDE00\']","stringValue":"smile"}],"willContinue":false}}]},"finishReason":"STOP"}]}\n\n'
    )
    esc_chunks = list(iter_gemini_stream_chunks([sse_escapes]))
    esc_tcs = [tc for ch in esc_chunks for tc in (ch.choices[0].delta.tool_calls or [])]
    assert json.loads(esc_tcs[0].function.arguments) == {
        "target.symbol": "600519",
        "line\nbreak": "ok",
        "😀": "smile",
    }

    for bad_esc_path in (r"$['bad\q']", r"$['\u123']", r"$['\uD800']", r"$['\uDC00']"):
        bad_payload = json.dumps(
            {
                "candidates": [
                    {
                        "index": 0,
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "id": "fc_be",
                                        "name": "f",
                                        "partialArgs": [{"jsonPath": bad_esc_path, "stringValue": "x"}],
                                        "willContinue": False,
                                    }
                                }
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            }
        )
        with pytest.raises(NativeBadRequestError):
            list(iter_gemini_stream_chunks([f"data: {bad_payload}\n\n".encode("utf-8")]))

    # F8 micro-fix: Literal lone surrogate already decoded by JSON parser is also rejected!
    from src.llm.gemini_transport import _parse_json_path_tokens

    with pytest.raises(NativeBadRequestError):
        _parse_json_path_tokens("$['\ud800']")
