from data_provider.provider_router import ProviderRouter


class _FakeManager:
    pass


class _FakeEastMoney:
    def __init__(self):
        self.quote_calls = []
        self.kline_calls = []

    def get_etf_quote(self, symbol, *, allow_remote=True):
        self.quote_calls.append((symbol, allow_remote))
        return {"source": "fake.etf", "stale": True, "error": None, "data": {"code": symbol, "price": 1.23}}

    def get_etf_daily_kline(self, symbol, period="daily", *, allow_remote=True):
        self.kline_calls.append((symbol, period, allow_remote))
        return {"source": "fake.etf.kline", "stale": True, "error": None, "data": [{"date": "2026-06-26", "close": 1.23}]}


class _FakeTHS:
    def __init__(self):
        self.snapshot_calls = []
        self.kline_calls = []

    def get_stock_snapshot(self, symbol):
        self.snapshot_calls.append(symbol)
        return {"source": "fake.ths", "stale": False, "error": None, "data": {"code": symbol, "price": 10.0}}

    def get_stock_daily_kline(self, symbol):
        self.kline_calls.append(symbol)
        return {"source": "fake.ths.kline", "stale": False, "error": None, "data": [{"date": "2026-06-26", "close": 10.0}]}


def _router():
    router = ProviderRouter(manager=_FakeManager())
    router.eastmoney = _FakeEastMoney()
    router.ths = _FakeTHS()
    return router


def test_etf_quote_uses_eastmoney_etf_path_and_skips_fuyao_stock_snapshot():
    router = _router()

    payload = router.get_realtime_quote("159516", allow_legacy_remote=False)

    assert payload["source"] == "fake.etf"
    assert payload["data"]["price"] == 1.23
    assert router.eastmoney.quote_calls == [("159516", False)]
    assert router.ths.snapshot_calls == []


def test_etf_detail_kline_uses_eastmoney_etf_daily_path():
    router = _router()

    payload = router.get_ths_stock_daily_kline("159516")

    assert payload["source"] == "fake.etf.kline"
    assert payload["data"][0]["close"] == 1.23
    assert router.eastmoney.kline_calls == [("159516", "daily", True)]
    assert router.ths.kline_calls == []


def test_stock_quote_still_uses_ths_snapshot_path():
    router = _router()

    payload = router.get_realtime_quote("600519", allow_legacy_remote=False)

    assert payload["source"] == "fake.ths"
    assert payload["data"]["price"] == 10.0
    assert router.ths.snapshot_calls == ["600519"]
    assert router.eastmoney.quote_calls == []
