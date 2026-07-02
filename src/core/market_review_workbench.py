# -*- coding: utf-8 -*-
"""
===================================
大盘复盘"复盘工作台"纯计算层 (Issue #1584)
===================================

职责：
1. 指数均线快照与技术状态标签（基于 data_provider 提供的日线历史，本地计算）
2. 宽度分化诊断、市场状态、建议仓位、大小盘结构观察等确定性判断
3. 合并 LLM 判读结果（确定性字段永远优先；催化只允许引用给定新闻编号）
4. 渲染注入复盘报告的"复盘工作台" markdown 块

本模块只做纯计算，不做任何 I/O，也不 import market_analyzer（避免循环依赖），
所有市场概览输入按鸭子类型读取属性。数据缺失一律省略字段并记录
data_quality.notes，绝不编造均线、领涨股或消化状态。

语言约定与既有确定性块一致：接受 'zh' / 'en'（ko 复用 en 结构，
由调用方按 _get_review_language() 传入）。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# 注入报告的固定标题字面量；Web 端据此在结构化渲染时过滤该 markdown 段，
# 避免与工作台结构化模块卡重复展示。修改需与前端 WORKBENCH_SECTION_TITLES 同步。
SUMMARY_HEADING_ZH = "一句话结论"
SUMMARY_HEADING_EN = "One-Line Conclusion"

_MA_FLAT_THRESHOLD = 0.001  # |close-ma|/ma < 0.1% 视为贴近均线
# 历史最后一根K线落后现价日期超过该天数视为过期；阈值取 15 天以覆盖
# 春节/国庆等 9-11 个自然日的长假空窗（更长的空窗按数据过期如实降级）。
_STALE_HISTORY_DAYS = 15

# 大小盘/风格结构观察使用的指数对：
# region -> ((强侧候选码, 名称), (弱侧候选码, 名称), 风格措辞)
# 候选码需与 get_main_indices 各数据源返回的 code 格式匹配（含 tushare 纯数字格式）。
# 措辞按指数对的真实语义选取，避免用非小盘指数下"小盘"结论（Issue #1584 数据诚实要求）：
# - cn 上证50 vs 创业板指：权重/大盘 vs 成长/小盘（惯用语义）
# - us 标普500 vs 罗素2000：大盘权重 vs 小盘（真实规模分化）
# - hk 恒指 vs 恒生科技：权重/价值 vs 科技/成长（不涉及小盘）
# 注：A 股"中小盘扩散"识别暂无中证1000/2000 指数支撑（未纳入指数集合），
# 由宽度分化诊断（指数弱但个股强）与 LLM 判读间接覆盖。
_STRUCTURE_PAIRS = {
    "cn": (
        ({"sh000016", "000016"}, {"zh": "上证50", "en": "SSE 50"}),
        ({"sz399006", "399006"}, {"zh": "创业板指", "en": "ChiNext"}),
        {"zh": ("权重/大盘风格占优", "成长/小盘风格占优"),
         "en": ("large-cap/defensive style in favor", "growth/small-cap style in favor")},
    ),
    "us": (
        ({"SPX"}, {"zh": "标普500", "en": "S&P 500"}),
        ({"RUT"}, {"zh": "罗素2000", "en": "Russell 2000"}),
        {"zh": ("大盘权重风格占优", "小盘风格占优"),
         "en": ("large-cap style in favor", "small-cap style in favor")},
    ),
    "hk": (
        ({"HSI"}, {"zh": "恒生指数", "en": "HSI"}),
        ({"HSTECH"}, {"zh": "恒生科技", "en": "HS Tech"}),
        {"zh": ("权重/价值风格占优", "科技/成长风格占优"),
         "en": ("value/large-cap style in favor", "tech/growth style in favor")},
    ),
}


def compute_index_ma_snapshot(
    bars: Optional[Sequence[Dict[str, Any]]],
    latest_close: Optional[float] = None,
    latest_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    根据日线历史计算均线快照。

    Args:
        bars: [{date: 'YYYY-MM-DD', close: float}]，允许乱序/None
        latest_close: 实时收盘/最新点位（历史源尚未包含当日时并入计算）
        latest_date: 现价对应日期 'YYYY-MM-DD'

    Returns:
        {ma5, ma10, ma20: float|None,
         ma_status: {'ma5': 'above|below|flat', ...} 仅含已计算均线,
         bars_used: int,
         data_quality: 'ok|partial|insufficient|stale'}
    """
    cleaned: List[Dict[str, Any]] = []
    for bar in bars or []:
        if not isinstance(bar, dict):
            continue
        close = bar.get("close")
        date_str = str(bar.get("date") or "")[:10]
        try:
            close_value = float(close)
        except (TypeError, ValueError):
            continue
        if close_value <= 0 or len(date_str) != 10:
            continue
        cleaned.append({"date": date_str, "close": close_value})
    cleaned.sort(key=lambda item: item["date"])

    reference_close = None
    if latest_close is not None:
        try:
            reference_close = float(latest_close)
        except (TypeError, ValueError):
            reference_close = None
        if reference_close is not None and reference_close <= 0:
            reference_close = None

    # 过期防护：历史最后一根落后现价日期超过 _STALE_HISTORY_DAYS 个自然日
    # （阈值已覆盖常规长假空窗），不计算均线；
    # 必须在并入实时合成K线之前判断，否则合成K线会掩盖历史过期。
    if cleaned and latest_date:
        try:
            last_dt = datetime.strptime(cleaned[-1]["date"], "%Y-%m-%d")
            ref_dt = datetime.strptime(str(latest_date)[:10], "%Y-%m-%d")
            if (ref_dt - last_dt).days > _STALE_HISTORY_DAYS:
                return {"bars_used": len(cleaned), "data_quality": "stale"}
        except ValueError:
            pass

    # 历史源尚未包含当日收盘时，用实时价并入一根合成K线。
    # latest_date 是运行日（服务器本地日期），未必是该市场的新交易日：
    # 休市/周末/时差场景下实时行情返回的就是最后一根历史K线的收盘价，
    # 此时并入合成K线会把最后一个交易日重复计入均线（静默失真）。
    # 以"实时价 != 最后一根历史收盘"作为出现新交易时段的判据；
    # 极端情况下真实新交易日恰好收平会少并入一根，但均线位置判断不受影响。
    if (
        reference_close is not None
        and latest_date
        and (not cleaned or cleaned[-1]["date"] < latest_date)
        and (not cleaned or reference_close != cleaned[-1]["close"])
    ):
        cleaned.append({"date": str(latest_date)[:10], "close": reference_close})

    if not cleaned:
        return {"bars_used": 0, "data_quality": "insufficient"}

    closes = [bar["close"] for bar in cleaned]
    if reference_close is None:
        reference_close = closes[-1]

    snapshot: Dict[str, Any] = {"bars_used": len(cleaned)}
    ma_status: Dict[str, str] = {}
    for window in (5, 10, 20):
        key = f"ma{window}"
        if len(closes) < window:
            snapshot[key] = None
            continue
        ma_value = round(sum(closes[-window:]) / window, 2)
        snapshot[key] = ma_value
        if ma_value <= 0:
            continue
        deviation = (reference_close - ma_value) / ma_value
        if abs(deviation) < _MA_FLAT_THRESHOLD:
            ma_status[key] = "flat"
        elif deviation > 0:
            ma_status[key] = "above"
        else:
            ma_status[key] = "below"

    if ma_status:
        snapshot["ma_status"] = ma_status
    if snapshot.get("ma20") is not None:
        snapshot["data_quality"] = "ok"
    elif snapshot.get("ma5") is not None or snapshot.get("ma10") is not None:
        snapshot["data_quality"] = "partial"
    else:
        snapshot["data_quality"] = "insufficient"
    return snapshot


def technical_status_label(ma_status: Optional[Dict[str, str]], language: str = "zh") -> Optional[str]:
    """由均线位置生成确定性技术状态标签，如 '站上MA5/MA10，MA20 之下'。"""
    if not ma_status:
        return None
    above = [key.upper() for key in ("ma5", "ma10", "ma20") if ma_status.get(key) == "above"]
    flat = [key.upper() for key in ("ma5", "ma10", "ma20") if ma_status.get(key) == "flat"]
    below = [key.upper() for key in ("ma5", "ma10", "ma20") if ma_status.get(key) == "below"]
    if not (above or flat or below):
        return None

    if language == "en":
        if above and not below and not flat:
            return f"Above all MAs ({'/'.join(above)})"
        if below and not above and not flat:
            return f"Below all MAs ({'/'.join(below)})"
        parts = []
        if above:
            parts.append(f"above {'/'.join(above)}")
        if flat:
            parts.append(f"near {'/'.join(flat)}")
        if below:
            parts.append(f"below {'/'.join(below)}")
        return ", ".join(parts).capitalize()

    if above and not below and not flat:
        return f"站上全部均线（{'/'.join(above)}）"
    if below and not above and not flat:
        return f"跌破全部均线（{'/'.join(below)}）"
    parts = []
    if above:
        parts.append(f"站上{'/'.join(above)}")
    if flat:
        parts.append(f"贴近{'/'.join(flat)}")
    if below:
        parts.append(f"{'/'.join(below)} 之下")
    return "，".join(parts)


def _breadth_inputs(overview: Any) -> Optional[Dict[str, float]]:
    """从概览提取宽度输入；无有效宽度数据返回 None。

    确定性宽度诊断只使用涨跌家数与指数平均涨跌幅；涨跌停结构已计入
    市场温度（market_light limit 维度）并作为 LLM 判读上下文，成交额
    缺少历史基线、不做确定性"放量"判断（Issue #1584 数据边界）。
    """
    up_count = getattr(overview, "up_count", 0) or 0
    down_count = getattr(overview, "down_count", 0) or 0
    participation = up_count + down_count
    if participation <= 0:
        return None
    indices = getattr(overview, "indices", None) or []
    changes = [
        getattr(idx, "change_pct", None)
        for idx in indices
        if getattr(idx, "change_pct", None) is not None
    ]
    if not changes:
        return None
    return {
        "avg_change": sum(changes) / len(changes),
        "up_ratio": up_count / participation,
    }


def compute_divergence_diagnosis(overview: Any, language: str = "zh") -> Optional[str]:
    """指数-宽度分化诊断（需要宽度数据；无数据返回 None，不猜测）。"""
    inputs = _breadth_inputs(overview)
    if inputs is None:
        return None
    avg = inputs["avg_change"]
    up_ratio = inputs["up_ratio"]

    if language == "en":
        if avg >= 0.2 and up_ratio < 0.45:
            return (
                f"Indices rose (avg {avg:+.2f}%) but only {up_ratio:.0%} of stocks advanced — "
                "index-led, narrow breadth."
            )
        if avg >= 0.2 and up_ratio >= 0.55:
            return (
                f"Indices (avg {avg:+.2f}%) and breadth ({up_ratio:.0%} advancers) rose together — "
                "broad participation."
            )
        if avg <= -0.2 and up_ratio >= 0.55:
            return (
                f"Indices fell (avg {avg:+.2f}%) while {up_ratio:.0%} of stocks advanced — "
                "heavyweight drag, resilient breadth."
            )
        # 普跌 wording aligned with derive_market_state (avg <= -0.8)
        if avg <= -0.8 and up_ratio < 0.35:
            return (
                f"Indices (avg {avg:+.2f}%) and breadth ({up_ratio:.0%} advancers) fell together — "
                "broad selloff."
            )
        if avg <= -0.2 and up_ratio < 0.35:
            return (
                f"Indices (avg {avg:+.2f}%) and breadth ({up_ratio:.0%} advancers) both soft — "
                "weak consolidation with poor breadth."
            )
        if avg <= -0.2:
            return (
                f"Indices fell (avg {avg:+.2f}%) with {up_ratio:.0%} advancers — "
                "structural selling rather than a full-market rout."
            )
        if up_ratio >= 0.55:
            return f"Indices were flat but {up_ratio:.0%} of stocks advanced — better than the index suggests."
        if up_ratio < 0.45:
            return f"Indices were flat but only {up_ratio:.0%} of stocks advanced — weaker than the index suggests."
        return None

    if avg >= 0.2 and up_ratio < 0.45:
        return f"指数上行（均涨 {avg:+.2f}%）但上涨家数占比仅 {up_ratio:.0%}，宽度不足，属结构性行情。"
    if avg >= 0.2 and up_ratio >= 0.55:
        return f"指数（均涨 {avg:+.2f}%）与宽度（上涨占比 {up_ratio:.0%}）同步走强，普涨扩散。"
    if avg <= -0.2 and up_ratio >= 0.55:
        return f"指数下跌（均跌 {avg:+.2f}%）但上涨占比达 {up_ratio:.0%}，权重拖累、个股偏活跃。"
    # 普跌措辞与 derive_market_state 阈值对齐（avg <= -0.8），避免同一块内自相矛盾
    if avg <= -0.8 and up_ratio < 0.35:
        return f"指数（均跌 {avg:+.2f}%）与宽度（上涨占比 {up_ratio:.0%}）同步走弱，普跌格局。"
    if avg <= -0.2 and up_ratio < 0.35:
        return f"指数（均跌 {avg:+.2f}%）与宽度（上涨占比 {up_ratio:.0%}）同步偏弱，弱势调整、赚钱效应差。"
    if avg <= -0.2:
        return f"指数下跌（均跌 {avg:+.2f}%）、上涨占比 {up_ratio:.0%}，结构性杀跌而非全面普跌。"
    if up_ratio >= 0.55:
        return f"指数波动有限但上涨占比 {up_ratio:.0%}，体感好于指数。"
    if up_ratio < 0.45:
        return f"指数波动有限但上涨占比仅 {up_ratio:.0%}，体感弱于指数。"
    return None


def derive_market_state(overview: Any, language: str = "zh") -> Optional[str]:
    """由指数均涨与宽度推导市场状态（固定词表）；无宽度数据返回 None。"""
    inputs = _breadth_inputs(overview)
    if inputs is None:
        return None
    avg = inputs["avg_change"]
    up_ratio = inputs["up_ratio"]

    if avg >= 0.8 and up_ratio >= 0.6:
        return "Broad rally" if language == "en" else "强势扩散"
    if avg >= 0.2 and up_ratio >= 0.55:
        return "Recovering breadth" if language == "en" else "普涨修复"
    if avg >= 0.2 and up_ratio < 0.45:
        return "Index-strong, stocks-weak" if language == "en" else "指数强但个股弱"
    if avg <= -0.2 and up_ratio >= 0.55:
        return "Index-weak, stocks-resilient" if language == "en" else "指数弱但个股强"
    if avg <= -0.8 and up_ratio < 0.35:
        return "Broad selloff" if language == "en" else "普跌"
    if avg <= -0.2:
        return "Weak consolidation" if language == "en" else "弱势调整"
    return "Mixed / divergent" if language == "en" else "震荡分化"


def compute_structure_note(overview: Any, region: str, language: str = "zh") -> Optional[str]:
    """大小盘/权重-成长结构观察；两只对照指数齐备且分化≥1个百分点才输出。

    风格措辞来自 _STRUCTURE_PAIRS 的按区域配置，保证结论与指数对的
    真实语义一致（如美股用标普500/罗素2000 得出大盘 vs 小盘结论）。
    """
    pair = _STRUCTURE_PAIRS.get(region)
    if not pair:
        return None
    (large_codes, large_names), (growth_codes, growth_names), style_labels = pair

    def _find_change(codes: set) -> Optional[float]:
        for idx in getattr(overview, "indices", None) or []:
            code = str(getattr(idx, "code", "") or "").strip()
            if code in codes or code.lower() in codes or code.upper() in codes:
                change = getattr(idx, "change_pct", None)
                if change is not None:
                    return float(change)
        return None

    large_change = _find_change(large_codes)
    growth_change = _find_change(growth_codes)
    if large_change is None or growth_change is None:
        return None
    spread = large_change - growth_change
    if abs(spread) < 1.0:
        return None

    large_label = large_names["en"] if language == "en" else large_names["zh"]
    growth_label = growth_names["en"] if language == "en" else growth_names["zh"]
    strong_style, weak_style = style_labels["en"] if language == "en" else style_labels["zh"]
    if language == "en":
        if spread > 0:
            return (
                f"{large_label} ({large_change:+.2f}%) clearly outperformed {growth_label} "
                f"({growth_change:+.2f}%) — {strong_style}."
            )
        return (
            f"{large_label} ({large_change:+.2f}%) clearly lagged {growth_label} "
            f"({growth_change:+.2f}%) — {weak_style}."
        )
    if spread > 0:
        return (
            f"{large_label}（{large_change:+.2f}%）明显强于{growth_label}"
            f"（{growth_change:+.2f}%），{strong_style}。"
        )
    return (
        f"{large_label}（{large_change:+.2f}%）明显弱于{growth_label}"
        f"（{growth_change:+.2f}%），{weak_style}。"
    )


def derive_suggested_position(score: Any, language: str = "zh") -> Optional[str]:
    """由市场温度分推导建议仓位档位（与 market_light 阈值 40/60 对齐）。"""
    try:
        value = int(score)
    except (TypeError, ValueError):
        return None
    if language == "en":
        if value < 30:
            return "0-20%"
        if value < 40:
            return "10-30%"
        if value < 60:
            return "30-50%"
        if value < 75:
            return "50-70%"
        return "60-80%"
    if value < 30:
        return "0-2成"
    if value < 40:
        return "1-3成"
    if value < 60:
        return "3-5成"
    if value < 75:
        return "5-7成"
    return "6-8成"


def _compact_text(value: Any, limit: int = 200) -> Optional[str]:
    """收敛 LLM 文本字段：非字符串/空值返回 None，超长截断。"""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text[:limit]


def _compact_str_list(value: Any, item_limit: int = 80, max_items: int = 6) -> List[str]:
    if not isinstance(value, list):
        return []
    items: List[str] = []
    for entry in value:
        text = _compact_text(entry, limit=item_limit)
        if text:
            items.append(text)
        if len(items) >= max_items:
            break
    return items


def build_workbench_core(
    overview: Any,
    light_snapshot: Optional[Dict[str, Any]],
    region: str,
    language: str = "zh",
    ma_notes: Optional[List[str]] = None,
    expects_breadth: bool = False,
) -> Dict[str, Any]:
    """
    组装确定性工作台核心（不含任何 LLM 字段）。

    Args:
        expects_breadth: 该市场按 MarketProfile 应有宽度数据（如 A 股）。
            应有而缺失时补数据质量说明；结构性无宽度的市场（US/HK/JP/KR）
            已由 prompt 数据边界与文档覆盖，不重复加噪声说明。

    Returns:
        {summary: {...}, divergence_diagnosis: str|None,
         data_quality: {notes: [...]}}；不可计算的键一律省略。
    """
    notes: List[str] = list(ma_notes or [])
    summary: Dict[str, Any] = {}

    if expects_breadth and _breadth_inputs(overview) is None:
        notes.append(
            "Advance/decline breadth unavailable; breadth diagnosis and deterministic market state omitted."
            if language == "en"
            else "缺少涨跌家数宽度数据，宽度分化诊断与确定性市场状态省略。"
        )

    score = None
    if isinstance(light_snapshot, dict):
        score = light_snapshot.get("score")
        if score is not None:
            summary["temperature_score"] = int(score)
            label = light_snapshot.get("temperature_label")
            if label:
                summary["temperature_label"] = str(label)
    if score is None:
        notes.append(
            "Market temperature unavailable for this market; position band omitted."
            if language == "en"
            else "该市场暂无市场温度数据，建议仓位档位省略。"
        )
    else:
        position = derive_suggested_position(score, language)
        if position:
            summary["suggested_position"] = position

    market_state = derive_market_state(overview, language)
    if market_state:
        summary["market_state"] = market_state
        summary["market_state_source"] = "deterministic"

    structure_note = compute_structure_note(overview, region, language)
    if structure_note:
        summary["structure_note"] = structure_note

    divergence = compute_divergence_diagnosis(overview, language)

    core: Dict[str, Any] = {"data_quality": {"notes": notes}}
    if summary:
        core["summary"] = summary
    if divergence:
        core["divergence_diagnosis"] = divergence
    return core


def merge_workbench_judgment(
    core: Dict[str, Any],
    judgment: Optional[Dict[str, Any]],
    news: Optional[Sequence[Dict[str, Any]]],
    language: str = "zh",
    index_codes: Optional[Sequence[str]] = None,
    sector_names: Optional[Sequence[str]] = None,
    fallback_guidance: Optional[str] = None,
) -> Dict[str, Any]:
    """
    合并确定性核心与 LLM 判读。确定性字段永远优先；判读只补空位：
    - market_state 仅在确定性缺失时采用（并标记 market_state_source=llm）
    - catalysts 必须引用给定新闻编号，标题从新闻复制，越界条目丢弃
    - 指数点评按 code 匹配、板块持续性/点评按名称精确匹配，未匹配丢弃

    judgment 为 None 时补数据质量说明，并用确定性档位生成次日计划骨架。
    """
    merged: Dict[str, Any] = {key: value for key, value in core.items()}
    summary = dict(merged.get("summary") or {})
    notes = list((merged.get("data_quality") or {}).get("notes") or [])
    news_items = list(news or [])
    valid_index_codes = {str(code) for code in (index_codes or []) if code}
    valid_sector_names = {str(name) for name in (sector_names or []) if name}

    if not judgment:
        notes.append(
            "LLM structured judgment unavailable; only deterministic fields are shown."
            if language == "en"
            else "LLM 结构化判读不可用，仅展示确定性字段。"
        )
    else:
        market_state = _compact_text(judgment.get("market_state"), limit=40)
        if market_state and "market_state" not in summary:
            summary["market_state"] = market_state
            summary["market_state_source"] = "llm"

        core_conclusion = _compact_text(judgment.get("core_conclusion"), limit=160)
        if core_conclusion:
            summary["core_conclusion"] = core_conclusion

        weight_note = _compact_text(judgment.get("weight_stock_note"), limit=160)
        if weight_note:
            summary["weight_stock_note"] = weight_note

        rotation_raw = judgment.get("style_rotation")
        if isinstance(rotation_raw, dict):
            rotation: Dict[str, Any] = {}
            strong = _compact_str_list(rotation_raw.get("strong"))
            weak = _compact_str_list(rotation_raw.get("weak"))
            comment = _compact_text(rotation_raw.get("comment"), limit=120)
            if strong:
                rotation["strong"] = strong
            if weak:
                rotation["weak"] = weak
            if comment:
                rotation["comment"] = comment
            if rotation:
                merged["style_rotation"] = rotation

        index_comments: Dict[str, str] = {}
        for entry in judgment.get("indices") or []:
            if not isinstance(entry, dict):
                continue
            code = str(entry.get("code") or "").strip()
            comment = _compact_text(entry.get("comment"), limit=120)
            if code and comment and (not valid_index_codes or code in valid_index_codes):
                index_comments[code] = comment
        if index_comments:
            merged["index_comments"] = index_comments

        sector_extras: Dict[str, Dict[str, str]] = {}
        for entry in judgment.get("sectors") or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name or (valid_sector_names and name not in valid_sector_names):
                continue
            extra: Dict[str, str] = {}
            persistence = _compact_text(entry.get("persistence"), limit=20)
            comment = _compact_text(entry.get("comment"), limit=120)
            if persistence:
                extra["persistence"] = persistence
            if comment:
                extra["comment"] = comment
            if extra:
                sector_extras[name] = extra
        if sector_extras:
            merged["sector_extras"] = sector_extras

        catalysts: List[Dict[str, Any]] = []
        for entry in judgment.get("catalysts") or []:
            if not isinstance(entry, dict):
                continue
            news_index = entry.get("news_index")
            if not isinstance(news_index, int) or not (0 <= news_index < len(news_items)):
                continue
            news_item = news_items[news_index]
            title = _compact_text(
                news_item.get("title") if isinstance(news_item, dict) else None,
                limit=120,
            )
            if not title:
                continue
            catalyst: Dict[str, Any] = {"news_index": news_index, "title": title}
            for key, limit in (
                ("nature", 20),
                ("scope", 40),
                ("duration", 20),
                ("digestion", 20),
                ("comment", 120),
            ):
                value = _compact_text(entry.get(key), limit=limit)
                if value:
                    catalyst[key] = value
            catalysts.append(catalyst)
        if catalysts:
            merged["catalysts"] = catalysts

        plan_raw = judgment.get("next_session_plan")
        if isinstance(plan_raw, dict):
            plan: Dict[str, Any] = {}
            advice = _compact_text(plan_raw.get("position_advice"), limit=120)
            if advice:
                plan["position_advice"] = advice
            for key in ("focus_sectors", "avoid_sectors", "key_levels", "risk_triggers"):
                values = _compact_str_list(plan_raw.get(key))
                if values:
                    plan[key] = values
            if plan:
                merged["next_session_plan"] = plan

    # 次日计划骨架兜底：确定性仓位档位 + 市场灯操作建议（不编造关注/回避方向）
    if "next_session_plan" not in merged:
        skeleton_parts = []
        if summary.get("suggested_position"):
            prefix = "Position band" if language == "en" else "参考仓位"
            skeleton_parts.append(f"{prefix} {summary['suggested_position']}")
        if fallback_guidance:
            skeleton_parts.append(str(fallback_guidance))
        if skeleton_parts:
            merged["next_session_plan"] = {
                "position_advice": "；".join(skeleton_parts) if language != "en" else "; ".join(skeleton_parts)
            }

    if summary:
        merged["summary"] = summary
    merged["data_quality"] = {"notes": notes}
    return merged


def render_summary_block(workbench: Optional[Dict[str, Any]], language: str = "zh") -> str:
    """
    渲染注入报告顶部的"一句话结论"块（参考截图模块①）。

    只包含结论性判断与数据说明；指数/板块/催化等表格由各自 section 的
    注入块承载，本块不重复。数据说明独立于 summary 渲染：JP/KR 等市场
    market_light 缺失且判读失败时，workbench 可能只剩 data_quality.notes，
    此时仍需注入说明块，让报告/推送能解释字段缺失原因（不伪造数据的
    另一半承诺）。结论行与数据说明全部缺失时才返回空字符串（不注入）。
    """
    if not isinstance(workbench, dict):
        return ""
    summary = workbench.get("summary") or {}
    en = language == "en"
    lines: List[str] = []

    signal_bits: List[str] = []
    if summary.get("temperature_score") is not None:
        temp_label = summary.get("temperature_label")
        suffix = (f" ({temp_label})" if temp_label else "") if en else (f"（{temp_label}）" if temp_label else "")
        signal_bits.append(
            f"Market temperature: {summary['temperature_score']}/100{suffix}"
            if en
            else f"市场温度：{summary['temperature_score']}/100{suffix}"
        )
    if summary.get("market_state"):
        signal_bits.append(
            f"Market state: {summary['market_state']}" if en else f"市场状态：{summary['market_state']}"
        )
    if summary.get("suggested_position"):
        signal_bits.append(
            f"Suggested position: {summary['suggested_position']}"
            if en
            else f"建议仓位：{summary['suggested_position']}"
        )
    if signal_bits:
        lines.append(" | ".join(signal_bits) if en else " ｜ ".join(signal_bits))

    if summary.get("core_conclusion"):
        label = "**Core conclusion**" if en else "**核心结论**"
        lines.append(f"{label}: {summary['core_conclusion']}" if en else f"{label}：{summary['core_conclusion']}")

    for key, zh_label, en_label in (
        ("structure_note", "结构观察", "Structure"),
        ("weight_stock_note", "权重观察", "Heavyweights"),
    ):
        if summary.get(key):
            lines.append(f"- {en_label}: {summary[key]}" if en else f"- {zh_label}：{summary[key]}")

    notes = (workbench.get("data_quality") or {}).get("notes") or []
    if notes:
        joined = "; ".join(notes) if en else "；".join(notes)
        lines.append(f"> Data notes: {joined}" if en else f"> 数据说明：{joined}")

    if not any(line.strip() for line in lines):
        return ""

    heading = SUMMARY_HEADING_EN if en else SUMMARY_HEADING_ZH
    return f"### {heading}\n\n" + "\n".join(lines)


def render_catalysts_table(
    catalysts: Optional[Sequence[Dict[str, Any]]],
    language: str = "zh",
) -> str:
    """渲染消息催化表（注入消息催化 section；参考截图模块⑤）。"""
    rows: List[str] = []
    for catalyst in catalysts or []:
        if not isinstance(catalyst, dict) or not catalyst.get("title"):
            continue
        rows.append(
            f"| {catalyst['title']} | {catalyst.get('nature') or '-'} "
            f"| {catalyst.get('scope') or '-'} | {catalyst.get('duration') or '-'} "
            f"| {catalyst.get('digestion') or '-'} | {catalyst.get('comment') or '-'} |"
        )
    if not rows:
        return ""
    if language == "en":
        header = "| Catalyst | Nature | Scope | Duration | Digestion | Comment |"
    else:
        header = "| 消息 | 性质 | 影响范围 | 持续性 | 消化状态 | 点评 |"
    return "\n".join([header, "|------|------|------|------|------|------|", *rows])


def render_style_rotation_line(
    style_rotation: Optional[Dict[str, Any]],
    language: str = "zh",
) -> str:
    """渲染板块 section 末尾的"判断：风格切换"行（参考截图模块④）。"""
    rotation = style_rotation or {}
    strong = rotation.get("strong") or []
    weak = rotation.get("weak") or []
    comment = rotation.get("comment") or ""
    if not (strong or weak or comment):
        return ""
    if language == "en":
        bits = []
        if strong:
            bits.append(f"strong: {', '.join(strong)}")
        if weak:
            bits.append(f"weak: {', '.join(weak)}")
        text = "; ".join(bits)
        tail = f" {comment}" if comment else ""
        return f"**Style rotation**: {text}.{tail}".rstrip()
    bits = []
    if strong:
        bits.append(f"走强 {'、'.join(strong)}")
    if weak:
        bits.append(f"承压 {'、'.join(weak)}")
    text = "；".join(bits)
    tail = f"{comment}" if comment else ""
    body = f"{text}。{tail}" if text else tail
    return f"**判断（风格切换）**：{body}"
