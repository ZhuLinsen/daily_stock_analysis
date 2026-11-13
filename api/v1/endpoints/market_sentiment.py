# -*- coding: utf-8 -*-
"""
===================================
市场情绪快照接口（issue #1939 Wave 5）
===================================

职责：
1. POST /api/v1/market-sentiment/snapshots 手动触发（202 受理 + 全局锁 409 +
   已有 complete 快照 200 短路；后台经 submit_background_task 异步执行）
2. GET /api/v1/market-sentiment/snapshots 日期列表（limit 1~200 / offset >= 0）
3. GET /api/v1/market-sentiment/snapshots/{trade_date} 详情（payload +
   provider_trace + quality_status + completeness）
4. GET /api/v1/market-sentiment/trend 指标趋势（枚举 metric + days/日期范围，
   end 自动钳制在 min(上海今天, 最新快照日)，未来行永不入序列）

契约来源：实施计划 §4；触发目标解析、锁与后台任务体语义全部由
``src/services/market_sentiment_service.py``（Wave 4）提供，本模块只做
HTTP 层机械映射。配置开关（路由可见性）由 Wave 6 统一接入。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Response

from api.v1.errors import api_error
from api.v1.schemas.market_sentiment import (
    MarketSentimentExistingSnapshot,
    MarketSentimentSnapshotDetailResponse,
    MarketSentimentSnapshotListResponse,
    MarketSentimentSnapshotSummaryItem,
    MarketSentimentTriggerRequest,
    MarketSentimentTriggerResponse,
    MarketSentimentTrendPoint,
    MarketSentimentTrendResponse,
)
from src.services.market_sentiment_service import (
    TREND_METRICS,
    InvalidTargetDateError,
    SnapshotTriggerConflictError,
    TradeCalendarUnavailableError,
    get_snapshot,
    list_snapshots,
    query_trend,
    release_snapshot_trigger_lock,
    run_snapshot_job,
    trigger_snapshot,
)
from src.services.market_sentiment_service import (
    _parse_trade_date as _parse_trade_date_format,
)
from src.services.task_queue import get_task_queue

logger = logging.getLogger(__name__)

router = APIRouter()

LIST_LIMIT_MIN = 1
LIST_LIMIT_MAX = 200
TREND_DAYS_MIN = 1
TREND_DAYS_MAX = 366


def _iso_or_none(value: Optional[datetime]) -> Optional[str]:
    """ORM datetime -> ISO 8601 字符串（None 保持 None）。"""
    return value.isoformat() if value is not None else None


def _is_plain_int(value) -> bool:
    """bool 是 int 的子类，显式排除。"""
    return isinstance(value, int) and not isinstance(value, bool)


# ============================================================
# POST /snapshots - 手动触发情绪快照（§4.1）
# ============================================================

@router.post(
    "/snapshots",
    response_model=MarketSentimentTriggerResponse,
    status_code=202,
    responses={
        202: {"description": "快照任务已受理", "model": MarketSentimentTriggerResponse},
        200: {"description": "已有 complete 快照，短路返回既有结果", "model": MarketSentimentTriggerResponse},
        400: {"description": "日期格式或触发目标不合法"},
        409: {"description": "快照任务正在执行中（全局锁冲突）"},
        500: {"description": "后台任务提交失败"},
        503: {"description": "交易日历暂不可用，无法解析触发目标"},
    },
    summary="触发市场情绪快照",
    description=(
        "手动触发一个后台情绪快照任务。一期仅支持触发「最近已收盘交易日」单一目标"
        "（按 Asia/Shanghai 收盘规则解析：≥15:00 且当日交易日为当日，否则上一交易日）；"
        "显式 trade_date 必须等于该目标日。该交易日已有 complete 快照且 force=false 时"
        "短路返回既有结果（200，不产生抓取成本）。"
    ),
)
def trigger_market_sentiment_snapshot(
    request: Optional[MarketSentimentTriggerRequest] = Body(None),
    response: Response = None,
) -> MarketSentimentTriggerResponse:
    """触发快照：校验 -> 服务层解析目标/抢锁 -> 入队后台任务。"""
    request = request or MarketSentimentTriggerRequest()

    # 显式日期先做格式校验（不经网络），格式错 -> 400 invalid_date
    if request.trade_date is not None:
        try:
            _parse_trade_date_format(request.trade_date)
        except ValueError:
            raise api_error(
                400,
                "invalid_date",
                f"trade_date 格式错误: {request.trade_date!r}（期望 YYYY-MM-DD）",
            )

    try:
        result = trigger_snapshot(request.trade_date, request.force)
    except InvalidTargetDateError as exc:
        raise api_error(400, "invalid_target_date", str(exc))
    except TradeCalendarUnavailableError as exc:
        # 计划 §4.1 未列枚举的 W4 新增失败面：日历依赖失败，可重试 -> 503
        raise api_error(
            503, "trade_calendar_unavailable", f"交易日历暂不可用，无法解析触发目标: {exc}"
        )
    except SnapshotTriggerConflictError as exc:
        raise api_error(409, "snapshot_running", str(exc))
    except Exception as exc:
        logger.error(
            "[MarketSentiment] 触发快照时发生内部错误: %s", exc, exc_info=True
        )
        raise api_error(500, "internal_error", f"触发快照时发生内部错误: {exc}")

    if result.status == "short_circuited":
        if response is not None:
            response.status_code = 200
        summary = result.existing_snapshot_summary or {}
        return MarketSentimentTriggerResponse(
            status="short_circuited",
            trade_date=result.trade_date,
            task_id=None,
            message="该交易日已有 complete 快照，直接返回既有结果（未启动新任务）",
            superseded_by_existing_complete=True,
            existing_snapshot=MarketSentimentExistingSnapshot(**summary),
        )

    try:
        task = get_task_queue().submit_background_task(
            lambda: run_snapshot_job(result.trade_date),
            stock_code="market_sentiment",
            stock_name="市场情绪快照",
            message="市场情绪快照任务已提交",
            task_id=result.task_id,
        )
    except Exception as exc:
        # 入队失败必须释放全局锁，否则锁泄漏导致后续触发全部 409
        release_snapshot_trigger_lock()
        logger.error(
            "[MarketSentiment] 快照任务入队失败 trade_date=%s: %s",
            result.trade_date, exc, exc_info=True,
        )
        raise api_error(500, "submit_failed", f"快照任务提交失败: {exc}")

    return MarketSentimentTriggerResponse(
        status="accepted",
        trade_date=result.trade_date,
        task_id=task.task_id,
        message="市场情绪快照任务已提交，完成后可经列表/详情接口查询结果",
    )


# ============================================================
# GET /snapshots - 日期列表（§4.2）
# ============================================================

@router.get(
    "/snapshots",
    response_model=MarketSentimentSnapshotListResponse,
    responses={
        200: {"description": "快照日期列表（只列实际存在的快照，不插值不补零）"},
        400: {"description": "分页参数越界"},
    },
    summary="获取情绪快照日期列表",
)
def list_market_sentiment_snapshots(
    limit: int = 30,
    offset: int = 0,
    order: str = "desc",
) -> MarketSentimentSnapshotListResponse:
    """分页列出快照摘要；边界校验属于 API 层（仓储层仅防御性钳制）。"""
    if not _is_plain_int(limit) or not (LIST_LIMIT_MIN <= limit <= LIST_LIMIT_MAX):
        raise api_error(
            400, "invalid_limit", f"limit 取值范围 {LIST_LIMIT_MIN}~{LIST_LIMIT_MAX}"
        )
    if not _is_plain_int(offset) or offset < 0:
        raise api_error(400, "invalid_offset", "offset 必须 >= 0")
    if order not in ("asc", "desc"):
        raise api_error(400, "invalid_order", "order 仅支持 asc / desc")

    result = list_snapshots(limit=limit, offset=offset, order=order)
    return MarketSentimentSnapshotListResponse(
        items=[
            MarketSentimentSnapshotSummaryItem(
                trade_date=item.trade_date,
                quality_status=item.quality_status,
                completeness=item.completeness,
                created_at=_iso_or_none(item.created_at),
                updated_at=_iso_or_none(item.updated_at),
            )
            for item in result.items
        ],
        total=result.total,
    )


# ============================================================
# GET /snapshots/{trade_date} - 详情（§4.3）
# ============================================================

@router.get(
    "/snapshots/{trade_date}",
    response_model=MarketSentimentSnapshotDetailResponse,
    responses={
        200: {"description": "完整快照（payload + provider_trace + 质量字段）"},
        400: {"description": "日期格式错误"},
        404: {"description": "该交易日无快照"},
    },
    summary="获取单日情绪快照详情",
)
def get_market_sentiment_snapshot_detail(
    trade_date: str,
) -> MarketSentimentSnapshotDetailResponse:
    """返回完整 payload 与取数轨迹；narrative 一期为 null（LLM 后置）。"""
    try:
        _parse_trade_date_format(trade_date)
    except ValueError:
        raise api_error(
            400,
            "invalid_date",
            f"trade_date 格式错误: {trade_date!r}（期望 YYYY-MM-DD）",
        )

    record = get_snapshot(trade_date)
    if record is None:
        raise api_error(
            404, "snapshot_not_found", f"未找到 {trade_date} 的市场情绪快照"
        )
    return MarketSentimentSnapshotDetailResponse(
        trade_date=record.trade_date,
        market=record.market,
        quality_status=record.quality_status,
        completeness=record.completeness,
        payload=record.payload,
        provider_trace=record.provider_trace,
        created_at=_iso_or_none(record.created_at),
        updated_at=_iso_or_none(record.updated_at),
    )


# ============================================================
# GET /trend - 指标趋势（§4.4）
# ============================================================

@router.get(
    "/trend",
    response_model=MarketSentimentTrendResponse,
    responses={
        200: {"description": "趋势序列（空序列返回 200 + available_points=0）"},
        400: {"description": "metric/days/日期范围不合法"},
    },
    summary="获取情绪指标趋势序列",
    description=(
        "metric 为 §4.4 枚举；days ∈ [1,366] 或 start_date+end_date 二选一"
        "（都给以日期范围为准）。end 缺省时自动钳制在 min(上海今天, 最新快照日)，"
        "未来行永不进入序列；缺失日不伪造点。"
    ),
)
def get_market_sentiment_trend(
    metric: str,
    days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> MarketSentimentTrendResponse:
    """指标趋势序列；边界语义（<= end / 未来钳制）由服务层固化并测试。"""
    if metric not in TREND_METRICS:
        raise api_error(
            400,
            "invalid_metric",
            f"metric 仅支持 {sorted(TREND_METRICS)} 之一，收到: {metric!r}",
        )
    if days is not None and (
        not _is_plain_int(days)
        or not (TREND_DAYS_MIN <= days <= TREND_DAYS_MAX)
    ):
        raise api_error(
            400,
            "invalid_days",
            f"days 取值范围 {TREND_DAYS_MIN}~{TREND_DAYS_MAX}",
        )
    for label, value in (("start_date", start_date), ("end_date", end_date)):
        if value is None:
            continue
        try:
            _parse_trade_date_format(value)
        except ValueError:
            raise api_error(
                400, "invalid_date", f"{label} 格式错误: {value!r}（期望 YYYY-MM-DD）"
            )
    if start_date is not None and end_date is not None:
        if _parse_trade_date_format(start_date) > _parse_trade_date_format(end_date):
            raise api_error(
                400, "invalid_date_range", "start_date 必须早于或等于 end_date"
            )

    result = query_trend(metric, days, start_date, end_date)
    return MarketSentimentTrendResponse(
        metric=result.metric,
        points=[
            MarketSentimentTrendPoint(
                trade_date=point.trade_date,
                value=point.value,
                quality_status=point.quality_status,
            )
            for point in result.points
        ],
        available_points=result.available_points,
    )
