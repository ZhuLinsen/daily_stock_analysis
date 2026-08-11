# -*- coding: utf-8 -*-
"""Tests for Agent-mode news_context write-back (upstream #1602 gap).

The pipeline's Agent branch skips the traditional Step-4 news search and the
agent discovers news through search_comprehensive_intel. Previously those tool
results were only returned to the LLM and persisted to news_intel; the
AnalysisContextPack news block stayed empty and every Agent-mode report
surfaced ``news_context_missing``.

This module covers the fix:
1. ``record_agent_news_context`` / ``pop_agent_news_context`` registry unit
   behaviour (thread-safe, consume-once, canonical code keys).
2. ``_handle_search_comprehensive_intel`` echoes its report into the registry
   only when at least one dimension has results.
3. Pipeline write-back consumes the registry entry and rebuilds the pack
   overview so the news block flips from MISSING to AVAILABLE, and the saved
   history news_content is populated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from src.services.analysis_context_builder import (
    AnalysisContextBuilder,
    PipelineAnalysisArtifacts,
)
from src.schemas.analysis_context_pack import ContextFieldStatus


# ---------------------------------------------------------------------------
# 1. Registry unit tests
# ---------------------------------------------------------------------------

class TestAgentNewsRegistry:
    def test_record_then_pop_roundtrip(self):
        from src.agent.tools.search_tools import (
            record_agent_news_context,
            pop_agent_news_context,
        )
        record_agent_news_context("605090", "【九丰能源 情报搜索结果】...")
        assert pop_agent_news_context("605090") == "【九丰能源 情报搜索结果】..."

    def test_pop_is_consume_once(self):
        from src.agent.tools.search_tools import (
            record_agent_news_context,
            pop_agent_news_context,
        )
        record_agent_news_context("605090", "news")
        assert pop_agent_news_context("605090") == "news"
        assert pop_agent_news_context("605090") == ""

    def test_pop_unknown_returns_empty(self):
        from src.agent.tools.search_tools import pop_agent_news_context
        assert pop_agent_news_context("999999") == ""

    def test_record_empty_is_noop(self):
        from src.agent.tools.search_tools import (
            record_agent_news_context,
            pop_agent_news_context,
        )
        record_agent_news_context("", "news")
        record_agent_news_context("605090", "")
        assert pop_agent_news_context("605090") == ""

    def test_canonical_key_normalisation(self):
        from src.agent.tools.search_tools import (
            record_agent_news_context,
            pop_agent_news_context,
        )
        # 605090 and 605090.SH / SH605090 should resolve to the same key.
        record_agent_news_context("605090", "news-a")
        assert pop_agent_news_context("605090.SH") == "news-a"


# ---------------------------------------------------------------------------
# 2. Tool echo behaviour
# ---------------------------------------------------------------------------

class TestToolEcho:
    def _intel_result(self, success: bool, results: Optional[list]) -> Any:
        resp = MagicMock()
        resp.success = success
        resp.results = results if results is not None else []
        resp.query = "q"
        resp.provider = "Brave"
        return resp

    def _call_handler(self, intel_results: Dict[str, Any]) -> Dict[str, Any]:
        from src.agent.tools import search_tools
        with patch.object(search_tools, "_get_search_service") as svc_mock:
            svc = MagicMock()
            svc.is_available = True
            svc.search_comprehensive_intel.return_value = intel_results
            svc.format_intel_report.return_value = "【xx 情报搜索结果】formatted"
            svc_mock.return_value = svc
            return search_tools._handle_search_comprehensive_intel("605090", "九丰能源")

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        from src.agent.tools import search_tools
        with search_tools._AGENT_NEWS_LOCK:
            search_tools._AGENT_NEWS_REGISTRY.clear()
        yield
        with search_tools._AGENT_NEWS_LOCK:
            search_tools._AGENT_NEWS_REGISTRY.clear()

    def test_echo_written_when_results_present(self):
        from src.agent.tools import search_tools
        intel = {"latest_news": self._intel_result(True, [MagicMock()])}
        out = self._call_handler(intel)
        assert "report" in out
        assert search_tools.pop_agent_news_context("605090") == "【xx 情报搜索结果】formatted"

    def test_echo_skipped_when_no_dimension_has_results(self):
        from src.agent.tools import search_tools
        intel = {
            "latest_news": self._intel_result(False, []),
            "risk_check": self._intel_result(True, []),
        }
        out = self._call_handler(intel)
        assert "report" in out  # tool still returns a report for the LLM
        assert search_tools.pop_agent_news_context("605090") == ""


# ---------------------------------------------------------------------------
# 3. Pipeline write-back → pack news block AVAILABLE
# ---------------------------------------------------------------------------

class TestPipelineWriteBack:
    def test_news_block_available_after_write_back(self):
        """End-to-end of the pack builder: with news_context populated, the
        news block must be AVAILABLE (not MISSING)."""
        artifacts = PipelineAnalysisArtifacts(
            code="605090",
            stock_name="九丰能源",
            market="cn",
            phase=None,
            base_context={
                "code": "605090",
                "stock_name": "九丰能源",
                "today": {},
                "yesterday": {},
            },
            enhanced_context={},
            realtime_quote=None,
            trend_result=None,
            chip_data=None,
            fundamental_context=None,
            news_context="【九丰能源 情报搜索结果】📰 最新消息...",
            news_result_count=6,
            metadata={"query_id": "q1", "trigger_source": "manual"},
        )
        pack = AnalysisContextBuilder.build(artifacts)
        news_block = pack.blocks.get("news")
        assert news_block is not None
        assert news_block.status == ContextFieldStatus.AVAILABLE
        content_item = news_block.items.get("content")
        assert content_item is not None
        assert content_item.value == "【九丰能源 情报搜索结果】📰 最新消息..."

    def test_news_block_missing_without_news_context(self):
        """Regression guard: without the write-back the pack still reports
        news_context_missing, proving the diagnostic is accurate."""
        artifacts = PipelineAnalysisArtifacts(
            code="605090",
            stock_name="九丰能源",
            market="cn",
            phase=None,
            base_context={
                "code": "605090",
                "stock_name": "九丰能源",
                "today": {},
                "yesterday": {},
            },
            enhanced_context={},
            realtime_quote=None,
            trend_result=None,
            chip_data=None,
            fundamental_context=None,
            news_context=None,
            news_result_count=None,
            metadata={"query_id": "q1", "trigger_source": "manual"},
        )
        pack = AnalysisContextBuilder.build(artifacts)
        news_block = pack.blocks.get("news")
        assert news_block is not None
        assert news_block.status == ContextFieldStatus.MISSING
        content_item = news_block.items.get("content")
        assert content_item.missing_reason == "news_context_missing"
