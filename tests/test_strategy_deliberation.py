# -*- coding: utf-8 -*-
"""Focused tests for Strategy Deliberation mediators."""

import json
import unittest

from src.agent.protocols import StrategyConflict, StrategyOpinion
from src.agent.skills.deliberation import (
    DeliberationMediator,
    LLMDeliberationMediator,
    MultiRoundDeliberationMediator,
    StrategySelfReviewMediator,
)
from src.agent.skills.synthesis import (
    ConflictDetector,
    StrategySynthesizer,
)


class TestStrategyDeliberationV0(unittest.TestCase):
    def test_omits_deliberation_without_conflicts(self):
        opinions = [
            StrategyOpinion(skill_id="bull_trend", signal="buy", confidence=0.8),
            StrategyOpinion(skill_id="hot_theme", signal="buy", confidence=0.7),
        ]

        synthesis = StrategySynthesizer().synthesize(
            opinions,
            weighted_score=4.0,
            final_signal="buy",
            weighted_confidence=0.75,
            conflicts=[],
        )

        self.assertEqual(synthesis["final_signal"], "buy")
        self.assertAlmostEqual(synthesis["confidence"], 0.75)
        self.assertNotIn("deliberation", synthesis)
        self.assertNotIn("revision_projection", synthesis)

    def test_softens_high_conflict_without_reversing_signal(self):
        opinions = [
            StrategyOpinion(skill_id="bull_trend", signal="strong_buy", confidence=0.82),
            StrategyOpinion(skill_id="hot_theme", signal="strong_sell", confidence=0.78),
        ]
        conflicts = ConflictDetector().detect(opinions, final_signal="hold")

        synthesis = StrategySynthesizer().synthesize(
            opinions,
            weighted_score=3.0,
            final_signal="hold",
            weighted_confidence=0.8,
            conflicts=conflicts,
        )

        self.assertEqual(synthesis["final_signal"], "hold")
        deliberation = synthesis["deliberation"]
        self.assertEqual(deliberation["status"], "completed")
        self.assertEqual(deliberation["mode"], "mediator_v0")
        self.assertEqual(deliberation["summary"]["resolution_status"], "partially_resolved")
        self.assertEqual(deliberation["summary"]["confidence_adjustment"], -0.06)
        self.assertAlmostEqual(synthesis["confidence"], 0.62)

        responses = deliberation["responses"]
        self.assertNotIn("reversed", {response["revision"] for response in responses})
        bull_softened = [
            response for response in responses
            if response["skill_id"] == "bull_trend" and response["revision"] == "softened"
        ]
        bear_softened = [
            response for response in responses
            if response["skill_id"] == "hot_theme" and response["revision"] == "softened"
        ]
        self.assertTrue(bull_softened)
        self.assertEqual(bull_softened[0]["original_signal"], "strong_buy")
        self.assertEqual(bull_softened[0]["revised_signal"], "buy")
        self.assertTrue(bear_softened)
        self.assertEqual(bear_softened[0]["original_signal"], "strong_sell")
        self.assertEqual(bear_softened[0]["revised_signal"], "sell")
        projection = synthesis["revision_projection"]
        self.assertEqual(projection["status"], "computed")
        self.assertEqual(projection["mode"], "preview_only")
        self.assertEqual(projection["source_mode"], "mediator_v0")
        self.assertEqual(projection["projected_signal"], "hold")
        self.assertFalse(projection["final_signal_overridden"])

    def test_preserves_high_confidence_minority_view(self):
        opinions = [
            StrategyOpinion(skill_id="bull_trend", signal="buy", confidence=0.82),
            StrategyOpinion(skill_id="fund_flow", signal="sell", confidence=0.8),
        ]
        conflicts = [
            StrategyConflict(
                conflict_type="high_confidence_dissent",
                severity="medium",
                participants=["fund_flow"],
                description_key="strategy_conflict.high_confidence_dissent",
                metadata={"final_signal": "buy"},
            )
        ]

        synthesis = StrategySynthesizer().synthesize(
            opinions,
            weighted_score=4.0,
            final_signal="buy",
            weighted_confidence=0.81,
            conflicts=conflicts,
        )

        self.assertEqual(synthesis["final_signal"], "buy")
        summary = synthesis["deliberation"]["summary"]
        self.assertTrue(summary["minority_view_preserved"])
        self.assertEqual(summary["resolution_status"], "unresolved")
        self.assertEqual(summary["confidence_adjustment"], -0.05)
        responses = synthesis["deliberation"]["responses"]
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["skill_id"], "fund_flow")
        self.assertEqual(responses[0]["revision"], "unchanged")
        self.assertEqual(responses[0]["revised_signal"], "sell")

    def test_revision_projection_does_not_override_final_signal(self):
        opinions = [
            StrategyOpinion(skill_id="bull_trend", signal="strong_buy", confidence=0.82),
            StrategyOpinion(skill_id="hot_theme", signal="strong_sell", confidence=0.3),
        ]
        conflicts = ConflictDetector().detect(opinions, final_signal="strong_buy")

        synthesis = StrategySynthesizer().synthesize(
            opinions,
            weighted_score=4.5,
            final_signal="strong_buy",
            weighted_confidence=0.68,
            conflicts=conflicts,
        )

        self.assertEqual(synthesis["final_signal"], "strong_buy")
        self.assertEqual(synthesis["weighted_score"], 4.5)
        projection = synthesis["revision_projection"]
        self.assertEqual(projection["projected_signal"], "hold")
        self.assertEqual(projection["changed_skill_count"], 2)
        self.assertEqual(projection["changed_skills"], ["bull_trend", "hot_theme"])
        self.assertFalse(projection["final_signal_overridden"])

    def test_revision_projection_ignores_unguarded_aggressive_response(self):
        class UnsafeProjectionMediator:
            def deliberate(self, opinions, conflicts, *, final_signal):
                baseline = DeliberationMediator().deliberate(
                    opinions,
                    conflicts,
                    final_signal=final_signal,
                )
                for response in baseline.responses:
                    response.revised_signal = response.original_signal
                    response.revised_confidence = response.original_confidence
                baseline.mode = "unsafe_test_mediator"
                return baseline

        synthesis = _synthesize_high_conflict(UnsafeProjectionMediator())

        projection = synthesis["revision_projection"]
        self.assertEqual(projection["source_mode"], "unsafe_test_mediator")
        self.assertEqual(projection["changed_skill_count"], 0)
        self.assertEqual(projection["projected_signal"], "hold")


class TestStrategyDeliberationV1(unittest.TestCase):
    def test_llm_mediator_accepts_schema_valid_payload(self):
        def fake_completion(messages):
            request = _request_payload(messages)
            payload = request["baseline_deliberation"]
            payload["summary"]["confidence_adjustment"] = -0.09
            payload["summary"]["confidence_adjustment_reason_key"] = (
                "deliberation.confidence.llm_v1_more_conservative"
            )
            return json.dumps(payload)

        synthesis = _synthesize_high_conflict(LLMDeliberationMediator(fake_completion))

        self.assertEqual(synthesis["final_signal"], "hold")
        self.assertAlmostEqual(synthesis["confidence"], 0.59)
        self.assertEqual(synthesis["deliberation"]["mode"], "llm_mediator_v1")
        self.assertEqual(
            synthesis["deliberation"]["summary"]["confidence_adjustment_reason_key"],
            "deliberation.confidence.llm_v1_more_conservative",
        )

    def test_llm_mediator_rejects_reversed_revision_and_falls_back(self):
        def fake_completion(messages):
            request = _request_payload(messages)
            payload = request["baseline_deliberation"]
            payload["responses"][0]["revision"] = "reversed"
            payload["responses"][0]["revised_signal"] = "sell"
            return json.dumps(payload)

        synthesis = _synthesize_high_conflict(LLMDeliberationMediator(fake_completion))

        self.assertEqual(synthesis["final_signal"], "hold")
        self.assertAlmostEqual(synthesis["confidence"], 0.62)
        self.assertEqual(synthesis["deliberation"]["mode"], "mediator_v0")
        self.assertNotIn(
            "reversed",
            {response["revision"] for response in synthesis["deliberation"]["responses"]},
        )

    def test_llm_mediator_cannot_undo_baseline_softening(self):
        def fake_completion(messages):
            request = _request_payload(messages)
            payload = request["baseline_deliberation"]
            for response in payload["responses"]:
                response["revision"] = "unchanged"
                response["revised_signal"] = response["original_signal"]
                response["revised_confidence"] = response["original_confidence"]
            return json.dumps(payload)

        synthesis = _synthesize_high_conflict(LLMDeliberationMediator(fake_completion))

        self.assertEqual(synthesis["deliberation"]["mode"], "mediator_v0")
        self.assertAlmostEqual(synthesis["confidence"], 0.62)
        self.assertEqual(synthesis["revision_projection"]["changed_skill_count"], 2)

    def test_llm_mediator_cannot_raise_baseline_adjustment(self):
        def fake_completion(messages):
            request = _request_payload(messages)
            payload = request["baseline_deliberation"]
            payload["summary"]["confidence_adjustment"] = 0
            return json.dumps(payload)

        synthesis = _synthesize_high_conflict(LLMDeliberationMediator(fake_completion))

        self.assertEqual(synthesis["deliberation"]["mode"], "mediator_v0")
        self.assertEqual(
            synthesis["deliberation"]["summary"]["confidence_adjustment"],
            -0.06,
        )

    def test_llm_mediator_cannot_raise_softened_baseline_confidence(self):
        def fake_completion(messages):
            request = _request_payload(messages)
            payload = request["baseline_deliberation"]
            response = payload["responses"][0]
            self.assertEqual(response["revision"], "softened")
            response["revised_confidence"] = response["original_confidence"]
            return json.dumps(payload)

        synthesis = _synthesize_high_conflict(LLMDeliberationMediator(fake_completion))

        self.assertEqual(synthesis["deliberation"]["mode"], "mediator_v0")
        self.assertEqual(synthesis["revision_projection"]["changed_skill_count"], 2)


class TestStrategyDeliberationV2(unittest.TestCase):
    def test_self_review_mediator_accepts_participant_reviews(self):
        def fake_self_review(skill_id, messages):
            request = _request_payload(messages)
            response = request["baseline_response"]
            if skill_id == "bull_trend" and response["revision"] == "softened":
                response["revised_confidence"] = 0.7
                response["critique_key"] = "deliberation.self_review.bull_trend.softened"
            else:
                response["critique_key"] = "deliberation.self_review.hot_theme.unchanged"
            return json.dumps(response)

        synthesis = _synthesize_high_conflict(StrategySelfReviewMediator(fake_self_review))

        self.assertEqual(synthesis["final_signal"], "hold")
        self.assertEqual(synthesis["deliberation"]["mode"], "self_review_v2")
        self.assertEqual(synthesis["deliberation"]["summary"]["resolution_status"], "partially_resolved")
        self.assertEqual(synthesis["deliberation"]["summary"]["confidence_adjustment"], -0.06)
        responses = synthesis["deliberation"]["responses"]
        self.assertTrue(any(
            response["skill_id"] == "bull_trend"
            and response["revision"] == "softened"
            and response["revised_signal"] == "buy"
            for response in responses
        ))
        self.assertTrue(any(
            response["skill_id"] == "hot_theme"
            and response["revision"] == "softened"
            and response["revised_signal"] == "sell"
            for response in responses
        ))

    def test_self_review_projection_uses_accepted_reviews(self):
        def fake_self_review(skill_id, messages):
            request = _request_payload(messages)
            response = request["baseline_response"]
            if skill_id == "bull_trend" and response["revision"] == "softened":
                response["revised_confidence"] = 0.4
            return json.dumps(response)

        opinions = [
            StrategyOpinion(skill_id="bull_trend", signal="strong_buy", confidence=0.9),
            StrategyOpinion(skill_id="hot_theme", signal="strong_sell", confidence=0.7),
        ]
        conflicts = ConflictDetector().detect(opinions, final_signal="hold")
        mediator = StrategySelfReviewMediator(fake_self_review)

        synthesis = StrategySynthesizer(deliberation_mediator=mediator).synthesize(
            opinions,
            weighted_score=3.0,
            final_signal="hold",
            weighted_confidence=0.8,
            conflicts=conflicts,
        )

        self.assertEqual(synthesis["final_signal"], "hold")
        projection = synthesis["revision_projection"]
        self.assertEqual(projection["source_mode"], "self_review_v2")
        self.assertEqual(projection["projected_signal"], "hold")
        self.assertEqual(projection["changed_skill_count"], 2)
        self.assertEqual(projection["changed_skills"], ["bull_trend", "hot_theme"])

    def test_self_review_mediator_rejects_any_reversed_review_and_falls_back(self):
        def fake_self_review(skill_id, messages):
            request = _request_payload(messages)
            response = request["baseline_response"]
            if skill_id == "bull_trend":
                response["revision"] = "reversed"
                response["revised_signal"] = "sell"
            return json.dumps(response)

        synthesis = _synthesize_high_conflict(StrategySelfReviewMediator(fake_self_review))

        self.assertEqual(synthesis["final_signal"], "hold")
        self.assertEqual(synthesis["deliberation"]["mode"], "mediator_v0")
        self.assertAlmostEqual(synthesis["confidence"], 0.62)
        self.assertNotIn(
            "reversed",
            {response["revision"] for response in synthesis["deliberation"]["responses"]},
        )

    def test_self_review_mediator_cannot_undo_baseline_softening(self):
        def fake_self_review(skill_id, messages):
            request = _request_payload(messages)
            response = request["baseline_response"]
            response["revision"] = "unchanged"
            response["revised_signal"] = response["original_signal"]
            response["revised_confidence"] = response["original_confidence"]
            return json.dumps(response)

        synthesis = _synthesize_high_conflict(StrategySelfReviewMediator(fake_self_review))

        self.assertEqual(synthesis["deliberation"]["mode"], "mediator_v0")
        self.assertAlmostEqual(synthesis["confidence"], 0.62)
        self.assertEqual(synthesis["revision_projection"]["changed_skill_count"], 2)

    def test_self_review_mediator_cannot_raise_softened_baseline_confidence(self):
        def fake_self_review(skill_id, messages):
            request = _request_payload(messages)
            response = request["baseline_response"]
            if response["revision"] == "softened":
                response["revised_confidence"] = response["original_confidence"]
            return json.dumps(response)

        synthesis = _synthesize_high_conflict(StrategySelfReviewMediator(fake_self_review))

        self.assertEqual(synthesis["deliberation"]["mode"], "mediator_v0")
        self.assertEqual(synthesis["revision_projection"]["changed_skill_count"], 2)

    def test_self_review_keeps_baseline_adjustment_when_more_resolved(self):
        def fake_self_review(skill_id, messages):
            response = _request_payload(messages)["baseline_response"]
            response["revision"] = "softened"
            response["revised_signal"] = (
                "buy" if response["original_signal"] == "strong_buy" else "sell"
            )
            response["revised_confidence"] = 0.7
            return json.dumps(response)

        opinions = [
            StrategyOpinion(skill_id="bull_trend", signal="strong_buy", confidence=0.82),
            StrategyOpinion(skill_id="hot_theme", signal="strong_sell", confidence=0.78),
        ]
        conflicts = [StrategyConflict(
            conflict_type="directional_opposition",
            severity="medium",
            participants=["bull_trend", "hot_theme"],
        )]
        synthesis = StrategySynthesizer(
            deliberation_mediator=StrategySelfReviewMediator(fake_self_review),
        ).synthesize(
            opinions,
            weighted_score=3.0,
            final_signal="hold",
            weighted_confidence=0.8,
            conflicts=conflicts,
        )

        self.assertEqual(synthesis["deliberation"]["mode"], "self_review_v2")
        self.assertEqual(synthesis["deliberation"]["summary"]["resolution_status"], "partially_resolved")
        self.assertEqual(synthesis["deliberation"]["summary"]["confidence_adjustment"], -0.05)


class TestStrategyDeliberationV4(unittest.TestCase):
    def test_multi_round_mediator_accepts_configured_second_round(self):
        def fake_round(round_index, messages):
            request = _request_payload(messages)
            payload = request["current_deliberation"]
            self.assertEqual(round_index, 2)
            self.assertEqual(request["round_index"], 2)
            payload["responses"][0]["revised_confidence"] = 0.5
            payload["responses"][0]["critique_key"] = "deliberation.multi_round.bull_trend.further_softened"
            payload["summary"]["confidence_adjustment"] = -0.09
            payload["summary"]["confidence_adjustment_reason_key"] = (
                "deliberation.confidence.multi_round_more_conservative"
            )
            return json.dumps(payload)

        synthesis = _synthesize_high_conflict(
            MultiRoundDeliberationMediator(fake_round, max_rounds=2),
        )

        self.assertEqual(synthesis["final_signal"], "hold")
        self.assertAlmostEqual(synthesis["confidence"], 0.59)
        deliberation = synthesis["deliberation"]
        self.assertEqual(deliberation["mode"], "multi_round_v4")
        self.assertEqual(deliberation["rounds"], 2)
        self.assertEqual(deliberation["round_history"][0]["status"], "baseline")
        self.assertEqual(deliberation["round_history"][1]["status"], "accepted")
        self.assertEqual(
            deliberation["summary"]["confidence_adjustment_reason_key"],
            "deliberation.confidence.multi_round_more_conservative",
        )
        self.assertEqual(synthesis["revision_projection"]["source_mode"], "multi_round_v4")
        self.assertFalse(synthesis["revision_projection"]["final_signal_overridden"])

    def test_multi_round_mediator_rejects_confidence_increase_and_keeps_baseline(self):
        def fake_round(round_index, messages):
            request = _request_payload(messages)
            payload = request["current_deliberation"]
            payload["responses"][0]["revised_confidence"] = 0.99
            return json.dumps(payload)

        synthesis = _synthesize_high_conflict(
            MultiRoundDeliberationMediator(fake_round, max_rounds=2),
        )

        self.assertEqual(synthesis["deliberation"]["mode"], "mediator_v0")
        self.assertEqual(synthesis["deliberation"]["rounds"], 1)
        self.assertNotIn("round_history", synthesis["deliberation"])
        self.assertAlmostEqual(synthesis["confidence"], 0.62)

    def test_multi_round_mediator_cannot_undo_baseline_softening(self):
        def fake_round(round_index, messages):
            request = _request_payload(messages)
            payload = request["current_deliberation"]
            for response in payload["responses"]:
                response["revision"] = "unchanged"
                response["revised_signal"] = response["original_signal"]
                response["revised_confidence"] = response["original_confidence"]
            return json.dumps(payload)

        synthesis = _synthesize_high_conflict(
            MultiRoundDeliberationMediator(fake_round, max_rounds=2),
        )

        self.assertEqual(synthesis["deliberation"]["mode"], "mediator_v0")
        self.assertEqual(synthesis["revision_projection"]["changed_skill_count"], 2)

    def test_multi_round_mediator_respects_max_rounds_one(self):
        def fail_if_called(round_index, messages):
            raise AssertionError("round_completion should not be called")

        opinions = [
            StrategyOpinion(skill_id="bull_trend", signal="strong_buy", confidence=0.82),
            StrategyOpinion(skill_id="hot_theme", signal="strong_sell", confidence=0.78),
        ]
        conflicts = ConflictDetector().detect(opinions, final_signal="hold")
        mediator = MultiRoundDeliberationMediator(fail_if_called, max_rounds=1)

        synthesis = StrategySynthesizer(deliberation_mediator=mediator).synthesize(
            opinions,
            weighted_score=3.0,
            final_signal="hold",
            weighted_confidence=0.8,
            conflicts=conflicts,
        )

        self.assertEqual(synthesis["deliberation"]["mode"], "mediator_v0")
        self.assertEqual(synthesis["deliberation"]["rounds"], 1)


def _request_payload(messages):
    content = messages[1]["content"]
    _, raw_json = content.split("\n\n", 1)
    return json.loads(raw_json)


def _synthesize_high_conflict(mediator):
    opinions = [
        StrategyOpinion(skill_id="bull_trend", signal="strong_buy", confidence=0.82),
        StrategyOpinion(skill_id="hot_theme", signal="strong_sell", confidence=0.78),
    ]
    conflicts = ConflictDetector().detect(opinions, final_signal="hold")
    return StrategySynthesizer(deliberation_mediator=mediator).synthesize(
        opinions,
        weighted_score=3.0,
        final_signal="hold",
        weighted_confidence=0.8,
        conflicts=conflicts,
    )


if __name__ == "__main__":
    unittest.main()
