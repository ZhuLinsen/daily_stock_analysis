# -*- coding: utf-8 -*-
"""Prompt rendering for Issue #1389 AnalysisContextPack runtime summaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Optional


BLOCK_LABELS_ZH = {
    "quote": "行情",
    "daily_bars": "日线",
    "technical": "技术",
    "chip": "筹码",
    "fundamentals": "基本面",
    "news": "新闻",
}

BLOCK_LABELS_EN = {
    "quote": "quote",
    "daily_bars": "daily bars",
    "technical": "technical",
    "chip": "chip",
    "fundamentals": "fundamentals",
    "news": "news",
}

STATUS_LABELS_ZH = {
    "available": "可用",
    "missing": "缺失",
    "not_supported": "不支持",
    "fallback": "降级",
    "stale": "过期",
    "estimated": "估算",
    "partial": "部分可用",
    "fetch_failed": "抓取失败",
}

STATUS_LABELS_EN = {
    "available": "available",
    "missing": "missing",
    "not_supported": "not supported",
    "fallback": "fallback",
    "stale": "stale",
    "estimated": "estimated",
    "partial": "partial",
    "fetch_failed": "fetch failed",
}

QUALITY_LEVEL_LABELS_ZH = {
    "good": "良好",
    "usable": "可用",
    "limited": "受限",
    "poor": "较差",
}

QUALITY_LEVEL_LABELS_EN = {
    "good": "good",
    "usable": "usable",
    "limited": "limited",
    "poor": "poor",
}

CORE_DEGRADED_STATUSES = {
    "stale",
    "fallback",
    "missing",
    "fetch_failed",
    "partial",
    "estimated",
}

KNOWN_MARKET_PHASES = frozenset(
    {
        "premarket",
        "intraday",
        "lunch_break",
        "closing_auction",
        "postmarket",
        "non_trading",
        "unknown",
    }
)

INTRADAY_MARKET_PHASES = frozenset({"intraday", "lunch_break", "closing_auction"})
CONSERVATIVE_MARKET_PHASES = frozenset({"non_trading", "unknown"})

SENSITIVE_MARKERS = (
    "api_key",
    "access_token",
    "refresh_token",
    "authorization",
    "webhook",
    "password",
    "cookie",
    "secret",
    "token",
    "sendkey",
    "license_key",
)


def normalize_analysis_context_pack_language(report_language: str = "zh") -> str:
    return "en" if str(report_language or "").lower() == "en" else "zh"


def get_analysis_context_pack_block_labels(report_language: str = "zh") -> Dict[str, str]:
    return (
        BLOCK_LABELS_EN
        if normalize_analysis_context_pack_language(report_language) == "en"
        else BLOCK_LABELS_ZH
    )


def iter_analysis_context_pack_block_keys(blocks: Mapping[str, Any]) -> List[str]:
    ordered_keys = [key for key in BLOCK_LABELS_ZH if key in blocks]
    ordered_keys.extend(key for key in blocks if key not in ordered_keys)
    return ordered_keys


def format_analysis_context_pack_prompt_section(
    pack: Any,
    *,
    report_language: str = "zh",
) -> str:
    """Return a low-sensitivity prompt summary for an AnalysisContextPack.

    The renderer intentionally ignores item values. P3 consumes the pack as a
    runtime prompt signal only; P4 exposes a separate low-sensitivity overview,
    not this prompt string or the full pack.
    """
    payload = _pack_to_dict(pack)
    if not payload:
        return ""

    subject = payload.get("subject")
    blocks = payload.get("blocks")
    if not isinstance(subject, Mapping) or not isinstance(blocks, Mapping):
        return ""

    lang = normalize_analysis_context_pack_language(report_language)
    return _format_en(payload) if lang == "en" else _format_zh(payload)


def analysis_context_pack_to_dict(pack: Any) -> Dict[str, Any]:
    if pack is None:
        return {}
    if isinstance(pack, Mapping):
        return dict(pack)
    model_dump = getattr(pack, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json")
        except TypeError:
            dumped = model_dump()
        except Exception:
            return {}
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


_pack_to_dict = analysis_context_pack_to_dict


def _format_zh(payload: Dict[str, Any]) -> str:
    lines = ["", "## 分析上下文包摘要"]
    lines.extend(_subject_lines(payload, lang="zh"))
    block_lines = _block_lines(payload, lang="zh")
    if block_lines:
        lines.append("- 数据块状态：")
        lines.extend(f"  - {line}" for line in block_lines)
    metadata_lines = _metadata_lines(payload, lang="zh")
    if metadata_lines:
        lines.extend(metadata_lines)
    warnings = _list_strings(_nested(payload, "data_quality", "warnings"))
    if warnings:
        lines.append(f"- 数据质量提醒：{_join_text(warnings, lang='zh')}")
    lines.extend(_data_limitation_lines(payload, lang="zh"))
    return "\n".join(lines) + "\n"


def _format_en(payload: Dict[str, Any]) -> str:
    lines = ["", "## Analysis Context Pack Summary"]
    lines.extend(_subject_lines(payload, lang="en"))
    block_lines = _block_lines(payload, lang="en")
    if block_lines:
        lines.append("- Data block status:")
        lines.extend(f"  - {line}" for line in block_lines)
    metadata_lines = _metadata_lines(payload, lang="en")
    if metadata_lines:
        lines.extend(metadata_lines)
    warnings = _list_strings(_nested(payload, "data_quality", "warnings"))
    if warnings:
        lines.append(f"- Data quality notes: {_join_text(warnings, lang='en')}")
    lines.extend(_data_limitation_lines(payload, lang="en"))
    return "\n".join(lines) + "\n"


def _subject_lines(payload: Dict[str, Any], *, lang: str) -> List[str]:
    subject = payload.get("subject") if isinstance(payload.get("subject"), Mapping) else {}
    code = _safe_text(subject.get("code"))
    name = _safe_text(subject.get("stock_name"))
    market = _safe_text(subject.get("market"))
    version = _safe_text(payload.get("pack_version"))

    if lang == "en":
        label = code or "unknown"
        if name:
            label += f" ({name})"
        line = f"- Subject: {label}"
        details = []
        if market:
            details.append(f"market={market}")
        if version:
            details.append(f"pack_version={version}")
        if details:
            line += f"; {', '.join(details)}"
        return [line]

    label = code or "未知标的"
    if name:
        label += f"（{name}）"
    line = f"- 标的：{label}"
    details = []
    if market:
        details.append(f"市场={market}")
    if version:
        details.append(f"pack_version={version}")
    if details:
        line += f"；{'，'.join(details)}"
    return [line]


def _block_lines(payload: Dict[str, Any], *, lang: str) -> List[str]:
    blocks = payload.get("blocks")
    if not isinstance(blocks, Mapping):
        return []

    labels = get_analysis_context_pack_block_labels(lang)
    ordered_keys = iter_analysis_context_pack_block_keys(blocks)

    lines: List[str] = []
    for key in ordered_keys:
        block = blocks.get(key)
        if not isinstance(block, Mapping):
            continue
        status = _safe_text(block.get("status")) or "unknown"
        label = labels.get(key, _safe_text(key))
        parts = [f"{label}: {status}"]

        source = _first_non_empty(
            block.get("source"),
            _first_item_field(block.get("items"), "source"),
        )
        if source:
            parts.append(f"source={source}")

        warnings = _list_strings(block.get("warnings"))
        if warnings:
            warning_label = "warnings" if lang == "en" else "告警"
            parts.append(f"{warning_label}={_join_text(warnings, lang=lang)}")

        reasons = _item_missing_reasons(block.get("items"))
        if reasons:
            reason_label = "missing_reason" if lang == "en" else "missing_reason"
            parts.append(f"{reason_label}={_join_text(reasons, lang=lang)}")

        lines.append("；".join(parts) if lang == "zh" else "; ".join(parts))
    return lines


def _metadata_lines(payload: Dict[str, Any], *, lang: str) -> List[str]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return []
    news_count = metadata.get("news_result_count")
    if news_count is None:
        return []
    return [
        f"- News result count: {news_count}"
        if lang == "en"
        else f"- 新闻结果数：{news_count}"
    ]


def _data_limitation_lines(payload: Dict[str, Any], *, lang: str) -> List[str]:
    lines = ["", "## Data Limitations" if lang == "en" else "## 数据限制"]
    data_quality = payload.get("data_quality")
    if not isinstance(data_quality, Mapping):
        data_quality = {}

    score = _safe_score(data_quality.get("overall_score"))
    level = _safe_text(data_quality.get("level"))
    if score is not None:
        level_text = _quality_level_label(level, lang=lang)
        if lang == "en":
            line = f"- Data quality score: {score}/100"
            if level_text:
                line += f" ({level_text})"
        else:
            line = f"- 数据质量评分：{score}/100"
            if level_text:
                line += f"（{level_text}）"
        lines.append(line)

    limitations = _localized_limitations(
        _list_strings(data_quality.get("limitations")),
        lang=lang,
    )
    if limitations:
        label = "Known limitations" if lang == "en" else "已知限制"
        separator = ": " if lang == "en" else "："
        lines.append(f"- {label}{separator}{_join_text(limitations, lang=lang)}")

    lines.extend(_phase_data_quality_constraint_lines(payload, lang=lang))

    if _has_core_degraded_block(payload):
        if lang == "en":
            lines.append(
                "- Confidence rule: when quote, daily bars, or technical data is "
                "stale, fallback, missing, fetch_failed, partial, or estimated, "
                "the final JSON confidence_level must not be High."
            )
        else:
            lines.append(
                "- 置信度规则：当 quote、daily_bars 或 technical 为 stale、fallback、missing、"
                "fetch_failed、partial 或 estimated 时，最终 JSON 的 confidence_level 不得为高。"
            )

    if lang == "en":
        lines.append(
            "- Analysis rule: missing auxiliary blocks only limit their matching "
            "analysis sections; do not treat missing data itself as bullish or bearish."
        )
        lines.append(
            "- Safety rule: use only status, source, warnings, and missing_reason "
            "from this summary; do not reproduce raw payloads, news body text, "
            "raw trend values, secrets, tokens, or webhooks."
        )
    else:
        lines.append(
            "- 分析规则：辅助数据块缺失只限制对应分析段落，不要把缺失本身解释为利好或利空。"
        )
        lines.append(
            "- 安全规则：只使用本摘要中的 status、source、warnings 和 missing_reason；"
            "不要复述 raw payload、新闻正文、趋势原始值、secret、token 或 webhook。"
        )
    return lines


def _localized_limitations(limitations: List[str], *, lang: str) -> List[str]:
    labels = get_analysis_context_pack_block_labels(lang)
    status_labels = STATUS_LABELS_EN if lang == "en" else STATUS_LABELS_ZH
    result: List[str] = []
    for item in limitations:
        key, separator, status = item.partition(":")
        if not separator:
            result.append(item)
            continue
        normalized_key = key.strip()
        normalized_status = status.strip()
        label = labels.get(normalized_key, _safe_text(normalized_key))
        status_label = status_labels.get(normalized_status, _safe_text(normalized_status))
        if not label or not status_label:
            continue
        result.append(
            f"{label}: {status_label}" if lang == "en" else f"{label}：{status_label}"
        )
    return result[:5]


def _has_core_degraded_block(payload: Dict[str, Any]) -> bool:
    blocks = payload.get("blocks")
    if not isinstance(blocks, Mapping):
        return False
    for key in ("quote", "daily_bars", "technical"):
        block = blocks.get(key)
        if not isinstance(block, Mapping):
            continue
        status = _safe_text(block.get("status"))
        if status in CORE_DEGRADED_STATUSES:
            return True
    return False


def _phase_data_quality_constraint_lines(payload: Dict[str, Any], *, lang: str) -> List[str]:
    if not _has_core_degraded_block(payload):
        return []

    phase = _phase_value(payload)
    if not phase or phase == "postmarket":
        return []

    if lang == "en":
        if phase in INTRADAY_MARKET_PHASES:
            return [
                "- Phase/data rule: intraday judgment is limited by quote, daily-bar, "
                "or technical data quality; state those limitations before making "
                "near-term trading conclusions."
            ]
        if phase == "premarket":
            return [
                "- Phase/data rule: the opening plan is limited by data freshness "
                "or fallback status; do not describe degraded quote data as "
                "today's completed price action."
            ]
        if phase in CONSERVATIVE_MARKET_PHASES:
            return [
                "- Phase/data rule: use only available data conservatively and do "
                "not fill in nonexistent intraday facts."
            ]
        return []

    if phase in INTRADAY_MARKET_PHASES:
        return [
            "- 阶段数据规则：盘中判断受实时行情、日线或技术数据质量限制；"
            "给出短线结论前必须说明这些限制。"
        ]
    if phase == "premarket":
        return [
            "- 阶段数据规则：开盘计划受数据新鲜度或降级状态限制；"
            "不得把降级行情描述成今日走势已经发生。"
        ]
    if phase in CONSERVATIVE_MARKET_PHASES:
        return [
            "- 阶段数据规则：只能保守使用当前可用数据，不得补全不存在的盘中事实。"
        ]
    return []


def _phase_value(payload: Dict[str, Any]) -> str:
    phase_payload = payload.get("phase")
    if not isinstance(phase_payload, Mapping):
        return ""
    phase = _safe_text(phase_payload.get("phase"))
    return phase if phase in KNOWN_MARKET_PHASES else ""


def _quality_level_label(level: str, *, lang: str) -> str:
    labels = QUALITY_LEVEL_LABELS_EN if lang == "en" else QUALITY_LEVEL_LABELS_ZH
    return labels.get(level, "")


def _safe_score(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if 0 <= value <= 100:
        return value
    return None


def _first_item_field(items: Any, field: str) -> Optional[str]:
    if not isinstance(items, Mapping):
        return None
    for item in items.values():
        if not isinstance(item, Mapping):
            continue
        value = _safe_text(item.get(field))
        if value:
            return value
    return None


def _item_missing_reasons(items: Any) -> List[str]:
    if not isinstance(items, Mapping):
        return []
    reasons: List[str] = []
    for item in items.values():
        if not isinstance(item, Mapping):
            continue
        reason = _safe_text(item.get("missing_reason"))
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons[:3]


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _list_strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        text = _safe_text(item)
        if text and text not in result:
            result.append(text)
    return result[:5]


def _first_non_empty(*values: Any) -> Optional[str]:
    for value in values:
        text = _safe_text(value)
        if text:
            return text
    return None


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    lowered = text.lower()
    if any(marker in lowered for marker in SENSITIVE_MARKERS):
        return "[REDACTED]"
    return text


def _join_text(values: Iterable[str], *, lang: str) -> str:
    separator = ", " if lang == "en" else "、"
    return separator.join(values)
