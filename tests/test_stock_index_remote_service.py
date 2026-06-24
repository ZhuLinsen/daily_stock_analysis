# -*- coding: utf-8 -*-
"""Tests for best-effort remote stock-index caching."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.services import stock_index_remote_service as service


@pytest.fixture(autouse=True)
def reset_remote_stock_index_state() -> None:
    service._reset_remote_stock_index_state_for_tests()
    yield
    service._reset_remote_stock_index_state_for_tests()


def _stock_index_payload(size: int = 100, *, name: str = "平安银行") -> list[list[object]]:
    return [
        [
            f"{index:06d}.SZ",
            f"{index:06d}",
            name,
            "pinganyinhang",
            "payh",
            [],
            "CN",
            "stock",
            True,
            100,
        ]
        for index in range(size)
    ]


def _bse_stock_index_payload(size: int = 100) -> list[list[object]]:
    payload = _stock_index_payload(size=size)
    payload[0][0] = "920964.BJ"
    payload[0][1] = "920964"
    payload[0][2] = "润农节水"
    payload[0][6] = "BSE"
    return payload


def _response(payload: object) -> Mock:
    response = Mock()
    response.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    response.encoding = "utf-8"
    response.raise_for_status.return_value = None
    return response


def test_refresh_remote_stock_index_cache_writes_valid_payload(tmp_path: Path) -> None:
    cache_path = tmp_path / "stocks.index.json"
    settings = service.RemoteStockIndexSettings(cache_path=cache_path)

    with patch.object(service.requests, "get", return_value=_response(_stock_index_payload())) as get:
        result = service.refresh_remote_stock_index_cache(settings)

    assert result.refreshed is True
    assert result.cache_path == cache_path
    assert json.loads(cache_path.read_text(encoding="utf-8"))[0][2] == "平安银行"
    get.assert_called_once_with(service.DEFAULT_STOCK_INDEX_REMOTE_URL, timeout=10)


def test_refresh_remote_stock_index_cache_decodes_remote_payload_as_utf8(tmp_path: Path) -> None:
    cache_path = tmp_path / "stocks.index.json"
    settings = service.RemoteStockIndexSettings(cache_path=cache_path)
    response = _response(_stock_index_payload())
    response.encoding = "ascii"

    with patch.object(service.requests, "get", return_value=response):
        result = service.refresh_remote_stock_index_cache(settings)

    assert result.refreshed is True
    assert json.loads(cache_path.read_text(encoding="utf-8"))[0][2] == "平安银行"


def test_refresh_remote_stock_index_cache_clears_backend_loader_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "stocks.index.json"
    settings = service.RemoteStockIndexSettings(cache_path=cache_path)

    with patch.object(service.requests, "get", return_value=_response(_stock_index_payload())), \
         patch("src.data.stock_index_loader.clear_stock_index_cache") as clear_cache:
        result = service.refresh_remote_stock_index_cache(settings)

    assert result.refreshed is True
    clear_cache.assert_called_once_with()


def test_refresh_remote_stock_index_cache_skips_fresh_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "stocks.index.json"
    cache_path.write_text(json.dumps(_stock_index_payload(), ensure_ascii=False), encoding="utf-8")
    settings = service.RemoteStockIndexSettings(cache_path=cache_path, ttl_hours=48)

    with patch.object(service.requests, "get") as get:
        result = service.refresh_remote_stock_index_cache(settings)

    assert result.skipped is True
    assert result.cache_path == cache_path
    get.assert_not_called()


def test_refresh_remote_stock_index_cache_keeps_old_cache_on_download_failure(tmp_path: Path) -> None:
    cache_path = tmp_path / "stocks.index.json"
    cache_path.write_text(json.dumps(_stock_index_payload(name="旧缓存"), ensure_ascii=False), encoding="utf-8")
    old_mtime = time.time() - 100 * 3600
    os.utime(cache_path, (old_mtime, old_mtime))
    settings = service.RemoteStockIndexSettings(cache_path=cache_path, ttl_hours=48)

    with patch.object(service.requests, "get", side_effect=TimeoutError("timeout")):
        result = service.refresh_remote_stock_index_cache(settings)

    assert result.cache_path == cache_path
    assert result.error == "timeout"
    assert json.loads(cache_path.read_text(encoding="utf-8"))[0][2] == "旧缓存"


def test_refresh_remote_stock_index_cache_suppresses_after_repeated_failures(tmp_path: Path) -> None:
    cache_path = tmp_path / "stocks.index.json"
    settings = service.RemoteStockIndexSettings(cache_path=cache_path, ttl_hours=48)

    with patch.object(service.requests, "get", side_effect=TimeoutError("timeout")) as get:
        results = [service.refresh_remote_stock_index_cache(settings) for _ in range(6)]

    assert get.call_count == service.DEFAULT_STOCK_INDEX_REMOTE_MAX_FAILURES
    assert results[-1].skipped is True
    assert results[-1].error == "remote update temporarily suppressed after repeated failures"


def test_refresh_remote_stock_index_cache_retries_after_failure_window(tmp_path: Path) -> None:
    cache_path = tmp_path / "stocks.index.json"
    settings = service.RemoteStockIndexSettings(cache_path=cache_path, ttl_hours=1)

    with patch.object(service.time, "time", return_value=1_000.0), \
         patch.object(service.requests, "get", side_effect=TimeoutError("timeout")):
        for _ in range(service.DEFAULT_STOCK_INDEX_REMOTE_MAX_FAILURES):
            service.refresh_remote_stock_index_cache(settings)

    with patch.object(service.time, "time", return_value=4_601.0), \
         patch.object(service.requests, "get", return_value=_response(_stock_index_payload())) as get:
        result = service.refresh_remote_stock_index_cache(settings)

    assert result.refreshed is True
    get.assert_called_once()


def test_refresh_remote_stock_index_cache_rejects_invalid_remote_payload(tmp_path: Path) -> None:
    cache_path = tmp_path / "stocks.index.json"
    cache_path.write_text(json.dumps(_stock_index_payload(name="旧缓存"), ensure_ascii=False), encoding="utf-8")
    settings = service.RemoteStockIndexSettings(cache_path=cache_path, ttl_hours=0)

    with patch.object(service.requests, "get", return_value=_response([["000001.SZ"]])):
        result = service.refresh_remote_stock_index_cache(settings)

    assert result.cache_path == cache_path
    assert result.error
    assert json.loads(cache_path.read_text(encoding="utf-8"))[0][2] == "旧缓存"


def test_validate_stock_index_payload_accepts_bse_market() -> None:
    payload = _bse_stock_index_payload()

    assert service.validate_stock_index_payload(payload) is payload


def test_validate_stock_index_payload_accepts_jp_and_kr_markets() -> None:
    payload = _stock_index_payload()
    payload[0][0] = "7203.T"
    payload[0][1] = "7203.T"
    payload[0][6] = "JP"
    payload[1][0] = "000660.KS"
    payload[1][1] = "000660.KS"
    payload[1][6] = "KR"

    assert service.validate_stock_index_payload(payload) is payload


@pytest.mark.parametrize("popularity", [None, "100", True, float("nan"), float("inf")])
def test_validate_stock_index_payload_rejects_invalid_popularity(popularity: object) -> None:
    payload = _stock_index_payload()
    payload[0][9] = popularity

    with pytest.raises(ValueError, match="popularity"):
        service.validate_stock_index_payload(payload)


def test_validate_stock_index_payload_rejects_missing_popularity() -> None:
    payload = _stock_index_payload()
    payload[0] = payload[0][:9]

    with pytest.raises(ValueError):
        service.validate_stock_index_payload(payload)


def test_missing_remote_stock_index_cache_is_silent(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    cache_path = tmp_path / "missing" / "stocks.index.json"

    with caplog.at_level(logging.WARNING, logger="src.services.stock_index_remote_service"):
        assert service.is_valid_remote_stock_index_file(cache_path) is False

    assert not any("cached remote index is invalid" in record.getMessage() for record in caplog.records)


def test_settings_from_config_uses_internal_remote_url_only() -> None:
    config = SimpleNamespace(
        stock_index_remote_update_enabled=False,
        stock_index_remote_url="https://example.invalid/override.json",
    )

    settings = service.settings_from_config(config)

    assert settings.enabled is False
    assert settings.url == service.DEFAULT_STOCK_INDEX_REMOTE_URL
    assert settings.ttl_hours == service.DEFAULT_STOCK_INDEX_REMOTE_TTL_HOURS
    assert settings.timeout_seconds == service.DEFAULT_STOCK_INDEX_REMOTE_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [["000001.SZ"]],
        _stock_index_payload(size=99),
    ],
)
def test_validate_stock_index_payload_rejects_bad_payloads(payload: object) -> None:
    with pytest.raises(ValueError):
        service.validate_stock_index_payload(payload)
