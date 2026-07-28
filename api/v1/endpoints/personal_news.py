"""API for the single-user personal stock news radar."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.personal_news.repository import PersonalNewsRepository
from src.personal_news.schemas import parse_stock_symbol, parse_watchlist_input
from src.personal_news.service import get_personal_news_monitor

router = APIRouter()


class WatchlistUpdate(BaseModel):
    symbols: str = Field(min_length=1, max_length=5000)


class RefreshRequest(BaseModel):
    trigger: str = Field(default="manual", pattern=r"^(page_open|manual|watchlist_add)$")


@router.get("", response_model=List[Dict[str, Any]], summary="List personal news")
def list_personal_news(
    limit: int = Query(default=50, ge=1, le=200),
    important_only: bool = Query(default=False),
) -> List[Dict[str, Any]]:
    return PersonalNewsRepository().list_articles(limit=limit, important_only=important_only)


@router.get("/providers", response_model=List[Dict[str, Any]], summary="List news radar provider status")
def list_provider_status() -> List[Dict[str, Any]]:
    return PersonalNewsRepository().list_provider_status()


@router.get("/watchlist", response_model=List[Dict[str, str]], summary="List personal news watchlist")
def list_watchlist() -> List[Dict[str, str]]:
    return PersonalNewsRepository().list_watchlist()


@router.post("/watchlist", response_model=Dict[str, Any], summary="Add symbols to personal news watchlist")
def add_watchlist(request: WatchlistUpdate) -> Dict[str, Any]:
    try:
        symbols = parse_watchlist_input(request.symbols)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_symbol", "message": str(exc)}) from exc
    repository = PersonalNewsRepository()
    existing = set(repository.get_watchlist_symbols())
    added = [symbol for symbol in symbols if symbol not in existing]
    items = repository.add_watchlist_symbols(added)
    refresh = None
    if added:
        refresh = get_personal_news_monitor().request_refresh(
            trigger="watchlist_add",
            symbols=added,
            force=True,
        )
    return {"items": items, "added": added, "refresh": refresh}


@router.delete("/watchlist/{symbol}", response_model=List[Dict[str, str]], summary="Remove a watchlist symbol")
def delete_watchlist(symbol: str) -> List[Dict[str, str]]:
    try:
        normalized, _ = parse_stock_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_symbol", "message": str(exc)}) from exc
    return PersonalNewsRepository().remove_watchlist_symbol(normalized)


@router.post("/refresh", response_model=Dict[str, Any], summary="Start a non-blocking personal news refresh")
def refresh_personal_news(
    request: RefreshRequest,
) -> Dict[str, Any]:
    monitor = get_personal_news_monitor()
    if request.trigger == "page_open" and not monitor.settings.refresh_on_open:
        return {**monitor.refresh_status(), "status": "completed", "message": "refresh_on_open_disabled"}
    return monitor.request_refresh(trigger=request.trigger)


@router.get("/refresh/status", response_model=Dict[str, Any], summary="Get personal news refresh status")
def get_refresh_status() -> Dict[str, Any]:
    return get_personal_news_monitor().refresh_status()


@router.post("/run", response_model=Dict[str, Any], summary="Run one personal news poll")
def run_personal_news_once() -> Dict[str, Any]:
    return get_personal_news_monitor().run_once(trigger="api")


@router.get("/{news_id}", response_model=Dict[str, Any], summary="Get personal news detail")
def get_personal_news(news_id: int) -> Dict[str, Any]:
    article = PersonalNewsRepository().get_article(news_id)
    if article is None:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": "新闻不存在"})
    return article
