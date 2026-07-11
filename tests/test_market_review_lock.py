# -*- coding: utf-8 -*-
"""Tests for market review lock stale cleanup on platforms without fcntl."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import src.core.market_review_lock as market_review_lock


class MarketReviewNoFcntlLockTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_running = market_review_lock._market_review_running
        market_review_lock._market_review_running = False

    def tearDown(self) -> None:
        market_review_lock._market_review_running = self._orig_running

    @staticmethod
    def _write_lock_file(path: Path, pid: int, started_at: datetime) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"pid={pid}\nstarted_at={started_at.isoformat()}\n",
            encoding="utf-8",
        )

    def test_stale_no_fcntl_lock_file_is_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = SimpleNamespace(database_path=str(Path(temp_dir) / "stock_analysis.db"))
            lock_path = market_review_lock.market_review_lock_path(config)
            self._write_lock_file(lock_path, pid=99999, started_at=datetime.now())

            with patch.object(market_review_lock, "fcntl", None), patch.object(
                market_review_lock,
                "_is_process_alive",
                return_value=False,
            ):
                token = market_review_lock.try_acquire_market_review_lock(config)

            self.assertIsNotNone(token)
            try:
                self.assertTrue(lock_path.exists())
            finally:
                market_review_lock.release_market_review_lock(token)

    def test_running_no_fcntl_lock_file_blocks_acquisition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = SimpleNamespace(database_path=str(Path(temp_dir) / "stock_analysis.db"))
            lock_path = market_review_lock.market_review_lock_path(config)
            self._write_lock_file(lock_path, pid=12345, started_at=datetime.now())

            with patch.object(market_review_lock, "fcntl", None), patch.object(
                market_review_lock,
                "_is_process_alive",
                return_value=True,
            ):
                token = market_review_lock.try_acquire_market_review_lock(config)

            self.assertIsNone(token)
            self.assertTrue(lock_path.exists())

    def test_empty_fresh_no_fcntl_lock_file_blocks_acquisition(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = SimpleNamespace(database_path=str(Path(temp_dir) / "stock_analysis.db"))
            lock_path = market_review_lock.market_review_lock_path(config)
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.touch()

            with patch.object(market_review_lock, "fcntl", None):
                token = market_review_lock.try_acquire_market_review_lock(config)

            self.assertIsNone(token)
            self.assertTrue(lock_path.exists())

    def test_empty_old_no_fcntl_lock_file_is_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = SimpleNamespace(database_path=str(Path(temp_dir) / "stock_analysis.db"))
            lock_path = market_review_lock.market_review_lock_path(config)
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.touch()
            old_timestamp = (datetime.now() - timedelta(days=2)).timestamp()
            os.utime(lock_path, (old_timestamp, old_timestamp))

            with patch.object(market_review_lock, "fcntl", None):
                token = market_review_lock.try_acquire_market_review_lock(config)

            self.assertIsNotNone(token)
            try:
                self.assertTrue(token.uses_flock is False)
            finally:
                market_review_lock.release_market_review_lock(token)

    def test_lock_with_old_started_at_is_recovered_even_if_process_alive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = SimpleNamespace(database_path=str(Path(temp_dir) / "stock_analysis.db"))
            lock_path = market_review_lock.market_review_lock_path(config)
            self._write_lock_file(
                lock_path,
                pid=12345,
                started_at=datetime.now() - timedelta(days=2),
            )

            with patch.object(market_review_lock, "fcntl", None), patch.object(
                market_review_lock,
                "_is_process_alive",
                return_value=True,
            ):
                token = market_review_lock.try_acquire_market_review_lock(config)

            self.assertIsNotNone(token)
            try:
                self.assertTrue(token.uses_flock is False)
            finally:
                market_review_lock.release_market_review_lock(token)

    def test_windows_liveness_probe_does_not_call_os_kill(self) -> None:
        with patch.object(market_review_lock.os, "name", "nt"), \
             patch.object(
                 market_review_lock,
                 "_is_windows_process_alive",
                 return_value=True,
             ) as windows_probe, \
             patch.object(market_review_lock.os, "kill") as os_kill:
            self.assertTrue(market_review_lock._is_process_alive(12345))

        windows_probe.assert_called_once_with(12345)
        os_kill.assert_not_called()

    def test_windows_liveness_probe_treats_invalid_pid_as_dead(self) -> None:
        kernel32 = SimpleNamespace(OpenProcess=lambda *_args: 0)
        with patch("ctypes.WinDLL", return_value=kernel32, create=True), \
             patch("ctypes.get_last_error", return_value=87, create=True):
            self.assertFalse(market_review_lock._is_windows_process_alive(99999))

    def test_windows_liveness_probe_keeps_access_denied_lock_active(self) -> None:
        kernel32 = SimpleNamespace(OpenProcess=lambda *_args: 0)
        with patch("ctypes.WinDLL", return_value=kernel32, create=True), \
             patch("ctypes.get_last_error", return_value=5, create=True):
            self.assertTrue(market_review_lock._is_windows_process_alive(12345))
