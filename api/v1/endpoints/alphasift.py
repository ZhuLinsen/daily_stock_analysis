# -*- coding: utf-8 -*-
"""AlphaSift stock screening API routes."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from api.deps import get_config_dep
from src.config import Config
from src.services.alphasift_service import AlphaSiftService

router = APIRouter()


class AlphaSiftScreenRequest(BaseModel):
    market: str = Field("cn", min_length=1, max_length=16)
    strategy: str = Field("dual_low", min_length=1, max_length=64)
    max_results: int = Field(20, ge=1, le=100)


class AlphaSiftStrategyResponse(BaseModel):
    id: str
    name: str = ""
    title: str = ""
    description: str = ""
    category: str = ""
    tag: str = ""
    tags: List[str] = Field(default_factory=list)
    market_scope: List[str] = Field(default_factory=list)
    market: str = ""


def _service(config: Config) -> AlphaSiftService:
    return AlphaSiftService(config=config)


@router.get("/status")
def alphasift_status(config: Config = Depends(get_config_dep)) -> Dict[str, Any]:
    return _service(config).status()


@router.get("/strategies")
def alphasift_strategies(
    request: Request,
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    return _service(config).strategies()


@router.post("/install")
def alphasift_install(
    request: Request,
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    return _service(config).install(request=request)


@router.post("/screen")
def alphasift_screen(
    request: AlphaSiftScreenRequest,
    http_request: Request,
    config: Config = Depends(get_config_dep),
) -> Dict[str, Any]:
    return _service(config).screen(
        strategy=request.strategy,
        market=request.market,
        max_results=request.max_results,
    )
