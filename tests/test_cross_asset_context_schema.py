# -*- coding: utf-8 -*-
"""Minimal contract tests for the cross-asset-v1 schema (Issue #1910 W2-core).

Full matrix (W1-plan T1) is completed by the downstream W2-tests task; these
keep the committed contract honest: version literal, risk appetite enum,
quality quadruple presence, and safe-dict whitelist semantics.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas.cross_asset_context import (
    CROSS_ASSET_GROUPS,
    CROSS_ASSET_SCHEMA_VERSION,
    CrossAssetContext,
    CrossAssetItem,
)


def _context(**overrides) -> CrossAssetContext:
    payload = {"market": "cn", "trade_date": "2026-10-22"}
    payload.update(overrides)
    return CrossAssetContext(**payload)


class TestSchemaVersionLiteral:
    def test_default_is_cross_asset_v1(self):
        assert _context().schema_version == "cross-asset-v1"
        assert CROSS_ASSET_SCHEMA_VERSION == "cross-asset-v1"

    def test_other_version_rejected_on_construct(self):
        with pytest.raises(ValidationError):
            _context(schema_version="cross-asset-v2")

    def test_model_copy_blocks_version_bypass(self):
        context = _context()
        with pytest.raises(ValidationError):
            context.model_copy(update={"schema_version": "v9"})


class TestRiskAppetiteEnum:
    @pytest.mark.parametrize("value", ["risk_on", "neutral", "risk_off", "unknown"])
    def test_allowed_values(self, value):
        assert _context(risk_appetite=value).risk_appetite == value

    @pytest.mark.parametrize("value", ["bullish", "RISK_OFF", "riskon", ""])
    def test_other_values_rejected(self, value):
        with pytest.raises(ValidationError):
            _context(risk_appetite=value)


class TestFieldValidators:
    def test_market_normalized_to_lowercase_and_whitelist(self):
        assert _context(market="CN").market == "cn"
        with pytest.raises(ValidationError):
            _context(market="mars")

    def test_trade_date_must_be_iso_date(self):
        assert _context(trade_date="2026-10-22").trade_date == "2026-10-22"
        with pytest.raises(ValidationError):
            _context(trade_date="22/10/2026")

    def test_item_as_of_must_be_iso_date(self):
        item = CrossAssetItem(status="ok", value=1.0, as_of="2026-10-21")
        assert item.as_of == "2026-10-21"
        with pytest.raises(ValidationError):
            CrossAssetItem(status="ok", value=1.0, as_of="yesterday")

    def test_six_groups_default_empty(self):
        context = _context()
        for group in CROSS_ASSET_GROUPS:
            assert getattr(context, group) == {}


class TestToSafeDict:
    def test_safe_dict_is_whitelist_without_raw_payload(self):
        context = _context(
            indices={
                "sh000001": CrossAssetItem(
                    status="ok",
                    value=3245.67,
                    change_pct=-1.2,
                    name="上证指数",
                    source="akshare",
                    as_of="2026-10-21",
                )
            },
            generated_at=None,
        )
        safe = context.to_safe_dict()

        assert safe["schema_version"] == "cross-asset-v1"
        assert safe["risk_appetite"] == "unknown"
        assert safe["indices"]["sh000001"]["value"] == 3245.67
        assert safe["indices"]["sh000001"]["change_pct"] == -1.2
        # mandatory quality quadruple survives
        assert safe["indices"]["sh000001"]["source"] == "akshare"
        assert safe["indices"]["sh000001"]["as_of"] == "2026-10-21"
        assert safe["indices"]["sh000001"]["stale"] is False
        assert "error" in safe["indices"]["sh000001"]
        # display name / generated_at are NOT part of the safe whitelist
        assert "name" not in safe["indices"]["sh000001"]
        assert "generated_at" not in safe

    def test_safe_dict_round_trips_through_json(self):
        import json

        context = _context(risk_appetite="risk_off", impact_summary="外部拖累")
        safe = context.to_safe_dict()
        assert json.loads(json.dumps(safe, ensure_ascii=False))["impact_summary"] == "外部拖累"
