"""Manage the local ChatGPT connection without exposing model credentials."""
import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from api.deps import chatgpt_unavailable_reason, require_chatgpt_access
from src.services.chatgpt_oauth_service import ChatGPTError, get_chatgpt_service

router = APIRouter()


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["new"] | None = None
    registration_id: str | None = Field(default=None, min_length=1)
    retry_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def one_target(self):
        if sum(value is not None for value in (self.registration_id, self.retry_id, self.mode)) > 1:
            raise ValueError("Choose a saved ChatGPT account or retry an authorization")
        return self


class DisconnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str | None = Field(default=None, min_length=1)
    attempt_id: str | None = Field(default=None, min_length=1)
    identity_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def one_target(self):
        if sum(value is not None for value in (self.connection_id, self.attempt_id, self.identity_id)) != 1:
            raise ValueError("Specify one ChatGPT connection, authorization attempt, or sign-in")
        return self


class ResumeUsageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(min_length=1)
    usage_pause_id: str = Field(min_length=1)


def _operation(request, action, *args, **kwargs):
    require_chatgpt_access(request)
    try:
        return getattr(get_chatgpt_service(), action)(*args, **kwargs)
    except ChatGPTError as exc:
        status = 409 if exc.code in {"chatgpt_connection_busy", "chatgpt_target_changed"} else 400
        if exc.code == "chatgpt_store_unavailable":
            status = 503
        raise HTTPException(status, detail={"error": exc.code, "message": str(exc)}) from None
    except OSError:
        raise HTTPException(503, detail={
            "error": "chatgpt_store_unavailable", "message": "ChatGPT connection storage is unavailable",
        }) from None


@router.get("/status")
def status(request: Request):
    reason = chatgpt_unavailable_reason(request)
    if reason:
        result = {"available": False, "connected": False, "error": reason}
        if reason == "chatgpt_store_unavailable" and getattr(request.app.state, "chatgpt_start_error", False):
            result["restart_required"] = True
        return result
    return _operation(request, "status")


@router.post("/connect")
async def connect(request: Request, options: ConnectRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(_operation, request, "connect", asyncio.get_running_loop(), **options.model_dump())


@router.get("/models")
def models(request: Request, connection_id: str, refresh: bool = False):
    return {"models": _operation(request, "models", connection_id, refresh=refresh)}


@router.post("/disconnect")
async def disconnect(request: Request, options: DisconnectRequest):
    return await run_in_threadpool(_operation, request, "disconnect", asyncio.get_running_loop(), **options.model_dump())


@router.post("/usage/resume")
async def resume_usage(request: Request, options: ResumeUsageRequest):
    return await run_in_threadpool(_operation, request, "resume_usage", **options.model_dump())
