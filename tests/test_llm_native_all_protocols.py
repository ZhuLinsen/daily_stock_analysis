# -*- coding: utf-8 -*-
"""Comprehensive offline tests for 4-protocol native HTTPX transport & unified router."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from unittest.mock import MagicMock

import httpx

from src.agent.llm_adapter import LLMToolAdapter
from src.llm import (
    NativeAPIError,
    NativeBadRequestError,
    NativeContextWindowExceededError,
    NativeRateLimitError,
    NativeUnifiedRouter,
    NativeUnifiedTransport,
    create_native_transport,
    resolve_native_protocol,
    supports_native_protocol,
)
from src.llm.anthropic_transport import resolve_anthropic_endpoint
from src.llm.gemini_transport import resolve_gemini_endpoint
from src.llm.usage import normalize_litellm_usage


class ProtocolResolutionTests(unittest.TestCase):
    def test_resolve_native_protocol_across_four_protocols_and_fallback_only(self) -> None:
        self.assertEqual(resolve_native_protocol("anthropic/claude-sonnet-4-5"), "anthropic")
        self.assertEqual(resolve_native_protocol("claude-3-7-sonnet-20250219"), "anthropic")
        self.assertEqual(resolve_native_protocol("gemini/gemini-2.5-flash"), "gemini")
        self.assertEqual(resolve_native_protocol("google/gemini-2.5-pro"), "gemini")
        self.assertEqual(resolve_native_protocol("gemini-2.5-pro"), "gemini")
        self.assertEqual(resolve_native_protocol("openai/gpt-5"), "openai_responses")
        self.assertEqual(resolve_native_protocol("deepseek/deepseek-chat"), "openai_chat")
        self.assertEqual(
            resolve_native_protocol("openrouter/anthropic/claude-3.5-sonnet"),
            "openai_chat",
        )
        self.assertEqual(
            resolve_native_protocol(
                "claude-proxy",
                api_base="https://proxy.example/v1",
                custom_llm_provider="openai_compatible",
            ),
            "openai_chat",
        )
        # Cloud-IAM protocols stay on fallback transport
        self.assertIsNone(resolve_native_protocol("bedrock/anthropic.claude-3-5-sonnet"))
        self.assertIsNone(resolve_native_protocol("vertex_ai/gemini-2.5-pro"))
        self.assertIsNone(resolve_native_protocol("azure/gpt-4o"))
        self.assertFalse(supports_native_protocol("bedrock/anthropic.claude-3-5-sonnet"))
        self.assertTrue(supports_native_protocol("anthropic/claude-sonnet-4-5"))

    def test_endpoint_resolution_prevents_path_duplication(self) -> None:
        self.assertEqual(
            resolve_anthropic_endpoint("https://api.anthropic.com"),
            "https://api.anthropic.com/v1/messages",
        )
        self.assertEqual(
            resolve_anthropic_endpoint("https://api.anthropic.com/v1"),
            "https://api.anthropic.com/v1/messages",
        )
        self.assertEqual(
            resolve_anthropic_endpoint("https://api.anthropic.com/v1/messages"),
            "https://api.anthropic.com/v1/messages",
        )
        self.assertEqual(
            resolve_gemini_endpoint("https://generativelanguage.googleapis.com", "gemini-2.5-pro"),
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent",
        )
        self.assertEqual(
            resolve_gemini_endpoint(
                "https://generativelanguage.googleapis.com/v1beta",
                "models/gemini-2.5-flash",
                stream=True,
            ),
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse",
        )


class AnthropicNativeTransportTests(unittest.TestCase):
    def test_anthropic_completion_vision_cache_control_thinking_and_alternation(self) -> None:
        captured: list[httpx.Request] = []
        captured_bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            captured_bodies.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "id": "msg_01abc",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-5",
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "Evaluating PE multiple vs 5Y band.",
                            "signature": "sig_thinking_xyz",
                        },
                        {
                            "type": "redacted_thinking",
                            "data": "opaque_redacted_blob",
                        },
                        {"type": "text", "text": "Checking position sizing."},
                        {
                            "type": "tool_use",
                            "id": "toolu_01",
                            "name": "get_stock_info",
                            "input": {"symbol": "600519"},
                        },
                    ],
                    "usage": {
                        "input_tokens": 120,
                        "cache_read_input_tokens": 800,
                        "cache_creation_input_tokens": 200,
                        "output_tokens": 65,
                    },
                },
            )

        transport = create_native_transport(
            http_transport=httpx.MockTransport(handler),
            fallback_to_litellm=False,
        )
        resp = transport.completion(
            model="anthropic/claude-sonnet-4-5",
            api_key="sk-ant-secret-key-999",
            api_base="https://api.anthropic.com/v1",
            temperature=0.3,
            max_tokens=1500,
            thinking={"type": "enabled", "budget_tokens": 2048},
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_stock_info",
                        "description": "Fetch stock quote",
                        "parameters": {
                            "type": "object",
                            "properties": {"symbol": {"type": "string"}},
                            "required": ["symbol"],
                        },
                    },
                }
            ],
            tool_choice="auto",
            messages=[
                {
                    "role": "system",
                    "content": "You are a quantitative analyst.",
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "role": "assistant",
                    "content": "Let me inspect prior tools.",
                    "provider_blocks": [
                        {"type": "thinking", "thinking": "prior", "signature": "sig_prior"}
                    ],
                    "tool_calls": [
                        {
                            "id": "toolu_a",
                            "type": "function",
                            "function": {"name": "get_a", "arguments": '{"x": 1}'},
                        },
                        {
                            "id": "toolu_b",
                            "type": "function",
                            "function": {"name": "get_b", "arguments": '{"y": 2}'},
                        },
                    ],
                },
                {"role": "tool", "tool_call_id": "toolu_a", "content": '{"ok": true}'},
                {"role": "tool", "tool_call_id": "toolu_b", "content": '{"ok": false}'},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this K-line chart."},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
                    ],
                },
            ],
        )

        self.assertEqual(len(captured), 1)
        req = captured[0]
        self.assertEqual(str(req.url), "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.headers.get("x-api-key"), "sk-ant-secret-key-999")
        self.assertEqual(req.headers.get("anthropic-version"), "2023-06-01")
        self.assertIsNone(req.headers.get("authorization"))

        sent = captured_bodies[0]
        # Thinking enabled bumps max_tokens > budget_tokens and omits non-1.0 temperature
        self.assertGreater(sent["max_tokens"], 2048)
        self.assertNotIn("temperature", sent)
        self.assertEqual(
            sent["system"],
            [
                {
                    "type": "text",
                    "text": "You are a quantitative analyst.",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        )
        # Sequential tool messages and user message all merged into one alternating "user" turn
        self.assertEqual([m["role"] for m in sent["messages"]], ["assistant", "user"])
        asst_blocks = sent["messages"][0]["content"]
        self.assertEqual(asst_blocks[0]["type"], "thinking")
        self.assertEqual(asst_blocks[-1]["type"], "tool_use")
        user_blocks = sent["messages"][1]["content"]
        self.assertEqual([b["type"] for b in user_blocks], ["tool_result", "tool_result", "text", "image"])
        self.assertEqual(
            user_blocks[3]["source"],
            {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="},
        )

        msg = resp.choices[0].message
        self.assertEqual(resp.choices[0].finish_reason, "tool_calls")
        self.assertEqual(msg.content, "Checking position sizing.")
        self.assertEqual(msg.reasoning_content, "Evaluating PE multiple vs 5Y band.")
        self.assertIsNone(msg.provider_blocks)
        self.assertEqual(len(msg.thinking_blocks or []), 2)
        self.assertEqual(msg.thinking_blocks[1]["type"], "redacted_thinking")
        self.assertEqual(msg.tool_calls[0].id, "toolu_01")
        self.assertEqual(msg.tool_calls[0].function.name, "get_stock_info")
        self.assertEqual(json.loads(msg.tool_calls[0].function.arguments), {"symbol": "600519"})

        normalized_usage = normalize_litellm_usage(
            resp.usage, model="anthropic/claude-sonnet-4-5", provider="anthropic"
        )
        self.assertEqual(normalized_usage["normalized_cache_read_tokens"], 800)
        self.assertEqual(normalized_usage["normalized_cache_write_tokens"], 200)
        self.assertEqual(normalized_usage["normalized_uncached_input_tokens"], 120)
        self.assertEqual(normalized_usage["prompt_tokens"], 1120)
        self.assertEqual(normalized_usage["completion_tokens"], 65)

    def test_anthropic_sse_streaming_thinking_signature_and_tool_delta(self) -> None:
        sse_frames = (
            'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_s1","model":"claude-sonnet-4-5","usage":{"input_tokens":50,"cache_read_input_tokens":30}}}\n\n'
            'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}\n\n'
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"Step 1"}}\n\n'
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"sig_final"}}\n\n'
            'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n'
            'event: content_block_start\ndata: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_s1","name":"run_factor","input":{}}}\n\n'
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"code\\":\\"600519\\"}"}}\n\n'
            'event: content_block_stop\ndata: {"type":"content_block_stop","index":1}\n\n'
            'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":40}}\n\n'
            'event: message_stop\ndata: {"type":"message_stop"}\n\n'
        ).encode("utf-8")

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=sse_frames)

        transport = create_native_transport(
            http_transport=httpx.MockTransport(handler),
            fallback_to_litellm=False,
        )
        chunks = list(
            transport.completion(
                model="anthropic/claude-sonnet-4-5",
                api_key="sk-ant-test",
                stream=True,
                messages=[{"role": "user", "content": "Run factor"}],
            )
        )
        reasoning = "".join(c.choices[0].delta.reasoning_content or "" for c in chunks)
        self.assertEqual(reasoning, "Step 1")
        thinking_blocks = [
            b
            for c in chunks
            for b in (c.choices[0].delta.thinking_blocks or [])
        ]
        self.assertEqual(
            thinking_blocks,
            [{"type": "thinking", "thinking": "Step 1", "signature": "sig_final"}],
        )
        tool_deltas = [tc for c in chunks for tc in (c.choices[0].delta.tool_calls or [])]
        self.assertEqual(tool_deltas[0].id, "toolu_s1")
        self.assertEqual(tool_deltas[0].function.name, "run_factor")
        self.assertEqual(tool_deltas[1].function.arguments, '{"code":"600519"}')
        self.assertEqual(chunks[-1].choices[0].finish_reason, "tool_calls")
        self.assertEqual(chunks[-1].usage.prompt_tokens, 80)
        self.assertEqual(chunks[-1].usage.completion_tokens, 40)


class GeminiNativeTransportTests(unittest.TestCase):
    def test_gemini_thought_signature_tool_loop_vision_and_usage(self) -> None:
        captured_requests: list[httpx.Request] = []
        captured_bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            body = json.loads(request.content.decode("utf-8"))
            captured_bodies.append(body)
            if len(captured_requests) == 1:
                return httpx.Response(
                    200,
                    json={
                        "responseId": "gem_1",
                        "modelVersion": "gemini-2.5-pro",
                        "candidates": [
                            {
                                "index": 0,
                                "finishReason": "STOP",
                                "content": {
                                    "role": "model",
                                    "parts": [
                                        {"text": "Need technicals first.", "thought": True},
                                        {
                                            "functionCall": {
                                                "name": "fetch_kline",
                                                "args": {"code": "AAPL"},
                                            },
                                            "thoughtSignature": "sig_gemini_roundtrip_1",
                                        },
                                    ],
                                },
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 300,
                            "candidatesTokenCount": 40,
                            "thoughtsTokenCount": 18,
                            "cachedContentTokenCount": 150,
                            "totalTokenCount": 358,
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "responseId": "gem_2",
                    "modelVersion": "gemini-2.5-pro",
                    "candidates": [
                        {
                            "index": 0,
                            "finishReason": "STOP",
                            "content": {
                                "role": "model",
                                "parts": [{"text": "Trend remains intact."}],
                            },
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 420,
                        "candidatesTokenCount": 25,
                        "totalTokenCount": 445,
                    },
                },
            )

        from types import SimpleNamespace

        transport = create_native_transport(
            http_transport=httpx.MockTransport(handler),
            fallback_to_litellm=False,
        )

        # Round-trip through LLMToolAdapter response parser & outbound message converter
        adapter = LLMToolAdapter.__new__(LLMToolAdapter)
        adapter._config = SimpleNamespace(llm_model_list=[])
        resp1_raw = transport.completion(
            model="gemini/gemini-2.5-pro",
            api_key="AIzaTestSecretKey1234",
            temperature=0.2,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "fetch_kline",
                        "description": "Fetch K-line candles",
                        "parameters": {
                            "$schema": "http://json-schema.org/draft-07/schema#",
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"code": {"type": "string"}},
                        },
                    },
                }
            ],
            messages=[
                {"role": "system", "content": "Be precise."},
                {"role": "user", "content": "Check AAPL."},
            ],
        )
        llm_resp1 = adapter._parse_litellm_response(
            resp1_raw,
            "gemini/gemini-2.5-pro",
        )
        self.assertEqual(llm_resp1.reasoning_content, "Need technicals first.")
        self.assertEqual(len(llm_resp1.tool_calls), 1)
        tc = llm_resp1.tool_calls[0]
        self.assertEqual(tc.thought_signature, "sig_gemini_roundtrip_1")

        history = [
            {"role": "system", "content": "Be precise."},
            {"role": "user", "content": "Check AAPL."},
            {
                "role": "assistant",
                "content": llm_resp1.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "thought_signature": tc.thought_signature,
                        "provider_specific_fields": tc.provider_specific_fields,
                    }
                ],
                "provider_blocks": llm_resp1.provider_blocks,
                "_trace_provider": "gemini",
                "_trace_model": "gemini/gemini-2.5-pro",
            },
            {
                "role": "tool",
                "name": "fetch_kline",
                "tool_call_id": tc.id,
                "content": '{"close": 230.5}',
            },
        ]
        wire_messages = adapter._convert_messages(
            history,
            target_model="gemini/gemini-2.5-pro",
        )
        resp2_raw = transport.completion(
            model="gemini/gemini-2.5-pro",
            api_key="AIzaTestSecretKey1234",
            messages=wire_messages,
        )
        llm_resp2 = adapter._parse_litellm_response(
            resp2_raw,
            "gemini/gemini-2.5-pro",
        )

        self.assertEqual(llm_resp2.content, "Trend remains intact.")
        req1, req2 = captured_requests
        self.assertEqual(
            str(req1.url),
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent",
        )
        # Key stays strictly in header, never leaked in URL query string
        self.assertNotIn("key=", str(req1.url))
        self.assertEqual(req1.headers.get("x-goog-api-key"), "AIzaTestSecretKey1234")

        body1, body2 = captured_bodies
        self.assertEqual(body1["systemInstruction"], {"parts": [{"text": "Be precise."}]})
        decl_params = body1["tools"][0]["functionDeclarations"][0]["parameters"]
        self.assertNotIn("$schema", decl_params)
        self.assertNotIn("additionalProperties", decl_params)

        # Turn 2 echoes exact thoughtSignature back on model functionCall AND resolves tool name on functionResponse
        model_turn = body2["contents"][1]
        self.assertEqual(model_turn["role"], "model")
        self.assertEqual(model_turn["parts"][0]["thoughtSignature"], "sig_gemini_roundtrip_1")
        tool_turn = body2["contents"][2]
        self.assertEqual(tool_turn["role"], "user")
        self.assertEqual(
            tool_turn["parts"][0],
            {"functionResponse": {"name": "fetch_kline", "response": {"close": 230.5}}},
        )

    def test_anthropic_llm_adapter_provider_blocks_roundtrip(self) -> None:
        captured_bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(request.content.decode("utf-8")))
            if len(captured_bodies) == 1:
                return httpx.Response(
                    200,
                    json={
                        "id": "msg_r1",
                        "role": "assistant",
                        "model": "claude-sonnet-4-5",
                        "stop_reason": "tool_use",
                        "content": [
                            {"type": "thinking", "thinking": "Think step", "signature": "sig_a1"},
                            {"type": "redacted_thinking", "data": "secret_blob"},
                            {"type": "tool_use", "id": "toolu_r1", "name": "get_pe", "input": {"code": "600519"}},
                        ],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "id": "msg_r2",
                    "role": "assistant",
                    "model": "claude-sonnet-4-5",
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "Valuation looks fair."}],
                },
            )

        from types import SimpleNamespace

        transport = create_native_transport(
            http_transport=httpx.MockTransport(handler),
            fallback_to_litellm=False,
        )
        adapter = LLMToolAdapter.__new__(LLMToolAdapter)
        adapter._config = SimpleNamespace(llm_model_list=[])
        raw1 = transport.completion(
            model="anthropic/claude-sonnet-4-5",
            api_key="sk-ant-r",
            messages=[{"role": "user", "content": "Evaluate 600519 PE."}],
        )
        parsed1 = adapter._parse_litellm_response(
            raw1, "anthropic/claude-sonnet-4-5"
        )
        history = [
            {"role": "user", "content": "Evaluate 600519 PE."},
            {
                "role": "assistant",
                "content": parsed1.content,
                "tool_calls": [
                    {
                        "id": parsed1.tool_calls[0].id,
                        "name": parsed1.tool_calls[0].name,
                        "arguments": parsed1.tool_calls[0].arguments,
                    }
                ],
                "provider_blocks": parsed1.provider_blocks,
                "_trace_provider": "anthropic",
                "_trace_model": "anthropic/claude-sonnet-4-5",
            },
            {"role": "tool", "tool_call_id": parsed1.tool_calls[0].id, "content": '{"pe": 22.5}'},
        ]
        wire_msgs = adapter._convert_messages(
            history,
            target_model="anthropic/claude-sonnet-4-5",
        )
        raw2 = transport.completion(
            model="anthropic/claude-sonnet-4-5",
            api_key="sk-ant-r",
            messages=wire_msgs,
        )
        self.assertEqual(raw2.choices[0].message.content, "Valuation looks fair.")
        asst_blocks = captured_bodies[1]["messages"][1]["content"]
        self.assertEqual([b["type"] for b in asst_blocks], ["thinking", "redacted_thinking", "tool_use"])
        self.assertEqual(asst_blocks[0]["signature"], "sig_a1")

    def test_gemini_vision_usage_and_streaming_sse(self) -> None:
        sse_body = (
            'data: {"responseId":"gem_s1","modelVersion":"gemini-2.5-flash","candidates":[{"index":0,"content":{"role":"model","parts":[{"text":"Thinking","thought":true}]}}]}\n\n'
            'data: {"responseId":"gem_s1","modelVersion":"gemini-2.5-flash","candidates":[{"index":0,"content":{"role":"model","parts":[{"functionCall":{"name":"calc","args":{"x":2}},"thoughtSignature":"sig_s"}]}}]}\n\n'
            'data: {"responseId":"gem_s1","modelVersion":"gemini-2.5-flash","candidates":[{"index":0,"finishReason":"STOP","content":{"role":"model","parts":[{"text":"Done"}]}}],"usageMetadata":{"promptTokenCount":100,"candidatesTokenCount":12,"cachedContentTokenCount":40,"thoughtsTokenCount":7,"totalTokenCount":119}}\n\n'
        ).encode("utf-8")
        captured_body = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_body.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, content=sse_body)

        transport = create_native_transport(
            http_transport=httpx.MockTransport(handler),
            fallback_to_litellm=False,
        )
        chunks = list(
            transport.completion(
                model="google/gemini-2.5-flash",
                api_key="AIzaStreamKey",
                stream=True,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Inspect image"},
                            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQ"}},
                        ],
                    }
                ],
            )
        )
        self.assertEqual(
            captured_body["contents"][0]["parts"][1],
            {"inlineData": {"mimeType": "image/jpeg", "data": "/9j/4AAQ"}},
        )
        self.assertEqual(chunks[0].choices[0].delta.reasoning_content, "Thinking")
        tc = chunks[1].choices[0].delta.tool_calls[0]
        self.assertEqual(tc.thought_signature, "sig_s")
        self.assertEqual(tc.provider_specific_fields, {"thought_signature": "sig_s"})
        self.assertEqual(chunks[2].choices[0].finish_reason, "tool_calls")

        norm = normalize_litellm_usage(chunks[2].usage, model="gemini/gemini-2.5-flash", provider="gemini")
        self.assertEqual(norm["normalized_cache_read_tokens"], 40)
        self.assertEqual(norm["provider_reported_cached_tokens"], 40)


class UnifiedRouterAndFailoverTests(unittest.TestCase):
    def test_heterogeneous_4_protocol_router_failover_and_cooldown(self) -> None:
        now = [1000.0]
        hits: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            hits.append(url)
            if "anthropic.com" in url:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "45"},
                    json={"type": "error", "error": {"type": "rate_limit_error", "message": "Overloaded"}},
                )
            if "generativelanguage.googleapis.com" in url:
                return httpx.Response(
                    200,
                    json={
                        "responseId": "gem_ok",
                        "candidates": [
                            {
                                "index": 0,
                                "finishReason": "STOP",
                                "content": {"role": "model", "parts": [{"text": "Recovered on Gemini"}]},
                            }
                        ],
                        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "totalTokenCount": 15},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "id": "resp_ok",
                    "object": "response",
                    "model": "gpt-5",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "OpenAI Responses ok"}]}],
                },
            )

        router = NativeUnifiedRouter(
            model_list=[
                {
                    "model_name": "smart-agent",
                    "litellm_params": {"model": "anthropic/claude-sonnet-4-5", "api_key": "sk-ant-1"},
                    "model_info": {"priority": 0},
                },
                {
                    "model_name": "smart-agent",
                    "litellm_params": {"model": "gemini/gemini-2.5-pro", "api_key": "AIza-2"},
                    "model_info": {"priority": 1},
                },
                {
                    "model_name": "smart-agent",
                    "litellm_params": {"model": "openai/gpt-5", "api_key": "sk-openai-3"},
                    "model_info": {"priority": 2},
                },
                {
                    "model_name": "smart-agent",
                    "litellm_params": {"model": "deepseek/deepseek-chat", "api_key": "sk-ds-4"},
                    "model_info": {"priority": 3},
                },
            ],
            http_transport=httpx.MockTransport(handler),
            clock=lambda: now[0],
        )
        res = router.completion(model="smart-agent", messages=[{"role": "user", "content": "Hello"}])
        self.assertEqual(res.choices[0].message.content, "Recovered on Gemini")
        self.assertEqual(len(hits), 2)
        self.assertIn("anthropic.com", hits[0])
        self.assertIn("generativelanguage.googleapis.com", hits[1])

        health = {d["deployment_id"]: d for d in router.pool.get_health_snapshot()}
        self.assertFalse(health["smart-agent:0"]["healthy"])
        self.assertAlmostEqual(health["smart-agent:0"]["cooldown_remaining_seconds"], 45.0, places=1)
        self.assertTrue(health["smart-agent:1"]["healthy"])

        # Subsequent call skips cooling Anthropic tier directly to healthy Gemini tier
        hits.clear()
        res2 = router.completion(model="smart-agent", messages=[{"role": "user", "content": "Again"}])
        self.assertEqual(res2.choices[0].message.content, "Recovered on Gemini")
        self.assertEqual(len(hits), 1)

    def test_stream_pre_first_chunk_failover_and_post_first_chunk_safety(self) -> None:
        call_num = [0]

        def pre_fail_handler(request: httpx.Request) -> httpx.Response:
            call_num[0] += 1
            if call_num[0] == 1:
                return httpx.Response(503, json={"error": {"message": "temporary upstream down"}})
            return httpx.Response(
                200,
                content=b'data: {"id":"c2","choices":[{"index":0,"delta":{"content":"Recovered stream"}}]}\n\ndata: [DONE]\n\n',
            )

        router = NativeUnifiedRouter(
            model_list=[
                {
                    "model_name": "dual",
                    "litellm_params": {"model": "anthropic/claude-sonnet-4-5", "api_key": "sk-1"},
                    "model_info": {"priority": 0},
                },
                {
                    "model_name": "dual",
                    "litellm_params": {"model": "deepseek/deepseek-chat", "api_key": "sk-2"},
                    "model_info": {"priority": 1},
                },
            ],
            http_transport=httpx.MockTransport(pre_fail_handler),
        )
        out = "".join(
            c.choices[0].delta.content or ""
            for c in router.completion(model="dual", stream=True, messages=[{"role": "user", "content": "hi"}])
        )
        self.assertEqual(out, "Recovered stream")

        # Post-first-chunk failure MUST NOT switch deployment mid-stream
        mid_attempts = [0]

        class _MidFailStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b'data: {"type":"message_start","message":{"id":"m1","model":"claude"}}\n\n'
                yield b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Partial"}}\n\n'
                raise httpx.ReadTimeout("mid-stream timeout sk-secret-mid-999")

        def mid_fail_handler(_request: httpx.Request) -> httpx.Response:
            mid_attempts[0] += 1
            return httpx.Response(200, stream=_MidFailStream())

        router_mid = NativeUnifiedRouter(
            model_list=[
                {"model_name": "m", "litellm_params": {"model": "anthropic/claude-sonnet-4-5", "api_key": "sk-secret-mid-999"}},
                {"model_name": "m", "litellm_params": {"model": "gemini/gemini-2.5-flash", "api_key": "AIza-backup"}},
            ],
            http_transport=httpx.MockTransport(mid_fail_handler),
        )
        gen = router_mid.completion(model="m", stream=True, messages=[{"role": "user", "content": "hi"}])
        first_chunk = next(gen)
        self.assertEqual(first_chunk.choices[0].delta.content, "Partial")
        with self.assertRaises(NativeAPIError) as ctx:
            next(gen)
        self.assertNotIn("sk-secret-mid-999", str(ctx.exception))
        self.assertEqual(mid_attempts[0], 1)

    def test_cloud_iam_fallback_and_secret_redaction_and_zero_litellm_import(self) -> None:
        fallback = MagicMock()
        fallback.completion.return_value = "fallback-ok"
        fallback.create_router.return_value = "fallback-router"

        def fail_secret(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={"error": {"message": "context window exceeded with x-goog-api-key: AIzaLeakTest and prompt is too long"}},
            )

        transport = NativeUnifiedTransport(
            http_transport=httpx.MockTransport(fail_secret),
            fallback_transport=fallback,
        )
        self.assertEqual(
            transport.completion(model="bedrock/anthropic.claude-3-5-sonnet", messages=[]),
            "fallback-ok",
        )
        self.assertEqual(
            transport.create_router(
                [{"model_name": "vx", "litellm_params": {"model": "vertex_ai/gemini-2.5-pro"}}]
            ),
            "fallback-router",
        )

        with self.assertRaises(NativeContextWindowExceededError) as err_ctx:
            transport.completion(
                model="gemini/gemini-2.5-pro",
                api_key="AIzaLeakTest",
                messages=[{"role": "user", "content": "huge prompt"}],
            )
        self.assertNotIn("AIzaLeakTest", str(err_ctx.exception))
        self.assertEqual(transport.resolve_exception("RateLimitError"), NativeRateLimitError)

        # Ensure native transport paths never eagerly import litellm in an isolated process
        self.assertIsInstance(
            create_native_transport(fallback_to_litellm=False),
            NativeUnifiedTransport,
        )
        no_fb = NativeUnifiedTransport(fallback_transport=None)
        with self.assertRaises(NativeBadRequestError):
            no_fb.completion(model="bedrock/claude-3-5-sonnet", messages=[])

        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        probe = (
            "import sys, httpx; "
            "from src.llm import create_native_transport; "
            "h = lambda r: httpx.Response(200, json={'id':'c1','choices':[{'index':0,'message':{'role':'assistant','content':'ok'}}]}); "
            "t = create_native_transport(http_transport=httpx.MockTransport(h), fallback_to_litellm=False); "
            "r = t.completion(model='deepseek/deepseek-chat', api_key='sk-x', messages=[{'role':'user','content':'hi'}]); "
            "assert r.choices[0].message.content == 'ok'; "
            "assert 'litellm' not in sys.modules, 'litellm unexpectedly imported'"
        )
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)

    def test_openai_chat_and_responses_unified_transport_smoke(self) -> None:
        seen_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            seen_urls.append(url)
            if url.endswith("/responses"):
                return httpx.Response(
                    200,
                    json={
                        "id": "resp_smoke",
                        "object": "response",
                        "model": "gpt-5",
                        "output": [{"type": "message", "content": [{"type": "output_text", "text": "responses-ok"}]}],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "id": "chat_smoke",
                    "model": "deepseek-chat",
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "chat-ok"}}],
                },
            )

        transport = create_native_transport(
            http_transport=httpx.MockTransport(handler),
            fallback_to_litellm=False,
        )
        r_chat = transport.completion(
            model="deepseek/deepseek-chat",
            api_key="sk-ds",
            messages=[{"role": "user", "content": "ping"}],
        )
        r_resp = transport.completion(
            model="openai/gpt-5",
            api_key="sk-oa",
            messages=[{"role": "user", "content": "ping"}],
        )
        self.assertEqual(r_chat.choices[0].message.content, "chat-ok")
        self.assertEqual(r_resp.choices[0].message.content, "responses-ok")
        self.assertTrue(seen_urls[0].endswith("/chat/completions"))
        self.assertTrue(seen_urls[1].endswith("/responses"))


if __name__ == "__main__":
    unittest.main()
