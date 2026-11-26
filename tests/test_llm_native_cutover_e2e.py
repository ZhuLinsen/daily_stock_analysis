# -*- coding: utf-8 -*-
"""End-to-end cutover tests for Issue #2622 Phase 2c (all 7 call sites + zero-litellm proof)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
import openai

from src.agent import chat_context, llm_adapter
from src.agent.llm_adapter import LLMToolAdapter
from src.analyzer import GeminiAnalyzer
from src.config import Config, get_litellm_model_providers
from src.llm import (
    NativeUnifiedRouter,
    NativeUnifiedTransport,
    create_native_transport,
    reset_transport_cache,
    resolve_llm_transport_mode,
    use_transport,
)
from src.services import image_stock_extractor
from src.services.screening import ranker
from src.services.screening_service import _screening_litellm_headers
from src.services.system_config_service import SystemConfigService


class RuntimeTransportModeTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_transport_cache()
        get_litellm_model_providers.cache_clear()

    def test_resolve_llm_transport_mode_and_unknown_fallback(self) -> None:
        self.assertEqual(resolve_llm_transport_mode(""), "litellm")
        self.assertEqual(resolve_llm_transport_mode("litellm"), "litellm")
        self.assertEqual(resolve_llm_transport_mode("auto"), "auto")
        self.assertEqual(resolve_llm_transport_mode("native_httpx"), "auto")
        self.assertEqual(resolve_llm_transport_mode("hybrid"), "auto")
        self.assertEqual(resolve_llm_transport_mode("native"), "native")
        self.assertEqual(resolve_llm_transport_mode("native_only"), "native")
        self.assertEqual(resolve_llm_transport_mode("httpx"), "native")

        with self.assertLogs("src.llm.transport", level=logging.WARNING) as cm:
            self.assertEqual(resolve_llm_transport_mode("unknown_mode"), "litellm")
        self.assertTrue(any("Unsupported LLM_TRANSPORT_MODE" in line for line in cm.output))

    def test_config_loads_llm_transport_mode_and_native_providers(self) -> None:
        env = {
            "LLM_TRANSPORT_MODE": "native",
            "LITELLM_MODEL": "anthropic/claude-sonnet-4-5",
            "ANTHROPIC_API_KEY": "sk-ant-test-key",
        }
        with patch.dict(os.environ, env, clear=False):
            reset_transport_cache()
            get_litellm_model_providers.cache_clear()
            cfg = Config._load_from_env()
            self.assertEqual(cfg.llm_transport_mode, "native")
            providers = get_litellm_model_providers()
            self.assertIn("anthropic", providers)
            self.assertIn("gemini", providers)
            self.assertIn("openai", providers)


class NativeCutoverE2ETests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_transport_cache()

    def test_analyzer_router_direct_and_hermes_no_proxy_client_cutover(self) -> None:
        requests_seen: list[tuple[str, dict]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            requests_seen.append((str(request.url), body))
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl_1",
                    "model": body.get("model", "deepseek-chat"),
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": '{"ok": true}'},
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )

        transport = create_native_transport(
            http_transport=httpx.MockTransport(handler),
            fallback_to_litellm=False,
        )

        # Multi-key legacy Router initialization must accept routing_strategy without TypeError
        cfg = Config(
            deepseek_api_keys=["sk-ds-key-1", "sk-ds-key-2"],
            litellm_model="deepseek/deepseek-chat",
            llm_model_list=[],
        )
        analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
        analyzer._get_runtime_config = lambda: cfg
        analyzer._router = None
        analyzer._litellm_available = False

        with use_transport(transport):
            analyzer._init_litellm()
            self.assertIsInstance(analyzer._router, NativeUnifiedRouter)
            resp = analyzer._dispatch_litellm_completion(
                "deepseek/deepseek-chat",
                {
                    "model": "deepseek/deepseek-chat",
                    "messages": [{"role": "user", "content": "Analyze"}],
                },
                config=cfg,
                use_channel_router=False,
                router_model_names=set(),
            )
        self.assertEqual(resp.choices[0].message.content, '{"ok": true}')

        # Hermes no-proxy injected client must keep caller client open & omit client from JSON body
        hermes_reqs: list[tuple[str, str, dict]] = []

        def hermes_handler(request: httpx.Request) -> httpx.Response:
            hermes_reqs.append(
                (
                    str(request.url),
                    request.headers.get("authorization", ""),
                    json.loads(request.content.decode("utf-8")),
                )
            )
            return httpx.Response(
                200,
                json={
                    "id": "hermes_1",
                    "model": "hermes-agent",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "hermes response"},
                        }
                    ],
                },
            )

        hermes_cfg = Config(
            litellm_model="hermes/hermes-agent",
            llm_model_list=[
                {
                    "model_name": "hermes/hermes-agent",
                    "litellm_params": {
                        "model": "openai/hermes-agent",
                        "api_base": "http://127.0.0.1:8642/v1",
                        "api_key": "hermes-local-key",
                    },
                    "model_info": {"dsa_channel": "hermes"},
                }
            ],
        )
        analyzer._router = None
        analyzer._get_runtime_config = lambda: hermes_cfg
        raw_http = httpx.Client(transport=httpx.MockTransport(hermes_handler), trust_env=False)
        wrapped_openai = openai.OpenAI(
            api_key="hermes-local-key",
            base_url="http://127.0.0.1:8642/v1",
            http_client=raw_http,
        )
        try:
            # Hermes transport calls with default NativeUnifiedTransport() (no custom http_transport)
            hermes_native = create_native_transport(fallback_to_litellm=False)
            with use_transport(hermes_native), patch(
                "src.analyzer.open_hermes_no_proxy_client"
            ) as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = wrapped_openai
                mock_ctx.return_value.__exit__.return_value = False
                hermes_resp = analyzer._dispatch_litellm_completion(
                    "hermes/hermes-agent",
                    {
                        "model": "hermes/hermes-agent",
                        "messages": [{"role": "user", "content": "Hello Hermes"}],
                    },
                    config=hermes_cfg,
                    use_channel_router=False,
                    router_model_names=set(),
                )
            self.assertEqual(hermes_resp.choices[0].message.content, "hermes response")
            self.assertFalse(raw_http.is_closed)
            self.assertEqual(hermes_reqs[0][0], "http://127.0.0.1:8642/v1/chat/completions")
            self.assertEqual(hermes_reqs[0][1], "Bearer hermes-local-key")
            self.assertNotIn("client", hermes_reqs[0][2])
        finally:
            raw_http.close()

    def test_agent_llm_adapter_and_chat_context_end_to_end_native(self) -> None:
        turn_bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            turn_bodies.append(body)
            if len(turn_bodies) == 1:
                return httpx.Response(
                    200,
                    json={
                        "responseId": "gem_agent_1",
                        "modelVersion": "gemini-2.5-pro",
                        "candidates": [
                            {
                                "index": 0,
                                "finishReason": "STOP",
                                "content": {
                                    "role": "model",
                                    "parts": [
                                        {
                                            "functionCall": {"name": "get_quote", "args": {"code": "600519"}},
                                            "thoughtSignature": "sig_agent_loop_1",
                                        }
                                    ],
                                },
                            }
                        ],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "responseId": "gem_agent_2",
                    "modelVersion": "gemini-2.5-pro",
                    "candidates": [
                        {
                            "index": 0,
                            "finishReason": "STOP",
                            "content": {"role": "model", "parts": [{"text": "Quote confirmed."}]},
                        }
                    ],
                },
            )

        transport = create_native_transport(
            http_transport=httpx.MockTransport(handler),
            fallback_to_litellm=False,
        )
        cfg = Config(
            litellm_model="gemini/gemini-2.5-pro",
            gemini_api_key="AIzaAgentKey123",
            gemini_api_keys=["AIzaAgentKey123", "AIzaAgentKey456"],
            llm_model_list=[],
        )
        with use_transport(transport):
            adapter = LLMToolAdapter(config=cfg)
            self.assertIsInstance(adapter._router, NativeUnifiedRouter)
            toks = chat_context.estimate_text_tokens("Quant factor momentum score", cfg)
            self.assertGreater(toks, 0)

            r1 = adapter.call_with_tools(
                messages=[{"role": "user", "content": "Get 600519 quote"}],
                tools=[
                    {
                        "name": "get_quote",
                        "description": "Fetch quote",
                        "parameters": {"type": "object", "properties": {"code": {"type": "string"}}},
                    }
                ],
            )
            self.assertEqual(r1.tool_calls[0].thought_signature, "sig_agent_loop_1")

            r2 = adapter.call_with_tools(
                messages=[
                    {"role": "user", "content": "Get 600519 quote"},
                    {
                        "role": "assistant",
                        "content": r1.content,
                        "tool_calls": [
                            {
                                "id": r1.tool_calls[0].id,
                                "name": r1.tool_calls[0].name,
                                "arguments": r1.tool_calls[0].arguments,
                                "thought_signature": r1.tool_calls[0].thought_signature,
                                "provider_specific_fields": r1.tool_calls[0].provider_specific_fields,
                            }
                        ],
                        "_trace_provider": "gemini",
                        "_trace_model": "gemini/gemini-2.5-pro",
                    },
                    {"role": "tool", "name": "get_quote", "tool_call_id": r1.tool_calls[0].id, "content": '{"price": 1500}'},
                ],
                tools=[],
            )
        self.assertEqual(r2.content, "Quote confirmed.")
        self.assertEqual(turn_bodies[1]["contents"][1]["parts"][0]["thoughtSignature"], "sig_agent_loop_1")

    def test_screening_ranker_headers_vision_and_system_config_channel_test(self) -> None:
        captured_headers: list[dict] = []
        captured_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_urls.append(str(request.url))
            captured_headers.append(dict(request.headers))
            url = str(request.url)
            if "generativelanguage.googleapis.com" in url:
                return httpx.Response(
                    200,
                    json={
                        "responseId": "gem_vis_1",
                        "candidates": [
                            {
                                "index": 0,
                                "finishReason": "STOP",
                                "content": {"role": "model", "parts": [{"text": '[{"code":"600519","name":"Kweichow","confidence":"high"}]'}]},
                            }
                        ],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "id": "rank_1",
                    "model": "gpt-4o",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": '{"status":"ok"}'},
                        }
                    ],
                },
            )

        transport = create_native_transport(
            http_transport=httpx.MockTransport(handler),
            fallback_to_litellm=False,
        )
        cfg = Config(
            litellm_model="gemini/gemini-2.5-flash",
            gemini_api_key="AIzaVisionKey",
            gemini_api_keys=["AIzaVisionKey"],
            llm_model_list=[
                {
                    "model_name": "openai/gpt-4o",
                    "litellm_params": {
                        "model": "openai/gpt-4o",
                        "api_key": "sk-rank-key",
                        "api_base": "https://proxy.example/v1",
                        "extra_headers": {"X-Channel-Tag": "screener-v1"},
                    },
                }
            ],
        )

        with use_transport(transport):
            with _screening_litellm_headers(cfg):
                rank_out = ranker._call_llm(
                    prompt="Rank stocks",
                    api_key="sk-rank-key",
                    model="openai/gpt-4o",
                    base_url="https://proxy.example/v1",
                )
            self.assertEqual(rank_out, '{"status":"ok"}')
            self.assertEqual(captured_headers[0].get("x-channel-tag"), "screener-v1")

            with patch("src.services.image_stock_extractor.get_config", return_value=cfg):
                vis_out = image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png", api_key="AIzaVisionKey")
            self.assertIn("600519", vis_out)
            self.assertIn("generativelanguage.googleapis.com", captured_urls[-1])

            service = SystemConfigService()
            channel_res = service.test_llm_channel(
                name="primary_openai",
                protocol="openai",
                base_url="https://proxy.example/v1",
                api_key="sk-test-channel",
                models=["openai/gpt-4o"],
                capability_checks=["json"],
            )
        self.assertTrue(channel_res["success"])
        self.assertEqual(channel_res["capability_results"]["json"]["status"], "passed")


class LegacyPatchCompatTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_transport_cache()

    def test_legacy_litellm_module_completion_patches_still_work_in_default_mode(self) -> None:
        fake_resp = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="legacy-patch-ok"))]
        )
        with patch.dict(os.environ, {"LLM_TRANSPORT_MODE": "litellm"}, clear=False):
            reset_transport_cache()
            with patch.object(image_stock_extractor.litellm, "completion", return_value=fake_resp) as patched_vis:
                cfg = Config(litellm_model="openai/gpt-4o", openai_api_key="sk-legacy", openai_api_keys=["sk-legacy"])
                with patch("src.services.image_stock_extractor.get_config", return_value=cfg):
                    res = image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png")
            self.assertEqual(res, "legacy-patch-ok")
            self.assertEqual(patched_vis.call_count, 1)


class SubprocessZeroLiteLLMProofTest(unittest.TestCase):
    def test_fresh_process_with_native_mode_never_imports_litellm(self) -> None:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        probe = """
import json, os, sys
os.environ["LLM_TRANSPORT_MODE"] = "native"
os.environ["LITELLM_MODEL"] = "anthropic/claude-sonnet-4-5"
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-subprocess"

import httpx
from src.config import Config, get_litellm_model_providers
from src.analyzer import GeminiAnalyzer
from src.agent import chat_context, llm_adapter
from src.services import image_stock_extractor, screening_service, system_config_service
from src.services.screening import ranker
from src.llm import create_native_transport, use_transport

assert "litellm" not in sys.modules, f"litellm imported at module load: {sys.modules.get('litellm')}"

providers = get_litellm_model_providers()
assert "anthropic" in providers and "gemini" in providers
assert "litellm" not in sys.modules, "litellm imported by get_litellm_model_providers()"

cfg = Config._load_from_env()
assert cfg.llm_transport_mode == "native"
assert chat_context.estimate_text_tokens("Hello World Token Test", cfg) > 0

def handler(req):
    return httpx.Response(200, json={
        "id": "msg_sub_1",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "native subprocess ok"}],
        "usage": {"input_tokens": 5, "output_tokens": 3},
    })

transport = create_native_transport(http_transport=httpx.MockTransport(handler), fallback_to_litellm=False)
analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
analyzer._config = cfg
analyzer._router = None
analyzer._litellm_available = False

with use_transport(transport):
    resp = analyzer._dispatch_litellm_completion(
        "anthropic/claude-sonnet-4-5",
        {"model": "anthropic/claude-sonnet-4-5", "messages": [{"role": "user", "content": "hi"}]},
        config=cfg,
        use_channel_router=False,
        router_model_names=set(),
    )
assert resp.choices[0].message.content == "native subprocess ok"
assert "litellm" not in sys.modules, f"litellm unexpectedly imported: {list(k for k in sys.modules if 'litellm' in k)}"
"""
        env = dict(os.environ)
        env["LLM_TRANSPORT_MODE"] = "native"
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)

    def test_native_router_honors_num_retries_for_transient_errors_and_excludes_auth_failures(self) -> None:
        import json as json_mod
        import httpx

        from src.llm.native_types import NativeBadRequestError
        from src.llm.transport import NativeUnifiedRouter

        # Case A: Single deployment recovers on retry 2 after 429 + 503; filtered kwargs absent from JSON.
        seen_payloads: list[dict] = []
        sleep_calls: list[float] = []
        attempt = {"count": 0}

        def transient_handler(request: httpx.Request) -> httpx.Response:
            attempt["count"] += 1
            seen_payloads.append(json_mod.loads(request.content.decode("utf-8")))
            if attempt["count"] == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "0.25"},
                    json={"error": {"message": "rate limited"}},
                )
            if attempt["count"] == 2:
                return httpx.Response(503, json={"error": {"message": "upstream unavailable"}})
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-retry-ok",
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "recovered"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                },
            )

        router = NativeUnifiedRouter(
            model_list=[
                {
                    "model_name": "gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "sk-transient",
                        "api_base": "https://api.example.com/v1",
                    },
                }
            ],
            http_transport=httpx.MockTransport(transient_handler),
            num_retries=2,
            cooldown_time=0.0,
            sleep_fn=sleep_calls.append,
        )
        resp = router.completion(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "ping"}],
            fallbacks=[{"model": "unused"}],
            metadata={"trace": "abc"},
            caching=False,
        )
        self.assertEqual(resp.choices[0].message.content, "recovered")
        self.assertEqual(attempt["count"], 3)
        self.assertEqual(len(sleep_calls), 2)
        for payload in seen_payloads:
            for filtered_key in ("num_retries", "fallbacks", "metadata", "caching"):
                self.assertNotIn(filtered_key, payload)

        # Case B: 401 bad auth key is excluded from subsequent retry rounds.
        key_hits = {"sk-bad": 0, "sk-good": 0}

        def auth_split_handler(request: httpx.Request) -> httpx.Response:
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            key_hits[token] = key_hits.get(token, 0) + 1
            if token == "sk-bad":
                return httpx.Response(401, json={"error": {"message": "invalid api key"}})
            if key_hits["sk-good"] == 1:
                return httpx.Response(429, json={"error": {"message": "temporary throttle"}})
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-good",
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok-after-auth-skip"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                },
            )

        auth_router = NativeUnifiedRouter(
            model_list=[
                {
                    "model_name": "gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "sk-bad",
                        "api_base": "https://api.example.com/v1",
                    },
                },
                {
                    "model_name": "gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "sk-good",
                        "api_base": "https://api.example.com/v1",
                    },
                },
            ],
            http_transport=httpx.MockTransport(auth_split_handler),
            num_retries=1,
            cooldown_time=0.0,
            sleep_fn=lambda _delay: None,
        )
        auth_resp = auth_router.completion(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
        )
        self.assertEqual(auth_resp.choices[0].message.content, "ok-after-auth-skip")
        self.assertEqual(key_hits["sk-bad"], 1)
        self.assertEqual(key_hits["sk-good"], 2)

        # Case C: Deterministic 400 fails fast without retries or sleeps.
        bad_req_calls = {"count": 0}
        bad_req_sleeps: list[float] = []

        def bad_request_handler(_request: httpx.Request) -> httpx.Response:
            bad_req_calls["count"] += 1
            return httpx.Response(400, json={"error": {"message": "bad payload"}})

        bad_router = NativeUnifiedRouter(
            model_list=[
                {
                    "model_name": "gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "sk-badreq",
                        "api_base": "https://api.example.com/v1",
                    },
                }
            ],
            http_transport=httpx.MockTransport(bad_request_handler),
            num_retries=2,
            cooldown_time=0.0,
            sleep_fn=bad_req_sleeps.append,
        )
        with self.assertRaises(NativeBadRequestError):
            bad_router.completion(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(bad_req_calls["count"], 1)
        self.assertEqual(bad_req_sleeps, [])

    def test_native_stream_retries_pre_first_chunk_and_aborts_post_first_chunk(self) -> None:
        import httpx

        from src.llm.native_types import NativeAPIError
        from src.llm.transport import NativeUnifiedRouter

        # Part A: Pre-first-chunk 429 retries cleanly and completes stream.
        pre_attempts = {"count": 0}
        pre_sleeps: list[float] = []

        def pre_chunk_handler(_request: httpx.Request) -> httpx.Response:
            pre_attempts["count"] += 1
            if pre_attempts["count"] == 1:
                return httpx.Response(429, json={"error": {"message": "rate limit"}})
            sse_body = (
                b'data: {"id":"1","choices":[{"index":0,"delta":{"content":"hello"}}]}\n\n'
                b"data: [DONE]\n\n"
            )
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=sse_body,
            )

        pre_router = NativeUnifiedRouter(
            model_list=[
                {
                    "model_name": "gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "sk-stream-pre",
                        "api_base": "https://api.example.com/v1",
                    },
                }
            ],
            http_transport=httpx.MockTransport(pre_chunk_handler),
            num_retries=1,
            cooldown_time=0.0,
            sleep_fn=pre_sleeps.append,
        )
        chunks = list(
            pre_router.completion(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
        )
        text = "".join(c.choices[0].delta.content or "" for c in chunks)
        self.assertEqual(text, "hello")
        self.assertEqual(pre_attempts["count"], 2)
        self.assertEqual(len(pre_sleeps), 1)

        # Part B: Error after yielding first chunk aborts immediately without retry.
        class MidStreamBreakByteStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b'data: {"id":"2","choices":[{"index":0,"delta":{"content":"partial"}}]}\n\n'
                raise httpx.ReadError("stream interrupted")

        post_attempts = {"count": 0}
        post_sleeps: list[float] = []

        def post_chunk_handler(_request: httpx.Request) -> httpx.Response:
            post_attempts["count"] += 1
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=MidStreamBreakByteStream(),
            )

        post_router = NativeUnifiedRouter(
            model_list=[
                {
                    "model_name": "gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "sk-stream-post",
                        "api_base": "https://api.example.com/v1",
                    },
                }
            ],
            http_transport=httpx.MockTransport(post_chunk_handler),
            num_retries=2,
            cooldown_time=0.0,
            sleep_fn=post_sleeps.append,
        )
        stream_iter = post_router.completion(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
        first = next(stream_iter)
        self.assertEqual(first.choices[0].delta.content, "partial")
        with self.assertRaises(NativeAPIError):
            next(stream_iter)
        self.assertEqual(post_attempts["count"], 1)
        self.assertEqual(post_sleeps, [])

    def test_native_router_stops_retrying_when_stock_cancelled(self) -> None:
        from concurrent.futures import CancelledError
        import httpx

        from src.core.stock_execution_context import (
            StockCancellationToken,
            set_current_stock_cancellation,
        )
        from src.llm.transport import NativeUnifiedRouter

        token = StockCancellationToken()
        calls = {"count": 0}

        def fail_once_handler(_request: httpx.Request) -> httpx.Response:
            calls["count"] += 1
            return httpx.Response(503, json={"error": {"message": "server busy"}})

        def cancel_during_backoff(_delay: float) -> None:
            token.cancel()

        router = NativeUnifiedRouter(
            model_list=[
                {
                    "model_name": "gpt-4o-mini",
                    "litellm_params": {
                        "model": "openai/gpt-4o-mini",
                        "api_key": "sk-cancel",
                        "api_base": "https://api.example.com/v1",
                    },
                }
            ],
            http_transport=httpx.MockTransport(fail_once_handler),
            num_retries=3,
            cooldown_time=0.0,
            sleep_fn=cancel_during_backoff,
        )
        prev = set_current_stock_cancellation(token)
        try:
            with self.assertRaises(CancelledError):
                router.completion(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
        finally:
            set_current_stock_cancellation(prev)
        self.assertEqual(calls["count"], 1)

    def test_auto_mode_resolve_exception_types_matches_both_native_and_loaded_litellm_errors(self) -> None:
        import types

        from src.llm.native_types import NativeRateLimitError
        from src.llm.transport import (
            LiteLLMTransport,
            resolve_exception_types,
            use_transport,
        )

        # Part A: In native mode with no litellm in sys.modules, resolve_exception_types does not import litellm.
        saved_litellm = sys.modules.pop("litellm", None)
        try:
            with use_transport(NativeUnifiedTransport(fallback_transport=None)):
                native_only_types = resolve_exception_types("RateLimitError")
                self.assertEqual(native_only_types, (NativeRateLimitError,))
                self.assertNotIn("litellm", sys.modules)
        finally:
            if saved_litellm is not None:
                sys.modules["litellm"] = saved_litellm

        # Part B: In auto mode with loaded litellm module, exception tuple matches both native and litellm classes.
        from src.agent.llm_adapter import _resolve_litellm_exception

        class DummyLiteLLMRateLimitError(Exception):
            pass

        fake_litellm = types.ModuleType("litellm")
        fake_litellm.RateLimitError = DummyLiteLLMRateLimitError

        with patch.dict(sys.modules, {"litellm": fake_litellm}):
            with use_transport(NativeUnifiedTransport(fallback_transport=LiteLLMTransport())):
                hybrid_types = resolve_exception_types("RateLimitError")
                self.assertIn(NativeRateLimitError, hybrid_types)
                self.assertIn(DummyLiteLLMRateLimitError, hybrid_types)
                adapter_types = _resolve_litellm_exception("RateLimitError")
                self.assertIn(NativeRateLimitError, adapter_types)
                self.assertIn(DummyLiteLLMRateLimitError, adapter_types)

    def test_config_registry_and_doctor_surface_llm_transport_mode(self) -> None:
        import tempfile

        from src.config import Config
        from src.core.config_registry import get_field_definition
        from src.llm.transport import get_transport_for_config
        from src.services.doctor_service import format_doctor_report, run_doctor_diagnostics

        field_meta = get_field_definition("LLM_TRANSPORT_MODE")
        self.assertIsNotNone(field_meta)
        self.assertEqual(field_meta["category"], "ai_model")
        self.assertEqual(field_meta["ui_control"], "select")
        self.assertEqual(field_meta["default_value"], "litellm")
        self.assertEqual(field_meta["validation"]["enum"], ["litellm", "auto", "native"])
        self.assertEqual(field_meta["help_key"], "settings.ai_model.LLM_TRANSPORT_MODE")

        clean_env = dict(os.environ)
        clean_env.pop("LLM_TRANSPORT_MODE", None)
        with patch.dict(os.environ, clean_env, clear=True):
            cfg = Config(stock_list=["600519"], llm_transport_mode="native")
            transport = get_transport_for_config(cfg)
            self.assertIsInstance(transport, NativeUnifiedTransport)
            self.assertIsNone(transport._fallback_transport)

            with tempfile.TemporaryDirectory() as tmpdir:
                doctor_cfg = Config(
                    stock_list=["600519"],
                    llm_transport_mode="native",
                    database_path=f"{tmpdir}/stock_analysis.db",
                    log_dir=tmpdir,
                )
                report = run_doctor_diagnostics(doctor_cfg)
                self.assertEqual(report["checks"]["llm"]["llm_transport_mode"], "native")
                formatted = format_doctor_report(report)
                self.assertIn("transport=native", formatted)


if __name__ == "__main__":
    unittest.main()
