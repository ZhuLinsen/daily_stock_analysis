# -*- coding: utf-8 -*-
"""API tests for DecisionSignal P1."""

from __future__ import annotations

import os
import sys
import time
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.app import create_app
from src.analyzer import AnalysisResult
from src.config import Config
from src.services.decision_signal_extractor import extract_and_persist_from_analysis_result
from src.services.decision_signal_service import DecisionSignalService
from src.storage import AnalysisHistory, DatabaseManager, DecisionSignalRecord, PortfolioAccount, PortfolioPosition, utc_naive_now


@contextmanager
def _temporary_tz(tz_name: str):
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = tz_name
    if hasattr(time, "tzset"):
        time.tzset()
    try:
        yield
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        if hasattr(time, "tzset"):
            time.tzset()


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


@pytest.fixture()
def client_and_db(tmp_path):
    old_env_file = os.environ.get("ENV_FILE")
    old_database_path = os.environ.get("DATABASE_PATH")
    env_path = tmp_path / ".env"
    db_path = tmp_path / "decision_signal_api.db"
    static_dir = tmp_path / "empty-static"
    static_dir.mkdir()
    env_path.write_text(
        "\n".join(
            [
                "STOCK_LIST=600519",
                "GEMINI_API_KEY=test",
                "ADMIN_AUTH_ENABLED=false",
                f"DATABASE_PATH={db_path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    os.environ["ENV_FILE"] = str(env_path)
    os.environ["DATABASE_PATH"] = str(db_path)
    _reset_auth_globals()
    Config.reset_instance()
    DatabaseManager.reset_instance()
    app = create_app(static_dir=Path(static_dir))
    client = TestClient(app)
    db = DatabaseManager.get_instance()
    try:
        yield client, db
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        _reset_auth_globals()
        if old_env_file is None:
            os.environ.pop("ENV_FILE", None)
        else:
            os.environ["ENV_FILE"] = old_env_file
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
        "source_agent": "api-test",
        "source_report_id": 3001,
        "trace_id": "trace-3001",
        "market_phase": "intraday",
        "trigger_source": "api",
        "action": "buy",
        "confidence": 0.75,
        "score": 80,
        "horizon": "3d",
        "entry_low": 1680,
        "stop_loss": 1600,
        "reason": "突破平台",
        "evidence": {"source": "unit-test"},
        "metadata": {"task_id": "task-3001", "alert_trigger_id": "alert-1"},
    }
    payload.update(overrides)
    return payload


def test_decision_signal_api_requires_session_when_admin_auth_enabled(tmp_path) -> None:
    old_env_file = os.environ.get("ENV_FILE")
    old_database_path = os.environ.get("DATABASE_PATH")
    env_path = tmp_path / ".env"
    db_path = tmp_path / "decision_signal_auth.db"
    static_dir = tmp_path / "empty-static"
    static_dir.mkdir()
    env_path.write_text(
        "\n".join(
            [
                "STOCK_LIST=600519",
                "GEMINI_API_KEY=test",
                "ADMIN_AUTH_ENABLED=true",
                f"DATABASE_PATH={db_path}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    os.environ["ENV_FILE"] = str(env_path)
    os.environ["DATABASE_PATH"] = str(db_path)
    _reset_auth_globals()
    Config.reset_instance()
    DatabaseManager.reset_instance()

    try:
        client = TestClient(create_app(static_dir=Path(static_dir)))
        resp = client.get("/api/v1/decision-signals")
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"
    finally:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        _reset_auth_globals()
        if old_env_file is None:
            os.environ.pop("ENV_FILE", None)
        else:
            os.environ["ENV_FILE"] = old_env_file
        if old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = old_database_path


def test_create_duplicate_list_detail_latest_and_status_update(client_and_db) -> None:
    client, _db = client_and_db

    created_resp = client.post("/api/v1/decision-signals", json=_payload())
    assert created_resp.status_code == 200, created_resp.text
    created = created_resp.json()
    assert created["created"] is True
    signal_id = created["item"]["id"]
    assert created["item"]["stock_code"] == "600519"
    assert created["item"]["plan_quality"] == "partial"
    assert created["item"]["decision_profile"] == "balanced"
    assert created["item"]["metadata"]["decision_profile"] == "balanced"
    assert created["item"]["expires_at"] is not None

    duplicate_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(reason="重复报告里不同文案不应覆盖旧信号"),
    )
    assert duplicate_resp.status_code == 200, duplicate_resp.text
    duplicate = duplicate_resp.json()
    assert duplicate["created"] is False
    assert duplicate["item"]["id"] == signal_id
    assert duplicate["item"]["reason"] == "突破平台"

    list_resp = client.get(
        "/api/v1/decision-signals",
        params={
            "market": "cn",
            "stock_code": "600519.SH",
            "action": "buy",
            "market_phase": "intraday",
            "source_type": "analysis",
            "trigger_source": "api",
            "status": "active",
        },
    )
    assert list_resp.status_code == 200, list_resp.text
    listed = list_resp.json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == signal_id

    detail_resp = client.get(f"/api/v1/decision-signals/{signal_id}")
    assert detail_resp.status_code == 200, detail_resp.text
    assert detail_resp.json()["id"] == signal_id

    latest_resp = client.get("/api/v1/decision-signals/latest/600519", params={"limit": 1})
    assert latest_resp.status_code == 200, latest_resp.text
    assert latest_resp.json()["items"][0]["id"] == signal_id

    patch_resp = client.patch(
        f"/api/v1/decision-signals/{signal_id}/status",
        json={
            "status": "closed",
            "metadata": {"closed_by": "api-test", "decision_profile": "aggressive"},
        },
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["status"] == "closed"
    assert patch_resp.json()["metadata"]["closed_by"] == "api-test"
    assert patch_resp.json()["metadata"]["decision_profile"] == "balanced"
    assert "task_id" not in patch_resp.json()["metadata"]

    clear_metadata_resp = client.patch(
        f"/api/v1/decision-signals/{signal_id}/status",
        json={"status": "archived", "metadata": None},
    )
    assert clear_metadata_resp.status_code == 200, clear_metadata_resp.text
    assert clear_metadata_resp.json()["status"] == "archived"
    assert clear_metadata_resp.json()["metadata"] is None

    terminal_reactivate_resp = client.patch(
        f"/api/v1/decision-signals/{signal_id}/status",
        json={"status": "active"},
    )
    assert terminal_reactivate_resp.status_code == 400, terminal_reactivate_resp.text
    assert terminal_reactivate_resp.json()["error"] == "validation_error"

    invalid_status_resp = client.patch(
        f"/api/v1/decision-signals/{signal_id}/status",
        json={"status": "bad_status"},
    )
    assert invalid_status_resp.status_code == 422
    assert invalid_status_resp.json()["error"] == "validation_error"

    missing_resp = client.get("/api/v1/decision-signals/999999")
    assert missing_resp.status_code == 404


def test_create_rejects_explicit_null_decision_profile_and_accepts_null_metadata(client_and_db) -> None:
    client, _db = client_and_db

    null_profile_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3010, trace_id="trace-null-profile", decision_profile=None),
    )
    assert null_profile_resp.status_code == 422, null_profile_resp.text
    assert "decision_profile" in null_profile_resp.text

    null_metadata_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3011, trace_id="trace-null-metadata", metadata=None),
    )
    assert null_metadata_resp.status_code == 200, null_metadata_resp.text
    null_metadata_item = null_metadata_resp.json()["item"]
    assert null_metadata_item["decision_profile"] == "balanced"
    assert null_metadata_item["metadata"] == {"decision_profile": "balanced"}

    omitted_metadata_payload = _payload(
        source_report_id=3012,
        trace_id="trace-omitted-metadata",
    )
    omitted_metadata_payload.pop("metadata")
    omitted_metadata_resp = client.post(
        "/api/v1/decision-signals",
        json=omitted_metadata_payload,
    )
    assert omitted_metadata_resp.status_code == 200, omitted_metadata_resp.text
    omitted_metadata_item = omitted_metadata_resp.json()["item"]
    assert omitted_metadata_item["decision_profile"] == "balanced"
    assert omitted_metadata_item["metadata"] == {"decision_profile": "balanced"}


def test_create_treats_null_lifecycle_fields_as_missing(client_and_db) -> None:
    client, _db = client_and_db

    response = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3002,
            trace_id="trace-null-lifecycle-api",
            horizon=None,
            expires_at=None,
            market_phase="intraday",
            metadata={"market_phase_summary": {"minutes_to_close": 25}},
        ),
    )

    assert response.status_code == 200, response.text
    item = response.json()["item"]
    assert item["status"] == "active"
    assert item["horizon"] == "intraday"
    assert item["expires_at"] is not None


def test_status_update_sanitizes_metadata_before_response_and_persistence(client_and_db) -> None:
    client, db = client_and_db

    created_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3051, trace_id="trace-3051"),
    )
    assert created_resp.status_code == 200, created_resp.text
    signal_id = created_resp.json()["item"]["id"]

    patch_resp = client.patch(
        f"/api/v1/decision-signals/{signal_id}/status",
        json={
            "status": "closed",
            "metadata": {
                "source_url": "https://news.example.com/article?id=1",
                "ordinary_services_url": "https://example.com/services/research?id=1",
                "ordinary_robot_url": "https://example.com/robot/send/report?id=1",
                "webhook": "https://hooks.slack.com/services/T000/B000/abcdef",
                "feishu": "https://open.feishu.cn/open-apis/bot/v2/hook/abcdef",
                "userinfo": "https://user:pass@example.com/path",
                "fragment": "https://news.example.com/cb#access_token=abc",
                "note": "Bearer abc+/def==",
            },
        },
    )
    assert patch_resp.status_code == 200, patch_resp.text
    response_blob = str(patch_resp.json()["metadata"])
    assert "https://news.example.com/article?id=1" in response_blob
    assert "https://example.com/services/research?id=1" in response_blob
    assert "https://example.com/robot/send/report?id=1" in response_blob
    assert "[REDACTED_URL]" in response_blob
    assert "hooks.slack.com" not in response_blob
    assert "open.feishu.cn" not in response_blob
    assert "user:pass" not in response_blob
    assert "access_token=abc" not in response_blob
    assert "abc+/def==" not in response_blob
    assert "+/def==" not in response_blob

    with db.session_scope() as session:
        row = session.query(DecisionSignalRecord).filter_by(id=signal_id).one()
        stored_blob = str(row.metadata_json)
    assert "https://news.example.com/article?id=1" in stored_blob
    assert "https://example.com/services/research?id=1" in stored_blob
    assert "https://example.com/robot/send/report?id=1" in stored_blob
    assert "[REDACTED_URL]" in stored_blob
    assert "hooks.slack.com" not in stored_blob
    assert "open.feishu.cn" not in stored_blob
    assert "user:pass" not in stored_blob
    assert "access_token=abc" not in stored_blob
    assert "abc+/def==" not in stored_blob
    assert "+/def==" not in stored_blob


def test_create_sanitizes_public_short_fields_and_filters_by_sanitized_trigger_source(client_and_db) -> None:
    client, db = client_and_db
    raw_trigger_source = "Bearer abc+/def=="
    created_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3061,
            trace_id="trace-public-sanitized",
            stock_name="secret=plain-secret",
            source_agent="https://hooks.example.com/send",
            trigger_source=raw_trigger_source,
            action_label="token=abc",
        ),
    )
    assert created_resp.status_code == 200, created_resp.text
    item = created_resp.json()["item"]
    assert item["stock_name"] == "secret=[REDACTED]"
    assert item["source_agent"] == "[REDACTED_URL]"
    assert item["trigger_source"] == "Bearer [REDACTED]"
    assert item["action_label"] == "token=[REDACTED]"
    assert "plain-secret" not in str(item)
    assert "abc+/def==" not in str(item)
    assert "hooks.example.com" not in str(item)

    list_resp = client.get(
        "/api/v1/decision-signals",
        params={"trigger_source": raw_trigger_source},
    )
    assert list_resp.status_code == 200, list_resp.text
    assert list_resp.json()["total"] == 1
    assert list_resp.json()["items"][0]["id"] == item["id"]

    with db.session_scope() as session:
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
    assert "hooks.example.com" not in stored_blob


def test_detail_endpoint_lazily_expires_active_signal(client_and_db) -> None:
    client, _db = client_and_db
    created_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3101,
            trace_id="trace-3101",
            expires_at=(utc_naive_now() - timedelta(minutes=5)).isoformat(),
        ),
    )
    assert created_resp.status_code == 200, created_resp.text
    signal_id = created_resp.json()["item"]["id"]
    assert created_resp.json()["item"]["status"] == "expired"

    detail_resp = client.get(f"/api/v1/decision-signals/{signal_id}")
    assert detail_resp.status_code == 200, detail_resp.text
    assert detail_resp.json()["status"] == "expired"

    reactivate_resp = client.patch(
        f"/api/v1/decision-signals/{signal_id}/status",
        json={"status": "active"},
    )
    assert reactivate_resp.status_code == 400, reactivate_resp.text
    assert reactivate_resp.json()["error"] == "validation_error"

    close_resp = client.patch(
        f"/api/v1/decision-signals/{signal_id}/status",
        json={"status": "closed"},
    )
    assert close_resp.status_code == 200, close_resp.text
    assert close_resp.json()["status"] == "closed"

    latest_resp = client.get("/api/v1/decision-signals/latest/600519")
    assert latest_resp.status_code == 200, latest_resp.text
    assert latest_resp.json()["total"] == 0


def test_patch_status_rejects_expired_signal_without_expires_at_extension(client_and_db) -> None:
    client, _db = client_and_db
    created_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=31011,
            trace_id="trace-31011",
            status="expired",
            expires_at=None,
        ),
    )
    assert created_resp.status_code == 200, created_resp.text
    item = created_resp.json()["item"]
    assert item["status"] == "expired"

    reactivate_resp = client.patch(
        f"/api/v1/decision-signals/{item['id']}/status",
        json={"status": "active"},
    )
    assert reactivate_resp.status_code == 400, reactivate_resp.text
    assert reactivate_resp.json()["error"] == "validation_error"


def test_create_accepts_timezone_aware_expires_at_values(client_and_db) -> None:
    client, _db = client_and_db

    expired_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3102,
            trace_id="trace-3102",
            expires_at="2020-01-01T00:00:00Z",
        ),
    )
    assert expired_resp.status_code == 200, expired_resp.text
    expired_item = expired_resp.json()["item"]
    assert expired_item["status"] == "expired"
    assert expired_item["expires_at"] == "2020-01-01T00:00:00"

    active_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3103,
            trace_id="trace-3103",
            expires_at="2099-01-01T00:00:00+08:00",
        ),
    )
    assert active_resp.status_code == 200, active_resp.text
    active_item = active_resp.json()["item"]
    assert active_item["status"] == "active"
    assert active_item["expires_at"] == "2098-12-31T16:00:00"


def test_create_refreshes_expired_same_source_when_future_expiry_is_supplied(client_and_db) -> None:
    client, db = client_and_db
    expired_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3111,
            trace_id="trace-refresh-original",
            expires_at="2020-01-01T00:00:00Z",
            reason="old reason",
            target_price=1800,
        ),
    )
    assert expired_resp.status_code == 200, expired_resp.text
    expired = expired_resp.json()
    signal_id = expired["item"]["id"]
    assert expired["created"] is True
    assert expired["item"]["status"] == "expired"

    refresh_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3111,
            trace_id="trace-refresh-new",
            expires_at=(utc_naive_now() + timedelta(days=2)).isoformat(),
            reason="fresh reason",
            target_price=1900,
        ),
    )
    assert refresh_resp.status_code == 200, refresh_resp.text
    refreshed = refresh_resp.json()
    assert refreshed["created"] is False
    assert refreshed["item"]["id"] == signal_id
    assert refreshed["item"]["status"] == "active"
    assert refreshed["item"]["reason"] == "fresh reason"
    assert refreshed["item"]["target_price"] == 1900
    assert refreshed["item"]["trace_id"] == "trace-refresh-original"
    assert refreshed["item"]["created_at"] == expired["item"]["created_at"]

    with db.session_scope() as session:
        row = session.query(DecisionSignalRecord).filter_by(id=signal_id).one()
        assert row.status == "active"
        assert row.reason == "fresh reason"
        assert row.trace_id == "trace-refresh-original"


def test_create_invalidates_opposing_active_signal_and_latest_filters_it(client_and_db) -> None:
    client, _db = client_and_db
    buy_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=31101,
            trace_id="trace-api-opposing-buy",
            action="buy",
        ),
    )
    assert buy_resp.status_code == 200, buy_resp.text
    buy = buy_resp.json()["item"]

    sell_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=31102,
            trace_id="trace-api-opposing-sell",
            action="sell",
        ),
    )
    assert sell_resp.status_code == 200, sell_resp.text
    sell = sell_resp.json()["item"]

    old_resp = client.get(f"/api/v1/decision-signals/{buy['id']}")
    assert old_resp.status_code == 200, old_resp.text
    old = old_resp.json()
    assert old["status"] == "invalidated"
    assert old["metadata"]["invalidated_by_signal_id"] == sell["id"]

    latest_resp = client.get("/api/v1/decision-signals/latest/600519", params={"limit": 5})
    assert latest_resp.status_code == 200, latest_resp.text
    latest = latest_resp.json()
    assert latest["total"] == 1
    assert latest["items"][0]["id"] == sell["id"]


def test_create_does_not_refresh_expired_same_source_without_future_active_expiry(client_and_db) -> None:
    client, _db = client_and_db
    expired_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3112,
            trace_id="trace-refresh-past-original",
            expires_at="2020-01-01T00:00:00Z",
            reason="old reason",
        ),
    )
    assert expired_resp.status_code == 200, expired_resp.text
    expired = expired_resp.json()

    second_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3112,
            trace_id="trace-refresh-past-new",
            expires_at="2020-01-02T00:00:00Z",
            reason="fresh reason",
        ),
    )
    assert second_resp.status_code == 200, second_resp.text
    second = second_resp.json()
    assert second["created"] is False
    assert second["item"]["id"] == expired["item"]["id"]
    assert second["item"]["status"] == "expired"
    assert second["item"]["reason"] == "old reason"


@pytest.mark.parametrize("terminal_status", ["closed", "invalidated", "archived"])
def test_create_does_not_reactivate_terminal_same_source_status(client_and_db, terminal_status) -> None:
    client, _db = client_and_db
    created_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3113,
            trace_id="trace-terminal-original",
            reason="old reason",
        ),
    )
    assert created_resp.status_code == 200, created_resp.text
    signal_id = created_resp.json()["item"]["id"]

    status_resp = client.patch(
        f"/api/v1/decision-signals/{signal_id}/status",
        json={"status": terminal_status},
    )
    assert status_resp.status_code == 200, status_resp.text

    second_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3113,
            trace_id="trace-terminal-new",
            expires_at=(utc_naive_now() + timedelta(days=2)).isoformat(),
            reason="fresh reason",
        ),
    )
    assert second_resp.status_code == 200, second_resp.text
    second = second_resp.json()
    assert second["created"] is False
    assert second["item"]["id"] == signal_id
    assert second["item"]["status"] == terminal_status
    assert second["item"]["reason"] == "old reason"


def test_timezone_aware_future_expiry_stays_active_in_non_utc_runtime(client_and_db) -> None:
    client, _db = client_and_db

    with _temporary_tz("Asia/Shanghai"):
        created_resp = client.post(
            "/api/v1/decision-signals",
            json=_payload(
                source_report_id=3104,
                trace_id="trace-3104",
                expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            ),
        )
        assert created_resp.status_code == 200, created_resp.text
        created = created_resp.json()["item"]
        assert created["status"] == "active"
        for field_name in ("expires_at", "created_at", "updated_at"):
            assert datetime.fromisoformat(created[field_name]).tzinfo is None

        latest_resp = client.get("/api/v1/decision-signals/latest/600519")
        assert latest_resp.status_code == 200, latest_resp.text
        assert latest_resp.json()["total"] == 1
        assert latest_resp.json()["items"][0]["id"] == created["id"]


def test_aware_datetime_range_filters_use_utc_naive_contract(client_and_db) -> None:
    client, _db = client_and_db

    with _temporary_tz("Asia/Shanghai"):
        created_resp = client.post(
            "/api/v1/decision-signals",
            json=_payload(source_report_id=3105, trace_id="trace-3105"),
        )
        assert created_resp.status_code == 200, created_resp.text
        signal_id = created_resp.json()["item"]["id"]

        list_resp = client.get(
            "/api/v1/decision-signals",
            params={
                "created_from": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                "created_to": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
            },
        )
        assert list_resp.status_code == 200, list_resp.text
        assert list_resp.json()["total"] == 1
        assert list_resp.json()["items"][0]["id"] == signal_id


def test_holding_only_uses_cached_positions_and_stock_code_variants(client_and_db) -> None:
    client, db = client_and_db
    stock_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3201, trace_id="trace-3201", stock_code="600519.SH"),
    )
    assert stock_resp.status_code == 200, stock_resp.text
    other_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3202,
            trace_id="trace-3202",
            stock_code="AAPL",
            stock_name="Apple",
            market="us",
        ),
    )
    assert other_resp.status_code == 200, other_resp.text
    inactive_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3203,
            trace_id="trace-3203",
            stock_code="TSLA",
            stock_name="Tesla",
            market="us",
        ),
    )
    assert inactive_resp.status_code == 200, inactive_resp.text
    zero_only_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3204,
            trace_id="trace-3204",
            stock_code="MSFT",
            stock_name="Microsoft",
            market="us",
        ),
    )
    assert zero_only_resp.status_code == 200, zero_only_resp.text
    hk_same_symbol_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3205,
            trace_id="trace-3205",
            stock_code="AAPL",
            stock_name="Apple HK synthetic",
            market="hk",
        ),
    )
    assert hk_same_symbol_resp.status_code == 200, hk_same_symbol_resp.text

    with db.session_scope() as session:
        account = PortfolioAccount(
            name="Test account",
            market="cn",
            base_currency="CNY",
            is_active=True,
        )
        session.add(account)
        session.flush()
        account_id = account.id
        session.add(
            PortfolioPosition(
                account_id=account_id,
                cost_method="fifo",
                symbol="SH600519",
                market="cn",
                currency="CNY",
                quantity=100,
                avg_cost=1600,
                total_cost=160000,
            )
        )
        session.add(
            PortfolioPosition(
                account_id=account_id,
                cost_method="fifo",
                symbol="AAPL",
                market="us",
                currency="USD",
                quantity=0,
            )
        )
        session.add(
            PortfolioPosition(
                account_id=account_id,
                cost_method="fifo",
                symbol="MSFT",
                market="us",
                currency="USD",
                quantity=0,
            )
        )
        session.add(
            PortfolioPosition(
                account_id=account_id,
                cost_method="avg",
                symbol="AAPL",
                market="us",
                currency="USD",
                quantity=5,
                avg_cost=180,
                total_cost=900,
            )
        )
        inactive_account = PortfolioAccount(
            name="Inactive account",
            market="us",
            base_currency="USD",
            is_active=False,
        )
        session.add(inactive_account)
        session.flush()
        inactive_account_id = inactive_account.id
        session.add(
            PortfolioPosition(
                account_id=inactive_account_id,
                cost_method="fifo",
                symbol="TSLA",
                market="us",
                currency="USD",
                quantity=3,
                avg_cost=200,
                total_cost=600,
            )
        )

    with patch(
        "src.services.portfolio_service.PortfolioService.get_portfolio_snapshot",
        side_effect=AssertionError("holding_only must not replay portfolio snapshots"),
    ):
        holding_resp = client.get(
            "/api/v1/decision-signals",
            params={"holding_only": "true", "account_id": account_id},
        )

    assert holding_resp.status_code == 200, holding_resp.text
    payload = holding_resp.json()
    assert payload["total"] == 2
    assert {(item["market"], item["stock_code"]) for item in payload["items"]} == {
        ("cn", "600519"),
        ("us", "AAPL"),
    }

    with patch(
        "src.services.portfolio_service.PortfolioService.get_portfolio_snapshot",
        side_effect=AssertionError("holding_only must not replay portfolio snapshots"),
    ):
        all_active_resp = client.get(
            "/api/v1/decision-signals",
            params={"holding_only": "true"},
        )

    assert all_active_resp.status_code == 200, all_active_resp.text
    all_active_payload = all_active_resp.json()
    assert all_active_payload["total"] == 2
    assert {(item["market"], item["stock_code"]) for item in all_active_payload["items"]} == {
        ("cn", "600519"),
        ("us", "AAPL"),
    }

    with patch(
        "src.services.portfolio_service.PortfolioService.get_portfolio_snapshot",
        side_effect=AssertionError("holding_only must not replay portfolio snapshots"),
    ):
        inactive_holding_resp = client.get(
            "/api/v1/decision-signals",
            params={"holding_only": "true", "account_id": inactive_account_id},
        )
    assert inactive_holding_resp.status_code == 200, inactive_holding_resp.text
    assert inactive_holding_resp.json()["total"] == 0
    assert inactive_holding_resp.json()["items"] == []

    variant_resp = client.get("/api/v1/decision-signals", params={"stock_code": "SH600519"})
    assert variant_resp.status_code == 200, variant_resp.text
    assert variant_resp.json()["total"] == 1

    with db.session_scope() as session:
        empty_account = PortfolioAccount(name="Empty account", market="cn", base_currency="CNY")
        session.add(empty_account)
        session.flush()
        empty_account_id = empty_account.id

    empty_resp = client.get(
        "/api/v1/decision-signals",
        params={"holding_only": "true", "account_id": empty_account_id},
    )
    assert empty_resp.status_code == 200, empty_resp.text
    assert empty_resp.json()["total"] == 0
    assert empty_resp.json()["items"] == []

    empty_bad_date_resp = client.get(
        "/api/v1/decision-signals",
        params={
            "holding_only": "true",
            "account_id": empty_account_id,
            "created_from": "bad-date",
        },
    )
    assert empty_bad_date_resp.status_code == 400
    assert empty_bad_date_resp.json()["error"] == "validation_error"


def test_query_validation_error_envelope(client_and_db) -> None:
    client, _db = client_and_db
    resp = client.get("/api/v1/decision-signals", params={"action": "panic"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "validation_error"

    page_size_resp = client.get("/api/v1/decision-signals", params={"page_size": 0})
    assert page_size_resp.status_code == 422
    assert page_size_resp.json()["error"] == "validation_error"


def test_internal_errors_do_not_reflect_exception_details(client_and_db) -> None:
    client, _db = client_and_db

    with patch("api.v1.endpoints.decision_signals.DecisionSignalService") as service_cls:
        service_cls.return_value.list_signals.side_effect = RuntimeError(
            "secret-token /private/tmp/internal-path"
        )
        resp = client.get("/api/v1/decision-signals")

    assert resp.status_code == 500
    payload = resp.json()
    assert payload["error"] == "internal_error"
    assert payload["message"] == "List decision signals failed"
    assert "secret-token" not in str(payload)
    assert "internal-path" not in str(payload)


def test_corrupt_persisted_json_returns_internal_error_consistently(client_and_db) -> None:
    client, db = client_and_db

    created_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3251, trace_id="trace-corrupt-json"),
    )
    assert created_resp.status_code == 200, created_resp.text
    signal_id = created_resp.json()["item"]["id"]

    with db.session_scope() as session:
        row = session.query(DecisionSignalRecord).filter_by(id=signal_id).one()
        row.evidence_json = "{bad persisted json"

    cases = [
        (
            client.get("/api/v1/decision-signals", params={"stock_code": "600519"}),
            "List decision signals failed",
        ),
        (
            client.get(f"/api/v1/decision-signals/{signal_id}"),
            "Get decision signal failed",
        ),
        (
            client.get("/api/v1/decision-signals/latest/600519"),
            "Get latest decision signals failed",
        ),
    ]
    for resp, message in cases:
        assert resp.status_code == 500, resp.text
        payload = resp.json()
        assert payload["error"] == "internal_error"
        assert payload["message"] == message
        assert "bad persisted json" not in str(payload)


def test_create_schema_and_service_validation_errors(client_and_db) -> None:
    client, _db = client_and_db

    schema_invalid_cases = [
        {"entry_low": -1},
        {"entry_high": 0},
        {"stop_loss": "nan"},
        {"target_price": "inf"},
        {"metadata": ["not-an-object"]},
    ]
    for overrides in schema_invalid_cases:
        resp = client.post("/api/v1/decision-signals", json=_payload(**overrides))
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"] == "validation_error"

    range_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3301, trace_id="trace-range", entry_low=1700, entry_high=1600),
    )
    assert range_resp.status_code == 400, range_resp.text
    assert range_resp.json()["error"] == "validation_error"

    long_trace_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3302, trace_id="x" * 65),
    )
    assert long_trace_resp.status_code == 400, long_trace_resp.text
    assert long_trace_resp.json()["error"] == "validation_error"
    assert "trace_id" in long_trace_resp.json()["message"]

    sensitive_trace_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3303, trace_id="Bearer abc+/def=="),
    )
    assert sensitive_trace_resp.status_code == 400, sensitive_trace_resp.text
    assert sensitive_trace_resp.json()["error"] == "validation_error"
    assert "trace_id" in sensitive_trace_resp.json()["message"]
    assert "abc+/def==" not in str(sensitive_trace_resp.json())

    for trace_id, leaked in (
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("cookie=session=abc123", "session=abc123"),
    ):
        sensitive_identity_resp = client.post(
            "/api/v1/decision-signals",
            json=_payload(source_report_id=3304, trace_id=trace_id),
        )
        assert sensitive_identity_resp.status_code == 400, sensitive_identity_resp.text
        assert sensitive_identity_resp.json()["error"] == "validation_error"
        assert "trace_id" in sensitive_identity_resp.json()["message"]
        assert leaked not in str(sensitive_identity_resp.json())


def test_dedup_distinguishes_horizon_and_market_phase(client_and_db) -> None:
    client, _db = client_and_db

    first_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3401, trace_id="trace-3401", horizon="1d", market_phase="intraday"),
    )
    assert first_resp.status_code == 200, first_resp.text
    first = first_resp.json()
    assert first["created"] is True

    duplicate_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3401, trace_id="trace-3401", horizon="1d", market_phase="intraday"),
    )
    assert duplicate_resp.status_code == 200, duplicate_resp.text
    duplicate = duplicate_resp.json()
    assert duplicate["created"] is False
    assert duplicate["item"]["id"] == first["item"]["id"]

    horizon_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3401, trace_id="trace-3401", horizon="10d", market_phase="intraday"),
    )
    assert horizon_resp.status_code == 200, horizon_resp.text
    assert horizon_resp.json()["created"] is True
    assert horizon_resp.json()["item"]["id"] != first["item"]["id"]

    phase_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(source_report_id=3401, trace_id="trace-3401", horizon="1d", market_phase="premarket"),
    )
    assert phase_resp.status_code == 200, phase_resp.text
    assert phase_resp.json()["created"] is True
    assert phase_resp.json()["item"]["id"] != first["item"]["id"]

    list_resp = client.get(
        "/api/v1/decision-signals",
        params={
            "stock_code": "600519",
            "source_type": "analysis",
            "source_report_id": 3401,
            "trace_id": "trace-3401",
            "trigger_source": "api",
        },
    )
    assert list_resp.status_code == 200, list_resp.text
    assert list_resp.json()["total"] == 3

    latest_resp = client.get("/api/v1/decision-signals/latest/600519", params={"limit": 3})
    assert latest_resp.status_code == 200, latest_resp.text
    assert latest_resp.json()["total"] == 3


def test_dedup_distinguishes_source_type_for_weak_report_ids(client_and_db) -> None:
    client, _db = client_and_db

    analysis_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3451,
            trace_id="trace-3451-analysis",
            source_type="analysis",
        ),
    )
    assert analysis_resp.status_code == 200, analysis_resp.text
    analysis = analysis_resp.json()
    assert analysis["created"] is True
    assert analysis["item"]["source_type"] == "analysis"

    manual_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3451,
            trace_id="trace-3451-manual",
            source_type="manual",
        ),
    )
    assert manual_resp.status_code == 200, manual_resp.text
    manual = manual_resp.json()
    assert manual["created"] is True
    assert manual["item"]["source_type"] == "manual"
    assert manual["item"]["id"] != analysis["item"]["id"]

    duplicate_manual_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3451,
            trace_id="trace-3451-manual-new",
            source_type="manual",
        ),
    )
    assert duplicate_manual_resp.status_code == 200, duplicate_manual_resp.text
    duplicate_manual = duplicate_manual_resp.json()
    assert duplicate_manual["created"] is False
    assert duplicate_manual["item"]["id"] == manual["item"]["id"]

    list_resp = client.get(
        "/api/v1/decision-signals",
        params={"stock_code": "600519", "source_report_id": 3451},
    )
    assert list_resp.status_code == 200, list_resp.text
    assert list_resp.json()["total"] == 2

    analysis_list_resp = client.get(
        "/api/v1/decision-signals",
        params={"stock_code": "600519", "source_report_id": 3451, "source_type": "analysis"},
    )
    assert analysis_list_resp.status_code == 200, analysis_list_resp.text
    assert analysis_list_resp.json()["total"] == 1

    manual_list_resp = client.get(
        "/api/v1/decision-signals",
        params={"stock_code": "600519", "source_report_id": 3451, "source_type": "manual"},
    )
    assert manual_list_resp.status_code == 200, manual_list_resp.text
    assert manual_list_resp.json()["total"] == 1


def test_stock_filter_codes_cover_market_optional_hk_without_widening_other_markets() -> None:
    from src.services.decision_signal_service import DecisionSignalService

    cases = [
        ("00700", None, ["00700", "HK00700"]),
        ("HK00700", None, ["HK00700"]),
        ("00700.HK", None, ["HK00700"]),
        ("00700", "hk", ["HK00700"]),
        ("600519", None, ["600519"]),
        ("600519.SH", None, ["600519"]),
        ("AAPL", None, ["AAPL"]),
    ]
    for raw_code, market, expected_codes in cases:
        assert DecisionSignalService._stock_filter_codes(raw_code, market=market) == expected_codes


def test_hk_stock_identity_variants_deduplicate_and_latest_matches(client_and_db) -> None:
    client, _db = client_and_db

    first_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3501,
            trace_id="trace-3501-a",
            stock_code="00700",
            stock_name="Tencent",
            market="hk",
        ),
    )
    assert first_resp.status_code == 200, first_resp.text
    first = first_resp.json()
    assert first["created"] is True
    assert first["item"]["stock_code"] == "HK00700"

    for raw_code, trace_id in (("HK00700", "trace-3501-b"), ("00700.HK", "trace-3501-c")):
        duplicate_resp = client.post(
            "/api/v1/decision-signals",
            json=_payload(
                source_report_id=3501,
                trace_id=trace_id,
                stock_code=raw_code,
                stock_name="Tencent",
                market="hk",
            ),
        )
        assert duplicate_resp.status_code == 200, duplicate_resp.text
        duplicate = duplicate_resp.json()
        assert duplicate["created"] is False
        assert duplicate["item"]["id"] == first["item"]["id"]

    latest_resp = client.get(
        "/api/v1/decision-signals/latest/00700",
        params={"market": "hk"},
    )
    assert latest_resp.status_code == 200, latest_resp.text
    assert latest_resp.json()["total"] == 1
    assert latest_resp.json()["items"][0]["id"] == first["item"]["id"]

    latest_cases = [
        ("00700", {}),
        ("HK00700", {}),
        ("00700.HK", {}),
        ("00700", {"market": "hk"}),
    ]
    for raw_code, params in latest_cases:
        latest_resp = client.get(f"/api/v1/decision-signals/latest/{raw_code}", params=params)
        assert latest_resp.status_code == 200, latest_resp.text
        latest_payload = latest_resp.json()
        assert latest_payload["total"] == 1
        assert latest_payload["items"][0]["id"] == first["item"]["id"]

    list_cases = [
        ("00700", {}),
        ("HK00700", {}),
        ("00700.HK", {}),
        ("00700", {"market": "hk"}),
    ]
    for raw_code, params in list_cases:
        list_resp = client.get(
            "/api/v1/decision-signals",
            params={"stock_code": raw_code, **params},
        )
        assert list_resp.status_code == 200, list_resp.text
        list_payload = list_resp.json()
        assert list_payload["total"] == 1
        assert list_payload["items"][0]["id"] == first["item"]["id"]


def test_dedup_distinguishes_market_for_same_symbol(client_and_db) -> None:
    client, _db = client_and_db

    us_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3601,
            trace_id="trace-3601-us",
            stock_code="DUPL",
            stock_name="Duplicate US",
            market="us",
        ),
    )
    assert us_resp.status_code == 200, us_resp.text
    assert us_resp.json()["created"] is True

    hk_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3601,
            trace_id="trace-3601-hk",
            stock_code="DUPL",
            stock_name="Duplicate HK",
            market="hk",
        ),
    )
    assert hk_resp.status_code == 200, hk_resp.text
    assert hk_resp.json()["created"] is True
    assert hk_resp.json()["item"]["id"] != us_resp.json()["item"]["id"]


def test_list_decision_profile_filter_distinguishes_unknown_from_omitted(client_and_db) -> None:
    client, db = client_and_db

    balanced_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3611,
            trace_id="trace-profile-api-balanced",
            decision_profile="balanced",
        ),
    )
    aggressive_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3612,
            trace_id="trace-profile-api-aggressive",
            decision_profile="aggressive",
        ),
    )
    legacy_resp = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            source_report_id=3613,
            trace_id="trace-profile-api-legacy",
            decision_profile="balanced",
        ),
    )
    assert balanced_resp.status_code == 200, balanced_resp.text
    assert aggressive_resp.status_code == 200, aggressive_resp.text
    assert legacy_resp.status_code == 200, legacy_resp.text
    legacy_id = legacy_resp.json()["item"]["id"]
    with db.session_scope() as session:
        row = session.query(DecisionSignalRecord).filter_by(id=legacy_id).one()
        row.decision_profile = None

    all_resp = client.get("/api/v1/decision-signals", params={"stock_code": "600519", "status": "active"})
    unknown_resp = client.get(
        "/api/v1/decision-signals",
        params={"stock_code": "600519", "status": "active", "decision_profile": "unknown"},
    )
    aggressive_list_resp = client.get(
        "/api/v1/decision-signals",
        params={"stock_code": "600519", "status": "active", "decision_profile": "aggressive"},
    )

    assert all_resp.status_code == 200, all_resp.text
    assert unknown_resp.status_code == 200, unknown_resp.text
    assert aggressive_list_resp.status_code == 200, aggressive_list_resp.text
    assert all_resp.json()["total"] == 3
    assert [item["id"] for item in unknown_resp.json()["items"]] == [legacy_id]
    assert aggressive_list_resp.json()["total"] == 1
    assert aggressive_list_resp.json()["items"][0]["decision_profile"] == "aggressive"


def _decision_signal_count(db: DatabaseManager) -> int:
    with db.session_scope() as session:
        return session.query(DecisionSignalRecord).count()


def _save_reassess_history(
    db: DatabaseManager,
    *,
    code: str = "600519",
    report_type: str = "full",
    operation_advice: str | None = "买入",
    raw_result: dict | str | None = None,
    context_snapshot: dict | str | None = None,
    sentiment_score: int | None = 72,
    stop_loss: float | None = 1600,
    take_profit: float | None = 1850,
) -> int:
    raw_payload = raw_result
    if isinstance(raw_payload, dict):
        raw_payload = json.dumps(raw_payload, ensure_ascii=False)
    context_payload = context_snapshot
    if isinstance(context_payload, dict):
        context_payload = json.dumps(context_payload, ensure_ascii=False)
    with db.session_scope() as session:
        row = AnalysisHistory(
            query_id="query-reassess-test",
            code=code,
            name="贵州茅台",
            report_type=report_type,
            sentiment_score=sentiment_score,
            operation_advice=operation_advice,
            trend_prediction="震荡上行",
            analysis_summary="趋势改善但需要风控。",
            raw_result=raw_payload,
            context_snapshot=context_payload,
            ideal_buy=1680,
            secondary_buy=1700,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        session.add(row)
        session.flush()
        return int(row.id)


def _set_reassess_history_created_at(
    db: DatabaseManager,
    record_id: int,
    created_at: datetime | None,
) -> None:
    with db.session_scope() as session:
        row = session.query(AnalysisHistory).filter(AnalysisHistory.id == record_id).one()
        row.created_at = created_at


def _valid_reassess_raw(**overrides) -> dict:
    raw = {
        "action": "buy",
        "operation_advice": "买入",
        "sentiment_score": 72,
        "confidence_level": "中",
        "analysis_summary": "趋势改善但需要确认。",
        "risk_warning": "跌破关键支撑需退出。",
        "dashboard": {
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": 1680,
                    "secondary_buy": 1700,
                    "stop_loss": 1600,
                    "take_profit": 1850,
                },
                "action_checklist": ["放量突破", "资金流转正"],
            },
            "phase_decision": {
                "watch_conditions": ["量能维持"],
            },
        },
    }
    raw.update(overrides)
    return raw


def _valid_reassess_context() -> dict:
    return {
        "market_phase_summary": {"phase": "intraday"},
        "analysis_context_pack_overview": {
            "data_quality": {"level": "usable"},
        },
    }


def _persist_auto_balanced_signal(
    db: DatabaseManager,
    *,
    source_report_id: int,
    raw_result: dict | None = None,
    context_snapshot: dict | None = None,
) -> dict:
    raw = raw_result or _valid_reassess_raw(invalidation="跌破关键支撑")
    result = AnalysisResult(
        code="600519",
        name="贵州茅台",
        sentiment_score=raw.get("sentiment_score", 72),
        trend_prediction="震荡上行",
        operation_advice=raw.get("operation_advice", "买入"),
        decision_type="buy",
        confidence_level=raw.get("confidence_level", "中"),
        analysis_summary=raw.get("analysis_summary", "趋势改善但需要确认。"),
        risk_warning=raw.get("risk_warning", "跌破关键支撑需退出。"),
        report_language="zh",
        action=raw.get("action", "buy"),
    )
    result.dashboard = raw.get("dashboard")
    persisted = extract_and_persist_from_analysis_result(
        result,
        context_snapshot=context_snapshot or _valid_reassess_context(),
        source_report_id=source_report_id,
        trace_id=f"trace-auto-{source_report_id}",
        query_source="api",
        report_type="full",
        profile_source="auto_default",
        service=DecisionSignalService(db_manager=db),
    )
    assert persisted is not None
    return persisted["item"]


def test_reassess_persist_true_inherits_source_report_not_found(client_and_db) -> None:
    client, db = client_and_db
    before = _decision_signal_count(db)

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={
            "source_report_id": 999999,
            "decision_profile": "aggressive",
            "persist": True,
        },
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"] == "source_report_not_found"
    assert _decision_signal_count(db) == before


@pytest.mark.parametrize(
    "payload",
    [
        {"decision_profile": "balanced", "persist": False},
        {"source_report_id": 0, "decision_profile": "balanced", "persist": False},
        {"source_report_id": 1, "decision_profile": "reckless", "persist": False},
    ],
)
def test_reassess_schema_validation_errors(client_and_db, payload) -> None:
    client, _db = client_and_db
    response = client.post("/api/v1/decision-signals/reassess", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "extra_field",
    [
        "signal_id",
        "action",
        "score",
        "confidence",
        "horizon",
        "invalidation",
        "stop_loss",
        "target_price",
        "metadata",
        "scoring_breakdown",
        "guardrail_result",
    ],
)
def test_reassess_forbids_extra_fields(client_and_db, extra_field) -> None:
    client, _db = client_and_db
    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={
            "source_report_id": 1,
            "decision_profile": "balanced",
            "persist": False,
            extra_field: "not-supported",
        },
    )
    assert response.status_code == 422


def test_reassess_error_mapping(client_and_db) -> None:
    client, db = client_and_db

    missing = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": 999999, "decision_profile": "balanced", "persist": False},
    )
    assert missing.status_code == 404
    assert missing.json()["error"] == "source_report_not_found"

    market_review_id = _save_reassess_history(
        db,
        report_type="market_review",
        raw_result=_valid_reassess_raw(),
        context_snapshot=_valid_reassess_context(),
    )
    non_stock = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": market_review_id, "decision_profile": "balanced", "persist": False},
    )
    assert non_stock.status_code == 400
    assert non_stock.json()["error"] == "unsupported_report_type"

    insufficient_id = _save_reassess_history(
        db,
        code="600519",
        operation_advice=None,
        raw_result={"analysis_summary": "仅有摘要，不能推断动作"},
        context_snapshot=_valid_reassess_context(),
    )
    insufficient = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": insufficient_id, "decision_profile": "balanced", "persist": False},
    )
    assert insufficient.status_code == 400
    assert insufficient.json()["error"] == "unsupported_report_snapshot"

    unsupported_market_id = _save_reassess_history(
        db,
        code="NOT_A_VALID_US_SYMBOL",
        raw_result=_valid_reassess_raw(),
        context_snapshot=_valid_reassess_context(),
    )
    unsupported_market = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": unsupported_market_id, "decision_profile": "balanced", "persist": False},
    )
    assert unsupported_market.status_code == 400
    assert unsupported_market.json()["error"] == "unsupported_report_snapshot"


def test_reassess_success_preview_is_read_only_and_uses_opaque_metadata(client_and_db, monkeypatch) -> None:
    client, db = client_and_db
    record_id = _save_reassess_history(
        db,
        raw_result=_valid_reassess_raw(),
        context_snapshot=_valid_reassess_context(),
    )
    monkeypatch.setattr(
        "src.services.decision_signal_service.DecisionSignalService.create_signal_with_outcome",
        lambda *_args, **_kwargs: (
            _ for _ in ()
        ).throw(AssertionError("create_signal_with_outcome must not be called")),
    )
    monkeypatch.setattr(
        "src.services.decision_signal_service.DecisionSignalService.create_history_bound_signal_with_outcome",
        lambda *_args, **_kwargs: (
            _ for _ in ()
        ).throw(AssertionError("create_history_bound_signal_with_outcome must not be called")),
    )
    monkeypatch.setattr(
        "src.services.decision_signal_service.DecisionSignalService.list_signals",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("list_signals must not be called")),
    )
    monkeypatch.setattr(
        "src.services.analysis_context_builder._build_quote_block",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("reassess must not rebuild quote context")),
    )
    before = _decision_signal_count(db)

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "balanced", "persist": False},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["item"] is None
    assert payload["created"] is False
    assert payload["persist_status"] is None
    assert payload["preview"]["action"] == payload["preview"]["metadata"]["guardrail_result"]["final_action"]
    assert payload["preview"]["metadata"]["decision_profile"] == "balanced"
    assert payload["preview"]["metadata"]["profile_source"] == "user_selected"
    assert payload["preview"]["metadata"]["signal_generation_version"] == "decision-profile-reassess-v1"
    assert payload["preview"]["metadata"]["scoring_version"] == "decision-profile-scoring-v1"
    assert "scoring_breakdown" in payload["preview"]["metadata"]
    assert payload["preview"]["metadata"]["data_quality_level"] == "medium"
    assert payload["preview"]["entry_low"] == 1680
    assert payload["preview"]["stop_loss"] == 1600
    assert _decision_signal_count(db) == before


def test_reassess_preview_prefers_stability_adjusted_score(client_and_db) -> None:
    client, db = client_and_db
    raw_result = _valid_reassess_raw(
        action=None,
        sentiment_score=72,
        operation_advice="观望",
    )
    dashboard = raw_result["dashboard"]
    dashboard["decision_score_calibration"] = {
        "raw_score": 72,
        "adjusted_score": 59,
        "final_action": "watch",
        "guardrail_reason": "资金流偏弱，先观望回撤到 45-59。",
    }
    raw_result["dashboard"] = dashboard
    record_id = _save_reassess_history(
        db,
        raw_result=raw_result,
        context_snapshot=_valid_reassess_context(),
    )

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "balanced", "persist": False},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["preview"]["score"] == 59
    assert payload["preview"]["action"] == "watch"
    assert payload["preview"]["metadata"]["guardrail_result"]["final_action"] == "watch"
    assert _decision_signal_count(db) == 0


def test_reassess_service_has_no_live_market_provider_imports() -> None:
    source = (Path(__file__).resolve().parents[1] / "src/services/decision_signal_reassess_service.py").read_text(
        encoding="utf-8"
    )
    assert "data_provider" not in source
    assert "yfinance" not in source
    assert "akshare" not in source
    assert "build_decision_signal_payload_from_report" not in source


def test_reassess_confidence_missing_buy_is_safe_non_actionable_preview(client_and_db) -> None:
    client, db = client_and_db
    record_id = _save_reassess_history(
        db,
        raw_result=_valid_reassess_raw(confidence_level=None),
        context_snapshot=_valid_reassess_context(),
    )
    before = _decision_signal_count(db)

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "aggressive", "persist": False},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    guardrail = payload["preview"]["metadata"]["guardrail_result"]
    assert guardrail["raw_action"] == "buy"
    assert guardrail["final_action"] in {"watch", "alert"}
    assert guardrail["passed"] is True
    assert guardrail["adjusted"] is True
    assert "missing_confidence" in guardrail["violations"]
    assert payload["blocked_reason"] is None
    assert payload["warnings"]
    assert {warning["code"] for warning in payload["warnings"]} == {"action_adjusted_by_guardrail"}
    assert all(warning["message"] for warning in payload["warnings"])
    assert _decision_signal_count(db) == before


def test_reassess_persist_writes_authoritative_item_and_deduplicates(client_and_db) -> None:
    client, db = client_and_db
    record_id = _save_reassess_history(
        db,
        raw_result=_valid_reassess_raw(invalidation="跌破关键支撑且资金流转负"),
        context_snapshot=_valid_reassess_context(),
    )
    request = {
        "source_report_id": record_id,
        "decision_profile": "aggressive",
        "persist": True,
    }

    first = client.post("/api/v1/decision-signals/reassess", json=request)

    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["preview"] is None
    assert first_payload["created"] is True
    assert first_payload["persist_status"] == "created"
    item = first_payload["item"]
    assert item["decision_profile"] == "aggressive"
    assert item["source_type"] == "analysis"
    assert item["source_report_id"] == record_id
    assert item["source_agent"] == "decision_profile_reassess"
    assert item["trigger_source"] == "web:decision_profile_reassess"
    assert item["action"] == item["metadata"]["guardrail_result"]["final_action"]
    assert item["metadata"]["profile_source"] == "user_selected"
    assert item["metadata"]["profile_policy_version"] == "decision-profile-v1"
    assert item["metadata"]["signal_generation_version"] == "decision-profile-reassess-v1"
    assert item["metadata"]["scoring_version"] == "decision-profile-scoring-v1"
    assert item["metadata"]["scoring_breakdown"]
    assert item["metadata"]["data_quality_level"] == "medium"
    assert item["metadata"]["guardrail_result"]["passed"] is True

    second = client.post("/api/v1/decision-signals/reassess", json=request)
    assert second.status_code == 200, second.text
    assert second.json()["created"] is False
    assert second.json()["persist_status"] == "existing"
    assert second.json()["item"]["id"] == item["id"]
    assert _decision_signal_count(db) == 1

    timeline = client.get(
        "/api/v1/decision-signals",
        params={"stock_code": "600519", "decision_profile": "aggressive", "page_size": 100},
    )
    assert timeline.status_code == 200, timeline.text
    assert [signal["id"] for signal in timeline.json()["items"]] == [item["id"]]


def test_reassess_persist_anchors_expired_signal_to_report_lifecycle(client_and_db) -> None:
    client, db = client_and_db
    report_created_at = utc_naive_now().replace(microsecond=0) - timedelta(days=30)
    context = _valid_reassess_context()
    context["market_phase_summary"] = {
        "phase": "intraday",
        "session_date": "2026-06-15",
        "minutes_to_close": 5,
        "ignored_private_field": "must-not-persist",
    }
    record_id = _save_reassess_history(
        db,
        raw_result=_valid_reassess_raw(
            horizon="intraday",
            invalidation="跌破关键支撑且资金流转负",
        ),
        context_snapshot=context,
    )
    _set_reassess_history_created_at(db, record_id, report_created_at)
    service = DecisionSignalService(db_manager=db)
    expected_created_at = service._coerce_history_created_at_to_utc_naive(report_created_at)

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "aggressive", "persist": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    item = payload["item"]
    assert payload["persist_status"] == "created"
    assert item["status"] == "expired"
    assert datetime.fromisoformat(item["created_at"]) == expected_created_at
    assert datetime.fromisoformat(item["expires_at"]) == expected_created_at + timedelta(minutes=5)
    assert item["metadata"]["market_phase_summary"] == {
        "phase": "intraday",
        "session_date": "2026-06-15",
        "minutes_to_close": 5,
    }

    listed = client.get(
        "/api/v1/decision-signals",
        params={"source_type": "analysis", "source_report_id": record_id, "page_size": 100},
    )
    assert listed.status_code == 200, listed.text
    assert [listed_item["id"] for listed_item in listed.json()["items"]] == [item["id"]]
    latest = client.get("/api/v1/decision-signals/latest/600519", params={"limit": 5})
    assert latest.status_code == 200, latest.text
    assert latest.json()["items"] == []


def test_reassess_persist_uses_saved_raw_phase_summary_when_context_summary_is_missing(
    client_and_db,
) -> None:
    client, db = client_and_db
    report_created_at = utc_naive_now().replace(microsecond=0) - timedelta(days=30)
    raw = _valid_reassess_raw(
        horizon="intraday",
        invalidation="跌破关键支撑",
        market_phase_summary={"phase": "intraday", "minutes_to_close": 7},
    )
    context = _valid_reassess_context()
    context.pop("market_phase_summary")
    record_id = _save_reassess_history(db, raw_result=raw, context_snapshot=context)
    _set_reassess_history_created_at(db, record_id, report_created_at)
    expected_created_at = DecisionSignalService(
        db_manager=db
    )._coerce_history_created_at_to_utc_naive(report_created_at)

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "balanced", "persist": True},
    )

    assert response.status_code == 200, response.text
    item = response.json()["item"]
    assert item["status"] == "expired"
    assert datetime.fromisoformat(item["expires_at"]) == expected_created_at + timedelta(minutes=7)
    assert item["metadata"]["market_phase_summary"] == {
        "phase": "intraday",
        "minutes_to_close": 7,
    }


def test_reassess_persist_returns_final_invalidated_item_without_harming_newer_signal(
    client_and_db,
) -> None:
    client, db = client_and_db
    report_created_at = utc_naive_now().replace(microsecond=0) - timedelta(days=1)
    context = _valid_reassess_context()
    context["market_phase_summary"] = {"phase": "postmarket"}
    record_id = _save_reassess_history(
        db,
        raw_result=_valid_reassess_raw(
            horizon="3d",
            invalidation="跌破关键支撑且资金流转负",
        ),
        context_snapshot=context,
    )
    _set_reassess_history_created_at(db, record_id, report_created_at)
    newer_sell = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            action="sell",
            score=20,
            decision_profile="aggressive",
            source_report_id=record_id + 1000,
            trace_id="trace-newer-aggressive-sell",
            market_phase="postmarket",
            horizon="3d",
        ),
    ).json()["item"]

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "aggressive", "persist": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    item = payload["item"]
    assert payload["persist_status"] == "created"
    assert item["status"] == "invalidated"
    assert item["metadata"]["invalidated_by_signal_id"] == newer_sell["id"]
    assert client.get(f"/api/v1/decision-signals/{newer_sell['id']}").json()["status"] == "active"
    latest = client.get("/api/v1/decision-signals/latest/600519", params={"limit": 5})
    assert [latest_item["id"] for latest_item in latest.json()["items"]] == [newer_sell["id"]]


def test_reassess_history_refresh_uses_created_at_not_updated_at_for_invalidation(
    client_and_db,
) -> None:
    client, db = client_and_db
    report_created_at = utc_naive_now().replace(microsecond=0) - timedelta(days=1)
    raw = _valid_reassess_raw(horizon="3d", invalidation="跌破关键支撑")
    context = _valid_reassess_context()
    context["market_phase_summary"] = {"phase": "postmarket"}
    record_id = _save_reassess_history(db, raw_result=raw, context_snapshot=context)
    _set_reassess_history_created_at(db, record_id, report_created_at)
    auto_item = _persist_auto_balanced_signal(
        db,
        source_report_id=record_id,
        raw_result=raw,
        context_snapshot=context,
    )
    expected_created_at = DecisionSignalService(
        db_manager=db
    )._coerce_history_created_at_to_utc_naive(report_created_at)
    with db.session_scope() as session:
        row = session.query(DecisionSignalRecord).filter(DecisionSignalRecord.id == auto_item["id"]).one()
        row.created_at = expected_created_at
        row.status = "expired"
        row.expires_at = utc_naive_now() - timedelta(minutes=1)
        row.updated_at = utc_naive_now() - timedelta(minutes=1)
    newer_sell = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            action="sell",
            score=20,
            decision_profile="balanced",
            source_report_id=record_id + 2000,
            trace_id="trace-newer-balanced-sell",
            market_phase="postmarket",
            horizon="3d",
        ),
    ).json()["item"]

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "balanced", "persist": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["persist_status"] == "refreshed"
    assert payload["item"]["id"] == auto_item["id"]
    assert payload["item"]["status"] == "invalidated"
    assert payload["item"]["metadata"]["invalidated_by_signal_id"] == newer_sell["id"]
    assert client.get(f"/api/v1/decision-signals/{newer_sell['id']}").json()["status"] == "active"


def test_reassess_persist_requires_report_time_without_breaking_preview(client_and_db) -> None:
    client, db = client_and_db
    record_id = _save_reassess_history(
        db,
        raw_result=_valid_reassess_raw(invalidation="跌破关键支撑"),
        context_snapshot=_valid_reassess_context(),
    )
    _set_reassess_history_created_at(db, record_id, None)
    before = _decision_signal_count(db)

    preview = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "balanced", "persist": False},
    )
    persisted = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "balanced", "persist": True},
    )

    assert preview.status_code == 200, preview.text
    assert preview.json()["preview"] is not None
    assert persisted.status_code == 400, persisted.text
    assert persisted.json()["error"] == "unsupported_report_snapshot"
    assert _decision_signal_count(db) == before


def test_reassess_balanced_persist_creates_when_auto_extraction_has_no_signal(client_and_db) -> None:
    client, db = client_and_db
    record_id = _save_reassess_history(
        db,
        raw_result=_valid_reassess_raw(invalidation="跌破关键支撑"),
        context_snapshot=_valid_reassess_context(),
    )

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "balanced", "persist": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["persist_status"] == "created"
    assert payload["created"] is True
    assert payload["item"]["decision_profile"] == "balanced"
    assert payload["item"]["source_agent"] == "decision_profile_reassess"
    assert payload["item"]["trigger_source"] == "web:decision_profile_reassess"
    assert payload["item"]["metadata"]["profile_source"] == "user_selected"
    assert payload["item"]["metadata"]["scoring_breakdown"]
    assert _decision_signal_count(db) == 1


def test_reassess_balanced_persist_reuses_actual_auto_generated_signal(client_and_db) -> None:
    client, db = client_and_db
    raw = _valid_reassess_raw(invalidation="跌破关键支撑")
    context = _valid_reassess_context()
    record_id = _save_reassess_history(db, raw_result=raw, context_snapshot=context)
    auto_item = _persist_auto_balanced_signal(
        db,
        source_report_id=record_id,
        raw_result=raw,
        context_snapshot=context,
    )

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "balanced", "persist": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["persist_status"] == "existing"
    assert payload["created"] is False
    assert payload["item"]["id"] == auto_item["id"]
    assert payload["item"]["source_agent"] == auto_item["source_agent"]
    assert payload["item"]["trigger_source"] == "api"
    assert payload["item"]["metadata"]["profile_source"] == "auto_default"
    assert payload["item"]["metadata"]["signal_generation_version"] == "legacy-report-extractor-v1"
    assert "scoring_breakdown" not in payload["item"]["metadata"]
    assert _decision_signal_count(db) == 1


def test_reassess_balanced_persist_refreshes_expired_auto_generated_signal(client_and_db) -> None:
    client, db = client_and_db
    raw = _valid_reassess_raw(invalidation="跌破关键支撑")
    context = _valid_reassess_context()
    record_id = _save_reassess_history(db, raw_result=raw, context_snapshot=context)
    auto_item = _persist_auto_balanced_signal(
        db,
        source_report_id=record_id,
        raw_result=raw,
        context_snapshot=context,
    )
    with db.session_scope() as session:
        row = session.query(DecisionSignalRecord).filter(DecisionSignalRecord.id == auto_item["id"]).one()
        row.status = "expired"
        row.expires_at = utc_naive_now() - timedelta(minutes=1)
        row.updated_at = utc_naive_now() - timedelta(minutes=1)

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "balanced", "persist": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["persist_status"] == "refreshed"
    assert payload["created"] is False
    assert payload["item"]["id"] == auto_item["id"]
    assert payload["item"]["status"] == "active"
    assert payload["item"]["created_at"] == auto_item["created_at"]
    assert payload["item"]["source_agent"] == auto_item["source_agent"]
    assert payload["item"]["trigger_source"] == "api"
    assert payload["item"]["metadata"]["profile_source"] == "user_selected"
    assert payload["item"]["metadata"]["signal_generation_version"] == "decision-profile-reassess-v1"
    assert payload["item"]["metadata"]["scoring_breakdown"]
    assert payload["item"]["action"] == payload["item"]["metadata"]["guardrail_result"]["final_action"]
    assert _decision_signal_count(db) == 1


def test_reassess_balanced_persist_reports_relaxed_phase_fill_without_overwriting_auto_metadata(
    client_and_db,
) -> None:
    client, db = client_and_db
    raw = _valid_reassess_raw(invalidation="跌破关键支撑")
    context = _valid_reassess_context()
    record_id = _save_reassess_history(db, raw_result=raw, context_snapshot=context)
    auto_item = _persist_auto_balanced_signal(
        db,
        source_report_id=record_id,
        raw_result=raw,
        context_snapshot=context,
    )
    with db.session_scope() as session:
        row = session.query(DecisionSignalRecord).filter(DecisionSignalRecord.id == auto_item["id"]).one()
        row.market_phase = None
        row.updated_at = utc_naive_now()

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "balanced", "persist": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["persist_status"] == "refreshed"
    assert payload["created"] is False
    assert payload["item"]["id"] == auto_item["id"]
    assert payload["item"]["market_phase"] == "intraday"
    assert payload["item"]["source_agent"] == auto_item["source_agent"]
    assert payload["item"]["trigger_source"] == "api"
    assert payload["item"]["metadata"]["profile_source"] == "auto_default"
    assert payload["item"]["metadata"]["signal_generation_version"] == "legacy-report-extractor-v1"
    assert "scoring_breakdown" not in payload["item"]["metadata"]
    assert _decision_signal_count(db) == 1


@pytest.mark.parametrize("terminal_status", ["closed", "invalidated", "archived"])
def test_reassess_balanced_persist_returns_terminal_auto_signal_without_reactivation(
    client_and_db,
    terminal_status,
) -> None:
    client, db = client_and_db
    raw = _valid_reassess_raw(invalidation="跌破关键支撑")
    context = _valid_reassess_context()
    record_id = _save_reassess_history(db, raw_result=raw, context_snapshot=context)
    auto_item = _persist_auto_balanced_signal(
        db,
        source_report_id=record_id,
        raw_result=raw,
        context_snapshot=context,
    )
    with db.session_scope() as session:
        row = session.query(DecisionSignalRecord).filter(DecisionSignalRecord.id == auto_item["id"]).one()
        row.status = terminal_status
        row.updated_at = utc_naive_now()

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "balanced", "persist": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["persist_status"] == "existing"
    assert payload["created"] is False
    assert payload["item"]["id"] == auto_item["id"]
    assert payload["item"]["status"] == terminal_status
    assert payload["item"]["metadata"]["profile_source"] == "auto_default"
    assert _decision_signal_count(db) == 1


def test_reassess_persist_distinguishes_profiles(client_and_db) -> None:
    client, db = client_and_db
    record_id = _save_reassess_history(
        db,
        raw_result=_valid_reassess_raw(invalidation="跌破关键支撑"),
        context_snapshot=_valid_reassess_context(),
    )

    aggressive = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "aggressive", "persist": True},
    )
    conservative = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "conservative", "persist": True},
    )

    assert aggressive.status_code == 200, aggressive.text
    assert conservative.status_code == 200, conservative.text
    assert aggressive.json()["item"]["id"] != conservative.json()["item"]["id"]
    assert aggressive.json()["item"]["decision_profile"] == "aggressive"
    assert conservative.json()["item"]["decision_profile"] == "conservative"
    assert _decision_signal_count(db) == 2


def test_reassess_persist_invalidates_only_same_profile_opposing_signal(client_and_db) -> None:
    client, db = client_and_db
    balanced_sell = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            action="sell",
            score=20,
            decision_profile="balanced",
            source_report_id=4101,
            trace_id="trace-balanced-sell",
        ),
    ).json()["item"]
    aggressive_sell = client.post(
        "/api/v1/decision-signals",
        json=_payload(
            action="sell",
            score=20,
            decision_profile="aggressive",
            source_report_id=4102,
            trace_id="trace-aggressive-sell",
        ),
    ).json()["item"]
    record_id = _save_reassess_history(
        db,
        raw_result=_valid_reassess_raw(invalidation="跌破关键支撑"),
        context_snapshot=_valid_reassess_context(),
    )

    persisted = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "aggressive", "persist": True},
    )

    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["item"]["action"] == "buy"
    assert client.get(f"/api/v1/decision-signals/{aggressive_sell['id']}").json()["status"] == "invalidated"
    assert client.get(f"/api/v1/decision-signals/{balanced_sell['id']}").json()["status"] == "active"


def test_reassess_persist_saves_safe_guardrail_downgrade_with_audit_metadata(client_and_db) -> None:
    client, db = client_and_db
    record_id = _save_reassess_history(
        db,
        raw_result=_valid_reassess_raw(confidence_level=None),
        context_snapshot=_valid_reassess_context(),
    )

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": "aggressive", "persist": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    guardrail = payload["item"]["metadata"]["guardrail_result"]
    assert payload["item"]["action"] == "watch"
    assert guardrail["raw_action"] == "buy"
    assert guardrail["final_action"] == "watch"
    assert guardrail["passed"] is True
    assert guardrail["adjusted"] is True
    assert guardrail["violations"]
    assert guardrail["adjustments"]
    assert payload["warnings"]
    assert all(warning["message"] for warning in payload["warnings"])
    assert _decision_signal_count(db) == 1


@pytest.mark.parametrize("decision_profile", ["balanced", "aggressive"])
def test_reassess_persist_guardrail_block_returns_structured_error_without_write(
    client_and_db,
    decision_profile,
) -> None:
    client, db = client_and_db
    record_id = _save_reassess_history(
        db,
        raw_result=_valid_reassess_raw(invalidation="跌破关键支撑"),
        context_snapshot=_valid_reassess_context(),
        stop_loss=1900,
        take_profit=1800,
    )
    before = _decision_signal_count(db)

    response = client.post(
        "/api/v1/decision-signals/reassess",
        json={"source_report_id": record_id, "decision_profile": decision_profile, "persist": True},
    )

    assert response.status_code == 400, response.text
    payload = response.json()
    assert payload["error"] == "guardrail_blocked"
    assert payload["blocked_reason"]
    assert {warning["code"] for warning in payload["warnings"]} >= {
        "action_adjusted_by_guardrail",
        "action_blocked_by_guardrail",
    }
    assert all(warning["message"] for warning in payload["warnings"])
    assert "created" not in payload
    assert _decision_signal_count(db) == before
