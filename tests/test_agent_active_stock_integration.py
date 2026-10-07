"""Phase 6B contracts on real SQLite; model/external execution is not involved."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import json
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import event, inspect, text

from src.agent.stock_scope import extract_stock_codes
from src.config import Config
from src.services.stock_list_parser import IndexRegistry
from src.storage import ChatSessionStateConflict, DatabaseManager


@pytest.fixture(autouse=True)
def isolated_database_manager():
    DatabaseManager.reset_instance()
    Config.reset_instance()
    yield
    DatabaseManager.reset_instance()
    Config.reset_instance()


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(db_url=f"sqlite:///{tmp_path / 'chat.db'}")


@pytest.fixture
def chat_stock_index(tmp_path, monkeypatch):
    from src.data import stock_index_loader

    def row(code, display, name, market="CN", kind="stock", aliases=None):
        return [code, display, name, "fixture", "fx", aliases or [], market, kind, True, 1]

    payload = [
        row("600519.SH", "600519", "贵州茅台", aliases=["茅台", "SH600519"]),
        row("300750.SZ", "300750", "宁德时代"),
        row("000001.SZ", "000001", "平安银行"),
        row("sh000001", "sh000001", "上证指数", kind="index", aliases=["000001.SH"]),
        row("688981.SH", "688981", "中芯国际"),
        row("00981.HK", "00981", "中芯国际", market="HK"),
        row("005930.KS", "005930.KS", "三星电子", market="KR"),
        row("AAPL", "AAPL", "苹果", market="US"),
    ]
    path = tmp_path / "stocks.index.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    stock_index_loader.clear_stock_index_cache()
    monkeypatch.setattr(stock_index_loader, "get_stock_index_candidate_paths", lambda: (path,))
    monkeypatch.setattr(stock_index_loader, "get_remote_stock_index_cache_path", lambda: tmp_path / "absent.json")
    yield path
    stock_index_loader.clear_stock_index_cache()


def test_chat_name_lookup_reuses_valid_selected_payload_and_excludes_code_aliases(chat_stock_index):
    from src.data.stock_index_loader import get_chat_stock_lookup

    lookup = get_chat_stock_lookup()
    assert lookup["names"]["茅台"] == (("600519.SH", "贵州茅台", "stock"),)
    assert len(lookup["names"]["中芯国际"]) == 2
    assert "sh600519" not in lookup["names"]
    assert "000001.sh" not in lookup["names"]
    assert lookup["index_rows"][0][0] == "sh000001"


@pytest.fixture
def action_chat_api(actual_chat_api, monkeypatch):
    from src.agent.llm_adapter import LLMResponse, LLMToolAdapter

    client, requests, config = actual_chat_api
    model_calls = []

    def controlled_model(_self, messages, *_args, **_kwargs):
        model_calls.append(messages)
        return LLMResponse(content='{"signal":"hold","confidence":0.5,"reasoning":"controlled action"}',
                           model="fixture", provider="fixture")

    monkeypatch.setattr(LLMToolAdapter, "call_with_tools", controlled_model)
    config.agent_orchestrator_mode = "quick"
    config.agent_memory_enabled = False
    return client, requests, model_calls, config


@pytest.mark.parametrize("arch", ["single", "multi"])
@pytest.mark.parametrize("prior,message,expected,clarify", [
    (None, "不要分析300750", None, False),
    ("600519", "不要改看300750，继续分析600519", "600519", False),
    ("600519", "是否改看300750？", "600519", True),
    (None, "是否改看300750？", None, True),
    ("600519", "如果改看300750会怎么样", "600519", True),
    ("600519", "他说“从600519改看300750”", "600519", True),
    ("300750", "是否改看300750？", "300750", True),
    ("000001", "是否改看300750？", "000001", True),
    ("600519", "不要比较600519和300750，继续分析600519", "600519", False),
])
def test_convergence_operation_qualification_reaches_real_api(
    action_chat_api, db, arch, prior, message, expected, clarify,
):
    client, requests, calls, config = action_chat_api
    config.agent_arch = arch
    sid = "convergence-action"
    if prior:
        response = client.post("/api/v1/agent/chat", json={"session_id": sid, "message": f"分析{prior}", "skills": []})
        assert response.status_code == 200
    before = db.read_chat_session_snapshot(sid)
    count = len(requests) + len(calls)
    response = client.post("/api/v1/agent/chat/stream", json={"session_id": sid, "message": message, "skills": []})
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[0]["type"] == "accepted" and events[-1]["type"] == "done"
    after = db.read_chat_session_snapshot(sid)
    assert (after["active_stock_context"] or {}).get("stock_code") == expected
    assert after["active_stock_context"] == before["active_stock_context"]
    assert after["session_state_version"] == before["session_state_version"] + 1
    if clarify:
        assert len(requests) + len(calls) == count
    elif arch == "single":
        assert requests[-1].stock_scope.allowed_stock_codes == ({expected} if expected else set())


def test_convergence_complete_tokens_have_only_actual_occurrence_spans(chat_stock_index):
    from src.services.agent_chat_session_service import _stock_lookup
    from src.agent.chat_object_decision import object_mentions

    registry, lookup = _stock_lookup()
    message = "从000001改看000001.SH"
    mentions = object_mentions(message, registry, lookup)
    assert [(item.start, item.end, item.identity.canonical_id) for item in mentions] == [
        (1, 7, "sz000001"), (9, 18, "sh000001"),
    ]


@pytest.mark.parametrize("tool_name", ["get_chip_distribution", "get_stock_info", "get_capital_flow", "get_stock_backtest_summary"])
def test_convergence_chip_capability_blocks_index_before_real_manager_route(chat_stock_index, monkeypatch, tool_name):
    from data_provider.base import DataFetcherManager
    from data_provider.realtime_types import ChipDistribution
    from src.agent.factory import get_tool_registry
    from src.agent.stock_scope import StockIdentity, StockScope
    from src.agent.tool_surface import ToolSurface
    from src.agent.tools import data_tools, execution
    from src.services.stock_list_parser import default_index_registry

    calls = []

    class ControlledProvider:
        name = "AkshareFetcher"
        priority = 1

        def get_chip_distribution(self, code):
            calls.append(code)
            return ChipDistribution(code=code, date="2026-10-06", source="fixture", profit_ratio=0.5,
                                    avg_cost=10, cost_90_low=8, cost_90_high=12)

    manager = DataFetcherManager(fetchers=[ControlledProvider()])
    monkeypatch.setattr(data_tools, "_get_fetcher_manager", lambda: manager)
    registry = default_index_registry()
    monkeypatch.setattr(execution, "_default_index_registry_or_none", lambda: registry)
    Config.get_instance().enable_chip_distribution = True
    identity = StockIdentity.from_code("sh000001", registry)
    scope = StockScope(expected_stock_code="sh000001", allowed_stock_codes={"sh000001"},
                       strict=True, identities=(identity,))
    result = ToolSurface(get_tool_registry()).execute_tool(
        tool_name, {"stock_code": "sh000001"}, execution.ToolAccessContext(stock_scope=scope),
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "stock_tool_unsupported"
    assert calls == []


def test_convergence_registry_failure_of_other_scope_member_is_local(db, chat_stock_index, monkeypatch):
    from datetime import date, timedelta
    import pandas as pd
    from src.agent.factory import get_tool_registry
    from src.agent.stock_scope import StockIdentity, StockScope
    from src.agent.tools import execution
    from src.services.stock_list_parser import IndexRegistry, default_index_registry
    from src.services import history_loader

    registry = default_index_registry()
    identities = tuple(StockIdentity.from_code(code, registry) for code in ("000001", "sh000001"))
    scope = StockScope(expected_stock_code="000001", allowed_stock_codes={"000001", "sh000001"},
                       strict=True, identities=identities)
    changed = IndexRegistry(())  # index gone; independently valid stock remains available
    monkeypatch.setattr(execution, "_default_index_registry_or_none", lambda: changed)
    target = date(2026, 10, 6)
    db.save_daily_data(pd.DataFrame([{"date": target - timedelta(days=i), "close": 111} for i in range(30)]),
                       "000001", "fixture")
    token = history_loader.set_frozen_target_date(target)
    try:
        result = execution.execute_runner_tool_call(
            tool_call=SimpleNamespace(name="get_daily_history", arguments={"stock_code": "000001", "days": 30}),
            tool_registry=get_tool_registry(), stock_scope=scope,
        )
    finally:
        history_loader.reset_frozen_target_date(token)
    assert result[5] is None and result[2] is True
    assert {row["close"] for row in json.loads(result[1])["data"]} == {111}


def test_convergence_builtin_asset_contracts_match_actual_factory():
    from src.agent.factory import get_tool_registry

    expected = {
        "get_realtime_quote": ("stock", "index"), "get_daily_history": ("stock", "index"),
        "get_chip_distribution": ("stock",), "get_analysis_context": ("stock", "index"),
        "get_stock_info": ("stock",), "get_capital_flow": ("stock",),
        "analyze_trend": ("stock", "index"), "calculate_ma": ("stock", "index"),
        "get_volume_analysis": ("stock", "index"), "analyze_pattern": ("stock", "index"),
        "search_stock_news": ("stock", "index"), "search_comprehensive_intel": ("stock", "index"),
        "get_stock_backtest_summary": ("stock",),
    }
    registry = get_tool_registry()
    # Inspect actual public tool list, not a copied registration fixture.
    names = {item["function"]["name"] for item in registry.to_openai_tools()}
    actual = {name: registry.resolve(name).policy.supported_asset_types for name in names
              if any(parameter.name == "stock_code" for parameter in registry.resolve(name).parameters)}
    assert actual == expected
    for name in ("get_skill_backtest_summary", "get_strategy_backtest_summary"):
        assert registry.resolve(name).policy.scope_dimensions == []
        assert registry.resolve(name).policy.supported_asset_types is None


@pytest.mark.parametrize("entry", ["runner", "surface"])
def test_convergence_unknown_custom_applicability_rejects_only_that_call(chat_stock_index, entry):
    from src.agent.stock_scope import StockIdentity, StockScope
    from src.agent.tool_surface import ToolSurface
    from src.agent.tools import execution
    from src.agent.tools.registry import ToolDefinition, ToolParameter, ToolPolicy, ToolRegistry
    from src.services.stock_list_parser import default_index_registry

    identity = StockIdentity.from_code("600519", default_index_registry())
    scope = StockScope(expected_stock_code=identity.stock_code, allowed_stock_codes={identity.stock_code},
                       strict=True, identities=(identity,))
    calls = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="unknown", description="Custom contract unknown",
        parameters=[ToolParameter("stock_code", "string", "Stock")],
        handler=lambda stock_code: calls.append(stock_code),
        policy=ToolPolicy.declared(read_only=True, scope_dimensions=["stock"]),
    ))
    if entry == "surface":
        result = ToolSurface(registry).execute_tool("unknown", {"stock_code": "600519"},
                                                    execution.ToolAccessContext(stock_scope=scope))
        assert result["error"]["code"] == "stock_tool_contract_unknown"
    else:
        result = execution.execute_runner_tool_call(
            tool_call=SimpleNamespace(name="unknown", arguments={"stock_code": "600519"}),
            tool_registry=registry, stock_scope=scope,
        )
        assert result[5]["error"] == "stock_tool_contract_unknown"
    assert calls == []
    # An explicitly legacy scope still uses the original compatible behavior.
    result = ToolSurface(registry).execute_tool("unknown", {"stock_code": "600519"},
        execution.ToolAccessContext(stock_scope=StockScope(allowed_stock_codes={"600519"})))
    assert result["ok"] and calls == ["600519"]


@pytest.mark.parametrize("token", ["000001", "000001.SH"])
def test_convergence_real_quote_route_retains_target_and_rejects_wrong_provider(
    chat_stock_index, monkeypatch, token,
):
    from data_provider import base
    from data_provider.realtime_types import UnifiedRealtimeQuote, RealtimeSource
    from src.agent.factory import get_tool_registry
    from src.agent.stock_scope import StockIdentity, StockScope
    from src.agent.tools import execution, data_tools
    from src.services.stock_list_parser import default_index_registry

    calls = []

    class Primary:
        name = "EfinanceFetcher"
        priority = 0

        def get_realtime_quote(self, code):
            calls.append((self.name, code))
            return UnifiedRealtimeQuote(code=code, name="stock fixture", price=111, source=RealtimeSource.EFINANCE)

    class Secondary:
        name = "AkshareFetcher"
        priority = 1

        def get_realtime_quote(self, code, source="em"):
            calls.append((source, code))
            # Index first provider is wrong; stock supplementary response is
            # wrong. Neither may enter a result by rewriting its code.
            returned = code if source == "sina" else "600519"
            return UnifiedRealtimeQuote(code=returned, name="index fixture", price=333,
                                        volume_ratio=999, source=RealtimeSource.TENCENT)

    manager = base.DataFetcherManager(fetchers=[Primary(), Secondary()])
    config = Config.get_instance()
    config.enable_realtime_quote = True
    config.realtime_source_priority = "efinance,akshare_em"
    identity = StockIdentity.from_code(token, default_index_registry())
    scope = StockScope(expected_stock_code=identity.stock_code, allowed_stock_codes={identity.stock_code},
                       strict=True, identities=(identity,))

    def controlled_manager():
        # Once the guard has resolved this call, a second classification would
        # be a test failure; real manager routing/provider calls remain intact.
        monkeypatch.setattr(base, "parse_analysis_target", lambda *_args: pytest.fail("downstream reclassification"))
        return manager

    monkeypatch.setattr(data_tools, "_get_fetcher_manager", controlled_manager)
    result = execution.execute_runner_tool_call(
        tool_call=SimpleNamespace(name="get_realtime_quote", arguments={"stock_code": token}),
        tool_registry=get_tool_registry(), stock_scope=scope,
    )
    assert result[5] is None and result[2] is True
    body = json.loads(result[1])
    assert body["code"] == identity.stock_code
    if identity.asset_type == "index":
        assert body["price"] == 333
        assert calls == [("tencent", "sh000001"), ("sina", "sh000001")]
    else:
        assert body["price"] == 111 and body["volume_ratio"] is None
        assert calls == [("EfinanceFetcher", "000001"), ("em", "000001")]


def test_convergence_real_news_handler_ignores_model_subject_name(db, chat_stock_index, monkeypatch):
    from src.agent.factory import get_tool_registry
    from src.agent.tools import execution, search_tools
    from src.services.agent_chat_session_service import AgentChatSessionService

    service = AgentChatSessionService(db)
    turn = service.prepare_session_turn(Config.get_instance(), "news-subject", "分析600519", [])
    calls = []

    def search(code, name, **kwargs):
        calls.append((code, name))
        return SimpleNamespace(success=True, results=[], query=f"{code} {name}", provider="fixture")

    monkeypatch.setattr(search_tools, "_get_search_service", lambda: SimpleNamespace(
        is_available=True, search_stock_news=search,
    ))
    result = execution.execute_runner_tool_call(
        tool_call=SimpleNamespace(name="search_stock_news", arguments={"stock_code": "600519", "stock_name": "宁德时代"}),
        tool_registry=get_tool_registry(), stock_scope=turn.stock_scope,
    )
    assert result[5] is None and result[2] is True
    assert calls == [("600519", "贵州茅台")]


@pytest.mark.parametrize("message, expected", [
    ("分析５１０３００", ["sh510300"]),
    ("分析159915", ["sz159915"]),
    ("分析005930.KS", ["005930.KS"]),
    ("从000001改看000001.SH", ["sz000001", "sh000001"]),
    ("从600519改看600519", ["sh600519", "sh600519"]),
])
def test_convergence_occurrences_share_normalized_view_and_complete_identity(chat_stock_index, message, expected):
    import unicodedata
    from src.agent.chat_object_decision import object_mentions
    from src.services.agent_chat_session_service import _stock_lookup

    registry, lookup = _stock_lookup()
    text = unicodedata.normalize("NFKC", message)
    mentions = [item for item in object_mentions(text, registry, lookup) if item.kind == "code"]
    assert [item.identity.canonical_id for item in mentions] == expected
    assert all(text[item.start:item.end] == item.raw for item in mentions)
    assert len({(item.start, item.end) for item in mentions}) == len(expected)


def test_convergence_casefold_name_expansion_maps_back_to_nfkc_coordinates(chat_stock_index):
    import unicodedata
    from src.agent.chat_object_decision import object_mentions, decide_chat_object
    from src.services.agent_chat_session_service import _stock_lookup

    registry, lookup = _stock_lookup()
    lookup = dict(lookup, names={"strasse": (("AAPL", "Straße", "stock"),)})
    text = unicodedata.normalize("NFKC", "请帮我分析Ｓｔｒａße")
    name = next(item for item in object_mentions(text, registry, lookup) if item.kind == "name")
    assert text[name.start:name.end] == "Straße" and name.end - name.start == 6
    result = decide_chat_object(text, None, registry, lookup)
    assert result.kind == "confirm" and result.target.identity.canonical_id == "AAPL"


@pytest.mark.parametrize("message,expected", [
    ("茅台现在适合买入吗？", "600519"),
    ("波浪理论看宁德时代", "300750"),
])
def test_convergence_existing_web_stock_prompts_still_confirm_via_real_api(actual_chat_api, db, message, expected):
    client, requests, _config = actual_chat_api
    response = client.post("/api/v1/agent/chat", json={"session_id": "web-prompt", "message": message, "skills": []})
    assert response.status_code == 200
    assert response.json()["active_stock_context"]["stock_code"] == expected
    assert db.read_chat_session_snapshot("web-prompt")["active_stock_context"]["stock_code"] == expected
    assert requests[-1].stock_scope.allowed_stock_codes == {expected}


def test_convergence_targets_do_not_mix_across_real_tool_threads(chat_stock_index):
    from threading import Barrier
    from src.agent.stock_scope import StockScope, StockIdentity
    from src.agent.tool_surface import ToolSurface
    from src.agent.tools import execution
    from src.agent.tools.registry import ToolRegistry, ToolPolicy, ToolDefinition, ToolParameter
    from src.services.stock_list_parser import default_index_registry

    barrier = Barrier(2)

    def external_probe(stock_code):
        barrier.wait(timeout=5)
        target = execution.get_tool_analysis_target(stock_code)
        identity = execution.get_tool_stock_identity(stock_code)
        return {"canonical": target.canonical_id, "type": target.asset_type, "code": identity.stock_code}

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="probe", description="Controlled downstream observation",
        parameters=[ToolParameter("stock_code", "string", "Stock")], handler=external_probe,
        policy=ToolPolicy.declared(read_only=True, scope_dimensions=["stock"], supported_asset_types=("stock", "index")),
    ))

    def call(code):
        identity = StockIdentity.from_code(code, default_index_registry())
        scope = StockScope(expected_stock_code=identity.stock_code, allowed_stock_codes={identity.stock_code},
                           strict=True, identities=(identity,))
        result = ToolSurface(registry).execute_tool("probe", {"stock_code": code}, execution.ToolAccessContext(stock_scope=scope))
        assert result["ok"]
        return json.loads(result["result_text"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(call, ["000001", "000001.SH"]))
    assert results == [{"canonical": "sz000001", "type": "stock", "code": "000001"},
                       {"canonical": "sh000001", "type": "index", "code": "sh000001"}]


@pytest.mark.parametrize("tool_name", ["get_daily_history", "analyze_trend", "calculate_ma", "get_volume_analysis", "analyze_pattern"])
def test_convergence_analysis_family_reads_only_bound_index_cache(db, chat_stock_index, monkeypatch, tool_name):
    from datetime import date, timedelta
    import pandas as pd
    from src.agent.factory import get_tool_registry
    from src.agent.stock_scope import StockIdentity, StockScope
    from src.agent.tools import execution
    from src.services import history_loader
    from src.services.stock_list_parser import default_index_registry

    target_date = date(2026, 10, 6)
    for code, base in [("000001", 100), ("sh000001", 300)]:
        db.save_daily_data(pd.DataFrame([
            {"date": target_date - timedelta(days=i), "close": base + i, "open": base + i,
             "high": base + i + 1, "low": base + i - 1, "volume": 1000 + i,
             "ma5": base + i, "ma10": base + i, "ma20": base + i}
            for i in range(90)
        ]), code, "fixture")
    reads = []
    original = db.get_data_range

    def observed(code, *args, **kwargs):
        reads.append(code)
        return original(code, *args, **kwargs)

    monkeypatch.setattr(db, "get_data_range", observed)
    monkeypatch.setattr(history_loader, "_get_fetcher_manager", lambda: pytest.fail("fresh complete cache"))
    identity = StockIdentity.from_code("sh000001", default_index_registry())
    scope = StockScope(expected_stock_code="sh000001", allowed_stock_codes={"sh000001"}, strict=True, identities=(identity,))
    frozen = history_loader.set_frozen_target_date(target_date)
    try:
        result = execution.execute_runner_tool_call(
            tool_call=SimpleNamespace(name=tool_name, arguments={"stock_code": "000001.SH"}),
            tool_registry=get_tool_registry(), stock_scope=scope,
        )
    finally:
        history_loader.reset_frozen_target_date(frozen)
    assert result[5] is None and result[2] is True
    assert "error" not in json.loads(result[1])
    assert reads and set(reads) == {"sh000001"}


def test_convergence_saved_data_tools_read_distinct_real_sqlite_keys(db, chat_stock_index, monkeypatch):
    from datetime import date
    import pandas as pd
    from src.agent.factory import get_tool_registry
    from src.agent.stock_scope import StockIdentity, StockScope
    from src.agent.tools import execution, backtest_tools
    from src.services.stock_list_parser import default_index_registry
    from src.services.backtest_service import BacktestService
    from src.storage import AnalysisHistory, BacktestResult, BacktestSummary

    for code, price in [("000001", 111), ("sh000001", 333)]:
        db.save_daily_data(pd.DataFrame([{"date": date(2026, 10, 6), "close": price}]), code, "fixture")
    with db.get_session() as session:
        for code, wins in [("000001", 11), ("sh000001", 77)]:
            session.add(BacktestSummary(scope="stock", code=code, eval_window_days=30,
                                        engine_version=Config.get_instance().backtest_engine_version,
                                        win_rate_pct=wins, total_evaluations=100, completed_count=100))
        source = AnalysisHistory(code="000001", name="SYNTHETIC CN source", report_type="simple")
        session.add(source)
        session.flush()
        session.add(BacktestResult(analysis_history_id=source.id, code="000001", analysis_date=date(2026, 10, 6),
                                  eval_window_days=30, engine_version=Config.get_instance().backtest_engine_version,
                                  eval_status="completed", stock_return_pct=11))
        session.commit()
    monkeypatch.setattr(backtest_tools, "_get_backtest_service", lambda: BacktestService(db))
    assert BacktestService(db).get_summary(scope="stock", code="000001", eval_window_days=30)["win_rate_pct"] == 11
    registry = get_tool_registry()
    for code, price in [("000001", 111), ("sh000001", 333)]:
        identity = StockIdentity.from_code(code, default_index_registry())
        scope = StockScope(expected_stock_code=code, allowed_stock_codes={code}, strict=True, identities=(identity,))
        result = execution.execute_runner_tool_call(
            tool_call=SimpleNamespace(name="get_analysis_context", arguments={"stock_code": code}),
            tool_registry=registry, stock_scope=scope,
        )
        assert result[5] is None and result[2] is True
        assert json.loads(result[1])["today"]["close"] == price
        backtest = execution.execute_runner_tool_call(
            tool_call=SimpleNamespace(name="get_stock_backtest_summary", arguments={"stock_code": code}),
            tool_registry=registry, stock_scope=scope,
        )
        if code == "000001":
            assert backtest[5] is None and backtest[2] is True
            assert json.loads(backtest[1])["summary"]["win_rate_pct"] == 11
        else:
            assert backtest[5]["error"] == "stock_tool_unsupported"


@pytest.mark.parametrize("arch", ["single", "multi"])
@pytest.mark.parametrize("prior", [None, "600519", "300750", "000001"])
@pytest.mark.parametrize("message", ["从600519改看300750", "把600519换成300750"])
def test_direction_destination_is_stable_in_real_prepare_and_execution(action_chat_api, db, arch, prior, message):
    from src.agent.factory import build_agent_chat_executor
    from src.services.agent_chat_session_service import AgentChatSessionService

    _client, requests, calls, config = action_chat_api
    config.agent_arch = arch
    service = AgentChatSessionService(db)
    sid = "direction-prepare"
    if prior:
        service.commit_user_turn(service.prepare_session_turn(config, sid, f"分析{prior}", []))
    executor = build_agent_chat_executor(config, skills=[])
    for _ in range(2):
        before = db.read_chat_session_snapshot(sid)
        resolved = service.prepare_session_turn(config, sid, message, [], context={
            "stock_code": "600519", "canonical_id": "sh600519", "asset_type": "stock",
            "previous_analysis_summary": "old-summary-sentinel",
            "previous_strategy": "old-strategy-sentinel", "previous_price": 987654.25,
        })
        assert resolved.clarification is None
        assert not any(key in resolved.effective_context for key in
                       ("previous_analysis_summary", "previous_strategy", "previous_price"))
        turn = executor.prepare_turn(message=message, session_id=sid, resolved_turn=resolved, session_service=service)
        accepted = turn.accepted_snapshot
        scope = turn.prepared.stock_scope if arch == "single" else turn.context.meta["stock_scope"]
        assert scope.allowed_stock_codes == {"300750"}
        assert [(item.canonical_id, item.asset_type) for item in scope.identities] == [("sz300750", "stock")]
        assert accepted["active_stock_context"]["stock_code"] == "300750"
        assert accepted["active_stock_context"]["source_message_id"] == accepted["user_message_id"]
        assert accepted["session_state_version"] == before["session_state_version"] + 1
        persisted = db.read_chat_session_snapshot(sid)
        assert persisted["active_stock_context"] == accepted["active_stock_context"]
        assert persisted["active_stock_context"]["updated_at"] == persisted["messages"][-1]["created_at"]
        if arch == "single":
            assert not any(sentinel in str(turn.prepared.history_messages) for sentinel in
                           ("old-summary-sentinel", "old-strategy-sentinel", "987654.25"))
        count = len(requests) + len(calls)
        assert executor.execute_turn(turn).success
        assert len(requests) + len(calls) > count  # fixed clarification cannot satisfy this
        if arch == "single":
            assert requests[-1].stock_scope == scope
        else:
            assert turn.context.stock_code == "300750"


@pytest.mark.parametrize("arch", ["single", "multi"])
@pytest.mark.parametrize("stream", [False, True])
def test_direction_repeat_and_aspect_followups_reach_real_chat_api(action_chat_api, db, arch, stream):
    client, requests, calls, config = action_chat_api
    config.agent_arch = arch
    sid = "action-api"
    endpoint = "/api/v1/agent/chat" + ("/stream" if stream else "")

    def send(message):
        response = client.post(endpoint, json={"session_id": sid, "message": message, "skills": []})
        assert response.status_code == 200, response.text
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")] if stream else []
        if stream:
            assert events[0]["type"] == "accepted" and events[-1]["type"] == "done"
        else:
            assert response.json()["success"]
        return events[0] if stream else response.json()

    send("分析600519")
    confirmed = db.read_chat_session_snapshot(sid)["active_stock_context"]
    for message in ("看看近期走势", "分析一下财务状况", "分析风险"):
        count = len(requests) + len(calls)
        payload = send(message)
        assert len(requests) + len(calls) > count
        state = db.read_chat_session_snapshot(sid)
        assert state["active_stock_context"] == confirmed
        assert payload["active_stock_context"]["stock_code"] == "600519"
        if arch == "single":
            assert requests[-1].stock_scope.allowed_stock_codes == {"600519"}
    count = len(requests) + len(calls)
    send("改看未能确认的新对象")
    assert len(requests) + len(calls) == count
    assert db.read_chat_session_snapshot(sid)["active_stock_context"] == confirmed
    for message in ("分析300750", "分析茅台", "从600519改看300750", "从600519改看300750"):
        count = len(requests) + len(calls)
        payload = send(message)
        assert len(requests) + len(calls) > count
        assert payload["active_stock_context"]["stock_code"] == ("600519" if message == "分析茅台" else "300750")
    assert db.read_chat_session_snapshot(sid)["session_state_version"] == 9


@pytest.mark.parametrize("arch", ["single", "multi"])
@pytest.mark.parametrize("message, code, canonical, asset_type, allowed, clarify", [
    ("从600519改看300750或000001", "600519", "sh600519", "stock", {"600519"}, True),
    ("从600519改看300750或未确认对象", "600519", "sh600519", "stock", {"600519"}, True),
    ("从600519改看300750，顺带提到000001", "300750", "sz300750", "stock", {"300750"}, False),
    ("从600519改看300750，比较000001的走势", "300750", "sz300750", "stock", {"300750"}, False),
    ("从茅台改看宁德时代", "300750", "sz300750", "stock", {"300750"}, False),
    ("从宁德时代改看宁德时代", "300750", "sz300750", "stock", {"300750"}, False),
    ("从sh000001改看005930.KS", "005930.KS", "005930.KS", "stock", {"005930.KS"}, False),
    ("从600519改看sh000001", "sh000001", "sh000001", "index", {"sh000001"}, False),
    ("比较600519和宁德时代，是否改看300750", "600519", "sh600519", "stock", {"600519", "300750"}, False),
])
def test_action_relation_does_not_choose_last_or_expand_incidental_scope(
    action_chat_api, db, arch, message, code, canonical, asset_type, allowed, clarify,
):
    from src.agent.factory import build_agent_chat_executor
    from src.services.agent_chat_session_service import AgentChatSessionService

    _client, requests, calls, config = action_chat_api
    config.agent_arch = arch
    service = AgentChatSessionService(db)
    sid = "action-relations"
    before = service.commit_user_turn(service.prepare_session_turn(config, sid, "分析600519", []))
    resolved = service.prepare_session_turn(config, sid, message, [])
    assert bool(resolved.clarification) is clarify
    if clarify:
        accepted = service.commit_user_turn(resolved)
    else:
        executor = build_agent_chat_executor(config, skills=[])
        turn = executor.prepare_turn(message=message, session_id=sid, resolved_turn=resolved, session_service=service)
        scope = turn.prepared.stock_scope if arch == "single" else turn.context.meta["stock_scope"]
        assert scope.allowed_stock_codes == allowed
        accepted = turn.accepted_snapshot
        assert executor.execute_turn(turn).success
        assert requests or calls
    stock = accepted["active_stock_context"]
    assert (stock["stock_code"], stock["canonical_id"], stock["asset_type"]) == (code, canonical, asset_type)
    assert db.read_chat_session_snapshot(sid)["active_stock_context"] == stock
    if clarify or "比较600519" in message:
        assert stock == before["active_stock_context"]
    else:
        assert stock["source_message_id"] == accepted["user_message_id"]


@pytest.mark.parametrize("arch", ["single", "multi"])
@pytest.mark.parametrize("message", ["看看近期走势", "分析一下财务状况", "分析风险", "研究盈利能力"])
def test_aspect_followup_snapshot_preserves_main_scope_source_and_matching_report_hints(
    action_chat_api, db, arch, message,
):
    from src.agent.factory import build_agent_chat_executor
    from src.services.agent_chat_session_service import AgentChatSessionService

    _client, requests, calls, config = action_chat_api
    config.agent_arch = arch
    service = AgentChatSessionService(db)
    before = service.commit_user_turn(service.prepare_session_turn(config, "aspect-prepare", "分析600519", []))
    resolved = service.prepare_session_turn(config, "aspect-prepare", message, [], context={
        "stock_code": "600519", "canonical_id": "sh600519", "asset_type": "stock",
        "previous_analysis_summary": "matching-summary-sentinel",
        "previous_strategy": "matching-strategy-sentinel", "previous_price": 987654.25,
    })
    assert resolved.clarification is None and not resolved.confirm_stock
    executor = build_agent_chat_executor(config, skills=[])
    turn = executor.prepare_turn(message=message, session_id="aspect-prepare", resolved_turn=resolved, session_service=service)
    scope = turn.prepared.stock_scope if arch == "single" else turn.context.meta["stock_scope"]
    assert scope.allowed_stock_codes == {"600519"}
    assert turn.accepted_snapshot["active_stock_context"] == before["active_stock_context"]
    assert turn.accepted_snapshot["session_state_version"] == 2
    if arch == "single":
        for sentinel in ("matching-summary-sentinel", "matching-strategy-sentinel", "987654.25"):
            assert sentinel in str(turn.prepared.history_messages)
    assert executor.execute_turn(turn).success and (requests or calls)


@pytest.mark.parametrize("message, clarify", [
    ("什么是市盈率", False), ("分析股票估值的基本方法", False),
    ("风险呢", True), ("看看近期走势", True),
])
def test_objectless_action_distinguishes_general_knowledge_and_dependent_followup(action_chat_api, message, clarify):
    client, requests, _calls, _config = action_chat_api
    response = client.post("/api/v1/agent/chat", json={"session_id": "objectless", "message": message, "skills": []})
    assert response.status_code == 200
    assert response.json()["active_stock_context"] is None
    assert bool(requests) is not clarify
    if requests:
        assert requests[0].stock_scope.allowed_stock_codes == set()


@pytest.mark.parametrize("history, expected, source_index", [
    (["分析600519", "看看近期走势", "风险呢"], "600519", 0),
    (["分析600519", "分析一下财务状况", "风险呢"], "600519", 0),
    (["分析600519", "不要改看300750，继续分析600519", "风险呢"], "600519", 0),
    (["分析600519", "是否改看300750？", "风险呢"], "600519", 0),
    (["分析600519", "他说“改看300750”", "风险呢"], "600519", 0),
    (["分析600519", "600519，改看宁德时代", "风险呢"], None, None),
    (["分析300750", "300750，改看宁德时代", "风险呢"], "300750", 0),
    (["600519，分析茅台", "风险呢"], None, None),
    (["分析600519", "改看未能确认的新对象", "风险呢"], None, None),
    (["分析600519", "改看未能确认的新对象", "风险呢", "分析300750"], "300750", 3),
    (["分析600519", "改看宁德时代", "看看近期走势", "风险呢"], None, None),
    (["分析600519", "分析宁德时代", "风险呢"], None, None),
    (["分析宁德时代", "风险呢"], None, None),
    (["分析600519", "改看宁德时代", "分析一下财务状况", "分析300750"], "300750", 3),
    (["分析600519", "从600519改看300750", "从600519改看300750", "风险呢"], "300750", 2),
    (["分析300750", "把600519换成300750", "风险呢"], "300750", 1),
    (["从600519改看300750", "风险呢"], "300750", 0),
    (["分析sh000001", "从sh000001改看005930.KS", "风险呢"], "005930.KS", 1),
    (["分析600519", "从600519改看300750或000001", "风险呢"], None, None),
    (["分析600519", "比较600519和宁德时代", "风险呢"], "600519", 0),
    (["比较600519和300750", "风险呢"], None, None),
])
def test_action_legacy_recovery_real_get_is_read_only_and_next_accept_is_atomic(
    action_chat_api, db, history, expected, source_index,
):
    client, requests, _calls, _config = action_chat_api
    sid = "action-legacy"
    ids = [db.save_conversation_user_turn(sid, message, []) for message in history]
    db.ensure_chat_session_generation(sid)
    before = db.read_chat_session_snapshot(sid)
    response = client.get(f"/api/v1/agent/chat/sessions/{sid}?limit=1")
    assert response.status_code == 200
    detail = response.json()
    assert (detail["active_stock_context"] or {}).get("stock_code") == expected
    assert detail["session_state_version"] == 0
    assert db.read_chat_session_snapshot(sid) == before
    response = client.post("/api/v1/agent/chat", json={"session_id": sid, "message": "风险呢", "skills": []})
    assert response.status_code == 200
    state = db.read_chat_session_snapshot(sid)
    assert state["session_state_version"] == 1
    assert (state["active_stock_context"] or {}).get("stock_code") == expected
    if expected:
        assert len(requests) == 1
        assert state["active_stock_context"]["source_message_id"] == ids[source_index]
        assert state["active_stock_context"]["updated_at"] == before["messages"][source_index]["created_at"]
    else:
        assert requests == []


@pytest.mark.parametrize("history, expected", [
    (["分析600519", "风险呢"], "600519"),
    (["分析600519", "改看宁德时代", "风险呢"], None),
    (["分析600519", "改看不认识的公司", "风险呢"], None),
    (["分析600519", "改看宁德时代", "和000001比较", "风险呢"], None),
    (["分析600519", "改看宁德时代", "分析300750", "风险呢"], "300750"),
    (["分析600519", "分析风险", "看看风险", "分析一下这只股票的风险", "和宁德时代比较"], "600519"),
    (["比较600519和300750", "风险呢"], None),
    (["分析sh000001", "风险呢"], "sh000001"),
])
def test_legacy_recovery_invalidates_unconfirmed_switch_without_name_fact(db, chat_stock_index, history, expected):
    from src.services.agent_chat_session_service import AgentChatSessionService

    for message in history:
        db.save_conversation_user_turn("legacy-replay", message, None)
    db.ensure_chat_session_generation("legacy-replay")
    service = AgentChatSessionService(db)
    detail = service.get_session_detail("legacy-replay", limit=1)
    assert (detail.active_stock_context or {}).get("stock_code") == expected
    assert len(detail.messages) == 1  # restoration must use the complete history, not this limit
    assert db.read_chat_session_snapshot("legacy-replay")["active_stock_context"] is None
    assert db.read_chat_session_snapshot("legacy-replay")["session_state_version"] == 0


def _resolve(service, session_id, message, skills=None, **kwargs):
    return service.prepare_session_turn(SimpleNamespace(agent_skills=["technical"]), session_id, message,
                                        skills, **kwargs)


def test_service_accepts_unique_names_but_not_client_hints_and_preserves_followup_source(db, chat_stock_index):
    from src.services.agent_chat_session_service import AgentChatSessionService

    service = AgentChatSessionService(db)
    hinted = _resolve(service, "service-names", "风险呢", context={"stock_code": "600519"})
    assert hinted.active_stock_context is None and hinted.clarification
    accepted_hint = service.commit_user_turn(hinted)
    assert accepted_hint["active_stock_context"] is None
    named = _resolve(service, "service-names", "分析贵州茅台", [])
    assert named.active_stock_context["canonical_id"] == "sh600519"
    assert named.active_stock_context["stock_name"] == "贵州茅台"
    accepted = service.commit_user_turn(named)
    maintained = _resolve(service, "service-names", "风险呢", context={
        "stock_code": "300750", "stock_name": "宁德时代", "previous_price": 99,
        "previous_analysis_summary": "wrong object", "report_language": "en",
    })
    assert maintained.active_stock_context == accepted["active_stock_context"]
    assert maintained.skill_selection.effective_skill_ids == []
    assert maintained.effective_context["stock_code"] == "600519"
    assert maintained.effective_context["report_language"] == "en"
    assert "previous_price" not in maintained.effective_context
    again = service.commit_user_turn(maintained)
    assert again["active_stock_context"]["source_message_id"] == accepted["user_message_id"]
    assert again["active_stock_context"]["updated_at"] == accepted["active_stock_context"]["updated_at"]
    assert len(db.get_conversation_messages("service-names")) == 3


def test_service_name_ambiguity_conflicting_hint_and_explicit_code_priority(db, chat_stock_index):
    from src.services.agent_chat_session_service import AgentChatSessionService

    service = AgentChatSessionService(db)
    ambiguous = _resolve(service, "names-ambiguous", "分析中芯国际")
    assert ambiguous.active_stock_context is None and ambiguous.clarification
    conflict = _resolve(service, "names-ambiguous", "分析宁德时代", context={"stock_code": "600519"})
    assert conflict.active_stock_context is None and conflict.clarification
    explicit = _resolve(service, "names-ambiguous", "分析688981中芯国际", context={"stock_code": "600519"})
    assert explicit.clarification is None
    assert explicit.active_stock_context["canonical_id"] == "sh688981"


def test_service_compare_does_not_select_or_switch_main_object(db, chat_stock_index):
    from src.services.agent_chat_session_service import AgentChatSessionService

    service = AgentChatSessionService(db)
    first = _resolve(service, "service-compare", "比较600519和300750")
    assert first.active_stock_context is None and first.clarification is None
    assert first.stock_scope.allowed_stock_codes == {"600519", "300750"}
    assert first.stock_scope.strict and not first.effective_context.get("stock_code")
    service.commit_user_turn(first)
    service.commit_user_turn(_resolve(service, "service-compare", "分析600519"))
    compare = _resolve(service, "service-compare", "和宁德时代比较")
    assert compare.active_stock_context["stock_code"] == "600519"
    assert compare.stock_scope.allowed_stock_codes == {"600519", "300750"}
    service.commit_user_turn(compare)
    assert service.get_session_detail("service-compare", 100).active_stock_context["stock_code"] == "600519"


def test_service_detail_invalidates_bypass_without_writing_then_accepts_null_or_reconfirmation(db, chat_stock_index):
    from src.services.agent_chat_session_service import AgentChatSessionService

    service = AgentChatSessionService(db)
    old = service.commit_user_turn(_resolve(service, "service-bypass", "分析600519", []))
    db.save_conversation_user_turn("service-bypass", "old backend followup", None)
    detail = service.get_session_detail("service-bypass", 1)
    assert detail.active_stock_context is None
    assert detail.session_state_version == old["session_state_version"]
    assert db.read_chat_session_snapshot("service-bypass")["active_stock_context"] == old["active_stock_context"]
    next_turn = _resolve(service, "service-bypass", "风险呢")
    assert next_turn.clarification and next_turn.active_stock_context is None
    cleared = service.commit_user_turn(next_turn)
    assert cleared["active_stock_context"] is None and cleared["selected_skill_ids"] == []
    confirmed = service.commit_user_turn(_resolve(service, "service-bypass", "分析宁德时代"))
    assert confirmed["active_stock_context"]["stock_code"] == "300750"


def test_service_legacy_restoration_commits_real_source_not_current_followup(db, chat_stock_index):
    from src.services.agent_chat_session_service import AgentChatSessionService

    source = db.save_conversation_user_turn("legacy-source", "分析sh000001", [])
    db.ensure_chat_session_generation("legacy-source")
    service = AgentChatSessionService(db)
    restored = _resolve(service, "legacy-source", "风险呢")
    assert restored.active_stock_context["source_message_id"] == source
    accepted = service.commit_user_turn(restored)
    assert accepted["active_stock_context"]["source_message_id"] != accepted["user_message_id"]
    assert accepted["active_stock_context"]["asset_type"] == "index"


def test_real_factory_prepare_acceptance_and_late_result_keep_turn_scope(db, chat_stock_index, monkeypatch):
    from src.agent.agent_backend import AgentRunResult, LiteLLMAgentBackend
    from src.agent.factory import build_agent_chat_executor
    from src.services.agent_chat_session_service import AgentChatSessionService

    requests = []

    def controlled_backend(_self, request):
        requests.append(request)
        return AgentRunResult(success=True, final_answer="controlled answer", backend="litellm",
                              model="fixture", messages=[])

    monkeypatch.setattr(LiteLLMAgentBackend, "run", controlled_backend)
    config = Config.get_instance()
    config.agent_backend = "litellm"
    config.agent_arch = "single"
    config.agent_skills = ["ma_golden_cross"]
    config.agent_context_compression_enabled = False
    service = AgentChatSessionService(db)
    resolved = service.prepare_session_turn(config, "factory-accepted", "分析600519", [])
    executor = build_agent_chat_executor(config, skills=resolved.skill_selection.effective_skill_ids)
    turn = executor.prepare_turn(message=resolved.message, session_id="factory-accepted",
                                 resolved_turn=resolved, session_service=service)
    assert turn.accepted_snapshot["active_stock_context"]["canonical_id"] == "sh600519"
    assert turn.prepared.stock_scope.strict
    assert [message["content"] for message in db.get_conversation_messages("factory-accepted")] == ["分析600519"]
    # Later accepted B cannot change A's prepared scope or A's late terminal fact.
    second = service.commit_user_turn(service.prepare_session_turn(config, "factory-accepted", "改看宁德时代"))
    result = executor.execute_turn(turn)
    assert result.success
    assert requests[0].stock_scope.identities[0].canonical_id == "sh600519"
    assert db.read_chat_session_snapshot("factory-accepted")["active_stock_context"] == second["active_stock_context"]
    assert len(db.get_conversation_messages("factory-accepted")) == 3


def test_real_prepare_rejects_aba_before_acceptance_and_drops_deleted_late_terminal(db, chat_stock_index, monkeypatch):
    from src.agent import chat_context
    from src.agent.agent_backend import AgentRunResult, LiteLLMAgentBackend
    from src.agent.factory import build_agent_chat_executor
    from src.services.agent_chat_session_service import AgentChatSessionService

    config = Config.get_instance()
    config.agent_backend = "litellm"
    config.agent_arch = "single"
    config.agent_context_compression_enabled = False
    service = AgentChatSessionService(db)
    service.commit_user_turn(service.prepare_session_turn(config, "prepare-aba", "分析600519", []))
    old = service.prepare_session_turn(config, "prepare-aba", "风险呢")
    executor = build_agent_chat_executor(config, skills=[])
    original = chat_context.estimate_messages_tokens

    def changed_during_token_estimation(*args, **kwargs):
        service.commit_user_turn(service.prepare_session_turn(config, "prepare-aba", "改看300750"))
        service.commit_user_turn(service.prepare_session_turn(config, "prepare-aba", "改看600519"))
        return 0

    monkeypatch.setattr(chat_context, "estimate_messages_tokens", changed_during_token_estimation)
    with pytest.raises(ChatSessionStateConflict):
        executor.prepare_turn(message=old.message, session_id="prepare-aba", resolved_turn=old, session_service=service)
    assert [message["content"] for message in db.get_conversation_messages("prepare-aba")] == ["分析600519", "改看300750", "改看600519"]
    monkeypatch.setattr(chat_context, "estimate_messages_tokens", original)
    prepared = service.prepare_session_turn(config, "prepare-aba", "风险呢")
    turn = executor.prepare_turn(message=prepared.message, session_id="prepare-aba", resolved_turn=prepared, session_service=service)
    db.delete_conversation_session("prepare-aba")
    service.commit_user_turn(service.prepare_session_turn(config, "prepare-aba", "分析300750"))
    monkeypatch.setattr(LiteLLMAgentBackend, "run", lambda _self, _request: AgentRunResult(
        success=True, final_answer="old late answer", backend="litellm", messages=[],
    ))
    executor.execute_turn(turn)
    assert [message["content"] for message in db.get_conversation_messages("prepare-aba")] == ["分析300750"]
    assert db.get_agent_provider_turns("prepare-aba") == []


@pytest.mark.parametrize("token", ["510300", "159915", "005930.KS"])
def test_existing_code_tokens_are_not_lost_before_parser(token):
    # Existing defect reproduction, unlike tests for not-yet-implemented schema.
    assert extract_stock_codes(f"分析{token}", IndexRegistry([])) == [token]


@pytest.mark.parametrize("prior, message, main, allowed", [
    (None, "比较600519和300750", "", {"600519", "300750"}),
    (None, "什么是止损策略", "", set()),
    ("分析600519", "和300750比较", "600519", {"600519", "300750"}),
])
def test_real_multi_factory_prepare_consumes_resolved_null_and_scope(
    db, chat_stock_index, monkeypatch, prior, message, main, allowed,
):
    from src.agent.factory import build_agent_chat_executor
    from src.agent.llm_adapter import LLMResponse, LLMToolAdapter
    from src.services.agent_chat_session_service import AgentChatSessionService

    calls = []

    def controlled_model(_self, messages, *_args, **_kwargs):
        calls.append(messages)
        return LLMResponse(content='{"signal":"hold","confidence":0.5,"reasoning":"fixture"}',
                           model="fixture", provider="fixture")

    monkeypatch.setattr(LLMToolAdapter, "call_with_tools", controlled_model)
    config = Config.get_instance()
    config.agent_backend = "litellm"
    config.agent_arch = "multi"
    config.agent_orchestrator_mode = "quick"
    config.agent_context_compression_enabled = False
    config.agent_memory_enabled = False
    service = AgentChatSessionService(db)
    if prior:
        service.commit_user_turn(service.prepare_session_turn(config, "multi-scope", prior, []))
    resolved = service.prepare_session_turn(config, "multi-scope", message, [])
    executor = build_agent_chat_executor(config, skills=[])
    turn = executor.prepare_turn(message=message, session_id="multi-scope",
                                 resolved_turn=resolved, session_service=service)
    assert turn.context.stock_code == main
    assert turn.context.meta["stock_scope"].strict
    assert turn.context.meta["stock_scope"].allowed_stock_codes == allowed
    assert (turn.accepted_snapshot["active_stock_context"] or {}).get("stock_code", "") == main
    assert calls == []  # acceptance must precede actual analysis calls
    result = executor.execute_turn(turn)
    assert result.success and calls
    assert turn.context.stock_code == main  # no stage promotes an allowed object to main
    if not main:
        assert any(message in row["content"] for rows in calls for row in rows)
    assert len([row for row in db.get_conversation_messages("multi-scope") if row["role"] == "user"]) == (2 if prior else 1)


def test_multi_conditional_terminal_does_not_write_into_rebuilt_session(db, chat_stock_index, monkeypatch):
    from src.agent.factory import build_agent_chat_executor
    from src.agent.llm_adapter import LLMResponse, LLMToolAdapter
    from src.services.agent_chat_session_service import AgentChatSessionService

    config = Config.get_instance()
    config.agent_backend = "litellm"
    config.agent_arch = "multi"
    config.agent_orchestrator_mode = "quick"
    config.agent_context_compression_enabled = False
    config.agent_memory_enabled = False
    service = AgentChatSessionService(db)
    resolved = service.prepare_session_turn(config, "multi-late", "分析600519", [])
    executor = build_agent_chat_executor(config, skills=[])
    turn = executor.prepare_turn(message=resolved.message, session_id="multi-late",
                                 resolved_turn=resolved, session_service=service)
    db.delete_conversation_session("multi-late")
    service.commit_user_turn(service.prepare_session_turn(config, "multi-late", "分析300750", []))
    monkeypatch.setattr(LLMToolAdapter, "call_with_tools", lambda *_a, **_k: LLMResponse(
        content='{"signal":"hold","confidence":0.5,"reasoning":"late"}', model="fixture", provider="fixture",
    ))
    assert executor.execute_turn(turn).success
    assert [row["content"] for row in db.get_conversation_messages("multi-late")] == ["分析300750"]


@pytest.fixture
def actual_chat_api(db, chat_stock_index, monkeypatch, tmp_path):
    from api.app import create_app
    from api.v1.endpoints import agent
    from fastapi.testclient import TestClient
    from src.agent.agent_backend import AgentRunResult, LiteLLMAgentBackend

    requests = []
    config = Config.get_instance()
    config.agent_backend = "litellm"
    config.agent_arch = "single"
    config.agent_skills = ["ma_golden_cross"]
    config.agent_context_compression_enabled = False
    monkeypatch.setattr(config, "is_agent_available", lambda: True)
    monkeypatch.setattr(agent, "get_config", lambda: config)
    monkeypatch.setattr("api.middlewares.auth.is_auth_enabled", lambda: False)

    def controlled_backend(_self, request):
        requests.append(request)
        return AgentRunResult(success=True, final_answer="controlled API answer", backend="litellm",
                              model="fixture", messages=[])

    monkeypatch.setattr(LiteLLMAgentBackend, "run", controlled_backend)
    return TestClient(create_app(static_dir=tmp_path / "static")), requests, config


@pytest.mark.parametrize("stream", [False, True])
def test_actual_chat_api_explicit_empty_skills_uses_builtin_not_config_default(actual_chat_api, db, stream):
    from src.agent.factory import resolve_skill_prompt_state

    client, requests, config = actual_chat_api
    response = client.post("/api/v1/agent/chat" + ("/stream" if stream else ""), json={
        "session_id": "api-empty-skill", "message": "分析600519", "skills": [],
    })
    assert response.status_code == 200
    assert len(requests) == 1
    builtin = resolve_skill_prompt_state(config, skills=[])
    assert builtin.skill_instructions in requests[0].system_prompt
    configured = resolve_skill_prompt_state(config, skills=["ma_golden_cross"])
    assert configured.skills_to_activate == ["ma_golden_cross"]
    assert configured.skill_instructions not in requests[0].system_prompt
    assert db.get_conversation_session_selected_skill_ids("api-empty-skill") == []
    assert len([row for row in db.get_conversation_messages("api-empty-skill") if row["role"] == "user"]) == 1


@pytest.mark.parametrize("stream", [False, True])
def test_actual_chat_api_state_payload_matches_detail_and_hides_private_sources(actual_chat_api, db, stream):
    client, requests, _config = actual_chat_api
    response = client.post("/api/v1/agent/chat" + ("/stream" if stream else ""), json={
        "session_id": "api-state", "message": "分析宁德时代", "skills": [],
    })
    assert response.status_code == 200
    payload = response.json() if not stream else next(
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    )
    detail = client.get("/api/v1/agent/chat/sessions/api-state").json()
    for key in ("active_stock_context", "session_generation", "session_state_version", "session_state"):
        assert payload[key] == detail[key]
    assert payload["active_stock_context"] == {
        "stock_code": "300750", "canonical_id": "sz300750", "asset_type": "stock", "stock_name": "宁德时代",
    }
    assert payload["session_state_version"] == 1
    assert len(requests) == 1
    assert "source_message_id" not in response.text and "updated_at" not in response.text


@pytest.mark.parametrize("stream", [False, True])
def test_actual_chat_api_clarification_accepts_without_analysis_or_compression(actual_chat_api, db, monkeypatch, stream):
    from src.agent import chat_context
    from src.agent.agent_backend import LiteLLMAgentBackend

    client, requests, config = actual_chat_api
    config.agent_context_compression_enabled = True
    config.agent_context_compression_trigger_tokens = 1
    def forbidden(*_args, **_kwargs):
        pytest.fail("fixed clarification entered analysis preparation or a model")
    monkeypatch.setattr(chat_context, "_generate_summary", forbidden)
    monkeypatch.setattr(LiteLLMAgentBackend, "run", forbidden)
    monkeypatch.setattr("api.v1.endpoints.agent._build_executor", forbidden)
    response = client.post("/api/v1/agent/chat" + ("/stream" if stream else ""), json={
        "session_id": "api-clarify", "message": "风险呢", "skills": [],
        "context": {"stock_code": "600519"},
    })
    assert response.status_code == 200
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert [event["type"] for event in events] == ["accepted", "done"]
        assert events[-1]["total_steps"] == 0
    assert requests == []
    snapshot = db.read_chat_session_snapshot("api-clarify")
    assert snapshot["session_state_version"] == 1 and snapshot["active_stock_context"] is None
    assert snapshot["selected_skill_ids"] == []
    assert [row["role"] for row in snapshot["messages"]] == ["user", "assistant"]


@pytest.mark.parametrize("stream", [False, True])
def test_actual_chat_api_stale_generation_conflict_before_acceptance(actual_chat_api, db, stream):
    client, requests, _config = actual_chat_api
    generation = db.ensure_chat_session_generation("api-conflict")
    db.delete_conversation_session("api-conflict")
    response = client.post("/api/v1/agent/chat" + ("/stream" if stream else ""), json={
        "session_id": "api-conflict", "message": "分析600519", "skills": [], "session_generation": generation,
    })
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert [event["type"] for event in events] == ["error"]
        assert events[0]["error_code"] == "session_state_conflict"
    else:
        assert response.status_code == 409
        assert response.json()["error"] == "session_state_conflict"
    assert requests == []
    snapshot = db.read_chat_session_snapshot("api-conflict")
    assert snapshot["messages"] == [] and snapshot["session_generation"] is None


@pytest.mark.parametrize("stream", [False, True])
def test_actual_chat_api_prepare_aba_conflict_has_no_partial_acceptance(actual_chat_api, db, monkeypatch, stream):
    from src.agent import chat_context
    from src.services.agent_chat_session_service import AgentChatSessionService

    client, requests, config = actual_chat_api
    service = AgentChatSessionService(db)
    service.commit_user_turn(service.prepare_session_turn(config, "api-aba", "分析600519", ["ma_golden_cross"]))
    original = db.read_chat_session_snapshot("api-aba")
    def interleave(*_args, **_kwargs):
        service.commit_user_turn(service.prepare_session_turn(config, "api-aba", "改看300750"))
        service.commit_user_turn(service.prepare_session_turn(config, "api-aba", "改看600519"))
        return 0
    monkeypatch.setattr(chat_context, "estimate_messages_tokens", interleave)
    response = client.post("/api/v1/agent/chat" + ("/stream" if stream else ""), json={
        "session_id": "api-aba", "message": "风险呢", "skills": [],
        "session_generation": original["session_generation"], "request_id": "api-aba-request",
    })
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert [event["type"] for event in events] == ["error"]
        assert events[0]["error_code"] == "session_state_conflict"
        assert events[0]["request_id"] == "api-aba-request" and events[0]["session_id"] == "api-aba"
    else:
        assert response.status_code == 409 and response.json()["error"] == "session_state_conflict"
    current = db.read_chat_session_snapshot("api-aba")
    assert requests == []
    assert current["session_state_version"] == 3 and current["selected_skill_ids"] == ["ma_golden_cross"]
    assert [row["content"] for row in current["messages"]] == ["分析600519", "改看300750", "改看600519"]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure_stage", ["prepare", "transaction"])
def test_actual_chat_api_prepare_or_insert_failure_cannot_partially_accept(
    actual_chat_api, db, monkeypatch, stream, failure_stage,
):
    from src.agent import chat_context
    from src.services.agent_chat_session_service import AgentChatSessionService

    client, requests, config = actual_chat_api
    service = AgentChatSessionService(db)
    service.commit_user_turn(service.prepare_session_turn(config, "api-failure", "分析600519", ["ma_golden_cross"]))
    before = db.read_chat_session_snapshot("api-failure")
    injected = []

    def prepare_failure(*_args, **_kwargs):
        injected.append("prepare")
        raise RuntimeError("controlled preparation failure")

    def insert_failure(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO conversation_messages"):
            injected.append("transaction")
            raise RuntimeError("controlled message insert failure")

    if failure_stage == "prepare":
        # Fail one preparation dependency, not the real factory/prepare itself.
        monkeypatch.setattr(chat_context, "estimate_messages_tokens", prepare_failure)
    else:
        event.listen(db._engine, "before_cursor_execute", insert_failure)
    try:
        response = client.post("/api/v1/agent/chat" + ("/stream" if stream else ""), json={
            "session_id": "api-failure", "message": "改看宁德时代", "skills": [],
            "session_generation": before["session_generation"],
        })
    finally:
        if failure_stage == "transaction":
            event.remove(db._engine, "before_cursor_execute", insert_failure)
    assert injected == [failure_stage] and requests == []
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert [item["type"] for item in events] == ["error"]
        assert events[0]["error_code"] == "request_not_accepted"
        assert "controlled preparation failure" not in response.text
        assert "controlled message insert failure" not in response.text
    else:
        # Non-conflict HTTP failures retain the existing API error contract.
        assert response.status_code == 500
    assert db.read_chat_session_snapshot("api-failure") == before


@pytest.mark.parametrize("stream", [False, True])
def test_actual_chat_api_auth_runs_before_clarification_and_identity(actual_chat_api, db, monkeypatch, stream):
    client, requests, _config = actual_chat_api
    monkeypatch.setattr("api.middlewares.auth.is_auth_enabled", lambda: True)
    response = client.post("/api/v1/agent/chat" + ("/stream" if stream else ""), json={
        "session_id": "no-auth", "message": "风险呢", "skills": [],
    })
    assert response.status_code == 401 and requests == []
    snapshot = db.read_chat_session_snapshot("no-auth")
    assert snapshot["session_generation"] is None and snapshot["messages"] == []


@pytest.mark.parametrize("stream, arch", [(False, "single"), (True, "multi")])
def test_actual_chat_api_clarification_preserves_codex_unsupported_boundary(actual_chat_api, db, stream, arch):
    client, requests, config = actual_chat_api
    config.agent_backend = "codex_app_server"
    config.agent_arch = arch
    response = client.post("/api/v1/agent/chat" + ("/stream" if stream else ""), json={
        "session_id": "unsupported-clarify", "message": "风险呢", "skills": [],
    })
    assert response.status_code == 400 and requests == []
    assert response.json()["error"] == ("unsupported_agent_arch" if arch == "multi" else "capability_unsupported")
    snapshot = db.read_chat_session_snapshot("unsupported-clarify")
    assert snapshot["session_generation"] is None and snapshot["messages"] == []


@pytest.mark.parametrize("stream", [False, True])
def test_actual_multi_api_general_question_keeps_null_and_real_guard_denies_guessed_stock(
    actual_chat_api, db, monkeypatch, stream,
):
    from src.agent.llm_adapter import LLMResponse, LLMToolAdapter, ToolCall

    client, requests, config = actual_chat_api
    config.agent_arch = "multi"
    config.agent_orchestrator_mode = "quick"
    config.agent_memory_enabled = False
    messages_seen = []
    def model_endpoint(_self, messages, *_args, **_kwargs):
        messages_seen.append([dict(row) for row in messages])
        if len(messages_seen) == 1:
            return LLMResponse(tool_calls=[ToolCall(id="guess", name="get_daily_history", arguments={"stock_code": "600519"})],
                               model="fixture", provider="fixture")
        return LLMResponse(content='{"signal":"hold","confidence":0.5,"reasoning":"general answer"}',
                           model="fixture", provider="fixture")
    monkeypatch.setattr(LLMToolAdapter, "call_with_tools", model_endpoint)
    response = client.post("/api/v1/agent/chat" + ("/stream" if stream else ""), json={
        "session_id": "multi-api-general", "message": "什么是止损策略", "skills": [],
    })
    assert response.status_code == 200 and messages_seen and requests == []
    payload = response.json() if not stream else json.loads(response.text.splitlines()[0][6:])
    assert payload["active_stock_context"] is None and payload["session_state_version"] == 1
    assert any("stock_scope_violation" in row.get("content", "")
               for rows in messages_seen for row in rows if row["role"] == "tool")
    current = db.read_chat_session_snapshot("multi-api-general")
    assert current["active_stock_context"] is None
    assert [row["role"] for row in current["messages"]] == ["user", "assistant"]


@pytest.mark.parametrize("error_code", [None, "backend_failure", "timeout", "cancelled"])
def test_actual_codex_factory_api_consumes_strict_accepted_snapshot_without_real_runtime(
    actual_chat_api, db, monkeypatch, error_code,
):
    from src.agent.agent_backend import AgentRunResult
    from src.agent.codex_agent_backend import CodexAgentBackend

    client, requests, config = actual_chat_api
    config.agent_backend = "codex_app_server"
    calls = []
    def controlled_runtime(_self, request):
        calls.append(request)
        return AgentRunResult(success=error_code is None, final_answer="fixture" if error_code is None else "",
                              backend="codex_app_server", error_code=error_code, error_message=error_code)
    monkeypatch.setattr(CodexAgentBackend, "run", controlled_runtime)
    response = client.post("/api/v1/agent/chat/stream", json={
        "session_id": "codex-api-state", "message": "分析sh000001", "skills": [],
    })
    assert response.status_code == 200 and requests == [] and len(calls) == 1
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert [event["type"] for event in events] == ["accepted", "done"]
    assert events[0]["active_stock_context"]["canonical_id"] == "sh000001"
    assert events[0]["active_stock_context"]["asset_type"] == "index"
    assert events[-1]["success"] is (error_code is None) and events[-1]["error_code"] == error_code
    assert calls[0].stock_scope.strict and calls[0].stock_scope.identities[0].canonical_id == "sh000001"
    current = db.read_chat_session_snapshot("codex-api-state")
    assert current["session_state_version"] == 1 and current["selected_skill_ids"] == []
    assert current["active_stock_context"]["asset_type"] == "index"
    assert [row["role"] for row in current["messages"]] == ["user", "assistant"]


@pytest.mark.parametrize("old_state_table", [False, True, "partial"])
def test_chat_schema_database_default_supports_old_shape_insert(tmp_path, old_state_table):
    path = tmp_path / "upgrade.db"
    if old_state_table:
        with sqlite3.connect(path) as old:
            old.execute(
                "CREATE TABLE conversation_session_states ("
                "session_id VARCHAR(100) PRIMARY KEY, selected_skill_ids_json TEXT NOT NULL, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
            old.execute(
                "INSERT INTO conversation_session_states VALUES (?, ?, ?, ?)",
                ("existing", '["technical"]', "2026-01-01", "2026-01-01"),
            )
            if old_state_table == "partial":
                old.execute("ALTER TABLE conversation_session_states ADD COLUMN active_stock_code VARCHAR(32)")
                old.execute("ALTER TABLE conversation_session_states ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0")
                old.execute("UPDATE conversation_session_states SET active_stock_code='600519'")
    manager = DatabaseManager(db_url=f"sqlite:///{path}")
    columns = {column["name"]: column for column in inspect(manager._engine).get_columns(
        "conversation_session_states"
    )}
    assert str(columns["state_version"]["default"]).strip("'\"") == "0"
    assert columns["state_version"]["nullable"] is False
    # Schema-level rollback evidence: exact old insert shape, no new ORM defaults.
    with manager._engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO conversation_session_states "
            "(session_id, selected_skill_ids_json, created_at, updated_at) "
            "VALUES ('old-new-session', '[]', '2026-01-01', '2026-01-01')"
        ))
    with manager._engine.connect() as connection:
        row = connection.execute(text(
            "SELECT state_version, session_generation FROM conversation_session_states "
            "WHERE session_id='old-new-session'"
        )).one()
        assert row == (0, None)
    DatabaseManager.reset_instance()
    upgraded = DatabaseManager(db_url=f"sqlite:///{path}")
    restored = upgraded.read_chat_session_snapshot("old-new-session")
    assert restored["session_generation"]
    assert restored["selected_skill_ids"] == []
    assert restored["session_state_version"] == 0
    if old_state_table:
        assert upgraded.read_chat_session_snapshot("existing")["selected_skill_ids"] == ["technical"]
        with upgraded._engine.connect() as connection:
            assert connection.execute(text(
                "SELECT created_at, updated_at FROM conversation_session_states WHERE session_id='existing'"
            )).one() == ("2026-01-01", "2026-01-01")
            if old_state_table == "partial":
                assert connection.execute(text(
                    "SELECT active_stock_code, state_version FROM conversation_session_states WHERE session_id='existing'"
                )).one() == ("600519", 0)


def test_chat_schema_failure_does_not_publish_half_initialized_manager_and_can_retry(tmp_path):
    from sqlalchemy.engine import Engine

    path = tmp_path / "interrupted-upgrade.db"
    with sqlite3.connect(path) as old:
        old.execute(
            "CREATE TABLE conversation_session_states ("
            "session_id VARCHAR(100) PRIMARY KEY, selected_skill_ids_json TEXT NOT NULL, "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        )
        old.execute(
            "INSERT INTO conversation_session_states VALUES (?, ?, ?, ?)",
            ("existing", '["technical"]', "2026-01-01", "2026-01-01"),
        )
    attempted = []

    def interrupt_second_chat_column(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("ALTER TABLE conversation_session_states ADD COLUMN"):
            attempted.append(statement)
            if "active_stock_canonical_id" in statement:
                raise RuntimeError("controlled Chat schema migration interruption")

    # Inject only a DDL execution failure: real manager, migrations and SQLite remain under test.
    event.listen(Engine, "before_cursor_execute", interrupt_second_chat_column)
    try:
        with pytest.raises(RuntimeError, match="controlled Chat schema migration interruption"):
            DatabaseManager(db_url=f"sqlite:///{path}")
    finally:
        event.remove(Engine, "before_cursor_execute", interrupt_second_chat_column)
    assert len(attempted) == 2
    assert DatabaseManager._instance is None
    with sqlite3.connect(path) as interrupted:
        columns = {row[1] for row in interrupted.execute("PRAGMA table_info(conversation_session_states)")}
        assert "active_stock_code" in columns and "active_stock_canonical_id" not in columns
        assert interrupted.execute("SELECT * FROM conversation_session_states").fetchone() == (
            "existing", '["technical"]', "2026-01-01", "2026-01-01", None,
        )
    recovered = DatabaseManager(db_url=f"sqlite:///{path}")
    snapshot = recovered.read_chat_session_snapshot("existing")
    assert recovered._initialized and snapshot["session_generation"]
    assert snapshot["selected_skill_ids"] == ["technical"] and snapshot["session_state_version"] == 0
    assert len(inspect(recovered._engine).get_columns("conversation_session_states")) == 13
    with recovered._engine.connect() as connection:
        assert connection.execute(text(
            "SELECT created_at, updated_at FROM conversation_session_states WHERE session_id='existing'"
        )).one() == ("2026-01-01", "2026-01-01")


def _stock(code="600519", canonical="sh600519"):
    return {
        "stock_code": code, "canonical_id": canonical,
        "asset_type": "stock", "stock_name": None,
    }


def _accept(manager, session_id, content, stock=None, skills=None, confirm=False):
    manager.ensure_chat_session_generation(session_id)
    snapshot = manager.read_chat_session_snapshot(session_id)
    return manager.commit_chat_user_turn(
        snapshot, content, selected_skill_ids=skills,
        active_stock_context=stock, confirm_stock=confirm,
    )


def test_chat_acceptance_commits_one_message_skill_and_stock(db):
    accepted = _accept(db, "atomic", "分析600519", _stock(), [], True)
    current = db.read_chat_session_snapshot("atomic")
    assert current["session_state_version"] == accepted["session_state_version"] == 1
    assert current["selected_skill_ids"] == []
    assert len(current["messages"]) == 1
    assert current["active_stock_context"]["canonical_id"] == "sh600519"
    assert current["active_stock_context"]["source_message_id"] == accepted["user_message_id"]
    previous_source = current["active_stock_context"]["updated_at"]
    follow_up = db.commit_chat_user_turn(
        current, "风险呢", active_stock_context=current["active_stock_context"]
    )
    assert follow_up["active_stock_context"]["updated_at"] == previous_source
    assert db.read_chat_session_snapshot("atomic")["selected_skill_ids"] == []


def test_stock_aba_rejects_prepared_old_version_without_partial_write(db):
    _accept(db, "aba", "A", _stock(), ["technical"], True)
    prepared = db.read_chat_session_snapshot("aba")
    _accept(db, "aba", "B", _stock("300750", "sz300750"), None, True)
    _accept(db, "aba", "A", _stock(), None, True)
    with pytest.raises(Exception) as failure:
        db.commit_chat_user_turn(prepared, "stale", selected_skill_ids=[],
                                 active_stock_context=prepared["active_stock_context"])
    assert failure.value.code == "session_state_conflict"
    current = db.read_chat_session_snapshot("aba")
    assert current["session_state_version"] == 3
    assert current["selected_skill_ids"] == ["technical"]
    assert [message["content"] for message in current["messages"]] == ["A", "B", "A"]


def test_delete_recreate_same_version_and_message_anchor_rejects_old_generation(db):
    _accept(db, "reused", "old", _stock(), [], True)
    prepared = db.read_chat_session_snapshot("reused")
    db.delete_conversation_session("reused")
    _accept(db, "reused", "new", _stock("300750", "sz300750"), [], True)
    # Make all non-generation equality checks collide; do not substitute stock ABA.
    old_id, _role, created_at = prepared["latest_user_anchor"]
    with db._engine.begin() as connection:
        connection.execute(text(
            "UPDATE conversation_messages SET created_at=:created WHERE session_id='reused'"
        ), {"created": created_at.replace("T", " ")})
    rebuilt = db.read_chat_session_snapshot("reused")
    assert rebuilt["latest_user_anchor"] == prepared["latest_user_anchor"]
    assert rebuilt["latest_user_anchor"][0] == old_id
    assert rebuilt["session_state_version"] == prepared["session_state_version"]
    assert rebuilt["session_generation"] != prepared["session_generation"]
    with pytest.raises(Exception) as failure:
        db.commit_chat_user_turn(prepared, "late", active_stock_context=prepared["active_stock_context"])
    assert failure.value.code == "session_state_conflict"
    assert [message["content"] for message in db.read_chat_session_snapshot("reused")["messages"]] == ["new"]


def test_two_connections_accept_same_snapshot_only_once(db):
    db.ensure_chat_session_generation("race")
    prepared = db.read_chat_session_snapshot("race")

    def attempt(content):
        try:
            return db.commit_chat_user_turn(prepared, content, active_stock_context=_stock(), confirm_stock=True)
        except Exception as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["first", "second"]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert [getattr(result, "code", None) for result in results].count("session_state_conflict") == 1
    assert len(db.read_chat_session_snapshot("race")["messages"]) == 1


def test_stale_requested_generation_does_not_recreate_session(db):
    generation = db.ensure_chat_session_generation("gone")
    db.delete_conversation_session("gone")
    with pytest.raises(Exception) as failure:
        db.ensure_chat_session_generation("gone", expected_generation=generation)
    assert failure.value.code == "session_state_conflict"
    assert db.read_chat_session_snapshot("gone")["session_generation"] is None


def test_invalid_stock_rolls_back_message_and_skill(db):
    db.ensure_chat_session_generation("invalid")
    snapshot = db.read_chat_session_snapshot("invalid")
    with pytest.raises(ValueError):
        db.commit_chat_user_turn(snapshot, "bad", selected_skill_ids=["technical"],
                                 active_stock_context={"stock_code": "600519"}, confirm_stock=True)
    current = db.read_chat_session_snapshot("invalid")
    assert current["messages"] == []
    assert current["selected_skill_ids"] is None
    assert current["session_state_version"] == 0


def test_state_skill_and_message_sources_share_one_read_snapshot(db):
    _accept(db, "snapshot", "old", _stock(), ["technical"], True)
    before = db.read_chat_session_snapshot("snapshot")
    injected = False

    def commit_between_reads(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal injected
        if not injected and statement.startswith("SELECT") and "FROM conversation_messages" in statement:
            injected = True
            # A separate, actual writer transaction commits after the reader has
            # fetched state but before it reads message sources (SQLite WAL).
            db.commit_chat_user_turn(before, "new", selected_skill_ids=["risk"],
                                     active_stock_context=_stock("300750", "sz300750"), confirm_stock=True)

    event.listen(db._engine, "before_cursor_execute", commit_between_reads)
    try:
        consistent = db.read_chat_session_snapshot("snapshot")
    finally:
        event.remove(db._engine, "before_cursor_execute", commit_between_reads)
    assert injected
    assert consistent["session_state_version"] == 1
    assert consistent["selected_skill_ids"] == ["technical"]
    assert consistent["active_stock_context"]["canonical_id"] == "sh600519"
    assert [message["content"] for message in consistent["messages"]] == ["old"]
    after = db.read_chat_session_snapshot("snapshot")
    assert after["session_state_version"] == 2
    assert after["selected_skill_ids"] == ["risk"]
    assert [message["content"] for message in after["messages"]] == ["old", "new"]


def test_existing_compression_cannot_resurrect_deleted_session(db, monkeypatch):
    from src.agent import chat_context

    db.save_conversation_message("late-summary", "user", "分析600519" * 50)
    config = SimpleNamespace(
        agent_context_compression_enabled=True,
        agent_context_compression_trigger_tokens=1,
        agent_context_protected_turns=0,
    )
    monkeypatch.setattr(chat_context, "estimate_messages_tokens", lambda *_: 1000)
    monkeypatch.setattr(chat_context, "estimate_text_tokens", lambda *_: 1000)

    def delayed_summary(**_kwargs):
        db.delete_conversation_session("late-summary")
        return "late result", SimpleNamespace(usage={})

    monkeypatch.setattr(chat_context, "_generate_summary", delayed_summary)
    try:
        chat_context._build_visible_history_state("late-summary", None, config)
    except ChatSessionStateConflict:
        pass
    assert db.get_conversation_summary("late-summary") is None
    assert db.get_conversation_messages("late-summary") == []


def _write_summary(db, snapshot, covered_id, summary):
    return db.upsert_conversation_summary(
        snapshot["session_id"], summary, covered_id, 1, 10, source_snapshot=snapshot,
    )


def test_summary_coverage_cas_does_not_regress(db):
    _accept(db, "summary-cas", "first", _stock(), None, True)
    _accept(db, "summary-cas", "second", _stock(), None, True)
    prepared = db.read_chat_session_snapshot("summary-cas")
    assert _write_summary(db, prepared, prepared["messages"][-1]["id"], "newer") is True
    assert _write_summary(db, prepared, prepared["messages"][0]["id"], "older") is False
    assert db.get_conversation_summary("summary-cas")["summary"] == "newer"


def test_summary_and_terminal_reject_deleted_recreated_instance(db):
    accepted = _accept(db, "late-all", "old", _stock(), None, True)
    prepared = db.read_chat_session_snapshot("late-all")
    db.delete_conversation_session("late-all")
    _accept(db, "late-all", "new", _stock(), None, True)
    assert _write_summary(db, prepared, prepared["messages"][0]["id"], "old summary") is False
    assert db.save_conversation_message("late-all", "assistant", "old result", accepted_turn=accepted) is None
    assert db.get_conversation_summary("late-all") is None
    assert [message["content"] for message in db.get_conversation_messages("late-all")] == ["new"]


def test_late_trace_is_guarded_in_same_transaction_as_insert_and_prune(db):
    accepted = _accept(db, "late-trace", "old", _stock(), None, True)
    db.delete_conversation_session("late-trace")
    _accept(db, "late-trace", "new", _stock(), None, True)
    assert db.save_agent_provider_turn(
        session_id="late-trace", run_id="old-run", provider="fixture", model="fixture",
        anchor_user_message_id=accepted["user_message_id"], anchor_assistant_message_id=0,
        messages=[], contains_reasoning=True, contains_tool_calls=False,
        contains_thinking_blocks=False, must_roundtrip=True, estimated_tokens=1,
        accepted_turn=accepted,
    ) is None
    assert db.get_agent_provider_turns("late-trace") == []


def test_real_history_compressors_interleave_without_write_lock_or_coverage_regression(db, monkeypatch):
    from src.agent import chat_context

    first = _accept(db, "compress-race", "first", _stock(), None, True)
    config = SimpleNamespace(
        agent_context_compression_enabled=True,
        agent_context_compression_trigger_tokens=1,
        agent_context_protected_turns=0,
    )
    monkeypatch.setattr(chat_context, "estimate_messages_tokens", lambda *_: 1000)
    monkeypatch.setattr(chat_context, "estimate_text_tokens", lambda *_: 1000)
    pending, release = Event(), Event()
    calls = []

    def summary_generator(**kwargs):
        source_ids = [message.id for message in kwargs["to_summarize"]]
        calls.append(source_ids)
        if source_ids == [first["user_message_id"]]:
            pending.set()
            assert release.wait(5), "old compression did not receive its controlled release"
            return "old summary discarded", SimpleNamespace(usage={})
        return "new summary saved", SimpleNamespace(usage={})

    monkeypatch.setattr(chat_context, "_generate_summary", summary_generator)
    with ThreadPoolExecutor(max_workers=2) as pool:
        older = pool.submit(chat_context._build_visible_history_state,
                            "compress-race", None, config, db_manager=db)
        try:
            assert pending.wait(5)
            # A different connection accepts a new turn while summary generation
            # is suspended. This would time out if it held a database write lock.
            writer = pool.submit(_accept, db, "compress-race", "second", _stock(), None, True)
            second = writer.result(timeout=5)
            newer = chat_context._build_visible_history_state(
                "compress-race", None, config, db_manager=db,
            )
        finally:
            release.set()
        older_result = older.result(timeout=5)
    saved = db.get_conversation_summary("compress-race")
    assert saved["covered_message_id"] == second["user_message_id"]
    assert saved["summary"] == "new summary saved"
    assert older_result.messages == newer.messages
    assert "old summary discarded" not in str(older_result.messages)
    assert len(calls) == 2  # no automatic model retry after the failed summary CAS


def test_context_uses_injected_database_and_original_trace_snapshot(db, monkeypatch):
    from src.agent import chat_context

    user_id = db.save_conversation_message("context-db", "user", "question")
    assistant_id = db.save_conversation_message("context-db", "assistant", "answer")
    db.ensure_chat_session_generation("context-db")
    snapshot = db.read_chat_session_snapshot("context-db")
    db.save_agent_provider_turn(
        session_id="context-db", run_id="later", provider="openai", model="openai/test-model",
        anchor_user_message_id=user_id, anchor_assistant_message_id=assistant_id,
        messages=[{"role": "assistant", "reasoning_content": "not in initial snapshot"}],
        contains_reasoning=True, contains_tool_calls=False, contains_thinking_blocks=False,
        must_roundtrip=True, estimated_tokens=1,
    )

    def no_global_database():
        raise AssertionError("injected history must not re-read a global database")

    monkeypatch.setattr(chat_context, "get_db", no_global_database)
    config = SimpleNamespace(
        agent_context_compression_enabled=False, llm_model_list=[],
        agent_litellm_model="openai/test-model", litellm_model="openai/test-model",
        litellm_fallback_models=[],
    )
    bundle = chat_context.build_agent_chat_context_bundle(
        "context-db", None, config, db_manager=db, source_snapshot=snapshot,
    )
    assert bundle.context_messages == [{"role": "user", "content": "question"},
                                       {"role": "assistant", "content": "answer"}]
    assert bundle.diagnostics["trace_injected"] is False


def test_chat_tokens_preserve_identity_until_parser():
    from src.agent.stock_scope import StockIdentity, extract_stock_code_tokens
    from src.services.stock_list_parser import default_index_registry

    tokens = extract_stock_code_tokens("比较510300、159915、005930.KS、sh000001与000001")
    assert tokens == ["510300", "159915", "005930.KS", "sh000001", "000001"]
    registry = default_index_registry()
    identities = [StockIdentity.from_code(token, registry) for token in tokens]
    assert [(identity.canonical_id, identity.asset_type) for identity in identities] == [
        ("sh510300", "stock"), ("sz159915", "stock"), ("005930.KS", "stock"),
        ("sh000001", "index"), ("sz000001", "stock"),
    ]
    assert identities[2].stock_code == "005930.KS"


@pytest.mark.parametrize("registry_state", ["missing", "empty", "changed_identity"])
def test_strict_guard_rejects_changed_registry_before_handler_or_cache(monkeypatch, registry_state):
    from src.agent import tools
    from src.agent.stock_scope import StockIdentity, StockScope
    from src.agent.tool_surface import ToolSurface
    from src.agent.tools.execution import ToolAccessContext, _build_tool_cache_key
    from src.agent.tools.registry import ToolDefinition, ToolParameter, ToolPolicy, ToolRegistry
    from src.services.stock_list_parser import IndexEntry, default_index_registry

    identity = StockIdentity.from_code("sh000001", default_index_registry())
    scope = StockScope(expected_stock_code=identity.stock_code,
                       allowed_stock_codes={identity.stock_code}, strict=True, identities=(identity,))
    called = []
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="probe", description="controlled stock tool",
        parameters=[ToolParameter(name="stock_code", type="string", description="Stock")],
        handler=lambda stock_code: called.append(stock_code),
        policy=ToolPolicy.declared(read_only=True, scope_dimensions=["stock"]),
    ))
    execution_registry = {
        "missing": None,
        "empty": IndexRegistry([]),
        "changed_identity": IndexRegistry([IndexEntry(
            bare_code="000001", exchange="SH", canonical_id="sh999999",
            display_name="changed fixture", aliases=("sh000001",),
        )]),
    }[registry_state]
    monkeypatch.setattr(tools.execution, "_default_index_registry_or_none", lambda: execution_registry)
    result = ToolSurface(registry).execute_tool("probe", {"stock_code": "sh000001"}, ToolAccessContext(stock_scope=scope))
    assert result["ok"] is False
    assert result["error"]["code"] == "stock_identity_unavailable"
    assert called == []
    assert _build_tool_cache_key("probe", {"stock_code": "sh000001"}, stock_scope=scope) is None


def test_real_runner_guard_cache_and_handler_helpers_share_typed_identity(monkeypatch):
    from src.agent.stock_scope import StockIdentity, StockScope
    from src.agent.tools import execution
    from src.agent.tools.data_tools import _history_code_candidates
    from src.agent.tools.registry import ToolDefinition, ToolParameter, ToolPolicy, ToolRegistry
    from src.agent.tools.search_tools import _canonical_search_code, _resolve_search_subject
    from src.services.stock_list_parser import default_index_registry

    registered = default_index_registry()
    index = StockIdentity.from_code("sh000001", registered)
    stock = StockIdentity.from_code("000001", registered)
    scope = StockScope(expected_stock_code=index.stock_code, allowed_stock_codes={index.stock_code, stock.stock_code},
                       strict=True, identities=(index, stock))
    calls = []

    def handler(stock_code):
        # Registry fails after guard validation. Cache/data/search helpers must
        # consume that call's bound identity, not silently reparse as stock.
        monkeypatch.setattr(execution, "_default_index_registry_or_none", lambda: None)
        assert _history_code_candidates(stock_code) == ([stock_code], stock_code)
        assert _canonical_search_code(stock_code) == stock_code
        if stock_code == index.stock_code:
            assert _resolve_search_subject(stock_code, "model guessed name") == ("", "上证指数")
        calls.append(stock_code)
        return {"error": "controlled external response", "retriable": False, "code": stock_code}

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="probe", description="Controlled stock endpoint",
        parameters=[ToolParameter(name="stock_code", type="string", description="Stock")], handler=handler,
        policy=ToolPolicy.declared(read_only=True, scope_dimensions=["stock"], supported_asset_types=("stock", "index")),
    ))
    cache = {}
    for token in ["sh000001", "000001", "000001.SH"]:
        monkeypatch.setattr(execution, "_default_index_registry_or_none", lambda: registered)
        result = execution.execute_runner_tool_call(
            tool_call=SimpleNamespace(name="probe", arguments={"stock_code": token}), tool_registry=registry,
            stock_scope=scope, non_retriable_tool_results=cache,
        )
        assert result[5] is None  # actual guard did not reject any valid scope member
    assert calls == ["sh000001", "000001"]
    assert result[4] is True  # same index alias uses its own non-retriable cache
    assert len(cache) == 2
    assert any('"asset_type": "index"' in key for key in cache)
    assert any('"asset_type": "stock"' in key for key in cache)


@pytest.mark.parametrize("token, change_registry, index_cache, expected_price", [
    ("sh000001", True, True, 333),
    ("sh000001", False, True, 333),
    ("000001", False, True, 111),
    ("sh000001", True, False, None),
])
def test_real_daily_history_read_keeps_guard_identity(db, monkeypatch, token, change_registry, index_cache, expected_price):
    from datetime import date, timedelta
    import pandas as pd
    from src.agent.stock_scope import StockIdentity, StockScope
    from src.agent.tools import execution
    from src.agent.tools.data_tools import get_daily_history_tool
    from src.agent.tools.registry import ToolRegistry
    from src.services import history_loader, stock_list_parser

    registry = stock_list_parser.default_index_registry()
    identity = StockIdentity.from_code(token, registry)
    scope = StockScope(expected_stock_code=identity.stock_code, allowed_stock_codes={identity.stock_code},
                       identities=(identity,), strict=True)
    target = date(2026, 10, 6)
    for code, price in [("000001", 111)] + ([("sh000001", 333)] if index_cache else []):
        frame = pd.DataFrame([{"date": target - timedelta(days=i), "close": price, "open": price,
                               "high": price, "low": price, "volume": 1000} for i in range(30)])
        db.save_daily_data(frame, code, "fixture")
    assert len(db.get_data_range("000001", target - timedelta(days=40), target)) == 30
    external_calls = []
    monkeypatch.setattr(history_loader, "_get_fetcher_manager", lambda: SimpleNamespace(
        get_daily_data=lambda *a, **kw: external_calls.append((a, kw)) or (None, "none")))

    def guard_registry():
        if change_registry:
            monkeypatch.setattr(stock_list_parser, "default_index_registry", lambda: IndexRegistry([]))
        return registry

    monkeypatch.setattr(execution, "_default_index_registry_or_none", guard_registry)
    tools = ToolRegistry()
    tools.register(get_daily_history_tool)
    frozen = history_loader.set_frozen_target_date(target)
    try:
        result = execution.execute_runner_tool_call(
            tool_call=SimpleNamespace(name="get_daily_history", arguments={"stock_code": token, "days": 30}),
            tool_registry=tools, stock_scope=scope,
        )
    finally:
        history_loader.reset_frozen_target_date(frozen)
    assert result[5] is None  # guard accepted the genuine typed index, not an early rejection
    payload = json.loads(result[1])
    if expected_price is None:
        # A registry mutation after the common boundary cannot reclassify this
        # call. A missing index cache uses the frozen index provider target.
        assert result[2] is True
        assert external_calls[0][1]["analysis_target"].canonical_id == "sh000001"
    else:
        assert result[2] is True
        assert payload["source"] == "db_cache"
        assert payload["code"] == identity.stock_code
        assert {row["close"] for row in payload["data"]} == {expected_price}
    assert len(external_calls) == (1 if expected_price is None else 0)
    assert {row.close for row in db.get_data_range("000001", target - timedelta(days=40), target)} == {111}
    assert len(db.get_data_range("sh000001", target - timedelta(days=40), target)) == (30 if index_cache else 0)


def test_legacy_history_read_preserves_existing_stock_and_index_cache_routes(db, monkeypatch):
    from datetime import date, timedelta
    import pandas as pd
    from src.services import history_loader

    target = date(2026, 10, 6)
    for code, price in [("000001", 111), ("sh000001", 333)]:
        db.save_daily_data(pd.DataFrame([
            {"date": target - timedelta(days=i), "close": price} for i in range(30)
        ]), code, "fixture")
    monkeypatch.setattr(history_loader, "_get_fetcher_manager", lambda: pytest.fail("fresh cache must avoid external fetch"))
    # No strict execution context: ordinary Bot/pipeline callers retain their
    # existing parser route, while both buckets are actual SQLite rows.
    for code, price in [("000001", 111), ("sh000001", 333)]:
        frame, source = history_loader.load_history_df(code, days=30, target_date=target)
        assert source == "db_cache"
        assert set(frame["close"]) == {price}


def test_strict_history_fallback_routes_frozen_target_and_writes_only_index(db, monkeypatch):
    from datetime import date, timedelta
    import pandas as pd
    from data_provider.base import DataFetcherManager
    from src.agent.stock_scope import StockIdentity, StockScope
    from src.agent.tools import execution
    from src.agent.tools.data_tools import get_daily_history_tool
    from src.agent.tools.registry import ToolRegistry
    from src.services import history_loader, stock_list_parser

    target = date(2026, 10, 6)
    registry = stock_list_parser.default_index_registry()
    identity = StockIdentity.from_code("sh000001", registry)
    stock_bars = pd.DataFrame([{"date": target - timedelta(days=i), "close": 111} for i in range(30)])
    db.save_daily_data(stock_bars, "000001", "fixture")
    monkeypatch.setattr(execution, "_default_index_registry_or_none", lambda: registry)
    monkeypatch.setattr(stock_list_parser, "default_index_registry", lambda: registry)
    # No external fetcher setup. The production manager's routing remains real;
    # only its remote index-data endpoint is substituted.
    manager = DataFetcherManager.__new__(DataFetcherManager)
    calls = []

    def fetch_index(parsed, **kwargs):
        calls.append(parsed)
        return pd.DataFrame([{"date": target, "close": 333}]), "controlled-index"

    monkeypatch.setattr(manager, "_get_cn_index_daily_data", fetch_index)

    def get_manager():
        # Change after loader validation, before manager routing. It must use
        # the frozen AnalysisTarget, not perform yet another default parse.
        monkeypatch.setattr(stock_list_parser, "default_index_registry", lambda: IndexRegistry([]))
        return manager

    monkeypatch.setattr(history_loader, "_get_fetcher_manager", get_manager)
    tools = ToolRegistry()
    tools.register(get_daily_history_tool)
    scope = StockScope(expected_stock_code="sh000001", allowed_stock_codes={"sh000001"},
                       strict=True, identities=(identity,))
    frozen = history_loader.set_frozen_target_date(target)
    try:
        result = execution.execute_runner_tool_call(
            tool_call=SimpleNamespace(name="get_daily_history", arguments={"stock_code": "sh000001", "days": 30}),
            tool_registry=tools, stock_scope=scope,
        )
    finally:
        history_loader.reset_frozen_target_date(frozen)
    assert result[5] is None and result[2] is True
    assert [(item.asset_type, item.canonical_id) for item in calls] == [("index", "sh000001")]
    assert json.loads(result[1])["data"][0]["close"] == 333
    assert {row.close for row in db.get_data_range("000001", target - timedelta(days=40), target)} == {111}
    assert [row.close for row in db.get_data_range("sh000001", target - timedelta(days=40), target)] == [333]


@pytest.mark.parametrize("arch", ["single", "multi"])
@pytest.mark.parametrize("interleave", ["none", "web", "recreate"])
def test_actual_bot_current_instance_can_reply_after_web(db, chat_stock_index, monkeypatch, arch, interleave):
    from bot.commands.chat import ChatCommand
    from bot.models import BotMessage, ChatType
    from src.agent.llm_adapter import LLMResponse, LLMToolAdapter, ToolCall
    from src.services.agent_chat_session_service import AgentChatSessionService

    config = Config.get_instance()
    config.agent_mode = True
    config.agent_backend = "litellm"
    config.agent_arch = arch
    config.agent_orchestrator_mode = "quick"
    config.agent_context_compression_enabled = False
    config.agent_memory_enabled = False
    service = AgentChatSessionService(db)
    message = BotMessage(platform="fixture", message_id="m", user_id="u", user_name="synthetic",
                         chat_id="room", chat_type=ChatType.PRIVATE, content="")
    sid = "fixture_u:chat"
    fired = False

    def model(_self, messages, *_a, **_kw):
        nonlocal fired
        users = [row for row in db.get_conversation_messages(sid) if row["role"] == "user"]
        if users and users[-1]["content"] == "本轮追问" and not fired:
            fired = True
            if interleave == "recreate":
                db.delete_conversation_session(sid)
            if interleave != "none":
                service.commit_user_turn(service.prepare_session_turn(config, sid, "改看300750", []))
            if arch == "single":
                return LLMResponse(tool_calls=[ToolCall(id="bot-trace", name="get_analysis_context",
                                                       arguments={"stock_code": "600519"})],
                                   reasoning_content="controlled reasoning", model="deepseek/fixture", provider="deepseek")
        return LLMResponse(content='{"signal":"hold","confidence":0.5,"reasoning":"controlled bot"}',
                           model="fixture", provider="fixture")

    monkeypatch.setattr(LLMToolAdapter, "call_with_tools", model)
    command = ChatCommand()
    first = command.execute(message, ["初次问股"])
    assert "对话执行出错" not in first.text and "对话失败" not in first.text
    accepted = service.commit_user_turn(service.prepare_session_turn(config, sid, "分析600519", []))
    reply = command.execute(message, ["本轮追问"])
    assert "对话执行出错" not in reply.text and "对话失败" not in reply.text
    assert fired
    rows = db.get_conversation_messages(sid)
    snapshot = db.read_chat_session_snapshot(sid)
    if interleave == "recreate":
        assert [row["content"] for row in rows] == ["改看300750"]
        assert snapshot["session_generation"] != accepted["session_generation"]
        assert db.get_agent_provider_turns(sid) == []
        assert db.get_conversation_summary(sid) is None
    else:
        assert sum(row["role"] == "user" and row["content"] == "本轮追问" for row in rows) == 1
        assert rows[-1]["role"] == "assistant"
        assert snapshot["session_generation"] == accepted["session_generation"]
        assert snapshot["session_state_version"] == (2 if interleave == "web" else 1)
        assert snapshot["active_stock_context"]["stock_code"] == ("300750" if interleave == "web" else "600519")
        if interleave == "none":
            detail = service.get_session_detail(sid, 100)
            assert detail.active_stock_context == accepted["active_stock_context"]
            assert detail.session_state_version == 1
            assert snapshot["latest_user_anchor"] == snapshot["last_accepted_user_anchor"]
        if arch == "single":
            traces = db.get_agent_provider_turns(sid)
            assert len(traces) == 1
            bot_user = next(row for row in rows if row["content"] == "本轮追问")
            assert traces[0]["anchor_user_message_id"] == int(bot_user["id"])
            assert traces[0]["anchor_assistant_message_id"] == int(rows[-1]["id"])


def _current_bot_probe(actual_chat_api, monkeypatch, arch):
    """Observe real execution; replace only the model boundary."""
    from bot.commands.chat import ChatCommand
    from bot.models import BotMessage, ChatType
    from src.agent.executor import AgentExecutor
    from src.agent.llm_adapter import LLMResponse, LLMToolAdapter
    from src.agent.orchestrator import AgentOrchestrator

    client, requests, config = actual_chat_api
    config.agent_mode = True
    config.agent_arch = arch
    config.agent_orchestrator_mode = "quick"
    config.agent_memory_enabled = False
    scopes, model_calls = [], []
    original_single = AgentExecutor._run_loop
    original_multi = AgentOrchestrator._execute_pipeline

    def single(self, *args, **kwargs):
        scopes.append(kwargs.get("stock_scope"))
        return original_single(self, *args, **kwargs)

    def multi(self, ctx, *args, **kwargs):
        scopes.append(ctx.meta.get("stock_scope"))
        return original_multi(self, ctx, *args, **kwargs)

    def model(_self, messages, *_args, **_kwargs):
        model_calls.append(messages)
        return LLMResponse(content='{"signal":"hold","confidence":0.5,"reasoning":"controlled bot"}',
                           model="fixture", provider="fixture")

    monkeypatch.setattr(AgentExecutor, "_run_loop", single)
    monkeypatch.setattr(AgentOrchestrator, "_execute_pipeline", multi)
    monkeypatch.setattr(LLMToolAdapter, "call_with_tools", model)
    message = BotMessage(platform="fixture", message_id="m", user_id="u", user_name="synthetic",
                         chat_id="room", chat_type=ChatType.PRIVATE, content="")
    return client, requests, config, ChatCommand(), message, scopes, model_calls


@pytest.mark.parametrize("arch", ["single", "multi"])
@pytest.mark.parametrize("message, allowed, preserve", [
    ("风险呢", {"600519"}, True),
    ("和300750比较", {"600519", "300750"}, True),
    ("改看300750", {"300750"}, False),
    ("改看未能确认的新对象", set(), False),
])
def test_current_bot_uses_authoritative_snapshot_without_becoming_stock_writer(
    actual_chat_api, db, monkeypatch, arch, message, allowed, preserve,
):
    client, requests, config, command, bot_message, scopes, model_calls = _current_bot_probe(
        actual_chat_api, monkeypatch, arch,
    )
    sid = "fixture_u:chat"
    # Establish A through the real API single backend, then exercise Bot's
    # current single/multi factory, preparation, transaction and execution.
    config.agent_arch = "single"
    response = client.post("/api/v1/agent/chat", json={"session_id": sid, "message": "分析600519", "skills": []})
    assert response.status_code == 200
    config.agent_arch = arch
    before = db.read_chat_session_snapshot(sid)
    reply = command.execute(bot_message, [message])
    after = db.read_chat_session_snapshot(sid)
    detail = client.get(f"/api/v1/agent/chat/sessions/{sid}").json()
    print("BOT_OBSERVATION", json.dumps({
        "arch": arch, "message": message, "scope": [scope.as_log_payload() if scope else None for scope in scopes],
        "before": before, "after": after, "detail": detail, "reply": reply.text, "model_calls": len(model_calls),
    }, default=str, ensure_ascii=False))
    assert "对话执行出错" not in reply.text and "对话失败" not in reply.text
    assert model_calls and len(scopes) == 1
    assert scopes[0] is not None and scopes[0].strict
    assert scopes[0].allowed_stock_codes == allowed
    assert after["active_stock_context"] == before["active_stock_context"]
    assert after["session_state_version"] == before["session_state_version"] == 1
    assert (detail["active_stock_context"] or {}).get("stock_code") == ("600519" if preserve else None)
    if preserve:
        assert after["last_accepted_user_anchor"] == after["latest_user_anchor"]
    else:
        assert after["last_accepted_user_anchor"] == before["last_accepted_user_anchor"]
    # Next Web follow-up must actually enter analysis, not merely return 200.
    config.agent_arch = "single"
    count = len(requests)
    next_web = client.post("/api/v1/agent/chat", json={"session_id": sid, "message": "风险呢", "skills": []})
    assert next_web.status_code == 200
    assert len(requests) == count + int(preserve)
    if preserve:
        assert requests[-1].stock_scope.strict
        assert requests[-1].stock_scope.allowed_stock_codes == {"600519"}
        final = db.read_chat_session_snapshot(sid)
        assert final["active_stock_context"] == before["active_stock_context"]
    else:
        assert db.read_chat_session_snapshot(sid)["active_stock_context"] is None


@pytest.mark.parametrize("arch", ["single", "multi"])
def test_stale_current_bot_commit_cannot_invalidate_newer_web_accept(
    actual_chat_api, db, monkeypatch, arch,
):
    from src.agent.conversation import ConversationManager

    client, _requests, config, command, bot_message, scopes, model_calls = _current_bot_probe(
        actual_chat_api, monkeypatch, arch,
    )
    sid = "fixture_u:chat"
    config.agent_arch = "single"
    assert client.post("/api/v1/agent/chat", json={
        "session_id": sid, "message": "分析600519", "skills": [],
    }).status_code == 200
    config.agent_arch = arch
    prepared, resume = Event(), Event()
    original_commit = ConversationManager.commit_user_turn
    captured, conflicts = [], []

    def barrier(self, database, snapshot, content, *args, **kwargs):
        captured.append(snapshot)
        prepared.set()
        assert resume.wait(10), "test did not release the Bot commit barrier"
        try:
            return original_commit(self, database, snapshot, content, *args, **kwargs)
        except ChatSessionStateConflict as exc:
            conflicts.append(exc.code)
            raise

    monkeypatch.setattr(ConversationManager, "commit_user_turn", barrier)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(command.execute, bot_message, ["风险呢"])
        try:
            assert prepared.wait(10), "Bot did not reach its real commit boundary"
            assert captured[0]["active_stock_context"]["stock_code"] == "600519"
            config.agent_arch = "single"
            assert client.post("/api/v1/agent/chat", json={
                "session_id": sid, "message": "改看300750", "skills": [],
            }).status_code == 200
        finally:
            resume.set()
        reply = future.result(timeout=10)
    after = db.read_chat_session_snapshot(sid)
    detail = client.get(f"/api/v1/agent/chat/sessions/{sid}").json()
    print("BOT_CAS_OBSERVATION", json.dumps({
        "arch": arch, "prepared": captured[0], "after": after, "detail": detail,
        "reply": reply.text, "model_calls": len(model_calls), "execution_count": len(scopes),
        "conflicts": conflicts,
    }, default=str, ensure_ascii=False))
    assert conflicts == ["session_state_conflict"]
    assert "refresh the session before retrying" in reply.text
    assert not model_calls and not scopes
    assert not any(row["role"] == "user" and row["content"] == "风险呢" for row in after["messages"])
    assert after["session_state_version"] == 2
    assert after["active_stock_context"]["stock_code"] == "300750"
    assert after["latest_user_anchor"] == after["last_accepted_user_anchor"]
    assert detail["active_stock_context"]["stock_code"] == "300750"


@pytest.mark.parametrize("disposition", ["preserve", "invalidate"])
def test_current_compatibility_cas_checks_latest_anchor_even_at_same_version(db, chat_stock_index, disposition):
    from src.services.agent_chat_session_service import AgentChatSessionService

    config = Config.get_instance()
    service = AgentChatSessionService(db)
    sid = "current-compatibility-anchor"
    accepted = service.commit_user_turn(service.prepare_session_turn(config, sid, "分析600519", []))
    stale_web = service.prepare_session_turn(config, sid, "风险呢", [])
    snapshot = db.read_chat_session_snapshot(sid)
    _scope, first_disposition = service.prepare_compatibility_turn(config, snapshot, "风险呢")
    assert first_disposition == "preserve"
    db.commit_legacy_chat_user_turn(snapshot, "风险呢", state_disposition=first_disposition)
    assert db.read_chat_session_snapshot(sid)["session_state_version"] == 1
    with pytest.raises(ChatSessionStateConflict):
        db.commit_legacy_chat_user_turn(snapshot, "迟到旧问题", state_disposition=disposition)
    with pytest.raises(ChatSessionStateConflict):
        service.commit_user_turn(stale_web)
    after = db.read_chat_session_snapshot(sid)
    assert not any(row["content"] == "迟到旧问题" for row in after["messages"])
    assert after["latest_user_anchor"] == after["last_accepted_user_anchor"]
    assert service.get_session_detail(sid, 100).active_stock_context == accepted["active_stock_context"]


@pytest.mark.parametrize("arch", ["single", "multi"])
@pytest.mark.parametrize("prior, message, expected_main, allowed, clarify", [
    (None, "比较600519和宁德时代", None, {"600519", "300750"}, False),
    ("分析600519", "比较600519和宁德时代", "600519", {"600519", "300750"}, False),
    ("分析600519", "从600519改看300750", "300750", {"300750"}, False),
    (None, "分析688981中芯国际", "688981", {"688981"}, False),
    (None, "分析中芯国际688981", "688981", {"688981"}, False),
    (None, "比较600519贵州茅台和300750宁德时代", None, {"600519", "300750"}, False),
    ("分析600519", "风险呢，顺带提到宁德时代", "600519", {"600519"}, False),
    # v1.0 convergence contract: an explicit background aside cannot affect
    # the ordinary follow-up or expand its scope, regardless of mention count.
    ("分析600519", "风险呢，顺带提到300750和000001", "600519", {"600519"}, False),
    ("分析600519", "300750和600519有什么消息", "600519", {"600519"}, True),
    ("分析600519", "从600519改看300750或000001", "600519", {"600519"}, True),
    (None, "比较600519和中芯国际", None, set(), True),
])
def test_resolved_mixed_mentions_and_switch_reach_execution_snapshot(
    db, chat_stock_index, prior, message, expected_main, allowed, clarify, arch,
):
    from src.agent.factory import build_agent_chat_executor
    from src.services.agent_chat_session_service import AgentChatSessionService

    config = Config.get_instance()
    config.agent_backend = "litellm"
    config.agent_arch = arch
    config.agent_context_compression_enabled = False
    service = AgentChatSessionService(db)
    sid = "mixed-mentions"
    before = service.commit_user_turn(service.prepare_session_turn(config, sid, prior, [])) if prior else None
    resolved = service.prepare_session_turn(config, sid, message, [], context={
        "stock_code": "600519", "canonical_id": "sh600519", "asset_type": "stock",
        "analysis_summary": "OLD REPORT MUST NOT LEAK", "current_price": 123,
    } if prior else None)
    assert bool(resolved.clarification) is clarify
    assert resolved.stock_scope.allowed_stock_codes == allowed
    assert (resolved.active_stock_context or {}).get("stock_code") == expected_main
    if clarify:
        accepted = service.commit_user_turn(resolved)
    else:
        executor = build_agent_chat_executor(config, skills=[])
        turn = executor.prepare_turn(message=message, session_id=sid, resolved_turn=resolved, session_service=service)
        execution_scope = turn.prepared.stock_scope if arch == "single" else turn.context.meta["stock_scope"]
        assert execution_scope == resolved.stock_scope
        if arch == "multi":
            assert turn.context.stock_code == (expected_main or "")
        accepted = turn.accepted_snapshot
        if prior and expected_main == "300750":
            history = turn.prepared.history_messages if arch == "single" else turn.context.meta.get("conversation_history", [])
            assert all("OLD REPORT" not in str(row) and "123" not in str(row) for row in history)
    stock = accepted["active_stock_context"]
    assert (stock or {}).get("stock_code") == expected_main
    persisted = db.read_chat_session_snapshot(sid)
    assert persisted["active_stock_context"] == stock
    if before and expected_main == "600519":
        assert stock["source_message_id"] == before["active_stock_context"]["source_message_id"]
        assert stock["updated_at"] == before["active_stock_context"]["updated_at"]
    elif stock:
        assert stock["source_message_id"] == accepted["user_message_id"]


@pytest.mark.parametrize("recreate", [False, True])
def test_legacy_chat_backend_uses_its_bound_source_for_terminal_and_trace(db, chat_stock_index, monkeypatch, recreate):
    from src.agent.agent_backend import AgentRunResult, LiteLLMAgentBackend
    from src.agent.factory import build_agent_chat_executor
    from src.services.agent_chat_session_service import AgentChatSessionService

    config = Config.get_instance()
    config.agent_backend = "litellm"
    config.agent_arch = "single"
    config.agent_context_compression_enabled = False
    service = AgentChatSessionService(db)
    sid = "legacy-backend"
    old = service.commit_user_turn(service.prepare_session_turn(config, sid, "分析600519", []))

    def controlled_backend(_self, request):
        users = [m for m in db.get_conversation_messages(sid) if m["role"] == "user"]
        assert [m["content"] for m in users] == ["分析600519", "legacy question"]
        if recreate:
            db.delete_conversation_session(sid)
        service.commit_user_turn(service.prepare_session_turn(config, sid, "分析300750", []))
        messages = [{"role": "system", "content": request.system_prompt}, *request.history_messages,
                    {"role": "user", "content": request.user_message},
                    {"role": "assistant", "content": "", "reasoning_content": "controlled reasoning",
                     "tool_calls": [{"id": "t", "type": "function", "function": {"name": "get_analysis_context", "arguments": "{}"}}],
                     "_trace_provider": "deepseek", "_trace_model": "deepseek/fixture"},
                    {"role": "tool", "tool_call_id": "t", "content": "controlled tool result"}]
        return AgentRunResult(success=True, final_answer="legacy answer", backend="litellm", messages=messages)

    monkeypatch.setattr(LiteLLMAgentBackend, "run", controlled_backend)
    executor = build_agent_chat_executor(config, skills=[])
    turn = executor.prepare_turn(message="legacy question", session_id=sid)
    assert turn.accepted_snapshot["session_generation"] == old["session_generation"]
    assert turn.accepted_snapshot["user_message_id"] != old["user_message_id"]
    assert db.read_chat_session_snapshot(sid)["session_state_version"] == 1
    assert executor.execute_turn(turn).success
    rows = db.get_conversation_messages(sid)
    traces = db.get_agent_provider_turns(sid)
    if recreate:
        assert [m["content"] for m in rows] == ["分析300750"]
        assert traces == []
    else:
        assert rows[-1]["content"] == "legacy answer"
        assert len(traces) == 1
        assert traces[0]["anchor_user_message_id"] == turn.user_message_id
        assert traces[0]["anchor_assistant_message_id"] == int(rows[-1]["id"])
    assert db.read_chat_session_snapshot(sid)["active_stock_context"]["stock_code"] == "300750"


@pytest.mark.parametrize("arch", ["single", "multi"])
def test_legacy_prepare_deletion_during_compression_cannot_rebind_request(db, chat_stock_index, monkeypatch, arch):
    from src.agent import chat_context
    from src.agent.factory import build_agent_chat_executor
    from src.services.agent_chat_session_service import AgentChatSessionService

    config = Config.get_instance()
    config.agent_backend = "litellm"
    config.agent_arch = arch
    config.agent_context_compression_enabled = True
    config.agent_context_compression_trigger_tokens = 1
    config.agent_context_protected_turns = 1
    service = AgentChatSessionService(db)
    sid = "legacy-summary"
    for i in range(4):
        accepted = service.commit_user_turn(service.prepare_session_turn(config, sid, "分析600519", []))
        db.save_conversation_message(sid, "assistant", f"old answer {i}", accepted_turn=accepted)
    called = []

    def summarize(**_kwargs):
        called.append(True)
        db.delete_conversation_session(sid)
        service.commit_user_turn(service.prepare_session_turn(config, sid, "分析300750", []))
        return "old summary", SimpleNamespace(usage={})

    monkeypatch.setattr(chat_context, "estimate_messages_tokens", lambda *_: 1000)
    monkeypatch.setattr(chat_context, "estimate_text_tokens", lambda *_: 1000)
    monkeypatch.setattr(chat_context, "_generate_summary", summarize)
    executor = build_agent_chat_executor(config, skills=[])
    with pytest.raises(ChatSessionStateConflict):
        executor.prepare_turn(message="late prepared request", session_id=sid)
    assert called == [True]
    assert [m["content"] for m in db.get_conversation_messages(sid)] == ["分析300750"]
    assert db.get_conversation_summary(sid) is None
