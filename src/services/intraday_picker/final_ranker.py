"""Combine real-time picker score with available DSA analysis."""

from __future__ import annotations

from .models import DsaAnalysisSummary, FinalCandidate, IntradayCandidate
from .scoring import clamp


def rank_final(
    candidates: list[IntradayCandidate],
    analyses: dict[str, DsaAnalysisSummary],
) -> list[FinalCandidate]:
    ranked: list[FinalCandidate] = []
    for candidate in candidates:
        dsa = analyses.get(candidate.stock_code)
        if dsa is not None and dsa.dsa_score is not None:
            final_score = candidate.picker_score * 0.65 + clamp(dsa.dsa_score) * 0.35
        else:
            final_score = candidate.picker_score
        ranked.append(FinalCandidate(candidate=candidate, dsa=dsa, final_score=clamp(final_score)))
    return sorted(ranked, key=lambda item: item.final_score, reverse=True)
