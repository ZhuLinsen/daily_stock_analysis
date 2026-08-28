# -*- coding: utf-8 -*-
"""Tests for the master debate service."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from src.config import Config
from src.services.master_debate_service import (
    PERSONAS,
    MasterDebateError,
    MasterDebateService,
    aggregate_debate,
    build_debate_prompt,
    extract_json,
    normalize_stance,
    parse_persona_outputs,
)
from src.storage import DatabaseManager

_FENCE = chr(96) * 3


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(tmp_path / "master_debate.db")
    Config.reset_instance()
    DatabaseManager.reset_instance()
    db = DatabaseManager.get_instance()
    try:
        yield db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


def _persona_outputs():
    return [
        {"persona_id": "warren_buffett", "stance": "bull", "confidence": 0.8,
         "thesis": "估值便宜", "key_points": ["护城河深", "现金流稳"], "key_levels": {}, "risk": "低估持续"},
        {"persona_id": "george_soros", "stance": "bear", "confidence": 0.6,
         "thesis": "预期透支", "key_points": ["拐点临近"], "key_levels": {}, "risk": "反弹"},
        {"persona_id": "jesse_livermore", "stance": "bull", "confidence": 0.7,
         "thesis": "趋势向上", "key_points": ["突破关键位"], "key_levels": {}, "risk": "假突破"},
    ]


def test_persona_catalog_complete():
    ids = {p.id for p in PERSONAS}
    assert ids == {
        "warren_buffett", "george_soros", "jesse_livermore",
        "peter_lynch", "william_oneil", "chan_theory",
    }
    assert all(p.name and p.philosophy and p.lens for p in PERSONAS)


def test_normalize_stance():
    assert normalize_stance("bull") == "bull"
    assert normalize_stance("看空") == "bear"
    assert normalize_stance("hold") == "neutral"
    assert normalize_stance("unknown") == "neutral"


def test_extract_json_from_fences():
    fenced = _FENCE + "json\n" + json.dumps({"personas": []}) + "\n" + _FENCE
    assert extract_json(fenced) == {"personas": []}


def test_parse_persona_outputs_normalizes_and_filters():
    payload = {
        "personas": [
            {"persona_id": "warren_buffett", "stance": "看多", "confidence": 0.9,
             "thesis": "好公司", "key_points": ["a", "b"], "key_levels": {"support": 10}, "risk": "r"},
            {"persona_id": "unknown_persona", "stance": "bull"},
            {"persona_id": "chan_theory", "stance": "neutral", "confidence": 0.4,
             "thesis": "结构未明", "key_points": [], "risk": ""},
        ]
    }
    outputs = parse_persona_outputs(json.dumps(payload))
    assert len(outputs) == 2  # unknown persona filtered out
    assert outputs[0]["stance"] == "bull"
    assert outputs[0]["name"] == "巴菲特"


def test_aggregate_debate_unanimous():
    outputs = _persona_outputs()
    result = aggregate_debate(outputs)
    assert result["bull_count"] == 2
    assert result["bear_count"] == 1
    assert result["consensus"] == "bull"
    assert result["divergence"] == 33  # 100 * (1 - 2/3)
    assert result["conviction"] == 67


def test_aggregate_debate_tie_is_neutral():
    outputs = [
        {"stance": "bull", "confidence": 0.5, "key_points": ["a"], "name": "x", "thesis": ""},
        {"stance": "bear", "confidence": 0.5, "key_points": ["b"], "name": "y", "thesis": ""},
    ]
    result = aggregate_debate(outputs)
    assert result["consensus"] == "neutral"
    assert result["divergence"] == 50


def test_aggregate_debate_empty():
    result = aggregate_debate([])
    assert result["consensus"] == "neutral"
    assert result["divergence"] == 0


def test_build_debate_prompt_contains_all_personas():
    prompt = build_debate_prompt("600519", "贵州茅台", "cn", "上下文")
    assert "600519" in prompt
    assert "巴菲特" in prompt and "缠论" in prompt
    assert "persona_id" in prompt


def test_run_debate_with_injected_generator_persists(isolated_db):
    service = MasterDebateService(db_manager=isolated_db)
    fake_raw = json.dumps({
        "personas": [
            {"persona_id": "warren_buffett", "stance": "bull", "confidence": 0.8,
             "thesis": "t1", "key_points": ["k1"], "risk": "r"},
            {"persona_id": "george_soros", "stance": "bear", "confidence": 0.6,
             "thesis": "t2", "key_points": ["k2"], "risk": "r"},
            {"persona_id": "jesse_livermore", "stance": "bull", "confidence": 0.7,
             "thesis": "t3", "key_points": ["k3"], "risk": "r"},
            {"persona_id": "peter_lynch", "stance": "bull", "confidence": 0.5,
             "thesis": "t4", "key_points": [], "risk": "r"},
            {"persona_id": "william_oneil", "stance": "neutral", "confidence": 0.4,
             "thesis": "t5", "key_points": [], "risk": "r"},
            {"persona_id": "chan_theory", "stance": "bull", "confidence": 0.9,
             "thesis": "t6", "key_points": ["k6"], "risk": "r"},
        ]
    })

    result = service.run_debate(
        code="600519", name="贵州茅台", market="cn",
        generate_text=lambda _prompt: fake_raw,
    )
    assert result["bull_count"] == 4
    assert result["consensus"] == "bull"
    assert result["id"] is not None
    assert len(result["personas"]) == 6

    records, total = service.list_records(code="600519")
    assert total == 1
    assert records[0]["divergence"] == result["divergence"]


def test_run_debate_retries_once_on_empty_response(isolated_db):
    service = MasterDebateService(db_manager=isolated_db)
    fake_raw = json.dumps({
        "personas": [
            {"persona_id": "warren_buffett", "stance": "bull", "confidence": 0.8,
             "thesis": "t1", "key_points": ["k1"], "risk": "r"},
        ]
    })
    calls = []

    def flaky(_prompt):
        calls.append(_prompt)
        if len(calls) == 1:
            return None  # 第一次空响应，重试后成功
        return fake_raw

    result = service.run_debate(code="600519", name="贵州茅台", market="cn", generate_text=flaky)
    assert len(calls) == 2
    assert result["bull_count"] == 1
    assert result["consensus"] == "bull"


def test_run_debate_empty_after_retry_raises_clear_error(isolated_db):
    service = MasterDebateService(db_manager=isolated_db)

    with pytest.raises(MasterDebateError, match="空内容"):
        service.run_debate(
            code="600519", name="贵州茅台", market="cn",
            generate_text=lambda _prompt: None,
        )


def test_run_debate_llm_exception_becomes_clear_error_not_500(isolated_db):
    service = MasterDebateService(db_manager=isolated_db)

    def broken(_prompt):
        raise RuntimeError("All LLM models failed (tried 1 model(s))")

    with pytest.raises(MasterDebateError, match="LLM 调用失败.*All LLM models failed"):
        service.run_debate(code="600519", name="贵州茅台", market="cn", generate_text=broken)


def test_run_debate_falls_back_to_no_context_on_failure(isolated_db):
    service = MasterDebateService(db_manager=isolated_db)
    fake_raw = json.dumps({
        "personas": [
            {"persona_id": "chan_theory", "stance": "bear", "confidence": 0.7,
             "thesis": "t", "key_points": [], "risk": "r"},
        ]
    })
    calls = []

    def long_prompt_breaks(prompt):
        calls.append("分析摘要" in prompt)
        if "分析摘要" in prompt:  # 带上下文的长 prompt -> 空响应
            return None
        return fake_raw

    result = service.run_debate(
        code="600519", name="贵州茅台", market="cn",
        context="分析摘要：很长的分析内容……" * 50,
        generate_text=long_prompt_breaks,
    )
    assert calls == [True, True, False]  # 带上下文两次空响应后，降级为无上下文成功
    assert result["bear_count"] == 1
    assert result["consensus"] == "bear"


def test_default_generator_uses_current_analyzer():
    analyzer = MagicMock()
    analyzer.generate_text.return_value = '{"personas": []}'

    with patch("src.analyzer.GeminiAnalyzer", return_value=analyzer) as analyzer_cls:
        result = MasterDebateService.__new__(MasterDebateService)._default_generate_text("prompt")

    analyzer_cls.assert_called_once_with()
    analyzer.generate_text.assert_called_once_with(
        "prompt",
        max_tokens=4096,
        temperature=0.6,
    )
    assert result == '{"personas": []}'
