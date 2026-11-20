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
    digest_limit: Optional[int] = None,
    market: str = "cn",
) -> Tuple[List[NewsDigestEntry], bool, int]:
    """资讯池采集：刷新落库后按需翻页回读，发布时间为权威时效口径。

    返回 (entries, feed_ok, fallback_count)。逐行按口径 cutoff 复核
    （published_at 用 UTC、fetched_at 用本地，OR-COR-2f1e978e）：发布时间超窗
    的旧闻即使 fetched_at 刚刷新也不进池（e5070d9a）；发布时间缺失按
    fetched_at 口径保留并计入 fallback（V5）；发布时间晚于运行时刻的“未来
    新闻”同样不进池、不占名额（OR-COR-f7b1824e 上界）。回读查询固定
    market=cn（OR-COR-9ca4e2b1：其他市场的个股资讯不得挤占 A 股摘要名额）
    并携带由运行时刻推得的固定 fetched_since 下界（OR-COR-f7b1824e：仓储
    days 预筛以逐次查询时刻为基准，刷新耗时会收紧下界、在逐行复核前误删
    刚过下界的合格新闻）。翻页不设固定页数上限，终止条件只有三个
    （OR-COR-7cf03c1e）：① 覆盖 total；② 页提前结束；③ 调用方提供
    digest_limit 且去重后条数已达上限——真实仓储按最新优先排序，未读行
    排序必在已读行之后，提前停止不会改变合并结果。刷新/回读失败按空池处理
    （fail-open，不致命）。
    """
    if intelligence_service is None:
        return [], False, 0
    try:
        refresh = intelligence_service.fetch_enabled_sources()
    except Exception as exc:  # noqa: BLE001 - 池刷新失败不致命
        logger.warning("NEWS_DIGEST 资讯池刷新失败，按空池处理: %s", exc)
        return [], False, 0
    all_sources_failed = _refresh_all_sources_failed(refresh)
    # 时区口径（OR-COR-2f1e978e）：池内 published_at 为 UTC 无时区（既有解析链路
    # 统一转 UTC 落库），fetched_at 为本地无时区（ORM default=datetime.now）。
    # cutoff 必须分口径对齐，禁止本地 cutoff 与 UTC 发布时间混用。
    lookback = timedelta(hours=max(1, int(lookback_hours)))
    published_cutoff = now.astimezone(timezone.utc).replace(tzinfo=None) - lookback
    published_upper = now.astimezone(timezone.utc).replace(tzinfo=None)
    fetched_cutoff = now.astimezone().replace(tzinfo=None) - lookback
    # 按需翻页（OR-COR-7cf03c1e）：真实仓储 page_size 钳 100 且先排序分页，
    # 固定页数上限会在高重复大池去重未满时静默遗漏后页有效新闻，故仅以上述
    # 三个自然条件终止；去重计数与窗口层 merge_entries 的存活口径逐条一致
    # （规范化 URL 去重、缺失 URL 不去重），去重本身仍由窗口层统一进行。
    limit = None if digest_limit is None else max(1, int(digest_limit))
    read_count = 0
    total: Optional[int] = None
    page = 1
    entries: List[NewsDigestEntry] = []
    fallback_count = 0
    seen_urls: set = set()
    deduped_count = 0
    while True:
        try:
            page_rows, page_total = intelligence_service.repo.list_items(
                market=market, fetched_since=fetched_cutoff,
                page=page, page_size=_FEED_PAGE_SIZE,
            )
        except Exception as exc:  # noqa: BLE001 - 回读失败不致命
            logger.warning("NEWS_DIGEST 资讯池回读失败，按空池处理: %s", exc)
            return [], False, 0
        page_rows = list(page_rows or [])
        read_count += len(page_rows)
        if total is None:
            total = int(page_total or 0)
        for row in page_rows:
            published = parse_published_datetime(getattr(row, "published_at", None))
            if published is not None and published < published_cutoff:
                continue  # 旧闻超窗：即使 fetched_at 刚刷新也不进池（e5070d9a）
            if published is not None and published > published_upper:
                continue  # 未来新闻不进池（OR-COR-f7b1824e：逐行复核需发布上界）
            if published is None:
                fetched = parse_published_datetime(getattr(row, "fetched_at", None))
                if fetched is not None and fetched < fetched_cutoff:
                    continue
                fallback_count += 1  # V5：缺失发布时间，按抓取口径纳入并计数
            entry = NewsDigestEntry(
                title=getattr(row, "title", ""), snippet=getattr(row, "summary", ""),
                url=getattr(row, "url", ""), source=getattr(row, "source", ""),
                published_at=published,
            )
            entries.append(entry)
            url_key = normalize_url(entry.url)
            if url_key is None or url_key not in seen_urls:
                deduped_count += 1  # 与 merge_entries 存活口径一致的去重计数
            if url_key is not None:
                seen_urls.add(url_key)
        if not page_rows or len(page_rows) < _FEED_PAGE_SIZE or read_count >= total:
            break  # 覆盖 total / 页提前结束
        if limit is not None and deduped_count >= limit:
            break  # 去重后摘要额已满（OR-COR-7cf03c1e 第二停止条件）
        page += 1

    if fallback_count:
        logger.info("NEWS_DIGEST 资讯池 %d 条缺失发布时间，按抓取时间口径纳入", fallback_count)
    if all_sources_failed and not entries:
        # OR-COR-d539c8a1：刷新服务把单源失败收进 results[].ok=False 而顶层恒
        # ok=True，采集层此前丢弃该返回值；全部启用来源失败且池内无窗口内条目
        # 时，采集失败不得伪装成“合法空池”返回成功（否则空摘要占用当日名额，
        # 来源恢复后的再次运行命中 already_claimed 无法补发）。池内有真实条目
        # 时摘要内容真实，仍按成功处理（见 test_feed_refresh_all_failed_but_pool_has_entries_still_ok）。
        logger.warning(
            "NEWS_DIGEST 刷新显示全部启用来源失败且池内无窗口内条目，按采集失败处理"
        )
        return [], False, 0
    return entries, True, fallback_count


def _refresh_all_sources_failed(refresh: Any) -> bool:
    """OR-COR-d539c8a1：识别 fetch_enabled_sources 结构化结果中的“全部来源失败”。

    真实实现（intelligence_service.fetch_enabled_sources）顶层恒 ok=True，
    单源失败只体现在 results[].ok=False。仅当至少有一个可识别的来源结果且
    全部失败时才判定失败：results 为空（未启用来源）或结构不可识别（旧测试
    替身）时返回 False，空池是否合法交由回读结果判定。"""
    if not isinstance(refresh, dict):
        return False
    results = refresh.get("results")
    if not isinstance(results, list) or not results:
        return False
    source_results = [item for item in results if isinstance(item, dict) and "ok" in item]
    if not source_results:
        return False
    return all(not item.get("ok") for item in source_results)
