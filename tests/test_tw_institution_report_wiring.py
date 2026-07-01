# -*- coding: utf-8 -*-
"""v2 report-wiring tests: tw 三大法人 (institutional flows) into the offshore institution block.

Pins the maintainer-confirmed contract for issue #1777 v2:
  - tw with data        -> institution coverage 'ok', raw net figures surfaced.
  - tw fetch-failed/None -> institution stays 'not_supported' (fail-open, main flow alive).
  - us/hk/jp/kr          -> institution stays 'not_supported' AND the tw fetcher is never
                            called (strictly-additive: other markets byte-identical).
  - tw institution data carries RAW figures only — no capital_flow_signal / score / schema.

Mirrors tests/test_fundamental_context.py's offshore pattern; fully offline (no network),
so it runs under the blocking backend gate (`pytest -m "not network"`).
"""

import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.base import DataFetcherManager

_TW_FETCHER_METHOD = (
    "data_provider.tw_institutional_fetcher.TwInstitutionalFetcher.get_institutional_net"
)

# Shape mirrors TwInstitutionalFetcher._build_record (real 2330 @ 20260629).
_FAKE_REC = {
    "stock_code": "2330",
    "date": "20260629",
    "market": "上市",
    "source": "TWSE-T86",
    "unit": "shares",
    "foreign_net": -1912490,
    "trust_net": 919216,
    "dealer_net": 996850,
    "total_net": 3576,
}

_OFFSHORE_CFG = SimpleNamespace(
    enable_fundamental_pipeline=True,
    fundamental_cache_ttl_seconds=0,
    fundamental_stage_timeout_seconds=1.5,
    fundamental_fetch_timeout_seconds=0.8,
    fundamental_retry_max=1,
)

_EMPTY_BUNDLE = {
    "status": "not_supported",
    "growth": {},
    "earnings": {},
    "belong_boards": [],
    "source_chain": [],
    "errors": [],
}


class TestTwInstitutionReportWiring(unittest.TestCase):
    def _context(self, code, institutional_return=None, institutional_side_effect=None):
        """Run get_fundamental_context(code) offline; returns (ctx, tw_fetcher_mock)."""
        manager = DataFetcherManager(fetchers=[])
        kwargs = {}
        if institutional_side_effect is not None:
            kwargs["side_effect"] = institutional_side_effect
        else:
            kwargs["return_value"] = institutional_return
        with patch("src.config.get_config", return_value=_OFFSHORE_CFG), \
                patch.object(manager, "get_realtime_quote", return_value=None), \
                patch(
                    "data_provider.yfinance_fundamental_adapter.YfinanceFundamentalAdapter.get_fundamental_bundle",
                    return_value=_EMPTY_BUNDLE,
                ), \
                patch(_TW_FETCHER_METHOD, **kwargs) as tw_mock:
            ctx = manager.get_fundamental_context(code)
        return ctx, tw_mock

    # ---- tw with data: institution surfaces the raw net figures --------------------
    def test_tw_institution_populated_when_fetcher_has_data(self):
        ctx, tw_mock = self._context("2330.TW", institutional_return=dict(_FAKE_REC))
        self.assertEqual(ctx["market"], "tw")
        self.assertEqual(ctx["coverage"].get("institution"), "ok")
        data = ctx["institution"]["data"]
        self.assertEqual(data["foreign_net"], -1912490)
        self.assertEqual(data["trust_net"], 919216)
        self.assertEqual(data["dealer_net"], 996850)
        self.assertEqual(data["total_net"], 3576)
        self.assertEqual(data["unit"], "shares")
        self.assertEqual(data["source"], "TWSE-T86")
        # other offshore blocks untouched
        for block in ("capital_flow", "dragon_tiger", "boards"):
            self.assertEqual(ctx["coverage"].get(block), "not_supported")
        # institution data must surface: the top-level status (which consumers key off)
        # is not 'not_supported' even though valuation/growth/earnings are unavailable.
        self.assertNotEqual(ctx["status"], "not_supported")
        tw_mock.assert_called_with("2330.TW")

    # ---- tw genuine-zero day is kept (record present, nets 0) ----------------------
    def test_tw_institution_keeps_genuine_zero(self):
        zero_rec = dict(_FAKE_REC, foreign_net=0, trust_net=0, dealer_net=0, total_net=0)
        ctx, _ = self._context("6488.TWO", institutional_return=zero_rec)
        self.assertEqual(ctx["coverage"].get("institution"), "ok")
        self.assertEqual(ctx["institution"]["data"]["foreign_net"], 0)
        self.assertEqual(ctx["institution"]["data"]["total_net"], 0)

    # ---- tw fail-open: None -> not_supported, no raise -----------------------------
    def test_tw_institution_fail_open_when_fetcher_returns_none(self):
        ctx, _ = self._context("2330.TW", institutional_return=None)
        self.assertEqual(ctx["coverage"].get("institution"), "not_supported")
        self.assertEqual(ctx["institution"].get("data"), {})

    # ---- tw fail-open: fetcher raises -> not_supported, main flow uninterrupted -----
    def test_tw_institution_fail_open_when_fetcher_raises(self):
        ctx, _ = self._context("2330.TW", institutional_side_effect=RuntimeError("boom"))
        self.assertEqual(ctx["coverage"].get("institution"), "not_supported")
        self.assertEqual(ctx["institution"].get("data"), {})
        # the rest of the context still built (no exception bubbled out)
        self.assertEqual(ctx["market"], "tw")

    # ---- strictly-additive: us is byte-identical AND the tw fetcher is never called -
    def test_us_institution_unchanged_and_tw_fetcher_not_called(self):
        ctx, tw_mock = self._context("AAPL", institutional_return=dict(_FAKE_REC))
        self.assertEqual(ctx["market"], "us")
        self.assertEqual(ctx["coverage"].get("institution"), "not_supported")
        self.assertEqual(ctx["institution"].get("data"), {})
        self.assertEqual(tw_mock.call_count, 0)

    # ---- B2: every other offshore market (hk/jp/kr) untouched + fetcher unused ------
    def test_other_offshore_markets_institution_unchanged(self):
        for code, market in (("0700.HK", "hk"), ("7203.T", "jp"), ("005930.KS", "kr")):
            ctx, tw_mock = self._context(code, institutional_return=dict(_FAKE_REC))
            self.assertEqual(ctx["market"], market, f"{code} routed to {ctx['market']}")
            self.assertEqual(ctx["coverage"].get("institution"), "not_supported")
            self.assertEqual(tw_mock.call_count, 0)

    # ---- fail-open on a fetcher WIRING/init failure (not just a fetch failure) ------
    def test_tw_institution_fail_open_when_fetcher_init_raises(self):
        manager = DataFetcherManager(fetchers=[])
        with patch("src.config.get_config", return_value=_OFFSHORE_CFG), \
                patch.object(manager, "get_realtime_quote", return_value=None), \
                patch(
                    "data_provider.yfinance_fundamental_adapter.YfinanceFundamentalAdapter.get_fundamental_bundle",
                    return_value=_EMPTY_BUNDLE,
                ), \
                patch(
                    "data_provider.tw_institutional_fetcher.TwInstitutionalFetcher",
                    side_effect=RuntimeError("init boom"),
                ):
            ctx = manager.get_fundamental_context("2330.TW")  # must NOT raise
        self.assertEqual(ctx["market"], "tw")
        self.assertEqual(ctx["coverage"].get("institution"), "not_supported")
        self.assertEqual(ctx["institution"].get("data"), {})

    # ---- a record missing a core net field is NOT shown as a clean 'ok' -------------
    def test_tw_institution_not_ok_when_core_net_missing(self):
        broken = dict(_FAKE_REC, foreign_net=None)  # a core component missing
        ctx, _ = self._context("2330.TW", institutional_return=broken)
        self.assertEqual(ctx["coverage"].get("institution"), "not_supported")
        self.assertEqual(ctx["institution"].get("data"), {})

    # ---- a slow fetch must NOT push the analysis past the fundamental stage budget ---
    def test_tw_institution_fetch_respects_stage_timeout(self):
        slow_cfg = SimpleNamespace(
            enable_fundamental_pipeline=True,
            fundamental_cache_ttl_seconds=0,
            fundamental_stage_timeout_seconds=0.3,
            fundamental_fetch_timeout_seconds=0.3,
            fundamental_retry_max=1,
        )
        manager = DataFetcherManager(fetchers=[])

        def _slow(_code):
            time.sleep(2.0)  # simulate a slow / rate-limited TWSE-TPEx call
            return dict(_FAKE_REC)

        start = time.time()
        with patch("src.config.get_config", return_value=slow_cfg), \
                patch.object(manager, "get_realtime_quote", return_value=None), \
                patch(
                    "data_provider.yfinance_fundamental_adapter.YfinanceFundamentalAdapter.get_fundamental_bundle",
                    return_value=_EMPTY_BUNDLE,
                ), \
                patch(_TW_FETCHER_METHOD, side_effect=_slow):
            ctx = manager.get_fundamental_context("2330.TW")
        elapsed = time.time() - start
        # the 2s fetch must be abandoned at the ~0.3s stage budget, not block the analysis
        self.assertLess(elapsed, 1.5, f"institution fetch ignored the stage timeout ({elapsed:.2f}s)")
        self.assertEqual(ctx["coverage"].get("institution"), "not_supported")

    # ---- negative: institution data carries RAW figures only, no derived signal ----
    def test_tw_institution_data_has_no_derived_signal_or_score(self):
        ctx, _ = self._context("2330.TW", institutional_return=dict(_FAKE_REC))
        data = ctx["institution"]["data"]
        self.assertEqual(
            set(data.keys()),
            {"foreign_net", "trust_net", "dealer_net", "total_net", "unit", "date", "source"},
        )
        forbidden = ("capital_flow_signal", "signal", "score", "weight", "normalized", "rating")
        for key in forbidden:
            self.assertNotIn(key, data, f"derived key '{key}' leaked into institution data")


    # ---- institution must use the STAGE budget, not the small per-symbol fetch cap -----
    def test_tw_institution_not_starved_by_small_fetch_timeout(self):
        # The 三大法人 block is a whole-market download (~4-5s). It must run under the
        # remaining STAGE budget, not the (small) per-symbol fetch_timeout — otherwise the
        # first/only stock of a run coin-flips to not_supported. A fetch slower than
        # fetch_timeout but within the stage budget must still land as 'ok'.
        cfg = SimpleNamespace(
            enable_fundamental_pipeline=True,
            fundamental_cache_ttl_seconds=0,
            fundamental_stage_timeout_seconds=8.0,   # generous stage budget
            fundamental_fetch_timeout_seconds=0.3,   # tiny per-symbol cap (would starve institution)
            fundamental_retry_max=1,
        )
        manager = DataFetcherManager(fetchers=[])

        def _slowish(_code):
            time.sleep(1.0)  # > fetch_timeout(0.3) but << stage budget(8) -> must complete
            return dict(_FAKE_REC)

        with patch("src.config.get_config", return_value=cfg), \
                patch.object(manager, "get_realtime_quote", return_value=None), \
                patch(
                    "data_provider.yfinance_fundamental_adapter.YfinanceFundamentalAdapter.get_fundamental_bundle",
                    return_value=_EMPTY_BUNDLE,
                ), \
                patch(_TW_FETCHER_METHOD, side_effect=_slowish):
            ctx = manager.get_fundamental_context("2330.TW")
        self.assertEqual(ctx["coverage"].get("institution"), "ok")
        self.assertEqual(ctx["institution"]["data"]["total_net"], _FAKE_REC["total_net"])

    # ---- FUNDAMENTAL_FETCH_TIMEOUT_SECONDS=0 disables per-fetch fetches — incl institution
    def test_tw_institution_disabled_when_fetch_timeout_zero(self):
        # fetch_timeout=0 is the existing "disable per-fetch fundamental fetches" config
        # (valuation/bundle skip). Institution must honour it too, not bypass it via the
        # stage budget.
        cfg = SimpleNamespace(
            enable_fundamental_pipeline=True,
            fundamental_cache_ttl_seconds=0,
            fundamental_stage_timeout_seconds=8.0,
            fundamental_fetch_timeout_seconds=0.0,   # disabled
            fundamental_retry_max=1,
        )
        manager = DataFetcherManager(fetchers=[])
        with patch("src.config.get_config", return_value=cfg), \
                patch.object(manager, "get_realtime_quote", return_value=None), \
                patch(
                    "data_provider.yfinance_fundamental_adapter.YfinanceFundamentalAdapter.get_fundamental_bundle",
                    return_value=_EMPTY_BUNDLE,
                ), \
                patch(_TW_FETCHER_METHOD, return_value=dict(_FAKE_REC)) as tw_mock:
            ctx = manager.get_fundamental_context("2330.TW")
        self.assertEqual(ctx["coverage"].get("institution"), "not_supported")
        self.assertEqual(tw_mock.call_count, 0)  # institution fetch skipped when disabled


if __name__ == "__main__":
    unittest.main()
