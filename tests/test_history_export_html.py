# -*- coding: utf-8 -*-
"""Tests for standalone printable HTML history report export endpoint."""

from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from api.deps import get_database_manager
from api.v1.endpoints import history as history_endpoint


class _FakeHistoryService:
    def __init__(self, result, markdown="# Report"):
        self._result = result
        self._markdown = markdown

    def resolve_and_get_detail(self, record_id):
        if str(record_id) == "missing":
            return None
        return self._result

    def get_markdown_report(self, record_id):
        return self._markdown


def _sample_detail():
    return {
        "id": 42,
        "query_id": "q-42",
        "stock_code": "600519",
        "storage_stock_code": "600519",
        "stock_name": "<script>alert(1)</script>贵州茅台",
        "report_type": "detailed",
        "report_language": "zh",
        "created_at": "2026-11-22T10:15:00",
        "model_used": "gemini/gemini-2.5-flash",
        "analysis_summary": "主升趋势稳健",
        "operation_advice": "买入",
        "action": "buy",
        "trend_prediction": "看多",
        "sentiment_score": 84,
        "ideal_buy": "1500",
        "secondary_buy": "1460",
        "stop_loss": "1420",
        "take_profit": "1680",
        "context_snapshot": {"realtime_quote": {"price": 1525.0, "pct_chg": 1.65, "volume_ratio": 1.35, "pe_ratio": 24.5}},
        "raw_result": {
            "dashboard": {
                "core_conclusion": {
                    "one_sentence": "回踩买点区间具性价比",
                    "position_advice": {"no_position": "分批介入", "has_position": "继续持有"},
                },
                "intelligence": {
                    "risk_alerts": ["<img src=x onerror=alert(9)>短期估值波动"],
                    "positive_catalysts": ["分红预期提升"],
                },
                "battle_plan": {
                    "action_checklist": ["✅ 均线多头排列", "⚠️ 留意量能变化"],
                },
                "signal_attribution": {
                    "technical_indicators": 45,
                    "news_sentiment": 20,
                    "fundamentals": 25,
                    "market_conditions": 10,
                    "strongest_bullish_signal": "突破 20 日均线",
                },
            }
        },
    }


def _make_client(monkeypatch, result, markdown="# Report"):
    svc = _FakeHistoryService(result, markdown)
    monkeypatch.setattr(history_endpoint, "HistoryService", lambda _db: svc)
    app = FastAPI()
    app.include_router(history_endpoint.router, prefix="/api/v1/history")
    app.dependency_overrides[get_database_manager] = lambda: object()
    return TestClient(app), svc


def test_export_history_html_attachment_and_csp(monkeypatch):
    client, svc = _make_client(monkeypatch, _sample_detail())
    svc.get_markdown_report = lambda _id: (_ for _ in ()).throw(AssertionError("should not generate markdown for stock HTML export"))
    resp = client.get("/api/v1/history/42/export-html")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert resp.headers["content-disposition"] == 'attachment; filename="dsa-report-600519-42.html"'
    assert resp.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "<script>" not in resp.text
    assert 'http-equiv="Content-Security-Policy"' in resp.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text
    assert "&lt;img src=x onerror=alert(9)&gt;" in resp.text
    assert "@media print" in resp.text
    assert "--bg: #ffffff;" in resp.text
    assert '<svg class="ruler-svg"' in resp.text
    assert "1.35" in resp.text
    assert "24.50" in resp.text


def test_export_history_html_inline_mode(monkeypatch):
    client, _ = _make_client(monkeypatch, _sample_detail())
    resp = client.get("/api/v1/history/42/export-html?inline=true")

    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == "inline"


def test_export_history_html_market_review_and_404(monkeypatch):
    market_detail = {
        "id": 88,
        "stock_code": "cn",
        "stock_name": "A股市场复盘",
        "report_type": "market_review",
        "report_language": "zh",
        "created_at": "2026-11-22T15:30:00",
        "sentiment_score": 68,
        "context_snapshot": {"market_review_payload": {"root_title": "2026-11-22 A股盘后复盘"}},
        "raw_result": {},
    }
    client, _ = _make_client(
        monkeypatch,
        market_detail,
        markdown="# 2026-11-22 A股盘后复盘\n\n<script>bad()</script>\n\n[Click](javascript:alert(1))\n\n[Bad](java&#x09;script:alert(1))\n\n## 核心指数\n\n上证指数收涨。",
    )
    resp = client.get("/api/v1/history/88/export-html")
    assert resp.status_code == 200
    assert "2026-11-22 A股盘后复盘" in resp.text
    assert "上证指数收涨" in resp.text
    assert "<script>" not in resp.text
    assert "javascript:" not in resp.text
    assert "alert(1)" not in resp.text

    not_found = client.get("/api/v1/history/missing/export-html")
    assert not_found.status_code == 404


def test_export_history_html_renders_structured_strategy_synthesis(monkeypatch):
    detail = _sample_detail()
    detail["raw_result"]["dashboard"]["strategy_synthesis"] = {
        "final_signal": "buy",
        "consensus_level": "medium",
        "conflict_severity": "medium",
        "conflict_count": 1,
        "confidence": 0.81,
        "supporting_skills": [
            {"skill_id": "bull_trend", "signal": "buy", "confidence": 0.86},
        ],
        "opposing_skills": [
            {"skill_id": "<img src=x onerror=alert(2)>", "signal": "sell", "confidence": 0.75},
        ],
        "summary_params": {"opinion_count": 2, "invalid_opinion_count": 1},
        "deliberation": {"summary": {"minority_view_preserved": True}},
    }
    client, _ = _make_client(monkeypatch, detail)
    resp = client.get("/api/v1/history/42/export-html")

    assert resp.status_code == 200
    assert "多策略综合" in resp.text
    assert "默认多头趋势 · 买入 · 86%" in resp.text
    assert "冲突: 中 (1)" in resp.text
    assert "置信度: 81%" in resp.text
    assert "已保留高置信度少数派异议" in resp.text
    assert "另有 1 个策略未能产出有效信号" in resp.text
    assert "<img src=x onerror=alert(2)>" not in resp.text
    assert "&lt;img src=x onerror=alert(2)&gt;" in resp.text
