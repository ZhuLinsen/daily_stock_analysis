# -*- coding: utf-8 -*-
"""Integration tests for Alert API MVP (Issue #1202 P1)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
from fastapi.testclient import TestClient

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.repositories.alert_repo import AlertRepository
from src.storage import AlertCooldownRecord, AlertNotificationRecord, AlertTriggerRecord, Base, DatabaseManager


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


class AlertApiTestCase(unittest.TestCase):
    """Alert API contract tests for P1 rule and history endpoints."""

    def setUp(self) -> None:
        _reset_auth_globals()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_path = self.data_dir / ".env"
        self.db_path = self.data_dir / "alert_api_test.db"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519",
                    "GEMINI_API_KEY=test",
                    "ADMIN_AUTH_ENABLED=false",
                    'AGENT_EVENT_ALERT_RULES_JSON=[{"stock_code":"000001","alert_type":"price_cross","direction":"above","price":10}]',
                    f"DATABASE_PATH={self.db_path}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(self.db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        app = create_app(static_dir=self.data_dir / "empty-static")
        self.client = TestClient(app)
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()
        _reset_auth_globals()

    def _create_rule(self, payload: dict | None = None) -> dict:
        body = {
            "name": "Moutai breakout",
            "target_scope": "single_symbol",
            "target": "600519",
            "alert_type": "price_cross",
            "parameters": {"direction": "above", "price": 1800},
            "severity": "warning",
            "enabled": True,
        }
        if payload:
            body.update(payload)
        resp = self.client.post("/api/v1/alerts/rules", json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def test_rule_crud_enable_disable_and_delete(self) -> None:
        created = self._create_rule()
        rule_id = created["id"]
        self.assertEqual(created["target"], "600519")
        self.assertEqual(created["alert_type"], "price_cross")
        self.assertEqual(created["parameters"]["price"], 1800.0)
        self.assertTrue(created["enabled"])
        self.assertEqual(created["source"], "api")
        self.assertIsNone(created["last_triggered_at"])
        self.assertIsNone(created["cooldown_until"])
        self.assertFalse(created["cooldown_active"])
        self.assertIsNotNone(created["created_at"])
        self.assertIsNotNone(created["updated_at"])

        list_resp = self.client.get("/api/v1/alerts/rules")
        self.assertEqual(list_resp.status_code, 200)
        payload = list_resp.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["id"], rule_id)

        detail_resp = self.client.get(f"/api/v1/alerts/rules/{rule_id}")
        self.assertEqual(detail_resp.status_code, 200)
        self.assertEqual(detail_resp.json()["id"], rule_id)

        patch_resp = self.client.patch(
            f"/api/v1/alerts/rules/{rule_id}",
            json={"enabled": False, "parameters": {"direction": "below", "price": 1600}},
        )
        self.assertEqual(patch_resp.status_code, 200, patch_resp.text)
        self.assertFalse(patch_resp.json()["enabled"])
        self.assertEqual(patch_resp.json()["parameters"], {"direction": "below", "price": 1600.0})

        enable_resp = self.client.post(f"/api/v1/alerts/rules/{rule_id}/enable")
        self.assertEqual(enable_resp.status_code, 200)
        self.assertTrue(enable_resp.json()["enabled"])

        disable_resp = self.client.post(f"/api/v1/alerts/rules/{rule_id}/disable")
        self.assertEqual(disable_resp.status_code, 200)
        self.assertFalse(disable_resp.json()["enabled"])

        delete_resp = self.client.delete(f"/api/v1/alerts/rules/{rule_id}")
        self.assertEqual(delete_resp.status_code, 200)
        self.assertEqual(delete_resp.json(), {"deleted": 1})

        missing_resp = self.client.get(f"/api/v1/alerts/rules/{rule_id}")
        self.assertEqual(missing_resp.status_code, 404)

    def test_rule_response_includes_server_cooldown_active_flag(self) -> None:
        created = self._create_rule()
        repo = AlertRepository(self.db)
        now_dt = datetime.now()
        cooldown_until = now_dt + timedelta(minutes=5)
        repo.upsert_cooldown(
            rule_id=created["id"],
            rule_key="single_symbol:600519:price_cross:{}",
            target="600519",
            severity="warning",
            last_triggered_at=now_dt,
            cooldown_until=cooldown_until,
            reason="active cooldown",
        )

        list_resp = self.client.get("/api/v1/alerts/rules")
        self.assertEqual(list_resp.status_code, 200, list_resp.text)
        item = list_resp.json()["items"][0]
        self.assertEqual(item["id"], created["id"])
        self.assertEqual(item["cooldown_until"], cooldown_until.isoformat())
        self.assertTrue(item["cooldown_active"])

        expired_at = datetime.now() - timedelta(minutes=5)
        repo.upsert_cooldown(
            rule_id=created["id"],
            rule_key="single_symbol:600519:price_cross:{}",
            target="600519",
            severity="warning",
            last_triggered_at=expired_at,
            cooldown_until=expired_at,
            reason="expired cooldown",
        )

        detail_resp = self.client.get(f"/api/v1/alerts/rules/{created['id']}")
        self.assertEqual(detail_resp.status_code, 200, detail_resp.text)
        self.assertFalse(detail_resp.json()["cooldown_active"])

    def test_rule_update_rejects_empty_payload(self) -> None:
        rule = self._create_rule()

        resp = self.client.patch(f"/api/v1/alerts/rules/{rule['id']}", json={})

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "validation_error")

    def test_rule_update_rejects_null_for_non_nullable_fields(self) -> None:
        rule = self._create_rule()

        for field_name in ("enabled", "severity", "name"):
            resp = self.client.patch(f"/api/v1/alerts/rules/{rule['id']}", json={field_name: None})
            self.assertEqual(resp.status_code, 400, resp.text)
            self.assertEqual(resp.json()["error"], "validation_error")

        detail_resp = self.client.get(f"/api/v1/alerts/rules/{rule['id']}")
        self.assertEqual(detail_resp.status_code, 200)
        detail = detail_resp.json()
        self.assertTrue(detail["enabled"])
        self.assertEqual(detail["severity"], "warning")
        self.assertEqual(detail["name"], "Moutai breakout")

    def test_rule_update_allows_null_for_reserved_policy_fields(self) -> None:
        rule = self._create_rule(
            {
                "cooldown_policy": {"cooldown_seconds": 60},
                "notification_policy": {"channels": ["wechat"]},
            }
        )

        resp = self.client.patch(
            f"/api/v1/alerts/rules/{rule['id']}",
            json={"cooldown_policy": None, "notification_policy": None},
        )

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIsNone(resp.json()["cooldown_policy"])
        self.assertIsNone(resp.json()["notification_policy"])

    def test_supported_rule_types_and_filters(self) -> None:
        self._create_rule()
        self._create_rule(
            {
                "name": "CATL drop",
                "target": "300750",
                "alert_type": "price_change_percent",
                "parameters": {"direction": "down", "change_pct": 3.5},
                "enabled": False,
            }
        )
        self._create_rule(
            {
                "name": "Wuliangye volume",
                "target": "000858",
                "alert_type": "volume_spike",
                "parameters": {"multiplier": 2.5},
            }
        )

        resp = self.client.get(
            "/api/v1/alerts/rules",
            params={"alert_type": "price_change_percent", "enabled": False},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["target"], "300750")
        self.assertEqual(payload["items"][0]["parameters"]["change_pct"], 3.5)

    def test_rejects_unsupported_and_invalid_rules(self) -> None:
        unsupported = self.client.post(
            "/api/v1/alerts/rules",
            json={
                "target_scope": "single_symbol",
                "target": "600519",
                "alert_type": "sentiment_shift",
                "parameters": {},
            },
        )
        self.assertEqual(unsupported.status_code, 400)
        self.assertEqual(unsupported.json()["error"], "unsupported_alert_type")

        invalid_price = self.client.post(
            "/api/v1/alerts/rules",
            json={
                "target_scope": "single_symbol",
                "target": "600519",
                "alert_type": "price_cross",
                "parameters": {"direction": "sideways", "price": 0},
            },
        )
        self.assertEqual(invalid_price.status_code, 400)
        self.assertEqual(invalid_price.json()["error"], "validation_error")

        missing_target = self.client.post(
            "/api/v1/alerts/rules",
            json={"target_scope": "single_symbol", "alert_type": "price_cross", "parameters": {"price": 10}},
        )
        self.assertEqual(missing_target.status_code, 422)

    def test_dry_run_price_cross_uses_mocked_quote_and_does_not_write_history(self) -> None:
        rule = self._create_rule()

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1800.0)),
        ) as quote:
            resp = self.client.post(f"/api/v1/alerts/rules/{rule['id']}/test")

        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertTrue(payload["triggered"])
        self.assertEqual(payload["status"], "triggered")
        self.assertEqual(payload["observed_value"], 1800.0)
        quote.assert_awaited_once_with("600519")

        self.assertEqual(self.client.get("/api/v1/alerts/triggers").json()["total"], 0)
        self.assertEqual(self.client.get("/api/v1/alerts/notifications").json()["total"], 0)

    def test_dry_run_price_cross_not_triggered_keeps_observed_value(self) -> None:
        rule = self._create_rule()

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=SimpleNamespace(price=1700.0)),
        ):
            resp = self.client.post(f"/api/v1/alerts/rules/{rule['id']}/test")

        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertFalse(payload["triggered"])
        self.assertEqual(payload["status"], "not_triggered")
        self.assertEqual(payload["observed_value"], 1700.0)

    def test_dry_run_quote_exception_returns_evaluation_error_and_sanitizes_message(self) -> None:
        rule = self._create_rule()

        async def _raise_quote_error(_stock_code):
            raise RuntimeError("token=secret-token failed at https://example.com/webhook")

        with patch("src.agent.events.EventMonitor._get_realtime_quote", new=_raise_quote_error):
            resp = self.client.post(f"/api/v1/alerts/rules/{rule['id']}/test")

        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertFalse(payload["triggered"])
        self.assertEqual(payload["status"], "evaluation_error")
        self.assertNotIn("secret-token", payload["message"])
        self.assertNotIn("example.com/webhook", payload["message"])

    def test_dry_run_price_change_supports_quote_aliases(self) -> None:
        rule = self._create_rule(
            {
                "target": "300750",
                "alert_type": "price_change_percent",
                "parameters": {"direction": "down", "change_pct": 3.25},
            }
        )

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value={"pct_chg": " -3.25% "}),
        ):
            resp = self.client.post(f"/api/v1/alerts/rules/{rule['id']}/test")

        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertTrue(payload["triggered"])
        self.assertEqual(payload["observed_value"], -3.25)

    def test_dry_run_volume_spike_uses_mocked_daily_data(self) -> None:
        rule = self._create_rule(
            {
                "target": "000858",
                "alert_type": "volume_spike",
                "parameters": {"multiplier": 2.5},
            }
        )
        df = pd.DataFrame({"volume": [100.0] * 19 + [300.0]})
        manager = MagicMock()
        manager.get_daily_data.return_value = (df, "unit-test")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            resp = self.client.post(f"/api/v1/alerts/rules/{rule['id']}/test")

        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertTrue(payload["triggered"])
        self.assertEqual(payload["status"], "triggered")
        manager.get_daily_data.assert_called_once_with("000858", days=20)

    def test_dry_run_volume_exception_returns_evaluation_error(self) -> None:
        rule = self._create_rule(
            {
                "target": "000858",
                "alert_type": "volume_spike",
                "parameters": {"multiplier": 2.5},
            }
        )
        manager = MagicMock()
        manager.get_daily_data.side_effect = RuntimeError("sendkey=secret-token data source failed")

        async def _run_inline(func, *args, **kwargs):
            return func(*args, **kwargs)

        with patch("data_provider.DataFetcherManager", return_value=manager), \
             patch("src.services.alert_service.asyncio.to_thread", new=_run_inline):
            resp = self.client.post(f"/api/v1/alerts/rules/{rule['id']}/test")

        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertEqual(payload["status"], "evaluation_error")
        self.assertFalse(payload["triggered"])
        self.assertNotIn("secret-token", payload["message"])

    def test_dry_run_missing_data_returns_not_triggered(self) -> None:
        rule = self._create_rule()

        with patch(
            "src.agent.events.EventMonitor._get_realtime_quote",
            new=AsyncMock(return_value=None),
        ):
            resp = self.client.post(f"/api/v1/alerts/rules/{rule['id']}/test")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "not_triggered")
        self.assertFalse(resp.json()["triggered"])

    def test_legacy_json_config_is_not_rewritten(self) -> None:
        before = self.env_path.read_text(encoding="utf-8")
        self._create_rule()
        after = self.env_path.read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertIn("AGENT_EVENT_ALERT_RULES_JSON", after)

    def test_trigger_and_notification_queries_are_paginated_and_sanitized(self) -> None:
        rule = self._create_rule()
        with self.db.get_session() as session:
            trigger = AlertTriggerRecord(
                rule_id=rule["id"],
                target="600519",
                observed_value=1810.0,
                threshold=1800.0,
                reason="breakout",
                data_source="unit-test",
                triggered_at=datetime(2026, 1, 1, 9, 30),
                status="triggered",
                diagnostics="url=https://example.com/hook?token=secret-token",
            )
            session.add(trigger)
            session.commit()
            session.refresh(trigger)
            notification = AlertNotificationRecord(
                trigger_id=trigger.id,
                channel="wechat",
                attempt=1,
                success=False,
                error_code="timeout",
                retryable=True,
                latency_ms=123,
                diagnostics="Bearer secret-token timeout at https://example.com/webhook?key=secret",
            )
            session.add(notification)
            session.commit()

        trigger_resp = self.client.get("/api/v1/alerts/triggers", params={"page": 1, "page_size": 10})
        self.assertEqual(trigger_resp.status_code, 200)
        trigger_payload = trigger_resp.json()
        self.assertEqual(trigger_payload["total"], 1)
        self.assertNotIn("secret-token", str(trigger_payload))
        self.assertNotIn("example.com/hook", str(trigger_payload))

        notification_resp = self.client.get("/api/v1/alerts/notifications", params={"channel": "wechat"})
        self.assertEqual(notification_resp.status_code, 200)
        notification_payload = notification_resp.json()
        self.assertEqual(notification_payload["total"], 1)
        self.assertTrue(notification_payload["items"][0]["retryable"])
        self.assertNotIn("secret-token", str(notification_payload))
        self.assertNotIn("example.com/webhook", str(notification_payload))

    def test_alert_cooldowns_table_create_all_is_idempotent(self) -> None:
        constraint_names = {constraint.name for constraint in AlertCooldownRecord.__table__.constraints}
        self.assertIn("uix_alert_cooldown_rule_target_severity", constraint_names)

        Base.metadata.create_all(self.db._engine)
        Base.metadata.create_all(self.db._engine)

        with self.db.get_session() as session:
            session.add(
                AlertCooldownRecord(
                    rule_id=1,
                    rule_key="single_symbol:600519:price_cross:{}",
                    target="600519",
                    severity="warning",
                    state="active",
                )
            )
            session.commit()
            count = session.query(AlertCooldownRecord).count()

        self.assertEqual(count, 1)

    def test_alert_cooldown_upsert_keeps_one_row_per_rule_target_severity(self) -> None:
        repo = AlertRepository(self.db)
        first = repo.upsert_cooldown(
            rule_id=1,
            rule_key="single_symbol:600519:price_cross:{}",
            target="600519",
            severity="warning",
            last_triggered_at=datetime(2026, 5, 18, 10, 0, 0),
            cooldown_until=datetime(2026, 5, 18, 11, 0, 0),
            reason="first trigger",
        )
        second = repo.upsert_cooldown(
            rule_id=1,
            rule_key="single_symbol:600519:price_cross:{}",
            target="600519",
            severity="warning",
            last_triggered_at=datetime(2026, 5, 18, 10, 30, 0),
            cooldown_until=datetime(2026, 5, 18, 11, 30, 0),
            reason="updated trigger",
        )

        with self.db.get_session() as session:
            rows = session.query(AlertCooldownRecord).all()

        self.assertEqual(first.id, second.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].reason, "updated trigger")
        self.assertEqual(rows[0].cooldown_until, datetime(2026, 5, 18, 11, 30, 0))


if __name__ == "__main__":
    unittest.main()
