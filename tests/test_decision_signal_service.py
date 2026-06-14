# -*- coding: utf-8 -*-
"""Service tests for DecisionSignal P1."""

from __future__ import annotations

import os
import subprocess
import sys
from math import inf, nan
from pathlib import Path

import pytest

from src.config import Config
from src.services.decision_signal_service import DecisionSignalService, DecisionSignalStorageError
from src.storage import DatabaseManager, DecisionSignalRecord
from src.utils.sanitize import sanitize_decision_signal_text, sanitize_diagnostic_text


def test_service_imports_without_api_bootstrap() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.services.decision_signal_service import DecisionSignalService; "
            "print(DecisionSignalService.__name__)",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "DecisionSignalService" in result.stdout


@pytest.fixture()
def isolated_db(tmp_path):
    old_database_path = os.environ.get("DATABASE_PATH")
    db_path = tmp_path / "decision_signal_service.db"
    os.environ["DATABASE_PATH"] = str(db_path)
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


def _payload(**overrides):
    payload = {
        "stock_code": "SH600519",
        "stock_name": "贵州茅台",
        "market": "cn",
        "source_type": "analysis",
        "source_report_id": 101,
        "trace_id": "trace-101",
        "market_phase": "intraday",
        "trigger_source": "api",
        "action": "buy",
        "confidence": 0.72,
        "score": 83,
        "horizon": "3d",
        "reason": "放量突破",
    }
    payload.update(overrides)
    return payload


def test_service_normalizes_fields_and_partial_plan_quality(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)

    result = service.create_signal(
        _payload(
            entry_low="1680.5",
            stop_loss="1600",
        )
    )

    item = result["item"]
    assert result["created"] is True
    assert item["stock_code"] == "600519"
    assert item["market"] == "cn"
    assert item["action"] == "buy"
    assert item["action_label"] == "买入"
    assert item["confidence"] == 0.72
    assert item["score"] == 83
    assert item["entry_low"] == 1680.5
    assert item["stop_loss"] == 1600.0
    assert item["plan_quality"] == "partial"


def test_service_plan_quality_slots_and_explicit_override(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)

    minimal = service.create_signal(_payload(source_report_id=201, trace_id="trace-201", entry_low=1680))
    assert minimal["item"]["plan_quality"] == "minimal"

    complete = service.create_signal(
        _payload(
            source_report_id=202,
            trace_id="trace-202",
            entry_low=1680,
            entry_high=1700,
            stop_loss=1600,
            target_price=1850,
            invalidation="跌破 1600",
        )
    )
    assert complete["item"]["plan_quality"] == "complete"

    explicit = service.create_signal(
        _payload(
            source_report_id=203,
            trace_id="trace-203",
            plan_quality="unknown",
            entry_low=1680,
            stop_loss=1600,
            target_price=1850,
            invalidation="跌破 1600",
        )
    )
    assert explicit["item"]["plan_quality"] == "unknown"


def test_service_rejects_invalid_enums_and_ranges(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)

    with pytest.raises(ValueError, match="market"):
        service.create_signal(_payload(market="jp"))
    with pytest.raises(ValueError, match="action"):
        service.create_signal(_payload(action="strong buy"))
    with pytest.raises(ValueError, match="confidence"):
        service.create_signal(_payload(confidence=1.1))
    with pytest.raises(ValueError, match="score"):
        service.create_signal(_payload(score=101))
    with pytest.raises(ValueError, match="trigger_source"):
        service.create_signal(_payload(trigger_source="x" * 65))
    with pytest.raises(ValueError, match="trace_id"):
        service.create_signal(_payload(trace_id="x" * 65))
    with pytest.raises(ValueError, match="source_agent"):
        service.create_signal(_payload(source_agent="x" * 65))
    with pytest.raises(ValueError, match="stock_name"):
        service.create_signal(_payload(stock_name="x" * 65))
    with pytest.raises(ValueError, match="action_label"):
        service.create_signal(_payload(action_label="x" * 33))


def test_service_rejects_invalid_price_plan_values(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)

    invalid_cases = [
        {"entry_low": -1},
        {"entry_high": 0},
        {"stop_loss": nan},
        {"target_price": inf},
        {"entry_low": "not-a-number"},
    ]
    for index, overrides in enumerate(invalid_cases, start=1):
        with pytest.raises(ValueError):
            service.create_signal(_payload(source_report_id=300 + index, trace_id=f"trace-price-{index}", **overrides))

    with pytest.raises(ValueError, match="entry_low"):
        service.create_signal(_payload(source_report_id=306, trace_id="trace-price-range", entry_low=1700, entry_high=1600))


def test_decision_signal_sanitizer_redacts_sensitive_url_queries_without_url_tail_leaks() -> None:
    sanitized = sanitize_decision_signal_text(
        "plain https://news.example.com/article?id=1 "
        "signed https://news.example.com/article?token=abc&id=1 "
        "auth https://news.example.com/article?auth_token=abc&id=2 "
        "api https://news.example.com/article?api-token=abc&id=3 "
        "userinfo https://user:pass@example.com/path "
        "fragment https://news.example.com/cb#access_token=abc "
        "slack https://hooks.slack.com/services/T000/B000/abc123 "
        "feishu https://open.feishu.cn/open-apis/bot/v2/hook/abcdef123456 "
        "wecom https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdef"
    )

    assert "https://news.example.com/article?id=1" in sanitized
    assert sanitized.count("[REDACTED_URL]") == 8
    assert "token=abc" not in sanitized
    assert "auth_token=abc" not in sanitized
    assert "api-token=abc" not in sanitized
    assert "user:pass" not in sanitized
    assert "hooks.slack.com" not in sanitized
    assert "open.feishu.cn" not in sanitized
    assert "qyapi.weixin.qq.com" not in sanitized
    assert "]&id=" not in sanitized


@pytest.mark.parametrize(
    ("raw_text", "expected_text", "leaked_fragments"),
    [
        (
            "auth Bearer abcdef0123456789 next",
            "auth Bearer [REDACTED] next",
            ("abcdef0123456789", "0123456789"),
        ),
        (
            "jwt Bearer header.payload:signature next",
            "jwt Bearer [REDACTED] next",
            ("header.payload:signature", "payload:signature"),
        ),
        (
            "base64 Bearer abc+/def==, next",
            "base64 Bearer [REDACTED], next",
            ("abc+/def==", "+/def==", "def=="),
        ),
        (
            "semicolon Bearer abc+/def==; next",
            "semicolon Bearer [REDACTED]; next",
            ("abc+/def==", "+/def==", "def=="),
        ),
        (
            "ampersand Bearer abc+/def==&next=1",
            "ampersand Bearer [REDACTED]&next=1",
            ("abc+/def==", "+/def==", "def=="),
        ),
    ],
)
def test_decision_signal_sanitizer_redacts_entire_bearer_token_matrix(
    raw_text,
    expected_text,
    leaked_fragments,
) -> None:
    sanitized = sanitize_decision_signal_text(raw_text)

    assert expected_text in sanitized
    for leaked in leaked_fragments:
        assert leaked not in sanitized


@pytest.mark.parametrize(
    ("raw_text", "expected_text", "leaked_fragments"),
    [
        (
            "basic Authorization: Basic dXNlcjpwYXNz next",
            "basic Authorization: [REDACTED] next",
            ("dXNlcjpwYXNz", "pwYXNz"),
        ),
        (
            "token Authorization: Token abc+/def==; next",
            "token Authorization: [REDACTED]; next",
            ("abc+/def==", "+/def==", "def=="),
        ),
        (
            "assignment authorization=secret-value next",
            "assignment authorization=[REDACTED] next",
            ("secret-value",),
        ),
        (
            "cookie Cookie: session=abc123; next",
            "cookie Cookie: [REDACTED]; next",
            ("session=abc123", "abc123"),
        ),
        (
            "set-cookie Set-Cookie: session=abc123; Path=/ next",
            "set-cookie Set-Cookie: [REDACTED]; Path=/ next",
            ("session=abc123", "abc123"),
        ),
        (
            "cookie assignment cookie=session=abc123 next",
            "cookie assignment cookie=[REDACTED] next",
            ("session=abc123", "abc123"),
        ),
    ],
)
def test_decision_signal_sanitizer_redacts_authorization_and_cookie_matrix(
    raw_text,
    expected_text,
    leaked_fragments,
) -> None:
    sanitized = sanitize_decision_signal_text(raw_text)

    assert expected_text in sanitized
    for leaked in leaked_fragments:
        assert leaked not in sanitized


def test_shared_diagnostic_sanitizer_uses_same_auth_credential_boundary() -> None:
    sanitized = sanitize_diagnostic_text(
        "Authorization: Bearer abc+/def==; next "
        "Authorization: Basic dXNlcjpwYXNz "
        "Cookie: session=abc123"
    )

    assert "Authorization: [REDACTED]; next" in sanitized
    assert "Authorization: [REDACTED]" in sanitized
    assert "Cookie: [REDACTED]" in sanitized
    for leaked in (
        "abc+/def==",
        "+/def==",
        "def==",
        "dXNlcjpwYXNz",
        "pwYXNz",
        "session=abc123",
        "abc123",
    ):
        assert leaked not in sanitized


def test_trace_id_identity_is_not_silently_truncated(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)
    trace_a = f"{'x' * 63}a"
    trace_b = f"{'x' * 63}b"

    first = service.create_signal(_payload(source_report_id=None, trace_id=trace_a))
    second = service.create_signal(_payload(source_report_id=None, trace_id=trace_b))

    assert first["created"] is True
    assert second["created"] is True
    assert first["item"]["id"] != second["item"]["id"]


def test_trace_id_rejects_sensitive_identity_text(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)

    with pytest.raises(ValueError, match="trace_id"):
        service.create_signal(_payload(trace_id="Bearer abc+/def=="))

    with pytest.raises(ValueError, match="trace_id"):
        service.create_signal(_payload(trace_id="Authorization: Basic dXNlcjpwYXNz"))

    with pytest.raises(ValueError, match="trace_id"):
        service.create_signal(_payload(trace_id="cookie=session=abc123"))

    with pytest.raises(ValueError, match="trace_id"):
        service.create_signal(_payload(trace_id="https://hooks.example.com/send"))


def test_service_sanitizes_public_short_fields_before_persisting(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)

    result = service.create_signal(
        _payload(
            stock_name="secret=plain-secret",
            source_agent="Bearer abc+/def==",
            trigger_source="Bearer abc+/def==",
            action_label="token=abc",
        )
    )

    item = result["item"]
    assert item["stock_name"] == "secret=[REDACTED]"
    assert item["source_agent"] == "Bearer [REDACTED]"
    assert item["trigger_source"] == "Bearer [REDACTED]"
    assert item["action_label"] == "token=[REDACTED]"
    assert "plain-secret" not in str(item)
    assert "abc+/def==" not in str(item)

    with isolated_db.get_session() as session:
        row = session.query(DecisionSignalRecord).filter_by(id=item["id"]).one()
        stored_blob = " ".join(
            str(value or "")
            for value in (
                row.stock_name,
                row.source_agent,
                row.trigger_source,
                row.action_label,
            )
        )
    assert "plain-secret" not in stored_blob
    assert "abc+/def==" not in stored_blob
    assert "Bearer [REDACTED]" in stored_blob


def test_service_sanitizes_text_and_json_before_persisting(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)
    long_text = "x" * 450

    result = service.create_signal(
        _payload(
            reason=f"{long_text} Bearer abc.def.ghi https://hooks.example.com/send",
            risk_summary="api_key=sk-1234567890abcdef123456",
            invalidation={"token": "plain-secret", "note": "secret=keepout"},
            watch_conditions=["watch https://example.com/path"],
            evidence={
                "webhook_url": "https://secret.example.com/hook",
                "source_url": "https://news.example.com/article?id=1",
                "signed_url": "https://news.example.com/article?token=abc&id=1",
                "auth_url": "https://news.example.com/article?auth_token=abc&id=2",
                "hyphen_signed_url": "https://news.example.com/article?api-key=abc",
                "slack": "https://hooks.slack.com/services/T000/B000/abcdef",
                "feishu": "https://open.feishu.cn/open-apis/bot/v2/hook/abcdef",
                "userinfo": "https://user:pass@example.com/path",
                "fragment": "https://news.example.com/cb#access_token=abc",
                "note": "Bearer abc+/def==",
                "auth_header": "Authorization: Basic dXNlcjpwYXNz",
                "cookie_header": "Cookie: session=abc123",
            },
            metadata={
                "access_token": "abc",
                "callback": "https://example.com/cb",
                "auth_assignment": "authorization=secret-value",
            },
        )
    )

    item = result["item"]
    assert len(item["reason"]) > 300
    response_blob = str(item)
    assert "hooks.example.com" not in response_blob
    assert "news.example.com/article?id=1" in response_blob
    assert "example.com/cb" in response_blob
    assert "secret.example.com" not in response_blob
    assert "hooks.slack.com" not in response_blob
    assert "open.feishu.cn" not in response_blob
    assert "user:pass" not in response_blob
    assert "access_token=abc" not in response_blob
    assert "token=abc" not in response_blob
    assert "auth_token=abc" not in response_blob
    assert "api-key=abc" not in response_blob
    assert "]&id=" not in response_blob
    assert "plain-secret" not in response_blob
    assert "abc+/def==" not in response_blob
    assert "+/def==" not in response_blob
    assert "dXNlcjpwYXNz" not in response_blob
    assert "pwYXNz" not in response_blob
    assert "session=abc123" not in response_blob
    assert "secret-value" not in response_blob
    assert "sk-1234567890abcdef123456" not in response_blob
    assert "[REDACTED" in response_blob

    with isolated_db.get_session() as session:
        row = session.query(DecisionSignalRecord).filter_by(id=item["id"]).one()
        stored_blob = " ".join(
            str(value or "")
            for value in (
                row.reason,
                row.risk_summary,
                row.invalidation,
                row.watch_conditions,
                row.evidence_json,
                row.metadata_json,
            )
        )
    assert "hooks.example.com" not in stored_blob
    assert "news.example.com/article?id=1" in stored_blob
    assert "hooks.slack.com" not in stored_blob
    assert "open.feishu.cn" not in stored_blob
    assert "user:pass" not in stored_blob
    assert "access_token=abc" not in stored_blob
    assert "token=abc" not in stored_blob
    assert "auth_token=abc" not in stored_blob
    assert "api-key=abc" not in stored_blob
    assert "]&id=" not in stored_blob
    assert "plain-secret" not in stored_blob
    assert "abc+/def==" not in stored_blob
    assert "+/def==" not in stored_blob
    assert "dXNlcjpwYXNz" not in stored_blob
    assert "pwYXNz" not in stored_blob
    assert "session=abc123" not in stored_blob
    assert "secret-value" not in stored_blob
    assert "sk-1234567890abcdef123456" not in stored_blob


def test_service_raises_on_corrupt_persisted_json(isolated_db) -> None:
    service = DecisionSignalService(db_manager=isolated_db)
    result = service.create_signal(_payload(source_report_id=351, trace_id="trace-351"))
    signal_id = result["item"]["id"]

    with isolated_db.get_session() as session:
        row = session.get(DecisionSignalRecord, signal_id)
        row.evidence_json = "{not valid json"
        session.commit()

    with pytest.raises(DecisionSignalStorageError, match="invalid persisted JSON"):
        service.get_signal(signal_id)
