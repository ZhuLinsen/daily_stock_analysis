# -*- coding: utf-8 -*-
"""Fetcher mock matrix for CrossAssetFetcher (Issue #1910, W1-plan T2-T5).

No network: the yfinance seam (``CrossAssetFetcher._fetch_yf_series``) and the
akshare batch seam (``data_provider.akshare_fetcher._akshare_call_with_timeout``)
are patched; the portfolio FX cache is a stub repository object.

Covered acceptance paths:
- T2 success — cn/hk/us market snapshots carry every group and every item has
  the mandatory ``source`` / ``as_of`` / ``stale`` / ``error`` quadruple;
- T3 missing — provider returns no data -> ``status="not_supported"``, no raise;
- T4 stale — ``as_of`` older than the threshold -> ``stale=True`` for that item
  only, siblings unaffected;
- T5 provider exception — provider raises -> ``error`` records the exception
  type, ``fetch_market_snapshot`` still returns the normal structure.
Plus the FX cache-first contract (portfolio cache hit / stale / miss / broken).
"""

from __future__ import annotations

import itertools
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from data_provider.cross_asset_fetcher import CrossAssetFetcher
from src.config import Config
from src.repositories.portfolio_repo import PortfolioRepository
from src.schemas.cross_asset_context import CROSS_ASSET_GROUPS
from src.services.cross_asset_context_service import build_data_quality
from src.services.portfolio_service import PortfolioService
from src.storage import DatabaseManager

TRADE_DATE = date(2026, 10, 22)
FRESH_AS_OF = TRADE_DATE
OLD_AS_OF = TRADE_DATE - timedelta(days=5)


def _fake_yf_series(
    table: Dict[str, Optional[Tuple[date, float, float]]],
    default: Optional[Tuple[date, float, float]] = None,
):
    """Build a ``_fetch_yf_series`` stand-in driven by a symbol->series table."""

    def _fetch(symbol: str) -> Optional[Tuple[date, float, float]]:
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


class TestSuccessThreeMarkets:
    """T2 — cn/hk/us success: structure + quality quadruple on every item."""

    def test_cn_snapshot_with_akshare_batch(self):
        batch = {
            "sh000001": {"as_of": FRESH_AS_OF, "close": 3245.67, "prev_close": 3284.0},
            "sz399001": {"as_of": FRESH_AS_OF, "close": 10411.4, "prev_close": 10411.4},
            "sz399006": {"as_of": FRESH_AS_OF, "close": 2111.1, "prev_close": 2150.0},
            "sh000300": {"as_of": FRESH_AS_OF, "close": 3950.2, "prev_close": 3980.5},
        }
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
        with patch(
            "data_provider.akshare_fetcher._akshare_call_with_timeout",
            MagicMock(return_value=batch),
        ), _patch_yf(
            # OR-COR-7bbac105: Yahoo Close is ALREADY a percent quantity
            # (4.21 = 4.21%); it must pass through unscaled.
            {"^VIX": (FRESH_AS_OF, 16.5, 15.8), "^TNX": (FRESH_AS_OF, 4.21, 4.15)}
        ):
            snapshot = fetcher.fetch_market_snapshot("cn", TRADE_DATE)

        assert set(snapshot.keys()) == set(CROSS_ASSET_GROUPS)
        # akshare CN indices: computed change_pct from close vs prev_close
        assert snapshot["indices"]["sh000001"].status == "ok"
        assert snapshot["indices"]["sh000001"].value == pytest.approx(3245.67)
        assert snapshot["indices"]["sh000001"].change_pct == pytest.approx(-1.17, abs=0.01)
        assert snapshot["indices"]["sh000001"].source == "akshare:stock_zh_index_daily_em"
        assert snapshot["indices"]["sz399006"].change_pct == pytest.approx(-1.81, abs=0.01)
        for item in snapshot["indices"].values():
            _assert_quadruple(item)
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
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
        with _patch_yf(table):
            snapshot = fetcher.fetch_market_snapshot("hk", TRADE_DATE)

        assert snapshot["indices"]["HSI"].status == "ok"
        assert snapshot["indices"]["HSI"].value == pytest.approx(24000.0)
        assert snapshot["indices"]["HSI"].change_pct == pytest.approx(-1.23, abs=0.01)
        assert snapshot["indices"]["HSTECH"].change_pct == pytest.approx(0.95, abs=0.01)
        for group in CROSS_ASSET_GROUPS:
            for item in snapshot[group].values():
                _assert_quadruple(item)

    def test_us_snapshot_via_yfinance(self):
        table = {
            "^GSPC": (FRESH_AS_OF, 5800.0, 5760.0),
            "^IXIC": (FRESH_AS_OF, 18500.0, 18400.0),
            "^DJI": (FRESH_AS_OF, 43200.0, 43300.0),
        }
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
        with _patch_yf(table):
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        assert {key for key in snapshot["indices"]} == {"SPX", "IXIC", "DJI"}
        assert snapshot["indices"]["IXIC"].change_pct == pytest.approx(0.54, abs=0.01)
        for group in CROSS_ASSET_GROUPS:
            for item in snapshot[group].values():
                _assert_quadruple(item)


class TestMissingData:
    """T3 — provider returns nothing -> not_supported, never raises."""

    def test_empty_provider_yields_not_supported_without_raise(self):
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
        with _patch_yf({}):  # every yfinance symbol: no data
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        assert set(snapshot.keys()) == set(CROSS_ASSET_GROUPS)
        for item in snapshot["indices"].values():
            assert item.status == "not_supported"
            assert item.error == "no_data"
            _assert_quadruple(item)
        for item in snapshot["commodities"].values():
            assert item.status == "not_supported"
        assert snapshot["commodities"]  # group still populated, just marked

    def test_unknown_market_falls_back_to_cn_without_raise(self):
        fetcher = CrossAssetFetcher(
            fx_repo=MagicMock(), timeout_seconds=2, stale_days=2
        )
        with patch(
            "data_provider.akshare_fetcher._akshare_call_with_timeout",
            MagicMock(return_value={}),  # empty batch -> akshare_batch_failed
        ), _patch_yf({}):
            snapshot = fetcher.fetch_market_snapshot("mars", TRADE_DATE)

        assert set(snapshot.keys()) == set(CROSS_ASSET_GROUPS)


class TestStaleMarking:
    """T4 — stale threshold flags only the offending item."""

    def test_stale_item_marked_and_sibling_unaffected(self):
        table = {
            "^GSPC": (OLD_AS_OF, 5800.0, 5760.0),  # 5 natural days old -> stale
            "^IXIC": (FRESH_AS_OF, 18500.0, 18400.0),  # fresh sibling
        }
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
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
        fetcher = CrossAssetFetcher(fx_repo=MagicMock(), stale_days=2)
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

        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
        with patch.object(
            CrossAssetFetcher,
            "_fetch_yf_series",
            new=staticmethod(
                lambda symbol: (
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

    def test_akshare_batch_failure_recorded_not_raised(self):
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
        with patch(
            "data_provider.akshare_fetcher._akshare_call_with_timeout",
            MagicMock(side_effect=RuntimeError("subprocess died")),
        ), _patch_yf({}):
            snapshot = fetcher.fetch_market_snapshot("cn", TRADE_DATE)

        assert snapshot["indices"]["sh000001"].status == "error"
        assert snapshot["indices"]["sh000001"].error == "akshare_batch_failed"

    def test_akshare_unavailable_symbols_mark_not_supported(self):
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
        # batch mapping present but every symbol unavailable -> per-item
        # not_supported (degradation level 4); a fully empty mapping goes to
        # error=akshare_batch_failed (covered by the failure test above).
        with patch(
            "data_provider.akshare_fetcher._akshare_call_with_timeout",
            MagicMock(return_value={"sh000001": None, "sz399001": None, "sz399006": None, "sh000300": None}),
        ), _patch_yf({}):
            snapshot = fetcher.fetch_market_snapshot("cn", TRADE_DATE)

        assert snapshot["indices"]["sh000001"].status == "not_supported"
        _assert_quadruple(snapshot["indices"]["sh000001"])


class TestFxCacheFirst:
    """FX reads the portfolio FX cache first, yfinance only on miss/broken."""

    def _fetcher(self, repo):
        return CrossAssetFetcher(fx_repo=repo, stale_days=2)

    def test_cache_hit_skips_yfinance(self):
        row = SimpleNamespace(rate=7.25, rate_date=FRESH_AS_OF, source="yfinance_batch")
        repo = MagicMock()
        repo.get_latest_fx_rate.return_value = row
        yf_mock = MagicMock(side_effect=AssertionError("yfinance must not be called on cache hit"))
        fetcher = self._fetcher(repo)
        with patch.object(CrossAssetFetcher, "_fetch_yf_series", new=staticmethod(yf_mock)):
            snapshot = fetcher.fetch_market_snapshot("cn", TRADE_DATE)

        repo.get_latest_fx_rate.assert_called_once_with(
            from_currency="USD", to_currency="CNH", as_of=TRADE_DATE
        )
        item = snapshot["fx"]["USDCNH"]
        assert item.status == "ok"
        assert item.value == pytest.approx(7.25)
        assert item.source == "portfolio_cache:yfinance_batch"
        assert item.stale is False
        assert item.change_pct is None  # single cached rate cannot yield a change
        _assert_quadruple(item)

    def test_cache_row_older_than_threshold_is_stale(self):
        row = SimpleNamespace(
            rate=7.25, rate_date=TRADE_DATE - timedelta(days=5), source="manual"
        )
        repo = MagicMock()
        repo.get_latest_fx_rate.return_value = row
        fetcher = self._fetcher(repo)
        with patch.object(CrossAssetFetcher, "_fetch_yf_series", new=staticmethod(MagicMock(
            side_effect=AssertionError("cache row must win even when stale")
        ))):
            snapshot = fetcher.fetch_market_snapshot("cn", TRADE_DATE)

        assert snapshot["fx"]["USDCNH"].status == "ok"
        assert snapshot["fx"]["USDCNH"].stale is True

    def test_cache_miss_falls_back_to_yfinance(self):
        repo = MagicMock()
        repo.get_latest_fx_rate.return_value = None
        fetcher = self._fetcher(repo)
        with patch.object(
            CrossAssetFetcher,
            "_fetch_yf_series",
            new=staticmethod(_fake_yf_series({"USDCNH=X": (FRESH_AS_OF, 7.31, 7.28)})),
        ):
            snapshot = fetcher.fetch_market_snapshot("cn", TRADE_DATE)

        item = snapshot["fx"]["USDCNH"]
        assert item.status == "ok"
        assert item.source == "yfinance"
        assert item.value == pytest.approx(7.31)
        assert item.change_pct == pytest.approx(0.41, abs=0.01)
        assert item.stale is False

    def test_broken_cache_repo_falls_back_to_yfinance(self):
        repo = MagicMock()
        repo.get_latest_fx_rate.side_effect = RuntimeError("db down")
        fetcher = self._fetcher(repo)
        with patch.object(
            CrossAssetFetcher,
            "_fetch_yf_series",
            new=staticmethod(_fake_yf_series({"USDCNH=X": (FRESH_AS_OF, 7.31, 7.28)})),
        ):
            snapshot = fetcher.fetch_market_snapshot("cn", TRADE_DATE)

        assert snapshot["fx"]["USDCNH"].status == "ok"
        assert snapshot["fx"]["USDCNH"].source == "yfinance"

    def test_no_fx_repo_uses_yfinance_directly(self):
        fetcher = CrossAssetFetcher(fx_repo=None, stale_days=2)
        # _get_fx_repo import path may construct a real repo; neutralize it
        with patch.object(
            CrossAssetFetcher, "_get_fx_repo", return_value=None
        ), patch.object(
            CrossAssetFetcher,
            "_fetch_yf_series",
            new=staticmethod(_fake_yf_series({"USDCNH=X": (FRESH_AS_OF, 7.31, 7.28)})),
        ):
            snapshot = fetcher.fetch_market_snapshot("cn", TRADE_DATE)

        assert snapshot["fx"]["USDCNH"].status == "ok"
        assert snapshot["fx"]["USDCNH"].source == "yfinance"


class TestDollarIndexKey:
    """The dollar-index self-pair ("DXY","DXY") must surface under the key
    "DXY", not "DXYDXY" (issue #1910 review, minor)."""

    def test_us_fx_group_uses_explicit_dxy_key(self):
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
        with _patch_yf({
            "DX-Y.NYB": (FRESH_AS_OF, 105.2, 104.9),
            "USDCNH=X": (FRESH_AS_OF, 7.31, 7.28),
        }):
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        assert set(snapshot["fx"].keys()) == {"USDCNH", "DXY"}
        assert snapshot["fx"]["DXY"].status == "ok"
        assert snapshot["fx"]["DXY"].value == pytest.approx(105.2)
        assert snapshot["fx"]["DXY"].name == "美元指数"
        _assert_quadruple(snapshot["fx"]["DXY"])

    def test_hk_fx_group_and_timeout_names_use_dxy_key(self):
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
        with _patch_yf({"DX-Y.NYB": (FRESH_AS_OF, 105.2, 104.9)}):
            snapshot = fetcher.fetch_market_snapshot("hk", TRADE_DATE)
        assert "DXY" in snapshot["fx"]
        assert "DXYDXY" not in snapshot["fx"]

        # the budget-exceeded path builds its placeholder names via the same
        # key rule
        timeout_group = fetcher._timeout_group_items("hk", "fx", TRADE_DATE)
        assert "DXY" in timeout_group
        assert "DXYDXY" not in timeout_group
        assert timeout_group["DXY"].error == "timeout"


class TestTnxNoDoubleScaling:
    """OR-COR-7bbac105 — ^TNX Close from Yahoo is already quoted in percent
    (4.21 = 4.21%); the former unconditional ``value / 10`` reported a yield
    ten times too small."""

    def test_tnx_close_passes_through_unscaled(self):
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
        with _patch_yf({"^TNX": (FRESH_AS_OF, 4.21, 4.15)}):
            snapshot = fetcher.fetch_market_snapshot("us", TRADE_DATE)

        item = snapshot["rates"]["US10Y"]
        assert item.status == "ok"
        assert item.value == pytest.approx(4.21, abs=0.0001)
        # change_pct is computed from the raw closes: (4.21-4.15)/4.15*100
        assert item.change_pct == pytest.approx(1.45, abs=0.01)

    def test_high_yield_regime_also_passes_through(self):
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
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
            series = CrossAssetFetcher._fetch_yf_series("^GSPC")

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
            series = CrossAssetFetcher._fetch_yf_series("^GSPC")

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
        fetcher = CrossAssetFetcher(fx_repo=MagicMock())
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
        fetcher = CrossAssetFetcher(fx_repo=MagicMock(), timeout_seconds=8)
        assert not hasattr(fetcher, "_deadline")
        # helpers are dead-reckoned from an explicit deadline (old no-arg
        # signature raised TypeError here)
        assert fetcher._budget_exceeded(time.monotonic() - 1) is True
        assert fetcher._budget_exceeded(time.monotonic() + 60) is False
        assert fetcher._budget_remaining(time.monotonic() + 60) > 0

    def test_concurrent_fetches_on_shared_instance_complete_isolated(self):
        fetcher = CrossAssetFetcher(fx_repo=MagicMock(), timeout_seconds=8)
        counter = itertools.count()
        counter_lock = threading.Lock()
        first_parked = threading.Event()
        release_first = threading.Event()

        def _seam(symbol: str):
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
                for item in snapshot[group].values():
                    _assert_quadruple(item)


class TestPortfolioFallbackStalePropagation(unittest.TestCase):
    """OR-COR-cross-asset-fx-cache-stale (issue #1910, PR #2428 review).

    Production fallback: when the portfolio service cannot refresh a pair
    online it copies the last known rate onto the target date with
    ``is_stale=True`` (``portfolio_service._refresh_account_fx_rates``).
    The cross-asset reader must honor that flag — not only the
    ``rate_date`` distance — and the FX group quality must carry the
    degradation (``stale`` + ``{group}:stale_data`` limitation), while the
    item keeps the ``source`` / ``as_of`` / ``stale`` / ``error`` contract.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        env_path = Path(self.temp_dir.name) / ".env"
        db_path = Path(self.temp_dir.name) / "fx_stale_test.db"
        env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519",
                    "GEMINI_API_KEY=test",
                    "ADMIN_AUTH_ENABLED=false",
                    f"DATABASE_PATH={db_path}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(env_path)
        os.environ["DATABASE_PATH"] = str(db_path)
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.repo = PortfolioRepository()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def test_refresh_fallback_same_day_stale_row_propagates_to_cross_asset_read(self):
        # 1. A genuine online rate from three days ago sits in the cache.
        self.repo.save_fx_rate(
            from_currency="USD",
            to_currency="CNH",
            rate_date=TRADE_DATE - timedelta(days=3),
            rate=7.10,
            source="yfinance",
            is_stale=False,
        )
        service = PortfolioService()
        account = service.create_account(
            name="us-account", broker="Demo", market="us", base_currency="CNH"
        )
        service.record_cash_ledger(
            account_id=account["id"],
            event_date=TRADE_DATE - timedelta(days=10),
            direction="in",
            amount=1000,
            currency="USD",
        )

        # 2. Online refresh finds no data -> fail-open stale fallback.
        with patch.object(
            PortfolioService, "_fetch_fx_rate_from_yfinance", new=MagicMock(return_value=None)
        ):
            summary = service.refresh_fx_rates(as_of=TRADE_DATE)
        assert summary["stale_count"] == 1
        assert summary["updated_count"] == 0
        assert summary["error_count"] == 0

        # 3. The production fallback record: same-day rate_date, is_stale=True.
        row = self.repo.get_latest_fx_rate(
            from_currency="USD", to_currency="CNH", as_of=TRADE_DATE
        )
        assert row is not None
        assert row.rate_date == TRADE_DATE
        assert row.is_stale is True

        # 4. Cross-asset read must inherit the degradation, not report a
        #    fresh same-day rate. Cache-first: yfinance must not be hit.
        fetcher = CrossAssetFetcher(fx_repo=self.repo, stale_days=2)
        with patch.object(
            CrossAssetFetcher,
            "_fetch_yf_series",
            new=staticmethod(MagicMock(side_effect=AssertionError("cache row must win"))),
        ):
            snapshot = fetcher.fetch_market_snapshot("cn", TRADE_DATE)

        item = snapshot["fx"]["USDCNH"]
        _assert_quadruple(item)
        assert item.status == "ok"
        assert item.value == pytest.approx(7.10)
        assert item.as_of == TRADE_DATE.isoformat()
        assert item.source.startswith("portfolio_cache:")
        assert item.error is None
        assert item.stale is True  # <-- RED before the fix

        # 5. Group-level quality statistics carry the degradation.
        quality = build_data_quality(snapshot)
        assert quality.fx.stale is True
        assert "fx:stale_data" in quality.limitations
