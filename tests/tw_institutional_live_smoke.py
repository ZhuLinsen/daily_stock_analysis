# -*- coding: utf-8 -*-
"""Manual live smoke for TwInstitutionalFetcher (NOT run by pytest — no test_ prefix).

The offline unit tests (tests/test_tw_institutional_fetcher.py) pin the parser to
FROZEN fixtures, so by construction they can never notice an upstream feed change.
This script hits the REAL TWSE T86 + TPEx OpenAPI endpoints to surface that drift:
an endpoint move, a core-column rename (which makes the fetcher fail-open SILENTLY,
returning None for every stock), a 民國->ISO date-format switch, or a schema change.
Both feeds are public 政府開放資料 — no credentials, no key.

Skip vs drift (a drift detector must not report a feed change as "PASS"):
    - A transport error (endpoint unreachable / SSL / timeout) -> SOFT SKIP: you cannot
      detect drift from an unreachable feed.
    - A non-trading-day response (T86 stat != "OK" / empty TPEx list) -> SOFT SKIP.
    - A 200 that is NOT valid JSON of the expected shape (an HTML maintenance page or a
      URL migration) -> DRIFT, reported LOUD ([x], exit 1). This is exactly the class of
      endpoint change the script exists to catch, so it must never be swallowed as a blip.
    - A core / foreign-dealer column rename -> DRIFT, reported LOUD.

What each level asserts (for stocks present in the feed that day):
    the fetcher's foreign/trust/dealer/total equal the raw columns it claims to read, and
    the ALWAYS-TRUE reconstruction `total == foreign + foreign_dealer + trust + dealer`
    holds (the 3-term identity `total == foreign + trust + dealer` only holds when the
    foreign-dealer sub-component is 0, so this reads the raw foreign-dealer column instead).

Usage:
    python tests/tw_institutional_live_smoke.py                 # default 2330.TW 0050.TW 5483.TWO 6488.TWO
    python tests/tw_institutional_live_smoke.py 2330.TW 5483.TWO  # custom codes

Exit code 0 = all checks pass / soft-skipped; 1 = a drift / parse mismatch was detected.
"""

import argparse
import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _PROJECT_ROOT)

try:  # Windows cp950 console mangles the Chinese feed messages / 上市·上櫃 labels
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - cosmetic only; never block the smoke on console encoding
    pass

import requests  # noqa: E402

from data_provider.tw_institutional_fetcher import (  # noqa: E402
    TwInstitutionalFetcher,
    _to_int,
    _T86_URL,
    _T86_CORE,
    _T86_CODE,
    _T86_FOREIGN,
    _T86_TRUST,
    _T86_DEALER,
    _T86_TOTAL,
    _TPEX_URL,
    _TPEX_FOREIGN_EXCL,
    _TPEX_TRUST,
    _TPEX_DEALER,
    _TPEX_TOTAL,
    _UA,
)

# Raw foreign-dealer columns — NOT read by the fetcher (foreign deliberately excludes
# them), but needed here to verify the always-true total reconstruction. A rename of
# these is drift relative to the reconstruction check, so their presence is asserted.
_T86_FOREIGN_DEALER = "外資自營商買賣超股數"
_TPEX_FOREIGN_DEALER = "ForeignDealers-Difference"

_HEADERS = {"User-Agent": _UA, "Accept": "application/json"}


def _print_header(title: str) -> None:
    print(f"\n{'=' * 64}")
    print(f"  {title}")
    print(f"{'=' * 64}")


def _check(label: str, ok: bool, detail: str = "") -> bool:
    mark = "[+]" if ok else "[x]"
    suffix = f"  {detail}" if detail else ""
    print(f"  {mark} {label}{suffix}")
    return ok


def _get_feed(url: str, params=None):
    """Fetch + JSON-parse a feed, classifying the outcome for a drift detector.

    Returns (payload, status, message) where status is one of:
      'ok'    -> payload is the parsed JSON
      'skip'  -> transport error; cannot judge drift from an unreachable feed
      'drift' -> a 200 that is not valid JSON (HTML maintenance page / URL migration)
    """
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=20)
    except requests.exceptions.RequestException as exc:
        return None, "skip", f"endpoint unreachable: {exc}"
    try:
        return resp.json(), "ok", ""
    except ValueError as exc:  # json.JSONDecodeError subclasses ValueError; non-JSON body = drift
        return None, "drift", f"non-JSON response (maintenance page / URL migration?): {exc}"


def _fetch_with_retry(fetcher: TwInstitutionalFetcher, code: str, tries: int = 3):
    """Transient upstream blips are real (observed live: a single TPEx call returning
    empty, the next succeeding). Retry before treating a None as a hard miss."""
    rec = None
    for _ in range(tries):
        rec = fetcher.get_institutional_net(code)
        if rec is not None:
            return rec
    return rec


def _cross_check_record(rec: dict, raw_foreign, raw_trust, raw_dealer, raw_total,
                        raw_foreign_dealer) -> bool:
    """Assert the fetcher parsed the columns it claims to, and the total reconstructs.

    raw_foreign_dealer may be None when the foreign-dealer column is renamed/absent (a
    drift already flagged up-front) or genuinely missing for this stock — in that case the
    always-true reconstruction cannot be computed, so it is reported as skipped rather than
    silently passed with a fabricated 0; the other four column cross-checks still run.
    """
    ok = True
    ok &= _check("foreign_net == raw foreign(ex-dealer) col", rec["foreign_net"] == raw_foreign,
                 f"fetcher={rec['foreign_net']:,} raw={raw_foreign}")
    ok &= _check("trust_net == raw trust col", rec["trust_net"] == raw_trust,
                 f"fetcher={rec['trust_net']:,} raw={raw_trust}")
    ok &= _check("dealer_net == raw dealer col", rec["dealer_net"] == raw_dealer,
                 f"fetcher={rec['dealer_net']:,} raw={raw_dealer}")
    ok &= _check("total_net == raw total col", rec["total_net"] == raw_total,
                 f"fetcher={rec['total_net']:,} raw={raw_total}")
    if raw_foreign_dealer is None:
        print("  [~] total reconstruction skipped — foreign-dealer value unavailable for this stock")
        return ok
    recon = rec["foreign_net"] + raw_foreign_dealer + rec["trust_net"] + rec["dealer_net"]
    ok &= _check("total == foreign + foreign_dealer + trust + dealer (always-true)",
                 recon == rec["total_net"],
                 f"recon={recon:,} total={rec['total_net']:,} (foreign_dealer={raw_foreign_dealer:,})")
    return ok


def level_twse(fetcher: TwInstitutionalFetcher, codes) -> bool:
    _print_header(f"Level TWSE / T86 (上市): {codes or '(none)'}")
    payload, status, msg = _get_feed(_T86_URL, {"response": "json", "selectType": "ALLBUT0999"})
    if status == "skip":
        print(f"  [!] T86 {msg} — soft skip")
        return True
    if status == "drift":
        return _check("T86 returned JSON", False, msg)
    if not isinstance(payload, dict):
        return _check("T86 response is a JSON object", False, f"got {type(payload).__name__} — feed shape drift")
    if payload.get("stat") != "OK":
        print(f"  [!] T86 stat={payload.get('stat')} (likely non-trading day) — soft skip")
        return True

    fields = payload.get("fields") or []
    missing = [n for n in _T86_CORE if n not in fields]
    ok = _check("T86 core column names present", not missing,
                f"missing={missing}" if missing else f"all {len(_T86_CORE)} present")
    if missing:
        print("  -> a renamed/removed core column makes the fetcher fail-open SILENTLY")
        return ok  # core rename => fetcher fail-opens (rec=None); stop before indexing absent columns
    fd_present = _T86_FOREIGN_DEALER in fields
    ok &= _check("T86 foreign-dealer column present (for reconstruction)", fd_present,
                 "" if fd_present else f"'{_T86_FOREIGN_DEALER}' renamed/removed — reconstruction unavailable")

    idx = {n: fields.index(n) for n in fields}
    fd_idx = idx.get(_T86_FOREIGN_DEALER)
    rows = {str(r[idx[_T86_CODE]]).strip(): r for r in (payload.get("data") or [])
            if isinstance(r, (list, tuple)) and _T86_CODE in idx}

    for code in codes:
        print(f"\n  -- {code} --")
        base = code.upper().rsplit(".", 1)[0]
        raw = rows.get(base)
        rec = _fetch_with_retry(fetcher, code)
        if rec is None:
            # raw row present but the fetcher returned None => a parse/date drift the fetcher
            # fail-opened on (e.g. a 民國->ISO date switch) — fail LOUD, never a soft-skip
            # (that conflation is exactly what would let the drift this script exists to catch slip).
            if raw is not None:
                ok &= _check(f"{base}: fetcher must parse a row that exists in the raw feed", False,
                             "raw row present but get_institutional_net() returned None after retries — parse/date drift")
            else:
                print(f"  [!] {base} not in T86 feed today — soft skip")
            continue
        if raw is None:
            print(f"  [!] {base} parsed by the fetcher but absent from this raw snapshot — soft-skip cross-check")
            continue
        fd_val = _to_int(raw[fd_idx]) if (fd_idx is not None and fd_idx < len(raw)) else None
        ok &= _cross_check_record(
            rec,
            _to_int(raw[idx[_T86_FOREIGN]]), _to_int(raw[idx[_T86_TRUST]]),
            _to_int(raw[idx[_T86_DEALER]]), _to_int(raw[idx[_T86_TOTAL]]), fd_val,
        )
    return ok


def level_tpex(fetcher: TwInstitutionalFetcher, codes) -> bool:
    _print_header(f"Level TPEx (上櫃): {codes or '(none)'}")
    arr, status, msg = _get_feed(_TPEX_URL)
    if status == "skip":
        print(f"  [!] TPEx {msg} — soft skip")
        return True
    if status == "drift":
        return _check("TPEx returned JSON", False, msg)
    if not isinstance(arr, list):
        return _check("TPEx response is a JSON array", False, f"got {type(arr).__name__} — feed shape drift")
    if not arr:
        print("  [!] TPEx returned an empty list (likely non-trading day) — soft skip")
        return True

    sample = arr[0]
    core_keys = (_TPEX_FOREIGN_EXCL, _TPEX_TRUST, _TPEX_DEALER, _TPEX_TOTAL)
    missing = [k for k in core_keys if k not in sample]
    ok = _check("TPEx core column keys present", not missing,
                f"missing={missing}" if missing else f"all {len(core_keys)} present")
    if missing:
        print("  -> a renamed/removed core key makes the fetcher fail-open SILENTLY")
    fd_present = _TPEX_FOREIGN_DEALER in sample
    ok &= _check("TPEx foreign-dealer key present (for reconstruction)", fd_present,
                 "" if fd_present else f"'{_TPEX_FOREIGN_DEALER}' renamed/removed — reconstruction unavailable")

    by_code = {str(r.get("SecuritiesCompanyCode", "")).strip(): r for r in arr if isinstance(r, dict)}
    for code in codes:
        print(f"\n  -- {code} --")
        base = code.upper().rsplit(".", 1)[0]
        raw = by_code.get(base)
        rec = _fetch_with_retry(fetcher, code)
        if rec is None:
            # raw row present but fetcher None => parse/date drift (e.g. a 民國 date-format change
            # _parse_tpex_row can't convert) — fail LOUD, not a soft-skip.
            if raw is not None:
                ok &= _check(f"{base}: fetcher must parse a row that exists in the raw feed", False,
                             "raw row present but get_institutional_net() returned None after retries — parse/date drift")
            else:
                print(f"  [!] {base} not in TPEx feed today — soft skip")
            continue
        if raw is None:
            print(f"  [!] {base} parsed by the fetcher but absent from this raw snapshot — soft-skip cross-check")
            continue
        fd_val = _to_int(raw.get(_TPEX_FOREIGN_DEALER)) if fd_present else None
        ok &= _cross_check_record(
            rec,
            _to_int(raw.get(_TPEX_FOREIGN_EXCL)), _to_int(raw.get(_TPEX_TRUST)),
            _to_int(raw.get(_TPEX_DEALER)), _to_int(raw.get(_TPEX_TOTAL)), fd_val,
        )
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="TwInstitutionalFetcher live smoke (real TWSE/TPEx)")
    parser.add_argument("codes", nargs="*",
                        default=["2330.TW", "0050.TW", "5483.TWO", "6488.TWO"],
                        help="stock codes with .TW / .TWO suffix")
    args = parser.parse_args()
    codes = args.codes or ["2330.TW", "0050.TW", "5483.TWO", "6488.TWO"]
    tw = [c for c in codes if c.upper().endswith(".TW")]
    two = [c for c in codes if c.upper().endswith(".TWO")]

    print("TwInstitutionalFetcher live smoke (public TWSE T86 + TPEx OpenAPI, no creds)")
    fetcher = TwInstitutionalFetcher()
    results = {"TWSE": level_twse(fetcher, tw), "TPEx": level_tpex(fetcher, two)}

    _print_header("Summary")
    for name, passed in results.items():
        print(f"  {'[+]' if passed else '[x]'} {name}: {'PASS' if passed else 'FAIL'}")
    all_ok = all(results.values())
    print(f"\n  {'All checks passed.' if all_ok else 'DRIFT/MISMATCH detected — see [x] above.'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
