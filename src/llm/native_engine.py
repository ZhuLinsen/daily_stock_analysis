# -*- coding: utf-8 -*-
"""Pooled HTTPX execution and streaming engine for the native 4-protocol LLM transport.

Implements invariants P3-P7:
- P3: Total attempt budget capped at ``1 + num_retries``; 400/413/422/404 and HTTP 200 HTML
  fail fast; 401/non-WAF 403 exclude key; WAF 403 & model-disabled 403 do NOT poison auth.
- P4: Single monotonic deadline per logical call (respecting stock cancellation deadline),
  with per-attempt remaining-time timeout and cancellation checks inside SSE chunk loop.
- P5: Closeable ``NativeStreamWrapper`` releasing HTTP resources even if never iterated,
  ``try/finally`` cleanup around ``resp.read()``, no post-first-chunk failover, and
  mandatory terminal-marker verification before ``mark_success``.
- P6: Shared pooled ``httpx.Client`` per proxy/TLS policy closed on ``reset_transport_cache()``,
  while honoring injected caller/deployment clients (e.g. Hermes no-proxy).
- P7: Full secret redaction in message, body, and warning logs; typed ``NativeTimeoutError``
  and ``NativeConnectionError``; support for float/tuple/``httpx.Timeout`` values.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

import httpx

from src.core.stock_execution_context import get_current_stock_cancellation
from src.llm.native_pool import DeploymentPool, parse_retry_after
from src.llm.native_types import (
    DeploymentSpec,
    NativeAPIError,
    NativeAuthenticationError,
    NativeBadRequestError,
    NativeCompletionResponse,
    NativeConnectionError,
    NativeContentFilterError,
    NativeContextWindowExceededError,
    NativeIncompleteStreamError,
    NativeNotFoundError,
    NativeProviderBlockedError,
    NativeStreamChunk,
    NativeTimeoutError,
    PreparedRequest,
    check_http_200_html_response,
    classify_http_error,
    collect_secret_values,
    sanitize_error_message,
)

logger = logging.getLogger(__name__)

# ============================================================
# P6: Pooled httpx.Client Lifecycle Management
# ============================================================

_POOLED_CLIENTS_LOCK = threading.Lock()
_POOLED_CLIENTS: Dict[Tuple[bool, str, str, str, str], httpx.Client] = {}


def _current_proxy_env_key() -> Tuple[str, str, str, str]:
    """Snapshot env vars affecting ``httpx.Client(trust_env=True)`` proxy/TLS routing."""
    return (
        os.getenv("HTTP_PROXY", "") or os.getenv("http_proxy", ""),
        os.getenv("HTTPS_PROXY", "") or os.getenv("https_proxy", ""),
        os.getenv("NO_PROXY", "") or os.getenv("no_proxy", ""),
        os.getenv("SSL_CERT_FILE", "") or os.getenv("SSL_CERT_DIR", ""),
    )


def get_pooled_httpx_client(*, trust_env: bool = True) -> httpx.Client:
    """Return a shared pooled ``httpx.Client`` for the current proxy/TLS environment."""
    env_key = _current_proxy_env_key() if trust_env else ("", "", "", "")
    cache_key = (bool(trust_env), *env_key)
    with _POOLED_CLIENTS_LOCK:
        client = _POOLED_CLIENTS.get(cache_key)
        if client is not None and not client.is_closed:
            return client
        client = httpx.Client(
            trust_env=trust_env,
            follow_redirects=False,
        )
        _POOLED_CLIENTS[cache_key] = client
        return client


def close_pooled_clients() -> None:
    """Close and discard all cached pooled ``httpx.Client`` instances."""
    with _POOLED_CLIENTS_LOCK:
        clients = list(_POOLED_CLIENTS.values())
        _POOLED_CLIENTS.clear()
    for client in clients:
        try:
            client.close()
        except Exception:
            pass


# ============================================================
# P4: Timeout Normalization & Single Monotonic Deadline
# ============================================================


def normalize_timeout_seconds(raw_timeout: Any, default_seconds: float = 120.0) -> Optional[float]:
    """Extract a positive finite overall timeout in seconds from float, tuple, or ``httpx.Timeout``."""
    if raw_timeout is None or raw_timeout == "":
        return float(default_seconds)
    if isinstance(raw_timeout, httpx.Timeout):
        candidates = [
            v
            for v in (raw_timeout.read, raw_timeout.connect, raw_timeout.write, raw_timeout.pool)
            if isinstance(v, (int, float)) and math.isfinite(v) and v > 0
        ]
        if not candidates:
            return None
        return float(max(candidates))
    if isinstance(raw_timeout, (tuple, list)):
        candidates = [
            float(v)
            for v in raw_timeout
            if isinstance(v, (int, float)) and math.isfinite(float(v)) and float(v) > 0
        ]
        if not candidates:
            return float(default_seconds)
        return float(max(candidates))
    try:
        parsed = float(raw_timeout)
    except (TypeError, ValueError):
        return float(default_seconds)
    if not math.isfinite(parsed) or parsed <= 0:
        return float(default_seconds)
    return parsed


def build_attempt_httpx_timeout(raw_timeout: Any, remaining_seconds: Optional[float]) -> httpx.Timeout:
    """Build an ``httpx.Timeout`` capped by ``remaining_seconds`` while preserving granular values."""
    if isinstance(raw_timeout, httpx.Timeout):
        def _cap(val: Optional[float]) -> Optional[float]:
            if val is None:
                return remaining_seconds
            if remaining_seconds is None:
                return val
            return min(val, remaining_seconds)

        return httpx.Timeout(
            connect=_cap(raw_timeout.connect),
            read=_cap(raw_timeout.read),
            write=_cap(raw_timeout.write),
            pool=_cap(raw_timeout.pool),
        )
    if isinstance(raw_timeout, (tuple, list)) and len(raw_timeout) >= 2:
        try:
            connect_t = float(raw_timeout[0])
            read_t = float(raw_timeout[1])
            if remaining_seconds is not None:
                connect_t = min(connect_t, remaining_seconds)
                read_t = min(read_t, remaining_seconds)
            return httpx.Timeout(connect=connect_t, read=read_t, write=read_t, pool=connect_t)
        except (TypeError, ValueError):
            pass
    effective = remaining_seconds if remaining_seconds is not None else 120.0
    return httpx.Timeout(max(0.001, float(effective)))


def _compute_call_deadline(
    *,
    raw_timeout: Any,
    default_timeout: float,
    clock: Callable[[], float],
) -> Optional[float]:
    """Compute one monotonic deadline per logical call (min of timeout and stock cancellation)."""
    req_seconds = normalize_timeout_seconds(raw_timeout, default_seconds=default_timeout)
    token = get_current_stock_cancellation()
    stock_remaining = token.remaining_seconds() if token is not None else None
    effective: Optional[float] = req_seconds
    if stock_remaining is not None:
        if effective is None:
            effective = float(stock_remaining)
        else:
            effective = min(effective, float(stock_remaining))
    if effective is None:
        return None
    return clock() + effective


def _remaining_before_deadline(
    deadline: Optional[float],
    *,
    clock: Callable[[], float],
    provider: str,
    secrets: Iterable[str] = (),
) -> Optional[float]:
    if deadline is None:
        return None
    remaining = deadline - clock()
    if remaining <= 0:
        raise NativeTimeoutError(
            "LLM request timed out before attempt (call deadline exceeded)",
            provider=provider,
            secrets=secrets,
        )
    return remaining


def _is_fail_fast_error(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            NativeBadRequestError,
            NativeContextWindowExceededError,
            NativeNotFoundError,
            NativeContentFilterError,
        ),
    )


def _select_next_candidate(
    *,
    attempt_idx: int,
    candidates: List[DeploymentSpec],
    pool: Optional[DeploymentPool],
    using_pool: bool,
    request_model: str,
    bad_auth_ids: set[str],
    tried_ids_this_call: List[str],
) -> Optional[DeploymentSpec]:
    """Choose the next candidate respecting pool cooldowns and excluded bad-auth deployments."""
    if using_pool and pool is not None:
        available = pool.select_candidates(request_model, exclude_ids=bad_auth_ids)
        if not available:
            return None
        # Prefer an untried healthy candidate before repeating a deployment.
        for dep in available:
            if dep.deployment_id not in tried_ids_this_call:
                return dep
        return available[0]

    filtered = [dep for dep in candidates if dep.deployment_id not in bad_auth_ids]
    if not filtered:
        return None
    return filtered[attempt_idx % len(filtered)]


def _entry_secrets(entry: DeploymentSpec, kwargs: Mapping[str, Any]) -> List[str]:
    merged_headers: Dict[str, Any] = dict(entry.extra_headers)
    for key in ("extra_headers", "headers", "default_headers"):
        raw = kwargs.get(key)
        if isinstance(raw, Mapping):
            merged_headers.update(raw)
    return collect_secret_values(entry.api_key, kwargs.get("api_key"), headers=merged_headers)


# ============================================================
# Non-Streaming Pooled Execution
# ============================================================


def execute_pooled_completion(
    *,
    candidates: List[DeploymentSpec],
    pool: Optional[DeploymentPool],
    using_pool: bool,
    messages: List[Dict[str, Any]],
    kwargs: Mapping[str, Any],
    prepare_request_fn: Callable[[DeploymentSpec, List[Dict[str, Any]], bool, Mapping[str, Any]], PreparedRequest],
    parse_response_fn: Callable[[DeploymentSpec, Mapping[str, Any], Iterable[str]], NativeCompletionResponse],
    http_transport: Optional[httpx.BaseTransport] = None,
    http_client: Optional[httpx.Client] = None,
    request_model: str = "",
    num_retries: int = 0,
    default_timeout: float = 120.0,
    clock: Callable[[], float] = time.monotonic,
    now_wall: Optional[Callable[[], float]] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> NativeCompletionResponse:
    """Execute non-streaming completion capped at ``1 + num_retries`` total attempts."""
    max_attempts = 1 + max(0, int(num_retries))
    effective_sleep = sleep_fn if sleep_fn is not None else time.sleep
    bad_auth_ids: set[str] = set()
    tried_ids: List[str] = []
    last_error: Optional[Exception] = None

    raw_timeout = kwargs.get("timeout")
    if raw_timeout is None and candidates and candidates[0].timeout is not None:
        raw_timeout = candidates[0].timeout
    deadline = _compute_call_deadline(
        raw_timeout=raw_timeout,
        default_timeout=default_timeout,
        clock=clock,
    )

    # Acquire client strategy (P6): caller client > mock/custom transport > shared pool.
    owned_transport_client: Optional[httpx.Client] = None
    if http_client is not None and http_transport is None:
        active_client = http_client
    elif http_transport is not None:
        owned_transport_client = httpx.Client(transport=http_transport, follow_redirects=False)
        active_client = owned_transport_client
    else:
        active_client = get_pooled_httpx_client(trust_env=True)

    try:
        for attempt_idx in range(max_attempts):
            if cancel_check is not None:
                cancel_check()

            entry = _select_next_candidate(
                attempt_idx=attempt_idx,
                candidates=candidates,
                pool=pool,
                using_pool=using_pool,
                request_model=request_model,
                bad_auth_ids=bad_auth_ids,
                tried_ids_this_call=tried_ids,
            )
            if entry is None:
                break

            secrets = _entry_secrets(entry, kwargs)
            remaining = _remaining_before_deadline(
                deadline,
                clock=clock,
                provider=entry.provider,
                secrets=secrets,
            )

            # Backoff only when retrying an already-tried deployment or after previous attempt.
            if attempt_idx > 0 and entry.deployment_id in tried_ids:
                backoff = min(0.25 * attempt_idx, 1.0)
                if remaining is not None:
                    backoff = min(backoff, max(0.0, remaining))
                if backoff > 0:
                    effective_sleep(backoff)
                    if cancel_check is not None:
                        cancel_check()
                    remaining = _remaining_before_deadline(
                        deadline,
                        clock=clock,
                        provider=entry.provider,
                        secrets=secrets,
                    )

            tried_ids.append(entry.deployment_id)
            url, headers, payload, prepared_timeout = prepare_request_fn(entry, messages, False, kwargs)
            attempt_timeout = build_attempt_httpx_timeout(
                raw_timeout if raw_timeout is not None else prepared_timeout,
                remaining,
            )

            try:
                resp = active_client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=attempt_timeout,
                )

                if resp.status_code >= 400:
                    err = classify_http_error(
                        resp.status_code,
                        resp.text,
                        provider=entry.provider,
                        secrets=secrets,
                        headers=resp.headers,
                        url=url,
                    )
                    if _is_fail_fast_error(err):
                        raise err
                    if isinstance(err, NativeAuthenticationError):
                        bad_auth_ids.add(entry.deployment_id)
                    if using_pool and pool is not None:
                        retry_after = parse_retry_after(
                            resp.headers.get("retry-after"),
                            now_wall=now_wall,
                        )
                        pool.mark_failure(
                            entry.deployment_id,
                            status_code=resp.status_code,
                            retry_after=retry_after,
                        )
                    last_error = err
                    continue

                content_type = resp.headers.get("content-type", "")
                body_text = resp.text
                check_http_200_html_response(
                    resp.status_code,
                    content_type,
                    body_text,
                    provider=entry.provider,
                    secrets=secrets,
                )

                try:
                    data = resp.json()
                except ValueError as json_exc:
                    raise NativeBadRequestError(
                        f"Endpoint returned non-JSON response (Content-Type: {content_type or 'unknown'}); "
                        "check Base URL /v1.",
                        status_code=resp.status_code,
                        provider=entry.provider,
                        body=body_text[:512],
                        secrets=secrets,
                        error_code="non_json_response",
                    ) from json_exc

                if not isinstance(data, Mapping):
                    raise NativeBadRequestError(
                        "Unexpected non-object JSON response from LLM endpoint",
                        status_code=resp.status_code,
                        provider=entry.provider,
                        body=str(data)[:512],
                        secrets=secrets,
                    )

                parsed = parse_response_fn(entry, data, secrets)
                parsed._hidden_params["deployment_id"] = entry.deployment_id
                parsed._hidden_params["protocol"] = entry.protocol
                parsed._hidden_params["transport_engine"] = "native"
                if using_pool and pool is not None:
                    pool.mark_success(entry.deployment_id)
                return parsed

            except (
                NativeBadRequestError,
                NativeContextWindowExceededError,
                NativeNotFoundError,
                NativeContentFilterError,
            ):
                raise
            except httpx.TimeoutException as exc:
                sanitized = sanitize_error_message(exc, secrets)
                logger.warning(
                    "[NativeLLM] Deployment %s timed out: %s",
                    entry.deployment_id,
                    sanitized,
                )
                if using_pool and pool is not None:
                    pool.mark_failure(entry.deployment_id, status_code=408)
                last_error = NativeTimeoutError(
                    sanitized or f"{type(exc).__name__}: request timed out",
                    provider=entry.provider,
                    secrets=secrets,
                )
            except httpx.TransportError as exc:
                sanitized = sanitize_error_message(exc, secrets)
                logger.warning(
                    "[NativeLLM] Deployment %s transport error: %s",
                    entry.deployment_id,
                    sanitized,
                )
                if using_pool and pool is not None:
                    pool.mark_failure(entry.deployment_id)
                last_error = NativeConnectionError(
                    sanitized or f"{type(exc).__name__}: transport error",
                    provider=entry.provider,
                    secrets=secrets,
                )
            except NativeProviderBlockedError as exc:
                # WAF 403 / model-disabled 403: do NOT add to bad_auth_ids!
                if using_pool and pool is not None:
                    pool.mark_failure(entry.deployment_id, status_code=exc.status_code)
                last_error = exc
            except NativeAPIError as exc:
                if isinstance(exc, NativeAuthenticationError):
                    bad_auth_ids.add(entry.deployment_id)
                if using_pool and pool is not None:
                    pool.mark_failure(entry.deployment_id, status_code=exc.status_code)
                last_error = exc

        if last_error is not None:
            raise last_error
        raise NativeAPIError(
            f"No available deployments configured for {request_model or 'request'}",
            provider=candidates[0].provider if candidates else "openai",
        )
    finally:
        if owned_transport_client is not None:
            try:
                owned_transport_client.close()
            except Exception:
                pass


# ============================================================
# P5: Streaming Execution with Strict Resource Ownership
# ============================================================


class NativeStreamWrapper:
    """Closeable stream wrapper guaranteeing connection release even if never iterated."""

    transport_engine: str = "native"

    def __init__(
        self,
        *,
        entry: DeploymentSpec,
        ctx: Any,
        resp: httpx.Response,
        owned_client: Optional[httpx.Client],
        pool: Optional[DeploymentPool],
        using_pool: bool,
        iter_stream_fn: Callable[[DeploymentSpec, Iterable[bytes], Iterable[str], Callable[[], None]], Iterator[NativeStreamChunk]],
        secrets: List[str],
        deadline: Optional[float],
        clock: Callable[[], float],
        cancel_check: Optional[Callable[[], None]],
        on_pre_chunk_retry: Callable[[Exception, str], Optional[Tuple[DeploymentSpec, Any, httpx.Response, Optional[httpx.Client], List[str]]]],
    ) -> None:
        self._entry = entry
        self._ctx = ctx
        self._resp = resp
        self._owned_client = owned_client
        self._pool = pool
        self._using_pool = using_pool
        self._iter_stream_fn = iter_stream_fn
        self._secrets = secrets
        self._deadline = deadline
        self._clock = clock
        self._cancel_check = cancel_check
        self._on_pre_chunk_retry = on_pre_chunk_retry
        self._closed = False
        self._iterator: Optional[Iterator[NativeStreamChunk]] = None

    def _close_active_connection(self) -> None:
        ctx = self._ctx
        self._ctx = None
        self._resp = None  # type: ignore[assignment]
        if ctx is not None:
            try:
                ctx.__exit__(None, None, None)
            except Exception:
                pass
        owned = self._owned_client
        self._owned_client = None
        if owned is not None:
            try:
                owned.close()
            except Exception:
                pass

    def close(self) -> None:
        """Close the active HTTP stream and owned client immediately."""
        if self._closed:
            return
        self._closed = True
        self._close_active_connection()

    def __enter__(self) -> "NativeStreamWrapper":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __iter__(self) -> "NativeStreamWrapper":
        if self._iterator is None:
            self._iterator = self._stream_loop()
        return self

    def __next__(self) -> NativeStreamChunk:
        if self._iterator is None:
            self._iterator = self._stream_loop()
        return next(self._iterator)

    def _check_deadline_and_cancel(self) -> None:
        if self._cancel_check is not None:
            self._cancel_check()
        _remaining_before_deadline(
            self._deadline,
            clock=self._clock,
            provider=self._entry.provider,
            secrets=self._secrets,
        )

    def _stream_loop(self) -> Iterator[NativeStreamChunk]:
        emitted_any = False
        try:
            while not self._closed:
                try:
                    self._check_deadline_and_cancel()
                    if self._resp is None:
                        return
                    for chunk in self._iter_stream_fn(
                        self._entry,
                        self._resp.iter_bytes(),
                        self._secrets,
                        self._check_deadline_and_cancel,
                    ):
                        if self._closed:
                            return
                        chunk._hidden_params["deployment_id"] = self._entry.deployment_id
                        chunk._hidden_params["protocol"] = self._entry.protocol
                        chunk._hidden_params["transport_engine"] = "native"
                        emitted_any = True
                        yield chunk

                    if not emitted_any:
                        raise NativeIncompleteStreamError(
                            "SSE stream closed without yielding any chunks",
                            provider=self._entry.provider,
                            secrets=self._secrets,
                            error_code="incomplete_stream",
                        )

                    if self._using_pool and self._pool is not None:
                        self._pool.mark_success(self._entry.deployment_id)
                    return

                except (
                    NativeBadRequestError,
                    NativeContextWindowExceededError,
                    NativeNotFoundError,
                    NativeContentFilterError,
                ):
                    raise
                except (
                    httpx.TimeoutException,
                    httpx.TransportError,
                    NativeAPIError,
                ) as exc:
                    sanitized = sanitize_error_message(exc, self._secrets)
                    if isinstance(exc, httpx.TimeoutException):
                        wrapped: NativeAPIError = NativeTimeoutError(
                            sanitized or "Stream timed out",
                            provider=self._entry.provider,
                            secrets=self._secrets,
                        )
                    elif isinstance(exc, httpx.TransportError):
                        wrapped = NativeConnectionError(
                            sanitized or "Stream transport error",
                            provider=self._entry.provider,
                            secrets=self._secrets,
                        )
                    else:
                        wrapped = exc

                    if self._using_pool and self._pool is not None:
                        self._pool.mark_failure(
                            self._entry.deployment_id,
                            status_code=wrapped.status_code,
                        )

                    self._close_active_connection()

                    if emitted_any or self._closed:
                        # P5: No failover after the first chunk has been emitted.
                        raise wrapped from exc

                    next_conn = self._on_pre_chunk_retry(wrapped, self._entry.deployment_id)
                    if next_conn is None:
                        raise wrapped from exc
                    self._entry, self._ctx, self._resp, self._owned_client, self._secrets = next_conn
                    continue
        finally:
            self.close()


def _open_stream_attempt(
    *,
    entry: DeploymentSpec,
    pool: Optional[DeploymentPool],
    using_pool: bool,
    messages: List[Dict[str, Any]],
    kwargs: Mapping[str, Any],
    prepare_request_fn: Callable[[DeploymentSpec, List[Dict[str, Any]], bool, Mapping[str, Any]], PreparedRequest],
    http_transport: Optional[httpx.BaseTransport],
    http_client: Optional[httpx.Client],
    raw_timeout: Any,
    remaining: Optional[float],
    bad_auth_ids: set[str],
    now_wall: Optional[Callable[[], float]],
) -> Tuple[Optional[Tuple[Any, httpx.Response, Optional[httpx.Client], List[str]]], Optional[Exception]]:
    """Open a single SSE stream attempt, ensuring cleanup on error (including ``resp.read()`` errors)."""
    secrets = _entry_secrets(entry, kwargs)
    url, headers, payload, prepared_timeout = prepare_request_fn(entry, messages, True, kwargs)
    attempt_timeout = build_attempt_httpx_timeout(
        raw_timeout if raw_timeout is not None else prepared_timeout,
        remaining,
    )

    owned_client: Optional[httpx.Client] = None
    if http_client is not None and http_transport is None:
        client = http_client
    elif http_transport is not None:
        owned_client = httpx.Client(transport=http_transport, follow_redirects=False)
        client = owned_client
    else:
        client = get_pooled_httpx_client(trust_env=True)

    ctx: Any = None
    try:
        ctx = client.stream("POST", url, headers=headers, json=payload, timeout=attempt_timeout)
        resp = ctx.__enter__()
    except httpx.TimeoutException as exc:
        if owned_client is not None:
            owned_client.close()
        sanitized = sanitize_error_message(exc, secrets)
        if using_pool and pool is not None:
            pool.mark_failure(entry.deployment_id, status_code=408)
        return None, NativeTimeoutError(
            sanitized or "Stream connection timed out",
            provider=entry.provider,
            secrets=secrets,
        )
    except httpx.TransportError as exc:
        if owned_client is not None:
            owned_client.close()
        sanitized = sanitize_error_message(exc, secrets)
        if using_pool and pool is not None:
            pool.mark_failure(entry.deployment_id)
        return None, NativeConnectionError(
            sanitized or "Stream connection error",
            provider=entry.provider,
            secrets=secrets,
        )

    # Handle HTTP >=400 with try/finally cleanup around resp.read() (P5).
    if resp.status_code >= 400:
        try:
            body_text = resp.read().decode("utf-8", errors="replace")
            retry_after = parse_retry_after(resp.headers.get("retry-after"), now_wall=now_wall)
            resp_headers = resp.headers
        except httpx.TimeoutException as exc:
            sanitized = sanitize_error_message(exc, secrets)
            if using_pool and pool is not None:
                pool.mark_failure(entry.deployment_id, status_code=408)
            return None, NativeTimeoutError(sanitized or "Error body read timed out", provider=entry.provider, secrets=secrets)
        except httpx.TransportError as exc:
            sanitized = sanitize_error_message(exc, secrets)
            if using_pool and pool is not None:
                pool.mark_failure(entry.deployment_id)
            return None, NativeConnectionError(sanitized or "Error body read failed", provider=entry.provider, secrets=secrets)
        finally:
            try:
                ctx.__exit__(None, None, None)
            except Exception:
                pass
            if owned_client is not None:
                try:
                    owned_client.close()
                except Exception:
                    pass

        err = classify_http_error(
            resp.status_code,
            body_text,
            provider=entry.provider,
            secrets=secrets,
            headers=resp_headers,
            url=url,
        )
        if _is_fail_fast_error(err):
            raise err
        if isinstance(err, NativeAuthenticationError):
            bad_auth_ids.add(entry.deployment_id)
        if using_pool and pool is not None:
            pool.mark_failure(
                entry.deployment_id,
                status_code=resp.status_code,
                retry_after=retry_after,
            )
        return None, err

    # Fail fast on HTTP 200 HTML response (e.g. missing /v1 returning landing page).
    content_type = resp.headers.get("content-type", "")
    if "text/html" in content_type.lower() or "application/xhtml" in content_type.lower():
        try:
            html_body = resp.read().decode("utf-8", errors="replace")
        finally:
            try:
                ctx.__exit__(None, None, None)
            except Exception:
                pass
            if owned_client is not None:
                try:
                    owned_client.close()
                except Exception:
                    pass
        check_http_200_html_response(
            resp.status_code,
            content_type,
            html_body,
            provider=entry.provider,
            secrets=secrets,
        )

    return (ctx, resp, owned_client, secrets), None


def stream_pooled_completion(
    *,
    candidates: List[DeploymentSpec],
    pool: Optional[DeploymentPool],
    using_pool: bool,
    messages: List[Dict[str, Any]],
    kwargs: Mapping[str, Any],
    prepare_request_fn: Callable[[DeploymentSpec, List[Dict[str, Any]], bool, Mapping[str, Any]], PreparedRequest],
    iter_stream_fn: Callable[[DeploymentSpec, Iterable[bytes], Iterable[str], Callable[[], None]], Iterator[NativeStreamChunk]],
    http_transport: Optional[httpx.BaseTransport] = None,
    http_client: Optional[httpx.Client] = None,
    request_model: str = "",
    num_retries: int = 0,
    default_timeout: float = 120.0,
    clock: Callable[[], float] = time.monotonic,
    now_wall: Optional[Callable[[], float]] = None,
    sleep_fn: Optional[Callable[[float], None]] = None,
    cancel_check: Optional[Callable[[], None]] = None,
) -> NativeStreamWrapper:
    """Open a closeable SSE stream with bounded ``1 + num_retries`` pre-first-chunk failover."""
    max_attempts = 1 + max(0, int(num_retries))
    effective_sleep = sleep_fn if sleep_fn is not None else time.sleep
    bad_auth_ids: set[str] = set()
    tried_ids: List[str] = []
    attempts_used = 0

    raw_timeout = kwargs.get("timeout")
    if raw_timeout is None and candidates and candidates[0].timeout is not None:
        raw_timeout = candidates[0].timeout
    deadline = _compute_call_deadline(
        raw_timeout=raw_timeout,
        default_timeout=default_timeout,
        clock=clock,
    )

    def _open_next(
        prior_error: Optional[Exception] = None,
    ) -> Tuple[Optional[Tuple[DeploymentSpec, Any, httpx.Response, Optional[httpx.Client], List[str]]], Optional[Exception]]:
        nonlocal attempts_used
        last_err = prior_error
        while attempts_used < max_attempts:
            if cancel_check is not None:
                cancel_check()

            entry = _select_next_candidate(
                attempt_idx=attempts_used,
                candidates=candidates,
                pool=pool,
                using_pool=using_pool,
                request_model=request_model,
                bad_auth_ids=bad_auth_ids,
                tried_ids_this_call=tried_ids,
            )
            if entry is None:
                break

            secrets = _entry_secrets(entry, kwargs)
            remaining = _remaining_before_deadline(
                deadline,
                clock=clock,
                provider=entry.provider,
                secrets=secrets,
            )

            if attempts_used > 0 and entry.deployment_id in tried_ids:
                backoff = min(0.25 * attempts_used, 1.0)
                if remaining is not None:
                    backoff = min(backoff, max(0.0, remaining))
                if backoff > 0:
                    effective_sleep(backoff)
                    if cancel_check is not None:
                        cancel_check()
                    remaining = _remaining_before_deadline(
                        deadline,
                        clock=clock,
                        provider=entry.provider,
                        secrets=secrets,
                    )

            attempts_used += 1
            tried_ids.append(entry.deployment_id)
            opened, err = _open_stream_attempt(
                entry=entry,
                pool=pool,
                using_pool=using_pool,
                messages=messages,
                kwargs=kwargs,
                prepare_request_fn=prepare_request_fn,
                http_transport=http_transport,
                http_client=http_client,
                raw_timeout=raw_timeout,
                remaining=remaining,
                bad_auth_ids=bad_auth_ids,
                now_wall=now_wall,
            )
            if opened is not None:
                ctx, resp, owned_client, opened_secrets = opened
                return (entry, ctx, resp, owned_client, opened_secrets), None
            last_err = err

        return None, last_err

    first_conn, first_err = _open_next()
    if first_conn is None:
        if first_err is not None:
            raise first_err
        raise NativeAPIError(
            f"No healthy deployments available for {request_model or 'stream'}",
            provider=candidates[0].provider if candidates else "openai",
        )

    entry0, ctx0, resp0, owned0, secrets0 = first_conn

    def _retry_pre_chunk(
        exc: Exception,
        failed_deployment_id: str,
    ) -> Optional[Tuple[DeploymentSpec, Any, httpx.Response, Optional[httpx.Client], List[str]]]:
        if isinstance(exc, NativeAuthenticationError):
            bad_auth_ids.add(failed_deployment_id)
        conn, _next_err = _open_next(prior_error=exc)
        return conn

    return NativeStreamWrapper(
        entry=entry0,
        ctx=ctx0,
        resp=resp0,
        owned_client=owned0,
        pool=pool,
        using_pool=using_pool,
        iter_stream_fn=iter_stream_fn,
        secrets=secrets0,
        deadline=deadline,
        clock=clock,
        cancel_check=cancel_check,
        on_pre_chunk_retry=_retry_pre_chunk,
    )
