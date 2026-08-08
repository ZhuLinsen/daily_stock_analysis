# -*- coding: utf-8 -*-
"""Stock screening routes."""

from __future__ import annotations

import uuid
import hmac
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.deps import get_config_dep, get_database_manager
from api.v1.errors import api_error
from src.config import Config
from src.services.screening_service import ScreeningService
from src.services.task_queue import TaskStatus as QueueTaskStatus
from src.services.task_queue import get_task_queue
from src.storage import DatabaseManager

router = APIRouter()
logger = logging.getLogger(__name__)


class ScreeningScreenRequest(BaseModel):
    market: str = Field("cn", min_length=1, max_length=16)
    strategy: str = Field("dual_low", min_length=1, max_length=64)
    max_results: int = Field(20, ge=1, le=100)
    variant_seed: str = Field("", max_length=128)


class ScreeningStrategyResponse(BaseModel):
    id: str
    name: str = ""
    title: str = ""
    description: str = ""
    category: str = ""
    tag: str = ""
    tags: List[str] = Field(default_factory=list)
    market_scope: List[str] = Field(default_factory=list)
    market: str = ""
    analysis_skills: List[str] = Field(default_factory=list)


class ScreeningScreenAccepted(BaseModel):
    task_id: str
    trace_id: str
    status: str = "pending"
    message: str
    strategy: str
    market: str
    max_results: int


class ScreeningScreenTaskStatus(BaseModel):
    task_id: str
    trace_id: Optional[str] = None
    status: str
    progress: int = 0
    message: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class ScheduledSyncRequest(BaseModel):
    """Candidate snapshot submitted by the GitHub Actions owner run."""

    run_id: str = Field(..., min_length=1, max_length=64)
    target_time: str = Field("", max_length=16)
    mode: str = Field("stocks-only", max_length=32)
    source: str = Field("github_actions", max_length=32)
    run_url: str = Field("", max_length=500)
    created_at: str = Field("", max_length=64)
    candidate_count: int = Field(0, ge=0, le=100)
    candidates: List[Dict[str, Any]] = Field(default_factory=list, max_length=100)


def _require_scheduled_sync_token(request: Request) -> None:
    expected = os.getenv("WEBUI_SYNC_TOKEN", "").strip()
    supplied = request.headers.get("X-DSA-Sync-Token", "").strip()
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid scheduled sync token")


def _service(config: Config, db_manager: Any = None) -> ScreeningService:
    usable_db = db_manager if callable(getattr(db_manager, "save_screening_run", None)) else None
    return ScreeningService(config=config, db_manager=usable_db)


def _screening_task_not_found(task_id: str) -> HTTPException:
    return api_error(
        404,
        "screening_screen_task_not_found",
        f"选股任务 {task_id} 不存在或已过期",
    )


def _build_screening_notification(
    *,
    result: Dict[str, Any],
    strategy: str,
    market: str,
) -> str:
    """Build a compact result notification for WebUI-triggered screening."""
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    candidate_count = int(result.get("candidate_count") or len(candidates))
    ranking_mode = str(result.get("ranking_mode") or "factor").strip()
    llm_model = str(result.get("llm_model_used") or "").strip()
    if ranking_mode == "llm" and llm_model:
        ranking_text = f"LLM重排（{llm_model}）"
    elif result.get("llm_failure_reason"):
        ranking_text = "因子排序（LLM重排未完成）"
    else:
        ranking_text = "因子排序"

    lines = [
        "📊 **WebUI选股完成**",
        "",
        f"策略：{strategy}",
        f"市场：{market}",
        f"结果：{candidate_count} 支候选股",
        f"排序：{ranking_text}",
        "",
    ]
    if candidates:
        lines.append("候选列表：")
        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                continue
            code = str(candidate.get("code") or "-").strip()
            name = str(candidate.get("name") or code).strip()
            score = candidate.get("score")
            change_pct = candidate.get("change_pct")
            score_text = f"评分 {float(score):.1f}" if isinstance(score, (int, float)) else "评分 -"
            change_text = (
                f"涨跌 {float(change_pct):+.2f}%"
                if isinstance(change_pct, (int, float))
                else "涨跌 -"
            )
            lines.append(f"{index}. {name}（{code}）｜{score_text}｜{change_text}")
    else:
        lines.append("本次没有返回候选股票。")

    warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
    if warnings:
        lines.extend(["", "提示：" + "；".join(str(item) for item in warnings[:3])])
    return "\n".join(lines)


def _notify_screening_result(
    *,
    task_id: str,
    result: Dict[str, Any],
    strategy: str,
    market: str,
) -> None:
    """Send a WebUI screening result without affecting task success."""
    try:
        from src.notification import NotificationService

        content = _build_screening_notification(
            result=result,
            strategy=strategy,
            market=market,
        )
        dispatch = NotificationService().send_with_results(
            content,
            route_type="report",
            dedup_key=f"webui-screening:{task_id}",
        )
        if not dispatch.success:
            logger.warning(
                "WebUI screening result notification failed: task_id=%s status=%s message=%s",
                task_id,
                getattr(dispatch, "status", "unknown"),
                getattr(dispatch, "message", ""),
            )
        else:
            logger.info(
                "WebUI screening result notification sent: task_id=%s status=%s",
                task_id,
                getattr(dispatch, "status", "sent"),
            )
    except Exception as exc:  # Notification must not turn a completed screen into a failed task.
        logger.exception(
            "WebUI screening result notification raised: task_id=%s error=%s",
            task_id,
            exc,
        )


@router.get("/status")
def screening_status(config: Config = Depends(get_config_dep)) -> Dict[str, Any]:
    return _service(config).status()


@router.get("/strategies")
def screening_strategies(
    request: Request,
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    return _service(config).strategies()


@router.get("/hotspots")
def screening_hotspots(
    provider: str = Query("", max_length=32),
    top: int = Query(12, ge=1, le=50),
    refresh: bool = Query(False),
    include_details: bool = Query(False),
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    refresh_value = refresh if isinstance(refresh, bool) else bool(getattr(refresh, "default", False))
    include_details_value = (
        include_details
        if isinstance(include_details, bool)
        else bool(getattr(include_details, "default", False))
    )
    return _service(config).hotspots(
        provider=provider,
        top=top,
        refresh=refresh_value,
        include_details=include_details_value,
    )


@router.get("/hotspots/{topic:path}")
def screening_hotspot_detail(
    topic: str,
    provider: str = Query("", max_length=32),
    refresh: bool = Query(False),
    include_search: bool = Query(False),
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    refresh_value = refresh if isinstance(refresh, bool) else bool(getattr(refresh, "default", False))
    include_search_value = (
        include_search
        if isinstance(include_search, bool)
        else bool(getattr(include_search, "default", False))
    )
    return _service(config).hotspot_detail(
        topic=topic,
        provider=provider,
        refresh=refresh_value,
        include_search=include_search_value,
    )


@router.post("/screen/tasks", status_code=202, response_model=ScreeningScreenAccepted)
def screening_start_screen_task(
    request: ScreeningScreenRequest,
    http_request: Request,
    config: Config = Depends(get_config_dep),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> ScreeningScreenAccepted:
    task_id = uuid.uuid4().hex
    task_queue = get_task_queue()

    def run_screen() -> Dict[str, Any]:
        task_queue.update_task_progress(
            task_id,
            20,
            "正在执行选股，外部数据源较慢时会持续后台运行",
        )

        def report_progress(progress: int, message: str) -> None:
            task_queue.update_task_progress(task_id, progress, message)

        result = _service(config, db_manager).screen(
            strategy=request.strategy,
            market=request.market,
            max_results=request.max_results,
            selection_seed=request.variant_seed,
            progress_callback=report_progress,
        )
        task_queue.update_task_progress(
            task_id,
            98,
            f"选股已完成，正在整理 {result.get('candidate_count', 0)} 条候选",
        )
        _notify_screening_result(
            task_id=task_id,
            result=result,
            strategy=request.strategy,
            market=request.market,
        )
        return result

    task = task_queue.submit_background_task(
        run_screen,
        stock_code="screening_screen",
        stock_name=f"{request.strategy} / {request.market}",
        report_type="screening_screen",
        message="选股任务已提交",
        task_id=task_id,
        trace_id=task_id,
    )
    return ScreeningScreenAccepted(
        task_id=task.task_id,
        trace_id=task.trace_id or task.task_id,
        status=task.status.value if isinstance(task.status, QueueTaskStatus) else str(task.status),
        message=task.message or "选股任务已提交",
        strategy=request.strategy,
        market=request.market,
        max_results=request.max_results,
    )


@router.get("/screen/tasks/{task_id}", response_model=ScreeningScreenTaskStatus)
def screening_screen_task_status(task_id: str) -> ScreeningScreenTaskStatus:
    task = get_task_queue().get_task(task_id)
    if task is None or task.report_type != "screening_screen":
        raise _screening_task_not_found(task_id)

    result = task.result if task.status == QueueTaskStatus.COMPLETED and isinstance(task.result, dict) else None
    return ScreeningScreenTaskStatus(
        task_id=task.task_id,
        trace_id=task.trace_id or task.task_id,
        status=task.status.value if isinstance(task.status, QueueTaskStatus) else str(task.status),
        progress=task.progress,
        message=task.message,
        error=task.error,
        result=result,
    )


@router.post("/screen")
def screening_screen(
    request: ScreeningScreenRequest,
    http_request: Request,
    config: Config = Depends(get_config_dep),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    return _service(config, db_manager).screen(
        strategy=request.strategy,
        market=request.market,
        max_results=request.max_results,
        selection_seed=request.variant_seed,
    )


@router.post("/scheduled-sync")
def scheduled_sync(
    request: ScheduledSyncRequest,
    http_request: Request,
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    """Ingest the owner GitHub run's candidate list for WebUI display.

    This endpoint deliberately does not trigger analysis or notifications.
    GitHub Actions remains the single owner of the scheduled analysis and
    Telegram delivery path, preventing duplicate model calls and pushes.
    """

    _require_scheduled_sync_token(http_request)
    candidates = request.candidates[:100]
    payload = {
        "run_id": request.run_id,
        "strategy": "github_intraday_auto",
        "market": "cn",
        "snapshot_source": "github_actions",
        "snapshot_count": request.candidate_count,
        "after_filter_count": request.candidate_count,
        "candidate_count": len(candidates),
        "llm_ranked": False,
        "daily_enriched": False,
        "source_errors": [],
        "warnings": [],
        "target_time": request.target_time,
        "mode": request.mode,
        "source": request.source,
        "run_url": request.run_url,
        "created_at_source": request.created_at,
        "candidates": candidates,
    }
    saved = db_manager.save_screening_run(payload)
    if not saved:
        raise HTTPException(status_code=503, detail="Failed to persist scheduled candidate snapshot")
    return {
        "ok": True,
        "run_id": request.run_id,
        "candidate_count": len(candidates),
        "message": "Scheduled candidate snapshot synced",
    }


@router.get("/scheduled-latest")
def scheduled_latest(
    target_time: str = Query("", max_length=16),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    """Return the latest GitHub-owned intraday candidate snapshot."""

    runs = db_manager.list_screening_runs(
        limit=20,
        strategy="github_intraday_auto",
        market="cn",
    )
    for summary in runs:
        detail = db_manager.get_screening_run(summary.get("run_id", "")) or {}
        result = detail.get("result") if isinstance(detail.get("result"), dict) else {}
        if target_time and str(result.get("target_time", "")) != target_time:
            continue
        return {
            "available": True,
            "run": detail,
            "candidates": result.get("candidates", []),
        }
    return {"available": False, "run": None, "candidates": []}


@router.get("/history")
def screening_history(
    limit: int = Query(20, ge=1, le=100),
    strategy: str = Query("", max_length=64),
    market: str = Query("", max_length=16),
    config: Config = Depends(get_config_dep),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    return _service(config, db_manager).history(
        limit=limit,
        strategy=strategy,
        market=market,
    )


@router.get("/history/{run_id}")
def screening_history_detail(
    run_id: str,
    config: Config = Depends(get_config_dep),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    return _service(config, db_manager).history_detail(run_id)


@router.get("/source-history")
def screening_source_history(
    limit: int = Query(100, ge=1, le=100),
    config: Config = Depends(get_config_dep),
    db_manager: DatabaseManager = Depends(get_database_manager),
) -> Dict[str, Any]:
    return _service(config, db_manager).source_history(limit=limit)
