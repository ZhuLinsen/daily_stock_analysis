# -*- coding: utf-8 -*-
"""Channel-native renderers consuming NotificationReportPayload."""

from __future__ import annotations

import html
import ipaddress
import json
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import markdown2

from src.formatters import utf16_len
from src.services.report_payload import (
    NotificationReportPayload,
    StockReportItem,
    StrategySkillItem,
    StrategySynthesisView,
)

_CHROME_TEXT: Dict[str, Dict[str, str]] = {
    "zh": {
        "brand_eyebrow": "DAILY STOCK ANALYSIS",
        "analyzed": "分析标的",
        "buy": "建议关注/买",
        "watch": "观望/持有",
        "sell_alert": "卖出/风险",
        "action": "操作建议",
        "score": "综合评分",
        "score_unit": "分",
        "price": "现价 / 涨跌",
        "current_price_short": "现价",
        "rr": "盈亏比",
        "rr_at_entry": "按买点",
        "below_stop": "已破止损",
        "above_target": "已达目标",
        "alerts": "风险预警",
        "risk_panel_title": "风险预警置顶 (Alert-First)",
        "risk_clear": "✓ 本期未触发高危风险警报",
        "no_results": "暂无分析结果",
        "conclusion": "核心结论",
        "time_sensitivity": "时效性",
        "ideal_buy": "理想买点",
        "secondary_buy": "次优买点",
        "stop_loss": "止损位",
        "take_profit": "目标位",
        "upside": "潜在空间",
        "downside": "止损幅度",
        "no_pos": "空仓应对",
        "has_pos": "持仓应对",
        "pos_size": "建议仓位",
        "catalysts": "利好催化",
        "risks": "风险提示",
        "attribution": "信号归因",
        "bull_sig": "最强看多",
        "bear_sig": "最强看空",
        "checklist": "执行清单",
        "failed_checks": "未通过检查",
        "earnings": "业绩预期",
        "sentiment": "舆情情绪",
        "latest_news": "最新动态",
        "sources": "数据来源",
        "model": "分析模型",
        "open_web": "打开 Web 控制台查看完整图表与追问",
        "summary_table_title": "标的决策摘要",
        "score_dist_title": "标的评分分布",
        "snapshot_title": "关键估值与量能指标",
        "vol_ratio": "量比",
        "turnover": "换手率",
        "pe": "市盈率",
        "pb": "市净率",
        "stock_col": "标的",
        "signal_col": "建议",
        "score_col": "评分",
        "trend_col": "趋势",
        "thesis_col": "核心逻辑",
        "details_expand": "展开详细点位、仓位与风控要点",
        "print_btn_hint": "A4 / 离线归档版",
        "technical": "技术指标",
        "news_sentiment": "新闻舆情",
        "fundamentals": "基本面",
        "market_conditions": "市场环境",
        "strategy_synthesis_title": "多策略综合",
        "strategy_final_signal": "综合信号",
        "strategy_consensus": "共识度",
        "strategy_conflict": "冲突",
        "strategy_confidence": "置信度",
        "strategy_supporting": "支持策略",
        "strategy_opposing": "反方策略",
        "strategy_minority_note": "已保留高置信度少数派异议，建议重点关注分歧风险",
        "strategy_invalid_note": "另有 {count} 个策略未能产出有效信号",
    },
    "en": {
        "brand_eyebrow": "DAILY STOCK ANALYSIS",
        "analyzed": "Analyzed",
        "buy": "Buy / Add",
        "watch": "Hold / Watch",
        "sell_alert": "Sell / Alert",
        "action": "Action",
        "score": "Score",
        "score_unit": "pts",
        "price": "Price / Chg",
        "current_price_short": "Now",
        "rr": "Risk / Reward",
        "rr_at_entry": "at entry",
        "below_stop": "Below Stop",
        "above_target": "Target Reached",
        "alerts": "Risk Alerts",
        "risk_panel_title": "Alert-First Risk Summary",
        "risk_clear": "✓ No critical risk alerts triggered",
        "no_results": "No analysis results",
        "conclusion": "Core Thesis",
        "time_sensitivity": "Horizon",
        "ideal_buy": "Ideal Entry",
        "secondary_buy": "Secondary Entry",
        "stop_loss": "Stop Loss",
        "take_profit": "Target",
        "upside": "Upside",
        "downside": "Downside",
        "no_pos": "No Position",
        "has_pos": "Holding",
        "pos_size": "Position Size",
        "catalysts": "Positive Catalysts",
        "risks": "Risk Alerts",
        "attribution": "Signal Attribution",
        "bull_sig": "Strongest Bullish",
        "bear_sig": "Strongest Bearish",
        "checklist": "Action Checklist",
        "failed_checks": "Failed Checks",
        "earnings": "Earnings Outlook",
        "sentiment": "Market Sentiment",
        "latest_news": "Latest News",
        "sources": "Data Sources",
        "model": "Model",
        "open_web": "Open Web Workspace for Charts & Follow-up",
        "summary_table_title": "Decision Overview",
        "score_dist_title": "Score Distribution",
        "snapshot_title": "Key Snapshot Metrics",
        "vol_ratio": "Vol Ratio",
        "turnover": "Turnover",
        "pe": "P/E",
        "pb": "P/B",
        "stock_col": "Symbol",
        "signal_col": "Action",
        "score_col": "Score",
        "trend_col": "Trend",
        "thesis_col": "Thesis",
        "details_expand": "Tap to view levels, position plan & risks",
        "print_btn_hint": "Offline Printable Archive",
        "technical": "Technicals",
        "news_sentiment": "News Sentiment",
        "fundamentals": "Fundamentals",
        "market_conditions": "Market Conditions",
        "strategy_synthesis_title": "Strategy Synthesis",
        "strategy_final_signal": "Final Signal",
        "strategy_consensus": "Consensus",
        "strategy_conflict": "Conflict",
        "strategy_confidence": "Confidence",
        "strategy_supporting": "Supporting",
        "strategy_opposing": "Opposing",
        "strategy_minority_note": "High-confidence minority dissent preserved; review divergence risks",
        "strategy_invalid_note": "{count} additional strategy opinion(s) produced invalid signals",
    },
    "ko": {
        "brand_eyebrow": "DAILY STOCK ANALYSIS",
        "analyzed": "분석 종목",
        "buy": "매수/추가",
        "watch": "관망/보유",
        "sell_alert": "매도/경보",
        "action": "대응 전략",
        "score": "종합 점수",
        "score_unit": "점",
        "price": "현재가 / 등락",
        "current_price_short": "현재가",
        "rr": "손익비",
        "rr_at_entry": "매수가 기준",
        "below_stop": "손절 이탈",
        "above_target": "목표 도달",
        "alerts": "리스크 경보",
        "risk_panel_title": "우선 리스크 경보 (Alert-First)",
        "risk_clear": "✓ 중대 리스크 경보가 감지되지 않았습니다",
        "no_results": "분석 결과 없음",
        "conclusion": "핵심 결론",
        "time_sensitivity": "시의성",
        "ideal_buy": "이상적 매수",
        "secondary_buy": "추가 매수",
        "stop_loss": "손절가",
        "take_profit": "목표가",
        "upside": "상승 여력",
        "downside": "손절 폭",
        "no_pos": "미보유 전략",
        "has_pos": "보유 중 전략",
        "pos_size": "권장 비중",
        "catalysts": "긍정 촉매",
        "risks": "리스크 경고",
        "attribution": "신호 귀인",
        "bull_sig": "최강 상승 신호",
        "bear_sig": "최강 하락 신호",
        "checklist": "실행 체크리스트",
        "failed_checks": "주의/미충족 항목",
        "earnings": "실적 전망",
        "sentiment": "투자 심리",
        "latest_news": "최신 뉴스",
        "sources": "데이터 출처",
        "model": "분석 모델",
        "open_web": "웹 워크스페이스에서 차트 및 상세 보기",
        "summary_table_title": "종목별 결정 요약",
        "score_dist_title": "점수 분포",
        "snapshot_title": "핵심 시세·밸류에이션 지표",
        "vol_ratio": "거래량 비율",
        "turnover": "회전율",
        "pe": "PER",
        "pb": "PBR",
        "stock_col": "종목",
        "signal_col": "신호",
        "score_col": "점수",
        "trend_col": "추세",
        "thesis_col": "핵심 요약",
        "details_expand": "눌러서 가격대·비중·리스크 상세 보기",
        "print_btn_hint": "오프라인 인쇄 보관용",
        "technical": "기술 지표",
        "news_sentiment": "뉴스 심리",
        "fundamentals": "펀더멘털",
        "market_conditions": "시장 환경",
        "strategy_synthesis_title": "전략 종합",
        "strategy_final_signal": "종합 신호",
        "strategy_consensus": "공감도",
        "strategy_conflict": "충돌",
        "strategy_confidence": "신뢰도",
        "strategy_supporting": "지지 전략",
        "strategy_opposing": "반대 전략",
        "strategy_minority_note": "고신뢰 소수 반대 의견이 보존되었습니다. 이견 리스크를 확인하세요",
        "strategy_invalid_note": "추가로 {count}개 전략이 유효한 신호를 생성하지 못했습니다",
    },
}

_ATTR_KEY_MAP = {
    "technical_indicators": "technical",
    "news_sentiment": "news_sentiment",
    "fundamentals": "fundamentals",
    "market_conditions": "market_conditions",
}

_LARK_UNSAFE_TAG_RE = re.compile(r"</?(?:at|a|font|img|text_tag|div|span)\b[^>]*>", re.IGNORECASE)
_MD_HREF_RE = re.compile(r'(<a\b[^>]*?\bhref\s*=\s*)(["\'])([^"\']*)\2', re.IGNORECASE)


def _c(lang: str, key: str) -> str:
    return _CHROME_TEXT.get(lang, _CHROME_TEXT["zh"]).get(key, _CHROME_TEXT["zh"].get(key, key))


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _lark_md_escape(text: Any) -> str:
    """Neutralize Feishu lark_md control tags (<at>, <a>, etc.) and markdown metacharacters."""
    raw = str(text or "")
    cleaned = _LARK_UNSAFE_TAG_RE.sub("", raw)
    cleaned = cleaned.replace("<", "&lt;").replace(">", "&gt;")
    for ch in ("*", "~", "`"):
        cleaned = cleaned.replace(ch, f"\\{ch}")
    return cleaned


def _clip(text: Any, limit: int) -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(raw) <= limit:
        return raw
    return raw[: max(1, limit - 1)].rstrip(" ,，;；.") + "…"


def is_public_web_url(url: str) -> bool:
    """Return True for external HTTP(S) URLs; reject loopback or unspecified hosts."""
    if not url or any(ch.isspace() for ch in url):
        return False
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host or host in {"localhost", "0.0.0.0"} or host.endswith(".localhost"):
        return False
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_loopback or addr.is_unspecified:
            return False
    except ValueError:
        pass
    return True


def _is_http_url(url: str) -> bool:
    return is_public_web_url(url)


def _sanitize_markdown_html_links(rendered_html: str) -> str:
    """Strip unsafe URI schemes (e.g. javascript:, data:, vbscript:) from HTML anchor hrefs."""
    def _replace(match: re.Match[str]) -> str:
        prefix, quote, raw_href = match.group(1), match.group(2), match.group(3).strip()
        unescaped = html.unescape(raw_href)
        normalized = re.sub(r"[\x00-\x1f]+", "", unescaped).strip()
        parsed = urlsplit(normalized)
        if not parsed.scheme:
            if normalized.startswith("//") or any(ch in unescaped for ch in ("\r", "\n", "\0")):
                return f'{prefix}{quote}#{quote}'
            return match.group(0)
        if parsed.scheme.lower() in {"http", "https", "mailto"}:
            return match.group(0)
        return f'{prefix}{quote}#{quote}'

    return _MD_HREF_RE.sub(_replace, rendered_html)


def _signal_colors(stock: StockReportItem) -> Tuple[str, str, str]:
    """Return (text_color, bg_color, border_color) for signal pills."""
    if stock.decision_bucket == "sell" or stock.action in {"sell", "reduce"}:
        return "#b91c1c", "#fef2f2", "#fecaca"
    if stock.action == "alert":
        return "#c2410c", "#fff7ed", "#fed7aa"
    if stock.decision_bucket == "buy" or stock.action in {"buy", "add"}:
        return "#047857", "#ecfdf5", "#a7f3d0"
    return "#b45309", "#fffbeb", "#fde68a"


def _change_pct_color(change_pct: Optional[float], lang: str) -> str:
    if change_pct is None or change_pct == 0:
        return "#475569"
    if lang == "en":
        return "#059669" if change_pct > 0 else "#dc2626"
    return "#dc2626" if change_pct > 0 else "#059669"


def _header_accent_hex(tone: str) -> str:
    return {
        "red": "#dc2626",
        "orange": "#d97706",
        "green": "#059669",
        "blue": "#1e3a8a",
    }.get(tone, "#1e3a8a")


def _compute_price_bar_positions(stock: StockReportItem) -> Optional[Dict[str, float]]:
    """Compute 0..100 positions for Stop -> Buy -> Current -> Target range bar."""
    if stock.decision_bucket == "sell" or stock.action in {"sell", "reduce"}:
        return None
    s = stock.sniper
    ref = s.ideal_buy_num or stock.current_price
    if not (s.stop_loss_num and ref and s.take_profit_num):
        return None
    if not (s.stop_loss_num < ref < s.take_profit_num):
        return None
    if max(s.take_profit_num / s.stop_loss_num, ref / s.stop_loss_num) > 5.0:
        return None
    lo = s.stop_loss_num
    hi = s.take_profit_num
    span = hi - lo
    if span <= 0:
        return None

    def pct(val: float) -> float:
        return max(0.0, min(100.0, ((val - lo) / span) * 100.0))

    result: Dict[str, float] = {
        "buy_pct": pct(s.ideal_buy_num or ref),
        "ref_pct": pct(ref),
    }
    if s.price_zone == "below_stop":
        result["current_pct"] = 0.0
    elif s.price_zone == "above_target":
        result["current_pct"] = 100.0
    elif stock.current_price is not None and lo <= stock.current_price <= hi:
        result["current_pct"] = pct(stock.current_price)
    return result


def _rr_label(stock: StockReportItem, lang: str) -> str:
    rr = stock.sniper.risk_reward_ratio
    if not rr:
        return ""
    differs = bool(
        stock.sniper.ref_basis == "ideal_buy"
        and stock.sniper.ideal_buy_num
        and stock.current_price
        and stock.current_price > 0
        and abs(stock.current_price - stock.sniper.ideal_buy_num) / stock.sniper.ideal_buy_num > 0.01
    )
    base = f"{_c(lang, 'rr')} 1:{rr:.2f}"
    return f"{base} ({_c(lang, 'rr_at_entry')})" if differs else base


def _price_zone_badge_text(stock: StockReportItem, lang: str) -> str:
    if stock.sniper.price_zone == "below_stop":
        return _c(lang, "below_stop")
    if stock.sniper.price_zone == "above_target":
        return _c(lang, "above_target")
    return ""


# ============================================================================
# 1. Email HTML Renderer (Editorial Slate-Paper Research Theme, Inline Table)
# ============================================================================

def _render_email_kpi_strip(payload: NotificationReportPayload) -> str:
    lang = payload.report_language
    if payload.single_stock and payload.stocks:
        s = payload.stocks[0]
        sig_fg, sig_bg, _ = _signal_colors(s)
        price_val = s.price_display or "—"
        if s.change_display:
            price_val = f"{price_val} ({s.change_display})"
        score_val = f"{s.score_display}/100" if s.sentiment_score is not None else "—"
        rr_val = f"1 : {s.sniper.risk_reward_ratio:.2f}" if s.sniper.risk_reward_ratio else (str(len(s.risk_alerts)) if s.risk_alerts else "0")
        rr_label = _c(lang, "rr") if s.sniper.risk_reward_ratio else _c(lang, "alerts")
        cells = [
            (_c(lang, "action"), s.signal_text or "—", sig_fg, sig_bg),
            (_c(lang, "score"), score_val, "#0f172a", "#f8fafc"),
            (_c(lang, "price"), price_val, "#0f172a", "#f8fafc"),
            (rr_label, rr_val, "#1e3a8a" if s.sniper.risk_reward_ratio else ("#b91c1c" if s.risk_alerts else "#047857"), "#f8fafc"),
        ]
    else:
        cells = [
            (_c(lang, "analyzed"), str(payload.total_count), "#0f172a", "#f8fafc"),
            (_c(lang, "buy"), str(payload.buy_count), "#047857", "#ecfdf5"),
            (_c(lang, "watch"), str(payload.hold_count), "#b45309", "#fffbeb"),
            (_c(lang, "sell_alert"), f"{payload.sell_count} / {payload.alert_count}", "#b91c1c" if (payload.sell_count or payload.alert_count) else "#475569", "#fef2f2" if (payload.sell_count or payload.alert_count) else "#f8fafc"),
        ]

    td_html = []
    for label, val, fg, bg in cells:
        td_html.append(
            f'<td width="25%" valign="top" style="padding:4px;">'
            f'<div style="background:{bg};border:1px solid #e2e8f0;border-radius:8px;padding:10px 10px;">'
            f'<div style="font-size:11px;color:#64748b;margin-bottom:4px;">{_esc(label)}</div>'
            f'<div style="font-size:15px;font-weight:700;color:{fg};font-family:\'SFMono-Regular\',Consolas,monospace;">{_esc(val)}</div>'
            f"</div></td>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:14px 0 6px 0;">'
        f"<tr>{''.join(td_html)}</tr>"
        "</table>"
    )


def _render_email_alert_box(payload: NotificationReportPayload) -> str:
    lang = payload.report_language
    if not payload.top_risk_alerts:
        if payload.risk_checked_count == 0:
            return ""
        return (
            '<div style="margin:12px 0;background:#ecfdf5;border:1px solid #a7f3d0;border-left:4px solid #059669;'
            'border-radius:8px;padding:10px 14px;font-size:13px;font-weight:600;color:#065f46;">'
            f"{_esc(_c(lang, 'risk_clear'))}"
            "</div>"
        )

    rows = []
    for entry in payload.top_risk_alerts:
        dot_color = "#dc2626" if entry.severity == "high" else "#d97706"
        rows.append(
            '<li style="margin:4px 0;line-height:1.5;color:#7f1d1d;">'
            f'<span style="color:{dot_color};font-weight:700;">[{_esc(entry.stock_name)} {_esc(entry.stock_code)}]</span> '
            f"{_esc(entry.message)}"
            "</li>"
        )
    return (
        '<div style="margin:12px 0;background:#fef2f2;border:1px solid #fecaca;border-left:4px solid #dc2626;'
        'border-radius:8px;padding:12px 16px;">'
        f'<div style="font-size:13px;font-weight:700;color:#991b1b;margin-bottom:6px;">{_esc(_c(lang, "risk_panel_title"))}</div>'
        f'<ul style="margin:0;padding-left:18px;font-size:13px;">{"".join(rows)}</ul>'
        "</div>"
    )


def _render_email_price_ruler(stock: StockReportItem, lang: str) -> str:
    pos = _compute_price_bar_positions(stock)
    if not pos:
        return ""
    rr_text = _rr_label(stock, lang)
    rr_badge = (
        f'<span style="display:inline-block;background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe;'
        f'border-radius:999px;padding:2px 8px;font-size:11px;font-weight:700;font-family:monospace;">'
        f"{_esc(rr_text)}</span>"
        if rr_text
        else ""
    )
    zone_txt = _price_zone_badge_text(stock, lang)
    zone_badge = ""
    if zone_txt:
        z_fg, z_bg, z_bd = (
            ("#b91c1c", "#fef2f2", "#fecaca")
            if stock.sniper.price_zone == "below_stop"
            else ("#047857", "#ecfdf5", "#a7f3d0")
        )
        zone_badge = (
            f' <span style="display:inline-block;background:{z_bg};color:{z_fg};border:1px solid {z_bd};'
            f'border-radius:999px;padding:2px 8px;font-size:11px;font-weight:700;">{_esc(zone_txt)}</span>'
        )
    meta_chips = []
    if stock.sniper.upside_pct is not None:
        meta_chips.append(
            f'<span style="font-size:11px;color:#047857;font-weight:600;margin-left:8px;">'
            f'{_esc(_c(lang, "upside"))} +{stock.sniper.upside_pct:.1f}%</span>'
        )
    if stock.sniper.downside_pct is not None:
        meta_chips.append(
            f'<span style="font-size:11px;color:#b91c1c;font-weight:600;margin-left:8px;">'
            f'{_esc(_c(lang, "downside"))} -{stock.sniper.downside_pct:.1f}%</span>'
        )

    left_w = max(5, min(95, int(round(pos["buy_pct"]))))
    right_w = 100 - left_w
    bar_table = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
        "<tr>"
        f'<td width="{left_w}%" height="8" bgcolor="#fca5a5" style="height:8px;line-height:8px;font-size:1px;background:#fca5a5;">&nbsp;</td>'
        f'<td width="{right_w}%" height="8" bgcolor="#6ee7b7" style="height:8px;line-height:8px;font-size:1px;background:#6ee7b7;">&nbsp;</td>'
        "</tr>"
        "</table>"
    )
    marker_table = ""
    if "current_pct" in pos:
        cur_pct = int(round(pos["current_pct"]))
        cur_label = f"▲ {_c(lang, 'current_price_short')} {stock.price_display}".strip()
        if cur_pct >= 72:
            spacer_w = max(1, min(70, cur_pct - 24))
            marker_table = (
                '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
                "<tr>"
                f'<td width="{spacer_w}%" style="font-size:1px;line-height:12px;">&nbsp;</td>'
                f'<td align="right" style="font-size:10px;line-height:14px;color:#0f172a;font-weight:700;padding-top:2px;">{_esc(cur_label)}</td>'
                "</tr></table>"
            )
        else:
            spacer_w = max(0, min(68, cur_pct - 2))
            spacer_td = f'<td width="{spacer_w}%" style="font-size:1px;line-height:12px;">&nbsp;</td>' if spacer_w > 0 else ""
            marker_table = (
                '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
                f"<tr>{spacer_td}"
                f'<td align="left" style="font-size:10px;line-height:14px;color:#0f172a;font-weight:700;padding-top:2px;">{_esc(cur_label)}</td>'
                "</tr></table>"
            )
    bounds_table = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:3px;">'
        "<tr>"
        f'<td align="left" style="font-size:10px;color:#64748b;font-family:monospace;">{_esc(_c(lang, "stop_loss"))} {stock.sniper.stop_loss_num:.2f}</td>'
        f'<td align="right" style="font-size:10px;color:#64748b;font-family:monospace;">{_esc(_c(lang, "take_profit"))} {stock.sniper.take_profit_num:.2f}</td>'
        "</tr></table>"
    )
    return (
        '<div style="margin:10px 0 4px 0;padding:8px 10px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;">'
        '<div style="margin-bottom:6px;">'
        f"{rr_badge}{zone_badge}{''.join(meta_chips)}"
        "</div>"
        f"{bar_table}{marker_table}{bounds_table}"
        "</div>"
    )


def _synthesis_signal_pill_colors(signal: str) -> Tuple[str, str, str, str]:
    normalized = (signal or "").strip().lower()
    if normalized in {"strong_buy", "buy", "strong buy", "买入", "强烈买入"}:
        return "#047857", "#ecfdf5", "#a7f3d0", "buy"
    if normalized in {"strong_sell", "sell", "strong sell", "卖出", "强烈卖出"}:
        return "#b91c1c", "#fef2f2", "#fecaca", "sell"
    return "#1e3a8a", "#eff6ff", "#bfdbfe", "hold"


def _synthesis_consensus_pill_colors(level: str) -> Tuple[str, str, str, str]:
    normalized = (level or "").strip().lower()
    if normalized in {"high", "高"}:
        return "#047857", "#ecfdf5", "#a7f3d0", "buy"
    if normalized in {"low", "insufficient", "低", "证据不足"}:
        return "#b45309", "#fffbeb", "#fde68a", "hold"
    return "#1e3a8a", "#eff6ff", "#bfdbfe", "hold"


def _synthesis_conflict_pill_colors(severity: str, count: int) -> Tuple[str, str, str, str]:
    if count <= 0:
        return "#475569", "#f8fafc", "#cbd5e1", ""
    normalized = (severity or "").strip().lower()
    if normalized in {"high", "高"}:
        return "#b91c1c", "#fef2f2", "#fecaca", "sell"
    return "#b45309", "#fffbeb", "#fde68a", "hold"


def _format_skill_item_text(item: StrategySkillItem) -> str:
    conf = f" · {item.confidence_pct}%" if item.confidence_pct is not None else ""
    return f"{item.display_name} · {item.signal_display}{conf}"


def _render_email_strategy_synthesis(stock: StockReportItem, lang: str) -> str:
    syn: Optional[StrategySynthesisView] = stock.strategy_synthesis
    if syn is None:
        if not stock.strategy_synthesis_summary:
            return ""
        return (
            '<div style="margin-top:8px;padding:7px 10px;background:#f8fafc;border:1px solid #e2e8f0;'
            f'border-radius:6px;font-size:12px;color:#334155;">{_esc(stock.strategy_synthesis_summary)}</div>'
        )

    sig_fg, sig_bg, sig_bd, _ = _synthesis_signal_pill_colors(syn.final_signal)
    con_fg, con_bg, con_bd, _ = _synthesis_consensus_pill_colors(syn.consensus_level)
    cf_fg, cf_bg, cf_bd, _ = _synthesis_conflict_pill_colors(syn.conflict_severity, syn.conflict_count)
    badges = [
        (
            f"{_c(lang, 'strategy_final_signal')}: {syn.final_signal_display}",
            sig_fg,
            sig_bg,
            sig_bd,
        ),
        (
            f"{_c(lang, 'strategy_consensus')}: {syn.consensus_display}",
            con_fg,
            con_bg,
            con_bd,
        ),
        (
            f"{_c(lang, 'strategy_conflict')}: {syn.conflict_display} ({syn.conflict_count})",
            cf_fg,
            cf_bg,
            cf_bd,
        ),
    ]
    if syn.confidence_pct is not None:
        badges.append((f"{_c(lang, 'strategy_confidence')}: {syn.confidence_pct}%", "#334155", "#f8fafc", "#cbd5e1"))

    badge_html = " ".join(
        f'<span style="display:inline-block;background:{bg};color:{fg};border:1px solid {bd};'
        f'border-radius:999px;padding:1px 7px;font-size:11px;font-weight:700;margin:2px 4px 2px 0;">{_esc(txt)}</span>'
        for txt, fg, bg, bd in badges
    )
    sup_chips = " ".join(
        '<span style="display:inline-block;background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0;'
        f'border-radius:4px;padding:1px 6px;font-size:11px;margin:2px 4px 2px 0;">{_esc(_format_skill_item_text(it))}</span>'
        for it in syn.supporting_skills
    ) or '<span style="font-size:11px;color:#64748b;">—</span>'
    opp_chips = " ".join(
        '<span style="display:inline-block;background:#fffbeb;color:#92400e;border:1px solid #fde68a;'
        f'border-radius:4px;padding:1px 6px;font-size:11px;margin:2px 4px 2px 0;">{_esc(_format_skill_item_text(it))}</span>'
        for it in syn.opposing_skills
    ) or '<span style="font-size:11px;color:#64748b;">—</span>'

    notes: List[str] = []
    if syn.minority_view_preserved:
        notes.append(f'<span style="color:#b45309;">▲ {_esc(_c(lang, "strategy_minority_note"))}</span>')
    if syn.invalid_opinion_count > 0:
        notes.append(_esc(_c(lang, "strategy_invalid_note").replace("{count}", str(syn.invalid_opinion_count))))
    notes_html = f'<div style="margin-top:6px;font-size:11px;color:#64748b;">{" &nbsp;·&nbsp; ".join(notes)}</div>' if notes else ""
    summary_html = f'<div style="margin:6px 0;font-size:12px;line-height:1.5;color:#334155;">{_esc(syn.summary)}</div>' if syn.summary else ""

    return (
        '<div style="margin-top:10px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;">'
        f'<div style="font-size:11px;font-weight:700;color:#475569;margin-bottom:4px;">{_esc(_c(lang, "strategy_synthesis_title"))}</div>'
        f'<div>{badge_html}</div>'
        f"{summary_html}"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:6px;"><tr>'
        '<td width="50%" valign="top" style="padding:2px 4px 2px 0;">'
        f'<div style="font-size:11px;font-weight:700;color:#047857;margin-bottom:2px;">{_esc(_c(lang, "strategy_supporting"))} ({len(syn.supporting_skills)})</div>'
        f"<div>{sup_chips}</div></td>"
        '<td width="50%" valign="top" style="padding:2px 0 2px 4px;">'
        f'<div style="font-size:11px;font-weight:700;color:#b45309;margin-bottom:2px;">{_esc(_c(lang, "strategy_opposing"))} ({len(syn.opposing_skills)})</div>'
        f"<div>{opp_chips}</div></td>"
        "</tr></table>"
        f"{notes_html}"
        "</div>"
    )


def _render_email_stock_card(
    stock: StockReportItem,
    lang: str,
    *,
    suppress_risk_alerts: bool = False,
) -> str:
    sig_fg, sig_bg, sig_border = _signal_colors(stock)
    price_parts = []
    if stock.price_display:
        price_parts.append(stock.price_display)
    if stock.change_display:
        chg_color = _change_pct_color(stock.change_pct, lang)
        price_parts.append(f'<span style="color:{chg_color};font-weight:600;">{_esc(stock.change_display)}</span>')
    price_html = f'<span style="font-size:13px;color:#334155;font-family:monospace;margin-left:8px;">{" ".join(price_parts)}</span>' if price_parts else ""

    header_row = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        "<tr>"
        '<td align="left" valign="middle">'
        f'<span style="font-size:16px;font-weight:700;color:#0f172a;">{_esc(stock.display_name)}</span> '
        f'<span style="display:inline-block;background:#f1f5f9;color:#334155;border:1px solid #cbd5e1;border-radius:4px;padding:1px 6px;font-size:12px;font-family:monospace;">{_esc(stock.code)}</span>'
        f"{price_html}"
        "</td>"
        '<td align="right" valign="middle" style="white-space:nowrap;">'
        f'<span style="display:inline-block;background:{sig_bg};color:{sig_fg};border:1px solid {sig_border};border-radius:999px;padding:3px 10px;font-size:12px;font-weight:700;">'
        f"{_esc(stock.signal_text)}</span> "
        f'<span style="display:inline-block;background:#0f172a;color:#ffffff;border-radius:999px;padding:3px 9px;font-size:12px;font-weight:700;font-family:monospace;">'
        f"{_esc(stock.score_display)}</span>"
        "</td></tr></table>"
    )

    thesis_html = ""
    if stock.one_sentence or stock.time_sensitivity or stock.trend_prediction or stock.analysis_summary:
        meta_bits = [b for b in (stock.trend_prediction, stock.time_sensitivity) if b]
        meta_line = (
            f'<div style="font-size:11px;color:#64748b;margin-top:4px;">{_esc(" · ".join(meta_bits))}</div>'
            if meta_bits
            else ""
        )
        thesis_text = stock.one_sentence or stock.analysis_summary
        thesis_html = (
            '<div style="margin:10px 0;background:#f8fafc;border-left:3px solid #1e3a8a;border-radius:4px;padding:10px 12px;">'
            + (f'<div style="font-size:13px;line-height:1.6;color:#1e293b;font-weight:500;">{_esc(thesis_text)}</div>' if thesis_text else "")
            + f"{meta_line}</div>"
        )

    sniper_cells = [
        (_c(lang, "stop_loss"), stock.sniper.stop_loss or "—", "#b91c1c"),
        (_c(lang, "ideal_buy"), stock.sniper.ideal_buy or "—", "#047857"),
        (_c(lang, "secondary_buy"), stock.sniper.secondary_buy or "—", "#0f766e"),
        (_c(lang, "take_profit"), stock.sniper.take_profit or "—", "#b45309"),
    ]
    sniper_html = ""
    if any(getattr(stock.sniper, k) for k in ("ideal_buy", "secondary_buy", "stop_loss", "take_profit")):
        tds = "".join(
            f'<td width="25%" valign="top" style="padding:3px;">'
            '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:6px;padding:7px 9px;">'
            f'<div style="font-size:11px;color:#64748b;margin-bottom:2px;">{_esc(lbl)}</div>'
            f'<div style="font-size:12px;font-weight:700;color:{clr};font-family:monospace;">{_esc(val)}</div>'
            "</div></td>"
            for lbl, val, clr in sniper_cells
        )
        sniper_html = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:6px 0;">'
            f"<tr>{tds}</tr></table>"
            f"{_render_email_price_ruler(stock, lang)}"
        )

    pos = stock.position_advice
    pos_html = ""
    if pos.no_position or pos.has_position:
        pos_html = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 2px 0;">'
            "<tr>"
            '<td width="50%" valign="top" style="padding:3px 4px 3px 0;">'
            '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px 10px;font-size:12px;line-height:1.5;color:#334155;">'
            f'<div style="font-size:11px;font-weight:700;color:#475569;margin-bottom:2px;">{_esc(_c(lang, "no_pos"))}</div>'
            f"{_esc(pos.no_position or '—')}"
            "</div></td>"
            '<td width="50%" valign="top" style="padding:3px 0 3px 4px;">'
            '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px 10px;font-size:12px;line-height:1.5;color:#334155;">'
            f'<div style="font-size:11px;font-weight:700;color:#475569;margin-bottom:2px;">{_esc(_c(lang, "has_pos"))}</div>'
            f"{_esc(pos.has_position or '—')}"
            "</div></td></tr></table>"
        )

    extras: List[str] = []
    if stock.risk_alerts and not suppress_risk_alerts:
        items_li = "".join(f'<li style="margin:2px 0;">{_esc(x)}</li>' for x in stock.risk_alerts[:3])
        extras.append(
            f'<div style="margin-top:8px;font-size:12px;color:#991b1b;">'
            f'<strong>{_esc(_c(lang, "risks"))}:</strong>'
            f'<ul style="margin:3px 0 0 18px;padding:0;">{items_li}</ul></div>'
        )
    if stock.positive_catalysts:
        items_li = "".join(f'<li style="margin:2px 0;">{_esc(x)}</li>' for x in stock.positive_catalysts[:3])
        extras.append(
            f'<div style="margin-top:8px;font-size:12px;color:#065f46;">'
            f'<strong>{_esc(_c(lang, "catalysts"))}:</strong>'
            f'<ul style="margin:3px 0 0 18px;padding:0;">{items_li}</ul></div>'
        )
    if stock.signal_attribution and (stock.signal_attribution.strongest_bullish or stock.signal_attribution.strongest_bearish):
        sig_bits = []
        if stock.signal_attribution.strongest_bullish:
            sig_bits.append(f'<span style="color:#047857;">▲ {_esc(_c(lang, "bull_sig"))}: {_esc(stock.signal_attribution.strongest_bullish)}</span>')
        if stock.signal_attribution.strongest_bearish:
            sig_bits.append(f'<span style="color:#b91c1c;">▼ {_esc(_c(lang, "bear_sig"))}: {_esc(stock.signal_attribution.strongest_bearish)}</span>')
        extras.append(f'<div style="margin-top:8px;font-size:12px;line-height:1.5;">{" &nbsp;|&nbsp; ".join(sig_bits)}</div>')
    if stock.failed_checks:
        chips = " ".join(
            f'<span style="display:inline-block;background:#fffbeb;border:1px solid #fde68a;color:#92400e;border-radius:4px;padding:2px 6px;font-size:11px;margin:2px 4px 2px 0;">{_esc(_clip(c, 48))}</span>'
            for c in stock.failed_checks[:3]
        )
        extras.append(f'<div style="margin-top:6px;">{chips}</div>')
    synthesis_html = _render_email_strategy_synthesis(stock, lang)
    if synthesis_html:
        extras.append(synthesis_html)
    if stock.empty_news_disclosure:
        extras.append(
            f'<div style="margin-top:8px;padding:6px 10px;background:#fffbeb;border:1px solid #fde68a;border-radius:6px;font-size:11px;color:#78350f;">{_esc(stock.empty_news_disclosure)}</div>'
        )

    border_left = "4px solid #dc2626" if stock.has_urgent_risk else "1px solid #e2e8f0"
    return (
        f'<div style="margin:14px 0;background:#ffffff;border:1px solid #e2e8f0;border-left:{border_left};'
        'border-radius:10px;padding:16px;">'
        f"{header_row}{thesis_html}{sniper_html}{pos_html}{''.join(extras)}"
        "</div>"
    )


def _render_email_summary_table(payload: NotificationReportPayload) -> str:
    lang = payload.report_language
    rows = []
    for s in payload.stocks:
        sig_fg, sig_bg, _ = _signal_colors(s)
        thesis = _clip(s.one_sentence or s.analysis_summary or s.trend_prediction, 68)
        rows.append(
            "<tr>"
            f'<td style="padding:8px 10px;border-top:1px solid #e2e8f0;font-size:13px;"><strong>{_esc(s.display_name)}</strong> <code style="font-size:11px;color:#64748b;">{_esc(s.code)}</code></td>'
            f'<td style="padding:8px 10px;border-top:1px solid #e2e8f0;font-size:12px;"><span style="background:{sig_bg};color:{sig_fg};padding:2px 8px;border-radius:999px;font-weight:700;">{_esc(s.signal_text)}</span></td>'
            f'<td style="padding:8px 10px;border-top:1px solid #e2e8f0;font-size:13px;font-family:monospace;font-weight:700;color:#0f172a;">{_esc(s.score_display)}</td>'
            f'<td style="padding:8px 10px;border-top:1px solid #e2e8f0;font-size:12px;color:#475569;">{_esc(thesis)}</td>'
            "</tr>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:14px 0;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;border-collapse:collapse;">'
        '<tr style="background:#f8fafc;">'
        f'<th align="left" style="padding:8px 10px;font-size:11px;color:#64748b;">{_esc(_c(lang, "stock_col"))}</th>'
        f'<th align="left" style="padding:8px 10px;font-size:11px;color:#64748b;">{_esc(_c(lang, "signal_col"))}</th>'
        f'<th align="left" style="padding:8px 10px;font-size:11px;color:#64748b;">{_esc(_c(lang, "score_col"))}</th>'
        f'<th align="left" style="padding:8px 10px;font-size:11px;color:#64748b;">{_esc(_c(lang, "thesis_col"))}</th>'
        "</tr>"
        f"{''.join(rows)}"
        "</table>"
    )


def render_email_html(payload: NotificationReportPayload) -> str:
    """Render 100% inline-CSS email HTML directly from NotificationReportPayload."""
    lang = payload.report_language
    html_lang = {"zh": "zh-CN", "en": "en", "ko": "ko"}.get(lang, "zh-CN")
    accent = _header_accent_hex(payload.header_tone)
    market_line = (
        f'<div style="font-size:12px;color:#64748b;margin-top:4px;">{_esc(payload.market_status_line)}</div>'
        if payload.market_status_line
        else ""
    )
    suppress_card_risk = bool(payload.single_stock and payload.top_risk_alerts)
    if not payload.stocks:
        body_section = f'<div style="padding:20px;text-align:center;color:#64748b;font-size:14px;">{_esc(_c(lang, "no_results"))}</div>'
    elif payload.summary_only:
        body_section = _render_email_summary_table(payload)
    else:
        body_section = "".join(
            _render_email_stock_card(s, lang, suppress_risk_alerts=suppress_card_risk)
            for s in payload.stocks
        )

    cta_html = ""
    if _is_http_url(payload.web_url):
        cta_html = (
            '<div style="text-align:center;margin:20px 0 8px 0;">'
            f'<a href="{_esc(payload.web_url)}" style="display:inline-block;background:#0f172a;color:#ffffff;'
            'text-decoration:none;font-size:13px;font-weight:600;padding:10px 22px;border-radius:8px;">'
            f"{_esc(_c(lang, 'open_web'))}</a></div>"
        )

    footer_bits = [f"{_c(lang, 'model')}: {', '.join(payload.models_used)}"] if payload.models_used else []
    footer_bits.append(payload.generated_at)
    footer_meta = _esc(" · ".join(footer_bits))

    return (
        "<!DOCTYPE html>"
        f'<html lang="{html_lang}">'
        '<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(payload.dynamic_title)}</title></head>"
        '<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'PingFang SC\',\'Microsoft YaHei\',sans-serif;color:#0f172a;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f1f5f9;">'
        '<tr><td align="center" style="padding:20px 12px;">'
        '<!--[if mso]><table role="presentation" align="center" width="680" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:680px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">'
        f'<tr><td style="height:4px;background:{accent};line-height:4px;font-size:4px;">&nbsp;</td></tr>'
        '<tr><td style="padding:20px 24px 24px 24px;">'
        f'<div style="font-size:11px;font-weight:700;letter-spacing:0.1em;color:#64748b;margin-bottom:6px;">{_esc(_c(lang, "brand_eyebrow"))} · {_esc(payload.report_date)}</div>'
        f'<h1 style="margin:0;font-size:20px;line-height:1.35;color:#0f172a;">{_esc(payload.dynamic_title)}</h1>'
        f"{market_line}"
        f"{_render_email_kpi_strip(payload)}"
        f"{_render_email_alert_box(payload)}"
        f"{body_section}"
        f"{cta_html}"
        '<div style="margin-top:18px;padding-top:12px;border-top:1px solid #e2e8f0;font-size:11px;line-height:1.6;color:#64748b;">'
        f"<div>{footer_meta}</div>"
        f"<div>{_esc(payload.disclaimer)}</div>"
        "</div>"
        "</td></tr></table>"
        '<!--[if mso]></td></tr></table><![endif]-->'
        "</td></tr></table>"
        "</body></html>"
    )


# ============================================================================
# 2. Standalone Offline / Printable HTML Renderer
# ============================================================================

_STANDALONE_CSS = """
:root {
  --bg: #f1f5f9;
  --surface: #ffffff;
  --surface-sub: #f8fafc;
  --ink: #0f172a;
  --ink-muted: #475569;
  --border: #e2e8f0;
  --accent: #1e3a8a;
  --buy-fg: #047857;
  --buy-bg: #ecfdf5;
  --buy-bd: #a7f3d0;
  --sell-fg: #b91c1c;
  --sell-bg: #fef2f2;
  --sell-bd: #fecaca;
  --warn-fg: #b45309;
  --warn-bg: #fffbeb;
  --warn-bd: #fde68a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0b1120;
    --surface: #111827;
    --surface-sub: #1e293b;
    --ink: #f1f5f9;
    --ink-muted: #94a3b8;
    --border: #334155;
    --accent: #60a5fa;
    --buy-fg: #34d399;
    --buy-bg: #064e3b;
    --buy-bd: #065f46;
    --sell-fg: #f87171;
    --sell-bg: #450a0a;
    --sell-bd: #7f1d1d;
    --warn-fg: #fbbf24;
    --warn-bg: #451a03;
    --warn-bd: #78350f;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 28px 16px;
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  line-height: 1.6;
}
.page {
  max-width: 860px;
  margin: 0 auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
}
.banner { height: 5px; background: var(--accent); }
.inner { padding: 26px 28px 28px 28px; }
.eyebrow { font-size: 11px; font-weight: 700; letter-spacing: 0.1em; color: var(--ink-muted); }
h1 { margin: 6px 0 4px 0; font-size: 22px; line-height: 1.35; }
.subline { font-size: 13px; color: var(--ink-muted); margin-bottom: 16px; }
.kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 16px 0; }
.kpi-card { background: var(--surface-sub); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
.kpi-label { font-size: 11px; color: var(--ink-muted); }
.kpi-value { font-size: 17px; font-weight: 700; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin-top: 2px; }
.alert-box { background: var(--sell-bg); border: 1px solid var(--sell-bd); border-left: 4px solid var(--sell-fg); border-radius: 10px; padding: 12px 16px; margin: 14px 0; }
.alert-title { font-size: 13px; font-weight: 700; color: var(--sell-fg); margin-bottom: 6px; }
.clear-box { background: var(--buy-bg); border: 1px solid var(--buy-bd); border-left: 4px solid var(--buy-fg); border-radius: 10px; padding: 10px 14px; font-size: 13px; font-weight: 600; color: var(--buy-fg); margin: 14px 0; }
.stock-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 18px; margin: 16px 0; break-inside: avoid; }
.stock-card.urgent { border-left: 4px solid var(--sell-fg); }
.stock-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; }
.stock-title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
.stock-name { font-size: 18px; font-weight: 700; }
.code-pill { background: var(--surface-sub); border: 1px solid var(--border); border-radius: 6px; padding: 1px 7px; font-size: 12px; font-family: ui-monospace, monospace; }
.badges { display: flex; align-items: center; gap: 6px; }
.pill { border-radius: 999px; padding: 3px 10px; font-size: 12px; font-weight: 700; border: 1px solid var(--border); }
.pill.buy { color: var(--buy-fg); background: var(--buy-bg); border-color: var(--buy-bd); }
.pill.sell { color: var(--sell-fg); background: var(--sell-bg); border-color: var(--sell-bd); }
.pill.hold { color: var(--warn-fg); background: var(--warn-bg); border-color: var(--warn-bd); }
.pill.alert { color: #c2410c; background: #fff7ed; border-color: #fed7aa; }
.score-pill { background: var(--ink); color: var(--surface); border-radius: 999px; padding: 3px 9px; font-size: 12px; font-weight: 700; font-family: ui-monospace, monospace; }
.zone-pill { border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 700; border: 1px solid var(--border); }
.zone-pill.stop { color: var(--sell-fg); background: var(--sell-bg); border-color: var(--sell-bd); }
.zone-pill.target { color: var(--buy-fg); background: var(--buy-bg); border-color: var(--buy-bd); }
.thesis-box { margin: 12px 0; background: var(--surface-sub); border-left: 3px solid var(--accent); border-radius: 6px; padding: 10px 14px; }
.sniper-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 10px 0; }
.sniper-cell { background: var(--surface-sub); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
.sniper-val { font-size: 13px; font-weight: 700; font-family: ui-monospace, monospace; margin-top: 2px; }
.range-box { background: var(--surface-sub); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin: 10px 0; }
.ruler-svg { width: 100%; height: 52px; display: block; margin-top: 6px; }
.dist-box { background: var(--surface-sub); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; margin: 14px 0; }
.dist-svg { width: 100%; height: 116px; display: block; }
.two-col { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 10px 0; }
.snap-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 6px; }
.sub-card { background: var(--surface-sub); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-size: 13px; }
.sub-title { font-size: 11px; font-weight: 700; text-transform: uppercase; color: var(--ink-muted); margin-bottom: 4px; }
.attr-row { display: grid; grid-template-columns: 96px 1fr 42px; align-items: center; gap: 8px; font-size: 12px; margin: 4px 0; }
.attr-track { height: 6px; background: var(--border); border-radius: 999px; overflow: hidden; }
.attr-fill { height: 6px; background: var(--accent); border-radius: 999px; }
.chk-list { list-style: none; margin: 6px 0 0 0; padding: 0; font-size: 12px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 12px; }
.footer { margin-top: 20px; padding-top: 12px; border-top: 1px solid var(--border); font-size: 12px; color: var(--ink-muted); }
.md-body h1, .md-body h2, .md-body h3 { margin-top: 1.1em; margin-bottom: 0.4em; }
.md-body table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px; }
.md-body th, .md-body td { border: 1px solid var(--border); padding: 6px 9px; text-align: left; }
.md-body th { background: var(--surface-sub); }
@media (max-width: 640px) {
  .kpi-grid, .sniper-grid, .snap-grid, .two-col, .chk-list { grid-template-columns: 1fr; }
  .inner { padding: 18px 16px; }
}
@media print {
  @page { margin: 14mm; }
  :root {
    --bg: #ffffff;
    --surface: #ffffff;
    --surface-sub: #f8fafc;
    --ink: #0f172a;
    --ink-muted: #475569;
    --border: #cbd5e1;
    --accent: #1e3a8a;
    --buy-fg: #047857;
    --buy-bg: #ecfdf5;
    --buy-bd: #a7f3d0;
    --sell-fg: #b91c1c;
    --sell-bg: #fef2f2;
    --sell-bd: #fecaca;
    --warn-fg: #b45309;
    --warn-bg: #fffbeb;
    --warn-bd: #fde68a;
  }
  body { background: #ffffff !important; color: #0f172a !important; padding: 0; }
  .page { box-shadow: none; border: none; max-width: none; background: #ffffff !important; }
  .kpi-card, .sniper-cell, .sub-card, .thesis-box, .range-box, .dist-box { background: #f8fafc !important; border-color: #cbd5e1 !important; color: #0f172a !important; }
  .stock-card { background: #ffffff !important; border-color: #cbd5e1 !important; }
}
"""


def _render_score_dist_svg(payload: NotificationReportPayload) -> str:
    scored = [s.sentiment_score for s in payload.stocks if s.sentiment_score is not None]
    if len(scored) < 2:
        return ""
    lang = payload.report_language
    buckets = [
        ("<40", lambda v: v < 40, "var(--sell-fg)"),
        ("40-59", lambda v: 40 <= v < 60, "var(--warn-fg)"),
        ("60-69", lambda v: 60 <= v < 70, "var(--accent)"),
        ("70-79", lambda v: 70 <= v < 80, "var(--buy-fg)"),
        ("80+", lambda v: v >= 80, "var(--buy-fg)"),
    ]
    counts = [sum(1 for sc in scored if pred(sc)) for _, pred, _ in buckets]
    max_v = max(1, *counts)
    w, h, top, bot = 360, 116, 18, 22
    bar_h = h - top - bot
    step = w / len(buckets)
    bw = step * 0.56
    parts: List[str] = []
    for idx, (label, _, fill) in enumerate(buckets):
        cnt = counts[idx]
        bh = max(4.0 if cnt > 0 else 2.0, (cnt / max_v) * bar_h)
        x = idx * step + (step - bw) / 2.0
        y = top + (bar_h - bh)
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" fill="{fill}" opacity="0.85"/>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{max(12.0, y - 4):.1f}" text-anchor="middle" font-size="10" font-family="ui-monospace,monospace" fill="var(--ink)">{cnt}</text>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{h - 5}" text-anchor="middle" font-size="10" font-family="ui-monospace,monospace" fill="var(--ink-muted)">{_esc(label)}</text>')
    svg = f'<svg class="dist-svg" viewBox="0 0 {w} {h}" role="img" aria-label="{_esc(_c(lang, "score_dist_title"))}">{"".join(parts)}</svg>'
    return f'<div class="dist-box"><div class="sub-title">{_esc(_c(lang, "score_dist_title"))}</div>{svg}</div>'


def _render_standalone_price_svg(stock: StockReportItem, pos: Dict[str, float], lang: str) -> str:
    w, y_bar, bar_h = 520, 16, 8
    buy_x = max(8.0, min(w - 8.0, (pos["buy_pct"] / 100.0) * (w - 16.0) + 8.0))
    left_w = max(0.0, buy_x - 8.0)
    right_w = max(0.0, (w - 8.0) - buy_x)
    shapes = [
        f'<rect x="8" y="{y_bar}" width="{left_w:.1f}" height="{bar_h}" rx="4" fill="#fca5a5"/>',
        f'<rect x="{buy_x:.1f}" y="{y_bar}" width="{right_w:.1f}" height="{bar_h}" rx="4" fill="#6ee7b7"/>',
        f'<line x1="{buy_x:.1f}" y1="{y_bar - 3}" x2="{buy_x:.1f}" y2="{y_bar + bar_h + 3}" stroke="var(--accent)" stroke-width="2"/>',
    ]
    if "current_pct" in pos:
        cx = max(8.0, min(w - 8.0, (pos["current_pct"] / 100.0) * (w - 16.0) + 8.0))
        shapes.append(f'<circle cx="{cx:.1f}" cy="{y_bar + bar_h / 2:.1f}" r="5.5" fill="var(--ink)" stroke="var(--surface)" stroke-width="1.5"/>')
        if stock.price_display:
            anchor = "end" if pos["current_pct"] > 82 else ("start" if pos["current_pct"] < 18 else "middle")
            shapes.append(
                f'<text x="{cx:.1f}" y="11" text-anchor="{anchor}" font-size="10" font-weight="700" font-family="ui-monospace,monospace" fill="var(--ink)">{_esc(_c(lang, "current_price_short"))} {_esc(stock.price_display)}</text>'
            )
    lo_lbl = f"{_c(lang, 'stop_loss')} {stock.sniper.stop_loss_num:.2f}"
    hi_lbl = f"{_c(lang, 'take_profit')} {stock.sniper.take_profit_num:.2f}"
    shapes.append(f'<text x="8" y="46" text-anchor="start" font-size="10" font-family="ui-monospace,monospace" fill="var(--ink-muted)">{_esc(lo_lbl)}</text>')
    if stock.sniper.ideal_buy_num:
        buy_lbl = f"{_c(lang, 'ideal_buy')} {stock.sniper.ideal_buy_num:.2f}"
        shapes.append(f'<text x="{buy_x:.1f}" y="46" text-anchor="middle" font-size="10" font-family="ui-monospace,monospace" fill="var(--accent)">{_esc(buy_lbl)}</text>')
    shapes.append(f'<text x="{w - 8}" y="46" text-anchor="end" font-size="10" font-family="ui-monospace,monospace" fill="var(--ink-muted)">{_esc(hi_lbl)}</text>')
    return f'<svg class="ruler-svg" viewBox="0 0 {w} 52" role="img">{"".join(shapes)}</svg>'


def _render_standalone_strategy_synthesis(stock: StockReportItem, lang: str) -> str:
    syn: Optional[StrategySynthesisView] = stock.strategy_synthesis
    if syn is None:
        if not stock.strategy_synthesis_summary:
            return ""
        return f'<div style="font-size:12px;margin-top:4px;">{_esc(stock.strategy_synthesis_summary)}</div>'

    _, _, _, sig_cls = _synthesis_signal_pill_colors(syn.final_signal)
    _, _, _, con_cls = _synthesis_consensus_pill_colors(syn.consensus_level)
    _, _, _, cf_cls = _synthesis_conflict_pill_colors(syn.conflict_severity, syn.conflict_count)
    badges = [
        f'<span class="pill {sig_cls}">{_esc(_c(lang, "strategy_final_signal"))}: {_esc(syn.final_signal_display)}</span>',
        f'<span class="pill {con_cls}">{_esc(_c(lang, "strategy_consensus"))}: {_esc(syn.consensus_display)}</span>',
        (
            f'<span class="pill {cf_cls}">'
            if cf_cls
            else '<span class="zone-pill">'
        ) + f"{_esc(_c(lang, 'strategy_conflict'))}: {_esc(syn.conflict_display)} ({syn.conflict_count})</span>",
    ]
    if syn.confidence_pct is not None:
        badges.append(f'<span class="code-pill">{_esc(_c(lang, "strategy_confidence"))}: {syn.confidence_pct}%</span>')

    sup_chips = " ".join(
        '<span class="pill buy" style="font-size:11px;padding:1px 7px;margin:2px 4px 2px 0;">'
        f"{_esc(_format_skill_item_text(it))}</span>"
        for it in syn.supporting_skills
    ) or '<span style="font-size:12px;color:var(--ink-muted);">—</span>'
    opp_chips = " ".join(
        '<span class="pill hold" style="font-size:11px;padding:1px 7px;margin:2px 4px 2px 0;">'
        f"{_esc(_format_skill_item_text(it))}</span>"
        for it in syn.opposing_skills
    ) or '<span style="font-size:12px;color:var(--ink-muted);">—</span>'

    notes: List[str] = []
    if syn.minority_view_preserved:
        notes.append(f'<span style="color:var(--warn-fg);">▲ {_esc(_c(lang, "strategy_minority_note"))}</span>')
    if syn.invalid_opinion_count > 0:
        notes.append(_esc(_c(lang, "strategy_invalid_note").replace("{count}", str(syn.invalid_opinion_count))))
    notes_html = f'<div style="font-size:11px;color:var(--ink-muted);margin-top:6px;">{" · ".join(notes)}</div>' if notes else ""
    summary_html = f'<div style="font-size:12px;margin:6px 0;color:var(--ink);">{_esc(syn.summary)}</div>' if syn.summary else ""

    return (
        '<div class="sub-card" style="margin-top:10px;">'
        f'<div class="sub-title">{_esc(_c(lang, "strategy_synthesis_title"))}</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center;">{"".join(badges)}</div>'
        f"{summary_html}"
        '<div class="two-col" style="margin:6px 0 0 0;">'
        f'<div><div class="sub-title" style="color:var(--buy-fg);">{_esc(_c(lang, "strategy_supporting"))} ({len(syn.supporting_skills)})</div><div>{sup_chips}</div></div>'
        f'<div><div class="sub-title" style="color:var(--warn-fg);">{_esc(_c(lang, "strategy_opposing"))} ({len(syn.opposing_skills)})</div><div>{opp_chips}</div></div>'
        "</div>"
        f"{notes_html}"
        "</div>"
    )


def _render_standalone_stock_card(
    stock: StockReportItem,
    lang: str,
    *,
    suppress_risk_alerts: bool = False,
) -> str:
    if stock.decision_bucket == "sell" or stock.action in {"sell", "reduce"}:
        pill_cls = "sell"
    elif stock.action == "alert":
        pill_cls = "alert"
    elif stock.decision_bucket == "buy" or stock.action in {"buy", "add"}:
        pill_cls = "buy"
    else:
        pill_cls = "hold"
    urgent_cls = " urgent" if stock.has_urgent_risk else ""
    price_bit = ""
    if stock.price_display or stock.change_display:
        chg_color = _change_pct_color(stock.change_pct, lang)
        chg_span = f'<span style="color:{chg_color};font-weight:600;">{_esc(stock.change_display)}</span>' if stock.change_display else ""
        price_bit = f'<span style="font-family:ui-monospace,monospace;font-size:13px;">{_esc(stock.price_display)} {chg_span}</span>'

    thesis_html = ""
    if stock.one_sentence or stock.analysis_summary or stock.trend_prediction or stock.time_sensitivity:
        meta_bits = [b for b in (stock.trend_prediction, stock.time_sensitivity) if b]
        meta_line = f'<div style="font-size:12px;color:var(--ink-muted);margin-top:4px;">{_esc(" · ".join(meta_bits))}</div>' if meta_bits else ""
        thesis_html = (
            '<div class="thesis-box">'
            + (f'<div>{_esc(stock.one_sentence or stock.analysis_summary)}</div>' if (stock.one_sentence or stock.analysis_summary) else "")
            + f"{meta_line}</div>"
        )

    sniper_html = ""
    if any(getattr(stock.sniper, k) for k in ("ideal_buy", "secondary_buy", "stop_loss", "take_profit")):
        cells = [
            (_c(lang, "stop_loss"), stock.sniper.stop_loss or "—"),
            (_c(lang, "ideal_buy"), stock.sniper.ideal_buy or "—"),
            (_c(lang, "secondary_buy"), stock.sniper.secondary_buy or "—"),
            (_c(lang, "take_profit"), stock.sniper.take_profit or "—"),
        ]
        sniper_html = '<div class="sniper-grid">' + "".join(
            f'<div class="sniper-cell"><div class="kpi-label">{_esc(lbl)}</div><div class="sniper-val">{_esc(val)}</div></div>'
            for lbl, val in cells
        ) + "</div>"
        pos = _compute_price_bar_positions(stock)
        if pos:
            rr_text = _rr_label(stock, lang)
            zone_txt = _price_zone_badge_text(stock, lang)
            zone_cls = "stop" if stock.sniper.price_zone == "below_stop" else "target"
            zone_pill = f'<span class="zone-pill {zone_cls}">{_esc(zone_txt)}</span>' if zone_txt else ""
            up = f' · {_esc(_c(lang, "upside"))} +{stock.sniper.upside_pct:.1f}%' if stock.sniper.upside_pct is not None else ""
            dn = f' · {_esc(_c(lang, "downside"))} -{stock.sniper.downside_pct:.1f}%' if stock.sniper.downside_pct is not None else ""
            sniper_html += (
                '<div class="range-box">'
                f'<div style="font-size:12px;font-weight:600;display:flex;flex-wrap:wrap;gap:8px;align-items:center;">'
                f'<span>{_esc(rr_text)}{up}{dn}</span>{zone_pill}</div>'
                f"{_render_standalone_price_svg(stock, pos, lang)}"
                "</div>"
            )

    pos_adv = stock.position_advice
    pos_html = ""
    if pos_adv.no_position or pos_adv.has_position or pos_adv.suggested_position:
        pos_cards = []
        if pos_adv.no_position:
            pos_cards.append(f'<div class="sub-card"><div class="sub-title">{_esc(_c(lang, "no_pos"))}</div><div>{_esc(pos_adv.no_position)}</div></div>')
        if pos_adv.has_position:
            pos_cards.append(f'<div class="sub-card"><div class="sub-title">{_esc(_c(lang, "has_pos"))}</div><div>{_esc(pos_adv.has_position)}</div></div>')
        pos_html = f'<div class="two-col">{"".join(pos_cards)}</div>' if pos_cards else ""
        if pos_adv.suggested_position:
            pos_html += f'<div style="font-size:12px;color:var(--ink-muted);margin:4px 0;"><strong>{_esc(_c(lang, "pos_size"))}:</strong> {_esc(pos_adv.suggested_position)}</div>'

    col_cards = []
    if stock.risk_alerts and not suppress_risk_alerts:
        lis = "".join(f"<li>{_esc(x)}</li>" for x in stock.risk_alerts)
        col_cards.append(f'<div class="sub-card"><div class="sub-title" style="color:var(--sell-fg);">{_esc(_c(lang, "risks"))}</div><ul style="margin:4px 0 0 16px;padding:0;">{lis}</ul></div>')
    if stock.positive_catalysts:
        lis = "".join(f"<li>{_esc(x)}</li>" for x in stock.positive_catalysts)
        col_cards.append(f'<div class="sub-card"><div class="sub-title" style="color:var(--buy-fg);">{_esc(_c(lang, "catalysts"))}</div><ul style="margin:4px 0 0 16px;padding:0;">{lis}</ul></div>')
    cols_html = f'<div class="two-col">{"".join(col_cards)}</div>' if col_cards else ""

    snap_cells: List[Tuple[str, str]] = []
    snap = stock.market_snapshot
    if isinstance(snap, dict):
        for skey, lbl_key, fmt in (
            ("volume_ratio", "vol_ratio", "{:.2f}"),
            ("turnover_rate", "turnover", "{:.2f}%"),
            ("pe_ratio", "pe", "{:.2f}"),
            ("pb_ratio", "pb", "{:.2f}"),
        ):
            raw_v = snap.get(skey)
            if raw_v is not None and not isinstance(raw_v, bool):
                try:
                    num_v = float(str(raw_v).rstrip("%"))
                except (TypeError, ValueError):
                    num_v = float("nan")
                if num_v == num_v and abs(num_v) != float("inf"):
                    snap_cells.append((_c(lang, lbl_key), fmt.format(num_v)))
    snap_html = ""
    if snap_cells:
        snap_items = "".join(
            f'<div class="sniper-cell"><div class="kpi-label">{_esc(lbl)}</div><div class="sniper-val">{_esc(val)}</div></div>'
            for lbl, val in snap_cells
        )
        snap_html = (
            '<div style="margin-top:10px;">'
            f'<div class="sub-title">{_esc(_c(lang, "snapshot_title"))}</div>'
            f'<div class="snap-grid">{snap_items}</div></div>'
        )

    attr_html = ""
    if stock.signal_attribution:
        rows = []
        for k, val in stock.signal_attribution.weights:
            lbl = _c(lang, _ATTR_KEY_MAP.get(k, k))
            w = max(0.0, min(100.0, val))
            rows.append(
                '<div class="attr-row">'
                f"<span>{_esc(lbl)}</span>"
                f'<div class="attr-track"><div class="attr-fill" style="width:{w:.0f}%;"></div></div>'
                f'<span style="font-family:monospace;text-align:right;">{val:.0f}%</span>'
                "</div>"
            )
        ext = []
        if stock.signal_attribution.strongest_bullish:
            ext.append(f"▲ {_esc(_c(lang, 'bull_sig'))}: {_esc(stock.signal_attribution.strongest_bullish)}")
        if stock.signal_attribution.strongest_bearish:
            ext.append(f"▼ {_esc(_c(lang, 'bear_sig'))}: {_esc(stock.signal_attribution.strongest_bearish)}")
        ext_html = f'<div style="font-size:12px;margin-top:6px;">{" | ".join(ext)}</div>' if ext else ""
        attr_html = (
            '<div class="sub-card" style="margin-top:10px;">'
            f'<div class="sub-title">{_esc(_c(lang, "attribution"))}</div>'
            f"{''.join(rows)}{ext_html}</div>"
        )

    extra_blocks = []
    if stock.earnings_outlook:
        extra_blocks.append(f'<div style="font-size:12px;margin-top:8px;"><strong>{_esc(_c(lang, "earnings"))}:</strong> {_esc(stock.earnings_outlook)}</div>')
    if stock.sentiment_summary:
        extra_blocks.append(f'<div style="font-size:12px;margin-top:4px;"><strong>{_esc(_c(lang, "sentiment"))}:</strong> {_esc(stock.sentiment_summary)}</div>')
    if stock.latest_news:
        extra_blocks.append(f'<div style="font-size:12px;margin-top:4px;"><strong>{_esc(_c(lang, "latest_news"))}:</strong> {_esc(stock.latest_news)}</div>')
    standalone_syn = _render_standalone_strategy_synthesis(stock, lang)
    if standalone_syn:
        extra_blocks.append(standalone_syn)
    if stock.checklist:
        items = "".join(f"<li>{_esc(x)}</li>" for x in stock.checklist)
        extra_blocks.append(
            f'<div class="sub-card" style="margin-top:10px;"><div class="sub-title">{_esc(_c(lang, "checklist"))}</div>'
            f'<ul class="chk-list">{items}</ul></div>'
        )
    if stock.empty_news_disclosure:
        extra_blocks.append(
            f'<div style="margin-top:8px;padding:8px 10px;border-radius:6px;background:var(--warn-bg);border:1px solid var(--warn-bd);font-size:12px;color:var(--warn-fg);">{_esc(stock.empty_news_disclosure)}</div>'
        )
    if stock.data_sources:
        extra_blocks.append(f'<div style="font-size:11px;color:var(--ink-muted);margin-top:6px;">{_esc(_c(lang, "sources"))}: {_esc(stock.data_sources)}</div>')

    return (
        f'<section class="stock-card{urgent_cls}">'
        '<div class="stock-head">'
        '<div class="stock-title">'
        f'<span class="stock-name">{_esc(stock.display_name)}</span>'
        f'<span class="code-pill">{_esc(stock.code)}</span>'
        f"{price_bit}"
        "</div>"
        '<div class="badges">'
        f'<span class="pill {pill_cls}">{_esc(stock.signal_text)}</span>'
        f'<span class="score-pill">{_esc(stock.score_display)}</span>'
        "</div></div>"
        f"{thesis_html}{sniper_html}{snap_html}{pos_html}{cols_html}{attr_html}{''.join(extra_blocks)}"
        "</section>"
    )


def render_standalone_html(
    payload: NotificationReportPayload,
    *,
    title_override: Optional[str] = None,
    market_review_markdown: str = "",
) -> str:
    """Render standalone offline & printable HTML archive document (CSP safe, zero scripts)."""
    lang = payload.report_language
    html_lang = {"zh": "zh-CN", "en": "en", "ko": "ko"}.get(lang, "zh-CN")
    title = title_override or payload.dynamic_title

    if market_review_markdown.strip():
        converted_md = markdown2.markdown(
            market_review_markdown,
            extras=["tables", "fenced-code-blocks", "cuddled-lists"],
            safe_mode="escape",
        )
        sanitized_md = _sanitize_markdown_html_links(converted_md)
        main_body = f'<div class="md-body">{sanitized_md}</div>'
    elif not payload.stocks:
        main_body = f'<p style="color:var(--ink-muted);">{_esc(_c(lang, "no_results"))}</p>'
    else:
        if payload.top_risk_alerts:
            alerts_html = (
                '<div class="alert-box">'
                f'<div class="alert-title">{_esc(_c(lang, "risk_panel_title"))}</div>'
                '<ul style="margin:0;padding-left:18px;font-size:13px;">'
                + "".join(
                    f"<li><strong>[{_esc(e.stock_name)} {_esc(e.stock_code)}]</strong> {_esc(e.message)}</li>"
                    for e in payload.top_risk_alerts
                )
                + "</ul></div>"
            )
        elif payload.risk_checked_count > 0:
            alerts_html = f'<div class="clear-box">{_esc(_c(lang, "risk_clear"))}</div>'
        else:
            alerts_html = ""
        dist_html = _render_score_dist_svg(payload)
        suppress_card_risk = bool(payload.single_stock and payload.top_risk_alerts)
        cards = "".join(
            _render_standalone_stock_card(s, lang, suppress_risk_alerts=suppress_card_risk)
            for s in payload.stocks
        )
        main_body = f"{alerts_html}{dist_html}{cards}"

    sub_bits = [payload.report_date, _c(lang, "print_btn_hint")]
    if payload.market_status_line:
        sub_bits.append(payload.market_status_line)

    footer_bits = [f"{_c(lang, 'model')}: {', '.join(payload.models_used)}"] if payload.models_used else []
    footer_bits.append(payload.generated_at)

    return (
        "<!DOCTYPE html>"
        f'<html lang="{html_lang}">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:;">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(title)}</title>"
        f"<style>{_STANDALONE_CSS}</style>"
        "</head>"
        "<body>"
        '<main class="page">'
        '<div class="banner"></div>'
        '<div class="inner">'
        f'<div class="eyebrow">{_esc(_c(lang, "brand_eyebrow"))}</div>'
        f"<h1>{_esc(title)}</h1>"
        f'<div class="subline">{_esc(" · ".join(sub_bits))}</div>'
        f"{main_body}"
        '<footer class="footer">'
        f"<div>{_esc(' · '.join(footer_bits))}</div>"
        f"<div>{_esc(payload.disclaimer)}</div>"
        "</footer>"
        "</div></main></body></html>"
    )


# ============================================================================
# 3. Feishu Native Interactive Card Renderer
# ============================================================================

def _feishu_kpi_fields(payload: NotificationReportPayload) -> Dict[str, Any]:
    lang = payload.report_language
    if payload.single_stock and payload.stocks:
        s = payload.stocks[0]
        price_str = f"{s.price_display} {s.change_display}".strip() or "—"
        score_str = f"{s.score_display}/100" if s.sentiment_score is not None else "—"
        rr_str = f"1:{s.sniper.risk_reward_ratio:.2f}" if s.sniper.risk_reward_ratio else str(len(s.risk_alerts))
        rr_lbl = _c(lang, "rr") if s.sniper.risk_reward_ratio else _c(lang, "alerts")
        pairs = [
            (_c(lang, "action"), f"{_lark_md_escape(s.signal_emoji)} {_lark_md_escape(s.signal_text)}"),
            (_c(lang, "score"), score_str),
            (_c(lang, "price"), _lark_md_escape(price_str)),
            (rr_lbl, _lark_md_escape(rr_str)),
        ]
    else:
        pairs = [
            (_c(lang, "analyzed"), f"{payload.total_count}"),
            (_c(lang, "buy"), f"{payload.buy_count}"),
            (_c(lang, "watch"), f"{payload.hold_count}"),
            (_c(lang, "sell_alert"), f"{payload.sell_count} / {payload.alert_count}"),
        ]
    return {
        "tag": "div",
        "fields": [
            {
                "is_short": True,
                "text": {"tag": "lark_md", "content": f"**{k}**\n{v}"},
            }
            for k, v in pairs
        ],
    }


def _feishu_stock_elements(
    stock: StockReportItem,
    lang: str,
    *,
    compact: bool = False,
    summary_only: bool = False,
) -> List[Dict[str, Any]]:
    quote_bits = [b for b in (stock.price_display, stock.change_display) if b]
    quote_txt = f" · {' '.join(quote_bits)}" if quote_bits else ""
    safe_name = _lark_md_escape(stock.display_name)
    safe_code = _lark_md_escape(stock.code)
    safe_signal = _lark_md_escape(stock.signal_text)

    if summary_only:
        thesis = _lark_md_escape(_clip(stock.one_sentence or stock.analysis_summary or stock.trend_prediction, 72))
        summary_line = f"**{_lark_md_escape(stock.signal_emoji)} {safe_name} ({safe_code})**{_lark_md_escape(quote_txt)} — {safe_signal} · {stock.score_display}"
        if thesis:
            summary_line += f"\n{thesis}"
        return [{"tag": "div", "text": {"tag": "lark_md", "content": summary_line}}]

    headline = f"**{_lark_md_escape(stock.signal_emoji)} {safe_name} ({safe_code})**{_lark_md_escape(quote_txt)}"
    thesis = _lark_md_escape(_clip(stock.one_sentence or stock.analysis_summary or stock.trend_prediction, 95 if compact else 180))

    elems: List[Dict[str, Any]] = [
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"{headline}\n{thesis}" if thesis else headline},
        }
    ]

    fields: List[Dict[str, Any]] = [
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**{_c(lang, 'action')}**\n{safe_signal} · {stock.score_display}"}},
        {"is_short": True, "text": {"tag": "lark_md", "content": f"**{_c(lang, 'stop_loss')} / {_c(lang, 'take_profit')}**\n{_lark_md_escape(stock.sniper.stop_loss or '—')} / {_lark_md_escape(stock.sniper.take_profit or '—')}"}},
    ]
    if not compact:
        fields.append({"is_short": True, "text": {"tag": "lark_md", "content": f"**{_c(lang, 'ideal_buy')}**\n{_lark_md_escape(stock.sniper.ideal_buy or '—')}"}})
        if stock.sniper.risk_reward_ratio:
            rr_txt = f"1:{stock.sniper.risk_reward_ratio:.2f}"
            zone_txt = _price_zone_badge_text(stock, lang)
            if zone_txt:
                rr_txt = f"{rr_txt} ({zone_txt})"
            fields.append({"is_short": True, "text": {"tag": "lark_md", "content": f"**{_c(lang, 'rr')}**\n{rr_txt}"}})
        elif stock.trend_prediction:
            fields.append({"is_short": True, "text": {"tag": "lark_md", "content": f"**{_c(lang, 'trend_col')}**\n{_lark_md_escape(stock.trend_prediction)}"}})
    elems.append({"tag": "div", "fields": fields})

    if not compact:
        notes: List[str] = []
        if stock.position_advice.no_position:
            notes.append(f"**{_c(lang, 'no_pos')}**: {_lark_md_escape(_clip(stock.position_advice.no_position, 80))}")
        if stock.position_advice.has_position:
            notes.append(f"**{_c(lang, 'has_pos')}**: {_lark_md_escape(_clip(stock.position_advice.has_position, 80))}")
        if stock.risk_alerts:
            notes.append(f"**{_c(lang, 'risks')}**: {_lark_md_escape(_clip('; '.join(stock.risk_alerts[:2]), 110))}")
        if stock.empty_news_disclosure:
            notes.append(_lark_md_escape(stock.empty_news_disclosure))
        if notes:
            elems.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(notes)}})

    return elems


def _feishu_plain_text_for_stocks(
    payload: NotificationReportPayload,
    stocks: Sequence[StockReportItem],
    *,
    keyword: str = "",
    page_suffix: str = "",
) -> str:
    lang = payload.report_language
    lines: List[str] = []
    if keyword:
        lines.append(keyword)
    lines.append(f"{payload.dynamic_title}{page_suffix}")
    for s in stocks:
        price = f" {s.price_display}({s.change_display})" if s.price_display else ""
        lines.append(f"{s.signal_emoji} {s.display_name}({s.code}){price} | {s.signal_text} | {s.score_display}")
        if not payload.summary_only:
            if s.one_sentence:
                lines.append(f"  {_clip(s.one_sentence, 100)}")
            if s.risk_alerts:
                lines.append(f"  [{_c(lang, 'risks')}] {_clip(s.risk_alerts[0], 90)}")
    return "\n".join(lines)


def _assemble_feishu_card(
    payload: NotificationReportPayload,
    stocks: Sequence[StockReportItem],
    *,
    web_url: str,
    keyword: str,
    page_index: int,
    total_pages: int,
    compact: bool = False,
) -> Dict[str, Any]:
    lang = payload.report_language
    suffix = f" ({page_index}/{total_pages})" if total_pages > 1 else ""
    elements: List[Dict[str, Any]] = []

    if keyword:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": keyword}})

    if page_index == 1:
        if payload.market_status_line:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": _lark_md_escape(payload.market_status_line)}})
        elements.append(_feishu_kpi_fields(payload))
        elements.append({"tag": "hr"})
        if payload.top_risk_alerts:
            alert_lines = [f"**{_c(lang, 'risk_panel_title')}**"]
            for entry in payload.top_risk_alerts[: (3 if compact else 6)]:
                alert_lines.append(
                    f"• **[{_lark_md_escape(entry.stock_name)} {_lark_md_escape(entry.stock_code)}]** "
                    f"{_lark_md_escape(_clip(entry.message, 90))}"
                )
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(alert_lines)}})
        elif payload.risk_checked_count > 0:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": _c(lang, "risk_clear")}})

    for idx, stock in enumerate(stocks):
        if elements and (page_index == 1 or idx > 0):
            elements.append({"tag": "hr"})
        elements.extend(
            _feishu_stock_elements(
                stock,
                lang,
                compact=compact,
                summary_only=payload.summary_only,
            )
        )

    if _is_http_url(web_url):
        elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": _c(lang, "open_web")},
                        "type": "primary",
                        "url": web_url,
                    }
                ],
            }
        )

    footer_bits = [f"{_c(lang, 'model')}: {', '.join(payload.models_used)}"] if payload.models_used else []
    footer_bits.append(payload.disclaimer)
    elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": " | ".join(b for b in footer_bits if b)}]})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{payload.dynamic_title}{suffix}"},
            "template": payload.header_tone,
        },
        "elements": elements,
    }


def render_feishu_card_pages(
    payload: NotificationReportPayload,
    *,
    web_url: str = "",
    keyword: str = "",
    max_bytes: int = 20000,
    request_limit: int = 20000,
    request_bytes_fn: Optional[Callable[[Dict[str, Any]], int]] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    """Render Feishu interactive Card JSON pages cleanly budgeted at stock boundaries."""
    resolved_url = web_url or payload.web_url
    measure = request_bytes_fn or (lambda card: len(json.dumps(card, ensure_ascii=False).encode("utf-8")))

    def fits(card: Dict[str, Any], plain: str) -> bool:
        return len(plain.encode("utf-8")) <= max_bytes and measure(card) <= request_limit

    if not payload.stocks:
        card = _assemble_feishu_card(payload, [], web_url=resolved_url, keyword=keyword, page_index=1, total_pages=1)
        plain = _feishu_plain_text_for_stocks(payload, [], keyword=keyword)
        return [(plain, card)]

    # Fast path: entire report fits in 1 card
    single_card = _assemble_feishu_card(payload, payload.stocks, web_url=resolved_url, keyword=keyword, page_index=1, total_pages=1)
    single_plain = _feishu_plain_text_for_stocks(payload, payload.stocks, keyword=keyword)
    if fits(single_card, single_plain):
        return [(single_plain, single_card)]

    # Greedy pagination by stock boundary (assuming N <= len(stocks) max)
    groups: List[List[StockReportItem]] = []
    current: List[StockReportItem] = []
    est_total = max(2, len(payload.stocks))

    for stock in payload.stocks:
        candidate = current + [stock]
        idx = len(groups) + 1
        card = _assemble_feishu_card(
            payload, candidate, web_url=resolved_url, keyword=keyword, page_index=idx, total_pages=est_total
        )
        plain = _feishu_plain_text_for_stocks(payload, candidate, keyword=keyword, page_suffix=f" ({idx}/{est_total})")
        if current and not fits(card, plain):
            groups.append(current)
            current = [stock]
        else:
            current = candidate
    if current:
        groups.append(current)

    total_pages = len(groups)
    pages: List[Tuple[str, Dict[str, Any]]] = []
    for idx, group in enumerate(groups, start=1):
        suffix = f" ({idx}/{total_pages})" if total_pages > 1 else ""
        card = _assemble_feishu_card(
            payload, group, web_url=resolved_url, keyword=keyword, page_index=idx, total_pages=total_pages, compact=False
        )
        plain = _feishu_plain_text_for_stocks(payload, group, keyword=keyword, page_suffix=suffix)
        if not fits(card, plain):
            card = _assemble_feishu_card(
                payload, group, web_url="", keyword=keyword, page_index=idx, total_pages=total_pages, compact=True
            )
            plain = _feishu_plain_text_for_stocks(payload, group, keyword=keyword, page_suffix=suffix)
            while measure(card) > request_limit and len(card.get("elements", [])) > (2 if keyword else 1):
                # Drop non-keyword trailing element (note/hr/optional details) to satisfy request_limit
                removed = card["elements"].pop(-1)
                if removed.get("tag") == "note" and len(card["elements"]) > (2 if keyword else 1):
                    card["elements"].pop(-1)
            while len(plain.encode("utf-8")) > max_bytes and len(plain) > 20:
                plain = plain[: max(1, len(plain) - 100)].rstrip()
            if measure(card) > request_limit:
                raise ValueError("Feishu structured card exceeds request_limit")
        pages.append((plain, card))
    return pages


# ============================================================================
# 4. Telegram Native HTML Renderer
# ============================================================================

def _tg_header_block(payload: NotificationReportPayload) -> Tuple[str, str]:
    lang = payload.report_language
    lines_html = [f"<b>{_esc(payload.dynamic_title)}</b>"]
    lines_plain = [payload.dynamic_title]

    summary_lines = [
        f"{_c(lang, 'analyzed')}: {payload.total_count} · "
        f"{_c(lang, 'buy')}: {payload.buy_count} · "
        f"{_c(lang, 'watch')}: {payload.hold_count} · "
        f"{_c(lang, 'sell_alert')}: {payload.sell_count}/{payload.alert_count}"
    ]
    if payload.market_status_line:
        summary_lines.append(payload.market_status_line)
    if payload.top_risk_alerts:
        summary_lines.append(f"⚠️ {_c(lang, 'risk_panel_title')}:")
        for entry in payload.top_risk_alerts[:3]:
            summary_lines.append(f"• [{entry.stock_name} {entry.stock_code}] {_clip(entry.message, 80)}")
    elif payload.risk_checked_count > 0:
        summary_lines.append(_c(lang, "risk_clear"))

    lines_html.append(f"<blockquote>{_esc(chr(10).join(summary_lines))}</blockquote>")
    lines_plain.extend(summary_lines)
    return "\n".join(lines_html), "\n".join(lines_plain)


def _tg_stock_block(
    stock: StockReportItem,
    lang: str,
    *,
    include_expandable: bool = True,
    summary_only: bool = False,
) -> Tuple[str, str]:
    price_bits = [b for b in (stock.price_display, stock.change_display) if b]
    price_part = f" · {' '.join(price_bits)}" if price_bits else ""
    line1_html = f"{_esc(stock.signal_emoji)} <b>{_esc(stock.display_name)}</b> <code>{_esc(stock.code)}</code>{_esc(price_part)}"
    line1_plain = f"{stock.signal_emoji} {stock.display_name} ({stock.code}){price_part}"

    rr_text = _rr_label(stock, lang)
    rr_part = f" · {rr_text}" if rr_text else ""
    zone_txt = _price_zone_badge_text(stock, lang)
    zone_part = f" · {zone_txt}" if zone_txt else ""
    trend_part = f" · {stock.trend_prediction}" if stock.trend_prediction else ""
    line2_html = f"<b>{_esc(stock.signal_text)}</b> · {_esc(_c(lang, 'score'))} <b>{_esc(stock.score_display)}</b>{_esc(trend_part)}{_esc(rr_part)}{_esc(zone_part)}"
    line2_plain = f"{stock.signal_text} · {_c(lang, 'score')} {stock.score_display}{trend_part}{rr_part}{zone_part}"

    if summary_only:
        thesis_compact = _clip(stock.one_sentence or stock.analysis_summary, 70)
        h_parts = [line1_html, line2_html] + ([_esc(thesis_compact)] if thesis_compact else [])
        p_parts = [line1_plain, line2_plain] + ([thesis_compact] if thesis_compact else [])
        return "\n".join(h_parts), "\n".join(p_parts)

    thesis = _clip(stock.one_sentence or stock.analysis_summary, 140)
    line3_html = _esc(thesis) if thesis else ""
    line3_plain = thesis

    sniper_parts_html: List[str] = []
    sniper_parts_plain: List[str] = []
    for key, val in (
        ("ideal_buy", stock.sniper.ideal_buy),
        ("stop_loss", stock.sniper.stop_loss),
        ("take_profit", stock.sniper.take_profit),
    ):
        if val:
            short_val = _clip(val, 24)
            sniper_parts_html.append(f"{_esc(_c(lang, key))}: <code>{_esc(short_val)}</code>")
            sniper_parts_plain.append(f"{_c(lang, key)}: {short_val}")
    line4_html = " | ".join(sniper_parts_html)
    line4_plain = " | ".join(sniper_parts_plain)

    expand_lines: List[str] = []
    if stock.position_advice.no_position:
        expand_lines.append(f"{_c(lang, 'no_pos')}: {_clip(stock.position_advice.no_position, 90)}")
    if stock.position_advice.has_position:
        expand_lines.append(f"{_c(lang, 'has_pos')}: {_clip(stock.position_advice.has_position, 90)}")
    if stock.risk_alerts:
        expand_lines.append(f"{_c(lang, 'risks')}: {_clip('; '.join(stock.risk_alerts[:2]), 110)}")
    if stock.positive_catalysts:
        expand_lines.append(f"{_c(lang, 'catalysts')}: {_clip('; '.join(stock.positive_catalysts[:2]), 100)}")
    if stock.failed_checks:
        expand_lines.append(f"{_c(lang, 'failed_checks')}: {_clip('; '.join(stock.failed_checks[:2]), 90)}")
    if stock.empty_news_disclosure:
        expand_lines.append(stock.empty_news_disclosure)

    html_parts = [p for p in (line1_html, line2_html, line3_html, line4_html) if p]
    plain_parts = [p for p in (line1_plain, line2_plain, line3_plain, line4_plain) if p]

    if include_expandable and expand_lines:
        body_txt = "\n".join(expand_lines)
        html_parts.append(f"<blockquote expandable>{_esc(body_txt)}</blockquote>")
        plain_parts.extend(expand_lines)

    return "\n".join(html_parts), "\n".join(plain_parts)


def render_telegram_html_chunks(
    payload: NotificationReportPayload,
    *,
    max_utf16_units: int = 4000,
) -> List[Tuple[str, str]]:
    """Render Telegram HTML + plain-text fallback chunks respecting UTF-16 budget."""
    lang = payload.report_language
    header_html, header_plain = _tg_header_block(payload)
    footer_lines: List[str] = []
    if _is_http_url(payload.web_url):
        footer_lines.append(f'<a href="{_esc(payload.web_url)}">{_esc(_c(lang, "open_web"))}</a>')
    if payload.models_used:
        footer_lines.append(f"<i>{_esc(_c(lang, 'model'))}: {_esc(', '.join(payload.models_used))}</i>")
    if payload.disclaimer:
        footer_lines.append(f"<i>{_esc(payload.disclaimer)}</i>")
    footer_html = "\n".join(footer_lines)

    footer_plain_lines = []
    if _is_http_url(payload.web_url):
        footer_plain_lines.append(f"{_c(lang, 'open_web')}: {payload.web_url}")
    if payload.models_used:
        footer_plain_lines.append(f"{_c(lang, 'model')}: {', '.join(payload.models_used)}")
    if payload.disclaimer:
        footer_plain_lines.append(payload.disclaimer)
    footer_plain = "\n".join(footer_plain_lines)

    def _fit_plain_as_html(plain_text: str) -> Tuple[str, str]:
        trimmed = plain_text
        if utf16_len(_esc(trimmed)) <= max_utf16_units:
            return _esc(trimmed), trimmed
        while utf16_len(_esc(trimmed)) > max_utf16_units and len(trimmed) > 20:
            trimmed = trimmed[: max(1, len(trimmed) - 40)].rstrip() + "…"
        while utf16_len(_esc(trimmed)) > max_utf16_units and len(trimmed) > 1:
            trimmed = trimmed[:-1]
        return _esc(trimmed), trimmed

    if not payload.stocks:
        parts_h = [header_html, f"<i>{_esc(_c(lang, 'no_results'))}</i>"] + ([footer_html] if footer_html else [])
        parts_p = [header_plain, _c(lang, "no_results")] + ([footer_plain] if footer_plain else [])
        text_html = "\n\n".join(parts_h)
        text_plain = "\n\n".join(parts_p)
        if utf16_len(text_html) <= max_utf16_units:
            return [(text_html, text_plain)]
        return [_fit_plain_as_html(text_plain)]

    sep = "\n\n"
    blocks = [
        _tg_stock_block(s, lang, include_expandable=True, summary_only=payload.summary_only)
        for s in payload.stocks
    ]
    compact_blocks = [
        _tg_stock_block(s, lang, include_expandable=False, summary_only=payload.summary_only)
        for s in payload.stocks
    ]

    chunks: List[Tuple[str, str]] = []
    cur_html: List[str] = [header_html]
    cur_plain: List[str] = [header_plain]

    def _fit_single(block_html: str, block_plain: str, fallback_html: str, fallback_plain: str) -> Tuple[str, str]:
        if utf16_len(block_html) <= max_utf16_units:
            return block_html, block_plain
        if utf16_len(fallback_html) <= max_utf16_units:
            return fallback_html, fallback_plain
        return _fit_plain_as_html(fallback_plain)

    for idx, (blk_html, blk_plain) in enumerate(blocks):
        candidate = sep.join(cur_html + [blk_html])
        if utf16_len(candidate) <= max_utf16_units:
            cur_html.append(blk_html)
            cur_plain.append(blk_plain)
            continue

        if len(cur_html) > 1 or cur_html[0] != header_html:
            chunks.append((sep.join(cur_html), sep.join(cur_plain)))
            cur_html = []
            cur_plain = []
        else:
            cmp_html, cmp_plain = compact_blocks[idx]
            if utf16_len(sep.join(cur_html + [cmp_html])) <= max_utf16_units:
                cur_html.append(cmp_html)
                cur_plain.append(cmp_plain)
                continue
            chunks.append((sep.join(cur_html), sep.join(cur_plain)))
            cur_html = []
            cur_plain = []

        cmp_html, cmp_plain = compact_blocks[idx]
        fit_html, fit_plain = _fit_single(blk_html, blk_plain, cmp_html, cmp_plain)
        cur_html.append(fit_html)
        cur_plain.append(fit_plain)

    if cur_html:
        if footer_html:
            if utf16_len(sep.join(cur_html + [footer_html])) <= max_utf16_units:
                cur_html.append(footer_html)
                cur_plain.append(footer_plain)
                chunks.append((sep.join(cur_html), sep.join(cur_plain)))
            else:
                chunks.append((sep.join(cur_html), sep.join(cur_plain)))
                chunks.append(
                    (footer_html, footer_plain)
                    if utf16_len(footer_html) <= max_utf16_units
                    else _fit_plain_as_html(footer_plain)
                )
        else:
            chunks.append((sep.join(cur_html), sep.join(cur_plain)))
    elif footer_html:
        chunks.append(
            (footer_html, footer_plain)
            if utf16_len(footer_html) <= max_utf16_units
            else _fit_plain_as_html(footer_plain)
        )

    return chunks


# ============================================================================
# 5. WeChat Work Native Digest Renderer (<font> semantics + 3950-byte budget)
# ============================================================================

def render_wechat_digest_chunks(
    payload: NotificationReportPayload,
    *,
    msg_type: str = "markdown",
    max_bytes: int = 3950,
) -> List[str]:
    """Render high-signal WeChat Work digest chunks within byte budgets."""
    is_text = str(msg_type or "markdown").strip().lower() == "text"
    effective_limit = min(max(300, max_bytes), 1950 if is_text else 3950)
    lang = payload.report_language

    def fmt_tone(text: str, tone: str) -> str:
        if is_text:
            return text
        return f'<font color="{tone}">{text}</font>'

    def bold(text: str) -> str:
        return text if is_text else f"**{text}**"

    def header_block() -> str:
        lines: List[str] = []
        title = payload.dynamic_title if is_text else f"### {payload.dynamic_title}"
        lines.append(title)
        kpi = (
            f"{_c(lang, 'buy')}:{payload.buy_count} | "
            f"{_c(lang, 'watch')}:{payload.hold_count} | "
            f"{_c(lang, 'sell_alert')}:{payload.sell_count}/{payload.alert_count}"
        )
        lines.append(kpi if is_text else f"> {kpi}")
        if payload.market_status_line:
            lines.append(payload.market_status_line if is_text else f"> {payload.market_status_line}")
        if payload.top_risk_alerts:
            lines.append(fmt_tone(f"{_c(lang, 'risk_panel_title')}:", "warning"))
            for entry in payload.top_risk_alerts[:3]:
                lines.append(f"• [{entry.stock_name} {entry.stock_code}] {_clip(entry.message, 65)}")
        elif payload.risk_checked_count > 0:
            lines.append(fmt_tone(_c(lang, "risk_clear"), "info"))
        return "\n".join(lines)

    def stock_block(stock: StockReportItem) -> str:
        if stock.decision_bucket == "sell" or stock.action in {"sell", "reduce"}:
            tone = "warning"
        elif stock.action == "alert":
            tone = "warning"
        elif stock.decision_bucket == "buy" or stock.action in {"buy", "add"}:
            tone = "info"
        else:
            tone = "comment"

        price_part = f" {stock.price_display} {stock.change_display}".strip()
        price_suffix = f" | {price_part}" if price_part else ""
        sig_colored = fmt_tone(f"{stock.signal_text} · {stock.score_display}", tone)
        lines = [
            f"{bold(f'{stock.display_name}({stock.code})')}{price_suffix} — {sig_colored}",
        ]
        if payload.summary_only:
            thesis_short = _clip(stock.one_sentence or stock.analysis_summary or stock.trend_prediction, 60)
            if thesis_short:
                lines.append(thesis_short)
            return "\n".join(lines)

        thesis = _clip(stock.one_sentence or stock.analysis_summary or stock.trend_prediction, 90)
        if thesis:
            lines.append(thesis)

        lvl_bits: List[str] = []
        if stock.sniper.ideal_buy:
            lvl_bits.append(f"{_c(lang, 'ideal_buy')}:{_clip(stock.sniper.ideal_buy, 18)}")
        if stock.sniper.stop_loss:
            lvl_bits.append(f"{_c(lang, 'stop_loss')}:{_clip(stock.sniper.stop_loss, 18)}")
        if stock.sniper.take_profit:
            lvl_bits.append(f"{_c(lang, 'take_profit')}:{_clip(stock.sniper.take_profit, 18)}")
        if stock.sniper.risk_reward_ratio:
            lvl_bits.append(f"R:R 1:{stock.sniper.risk_reward_ratio:.1f}")
        zone_txt = _price_zone_badge_text(stock, lang)
        if zone_txt:
            lvl_bits.append(zone_txt)
        if lvl_bits:
            lines.append(" | ".join(lvl_bits))

        if stock.position_advice.no_position:
            lines.append(f"{_c(lang, 'no_pos')}: {_clip(stock.position_advice.no_position, 55)}")
        if stock.risk_alerts:
            lines.append(fmt_tone(f"{_c(lang, 'risks')}: {_clip(stock.risk_alerts[0], 60)}", "warning"))
        if stock.empty_news_disclosure:
            lines.append(fmt_tone(_clip(stock.empty_news_disclosure, 80), "comment"))
        return "\n".join(lines)

    # Reserve ~18 bytes for optional (i/N) pagination header
    pack_limit = max(200, effective_limit - 18)

    def _split_block_utf8(block: str, limit: int = pack_limit) -> List[str]:
        parts: List[str] = []
        buf: List[str] = []
        for line in block.split("\n"):
            cand = "\n".join(buf + [line])
            if buf and len(cand.encode("utf-8")) > limit:
                parts.append("\n".join(buf))
                buf = [line]
            elif len(line.encode("utf-8")) > limit:
                if buf:
                    parts.append("\n".join(buf))
                    buf = []
                # Strip inline <font> wrapper on ultra-long single line before hard-slicing UTF-8
                rem = re.sub(r"</?font[^>]*>", "", line)
                while rem:
                    cut = len(rem)
                    while len(rem[:cut].encode("utf-8")) > limit and cut > 1:
                        cut = max(1, cut - max(1, (len(rem[:cut].encode("utf-8")) - limit) // 3))
                    parts.append(rem[:cut])
                    rem = rem[cut:]
            else:
                buf.append(line)
        if buf:
            parts.append("\n".join(buf))
        return parts

    hdr = header_block()
    if not payload.stocks:
        single = f"{hdr}\n\n{_c(lang, 'no_results')}"
        if len(single.encode("utf-8")) <= effective_limit:
            return [single]
        return _split_block_utf8(single, limit=effective_limit)

    blocks = [hdr] + [stock_block(s) for s in payload.stocks]
    footer_bits = [f"{_c(lang, 'model')}: {', '.join(payload.models_used)}"] if payload.models_used else []
    footer_bits.append(payload.disclaimer)
    footer = " | ".join(b for b in footer_bits if b)
    if footer:
        blocks.append(footer if is_text else fmt_tone(footer, "comment"))

    raw_chunks: List[str] = []
    current_parts: List[str] = []

    for block in blocks:
        candidate = "\n\n".join(current_parts + [block])
        if len(candidate.encode("utf-8")) <= pack_limit:
            current_parts.append(block)
            continue
        if current_parts:
            raw_chunks.append("\n\n".join(current_parts))
            current_parts = []
        if len(block.encode("utf-8")) <= pack_limit:
            current_parts.append(block)
        else:
            sub_parts = _split_block_utf8(block)
            raw_chunks.extend(sub_parts[:-1])
            if sub_parts:
                current_parts.append(sub_parts[-1])

    if current_parts:
        raw_chunks.append("\n\n".join(current_parts))

    if len(raw_chunks) <= 1:
        return raw_chunks

    total = len(raw_chunks)
    paged: List[str] = []
    for idx, chunk in enumerate(raw_chunks, start=1):
        marker = f"({idx}/{total})\n"
        lines = chunk.split("\n")
        text = marker + "\n".join(lines)
        while len(text.encode("utf-8")) > effective_limit and len(lines) > 1:
            lines.pop()
            text = marker + "\n".join(lines)
        while len(text.encode("utf-8")) > effective_limit and len(text) > len(marker) + 10:
            # Remove any <font> wrapper first so slicing never produces unclosed XML/HTML tags
            stripped = re.sub(r"</?font[^>]*>", "", "\n".join(lines))
            text = marker + stripped
            while len(text.encode("utf-8")) > effective_limit and len(text) > len(marker) + 10:
                text = text[:-10].rstrip()
            break
        paged.append(text)
    return paged
