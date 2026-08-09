# -*- coding: utf-8 -*-
"""Decision-first HTML posters for Markdown stock and market reports.

The notification pipeline currently owns a Markdown string, rather than the
original Pydantic/dataclass payload.  This module therefore extracts only the
stable, renderer-generated Markdown contract and turns it into a compact share
card.  Missing fields are hidden; no price, score, signal, or market statistic
is inferred.
"""

from __future__ import annotations

import base64
import html
import mimetypes
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

import markdown2


PROJECT_URL = "https://github.com/ZhuLinsen/daily_stock_analysis"
PROJECT_REPOSITORY = "ZhuLinsen/daily_stock_analysis"
PROJECT_DISPLAY_NAME = "股票智能分析系统"
DEFAULT_XIAOHONGSHU_QR_PATH = "src/assets/share_image/xiaohongshu_qr.jpg"
DEFAULT_XIAOHONGSHU_HANDLE = "@霸天土小豆"
_MARKET_RE = re.compile(
    r"(?:大盘复盘|市场复盘|market\s+(?:review|recap)|시황\s*리뷰)", re.IGNORECASE
)
_MARKET_SCOPE_RE = re.compile(
    r"(?:A股|港股|美股|日股|韩股|中国\s*A주|미국|홍콩|일본|한국|\b(?:cn|hk|us|jp|kr)\b|a[-\s]?share|hong\s+kong|japan|korea|u\.?s\.?)",
    re.IGNORECASE,
)
_DASHBOARD_RE = re.compile(r"(?:决策仪表盘|decision\s+dashboard)", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$", re.MULTILINE)
_QUOTE_RE = re.compile(r"^\s*>\s+(.+?)\s*$", re.MULTILINE)
_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})(?:[ T]\d{2}:\d{2}(?::\d{2})?)?\b")
_MARKET_REGION_REF_RE = re.compile(
    r"^\[dsa-market-region\]:\s+#\s+\(\s*([a-z,]+)\s*\)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SUFFIXED_NUMERIC_CODE_PATTERN = (
    r"(?:\d{6}\.(?:SH|SZ|SS|BJ|KS|KQ)|\d{1,5}\.HK|\d{4,6}\.(?:TWO|TW)|\d{4,5}\.T)"
)
_CODE_RE = re.compile(
    rf"(?:\(|（)?({_SUFFIXED_NUMERIC_CODE_PATTERN}|(?:(?i:sh|sz|bj|hk))?\d{{5,6}}(?:\.[A-Z]{{2}})?|(?<![A-Za-z])[A-Z]{{1,5}}(?:\.[A-Z])?(?![A-Za-z]))(?:\)|）)?",
)
_NUMERIC_CODE_RE = re.compile(
    rf"(?:{_SUFFIXED_NUMERIC_CODE_PATTERN}|(?:(?i:sh|sz|bj|hk))?\d{{5,6}}(?:\.[A-Z]{{2}})?)"
)
_NA_VALUES = {"", "-", "--", "n/a", "na", "none", "null", "暂无", "暂无数据"}
_POSTER_TEXT = {
    "zh": {
        "brand": "AI 股票分析", "stock_subtitle": "个股决策卡 · 结论、点位与风险一图读懂",
        "market_subtitle": "指数、宽度、主线与风险的收盘复盘", "multi_title": "多市场复盘",
        "multi_subtitle": "按市场分段展示指数、主线与风险边界", "dashboard_subtitle": "多股决策摘要",
        "score": "评分", "confidence": "置信度", "trend": "趋势", "core": "核心结论",
        "snapshot": "市场快照", "execution": "执行计划", "technical": "技术参考",
        "next_watch": "下一步观察", "positive_catalysts": "利好催化", "risk_alerts": "风险警报",
        "catalysts_risks": "催化与风险", "no_position": "未持仓", "holding": "已持仓",
        "position": "仓位", "entry": "建仓", "risk_control": "风控", "position_advice": "持仓建议",
        "market_signal": "市场信号", "today_conclusion": "今日结论", "breadth": "市场宽度",
        "dimensions": "信号拆解", "leaders": "强势板块", "laggards": "弱势板块",
        "focus_tag": "关注", "avoid_tag": "回避", "focus": "重点跟踪", "funds": "资金观察",
        "strategy": "明日策略", "risks": "风险提示", "tagline": "让股票研究更简单、更高效",
        "open_source": "开源项目 · GitHub", "xiaohongshu": "小红书",
        "disclaimer": "AI 生成，仅供研究交流，不构成投资建议。市场有风险，决策需谨慎。",
        "source": "数据源",
    },
    "en": {
        "brand": "AI Stock Analysis", "stock_subtitle": "Stock decision card · thesis, levels, and risks",
        "market_subtitle": "Closing review of indices, breadth, themes, and risks", "multi_title": "Multi-market Recap",
        "multi_subtitle": "Indices, themes, and risk boundaries by market", "dashboard_subtitle": "Multi-stock Decision Summary",
        "score": "Score", "confidence": "Confidence", "trend": "Trend", "core": "Core Conclusion",
        "snapshot": "Market Snapshot", "execution": "Execution Plan", "technical": "Technical Reference",
        "next_watch": "Next Watch", "positive_catalysts": "Positive Catalysts", "risk_alerts": "Risk Alerts",
        "catalysts_risks": "Catalysts & Risks", "no_position": "No Position", "holding": "Holding",
        "position": "Position", "entry": "Entry", "risk_control": "Risk Control", "position_advice": "Position Advice",
        "market_signal": "Market Signal", "today_conclusion": "Conclusion", "breadth": "Market Breadth",
        "dimensions": "Signal Breakdown", "leaders": "Leading Sectors", "laggards": "Lagging Sectors",
        "focus_tag": "Watch", "avoid_tag": "Avoid", "focus": "Key Watchlist", "funds": "Fund Flow Watch",
        "strategy": "Next-session Plan", "risks": "Risk Alerts", "tagline": "Make stock research simpler and more efficient",
        "open_source": "Open Source · GitHub", "xiaohongshu": "Xiaohongshu",
        "disclaimer": "AI-generated for research only; not investment advice. Markets involve risk.",
        "source": "Source",
    },
    "ko": {
        "brand": "AI 주식 분석", "stock_subtitle": "종목 의사결정 카드 · 결론, 가격대, 리스크",
        "market_subtitle": "지수, 시장 폭, 주도주와 리스크 마감 리뷰", "multi_title": "다중 시장 리뷰",
        "multi_subtitle": "시장별 지수, 주도주와 리스크 경계", "dashboard_subtitle": "다중 종목 의사결정 요약",
        "score": "점수", "confidence": "신뢰도", "trend": "추세", "core": "핵심 결론",
        "snapshot": "시세 스냅샷", "execution": "실행 계획", "technical": "기술 참고",
        "next_watch": "다음 관찰", "positive_catalysts": "긍정 촉매", "risk_alerts": "리스크 경보",
        "catalysts_risks": "촉매와 리스크", "no_position": "미보유", "holding": "보유 중",
        "position": "포지션", "entry": "진입", "risk_control": "리스크 관리", "position_advice": "포지션 제안",
        "market_signal": "시장 신호", "today_conclusion": "오늘의 결론", "breadth": "시장 폭",
        "dimensions": "신호 분석", "leaders": "강세 섹터", "laggards": "약세 섹터",
        "focus_tag": "관찰", "avoid_tag": "회피", "focus": "주요 관찰", "funds": "자금 흐름",
        "strategy": "다음 거래일 전략", "risks": "리스크 경고", "tagline": "주식 리서치를 더 쉽고 효율적으로",
        "open_source": "오픈소스 · GitHub", "xiaohongshu": "샤오홍슈",
        "disclaimer": "AI 생성 연구 자료이며 투자 조언이 아닙니다. 투자에는 위험이 따릅니다.",
        "source": "데이터 소스",
    },
}
_POSTER_LABELS = {
    "en": {
        "当前/收盘": "Current/Close", "现价": "Current", "涨跌幅": "Change", "涨跌": "Change",
        "量比": "Volume Ratio", "换手率": "Turnover", "换手": "Turnover", "理想买入": "Ideal Entry",
        "确认买入": "Confirmed Entry", "止损": "Stop Loss", "目标": "Target", "均线": "MA Alignment",
        "量能": "Volume", "趋势分": "Trend Score", "MA5乖离": "MA5 Bias", "支撑": "Support", "压力": "Resistance",
        "行动窗口": "Action Window", "下次检查": "Next Check", "上涨": "Advancers", "下跌": "Decliners",
        "涨停": "Limit-up", "跌停": "Limit-down", "成交额": "Turnover", "赚钱效应": "Breadth Score",
        "指数强度": "Index Strength", "涨停结构": "Limit Structure",
    },
    "ko": {
        "当前/收盘": "현재/종가", "现价": "현재가", "涨跌幅": "등락률", "涨跌": "등락",
        "量比": "거래량 비율", "换手率": "회전율", "换手": "회전율", "理想买入": "이상적 진입",
        "确认买入": "확인 진입", "止损": "손절", "目标": "목표", "均线": "이동평균",
        "量能": "거래량", "趋势分": "추세 점수", "MA5乖离": "MA5 이격", "支撑": "지지", "压力": "저항",
        "行动窗口": "행동 구간", "下次检查": "다음 점검", "上涨": "상승", "下跌": "하락",
        "涨停": "상한가", "跌停": "하한가", "成交额": "거래대금", "赚钱效应": "시장 폭 점수",
        "指数强度": "지수 강도", "涨停结构": "상한가 구조",
    },
}
_MARKET_LABEL_PATTERNS = (
    (
        "A股",
        re.compile(
            r"(?:A\s*股|a[-\s]?share|\bcn\s+market\s+(?:review|recap)\b|\bchina\b|중국\s*A주)",
            re.IGNORECASE,
        ),
    ),
    (
        "港股",
        re.compile(
            r"(?:港\s*股|\bhk\s+market\s+(?:review|recap)\b|hong\s+kong|홍콩)",
            re.IGNORECASE,
        ),
    ),
    (
        "美股",
        re.compile(
            r"(?:美\s*股|\b(?:u\.?s\.?|us)\s+market\s+(?:review|recap)\b|united\s+states|미국)",
            re.IGNORECASE,
        ),
    ),
    ("日股", re.compile(r"(?:日\s*股|japan|일본)", re.IGNORECASE)),
    ("韩股", re.compile(r"(?:韩\s*股|korea|한국)", re.IGNORECASE)),
)


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]
    raw_rows: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class ShareImageBranding:
    """Optional deployment-owned social branding for share posters."""

    xiaohongshu_url: str = ""
    xiaohongshu_handle: str = ""
    xiaohongshu_id: str = ""
    xiaohongshu_qr_path: str = ""

    @property
    def has_xiaohongshu(self) -> bool:
        return any((
            self.xiaohongshu_url.strip(),
            self.xiaohongshu_handle.strip(),
            self.xiaohongshu_id.strip(),
            self.xiaohongshu_qr_path.strip(),
        ))


def share_image_branding_from_config(config: object) -> ShareImageBranding:
    """Build poster branding with bundled defaults applied only as an atomic pair."""

    url = str(getattr(config, "share_image_xiaohongshu_url", None) or "").strip()
    handle = str(getattr(config, "share_image_xiaohongshu_handle", None) or "").strip()
    account_id = str(getattr(config, "share_image_xiaohongshu_id", None) or "").strip()
    qr_path = str(getattr(config, "share_image_xiaohongshu_qr_path", None) or "").strip()

    if not any((url, handle, account_id, qr_path)):
        handle = DEFAULT_XIAOHONGSHU_HANDLE
        qr_path = DEFAULT_XIAOHONGSHU_QR_PATH

    return ShareImageBranding(
        xiaohongshu_url=url,
        xiaohongshu_handle=handle,
        xiaohongshu_id=account_id,
        xiaohongshu_qr_path=qr_path,
    )


@dataclass
class StockPoster:
    title: str
    language: str = "zh"
    code: str = ""
    report_date: str = ""
    action: str = ""
    score: str = ""
    trend: str = ""
    confidence: str = ""
    conclusion: str = ""
    snapshot: list[tuple[str, str, str]] = field(default_factory=list)
    sniper: list[tuple[str, str, str]] = field(default_factory=list)
    technical: list[tuple[str, str, str]] = field(default_factory=list)
    catalysts: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    watch_items: list[tuple[str, str, str]] = field(default_factory=list)
    no_position: str = ""
    has_position: str = ""
    position_size: str = ""
    entry_plan: str = ""
    risk_control: str = ""
    data_source: str = ""


@dataclass
class MarketPoster:
    title: str
    language: str = "zh"
    report_date: str = ""
    summary: str = ""
    score: str = ""
    temperature: str = ""
    signal: str = ""
    guidance: str = ""
    reasons: list[str] = field(default_factory=list)
    indices: list[tuple[str, str, str, str]] = field(default_factory=list)
    breadth: list[tuple[str, str, str]] = field(default_factory=list)
    dimensions: list[tuple[str, str, str]] = field(default_factory=list)
    sectors: list[tuple[str, str, str]] = field(default_factory=list)
    laggards: list[tuple[str, str, str]] = field(default_factory=list)
    funds: list[tuple[str, str, str]] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    catalysts: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


@dataclass
class MarketSegment:
    title: str
    markdown: str


def _asset_path(path_value: str) -> Optional[Path]:
    if not path_value.strip():
        return None

    configured = Path(path_value).expanduser()
    candidates = [configured] if configured.is_absolute() else [
        Path.cwd() / configured,
        Path(__file__).resolve().parent.parent / configured,
    ]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root and not configured.is_absolute():
        candidates.append(Path(bundle_root) / configured)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _asset_data_uri(path_value: str) -> str:
    asset_path = _asset_path(path_value)
    if asset_path is None:
        return ""
    try:
        payload = asset_path.read_bytes()
    except OSError:
        return ""
    mime_type = mimetypes.guess_type(asset_path.name)[0] or "image/png"
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _plain(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_`~]", "", text)
    text = re.sub(r"^[^\w\u4e00-\u9fff+\-]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_value(value: object, *, limit: int = 90) -> str:
    text = _plain(value)
    text = re.sub(
        r"^(?:理想买入点|次优买入点|止损位?|目标位?|ideal entry|secondary entry|stop loss|target)\s*[:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    if text.lower() in _NA_VALUES:
        return ""
    if len(text) > limit:
        return text[: limit - 1].rstrip("，,；;。.") + "…"
    return text


def _compact_text(value: object, *, limit: int = 46) -> str:
    """Keep poster copy scannable without changing the underlying report."""

    text = _clean_value(value, limit=max(limit * 2, 90))
    text = re.sub(r"^[✅⚠️❌🔴🟢🟡]+\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ，,；;。")
    if len(text) <= limit:
        return text
    first_clause = re.split(r"[；;。]", text, maxsplit=1)[0].strip()
    if first_clause and len(first_clause) <= limit:
        return first_clause
    return text[: limit - 1].rstrip("，,；;。 ") + "…"


def _nested_mapping(value: object, *keys: str) -> Mapping[str, Any]:
    current: object = value
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return current if isinstance(current, Mapping) else {}


def _poster_language(
    markdown_text: str,
    payload: Optional[Mapping[str, Any]] = None,
) -> str:
    """Resolve poster chrome language from the persisted contract or report."""

    if isinstance(payload, Mapping):
        raw_language = payload.get("report_language") or payload.get("language")
        normalized = str(raw_language or "").strip().lower().replace("_", "-")
        if normalized.startswith("en"):
            return "en"
        if normalized.startswith("ko"):
            return "ko"
        if normalized.startswith("zh"):
            return "zh"
    if re.search(r"[\uac00-\ud7af]", markdown_text or ""):
        return "ko"
    if re.search(
        r"(?:core conclusion|market snapshot|action levels|market (?:review|recap)|major indices)",
        markdown_text or "",
        re.IGNORECASE,
    ):
        return "en"
    return "zh"


def _poster_text(language: str, key: str) -> str:
    return _POSTER_TEXT.get(language, _POSTER_TEXT["zh"]).get(key, _POSTER_TEXT["zh"].get(key, key))


def _poster_label(language: str, label: str) -> str:
    translated = _POSTER_LABELS.get(language, {}).get(label)
    if translated:
        return translated
    if language == "en" and label.startswith("观察 "):
        return label.replace("观察 ", "Watch ", 1)
    if language == "ko" and label.startswith("观察 "):
        return label.replace("观察 ", "관찰 ", 1)
    return label


def _metric_value(
    items: Iterable[tuple[str, str, str]],
    *labels: str,
) -> str:
    for label, value, _tone in items:
        if any(candidate == label for candidate in labels) and value:
            return value
    return ""


def _merge_metrics(
    existing: Iterable[tuple[str, str, str]],
    overlay: Iterable[tuple[str, str, str]],
) -> list[tuple[str, str, str]]:
    """Overlay populated metric cards without erasing Markdown fallbacks."""

    merged = list(existing)
    positions = {label: index for index, (label, _value, _tone) in enumerate(merged)}
    for item in overlay:
        label, value, _tone = item
        if not value:
            continue
        if label in positions:
            merged[positions[label]] = item
        else:
            positions[label] = len(merged)
            merged.append(item)
    return merged


def _merge_compact_list(
    existing: Iterable[object],
    overlay: object,
    *,
    limit_items: int = 2,
    limit_chars: int = 36,
) -> list[str]:
    """Prefer structured list items without erasing Markdown fallback entries."""

    if not isinstance(overlay, list):
        return [str(item) for item in existing if _clean_value(item)][:limit_items]

    merged: list[str] = []
    seen: set[str] = set()
    for source in (overlay, list(existing)):
        for item in source:
            text = _compact_text(item, limit=limit_chars)
            if not text:
                continue
            key = _plain(text).lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(text)
            if len(merged) >= limit_items:
                return merged
    return merged


def _market_light_overlay_allowed(payload: Mapping[str, Any]) -> bool:
    """Skip fabricated market-light snapshots that were persisted as unavailable."""

    return str(payload.get("data_quality") or "").strip().lower() != "unavailable"


def _normalize_index_name(value: object) -> str:
    return _plain(_clean_value(value, limit=28)).strip().lower()


def _normalize_ranking_name(value: object) -> str:
    return _plain(_clean_value(value, limit=28)).strip().lower()


def _merge_index_cards(
    existing: Iterable[tuple[str, str, str, str]],
    overlay: Iterable[Mapping[str, Any]],
    *,
    positive_tone: str,
    negative_tone: str,
) -> list[tuple[str, str, str, str]]:
    """Merge structured index fields into Markdown-parsed cards without dropping fallbacks."""

    merged = list(existing)
    positions = {
        key: index
        for index, (name, _current, _change, _color) in enumerate(merged)
        if (key := _normalize_index_name(name))
    }
    for item in overlay:
        name = _clean_value(item.get("name"), limit=18)
        if not name:
            continue
        current = _number_text(item.get("current"))
        change = _signed_percent(item.get("change_pct"))
        key = _normalize_index_name(name)
        if not key:
            continue
        if key in positions:
            index = positions[key]
            current_name, current_value, current_change, current_color = merged[index]
            merged_change = change or current_change
            if merged_change.startswith("+"):
                color = positive_tone
            elif merged_change.startswith("-"):
                color = negative_tone
            else:
                color = current_color
            merged[index] = (
                name or current_name,
                current or current_value,
                merged_change,
                color,
            )
            continue
        if not (current and change) or len(merged) >= 4:
            continue
        merged.append(
            (
                name,
                current,
                change,
                positive_tone if change.startswith("+") else negative_tone if change.startswith("-") else "",
            )
        )
        positions[key] = len(merged) - 1
    return merged[:4]


def _merge_sector_rankings(
    existing: Iterable[tuple[str, str, str]],
    overlay: Iterable[Mapping[str, Any]],
    *,
    positive_tone: str,
    negative_tone: str,
    default_tone: str,
) -> list[tuple[str, str, str]]:
    """Merge structured sector rows into Markdown rankings without dropping fallbacks."""

    merged = list(existing)
    positions = {
        key: index
        for index, (name, _change, _tone) in enumerate(merged)
        if (key := _normalize_ranking_name(name))
    }
    for offset, item in enumerate(overlay):
        name = _clean_value(item.get("name"), limit=18)
        change = _signed_percent(item.get("change_pct"))
        if not name:
            continue
        key = _normalize_ranking_name(name)
        target_index = positions.get(key) if key else None
        if target_index is None and change and offset < len(merged):
            target_index = offset
        if target_index is not None:
            current_name, current_change, current_tone = merged[target_index]
            current_key = _normalize_ranking_name(current_name)
            merged_change = change or current_change
            if merged_change.startswith("+"):
                tone = positive_tone
            elif merged_change.startswith("-"):
                tone = negative_tone
            else:
                tone = current_tone or default_tone
            merged[target_index] = (
                name or current_name,
                merged_change,
                tone,
            )
            if current_key and current_key != key and positions.get(current_key) == target_index:
                positions.pop(current_key, None)
            if key:
                positions[key] = target_index
            continue
        if len(merged) >= 3:
            continue
        merged.append(
            (
                name,
                change,
                positive_tone if change.startswith("+") else negative_tone if change.startswith("-") else default_tone,
            )
        )
        if key:
            positions[key] = len(merged) - 1
    return merged[:3]


def _number_text(value: object, *, suffix: str = "") -> str:
    if value is None or isinstance(value, bool):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _clean_value(value, limit=18)
    rendered = f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{rendered}{suffix}"


def _compact_turnover(value: object, unit: object) -> str:
    """Render large CNY turnover figures without forcing narrow cards to wrap."""

    unit_text = _clean_value(unit, limit=8)
    try:
        number = float(value)
    except (TypeError, ValueError):
        amount = _number_text(value)
        return f"{amount}{unit_text}" if amount else ""
    if unit_text in {"亿", "亿元"} and abs(number) >= 10000:
        return f"{number / 10000:.2f}".rstrip("0").rstrip(".") + "万亿"
    return f"{_number_text(number)}{unit_text}"


def _signed_percent(value: object) -> str:
    if value is None or isinstance(value, bool):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = _clean_value(value, limit=18)
        return text if "%" in text else f"{text}%" if text else ""
    return f"{number:+.2f}%"


def _price_tokens(value: object) -> list[str]:
    text = _plain(value)
    # Indicator labels such as MA5/MA10 are not prices; nearby parenthesized
    # values (for example ``MA10（55.13）``) remain eligible.
    return re.findall(r"(?<![A-Za-z\d])(\d+(?:\.\d+)?)(?!\d|%)", text)


def _compact_sniper_value(key: str, value: object) -> str:
    text = _clean_value(value, limit=120)
    if not text:
        return ""
    if key == "ideal_buy" and any(token in text for token in ("暂无", "暂不", "不满足")):
        return "等待企稳"
    prices = _price_tokens(text)
    if not prices:
        return _compact_text(text, limit=18)
    if key == "take_profit" and len(prices) >= 2:
        return f"{prices[0]}–{prices[1]}"
    return prices[0]


def _compact_position(value: object, *, holding: bool) -> str:
    text = _clean_value(value, limit=150)
    if not text:
        return ""
    prices = _price_tokens(text)
    if holding and prices:
        stop_match = re.search(r"跌破\s*(\d+(?:\.\d+)?)", text)
        reduce_at = next((price for price in prices if price != (stop_match.group(1) if stop_match else "")), "")
        parts = []
        if "减仓" in text:
            parts.append(f"反弹至 {reduce_at} 附近减仓" if reduce_at else "反弹减仓")
        if stop_match:
            parts.append(f"跌破 {stop_match.group(1)} 止损")
        if parts:
            return "；".join(parts)
    if not holding:
        if "等待" in text or "企稳" in text:
            levels = " / ".join(prices[:2])
            return f"等待 {levels} 附近企稳" if levels else "等待右侧企稳信号"
        if "不" in text and any(term in text for term in ("建仓", "接", "买入")):
            return "暂不建仓"
    return _compact_text(text, limit=40)


def _escape(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _extract_sections(markdown_text: str) -> list[tuple[str, str, int]]:
    matches = list(_HEADING_RE.finditer(markdown_text or ""))
    sections: list[tuple[str, str, int]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        sections.append((_plain(match.group(2)), markdown_text[start:end].strip(), len(match.group(1))))
    return sections


def _section(markdown_text: str, *terms: str) -> str:
    matches = list(_HEADING_RE.finditer(markdown_text or ""))
    for index, match in enumerate(matches):
        title = _plain(match.group(2)).lower()
        if not any(term.lower() in title for term in terms):
            continue
        level = len(match.group(1))
        end = len(markdown_text)
        for following in matches[index + 1 :]:
            if len(following.group(1)) <= level:
                end = following.start()
                break
        return markdown_text[match.end() : end].strip()
    return ""


def _parse_tables(markdown_text: str) -> list[Table]:
    lines = (markdown_text or "").splitlines()
    tables: list[Table] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip().startswith("|"):
            index += 1
            continue
        block: list[str] = []
        while index < len(lines) and lines[index].strip().startswith("|"):
            block.append(lines[index].strip())
            index += 1
        if len(block) < 2:
            continue
        raw_cells = [[cell.strip() for cell in row.strip("|").split("|")] for row in block]
        if not all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in raw_cells[1]):
            continue
        cells = [
            [_clean_value(cell, limit=140) for cell in row.strip("|").split("|")]
            for row in block
        ]
        width = len(cells[0])
        rows = [row[:width] + [""] * max(0, width - len(row)) for row in cells[2:]]
        tables.append(Table(headers=cells[0], rows=rows, raw_rows=raw_cells[2:]))
    return tables


def _table_map(table: Table) -> dict[str, str]:
    return {
        _plain(row[0]).lower(): _clean_value(row[1], limit=120)
        for row in table.rows
        if len(row) >= 2 and _plain(row[0])
    }


def _find_table(markdown_text: str, *header_terms: str) -> Optional[Table]:
    for table in _parse_tables(markdown_text):
        header = " ".join(table.headers).lower()
        body = " ".join(" ".join(row) for row in table.rows).lower()
        if all(term.lower() in f"{header} {body}" for term in header_terms):
            return table
    return None


def _mapped_value(mapping: dict[str, str], *labels: str) -> str:
    for key, value in mapping.items():
        if any(label.lower() in key for label in labels) and _clean_value(value):
            return _clean_value(value)
    return ""


def _opposite_color(color: str) -> str:
    if color == "green":
        return "red"
    if color == "red":
        return "green"
    return ""


def _marker_color(raw_change: str) -> str:
    if "🟢" in (raw_change or ""):
        return "green"
    if "🔴" in (raw_change or ""):
        return "red"
    return ""


def _positive_color_from_change(raw_change: str, change: str) -> str:
    marker_color = _marker_color(raw_change)
    if not marker_color:
        return ""
    normalized_change = re.sub(r"[🟢🔴⚪\s]", "", change or "")
    return _opposite_color(marker_color) if normalized_change.startswith("-") else marker_color


def _ranking_change_tone(change: str, *, positive_tone: str, negative_tone: str, default_tone: str) -> str:
    normalized_change = (change or "").strip()
    if normalized_change.startswith("+"):
        return positive_tone
    if normalized_change.startswith("-"):
        return negative_tone
    return default_tone


def _has_meaningful_section(markdown_text: str, *terms: str) -> bool:
    section = _section(markdown_text, *terms)
    if not section:
        return False
    cleaned = _clean_value(section, limit=400)
    if not cleaned:
        return False
    for boilerplate in (
        "建议仅供参考，不构成投资建议",
        "仅供研究交流，不构成投资建议",
        "does not constitute investment advice",
    ):
        cleaned = cleaned.replace(boilerplate, "").strip()
    return bool(cleaned)


def _meaningful_market_subsection_count(markdown_text: str) -> int:
    count = 0
    for _title, body, level in _extract_sections(markdown_text):
        if level == 3 and _clean_value(body, limit=400):
            count += 1
    return count


def _labeled_value(text: str, *labels: str, limit: int = 100) -> str:
    joined = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:\*{{0,2}}(?:{joined})\*{{0,2}})\s*[:：]\s*(.+?)(?=\s*\||\n|$)",
        text or "",
        flags=re.IGNORECASE,
    )
    return _clean_value(match.group(1), limit=limit) if match else ""


def _labeled_line(text: str, *labels: str, limit: int = 100) -> str:
    joined = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:\*{{0,2}}(?:{joined})\*{{0,2}})\s*[:：]\s*(.+?)(?=\n|$)",
        text or "",
        flags=re.IGNORECASE,
    )
    return _clean_value(match.group(1), limit=limit) if match else ""


def _list_after_label(text: str, *labels: str, limit: int = 3) -> list[str]:
    joined = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:\*{{0,2}}[^\n]*(?:{joined})[^\n]*\*{{0,2}})\s*[:：]?\s*\n(?P<body>.*?)(?=\n\s*\*{{1,2}}[^\n]+\*{{1,2}}\s*[:：]|\n#|\Z)",
        text or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    items = []
    for line in match.group("body").splitlines():
        cleaned = _clean_value(re.sub(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)", "", line), limit=72)
        if cleaned:
            items.append(cleaned)
        if len(items) >= limit:
            break
    return items


def _section_items(text: str, *, limit: int = 3) -> list[str]:
    items: list[str] = []
    for line in (text or "").splitlines():
        if not re.match(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)", line):
            continue
        cleaned = _clean_value(re.sub(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)", "", line), limit=88)
        if cleaned and "不构成投资建议" not in cleaned:
            items.append(cleaned)
        if len(items) >= limit:
            break
    return items


def _sentences(text: str, *, limit: int = 2) -> list[str]:
    clean = _plain(re.sub(r"^\s*(?:[-*+]\s+|\d+[.)、]\s*)", "", text or "", flags=re.MULTILINE))
    clean = re.sub(r"#{1,4}\s*", "", clean)
    pieces = re.split(r"(?<=[。！？!?])\s*", clean)
    result = [_clean_value(piece, limit=88) for piece in pieces if _clean_value(piece, limit=88)]
    return result[:limit]


def _extract_date(markdown_text: str, fallback: date) -> str:
    match = _DATE_RE.search(markdown_text or "")
    return match.group(1) if match else fallback.isoformat()


def _market_label(text: str) -> str:
    scope = _plain(text)
    for label, pattern in _MARKET_LABEL_PATTERNS:
        if pattern.search(scope):
            return label
    return ""


def _market_region_hint(markdown_text: str) -> str:
    match = _MARKET_REGION_REF_RE.search(markdown_text or "")
    return match.group(1).strip().lower() if match else ""


def _market_label_for_region(region: str) -> str:
    return {
        "cn": "A股",
        "hk": "港股",
        "us": "美股",
        "jp": "日股",
        "kr": "韩股",
    }.get((region or "").strip().lower(), "")


def _stock_heading_entry(raw_title: str) -> Optional[tuple[str, str]]:
    def _heading_name(fragment: str) -> str:
        name = _plain(fragment).strip(" -—()（）")
        return re.sub(r"\b(?:分析报告|analysis report)$", "", name, flags=re.IGNORECASE).strip()

    def _is_parenthesized(match: re.Match[str]) -> bool:
        start, end = match.span(1)
        return start > 0 and raw_title[start - 1] in "(（" and end < len(raw_title) and raw_title[end] in ")）"

    trailing_candidate: Optional[tuple[str, str]] = None
    leading_candidate: Optional[tuple[str, str]] = None
    for match in _CODE_RE.finditer(raw_title):
        code = match.group(1).upper()
        name = _heading_name(raw_title[: match.start()])
        if name:
            if _is_parenthesized(match):
                return name, code
            if leading_candidate is None:
                leading_candidate = (name, code)
            continue
        if _NUMERIC_CODE_RE.fullmatch(code):
            trailing_name = _heading_name(raw_title[match.end() :])
            if trailing_name and trailing_candidate is None:
                trailing_candidate = (trailing_name, code)
    return trailing_candidate or leading_candidate


def _stock_headings(markdown_text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for raw_title, _body, level in _extract_sections(markdown_text):
        if level > 2 or _MARKET_RE.search(raw_title) or _DASHBOARD_RE.search(raw_title):
            continue
        entry = _stock_heading_entry(raw_title)
        if entry:
            found.append(entry)
    return found


def _is_market_review_title(title: str) -> bool:
    return bool(_MARKET_RE.search(_plain(title)))


def _has_market_scope(title: str) -> bool:
    return bool(_MARKET_SCOPE_RE.search(_plain(title)))


def _market_segments(markdown_text: str) -> list[MarketSegment]:
    top_level_matches = [
        match
        for match in _HEADING_RE.finditer(markdown_text or "")
        if len(match.group(1)) == 1
    ]
    matches = [match for match in top_level_matches if _is_market_review_title(match.group(2))]
    if len(matches) < 2:
        return []
    if top_level_matches and matches[0].start() == top_level_matches[0].start():
        first_title = matches[0].group(2)
        if not _has_market_scope(first_title):
            scoped_matches = [match for match in top_level_matches if _has_market_scope(match.group(2))]
            if len(scoped_matches) >= 2:
                matches = scoped_matches

    segments: list[MarketSegment] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
        segments.append(
            MarketSegment(
                title=_plain(match.group(2)),
                markdown=markdown_text[match.start() : end].strip(),
            )
        )
    return segments


def _stock_data(markdown_text: str, generated_on: date) -> StockPoster:
    headings = _stock_headings(markdown_text)
    if headings:
        name, code = headings[0]
    else:
        first_title = next((title for title, _body, _level in _extract_sections(markdown_text)), "个股分析")
        entry = _stock_heading_entry(first_title)
        if entry:
            name, code = entry
        else:
            match = _CODE_RE.search(first_title)
            if match and match.start() == 0:
                # US ticker-only titles (and titles containing escaped HTML) read
                # better as one title than as an empty name plus a detached code.
                code = ""
                name = _plain(first_title)
            else:
                code = match.group(1).upper() if match else ""
                name = _plain(first_title[: match.start()] if match else first_title)
            name = re.sub(r"(?:分析报告|analysis report)$", "", name, flags=re.IGNORECASE).strip()

    score_match = re.search(r"(?:评分|score)\s*[:：]?\s*\*{0,2}(\d{1,3})", markdown_text, re.IGNORECASE)
    core = _section(markdown_text, "核心结论", "core conclusion", "核心判断")
    action_terms = (
        "买入", "加仓", "持有", "观望", "减仓", "卖出", "回避", "警戒",
        "buy", "add", "hold", "watch", "reduce", "sell", "avoid", "alert",
    )
    action_value = next(
        (
            candidate
            for candidate in (
                _clean_value(raw_candidate, limit=18)
                for raw_candidate in re.findall(
                    r"\*\*([^*\n]+)\*\*\s*[:：]",
                    core or markdown_text,
                    re.IGNORECASE,
                )
            )
            if any(term in candidate.lower() for term in action_terms)
        ),
        "",
    )
    quote_trend_match = re.search(
        r"^\s*>\s+.*?(?:评分|score)\s*[:：]?\s*\*{0,2}\d{1,3}\*{0,2}\s*\|\s*([^\n|]+)",
        markdown_text,
        re.IGNORECASE | re.MULTILINE,
    )
    trend_match = re.search(r"\*\*[^\n]+?\*\*\s*\|\s*([^\n]+)", core)
    conclusion = _labeled_value(core, "一句话决策", "One-line Decision", limit=110)
    if not conclusion:
        match = re.search(r"\*\*[^\n]+?\*\*\s*[:：]\s*(.+)", core)
        conclusion = _clean_value(match.group(1), limit=110) if match else ""

    poster = StockPoster(
        title=name or "个股分析",
        language=_poster_language(markdown_text),
        code=code,
        report_date=_extract_date(markdown_text, generated_on),
        action=action_value,
        score=score_match.group(1) if score_match else "",
        trend=(
            _clean_value(quote_trend_match.group(1), limit=16)
            if quote_trend_match
            else _clean_value(trend_match.group(1), limit=16) if trend_match else ""
        ),
        conclusion=conclusion,
    )

    snapshot_section = _section(markdown_text, "市场快照", "当日行情", "market snapshot", "시세 스냅샷")
    snapshot_map: dict[str, str] = {}
    for table in _parse_tables(snapshot_section):
        if len(table.rows) == 1:
            snapshot_map.update(
                {_plain(header).lower(): _clean_value(value) for header, value in zip(table.headers, table.rows[0])}
            )
        snapshot_map.update(_table_map(table))
    current = _mapped_value(snapshot_map, "当前价", "current price", "price") or _mapped_value(
        snapshot_map, "收盘价", "收盘", "close"
    )
    change = _mapped_value(snapshot_map, "涨跌幅", "change %", "change pct")
    ratio = _mapped_value(snapshot_map, "量比", "volume ratio")
    turnover = _mapped_value(snapshot_map, "换手率", "turnover rate")
    for label, value, tone in (
        ("当前/收盘", current, "primary"),
        ("涨跌幅", change, "up" if not change.startswith("-") else "down"),
        ("量比", ratio, "neutral"),
        ("换手率", turnover, "neutral"),
    ):
        if value:
            poster.snapshot.append((label, value, tone))
    poster.data_source = _mapped_value(snapshot_map, "数据源", "行情来源", "source")

    data_section = _section(markdown_text, "数据透视", "data view", "技术面", "technicals")
    data_map: dict[str, str] = {}
    for table in _parse_tables(data_section):
        data_map.update(_table_map(table))
    ma = _labeled_value(data_section, "均线排列", "MA Alignment", limit=42)
    ma = next((label for label in ("多头排列", "空头排列") if label in ma), _compact_text(ma, limit=16))
    volume_ratio = _labeled_line(data_section, "量能", "成交量", "Volume", limit=64)
    support = _mapped_value(data_map, "支撑位", "support")
    resistance = _mapped_value(data_map, "压力位", "resistance")
    for label, value, tone in (
        ("均线", ma, "positive" if "多头" in ma.lower() or "bull" in ma.lower() else "neutral"),
        ("量能", volume_ratio, "neutral"),
        ("支撑", support, "positive"),
        ("压力", resistance, "negative"),
    ):
        if value:
            poster.technical.append((label, value, tone))

    battle = _section(markdown_text, "作战计划", "battle plan", "操作计划", "操作点位", "action levels")
    sniper_table = _find_table(battle, "理想") or _find_table(battle, "ideal")
    sniper_values: dict[str, str] = {}
    if sniper_table:
        if len(sniper_table.headers) >= 3 and len(sniper_table.rows) == 1:
            sniper_values = {
                _plain(header).lower(): _clean_value(value, limit=62)
                for header, value in zip(sniper_table.headers, sniper_table.rows[0])
            }
        else:
            sniper_values = _table_map(sniper_table)
    for labels, display, tone in (
        (("理想买入点", "ideal entry"), "理想买入", "buy"),
        (("次优买入点", "secondary entry"), "次优买入", "secondary"),
        (("止损位", "stop loss"), "止损", "stop"),
        (("目标位", "target"), "目标", "target"),
    ):
        raw_value = _mapped_value(sniper_values, *labels)
        key = {
            "理想买入": "ideal_buy",
            "次优买入": "secondary_buy",
            "止损": "stop_loss",
            "目标": "take_profit",
        }[display]
        value = _compact_sniper_value(key, raw_value)
        if value:
            poster.sniper.append(("确认买入" if display == "次优买入" else display, value, tone))

    info = _section(markdown_text, "重要信息", "key updates", "消息面", "news flow")
    poster.catalysts = [
        _compact_text(item, limit=36)
        for item in _list_after_label(info, "利好催化", "positive catalysts")[:2]
    ]
    poster.risks = [
        _compact_text(item, limit=36)
        for item in _list_after_label(info, "风险警报", "risk alerts")[:2]
    ]
    if not poster.risks:
        poster.risks = [
            _compact_text(item, limit=36)
            for item in _section_items(
                _section(markdown_text, "风险提示", "risk warning", "risk alerts"), limit=2
            )
        ]

    position_table = _find_table(core, "持仓") or _find_table(core, "position")
    if position_table:
        position_map = _table_map(position_table)
        poster.no_position = _mapped_value(position_map, "空仓", "no position")
        poster.has_position = _mapped_value(position_map, "持仓者", "holding")
    position_section = _section(markdown_text, "持仓建议", "position advice")
    if not poster.no_position:
        poster.no_position = _labeled_value(position_section, "空仓者", "no position", limit=90)
    if not poster.has_position:
        poster.has_position = _labeled_value(position_section, "持仓者", "holding", limit=90)
    poster.no_position = _compact_position(poster.no_position, holding=False)
    poster.has_position = _compact_position(poster.has_position, holding=True)
    return poster


def _stock_data_from_payload(
    payload: Mapping[str, Any],
    markdown_text: str,
    generated_on: date,
) -> StockPoster:
    """Prefer the analysis JSON contract and retain Markdown as a field fallback."""

    poster = _stock_data(markdown_text, generated_on)
    poster.language = _poster_language(markdown_text, payload)
    dashboard = payload.get("dashboard")
    if not isinstance(dashboard, Mapping):
        dashboard = {}

    core = _nested_mapping(dashboard, "core_conclusion")
    data_view = _nested_mapping(dashboard, "data_perspective")
    price = _nested_mapping(data_view, "price_position")
    volume = _nested_mapping(data_view, "volume_analysis")
    trend = _nested_mapping(data_view, "trend_status")
    intelligence = _nested_mapping(dashboard, "intelligence")
    battle = _nested_mapping(dashboard, "battle_plan")
    sniper = _nested_mapping(battle, "sniper_points")
    position_advice = _nested_mapping(core, "position_advice")
    phase = _nested_mapping(dashboard, "phase_decision")

    poster.title = _clean_value(payload.get("name"), limit=30) or poster.title
    poster.code = _clean_value(payload.get("code"), limit=16) or poster.code
    poster.action = _clean_value(
        payload.get("action_label") or payload.get("operation_advice"), limit=12
    ) or poster.action
    score = payload.get("sentiment_score")
    if score is not None:
        poster.score = _number_text(score)
    poster.trend = _clean_value(payload.get("trend_prediction"), limit=16) or poster.trend
    poster.confidence = _clean_value(
        payload.get("confidence_level") or dashboard.get("confidence_level"),
        limit=10,
    )
    poster.conclusion = _compact_text(core.get("one_sentence"), limit=54) or poster.conclusion

    persisted_snapshot = _nested_mapping(payload, "market_snapshot")
    current = _number_text(payload.get("current_price") or price.get("current_price"))
    if not current:
        current = _clean_value(
            persisted_snapshot.get("price") or persisted_snapshot.get("close"),
            limit=18,
        )
    current = current or _metric_value(poster.snapshot, "现价", "当前/收盘")
    change = _signed_percent(payload.get("change_pct"))
    if not change:
        change = _clean_value(persisted_snapshot.get("pct_chg"), limit=18)
    change = change or _metric_value(poster.snapshot, "涨跌", "涨跌幅")
    ratio = _number_text(volume.get("volume_ratio"))
    if not ratio:
        ratio = _clean_value(persisted_snapshot.get("volume_ratio"), limit=18)
    ratio = ratio or _metric_value(poster.snapshot, "量比")
    turnover = _number_text(volume.get("turnover_rate"), suffix="%")
    if not turnover:
        turnover = _clean_value(persisted_snapshot.get("turnover_rate"), limit=18)
    turnover = turnover or _metric_value(poster.snapshot, "换手", "换手率")
    positive_tone = _stock_positive_tone(poster.code)
    negative_tone = _opposite_color(positive_tone)
    poster.snapshot = [
        item for item in (
            ("现价", current, "primary"),
            ("涨跌", change, positive_tone if not change.startswith("-") else negative_tone),
            ("量比", ratio, "neutral"),
            ("换手", turnover, "neutral"),
        ) if item[1]
    ]
    poster.data_source = (
        _clean_value(persisted_snapshot.get("source"), limit=30)
        or poster.data_source
    )

    ma_alignment = _clean_value(trend.get("ma_alignment"), limit=60)
    ma_summary = next(
        (label for label in ("多头排列", "空头排列") if label in ma_alignment),
        _compact_text(ma_alignment, limit=16),
    )
    support = _number_text(price.get("support_level"))
    resistance = _number_text(price.get("resistance_level"))
    trend_score = _number_text(trend.get("trend_score"), suffix="/100")
    bias_ma5 = _signed_percent(price.get("bias_ma5"))
    payload_technical = [
        item for item in (
            ("均线", ma_summary, "positive" if "多头" in ma_summary else "negative" if "空头" in ma_summary else "neutral"),
            ("趋势分", trend_score, _tone_for_score(_number_text(trend.get("trend_score")))),
            ("MA5乖离", bias_ma5, "positive" if not bias_ma5.startswith("-") else "negative"),
            ("支撑", support, "positive"),
            ("压力", resistance, "negative"),
        ) if item[1]
    ]
    existing_technical = poster.technical
    if any(volume.get(key) is not None for key in ("volume_ratio", "turnover_rate")):
        # Ratio/turnover already appear in the snapshot.  Keep the verbose
        # Markdown volume prose only for older/partial payloads that do not
        # carry those exact structured fields.
        existing_technical = [
            item for item in existing_technical if item[0] != "量能"
        ]
    poster.technical = _merge_metrics(existing_technical, payload_technical)

    payload_sniper: list[tuple[str, str, str]] = []
    for key, label, tone in (
        ("ideal_buy", "理想买入", "buy"),
        ("secondary_buy", "确认买入", "secondary"),
        ("stop_loss", "止损", "stop"),
        ("take_profit", "目标", "target"),
    ):
        value = _compact_sniper_value(key, sniper.get(key))
        if value:
            payload_sniper.append((label, value, tone))
    poster.sniper = _merge_metrics(poster.sniper, payload_sniper)

    catalysts = intelligence.get("positive_catalysts")
    risks = intelligence.get("risk_alerts")
    if isinstance(catalysts, list):
        poster.catalysts = _merge_compact_list(poster.catalysts, catalysts)
    if isinstance(risks, list):
        poster.risks = _merge_compact_list(poster.risks, risks)

    watch_conditions = phase.get("watch_conditions")
    payload_watch_items = [
        item for item in (
            ("行动窗口", _compact_text(phase.get("action_window"), limit=24), "primary"),
            ("下次检查", _compact_text(phase.get("next_check_time"), limit=28), "secondary"),
        ) if item[1]
    ]
    if isinstance(watch_conditions, list):
        payload_watch_items.extend(
            (f"观察 {index}", _compact_text(value, limit=31), "warning")
            for index, value in enumerate(watch_conditions[:2], 1)
            if _clean_value(value)
        )
    if payload_watch_items:
        poster.watch_items = payload_watch_items

    poster.no_position = (
        _compact_position(position_advice.get("no_position"), holding=False)
        or poster.no_position
    )
    poster.has_position = (
        _compact_position(position_advice.get("has_position"), holding=True)
        or poster.has_position
    )
    # The full report keeps sizing, entry and risk-control prose.  The share
    # poster intentionally shows only the two user states above.
    poster.position_size = ""
    poster.entry_plan = ""
    poster.risk_control = ""
    return poster


def _market_title(markdown_text: str) -> str:
    first_title = next((title for title, _body, _level in _extract_sections(markdown_text)), "")
    language = _poster_language(markdown_text)
    if language in {"en", "ko"} and _is_market_review_title(first_title):
        return first_title
    market = _market_label(first_title)
    if market:
        return f"{market}市场复盘"
    hinted_market = _market_label_for_region(_market_region_hint(markdown_text))
    if hinted_market:
        return f"{hinted_market}市场复盘"
    market = _market_label(markdown_text[:600])
    if market:
        return f"{market}市场复盘"
    if _is_market_review_title(first_title):
        return first_title
    return "A股市场复盘"


def _parsed_breadth_metrics(overview: str) -> list[tuple[str, str]]:
    metrics: list[tuple[str, str]] = []
    advance_match = re.search(
        r"Advancers\s+([^/;\n]+?)\s*/\s*Decliners\s+([^/;\n]+?)(?:\s*/\s*Flat\s+([^;\n]+?))?(?=$|;|\n)",
        overview or "",
        flags=re.IGNORECASE,
    )
    if advance_match:
        metrics.extend(
            [
                ("上涨", _clean_value(advance_match.group(1), limit=32)),
                ("下跌", _clean_value(advance_match.group(2), limit=32)),
            ]
        )

    limit_match = re.search(
        r"Limit(?:-|\s)?up\s+([^/;\n]+?)\s*/\s*Limit(?:-|\s)?down\s+([^;\n]+?)(?=$|;|\n)",
        overview or "",
        flags=re.IGNORECASE,
    )
    if limit_match:
        metrics.extend(
            [
                ("涨停", _clean_value(limit_match.group(1), limit=32)),
                ("跌停", _clean_value(limit_match.group(2), limit=32)),
            ]
        )

    turnover_match = re.search(
        r"Turnover\s+(.+?)(?=$|;|\n)",
        overview or "",
        flags=re.IGNORECASE,
    )
    if turnover_match:
        metrics.append(("成交额", _clean_value(turnover_match.group(1), limit=48)))
    return [(label, value) for label, value in metrics if value]


def _parse_index_bullets(index_section: str) -> list[tuple[str, str, str, str]]:
    indices: list[tuple[str, str, str, str]] = []
    for line in (index_section or "").splitlines():
        match = re.match(
            r"^\s*[-*+]\s+(?:\*\*)?(?P<name>[^:*]+?)(?:\*\*)?\s*[:：]\s*(?P<current>[^()\n]+?)\s*\((?P<change>[^)\n]+)\)\s*$",
            line,
        )
        if not match:
            continue
        name = _clean_value(match.group("name"), limit=28)
        current = _clean_value(match.group("current"), limit=18)
        change = re.sub(r"\s+", " ", match.group("change")).strip()
        if not (name and current and change):
            continue
        color = _marker_color(change)
        if not color:
            color = "green" if any(marker in change for marker in ("↑", "+")) else "red" if any(marker in change for marker in ("↓", "-")) else ""
        indices.append((name, current, change, color))
        if len(indices) >= 4:
            break
    return indices


def _direction_items(value: object, *, limit: int = 2) -> list[str]:
    """Extract short sector/theme labels from a verbose plan sentence."""

    text = _clean_value(value, limit=220)
    if not text:
        return []
    text = re.sub(r"其[一二三四][、，,:：]?", "", text)
    clauses = [part.strip(" ，,；;") for part in re.split(r"[；;]", text) if part.strip()]
    items: list[str] = []
    for clause in clauses:
        qualified = re.findall(r"的([^，,；;等]{2,20})等", clause)
        candidates = re.findall(
            r"(?:^|[，,])([A-Za-z0-9一-鿿]+(?:、[A-Za-z0-9一-鿿]+)*)等",
            clause,
        )
        if qualified:
            label = qualified[-1]
        elif candidates:
            label = candidates[-1]
        else:
            label = re.split(r"[，,。]", clause, maxsplit=1)[0]
        label = re.sub(r"^(?:关注方向|回避方向)[:：]?", "", label).strip()
        label = _compact_text(label, limit=24)
        if label and label not in items:
            items.append(label)
        if len(items) >= limit:
            break
    return items


def _market_fund_metrics(markdown_text: str) -> list[tuple[str, str, str]]:
    section = _section(markdown_text, "资金与情绪", "fund flows", "liquidity & sentiment")
    if not section:
        return []
    metrics: list[tuple[str, str, str]] = []
    ratio = re.search(r"涨跌比(?:接近|约为|约)?\s*([\d.]+\s*:\s*[\d.]+)", section)
    if ratio:
        metrics.append(("涨跌比", ratio.group(1).replace(" ", ""), "positive"))
    increment = re.search(
        r"较前(?:一交易日|日).*?放量(?:超|逾)?\s*([\d.]+)\s*亿元",
        section,
    )
    if increment:
        metrics.append(("增量成交", f"+{increment.group(1)}亿", "primary"))
    if any(term in section for term in ("科技", "科创", "半导体")) and any(
        term in section for term in ("分歧", "冲高回落", "兑现")
    ):
        metrics.append(("资金风格", "科技主导·高位分歧", "warning"))
    return metrics[:3]


def _market_data(markdown_text: str, generated_on: date) -> MarketPoster:
    overview = _section(markdown_text, "盘面总览", "market summary", "breadth & liquidity", "시장 요약")
    score_match = re.search(
        r"(?:盘面信号|市场信号|market signal|시장 신호)\*{0,2}\s*[:：]\s*(\d{1,3})/100(?:\s*[（(]([^，,)]+)[，,]\s*([^）)]+)[）)])?",
        markdown_text,
        re.IGNORECASE,
    )
    quote = _QUOTE_RE.search(markdown_text)
    poster = MarketPoster(
        title=_market_title(markdown_text),
        language=_poster_language(markdown_text),
        report_date=_extract_date(markdown_text, generated_on),
        summary=_compact_text(quote.group(1), limit=58) if quote else "",
        score=score_match.group(1) if score_match else "",
        temperature=_clean_value(score_match.group(2), limit=12) if score_match and score_match.group(2) else "",
        signal=_clean_value(score_match.group(3), limit=12) if score_match and score_match.group(3) else "",
        guidance=_compact_text(
            _labeled_value(overview, "操作建议", "Guidance", "운용 제안", "가이던스", limit=100),
            limit=52,
        ),
    )
    reason_text = _labeled_value(overview, "信号依据", "Drivers", "신호 근거", "동인", limit=220)
    poster.reasons = [
        _compact_text(item, limit=34)
        for item in re.split(r"[；;]", reason_text)
        if _clean_value(item, limit=72)
    ][:3]
    if not poster.reasons and poster.summary:
        poster.reasons = _sentences(poster.summary, limit=2)

    index_section = _section(markdown_text, "指数结构", "major indices", "index commentary", "주요 지수", "지수 구조")
    index_table = (
        _find_table(index_section, "指数", "涨跌幅")
        or _find_table(index_section, "index", "change")
        or _find_table(index_section, "지수", "등락률")
    )
    positive_color = "green"
    if index_table:
        headers = [header.lower() for header in index_table.headers]
        name_i = next((i for i, value in enumerate(headers) if "指数" in value or "index" in value or "지수" in value), 0)
        current_i = next((i for i, value in enumerate(headers) if "最新" in value or "last" in value or "최신" in value), 1)
        change_i = next((i for i, value in enumerate(headers) if "涨跌幅" in value or "change" in value or "등락률" in value), 2)
        for row_index, row in enumerate(index_table.rows[:4]):
            if len(row) > max(name_i, current_i, change_i):
                raw_change = (
                    index_table.raw_rows[row_index][change_i]
                    if row_index < len(index_table.raw_rows)
                    and len(index_table.raw_rows[row_index]) > change_i
                    else row[change_i]
                )
                color = _marker_color(raw_change)
                if not color:
                    color = "red" if row[change_i].strip().startswith("-") else "green"
                positive_color = _positive_color_from_change(raw_change, row[change_i]) or positive_color
                poster.indices.append((row[name_i], row[current_i], row[change_i], color))
    if not poster.indices:
        poster.indices = _parse_index_bullets(index_section)
        if poster.indices:
            first_change = poster.indices[0][2]
            inferred_positive_color = _positive_color_from_change(first_change, first_change)
            if inferred_positive_color:
                positive_color = inferred_positive_color

    breadth_table = (
        _find_table(overview, "上涨", "成交额")
        or _find_table(overview, "breadth")
        or _find_table(overview, "상승", "거래대금")
    )
    if breadth_table:
        mapping = _table_map(breadth_table)
        advance = _mapped_value(mapping, "上涨/下跌", "advancers", "상승/하락")
        limits = _mapped_value(mapping, "涨停/跌停", "limit-up", "상한가/하한가")
        amount = _mapped_value(mapping, "成交额", "turnover", "거래대금")
        if advance:
            parts = [part.strip() for part in advance.split("/")]
            if parts:
                poster.breadth.append(("上涨", parts[0], positive_color))
            if len(parts) > 1:
                negative_color = "red" if positive_color == "green" else "green"
                poster.breadth.append(("下跌", parts[1], negative_color))
        if limits:
            parts = [part.strip() for part in limits.split("/")]
            if parts:
                poster.breadth.append(("涨停", parts[0], positive_color))
            if len(parts) > 1:
                negative_color = "red" if positive_color == "green" else "green"
                poster.breadth.append(("跌停", parts[1], negative_color))
        if amount:
            poster.breadth.append(("成交额", amount, "primary"))
    if not poster.breadth:
        for label, value in _parsed_breadth_metrics(overview):
            if label == "上涨":
                tone = positive_color
            elif label in {"下跌", "跌停"}:
                tone = "red" if positive_color == "green" else "green"
            elif label == "涨停":
                tone = positive_color
            else:
                tone = "primary"
            poster.breadth.append((label, value, tone))

    sector_section = _section(markdown_text, "板块主线", "sector highlights", "섹터 하이라이트", "주도 섹터")
    sector_table = (
        _find_table(sector_section, "板块", "涨跌幅")
        or _find_table(sector_section, "sector", "change")
        or _find_table(sector_section, "섹터", "등락률")
    )
    if sector_table:
        for row in sector_table.rows[:3]:
            if len(row) >= 3:
                change = _clean_value(row[-1], limit=12)
                poster.sectors.append(
                    (
                        _clean_value(row[-2], limit=20),
                        change,
                        _ranking_change_tone(
                            change,
                            positive_tone=positive_color,
                            negative_tone=_opposite_color(positive_color),
                            default_tone=positive_color,
                        ),
                    )
                )
    sector_tables = [
        table
        for table in _parse_tables(sector_section)
        if any(term in " ".join(table.headers).lower() for term in ("板块", "sector", "섹터"))
    ]
    if len(sector_tables) > 1:
        for row in sector_tables[1].rows[:3]:
            if len(row) >= 3:
                change = _clean_value(row[-1], limit=12)
                poster.laggards.append(
                    (
                        _clean_value(row[-2], limit=20),
                        change,
                        _ranking_change_tone(
                            change,
                            positive_tone=positive_color,
                            negative_tone=_opposite_color(positive_color),
                            default_tone=_opposite_color(positive_color),
                        ),
                    )
                )

    catalyst_section = _section(markdown_text, "消息催化", "news catalysts", "뉴스 촉매")
    poster.catalysts = [
        _compact_text(item, limit=34)
        for item in (_section_items(catalyst_section, limit=2) or _sentences(catalyst_section, limit=2))
    ]
    plan_section = _section(markdown_text, "明日交易计划", "strategy plan", "outlook", "내일 거래 계획", "내일 계획")
    poster.focus = _direction_items(
        _labeled_value(plan_section, "关注方向", "focus", "관심 방향", limit=220)
    )
    poster.avoid = _direction_items(
        _labeled_value(plan_section, "回避方向", "avoid", "회피 방향", limit=220)
    )
    poster.funds = _market_fund_metrics(markdown_text)
    for label in ("结论", "仓位区间", "触发失效条件", "결론", "비중 구간", "무효화 조건"):
        value = _labeled_value(plan_section, label, limit=86)
        if value:
            poster.plan.append(_compact_text(f"{label}：{value}", limit=32))
        if len(poster.plan) >= 3:
            break
    if not poster.plan:
        poster.plan = [
            _compact_text(item, limit=32)
            for item in (_section_items(plan_section, limit=3) or _sentences(plan_section, limit=3))
        ]
    poster.risks = [
        _compact_text(item, limit=34)
        for item in _section_items(
            _section(markdown_text, "风险提示", "risk alerts", "리스크 경보", "리스크 경고"),
            limit=2,
        )
    ]
    return poster


def _market_data_from_payload(
    payload: Mapping[str, Any],
    markdown_text: str,
    generated_on: date,
) -> MarketPoster:
    """Overlay exact market metrics from the persisted market-review payload."""

    poster = _market_data(markdown_text, generated_on)
    poster.language = _poster_language(markdown_text, payload)
    payload_title = _clean_value(payload.get("title"), limit=36)
    if payload_title and not _DATE_RE.match(payload_title):
        poster.title = payload_title
    poster.report_date = _clean_value(payload.get("date"), limit=18) or poster.report_date
    color_scheme = str(payload.get("color_scheme") or "").strip().lower()
    if color_scheme == "red_up":
        positive_tone = "red"
    elif color_scheme == "green_up":
        positive_tone = "green"
    else:
        positive_tone = "green"
        for _name, _current, change, color in poster.indices:
            if not color or not change:
                continue
            positive_tone = _opposite_color(color) if change.strip().startswith("-") else color
            break
    negative_tone = _opposite_color(positive_tone)

    light = payload.get("market_light")
    if isinstance(light, Mapping):
        if _market_light_overlay_allowed(light) and light.get("score") is not None:
            poster.score = _number_text(light.get("score"))
        if _market_light_overlay_allowed(light):
            poster.temperature = _clean_value(light.get("temperature_label"), limit=12) or poster.temperature
            poster.signal = (
                _clean_value(light.get("label"), limit=12)
                or poster.signal
                or poster.temperature
            )
            dimensions = light.get("dimensions")
            if isinstance(dimensions, Mapping):
                for key, label in (
                    ("breadth", "赚钱效应"),
                    ("index", "指数强度"),
                    ("limit", "涨停结构"),
                ):
                    dimension = dimensions.get(key)
                    if (
                        not isinstance(dimension, Mapping)
                        or dimension.get("score") is None
                        or dimension.get("available") is False
                    ):
                        continue
                    score = _number_text(dimension.get("score"))
                    try:
                        numeric_score = float(dimension.get("score"))
                    except (TypeError, ValueError):
                        numeric_score = 0
                    tone = "positive" if numeric_score >= 70 else "warning" if numeric_score >= 50 else "negative"
                    poster.dimensions.append((label, f"{score}/100", tone))

    indices = payload.get("indices")
    if isinstance(indices, list):
        structured_indices = [item for item in indices[:4] if isinstance(item, Mapping)]
        if structured_indices:
            poster.indices = _merge_index_cards(
                poster.indices,
                structured_indices,
                positive_tone=positive_tone,
                negative_tone=negative_tone,
            )

    breadth = payload.get("breadth")
    if isinstance(breadth, Mapping):
        amount = _compact_turnover(
            breadth.get("total_amount"),
            breadth.get("turnover_unit"),
        )
        exact_breadth = [
            item for item in (
                ("上涨", _number_text(breadth.get("up_count")), positive_tone),
                ("下跌", _number_text(breadth.get("down_count")), negative_tone),
                ("涨停", _number_text(breadth.get("limit_up_count")), "hot"),
                ("跌停", _number_text(breadth.get("limit_down_count")), negative_tone),
                ("成交额", amount, "primary"),
            ) if item[1]
        ]
        if exact_breadth:
            poster.breadth = _merge_metrics(poster.breadth, exact_breadth)

    sectors = payload.get("sectors")
    top_sectors = sectors.get("top") if isinstance(sectors, Mapping) else None
    if isinstance(top_sectors, list):
        structured_top = [item for item in top_sectors[:3] if isinstance(item, Mapping)]
        if structured_top:
            poster.sectors = _merge_sector_rankings(
                poster.sectors,
                structured_top,
                positive_tone=positive_tone,
                negative_tone=negative_tone,
                default_tone=positive_tone,
            )
    bottom_sectors = sectors.get("bottom") if isinstance(sectors, Mapping) else None
    if isinstance(bottom_sectors, list):
        structured_bottom = [item for item in bottom_sectors[:3] if isinstance(item, Mapping)]
        if structured_bottom:
            poster.laggards = _merge_sector_rankings(
                poster.laggards,
                structured_bottom,
                positive_tone=positive_tone,
                negative_tone=negative_tone,
                default_tone=negative_tone,
            )
    return poster


def _should_keep_market_fallback(markdown_text: str, data: MarketPoster) -> bool:
    expected_sections = (
        (
            _has_meaningful_section(markdown_text, "盘面总览", "market summary", "breadth & liquidity", "시장 요약"),
            any((data.score, data.guidance, data.reasons, data.summary, data.breadth)),
        ),
        (
            _has_meaningful_section(markdown_text, "指数结构", "major indices", "index commentary", "주요 지수", "지수 구조"),
            bool(data.indices),
        ),
        (
            _has_meaningful_section(markdown_text, "板块主线", "sector highlights", "섹터 하이라이트", "주도 섹터"),
            bool(data.sectors),
        ),
        (
            _has_meaningful_section(markdown_text, "消息催化", "news catalysts", "뉴스 촉매"),
            bool(data.catalysts),
        ),
        (
            _has_meaningful_section(markdown_text, "明日交易计划", "strategy plan", "outlook", "내일 거래 계획", "내일 계획"),
            bool(data.plan),
        ),
        (
            _has_meaningful_section(markdown_text, "风险提示", "risk alerts", "리스크 경보", "리스크 경고"),
            bool(data.risks),
        ),
    )
    if any(expected and not populated for expected, populated in expected_sections):
        return True
    mapped_subsections = sum(1 for expected, populated in expected_sections if expected and populated)
    unmapped_subsections = max(
        0, _meaningful_market_subsection_count(markdown_text) - mapped_subsections
    )
    # A normal report may contain one explanatory detail section such as
    # “资金与情绪”.  That should not duplicate the entire report in a share
    # poster.  Keep the full fallback only when most localized sections remain
    # outside the structured contract.
    return unmapped_subsections > max(1, mapped_subsections)


def _tone_for_action(action: str) -> str:
    normalized = (action or "").lower()
    if any(term in normalized for term in ("买", "加仓", "buy", "add")):
        return "positive"
    if any(term in normalized for term in ("卖", "减仓", "回避", "sell", "reduce", "avoid")):
        return "negative"
    return "primary"


def _tone_for_score(score: str) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "primary"
    if value > 60:
        return "positive"
    if value < 40:
        return "negative"
    return "warning"


def _tone_for_trend(trend: str) -> str:
    normalized = (trend or "").lower()
    if any(term in normalized for term in ("看多", "bull", "uptrend")):
        return "positive"
    if any(term in normalized for term in ("看空", "bear", "downtrend")):
        return "negative"
    return "primary"


def _stock_positive_tone(code: str) -> str:
    normalized = (code or "").strip().upper()
    red_up_market = bool(
        re.fullmatch(r"\d{6}", normalized)
        or re.match(r"^(?:SH|SZ|BJ|HK)\d+", normalized)
        or re.search(r"\.(?:SH|SS|SZ|BJ|HK|T|TW|TWO|KS|KQ)$", normalized)
    )
    return "red" if red_up_market else "green"


def _metric_cards(
    items: Iterable[tuple[str, str, str]],
    class_name: str = "",
    *,
    language: str = "zh",
) -> str:
    cards = []
    for label, value, tone in items:
        classes = " ".join(part for part in ("metric", class_name, tone) if part)
        cards.append(
            f'<div class="{_escape(classes)}"><span>{_escape(_poster_label(language, label))}</span><strong>{_escape(value)}</strong></div>'
        )
    return "".join(cards)


def _list_html(items: Iterable[str], empty: str = "") -> str:
    values = [value for value in items if value]
    if not values:
        return f'<p class="muted">{_escape(empty)}</p>' if empty else ""
    return "<ul>" + "".join(f"<li>{_escape(value)}</li>" for value in values) + "</ul>"


def _section_html(title: str, icon: str, content: str, class_name: str = "") -> str:
    if not content:
        return ""
    return f'<section class="poster-section {class_name}"><h2><b>{_escape(icon)}</b>{_escape(title)}</h2>{content}</section>'


def _render_markdown_fragment(markdown_text: str) -> str:
    return markdown2.markdown(
        markdown_text,
        extras=["tables", "fenced-code-blocks", "break-on-newline", "cuddled-lists"],
        safe_mode="escape",
    )


def _stock_body(data: StockPoster, fallback_html: str) -> str:
    language = data.language
    tone = _tone_for_action(data.action)
    score_tone = _tone_for_score(data.score)
    trend_tone = _tone_for_trend(data.trend)
    score = f'<div class="signal-score {score_tone}"><span>{_escape(_poster_text(language, "score"))}</span><strong>{_escape(data.score)}</strong><small>/100</small></div>' if data.score else ""
    confidence = f'<small>{_escape(_poster_text(language, "confidence"))} {_escape(data.confidence)}</small>' if data.confidence else ""
    trend = f'<div class="signal-trend {trend_tone}"><span>{_escape(_poster_text(language, "trend"))}</span><strong>{_escape(data.trend)}</strong>{confidence}</div>' if data.trend else ""
    action = f'<div class="action-chip {tone}">{_escape(data.action)}</div>' if data.action else ""
    signal_row = f'<div class="signal-row">{action}{score}{trend}</div>' if action or score or trend else ""
    conclusion = _section_html(_poster_text(language, "core"), "◎", f'<div class="conclusion">{_escape(data.conclusion)}</div>') if data.conclusion else ""
    snapshot = _section_html(_poster_text(language, "snapshot"), "▥", f'<div class="metric-grid snapshot-grid">{_metric_cards(data.snapshot, language=language)}</div>') if data.snapshot else ""
    sniper = _section_html(_poster_text(language, "execution"), "◎", f'<div class="metric-grid sniper-grid sniper-table">{_metric_cards(data.sniper, "sniper", language=language)}</div>') if data.sniper else ""
    technical = _section_html(_poster_text(language, "technical"), "⌁", f'<div class="metric-grid technical-grid">{_metric_cards(data.technical, language=language)}</div>') if data.technical else ""
    watch = _section_html(
        _poster_text(language, "next_watch"),
        "✓",
        '<div class="watch-grid">' + "".join(
            f'<div class="watch-card {tone_name}"><span>{_escape(_poster_label(language, label))}</span><p>{_escape(value)}</p></div>'
            for label, value, tone_name in data.watch_items
        ) + "</div>",
    ) if data.watch_items else ""
    insight_cards = ""
    if data.catalysts:
        insight_cards += f'<div class="insight positive"><h3>{_escape(_poster_text(language, "positive_catalysts"))}</h3>{_list_html(data.catalysts)}</div>'
    if data.risks:
        insight_cards += f'<div class="insight negative"><h3>{_escape(_poster_text(language, "risk_alerts"))}</h3>{_list_html(data.risks)}</div>'
    insights = _section_html(_poster_text(language, "catalysts_risks"), "!", f'<div class="two-column">{insight_cards}</div>') if insight_cards else ""
    position_rows = ""
    for label, value, tone_name in (
        (_poster_text(language, "no_position"), data.no_position, "primary"),
        (_poster_text(language, "holding"), data.has_position, "warning"),
        (_poster_text(language, "position"), data.position_size, "positive"),
    ):
        if value:
            position_rows += f'<div class="position-row"><span class="pill {tone_name}">{label}</span><p>{_escape(value)}</p></div>'
    if data.entry_plan:
        position_rows += f'<div class="position-row"><span class="pill primary">{_escape(_poster_text(language, "entry"))}</span><p>{_escape(data.entry_plan)}</p></div>'
    if data.risk_control:
        position_rows += f'<div class="position-row"><span class="pill negative">{_escape(_poster_text(language, "risk_control"))}</span><p>{_escape(data.risk_control)}</p></div>'
    positions = _section_html(_poster_text(language, "position_advice"), "▣", f'<div class="position-box">{position_rows}</div>') if position_rows else ""
    structured = any((signal_row, conclusion, snapshot, sniper, technical, watch, insights, positions))
    fallback = f'<section class="report-fallback"><article class="report-content">{fallback_html}</article></section>' if not structured else ""
    return f"{signal_row}{conclusion}{snapshot}{sniper}{technical}{watch}{insights}{positions}{fallback}"


def _market_body(data: MarketPoster, fallback_html: str, markdown_text: str) -> str:
    language = data.language
    signal = ""
    if data.score:
        signal = (
            '<section class="market-signal">'
            f'<div class="signal-main"><span>{_escape(_poster_text(language, "market_signal"))}</span>'
            f'<strong>{_escape(data.score)}</strong><small>/100</small></div>'
            f'<div class="market-label">{_escape(data.signal or data.temperature)}</div>'
            f'<div class="signal-guidance"><span>{_escape(_poster_text(language, "today_conclusion"))}</span><p>{_escape(data.guidance or data.summary)}</p></div>'
            '</section>'
        )
    elif any((data.guidance, data.summary, data.reasons)):
        overview_parts: list[str] = []
        conclusion = data.guidance or data.summary
        if conclusion:
            overview_parts.append(f'<div class="conclusion">{_escape(conclusion)}</div>')
        if data.reasons:
            overview_parts.append(_list_html(data.reasons))
        signal = _section_html(
            _poster_text(language, "today_conclusion"),
            "◎",
            "".join(overview_parts),
        )
    indices = ""
    if data.indices:
        cards = []
        for name, current, change, color in data.indices:
            cards.append(f'<div class="index-card"><span>{_escape(name)}</span><strong class="{color}">{_escape(change)}</strong><small>{_escape(current)}</small></div>')
        indices = f'<div class="index-grid">{"".join(cards)}</div>'
    breadth = _section_html(_poster_text(language, "breadth"), "↕", f'<div class="metric-grid breadth-grid">{_metric_cards(data.breadth, language=language)}</div>') if data.breadth else ""
    dimensions = _section_html(
        _poster_text(language, "dimensions"),
        "◫",
        f'<div class="metric-grid dimension-grid">{_metric_cards(data.dimensions, language=language)}</div>',
    ) if data.dimensions else ""
    sector_rows = "".join(
        f'<div class="ranking-row"><b>{index:02d}</b><span>{_escape(name)}</span><strong class="{_escape(tone)}">{_escape(change)}</strong></div>'
        for index, (name, change, tone) in enumerate(data.sectors, 1)
    )
    laggard_rows = "".join(
        f'<div class="ranking-row lagging"><b>{index:02d}</b><span>{_escape(name)}</span><strong class="{_escape(tone)}">{_escape(change)}</strong></div>'
        for index, (name, change, tone) in enumerate(data.laggards, 1)
    )
    sectors = _section_html(_poster_text(language, "leaders"), "◆", f'<div class="ranking">{sector_rows}</div>') if sector_rows else ""
    laggards = _section_html(_poster_text(language, "laggards"), "◇", f'<div class="ranking">{laggard_rows}</div>') if laggard_rows else ""
    sector_dual = (
        f'<div class="market-two-column"><div class="market-left">{sectors}</div>'
        f'<div class="market-right">{laggards}</div></div>'
        if sectors or laggards else ""
    )
    focus_rows = "".join(
        f'<div class="focus-row"><b>{_escape(_poster_text(language, "focus_tag"))}</b><span>{_escape(value)}</span></div>'
        for value in data.focus
    ) + "".join(
        f'<div class="focus-row avoid"><b>{_escape(_poster_text(language, "avoid_tag"))}</b><span>{_escape(value)}</span></div>'
        for value in data.avoid
    )
    fund_rows = "".join(
        f'<div class="fund-row {_escape(tone)}"><span>{_escape(_poster_label(language, label))}</span><strong>{_escape(value)}</strong></div>'
        for label, value, tone in data.funds
    )
    focus = _section_html(_poster_text(language, "focus"), "◎", f'<div class="focus-list">{focus_rows}</div>') if focus_rows else ""
    funds = _section_html(_poster_text(language, "funds"), "↗", f'<div class="fund-list">{fund_rows}</div>') if fund_rows else ""
    detail_dual = (
        f'<div class="market-two-column market-details"><div class="market-left">{focus}</div>'
        f'<div class="market-right">{funds}</div></div>'
        if focus or funds else ""
    )
    catalysts = _section_html(
        _poster_text(language, "positive_catalysts"),
        "✦",
        _list_html(data.catalysts),
    ) if data.catalysts else ""
    plan = _section_html(_poster_text(language, "strategy"), "✓", _list_html(data.plan), "strategy-strip") if data.plan else ""
    risks = _section_html(_poster_text(language, "risks"), "!", _list_html(data.risks), "risk-strip") if data.risks else ""
    structured = any((signal, indices, breadth, dimensions, sector_dual, detail_dual, catalysts, plan, risks))
    keep_fallback = not structured or _should_keep_market_fallback(markdown_text, data)
    fallback = f'<section class="report-fallback"><article class="report-content">{fallback_html}</article></section>' if keep_fallback else ""
    return f"{signal}{indices}{breadth}{dimensions}{sector_dual}{detail_dual}{catalysts}{plan}{risks}{fallback}"


def _generic_body(report_html: str) -> str:
    return f'<section class="report-fallback"><article class="report-content">{report_html}</article></section>'


def _market_region_for_segment(segment: MarketSegment) -> str:
    label = _market_label(segment.title) or _market_label(segment.markdown[:500])
    return {
        "A股": "cn",
        "港股": "hk",
        "美股": "us",
        "日股": "jp",
        "韩股": "kr",
    }.get(label, "")


def _multi_market_body(
    segments: list[MarketSegment],
    generated_on: date,
    structured_payload: Optional[Mapping[str, Any]] = None,
) -> str:
    blocks: list[str] = []
    markets = structured_payload.get("markets") if isinstance(structured_payload, Mapping) else None
    market_payloads = markets if isinstance(markets, Mapping) else {}
    unused_regions = [
        region for region in ("cn", "hk", "us", "jp", "kr")
        if isinstance(market_payloads.get(region), Mapping)
    ]
    for segment in segments:
        body_markdown = _HEADING_RE.sub("", segment.markdown, count=1).strip()
        fallback_html = _render_markdown_fragment(body_markdown)
        region = _market_region_for_segment(segment)
        payload = market_payloads.get(region) if region else None
        if not isinstance(payload, Mapping) and unused_regions:
            payload = market_payloads.get(unused_regions[0])
            region = unused_regions[0]
        if region in unused_regions:
            unused_regions.remove(region)
        data = (
            _market_data_from_payload(payload, segment.markdown, generated_on)
            if isinstance(payload, Mapping)
            else _market_data(segment.markdown, generated_on)
        )
        title = data.title or segment.title
        blocks.append(
            f'<section class="poster-section market-region-title"><h2><b>◎</b>{_escape(title)}</h2></section>'
            f"{_market_body(data, fallback_html, segment.markdown)}"
        )
    return "".join(blocks)


def _safe_web_url(value: str) -> str:
    url = value.strip()
    return url if re.match(r"^https?://", url, re.IGNORECASE) else ""


def _xiaohongshu_card(branding: ShareImageBranding, language: str) -> str:
    if not branding.has_xiaohongshu:
        return ""

    label = _poster_text(language, "xiaohongshu")
    account_parts = [part for part in (
        branding.xiaohongshu_handle.strip(),
        f"ID {branding.xiaohongshu_id.strip()}" if branding.xiaohongshu_id.strip() else "",
    ) if part]
    account = " · ".join(account_parts) or branding.xiaohongshu_url.strip()
    qr_data_uri = _asset_data_uri(branding.xiaohongshu_qr_path)
    qr_alt = f"{label}二维码" if language == "zh" else f"{label} QR"
    image = (
        f'<div class="qr-frame"><img src="{qr_data_uri}" alt="{_escape(qr_alt)}"></div>'
        if qr_data_uri else ""
    )
    url = _safe_web_url(branding.xiaohongshu_url)
    if image and url:
        image = f'<a href="{_escape(url)}">{image}</a>'
    account_markup = (
        f'<span><b>{_escape(label)}</b>{(" " + _escape(account)) if account else ""}</span>'
    )
    if url:
        account_markup = f'<a class="social-link" href="{_escape(url)}">{account_markup}</a>'
    return (
        f'<div class="qr-card{(" text-only" if not image else "")}">{image}'
        f'{account_markup}</div>'
    )


def _footer(branding: ShareImageBranding, source_line: str, language: str) -> str:
    social_card = _xiaohongshu_card(branding, language)
    brand_class = "footer-brand" if social_card else "footer-brand full"
    return f"""
    <footer class="poster-footer">
      <div class="{brand_class}">
        <div class="footer-title"><strong>DSA</strong><span>{_escape(PROJECT_DISPLAY_NAME)}</span></div>
        <small>{_escape(_poster_text(language, "tagline"))}</small>
        <div class="repo-line">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 3.64 0 8.13c0 3.59 2.29 6.64 5.47 7.71.4.08.55-.18.55-.39 0-.19-.01-.83-.01-1.51-2.01.38-2.53-.5-2.69-.96-.09-.23-.48-.96-.82-1.15-.28-.15-.68-.53-.01-.54.63-.01 1.08.59 1.23.83.72 1.23 1.87.88 2.33.67.07-.53.28-.88.51-1.08-1.78-.21-3.64-.91-3.64-4.02 0-.89.31-1.62.82-2.19-.08-.21-.36-1.04.08-2.16 0 0 .67-.22 2.2.84A7.45 7.45 0 0 1 8 3.91c.68 0 1.36.09 2 .27 1.53-1.06 2.2-.84 2.2-.84.44 1.12.16 1.95.08 2.16.51.57.82 1.3.82 2.19 0 3.12-1.87 3.81-3.65 4.02.29.25.54.74.54 1.5 0 1.08-.01 1.95-.01 2.22 0 .22.15.47.55.39A8.15 8.15 0 0 0 16 8.13C16 3.64 12.42 0 8 0Z"/></svg>
          <div><em>{_escape(_poster_text(language, "open_source"))}</em><b>{_escape(PROJECT_REPOSITORY)}</b></div>
        </div>
      </div>
      {social_card}
    </footer>
    <div class="disclaimer">{_escape(_poster_text(language, "disclaimer"))}{_escape(source_line)}</div>
    """


def build_share_image_html(
    markdown_text: str,
    *,
    generated_on: Optional[date] = None,
    structured_payload: Optional[Mapping[str, Any]] = None,
    branding: Optional[ShareImageBranding] = None,
) -> str:
    """Build a deterministic 1080px stock, market, or dashboard share poster.

    Structured analysis JSON is preferred when available; stable Markdown remains
    the compatibility fallback. Unknown fields are omitted. Optional social
    branding is supplied by deployment config and never fetched at render time.
    """

    generated = generated_on or date.today()
    language = _poster_language(markdown_text, structured_payload)
    headings = _extract_sections(markdown_text)
    first_title = headings[0][0] if headings else "股票智能分析报告"
    stock_headings = _stock_headings(markdown_text)
    market_segments = _market_segments(markdown_text)
    candidate_market_titles = headings[:2]
    is_market = any(
        level <= 2 and _is_market_review_title(title)
        for title, _body, level in candidate_market_titles
    )
    is_single_stock = len(stock_headings) == 1
    report_kind = "market" if is_market else "stock" if is_single_stock else "dashboard"

    body_markdown = _HEADING_RE.sub("", markdown_text, count=1).strip()
    fallback_html = _render_markdown_fragment(body_markdown)
    stamp = _extract_date(markdown_text, generated)
    source_line = ""
    if report_kind == "market":
        if market_segments:
            title = _poster_text(language, "multi_title")
            subtitle = _poster_text(language, "multi_subtitle")
            content = _multi_market_body(
                market_segments,
                generated,
                structured_payload=structured_payload,
            )
        else:
            data = (
                _market_data_from_payload(structured_payload, markdown_text, generated)
                if isinstance(structured_payload, Mapping)
                else _market_data(markdown_text, generated)
            )
            title = data.title
            language = data.language
            subtitle = data.summary or _poster_text(language, "market_subtitle")
            content = _market_body(data, fallback_html, markdown_text)
    elif report_kind == "stock":
        data = (
            _stock_data_from_payload(structured_payload, markdown_text, generated)
            if isinstance(structured_payload, Mapping)
            else _stock_data(markdown_text, generated)
        )
        title = data.title
        language = data.language
        subtitle = _poster_text(language, "stock_subtitle")
        content = _stock_body(data, fallback_html)
        if data.data_source:
            source_line = (
                f" 数据源：{data.data_source}。"
                if language == "zh"
                else f" {_poster_text(language, 'source')}: {data.data_source}."
            )
    else:
        title = first_title
        subtitle = _poster_text(language, "dashboard_subtitle")
        content = _generic_body(fallback_html)

    poster_branding = branding or ShareImageBranding()

    return f"""<!DOCTYPE html>
<html lang="{'en' if language == 'en' else 'ko' if language == 'ko' else 'zh-CN'}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=1080, initial-scale=1">
  <title>{_escape(title)}</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; width: 1080px; background: #eef4fd; }}
    body {{ color: #081b40; font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "PingFang SC", "Microsoft YaHei", Arial, sans-serif; font-size: 22px; line-height: 1.5; -webkit-font-smoothing: antialiased; }}
    .poster {{ width: 1080px; padding: 38px 34px 24px; border: 1px solid #aebdd4; border-radius: 28px; background: radial-gradient(circle at 92% 6%, rgba(48,123,255,.15), transparent 260px), linear-gradient(180deg,#fff 0%,#fbfdff 78%,#eef5ff 100%); }}
    .poster-header {{ display: table; width: 100%; margin-bottom: 28px; }}
    .brand, .meta {{ display: table-cell; vertical-align: middle; }}
    .brand {{ font-size: 26px; font-weight: 650; }} .brand strong {{ margin: 0 14px 0 13px; font-size: 43px; letter-spacing: -2px; }} .brand em {{ color: #8b9bb3; font-style: normal; }}
    .brand-mark {{ display: inline-block; width: 39px; height: 40px; vertical-align: middle; white-space: nowrap; }} .brand-mark i {{ display:inline-block; width:8px; margin-right:4px; border-radius:5px 5px 2px 2px; vertical-align:bottom; }} .brand-mark i:nth-child(1){{height:18px;background:#ff3b30}} .brand-mark i:nth-child(2){{height:28px;background:#00a86b}} .brand-mark i:nth-child(3){{height:40px;margin:0;background:#1677ff}}
    .meta {{ text-align:right; color:#3e506c; font-size:21px; }} .date-chip {{ display:inline-block; padding:10px 17px; border:1px solid #aec4e7; border-radius:16px; background:rgba(255,255,255,.85); }}
    .hero {{ min-height: 145px; margin-bottom: 24px; padding: 10px 10px 20px; }} .hero h1 {{ margin:0 0 8px; max-width:820px; font-size:68px; line-height:1.15; letter-spacing:-3px; }} .hero .code {{ margin-left:18px; color:#1768e8; font-size:38px; letter-spacing:0; white-space:nowrap; }} .hero p {{ margin:0; max-width:810px; color:#3c4f70; font-size:24px; }}
    .signal-row {{ display:table; width:100%; margin:0 0 26px; border-spacing:14px 0; table-layout:fixed; }} .signal-row>div {{ display:table-cell; height:88px; padding:14px 20px; border:1px solid #cad8ec; border-radius:16px; vertical-align:middle; background:rgba(255,255,255,.92); }} .signal-row .action-chip {{ width:24%; color:#fff; text-align:center; font-size:38px; font-weight:850; background:#1974ed; box-shadow:0 10px 24px rgba(25,116,237,.22); }} .signal-row .action-chip.positive{{background:linear-gradient(135deg,#118a55,#19b66f)}} .signal-row .action-chip.negative{{background:linear-gradient(135deg,#e63b45,#ff5a52)}} .signal-score span,.signal-trend span{{margin-right:14px;font-weight:750}} .signal-score strong{{color:#0da15d;font-size:41px}} .signal-score.warning strong{{color:#f59e0b}} .signal-score.negative strong{{color:#ed343d}} .signal-score small{{color:#53627b;font-size:20px}} .signal-trend strong{{color:#1768e8;font-size:30px}} .signal-trend>small{{display:block;margin-top:3px;color:#64748b;font-size:15px}} .signal-trend.positive strong{{color:#0a9c58}} .signal-trend.negative strong{{color:#ed343d}}
    .poster-section {{ margin:0 10px 25px; }} .poster-section h2 {{ margin:0 0 12px; font-size:29px; line-height:1.3; }} .poster-section h2 b {{ display:inline-block; width:34px; color:#176ff2; font-family:Arial,sans-serif; }}
    .conclusion {{ padding:16px 24px; border:1.5px solid #72a8ff; border-radius:14px; color:#13294e; background:linear-gradient(90deg,#f9fcff,#eff6ff); font-size:25px; font-weight:600; }}
    .metric-grid {{ display:table; width:100%; border-spacing:12px 0; table-layout:fixed; }} .metric {{ display:table-cell; height:112px; padding:14px 12px; border:1px solid #d0dced; border-radius:16px; text-align:center; vertical-align:middle; background:rgba(255,255,255,.92); }} .metric span {{ display:block; margin-bottom:5px; color:#233653; font-weight:700; }} .metric strong {{ display:block; color:#10254b; font-size:31px; line-height:1.25; overflow-wrap:break-word; word-break:normal; }} .metric.primary strong{{color:#1768e8}} .metric.up strong,.metric.positive strong,.metric.buy strong,.metric.green strong{{color:#0a9c58}} .metric.down strong,.metric.negative strong,.metric.stop strong,.metric.red strong{{color:#ed343d}} .metric.hot strong{{color:#ff4a36}} .metric.secondary strong{{color:#1768e8}} .metric.target strong{{color:#ff8a00}} .sniper-grid .metric{{height:112px}} .sniper-grid .metric strong{{font-size:29px}} .technical-grid .metric strong{{font-size:26px}}
    .watch-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 12px}} .watch-card{{min-height:78px;padding:12px 16px;border:1px solid #d2deef;border-left:4px solid #1768e8;border-radius:13px;background:linear-gradient(145deg,#f7faff,#fff)}} .watch-card.warning{{border-left-color:#f59e0b}} .watch-card.secondary{{border-left-color:#6d5dfc}} .watch-card span{{display:block;color:#52647f;font-size:16px;font-weight:750}} .watch-card p{{margin:4px 0 0;color:#152a4d;font-size:18px;font-weight:650;line-height:1.35}} .two-column {{ display:table; width:100%; border-spacing:12px 0; table-layout:fixed; }} .insight {{ display:table-cell; width:50%; padding:15px 20px; border:1px solid #d5e1f0; border-radius:15px; background:#fff; vertical-align:top; }} .insight.positive{{background:linear-gradient(145deg,#f1fff7,#fff)}} .insight.negative{{background:linear-gradient(145deg,#fff4f4,#fff)}} .insight h3{{margin:0 0 6px;color:#0a9c58;font-size:23px}} .insight.negative h3{{color:#ed343d}} .insight ul{{font-size:19px}} ul{{margin:4px 0;padding-left:25px}} li{{margin:5px 0}}
    .position-box {{ overflow:hidden; border:1px solid #d5e1f0; border-radius:15px; background:#fff; }} .position-row {{ display:table; width:100%; padding:10px 18px; border-bottom:1px solid #e5ecf5; }} .position-row:last-child{{border:0}} .position-row .pill,.position-row p{{display:table-cell;vertical-align:middle}} .position-row .pill{{width:92px;padding:5px 10px;border-radius:8px;color:#fff;text-align:center;font-size:18px;font-weight:750;background:#357dea}} .position-row .pill.warning{{background:#f2a20c}} .position-row .pill.positive{{background:#13a365}} .position-row .pill.negative{{background:#eb3e47}} .position-row p{{margin:0;padding-left:16px}}
    .market-signal {{ display:table; width:calc(100% - 20px); min-height:154px; margin:0 10px 24px; padding:20px 27px; border:1px solid #bfd4f4; border-radius:22px; background:linear-gradient(135deg,#fff 0%,#f1f7ff 58%,#ecfff6 100%); box-shadow:0 12px 34px rgba(18,71,153,.08); table-layout:fixed; }} .signal-main,.market-label,.signal-guidance{{display:table-cell;vertical-align:middle}} .signal-main{{width:25%}} .market-signal span{{display:block;font-weight:750}} .market-signal strong{{color:#1768e8;font-size:74px;line-height:1.05}} .market-signal small{{font-size:30px}} .market-label{{width:19%;padding:9px 12px;border:1px solid #23ad69;border-radius:10px;color:#0d9958;text-align:center;font-size:23px;font-weight:800;background:#f1fff7}} .signal-guidance{{width:56%;padding-left:28px;color:#233653}} .signal-guidance span{{color:#1768e8;font-size:18px;letter-spacing:1px}} .signal-guidance p{{margin:6px 0 0;font-size:23px;font-weight:700;line-height:1.45}}
    .index-grid {{ display:table; width:100%; margin:0 0 24px; border-spacing:10px 0; table-layout:fixed; }} .index-card{{display:table-cell;padding:16px 18px;border:1px solid #d0dced;border-radius:18px;background:linear-gradient(160deg,#fff,#f6f9ff);box-shadow:0 8px 22px rgba(25,78,153,.05)}} .index-card span,.index-card small{{display:block}} .index-card span{{font-weight:750}} .index-card strong{{display:block;margin:8px 0 0;font-size:35px}} .index-card strong.red{{color:#ed3f36}} .index-card strong.green{{color:#0a9c58}} .index-card small{{color:#3d506f;font-size:19px}}
    .breadth-grid .metric{{background:linear-gradient(160deg,#fff,#f7faff)}} .breadth-grid .metric strong{{font-size:29px}} .dimension-grid .metric{{height:94px;background:linear-gradient(145deg,#f7faff,#fff)}} .dimension-grid .metric strong{{font-size:33px}} .market-two-column{{display:table;width:calc(100% - 20px);margin:0 10px 24px;border-spacing:8px 0;table-layout:fixed}} .market-left,.market-right{{display:table-cell;width:50%;vertical-align:top}} .market-two-column .poster-section{{min-height:238px;margin:0;padding:20px 22px;border:1px solid #d3dfef;border-radius:19px;background:linear-gradient(160deg,#fff,#f8fbff)}} .ranking-row{{display:table;width:100%;padding:13px 0;border-bottom:1px solid #e6edf6}} .ranking-row:last-child{{border:0}} .ranking-row>*{{display:table-cell;vertical-align:middle}} .ranking-row b{{width:44px;color:#fff;border-radius:9px;text-align:center;background:linear-gradient(135deg,#1677ff,#6a5cff)}} .ranking-row:nth-child(2) b{{background:linear-gradient(135deg,#ff8a00,#ffb020)}} .ranking-row:nth-child(3) b{{background:linear-gradient(135deg,#12a66a,#37c98a)}} .ranking-row span{{padding-left:13px;font-weight:700}} .ranking-row strong{{text-align:right}} .ranking-row strong.red{{color:#ed3f36}} .ranking-row strong.green{{color:#0a9c58}} .ranking-row.lagging b{{background:linear-gradient(135deg,#64748b,#94a3b8)}} .market-details .poster-section{{min-height:214px}} .focus-row,.fund-row{{display:table;width:100%;padding:10px 0;border-bottom:1px solid #e6edf6}} .focus-row:last-child,.fund-row:last-child{{border:0}} .focus-row b,.focus-row span,.fund-row span,.fund-row strong{{display:table-cell;vertical-align:middle}} .focus-row b{{width:66px;color:#fff;border-radius:8px;text-align:center;background:#1677ff}} .focus-row.avoid b{{background:#ef4444}} .focus-row span{{padding-left:14px;font-weight:700}} .fund-row span{{color:#52647f}} .fund-row strong{{text-align:right;color:#1768e8}} .fund-row.positive strong{{color:#0a9c58}} .fund-row.warning strong{{color:#f59e0b}} .strategy-strip{{padding:16px 22px;border:1px solid #cbdcf4;border-radius:17px;background:linear-gradient(90deg,#f6faff,#fff)}} .strategy-strip ul{{display:table;width:100%;padding-left:25px}} .strategy-strip li{{display:table-cell;width:33.33%;padding-right:20px;font-size:19px;vertical-align:top}}
    .risk-strip{{padding:16px 22px;border:1px solid #ffc5c5;border-radius:17px;background:linear-gradient(90deg,#fff3f3,#fffafa)}} .risk-strip h2{{color:#e7373f}} .risk-strip ul{{display:table;width:100%;padding-left:25px}} .risk-strip li{{display:table-cell;width:50%;padding-right:24px;font-size:19px}}
    .report-fallback {{ margin:0 10px 26px; padding:24px 28px; border:1px solid #d5e1f0; border-radius:18px; background:#fff; }} .report-content{{overflow-wrap:anywhere}} .report-content h1,.report-content h2,.report-content h3{{color:#153d78;overflow-wrap:anywhere;word-break:break-word}} .report-content h2{{font-size:29px}} .report-content h3{{font-size:25px}} .report-content p,.report-content li,.report-content th,.report-content td,.report-content blockquote,.report-content a{{overflow-wrap:anywhere;word-break:break-word}} .report-content table{{width:100%;border-collapse:collapse;font-size:19px;table-layout:fixed}} .report-content th,.report-content td{{padding:10px;border:1px solid #dbe4f1}} .report-content th{{background:#eef4fc}} .report-content pre{{max-width:100%;margin:16px 0;padding:16px 18px;overflow-x:auto;border-radius:14px;background:#f4f7fc;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}} .report-content code{{white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word}} .report-content blockquote{{margin:15px 0;padding:12px 18px;border-left:5px solid #4385ef;background:#f3f7fd}}
    .poster-footer {{ display:table; width:100%; margin-top:18px; padding:14px 34px 5px; border-top:1px solid #ccdaec; table-layout:fixed; }} .footer-brand,.qr-card{{display:table-cell;vertical-align:middle}} .footer-brand{{width:74%;padding-left:6px}} .footer-brand.full{{width:100%}} .footer-title{{display:flex;align-items:baseline;gap:15px}} .footer-title strong{{color:#1768e8;font-size:43px;font-style:italic;line-height:1}} .footer-title span{{font-size:24px;font-weight:800}} .footer-brand>small{{display:block;margin-top:4px;color:#536683;font-size:16px}} .repo-line{{display:flex;align-items:center;gap:9px;margin-top:11px;color:#111827}} .repo-line svg{{width:25px;height:25px;flex:none;fill:currentColor}} .repo-line div{{min-width:0}} .repo-line em,.repo-line b{{display:block;font-style:normal}} .repo-line em{{margin-bottom:1px;color:#64748b;font-size:12px;letter-spacing:.6px}} .repo-line b{{font-size:16px;line-height:1.15;white-space:nowrap}} .qr-card{{width:26%;text-align:center;font-size:16px;font-weight:750;line-height:1.2}} .qr-card.text-only{{padding-left:18px}} .qr-card .social-link{{color:inherit;text-decoration:none}} .qr-card span b{{color:#ff2442}} .qr-frame{{width:132px;height:132px;margin:0 auto 5px;padding:4px;border:1px solid #d3deed;border-radius:13px;background:#fff}} .qr-frame img{{display:block;width:122px;height:122px;object-fit:contain}} .disclaimer{{margin:6px -34px -24px;padding:8px 34px;color:#285b9d;font-size:14px;text-align:center;background:#eaf3ff}}
  </style>
</head>
<body>
  <main class="poster {report_kind}">
    <header class="poster-header"><div class="brand"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span><strong>DSA</strong><em>|</em> {_escape(_poster_text(language, "brand"))}</div><div class="meta"><span class="date-chip">{_escape(stamp)}</span></div></header>
    <section class="hero"><h1>{_escape(title)}{f'<span class="code">{_escape(data.code)}</span>' if report_kind == 'stock' and data.code else ''}</h1><p>{_escape(subtitle)}</p></section>
    {content}
    {_footer(poster_branding, source_line, language)}
  </main>
</body>
</html>"""


__all__ = [
    "DEFAULT_XIAOHONGSHU_HANDLE",
    "DEFAULT_XIAOHONGSHU_QR_PATH",
    "PROJECT_REPOSITORY",
    "PROJECT_DISPLAY_NAME",
    "PROJECT_URL",
    "ShareImageBranding",
    "build_share_image_html",
    "share_image_branding_from_config",
]
