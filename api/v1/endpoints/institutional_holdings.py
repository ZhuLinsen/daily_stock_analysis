# -*- coding: utf-8 -*-
"""Endpoints for importing and analyzing public SEC Form 13F holdings."""

from __future__ import annotations

import logging
import os

import requests
from api.deps import get_database_manager
from fastapi import APIRouter, Depends, HTTPException
from src.storage import DatabaseManager

from api.v1.schemas.institutional_holdings import (
    FilingImportErrorItem,
    FilingSnapshotItem,
    HoldingDeltaItem,
    InstitutionalHoldingAnalysisResponse,
    InstitutionalHoldingImportRequest,
    InstitutionalHoldingImportResponse,
)
from src.services.institutional_holdings_service import (
    PUBLIC_DISCLOSURE_DISCLAIMER,
    InstitutionalHoldingsService,
)
from src.services.sec_13f_service import (
    SEC_USER_AGENT_ENV,
    FilingSnapshotData,
    PortfolioAnalysis,
    Sec13FClient,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/import",
    response_model=InstitutionalHoldingImportResponse,
    summary="Import recent SEC 13F snapshots",
    description=(
        "Imports effective quarterly Form 13F accessions into filing_snapshots and "
        "filing_holdings. Requires SEC_USER_AGENT with a contact email."
    ),
)
def import_institutional_holdings(
    request: InstitutionalHoldingImportRequest,
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> InstitutionalHoldingImportResponse:
    try:
        client = Sec13FClient(user_agent=os.getenv(SEC_USER_AGENT_ENV, ""))
        result = InstitutionalHoldingsService(db_manager, client=client).import_recent(
            request.cik,
            max_filings=request.max_filings,
        )
        return InstitutionalHoldingImportResponse(
            manager_cik=result.manager_cik,
            requested=result.requested,
            processed=result.processed,
            created=result.created,
            refreshed=result.refreshed,
            unchanged=result.unchanged,
            holdings_saved=result.holdings_saved,
            errors=[
                FilingImportErrorItem(
                    accession_number=item.accession_number,
                    message=item.message,
                )
                for item in result.errors
            ],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_params", "message": str(exc)},
        ) from exc
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": "sec_unavailable", "message": str(exc)},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("SEC 13F import failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "SEC 13F import failed"},
        ) from exc


@router.get(
    "/{cik}/latest",
    response_model=InstitutionalHoldingAnalysisResponse,
    summary="Analyze the latest imported 13F snapshot",
    description="Compares share counts with the preceding report period and calculates concentration.",
)
def get_latest_institutional_holdings(
    cik: str,
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> InstitutionalHoldingAnalysisResponse:
    try:
        analysis = InstitutionalHoldingsService(db_manager).get_latest_analysis(cik)
        if analysis is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "not_found",
                    "message": "No imported 13F snapshots found for this CIK",
                },
            )
        return _analysis_response(analysis)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_params", "message": str(exc)},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("SEC 13F analysis failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "SEC 13F analysis failed"},
        ) from exc


def _snapshot_item(snapshot: FilingSnapshotData) -> FilingSnapshotItem:
    return FilingSnapshotItem(
        manager_cik=snapshot.reference.manager_cik,
        manager_name=snapshot.manager_name,
        form_type=snapshot.reference.form_type,
        accession_number=snapshot.reference.accession_number,
        report_period=snapshot.reference.report_period,
        filed_date=snapshot.reference.filed_date,
        accepted_at=snapshot.reference.accepted_at,
        entry_count=snapshot.entry_count,
        total_value_usd=snapshot.total_value_usd,
        primary_document_url=snapshot.primary_document_url,
        information_table_url=snapshot.information_table_url,
    )


def _analysis_response(analysis: PortfolioAnalysis) -> InstitutionalHoldingAnalysisResponse:
    return InstitutionalHoldingAnalysisResponse(
        manager_cik=analysis.current.reference.manager_cik,
        manager_name=analysis.current.manager_name,
        current=_snapshot_item(analysis.current),
        previous=_snapshot_item(analysis.previous) if analysis.previous else None,
        top_4_concentration_pct=analysis.top_4_concentration_pct,
        top_6_concentration_pct=analysis.top_6_concentration_pct,
        holdings=[
            HoldingDeltaItem(
                issuer_name=item.issuer_name,
                title_of_class=item.title_of_class,
                cusip=item.cusip,
                put_call=item.put_call,
                status=item.status,
                current_shares=item.current_shares,
                previous_shares=item.previous_shares,
                share_delta=item.share_delta,
                share_delta_pct=item.share_delta_pct,
                current_value_usd=item.current_value_usd,
                previous_value_usd=item.previous_value_usd,
                current_weight_pct=item.current_weight_pct,
            )
            for item in analysis.deltas
        ],
        disclosure_note=PUBLIC_DISCLOSURE_DISCLAIMER,
    )
