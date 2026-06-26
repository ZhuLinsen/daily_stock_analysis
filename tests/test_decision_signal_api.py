# -*- coding: utf-8 -*-
"""API tests for DecisionSignal P1."""

from __future__ import annotations

import os
import sys
import time
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
from src.config import Config
from src.storage import DatabaseManager, DecisionSignalRecord, PortfolioAccount, PortfolioPosition, utc_naive_now


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
        json={"status": "closed", "metadata": {"closed_by": "api-test"}},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["status"] == "closed"
    assert patch_resp.json()["metadata"]["closed_by"] == "api-test"
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
