# -*- coding: utf-8 -*-
"""Regression tests for provenance-aware screening explanations."""

from datetime import datetime, timedelta, timezone

import pytest

from src.services.screening.models import ScreeningConfig
from src.services.screening.scorer import normalized_factor_weights
from src.services.screening_service import (
    _attach_candidate_explanations,
    _normalize_candidate,
    _strategy_factor_weights,
)


def test_strategy_explanations_use_scorer_defaults_when_weights_are_omitted() -> None:
    effective = normalized_factor_weights(ScreeningConfig(tech_weight=0.2))
    weights = _strategy_factor_weights("custom", effective_weights=effective)

    assert weights == pytest.approx({
        "value": 0.4,
        "liquidity": 0.2,
        "stability": 0.2,
        "momentum": 0.11,
        "activity": 0.09,
    })


def test_strategy_explanations_use_scorer_fallback_when_all_weights_are_zero() -> None:
    effective = normalized_factor_weights(
        ScreeningConfig(factor_weights={"value": 0, "stability": 0})
    )
    weights = _strategy_factor_weights("custom", effective_weights=effective)

    assert weights == {
        "value": 0.4,
        "liquidity": 0.2,
        "momentum": 0.2,
        "activity": 0.2,
    }


def test_real_zero_quote_change_is_preserved_as_observed_evidence() -> None:
    candidate = {
        "rank": 1,
        "reason": "通过价值和流动性筛选",
        "factor_scores": {"value": 90.0},
        "dsa_context": {"quote": {"change_pct": 0.0}},
        "dsa_news": [],
        "dsa_events": [],
        "llm_catalysts": [],
    }

    result = _attach_candidate_explanations(
        candidate,
        factor_weights={"quality": 0.4, "value": 0.6},
    )

    quote_item = next(item for item in result["why_now"] if item["code"] == "quote_change_pct")
    assert quote_item["value"] == 0.0
    assert quote_item["quality"] == "observed"
    assert result["explanation_quality"]["why_now"] == "ok"


def test_stale_or_partial_quote_is_not_presented_as_current_observed_evidence() -> None:
    for quality_fields in ({"is_stale": True}, {"data_quality": "partial"}):
        candidate = {
            "rank": 1,
            "reason": "local reason",
            "factor_scores": {},
            "dsa_context": {"quote": {"change_pct": 3.0, "amount": 100.0, **quality_fields}},
            "dsa_news": [],
            "dsa_events": [],
            "llm_catalysts": [],
        }

        result = _attach_candidate_explanations(candidate)

        assert [item["code"] for item in result["why_now"]] == ["awaiting_evidence"]
        assert result["explanation_quality"]["why_now"] == "unknown"


def test_top_level_zero_without_quote_provenance_is_not_presented_as_current_evidence() -> None:
    candidate = {
        "rank": 2,
        "reason": "本地因子入选",
        "change_pct": 0.0,
        "amount": 0.0,
        "factor_scores": {},
        "dsa_context": {},
        "dsa_news": [],
        "dsa_events": [],
        "llm_catalysts": [],
    }

    result = _attach_candidate_explanations(candidate)

    assert [item["code"] for item in result["why_now"]] == ["awaiting_evidence"]
    assert result["explanation_quality"]["why_now"] == "unknown"


def test_local_selection_explanation_survives_without_llm_output() -> None:
    candidate = {
        "rank": 3,
        "reason": "",
        "factor_scores": {"quality": 88.0, "value": 91.0},
        "dsa_context": {},
        "dsa_news": [],
        "dsa_events": [],
    }

    result = _attach_candidate_explanations(
        candidate,
        factor_weights={"quality": 0.4, "value": 0.6},
    )

    assert result["why_selected"][0]["code"] == "top_factors"
    assert "value 91.0" in result["why_selected"][0]["text"]
    assert result["explanation_quality"]["why_selected"] == "ok"


def test_top_factors_only_use_weighted_strategy_contributors() -> None:
    candidate = {
        "rank": 3,
        "reason": "",
        "factor_scores": {"topic_alignment": 99.0, "value": 70.0, "momentum": 90.0},
        "dsa_context": {},
        "dsa_news": [],
        "dsa_events": [],
    }

    result = _attach_candidate_explanations(
        candidate,
        factor_weights={"value": 0.8, "momentum": 0.2},
    )

    factor_text = result["why_selected"][0]["text"]
    assert "value 70.0" in factor_text
    assert "momentum 90.0" in factor_text
    assert factor_text.index("value 70.0") < factor_text.index("momentum 90.0")
    assert "topic_alignment" not in factor_text


def test_fallback_reason_uses_the_same_strategy_weights_as_top_factors() -> None:
    candidate = _normalize_candidate(
        {
            "code": "600519",
            "factor_scores": {"topic_alignment": 99.0, "value": 70.0, "momentum": 90.0},
        },
        1,
        factor_weights={"value": 0.8, "momentum": 0.2, "topic_alignment": 0.0},
    )

    result = _attach_candidate_explanations(
        candidate,
        factor_weights={"value": 0.8, "momentum": 0.2, "topic_alignment": 0.0},
    )

    assert "value 70.0" in candidate["reason"]
    assert "momentum 90.0" in candidate["reason"]
    assert "topic_alignment" not in candidate["reason"]
    assert "topic_alignment" not in " ".join(item["text"] for item in result["why_selected"])


def test_llm_reason_does_not_replace_the_observed_local_selection_fallback() -> None:
    candidate = {
        "rank": 4,
        "reason": "模型认为催化充足",
        "llm_thesis": "模型认为催化充足",
        "factor_scores": {},
        "dsa_context": {},
        "dsa_news": [],
        "dsa_events": [],
    }

    result = _attach_candidate_explanations(candidate)

    assert [item["quality"] for item in result["why_selected"]] == ["inferred", "observed"]
    assert result["why_selected"][1]["code"] == "selection_outcome"
    assert result["why_selected"][1]["text"] == "已进入当前选股候选结果"
    assert result["explanation_quality"]["why_selected"] == "partial"


def test_distinct_llm_ranking_reason_stays_inferred_and_keeps_rank_fallback() -> None:
    candidate = {
        "rank": 5,
        "reason": "LLM ranking reason",
        "ranking_reason": "LLM ranking reason",
        "llm_thesis": "A different, longer thesis",
        "factor_scores": {},
        "dsa_context": {},
        "dsa_news": [],
        "dsa_events": [],
    }

    result = _attach_candidate_explanations(candidate)

    assert [item["quality"] for item in result["why_selected"]] == ["inferred", "observed"]
    assert result["why_selected"][1]["code"] == "selection_outcome"


def test_news_and_events_without_provenance_are_not_observed() -> None:
    candidate = {
        "rank": 6,
        "reason": "local reason",
        "factor_scores": {},
        "dsa_context": {},
        "dsa_news": [{"title": "Unattributed headline", "url": "https://example.test/news"}],
        "dsa_events": [{"title": "Unattributed event"}],
    }

    result = _attach_candidate_explanations(candidate)

    assert [item["code"] for item in result["why_now"]] == ["awaiting_evidence"]
    assert result["explanation_quality"]["why_now"] == "unknown"


def test_llm_risk_summary_stays_inferred_and_keeps_rank_fallback() -> None:
    candidate = {
        "rank": 7,
        "reason": "LLM generated risk summary",
        "risk_summary": "LLM generated risk summary",
        "factor_scores": {},
        "dsa_context": {},
        "dsa_news": [],
        "dsa_events": [],
    }

    result = _attach_candidate_explanations(candidate)

    assert [item["quality"] for item in result["why_selected"]] == ["inferred", "observed"]
    assert result["why_selected"][1]["code"] == "selection_outcome"


def test_risk_summary_is_not_promoted_to_selection_reason_when_reason_is_missing() -> None:
    candidate = _normalize_candidate({
        "code": "600519",
        "risk_summary": "估值过高",
        "factor_scores": {},
    }, 1)

    result = _attach_candidate_explanations(candidate)

    assert candidate["risk_summary"] == "估值过高"
    assert candidate["reason"] == ""
    assert [item["code"] for item in result["why_selected"]] == ["selection_outcome"]
    assert all("估值过高" not in item["text"] for item in result["why_selected"])


def test_post_analyzer_summary_keeps_inferred_provenance() -> None:
    candidate = _normalize_candidate({
        "code": "600519",
        "post_analysis_summaries": {"dsa": "模型生成的后分析摘要"},
        "factor_scores": {},
    }, 1)

    result = _attach_candidate_explanations(candidate)

    reason = result["why_selected"][0]
    assert reason["code"] == "selection_reason"
    assert reason["source"] == "post_analyzer:dsa"
    assert reason["quality"] == "inferred"
    assert result["why_selected"][1]["code"] == "selection_outcome"


def test_local_scorecard_summary_keeps_observed_provenance() -> None:
    candidate = _normalize_candidate({
        "code": "600519",
        "post_analysis_summaries": {"scorecard": "本地因子计分摘要"},
        "factor_scores": {},
    }, 1)

    result = _attach_candidate_explanations(candidate)

    reason = result["why_selected"][0]
    assert reason["source"] == "post_analyzer:scorecard"
    assert reason["quality"] == "observed"
    assert result["explanation_quality"]["why_selected"] == "ok"


def test_scorecard_using_llm_fields_keeps_inferred_provenance() -> None:
    candidate = _normalize_candidate({
        "code": "600519",
        "post_analysis_summaries": {"scorecard": "本地评分叠加模型风险"},
        "llm_confidence": 0.8,
        "llm_risks": ["模型风险"],
        "factor_scores": {},
    }, 1)

    result = _attach_candidate_explanations(candidate)

    reason = result["why_selected"][0]
    assert reason["source"] == "post_analyzer:scorecard"
    assert reason["quality"] == "inferred"
    assert result["explanation_quality"]["why_selected"] == "partial"


def test_explicit_reason_keeps_distinct_post_analysis_summaries() -> None:
    candidate = _normalize_candidate({
        "code": "600519",
        "ranking_reason": "量价和质量因子排名靠前",
        "post_analysis_summaries": {
            "scorecard": "本地因子计分摘要",
            "dsa": "模型补充的新闻风险摘要",
        },
        "factor_scores": {},
    }, 1)

    result = _attach_candidate_explanations(candidate)

    assert [item["code"] for item in result["why_selected"]] == [
        "selection_reason",
        "post_analysis_summary",
        "post_analysis_summary",
    ]
    assert result["why_selected"][0]["text"] == "量价和质量因子排名靠前"
    assert result["why_selected"][1] == {
        "code": "post_analysis_summary",
        "text": "本地因子计分摘要",
        "source": "post_analyzer:scorecard",
        "quality": "observed",
    }
    assert result["why_selected"][2] == {
        "code": "post_analysis_summary",
        "text": "模型补充的新闻风险摘要",
        "source": "post_analyzer:dsa",
        "quality": "inferred",
    }
    assert result["explanation_quality"]["why_selected"] == "partial"


def test_post_analysis_summary_matching_explicit_reason_is_not_duplicated() -> None:
    candidate = _normalize_candidate({
        "code": "600519",
        "reason": "同一条后分析摘要",
        "post_analysis_summaries": {
            "scorecard": "同一条后分析摘要",
        },
        "factor_scores": {},
    }, 1)

    result = _attach_candidate_explanations(candidate)

    assert [item["text"] for item in result["why_selected"]] == [
        "同一条后分析摘要",
    ]


def test_risk_level_is_not_promoted_to_selection_reason() -> None:
    candidate = _normalize_candidate({
        "code": "600519",
        "risk_level": "high",
        "industry": "白酒",
        "factor_scores": {},
    }, 1)

    result = _attach_candidate_explanations(candidate)

    assert candidate["reason"] == ""
    assert [item["code"] for item in result["why_selected"]] == ["selection_outcome"]
    assert "风险" not in result["why_selected"][0]["text"]


def test_stale_or_undated_events_are_not_why_now_evidence() -> None:
    stale_date = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    candidate = {
        "rank": 8,
        "reason": "local reason",
        "factor_scores": {},
        "dsa_context": {},
        "dsa_news": [],
        "dsa_events": [
            {"title": "Stale event", "source": "exchange", "published_date": stale_date},
            {"title": "Undated event", "source": "exchange"},
        ],
    }

    result = _attach_candidate_explanations(candidate)

    assert [item["code"] for item in result["why_now"]] == ["awaiting_evidence"]


def test_stale_or_undated_news_is_not_why_now_evidence() -> None:
    stale_date = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    candidate = {
        "rank": 9,
        "reason": "local reason",
        "factor_scores": {},
        "dsa_context": {},
        "dsa_news": [
            {"title": "Stale news", "source": "wire", "published_date": stale_date},
            {"title": "Undated news", "source": "wire"},
        ],
        "dsa_events": [],
    }

    result = _attach_candidate_explanations(candidate)

    assert [item["code"] for item in result["why_now"]] == ["awaiting_evidence"]


def test_recent_news_with_source_is_observed_why_now_evidence() -> None:
    candidate = {
        "rank": 10,
        "reason": "local reason",
        "factor_scores": {},
        "dsa_context": {},
        "dsa_news": [{
            "title": "Recent news",
            "source": "wire",
            "published_date": "2 days ago",
        }],
        "dsa_events": [],
    }

    result = _attach_candidate_explanations(candidate)

    assert result["why_now"][0]["code"] == "news"
    assert result["why_now"][0]["quality"] == "observed"


def test_recent_event_with_source_is_observed_why_now_evidence() -> None:
    candidate = {
        "rank": 9,
        "reason": "local reason",
        "factor_scores": {},
        "dsa_context": {},
        "dsa_news": [],
        "dsa_events": [{
            "title": "Recent event",
            "source": "exchange",
            "published_date": datetime.now(timezone.utc).isoformat(),
        }],
    }

    result = _attach_candidate_explanations(candidate)

    assert result["why_now"][0]["code"] == "event"
    assert result["why_now"][0]["quality"] == "observed"


def test_recent_relative_provider_date_is_observed_why_now_evidence() -> None:
    candidate = {
        "rank": 10,
        "reason": "local reason",
        "factor_scores": {},
        "dsa_context": {},
        "dsa_news": [],
        "dsa_events": [{
            "title": "Recent provider event",
            "source": "serpapi",
            "published_date": "2 days ago",
        }],
    }

    result = _attach_candidate_explanations(candidate)

    assert result["why_now"][0]["code"] == "event"
    assert result["why_now"][0]["quality"] == "observed"
