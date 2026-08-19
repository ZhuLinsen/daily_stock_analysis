# -*- coding: utf-8 -*-
"""
===================================
DSA Schemas
===================================

Pydantic schemas for report output validation and internal contracts.
"""

from src.schemas.analysis_context_pack import (
    PACK_VERSION,
    AnalysisContextBlock,
    AnalysisContextItem,
    AnalysisContextPack,
    AnalysisSubject,
    ContextFieldStatus,
    DataQuality,
)
from src.schemas.report_schema import AnalysisReportSchema

__all__ = [
    "AnalysisReportSchema",
    "PACK_VERSION",
    "AnalysisContextBlock",
    "AnalysisContextItem",
    "AnalysisContextPack",
    "AnalysisSubject",
    "ContextFieldStatus",
    "DataQuality",
]

from src.schemas.research_contracts import (
    Claim,
    ClaimKind,
    ConflictItem,
    ConflictResolutionStatus,
    ConflictType,
    EvidenceFreshness,
    EvidenceRef,
    FailMode,
    FrameworkOpinion,
    Horizon,
    HorizonDecision,
    IntegratedDecision,
    ProviderCapabilities,
    ProviderError,
    ProviderErrorCode,
    ProviderRole,
    Reproducibility,
    ResearchRequest,
    SCHEMA_VERSION,
    SensitiveLevel,
    Stance,
    to_json,
)
