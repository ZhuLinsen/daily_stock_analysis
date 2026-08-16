"""Application orchestration for the isolated intraday picker.

This module depends only on domain ports. Concrete DSA/AlphaSift/Pytdx
implementations are injected by ``runtime.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .config import IntradayPickerConfig
from .final_ranker import rank_final
from .metrics import calculate_intraday_metrics
from .models import IntradayCandidate, StrategyHit
from .scoring import rank_candidates
from .stock_analysis_rules import evaluate_rule
from .strategy_profiles import get_profile


def _num(mapping: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def merge_strategy_hits(hits: list[StrategyHit]) -> list[IntradayCandidate]:
    by_code: dict[str, IntradayCandidate] = {}
    for hit in hits:
        candidate = by_code.get(hit.stock_code)
        if candidate is None:
            candidate = IntradayCandidate(
                stock_code=hit.stock_code,
                stock_name=hit.stock_name,
                price=hit.price,
                change_pct=hit.change_pct,
                metadata=dict(hit.raw),
            )
            by_code[hit.stock_code] = candidate
        candidate.strategy_hits.append(hit)
        candidate.strategy_score = max(candidate.strategy_score, hit.strategy_score)
        if not candidate.stock_name and hit.stock_name:
            candidate.stock_name = hit.stock_name
        if hit.price:
            candidate.price = hit.price
        candidate.change_pct = hit.change_pct
        # Preserve a quality reference without making it an independent universe path.
        if hit.quality_score is not None:
            candidate.metadata["quality_score"] = hit.quality_score
        for key, value in hit.raw.items():
            candidate.metadata.setdefault(key, value)
    return list(by_code.values())


class IntradayPickerOrchestrator:
    def __init__(
        self,
        *,
        config: IntradayPickerConfig,
        strategy_gateway: Any,
        market_gateway: Any,
        history_repository: Any,
        dsa_gateway: Any,
        notification_gateway: Any,
        run_state: Any,
    ):
        self.config = config
        self.strategy_gateway = strategy_gateway
        self.market_gateway = market_gateway
        self.history_repository = history_repository
        self.dsa_gateway = dsa_gateway
        self.notification_gateway = notification_gateway
        self.run_state = run_state

    @staticmethod
    def run_id(now: datetime) -> str:
        return now.strftime("%Y%m%d-%H%M")

    def _enrich_candidate(self, candidate: IntradayCandidate, now: datetime) -> None:
        profile = get_profile(self.config.profile)
        for rule_id in profile.get("confirmations", ()):
            candidate.confirmations.append(evaluate_rule(rule_id, candidate))

        try:
            current = self.market_gateway.get_intraday_context(candidate.stock_code, now)
            history = self.history_repository.get_or_build_baseline(
                candidate.stock_code,
                now,
                self.market_gateway,
            )
        except Exception as exc:
            candidate.metadata.setdefault("source_errors", []).append(f"intraday:{exc}")
            current, history = {}, []

        raw = candidate.metadata
        sector_score = _num(raw, "board_heat_score", "theme_heat", "sector_score")
        breakout_score = _num(raw, "breakout_score", "signal_score", "breakout_20d")
        quality_score = _num(raw, "quality_score", "risk_quality_score")
        candidate.metrics = calculate_intraday_metrics(
            current,
            history,
            sector_score=sector_score,
            breakout_score=breakout_score,
            risk_quality_score=quality_score,
        )
        if current.get("price"):
            candidate.price = float(current["price"])

    def run_preliminary(self, now: datetime, *, force: bool = False, dry_run: bool = False) -> list[IntradayCandidate]:
        run_id = self.run_id(now)
        if not force and self.run_state.is_completed(run_id):
            return []

        hits = self.strategy_gateway.screen(self.config.profile, now)
        candidates = merge_strategy_hits(hits)
        for candidate in candidates:
            self._enrich_candidate(candidate, now)
        top = rank_candidates(candidates)[: self.config.top_n]

        self.run_state.save_preliminary(
            run_id,
            top,
            {
                "profile": self.config.profile,
                "candidate_count": len(candidates),
                "trigger_time": now.isoformat(),
                "dry_run": dry_run,
            },
        )
        if dry_run:
            return top

        if self.config.notify_preliminary:
            try:
                self.notification_gateway.send_preliminary(run_id, top)
            except Exception as exc:
                for candidate in top:
                    candidate.metadata.setdefault("source_errors", []).append(f"notify:{exc}")

        if self.config.dsa_enabled and top:
            try:
                refs = self.dsa_gateway.submit_or_reuse(top, now)
                self.run_state.save_dsa_tasks(run_id, refs)
            except Exception as exc:
                for candidate in top:
                    candidate.metadata.setdefault("source_errors", []).append(f"dsa_submit:{exc}")
        return top

    def finalize(self, run_id: str, candidates: list[IntradayCandidate], now: datetime):
        analyses = self.dsa_gateway.collect_available(candidates, now) if self.config.dsa_enabled else {}
        final = rank_final(candidates, analyses)[: self.config.final_top_n]
        self.run_state.save_final(run_id, final)
        if self.config.notify_final:
            try:
                self.notification_gateway.send_final(run_id, final)
            except Exception:
                pass
        return final
