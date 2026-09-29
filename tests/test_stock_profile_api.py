# -*- coding: utf-8 -*-
"""Contract tests for the stock profile aggregate endpoint."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
import pytest

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.services.stock_profile_service import InvalidStockProfileCode, StockProfileService
from src.storage import DatabaseManager


def test_stock_profile_service_import_is_independent_of_api_bootstrap() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.services.stock_profile_service import StockProfileService; "
            "assert StockProfileService.__name__ == 'StockProfileService'",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _quote(code: str = "AAPL") -> dict:
    return {
        "stock_code": code,
        "stock_name": "Apple",
        "current_price": 200.0,
        "change": 1.0,
        "change_percent": 0.5,
        "update_time": "2026-08-29T10:00:00+08:00",
    }


def _history() -> dict:
    return {
        "data": [
            {
                "date": "2026-08-28",
                "open": 198.0,
                "high": 202.0,
                "low": 197.0,
                "close": 200.0,
                "volume": 1000.0,
            }
        ]
    }


def _report_list() -> dict:
    return {
        "items": [
            {
                "id": 12,
                "query_id": "query-12",
                "stock_code": "AAPL",
                "stock_name": "Apple",
                "analysis_summary": "Demand remains resilient",
                "sentiment_score": 70,
                "created_at": "2026-08-28T12:00:00+08:00",
            }
        ],
        "total": 1,
    }


def _report_detail() -> dict:
    return {
        "id": 12,
        "query_id": "query-12",
        "stock_code": "AAPL",
        "stock_name": "Apple",
        "analysis_summary": "Demand remains resilient",
        "operation_advice": "Watch",
        "action": "watch",
        "action_label": "Watch",
        "trend_prediction": "Neutral",
        "sentiment_score": 70,
        "stop_loss": "180",
        "created_at": "2026-08-28T12:00:00+08:00",
        "context_snapshot": None,
    }


def _intelligence(code: str = "AAPL", market: str = "us") -> dict:
    return {
        "items": [
            {
                "id": 5,
                "source_type": "rss",
                "title": "Company update",
                "url": "https://example.com/update",
                "scope_type": "symbol",
                "scope_value": code,
                "market": market,
            }
        ],
        "total": 1,
    }


def _service(**overrides: object) -> tuple[StockProfileService, dict[str, MagicMock]]:
    dependencies = {
        "stock_service": MagicMock(),
        "history_service": MagicMock(),
        "intelligence_service": MagicMock(),
        "portfolio_repository": MagicMock(),
        "alert_service": MagicMock(),
    }
    dependencies.update(overrides)
    dependencies["stock_service"].get_realtime_quote.return_value = _quote()
    dependencies["stock_service"].get_history_data.return_value = _history()
    dependencies["history_service"].get_history_list.return_value = _report_list()
    dependencies["history_service"].get_history_detail_by_id.return_value = _report_detail()
    dependencies["history_service"].get_latest_fundamental_snapshot.return_value = None
    dependencies["intelligence_service"].list_items.return_value = _intelligence()
    dependencies["portfolio_repository"].list_cached_position_identities.return_value = [("us", "aapl")]
    dependencies["alert_service"].list_rules.return_value = {
        "items": [{"id": 8, "enabled": True}, {"id": 9, "enabled": False}],
        "total": 2,
    }
    return StockProfileService(**dependencies), dependencies


def test_profile_uses_one_canonical_code_and_returns_structured_research() -> None:
    service, dependencies = _service()

    payload = service.get_profile("aapl", history_days=45)

    assert payload["canonical_code"] == "AAPL"
    assert payload["market"] == "us"
    assert payload["quote"]["status"] == "fresh"
    assert payload["history"]["status"] == "fresh"
    assert payload["research"]["status"] == "fresh"
    assert payload["research"]["data"]["structured_report"]["artifact_id"] == "report:12"
    assert payload["portfolio"]["data"] == {"held": True, "matched_markets": ["us"]}
    assert payload["monitors"]["data"] == {
        "total_rule_count": 2,
        "enabled_rule_count": 1,
        "rule_ids": [8, 9],
    }
    assert payload["evidence_quality"]["status"] == "partial"
    dependencies["stock_service"].get_realtime_quote.assert_called_once_with("AAPL")
    dependencies["stock_service"].get_history_data.assert_called_once_with(
        "AAPL", period="daily", days=45
    )
    dependencies["history_service"].get_history_list.assert_called_once_with(
        stock_code="AAPL", page=1, limit=5, market_hint="us"
    )
    assert {call.kwargs["scope_value"] for call in dependencies["intelligence_service"].list_items.call_args_list} == {
        "AAPL",
        "AAPL.US",
    }
    assert {call.kwargs["target"] for call in dependencies["alert_service"].list_rules.call_args_list} == {
        "AAPL",
        "AAPL.US",
    }
    assert dependencies["intelligence_service"].list_items.call_count == 4
    assert dependencies["alert_service"].list_rules.call_count == 2


def test_profile_alias_queries_are_unique_by_casefolded_identity() -> None:
    aliases = StockProfileService._code_aliases("600519", market_hint="cn")

    assert len(aliases) == len({alias.casefold() for alias in aliases})


@pytest.mark.parametrize("code", ["600519.SZ", "000001.SH", "920748.SH"])
def test_profile_rejects_exchange_conflicts_before_downstream_queries(code: str) -> None:
    service, dependencies = _service()

    with pytest.raises(InvalidStockProfileCode):
        service.get_profile(code)

    dependencies["stock_service"].get_realtime_quote.assert_not_called()
    dependencies["history_service"].get_history_list.assert_not_called()


def test_profile_research_preserves_specialized_report_evidence() -> None:
    service, dependencies = _service()
    detail = _report_detail()
    detail["context_snapshot"] = {
        "fundamental_context": {
            "earnings": {
                "data": {
                    "financial_report": {"report_date": "2026-06-30"},
                    "dividend": {"ttm_cash_dividend_per_share": 1.2},
                }
            }
        }
    }
    detail["raw_result"] = {
        "market_structure_context": {
            "schema_version": "market-structure-v1",
            "status": "available",
            "market_theme_context": {"schema_version": "market-theme-v1"},
            "stock_market_position": {"schema_version": "stock-market-position-v1"},
        }
    }
    dependencies["history_service"].get_history_detail_by_id.return_value = detail

    payload = service.get_profile("AAPL")

    artifact = payload["research"]["data"]["structured_report"]
    evidence_ids = {item["id"] for item in artifact["evidence"]}
    assert {
        "fundamental:financial_report",
        "fundamental:dividend_metrics",
        "market:structure",
    } <= evidence_ids
    assert artifact["data_quality"]["source_count"] == len(artifact["evidence"])


def test_profile_research_reads_independent_fundamental_snapshot() -> None:
    service, dependencies = _service()
    detail = _report_detail()
    detail["storage_stock_code"] = "AAPL.US"
    dependencies["history_service"].get_history_detail_by_id.return_value = detail
    dependencies["history_service"].get_latest_fundamental_snapshot.return_value = {
        "earnings": {
            "data": {
                "financial_report": {"report_date": "2026-06-30"},
                "dividend": {"ttm_cash_dividend_per_share": 1.2},
            }
        }
    }

    payload = service.get_profile("AAPL")

    artifact = payload["research"]["data"]["structured_report"]
    evidence_ids = {item["id"] for item in artifact["evidence"]}
    assert {
        "fundamental:financial_report",
        "fundamental:dividend_metrics",
    } <= evidence_ids
    dependencies["history_service"].get_latest_fundamental_snapshot.assert_called_once_with(
        query_id="query-12",
        stock_code="AAPL.US",
    )


def test_hk_alias_is_canonicalized_before_every_downstream_query() -> None:
    service, dependencies = _service()
    dependencies["stock_service"].get_realtime_quote.return_value = _quote("HK00700")
    dependencies["history_service"].get_history_list.return_value = {"items": [], "total": 0}
    dependencies["intelligence_service"].list_items.return_value = _intelligence("HK00700", "hk")

    payload = service.get_profile("00700.HK")

    assert payload["canonical_code"] == "HK00700"
    assert payload["market"] == "hk"
    dependencies["stock_service"].get_realtime_quote.assert_called_once_with("HK00700")
    dependencies["history_service"].get_history_list.assert_called_once_with(
        stock_code="HK00700", page=1, limit=5, market_hint="hk"
    )
    assert "00700.HK" in {
        call.kwargs["scope_value"]
        for call in dependencies["intelligence_service"].list_items.call_args_list
    }
    assert "00700.HK" in {
        call.kwargs["target"] for call in dependencies["alert_service"].list_rules.call_args_list
    }


def test_jp_and_kr_codes_preserve_shared_market_identity() -> None:
    jp_service, _ = _service()
    kr_service, kr_dependencies = _service()

    jp_payload = jp_service.get_profile("7203.T")
    kr_payload = kr_service.get_profile("005930")

    assert jp_payload["canonical_code"] == "7203.T"
    assert jp_payload["market"] == "jp"
    assert kr_payload["canonical_code"] == "005930.KS"
    assert kr_payload["market"] == "kr"
    assert {call.kwargs["market"] for call in kr_dependencies["intelligence_service"].list_items.call_args_list} == {
        "kr",
        "global",
    }


def test_portfolio_identity_uses_cached_market_hint_and_requires_same_market() -> None:
    jp_service, jp_dependencies = _service()
    jp_dependencies["portfolio_repository"].list_cached_position_identities.return_value = [
        ("jp", "8035"),
    ]
    kr_service, kr_dependencies = _service()
    kr_dependencies["portfolio_repository"].list_cached_position_identities.return_value = [
        ("cn", "005930"),
    ]

    jp_payload = jp_service.get_profile("8035.T")
    kr_payload = kr_service.get_profile("005930.KS")

    assert jp_payload["portfolio"]["data"] == {"held": True, "matched_markets": ["jp"]}
    assert kr_payload["portfolio"]["data"] == {"held": False, "matched_markets": []}


def test_legacy_bare_korean_position_keeps_market_hint_during_profile_match() -> None:
    service, dependencies = _service()
    dependencies["portfolio_repository"].list_cached_position_identities.return_value = [
        ("kr", "123456"),
    ]

    payload = service.get_profile("123456.KS")

    assert payload["portfolio"]["data"] == {"held": True, "matched_markets": ["kr"]}


def test_short_hk_cached_position_uses_its_market_hint() -> None:
    service, dependencies = _service()
    dependencies["portfolio_repository"].list_cached_position_identities.return_value = [
        ("hk", "700"),
    ]

    payload = service.get_profile("HK00700")

    assert payload["portfolio"]["data"] == {"held": True, "matched_markets": ["hk"]}


def test_bare_taiwan_cached_position_uses_its_market_hint() -> None:
    service, dependencies = _service()
    dependencies["portfolio_repository"].list_cached_position_identities.return_value = [
        ("tw", "2330"),
    ]

    payload = service.get_profile("2330.TW")

    assert payload["portfolio"]["data"] == {"held": True, "matched_markets": ["tw"]}


def test_taiwan_intelligence_reads_bare_alias_only_with_market_scope() -> None:
    service, dependencies = _service()

    def intelligence_by_alias(**kwargs: object) -> dict:
        if kwargs.get("scope_value") == "2330" and kwargs.get("market") == "tw":
            return _intelligence("2330", "tw")
        return {"items": [], "total": 0}

    dependencies["intelligence_service"].list_items.side_effect = intelligence_by_alias

    payload = service.get_profile("2330.TW")

    calls = {
        (call.kwargs["scope_value"], call.kwargs["market"])
        for call in dependencies["intelligence_service"].list_items.call_args_list
    }
    assert ("2330", "tw") in calls
    assert ("2330", "global") not in calls
    assert payload["intelligence"]["items"][0]["scope_value"] == "2330"


def test_japan_intelligence_reads_bare_alias_only_with_market_scope() -> None:
    service, dependencies = _service()

    def intelligence_by_alias(**kwargs: object) -> dict:
        if kwargs.get("scope_value") == "8035" and kwargs.get("market") == "jp":
            return _intelligence("8035", "jp")
        return {"items": [], "total": 0}

    dependencies["intelligence_service"].list_items.side_effect = intelligence_by_alias

    payload = service.get_profile("8035.T")

    calls = {
        (call.kwargs["scope_value"], call.kwargs["market"])
        for call in dependencies["intelligence_service"].list_items.call_args_list
    }
    assert ("8035", "jp") in calls
    assert ("8035", "global") not in calls
    assert payload["intelligence"]["items"][0]["scope_value"] == "8035"


def test_offshore_research_lookup_excludes_cross_market_bare_numeric_aliases() -> None:
    service, dependencies = _service()
    dependencies["history_service"].get_history_list.return_value = {"items": [], "total": 0}

    payload = service.get_profile("8035.T")

    assert payload["research"]["status"] == "unavailable"
    dependencies["history_service"].get_history_list.assert_called_once_with(
        stock_code="8035.T",
        page=1,
        limit=5,
        market_hint="jp",
        include_ambiguous_numeric_aliases=False,
    )


def test_offshore_monitor_lookup_keeps_market_unique_bare_numeric_alias() -> None:
    service, dependencies = _service()

    def rules_by_alias(**kwargs: object) -> dict:
        if kwargs.get("target") == "005930":
            return {"items": [{"id": 99, "enabled": True}], "total": 1}
        return {"items": [], "total": 0}

    dependencies["alert_service"].list_rules.side_effect = rules_by_alias

    payload = service.get_profile("005930.KS")

    queried_targets = {
        call.kwargs["target"] for call in dependencies["alert_service"].list_rules.call_args_list
    }
    assert "005930" in queried_targets
    assert "005930.KS" in queried_targets
    assert payload["monitors"]["data"]["total_rule_count"] == 1


def test_hk_monitor_lookup_keeps_unpadded_legacy_target() -> None:
    service, dependencies = _service()

    def rules_by_alias(**kwargs: object) -> dict:
        if kwargs.get("target") == "700":
            return {"items": [{"id": 77, "enabled": True}], "total": 1}
        return {"items": [], "total": 0}

    dependencies["alert_service"].list_rules.side_effect = rules_by_alias

    payload = service.get_profile("HK00700")

    queried_targets = {
        call.kwargs["target"] for call in dependencies["alert_service"].list_rules.call_args_list
    }
    assert "700" in queried_targets
    assert payload["monitors"]["data"]["rule_ids"] == [77]


def test_profile_collects_intelligence_and_monitors_saved_under_legacy_aliases() -> None:
    service, dependencies = _service()

    def intelligence_by_alias(**kwargs: object) -> dict:
        if kwargs.get("scope_value") == "600519.SH":
            return _intelligence("600519.SH", "cn")
        return {"items": [], "total": 0}

    def rules_by_alias(**kwargs: object) -> dict:
        if kwargs.get("target") == "SH600519":
            return {"items": [{"id": 88, "enabled": True}], "total": 1}
        return {"items": [], "total": 0}

    dependencies["intelligence_service"].list_items.side_effect = intelligence_by_alias
    dependencies["alert_service"].list_rules.side_effect = rules_by_alias

    payload = service.get_profile("600519")

    assert payload["intelligence"]["status"] == "fresh"
    assert payload["intelligence"]["items"][0]["scope_value"] == "600519.SH"
    assert payload["monitors"]["data"] == {
        "total_rule_count": 1,
        "enabled_rule_count": 1,
        "rule_ids": [88],
    }


def test_explicit_cn_identity_never_reexpands_through_a_colliding_kr_alias() -> None:
    service, dependencies = _service()
    dependencies["history_service"].get_history_list.return_value = {"items": [], "total": 0}

    payload = service.get_profile("SZ000660")

    assert payload["canonical_code"] == "000660"
    assert payload["market"] == "cn"
    dependencies["history_service"].get_history_list.assert_called_once_with(
        stock_code="000660",
        page=1,
        limit=5,
        market_hint="cn",
    )
    intelligence_aliases = {
        call.kwargs["scope_value"]
        for call in dependencies["intelligence_service"].list_items.call_args_list
    }
    monitor_aliases = {
        call.kwargs["target"] for call in dependencies["alert_service"].list_rules.call_args_list
    }
    intelligence_calls = {
        (call.kwargs["scope_value"], call.kwargs["market"])
        for call in dependencies["intelligence_service"].list_items.call_args_list
    }
    assert "000660.KS" not in intelligence_aliases
    assert "000660.KS" not in monitor_aliases
    assert ("000660", "cn") in intelligence_calls
    assert ("000660", "global") not in intelligence_calls
    assert {"SZ000660", "000660.SZ"} <= intelligence_aliases
    assert {"SZ000660", "000660.SZ"} <= monitor_aliases


def test_unambiguous_cn_bare_code_remains_available_to_global_and_monitor_queries() -> None:
    service, dependencies = _service()

    service.get_profile("600519")

    intelligence_calls = {
        (call.kwargs["scope_value"], call.kwargs["market"])
        for call in dependencies["intelligence_service"].list_items.call_args_list
    }
    monitor_targets = {
        call.kwargs["target"] for call in dependencies["alert_service"].list_rules.call_args_list
    }
    assert ("600519", "global") in intelligence_calls
    assert "600519" in monitor_targets


def test_us_suffix_converges_to_bare_ticker_and_queries_legacy_aliases() -> None:
    service, dependencies = _service()

    payload = service.get_profile("AAPL.US")

    assert payload["canonical_code"] == "AAPL"
    assert payload["market"] == "us"
    assert payload["portfolio"]["data"]["held"] is True
    dependencies["stock_service"].get_realtime_quote.assert_called_once_with("AAPL")
    dependencies["history_service"].get_history_list.assert_called_once_with(
        stock_code="AAPL", page=1, limit=5, market_hint="us"
    )
    assert {"AAPL", "AAPL.US"} <= {
        call.kwargs["scope_value"]
        for call in dependencies["intelligence_service"].list_items.call_args_list
    }
    assert {"AAPL", "AAPL.US"} <= {
        call.kwargs["target"] for call in dependencies["alert_service"].list_rules.call_args_list
    }


def test_profile_includes_global_symbol_intelligence() -> None:
    service, dependencies = _service()

    def intelligence_by_market(**kwargs: object) -> dict:
        if kwargs.get("scope_value") == "AAPL" and kwargs.get("market") == "global":
            return _intelligence("AAPL", "global")
        return {"items": [], "total": 0}

    dependencies["intelligence_service"].list_items.side_effect = intelligence_by_market

    payload = service.get_profile("AAPL")

    assert payload["intelligence"]["status"] == "fresh"
    assert payload["intelligence"]["items"][0]["market"] == "global"


def test_empty_intelligence_keeps_partial_status_when_any_alias_query_fails() -> None:
    service, dependencies = _service()

    def partially_failing_query(**kwargs: object) -> dict:
        if kwargs.get("scope_value") == "AAPL.US" and kwargs.get("market") == "us":
            raise RuntimeError("transient query failure")
        return {"items": [], "total": 0}

    dependencies["intelligence_service"].list_items.side_effect = partially_failing_query

    payload = service.get_profile("AAPL")

    assert payload["intelligence"] == {
        "status": "partial",
        "items": [],
        "limitations": ["intelligence_alias_query_partial"],
    }


def test_optional_block_failures_remain_partial_and_do_not_hide_monitor_data() -> None:
    service, dependencies = _service()
    dependencies["stock_service"].get_realtime_quote.side_effect = RuntimeError("quote failed")
    dependencies["stock_service"].get_history_data.return_value = {"data": []}
    dependencies["history_service"].get_history_detail_by_id.return_value = None
    dependencies["intelligence_service"].list_items.side_effect = RuntimeError("intel failed")
    dependencies["portfolio_repository"].list_cached_position_identities.side_effect = RuntimeError("db failed")

    payload = service.get_profile("AAPL")

    assert payload["quote"]["status"] == "unavailable"
    assert payload["history"]["status"] == "unavailable"
    assert payload["research"]["status"] == "partial"
    assert payload["research"]["data"]["recent_reports"][0]["id"] == 12
    assert payload["intelligence"]["status"] == "unavailable"
    assert payload["portfolio"]["status"] == "unavailable"
    assert payload["monitors"]["status"] == "fresh"
    assert payload["evidence_quality"]["status"] == "partial"
    assert "latest_report_detail_unavailable" in payload["evidence_quality"]["limitations"]


def test_all_dependency_failures_return_unavailable_profile_instead_of_raising() -> None:
    service, dependencies = _service()
    for dependency, method in (
        ("stock_service", "get_realtime_quote"),
        ("stock_service", "get_history_data"),
        ("history_service", "get_history_list"),
        ("intelligence_service", "list_items"),
        ("portfolio_repository", "list_cached_position_identities"),
        ("alert_service", "list_rules"),
    ):
        getattr(dependencies[dependency], method).side_effect = RuntimeError("offline")

    payload = service.get_profile("600519")

    assert payload["market"] == "cn"
    assert payload["evidence_quality"]["status"] == "unavailable"
    assert set(payload["evidence_quality"]["blocks"].values()) == {"unavailable"}


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


def _endpoint_payload() -> dict:
    service, _ = _service()
    return service.get_profile("AAPL")


def test_profile_endpoint_validates_code_and_exposes_contract() -> None:
    _reset_auth_globals()
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            os.environ["DATABASE_PATH"] = str(Path(temp_dir) / "profile.db")
            os.environ["ADMIN_AUTH_ENABLED"] = "false"
            Config.reset_instance()
            DatabaseManager.reset_instance()
            app = create_app(static_dir=Path(temp_dir) / "empty-static")
            client = TestClient(app)
            with patch(
                "api.v1.endpoints.stocks.StockProfileService.get_profile",
                return_value=_endpoint_payload(),
            ) as get_profile:
                response = client.get("/api/v1/stocks/AAPL/profile", params={"history_days": 90})
                jp = client.get("/api/v1/stocks/7203.T/profile")
                kr = client.get("/api/v1/stocks/005930.KS/profile")
                tw = client.get("/api/v1/stocks/2330.TW/profile")
                two = client.get("/api/v1/stocks/6505.TWO/profile")
                tw_etf = client.get("/api/v1/stocks/006208.TW/profile")
            invalid = client.get("/api/v1/stocks/invalid-code/profile")
            conflicts = [
                client.get(f"/api/v1/stocks/{code}/profile")
                for code in ("600519.SZ", "000001.SH", "920748.SH")
            ]

            assert response.status_code == 200, response.text
            assert response.json()["canonical_code"] == "AAPL"
            assert [item.args for item in get_profile.call_args_list] == [
                ("AAPL",),
                ("7203.T",),
                ("005930.KS",),
                ("2330.TW",),
                ("6505.TWO",),
                ("006208.TW",),
            ]
            assert [item.kwargs for item in get_profile.call_args_list] == [
                {"history_days": 90},
                {"history_days": 60},
                {"history_days": 60},
                {"history_days": 60},
                {"history_days": 60},
                {"history_days": 60},
            ]
            assert invalid.status_code == 400
            assert [item.status_code for item in conflicts] == [400, 400, 400]
            assert {
                item.json()["error"]
                for item in conflicts
            } == {"invalid_stock_code"}
            assert jp.status_code == 200
            assert kr.status_code == 200
            assert tw.status_code == 200
            assert two.status_code == 200
            assert tw_etf.status_code == 200
        finally:
            DatabaseManager.reset_instance()
            Config.reset_instance()
            os.environ.pop("DATABASE_PATH", None)
            os.environ.pop("ADMIN_AUTH_ENABLED", None)
            _reset_auth_globals()


def test_static_openapi_matches_stock_profile_runtime_contract() -> None:
    static_spec = json.loads(
        (Path(__file__).resolve().parents[1] / "docs" / "architecture" / "api_spec.json").read_text(
            encoding="utf-8"
        )
    )
    runtime_spec = create_app().openapi()
    api_path = "/api/v1/stocks/{stock_code}/profile"
    assert static_spec["paths"][api_path] == runtime_spec["paths"][api_path]
    schema_names = [
        name for name in runtime_spec["components"]["schemas"] if name.startswith("StockProfile")
    ]
    assert schema_names
    for schema_name in schema_names:
        assert static_spec["components"]["schemas"][schema_name] == runtime_spec["components"]["schemas"][schema_name]
