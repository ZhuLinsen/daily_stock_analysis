# -*- coding: utf-8 -*-
"""Minimal service tests for CrossAssetContextService (Issue #1910 W2-core).

Covers the deterministic voting rule, fail-open behaviour, sector links,
cache reuse and disabled switch, all against a stub fetcher (no network).
Full matrix (W1-plan T6-T9) is completed by the downstream W2-tests task.
"""

from __future__ import annotations

import os
from datetime import date
from types import SimpleNamespace
from typing import Dict
from unittest.mock import patch

import pytest

from src.schemas.cross_asset_context import CROSS_ASSET_GROUPS, CrossAssetItem
from src.services.cross_asset_context_service import (
    MIN_EFFECTIVE_VOTES,
    CrossAssetContextService,
    build_cross_asset_context,
    build_minimal_unknown_context,
    compute_risk_appetite,
)

TRADE_DATE = date(2026, 10, 22)


def _item(*, change_pct=None, value=None, status="ok", stale=False, error=None):
    return CrossAssetItem(
        status=status,
        value=value,
        change_pct=change_pct,
        source="yfinance",
        as_of="2026-10-21",
        stale=stale,
        error=error,
    )


def _snapshot(indices=None, fx=None, volatility=None) -> Dict[str, Dict[str, CrossAssetItem]]:
    return {
        "indices": indices or {},
        "fx": fx or {},
        "rates": {},
        "commodities": {},
        "crypto": {},
        "volatility": volatility or {},
    }


class _StubFetcher:
    def __init__(self, snapshot=None, exc: Exception | None = None):
        self.snapshot = snapshot or _snapshot()
        self.exc = exc
        self.calls = 0
        self.seen_markets = []

    def fetch_market_snapshot(self, market, trade_date):
        self.calls += 1
        self.seen_markets.append((market, trade_date))
        if self.exc is not None:
            raise self.exc
        return self.snapshot


class TestVotingRule:
    def test_risk_off_scenario(self):
        snapshot = _snapshot(
            indices={
                "sh000001": _item(change_pct=-1.5),
                "sh000300": _item(change_pct=-1.8),
                "sz399006": _item(change_pct=-2.2),
            },
            fx={"USDCNH": _item(change_pct=0.5)},
            volatility={"VIX": _item(value=26.5, change_pct=12.0)},
        )
        appetite, net, effective = compute_risk_appetite(snapshot)
        assert appetite == "risk_off"
        assert net <= -2
        assert effective >= MIN_EFFECTIVE_VOTES

    def test_risk_on_scenario(self):
        snapshot = _snapshot(
            indices={
                "sh000001": _item(change_pct=1.1),
                "sh000300": _item(change_pct=0.8),
                "sz399006": _item(change_pct=1.4),
            },
            fx={"USDCNH": _item(change_pct=-0.3)},
            volatility={"VIX": _item(value=14.0)},
        )
        assert compute_risk_appetite(snapshot)[0] == "risk_on"

    def test_neutral_boundary(self):
        snapshot = _snapshot(
            indices={
                "sh000001": _item(change_pct=0.8),
                "sh000300": _item(change_pct=-0.4),
            },
            fx={"USDCNH": _item(change_pct=-0.1)},
            volatility={"VIX": _item(value=15.0)},
        )
        appetite, net, _effective = compute_risk_appetite(snapshot)
        assert appetite == "neutral"
        assert -2 < net < 2

    def test_vix_levels_vote_strong_and_weak(self):
        strong = _snapshot(volatility={"VIX": _item(value=25.0)}, indices={"a": _item(change_pct=1.0)})
        weak = _snapshot(volatility={"VIX": _item(value=20.5)}, indices={"a": _item(change_pct=1.0)})
        assert compute_risk_appetite(strong)[0] == "unknown"  # 2 effective votes not enough alone
        assert compute_risk_appetite(weak)[1] == 0  # weak VIX vote (-1) + index (+1) = 0

    def test_insufficient_votes_unknown(self):
        snapshot = _snapshot(
            indices={"sh000001": _item(change_pct=1.0)},
            fx={"USDCNH": _item(change_pct=0.2)},
        )
        assert compute_risk_appetite(snapshot)[0] == "unknown"

    def test_indices_and_volatility_both_missing_unknown(self):
        snapshot = _snapshot(fx={"USDCNH": _item(change_pct=0.2), "USDHKD": _item(change_pct=0.1)})
        assert compute_risk_appetite(snapshot)[0] == "unknown"


class TestBuildContext:
    def test_full_build_off_snapshot(self):
        snapshot = _snapshot(
            indices={"sh000001": _item(change_pct=-1.5), "sh000300": _item(change_pct=-1.2)},
            fx={"USDCNH": _item(change_pct=0.6)},
            volatility={"VIX": _item(value=27.0)},
        )
        context = build_cross_asset_context(
            market="cn", trade_date=TRADE_DATE, snapshot=snapshot, industry="半导体"
        )
        assert context.schema_version == "cross-asset-v1"
        assert context.risk_appetite == "risk_off"
        assert "risk-off" in context.impact_summary
        assert "VIX" in context.impact_summary
        assert "vix_high" in context.risk_tags
        assert "usd_strength" in context.risk_tags
        assets = {(link.group, link.asset) for link in context.sector_links}
        assert ("indices", "sh000300") in assets  # cn market default
        assert ("rates", "US10Y") in assets  # 半导体 industry override
        assert all(link.link_reason for link in context.sector_links)
        assert context.data_quality.indices.ok_count == 2

    def test_stale_ok_items_still_vote(self):
        snapshot = _snapshot(
            indices={
                "sh000001": _item(change_pct=-1.0, stale=True),
                "sh000300": _item(change_pct=-1.0),
                "sz399006": _item(change_pct=-1.0),
            },
            fx={"USDCNH": _item(change_pct=0.4)},
            volatility={"VIX": _item(value=26.0, stale=True)},
        )
        context = build_cross_asset_context(market="cn", trade_date=TRADE_DATE, snapshot=snapshot)
        assert context.risk_appetite == "risk_off"  # stale ok items still vote
        assert any(limitation.endswith("stale_data") for limitation in context.data_quality.limitations)


class TestFailOpen:
    def test_fetcher_exception_never_raises(self):
        service = CrossAssetContextService(fetcher=_StubFetcher(exc=RuntimeError("boom")))
        context = service.get_context("cn", TRADE_DATE, "600519")
        assert context.risk_appetite == "unknown"
        assert context.data_quality.limitations
        assert "RuntimeError" in context.data_quality.limitations[0]

    def test_minimal_unknown_context(self):
        context = build_minimal_unknown_context(market="hk", trade_date=TRADE_DATE, reason="x")
        assert context.market == "hk"
        assert context.risk_appetite == "unknown"
        assert "暂不可用" in context.impact_summary

    def test_bad_inputs_still_fail_open(self):
        service = CrossAssetContextService(fetcher=_StubFetcher())
        context = service.get_context("mars", "not-a-date")
        assert context.risk_appetite == "unknown"
        assert context.market == "cn"  # normalized, never raises


class TestCacheAndSwitch:
    def test_same_market_day_hits_cache_once(self):
        fetcher = _StubFetcher()
        service = CrossAssetContextService(fetcher=fetcher)
        first = service.get_context("cn", TRADE_DATE, "600519")
        second = service.get_context("cn", TRADE_DATE, "000001")
        assert fetcher.calls == 1
        assert first is second

    def test_different_market_or_date_refetches(self):
        fetcher = _StubFetcher()
        service = CrossAssetContextService(fetcher=fetcher)
        service.get_context("cn", TRADE_DATE)
        service.get_context("hk", TRADE_DATE)
        service.get_context("cn", date(2026, 10, 23))
        assert fetcher.calls == 3

    def test_disabled_switch_returns_unknown_context(self):
        fetcher = _StubFetcher()
        config = SimpleNamespace(cross_asset_context_enabled=False)
        service = CrossAssetContextService(fetcher=fetcher, config=config)
        context = service.get_context("cn", TRADE_DATE)
        assert fetcher.calls == 0
        assert context.risk_appetite == "unknown"
        assert "disabled" in context.data_quality.limitations[0]

    def test_enabled_switch_fetches(self):
        config = SimpleNamespace(cross_asset_context_enabled=True)
        fetcher = _StubFetcher()
        service = CrossAssetContextService(fetcher=fetcher, config=config)
        context = service.get_context("us", TRADE_DATE)
        assert fetcher.calls == 1
        assert context.market == "us"

    def test_unknown_market_normalized(self):
        fetcher = _StubFetcher()
        service = CrossAssetContextService(fetcher=fetcher)
        service.get_context("CN", TRADE_DATE)
        assert fetcher.seen_markets[0][0] == "cn"


class TestManagedFetcherConfigReload:
    """Runtime config reload must reach the service-managed fetcher.

    PR #2428 review blocker OR-COR-cross-asset-config-reload: the process-wide
    service kept the first CrossAssetFetcher forever, so editing
    CROSS_ASSET_CONTEXT_TIMEOUT_SECONDS / CROSS_ASSET_CONTEXT_STALE_DAYS via
    the Web settings page (or the schedule config reload) never took effect
    until a process restart.
    """

    @staticmethod
    def _config(timeout_seconds, stale_days):
        return SimpleNamespace(
            cross_asset_context_enabled=True,
            cross_asset_context_timeout_seconds=timeout_seconds,
            cross_asset_context_stale_days=stale_days,
        )

    @staticmethod
    def _patch_fetcher_factory(created):
        def _factory(**kwargs):
            fetcher = _StubFetcher()
            fetcher.params = (kwargs["timeout_seconds"], kwargs["stale_days"])
            created.append(fetcher)
            return fetcher

        return patch(
            "data_provider.cross_asset_fetcher.CrossAssetFetcher",
            side_effect=_factory,
        )

    def test_settings_change_rebuilds_managed_fetcher(self):
        created = []
        service = CrossAssetContextService()

        with self._patch_fetcher_factory(created):
            service.get_context("cn", TRADE_DATE, config=self._config(8, 2))
            # different trade_date bypasses the per-(market, day) context cache
            service.get_context("cn", date(2026, 10, 23), config=self._config(1, 30))

        assert [fetcher.params for fetcher in created] == [(8, 2), (1, 30)]

    def test_unchanged_settings_reuse_managed_fetcher(self):
        created = []
        service = CrossAssetContextService()

        with self._patch_fetcher_factory(created):
            service.get_context("cn", TRADE_DATE, config=self._config(8, 2))
            service.get_context("cn", date(2026, 10, 23), config=self._config(8, 2))

        assert len(created) == 1

    def test_injected_fetcher_is_never_replaced(self):
        fetcher = _StubFetcher()
        service = CrossAssetContextService(fetcher=fetcher)
        created = []

        with self._patch_fetcher_factory(created):
            service.get_context("cn", TRADE_DATE, config=self._config(8, 2))
            service.get_context("cn", date(2026, 10, 23), config=self._config(1, 30))

        assert created == []
        assert fetcher.calls == 2

    def test_real_config_env_change_reaches_managed_fetcher(self, monkeypatch):
        """Project convention (monkeypatch.setenv + Config reload): a real
        Config re-parsed from edited env vars must drive the next fetch."""
        from src.config import Config

        created = []
        service = CrossAssetContextService()

        with patch("src.config.setup_env"), \
             patch.object(Config, "_parse_litellm_yaml", return_value=[]), \
             patch.object(Config, "_parse_stock_email_groups", return_value=[]):
            monkeypatch.setenv("CROSS_ASSET_CONTEXT_TIMEOUT_SECONDS", "8")
            monkeypatch.setenv("CROSS_ASSET_CONTEXT_STALE_DAYS", "2")
            with self._patch_fetcher_factory(created):
                service.get_context("cn", TRADE_DATE, config=Config._load_from_env())

                monkeypatch.setenv("CROSS_ASSET_CONTEXT_TIMEOUT_SECONDS", "1")
                monkeypatch.setenv("CROSS_ASSET_CONTEXT_STALE_DAYS", "30")
                with patch.dict(os.environ, {}, clear=False):
                    fresh_config = Config._load_from_env()
                service.get_context(
                    "cn", date(2026, 10, 23), config=fresh_config
                )

        assert [fetcher.params for fetcher in created] == [(8, 2), (1, 30)]
