# -*- coding: utf-8 -*-
"""消息面汇总 · 源抓取适配层（issue #2184）：条目规范化与本地资讯池采集。

时效口径（OR-COR-e5070d9a）：以 published_at 为准；缺失回退 fetched_at 并
显式计数（V5）——fetch_enabled_sources() 会刷新旧文章的 fetched_at，绝不能
以 fetched_at 作为时效窗口。时区口径（OR-COR-2f1e978e）：published_at 为
UTC 无时区、fetched_at 为本地无时区，cutoff 分口径对齐。搜索腿为后续 PR。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

_TRUNCATE_TITLE = 90
_TRUNCATE_SNIPPET = 220
_TRUNCATE_SOURCE = 60
_FEED_LOOKBACK_HOURS = 48
_FEED_PAGE_SIZE = 100  # 对齐真实仓储钳制上限（intelligence_repo.list_items）
_FEED_MAX_PAGES = 10   # 翻页安全上限：最多回读 10 页，防患异常大池
_CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset({"utm", "spm"})


def compact_field(value: Any, limit: int) -> str:
    """剥控制字符、折叠空白并截断到 limit（含省略号）。"""
    text = " ".join(_CONTROL_CHARS_PATTERN.sub(" ", str(value or "")).split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def clean_link(value: Any) -> str:
    """链接清洗：仅去控制字符、折叠空白；绝不截断（截断含省略号会破坏
    链接可达性与去重身份，OR-COR-45e659d1）。"""
    return " ".join(_CONTROL_CHARS_PATTERN.sub(" ", str(value or "")).split())


def parse_published_datetime(value: Any) -> Optional[datetime]:
    """发布时间规范化：仅接受 datetime；tz-aware 统一转 UTC 无时区（资讯池
    intelligence_service._parse_datetime 的落库口径），naive 原样透传，其余 None。"""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def normalize_url(url: str) -> Optional[str]:
    """URL 规范化（去重主键，OR-COR-45e659d1 最小归一化）：仅小写 scheme/host、
    去 fragment、去跟踪参数（utm_* / spm）、去路径尾斜杠；保留 path/query 的
    原始大小写与区分性参数，绝不合并不同文章。"""
    text = str(url or "").strip()
    if not text:
        return None
    try:
        parts = urlsplit(text)
    except ValueError:
        return text
    query_pairs = [
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not (key.lower().startswith(_TRACKING_PARAM_PREFIXES) or key.lower() in _TRACKING_PARAMS)
    ]
    normalized = urlunsplit((
        parts.scheme.lower(), parts.netloc.lower(),
        parts.path.rstrip("/"), urlencode(query_pairs), "",
    ))
    return normalized or None


@dataclass
class NewsDigestEntry:
    """汇总条目；构造时即完成逐字段截断与控制字符清洗（长度上界保证；
    URL 例外——仅清洗、不截断，保持链接可达与去重身份）。"""

    title: str
    snippet: str
    url: str
    source: str
    published_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        self.title = compact_field(self.title, _TRUNCATE_TITLE)
        self.snippet = compact_field(self.snippet, _TRUNCATE_SNIPPET)
        self.url = clean_link(self.url)
        self.source = compact_field(self.source, _TRUNCATE_SOURCE)
        self.published_at = parse_published_datetime(self.published_at)


def collect_feed_entries(
    intelligence_service: Any,
    *,
    now: datetime,
    lookback_hours: int = _FEED_LOOKBACK_HOURS,
) -> Tuple[List[NewsDigestEntry], bool, int]:
    """资讯池采集：刷新落库后按需翻页回读，发布时间为权威时效口径。

    返回 (entries, feed_ok, fallback_count)。逐行按口径 cutoff 复核
    （published_at 用 UTC、fetched_at 用本地，OR-COR-2f1e978e）：发布时间超窗
    的旧闻即使 fetched_at 刚刷新也不进池（e5070d9a）；发布时间缺失按
    fetched_at 口径保留并计入 fallback（V5）。翻页直至覆盖 total 或页提前
    结束（OR-COR-7cf03c1e）。刷新/回读失败按空池处理（fail-open，不致命）。
    """
    if intelligence_service is None:
        return [], False, 0
    try:
        intelligence_service.fetch_enabled_sources()
    except Exception as exc:  # noqa: BLE001 - 池刷新失败不致命
        logger.warning("NEWS_DIGEST 资讯池刷新失败，按空池处理: %s", exc)
        return [], False, 0
    # 按需翻页（OR-COR-7cf03c1e）：真实仓储 page_size 钳 100 且先排序分页，
    # 只读第一页再去重会让后页窗口内有效新闻在摘要未满时被遗漏。翻页直至
    # 覆盖 total 或页提前结束（_FEED_MAX_PAGES 兜底），去重仍在窗口层统一进行。
    rows: List[Any] = []
    total: Optional[int] = None
    page = 1
    while page <= _FEED_MAX_PAGES:
        try:
            page_rows, page_total = intelligence_service.repo.list_items(
                days=max(1, -(-int(lookback_hours) // 24)), page=page, page_size=_FEED_PAGE_SIZE,
            )
        except Exception as exc:  # noqa: BLE001 - 回读失败不致命
            logger.warning("NEWS_DIGEST 资讯池回读失败，按空池处理: %s", exc)
            return [], False, 0
        rows.extend(page_rows or [])
        if total is None:
            total = int(page_total or 0)
        if not page_rows or len(page_rows) < _FEED_PAGE_SIZE or len(rows) >= total:
            break
        page += 1

    # 时区口径（OR-COR-2f1e978e）：池内 published_at 为 UTC 无时区（既有解析链路
    # 统一转 UTC 落库），fetched_at 为本地无时区（ORM default=datetime.now）。
    # cutoff 必须分口径对齐，禁止本地 cutoff 与 UTC 发布时间混用。
    lookback = timedelta(hours=max(1, int(lookback_hours)))
    published_cutoff = now.astimezone(timezone.utc).replace(tzinfo=None) - lookback
    fetched_cutoff = now.astimezone().replace(tzinfo=None) - lookback
    entries: List[NewsDigestEntry] = []
    fallback_count = 0
    for row in (rows or []):
        published = parse_published_datetime(getattr(row, "published_at", None))
        if published is not None and published < published_cutoff:
            continue  # 旧闻超窗：即使 fetched_at 刚刷新也不进池（e5070d9a）
        if published is None:
            fetched = parse_published_datetime(getattr(row, "fetched_at", None))
            if fetched is not None and fetched < fetched_cutoff:
                continue
            fallback_count += 1  # V5：缺失发布时间，按抓取口径纳入并计数
        entries.append(NewsDigestEntry(
            title=getattr(row, "title", ""), snippet=getattr(row, "summary", ""),
            url=getattr(row, "url", ""), source=getattr(row, "source", ""),
            published_at=published,
        ))
    if fallback_count:
        logger.info("NEWS_DIGEST 资讯池 %d 条缺失发布时间，按抓取时间口径纳入", fallback_count)
    return entries, True, fallback_count
