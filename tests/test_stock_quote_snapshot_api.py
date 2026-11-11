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
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app import create_app
from data_provider.base import DataFetcherManager
from data_provider.realtime_types import RealtimeSource, UnifiedRealtimeQuote
from src.config import Config
from src.services.quote_snapshot_service import clear_snapshot_cache
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


# ============================================
# r2 blocker A：指数身份不得被端点预规范化剥离
# （OR-COR-e347c2a0 / 33692011）
# ============================================

class _FakeAkshareFetcher:
    """指数/股票两条链共用的探针 fetcher：记录收到的符号形态。"""

    name = "AkshareFetcher"
    priority = 1

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_realtime_quote(self, stock_code, source="em"):
        self.calls.append((stock_code, source))
        if source == "tencent":
            return UnifiedRealtimeQuote(
                code=stock_code,
                name=f"chain:{stock_code}",
                price=3000.0,
                change_pct=1.0,
                source=RealtimeSource.TENCENT,
            )
        return None


class _FakeEfinanceFetcher:
    name = "EfinanceFetcher"
    priority = 0

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_realtime_quote(self, stock_code):
        self.calls.append(stock_code)
        return None

    def get_index_realtime_quote(self, stock_code):
        self.calls.append(stock_code)
        return None


class _StubAkshareFetcher:
    """盘口探针桩：路由测试不触网。"""

    def __init__(self) -> None:
        pass

    def get_a_share_order_book(self, code):
        return None


def test_quote_index_form_routes_through_index_chain_unstripped() -> None:
    """sh000016 必须原样进入数据源链（指数链）；裸 000016 走股票链；
    缓存键按原始入参区分，两形态互不污染。"""
    client, temp_dir = _make_client()
    try:
        fake_akshare = _FakeAkshareFetcher()

        def manager_factory(*args, **kwargs):
            return DataFetcherManager(fetchers=[_FakeEfinanceFetcher(), fake_akshare])

        with patch(
            "src.services.quote_snapshot_service.DataFetcherManager", new=manager_factory
        ), patch(
            "src.services.quote_snapshot_service.AkshareFetcher", new=_StubAkshareFetcher
        ), patch(
            "src.config.get_config",
            return_value=SimpleNamespace(
                enable_realtime_quote=True,
                realtime_source_priority="tencent,akshare_sina,efinance,akshare_em",
                realtime_cache_ttl=600,
            ),
        ):
            clear_snapshot_cache()
            index_resp = client.get("/api/v1/stocks/sh000016/quote")
            calls_after_index = list(fake_akshare.calls)
            stock_resp = client.get("/api/v1/stocks/000016/quote")
            calls_after_stock = list(fake_akshare.calls)

            assert index_resp.status_code == 200, index_resp.text
            assert stock_resp.status_code == 200, stock_resp.text

            # 指数形态原样进入数据源链：前缀不被端点剥离（r1 缺陷是剥成 000016）
            assert ("sh000016", "tencent") in calls_after_index, (
                f"指数请求必须保留前缀进入数据源链，实际: {calls_after_index}"
            )
            # 裸码走股票链：裸形态进入数据源链
            stock_window = calls_after_stock[len(calls_after_index):]
            assert ("000016", "tencent") in stock_window, (
                f"裸码必须以裸形态进入股票链，实际新增: {stock_window}"
            )
            # 股票链不得收到被剥离的指数形态（即指数请求不得漏进股票链）
            assert index_resp.json()["stock_code"] == "sh000016"
            assert stock_resp.json()["stock_code"] == "000016"
            assert index_resp.json()["stock_name"] != stock_resp.json()["stock_name"]

            # 缓存按原始入参键控：同形态二次请求不再取数
            before_cache_hit = len(fake_akshare.calls)
            index_again = client.get("/api/v1/stocks/sh000016/quote")
            stock_again = client.get("/api/v1/stocks/000016/quote")
            assert index_again.status_code == 200
            assert stock_again.status_code == 200
            assert len(fake_akshare.calls) == before_cache_hit, (
                "TTL 内同形态请求必须命中缓存（不得重新取数）"
            )
            assert index_again.json()["stock_code"] == "sh000016"
            assert stock_again.json()["stock_code"] == "000016"

            # 后缀形态 000016.SH 同为指数身份（parse_analysis_target: index）：
            # 必须走指数链，绝不被剥成裸 000016 混入股票链
            calls_before_suffix = len(fake_akshare.calls)
            suffix_resp = client.get("/api/v1/stocks/000016.SH/quote")
            assert suffix_resp.status_code == 200, suffix_resp.text
            suffix_window = fake_akshare.calls[calls_before_suffix:]
            assert ("000016", "tencent") not in suffix_window, (
                f"后缀指数请求不得被剥成裸码进股票链，实际新增: {suffix_window}"
            )
    finally:
        clear_snapshot_cache()
        _teardown(temp_dir)


# ============================================
# r2 blocker B：profile 复用旧 StockQuote，快照用独立模型
# （OR-COR-9c98b032）
# ============================================

def test_profile_quote_block_keeps_legacy_stock_quote_shape() -> None:
    """StockProfileQuoteBlock.data（旧 current_price 族）必须原样保留字段，
    pydantic 不得静默丢弃既有 profile 行情块数据。"""
    from api.v1.schemas.stocks import StockProfileQuoteBlock, StockQuote, StockQuoteSnapshot

    block = StockProfileQuoteBlock(
        status="fresh",
        data={
            "stock_code": "AAPL",
            "stock_name": "Apple",
            "current_price": 200.0,
            "change": 1.0,
            "change_percent": 0.5,
            "open": 198.0,
            "high": 202.0,
            "low": 197.0,
            "prev_close": 199.0,
            "volume": 1000.0,
            "amount": 200000.0,
            "update_time": "2026-08-29T10:00:00+08:00",
        },
    )

    assert block.data is not None
    assert block.data.current_price == 200.0
    assert block.data.change == 1.0
    assert block.data.change_percent == 0.5
    assert block.data.prev_close == 199.0
    assert block.data.update_time == "2026-08-29T10:00:00+08:00"

    # 两模型并存：StockQuote 保持旧 12 字段族（profile 用），
    # StockQuoteSnapshot 承载 22 字段快照族（快照端点用）
    assert "current_price" in StockQuote.model_fields
    assert "price" not in StockQuote.model_fields
    assert "price" in StockQuoteSnapshot.model_fields
    assert "current_price" not in StockQuoteSnapshot.model_fields
    for field in QUOTE_SNAPSHOT_FIELDS:
        assert field in StockQuoteSnapshot.model_fields, f"snapshot model missing: {field}"


def test_profile_endpoint_quote_data_keeps_current_price_through_response_model() -> None:
    client, temp_dir = _make_client()
    try:
        from api.v1.schemas.stocks import (
            StockProfileEvidenceQuality,
            StockProfileHistoryBlock,
            StockProfileIntelligenceBlock,
            StockProfileMonitorBlock,
            StockProfilePortfolioBlock,
            StockProfileQuoteBlock,
            StockProfileResearchBlock,
            StockProfileResponse,
        )

        legacy_quote = {
            "stock_code": "AAPL",
            "stock_name": "Apple",
            "current_price": 200.0,
            "change": 1.0,
            "change_percent": 0.5,
            "open": 198.0,
            "high": 202.0,
            "low": 197.0,
            "prev_close": 199.0,
            "volume": 1000.0,
            "amount": 200000.0,
            "update_time": "2026-08-29T10:00:00+08:00",
        }
        profile_payload = StockProfileResponse(
            requested_code="AAPL",
            canonical_code="AAPL",
            market="us",
            as_of="2026-11-11T10:00:00+00:00",
            quote=StockProfileQuoteBlock(status="fresh", data=legacy_quote),
            history=StockProfileHistoryBlock(status="unavailable"),
            research=StockProfileResearchBlock(status="unavailable"),
            intelligence=StockProfileIntelligenceBlock(status="unavailable"),
            portfolio=StockProfilePortfolioBlock(status="unavailable"),
            monitors=StockProfileMonitorBlock(status="unavailable"),
            evidence_quality=StockProfileEvidenceQuality(status="unavailable"),
        ).model_dump(mode="json")
        with patch(
            "api.v1.endpoints.stocks.StockProfileService.get_profile",
            return_value=profile_payload,
        ):
            response = client.get("/api/v1/stocks/AAPL/profile")

        assert response.status_code == 200, response.text
        quote_data = response.json()["quote"]["data"]
        assert quote_data["current_price"] == 200.0, (
            f"profile quote.data 必须保留 current_price（pydantic 不得静默丢弃），实际键: {sorted(quote_data)}"
        )
        assert quote_data["change"] == 1.0
        assert quote_data["change_percent"] == 0.5
    finally:
        _teardown(temp_dir)
