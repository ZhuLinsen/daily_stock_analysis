"""Manage the local ChatGPT connection without exposing model credentials."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.deps import chatgpt_unavailable_reason, require_chatgpt_access
from src.services.chatgpt_oauth_service import ChatGPTError, get_chatgpt_service

router = APIRouter()


class ConnectRequest(BaseModel):
    new_account: bool = False
    reconsent: bool = False


def _operation(request, action, *args, **kwargs):
    require_chatgpt_access(request)
    try:
        return getattr(get_chatgpt_service(), action)(*args, **kwargs)
    except ChatGPTError as exc:
        status = 409 if exc.code == "chatgpt_connection_busy" else 400
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
def connect(request: Request, options: ConnectRequest):
    return _operation(request, "connect", **options.model_dump())


@router.get("/models")
def models(request: Request, connection_id: str, refresh: bool = False):
    return {"models": _operation(request, "models", connection_id, refresh=refresh)}


@router.post("/disconnect")
def disconnect(request: Request):
    return _operation(request, "disconnect")
