# -*- coding: utf-8 -*-
"""Compatibility assertions for market review runtime assembly."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.core.market_review_runtime import build_market_review_runtime, has_configured_llm_runtime


class TestMarketReviewRuntimeCompatibility(unittest.TestCase):
    @staticmethod
    def _base_config() -> SimpleNamespace:
        return SimpleNamespace(
            litellm_model="",
            llm_model_list=[],
            gemini_api_key=None,
            gemini_api_keys=[],
            openai_api_key=None,
            openai_api_keys=[],
            anthropic_api_key=None,
            anthropic_api_keys=[],
            deepseek_api_key=None,
            deepseek_api_keys=[],
            bocha_api_keys=None,
            tavily_api_keys=None,
            anspire_api_keys=None,
            brave_api_keys=None,
            serpapi_api_keys=None,
            minimax_api_keys=None,
            searxng_base_urls=None,
            searxng_public_instances_enabled=True,
            news_max_age_days=3,
            news_strategy_profile="short",
            has_search_capability_enabled=lambda: False,
        )

    def test_build_market_review_runtime_includes_legacy_provider_configs(self) -> None:
        config = self._base_config()
        config.openai_api_key = "openai-key"
        notifier = MagicMock()
        analyzer = MagicMock()
        analyzer.is_available.return_value = True

        with patch("src.analyzer.GeminiAnalyzer", return_value=analyzer) as analyzer_cls, \
             patch("src.notification.NotificationService", return_value=notifier) as notifier_cls, \
             patch("src.search_service.SearchService") as search_cls:
            runtime_notifier, runtime_analyzer, runtime_search = build_market_review_runtime(config)

        notifier_cls.assert_called_once_with(source_message=None)
        analyzer_cls.assert_called_once_with(config=config)
        search_cls.assert_not_called()
        self.assertIs(runtime_notifier, notifier)
        self.assertIs(runtime_analyzer, analyzer)
        self.assertIsNone(runtime_search)

    def test_build_market_review_runtime_supports_litellm_channel_model_list(self) -> None:
        config = self._base_config()
        config.litellm_model = ""
        config.llm_model_list = [
            {
                "model_name": "openai/gpt-5.5",
                "litellm_params": {
                    "api_key": "openai-channel-key",
                    "model": "openai/gpt-5.5",
                    "api_base": "https://api.openrouter.ai/v1",
                },
            }
        ]
        notifier = MagicMock()
        analyzer = MagicMock()
        analyzer.is_available.return_value = True

        with patch("src.analyzer.GeminiAnalyzer", return_value=analyzer) as analyzer_cls, \
             patch("src.notification.NotificationService", return_value=notifier) as notifier_cls, \
             patch("src.search_service.SearchService") as search_cls:
            runtime_notifier, runtime_analyzer, runtime_search = build_market_review_runtime(config)

        notifier_cls.assert_called_once_with(source_message=None)
        analyzer_cls.assert_called_once_with(config=config)
        search_cls.assert_not_called()
        self.assertIs(runtime_notifier, notifier)
        self.assertIs(runtime_analyzer, analyzer)
        self.assertIsNone(runtime_search)

    def test_build_market_review_runtime_supports_explicit_litellm_model_only(self) -> None:
        config = self._base_config()
        config.litellm_model = "openai/gpt-5.5"

        notifier = MagicMock()
        analyzer = MagicMock()
        analyzer.is_available.return_value = True

        with patch("src.analyzer.GeminiAnalyzer", return_value=analyzer) as analyzer_cls, \
             patch("src.notification.NotificationService", return_value=notifier) as notifier_cls, \
             patch("src.search_service.SearchService") as search_cls:
            runtime_notifier, runtime_analyzer, runtime_search = build_market_review_runtime(config)

        notifier_cls.assert_called_once_with(source_message=None)
        analyzer_cls.assert_called_once_with(config=config)
        search_cls.assert_not_called()
        self.assertIs(runtime_notifier, notifier)
        self.assertIs(runtime_analyzer, analyzer)
        self.assertIsNone(runtime_search)

    def test_has_configured_llm_runtime_returns_false_without_any_model_source(self) -> None:
        config = self._base_config()
        self.assertFalse(has_configured_llm_runtime(config))

    def test_has_configured_llm_runtime_supports_legacy_fields(self) -> None:
        base = self._base_config()
        test_configs = [
            ("openai_api_key", {"openai_api_key": "openai-key"}),
            ("openai_api_keys", {"openai_api_keys": ["openai-key"]}),
            ("anthropic_api_key", {"anthropic_api_key": "anthropic-key"}),
            ("anthropic_api_keys", {"anthropic_api_keys": ["anthropic-key"]}),
            ("deepseek_api_key", {"deepseek_api_key": "deepseek-key"}),
            ("deepseek_api_keys", {"deepseek_api_keys": ["deepseek-key"]}),
            ("gemini_api_key", {"gemini_api_key": "gemini-key"}),
            ("gemini_api_keys", {"gemini_api_keys": ["gemini-key"]}),
            ("litellm_model", {"litellm_model": "claude-3-5-sonnet"}),
            ("llm_model_list", {"llm_model_list": [{"model_name": "openai/gpt-4.1", "litellm_params": {"model": "openai/gpt-4.1"}}]}),
        ]

        for key, updates in test_configs:
            with self.subTest(field=key):
                config = SimpleNamespace(**vars(base))
                setattr(config, key, updates[key])
                config.openai_api_key = updates.get("openai_api_key", base.openai_api_key)
                config.openai_api_keys = updates.get("openai_api_keys", base.openai_api_keys)
                config.anthropic_api_key = updates.get("anthropic_api_key", base.anthropic_api_key)
                config.anthropic_api_keys = updates.get("anthropic_api_keys", base.anthropic_api_keys)
                config.deepseek_api_key = updates.get("deepseek_api_key", base.deepseek_api_key)
                config.deepseek_api_keys = updates.get("deepseek_api_keys", base.deepseek_api_keys)
                config.gemini_api_key = updates.get("gemini_api_key", base.gemini_api_key)
                config.gemini_api_keys = updates.get("gemini_api_keys", base.gemini_api_keys)
                config.litellm_model = updates.get("litellm_model", base.litellm_model)
                config.llm_model_list = updates.get("llm_model_list", base.llm_model_list)
                self.assertTrue(has_configured_llm_runtime(config))
