# -*- coding: utf-8 -*-
"""
Tests for agent-mode pipeline integration.

Covers:
- Config: agent_mode, agent_max_steps, agent_skills fields
- _analyze_with_agent method
- _agent_result_to_analysis_result conversion
- YAML strategy loading (load_builtin_strategies)
"""

import json
import importlib
import types
import unittest
import sys
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _builtin_strategy_names() -> set[str]:
    strategies_dir = Path(__file__).resolve().parent.parent / "strategies"
    return {path.stem for path in strategies_dir.glob("*.yaml")}


# ============================================================
# Config tests
# ============================================================

class TestAgentConfig(unittest.TestCase):
    """Test agent-related configuration fields load correctly."""

    @patch.dict(os.environ, {}, clear=True)
    @patch('src.config.load_dotenv')
    def test_default_agent_config(self, _mock_dotenv):
        """Agent mode should be disabled by default."""
        from src.config import Config
        Config._instance = None
        config = Config._load_from_env()
        self.assertEqual(config.agent_litellm_model, "")
        self.assertFalse(config.agent_mode)
        self.assertEqual(config.agent_max_steps, 10)
        self.assertEqual(config.agent_skills, [])

    @patch.dict(os.environ, {
        'AGENT_MODE': 'true',
        'AGENT_MAX_STEPS': '15',
        'AGENT_SKILLS': 'dragon_head,shrink_pullback,volume_breakout',
    }, clear=True)
    def test_agent_config_from_env(self):
        """Agent config should be loaded from environment."""
        from src.config import Config
        Config._instance = None
        config = Config._load_from_env()
        self.assertTrue(config.agent_mode)
        self.assertEqual(config.agent_max_steps, 15)
        self.assertEqual(config.agent_skills, ['dragon_head', 'shrink_pullback', 'volume_breakout'])

    @patch.dict(os.environ, {'AGENT_MODE': 'false'}, clear=True)
    def test_agent_mode_disabled(self):
        """Explicitly disabled agent mode."""
        from src.config import Config
        Config._instance = None
        config = Config._load_from_env()
        self.assertFalse(config.agent_mode)

    @patch.dict(os.environ, {'AGENT_SKILLS': ''}, clear=True)
    def test_empty_skills_list(self):
        """Empty AGENT_SKILLS should produce empty list."""
        from src.config import Config
        Config._instance = None
        config = Config._load_from_env()
        self.assertEqual(config.agent_skills, [])

    @patch.dict(os.environ, {'AGENT_SKILLS': '  dragon_head , shrink_pullback  '}, clear=True)
    def test_skills_whitespace_handling(self):
        """Skills should have whitespace trimmed."""
        from src.config import Config
        Config._instance = None
        config = Config._load_from_env()
        self.assertEqual(config.agent_skills, ['dragon_head', 'shrink_pullback'])

    @patch.dict(os.environ, {'AGENT_LITELLM_MODEL': 'gpt-4o-mini'}, clear=True)
    def test_agent_is_available_when_agent_primary_model_is_configured(self):
        """Agent availability auto-detection should use effective Agent primary model."""
        from src.config import Config
        Config._instance = None
        config = Config._load_from_env()
        self.assertEqual(config.agent_litellm_model, 'openai/gpt-4o-mini')
        self.assertTrue(config.is_agent_available())


class TestAgentFactorySkillBaseline(unittest.TestCase):
    """Ensure explicit skill selection does not silently re-apply the default bull-trend baseline."""

    @staticmethod
    def _make_skill(name: str, *, default_active: bool = False, default_priority: int = 100):
        return SimpleNamespace(
            name=name,
            display_name=name,
            description=f"{name} desc",
            instructions=f"{name} instructions",
            default_active=default_active,
            default_router=default_active,
            default_priority=default_priority,
            user_invocable=True,
        )

    def _run_factory_case(self, config, *, request_skills, skill_catalog, instructions):
        skill_manager = MagicMock()
        skill_manager.list_skills.return_value = skill_catalog
        skill_manager.get_skill_instructions.return_value = instructions

        fake_llm_module = types.ModuleType("src.agent.llm_adapter")
        fake_llm_module.LLMToolAdapter = MagicMock(return_value=MagicMock())
        fake_executor_module = types.ModuleType("src.agent.executor")
        fake_executor_cls = MagicMock(return_value=MagicMock())
        fake_executor_module.AgentExecutor = fake_executor_cls

        with patch.dict(sys.modules, {
            "litellm": MagicMock(),
            "src.agent.llm_adapter": fake_llm_module,
            "src.agent.executor": fake_executor_module,
        }):
            factory_module = importlib.import_module("src.agent.factory")

            with patch.object(factory_module, "get_skill_manager", return_value=skill_manager), \
                 patch.object(factory_module, "get_tool_registry", return_value=MagicMock()):
                factory_module.build_agent_executor(config, skills=request_skills)

        return fake_executor_cls.call_args.kwargs, skill_manager

    def test_explicit_request_disables_default_skill_policy(self):
        config = SimpleNamespace(
            agent_arch="single",
            agent_skills=[],
            agent_max_steps=10,
            agent_orchestrator_timeout_s=600,
        )
        kwargs, skill_manager = self._run_factory_case(
            config,
            request_skills=["chan_theory"],
            skill_catalog=[
                self._make_skill("bull_trend", default_active=True, default_priority=10),
                self._make_skill("chan_theory", default_priority=20),
            ],
            instructions="chan_theory instructions",
        )

        self.assertEqual(kwargs["default_skill_policy"], "")
        skill_manager.activate.assert_called_once_with(["chan_theory"])

    def test_configured_skills_disable_default_skill_policy(self):
        config = SimpleNamespace(
            agent_arch="single",
            agent_skills=["wave_theory"],
            agent_max_steps=10,
            agent_orchestrator_timeout_s=600,
        )
        kwargs, skill_manager = self._run_factory_case(
            config,
            request_skills=None,
            skill_catalog=[
                self._make_skill("bull_trend", default_active=True, default_priority=10),
                self._make_skill("wave_theory", default_priority=20),
            ],
            instructions="wave_theory instructions",
        )

        self.assertEqual(kwargs["default_skill_policy"], "")
        skill_manager.activate.assert_called_once_with(["wave_theory"])

    def test_implicit_default_run_keeps_default_skill_policy(self):
        config = SimpleNamespace(
            agent_arch="single",
            agent_skills=[],
            agent_max_steps=10,
            agent_orchestrator_timeout_s=600,
        )
        kwargs, skill_manager = self._run_factory_case(
            config,
            request_skills=None,
            skill_catalog=[self._make_skill("bull_trend", default_active=True, default_priority=10)],
            instructions="bull_trend instructions",
        )

        self.assertIn("严进策略", kwargs["default_skill_policy"])
        skill_manager.activate.assert_called_once_with(["bull_trend"])

    def test_explicit_empty_request_falls_back_to_primary_default_skill(self):
        config = SimpleNamespace(
            agent_arch="single",
            agent_skills=[],
            agent_max_steps=10,
            agent_orchestrator_timeout_s=600,
        )
        kwargs, skill_manager = self._run_factory_case(
            config,
            request_skills=[],
            skill_catalog=[
                self._make_skill("bull_trend", default_active=True, default_priority=10),
                self._make_skill("chan_theory", default_priority=20),
            ],
            instructions="bull_trend instructions",
        )

        self.assertIn("严进策略", kwargs["default_skill_policy"])
        skill_manager.activate.assert_called_once_with(["bull_trend"])


# ============================================================
# AgentResult to AnalysisResult conversion
# ============================================================

class TestAgentResultConversion(unittest.TestCase):
    """Test _agent_result_to_analysis_result without spinning up the full pipeline."""

    def _make_pipeline(self):
        """Create a minimal StockAnalysisPipeline with mocked dependencies."""
        # We need to import and mock carefully to avoid touching real services
        with patch('src.core.pipeline.get_config') as mock_config, \
             patch('src.core.pipeline.get_db'), \
             patch('src.core.pipeline.DataFetcherManager'), \
             patch('src.core.pipeline.GeminiAnalyzer'), \
             patch('src.core.pipeline.NotificationService'), \
             patch('src.core.pipeline.SearchService'):

            mock_cfg = MagicMock()
            mock_cfg.max_workers = 2
            mock_cfg.agent_mode = True
            mock_cfg.agent_max_steps = 10
            mock_cfg.agent_skills = []
            mock_cfg.bocha_api_keys = []
            mock_cfg.tavily_api_keys = []
            mock_cfg.brave_api_keys = []
            mock_cfg.serpapi_keys = []
            mock_cfg.searxng_base_urls = []
            mock_cfg.searxng_public_instances_enabled = False
            mock_cfg.news_max_age_days = 7
            mock_cfg.enable_realtime_quote = True
            mock_cfg.enable_chip_distribution = True
            mock_cfg.realtime_source_priority = []
            mock_cfg.save_context_snapshot = False
            mock_config.return_value = mock_cfg

            from src.core.pipeline import StockAnalysisPipeline
            pipeline = StockAnalysisPipeline(config=mock_cfg)
            return pipeline

    def test_convert_success_dashboard(self):
        """Successful AgentResult should produce a valid AnalysisResult."""
        pipeline = self._make_pipeline()

        from src.agent.executor import AgentResult
        from src.enums import ReportType

        dashboard = {
            "stock_name": "贵州茅台",
            "sentiment_score": 80,
            "trend_prediction": "看多",
            "operation_advice": "持有",
            "decision_type": "hold",
            "confidence_level": "高",
            "dashboard": {"core_conclusion": {"one_sentence": "看好"}},
            "analysis_summary": "Testing",
            "key_points": "Strong",
            "risk_warning": "High valuation",
            "buy_reason": "Leader",
            "trend_analysis": "Upward",
            "technical_analysis": "Bullish MACD",
            "ma_analysis": "Golden cross",
            "volume_analysis": "Healthy volume",
            "pattern_analysis": "Cup and handle",
            "fundamental_analysis": "Strong revenue",
            "sector_position": "Liquor leader",
            "company_highlights": "Brand value",
            "news_summary": "Recent news",
            "market_sentiment": "Optimistic",
            "hot_topics": "Baijiu",
            "short_term_outlook": "Bullish",
            "medium_term_outlook": "Stable",
        }

        agent_result = AgentResult(
            success=True,
            content=json.dumps(dashboard),
            dashboard=dashboard,
            tool_calls_log=[{"step": 1, "tool": "echo", "success": True}],
            total_steps=3,
            total_tokens=500,
            provider="gemini",
        )

        result = pipeline._agent_result_to_analysis_result(
            agent_result, "600519", "贵州茅台", ReportType.SIMPLE, "q123"
        )

        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.code, "600519")
        self.assertEqual(result.name, "贵州茅台")
        self.assertEqual(result.sentiment_score, 80)
        self.assertEqual(result.trend_prediction, "看多")
        self.assertEqual(result.decision_type, "hold")
        self.assertIn("agent:gemini", result.data_sources)
        self.assertIsNotNone(result.dashboard)

    def test_convert_failed_dashboard(self):
        """Failed AgentResult should produce a minimal AnalysisResult."""
        pipeline = self._make_pipeline()

        from src.agent.executor import AgentResult
        from src.enums import ReportType

        agent_result = AgentResult(
            success=False,
            content="",
            dashboard=None,
            error="Max steps exceeded",
        )

        result = pipeline._agent_result_to_analysis_result(
            agent_result, "600519", "贵州茅台", ReportType.SIMPLE, "q123"
        )

        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertEqual(result.sentiment_score, 50)
        self.assertEqual(result.operation_advice, "观望")
        self.assertIn("Max steps exceeded", result.error_message)

    def test_convert_uses_dashboard_stock_name_when_input_is_placeholder(self):
        """When input name is placeholder-like, prefer dashboard stock_name."""
        pipeline = self._make_pipeline()

        from src.agent.executor import AgentResult
        from src.enums import ReportType

        agent_result = AgentResult(
            success=True,
            content="{}",
            dashboard={
                "stock_name": "科创芯片ETF",
                "sentiment_score": 75,
                "trend_prediction": "震荡偏多",
                "operation_advice": "持有",
                "decision_type": "hold",
            },
            provider="gemini",
        )

        result = pipeline._agent_result_to_analysis_result(
            agent_result, "588200", "股票588200", ReportType.SIMPLE, "q-placeholder"
        )
        self.assertEqual(result.name, "科创芯片ETF")

    def test_convert_keeps_input_stock_name_when_valid(self):
        """When input name is already valid, do not overwrite with dashboard value."""
        pipeline = self._make_pipeline()

        from src.agent.executor import AgentResult
        from src.enums import ReportType

        agent_result = AgentResult(
            success=True,
            content="{}",
            dashboard={
                "stock_name": "错误名称",
                "sentiment_score": 70,
                "trend_prediction": "看多",
                "operation_advice": "持有",
                "decision_type": "hold",
            },
            provider="gemini",
        )

        result = pipeline._agent_result_to_analysis_result(
            agent_result, "600519", "贵州茅台", ReportType.SIMPLE, "q-valid"
        )
        self.assertEqual(result.name, "贵州茅台")


# ============================================================
# Skill registration in pipeline
# ============================================================

class TestPipelineSkillRegistration(unittest.TestCase):
    """Test built-in strategies load from YAML via SkillManager."""

    def test_load_builtin_strategies(self):
        """SkillManager.load_builtin_strategies() should load all YAML strategies."""
        from src.agent.skills.base import SkillManager

        skill_manager = SkillManager()
        expected = _builtin_strategy_names()
        count = skill_manager.load_builtin_strategies()
        self.assertEqual(count, len(expected))

        skills = skill_manager.list_skills()
        self.assertEqual(len(skills), len(expected))

        names = {s.name for s in skills}
        self.assertEqual(names, expected)

        # All should be disabled by default
        active = skill_manager.list_active_skills()
        self.assertEqual(len(active), 0)

        # All should have source='builtin'
        for s in skills:
            self.assertEqual(s.source, "builtin")


# ============================================================
# Pipeline dual-path routing
# ============================================================

class TestPipelineRouting(unittest.TestCase):
    """Test that analyze_stock routes to agent mode when config.agent_mode is True."""

    def test_agent_mode_routes_to_agent(self):
        """When agent_mode=True, analyze_stock should call _analyze_with_agent."""
        with patch('src.core.pipeline.get_config') as mock_config, \
             patch('src.core.pipeline.get_db'), \
             patch('src.core.pipeline.DataFetcherManager'), \
             patch('src.core.pipeline.GeminiAnalyzer'), \
             patch('src.core.pipeline.NotificationService'), \
             patch('src.core.pipeline.SearchService'):

            mock_cfg = MagicMock()
            mock_cfg.max_workers = 2
            mock_cfg.agent_mode = True
            mock_cfg.agent_max_steps = 5
            mock_cfg.agent_skills = []
            mock_cfg.bocha_api_keys = []
            mock_cfg.tavily_api_keys = []
            mock_cfg.brave_api_keys = []
            mock_cfg.serpapi_keys = []
            mock_cfg.searxng_base_urls = []
            mock_cfg.searxng_public_instances_enabled = False
            mock_cfg.news_max_age_days = 7
            mock_cfg.enable_realtime_quote = True
            mock_cfg.enable_chip_distribution = True
            mock_cfg.realtime_source_priority = []
            mock_cfg.save_context_snapshot = False
            mock_config.return_value = mock_cfg

            from src.core.pipeline import StockAnalysisPipeline
            from src.enums import ReportType
            pipeline = StockAnalysisPipeline(config=mock_cfg)

            # Mock _analyze_with_agent to verify it gets called
            pipeline._analyze_with_agent = MagicMock(return_value=None)

            pipeline.analyze_stock("600519", ReportType.SIMPLE, "q1")

            pipeline._analyze_with_agent.assert_called_once()
            call_args = pipeline._analyze_with_agent.call_args
            # Positional args: code, report_type, query_id, stock_name, realtime_quote, chip_data, fundamental_context, trend_result
            self.assertEqual(call_args[0][0], "600519")
            self.assertEqual(call_args[0][1], ReportType.SIMPLE)
            self.assertEqual(call_args[0][2], "q1")
            # trend_result (8th arg) should be present (may be a TrendAnalysisResult or None)
            self.assertEqual(len(call_args[0]), 8)

    def test_legacy_mode_does_not_call_agent(self):
        """When agent_mode=False, analyze_stock should NOT call _analyze_with_agent."""
        with patch('src.core.pipeline.get_config') as mock_config, \
             patch('src.core.pipeline.get_db') as mock_db, \
             patch('src.core.pipeline.DataFetcherManager') as mock_fm, \
             patch('src.core.pipeline.GeminiAnalyzer') as mock_analyzer, \
             patch('src.core.pipeline.NotificationService'), \
             patch('src.core.pipeline.SearchService') as mock_search:

            mock_cfg = MagicMock()
            mock_cfg.max_workers = 2
            mock_cfg.agent_mode = False
            mock_cfg.is_agent_available.return_value = False
            mock_cfg.agent_max_steps = 10
            mock_cfg.agent_skills = []
            mock_cfg.bocha_api_keys = []
            mock_cfg.tavily_api_keys = []
            mock_cfg.brave_api_keys = []
            mock_cfg.serpapi_keys = []
            mock_cfg.searxng_base_urls = []
            mock_cfg.searxng_public_instances_enabled = False
            mock_cfg.news_max_age_days = 7
            mock_cfg.enable_realtime_quote = True
            mock_cfg.enable_chip_distribution = True
            mock_cfg.realtime_source_priority = []
            mock_cfg.save_context_snapshot = False
            mock_config.return_value = mock_cfg

            from src.core.pipeline import StockAnalysisPipeline
            from src.enums import ReportType
            pipeline = StockAnalysisPipeline(config=mock_cfg)

            # Mock the fetcher_manager to return None for realtime
            pipeline.fetcher_manager.get_realtime_quote.return_value = None
            pipeline.fetcher_manager.get_chip_distribution.return_value = None
            # Mock search service
            pipeline.search_service.is_available = False
            # Mock DB context
            pipeline.db.get_analysis_context.return_value = None
            # Mock analyzer
            pipeline.analyzer.analyze.return_value = None

            result = pipeline.analyze_stock("600519", ReportType.SIMPLE, "q1")

            # _analyze_with_agent should NOT exist as a mock (it's the real method)
            # Instead, verify analyzer.analyze was called (legacy path)
            pipeline.analyzer.analyze.assert_called_once()


class TestAnalyzeWithAgentStockName(unittest.TestCase):
    """Test stock-name handling in _analyze_with_agent."""

    def test_analyze_with_agent_uses_resolved_name_for_news_persistence(self):
        """Should use resolved stock name from dashboard for search and DB persistence."""
        with patch('src.core.pipeline.get_config') as mock_config, \
             patch('src.core.pipeline.get_db'), \
             patch('src.core.pipeline.DataFetcherManager'), \
             patch('src.core.pipeline.GeminiAnalyzer'), \
             patch('src.core.pipeline.NotificationService'), \
             patch('src.core.pipeline.SearchService'), \
             patch('src.agent.factory.build_agent_executor') as mock_build_executor:

            mock_cfg = MagicMock()
            mock_cfg.max_workers = 2
            mock_cfg.agent_mode = True
            mock_cfg.agent_max_steps = 10
            mock_cfg.agent_skills = []
            mock_cfg.bocha_api_keys = []
            mock_cfg.tavily_api_keys = []
            mock_cfg.brave_api_keys = []
            mock_cfg.serpapi_keys = []
            mock_cfg.searxng_base_urls = []
            mock_cfg.searxng_public_instances_enabled = False
            mock_cfg.news_max_age_days = 7
            mock_cfg.enable_realtime_quote = True
            mock_cfg.enable_chip_distribution = True
            mock_cfg.realtime_source_priority = []
            mock_cfg.save_context_snapshot = False
            mock_config.return_value = mock_cfg

            from src.core.pipeline import StockAnalysisPipeline
            from src.agent.executor import AgentResult
            from src.enums import ReportType
            pipeline = StockAnalysisPipeline(config=mock_cfg)

            agent_result = AgentResult(
                success=True,
                content="{}",
                dashboard={
                    "stock_name": "科创芯片ETF",
                    "sentiment_score": 78,
                    "trend_prediction": "震荡偏多",
                    "operation_advice": "持有",
                    "decision_type": "hold",
                },
                provider="gemini",
            )
            mock_executor = MagicMock()
            mock_executor.run.return_value = agent_result
            mock_build_executor.return_value = mock_executor

            news_response = MagicMock()
            news_response.success = True
            news_response.results = [{"title": "test"}]
            news_response.query = "test query"
            pipeline.search_service.is_available = True
            pipeline.search_service.search_stock_news.return_value = news_response

            result = pipeline._analyze_with_agent(
                code="588200",
                report_type=ReportType.SIMPLE,
                query_id="q-news",
                stock_name="股票588200",
                realtime_quote=None,
                chip_data=None
            )

            self.assertIsNotNone(result)
            self.assertEqual(result.name, "科创芯片ETF")
            pipeline.search_service.search_stock_news.assert_called_once_with(
                stock_code="588200",
                stock_name="科创芯片ETF",
                max_results=5
            )
            pipeline.db.save_news_intel.assert_called_once()
            saved_kwargs = pipeline.db.save_news_intel.call_args.kwargs
            self.assertEqual(saved_kwargs["name"], "科创芯片ETF")


# ============================================================
# Agent construction chain (real objects, mocked LLM)
# ============================================================

class TestAgentConstructionChain(unittest.TestCase):
    """Test that the agent construction chain wires up correctly."""

    def test_llm_adapter_accepts_config(self):
        """LLMToolAdapter should accept an optional config parameter."""
        mock_cfg = MagicMock()
        mock_cfg.gemini_api_key = ""
        mock_cfg.anthropic_api_key = ""
        mock_cfg.openai_api_key = ""
        mock_cfg.openai_base_url = ""
        mock_cfg.openai_model = ""

        from src.agent.llm_adapter import LLMToolAdapter
        adapter = LLMToolAdapter(config=mock_cfg)
        self.assertIsNotNone(adapter)

    def test_llm_adapter_no_args(self):
        """LLMToolAdapter should also work with no arguments (uses get_config)."""
        with patch('src.agent.llm_adapter.get_config') as mock_get_config:
            mock_cfg = MagicMock()
            mock_cfg.gemini_api_key = ""
            mock_cfg.anthropic_api_key = ""
            mock_cfg.openai_api_key = ""
            mock_cfg.openai_base_url = ""
            mock_cfg.openai_model = ""
            mock_get_config.return_value = mock_cfg

            from src.agent.llm_adapter import LLMToolAdapter
            adapter = LLMToolAdapter()
            self.assertIsNotNone(adapter)

    def test_full_construction_chain(self):
        """Test ToolRegistry + SkillManager + LLMToolAdapter + AgentExecutor wiring."""
        from src.agent.tools.registry import ToolRegistry, ToolDefinition, ToolParameter
        from src.agent.skills.base import SkillManager, Skill
        from src.agent.llm_adapter import LLMToolAdapter
        from src.agent.executor import AgentExecutor

        # Build registry with a dummy tool
        registry = ToolRegistry()

        def dummy_handler(x: str) -> str:
            return f"echo {x}"

        dummy_tool = ToolDefinition(
            name="dummy_echo",
            description="A test tool for echoing input.",
            category="test",
            parameters=[ToolParameter(name="x", type="string", description="input string", required=True)],
            handler=dummy_handler,
        )
        registry.register(dummy_tool)

        # Build skill manager with a fresh skill instance (avoid module singleton state)
        skill_manager = SkillManager()
        test_skill = Skill(
            name="test_skill",
            display_name="测试策略",
            description="A test skill",
            instructions="Test instructions for analysis.",
            category="trend",
            core_rules=[1, 2],
        )
        skill_manager.register(test_skill)
        skill_manager.activate(["test_skill"])
        instructions = skill_manager.get_skill_instructions()
        self.assertIn("测试策略", instructions)

        # Build LLM adapter with mocked config (no real API keys)
        mock_cfg = MagicMock()
        mock_cfg.gemini_api_key = ""
        mock_cfg.anthropic_api_key = ""
        mock_cfg.openai_api_key = ""
        mock_cfg.openai_base_url = ""
        mock_cfg.openai_model = ""
        adapter = LLMToolAdapter(config=mock_cfg)

        # Build executor
        executor = AgentExecutor(
            tool_registry=registry,
            llm_adapter=adapter,
            skill_instructions=instructions,
            max_steps=3,
        )
        self.assertEqual(executor.max_steps, 3)
        self.assertIsNotNone(executor.tool_registry)
        self.assertIsNotNone(executor.llm_adapter)

    @patch("src.agent.llm_adapter.Router")
    def test_llm_adapter_call_completion_uses_effective_agent_models_order(self, _mock_router):
        """call_completion should use Agent effective model chain in order."""
        mock_cfg = MagicMock()
        mock_cfg.agent_litellm_model = "gpt-4o-mini"
        mock_cfg.litellm_model = "gemini/gemini-2.5-flash"
        mock_cfg.litellm_fallback_models = ["openai/gpt-4o-mini", "anthropic/claude-3-5-sonnet-20241022"]
        mock_cfg.llm_model_list = []
        mock_cfg.llm_temperature = 0.7
        mock_cfg.gemini_api_keys = []
        mock_cfg.anthropic_api_keys = []
        mock_cfg.openai_api_keys = []
        mock_cfg.deepseek_api_keys = []
        mock_cfg.openai_base_url = None

        from src.agent.llm_adapter import LLMToolAdapter
        adapter = LLMToolAdapter(config=mock_cfg)

        calls = []

        def fake_call(_messages, _tools, model, **_kwargs):
            calls.append(model)
            if model == "openai/gpt-4o-mini":
                raise RuntimeError("primary failed")
            return MagicMock(content="ok")

        adapter._call_litellm_model = MagicMock(side_effect=fake_call)

        result = adapter.call_completion(messages=[{"role": "user", "content": "hi"}], tools=[])

        self.assertEqual(calls, ["openai/gpt-4o-mini", "anthropic/claude-3-5-sonnet-20241022"])
        self.assertEqual(result.content, "ok")

    @patch("src.agent.llm_adapter.Router")
    def test_llm_adapter_recomputes_timeout_for_each_fallback_attempt(self, _mock_router):
        """Each fallback model attempt should receive only the remaining timeout budget."""
        mock_cfg = MagicMock()
        mock_cfg.agent_litellm_model = "gpt-4o-mini"
        mock_cfg.litellm_model = None
        mock_cfg.litellm_fallback_models = ["anthropic/claude-3-5-sonnet-20241022"]
        mock_cfg.llm_model_list = []
        mock_cfg.llm_temperature = 0.7
        mock_cfg.gemini_api_keys = []
        mock_cfg.anthropic_api_keys = []
        mock_cfg.openai_api_keys = []
        mock_cfg.deepseek_api_keys = []
        mock_cfg.openai_base_url = None

        from src.agent.llm_adapter import LLMToolAdapter
        adapter = LLMToolAdapter(config=mock_cfg)

        timeouts = []

        def fake_call(_messages, _tools, model, **kwargs):
            timeouts.append((model, kwargs.get("timeout")))
            if model == "openai/gpt-4o-mini":
                raise RuntimeError("primary failed")
            return MagicMock(content="ok")

        adapter._call_litellm_model = MagicMock(side_effect=fake_call)

        with patch("src.agent.llm_adapter.time.time", side_effect=[0.0, 0.0, 7.0, 7.0]):
            result = adapter.call_completion(
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
                timeout=10.0,
            )

        self.assertEqual(result.content, "ok")
        self.assertEqual(timeouts[0], ("openai/gpt-4o-mini", 10.0))
        self.assertEqual(timeouts[1], ("anthropic/claude-3-5-sonnet-20241022", 3.0))


# ============================================================
# _safe_int tests
# ============================================================

class TestSafeInt(unittest.TestCase):
    """Test the _safe_int helper for robust sentiment_score parsing."""

    def _get_safe_int(self):
        """Get reference to StockAnalysisPipeline._safe_int static method."""
        with patch('src.core.pipeline.get_config') as mock_config, \
             patch('src.core.pipeline.get_db'), \
             patch('src.core.pipeline.DataFetcherManager'), \
             patch('src.core.pipeline.GeminiAnalyzer'), \
             patch('src.core.pipeline.NotificationService'), \
             patch('src.core.pipeline.SearchService'):

            mock_cfg = MagicMock()
            mock_cfg.max_workers = 2
            mock_cfg.agent_mode = False
            mock_cfg.agent_max_steps = 10
            mock_cfg.agent_skills = []
            mock_cfg.bocha_api_keys = []
            mock_cfg.tavily_api_keys = []
            mock_cfg.brave_api_keys = []
            mock_cfg.serpapi_keys = []
            mock_cfg.searxng_base_urls = []
            mock_cfg.searxng_public_instances_enabled = False
            mock_cfg.news_max_age_days = 7
            mock_cfg.enable_realtime_quote = True
            mock_cfg.enable_chip_distribution = True
            mock_cfg.realtime_source_priority = []
            mock_cfg.save_context_snapshot = False
            mock_config.return_value = mock_cfg

            from src.core.pipeline import StockAnalysisPipeline
            return StockAnalysisPipeline._safe_int

    def test_int_passthrough(self):
        safe_int = self._get_safe_int()
        self.assertEqual(safe_int(80), 80)

    def test_float_truncate(self):
        safe_int = self._get_safe_int()
        self.assertEqual(safe_int(75.6), 75)

    def test_string_numeric(self):
        safe_int = self._get_safe_int()
        self.assertEqual(safe_int("80"), 80)

    def test_string_with_unit(self):
        """LLM may return '80分' instead of 80."""
        safe_int = self._get_safe_int()
        self.assertEqual(safe_int("80分"), 80)

    def test_string_with_percent(self):
        safe_int = self._get_safe_int()
        self.assertEqual(safe_int("75%"), 75)

    def test_none_default(self):
        safe_int = self._get_safe_int()
        self.assertEqual(safe_int(None), 50)
        self.assertEqual(safe_int(None, 60), 60)

    def test_empty_string(self):
        safe_int = self._get_safe_int()
        self.assertEqual(safe_int(""), 50)

    def test_non_numeric_string(self):
        safe_int = self._get_safe_int()
        self.assertEqual(safe_int("high"), 50)

    def test_negative(self):
        safe_int = self._get_safe_int()
        self.assertEqual(safe_int("-10"), -10)


# ============================================================
# Skill activation semantics
# ============================================================

class TestSkillActivation(unittest.TestCase):
    """Test that skill activation follows the correct semantics."""

    def test_skills_default_disabled(self):
        """After registration, skills should be disabled by default."""
        from src.agent.skills.base import SkillManager, Skill

        manager = SkillManager()
        # Create a fresh Skill with default enabled=False
        test_skill = Skill(
            name="test_disabled",
            display_name="Test",
            description="test",
            instructions="test",
        )
        manager.register(test_skill)
        active = manager.list_active_skills()
        self.assertEqual(len(active), 0, "Skills should be disabled by default")

    def test_activate_all(self):
        """activate(['all']) should enable all registered skills."""
        from src.agent.skills.base import SkillManager, Skill

        manager = SkillManager()
        # Create test skills instead of importing deleted Python modules
        skill1 = Skill(name="dragon_head", display_name="龙头策略",
                       description="test", instructions="test")
        skill2 = Skill(name="shrink_pullback", display_name="缩量回踩",
                       description="test", instructions="test")
        manager.register(skill1)
        manager.register(skill2)
        manager.activate(["all"])
        active = manager.list_active_skills()
        self.assertEqual(len(active), 2)

    def test_activate_specific(self):
        """activate with specific names should only enable those."""
        from src.agent.skills.base import SkillManager, Skill

        manager = SkillManager()
        skill1 = Skill(name="dragon_head", display_name="龙头策略",
                       description="test", instructions="test")
        skill2 = Skill(name="shrink_pullback", display_name="缩量回踩",
                       description="test", instructions="test")
        skill3 = Skill(name="volume_breakout", display_name="放量突破",
                       description="test", instructions="test")
        manager.register(skill1)
        manager.register(skill2)
        manager.register(skill3)
        manager.activate(["dragon_head"])
        active = manager.list_active_skills()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].name, "dragon_head")

    def test_empty_config_uses_primary_default_skill(self):
        """Empty agent_skills config should activate the primary default skill only."""
        from src.agent.skills.base import SkillManager
        from src.agent.skills.defaults import get_default_active_skill_ids

        skill_manager = SkillManager()
        count = skill_manager.load_builtin_strategies()
        self.assertEqual(count, len(_builtin_strategy_names()), "Should load all built-in strategies from YAML")

        default_ids = get_default_active_skill_ids(skill_manager.list_skills())
        self.assertEqual(default_ids, ["bull_trend"])
        skill_manager.activate(default_ids)

        active = skill_manager.list_active_skills()
        self.assertEqual([skill.name for skill in active], ["bull_trend"])

    def test_sentiment_score_parsed_from_dashboard(self):
        """Verify _agent_result_to_analysis_result handles non-numeric sentiment_score."""
        with patch('src.core.pipeline.get_config') as mock_config, \
             patch('src.core.pipeline.get_db'), \
             patch('src.core.pipeline.DataFetcherManager'), \
             patch('src.core.pipeline.GeminiAnalyzer'), \
             patch('src.core.pipeline.NotificationService'), \
             patch('src.core.pipeline.SearchService'):

            mock_cfg = MagicMock()
            mock_cfg.max_workers = 2
            mock_cfg.agent_mode = True
            mock_cfg.agent_max_steps = 10
            mock_cfg.agent_skills = []
            mock_cfg.bocha_api_keys = []
            mock_cfg.tavily_api_keys = []
            mock_cfg.brave_api_keys = []
            mock_cfg.serpapi_keys = []
            mock_cfg.searxng_base_urls = []
            mock_cfg.searxng_public_instances_enabled = False
            mock_cfg.news_max_age_days = 7
            mock_cfg.enable_realtime_quote = True
            mock_cfg.enable_chip_distribution = True
            mock_cfg.realtime_source_priority = []
            mock_cfg.save_context_snapshot = False
            mock_config.return_value = mock_cfg

            from src.core.pipeline import StockAnalysisPipeline
            from src.agent.executor import AgentResult
            from src.enums import ReportType
            pipeline = StockAnalysisPipeline(config=mock_cfg)

            # Dashboard with "80分" instead of 80
            agent_result = AgentResult(
                success=True,
                content="{}",
                dashboard={
                    "stock_name": "TestCo",
                    "sentiment_score": "80分",
                    "trend_prediction": "看多",
                    "operation_advice": "买入",
                    "decision_type": "buy",
                },
                provider="gemini",
            )

            result = pipeline._agent_result_to_analysis_result(
                agent_result, "600519", "TestCo", ReportType.SIMPLE, "q1"
            )
            self.assertEqual(result.sentiment_score, 80)


if __name__ == '__main__':
    unittest.main()
