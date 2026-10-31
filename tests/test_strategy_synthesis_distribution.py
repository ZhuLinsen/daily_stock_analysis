# -*- coding: utf-8 -*-
"""W1-RED tests for the strategy_synthesis contract extension (issue #2071).

Covers the three appended top-level payload fields:
- ``schema_version`` ("strategy-synthesis-v1")
- ``signal_distribution`` (bullish/neutral/bearish: {count, weight_share})
- ``primary_dissent`` (highest-weight opposing opinion, deterministic order)

Rules pinned here (see plan W1 task 1):
- counts only include valid (non ``invalid_signal``) opinions
- ``weight_share`` = camp valid weight sum / valid weight sum, rounded to 4;
  zero/absent denominator -> all ``None`` (never fabricated)
- ``primary_dissent`` only from opposing camps; order = applied weight desc ->
  confidence desc -> skill_id asc; absent opposing/weights -> ``None``
- purely deterministic: no LLM involvement
- existing fields (final_signal/weighted_score/confidence/supporting/opposing)
  keep their pre-change baseline values; supporting/opposing items gain NO
  ``weight`` key.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from src.agent.protocols import AgentOpinion, StrategyOpinion
from src.agent.skills.engine import StrategyEngine
from src.agent.skills.synthesis import StrategySynthesizer
from src.report_language import normalize_strategy_synthesis_payload


SCHEMA_VERSION = "strategy-synthesis-v1"


class _NoLLMmediator:
    """Deliberation mediator stub that provably performs no LLM work."""

    def deliberate(self, opinions, conflicts, final_signal):
        return None


def _engine_opinions_unequal_weights():
    """3-skill fixture: buy 0.9 / buy 0.7 / sell 0.6 (all valid)."""
    return [
        AgentOpinion(agent_name="skill_alpha_buy", signal="buy", confidence=0.9),
        AgentOpinion(agent_name="skill_beta_buy", signal="buy", confidence=0.7),
        AgentOpinion(agent_name="skill_gamma_sell", signal="sell", confidence=0.6),
    ]


def _direct_synthesize(opinions, weights, *, final_signal, weighted_score, weighted_confidence):
    return StrategySynthesizer(deliberation_mediator=_NoLLMmediator()).synthesize(
        opinions,
        weighted_score=weighted_score,
        final_signal=final_signal,
        weighted_confidence=weighted_confidence,
        conflicts=[],
        opinion_weights=weights,
    )


class TestSignalDistributionEnginePath(unittest.TestCase):
    """Engine-path tests: StrategyEngine.process is the shortest fixture path."""

    def test_1_schema_version_present_on_engine_synthesis(self):
        result = StrategyEngine().process(_engine_opinions_unequal_weights())

        self.assertIsNotNone(result.synthesis_dict)
        self.assertEqual(result.synthesis_dict["schema_version"], SCHEMA_VERSION)

    def test_2_camp_mapping_one_skill_per_camp(self):
        result = StrategyEngine().process(
            [
                AgentOpinion(agent_name="skill_x", signal="buy", confidence=0.5),
                AgentOpinion(agent_name="skill_y", signal="hold", confidence=0.5),
                AgentOpinion(agent_name="skill_z", signal="sell", confidence=0.5),
            ]
        )

        distribution = result.synthesis_dict["signal_distribution"]
        self.assertEqual(distribution["bullish"]["count"], 1)
        self.assertEqual(distribution["neutral"]["count"], 1)
        self.assertEqual(distribution["bearish"]["count"], 1)

        # strong_buy/strong_sell map to the same camps as buy/sell.
        payload = _direct_synthesize(
            [
                StrategyOpinion(skill_id="sb", agent_name="skill_sb", signal="strong_buy", confidence=0.6),
                StrategyOpinion(skill_id="ho", agent_name="skill_ho", signal="hold", confidence=0.6),
                StrategyOpinion(skill_id="ss", agent_name="skill_ss", signal="strong_sell", confidence=0.6),
            ],
            weights=[0.6, 0.6, 0.6],
            final_signal="hold",
            weighted_score=3.0,
            weighted_confidence=0.6,
        )
        distribution = payload["signal_distribution"]
        self.assertEqual(distribution["bullish"]["count"], 1)
        self.assertEqual(distribution["neutral"]["count"], 1)
        self.assertEqual(distribution["bearish"]["count"], 1)

    def test_3_invalid_opinions_excluded_from_distribution(self):
        result = StrategyEngine().process(
            [
                AgentOpinion(agent_name="skill_a", signal="buy", confidence=0.8),
                AgentOpinion(agent_name="skill_bad", signal="moon", confidence=0.9),
            ]
        )

        distribution = result.synthesis_dict["signal_distribution"]
        self.assertEqual(distribution["bullish"]["count"], 1)
        self.assertEqual(distribution["neutral"]["count"], 0)
        self.assertEqual(distribution["bearish"]["count"], 0)
        self.assertEqual(result.synthesis_dict["summary_params"]["invalid_opinion_count"], 1)

        # Same isolation holds on the direct synthesize path where an
        # invalid StrategyOpinion stays inside the opinions list: neither its
        # count nor its weight may enter any camp or the share denominator.
        invalid = StrategyOpinion(
            skill_id="bad",
            agent_name="skill_bad",
            signal="hold",
            confidence=0.9,
            invalid_signal=True,
        )
        payload = _direct_synthesize(
            [
                StrategyOpinion(skill_id="a", agent_name="skill_a", signal="buy", confidence=0.8),
                invalid,
            ],
            weights=[0.8, 0.9],
            final_signal="buy",
            weighted_score=4.0,
            weighted_confidence=0.8,
        )
        distribution = payload["signal_distribution"]
        self.assertEqual(distribution["bullish"]["count"], 1)
        self.assertEqual(distribution["neutral"]["count"], 0)
        self.assertEqual(distribution["bearish"]["count"], 0)
        self.assertEqual(distribution["bullish"]["weight_share"], 1.0)
        self.assertEqual(distribution["neutral"]["weight_share"], 0.0)
        self.assertEqual(distribution["bearish"]["weight_share"], 0.0)

    def test_4_weight_share_normalization_unequal_weights(self):
        result = StrategyEngine().process(_engine_opinions_unequal_weights())

        distribution = result.synthesis_dict["signal_distribution"]
        # weights: 0.9 + 0.7 = 1.6 bullish, 0.6 bearish, valid sum 2.2
        self.assertEqual(distribution["bullish"]["weight_share"], 0.7273)
        self.assertEqual(distribution["neutral"]["weight_share"], 0.0)
        self.assertEqual(distribution["bearish"]["weight_share"], 0.2727)
        share_sum = sum(
            distribution[camp]["weight_share"] for camp in ("bullish", "neutral", "bearish")
        )
        self.assertLess(abs(share_sum - 1.0), 1e-3)

    def test_5_zero_weight_denominator_shares_none_counts_real(self):
        result = StrategyEngine().process(
            [
                AgentOpinion(agent_name="skill_alpha_buy", signal="buy", confidence=0.0),
                AgentOpinion(agent_name="skill_beta_buy", signal="buy", confidence=0.0),
                AgentOpinion(agent_name="skill_gamma_sell", signal="sell", confidence=0.0),
            ]
        )

        distribution = result.synthesis_dict["signal_distribution"]
        # counts stay factual even though all weights are zero
        self.assertEqual(distribution["bullish"]["count"], 2)
        self.assertEqual(distribution["neutral"]["count"], 0)
        self.assertEqual(distribution["bearish"]["count"], 1)
        self.assertIsNone(distribution["bullish"]["weight_share"])
        self.assertIsNone(distribution["neutral"]["weight_share"])
        self.assertIsNone(distribution["bearish"]["weight_share"])
        # full weight tie (0.0) + confidence tie (0.0) -> skill_id ascending
        self.assertEqual(result.synthesis_dict["primary_dissent"]["skill_id"], "alpha_buy")

    def test_6_no_consensus_stub_carries_new_fields(self):
        result = StrategyEngine().process(
            [
                AgentOpinion(agent_name="skill_bad0", signal="moon", confidence=0.9),
                AgentOpinion(agent_name="skill_bad1", signal="", confidence=0.9),
            ]
        )

        stub = result.synthesis_dict
        self.assertIsNotNone(stub)
        self.assertEqual(stub["schema_version"], SCHEMA_VERSION)
        self.assertEqual(
            stub["signal_distribution"],
            {
                "bullish": {"count": 0, "weight_share": None},
                "neutral": {"count": 0, "weight_share": None},
                "bearish": {"count": 0, "weight_share": None},
            },
        )
        self.assertIsNone(stub["primary_dissent"])

    def test_8_single_skill_no_opposing_dissent_none(self):
        hold_result = StrategyEngine().process(
            [AgentOpinion(agent_name="skill_solo", signal="hold", confidence=0.5)]
        )
        distribution = hold_result.synthesis_dict["signal_distribution"]
        self.assertEqual(distribution["neutral"]["count"], 1)
        self.assertEqual(distribution["bullish"]["count"], 0)
        self.assertEqual(distribution["bearish"]["count"], 0)
        self.assertIsNone(hold_result.synthesis_dict["primary_dissent"])

        buy_result = StrategyEngine().process(
            [AgentOpinion(agent_name="skill_solo", signal="buy", confidence=0.5)]
        )
        distribution = buy_result.synthesis_dict["signal_distribution"]
        self.assertEqual(distribution["bullish"]["count"], 1)
        self.assertIsNone(buy_result.synthesis_dict["primary_dissent"])

    def test_10_existing_payload_fields_keep_baseline_values(self):
        """Baseline recorded before the change (worktree @ ec66bf46+).

        The appended fields must not perturb any existing payload value, and
        supporting/opposing items must NOT gain a ``weight`` key (plan Q1).
        """
        result = StrategyEngine().process(_engine_opinions_unequal_weights())
        payload = result.synthesis_dict

        self.assertEqual(payload["final_signal"], "hold")
        self.assertEqual(payload["weighted_score"], 3.4545)
        self.assertEqual(payload["confidence"], 0.6517)
        self.assertEqual(payload["original_confidence"], 0.7545)
        self.assertEqual(
            payload["supporting_skills"],
            [],
        )
        self.assertEqual(
            payload["opposing_skills"],
            [
                {
                    "agent_name": "skill_alpha_buy",
                    "conditions_met": [],
                    "confidence": 0.9,
                    "invalid_signal": False,
                    "reasoning": "",
                    "score_adjustment": 0.0,
                    "signal": "buy",
                    "skill_id": "alpha_buy",
                },
                {
                    "agent_name": "skill_beta_buy",
                    "conditions_met": [],
                    "confidence": 0.7,
                    "invalid_signal": False,
                    "reasoning": "",
                    "score_adjustment": 0.0,
                    "signal": "buy",
                    "skill_id": "beta_buy",
                },
                {
                    "agent_name": "skill_gamma_sell",
                    "conditions_met": [],
                    "confidence": 0.6,
                    "invalid_signal": False,
                    "reasoning": "",
                    "score_adjustment": 0.0,
                    "signal": "sell",
                    "skill_id": "gamma_sell",
                },
            ],
        )
        for item in [*payload["supporting_skills"], *payload["opposing_skills"]]:
            self.assertNotIn("weight", item)


class TestPrimaryDissentSelection(unittest.TestCase):
    """Direct synthesize calls with explicit weights pin the ordering rule."""

    def test_7a_heavier_applied_weight_beats_higher_confidence(self):
        payload = _direct_synthesize(
            [
                StrategyOpinion(skill_id="skill_p", agent_name="skill_p", signal="sell", confidence=0.9),
                StrategyOpinion(skill_id="skill_q", agent_name="skill_q", signal="sell", confidence=0.5),
            ],
            weights=[0.4, 0.8],
            final_signal="buy",
            weighted_score=4.0,
            weighted_confidence=0.7,
        )

        dissent = payload["primary_dissent"]
        self.assertEqual(
            dissent,
            {
                "skill_id": "skill_q",
                "agent_name": "skill_q",
                "signal": "sell",
                "confidence": 0.5,
                "reasoning": "",
            },
        )

    def test_7b_weight_tie_broken_by_confidence_desc(self):
        payload = _direct_synthesize(
            [
                StrategyOpinion(skill_id="skill_m", agent_name="skill_m", signal="sell", confidence=0.6),
                StrategyOpinion(skill_id="skill_n", agent_name="skill_n", signal="sell", confidence=0.9),
            ],
            weights=[0.5, 0.5],
            final_signal="buy",
            weighted_score=4.0,
            weighted_confidence=0.75,
        )

        self.assertEqual(payload["primary_dissent"]["skill_id"], "skill_n")

    def test_7c_full_tie_broken_by_skill_id_ascending(self):
        payload = _direct_synthesize(
            [
                StrategyOpinion(skill_id="skill_b", agent_name="skill_b", signal="sell", confidence=0.7),
                StrategyOpinion(skill_id="skill_a", agent_name="skill_a", signal="sell", confidence=0.7),
            ],
            weights=[0.5, 0.5],
            final_signal="buy",
            weighted_score=4.0,
            weighted_confidence=0.7,
        )

        self.assertEqual(payload["primary_dissent"]["skill_id"], "skill_a")

    def test_7d_dissent_only_from_opposing_camp(self):
        payload = _direct_synthesize(
            [
                # heaviest opinion overall, but it supports the final signal
                StrategyOpinion(skill_id="skill_sup", agent_name="skill_sup", signal="buy", confidence=0.95),
                StrategyOpinion(skill_id="skill_d", agent_name="skill_d", signal="sell", confidence=0.5),
            ],
            weights=[9.9, 0.2],
            final_signal="buy",
            weighted_score=4.0,
            weighted_confidence=0.7,
        )

        dissent = payload["primary_dissent"]
        self.assertIsNotNone(dissent)
        self.assertNotEqual(dissent["skill_id"], "skill_sup")
        self.assertEqual(dissent["skill_id"], "skill_d")


class TestDeterminismAndNoLLM(unittest.TestCase):
    def test_9_distribution_and_dissent_deterministic_and_llm_free(self):
        opinions = [
            StrategyOpinion(skill_id="alpha_buy", agent_name="skill_alpha_buy", signal="buy", confidence=0.9),
            StrategyOpinion(skill_id="beta_buy", agent_name="skill_beta_buy", signal="buy", confidence=0.7),
            StrategyOpinion(skill_id="gamma_sell", agent_name="skill_gamma_sell", signal="sell", confidence=0.6),
        ]
        weights = [0.9, 0.7, 0.6]

        default_run = StrategySynthesizer().synthesize(
            opinions,
            weighted_score=3.4545,
            final_signal="hold",
            weighted_confidence=0.7545,
            conflicts=[],
            opinion_weights=weights,
        )
        no_llm_run = StrategySynthesizer(deliberation_mediator=_NoLLMmediator()).synthesize(
            opinions,
            weighted_score=3.4545,
            final_signal="hold",
            weighted_confidence=0.7545,
            conflicts=[],
            opinion_weights=weights,
        )
        repeat_run = StrategySynthesizer(deliberation_mediator=_NoLLMmediator()).synthesize(
            opinions,
            weighted_score=3.4545,
            final_signal="hold",
            weighted_confidence=0.7545,
            conflicts=[],
            opinion_weights=weights,
        )

        # Identical regardless of any deliberation mediator (LLM or not) and
        # byte-stable across repeated runs.
        self.assertEqual(
            json.dumps(default_run["signal_distribution"], sort_keys=True),
            json.dumps(no_llm_run["signal_distribution"], sort_keys=True),
        )
        self.assertEqual(
            json.dumps(default_run["primary_dissent"], sort_keys=True),
            json.dumps(no_llm_run["primary_dissent"], sort_keys=True),
        )
        self.assertEqual(
            json.dumps(no_llm_run["signal_distribution"], sort_keys=True),
            json.dumps(repeat_run["signal_distribution"], sort_keys=True),
        )
        self.assertEqual(
            json.dumps(no_llm_run["primary_dissent"], sort_keys=True),
            json.dumps(repeat_run["primary_dissent"], sort_keys=True),
        )
        self.assertEqual(
            no_llm_run["signal_distribution"],
            {
                "bullish": {"count": 2, "weight_share": 0.7273},
                "neutral": {"count": 0, "weight_share": 0.0},
                "bearish": {"count": 1, "weight_share": 0.2727},
            },
        )
        self.assertEqual(no_llm_run["primary_dissent"]["skill_id"], "alpha_buy")

        # Engine path is equally deterministic across engine instances.
        first = StrategyEngine().process(_engine_opinions_unequal_weights()).synthesis_dict
        second = StrategyEngine().process(_engine_opinions_unequal_weights()).synthesis_dict
        self.assertEqual(
            json.dumps(first["signal_distribution"], sort_keys=True),
            json.dumps(second["signal_distribution"], sort_keys=True),
        )
        self.assertEqual(
            json.dumps(first["primary_dissent"], sort_keys=True),
            json.dumps(second["primary_dissent"], sort_keys=True),
        )


class TestNormalizeSynthesisPayloadExtension(unittest.TestCase):
    """report_language.normalize_strategy_synthesis_payload sanitizes new fields."""

    def test_11_normalize_sanitizes_new_fields_and_keeps_valid_ones(self):
        valid = normalize_strategy_synthesis_payload(
            {
                "schema_version": SCHEMA_VERSION,
                "final_signal": "hold",
                "signal_distribution": {"bullish": {"count": 1, "weight_share": 1.0}},
                "primary_dissent": {"skill_id": "x", "agent_name": "skill_x"},
            }
        )
        self.assertEqual(valid["schema_version"], SCHEMA_VERSION)
        self.assertEqual(valid["signal_distribution"], {"bullish": {"count": 1, "weight_share": 1.0}})
        self.assertEqual(valid["primary_dissent"], {"skill_id": "x", "agent_name": "skill_x"})

        malformed = normalize_strategy_synthesis_payload(
            {
                "schema_version": 123,
                "signal_distribution": "oops",
                "primary_dissent": ["not", "a", "dict"],
            }
        )
        self.assertIsNone(malformed["schema_version"])
        self.assertIsNone(malformed["signal_distribution"])
        self.assertIsNone(malformed["primary_dissent"])

        # Legacy payloads without the new keys normalize to explicit Nones.
        legacy = normalize_strategy_synthesis_payload({"final_signal": "buy"})
        self.assertIsNone(legacy["schema_version"])
        self.assertIsNone(legacy["signal_distribution"])
        self.assertIsNone(legacy["primary_dissent"])


if __name__ == "__main__":
    unittest.main()
