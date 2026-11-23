#!/usr/bin/env python3
"""Generate the Longbridge SDK OAuth token cache for headless runtimes."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def _default_client_id() -> str:
    return (
        os.getenv("LONGBRIDGE_OAUTH_CLIENT_ID")
        or os.getenv("LONGBRIDGE_APP_KEY")
        or ""
    ).strip()


def _token_cache_path(client_id: str) -> Path:
    return Path.home() / ".longbridge" / "openapi" / "tokens" / client_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Longbridge OAuth authorization and persist the SDK token cache. "
            "Use this once on an interactive machine before schedule/Docker/GitHub Actions runs."
        )
    )
    parser.add_argument(
        "--client-id",
        default=_default_client_id(),
        help="OAuth client_id. Defaults to LONGBRIDGE_OAUTH_CLIENT_ID, then LONGBRIDGE_APP_KEY.",
    )
    parser.add_argument(
        "--verify-symbol",
        default="",
        help="Optional Longbridge symbol such as AAPL.US or 700.HK to verify QuoteContext after auth.",
    )
    args = parser.parse_args()

    client_id = (args.client_id or "").strip()
    if not client_id:
        parser.error("missing --client-id or LONGBRIDGE_OAUTH_CLIENT_ID")

    try:
        from longbridge.openapi import Config, OAuthBuilder, QuoteContext
    except Exception as exc:
        raise SystemExit(
            "longbridge SDK is not installed. Run `pip install -r requirements.txt` first."
        ) from exc

    def show_url(url: str) -> None:
        print(f"Open this URL to authorize Longbridge OAuth:\n{url}\n")

    oauth = OAuthBuilder(client_id).build(show_url)
    config = Config.from_oauth(oauth)

    if args.verify_symbol:
        ctx = QuoteContext(config)
        quote = ctx.quote([args.verify_symbol])[0]
        print(f"Verified {args.verify_symbol}: {getattr(quote, 'last_done', None)}")

    token_cache = _token_cache_path(client_id)
    print(f"OAuth token cache: {token_cache}")
    print(
        "For GitHub Actions, store the base64 of this file as "
        "`LONGBRIDGE_OAUTH_TOKEN_CACHE_B64`."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
