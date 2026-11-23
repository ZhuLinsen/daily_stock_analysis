# -*- coding: utf-8 -*-
"""Regression tests for provenance-aware screening explanations."""

import json

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from src.services.screening.models import Pick, ScreeningConfig
from src.services.screening.config import Config as ScreeningRuntimeConfig
from src.services.screening.post_analysis import run_post_analyzers
from src.services.screening.ranker import _parse_ranking_response_detail, rank_candidates_with_metadata
from src.services.screening.scorer import normalized_factor_weights
from src.services.screening_service import (
    _attach_candidate_explanations,
    _enrich_candidates_with_dsa,
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

    assert [item["quality"] for item in result["why_selected"]] == ["inferred", "inferred", "observed"]
    assert result["why_selected"][1]["code"] == "llm_thesis"
    assert result["why_selected"][1]["text"] == "A different, longer thesis"
    assert result["why_selected"][2]["code"] == "selection_outcome"


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


@pytest.mark.parametrize(("analyzer", "confidence", "quality"), [
    ("scorecard", None, "observed"),
    ("scorecard", 0.8, "inferred"),
    ("dsa", None, "inferred"),
    ("external_http", None, "inferred"),
])
def test_reranked_pick_keeps_llm_reason_and_completed_analyzer_summary(
    monkeypatch, analyzer: str, confidence: float | None, quality: str,
) -> None:
    picks = [
        Pick(rank=1, code="600519", name="Original leader", final_score=85, screen_score=85),
        Pick(
            rank=2, code="000001", name="Promoted pick", final_score=84, screen_score=84,
            ranking_reason="LLM ranking reason", llm_confidence=confidence,
            factor_scores={"value": 90, "stability": 80},
        ),
    ]

    def respond(_url, *, json, timeout):
        # Mock only the remote transport; use the actual analyzer parsing,
        # score adjustments, re-ranking and summary recording below.
        if "stock_code" in json:
            body = {
                "summary": "DSA completed summary",
                "report": {"summary": {
                    "operation_advice": "买入" if json["stock_code"] == "000001" else "中性",
                }},
            }
        else:
            body = {"ranked": [
                {"code": pick["code"], "summary": "External completed summary",
                 "score_delta": 3 if pick["code"] == "000001" else 0}
                for pick in json["candidates"]
            ]}
        return Mock(json=Mock(return_value=body))

    monkeypatch.setattr("src.services.screening.post_analysis.requests.post", respond)
    analyzed, degradation = run_post_analyzers(
        picks, analyzer_names=[analyzer], run_id="explanation-rerank",
        config=ScreeningRuntimeConfig(
            dsa_api_url="https://dsa.example.invalid",
            post_analyzer_url="https://analyzer.example.invalid",
        ),
    )

    assert degradation == []
    promoted = analyzed[0]
    assert promoted.code == "000001"
    assert promoted.rank == 1
    assert promoted.final_score > 85
    assert promoted.post_analysis_status[analyzer] == "completed"
    assert promoted.post_analysis_score_deltas[analyzer] > 0

    candidate = _normalize_candidate(promoted, 1)
    result = _attach_candidate_explanations(candidate, factor_weights={"value": 1})
    assert candidate["reason"] == promoted.ranking_reason
    assert {"code": "selection_reason", "text": promoted.ranking_reason,
            "source": "llm", "quality": "inferred"} in result["why_selected"]
    assert {"code": "post_analysis_summary", "text": promoted.post_analysis_summaries[analyzer],
            "source": f"post_analyzer:{analyzer}", "quality": quality} in result["why_selected"]


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


@pytest.mark.parametrize(("analyzer", "llm_inputs", "quality"), [
    ("external_http", {}, "inferred"),
    ("dsa", {}, "inferred"),
    ("scorecard", {}, "observed"),
    ("scorecard", {"llm_confidence": 0.8}, "inferred"),
])
@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("delta", [3.0, -2.5])
def test_summaryless_score_change_survives_normalization(
    analyzer: str, llm_inputs: dict, quality: str, wrapped: bool, delta: float,
) -> None:
    payload = {
        "code": "000001",
        "ranking_reason": "独立排名理由",
        "post_analysis_status": {analyzer: "completed"},
        "post_analysis_score_deltas": {analyzer: delta},
        "post_analysis_summaries": {analyzer: "   "},
    }
    candidate = _normalize_candidate(
        {"raw": payload, **llm_inputs} if wrapped else {**payload, **llm_inputs}, 1,
    )
    for _ in range(2):
        assert candidate["post_analysis_status"] == {analyzer: "completed"}
        assert candidate["post_analysis_score_deltas"] == {analyzer: delta}
        result = _attach_candidate_explanations(candidate)
        analyzer_items = [item for item in result["why_selected"]
                          if item["source"] == f"post_analyzer:{analyzer}"]
        assert analyzer_items == [{
            "code": "post_analysis_score_delta",
            "text": f"{analyzer} 后分析已完成，评分调整 {delta:+g}（未提供摘要）",
            "source": f"post_analyzer:{analyzer}", "quality": quality, "value": delta,
        }]
        assert any(item["text"] == "独立排名理由" for item in result["why_selected"])
        candidate = _normalize_candidate(result, 1)


@pytest.mark.parametrize(("status", "delta", "summary", "expected_codes"), [
    ("completed", 3.0, None, ["post_analysis_score_delta"]),
    ("completed", 3.0, "已有摘要", ["selection_reason"]),
    ("completed", 0.0, "", []),
    ("failed", 3.0, "", []),
    ("skipped", 3.0, "", []),
    (None, 3.0, "", []),
    ("completed", None, "", []),
    ("completed", "3", "", []),
    ("completed", True, "", []),
    ("completed", float("nan"), "", []),
    ("completed", float("inf"), "", []),
])
def test_score_change_explanation_requires_completed_nonzero_delta_without_summary(
    status, delta, summary, expected_codes,
) -> None:
    payload = {
        "code": "000001",
        "post_analysis_status": {"external_http": status},
        "post_analysis_score_deltas": {"external_http": delta},
    }
    if summary is not None:
        payload["post_analysis_summaries"] = {"external_http": summary}
    result = _attach_candidate_explanations(_normalize_candidate(payload, 1))
    assert [item["code"] for item in result["why_selected"]
            if item["source"] == "post_analyzer:external_http"] == expected_codes


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


@pytest.mark.parametrize("rationale", [
    {"reason": "排序理由"},
    {"thesis": "独立论点"},
    {"reason": "排序理由", "thesis": "独立论点"},
    {"reason": "同一理由", "thesis": "同一理由"},
    {"risk": "只应显示在风险区"},
])
def test_accepted_ranker_rationale_survives_as_individual_inferred_items(rationale) -> None:
    original = Pick(rank=1, code="600519", name="测试", final_score=80, screen_score=80)
    parsed = _parse_ranking_response_detail(
        json.dumps({"ranked": [{"code": "600519", "llm_score": 90, **rationale}]}),
        [original],
    )
    assert parsed.coverage == 1.0
    assert parsed.errors == []
    candidate = _normalize_candidate(parsed.picks[0], 1)
    result = _attach_candidate_explanations(candidate)
    llm_items = [item for item in result["why_selected"] if item["source"] == "llm"]
    expected = {value for key, value in rationale.items() if key in {"reason", "thesis"}}
    assert {item["text"] for item in llm_items} == (expected or {"模型已参与排序（未提供入选理由）"})
    assert len(llm_items) == len({item["text"] for item in llm_items})
    assert all(item["quality"] == "inferred" for item in llm_items)
    assert all(item["text"] != rationale.get("risk") for item in result["why_selected"])


def test_equal_summary_text_keeps_each_analyzer_provenance() -> None:
    candidate = _normalize_candidate({
        "code": "600519",
        "post_analysis_summaries": {"scorecard": "同文案", "external_http": "同文案"},
    }, 1)
    result = _attach_candidate_explanations(candidate)
    matching = [item for item in result["why_selected"] if item["text"] == "同文案"]
    assert {(item["source"], item["quality"]) for item in matching} == {
        ("post_analyzer:scorecard", "observed"), ("post_analyzer:external_http", "inferred"),
    }
    assert len(matching) == 2
    assert result["explanation_quality"]["why_selected"] == "partial"


def test_explicit_post_summary_alias_does_not_invent_observed_local_source() -> None:
    candidate = _normalize_candidate({
        "code": "600519", "reason": "远程摘要",
        "post_analysis_summaries": {"dsa": "远程摘要"},
    }, 1)
    result = _attach_candidate_explanations(candidate)
    matching = [item for item in result["why_selected"] if item["text"] == "远程摘要"]
    assert len(matching) == 1
    assert matching[0]["source"] == "post_analyzer:dsa"
    assert matching[0]["quality"] == "inferred"


def test_raw_wrapper_uses_merged_ranking_and_scorecard_inputs() -> None:
    candidate = _normalize_candidate({
        "code": "600519", "ranking_reason": "外层模型理由", "llm_risks": ["模型风险"],
        "raw": {"post_analysis_summaries": {"scorecard": "本地评分叠加模型风险"}},
    }, 1)
    result = _attach_candidate_explanations(candidate)
    assert any(item["text"] == "外层模型理由" and item["source"] == "llm" for item in result["why_selected"])
    assert any(item["source"] == "post_analyzer:scorecard" and item["quality"] == "inferred" for item in result["why_selected"])
    fallback = _normalize_candidate({
        "code": "600519", "llm_risks": ["模型风险"],
        "raw": {"post_analysis_summaries": {"scorecard": "本地评分叠加模型风险"}},
    }, 1)
    assert fallback["reason_quality"] == "inferred"
    normalized_again = _normalize_candidate(fallback, 1)
    assert normalized_again["reason_source"] == fallback["reason_source"]
    assert normalized_again["reason_quality"] == "inferred"


@pytest.mark.parametrize("location", ["top_level", "context"])
@pytest.mark.parametrize("missing", ["stale", "undated", "source", "text"])
@pytest.mark.parametrize("kind", ["news", "events"])
def test_refresh_unusable_pre_enrichment_before_why_now(monkeypatch, location, missing, kind):
    """Exercise both cache gates, actual context builder, normalization and explanations."""
    from src.services import screening_service as service

    today = datetime.now().date().isoformat()
    current = {"title": "current evidence", "source": "provider", "published_date": today}
    unusable = dict(current)
    if missing == "stale":
        unusable["published_date"] = "2000-01-01"
    elif missing == "undated":
        unusable.pop("published_date")
    elif missing == "source":
        unusable["source"] = ""
    else:
        unusable["title"] = ""
    cached = {"news": [dict(current)], "events": [dict(current)]}
    cached[kind] = [unusable]
    context = {"enriched": True, "quote": {"price": 10}, "fundamentals": {"status": "ok"}}
    payload = {"code": "000001", "dsa_context": context}
    for category, items in cached.items():
        if location == "top_level":
            payload[f"dsa_{category}"] = items
        else:
            context[category] = {"success": True, "results": items}
    monkeypatch.setattr(service, "_get_dsa_fetcher_manager", lambda: Mock(get_stock_name=Mock(return_value="Name")))
    searches = {}
    for category in ("news", "events"):
        searches[category] = Mock(return_value={"success": True, "results": [dict(current)]})
        monkeypatch.setattr(service, f"search_dsa_stock_{category}", searches[category])
    quote = Mock(side_effect=AssertionError("existing quote must be reused"))
    fundamental = Mock(side_effect=AssertionError("existing fundamentals must be reused"))
    monkeypatch.setattr(service, "get_dsa_realtime_quote", quote)
    monkeypatch.setattr(service, "get_dsa_fundamental_context", fundamental)

    candidates, _ = _enrich_candidates_with_dsa([_normalize_candidate(payload, 1)])
    result = _attach_candidate_explanations(candidates[0])
    searches[kind].assert_called_once()
    searches["events" if kind == "news" else "news"].assert_not_called()
    quote.assert_not_called()
    fundamental.assert_not_called()
    assert {item["code"] for item in result["why_now"]} == {"news", "event"}
    assert all(item["quality"] == "observed" for item in result["why_now"])


@pytest.mark.parametrize("location", ["top_level", "context"])
@pytest.mark.parametrize("text_fields", [
    {"title": "current evidence"},
    {"snippet": "current evidence"},
    {"title": "   ", "snippet": "current evidence"},
])
def test_usable_pre_enrichment_skips_refresh(monkeypatch, location, text_fields):
    from src.services import screening_service as service

    current = {**text_fields, "source": "provider",
               "published_date": datetime.now().date().isoformat()}
    context = {"enriched": True, "warnings": ["cached warning"]}
    payload = {"code": "000001", "dsa_context": context}
    for kind in ("news", "events"):
        if location == "top_level":
            payload[f"dsa_{kind}"] = [dict(current)]
        else:
            context[kind] = {"success": True, "results": [dict(current)]}
    builder = Mock(side_effect=AssertionError("usable cached evidence must be reused"))
    monkeypatch.setattr(service, "_build_dsa_candidate_context", builder)

    candidates, metadata = _enrich_candidates_with_dsa([_normalize_candidate(payload, 1)])

    builder.assert_not_called()
    assert metadata["enriched_count"] == 1
    assert metadata["warnings"] == ["cached warning"]
    result = _attach_candidate_explanations(candidates[0])
    assert {item["code"] for item in result["why_now"]} == {"news", "event"}
    assert {item["text"] for item in result["why_now"]} == {"消息：current evidence", "事件：current evidence"}
    assert result["explanation_quality"]["why_now"] == "ok"


def test_failed_refresh_keeps_stale_evidence_out_of_why_now(monkeypatch):
    from src.services import screening_service as service

    old = {"title": "stale", "source": "provider", "published_date": "2000-01-01"}
    payload = {"code": "000001", "dsa_news": [old], "dsa_events": [old],
               "dsa_context": {"enriched": True, "quote": {"price": 10}, "fundamentals": {"status": "ok"}}}
    monkeypatch.setattr(service, "_get_dsa_fetcher_manager", lambda: Mock(get_stock_name=Mock(return_value="Name")))
    monkeypatch.setattr(service, "search_dsa_stock_news", Mock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr(service, "search_dsa_stock_events", Mock(return_value={"success": False, "results": []}))
    candidates, metadata = _enrich_candidates_with_dsa([_normalize_candidate(payload, 1)])
    result = _attach_candidate_explanations(candidates[0])
    assert [item["code"] for item in result["why_now"]] == ["awaiting_evidence"]
    assert result["explanation_quality"]["why_now"] == "unknown"
    assert any("offline" in warning for warning in metadata["warnings"])


@pytest.mark.parametrize("rationale", [{}, {"risk": "风险不应作为入选理由"}])
@pytest.mark.parametrize("score", [None, 0, 90])
def test_reasonless_accepted_llm_ranking_keeps_inferred_quality(monkeypatch, rationale, score):
    from src.services.screening import ranker

    response = {"code": "000001", **rationale}
    if score is not None:
        response["llm_score"] = score
    monkeypatch.setattr(ranker, "_call_llm", lambda *args, **kwargs: json.dumps({"ranked": [
        response, {"code": "600519", "llm_score": 0},
    ]}))
    ranked = rank_candidates_with_metadata(
        [Pick(rank=1, code="600519", name="Original leader", final_score=90, screen_score=90,
              factor_scores={"value": 90}),
         Pick(rank=2, code="000001", name="Promoted pick", final_score=80, screen_score=80,
              factor_scores={"value": 80})],
        "", "test-key", "test-model", max_retries=0, rank_weight=1,
    )
    assert ranked.ranked
    assert [pick.code for pick in ranked.picks] == ["000001", "600519"]
    assert [pick.rank for pick in ranked.picks] == [1, 2]
    for pick in ranked.picks:
        candidate = _normalize_candidate(pick, pick.rank, factor_weights={"value": 1})
        for _ in range(2):
            result = _attach_candidate_explanations(candidate, factor_weights={"value": 1})
            inferred = [item for item in result["why_selected"] if item["source"] == "llm"]
            assert inferred == [{"code": "llm_ranking", "text": "模型已参与排序（未提供入选理由）",
                                 "source": "llm", "quality": "inferred"}]
            assert any(item["code"] == "top_factors" and item["quality"] == "observed"
                       for item in result["why_selected"])
            assert result["explanation_quality"]["why_selected"] == "partial"
            assert all(item["text"] != rationale.get("risk") for item in result["why_selected"])
            candidate = _normalize_candidate({"raw": result}, pick.rank, factor_weights={"value": 1})


def test_failed_llm_ranking_does_not_invent_inferred_participation(monkeypatch):
    from src.services.screening import ranker

    monkeypatch.setattr(ranker, "_call_llm", lambda *args, **kwargs: "invalid")
    ranked = rank_candidates_with_metadata(
        [Pick(rank=1, code="000001", name="Name", final_score=80, screen_score=80,
              factor_scores={"value": 80})], "", "test-key", "test-model", max_retries=0,
    )
    assert not ranked.ranked
    result = _attach_candidate_explanations(_normalize_candidate(ranked.picks[0], 1), factor_weights={"value": 1})
    assert not any(item["source"] == "llm" for item in result["why_selected"])
    assert result["explanation_quality"]["why_selected"] == "ok"
