# -*- coding: utf-8 -*-
"""
===================================
股票智能分析系统 - 大盘复盘模块（支持 A 股 / 港股 / 美股 / 日本 / 韩国）
===================================

职责：
1. 根据 MARKET_REVIEW_REGION 配置选择市场区域（cn / hk / us / jp / kr / both）
2. 执行大盘复盘分析并生成复盘报告
3. 保存和发送复盘报告
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
import uuid

from src.config import get_config
from src.notification import NotificationService
from src.market_analyzer import MarketAnalyzer
from src.report_language import normalize_report_language
from src.search_service import SearchService
from src.analyzer import AnalysisResult, GeminiAnalyzer
from src.llm.generation_backend import GenerationError
from src.services.run_diagnostics import (
    current_diagnostic_snapshot,
    record_history_run,
    record_notification_run,
)
from src.schemas.market_light import MARKET_LIGHT_REGIONS


logger = logging.getLogger(__name__)

MARKET_REVIEW_HISTORY_CODE = "MARKET"
MARKET_REVIEW_REPORT_TYPE = "market_review"
_MARKET_REVIEW_MARKETS = (
    ('cn', 'cn_title', 'A 股'),
    ('hk', 'hk_title', '港股'),
    ('us', 'us_title', '美股'),
    ('jp', 'jp_title', '日股'),
    ('kr', 'kr_title', '韩股'),
)
_MARKET_REVIEW_REGION_ORDER = tuple(market for market, _, _ in _MARKET_REVIEW_MARKETS)
_VALID_MARKET_REVIEW_REGIONS = frozenset(_MARKET_REVIEW_REGION_ORDER)


@dataclass
class MarketReviewRunResult:
    """Structured result for API/Web consumers while keeping Markdown compatibility."""

    report: str
    market_review_payload: Dict[str, Any] = field(default_factory=dict)


def _refresh_market_review_history_diagnostics(*, query_id: str) -> None:
    """Refresh persisted market-review diagnostics after late flow events are recorded."""
    diagnostic_snapshot = current_diagnostic_snapshot()
    if diagnostic_snapshot is None:
        return

    try:
        from src.storage import DatabaseManager

        db = DatabaseManager.get_instance()
        updater = getattr(db, "update_analysis_history_diagnostics", None)
        if callable(updater):
            updater(
                query_id=query_id,
                code=MARKET_REVIEW_HISTORY_CODE,
                diagnostics=diagnostic_snapshot,
            )
    except Exception as exc:
        logger.warning("回写大盘复盘运行诊断失败（fail-open）: %s", exc)


def _record_market_review_notification_run(
    *,
    query_id: str,
    channel: str,
    status: str,
    success: bool,
    attempts: int = 1,
    error_message: Optional[Any] = None,
) -> None:
    record_notification_run(
        channel=channel,
        status=status,
        success=success,
        attempts=attempts,
        error_message=error_message,
    )
    _refresh_market_review_history_diagnostics(query_id=query_id)


def _collect_market_light_snapshot(
    snapshots: Dict[str, Dict[str, Any]],
    *,
    region: str,
    review_result: Any,
) -> None:
    if region not in MARKET_LIGHT_REGIONS:
        return
    snapshot = getattr(review_result, "market_light_snapshot", None)
    if isinstance(snapshot, dict) and snapshot:
        snapshots[region] = snapshot


def _get_market_review_text(language: str) -> dict[str, str]:
    normalized = normalize_report_language(language)
    if normalized == "en":
        return {
            "root_title": "# 🎯 Market Review",
            "push_title": "🎯 Market Review",
            "cn_title": "# A-share Market Recap",
            "us_title": "# US Market Recap",
            "hk_title": "# HK Market Recap",
            "jp_title": "# Japan Market Recap",
            "kr_title": "# Korea Market Recap",
            "separator": "> Next market recap follows",
        }
    if normalized == "ko":
        return {
            "root_title": "# 🎯 시황 리뷰",
            "push_title": "🎯 시황 리뷰",
            "cn_title": "# 중국 A주 시황 리뷰",
            "us_title": "# 미국 시황 리뷰",
            "hk_title": "# 홍콩 시황 리뷰",
            "jp_title": "# 일본 시황 리뷰",
            "kr_title": "# 한국 시황 리뷰",
            "separator": "> 다음 시장 시황 리뷰",
        }
    return {
        "root_title": "# 🎯 大盘复盘",
        "push_title": "🎯 大盘复盘",
        "cn_title": "# A股大盘复盘",
        "us_title": "# 美股大盘复盘",
        "hk_title": "# 港股大盘复盘",
        "jp_title": "# 日股大盘复盘",
        "kr_title": "# 韩股大盘复盘",
        "separator": "> 以下为下一市场大盘复盘",
    }


def _get_market_review_market_heading(language: Any, market: str) -> str:
    review_text = _get_market_review_text(str(language or "zh"))
    title_key = next(
        (candidate_title_key for mkt, candidate_title_key, _ in _MARKET_REVIEW_MARKETS if mkt == market),
        "",
    )
    return str(review_text.get(title_key) or market.upper()).lstrip("#").strip()


def _resolve_market_review_regions(raw_region: Optional[str]) -> list[str]:
    """Normalize MARKET_REVIEW_REGION into an ordered, non-empty region list."""

    region = str(raw_region or 'cn').strip().lower()
    if region == 'both':
        return list(_MARKET_REVIEW_REGION_ORDER)
    if ',' in region:
        requested = {
            item.strip().lower()
            for item in region.split(',')
            if item.strip().lower() in _VALID_MARKET_REVIEW_REGIONS
        }
        return [market for market in _MARKET_REVIEW_REGION_ORDER if market in requested] or ['cn']
    if region in _VALID_MARKET_REVIEW_REGIONS:
        return [region]
    return ['cn']


def run_market_review(
    notifier: NotificationService,
    analyzer: Optional[GeminiAnalyzer] = None,
    search_service: Optional[SearchService] = None,
    config: Optional[object] = None,
    send_notification: bool = True,
    merge_notification: bool = False,
    override_region: Optional[str] = None,
    query_id: Optional[str] = None,
    return_structured: bool = False,
    save_report_file: bool = True,
    persist_history: bool = True,
    trigger_source: str = "cli",
) -> Optional[str] | Optional[MarketReviewRunResult]:
    """
    执行大盘复盘分析

    Args:
        notifier: 通知服务
        analyzer: AI分析器（可选）
        search_service: 搜索服务（可选）
        config: 本次复盘使用的配置（可选，未传时读取全局配置）
        send_notification: 是否发送通知
        merge_notification: 是否合并推送（跳过本次推送，由 main 层合并个股+大盘后统一发送，Issue #190）
        override_region: 覆盖 config 的 market_review_region（Issue #373 交易日过滤后有效子集）
        query_id: 历史记录关联 ID；API 后台任务会传入 task_id，CLI/Bot 为空时自动生成
        save_report_file: 是否保存 Markdown 文件；上下文生成路径可关闭以避免多区域临时复盘互相覆盖
        persist_history: 是否写入 analysis_history；预热路径可关闭以避免覆盖用户可见的同日大盘复盘记录
        trigger_source: 触发来源，用于日志排障（cli/schedule/api/bot/service 等）

    Returns:
        复盘报告文本
    """
    runtime_config = config or get_config()
    history_query_id = query_id or f"market_review_{uuid.uuid4().hex}"
    review_text = _get_market_review_text(getattr(runtime_config, "report_language", "zh"))
    raw_region = (
        override_region
        if override_region is not None
        else (getattr(runtime_config, 'market_review_region', 'cn') or 'cn')
    )
    run_markets = _resolve_market_review_regions(raw_region)
    persist_region = ','.join(run_markets) if len(run_markets) > 1 else run_markets[0]
    logger.info(
        "[MarketReview] component=market_review action=start trigger_source=%s query_id=%s region=%s",
        trigger_source,
        history_query_id,
        persist_region,
    )

    try:
        if len(run_markets) > 1:
            # 多市场顺序执行，合并报告
            parts = []
            market_light_snapshots: Dict[str, Dict[str, Any]] = {}
            market_review_payloads: Dict[str, Dict[str, Any]] = {}
            for mkt, title_key, label in _MARKET_REVIEW_MARKETS:
                if mkt not in run_markets:
                    continue
                logger.info(
                    "[MarketReview] component=market_review action=build_report "
                    "trigger_source=%s query_id=%s region=%s label=%s",
                    trigger_source,
                    history_query_id,
                    mkt,
                    label,
                )
                mkt_analyzer = MarketAnalyzer(
                    search_service=search_service,
                    analyzer=analyzer,
                    region=mkt,
                    config=runtime_config,
                )
                review_result = mkt_analyzer.run_daily_review_with_snapshot()
                mkt_report = review_result.report
                _collect_market_light_snapshot(
                    market_light_snapshots,
                    region=mkt,
                    review_result=review_result,
                )
                market_review_payloads[mkt] = _coerce_market_review_payload(
                    review_result,
                    region=mkt,
                    report=mkt_report,
                )
                if mkt_report:
                    parts.append(f"{review_text[title_key]}\n\n{mkt_report}")
            if parts:
                review_report = f"\n\n---\n\n{review_text['separator']}\n\n".join(parts)
            else:
                review_report = None
        else:
            run_region = run_markets[0]
            label = next(
                (market_label for mkt, _, market_label in _MARKET_REVIEW_MARKETS if mkt == run_region),
                run_region,
            )
            logger.info(
                "[MarketReview] component=market_review action=build_report "
                "trigger_source=%s query_id=%s region=%s label=%s",
                trigger_source,
                history_query_id,
                run_region,
                label,
            )
            market_analyzer = MarketAnalyzer(
                search_service=search_service,
                analyzer=analyzer,
                region=run_region,
                config=runtime_config,
            )
            review_result = market_analyzer.run_daily_review_with_snapshot()
            review_report = review_result.report
            market_light_snapshots = {}
            _collect_market_light_snapshot(
                market_light_snapshots,
                region=run_region,
                review_result=review_result,
            )
            market_review_payloads = {
                run_region: _coerce_market_review_payload(
                    review_result,
                    region=run_region,
                    report=review_report,
                )
            }
        
        if review_report:
            market_review_payload = _build_combined_market_review_payload(
                review_report=review_report,
                payloads=market_review_payloads,
                region=persist_region,
                language=getattr(runtime_config, "report_language", "zh"),
                root_title=review_text["root_title"],
            )
            markdown_report = _render_market_review_payload_markdown(
                market_review_payload,
                wrapper_title=review_text["root_title"],
            )
            merge_markdown_report = _render_market_review_merge_markdown(
                market_review_payload,
                review_report=review_report,
            )
            if save_report_file:
                # 保存报告到文件
                date_str = datetime.now().strftime('%Y%m%d')
                report_filename = f"market_review_{date_str}.md"
                filepath = notifier.save_report_to_file(
                    markdown_report,
                    report_filename
                )
                logger.info(
                    "[MarketReview] component=market_review action=save_report "
                    "trigger_source=%s query_id=%s region=%s path=%s",
                    trigger_source,
                    history_query_id,
                    persist_region,
                    filepath,
                )

            if persist_history:
                _persist_market_review_history(
                    review_report=review_report,
                    markdown_report=markdown_report,
                    region=persist_region,
                    config=runtime_config,
                    query_id=history_query_id,
                    market_light_snapshots=market_light_snapshots,
                    market_review_payload=market_review_payload,
                )
            
            # 推送通知（合并模式下跳过，由 main 层统一发送）
            if merge_notification and send_notification:
                logger.info(
                    "[MarketReview] component=market_review action=skip_standalone_notification "
                    "trigger_source=%s query_id=%s region=%s",
                    trigger_source,
                    history_query_id,
                    persist_region,
                )
                _record_market_review_notification_run(
                    query_id=history_query_id,
                    channel="report",
                    status="skipped",
                    success=False,
                    attempts=0,
                )
            elif send_notification and notifier.is_available():
                # 添加标题
                report_content = _render_market_review_payload_markdown(
                    market_review_payload,
                    wrapper_title=review_text["push_title"],
                )

                success = notifier.send(report_content, email_send_to_all=True, route_type="report")
                _record_market_review_notification_run(
                    query_id=history_query_id,
                    channel="report",
                    status="success" if success else "failed",
                    success=success,
                )
                if success:
                    logger.info(
                        "[MarketReview] component=market_review action=send_notification "
                        "status=success trigger_source=%s query_id=%s region=%s",
                        trigger_source,
                        history_query_id,
                        persist_region,
                    )
                else:
                    logger.warning(
                        "[MarketReview] component=market_review action=send_notification "
                        "status=failed trigger_source=%s query_id=%s region=%s",
                        trigger_source,
                        history_query_id,
                        persist_region,
                    )
            elif not send_notification:
                logger.info(
                    "[MarketReview] component=market_review action=skip_notification "
                    "reason=no_notify trigger_source=%s query_id=%s region=%s",
                    trigger_source,
                    history_query_id,
                    persist_region,
                )
                _record_market_review_notification_run(
                    query_id=history_query_id,
                    channel="report",
                    status="skipped",
                    success=False,
                    attempts=0,
                )
            else:
                logger.info(
                    "[MarketReview] component=market_review action=skip_notification "
                    "reason=not_configured trigger_source=%s query_id=%s region=%s",
                    trigger_source,
                    history_query_id,
                    persist_region,
                )
                _record_market_review_notification_run(
                    query_id=history_query_id,
                    channel="report",
                    status="not_configured",
                    success=False,
                    attempts=0,
                )
            
            if return_structured:
                return MarketReviewRunResult(
                    report=review_report,
                    market_review_payload=market_review_payload,
                )
            if merge_notification:
                return merge_markdown_report
            return review_report
        
    except GenerationError:
        logger.exception(
            "[MarketReview] component=market_review action=failed "
            "reason=generation_backend_config trigger_source=%s query_id=%s region=%s",
            trigger_source,
            history_query_id,
            persist_region,
        )
        raise
    except Exception:
        logger.exception(
            "[MarketReview] component=market_review action=failed "
            "trigger_source=%s query_id=%s region=%s",
            trigger_source,
            history_query_id,
            persist_region,
        )
    
    return None


def _coerce_market_review_payload(
    review_result: Any,
    *,
    region: str,
    report: Optional[str],
) -> Dict[str, Any]:
    payload = getattr(review_result, "structured_payload", None)
    if isinstance(payload, dict) and payload:
        return payload
    return {
        "version": 1,
        "kind": MARKET_REVIEW_REPORT_TYPE,
        "region": region,
        "title": "",
        "sections": [{"key": "full_review", "title": "Review", "markdown": report or ""}],
        "markdown_report": report or "",
    }


def _build_combined_market_review_payload(
    *,
    review_report: str,
    payloads: Dict[str, Dict[str, Any]],
    region: str,
    language: str,
    root_title: str,
) -> Dict[str, Any]:
    normalized_language = normalize_report_language(language)
    title = root_title.lstrip("#").strip()
    if len(payloads) == 1:
        payload = dict(next(iter(payloads.values())))
        payload["version"] = payload.get("version") or 1
        payload["kind"] = MARKET_REVIEW_REPORT_TYPE
        payload["region"] = region
        payload["language"] = payload.get("language") or normalized_language
        payload["root_title"] = title
        payload["markdown_report"] = review_report
        return payload
    return {
        "version": 1,
        "kind": MARKET_REVIEW_REPORT_TYPE,
        "region": region,
        "language": normalized_language,
        "title": title,
        "root_title": title,
        "markets": payloads,
        "markdown_report": review_report,
    }


def _render_market_review_payload_markdown(
    payload: Dict[str, Any],
    *,
    wrapper_title: Optional[str] = None,
) -> str:
    """Render Markdown from the structured market-review payload for file/push compatibility."""
    body = _render_market_review_payload_body(payload)
    if wrapper_title:
        return f"{wrapper_title}\n\n{body}".strip()
    return body.strip()


def _render_market_review_merge_markdown(
    payload: Dict[str, Any],
    *,
    review_report: str,
) -> str:
    """Render market-review body for the outer combined notification wrapper."""
    markets = payload.get("markets")
    if isinstance(markets, dict) and markets:
        return _render_market_review_payload_markdown(payload)
    return _append_missing_sector_payload_block(review_report, payload)


def _render_market_review_payload_body(payload: Dict[str, Any]) -> str:
    markets = payload.get("markets")
    if isinstance(markets, dict) and markets:
        markdown_report = payload.get("markdown_report")
        if isinstance(markdown_report, str) and markdown_report.strip():
            original_markdown = markdown_report.strip()
            rendered = original_markdown
            for market in _MARKET_REVIEW_REGION_ORDER:
                market_payload = markets.get(market)
                if not isinstance(market_payload, dict):
                    continue
                title_prefix = str(market_payload.get("title") or market.upper()).strip()
                wrapper_title = _get_market_review_market_heading(payload.get("language"), market)
                segment_title_prefix = title_prefix
                if wrapper_title and _extract_market_markdown_segment(original_markdown, wrapper_title):
                    segment_title_prefix = wrapper_title
                rendered = _append_missing_sector_payload_block_to_market_segment(
                    rendered,
                    market_payload,
                    title_prefix=title_prefix,
                    segment_title_prefix=segment_title_prefix,
                )
            return rendered
        parts = []
        for market in _MARKET_REVIEW_REGION_ORDER:
            market_payload = markets.get(market)
            if isinstance(market_payload, dict):
                parts.append(_render_single_market_review_payload(market_payload))
        return "\n\n---\n\n".join(part for part in parts if part).strip()
    return _render_single_market_review_payload(payload)


def _render_single_market_review_payload(payload: Dict[str, Any]) -> str:
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        markdown = payload.get("markdown_report")
        rendered = markdown if isinstance(markdown, str) else ""
        return _append_missing_sector_payload_block(rendered, payload)

    title = payload.get("title")
    normalized_title = _normalize_market_review_heading(title)
    lines = []
    if isinstance(title, str) and title.strip():
        lines.extend([f"## {title.strip()}", ""])
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_title = str(section.get("title") or "").strip()
        markdown = str(section.get("markdown") or "").strip()
        if not markdown:
            continue
        should_render_section_title = (
            section_title
            and section.get("key") != "overview"
            and _normalize_market_review_heading(section_title) != normalized_title
        )
        if should_render_section_title:
            lines.extend([f"### {section_title}", ""])
        lines.extend([markdown, ""])
    return _append_missing_sector_payload_block("\n".join(lines).strip(), payload)


def _append_missing_sector_payload_block(
    markdown: str,
    payload: Dict[str, Any],
    *,
    title_prefix: str = "",
    existing_markdown: Optional[Any] = None,
    segment_title_prefix: str = "",
) -> str:
    sector_block = _render_sector_payload_markdown_block(payload, title_prefix=title_prefix)
    if not sector_block:
        return markdown.strip()
    markdown_to_check = markdown if existing_markdown is None else existing_markdown
    check_title_prefix = segment_title_prefix or title_prefix
    if _markdown_has_sector_table(markdown_to_check, title_prefix=check_title_prefix):
        return markdown.strip()

    base = markdown.strip()
    if not base:
        return sector_block
    return f"{base}\n\n{sector_block}".strip()


def _append_missing_sector_payload_block_to_market_segment(
    markdown: str,
    payload: Dict[str, Any],
    *,
    title_prefix: str = "",
    segment_title_prefix: str = "",
) -> str:
    base = markdown.strip()
    check_title_prefix = segment_title_prefix or title_prefix
    sector_block = _render_sector_payload_markdown_block(payload, title_prefix=title_prefix)
    if not sector_block:
        return base
    if _markdown_has_sector_table(base, title_prefix=check_title_prefix):
        return base

    segment_span = _find_market_markdown_segment_span(base, check_title_prefix)
    if segment_span is None:
        return _append_missing_sector_payload_block(
            base,
            payload,
            title_prefix=title_prefix,
            existing_markdown=base,
            segment_title_prefix=check_title_prefix,
        )

    start, end = segment_span
    segment = base[start:end].strip()
    rendered_segment = f"{segment}\n\n{sector_block}".strip() if segment else sector_block
    suffix = base[end:]
    if suffix and not suffix.startswith(("\n", "\r")):
        rendered_segment = f"{rendered_segment}\n\n"
    return f"{base[:start]}{rendered_segment}{suffix}".strip()


def _render_sector_payload_markdown_block(
    payload: Dict[str, Any],
    *,
    title_prefix: str = "",
) -> str:
    sector_block = _render_sector_payload_block(payload)
    if not sector_block:
        return ""
    language = normalize_report_language(payload.get("language"))
    title = "Sector Highlights" if language == "en" else "板块主线"
    heading = f"{title_prefix} / {title}" if title_prefix else title
    return f"### {heading}\n\n{sector_block}".strip()


def _markdown_has_sector_table(markdown: Any, *, title_prefix: str = "") -> bool:
    text = str(markdown or "")
    if title_prefix:
        title = title_prefix.strip()
        prefixed_markers = (
            f"### {title} / 板块主线",
            f"### {title} / Sector Highlights",
        )
        if any(marker in text for marker in prefixed_markers):
            return True
        segment = _extract_market_markdown_segment(text, title)
        if segment is None:
            return False
        text = segment

    return _markdown_contains_sector_markers(text)


def _extract_market_markdown_segment(markdown: str, title: str) -> Optional[str]:
    segment_span = _find_market_markdown_segment_span(markdown, title)
    if segment_span is None:
        return None
    start, end = segment_span
    return markdown[start:end]


def _find_market_markdown_segment_span(markdown: str, title: str) -> Optional[tuple[int, int]]:
    if not title:
        return None
    heading_pattern = re.compile(rf"(?m)^(#{{1,2}})\s+{re.escape(title)}\s*$")
    match = heading_pattern.search(markdown)
    if not match:
        return None
    heading_level = len(match.group(1))
    next_heading = re.search(
        rf"(?m)^(?:#{{1,{heading_level}}}\s+|---\s*$)",
        markdown[match.end():],
    )
    end = match.end() + next_heading.start() if next_heading else len(markdown)
    return match.start(), end


def _markdown_contains_sector_markers(text: str) -> bool:
    markers = (
        "#### 领涨板块",
        "#### 领跌板块",
        "#### 行业板块领涨",
        "#### 行业板块领跌",
        "#### Leading Sectors",
        "#### Lagging Sectors",
        "#### Leading Industry Sectors",
        "#### Lagging Industry Sectors",
        "| 排名 | 板块 |",
        "| 排名 | 行业板块 |",
        "| Rank | Sector |",
    )
    return any(marker in text for marker in markers)


def _render_sector_payload_block(payload: Dict[str, Any]) -> str:
    sectors = payload.get("sectors")
    if not isinstance(sectors, dict):
        return ""
    top = sectors.get("top") if isinstance(sectors.get("top"), list) else []
    bottom = sectors.get("bottom") if isinstance(sectors.get("bottom"), list) else []
    if not top and not bottom:
        return ""

    language = normalize_report_language(payload.get("language"))
    lines = []
    if top:
        if language == "en":
            lines.extend(["#### Leading Sectors", "| Rank | Sector | Change |", "|------|--------|--------|"])
        else:
            lines.extend(["#### 领涨板块 Top 5", "| 排名 | 板块 | 涨跌幅 |", "|------|------|--------|"])
        for rank, sector in enumerate(top[:5], 1):
            if not isinstance(sector, dict):
                continue
            name = str(sector.get("name") or "-").strip() or "-"
            lines.append(f"| {rank} | {name} | {_format_sector_change_pct(sector)} |")
    if bottom:
        if lines:
            lines.append("")
        if language == "en":
            lines.extend(["#### Lagging Sectors", "| Rank | Sector | Change |", "|------|--------|--------|"])
        else:
            lines.extend(["#### 领跌板块 Top 5", "| 排名 | 板块 | 涨跌幅 |", "|------|------|--------|"])
        for rank, sector in enumerate(bottom[:5], 1):
            if not isinstance(sector, dict):
                continue
            name = str(sector.get("name") or "-").strip() or "-"
            lines.append(f"| {rank} | {name} | {_format_sector_change_pct(sector)} |")
    return "\n".join(lines).strip()


def _format_sector_change_pct(sector: Dict[str, Any]) -> str:
    raw = sector.get("change_pct", sector.get("changePct"))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return "--"
    return f"{value:+.2f}%"


def _normalize_market_review_heading(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.lstrip("#").strip().lower().split())


def _persist_market_review_history(
    *,
    review_report: str,
    markdown_report: str,
    region: str,
    config: object,
    query_id: Optional[str] = None,
    market_light_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
    market_review_payload: Optional[Dict[str, Any]] = None,
) -> int:
    """Persist market review output into the existing analysis history table."""
    try:
        from src.storage import DatabaseManager

        report_language = normalize_report_language(getattr(config, "report_language", "zh"))
        summary = _summarize_market_review(review_report, report_language)
        if report_language == "en":
            stock_name = "Market Review"
            operation_advice = "View review"
            trend_prediction = "Market review"
        elif report_language == "ko":
            stock_name = "시황 리뷰"
            operation_advice = "리뷰 보기"
            trend_prediction = "시황 리뷰"
        else:
            stock_name = "大盘复盘"
            operation_advice = "查看复盘"
            trend_prediction = "大盘复盘"

        result = AnalysisResult(
            code=MARKET_REVIEW_HISTORY_CODE,
            name=stock_name,
            sentiment_score=50,
            trend_prediction=trend_prediction,
            operation_advice=operation_advice,
            analysis_summary=summary,
            report_language=report_language,
            news_summary=review_report,
            raw_response=markdown_report,
            data_sources="market_review",
        )

        history_query_id = query_id or f"market_review_{uuid.uuid4().hex}"
        context_snapshot = {
            "report_kind": MARKET_REVIEW_REPORT_TYPE,
            "market_review_region": region,
            "report_language": report_language,
        }
        if market_light_snapshots:
            context_snapshot["market_light_snapshots"] = market_light_snapshots
        if market_review_payload:
            context_snapshot["market_review_payload"] = market_review_payload
        diagnostic_snapshot = current_diagnostic_snapshot()
        if diagnostic_snapshot is not None:
            context_snapshot["diagnostics"] = diagnostic_snapshot
        context_snapshot["analysis_context_pack_overview"] = _build_market_review_context_overview(
            region=region,
            report_language=report_language,
            diagnostic_snapshot=diagnostic_snapshot,
        )

        db = DatabaseManager.get_instance()
        saved_history_id = db.save_analysis_history(
            result=result,
            query_id=history_query_id,
            report_type=MARKET_REVIEW_REPORT_TYPE,
            news_content=review_report,
            context_snapshot=context_snapshot,
            save_snapshot=True,
        )
        valid_saved_history_id = (
            saved_history_id
            if (
                isinstance(saved_history_id, int)
                and not isinstance(saved_history_id, bool)
                and saved_history_id > 0
            )
            else None
        )
        record_history_run(
            report_saved=bool(saved_history_id),
            metadata_saved=bool(saved_history_id),
            analysis_history_id=valid_saved_history_id,
        )
        _refresh_market_review_history_diagnostics(query_id=history_query_id)
        if saved_history_id:
            logger.info("大盘复盘历史记录已保存: query_id=%s", history_query_id)
        else:
            logger.warning("大盘复盘历史记录保存失败: query_id=%s", history_query_id)
        return saved_history_id
    except Exception as exc:
        record_history_run(
            report_saved=False,
            metadata_saved=False,
            error_message=exc,
        )
        logger.warning("大盘复盘历史记录保存异常，报告文件与推送流程继续: %s", exc, exc_info=True)
        return 0


def _build_market_review_context_overview(
    *,
    region: str,
    report_language: str,
    diagnostic_snapshot: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a low-sensitivity overview block for market-review run-flow rendering."""
    warnings: list[str] = []
    counts = {
        "available": 1,
        "missing": 0,
        "not_supported": 0,
        "fallback": 0,
        "stale": 0,
        "estimated": 0,
        "partial": 0,
        "fetch_failed": 0,
    }
    metadata: Dict[str, Any] = {
        "trigger_source": "market_review",
        "scope": "market_review",
        "report_type": MARKET_REVIEW_REPORT_TYPE,
    }
    if isinstance(diagnostic_snapshot, dict):
        metadata["trigger_source"] = diagnostic_snapshot.get("trigger_source") or metadata["trigger_source"]
        metadata["scope"] = diagnostic_snapshot.get("scope") or metadata["scope"]

    label = (
        "Market review" if report_language == "en"
        else "시황 리뷰" if report_language == "ko"
        else "大盘复盘"
    )
    return {
        "pack_version": "market_review/1.0",
        "created_at": datetime.now().isoformat(),
        "subject": {
            "code": MARKET_REVIEW_HISTORY_CODE,
            "stock_name": label,
            "market": region,
        },
        "blocks": [
            {
                "key": MARKET_REVIEW_REPORT_TYPE,
                "label": label,
                "status": "available",
                "source": MARKET_REVIEW_REPORT_TYPE,
                "warnings": warnings,
                "missing_reasons": [],
            }
        ],
        "counts": counts,
        "warnings": warnings,
        "metadata": metadata,
        "data_quality": {
            "level": "good",
            "overall_score": 100,
            "available": 1,
            "total": 1,
            "missing": 0,
        },
    }


def _summarize_market_review(review_report: str, report_language: str) -> str:
    for line in (review_report or "").splitlines():
        text = line.strip().lstrip("#").strip()
        if text and not text.startswith("---") and not text.startswith(">"):
            return text[:200]
    if report_language == "en":
        return "Market review report generated."
    if report_language == "ko":
        return "시황 리뷰 리포트가 생성되었습니다."
    return "大盘复盘报告已生成。"
