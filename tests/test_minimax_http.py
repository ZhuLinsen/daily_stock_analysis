"""Exercise the real LiteLLM/OpenAI stack with only its HTTP transport replaced."""

import os
from pathlib import Path
import subprocess
import sys
import unittest


class MiniMaxHTTPTest(unittest.TestCase):
    def test_real_sdk_contract(self):
        # Other unit tests intentionally install a LiteLLM stub. A fresh process
        # makes this contract independent of collection order and those stubs.
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "LITELLM_TELEMETRY": "False",
        }
        result = subprocess.run(
            [sys.executable, __file__, "--transport-contract"],
            env=env, capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def run_transport_contract():
    import json
    import traceback
    from unittest.mock import patch

    import httpx
    import litellm
    from openai._base_client import SyncAPIClient
    from src.agent.llm_adapter import LLMToolAdapter, register_fallback_model_pricing
    from src.config import Config

    assert not getattr(litellm, "__dsa_test_stub__", False)
    tools = [{"type": "function", "function": {
        "name": "get_price", "description": "Get a stock price",
        "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}},
                       "required": ["symbol"]},
    }}]
    image_urls = [
        "https://example.com/chart.png",
        "data:image/png;base64,iVBORw0KGgo=",
    ]
    cases = [(model, "https://api.minimax.io/v1") for model in (
        "MiniMax-M3.1-Flash", "MiniMax-M3", "MiniMax-M2.7", "custom-model", "gpt-4o",
    )] + [
        ("MiniMax-M3.1-Flash", "https://api.minimax.com/v1"),
        ("MiniMax-M3.1-Flash", "https://custom.example/v1"),
    ]
    for model, base_url in cases:
        requests = []

        def handle_request(_transport, request):
            # No network, including unexpected endpoints, may escape this boundary.
            assert str(request.url) == base_url + "/chat/completions"
            assert request.headers["authorization"] == "Bearer test-only"
            body = json.loads(request.read())
            requests.append(body)
            assert body["model"] == model
            assert body.get("thinking", {}).get("type") != "disabled"
            assert body.get("reasoning_effort") != "none"
            assert "service_tier" not in body
            assert body.get("reasoning_split") is not False
            if "tools" not in body:
                assert body["messages"][-1]["content"] == "Analyze the current market."
                return httpx.Response(200, request=request, json={
                    "id": "chatcmpl-text", "object": "chat.completion", "created": 1,
                    "model": model, "choices": [{"index": 0, "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Market analysis complete."}}],
                })
            assert body["tools"] == tools
            # LiteLLM may omit the default; both forms mean automatic tool choice.
            assert body.get("tool_choice", "auto") == "auto"
            assert [part["image_url"]["url"] for part in body["messages"][1]["content"]
                    if part["type"] == "image_url"] == image_urls
            if len(requests) == 1:
                message = {"role": "assistant", "content": None, "reasoning_content": "fixture reasoning",
                           "tool_calls": [{"id": "price-1", "type": "function", "function": {
                               "name": "get_price", "arguments": '{"symbol":"AAPL"}',
                           }}]}
                finish = "tool_calls"
            else:
                assistant = body["messages"][-2]
                assert assistant["reasoning_content"] == "fixture reasoning"
                assert assistant["tool_calls"][0]["id"] == "price-1"
                assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"symbol": "AAPL"}
                assert body["messages"][-1] == {
                    "role": "tool", "tool_call_id": "price-1", "content": '{"price": 123}',
                }
                message = {"role": "assistant", "content": "The price is 123."}
                finish = "stop"
            return httpx.Response(200, request=request, json={
                "id": "chatcmpl-test", "object": "chat.completion", "created": 1,
                "model": model, "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            })

        transport_errors = []

        def send_request(client, request, **_kwargs):
            # Intercept the fully serialized request regardless of whether the
            # current OpenAI/LiteLLM combination chooses httpx or httpx2.
            try:
                return handle_request(client, request)
            except Exception:
                transport_errors.append(traceback.format_exc())
                raise

        env = {
            "LLM_CHANNELS": "minimax",
            "LLM_MINIMAX_PROTOCOL": "openai",
            "LLM_MINIMAX_BASE_URL": base_url,
            "LLM_MINIMAX_API_KEY": "test-only",
            "LLM_MINIMAX_MODELS": (
                "MiniMax-M3.1-Flash,MiniMax-M3"
                if model == "MiniMax-M3.1-Flash" and base_url == "https://api.minimax.io/v1"
                else model
            ),
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "LITELLM_TELEMETRY": "False",
        }
        with patch.dict(os.environ, env, clear=True), patch("src.config.setup_env"), \
                patch.object(Config, "_parse_litellm_yaml", return_value=[]), \
                patch.object(SyncAPIClient, "_send_request", send_request), \
                patch("socket.socket.connect", side_effect=AssertionError("Unexpected network access")):
            config = Config._load_from_env()
            assert config.litellm_model == "openai/" + model
            adapter = LLMToolAdapter(config)
            assert adapter.is_available
            messages = [
                {"role": "system", "content": "Analyze the chart using the tool."},
                {"role": "user", "content": [
                    {"type": "text", "text": "What is the current price?"},
                    *[{"type": "image_url", "image_url": {"url": url}} for url in image_urls],
                ]},
            ]
            first = adapter.call_with_tools(messages, tools, timeout=15)
            assert not transport_errors, "\n".join(transport_errors)
            assert first.tool_calls, first.content
            assert first.reasoning_content == "fixture reasoning"
            call = first.tool_calls[0]
            assert (call.id, call.name, call.arguments) == ("price-1", "get_price", {"symbol": "AAPL"})
            messages += [
                {"role": "assistant", "content": first.content, "reasoning_content": first.reasoning_content,
                 "tool_calls": [{"id": call.id, "name": call.name, "arguments": call.arguments}]},
                {"role": "tool", "tool_call_id": call.id, "content": {"price": 123}},
            ]
            second = adapter.call_with_tools(messages, tools, timeout=15)
            assert not transport_errors, "\n".join(transport_errors)
            assert second.content == "The price is 123.", second.content
            assert len(requests) == 2
            if model == "MiniMax-M3.1-Flash" and base_url == "https://api.minimax.io/v1":
                from src.analyzer import GeminiAnalyzer

                analyzer = GeminiAnalyzer(config=config)
                assert analyzer.generate_text("Analyze the current market.") == "Market analysis complete."
                assert len(requests) == 3

    # Verify YAML deployment extra_body (e.g. OpenRouter provider routing & privacy)
    # is preserved and merged with reasoning_effort=low across Agent, Analyzer,
    # explicit user overrides, and multi-deployment Router retries.
    openrouter_url = "https://openrouter.ai/api/v1"
    openrouter_model = "openai/minimax/minimax-m3.1-flash"
    provider_policy = {
        "only": ["minimax"],
        "allow_fallbacks": False,
        "data_collection": "deny",
    }
    openrouter_requests = []
    openrouter_errors = []

    def handle_openrouter(_transport, request):
        assert str(request.url) == openrouter_url + "/chat/completions"
        body = json.loads(request.read())
        auth = request.headers["authorization"]
        openrouter_requests.append((auth, body))
        if auth == "Bearer key-fail-once":
            return httpx.Response(500, request=request, json={"error": {"message": "transient upstream error"}})
        return httpx.Response(200, request=request, json={
            "id": "chatcmpl-or", "object": "chat.completion", "created": 1,
            "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "OpenRouter response ok."}}],
        })

    def send_openrouter(client, request, **_kwargs):
        try:
            return handle_openrouter(client, request)
        except Exception:
            openrouter_errors.append(traceback.format_exc())
            raise

    yaml_model_list = [
        {
            "model_name": openrouter_model,
            "litellm_params": {
                "model": openrouter_model,
                "api_base": openrouter_url,
                "api_key": "test-only",
                "extra_body": {"provider": dict(provider_policy)},
            },
        }
    ]
    override_model_list = [
        {
            "model_name": openrouter_model,
            "litellm_params": {
                "model": openrouter_model,
                "api_base": openrouter_url,
                "api_key": "test-override",
                "extra_body": {
                    "provider": dict(provider_policy),
                    "reasoning_effort": "high",
                },
            },
        }
    ]
    retry_model_list = [
        {
            "model_name": openrouter_model,
            "litellm_params": {
                "model": openrouter_model,
                "api_base": openrouter_url,
                "api_key": "key-fail-once",
                "extra_body": {"provider": {"only": ["minimax-primary"], "allow_fallbacks": False}},
            },
        },
        {
            "model_name": openrouter_model,
            "litellm_params": {
                "model": openrouter_model,
                "api_base": openrouter_url,
                "api_key": "key-backup",
                "extra_body": {"provider": {"only": ["minimax-backup"], "data_collection": "deny"}},
            },
        },
    ]

    with patch.object(SyncAPIClient, "_send_request", send_openrouter), \
            patch("socket.socket.connect", side_effect=AssertionError("Unexpected network access")):
        from src.analyzer import GeminiAnalyzer

        yaml_cfg = Config(
            stock_list=[],
            litellm_model=openrouter_model,
            llm_model_list=yaml_model_list,
        )
        or_adapter = LLMToolAdapter(yaml_cfg)
        assert or_adapter.call_text([{"role": "user", "content": "Hello"}]).content == "OpenRouter response ok."
        assert or_adapter.call_with_tools([{"role": "user", "content": "Hello"}], tools).content == "OpenRouter response ok."
        or_analyzer = GeminiAnalyzer(config=yaml_cfg)
        assert or_analyzer.generate_text("Analyze OpenRouter.") == "OpenRouter response ok."
        assert not openrouter_errors, "\n".join(openrouter_errors)
        assert len(openrouter_requests) == 3
        for _auth, body in openrouter_requests:
            assert body.get("provider") == provider_policy, body
            assert body.get("reasoning_effort") == "low", body

        openrouter_requests.clear()
        override_cfg = Config(
            stock_list=[],
            litellm_model=openrouter_model,
            llm_model_list=override_model_list,
        )
        assert LLMToolAdapter(override_cfg).call_text([{"role": "user", "content": "Hi"}]).content == "OpenRouter response ok."
        assert GeminiAnalyzer(config=override_cfg).generate_text("Hi") == "OpenRouter response ok."
        assert not openrouter_errors, "\n".join(openrouter_errors)
        assert len(openrouter_requests) == 2
        for _auth, body in openrouter_requests:
            assert body.get("provider") == provider_policy, body
            assert body.get("reasoning_effort") == "high", body

        openrouter_requests.clear()
        retry_cfg = Config(
            stock_list=[],
            litellm_model=openrouter_model,
            llm_model_list=retry_model_list,
        )
        retry_adapter = LLMToolAdapter(retry_cfg)
        with patch.object(
            retry_adapter._router,
            "get_available_deployment",
            side_effect=[retry_adapter._router.model_list[0], retry_adapter._router.model_list[1]],
        ):
            assert retry_adapter.call_text([{"role": "user", "content": "Retry"}]).content == "OpenRouter response ok."
        assert not openrouter_errors, "\n".join(openrouter_errors)
        assert len(openrouter_requests) == 2
        assert openrouter_requests[0][0] == "Bearer key-fail-once"
        assert openrouter_requests[0][1].get("provider") == {"only": ["minimax-primary"], "allow_fallbacks": False}
        assert openrouter_requests[0][1].get("reasoning_effort") == "low"
        assert openrouter_requests[1][0] == "Bearer key-backup"
        assert openrouter_requests[1][1].get("provider") == {"only": ["minimax-backup"], "data_collection": "deny"}
        assert openrouter_requests[1][1].get("reasoning_effort") == "low"

    # The real SDK's registry must expose the capacities used for token budgeting.
    register_fallback_model_pricing(["openai/MiniMax-M3.1-Flash"])
    info = litellm.model_cost["MiniMax-M3.1-Flash"]
    assert info["context_window"] == 1000000
    assert info["max_tokens"] == 524288
    assert info["supports_vision"] and info["supports_function_calling"]
    assert info["supports_audio_input"] is False and info["supports_audio_output"] is False
    assert info["input_cost_per_token"] == 0.00000015
    assert info["output_cost_per_token"] == 0.0000006
    assert info["cache_read_input_token_cost"] == 0.000000015
    print("Real SDK HTTP: 7 cases + OpenRouter extra_body preservation/override/retry verified")


if __name__ == "__main__":
    if "--transport-contract" in sys.argv:
        run_transport_contract()
    else:
        unittest.main()
