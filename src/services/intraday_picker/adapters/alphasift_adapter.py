"""AlphaSift adapter for intraday candidate discovery.

This is the only intraday-picker module allowed to import the existing
AlphaSift bridge. It normalizes multiple possible AlphaSift result shapes and
keeps current AlphaSift endpoint/default behaviour untouched.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from src.config import get_config
from src.services.alphasift_service import AlphaSiftService

from ..config import IntradayPickerConfig
from ..models import StrategyHit
from ..strategy_profiles import get_profile


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_rows(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return
    if not isinstance(payload, dict):
        return
    for key in ("picks", "candidates", "results", "stocks", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item
            return
    nested = payload.get("result")
    if nested is not None:
        yield from _candidate_rows(nested)


class AlphaSiftStrategyAdapter:
    def __init__(self, picker_config: IntradayPickerConfig):
        self.picker_config = picker_config
        self._service = AlphaSiftService(config=get_config())

    def _run_strategy(self, strategy_id: str, max_results: int) -> list[StrategyHit]:
        payload = self._service.screen(
            strategy=strategy_id,
            market="cn",
            max_results=max_results,
        )
        hits: list[StrategyHit] = []
        for row in _candidate_rows(payload):
            code = str(row.get("code") or row.get("stock_code") or row.get("symbol") or "").strip()
            if not code:
                continue
            raw_score = row.get("final_score", row.get("score", row.get("strategy_score", 0)))
            hits.append(
                StrategyHit(
                    stock_code=code,
                    stock_name=str(row.get("name") or row.get("stock_name") or ""),
                    price=_num(row.get("price", row.get("current_price", 0))),
                    change_pct=_num(row.get("change_pct", row.get("pct_chg", row.get("涨跌幅", 0)))),
                    strategy_id=strategy_id,
                    strategy_score=_num(raw_score),
                    source="alphasift",
                    quality_score=_num(row.get("quality_score"), 0.0) if row.get("quality_score") is not None else None,
                    raw=dict(row),
                )
            )
        return hits

    def screen(self, profile: str, now: datetime) -> list[StrategyHit]:
        del now  # AlphaSift reads the current market snapshot itself.
        profile_config = get_profile(profile)
        hits: list[StrategyHit] = []
        for strategy_id in profile_config.get("alphasift", ()):
            try:
                hits.extend(self._run_strategy(strategy_id, self.picker_config.candidate_limit_per_strategy))
            except Exception:
                # Strategy isolation: one AlphaSift source/strategy failure must not
                # terminate the remaining candidate discovery paths.
                continue

        # Quality-reference strategies do not create extra universe breadth when a
        # stock is already present; they only attach a quality score when matched.
        quality_by_code: dict[str, float] = {}
        for strategy_id in profile_config.get("quality_reference", ()):
            try:
                for hit in self._run_strategy(strategy_id, min(20, self.picker_config.candidate_limit_per_strategy)):
                    quality_by_code[hit.stock_code] = hit.strategy_score
            except Exception:
                continue

        normalized: list[StrategyHit] = []
        for hit in hits:
            quality = quality_by_code.get(hit.stock_code, hit.quality_score)
            normalized.append(
                StrategyHit(
                    stock_code=hit.stock_code,
                    strategy_id=hit.strategy_id,
                    strategy_score=hit.strategy_score,
                    source=hit.source,
                    stock_name=hit.stock_name,
                    price=hit.price,
                    change_pct=hit.change_pct,
                    quality_score=quality,
                    raw=hit.raw,
                )
            )
        return normalized
