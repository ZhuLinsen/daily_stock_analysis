# -*- coding: utf-8 -*-
"""Suites 2, 5, 6, 7, 8, 9, 10: Real Config E2E, Pool properties, Stream ownership, Redaction, Real-TCP loopback + proxy, LiteLLM Parity Harness, and Zero-LiteLLM subprocess import boundary."""

from __future__ import annotations

from concurrent.futures import CancelledError
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import patch

import httpx
import litellm as real_litellm
import pytest

from src.agent.llm_adapter import LLMToolAdapter
from src.analyzer import GeminiAnalyzer
from src.config import Config
from src.core.stock_execution_context import (
    StockCancellationToken,
    set_current_stock_cancellation,
)
from src.llm.hermes import open_hermes_no_proxy_client
from src.llm.native_engine import get_pooled_httpx_client
from src.llm.native_pool import DeploymentPool, parse_retry_after
from src.llm.native_types import (
    DeploymentSpec,
    NativeAPIError,
    NativeAuthenticationError,
    NativeBadRequestError,
    NativeConfigError,
    NativeConnectionError,
    NativeIncompleteStreamError,
    NativeNotFoundError,
    NativeProviderBlockedError,
    NativeRateLimitError,
    NativeTimeoutError,
)
from src.llm.transport import (
    NativeUnifiedRouter,
    NativeUnifiedTransport,
    create_native_transport,
    reset_transport_cache,
    resolve_exception_types,
    resolve_llm_transport_mode,
)
from src.services import image_stock_extractor
from src.services.doctor_service import format_doctor_report, run_doctor_diagnostics
from src.services.screening.models import Pick
from src.services.screening.ranker import rank_candidates
from src.services.system_config_service import SystemConfigService

REPO_ROOT = Path(__file__).resolve().parent.parent


# ============================================================
# Helper: Real-TCP Loopback HTTP/1.1 + Chunked SSE Server
# ============================================================


class _LoopbackServer:
    """Real TCP ThreadingHTTPServer capturing raw requests and supporting chunked SSE & disconnect tracking."""

    def __init__(self, responder: Callable[[Dict[str, Any], BaseHTTPRequestHandler], None]) -> None:
        self.requests: List[Dict[str, Any]] = []
        self.client_disconnected = threading.Event()
        self.server_handler_done = threading.Event()
        parent = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                del format, args

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw_body = self.rfile.read(length) if length > 0 else b""
                try:
                    parsed_body = json.loads(raw_body.decode("utf-8")) if raw_body else None
                except ValueError:
                    parsed_body = raw_body.decode("utf-8", errors="replace")
                record = {
                    "method": "POST",
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": parsed_body,
                    "raw_body": raw_body,
                }
                parent.requests.append(record)
                try:
                    responder(record, self)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    parent.client_disconnected.set()
                finally:
                    parent.server_handler_done.set()

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> "_LoopbackServer":
        self._thread.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: Any, headers: Optional[Dict[str, str]] = None) -> None:
    encoded = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.send_header("Connection", "close")
    for k, v in (headers or {}).items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(encoded)
    handler.wfile.flush()


def _send_chunked_sse(handler: BaseHTTPRequestHandler, chunks: List[bytes], delay_sec: float = 0.0) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Transfer-Encoding", "chunked")
    handler.send_header("Connection", "close")
    handler.end_headers()
    for chunk in chunks:
        if delay_sec > 0:
            time.sleep(delay_sec)
        size_line = f"{len(chunk):x}\r\n".encode("ascii")
        handler.wfile.write(size_line + chunk + b"\r\n")
        handler.wfile.flush()
    handler.wfile.write(b"0\r\n\r\n")
    handler.wfile.flush()


# ============================================================
# Suite 2: Real Config -> model_list -> router E2E (no use_transport!)
# ============================================================


@pytest.mark.parametrize("mode", ["litellm", "auto", "native"])
def test_real_config_to_router_e2e_across_all_modes_without_use_transport(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real Config._load_from_env() -> analyzer, Agent, Vision, screening, Test Channel, Doctor across 3 modes."""
    def _responder(req: Dict[str, Any], handler: BaseHTTPRequestHandler) -> None:
        if req["path"].endswith("/chat/completions"):
            body = req["body"] or {}
            if body.get("stream"):
                _send_chunked_sse(
                    handler,
                    [
                        b'data: {"id":"c1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"{\\"status\\": \\"ok\\"}"}}]}\n\n',
                        b'data: {"id":"c1","model":"gpt-4o","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":4,"total_tokens":14}}\n\n',
                        b"data: [DONE]\n\n",
                    ],
                )
                return
            msgs = body.get("messages") or []
            user_text = str(msgs[-1].get("content") if msgs else "")
            if "600519" in user_text and "ranked" in user_text.lower():
                content = json.dumps({"ranked": [{"code": "600519", "reason": "strong", "llm_score": 88}]})
            elif isinstance(msgs[-1].get("content"), list):
                content = json.dumps([{"code": "600519", "name": "贵州茅台", "confidence": "high"}])
            else:
                content = "OK"
            _send_json(
                handler,
                200,
                {
                    "id": "chatcmpl-e2e",
                    "model": "gpt-4o",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
                },
            )
            return
        _send_json(handler, 404, {"error": {"message": "not found"}})

    with _LoopbackServer(_responder) as srv:
        # Clear interfering env vars and configure real LLM_CHANNELS + LLM_TRANSPORT_MODE
        for k in list(os.environ.keys()):
            if k.startswith(("LLM_", "LITELLM_", "OPENAI_", "GEMINI_", "ANTHROPIC_", "DEEPSEEK_", "MODELFLARE_", "AIHUBMIX_", "VISION_", "AGENT_LITELLM_")):
                monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("LLM_TRANSPORT_MODE", mode)
        monkeypatch.setenv("LLM_CHANNELS", "relay")
        monkeypatch.setenv("LLM_RELAY_PROTOCOL", "openai")
        monkeypatch.setenv("LLM_RELAY_BASE_URL", f"{srv.base_url}/v1")
        monkeypatch.setenv("LLM_RELAY_API_KEY", "sk-e2e-secret-12345678")
        monkeypatch.setenv("LLM_RELAY_MODELS", "gpt-4o")
        monkeypatch.setenv("LITELLM_MODEL", "openai/gpt-4o")
        monkeypatch.setenv("VISION_MODEL", "openai/gpt-4o")
        Config.reset_instance()
        try:
            cfg = Config.get_instance()
            assert cfg.llm_transport_mode == mode
            assert resolve_llm_transport_mode(config=cfg) == mode

            # 1. Doctor reports consistent transport mode
            doc = run_doctor_diagnostics(cfg)
            assert doc["checks"]["llm"]["llm_transport_mode"] == mode
            assert f"transport={mode}" in format_doctor_report(doc)

            # 2. Analyzer + usage audit transport label
            analyzer = GeminiAnalyzer()
            text, model_used, usage = analyzer._call_litellm_impl(
                "Say OK",
                {"max_tokens": 64},
                audit_context={"call_type": "analysis"},
            )
            assert text == "OK"
            assert model_used
            expected_engine = "litellm" if mode == "litellm" else "native"
            assert usage.get("transport") == expected_engine

            # 3. Agent LLMToolAdapter
            adapter = LLMToolAdapter(cfg)
            agent_resp = adapter.call_text([{"role": "user", "content": "Say OK"}])
            assert agent_resp.content == "OK"

            # 4. Vision extractor
            vision_raw = image_stock_extractor._call_litellm_vision("aGVsbG8=", "image/png")
            assert "600519" in vision_raw

            # 5. Screening ranker
            req_before_rank = len(srv.requests)
            picks = [Pick(rank=1, code="600519", name="贵州茅台", final_score=90.0, screen_score=90.0)]
            ranked = rank_candidates(
                picks,
                ranking_hints="Prefer high quality leaders",
                llm_api_key="sk-e2e-secret-12345678",
                llm_model="openai/gpt-4o",
                llm_base_url=f"{srv.base_url}/v1",
                timeout_sec=10.0,
            )
            assert len(ranked) == 1
            assert len(srv.requests) > req_before_rank

            # 6. Test Channel
            svc = SystemConfigService()
            res = svc.test_llm_channel(
                name="relay",
                protocol="openai",
                base_url=f"{srv.base_url}/v1",
                api_key="sk-e2e-secret-12345678",
                models=["gpt-4o"],
            )
            assert res["success"] is True
        finally:
            Config.reset_instance()


def test_native_mode_config_error_caught_cleanly_by_analyzer_and_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R7: native mode + Unsupported (bedrock/) raises NativeConfigError caught cleanly by analyzer & Agent."""
    for k in list(os.environ.keys()):
        if k.startswith(("LLM_", "LITELLM_", "OPENAI_", "GEMINI_", "ANTHROPIC_", "DEEPSEEK_", "AGENT_LITELLM_")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_TRANSPORT_MODE", "native")
    Config.reset_instance()
    try:
        cfg = Config(
            llm_transport_mode="native",
            litellm_model="bedrock/anthropic.claude-3-5-sonnet",
            agent_litellm_model="bedrock/anthropic.claude-3-5-sonnet",
            llm_model_list=[
                {
                    "model_name": "bedrock/anthropic.claude-3-5-sonnet",
                    "litellm_params": {"model": "bedrock/anthropic.claude-3-5-sonnet"},
                }
            ],
        )
        with patch("src.analyzer.get_config", return_value=cfg):
            analyzer = GeminiAnalyzer()
            assert analyzer._router is None
            assert isinstance(getattr(analyzer, "_transport_config_error", None), NativeConfigError)

        adapter = LLMToolAdapter(cfg)
        assert adapter.is_available is False
        assert adapter._backend_error is not None
        resp = adapter.call_text([{"role": "user", "content": "hi"}])
        assert resp.provider == "error"
    finally:
        Config.reset_instance()


# ============================================================
# Suite 5: Pool Property Tests (Fake Clock & Sleep)
# ============================================================


def test_pool_rotation_cooldown_retry_after_attempt_cap_auth_waf_404_and_deadline() -> None:
    """P1-P4: 300-call ±10% equal rotation, cooldown skip, numeric+HTTP-date Retry-After, attempt cap, 404/WAF/401, deadline."""
    # 1. Retry-After numeric & RFC 7231 HTTP-date
    fixed_now = datetime(2026, 11, 28, 12, 0, 0, tzinfo=timezone.utc)
    future_hdr = format_datetime(fixed_now + timedelta(seconds=42), usegmt=True)
    assert parse_retry_after("15.5") == 15.5
    assert parse_retry_after(future_hdr, now_wall=lambda: fixed_now.timestamp()) == pytest.approx(42.0, abs=0.5)
    assert parse_retry_after("9999", max_seconds=300.0) == 300.0

    # 2. Equal-priority rotation: 300 calls over 3 keys -> each within ±10% (exact 100/100/100)
    now = [100.0]
    specs = [
        DeploymentSpec(
            alias="openai/gpt-4o",
            wire_model="gpt-4o",
            api_base="https://relay.example.com/v1",
            api_key=f"sk-key-{i}-123456",
            deployment_id=f"dep-{i}",
            protocol="openai_chat",
            provider="openai",
            endpoint_url="https://relay.example.com/v1/chat/completions",
            priority=0,
        )
        for i in range(3)
    ]
    pool = DeploymentPool(specs, clock=lambda: now[0])
    counts = {f"dep-{i}": 0 for i in range(3)}
    for _ in range(300):
        chosen = pool.select_candidates("openai/gpt-4o")[0]
        counts[chosen.deployment_id] += 1
    for dep_id, cnt in counts.items():
        assert 90 <= cnt <= 110, f"Unbalanced rotation for {dep_id}: {cnt}"

    # 3. Cooldown skip (skip cooling when healthy exist; fall back when all cooling)
    pool.mark_failure("dep-0", status_code=429, retry_after=25.0)
    cands = pool.select_candidates("openai/gpt-4o")
    assert all(c.deployment_id != "dep-0" for c in cands)
    pool.mark_failure("dep-1", status_code=429, retry_after=10.0)
    pool.mark_failure("dep-2", status_code=429, retry_after=50.0)
    all_cooling = pool.select_candidates("openai/gpt-4o")
    assert [c.deployment_id for c in all_cooling] == ["dep-1", "dep-0", "dep-2"]
    now[0] += 15.0
    recovered = pool.select_candidates("openai/gpt-4o")
    assert [c.deployment_id for c in recovered] == ["dep-1"]

    # 4. Attempt cap = 1 + num_retries (NOT rounds * N), 401 excluded, WAF 403 NOT excluded, 404 fails fast
    attempt_log: List[str] = []

    def _cap_handler(request: httpx.Request) -> httpx.Response:
        attempt_log.append(request.headers.get("authorization", ""))
        return httpx.Response(503, json={"error": {"message": "busy"}})

    model_list = [
        {"model_name": "m", "litellm_params": {"model": "openai/gpt-4o", "api_key": f"sk-k{i}-9999"}}
        for i in range(4)
    ]
    router = NativeUnifiedRouter(
        model_list=model_list,
        http_transport=httpx.MockTransport(_cap_handler),
        num_retries=2,
        sleep_fn=lambda _s: None,
    )
    with pytest.raises(NativeAPIError):
        router.completion(model="m", messages=[{"role": "user", "content": "hi"}])
    # 4 deployments with num_retries=2 must still cap total attempts at 1 + 2 = 3!
    assert len(attempt_log) == 3

    # 404 fails fast on 1st attempt
    hits_404 = 0

    def _404_handler(request: httpx.Request) -> httpx.Response:
        nonlocal hits_404
        del request
        hits_404 += 1
        return httpx.Response(404, json={"error": {"message": "not found"}})

    router_404 = NativeUnifiedRouter(
        model_list=model_list,
        http_transport=httpx.MockTransport(_404_handler),
        num_retries=3,
        sleep_fn=lambda _s: None,
    )
    with pytest.raises(NativeNotFoundError):
        router_404.completion(model="m", messages=[{"role": "user", "content": "hi"}])
    assert hits_404 == 1

    # 401 excludes key so single key does NOT retry on 401; WAF 403 is NOT excluded as bad auth
    hits_401 = 0

    def _401_handler(request: httpx.Request) -> httpx.Response:
        nonlocal hits_401
        del request
        hits_401 += 1
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    router_401 = NativeUnifiedRouter(
        model_list=[model_list[0]],
        http_transport=httpx.MockTransport(_401_handler),
        num_retries=3,
        sleep_fn=lambda _s: None,
    )
    with pytest.raises(NativeAuthenticationError):
        router_401.completion(model="m", messages=[{"role": "user", "content": "hi"}])
    assert hits_401 == 1

    hits_waf = 0

    def _waf_handler(request: httpx.Request) -> httpx.Response:
        nonlocal hits_waf
        del request
        hits_waf += 1
        if hits_waf == 1:
            return httpx.Response(403, headers={"content-type": "text/html"}, text="<html><title>Just a moment...</title></html>")
        return httpx.Response(
            200,
            json={"id": "c1", "model": "gpt-4o", "choices": [{"index": 0, "message": {"role": "assistant", "content": "recovered"}, "finish_reason": "stop"}]},
        )

    router_waf = NativeUnifiedRouter(
        model_list=[model_list[0]],
        http_transport=httpx.MockTransport(_waf_handler),
        num_retries=2,
        sleep_fn=lambda _s: None,
    )
    waf_resp = router_waf.completion(model="m", messages=[{"role": "user", "content": "hi"}])
    assert waf_resp.choices[0].message.content == "recovered"
    assert hits_waf == 2

    # 5. Monotonic deadline across retries (retries never reset budget)
    fake_t = [0.0]

    def _fake_sleep(sec: float) -> None:
        fake_t[0] += sec

    def _slow_503(request: httpx.Request) -> httpx.Response:
        del request
        fake_t[0] += 0.6
        return httpx.Response(503, json={"error": {"message": "retry"}})

    router_dl = NativeUnifiedRouter(
        model_list=[model_list[0]],
        http_transport=httpx.MockTransport(_slow_503),
        num_retries=5,
        clock=lambda: fake_t[0],
        sleep_fn=_fake_sleep,
    )
    with pytest.raises(NativeTimeoutError):
        router_dl.completion(model="m", messages=[{"role": "user", "content": "hi"}], timeout=1.0)
    assert fake_t[0] >= 1.0

    # 6. Cancellation inside SSE chunk loop
    token = StockCancellationToken(deadline=time.monotonic() + 30.0)

    def _cancel_sse_handler(request: httpx.Request) -> httpx.Response:
        del request

        class _ByteStream(httpx.SyncByteStream):
            def __iter__(self):
                yield b'data: {"id":"c1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"a"}}]}\n\n'
                token.cancel()
                yield b'data: {"id":"c1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"b"}}]}\n\n'
                yield b"data: [DONE]\n\n"

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=_ByteStream())

    t_cancel = create_native_transport(http_transport=httpx.MockTransport(_cancel_sse_handler), fallback_to_litellm=False)
    prev_token = set_current_stock_cancellation(token)
    try:
        stream = t_cancel.completion(
            model="openai/gpt-4o",
            api_key="sk-1234",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
        first = next(stream)
        assert first.choices[0].delta.content == "a"
        with pytest.raises(CancelledError):
            next(stream)
        stream.close()
    finally:
        set_current_stock_cancellation(prev_token)


# ============================================================
# Suite 6: Stream Ownership (Never-Iterated close & Mid-Stream Exception)
# ============================================================


def test_stream_ownership_never_iterated_close_and_mid_iteration_abort_disconnect_loopback() -> None:
    """Closing a never-iterated stream or raising mid-iteration releases the TCP socket cleanly."""
    def _infinite_sse(req: Dict[str, Any], handler: BaseHTTPRequestHandler) -> None:
        del req
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.send_header("Connection", "close")
        handler.end_headers()
        payload = b'data: {"id":"c1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"x"}}]}\n\n'
        chunk = f"{len(payload):x}\r\n".encode("ascii") + payload + b"\r\n"
        for _ in range(5000):
            handler.wfile.write(chunk)
            handler.wfile.flush()
            time.sleep(0.005)

    # 1. Never iterated + close() -> assert client_disconnected ONLY (no server_handler_done fallback!)
    with _LoopbackServer(_infinite_sse) as srv:
        transport = create_native_transport(fallback_to_litellm=False)
        stream = transport.completion(
            model="openai/gpt-4o",
            api_base=f"{srv.base_url}/v1",
            api_key="sk-stream-1234",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
        stream.close()
        assert srv.client_disconnected.wait(timeout=3.0)

    # 2. Mid-iteration caller abort + close() -> assert client_disconnected ONLY
    with _LoopbackServer(_infinite_sse) as srv:
        transport = create_native_transport(fallback_to_litellm=False)
        stream = transport.completion(
            model="openai/gpt-4o",
            api_base=f"{srv.base_url}/v1",
            api_key="sk-stream-1234",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
        try:
            with stream:
                chunk = next(stream)
                assert chunk.choices[0].delta.content == "x"
                raise RuntimeError("caller aborted")
        except RuntimeError:
            pass
        assert srv.client_disconnected.wait(timeout=3.0)


# ============================================================
# Suite 7: Secret Redaction in str(exc), exc.body, and logs
# ============================================================


def test_secret_redaction_in_exception_str_body_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    """API keys never leak in str(exc), exc.body, or caplog across HTTP, in-band, and transport errors."""
    secret = "sk-topsecret-leak-guard-987654"
    header_secret = "custom-hdr-secret-554433"

    def _http_err_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            401,
            json={"error": {"message": f"Invalid token Bearer {secret} and {header_secret}"}},
        )

    transport = create_native_transport(http_transport=httpx.MockTransport(_http_err_handler), fallback_to_litellm=False)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(NativeAuthenticationError) as exc_info:
            transport.completion(
                model="openai/gpt-4o",
                api_key=secret,
                extra_headers={"X-API-Token": header_secret},
                messages=[{"role": "user", "content": "hi"}],
            )
    assert secret not in str(exc_info.value)
    assert secret not in str(exc_info.value.body)
    assert header_secret not in str(exc_info.value)
    assert header_secret not in str(exc_info.value.body)
    assert secret not in caplog.text
    assert header_secret not in caplog.text

    # Transport error redaction
    def _transport_err_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"Failed connecting with Authorization: Bearer {secret} ?key={secret}", request=request)

    t_conn = create_native_transport(http_transport=httpx.MockTransport(_transport_err_handler), fallback_to_litellm=False)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        with pytest.raises(NativeConnectionError) as conn_exc:
            t_conn.completion(
                model="openai/gpt-4o",
                api_key=secret,
                messages=[{"role": "user", "content": "hi"}],
            )
    assert secret not in str(conn_exc.value)
    assert secret not in caplog.text


# ============================================================
# Suite 8: Real-TCP Loopback (Chunked SSE, Timeout, Disconnect, Proxy Stub + Hermes No-Proxy)
# ============================================================


def test_real_tcp_loopback_chunked_sse_timeout_disconnect_and_proxy_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real TCP: random chunked SSE, read timeout -> NativeTimeoutError, mid-stream disconnect, proxy vs Hermes no-proxy."""
    # 1. Chunked SSE with weird byte splits
    def _chunked_responder(req: Dict[str, Any], handler: BaseHTTPRequestHandler) -> None:
        del req
        full = (
            b'data: {"id":"tcp1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"Hello "}}]}\n\n'
            b'data: {"id":"tcp1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"TCP"},"finish_reason":"stop"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        _send_chunked_sse(handler, [full[:7], full[7:39], full[39:95], full[95:]])

    with _LoopbackServer(_chunked_responder) as srv:
        transport = create_native_transport(fallback_to_litellm=False)
        stream = transport.completion(
            model="openai/gpt-4o",
            api_base=f"{srv.base_url}/v1",
            api_key="sk-tcp-1234",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
        got = "".join(c.choices[0].delta.content or "" for c in stream)
        assert got == "Hello TCP"

    # 2. Slow server read timeout -> NativeTimeoutError (subclass of TimeoutError with non-empty message)
    def _slow_responder(req: Dict[str, Any], handler: BaseHTTPRequestHandler) -> None:
        del req
        time.sleep(0.5)
        _send_json(handler, 200, {"choices": [{"message": {"content": "late"}}]})

    with _LoopbackServer(_slow_responder) as srv:
        transport = create_native_transport(fallback_to_litellm=False)
        with pytest.raises(NativeTimeoutError) as t_exc:
            transport.completion(
                model="openai/gpt-4o",
                api_base=f"{srv.base_url}/v1",
                api_key="sk-tcp-1234",
                messages=[{"role": "user", "content": "hi"}],
                timeout=0.1,
            )
        assert isinstance(t_exc.value, TimeoutError)
        assert "timed out" in str(t_exc.value).lower()

    # 3. Mid-stream TCP disconnect -> raises NativeIncompleteStreamError or NativeConnectionError
    def _drop_responder(req: Dict[str, Any], handler: BaseHTTPRequestHandler) -> None:
        del req
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(b'data: {"id":"d1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"part"}}]}\n\n')
        handler.wfile.flush()
        # Close abruptly without [DONE]

    with _LoopbackServer(_drop_responder) as srv:
        transport = create_native_transport(fallback_to_litellm=False)
        stream = transport.completion(
            model="openai/gpt-4o",
            api_base=f"{srv.base_url}/v1",
            api_key="sk-tcp-1234",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
        with pytest.raises((NativeIncompleteStreamError, NativeConnectionError)):
            list(stream)

    # 4. Proxy stub via HTTP_PROXY vs Hermes no-proxy client bypassing proxy
    proxy_hits: List[str] = []

    def _proxy_responder(req: Dict[str, Any], handler: BaseHTTPRequestHandler) -> None:
        proxy_hits.append(req["path"])
        _send_json(
            handler,
            200,
            {"id": "p1", "model": "gpt-4o", "choices": [{"index": 0, "message": {"role": "assistant", "content": "via-proxy"}, "finish_reason": "stop"}]},
        )

    def _hermes_responder(req: Dict[str, Any], handler: BaseHTTPRequestHandler) -> None:
        del req
        _send_json(
            handler,
            200,
            {"id": "h1", "model": "hermes-agent", "choices": [{"index": 0, "message": {"role": "assistant", "content": "direct-hermes"}, "finish_reason": "stop"}]},
        )

    with _LoopbackServer(_proxy_responder) as proxy_srv, _LoopbackServer(_hermes_responder) as hermes_srv:
        monkeypatch.setenv("HTTP_PROXY", proxy_srv.base_url)
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        reset_transport_cache()
        try:
            transport = create_native_transport(fallback_to_litellm=False)
            # Default pooled client respects HTTP_PROXY for non-hermes remote URL
            proxied = transport.completion(
                model="openai/gpt-4o",
                api_base="http://relay.invalid/v1",
                api_key="sk-proxy-1234",
                messages=[{"role": "user", "content": "hi"}],
            )
            assert proxied.choices[0].message.content == "via-proxy"
            assert len(proxy_hits) == 1

            # Hermes no-proxy client bypasses HTTP_PROXY completely!
            with open_hermes_no_proxy_client(
                api_key="sk-hermes-1234",
                base_url=f"{hermes_srv.base_url}/v1",
                timeout=10.0,
            ) as hermes_client:
                direct = transport.completion(
                    model="openai/hermes-agent",
                    client=hermes_client,
                    messages=[{"role": "user", "content": "hi"}],
                )
            assert direct.choices[0].message.content == "direct-hermes"
            assert len(proxy_hits) == 1  # Proxy NOT touched by Hermes!
            assert len(hermes_srv.requests) == 1
        finally:
            monkeypatch.delenv("HTTP_PROXY", raising=False)
            reset_transport_cache()

    # Verify reset_transport_cache() closes pooled clients
    pooled = get_pooled_httpx_client(trust_env=True)
    assert not pooled.is_closed
    reset_transport_cache()
    assert pooled.is_closed


# ============================================================
# Suite 9: LiteLLM <-> Native Parity Harness (Same Loopback Server)
# ============================================================


def test_litellm_vs_native_parity_harness_all_four_protocols() -> None:
    """Point installed LiteLLM and NativeUnifiedTransport at the SAME loopback server and assert wire & response parity."""
    def _parity_responder(req: Dict[str, Any], handler: BaseHTTPRequestHandler) -> None:
        path = req["path"]
        if path.endswith("/chat/completions"):
            if (req["body"] or {}).get("stream"):
                _send_chunked_sse(
                    handler,
                    [
                        b'data: {"id":"chatcmpl-sp","object":"chat.completion.chunk","created":1700000000,"model":"gpt-4o","choices":[{"index":0,"delta":{"role":"assistant","content":"stream-"}}]}\n\n',
                        b'data: {"id":"chatcmpl-sp","object":"chat.completion.chunk","created":1700000000,"model":"gpt-4o","choices":[{"index":0,"delta":{"content":"parity"},"finish_reason":"stop"}]}\n\n',
                        b"data: [DONE]\n\n",
                    ],
                )
                return
            _send_json(
                handler,
                200,
                {
                    "id": "chatcmpl-parity",
                    "object": "chat.completion",
                    "created": 1700000000,
                    "model": req["body"]["model"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "parity-chat-ok",
                                "tool_calls": [
                                    {
                                        "id": "call_p1",
                                        "type": "function",
                                        "function": {"name": "get_quote", "arguments": '{"code":"600519"}'},
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                },
            )
            return
        if path.endswith("/responses"):
            _send_json(
                handler,
                200,
                {
                    "id": "resp-parity",
                    "object": "response",
                    "created_at": 1700000000,
                    "status": "completed",
                    "model": req["body"]["model"],
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "parity-resp-ok"}],
                        }
                    ],
                    "usage": {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
                },
            )
            return
        if path.endswith("/v1/messages"):
            _send_json(
                handler,
                200,
                {
                    "id": "msg_parity",
                    "type": "message",
                    "role": "assistant",
                    "model": req["body"]["model"],
                    "content": [{"type": "text", "text": "parity-anth-ok"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 15, "output_tokens": 6},
                },
            )
            return
        if ":generateContent" in path:
            _send_json(
                handler,
                200,
                {
                    "responseId": "gem-parity",
                    "modelVersion": "gemini-2.5-flash",
                    "candidates": [
                        {
                            "index": 0,
                            "content": {"role": "model", "parts": [{"text": "parity-gem-ok"}]},
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 3, "totalTokenCount": 11},
                },
            )
            return
        _send_json(handler, 404, {"error": {"message": f"unknown path {path}"}})

    native = create_native_transport(fallback_to_litellm=False)
    messages = [{"role": "user", "content": "ping"}]

    with _LoopbackServer(_parity_responder) as srv:
        fixtures = [
            (
                "openai_chat_gpt4o",
                {"model": "openai/gpt-4o", "api_base": f"{srv.base_url}/v1", "api_key": "sk-par-1234", "max_tokens": 128},
                "authorization",
                "max_tokens",
            ),
            (
                "openai_chat_gpt5",
                {"model": "openai/gpt-5", "api_base": f"{srv.base_url}/v1", "api_key": "sk-par-1234", "max_tokens": 128},
                "authorization",
                "max_completion_tokens",
            ),
            (
                "openai_responses",
                {"model": "openai/responses/gpt-5", "api_base": f"{srv.base_url}/v1", "api_key": "sk-par-1234", "max_tokens": 128},
                "authorization",
                "max_output_tokens",
            ),
            (
                "anthropic",
                {"model": "anthropic/claude-sonnet-4-6", "api_base": srv.base_url, "api_key": "sk-ant-par-1234", "max_tokens": 128},
                "x-api-key",
                "max_tokens",
            ),
            (
                "gemini",
                {"model": "gemini/gemini-2.5-flash", "api_base": f"{srv.base_url}/v1beta", "api_key": "AIzaParityKey01234567890", "max_tokens": 128},
                "x-goog-api-key",
                None,
            ),
        ]

        for name, params, expected_auth_hdr, expected_max_key in fixtures:
            srv.requests.clear()
            litellm_resp = real_litellm.completion(messages=messages, **params)
            assert len(srv.requests) == 1, f"{name}: litellm made {len(srv.requests)} calls"
            lt_req = srv.requests[0]

            srv.requests.clear()
            native_resp = native.completion(messages=messages, **params)
            assert len(srv.requests) == 1, f"{name}: native made {len(srv.requests)} calls"
            nt_req = srv.requests[0]

            # 1. Path & non-auth query parity
            from urllib.parse import parse_qsl, urlsplit

            lt_split = urlsplit(lt_req["path"])
            nt_split = urlsplit(nt_req["path"])
            assert nt_split.path == lt_split.path, f"{name}: path mismatch"
            lt_non_auth_q = [(k, v) for k, v in parse_qsl(lt_split.query) if k.lower() != "key"]
            nt_non_auth_q = [(k, v) for k, v in parse_qsl(nt_split.query) if k.lower() != "key"]
            assert nt_non_auth_q == lt_non_auth_q, f"{name}: query mismatch"
            # 2. Auth header value parity
            assert expected_auth_hdr in nt_req["headers"], f"{name}: native missing {expected_auth_hdr}"
            if expected_auth_hdr in lt_req["headers"]:
                assert nt_req["headers"][expected_auth_hdr] == lt_req["headers"][expected_auth_hdr], f"{name}: auth value mismatch"
            else:
                assert "key=" in lt_req["path"], f"{name}: litellm missing auth"
            # 3. Wire model parity (for non-Gemini protocols where model is in JSON body)
            if name != "gemini":
                assert nt_req["body"]["model"] == lt_req["body"]["model"], f"{name}: wire model mismatch"
            # 4. Max-token, store, stream_options, and tools parity
            if expected_max_key:
                assert expected_max_key in nt_req["body"], f"{name}: native missing {expected_max_key}"
                if name == "openai_chat_gpt5":
                    assert "max_completion_tokens" in lt_req["body"] or "max_tokens" in lt_req["body"]
                else:
                    assert expected_max_key in lt_req["body"], f"{name}: litellm missing {expected_max_key}"
            else:
                assert nt_req["body"]["generationConfig"]["maxOutputTokens"] == 128
                lt_gen = lt_req["body"]["generationConfig"]
                assert (lt_gen.get("maxOutputTokens") or lt_gen.get("max_output_tokens")) == 128
            if name == "openai_responses":
                assert nt_req["body"]["store"] is False
                assert "reasoning.encrypted_content" in nt_req["body"].get("include", [])
            if name == "openai_chat_gpt4o":
                assert "stream_options" not in nt_req["body"]
            # 5. Normalized response parity (content, finish_reason, usage)
            assert native_resp.choices[0].message.content == litellm_resp.choices[0].message.content, f"{name}: content mismatch"
            assert native_resp.choices[0].finish_reason == litellm_resp.choices[0].finish_reason, f"{name}: finish_reason mismatch"
            assert native_resp.usage.prompt_tokens == litellm_resp.usage.prompt_tokens, f"{name}: prompt_tokens mismatch"
            assert native_resp.usage.completion_tokens == litellm_resp.usage.completion_tokens, f"{name}: completion_tokens mismatch"

        # 6. Tool-calling & streaming SSE parity against the same local loopback server
        sample_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_quote",
                    "description": "Fetch quote",
                    "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
                },
            }
        ]
        srv.requests.clear()
        lt_tool_resp = real_litellm.completion(
            model="openai/gpt-4o",
            api_base=f"{srv.base_url}/v1",
            api_key="sk-par-1234",
            messages=messages,
            tools=sample_tools,
            max_tokens=64,
        )
        lt_tool_req = srv.requests[0]
        srv.requests.clear()
        nt_tool_resp = native.completion(
            model="openai/gpt-4o",
            api_base=f"{srv.base_url}/v1",
            api_key="sk-par-1234",
            messages=messages,
            tools=sample_tools,
            max_tokens=64,
        )
        nt_tool_req = srv.requests[0]
        assert nt_tool_req["body"]["tools"] == lt_tool_req["body"]["tools"]
        assert nt_tool_resp.choices[0].message.content == lt_tool_resp.choices[0].message.content
        assert nt_tool_resp.choices[0].finish_reason == lt_tool_resp.choices[0].finish_reason == "tool_calls"
        nt_tcs = nt_tool_resp.choices[0].message.tool_calls
        lt_tcs = lt_tool_resp.choices[0].message.tool_calls
        assert len(nt_tcs) == len(lt_tcs) == 1
        assert nt_tcs[0].id == lt_tcs[0].id == "call_p1"
        assert nt_tcs[0].function.name == lt_tcs[0].function.name == "get_quote"
        assert json.loads(nt_tcs[0].function.arguments) == json.loads(lt_tcs[0].function.arguments) == {"code": "600519"}

        # Streaming SSE parity
        srv.requests.clear()
        lt_stream_text = "".join(
            (getattr(c.choices[0].delta, "content", None) or "")
            for c in real_litellm.completion(
                model="openai/gpt-4o",
                api_base=f"{srv.base_url}/v1",
                api_key="sk-par-1234",
                messages=messages,
                stream=True,
            )
            if c.choices
        )
        srv.requests.clear()
        nt_stream_text = "".join(
            (c.choices[0].delta.content or "")
            for c in native.completion(
                model="openai/gpt-4o",
                api_base=f"{srv.base_url}/v1",
                api_key="sk-par-1234",
                messages=messages,
                stream=True,
            )
            if c.choices
        )
        assert nt_stream_text == lt_stream_text == "stream-parity"


def test_p1_3_two_and_four_healthy_keys_rotate_evenly_through_router() -> None:
    """P1-3: 2 healthy keys and 4 healthy keys rotate evenly through NativeUnifiedRouter without double-stepping."""
    for key_count in (2, 4):
        seen_auths: List[str] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            seen_auths.append(request.headers.get("authorization", ""))
            return httpx.Response(
                200,
                json={
                    "id": "c1",
                    "model": "gpt-4o",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                },
            )

        model_list = [
            {
                "model_name": "openai/gpt-4o",
                "litellm_params": {
                    "model": "openai/gpt-4o",
                    "api_base": "https://relay.example/v1",
                    "api_key": f"sk-key-{i}",
                },
            }
            for i in range(1, key_count + 1)
        ]
        router = NativeUnifiedRouter(
            model_list=model_list,
            http_transport=httpx.MockTransport(_handler),
            num_retries=1,
        )
        for _ in range(key_count * 2):
            resp = router.completion(model="openai/gpt-4o", messages=[{"role": "user", "content": "hi"}])
            assert resp.choices[0].message.content == "ok"

        expected = [f"Bearer sk-key-{i}" for i in range(1, key_count + 1)] * 2
        assert seen_auths == expected


def test_p0_2c_and_p1_4_origin_bound_caller_headers_and_per_deployment_clients_on_failover() -> None:
    """P0-2c + P1-4: Per-deployment httpx.Client honored across failover; private caller headers never cross origins."""
    seen: List[Tuple[str, Dict[str, str]]] = []

    def _client_a_handler(request: httpx.Request) -> httpx.Response:
        seen.append(("client_a", dict(request.headers)))
        return httpx.Response(503, json={"error": {"message": "origin A overloaded"}})

    def _client_b_handler(request: httpx.Request) -> httpx.Response:
        seen.append(("client_b", dict(request.headers)))
        return httpx.Response(
            200,
            json={
                "id": "c-b",
                "model": "gpt-4o",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "from-b"}, "finish_reason": "stop"}],
            },
        )

    client_a = httpx.Client(transport=httpx.MockTransport(_client_a_handler))
    client_b = httpx.Client(transport=httpx.MockTransport(_client_b_handler))
    try:
        model_list = [
            {
                "model_name": "openai/gpt-4o",
                "litellm_params": {
                    "model": "openai/gpt-4o",
                    "api_base": "https://origin-a.example/v1",
                    "api_key": "sk-origin-a-key",
                    "client": client_a,
                },
                "model_info": {"priority": 0},
            },
            {
                "model_name": "openai/gpt-4o",
                "litellm_params": {
                    "model": "openai/gpt-4o",
                    "api_base": "https://origin-b.example/v1",
                    "api_key": "sk-origin-b-key",
                    "client": client_b,
                },
                "model_info": {"priority": 1},
            },
        ]
        router = NativeUnifiedRouter(model_list=model_list, num_retries=1, sleep_fn=lambda _s: None)
        resp = router.completion(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            api_base="https://origin-a.example/v1",
            extra_headers={
                "Authorization": "Bearer sk-caller-origin-a-private",
                "X-Signature": "sig-origin-a-private",
                "X-Request-Id": "req-safe-123",
            },
        )
        assert resp.choices[0].message.content == "from-b"
        assert [tag for tag, _ in seen] == ["client_a", "client_b"]
        # Origin A got caller's origin-A private Authorization & X-Signature headers + safe X-Request-Id
        assert seen[0][1]["authorization"] == "Bearer sk-caller-origin-a-private"
        assert seen[0][1]["x-signature"] == "sig-origin-a-private"
        assert seen[0][1]["x-request-id"] == "req-safe-123"
        # Origin B MUST NOT receive origin A's private Authorization or X-Signature; only allowlisted headers cross!
        assert seen[1][1]["authorization"] == "Bearer sk-origin-b-key"
        assert "x-signature" not in seen[1][1]
        assert seen[1][1]["x-request-id"] == "req-safe-123"
    finally:
        client_a.close()
        client_b.close()


def test_p1_5_concurrent_reset_transport_cache_does_not_break_inflight_stream() -> None:
    """P1-5: Calling reset_transport_cache() mid-stream retires old pooled client without breaking in-flight stream."""
    from src.llm.native_engine import get_pooled_httpx_client

    def _two_chunk_sse(req: Dict[str, Any], handler: BaseHTTPRequestHandler) -> None:
        del req
        _send_chunked_sse(
            handler,
            [
                b'data: {"id":"c1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"first"}}]}\n\n',
                b'data: {"id":"c1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"-second"},"finish_reason":"stop"}]}\n\n',
                b"data: [DONE]\n\n",
            ],
            delay_sec=0.05,
        )

    reset_transport_cache()
    with _LoopbackServer(_two_chunk_sse) as srv:
        transport = create_native_transport(fallback_to_litellm=False)
        old_client = get_pooled_httpx_client(trust_env=True)
        stream = transport.completion(
            model="openai/gpt-4o",
            api_base=f"{srv.base_url}/v1",
            api_key="sk-reset-1234",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
        first_chunk = next(stream)
        assert first_chunk.choices[0].delta.content == "first"

        # Reset cache while stream is actively open and holding a lease!
        reset_transport_cache()
        assert not old_client.is_closed

        rest = "".join(c.choices[0].delta.content or "" for c in stream)
        assert rest == "-second"
        # Once stream finishes and releases the final lease, retired client is closed automatically!
        assert old_client.is_closed


def test_p1_6_non_stream_trickle_deadline_and_recovery_deadline_preserved() -> None:
    """P1-6: Non-streaming slow trickle hits total monotonic deadline; param recovery preserves original deadline."""
    from src.llm.errors import call_litellm_with_param_recovery
    from src.llm.native_types import NativeTimeoutError

    def _trickle_json(req: Dict[str, Any], handler: BaseHTTPRequestHandler) -> None:
        del req
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.end_headers()
        pieces = [b'{"id":"c1","model":"gpt-4o","choices":[{"index":0,"message":{"role":"assistant","content":"', b"a", b"b", b'"},"finish_reason":"stop"}]}']
        for p in pieces:
            handler.wfile.write(f"{len(p):x}\r\n".encode("ascii") + p + b"\r\n")
            handler.wfile.flush()
            time.sleep(0.12)
        handler.wfile.write(b"0\r\n\r\n")
        handler.wfile.flush()

    with _LoopbackServer(_trickle_json) as srv:
        transport = create_native_transport(fallback_to_litellm=False)
        with pytest.raises(NativeTimeoutError):
            transport.completion(
                model="openai/gpt-4o",
                api_base=f"{srv.base_url}/v1",
                api_key="sk-trickle-1234",
                messages=[{"role": "user", "content": "hi"}],
                timeout=0.18,
            )

    # Param recovery without stock cancellation token shrinks remaining timeout instead of resetting full timeout
    observed_timeouts: List[float] = []

    def _slow_400_then_ok(kw: Dict[str, Any]) -> str:
        observed_timeouts.append(float(kw["timeout"]))
        if len(observed_timeouts) == 1:
            time.sleep(0.12)
            raise RuntimeError("Unsupported parameter: temperature is not supported")
        return "ok"

    out = call_litellm_with_param_recovery(
        _slow_400_then_ok,
        model="openai/gpt-4o",
        call_kwargs={"model": "openai/gpt-4o", "messages": [], "temperature": 0.7, "timeout": 1.0},
        cache_recovery=False,
    )
    assert out == "ok"
    assert len(observed_timeouts) == 2
    assert observed_timeouts[1] < observed_timeouts[0] - 0.05


def test_p1_7_p1_8_p1_9_streaming_json_error_html_in_json_and_opaque_query_key_redaction() -> None:
    """P1-7: streaming HTTP 200 JSON error; P1-8: JSON containing <html> succeeds; P1-9: opaque ?key= redacted."""
    from src.llm.native_types import NativeRateLimitError

    # P1-8: Valid JSON completion whose content contains "<html><body>hello</body></html>" MUST succeed!
    def _json_with_html(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "id": "c-html",
                "model": "gpt-4o",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "<html><body><h1>Report</h1></body></html>"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    tr_html = NativeUnifiedTransport(http_transport=httpx.MockTransport(_json_with_html))
    resp = tr_html.completion(
        model="openai/gpt-4o",
        api_base="https://relay.example/v1",
        api_key="sk-1234",
        messages=[{"role": "user", "content": "render html"}],
    )
    assert "<html><body><h1>Report</h1></body></html>" == resp.choices[0].message.content

    # P1-7 + P1-9: Streaming HTTP 200 application/json error raises typed NativeRateLimitError (NOT IncompleteStream)
    # and redacts bare opaque query credential from both str(exc) and exc.body!
    opaque_token = "opaque_gem_secret_776655"

    def _stream_json_err(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={
                "error": {
                    "code": 429,
                    "message": f"Rate limit exceeded for credential {opaque_token}",
                    "type": "rate_limit_error",
                }
            },
        )

    tr_stream = NativeUnifiedTransport(http_transport=httpx.MockTransport(_stream_json_err))
    with pytest.raises(NativeRateLimitError) as exc_info:
        tr_stream.completion(
            model="gemini/gemini-2.5-flash",
            api_base=f"https://proxy.example/v1beta?key={opaque_token}",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
    assert opaque_token not in str(exc_info.value)
    assert opaque_token not in str(exc_info.value.body)


def test_p1_10_real_http_body_400_recovery_for_gpt5_max_tokens_and_stream_options() -> None:
    """P1-10: Real HTTP 400 recovery undoes adapter-injected max_completion_tokens & stream_options."""
    from src.llm.errors import call_litellm_with_param_recovery
    from src.llm.generation_params import clear_litellm_generation_param_recovery_cache

    clear_litellm_generation_param_recovery_cache()
    bodies_seen: List[Dict[str, Any]] = []

    def _strict_relay(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        bodies_seen.append(body)
        if "max_completion_tokens" in body:
            return httpx.Response(
                400,
                json={"error": {"message": "Unsupported parameter: 'max_completion_tokens'. Use 'max_tokens' instead."}},
            )
        if "stream_options" in body:
            return httpx.Response(
                400,
                json={"error": {"message": "Unsupported parameter: 'stream_options' is not supported."}},
            )
        if body.get("stream"):
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content=(
                    b'data: {"id":"s1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"ok-stream"},"finish_reason":"stop"}]}\n\n'
                    b"data: [DONE]\n\n"
                ),
            )
        return httpx.Response(
            200,
            json={
                "id": "c1",
                "model": "gpt-5",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok-gpt5"}, "finish_reason": "stop"}],
            },
        )

    transport = NativeUnifiedTransport(http_transport=httpx.MockTransport(_strict_relay))

    # 1. gpt-5 auto-maps max_tokens -> max_completion_tokens; 400 recovery forces max_tokens on retry!
    resp = call_litellm_with_param_recovery(
        lambda kw: transport.completion(**kw),
        model="openai/gpt-5",
        call_kwargs={
            "model": "openai/gpt-5",
            "api_base": "https://relay.example/v1",
            "api_key": "sk-1234",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 128,
        },
        cache_recovery=False,
    )
    assert resp.choices[0].message.content == "ok-gpt5"
    assert "max_completion_tokens" in bodies_seen[0]
    assert "max_tokens" in bodies_seen[1] and "max_completion_tokens" not in bodies_seen[1]

    # 2. Official api.openai.com stream auto-injects stream_options; 400 recovery suppresses it on retry!
    bodies_seen.clear()
    stream = call_litellm_with_param_recovery(
        lambda kw: transport.completion(**kw),
        model="openai/gpt-4o",
        call_kwargs={
            "model": "openai/gpt-4o",
            "api_base": "https://api.openai.com/v1",
            "api_key": "sk-1234",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
        cache_recovery=False,
    )
    assert "".join(c.choices[0].delta.content or "" for c in stream) == "ok-stream"
    assert "stream_options" in bodies_seen[0]
    assert "stream_options" not in bodies_seen[1]


def test_p1_13_and_p1_14_audit_transport_label_and_pricing_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-13: confirmed engine wins over default litellm seed & auto fallback tags litellm; P1-14: pricing sync preserves SDK costs."""
    from types import SimpleNamespace
    from src.llm.transport import get_transport_engine_label

    # P1-13a: Auto-mode fallback response gets explicitly tagged "litellm"
    class _FakeFallback:
        transport_engine = "litellm"

        def __init__(self) -> None:
            self.cost_map: Dict[str, Any] = {
                "gpt-4o": {"input_cost_per_token": 0.0000025, "output_cost_per_token": 0.00001}
            }
            self.registered_calls: List[Dict[str, Any]] = []

        def completion(self, **_kw: Any) -> Any:
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="from-fb"))],
                _hidden_params={},
            )

        def create_router(self, model_list: List[Dict[str, Any]], **_kw: Any) -> Any:
            fb = self

            class _FbRouter:
                def completion(self, **_kw: Any) -> Any:
                    return fb.completion(**_kw)

            return _FbRouter()

        def can_register_model(self) -> bool:
            return True

        def get_model_cost(self) -> Dict[str, Any]:
            return dict(self.cost_map)

        def register_model(self, model_cost: Dict[str, Any]) -> None:
            self.registered_calls.append(dict(model_cost))
            self.cost_map.update(model_cost)

    reset_transport_cache()
    fb = _FakeFallback()
    native_auto = NativeUnifiedTransport(fallback_transport=fb)
    # Register synthetic 0.0 fallback for gpt-4o AND custom non-zero pricing for custom-m1 BEFORE fallback triggers
    native_auto.register_model(
        {
            "gpt-4o": {"input_cost_per_token": 0.0, "output_cost_per_token": 0.0},
            "custom-m1": {"input_cost_per_token": 0.000001, "output_cost_per_token": 0.000002},
        }
    )

    fb_resp = native_auto.completion(model="bedrock/claude-3-5", messages=[{"role": "user", "content": "hi"}])
    # P1-13: untagged fallback response is explicitly tagged "litellm"
    assert get_transport_engine_label(fb_resp, transport=native_auto) == "litellm"

    # P1-14a: Synthetic 0.0 fallback MUST NOT overwrite real built-in gpt-4o cost!
    assert fb.cost_map["gpt-4o"]["input_cost_per_token"] == 0.0000025
    assert fb.cost_map["custom-m1"]["input_cost_per_token"] == 0.000001

    # P1-14b: Later register_model calls MUST propagate to already-materialized fallback transport!
    native_auto.register_model(
        {"later-custom-m2": {"input_cost_per_token": 0.000003, "output_cost_per_token": 0.000004}}
    )
    assert fb.cost_map["later-custom-m2"]["input_cost_per_token"] == 0.000003

    # P1-13b: Stock analysis default "litellm" audit seed yields to confirmed "native", while local CLI ID stays intact
    def _ok_chat(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "id": "c-audit",
                "model": "gpt-4o",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    for k in list(os.environ.keys()):
        if k.startswith(("LLM_", "LITELLM_", "OPENAI_", "GEMINI_", "ANTHROPIC_", "DEEPSEEK_")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_TRANSPORT_MODE", "native")
    monkeypatch.setenv("LLM_CHANNELS", "relay")
    monkeypatch.setenv("LLM_RELAY_PROTOCOL", "openai")
    monkeypatch.setenv("LLM_RELAY_BASE_URL", "https://relay.example/v1")
    monkeypatch.setenv("LLM_RELAY_API_KEY", "sk-audit-1234")
    monkeypatch.setenv("LLM_RELAY_MODELS", "gpt-4o")
    monkeypatch.setenv("LITELLM_MODEL", "openai/gpt-4o")
    Config.reset_instance()
    try:
        from src.llm.transport import use_transport

        with use_transport(NativeUnifiedTransport(http_transport=httpx.MockTransport(_ok_chat))):
            analyzer = GeminiAnalyzer()
            _txt, _m, usage_native = analyzer._call_litellm_impl(
                "Say OK",
                {"max_tokens": 32},
                audit_context={"transport": "litellm", "analysis_mode": "stock_analysis"},
            )
            assert usage_native["transport"] == "native"

            _txt2, _m2, usage_cli = analyzer._call_litellm_impl(
                "Say OK",
                {"max_tokens": 32},
                audit_context={"transport": "claude_code", "analysis_mode": "stock_analysis"},
            )
            assert usage_cli["transport"] == "claude_code"
    finally:
        Config.reset_instance()


def test_round2_p0_2_cooldown_origin_failover_and_p0_3_client_redirect_guards() -> None:
    """Round 2 P0-2 & P0-3: Cooling origin B wakes up without leaking caller secrets/headers; follow_redirects=False enforced; mismatched dep_client & originless caller_http guarded."""
    # 1. P0-2: Origin B is cooling at peek time, wakes up during failover after A returns 503.
    # Caller's Authorization, X-Signature, and fallback api_key MUST NOT reach origin B!
    now_box = [100.0]
    seen_reqs: List[Tuple[str, Dict[str, str]]] = []

    def _cooldown_handler(request: httpx.Request) -> httpx.Response:
        seen_reqs.append((str(request.url), dict(request.headers)))
        if "origin-a.example" in str(request.url):
            now_box[0] += 5.0  # Advance past origin B's cooldown before attempt 2!
            return httpx.Response(503, json={"error": {"message": "origin A down"}})
        return httpx.Response(
            200,
            json={
                "id": "c-b",
                "model": "gpt-4o",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "origin-b-ok"}, "finish_reason": "stop"}],
            },
        )

    router = NativeUnifiedRouter(
        model_list=[
            {
                "model_name": "openai/gpt-4o",
                "litellm_params": {"model": "openai/gpt-4o", "api_base": "https://origin-a.example/v1", "api_key": "sk-a"},
                "model_info": {"priority": 0},
            },
            {
                "model_name": "openai/gpt-4o",
                "litellm_params": {"model": "openai/gpt-4o", "api_base": "https://origin-b.example/v1"},
                "model_info": {"priority": 1},
            },
        ],
        http_transport=httpx.MockTransport(_cooldown_handler),
        num_retries=1,
        clock=lambda: now_box[0],
        sleep_fn=lambda _s: None,
    )
    dep_b = [d for d in router._pool.get_alias_deployments("openai/gpt-4o") if "origin-b" in d.api_base][0]
    router._pool.mark_failure(dep_b.deployment_id, status_code=429, retry_after=2.0)

    resp = router.completion(
        model="openai/gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-caller-secret-must-not-leak",
        extra_headers={
            "Authorization": "Bearer sk-caller-hdr-secret",
            "X-Signature": "private-hmac-sig",
            "X-Request-Id": "safe-req-id-99",
        },
    )
    assert resp.choices[0].message.content == "origin-b-ok"
    assert len(seen_reqs) == 2
    assert "origin-b.example" in seen_reqs[1][0]
    assert "authorization" not in seen_reqs[1][1]
    assert "x-signature" not in seen_reqs[1][1]
    assert seen_reqs[1][1]["x-request-id"] == "safe-req-id-99"

    # 2. P0-3a: Injected client with follow_redirects=True MUST NOT follow 302 cross-origin redirect!
    redirect_hosts: List[str] = []

    def _redir_handler(request: httpx.Request) -> httpx.Response:
        redirect_hosts.append(request.url.host)
        if request.url.host == "relay.example":
            return httpx.Response(302, headers={"Location": "https://evil.example/steal"})
        raise AssertionError("Must NEVER follow 302 redirect to evil.example")

    redir_client = httpx.Client(transport=httpx.MockTransport(_redir_handler), follow_redirects=True)
    try:
        tr = NativeUnifiedTransport()
        for is_stream in (False, True):
            redirect_hosts.clear()
            with pytest.raises(NativeAPIError):
                tr.completion(
                    model="openai/gpt-4o",
                    api_base="https://relay.example/v1",
                    api_key="sk-secret-redir",
                    messages=[{"role": "user", "content": "hi"}],
                    client=redir_client,
                    stream=is_stream,
                )
            assert redirect_hosts == ["relay.example"]
    finally:
        redir_client.close()

    # 3. P0-3b & P0-3c: Mismatched dep_client origin is ignored; originless caller_http does not override multi-origin dep_clients
    mismatched_client = httpx.Client(
        base_url="https://wrong-origin.example/v1",
        transport=httpx.MockTransport(lambda _r: (_ for _ in ()).throw(AssertionError("mismatched dep_client must not be used"))),
    )
    dep_a_hits: List[str] = []
    dep_b_hits: List[str] = []
    dep_a_client = httpx.Client(
        base_url="https://origin-a.example/v1",
        transport=httpx.MockTransport(
            lambda r: (dep_a_hits.append(str(r.url)), httpx.Response(503, json={"error": {"message": "busy"}}))[1]
        ),
    )
    dep_b_client = httpx.Client(
        base_url="https://origin-b.example/v1",
        transport=httpx.MockTransport(
            lambda r: (
                dep_b_hits.append(str(r.url)),
                httpx.Response(200, json={"id": "ok", "model": "gpt-4o", "choices": [{"index": 0, "message": {"role": "assistant", "content": "dep-b"}, "finish_reason": "stop"}]}),
            )[1]
        ),
    )
    originless_caller = httpx.Client(
        transport=httpx.MockTransport(lambda _r: (_ for _ in ()).throw(AssertionError("originless caller_http must not override multi-origin dep_clients")))
    )
    try:
        r_mismatch = NativeUnifiedRouter(
            model_list=[
                {
                    "model_name": "openai/gpt-4o",
                    "litellm_params": {"model": "openai/gpt-4o", "api_base": "https://origin-a.example/v1", "api_key": "sk-a", "client": mismatched_client},
                }
            ]
        )
        assert not r_mismatch._deployment_clients

        r_multi = NativeUnifiedRouter(
            model_list=[
                {
                    "model_name": "openai/gpt-4o",
                    "litellm_params": {"model": "openai/gpt-4o", "api_base": "https://origin-a.example/v1", "api_key": "sk-a", "client": dep_a_client},
                    "model_info": {"priority": 0},
                },
                {
                    "model_name": "openai/gpt-4o",
                    "litellm_params": {"model": "openai/gpt-4o", "api_base": "https://origin-b.example/v1", "api_key": "sk-b", "client": dep_b_client},
                    "model_info": {"priority": 1},
                },
            ],
            num_retries=1,
            sleep_fn=lambda _s: None,
        )
        out = r_multi.completion(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            client=originless_caller,
        )
        assert out.choices[0].message.content == "dep-b"
        assert len(dep_a_hits) == 1 and len(dep_b_hits) == 1
    finally:
        mismatched_client.close()
        dep_a_client.close()
        dep_b_client.close()
        originless_caller.close()


def test_round2_p1_1_p1_2_stream_close_retry_race_and_close_aware_base_transport() -> None:
    """Round 2 P1-1 & P1-2: close() racing with pre-chunk retry releases replacement ctx; close-aware BaseTransport survives retries."""
    from src.llm.native_engine import NativeStreamWrapper

    # 1. P1-1: NativeStreamWrapper.close() races with _on_pre_chunk_retry opening a replacement connection
    retry_started = threading.Event()
    allow_retry_return = threading.Event()
    replacement_closed = threading.Event()

    class _TrackedCtx:
        def __init__(self, on_close: Optional[Callable[[], None]] = None) -> None:
            self.closed = False
            self._on_close = on_close

        def __exit__(self, *_args: Any) -> None:
            self.closed = True
            if self._on_close is not None:
                self._on_close()

    init_ctx = _TrackedCtx()
    repl_ctx = _TrackedCtx(on_close=replacement_closed.set)
    spec = DeploymentSpec(alias="openai/gpt-4o", wire_model="gpt-4o", protocol="openai_chat", provider="openai")

    def _failing_iter(_entry: Any, _chunks: Any, _secrets: Any, _cancel: Any) -> Any:
        raise NativeConnectionError("pre-chunk drop", provider="openai")
        yield  # pragma: no cover

    def _slow_retry(_exc: Exception, _dep_id: str) -> Tuple[Any, Optional[Exception]]:
        retry_started.set()
        allow_retry_return.wait(timeout=5.0)
        return (spec, repl_ctx, None, iter([]), None, []), None

    wrapper = NativeStreamWrapper(
        entry=spec,
        ctx=init_ctx,
        resp=None,  # type: ignore[arg-type]
        byte_iter=iter([]),
        shared_transport_client=None,
        pooled_lease=None,
        pool=None,
        using_pool=False,
        iter_stream_fn=_failing_iter,
        secrets=[],
        deadline=None,
        clock=time.monotonic,
        cancel_check=None,
        on_pre_chunk_retry=_slow_retry,
    )

    def _consume() -> None:
        list(wrapper)

    t = threading.Thread(target=_consume)
    t.start()
    assert retry_started.wait(timeout=5.0)
    wrapper.close()
    allow_retry_return.set()
    t.join(timeout=5.0)
    assert init_ctx.closed is True
    assert repl_ctx.closed is True
    assert replacement_closed.is_set()

    # 2. P1-2: Close-aware BaseTransport MUST stay open across retries and close ONCE when call ends
    class _CloseAwareTransport(httpx.BaseTransport):
        def __init__(self, *, stream_mode: bool) -> None:
            self.stream_mode = stream_mode
            self.calls = 0
            self.close_count = 0
            self.is_closed = False

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            del request
            if self.is_closed:
                raise RuntimeError("Injected BaseTransport was prematurely closed before retry!")
            self.calls += 1
            if self.calls == 1:
                return httpx.Response(503, json={"error": {"message": "transient 503"}})
            if self.stream_mode:
                return httpx.Response(
                    200,
                    headers={"Content-Type": "text/event-stream"},
                    content=(
                        b'data: {"id":"s2","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"retry-stream-ok"},"finish_reason":"stop"}]}\n\n'
                        b"data: [DONE]\n\n"
                    ),
                )
            return httpx.Response(
                200,
                json={"id": "c2", "model": "gpt-4o", "choices": [{"index": 0, "message": {"role": "assistant", "content": "retry-ok"}, "finish_reason": "stop"}]},
            )

        def close(self) -> None:
            self.is_closed = True
            self.close_count += 1

    t_non_stream = _CloseAwareTransport(stream_mode=False)
    r_non_stream = NativeUnifiedRouter(
        model_list=[{"model_name": "openai/gpt-4o", "litellm_params": {"model": "openai/gpt-4o", "api_base": "https://relay.example/v1", "api_key": "sk-1"}}],
        http_transport=t_non_stream,
        num_retries=1,
        sleep_fn=lambda _s: None,
    )
    res_ns = r_non_stream.completion(model="openai/gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert res_ns.choices[0].message.content == "retry-ok"
    assert t_non_stream.calls == 2
    # F4: Per-call wrapper uses _NonClosingTransport so router-shared BaseTransport stays open for call 2!
    assert t_non_stream.close_count == 0
    res_ns2 = r_non_stream.completion(model="openai/gpt-4o", messages=[{"role": "user", "content": "hi2"}])
    assert res_ns2.choices[0].message.content == "retry-ok"
    assert t_non_stream.calls == 3
    assert t_non_stream.close_count == 0

    t_stream = _CloseAwareTransport(stream_mode=True)
    r_stream = NativeUnifiedRouter(
        model_list=[{"model_name": "openai/gpt-4o", "litellm_params": {"model": "openai/gpt-4o", "api_base": "https://relay.example/v1", "api_key": "sk-1"}}],
        http_transport=t_stream,
        num_retries=1,
        sleep_fn=lambda _s: None,
    )
    st = r_stream.completion(model="openai/gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True)
    assert "".join(c.choices[0].delta.content or "" for c in st) == "retry-stream-ok"
    assert t_stream.calls == 2
    assert t_stream.close_count == 0
    st2 = r_stream.completion(model="openai/gpt-4o", messages=[{"role": "user", "content": "hi2"}], stream=True)
    assert "".join(c.choices[0].delta.content or "" for c in st2) == "retry-stream-ok"
    assert t_stream.calls == 3
    assert t_stream.close_count == 0


def test_round2_p1_3_p1_4_p1_7c_bom_json_waf_403_exact_64k_text_plain_and_pct_secret() -> None:
    """Round 2 P1-3, P1-4, P1-7c: BOM JSON, HTML 403 w/ JSON MIME, exact 64 KiB error stop, text/plain JSON error, preamble timeout retry, percent-encoded query secret."""
    # 1. P1-3a: Valid BOM-prefixed JSON succeeds
    bom_payload = b'\xef\xbb\xbf{"id":"bom1","model":"gpt-4o","choices":[{"index":0,"message":{"role":"assistant","content":"bom-ok"},"finish_reason":"stop"}]}'
    tr_bom = NativeUnifiedTransport(
        http_transport=httpx.MockTransport(
            lambda _r: httpx.Response(200, headers={"Content-Type": "application/json"}, content=bom_payload)
        )
    )
    assert tr_bom.completion(
        model="openai/gpt-4o",
        api_base="https://relay.example/v1",
        api_key="sk-1",
        messages=[{"role": "user", "content": "hi"}],
    ).choices[0].message.content == "bom-ok"

    # 2. P1-3b: HTTP 403 WAF HTML mislabeled as application/json -> NativeProviderBlockedError (NOT NativeAuthenticationError!)
    tr_waf = NativeUnifiedTransport(
        http_transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                403,
                headers={"Content-Type": "application/json"},
                content=b"<!DOCTYPE html><html><body>Just a moment... Cloudflare</body></html>",
            )
        )
    )
    with pytest.raises(NativeProviderBlockedError):
        tr_waf.completion(
            model="openai/gpt-4o",
            api_base="https://relay.example/v1",
            api_key="sk-1",
            messages=[{"role": "user", "content": "hi"}],
        )

    # 3. P1-4a: Exact 65,536-byte error body stops immediately without reading trailing blocking chunk!
    class _Exact64KStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"E" * 65536
            raise httpx.ReadTimeout("Should NOT read past max_bytes=65536!")

    tr_64k = NativeUnifiedTransport(
        http_transport=httpx.MockTransport(
            lambda _r: httpx.Response(500, headers={"Content-Type": "text/plain"}, stream=_Exact64KStream())
        )
    )
    with pytest.raises(NativeAPIError) as exc_64k:
        tr_64k.completion(
            model="openai/gpt-4o",
            api_base="https://relay.example/v1",
            api_key="sk-1",
            messages=[{"role": "user", "content": "hi"}],
        )
    assert exc_64k.value.status_code == 500

    # 4. P1-4b: HTTP 200 text/plain JSON error classified cleanly as NativeRateLimitError
    tr_plain = NativeUnifiedTransport(
        http_transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                headers={"Content-Type": "text/plain"},
                content=b'{"error":{"code":429,"message":"rate limited over text/plain","type":"rate_limit_error"}}',
            )
        )
    )
    with pytest.raises(NativeRateLimitError):
        tr_plain.completion(
            model="openai/gpt-4o",
            api_base="https://relay.example/v1",
            api_key="sk-1",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )

    # 5. P1-4b: Timeout during stream-open HTML preamble read is retried cleanly on attempt 2!
    preamble_attempts = [0]

    class _TimeoutPreambleStream(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadTimeout("stalled HTML preamble")
            yield b""  # pragma: no cover

    def _preamble_handler(_r: httpx.Request) -> httpx.Response:
        preamble_attempts[0] += 1
        if preamble_attempts[0] == 1:
            return httpx.Response(200, headers={"Content-Type": "text/html"}, stream=_TimeoutPreambleStream())
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=(
                b'data: {"id":"p2","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"recovered"},"finish_reason":"stop"}]}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    r_preamble = NativeUnifiedRouter(
        model_list=[{"model_name": "openai/gpt-4o", "litellm_params": {"model": "openai/gpt-4o", "api_base": "https://relay.example/v1", "api_key": "sk-1"}}],
        http_transport=httpx.MockTransport(_preamble_handler),
        num_retries=1,
        sleep_fn=lambda _s: None,
    )
    st_pre = r_preamble.completion(model="openai/gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True)
    assert "".join(c.choices[0].delta.content or "" for c in st_pre) == "recovered"
    assert preamble_attempts[0] == 2

    # 6. P1-7c: Percent-encoded query key (?api%5Fkey=...) redacts BOTH raw and decoded secret values!
    raw_secret = "my%2Bsecret%2Ftoken99"
    decoded_secret = "my+secret/token99"
    tr_pct = NativeUnifiedTransport(
        http_transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                400,
                json={"error": {"message": f"bad raw={raw_secret} decoded={decoded_secret}"}},
            )
        )
    )
    with pytest.raises(NativeBadRequestError) as exc_pct:
        tr_pct.completion(
            model="gemini/gemini-2.5-flash",
            api_base=f"https://proxy.example/v1beta?api%5Fkey={raw_secret}",
            messages=[{"role": "user", "content": "hi"}],
        )
    assert raw_secret not in str(exc_pct.value)
    assert decoded_secret not in str(exc_pct.value)
    assert raw_secret not in str(exc_pct.value.body)
    assert decoded_secret not in str(exc_pct.value.body)


def test_round2_p1_6a_p1_7a_p1_8_p1_10_p2_recovery_ranker_proxy_and_system_config(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 2 P1-6a, P1-7a, P1-8, P1-10, P2: non-native recovery no-op, YAML max_tokens recovery, tuple/httpx Timeout deadline, ranker response_format suppression, proxy key, SystemConfigService error classification."""
    from types import SimpleNamespace
    from src.llm.errors import call_litellm_with_param_recovery
    from src.llm.native_engine import _current_proxy_env_key
    from src.llm.transport import LiteLLMTransport, use_transport
    from src.services.screening import ranker

    # 1. P1-6a: LiteLLMTransport.create_router strips _dsa_* and dsa_channel_protocol
    captured_ml: List[Dict[str, Any]] = []

    class _CaptureLitellmRouter:
        def __init__(self, model_list: List[Dict[str, Any]], **_kw: Any) -> None:
            captured_ml.extend(model_list)

    lt = LiteLLMTransport()
    monkeypatch.setattr(lt, "_load_litellm", lambda: SimpleNamespace(Router=_CaptureLitellmRouter))
    lt.create_router(
        [
            {
                "model_name": "openai/gpt-4o",
                "litellm_params": {
                    "model": "openai/gpt-4o",
                    "api_key": "sk-1",
                    "dsa_channel_protocol": "openai",
                    "_dsa_internal": True,
                },
            }
        ]
    )
    assert "dsa_channel_protocol" not in captured_ml[0]["litellm_params"]
    assert "_dsa_internal" not in captured_ml[0]["litellm_params"]

    # 2. P1-6a: Non-native RuntimeError does NOT retry when only native-only _dsa_* keys changed
    non_native_calls = [0]

    def _non_native_400(_kw: Dict[str, Any]) -> str:
        non_native_calls[0] += 1
        raise RuntimeError("Unsupported parameter: 'max_completion_tokens'. Use 'max_tokens' instead.")

    with pytest.raises(RuntimeError, match="max_completion_tokens"):
        call_litellm_with_param_recovery(
            _non_native_400,
            model="openai/gpt-5",
            call_kwargs={"model": "openai/gpt-5", "messages": [], "max_tokens": 64},
            cache_recovery=False,
        )
    assert non_native_calls[0] == 1

    # 3. P1-8: Deployment YAML max_tokens (NOT in caller kwargs) still recovers with _dsa_force_max_tokens=True on native 400!
    yaml_bodies: List[Dict[str, Any]] = []

    def _yaml_max_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        yaml_bodies.append(body)
        if "max_completion_tokens" in body:
            return httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'max_completion_tokens'. Use 'max_tokens'."}})
        return httpx.Response(200, json={"id": "c1", "model": "gpt-5", "choices": [{"index": 0, "message": {"role": "assistant", "content": "yaml-recovered"}, "finish_reason": "stop"}]})

    r_yaml_max = NativeUnifiedRouter(
        model_list=[
            {
                "model_name": "openai/gpt-5",
                "litellm_params": {"model": "openai/gpt-5", "api_base": "https://relay.example/v1", "api_key": "sk-1", "max_tokens": 256},
            }
        ],
        http_transport=httpx.MockTransport(_yaml_max_handler),
    )
    out_ymax = call_litellm_with_param_recovery(
        lambda kw: r_yaml_max.completion(**kw),
        model="openai/gpt-5",
        call_kwargs={"model": "openai/gpt-5", "messages": [{"role": "user", "content": "hi"}]},
        cache_recovery=False,
    )
    assert out_ymax.choices[0].message.content == "yaml-recovered"
    assert "max_completion_tokens" in yaml_bodies[0]
    assert yaml_bodies[1]["max_tokens"] == 256 and "max_completion_tokens" not in yaml_bodies[1]

    # 4. P1-8 & F9: Tuple and httpx.Timeout preserve per-phase bounds (including pool=0.0 and connect=0.2) while shrinking read under one monotonic deadline!
    for raw_t, initial_read in (((0.2, 1.0), 1.0), (httpx.Timeout(connect=0.2, read=1.0, write=0.3, pool=0.0), 1.0)):
        seen_t: List[Any] = []

        def _slow_rec(kw: Dict[str, Any]) -> str:
            seen_t.append(kw["timeout"])
            if len(seen_t) == 1:
                time.sleep(0.08)
                raise RuntimeError("Unsupported parameter: temperature is not supported")
            return "ok"

        assert call_litellm_with_param_recovery(
            _slow_rec,
            model="openai/gpt-4o",
            call_kwargs={"model": "openai/gpt-4o", "messages": [], "temperature": 0.5, "timeout": raw_t},
            cache_recovery=False,
        ) == "ok"
        assert len(seen_t) == 2
        assert seen_t[0] == raw_t
        if isinstance(raw_t, tuple):
            assert isinstance(seen_t[1], tuple)
            assert seen_t[1][0] == pytest.approx(0.2)
            assert seen_t[1][1] < initial_read - 0.03
        else:
            assert isinstance(seen_t[1], httpx.Timeout)
            assert seen_t[1].connect == pytest.approx(0.2)
            assert seen_t[1].write == pytest.approx(0.3)
            assert seen_t[1].pool == pytest.approx(0.0)
            assert seen_t[1].read is not None and seen_t[1].read < initial_read - 0.03

    # 5. P1-10: Ranker JSON-mode fallback retry suppresses inherited deployment YAML response_format!
    ranker_yaml = tmp_path / "ranker_rf.yaml"
    ranker_yaml.write_text(
        json.dumps(
            {
                "model_list": [
                    {
                        "model_name": "openai/rank-rf",
                        "litellm_params": {
                            "model": "openai/rank-rf",
                            "api_base": "https://relay.example/v1",
                            "api_key": "sk-rank",
                            "response_format": {"type": "json_object"},
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    ranker_bodies: List[Dict[str, Any]] = []

    def _ranker_rf_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        ranker_bodies.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format is not supported by this model"}})
        return httpx.Response(200, json={"id": "rk", "model": "rank-rf", "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"ranked":[]}'}, "finish_reason": "stop"}]})

    with use_transport(NativeUnifiedTransport(http_transport=httpx.MockTransport(_ranker_rf_handler))):
        out_rk = ranker._call_litellm_router(
            config_path=str(ranker_yaml),
            model_chain=["openai/rank-rf"],
            messages=[{"role": "user", "content": "rank"}],
            temperature=0.1,
            json_mode=True,
            timeout_sec=10.0,
        )
    assert out_rk == '{"ranked":[]}'
    assert len(ranker_bodies) == 2
    assert "response_format" in ranker_bodies[0]
    assert "response_format" not in ranker_bodies[1]

    # 6. P2: SystemConfigService classifies NativeConfigError BEFORE substring quota/timeout checks
    svc = SystemConfigService()
    assert svc._classify_llm_exception(NativeConfigError("quota config missing api_base")).error_code == "config_error"
    assert svc._classify_llm_exception(NativeConfigError("timeout config invalid")).error_code == "config_error"

    # 7. P2: Pooled client proxy key distinguishes ALL_PROXY vs all_proxy
    monkeypatch.setenv("ALL_PROXY", "http://upper.proxy:8080")
    monkeypatch.delenv("all_proxy", raising=False)
    k1 = _current_proxy_env_key()
    monkeypatch.setenv("all_proxy", "http://lower.proxy:8080")
    k2 = _current_proxy_env_key()
    assert k1 != k2

    # 8. P1-7a: Analyzer CLI -> HTTP fallback overrides CLI-seeded transport in audit_context
    for k in list(os.environ.keys()):
        if k.startswith(("LLM_", "LITELLM_", "OPENAI_", "GEMINI_", "ANTHROPIC_", "DEEPSEEK_")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_TRANSPORT_MODE", "native")
    monkeypatch.setenv("LLM_CHANNELS", "relay")
    monkeypatch.setenv("LLM_RELAY_PROTOCOL", "openai")
    monkeypatch.setenv("LLM_RELAY_BASE_URL", "https://relay.example/v1")
    monkeypatch.setenv("LLM_RELAY_API_KEY", "sk-fb-1234")
    monkeypatch.setenv("LLM_RELAY_MODELS", "gpt-4o")
    monkeypatch.setenv("LITELLM_MODEL", "openai/gpt-4o")
    Config.reset_instance()
    try:
        def _ok_fb(_r: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"id": "fb", "model": "gpt-4o", "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]})

        with use_transport(NativeUnifiedTransport(http_transport=httpx.MockTransport(_ok_fb))):
            from src.llm.backend_registry import CLAUDE_CODE_CLI_BACKEND_ID, LITELLM_BACKEND_ID
            from src.llm.generation_backend import GenerationError, GenerationErrorCode

            analyzer = GeminiAnalyzer()
            orig_get_backend = analyzer._get_generation_backend

            class _FailingCliBackend:
                def generate(self, *_a: Any, **_kw: Any) -> Any:
                    raise GenerationError(
                        error_code=GenerationErrorCode.UNKNOWN_BACKEND_ERROR,
                        stage="generate",
                        retryable=False,
                        fallbackable=True,
                        backend=CLAUDE_CODE_CLI_BACKEND_ID,
                        provider=CLAUDE_CODE_CLI_BACKEND_ID,
                    )

            audit_ctx: Dict[str, Any] = {"transport": CLAUDE_CODE_CLI_BACKEND_ID, "analysis_mode": "stock_analysis"}
            monkeypatch.setattr(analyzer, "get_generation_backend_config_error", lambda: None)
            monkeypatch.setattr(
                analyzer,
                "_resolve_generation_backend_config",
                lambda: (CLAUDE_CODE_CLI_BACKEND_ID, LITELLM_BACKEND_ID),
            )
            monkeypatch.setattr(
                analyzer,
                "_get_generation_backend",
                lambda bid=None: _FailingCliBackend() if bid == CLAUDE_CODE_CLI_BACKEND_ID else orig_get_backend(bid),
            )
            _txt, _m, usage = analyzer._call_litellm("Say OK", {"max_tokens": 16}, audit_context=audit_ctx)
            assert usage["transport"] == "native"
            assert audit_ctx["transport"] == CLAUDE_CODE_CLI_BACKEND_ID
    finally:
        Config.reset_instance()


def test_round3_f2_f3_f4_f5_f6_final_runtime_convergence() -> None:
    """Round 3 F2, F3, F4, F5, F6: originless client guard under header restriction, redirect Location query/fragment strip, close-during-backoff guard, extra_body _dsa_* strip, multi-chunk text/plain preamble."""
    from src.llm.transport import _strip_internal_litellm_kwargs

    # 1. F2: Originless caller_http MUST NOT be picked when restrict_caller_headers=True (caller origin A vs deployment origin B)
    dep_b_hits: List[str] = []
    originless_client = httpx.Client(
        headers={"Authorization": "Bearer sk-originless-client-default-secret"},
        transport=httpx.MockTransport(
            lambda _r: (_ for _ in ()).throw(AssertionError("Originless caller_http must NOT be used across origins!"))
        ),
    )
    dep_b_client = httpx.Client(
        base_url="https://origin-b.example/v1",
        transport=httpx.MockTransport(
            lambda r: (
                dep_b_hits.append(str(r.url)),
                httpx.Response(200, json={"id": "ok", "model": "gpt-4o", "choices": [{"index": 0, "message": {"role": "assistant", "content": "safe-b"}, "finish_reason": "stop"}]}),
            )[1]
        ),
    )
    try:
        r_f2 = NativeUnifiedRouter(
            model_list=[
                {
                    "model_name": "openai/gpt-4o",
                    "litellm_params": {"model": "openai/gpt-4o", "api_base": "https://origin-b.example/v1", "api_key": "sk-b", "client": dep_b_client},
                }
            ]
        )
        res_f2 = r_f2.completion(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            api_base="https://origin-a.example/v1",
            client=originless_client,
        )
        assert res_f2.choices[0].message.content == "safe-b"
        assert len(dep_b_hits) == 1
    finally:
        originless_client.close()
        dep_b_client.close()

    # 2. F3: HTTP 302 Location query/fragment stripped & redacted in unexpected_redirect errors (non-stream & stream)
    redir_secret_sig = "sig_top_secret_987654"
    redir_secret_tok = "tok_top_secret_123456"
    tr_redir = NativeUnifiedTransport(
        http_transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                302,
                headers={"Location": f"https://evil.example/cb?sig={redir_secret_sig}&access_token={redir_secret_tok}#frag_secret"},
            )
        )
    )
    for is_stream in (False, True):
        with pytest.raises(NativeBadRequestError) as exc_r:
            tr_redir.completion(
                model="openai/gpt-4o",
                api_base="https://relay.example/v1",
                api_key="sk-1",
                messages=[{"role": "user", "content": "hi"}],
                stream=is_stream,
            )
        assert exc_r.value.error_code == "unexpected_redirect"
        assert redir_secret_sig not in str(exc_r.value)
        assert redir_secret_tok not in str(exc_r.value)
        assert "frag_secret" not in str(exc_r.value)
        assert "https://evil.example/cb" in str(exc_r.value)

    # 3. F4: Closing stream DURING pre-chunk retry backoff prevents opening attempt 2!
    backoff_entered = threading.Event()
    allow_backoff_exit = threading.Event()
    http_attempts = [0]

    class _PreChunkDropStream(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadError("drop before first chunk")
            yield b""  # pragma: no cover

    def _backoff_handler(_r: httpx.Request) -> httpx.Response:
        http_attempts[0] += 1
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=_PreChunkDropStream())

    def _blocking_sleep(_sec: float) -> None:
        backoff_entered.set()
        allow_backoff_exit.wait(timeout=5.0)

    r_backoff = NativeUnifiedRouter(
        model_list=[
            {"model_name": "openai/gpt-4o", "litellm_params": {"model": "openai/gpt-4o", "api_base": "https://relay.example/v1", "api_key": "sk-1"}}
        ],
        http_transport=httpx.MockTransport(_backoff_handler),
        num_retries=2,
        sleep_fn=_blocking_sleep,
    )
    st_bo = r_backoff.completion(model="openai/gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True)
    t_bo = threading.Thread(target=lambda: list(st_bo))
    t_bo.start()
    assert backoff_entered.wait(timeout=5.0)
    st_bo.close()
    allow_backoff_exit.set()
    t_bo.join(timeout=5.0)
    assert http_attempts[0] == 1

    # 4. F5: _strip_internal_litellm_kwargs strips _dsa_* inside extra_body too
    stripped = _strip_internal_litellm_kwargs(
        {
            "model": "openai/gpt-4o",
            "_dsa_force_max_tokens": True,
            "extra_body": {"_dsa_leaked": 1, "dsa_channel_protocol": "openai", "reasoning": {"effort": "low"}},
        }
    )
    assert "_dsa_force_max_tokens" not in stripped
    assert stripped["extra_body"] == {"reasoning": {"effort": "low"}}

    # 5. F6: Multi-chunk text/plain stream preamble (whitespace-first JSON, split <ht + ml>, and normal text/plain SSE)
    class _ChunksStream(httpx.SyncByteStream):
        def __init__(self, chunks: List[bytes]) -> None:
            self._chunks = chunks

        def __iter__(self):
            yield from self._chunks

    tr_ws_json = NativeUnifiedTransport(
        http_transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                headers={"Content-Type": "text/plain"},
                stream=_ChunksStream([b"   \r\n", b'{"error":{"code":429,"message":"ws json rate limit","type":"rate_limit_error"}}']),
            )
        )
    )
    with pytest.raises(NativeRateLimitError):
        tr_ws_json.completion(
            model="openai/gpt-4o",
            api_base="https://relay.example/v1",
            api_key="sk-1",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )

    tr_split_html = NativeUnifiedTransport(
        http_transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                headers={"Content-Type": "text/plain"},
                stream=_ChunksStream([b" " * 600, b"<ht", b"ml><body><h1>Bad Gateway</h1></body></html>"]),
            )
        )
    )
    with pytest.raises(NativeBadRequestError) as exc_html:
        tr_split_html.completion(
            model="openai/gpt-4o",
            api_base="https://relay.example/v1",
            api_key="sk-1",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
    assert exc_html.value.error_code == "non_json_html"

    # F3 micro-fix: malformed Location authority fallback strips user:pass@ too
    from src.llm.native_engine import _sanitize_redirect_location

    sanitized_bad_auth = _sanitize_redirect_location("https://user:superpass@[bad-ipv6/cb?sig=999", [])
    assert "superpass" not in sanitized_bad_auth
    assert "sig=999" not in sanitized_bad_auth

    # F5 micro-fix: _sync_shared_pricing_to_transport writes to SDK only without re-writing _SHARED_MODEL_COSTS
    from types import SimpleNamespace
    from src.llm import transport as llm_transport_mod

    sdk_costs: Dict[str, Any] = {}
    lt_sync = llm_transport_mod.LiteLLMTransport()
    lt_sync._load_litellm = staticmethod(  # type: ignore[method-assign]
        lambda: SimpleNamespace(
            model_cost=sdk_costs,
            register_model=lambda m: sdk_costs.update(m),
        )
    )
    with llm_transport_mod._SHARED_MODEL_COSTS_LOCK:
        llm_transport_mod._SHARED_MODEL_COSTS["sync-race-model"] = {
            "input_cost_per_token": 0.002,
            "output_cost_per_token": 0.002,
        }
    try:
        llm_transport_mod._sync_shared_pricing_to_transport(
            lt_sync,
            {"sync-race-model": {"input_cost_per_token": 0.001, "output_cost_per_token": 0.001}},
        )
        assert sdk_costs["sync-race-model"]["input_cost_per_token"] == 0.002
        with llm_transport_mod._SHARED_MODEL_COSTS_LOCK:
            assert llm_transport_mod._SHARED_MODEL_COSTS["sync-race-model"]["input_cost_per_token"] == 0.002
    finally:
        with llm_transport_mod._SHARED_MODEL_COSTS_LOCK:
            llm_transport_mod._SHARED_MODEL_COSTS.pop("sync-race-model", None)

    tr_plain_sse = NativeUnifiedTransport(
        http_transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                headers={"Content-Type": "text/plain"},
                stream=_ChunksStream(
                    [
                        b'data: {"id":"s1","model":"gpt-4o","choices":[{"index":0,"delta":{"content":"plain-sse-ok"},"finish_reason":"stop"}]}\n\n',
                        b"data: [DONE]\n\n",
                    ]
                ),
            )
        )
    )
    plain_st = tr_plain_sse.completion(
        model="openai/gpt-4o",
        api_base="https://relay.example/v1",
        api_key="sk-1",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )
    assert "".join(c.choices[0].delta.content or "" for c in plain_st) == "plain-sse-ok"


# ============================================================
# Suite 10: Subprocess Zero-LiteLLM-Import Test in Native Mode + Exception Coverage
# ============================================================


def test_resolve_exception_types_covers_all_required_p8_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """P8: resolve_exception_types covers every exception name callers catch."""
    monkeypatch.setenv("LLM_TRANSPORT_MODE", "native")
    reset_transport_cache()
    try:
        for name in (
            "RateLimitError",
            "ContextWindowExceededError",
            "Timeout",
            "APIConnectionError",
            "ServiceUnavailableError",
            "AuthenticationError",
            "BadRequestError",
        ):
            classes = resolve_exception_types(name)
            assert classes, f"Empty exception tuple for {name}"
            assert all(issubclass(c, BaseException) for c in classes)
    finally:
        monkeypatch.delenv("LLM_TRANSPORT_MODE", raising=False)
        reset_transport_cache()


def test_native_mode_never_imports_litellm_in_subprocess() -> None:
    """Suite 10: executing all 4 native protocols in LLM_TRANSPORT_MODE=native NEVER imports litellm."""
    probe = r"""
import json, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        _ = self.rfile.read(n)
        if self.path.endswith("/chat/completions"):
            body = {"id":"c1","model":"gpt-4o","choices":[{"index":0,"message":{"role":"assistant","content":"ok-chat"},"finish_reason":"stop"}]}
        elif self.path.endswith("/responses"):
            body = {"id":"r1","model":"gpt-5","status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"ok-resp"}]}]}
        elif self.path.endswith("/v1/messages"):
            body = {"id":"m1","role":"assistant","model":"claude-sonnet-4-6","content":[{"type":"text","text":"ok-anth"}],"stop_reason":"end_turn"}
        else:
            body = {"responseId":"g1","modelVersion":"gemini-2.5-flash","candidates":[{"index":0,"content":{"parts":[{"text":"ok-gem"}]},"finishReason":"STOP"}]}
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
t = threading.Thread(target=srv.serve_forever, daemon=True)
t.start()
try:
    from src.llm.transport import dispatch_completion, get_model_providers, estimate_tokens
    assert "litellm" not in sys.modules
    assert "openai" in get_model_providers()
    assert estimate_tokens("贵州茅台") >= 6
    base = f"http://127.0.0.1:{port}"
    r1 = dispatch_completion(model="openai/gpt-4o", api_base=f"{base}/v1", api_key="sk-1", messages=[{"role":"user","content":"hi"}])
    r2 = dispatch_completion(model="openai/responses/gpt-5", api_base=f"{base}/v1", api_key="sk-1", messages=[{"role":"user","content":"hi"}])
    r3 = dispatch_completion(model="anthropic/claude-sonnet-4-6", api_base=base, api_key="sk-ant-1", messages=[{"role":"user","content":"hi"}])
    r4 = dispatch_completion(model="gemini/gemini-2.5-flash", api_base=f"{base}/v1beta", api_key="AIza1", messages=[{"role":"user","content":"hi"}])
    assert r1.choices[0].message.content == "ok-chat"
    assert r2.choices[0].message.content == "ok-resp"
    assert r3.choices[0].message.content == "ok-anth"
    assert r4.choices[0].message.content == "ok-gem"
    assert "litellm" not in sys.modules, f"litellm was imported in native mode: {[k for k in sys.modules if 'litellm' in k]}"
finally:
    srv.shutdown()
    srv.server_close()
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["LLM_TRANSPORT_MODE"] = "native"
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}\nstdout={proc.stdout}"
