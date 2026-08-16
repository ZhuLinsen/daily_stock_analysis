"""Small confirmation rules inspired by jiasanpang/stock_analysis.

These rules operate only on candidates already produced by AlphaSift. They do
not fetch data and are intentionally not a second full-market scanner.
"""

from __future__ import annotations

from typing import Any, Callable

from .models import IntradayCandidate, RuleResult


def _num(mapping: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def reversal_breakout(candidate: IntradayCandidate) -> RuleResult:
    raw = candidate.metadata
    change = candidate.change_pct
    change_60d = _num(raw, "change_pct_60d", "60日涨跌幅")
    volume_ratio = _num(raw, "volume_ratio", "量比")
    price = candidate.price
    ma20 = _num(raw, "ma20", "MA20")
    breakout = _num(raw, "breakout_20d", "breakout_score", "突破强度")

    reasons: list[str] = []
    score = 0.0
    if 1.0 <= change <= 7.5:
        score += 25
        reasons.append("当日价格出现向上确认")
    if volume_ratio >= 1.5:
        score += 25
        reasons.append("量能温和放大")
    if price > 0 and ma20 > 0 and price >= ma20:
        score += 20
        reasons.append("价格位于MA20之上")
    if breakout > 0:
        score += 20
        reasons.append("存在突破背景")
    if change_60d <= 40:
        score += 10
    matched = score >= 60
    return RuleResult("reversal_breakout", matched, score, reasons)


def buy_pullback(candidate: IntradayCandidate) -> RuleResult:
    raw = candidate.metadata
    change_60d = _num(raw, "change_pct_60d", "60日涨跌幅")
    volume_ratio = _num(raw, "volume_ratio", "量比")
    ma10 = _num(raw, "ma10", "MA10")
    ma20 = _num(raw, "ma20", "MA20")
    price = candidate.price
    change = candidate.change_pct

    score = 0.0
    reasons: list[str] = []
    if 8 <= change_60d <= 65:
        score += 30
        reasons.append("中期趋势已建立")
    if -2 <= change <= 2:
        score += 25
        reasons.append("处于温和回踩区间")
    if 0.5 <= volume_ratio <= 1.5:
        score += 20
        reasons.append("回踩量能健康")
    if price > 0 and ma20 > 0 and price >= ma20:
        score += 15
        reasons.append("未跌破MA20")
    if price > 0 and ma10 > 0 and (price - ma10) / ma10 * 100 <= 5:
        score += 10
        reasons.append("靠近MA10支撑")
    return RuleResult("buy_pullback", score >= 65, score, reasons)


def bottom_reversal(candidate: IntradayCandidate) -> RuleResult:
    raw = candidate.metadata
    change_60d = _num(raw, "change_pct_60d", "60日涨跌幅")
    volume_ratio = _num(raw, "volume_ratio", "量比")
    market_cap = _num(raw, "market_cap", "总市值")
    change = candidate.change_pct

    score = 0.0
    reasons: list[str] = []
    if -25 <= change_60d <= -10:
        score += 35
        reasons.append("60日跌幅处于反转观察区")
    if 1 <= change <= 5:
        score += 25
        reasons.append("当日出现反转确认")
    if volume_ratio >= 1.2:
        score += 25
        reasons.append("企稳后量能开始恢复")
    elif 0.7 <= volume_ratio < 1.2:
        score += 10
    if 0 < market_cap <= 300:
        score += 15
        reasons.append("市值处于反转策略偏好区间")
    return RuleResult("bottom_reversal", score >= 65, score, reasons)


RULES: dict[str, Callable[[IntradayCandidate], RuleResult]] = {
    "reversal_breakout": reversal_breakout,
    "buy_pullback": buy_pullback,
    "bottom_reversal": bottom_reversal,
}


def evaluate_rule(rule_id: str, candidate: IntradayCandidate) -> RuleResult:
    rule = RULES.get(rule_id)
    if rule is None:
        return RuleResult(rule_id, False, 0.0, ["unknown confirmation rule"])
    return rule(candidate)
