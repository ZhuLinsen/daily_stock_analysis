# -*- coding: utf-8 -*-
"""Tests for the Miaoxiang (妙想 MX_API) supplementary data provider."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from data_provider.base import DataFetchError, DataFetcherManager
from data_provider.miaoxiang_fetcher import (
    MiaoxiangFetcher,
    _parse_money_yuan,
    _parse_number,
    _parse_ratio,
)


def _make_table(head: List[str], indicators: Dict[str, List[str]], name_map: Dict[str, str]) -> Dict[str, Any]:
    table: Dict[str, Any] = {"headName": head}
    table.update(indicators)
    return {"table": table, "nameMap": name_map, "entityName": "test"}


def _make_response(tables: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "status": 0,
        "message": "",
        "data": {"data": {"searchDataResultDTO": {"dataTableDTOList": tables}}},
    }


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload
        self.status_code = 200

    def json(self) -> Dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _fetcher_with_response(monkeypatch, payload: Dict[str, Any]) -> MiaoxiangFetcher:
    fetcher = MiaoxiangFetcher(api_key="test-key", cache_ttl=0)

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse(payload)

    monkeypatch.setattr("data_provider.miaoxiang_fetcher.requests.post", fake_post)
    return fetcher


class TestParsers:
    def test_parse_number(self):
        assert _parse_number("13.91") == 13.91
        assert _parse_number("14.03元") == 14.03
        assert _parse_number("1,234.5") == 1234.5
        assert _parse_number("无数据") is None

    def test_parse_money_yuan(self):
        assert _parse_money_yuan("-93.64万元") == pytest.approx(-936400.0)
        assert _parse_money_yuan("1.2亿") == pytest.approx(1.2e8)
        assert _parse_money_yuan("-493.5万") == pytest.approx(-4935000.0)

    def test_parse_ratio(self):
        assert _parse_ratio("83.24%") == pytest.approx(0.8324)
        assert _parse_ratio("0.83") == pytest.approx(0.83)
        assert _parse_ratio(None) is None


class TestChipDistribution:
    def test_prefers_table_with_more_target_fields(self, monkeypatch):
        """自然语言返回的表格组合不稳定：应选中字段最全的快照表而非单字段序列表。"""
        snapshot = {
            "table": {
                "headName": ["2026-08-21 21:52"],
                "f1": ["13.91"],
                "f2": ["4.79%"],
                "f3": ["83.24%"],
                "f4": ["10.57%"],
            },
            "nameMap": {"f1": "平均成本", "f2": "70%筹码集中度", "f3": "获利比例", "f4": "90%筹码集中度"},
            "entityName": "盛航股份",
        }
        series = {
            "table": {
                "headName": ["2026-08-21(日)", "2026-08-20(日)", "2026-08-19(日)"],
                "f1": ["14.03元", "14.02元", "14.01元"],
            },
            "nameMap": {"f1": "平均成本"},
            "entityName": "盛航股份",
        }
        fetcher = _fetcher_with_response(monkeypatch, _make_response([snapshot, series]))
        chip = fetcher.get_chip_distribution("001205")
        assert chip is not None
        assert chip.avg_cost == pytest.approx(13.91)
        assert chip.profit_ratio == pytest.approx(0.8324)
        assert chip.concentration_90 == pytest.approx(0.1057)
        assert chip.concentration_70 == pytest.approx(0.0479)
        assert chip.source == "miaoxiang"

    def test_non_cn_codes_return_none(self, monkeypatch):
        fetcher = _fetcher_with_response(monkeypatch, _make_response([]))
        assert fetcher.get_chip_distribution("AAPL") is None
        assert fetcher.get_chip_distribution("00700") is None


class TestCapitalFlow:
    def test_series_aggregation(self, monkeypatch):
        series = {
            "table": {
                "headName": ["2026-08-21(日)", "2026-08-20(日)", "2026-08-19(日)", "2026-08-18(日)", "2026-08-17(日)"],
                "f1": ["-93.64万", "-100万", "-200万", "300万", "400万"],
            },
            "nameMap": {"f1": "主力净流入资金"},
            "entityName": "盛航股份",
        }
        fetcher = _fetcher_with_response(monkeypatch, _make_response([series]))
        flow = fetcher.get_capital_flow("001205")
        assert flow["status"] == "partial"
        assert flow["stock_flow"]["main_net_inflow"] == pytest.approx(-936400.0)
        assert flow["stock_flow"]["inflow_5d"] == pytest.approx(-936400.0 - 1e6 - 2e6 + 3e6 + 4e6)
        assert "miaoxiang:capital_flow" in flow["source_chain"]

    def test_empty_response_returns_not_supported(self, monkeypatch):
        fetcher = _fetcher_with_response(monkeypatch, _make_response([]))
        flow = fetcher.get_capital_flow("001205")
        assert flow["status"] == "not_supported"
        assert flow["stock_flow"] == {}


class TestDailyNotSupported:
    def test_daily_raises_quickly(self):
        fetcher = MiaoxiangFetcher(api_key="test-key")
        from data_provider.base import DataFetchError

        with pytest.raises(DataFetchError):
            fetcher._fetch_raw_data("001205", "2026-01-01", "2026-01-31")


class TestCapitalFlowBudgetContract:
    """资金流补充必须受剩余阶段预算硬约束（PR #2247 评审 blocker）。"""

    def _manager_with_slow_supplement(self, sleep_seconds: float):
        import threading
        import time as _time

        from data_provider.base import DataFetcherManager

        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = []
        manager._fetchers_lock = threading.RLock()
        manager._fetchers_by_name = {}
        manager._fetcher_call_locks = {}
        manager._fetcher_call_locks_lock = manager._fetchers_lock
        manager._stock_name_cache = {}
        manager._stock_name_cache_lock = manager._fetchers_lock
        manager._priority_override_names = set()
        manager._fundamental_timeout_worker_limit = 8
        manager._fundamental_timeout_slots = __import__("threading").BoundedSemaphore(8)

        class _SlowSupplementFetcher:
            name = "SlowSupplementFetcher"
            priority = 90
            capital_flow_markets = {"cn"}
            calls = 0

            def get_capital_flow(self, stock_code):
                _SlowSupplementFetcher.calls += 1
                _time.sleep(sleep_seconds)
                return {"stock_flow": {"main_net_inflow": 1.0}, "source_chain": []}

        manager._fetchers = [_SlowSupplementFetcher()]
        return manager, _SlowSupplementFetcher

    def test_zero_budget_skips_supplement_entirely(self):
        manager, cls = self._manager_with_slow_supplement(sleep_seconds=0.0)
        payload = {"stock_flow": {}, "sector_rankings": {"top": [], "bottom": []}, "source_chain": [], "errors": []}
        manager._supplement_capital_flow_from_fetchers("001205", payload, budget_seconds=0.0)
        assert payload["stock_flow"] == {}
        assert cls.calls == 0
        assert "capital_flow supplement budget exhausted" in payload["errors"]

    def test_slow_supplement_is_cut_off_by_remaining_budget(self):
        manager, cls = self._manager_with_slow_supplement(sleep_seconds=5.0)
        payload = {"stock_flow": {}, "sector_rankings": {"top": [], "bottom": []}, "source_chain": [], "errors": []}
        start = __import__("time").time()
        manager._supplement_capital_flow_from_fetchers("001205", payload, budget_seconds=0.5)
        elapsed = __import__("time").time() - start
        # 线程超时硬切断:总耗时不得显著超过预算
        assert elapsed < 3.0, f"supplement blocked for {elapsed:.1f}s beyond budget"
        assert payload["stock_flow"] == {}  # 未拿到结果
        assert any("timeout" in str(e) for e in payload["errors"])

    def test_default_request_timeout_is_budget_friendly(self):
        """妙想请求默认超时必须与基本面阶段预算同量级（≤10s）。"""
        fetcher = MiaoxiangFetcher(api_key="test-key")
        assert fetcher.timeout <= 10


class TestPayloadContract:
    """MX query 响应契约:公开文档形态与实测形态都必须可用(评审 blocker)。"""

    PUBLIC_SHAPE = {
        "status": 0,
        "message": "",
        "data": {
            "dataTableDTOList": [
                {
                    "table": {"headName": ["2026-08-21"], "f1": ["13.91"], "f2": ["83.24%"]},
                    "nameMap": {"f1": "平均成本", "f2": "获利比例"},
                    "entityName": "测试股份",
                }
            ]
        },
    }

    LIVE_SHAPE = {
        "status": 0,
        "message": "",
        "data": {"data": {"searchDataResultDTO": {"dataTableDTOList": [
            {
                "table": {"headName": ["2026-08-21"], "f1": ["13.91"], "f2": ["83.24%"]},
                "nameMap": {"f1": "平均成本", "f2": "获利比例"},
                "entityName": "测试股份",
            }
        ]}}},
    }

    def test_public_documented_shape_parsed(self, monkeypatch):
        fetcher = _fetcher_with_response(monkeypatch, self.PUBLIC_SHAPE)
        chip = fetcher.get_chip_distribution("001205")
        assert chip.avg_cost == pytest.approx(13.91)
        assert chip.profit_ratio == pytest.approx(0.8324)

    def test_live_verified_shape_parsed(self, monkeypatch):
        fetcher = _fetcher_with_response(monkeypatch, self.LIVE_SHAPE)
        chip = fetcher.get_chip_distribution("001205")
        assert chip.avg_cost == pytest.approx(13.91)

    def test_empty_table_list_fails_open_with_data_fetch_error(self, monkeypatch):
        fetcher = _fetcher_with_response(monkeypatch, {"status": 0, "data": {"dataTableDTOList": []}})
        with pytest.raises(DataFetchError):
            fetcher.get_chip_distribution("001205")

    def test_malformed_structure_fails_open(self, monkeypatch):
        for malformed in (
            {"status": 0, "data": "not-a-dict"},
            {"status": 0},
            {"status": 0, "data": {"unexpected": 1}},
        ):
            fetcher = _fetcher_with_response(monkeypatch, malformed)
            with pytest.raises(DataFetchError):
                fetcher.get_chip_distribution("001205")

    def test_auth_or_quota_failure_status_nonzero(self, monkeypatch):
        fetcher = _fetcher_with_response(monkeypatch, {"status": 1001, "message": "鉴权失败/额度不足"})
        with pytest.raises(DataFetchError) as exc_info:
            fetcher.get_chip_distribution("001205")
        assert "1001" in str(exc_info.value)
        # 资金流侧必须 fail-open 为 not_supported,而不是抛出
        flow = fetcher.get_capital_flow("001205")
        assert flow["status"] == "not_supported"
        assert flow["stock_flow"] == {}


class TestSupplementMarketDetection:
    """补充源探测必须按市场能力收窄:仅 Futu OpenD(港股)时不得削减 A 股主预算(评审 blocker)。"""

    @staticmethod
    def _bare_manager(fetchers):
        import threading

        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = list(fetchers)
        manager._fetchers_lock = threading.RLock()
        manager._fetchers_by_name = {f.name: f for f in fetchers}
        manager._fetcher_call_locks = {}
        manager._fetcher_call_locks_lock = manager._fetchers_lock
        manager._stock_name_cache = {}
        manager._stock_name_cache_lock = manager._fetchers_lock
        manager._priority_override_names = set()
        manager._fundamental_timeout_worker_limit = 8
        manager._fundamental_timeout_slots = threading.BoundedSemaphore(8)
        return manager

    @staticmethod
    def _captured_budgets(manager, budgets):
        def fake_run_with_retry(task, timeout_seconds, task_name, *, quarantine_key=None):
            budgets.append((task_name, float(timeout_seconds)))
            return {"stock_flow": {}, "sector_rankings": {"top": [], "bottom": []},
                    "source_chain": [], "errors": [], "status": "not_supported"}, None, int(timeout_seconds * 1000)

        manager._run_with_retry = fake_run_with_retry
        return manager

    def test_futu_only_does_not_cut_cn_adapter_budget(self):
        class _FutuLike:
            name = "FutuFetcher"
            priority = 10

            def get_capital_flow(self, stock_code):
                return None  # 港股专用,A 股立即空返回

        budgets = []
        manager = self._captured_budgets(self._bare_manager([_FutuLike()]), budgets)
        manager.get_capital_flow_context("001205", budget_seconds=10.0)
        assert budgets and budgets[0] == ("capital_flow", 10.0)  # 全额预算,不被缩到 6

    def test_miaoxiang_present_cuts_adapter_budget(self):
        fetcher = MiaoxiangFetcher(api_key="test-key")
        budgets = []
        manager = self._captured_budgets(self._bare_manager([fetcher]), budgets)
        # 让补充调用立即失败,聚焦预算断言
        manager._run_with_timeout = lambda task, t, name, **kwargs: (None, f"{name} timeout", int(t * 1000))
        manager.get_capital_flow_context("001205", budget_seconds=10.0)
        assert budgets and budgets[0] == ("capital_flow", 6.0)  # 60% 留余量

    def test_supplement_loop_skips_non_market_fetchers(self):
        class _FutuLike:
            name = "FutuFetcher"
            priority = 10
            calls = 0

            def get_capital_flow(self, stock_code):
                _FutuLike.calls += 1
                return None

        payload = {"stock_flow": {}, "sector_rankings": {"top": [], "bottom": []},
                   "source_chain": [], "errors": []}
        manager = self._bare_manager([_FutuLike()])
        manager._supplement_capital_flow_from_fetchers("001205", payload, budget_seconds=5.0)
        assert _FutuLike.calls == 0  # 未声明 cn 能力,循环不调用


class TestFlowWindowCompletenessContract:
    """5日/10日窗口字段必须具备完整交易日数据才输出(评审 blocker OR-COR-mx-partial-window-sums-mislabelled)。"""

    @staticmethod
    def _fetcher_with_rows(monkeypatch, rows):
        series = {
            "table": {
                "headName": [f"2026-08-{20 - i:02d}(日)" for i in range(len(rows))],
                "f1": [f"{v}万" for v in rows],
            },
            "nameMap": {"f1": "主力净流入资金"},
            "entityName": "测试",
        }
        return _fetcher_with_response(monkeypatch, _make_response([series]))

    def test_two_rows_emit_no_window_fields(self, monkeypatch):
        flow = self._fetcher_with_rows(monkeypatch, [100, 200]).get_capital_flow("001205")
        assert flow["stock_flow"]["main_net_inflow"] == pytest.approx(1_000_000.0)
        assert flow["stock_flow"]["inflow_5d"] is None
        assert flow["stock_flow"]["inflow_10d"] is None

    def test_five_rows_emit_only_5d(self, monkeypatch):
        flow = self._fetcher_with_rows(monkeypatch, [100, 100, 100, 100, 100]).get_capital_flow("001205")
        assert flow["stock_flow"]["inflow_5d"] == pytest.approx(5_000_000.0)
        assert flow["stock_flow"]["inflow_10d"] is None

    def test_ten_rows_emit_both_windows(self, monkeypatch):
        flow = self._fetcher_with_rows(monkeypatch, [100] * 10).get_capital_flow("001205")
        assert flow["stock_flow"]["inflow_5d"] == pytest.approx(5_000_000.0)
        assert flow["stock_flow"]["inflow_10d"] == pytest.approx(10_000_000.0)


class TestMarketGatingContract:
    """市场门禁必须使用仓库权威判定:所有非 A 股形态都不得触发妙想请求(评审 blocker OR-COR-mx-bare-hk-short-code-misrouted 及同类)。"""

    NON_CN_CODES = [
        "1810",            # 4位裸港股短码(stock_list_parser 归类为 HK)
        "0001",            # 4位裸港股短码
        "00700",           # 5位裸港股
        "00700.HK",        # 后缀形式
        "HK00700",         # 前缀形式
        "AAPL",            # 美股裸码
        "BRK.B",           # 美股带点
        "AAPL.US",         # 美股后缀
        "6758.T",          # 日股
    ]

    ETF_CODES = ["510300", "159915"]

    def test_chip_skips_all_non_cn_without_http(self, monkeypatch):
        calls = []
        import data_provider.miaoxiang_fetcher as mx_mod

        def spy_post(*a, **k):
            calls.append(a)
            raise AssertionError("非 A 股代码不得发起妙想请求")

        monkeypatch.setattr(mx_mod.requests, "post", spy_post)
        fetcher = mx_mod.MiaoxiangFetcher(api_key="test-key")
        for code in self.NON_CN_CODES + self.ETF_CODES:
            assert fetcher.get_chip_distribution(code) is None, code
        assert calls == []

    def test_capital_flow_skips_all_non_cn_without_http(self, monkeypatch):
        import data_provider.miaoxiang_fetcher as mx_mod

        monkeypatch.setattr(
            mx_mod.requests, "post",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("非 A 股代码不得发起妙想请求")),
        )
        fetcher = mx_mod.MiaoxiangFetcher(api_key="test-key")
        for code in self.NON_CN_CODES + self.ETF_CODES:
            flow = fetcher.get_capital_flow(code)
            assert flow["status"] == "not_supported" and flow["stock_flow"] == {}, code


class TestManagerLevelMarketGate:
    """manager 级:非 A 股(含 .US 后缀)不得进入 cn 补充循环(评审建议的 manager 级回归)。"""

    def test_bare_hk_short_code_returns_none_at_manager_level(self, monkeypatch):
        import threading

        import data_provider.miaoxiang_fetcher as mx_mod

        monkeypatch.setattr(
            mx_mod.requests, "post",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("港股短码不得触发妙想请求")),
        )
        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = [mx_mod.MiaoxiangFetcher(api_key="test-key")]
        manager._fetchers_lock = threading.RLock()
        manager._fetchers_by_name = {"MiaoxiangFetcher": manager._fetchers[0]}
        manager._fetcher_call_locks = {}
        manager._fetcher_call_locks_lock = manager._fetchers_lock
        manager._stock_name_cache = {}
        manager._stock_name_cache_lock = manager._fetchers_lock
        manager._priority_override_names = set()
        # 港股短码走 manager 筹码链路:妙想被跳过,最终所有源失败返回 None
        assert manager.get_chip_distribution("1810") is None

    def test_us_suffix_never_enters_cn_supplement(self):
        import threading

        manager = DataFetcherManager.__new__(DataFetcherManager)
        manager._fetchers = [MiaoxiangFetcher(api_key="test-key")]
        manager._fetchers_lock = threading.RLock()
        manager._fetchers_by_name = {"MiaoxiangFetcher": manager._fetchers[0]}
        manager._fetcher_call_locks = {}
        manager._fetcher_call_locks_lock = manager._fetchers_lock
        manager._stock_name_cache = {}
        manager._stock_name_cache_lock = manager._fetchers_lock
        manager._priority_override_names = set()

        payload = {"stock_flow": {}, "sector_rankings": {"top": [], "bottom": []},
                   "source_chain": [], "errors": []}
        # 即使外层误判市场,补充循环也不得为美股后缀代码调用妙想
        manager._supplement_capital_flow_from_fetchers("AAPL.US", payload, budget_seconds=5.0)
        assert payload["stock_flow"] == {}


class TestUnifiedBudgetProbeGate:
    """外层预算探测必须与补充循环同口径:.US 请求不得被切走预算(评审 blocker OR-COR-mx-us-suffix-budget-probe-misclassified)。"""

    def test_us_suffix_short_circuits_to_not_supported(self):
        budgets = []
        manager = TestSupplementMarketDetection._bare_manager([MiaoxiangFetcher(api_key="test-key")])

        def fake_run_with_retry(task, timeout_seconds, task_name, *, quarantine_key=None):
            budgets.append((task_name, float(timeout_seconds)))
            return {"stock_flow": {}, "sector_rankings": {"top": [], "bottom": []},
                    "source_chain": [], "errors": [], "status": "not_supported"}, None, int(timeout_seconds * 1000)

        manager._run_with_retry = fake_run_with_retry
        block = manager.get_capital_flow_context("AAPL.US", budget_seconds=10.0)
        # .US 美股后缀:首层门禁直接 not_supported,不进入 CN 适配器,也不分配预算
        assert budgets == []
        assert block.get("status") == "not_supported"

    def test_cn_code_with_mx_still_gets_budget_split(self):
        budgets = []
        manager = TestSupplementMarketDetection._bare_manager([MiaoxiangFetcher(api_key="test-key")])

        def fake_run_with_retry(task, timeout_seconds, task_name, *, quarantine_key=None):
            budgets.append((task_name, float(timeout_seconds)))
            return {"stock_flow": {}, "sector_rankings": {"top": [], "bottom": []},
                    "source_chain": [], "errors": [], "status": "not_supported"}, None, int(timeout_seconds * 1000)

        manager._run_with_retry = fake_run_with_retry
        manager._run_with_timeout = lambda task, t, name, **kwargs: (None, f"{name} timeout", int(t * 1000))
        manager.get_capital_flow_context("001205", budget_seconds=10.0)
        assert budgets and budgets[0] == ("capital_flow", 6.0)


class TestConfigSchemaContract:
    """system-config schema 回归:MX 设置项的字段类型与敏感属性(评审建议)。"""

    def test_mx_apikey_is_sensitive_password_field(self):
        from src.core.config_registry import get_field_definition

        field = get_field_definition("MX_APIKEY")
        assert field.get("data_type") == "string"
        assert field.get("ui_control") == "password"
        assert field.get("is_sensitive") is True
        assert field.get("category") == "data_source"

    def test_mx_priority_is_integer_field(self):
        from src.core.config_registry import get_field_definition

        field = get_field_definition("MX_PRIORITY")
        assert field.get("data_type") == "integer"
        assert field.get("is_sensitive") is False
        assert field.get("validation", {}).get("min") == 0


class TestSupplementRuntimeContracts:
    @pytest.mark.parametrize("fresh_instances", [False, True])
    def test_concurrent_burst_does_not_leave_late_quota_requests(self, monkeypatch, fresh_instances):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier, Event, current_thread
        from types import SimpleNamespace

        barrier, release = Barrier(8), Event()
        posts = []
        monkeypatch.setattr("data_provider.miaoxiang_fetcher.MX_MIN_REQUEST_INTERVAL_SECONDS", 0)
        monkeypatch.setattr("src.config.get_config", lambda: SimpleNamespace(fundamental_retry_max=1))
        shared = MiaoxiangFetcher(api_key="test-key", cache_ttl=0)
        managers = [DataFetcherManager(fetchers=[MiaoxiangFetcher(api_key="test-key", cache_ttl=0)
                                                if fresh_instances else shared]) for _ in range(8)]
        for manager in managers:
            manager._fundamental_adapter.get_capital_flow = lambda code: {
                "status": "not_supported", "stock_flow": {}, "sector_rankings": {}, "errors": [],
            }

        def blocked_post(*args, **kwargs):
            posts.append(current_thread())
            assert release.wait(timeout=5)
            table = _make_table(["2026-08-21"], {"0": ["100万"]}, {"0": "主力净流入资金"})
            return _FakeResponse(_make_response([table]))

        def call(index):
            barrier.wait(timeout=2)
            return managers[index].get_capital_flow_context(str(600100 + index), budget_seconds=0.15)

        monkeypatch.setattr("data_provider.miaoxiang_fetcher.requests.post", blocked_post)
        try:
            with ThreadPoolExecutor(max_workers=8) as callers:
                list(callers.map(call, range(8)))
            assert len(posts) == 1
            result, error, _ = managers[0]._run_with_timeout(lambda: "healthy", 1, "unrelated")
            assert result == "healthy" and error is None
        finally:
            release.set()
            for worker in posts:
                worker.join(timeout=2)
                assert not worker.is_alive()
        assert len(posts) == 1  # No queued HTTP calls execute after their callers timed out.
        assert managers[0].get_capital_flow_context("600519", budget_seconds=1)["data"]["stock_flow"]["main_net_inflow"] == 1e6

    @pytest.mark.parametrize("active_kind", ["chip", "flow"])
    @pytest.mark.parametrize("fresh_instance", [False, True])
    def test_chip_and_flow_share_nonblocking_admission(self, monkeypatch, active_kind, fresh_instance):
        from threading import Event, Thread

        entered, release = Event(), Event()
        posts, errors = [], []
        fetcher = MiaoxiangFetcher(api_key="test-key", cache_ttl=0)
        other = MiaoxiangFetcher(api_key="test-key", cache_ttl=0) if fresh_instance else fetcher
        table = _make_table(["2026-08-21"], {"0": ["13.91"], "1": ["100万"]},
                            {"0": "平均成本", "1": "主力净流入资金"})

        def blocked_post(*args, **kwargs):
            posts.append(kwargs["json"]["toolQuery"])
            entered.set()
            assert release.wait(timeout=5)
            return _FakeResponse(_make_response([table]))

        def active():
            try:
                getter = fetcher.get_chip_distribution if active_kind == "chip" else fetcher.get_capital_flow
                getter("600519")
            except Exception as exc:
                errors.append(exc)

        monkeypatch.setattr("data_provider.miaoxiang_fetcher.requests.post", blocked_post)
        monkeypatch.setattr("data_provider.miaoxiang_fetcher.MX_MIN_REQUEST_INTERVAL_SECONDS", 0)
        worker = Thread(target=active)
        worker.start()
        try:
            assert entered.wait(timeout=2)
            if active_kind == "chip":
                payload = {"stock_flow": {}, "errors": []}
                DataFetcherManager(fetchers=[other])._supplement_capital_flow_from_fetchers("600330", payload, 0.2)
                assert payload["stock_flow"] == {}
                assert any("仍在执行" in error for error in payload["errors"])
            else:
                with pytest.raises(DataFetchError, match="仍在执行"):
                    other.get_chip_distribution("600330")
            assert len(posts) == 1
        finally:
            release.set()
            worker.join(timeout=2)
            assert not worker.is_alive()
        assert errors == [] and len(posts) == 1
        assert other.get_chip_distribution("600330").avg_cost == pytest.approx(13.91)

    @pytest.mark.parametrize("fresh_manager", [False, True])
    def test_timed_out_requests_do_not_queue_or_starve_other_work(self, monkeypatch, fresh_manager):
        from threading import Event, current_thread
        from types import SimpleNamespace

        release = Event()
        workers = []
        http_calls = []
        fetcher = MiaoxiangFetcher(api_key="test-key", cache_ttl=0)
        manager = DataFetcherManager(fetchers=[fetcher])
        original_getter = fetcher.get_capital_flow
        table = _make_table(["2026-08-21"], {"0": ["100万"]}, ["主力净流入资金"])
        # Keep this concurrency test independent of the separate nameMap defect.
        table["nameMap"] = {"0": "主力净流入资金"}

        def tracked_getter(code):
            workers.append(current_thread())
            return original_getter(code)

        def blocked_post(*args, **kwargs):
            http_calls.append(kwargs["json"]["toolQuery"])
            assert release.wait(timeout=5), "test did not release the fake HTTP call"
            return _FakeResponse(_make_response([table]))

        monkeypatch.setattr(fetcher, "get_capital_flow", tracked_getter)
        monkeypatch.setattr("data_provider.miaoxiang_fetcher.requests.post", blocked_post)
        monkeypatch.setattr("data_provider.miaoxiang_fetcher.MX_MIN_REQUEST_INTERVAL_SECONDS", 0)

        def supplement(target, code, budget=0.02):
            payload = {"stock_flow": {}, "source_chain": [], "errors": []}
            target._supplement_capital_flow_from_fetchers(code, payload, budget)
            return payload

        try:
            for index in range(12):
                target = DataFetcherManager(fetchers=[fetcher]) if fresh_manager else manager
                assert supplement(target, str(600100 + index))["stock_flow"] == {}
            assert len(workers) == 1
            assert len(http_calls) == 1
            result, error, _ = manager._run_with_timeout(lambda: "healthy", 1, "unrelated")
            assert result == "healthy" and error is None

            healthy = SimpleNamespace(
                name="HealthyFlowFixture", priority=99, capital_flow_markets={"cn"},
                get_capital_flow=lambda code: {"stock_flow": {"main_net_inflow": 2}},
            )
            alternate = DataFetcherManager(fetchers=[fetcher, healthy])
            assert supplement(alternate, "600519", 0.2)["stock_flow"]["main_net_inflow"] == 2
        finally:
            release.set()
            for worker in workers:
                worker.join(timeout=2)
                assert not worker.is_alive()

        assert supplement(manager, "600519", 1)["stock_flow"]["main_net_inflow"] == 1_000_000
        assert len(http_calls) == 2  # One abandoned call, then one fresh call after actual exit.

    def test_cn_daily_route_skips_mx_before_calls_and_telemetry(self, monkeypatch):
        from types import SimpleNamespace
        import pandas as pd

        calls = []
        started = []
        fetcher = MiaoxiangFetcher(api_key="test-key", priority=0)

        def unsupported_daily(**kwargs):
            calls.append(kwargs)
            raise AssertionError("supplement-only provider entered daily route")

        monkeypatch.setattr(fetcher, "get_daily_data", unsupported_daily)
        monkeypatch.setattr("data_provider.base.record_provider_run_started", lambda **kwargs: started.append(kwargs))
        monkeypatch.setattr("data_provider.base.record_provider_run", lambda **kwargs: None)
        healthy = SimpleNamespace(name="CnDailyFixture", priority=1,
                                  get_daily_data=lambda **kwargs: pd.DataFrame({"close": [10.0]}))
        manager = DataFetcherManager(fetchers=[fetcher, healthy])
        try:
            frame, source = manager.get_daily_data("600519")
            assert source == "CnDailyFixture" and not frame.empty
            assert calls == []
            assert [entry["provider"] for entry in started] == ["CnDailyFixture"]
        finally:
            DataFetcherManager.reset_daily_source_health()


class TestListNameMapContract:
    def test_chip_table_selection_and_rows_share_list_mapping(self, monkeypatch):
        table = _make_table(["2026-08-21"], {"0": ["13.91"], "1": ["83.24%"]},
                            ["平均成本", "获利比例"])
        chip = _fetcher_with_response(monkeypatch, _make_response([table])).get_chip_distribution("001205")
        assert chip.avg_cost == pytest.approx(13.91)
        assert chip.profit_ratio == pytest.approx(0.8324)

    def test_money_table_selection_and_rows_share_list_mapping(self, monkeypatch):
        table = _make_table(["2026-08-21"], {"0": ["13.91"], "1": ["100万"]},
                            ["收盘价", "主力净流入资金"])
        flow = _fetcher_with_response(monkeypatch, _make_response([table])).get_capital_flow("001205")
        assert flow["stock_flow"]["main_net_inflow"] == pytest.approx(1_000_000)


class TestCapitalFlowColumnSelection:
    @pytest.mark.parametrize("with_price_column", [False, True])
    @pytest.mark.parametrize("descending", [False, True])
    def test_short_amount_column_preserves_missing_date(self, monkeypatch, with_price_column, descending):
        indicators = {"f1": ["100万"] * 5}
        labels = {"f1": "主力净流入资金"}
        if with_price_column:
            indicators["f2"] = ["13.91"] * 6
            labels["f2"] = "收盘价"
        dates = sorted([f"2026-08-{16 + i:02d}" for i in range(6)], reverse=descending)
        table = _make_table(dates, indicators, labels)
        flow = _fetcher_with_response(monkeypatch, _make_response([table])).get_capital_flow("001205")
        if descending:  # The missing oldest observation is outside the latest five days.
            assert flow["stock_flow"]["main_net_inflow"] == pytest.approx(1_000_000)
            assert flow["stock_flow"]["inflow_5d"] == pytest.approx(5_000_000)
        else:
            assert flow["stock_flow"]["main_net_inflow"] is None
            assert flow["stock_flow"]["inflow_5d"] is None

    @pytest.mark.parametrize("ratio", ["3.5%", "3.5％"])
    def test_percentage_is_not_a_money_value_even_under_amount_label(self, monkeypatch, ratio):
        table = _make_table(["2026-08-21"], {"f1": [ratio]}, {"f1": "主力净流入资金"})
        flow = _fetcher_with_response(monkeypatch, _make_response([table])).get_capital_flow("001205")
        assert flow["stock_flow"] == {}

    def test_missing_latest_amount_does_not_backfill_previous_day(self, monkeypatch):
        table = _make_table(["2026-08-21", "2026-08-20"], {"f1": [None, "100万"]},
                            {"f1": "主力净流入资金"})
        flow = _fetcher_with_response(monkeypatch, _make_response([table])).get_capital_flow("001205")
        assert flow["stock_flow"]["main_net_inflow"] is None
        assert flow["stock_flow"]["inflow_5d"] is None

    def test_missing_amount_does_not_compress_trading_window(self, monkeypatch):
        table = _make_table(
            [f"2026-08-{21 - i:02d}" for i in range(10)],
            {"f1": ["100万", None] + ["100万"] * 8},
            {"f1": "主力净流入资金"},
        )
        flow = _fetcher_with_response(monkeypatch, _make_response([table])).get_capital_flow("001205")
        assert flow["stock_flow"]["main_net_inflow"] == pytest.approx(1_000_000)
        assert flow["stock_flow"]["inflow_5d"] is None
        assert flow["stock_flow"]["inflow_10d"] is None

    @pytest.mark.parametrize("preceding_label", ["收盘价", "主力净流入占比"])
    def test_amount_is_selected_by_label_not_column_order(self, monkeypatch, preceding_label):
        table = _make_table(
            ["2026-08-21", "2026-08-20", "2026-08-19", "2026-08-18", "2026-08-17"],
            {"f1": ["13.91"] * 5, "f2": ["100万", "200万", "300万", "400万", "500万"]},
            {"f1": preceding_label, "f2": "主力净流入资金"},
        )
        flow = _fetcher_with_response(monkeypatch, _make_response([table])).get_capital_flow("001205")
        assert flow["stock_flow"]["main_net_inflow"] == pytest.approx(1_000_000)
        assert flow["stock_flow"]["inflow_5d"] == pytest.approx(15_000_000)

    def test_ratio_only_table_does_not_become_currency(self, monkeypatch):
        table = _make_table(["2026-08-21"], {"f1": ["3.5%"]}, {"f1": "主力净流入占比"})
        flow = _fetcher_with_response(monkeypatch, _make_response([table])).get_capital_flow("001205")
        assert flow["status"] == "not_supported"
        assert flow["stock_flow"] == {}

    def test_missing_amount_never_falls_back_to_closing_price(self, monkeypatch):
        table = _make_table(["2026-08-21"], {"f1": ["13.91"], "f2": [None]},
                            {"f1": "收盘价", "f2": "主力净流入资金"})
        flow = _fetcher_with_response(monkeypatch, _make_response([table])).get_capital_flow("001205")
        assert flow["status"] == "not_supported"
        assert flow["stock_flow"] == {}

    def test_longer_ratio_table_cannot_hide_amount_table(self, monkeypatch):
        ratio = _make_table(["2026-08-21", "2026-08-20"], {"f1": ["3%", "4%"]},
                            {"f1": "主力净流入占比"})
        amount = _make_table(["2026-08-21"], {"f1": ["100万"]}, {"f1": "主力净流入资金"})
        flow = _fetcher_with_response(monkeypatch, _make_response([ratio, amount])).get_capital_flow("001205")
        assert flow["stock_flow"]["main_net_inflow"] == pytest.approx(1_000_000)
