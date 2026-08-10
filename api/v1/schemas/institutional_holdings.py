# -*- coding: utf-8 -*-
"""API schemas for SEC 13F institutional holdings."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class InstitutionalHoldingImportRequest(BaseModel):
    cik: str = Field(
        "0001759760",
        description="SEC CIK; defaults to H&H International Investment",
    )
    max_filings: int = Field(8, ge=1, le=20, description="Distinct report periods to import")


class FilingImportErrorItem(BaseModel):
    accession_number: str
    message: str


class InstitutionalHoldingImportResponse(BaseModel):
    manager_cik: str
    requested: int
    processed: int
    created: int
    refreshed: int
    unchanged: int
    holdings_saved: int
    errors: List[FilingImportErrorItem] = Field(default_factory=list)


class FilingSnapshotItem(BaseModel):
    manager_cik: str
    manager_name: str
    form_type: str
    accession_number: str
    report_period: date
    filed_date: date
    accepted_at: datetime
    entry_count: int
    total_value_usd: int
    primary_document_url: str
    information_table_url: str


class HoldingDeltaItem(BaseModel):
    issuer_name: str
    title_of_class: str
    cusip: str
    put_call: str = ""
    status: str
    current_shares: Optional[Decimal] = None
    previous_shares: Optional[Decimal] = None
    share_delta: Optional[Decimal] = None
    share_delta_pct: Optional[float] = None
    current_value_usd: Optional[int] = None
    previous_value_usd: Optional[int] = None
    current_weight_pct: Optional[float] = None


class InstitutionalHoldingAnalysisResponse(BaseModel):
    manager_cik: str
    manager_name: str
    current: FilingSnapshotItem
    previous: Optional[FilingSnapshotItem] = None
    top_4_concentration_pct: float
    top_6_concentration_pct: float
    holdings: List[HoldingDeltaItem] = Field(default_factory=list)
    disclosure_note: str
