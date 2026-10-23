# -*- coding: utf-8 -*-
"""
Optional fastapi-guard security middleware (default off).

Enabled with GUARD_ENABLED=true. It adds per-IP rate limiting, an optional IP
allowlist / blocklist, request screening (path, query, headers) and automatic
bans for scanners. It complements the login failure limiter in src/auth.py and
does not replace it.
"""

from __future__ import annotations

import logging
import os
from typing import List

logger = logging.getLogger(__name__)

_TRUE = ("true", "1", "yes")


def is_guard_enabled() -> bool:
    """Read GUARD_ENABLED (default false)."""
    return os.getenv("GUARD_ENABLED", "false").strip().lower() in _TRUE


def _csv(name: str, default: str = "") -> List[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _trust_xff() -> bool:
    return os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true"


def _trusted_proxies() -> List[str]:
    return _csv("GUARD_TRUSTED_PROXIES", "127.0.0.1,::1")


def uvicorn_proxy_kwargs() -> dict:
    """Uvicorn options that keep its proxy-header handling in line with the guard.

    Uvicorn rewrites the client address from X-Forwarded-For (FORWARDED_ALLOW_IPS)
    before the app runs, so the guard only ever sees the rewritten address. With the
    guard on, Uvicorn trusts the same proxies as the guard, or none when
    TRUST_X_FORWARDED_FOR is off. With the guard off nothing changes.
    """
    if not is_guard_enabled():
        return {}
    if not _trust_xff():
        return {"proxy_headers": False}
    return {"proxy_headers": True, "forwarded_allow_ips": _trusted_proxies()}


def add_guard_middleware(app) -> None:
    """Mount fastapi-guard when GUARD_ENABLED=true; do nothing (and never import it) otherwise."""
    if not is_guard_enabled():
        return
    try:
        from guard import PureASGISecurityMiddleware, SecurityConfig
        from guard_core.handlers.suspatterns_handler import ALL_DETECTION_CATEGORIES
    except ImportError as exc:
        raise RuntimeError(
            "GUARD_ENABLED=true requires the 'fastapi-guard' package. "
            "Install it with: pip install -r requirements.txt"
        ) from exc

    # X-Forwarded-For is only read when TRUST_X_FORWARDED_FOR=true, and then (depth 1)
    # only its rightmost entry, and only when the TCP peer is in GUARD_TRUSTED_PROXIES
    # (loopback by default). src/auth.get_client_ip() also takes the rightmost entry
    # but does not check the peer. The server entry points pass uvicorn_proxy_kwargs()
    # so that Uvicorn does not rewrite the peer from other proxies first.
    trusted_proxies = tuple(_trusted_proxies()) if _trust_xff() else ()

    config = SecurityConfig(
        enable_redis=False,  # in-memory state, per process; no Redis required
        enable_cors=False,  # CORS stays with CORSMiddleware, which wraps the guard
        security_headers=None,  # do not change response headers
        trusted_proxies=trusted_proxies,
        trusted_proxy_depth=1,
        rate_limit=_int("GUARD_RATE_LIMIT", 300),
        rate_limit_window=_int("GUARD_RATE_LIMIT_WINDOW", 60),
        whitelist=tuple(_csv("GUARD_WHITELIST")) or None,
        blacklist=tuple(_csv("GUARD_BLACKLIST")),
        detection_scan_body=os.getenv("GUARD_SCAN_BODY", "false").strip().lower() in _TRUE,
        passive_mode=os.getenv("GUARD_PASSIVE_MODE", "false").strip().lower() in _TRUE,
        # Browsers send the page address as Referer, and guard-core 4.4.0 flags localhost and LAN addresses in it as ssrf.
        enabled_detection_categories=frozenset(ALL_DETECTION_CATEGORIES) - {"ssrf"},
    )
    app.add_middleware(PureASGISecurityMiddleware, config=config)
    logger.info(
        "fastapi-guard enabled (rate_limit=%s/%ss, allowlist=%s, passive=%s)",
        config.rate_limit,
        config.rate_limit_window,
        bool(config.whitelist),
        config.passive_mode,
    )
