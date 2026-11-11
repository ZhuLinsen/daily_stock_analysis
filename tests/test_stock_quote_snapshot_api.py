# -*- coding: utf-8 -*-
"""Contract tests for the read-only quote snapshot endpoint (issue #771).

契约口径（计划默认值 4/5 钉死）：
- GET /api/v1/stocks/{code}/quote 返回 22 字段行情快照
  （直出 15 + 派生 3 + MA 4 档）+ 数据质量元数据。
- 多市场降级：缺失字段一律显式 null，并以 missing_fields 透出，不做字段级硬失败。
- 未知代码与既有 API 错误范式一致：404 {"error": "not_found"}。
- 非法代码格式：400 {"error": "invalid_stock_code"}。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from src.config import Config
from src.storage import DatabaseManager

# 计划默认值 4 钉死的 22 字段清单（不得增删口径）
QUOTE_SNAPSHOT_FIELDS = (
    # 直出 15（UnifiedRealtimeQuote）
    "price",
    "pre_close",
    "open_price",
    "high",
    "low",
    "volume",
    "amount",
    "change_amount",
    "change_pct",
    "amplitude",
    "volume_ratio",
    "turnover_rate",
    "change_60d",
    "high_52w",
    "low_52w",
    # 派生 3
    "vwap",
    "bid_ask_ratio",
    "trade_count",
    # MA 4 档
    "ma5",
    "ma10",
    "ma20",
    "ma60",
)

# 数据质量元数据（计划默认值 4：source/is_stale/missing_fields 随响应透出）
QUOTE_METADATA_FIELDS = (
    "source",
    "is_stale",
    "missing_fields",
    "fetched_at",
    "provider_timestamp",
    "stale_seconds",
    "market",
    "currency",
    "data_quality",
    "fallback_from",
)


def _full_cn_snapshot() -> dict:
    """A 股全字段快照（模拟 akshare em 全量源 + 派生齐备）。"""
    payload = {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "source": "akshare_em",
        "fetched_at": "2026-11-11T10:00:00+00:00",
        "provider_timestamp": "2026-11-11T09:59:00+00:00",
        "is_stale": False,
        "stale_seconds": 60,
        "market": "cn",
        "currency": "CNY",
        "data_quality": "ok",
        "fallback_from": None,
        "missing_fields": [],
        "price": 1500.0,
        "pre_close": 1480.0,
        "open_price": 1490.0,
        "high": 1510.0,
        "low": 1485.0,
        "volume": 2_000_000,
        "amount": 3_000_000_000.0,
        "change_amount": 20.0,
        "change_pct": 1.35,
        "amplitude": 1.69,
        "volume_ratio": 1.2,
        "turnover_rate": 0.16,
        "change_60d": 12.5,
        "high_52w": 1850.0,
        "low_52w": 1300.0,
        "vwap": 1500.0,
        "bid_ask_ratio": 8.5,
        "trade_count": None,  # 成交笔数 em 标准接口不可得 → 恒 null
        "ma5": 1495.0,
        "ma10": 1490.0,
        "ma20": 1470.0,
        "ma60": 1420.0,
    }
    return payload


def _degraded_us_snapshot() -> dict:
    """美股降级快照：仅 yfinance 可得的少量字段，其余显式 null + missing_fields。"""
    missing = [
        "amount",
        "amplitude",
        "bid_ask_ratio",
        "change_60d",
        "change_amount",
        "high_52w",
        "low_52w",
        "open_price",
        "pre_close",
        "trade_count",
        "turnover_rate",
        "vwap",
        "volume_ratio",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
    ]
    payload = {
        "stock_code": "AAPL",
        "stock_name": "Apple",
        "source": "yfinance",
        "fetched_at": "2026-11-11T10:00:00+00:00",
        "provider_timestamp": None,
        "is_stale": None,
        "stale_seconds": None,
        "market": "us",
        "currency": "USD",
        "data_quality": "partial",
        "fallback_from": None,
        "missing_fields": missing,
        "price": 200.0,
        "pre_close": None,
        "open_price": None,
        "high": 201.0,
        "low": 198.5,
        "volume": 51_000_000,
        "amount": None,
        "change_amount": None,
        "change_pct": 0.25,
        "amplitude": None,
        "volume_ratio": None,
        "turnover_rate": None,
        "change_60d": None,
        "high_52w": None,
        "low_52w": None,
        "vwap": None,
        "bid_ask_ratio": None,
        "trade_count": None,
        "ma5": None,
        "ma10": None,
        "ma20": None,
        "ma60": None,
    }
    return payload


def _make_client():
    temp_dir = tempfile.TemporaryDirectory()
    os.environ["DATABASE_PATH"] = str(Path(temp_dir.name) / "quote.db")
    os.environ["ADMIN_AUTH_ENABLED"] = "false"
    Config.reset_instance()
    DatabaseManager.reset_instance()
    app = create_app(static_dir=Path(temp_dir.name) / "empty-static")
    client = TestClient(app)
    return client, temp_dir


def _teardown(temp_dir) -> None:
    temp_dir.cleanup()
    DatabaseManager.reset_instance()
    Config.reset_instance()
    os.environ.pop("DATABASE_PATH", None)
    os.environ.pop("ADMIN_AUTH_ENABLED", None)


def test_quote_snapshot_exposes_pinned_22_field_contract() -> None:
    client, temp_dir = _make_client()
    try:
        with patch("api.v1.endpoints.stocks.QuoteSnapshotService") as service_cls:
            service_cls.return_value.get_snapshot.return_value = _full_cn_snapshot()
            response = client.get("/api/v1/stocks/600519/quote")

        assert response.status_code == 200, response.text
        body = response.json()

        # 22 字段全部存在且为显式键（缺失也要是 null，不能省键）
        for field in QUOTE_SNAPSHOT_FIELDS:
            assert field in body, f"missing pinned field: {field}"
        # 数据质量元数据透出
        for field in QUOTE_METADATA_FIELDS:
            assert field in body, f"missing metadata field: {field}"

        assert body["stock_code"] == "600519"
        assert body["stock_name"] == "贵州茅台"
        assert body["price"] == 1500.0
        assert body["volume"] == 2_000_000
        assert body["vwap"] == 1500.0
        assert body["ma60"] == 1420.0
        assert body["source"] == "akshare_em"
        assert body["is_stale"] is False
        assert body["missing_fields"] == []

        # 旧 12 字段口径字段必须退场（口径切换为 UnifiedRealtimeQuote 命名）
        for legacy_field in ("current_price", "prev_close", "change", "change_percent", "open", "update_time"):
            assert legacy_field not in body, f"legacy field must be removed: {legacy_field}"
    finally:
        _teardown(temp_dir)


def test_quote_snapshot_multi_market_degradation_semantics() -> None:
    client, temp_dir = _make_client()
    try:
        with patch("api.v1.endpoints.stocks.QuoteSnapshotService") as service_cls:
            service_cls.return_value.get_snapshot.return_value = _degraded_us_snapshot()
            response = client.get("/api/v1/stocks/AAPL/quote")

        assert response.status_code == 200, response.text
        body = response.json()

        # 降级字段一律显式 null（JSON null，不是缺键），前端以 "—" 占位
        for field in ("pre_close", "amount", "vwap", "bid_ask_ratio", "trade_count", "ma60"):
            assert field in body, f"degraded field must be explicit null key: {field}"
            assert body[field] is None, f"degraded field must be null: {field}"

        # 不可得字段集合随 missing_fields 透出
        missing = set(body["missing_fields"])
        assert {"vwap", "bid_ask_ratio", "trade_count", "ma60"} <= missing

        # 元数据可用字段仍然透出
        assert body["source"] == "yfinance"
        assert body["data_quality"] == "partial"
        assert body["price"] == 200.0
    finally:
        _teardown(temp_dir)


def test_quote_unknown_code_returns_404_not_found() -> None:
    client, temp_dir = _make_client()
    try:
        with patch("api.v1.endpoints.stocks.QuoteSnapshotService") as service_cls:
            service_cls.return_value.get_snapshot.return_value = None
            response = client.get("/api/v1/stocks/600519/quote")

        assert response.status_code == 404, response.text
        # 既有 API 错误范式：应用层将 HTTPException detail 展平为 {"error", "message"}
        assert response.json()["error"] == "not_found"
    finally:
        _teardown(temp_dir)


def test_quote_invalid_code_returns_400_before_service_call() -> None:
    client, temp_dir = _make_client()
    try:
        with patch("api.v1.endpoints.stocks.QuoteSnapshotService") as service_cls:
            response = client.get("/api/v1/stocks/@@bad@@/quote")

        assert response.status_code == 400, response.text
        assert response.json()["error"] == "invalid_stock_code"
        service_cls.assert_not_called()
    finally:
        _teardown(temp_dir)


def test_quote_snapshot_endpoint_is_read_only_get() -> None:
    client, temp_dir = _make_client()
    try:
        with patch("api.v1.endpoints.stocks.QuoteSnapshotService") as service_cls:
            service_cls.return_value.get_snapshot.return_value = _full_cn_snapshot()
            post_response = client.post("/api/v1/stocks/600519/quote")
            get_response = client.get("/api/v1/stocks/600519/quote")

        assert post_response.status_code == 405, post_response.status_code
        assert get_response.status_code == 200
        service_cls.return_value.get_snapshot.assert_called_once_with("600519")
    finally:
        _teardown(temp_dir)
