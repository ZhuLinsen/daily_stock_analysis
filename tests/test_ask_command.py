# -*- coding: utf-8 -*-
"""Tests for AskCommand skill selection and multi-stock support."""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    from tests.litellm_stub import ensure_litellm_stub

    ensure_litellm_stub()

from bot.commands.ask import AskCommand
from bot.models import BotMessage, ChatType
from src.agent.skills.base import Skill


class AskCommandSkillSelectionTestCase(unittest.TestCase):
    """Verify /ask skill selection follows skill metadata instead of hardcoded ids."""

    def test_parse_skill_defaults_to_primary_metadata_skill(self) -> None:
        command = AskCommand()
        skills = [
            Skill(
                name="box_oscillation",
                display_name="箱体震荡",
                description="box",
                instructions="box",
                default_priority=30,
            ),
            Skill(
                name="wave_theory",
                display_name="波浪理论",
                description="wave",
                instructions="wave",
                default_active=True,
                default_priority=10,
            ),
        ]

        with patch.object(AskCommand, "_load_skills", return_value=skills):
            self.assertEqual(command._parse_skill(["600519"]), "wave_theory")

    def test_parse_skill_matches_alias_before_default(self) -> None:
        command = AskCommand()
        skills = [
            Skill(
                name="bull_trend",
                display_name="默认多头趋势",
                description="trend",
                instructions="trend",
                aliases=["趋势", "趋势分析"],
                default_active=True,
                default_priority=10,
            ),
            Skill(
                name="chan_theory",
                display_name="缠论",
                description="chan",
                instructions="chan",
                aliases=["缠论", "缠论分析"],
                default_priority=40,
            ),
        ]

        with patch.object(AskCommand, "_load_skills", return_value=skills):
            self.assertEqual(command._parse_skill(["600519", "请", "用缠论分析"]), "chan_theory")


class TestAskCommandMultiStock(unittest.TestCase):
    """Test multi-stock ask command aggregation output."""

    @staticmethod
    def _message() -> BotMessage:
        return BotMessage(
            platform="feishu",
            message_id="msg-1",
            user_id="user-1",
            user_name="tester",
            chat_id="chat-1",
            chat_type=ChatType.PRIVATE,
            content="/ask 600519,000858",
        )

    @staticmethod
    def _dashboard(code: str) -> dict:
        return {
            "stock_name": f"股票{code}",
            "decision_type": "buy",
            "sentiment_score": 72,
            "trend_prediction": "看多",
            "operation_advice": "买入",
            "analysis_summary": f"{code} summary",
            "risk_warning": f"{code} risk",
            "dashboard": {
                "battle_plan": {
                    "sniper_points": {
                        "ideal_buy": "10.0",
                        "stop_loss": "9.5",
                    }
                }
            },
        }

    def test_analyze_multi_includes_portfolio_overlay(self):
        command = AskCommand()
        config = SimpleNamespace()
        message = self._message()

        class FakeExecutor:
            def run(self, task, context=None):
                code = context["stock_code"]
                return SimpleNamespace(
                    success=True,
                    content=f"{code} raw content",
                    dashboard=TestAskCommandMultiStock._dashboard(code),
                )

        with patch("src.agent.factory.build_agent_executor", return_value=FakeExecutor()):
            with patch.object(command, "_build_portfolio_section", return_value="## 组合视角\n组合摘要"):
                with patch("src.agent.conversation.conversation_manager"):
                    response = command._analyze_multi(config, message, ["600519", "000858"], None, "")

        self.assertTrue(response.markdown)
        self.assertIn("## 组合视角", response.text)
        self.assertIn("| 600519 | buy | 72% |", response.text)
        self.assertIn("### 000858", response.text)

    def test_merge_code_args_keeps_skill_token_outside_stock_list(self):
        command = AskCommand()

        raw_code_str, remaining_args = command._merge_code_args(["AAPL", "trend"])

        self.assertEqual(raw_code_str, "AAPL")
        self.assertEqual(remaining_args, ["trend"])
        self.assertEqual(command._parse_stock_codes(raw_code_str), ["AAPL"])

    def test_merge_code_args_keeps_comma_split_multi_stock_support(self):
        command = AskCommand()

        raw_code_str, remaining_args = command._merge_code_args(["600519,", "000858", "波浪理论"])

        self.assertEqual(raw_code_str, "600519,000858")
        self.assertEqual(remaining_args, ["波浪理论"])

    def test_build_portfolio_section_reads_assessment(self):
        command = AskCommand()
        results = {
            "600519": {
                "signal": "buy",
                "confidence": 0.8,
                "summary": "茅台 summary",
                "stock_name": "贵州茅台",
                "risk_flags": [{"category": "portfolio_input", "description": "估值偏高", "severity": "medium"}],
            },
            "000858": {
                "signal": "hold",
                "confidence": 0.6,
                "summary": "五粮液 summary",
                "stock_name": "五粮液",
                "risk_flags": [],
            },
        }

        def fake_run(self, ctx, progress_callback=None):
            ctx.data["portfolio_assessment"] = {
                "summary": "组合偏消费集中，建议控制仓位。",
                "portfolio_risk_score": 7,
                "sector_warnings": ["白酒板块集中度过高"],
                "correlation_warnings": ["600519 与 000858 相关性偏高"],
                "rebalance_suggestions": ["降低单一行业暴露"],
                "positions": [
                    {"code": "600519", "suggested_weight": 0.4, "signal": "buy"},
                    {"code": "000858", "suggested_weight": 0.2, "signal": "hold"},
                ],
            }
            return SimpleNamespace(success=True)

        with patch("src.agent.factory.get_tool_registry", return_value=MagicMock()):
            with patch("src.agent.llm_adapter.LLMToolAdapter", return_value=MagicMock()):
                with patch("src.agent.agents.portfolio_agent.PortfolioAgent.run", new=fake_run):
                    text = command._build_portfolio_section(SimpleNamespace(), ["600519", "000858"], results)

        self.assertIn("## 组合视角", text)
        self.assertIn("组合偏消费集中", text)
        self.assertIn("建议仓位", text)

    def test_build_portfolio_section_returns_quickly_on_timeout(self):
        command = AskCommand()
        results = {
            "600519": {
                "signal": "buy",
                "confidence": 0.8,
                "summary": "茅台 summary",
                "stock_name": "贵州茅台",
                "risk_flags": [],
            },
            "000858": {
                "signal": "hold",
                "confidence": 0.6,
                "summary": "五粮液 summary",
                "stock_name": "五粮液",
                "risk_flags": [],
            },
        }

        def slow_run(self, ctx, progress_callback=None):
            time.sleep(0.1)
            ctx.data["portfolio_assessment"] = {"summary": "late summary"}
            return SimpleNamespace(success=True)

        started_at = time.monotonic()
        with patch("src.agent.factory.get_tool_registry", return_value=MagicMock()):
            with patch("src.agent.llm_adapter.LLMToolAdapter", return_value=MagicMock()):
                with patch("src.agent.agents.portfolio_agent.PortfolioAgent.run", new=slow_run):
                    text = command._build_portfolio_section(
                        SimpleNamespace(),
                        ["600519", "000858"],
                        results,
                        timeout_s=0.01,
                    )

        elapsed_s = time.monotonic() - started_at
        self.assertEqual(text, "")
        self.assertLess(elapsed_s, 0.08)

    def test_analyze_multi_falls_back_to_text_when_dashboard_parse_fails(self):
        command = AskCommand()
        config = SimpleNamespace()
        message = self._message()

        class FakeExecutor:
            def run(self, task, context=None):
                code = context["stock_code"]
                return SimpleNamespace(
                    success=False,
                    content=f"{code} 自由文本分析",
                    dashboard=None,
                    error="Failed to parse dashboard JSON from agent response",
                )

        with patch("src.agent.factory.build_agent_executor", return_value=FakeExecutor()):
            with patch.object(command, "_build_portfolio_section", return_value=""):
                with patch("src.agent.conversation.conversation_manager"):
                    response = command._analyze_multi(config, message, ["600519", "000858"], None, "")

        self.assertIn("600519 自由文本分析", response.text)
        self.assertNotIn("⚠️ 分析失败: Failed to parse dashboard JSON", response.text)

    def test_analyze_multi_persists_formatted_history_instead_of_raw_json(self):
        command = AskCommand()
        config = SimpleNamespace()
        message = self._message()

        class FakeExecutor:
            def run(self, task, context=None):
                code = context["stock_code"]
                return SimpleNamespace(
                    success=True,
                    content='{"raw":"json"}',
                    dashboard=TestAskCommandMultiStock._dashboard(code),
                )

        with patch("src.agent.factory.build_agent_executor", return_value=FakeExecutor()):
            with patch.object(command, "_build_portfolio_section", return_value=""):
                with patch("src.agent.conversation.conversation_manager") as mock_cm:
                    command._analyze_multi(config, message, ["600519", "000858"], None, "")

        assistant_messages = [
            call.args[2]
            for call in mock_cm.add_message.call_args_list
            if len(call.args) >= 3 and call.args[1] == "assistant"
        ]
        self.assertEqual(len(assistant_messages), 2)
        self.assertTrue(all("**结论**: buy" in text for text in assistant_messages))
        self.assertTrue(all('{"raw":"json"}' not in text for text in assistant_messages))

    def test_analyze_multi_prewarms_db_before_parallel_history_writes(self):
        command = AskCommand()
        config = SimpleNamespace()
        message = self._message()
        call_order = []

        class FakeExecutor:
            def run(self, task, context=None):
                code = context["stock_code"]
                return SimpleNamespace(
                    success=True,
                    content=f"{code} raw content",
                    dashboard=TestAskCommandMultiStock._dashboard(code),
                )

        with patch("bot.commands.ask.get_db", side_effect=lambda: call_order.append("db")) as mock_get_db:
            with patch("src.agent.factory.build_agent_executor", return_value=FakeExecutor()):
                with patch.object(command, "_build_portfolio_section", return_value=""):
                    with patch("src.agent.conversation.conversation_manager") as mock_cm:
                        mock_cm.add_message.side_effect = lambda *args, **kwargs: call_order.append("history")
                        command._analyze_multi(config, message, ["600519", "000858"], None, "")

        mock_get_db.assert_called_once_with()
        self.assertTrue(call_order)
        self.assertEqual(call_order[0], "db")

    def test_format_stock_result_renders_numeric_sniper_points(self):
        dashboard = self._dashboard("600519")
        dashboard["dashboard"]["battle_plan"]["sniper_points"] = {
            "ideal_buy": 10.0,
            "secondary_buy": 9.8,
            "stop_loss": 9.5,
            "take_profit": 11.6,
        }

        text = AskCommand._format_stock_result("600519", dashboard, "raw content")

        self.assertIn("**关键点位**", text)
        self.assertIn("ideal_buy=10.0", text)
        self.assertIn("secondary_buy=9.8", text)
        self.assertIn("stop_loss=9.5", text)
        self.assertIn("take_profit=11.6", text)

    def test_analyze_single_passes_requested_skill_into_context(self):
        command = AskCommand()
        config = SimpleNamespace()
        message = self._message()
        captured = {}

        class FakeExecutor:
            def chat(self, message, session_id, progress_callback=None, context=None):
                captured["message"] = message
                captured["session_id"] = session_id
                captured["context"] = context
                return SimpleNamespace(success=True, content="analysis ok")

        with patch("src.agent.factory.build_agent_executor", return_value=FakeExecutor()):
            with patch.object(command, "_resolve_skill_name", return_value="缠论"):
                response = command._analyze_single(config, message, "600519", "chan_theory", "")

        self.assertIn("analysis ok", response.text)
        self.assertEqual(captured["context"]["stock_code"], "600519")
        self.assertEqual(captured["context"]["skills"], ["chan_theory"])
        self.assertEqual(captured["context"]["strategies"], ["chan_theory"])


class TestAskCommandSilentExceptionFix(unittest.TestCase):
    """Verify that _load_skills and _get_default_skill_id log warnings on failure."""

    def test_load_skills_logs_warning_and_returns_empty_list(self):
        boom = RuntimeError("skill manager unavailable")
        with patch("src.agent.factory.get_skill_manager", side_effect=boom):
            with self.assertLogs("bot.commands.ask", level="WARNING") as cm:
                result = AskCommand._load_skills()
        self.assertEqual(result, [])
        self.assertTrue(any("_load_skills failed" in line for line in cm.output))

    def test_get_default_skill_id_logs_warning_and_returns_empty_string(self):
        boom = RuntimeError("defaults unavailable")
        with patch.object(AskCommand, "_load_skills", return_value=[]):
            with patch("src.agent.skills.defaults.get_primary_default_skill_id", side_effect=boom):
                with self.assertLogs("bot.commands.ask", level="WARNING") as cm:
                    result = AskCommand._get_default_skill_id()
        self.assertEqual(result, "")
        self.assertTrue(any("_get_default_skill_id failed" in line for line in cm.output))


if __name__ == "__main__":
    unittest.main()
