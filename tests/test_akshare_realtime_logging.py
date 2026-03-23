import logging

import pytest
import requests

from data_provider.akshare_fetcher import (
    AkshareFetcher,
    SINA_REALTIME_ENDPOINT,
    TENCENT_REALTIME_ENDPOINT,
)


class _DummyCircuitBreaker:
    def __init__(self):
        self.failures = []
        self.successes = []

    def is_available(self, source: str) -> bool:
        return True

    def record_success(self, source: str) -> None:
        self.successes.append(source)

    def record_failure(self, source: str, error=None) -> None:
        self.failures.append((source, error))


class _DummyResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.encoding = None


def _make_sina_payload() -> str:
    fields = [
        "大秦铁路", "5.100", "5.000", "5.190", "5.200", "5.050", "5.180", "5.190",
        "123456", "789012"
    ]
    fields.extend(["0"] * 20)
    fields.extend(["2026-03-08", "15:00:00"])
    return f'var hq_str_sh601006="{",".join(fields)}";'


def _make_tencent_payload() -> str:
    fields = ["0"] * 50
    fields[1] = "大秦铁路"
    fields[2] = "601006"
    fields[3] = "5.19"
    fields[4] = "5.00"
    fields[5] = "5.10"
    fields[6] = "1234"
    fields[31] = "0.19"
    fields[32] = "3.80"
    fields[34] = "5.20"
    fields[35] = "5.05"
    fields[38] = "0.69"
    fields[39] = "12.3"
    fields[43] = "2.00"
    fields[44] = "1000"
    fields[45] = "1200"
    fields[46] = "1.20"
    fields[49] = "0.63"
    return f'v_sh601006="{"~".join(fields)}";'


@pytest.fixture
def akshare_fetcher(monkeypatch):
    fetcher = AkshareFetcher()
    monkeypatch.setattr(fetcher, "_enforce_rate_limit", lambda: None)
    return fetcher


def test_sina_realtime_success_logs_endpoint(caplog, monkeypatch, akshare_fetcher):
    breaker = _DummyCircuitBreaker()
    monkeypatch.setattr("data_provider.akshare_fetcher.get_realtime_circuit_breaker", lambda: breaker)
    monkeypatch.setattr(
        "data_provider.akshare_fetcher.requests.get",
        lambda *args, **kwargs: _DummyResponse(200, _make_sina_payload()),
    )

    with caplog.at_level(logging.INFO):
        quote = akshare_fetcher._get_stock_realtime_quote_sina("601006")

    assert quote is not None
    assert quote.name == "大秦铁路"
    assert quote.price == 5.19
    assert breaker.successes == ["akshare_sina"]
    assert f"endpoint={SINA_REALTIME_ENDPOINT}" in caplog.text
    assert "[实时行情-新浪] 601006 大秦铁路:" in caplog.text


def test_sina_realtime_remote_disconnect_logs_category(caplog, monkeypatch, akshare_fetcher):
    breaker = _DummyCircuitBreaker()
    monkeypatch.setattr("data_provider.akshare_fetcher.get_realtime_circuit_breaker", lambda: breaker)

    def _raise_disconnect(*args, **kwargs):
        raise requests.exceptions.ConnectionError("Remote end closed connection without response")

    monkeypatch.setattr("data_provider.akshare_fetcher.requests.get", _raise_disconnect)

    with caplog.at_level(logging.INFO):
        quote = akshare_fetcher._get_stock_realtime_quote_sina("601006")

    assert quote is None
    assert breaker.failures
    source_key, message = breaker.failures[0]
    assert source_key == "akshare_sina"
    assert "category=remote_disconnect" in message
    assert f"endpoint={SINA_REALTIME_ENDPOINT}" in caplog.text
    assert "新浪 实时行情接口失败:" in caplog.text


def test_tencent_realtime_http_status_logs_endpoint(caplog, monkeypatch, akshare_fetcher):
    breaker = _DummyCircuitBreaker()
    monkeypatch.setattr("data_provider.akshare_fetcher.get_realtime_circuit_breaker", lambda: breaker)
    monkeypatch.setattr(
        "data_provider.akshare_fetcher.requests.get",
        lambda *args, **kwargs: _DummyResponse(503, "service unavailable"),
    )

    with caplog.at_level(logging.INFO):
        quote = akshare_fetcher._get_stock_realtime_quote_tencent("601006")

    assert quote is None
    assert breaker.failures
    source_key, message = breaker.failures[0]
    assert source_key == "akshare_tencent"
    assert "category=http_status" in message
    assert "detail=HTTP 503" in message
    assert f"endpoint={TENCENT_REALTIME_ENDPOINT}" in caplog.text


def test_tencent_realtime_success_logs_endpoint(caplog, monkeypatch, akshare_fetcher):
    breaker = _DummyCircuitBreaker()
    monkeypatch.setattr("data_provider.akshare_fetcher.get_realtime_circuit_breaker", lambda: breaker)
    monkeypatch.setattr(
        "data_provider.akshare_fetcher.requests.get",
        lambda *args, **kwargs: _DummyResponse(200, _make_tencent_payload()),
    )

    with caplog.at_level(logging.INFO):
        quote = akshare_fetcher._get_stock_realtime_quote_tencent("601006")

    assert quote is not None
    assert quote.name == "大秦铁路"
    assert quote.price == 5.19
    assert breaker.successes == ["akshare_tencent"]
    assert f"endpoint={TENCENT_REALTIME_ENDPOINT}" in caplog.text
    assert "[实时行情-腾讯] 601006 大秦铁路:" in caplog.text
