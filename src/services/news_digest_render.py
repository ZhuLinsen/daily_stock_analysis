# -*- coding: utf-8 -*-
"""消息面汇总 · 摘要生成层（issue #2184）。

模板摘要（无外部依赖、确定性输出）：上下文头注 + 按来源分组正文 + 新鲜度
脚注（携带 V5 回退条数标注）。LLM 摘要与英文本地化为后续 PR。"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from typing import List, Optional

from src.services.news_digest_sources import NewsDigestEntry
from src.services.news_digest_window import NewsDigestContext

_CONTEXT_LABELS_ZH = {"premarket": "盘前", "weekend": "周末", "holiday": "节假日"}
_NEWS_DIGEST_EMPTY_DISCLOSURE_ZH = "本时段未收集到近 48 小时内的资讯条目；为避免误导，本份摘要不含任何推测内容。"


def _render_digest_footer(now: datetime, feed_count: int, fallback_count: int) -> str:
    """新鲜度脚注；fallback_count > 0 时显式标注回退口径（V5，绝不静默）。"""
    parts = [f"生成时间 {now:%Y-%m-%d %H:%M}（本地时区）", f"资讯池条目/{feed_count}"]
    if fallback_count:
        parts.append(f"其中 {fallback_count} 条缺失发布时间、按抓取时间口径纳入")
    return "｜".join(parts)


def _render_template_body(entries: List[NewsDigestEntry]) -> str:
    if not entries:
        return _NEWS_DIGEST_EMPTY_DISCLOSURE_ZH
    groups: "OrderedDict[str, List[NewsDigestEntry]]" = OrderedDict()
    for entry in entries:
        groups.setdefault(entry.source or "未知来源", []).append(entry)
    lines: List[str] = []
    for source, group in groups.items():
        lines.append(f"## 来源：{source}")
        for index, entry in enumerate(group, 1):
            title_part = f"[{entry.title}]({entry.url})" if entry.url else entry.title
            time_part = f"（{entry.published_at:%Y-%m-%d %H:%M}）" if entry.published_at else ""
            snippet_part = f" — {entry.snippet}" if entry.snippet else ""
            lines.append(f"- {index}. {title_part}{time_part}{snippet_part}")
    return "\n".join(lines)


def generate_template_digest(
    entries: List[NewsDigestEntry],
    context: NewsDigestContext,
    *,
    now: Optional[datetime] = None,
    feed_count: int = 0,
    fallback_count: int = 0,
) -> str:
    """模板摘要：头注上下文标签 + 分组正文 + 新鲜度脚注（含 V5 回退标注）。"""
    moment = now or datetime.now()
    label = _CONTEXT_LABELS_ZH.get(context.kind, context.kind)
    header = f"# 消息面汇总（{label}）{context.date:%Y-%m-%d}"
    body = _render_template_body(entries)
    footer = _render_digest_footer(moment, feed_count, fallback_count)
    return f"{header}\n\n{body}\n\n{footer}"
