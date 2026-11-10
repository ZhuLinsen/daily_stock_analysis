# -*- coding: utf-8 -*-
"""Daily hot-top10 light analysis service (Issue #1936).

Every trading day, fetch the top-N market theme hot list from DSA's existing
industry/concept ranking providers (``MarketHotspotService``), generate ONE
lightweight LLM summary (per-theme driver / strength / entry advice / risk),
render a bilingual markdown report and push it through the existing report
notification channel.

Design rules:

- Fail-open everywhere: hotspot fetch failure, LLM failure and notification
  failure are logged and degraded, never raised into the scheduler loop.
- One LLM call produces the whole report (a T10 overview), NOT ten
  full per-stock analyses. This is a theme hot-list overview; users who need
  a deep single-stock report should use the existing analysis entry points.
- Daily dedup via a persisted JSON marker next to the SQLite database
  (same directory pattern as ``src/core/analysis_run_marker.py``): missing /
  corrupt / unreadable markers fail open (the run executes again). The marker
  is recorded only after the report was produced AND delivered — the push
  succeeded, or the push was intentionally skipped/disabled AND the local
  save succeeded (OR-COR-8c2d195e: a failed save with no successful push
  delivers nothing and leaves the marker open for the next retry).
- Trading-day gate reuses ``src/core/trading_calendar.get_open_markets_today``
  (fail-open: when the calendar library is unavailable every market counts as
  open). ``force_run`` bypasses both the gate and the dedup marker.
- Cross-slot in-flight mutex (OR-COR-9a41d2ce): the primary and data-ready
  occurrences register under different scheduler job names, so the
  scheduler's per-name guard does not mutually exclude them. A process-wide
  non-reentrant mutex covers each whole run (dedup checks -> LLM -> save ->
  deliver -> marker); a trigger arriving while another run holds it exits
  immediately with ``already_running`` — no push, no marker — and retries on
  the next occurrence.
- Default OFF: with ``HOT_TOP10_ENABLED`` unset the feature registers nothing
  and changes zero behavior.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_HOT_TOP10_COUNT = 10
MAX_HOT_TOP10_COUNT = 30
DEFAULT_HOT_TOP10_SCHEDULE_TIME = "15:10"
# Data-ready follow-up slot (OR-COR-3e7f490e, narrowed): the primary slot
# sits before the 15:30 Tushare ranking cut, so on default deployments its
# delivery covers the previous trading day and cannot consume today's dedup
# marker. A second daily occurrence shortly after the cut delivers today's
# list once the provider serves it (and idles when the primary slot already
# delivered today's data).
DEFAULT_HOT_TOP10_DATA_READY_SCHEDULE_TIME = "15:35"
MARKER_FILE_NAME = "hot_top10_state.json"
# v2 adds ``data_date`` (the ranking date the delivered report actually
# covers, OR-COR-3e7f490e). v1 markers fail open and re-deliver once.
MARKER_SCHEMA_VERSION = 2
LLM_MAX_TOKENS = 3000
LLM_TEMPERATURE = 0.3

# OR-COR-9a41d2ce: process-wide non-reentrant mutex held for the whole run
# (dedup checks -> LLM -> save -> deliver -> marker). The two schedule slots
# register under different job names, so only this service-level guard
# mutually excludes overlapping occurrences.
_HOT_TOP10_RUN_MUTEX = threading.Lock()

# OR-COR-7c92a610: one-shot pending follow-up request. Both schedule slots
# are daily-only, so a trigger that loses the mutex race must not be
# dropped outright — that would lose the day's follow-up opportunity when
# the primary run is slow. The in-flight holder consumes the flag right
# after finishing its own run: fresh data is fetched and the full dedup
# semantics decide whether anything ships.
_HOT_TOP10_PENDING_FOLLOWUP = threading.Event()

# OR-COR-5c51e8d7: the process mutex above cannot exclude two INDEPENDENT
# scheduler processes sharing the same DATABASE_PATH (CLI --schedule next to
# the Web/API/desktop runtime scheduler, or two replicas). Delivery is
# therefore claimed atomically per data date via an exclusive-create file
# next to the marker: ``hot_top10_claim_<data_date>.lock``. A claim older
# than this TTL is crash residue and is taken over.
HOT_TOP10_CLAIM_STALE_AFTER = timedelta(hours=2)
_HOT_TOP10_CLAIM_FILE_PREFIX = "hot_top10_claim_"


def hot_top10_claim_path(config: Any, data_date: str) -> Path:
    """Cross-process delivery claim file for ``data_date`` (marker's dir)."""
    return hot_top10_marker_path(config).parent / (
        f"{_HOT_TOP10_CLAIM_FILE_PREFIX}{data_date}.lock"
    )


def _write_hot_top10_claim_file(path: Path) -> bool:
    """Exclusive-create the claim file; True when THIS process owns it.

    ``O_CREAT | O_EXCL`` is the only portable atomic test-and-set across
    processes on Windows and POSIX alike."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(datetime.now().isoformat(timespec="seconds"))
        handle.write("\n")
        handle.write(str(os.getpid()))
    return True


def _hot_top10_claim_timestamp(path: Path) -> Optional[datetime]:
    """Parse the claim timestamp; None when missing/corrupt (treated stale)."""
    try:
        first_line = path.read_text(encoding="utf-8").strip().splitlines()[0]
    except (OSError, IndexError):
        return None
    try:
        return datetime.fromisoformat(first_line)
    except ValueError:
        return None


class _HotTop10DeliveryClaim:
    """A held cross-process delivery claim; ``release`` removes the file."""

    __slots__ = ("_path", "_released")

    def __init__(self, path: Path) -> None:
        self._path = path
        self._released = False

    def release(self) -> None:
        """Best-effort delete; a lost race against a stale takeover is
        tolerable (the next stale window resolves it)."""
        if self._released:
            return
        self._released = True
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning(
                "[HotTop10] 删除投递认领文件失败（忽略，陈旧后可被接管）: %s", exc
            )


def acquire_hot_top10_delivery_claim(
    config: Any, data_date: str
) -> Optional[_HotTop10DeliveryClaim]:
    """Atomically claim the right to deliver ``data_date`` across processes.

    Returns the claim handle, or ``None`` when another live process already
    holds the claim (caller reports ``already_claimed``: no push, no marker,
    retry on the next trigger). A stale claim — crash residue older than
    ``HOT_TOP10_CLAIM_STALE_AFTER`` — is taken over via
    unlink-then-exclusive-create, which stays atomic (at most one process
    wins the create). Unreadable/corrupt claim files count as stale
    (fail-open, same rules as the marker)."""
    claim_path = hot_top10_claim_path(config, data_date)
    try:
        claim_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "[HotTop10] 认领目录创建失败，本次退化为无跨进程互斥: %s", exc
        )
        return _HotTop10DeliveryClaim(claim_path)
    for _ in range(2):
        if _write_hot_top10_claim_file(claim_path):
            return _HotTop10DeliveryClaim(claim_path)
        claimed_at = _hot_top10_claim_timestamp(claim_path)
        if (
            claimed_at is not None
            and datetime.now() - claimed_at < HOT_TOP10_CLAIM_STALE_AFTER
        ):
            return None
        # Stale (or unreadable) claim: crash residue — take it over.
        try:
            claim_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning(
                "[HotTop10] 陈旧认领文件删除失败，按已被他人持有处理: %s", exc
            )
            return None
    return None


_ADVICE_VALUES = {"观望", "轻仓介入", "积极介入"}


@dataclass
class HotTop10RunResult:
    """Outcome of one hot-top10 run (never raises)."""

    delivered: bool
    skipped: bool
    reason: str
    report_markdown: Optional[str] = None
    llm_completed: bool = False
    notification_status: str = "not_attempted"
    # The trading-day date the delivered list actually covers; ``None`` when
    # the provider did not expose one (treated as current-day data).
    ranking_date: Optional[str] = None


# --------------------------------------------------------------------------
# Daily dedup marker (JSON file next to the SQLite database)
# --------------------------------------------------------------------------


def hot_top10_marker_path(config: Any) -> Path:
    """Marker location next to the SQLite database (data/ in deployments)."""
    database_path = getattr(config, "database_path", "./data/stock_analysis.db")
    return Path(database_path).parent / MARKER_FILE_NAME


def hot_top10_already_delivered_today(config: Any) -> tuple:
    """Return ``(skip, reason)``. Missing/corrupt markers always fail open."""
    try:
        marker_path = hot_top10_marker_path(config)
        try:
            raw = marker_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False, "no hot-top10 marker file (first run of the day)"
        except OSError as exc:
            return False, f"hot-top10 marker unreadable, fail-open ({exc})"
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            return False, f"hot-top10 marker corrupt, fail-open ({exc})"
        if not isinstance(payload, dict):
            return False, "hot-top10 marker is not a JSON object, fail-open"
        if payload.get("schema_version") != MARKER_SCHEMA_VERSION:
            return (
                False,
                "unknown hot-top10 marker schema version, fail-open",
            )
        marker_date = str(payload.get("run_date") or "")
        today = date.today().isoformat()
        if marker_date != today:
            return False, f"marker run_date {marker_date!r} is not today ({today})"
        # OR-COR-3e7f490e: a delivered report only consumes the dedup slot
        # of the data date it actually covers. A marker left by a stale
        # (previous-trading-day) delivery must NOT block a later run, so
        # today's fresh data can still be delivered through the regular
        # entry once the provider serves it. A missing data_date only
        # happens on v1 markers, which already failed open above.
        data_date = str(payload.get("data_date") or "")
        if data_date != today:
            return False, (
                f"marker data_date {data_date!r} is not today ({today}); "
                "today's data has not been delivered yet"
            )
        if payload.get("delivered") is not True:
            return False, "marker recorded an undelivered run, fail-open"
        return True, f"today's hot-top10 report already delivered ({marker_date})"
    except Exception as exc:  # pragma: no cover - defensive fail-open
        return False, f"hot-top10 dedup gate error, fail-open: {exc}"


def record_hot_top10_marker(
    config: Any,
    *,
    llm_completed: bool,
    notification_status: str,
    data_date: Optional[str] = None,
) -> None:
    """Persist today's delivery marker atomically; errors are swallowed.

    ``data_date`` records the ranking date the delivered report actually
    covers (OR-COR-3e7f490e). It defaults to today: an unknown provider
    date is treated as current-day data, so the daily dedup keeps working
    exactly as before for realtime providers.
    """
    try:
        marker_path = hot_top10_marker_path(config)
        payload = {
            "schema_version": MARKER_SCHEMA_VERSION,
            "run_date": date.today().isoformat(),
            "data_date": data_date or date.today().isoformat(),
            "delivered": True,
            "llm_completed": bool(llm_completed),
            "notification_status": str(notification_status or "unknown"),
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "pid": os.getpid(),
        }
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = marker_path.with_name(f"{marker_path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, marker_path)
        logger.info(
            "[HotTop10] 已记录当日投递标记: %s", marker_path
        )
    except Exception as exc:
        logger.warning("[HotTop10] 写入当日投递标记失败（忽略）: %s", exc)


def _load_delivered_marker_payload(config: Any) -> Optional[Dict[str, Any]]:
    """Read a v2 delivered marker; ``None`` on any problem (fail-open)."""
    try:
        raw = hot_top10_marker_path(config).read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != MARKER_SCHEMA_VERSION:
        return None
    if payload.get("delivered") is not True:
        return None
    return payload


def hot_top10_data_date_delivered_today(config: Any, data_date: str) -> tuple:
    """Return ``(skip, reason)`` for a SAME-DAY re-delivery of ``data_date``.

    OR-COR-3e7f490e (narrowed): the data-ready follow-up occurrence must not
    push the same ranking date twice in one day. If today's marker already
    records a successful delivery covering exactly ``data_date`` (whether
    that is today's fresh data or the previous trading day's stale list),
    the follow-up run skips. Markers from earlier run dates never block
    (same-day semantics only); any marker problem fails open.
    """
    payload = _load_delivered_marker_payload(config)
    if payload is None:
        return False, "no usable delivered marker, fail-open"
    marker_date = str(payload.get("run_date") or "")
    if marker_date != date.today().isoformat():
        return False, f"marker run_date {marker_date!r} is not today"
    delivered_date = str(payload.get("data_date") or "")
    if delivered_date != data_date:
        return False, (
            f"marker data_date {delivered_date!r} differs from {data_date!r}"
        )
    return True, (
        f"data date {data_date} already delivered today ({marker_date})"
    )


# --------------------------------------------------------------------------
# Trading-day gate
# --------------------------------------------------------------------------


def is_cn_trading_day_today() -> bool:
    """Whether the CN market is open today (fail-open when unsure)."""
    try:
        from src.core.trading_calendar import get_open_markets_today

        return "cn" in get_open_markets_today()
    except Exception as exc:
        logger.warning(
            "[HotTop10] 交易日判断失败，fail-open 视为交易日: %s", exc
        )
        return True


# --------------------------------------------------------------------------
# Hot-list collection (DSA-native theme rankings)
# --------------------------------------------------------------------------


def _normalize_ranking_date(value: Any) -> Optional[str]:
    """Normalize a provider ranking date to ISO ``YYYY-MM-DD``; ``None`` unknown.

    Tushare board rankings carry ``YYYYMMDD`` dates; the hotspot payload uses
    ISO. Anything unparseable counts as "date unknown" (fail-open semantics:
    the report falls back to the current behavior of not labeling a date).
    """
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _collect_hot_list_items(
    count: int,
    hotspot_service: Any = None,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Fetch and normalize the theme hot list; ``items is None`` when unusable.

    Returns ``(items, ranking_date)``.

    Selection (OR-COR-a7e7c3a3): candidates from ALL buckets compete after
    name de-duplication — they are sorted by change_pct descending (entries
    without a number keep bucket order at the end) and only then truncated
    to ``count``. The old sequential fill stopped at ``count`` inside
    ``active_themes``/``leading_industries`` and wrongly evicted
    small-negative concepts on negative-industry days.

    ``ranking_date`` (OR-COR-3e7f490e) is the payload trade date, falling
    back to the first per-item trade date, so downstream stages can label
    the report with the real list date even when the provider serves the
    previous trading day's rankings.
    """
    if hotspot_service is None:
        from src.services.market_hotspot_service import MarketHotspotService

        hotspot_service = MarketHotspotService()

    payload = hotspot_service.get_hotspots(market="cn", limit=count)
    if not isinstance(payload, dict):
        return None, None

    candidates: List[Dict[str, Any]] = []
    seen_names = set()
    buckets = [
        ("active_themes", None),
        ("leading_industries", "industry"),
        ("leading_concepts", "concept"),
    ]
    for bucket, default_kind in buckets:
        raw_items = payload.get(bucket)
        if not isinstance(raw_items, list):
            continue
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            kind = entry.get("source") or default_kind or "theme"
            candidates.append(
                {
                    "name": name,
                    "code": str(entry.get("code") or "").strip(),
                    "change_pct": entry.get("change_pct"),
                    "kind": str(kind),
                    "phase": str(entry.get("phase") or "unknown"),
                    "strength_score": entry.get("strength_score"),
                    "reason": str(entry.get("reason") or "").strip(),
                    "trade_date": _normalize_ranking_date(entry.get("trade_date")),
                }
            )
    if not candidates:
        return None, None

    def _change_sort_key(item: Dict[str, Any]) -> Tuple[int, float]:
        value = item.get("change_pct")
        if isinstance(value, (int, float)):
            return (0, -float(value))
        return (1, 0.0)

    candidates.sort(key=_change_sort_key)
    items = candidates[:count]
    for index, item in enumerate(items, 1):
        item["rank"] = index

    ranking_date = _normalize_ranking_date(payload.get("trade_date"))
    if ranking_date is None:
        for item in candidates:
            if item.get("trade_date"):
                ranking_date = item["trade_date"]
                break
    return items, ranking_date


def _format_change_pct(value: Any, language: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A" if language == "en" else "无数据"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}%"


# --------------------------------------------------------------------------
# Prompt assembly / LLM summary
# --------------------------------------------------------------------------


def _build_analyzer(config: Any):
    from src.analyzer import GeminiAnalyzer

    return GeminiAnalyzer(config=config)


def build_hot_top10_prompt(
    items: List[Dict[str, Any]],
    language: str,
    ranking_date: Optional[str] = None,
) -> str:
    """Assemble the single-call summary prompt (bilingual).

    ``ranking_date`` labels the trading day the list data actually covers
    (OR-COR-3e7f490e); when it is not today the model is told explicitly so
    it never presents previous-day rankings as today's market.
    """
    today = date.today().isoformat()
    date_note_en = ""
    date_note_zh = ""
    if ranking_date:
        if ranking_date != today:
            date_note_en = (
                f"Ranking date: {ranking_date}. NOTE: this list is data from "
                "that trading day, NOT today's market; do not describe it as "
                "today's action."
            )
            date_note_zh = (
                f"榜单日期：{ranking_date}。注意：该榜单为上述交易日数据，"
                "并非今日实时行情，请勿当作今日盘面描述。"
            )
        else:
            date_note_en = f"Ranking date: {ranking_date} (today)."
            date_note_zh = f"榜单日期：{ranking_date}（今日）。"

    if language == "en":
        lines = [
            "You are an A-share market hotspot analyst. Below is the market",
            "theme hot list ranked by gain (from DSA industry/concept rankings):",
            "",
        ]
        if date_note_en:
            lines += [date_note_en, ""]
        for item in items:
            lines.append(
                f"{item['rank']}. {item['name']} ({item['kind']}) "
                f"change {_format_change_pct(item['change_pct'], 'en')}, "
                f"phase {item['phase']}"
            )
        lines += [
            "",
            "For EACH theme output: the likely driver (news/funds/event",
            "attribution; mark speculation explicitly), a strength assessment",
            "(strong/medium/weak), an entry advice (wait/light position/",
            "active entry) and the key risk.",
            "Reply with STRICT JSON only (no extra text):",
            '{"summary": "one paragraph on the hotspot mainline of the ranking date above", '
            '"items": [{"rank": 1, "name": "...", "driver": "...", '
            '"strength": "strong|medium|weak", '
            '"advice": "wait|light position|active entry", "risk": "..."}]}',
        ]
        return "\n".join(lines)

    lines = [
        "你是 A 股市场热点分析助手。以下是市场主题热榜"
        "（按涨跌幅排名，来自 DSA 行业/概念排名数据）：",
        "",
    ]
    if date_note_zh:
        lines += [date_note_zh, ""]
    for item in items:
        lines.append(
            f"{item['rank']}. {item['name']}（{item['kind']}）"
            f"涨跌幅 {_format_change_pct(item['change_pct'], 'zh')}，"
            f"阶段 {item['phase']}"
        )
    lines += [
        "",
        "请针对每个主题输出：热榜动因（新闻/资金/事件归因，无明确信息来源时"
        "请标注“推测”）、强度评估（强/中/弱）、介入建议（观望/轻仓介入/积极介入）、"
        "风险提示。",
        "严格只输出以下 JSON，不要输出任何多余文本：",
        '{"summary": "一段话总结上述榜单日期的热点主线与整体参与度", '
        '"items": [{"rank": 1, "name": "主题名", "driver": "动因", '
        '"strength": "强|中|弱", "advice": "观望|轻仓介入|积极介入", '
        '"risk": "风险提示"}]}',
    ]
    return "\n".join(lines)


def parse_llm_summary(text: Any) -> Optional[Dict[str, Any]]:
    """Robustly extract the summary JSON object; ``None`` when unusable."""
    if not isinstance(text, str) or not text.strip():
        return None
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            return None
        cleaned = cleaned[start : end + 1]
    try:
        payload = json.loads(cleaned)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("items"), list):
        payload["items"] = []
    return payload


def _summary_items_by_name(payload: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    if not isinstance(payload, dict):
        return indexed
    for entry in payload.get("items") or []:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            if name:
                indexed[name] = entry
    return indexed


# --------------------------------------------------------------------------
# Report rendering (bilingual)
# --------------------------------------------------------------------------


def render_hot_top10_report(
    items: List[Dict[str, Any]],
    summary: Optional[Dict[str, Any]],
    llm_completed: bool,
    language: str,
    ranking_date: Optional[str] = None,
) -> str:
    """Render the markdown report; degraded to data-only when LLM failed.

    ``ranking_date`` (OR-COR-3e7f490e) is shown in the title and header as
    the 榜单日期 the list data actually covers. When the provider served a
    previous trading day's rankings (default trigger 15:10 sits before the
    15:30 data cut), the report says so explicitly instead of presenting
    the list as today's market.
    """
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = date.today().isoformat()
    title_date = ranking_date or today
    stale = bool(ranking_date) and ranking_date != today
    if language == "en":
        title = f"# Market Hot Themes Top {len(items)} — {title_date}"
        ranking_date_note = (
            f"Ranking date: {ranking_date}"
            + (
                " (NOT today; previous trading day data — today's list will be "
                "delivered separately once the data cut is available)"
                if stale
                else " (today)"
            )
            if ranking_date
            else "Ranking date: unknown (provider did not report one)"
        )
        header_note = (
            f"> Generated at: {now_text} | {ranking_date_note} | "
            "Data source: DSA industry/concept rankings (MarketHotspotService), "
            "a theme-level hot list. This is a light overview, NOT per-stock "
            "deep analysis; use the existing stock analysis entry points for that."
        )
        overview_title = "## Hotspot Overview"
        per_item_title = "## Theme Breakdown"
        data_title = "## Hot List Data"
        labels = {
            "driver": "Driver",
            "strength": "Strength",
            "advice": "Entry advice",
            "risk": "Risk",
            "rank": "Rank",
            "theme": "Theme",
            "type": "Type",
            "change": "Change",
            "phase": "Phase",
        }
        llm_failed_note = (
            "> AI summary generation failed this run; the data overview below "
            "is still delivered."
        )
        raw_note_prefix = "> AI summary could not be parsed as structured JSON; raw model output:\n\n"
    else:
        title = f"# 市场热榜 Top {len(items)} 分析 — {title_date}"
        if ranking_date:
            ranking_date_note = (
                f"榜单日期：{ranking_date}"
                + (
                    "（非今日：为上一交易日榜单数据，当日数据就绪后将按当日榜单另行生成）"
                    if stale
                    else "（今日）"
                )
            )
        else:
            ranking_date_note = "榜单日期：未知（数据源未提供日期）"
        header_note = (
            f"> 生成时间：{now_text} ｜ {ranking_date_note} ｜ "
            "数据来源：DSA 行业/概念排名（MarketHotspotService），为主题级热榜。"
            "本报告为热榜轻量概览，非个股深度报告；个股深度分析请使用既有个股分析入口。"
        )
        overview_title = "## 热点总览"
        per_item_title = "## 逐项分析"
        data_title = "## 热榜数据"
        labels = {
            "driver": "热榜动因",
            "strength": "强度评估",
            "advice": "介入建议",
            "risk": "风险提示",
            "rank": "排名",
            "theme": "主题",
            "type": "类型",
            "change": "涨跌幅",
            "phase": "阶段",
        }
        llm_failed_note = (
            "> 本次 AI 摘要生成失败，以下为数据概览（降级交付）。"
        )
        raw_note_prefix = "> AI 摘要未能解析为结构化 JSON，原始模型输出如下：\n\n"

    indexed = _summary_items_by_name(summary)
    lines = [title, "", header_note, "", overview_title, ""]
    if isinstance(summary, dict) and str(summary.get("summary") or "").strip():
        lines.append(str(summary["summary"]).strip())
    elif llm_completed:
        lines.append(raw_note_prefix)
        lines.append("```")
        raw_text = str(summary.get("raw") or "").strip() if summary else ""
        lines.append(raw_text or ("-"))
        lines.append("```")
    else:
        lines.append(llm_failed_note)

    lines += ["", per_item_title, ""]
    for item in items:
        entry = indexed.get(item["name"], {})
        lines.append(
            f"### {item['rank']}. {item['name']}"
            f"（{item['kind']}）｜ {_format_change_pct(item['change_pct'], language)}"
        )
        driver = str(entry.get("driver") or "").strip()
        if not driver:
            driver = item.get("reason") or (
                "AI 摘要缺失" if language != "en" else "AI summary unavailable"
            )
        strength = str(entry.get("strength") or "").strip() or "-"
        advice = str(entry.get("advice") or "").strip() or (
            "观望" if language != "en" else "wait"
        )
        risk = str(entry.get("risk") or "").strip() or (
            "动因不明确，注意追高风险" if language != "en" else "Unclear driver; avoid chasing"
        )
        lines += [
            f"- {labels['driver']}：{driver}",
            f"- {labels['strength']}：{strength}",
            f"- {labels['advice']}：{advice}",
            f"- {labels['risk']}：{risk}",
            "",
        ]

    lines += [data_title, ""]
    lines.append(
        f"| {labels['rank']} | {labels['theme']} | {labels['type']} | "
        f"{labels['change']} | {labels['phase']} |"
    )
    lines.append("| --- | --- | --- | --- | --- |")
    for item in items:
        lines.append(
            f"| {item['rank']} | {item['name']} | {item['kind']} | "
            f"{_format_change_pct(item['change_pct'], language)} | {item['phase']} |"
        )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Delivery (report file + notification channel)
# --------------------------------------------------------------------------


def _deliver(
    report_markdown: str,
    send_notification: bool,
    notifier: Any,
) -> Tuple[str, bool]:
    """Save + push the report. Returns ``(status, report_saved)``; never raises.

    ``report_saved`` (OR-COR-8c2d195e) tells the caller whether the local
    report file actually landed. With no successful notification push it is
    the ONLY delivery that counts, so a failed save must propagate into the
    delivery decision instead of being swallowed here.
    """
    try:
        if notifier is None:
            from src.notification import NotificationService

            notifier = NotificationService()
    except Exception as exc:
        logger.warning(
            "[HotTop10] 通知服务初始化失败，报告未保存也未推送: %s\n%s", exc, report_markdown
        )
        return "notifier_init_failed", False

    report_saved = False
    filename = f"hot_top10_{date.today():%Y%m%d}.md"
    try:
        path = notifier.save_report_to_file(report_markdown, filename)
        logger.info("[HotTop10] 报告已保存: %s", path)
        report_saved = True
    except Exception as exc:
        # OR-COR-8c2d195e: do NOT swallow silently — the caller must know
        # the report exists nowhere (no save, no push) and retry.
        logger.warning("[HotTop10] 报告保存失败: %s\n%s", exc, report_markdown)

    if not send_notification:
        logger.info("[HotTop10] 通知推送已禁用（--no-notify）")
        return "disabled", report_saved
    try:
        if not notifier.is_available():
            logger.info("[HotTop10] 未配置通知渠道，跳过推送（报告仅落盘）")
            return "no_channel", report_saved
        if notifier.send(report_markdown, route_type="report"):
            logger.info("[HotTop10] 通知推送成功")
            return "sent", report_saved
        logger.warning("[HotTop10] 通知推送失败")
        return "failed", report_saved
    except Exception as exc:
        logger.warning("[HotTop10] 通知推送异常: %s", exc)
        return "failed", report_saved


# --------------------------------------------------------------------------
# Run entry (CLI + scheduler)
# --------------------------------------------------------------------------


def run_hot_top10_analysis(
    config: Any,
    *,
    send_notification: bool = True,
    notifier: Any = None,
    analyzer: Any = None,
    hotspot_service: Any = None,
    respect_dedup: bool = True,
    force_run: bool = False,
) -> HotTop10RunResult:
    """One hot-top10 run, guarded by the cross-slot in-flight mutex.

    OR-COR-9a41d2ce: the primary and data-ready schedule slots register
    under different job names, so the scheduler's per-name in-flight guard
    does not mutually exclude them, and both dedup checks happen before the
    LLM/save/push stages — two overlapping occurrences could both pass the
    checks and push the same list twice. This wrapper takes a process-wide
    non-reentrant mutex around the entire critical section (dedup checks ->
    LLM -> save -> deliver -> marker). A trigger arriving while another run
    holds the mutex exits immediately with ``skipped=True`` and
    ``reason="already_running"`` — nothing is pushed and the day's dedup
    marker is left untouched (OR-COR-8c2d195e recovery semantics).

    OR-COR-7c92a610: that losing trigger is not dropped. Both slots are
    daily-only, so the wrapper retains a ONE-SHOT pending follow-up request
    and the in-flight holder re-executes the run once right after finishing
    (fresh fetch -> full dedup semantics; a same-data-date delivery
    dedup-skips, a new data date ships). The follow-up calls the locked body
    directly and cannot recurse; the primary run's result stays the caller's
    return value and the follow-up outcome is logged.

    Never raises: every stage degrades and logs; see
    :func:`_run_hot_top10_analysis_locked` for the run itself.
    """
    if not _HOT_TOP10_RUN_MUTEX.acquire(blocking=False):
        # OR-COR-7c92a610: the in-flight holder will consume this one-shot
        # request right after finishing, so the overlapping trigger is not
        # lost for the day (both slots fire daily; there is no later slot).
        _HOT_TOP10_PENDING_FOLLOWUP.set()
        logger.warning(
            "[HotTop10] 上一轮热榜分析仍在执行中，本次触发跳过"
            "（已登记一次性待补投请求：不投递、不落当日标记，"
            "首轮完成后自动补执行并重新走完整去重）"
        )
        return HotTop10RunResult(
            delivered=False,
            skipped=True,
            reason="already_running",
        )
    try:
        result = _run_hot_top10_analysis_locked(
            config,
            send_notification=send_notification,
            notifier=notifier,
            analyzer=analyzer,
            hotspot_service=hotspot_service,
            respect_dedup=respect_dedup,
            force_run=force_run,
        )
        # OR-COR-7c92a610: consume the pending follow-up exactly once per
        # entry, while still holding the mutex. The follow-up calls the
        # locked body DIRECTLY, so it can never recurse into itself; a
        # trigger arriving during the follow-up returns already_running and
        # (re)registers the flag for the next run entry.
        if _HOT_TOP10_PENDING_FOLLOWUP.is_set():
            _HOT_TOP10_PENDING_FOLLOWUP.clear()
            logger.info(
                "[HotTop10] 首轮执行期间有触发被互斥跳过：执行一次性补投"
                "（重新取数 → 去重 → 生成 → 保存 → 投递 → 落标记）"
            )
            followup_result = _run_hot_top10_analysis_locked(
                config,
                send_notification=send_notification,
                notifier=notifier,
                analyzer=analyzer,
                hotspot_service=hotspot_service,
                respect_dedup=respect_dedup,
                force_run=force_run,
            )
            logger.info(
                "[HotTop10] 补投完成: delivered=%s skipped=%s reason=%s "
                "llm_completed=%s notification=%s",
                followup_result.delivered,
                followup_result.skipped,
                followup_result.reason,
                followup_result.llm_completed,
                followup_result.notification_status,
            )
        # The primary run's result stays the caller's return value; the
        # follow-up outcome is logged and observable via the marker.
        return result
    finally:
        _HOT_TOP10_RUN_MUTEX.release()


def _run_hot_top10_analysis_locked(
    config: Any,
    *,
    send_notification: bool = True,
    notifier: Any = None,
    analyzer: Any = None,
    hotspot_service: Any = None,
    respect_dedup: bool = True,
    force_run: bool = False,
) -> HotTop10RunResult:
    """Run body executed while holding ``_HOT_TOP10_RUN_MUTEX``.

    One run: fetch -> summarize -> render -> deliver. Never raises: every
    stage degrades and logs. The daily marker is recorded only when the
    report was produced AND delivered — the push succeeded, or the push was
    intentionally skipped/disabled AND the local save succeeded
    (OR-COR-8c2d195e) — so a failed push or save retries later.
    """
    count = getattr(config, "hot_top10_count", DEFAULT_HOT_TOP10_COUNT) or DEFAULT_HOT_TOP10_COUNT
    try:
        count = max(1, min(MAX_HOT_TOP10_COUNT, int(count)))
    except (TypeError, ValueError):
        count = DEFAULT_HOT_TOP10_COUNT
    language = str(getattr(config, "report_language", "zh") or "zh").strip().lower()
    if language not in {"zh", "en"}:
        language = "zh"

    if respect_dedup and not force_run:
        skip, reason = hot_top10_already_delivered_today(config)
        if skip:
            logger.info("[HotTop10] 当日报告已投递，跳过: %s", reason)
            return HotTop10RunResult(
                delivered=False,
                skipped=True,
                reason=f"already_delivered_today: {reason}",
            )

    if not force_run and getattr(config, "trading_day_check_enabled", True):
        if not is_cn_trading_day_today():
            logger.info("[HotTop10] 今日 A 股非交易日，跳过热榜分析")
            return HotTop10RunResult(
                delivered=False,
                skipped=True,
                reason="non_trading_day",
            )

    items, ranking_date = _collect_hot_list_items(count, hotspot_service=hotspot_service)
    if not items:
        logger.warning("[HotTop10] 热榜数据获取失败，本轮不生成报告")
        return HotTop10RunResult(
            delivered=False,
            skipped=True,
            reason="hotspot_data_unavailable",
        )
    effective_data_date = ranking_date or date.today().isoformat()
    if respect_dedup and not force_run:
        # Same-day re-delivery guard (OR-COR-3e7f490e, narrowed): the
        # data-ready follow-up occurrence may fire while the provider still
        # serves the previous trading day's rankings — the very list the
        # primary slot already delivered. Pushing it again would duplicate
        # the stale report, so a delivery covering the exact same data date
        # recorded today skips instead.
        same_date_skip, same_date_reason = hot_top10_data_date_delivered_today(
            config, effective_data_date
        )
        if same_date_skip:
            logger.info(
                "[HotTop10] 该榜单数据日期今日已投递，跳过重复推送: %s",
                same_date_reason,
            )
            return HotTop10RunResult(
                delivered=False,
                skipped=True,
                reason=f"same_data_date_delivered_today: {same_date_reason}",
            )
    if ranking_date and ranking_date != date.today().isoformat():
        logger.info(
            "[HotTop10] 榜单日期为 %s（非今日）：报告将按该日期标注，"
            "且不占用今日投递标记，当日数据就绪后可再投",
            ranking_date,
        )

    # OR-COR-5c51e8d7: atomic cross-process claim for this data date. The
    # run mutex above cannot exclude two INDEPENDENT processes sharing the
    # same DATABASE_PATH (CLI --schedule beside the Web/API/desktop runtime
    # scheduler), and the dedup checks above all happen BEFORE the
    # LLM/save/push stages — two processes could both pass them and push
    # the same list. The exclusive-create claim file makes check ->
    # generate -> save -> push -> marker exclusive per data date.
    # force_run (explicit human override) stays unclaimed.
    delivery_claim = None
    if not force_run:
        delivery_claim = acquire_hot_top10_delivery_claim(
            config, effective_data_date
        )
        if delivery_claim is None:
            logger.warning(
                "[HotTop10] 该榜单数据日期（%s）已被其他进程认领投递，本次跳过："
                "不推送、不落当日标记，等待下次触发重试",
                effective_data_date,
            )
            return HotTop10RunResult(
                delivered=False,
                skipped=True,
                reason="already_claimed",
            )
        if respect_dedup:
            # Close the check->claim window: the other process may have
            # finished its whole delivery between the marker reads above and
            # this claim being won. Its marker landed BEFORE it released the
            # claim, so a fresh read here settles the race.
            claimed_skip, claimed_reason = hot_top10_data_date_delivered_today(
                config, effective_data_date
            )
            if claimed_skip:
                delivery_claim.release()
                logger.info(
                    "[HotTop10] 认领后发现该数据日期已被投递，跳过: %s",
                    claimed_reason,
                )
                return HotTop10RunResult(
                    delivered=False,
                    skipped=True,
                    reason=f"same_data_date_delivered_today: {claimed_reason}",
                )

    try:
        llm_completed = False
        summary: Optional[Dict[str, Any]] = None
        try:
            if analyzer is None:
                analyzer = _build_analyzer(config)
            prompt = build_hot_top10_prompt(items, language, ranking_date=ranking_date)
            llm_text = analyzer.generate_text(
                prompt,
                max_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
            )
            if isinstance(llm_text, str) and llm_text.strip():
                summary = parse_llm_summary(llm_text)
                if summary is not None:
                    llm_completed = True
                else:
                    summary = {"raw": llm_text}
                    logger.warning("[HotTop10] AI 摘要 JSON 解析失败，按原文降级渲染")
            else:
                logger.warning("[HotTop10] AI 摘要生成失败（返回空），降级为数据概览")
        except Exception as exc:
            logger.warning("[HotTop10] AI 摘要生成异常，降级为数据概览: %s", exc)

        report_markdown = render_hot_top10_report(
            items, summary, llm_completed, language, ranking_date=ranking_date
        )
        notification_status, report_saved = _deliver(
            report_markdown, send_notification, notifier
        )

        if notification_status in {"failed", "notifier_init_failed"}:
            # Push failed: leave the marker unset so the next occurrence retries.
            logger.warning(
                "[HotTop10] 推送未成功（status=%s），不记录当日标记，等待下次重试",
                notification_status,
            )
        elif not report_saved and notification_status != "sent":
            # OR-COR-8c2d195e: no successful notification push AND the local
            # save failed, so nothing was actually delivered. The day's dedup
            # marker must stay open, otherwise a recoverable storage failure
            # would silently swallow the whole day's report. (A successful push
            # with a failed save still counts as delivered and records below.)
            logger.warning(
                "[HotTop10] 报告保存失败且无成功通知交付（status=%s），"
                "不记录当日标记，等待下次重试",
                notification_status,
            )
        else:
            record_hot_top10_marker(
                config,
                llm_completed=llm_completed,
                notification_status=notification_status,
                # The dedup slot belongs to the data date the report covers; a
                # stale (previous-day) delivery therefore leaves today's slot
                # open for the fresh data (OR-COR-3e7f490e).
                data_date=ranking_date,
            )

        # The run only counts as delivered when the report reached somewhere:
        # a successful push, or a successful local save (for the disabled /
        # no-channel paths that rely on the file).
        delivery_completed = report_saved or notification_status == "sent"
        return HotTop10RunResult(
            delivered=delivery_completed,
            skipped=False,
            reason="ok" if delivery_completed else f"delivery_failed: {notification_status}",
            report_markdown=report_markdown,
            llm_completed=llm_completed,
            notification_status=notification_status,
            ranking_date=ranking_date,
        )
    finally:
        # Release the claim on EVERY path: push/save failure leaves the
        # MARKER open for retry (OR-COR-8c2d195e) and the released claim
        # lets that retry proceed; after a recorded marker the claim has
        # served its purpose (the next data date claims a fresh file).
        if delivery_claim is not None:
            delivery_claim.release()
