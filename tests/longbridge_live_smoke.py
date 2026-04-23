# -*- coding: utf-8 -*-
"""
Manual smoke script for Longbridge integration (NOT run by pytest — no test_ prefix).

Usage:
    # 1. Copy .env.example -> .env and fill LONGBRIDGE_* (.env.example is never loaded by the app)
    # 2. Or set env vars in the shell, e.g. set LONGBRIDGE_APP_KEY=...

    # 3. Run (Python 3.10+), from repo root or tests/ both OK
    python tests/longbridge_live_smoke.py

    # 4. Test with specific stock
    python tests/longbridge_live_smoke.py TSLA

    # 5. One-off credentials (prefer .env; args may appear in shell history)
    python tests/longbridge_live_smoke.py AAPL --lb-app-key ... --lb-app-secret ... --lb-access-token ...

Runs three levels:
    Level 1: LongbridgeFetcher standalone  (does LB API work?)
    Level 2: DataFetcherManager supplement  (does yfinance + LB merge work?)
    Level 3: Full pipeline quote            (does get_realtime_quote return filled data?)
"""

import argparse
import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _PROJECT_ROOT)

# Load project-root .env (not CWD). Running from tests/ would otherwise miss ../.env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
except ImportError:
    pass


def _print_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def _print_field(label: str, value, ok_if_not_none=True):
    status = "OK" if (value is not None and value != 0) else "MISSING"
    mark = "[+]" if status == "OK" else "[x]"
    if ok_if_not_none:
        print(f"  {mark} {label:20s}: {value}  [{status}]")
    else:
        print(f"     {label:20s}: {value}")


def run_level1_standalone(stock_code: str):
    """LongbridgeFetcher in isolation."""
    _print_header(f"Level 1: LongbridgeFetcher standalone ({stock_code})")

    from data_provider.longbridge_fetcher import LongbridgeFetcher

    fetcher = LongbridgeFetcher()

    if not fetcher._is_available():
        print("  [x] Longbridge credentials not configured!")
        print("  Set LONGBRIDGE_APP_KEY, LONGBRIDGE_APP_SECRET, LONGBRIDGE_ACCESS_TOKEN")
        return False

    print("  [+] Credentials found")

    quote = fetcher.get_realtime_quote(stock_code)
    if quote is None:
        print(f"  [x] get_realtime_quote({stock_code}) returned None")
        return False

    print(f"\n  Quote for {stock_code} (source: {quote.source.value}):")
    _print_field("price", quote.price)
    _print_field("change_pct", f"{quote.change_pct}%" if quote.change_pct else None)
    _print_field("volume", quote.volume)
    _print_field("amount (turnover)", quote.amount)
    _print_field("volume_ratio", quote.volume_ratio)
    _print_field("turnover_rate", f"{quote.turnover_rate}%" if quote.turnover_rate else None)
    _print_field("pe_ratio", quote.pe_ratio)
    _print_field("pb_ratio", quote.pb_ratio)
    _print_field("total_mv", quote.total_mv)
    _print_field("name", quote.name, ok_if_not_none=False)

    critical_fields = [quote.volume_ratio, quote.turnover_rate, quote.pe_ratio]
    filled = sum(1 for f in critical_fields if f is not None and f != 0)
    print(f"\n  Result: {filled}/3 critical fields filled (volume_ratio, turnover_rate, pe_ratio)")
    return filled >= 2


def run_level2_supplement(stock_code: str):
    """YFinance + Longbridge supplement flow."""
    _print_header(f"Level 2: YFinance + Longbridge supplement ({stock_code})")

    from data_provider.base import DataFetcherManager

    manager = DataFetcherManager()

    # Step 1: yfinance only
    yf_quote = None
    for fetcher in manager._get_fetchers_snapshot():
        if fetcher.name == "YfinanceFetcher":
            try:
                yf_quote = fetcher.get_realtime_quote(stock_code)
            except Exception as e:
                print(f"  [x] YFinance failed: {e}")
            break

    if yf_quote is None:
        print(f"  [x] YFinance returned None for {stock_code}")
    else:
        print(f"  YFinance quote:")
        _print_field("price", yf_quote.price)
        _print_field("volume_ratio", yf_quote.volume_ratio)
        _print_field("turnover_rate", yf_quote.turnover_rate)
        _print_field("pe_ratio", yf_quote.pe_ratio)

    # Snapshot before supplement — merge mutates primary_quote in place, so comparing
    # after would wrongly show "no new fields".
    _supp_fields = ["volume_ratio", "turnover_rate", "pe_ratio", "pb_ratio", "total_mv"]
    yf_snapshot = None
    if yf_quote is not None:
        yf_snapshot = {f: getattr(yf_quote, f, None) for f in _supp_fields}

    # Step 2: Supplement from Longbridge
    result = manager._supplement_from_longbridge(stock_code, yf_quote)
    if result is None:
        print(f"\n  [x] Supplement returned None")
        return False

    print(f"\n  After Longbridge supplement:")
    _print_field("price", result.price)
    _print_field("volume_ratio", result.volume_ratio)
    _print_field("turnover_rate", result.turnover_rate)
    _print_field("pe_ratio", result.pe_ratio)
    _print_field("pb_ratio", result.pb_ratio)
    _print_field("total_mv", result.total_mv)

    newly_filled = []
    if yf_snapshot is not None:
        for field in _supp_fields:
            old = yf_snapshot.get(field)
            new = getattr(result, field, None)
            if old is None and new is not None:
                newly_filled.append(field)
    if newly_filled:
        print(f"\n  [+] Longbridge filled {len(newly_filled)} fields: {newly_filled}")
    else:
        print(f"\n  [!] No new fields filled (LB may also lack data or creds missing)")
    return True


def run_level3_full_pipeline(stock_code: str):
    """Full get_realtime_quote path."""
    _print_header(f"Level 3: Full DataFetcherManager.get_realtime_quote ({stock_code})")

    from data_provider.base import DataFetcherManager

    manager = DataFetcherManager()
    quote = manager.get_realtime_quote(stock_code)

    if quote is None:
        print(f"  [x] get_realtime_quote({stock_code}) returned None")
        return False

    print(f"  source: {quote.source.value}")
    _print_field("price", quote.price)
    _print_field("volume_ratio", quote.volume_ratio)
    _print_field("turnover_rate", quote.turnover_rate)
    _print_field("pe_ratio", quote.pe_ratio)
    _print_field("total_mv", quote.total_mv)

    missing = []
    for field in ["volume_ratio", "turnover_rate", "pe_ratio"]:
        if getattr(quote, field, None) is None:
            missing.append(field)

    if missing:
        print(f"\n  [!] Still missing: {missing}")
    else:
        print(f"\n  [+] All critical fields present!")
    return len(missing) == 0


def _apply_cli_credentials(args: argparse.Namespace) -> None:
    """Set LONGBRIDGE_* from CLI if all three are provided (before importing app config)."""
    if args.lb_app_key and args.lb_app_secret and args.lb_access_token:
        os.environ["LONGBRIDGE_APP_KEY"] = args.lb_app_key
        os.environ["LONGBRIDGE_APP_SECRET"] = args.lb_app_secret
        os.environ["LONGBRIDGE_ACCESS_TOKEN"] = args.lb_access_token
    elif any((args.lb_app_key, args.lb_app_secret, args.lb_access_token)):
        print(
            "Warning: --lb-app-key / --lb-app-secret / --lb-access-token must be used together; "
            "ignoring partial flags.",
            file=sys.stderr,
        )


def main():
    parser = argparse.ArgumentParser(description="Longbridge integration smoke test")
    parser.add_argument(
        "stock",
        nargs="?",
        default="AAPL",
        help="Stock code (e.g. AAPL, 00700, HK00700)",
    )
    parser.add_argument(
        "--lb-app-key",
        "--lb-appkey",
        dest="lb_app_key",
        default=None,
        help="LONGBRIDGE_APP_KEY",
    )
    parser.add_argument("--lb-app-secret", dest="lb_app_secret", default=None, help="LONGBRIDGE_APP_SECRET")
    parser.add_argument(
        "--lb-access-token",
        dest="lb_access_token",
        default=None,
        help="LONGBRIDGE_ACCESS_TOKEN",
    )
    args = parser.parse_args()
    stock = (args.stock or "AAPL").strip()

    _apply_cli_credentials(args)

    print(f"Longbridge Integration Smoke Test")
    print(f"Stock: {stock}")

    has_creds = bool(
        os.getenv("LONGBRIDGE_APP_KEY")
        and os.getenv("LONGBRIDGE_APP_SECRET")
        and os.getenv("LONGBRIDGE_ACCESS_TOKEN")
    )
    print(f"Credentials: {'configured' if has_creds else 'NOT configured'}")

    results = {}
    results["L1"] = run_level1_standalone(stock)
    results["L2"] = run_level2_supplement(stock)
    results["L3"] = run_level3_full_pipeline(stock)

    _print_header("Summary")
    for level, passed in results.items():
        mark = "[+]" if passed else "[x]"
        print(f"  {mark} {level}: {'PASS' if passed else 'FAIL'}")

    if all(results.values()):
        print(f"\n  All tests passed! Data pipeline is working.")
    elif not has_creds:
        print(f"\n  Set LONGBRIDGE_* env vars or pass --lb-* flags and re-run.")


if __name__ == "__main__":
    main()
