# -*- coding: utf-8 -*-
"""消息面汇总单元测试（issue #2184，v2 精简版）。

- 全部时间注入固定 datetime；协作者（资讯池/通知）用仓内记录桩；
  零网络、零真实 LLM、零 Config 单例依赖。
- OR 回归覆盖：e5070d9a（published_at 口径）、4c0e3220/e2e5dd13（发送失败
  释放 claim）、860c1e1a（同日至多一份，无 force 绕过面）、7f5b2d19（v2 不写
  分析历史，结构性消除）；849edf8d/000c926a 见 tests/test_news_digest_config.py。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from datetime import time as dtime
from datetime import timezone
from types import SimpleNamespace

import pytest

import src.services.news_digest_service as news_digest_service
from src.services.news_digest_render import (
    _render_digest_footer,
    generate_template_digest,
)
from src.services.news_digest_sources import (
    _TRUNCATE_SNIPPET,
    _TRUNCATE_SOURCE,
    _TRUNCATE_TITLE,
    _TRUNCATE_URL,
    NewsDigestEntry,
    collect_feed_entries,
    compact_field,
)
from src.services.news_digest_window import (
    NewsDigestContext,
    claim_news_digest_date,
    merge_entries,
    release_news_digest_date,
    resolve_news_digest_context,
)
from src.services.news_digest_service import run_news_digest_once

pytestmark = pytest.mark.unit

# 固定时钟：2026-10-20 周二（交易日），2026-10-24 周六。
TUESDAY_PREMARKET = datetime(2026, 10, 20, 8, 30)
TUESDAY_AFTER_WINDOW = datetime(2026, 10, 20, 9, 20)
SATURDAY_IN_WINDOW = datetime(2026, 10, 24, 10, 0)
SUNDAY_BEFORE_WINDOW = datetime(2026, 10, 25, 7, 0)
PREMARKET_WINDOW = "08:00-09:15"
OFFDAY_WINDOW = "09:00-18:00"


# ---------------------------------------------------------------------------
# stubs
# ---------------------------------------------------------------------------


class StubIntelligenceService:
    """fetch_enabled_sources + repo.list_items 记录桩（查询返回全量 rows）。"""

    def __init__(self, rows=None, fetch_error=None, list_error=None):
        self.rows = list(rows or [])
        self._fetch_error = fetch_error
        self._list_error = list_error
        self.fetch_called = False
        self.list_calls = []
        self.repo = SimpleNamespace(list_items=self._list_items)

    def fetch_enabled_sources(self):
        self.fetch_called = True
        if self._fetch_error is not None:
            raise self._fetch_error
        return {"ok": True, "source_count": 1, "results": [], "saved_count": 0}

    def _list_items(self, **kwargs):
        if self._list_error is not None:
            raise self._list_error
        self.list_calls.append(dict(kwargs))
        return list(self.rows), len(self.rows)


class StubNotifier:
    """send 可配置成功/失败/抛错的记录桩：send_result=False 模拟所有渠道失败。"""

    def __init__(self, send_result=True, error=None):
        self.send_result = send_result
        self._error = error
        self.calls = []

    def send(self, content, **kwargs):
        self.calls.append(dict(kwargs, content=content))
        if self._error is not None:
            raise self._error
        return self.send_result


_ROW_ID = 0


def _feed_row(title, url, summary="池内摘要", source="华尔街见闻",
              published_at=None, fetched_at=None):
    global _ROW_ID
    _ROW_ID += 1
    return SimpleNamespace(
        id=_ROW_ID,
        title=title, summary=summary, url=url, source=source,
        published_at=published_at, fetched_at=fetched_at,
    )


def _config(tmp_path=None, **overrides):
    values = {
        "news_digest_enabled": True,
        "news_digest_premarket_window": PREMARKET_WINDOW,
        "news_digest_offday_window": OFFDAY_WINDOW,
        "news_digest_max_news": 12,
        "report_language": "zh",
    }
    if tmp_path is not None:
        values["database_path"] = str(tmp_path / "digest.db")
    values.update(overrides)
    return SimpleNamespace(**values)


def _entry(title="标题", snippet="摘要", url="https://news.cn/a", source="来源",
           published_at=None):
    return NewsDigestEntry(
        title=title, snippet=snippet, url=url, source=source, published_at=published_at,
    )


def _claim_count(db_path):
    connection = sqlite3.connect(str(db_path))
    try:
        exists = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='news_digest_claims'"
        ).fetchone()
        if not exists:
            return 0
        return connection.execute("SELECT COUNT(*) FROM news_digest_claims").fetchone()[0]
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# 时段判定组
# ---------------------------------------------------------------------------


def test_weekend_saturday_in_offday_window():
    context = resolve_news_digest_context(SATURDAY_IN_WINDOW, region="cn")
    assert context is not None
    assert context.kind == "weekend"
    assert context.window_start == dtime(9, 0)
    assert context.window_end == dtime(18, 0)


def test_weekend_before_window_none():
    assert resolve_news_digest_context(SUNDAY_BEFORE_WINDOW, region="cn") is None


def test_holiday_via_calendar_stub():
    context = resolve_news_digest_context(
        TUESDAY_PREMARKET.replace(hour=10, minute=0),  # 需落在 offday 窗口内
        region="cn", is_trading_day=lambda check_date: False,
    )
    assert context is not None
    assert context.kind == "holiday"


def test_trading_day_premarket_in_window():
    context = resolve_news_digest_context(
        TUESDAY_PREMARKET, region="cn", is_trading_day=lambda check_date: True,
    )
    assert context is not None
    assert context.kind == "premarket"


def test_trading_day_outside_window_none():
    assert resolve_news_digest_context(
        TUESDAY_AFTER_WINDOW, region="cn", is_trading_day=lambda check_date: True,
    ) is None


def test_window_start_inclusive_end_exclusive():
    check = lambda check_date: True  # noqa: E731
    assert resolve_news_digest_context(
        TUESDAY_PREMARKET.replace(hour=8, minute=0), region="cn", is_trading_day=check,
    ) is not None
    assert resolve_news_digest_context(
        TUESDAY_PREMARKET.replace(hour=9, minute=15), region="cn", is_trading_day=check,
    ) is None


def test_invalid_window_falls_back_to_default():
    context = resolve_news_digest_context(
        SATURDAY_IN_WINDOW, region="cn", offday_window="bad-window",
    )
    assert context is not None
    assert context.window_start == dtime(9, 0)


def test_cross_midnight_window_rejected():
    # start>=end（含跨午夜）一律非法：回退默认窗口后仍按默认判定
    context = resolve_news_digest_context(
        TUESDAY_PREMARKET, region="cn", premarket_window="22:00-06:00",
    )
    assert context is not None
    assert context.kind == "premarket"
    assert context.window_start == dtime(8, 0)


# ---------------------------------------------------------------------------
# claim 组
# ---------------------------------------------------------------------------


def test_claim_first_true_second_false(tmp_path):
    db_path = tmp_path / "claims.db"
    assert claim_news_digest_date(db_path, "2026-10-20", "cn", "premarket") is True
    assert claim_news_digest_date(db_path, "2026-10-20", "cn", "premarket") is False


def test_claim_survives_reconnect(tmp_path):
    db_path = tmp_path / "claims.db"
    assert claim_news_digest_date(db_path, "2026-10-20") is True
    assert claim_news_digest_date(db_path, "2026-10-20") is False


def test_claim_different_date_true(tmp_path):
    db_path = tmp_path / "claims.db"
    assert claim_news_digest_date(db_path, "2026-10-20") is True
    assert claim_news_digest_date(db_path, "2026-10-21") is True


def test_release_allows_reclaim(tmp_path):
    db_path = tmp_path / "claims.db"
    assert claim_news_digest_date(db_path, "2026-10-20") is True
    assert release_news_digest_date(db_path, "2026-10-20") is True
    assert claim_news_digest_date(db_path, "2026-10-20") is True


# ---------------------------------------------------------------------------
# 条目规范化与去重合并组
# ---------------------------------------------------------------------------


def test_field_truncation_and_control_char_strip_at_construction():
    entry = NewsDigestEntry(
        title="标题\x00" + "长" * 120,
        snippet="摘要\x07" + "细" * 300,
        url="https://example.com/" + "p" * 200,
        source="源\x1b" + "名" * 80,
    )
    assert "\x00" not in entry.title and "\x07" not in entry.snippet
    assert "\x1b" not in entry.source
    assert len(entry.title) <= _TRUNCATE_TITLE
    assert len(entry.snippet) <= _TRUNCATE_SNIPPET
    assert len(entry.url) <= _TRUNCATE_URL
    assert len(entry.source) <= _TRUNCATE_SOURCE
    assert compact_field("a\x00b", 10) == "a b"


def test_dedup_by_normalized_url():
    kept = merge_entries(
        [
            _entry("标题一", url="https://n.cn/1?utm=x"),
            _entry("标题二", url="https://N.cn/1"),  # 规范化后 URL 撞车
            _entry("标题三", url="https://n.cn/3#frag"),
            _entry("标题四", url="https://n.cn/3"),  # 同上，fragment/尾斜杠规范化后撞车
            _entry("无链接条目", url=""),
        ],
        limit=10,
    )
    assert len(kept) == 3
    assert [item.title for item in kept] == ["标题一", "标题三", "无链接条目"]


def test_total_capped_to_max_news():
    entries = [_entry(f"标题{i}", url=f"https://n.cn/{i}") for i in range(20)]
    assert len(merge_entries(entries, limit=5)) == 5
    assert len(merge_entries(entries, limit=0)) == 1  # 非法下限钳到 1


# ---------------------------------------------------------------------------
# 资讯池采集组（OR-COR-e5070d9a published_at 口径 + V5 回退）
# ---------------------------------------------------------------------------


def test_feed_none_service_yields_empty():
    assert collect_feed_entries(None, now=TUESDAY_PREMARKET) == ([], False, 0)


def test_feed_error_yields_empty():
    stub = StubIntelligenceService(fetch_error=RuntimeError("fetch boom"))
    entries, feed_ok, fallback = collect_feed_entries(stub, now=TUESDAY_PREMARKET)
    assert (entries, feed_ok, fallback) == ([], False, 0)


def test_feed_readback_failure_yields_empty():
    stub = StubIntelligenceService(list_error=RuntimeError("list boom"))
    entries, feed_ok, fallback = collect_feed_entries(stub, now=TUESDAY_PREMARKET)
    assert (entries, feed_ok, fallback) == ([], False, 0)


def test_feed_readback_queries_fetched_window():
    stub = StubIntelligenceService(rows=[])
    collect_feed_entries(stub, now=TUESDAY_PREMARKET)
    assert stub.list_calls == [{"days": 2, "page": 1, "page_size": 200}]


def test_stale_published_excluded_even_if_fetched_now():
    """OR-COR-e5070d9a 回归：一周前发布的旧文，fetched_at 刚刷新 → 不进池。"""
    stale = _feed_row(
        "一周前旧闻", "https://f.cn/stale",
        published_at=TUESDAY_PREMARKET - timedelta(days=7),
        fetched_at=TUESDAY_PREMARKET,  # 刚被抓取刷新
    )
    entries, feed_ok, fallback = collect_feed_entries(
        StubIntelligenceService(rows=[stale]), now=TUESDAY_PREMARKET,
    )
    assert feed_ok is True
    assert entries == []
    assert fallback == 0


def test_missing_published_falls_back_with_count():
    """V5 回归：发布时间缺失 → 按 fetched_at 口径纳入且 fallback 计数正确。"""
    fresh_missing = _feed_row(
        "缺发布时间的新抓", "https://f.cn/nopub",
        published_at=None, fetched_at=TUESDAY_PREMARKET,
    )
    in_window = _feed_row(
        "窗内新闻", "https://f.cn/in",
        published_at=TUESDAY_PREMARKET - timedelta(hours=2),
    )
    entries, feed_ok, fallback = collect_feed_entries(
        StubIntelligenceService(rows=[fresh_missing, in_window]), now=TUESDAY_PREMARKET,
    )
    assert feed_ok is True
    assert fallback == 1
    titles = {entry.title for entry in entries}
    assert titles == {"缺发布时间的新抓", "窗内新闻"}
    missing_entry = next(entry for entry in entries if entry.title == "缺发布时间的新抓")
    assert missing_entry.published_at is None, "发布时间缺失不编造（不回填 fetched_at 展示）"


def test_expired_fallback_row_excluded():
    """发布时间缺失且抓取时间也超窗 → 两侧都不要。"""
    expired = _feed_row(
        "两侧都过期", "https://f.cn/expired",
        published_at=None,
        fetched_at=TUESDAY_PREMARKET - timedelta(days=3),
    )
    entries, feed_ok, fallback = collect_feed_entries(
        StubIntelligenceService(rows=[expired]), now=TUESDAY_PREMARKET,
    )
    assert feed_ok is True
    assert entries == []
    assert fallback == 0


def test_fresh_published_row_kept_by_authoritative_filter():
    """发布时间在窗内的快讯必须保留（Python 层权威过滤不误删新内容）。"""
    fresh_old_fetch = _feed_row(
        "两天前抓到的快讯", "https://f.cn/oldfetch",
        published_at=TUESDAY_PREMARKET - timedelta(hours=10),
        fetched_at=TUESDAY_PREMARKET - timedelta(days=3),
    )
    entries, feed_ok, _fallback = collect_feed_entries(
        StubIntelligenceService(rows=[fresh_old_fetch]), now=TUESDAY_PREMARKET,
    )
    assert feed_ok is True
    assert [entry.title for entry in entries] == ["两天前抓到的快讯"]


def test_tz_aware_published_normalized_to_naive():
    """带时区的发布时间 → 剥除时区按本地时间解释（避免窗口比较偏移）。"""
    tz_row = _feed_row(
        "带时区快讯", "https://f.cn/tz",
        published_at=(TUESDAY_PREMARKET - timedelta(hours=2)).replace(tzinfo=timezone.utc),
    )
    entries, _feed_ok, _fallback = collect_feed_entries(
        StubIntelligenceService(rows=[tz_row]), now=TUESDAY_PREMARKET,
    )
    assert entries[0].published_at == TUESDAY_PREMARKET - timedelta(hours=2)
    assert entries[0].published_at.tzinfo is None


# ---------------------------------------------------------------------------
# 渲染组
# ---------------------------------------------------------------------------


def _premarket_context():
    return NewsDigestContext(
        kind="premarket", date=date(2026, 10, 20),
        window_start=dtime(8, 0), window_end=dtime(9, 15), region="cn",
    )


def test_template_digest_contains_header_body_footer():
    report = generate_template_digest(
        [_entry("池内新闻一", source="华尔街见闻", published_at=TUESDAY_PREMARKET)],
        _premarket_context(), now=TUESDAY_PREMARKET, feed_count=1, fallback_count=0,
    )
    assert report.startswith("# 消息面汇总（盘前）2026-10-20")
    assert "## 来源：华尔街见闻" in report
    assert "生成时间 2026-10-20 08:30" in report
    assert "资讯池条目/1" in report


def test_footer_marks_fallback_count_when_present():
    footer = _render_digest_footer(TUESDAY_PREMARKET, feed_count=3, fallback_count=2)
    assert "2 条缺失发布时间" in footer, "V5：回退口径必须在输出中显式标注"
    assert "资讯池条目/3" in footer


def test_empty_inputs_template_with_disclosure():
    report = generate_template_digest([], _premarket_context(), now=TUESDAY_PREMARKET)
    assert "未收集到近 48 小时内的资讯条目" in report
    assert "不含任何推测内容" in report


# ---------------------------------------------------------------------------
# run_once 组（全链 stub）
# ---------------------------------------------------------------------------


def test_run_once_skips_when_disabled(tmp_path):
    db_path = tmp_path / "digest.db"
    result = run_news_digest_once(
        _config(tmp_path, news_digest_enabled=False),
        now=TUESDAY_PREMARKET, intelligence_service=None, notifier=StubNotifier(),
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "disabled"
    assert _claim_count(db_path) == 0


def test_run_once_skips_outside_window(tmp_path):
    db_path = tmp_path / "digest.db"
    result = run_news_digest_once(
        _config(tmp_path), now=TUESDAY_AFTER_WINDOW,
        intelligence_service=None, notifier=StubNotifier(),
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "outside_window"
    assert _claim_count(db_path) == 0


def test_run_once_emits_once_per_day(tmp_path):
    """OR-COR-860c1e1a 结构性覆盖：无 force 入口，claim 命中即跳过，不重发。"""
    notifier = StubNotifier()
    pool = StubIntelligenceService(rows=[
        _feed_row("早盘消息", "https://f.cn/9", published_at=TUESDAY_PREMARKET),
    ])
    config = _config(tmp_path)
    first = run_news_digest_once(
        config, now=TUESDAY_PREMARKET, intelligence_service=pool, notifier=notifier,
    )
    second = run_news_digest_once(
        config, now=TUESDAY_PREMARKET.replace(hour=8, minute=40),
        intelligence_service=pool, notifier=notifier,
    )
    assert first["status"] == "success"
    assert second["status"] == "skipped"
    assert "claim" in (second["reason"] or "")
    assert len(notifier.calls) == 1
    assert _claim_count(config.database_path) == 1


def test_run_once_unexpected_exception_releases_claim(tmp_path):
    """通知腿抛错（未预期异常路径）：释放本次 claim，窗口内可补发。"""
    notifier = StubNotifier(error=RuntimeError("channel boom"))
    config = _config(tmp_path)
    result = run_news_digest_once(
        config, now=TUESDAY_PREMARKET,
        intelligence_service=StubIntelligenceService(rows=[
            _feed_row("早盘消息", "https://f.cn/9", published_at=TUESDAY_PREMARKET),
        ]),
        notifier=notifier,
    )
    assert result["status"] == "failed"
    assert "unexpected_error" in (result["reason"] or "")
    assert _claim_count(config.database_path) == 0, "未预期异常必须释放本次 claim"
    assert claim_news_digest_date(config.database_path, "2026-10-20", "cn", "premarket") is True


def test_run_once_result_schema(tmp_path):
    """输出 schema：fallback_count/feed_ok/report 等元数据齐全（V5 计数对外可见）。"""
    notifier = StubNotifier()
    result = run_news_digest_once(
        _config(tmp_path), now=TUESDAY_PREMARKET,
        intelligence_service=StubIntelligenceService(rows=[
            _feed_row("池内新闻", "https://f.cn/1", published_at=TUESDAY_PREMARKET),
            _feed_row("缺时间新闻", "https://f.cn/2", published_at=None,
                      fetched_at=TUESDAY_PREMARKET),
        ]),
        notifier=notifier,
    )
    assert result["status"] == "success"
    assert set(result) >= {
        "status", "reason", "region", "date", "context", "entries_count",
        "feed_ok", "fallback_count", "notified", "report",
    }
    assert result["entries_count"] == 2
    assert result["fallback_count"] == 1
    assert result["report"].startswith("# 消息面汇总")


def test_run_once_notifies_with_dedup_key(tmp_path):
    notifier = StubNotifier()
    result = run_news_digest_once(
        _config(tmp_path), now=TUESDAY_PREMARKET,
        intelligence_service=StubIntelligenceService(rows=[
            _feed_row("池内新闻", "https://f.cn/1", published_at=TUESDAY_PREMARKET),
        ]),
        notifier=notifier,
    )
    assert result["status"] == "success"
    assert len(notifier.calls) == 1
    call = notifier.calls[0]
    assert call["route_type"] == "report"
    assert call["dedup_key"] == "news_digest:cn:2026-10-20"
    assert call["email_send_to_all"] is True


def test_run_once_report_footer_and_fallback_metadata(tmp_path):
    """新鲜度脚注 + V5 fallback 计数在推送内容中显式可见。"""
    notifier = StubNotifier()
    result = run_news_digest_once(
        _config(tmp_path), now=TUESDAY_PREMARKET,
        intelligence_service=StubIntelligenceService(rows=[
            _feed_row("池内新闻一", "https://f.cn/1", published_at=TUESDAY_PREMARKET),
            _feed_row("池内新闻二", "https://f.cn/2", published_at=TUESDAY_PREMARKET),
            _feed_row("池内缺时间", "https://f.cn/3", published_at=None,
                      fetched_at=TUESDAY_PREMARKET),
        ]),
        notifier=notifier,
    )
    assert result["status"] == "success"
    assert result["entries_count"] == 3
    assert result["feed_ok"] is True
    assert result["fallback_count"] == 1
    content = notifier.calls[0]["content"]
    assert "生成时间 2026-10-20 08:30" in content
    assert "1 条缺失发布时间" in content, "V5：脚注必须标注回退条数"


# ---------------------------------------------------------------------------
# 发送失败 → 释放 claim 可补发（OR-COR-4c0e3220/e2e5dd13）
# ---------------------------------------------------------------------------


def test_run_once_send_failure_releases_claim_and_fails(tmp_path):
    """所有渠道发送失败：failed、释放当日 claim，窗口内恢复后可补发。"""
    config = _config(tmp_path)
    failing = StubNotifier(send_result=False)
    first = run_news_digest_once(
        config, now=TUESDAY_PREMARKET,
        intelligence_service=StubIntelligenceService(rows=[
            _feed_row("早盘消息", "https://f.cn/9", published_at=TUESDAY_PREMARKET),
        ]),
        notifier=failing,
    )
    assert first["status"] == "failed"
    assert first["notified"] is False
    assert "notification" in (first["reason"] or "")
    assert _claim_count(config.database_path) == 0, "发送失败必须释放当日 claim"

    working = StubNotifier()
    second = run_news_digest_once(
        config, now=TUESDAY_PREMARKET.replace(hour=8, minute=50),
        intelligence_service=None, notifier=working,
    )
    assert second["status"] == "success"
    assert second["notified"] is True
    assert len(working.calls) == 1
    assert _claim_count(config.database_path) == 1


def test_run_once_send_failure_still_reports_generated_content(tmp_path):
    """失败结果仍带回已生成 report（CLI 打印可见），但 notified=False。"""
    result = run_news_digest_once(
        _config(tmp_path), now=TUESDAY_PREMARKET,
        intelligence_service=None, notifier=StubNotifier(send_result=False),
    )
    assert result["status"] == "failed"
    assert result.get("report")
    assert "# 消息面汇总" in result["report"]
