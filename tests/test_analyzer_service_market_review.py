# -*- coding: utf-8 -*-
"""Tests for analyzer_service.perform_market_review lock and notify defaults."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import src.core.market_review_lock as market_review_lock
from src.core.market_review_lock import (
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
