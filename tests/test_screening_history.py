# -*- coding: utf-8 -*-
"""Persistence and DSA hand-off coverage for the built-in screening engine."""

from __future__ import annotations

import json
import unittest
from itertools import product
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

from src.config import Config
from src.services.screening import pipeline as screening_pipeline
from src.services.screening.config import Config as ScreeningRuntimeConfig
from src.services.screening.models import HardFilterConfig, Pick, ScreenResult, ScreeningConfig, Strategy
from src.services.screening.post_analysis import run_post_analyzers
from src.services.screening.ranker import rank_candidates_with_metadata
from src.services.screening.strategy import list_strategies
from src.services.screening_service import ScreeningService, _build_dsa_candidate_context
from src.storage import DatabaseManager


class ScreeningHistoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url="sqlite:///:memory:")
        self.config = Config(screening_enabled=True)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()

    def test_pre_enriched_news_refresh_survives_screen_and_history(self) -> None:
        """Keep the refresh gates and search-response adapter real through persistence."""
        for published_date, location, kind, title in product(
            ("2000-01-01", None), ("top_level", "context"), ("news", "events"),
            ("Current evidence", "   "),
        ):
            with self.subTest(published_date=published_date, location=location, kind=kind, title=title):
                current = {
                    "title": title, "snippet": "Current evidence", "source": "provider",
                    "published_date": datetime.now().date().isoformat(),
                }
                cached = {"news": [dict(current)], "events": [dict(current)]}
                cached[kind] = [{**current, "title": "Old evidence", "published_date": published_date}]
                context = {
                    "enriched": True, "quote": {"price": 10},
                    "fundamentals": {"status": "ok"},
                }
                candidate = {"code": "000001", "name": "Name", "dsa_context": context}
                for category, items in cached.items():
                    if location == "top_level":
                        candidate[f"dsa_{category}"] = items
                    else:
                        context[category] = {"success": True, "results": items}
                provider = Mock(is_available=True)
                provider_response = SimpleNamespace(success=True, results=[SimpleNamespace(**current)])
                provider.search_stock_news.return_value = provider_response
                provider.search_stock_events.return_value = provider_response
                service = ScreeningService(self.config, db_manager=self.db)
                with (
                    patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, None)),
                    patch("src.services.screening_service._call_screening_screen", return_value={"candidates": [candidate]}),
                    patch("src.services.screening_service._get_dsa_search_service", return_value=provider),
                    patch("src.services.screening_service._get_dsa_fetcher_manager", return_value=Mock()),
                    patch("src.services.screening_service.get_dsa_realtime_quote") as quote_fetch,
                    patch("src.services.screening_service.get_dsa_fundamental_context") as fundamental_fetch,
                ):
                    response = service.screen(strategy="dual_low", market="cn", max_results=1)

                if kind == "news":
                    provider.search_stock_news.assert_called_once_with("000001", "Name", max_results=3)
                    provider.search_stock_events.assert_not_called()
                else:
                    provider.search_stock_events.assert_called_once_with("000001", "Name")
                    provider.search_stock_news.assert_not_called()
                quote_fetch.assert_not_called()
                fundamental_fetch.assert_not_called()
                selected = response["candidates"][0]
                self.assertEqual(selected["dsa_context"]["quote"], context["quote"])
                self.assertEqual(selected["dsa_context"]["fundamentals"], context["fundamentals"])
                self.assertEqual(selected["explanation_quality"]["why_now"], "ok")
                self.assertEqual(selected["why_now"], [
                    {"code": "news", "text": "消息：Current evidence", "source": "provider", "quality": "observed"},
                    {"code": "event", "text": "事件：Current evidence", "source": "provider", "quality": "observed"},
                ])
                self.assertEqual(response["dsa_enrichment"]["enriched_count"], 1)
                self.assertEqual(response["dsa_enrichment"]["warnings"], [])
                history = service.history_detail(response["run_id"])
                self.assertEqual(history["result"]["candidates"][0], selected)

    def test_thesis_only_ranking_survives_fallback_screen_and_history(self) -> None:
        for fallback in ("none", "local_factors", "scorecard"):
            with self.subTest(fallback=fallback):
                picks = [
                    Pick(rank=1, code="600519", name="Original leader", final_score=85, screen_score=85),
                    Pick(
                        rank=2, code="000001", name="Promoted pick", final_score=84, screen_score=84,
                        factor_scores={} if fallback == "none" else {"value": 90, "stability": 80},
                    ),
                ]
                thesis = "模型仅通过论点解释此次排名提升"
                with patch("src.services.screening.ranker._call_llm", return_value=json.dumps({
                    "ranked": [
                        {"code": "000001", "llm_score": 99, "thesis": thesis},
                        {"code": "600519", "llm_score": 60},
                    ],
                })):
                    ranking = rank_candidates_with_metadata(
                        picks, "test hints", "test-key", "test-model", max_retries=0,
                    )
                self.assertTrue(ranking.ranked)
                self.assertEqual(ranking.coverage, 1.0)
                self.assertEqual(ranking.errors, [])
                promoted = ranking.picks[0]
                self.assertEqual(promoted.code, "000001")
                self.assertEqual(promoted.ranking_reason, "")
                run_id = f"thesis-only-{fallback}"
                if fallback == "scorecard":
                    analyzed, degradation = run_post_analyzers(
                        ranking.picks, analyzer_names=["scorecard"], run_id=run_id,
                        config=ScreeningRuntimeConfig(),
                    )
                    self.assertEqual(degradation, [])
                else:
                    analyzed = ranking.picks
                service = ScreeningService(self.config, db_manager=self.db)
                with (
                    patch(
                        "src.services.screening_service._get_screening_status_snapshot",
                        return_value=({}, True, None),
                    ),
                    patch(
                        "src.services.screening_service._call_screening_screen",
                        return_value={
                            "run_id": run_id, "candidates": analyzed,
                            "effective_factor_weights": {"value": 1}, "llm_ranked": True,
                        },
                    ),
                    patch(
                        "src.services.screening_service._enrich_candidates_with_dsa",
                        side_effect=lambda candidates, **_kwargs: (candidates, {}),
                    ),
                ):
                    response = service.screen(strategy="dual_low", market="cn", max_results=1)

                candidate = response["candidates"][0]
                self.assertEqual(candidate["code"], promoted.code)
                self.assertEqual(candidate["rank"], 1)
                self.assertEqual(candidate["score"], promoted.final_score)
                explanations = candidate["why_selected"]
                self.assertEqual([item for item in explanations if item["source"] == "llm"], [{
                    "code": "llm_thesis", "text": thesis, "source": "llm", "quality": "inferred",
                }])
                if fallback == "scorecard":
                    self.assertIn({
                        "code": "selection_reason", "text": promoted.post_analysis_summaries["scorecard"],
                        "source": "post_analyzer:scorecard", "quality": "observed",
                    }, explanations)
                elif fallback == "local_factors":
                    self.assertTrue(any(item["code"] == "top_factors" for item in explanations))
                else:
                    self.assertTrue(any(item["code"] == "selection_outcome" for item in explanations))
                stored = self.db.get_screening_run(run_id)
                self.assertIsNotNone(stored)
                assert stored is not None
                self.assertEqual(stored["result"]["candidates"][0]["why_selected"], explanations)
                history = service.history_detail(run_id)
                self.assertEqual(history["result"]["candidates"][0]["why_selected"], explanations)

    def test_reranked_scorecard_summary_survives_screen_and_history(self) -> None:
        picks = [
            Pick(rank=1, code="600519", name="Original leader", final_score=85, screen_score=85),
            Pick(
                rank=2, code="000001", name="Promoted pick", final_score=84, screen_score=84,
                ranking_reason="LLM ranking reason", llm_confidence=0.8,
                factor_scores={"value": 90, "stability": 80},
            ),
        ]
        analyzed, degradation = run_post_analyzers(
            picks, analyzer_names=["scorecard"], run_id="scorecard-history",
            config=ScreeningRuntimeConfig(),
        )
        self.assertEqual(degradation, [])
        promoted = analyzed[0]
        self.assertEqual(promoted.code, "000001")
        self.assertGreater(promoted.final_score, 85)
        service = ScreeningService(self.config, db_manager=self.db)
        with (
            patch(
                "src.services.screening_service._get_screening_status_snapshot",
                return_value=({}, True, None),
            ),
            patch(
                "src.services.screening_service._call_screening_screen",
                return_value={
                    "run_id": "scorecard-history", "candidates": analyzed,
                    "effective_factor_weights": {"value": 1}, "llm_ranked": True,
                },
            ),
            patch(
                "src.services.screening_service._enrich_candidates_with_dsa",
                side_effect=lambda candidates, **_kwargs: (candidates, {}),
            ),
        ):
            response = service.screen(strategy="dual_low", market="cn", max_results=1)

        candidate = response["candidates"][0]
        self.assertEqual(candidate["code"], promoted.code)
        self.assertEqual(candidate["rank"], 1)
        self.assertEqual(candidate["score"], promoted.final_score)
        explanations = candidate["why_selected"]
        self.assertIn({
            "code": "selection_reason", "text": promoted.ranking_reason,
            "source": "llm", "quality": "inferred",
        }, explanations)
        self.assertIn({
            "code": "post_analysis_summary", "text": promoted.post_analysis_summaries["scorecard"],
            "source": "post_analyzer:scorecard", "quality": "inferred",
        }, explanations)
        stored = self.db.get_screening_run("scorecard-history")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["result"]["candidates"][0]["why_selected"], explanations)
        history = service.history_detail("scorecard-history")
        self.assertEqual(history["result"]["candidates"][0]["why_selected"], explanations)

    def test_summaryless_external_score_changes_survive_screen_and_history(self) -> None:
        for delta, summary_kind in product((3.0, -3.0), ("omitted", "null", "blank")):
            with self.subTest(delta=delta, summary_kind=summary_kind):
                picks = [
                    Pick(rank=1, code="600519", name="Original leader", final_score=85, screen_score=85),
                    Pick(rank=2, code="000001", name="Challenger", final_score=84, screen_score=84),
                ]
                changed_code = "000001" if delta > 0 else "600519"
                run_id = f"summaryless-external-{delta}-{summary_kind}"
                remote_result = {"ranked": [
                    {"code": pick.code, "score_delta": delta if pick.code == changed_code else 0}
                    for pick in picks
                ]}
                if summary_kind != "omitted":
                    for item in remote_result["ranked"]:
                        item["summary"] = None if summary_kind == "null" else "   "
                with patch(
                    "src.services.screening.post_analysis.requests.post",
                    return_value=Mock(json=Mock(return_value=remote_result)),
                ):
                    analyzed, degradation = run_post_analyzers(
                        picks, analyzer_names=["external_http"], run_id=run_id,
                        config=ScreeningRuntimeConfig(post_analyzer_url="https://analyzer.example.invalid"),
                    )
                self.assertEqual(degradation, [])
                self.assertEqual(analyzed[0].code, "000001")
                changed = next(pick for pick in analyzed if pick.code == changed_code)
                self.assertEqual(changed.post_analysis_summaries["external_http"], "")
                self.assertEqual(changed.post_analysis_status["external_http"], "completed")
                self.assertEqual(changed.final_score, changed.screen_score + delta)

                service = ScreeningService(self.config, db_manager=self.db)
                with (
                    patch(
                        "src.services.screening_service._get_screening_status_snapshot",
                        return_value=({}, True, None),
                    ),
                    patch(
                        "src.services.screening_service._call_screening_screen",
                        return_value={"run_id": run_id, "candidates": analyzed},
                    ),
                    patch(
                        "src.services.screening_service._enrich_candidates_with_dsa",
                        side_effect=lambda candidates, **_kwargs: (candidates, {}),
                    ),
                ):
                    response = service.screen(strategy="dual_low", market="cn", max_results=2)
                self.assertEqual(response["candidates"][0]["code"], "000001")
                candidate = next(item for item in response["candidates"] if item["code"] == changed_code)
                self.assertEqual(candidate["score"], changed.final_score)
                self.assertEqual(candidate["post_analysis_status"], {"external_http": "completed"})
                self.assertEqual(candidate["post_analysis_score_deltas"], {"external_http": delta})
                self.assertIn({
                    "code": "post_analysis_score_delta",
                    "text": f"external_http 后分析已完成，评分调整 {delta:+g}（未提供摘要）",
                    "source": "post_analyzer:external_http", "quality": "inferred", "value": delta,
                }, candidate["why_selected"])
                unchanged = next(item for item in response["candidates"] if item["code"] != changed_code)
                self.assertFalse(any(
                    item["source"] == "post_analyzer:external_http" for item in unchanged["why_selected"]
                ))
                stored = self.db.get_screening_run(run_id)
                self.assertIsNotNone(stored)
                assert stored is not None
                self.assertEqual(stored["result"]["candidates"], response["candidates"])
                self.assertEqual(service.history_detail(run_id)["result"]["candidates"], response["candidates"])

    def test_refreshed_pre_enrichment_is_returned_and_persisted(self) -> None:
        old = {"title": "stale", "source": "cached", "published_date": "2000-01-01"}
        fresh = {"title": "current", "source": "provider", "published_date": datetime.now().date().isoformat()}
        service = ScreeningService(self.config, db_manager=self.db)
        with (
            patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, None)),
            patch("src.services.screening_service._call_screening_screen", return_value={
                "run_id": "refreshed-history", "candidates": [{
                    "code": "000001", "dsa_context": {
                        "enriched": True, "quote": {"price": 10}, "fundamentals": {"status": "ok"},
                        "news": {"success": True, "results": [old]},
                        "events": {"success": True, "results": [old]},
                    },
                }],
            }),
            patch("src.services.screening_service._get_dsa_fetcher_manager",
                  return_value=Mock(get_stock_name=Mock(return_value="Name"))),
            patch("src.services.screening_service.search_dsa_stock_news",
                  return_value={"success": True, "results": [fresh]}),
            patch("src.services.screening_service.search_dsa_stock_events",
                  return_value={"success": True, "results": [fresh]}),
        ):
            response = service.screen(strategy="dual_low", market="cn", max_results=1)
        candidate = response["candidates"][0]
        self.assertEqual({item["code"] for item in candidate["why_now"]}, {"news", "event"})
        self.assertTrue(all(item["source"] == "provider" for item in candidate["why_now"]))
        self.assertEqual(candidate["explanation_quality"]["why_now"], "ok")
        self.assertEqual(service.history_detail("refreshed-history")["result"]["candidates"], [candidate])

    def test_reasonless_llm_ranking_provenance_survives_screen_and_history(self) -> None:
        from src.services.screening.ranker import rank_candidates_with_metadata

        for score in (None, 0, 90):
            with self.subTest(score=score):
                ranked_item = {"code": "000001", "risk": "风险只保留在风险区"}
                if score is not None:
                    ranked_item["llm_score"] = score
                with patch("src.services.screening.ranker._call_llm",
                           return_value=json.dumps({"ranked": [ranked_item]})):
                    ranked = rank_candidates_with_metadata(
                        [Pick(rank=1, code="000001", name="Name", final_score=80, screen_score=80,
                              factor_scores={"value": 80})], "", "test-key", "test-model", max_retries=0,
                    )
                self.assertTrue(ranked.ranked)
                run_id = f"reasonless-{score}"
                service = ScreeningService(self.config, db_manager=self.db)
                with (
                    patch("src.services.screening_service._get_screening_status_snapshot", return_value=({}, True, None)),
                    patch("src.services.screening_service._call_screening_screen", return_value={
                        "run_id": run_id, "candidates": ranked.picks, "effective_factor_weights": {"value": 1},
                    }),
                    patch("src.services.screening_service._enrich_candidates_with_dsa",
                          side_effect=lambda candidates, **_kwargs: (candidates, {})),
                ):
                    response = service.screen(strategy="dual_low", market="cn", max_results=1)
                candidate = response["candidates"][0]
                self.assertEqual(candidate["explanation_quality"]["why_selected"], "partial")
                self.assertEqual(candidate["risk_summary"], "风险只保留在风险区")
                self.assertIn({"code": "llm_ranking", "text": "模型已参与排序（未提供入选理由）",
                               "source": "llm", "quality": "inferred"}, candidate["why_selected"])
                self.assertEqual(service.history_detail(run_id)["result"]["candidates"], [candidate])

    def test_empty_pipeline_runs_preserve_actual_strategy_weights_in_history(self) -> None:
        """Exercise both real filter exits through the service and persisted history."""
        service = ScreeningService(self.config, db_manager=self.db)
        weight_cases = (
            ({"value": 6, "liquidity": 4}, {"value": 0.6, "liquidity": 0.4}),
            ({"value": 1, "momentum": 0}, {"value": 1.0, "momentum": 0.0}),
            ({}, {"value": 0.4, "liquidity": 0.2, "stability": 0.2,
                  "momentum": 0.11, "activity": 0.09}),
            ({"value": 0, "liquidity": 0},
             {"value": 0.4, "liquidity": 0.2, "momentum": 0.2, "activity": 0.2}),
        )
        for daily_filter, (configured_weights, expected_weights) in product((False, True), weight_cases):
            with self.subTest(daily_filter=daily_filter, weights=configured_weights):
                strategy = Strategy(
                    name="empty_demo", display_name="Empty demo", description="test",
                    version="2.1", category="value",
                    screening=ScreeningConfig(
                        enabled=True,
                        hard_filters=HardFilterConfig(
                            price_min=None if daily_filter else 20,
                            change_60d_min=0 if daily_filter else None,
                        ),
                        factor_weights=configured_weights, tech_weight=0.2,
                    ),
                )
                snapshot = pd.DataFrame([{
                    "code": "000001", "name": "Test", "price": 10,
                    "change_pct": 0, "amount": 200_000_000,
                }])
                runtime = ScreeningRuntimeConfig(
                    daily_enrich_enabled=False, post_analyzers=[],
                    risk_enabled=False, portfolio_diversity_enabled=False,
                )

                def run_pipeline(*args, **kwargs):
                    result = screening_pipeline.screen("empty_demo", use_llm=False, config=runtime)
                    self.assertEqual(result.effective_factor_weights.keys(), expected_weights.keys())
                    for factor, weight in expected_weights.items():
                        self.assertAlmostEqual(result.effective_factor_weights[factor], weight)
                    return result

                # The execution result must remain authoritative even if the
                # strategy catalog differs from the configuration used to run.
                with (
                    patch("src.services.screening_service._get_screening_status_snapshot",
                          return_value=({}, True, None)),
                    patch("src.services.screening_service._call_screening_screen", side_effect=run_pipeline),
                    patch("src.services.screening_service.load_screening_strategies", return_value=[{
                        "name": "empty_demo", "version": "9.0", "category": "growth",
                        "factor_weights": {"value": 1},
                    }]) as catalog_loader,
                    patch.object(screening_pipeline, "load_all_strategies", return_value={"empty_demo": strategy}),
                    patch.object(screening_pipeline, "fetch_snapshot_with_fallback", return_value=snapshot),
                    patch.object(screening_pipeline, "enrich_daily_features",
                                 side_effect=lambda df, **kwargs: df.assign(change_60d=-10)),
                    patch("src.services.screening_service._enrich_candidates_with_dsa",
                          side_effect=lambda candidates, **_kwargs: (candidates, {})),
                ):
                    response = service.screen(strategy="empty_demo", market="cn", max_results=3)
                    # History remains readable without access to the catalog.
                    catalog_loader.side_effect = AssertionError("History must not reload strategy metadata")
                    stored = service.history_detail(response["run_id"])["result"]

                self.assertEqual(response["candidates"], [])
                expected_exit = "No candidates after daily hard filter" if daily_filter else "No candidates after hard filter"
                self.assertIn(expected_exit, response["degradation"])
                for result in (response, stored):
                    self.assertEqual(result["strategy_version"], "2.1")
                    self.assertEqual(result["strategy_category"], "value")
                    self.assertEqual(result["effective_factor_weights"].keys(), expected_weights.keys())
                    for factor, weight in expected_weights.items():
                        self.assertAlmostEqual(result["effective_factor_weights"][factor], weight)
                self.assertEqual(stored["effective_factor_weights"], response["effective_factor_weights"])

    def test_missing_runtime_weights_are_not_inferred_from_strategy_catalog(self) -> None:
        service = ScreeningService(self.config, db_manager=self.db)
        raw_result = ScreenResult(strategy="empty_demo", market="cn", strategy_version="2.1")
        with (
            patch("src.services.screening_service._get_screening_status_snapshot",
                  return_value=({}, True, None)),
            patch("src.services.screening_service._call_screening_screen", return_value=raw_result),
            patch("src.services.screening_service.load_screening_strategies", return_value=[{
                "name": "empty_demo", "version": "9.0", "factor_weights": {"value": 6, "liquidity": 4},
            }]),
            patch("src.services.screening_service._enrich_candidates_with_dsa",
                  side_effect=lambda candidates, **_kwargs: (candidates, {})),
        ):
            response = service.screen(strategy="empty_demo", market="cn", max_results=3)
        stored = service.history_detail(response["run_id"])["result"]
        for result in (response, stored):
            self.assertEqual(result["candidates"], [])
            self.assertEqual(result["strategy_version"], "2.1")
            self.assertEqual(result["effective_factor_weights"], {})

    def test_completed_screen_run_is_persisted_and_loaded(self) -> None:
        raw_result = {
            "run_id": "screen-run-1",
            "strategy": "dual_low",
            "strategy_version": "1.1",
            "strategy_category": "value",
            "effective_factor_weights": {"value": 0.6, "liquidity": 0.4},
            "market": "cn",
            "snapshot_source": "sina",
            "snapshot_count": 5000,
            "after_filter_count": 12,
            "llm_ranked": True,
            "daily_enriched": False,
            "source_errors": ["efinance: request timed out"],
            "warnings": ["Snapshot source fallback: efinance: request timed out"],
            "candidates": [
                {
                    "rank": 1,
                    "code": "600519",
                    "name": "贵州茅台",
                    "final_score": 88.5,
                    "ranking_reason": "低估值与流动性通过",
                    "llm_thesis": "模型论点",
                    "post_analysis_summaries": {"scorecard": "同文案", "external_http": "同文案"},
                }
            ],
        }
        service = ScreeningService(self.config, db_manager=self.db)

        with (
            patch(
                "src.services.screening_service._get_screening_status_snapshot",
                return_value=({}, True, None),
            ),
            patch(
                "src.services.screening_service._call_screening_screen",
                return_value=raw_result,
            ),
            patch(
                "src.services.screening_service._enrich_candidates_with_dsa",
                side_effect=lambda candidates, **_kwargs: (
                    candidates,
                    {
                        "enabled": True,
                        "requested_count": 1,
                        "enriched_count": 0,
                        "warnings": [],
                    },
                ),
            ),
        ):
            response = service.screen(strategy="dual_low", market="cn", max_results=3)

        self.assertEqual(response["run_id"], "screen-run-1")
        stored = self.db.get_screening_run("screen-run-1")
        self.assertIsNotNone(stored)
        assert stored is not None
        for key in ("strategy_version", "strategy_category", "effective_factor_weights"):
            self.assertEqual(response[key], raw_result[key])
            self.assertEqual(stored["result"][key], raw_result[key])
        self.assertEqual(stored["candidate_count"], 1)
        self.assertEqual(stored["result"]["candidates"][0]["code"], "600519")
        explanations = response["candidates"][0]["why_selected"]
        self.assertIn(("llm", "inferred", "模型论点"), {
            (item["source"], item["quality"], item["text"]) for item in explanations
        })
        self.assertEqual({(item["source"], item["quality"]) for item in explanations if item["text"] == "同文案"}, {
            ("post_analyzer:scorecard", "observed"), ("post_analyzer:external_http", "inferred"),
        })
        self.assertEqual(service.history_detail("screen-run-1")["result"]["candidates"][0]["why_selected"], explanations)
        self.assertEqual(stored["result"]["candidates"][0]["why_selected"], explanations)


        history = service.history(limit=10, strategy="dual_low", market="cn")
        self.assertEqual(history["run_count"], 1)
        self.assertNotIn("result", history["runs"][0])

    def test_screen_maps_pipeline_degradation_into_warning_contract(self) -> None:
        raw_result = {
            "run_id": "screen-run-degradation",
            "strategy": "dual_low",
            "market": "cn",
            "snapshot_source": "sina",
            "snapshot_count": 5000,
            "after_filter_count": 12,
            "llm_ranked": False,
            "daily_enriched": False,
            "source_errors": ["efinance: request timed out"],
            "degradation": [
                "Snapshot source fallback: efinance: request timed out",
                "LLM ranking failed: fell back to screen_score",
            ],
            "candidates": [
                {
                    "rank": 1,
                    "code": "600519",
                    "name": "贵州茅台",
                    "final_score": 88.5,
                    "ranking_reason": "低估值与流动性通过",
                }
            ],
        }
        service = ScreeningService(self.config, db_manager=self.db)

        with (
            patch(
                "src.services.screening_service._get_screening_status_snapshot",
                return_value=({}, True, None),
            ),
            patch(
                "src.services.screening_service._call_screening_screen",
                return_value=raw_result,
            ),
            patch(
                "src.services.screening_service._enrich_candidates_with_dsa",
                side_effect=lambda candidates, **_kwargs: (
                    candidates,
                    {
                        "enabled": True,
                        "requested_count": 1,
                        "enriched_count": 0,
                        "warnings": [],
                    },
                ),
            ),
        ):
            response = service.screen(strategy="dual_low", market="cn", max_results=3)

        self.assertEqual(
            response["warnings"],
            [
                "Snapshot source fallback: efinance: request timed out",
                "LLM ranking failed: fell back to screen_score",
            ],
        )
        self.assertEqual(
            response["degradation"],
            [
                "Snapshot source fallback: efinance: request timed out",
                "LLM ranking failed: fell back to screen_score",
            ],
        )
        stored = self.db.get_screening_run("screen-run-degradation")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored["warnings"], response["warnings"])
        self.assertEqual(stored["result"]["warnings"], response["warnings"])
        self.assertEqual(stored["result"]["degradation"], response["degradation"])

        history = service.history(limit=10, strategy="dual_low", market="cn")
        self.assertEqual(history["runs"][0]["warnings"], response["warnings"])

        source_history = service.source_history(limit=10)
        self.assertEqual(source_history["fallback_runs"], 1)

    def test_save_is_idempotent_and_source_history_aggregates_failures(self) -> None:
        payload = {
            "run_id": "screen-run-2",
            "strategy": "volume_breakout",
            "market": "cn",
            "snapshot_source": "sina",
            "candidate_count": 2,
            "source_errors": ["efinance: empty response"],
            "warnings": [],
            "degradation": ["Snapshot source fallback: efinance: empty response"],
            "candidates": [],
        }
        self.assertEqual(self.db.save_screening_run(payload), 1)
        payload["candidate_count"] = 3
        self.assertEqual(self.db.save_screening_run(payload), 1)

        runs = self.db.list_screening_runs(limit=10)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["candidate_count"], 3)
        self.assertEqual(
            runs[0]["warnings"],
            ["Snapshot source fallback: efinance: empty response"],
        )

        source_history = ScreeningService(
            self.config,
            db_manager=self.db,
        ).source_history(limit=10)
        self.assertEqual(source_history["runs_analyzed"], 1)
        self.assertEqual(source_history["fallback_runs"], 1)
        self.assertEqual(source_history["sources"]["sina"]["selected_runs"], 1)
        self.assertEqual(source_history["sources"]["efinance"]["error_count"], 1)

    def test_screening_strategies_declare_dsa_analysis_skill_handoffs(self) -> None:
        strategies = {item.name: item for item in list_strategies()}

        self.assertEqual(strategies["volume_breakout"].analysis_skills, ["volume_breakout"])
        self.assertEqual(
            strategies["capital_heat"].analysis_skills,
            ["hot_theme", "emotion_cycle"],
        )

    def test_fresh_post_rank_context_includes_dsa_events(self) -> None:
        manager = Mock()
        manager.get_stock_name.return_value = "贵州茅台"
        news = {
            "success": True,
            "results": [{"title": "贵州茅台经营动态", "url": "https://example.com/news"}],
        }
        events = {
            "success": True,
            "results": [{"title": "贵州茅台发布年度报告", "url": "https://example.com/event"}],
        }
        candidate = {
            "code": "600519",
            "name": "贵州茅台",
            "dsa_context": {
                "quote": {"price": 1688.0},
                "fundamentals": {"pe_ttm": 24.5},
            },
        }

        with (
            patch("src.services.screening_service._get_dsa_fetcher_manager", return_value=manager),
            patch("src.services.screening_service.search_dsa_stock_news", return_value=news),
            patch("src.services.screening_service.search_dsa_stock_events", return_value=events) as event_search,
        ):
            enriched = _build_dsa_candidate_context(candidate)

        event_search.assert_called_once_with("600519", "贵州茅台", max_results=3)
        self.assertEqual(enriched["dsa_events"][0]["title"], "贵州茅台发布年度报告")
        self.assertEqual(enriched["dsa_context"]["events"], events)
        self.assertIn("DSA事件", enriched["dsa_analysis_summary"])


if __name__ == "__main__":
    unittest.main()
