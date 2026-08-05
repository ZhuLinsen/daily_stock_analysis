# -*- coding: utf-8 -*-
"""Regression tests for screening LiteLLM ranking request compatibility."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

from src.llm.generation_params import clear_litellm_generation_param_recovery_cache
from src.services.screening.models import Pick
from src.services.screening.ranker import _call_llm, rank_candidates_with_metadata


def _response(content: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _ranking_response(*codes: str) -> str:
    ranked = [
        {
            "code": code,
            "llm_score": 90 - index,
            "confidence": 0.8,
            "reason": f"reason-{code}",
            "risk": "risk",
        }
        for index, code in enumerate(codes)
    ]
    import json

    return json.dumps({"ranked": ranked}, ensure_ascii=False)


def test_screening_ranker_direct_call_omits_temperature_for_gpt5() -> None:
    clear_litellm_generation_param_recovery_cache()
    completion_calls: list[dict[str, object]] = []

    def completion(**kwargs):
        completion_calls.append(dict(kwargs))
        return _response()

    fake_litellm = SimpleNamespace(completion=completion)

    with patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False):
        result = _call_llm(
            "rank candidates",
            api_key="test-key",
            model="openai/gpt-5-mini",
            base_url="",
            temperature=0.2,
            json_mode=False,
        )

    assert result == "ok"
    assert "temperature" not in completion_calls[0]


def test_screening_ranker_direct_call_uses_responses_wire_model_for_matching_channel() -> None:
    completion_calls: list[dict[str, object]] = []

    def completion(**kwargs):
        completion_calls.append(dict(kwargs))
        return _response()

    fake_litellm = SimpleNamespace(completion=completion)

    with patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False):
        result = _call_llm(
            "rank candidates",
            api_key="test-key",
            model="openai/gpt-5.6-sol",
            base_url="",
            json_mode=False,
            channels=[
                {
                    "name": "draft",
                    "protocol": "openai",
                    "api_surface": "responses",
                    "api_keys": ["sk-draft"],
                    "base_url": "https://api.example.com/v1",
                    "models": ["openai/gpt-5.6-sol"],
                }
            ],
        )

    assert result == "ok"
    assert len(completion_calls) == 1
    assert completion_calls[0]["model"] == "openai/responses/gpt-5.6-sol"
    assert completion_calls[0]["api_key"] == "sk-draft"
    assert completion_calls[0]["api_base"] == "https://api.example.com/v1"


def test_screening_ranker_does_not_retry_public_alias_after_responses_attempt_failure() -> None:
    completion_calls: list[dict[str, object]] = []

    def completion(**kwargs):
        completion_calls.append(dict(kwargs))
        raise RuntimeError("responses endpoint rejected request")

    fake_litellm = SimpleNamespace(completion=completion)

    with patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False):
        try:
            _call_llm(
                "rank candidates",
                api_key="test-key",
                model="openai/gpt-5.6-sol",
                base_url="https://fallback.example.com/v1",
                json_mode=False,
                channels=[
                    {
                        "name": "draft",
                        "protocol": "openai",
                        "api_surface": "responses",
                        "api_keys": ["sk-draft"],
                        "base_url": "https://api.example.com/v1",
                        "models": ["openai/gpt-5.6-sol"],
                    }
                ],
            )
        except RuntimeError as exc:
            assert "responses endpoint rejected request" in str(exc)
        else:
            raise AssertionError("expected _call_llm to raise")

    assert len(completion_calls) == 1
    assert completion_calls[0]["model"] == "openai/responses/gpt-5.6-sol"
    assert completion_calls[0]["api_base"] == "https://api.example.com/v1"


def test_screening_ranker_rejects_invalid_responses_wire_route_before_call() -> None:
    completion_calls: list[dict[str, object]] = []

    def completion(**kwargs):
        completion_calls.append(dict(kwargs))
        return _response()

    fake_litellm = SimpleNamespace(completion=completion)

    with patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False):
        try:
            _call_llm(
                "rank candidates",
                api_key="test-key",
                model="anthropic/claude-sonnet-4-6",
                base_url="",
                json_mode=False,
                channels=[
                    {
                        "name": "draft",
                        "protocol": "openai",
                        "api_surface": "responses",
                        "api_keys": ["sk-draft"],
                        "models": ["anthropic/claude-sonnet-4-6"],
                    }
                ],
            )
        except ValueError as exc:
            assert "normalized openai" in str(exc)
        else:
            raise AssertionError("expected invalid Responses route to raise")

    assert completion_calls == []


def test_screening_ranker_direct_call_retries_temperature_with_param_recovery() -> None:
    clear_litellm_generation_param_recovery_cache()
    completion_calls: list[dict[str, object]] = []

    def completion(**kwargs):
        completion_calls.append(dict(kwargs))
        if len(completion_calls) == 1:
            raise RuntimeError("Unsupported parameter: temperature is not supported")
        return _response()

    fake_litellm = SimpleNamespace(completion=completion)

    with patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False):
        result = _call_llm(
            "rank candidates",
            api_key="test-key",
            model="openai/custom-temp-locked",
            base_url="",
            temperature=0.7,
            json_mode=False,
        )

    assert result == "ok"
    assert completion_calls[0]["temperature"] == 0.7
    assert "temperature" not in completion_calls[1]


def test_screening_ranker_does_not_read_reasoning_content_when_content_is_empty() -> None:
    completion_calls: list[dict[str, object]] = []

    def completion(**kwargs):
        completion_calls.append(dict(kwargs))
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        reasoning_content='{"ranked": []}',
                    )
                )
            ]
        )

    fake_litellm = SimpleNamespace(completion=completion)
    with patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False):
        result = _call_llm(
            "rank candidates",
            api_key="test-key",
            model="deepseek/deepseek-reasoner",
            base_url="",
            json_mode=True,
        )

    # Do not treat internal reasoning_content as final model output; allow higher
    # level fallback logic to handle it instead.
    assert result == ''
    assert len(completion_calls) == 1


def test_screening_ranker_reads_choice_content_blocks_without_changing_json() -> None:
    expected = '{"ranked":[{"code":"600519"}]}'

    def completion(**_kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=""),
                    content_blocks=[
                        {"type": "output_text", "text": '{"ranked":[{"code":"600'},
                        {"type": "output_text", "text": '519"}]}'},
                    ],
                )
            ]
        )

    with patch.dict(sys.modules, {"litellm": SimpleNamespace(completion=completion)}, clear=False):
        result = _call_llm(
            "rank candidates",
            api_key="test-key",
            model="openai/gpt-5-mini",
            base_url="",
            json_mode=True,
        )

    assert result == expected


def test_screening_ranker_ignores_thinking_blocks_in_message_content() -> None:
    final = _ranking_response("600519")
    draft = _ranking_response("000001")

    def completion(**_kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=[
                            {"type": "thinking", "text": draft},
                            {"type": "output_text", "text": final},
                        ],
                    )
                )
            ]
        )

    with patch.dict(sys.modules, {"litellm": SimpleNamespace(completion=completion)}, clear=False):
        result = _call_llm(
            "rank candidates",
            api_key="test-key",
            model="openai/gpt-5-mini",
            base_url="",
            json_mode=True,
        )

    assert result == final


def test_screening_ranker_router_call_applies_kimi_temperature_and_recovery(tmp_path) -> None:
    clear_litellm_generation_param_recovery_cache()
    router_calls: list[dict[str, object]] = []

    class FakeRouter:
        def __init__(self, *, model_list):
            self.model_list = model_list

        def completion(self, **kwargs):
            router_calls.append(dict(kwargs))
            if len(router_calls) == 1:
                raise RuntimeError("Unsupported parameter: temperature is not supported")
            return _response()

    fake_litellm = SimpleNamespace(Router=FakeRouter, completion=lambda **_: _response())
    config_path = tmp_path / "litellm.yaml"
    config_path.write_text(
        """
model_list:
  - model_name: moonshot/kimi-k2.6
    litellm_params:
      model: moonshot/kimi-k2.6
        """.strip(),
        encoding="utf-8",
    )

    with patch.dict(sys.modules, {"litellm": fake_litellm}, clear=False):
        result = _call_llm(
            "rank candidates",
            api_key="test-key",
            model="moonshot/kimi-k2.6",
            base_url="",
            temperature=0.2,
            json_mode=False,
            config_path=str(config_path),
        )

    assert result == "ok"
    assert router_calls[0]["temperature"] == 1.0
    assert "temperature" not in router_calls[1]


def test_rank_candidates_with_metadata_does_not_mutate_candidates_when_coverage_is_low() -> None:
    candidates = [
        Pick(rank=1, code="600519", name="贵州茅台", final_score=90.0, screen_score=90.0),
        Pick(rank=2, code="000001", name="平安银行", final_score=80.0, screen_score=80.0),
    ]
    response = """
    {
      "ranked": [
        {
          "code": "600519",
          "reason": "partial coverage",
          "risk": "watch valuation",
          "llm_score": 95,
          "sector": "Baijiu"
        }
      ]
    }
    """.strip()

    with patch("src.services.screening.ranker._call_llm", return_value=response):
        result = rank_candidates_with_metadata(
            candidates,
            "test hints",
            "test-key",
            "openai/gpt-5-mini",
            min_coverage=0.75,
            max_retries=0,
        )

    assert result.ranked is False
    assert result.picks is candidates
    assert candidates[0].llm_score is None
    assert candidates[0].risk_summary == ""
    assert candidates[0].llm_sector == ""


def test_rank_candidates_with_metadata_tries_fallback_after_invalid_json() -> None:
    candidates = [
        Pick(rank=1, code="600519", name="贵州茅台", final_score=90.0, screen_score=90.0),
        Pick(rank=2, code="000001", name="平安银行", final_score=80.0, screen_score=80.0),
    ]
    called_models: list[str] = []

    def call_llm(_prompt, _api_key, model, _base_url, **kwargs):
        called_models.append(model)
        assert kwargs["fallback_models"] == []
        if model == "deepseek/deepseek-chat":
            return "I cannot provide structured output."
        return _ranking_response("600519", "000001")

    with patch("src.services.screening.ranker._call_llm", side_effect=call_llm):
        result = rank_candidates_with_metadata(
            candidates,
            "test hints",
            "test-key",
            "deepseek/deepseek-chat",
            fallback_models=["gemini/gemini-3-flash-preview"],
            min_coverage=1.0,
            max_retries=0,
        )

    assert result.ranked is True
    assert result.model_used == "gemini/gemini-3-flash-preview"
    assert result.attempted_models == [
        "deepseek/deepseek-chat",
        "gemini/gemini-3-flash-preview",
    ]
    assert called_models == result.attempted_models
    assert result.errors == []


def test_rank_candidates_with_metadata_reports_all_invalid_models() -> None:
    candidates = [Pick(rank=1, code="600519", name="贵州茅台", final_score=90.0, screen_score=90.0)]

    with patch("src.services.screening.ranker._call_llm", return_value="not-json"):
        result = rank_candidates_with_metadata(
            candidates,
            "test hints",
            "test-key",
            "deepseek/deepseek-chat",
            fallback_models=["openai/gpt-4o"],
            max_retries=0,
        )

    assert result.ranked is False
    assert result.picks is candidates
    assert result.failure_reason == "invalid_response"
    assert result.attempted_models == ["deepseek/deepseek-chat", "openai/gpt-4o"]
    assert len(result.errors) == 2
