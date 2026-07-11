# -*- coding: utf-8 -*-
"""Tests for Market Light alert evaluation."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src.services.market_light_alerts import (
    MarketLightAlert,
    evaluate_market_light_alert,
    normalize_market_alert_parameters,
)


def _snapshot(
    *,
    trade_date: str = "2026-03-07",
    score: int = 45,
    status: str = "yellow",
    data_quality: str = "ok",
    breadth_available: bool = True,
    index_available: bool = True,
    limit_available: bool = True,
) -> dict:
    return {
        "region": "cn",
        "trade_date": trade_date,
        "status": status,
        "score": score,
        "label": "需观察",
        "temperature_label": "震荡",
        "reasons": ["test"],
        "guidance": "test",
        "dimensions": {
            "breadth": {"score": 50, "available": breadth_available},
            "index": {"score": 50, "available": index_available},
            "limit": {"score": 50, "available": limit_available},
        },
        "data_quality": data_quality,
    }


class MarketLightAlertsTestCase(unittest.TestCase):
    def _rule(self, alert_type: str, parameters: dict) -> MarketLightAlert:
        return MarketLightAlert(
            target_scope="market",
            target="cn",
            alert_type=alert_type,
            parameters=parameters,
            metadata={"persisted_rule_id": 7, "trading_day_check_enabled": False},
        )

    def test_normalize_status_rejects_green(self) -> None:
        with self.assertRaisesRegex(ValueError, "red or yellow"):
            normalize_market_alert_parameters("market_light_status", {"statuses": ["green"]})

    def test_market_light_alert_rejects_jp_kr_targets(self) -> None:
        for region in ("jp", "kr"):
            with self.subTest(region=region):
                with self.assertRaisesRegex(ValueError, "cn, hk, us"):
                    MarketLightAlert(
                        target_scope="market",
                        target=region,
                        alert_type="market_light_status",
                        parameters={"statuses": ["red"]},
                    )

    def test_status_unavailable_is_skipped(self) -> None:
        result = evaluate_market_light_alert(
            self._rule("market_light_status", {"statuses": ["red", "yellow"]}),
            current_snapshot=_snapshot(data_quality="unavailable", index_available=False),
        )

        self.assertFalse(result["triggered"])
        self.assertEqual(result["record_status"], "skipped")
        self.assertEqual(result["data_source"], "market_light")

    def test_status_partial_triggers_with_missing_dimensions_diagnostics(self) -> None:
        result = evaluate_market_light_alert(
            self._rule("market_light_status", {"statuses": ["yellow"]}),
            current_snapshot=_snapshot(data_quality="partial", breadth_available=False, limit_available=False),
        )

        self.assertTrue(result["triggered"])
        diagnostics = json.loads(result["diagnostics"])
        self.assertEqual(diagnostics["data_quality"], "partial")
        self.assertEqual(diagnostics["missing_dimensions"], ["breadth", "limit"])
        self.assertEqual(result["data_timestamp"].isoformat(), "2026-03-07T00:00:00")

    def test_score_drop_uses_previous_trade_date_and_allows_partial_comparison(self) -> None:
        previous = _snapshot(
            trade_date="2026-03-06",
            score=75,
            status="green",
            data_quality="partial",
            limit_available=False,
        )
        current = _snapshot(trade_date="2026-03-07", score=55, data_quality="partial", breadth_available=False)

        with patch("src.services.market_light_alerts.load_previous_snapshot", return_value=previous):
            result = evaluate_market_light_alert(
                self._rule("market_light_score_drop", {"min_drop": 10.0}),
                current_snapshot=current,
            )

        self.assertTrue(result["triggered"])
        self.assertEqual(result["observed_value"], 55.0)
        self.assertEqual(result["threshold"], 10.0)
        diagnostics = json.loads(result["diagnostics"])
        self.assertTrue(diagnostics["partial_comparison"])
        self.assertEqual(diagnostics["prev_score"], 75)
        self.assertEqual(diagnostics["prev_trade_date"], "2026-03-06")
        self.assertEqual(diagnostics["missing_dimensions"], ["breadth", "limit"])

    def test_score_drop_without_previous_snapshot_is_skipped(self) -> None:
        with patch("src.services.market_light_alerts.load_previous_snapshot", return_value=None):
            result = evaluate_market_light_alert(
                self._rule("market_light_score_drop", {"min_drop": 10.0}),
                current_snapshot=_snapshot(),
            )

        self.assertFalse(result["triggered"])
        self.assertEqual(result["record_status"], "skipped")

    def test_score_drop_previous_snapshot_parse_error_is_degraded(self) -> None:
        with patch(
            "src.services.market_light_alerts.load_previous_snapshot",
            side_effect=ValueError("invalid persisted market light snapshot"),
        ):
            result = evaluate_market_light_alert(
                self._rule("market_light_score_drop", {"min_drop": 10.0}),
                current_snapshot=_snapshot(),
            )

        self.assertFalse(result["triggered"])
        self.assertEqual(result["record_status"], "degraded")
        diagnostics = json.loads(result["diagnostics"])
        self.assertIn("invalid persisted market light snapshot", diagnostics["error"])


if __name__ == "__main__":
    unittest.main()
