# -*- coding: utf-8 -*-
"""Tests for analyzer_service.perform_market_review lock and notify defaults."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import src.core.market_review_lock as market_review_lock
from src.core.market_review_lock import (
    market_review_lock_path,
    release_market_review_lock,
    try_acquire_market_review_lock,
)
from src.services import analyzer_service


@pytest.fixture(autouse=True)
def _reset_market_review_running_flag():
    original = market_review_lock._market_review_running
    market_review_lock._market_review_running = False
    try:
        yield
    finally:
        market_review_lock._market_review_running = original


@pytest.fixture
def review_config(tmp_path):
    return SimpleNamespace(database_path=str(tmp_path / "stock_analysis.db"))


def test_relative_database_path_lock_follows_cwd(tmp_path, monkeypatch) -> None:
    """Plugin-out-of-repo scenario: relative DB/lock paths resolve against cwd.

    Skill examples must chdir into DSA_REPO_ROOT so Web and plugin share one lock.
    """
    repo_root = tmp_path / "dsa_checkout"
    other_cwd = tmp_path / "user_project"
    (repo_root / "data").mkdir(parents=True)
    other_cwd.mkdir()

    relative_config = SimpleNamespace(database_path="./data/stock_analysis.db")

    monkeypatch.chdir(repo_root)
    lock_in_repo = market_review_lock_path(relative_config).resolve()

    monkeypatch.chdir(other_cwd)
    lock_outside = market_review_lock_path(relative_config).resolve()

    assert lock_in_repo != lock_outside
    assert lock_in_repo == (repo_root / "data" / "market_review.lock").resolve()
    assert lock_outside == (other_cwd / "data" / "market_review.lock").resolve()

    # After chdir back to the checkout (plugin skill example), locks align again.
    monkeypatch.chdir(repo_root)
    assert market_review_lock_path(relative_config).resolve() == lock_in_repo

    held_in_repo = try_acquire_market_review_lock(relative_config)
    assert held_in_repo is not None
    assert held_in_repo.path.resolve() == lock_in_repo
    release_market_review_lock(held_in_repo)

    # Same process resets the in-memory flag on release; a different cwd then
    # locks a different file (two OS processes would not share that flag).
    monkeypatch.chdir(other_cwd)
    held_outside = try_acquire_market_review_lock(relative_config)
    assert held_outside is not None
    assert held_outside.path.resolve() == lock_outside
    release_market_review_lock(held_outside)


def test_perform_market_review_signature_exposes_send_notification() -> None:
    """Plugin skill relies on this kwarg; older checkouts without it must upgrade."""
    params = inspect.signature(analyzer_service.perform_market_review).parameters
    assert "send_notification" in params


def test_perform_market_review_passes_send_notification_false(review_config) -> None:
    pipeline = MagicMock()
    pipeline.notifier = MagicMock(name="pipeline_notifier")
    pipeline.analyzer = MagicMock(name="analyzer")
    pipeline.search_service = MagicMock(name="search")

    with patch.object(
        analyzer_service, "StockAnalysisPipeline", return_value=pipeline
    ) as pipeline_cls, patch.object(
        analyzer_service, "run_market_review", return_value="report"
    ) as run_review, patch.object(
        analyzer_service, "try_acquire_market_review_lock", return_value=object()
    ) as acquire, patch.object(
        analyzer_service, "release_market_review_lock"
    ) as release:
        result = analyzer_service.perform_market_review(
            config=review_config,
            send_notification=False,
        )

    assert result == "report"
    acquire.assert_called_once_with(review_config)
    pipeline_cls.assert_called_once()
    run_review.assert_called_once()
    kwargs = run_review.call_args.kwargs
    assert kwargs["send_notification"] is False
    assert kwargs["notifier"] is pipeline.notifier
    assert kwargs["config"] is review_config
    assert kwargs["trigger_source"] == "service"
    release.assert_called_once()


def test_perform_market_review_skips_when_lock_held(review_config) -> None:
    held = try_acquire_market_review_lock(review_config)
    assert held is not None
    try:
        with patch.object(analyzer_service, "StockAnalysisPipeline") as pipeline_cls, patch.object(
            analyzer_service, "run_market_review"
        ) as run_review:
            result = analyzer_service.perform_market_review(
                config=review_config,
                send_notification=False,
            )
        assert result is None
        pipeline_cls.assert_not_called()
        run_review.assert_not_called()
    finally:
        release_market_review_lock(held)


def test_perform_market_review_releases_lock_on_success(review_config) -> None:
    pipeline = MagicMock()
    pipeline.notifier = MagicMock()
    pipeline.analyzer = MagicMock()
    pipeline.search_service = MagicMock()

    with patch.object(
        analyzer_service, "StockAnalysisPipeline", return_value=pipeline
    ), patch.object(
        analyzer_service, "run_market_review", return_value="ok"
    ):
        assert (
            analyzer_service.perform_market_review(
                config=review_config,
                send_notification=False,
            )
            == "ok"
        )

    # Lock should be free for a subsequent acquire after the service returns.
    token = try_acquire_market_review_lock(review_config)
    assert token is not None
    release_market_review_lock(token)
