# -*- coding: utf-8 -*-
"""Stock screening routes."""

from __future__ import annotations

import uuid
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


def _service(config: Config, db_manager: Any = None) -> ScreeningService:
    usable_db = db_manager if callable(getattr(db_manager, "save_screening_run", None)) else None
    return ScreeningService(config=config, db_manager=usable_db)


def _screening_task_not_found(task_id: str) -> HTTPException:
    return api_error(
        404,
        "screening_screen_task_not_found",
        f"选股任务 {task_id} 不存在或已过期",
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
