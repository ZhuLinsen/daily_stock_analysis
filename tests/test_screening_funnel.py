# -*- coding: utf-8 -*-
"""Tests for Breakthrough 19: Screening-to-Watchlist & Batch Analysis Funnel."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_database_manager
from src.services.screening_funnel_service import (
    analyze_screening_candidates,
    extract_screening_candidates,
    promote_screening_to_watchlist,
)
from src.services.task_queue import DuplicateTaskError
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

    # FastAPI endpoints
    app = create_app()
    app.dependency_overrides[get_database_manager] = lambda: db
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

    assert client.post("/api/v1/screening/runs/nonexistent-run/promote-watchlist").status_code == 404
