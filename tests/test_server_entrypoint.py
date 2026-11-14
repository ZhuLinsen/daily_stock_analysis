# -*- coding: utf-8 -*-
"""Tests for server.py direct-run entrypoint option resolution."""

from __future__ import annotations

import server


def test_resolve_server_uvicorn_options_defaults(monkeypatch) -> None:
    for key in ("API_HOST", "API_PORT", "API_RELOAD", "WEBUI_HOST", "WEBUI_PORT"):
        monkeypatch.delenv(key, raising=False)

    assert server._resolve_server_uvicorn_options() == {
        "host": "127.0.0.1",
        "port": 8000,
        "reload": False,
    }


def test_resolve_server_uvicorn_options_falls_back_to_webui_env(monkeypatch) -> None:
    for key in ("API_HOST", "API_PORT", "API_RELOAD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("WEBUI_PORT", "9000")

    assert server._resolve_server_uvicorn_options() == {
        "host": "0.0.0.0",
        "port": 9000,
        "reload": False,
    }


def test_resolve_server_uvicorn_options_prefers_api_env_and_reload(monkeypatch) -> None:
    monkeypatch.setenv("WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("WEBUI_PORT", "9000")
    monkeypatch.setenv("API_HOST", "127.0.0.2")
    monkeypatch.setenv("API_PORT", "8088")
    monkeypatch.setenv("API_RELOAD", "on")

    assert server._resolve_server_uvicorn_options() == {
        "host": "127.0.0.2",
        "port": 8088,
        "reload": True,
    }
