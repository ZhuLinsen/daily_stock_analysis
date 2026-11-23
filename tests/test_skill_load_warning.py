# -*- coding: utf-8 -*-
"""Tests that skill-loading exceptions emit warning logs instead of being silently swallowed."""

import logging
import unittest
from unittest.mock import patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from bot.commands.ask import AskCommand
from src.agent.skills.aggregator import SkillAggregator
from src.agent.skills.router import SkillRouter


class AskCommandSkillLoadWarningTests(unittest.TestCase):
    """AskCommand._load_skills and _get_default_skill_id must log on failure."""

    def test_load_skills_logs_warning_on_exception(self) -> None:
        with patch("src.agent.factory.get_skill_manager", side_effect=RuntimeError("factory broken")):
            with self.assertLogs("bot.commands.ask", level=logging.WARNING) as cm:
                result = AskCommand._load_skills()
        self.assertEqual(result, [])
        self.assertTrue(any("Failed to load skills" in line for line in cm.output))

    def test_get_default_skill_id_logs_warning_on_exception(self) -> None:
        with patch.object(AskCommand, "_load_skills", side_effect=RuntimeError("boom")):
            with self.assertLogs("bot.commands.ask", level=logging.WARNING) as cm:
                result = AskCommand._get_default_skill_id()
        self.assertEqual(result, "")
        self.assertTrue(any("Failed to resolve default skill id" in line for line in cm.output))


class SkillRouterWarningTests(unittest.TestCase):
    """SkillRouter methods must log on failure."""

    def test_get_available_skills_logs_warning(self) -> None:
        with patch("src.agent.factory.get_skill_manager", side_effect=RuntimeError("no manager")):
            with patch("src.agent.factory._SKILL_MANAGER_PROTOTYPE", None):
                with self.assertLogs("src.agent.skills.router", level=logging.WARNING) as cm:
                    result = SkillRouter._get_available_skills()
        self.assertEqual(result, [])
        self.assertTrue(any("Failed to get available skills" in line for line in cm.output))

    def test_get_routing_mode_logs_warning(self) -> None:
        with patch("src.config.get_config", side_effect=RuntimeError("no config")):
            with self.assertLogs("src.agent.skills.router", level=logging.WARNING) as cm:
                result = SkillRouter._get_routing_mode()
        self.assertEqual(result, "auto")
        self.assertTrue(any("Failed to get routing mode" in line for line in cm.output))

    def test_get_manual_skills_logs_warning(self) -> None:
        with patch("src.config.get_config", side_effect=RuntimeError("cfg error")):
            with patch.object(SkillRouter, "_get_available_skills", return_value=[]):
                with self.assertLogs("src.agent.skills.router", level=logging.WARNING) as cm:
                    result = SkillRouter._get_manual_skills(max_count=3)
        self.assertIsInstance(result, list)
        self.assertTrue(any("Failed to get manual skills config" in line for line in cm.output))


class SkillAggregatorDebugLogTests(unittest.TestCase):
    """SkillAggregator helpers must log at debug level on failure."""

    def test_outcome_weights_log_debug_on_exception(self) -> None:
        class FailingWeightService:
            def compute_weights(self, _skill_ids):
                raise RuntimeError("no statistics")

        aggregator = SkillAggregator(
            weight_service=FailingWeightService()
        )
        with self.assertLogs(
            "src.agent.skills.aggregator",
            level=logging.DEBUG,
        ) as cm:
            result = aggregator._performance_weights(["some_skill"])
        self.assertEqual(result, {"some_skill": 1.0})
        self.assertTrue(
            any("outcome weights" in line.lower() for line in cm.output)
        )

    def test_use_outcome_autoweight_logs_debug_on_exception(self) -> None:
        with patch("src.config.get_config", side_effect=RuntimeError("cfg error")):
            with self.assertLogs("src.agent.skills.aggregator", level=logging.DEBUG) as cm:
                result = SkillAggregator._use_outcome_autoweight()
        self.assertTrue(result)
        self.assertTrue(
            any("outcome autoweight" in line.lower() for line in cm.output)
        )


if __name__ == "__main__":
    unittest.main()
