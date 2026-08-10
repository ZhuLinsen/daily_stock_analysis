# -*- coding: utf-8 -*-
"""Application service for importing and analyzing institutional 13F holdings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.storage import DatabaseManager

from src.repositories.institutional_holdings_repo import InstitutionalHoldingsRepository
from src.services.sec_13f_service import (
    PortfolioAnalysis,
    Sec13FClient,
    analyze_latest_holdings,
    normalize_cik,
    select_effective_filings,
)

PUBLIC_DISCLOSURE_DISCLAIMER = (
    "Form 13F is a delayed public disclosure of specified long securities managed by the filer. "
    "It is not a real-time or complete personal portfolio and does not disclose cash, short "
    "positions, non-reportable securities, or intra-quarter trades."
)


@dataclass(frozen=True)
class FilingImportError:
    accession_number: str
    message: str


@dataclass(frozen=True)
class ImportRecentResult:
    manager_cik: str
    requested: int
    processed: int
    created: int
    refreshed: int
    unchanged: int
    holdings_saved: int
    errors: Tuple[FilingImportError, ...]


class InstitutionalHoldingsService:
    """Coordinates SEC transport, idempotent storage, and derived analysis."""

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        *,
        client: Optional[Sec13FClient] = None,
        repository: Optional[InstitutionalHoldingsRepository] = None,
    ) -> None:
        self.repository = repository or InstitutionalHoldingsRepository(db_manager)
        self.client = client

    def import_recent(self, cik: str, *, max_filings: int = 8) -> ImportRecentResult:
        if self.client is None:
            raise ValueError("SEC client is required for imports")
        if not 1 <= max_filings <= 20:
            raise ValueError("max_filings must be between 1 and 20")

        canonical_cik = normalize_cik(cik)
        references = self.client.list_recent_filings(
            canonical_cik,
            limit=min(100, max_filings * 3),
        )
        effective = select_effective_filings(references, limit=max_filings)

        created = 0
        refreshed = 0
        unchanged = 0
        holdings_saved = 0
        processed = 0
        errors: List[FilingImportError] = []

        # Persist oldest first so a partially successful import still leaves a
        # useful chronological baseline for the latest-quarter comparison.
        for reference in reversed(effective):
            try:
                snapshot = self.client.fetch_snapshot(reference)
                result = self.repository.save_snapshot(snapshot)
                processed += 1
                holdings_saved += result.holding_count
                if result.created:
                    created += 1
                elif result.refreshed:
                    refreshed += 1
                else:
                    unchanged += 1
            except Exception as exc:  # noqa: BLE001 - return per-accession diagnostics.
                errors.append(
                    FilingImportError(
                        accession_number=reference.accession_number,
                        message=str(exc),
                    )
                )

        return ImportRecentResult(
            manager_cik=canonical_cik,
            requested=len(effective),
            processed=processed,
            created=created,
            refreshed=refreshed,
            unchanged=unchanged,
            holdings_saved=holdings_saved,
            errors=tuple(errors),
        )

    def get_latest_analysis(self, cik: str) -> Optional[PortfolioAnalysis]:
        snapshots = self.repository.list_effective_snapshots(cik, limit=2)
        if not snapshots:
            return None
        previous = snapshots[1] if len(snapshots) > 1 else None
        return analyze_latest_holdings(snapshots[0], previous)
