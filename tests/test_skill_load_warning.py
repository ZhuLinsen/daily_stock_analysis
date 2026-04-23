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

    def test_backtest_factor_logs_debug_on_exception(self) -> None:
        with patch("src.agent.skills.aggregator.SkillAggregator._use_backtest_autoweight", return_value=True):
            with patch("src.services.backtest_service.BacktestService", side_effect=ImportError("no backtest")):
                with self.assertLogs("src.agent.skills.aggregator", level=logging.DEBUG) as cm:
                    result = SkillAggregator._backtest_factor("some_skill", 30)
        self.assertEqual(result, 1.0)
        self.assertTrue(any("backtest factor" in line.lower() for line in cm.output))

    def test_use_backtest_autoweight_logs_debug_on_exception(self) -> None:
        with patch("src.config.get_config", side_effect=RuntimeError("cfg error")):
            with self.assertLogs("src.agent.skills.aggregator", level=logging.DEBUG) as cm:
                result = SkillAggregator._use_backtest_autoweight()
        self.assertTrue(result)
        self.assertTrue(any("backtest autoweight" in line.lower() for line in cm.output))


if __name__ == "__main__":
    unittest.main()
