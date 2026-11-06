"""Production backtest writer -> strict Chat tool, with only synthetic SQLite."""
from datetime import date, datetime
import dataclasses
import json

import pytest
from sqlalchemy import event, select

from tests.test_phase6b_f1_f2 import record
from tests.test_agent_active_stock_integration import isolated_database_manager, db, chat_stock_index  # noqa: F401
from src.config import Config


@pytest.mark.parametrize("analysis_code", ["600519", "600519.SH"])
def test_normal_backtest_writer_is_readable_by_strict_tool(db, chat_stock_index, monkeypatch, analysis_code):
    from src.agent.factory import get_tool_registry
    from src.agent.tool_surface import ToolSurface
    from src.agent.tools import backtest_tools, execution
    from src.repositories import backtest_repo
    from src.services import backtest_service
    from src.services.agent_chat_session_service import AgentChatSessionService
    from src.services.stock_list_parser import default_index_registry
    from src.storage import AnalysisHistory, BacktestResult, BacktestSummary, StockDaily

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2024, 3, 12, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(backtest_service, "datetime", FixedDateTime)
    monkeypatch.setattr(backtest_repo, "datetime", FixedDateTime)
    # Only the external refill endpoint is forbidden/substituted. Full local
    # bars must let the real start/window/evaluator/writer work without it.
    monkeypatch.setattr(backtest_service.BacktestService, "_try_fill_daily_data",
                        lambda *_args, **_kwargs: pytest.fail("complete synthetic bars must avoid external refill"))
    with db.get_session() as session:
        history = AnalysisHistory(code=analysis_code, name="SYNTHETIC writer control", report_type="simple",
                                  operation_advice="买入", created_at=datetime(2024, 3, 4, 16),
                                  context_snapshot=json.dumps({"enhanced_context": {"date": "2024-03-04"},
                                      "market_phase_summary": {"market": "cn", "phase": "postmarket",
                                          "effective_daily_bar_date": "2024-03-04"}}))
        session.add(history)
        for day, close in [(4, 100), (5, 103), (6, 105), (7, 107), (8, 108)]:
            session.add(StockDaily(code=analysis_code, date=date(2024, 3, day), open=close,
                                   high=close + 1, low=close - 1, close=close))
        session.commit()
    service = backtest_service.BacktestService(db)
    write = service.run_backtest(code=analysis_code, eval_window_days=3, min_age_days=0)
    with db.get_session() as session:
        results = [{col.name: getattr(row, col.name) for col in BacktestResult.__table__.columns}
                   for row in session.execute(select(BacktestResult)).scalars()]
        summaries = [{col.name: getattr(row, col.name) for col in BacktestSummary.__table__.columns}
                     for row in session.execute(select(BacktestSummary)).scalars()]
    stock_summaries = [row for row in summaries if row["scope"] == "stock"]
    assert write["saved"] == write["completed"] == 1 and write["errors"] == write["insufficient"] == 0
    assert [row["code"] for row in results] == [analysis_code]
    assert results[0]["eval_status"] == "completed"
    assert stock_summaries[0]["code"] == "600519" and stock_summaries[0]["completed_count"] == 1

    owner = AgentChatSessionService(db)
    resolved = owner.prepare_session_turn(Config.get_instance(), "writer-read", "分析600519", [])
    accepted = owner.commit_user_turn(resolved)
    before = db.read_chat_session_snapshot("writer-read")
    monkeypatch.setattr(backtest_tools, "_backtest_service", service)
    selects = []

    def observe(_conn, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "backtest_" in statement:
            selects.append({"sql": statement, "parameters": parameters})

    event.listen(db._engine, "before_cursor_execute", observe)
    try:
        read = ToolSurface(get_tool_registry()).execute_tool("get_stock_backtest_summary",
            {"stock_code": "600519", "eval_window_days": 3}, execution.ToolAccessContext(stock_scope=resolved.stock_scope))
        target = execution._validated_chat_tool_target(resolved.stock_scope, "600519", default_index_registry()).target
        page2 = service.get_recent_evaluations(code="600519", eval_window_days=3, limit=1, page=2, analysis_target=target)
    finally:
        event.remove(db._engine, "before_cursor_execute", observe)
    record(f"writer-read-{analysis_code}", {"write": write, "stored_results": results, "stored_summaries": summaries,
        "accepted": accepted, "target": dataclasses.asdict(target), "scope": resolved.stock_scope.as_log_payload(),
        "selects": selects, "tool_read": read, "page2": page2,
        "state_before_read": before, "state_after_read": db.read_chat_session_snapshot("writer-read")})
    assert read["ok"] and read["error"] is None
    data = read["result"]
    assert data.get("summary") is not None, "normal numeric summary must remain readable"
    assert data["summary"]["code"] == "600519"
    assert data["summary"]["total_evaluations"] == data["summary"]["completed_count"] == data["total"] == 1
    assert len(data["recent_evaluations"]) == 1
    assert data["recent_evaluations"][0]["stock_return_pct"] == results[0]["stock_return_pct"]
    assert page2["total"] == 1 and page2["items"] == []
    assert accepted["active_stock_context"]["canonical_id"] == target.canonical_id == "sh600519"
    assert db.read_chat_session_snapshot("writer-read") == before


@pytest.mark.parametrize("source_code,market,expected_marker", [
    ("005930", "cn", 11),
    ("005930.KS", "kr", None),
    ("005930", "kr", None),
    (None, None, None),
])
def test_numeric_storage_key_requires_matching_existing_source(db, chat_stock_index, monkeypatch, source_code, market, expected_marker):
    from src.agent.factory import get_tool_registry
    from src.agent.tool_surface import ToolSurface
    from src.agent.tools import backtest_tools, execution
    from src.services.agent_chat_session_service import AgentChatSessionService
    from src.services.backtest_service import BacktestService
    from src.services.stock_list_parser import default_index_registry
    from src.storage import AnalysisHistory, BacktestResult, BacktestSummary

    engine = Config.get_instance().backtest_engine_version
    marker = expected_marker or 77
    with db.get_session() as session:
        session.add(BacktestSummary(scope="stock", code="005930", eval_window_days=30, engine_version=engine,
                                   win_rate_pct=marker, total_evaluations=1, completed_count=1))
        if source_code:
            source = AnalysisHistory(code=source_code, name="SYNTHETIC ownership control", report_type="simple",
                                     context_snapshot=json.dumps({"market_phase_summary": {"phase": "postmarket", "market": market}}))
            session.add(source)
            session.flush()
            session.add(BacktestResult(code="005930", analysis_history_id=source.id, analysis_date=date(2024, 3, 4),
                                      eval_window_days=30, engine_version=engine, eval_status="completed", stock_return_pct=marker))
        session.commit()
    service = BacktestService(db)
    monkeypatch.setattr(backtest_tools, "_backtest_service", service)
    owner = AgentChatSessionService(db)
    resolved = owner.prepare_session_turn(Config.get_instance(), "numeric-owner", "分析005930", [])
    accepted = owner.commit_user_turn(resolved)
    target = execution._validated_chat_tool_target(resolved.stock_scope, "005930", default_index_registry()).target
    selects = []

    def observe(_conn, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "backtest_" in statement:
            selects.append({"sql": statement, "parameters": parameters})

    event.listen(db._engine, "before_cursor_execute", observe)
    try:
        read = ToolSurface(get_tool_registry()).execute_tool("get_stock_backtest_summary",
            {"stock_code": "005930"}, execution.ToolAccessContext(stock_scope=resolved.stock_scope))
        recent = service.get_recent_evaluations(code="005930", eval_window_days=30, analysis_target=target)
    finally:
        event.remove(db._engine, "before_cursor_execute", observe)
    record(f"numeric-owner-{source_code}-{market}", {"source_code": source_code, "source_market": market,
        "accepted": accepted, "target": dataclasses.asdict(target), "selects": selects, "read": read, "recent": recent})
    assert read["ok"] and read["error"] is None
    assert accepted["active_stock_context"]["canonical_id"] == target.canonical_id == "sz005930"
    assert "005930.KS" not in str(selects)
    if expected_marker is None:
        assert "info" in read["result"] and "error" not in read["result"]
        assert recent["items"] == [] and recent["total"] == 0
    else:
        assert read["result"]["summary"]["win_rate_pct"] == expected_marker
        assert read["result"]["total"] == recent["total"] == 1
        assert [row["stock_return_pct"] for row in recent["items"]] == [expected_marker]
