# -*- coding: utf-8 -*-
"""
===================================
AI 服务管理接口
===================================

职责：
1. 提供 AI 服务的配置测试、文本生成等管理操作
2. 对接 src/ai_services/ 适配层
3. 供 Web 前端页面调用
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.ai_services import AIServiceConfig, AIServiceFactory

logger = logging.getLogger(__name__)

router = APIRouter()


# =========================================================================
# 请求/响应模型
# =========================================================================


class TestConnectionRequest(BaseModel):
    """测试连接请求。"""
    service_name: str = Field(..., description="服务名称: deepseek / hongdie")
    api_key: str = Field(..., description="API Key")
    base_url: Optional[str] = Field(None, description="API 基础地址，留空使用默认")
    model: Optional[str] = Field(None, description="模型名称，留空使用默认")


class TestConnectionResponse(BaseModel):
    """测试连接响应。"""
    ok: bool
    message: str
    service: str
    model: str
    elapsed_ms: Optional[float] = None


class GenerateRequest(BaseModel):
    """文本生成请求。"""
    service_name: str = Field(..., description="服务名称: deepseek / hongdie")
    api_key: str = Field(..., description="API Key")
    prompt: str = Field(..., description="提示词")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    model: Optional[str] = Field(None, description="模型名称")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="温度参数")
    max_tokens: Optional[int] = Field(None, ge=1, le=65536, description="最大令牌数")
    base_url: Optional[str] = Field(None, description="API 基础地址")
    timeout: Optional[float] = Field(None, description="超时秒数")


class GenerateResponse(BaseModel):
    """文本生成响应。"""
    ok: bool
    text: Optional[str] = None
    error: Optional[str] = None
    service: str
    model: str
    elapsed_ms: float


class ModelInfo(BaseModel):
    """模型信息。"""
    service: str
    models: List[str]


class ServiceInfo(BaseModel):
    """服务信息。"""
    name: str
    label: str
    description: str
    default_base_url: str
    homepage: Optional[str] = None


# =========================================================================
# 工具函数
# =========================================================================


def _create_service(service_name: str, api_key: str, **overrides: Any) -> Any:
    """根据参数临时创建服务实例（不缓存）。"""
    config = AIServiceConfig()
    target = config.deepseek if service_name == "deepseek" else config.hongdie
    target.enabled = True
    target.api_key = api_key
    if overrides.get("base_url"):
        target.base_url = overrides["base_url"]
    if overrides.get("model"):
        target.model = overrides["model"]

    factory = AIServiceFactory(config)
    service = factory.get_service(service_name)
    return service


# =========================================================================
# API 端点
# =========================================================================


@router.get("/services", response_model=List[ServiceInfo])
async def list_services() -> List[ServiceInfo]:
    """获取所有可用的 AI 服务信息。"""
    from src.ai_services import DeepSeekService, HongdieService

    return [
        ServiceInfo(
            name="deepseek",
            label="DeepSeek AI",
            description="DeepSeek 官方 API 服务，支持 deepseek-chat、deepseek-v4-flash 等模型",
            default_base_url="https://api.deepseek.com",
            homepage="https://platform.deepseek.com",
        ),
        ServiceInfo(
            name="hongdie",
            label="红蝶AI",
            description="红蝶AI OpenAI-compatible API 代理，支持 GPT、Claude、Gemini、DeepSeek 等多种模型",
            default_base_url="https://tokento.vip/v1",
            homepage="https://tokento.vip",
        ),
    ]


@router.get("/models", response_model=List[ModelInfo])
async def list_models() -> List[ModelInfo]:
    """获取所有服务支持的模型列表。"""
    from src.ai_services import DeepSeekService, HongdieService

    return [
        ModelInfo(service="deepseek", models=DeepSeekService.get_supported_models()),
        ModelInfo(service="hongdie", models=HongdieService.get_supported_models()),
    ]


@router.post("/test", response_model=TestConnectionResponse)
async def test_connection(req: TestConnectionRequest) -> TestConnectionResponse:
    """测试 AI 服务连接。"""
    import time

    service_name = req.service_name.lower()
    if service_name not in ("deepseek", "hongdie"):
        raise HTTPException(status_code=400, detail=f"不支持的服务: {service_name}")

    t0 = time.monotonic()
    try:
        service = _create_service(
            service_name,
            req.api_key,
            base_url=req.base_url,
            model=req.model,
        )
        result = service.check_connection()
        elapsed = (time.monotonic() - t0) * 1000
        return TestConnectionResponse(
            ok=result["ok"],
            message=result["message"],
            service=service_name,
            model=result.get("model", req.model or ""),
            elapsed_ms=round(elapsed, 1),
        )
    except Exception as exc:
        elapsed = (time.monotonic() - t0) * 1000
        return TestConnectionResponse(
            ok=False,
            message=str(exc),
            service=service_name,
            model=req.model or "",
            elapsed_ms=round(elapsed, 1),
        )


@router.post("/generate", response_model=GenerateResponse)
async def generate_text(req: GenerateRequest) -> GenerateResponse:
    """调用 AI 服务生成文本。"""
    import time

    service_name = req.service_name.lower()
    if service_name not in ("deepseek", "hongdie"):
        raise HTTPException(status_code=400, detail=f"不支持的服务: {service_name}")

    t0 = time.monotonic()
    try:
        service = _create_service(
            service_name,
            req.api_key,
            base_url=req.base_url,
            model=req.model,
        )
        result = service.generate_text(
            req.prompt,
            system_prompt=req.system_prompt,
            model=req.model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            timeout=req.timeout,
            use_cache=False,
        )
        elapsed = (time.monotonic() - t0) * 1000
        return GenerateResponse(
            ok=True,
            text=result,
            service=service_name,
            model=req.model or "",
            elapsed_ms=round(elapsed, 1),
        )
    except Exception as exc:
        elapsed = (time.monotonic() - t0) * 1000
        return GenerateResponse(
            ok=False,
            error=str(exc),
            service=service_name,
            model=req.model or "",
            elapsed_ms=round(elapsed, 1),
        )
