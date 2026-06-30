# -*- coding: utf-8 -*-
"""Live-network drift tests for TwInstitutionalFetcher, gated by @pytest.mark.network.

These hit the REAL TWSE T86 + TPEx OpenAPI endpoints, so they run ONLY in the
non-blocking "Network Smoke" cron (`pytest -m network`). The blocking backend gate
runs `pytest -m "not network"` (scripts/ci_gate.sh), so these never gate a PR.

The offline suite (tests/test_tw_institutional_fetcher.py) pins the parser to frozen
fixtures and therefore cannot detect upstream feed drift; this file is that detector.
Each test is self-contained (one raw fetch + the fetcher, in the same test) so a column
rename is caught LOUD and a narrow connectivity window cannot split-skip two corroborating
tests. Drift fails LOUD; a transport error, non-trading day, or transient blip skips QUIET
so the cron is not noisy. A 200 that is NOT JSON (maintenance page / URL migration) is
DRIFT, not a blip, so it fails — never skipped. Both feeds are public 政府開放資料, no creds.

For the richer human-readable cross-check, see tests/tw_institutional_live_smoke.py.
"""

import os
import sys
import unittest

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_provider.tw_institutional_fetcher import (  # noqa: E402
    TwInstitutionalFetcher,
    _to_int,
    _T86_CORE,
    _T86_CODE,
    _T86_FOREIGN,
    _T86_TRUST,
    _T86_DEALER,
    _T86_TOTAL,
    _T86_URL,
    _TPEX_URL,
    _TPEX_FOREIGN_EXCL,
    _TPEX_TRUST,
    _TPEX_DEALER,
    _TPEX_TOTAL,
    _UA,
)

import requests  # noqa: E402

_HEADERS = {"User-Agent": _UA, "Accept": "application/json"}
_NET_FIELDS = ("foreign_net", "trust_net", "dealer_net", "total_net")


def _fetch_with_retry(fetcher, code, tries=3):
    """Transient upstream blips are real (observed live); retry before giving up."""
    rec = None
    for _ in range(tries):
        rec = fetcher.get_institutional_net(code)
        if rec is not None:
            return rec
    return rec


@pytest.mark.network
class TestTwInstitutionalLiveNetwork(unittest.TestCase):
    """Cron-only smoke: assert the live feeds still match the fetcher's contract."""

    def _get_feed_or_skip(self, url, params=None):
        """Transport error -> skip (can't judge drift from an unreachable feed); a 200
        that is not valid JSON (HTML maintenance page / URL migration) -> fail LOUD."""
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=20)
        except requests.exceptions.RequestException as exc:
            self.skipTest(f"endpoint unreachable: {exc}")
        try:
            return resp.json()
        except ValueError as exc:  # non-JSON body is feed drift, not a transient blip
            self.fail(f"{url} returned non-JSON (maintenance page / URL migration?): {exc}")

    def _assert_record_shape(self, rec, market_label):
        for field in _NET_FIELDS:
            self.assertIsInstance(rec[field], int, f"{field} not an int: {rec[field]!r}")
        self.assertEqual(rec["market"], market_label)
        self.assertEqual(rec["unit"], "shares")
        self.assertTrue(rec["date"].isdigit() and len(rec["date"]) == 8, f"bad date {rec['date']!r}")

    def test_t86_live_columns_and_fetcher_match_raw(self):
        """T86 core columns still named as expected AND the fetcher's parsed net figures
        equal the raw columns for a liquid stock (catches a fabricated fallback total)."""
        payload = self._get_feed_or_skip(
            _T86_URL, {"response": "json", "selectType": "ALLBUT0999"})
        if not isinstance(payload, dict):
            self.fail(f"T86 response not a JSON object: {type(payload).__name__} (feed shape drift)")
        if payload.get("stat") != "OK":
            self.skipTest(f"T86 stat={payload.get('stat')} (likely non-trading day)")
        fields = payload.get("fields") or []
        missing = [name for name in _T86_CORE if name not in fields]
        self.assertEqual(missing, [], f"TWSE T86 core columns renamed/removed: {missing}")

        idx = {name: fields.index(name) for name in fields}
        row = next((r for r in (payload.get("data") or [])
                    if isinstance(r, (list, tuple)) and str(r[idx[_T86_CODE]]).strip() == "2330"), None)
        rec = _fetch_with_retry(TwInstitutionalFetcher(), "2330.TW")
        if rec is None:
            # row present in the raw feed but the fetcher returned None => parse/date drift
            # (the exact fail-open this test exists to catch) -> FAIL, never a soft-skip.
            if row is not None:
                self.fail("2330 is present in the raw T86 feed but the fetcher returned None after "
                          "retries — parse/date drift (e.g. a column/date-format change)")
            self.skipTest("2330.TW None and absent from the raw feed (transient / suspended)")
        if row is None:
            self.skipTest("2330 not in the raw T86 snapshot (cross-check unavailable)")
        self._assert_record_shape(rec, "上市")
        self.assertEqual(rec["foreign_net"], _to_int(row[idx[_T86_FOREIGN]]))
        self.assertEqual(rec["trust_net"], _to_int(row[idx[_T86_TRUST]]))
        self.assertEqual(rec["dealer_net"], _to_int(row[idx[_T86_DEALER]]))
        # raw total present (it is in _T86_CORE, asserted above) -> the fetcher must echo it,
        # never the foreign+trust+dealer fallback synthesised when the column is absent.
        self.assertEqual(rec["total_net"], _to_int(row[idx[_T86_TOTAL]]))

    def test_tpex_live_columns_and_fetcher_match_raw(self):
        """TPEx core keys still present AND the fetcher's parsed net figures equal the raw
        columns for a liquid stock (catches a fabricated fallback total)."""
        arr = self._get_feed_or_skip(_TPEX_URL)
        if not isinstance(arr, list):
            self.fail(f"TPEx response not a JSON array: {type(arr).__name__} (feed shape drift)")
        if not arr:
            self.skipTest("TPEx returned an empty list (likely non-trading day)")
        if not isinstance(arr[0], dict):
            self.fail(f"TPEx arr[0] not a dict: {type(arr[0]).__name__} (feed shape drift)")
        core_keys = (_TPEX_FOREIGN_EXCL, _TPEX_TRUST, _TPEX_DEALER, _TPEX_TOTAL)
        missing = [k for k in core_keys if k not in arr[0]]
        self.assertEqual(missing, [], f"TPEx core keys renamed/removed: {missing}")

        raw = next((r for r in arr
                    if isinstance(r, dict) and str(r.get("SecuritiesCompanyCode", "")).strip() == "5483"), None)
        rec = _fetch_with_retry(TwInstitutionalFetcher(), "5483.TWO")
        if rec is None:
            # row present in the raw feed but the fetcher returned None => parse/date drift
            # (e.g. a 民國 date-format change _parse_tpex_row can't convert) -> FAIL, not soft-skip.
            if raw is not None:
                self.fail("5483 is present in the raw TPEx feed but the fetcher returned None after "
                          "retries — parse/date drift (e.g. a 民國 date-format change)")
            self.skipTest("5483.TWO None and absent from the raw feed (transient / suspended)")
        if raw is None:
            self.skipTest("5483 not in the raw TPEx snapshot (cross-check unavailable)")
        self._assert_record_shape(rec, "上櫃")
        self.assertEqual(rec["foreign_net"], _to_int(raw.get(_TPEX_FOREIGN_EXCL)))
        self.assertEqual(rec["trust_net"], _to_int(raw.get(_TPEX_TRUST)))
        self.assertEqual(rec["dealer_net"], _to_int(raw.get(_TPEX_DEALER)))
        self.assertEqual(rec["total_net"], _to_int(raw.get(_TPEX_TOTAL)))


if __name__ == "__main__":
    unittest.main()
