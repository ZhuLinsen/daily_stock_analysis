# -*- coding: utf-8 -*-
"""Structured report ViewModel for channel-native notifications and HTML export."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.market_phase_summary import format_public_market_status_line
from src.report_language import (
    get_localized_stock_name,
    get_report_labels,
    get_signal_level,
    localize_conflict_severity,
    localize_consensus_level,
    localize_strategy_signal,
    localize_strategy_skill,
    localize_strategy_synthesis_summary,
    localize_trend_prediction,
    normalize_report_language,
    normalize_strategy_synthesis_payload,
    strategy_invalid_opinion_count,
)
from src.schemas.decision_action import (
    display_action_fields_for_result,
    display_decision_type_for_result,
    display_operation_advice_for_result,
)
from src.services.empty_news import empty_news_disclosure
from src.utils.data_processing import (
    normalize_model_used,
    signal_attribution_has_content,
    signal_attribution_weight_items,
)

_INDICATOR_PREFIX_RE = re.compile(r"(?:MA|BOLL|RSI|KDJ|MACD|WR|BIAS|T\+)\s*(?:\d+\s*/\s*)*$", re.IGNORECASE)
_NON_PRICE_UNIT_RE = re.compile(
    r"^(?:%|percent(?:age)?\b|百分之|퍼센트|日|周|週|月|年|天|个交易日|倍|거래일|일|주|개월|년|배"
    r"|(?:[-‐‑–]\s*)?(?:(?:trading\s+)?(?:days?|sessions?|periods?)|weeks?|months?|years?|times?|x|d)\b)",
    re.IGNORECASE,
)
_MA_PERIOD_LIST_RE = re.compile(
    r"\b\d+(?:\.\d+)?(?:(?:\s*[-‐‑–—/,、·，]+\s*(?:(?:and|or|to|&|和|및|와)\s*)?"
    r"|\s+(?:and|or|to|&|和|및|와)\s*|(?:和|및|와)\s*)\d+(?:\.\d+)?){1,}\s*"
    r"(?:[-‐‑–—]\s*)?(?:(?:trading\s+)?(?:days?|sessions?|periods?|weeks?|months?|years?|d)"
    r"|日|周|週|月|年|天|거래일|일|주|개월|년|배|MA|moving\s+averages?)(?![A-Za-z])",
    re.IGNORECASE | re.UNICODE,
)
_CURRENT_PRICE_CTX_RE = re.compile(
    r"(?:current|latest|last|market)\s+price(?:\s+(?:is|of|at))?\s*[:：]?\s*(?:about|around|approx(?:imately)?)?\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$",
    re.IGNORECASE,
)
_CJK_CURRENT_PRICE_CTX_RE = re.compile(
    r"(?:当前价(?:格)?|目前价(?:格)?|现价)\s*(?:(?:约|大约)\s*)?(?:(?:是|为|在)\s*)?(?:[:：]\s*)?(?:(?:约|大约)\s*)?(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$",
    re.UNICODE,
)
_KO_CURRENT_PRICE_CTX_RE = re.compile(
    r"(?:현재\s*가격?|시세)\s*(?:는|이|가)?\s*(?:[:：]\s*)?약?\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)?$",
    re.UNICODE,
)
_PRICE_UNIT_AFTER_RE = re.compile(
    r"^\s*(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY|dollars?|euros?)\b|元|美元|美金|港元|港币|港幣|日元|新台币|新臺幣|円|원)",
    re.IGNORECASE | re.UNICODE,
)
_PRICE_UNIT_BEFORE_RE = re.compile(r"(?:[$¥₩]|(?:USD|CNY|HKD|TWD|KRW|JPY)\s*)$", re.IGNORECASE | re.UNICODE)
_RATIO_CTX_RE = re.compile(
    r"(?:risk\s*[-/]?\s*(?:to\s*[-/]?\s*)?(?:reward|return)|reward\s*(?:[-/]?\s*to\s*[-/]?\s*risk|[-/]\s*risk)"
    r"|risk\s*reward|ratio|R\s*/\s*R|风险\s*(?:回报|收益)|回报比|收益比|比率|손익\s*비)",
    re.IGNORECASE | re.UNICODE,
)
_RATIO_PAIR_RE = re.compile(r"\d+(?:\.\d+)?\s*([:：∶︓﹕꞉/／]|比|to)\s*\d+(?:\.\d+)?", re.IGNORECASE)
_DATE_RE = re.compile(
    r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*(?:日|号)|\b\d{1,2}[/-]\d{1,2}\b",
    re.IGNORECASE | re.UNICODE,
)
_SNIPER_PREFIXES = (
    "理想买入点：",
    "次优买入点：",
    "止损位：",
    "目标位：",
    "理想买入点:",
    "次优买入点:",
    "止损位:",
    "目标位:",
    "Ideal Entry:",
    "Secondary Entry:",
    "Stop Loss:",
    "Target:",
)
_NA_STRINGS = {"", "-", "—", "n/a", "na", "none", "null", "unknown"}


@dataclass
class SniperLevels:
    """Structured strategy price points and derived risk/reward metrics."""

    ideal_buy: str = ""
    secondary_buy: str = ""
    stop_loss: str = ""
    take_profit: str = ""
    ideal_buy_num: Optional[float] = None
    secondary_buy_num: Optional[float] = None
    stop_loss_num: Optional[float] = None
    take_profit_num: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
    upside_pct: Optional[float] = None
    downside_pct: Optional[float] = None
    ref_basis: str = ""
    price_zone: str = ""


@dataclass
class PositionAdvice:
    """Position-aware execution guidance."""

    no_position: str = ""
    has_position: str = ""
    suggested_position: str = ""
    entry_plan: str = ""
    risk_control: str = ""


@dataclass
class SignalAttributionItem:
    """Structured signal attribution weights and extreme signals."""

    weights: List[Tuple[str, float]] = field(default_factory=list)
    strongest_bullish: str = ""
    strongest_bearish: str = ""


@dataclass
class StrategySkillItem:
    """Per-strategy opinion entry for structured synthesis rendering."""

    skill_id: str
    display_name: str
    signal: str
    signal_display: str
    confidence_pct: Optional[int] = None


@dataclass
class StrategySynthesisView:
    """Structured multi-strategy consensus and conflict view for renderers."""

    final_signal: str
    final_signal_display: str
    consensus_level: str
    consensus_display: str
    conflict_severity: str
    conflict_display: str
    conflict_count: int = 0
    confidence_pct: Optional[int] = None
    opinion_count: int = 0
    invalid_opinion_count: int = 0
    summary: str = ""
    supporting_skills: List[StrategySkillItem] = field(default_factory=list)
    opposing_skills: List[StrategySkillItem] = field(default_factory=list)
    minority_view_preserved: bool = False


@dataclass
class RiskAlertEntry:
    """Risk alert item for Alert-First top callout."""

    stock_code: str
    stock_name: str
    message: str
    severity: str = "medium"


@dataclass
class StockReportItem:
    """Per-stock ViewModel shared across IM, Email, and standalone HTML renderers."""

    code: str
    name: str
    display_name: str
    action: str
    decision_bucket: str
    signal_text: str
    signal_emoji: str
    sentiment_score: Optional[int]
    trend_prediction: str
    current_price: Optional[float] = None
    change_pct: Optional[float] = None
    price_display: str = ""
    change_display: str = ""
    one_sentence: str = ""
    time_sensitivity: str = ""
    sniper: SniperLevels = field(default_factory=SniperLevels)
    position_advice: PositionAdvice = field(default_factory=PositionAdvice)
    risk_alerts: List[str] = field(default_factory=list)
    positive_catalysts: List[str] = field(default_factory=list)
    sentiment_summary: str = ""
    earnings_outlook: str = ""
    latest_news: str = ""
    checklist: List[str] = field(default_factory=list)
    failed_checks: List[str] = field(default_factory=list)
    signal_attribution: Optional[SignalAttributionItem] = None
    strategy_synthesis_summary: str = ""
    strategy_synthesis: Optional[StrategySynthesisView] = None
    empty_news_disclosure: str = ""
    data_sources: str = ""
    model_used: str = ""
    has_urgent_risk: bool = False
    has_risk_assessment: bool = False
    market_snapshot: Dict[str, Any] = field(default_factory=dict)
    analysis_summary: str = ""

    @property
    def score_display(self) -> str:
        return str(self.sentiment_score) if self.sentiment_score is not None else "—"


@dataclass
class NotificationReportPayload:
    """Canonical structured report payload consumed by channel-native renderers."""

    report_date: str
    generated_at: str
    report_language: str
    single_stock: bool
    summary_only: bool
    dynamic_title: str
    header_tone: str
    total_count: int
    buy_count: int
    hold_count: int
    sell_count: int
    alert_count: int
    avg_score: float
    market_status_line: str
    risk_checked_count: int = 0
    top_risk_alerts: List[RiskAlertEntry] = field(default_factory=list)
    stocks: List[StockReportItem] = field(default_factory=list)
    models_used: List[str] = field(default_factory=list)
    web_url: str = ""
    disclaimer: str = ""
    raw_markdown_fallback: str = ""


def _safe_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if parsed == parsed and abs(parsed) != float("inf") else None
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    parsed = _safe_float(value)
    if parsed is None:
        return default
    return int(round(parsed))


def _clean_sniper_value(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() in _NA_STRINGS:
        return ""
    for prefix in _SNIPER_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
            break
    return "" if s.lower() in _NA_STRINGS else s


def _is_ratio_candidate(segment: str, start: int, end: int) -> bool:
    for match in _RATIO_PAIR_RE.finditer(segment):
        m_start, m_end = match.span()
        if start < m_start or end > m_end:
            continue
        if _PRICE_UNIT_AFTER_RE.search(segment[m_end:]) or _PRICE_UNIT_BEFORE_RE.search(segment[:m_start]):
            continue
        sep = match.group(1).lower()
        nearby = segment[max(0, m_start - 40): min(len(segment), m_end + 40)]
        needs_ctx = sep in {"/", "／", "to"}
        if not needs_ctx or _RATIO_CTX_RE.search(nearby):
            return True
    return False


def _is_date_candidate(segment: str, start: int, end: int) -> bool:
    for match in _DATE_RE.finditer(segment):
        m_start, m_end = match.span()
        raw = match.group(0)
        if re.fullmatch(r"\d{1,2}[/-]\d{1,2}", raw):
            parts = re.split(r"[/-]", raw)
            month, day = int(parts[0]), int(parts[1])
            if month > 31 or day > 31 or (month > 12 and day > 12):
                continue
            if _PRICE_UNIT_AFTER_RE.search(segment[m_end:]) or _PRICE_UNIT_BEFORE_RE.search(segment[:m_start]):
                continue
        if start >= m_start and end <= m_end:
            return True
    return False


def _is_ma_period(segment: str, start: int, end: int) -> bool:
    prefix = segment[:start]
    suffix = segment[end:].lstrip()
    if _INDICATOR_PREFIX_RE.search(prefix) or _NON_PRICE_UNIT_RE.match(suffix):
        return True
    for match in _MA_PERIOD_LIST_RE.finditer(segment):
        if start >= match.start() and end <= match.end():
            return True
    return False


def _is_current_price_annotation(segment: str, start: int) -> bool:
    prefix = segment[:start]
    return bool(
        _CURRENT_PRICE_CTX_RE.search(prefix)
        or _CJK_CURRENT_PRICE_CTX_RE.search(prefix)
        or _KO_CURRENT_PRICE_CTX_RE.search(prefix)
    )


def parse_price_number(text: Any) -> Optional[float]:
    """Extract the primary numeric price level while skipping dates, ratios, MA periods, and %."""
    if text is None or isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        val = float(text)
        return val if val == val and val > 0 else None

    raw = str(text).strip()
    if not raw or raw.lower() in _NA_STRINGS:
        return None

    for segment in re.split(r"[\n\r]+|(?<=\d)\s*[;；]\s*", raw):
        seg = segment.strip()
        if not seg:
            continue
        cleaned = seg.replace(",", "")
        for match in re.finditer(r"\d+(?:\.\d+)?", cleaned):
            start, end = match.span()
            if _is_ratio_candidate(cleaned, start, end):
                continue
            if _is_date_candidate(cleaned, start, end):
                continue
            if _is_ma_period(cleaned, start, end):
                continue
            if _is_current_price_annotation(cleaned, start):
                continue
            try:
                val = float(match.group(0))
            except ValueError:
                continue
            if val > 0 and val == val:
                return val
    return None


def _is_scale_compatible(a: Optional[float], b: Optional[float], *, max_ratio: float = 5.0) -> bool:
    if a is None or b is None or a <= 0 or b <= 0:
        return True
    return max(a / b, b / a) <= max_ratio


def _compute_sniper_levels(
    raw_sniper: Mapping[str, Any],
    *,
    current_price: Optional[float] = None,
    suppress_bullish_rr: bool = False,
) -> SniperLevels:
    ideal_buy = _clean_sniper_value(raw_sniper.get("ideal_buy"))
    secondary_buy = _clean_sniper_value(raw_sniper.get("secondary_buy"))
    stop_loss = _clean_sniper_value(raw_sniper.get("stop_loss"))
    take_profit = _clean_sniper_value(raw_sniper.get("take_profit"))

    ideal_num = parse_price_number(ideal_buy)
    secondary_num = parse_price_number(secondary_buy)
    stop_num = parse_price_number(stop_loss)
    target_num = parse_price_number(take_profit)

    ref_num: Optional[float] = None
    ref_basis = ""
    if ideal_num and _is_scale_compatible(ideal_num, current_price):
        ref_num = ideal_num
        ref_basis = "ideal_buy"
    elif current_price and current_price > 0:
        ref_num = current_price
        ref_basis = "current"

    price_zone = ""
    if (
        stop_num
        and target_num
        and stop_num < target_num
        and current_price is not None
        and current_price > 0
        and _is_scale_compatible(stop_num, target_num)
        and _is_scale_compatible(current_price, stop_num)
        and _is_scale_compatible(current_price, target_num)
    ):
        if current_price < stop_num:
            price_zone = "below_stop"
        elif current_price > target_num:
            price_zone = "above_target"
        else:
            price_zone = "in_range"

    rr_ratio: Optional[float] = None
    upside_pct: Optional[float] = None
    downside_pct: Optional[float] = None

    if (
        not suppress_bullish_rr
        and ref_num
        and stop_num
        and target_num
        and stop_num < ref_num < target_num
        and _is_scale_compatible(stop_num, ref_num)
        and _is_scale_compatible(target_num, ref_num)
        and _is_scale_compatible(target_num, stop_num)
    ):
        risk = ref_num - stop_num
        reward = target_num - ref_num
        if risk > 0 and reward > 0:
            rr_ratio = round(reward / risk, 2)
            upside_pct = round((reward / ref_num) * 100.0, 1)
            downside_pct = round((risk / ref_num) * 100.0, 1)

    return SniperLevels(
        ideal_buy=ideal_buy,
        secondary_buy=secondary_buy,
        stop_loss=stop_loss,
        take_profit=take_profit,
        ideal_buy_num=ideal_num,
        secondary_buy_num=secondary_num,
        stop_loss_num=stop_num,
        take_profit_num=target_num,
        risk_reward_ratio=rr_ratio,
        upside_pct=upside_pct,
        downside_pct=downside_pct,
        ref_basis=ref_basis,
        price_zone=price_zone,
    )


def _normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        items: List[str] = []
        for entry in value:
            text = str(entry).strip() if entry is not None else ""
            if text:
                items.append(text)
        return items
    text = str(value).strip()
    return [text] if text else []


def _format_price_display(price: Optional[float]) -> str:
    if price is None:
        return ""
    if price >= 1000:
        return f"{price:,.2f}"
    if price >= 100:
        return f"{price:.2f}"
    if price >= 1:
        return f"{price:.2f}"
    return f"{price:.4f}".rstrip("0").rstrip(".")


def _format_change_display(change_pct: Optional[float]) -> str:
    if change_pct is None:
        return ""
    sign = "+" if change_pct > 0 else ""
    return f"{sign}{change_pct:.2f}%"


def _build_dynamic_title(
    *,
    report_date: str,
    report_language: str,
    single_stock: bool,
    stocks: Sequence[StockReportItem],
    buy_count: int,
    hold_count: int,
    sell_count: int,
    alert_count: int,
) -> str:
    short_date = report_date[5:10] if len(report_date) >= 10 and report_date[4] == "-" else report_date
    if single_stock and stocks:
        s = stocks[0]
        risk_n = len(s.risk_alerts) if s.has_urgent_risk else 0
        if report_language == "en":
            score_bit = f" · {s.sentiment_score}" if s.sentiment_score is not None else ""
            base = f"DSA Brief ({short_date}) | {s.display_name}({s.code}) {s.signal_text}{score_bit}"
            return f"{base} · {risk_n} Alert(s)" if risk_n > 0 else base
        if report_language == "ko":
            score_bit = f" · {s.sentiment_score}점" if s.sentiment_score is not None else ""
            base = f"DSA 브리핑 ({short_date}) | {s.display_name}({s.code}) {s.signal_text}{score_bit}"
            return f"{base} · 경보{risk_n}" if risk_n > 0 else base
        score_bit = f" · {s.sentiment_score}分" if s.sentiment_score is not None else ""
        base = f"DSA 决策简报 ({short_date})｜{s.display_name}({s.code}) {s.signal_text}{score_bit}"
        return f"{base} · 预警{risk_n}" if risk_n > 0 else base

    if report_language == "en":
        base = f"DSA Daily ({short_date}) | Buy {buy_count} · Watch {hold_count} · Sell {sell_count}"
        return f"{base} · Alerts {alert_count}" if alert_count > 0 else base
    if report_language == "ko":
        base = f"DSA 데일리 ({short_date}) | 매수 {buy_count} · 관망 {hold_count} · 매도 {sell_count}"
        return f"{base} · 경보 {alert_count}" if alert_count > 0 else base
    base = f"DSA 决策日报 ({short_date})｜买{buy_count}·观{hold_count}·卖{sell_count}"
    return f"{base}·预警{alert_count}" if alert_count > 0 else base


def _resolve_header_tone(
    *,
    single_stock: bool,
    buy_count: int,
    sell_count: int,
    alert_count: int,
    stocks: Sequence[StockReportItem],
) -> str:
    if sell_count > 0 or any(
        s.has_urgent_risk and (s.action == "alert" or (s.sentiment_score is not None and s.sentiment_score < 50))
        for s in stocks
    ):
        return "red"
    if alert_count > 0:
        return "orange"
    if buy_count > 0 and sell_count == 0 and alert_count == 0:
        return "green"
    if stocks:
        if any(s.decision_bucket == "hold" for s in stocks):
            return "orange"
    return "blue"


def _parse_non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value if value > 0 else 0
    if isinstance(value, float):
        return int(value) if value == value and value > 0 else 0
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isascii() and stripped.isdecimal():
            parsed = int(stripped)
            return parsed if parsed > 0 else 0
    return 0


def _parse_confidence_pct(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed < 0.0 or parsed > 1.0:
        return None
    return round(parsed * 100)


def _build_strategy_skill_items(raw_items: Any, report_language: str) -> List[StrategySkillItem]:
    if not isinstance(raw_items, list):
        return []
    parsed_items: List[StrategySkillItem] = []
    for entry in raw_items:
        if not isinstance(entry, Mapping):
            continue
        skill_id = str(entry.get("skill_id") or entry.get("agent_name") or "").strip()
        if not skill_id:
            continue
        raw_signal = str(entry.get("signal") or entry.get("normalized_signal") or "hold").strip() or "hold"
        parsed_items.append(
            StrategySkillItem(
                skill_id=skill_id,
                display_name=localize_strategy_skill(skill_id, report_language) or skill_id,
                signal=raw_signal,
                signal_display=localize_strategy_signal(raw_signal, report_language) or raw_signal,
                confidence_pct=_parse_confidence_pct(entry.get("confidence")),
            )
        )
    return parsed_items


def _build_strategy_synthesis_view(raw_synthesis: Any, report_language: str) -> Optional[StrategySynthesisView]:
    synthesis = normalize_strategy_synthesis_payload(raw_synthesis)
    if not synthesis:
        return None

    final_signal = str(synthesis.get("final_signal") or "").strip()
    supporting_skills = _build_strategy_skill_items(synthesis.get("supporting_skills"), report_language)
    opposing_skills = _build_strategy_skill_items(synthesis.get("opposing_skills"), report_language)
    if not final_signal and not supporting_skills and not opposing_skills:
        return None

    normalized_signal = final_signal or "hold"
    consensus_level = str(synthesis.get("consensus_level") or "N/A").strip() or "N/A"
    conflict_severity = str(synthesis.get("conflict_severity") or "none").strip() or "none"
    conflict_count = _parse_non_negative_int(synthesis.get("conflict_count"))
    confidence_pct = _parse_confidence_pct(synthesis.get("confidence"))

    summary_params = synthesis.get("summary_params")
    explicit_opinions = (
        _parse_non_negative_int(summary_params.get("opinion_count"))
        if isinstance(summary_params, Mapping)
        else 0
    )
    opinion_count = explicit_opinions or (len(supporting_skills) + len(opposing_skills))
    invalid_opinion_count = strategy_invalid_opinion_count(synthesis)

    deliberation = synthesis.get("deliberation")
    delib_summary = deliberation.get("summary") if isinstance(deliberation, Mapping) else None
    if isinstance(delib_summary, Mapping):
        minority_preserved = delib_summary.get("minority_view_preserved") is True
    else:
        minority_preserved = synthesis.get("minority_view_preserved") is True

    return StrategySynthesisView(
        final_signal=normalized_signal,
        final_signal_display=localize_strategy_signal(normalized_signal, report_language) or normalized_signal,
        consensus_level=consensus_level,
        consensus_display=localize_consensus_level(consensus_level, report_language) or consensus_level,
        conflict_severity=conflict_severity,
        conflict_display=localize_conflict_severity(conflict_severity, report_language) or conflict_severity,
        conflict_count=conflict_count,
        confidence_pct=confidence_pct,
        opinion_count=opinion_count,
        invalid_opinion_count=invalid_opinion_count,
        summary=localize_strategy_synthesis_summary(synthesis, report_language),
        supporting_skills=supporting_skills,
        opposing_skills=opposing_skills,
        minority_view_preserved=minority_preserved,
    )


def _resolve_signal_bucket_and_text(result: Any, report_language: str) -> Tuple[str, str, str, str]:
    display_fields = display_action_fields_for_result(result, report_language=report_language)
    action = str(display_fields.get("action") or "").strip() or "watch"
    bucket = display_decision_type_for_result(result, report_language=report_language)
    advice = display_operation_advice_for_result(result, report_language=report_language)
    signal_action = {
        "buy": "buy",
        "add": "buy",
        "hold": "hold",
        "reduce": "reduce",
        "sell": "sell",
        "watch": "watch",
        "avoid": "hold",
        "alert": "alert",
    }.get(action)
    score = _safe_int(getattr(result, "sentiment_score", None), None)
    _, emoji, _tag = get_signal_level(signal_action or advice, score if score is not None else 50, report_language)
    return action, bucket, advice or "", emoji


def _sort_alert_first(item: StockReportItem) -> Tuple[int, int, str]:
    if item.decision_bucket == "sell" or item.action in {"sell", "reduce"}:
        return (0, item.sentiment_score if item.sentiment_score is not None else 999, item.code)
    if item.has_urgent_risk or item.action == "alert":
        return (1, item.sentiment_score if item.sentiment_score is not None else 999, item.code)
    if item.decision_bucket == "buy" or item.action in {"buy", "add"}:
        return (2, -(item.sentiment_score if item.sentiment_score is not None else -1), item.code)
    return (3, -(item.sentiment_score if item.sentiment_score is not None else -1), item.code)


def _is_failed_or_warn_checklist(item: str) -> bool:
    stripped = item.strip()
    if stripped.startswith(("✅", "✔", "☑", "[pass]", "[PASS]")):
        return False
    if stripped.startswith(("❌", "✗", "✘", "⚠️", "⚠", "[x]", "[X]", "[!]")) or re.match(r"^\[\s*fail\s*\]", stripped, re.I):
        return True
    lower = stripped.lower()
    return "不通过" in stripped or "未满足" in stripped or "fail" in lower


def _extract_stock_item(
    result: Any,
    *,
    report_language: str,
    show_llm_model: bool,
    empty_news_fn: Any = None,
) -> StockReportItem:
    code = str(getattr(result, "code", "") or "").strip() or "UNKNOWN"
    raw_name = getattr(result, "name", None) or ""
    display_name = get_localized_stock_name(raw_name, code, report_language)
    score = _safe_int(getattr(result, "sentiment_score", None), None)
    action, bucket, signal_text, signal_emoji = _resolve_signal_bucket_and_text(result, report_language)

    trend_raw = getattr(result, "trend_prediction", None) or ""
    trend_display = localize_trend_prediction(trend_raw, report_language) if trend_raw else ""

    dashboard = getattr(result, "dashboard", None)
    if not isinstance(dashboard, Mapping):
        dashboard = {}
    core = dashboard.get("core_conclusion") if isinstance(dashboard.get("core_conclusion"), Mapping) else {}
    battle = dashboard.get("battle_plan") if isinstance(dashboard.get("battle_plan"), Mapping) else {}
    intel = dashboard.get("intelligence") if isinstance(dashboard.get("intelligence"), Mapping) else {}
    snapshot = getattr(result, "market_snapshot", None)
    if not isinstance(snapshot, Mapping):
        snapshot = {}

    current_price = _safe_float(getattr(result, "current_price", None))
    if current_price is None:
        current_price = _safe_float(snapshot.get("price")) or _safe_float(snapshot.get("close"))
    change_pct = _safe_float(getattr(result, "change_pct", None))
    if change_pct is None:
        change_pct = _safe_float(snapshot.get("pct_chg"))

    analysis_summary = str(getattr(result, "analysis_summary", None) or "").strip()
    one_sentence = str(core.get("one_sentence") or analysis_summary or "").strip()
    labels = get_report_labels(report_language)
    time_sensitivity = str(core.get("time_sensitivity") or "").strip()

    sniper_raw = battle.get("sniper_points") if isinstance(battle.get("sniper_points"), Mapping) else {}
    sniper = _compute_sniper_levels(
        sniper_raw,
        current_price=current_price,
        suppress_bullish_rr=(bucket == "sell" or action in {"sell", "reduce"}),
    )

    pos_raw = core.get("position_advice") if isinstance(core.get("position_advice"), Mapping) else {}
    pos_strat = battle.get("position_strategy") if isinstance(battle.get("position_strategy"), Mapping) else {}
    position_advice = PositionAdvice(
        no_position=str(pos_raw.get("no_position") or "").strip(),
        has_position=str(pos_raw.get("has_position") or "").strip(),
        suggested_position=str(pos_strat.get("suggested_position") or "").strip(),
        entry_plan=str(pos_strat.get("entry_plan") or "").strip(),
        risk_control=str(pos_strat.get("risk_control") or "").strip(),
    )

    risk_alerts = _normalize_string_list(intel.get("risk_alerts"))
    if not risk_alerts:
        risk_alerts = _normalize_string_list(getattr(result, "risk_warning", None))
    has_risk_assessment = bool(intel) or bool(risk_alerts) or getattr(result, "risk_warning", None) is not None
    catalysts = _normalize_string_list(intel.get("positive_catalysts"))
    sentiment_summary = str(intel.get("sentiment_summary") or getattr(result, "market_sentiment", "") or "").strip()
    earnings_outlook = str(intel.get("earnings_outlook") or "").strip()
    latest_news = str(intel.get("latest_news") or "").strip()

    checklist = _normalize_string_list(battle.get("action_checklist"))
    failed_checks = [item for item in checklist if _is_failed_or_warn_checklist(item)]

    signal_attr_raw = dashboard.get("signal_attribution") if isinstance(dashboard.get("signal_attribution"), Mapping) else {}
    signal_attribution: Optional[SignalAttributionItem] = None
    if signal_attribution_has_content(dict(signal_attr_raw)):
        weight_items = [
            (key, float(val))
            for key, val in signal_attribution_weight_items(dict(signal_attr_raw))
        ]
        signal_attribution = SignalAttributionItem(
            weights=weight_items,
            strongest_bullish=str(signal_attr_raw.get("strongest_bullish_signal") or "").strip(),
            strongest_bearish=str(signal_attr_raw.get("strongest_bearish_signal") or "").strip(),
        )

    synthesis = normalize_strategy_synthesis_payload(dashboard.get("strategy_synthesis"))
    strategy_synthesis_view = _build_strategy_synthesis_view(synthesis, report_language)
    synthesis_summary = (
        localize_strategy_synthesis_summary(synthesis, report_language)
        if synthesis
        else ""
    )
    if synthesis and synthesis_summary:
        final_sig = localize_strategy_signal(synthesis.get("final_signal", ""), report_language)
        consensus = localize_consensus_level(synthesis.get("consensus_level", ""), report_language)
        conflict = localize_conflict_severity(synthesis.get("conflict_severity", "none"), report_language)
        synthesis_summary = (
            f"{final_sig} | {labels['strategy_consensus_level_label']} {consensus} | "
            f"{labels['strategy_conflict_label']} {conflict} — {synthesis_summary}"
        )

    news_disclosure = ""
    if callable(empty_news_fn):
        try:
            news_disclosure = str(empty_news_fn(result, report_language) or "").strip()
        except Exception:
            news_disclosure = ""
    if not news_disclosure:
        try:
            news_disclosure = str(empty_news_disclosure(result, report_language) or "").strip()
        except Exception:
            news_disclosure = ""

    data_sources = str(getattr(result, "data_sources", "") or "").strip()
    model_used = ""
    if show_llm_model:
        model_used = normalize_model_used(getattr(result, "model_used", None)) or ""

    has_urgent_risk = (
        bucket == "sell"
        or action in {"sell", "reduce", "alert"}
        or (bool(risk_alerts) and score is not None and score < 60)
    )

    return StockReportItem(
        code=code,
        name=str(raw_name or code),
        display_name=display_name,
        action=action,
        decision_bucket=bucket,
        signal_text=signal_text,
        signal_emoji=signal_emoji,
        sentiment_score=score,
        trend_prediction=trend_display,
        current_price=current_price,
        change_pct=change_pct,
        price_display=_format_price_display(current_price),
        change_display=_format_change_display(change_pct),
        one_sentence=one_sentence,
        time_sensitivity=time_sensitivity,
        sniper=sniper,
        position_advice=position_advice,
        risk_alerts=risk_alerts,
        positive_catalysts=catalysts,
        sentiment_summary=sentiment_summary,
        earnings_outlook=earnings_outlook,
        latest_news=latest_news,
        checklist=checklist,
        failed_checks=failed_checks,
        signal_attribution=signal_attribution,
        strategy_synthesis_summary=synthesis_summary,
        strategy_synthesis=strategy_synthesis_view,
        empty_news_disclosure=news_disclosure,
        data_sources=data_sources,
        model_used=model_used,
        has_urgent_risk=has_urgent_risk,
        has_risk_assessment=has_risk_assessment,
        market_snapshot=dict(snapshot),
        analysis_summary=analysis_summary,
    )


def _collect_top_risk_alerts(
    stocks: Sequence[StockReportItem],
    *,
    single_stock: bool = False,
    limit: int = 6,
) -> List[RiskAlertEntry]:
    entries: List[RiskAlertEntry] = []
    seen: set[Tuple[str, str]] = set()
    per_stock_cap = 4 if single_stock else 2
    for stock in stocks:
        if not stock.has_urgent_risk:
            continue
        severity = (
            "high"
            if (
                stock.decision_bucket == "sell"
                or stock.action in {"sell", "reduce", "alert"}
                or (stock.sentiment_score is not None and stock.sentiment_score < 50)
            )
            else "medium"
        )
        added_for_stock = 0
        for msg in stock.risk_alerts:
            cleaned = msg.strip()
            if not cleaned:
                continue
            key = (stock.code, cleaned)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                RiskAlertEntry(
                    stock_code=stock.code,
                    stock_name=stock.display_name,
                    message=cleaned,
                    severity=severity,
                )
            )
            added_for_stock += 1
            if added_for_stock >= per_stock_cap or len(entries) >= limit:
                break
        if len(entries) >= limit:
            break
    return entries[:limit]


def build_notification_report_payload(
    results: Iterable[Any],
    *,
    report_date: Optional[str] = None,
    report_language: Optional[str] = None,
    single_stock: bool = False,
    summary_only: bool = False,
    show_llm_model: bool = True,
    web_url: str = "",
    market_status_line: str = "",
    empty_news_fn: Any = None,
    raw_markdown_fallback: str = "",
) -> NotificationReportPayload:
    """Build structured ViewModel payload from AnalysisResult list."""
    result_list = list(results or [])
    detected_lang = report_language
    if not detected_lang:
        for r in result_list:
            lang = getattr(r, "report_language", None)
            if lang:
                detected_lang = lang
                break
    lang = normalize_report_language(detected_lang)
    labels = get_report_labels(lang)

    resolved_date = report_date or datetime.now().strftime("%Y-%m-%d")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    if not market_status_line:
        for r in result_list:
            line = format_public_market_status_line(
                getattr(r, "market_phase_summary", None),
                report_language=lang,
            )
            if line:
                market_status_line = line
                break

    items = [
        _extract_stock_item(
            r,
            report_language=lang,
            show_llm_model=show_llm_model,
            empty_news_fn=empty_news_fn,
        )
        for r in result_list
    ]
    items.sort(key=_sort_alert_first)

    buy_count = sum(1 for item in items if item.decision_bucket == "buy")
    sell_count = sum(1 for item in items if item.decision_bucket == "sell")
    hold_count = len(items) - buy_count - sell_count
    urgent_stock_count = sum(1 for item in items if item.has_urgent_risk)
    risk_checked_count = sum(1 for item in items if item.has_risk_assessment)
    scored = [item.sentiment_score for item in items if item.sentiment_score is not None]
    avg_score = round(sum(scored) / len(scored), 1) if scored else 0.0

    top_alerts = _collect_top_risk_alerts(items, single_stock=single_stock)
    models_used = list(dict.fromkeys(item.model_used for item in items if item.model_used))

    dynamic_title = _build_dynamic_title(
        report_date=resolved_date,
        report_language=lang,
        single_stock=single_stock,
        stocks=items,
        buy_count=buy_count,
        hold_count=hold_count,
        sell_count=sell_count,
        alert_count=urgent_stock_count,
    )
    header_tone = _resolve_header_tone(
        single_stock=single_stock,
        buy_count=buy_count,
        sell_count=sell_count,
        alert_count=urgent_stock_count,
        stocks=items,
    )

    resolved_web_url = (web_url or "").strip()

    return NotificationReportPayload(
        report_date=resolved_date,
        generated_at=generated_at,
        report_language=lang,
        single_stock=single_stock,
        summary_only=summary_only,
        dynamic_title=dynamic_title,
        header_tone=header_tone,
        total_count=len(items),
        buy_count=buy_count,
        hold_count=hold_count,
        sell_count=sell_count,
        alert_count=urgent_stock_count,
        avg_score=avg_score,
        market_status_line=market_status_line,
        risk_checked_count=risk_checked_count,
        top_risk_alerts=top_alerts,
        stocks=items,
        models_used=models_used,
        web_url=resolved_web_url,
        disclaimer=labels["not_investment_advice"],
        raw_markdown_fallback=raw_markdown_fallback,
    )


class _HistoryResultAdapter:
    """Lightweight adapter exposing HistoryService detail dict as AnalysisResult-like attributes."""

    def __init__(self, detail: Mapping[str, Any]):
        raw_result = detail.get("raw_result")
        raw = raw_result if isinstance(raw_result, Mapping) else {}
        context_snapshot = detail.get("context_snapshot")
        ctx = context_snapshot if isinstance(context_snapshot, Mapping) else {}

        self.code = detail.get("stock_code") or detail.get("storage_stock_code") or ""
        self.name = detail.get("stock_name") or raw.get("name") or self.code
        self.sentiment_score = _safe_int(detail.get("sentiment_score"), _safe_int(raw.get("sentiment_score"), None))
        self.trend_prediction = detail.get("trend_prediction") or raw.get("trend_prediction") or ""
        self.operation_advice = detail.get("operation_advice") or raw.get("operation_advice") or ""
        self.decision_type = raw.get("decision_type") or ""
        self.confidence_level = raw.get("confidence_level") or ""
        self.report_language = detail.get("report_language") or raw.get("report_language") or "zh"
        self.action = detail.get("action") or raw.get("action")
        self.action_label = detail.get("action_label") or raw.get("action_label")
        self.report_type = detail.get("report_type")

        dashboard = raw.get("dashboard")
        dashboard_copy: Dict[str, Any] = dict(dashboard) if isinstance(dashboard, Mapping) else {}
        battle_plan = dict(dashboard_copy.get("battle_plan") or {}) if isinstance(dashboard_copy.get("battle_plan"), Mapping) else {}
        sniper = dict(battle_plan.get("sniper_points") or {}) if isinstance(battle_plan.get("sniper_points"), Mapping) else {}
        for field_name in ("ideal_buy", "secondary_buy", "stop_loss", "take_profit"):
            if detail.get(field_name) is not None and not sniper.get(field_name):
                sniper[field_name] = detail.get(field_name)
        if sniper:
            battle_plan["sniper_points"] = sniper
            dashboard_copy["battle_plan"] = battle_plan
        self.dashboard = dashboard_copy

        self.analysis_summary = detail.get("analysis_summary") or raw.get("analysis_summary") or ""
        self.risk_warning = raw.get("risk_warning")
        self.market_sentiment = raw.get("market_sentiment") or ""
        self.data_sources = raw.get("data_sources") or ""
        self.model_used = detail.get("model_used") or raw.get("model_used")
        self.market_snapshot = raw.get("market_snapshot") if isinstance(raw.get("market_snapshot"), Mapping) else {}
        self.market_phase_summary = detail.get("market_phase_summary")
        self.news_content = detail.get("news_content")
        self.search_performed = bool(raw.get("search_performed", False))
        self.news_result_count = raw.get("news_result_count")
        self.news_result_count_known = bool(raw.get("news_result_count_known", False))
        self.news_evidence_present = bool(raw.get("news_evidence_present", False))
        self._empty_news_disclosure_text = str(detail.get("empty_news_disclosure") or "").strip()

        from src.utils.data_processing import extract_realtime_detail_fields

        realtime = extract_realtime_detail_fields(ctx)
        self.current_price = (
            _safe_float(realtime.get("current_price"))
            or _safe_float(raw.get("current_price"))
            or _safe_float(detail.get("current_price"))
        )
        self.change_pct = _safe_float(realtime.get("change_pct"))
        if self.change_pct is None:
            self.change_pct = _safe_float(raw.get("change_pct")) or _safe_float(detail.get("change_pct"))

        snapshot_copy: Dict[str, Any] = dict(self.market_snapshot) if isinstance(self.market_snapshot, Mapping) else {}
        rt_ctx: Mapping[str, Any] = {}
        if isinstance(ctx.get("realtime_quote"), Mapping):
            rt_ctx = ctx.get("realtime_quote")  # type: ignore[assignment]
        elif isinstance(ctx.get("enhanced_context"), Mapping) and isinstance(ctx["enhanced_context"].get("realtime"), Mapping):
            rt_ctx = ctx["enhanced_context"]["realtime"]
        for key in ("volume_ratio", "turnover_rate", "pe_ratio", "pb_ratio"):
            if snapshot_copy.get(key) is None:
                for cand in (rt_ctx.get(key), detail.get(key), raw.get(key)):
                    val = _safe_float(cand)
                    if val is not None:
                        snapshot_copy[key] = val
                        break
        self.market_snapshot = snapshot_copy


def build_history_report_payload(
    detail_record: Mapping[str, Any],
    *,
    markdown_content: str = "",
    web_url: str = "",
) -> NotificationReportPayload:
    """Build structured NotificationReportPayload from HistoryService detail record."""
    created_at = str(detail_record.get("created_at") or "").strip()
    report_date = created_at[:10] if len(created_at) >= 10 else datetime.now().strftime("%Y-%m-%d")
    adapter = _HistoryResultAdapter(detail_record)
    payload = build_notification_report_payload(
        [adapter],
        report_date=report_date,
        report_language=adapter.report_language,
        single_stock=True,
        summary_only=False,
        show_llm_model=True,
        web_url=web_url,
        empty_news_fn=lambda _r, _l: adapter._empty_news_disclosure_text,
        raw_markdown_fallback=markdown_content,
    )
    if created_at:
        payload.generated_at = created_at.replace("T", " ")[:16]
    return payload
