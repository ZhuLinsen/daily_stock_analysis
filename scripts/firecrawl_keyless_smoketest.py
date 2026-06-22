#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Firecrawl keyless smoke test.

Goal: verify whether the Firecrawl Python SDK can run a real `search` WITHOUT an
API key (Firecrawl "Keyless", launched 2026-06-16: 1,000 free credits/month, no
account). Keyless is IP-reputation gated, so this must be run from a clean
(residential) IP — datacenter / CI / VPN IPs are refused with a 403.

Key finding this script encodes:
  - The top-level `firecrawl.Firecrawl` wrapper CANNOT go keyless: its constructor
    eagerly builds a v1 client that raises `ValueError: No API key provided`.
  - The v2 `firecrawl.v2.client.FirecrawlClient` CAN: with no key it simply omits
    the `Authorization` header (HttpClient only adds it `if self.api_key`).
  - So the correct keyless construction is `FirecrawlClient()` with NO key — never
    a dummy/placeholder string (a bogus token gets a 401 "Invalid token").

Usage:
    # keyless (the thing we're verifying) — make sure FIRECRAWL_API_KEY is unset
    python scripts/firecrawl_keyless_smoketest.py

    # keyed comparison (optional)
    FIRECRAWL_API_KEY=fc-... python scripts/firecrawl_keyless_smoketest.py

Exit code is 0 only if a search actually returns results.
"""

import os
import sys
import warnings

warnings.filterwarnings("ignore")

QUERY = "Alibaba stock news"


def _results_from(response):
    """Pull the result list out of the v2 SearchData (news preferred, then web)."""
    for bucket in ("news", "web"):
        items = getattr(response, bucket, None)
        if items:
            return items
    return []


def run_keyless():
    print("=" * 70)
    print("KEYLESS test — FirecrawlClient() with NO api key")
    print("=" * 70)

    # Make sure no key leaks in from the environment for the keyless run.
    had_env_key = bool(os.environ.get("FIRECRAWL_API_KEY"))
    if had_env_key:
        print("note: FIRECRAWL_API_KEY is set in env — unsetting it for the keyless run")
        os.environ.pop("FIRECRAWL_API_KEY", None)

    try:
        from firecrawl.v2.client import FirecrawlClient
    except ImportError as e:
        print(f"FAIL: cannot import FirecrawlClient ({e}). Is firecrawl-py installed?")
        return False

    client = FirecrawlClient()  # no key, no dummy — true keyless
    print("constructed FirecrawlClient() with no key: OK")

    try:
        resp = client.search(QUERY, limit=2, sources=[{"type": "news"}])
    except Exception as e:
        msg = str(e)
        print(f"\nsearch raised {type(e).__name__}: {msg[:300]}")
        if "IP address looks suspicious" in msg or "WebsiteNotSupported" in type(e).__name__:
            print(
                "\n--> Keyless reached the API but THIS IP is not trusted.\n"
                "    Re-run from a clean/residential IP, or use an API key.\n"
                "    (This confirms the keyless code path is correct — no auth header sent.)"
            )
        elif "401" in msg or "Unauthorized" in msg:
            print("\n--> Unexpected 401 — a token was sent. Should be sending NO auth header.")
        return False

    items = _results_from(resp)
    print(f"\nKEYLESS SEARCH SUCCEEDED — {len(items)} result(s):")
    for i, it in enumerate(items, 1):
        print(f"  {i}. {getattr(it, 'title', None)}")
        print(f"     {getattr(it, 'url', None)}")
        summ = getattr(it, "summary", None) or getattr(it, "description", None) or ""
        print(f"     {str(summ)[:160]}")
    return bool(items)


def run_keyed():
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        print("\n(skipping keyed test — FIRECRAWL_API_KEY not set)")
        return None

    print("\n" + "=" * 70)
    print("KEYED test — Firecrawl(api_key=...) via the top-level wrapper")
    print("=" * 70)
    try:
        from firecrawl import Firecrawl
        app = Firecrawl(api_key=key)
        resp = app.search(QUERY, limit=2, sources=[{"type": "news"}])
        items = _results_from(resp)
        print(f"KEYED SEARCH SUCCEEDED — {len(items)} result(s)")
        return bool(items)
    except Exception as e:
        print(f"KEYED search failed: {type(e).__name__}: {str(e)[:200]}")
        return False


if __name__ == "__main__":
    keyless_ok = run_keyless()
    run_keyed()
    print("\n" + "-" * 70)
    print(f"RESULT: keyless {'WORKS from this IP' if keyless_ok else 'did NOT return results from this IP'}")
    sys.exit(0 if keyless_ok else 1)
