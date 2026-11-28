"""Opt-in keyless Azure OpenAI smoke tests. Sends only synthetic prompts and images."""

import io
import os
from importlib.metadata import version

import pytest
from dotenv import dotenv_values


pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(os.getenv("RUN_AZURE_OPENAI_SMOKE") != "1", reason="Requires explicit Azure smoke opt-in"),
]


@pytest.fixture(scope="module")
def azure_route(tmp_path_factory):
    source = dotenv_values(os.getenv("ENV_FILE") or ".env")
    endpoint = os.getenv("LLM_AZURE_BASE_URL") or source.get("LLM_AZURE_BASE_URL") or ""
    models = os.getenv("LLM_AZURE_MODELS") or source.get("LLM_AZURE_MODELS") or ""
    deployment = models.split(",")[0].strip().removeprefix("azure/")
    env_file = tmp_path_factory.mktemp("azure-smoke") / "smoke.env"
    env_file.touch()
    model = f"azure/{deployment}"
    with pytest.MonkeyPatch.context() as env:
        for key in list(os.environ):
            if key.startswith(("LLM_", "LITELLM_", "AZURE_OPENAI_", "AZURE_API_", "AZURE_AD_", "GENERATION_", "VISION_")):
                env.delenv(key)
        for key, value in {
            "ENV_FILE": str(env_file),
            "LLM_CHANNELS": "azure",
            "LLM_AZURE_PROTOCOL": "azure",
            "LLM_AZURE_BASE_URL": endpoint,
            "LLM_AZURE_MODELS": deployment,
            "LITELLM_MODEL": model,
            "VISION_MODEL": model,
            "LITELLM_LOG": "ERROR",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        }.items():
            env.setenv(key, value)

        import litellm

        from src.config import Config, get_config
        from src.llm.azure_openai import _get_azure_token_provider, is_azure_openai_endpoint

        assert is_azure_openai_endpoint(endpoint), "Set LLM_AZURE_BASE_URL to an Azure OpenAI resource root"
        assert deployment, "Set LLM_AZURE_MODELS to a vision-capable Azure deployment name"
        assert not getattr(litellm, "__dsa_test_stub__", False), "Run this file alone to use the real LiteLLM"
        env.setattr(litellm, "telemetry", False)
        env.setattr(litellm, "suppress_debug_info", True)
        env.setattr(Config, "_instance", None)
        _get_azure_token_provider.cache_clear()
        try:
            config = get_config()
            assert config.litellm_model == model
            assert len(config.llm_model_list) == 1
            params = config.llm_model_list[0]["litellm_params"]
            assert "api_key" not in params
            assert callable(params["azure_ad_token_provider"])
            print(f"LiteLLM {version('litellm')}; Azure Identity {version('azure-identity')}; OpenAI {version('openai')}")
            yield config, model
        finally:
            _get_azure_token_provider.cache_clear()


def test_azure_passwordless_analysis_router(azure_route):
    from litellm import Router

    from src.analyzer import GeminiAnalyzer

    config, model = azure_route
    analyzer = GeminiAnalyzer(config=config)
    assert isinstance(analyzer._router, Router)
    text, _, usage = analyzer._call_litellm(
        "Reply with OK only.",
        {"temperature": None, "max_output_tokens": 128, "timeout": 30},
        system_prompt="This is a connectivity check.",
    )
    assert text.strip().rstrip(".").upper() == "OK"
    assert usage.get("route_model", model) == model


def test_azure_passwordless_screening(azure_route):
    from src.services.screening.models import Pick
    from src.services.screening.ranker import rank_candidates_with_metadata
    from src.services.screening_service import _normalize_dsa_llm_channels

    config, model = azure_route
    result = rank_candidates_with_metadata(
        [Pick(rank=1, code="AAPL", name="Synthetic candidate", final_score=60, screen_score=60)],
        "Rank only the provided synthetic candidate.",
        "",
        model,
        max_retries=0,
        timeout_sec=30,
        max_tokens=1024,
        channels=_normalize_dsa_llm_channels(config),
    )
    assert result.ranked, result
    assert [pick.code for pick in result.picks] == ["AAPL"]


def test_azure_passwordless_vision(azure_route):
    from PIL import Image, ImageDraw, ImageFont

    from src.services.image_stock_extractor import extract_stock_codes_from_image

    image = Image.new("RGB", (250, 100), "white")
    ImageDraw.Draw(image).text((20, 20), "AAPL", font=ImageFont.load_default(size=48), fill="black")
    data = io.BytesIO()
    image.save(data, format="PNG")

    items, _ = extract_stock_codes_from_image(data.getvalue(), "image/png")
    assert any(code == "AAPL" for code, _, _ in items)
