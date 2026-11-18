# -*- coding: utf-8 -*-
"""CLI-level regression tests for the --hot-top10 one-shot entry (Issue #1936).

Covers OR-COR-fa50e861 (exit code must mirror service delivery status —
the report text is rendered BEFORE save/push, so its presence alone must
not signal success) and OR-COR-ac05ea85 (the hot-top10 branch is exempt
from watchlist parsing via _skips_stock_entry).
"""

import os
import unittest

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

import main  # noqa: E402  (repo pattern: stub litellm before importing main)

from src.services.hot_top10.service import HotTop10RunResult  # noqa: E402


class HotTop10ExitCodeTestCase(unittest.TestCase):
    """OR-COR-fa50e861: a fully failed delivery (report save failed, push
    failed, or marker write failed) must exit non-zero even though the
    report text was already rendered; only delivered runs exit 0."""

    def test_failed_delivery_with_report_text_exits_nonzero(self):
        result = HotTop10RunResult(
            False, False, "delivery_failed: failed", report_markdown="# 市场热榜"
        )
        self.assertEqual(main._hot_top10_exit_code(result), 1)

    def test_marker_write_failure_exits_nonzero(self):
        result = HotTop10RunResult(
            False, True, "marker_write_failed", report_markdown="# 市场热榜"
        )
        self.assertEqual(main._hot_top10_exit_code(result), 1)

    def test_delivered_run_exits_zero(self):
        result = HotTop10RunResult(True, False, "ok", report_markdown="# 市场热榜")
        self.assertEqual(main._hot_top10_exit_code(result), 0)

    def test_skipped_run_without_report_exits_nonzero(self):
        result = HotTop10RunResult(False, True, "hotspot_data_unavailable")
        self.assertEqual(main._hot_top10_exit_code(result), 1)


class HotTop10StockEntryExemptionTestCase(unittest.TestCase):
    """OR-COR-ac05ea85: --hot-top10 never consumes the watchlist, so it must
    be exempt from stock-entry parsing: an unrelated ``--stocks`` token (or
    an unregistered STOCK_LIST target under GitHub Actions) must not block
    the hot-top10 run before the branch is even reached."""

    def _args(self, hot_top10):
        import argparse

        return argparse.Namespace(
            backtest=False,
            etf_rotation=False,
            market_review=False,
            serve_only=False,
            webui_only=False,
            portfolio=None,
            schedule=False,
            hot_top10=hot_top10,
        )

    def _config(self):
        from types import SimpleNamespace

        return SimpleNamespace(schedule_enabled=False)

    def test_hot_top10_flag_skips_stock_entry(self):
        self.assertTrue(main._skips_stock_entry(self._args(True), self._config()))

    def test_plain_run_still_consumes_stock_entry(self):
        self.assertFalse(main._skips_stock_entry(self._args(False), self._config()))


if __name__ == "__main__":
    unittest.main()
