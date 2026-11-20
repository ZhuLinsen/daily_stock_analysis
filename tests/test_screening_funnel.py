# -*- coding: utf-8 -*-
"""Regressions for screening watchlist promotion and batch analysis."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from multiprocessing import get_context
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.deps import get_config_dep, get_database_manager, get_system_config_service
from api.v1.endpoints.stocks import add_to_watchlist, remove_from_watchlist
from api.v1.schemas.history import WatchlistRequest
from data_provider.base import DataFetcherManager
from data_provider.yfinance_fetcher import YfinanceFetcher
from data_provider.yfinance_fundamental_adapter import YfinanceFundamentalAdapter
from src.config import Config
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
        "candidates": [
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
    mock_cfg_svc.get_watchlist_snapshot.return_value = (["600519"], "v-1")
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
    app.dependency_overrides[get_system_config_service] = lambda: mock_cfg_svc
    client = TestClient(app)
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


def test_screening_funnel_accepts_real_task_queue_and_reports_submission_failures(tmp_path, monkeypatch) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_queue.db'}")
    _seed_screening_run(db)

    monkeypatch.setattr(AnalysisTaskQueue, "_instance", None)
    queue = AnalysisTaskQueue(max_workers=1)
    with patch.object(queue, "_executor") as executor:
        executor.submit.side_effect = [MagicMock(), RuntimeError("executor rejected task"), MagicMock()]
        result = analyze_screening_candidates("run-w6-1", top_n=3, task_queue=queue, db_manager=db)

    assert result["ok"] is False
    assert [task["code"] for task in result["submitted"]] == ["600519", "AAPL"]
    assert result["failed"] == [{"code": "000858", "error": "executor rejected task"}]
    for submitted in result["submitted"]:
        assert queue.get_task(submitted["task_id"]).selection_source == "import"


def test_screening_extraction_prefers_persisted_candidates_and_preserves_zero_values(tmp_path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_candidates.db'}")
    db.save_screening_run({
        "run_id": "run-candidates",
        "strategy": "custom",
        "market": "us",
        "candidates": [
            {"code": "MSFT,AAPL", "score": 99},
            {"code": "not/a/code", "score": 98},
            {"code": "BRK-B", "score": 0, "rank_score": 78, "price": 0, "close": 100},
            {"code": "BRK.B", "score": 90},
        ],
        "results": [{"code": "MSFT", "score": 95}],
    })

    result = extract_screening_candidates("run-candidates", db_manager=db)

    assert [(row["code"], row["score"], row["price"]) for row in result["candidates"]] == [("BRK.B", 0, 0)]


@pytest.mark.parametrize(
    ("existing_code", "candidate_code", "removed_code"),
    [
        ("sh000001", "000001", "000001"),
        ("000001.SS", "000001", "000001"),
        ("000001", "sh000001", "000001.SH"),
        ("600000", "csi930955", "930955.CSI"),
    ],
)
def test_screening_funnel_preserves_index_vs_stock_normalizes_us_hyphen_and_env_fallback(
    tmp_path, monkeypatch, existing_code, candidate_code, removed_code,
) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_edge.db'}")
    db.save_screening_run({
        "run_id": "run-edge",
        "strategy": "custom",
        "market": "us",
        "candidate_count": 2,
        "results": [
            {"code": candidate_code, "score": 90.0},
            {"code": "BRK-B", "name": "Berkshire Hathaway", "score": 88.0},
        ],
    })

    # 1. The same-code index and stock can coexist; BRK-B promotes as BRK.B.
    # 2. Blank .env STOCK_LIST= falls back to process env STOCK_LIST
    env_file = tmp_path / ".env"
    env_file.write_text("STOCK_LIST=\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_file))
    monkeypatch.setenv("STOCK_LIST", f"{existing_code}，600519")
    monkeypatch.setattr(Config, "_instance", None)

    manager = ConfigManager(env_path=env_file)
    cfg_svc = SystemConfigService(manager=manager)
    promoted = promote_screening_to_watchlist("run-edge", top_n=5, config_service=cfg_svc, db_manager=db)
    assert promoted["added"] == [candidate_code, "BRK.B"]
    assert promoted["total_watchlist"] == 4

    saved_list = cfg_svc._manager.read_config_map()["STOCK_LIST"]
    assert saved_list == f"{existing_code},600519,{candidate_code},BRK.B"

    # Verify BRK.B promoted into STOCK_LIST can be deleted cleanly by existing watchlist/remove endpoint
    app = create_app()
    app.dependency_overrides[get_system_config_service] = lambda: cfg_svc
    client = TestClient(app)
    rem_resp = client.post("/api/v1/stocks/watchlist/remove", json={"stock_code": "BRK.B"})
    assert rem_resp.status_code == 200
    assert rem_resp.json()["stock_codes"] == [existing_code, "600519", candidate_code]

    rem_resp = client.post("/api/v1/stocks/watchlist/remove", json={"stock_code": removed_code})
    assert rem_resp.status_code == 200
    assert rem_resp.json()["stock_codes"] == [existing_code, "600519"]
    assert manager.read_config_map()["STOCK_LIST"] == f"{existing_code},600519"


def test_screening_analyze_top_submits_same_code_index_and_stock(tmp_path, monkeypatch) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_index.db'}")
    db.save_screening_run({
        "run_id": "run-index",
        "strategy": "custom",
        "market": "cn",
        "candidate_count": 2,
        "candidates": [{"code": "000001.SH", "score": 94}, {"code": "000001", "score": 90}],
    })
    monkeypatch.setattr(AnalysisTaskQueue, "_instance", None)
    queue = AnalysisTaskQueue(max_workers=1)
    with patch.object(queue, "_executor") as executor:
        result = analyze_screening_candidates("run-index", task_queue=queue, db_manager=db)

    assert result["ok"] is True
    assert result["duplicates"] == []
    index, stock = result["submitted"]
    assert [index["code"], stock["code"]] == ["sh000001", "000001"]
    index_task = queue.get_task(index["task_id"])
    assert index_task.asset_type == "index"
    assert index_task.analysis_target.canonical_id == "sh000001"
    assert executor.submit.call_args_list[0].args[-1] == index_task.analysis_target


@pytest.mark.parametrize(
    ("yahoo_symbol", "canonical_code"),
    [("BRK-B", "BRK.B"), ("BAC-PL", "BAC-PL")],
)
def test_screening_us_symbol_can_be_promoted_removed_and_analyzed(
    tmp_path, monkeypatch, yahoo_symbol, canonical_code,
) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_us.db'}")
    db.save_screening_run({
        "run_id": "run-us",
        "strategy": "custom",
        "market": "us",
        "candidate_count": 1,
        "candidates": [{"code": yahoo_symbol, "score": 90.0}],
    })
    env_path = tmp_path / "watchlist.env"
    env_path.write_text("STOCK_LIST=AAPL\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.setenv("STOCK_LIST", "AAPL")
    monkeypatch.setattr(Config, "_instance", None)
    service = SystemConfigService(manager=ConfigManager(env_path=env_path))
    app = create_app()
    app.dependency_overrides[get_database_manager] = lambda: db
    app.dependency_overrides[get_config_dep] = lambda: SimpleNamespace(screening_enabled=True)
    app.dependency_overrides[get_system_config_service] = lambda: service
    client = TestClient(app)

    promoted = client.post("/api/v1/screening/runs/run-us/promote-watchlist")
    assert promoted.status_code == 200
    assert promoted.json()["added"] == [canonical_code]
    assert client.get("/api/v1/stocks/watchlist").json()["stock_codes"] == ["AAPL", canonical_code]
    removed = client.post("/api/v1/stocks/watchlist/remove", json={"stock_code": canonical_code})
    assert removed.status_code == 200
    assert removed.json()["stock_codes"] == ["AAPL"]

    monkeypatch.setattr(AnalysisTaskQueue, "_instance", None)
    queue = AnalysisTaskQueue(max_workers=1)
    with patch.object(queue, "_executor"), patch("src.services.task_queue.get_task_queue", return_value=queue):
        response = client.post("/api/v1/screening/runs/run-us/analyze-top")

    assert response.status_code == 200
    submitted, = response.json()["submitted"]
    assert submitted["code"] == canonical_code
    task = queue.get_task(submitted["task_id"])
    assert task is not None
    raw = pd.DataFrame(
        {"Open": [480.0], "High": [482.0], "Low": [477.0], "Close": [481.0], "Volume": [1200]},
        index=pd.DatetimeIndex(["2026-05-26"], name="Date"),
    )
    download_data = raw.copy()
    download_data.columns = pd.MultiIndex.from_product([raw.columns, [yahoo_symbol]])
    with patch("yfinance.download", return_value=download_data) as download:
        data, source = DataFetcherManager(fetchers=[YfinanceFetcher()]).get_daily_data(
            task.stock_code, start_date="2026-05-25", end_date="2026-05-27",
        )
    assert download.call_args.kwargs["tickers"] == yahoo_symbol
    assert source == "YfinanceFetcher"
    assert data["close"].tolist() == [481.0]

    ticker = MagicMock(fast_info=None, info={"shortName": canonical_code, "currency": "USD"})
    ticker.history.return_value = raw
    with patch("yfinance.Ticker", return_value=ticker) as get_ticker:
        quote = YfinanceFetcher().get_realtime_quote(task.stock_code)
        get_ticker.assert_called_once_with(yahoo_symbol)
        assert quote.code == canonical_code
        assert quote.market == "us"
        assert quote.price == 481.0

        get_ticker.reset_mock()
        YfinanceFundamentalAdapter().get_fundamental_bundle(task.stock_code)
        get_ticker.assert_called_once_with(yahoo_symbol)


def test_legacy_watchlist_entry_is_idempotent_and_can_be_analyzed_in_home_batch(tmp_path, monkeypatch) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_legacy.db'}")
    db.save_screening_run({
        "run_id": "run-legacy",
        "strategy": "custom",
        "market": "us",
        "candidate_count": 1,
        "candidates": [{"code": "BRK-B", "score": 90.0}],
    })
    env_path = tmp_path / "watchlist.env"
    env_path.write_text("STOCK_LIST=BRK-B,AAPL\n", encoding="utf-8")
    service = SystemConfigService(manager=ConfigManager(env_path=env_path))
    app = create_app()
    app.dependency_overrides[get_system_config_service] = lambda: service
    client = TestClient(app)

    promoted = promote_screening_to_watchlist("run-legacy", config_service=service, db_manager=db)
    assert promoted["added"] == []
    assert promoted["already_present"] == ["BRK.B"]
    watchlist = client.get("/api/v1/stocks/watchlist").json()["stock_codes"]
    assert watchlist == ["BRK-B", "AAPL"]

    monkeypatch.setattr(AnalysisTaskQueue, "_instance", None)
    queue = AnalysisTaskQueue(max_workers=1)
    with patch.object(queue, "_executor"), patch("api.v1.endpoints.analysis.get_task_queue", return_value=queue):
        response = client.post("/api/v1/analysis/analyze", json={"stock_codes": watchlist, "async_mode": True})

    assert response.status_code == 202
    assert [task["stock_code"] for task in response.json()["accepted"]] == ["BRK.B", "AAPL"]


def _add_to_watchlist_in_worker(attempted, saved) -> None:
    manager = ConfigManager()
    apply_updates = manager.apply_updates

    def notify_write_attempt(*args, **kwargs):
        attempted.set()
        return apply_updates(*args, **kwargs)

    with patch.object(manager, "apply_updates", side_effect=notify_write_attempt):
        service = SystemConfigService(manager=manager)
        result = add_to_watchlist(WatchlistRequest(stock_code="000858"), service=service)
    saved.set()
    assert result.stock_codes == ["600519", "300750", "000858"]


def test_promotion_and_watchlist_add_serialize_across_processes(tmp_path, monkeypatch) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_multiprocess.db'}")
    db.save_screening_run({
        "run_id": "run-multiprocess",
        "strategy": "custom",
        "market": "cn",
        "candidate_count": 1,
        "candidates": [{"code": "300750", "score": 90.0}],
    })
    env_path = tmp_path / "watchlist.env"
    env_path.write_text("STOCK_LIST=600519\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.setenv("STOCK_LIST", "600519")
    monkeypatch.setattr(Config, "_instance", None)
    manager = ConfigManager(env_path=env_path)
    service = SystemConfigService(manager=manager)

    context = get_context("spawn")
    attempted, saved = context.Event(), context.Event()
    worker = context.Process(target=_add_to_watchlist_in_worker, args=(attempted, saved))
    paused, resume = Event(), Event()
    atomic_upsert = manager._atomic_upsert

    def pause_before_write(updates):
        paused.set()
        assert resume.wait(20)
        atomic_upsert(updates)

    with patch.object(manager, "_atomic_upsert", side_effect=pause_before_write):
        with ThreadPoolExecutor(max_workers=1) as executor:
            promotion = executor.submit(
                promote_screening_to_watchlist, "run-multiprocess", config_service=service, db_manager=db,
            )
            try:
                assert paused.wait(10)
                worker.start()
                assert attempted.wait(15)
                assert not saved.wait(0.25)
            finally:
                resume.set()
                if worker.pid is not None:
                    worker.join(10)
                    if worker.is_alive():
                        worker.terminate()
                        worker.join(5)
            assert promotion.result(timeout=5)["added"] == ["300750"]

    assert worker.exitcode == 0
    assert saved.is_set()
    assert manager.read_config_map()["STOCK_LIST"] == "600519,300750,000858"


def _clear_watchlist_in_worker() -> None:
    response = remove_from_watchlist(WatchlistRequest(stock_code="600519"), service=SystemConfigService())
    assert response.stock_codes == []


def test_promotion_does_not_restore_code_cleared_by_another_process(tmp_path, monkeypatch) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_cleared.db'}")
    db.save_screening_run({
        "run_id": "run-cleared",
        "strategy": "custom",
        "market": "cn",
        "candidates": [{"code": "300750"}],
    })
    env_path = tmp_path / "watchlist.env"
    env_path.write_text("STOCK_LIST=\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.setenv("STOCK_LIST", "600519")
    monkeypatch.setattr(Config, "_instance", None)

    worker = get_context("spawn").Process(target=_clear_watchlist_in_worker)
    worker.start()
    try:
        worker.join(20)
        assert worker.exitcode == 0
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(5)

    assert os.environ["STOCK_LIST"] == "600519"
    service = SystemConfigService()
    assert service.get_watchlist_snapshot()[0] == []
    promoted = promote_screening_to_watchlist("run-cleared", config_service=service, db_manager=db)
    assert promoted["added"] == ["300750"]
    assert service.get_watchlist_snapshot()[0] == ["300750"]


@pytest.mark.parametrize(
    ("pause_at", "expected"),
    [
        ("promotion_write", ["600519", "300750", "000858"]),
        ("home_snapshot", ["600519", "300750", "000858"]),
        ("promotion_validation", ["300750"]),
    ],
)
def test_watchlist_concurrent_home_and_promotion(
    tmp_path, monkeypatch, pause_at, expected,
) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_concurrent.db'}")
    db.save_screening_run({
        "run_id": "run-concurrent",
        "strategy": "custom",
        "market": "cn",
        "candidate_count": 1,
        "candidates": [{"code": "300750", "name": "宁德时代", "score": 90.0}],
    })
    clear_env_fallback = pause_at == "promotion_validation"
    env_path = tmp_path / "watchlist.env"
    env_path.write_text("STOCK_LIST=\n" if clear_env_fallback else "STOCK_LIST=600519\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.setenv("STOCK_LIST", "600519")
    monkeypatch.setattr(Config, "_instance", None)
    promotion = SystemConfigService(manager=ConfigManager(env_path=env_path))
    home = SystemConfigService(manager=ConfigManager(env_path=env_path))
    initial_version = home._manager.get_config_version()

    paused = Event()
    resume = Event()

    owner, method = {
        "promotion_write": (promotion._manager, "_atomic_upsert"),
        "home_snapshot": (home, "get_watchlist_snapshot"),
        "promotion_validation": (promotion, "_collect_issues"),
    }[pause_at]
    original = getattr(owner, method)

    def pause_once(*args, **kwargs):
        # Intercept persistence after the last version check, or pause after
        # returning the real snapshot/validation for the other interleavings.
        if pause_at != "promotion_write":
            result = original(*args, **kwargs)
        if not paused.is_set():
            paused.set()
            assert resume.wait(10)
        return original(*args, **kwargs) if pause_at == "promotion_write" else result

    monkeypatch.setattr(owner, method, pause_once)

    def promote():
        return promote_screening_to_watchlist("run-concurrent", config_service=promotion, db_manager=db)

    def edit_home():
        if clear_env_fallback:
            return remove_from_watchlist(WatchlistRequest(stock_code="600519"), service=home)
        return add_to_watchlist(WatchlistRequest(stock_code="000858"), service=home)

    promotion_first = pause_at != "home_snapshot"
    first, second = (promote, edit_home) if promotion_first else (edit_home, promote)
    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(first)
        try:
            assert paused.wait(10)
            if pause_at == "promotion_write":
                home_lock_requested = Event()
                original_lock = home._manager.locked

                def notify_home_lock():
                    home_lock_requested.set()
                    return original_lock()

                monkeypatch.setattr(home._manager, "locked", notify_home_lock)
                home_future = executor.submit(second)
                assert home_lock_requested.wait(10)
                with pytest.raises(FutureTimeoutError):
                    home_future.result(timeout=0.25)
            else:
                second_result = second()
                if clear_env_fallback:
                    assert home._manager.get_config_version() != initial_version
        finally:
            resume.set()
        first_result = future.result(timeout=10)
        if pause_at == "promotion_write":
            second_result = home_future.result(timeout=10)

    promoted, edited = (first_result, second_result) if promotion_first else (second_result, first_result)
    assert promoted["added"] == ["300750"]
    if clear_env_fallback:
        assert edited.stock_codes == []
    else:
        assert "000858" in edited.stock_codes
    assert home._manager.read_config_map()["STOCK_LIST"].split(",") == expected
    assert Config.get_instance().stock_list == expected


def test_screening_funnel_retries_on_config_conflict_to_preserve_concurrent_adds(tmp_path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_conflict.db'}")
    _seed_screening_run(db)

    svc = MagicMock()
    svc.get_watchlist_snapshot.side_effect = [
        (["600519"], "v1"),
        (["600519", "300750"], "v2"),
    ]
    svc.update.side_effect = [ConfigConflictError("v2"), {"updated_keys": ["STOCK_LIST"]}]

    promoted = promote_screening_to_watchlist("run-w6-1", top_n=2, config_service=svc, db_manager=db)
    assert promoted["added"] == ["000858"]
    assert svc.update.call_count == 2
    final_items = svc.update.call_args.kwargs["items"]
    assert final_items == [{"key": "STOCK_LIST", "value": "600519,300750,000858"}]


def test_screening_promotion_retries_a_torn_file_read(tmp_path, monkeypatch) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_torn.db'}")
    _seed_screening_run(db)
    env_path = tmp_path / ".env"
    env_path.write_text("STOCK_LIST=600519\n", encoding="utf-8")
    monkeypatch.setenv("ENV_FILE", str(env_path))
    monkeypatch.setenv("STOCK_LIST", "600519")
    monkeypatch.setattr(Config, "_instance", None)
    manager = ConfigManager(env_path=env_path)
    service = SystemConfigService(manager=manager)
    original_read = manager.read_config_map

    def replace_during_first_read():
        monkeypatch.setattr(manager, "read_config_map", original_read)
        values = original_read()
        env_path.write_text("STOCK_LIST=600519,300750\n", encoding="utf-8")
        return values

    monkeypatch.setattr(manager, "read_config_map", replace_during_first_read)
    result = promote_screening_to_watchlist("run-w6-1", top_n=2, config_service=service, db_manager=db)

    assert result["added"] == ["000858"]
    assert manager.read_config_map()["STOCK_LIST"] == "600519,300750,000858"


def test_screening_promotion_returns_409_after_four_conflicts(tmp_path) -> None:
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'screen_contended.db'}")
    _seed_screening_run(db)
    service = MagicMock()
    service.get_watchlist_snapshot.return_value = (["600519"], "v1")
    service.update.side_effect = ConfigConflictError("v2")
    app = create_app()
    app.dependency_overrides[get_database_manager] = lambda: db
    app.dependency_overrides[get_config_dep] = lambda: SimpleNamespace(screening_enabled=True)
    app.dependency_overrides[get_system_config_service] = lambda: service

    response = TestClient(app).post("/api/v1/screening/runs/run-w6-1/promote-watchlist")

    assert response.status_code == 409
    assert response.json()["error"] == "config_conflict"
    assert service.get_watchlist_snapshot.call_count == service.update.call_count == 4
