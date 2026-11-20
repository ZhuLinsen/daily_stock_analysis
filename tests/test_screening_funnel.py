# -*- coding: utf-8 -*-
"""Tests for Breakthrough 19: Screening-to-Watchlist & Batch Analysis Funnel."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_config_dep, get_database_manager
from src.core.config_manager import ConfigManager
from src.services.screening_funnel_service import (
    analyze_screening_candidates,
    extract_screening_candidates,
    promote_screening_to_watchlist,
)
from src.services.system_config_service import ConfigConflictError, SystemConfigService
from src.services.task_queue import AnalysisTaskQueue, DuplicateTaskError
from src.storage import DatabaseManager


def _seed_screening_run(db: DatabaseManager, run_id: str = "run-w6-1") -> None:
    db.save_screening_run({
        "run_id": run_id,
        "strategy": "dual_low",
        "market": "cn",
        "candidate_count": 3,
        "results": [
            {"code": "600519", "name": "贵州茅台", "score": 91.5, "close": 1520.0},
            {"code": "000858", "name": "五粮液", "score": 84.0, "close": 140.0},
            {"code": "AAPL", "name": "Apple", "score": 79.0, "close": 225.0},
        ],
    })


def test_screening_funnel_promote_analyze_and_api(tmp_path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_funnel.db'}")
    _seed_screening_run(db)

    latest = extract_screening_candidates(None, top_n=2, db_manager=db)
    assert latest["run_id"] == "run-w6-1"
    assert [c["code"] for c in latest["candidates"]] == ["600519", "000858"]

    # Idempotent watchlist promotion skips existing 600519 and adds 000858 + AAPL
    mock_cfg_svc = MagicMock()
    mock_cfg_svc.get_config.return_value = {
        "config_version": "v-1",
        "items": [{"key": "STOCK_LIST", "value": "600519"}],
    }
    promoted = promote_screening_to_watchlist("run-w6-1", top_n=5, config_service=mock_cfg_svc, db_manager=db)
    assert promoted["added"] == ["000858", "AAPL"]
    assert promoted["already_present"] == ["600519"]
    assert promoted["total_watchlist"] == 3
    mock_cfg_svc.update.assert_called_once()

    # Batch analyze queues new items and isolates DuplicateTaskError cleanly
    mock_queue = MagicMock()
    mock_queue.submit_task.side_effect = [
        MagicMock(task_id="t-1", trace_id="tr-1"),
        DuplicateTaskError("000858", "existing-t-2"),
        MagicMock(task_id="t-3", trace_id="tr-3"),
    ]
    analyzed = analyze_screening_candidates("run-w6-1", top_n=5, task_queue=mock_queue, db_manager=db)
    assert [s["code"] for s in analyzed["submitted"]] == ["600519", "AAPL"]
    assert [d["code"] for d in analyzed["duplicates"]] == ["000858"]

    # FastAPI endpoints (requires SCREENING_ENABLED=true)
    app = create_app()
    app.dependency_overrides[get_database_manager] = lambda: db
    app.dependency_overrides[get_config_dep] = lambda: SimpleNamespace(screening_enabled=True)
    client = TestClient(app)
    with patch("src.services.screening_funnel_service.SystemConfigService", return_value=mock_cfg_svc):
        resp_prom = client.post("/api/v1/screening/runs/run-w6-1/promote-watchlist", json={"top_n": 3})
    assert resp_prom.status_code == 200
    assert resp_prom.json()["ok"] is True

    mock_queue.submit_task.side_effect = None
    mock_queue.submit_task.return_value = MagicMock(task_id="t-api", trace_id="tr-api")
    with patch("src.services.task_queue.get_task_queue", return_value=mock_queue):
        resp_ana = client.post("/api/v1/screening/runs/run-w6-1/analyze-top", json={"top_n": 2})
    assert resp_ana.status_code == 200
    assert len(resp_ana.json()["submitted"]) == 2
    assert mock_queue.submit_task.call_args.kwargs["selection_source"] == "import"

    assert client.post("/api/v1/screening/runs/nonexistent-run/promote-watchlist").status_code == 404


def test_screening_funnel_enforces_feature_flag_403(tmp_path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_disabled.db'}")
    _seed_screening_run(db)
    app = create_app()
    app.dependency_overrides[get_database_manager] = lambda: db
    app.dependency_overrides[get_config_dep] = lambda: SimpleNamespace(screening_enabled=False)
    client = TestClient(app)

    resp_prom = client.post("/api/v1/screening/runs/run-w6-1/promote-watchlist", json={"top_n": 2})
    assert resp_prom.status_code == 403
    assert resp_prom.json()["error"] == "screening_disabled"

    resp_ana = client.post("/api/v1/screening/runs/run-w6-1/analyze-top", json={"top_n": 2})
    assert resp_ana.status_code == 403
    assert resp_ana.json()["error"] == "screening_disabled"


def test_screening_funnel_accepts_real_task_queue_and_reports_submission_failures(tmp_path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_queue.db'}")
    _seed_screening_run(db)

    queue = AnalysisTaskQueue(max_workers=1)
    with patch.object(queue, "_executor", MagicMock()) as mock_exec:
        mock_exec.submit.return_value = MagicMock()
        result = analyze_screening_candidates("run-w6-1", top_n=1, task_queue=queue, db_manager=db)
    assert result["ok"] is True
    assert len(result["submitted"]) == 1
    assert result["submitted"][0]["code"] == "600519"
    assert result["failed"] == []

    # Partial or total queue errors must not be masked by ok=True
    broken_queue = MagicMock()
    broken_queue.submit_task.side_effect = ValueError("queue rejected source")
    failed_result = analyze_screening_candidates("run-w6-1", top_n=1, task_queue=broken_queue, db_manager=db)
    assert failed_result["ok"] is False
    assert failed_result["submitted"] == []
    assert len(failed_result["failed"]) == 1


def test_screening_funnel_preserves_index_vs_stock_normalizes_us_hyphen_and_env_fallback(tmp_path, monkeypatch) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_edge.db'}")
    db.save_screening_run({
        "run_id": "run-edge",
        "strategy": "custom",
        "market": "us",
        "candidate_count": 2,
        "results": [
            {"code": "000001", "name": "平安银行", "score": 90.0},
            {"code": "BRK-B", "name": "Berkshire Hathaway", "score": 88.0},
        ],
    })

    # 1. Existing sh000001 index does not collide with stock 000001; BRK-B promotes as BRK.B
    # 2. Blank .env STOCK_LIST= falls back to process env STOCK_LIST
    env_file = tmp_path / ".env"
    env_file.write_text("STOCK_LIST=\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_file))
    monkeypatch.setenv("STOCK_LIST", "sh000001,600519")

    manager = ConfigManager(env_path=env_file)
    cfg_svc = SystemConfigService(manager=manager)
    promoted = promote_screening_to_watchlist("run-edge", top_n=5, config_service=cfg_svc, db_manager=db)
    assert promoted["added"] == ["000001", "BRK.B"]
    assert promoted["total_watchlist"] == 4

    saved_list = cfg_svc._manager.read_config_map()["STOCK_LIST"]
    assert saved_list == "sh000001,600519,000001,BRK.B"

    # Verify BRK.B promoted into STOCK_LIST can be deleted cleanly by existing watchlist/remove endpoint
    from api.deps import get_system_config_service
    app = create_app()
    app.dependency_overrides[get_system_config_service] = lambda: cfg_svc
    client = TestClient(app)
    rem_resp = client.post("/api/v1/stocks/watchlist/remove", json={"stock_code": "BRK.B"})
    assert rem_resp.status_code == 200
    assert "BRK.B" not in rem_resp.json()["stock_codes"]


def test_screening_funnel_retries_on_config_conflict_to_preserve_concurrent_adds(tmp_path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_conflict.db'}")
    _seed_screening_run(db)

    svc = MagicMock()
    svc._manager.get_config_version.side_effect = ["v1", "v2"]
    svc.get_config.side_effect = [
        {"config_version": "v1", "items": [{"key": "STOCK_LIST", "value": "600519"}]},
        {"config_version": "v2", "items": [{"key": "STOCK_LIST", "value": "600519,300750"}]},
    ]
    svc.update.side_effect = [ConfigConflictError("v2"), {"updated_keys": ["STOCK_LIST"]}]

    promoted = promote_screening_to_watchlist("run-w6-1", top_n=2, config_service=svc, db_manager=db)
    assert promoted["added"] == ["000858"]
    assert svc.update.call_count == 2
    final_items = svc.update.call_args.kwargs["items"]
    assert final_items == [{"key": "STOCK_LIST", "value": "600519,300750,000858"}]
