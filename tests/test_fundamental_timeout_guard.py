"""Deterministic regression tests for timed-out fundamental background work."""

from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Event, Thread, current_thread
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from data_provider.base import DataFetcherManager


def test_repeated_capital_flow_timeouts_do_not_spawn_more_background_workers():
    release = Event()
    workers = []
    config = SimpleNamespace(fundamental_retry_max=2, fundamental_fetch_timeout_seconds=0.01)

    def blocked(_stock_code):
        workers.append(current_thread())
        release.wait()
        return {"stock_flow": {"today_main_net_inflow": 1}}

    try:
        with patch("src.config.get_config", return_value=config), patch(
            "data_provider.fundamental_adapter.AkshareFundamentalAdapter.get_capital_flow",
            side_effect=blocked,
        ):
            # Each analysis pipeline can create a new manager; a per-manager
            # guard would still leak one background request per analysis.
            for index in range(12):
                manager = DataFetcherManager(fetchers=[])
                block = manager.get_capital_flow_context(f"{600000 + index}")
                assert block["status"] == "failed"
            assert len(workers) == 1
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=2)
            assert not worker.is_alive()


@pytest.mark.parametrize("raises", [False, True])
def test_quarantine_releases_only_after_real_worker_exit(raises):
    manager = DataFetcherManager(fetchers=[])
    manager._fundamental_timeout_slots = BoundedSemaphore(1)
    release = Event()
    workers = []
    key = ("test_provider", "recovery")

    def blocked():
        workers.append(current_thread())
        release.wait()
        if raises:
            raise RuntimeError("late upstream failure")
        return "late result"

    try:
        result, error, _ = manager._run_with_timeout(blocked, 0.01, "test", quarantine_key=key)
        assert result is None and "timeout" in error
        # A timeout must not release the real worker's slot.
        assert not manager._fundamental_timeout_slots.acquire(blocking=False)
        for _ in range(12):
            result, error, _ = manager._run_with_timeout(blocked, 0.01, "test", quarantine_key=key)
            assert result is None and "previous request still running" in error
        assert len(workers) == 1

        other = DataFetcherManager(fetchers=[])
        for other_key in [("test_provider", "other_operation"), ("other_provider", "recovery"), None]:
            result, error, _ = other._run_with_timeout(lambda: "healthy", 1, "other", quarantine_key=other_key)
            assert result == "healthy" and error is None
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=2)
            assert not worker.is_alive()

    assert key not in DataFetcherManager._fundamental_timed_out_workers
    result, error, _ = manager._run_with_timeout(lambda: "fresh result", 1, "test", quarantine_key=key)
    assert result == "fresh result" and error is None


def test_concurrent_healthy_requests_are_not_quarantined():
    manager = DataFetcherManager(fetchers=[])
    key = ("test_provider", "healthy")
    entered = [Event(), Event()]
    release = Event()

    def healthy(index):
        entered[index].set()
        release.wait()
        return index

    with ThreadPoolExecutor(max_workers=2) as callers:
        futures = [callers.submit(manager._run_with_timeout, lambda i=i: healthy(i), 2, "healthy", quarantine_key=key)
                   for i in range(2)]
        try:
            assert all(event.wait(timeout=1) for event in entered)
        finally:
            release.set()
        assert [future.result()[0] for future in futures] == [0, 1]
    assert key not in DataFetcherManager._fundamental_timed_out_workers


def test_all_timed_out_workers_must_finish_before_quarantine_reopens():
    manager = DataFetcherManager(fetchers=[])
    key = ("test_provider", "parallel_timeout")
    entered = [Event(), Event()]
    release = [Event(), Event()]
    workers = [None, None]

    def blocked(index):
        workers[index] = current_thread()
        entered[index].set()
        release[index].wait()
        return index

    # Hold callers at join until both workers have started, eliminating startup
    # timing assumptions from the two-timeout registration race.
    real_join = Thread.join

    def synchronized_join(worker, timeout=None):
        if worker.name == "fundamental-parallel":
            assert all(event.wait(timeout=2) for event in entered)
            return real_join(worker, timeout=0)
        return real_join(worker, timeout=timeout)

    try:
        with ThreadPoolExecutor(max_workers=2) as callers, patch("data_provider.base.Thread.join", synchronized_join):
            futures = [callers.submit(manager._run_with_timeout, lambda i=i: blocked(i), 1, "parallel", quarantine_key=key)
                       for i in range(2)]
            assert all("timeout" in future.result()[1] for future in futures)
        assert DataFetcherManager._fundamental_timed_out_workers[key] == 2
        release[0].set()
        workers[0].join(timeout=2)
        assert not workers[0].is_alive()
        result, error, _ = manager._run_with_timeout(lambda: "should skip", 1, "parallel", quarantine_key=key)
        assert result is None and "previous request still running" in error
    finally:
        for event in release:
            event.set()
        for worker in workers:
            if worker is not None:
                worker.join(timeout=2)
                assert not worker.is_alive()
    assert key not in DataFetcherManager._fundamental_timed_out_workers


def test_thread_start_failure_does_not_leak_slot_or_quarantine():
    manager = DataFetcherManager(fetchers=[])
    manager._fundamental_timeout_slots = BoundedSemaphore(1)
    key = ("test_provider", "start_failure")
    with patch("data_provider.base.Thread.start", side_effect=RuntimeError("cannot start")):
        result, error, _ = manager._run_with_timeout(lambda: 1, 1, "test", quarantine_key=key)
    assert result is None and error == "cannot start"
    assert key not in DataFetcherManager._fundamental_timed_out_workers
    result, error, _ = manager._run_with_timeout(lambda: 2, 1, "test", quarantine_key=key)
    assert result == 2 and error is None


def test_completion_at_join_boundary_does_not_leave_stale_quarantine():
    manager = DataFetcherManager(fetchers=[])
    key = ("test_provider", "deadline_boundary")
    real_join = Thread.join

    def complete_before_return(worker, timeout=None):
        # Deterministically model completion before the caller records timeout.
        real_join(worker, timeout=2)
        assert not worker.is_alive()

    with patch("data_provider.base.Thread.join", complete_before_return):
        for _ in range(20):
            result, error, _ = manager._run_with_timeout(lambda: 42, 0.001, "test", quarantine_key=key)
            assert result == 42 and error is None
    assert key not in DataFetcherManager._fundamental_timed_out_workers


def test_capital_flow_quarantine_preserves_other_blocks_and_recovers():
    manager = DataFetcherManager(fetchers=[])
    config = SimpleNamespace(
        enable_fundamental_pipeline=True,
        fundamental_cache_ttl_seconds=0,
        fundamental_stage_timeout_seconds=2,
        fundamental_fetch_timeout_seconds=0.1,
        fundamental_retry_max=2,
    )
    release = Event()
    workers = []
    capital_payload = {"stock_flow": {"today_main_net_inflow": 1}}

    def blocked(_stock_code):
        workers.append(current_thread())
        release.wait()
        return capital_payload

    quote = SimpleNamespace(pe_ratio=10)
    bundle = {"status": "ok", "growth": {"roe": 10}, "earnings": {"revenue": 1}, "institution": {"count": 1}}
    dragon = {"status": "ok", "is_on_list": True}
    rankings = ([{"name": "top"}], [{"name": "bottom"}], [], "")
    try:
        with patch("src.config.get_config", return_value=config), \
                patch.object(manager, "get_realtime_quote", return_value=quote), \
                patch.object(manager._fundamental_adapter, "get_fundamental_bundle", return_value=bundle), \
                patch.object(manager._fundamental_adapter, "get_dragon_tiger_flag", return_value=dragon), \
                patch.object(manager, "_get_sector_rankings_with_meta", return_value=rankings), \
                patch.object(manager._fundamental_adapter, "get_capital_flow", side_effect=blocked):
            for _ in range(12):
                context = manager.get_fundamental_context("600519")
                assert context["status"] == "partial"
                assert context["capital_flow"]["status"] == "failed"
                assert context["valuation"]["status"] == "ok"
                assert context["growth"]["status"] == "ok"
                assert context["dragon_tiger"]["status"] == "ok"
                assert context["boards"]["status"] == "ok"
            assert len(workers) == 1
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=2)
            assert not worker.is_alive()

    with patch("src.config.get_config", return_value=config), \
            patch.object(manager._fundamental_adapter, "get_capital_flow", return_value=capital_payload):
        assert manager.get_capital_flow_context("600519")["status"] == "ok"
