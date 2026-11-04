# -*- coding: utf-8 -*-
"""Internal CrossAssetContext schema for Issue #1910 (cross-asset-v1).

Contract rules (from issue #1910 + maintainer comments):

- ``risk_appetite`` only gives a direction (risk_on/neutral/risk_off/unknown);
  it is NEVER a trading instruction.
- Asset groups are filled per market with whatever data is available; no group
  is mandatory.
- Every field-level datum carries ``source`` / ``as_of`` / ``stale`` / ``error``
  so degraded data can never masquerade as fresh data.
- Prompt and reports only receive the low-sensitivity summary produced by
  :meth:`CrossAssetContext.to_safe_dict`, never the raw payload.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from src.utils.sanitize import redact_sensitive_mapping


CROSS_ASSET_SCHEMA_VERSION = "cross-asset-v1"
_CROSS_ASSET_VERSION_ADAPTER = TypeAdapter(Literal["cross-asset-v1"])

CrossAssetRiskAppetite = Literal["risk_on", "neutral", "risk_off", "unknown"]
CrossAssetItemStatus = Literal["ok", "not_supported", "error"]

# The six asset groups of the cross-asset-v1 contract.
CROSS_ASSET_GROUPS = ("indices", "fx", "rates", "commodities", "crypto", "volatility")

_VALID_MARKETS = frozenset({"cn", "hk", "us", "jp", "kr", "tw"})


class _CrossAssetModel(BaseModel):
    """Base model for the cross-asset-v1 internal contract."""

    model_config = ConfigDict(validate_assignment=True)


class CrossAssetItem(_CrossAssetModel):
    """Field-level cross-asset datum with mandatory quality quadruple.

    ``source`` / ``as_of`` / ``stale`` / ``error`` exist on every item so a
    degraded datum is always explicitly labelled (issue hard requirement).
    """

    status: CrossAssetItemStatus = "not_supported"
    value: Optional[float] = None
    change_pct: Optional[float] = None
    name: Optional[str] = None
    source: Optional[str] = None
    as_of: Optional[str] = None
    stale: bool = False
    error: Optional[str] = None

    @field_validator("as_of")
    @classmethod
    def _as_of_must_be_date_string(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        text = str(value).strip()
        if not text:
            return None
        try:
            datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("as_of must be a YYYY-MM-DD date string") from exc
        return text[:10]


class SectorLink(_CrossAssetModel):
    """Why this analysis should watch a given external asset."""

    asset: str
    asset_name: Optional[str] = None
    group: str
    link_reason: str = ""

    @field_validator("group")
    @classmethod
    def _group_must_be_known(cls, value: str) -> str:
        if value not in CROSS_ASSET_GROUPS:
            raise ValueError(f"group must be one of {CROSS_ASSET_GROUPS}")
        return value


class CrossAssetGroupQuality(_CrossAssetModel):
    """Per-group quality summary (source/as_of/stale/error quadruple)."""

    source: Optional[str] = None
    as_of: Optional[str] = None
    stale: bool = False
    error: Optional[str] = None
    item_count: int = 0
    ok_count: int = 0


class CrossAssetDataQuality(_CrossAssetModel):
    """Low-sensitivity data quality summary for a CrossAssetContext."""

    indices: CrossAssetGroupQuality = Field(default_factory=CrossAssetGroupQuality)
    fx: CrossAssetGroupQuality = Field(default_factory=CrossAssetGroupQuality)
    rates: CrossAssetGroupQuality = Field(default_factory=CrossAssetGroupQuality)
    commodities: CrossAssetGroupQuality = Field(default_factory=CrossAssetGroupQuality)
    crypto: CrossAssetGroupQuality = Field(default_factory=CrossAssetGroupQuality)
    volatility: CrossAssetGroupQuality = Field(default_factory=CrossAssetGroupQuality)
    limitations: List[str] = Field(default_factory=list)


class CrossAssetContext(_CrossAssetModel):
    """Versioned cross-asset background envelope (cross-asset-v1)."""

    market: str
    trade_date: str
    schema_version: Literal["cross-asset-v1"] = CROSS_ASSET_SCHEMA_VERSION
    risk_appetite: CrossAssetRiskAppetite = "unknown"
    indices: Dict[str, CrossAssetItem] = Field(default_factory=dict)
    fx: Dict[str, CrossAssetItem] = Field(default_factory=dict)
    rates: Dict[str, CrossAssetItem] = Field(default_factory=dict)
    commodities: Dict[str, CrossAssetItem] = Field(default_factory=dict)
    crypto: Dict[str, CrossAssetItem] = Field(default_factory=dict)
    volatility: Dict[str, CrossAssetItem] = Field(default_factory=dict)
    sector_links: List[SectorLink] = Field(default_factory=list)
    impact_summary: str = ""
    risk_tags: List[str] = Field(default_factory=list)
    data_quality: CrossAssetDataQuality = Field(default_factory=CrossAssetDataQuality)
    generated_at: Optional[datetime] = None

    @field_validator("market")
    @classmethod
    def _market_must_be_known(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in _VALID_MARKETS:
            raise ValueError(f"market must be one of {sorted(_VALID_MARKETS)}")
        return normalized

    @field_validator("trade_date")
    @classmethod
    def _trade_date_must_be_date_string(cls, value: str) -> str:
        text = str(value or "").strip()
        try:
            datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("trade_date must be a YYYY-MM-DD date string") from exc
        return text[:10]

    def to_safe_dict(self) -> Dict[str, Any]:
        """Return the low-sensitivity whitelist dict injected into prompts.

        Per contract: no raw payload, no ``name``/``generated_at``; only
        value/change_pct plus the mandatory source/as_of/stale/error quadruple
        (and status) for each group item, plus data_quality.
        """

        payload: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "market": self.market,
            "trade_date": self.trade_date,
            "risk_appetite": self.risk_appetite,
            "impact_summary": self.impact_summary,
            "risk_tags": list(self.risk_tags),
            "sector_links": [
                {
                    "asset": link.asset,
                    "asset_name": link.asset_name,
                    "group": link.group,
                    "link_reason": link.link_reason,
                }
                for link in self.sector_links
            ],
            "data_quality": redact_sensitive_mapping(
                self.data_quality.model_dump(mode="json")
            ),
        }
        for group in CROSS_ASSET_GROUPS:
            items = getattr(self, group) or {}
            payload[group] = {
                key: {
                    "status": item.status,
                    "value": item.value,
                    "change_pct": item.change_pct,
                    "source": item.source,
                    "as_of": item.as_of,
                    "stale": item.stale,
                    "error": item.error,
                }
                for key, item in items.items()
            }
        return payload

    def model_copy(
        self,
        *,
        update: Optional[Mapping[str, Any]] = None,
        deep: bool = False,
    ) -> "CrossAssetContext":
        """Copy the context without bypassing the fixed contract fields."""

        if update is not None and "schema_version" in update:
            _CROSS_ASSET_VERSION_ADAPTER.validate_python(update["schema_version"])
        return super().model_copy(update=update, deep=deep)


def now_utc() -> datetime:
    """Current UTC timestamp (kept here so callers share one clock source)."""

    return datetime.now(timezone.utc)
