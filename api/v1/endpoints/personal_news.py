"""API for the single-user personal stock news radar."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, Request

from src.personal_news.repository import PersonalNewsRepository

router = APIRouter()


@router.get("", response_model=List[Dict[str, Any]], summary="List personal news")
def list_personal_news(
    limit: int = Query(default=50, ge=1, le=200),
    important_only: bool = Query(default=False),
) -> List[Dict[str, Any]]:
    return PersonalNewsRepository().list_articles(limit=limit, important_only=important_only)


@router.get("/providers", response_model=List[Dict[str, Any]], summary="List news radar provider status")
def list_provider_status() -> List[Dict[str, Any]]:
    return PersonalNewsRepository().list_provider_status()


@router.post("/run", response_model=Dict[str, int], summary="Run one personal news poll")
def run_personal_news_once(request: Request) -> Dict[str, int]:
    monitor = getattr(request.app.state, "personal_news_monitor", None)
    if monitor is None:
        from src.config import get_config
        from src.personal_news.service import build_personal_news_monitor

        monitor = build_personal_news_monitor(get_config())
        request.app.state.personal_news_monitor = monitor
    return monitor.run_once()


@router.get("/{news_id}", response_model=Dict[str, Any], summary="Get personal news detail")
def get_personal_news(news_id: int) -> Dict[str, Any]:
    article = PersonalNewsRepository().get_article(news_id)
    if article is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "新闻不存在"})
    return article
