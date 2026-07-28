"""Deterministic importance scoring. The LLM never controls this score."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Tuple

from src.personal_news.schemas import NewsCandidate


HIGH_IMPACT_TERMS = {
    "业绩预告", "盈利预警", "上调指引", "下调指引", "重大合同", "并购", "收购", "回购",
    "减持", "增持", "停牌", "复牌", "监管", "处罚", "调查", "召回", "诉讼", "破产",
    "关税", "制裁", "利率", "降息", "加息", "芯片出口", "earnings", "guidance", "merger",
    "acquisition", "buyback", "sanction", "tariff", "investigation", "recall",
}


def score_importance(candidate: NewsCandidate, watchlist: Iterable[str]) -> Tuple[int, list[str]]:
    watch = {item.strip().upper() for item in watchlist if item and item.strip()}
    score = 0
    reasons: list[str] = []
    text = f"{candidate.title} {candidate.summary}".casefold()

    if candidate.is_announcement or candidate.is_regulatory:
        score += 30
        reasons.append("公司或监管公告 +30")
    matched_symbols = sorted(watch.intersection(candidate.symbols))
    if matched_symbols:
        score += 25
        reasons.append(f"命中自选股 {','.join(matched_symbols)} +25")
    matched_terms = sorted(term for term in HIGH_IMPACT_TERMS if term.casefold() in text)
    if matched_terms:
        score += min(20, 8 + 4 * len(matched_terms))
        reasons.append(f"高影响事件 {','.join(matched_terms[:3])} +{min(20, 8 + 4 * len(matched_terms))}")
    reliability_points = round(candidate.source_reliability * 0.1)
    score += reliability_points
    reasons.append(f"来源可靠度 +{reliability_points}")
    if candidate.source_count >= 2:
        confirmation_points = min(10, (candidate.source_count - 1) * 5)
        score += confirmation_points
        reasons.append(f"{candidate.source_count} 个来源确认 +{confirmation_points}")
    if candidate.published_at is not None:
        now = datetime.now(timezone.utc)
        published = candidate.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (now - published.astimezone(timezone.utc)).total_seconds() / 3600)
        freshness_points = 10 if age_hours <= 6 else 5 if age_hours <= 24 else 0
        score += freshness_points
        if freshness_points:
            reasons.append(f"新闻时效 +{freshness_points}")
    if candidate.price_change_percent is not None and abs(candidate.price_change_percent) >= 3:
        score += 8
        reasons.append("明显价格变化 +8")
    if candidate.volume_change_percent is not None and abs(candidate.volume_change_percent) >= 50:
        score += 7
        reasons.append("明显成交量变化 +7")
    entity_points = round(candidate.entity_confidence * 0.1)
    score += entity_points
    reasons.append(f"实体匹配置信度 +{entity_points}")
    return min(score, 100), reasons
