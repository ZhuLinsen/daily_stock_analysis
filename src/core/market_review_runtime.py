"""Reusable market review runtime assembly helpers.

Centralize the analyzer/search/notification construction so API, CLI and Bot
entrypoints share one initialization path for 大盘复盘.
"""

from __future__ import annotations

import logging
from inspect import getattr_static
from typing import Any, Optional, Tuple

from src.config import Config
from src.llm.backend_registry import (
    CODEX_CLI_BACKEND_ID,
    resolve_generation_backend_id,
    resolve_generation_fallback_backend_id,
)
from src.llm.generation_backend import GenerationError

logger = logging.getLogger(__name__)


def has_configured_llm_runtime(config: Config) -> bool:
    """Return whether any LLM model configuration is available."""
    try:
        if resolve_generation_backend_id(config) == CODEX_CLI_BACKEND_ID:
            return True
    except GenerationError:
        pass

    if (getattr(config, "litellm_model", "") or "").strip():
        return True
    if getattr(config, "llm_model_list", None):
        return True

    for field in (
        "gemini_api_key",
        "gemini_api_keys",
        "anthropic_api_key",
        "anthropic_api_keys",
        "deepseek_api_key",
        "deepseek_api_keys",
        "openai_api_key",
        "openai_api_keys",
    ):
        value = getattr(config, field, None)
        if isinstance(value, str):
            if value.strip():
                return True
        elif value:
            return True

    return False


def _get_analyzer_generation_backend_config_error(analyzer: Any) -> Optional[GenerationError]:
    """Return backend config errors without treating dynamic mock attrs as real methods."""
    missing = object()
    if getattr_static(analyzer, "get_generation_backend_config_error", missing) is missing:
        return None
    method = getattr(analyzer, "get_generation_backend_config_error", None)
    if not callable(method):
        return None
    error = method()
    return error if isinstance(error, GenerationError) else None


def _get_config_generation_backend_error(config: Config) -> Optional[GenerationError]:
    """Return generation backend config errors before analyzer construction."""
    try:
        resolve_generation_backend_id(config)
        resolve_generation_fallback_backend_id(config)
    except GenerationError as exc:
        return exc
    return None


def build_market_review_runtime(
    config: Config,
    source_message: Optional[Any] = None,
) -> Tuple[Any, Any, Any]:
    """
    Build shared NotificationService, GeminiAnalyzer and SearchService instances.
    """
    from src.analyzer import GeminiAnalyzer
    from src.notification import NotificationService
    from src.search_service import SearchService

    notifier = NotificationService(source_message=source_message)

    search_service = None
    has_search_capability = getattr(config, "has_search_capability_enabled", None)
    if callable(has_search_capability) and has_search_capability():
        search_service = SearchService(
            bocha_keys=getattr(config, "bocha_api_keys", None),
            tavily_keys=getattr(config, "tavily_api_keys", None),
            anspire_keys=getattr(config, "anspire_api_keys", None),
            brave_keys=getattr(config, "brave_api_keys", None),
            serpapi_keys=getattr(config, "serpapi_keys", None),
            minimax_keys=getattr(config, "minimax_api_keys", None),
            searxng_base_urls=getattr(config, "searxng_base_urls", None),
            searxng_public_instances_enabled=getattr(
                config,
                "searxng_public_instances_enabled",
                True,
            ),
            news_max_age_days=getattr(config, "news_max_age_days", 3),
            news_strategy_profile=getattr(config, "news_strategy_profile", "short"),
        )

    analyzer = None
    if has_configured_llm_runtime(config):
        analyzer = GeminiAnalyzer(config=config)
        backend_error = _get_analyzer_generation_backend_config_error(analyzer)
        if backend_error is not None:
            logger.error("AI 分析器生成后端配置错误: %s", backend_error)
        elif not analyzer.is_available():
            logger.warning("AI 分析器初始化后不可用，请检查 LLM 配置")
            analyzer = None
    else:
        backend_error = _get_config_generation_backend_error(config)
        if backend_error is not None:
            logger.error("AI 分析器生成后端配置错误: %s", backend_error)
        else:
            logger.warning("未检测到 LLM 模型配置，将仅使用模板生成报告")

    return notifier, analyzer, search_service
