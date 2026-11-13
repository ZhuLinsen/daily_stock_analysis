# -*- coding: utf-8 -*-
"""Fail-open aggregation tests for MarketSentimentFetcher (issue #1939 Wave 3).

All network paths are stubbed: pool APIs are intercepted by replacing the
module-level ``_akshare_call_with_timeout`` reference (routing on its
``call_name`` argument, the existing repo convention), and the reused
``get_market_stats`` / ``get_sector_rankings`` calls are stubbed via an
injected fake AkshareFetcher. Asserts: per-group provider_trace status
(ok/timeout/error/empty), group isolation (one failing source never affects
the others), and fetch_all never raises.
"""

import unittest
from unittest import mock

import pandas as pd

from data_provider import market_sentiment_fetcher as msf

TRADE_DATE = "20261113"
PREV_TRADE_DATE = "20261112"


def _pool_df(n=2):
    return pd.DataFrame({
        "序号": list(range(1, n + 1)),
        "代码": ["00000%d" % i for i in range(1, n + 1)],
        "名称": ["股%d" % i for i in range(1, n + 1)],
        "涨跌幅": [9.99] * n,
        "连板数": [1] * n,
    })


def _empty_pool_df():
    return pd.DataFrame(columns=["序号", "代码", "名称", "涨跌幅", "连板数"])


class _StubAkshareFetcher:
    """Duck-typed stand-in for AkshareFetcher: reused calls + rate-limit noops."""

    def __init__(self, stats=None, rankings=None):
        self._stats = stats
        self._rankings = rankings

    def _set_random_user_agent(self):
        pass

    def _enforce_rate_limit(self):
        pass

    def get_market_stats(self):
        return self._stats

    def get_sector_rankings(self, n=5):
        return self._rankings


def _stats_fixture():
    return {
        "up_count": 765, "down_count": 4747, "flat_count": 58,
        "limit_up_count": 61, "limit_down_count": 9, "total_amount": 16668.97,
    }


def _rankings_fixture():
    top = [{"name": "半导体", "change_pct": 4.2}]
    bottom = [{"name": "房地产", "change_pct": -2.1}]
    return top, bottom


def _route_pools(by_call_name=None, by_call_and_date=None):
    """Build a fake _akshare_call_with_timeout.

    ``by_call_name`` maps call_name -> DataFrame | Exception.
    ``by_call_and_date`` maps (call_name, date) -> DataFrame | Exception.
    Unknown calls return a 2-row pool DataFrame.
    """
    by_call_name = by_call_name or {}
    by_call_and_date = by_call_and_date or {}

    def fake(func, *args, timeout=None, call_name="akshare", **kwargs):
        date = kwargs.get("date")
        if (call_name, date) in by_call_and_date:
            outcome = by_call_and_date[(call_name, date)]
        elif call_name in by_call_name:
            outcome = by_call_name[call_name]
        else:
            outcome = _pool_df()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return fake


def _make_fetcher(stats="ok", rankings="ok"):
    stub = _StubAkshareFetcher(
        stats=_stats_fixture() if stats == "ok" else None,
        rankings=_rankings_fixture() if rankings == "ok" else None,
    )
    return msf.MarketSentimentFetcher(akshare_fetcher=stub, timeout=1.0)


def _trace_groups(result):
    """metric_group -> list of trace entries."""
    grouped = {}
    for entry in result["provider_trace"]:
        grouped.setdefault(entry["metric_group"], []).append(entry)
    return grouped


class FetchAllOkTests(unittest.TestCase):
    def test_all_sources_ok(self):
        fetcher = _make_fetcher()
        with mock.patch.object(
                msf, "_akshare_call_with_timeout",
                new=_route_pools()):
            result = fetcher.fetch_all(TRADE_DATE, PREV_TRADE_DATE)

        self.assertIsNotNone(result["stats"])
        self.assertIsNotNone(result["sector_rankings"])
        for key in ("today_pool", "prev_pool", "broken_pool", "limit_down_pool",
                    "previous_pool"):
            self.assertIsInstance(result[key], pd.DataFrame, key)

        trace = result["provider_trace"]
        statuses = {(e["metric_group"], e["api"]): e["status"] for e in trace}
        self.assertEqual(
            {e["status"] for e in trace}, {"ok"})
        # every metric group has at least one trace entry
        self.assertEqual(
            {e["metric_group"] for e in trace},
            {"breadth", "turnover", "limit_up_pool", "broken_pool",
             "promotion", "prev_feedback", "sector"},
        )
        # reused calls recorded under their real API names
        self.assertIn(("breadth", "AkshareFetcher.get_market_stats"), statuses)
        self.assertIn(("sector", "AkshareFetcher.get_sector_rankings"), statuses)
        # pool call params carry the akshare-native dates
        for entry in trace:
            self.assertIsNotNone(entry["fetched_at"])
            self.assertIsInstance(entry["elapsed_ms"], int)
            self.assertIsNone(entry["error"])
            if entry["api"].startswith("ak.stock_zt_pool"):
                self.assertIn("date", entry["params"])

    def test_previous_em_uses_trade_date_prev_pool_uses_prev_date(self):
        fetcher = _make_fetcher()
        calls = []

        def spy(func, *args, timeout=None, call_name="akshare", **kwargs):
            calls.append((call_name, dict(kwargs)))
            return _pool_df()

        with mock.patch.object(msf, "_akshare_call_with_timeout", new=spy):
            fetcher.fetch_all(TRADE_DATE, PREV_TRADE_DATE)

        zt_calls = [c for c in calls if c[0] == "ak.stock_zt_pool_em"]
        self.assertEqual(
            [c[1]["date"] for c in zt_calls],
            [TRADE_DATE, PREV_TRADE_DATE],
        )
        prev_calls = [c for c in calls if c[0] == "ak.stock_zt_pool_previous_em"]
        self.assertEqual(len(prev_calls), 1)
        self.assertEqual(prev_calls[0][1]["date"], TRADE_DATE)

    def test_prev_trade_date_none_skips_prev_pool_only(self):
        """previous_em(date=trade_date) is self-contained (W1 reconciliation),
        so only the previous-day zt_pool call is skipped."""
        fetcher = _make_fetcher()
        calls = []

        def spy(func, *args, timeout=None, call_name="akshare", **kwargs):
            calls.append((call_name, dict(kwargs)))
            return _pool_df()

        with mock.patch.object(msf, "_akshare_call_with_timeout", new=spy):
            result = fetcher.fetch_all(TRADE_DATE, None)

        prev_zt_dates = [kw["date"] for name, kw in calls
                         if name == "ak.stock_zt_pool_em"]
        self.assertEqual(prev_zt_dates, [TRADE_DATE])  # only today's pool fetched
        self.assertIsNone(result["prev_pool"])
        # previous_em still fetched with the trade date
        self.assertIsInstance(result["previous_pool"], pd.DataFrame)
        prev_calls = [c for c in calls if c[0] == "ak.stock_zt_pool_previous_em"]
        self.assertEqual(len(prev_calls), 1)
        self.assertEqual(prev_calls[0][1]["date"], TRADE_DATE)


class FetchAllFailOpenTests(unittest.TestCase):
    def test_today_pool_timeout_isolates_limit_up_and_broken_groups(self):
        fetcher = _make_fetcher()
        routing = _route_pools(by_call_and_date={
            ("ak.stock_zt_pool_em", TRADE_DATE): TimeoutError("45s exceeded"),
        })
        with mock.patch.object(msf, "_akshare_call_with_timeout", new=routing):
            result = fetcher.fetch_all(TRADE_DATE, PREV_TRADE_DATE)

        self.assertIsNone(result["today_pool"])
        # prev-day zt_pool call (same API, different date) unaffected
        self.assertIsInstance(result["prev_pool"], pd.DataFrame)
        self.assertIsInstance(result["limit_down_pool"], pd.DataFrame)
        grouped = _trace_groups(result)
        for group in ("limit_up_pool", "broken_pool"):
            timeouts = [e for e in grouped[group]
                        if e["api"] == "ak.stock_zt_pool_em"]
            self.assertTrue(timeouts, group)
            self.assertEqual({e["status"] for e in timeouts}, {"timeout"}, group)
            self.assertIn("45s", timeouts[0]["error"])
        ok_groups = {e["metric_group"] for e in result["provider_trace"]
                     if e["status"] == "ok"}
        self.assertIn("promotion", ok_groups)
        self.assertIn("prev_feedback", ok_groups)

    def test_broken_pool_exception_marks_error(self):
        fetcher = _make_fetcher()
        routing = _route_pools(by_call_name={
            "ak.stock_zt_pool_zbgc_em": RuntimeError("boom"),
        })
        with mock.patch.object(msf, "_akshare_call_with_timeout", new=routing):
            result = fetcher.fetch_all(TRADE_DATE, PREV_TRADE_DATE)

        self.assertIsNone(result["broken_pool"])
        self.assertIsInstance(result["today_pool"], pd.DataFrame)
        entries = [e for e in result["provider_trace"]
                   if e["api"] == "ak.stock_zt_pool_zbgc_em"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["metric_group"], "broken_pool")
        self.assertEqual(entries[0]["status"], "error")
        self.assertIn("boom", entries[0]["error"])

    def test_limit_down_pool_empty_df_is_ok_zero(self):
        """Empty dtgc pool is a valid market state (0 limit-down), not missing."""
        fetcher = _make_fetcher()
        routing = _route_pools(by_call_name={
            "ak.stock_zt_pool_dtgc_em": _empty_pool_df(),
        })
        with mock.patch.object(msf, "_akshare_call_with_timeout", new=routing):
            result = fetcher.fetch_all(TRADE_DATE, PREV_TRADE_DATE)

        df = result["limit_down_pool"]
        self.assertIsInstance(df, pd.DataFrame)
        self.assertTrue(df.empty)
        entries = [e for e in result["provider_trace"]
                   if e["api"] == "ak.stock_zt_pool_dtgc_em"]
        self.assertEqual(entries[0]["status"], "ok")

    def test_prev_pool_empty_df_marks_empty(self):
        """Beyond-retention prev-date returns a silent empty DF (W1 probe1b):
        judged by row count, groups recorded empty and data handed back None."""
        fetcher = _make_fetcher()
        routing = _route_pools(by_call_and_date={
            ("ak.stock_zt_pool_em", PREV_TRADE_DATE): _empty_pool_df(),
        })
        with mock.patch.object(msf, "_akshare_call_with_timeout", new=routing):
            result = fetcher.fetch_all(TRADE_DATE, PREV_TRADE_DATE)

        self.assertIsNone(result["prev_pool"])
        grouped = _trace_groups(result)
        for group in ("promotion", "prev_feedback"):
            empties = [e for e in grouped[group] if e["api"] == "ak.stock_zt_pool_em"]
            self.assertTrue(empties, group)
            self.assertEqual({e["status"] for e in empties}, {"empty"}, group)
            self.assertIsNone(empties[0]["error"])
        # today pool unaffected
        self.assertIsInstance(result["today_pool"], pd.DataFrame)

    def test_previous_em_empty_df_marks_empty(self):
        fetcher = _make_fetcher()
        routing = _route_pools(by_call_name={
            "ak.stock_zt_pool_previous_em": _empty_pool_df(),
        })
        with mock.patch.object(msf, "_akshare_call_with_timeout", new=routing):
            result = fetcher.fetch_all(TRADE_DATE, PREV_TRADE_DATE)

        self.assertIsNone(result["previous_pool"])
        entries = [e for e in result["provider_trace"]
                   if e["api"] == "ak.stock_zt_pool_previous_em"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["metric_group"], "prev_feedback")
        self.assertEqual(entries[0]["status"], "empty")

    def test_stats_none_marks_breadth_and_turnover_error(self):
        fetcher = _make_fetcher(stats=None)
        with mock.patch.object(
                msf, "_akshare_call_with_timeout", new=_route_pools()):
            result = fetcher.fetch_all(TRADE_DATE, PREV_TRADE_DATE)

        self.assertIsNone(result["stats"])
        grouped = _trace_groups(result)
        for group in ("breadth", "turnover"):
            self.assertEqual(
                {e["status"] for e in grouped[group]}, {"error"}, group)
        self.assertIn("limit_up_pool", grouped)
        self.assertEqual({e["status"] for e in grouped["limit_up_pool"]}, {"ok"})

    def test_rankings_none_marks_sector_error(self):
        fetcher = _make_fetcher(rankings=None)
        with mock.patch.object(
                msf, "_akshare_call_with_timeout", new=_route_pools()):
            result = fetcher.fetch_all(TRADE_DATE, PREV_TRADE_DATE)

        self.assertIsNone(result["sector_rankings"])
        grouped = _trace_groups(result)
        self.assertEqual({e["status"] for e in grouped["sector"]}, {"error"})

    def test_fetch_all_never_raises_when_everything_fails(self):
        fetcher = _make_fetcher(stats=None, rankings=None)
        routing = _route_pools(by_call_name={
            "ak.stock_zt_pool_em": TimeoutError("t/o"),
            "ak.stock_zt_pool_zbgc_em": ValueError("v"),
            "ak.stock_zt_pool_dtgc_em": KeyError("k"),
            "ak.stock_zt_pool_previous_em": RuntimeError("r"),
        })
        with mock.patch.object(msf, "_akshare_call_with_timeout", new=routing):
            result = fetcher.fetch_all(TRADE_DATE, PREV_TRADE_DATE)

        for key in ("stats", "sector_rankings", "today_pool", "prev_pool",
                    "broken_pool", "limit_down_pool", "previous_pool"):
            self.assertIsNone(result[key], key)
        statuses = {(e["metric_group"], e["api"]): e["status"]
                    for e in result["provider_trace"]}
        self.assertEqual(statuses[("limit_up_pool", "ak.stock_zt_pool_em")], "timeout")
        self.assertEqual(statuses[("broken_pool", "ak.stock_zt_pool_zbgc_em")], "error")
        self.assertEqual(statuses[("prev_feedback", "ak.stock_zt_pool_previous_em")], "error")

    def test_trace_entry_shape(self):
        fetcher = _make_fetcher()
        with mock.patch.object(
                msf, "_akshare_call_with_timeout", new=_route_pools()):
            result = fetcher.fetch_all(TRADE_DATE, PREV_TRADE_DATE)
        entry = result["provider_trace"][0]
        self.assertEqual(
            sorted(entry.keys()),
            ["api", "elapsed_ms", "error", "fetched_at", "metric_group",
             "params", "provider", "status"],
        )
        self.assertEqual(entry["provider"], "akshare")
        self.assertEqual(entry["status"], "ok")


class DefaultConstructionTests(unittest.TestCase):
    def test_default_wraps_real_akshare_fetcher(self):
        fetcher = msf.MarketSentimentFetcher()
        self.assertEqual(fetcher._ak.name, "AkshareFetcher")
        self.assertEqual(fetcher.timeout_seconds, msf.DEFAULT_POOL_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
