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
from src.schemas.factor_contract import (
    FACTOR_CONTRACT_VERSION,
    FACTOR_SET_VERSION,
    CandidateFactorScore,
    CandidatePoolRun,
    FactorCategory,
    FactorDataQuality,
    FactorDefinition,
    FactorFieldStatus,
    FactorId,
    FactorSnapshot,
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
    "FACTOR_CONTRACT_VERSION",
    "FACTOR_SET_VERSION",
    "CandidateFactorScore",
    "CandidatePoolRun",
    "FactorCategory",
    "FactorDataQuality",
    "FactorDefinition",
    "FactorFieldStatus",
    "FactorId",
    "FactorSnapshot",
]
