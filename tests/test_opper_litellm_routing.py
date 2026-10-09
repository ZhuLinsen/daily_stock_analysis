# -*- coding: utf-8 -*-
"""Opper channel values as resolved by the installed LiteLLM package.

The channel tests in test_llm_channel_config.py run against the lightweight
LiteLLM stub. These cases load the real package for the duration of this
module, without any network request, and check how it routes the values an
Opper channel saves. The previous ``litellm`` modules are restored afterwards
so other test files keep the import state they expect, and the provider
set cached by ``get_litellm_model_providers`` is cleared if this module was
the first to fill it.
"""

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import (  # noqa: E402
    get_litellm_model_providers,
    normalize_llm_channel_model,
    route_discovered_llm_model,
)

OPPER_BASE_URL = "https://api.opper.ai/v3/compat"


def _litellm_modules() -> dict:
    return {
        name: module
        for name, module in sys.modules.items()
        if name == "litellm" or name.startswith("litellm.")
    }


@pytest.fixture(scope="module")
def real_litellm():
    saved = _litellm_modules()
    provider_cache_was_empty = get_litellm_model_providers.cache_info().currsize == 0
    is_stub = getattr(saved.get("litellm"), "__dsa_test_stub__", False)
    saved_cost_map_env = os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP")
    if is_stub:
        for name in saved:
            sys.modules.pop(name, None)
    # Use the bundled model cost map instead of fetching it on import.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    try:
        litellm = importlib.import_module("litellm")
    except ModuleNotFoundError:
        litellm = None
    finally:
        if saved_cost_map_env is None:
            os.environ.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
        else:
            os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = saved_cost_map_env
    try:
        if litellm is None or getattr(litellm, "__dsa_test_stub__", False):
            pytest.skip("real LiteLLM is not installed")
        yield litellm
    finally:
        if provider_cache_was_empty:
            get_litellm_model_providers.cache_clear()
        if is_stub:
            for name in list(_litellm_modules()):
                sys.modules.pop(name, None)
            sys.modules.update(saved)


def _resolve(litellm, model: str):
    resolved = litellm.get_llm_provider(model=model, api_base=OPPER_BASE_URL)
    # get_llm_provider returns (model, custom_llm_provider, dynamic_api_key, api_base).
    return resolved[0], resolved[1], resolved[-1]


@pytest.mark.parametrize(
    ("listed_id", "sent_model"),
    [
        ("anthropic/claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"),
        ("aws/claude-sonnet-4-6-eu", "aws/claude-sonnet-4-6-eu"),
        ("openai/gpt-5.5", "openai/gpt-5.5"),
        ("claude-sonnet-4-6", "claude-sonnet-4-6"),
    ],
)
def test_discovered_opper_ids_use_openai_route_with_full_id(real_litellm, listed_id, sent_model) -> None:
    saved = route_discovered_llm_model(listed_id, OPPER_BASE_URL)
    runtime = normalize_llm_channel_model(saved, "openai", OPPER_BASE_URL)

    model, provider, api_base = _resolve(real_litellm, runtime)

    assert provider == "openai"
    assert model == sent_model
    assert api_base == OPPER_BASE_URL


def test_hand_typed_vendor_id_keeps_its_litellm_provider(real_litellm) -> None:
    runtime = normalize_llm_channel_model("anthropic/claude-sonnet-4-6", "openai", OPPER_BASE_URL)

    model, provider, api_base = _resolve(real_litellm, runtime)

    assert runtime == "anthropic/claude-sonnet-4-6"
    assert provider == "anthropic"
    assert model == "claude-sonnet-4-6"
    assert api_base == OPPER_BASE_URL
