"""Deterministic coverage for research stage budgets and timeout provenance."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.research import ResearchAgent


@pytest.mark.parametrize("remaining,expected", [(600, 120), (17, 17), (None, 120)])
def test_synthesis_has_a_bounded_budget_longer_than_thirty_seconds(remaining, expected):
    adapter = MagicMock()
    adapter.call_text.return_value = SimpleNamespace(
        provider="test", content="Synthetic report", usage={"total_tokens": 11},
    )
    agent = ResearchAgent(tool_registry=None, llm_adapter=adapter)
    result = agent._synthesise_report(
        "Synthetic question", [{"question": "Q1", "content": "Finding"}], None,
        timeout_seconds=remaining,
    )
    assert result["content"] == "Synthetic report"
    assert adapter.call_text.call_args.kwargs["timeout"] == expected


def test_exhausted_synthesis_budget_does_not_call_the_model():
    adapter = MagicMock()
    agent = ResearchAgent(tool_registry=None, llm_adapter=adapter)
    result = agent._synthesise_report("Question", [], None, timeout_seconds=0)
    assert result["timed_out"] is True
    adapter.call_text.assert_not_called()


@pytest.mark.parametrize("route", ["direct", "channel-router", "legacy-router"])
@pytest.mark.parametrize("remaining,elapsed", [(600, 7), (17, 7), (17, 17)])
def test_synthesis_budget_reaches_model_calls_and_bounds_fallback(route, remaining, elapsed):
    from src.agent.llm_adapter import LLMToolAdapter
    from src.config import Config

    primary = "openai/research-primary"
    fallback = "anthropic/research-fallback"
    config = Config(litellm_model=primary, litellm_fallback_models=[fallback],
                    llm_prompt_cache_telemetry_enabled=False)
    if route == "channel-router":
        config.llm_model_list = [{
            "model_name": primary,
            "litellm_params": {"model": primary, "api_key": "synthetic-key"},
        }]
    elif route == "legacy-router":
        config.openai_api_keys = ["synthetic-key-1", "synthetic-key-2"]

    clock = [0.0]
    calls = []
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="Synthetic report", tool_calls=[]))],
        usage={"prompt_tokens": 3, "completion_tokens": 8, "total_tokens": 11},
    )

    def complete(**kwargs):
        calls.append((kwargs["model"], kwargs["timeout"]))
        if kwargs["model"] == primary:
            clock[0] += elapsed
            raise TimeoutError("Synthetic primary request timed out")
        return response

    # Keep the real adapter/routing/recovery stack; replace only model I/O and the clock.
    with patch("src.agent.llm_adapter.Router") as router, \
         patch("src.agent.llm_adapter.litellm.completion", side_effect=complete) as direct, \
         patch("src.agent.llm_adapter.time.time", side_effect=lambda: clock[0]):
        router.return_value.completion.side_effect = complete
        adapter = LLMToolAdapter(config=config)
        agent = ResearchAgent(tool_registry=None, llm_adapter=adapter)
        result = agent._synthesise_report("Synthetic question", [], None, timeout_seconds=remaining)

    budget = min(120, remaining)
    assert calls[0] == (primary, budget)
    assert router.return_value.completion.call_count == (0 if route == "direct" else 1)
    if elapsed < budget:
        assert calls == [(primary, budget), (fallback, budget - elapsed)]
        assert direct.call_count == (2 if route == "direct" else 1)
        assert result["content"] == "Synthetic report"
        assert result["tokens"] == 11
    else:
        assert calls == [(primary, budget)]
        assert direct.call_count == (1 if route == "direct" else 0)
        assert result["timed_out"] is True
        assert "timed out before trying fallback" in result["error"]


@pytest.mark.parametrize("phase", ["decompose", "sub-question 1", "synthesis"])
def test_stage_timeout_preserves_cause_and_does_not_claim_overall_budget_exhaustion(phase):
    agent = ResearchAgent(tool_registry=None, llm_adapter=MagicMock())
    failure = {"timed_out": True, "error": "Synthetic provider request timed out", "tokens": 7}
    planning = failure if phase == "decompose" else {"questions": ["Q1"], "tokens": 3}
    finding = failure if phase == "sub-question 1" else {"question": "Q1", "content": "Finding", "tokens": 5}
    with patch.object(agent, "_decompose_query", return_value=planning), \
         patch.object(agent, "_research_sub_question", return_value=finding), \
         patch.object(agent, "_synthesise_report", return_value=failure), \
         patch("src.agent.research.time.monotonic", side_effect=[0] + [120] * 12):
        result = agent.research("Synthetic question", timeout_seconds=600)
    assert result.success is False and result.timed_out is True
    assert phase in result.error
    assert "after 120s" in result.error and "overall budget: 600s" in result.error
    assert failure["error"] in result.error
    assert "timed out after 600s" not in result.error
    assert result.total_tokens == {"decompose": 7, "sub-question 1": 10, "synthesis": 15}[phase]


def test_real_synthesis_timeout_path_keeps_its_provider_cause():
    adapter = MagicMock()
    adapter.call_text.return_value = SimpleNamespace(provider="error", content="Synthetic provider timeout")
    agent = ResearchAgent(tool_registry=None, llm_adapter=adapter)
    with patch.object(agent, "_decompose_query", return_value={"questions": ["Q1"], "tokens": 3}), \
         patch.object(agent, "_research_sub_question", return_value={"question": "Q1", "content": "Finding", "tokens": 5}), \
         patch("src.agent.research.time.monotonic", side_effect=[0] + [120] * 12):
        result = agent.research("Synthetic question", timeout_seconds=600)
    assert result.success is False and result.timed_out is True
    assert "synthesis" in result.error and "Synthetic provider timeout" in result.error
    assert result.total_tokens == 8


def test_overall_deadline_expiry_still_stops_before_planning():
    agent = ResearchAgent(tool_registry=None, llm_adapter=MagicMock())
    with patch.object(agent, "_decompose_query") as planning, \
         patch("src.agent.research.time.monotonic", side_effect=[0] + [601] * 12):
        result = agent.research("Synthetic question", timeout_seconds=600)
    planning.assert_not_called()
    assert result.timed_out is True and result.success is False
    assert "timed out after 600s" in result.error


def test_research_api_keeps_stage_error_and_known_token_usage():
    from api.v1.endpoints.agent import ResearchRequest, agent_research

    config = SimpleNamespace(is_agent_available=lambda: True, agent_deep_research_budget=30000,
                             agent_deep_research_timeout=600)
    failure = SimpleNamespace(success=False, report="", sub_questions=["Q1"], findings_count=1,
                              total_tokens=42, duration_s=120, timed_out=True,
                              error="Deep research timed out during synthesis after 120s: provider timeout")
    with patch("api.v1.endpoints.agent.get_config", return_value=config), \
         patch("src.agent.factory.get_tool_registry", return_value=MagicMock()), \
         patch("src.agent.llm_adapter.LLMToolAdapter", return_value=MagicMock()), \
         patch("api.v1.endpoints.agent._run_research_in_background", new=AsyncMock(return_value=failure)):
        result = asyncio.run(agent_research(ResearchRequest(question="Synthetic question")))
    assert result.success is False
    assert result.error == failure.error
    assert result.token_usage == 42
    assert result.content == ""
