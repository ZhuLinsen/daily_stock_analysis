"""Deterministic US macro scoring. LLMs may explain, never override this output."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal['明显偏多', '偏多', '中性', '偏空', '明显偏空']
Confidence = Literal['低', '中', '高']


@dataclass(frozen=True)
class MarketSignal:
    name: str
    score: int
    reason: str
    source_indicators: list[str]


def _direction(score: int, enough_data: bool) -> tuple[Direction, Confidence]:
    if not enough_data: return '中性', '低'
    if score >= 5: return '明显偏多', '高'
    if score >= 2: return '偏多', '中'
    if score <= -5: return '明显偏空', '高'
    if score <= -2: return '偏空', '中'
    return '中性', '低'


def assess_us_macro(market_data: list[dict], observations: list[dict]) -> dict:
    market = {item['indicator']: item for item in market_data}
    rates = {item['indicator']: item for item in observations}
    signals: list[MarketSignal] = []
    vix = market.get('vix')
    spx = market.get('sp500')
    if vix and vix.get('change_5d') is not None:
        signals.append(MarketSignal('vix_5d', -2 if vix['change_5d'] > 10 else (1 if vix['change_5d'] < -10 else 0), 'VIX五日变化反映风险偏好', ['vix']))
    if spx and spx.get('above_ma_20') is not None:
        signals.append(MarketSignal('spx_trend', 2 if spx['above_ma_20'] and spx.get('above_ma_50') else -2 if not spx['above_ma_20'] else 0, '标普500相对中期均线', ['sp500']))
    two, ten = rates.get('treasury_2y'), rates.get('treasury_10y')
    if two and ten and two.get('value') is not None and ten.get('value') is not None:
        spread = ten['value'] - two['value']
        signals.append(MarketSignal('curve', 1 if spread > 0 else -1, f'2Y-10Y利差为{spread:.2f}个百分点', ['treasury_2y', 'treasury_10y']))
    score = sum(signal.score for signal in signals)
    enough = len(signals) >= 2
    direction, confidence = _direction(score, enough)
    regime = 'risk_on' if enough and score >= 3 else 'risk_off' if enough and score <= -3 else 'mixed' if enough and score else 'neutral'
    horizons = {name: {'direction': direction, 'confidence': confidence, 'score': score, 'drivers': [s.reason for s in signals], 'source_indicator_ids': [key for s in signals for key in s.source_indicators]} for name in ('当日或下一交易日', '未来1周', '未来1个月')}
    return {'regime': regime, 'signals': [s.__dict__ for s in signals], 'horizons': horizons, 'warning': None if enough else '数据不足或信号相互冲突'}
