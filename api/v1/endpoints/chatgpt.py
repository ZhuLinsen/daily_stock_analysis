"""Manage the local ChatGPT connection without exposing model credentials."""
import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from api.deps import chatgpt_unavailable_reason, require_chatgpt_access
from src.services.chatgpt_oauth_service import ChatGPTError, get_chatgpt_service

router = APIRouter()


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registration_id: str | None = Field(default=None, min_length=1)


class DisconnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str | None = Field(default=None, min_length=1)
    attempt_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def one_target(self):
        if bool(self.connection_id) == bool(self.attempt_id):
            raise ValueError("Specify one ChatGPT connection or authorization attempt")
        return self


def _operation(request, action, *args, **kwargs):
    require_chatgpt_access(request)
    try:
        return getattr(get_chatgpt_service(), action)(*args, **kwargs)
    except ChatGPTError as exc:
        status = 409 if exc.code in {"chatgpt_connection_busy", "chatgpt_target_changed"} else 400
        raise HTTPException(status, detail={"error": exc.code, "message": str(exc)}) from None
    except OSError:
        raise HTTPException(503, detail={
            "error": "chatgpt_store_unavailable", "message": "ChatGPT connection storage is unavailable",
        }) from None


@router.get("/status")
def status(request: Request):
    reason = chatgpt_unavailable_reason(request)
    if reason:
        return {"available": False, "connected": False, "error": reason}
    return _operation(request, "status")


@router.post("/connect")
async def connect(request: Request, options: ConnectRequest):
    return await run_in_threadpool(_operation, request, "connect", asyncio.get_running_loop(), **options.model_dump())


@router.get("/models")
def models(request: Request, connection_id: str, refresh: bool = False):
    return {"models": _operation(request, "models", connection_id, refresh=refresh)}


@router.post("/disconnect")
async def disconnect(request: Request, options: DisconnectRequest):
    return await run_in_threadpool(_operation, request, "disconnect", asyncio.get_running_loop(), **options.model_dump())
