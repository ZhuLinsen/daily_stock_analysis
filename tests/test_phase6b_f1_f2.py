"""Bounded F1/F2 correctness regressions on real Chat/guard/SQLite paths."""
import dataclasses
import json
import os
from pathlib import Path
import sys
import threading
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from tests.test_agent_active_stock_integration import (  # noqa: F401
    isolated_database_manager, db, chat_stock_index, actual_chat_api, action_chat_api,
)
from src.config import Config


def record(name, data):
    """Optional raw evidence outside the repository; no debug product fields."""
    if os.environ.get("PHASE6B_EVIDENCE_DIR"):
        path = Path(os.environ["PHASE6B_EVIDENCE_DIR"])
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


@pytest.mark.parametrize("arch", ["single", "multi"])
@pytest.mark.parametrize("case,message,decision,allowed,analysis", [
    ("conditional", "如果600519下跌，就改看300750", "clarify", {"600519"}, False),
    ("negative-comparison", "不要研究600519和300750的区别，继续分析600519", "maintain", {"600519"}, True),
    ("switch", "从600519改看300750", "confirm", {"300750"}, True),
    ("compare", "比较600519和300750", "compare", {"600519", "300750"}, True),
    ("followup", "看看近期走势", "maintain", {"600519"}, True),
    ("independent-switch", "如果600519下跌，就改看300750；现在改看000001", "confirm", {"000001"}, True),
    ("denied-choice", "不要研究600519和300750哪个更适合，继续分析600519", "maintain", {"600519"}, True),
])
def test_f1_real_stream_decision_acceptance_and_execution(action_chat_api, db, arch, case, message, decision, allowed, analysis):
    client, requests, calls, config = action_chat_api
    config.agent_arch = arch
    sid = f"f1-{arch}-{case}"
    assert client.post("/api/v1/agent/chat", json={"session_id": sid, "message": "分析600519", "skills": []}).status_code == 200
    before = db.read_chat_session_snapshot(sid)
    count = len(requests) + len(calls)
    observed, execution = [], []

    def profile(frame, kind, result):
        if kind != "return" or result is None:
            return
        if (frame.f_code.co_name == "_resolve_session_turn"
                and frame.f_locals.get("message") == message
                and frame.f_code.co_filename.endswith("agent_chat_session_service.py")):
            observed.append({"decision": dataclasses.asdict(frame.f_locals["decision"]),
                             "scope": result.stock_scope.as_log_payload()})
        if frame.f_code.co_name == "prepare_turn" and frame.f_locals.get("message") == message:
            if hasattr(result, "prepared"):
                execution.append(result.prepared.stock_scope.as_log_payload())
            elif hasattr(result, "context"):
                execution.append(result.context.meta["stock_scope"].as_log_payload())

    previous, previous_threads = sys.getprofile(), threading.getprofile()
    sys.setprofile(profile)
    threading.setprofile(profile)
    try:
        response = client.post("/api/v1/agent/chat/stream", json={"session_id": sid, "message": message, "skills": []})
    finally:
        sys.setprofile(previous)
        threading.setprofile(previous_threads)
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    after = db.read_chat_session_snapshot(sid)
    started = len(requests) + len(calls) > count
    record(f"F1-{arch}-{case}", {"before": before, "observed": observed, "events": events,
                                "after": after, "execution_scopes": execution, "analysis_started": started})
    assert observed[0]["decision"]["kind"] == decision
    assert events[0]["type"] == "accepted" and events[-1]["type"] == "done"
    assert events[0]["active_stock_context"] == {
        key: after["active_stock_context"][key] for key in ("stock_code", "stock_name", "canonical_id", "asset_type")}
    assert after["session_state_version"] == before["session_state_version"] + 1
    assert after["selected_skill_ids"] == []
    assert len([m for m in after["messages"] if m["role"] == "user"]) == 2
    assert started is analysis
    if decision == "confirm":
        assert after["active_stock_context"]["stock_code"] == next(iter(allowed))
        assert after["active_stock_context"]["source_message_id"] == after["latest_user_anchor"][0]
    else:
        assert after["active_stock_context"] == before["active_stock_context"]
    assert set(observed[0]["scope"]["allowed_stock_codes"]) == allowed
    assert bool(execution) is analysis
    for scope in execution:
        assert set(scope["allowed_stock_codes"]) == allowed


@pytest.mark.parametrize("history, expected", [
    (["分析600519", "如果600519下跌，就改看300750", "风险呢"], "600519"),
    (["分析600519", "不要研究600519和300750的区别，继续分析600519", "风险呢"], "600519"),
    (["如果600519下跌，就改看300750"], None),
])
def test_f1_legacy_get_and_next_accept_keep_actual_provenance(action_chat_api, db, history, expected):
    client, requests, calls, _config = action_chat_api
    sid = "f1-legacy"
    ids = [db.save_conversation_user_turn(sid, message, []) for message in history]
    db.ensure_chat_session_generation(sid)
    before = db.read_chat_session_snapshot(sid)
    detail = client.get(f"/api/v1/agent/chat/sessions/{sid}?limit=1").json()
    unchanged = db.read_chat_session_snapshot(sid)
    response = client.post("/api/v1/agent/chat", json={"session_id": sid, "message": "风险呢", "skills": []})
    after = db.read_chat_session_snapshot(sid)
    record(f"F1-history-{expected}-{len(history)}-{history[-2] if len(history) > 1 else 'empty'}",
           {"history": history, "before": before, "detail": detail, "after_get": unchanged,
            "after_accept": after, "response": response.json(), "analysis_calls": len(requests) + len(calls)})
    assert detail["session_state_version"] == 0 and unchanged == before
    assert (detail["active_stock_context"] or {}).get("stock_code") == expected
    assert response.status_code == 200 and after["session_state_version"] == 1
    assert (after["active_stock_context"] or {}).get("stock_code") == expected
    if expected:
        assert after["active_stock_context"]["source_message_id"] == ids[0]
        assert after["active_stock_context"]["updated_at"] == before["messages"][0]["created_at"]
        assert requests
    else:
        assert not requests and not calls
    # Positive versions are authoritative: history is not replayed on a GET.
    final_detail = client.get(f"/api/v1/agent/chat/sessions/{sid}").json()["active_stock_context"]
    assert final_detail == ({key: after["active_stock_context"][key]
                             for key in ("stock_code", "stock_name", "canonical_id", "asset_type")} if expected else None)
    assert db.read_chat_session_snapshot(sid) == after


@pytest.mark.parametrize("token, only_other_market, runner, marker", [
    ("005930", False, False, 11), ("005930", True, False, None),
    ("005930.KS", False, False, 77), ("600519", False, False, 33),
    ("sh000001", False, False, None), ("300750", False, False, None),
    ("005930", False, True, 11),
])
def test_f2_validated_target_reaches_summary_recent_and_sql(db, monkeypatch, token, only_other_market, runner, marker):
    from src.agent.factory import get_tool_registry
    from src.agent.tools import execution, backtest_tools
    from src.agent.tool_surface import ToolSurface
    from src.data import stock_index_loader as loader
    from src.services.stock_index_remote_service import validate_stock_index_payload
    from src.services.stock_list_parser import default_index_registry, parse_analysis_target
    from src.services.agent_chat_session_service import AgentChatSessionService
    from src.storage import AnalysisHistory, BacktestSummary, BacktestResult
    from src.services.backtest_service import BacktestService

    monkeypatch.setattr(backtest_tools, "_backtest_service", BacktestService(db))
    loader.clear_stock_index_cache()
    registry = default_index_registry()
    payload = loader._CHAT_INDEX_PAYLOAD_CACHE
    validate_stock_index_payload(payload)
    loader._validate_index_rows_semantics(loader._extract_active_index_rows(payload), loader._extract_active_non_index_rows(payload))
    engine = Config.get_instance().backtest_engine_version
    service = AgentChatSessionService(db)
    resolved = service.prepare_session_turn(Config.get_instance(), f"f2-{token}", f"分析{token}", [])
    accepted = service.commit_user_turn(resolved)
    with db.get_session() as session:
        for i, (code, value) in enumerate([("005930.SZ", 11), ("005930.KS", 77), ("600519.SH", 33)]):
            if only_other_market and code != "005930.KS":
                continue
            history = AnalysisHistory(code=code, name=f"SYNTHETIC marker {value}", report_type="simple")
            session.add(history)
            session.flush()
            session.add(BacktestSummary(scope="stock", code=code, eval_window_days=30, engine_version=engine,
                                       win_rate_pct=value, total_evaluations=1, completed_count=1,
                                       computed_at=datetime(2026, 10, 7) + timedelta(seconds=i)))
            session.add(BacktestResult(analysis_history_id=history.id, code=code, analysis_date=date(2026, 10, 6),
                                      eval_window_days=30, engine_version=engine, eval_status="completed",
                                      stock_return_pct=value, operation_advice="hold", outcome="neutral", direction_correct=True))
        session.commit()
    sql, observations = [], []

    def sql_observer(_conn, _cursor, statement, parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT") and ("backtest_summaries" in statement or "backtest_results" in statement):
            sql.append({"statement": statement, "parameters": parameters})

    def profile(frame, kind, result):
        if kind == "return" and frame.f_code.co_name == "_validated_chat_tool_target" and result is not None:
            observations.append({"identity": dataclasses.asdict(result.identity), "target": dataclasses.asdict(result.target)})
        if kind == "call" and frame.f_code.co_name in {"get_summary", "get_results_paginated"} and frame.f_code.co_filename.endswith("backtest_repo.py"):
            observations.append({"repository": frame.f_code.co_name, "code": frame.f_locals.get("code"),
                                 "code_candidates": frame.f_locals.get("code_candidates")})

    event.listen(db._engine, "before_cursor_execute", sql_observer)
    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        arguments = {"stock_code": token, "eval_window_days": 30}
        if runner:
            result = execution.execute_runner_tool_call(tool_call=SimpleNamespace(name="get_stock_backtest_summary", arguments=arguments),
                                                        tool_registry=get_tool_registry(), stock_scope=resolved.stock_scope)
            ok, error, data = result[2], result[5], json.loads(result[1])
        else:
            result = ToolSurface(get_tool_registry()).execute_tool("get_stock_backtest_summary", arguments,
                                                                  execution.ToolAccessContext(stock_scope=resolved.stock_scope))
            ok, error, data = result["ok"], result.get("error"), result.get("result")
    finally:
        sys.setprofile(previous)
        event.remove(db._engine, "before_cursor_execute", sql_observer)
    record(f"F2-{token}-other{only_other_market}-runner{runner}", {"parser": dataclasses.asdict(parse_analysis_target(token, registry)),
           "accepted": accepted, "scope": resolved.stock_scope.as_log_payload(), "observations": observations,
           "sql": sql, "result": result})
    if token == "sh000001":
        assert not ok and error["code"] == "stock_tool_unsupported" and not sql
        return
    assert ok and not error and sql
    if token == "005930":
        assert accepted["active_stock_context"]["canonical_id"] == "sz005930"
        assert observations[0]["target"]["canonical_id"] == "sz005930"
        assert "005930.KS" not in str(sql)
    if marker is None:
        assert "info" in data and "error" not in data
    else:
        assert data["summary"]["win_rate_pct"] == marker
        assert [item["stock_return_pct"] for item in data["recent_evaluations"]] == [marker]
        assert data["total"] == 1


@pytest.fixture
def numeric_backtest_data(db):
    from src.services.backtest_service import BacktestService
    from src.storage import AnalysisHistory, BacktestSummary, BacktestResult

    service = BacktestService(db)
    engine = Config.get_instance().backtest_engine_version
    with db.get_session() as session:
        history = AnalysisHistory(code="600519", name="SYNTHETIC unqualified legacy row", report_type="simple")
        session.add(history)
        session.flush()
        session.add(BacktestSummary(scope="stock", code="600519", eval_window_days=30, engine_version=engine,
                                   win_rate_pct=33, total_evaluations=1, completed_count=1))
        session.add(BacktestResult(analysis_history_id=history.id, code="600519", analysis_date=date(2026, 10, 6),
                                  eval_window_days=30, engine_version=engine, eval_status="completed", stock_return_pct=33))
        session.commit()
    return service, engine


def test_f2_normal_numeric_keys_are_readable_by_strict_and_legacy(numeric_backtest_data, chat_stock_index):
    from src.services.stock_list_parser import parse_analysis_target

    service, _engine = numeric_backtest_data
    assert service.get_summary(scope="stock", code="600519", eval_window_days=30)["win_rate_pct"] == 33
    assert service.get_recent_evaluations(code="600519", eval_window_days=30)["total"] == 1
    target = parse_analysis_target("600519")
    strict_summary = service.get_summary(scope="stock", code="600519", eval_window_days=30, analysis_target=target)
    strict_recent = service.get_recent_evaluations(code="600519", eval_window_days=30, analysis_target=target)
    assert strict_summary["win_rate_pct"] == 33
    assert strict_recent["total"] == 1 and strict_recent["items"][0]["stock_return_pct"] == 33
    record("F2-normal-numeric-and-legacy", {"legacy_summary_marker": 33, "legacy_total": 1,
                                         "strict_summary": strict_summary, "strict_recent": strict_recent})


def test_f2_explicit_empty_candidates_do_not_enter_legacy(numeric_backtest_data):
    service, engine = numeric_backtest_data
    assert service.repo.get_summary(scope="stock", code=None, engine_version=engine) is not None
    all_rows, all_total = service.repo.get_results_paginated(code=None, engine_version=engine, days=None, offset=0, limit=10)
    assert all_total == len(all_rows) == 1
    assert service.repo.get_summary(scope="stock", code=None, engine_version=engine, code_candidates=()) is None
    rows, total = service.repo.get_results_paginated(code=None, engine_version=engine, days=None, offset=0, limit=10, code_candidates=())
    assert rows == [] and total == 0
    record("F2-explicit-empty", {"legacy_unconstrained_total": all_total, "explicit_empty_total": total})


@pytest.mark.parametrize("method", ["get_summary", "get_recent_evaluations"])
def test_f2_supplied_invalid_target_or_unsupported_filter_never_falls_back(db, chat_stock_index, method):
    from src.services.backtest_service import BacktestService
    from src.services.stock_list_parser import parse_analysis_target

    service = BacktestService(db)
    target = parse_analysis_target("600519")
    kwargs = {"scope": "stock"} if method == "get_summary" else {}
    read = getattr(service, method)
    for invalid in (dataclasses.replace(target, canonical_id="sz600519"),
                    dataclasses.replace(target, raw_input="300750"),
                    dataclasses.replace(target, asset_type="index")):
        with pytest.raises(ValueError):
            read(code="600519", eval_window_days=30, analysis_target=invalid, **kwargs)
    with pytest.raises(ValueError, match="dynamic filters"):
        read(code="600519", eval_window_days=30, analysis_target=target, analysis_date_from=date(2026, 10, 1), **kwargs)
    with pytest.raises(ValueError, match="dynamic filters"):
        read(code="600519", eval_window_days=30, analysis_target=target, analysis_phase="bull", **kwargs)
