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
  is recorded only after the report was produced AND the push succeeded (or
  the push was intentionally skipped), so a failed push retries on the next
  restart/occurrence instead of losing the day's report.
- Trading-day gate reuses ``src/core/trading_calendar.get_open_markets_today``
  (fail-open: when the calendar library is unavailable every market counts as
  open). ``force_run`` bypasses both the gate and the dedup marker.
- Default OFF: with ``HOT_TOP10_ENABLED`` unset the feature registers nothing
  and changes zero behavior.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_HOT_TOP10_COUNT = 10
MAX_HOT_TOP10_COUNT = 30
DEFAULT_HOT_TOP10_SCHEDULE_TIME = "15:10"
MARKER_FILE_NAME = "hot_top10_state.json"
MARKER_SCHEMA_VERSION = 1
LLM_MAX_TOKENS = 3000
LLM_TEMPERATURE = 0.3

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
) -> None:
    """Persist today's delivery marker atomically; errors are swallowed."""
    try:
        marker_path = hot_top10_marker_path(config)
        payload = {
            "schema_version": MARKER_SCHEMA_VERSION,
            "run_date": date.today().isoformat(),
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


def _collect_hot_list_items(
    count: int,
    hotspot_service: Any = None,
) -> Optional[List[Dict[str, Any]]]:
    """Fetch and normalize the theme hot list; ``None`` when data is unusable."""
    if hotspot_service is None:
        from src.services.market_hotspot_service import MarketHotspotService

        hotspot_service = MarketHotspotService()

    payload = hotspot_service.get_hotspots(market="cn", limit=count)
    if not isinstance(payload, dict):
        return None

    items: List[Dict[str, Any]] = []
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
            if not isinstance(entry, dict) or len(items) >= count:
                break
            name = str(entry.get("name") or "").strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            kind = entry.get("source") or default_kind or "theme"
            items.append(
                {
                    "name": name,
                    "code": str(entry.get("code") or "").strip(),
                    "rank": len(items) + 1,
                    "change_pct": entry.get("change_pct"),
                    "kind": str(kind),
                    "phase": str(entry.get("phase") or "unknown"),
                    "strength_score": entry.get("strength_score"),
                    "reason": str(entry.get("reason") or "").strip(),
                }
            )
    return items or None


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


def build_hot_top10_prompt(items: List[Dict[str, Any]], language: str) -> str:
    """Assemble the single-call summary prompt (bilingual)."""
    if language == "en":
        lines = [
            "You are an A-share market hotspot analyst. Below is today's market",
            "theme hot list ranked by gain (from DSA industry/concept rankings):",
            "",
        ]
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
            '{"summary": "one paragraph on today\'s hotspot mainline", '
            '"items": [{"rank": 1, "name": "...", "driver": "...", '
            '"strength": "strong|medium|weak", '
            '"advice": "wait|light position|active entry", "risk": "..."}]}',
        ]
        return "\n".join(lines)

    lines = [
        "你是 A 股市场热点分析助手。以下是今日市场主题热榜"
        "（按涨跌幅排名，来自 DSA 行业/概念排名数据）：",
        "",
    ]
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
        '{"summary": "一段话总结今日热点主线与整体参与度", '
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
) -> str:
    """Render the markdown report; degraded to data-only when LLM failed."""
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if language == "en":
        title = f"# Market Hot Themes Top {len(items)} — {date.today().isoformat()}"
        header_note = (
            f"> Generated at: {now_text} | "
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
        title = f"# 市场热榜 Top {len(items)} 分析 — {date.today().isoformat()}"
        header_note = (
            f"> 生成时间：{now_text} ｜ "
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
) -> str:
    """Save + push the report. Returns a status string; never raises."""
    try:
        if notifier is None:
            from src.notification import NotificationService

            notifier = NotificationService()
    except Exception as exc:
        logger.warning(
            "[HotTop10] 通知服务初始化失败，报告未保存也未推送: %s\n%s", exc, report_markdown
        )
        return "notifier_init_failed"

    filename = f"hot_top10_{date.today():%Y%m%d}.md"
    try:
        path = notifier.save_report_to_file(report_markdown, filename)
        logger.info("[HotTop10] 报告已保存: %s", path)
    except Exception as exc:
        logger.warning("[HotTop10] 报告保存失败: %s\n%s", exc, report_markdown)

    if not send_notification:
        logger.info("[HotTop10] 通知推送已禁用（--no-notify）")
        return "disabled"
    try:
        if not notifier.is_available():
            logger.info("[HotTop10] 未配置通知渠道，跳过推送（报告仅落盘）")
            return "no_channel"
        if notifier.send(report_markdown, route_type="report"):
            logger.info("[HotTop10] 通知推送成功")
            return "sent"
        logger.warning("[HotTop10] 通知推送失败")
        return "failed"
    except Exception as exc:
        logger.warning("[HotTop10] 通知推送异常: %s", exc)
        return "failed"


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
    """One hot-top10 run: fetch -> summarize -> render -> deliver.

    Never raises: every stage degrades and logs. The daily marker is recorded
    only when the report was produced AND the push succeeded (or the push was
    intentionally skipped/disabled), so a failed push retries later.
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

    items = _collect_hot_list_items(count, hotspot_service=hotspot_service)
    if not items:
        logger.warning("[HotTop10] 热榜数据获取失败，本轮不生成报告")
        return HotTop10RunResult(
            delivered=False,
            skipped=True,
            reason="hotspot_data_unavailable",
        )

    llm_completed = False
    summary: Optional[Dict[str, Any]] = None
    try:
        if analyzer is None:
            analyzer = _build_analyzer(config)
        prompt = build_hot_top10_prompt(items, language)
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

    report_markdown = render_hot_top10_report(items, summary, llm_completed, language)
    notification_status = _deliver(report_markdown, send_notification, notifier)

    if notification_status in {"failed", "notifier_init_failed"}:
        # Push failed: leave the marker unset so the next occurrence retries.
        logger.warning(
            "[HotTop10] 推送未成功（status=%s），不记录当日标记，等待下次重试",
            notification_status,
        )
    else:
        record_hot_top10_marker(
            config,
            llm_completed=llm_completed,
            notification_status=notification_status,
        )

    return HotTop10RunResult(
        delivered=True,
        skipped=False,
        reason="ok",
        report_markdown=report_markdown,
        llm_completed=llm_completed,
        notification_status=notification_status,
    )
