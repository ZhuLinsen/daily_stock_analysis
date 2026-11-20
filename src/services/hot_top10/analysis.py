# -*- coding: utf-8 -*-
"""Hot-top10 analysis layer: ONE LLM call produces the whole report
(per-theme driver / strength / entry advice / risk). LLM failures degrade to
a data-only overview — never raised into the caller."""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.services.hot_top10.datasource import format_change_pct

logger = logging.getLogger(__name__)


def build_analyzer(config: Any):
    from src.analyzer import GeminiAnalyzer

    return GeminiAnalyzer(config=config)


def build_hot_top10_prompt(items: List[Dict[str, Any]]) -> str:
    lines = ["你是 A 股市场热点分析助手。以下是市场主题热榜（按涨跌幅排名，来自 DSA 行业/概念排名数据）：", ""]
    for item in items:
        lines.append(
            f"{item['rank']}. {item['name']}（{item['kind']}）涨跌幅 "
            f"{format_change_pct(item['change_pct'])}，阶段 {item['phase']}"
        )
    lines += [
        "",
        "请针对每个主题输出：热榜动因（新闻/资金/事件归因，无明确信息来源时标注“推测”）、"
        "强度评估（强/中/弱）、介入建议（观望/轻仓介入/积极介入）、风险提示。",
        "严格只输出以下 JSON，不要输出任何多余文本：",
        '{"summary": "一段话总结热点主线与整体参与度", "items": [{"rank": 1, "name": "主题名", '
        '"driver": "动因", "strength": "强|中|弱", "advice": "观望|轻仓介入|积极介入", '
        '"risk": "风险提示"}]}',
    ]
    return "\n".join(lines)


def parse_llm_summary(text: Any) -> Optional[Dict[str, Any]]:
    """Robustly extract the summary JSON object; ``None`` when unusable."""
    if not isinstance(text, str) or not text.strip():
        return None
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    cleaned = fence.group(1).strip() if fence else text[text.find("{"): text.rfind("}") + 1]
    if not cleaned.startswith("{"):
        return None
    try:
        payload = json.loads(cleaned)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("items"), list):
        payload["items"] = []
    return payload


def render_hot_top10_report(items, summary, llm_completed) -> str:
    """Render the zh markdown report; degraded to data-only when LLM failed."""
    indexed = {
        str(entry["name"]).strip(): entry
        for entry in (summary or {}).get("items") or []
        if isinstance(entry, dict) and str(entry.get("name") or "").strip()
    }
    lines = [
        f"# 市场热榜 Top {len(items)} 分析 — {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "> 生成时间：%s ｜ 数据来源：DSA 行业/概念排名。本报告为热榜轻量概览，非个股深度报告。"
        % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "", "## 热点总览", "",
        str((summary or {}).get("summary") or "").strip()
        or ("> 本次 AI 摘要生成失败，以下为数据概览（降级交付）。" if not llm_completed else "-"),
        "", "## 逐项分析", "",
        "| 排名 | 主题 | 涨跌幅 | 热榜动因 | 强度评估 | 介入建议 | 风险提示 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        entry = indexed.get(item["name"], {})
        lines.append(
            f"| {item['rank']} | {item['name']}（{item['kind']}） | {format_change_pct(item['change_pct'])} "
            f"| {str(entry.get('driver') or '').strip() or item.get('reason') or 'AI 摘要缺失'} "
            f"| {str(entry.get('strength') or '').strip() or '-'} "
            f"| {str(entry.get('advice') or '').strip() or '观望'} "
            f"| {str(entry.get('risk') or '').strip() or '动因不明确，注意追高风险'} |"
        )
    lines.append("")
    return "\n".join(lines)
