# -*- coding: utf-8 -*-

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.v1.endpoints import history as history_endpoint
from src.share_image import DEFAULT_XIAOHONGSHU_HANDLE, DEFAULT_XIAOHONGSHU_QR_PATH


class _FakeHistoryService:
    def __init__(self, result, markdown="# 中钨高新 000657 分析报告"):
        self.result = result
        self.markdown = markdown

    def resolve_and_get_detail(self, record_id):
        return self.result

    def get_markdown_report(self, record_id):
        return self.markdown


def _patch_service(monkeypatch, result, markdown="# 中钨高新 000657 分析报告"):
    service = _FakeHistoryService(result, markdown)
    monkeypatch.setattr(history_endpoint, "HistoryService", lambda _db: service)
    monkeypatch.setattr(
        history_endpoint,
        "get_config",
        lambda: SimpleNamespace(
            markdown_to_image_max_chars=15000,
            md2img_engine="markdown-to-file",
        ),
    )
    return service


def test_history_share_image_returns_png_with_stock_payload(monkeypatch):
    raw_result = {"code": "000657", "name": "中钨高新", "dashboard": {}}
    _patch_service(
        monkeypatch,
        {
            "id": 17,
            "report_type": "detailed",
            "raw_result": raw_result,
            "context_snapshot": {},
        },
    )
    calls = []

    def fake_markdown_to_image(markdown, **kwargs):
        calls.append((markdown, kwargs))
        return b"\x89PNG\r\n\x1a\nposter"

    monkeypatch.setattr(history_endpoint, "markdown_to_image", fake_markdown_to_image)

    response = history_endpoint.get_history_share_image("17", db_manager=object())

    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert response.body.startswith(b"\x89PNG")
    assert response.headers["content-disposition"] == 'attachment; filename="dsa-report-17.png"'
    assert calls[0][1]["structured_payload"] is raw_result
    assert calls[0][1]["max_chars"] == 15000


def test_history_share_image_prefers_market_review_payload(monkeypatch):
    market_payload = {"kind": "market_review", "date": "2026-08-01"}
    _patch_service(
        monkeypatch,
        {
            "id": 18,
            "report_type": "market_review",
            "raw_result": {"raw_response": "market report"},
            "context_snapshot": {"market_review_payload": market_payload},
        },
        markdown="# A股市场复盘",
    )
    captured = {}

    def fake_markdown_to_image(markdown, **kwargs):
        captured.update(kwargs)
        return b"png"

    monkeypatch.setattr(history_endpoint, "markdown_to_image", fake_markdown_to_image)

    history_endpoint.get_history_share_image("18", db_manager=object())

    assert captured["structured_payload"] is market_payload


def test_history_share_image_html_returns_desktop_poster_with_restrictive_csp(monkeypatch):
    raw_result = {"code": "000657", "name": "中钨高新", "dashboard": {}}
    _patch_service(
        monkeypatch,
        {
            "id": 20,
            "report_type": "detailed",
            "raw_result": raw_result,
            "context_snapshot": {},
        },
    )
    captured = {}

    def fake_build_share_image_html(markdown, **kwargs):
        captured["markdown"] = markdown
        captured.update(kwargs)
        return "<!DOCTYPE html><html><body>poster</body></html>"

    monkeypatch.setattr(
        history_endpoint,
        "build_share_image_html",
        fake_build_share_image_html,
    )

    response = history_endpoint.get_history_share_image_html("20", db_manager=object())

    assert response.status_code == 200
    assert response.media_type == "text/html"
    assert b"poster" in response.body
    assert captured["structured_payload"] is raw_result
    assert captured["branding"].xiaohongshu_handle == DEFAULT_XIAOHONGSHU_HANDLE
    assert captured["branding"].xiaohongshu_id == ""
    assert captured["branding"].xiaohongshu_qr_path == DEFAULT_XIAOHONGSHU_QR_PATH
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    )


def test_history_share_image_html_rejects_reports_over_configured_limit(monkeypatch):
    _patch_service(
        monkeypatch,
        {
            "id": 21,
            "report_type": "detailed",
            "raw_result": {"code": "000657"},
            "context_snapshot": {},
        },
        markdown="x" * 15001,
    )

    with pytest.raises(HTTPException) as exc_info:
        history_endpoint.get_history_share_image_html("21", db_manager=object())

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail["error"] == "share_image_too_large"


def test_history_share_image_reports_renderer_unavailable(monkeypatch):
    _patch_service(
        monkeypatch,
        {
            "id": 19,
            "report_type": "detailed",
            "raw_result": {"code": "000657"},
            "context_snapshot": {},
        },
    )
    monkeypatch.setattr(history_endpoint, "markdown_to_image", lambda *_args, **_kwargs: None)

    with pytest.raises(HTTPException) as exc_info:
        history_endpoint.get_history_share_image("19", db_manager=object())

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error"] == "share_image_unavailable"


def test_history_share_image_returns_not_found(monkeypatch):
    _patch_service(monkeypatch, None)

    with pytest.raises(HTTPException) as exc_info:
        history_endpoint.get_history_share_image("missing", db_manager=object())

    assert exc_info.value.status_code == 404
