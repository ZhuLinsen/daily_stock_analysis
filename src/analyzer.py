# -*- coding: utf-8 -*-
"""
===================================
A股自選股智慧分析系統 - AI分析層
===================================

職責：
1. 封裝 LLM 呼叫邏輯（透過 LiteLLM 統一呼叫 Gemini/Anthropic/OpenAI 等）
2. 結合技術面和訊息面生成分析報告
3. 解析 LLM 響應為結構化 AnalysisResult
"""

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple, Callable

import litellm
from json_repair import repair_json
from litellm import Router

from src.agent.llm_adapter import (
    get_thinking_extra_body,
    resolve_fallback_litellm_wire_models,
    register_fallback_model_pricing,
)
from src.agent.skills.defaults import CORE_TRADING_SKILL_POLICY_ZH
from src.config import (
    Config,
    extra_litellm_params,
    get_api_keys_for_model,
    get_config,
    get_configured_llm_models,
    normalize_litellm_temperature,
    resolve_litellm_wire_model,
    resolve_news_window_days,
)
from src.llm.generation_params import apply_litellm_generation_params
from src.llm.errors import call_litellm_with_param_recovery
from src.storage import persist_llm_usage
from src.data.stock_mapping import STOCK_NAME_MAP
from src.report_language import (
    get_signal_level,
    get_no_data_text,
    get_placeholder_text,
    get_unknown_text,
    get_chip_unavailable_text,
    infer_decision_type_from_advice,
    is_chip_placeholder_value,
    localize_chip_health,
    localize_confidence_level,
    normalize_report_language,
)
from src.schemas.report_schema import AnalysisReportSchema
from src.market_context import get_market_role, get_market_guidelines
from src.market_phase_prompt import format_market_phase_prompt_section

logger = logging.getLogger(__name__)


def _normalize_risk_warning_values(value: Any) -> List[str]:
    """Normalize arbitrary risk_warning values into a flat list of text alerts."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        normalized: List[str] = []
        for item in value:
            normalized.extend(_normalize_risk_warning_values(item))
        return normalized
    if isinstance(value, dict):
        if not value:
            return []
        try:
            dumped = json.dumps(value, ensure_ascii=False)
            text = dumped.strip()
        except (TypeError, ValueError):
            text = str(value).strip()
        return [text] if text else []
    text = str(value).strip()
    return [text] if text else []


def _today_has_realtime_overlay(today: Any) -> bool:
    if not isinstance(today, dict):
        return False
    data_source = today.get("data_source") or today.get("dataSource")
    if isinstance(data_source, str) and data_source.startswith("realtime:"):
        return True
    if today.get("is_partial_bar") is True or today.get("isPartialBar") is True:
        return True
    if today.get("is_estimated") is True or today.get("isEstimated") is True:
        return True
    return bool(today.get("estimated_fields") or today.get("estimatedFields"))


def _today_looks_complete_daily_bar(
    context: Dict[str, Any],
    phase_context: Dict[str, Any],
) -> bool:
    today = context.get("today")
    if (
        not isinstance(today, dict)
        or today.get("close") in (None, "")
        or _today_has_realtime_overlay(today)
    ):
        return False

    effective_date = phase_context.get("effective_daily_bar_date")
    today_date = today.get("date") or today.get("trade_date") or context.get("date")
    if effective_date and today_date and str(today_date) != str(effective_date):
        return False
    return True


def _phase_aware_quote_labels(context: Dict[str, Any]) -> Tuple[str, str]:
    """Choose Chinese quote-table labels that do not conflict with phase context."""
    phase_context = context.get("market_phase_context")
    if not isinstance(phase_context, dict):
        return "今日行情", "收盤價"

    phase = str(phase_context.get("phase") or "").strip()
    if phase in {"premarket", "non_trading"}:
        today = context.get("today")
        if _today_looks_complete_daily_bar(context, phase_context):
            return "上一完整交易日行情", "上一完整交易日收盤價"
        if _today_has_realtime_overlay(today):
            return "最新行情", "實時估算價"
        if isinstance(today, dict) and today.get("close") not in (None, ""):
            return "最新行情", "最新價"
        return "今日行情", "收盤價"

    if (
        phase in {"intraday", "lunch_break", "closing_auction"}
        and phase_context.get("is_partial_bar") is True
    ):
        return "最新行情", "盤中估算價"

    return "今日行情", "收盤價"


def _should_hide_regular_session_ohlc(context: Dict[str, Any]) -> bool:
    phase_context = context.get("market_phase_context")
    if not isinstance(phase_context, dict):
        return False

    phase = str(phase_context.get("phase") or "").strip()
    return phase in {"premarket", "non_trading"} and not _today_looks_complete_daily_bar(
        context,
        phase_context,
    )


class _LiteLLMStreamError(RuntimeError):
    """Internal error wrapper that records whether any text was streamed."""

    def __init__(self, message: str, *, partial_received: bool = False):
        super().__init__(message)
        self.partial_received = partial_received


class _AllModelsFailedError(Exception):
    """Raised when every model in the fallback chain fails.

    This includes both LLM call errors and JSON parse errors (when a
    ``response_validator`` is provided to :meth:`GeminiAnalyzer._call_litellm`).

    The ``last_response_text`` attribute holds the raw text from the last model
    that *did* return a response (but whose JSON could not be validated), so
    callers can still attempt a best-effort text fallback.

    ``last_model`` and ``last_usage`` record the model name and token usage
    from the last attempt so callers can persist usage even on fallback.
    """

    def __init__(
        self,
        message: str,
        *,
        last_response_text: Optional[str] = None,
        last_model: Optional[str] = None,
        last_usage: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.last_response_text = last_response_text
        self.last_model = last_model
        self.last_usage = last_usage or {}


def check_content_integrity(
    result: "AnalysisResult",
    *,
    require_phase_decision: bool = False,
) -> Tuple[bool, List[str]]:
    """
    Check mandatory fields for report content integrity.
    Returns (pass, missing_fields). Module-level for use by pipeline (agent weak mode).
    """
    missing: List[str] = []

    def _is_blank_text(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        return True

    def _is_invalid_risk_alerts(value: Any) -> bool:
        return not isinstance(value, list)

    def _is_invalid_stop_loss(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, (list, tuple, dict)):
            return True
        if isinstance(value, str):
            return not value.strip()
        return False

    if result.sentiment_score is None:
        missing.append("sentiment_score")
    advice = result.operation_advice
    if not advice or not isinstance(advice, str) or _is_blank_text(advice):
        missing.append("operation_advice")
    summary = result.analysis_summary
    if not summary or not isinstance(summary, str) or _is_blank_text(summary):
        missing.append("analysis_summary")
    dash = result.dashboard if isinstance(result.dashboard, dict) else {}
    core = dash.get("core_conclusion")
    core = core if isinstance(core, dict) else {}
    if _is_blank_text(core.get("one_sentence")):
        missing.append("dashboard.core_conclusion.one_sentence")
    intel = dash.get("intelligence")
    intel = intel if isinstance(intel, dict) else None
    if intel is None or _is_invalid_risk_alerts(intel.get("risk_alerts")):
        missing.append("dashboard.intelligence.risk_alerts")
    if result.decision_type in ("buy", "hold"):
        battle = dash.get("battle_plan")
        battle = battle if isinstance(battle, dict) else {}
        sp = battle.get("sniper_points")
        sp = sp if isinstance(sp, dict) else {}
        stop_loss = sp.get("stop_loss")
        if _is_invalid_stop_loss(stop_loss):
            missing.append("dashboard.battle_plan.sniper_points.stop_loss")
    if require_phase_decision:
        phase_decision = dash.get("phase_decision")
        phase_decision = phase_decision if isinstance(phase_decision, dict) else {}
        if not isinstance(phase_decision.get("phase_context"), dict):
            missing.append("dashboard.phase_decision.phase_context")
        if _is_blank_text(phase_decision.get("action_window")):
            missing.append("dashboard.phase_decision.action_window")
        if _is_blank_text(phase_decision.get("immediate_action")):
            missing.append("dashboard.phase_decision.immediate_action")
        if not isinstance(phase_decision.get("watch_conditions"), list):
            missing.append("dashboard.phase_decision.watch_conditions")
        if _is_blank_text(phase_decision.get("next_check_time")):
            missing.append("dashboard.phase_decision.next_check_time")
        if _is_blank_text(phase_decision.get("confidence_reason")):
            missing.append("dashboard.phase_decision.confidence_reason")
        if not isinstance(phase_decision.get("data_limitations"), list):
            missing.append("dashboard.phase_decision.data_limitations")
    return len(missing) == 0, missing


def apply_placeholder_fill(result: "AnalysisResult", missing_fields: List[str]) -> None:
    """Fill missing mandatory fields with placeholders (in-place). Module-level for pipeline."""

    def _is_blank_text(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        return True

    def _is_invalid_risk_alerts(value: Any) -> bool:
        return not isinstance(value, list)

    def _is_invalid_stop_loss(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, (list, tuple, dict)):
            return True
        if isinstance(value, str):
            return not value.strip()
        return False

    report_language = normalize_report_language(getattr(result, "report_language", "zh"))
    placeholder = get_placeholder_text(report_language)
    phase_decision_placeholders = {
        "dashboard.phase_decision.action_window": (
            "Model did not provide a phase action window"
            if report_language == "en"
            else "模型未提供階段化行動視窗"
        ),
        "dashboard.phase_decision.immediate_action": (
            "Model did not provide a phase-aware immediate action"
            if report_language == "en"
            else "模型未提供階段化即時動作"
        ),
        "dashboard.phase_decision.next_check_time": (
            "Model did not provide a next check point"
            if report_language == "en"
            else "模型未提供下一次檢查點"
        ),
        "dashboard.phase_decision.confidence_reason": (
            "Model did not provide a phase confidence rationale"
            if report_language == "en"
            else "模型未提供階段化置信度理由"
        ),
    }
    for field in missing_fields:
        if field == "sentiment_score":
            result.sentiment_score = 50
        elif field == "operation_advice":
            if _is_blank_text(result.operation_advice):
                result.operation_advice = placeholder
        elif field == "analysis_summary":
            if _is_blank_text(result.analysis_summary):
                result.analysis_summary = placeholder
        elif field == "dashboard.core_conclusion.one_sentence":
            if not result.dashboard:
                result.dashboard = {}
            core = result.dashboard.get("core_conclusion")
            if not isinstance(core, dict):
                core = {}
                result.dashboard["core_conclusion"] = core
            fallback_sentence = (
                result.analysis_summary
                or result.operation_advice
                or placeholder
            )
            if _is_blank_text(core.get("one_sentence")):
                result.dashboard["core_conclusion"]["one_sentence"] = fallback_sentence
        elif field == "dashboard.intelligence.risk_alerts":
            if not result.dashboard:
                result.dashboard = {}
            intelligence = result.dashboard.get("intelligence")
            if not isinstance(intelligence, dict):
                intelligence = {}
                result.dashboard["intelligence"] = intelligence
            if _is_invalid_risk_alerts(intelligence.get("risk_alerts")):
                risk_warning_values = _normalize_risk_warning_values(result.risk_warning)
                intelligence["risk_alerts"] = risk_warning_values
        elif field == "dashboard.battle_plan.sniper_points.stop_loss":
            if not result.dashboard:
                result.dashboard = {}
            battle_plan = result.dashboard.get("battle_plan")
            if not isinstance(battle_plan, dict):
                battle_plan = {}
                result.dashboard["battle_plan"] = battle_plan
            sniper_points = battle_plan.get("sniper_points")
            if not isinstance(sniper_points, dict):
                sniper_points = {}
                battle_plan["sniper_points"] = sniper_points
            if _is_invalid_stop_loss(sniper_points.get("stop_loss")):
                sniper_points["stop_loss"] = placeholder
        elif field.startswith("dashboard.phase_decision."):
            if not result.dashboard:
                result.dashboard = {}
            phase_decision = result.dashboard.get("phase_decision")
            if not isinstance(phase_decision, dict):
                phase_decision = {}
                result.dashboard["phase_decision"] = phase_decision
            if field == "dashboard.phase_decision.phase_context":
                if not isinstance(phase_decision.get("phase_context"), dict):
                    phase_decision["phase_context"] = {}
            elif field == "dashboard.phase_decision.watch_conditions":
                if not isinstance(phase_decision.get("watch_conditions"), list):
                    phase_decision["watch_conditions"] = []
            elif field == "dashboard.phase_decision.data_limitations":
                if not isinstance(phase_decision.get("data_limitations"), list):
                    phase_decision["data_limitations"] = []
            elif field in phase_decision_placeholders:
                if _is_blank_text(phase_decision.get(field.rsplit(".", 1)[-1])):
                    phase_decision[field.rsplit(".", 1)[-1]] = phase_decision_placeholders[field]


# ---------- chip_structure fallback (Issue #589) ----------

_CHIP_KEYS: tuple = ("profit_ratio", "avg_cost", "concentration", "chip_health")


def _is_value_placeholder(v: Any) -> bool:
    """True if value is empty or placeholder (N/A, 資料缺失, etc.)."""
    return is_chip_placeholder_value(v)


_RISK_WARNING_PLACEHOLDER_TEXTS = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "tbd",
    "暫無",
    "待補充",
    "資料缺失",
    "未知",
    "無",
}

_STRUCTURAL_RISK_PHRASE_HINTS = (
    "重大利空",
    "重大風險",
    "關鍵風險",
    "減持",
    "高位減持",
    "退市",
    "退市風險",
    "停牌",
    "重大問詢",
    "處罰",
    "限售",
    "違規",
    "違規風險",
    "訴訟",
    "問詢",
    "監管",
    "財務",
    "審計",
    "爆雷",
    "暴雷",
    "違約",
    "違約風險",
    "流動性危機",
    "債務",
    "清算",
    "破產",
    "重大變臉",
    "major risk",
    "material adverse",
    "suspension",
    "delisting",
    "regulatory",
    "downgrade",
    "liquidity",
    "default",
)

_CAPITAL_FLOW_UNAVAILABLE_STATUS = {
    "not_supported",
    "not supported",
    "unsupported",
    "unavailable",
    "not_available",
    "not available",
    "none",
    "na",
    "n/a",
    "null",
    "missing",
}


def _is_meaningful_text(value: Any) -> bool:
    text = str(value).strip() if value is not None else ""
    if not text:
        return False
    lowered = text.strip().lower()
    return lowered not in _RISK_WARNING_PLACEHOLDER_TEXTS


def _safe_float(v: Any, default: float = 0.0) -> float:
    """Safely convert to float; return default on failure. Private helper for chip fill."""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        try:
            return default if math.isnan(float(v)) else float(v)
        except (ValueError, TypeError):
            return default
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def _coerce_chip_metric(v: Any) -> Optional[float]:
    """Convert chip metrics while preserving the distinction between missing and zero."""
    if v is None:
        return None
    try:
        numeric = float(v)
    except (TypeError, ValueError):
        try:
            numeric = float(str(v).strip())
        except (TypeError, ValueError):
            return None
    return None if math.isnan(numeric) else numeric


_BULLISH_TREND_HINTS: Tuple[str, ...] = (
    "多頭排列",
    "持續上漲",
    "趨勢向上",
    "上升趨勢",
    "向上發散",
    "bullish",
    "uptrend",
)
_WEAK_BULLISH_TREND_HINTS: Tuple[str, ...] = ("弱勢多頭",)
_BEARISH_TREND_HINTS: Tuple[str, ...] = (
    "空頭排列",
    "持續下跌",
    "趨勢向下",
    "下降趨勢",
    "向下發散",
    "bearish",
    "downtrend",
)
_WEAK_BEARISH_TREND_HINTS: Tuple[str, ...] = ("弱勢空頭",)
_NEGATION_TOKENS: Tuple[str, ...] = (
    "不是",
    "並非",
    "並未",
    "沒有",
    "尚不",
    "尚未",
    "未",
    "無",
    "不屬",
    "非",
    "not ",
    "no ",
)
_NEGATION_BREAK_CHARS: Tuple[str, ...] = (",", ".", ";", ":", "!", "?", "，", "。", "；", "：", "！", "？", "\n")
_NEGATION_LOOKBACK_CHARS = 16
_NEGATION_MAX_GAP_CHARS = 8
_NEGATION_SCOPE_BREAK_TOKENS: Tuple[str, ...] = (
    "而是",
    "但是",
    "但",
    "反而",
    "反倒",
    "轉為",
    "轉成",
    "改為",
    "改成",
    " but ",
    " instead ",
    " rather ",
)
_SINGLE_CHAR_NEGATION_GAP_PREFIXES: Tuple[str, ...] = (
    "形成",
    "出現",
    "進入",
    "轉為",
    "轉成",
    "構成",
    "呈現",
    "顯示",
    "屬於",
    "是",
    "有",
    "能",
    "見",
    "站",
    "守",
    "破",
)


def _normalize_prompt_reason_items(items: Any) -> List[str]:
    """Normalize prompt reason/risk items into a clean string list."""
    if not isinstance(items, list):
        return []
    normalized: List[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def _contains_trend_hint(text: str, hints: Tuple[str, ...]) -> bool:
    """Return True when text contains a non-negated strong trend hint."""
    lowered = text.strip().lower()

    def _has_negation_scope_break(gap: str) -> bool:
        normalized_gap = gap.lower()
        for token in _NEGATION_SCOPE_BREAK_TOKENS:
            token_index = normalized_gap.find(token)
            if token_index > 0:
                return True
        return False

    def _is_valid_negation_gap(token: str, gap: str) -> bool:
        if not gap:
            return True
        if token not in {"未", "無", "非"}:
            return True
        return any(gap.startswith(prefix) for prefix in _SINGLE_CHAR_NEGATION_GAP_PREFIXES)

    def _is_negated_match(index: int) -> bool:
        prefix = lowered[max(0, index - _NEGATION_LOOKBACK_CHARS):index]
        for token in _NEGATION_TOKENS:
            token_index = prefix.rfind(token)
            if token_index < 0:
                continue
            gap = prefix[token_index + len(token):]
            if any(char in gap for char in _NEGATION_BREAK_CHARS):
                continue
            stripped_gap = gap.strip()
            if len(stripped_gap) > _NEGATION_MAX_GAP_CHARS:
                continue
            if _has_negation_scope_break(stripped_gap):
                continue
            if not _is_valid_negation_gap(token, stripped_gap):
                continue
            return True
        return False

    for hint in hints:
        keyword = hint.lower()
        start = 0
        while True:
            index = lowered.find(keyword, start)
            if index < 0:
                break
            if not _is_negated_match(index):
                return True
            start = index + len(keyword)
    return False


def _infer_trend_direction(trend: Dict[str, Any]) -> str:
    """Infer the final trend direction from trend_status and ma_alignment."""
    combined = " ".join(
        str(trend.get(key, "")).strip()
        for key in ("trend_status", "ma_alignment")
        if str(trend.get(key, "")).strip()
    )
    if not combined:
        return "neutral"
    lowered = combined.lower()
    normalized = lowered.replace(" ", "")
    has_bullish = (
        _contains_trend_hint(combined, _BULLISH_TREND_HINTS + _WEAK_BULLISH_TREND_HINTS)
        or "ma5>ma10>ma20" in normalized
        or (
            "ma5>ma10" in normalized
            and any(pattern in normalized for pattern in ("ma10≤ma20", "ma10<=ma20"))
        )
    )
    has_bearish = (
        _contains_trend_hint(combined, _BEARISH_TREND_HINTS + _WEAK_BEARISH_TREND_HINTS)
        or "ma5<ma10<ma20" in normalized
        or (
            "ma5<ma10" in normalized
            and any(pattern in normalized for pattern in ("ma10≥ma20", "ma10>=ma20"))
        )
    )
    if has_bullish and not has_bearish:
        return "bullish"
    if has_bearish and not has_bullish:
        return "bearish"
    return "neutral"


def _filter_conflicting_trend_items(items: List[str], conflict_hints: Tuple[str, ...]) -> List[str]:
    """Drop reasons that directly conflict with the final trend direction."""
    return [item for item in items if not _contains_trend_hint(item, conflict_hints)]


def _sanitize_trend_analysis_for_prompt(
    trend: Any,
    *,
    volume_change_ratio: Any = None,
) -> Dict[str, Any]:
    """Clean prompt-only trend hints on a derived copy without touching runtime/provider config."""
    trend_dict = dict(trend) if isinstance(trend, dict) else {}
    signal_reasons = _normalize_prompt_reason_items(trend_dict.get("signal_reasons"))
    risk_factors = _normalize_prompt_reason_items(trend_dict.get("risk_factors"))
    prompt_notes: List[str] = []
    trend_direction = _infer_trend_direction(trend_dict)

    if trend_direction == "bearish":
        filtered_signal_reasons = _filter_conflicting_trend_items(
            signal_reasons,
            _BULLISH_TREND_HINTS + _WEAK_BULLISH_TREND_HINTS,
        )
        if len(filtered_signal_reasons) != len(signal_reasons):
            prompt_notes.append("當前技術結構偏空，已剔除與空頭主判斷直接衝突的看多結構理由。")
        signal_reasons = filtered_signal_reasons
        prompt_notes.append(
            "若新聞、業績或政策催化偏多，只能表述為“事件先行、技術待確認”或“基本面偏多，但技術面尚未確認”，嚴禁寫成確定性買點。"
        )
    elif trend_direction == "bullish":
        filtered_signal_reasons = _filter_conflicting_trend_items(
            signal_reasons,
            _BEARISH_TREND_HINTS + _WEAK_BEARISH_TREND_HINTS,
        )
        if len(filtered_signal_reasons) != len(signal_reasons):
            prompt_notes.append("當前技術結構偏多，已剔除與多頭主判斷直接衝突的空頭結構理由。")
        signal_reasons = filtered_signal_reasons
        filtered_risk_factors = _filter_conflicting_trend_items(
            risk_factors,
            _BEARISH_TREND_HINTS + _WEAK_BEARISH_TREND_HINTS,
        )
        if len(filtered_risk_factors) != len(risk_factors):
            prompt_notes.append("當前技術結構偏多，已剔除與多頭主判斷直接衝突的空頭結構風險表述。")
        risk_factors = filtered_risk_factors

    parsed_volume_change = _safe_float(volume_change_ratio, default=math.nan)
    if math.isfinite(parsed_volume_change) and parsed_volume_change > 10:
        prompt_notes.append(
            f"成交量較昨日變化約 {parsed_volume_change:.2f} 倍，可能存在異常資料或一次性衝量；量能訊號必須降權解讀，不能機械視為強確認。"
        )

    trend_dict["signal_reasons"] = signal_reasons
    trend_dict["risk_factors"] = risk_factors
    trend_dict["prompt_consistency_notes"] = prompt_notes
    trend_dict["prompt_trend_direction"] = trend_direction
    return trend_dict


def _derive_chip_health(profit_ratio: float, concentration_90: float, language: str = "zh") -> str:
    """Derive chip_health from profit_ratio and concentration_90."""
    if profit_ratio >= 0.9:
        return localize_chip_health("警惕", language)  # 獲利盤極高
    if concentration_90 >= 0.25:
        return localize_chip_health("警惕", language)  # 籌碼分散
    if concentration_90 < 0.15 and 0.3 <= profit_ratio < 0.9:
        return localize_chip_health("健康", language)  # 集中且獲利比例適中
    return localize_chip_health("一般", language)


def _build_chip_structure_from_data(chip_data: Any, language: str = "zh") -> Dict[str, Any]:
    """Build chip_structure dict from ChipDistribution or dict."""
    if hasattr(chip_data, "profit_ratio"):
        pr = _safe_float(chip_data.profit_ratio)
        ac = chip_data.avg_cost
        c90 = _safe_float(chip_data.concentration_90)
    else:
        d = chip_data if isinstance(chip_data, dict) else {}
        pr = _safe_float(d.get("profit_ratio"))
        ac = d.get("avg_cost")
        c90 = _safe_float(d.get("concentration_90"))
    chip_health = _derive_chip_health(pr, c90, language=language)
    return {
        "profit_ratio": f"{pr:.1%}",
        "avg_cost": ac if (ac is not None and _safe_float(ac) != 0.0) else "N/A",
        "concentration": f"{c90:.2%}",
        "chip_health": chip_health,
    }


def _has_meaningful_chip_data(chip_data: Any) -> bool:
    """Return True when chip data has the core metrics required for reporting."""
    if not chip_data:
        return False
    if hasattr(chip_data, "avg_cost"):
        avg_cost = _coerce_chip_metric(getattr(chip_data, "avg_cost", None))
        concentration_90 = _coerce_chip_metric(getattr(chip_data, "concentration_90", None))
        concentration_70 = _coerce_chip_metric(getattr(chip_data, "concentration_70", None))
    else:
        d = chip_data if isinstance(chip_data, dict) else {}
        avg_cost = _coerce_chip_metric(d.get("avg_cost"))
        concentration_90_value = d.get("concentration_90")
        if concentration_90_value is None:
            concentration_90_value = d.get("concentration")
        concentration_90 = _coerce_chip_metric(concentration_90_value)
        concentration_70 = _coerce_chip_metric(d.get("concentration_70"))
    return (
        avg_cost is not None
        and avg_cost > 0
        and (
            (concentration_90 is not None and concentration_90 >= 0)
            or (concentration_70 is not None and concentration_70 >= 0)
        )
    )


def _mark_chip_structure_unavailable(result: "AnalysisResult", language: str) -> None:
    if not result or not isinstance(result.dashboard, dict):
        return
    data_perspective = result.dashboard.get("data_perspective")
    if not isinstance(data_perspective, dict):
        return
    data_perspective["chip_structure"] = {}
    data_perspective["chip_unavailable_reason"] = get_chip_unavailable_text(language)


def normalize_chip_structure_availability(result: "AnalysisResult", chip_data: Any) -> None:
    """Fill valid chip metrics or collapse placeholder-only chip fields to one fallback line."""
    if not result:
        return
    language = getattr(result, "report_language", "zh")
    if _has_meaningful_chip_data(chip_data):
        fill_chip_structure_if_needed(result, chip_data)
        return
    _mark_chip_structure_unavailable(result, language)


def fill_chip_structure_if_needed(result: "AnalysisResult", chip_data: Any) -> None:
    """When chip_data exists, fill chip_structure placeholder fields from chip_data (in-place)."""
    if not result or not _has_meaningful_chip_data(chip_data):
        return
    try:
        if not result.dashboard:
            result.dashboard = {}
        dash = result.dashboard
        # Use `or {}` rather than setdefault so that an explicit `null` from LLM is also replaced
        dp = dash.get("data_perspective") or {}
        dash["data_perspective"] = dp
        cs = dp.get("chip_structure") or {}
        filled = _build_chip_structure_from_data(
            chip_data,
            language=getattr(result, "report_language", "zh"),
        )
        # Start from a copy of cs to preserve any extra keys the LLM may have added
        merged = dict(cs)
        for k in _CHIP_KEYS:
            if _is_value_placeholder(merged.get(k)):
                merged[k] = filled[k]
        if merged != cs:
            dp["chip_structure"] = merged
            logger.info("[chip_structure] Filled placeholder chip fields from data source (Issue #589)")
    except Exception as e:
        logger.warning("[chip_structure] Fill failed, skipping: %s", e)


_PRICE_POS_KEYS = ("ma5", "ma10", "ma20", "bias_ma5", "bias_status", "current_price", "support_level", "resistance_level")


def fill_price_position_if_needed(
    result: "AnalysisResult",
    trend_result: Any = None,
    realtime_quote: Any = None,
) -> None:
    """Fill missing price_position fields from trend_result / realtime data (in-place)."""
    if not result:
        return
    try:
        if not result.dashboard:
            result.dashboard = {}
        dash = result.dashboard
        dp = dash.get("data_perspective") or {}
        dash["data_perspective"] = dp
        pp = dp.get("price_position") or {}

        computed: Dict[str, Any] = {}
        if trend_result:
            tr = trend_result if isinstance(trend_result, dict) else (
                trend_result.__dict__ if hasattr(trend_result, "__dict__") else {}
            )
            computed["ma5"] = tr.get("ma5")
            computed["ma10"] = tr.get("ma10")
            computed["ma20"] = tr.get("ma20")
            computed["bias_ma5"] = tr.get("bias_ma5")
            computed["current_price"] = tr.get("current_price")
            support_levels = tr.get("support_levels") or []
            resistance_levels = tr.get("resistance_levels") or []
            if support_levels:
                computed["support_level"] = support_levels[0]
            if resistance_levels:
                computed["resistance_level"] = resistance_levels[0]
        if realtime_quote:
            rq = realtime_quote if isinstance(realtime_quote, dict) else (
                realtime_quote.to_dict() if hasattr(realtime_quote, "to_dict") else {}
            )
            if _is_value_placeholder(computed.get("current_price")):
                computed["current_price"] = rq.get("price")

        filled = False
        for k in _PRICE_POS_KEYS:
            if _is_value_placeholder(pp.get(k)) and not _is_value_placeholder(computed.get(k)):
                pp[k] = computed[k]
                filled = True
        if filled:
            dp["price_position"] = pp
            logger.info("[price_position] Filled placeholder fields from computed data")
    except Exception as e:
        logger.warning("[price_position] Fill failed, skipping: %s", e)


def stabilize_decision_with_structure(
    result: "AnalysisResult",
    trend_result: Any = None,
    fundamental_context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Calibrate aggressive buy/sell advice with price levels and capital flow.

    The LLM can overreact to one-day price movement.  This guard keeps the
    public `decision_type` enum stable while allowing richer neutral wording
    such as 震盪/洗盤觀察 when support, resistance, and fund flow do not confirm
    an immediate buy/sell action.
    """
    if not result:
        return

    try:
        language = normalize_report_language(getattr(result, "report_language", "zh"))
        dashboard = result.dashboard if isinstance(result.dashboard, dict) else {}
        data_perspective = dashboard.get("data_perspective") if isinstance(dashboard, dict) else {}
        if not isinstance(data_perspective, dict):
            data_perspective = {}
        price_position = data_perspective.get("price_position")
        if not isinstance(price_position, dict):
            price_position = {}

        trend_dict = _as_dict_for_decision_guard(trend_result)
        current_price = _first_numeric_value(
            getattr(result, "current_price", None),
            price_position.get("current_price"),
            trend_dict.get("current_price"),
        )
        support = _first_numeric_value(
            price_position.get("support_level"),
            _first_list_value(trend_dict.get("support_levels")),
        )
        resistance = _first_numeric_value(
            price_position.get("resistance_level"),
            _first_list_value(trend_dict.get("resistance_levels")),
        )
        decision_type = infer_decision_type_from_advice(
            getattr(result, "decision_type", ""),
            default=getattr(result, "decision_type", "hold") or "hold",
        )
        decision_type = decision_type if decision_type in {"buy", "hold", "sell"} else "hold"
        advice_decision_type = infer_decision_type_from_advice(
            getattr(result, "operation_advice", ""),
            default="",
        )

        flow_bias, flow_reason = _capital_flow_bias_with_status(fundamental_context)
        if flow_bias == "unavailable":
            if isinstance(fundamental_context, dict) and "capital_flow" in fundamental_context:
                if decision_type == "buy" or advice_decision_type == "buy":
                    _downgrade_buy_without_capital_flow(
                        result,
                        language,
                        current_price=current_price,
                        support=support,
                        resistance=resistance,
                        flow_status=flow_reason,
                    )
                else:
                    _set_decision_stability_unavailable(
                        result,
                        language,
                        current_price=current_price,
                        support=support,
                        resistance=resistance,
                        flow_status=flow_reason,
                    )
            return

        if current_price is None:
            return

        broke_support = support is not None and current_price < support * 0.985
        near_support = support is not None and not broke_support and current_price <= support * 1.03
        breakout = resistance is not None and current_price > resistance * 1.01
        near_resistance = (
            resistance is not None
            and not breakout
            and current_price >= resistance * 0.97
        )
        mid_range = (
            support is not None
            and resistance is not None
            and support * 1.03 < current_price < resistance * 0.97
        )

        has_significant_risk = _has_structural_risk_alert(result)

        if decision_type == "buy":
            if near_resistance and flow_bias != "inflow":
                _downgrade_to_structural_hold(
                    result,
                    language,
                    advice_key="range",
                    reason_key="buy_near_resistance",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
            elif flow_bias == "outflow" and not breakout:
                _downgrade_to_structural_hold(
                    result,
                    language,
                    advice_key="range",
                    reason_key="buy_with_outflow",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
            elif mid_range and flow_bias == "neutral":
                _downgrade_to_structural_hold(
                    result,
                    language,
                    advice_key="range",
                    reason_key="hold_mid_range",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
        elif decision_type == "sell":
            if near_support and (flow_bias != "outflow") and not has_significant_risk:
                _downgrade_to_structural_hold(
                    result,
                    language,
                    advice_key="shakeout",
                    reason_key="sell_near_support",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
            elif flow_bias == "inflow" and not broke_support and not has_significant_risk:
                _downgrade_to_structural_hold(
                    result,
                    language,
                    advice_key="hold",
                    reason_key="sell_with_inflow",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
        elif decision_type == "hold":
            change_pct = _first_numeric_value(getattr(result, "change_pct", None))
            if change_pct is not None and change_pct < 0 and near_support and flow_bias != "outflow":
                _set_structural_hold_wording(
                    result,
                    language,
                    advice_key="shakeout",
                    reason_key="hold_shakeout",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
            elif mid_range and flow_bias == "neutral":
                _set_structural_hold_wording(
                    result,
                    language,
                    advice_key="range",
                    reason_key="hold_mid_range",
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    flow_bias=flow_bias,
                )
        _sync_stability_dashboard_fields(result)
    except Exception as exc:
        logger.warning("[decision_stability] skipped: %s", exc)


def _has_structural_risk_alert(result: "AnalysisResult") -> bool:
    dashboard = result.dashboard if isinstance(result.dashboard, dict) else {}

    risk_text = getattr(result, "risk_warning", "")
    if _is_significant_structural_risk(risk_text):
        return True

    intelligence = dashboard.get("intelligence") if isinstance(dashboard, dict) else None
    if isinstance(intelligence, dict):
        risk_alerts = intelligence.get("risk_alerts")
        if isinstance(risk_alerts, str):
            if _is_significant_structural_risk(risk_alerts):
                return True
        elif isinstance(risk_alerts, (list, tuple, set)):
            if any(_is_significant_structural_risk(item) for item in risk_alerts):
                return True

    core_conclusion = dashboard.get("core_conclusion") if isinstance(dashboard, dict) else None
    if isinstance(core_conclusion, dict):
        signal_type = str(core_conclusion.get("signal_type", "")).strip()
        if _is_significant_structural_risk(signal_type):
            return True
    return False


def _is_significant_structural_risk(value: Any) -> bool:
    text = str(value or "").strip()
    if not _is_meaningful_text(text):
        return False

    normalized = text.lower()
    if any(keyword in normalized for keyword in _STRUCTURAL_RISK_PHRASE_HINTS):
        return True

    return "重大" in text and "風險" in normalized


def _sync_stability_dashboard_fields(result: "AnalysisResult") -> None:
    dashboard = result.dashboard if isinstance(result.dashboard, dict) else {}
    result.dashboard = dashboard
    dashboard["sentiment_score"] = getattr(result, "sentiment_score", None)
    dashboard["operation_advice"] = getattr(result, "operation_advice", None)
    dashboard["decision_type"] = getattr(result, "decision_type", None)


def _as_dict_for_decision_guard(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        try:
            converted = value.to_dict()
            return converted if isinstance(converted, dict) else {}
        except Exception:
            return {}
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _first_list_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return value


def _coerce_numeric_value(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if math.isfinite(float(value)):
            return float(value)
        return None
    text = str(value).replace(",", "").replace("，", "").strip()
    if not text or text.upper() in {"N/A", "NA", "NONE", "NULL"}:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _first_numeric_value(*values: Any) -> Optional[float]:
    for value in values:
        if isinstance(value, (list, tuple)):
            nested = _first_numeric_value(*value)
            if nested is not None:
                return nested
            continue
        numeric = _coerce_numeric_value(value)
        if numeric is not None:
            return numeric
    return None


def _capital_flow_bias(fundamental_context: Optional[Dict[str, Any]]) -> str:
    return _capital_flow_bias_with_status(fundamental_context)[0]


def _capital_flow_bias_with_status(
    fundamental_context: Optional[Dict[str, Any]],
) -> tuple[str, str]:
    if not isinstance(fundamental_context, dict):
        return "unavailable", "invalid_context"
    block = fundamental_context.get("capital_flow")
    if not isinstance(block, dict):
        return "unavailable", "capital_flow_block_missing"
    status = str(block.get("status") or "").strip().lower()
    normalized_status = status.replace("-", " ").replace("_", " ").strip()
    if normalized_status in _CAPITAL_FLOW_UNAVAILABLE_STATUS or "not supported" in normalized_status:
        return "unavailable", status or "not_supported"
    data = block.get("data") if isinstance(block.get("data"), dict) else block
    stock_flow = data.get("stock_flow") if isinstance(data, dict) else None
    if not isinstance(stock_flow, dict) or not stock_flow:
        return "unavailable", "empty_stock_flow"

    def _flow_direction(value: Optional[float]) -> Optional[str]:
        if value is None or value == 0:
            return None
        return "inflow" if value > 0 else "outflow"

    numeric_values = [
        _coerce_numeric_value(stock_flow.get("main_net_inflow")),
        _coerce_numeric_value(stock_flow.get("inflow_5d")),
        _coerce_numeric_value(stock_flow.get("inflow_10d")),
    ]
    if all(value is None for value in numeric_values):
        return "unavailable", "missing_or_na_flow_fields"

    ordered_signals = [
        _flow_direction(value) for value in numeric_values
    ]
    directions = {signal for signal in ordered_signals if signal is not None}
    if not directions or len(directions) > 1:
        return "neutral", "conflict_or_missing"
    for signal in ordered_signals:
        if signal is not None:
            return signal, "ok"
    return "neutral", "neutral"


def _capital_flow_status_for_stability(reason: str, language: str) -> str:
    normalized = str(reason or "").strip().lower()
    if "not_supported" in normalized or "unsupported" in normalized or "not available" in normalized:
        return "市場資金流服務暫不支援" if language == "zh" else "Capital flow source unsupported"
    if "empty_stock_flow" in normalized or "missing" in normalized:
        return "資金流資料缺失" if language == "zh" else "capital flow data unavailable"
    return "資金流資料不可用" if language == "zh" else "capital flow unavailable"


def _set_decision_stability_unavailable(
    result: "AnalysisResult",
    language: str,
    *,
    current_price: Optional[float],
    support: Optional[float],
    resistance: Optional[float],
    flow_status: str,
) -> None:
    dashboard = result.dashboard if isinstance(result.dashboard, dict) else {}
    result.dashboard = dashboard
    dashboard["decision_stability"] = {
        "applied": False,
        "reason": "資金流不可用，未使用資金流校準" if language == "zh" else "Capital flow unavailable; stability calibration not applied",
        "capital_flow_status": _capital_flow_status_for_stability(flow_status, language),
        "current_price": current_price,
        "support": support,
        "resistance": resistance,
        "capital_flow_bias": "unavailable",
    }
    _sync_stability_dashboard_fields(result)


def _bound_hold_watch_sentiment_score(result: "AnalysisResult") -> None:
    try:
        score = int(getattr(result, "sentiment_score", 50))
    except (TypeError, ValueError):
        score = 50
    result.sentiment_score = min(59, max(45, score))


def _apply_hold_watch_dashboard(
    result: "AnalysisResult",
    language: str,
    *,
    advice: str,
    reason: str,
    current_price: Optional[float],
    support: Optional[float],
    resistance: Optional[float],
    flow_bias: str,
    no_position: str,
    has_position: str,
    capital_flow_status: Optional[str] = None,
) -> None:
    result.operation_advice = advice

    dashboard = result.dashboard if isinstance(result.dashboard, dict) else {}
    result.dashboard = dashboard
    core = dashboard.get("core_conclusion")
    if not isinstance(core, dict):
        core = {}
        dashboard["core_conclusion"] = core
    core["signal_type"] = "🟡持有觀望" if language == "zh" else "🟡 Hold / Watch"
    core["one_sentence"] = f"{advice}：{reason}" if language == "zh" else f"{advice}: {reason}"

    position_advice = core.get("position_advice")
    if not isinstance(position_advice, dict):
        position_advice = {}
        core["position_advice"] = position_advice
    position_advice["no_position"] = no_position
    position_advice["has_position"] = has_position

    stability = {
        "applied": True,
        "reason": reason,
        "current_price": current_price,
        "support": support,
        "resistance": resistance,
        "capital_flow_bias": flow_bias,
    }
    if capital_flow_status is not None:
        stability["capital_flow_status"] = capital_flow_status
    dashboard["decision_stability"] = stability

    if reason and reason not in str(result.risk_warning or ""):
        sep = "；" if language == "zh" else "; "
        result.risk_warning = f"{result.risk_warning}{sep}{reason}" if result.risk_warning else reason
    result.buy_reason = reason or result.buy_reason


def _downgrade_buy_without_capital_flow(
    result: "AnalysisResult",
    language: str,
    *,
    current_price: Optional[float],
    support: Optional[float],
    resistance: Optional[float],
    flow_status: str,
) -> None:
    status_text = _capital_flow_status_for_stability(flow_status, language)
    if language == "zh":
        advice = "持有觀察"
        reason = f"{status_text}，買進結論缺少資金面確認，先按觀察處理。"
        no_position = "空倉先不追買，等待資金流恢復、支撐確認或有效突破後再行動。"
        has_position = "持股以關鍵支撐為風控線，資金流恢復前控制部位。"
        confidence = "低"
    else:
        advice = "Hold and watch"
        reason = f"{status_text}; the buy call lacks capital-flow confirmation, so treat it as watch-only."
        no_position = "Do not chase; wait for capital-flow recovery, support confirmation, or a valid breakout."
        has_position = "Use key support as the risk line and keep position size controlled until capital flow recovers."
        confidence = "Low"

    result.decision_type = "hold"
    result.confidence_level = confidence
    _bound_hold_watch_sentiment_score(result)
    _apply_hold_watch_dashboard(
        result,
        language,
        advice=advice,
        reason=reason,
        current_price=current_price,
        support=support,
        resistance=resistance,
        flow_bias="unavailable",
        no_position=no_position,
        has_position=has_position,
        capital_flow_status=status_text,
    )
    _sync_stability_dashboard_fields(result)
    logger.info("[decision_stability] Downgraded buy because capital flow is unavailable: %s", flow_status)


def _downgrade_to_structural_hold(
    result: "AnalysisResult",
    language: str,
    *,
    advice_key: str,
    reason_key: str,
    current_price: float,
    support: Optional[float],
    resistance: Optional[float],
    flow_bias: str,
) -> None:
    result.decision_type = "hold"
    _bound_hold_watch_sentiment_score(result)
    _set_structural_hold_wording(
        result,
        language,
        advice_key=advice_key,
        reason_key=reason_key,
        current_price=current_price,
        support=support,
        resistance=resistance,
        flow_bias=flow_bias,
    )


def _set_structural_hold_wording(
    result: "AnalysisResult",
    language: str,
    *,
    advice_key: str,
    reason_key: str,
    current_price: float,
    support: Optional[float],
    resistance: Optional[float],
    flow_bias: str,
) -> None:
    _advice_map = {
        "zh": {
            "range": "震盪觀望",
            "shakeout": "洗盤觀察",
            "hold": "持有觀察",
        },
        "zh_TW": {
            "range": "震盪觀望",
            "shakeout": "洗盤觀察",
            "hold": "持有觀察",
        },
        "en": {
            "range": "Range-bound watch",
            "shakeout": "Shakeout watch",
            "hold": "Hold and watch",
        },
    }
    _lang_key = language if language in _advice_map else "zh"
    _default_advice = "持有觀察" if language == "zh_TW" else ("持有觀察" if language == "zh" else "Hold and watch")
    advice = _advice_map[_lang_key].get(advice_key, _default_advice)
    reason_templates = {
        "zh": {
            "buy_near_resistance": "價格接近壓力位且主力資金未確認流入，不宜僅因短線反彈追買。",
            "buy_with_outflow": "主力資金流出與買進結論衝突，買點需等待支撐確認或資金迴流。",
            "sell_near_support": "價格貼近支撐且未見資金持續流出，不宜僅因單日下跌直接賣出。",
            "sell_with_inflow": "主力資金流入與賣出結論衝突，先按持有觀察處理並跟蹤支撐失效。",
            "hold_shakeout": "價格回落至支撐附近但資金未確認流出，更適合按洗盤觀察處理。",
            "hold_mid_range": "價格處於支撐與壓力之間且資金流不明確，維持震盪觀望更可操作。",
        },
        "zh_TW": {
            "buy_near_resistance": "價格接近壓力位且主力資金未確認流入，不宜僅因短線反彈追買。",
            "buy_with_outflow": "主力資金流出與買進結論衝突，買點需等待支撐確認或資金迴流。",
            "sell_near_support": "價格貼近支撐且未見資金持續流出，不宜僅因單日下跌直接賣出。",
            "sell_with_inflow": "主力資金流入與賣出結論衝突，先按持有觀察處理並追蹤支撐失效。",
            "hold_shakeout": "價格回落至支撐附近但資金未確認流出，更適合按洗盤觀察處理。",
            "hold_mid_range": "價格處於支撐與壓力之間且資金流不明確，維持震盪觀望更可操作。",
        },
        "en": {
            "buy_near_resistance": "Price is near resistance without confirmed main-force inflow, so chasing the rebound is not actionable.",
            "buy_with_outflow": "Main-force outflow conflicts with a buy call; wait for support confirmation or capital inflow.",
            "sell_near_support": "Price is near support without sustained outflow, so a one-day drop is not enough to sell.",
            "sell_with_inflow": "Main-force inflow conflicts with a sell call; hold and watch for support failure.",
            "hold_shakeout": "Price pulled back near support without confirmed outflow, which is better treated as a shakeout watch.",
            "hold_mid_range": "Price is between support and resistance with neutral fund flow, so range-bound watch is more actionable.",
        },
    }
    reason = reason_templates.get(_lang_key, reason_templates["zh"]).get(reason_key, "")
    result.operation_advice = advice
    if language in ("zh", "zh_TW") and advice_key == "range":
        _sideways = "震盪" if language == "zh_TW" else "震盪"
        if _sideways not in str(result.trend_prediction) and "震" not in str(result.trend_prediction):
            result.trend_prediction = _sideways
    elif language == "en" and advice_key == "range":
        result.trend_prediction = "Sideways"

    if language == "zh_TW":
        no_position = "空倉先不追漲殺跌，等待支撐確認、放量突破或資金迴流後再行動。"
        has_position = "持股以關鍵支撐為風控線，未跌破前以觀察和分批控倉為主。"
    elif language == "zh":
        no_position = "空倉先不追漲殺跌，等待支撐確認、放量突破或資金迴流後再行動。"
        has_position = "持股以關鍵支撐為風控線，未跌破前以觀察和分批控倉為主。"
    else:
        no_position = "Do not chase or panic; wait for support confirmation, breakout, or renewed inflow."
        has_position = "Use key support as the risk line and manage position size unless support fails."
    _apply_hold_watch_dashboard(
        result,
        language,
        advice=advice,
        reason=reason,
        current_price=current_price,
        support=support,
        resistance=resistance,
        flow_bias=flow_bias,
        no_position=no_position,
        has_position=has_position,
    )
    logger.info("[decision_stability] Applied structural hold calibration: %s", reason_key)


def get_stock_name_multi_source(
    stock_code: str,
    context: Optional[Dict] = None,
    data_manager = None
) -> str:
    """
    多來源獲取股票中文名稱

    獲取策略（按優先順序）：
    1. 從傳入的 context 中獲取（realtime 資料）
    2. 從靜態對映表 STOCK_NAME_MAP 獲取
    3. 從 DataFetcherManager 獲取（各資料來源）
    4. 返回預設名稱（股票+程式碼）

    Args:
        stock_code: 股票程式碼
        context: 分析上下文（可選）
        data_manager: DataFetcherManager 例項（可選）

    Returns:
        股票中文名稱
    """
    # 1. 從上下文獲取（實時行情資料）
    if context:
        # 優先從 stock_name 欄位獲取
        if context.get('stock_name'):
            name = context['stock_name']
            if name and not name.startswith('股票'):
                return name

        # 其次從 realtime 資料獲取
        if 'realtime' in context and context['realtime'].get('name'):
            return context['realtime']['name']

    # 2. 從靜態對映表獲取
    if stock_code in STOCK_NAME_MAP:
        return STOCK_NAME_MAP[stock_code]

    # 3. 從資料來源獲取
    if data_manager is None:
        try:
            from data_provider.base import DataFetcherManager
            data_manager = DataFetcherManager()
        except Exception as e:
            logger.debug(f"無法初始化 DataFetcherManager: {e}")

    if data_manager:
        try:
            name = data_manager.get_stock_name(stock_code)
            if name:
                # 更新快取
                STOCK_NAME_MAP[stock_code] = name
                return name
        except Exception as e:
            logger.debug(f"從資料來源獲取股票名稱失敗: {e}")

    # 4. 返回預設名稱
    return f'股票{stock_code}'


@dataclass
class AnalysisResult:
    """
    AI 分析結果資料類 - 決策儀表盤版

    封裝 Gemini 返回的分析結果，包含決策儀表盤和詳細分析
    """
    code: str
    name: str

    # ========== 核心指標 ==========
    sentiment_score: int  # 綜合評分 0-100 (>70強烈看多, >60看多, 40-60震盪, <40看空)
    trend_prediction: str  # 趨勢預測：強烈看多/看多/震盪/看空/強烈看空
    operation_advice: str  # 操作建議：買進/加倉/持有/減倉/賣出/觀望
    decision_type: str = "hold"  # 決策型別：buy/hold/sell（用於統計）
    confidence_level: str = "中"  # 置信度：高/中/低
    report_language: str = "zh"  # 報告輸出語言：zh/en

    # ========== 決策儀表盤 (新增) ==========
    dashboard: Optional[Dict[str, Any]] = None  # 完整的決策儀表盤資料

    # ========== 走勢分析 ==========
    trend_analysis: str = ""  # 走勢形態分析（支撐位、壓力位、趨勢線等）
    short_term_outlook: str = ""  # 短期展望（1-3日）
    medium_term_outlook: str = ""  # 中期展望（1-2周）

    # ========== 技術面分析 ==========
    technical_analysis: str = ""  # 技術指標綜合分析
    ma_analysis: str = ""  # 均線分析（多頭/空頭排列，金叉/死叉等）
    volume_analysis: str = ""  # 量能分析（放量/縮量，主力動向等）
    pattern_analysis: str = ""  # K線形態分析

    # ========== 基本面分析 ==========
    fundamental_analysis: str = ""  # 基本面綜合分析
    sector_position: str = ""  # 板塊地位和行業趨勢
    company_highlights: str = ""  # 公司亮點/風險點

    # ========== 情緒面/訊息面分析 ==========
    news_summary: str = ""  # 近期重要新聞/公告摘要
    market_sentiment: str = ""  # 市場情緒分析
    hot_topics: str = ""  # 相關熱點話題

    # ========== 綜合分析 ==========
    analysis_summary: str = ""  # 綜合分析摘要
    key_points: str = ""  # 核心看點（3-5個要點）
    risk_warning: str = ""  # 風險提示
    buy_reason: str = ""  # 買進/賣出理由

    # ========== 後設資料 ==========
    market_snapshot: Optional[Dict[str, Any]] = None  # 當日行情快照（展示用）
    raw_response: Optional[str] = None  # 原始響應（除錯用）
    search_performed: bool = False  # 是否執行了聯網搜尋
    data_sources: str = ""  # 資料來源說明
    value_network_mermaid: Optional[str] = None  # Phase 18A：可選的價值網路圖 Mermaid 原始文字（已驗證或 None）
    # Phase 25.6：可選的四大師視角補充（點評式，不含行動、不覆蓋原始建議；渲染時再驗證/淨化）
    four_masters_commentary: Optional[Dict[str, Any]] = None
    instrument_type: str = "unknown"  # Phase 19B.1：報告契約欄位，僅來自 SymbolRecord，非 LLM 推論
    # Phase 19B.2：股票專屬估值/基本面快照，由後端決定性組裝（FinMind/yfinance），非 LLM 推論
    valuation_snapshot: Optional[Dict[str, Any]] = None
    fundamental_snapshot: Optional[Dict[str, Any]] = None
    # Phase 19B.3：ETF/指數專屬曝險/市場風險快照，由後端決定性組裝，非 LLM 推論
    exposure_snapshot: Optional[Dict[str, Any]] = None
    market_risk_snapshot: Optional[Dict[str, Any]] = None
    # Phase 19B.4：股票/ETF/指數多週期趨勢快照，由後端從已抓取的 OHLC 資料決定性計算，非 LLM 推論
    multi_period_trend_snapshot: Optional[Dict[str, Any]] = None
    # Phase 19G-R7B：市場恐慌指標快照。US=VIX，TW=VIXTWN；分析時決定性擷取，非 LLM 推論
    market_fear_index_snapshot: Optional[Dict[str, Any]] = None
    success: bool = True
    error_message: Optional[str] = None

    # ========== 價格資料（分析時快照）==========
    current_price: Optional[float] = None  # 分析時的股價
    change_pct: Optional[float] = None     # 分析時的漲跌幅(%)

    # ========== 模型標記（Issue #528）==========
    model_used: Optional[str] = None  # 分析使用的 LLM 模型（完整名，如 gemini/gemini-2.0-flash）

    # ========== 歷史對比（Report Engine P0）==========
    query_id: Optional[str] = None  # 本次分析 query_id，用於歷史對比時排除本次記錄

    # ========== 基本面上下文（僅執行時，用於通知拼裝；不持久化到 to_dict）==========
    fundamental_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典"""
        return {
            'code': self.code,
            'name': self.name,
            'sentiment_score': self.sentiment_score,
            'trend_prediction': self.trend_prediction,
            'operation_advice': self.operation_advice,
            'decision_type': self.decision_type,
            'confidence_level': self.confidence_level,
            'report_language': self.report_language,
            'dashboard': self.dashboard,  # 決策儀表盤資料
            'trend_analysis': self.trend_analysis,
            'short_term_outlook': self.short_term_outlook,
            'medium_term_outlook': self.medium_term_outlook,
            'technical_analysis': self.technical_analysis,
            'ma_analysis': self.ma_analysis,
            'volume_analysis': self.volume_analysis,
            'pattern_analysis': self.pattern_analysis,
            'fundamental_analysis': self.fundamental_analysis,
            'sector_position': self.sector_position,
            'company_highlights': self.company_highlights,
            'news_summary': self.news_summary,
            'market_sentiment': self.market_sentiment,
            'hot_topics': self.hot_topics,
            'analysis_summary': self.analysis_summary,
            'key_points': self.key_points,
            'risk_warning': self.risk_warning,
            'buy_reason': self.buy_reason,
            'market_snapshot': self.market_snapshot,
            'search_performed': self.search_performed,
            'success': self.success,
            'error_message': self.error_message,
            'current_price': self.current_price,
            'change_pct': self.change_pct,
            'model_used': self.model_used,
            'value_network_mermaid': self.value_network_mermaid,
            'four_masters_commentary': self.four_masters_commentary,
            'instrument_type': self.instrument_type,
            'valuation_snapshot': self.valuation_snapshot,
            'fundamental_snapshot': self.fundamental_snapshot,
            'exposure_snapshot': self.exposure_snapshot,
            'market_risk_snapshot': self.market_risk_snapshot,
            'multi_period_trend_snapshot': self.multi_period_trend_snapshot,
            'market_fear_index_snapshot': self.market_fear_index_snapshot,
        }

    def get_core_conclusion(self) -> str:
        """獲取核心結論（一句話）"""
        if self.dashboard and 'core_conclusion' in self.dashboard:
            return self.dashboard['core_conclusion'].get('one_sentence', self.analysis_summary)
        return self.analysis_summary

    def get_position_advice(self, has_position: bool = False) -> str:
        """獲取持股建議"""
        if self.dashboard and 'core_conclusion' in self.dashboard:
            pos_advice = self.dashboard['core_conclusion'].get('position_advice', {})
            if has_position:
                return pos_advice.get('has_position', self.operation_advice)
            return pos_advice.get('no_position', self.operation_advice)
        return self.operation_advice

    def get_sniper_points(self) -> Dict[str, str]:
        """獲取狙擊點位"""
        if self.dashboard and 'battle_plan' in self.dashboard:
            return self.dashboard['battle_plan'].get('sniper_points', {})
        return {}

    def get_checklist(self) -> List[str]:
        """獲取檢查清單"""
        if self.dashboard and 'battle_plan' in self.dashboard:
            return self.dashboard['battle_plan'].get('action_checklist', [])
        return []

    def get_risk_alerts(self) -> List[str]:
        """獲取風險警報"""
        if self.dashboard and 'intelligence' in self.dashboard:
            return self.dashboard['intelligence'].get('risk_alerts', [])
        return []

    def get_emoji(self) -> str:
        """根據操作建議返回對應 emoji"""
        _, emoji, _ = get_signal_level(
            self.operation_advice,
            self.sentiment_score,
            self.report_language,
        )
        return emoji

    def get_confidence_stars(self) -> str:
        """返回置信度星級"""
        star_map = {
            "高": "⭐⭐⭐",
            "high": "⭐⭐⭐",
            "中": "⭐⭐",
            "medium": "⭐⭐",
            "低": "⭐",
            "low": "⭐",
        }
        return star_map.get(str(self.confidence_level or "").strip().lower(), "⭐⭐")


class GeminiAnalyzer:
    """
    Gemini AI 分析器

    職責：
    1. 呼叫 Google Gemini API 進行股票分析
    2. 結合預先搜尋的新聞和技術面資料生成分析報告
    3. 解析 AI 返回的 JSON 格式結果

    使用方式：
        analyzer = GeminiAnalyzer()
        result = analyzer.analyze(context, news_context)
    """

    # ========================================
    # 系統提示詞 - 決策儀表盤 v2.0
    # ========================================
    # 輸出格式升級：從簡單訊號升級為決策儀表盤
    # 核心模組：核心結論 + 資料透視 + 輿情情報 + 作戰計劃
    # ========================================

    LEGACY_DEFAULT_SYSTEM_PROMPT = """你是一位專注於趨勢交易的{market_placeholder}投資分析師，負責生成專業的【決策儀表盤】分析報告。

{guidelines_placeholder}

""" + CORE_TRADING_SKILL_POLICY_ZH + """

## 輸出格式：決策儀表盤 JSON

請嚴格按照以下 JSON 格式輸出，這是一個完整的【決策儀表盤】：

```json
{
    "stock_name": "股票中文名稱",
    "sentiment_score": 0-100整數,
    "trend_prediction": "強烈看多/看多/震盪/看空/強烈看空",
    "operation_advice": "買進/加倉/持有/減倉/賣出/觀望",
    "decision_type": "buy/hold/sell",
    "confidence_level": "高/中/低",

    "dashboard": {
        "core_conclusion": {
            "one_sentence": "一句話核心結論（30字以內，直接告訴使用者做什麼）",
            "signal_type": "🟢買進訊號/🟡持有觀望/🔴賣出訊號/⚠️風險警告",
            "time_sensitivity": "立即行動/今日內/本週內/不急",
            "position_advice": {
                "no_position": "空倉者建議：具體操作指引",
                "has_position": "持股者建議：具體操作指引"
            }
        },

        "data_perspective": {
            "trend_status": {
                "ma_alignment": "均線排列狀態描述",
                "is_bullish": true/false,
                "trend_score": 0-100
            },
            "price_position": {
                "current_price": 當前價格數值,
                "ma5": MA5數值,
                "ma10": MA10數值,
                "ma20": MA20數值,
                "bias_ma5": 乖離率百分比數值,
                "bias_status": "安全/警戒/危險",
                "support_level": 支撐位價格,
                "resistance_level": 壓力位價格
            },
            "volume_analysis": {
                "volume_ratio": 量比數值,
                "volume_status": "放量/縮量/平量",
                "turnover_rate": 換手率百分比,
                "volume_meaning": "量能含義解讀（如：縮量回撥錶示拋壓減輕）"
            },
            "chip_structure": {
                "profit_ratio": 獲利比例,
                "avg_cost": 平均成本,
                "concentration": 籌碼集中度,
                "chip_health": "健康/一般/警惕"
            }
        },

        "intelligence": {
            "latest_news": "【最新訊息】近期重要新聞摘要",
            "risk_alerts": ["風險點1：具體描述", "風險點2：具體描述"],
            "positive_catalysts": ["利好1：具體描述", "利好2：具體描述"],
            "earnings_outlook": "業績預期分析（基於年報預告、業績快報等）",
            "sentiment_summary": "輿情情緒一句話總結"
        },

        "battle_plan": {
            "sniper_points": {
                "ideal_buy": "理想買進點：XX元（在MA5附近）",
                "secondary_buy": "次優買進點：XX元（在MA10附近）",
                "stop_loss": "止損位：XX元（跌破MA20或X%）",
                "take_profit": "目標位：XX元（前高/整數關口）"
            },
            "position_strategy": {
                "suggested_position": "建議部位：X成",
                "entry_plan": "分批建倉策略描述",
                "risk_control": "風控策略描述"
            },
            "action_checklist": [
                "✅/⚠️/❌ 檢查項1：多頭排列",
                "✅/⚠️/❌ 檢查項2：乖離率合理（強勢趨勢可放寬）",
                "✅/⚠️/❌ 檢查項3：量能配合",
                "✅/⚠️/❌ 檢查項4：無重大利空",
                "✅/⚠️/❌ 檢查項5：籌碼健康",
                "✅/⚠️/❌ 檢查項6：PE估值合理"
            ]
        },

        "phase_decision": {
            "phase_context": {"phase": "premarket/intraday/lunch_break/closing_auction/postmarket/non_trading/unknown"},
            "action_window": "盤前計劃/盤中跟蹤/午間確認/收盤前風控/盤後覆盤/非交易日觀察",
            "immediate_action": "立即行動/等待確認/觀察/止損止盈預警/禁止追高/無盤中動作",
            "watch_conditions": ["觀察條件1", "觀察條件2"],
            "next_check_time": "下一次檢查點或市場本地時間",
            "confidence_reason": "置信度理由，說明階段和資料質量限制",
            "data_limitations": ["階段或資料質量限制1", "階段或資料質量限制2"]
        }
    },

    "analysis_summary": "100字綜合分析摘要",
    "key_points": "3-5個核心看點，逗號分隔",
    "risk_warning": "風險提示",
    "buy_reason": "操作理由，引用交易理念",

    "trend_analysis": "走勢形態分析",
    "short_term_outlook": "短期1-3日展望",
    "medium_term_outlook": "中期1-2周展望",
    "technical_analysis": "技術面綜合分析",
    "ma_analysis": "均線系統分析",
    "volume_analysis": "量能分析",
    "pattern_analysis": "K線形態分析",
    "fundamental_analysis": "基本面分析",
    "sector_position": "板塊行業分析",
    "company_highlights": "公司亮點/風險",
    "news_summary": "新聞摘要",
    "market_sentiment": "市場情緒",
    "hot_topics": "相關熱點",

    "search_performed": true/false,
    "data_sources": "資料來源說明"{value_network_schema_field}
}
```

## 評分標準

### 強烈買進（80-100分）：
- ✅ 多頭排列：MA5 > MA10 > MA20
- ✅ 低乖離率：<2%，最佳買點
- ✅ 縮量回撥或放量突破
- ✅ 籌碼集中健康
- ✅ 訊息面有利好催化

### 買進（60-79分）：
- ✅ 多頭排列或弱勢多頭
- ✅ 乖離率 <5%
- ✅ 量能正常
- ⚪ 允許一項次要條件不滿足

### 觀望（40-59分）：
- ⚠️ 乖離率 >5%（追高風險）
- ⚠️ 均線纏繞趨勢不明
- ⚠️ 有風險事件

### 賣出/減倉（0-39分）：
- ❌ 空頭排列
- ❌ 跌破MA20
- ❌ 放量下跌
- ❌ 重大利空

## 決策儀表盤核心原則

1. **核心結論先行**：一句話說清該買該賣
2. **分持股建議**：空倉者和持股者給不同建議
3. **精確狙擊點**：必須給出具體價格，不說模糊的話
4. **檢查清單視覺化**：用 ✅⚠️❌ 明確顯示每項檢查結果
5. **風險優先順序**：輿情中的風險點要醒目標出

## 可操作性與穩定性約束

- 不得僅因為單日漲跌或評分跨線就在“買進/賣出”之間劇烈切換。
- 操作建議必須同時參考價格位置（支撐/壓力位）、量能/籌碼、主力資金流向和風險事件。
- 股價位於支撐與壓力之間、資金流不明確時，優先輸出“持有/震盪/觀望/洗盤觀察”等可執行的中性建議；`decision_type` 仍保持 `hold`。
- 只有在接近支撐確認或有效突破壓力，且資金流/量價配合時，才能給出買進；接近壓力且資金流出時不得追買。
- 只有在跌破關鍵支撐、主力資金持續流出或風險顯著放大時，才能給出賣出/減倉。
- 必須輸出 `dashboard.phase_decision` 七欄位；盤中/午休/臨近收盤要給出當前動作、觀察條件和下一次檢查點。
- 盤前、非交易日或未知階段不得偽造今日盤中走勢；quote/daily_bars/technical 存在 stale、fallback、missing、fetch_failed、partial 或 estimated 時，`confidence_level` 不得為高。"""

    SYSTEM_PROMPT = """你是一位{market_placeholder}投資分析師，負責生成專業的【決策儀表盤】分析報告。

{guidelines_placeholder}

{default_skill_policy_section}
{skills_section}

## 輸出格式：決策儀表盤 JSON

請嚴格按照以下 JSON 格式輸出，這是一個完整的【決策儀表盤】：

```json
{
    "stock_name": "股票中文名稱",
    "sentiment_score": 0-100整數,
    "trend_prediction": "強烈看多/看多/震盪/看空/強烈看空",
    "operation_advice": "買進/加倉/持有/減倉/賣出/觀望",
    "decision_type": "buy/hold/sell",
    "confidence_level": "高/中/低",

    "dashboard": {
        "core_conclusion": {
            "one_sentence": "一句話核心結論（30字以內，直接告訴使用者做什麼）",
            "signal_type": "🟢買進訊號/🟡持有觀望/🔴賣出訊號/⚠️風險警告",
            "time_sensitivity": "立即行動/今日內/本週內/不急",
            "position_advice": {
                "no_position": "空倉者建議：具體操作指引",
                "has_position": "持股者建議：具體操作指引"
            }
        },

        "data_perspective": {
            "trend_status": {
                "ma_alignment": "均線排列狀態描述",
                "is_bullish": true/false,
                "trend_score": 0-100
            },
            "price_position": {
                "current_price": 當前價格數值,
                "ma5": MA5數值,
                "ma10": MA10數值,
                "ma20": MA20數值,
                "bias_ma5": 乖離率百分比數值,
                "bias_status": "安全/警戒/危險",
                "support_level": 支撐位價格,
                "resistance_level": 壓力位價格
            },
            "volume_analysis": {
                "volume_ratio": 量比數值,
                "volume_status": "放量/縮量/平量",
                "turnover_rate": 換手率百分比,
                "volume_meaning": "量能含義解讀（如：縮量回撥錶示拋壓減輕）"
            },
            "chip_structure": {
                "profit_ratio": 獲利比例,
                "avg_cost": 平均成本,
                "concentration": 籌碼集中度,
                "chip_health": "健康/一般/警惕"
            }
        },

        "intelligence": {
            "latest_news": "【最新訊息】近期重要新聞摘要",
            "risk_alerts": ["風險點1：具體描述", "風險點2：具體描述"],
            "positive_catalysts": ["利好1：具體描述", "利好2：具體描述"],
            "earnings_outlook": "業績預期分析（基於年報預告、業績快報等）",
            "sentiment_summary": "輿情情緒一句話總結"
        },

        "battle_plan": {
            "sniper_points": {
                "ideal_buy": "理想入場位：XX元（滿足主要技能觸發條件）",
                "secondary_buy": "次優入場位：XX元（更保守或確認後執行）",
                "stop_loss": "止損位：XX元（失效條件或X%風險）",
                "take_profit": "目標位：XX元（按阻力位/風險回報比制定）"
            },
            "position_strategy": {
                "suggested_position": "建議部位：X成",
                "entry_plan": "分批建倉策略描述",
                "risk_control": "風控策略描述"
            },
            "action_checklist": [
                "✅/⚠️/❌ 檢查項1：當前結構是否滿足啟用技能條件",
                "✅/⚠️/❌ 檢查項2：入場位置與風險回報是否合理",
                "✅/⚠️/❌ 檢查項3：量價/波動/籌碼是否支援判斷",
                "✅/⚠️/❌ 檢查項4：無重大利空",
                "✅/⚠️/❌ 檢查項5：部位與止損計劃明確",
                "✅/⚠️/❌ 檢查項6：估值/業績/催化與結論匹配"
            ]
        },

        "phase_decision": {
            "phase_context": {"phase": "premarket/intraday/lunch_break/closing_auction/postmarket/non_trading/unknown"},
            "action_window": "盤前計劃/盤中跟蹤/午間確認/收盤前風控/盤後覆盤/非交易日觀察",
            "immediate_action": "立即行動/等待確認/觀察/止損止盈預警/禁止追高/無盤中動作",
            "watch_conditions": ["觀察條件1", "觀察條件2"],
            "next_check_time": "下一次檢查點或市場本地時間",
            "confidence_reason": "置信度理由，說明階段和資料質量限制",
            "data_limitations": ["階段或資料質量限制1", "階段或資料質量限制2"]
        }
    },

    "analysis_summary": "100字綜合分析摘要",
    "key_points": "3-5個核心看點，逗號分隔",
    "risk_warning": "風險提示",
    "buy_reason": "操作理由，引用啟用技能或風險框架",

    "trend_analysis": "走勢形態分析",
    "short_term_outlook": "短期1-3日展望",
    "medium_term_outlook": "中期1-2周展望",
    "technical_analysis": "技術面綜合分析",
    "ma_analysis": "均線系統分析",
    "volume_analysis": "量能分析",
    "pattern_analysis": "K線形態分析",
    "fundamental_analysis": "基本面分析",
    "sector_position": "板塊行業分析",
    "company_highlights": "公司亮點/風險",
    "news_summary": "新聞摘要",
    "market_sentiment": "市場情緒",
    "hot_topics": "相關熱點",

    "search_performed": true/false,
    "data_sources": "資料來源說明"{value_network_schema_field}
}
```

## 評分標準

### 強烈買進（80-100分）：
- ✅ 多個啟用技能同時支援積極結論
- ✅ 上行空間、觸發條件與風險回報清晰
- ✅ 關鍵風險已排查，部位與止損計劃明確
- ✅ 重要資料和情報結論彼此一致

### 買進（60-79分）：
- ✅ 主訊號偏積極，但仍有少量待確認項
- ✅ 允許存在可控風險或次優入場點
- ✅ 需要在報告中明確補充觀察條件

### 觀望（40-59分）：
- ⚠️ 訊號分歧較大，或缺乏足夠確認
- ⚠️ 風險與機會大致均衡
- ⚠️ 更適合等待觸發條件或迴避不確定性

### 賣出/減倉（0-39分）：
- ❌ 主要結論轉弱，風險明顯高於收益
- ❌ 觸發了止損/失效條件或重大利空
- ❌ 現有部位更需要保護而不是進攻

## 決策儀表盤核心原則

1. **核心結論先行**：一句話說清該買該賣
2. **分持股建議**：空倉者和持股者給不同建議
3. **精確狙擊點**：必須給出具體價格，不說模糊的話
4. **檢查清單視覺化**：用 ✅⚠️❌ 明確顯示每項檢查結果
5. **風險優先順序**：輿情中的風險點要醒目標出

## 可操作性與穩定性約束

- 不得僅因為單日漲跌或評分跨線就在“買進/賣出”之間劇烈切換。
- 操作建議必須同時參考價格位置（支撐/壓力位）、量能/籌碼、主力資金流向和風險事件。
- 股價位於支撐與壓力之間、資金流不明確時，優先輸出“持有/震盪/觀望/洗盤觀察”等可執行的中性建議；`decision_type` 仍保持 `hold`。
- 只有在接近支撐確認或有效突破壓力，且資金流/量價配合時，才能給出買進；接近壓力且資金流出時不得追買。
- 只有在跌破關鍵支撐、主力資金持續流出或風險顯著放大時，才能給出賣出/減倉。
- 必須輸出 `dashboard.phase_decision` 七欄位；盤中/午休/臨近收盤要給出當前動作、觀察條件和下一次檢查點。
- 盤前、非交易日或未知階段不得偽造今日盤中走勢；quote/daily_bars/technical 存在 stale、fallback、missing、fetch_failed、partial 或 estimated 時，`confidence_level` 不得為高。"""

    TEXT_SYSTEM_PROMPT = """你是一位專業的股票分析助手。

- 回答必須基於使用者提供的資料與上下文
- 若資訊不足，要明確指出不確定性
- 不要編造價格、財報或新聞事實
"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        config: Optional[Config] = None,
        skills: Optional[List[str]] = None,
        skill_instructions: Optional[str] = None,
        default_skill_policy: Optional[str] = None,
        use_legacy_default_prompt: Optional[bool] = None,
    ):
        """Initialize LLM Analyzer via LiteLLM.

        Args:
            api_key: Ignored (kept for backward compatibility). Keys are loaded from config.
        """
        self._config_override = config
        self._requested_skills = list(skills) if skills is not None else None
        self._skill_instructions_override = skill_instructions
        self._default_skill_policy_override = default_skill_policy
        self._use_legacy_default_prompt_override = use_legacy_default_prompt
        self._resolved_prompt_state: Optional[Dict[str, Any]] = None
        self._router = None
        self._legacy_router_model_list: List[Dict[str, Any]] = []
        self._litellm_available = False
        self._init_litellm()
        if not self._litellm_available:
            logger.warning("No LLM configured (LITELLM_MODEL / API keys), AI analysis will be unavailable")

    def _get_runtime_config(self) -> Config:
        """Return the runtime config, honoring injected overrides for tests/pipeline."""
        return getattr(self, "_config_override", None) or get_config()

    def _get_skill_prompt_sections(self) -> tuple[str, str, bool]:
        """Resolve skill instructions + default baseline + prompt mode."""
        skill_instructions = getattr(self, "_skill_instructions_override", None)
        default_skill_policy = getattr(self, "_default_skill_policy_override", None)
        use_legacy_default_prompt = getattr(self, "_use_legacy_default_prompt_override", None)

        if skill_instructions is not None and default_skill_policy is not None:
            return (
                skill_instructions,
                default_skill_policy,
                bool(use_legacy_default_prompt) if use_legacy_default_prompt is not None else False,
            )

        resolved_state = getattr(self, "_resolved_prompt_state", None)
        if resolved_state is None:
            from src.agent.factory import resolve_skill_prompt_state

            prompt_state = resolve_skill_prompt_state(
                self._get_runtime_config(),
                skills=getattr(self, "_requested_skills", None),
            )
            resolved_state = {
                "skill_instructions": prompt_state.skill_instructions,
                "default_skill_policy": prompt_state.default_skill_policy,
                "use_legacy_default_prompt": bool(getattr(prompt_state, "use_legacy_default_prompt", False)),
            }
            self._resolved_prompt_state = resolved_state

        return (
            skill_instructions if skill_instructions is not None else resolved_state.get("skill_instructions", ""),
            default_skill_policy if default_skill_policy is not None else resolved_state.get("default_skill_policy", ""),
            (
                use_legacy_default_prompt
                if use_legacy_default_prompt is not None
                else bool(resolved_state.get("use_legacy_default_prompt", False))
            ),
        )

    def _get_analysis_system_prompt(self, report_language: str, stock_code: str = "") -> str:
        """Build the analyzer system prompt with output-language guidance."""
        lang = normalize_report_language(report_language)
        market_role = get_market_role(stock_code, lang)
        market_guidelines = get_market_guidelines(stock_code, lang)
        skill_instructions, default_skill_policy, use_legacy_default_prompt = self._get_skill_prompt_sections()
        value_network_schema_field = ""
        if getattr(self._get_runtime_config(), 'enable_value_network_mermaid', False):
            value_network_schema_field = (
                ',\n    "value_network_mermaid": "純 Mermaid flowchart 文字或 null；'
                "啟用時必須出現此鍵，產生規則見後方「附錄：價值網路圖」\""
            )
        # Phase 25.6：四大師視角補充 schema 欄位借用同一個模板佔位符（附加式，不改模板）
        from src.services.four_masters_commentary import build_four_masters_prompt_sections
        four_masters_schema_field, _ = build_four_masters_prompt_sections(
            getattr(self._get_runtime_config(), 'enable_four_masters_commentary', False)
        )
        value_network_schema_field += four_masters_schema_field
        if use_legacy_default_prompt:
            base_prompt = self.LEGACY_DEFAULT_SYSTEM_PROMPT.replace(
                "{market_placeholder}", market_role
            ).replace(
                "{guidelines_placeholder}", market_guidelines
            ).replace(
                "{value_network_schema_field}", value_network_schema_field
            )
        else:
            skills_section = ""
            if skill_instructions:
                skills_section = f"## 啟用的交易技能\n\n{skill_instructions}\n"
            default_skill_policy_section = ""
            if default_skill_policy:
                default_skill_policy_section = f"{default_skill_policy}\n"
            base_prompt = (
                self.SYSTEM_PROMPT.replace("{market_placeholder}", market_role)
                .replace("{guidelines_placeholder}", market_guidelines)
                .replace("{default_skill_policy_section}", default_skill_policy_section)
                .replace("{skills_section}", skills_section)
                .replace("{value_network_schema_field}", value_network_schema_field)
            )
        if lang == "en":
            return base_prompt + """

## Output Language (highest priority)

- Keep all JSON keys unchanged.
- `decision_type` must remain `buy|hold|sell`.
- All human-readable JSON values must be written in English.
- Use the common English company name when you are confident; otherwise keep the original listed company name instead of inventing one.
- This includes `stock_name`, `trend_prediction`, `operation_advice`, `confidence_level`, nested dashboard text, checklist items, and all narrative summaries.
"""
        if lang == "zh_TW":
            return base_prompt + """

## 輸出語言（最高優先順序）

- 所有 JSON 鍵名保持不變。
- `decision_type` 必須保持為 `buy|hold|sell`。
- 所有面向使用者的人類可讀文字值必須使用繁體中文。
- 這包含 `stock_name`、`trend_prediction`、`operation_advice`、`confidence_level`、巢狀 dashboard 文字、檢查清單專案，以及所有敘述摘要。
"""
        return base_prompt + """

## 輸出語言（最高優先順序）

- 所有 JSON 鍵名保持不變。
- `decision_type` 必須保持為 `buy|hold|sell`。
- 所有面向使用者的人類可讀文字值必須使用中文。
"""

    def _has_channel_config(self, config: Config) -> bool:
        """Check if multi-channel config (channels / YAML / legacy model_list) is active."""
        return bool(config.llm_model_list) and not all(
            e.get('model_name', '').startswith('__legacy_') for e in config.llm_model_list
        )

    @staticmethod
    def _legacy_router_provider_alias(model: str) -> str:
        provider = model.split("/", 1)[0] if "/" in model else "openai"
        return f"__legacy_{provider}__"

    @staticmethod
    def _build_legacy_router_model_list_from_config(
        model: str,
        model_list: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Build legacy-router candidates from configured legacy llm_model_list entries."""
        if not model:
            return []
        target_model = model
        target_legacy_alias = GeminiAnalyzer._legacy_router_provider_alias(model)
        legacy_entries: List[Dict[str, Any]] = []
        for entry in model_list or []:
            if not isinstance(entry, dict):
                continue
            model_name = str(entry.get("model_name") or "").strip()
            if model_name != target_legacy_alias:
                continue

            params = entry.get("litellm_params")
            if not isinstance(params, dict):
                continue

            api_key = str(params.get("api_key") or "").strip()
            if not api_key or len(api_key) < 8:
                continue

            deployed_params = dict(params)
            deployed_params["model"] = target_model
            deployed_params["api_key"] = api_key
            legacy_entries.append({
                "model_name": target_model,
                "litellm_params": deployed_params,
            })

        return legacy_entries

    @staticmethod
    def _is_local_api_base(base_url: Optional[str]) -> bool:
        """Return True when base_url points to a local / private-network server."""
        if not base_url:
            return False
        try:
            from urllib.parse import urlparse
            host = urlparse(base_url).hostname or ""
            return (
                host in ("localhost", "127.0.0.1", "::1")
                or host.startswith("192.168.")
                or host.startswith("10.")
                or (host.startswith("172.") and len(host.split(".")) == 4)
            )
        except Exception:
            return False

    @staticmethod
    def _probe_api_base_reachable(base_url: str, timeout: float = 2.0) -> bool:
        """Quick GET /models probe to check if a local LLM server is up."""
        try:
            import requests as _req
            url = base_url.rstrip("/") + "/models"
            resp = _req.get(url, timeout=timeout)
            return resp.status_code < 500
        except Exception:
            return False

    def _filter_reachable_model_list(
        self, model_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Remove model_list entries whose local api_base is unreachable.

        Cloud channels (no api_base or public domain) are always kept.
        Local servers (private-IP / localhost api_base) are probed once;
        if unreachable the whole group sharing that api_base is dropped and
        the system falls through to the next channel in the Router.
        """
        probed: Dict[str, bool] = {}
        reachable: List[Dict[str, Any]] = []
        skipped_bases: set = set()

        for entry in model_list:
            params = entry.get("litellm_params", {})
            api_base = params.get("api_base") or params.get("base_url") or ""
            if not self._is_local_api_base(api_base):
                reachable.append(entry)
                continue
            if api_base not in probed:
                ok = self._probe_api_base_reachable(api_base)
                probed[api_base] = ok
                if not ok:
                    skipped_bases.add(api_base)
                    logger.warning(
                        "Analyzer LLM: local server unreachable, skipping channel — %s",
                        api_base,
                    )
                else:
                    logger.info(
                        "Analyzer LLM: local server reachable — %s", api_base
                    )
            if probed[api_base]:
                reachable.append(entry)

        if skipped_bases:
            remaining = list(dict.fromkeys(
                e["litellm_params"]["model"] for e in reachable
            ))
            logger.info(
                "Analyzer LLM: after pre-check, active models: %s", remaining
            )
        return reachable

    def _init_litellm(self) -> None:
        """Initialize litellm Router from channels / YAML / legacy keys."""
        config = self._get_runtime_config()
        litellm_model = config.litellm_model
        if not litellm_model:
            logger.warning("Analyzer LLM: LITELLM_MODEL not configured")
            return

        self._litellm_available = True

        # --- Channel / YAML path: build Router from pre-built model_list ---
        if self._has_channel_config(config):
            model_list = self._filter_reachable_model_list(config.llm_model_list)
            if not model_list:
                logger.warning(
                    "Analyzer LLM: all configured channels are unreachable; "
                    "LLM analysis will be unavailable until a provider comes online"
                )
                self._litellm_available = False
                return
            # Store filtered list so router_model_names reflects only live deployments
            self._active_model_list: List[Dict[str, Any]] = model_list
            try:
                self._router = Router(
                    model_list=model_list,
                    routing_strategy="simple-shuffle",
                    num_retries=2,
                )
            except TypeError:
                logger.debug("Analyzer LLM: Router constructor signature not compatible; fallback to direct mode")
                self._router = None
            else:
                unique_models = list(dict.fromkeys(
                    e['litellm_params']['model'] for e in model_list
                ))
                logger.info(
                    f"Analyzer LLM: Router initialized from channels/YAML — "
                    f"{len(model_list)} deployment(s), models: {unique_models}"
                )
                return

        # --- Legacy path: build Router for multi-key, or use single key ---
        keys = get_api_keys_for_model(litellm_model, config)
        legacy_model_list = self._build_legacy_router_model_list_from_config(
            litellm_model,
            config.llm_model_list,
        )
        if len(legacy_model_list) <= 1 and keys:
            extra_params = extra_litellm_params(litellm_model, config)
            configured_model_list = [
                {
                    "model_name": litellm_model,
                    "litellm_params": {
                        "model": litellm_model,
                        "api_key": k,
                        **extra_params,
                    },
                }
                for k in keys
            ]
            if not legacy_model_list:
                legacy_model_list = configured_model_list
            elif len(legacy_model_list) < len(configured_model_list):
                legacy_model_list = configured_model_list

        if len(legacy_model_list) > 1:
            self._legacy_router_model_list = legacy_model_list
            try:
                self._router = Router(
                    model_list=legacy_model_list,
                    routing_strategy="simple-shuffle",
                    num_retries=2,
                )
            except TypeError:
                logger.debug("Analyzer LLM: Legacy Router constructor signature not compatible; using legacy model_list fallback")
                self._router = None
            else:
                logger.info(
                    f"Analyzer LLM: Legacy Router initialized with {len(legacy_model_list)} keys "
                    f"for {litellm_model}"
                )
                return

        if keys:
            logger.info(f"Analyzer LLM: litellm initialized (model={litellm_model})")
        else:
            logger.info(
                f"Analyzer LLM: litellm initialized (model={litellm_model}, "
                f"API key from environment)"
            )

    def is_available(self) -> bool:
        """Check if LiteLLM is properly configured with at least one API key."""
        return self._router is not None or self._litellm_available

    def _dispatch_litellm_completion(
        self,
        model: str,
        call_kwargs: Dict[str, Any],
        *,
        config: Config,
        use_channel_router: bool,
        router_model_names: set[str],
        timeout: int | None = None,
    ) -> Any:
        """Dispatch a LiteLLM completion through router or direct fallback."""
        wire_models = resolve_fallback_litellm_wire_models(model, config.llm_model_list)
        register_fallback_model_pricing(wire_models)
        effective_kwargs = dict(call_kwargs)
        if timeout is not None and timeout > 0:
            effective_kwargs["timeout"] = timeout
        if use_channel_router and self._router and model in router_model_names:
            return self._router.completion(**effective_kwargs)
        if self._router and model == config.litellm_model and not use_channel_router:
            return self._router.completion(**effective_kwargs)

        keys = get_api_keys_for_model(model, config)
        if keys:
            effective_kwargs["api_key"] = keys[0]
        effective_kwargs.update(extra_litellm_params(model, config))
        return litellm.completion(**effective_kwargs)

    def _normalize_usage(self, usage_obj: Any) -> Dict[str, Any]:
        """Normalize usage objects from LiteLLM responses/chunks."""
        if not usage_obj:
            return {}

        def _get_value(key: str) -> int:
            if isinstance(usage_obj, dict):
                return int(usage_obj.get(key) or 0)
            return int(getattr(usage_obj, key, 0) or 0)

        return {
            "prompt_tokens": _get_value("prompt_tokens"),
            "completion_tokens": _get_value("completion_tokens"),
            "total_tokens": _get_value("total_tokens"),
        }

    @staticmethod
    def _get_response_field(obj: Any, key: str) -> Any:
        """Read a field from dict-like or object-like LiteLLM payloads."""
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    def _extract_text_blocks(self, blocks: Any) -> str:
        """Extract text from OpenAI-compatible content block lists."""
        if not blocks:
            return ""

        parts: List[str] = []
        for block in blocks:
            if isinstance(block, str):
                parts.append(block)
                continue

            text = None
            if isinstance(block, dict):
                text = block.get("text")
                if text is None:
                    text = block.get("content")
            else:
                text = getattr(block, "text", None)
                if text is None:
                    text = getattr(block, "content", None)

            if isinstance(text, str) and text:
                parts.append(text)

        return "".join(parts).strip()

    def _extract_completion_text(self, response: Any) -> str:
        """Extract text from non-stream LiteLLM completion responses."""
        choices = self._get_response_field(response, "choices")
        if not choices:
            return ""

        choice = choices[0]
        message = self._get_response_field(choice, "message")

        content_blocks = self._get_response_field(choice, "content_blocks")
        if content_blocks is None and message is not None:
            content_blocks = self._get_response_field(message, "content_blocks")
        block_text = self._extract_text_blocks(content_blocks)
        if block_text:
            return block_text

        content = None
        if message is not None:
            content = self._get_response_field(message, "content")
        if content is None:
            content = self._get_response_field(choice, "content")

        if isinstance(content, list):
            return self._extract_text_blocks(content)
        if isinstance(content, str):
            return content.strip()
        return str(content).strip() if content is not None else ""

    def _extract_stream_text(self, chunk: Any) -> str:
        """Extract provider-agnostic text delta from a LiteLLM streaming chunk."""
        choices = chunk.get("choices") if isinstance(chunk, dict) else getattr(chunk, "choices", None)
        if not choices:
            return ""

        choice = choices[0]
        delta = choice.get("delta") if isinstance(choice, dict) else getattr(choice, "delta", None)
        message = choice.get("message") if isinstance(choice, dict) else getattr(choice, "message", None)

        content: Any = None
        if isinstance(delta, dict):
            content = delta.get("content")
        elif isinstance(delta, str):
            content = delta
        elif delta is not None:
            content = getattr(delta, "content", None)

        if content is None:
            if isinstance(message, dict):
                content = message.get("content")
            elif message is not None:
                content = getattr(message, "content", None)

        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)

        return content if isinstance(content, str) else ""

    def _consume_litellm_stream(
        self,
        stream_response: Any,
        *,
        model: str,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Consume a LiteLLM stream into a single text payload."""
        chunks: List[str] = []
        usage: Dict[str, Any] = {}
        chars_received = 0
        next_emit_at = 1

        try:
            for chunk in stream_response:
                chunk_usage = chunk.get("usage") if isinstance(chunk, dict) else getattr(chunk, "usage", None)
                normalized_usage = self._normalize_usage(chunk_usage)
                if normalized_usage:
                    usage = normalized_usage

                delta_text = self._extract_stream_text(chunk)
                if not delta_text:
                    continue

                chunks.append(delta_text)
                chars_received += len(delta_text)
                if progress_callback and chars_received >= next_emit_at:
                    progress_callback(chars_received)
                    next_emit_at = chars_received + 160
        except Exception as exc:
            raise _LiteLLMStreamError(
                f"{model} stream interrupted: {exc}",
                partial_received=chars_received > 0,
            ) from exc

        response_text = "".join(chunks).strip()
        if not response_text:
            raise _LiteLLMStreamError(
                f"{model} stream returned empty response",
                partial_received=False,
            )

        if progress_callback and chars_received > 0:
            progress_callback(chars_received)

        return response_text, usage

    def _call_litellm(
        self,
        prompt: str,
        generation_config: dict,
        *,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        stream_progress_callback: Optional[Callable[[int], None]] = None,
        response_validator: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Call LLM via litellm with fallback across configured models.

        When channels/YAML are configured, every model goes through the Router
        (which handles per-model key selection, load balancing, and retries).
        In legacy mode, the primary model may use the Router while fallback
        models fall back to direct litellm.completion().

        Args:
            prompt: User prompt text.
            generation_config: Dict with optional keys: temperature, max_output_tokens, max_tokens.
            response_validator: Optional callable that accepts the raw response text and raises
                an exception if the response is unacceptable (e.g. not valid JSON).  When it
                raises, the current model is treated as failed and the next fallback model is
                tried.  If all models fail validation, :class:`_AllModelsFailedError` is raised
                with ``last_response_text`` set to the last raw response received.

        Returns:
            Tuple of (response text, model_used, usage). On success model_used is the full model
            name and usage is a dict with prompt_tokens, completion_tokens, total_tokens.
        """
        config = self._get_runtime_config()
        max_tokens = (
            generation_config.get('max_output_tokens')
            or generation_config.get('max_tokens')
            or 8192
        )
        requested_temperature = generation_config.get('temperature', 0.7)
        llm_timeout = getattr(config, 'llm_provider_timeout_seconds', None)

        use_channel_router = self._has_channel_config(config)
        # Use the pre-check filtered list so router_model_names and models_to_try
        # only include models that actually have live Router deployments.
        active_list = getattr(self, "_active_model_list", None) or config.llm_model_list
        router_model_names = set(get_configured_llm_models(active_list))

        if use_channel_router and router_model_names:
            # Channel router is active: iterate only over live router models.
            models_to_try = list(dict.fromkeys(get_configured_llm_models(active_list)))
        else:
            models_to_try = [config.litellm_model] + (config.litellm_fallback_models or [])
            models_to_try = [m for m in models_to_try if m]

        last_error = None
        last_response_text: Optional[str] = None
        last_model: Optional[str] = None
        last_usage: Dict[str, Any] = {}
        effective_system_prompt = system_prompt or self.TEXT_SYSTEM_PROMPT
        for model in models_to_try:
            recovery_model_list = config.llm_model_list
            legacy_router_model_list = getattr(self, "_legacy_router_model_list", None) or []
            if legacy_router_model_list and model == config.litellm_model and not use_channel_router:
                recovery_model_list = legacy_router_model_list

            try:
                model_short = model.split("/")[-1] if "/" in model else model
                extra = get_thinking_extra_body(model_short)
                call_kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": effective_system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": max_tokens,
                }
                if extra:
                    call_kwargs["extra_body"] = extra
                uses_router = (
                    (use_channel_router and self._router and model in router_model_names)
                    or (self._router and model == config.litellm_model and not use_channel_router)
                )
                if not uses_router:
                    try:
                        keys = get_api_keys_for_model(model, config)
                    except AttributeError:
                        keys = []
                    if keys:
                        call_kwargs["api_key"] = keys[0]
                    try:
                        call_kwargs.update(extra_litellm_params(model, config))
                    except AttributeError:
                        pass
                call_kwargs = apply_litellm_generation_params(
                    call_kwargs,
                    model,
                    requested_temperature,
                    model_list=recovery_model_list,
                )

                _stream_text: Optional[str] = None
                _stream_usage: Dict[str, Any] = {}

                if stream:
                    try:
                        stream_response = call_litellm_with_param_recovery(
                            lambda kwargs: self._dispatch_litellm_completion(
                                model,
                                kwargs,
                                config=config,
                                use_channel_router=use_channel_router,
                                router_model_names=router_model_names,
                                timeout=llm_timeout,
                            ),
                            model=model,
                            call_kwargs={**call_kwargs, "stream": True},
                            model_list=recovery_model_list,
                            cache_recovery=False,
                            logger=logger,
                        )
                        _stream_text, _stream_usage = self._consume_litellm_stream(
                            stream_response,
                            model=model,
                            progress_callback=stream_progress_callback,
                        )
                    except _LiteLLMStreamError as exc:
                        if exc.partial_received:
                            logger.warning(
                                "[LiteLLM] %s stream failed after partial output, retrying non-stream for same model: %s",
                                model,
                                exc,
                            )
                        else:
                            logger.warning(
                                "[LiteLLM] %s stream unavailable before first chunk, falling back to non-stream: %s",
                                model,
                                exc,
                            )
                        last_error = exc
                    except Exception as exc:
                        logger.warning(
                            "[LiteLLM] %s stream request failed before first chunk, falling back to non-stream: %s",
                            model,
                            exc,
                        )

                if _stream_text is not None:
                    last_response_text = _stream_text
                    last_model = model
                    last_usage = _stream_usage
                    if response_validator is not None:
                        response_validator(_stream_text)
                    return _stream_text, model, _stream_usage

                response = call_litellm_with_param_recovery(
                    lambda kwargs: self._dispatch_litellm_completion(
                        model,
                        kwargs,
                        config=config,
                        use_channel_router=use_channel_router,
                        router_model_names=router_model_names,
                        timeout=llm_timeout,
                    ),
                    model=model,
                    call_kwargs=call_kwargs,
                    model_list=recovery_model_list,
                    logger=logger,
                )

                content = self._extract_completion_text(response)
                if content:
                    usage = self._normalize_usage(self._get_response_field(response, "usage"))
                    last_response_text = content
                    last_model = model
                    last_usage = usage
                    if response_validator is not None:
                        response_validator(content)
                    return (content, model, usage)
                raise ValueError("LLM returned empty response")

            except Exception as e:
                logger.warning(f"[LiteLLM] {model} failed: {e}")
                last_error = e
                continue

        raise _AllModelsFailedError(
            f"All LLM models failed (tried {len(models_to_try)} model(s)). Last error: {last_error}",
            last_response_text=last_response_text,
            last_model=last_model,
            last_usage=last_usage,
        )

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> Optional[str]:
        """Public entry point for free-form text generation.

        External callers (e.g. MarketAnalyzer) must use this method instead of
        calling _call_litellm() directly or accessing private attributes such as
        _litellm_available, _router, _model, _use_openai, or _use_anthropic.

        Args:
            prompt:      Text prompt to send to the LLM.
            max_tokens:  Maximum tokens in the response (default 2048).
            temperature: Sampling temperature (default 0.7).

        Returns:
            Response text, or None if the LLM call fails (error is logged).
        """
        try:
            result = self._call_litellm(
                prompt,
                generation_config={"max_tokens": max_tokens, "temperature": temperature},
            )
            if isinstance(result, tuple):
                text, model_used, usage = result
                persist_llm_usage(usage, model_used, call_type="market_review")
                return text
            return result
        except Exception as exc:
            logger.error("[generate_text] LLM call failed: %s", exc)
            return None

    def analyze(
        self, 
        context: Dict[str, Any],
        news_context: Optional[str] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        stream_progress_callback: Optional[Callable[[int], None]] = None,
        analysis_context_pack_summary: Optional[str] = None,
    ) -> AnalysisResult:
        """
        分析單隻股票
        
        流程：
        1. 格式化輸入資料（技術面 + 新聞）
        2. 呼叫 Gemini API（帶重試和模型切換）
        3. 解析 JSON 響應
        4. 返回結構化結果
        
        Args:
            context: 從 storage.get_analysis_context() 獲取的上下文資料
            news_context: 預先搜尋的新聞內容（可選）
            
        Returns:
            AnalysisResult 物件
        """
        def _emit_progress(progress: int, message: str) -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(progress, message)
            except Exception as exc:
                logger.debug("[analyzer] progress callback skipped: %s", exc)

        code = context.get('code', 'Unknown')
        config = self._get_runtime_config()
        report_language = normalize_report_language(getattr(config, "report_language", "zh"))
        system_prompt = self._get_analysis_system_prompt(report_language, stock_code=code)
        
        # 請求前增加延時（防止連續請求觸發限流）
        request_delay = config.gemini_request_delay
        if request_delay > 0:
            logger.debug(f"[LLM] 請求前等待 {request_delay:.1f} 秒...")
            _emit_progress(65, f"{code}：LLM 請求前等待 {request_delay:.1f} 秒")
            time.sleep(request_delay)
        
        # 優先從上下文獲取股票名稱（由 main.py 傳入）
        name = context.get('stock_name')
        if not name or name.startswith('股票'):
            # 備選：從 realtime 中獲取
            if 'realtime' in context and context['realtime'].get('name'):
                name = context['realtime']['name']
            else:
                # 最後從對映表獲取
                name = STOCK_NAME_MAP.get(code, f'股票{code}')
        
        # 如果模型不可用，返回預設結果
        if not self.is_available():
            return AnalysisResult(
                code=code,
                name=name,
                sentiment_score=50,
                trend_prediction='Sideways' if report_language == "en" else '震盪',
                operation_advice='Hold' if report_language == "en" else '持有',
                confidence_level='Low' if report_language == "en" else '低',
                analysis_summary='AI analysis is unavailable because no API key is configured.' if report_language == "en" else 'AI 分析功能未啟用（未配置 API Key）',
                risk_warning='Configure an LLM API key (GEMINI_API_KEY/ANTHROPIC_API_KEY/OPENAI_API_KEY) and retry.' if report_language == "en" else '請配置 LLM API Key（GEMINI_API_KEY/ANTHROPIC_API_KEY/OPENAI_API_KEY）後重試',
                success=False,
                error_message='LLM API key is not configured' if report_language == "en" else 'LLM API Key 未配置',
                model_used=None,
                report_language=report_language,
            )
        
        try:
            # 格式化輸入（包含技術面資料和新聞）
            prompt = self._format_prompt(
                context,
                name,
                news_context,
                report_language=report_language,
                analysis_context_pack_summary=analysis_context_pack_summary,
            )
            
            config = self._get_runtime_config()
            # Show active channel models when channel router is in use; fall back to litellm_model.
            _active = getattr(self, "_active_model_list", None)
            if _active and self._has_channel_config(config):
                from src.config import get_configured_llm_models as _gcm  # noqa: PLC0415
                model_name = ",".join(_gcm(_active)) or config.litellm_model or "unknown"
            else:
                model_name = config.litellm_model or "unknown"
            logger.info(f"========== AI 分析 {name}({code}) ==========")
            logger.info(f"[LLM配置] 模型: {model_name}")
            logger.info(f"[LLM配置] Prompt 長度: {len(prompt)} 字元")
            logger.info(f"[LLM配置] 是否包含新聞: {'是' if news_context else '否'}")

            # 記錄完整 prompt 到日誌（INFO級別記錄摘要，DEBUG記錄完整）
            prompt_preview = prompt[:500] + "..." if len(prompt) > 500 else prompt
            logger.info(f"[LLM Prompt 預覽]\n{prompt_preview}")
            logger.debug(f"=== 完整 Prompt ({len(prompt)}字元) ===\n{prompt}\n=== End Prompt ===")

            # 設定生成配置
            generation_config = {
                "temperature": config.llm_temperature,
                "max_output_tokens": 8192,
            }

            logger.info(f"[LLM呼叫] 開始呼叫 {model_name}...")
            _emit_progress(68, f"{name}：LLM 已接收請求，等待響應")

            # 使用 litellm 呼叫（支援完整性校驗重試）
            current_prompt = prompt
            retry_count = 0
            max_retries = config.report_integrity_retry if config.report_integrity_enabled else 0

            while True:
                start_time = time.time()
                try:
                    response_text, model_used, llm_usage = self._call_litellm(
                        current_prompt,
                        generation_config,
                        system_prompt=system_prompt,
                        stream=True,
                        stream_progress_callback=stream_progress_callback,
                        response_validator=self._validate_json_response,
                    )
                except _AllModelsFailedError as exc:
                    if exc.last_response_text is not None:
                        logger.warning(
                            "[LLM JSON] %s(%s): all models returned invalid JSON, using text fallback",
                            name,
                            code,
                        )
                        response_text = exc.last_response_text
                        model_used = exc.last_model
                        llm_usage = exc.last_usage
                    else:
                        raise
                elapsed = time.time() - start_time

                # 記錄響應資訊
                logger.info(
                    f"[LLM返回] {model_name} 響應成功, 耗時 {elapsed:.2f}s, 響應長度 {len(response_text)} 字元"
                )
                response_preview = response_text[:300] + "..." if len(response_text) > 300 else response_text
                logger.info(f"[LLM返回 預覽]\n{response_preview}")
                logger.debug(
                    f"=== {model_name} 完整響應 ({len(response_text)}字元) ===\n{response_text}\n=== End Response ==="
                )
                # Keep parser/retry progress monotonic so task progress/message never "goes backward".
                parse_progress = min(99, 93 + retry_count * 2)
                _emit_progress(parse_progress, f"{name}：LLM 返回完成，正在解析 JSON")

                # 解析響應
                result = self._parse_response(response_text, code, name)
                result.raw_response = response_text
                result.search_performed = bool(news_context)
                result.market_snapshot = self._build_market_snapshot(context)
                result.model_used = model_used
                result.report_language = report_language
                normalize_chip_structure_availability(result, context.get("chip"))

                # 內容完整性校驗（可選）
                if not config.report_integrity_enabled:
                    break
                require_phase_decision = isinstance(context.get("market_phase_context"), dict)
                pass_integrity, missing_fields = self._check_content_integrity(
                    result,
                    require_phase_decision=require_phase_decision,
                )
                if pass_integrity:
                    break
                if retry_count < max_retries:
                    current_prompt = self._build_integrity_retry_prompt(
                        prompt,
                        response_text,
                        missing_fields,
                        report_language=report_language,
                    )
                    retry_count += 1
                    logger.info(
                        "[LLM完整性] 必填欄位缺失 %s，第 %d 次補全重試",
                        missing_fields,
                        retry_count,
                    )
                    retry_progress = min(99, 92 + retry_count * 2)
                    _emit_progress(
                        retry_progress,
                        f"{name}：報告欄位不完整，正在補全重試（{retry_count}/{max_retries}）",
                    )
                else:
                    self._apply_placeholder_fill(result, missing_fields)
                    logger.warning(
                        "[LLM完整性] 必填欄位缺失 %s，已佔位補全，不阻塞流程",
                        missing_fields,
                    )
                    break

            persist_llm_usage(llm_usage, model_used, call_type="analysis", stock_code=code)

            logger.info(f"[LLM解析] {name}({code}) 分析完成: {result.trend_prediction}, 評分 {result.sentiment_score}")

            return result
            
        except Exception as e:
            logger.error(f"AI 分析 {name}({code}) 失敗: {e}")
            return AnalysisResult(
                code=code,
                name=name,
                sentiment_score=50,
                trend_prediction='Sideways' if report_language == "en" else '震盪',
                operation_advice='Hold' if report_language == "en" else '持有',
                confidence_level='Low' if report_language == "en" else '低',
                analysis_summary=(f'Analysis failed: {str(e)[:100]}' if report_language == "en" else f'分析過程出錯: {str(e)[:100]}'),
                risk_warning='Analysis failed. Please retry later or review manually.' if report_language == "en" else '分析失敗，請稍後重試或手動分析',
                success=False,
                error_message=str(e),
                model_used=None,
                report_language=report_language,
            )
    
    def _format_prompt(
        self, 
        context: Dict[str, Any], 
        name: str,
        news_context: Optional[str] = None,
        report_language: str = "zh",
        analysis_context_pack_summary: Optional[str] = None,
    ) -> str:
        """
        格式化分析提示詞（決策儀表盤 v2.0）
        
        包含：技術指標、實時行情（量比/換手率）、籌碼分佈、趨勢分析、新聞
        
        Args:
            context: 技術面資料上下文（包含增強資料）
            name: 股票名稱（預設值，可能被上下文覆蓋）
            news_context: 預先搜尋的新聞內容
        """
        code = context.get('code', 'Unknown')
        report_language = normalize_report_language(report_language)
        _, _, use_legacy_default_prompt = self._get_skill_prompt_sections()
        
        # 優先使用上下文中的股票名稱（從 realtime_quote 獲取）
        stock_name = context.get('stock_name', name)
        if not stock_name or stock_name == f'股票{code}':
            stock_name = STOCK_NAME_MAP.get(code, f'股票{code}')
            
        today = context.get('today', {})
        unknown_text = get_unknown_text(report_language)
        no_data_text = get_no_data_text(report_language)
        quote_section_title, close_price_label = _phase_aware_quote_labels(context)
        hide_regular_session_ohlc = _should_hide_regular_session_ohlc(context)
        realtime_overlay_quote = hide_regular_session_ohlc and _today_has_realtime_overlay(today)
        pct_chg_label = "實時漲跌幅" if realtime_overlay_quote else "漲跌幅"
        volume_label = "實時成交量" if realtime_overlay_quote else "成交量"
        amount_label = "實時成交額" if realtime_overlay_quote else "成交額"
        quote_rows = [
            f"| {close_price_label} | {today.get('close', 'N/A')} 元 |",
        ]
        if not hide_regular_session_ohlc:
            quote_rows.extend(
                [
                    f"| 開盤價 | {today.get('open', 'N/A')} 元 |",
                    f"| 最高價 | {today.get('high', 'N/A')} 元 |",
                    f"| 最低價 | {today.get('low', 'N/A')} 元 |",
                ]
            )
        quote_rows.extend(
            [
                f"| {pct_chg_label} | {today.get('pct_chg', 'N/A')}% |",
                f"| {volume_label} | {self._format_volume(today.get('volume'))} |",
                f"| {amount_label} | {self._format_amount(today.get('amount'))} |",
            ]
        )
        quote_rows_text = "\n".join(quote_rows)
        
        # ========== 構建決策儀表盤格式的輸入 ==========
        prompt = f"""# 決策儀表盤分析請求

## 📊 股票基礎資訊
| 專案 | 資料 |
|------|------|
| 股票程式碼 | **{code}** |
| 股票名稱 | **{stock_name}** |
| 分析日期 | {context.get('date', unknown_text)} |

---
"""
        prompt += format_market_phase_prompt_section(
            context.get("market_phase_context"),
            report_language=report_language,
        )
        if isinstance(analysis_context_pack_summary, str) and analysis_context_pack_summary:
            prompt += analysis_context_pack_summary
        prompt += f"""

## 📈 技術面資料

### {quote_section_title}
| 指標 | 數值 |
|------|------|
{quote_rows_text}

### 均線系統（關鍵判斷指標）
| 均線 | 數值 | 說明 |
|------|------|------|
| MA5 | {today.get('ma5', 'N/A')} | 短期趨勢線 |
| MA10 | {today.get('ma10', 'N/A')} | 中短期趨勢線 |
| MA20 | {today.get('ma20', 'N/A')} | 中期趨勢線 |
| 均線形態 | {context.get('ma_status', unknown_text)} | 多頭/空頭/纏繞 |
"""
        
        # 新增實時行情資料（量比、換手率等）
        if 'realtime' in context:
            rt = context['realtime']
            prompt += f"""
### 實時行情增強資料
| 指標 | 數值 | 解讀 |
|------|------|------|
| 當前價格 | {rt.get('price', 'N/A')} 元 | |
| **量比** | **{rt.get('volume_ratio', 'N/A')}** | {rt.get('volume_ratio_desc', '')} |
| **換手率** | **{rt.get('turnover_rate', 'N/A')}%** | |
| 市盈率(動態) | {rt.get('pe_ratio', 'N/A')} | |
| 市淨率 | {rt.get('pb_ratio', 'N/A')} | |
| 總市值 | {self._format_amount(rt.get('total_mv'))} | |
| 流通市值 | {self._format_amount(rt.get('circ_mv'))} | |
| 60日漲跌幅 | {rt.get('change_60d', 'N/A')}% | 中期表現 |
"""

        # 新增財報與分紅（價值投資口徑）
        fundamental_context = context.get("fundamental_context") if isinstance(context, dict) else None
        earnings_block = (
            fundamental_context.get("earnings", {})
            if isinstance(fundamental_context, dict)
            else {}
        )
        earnings_data = (
            earnings_block.get("data", {})
            if isinstance(earnings_block, dict)
            else {}
        )
        financial_report = (
            earnings_data.get("financial_report", {})
            if isinstance(earnings_data, dict)
            else {}
        )
        dividend_metrics = (
            earnings_data.get("dividend", {})
            if isinstance(earnings_data, dict)
            else {}
        )
        if isinstance(financial_report, dict) or isinstance(dividend_metrics, dict):
            financial_report = financial_report if isinstance(financial_report, dict) else {}
            dividend_metrics = dividend_metrics if isinstance(dividend_metrics, dict) else {}
            ttm_yield = dividend_metrics.get("ttm_dividend_yield_pct", "N/A")
            ttm_cash = dividend_metrics.get("ttm_cash_dividend_per_share", "N/A")
            ttm_count = dividend_metrics.get("ttm_event_count", "N/A")
            report_date = financial_report.get("report_date", "N/A")
            prompt += f"""
### 財報與分紅（價值投資口徑）
| 指標 | 數值 | 說明 |
|------|------|------|
| 最近報告期 | {report_date} | 來自結構化財報欄位 |
| 營業收入 | {financial_report.get('revenue', 'N/A')} | |
| 歸母淨利潤 | {financial_report.get('net_profit_parent', 'N/A')} | |
| 經營現金流 | {financial_report.get('operating_cash_flow', 'N/A')} | |
| ROE | {financial_report.get('roe', 'N/A')} | |
| 近12個月每股現金分紅 | {ttm_cash} | 僅現金分紅、稅前口徑 |
| TTM 股息率 | {ttm_yield} | 公式：近12個月每股現金分紅 / 當前價格 × 100% |
| TTM 分紅事件數 | {ttm_count} | |

> 若上述欄位為 N/A 或缺失，請明確寫“資料缺失，無法判斷”，禁止編造。
"""

        capital_flow_block = (
            fundamental_context.get("capital_flow", {})
            if isinstance(fundamental_context, dict)
            else {}
        )
        capital_flow_data = (
            capital_flow_block.get("data", {})
            if isinstance(capital_flow_block, dict)
            else {}
        )
        stock_flow = (
            capital_flow_data.get("stock_flow", {})
            if isinstance(capital_flow_data, dict)
            else {}
        )
        sector_flow = (
            capital_flow_data.get("sector_rankings", {})
            if isinstance(capital_flow_data, dict)
            else {}
        )
        has_capital_flow = (
            isinstance(stock_flow, dict)
            and any(v is not None for v in stock_flow.values())
        ) or (
            isinstance(sector_flow, dict)
            and (sector_flow.get("top") or sector_flow.get("bottom"))
        )
        if has_capital_flow:
            top_sectors = sector_flow.get("top", []) if isinstance(sector_flow, dict) else []
            bottom_sectors = sector_flow.get("bottom", []) if isinstance(sector_flow, dict) else []
            top_sector_text = "、".join(
                str(item.get("name", "")).strip()
                for item in top_sectors[:3]
                if isinstance(item, dict) and str(item.get("name", "")).strip()
            ) or "N/A"
            bottom_sector_text = "、".join(
                str(item.get("name", "")).strip()
                for item in bottom_sectors[:3]
                if isinstance(item, dict) and str(item.get("name", "")).strip()
            ) or "N/A"
            prompt += f"""
### 主力資金流向（操作建議過濾器）
| 指標 | 數值 | 決策含義 |
|------|------|----------|
| 主力淨流入 | {stock_flow.get('main_net_inflow', 'N/A')} | 正值偏支援，負值偏壓制 |
| 5日淨流入 | {stock_flow.get('inflow_5d', 'N/A')} | 用於判斷資金持續性 |
| 10日淨流入 | {stock_flow.get('inflow_10d', 'N/A')} | 用於判斷資金持續性 |
| 資金流入靠前板塊 | {top_sector_text} | 板塊資金共振參考 |
| 資金流出靠前板塊 | {bottom_sector_text} | 板塊風險參考 |

> 資金流向只能作為價格位置的過濾器：接近壓力且主力流出時不得追買；接近支撐且未放量跌破時，優先判斷為持有觀察、震盪或洗盤觀察。
"""

        # 新增籌碼分佈資料
        if 'chip' in context:
            chip = context['chip']
            profit_ratio = chip.get('profit_ratio', 0)
            prompt += f"""
### 籌碼分佈資料（效率指標）
| 指標 | 數值 | 健康標準 |
|------|------|----------|
| **獲利比例** | **{profit_ratio:.1%}** | 70-90%時警惕 |
| 平均成本 | {chip.get('avg_cost', 'N/A')} 元 | 現價應高於5-15% |
| 90%籌碼集中度 | {chip.get('concentration_90', 0):.2%} | <15%為集中 |
| 70%籌碼集中度 | {chip.get('concentration_70', 0):.2%} | |
| 籌碼狀態 | {chip.get('chip_status', unknown_text)} | |
"""
        else:
            chip_unavailable_text = get_chip_unavailable_text(report_language)
            chip_instruction = (
                "Do not fabricate profit ratio, average cost, or concentration. Mention chip data "
                "unavailability only once in the report; do not repeat per-field no-data text in `chip_structure`."
                if report_language == "en"
                else "請勿編造獲利比例、平均成本或集中度；報告中只說明一次籌碼資料不可用，不要把“資料缺失，無法判斷”逐欄位重複寫入 `chip_structure`。"
            )
            prompt += f"""
### 籌碼分佈資料（效率指標）
> {chip_unavailable_text}
> {chip_instruction}
"""
        
        # 新增趨勢分析結果（僅隱式內建 bull_trend 預設回退保留舊口徑）
        if 'trend_analysis' in context:
            trend = _sanitize_trend_analysis_for_prompt(
                context['trend_analysis'],
                volume_change_ratio=context.get('volume_change_ratio'),
            )
            consistency_notes = trend.get('prompt_consistency_notes', [])
            if use_legacy_default_prompt:
                bias_warning = "🚨 超過5%，嚴禁追高！" if trend.get('bias_ma5', 0) > 5 else "✅ 安全範圍"
                prompt += f"""
### 趨勢分析預判（基於交易理念）
| 指標 | 數值 | 判定 |
|------|------|------|
| 趨勢狀態 | {trend.get('trend_status', unknown_text)} | |
| 均線排列 | {trend.get('ma_alignment', unknown_text)} | MA5>MA10>MA20為多頭 |
| 趨勢強度 | {trend.get('trend_strength', 0)}/100 | |
| **乖離率(MA5)** | **{trend.get('bias_ma5', 0):+.2f}%** | {bias_warning} |
| 乖離率(MA10) | {trend.get('bias_ma10', 0):+.2f}% | |
| 量能狀態 | {trend.get('volume_status', unknown_text)} | {trend.get('volume_trend', '')} |
| 系統訊號 | {trend.get('buy_signal', unknown_text)} | |
| 系統評分 | {trend.get('signal_score', 0)}/100 | |

#### 系統分析理由
**買進理由**：
{chr(10).join('- ' + r for r in trend.get('signal_reasons', ['無'])) if trend.get('signal_reasons') else '- 無'}

**風險因素**：
{chr(10).join('- ' + r for r in trend.get('risk_factors', ['無'])) if trend.get('risk_factors') else '- 無'}
"""
                if consistency_notes:
                    prompt += f"""

**一致性約束**：
{chr(10).join('- ' + note for note in consistency_notes)}
"""
            else:
                bias_warning = (
                    "🚨 偏離較大，需謹慎評估追高風險"
                    if trend.get('bias_ma5', 0) > 5
                    else "✅ 位置相對可控"
                )
                prompt += f"""
### 技術與結構分析（供啟用技能判斷參考）
| 指標 | 數值 | 說明 |
|------|------|------|
| 趨勢狀態 | {trend.get('trend_status', unknown_text)} | |
| 均線排列 | {trend.get('ma_alignment', unknown_text)} | 結合啟用技能判斷結構強弱 |
| 趨勢強度 | {trend.get('trend_strength', 0)}/100 | |
| **價格位置(MA5)** | **{trend.get('bias_ma5', 0):+.2f}%** | {bias_warning} |
| 價格位置(MA10) | {trend.get('bias_ma10', 0):+.2f}% | |
| 量能狀態 | {trend.get('volume_status', unknown_text)} | {trend.get('volume_trend', '')} |
| 系統訊號 | {trend.get('buy_signal', unknown_text)} | |
| 系統評分 | {trend.get('signal_score', 0)}/100 | |

#### 系統分析理由
**支援因素**：
{chr(10).join('- ' + r for r in trend.get('signal_reasons', ['無'])) if trend.get('signal_reasons') else '- 無'}

**風險因素**：
{chr(10).join('- ' + r for r in trend.get('risk_factors', ['無'])) if trend.get('risk_factors') else '- 無'}
"""
                if consistency_notes:
                    prompt += f"""

**一致性約束**：
{chr(10).join('- ' + note for note in consistency_notes)}
"""
        
        # 新增昨日對比資料
        if 'yesterday' in context:
            volume_change = context.get('volume_change_ratio', 'N/A')
            prompt += f"""
### 量價變化
- 成交量較昨日變化：{volume_change}倍
- 價格較昨日變化：{context.get('price_change_ratio', 'N/A')}%
"""
            parsed_volume_change = _safe_float(volume_change, default=math.nan)
            if math.isfinite(parsed_volume_change) and parsed_volume_change > 10:
                prompt += """
- ⚠️ 量能異常提示：成交量較昨日放大超過10倍，可能受異常資料或一次性衝量影響，必須降權解讀，不能機械視為強確認訊號
"""
        
        # 新增新聞搜尋結果（重點區域）
        news_window_days: Optional[int] = None
        context_window = context.get("news_window_days")
        try:
            if context_window is not None:
                parsed_window = int(context_window)
                if parsed_window > 0:
                    news_window_days = parsed_window
        except (TypeError, ValueError):
            news_window_days = None

        if news_window_days is None:
            prompt_config = self._get_runtime_config()
            news_window_days = resolve_news_window_days(
                news_max_age_days=getattr(prompt_config, "news_max_age_days", 3),
                news_strategy_profile=getattr(prompt_config, "news_strategy_profile", "short"),
            )
        prompt += """
---

## 📰 輿情情報
"""
        if news_context:
            prompt += f"""
以下是 **{stock_name}({code})** 近{news_window_days}日的新聞搜尋結果，請重點提取：
1. 🚨 **風險警報**：減持、處罰、利空
2. 🎯 **利好催化**：業績、合同、政策
3. 📊 **業績預期**：年報預告、業績快報
4. 🕒 **時間規則（強制）**：
   - 輸出到 `risk_alerts` / `positive_catalysts` / `latest_news` 的每一條都必須帶具體日期（YYYY-MM-DD）
   - 超出近{news_window_days}日視窗的新聞一律忽略
   - 時間未知、無法確定釋出日期的新聞一律忽略

```
{news_context}
```
"""
        else:
            prompt += """
未搜尋到該股票近期的相關新聞。請主要依據技術面資料進行分析。
"""

        # 注入缺失資料警告
        if context.get('data_missing'):
            prompt += """
⚠️ **資料缺失警告**
由於介面限制，當前無法獲取完整的實時行情和技術指標資料。
請 **忽略上述表格中的 N/A 資料**，重點依據 **【📰 輿情情報】** 中的新聞進行基本面和情緒面分析。
在回答技術面問題（如均線、乖離率）時，請直接說明“資料缺失，無法判斷”，**嚴禁編造資料**。
"""

        # 明確的輸出要求
        prompt += f"""
---

## ✅ 分析任務

請為 **{stock_name}({code})** 生成【決策儀表盤】，嚴格按照 JSON 格式輸出。
"""
        if context.get('is_index_etf'):
            prompt += """
> ⚠️ **指數/ETF 分析約束**：該標的為指數跟蹤型 ETF 或市場指數。
> - 風險分析僅關注：**指數走勢、跟蹤誤差、市場流動性**
> - 嚴禁將基金公司的訴訟、聲譽、高管變動納入風險警報
> - 業績預期基於**指數成分股整體表現**，而非基金公司財報
> - `risk_alerts` 中不得出現基金管理人相關的公司經營風險

"""
        if getattr(self._get_runtime_config(), 'enable_value_network_mermaid', False):
            etf_semantic_hint = (
                "- ETF 語意對應：`供應商`=主要成分股/持股權重，`客戶`=申購資金來源（機構/散戶/政策驅動），"
                "`競爭者`=同類型 ETF 或可替代的個股直接投資，`互補者`=產業趨勢/政策/上游需求題材。\n"
                if context.get('is_index_etf')
                else ""
            )
            prompt += f"""
### 附錄：價值網路圖（啟用時必須輸出此欄位，dagre 排版受限的 4 分類 A4 卡片版型）
請在最上層 JSON 額外輸出 `value_network_mermaid` 欄位（字串或 null）。此功能已啟用，**該鍵必須出現在 JSON 中**，即使值為 null。
- 對於有公開商業身份的已知標的（如知名上市公司、ETF），通常應能產出至少類別層級的精簡價值網路圖，即使沒有精確供應商/客戶證據，也不要因此直接省略圖表。
- 若無法取得精確的具名供應商/客戶/競爭者，請改用產業類別層級節點，不要編造具體公司名稱。
- 只有在該標的業務身份本身嚴重不明確（例如資料嚴重缺失、無法判斷所屬產業）時，才將 `value_network_mermaid` 設為 null。
{etf_semantic_hint}- **結構固定為「一個中心節點 + 剛好 4 個分類方框」**：標的本身只能是一個中心節點，不要額外建立「公司核心業務」或「護城河」之類的獨立 subgraph；護城河/收購/風險等戰略資訊請併入最接近語意的既有分類卡片內（例如寫進該卡片的第二行）。
- 分類方框固定使用這四個（subgraph id 固定用 `S`/`K`/`R`/`P`）：`供應商 Suppliers`(S)、`客戶 Customers`(K)、`競爭者 Competitors`(R)、`互補者 Complementors`(P)。
- 每個分類方框固定 3 張卡片（id 例如 `S1`/`S2`/`S3`），總可視節點數（含中心節點）固定為 13 個；若戰略卡必須併入導致某分類需要第 4 張卡，上限放寬到每分類最多 4 張、總數最多 17 個，不要超過。
- 同類項請合併成一個節點（例如「AWS / Google Cloud」合併成一個節點），不要每家公司都拆成獨立節點。
- **第一行必須是 `flowchart TB`，不要輸出 `%%{{init...}}%%` 這類樣式指令**（樣式由系統固定附加，不需要也不可以由你輸出）。
- **每個分類方框內，三張卡片之間必須用隱形連結 `~~~` 串成一條鏈**（例如 `S1 ~~~ S2`、`S2 ~~~ S3`），這是讓圖表呈直向堆疊、不被排成寬扁長條的必要寫法，務必每個分類都要寫。
- **代表性連線的接法固定**：`供應商`、`客戶` 在中心節點上方，代表邊**從各分類最後一張卡接到中心**（例如 3 張卡時是 `S3 --> C`、`K3 --> C`）；`競爭者`、`互補者` 在中心節點下方，代表邊**從中心接到各分類第一張卡**（例如 `C --> R1`、`C --> P1`）。不可接到第一張卡了事，也不可每張卡都接中心。
- 可視連線數量建議在 4-8 條以內（4 個分類各 1 條代表邊接中心即可）；分類內的 `~~~` 隱形鏈不算入可見連線數量，但仍必須輸出。
- 卡片標籤固定格式為「公司名 (代碼)<br/>角色關係」，最多 2 行，必要時 3 行：
  - 美股代碼一律加 `.US` 後綴（例如 `NVIDIA (NVDA.US)`、`Amazon (AMZN.US)`），對齊台股慣例。
  - 台股代碼一律加 `.TW` 後綴（例如 `TSMC (2330.TW)`、`MediaTek (2454.TW)`）。
  - 韓股使用純數字代碼，不加後綴（例如 `Samsung (005930)`）。
  - 不確定代碼是否正確時整個代碼省略（連括號都不寫），不可瞎猜代碼或猜錯市場後綴；非上市/抽象節點（產業類別、政策題材、資金來源）本來就不需要代碼。
- **節點與 subgraph 標籤一律使用雙引號包住**（例如 `C["Microsoft (MSFT.US)<br/>雲端/AI"]`、`subgraph S["供應商 Suppliers"]`），不可省略雙引號：標籤內只要含有括號（例如代碼的 `(NVDA.US)`），不加雙引號會讓 Mermaid 解析直接失敗、整張圖無法渲染。
- 節點 ID 與 subgraph ID 都必須是安全的 ASCII 識別碼（例如 `C`、`S1`、`K1`、`R1`、`P1`），不可使用中文作為 ID，也不可使用以數字開頭的 ID（例如不可用 `5G_SoC`）；中文或專有名稱只能放在節點標籤（`[...]` 內）。
- 內容為**純 Mermaid flowchart 原始文字**，只能使用 `flowchart TB`（不要使用 `flowchart LR`）。
- 仍要輸出 `classDef`/`class` 樣式指派行（例如 `classDef card ...`、`classDef center ...`、`class S1,S2,S3 card`、`class C center`）。
- 不要包含 ``` 圍欄、HTML（`<br/>` 除外）或任何其他文字說明，只放 Mermaid 原始語法本身，也不可包含裸網址。
- 用語不得超出本報告主結論的強度（禁止「必買」「保證上漲」「穩賺」等用語）。
"""
        if getattr(self._get_runtime_config(), 'enable_four_masters_commentary', False):
            from src.services.four_masters_commentary import build_four_masters_prompt_sections
            _, four_masters_instruction_section = build_four_masters_prompt_sections(True)
            prompt += four_masters_instruction_section

        prompt += f"""
### ⚠️ 重要：輸出正確的股票名稱格式
正確的股票名稱格式為“股票名稱（股票程式碼）”，例如“貴州茅臺（600519）”。
如果上方顯示的股票名稱為"股票{code}"或不正確，請在分析開頭**明確輸出該股票的正確中文全稱**。
"""
        if use_legacy_default_prompt:
            prompt += f"""

### 重點關注（必須明確回答）：
1. ❓ 是否滿足 MA5>MA10>MA20 多頭排列？
2. ❓ 當前乖離率是否在安全範圍內（<5%）？—— 超過5%必須標註"嚴禁追高"
3. ❓ 量能是否配合（縮量回撥/放量突破）？
4. ❓ 籌碼結構是否健康？
5. ❓ 訊息面有無重大利空？（減持、處罰、業績變臉等）
"""
        else:
            prompt += f"""

### 重點關注（必須明確回答）：
1. ❓ 當前結構是否滿足啟用技能的關鍵觸發條件？
2. ❓ 當前入場位置與風險回報是否合理？若偏離過大，請明確說明等待條件
3. ❓ 量能、波動與籌碼結構是否支援當前結論？
4. ❓ 訊息面有無重大利空或與技能結論衝突的資訊？
5. ❓ 若結論成立，具體觸發條件、止損位、觀察點分別是什麼？
"""
        prompt += f"""

### 決策儀表盤要求：
- **股票名稱**：必須輸出正確的中文全稱（如"貴州茅臺"而非"股票600519"）
- **核心結論**：一句話說清該買/該賣/該等
- **持股分類建議**：空倉者怎麼做 vs 持股者怎麼做
- **具體狙擊點位**：買進價、止損價、目標價（精確到分）
- **檢查清單**：每項用 ✅/⚠️/❌ 標記
- **訊息面時間合規**：`latest_news`、`risk_alerts`、`positive_catalysts` 不得包含超出近{news_window_days}日或時間未知的資訊
- **技術面一致性**：嚴禁把“空頭排列”和“多頭排列”等互斥結論同時當作有效依據；若基本面/事件面與技術面衝突，必須明確寫“事件先行、技術待確認”或“基本面偏多，但技術面尚未確認”
 
請輸出完整的 JSON 格式決策儀表盤。"""

        if report_language == "en":
            prompt += """

### Output language requirements (highest priority)
- Keep every JSON key exactly as defined above; do not translate keys.
- `decision_type` must remain `buy`, `hold`, or `sell`.
- All human-readable JSON values must be in English.
- This includes `stock_name`, `trend_prediction`, `operation_advice`, `confidence_level`, all nested dashboard text, checklist items, and every summary field.
- Use the common English company name when you are confident. If not, keep the listed company name rather than inventing one.
- When data is missing, explain it in English instead of Chinese.
"""
        else:
            prompt += f"""

### 輸出語言要求（最高優先順序）
- 所有 JSON 鍵名必須保持不變，不要翻譯鍵名。
- `decision_type` 必須保持為 `buy`、`hold`、`sell`。
- 所有面向使用者的人類可讀文字值必須使用中文。
- 當資料缺失時，請使用中文直接說明“{no_data_text}，無法判斷”。
"""
        
        return prompt
    
    def _format_volume(self, volume: Optional[float]) -> str:
        """格式化成交量顯示"""
        if volume is None:
            return 'N/A'
        if volume >= 1e8:
            return f"{volume / 1e8:.2f} 億股"
        elif volume >= 1e4:
            return f"{volume / 1e4:.2f} 萬股"
        else:
            return f"{volume:.0f} 股"
    
    def _format_amount(self, amount: Optional[float]) -> str:
        """格式化成交額顯示"""
        if amount is None:
            return 'N/A'
        if amount >= 1e8:
            return f"{amount / 1e8:.2f} 億元"
        elif amount >= 1e4:
            return f"{amount / 1e4:.2f} 萬元"
        else:
            return f"{amount:.0f} 元"

    def _format_percent(self, value: Optional[float]) -> str:
        """格式化百分比顯示"""
        if value is None:
            return 'N/A'
        try:
            return f"{float(value):.2f}%"
        except (TypeError, ValueError):
            return 'N/A'

    def _format_price(self, value: Optional[float]) -> str:
        """格式化價格顯示"""
        if value is None:
            return 'N/A'
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return 'N/A'

    def _build_market_snapshot(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """構建當日行情快照（展示用）"""
        today = context.get('today', {}) or {}
        realtime = context.get('realtime', {}) or {}
        yesterday = context.get('yesterday', {}) or {}

        prev_close = yesterday.get('close')
        close = today.get('close')
        high = today.get('high')
        low = today.get('low')

        amplitude = None
        change_amount = None
        if prev_close not in (None, 0) and high is not None and low is not None:
            try:
                amplitude = (float(high) - float(low)) / float(prev_close) * 100
            except (TypeError, ValueError, ZeroDivisionError):
                amplitude = None
        if prev_close is not None and close is not None:
            try:
                change_amount = float(close) - float(prev_close)
            except (TypeError, ValueError):
                change_amount = None

        snapshot = {
            "date": context.get('date', '未知'),
            "close": self._format_price(close),
            "open": self._format_price(today.get('open')),
            "high": self._format_price(high),
            "low": self._format_price(low),
            "prev_close": self._format_price(prev_close),
            "pct_chg": self._format_percent(today.get('pct_chg')),
            "change_amount": self._format_price(change_amount),
            "amplitude": self._format_percent(amplitude),
            "volume": self._format_volume(today.get('volume')),
            "amount": self._format_amount(today.get('amount')),
        }

        if realtime:
            snapshot.update({
                "price": self._format_price(realtime.get('price')),
                "volume_ratio": realtime.get('volume_ratio', 'N/A'),
                "turnover_rate": self._format_percent(realtime.get('turnover_rate')),
                "source": getattr(realtime.get('source'), 'value', realtime.get('source', 'N/A')),
            })

        return snapshot

    def _check_content_integrity(
        self,
        result: AnalysisResult,
        *,
        require_phase_decision: bool = False,
    ) -> Tuple[bool, List[str]]:
        """Delegate to module-level check_content_integrity."""
        return check_content_integrity(result, require_phase_decision=require_phase_decision)

    def _build_integrity_complement_prompt(self, missing_fields: List[str], report_language: str = "zh") -> str:
        """Build complement instruction for missing mandatory fields."""
        report_language = normalize_report_language(report_language)
        if report_language == "en":
            lines = ["### Completion requirements: fill the missing mandatory fields below and output the full JSON again:"]
            for f in missing_fields:
                if f == "sentiment_score":
                    lines.append("- sentiment_score: integer score from 0 to 100")
                elif f == "operation_advice":
                    lines.append("- operation_advice: localized action advice")
                elif f == "analysis_summary":
                    lines.append("- analysis_summary: concise analysis summary")
                elif f == "dashboard.core_conclusion.one_sentence":
                    lines.append("- dashboard.core_conclusion.one_sentence: one-line decision")
                elif f == "dashboard.intelligence.risk_alerts":
                    lines.append("- dashboard.intelligence.risk_alerts: risk alert list (can be empty)")
                elif f == "dashboard.battle_plan.sniper_points.stop_loss":
                    lines.append("- dashboard.battle_plan.sniper_points.stop_loss: stop-loss level")
                elif f == "dashboard.phase_decision.phase_context":
                    lines.append("- dashboard.phase_decision.phase_context: public market phase summary subset")
                elif f == "dashboard.phase_decision.action_window":
                    lines.append("- dashboard.phase_decision.action_window: phase-aware action window")
                elif f == "dashboard.phase_decision.immediate_action":
                    lines.append("- dashboard.phase_decision.immediate_action: act now / wait / watch / no intraday action")
                elif f == "dashboard.phase_decision.watch_conditions":
                    lines.append("- dashboard.phase_decision.watch_conditions: list of watch conditions")
                elif f == "dashboard.phase_decision.next_check_time":
                    lines.append("- dashboard.phase_decision.next_check_time: next check point or market-local time")
                elif f == "dashboard.phase_decision.confidence_reason":
                    lines.append("- dashboard.phase_decision.confidence_reason: confidence rationale and data limits")
                elif f == "dashboard.phase_decision.data_limitations":
                    lines.append("- dashboard.phase_decision.data_limitations: list of phase/data quality limitations")
            return "\n".join(lines)

        lines = ["### 補全要求：請在上方分析基礎上補充以下必填內容，並輸出完整 JSON："]
        for f in missing_fields:
            if f == "sentiment_score":
                lines.append("- sentiment_score: 0-100 綜合評分")
            elif f == "operation_advice":
                lines.append("- operation_advice: 買進/加倉/持有/減倉/賣出/觀望")
            elif f == "analysis_summary":
                lines.append("- analysis_summary: 綜合分析摘要")
            elif f == "dashboard.core_conclusion.one_sentence":
                lines.append("- dashboard.core_conclusion.one_sentence: 一句話決策")
            elif f == "dashboard.intelligence.risk_alerts":
                lines.append("- dashboard.intelligence.risk_alerts: 風險警報列表（可為空陣列）")
            elif f == "dashboard.battle_plan.sniper_points.stop_loss":
                lines.append("- dashboard.battle_plan.sniper_points.stop_loss: 止損價")
            elif f == "dashboard.phase_decision.phase_context":
                lines.append("- dashboard.phase_decision.phase_context: 公開低敏市場階段摘要子集")
            elif f == "dashboard.phase_decision.action_window":
                lines.append("- dashboard.phase_decision.action_window: 階段化行動視窗")
            elif f == "dashboard.phase_decision.immediate_action":
                lines.append("- dashboard.phase_decision.immediate_action: 立即行動/等待確認/觀察/無盤中動作")
            elif f == "dashboard.phase_decision.watch_conditions":
                lines.append("- dashboard.phase_decision.watch_conditions: 觀察條件陣列")
            elif f == "dashboard.phase_decision.next_check_time":
                lines.append("- dashboard.phase_decision.next_check_time: 下一次檢查點或市場本地時間")
            elif f == "dashboard.phase_decision.confidence_reason":
                lines.append("- dashboard.phase_decision.confidence_reason: 置信度理由與資料限制")
            elif f == "dashboard.phase_decision.data_limitations":
                lines.append("- dashboard.phase_decision.data_limitations: 階段/資料質量限制陣列")
        return "\n".join(lines)

    def _build_integrity_retry_prompt(
        self,
        base_prompt: str,
        previous_response: str,
        missing_fields: List[str],
        report_language: str = "zh",
    ) -> str:
        """Build retry prompt using the previous response as the complement baseline."""
        complement = self._build_integrity_complement_prompt(missing_fields, report_language=report_language)
        previous_output = previous_response.strip()
        if normalize_report_language(report_language) == "en":
            prefix = "### The previous output is below. Complete the missing fields based on that output and return the full JSON again. Do not omit existing fields:"
        else:
            prefix = "### 上一次輸出如下，請在該輸出基礎上補齊缺失欄位，並重新輸出完整 JSON。不要省略已有欄位："
        return "\n\n".join([
            base_prompt,
            prefix,
            previous_output,
            complement,
        ])

    def _apply_placeholder_fill(self, result: AnalysisResult, missing_fields: List[str]) -> None:
        """Delegate to module-level apply_placeholder_fill."""
        apply_placeholder_fill(result, missing_fields)

    def _parse_response(
        self, 
        response_text: str, 
        code: str, 
        name: str
    ) -> AnalysisResult:
        """
        解析 Gemini 響應（決策儀表盤版）
        
        嘗試從響應中提取 JSON 格式的分析結果，包含 dashboard 欄位
        如果解析失敗，嘗試智慧提取或返回預設結果
        """
        try:
            report_language = normalize_report_language(
                getattr(self._get_runtime_config(), "report_language", "zh")
            )
            # 清理響應文字：移除 markdown 程式碼塊標記
            cleaned_text = response_text
            if '```json' in cleaned_text:
                cleaned_text = cleaned_text.replace('```json', '').replace('```', '')
            elif '```' in cleaned_text:
                cleaned_text = cleaned_text.replace('```', '')
            
            # 嘗試找到 JSON 內容
            json_start = cleaned_text.find('{')
            json_end = cleaned_text.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = cleaned_text[json_start:json_end]
                
                # 嘗試修復常見的 JSON 問題
                json_str = self._fix_json_string(json_str)
                
                data = json.loads(json_str)

                # Schema validation (lenient: on failure, continue with raw dict)
                try:
                    AnalysisReportSchema.model_validate(data)
                except Exception as e:
                    logger.warning(
                        "LLM report schema validation failed, continuing with raw dict: %s",
                        str(e)[:100],
                    )

                # 提取 dashboard 資料
                dashboard = data.get('dashboard', None)

                # 優先使用 AI 返回的股票名稱（如果原名稱無效或包含程式碼）
                ai_stock_name = data.get('stock_name')
                if ai_stock_name and (name.startswith('股票') or name == code or 'Unknown' in name):
                    name = ai_stock_name

                # 解析所有欄位，使用預設值防止缺失
                # 解析 decision_type，如果沒有則根據 operation_advice 推斷
                decision_type = data.get('decision_type', '')
                if not decision_type:
                    op = data.get('operation_advice', 'Hold' if report_language == "en" else '持有')
                    decision_type = infer_decision_type_from_advice(op, default='hold')
                
                return AnalysisResult(
                    code=code,
                    name=name,
                    # 核心指標
                    sentiment_score=int(data.get('sentiment_score', 50)),
                    trend_prediction=data.get('trend_prediction', 'Sideways' if report_language == "en" else '震盪'),
                    operation_advice=data.get('operation_advice', 'Hold' if report_language == "en" else '持有'),
                    decision_type=decision_type,
                    confidence_level=localize_confidence_level(
                        data.get('confidence_level', 'Medium' if report_language == "en" else '中'),
                        report_language,
                    ),
                    report_language=report_language,
                    # 決策儀表盤
                    dashboard=dashboard,
                    # 走勢分析
                    trend_analysis=data.get('trend_analysis', ''),
                    short_term_outlook=data.get('short_term_outlook', ''),
                    medium_term_outlook=data.get('medium_term_outlook', ''),
                    # 技術面
                    technical_analysis=data.get('technical_analysis', ''),
                    ma_analysis=data.get('ma_analysis', ''),
                    volume_analysis=data.get('volume_analysis', ''),
                    pattern_analysis=data.get('pattern_analysis', ''),
                    # 基本面
                    fundamental_analysis=data.get('fundamental_analysis', ''),
                    sector_position=data.get('sector_position', ''),
                    company_highlights=data.get('company_highlights', ''),
                    # 情緒面/訊息面
                    news_summary=data.get('news_summary', ''),
                    market_sentiment=data.get('market_sentiment', ''),
                    hot_topics=data.get('hot_topics', ''),
                    # 綜合
                    analysis_summary=data.get('analysis_summary', 'Analysis completed' if report_language == "en" else '分析完成'),
                    key_points=data.get('key_points', ''),
                    risk_warning=data.get('risk_warning', ''),
                    buy_reason=data.get('buy_reason', ''),
                    # 後設資料
                    search_performed=data.get('search_performed', False),
                    data_sources=data.get('data_sources', 'Technical data' if report_language == "en" else '技術面資料'),
                    value_network_mermaid=data.get('value_network_mermaid'),
                    four_masters_commentary=data.get('four_masters_commentary') if isinstance(data.get('four_masters_commentary'), dict) else None,
                    success=True,
                )
            else:
                # 沒有找到 JSON，標記為失敗
                logger.warning(f"無法從響應中提取 JSON，標記為解析失敗")
                return self._parse_text_response(response_text, code, name)
                
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失敗: {e}，標記為解析失敗")
            return self._parse_text_response(response_text, code, name)
    
    def _fix_json_string(self, json_str: str) -> str:
        """修復常見的 JSON 格式問題"""
        import re
        
        # 移除註釋
        json_str = re.sub(r'//.*?\n', '\n', json_str)
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
        
        # 修復尾隨逗號
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        
        # 確保布林值是小寫
        json_str = json_str.replace('True', 'true').replace('False', 'false')
        
        # fix by json-repair
        json_str = repair_json(json_str)
        
        return json_str

    def _validate_json_response(self, text: str) -> None:
        """Validate that *text* contains a parseable JSON object.

        Used as the ``response_validator`` argument to :meth:`_call_litellm` so
        that a JSON-less or unparseable reply from the primary model is treated
        as a model failure and triggers fallback to the next configured model.

        Raises:
            ValueError: if no JSON object is found in *text*.
            json.JSONDecodeError: if the extracted JSON cannot be parsed (after
                :meth:`_fix_json_string` attempts repair).
        """
        cleaned = text
        if "```json" in cleaned:
            cleaned = cleaned.replace("```json", "").replace("```", "")
        elif "```" in cleaned:
            cleaned = cleaned.replace("```", "")

        json_start = cleaned.find("{")
        json_end = cleaned.rfind("}") + 1

        if json_start < 0 or json_end <= json_start:
            raise ValueError("No JSON object found in LLM response")

        json_str = cleaned[json_start:json_end]
        json_str = self._fix_json_string(json_str)
        json.loads(json_str)
    
    def _parse_text_response(
        self, 
        response_text: str, 
        code: str, 
        name: str
    ) -> AnalysisResult:
        """從純文字響應中儘可能提取分析資訊"""
        report_language = normalize_report_language(
            getattr(self._get_runtime_config(), "report_language", "zh")
        )
        # 嘗試識別關鍵詞來判斷情緒
        sentiment_score = 50
        trend = 'Sideways' if report_language == "en" else '震盪'
        advice = 'Hold' if report_language == "en" else '持有'
        
        text_lower = response_text.lower()
        
        # 簡單的情緒識別
        positive_keywords = ['看多', '買進', '上漲', '突破', '強勢', '利好', '加倉', 'bullish', 'buy']
        negative_keywords = ['看空', '賣出', '下跌', '跌破', '弱勢', '利空', '減倉', 'bearish', 'sell']
        
        positive_count = sum(1 for kw in positive_keywords if kw in text_lower)
        negative_count = sum(1 for kw in negative_keywords if kw in text_lower)
        
        if positive_count > negative_count + 1:
            sentiment_score = 65
            trend = 'Bullish' if report_language == "en" else '看多'
            advice = 'Buy' if report_language == "en" else '買進'
            decision_type = 'buy'
        elif negative_count > positive_count + 1:
            sentiment_score = 35
            trend = 'Bearish' if report_language == "en" else '看空'
            advice = 'Sell' if report_language == "en" else '賣出'
            decision_type = 'sell'
        else:
            decision_type = 'hold'
        
        # 擷取前500字元作為摘要
        summary = response_text[:500] if response_text else ('No analysis result' if report_language == "en" else '無分析結果')
        
        return AnalysisResult(
            code=code,
            name=name,
            sentiment_score=sentiment_score,
            trend_prediction=trend,
            operation_advice=advice,
            decision_type=decision_type,
            confidence_level='Low' if report_language == "en" else '低',
            analysis_summary=summary,
            key_points='JSON parsing failed; treat this as best-effort output.' if report_language == "en" else 'JSON解析失敗，僅供參考',
            risk_warning='The result may be inaccurate. Cross-check with other information.' if report_language == "en" else '分析結果可能不準確，建議結合其他資訊判斷',
            raw_response=response_text,
            success=False,
            error_message='LLM response is not valid JSON; analysis result will not be persisted',
            report_language=report_language,
        )
    
    def batch_analyze(
        self, 
        contexts: List[Dict[str, Any]],
        delay_between: float = 2.0
    ) -> List[AnalysisResult]:
        """
        批次分析多隻股票
        
        注意：為避免 API 速率限制，每次分析之間會有延遲
        
        Args:
            contexts: 上下文資料列表
            delay_between: 每次分析之間的延遲（秒）
            
        Returns:
            AnalysisResult 列表
        """
        results = []
        
        for i, context in enumerate(contexts):
            if i > 0:
                logger.debug(f"等待 {delay_between} 秒後繼續...")
                time.sleep(delay_between)
            
            result = self.analyze(context)
            results.append(result)
        
        return results


# 便捷函式
def get_analyzer() -> GeminiAnalyzer:
    """獲取 LLM 分析器例項"""
    return GeminiAnalyzer()


if __name__ == "__main__":
    # 測試程式碼
    logging.basicConfig(level=logging.DEBUG)
    
    # 模擬上下文資料
    test_context = {
        'code': '600519',
        'date': '2026-01-09',
        'today': {
            'open': 1800.0,
            'high': 1850.0,
            'low': 1780.0,
            'close': 1820.0,
            'volume': 10000000,
            'amount': 18200000000,
            'pct_chg': 1.5,
            'ma5': 1810.0,
            'ma10': 1800.0,
            'ma20': 1790.0,
            'volume_ratio': 1.2,
        },
        'ma_status': '多頭排列 📈',
        'volume_change_ratio': 1.3,
        'price_change_ratio': 1.5,
    }
    
    analyzer = GeminiAnalyzer()
    
    if analyzer.is_available():
        print("=== AI 分析測試 ===")
        result = analyzer.analyze(test_context)
        print(f"分析結果: {result.to_dict()}")
    else:
        print("Gemini API 未配置，跳過測試")
