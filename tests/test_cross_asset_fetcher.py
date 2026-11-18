# -*- coding: utf-8 -*-
"""Fetcher mock matrix for CrossAssetFetcher (Issue #1910, PR #2428 r2).

No network: the yfinance seam (``CrossAssetFetcher._fetch_yf_series``) is
patched. Phase-1 provider scope is yfinance-only — global indices
(hk/us/jp/kr/tw + cn FTSE-A50 best-effort), VIX (volatility) and US 10Y
(rates); FX / commodities / crypto providers, the akshare CN index batch and
the portfolio FX cache channel are deferred to a later PR and their groups
stay empty (never fabricated).

Covered acceptance paths:
- T2 success — hk/us snapshots carry every group; every item has the
  mandatory ``source`` / ``as_of`` / ``stale`` / ``error`` quadruple;
- T3 missing — provider returns no data -> ``status="not_supported"``, no raise;
- T4 stale — ``as_of`` older than the threshold -> ``stale=True`` for that item
  only, siblings unaffected;
- T5 provider exception — provider raises -> ``error`` records the exception
  type, ``fetch_market_snapshot`` still returns the normal structure.
Retained review-fix regressions: ^TNX percent passthrough (OR-COR-7bbac105),
pandas index-label ``as_of`` coercion (OR-COR-ce1b6a21), call-stack-local
budget deadline (concurrent-fetch isolation).
"""

from __future__ import annotations

import itertools
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Dict, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from data_provider.cross_asset_fetcher import CrossAssetFetcher, _change_pct
from src.schemas.cross_asset_context import CROSS_ASSET_GROUPS

TRADE_DATE = date(2026, 10, 22)
FRESH_AS_OF = TRADE_DATE
OLD_AS_OF = TRADE_DATE - timedelta(days=5)

# Phase-1 defers fx/commodities/crypto providers: their groups stay empty.
_PHASE1_EMPTY_GROUPS = ("fx", "commodities", "crypto")


def _fake_yf_series(
    table: Dict[str, Optional[Tuple[date, float, float]]],
    default: Optional[Tuple[date, float, float]] = None,
):
    """Build a ``_fetch_yf_series`` stand-in driven by a symbol->series table.

    OR-COR-d20b0d9f: the seam now receives ``(symbol, trade_date)``; the
    table-driven stand-in ignores the target date (the REAL seam's
    target-date alignment is covered by ``TestTargetDateAlignment`` via the
    pandas stub).
    """

    def _fetch(
        symbol: str, trade_date: Optional[date] = None
    ) -> Optional[Tuple[date, float, float]]:
        if symbol in table:
            return table[symbol]
        return default

    return _fetch


def _patch_yf(table, default=None):
    """Patch the static yfinance seam for the duration of a test."""

    return patch.object(
        CrossAssetFetcher,
        "_fetch_yf_series",
        new=staticmethod(_fake_yf_series(table, default)),
    )


def _assert_quadruple(item) -> None:
    """Every item must carry the data-quality quadruple (issue #1910)."""

    payload = item.model_dump()
    for key in ("source", "as_of", "stale", "error"):
        assert key in payload
    if item.status == "ok":
        assert item.source, "ok item must record its source"
        assert item.as_of, "ok item must record its as_of"
        assert isinstance(item.stale, bool)
        assert item.error is None
    else:
        assert item.error, f"{item.status} item must explain itself via error"


class TestSuccessMarkets:
    """T2 — success: structure + quality quadruple on every item."""

    def test_cn_snapshot_via_yfinance_best_effort_a50(self):
        # Phase 1 has no akshare CN batch: cn indices are the best-effort
        # FTSE A50 yfinance row; rates/VIX come from the same channel.
        table = {
            "CHA50CFD": (FRESH_AS_OF, 13250.0, 13310.0),
            "^VIX": (FRESH_AS_OF, 16.5, 15.8),
            # OR-COR-7bbac105: Yahoo Close is ALREADY a percent quantity
            # (4.21 = 4.21%); it must pass through unscaled.
            "^TNX": (FRESH_AS_OF, 4.21, 4.15),
        }
        fetcher = CrossAssetFetcher()
        with _patch_yf(table):
            snapshot = fetcher.fetch_market_snapshot("cn", TRADE_DATE)

        assert set(snapshot.keys()) == set(CROSS_ASSET_GROUPS)
        assert snapshot["indices"]["CHA50CFD"].status == "ok"
        assert snapshot["indices"]["CHA50CFD"].value == pytest.approx(13250.0)
        for group in _PHASE1_EMPTY_GROUPS:
            assert snapshot[group] == {}
        # US 10Y (^TNX) passes through as the percent yield Yahoo already quotes
        assert snapshot["rates"]["US10Y"].status == "ok"
        assert snapshot["rates"]["US10Y"].value == pytest.approx(4.21, abs=0.001)
        _assert_quadruple(snapshot["rates"]["US10Y"])
        # VIX ok item carries the quadruple too
        assert snapshot["volatility"]["VIX"].status == "ok"
        assert snapshot["volatility"]["VIX"].stale is False
        _assert_quadruple(snapshot["volatility"]["VIX"])

    def test_hk_snapshot_via_yfinance(self):
        table = {
            "^HSI": (FRESH_AS_OF, 24000.0, 24300.0),
            "HSTECH.HK": (FRESH_AS_OF, 5300.0, 5250.0),
            "^HSCE": (FRESH_AS_OF, 8600.0, 8550.0),
            "^VIX": (FRESH_AS_OF, 17.0, 16.0),
        }
        fetcher = CrossAssetFetcher()
        with _patch_yf(table):
            snapshot = fetcher.fetch_market_snapshot("hk", TRADE_DATE)

        assert snapshot["indices"]["HSI"].status == "ok"
        assert snapshot["indices"]["HSI"].value == pytest.approx(24000.0)
        assert snapshot["indices"]["HSI"].change_pct == pytest.approx(-1.23, abs=0.01)
        assert snapshot["indices"]["HSTECH"].change_pct == pytest.approx(0.95, abs=0.01)
        for group in CROSS_ASSET_GROUPS:
            if group in _PHASE1_EMPTY_GROUPS:
                assert snapshot[group] == {}
                continue
            for item in snapshot[group].values():
                _assert_quadruple(item)

    def test_us_snapshot_via_yfinance(self):
        table = {
            "^GSPC": (FRESH_AS_OF, 5800.0, 5760.0),
            "^IXIC": (FRESH_AS_OF, 18500.0, 18400.0),
            "^DJI": (FRESH_AS_OF, 43200.0, 43300.0),
            "^VIX": (FRESH_AS_OF, 17.0, 16.0),
            "^TNX": (FRESH_AS_OF, 4.21, 4.15),
        }
        fetcher = CrossAssetFetcher()
        with _patch_yf(table):
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        assert {key for key in snapshot["indices"]} == {"SPX", "IXIC", "DJI"}
        assert snapshot["indices"]["IXIC"].change_pct == pytest.approx(0.54, abs=0.01)
        for group in CROSS_ASSET_GROUPS:
            if group in _PHASE1_EMPTY_GROUPS:
                assert snapshot[group] == {}
                continue
            for item in snapshot[group].values():
                _assert_quadruple(item)


class TestMissingData:
    """T3 — provider returns nothing -> not_supported, never raises."""

    def test_empty_provider_yields_not_supported_without_raise(self):
        fetcher = CrossAssetFetcher()
        with _patch_yf({}):  # every yfinance symbol: no data
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        assert set(snapshot.keys()) == set(CROSS_ASSET_GROUPS)
        for item in snapshot["indices"].values():
            assert item.status == "not_supported"
            assert item.error == "no_data"
            _assert_quadruple(item)
        # deferred groups stay empty (never fabricated)
        for group in _PHASE1_EMPTY_GROUPS:
            assert snapshot[group] == {}
        assert snapshot["rates"]["US10Y"].status == "not_supported"

    def test_unknown_market_falls_back_to_cn_without_raise(self):
        fetcher = CrossAssetFetcher(timeout_seconds=2, stale_days=2)
        with _patch_yf({}):
            snapshot = fetcher.fetch_market_snapshot("mars", TRADE_DATE)

        assert set(snapshot.keys()) == set(CROSS_ASSET_GROUPS)


class TestStaleMarking:
    """T4 — stale threshold flags only the offending item."""

    def test_stale_item_marked_and_sibling_unaffected(self):
        table = {
            "^GSPC": (OLD_AS_OF, 5800.0, 5760.0),  # 5 natural days old -> stale
            "^IXIC": (FRESH_AS_OF, 18500.0, 18400.0),  # fresh sibling
        }
        fetcher = CrossAssetFetcher()
        with _patch_yf(table):
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        assert snapshot["indices"]["SPX"].stale is True
        assert snapshot["indices"]["SPX"].as_of == OLD_AS_OF.isoformat()
        assert snapshot["indices"]["SPX"].status == "ok"  # stale data stays usable
        assert snapshot["indices"]["IXIC"].stale is False
        assert snapshot["indices"]["IXIC"].status == "ok"
        _assert_quadruple(snapshot["indices"]["SPX"])
        _assert_quadruple(snapshot["indices"]["IXIC"])

    def test_rates_use_stricter_threshold_than_default(self):
        two_days_old = TRADE_DATE - timedelta(days=2)
        table = {"^TNX": (two_days_old, 4.21, 4.15), "^VIX": (two_days_old, 17.0, 16.0)}
        fetcher = CrossAssetFetcher(stale_days=2)
        with _patch_yf(table):
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        # rates: trading-day+1 threshold -> 2 days old is stale
        assert snapshot["rates"]["US10Y"].stale is True
        # volatility: default 2-day threshold -> exactly 2 days is not yet stale
        assert snapshot["volatility"]["VIX"].stale is False


class TestProviderException:
    """T5 — provider raise -> error recorded, normal structure returned."""

    def test_yfinance_raise_becomes_item_error(self):
        table = {"^IXIC": (FRESH_AS_OF, 18500.0, 18400.0)}

        def _boom(symbol: str):
            raise RuntimeError("yfinance exploded")

        fetcher = CrossAssetFetcher()
        with patch.object(
            CrossAssetFetcher,
            "_fetch_yf_series",
            new=staticmethod(
                lambda symbol, trade_date=None: (
                    table[symbol] if symbol in table else (_boom(symbol) or None)
                )
            ),
        ):
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        # failing symbol recorded, function still returned the full structure
        assert snapshot["indices"]["SPX"].status == "error"
        assert "RuntimeError" in snapshot["indices"]["SPX"].error
        assert snapshot["indices"]["SPX"].source  # quadruple still filled
        # sibling keeps working — one provider failure never blocks the group
        assert snapshot["indices"]["IXIC"].status == "ok"
        assert snapshot["indices"]["IXIC"].change_pct == pytest.approx(0.54, abs=0.01)
        for group in CROSS_ASSET_GROUPS:
            assert isinstance(snapshot[group], dict)


class TestTnxNoDoubleScaling:
    """OR-COR-7bbac105 — ^TNX Close from Yahoo is already quoted in percent
    (4.21 = 4.21%); the former unconditional ``value / 10`` reported a yield
    ten times too small."""

    def test_tnx_close_passes_through_unscaled(self):
        fetcher = CrossAssetFetcher()
        with _patch_yf({"^TNX": (FRESH_AS_OF, 4.21, 4.15)}):
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        item = snapshot["rates"]["US10Y"]
        assert item.status == "ok"
        assert item.value == pytest.approx(4.21, abs=0.0001)
        # change_pct is computed from the raw closes: (4.21-4.15)/4.15*100
        assert item.change_pct == pytest.approx(1.45, abs=0.01)

    def test_high_yield_regime_also_passes_through(self):
        fetcher = CrossAssetFetcher()
        with _patch_yf({"^TNX": (FRESH_AS_OF, 4.995, 4.98)}):
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        assert snapshot["rates"]["US10Y"].value == pytest.approx(4.995, abs=0.0001)


class TestYfSeriesTimestampCoercion:
    """OR-COR-ce1b6a21 — the real pandas DatetimeIndex label must flow through
    the REAL ``_fetch_yf_series`` (only yfinance itself is stubbed) and come
    out as a date; the former ``getattr(last_index, "date", last_index)`` handed
    the bound method to the converter so every yfinance success was
    ``as_of=None`` / ``stale=True``."""

    @staticmethod
    def _yf_stub(frame):
        return SimpleNamespace(
            Ticker=lambda symbol: SimpleNamespace(
                history=lambda period=None, auto_adjust=None: frame
            )
        )

    def test_real_datetime_index_yields_as_of_date(self):
        import pandas as pd

        frame = pd.DataFrame(
            {"Close": [41.9, 42.7]},
            index=pd.DatetimeIndex(["2026-10-21", "2026-10-22"]),
        )
        with patch.dict(sys.modules, {"yfinance": self._yf_stub(frame)}):
            series = CrossAssetFetcher._fetch_yf_series("^GSPC", TRADE_DATE)

        assert series is not None
        as_of, last, prev = series
        assert as_of == date(2026, 10, 22)
        assert last == pytest.approx(42.7)
        assert prev == pytest.approx(41.9)

    def test_string_index_still_parses(self):
        import pandas as pd

        frame = pd.DataFrame(
            {"Close": [5800.0, 5810.0]},
            index=["2026-10-21", "2026-10-22"],
        )
        with patch.dict(sys.modules, {"yfinance": self._yf_stub(frame)}):
            series = CrossAssetFetcher._fetch_yf_series("^GSPC", TRADE_DATE)

        assert series is not None
        as_of, last, _prev = series
        assert as_of == date(2026, 10, 22)
        assert last == pytest.approx(5810.0)

    def test_snapshot_ok_item_carries_as_of_and_is_not_falsely_stale(self):
        import pandas as pd

        frame = pd.DataFrame(
            {"Close": [41.9, 42.7]},
            index=pd.DatetimeIndex(["2026-10-21", "2026-10-22"]),
        )
        fetcher = CrossAssetFetcher()
        with patch.dict(sys.modules, {"yfinance": self._yf_stub(frame)}):
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        item = snapshot["rates"]["US10Y"]
        assert item.status == "ok"
        assert item.as_of == "2026-10-22"  # was None before the fix
        assert item.stale is False  # was True-by-None before the fix
        _assert_quadruple(item)


class TestBudgetDeadlineIsolation:
    """The budget deadline must be call-stack local, not instance state: the
    fetcher is a shared singleton and task_queue runs analyze_stock on a
    ThreadPoolExecutor, so an instance attribute would let concurrent fetches
    overwrite each other's deadline (issue #1910 review, minor)."""

    def test_deadline_is_not_instance_state_and_helpers_take_it_explicitly(self):
        fetcher = CrossAssetFetcher(timeout_seconds=8)
        assert not hasattr(fetcher, "_deadline")
        # helpers are dead-reckoned from an explicit deadline (old no-arg
        # signature raised TypeError here)
        assert fetcher._budget_exceeded(time.monotonic() - 1) is True
        assert fetcher._budget_exceeded(time.monotonic() + 60) is False
        assert fetcher._budget_remaining(time.monotonic() + 60) > 0

    def test_concurrent_fetches_on_shared_instance_complete_isolated(self):
        fetcher = CrossAssetFetcher(timeout_seconds=8)
        counter = itertools.count()
        counter_lock = threading.Lock()
        first_parked = threading.Event()
        release_first = threading.Event()

        def _seam(symbol: str, trade_date=None):
            with counter_lock:
                n = next(counter)
            if n == 0:
                # park the first fetch mid-group so the second overlaps it
                first_parked.set()
                release_first.wait(timeout=5)
            return (FRESH_AS_OF, 100.0, 99.0)

        with patch.object(
            CrossAssetFetcher, "_fetch_yf_series", new=staticmethod(_seam)
        ):
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_a = pool.submit(fetcher.fetch_market_snapshot, "us", TRADE_DATE)
                assert first_parked.wait(timeout=5)
                fut_b = pool.submit(fetcher.fetch_market_snapshot, "us", TRADE_DATE)
                snapshot_b = fut_b.result(timeout=15)  # must not block on A
                release_first.set()
                snapshot_a = fut_a.result(timeout=15)

        for snapshot in (snapshot_a, snapshot_b):
            assert set(snapshot.keys()) == set(CROSS_ASSET_GROUPS)
            assert snapshot["volatility"]["VIX"].status == "ok"
            for group in CROSS_ASSET_GROUPS:
                if group in _PHASE1_EMPTY_GROUPS:
                    assert snapshot[group] == {}
                    continue
                for item in snapshot[group].values():
                    _assert_quadruple(item)


class TestTargetDateAlignment:
    """OR-COR-d20b0d9f — the reader must align bar selection to the analysis
    target date (``effective_daily_bar_date`` handed in as ``trade_date``).

    The yfinance seam used to request ``period="5d"`` and take the LAST row
    while ignoring the target date: during a US Monday session (target =
    last Friday) a Monday bar was returned and stamped as fresh Friday
    context, and a frozen run targeting a past date picked execution-time
    bars. Newer-than-target data must never masquerade as target-day data,
    and a negative (trade_date - as_of) day-diff must never read as fresh.
    """

    @staticmethod
    def _yf_stub(frame):
        return SimpleNamespace(
            Ticker=lambda symbol: SimpleNamespace(
                history=lambda period=None, auto_adjust=None: frame
            )
        )

    def test_real_fetch_series_prefers_bar_on_or_before_target(self):
        import pandas as pd

        frame = pd.DataFrame(
            {"Close": [100.0, 110.0, 90.0]},
            index=pd.DatetimeIndex(
                ["2026-11-12", "2026-11-13", "2026-11-16"]
            ),  # Thu, target Fri, Monday
        )
        with patch.dict(sys.modules, {"yfinance": self._yf_stub(frame)}):
            series = CrossAssetFetcher._fetch_yf_series(
                "^GSPC", date(2026, 11, 13)
            )

        assert series is not None
        as_of, last, prev = series
        assert as_of == date(2026, 11, 13)  # Monday bar excluded
        assert last == pytest.approx(110.0)
        assert prev == pytest.approx(100.0)

    def test_snapshot_marks_target_day_bar_not_latest_bar(self):
        import pandas as pd

        frame = pd.DataFrame(
            {"Close": [100.0, 110.0, 90.0]},
            index=pd.DatetimeIndex(
                ["2026-11-12", "2026-11-13", "2026-11-16"]
            ),
        )
        fetcher = CrossAssetFetcher()
        with patch.dict(sys.modules, {"yfinance": self._yf_stub(frame)}):
            snapshot = fetcher.fetch_market_snapshot("us", date(2026, 11, 13))

        item = snapshot["indices"]["SPX"]
        assert item.status == "ok"
        assert item.as_of == "2026-11-13"  # not the Monday bar
        assert item.value == pytest.approx(110.0)
        assert item.change_pct == pytest.approx(10.0, abs=0.01)
        assert item.stale is False
        _assert_quadruple(item)

    def test_all_bars_after_target_date_degrade_to_not_supported(self):
        import pandas as pd

        frame = pd.DataFrame(
            {"Close": [90.0, 91.0]},
            index=pd.DatetimeIndex(["2026-11-16", "2026-11-17"]),
        )
        fetcher = CrossAssetFetcher()
        with patch.dict(sys.modules, {"yfinance": self._yf_stub(frame)}):
            snapshot = fetcher.fetch_market_snapshot("us", date(2026, 11, 13))

        # Every bar is newer than the target: it must NOT be presented as
        # target-day context (fail-open -> not_supported / no_data).
        for item in snapshot["indices"].values():
            assert item.status == "not_supported"
            assert item.error == "no_data"
            _assert_quadruple(item)

    def test_undatable_labels_still_degrade_via_stale(self):
        import pandas as pd

        frame = pd.DataFrame(
            {"Close": [100.0, 110.0]}, index=["not-a-date", "also-not"]
        )
        with patch.dict(sys.modules, {"yfinance": self._yf_stub(frame)}):
            series = CrossAssetFetcher._fetch_yf_series(
                "^GSPC", date(2026, 11, 13)
            )

        # Nothing datable -> original selection is kept and quality degrades
        # through as_of=None / stale=True instead of fabricating a date.
        assert series is not None
        as_of, last, _prev = series
        assert as_of is None
        assert last == pytest.approx(110.0)

    def test_future_as_of_is_stale(self):
        fetcher = CrossAssetFetcher()
        # as_of one day AFTER the target: negative age must read as stale.
        assert fetcher._is_stale(date(2026, 10, 23), date(2026, 10, 22), 1) is True
        assert fetcher._is_stale(FRESH_AS_OF, TRADE_DATE, 1) is False


class TestNonFiniteCloseRejection:
    """OR-COR-be3a04e3 — non-finite closes (NaN keeps only NaN out via
    dropna; +/-inf SURVIVES dropna) must be rejected at the data-entry seam,
    not merely skipped at render time. An inf close used to become a
    ``status="ok"`` item with ``value=inf`` / ``change_pct=inf`` that voted,
    entered the summary and quality stats, and was cached."""

    @staticmethod
    def _yf_stub(frame):
        return SimpleNamespace(
            Ticker=lambda symbol: SimpleNamespace(
                history=lambda period=None, auto_adjust=None: frame
            )
        )

    def test_inf_close_is_rejected_at_entry(self):
        import pandas as pd

        frame = pd.DataFrame(
            {"Close": [100.0, 101.0, float("inf")]},  # dropna keeps inf
            index=pd.DatetimeIndex(["2026-10-20", "2026-10-21", "2026-10-22"]),
        )
        with patch.dict(sys.modules, {"yfinance": self._yf_stub(frame)}):
            series = CrossAssetFetcher._fetch_yf_series("^GSPC", TRADE_DATE)

        assert series is None  # before the fix: (TRADE_DATE, inf, 101.0)

    def test_snapshot_surfaces_no_data_not_ok_inf_item(self):
        import pandas as pd

        frame = pd.DataFrame(
            {"Close": [100.0, 101.0, float("inf")]},
            index=pd.DatetimeIndex(["2026-10-20", "2026-10-21", "2026-10-22"]),
        )
        fetcher = CrossAssetFetcher()
        with patch.dict(sys.modules, {"yfinance": self._yf_stub(frame)}):
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        item = snapshot["indices"]["SPX"]
        assert item.status == "not_supported"
        assert item.error == "no_data"
        assert item.value is None
        _assert_quadruple(item)

    def test_non_finite_prev_close_is_rejected(self):
        import pandas as pd

        frame = pd.DataFrame(
            {"Close": [float("inf"), 101.0]},
            index=pd.DatetimeIndex(["2026-10-21", "2026-10-22"]),
        )
        with patch.dict(sys.modules, {"yfinance": self._yf_stub(frame)}):
            series = CrossAssetFetcher._fetch_yf_series("^GSPC", TRADE_DATE)

        # prev=inf would poison change_pct into inf/nan -> reject the bar pair
        assert series is None

    def test_change_pct_non_finite_returns_none(self):
        # overflow: (1e308 / 1e-308) * 100 overflows to inf
        assert _change_pct(1e308, 1e-308) is None
        assert _change_pct(float("nan"), 1.0) is None
        # finite baseline stays intact
        assert _change_pct(110.0, 100.0) == pytest.approx(10.0)


class TestBudgetExceededSurfacesTimeout:
    """An exhausted budget must surface ``error="timeout"`` on the affected
    group's items — never silently drop the group (contract rule)."""

    def test_expired_budget_marks_pending_items_as_timeout(self):
        fetcher = CrossAssetFetcher()
        timeout_group = fetcher._timeout_group_items("us", "indices", TRADE_DATE)
        assert set(timeout_group.keys()) == {"SPX", "IXIC", "DJI"}
        for item in timeout_group.values():
            assert item.status == "error"
            assert item.error == "timeout"
            _assert_quadruple(item)
