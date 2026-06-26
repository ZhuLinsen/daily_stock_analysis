# -*- coding: utf-8 -*-
"""Tests for Analyzer.generate_text() and the market_analyzer bypass fix.

Covers:
- generate_text() returns the LLM response on success
- generate_text() returns None and logs on ordinary failures
- generation backend configuration errors propagate explicitly
- market_analyzer calls generate_text(), not private analyzer attributes
- Any provider configuration (Gemini / Anthropic / OpenAI / LLM_CHANNELS)
  does NOT trigger AttributeError (regression guard for the old bypass bug)
"""
import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Stub heavy dependencies before project imports
for _mod in ("litellm", "google.generativeai", "google.genai", "anthropic"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest
from unittest.mock import PropertyMock


@pytest.fixture(autouse=True)
def _llm_usage_hmac_env(monkeypatch):
    monkeypatch.setenv("LLM_USAGE_HMAC_SECRET", "test-usage-hmac-secret")
    monkeypatch.setenv("LLM_USAGE_HMAC_KEY_VERSION", "test-v1")


def _assert_usage_contains(usage, expected):
    for key, value in expected.items():
        assert usage[key] == value
    assert usage["normalized_prompt_tokens"] == expected.get("prompt_tokens")
    assert usage["normalized_completion_tokens"] == expected.get("completion_tokens")
    assert usage["normalized_total_tokens"] == expected.get("total_tokens")
    assert usage["provider_usage_json"]
    assert usage["messages_hmac"] and len(usage["messages_hmac"]) == 64
    assert usage["hmac_key_version"] == "test-v1"


def _assert_no_provider_usage_hmac_only(usage):
    assert "prompt_tokens" not in usage
    assert usage["messages_hmac"] and len(usage["messages_hmac"]) == 64
    assert usage["hmac_key_version"] == "test-v1"


_OPENAI_COMPATIBILITY_PAYLOAD_FIXTURES = [
    # Repro case 1 (Issue #1279): OpenAI-compatible provider message.content is None while text is in content_blocks.
    (
        "openai/cpa-compatible",
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "content_blocks": [
                            {"type": "text", "text": "block "},
                            {"type": "text", "text": "response"},
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        },
        "block response",
    ),
    # Repro case 2: OpenAI-compatible provider returns message.content as list-of-blocks.
    (
        "openai/list-content-provider",
        {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "list "},
                            {"type": "text", "text": "response"},
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        },
        "list response",
    ),
]


# ---------------------------------------------------------------------------
# Analyzer.generate_text()
# ---------------------------------------------------------------------------

class TestAnalyzerGenerateText:
    def _make_analyzer(self):
        """Return a minimally configured GeminiAnalyzer with _call_litellm mocked."""
        with patch("src.analyzer.get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.litellm_model = "gemini/gemini-2.0-flash"
            cfg.litellm_fallback_models = []
            cfg.gemini_api_keys = ["sk-gemini-testkey-1234"]
            cfg.anthropic_api_keys = []
            cfg.openai_api_keys = []
            cfg.deepseek_api_keys = []
            cfg.llm_model_list = []
            cfg.openai_base_url = None
            cfg.generation_backend = "litellm"
            cfg.generation_fallback_backend = "litellm"
            mock_cfg.return_value = cfg
            from src.analyzer import GeminiAnalyzer
            analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
            analyzer._router = None
            analyzer._litellm_available = True
            analyzer._config_override = cfg
            return analyzer

    def test_legacy_market_group_normalizes_supported_markets(self):
        from src.analyzer import _legacy_market_group

        assert _legacy_market_group("") == "unknown"
        assert _legacy_market_group("unknown") == "unknown"
        assert _legacy_market_group("600519") == "cn"
        assert _legacy_market_group("hk00700") == "hk"
        assert _legacy_market_group("AAPL") == "us"

    def test_legacy_audit_marker_specs_use_language_and_optional_context(self):
        from src.analyzer import _legacy_audit_marker_specs

        zh_markers = _legacy_audit_marker_specs(
            {"date": "2026-06-19"},
            code="600519",
            stock_name="贵州茅台",
            report_language="zh",
            news_context="news",
            analysis_context_pack_summary="pack summary",
        )
        zh_by_name = {marker["marker_name"]: marker for marker in zh_markers}

        assert zh_by_name["stock_code"]["text"] == "600519"
        assert zh_by_name["stock_name"]["text"] == "贵州茅台"
        assert zh_by_name["analysis_date"]["text"] == "2026-06-19"
        assert zh_by_name["market_phase"]["text"] == "## 市场阶段上下文"
        assert zh_by_name["daily_market_context"]["text"] == "## 大盘环境摘要"
        assert zh_by_name["analysis_context_pack"]["text"] == "pack summary"
        assert zh_by_name["quote"]["text"] == "## 📈 技术面数据"
        assert zh_by_name["news_context"]["text"] == "## 📰 舆情情报"
        assert {marker["message_role"] for marker in zh_markers} == {"user"}

        en_markers = _legacy_audit_marker_specs(
            {"date": ""},
            code="AAPL",
            stock_name="Apple",
            report_language="en",
            news_context=None,
            analysis_context_pack_summary=None,
        )
        en_by_name = {marker["marker_name"]: marker for marker in en_markers}

        assert en_by_name["market_phase"]["text"] == "## Market Phase Context"
        assert en_by_name["daily_market_context"]["text"] == "## Daily Market Context"
        assert "analysis_date" not in en_by_name
        assert "analysis_context_pack" not in en_by_name
        assert "news_context" not in en_by_name

    def test_generate_text_returns_llm_response(self):
        analyzer = self._make_analyzer()
        with patch.object(analyzer, "_call_litellm", return_value="市场分析报告") as mock_call:
            result = analyzer.generate_text("写一份复盘", max_tokens=1024, temperature=0.5)
            assert result == "市场分析报告"
            mock_call.assert_called_once_with(
                "写一份复盘",
                generation_config={"max_tokens": 1024, "temperature": 0.5},
            )

    def test_generate_text_does_not_persist_unavailable_usage(self):
        analyzer = self._make_analyzer()
        usage = {
            "usage_available": False,
            "usage_source": "unavailable",
            "backend": "codex_cli",
        }
        with patch.object(analyzer, "_call_litellm", return_value=("复盘", "codex_cli", usage)), \
             patch("src.analyzer.persist_llm_usage") as mock_persist:
            result = analyzer.generate_text("写一份复盘")

        assert result == "复盘"
        mock_persist.assert_not_called()

    def test_codex_cli_is_available_without_litellm_api_keys(self):
        analyzer = self._make_analyzer()
        analyzer._litellm_available = False
        analyzer._router = None
        analyzer._config_override = SimpleNamespace(
            generation_backend="codex_cli",
            generation_fallback_backend="",
            generation_backend_timeout_seconds=300,
            generation_backend_max_output_bytes=1048576,
            generation_backend_max_concurrency=1,
            local_cli_backend_max_concurrency=1,
        )

        with patch("src.llm.local_cli_backend.shutil.which", return_value="/usr/bin/codex"), \
             patch("src.llm.local_cli_backend.os.access", return_value=True):
            assert analyzer.get_generation_backend_config_error() is None
            assert analyzer.is_available() is True

    def test_analyze_uses_litellm_fallback_when_codex_cli_config_error_is_fallbackable(self):
        from src.llm.generation_backend import GenerationBackend, GenerationError, GenerationErrorCode
        from src.llm.local_cli_backend import LocalCliGenerationBackend

        analyzer = self._make_analyzer()
        analyzer._litellm_available = True
        analyzer._config_override = SimpleNamespace(
            generation_backend="codex_cli",
            generation_fallback_backend="litellm",
            litellm_model="gemini/gemini-2.0-flash",
            litellm_fallback_models=[],
            llm_model_list=[],
            report_language="zh",
            gemini_request_delay=0,
            llm_temperature=0.7,
            report_integrity_enabled=False,
            report_integrity_retry=0,
        )
        codex_error = GenerationError(
            error_code=GenerationErrorCode.COMMAND_NOT_FOUND,
            stage="configuration",
            retryable=False,
            fallbackable=True,
            backend="codex_cli",
            provider="codex_cli",
            details={"reason": "executable_not_found"},
        )
        primary_backend = MagicMock(spec=LocalCliGenerationBackend)
        primary_backend.get_config_error.return_value = codex_error
        primary_backend.generate.side_effect = codex_error
        fallback_backend = MagicMock(spec=GenerationBackend)
        fallback_backend.generate.return_value = SimpleNamespace(
            text=json.dumps({
                "sentiment_score": 70,
                "trend_prediction": "看多",
                "operation_advice": "持有",
                "analysis_summary": "fallback ok",
            }),
            model="gemini/gemini-2.0-flash",
            usage={
                "usage_available": False,
                "usage_source": "unavailable",
                "backend": "litellm",
            },
        )

        def _backend_for(backend_id=None):
            return primary_backend if backend_id == "codex_cli" else fallback_backend

        with patch.object(analyzer, "_get_generation_backend", side_effect=_backend_for), \
             patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
             patch.object(analyzer, "_get_skill_prompt_sections", return_value=(None, None, True)), \
             patch.object(analyzer, "_format_prompt", return_value="prompt"), \
             patch.object(analyzer, "_build_market_snapshot", return_value={}):
            assert analyzer.is_available() is True
            result = analyzer.analyze({"code": "600519", "stock_name": "贵州茅台"})

        assert result.success is True
        assert result.analysis_summary == "fallback ok"
        primary_backend.generate.assert_called()
        fallback_backend.generate.assert_called()

    def test_analyze_preserves_litellm_text_fallback_after_codex_cli_primary_failure(self):
        from src.analyzer import AnalysisResult, _AllModelsFailedError
        from src.llm.generation_backend import GenerationBackend, GenerationError, GenerationErrorCode

        analyzer = self._make_analyzer()
        analyzer._litellm_available = True
        analyzer._config_override = SimpleNamespace(
            generation_backend="codex_cli",
            generation_fallback_backend="litellm",
            litellm_model="provider/primary-model",
            litellm_fallback_models=["provider/fallback-model"],
            llm_model_list=[],
            report_language="zh",
            gemini_request_delay=0,
            llm_temperature=0.7,
            report_integrity_enabled=False,
            report_integrity_retry=0,
        )
        primary_error = GenerationError(
            error_code=GenerationErrorCode.COMMAND_NOT_FOUND,
            stage="configuration",
            retryable=False,
            fallbackable=True,
            backend="codex_cli",
            provider="codex_cli",
            details={"reason": "executable_not_found"},
        )
        all_models_error = _AllModelsFailedError(
            "all fallback models returned invalid JSON",
            last_response_text="这不是 JSON，而是 fallback 模型返回的纯文本分析",
            last_model="provider/fallback-model",
            last_usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )
        text_fallback_result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="持有",
            analysis_summary="纯文本兜底摘要",
            success=False,
            error_message="LLM response is not valid JSON; analysis result will not be persisted",
        )
        primary_backend = MagicMock(spec=GenerationBackend)
        primary_backend.generate.side_effect = primary_error
        fallback_backend = MagicMock(spec=GenerationBackend)
        fallback_backend.generate.side_effect = all_models_error

        def _backend_for(backend_id):
            return primary_backend if backend_id == "codex_cli" else fallback_backend

        with patch.object(analyzer, "get_generation_backend_config_error", return_value=None), \
             patch.object(analyzer, "is_available", return_value=True), \
             patch.object(analyzer, "_get_generation_backend", side_effect=_backend_for), \
             patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
             patch.object(analyzer, "_get_skill_prompt_sections", return_value=(None, None, True)), \
             patch.object(analyzer, "_format_prompt", return_value="prompt"), \
             patch.object(analyzer, "_parse_response", return_value=text_fallback_result) as mock_parse, \
             patch.object(analyzer, "_build_market_snapshot", return_value={}), \
             patch("src.analyzer.persist_llm_usage") as mock_persist:
            result = analyzer.analyze({"code": "600519", "stock_name": "贵州茅台"})

        assert result.analysis_summary == "纯文本兜底摘要"
        assert result.raw_response == "这不是 JSON，而是 fallback 模型返回的纯文本分析"
        assert result.model_used == "provider/fallback-model"
        mock_parse.assert_called_once_with(
            "这不是 JSON，而是 fallback 模型返回的纯文本分析",
            "600519",
            "贵州茅台",
        )
        mock_persist.assert_called_once_with(
            {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "provider/fallback-model",
            call_type="analysis",
            stock_code="600519",
        )
        primary_backend.generate.assert_called_once()
        fallback_backend.generate.assert_called_once()

    def test_analyze_does_not_persist_unavailable_usage(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            generation_backend="codex_cli",
            generation_fallback_backend="",
            generation_backend_timeout_seconds=300,
            generation_backend_max_output_bytes=1048576,
            generation_backend_max_concurrency=1,
            local_cli_backend_max_concurrency=1,
            litellm_model="",
            gemini_request_delay=0,
            report_language="zh",
            llm_temperature=0.7,
            report_integrity_enabled=False,
            report_integrity_retry=0,
        )
        response_text = json.dumps({
            "sentiment_score": 70,
            "trend_prediction": "看多",
            "operation_advice": "持有",
            "analysis_summary": "测试",
        })
        usage = {
            "usage_available": False,
            "usage_source": "unavailable",
            "backend": "codex_cli",
        }

        with patch.object(analyzer, "get_generation_backend_config_error", return_value=None), \
             patch.object(analyzer, "is_available", return_value=True), \
             patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
             patch.object(analyzer, "_get_skill_prompt_sections", return_value=(None, None, True)), \
             patch.object(analyzer, "_format_prompt", return_value="prompt"), \
             patch.object(analyzer, "_call_litellm", return_value=(response_text, "codex_cli", usage)), \
             patch.object(analyzer, "_build_market_snapshot", return_value={}), \
             patch("src.analyzer.persist_llm_usage") as mock_persist:
            result = analyzer.analyze({"code": "600519", "stock_name": "贵州茅台"})

        assert result.success is True
        mock_persist.assert_not_called()

    def test_generate_text_returns_none_on_failure(self):
        analyzer = self._make_analyzer()
        with patch.object(analyzer, "_call_litellm", side_effect=Exception("LLM error")):
            result = analyzer.generate_text("prompt")
            assert result is None  # must not raise

    def test_generate_text_raises_generation_error_for_unsupported_backend(self):
        from src.llm.generation_backend import GenerationError

        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            generation_backend="codex",
            generation_fallback_backend="litellm",
        )

        with pytest.raises(GenerationError) as exc_info:
            analyzer.generate_text("prompt")

        assert exc_info.value.details["field"] == "GENERATION_BACKEND"
        assert exc_info.value.details["requested_backend"] == "codex"

    def test_generate_text_default_params(self):
        analyzer = self._make_analyzer()
        with patch.object(analyzer, "_call_litellm", return_value="ok") as mock_call:
            analyzer.generate_text("hello")
            _, kwargs = mock_call.call_args
            gen_cfg = kwargs["generation_config"]
            assert gen_cfg["max_tokens"] == 2048
            assert gen_cfg["temperature"] == 0.7

    def test_call_litellm_wrapper_uses_generation_backend_tuple_contract(self):
        from src.llm.generation_backend import GenerationBackend

        analyzer = self._make_analyzer()
        backend = MagicMock(spec=GenerationBackend)
        backend.generate.return_value = SimpleNamespace(
            text="backend response",
            model="gemini/gemini-3.1-pro-preview",
            usage={"provider": "gemini", "total_tokens": 9},
        )

        with patch.object(analyzer, "_get_generation_backend", return_value=backend):
            result = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
                system_prompt="system",
                stream=True,
                stream_progress_callback=lambda _chars: None,
                response_validator=lambda _text: None,
                audit_context={"call_type": "analysis"},
            )

        assert result == (
            "backend response",
            "gemini/gemini-3.1-pro-preview",
            {"provider": "gemini", "total_tokens": 9},
        )
        backend.generate.assert_called_once()
        _, generation_config = backend.generate.call_args.args
        assert generation_config == {"max_tokens": 128, "temperature": 0.2}
        assert backend.generate.call_args.kwargs["system_prompt"] == "system"
        assert backend.generate.call_args.kwargs["stream"] is True
        assert callable(backend.generate.call_args.kwargs["stream_progress_callback"])
        assert callable(backend.generate.call_args.kwargs["response_validator"])
        assert backend.generate.call_args.kwargs["audit_context"] == {"call_type": "analysis"}

    def test_call_litellm_wraps_fallback_generation_error_with_primary_context(self):
        from src.llm.generation_backend import GenerationBackend, GenerationError, GenerationErrorCode

        analyzer = self._make_analyzer()
        analyzer._config_override.generation_backend = "codex_cli"
        analyzer._config_override.generation_fallback_backend = "litellm"
        primary_error = GenerationError(
            error_code=GenerationErrorCode.COMMAND_NOT_FOUND,
            stage="configuration",
            retryable=False,
            fallbackable=True,
            backend="codex_cli",
            provider="codex_cli",
            details={"reason": "executable_not_found"},
        )
        fallback_error = GenerationError(
            error_code=GenerationErrorCode.INVALID_JSON,
            stage="validation",
            retryable=True,
            fallbackable=True,
            backend="litellm",
            provider="gemini",
            details={"reason": "invalid_json"},
        )
        primary_backend = MagicMock(spec=GenerationBackend)
        primary_backend.generate.side_effect = primary_error
        fallback_backend = MagicMock(spec=GenerationBackend)
        fallback_backend.generate.side_effect = fallback_error

        def _backend_for(backend_id):
            return primary_backend if backend_id == "codex_cli" else fallback_backend

        with patch.object(analyzer, "_get_generation_backend", side_effect=_backend_for):
            with pytest.raises(GenerationError) as exc_info:
                analyzer._call_litellm("prompt", {"max_tokens": 128})

        error = exc_info.value
        assert error.stage == "fallback"
        assert error.error_code is GenerationErrorCode.INVALID_JSON
        assert error.details["reason"] == "fallback_backend_failed"
        assert error.details["primary_error"]["error_code"] == "command_not_found"
        assert error.details["primary_error"]["details"]["reason"] == "executable_not_found"
        assert error.details["fallback_error"]["error_code"] == "invalid_json"
        assert error.details["fallback_error"]["details"]["reason"] == "invalid_json"

    def test_call_litellm_rejects_unknown_generation_backend_without_litellm_fallback(self):
        from src.llm.generation_backend import GenerationError

        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            generation_backend="codex",
            generation_fallback_backend="litellm",
        )

        with pytest.raises(GenerationError) as exc_info:
            analyzer._call_litellm("prompt", {"max_tokens": 128})

        assert exc_info.value.details["requested_backend"] == "codex"

    def test_call_litellm_rejects_unknown_generation_fallback_backend(self):
        from src.llm.generation_backend import GenerationError

        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            generation_backend="litellm",
            generation_fallback_backend="codex",
        )

        with pytest.raises(GenerationError) as exc_info:
            analyzer._call_litellm("prompt", {"max_tokens": 128})

        assert exc_info.value.details["field"] == "GENERATION_FALLBACK_BACKEND"
        assert exc_info.value.details["requested_backend"] == "codex"

    def test_analyze_reports_generation_backend_config_error_instead_of_api_key_missing(self):
        analyzer = self._make_analyzer()
        analyzer._litellm_available = True
        analyzer._config_override = SimpleNamespace(
            generation_backend="codex",
            generation_fallback_backend="litellm",
            report_language="zh",
            gemini_request_delay=0,
        )

        with patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
             patch.object(analyzer, "_get_skill_prompt_sections", return_value=(None, None, True)):
            result = analyzer.analyze({"code": "AAPL", "stock_name": "Apple"})

        assert result.success is False
        assert "backend_not_configured" in result.error_message
        assert "GENERATION_BACKEND" in result.error_message
        assert "codex" in result.error_message
        assert "API Key" not in result.error_message
        assert "API Key" not in result.analysis_summary

    def test_call_litellm_stream_aggregates_chunks_and_reports_progress(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="gemini/gemini-2.0-flash",
            litellm_fallback_models=[],
            llm_model_list=[],
        )

        def stream_response():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="abc"))],
                usage=None,
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="def"))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
            )

        progress_updates = []

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=stream_response()):
            text, model, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
                stream=True,
                stream_progress_callback=progress_updates.append,
            )

        assert text == "abcdef"
        assert model == "gemini/gemini-2.0-flash"
        _assert_usage_contains(usage, {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
        assert progress_updates == [3, 6]

    def test_call_litellm_stream_reads_private_hidden_usage_best_effort(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=[],
            llm_model_list=[],
        )

        def stream_response():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="abc"))],
                usage=None,
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=""))],
                usage=None,
                _hidden_params={
                    "usage": SimpleNamespace(prompt_tokens=11, completion_tokens=2, total_tokens=13)
                },
            )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=stream_response()):
            text, model, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
                stream=True,
            )

        assert text == "abc"
        assert model == "openai/gpt-4o-mini"
        _assert_usage_contains(usage, {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13})

    def test_call_litellm_stream_records_legacy_message_audit_for_actual_messages(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="gemini/gemini-2.0-flash",
            litellm_fallback_models=[],
            llm_model_list=[],
        )

        def stream_response():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))],
                usage=SimpleNamespace(prompt_tokens=8, completion_tokens=1, total_tokens=9),
            )

        audit_context = {
            "language": "zh",
            "market_group": "cn",
            "analysis_mode": "stock_analysis",
            "dynamic_markers": [
                {"marker_name": "stock_code", "message_role": "user", "text": "600519"},
                {"marker_name": "quote", "message_role": "user", "text": "## 📈 技术面数据"},
            ],
        }

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=stream_response()):
            text, model, usage = analyzer._call_litellm(
                "## 📊 股票基础信息\n| 股票代码 | **600519** |\n\n## 📈 技术面数据\n",
                {"max_tokens": 128, "temperature": 0.2},
                system_prompt="system prompt",
                stream=True,
                audit_context=audit_context,
            )

        assert text == "ok"
        assert model == "gemini/gemini-2.0-flash"
        _assert_usage_contains(usage, {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9})
        assert usage["language"] == "zh"
        assert usage["market_group"] == "cn"
        assert usage["analysis_mode"] == "stock_analysis"
        assert usage["provider"] == "gemini"
        assert usage["transport"] == "litellm"
        assert usage["message_count"] == 2
        markers = json.loads(usage["known_dynamic_marker_positions"])
        assert [marker["marker_name"] for marker in markers] == ["stock_code", "quote"]
        assert "600519" not in usage["known_dynamic_marker_positions"]

    def test_call_litellm_legacy_path_uses_legacy_model_list_for_param_recovery(self):
        with patch("src.analyzer.get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.litellm_model = "openai/gpt-4o-mini"
            cfg.litellm_fallback_models = []
            cfg.gemini_api_keys = []
            cfg.anthropic_api_keys = []
            cfg.deepseek_api_keys = []
            cfg.openai_api_keys = ["sk-openai-legacy-a", "sk-openai-legacy-b"]
            cfg.openai_base_url = None
            cfg.llm_model_list = [
                {
                    "model_name": "__legacy_openai__",
                    "litellm_params": {
                        "model": "__legacy_openai__",
                        "api_key": "sk-openai-legacy-a",
                        "api_base": "https://legacy-a.example/v1",
                        "extra_headers": {"x-tenant": "legacy-a"},
                    },
                },
                {
                    "model_name": "__legacy_openai__",
                    "litellm_params": {
                        "model": "__legacy_openai__",
                        "api_key": "sk-openai-legacy-b",
                        "api_base": "https://legacy-b.example/v1",
                        "extra_headers": {"x-tenant": "legacy-b"},
                    },
                },
            ]
            cfg.llm_temperature = 0.7
            mock_cfg.return_value = cfg

            from src.analyzer import GeminiAnalyzer

            analyzer = GeminiAnalyzer()
            analyzer._config_override = cfg

        captured = {}

        def _fake_call_litellm_with_param_recovery(call, **kwargs):
            captured["model_list"] = kwargs.get("model_list")
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=None,
            )

        with patch("src.analyzer.call_litellm_with_param_recovery", side_effect=_fake_call_litellm_with_param_recovery):
            text, _, _ = analyzer._call_litellm("回归用例", {"max_tokens": 128, "temperature": 0.7})

        assert text == "ok"
        passed_model_list = captured.get("model_list")
        assert passed_model_list is not None
        assert len(passed_model_list) == 2
        assert all(item["litellm_params"].get("model") == "openai/gpt-4o-mini" for item in passed_model_list)
        assert [item["litellm_params"]["api_base"] for item in passed_model_list] == [
            "https://legacy-a.example/v1",
            "https://legacy-b.example/v1",
        ]
        assert [item["litellm_params"]["extra_headers"] for item in passed_model_list] == [
            {"x-tenant": "legacy-a"},
            {"x-tenant": "legacy-b"},
        ]

    @patch("src.analyzer.Router")
    def test_analyzer_legacy_router_recovery_cache_is_scoped_by_api_base(self, mock_router):
        """Analyzer legacy recovery should not leak across same model different api_base."""
        from src.analyzer import call_litellm_with_param_recovery as real_call
        from src.llm.generation_params import clear_litellm_generation_param_recovery_cache

        clear_litellm_generation_param_recovery_cache()
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="analyzer ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )
        strict_router = MagicMock()
        flex_router = MagicMock()
        strict_router.completion.side_effect = [
            RuntimeError("Unsupported parameter: temperature is not supported"),
            response,
        ]
        flex_router.completion.return_value = response
        mock_router.side_effect = [strict_router, flex_router]

        strict_cfg = SimpleNamespace(
            litellm_model="openai/shared-model",
            litellm_fallback_models=[],
            llm_model_list=[],
            llm_temperature=0.2,
            gemini_api_keys=[],
            anthropic_api_keys=[],
            openai_api_keys=["sk-strict-key-1", "sk-strict-key-2"],
            deepseek_api_keys=[],
            openai_base_url="https://strict.example/v1",
        )
        flex_cfg = SimpleNamespace(
            litellm_model="openai/shared-model",
            litellm_fallback_models=[],
            llm_model_list=[],
            llm_temperature=0.2,
            gemini_api_keys=[],
            anthropic_api_keys=[],
            openai_api_keys=["sk-flex-key-1", "sk-flex-key-2"],
            deepseek_api_keys=[],
            openai_base_url="https://flex.example/v1",
        )

        captured_model_lists = []

        def _fake_recovery(call, **kwargs):
            captured_model_lists.append(kwargs.get("model_list"))
            return real_call(call, **kwargs)

        import src.analyzer as analyzer_module
        from src.analyzer import GeminiAnalyzer

        with patch.object(analyzer_module, "call_litellm_with_param_recovery", side_effect=_fake_recovery):
            GeminiAnalyzer(config=strict_cfg)._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )
            GeminiAnalyzer(config=flex_cfg)._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert len(captured_model_lists) == 2
        strict_model_list = captured_model_lists[0]
        flex_model_list = captured_model_lists[1]
        assert strict_model_list is not None
        assert flex_model_list is not None
        assert all(
            item.get("litellm_params", {}).get("api_base") == "https://strict.example/v1"
            for item in strict_model_list
        )
        assert all(
            item.get("litellm_params", {}).get("api_base") == "https://flex.example/v1"
            for item in flex_model_list
        )
        assert strict_router.completion.call_args_list[0].kwargs["temperature"] == 0.2
        assert "temperature" not in strict_router.completion.call_args_list[1].kwargs
        assert flex_router.completion.call_args.kwargs["temperature"] == 0.2

    def test_prompt_cache_hints_disabled_does_not_change_analyzer_request_shape(self):
        from src.analyzer import GeminiAnalyzer

        cfg = SimpleNamespace(
            litellm_model="openai/gpt-4o",
            litellm_fallback_models=[],
            llm_model_list=[],
            llm_temperature=0.7,
            gemini_api_keys=[],
            anthropic_api_keys=[],
            openai_api_keys=["sk-openai-test"],
            deepseek_api_keys=[],
            openai_base_url=None,
            llm_prompt_cache_telemetry_enabled=True,
            llm_prompt_cache_hints_enabled=False,
            llm_prompt_cache_diagnostics_level="off",
        )
        analyzer = GeminiAnalyzer(config=cfg)
        captured = {}

        def _fake_recovery(call, **kwargs):
            captured["call_kwargs"] = kwargs["call_kwargs"]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage={"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
            )

        with patch("src.analyzer.call_litellm_with_param_recovery", side_effect=_fake_recovery):
            text, _, _ = analyzer._call_litellm("dynamic prompt", {"max_tokens": 128, "temperature": 0.7})

        assert text == "ok"
        call_kwargs = captured["call_kwargs"]
        assert "prompt_cache_key" not in call_kwargs
        assert call_kwargs["messages"] == [
            {"role": "system", "content": analyzer.TEXT_SYSTEM_PROMPT},
            {"role": "user", "content": "dynamic prompt"},
        ]

    def test_prompt_cache_telemetry_disabled_filters_cache_fields_from_analyzer_usage(self):
        from src.analyzer import GeminiAnalyzer

        cfg = SimpleNamespace(
            litellm_model="openai/gpt-4o",
            litellm_fallback_models=[],
            llm_model_list=[],
            llm_temperature=0.7,
            gemini_api_keys=[],
            anthropic_api_keys=[],
            openai_api_keys=["sk-openai-test"],
            deepseek_api_keys=[],
            openai_base_url=None,
            llm_prompt_cache_telemetry_enabled=False,
            llm_prompt_cache_hints_enabled=False,
            llm_prompt_cache_diagnostics_level="off",
        )
        analyzer = GeminiAnalyzer(config=cfg)

        def _fake_recovery(call, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage={
                    "prompt_tokens": 1200,
                    "completion_tokens": 1,
                    "total_tokens": 1201,
                    "prompt_tokens_details": {"cached_tokens": 1000},
                },
            )

        with patch("src.analyzer.call_litellm_with_param_recovery", side_effect=_fake_recovery):
            _, _, usage = analyzer._call_litellm("dynamic prompt", {"max_tokens": 128, "temperature": 0.7})

        assert usage["prompt_tokens"] == 1200
        assert usage["completion_tokens"] == 1
        assert usage["total_tokens"] == 1201
        assert "provider_usage_json" not in usage
        assert "normalized_cache_read_tokens" not in usage
        assert "cache_capability" not in usage
        assert usage["messages_hmac"]

    def test_prompt_cache_telemetry_disabled_marks_no_usage_response_for_storage(self):
        from src.analyzer import GeminiAnalyzer

        cfg = SimpleNamespace(
            litellm_model="openai/gpt-4o",
            litellm_fallback_models=[],
            llm_model_list=[],
            llm_temperature=0.7,
            gemini_api_keys=[],
            anthropic_api_keys=[],
            openai_api_keys=["sk-openai-test"],
            deepseek_api_keys=[],
            openai_base_url=None,
            llm_prompt_cache_telemetry_enabled=False,
            llm_prompt_cache_hints_enabled=False,
            llm_prompt_cache_diagnostics_level="off",
        )
        analyzer = GeminiAnalyzer(config=cfg)

        def _fake_recovery(call, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=None,
            )

        with patch("src.analyzer.call_litellm_with_param_recovery", side_effect=_fake_recovery):
            text, _, usage = analyzer._call_litellm("dynamic prompt", {"max_tokens": 128, "temperature": 0.7})

        assert text == "ok"
        assert getattr(usage, "prompt_cache_telemetry_disabled", False)
        assert "cache_capability" not in usage
        assert "cache_eligibility" not in usage
        assert "cache_observation" not in usage
        assert usage["messages_hmac"]

    def test_call_litellm_stream_falls_back_to_non_stream_before_first_chunk(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="gemini/gemini-2.0-flash",
            litellm_fallback_models=[],
            llm_model_list=[],
        )

        def broken_stream():
            raise RuntimeError("stream unsupported")
            yield  # pragma: no cover

        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="full response"))],
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=5, total_tokens=9),
        )

        dispatch_calls = []

        def fake_dispatch(model, call_kwargs, **kwargs):
            dispatch_calls.append(call_kwargs.copy())
            if call_kwargs.get("stream"):
                return broken_stream()
            return response

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=fake_dispatch):
            text, model, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
                stream=True,
            )

        assert text == "full response"
        assert model == "gemini/gemini-2.0-flash"
        _assert_usage_contains(usage, {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9})
        assert len(dispatch_calls) == 2
        assert dispatch_calls[0]["stream"] is True
        assert "stream" not in dispatch_calls[1]

    @pytest.mark.parametrize(
        "provider_model,response_payload,expected_text",
        _OPENAI_COMPATIBILITY_PAYLOAD_FIXTURES,
        ids=["issue1279-message-content-null", "issue1279-message-content-list"],
    )
    def test_call_litellm_extracts_external_provider_text_shapes(self, provider_model, response_payload, expected_text):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model=provider_model,
            litellm_fallback_models=[],
            llm_model_list=[],
        )
        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response_payload):
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert text == expected_text
        assert model_used == provider_model
        _assert_usage_contains(usage, response_payload["usage"])

    def test_call_litellm_falls_back_to_message_content_when_blocks_empty(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="openai/deepseek-chat",
            litellm_fallback_models=[],
            llm_model_list=[],
        )
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    content_blocks=[],
                    message=SimpleNamespace(content="message response"),
                )
            ],
            usage=None,
        )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response):
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert text == "message response"
        assert model_used == "openai/deepseek-chat"
        _assert_no_provider_usage_hmac_only(usage)
        assert "message_count" not in usage
        assert "known_dynamic_marker_positions" not in usage

    def test_call_litellm_normalizes_kimi_k26_temperature(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="openai/kimi-k2.6",
            litellm_fallback_models=[],
            llm_model_list=[],
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response) as mock_dispatch:
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert text == "ok"
        assert model_used == "openai/kimi-k2.6"
        _assert_usage_contains(usage, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        call_kwargs = mock_dispatch.call_args.args[1]
        assert call_kwargs["temperature"] == 1.0

    def test_call_litellm_non_stream_records_legacy_message_audit_for_actual_messages(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=[],
            llm_model_list=[],
        )
        prompt = (
            "# 决策仪表盘分析请求\n"
            "| 股票代码 | **600519** |\n"
            "| 股票名称 | **贵州茅台** |\n"
            "| 分析日期 | 2026-06-19 |\n\n"
            "## ✅ 分析任务\n"
            "请输出 JSON。"
        )
        fixed_rules_offset = prompt.index("## ✅ 分析任务")
        audit_context = {
            "language": "zh",
            "market_group": "cn",
            "analysis_mode": "stock_analysis",
            "dynamic_markers": [
                {"marker_name": "stock_code", "message_role": "user", "text": "600519"},
                {"marker_name": "stock_name", "message_role": "user", "text": "贵州茅台"},
                {"marker_name": "analysis_date", "message_role": "user", "text": "2026-06-19"},
            ],
        }
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=1, total_tokens=11),
        )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response):
            text, model_used, usage = analyzer._call_litellm(
                prompt,
                {"max_tokens": 128, "temperature": 0.2},
                system_prompt="system prompt",
                audit_context=audit_context,
            )

        assert text == "ok"
        assert model_used == "openai/gpt-4o-mini"
        _assert_usage_contains(usage, {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11})
        assert usage["provider"] == "openai"
        assert usage["message_count"] == 2
        markers = {
            marker["marker_name"]: marker
            for marker in json.loads(usage["known_dynamic_marker_positions"])
        }
        for marker_name in ("stock_code", "stock_name", "analysis_date"):
            assert markers[marker_name]["message_role"] == "user"
            assert markers[marker_name]["char_offset"] < fixed_rules_offset
        assert "600519" not in usage["known_dynamic_marker_positions"]
        assert "贵州茅台" not in usage["known_dynamic_marker_positions"]
        assert "2026-06-19" not in usage["known_dynamic_marker_positions"]

    def test_call_litellm_system_hmac_distinguishes_language_and_market_prompt(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=[],
            llm_model_list=[],
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=1, total_tokens=11),
        )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response):
            _, _, zh_usage = analyzer._call_litellm(
                "same user prompt 600519",
                {"max_tokens": 128, "temperature": 0.2},
                system_prompt="system prompt zh cn",
                audit_context={
                    "language": "zh",
                    "market_group": "cn",
                    "analysis_mode": "stock_analysis",
                    "dynamic_markers": [
                        {"marker_name": "stock_code", "message_role": "user", "text": "600519"},
                    ],
                },
            )
            _, _, en_usage = analyzer._call_litellm(
                "same user prompt 600519",
                {"max_tokens": 128, "temperature": 0.2},
                system_prompt="system prompt en us",
                audit_context={
                    "language": "en",
                    "market_group": "us",
                    "analysis_mode": "stock_analysis",
                    "dynamic_markers": [
                        {"marker_name": "stock_code", "message_role": "user", "text": "600519"},
                    ],
                },
            )

        assert zh_usage["system_message_hmac"] != en_usage["system_message_hmac"]
        assert zh_usage["messages_hmac"] != en_usage["messages_hmac"]
        assert zh_usage["user_message_hmac"] == en_usage["user_message_hmac"]
        assert zh_usage["market_group"] == "cn"
        assert en_usage["market_group"] == "us"

    def test_call_litellm_normalizes_kimi_k26_temperature_for_yaml_alias(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="kimi_router",
            litellm_fallback_models=[],
            llm_model_list=[
                {
                    "model_name": "kimi_router",
                    "litellm_params": {"model": "openai/kimi-k2.6"},
                }
            ],
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response) as mock_dispatch:
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert text == "ok"
        assert model_used == "kimi_router"
        _assert_usage_contains(usage, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        call_kwargs = mock_dispatch.call_args.args[1]
        assert call_kwargs["temperature"] == 1.0

    def test_call_litellm_normalizes_kimi_k26_temperature_for_non_thinking_yaml_alias(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="kimi_router",
            litellm_fallback_models=[],
            llm_model_list=[
                {
                    "model_name": "kimi_router",
                    "litellm_params": {
                        "model": "openai/kimi-k2.6",
                        "extra_body": {"thinking": {"type": "disabled"}},
                    },
                }
            ],
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response) as mock_dispatch:
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert text == "ok"
        assert model_used == "kimi_router"
        _assert_usage_contains(usage, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        call_kwargs = mock_dispatch.call_args.args[1]
        assert call_kwargs["temperature"] == 0.6

    def test_call_litellm_resolves_anthropic_alias_for_usage_normalization(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="claude-router",
            litellm_fallback_models=[],
            llm_model_list=[
                {
                    "model_name": "claude-router",
                    "litellm_params": {"model": "anthropic/claude-sonnet-test"},
                }
            ],
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=30,
                cache_read_input_tokens=10,
                cache_creation_input_tokens=20,
            ),
        )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response):
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert text == "ok"
        assert model_used == "claude-router"
        assert usage["prompt_tokens"] == 130
        assert usage["completion_tokens"] == 30
        assert usage["total_tokens"] == 160
        assert usage["normalized_cache_read_tokens"] == 10
        assert usage["normalized_cache_write_tokens"] == 20
        assert usage["cache_observation"] == "read_and_write"

    def test_call_litellm_uses_openai_wire_model_for_alias_usage_threshold(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="fast",
            litellm_fallback_models=[],
            llm_model_list=[
                {
                    "model_name": "fast",
                    "litellm_params": {"model": "openai/gpt-4o"},
                }
            ],
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(
                prompt_tokens=500,
                completion_tokens=20,
                total_tokens=520,
                prompt_tokens_details={"cached_tokens": 0},
            ),
        )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response):
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert text == "ok"
        assert model_used == "fast"
        assert usage["provider_min_cache_tokens"] == 1024
        assert usage["cache_capability"] == "supported"
        assert usage["cache_eligibility"] == "below_threshold"
        assert usage["cache_observation"] == "unknown"
        assert usage["normalized_cache_read_tokens"] == 0
        assert usage["normalized_cache_eligible_input_tokens"] is None
        assert usage["normalized_cache_hit_ratio"] is None

    def test_call_litellm_preserves_anthropic_litellm_prompt_tokens_without_input_tokens(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="claude-router",
            litellm_fallback_models=[],
            llm_model_list=[
                {
                    "model_name": "claude-router",
                    "litellm_params": {"model": "anthropic/claude-sonnet-test"},
                }
            ],
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response):
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert text == "ok"
        assert model_used == "claude-router"
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 20
        assert usage["total_tokens"] == 120
        assert usage["normalized_prompt_tokens"] == 100
        assert usage["normalized_uncached_input_tokens"] == 100
        assert usage["cache_observation"] == "zero_hit"
        assert usage["messages_hmac"] and len(usage["messages_hmac"]) == 64

    def test_call_litellm_stream_resolves_glm_alias_for_usage_normalization(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="glm-router",
            litellm_fallback_models=[],
            llm_model_list=[
                {
                    "model_name": "glm-router",
                    "litellm_params": {"model": "zhipu/glm-4.5"},
                }
            ],
        )

        def stream_response():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))],
                usage=SimpleNamespace(
                    prompt_tokens=1200,
                    completion_tokens=80,
                    total_tokens=1280,
                    prompt_tokens_details={"cached_tokens": 1200},
                ),
            )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=stream_response()):
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
                stream=True,
            )

        assert text == "ok"
        assert model_used == "glm-router"
        assert usage["normalized_cache_read_tokens"] == 1200
        assert usage["cache_capability"] == "supported"
        assert usage["cache_observation"] == "full_hit"

    def test_call_litellm_stream_uses_openai_wire_model_for_alias_usage_threshold(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="fast",
            litellm_fallback_models=[],
            llm_model_list=[
                {
                    "model_name": "fast",
                    "litellm_params": {"model": "openai/gpt-4o"},
                }
            ],
        )

        def stream_response():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))],
                usage=SimpleNamespace(
                    prompt_tokens=500,
                    completion_tokens=20,
                    total_tokens=520,
                    prompt_tokens_details={"cached_tokens": 0},
                ),
            )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=stream_response()):
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
                stream=True,
            )

        assert text == "ok"
        assert model_used == "fast"
        assert usage["provider_min_cache_tokens"] == 1024
        assert usage["cache_capability"] == "supported"
        assert usage["cache_eligibility"] == "below_threshold"
        assert usage["cache_observation"] == "unknown"
        assert usage["normalized_cache_read_tokens"] == 0
        assert usage["normalized_cache_eligible_input_tokens"] is None
        assert usage["normalized_cache_hit_ratio"] is None

    def test_call_litellm_omits_temperature_for_gpt5_family(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="openai/gpt5.5-ferr",
            litellm_fallback_models=[],
            llm_model_list=[],
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

        with patch.object(analyzer, "_dispatch_litellm_completion", return_value=response) as mock_dispatch:
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert text == "ok"
        assert model_used == "openai/gpt5.5-ferr"
        _assert_usage_contains(usage, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        call_kwargs = mock_dispatch.call_args.args[1]
        assert "temperature" not in call_kwargs

    def test_call_litellm_recovers_from_temperature_default_error(self):
        from src.llm.generation_params import clear_litellm_generation_param_recovery_cache

        clear_litellm_generation_param_recovery_cache()
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="openai/custom-default-temp",
            litellm_fallback_models=[],
            llm_model_list=[],
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )
        calls = []

        def _dispatch(model, call_kwargs, **_kwargs):
            calls.append(dict(call_kwargs))
            if len(calls) == 1:
                raise RuntimeError(
                    "temperature=0.2 is unsupported. Only the default (1.0) value is supported."
                )
            return response

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=_dispatch):
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert text == "ok"
        assert model_used == "openai/custom-default-temp"
        _assert_usage_contains(usage, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        assert calls[0]["temperature"] == 0.2
        assert calls[1]["temperature"] == 1.0

    def test_call_litellm_keeps_user_temperature_for_non_kimi_fallback(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="openai/kimi-k2.6",
            litellm_fallback_models=["openai/gpt-4o-mini"],
            llm_model_list=[],
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="fallback ok"))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )
        temperatures = []

        def fake_dispatch(model, call_kwargs, **kwargs):
            temperatures.append((model, call_kwargs["temperature"]))
            if model == "openai/kimi-k2.6":
                raise RuntimeError("primary failed")
            return response

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=fake_dispatch):
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
            )

        assert text == "fallback ok"
        assert model_used == "openai/gpt-4o-mini"
        _assert_usage_contains(usage, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
        assert temperatures == [
            ("openai/kimi-k2.6", 1.0),
            ("openai/gpt-4o-mini", 0.2),
        ]

    def test_call_litellm_stream_falls_back_to_non_stream_after_partial_and_falls_back_model(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="provider/bad-model",
            litellm_fallback_models=["provider/good-model"],
            llm_model_list=[],
        )

        def partial_then_broken_stream():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="abc"))],
                usage=None,
            )
            raise RuntimeError("stream disconnected")

        def good_stream():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="fallback"))],
                usage=SimpleNamespace(prompt_tokens=4, completion_tokens=5, total_tokens=9),
            )

        fallback_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="fallback full"))],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=8, total_tokens=15),
        )

        dispatch_calls = []

        def fake_dispatch(model, call_kwargs, **kwargs):
            dispatch_calls.append((model, bool(call_kwargs.get("stream"))))
            if model == "provider/bad-model":
                if call_kwargs.get("stream"):
                    return partial_then_broken_stream()
                raise RuntimeError("non-stream model broken")
            if call_kwargs.get("stream"):
                return good_stream()
            return fallback_response

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=fake_dispatch):
            text, model_used, usage = analyzer._call_litellm(
                "prompt",
                {"max_tokens": 128, "temperature": 0.2},
                stream=True,
            )

        assert text == "fallback"
        assert model_used == "provider/good-model"
        _assert_usage_contains(usage, {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9})
        assert dispatch_calls == [
            ("provider/bad-model", True),
            ("provider/bad-model", False),
            ("provider/good-model", True),
        ]

    def test_analyze_integrity_retry_keeps_progress_monotonic(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            gemini_request_delay=0,
            report_language="zh",
            litellm_model="gemini/gemini-2.0-flash",
            llm_temperature=0.2,
            report_integrity_enabled=True,
            report_integrity_retry=1,
        )

        from src.analyzer import AnalysisResult

        progress_updates = []
        first_result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=80,
            trend_prediction="看多",
            operation_advice="持有",
            analysis_summary="首轮结果",
        )
        second_result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=82,
            trend_prediction="看多",
            operation_advice="持有",
            analysis_summary="补全后结果",
        )

        with patch.object(analyzer, "is_available", return_value=True), \
             patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
             patch.object(analyzer, "_format_prompt", return_value="prompt"), \
             patch.object(
                 analyzer,
                 "_call_litellm",
                 side_effect=[
                     ("first response", "model-a", {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}),
                     ("second response", "model-a", {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}),
                 ],
             ), \
             patch.object(analyzer, "_parse_response", side_effect=[first_result, second_result]), \
             patch.object(analyzer, "_build_market_snapshot", return_value={}), \
             patch.object(
                 analyzer,
                 "_check_content_integrity",
                 side_effect=[(False, ["analysis_summary"]), (True, [])],
             ), \
             patch.object(analyzer, "_build_integrity_retry_prompt", return_value="retry prompt"), \
             patch("src.analyzer.persist_llm_usage"):
            result = analyzer.analyze(
                {"code": "600519", "stock_name": "贵州茅台"},
                progress_callback=lambda progress, message: progress_updates.append((progress, message)),
            )

        assert result.analysis_summary == "补全后结果"
        assert [progress for progress, _ in progress_updates] == [68, 93, 94, 95]
        assert "补全重试" in progress_updates[2][1]
        assert "解析 JSON" in progress_updates[3][1]

    def test_analyze_persists_provider_usage_from_private_stream_hidden_usage_best_effort(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            gemini_request_delay=0,
            report_language="zh",
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=[],
            llm_model_list=[],
            llm_temperature=0.2,
            report_integrity_enabled=False,
            report_integrity_retry=0,
        )

        from src.analyzer import AnalysisResult

        parsed_result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=80,
            trend_prediction="看多",
            operation_advice="持有",
            analysis_summary="分析结果",
        )

        def stream_response():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content='{"sentiment_score":80}'))],
                usage=None,
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=""))],
                usage=None,
                _hidden_params={
                    "usage": SimpleNamespace(prompt_tokens=11, completion_tokens=2, total_tokens=13)
                },
            )

        with patch.object(analyzer, "is_available", return_value=True), \
             patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
             patch.object(analyzer, "_get_skill_prompt_sections", return_value=("RSI skill raw", "Default skill policy", False)), \
             patch.object(analyzer, "_format_prompt", return_value="prompt"), \
             patch.object(analyzer, "_validate_json_response"), \
             patch.object(analyzer, "_dispatch_litellm_completion", return_value=stream_response()), \
             patch.object(analyzer, "_parse_response", return_value=parsed_result), \
             patch.object(analyzer, "_build_market_snapshot", return_value={}), \
             patch("src.analyzer.persist_llm_usage") as mock_usage:
            result = analyzer.analyze({"code": "600519", "stock_name": "贵州茅台"})

        assert result.analysis_summary == "分析结果"
        mock_usage.assert_called_once()
        usage_arg, model_arg = mock_usage.call_args[0]
        assert model_arg == "openai/gpt-4o-mini"
        _assert_usage_contains(usage_arg, {"prompt_tokens": 11, "completion_tokens": 2, "total_tokens": 13})
        assert usage_arg["language"] == "zh"
        assert usage_arg["market_group"] == "cn"
        assert usage_arg["analysis_mode"] == "stock_analysis"
        assert usage_arg["legacy_prompt_mode"] == "skill_aware"
        assert usage_arg["skill_config_hmac"] and len(usage_arg["skill_config_hmac"]) == 64
        assert usage_arg["provider"] == "openai"
        assert usage_arg["transport"] == "litellm"
        assert usage_arg["message_count"] == 2
        assert json.loads(usage_arg["known_dynamic_marker_positions"]) == []
        assert mock_usage.call_args.kwargs == {"call_type": "analysis", "stock_code": "600519"}

    def test_analyze_records_marker_positions_from_real_prompt_format(self):
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            gemini_request_delay=0,
            report_language="zh",
            litellm_model="openai/gpt-4o-mini",
            litellm_fallback_models=[],
            llm_model_list=[],
            llm_temperature=0.2,
            report_integrity_enabled=False,
            report_integrity_retry=0,
            news_max_age_days=3,
            news_strategy_profile="short",
        )

        from src.analyzer import AnalysisResult

        parsed_result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=80,
            trend_prediction="看多",
            operation_advice="持有",
            analysis_summary="分析结果",
        )

        def stream_response():
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content='{"sentiment_score":80}'))],
                usage=SimpleNamespace(prompt_tokens=42, completion_tokens=3, total_tokens=45),
            )

        context = {
            "code": "600519",
            "stock_name": "贵州茅台",
            "date": "2026-06-19",
            "today": {
                "close": 1500,
                "open": 1490,
                "high": 1510,
                "low": 1480,
                "pct_chg": 1.2,
                "volume": 100000,
                "amount": 150000000,
            },
            "market_phase_context": {
                "phase": "intraday",
                "is_partial_bar": False,
            },
            "daily_market_context": {
                "summary": "市场偏谨慎，等待量能确认。",
                "region": "cn",
                "trade_date": "2026-06-19",
            },
        }

        with patch.object(analyzer, "is_available", return_value=True), \
             patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
             patch.object(analyzer, "_get_skill_prompt_sections", return_value=("RSI skill raw", "Default skill policy", False)), \
             patch.object(analyzer, "_validate_json_response"), \
             patch.object(analyzer, "_dispatch_litellm_completion", return_value=stream_response()), \
             patch.object(analyzer, "_parse_response", return_value=parsed_result), \
             patch.object(analyzer, "_build_market_snapshot", return_value={}), \
             patch("src.analyzer.persist_llm_usage") as mock_usage:
            result = analyzer.analyze(
                context,
                news_context="2026-06-18 贵州茅台发布经营公告。",
                analysis_context_pack_summary="## 分析上下文包\n- 估值处于中性区间。",
            )

        assert result.analysis_summary == "分析结果"
        mock_usage.assert_called_once()
        usage_arg, _ = mock_usage.call_args[0]
        markers = {
            marker["marker_name"]: marker
            for marker in json.loads(usage_arg["known_dynamic_marker_positions"])
        }
        for marker_name in (
            "stock_code",
            "stock_name",
            "analysis_date",
            "market_phase",
            "daily_market_context",
            "analysis_context_pack",
            "quote",
            "news_context",
        ):
            assert marker_name in markers
            assert markers[marker_name]["message_role"] == "user"
            assert isinstance(markers[marker_name]["char_offset"], int)
            assert markers[marker_name]["char_offset"] >= 0
        assert usage_arg["legacy_prompt_mode"] == "skill_aware"
        assert usage_arg["skill_config_hmac"] and len(usage_arg["skill_config_hmac"]) == 64
        assert "600519" not in usage_arg["known_dynamic_marker_positions"]
        assert "贵州茅台" not in usage_arg["known_dynamic_marker_positions"]
        assert "2026-06-19" not in usage_arg["known_dynamic_marker_positions"]

    def test_parse_response_non_json_returns_failure(self):
        """_parse_response must return success=False when LLM output is not valid JSON."""
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(report_language="zh")

        from src.analyzer import GeminiAnalyzer

        result = GeminiAnalyzer._parse_response(analyzer, "这是一段纯文本分析，没有 JSON。", "600519", "贵州茅台")
        assert result.success is False
        assert result.error_message is not None
        assert result.code == "600519"

    def test_parse_response_malformed_json_returns_failure(self):
        """_parse_response must return success=False when JSON extraction fails."""
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(report_language="zh")

        from src.analyzer import GeminiAnalyzer

        malformed = "Here is the analysis: {broken json content without closing"
        result = GeminiAnalyzer._parse_response(analyzer, malformed, "AAPL", "Apple")
        assert result.success is False
        assert result.error_message is not None

    def test_parse_response_valid_json_returns_success(self):
        """_parse_response must return success=True when LLM output contains valid JSON."""
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(report_language="zh")

        from src.analyzer import GeminiAnalyzer
        import json

        valid_response = json.dumps({
            "sentiment_score": 75,
            "trend_prediction": "看多",
            "operation_advice": "持有",
            "analysis_summary": "测试分析",
        })
        result = GeminiAnalyzer._parse_response(analyzer, valid_response, "600519", "贵州茅台")
        assert result.success is True
        assert result.error_message is None

    def test_json_parse_failure_triggers_fallback_model(self):
        """When the primary model returns non-JSON, _call_litellm must try the fallback model."""
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="provider/primary-model",
            litellm_fallback_models=["provider/fallback-model"],
            llm_model_list=[],
        )

        import json as _json
        valid_json = _json.dumps({"sentiment_score": 70, "trend_prediction": "看多"})
        dispatch_calls = []

        def fake_dispatch(model, call_kwargs, **kwargs):
            dispatch_calls.append(model)
            if "primary" in model:
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="这不是 JSON 格式的响应"))],
                    usage=None,
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=valid_json))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            )

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=fake_dispatch):
            text, model_used, usage = analyzer._call_litellm(
                "test prompt",
                {"max_tokens": 128, "temperature": 0.7},
                response_validator=analyzer._validate_json_response,
            )

        assert "primary" in dispatch_calls[0], "primary model should be tried first"
        assert len(dispatch_calls) == 2, "fallback model should be tried after primary JSON failure"
        assert "fallback" in model_used
        assert valid_json == text

    def test_all_models_invalid_json_raises_all_models_failed_error(self):
        """When all models return non-JSON, _AllModelsFailedError is raised with last_response_text."""
        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            litellm_model="provider/primary-model",
            litellm_fallback_models=["provider/fallback-model"],
            llm_model_list=[],
        )

        from src.analyzer import _AllModelsFailedError

        def fake_dispatch(model, call_kwargs, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="这不是 JSON 格式的响应"))],
                usage=None,
            )

        with patch.object(analyzer, "_dispatch_litellm_completion", side_effect=fake_dispatch):
            with pytest.raises(_AllModelsFailedError) as exc_info:
                analyzer._call_litellm(
                    "test prompt",
                    {"max_tokens": 128, "temperature": 0.7},
                    response_validator=analyzer._validate_json_response,
                )

        assert exc_info.value.last_response_text == "这不是 JSON 格式的响应"

    def test_analyze_all_models_invalid_json_goes_through_post_processing(self):
        """When all models return non-JSON, analyze() must still run integrity
        checks, placeholder fill, and persist_llm_usage — no early return.

        With report_integrity_retry=1, the retry loop runs once (re-prompting
        with complement instructions); when that also yields invalid JSON the
        exhausted-retries path fires placeholder fill.
        """
        from src.analyzer import AnalysisResult, _AllModelsFailedError

        analyzer = self._make_analyzer()
        analyzer._config_override = SimpleNamespace(
            gemini_request_delay=0,
            report_language="zh",
            litellm_model="provider/primary-model",
            litellm_fallback_models=["provider/fallback-model"],
            llm_temperature=0.7,
            llm_model_list=[],
            report_integrity_enabled=True,
            report_integrity_retry=1,
        )

        # _parse_response on non-JSON text produces a text fallback result
        text_fallback_result = AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=50,
            trend_prediction="震荡",
            operation_advice="持有",
            analysis_summary="部分文本摘要",
            success=False,
            error_message="LLM response is not valid JSON; analysis result will not be persisted",
        )

        all_models_error = _AllModelsFailedError(
            "all failed",
            last_response_text="这不是 JSON，而是纯文本分析结果",
            last_model="provider/fallback-model",
            last_usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

        with patch.object(analyzer, "is_available", return_value=True), \
             patch.object(analyzer, "_get_analysis_system_prompt", return_value="system"), \
             patch.object(analyzer, "_format_prompt", return_value="prompt"), \
             patch.object(
                 analyzer,
                 "_call_litellm",
                 side_effect=all_models_error,
             ) as mock_call, \
             patch.object(analyzer, "_parse_response", return_value=text_fallback_result) as mock_parse, \
             patch.object(analyzer, "_build_market_snapshot", return_value={}), \
             patch.object(analyzer, "_check_content_integrity", return_value=(False, ["dashboard.core_conclusion.one_sentence"])), \
             patch.object(analyzer, "_build_integrity_retry_prompt", return_value="retry prompt"), \
             patch.object(analyzer, "_apply_placeholder_fill") as mock_fill, \
             patch("src.analyzer.persist_llm_usage") as mock_usage:

            result = analyzer.analyze(
                {"code": "600519", "stock_name": "贵州茅台"},
                news_context="some news",
            )

        # _call_litellm called twice: initial + 1 retry
        assert mock_call.call_count == 2

        # _parse_response called twice (initial + retry)
        assert mock_parse.call_count == 2
        mock_parse.assert_called_with("这不是 JSON，而是纯文本分析结果", "600519", "贵州茅台")

        # Placeholder fill was applied after retry exhaustion
        mock_fill.assert_called_once()
        assert "dashboard.core_conclusion.one_sentence" in mock_fill.call_args[0][1]

        # persist_llm_usage was called with the last model and usage
        mock_usage.assert_called_once()
        usage_args = mock_usage.call_args
        assert usage_args[0][0] == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        assert usage_args[0][1] == "provider/fallback-model"
        assert usage_args[1]["call_type"] == "analysis"
        assert usage_args[1]["stock_code"] == "600519"

        # Result is success=False (text fallback), but all fields exist
        assert result.success is False
        assert result.code == "600519"
        assert result.search_performed is True


# ---------------------------------------------------------------------------
# market_analyzer uses generate_text(), not private attributes
# ---------------------------------------------------------------------------

class TestMarketAnalyzerBypassFix:
    def _make_market_analyzer_with_mock_generate_text(self, return_value="复盘报告"):
        """Return a MarketAnalyzer whose embedded Analyzer.generate_text is mocked."""
        from src.core.market_profile import CN_PROFILE
        from src.core.market_strategy import get_market_strategy_blueprint

        with patch("src.analyzer.get_config") as mock_cfg, \
             patch("src.market_analyzer.get_config") as mock_cfg2:
            cfg = MagicMock()
            cfg.litellm_model = "gemini/gemini-2.0-flash"
            cfg.litellm_fallback_models = []
            cfg.gemini_api_keys = ["sk-gemini-testkey-1234"]
            cfg.anthropic_api_keys = []
            cfg.openai_api_keys = []
            cfg.deepseek_api_keys = []
            cfg.llm_model_list = []
            cfg.openai_base_url = None
            cfg.market_review_region = "cn"
            cfg.market_review_color_scheme = "green_up"
            cfg.report_language = "zh"
            cfg.generation_backend = "litellm"
            cfg.generation_fallback_backend = "litellm"
            mock_cfg.return_value = cfg
            mock_cfg2.return_value = cfg

            from src.analyzer import GeminiAnalyzer
            from src.market_analyzer import MarketAnalyzer

            analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
            analyzer._router = None
            analyzer._litellm_available = True
            analyzer._config_override = cfg
            analyzer.generate_text = MagicMock(return_value=return_value)

            ma = MarketAnalyzer.__new__(MarketAnalyzer)
            ma.analyzer = analyzer
            ma.config = cfg
            ma.profile = CN_PROFILE
            ma.strategy = get_market_strategy_blueprint("cn")
            ma.region = "cn"
            return ma

    def test_no_access_to_private_model_attribute(self):
        """generate_text() must be called; _model must never be accessed."""
        ma = self._make_market_analyzer_with_mock_generate_text("复盘结果")
        # Ensure _model attribute does not exist (simulates PR #494 state)
        assert not hasattr(ma.analyzer, "_model") or ma.analyzer._model is None, (
            "_model should not be set on the LiteLLM-based analyzer"
        )
        # generate_text is a MagicMock, so calling it won't crash
        result = ma.analyzer.generate_text("prompt")
        assert isinstance(result, str) and len(result) > 0
        ma.analyzer.generate_text.assert_called_once()

    def test_generate_text_none_falls_back_to_template(self):
        """generate_market_review() falls back to template when generate_text returns None."""
        from src.market_analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=5.0,
                    change_pct=0.15,
                )
            ],
        )
        result = ma.generate_market_review(overview, [])
        assert isinstance(result, str) and len(result) > 0
        ma.analyzer.generate_text.assert_called_once()

    def test_generation_backend_config_error_does_not_template_fallback(self):
        from src.llm.generation_backend import GenerationError
        from src.market_analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        ma.analyzer._config_override.generation_backend = "codex"
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=5.0,
                    change_pct=0.15,
                )
            ],
        )

        with patch.object(ma, "_generate_template_review", wraps=ma._generate_template_review) as template_review, \
             patch("src.market_analyzer.record_llm_run") as mock_record_llm_run:
            with pytest.raises(GenerationError) as exc_info:
                ma.generate_market_review(overview, [])

        assert exc_info.value.details["field"] == "GENERATION_BACKEND"
        assert exc_info.value.details["requested_backend"] == "codex"
        template_review.assert_not_called()
        ma.analyzer.generate_text.assert_not_called()
        mock_record_llm_run.assert_called_once()
        diagnostic = mock_record_llm_run.call_args.kwargs
        assert diagnostic["success"] is False
        assert diagnostic["call_type"] == "market_review"
        assert diagnostic["error_type"] == "GenerationError"
        assert "backend_not_configured" in str(diagnostic["error_message"])

    def test_local_backend_execution_error_does_not_template_fallback(self):
        from src.llm.generation_backend import GenerationError, GenerationErrorCode
        from src.market_analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        ma.analyzer.generate_text.side_effect = GenerationError(
            error_code=GenerationErrorCode.COMMAND_NOT_FOUND,
            stage="configuration",
            retryable=False,
            fallbackable=True,
            backend="codex_cli",
            provider="codex_cli",
            details={"reason": "executable_not_found"},
        )
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=5.0,
                    change_pct=0.15,
                )
            ],
        )

        with patch.object(ma, "_generate_template_review", wraps=ma._generate_template_review) as template_review:
            with pytest.raises(GenerationError) as exc_info:
                ma.generate_market_review(overview, [])

        assert exc_info.value.error_code is GenerationErrorCode.COMMAND_NOT_FOUND
        template_review.assert_not_called()

    def test_generation_backend_config_error_without_analyzer_does_not_template_fallback(self):
        from src.llm.generation_backend import GenerationError
        from src.market_analyzer import MarketOverview, MarketIndex

        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=5.0,
                    change_pct=0.15,
                )
            ],
        )
        cases = [
            ("generation_backend", "GENERATION_BACKEND"),
            ("generation_fallback_backend", "GENERATION_FALLBACK_BACKEND"),
        ]

        for attr_name, expected_field in cases:
            ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
            ma.analyzer = None
            ma.config.generation_backend = "litellm"
            ma.config.generation_fallback_backend = "litellm"
            setattr(ma.config, attr_name, "codex")

            with patch.object(ma, "_generate_template_review", wraps=ma._generate_template_review) as template_review, \
                 patch("src.market_analyzer.record_llm_run") as mock_record_llm_run:
                with pytest.raises(GenerationError) as exc_info:
                    ma.generate_market_review(overview, [])

            assert exc_info.value.details["field"] == expected_field
            assert exc_info.value.details["requested_backend"] == "codex"
            template_review.assert_not_called()
            mock_record_llm_run.assert_called_once()

    def test_market_review_uses_8192_max_tokens(self):
        """generate_market_review() should request a larger output budget to avoid truncation."""
        from src.market_analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="复盘结果")
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=5.0,
                    change_pct=0.15,
                )
            ],
        )

        result = ma.generate_market_review(overview, [])

        assert isinstance(result, str) and len(result) > 0
        ma.analyzer.generate_text.assert_called_once()
        _, kwargs = ma.analyzer.generate_text.call_args
        assert kwargs["max_tokens"] == 8192
        assert kwargs["temperature"] == 0.7

    def test_generate_template_review_uses_english_shell_for_cn_when_report_language_is_en(self):
        from src.market_analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        ma.config.report_language = "en"
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=12.0,
                    change_pct=0.36,
                )
            ],
            up_count=3200,
            down_count=1800,
            limit_up_count=88,
            limit_down_count=5,
            total_amount=14567.0,
            top_sectors=[{"name": "AI算力", "change_pct": 3.25}],
            bottom_sectors=[{"name": "煤炭", "change_pct": -1.12}],
        )

        result = ma.generate_market_review(overview, [])

        assert "A-share Market Recap" in result
        assert "### 1. Market Summary" in result
        assert "### 3. Breadth & Liquidity" in result
        assert "Turnover (CNY 100m)" in result
        assert "### 4. Sector Highlights" in result
        assert "### 6. Strategy Framework" in result
        assert "### 一、市场总结" not in result

    def test_generate_template_review_keeps_chinese_shell_for_us_when_report_language_is_default(self):
        from src.core.market_profile import US_PROFILE
        from src.core.market_strategy import get_market_strategy_blueprint
        from src.market_analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        ma.region = "us"
        ma.profile = US_PROFILE
        ma.strategy = get_market_strategy_blueprint("us")
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="SPX",
                    name="标普500",
                    current=5200.0,
                    change=-18.0,
                    change_pct=-0.35,
                )
            ],
        )

        result = ma.generate_market_review(overview, [])

        assert "## 2026-03-05 大盘复盘" in result
        assert "### 一、盘面总览" in result
        assert "今日美股市场整体呈现**小幅下跌**态势" in result
        assert "### 6. Strategy Framework" not in result
        assert "### 六、策略框架" in result
        assert "### 1. Market Summary" not in result
        assert "US Market Recap" not in result

    def test_inject_data_into_review_matches_english_headings(self):
        from src.market_analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="review")
        ma.config.report_language = "en"
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=12.0,
                    change_pct=0.36,
                    amount=145000000000.0,
                )
            ],
            up_count=3200,
            down_count=1800,
            flat_count=100,
            limit_up_count=88,
            limit_down_count=5,
            total_amount=14567.0,
            top_sectors=[{"name": "AI算力", "change_pct": 3.25}],
            bottom_sectors=[{"name": "煤炭", "change_pct": -1.12}],
        )
        review = """## 2026-03-05 A-share Market Recap

### 1. Market Summary
Summary text.

### 2. Index Commentary
Index text.

### 4. Sector Highlights
Sector text.
"""

        result = ma._inject_data_into_review(review, overview)

        assert "- **Market Signal**: 66/100 (constructive, risk-on)" in result
        assert "- **Breadth**: Advancers 3200 / Decliners 1800 / Flat 100;" in result
        assert "Turnover 14567 (CNY 100m)" in result
        assert "| Index | Last | Change % | Open | High | Low | Amplitude | Turnover (CNY 100m) |" in result
        assert "#### Leading Sectors" in result
        assert "| 1 | AI算力 | +3.25% |" in result
        assert "#### Lagging Sectors" in result
        assert "| 1 | 煤炭 | -1.12% |" in result

    def test_inject_data_into_review_matches_reference_style_chinese_headings(self):
        from src.market_analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="review")
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="000001",
                    name="上证指数",
                    current=3300.0,
                    change=12.0,
                    change_pct=0.36,
                    open=3288.0,
                    high=3312.0,
                    low=3276.0,
                    amount=145000000000.0,
                    amplitude=1.1,
                )
            ],
            up_count=3200,
            down_count=1800,
            flat_count=100,
            limit_up_count=88,
            limit_down_count=5,
            total_amount=14567.0,
            top_sectors=[{"name": "AI算力", "change_pct": 3.25}],
            bottom_sectors=[{"name": "煤炭", "change_pct": -1.12}],
        )
        news = [{"title": "AI算力板块走强", "snippet": "算力产业链延续活跃，成交额放大"}]
        review = """## 2026-03-05 大盘复盘

### 一、盘面总览
总结。

### 二、指数结构
指数。

### 三、板块主线
板块。

### 五、消息催化
新闻。
"""

        result = ma._inject_data_into_review(review, overview, news)

        assert "盘面信号" in result
        assert "66/100（偏暖，可进攻）" in result
        assert "绿灯（可进攻）" not in result
        assert "大盘红绿灯" not in result
        assert "green（可进攻）" not in result
        assert "信号依据" in result
        signal_line = next(line for line in result.splitlines() if "**盘面信号**" in line)
        drivers_line = next(line for line in result.splitlines() if "**信号依据**" in line)
        assert signal_line.startswith("- ")
        assert "66/100" in signal_line
        assert "█" not in result
        assert "░" not in result
        assert "盘面温度" not in drivers_line
        assert "操作建议" in result
        assert "盘面温度" not in result
        assert "| 上涨/下跌/平盘 | 3200 / 1800 / 100 |" in result
        assert "| 指数 | 最新 | 涨跌幅 | 开盘 | 最高 | 最低 | 振幅 | 成交额(亿) |" in result
        assert "| 上证指数 | 3300.00 | 🟢 +0.36% | 3288.00 | 3312.00 | 3276.00 | 1.10% | 1450 |" in result
        assert "#### 领涨板块 Top 5" in result
        assert "| 1 | AI算力 | +3.25% |" in result
        assert "#### 近三日市场线索" not in result
        assert "AI算力板块走强" not in result
        assert "新闻。" in result
        assert "算力产业链延续活跃" not in result

    def test_market_review_payload_sections_skip_top_report_title(self):
        from src.market_analyzer import MarketAnalyzer

        ma = MarketAnalyzer.__new__(MarketAnalyzer)
        sections = ma._split_report_sections("""## 2026-06-03 大盘复盘

> 今日指数分化。

### 一、盘面总览
正文
""")

        assert sections[0]["key"] == "overview"
        assert "今日指数分化" in sections[0]["markdown"]
        assert all(section["title"] != "2026-06-03 大盘复盘" for section in sections)

    def test_news_block_renders_title_source_and_link_only(self):
        from src.market_analyzer import MarketAnalyzer

        ma = MarketAnalyzer.__new__(MarketAnalyzer)
        ma.config = SimpleNamespace(report_language="zh")
        ma.region = "cn"
        long_snippet = (
            "复盘必读 2026-05-06 复盘的意义在于更清晰地把握市场脉搏，"
            "综合描述 A 股三大指数今日集体反弹，成交额放大，科技成长方向领涨。"
        )

        result = ma._build_news_block([
            {
                "title": "A股收评：科创50指数放量反弹涨5.47% 两市成交额重回3万亿元",
                "snippet": long_snippet,
                "source": "东方财富",
                "published_date": "2026-05-06",
                "url": "https://example.com/news/1",
            }
        ])

        assert "#### 近三日市场线索" in result
        assert "| 序号 |" not in result
        assert "摘要/线索片段" not in result
        assert "关注点" not in result
        assert "成交额放大" not in result
        assert (
            "- 1. [A股收评：科创50指数放量反弹涨5.47% 两市成交额重回3万亿元]"
            "(https://example.com/news/1)（东方财富 / 2026-05-06）"
        ) in result

    def test_news_block_uses_dash_when_source_metadata_missing(self):
        from src.market_analyzer import MarketAnalyzer

        ma = MarketAnalyzer.__new__(MarketAnalyzer)
        ma.config = SimpleNamespace(report_language="zh")
        ma.region = "cn"

        result = ma._build_news_block([
            {
                "title": "政策利好带动板块活跃",
                "snippet": "相关主题成交放大",
            }
        ])

        assert "- 1. 政策利好带动板块活跃" in result
        assert "相关主题成交放大" not in result
        assert "| 1 | 政策利好带动板块活跃 |" not in result

    def test_news_block_uses_english_metadata_punctuation(self):
        from src.market_analyzer import MarketAnalyzer

        ma = MarketAnalyzer.__new__(MarketAnalyzer)
        ma.config = SimpleNamespace(report_language="en")
        ma.region = "us"

        result = ma._build_news_block([
            {
                "title": "Chip stocks rally as AI demand improves",
                "source": "Reuters",
                "published_date": "2026-05-06",
                "url": "https://example.com/news/2",
            }
        ])

        assert "#### News Catalysts" in result
        assert (
            "- 1. [Chip stocks rally as AI demand improves](https://example.com/news/2)"
            " (Reuters / 2026-05-06)"
        ) in result
        assert "（Reuters" not in result

    def test_review_prompt_caps_news_url_context(self):
        from src.market_analyzer import MarketOverview

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="review")
        long_url = "https://example.com/redirect?" + "utm_campaign=" + ("x" * 420)

        prompt = ma._build_review_prompt(
            MarketOverview(date="2026-05-06"),
            [
                {
                    "title": "A股收评：指数放量反弹",
                    "snippet": "科技成长方向领涨",
                    "source": "测试来源",
                    "published_date": "2026-05-06",
                    "url": long_url,
                }
            ],
        )

        assert long_url not in prompt
        assert "URL: https://example.com/redirect?" in prompt
        assert ("x" * 220) not in prompt

    def test_market_light_snapshot_marks_defensive_market_red(self):
        from src.market_analyzer import MarketIndex, MarketOverview

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="review")
        overview = MarketOverview(
            date="2026-03-06",
            indices=[
                MarketIndex(code="000001", name="上证指数", current=3200, change_pct=-1.8),
                MarketIndex(code="399001", name="深证成指", current=9800, change_pct=-2.4),
            ],
            up_count=900,
            down_count=4100,
            limit_up_count=10,
            limit_down_count=80,
            total_amount=9800.0,
        )

        snapshot = ma.build_market_light_snapshot(overview)

        assert snapshot["status"] == "red"
        assert snapshot["label"] == "偏防守"
        assert snapshot["score"] < 40
        assert snapshot["region"] == "cn"
        assert snapshot["trade_date"] == "2026-03-06"
        assert snapshot["data_quality"] == "ok"
        assert snapshot["dimensions"]["breadth"]["available"] is True
        assert snapshot["dimensions"]["index"]["available"] is True
        assert snapshot["dimensions"]["limit"]["available"] is True
        assert any("亏钱效应" in reason for reason in snapshot["reasons"])

    def test_market_light_snapshot_uses_english_labels_and_reasons(self):
        from src.market_analyzer import MarketIndex, MarketOverview

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="review")
        ma.config.report_language = "en"
        overview = MarketOverview(
            date="2026-03-06",
            indices=[
                MarketIndex(code="000001", name="SSE Composite", current=3200, change_pct=-1.8),
                MarketIndex(code="399001", name="SZSE Component", current=9800, change_pct=-2.4),
            ],
            up_count=900,
            down_count=4100,
            limit_up_count=10,
            limit_down_count=80,
            total_amount=9800.0,
        )

        snapshot = ma.build_market_light_snapshot(overview)

        assert snapshot["status"] == "red"
        assert snapshot["label"] == "risk-off"
        assert snapshot["guidance"] == (
            "Risk is elevated; prioritize drawdown control and avoid chasing weak rebounds."
        )
        assert not any(reason.startswith("market temperature ") for reason in snapshot["reasons"])
        assert any(
            reason.startswith("advancers ratio ") and "downside pressure dominates" in reason
            for reason in snapshot["reasons"]
        )

    def test_market_light_snapshot_marks_us_without_breadth_as_partial(self):
        from src.core.market_profile import US_PROFILE
        from src.market_analyzer import MarketIndex, MarketOverview

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="review")
        ma.region = "us"
        ma.profile = US_PROFILE
        ma.config.report_language = "en"
        overview = MarketOverview(
            date="2026-03-06",
            indices=[MarketIndex(code="SPX", name="S&P 500", current=5000, change_pct=0.5)],
        )

        snapshot = ma.build_market_light_snapshot(overview)

        assert snapshot["region"] == "us"
        assert snapshot["data_quality"] == "partial"
        assert snapshot["dimensions"]["breadth"] == {"score": 50, "available": False}
        assert snapshot["dimensions"]["index"]["available"] is True
        assert snapshot["dimensions"]["limit"] == {"score": 50, "available": False}

    def test_market_review_payload_omits_breadth_for_markets_without_stats(self):
        from src.core.market_profile import US_PROFILE
        from src.market_analyzer import MarketIndex, MarketOverview

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="复盘结果")
        ma.region = "us"
        ma.profile = US_PROFILE

        payload = ma.build_market_review_payload(
            MarketOverview(
                date="2026-03-18",
                indices=[
                    MarketIndex(code="SPX", name="S&P 500", current=5200.0, change_pct=0.6),
                ],
                up_count=1000,
                down_count=400,
                limit_up_count=10,
                limit_down_count=0,
                total_amount=9800.0,
            ),
            [],
            "美股复盘报告",
            market_light_snapshot={"dimensions": {"breadth": {"score": 60, "available": True}}},
        )

        assert "breadth" not in payload
        assert payload["indices"][0]["code"] == "SPX"

    def test_market_review_payload_omits_breadth_for_cn_market_without_available_stats(self):
        from src.market_analyzer import MarketIndex, MarketOverview

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="复盘结果")
        payload = ma.build_market_review_payload(
            MarketOverview(
                date="2026-03-18",
                indices=[
                    MarketIndex(code="000001", name="上证指数", current=3200.0, change_pct=0.6),
                ],
                up_count=0,
                down_count=0,
                flat_count=0,
                limit_up_count=0,
                limit_down_count=0,
                total_amount=0.0,
            ),
            [],
            "A股复盘报告",
            market_light_snapshot={"dimensions": {"breadth": {"score": 55, "available": False}}},
        )

        assert "breadth" not in payload
        assert payload["indices"][0]["name"] == "上证指数"

    def test_market_review_payload_includes_breadth_only_when_stats_available(self):
        from src.market_analyzer import MarketIndex, MarketOverview

        ma = self._make_market_analyzer_with_mock_generate_text(return_value="复盘结果")
        payload = ma.build_market_review_payload(
            MarketOverview(
                date="2026-03-18",
                indices=[
                    MarketIndex(code="000001", name="上证指数", current=3200.0, change_pct=0.6),
                ],
                up_count=1200,
                down_count=900,
                flat_count=60,
                limit_up_count=12,
                limit_down_count=4,
                total_amount=12345.0,
            ),
            [],
            "A股复盘报告",
            market_light_snapshot={"dimensions": {"breadth": {"score": 62, "available": True}}},
        )

        assert payload["breadth"] is not None
        assert payload["breadth"]["up_count"] == 1200
        assert payload["breadth"]["down_count"] == 900
        assert payload["breadth"]["limit_up_count"] == 12
        assert payload["breadth"]["total_amount"] == 12345.0

    def test_us_english_indices_do_not_label_turnover_as_cny(self):
        from src.core.market_profile import US_PROFILE
        from src.core.market_strategy import get_market_strategy_blueprint
        from src.market_analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        ma.config.report_language = "en"
        ma.region = "us"
        ma.profile = US_PROFILE
        ma.strategy = get_market_strategy_blueprint("us")
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(
                    code="SPX",
                    name="S&P 500",
                    current=5200.0,
                    change=35.0,
                    change_pct=0.68,
                    amount=9876543210.0,
                )
            ],
        )

        result = ma._build_indices_block(overview)

        assert "CNY 100m" not in result
        assert "Turnover (USD bn)" in result
        assert "| S&P 500 | 5200.00 |" in result

    def test_indices_block_uses_configured_red_up_color_scheme(self):
        from src.market_analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        ma.config.market_review_color_scheme = "red_up"
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(code="000001", name="上证指数", current=3200.0, change_pct=0.68),
                MarketIndex(code="399001", name="深证成指", current=9800.0, change_pct=-0.42),
                MarketIndex(code="399006", name="创业板指", current=2100.0, change_pct=0.0),
            ],
        )

        result = ma._build_indices_block(overview)

        assert "| 上证指数 | 3200.00 | 🔴 +0.68% |" in result
        assert "| 深证成指 | 9800.00 | 🟢 -0.42% |" in result
        assert "| 创业板指 | 2100.00 | ⚪ +0.00% |" in result

    def test_indices_block_keeps_green_up_default_color_scheme(self):
        from src.market_analyzer import MarketOverview, MarketIndex

        ma = self._make_market_analyzer_with_mock_generate_text(return_value=None)
        overview = MarketOverview(
            date="2026-03-05",
            indices=[
                MarketIndex(code="000001", name="上证指数", current=3200.0, change_pct=0.68),
                MarketIndex(code="399001", name="深证成指", current=9800.0, change_pct=-0.42),
            ],
        )

        result = ma._build_indices_block(overview)

        assert "| 上证指数 | 3200.00 | 🟢 +0.68% |" in result
        assert "| 深证成指 | 9800.00 | 🔴 -0.42% |" in result

    def test_no_private_attribute_access_in_market_analyzer_source(self):
        """Static guard: market_analyzer.py must not access private analyzer attrs."""
        import ast
        import pathlib

        src = pathlib.Path("src/market_analyzer.py").read_text()
        tree = ast.parse(src)
        forbidden = {
            "_model", "_router", "_use_openai", "_use_anthropic",  # historical
            "_call_litellm",      # use generate_text() instead
            "_litellm_available", # use is_available() instead
        }

        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in forbidden:
                    violations.append(node.attr)

        assert violations == [], (
            f"market_analyzer.py still accesses private Analyzer attributes: {violations}"
        )
