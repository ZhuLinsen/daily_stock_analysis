# -*- coding: utf-8 -*-
"""Pooled HTTPX execution and streaming engine for the native 4-protocol LLM transport.

Implements invariants P3-P7:
- P3: Total attempt budget capped at ``1 + num_retries``; 400/413/422/404 and HTTP 200 HTML
  fail fast; 401/non-WAF 403 exclude key; WAF 403 & model-disabled 403 do NOT poison auth.
- P4: Single monotonic deadline per logical call (respecting stock cancellation deadline),
  enforced incrementally across non-streaming chunks, bounded error reads, parameter
  recovery retries, pre-``mark_success`` checks, and SSE chunk loops.
- P5: Thread-safe closeable ``NativeStreamWrapper`` releasing HTTP resources even if never
  iterated or closed concurrently with pre-chunk retry, ``try/finally`` cleanup around
  bounded error/preamble reads, no post-first-chunk failover, streaming HTTP 200 JSON/HTML
  detection (including ``text/plain``), and mandatory terminal-marker verification before
  ``mark_success``.
- P6: Reference-counted shared pooled ``httpx.Client`` per proxy/TLS policy (including
  distinct ``ALL_PROXY``/``all_proxy``) safely retiring on ``reset_transport_cache()``,
  while enforcing origin-bound caller/deployment clients, ``follow_redirects=False`` on
  every request, and single-lifecycle wrapper clients for injected ``httpx.BaseTransport``.
- P7: Full secret redaction (including decoded/raw URL query credentials) in message,
  body, and warning logs; typed ``NativeTimeoutError`` and ``NativeConnectionError``;
  support for float/tuple/``httpx.Timeout`` values.
"""

from __future__ import annotations

from dataclasses import dataclass
import itertools
import json
import logging
import math
import os
import re
import threading
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import httpx

from src.core.stock_execution_context import get_current_stock_cancellation
from src.llm.native_pool import DeploymentPool, parse_retry_after
from src.llm.native_resolve import resolve_headers_env, url_origin
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
    check_in_band_json_error,
    classify_http_error,
    collect_secret_values,
    looks_like_html,
    sanitize_error_message,
)

logger = logging.getLogger(__name__)

_MAX_ERROR_BODY_BYTES = 64 * 1024
_MAX_NON_STREAM_BODY_BYTES = 32 * 1024 * 1024

# ============================================================
# P6: Lease-Counted Pooled httpx.Client Lifecycle Management
# ============================================================


@dataclass
class _PooledClientEntry:
    client: httpx.Client
    leases: int = 0
    retired: bool = False
    closed: bool = False


_POOLED_CLIENTS_LOCK = threading.Lock()
_POOLED_CLIENTS: Dict[Tuple[bool, str, str, str, str, str, str, str, str, str, str], _PooledClientEntry] = {}


def _current_proxy_env_key() -> Tuple[str, str, str, str, str, str, str, str, str, str]:
    """Snapshot env vars affecting ``httpx.Client(trust_env=True)`` proxy/TLS routing (P2)."""
    return (
        os.getenv("HTTP_PROXY", ""),
        os.getenv("http_proxy", ""),
        os.getenv("HTTPS_PROXY", ""),
        os.getenv("https_proxy", ""),
        os.getenv("ALL_PROXY", ""),
        os.getenv("all_proxy", ""),
        os.getenv("NO_PROXY", ""),
        os.getenv("no_proxy", ""),
        os.getenv("SSL_CERT_FILE", ""),
        os.getenv("SSL_CERT_DIR", ""),
    )


def _acquire_pooled_client_entry(*, trust_env: bool = True) -> _PooledClientEntry:
    """Acquire a leased pooled ``httpx.Client`` entry safe against concurrent cache resets."""
    env_key = _current_proxy_env_key() if trust_env else ("",) * 10
    cache_key = (bool(trust_env), *env_key)
    with _POOLED_CLIENTS_LOCK:
        entry = _POOLED_CLIENTS.get(cache_key)
        if entry is None or entry.retired or entry.closed or entry.client.is_closed:
            entry = _PooledClientEntry(
                client=httpx.Client(
                    trust_env=trust_env,
                    follow_redirects=False,
                )
            )
            _POOLED_CLIENTS[cache_key] = entry
        entry.leases += 1
        return entry


def _release_pooled_client_entry(entry: Optional[_PooledClientEntry]) -> None:
    """Release a pooled client lease and close it immediately if already retired."""
    if entry is None:
        return
    client_to_close: Optional[httpx.Client] = None
    with _POOLED_CLIENTS_LOCK:
        entry.leases = max(0, entry.leases - 1)
        if entry.retired and entry.leases == 0 and not entry.closed:
            entry.closed = True
            client_to_close = entry.client
    if client_to_close is not None:
        try:
            client_to_close.close()
        except Exception:
            pass


def get_pooled_httpx_client(*, trust_env: bool = True) -> httpx.Client:
    """Return the active shared pooled ``httpx.Client`` for the current proxy/TLS environment."""
    env_key = _current_proxy_env_key() if trust_env else ("",) * 10
    cache_key = (bool(trust_env), *env_key)
    with _POOLED_CLIENTS_LOCK:
        entry = _POOLED_CLIENTS.get(cache_key)
        if entry is None or entry.retired or entry.closed or entry.client.is_closed:
            entry = _PooledClientEntry(
                client=httpx.Client(
                    trust_env=trust_env,
                    follow_redirects=False,
                )
            )
            _POOLED_CLIENTS[cache_key] = entry
        return entry.client


def close_pooled_clients() -> None:
    """Retire all cached pooled ``httpx.Client`` instances, closing idle ones immediately.

    Clients currently leased by in-flight requests or open streams remain alive
    until their last lease releases, avoiding concurrent ``RuntimeError`` crashes.
    """
    to_close: List[httpx.Client] = []
    with _POOLED_CLIENTS_LOCK:
        entries = list(_POOLED_CLIENTS.values())
        _POOLED_CLIENTS.clear()
        for entry in entries:
            entry.retired = True
            if entry.leases <= 0 and not entry.closed:
                entry.closed = True
                to_close.append(entry.client)
    for client in to_close:
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
    external_deadline: Optional[float] = None,
) -> Optional[float]:
    """Compute one monotonic deadline per logical call (min of timeout, recovery deadline, and stock cancel)."""
    req_seconds = normalize_timeout_seconds(raw_timeout, default_seconds=default_timeout)
    token = get_current_stock_cancellation()
    stock_remaining = token.remaining_seconds() if token is not None else None
    effective: Optional[float] = req_seconds
    if stock_remaining is not None:
        if effective is None:
            effective = float(stock_remaining)
        else:
            effective = min(effective, float(stock_remaining))
    computed = (clock() + effective) if effective is not None else None
    if external_deadline is not None:
        try:
            ext_val = float(external_deadline)
            if math.isfinite(ext_val):
                computed = ext_val if computed is None else min(computed, ext_val)
        except (TypeError, ValueError):
            pass
    return computed


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
            "LLM request timed out (call deadline exceeded)",
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


def _is_json_content_type(content_type: Optional[str]) -> bool:
    ct = str(content_type or "").split(";", 1)[0].strip().lower()
    return ct in {"application/json", "text/json"} or ct.endswith("+json")


def _is_html_content_type(content_type: Optional[str]) -> bool:
    ct = str(content_type or "").lower()
    return "text/html" in ct or "application/xhtml" in ct


def _is_sse_content_type(content_type: Optional[str]) -> bool:
    ct = str(content_type or "").split(";", 1)[0].strip().lower()
    return ct == "text/event-stream"


def _read_bytes_bounded(
    byte_iter: Iterator[bytes],
    *,
    status_code: int,
    deadline: Optional[float],
    clock: Callable[[], float],
    cancel_check: Optional[Callable[[], None]],
    provider: str,
    secrets: Iterable[str],
    max_bytes: int,
    raise_on_limit: bool = False,
    initial_chunk: Optional[bytes] = None,
) -> bytes:
    """Read bytes incrementally while enforcing call deadline, cancellation, and size cap (P1-4a)."""
    chunks: List[bytes] = []
    total = 0

    def _consume(chunk: bytes) -> bool:
        nonlocal total
        if not chunk:
            return False
        remaining_cap = max_bytes - total
        if len(chunk) > remaining_cap:
            if raise_on_limit:
                raise NativeBadRequestError(
                    f"LLM response body exceeded maximum size ({max_bytes} bytes)",
                    status_code=status_code,
                    provider=provider,
                    secrets=secrets,
                    error_code="response_too_large",
                )
            if remaining_cap > 0:
                chunks.append(chunk[:remaining_cap])
                total += remaining_cap
            return True
        chunks.append(chunk)
        total += len(chunk)
        # P1-4a: Stop immediately once cap is reached so exact-size error bodies don't wait for EOF.
        return (not raise_on_limit) and total >= max_bytes

    if initial_chunk is not None:
        if cancel_check is not None:
            cancel_check()
        _remaining_before_deadline(deadline, clock=clock, provider=provider, secrets=secrets)
        if _consume(initial_chunk):
            return b"".join(chunks)

    for chunk in byte_iter:
        if cancel_check is not None:
            cancel_check()
        _remaining_before_deadline(deadline, clock=clock, provider=provider, secrets=secrets)
        if _consume(chunk):
            break

    if cancel_check is not None:
        cancel_check()
    _remaining_before_deadline(deadline, clock=clock, provider=provider, secrets=secrets)
    return b"".join(chunks)


def _read_response_bounded(
    resp: httpx.Response,
    *,
    deadline: Optional[float],
    clock: Callable[[], float],
    cancel_check: Optional[Callable[[], None]],
    provider: str,
    secrets: Iterable[str],
    max_bytes: int,
    raise_on_limit: bool = False,
) -> bytes:
    return _read_bytes_bounded(
        resp.iter_bytes(),
        status_code=resp.status_code,
        deadline=deadline,
        clock=clock,
        cancel_check=cancel_check,
        provider=provider,
        secrets=secrets,
        max_bytes=max_bytes,
        raise_on_limit=raise_on_limit,
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
    """Choose the next candidate respecting pool cooldowns and advancing cursor ONCE per logical call."""
    if using_pool and pool is not None:
        # P1-3: Advance round-robin cursor only on attempt 0 so 2/4 healthy keys rotate cleanly.
        available = pool.select_candidates(
            request_model,
            exclude_ids=bad_auth_ids,
            advance_cursor=(attempt_idx == 0),
        )
        if not available:
            return None
        for dep in available:
            if dep.deployment_id not in tried_ids_this_call:
                return dep
        return available[0]

    filtered = [dep for dep in candidates if dep.deployment_id not in bad_auth_ids]
    if not filtered:
        return None
    return filtered[attempt_idx % len(filtered)]


def _entry_secrets(
    entry: DeploymentSpec,
    kwargs: Mapping[str, Any],
    *,
    url: Optional[str] = None,
    headers: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    merged_headers: Dict[str, Any] = dict(entry.extra_headers)
    for key in ("extra_headers", "headers", "default_headers"):
        raw = kwargs.get(key)
        if isinstance(raw, Mapping):
            merged_headers.update(resolve_headers_env(raw))
    if isinstance(headers, Mapping):
        merged_headers.update(headers)
    return collect_secret_values(
        entry.api_key,
        kwargs.get("api_key"),
        headers=merged_headers,
        url=url or entry.endpoint_url or entry.api_base,
    )


def _collect_alias_origins(
    candidates: List[DeploymentSpec],
    *,
    pool: Optional[DeploymentPool],
    using_pool: bool,
    request_model: str,
) -> set[Tuple[str, str, int]]:
    """Collect origins across ALL deployments registered for the alias regardless of cooldown (P0-2)."""
    all_deps = (
        pool.get_alias_deployments(request_model)
        if (using_pool and pool is not None)
        else candidates
    )
    return {
        orig
        for dep in all_deps
        if (orig := url_origin(dep.api_base)) is not None
    }


def _should_restrict_cross_origin_headers(
    entry: DeploymentSpec,
    *,
    using_pool: bool,
    pool_origins: set[Tuple[str, str, int]],
    caller_header_origin: Optional[Tuple[str, str, int]],
) -> bool:
    """Return True when caller headers/api_key must be restricted to the safe cross-origin allowlist (P0-2)."""
    entry_origin = url_origin(entry.api_base)
    if caller_header_origin is not None:
        return entry_origin is None or entry_origin != caller_header_origin
    if using_pool and len(pool_origins) > 1:
        return True
    return False


class _NonClosingTransport(httpx.BaseTransport):
    """Proxy wrapping a caller/router-owned BaseTransport so per-call Client.close() never closes it (F4)."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._inner.handle_request(request)

    def close(self) -> None:
        return None


def _sanitize_redirect_location(raw_location: str, secrets: Iterable[str]) -> str:
    """Strip query/fragment and redact any remaining secrets from HTTP 3xx Location headers (F3)."""
    loc = str(raw_location or "").strip()
    if not loc:
        return ""
    loc_secrets = list(secrets) + collect_secret_values(url=loc)
    try:
        parts = urlsplit(loc)
        netloc = parts.netloc
        if "@" in netloc:
            netloc = netloc.split("@", 1)[1]
        stripped = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except Exception:
        stripped = re.sub(r"(://)[^/@]+@", r"\1", loc.split("?", 1)[0].split("#", 1)[0])
    return sanitize_error_message(stripped, loc_secrets)


def _acquire_attempt_client(
    entry: DeploymentSpec,
    *,
    shared_transport_client: Optional[httpx.Client],
    http_client: Optional[httpx.Client],
    caller_client_origin: Optional[Tuple[str, str, int]],
    deployment_clients: Optional[Mapping[str, httpx.Client]],
    multi_origin_pool: bool,
    restrict_caller_headers: bool = False,
) -> Tuple[httpx.Client, Optional[_PooledClientEntry]]:
    """Select the attempt-scoped HTTPX client respecting origin boundaries (P0-3c, F2, P1-2, P1-4, P1-5)."""
    if shared_transport_client is not None:
        return shared_transport_client, None

    entry_origin = url_origin(entry.api_base)
    dep_client = deployment_clients.get(entry.deployment_id) if deployment_clients is not None else None

    if http_client is not None:
        if caller_client_origin is not None:
            if entry_origin is not None and entry_origin == caller_client_origin:
                return http_client, None
        elif not multi_origin_pool and dep_client is None and not restrict_caller_headers:
            return http_client, None

    if dep_client is not None:
        return dep_client, None

    lease = _acquire_pooled_client_entry(trust_env=True)
    return lease.client, lease


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
    deployment_clients: Optional[Mapping[str, httpx.Client]] = None,
    caller_client_origin: Optional[Tuple[str, str, int]] = None,
    caller_header_origin: Optional[Tuple[str, str, int]] = None,
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

    # P0-2: Compute origins over ALL alias deployments regardless of cooldown.
    pool_origins = _collect_alias_origins(
        candidates,
        pool=pool,
        using_pool=using_pool,
        request_model=request_model,
    )
    multi_origin_pool = using_pool and len(pool_origins) > 1

    raw_timeout = kwargs.get("timeout")
    if raw_timeout is None and candidates and candidates[0].timeout is not None:
        raw_timeout = candidates[0].timeout
    deadline = _compute_call_deadline(
        raw_timeout=raw_timeout,
        default_timeout=default_timeout,
        clock=clock,
        external_deadline=kwargs.get("_dsa_deadline_monotonic"),
    )

    # P1-2 & F4: Keep injected BaseTransport wrapper client alive across attempts AND
    # wrap with _NonClosingTransport so completing call 1 never closes a router-shared transport.
    shared_transport_client: Optional[httpx.Client] = (
        httpx.Client(transport=_NonClosingTransport(http_transport), follow_redirects=False)
        if http_transport is not None
        else None
    )

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

            # Backoff only when retrying an already-tried deployment.
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
            restrict_cross_origin = _should_restrict_cross_origin_headers(
                entry,
                using_pool=using_pool,
                pool_origins=pool_origins,
                caller_header_origin=caller_header_origin,
            )
            attempt_kwargs: Dict[str, Any] = dict(kwargs)
            if restrict_cross_origin:
                attempt_kwargs["_dsa_skip_sensitive_caller_headers"] = True

            url, headers, payload, prepared_timeout = prepare_request_fn(
                entry, messages, False, attempt_kwargs
            )
            secrets = _entry_secrets(entry, attempt_kwargs, url=url, headers=headers)
            attempt_timeout = build_attempt_httpx_timeout(
                raw_timeout if raw_timeout is not None else prepared_timeout,
                remaining,
            )

            active_client, pooled_lease = _acquire_attempt_client(
                entry,
                shared_transport_client=shared_transport_client,
                http_client=http_client,
                caller_client_origin=caller_client_origin,
                deployment_clients=deployment_clients,
                multi_origin_pool=multi_origin_pool,
                restrict_caller_headers=restrict_cross_origin,
            )

            try:
                # P0-3a: Explicitly disable redirects on EVERY request even for injected clients.
                with active_client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=payload,
                    timeout=attempt_timeout,
                    follow_redirects=False,
                ) as resp:
                    status_code = resp.status_code
                    resp_headers = resp.headers
                    content_type = resp_headers.get("content-type", "")

                    if 300 <= status_code < 400:
                        location = _sanitize_redirect_location(resp_headers.get("location", ""), secrets)
                        raise NativeBadRequestError(
                            f"HTTP {status_code} redirect refused (follow_redirects=False)"
                            + (f" -> {location}" if location else ""),
                            status_code=status_code,
                            provider=entry.provider,
                            secrets=secrets,
                            error_code="unexpected_redirect",
                        )

                    if status_code >= 400:
                        raw_err_bytes = _read_response_bounded(
                            resp,
                            deadline=deadline,
                            clock=clock,
                            cancel_check=cancel_check,
                            provider=entry.provider,
                            secrets=secrets,
                            max_bytes=_MAX_ERROR_BODY_BYTES,
                            raise_on_limit=False,
                        )
                        body_text = raw_err_bytes.decode("utf-8-sig", errors="replace")
                        err = classify_http_error(
                            status_code,
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
                            retry_after = parse_retry_after(
                                resp_headers.get("retry-after"),
                                now_wall=now_wall,
                            )
                            pool.mark_failure(
                                entry.deployment_id,
                                status_code=status_code,
                                retry_after=retry_after,
                            )
                        last_error = err
                        continue

                    max_body = _MAX_ERROR_BODY_BYTES if _is_html_content_type(content_type) else _MAX_NON_STREAM_BODY_BYTES
                    raw_bytes = _read_response_bounded(
                        resp,
                        deadline=deadline,
                        clock=clock,
                        cancel_check=cancel_check,
                        provider=entry.provider,
                        secrets=secrets,
                        max_bytes=max_body,
                        raise_on_limit=not _is_html_content_type(content_type),
                    )
                    # P1-3a: Decode with utf-8-sig so BOM-prefixed valid JSON succeeds.
                    body_text = raw_bytes.decode("utf-8-sig", errors="replace")

                # P1-8 & P1-3b: Explicit HTML content-type fails fast; otherwise parse JSON FIRST,
                # and on JSON parse failure sniff document-start HTML ignoring bogus JSON MIME.
                if _is_html_content_type(content_type):
                    check_http_200_html_response(
                        status_code,
                        content_type,
                        body_text,
                        provider=entry.provider,
                        secrets=secrets,
                    )

                try:
                    data = json.loads(body_text)
                except ValueError as json_exc:
                    check_http_200_html_response(
                        status_code,
                        content_type,
                        body_text,
                        provider=entry.provider,
                        secrets=secrets,
                        ignore_content_type=True,
                    )
                    raise NativeBadRequestError(
                        f"Endpoint returned non-JSON response (Content-Type: {content_type or 'unknown'}); "
                        "check Base URL /v1.",
                        status_code=status_code,
                        provider=entry.provider,
                        body=body_text[:512],
                        secrets=secrets,
                        error_code="non_json_response",
                    ) from json_exc

                if not isinstance(data, Mapping):
                    raise NativeBadRequestError(
                        "Unexpected non-object JSON response from LLM endpoint",
                        status_code=status_code,
                        provider=entry.provider,
                        body=str(data)[:512],
                        secrets=secrets,
                    )

                parsed = parse_response_fn(entry, data, secrets)
                if cancel_check is not None:
                    cancel_check()
                _remaining_before_deadline(
                    deadline,
                    clock=clock,
                    provider=entry.provider,
                    secrets=secrets,
                )
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
            except NativeTimeoutError as exc:
                if deadline is not None and (deadline - clock()) <= 0:
                    if using_pool and pool is not None:
                        pool.mark_failure(entry.deployment_id, status_code=408)
                    raise
                if using_pool and pool is not None:
                    pool.mark_failure(entry.deployment_id, status_code=exc.status_code or 408)
                last_error = exc
            except NativeAPIError as exc:
                if isinstance(exc, NativeAuthenticationError):
                    bad_auth_ids.add(entry.deployment_id)
                if using_pool and pool is not None:
                    pool.mark_failure(entry.deployment_id, status_code=exc.status_code)
                last_error = exc
            finally:
                _release_pooled_client_entry(pooled_lease)

        if last_error is not None:
            raise last_error
        raise NativeAPIError(
            f"No available deployments configured for {request_model or 'request'}",
            provider=candidates[0].provider if candidates else "openai",
        )
    finally:
        if shared_transport_client is not None:
            try:
                shared_transport_client.close()
            except Exception:
                pass


# ============================================================
# P5: Streaming Execution with Strict Resource Ownership
# ============================================================

_StreamOpenTuple = Tuple[
    DeploymentSpec,
    Any,
    httpx.Response,
    Iterator[bytes],
    Optional[_PooledClientEntry],
    List[str],
]


def _close_stream_resources(
    ctx: Any,
    pooled_lease: Optional[_PooledClientEntry],
    shared_transport_client: Optional[httpx.Client] = None,
) -> None:
    if ctx is not None:
        try:
            ctx.__exit__(None, None, None)
        except Exception:
            pass
    _release_pooled_client_entry(pooled_lease)
    if shared_transport_client is not None:
        try:
            shared_transport_client.close()
        except Exception:
            pass


class NativeStreamWrapper:
    """Thread-safe closeable stream wrapper guaranteeing connection and lease release (P1-1, P5)."""

    transport_engine: str = "native"

    def __init__(
        self,
        *,
        entry: DeploymentSpec,
        ctx: Any,
        resp: httpx.Response,
        byte_iter: Iterator[bytes],
        shared_transport_client: Optional[httpx.Client],
        pooled_lease: Optional[_PooledClientEntry],
        pool: Optional[DeploymentPool],
        using_pool: bool,
        iter_stream_fn: Callable[[DeploymentSpec, Iterable[bytes], Iterable[str], Callable[[], None]], Iterator[NativeStreamChunk]],
        secrets: List[str],
        deadline: Optional[float],
        clock: Callable[[], float],
        cancel_check: Optional[Callable[[], None]],
        on_pre_chunk_retry: Callable[[Exception, str], Tuple[Optional[_StreamOpenTuple], Optional[Exception]]],
    ) -> None:
        self._lock = threading.Lock()
        self._entry = entry
        self._ctx = ctx
        self._resp: Optional[httpx.Response] = resp
        self._byte_iter: Optional[Iterator[bytes]] = byte_iter
        self._shared_transport_client = shared_transport_client
        self._pooled_lease = pooled_lease
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

    def _close_active_connection(self, *, close_shared_client: bool = False) -> None:
        with self._lock:
            ctx = self._ctx
            lease = self._pooled_lease
            shared = self._shared_transport_client if close_shared_client else None
            self._ctx = None
            self._resp = None
            self._byte_iter = None
            self._pooled_lease = None
            if close_shared_client:
                self._shared_transport_client = None
        _close_stream_resources(ctx, lease, shared)

    def is_closed(self) -> bool:
        """Return True once ``close()`` has been called (F4)."""
        with self._lock:
            return self._closed

    def close(self) -> None:
        """Close the active HTTP stream, pooled lease, and owned transport client immediately."""
        with self._lock:
            self._closed = True
            ctx = self._ctx
            lease = self._pooled_lease
            shared = self._shared_transport_client
            self._ctx = None
            self._resp = None
            self._byte_iter = None
            self._pooled_lease = None
            self._shared_transport_client = None
        _close_stream_resources(ctx, lease, shared)

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
            while True:
                with self._lock:
                    if self._closed or self._byte_iter is None:
                        return
                    cur_entry = self._entry
                    cur_byte_iter = self._byte_iter
                    cur_secrets = self._secrets

                try:
                    self._check_deadline_and_cancel()
                    for chunk in self._iter_stream_fn(
                        cur_entry,
                        cur_byte_iter,
                        cur_secrets,
                        self._check_deadline_and_cancel,
                    ):
                        with self._lock:
                            if self._closed:
                                return
                        chunk._hidden_params["deployment_id"] = cur_entry.deployment_id
                        chunk._hidden_params["protocol"] = cur_entry.protocol
                        chunk._hidden_params["transport_engine"] = "native"
                        emitted_any = True
                        yield chunk

                    if not emitted_any:
                        raise NativeIncompleteStreamError(
                            "SSE stream closed without yielding any chunks",
                            provider=cur_entry.provider,
                            secrets=cur_secrets,
                            error_code="incomplete_stream",
                        )

                    self._check_deadline_and_cancel()
                    if self._using_pool and self._pool is not None:
                        self._pool.mark_success(cur_entry.deployment_id)
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
                    sanitized = sanitize_error_message(exc, cur_secrets)
                    if isinstance(exc, httpx.TimeoutException):
                        wrapped: NativeAPIError = NativeTimeoutError(
                            sanitized or "Stream timed out",
                            provider=cur_entry.provider,
                            secrets=cur_secrets,
                        )
                    elif isinstance(exc, httpx.TransportError):
                        wrapped = NativeConnectionError(
                            sanitized or "Stream transport error",
                            provider=cur_entry.provider,
                            secrets=cur_secrets,
                        )
                    else:
                        wrapped = exc

                    if self._using_pool and self._pool is not None:
                        self._pool.mark_failure(
                            cur_entry.deployment_id,
                            status_code=wrapped.status_code,
                        )

                    # Keep shared_transport_client open during pre-chunk failover (P1-2).
                    self._close_active_connection(close_shared_client=False)

                    with self._lock:
                        already_closed = self._closed
                    if emitted_any or already_closed:
                        # P5: No failover after the first chunk has been emitted or stream closed.
                        raise wrapped from exc

                    if isinstance(wrapped, NativeTimeoutError) and self._deadline is not None:
                        if (self._deadline - self._clock()) <= 0:
                            raise wrapped from exc

                    next_conn, retry_err = self._on_pre_chunk_retry(wrapped, cur_entry.deployment_id)
                    if next_conn is None:
                        if self.is_closed():
                            return
                        if retry_err is not None and retry_err is not wrapped:
                            raise retry_err
                        raise wrapped from exc

                    # P1-1: Guard replacement adoption under lock; if close() won the race, release immediately!
                    next_entry, next_ctx, next_resp, next_iter, next_lease, next_secrets = next_conn
                    with self._lock:
                        if self._closed:
                            should_discard = True
                        else:
                            should_discard = False
                            self._entry = next_entry
                            self._ctx = next_ctx
                            self._resp = next_resp
                            self._byte_iter = next_iter
                            self._pooled_lease = next_lease
                            self._secrets = next_secrets
                    if should_discard:
                        _close_stream_resources(next_ctx, next_lease)
                        return
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
    shared_transport_client: Optional[httpx.Client],
    http_client: Optional[httpx.Client],
    caller_client_origin: Optional[Tuple[str, str, int]],
    deployment_clients: Optional[Mapping[str, httpx.Client]],
    multi_origin_pool: bool,
    raw_timeout: Any,
    remaining: Optional[float],
    deadline: Optional[float],
    clock: Callable[[], float],
    cancel_check: Optional[Callable[[], None]],
    bad_auth_ids: set[str],
    now_wall: Optional[Callable[[], float]],
) -> Tuple[Optional[Tuple[Any, httpx.Response, Iterator[bytes], Optional[_PooledClientEntry], List[str]]], Optional[Exception]]:
    """Open a single SSE stream attempt with bounded error/preamble reads and JSON/HTML 200 detection."""
    url, headers, payload, prepared_timeout = prepare_request_fn(entry, messages, True, kwargs)
    secrets = _entry_secrets(entry, kwargs, url=url, headers=headers)
    attempt_timeout = build_attempt_httpx_timeout(
        raw_timeout if raw_timeout is not None else prepared_timeout,
        remaining,
    )

    client, pooled_lease = _acquire_attempt_client(
        entry,
        shared_transport_client=shared_transport_client,
        http_client=http_client,
        caller_client_origin=caller_client_origin,
        deployment_clients=deployment_clients,
        multi_origin_pool=multi_origin_pool,
        restrict_caller_headers=bool(kwargs.get("_dsa_skip_sensitive_caller_headers")),
    )

    def _release_resources(ctx_obj: Any = None) -> None:
        _close_stream_resources(ctx_obj, pooled_lease)

    ctx: Any = None
    try:
        # P0-3a: Explicitly disable redirects on EVERY stream request.
        ctx = client.stream(
            "POST",
            url,
            headers=headers,
            json=payload,
            timeout=attempt_timeout,
            follow_redirects=False,
        )
        resp = ctx.__enter__()
    except httpx.TimeoutException as exc:
        _release_resources()
        sanitized = sanitize_error_message(exc, secrets)
        if using_pool and pool is not None:
            pool.mark_failure(entry.deployment_id, status_code=408)
        return None, NativeTimeoutError(
            sanitized or "Stream connection timed out",
            provider=entry.provider,
            secrets=secrets,
        )
    except httpx.TransportError as exc:
        _release_resources()
        sanitized = sanitize_error_message(exc, secrets)
        if using_pool and pool is not None:
            pool.mark_failure(entry.deployment_id)
        return None, NativeConnectionError(
            sanitized or "Stream connection error",
            provider=entry.provider,
            secrets=secrets,
        )
    except Exception:
        _release_resources()
        raise

    def _handle_json_stream_body(json_text: str, content_type_label: str) -> Tuple[None, Exception]:
        try:
            parsed_obj = json.loads(json_text)
        except ValueError as json_exc:
            check_http_200_html_response(
                resp.status_code,
                content_type_label,
                json_text,
                provider=entry.provider,
                secrets=secrets,
                ignore_content_type=True,
            )
            raise NativeBadRequestError(
                f"Streaming endpoint returned invalid JSON ({content_type_label}): {json_text[:200]}",
                status_code=resp.status_code,
                provider=entry.provider,
                body=json_text[:512],
                secrets=secrets,
                error_code="non_sse_json_response",
            ) from json_exc

        if isinstance(parsed_obj, Mapping):
            try:
                check_in_band_json_error(parsed_obj, provider=entry.provider, secrets=secrets)
            except NativeAPIError as in_band_err:
                if _is_fail_fast_error(in_band_err):
                    raise
                if isinstance(in_band_err, NativeAuthenticationError):
                    bad_auth_ids.add(entry.deployment_id)
                if using_pool and pool is not None:
                    pool.mark_failure(
                        entry.deployment_id,
                        status_code=in_band_err.status_code,
                    )
                return None, in_band_err

        raise NativeBadRequestError(
            f"Streaming endpoint returned {content_type_label or 'JSON'} instead of text/event-stream",
            status_code=resp.status_code,
            provider=entry.provider,
            body=json_text[:512],
            secrets=secrets,
            error_code="non_sse_json_response",
        )

    # Fail fast on HTTP 3xx redirects (follow_redirects=False) instead of parsing redirect as SSE.
    if 300 <= resp.status_code < 400:
        location = _sanitize_redirect_location(resp.headers.get("location", ""), secrets)
        status_code = resp.status_code
        _release_resources(ctx)
        raise NativeBadRequestError(
            f"HTTP {status_code} redirect refused (follow_redirects=False)"
            + (f" -> {location}" if location else ""),
            status_code=status_code,
            provider=entry.provider,
            secrets=secrets,
            error_code="unexpected_redirect",
        )

    # Handle HTTP >=400 with bounded deadline-checked body read and guaranteed cleanup (P5, P1-4a, P1-6).
    if resp.status_code >= 400:
        try:
            raw_err = _read_response_bounded(
                resp,
                deadline=deadline,
                clock=clock,
                cancel_check=cancel_check,
                provider=entry.provider,
                secrets=secrets,
                max_bytes=_MAX_ERROR_BODY_BYTES,
                raise_on_limit=False,
            )
            body_text = raw_err.decode("utf-8-sig", errors="replace")
            retry_after = parse_retry_after(resp.headers.get("retry-after"), now_wall=now_wall)
            resp_headers = resp.headers
        except httpx.TimeoutException as exc:
            sanitized = sanitize_error_message(exc, secrets)
            if using_pool and pool is not None:
                pool.mark_failure(entry.deployment_id, status_code=408)
            return None, NativeTimeoutError(
                sanitized or "Error body read timed out",
                provider=entry.provider,
                secrets=secrets,
            )
        except httpx.TransportError as exc:
            sanitized = sanitize_error_message(exc, secrets)
            if using_pool and pool is not None:
                pool.mark_failure(entry.deployment_id)
            return None, NativeConnectionError(
                sanitized or "Error body read failed",
                provider=entry.provider,
                secrets=secrets,
            )
        finally:
            _release_resources(ctx)

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

    # Fail fast on HTTP 200 HTML response (P1-4b: catch Timeout/TransportError during preamble read).
    content_type = resp.headers.get("content-type", "")
    if _is_html_content_type(content_type):
        try:
            raw_html = _read_response_bounded(
                resp,
                deadline=deadline,
                clock=clock,
                cancel_check=cancel_check,
                provider=entry.provider,
                secrets=secrets,
                max_bytes=_MAX_ERROR_BODY_BYTES,
                raise_on_limit=False,
            )
            html_body = raw_html.decode("utf-8-sig", errors="replace")
        except httpx.TimeoutException as exc:
            sanitized = sanitize_error_message(exc, secrets)
            if using_pool and pool is not None:
                pool.mark_failure(entry.deployment_id, status_code=408)
            return None, NativeTimeoutError(sanitized or "HTML preamble read timed out", provider=entry.provider, secrets=secrets)
        except httpx.TransportError as exc:
            sanitized = sanitize_error_message(exc, secrets)
            if using_pool and pool is not None:
                pool.mark_failure(entry.deployment_id)
            return None, NativeConnectionError(sanitized or "HTML preamble read failed", provider=entry.provider, secrets=secrets)
        finally:
            _release_resources(ctx)
        check_http_200_html_response(
            resp.status_code,
            content_type,
            html_body,
            provider=entry.provider,
            secrets=secrets,
        )

    # P1-7 & P1-4b: Detect HTTP 200 application/json errors before entering SSE parser.
    if _is_json_content_type(content_type):
        try:
            raw_json = _read_response_bounded(
                resp,
                deadline=deadline,
                clock=clock,
                cancel_check=cancel_check,
                provider=entry.provider,
                secrets=secrets,
                max_bytes=_MAX_ERROR_BODY_BYTES,
                raise_on_limit=False,
            )
            json_text = raw_json.decode("utf-8-sig", errors="replace")
        except httpx.TimeoutException as exc:
            sanitized = sanitize_error_message(exc, secrets)
            if using_pool and pool is not None:
                pool.mark_failure(entry.deployment_id, status_code=408)
            return None, NativeTimeoutError(sanitized or "JSON preamble read timed out", provider=entry.provider, secrets=secrets)
        except httpx.TransportError as exc:
            sanitized = sanitize_error_message(exc, secrets)
            if using_pool and pool is not None:
                pool.mark_failure(entry.deployment_id)
            return None, NativeConnectionError(sanitized or "JSON preamble read failed", provider=entry.provider, secrets=secrets)
        finally:
            _release_resources(ctx)
        return _handle_json_stream_body(json_text, content_type)

    # P1-4b & F6: For non-SSE Content-Type (e.g. text/plain or omitted), accumulate leading
    # chunks until non-whitespace preamble bytes identify JSON/HTML vs SSE (handling
    # whitespace-first JSON and split `<ht`+`ml>` tags without delaying real SSE streams).
    byte_iter: Iterator[bytes] = resp.iter_bytes()
    if not _is_sse_content_type(content_type):
        buffered_chunks: List[bytes] = []
        raw_lead = bytearray()
        try:
            for candidate_chunk in byte_iter:
                if cancel_check is not None:
                    cancel_check()
                _remaining_before_deadline(deadline, clock=clock, provider=entry.provider, secrets=secrets)
                if not candidate_chunk:
                    continue
                buffered_chunks.append(candidate_chunk)
                raw_lead.extend(candidate_chunk)
                stripped_lead = bytes(raw_lead).lstrip(b"\xef\xbb\xbf \t\r\n")
                if not stripped_lead:
                    # Guard against infinite whitespace-only streams.
                    if len(raw_lead) >= 4096:
                        break
                    continue
                if stripped_lead.startswith(b"{"):
                    break
                if stripped_lead.startswith(b"<"):
                    if len(stripped_lead) >= 64 or looks_like_html(
                        stripped_lead[:512].decode("utf-8-sig", errors="replace"),
                        ignore_content_type=True,
                    ):
                        break
                    continue
                # Not JSON or HTML (e.g. SSE `data:` / `event:` / `:comment`): stop immediately!
                break
        except httpx.TimeoutException as exc:
            _release_resources(ctx)
            sanitized = sanitize_error_message(exc, secrets)
            if using_pool and pool is not None:
                pool.mark_failure(entry.deployment_id, status_code=408)
            return None, NativeTimeoutError(sanitized or "Stream preamble read timed out", provider=entry.provider, secrets=secrets)
        except httpx.TransportError as exc:
            _release_resources(ctx)
            sanitized = sanitize_error_message(exc, secrets)
            if using_pool and pool is not None:
                pool.mark_failure(entry.deployment_id)
            return None, NativeConnectionError(sanitized or "Stream preamble read failed", provider=entry.provider, secrets=secrets)
        except Exception:
            _release_resources(ctx)
            raise

        if buffered_chunks:
            combined_lead = b"".join(buffered_chunks)
            stripped_lead = combined_lead.lstrip(b"\xef\xbb\xbf \t\r\n")
            if stripped_lead.startswith(b"{"):
                try:
                    raw_json = _read_bytes_bounded(
                        byte_iter,
                        status_code=resp.status_code,
                        deadline=deadline,
                        clock=clock,
                        cancel_check=cancel_check,
                        provider=entry.provider,
                        secrets=secrets,
                        max_bytes=_MAX_ERROR_BODY_BYTES,
                        raise_on_limit=False,
                        initial_chunk=combined_lead,
                    )
                    json_text = raw_json.decode("utf-8-sig", errors="replace")
                except httpx.TimeoutException as exc:
                    sanitized = sanitize_error_message(exc, secrets)
                    if using_pool and pool is not None:
                        pool.mark_failure(entry.deployment_id, status_code=408)
                    return None, NativeTimeoutError(sanitized or "JSON preamble read timed out", provider=entry.provider, secrets=secrets)
                except httpx.TransportError as exc:
                    sanitized = sanitize_error_message(exc, secrets)
                    if using_pool and pool is not None:
                        pool.mark_failure(entry.deployment_id)
                    return None, NativeConnectionError(sanitized or "JSON preamble read failed", provider=entry.provider, secrets=secrets)
                finally:
                    _release_resources(ctx)
                return _handle_json_stream_body(json_text, content_type or "text/plain")

            preview_text = stripped_lead[:512].decode("utf-8-sig", errors="replace")
            if looks_like_html(preview_text, ignore_content_type=True):
                try:
                    raw_html = _read_bytes_bounded(
                        byte_iter,
                        status_code=resp.status_code,
                        deadline=deadline,
                        clock=clock,
                        cancel_check=cancel_check,
                        provider=entry.provider,
                        secrets=secrets,
                        max_bytes=_MAX_ERROR_BODY_BYTES,
                        raise_on_limit=False,
                        initial_chunk=combined_lead,
                    )
                    html_body = raw_html.decode("utf-8-sig", errors="replace")
                except httpx.TimeoutException as exc:
                    sanitized = sanitize_error_message(exc, secrets)
                    if using_pool and pool is not None:
                        pool.mark_failure(entry.deployment_id, status_code=408)
                    return None, NativeTimeoutError(sanitized or "HTML preamble read timed out", provider=entry.provider, secrets=secrets)
                except httpx.TransportError as exc:
                    sanitized = sanitize_error_message(exc, secrets)
                    if using_pool and pool is not None:
                        pool.mark_failure(entry.deployment_id)
                    return None, NativeConnectionError(sanitized or "HTML preamble read failed", provider=entry.provider, secrets=secrets)
                finally:
                    _release_resources(ctx)
                check_http_200_html_response(
                    resp.status_code,
                    content_type,
                    html_body,
                    provider=entry.provider,
                    secrets=secrets,
                    ignore_content_type=True,
                )

            byte_iter = itertools.chain(buffered_chunks, byte_iter)

    return (ctx, resp, byte_iter, pooled_lease, secrets), None


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
    deployment_clients: Optional[Mapping[str, httpx.Client]] = None,
    caller_client_origin: Optional[Tuple[str, str, int]] = None,
    caller_header_origin: Optional[Tuple[str, str, int]] = None,
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

    # P0-2: Compute origins over ALL alias deployments regardless of cooldown.
    pool_origins = _collect_alias_origins(
        candidates,
        pool=pool,
        using_pool=using_pool,
        request_model=request_model,
    )
    multi_origin_pool = using_pool and len(pool_origins) > 1

    raw_timeout = kwargs.get("timeout")
    if raw_timeout is None and candidates and candidates[0].timeout is not None:
        raw_timeout = candidates[0].timeout
    deadline = _compute_call_deadline(
        raw_timeout=raw_timeout,
        default_timeout=default_timeout,
        clock=clock,
        external_deadline=kwargs.get("_dsa_deadline_monotonic"),
    )

    # P1-2 & F4: Share one wrapper client across retries AND wrap with _NonClosingTransport
    # so closing a stream never closes a router-shared BaseTransport needed by later calls.
    shared_transport_client: Optional[httpx.Client] = (
        httpx.Client(transport=_NonClosingTransport(http_transport), follow_redirects=False)
        if http_transport is not None
        else None
    )
    is_wrapper_closed: List[Callable[[], bool]] = [lambda: False]

    def _open_next(
        prior_error: Optional[Exception] = None,
    ) -> Tuple[Optional[_StreamOpenTuple], Optional[Exception]]:
        nonlocal attempts_used
        last_err = prior_error
        while attempts_used < max_attempts:
            if is_wrapper_closed[0]():
                return None, last_err
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
                    # F4: Re-check wrapper closure after backoff BEFORE opening a fresh HTTP attempt!
                    if is_wrapper_closed[0]():
                        return None, last_err
                    if cancel_check is not None:
                        cancel_check()
                    remaining = _remaining_before_deadline(
                        deadline,
                        clock=clock,
                        provider=entry.provider,
                        secrets=secrets,
                    )

            if is_wrapper_closed[0]():
                return None, last_err

            attempts_used += 1
            tried_ids.append(entry.deployment_id)
            restrict_cross_origin = _should_restrict_cross_origin_headers(
                entry,
                using_pool=using_pool,
                pool_origins=pool_origins,
                caller_header_origin=caller_header_origin,
            )
            attempt_kwargs: Dict[str, Any] = dict(kwargs)
            if restrict_cross_origin:
                attempt_kwargs["_dsa_skip_sensitive_caller_headers"] = True

            opened, err = _open_stream_attempt(
                entry=entry,
                pool=pool,
                using_pool=using_pool,
                messages=messages,
                kwargs=attempt_kwargs,
                prepare_request_fn=prepare_request_fn,
                shared_transport_client=shared_transport_client,
                http_client=http_client,
                caller_client_origin=caller_client_origin,
                deployment_clients=deployment_clients,
                multi_origin_pool=multi_origin_pool,
                raw_timeout=raw_timeout,
                remaining=remaining,
                deadline=deadline,
                clock=clock,
                cancel_check=cancel_check,
                bad_auth_ids=bad_auth_ids,
                now_wall=now_wall,
            )
            if opened is not None:
                ctx, resp, byte_iter, pooled_lease, opened_secrets = opened
                return (entry, ctx, resp, byte_iter, pooled_lease, opened_secrets), None
            last_err = err

        return None, last_err

    try:
        first_conn, first_err = _open_next()
    except Exception:
        if shared_transport_client is not None:
            try:
                shared_transport_client.close()
            except Exception:
                pass
        raise

    if first_conn is None:
        if shared_transport_client is not None:
            try:
                shared_transport_client.close()
            except Exception:
                pass
        if first_err is not None:
            raise first_err
        raise NativeAPIError(
            f"No healthy deployments available for {request_model or 'stream'}",
            provider=candidates[0].provider if candidates else "openai",
        )

    entry0, ctx0, resp0, iter0, lease0, secrets0 = first_conn

    def _retry_pre_chunk(
        exc: Exception,
        failed_deployment_id: str,
    ) -> Tuple[Optional[_StreamOpenTuple], Optional[Exception]]:
        if isinstance(exc, NativeAuthenticationError):
            bad_auth_ids.add(failed_deployment_id)
        return _open_next(prior_error=exc)

    wrapper = NativeStreamWrapper(
        entry=entry0,
        ctx=ctx0,
        resp=resp0,
        byte_iter=iter0,
        shared_transport_client=shared_transport_client,
        pooled_lease=lease0,
        pool=pool,
        using_pool=using_pool,
        iter_stream_fn=iter_stream_fn,
        secrets=secrets0,
        deadline=deadline,
        clock=clock,
        cancel_check=cancel_check,
        on_pre_chunk_retry=_retry_pre_chunk,
    )
    is_wrapper_closed[0] = wrapper.is_closed
    return wrapper
