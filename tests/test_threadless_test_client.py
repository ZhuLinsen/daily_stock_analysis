# -*- coding: utf-8 -*-
"""Regression tests for the local TestClient compatibility shim."""

import asyncio
from contextvars import ContextVar

import anyio.to_thread
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient as FastAPITestClient


def test_threadless_test_client_preserves_cookies_between_requests() -> None:
    app = FastAPI()

    @app.post("/login")
    def login(response: Response) -> dict[str, bool]:
        response.set_cookie("dsa_session", "session-token")
        return {"ok": True}

    @app.get("/protected")
    def protected(request: Request) -> dict[str, str | None]:
        return {"session": request.cookies.get("dsa_session")}

    client = FastAPITestClient(app)

    assert client.post("/login").status_code == 200
    assert client.get("/protected").json() == {"session": "session-token"}


def test_threadless_test_client_lifespan_runs_once_per_context() -> None:
    app = FastAPI()
    lifecycle_calls = {"startup": 0, "shutdown": 0, "requests": 0}

    @app.on_event("startup")
    async def _on_startup() -> None:
        lifecycle_calls["startup"] += 1

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        lifecycle_calls["shutdown"] += 1

    @app.get("/ping")
    def ping() -> dict[str, str]:
        lifecycle_calls["requests"] += 1
        return {"ok": "pong"}

    with FastAPITestClient(app) as client:
        assert client.get("/ping").json() == {"ok": "pong"}
        assert client.get("/ping").json() == {"ok": "pong"}

    assert lifecycle_calls["startup"] == 1
    assert lifecycle_calls["shutdown"] == 1
    assert lifecycle_calls["requests"] == 2


def test_threadless_test_client_does_not_run_lifespan_without_context() -> None:
    app = FastAPI()
    lifecycle_calls = {"startup": 0, "shutdown": 0, "requests": 0}

    @app.on_event("startup")
    async def _on_startup() -> None:
        lifecycle_calls["startup"] += 1

    @app.on_event("shutdown")
    async def _on_shutdown() -> None:
        lifecycle_calls["shutdown"] += 1

    @app.get("/ping")
    def ping() -> dict[str, str]:
        lifecycle_calls["requests"] += 1
        return {"ok": "pong"}

    client = FastAPITestClient(app)

    assert client.get("/ping").json() == {"ok": "pong"}
    assert client.get("/ping").json() == {"ok": "pong"}

    assert lifecycle_calls["startup"] == 0
    assert lifecycle_calls["shutdown"] == 0
    assert lifecycle_calls["requests"] == 2


def test_anyio_to_thread_shim_preserves_contextvars() -> None:
    request_id = ContextVar("request_id", default="")
    request_id.set("req-123")

    async def read_from_worker() -> str:
        return await anyio.to_thread.run_sync(request_id.get)

    assert anyio.run(read_from_worker) == "req-123"


def test_shutdown_default_executor_shim_accepts_timeout_argument() -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(loop.shutdown_default_executor(timeout=0.01))
    finally:
        loop.close()
