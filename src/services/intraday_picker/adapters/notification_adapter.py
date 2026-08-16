"""Reuse the existing DSA notification facade for intraday summaries."""

from __future__ import annotations

from typing import Sequence

from src.notification import NotificationService

from ..models import FinalCandidate, IntradayCandidate


def _strategy_labels(candidate: IntradayCandidate) -> str:
    ids = [hit.strategy_id for hit in candidate.strategy_hits]
    ids.extend(result.rule_id for result in candidate.confirmations if result.matched)
    return " + ".join(dict.fromkeys(ids)) or "-"


class DsaNotificationAdapter:
    def __init__(self):
        self.service = NotificationService()

    def send_preliminary(self, run_id: str, candidates: Sequence[IntradayCandidate]) -> None:
        lines = [f"## 早盘实时候选 Top{len(candidates)}", "", f"> run: `{run_id}`", ""]
        for idx, item in enumerate(candidates, 1):
            rvol = "--" if item.metrics.rvol_time is None else f"{item.metrics.rvol_time:.2f}x"
            sector = "--" if item.metrics.sector_score is None else f"{item.metrics.sector_score:.0f}"
            lines.extend(
                [
                    f"**{idx}. {item.stock_name or item.stock_code} ({item.stock_code}) — {item.picker_score:.1f}**",
                    f"- 涨幅 {item.change_pct:+.2f}% | 同期放量 {rvol} | 板块 {sector}",
                    f"- 命中：{_strategy_labels(item)}",
                    "",
                ]
            )
        lines.append("*初选为盘中量价筛选结果，DSA 深度分析在后台继续执行。* ")
        self.service.send("\n".join(lines), route_type="report", dedup_key=f"intraday-pre-{run_id}")

    def send_final(self, run_id: str, candidates: Sequence[FinalCandidate]) -> None:
        lines = [f"## DSA 早盘深度精选 Top{len(candidates)}", "", f"> run: `{run_id}`", ""]
        for idx, item in enumerate(candidates, 1):
            candidate = item.candidate
            dsa = item.dsa
            dsa_score = "--" if dsa is None or dsa.dsa_score is None else f"{dsa.dsa_score:.0f}"
            advice = dsa.operation_advice if dsa and dsa.operation_advice else "DSA未完成"
            lines.extend(
                [
                    f"**{idx}. {candidate.stock_name or candidate.stock_code} ({candidate.stock_code}) — {item.final_score:.1f}**",
                    f"- 盘中 {candidate.picker_score:.1f} | DSA {dsa_score} | {advice}",
                    f"- 命中：{_strategy_labels(candidate)}",
                    "",
                ]
            )
        lines.append("*仅用于研究与策略验证，不构成投资建议。*")
        self.service.send("\n".join(lines), route_type="report", dedup_key=f"intraday-final-{run_id}")
