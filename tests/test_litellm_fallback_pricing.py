# -*- coding: utf-8 -*-
"""Tests for fallback LiteLLM pricing registration."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from src.agent import llm_adapter


def _fake_litellm_response(content: str = "agent ok") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=[],
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )


def _fake_agent_config(**overrides) -> SimpleNamespace:
    config = {
        "agent_litellm_model": "",
        "litellm_model": "openai/mimo-alpha",
        "litellm_fallback_models": [],
        "llm_model_list": [],
        "llm_temperature": 0.7,
        "gemini_api_keys": [],
        "anthropic_api_keys": [],
        "openai_api_keys": [],
        "deepseek_api_keys": [],
        "openai_base_url": None,
    }
    config.update(overrides)
    return SimpleNamespace(**config)


class LiteLLMFallbackPricingTestCase(unittest.TestCase):
    def test_register_fallback_pricing_registers_unknown_openai_model(self) -> None:
        registered = []

        def _register(payload):
            registered.append(payload)

        with patch.object(llm_adapter.litellm, "register_model", side_effect=_register, create=True):
            with patch.object(llm_adapter.litellm, "model_cost", {}, create=True):
                llm_adapter._FALLBACK_MODEL_PRICING_REGISTERED.clear()
                llm_adapter.register_fallback_model_pricing(["openai/mimo-alpha"])

        self.assertTrue(any("mimo-alpha" in payload for payload in registered))

    def test_register_fallback_pricing_skips_custom_pricing_models(self) -> None:
        registered = []

        def _register(payload):
            registered.append(payload)

        with patch.object(llm_adapter.litellm, "register_model", side_effect=_register, create=True):
            with patch.object(llm_adapter.litellm, "model_cost", {"MiniMax-M2.7": {"input_cost_per_token": 1.0}}, create=True):
                llm_adapter._FALLBACK_MODEL_PRICING_REGISTERED.clear()
                llm_adapter.register_fallback_model_pricing(["openai/MiniMax-M2.7", "openai/mimo-beta"])

        self.assertFalse(any("MiniMax-M2.7" in payload for payload in registered))
        self.assertTrue(any("mimo-beta" in payload for payload in registered))

    def test_register_fallback_pricing_registers_unknown_custom_pricing_model(self) -> None:
        registered = []

        def _register(payload):
            registered.append(payload)

        with patch.object(llm_adapter.litellm, "register_model", side_effect=_register, create=True):
            with patch.object(llm_adapter.litellm, "model_cost", {}, create=True):
                llm_adapter._FALLBACK_MODEL_PRICING_REGISTERED.clear()
                llm_adapter.register_fallback_model_pricing(["openai/MiniMax-M2.7"])

        self.assertEqual(
            registered,
            [{"MiniMax-M2.7": llm_adapter._CUSTOM_MODEL_PRICING["MiniMax-M2.7"]}],
        )

    def test_register_fallback_pricing_falls_back_to_zero_cost_when_custom_pricing_registration_fails(self) -> None:
        registered: list[dict] = []
        attempts = 0

        def _register(payload):
            nonlocal attempts
            attempts += 1
            registered.append(payload)
            if attempts == 1:
                raise RuntimeError("register failed")

        with patch.object(llm_adapter.litellm, "register_model", side_effect=_register, create=True):
            with patch.object(llm_adapter.litellm, "model_cost", {}, create=True):
                llm_adapter._FALLBACK_MODEL_PRICING_REGISTERED.clear()
                llm_adapter.register_fallback_model_pricing(["openai/MiniMax-M2.7"])

        self.assertEqual(len(registered), 2)
        self.assertEqual(
            registered[0],
            {"MiniMax-M2.7": llm_adapter._CUSTOM_MODEL_PRICING["MiniMax-M2.7"]},
        )
        self.assertEqual(
            registered[1],
            {"MiniMax-M2.7": llm_adapter._FALLBACK_MODEL_PRICING},
        )

    def test_llm_tool_adapter_registers_fallback_pricing_before_direct_completion(self) -> None:
        adapter = llm_adapter.LLMToolAdapter.__new__(llm_adapter.LLMToolAdapter)
        adapter._config = _fake_agent_config()
        adapter._router = None
        adapter._legacy_router_model_list = []

        events = []

        def _register(models):
            events.append(("register", list(models)))

        def _completion(**_kwargs):
            events.append(("completion", _kwargs["model"]))
            return _fake_litellm_response()

        with patch.object(llm_adapter, "register_fallback_model_pricing", side_effect=_register):
            with patch.object(llm_adapter.litellm, "completion", side_effect=_completion):
                result = adapter._call_litellm_model(
                    [{"role": "user", "content": "hi"}],
                    [],
                    "openai/mimo-alpha",
                )

        self.assertEqual(result.content, "agent ok")
        self.assertEqual(events[:2], [("register", ["openai/mimo-alpha"]), ("completion", "openai/mimo-alpha")])

    def test_llm_tool_adapter_registers_fallback_pricing_for_router_wire_model(self) -> None:
        adapter = llm_adapter.LLMToolAdapter.__new__(llm_adapter.LLMToolAdapter)
        adapter._config = _fake_agent_config(
            litellm_model="mimo_alias",
            llm_model_list=[
                {
                    "model_name": "mimo_alias",
                    "litellm_params": {"model": "openai/mimo-router"},
                }
            ],
        )
        adapter._legacy_router_model_list = []

        events = []

        def _register(models):
            events.append(("register", list(models)))

        def _router_completion(**_kwargs):
            events.append(("router", _kwargs["model"]))
            return _fake_litellm_response()

        adapter._router = SimpleNamespace(completion=_router_completion)

        with patch.object(llm_adapter, "register_fallback_model_pricing", side_effect=_register):
            result = adapter._call_litellm_model(
                [{"role": "user", "content": "hi"}],
                [],
                "mimo_alias",
            )

        self.assertEqual(result.content, "agent ok")
        self.assertEqual(events[:2], [("register", ["openai/mimo-router"]), ("router", "mimo_alias")])

    def test_llm_tool_adapter_registers_fallback_pricing_for_router_wire_models(self) -> None:
        adapter = llm_adapter.LLMToolAdapter.__new__(llm_adapter.LLMToolAdapter)
        adapter._config = _fake_agent_config(
            litellm_model="mimo_alias",
            llm_model_list=[
                {
                    "model_name": "mimo_alias",
                    "litellm_params": {"model": "openai/mimo-alpha"},
                },
                {
                    "model_name": "mimo_alias",
                    "litellm_params": {"model": "openai/mimo-beta"},
                },
            ],
        )
        adapter._legacy_router_model_list = []

        events = []

        def _register(models):
            events.append(("register", list(models)))

        def _router_completion(**_kwargs):
            events.append(("router", _kwargs["model"]))
            return _fake_litellm_response()

        adapter._router = SimpleNamespace(completion=_router_completion)

        with patch.object(llm_adapter, "register_fallback_model_pricing", side_effect=_register):
            result = adapter._call_litellm_model(
                [{"role": "user", "content": "hi"}],
                [],
                "mimo_alias",
            )

        self.assertEqual(result.content, "agent ok")
        self.assertEqual(
            events[:2],
            [("register", ["openai/mimo-alpha", "openai/mimo-beta"]), ("router", "mimo_alias")],
        )
