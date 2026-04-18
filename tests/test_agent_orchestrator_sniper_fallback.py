# -*- coding: utf-8 -*-
"""Regression tests for AgentOrchestrator sniper point fallbacks."""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.agent.orchestrator import AgentOrchestrator
from src.agent.protocols import AgentContext


class TestAgentOrchestratorSniperFallback(unittest.TestCase):
    def test_secondary_buy_does_not_duplicate_ideal_buy(self):
        orch = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
        )
        ctx = AgentContext(query="test", stock_code="301308", stock_name="江波龙")

        payload = {
            "decision_type": "buy",
            "analysis_summary": "趋势仍强，等待回踩。",
            "dashboard": {
                "key_levels": {
                    "support": 301.61,
                    "stop_loss": 295.0,
                    "resistance": 340.44,
                }
            },
        }

        normalized = orch._normalize_dashboard_payload(payload, ctx)

        self.assertIsNotNone(normalized)
        sniper = normalized["dashboard"]["battle_plan"]["sniper_points"]
        self.assertEqual(sniper["ideal_buy"], 301.61)
        self.assertEqual(sniper["secondary_buy"], "N/A")

    def test_secondary_buy_numeric_string_does_not_duplicate_ideal_buy(self):
        orch = AgentOrchestrator(
            tool_registry=MagicMock(),
            llm_adapter=MagicMock(),
        )
        ctx = AgentContext(query="test", stock_code="301308", stock_name="江波龙")

        payload = {
            "decision_type": "buy",
            "analysis_summary": "趋势仍强，等待回踩。",
            "dashboard": {
                "battle_plan": {
                    "sniper_points": {
                        "secondary_buy": "301.61",
                    }
                },
                "key_levels": {
                    "support": 301.61,
                    "stop_loss": 295.0,
                    "resistance": 340.44,
                },
            },
        }

        normalized = orch._normalize_dashboard_payload(payload, ctx)

        self.assertIsNotNone(normalized)
        sniper = normalized["dashboard"]["battle_plan"]["sniper_points"]
        self.assertEqual(sniper["ideal_buy"], 301.61)
        self.assertEqual(sniper["secondary_buy"], "N/A")


if __name__ == "__main__":
    unittest.main()
