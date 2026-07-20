"""Read-only Feishu display adapters for stock and US macro reports.

These helpers deliberately translate already-produced structured results only.
They must not collect data, call an LLM, or mutate report history.
"""

from __future__ import annotations

from typing import Any

from src.schemas.macro import USMacroAIExplanation, USMacroSnapshot


STOCK_DISCLAIMER = "仅供信息参考，不构成投资建议。"
MACRO_DISCLAIMER = "仅供宏观信息参考，不构成投资建议。"

_TREND_LABELS = {
    "强烈看多": "明显偏多",
    "看多": "偏多",
    "震荡": "震荡",
    "看空": "偏空",
    "强烈看空": "明显偏空",
}
_PROVIDER_LABELS = {
    "EfinanceFetcher": "东方财富",
    "TencentFetcher": "腾讯财经",
    "efinance": "东方财富",
    "tencent": "腾讯财经",
}
_REGIME_LABELS = {
    "neutral": "中性",
    "risk_on": "风险偏好改善",
    "risk_off": "风险偏好走弱",
    "mixed": "分化",
}
_MACRO_INDICATOR_LABELS = {
    "policy_rate_lower": "美联储目标利率下限",
    "policy_rate_upper": "美联储目标利率上限",
    "effective_fed_funds_rate": "有效联邦基金利率",
    "sofr": "SOFR",
    "treasury_2y": "美国2年期国债收益率",
    "treasury_10y": "美国10年期国债收益率",
    "vix": "VIX",
}


def build_stock_feishu_message(raw: dict[str, Any], context: dict[str, Any] | None = None) -> str:
    """Render one compact stock message from an already-persisted result."""
    context = context or {}
    name = str(raw.get("name") or "未知标的")
    code = str(raw.get("code") or "未知代码")
    dashboard = raw.get("dashboard") if isinstance(raw.get("dashboard"), dict) else {}
    phase = dashboard.get("phase_decision") if isinstance(dashboard.get("phase_decision"), dict) else {}
    enhanced = context.get("enhanced_context") if isinstance(context.get("enhanced_context"), dict) else {}
    today = enhanced.get("today") if isinstance(enhanced.get("today"), dict) else {}

    lines = [
        f"{name}｜{code}｜股票分析",
        f"数据日期：{_effective_daily_date(phase, today, raw) or '未知'}",
        f"模型观点：{raw.get('operation_advice') or '观望'}",
        f"综合评分：{_number(raw.get('sentiment_score'))}",
        f"趋势判断：{_trend_label(raw.get('trend_prediction'))}",
    ]
    reasons = _stock_reasons(enhanced, raw)
    if reasons:
        lines.append("核心依据：")
        lines.extend(f"• {reason}" for reason in reasons[:3])
    watch = _watch_condition(phase, raw.get("trend_prediction"))
    if watch:
        lines.extend(["关注条件：", watch])
    sources = _stock_sources(raw, enhanced)
    if sources:
        lines.append(f"数据来源：{'｜'.join(sources)}")
    limitations = _stock_limitations(phase, raw)
    if limitations:
        lines.append(f"数据限制：{_format_limitations(limitations)}")
    lines.append(STOCK_DISCLAIMER)
    return "\n".join(lines)


def build_us_macro_feishu_messages(
    snapshot: USMacroSnapshot,
    assessment: dict[str, Any],
    explanation: USMacroAIExplanation | None = None,
) -> list[str]:
    """Render the three US macro messages without changing deterministic output."""
    report_date = snapshot.as_of.date().isoformat()
    horizons = assessment.get("horizons") or {}
    core = [f"美国宏观市场晨报｜核心结论｜{report_date}", f"市场环境：{_regime_label(assessment.get('regime'))}"]
    for key, aliases in (("下一交易日", ("下一交易日", "当日或下一交易日")), ("未来1周", ("未来1周",)), ("未来1个月", ("未来1个月",))):
        item = next((horizons.get(alias) for alias in aliases if horizons.get(alias)), {})
        core.append(f"{key}：{_direction_label(item.get('direction'))}｜{_confidence_label(item.get('confidence'))}")
    drivers = (horizons.get("未来1周") or {}).get("drivers") or []
    if drivers:
        core.extend(["核心判断：", "；".join(str(item) for item in drivers[:2])])
    if snapshot.missing_indicators or snapshot.warnings:
        core.append("市场行情缺失，缺少风险资产交叉验证。")
    core.extend(["数据状态：", f"利率与债券：{len(snapshot.observations)}/7", f"市场行情：{len(snapshot.market_data)}/9"])

    rates = [f"美国宏观市场晨报｜利率与债券｜{report_date}"]
    observations = {item.indicator: item for item in snapshot.observations}
    lower = observations.get("policy_rate_lower")
    upper = observations.get("policy_rate_upper")
    if lower and upper:
        rates.append(f"美联储目标利率区间：{lower.value:.2f}%–{upper.value:.2f}%")
    for indicator in ("effective_fed_funds_rate", "sofr", "treasury_2y", "treasury_10y", "vix"):
        item = observations.get(indicator)
        if item:
            rates.append(_format_macro_observation(item))
    curve = _curve_basis_points(observations.get("treasury_2y"), observations.get("treasury_10y"))
    if curve is not None:
        rates.append(f"2Y–10Y利差：{curve:+.0f}bp")
    rates.append("数据来源：FRED")

    narrative = [f"美国宏观市场晨报｜解释与风险｜{report_date}"]
    if explanation:
        narrative.extend(_narrative_lines(explanation))
    else:
        narrative.extend(["核心逻辑：", "当前解释暂不可用，结论仍以已展示的确定性规则为准。"])
    if not snapshot.market_data:
        narrative.extend(["数据限制：", "当前股指、美元和商品行情不可用，本次解释主要基于利率、国债收益率和VIX数据。"])
    elif snapshot.missing_indicators or snapshot.warnings:
        narrative.extend(["数据限制：", "部分指标不可用或存在延迟，结论已按程序规则降级。"])
    narrative.append(MACRO_DISCLAIMER)
    return ["\n".join(core), "\n".join(rates), "\n".join(narrative)]


def _stock_reasons(enhanced: dict[str, Any], raw: dict[str, Any]) -> list[str]:
    trend = enhanced.get("trend_analysis") if isinstance(enhanced.get("trend_analysis"), dict) else {}
    chip = enhanced.get("chip") if isinstance(enhanced.get("chip"), dict) else {}
    reasons: list[str] = []
    alignment = str(trend.get("ma_alignment") or "").strip()
    if alignment:
        reasons.append(f"均线状态：{alignment}")
    bias = trend.get("bias_ma5")
    if isinstance(bias, (int, float)) and abs(bias) >= 5:
        direction = "短线涨幅偏大" if bias > 0 else "短线偏离均线较大"
        reasons.append(f"5日乖离率{bias:.2f}%，{direction}")
    chip_status = str(chip.get("chip_status") or "").strip()
    if chip_status:
        reasons.append(f"筹码状态：{chip_status}")
    risk_factors = [str(item).lstrip("⚠️❌✅ ").strip() for item in trend.get("risk_factors", []) if str(item).strip()]
    reasons.extend(risk_factors)
    if reasons:
        return _unique(reasons)
    summary = raw.get("key_points") or raw.get("ma_analysis") or raw.get("technical_analysis")
    return [str(summary).strip()] if summary else []


def _watch_condition(phase: dict[str, Any], trend_prediction: Any) -> str | None:
    conditions = phase.get("watch_conditions") if isinstance(phase.get("watch_conditions"), list) else []
    for condition in conditions:
        text = str(condition).strip()
        if text:
            text = text.split("：", 1)[-1].strip()
            if _contains_directive(text):
                return _neutral_risk_condition(trend_prediction)
            return text
    return "等待趋势和量能出现进一步确认。" if phase else None


def _stock_sources(raw: dict[str, Any], enhanced: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    today = enhanced.get("today") if isinstance(enhanced.get("today"), dict) else {}
    yesterday = enhanced.get("yesterday") if isinstance(enhanced.get("yesterday"), dict) else {}
    realtime = enhanced.get("realtime") if isinstance(enhanced.get("realtime"), dict) else {}
    for source in (yesterday.get("data_source"), today.get("data_source"), realtime.get("source"), raw.get("data_sources")):
        if not source:
            continue
        for part in str(source).replace(",", "|").split("|"):
            label = _provider_label(part)
            if label and not _same_provider(label, sources):
                sources.append(label)
    return sources


def _stock_limitations(phase: dict[str, Any], raw: dict[str, Any]) -> list[str]:
    limits = phase.get("data_limitations") if isinstance(phase.get("data_limitations"), list) else []
    rendered: list[str] = []
    volume_quality_issue = False
    for limit in limits:
        text = str(limit).strip()
        if not text or text == "technical: partial":
            continue
        if "成交量" in text and any(marker in text for marker in ("异常", "失真", "降权")):
            volume_quality_issue = True
            continue
        text = text.replace("技术指标为partial状态", "部分技术指标数据不完整").replace("技术面数据为partial状态", "部分技术指标数据不完整")
        text = text.replace("技术面数据标记为partial", "部分技术指标数据不完整")
        text = text.replace("（intraday_realtime_overlay）", "").replace("intraday_realtime_overlay", "")
        text = text.split("：", 1)[-1].strip()
        if text and text not in rendered:
            rendered.append(text)
    if volume_quality_issue:
        rendered.append("成交量数据存在异常，相关量价信号已从本次判断中降权或忽略")
    if not raw.get("news_summary") or "暂无" in str(raw.get("news_summary")):
        rendered.append("暂未获取到有效新闻")
    return rendered[:3]


def _format_macro_observation(item: Any) -> str:
    label = _MACRO_INDICATOR_LABELS.get(item.indicator, item.indicator)
    unit = "点" if item.unit == "Index" else "%" if item.unit == "Percent" else (item.unit or "")
    value = f"{item.value:.2f}{unit}"
    return f"{label}：{value}｜{item.observation_date.isoformat()}"


def _curve_basis_points(two_year: Any, ten_year: Any) -> float | None:
    if two_year is None or ten_year is None:
        return None
    return (ten_year.value - two_year.value) * 100


def _narrative_lines(explanation: USMacroAIExplanation) -> list[str]:
    sections = [
        ("核心逻辑", explanation.core_logic),
        ("利多因素", "；".join(explanation.bullish_factors[:3])),
        ("利空因素", "；".join(explanation.bearish_factors[:3])),
        ("风险", "；".join(explanation.risks[:3])),
        ("失效条件", "；".join(explanation.invalidation_conditions[:3])),
    ]
    lines: list[str] = []
    for title, content in sections:
        if content:
            lines.extend([f"{title}：", str(content)])
    return lines


def _market_date(raw: dict[str, Any]) -> str | None:
    snapshot = raw.get("market_snapshot") if isinstance(raw.get("market_snapshot"), dict) else {}
    value = snapshot.get("date")
    return str(value) if value else None


def _effective_daily_date(phase: dict[str, Any], today: dict[str, Any], raw: dict[str, Any]) -> str | None:
    context = phase.get("phase_context") if isinstance(phase.get("phase_context"), dict) else {}
    return str(context.get("effective_daily_bar_date") or today.get("date") or _market_date(raw) or "") or None


def _provider_label(value: Any) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    if text in _PROVIDER_LABELS:
        return _PROVIDER_LABELS[text]
    lowered = text.lower()
    if "efinance" in lowered or "eastmoney" in lowered:
        return "东方财富日线"
    if "tencent" in lowered:
        return "腾讯财经实时行情"
    return None


def _same_provider(label: str, sources: list[str]) -> bool:
    normalized = label.replace("实时行情", "")
    return any(source.replace("实时行情", "") == normalized for source in sources)


def _contains_directive(text: str) -> bool:
    return any(token in text for token in ("止损", "离场", "卖出", "减仓", "加仓", "建仓"))


def _neutral_risk_condition(trend_prediction: Any) -> str:
    trend = _trend_label(trend_prediction)
    if "偏空" in trend:
        return "关注下一个交易日能否止跌并重新站回短期均线；若继续走弱，当前偏空判断仍然有效。"
    return "关注下一个交易日的趋势与量能确认；若走势继续走弱，当前判断仍然有效。"


def _format_limitations(limitations: list[str]) -> str:
    clean: list[str] = []
    for item in limitations:
        text = str(item).strip().strip("。； ")
        if text and text not in clean:
            clean.append(text)
    return "；".join(clean) + "。"


def _number(value: Any) -> str:
    return str(value) if value is not None else "--"


def _trend_label(value: Any) -> str:
    return _TREND_LABELS.get(str(value), str(value or "未知"))


def _regime_label(value: Any) -> str:
    return _REGIME_LABELS.get(str(value), str(value or "未知"))


def _direction_label(value: Any) -> str:
    return _regime_label(value)


def _confidence_label(value: Any) -> str:
    text = str(value or "低")
    return text if text.endswith("置信度") else f"{text}置信度"


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
