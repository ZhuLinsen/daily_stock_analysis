# -*- coding: utf-8 -*-
"""TwInstitutionalFetcher — Taiwan 三大法人 (institutional-investor) daily net buy/sell.

Data-layer only, ``tw``-only, strictly additive. This module is a self-contained
data-access building block: it fetches, parses, caches and fail-opens. It is NOT
wired into the analysis report / Web / scoring path — that is a deliberate
follow-up (per #1777). It does not touch the existing A-share / HK / US / JP / KR
flows in ``data_provider/base.py``.

Sources (政府開放資料, 政府資料開放授權條款第 1 版 / OGDL v1, commercial-safe, no key):
  - 上市 TWSE T86 「三大法人買賣超日報」 (per-stock), legacy RWD JSON endpoint
    https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date=YYYYMMDD&selectType=ALLBUT0999
    (date is 西元 ``YYYYMMDD``; numeric values are comma-formatted strings)
  - 上櫃 TPEx ``tpex_3insti_daily_trading``, OpenAPI
    https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading
    (date is 民國 ``1150626``; numeric values are plain integer strings)

Fail-open contract: any network error, rate-limit, empty response, unexpected
shape or missing field returns ``None`` (no data) — it never raises into the
caller, so the analysis main flow is never interrupted.

Units are **shares (股)**, not lots (張). Buy/sell-net signs are preserved
(negative = net sell).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
_TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# TWSE T86 core column NAMES. Read by name (not a fixed index) so a TWSE column
# rename / reorder fails open instead of silently shipping misaligned numbers.
# foreign = 外陸資 (NOT incl 外資自營商): foreign-dealer sits outside the 外資
# category in the official 三大法人 total.
_T86_CODE = "證券代號"
_T86_FOREIGN = "外陸資買賣超股數(不含外資自營商)"
_T86_TRUST = "投信買賣超股數"
_T86_DEALER = "自營商買賣超股數"
_T86_TOTAL = "三大法人買賣超股數"
_T86_CORE = (_T86_CODE, _T86_FOREIGN, _T86_TRUST, _T86_DEALER, _T86_TOTAL)

# TPEx OpenAPI column keys (verified live 2026-06; note the inconsistent spacing in
# the official feed). foreign = dealer-excluded, matching TotalDifference =
# foreign-excl + trust + dealer.
_TPEX_FOREIGN_EXCL = (
    "Foreign Investors include Mainland Area Investors "
    "(Foreign Dealers excluded)-Difference"
)
_TPEX_TRUST = "SecuritiesInvestmentTrustCompanies-Difference"
_TPEX_DEALER = "Dealers-Difference"
_TPEX_TOTAL = "TotalDifference"


def _to_int(value: Any) -> Optional[int]:
    """Parse a TWSE/TPEx numeric cell to int, preserving sign.

    Handles comma grouping (T86) and plain ints (TPEx). Empty / ``--`` / ``-`` /
    non-numeric -> ``None`` (treated as missing, never a fabricated 0).
    """
    try:
        text = str(value).replace(",", "").replace(" ", "").strip()
    except (TypeError, ValueError):
        return None
    if text in ("", "-", "--", "—"):
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def minguo_to_ad(date_str: Any) -> Optional[str]:
    """Convert a TPEx 民國 date ``YYYMMDD`` (e.g. ``1150626``) to 西元 ``YYYYMMDD``.

    ``1150626`` -> ``20260626`` (民國 115 + 1911 = 西元 2026). Returns ``None`` for
    anything that is not a 7-digit 民國 date, so a format change fails open.
    """
    text = str(date_str).strip()
    if not (text.isdigit() and len(text) == 7):
        return None
    return f"{int(text[:3]) + 1911}{text[3:]}"


class TwInstitutionalFetcher:
    """Fetch Taiwan per-stock 三大法人 net buy/sell, ``.TW`` (上市) / ``.TWO`` (上櫃) only."""

    name = "TwInstitutionalFetcher"

    def __init__(
        self,
        *,
        cache_ttl_seconds: int = 900,
        min_request_interval: float = 1.8,
        timeout: int = 15,
    ) -> None:
        # Whole-market single-day cache keyed by (market, ad_date); filtered per stock.
        self._cache: Dict[Any, Dict[str, dict]] = {}
        self._cache_at: Dict[Any, float] = {}
        self._cache_ttl = cache_ttl_seconds
        self._timeout = timeout
        # TWSE T86 RWD endpoint has an informal ~3 req / 5 s ban; throttle requests.
        self._min_interval = min_request_interval
        self._last_request_at = 0.0
        self._lock = threading.Lock()
        self._throttle_lock = threading.Lock()
        # One lock per unique (market, ad_date) key; bounded by tw markets x
        # distinct dates queried -- low thousands at most, negligible memory.
        self._inflight: Dict[Any, threading.Lock] = {}

    # ------------------------------------------------------------------ public
    def get_institutional_net(
        self, stock_code: str, date: Optional[str] = None
    ) -> Optional[dict]:
        """Return the normalized 三大法人 record for one TW stock, or ``None``.

        ``stock_code`` must carry an explicit ``.TW`` / ``.TWO`` suffix; a bare or
        non-TW code returns ``None`` (not applicable). ``date`` (西元 ``YYYYMMDD``)
        only applies to 上市/T86; 上櫃/TPEx OpenAPI serves the latest trading day.
        Fail-open: any error returns ``None``.
        """
        market = self._market_of(stock_code)
        if market is None:
            return None
        base = self._base_code(stock_code)
        try:
            table = self._whole_market(market, date)
        except Exception as exc:  # noqa: BLE001 - fail-open by contract
            logger.info(
                "[tw-inst] fetch failed market=%s code=%s: %s", market, stock_code, exc
            )
            return None
        if not table:
            return None
        return table.get(base)

    # ------------------------------------------------------------------ routing
    @staticmethod
    def _market_of(stock_code: Any) -> Optional[str]:
        upper = str(stock_code or "").strip().upper()
        if upper.endswith(".TWO"):
            return "tpex"
        if upper.endswith(".TW"):
            return "twse"
        return None

    @staticmethod
    def _base_code(stock_code: Any) -> str:
        return str(stock_code or "").strip().upper().rsplit(".", 1)[0]

    @staticmethod
    def _norm_ad_date(date: Any) -> Optional[str]:
        if not date:
            return None
        text = str(date).strip().replace("-", "").replace("/", "")
        return text if (text.isdigit() and len(text) == 8) else None

    # -------------------------------------------------- whole-market cached fetch
    def _whole_market(self, market: str, date: Optional[str]) -> Dict[str, dict]:
        """Whole-market single-day table {code: record}, cached per (market, date).

        May raise on network / HTTP errors -- the public get_institutional_net wraps
        this in a fail-open try/except. Only non-empty results are cached, so a
        transient rate-limit / empty response is retried on the next call rather
        than serving an empty table for the whole TTL.

        Concurrent callers for the SAME (market, date) coalesce into a single
        upstream fetch (cache-stampede guard) -- this keeps the T86 ~3 req/5 s
        budget intact under parallel callers; different keys still fetch in
        parallel, and the master lock is never held across network I/O. On a fetch
        error the key-lock is released and waiting callers each retry independently
        (serialized only by _throttle), since failures are deliberately not cached.
        """
        ad_date = self._norm_ad_date(date) if market == "twse" else None
        key = (market, ad_date)
        cached = self._read_cache(key)
        if cached is not None:
            return cached
        # Serialize same-key fetches so a burst of callers issues ONE request, not N.
        with self._key_lock(key):
            cached = self._read_cache(key)  # double-check: a prior holder may have filled it
            if cached is not None:
                return cached
            table = self._fetch_twse(ad_date) if market == "twse" else self._fetch_tpex()
            if table:  # never cache an empty / failed fetch -> no TTL-long blackout
                with self._lock:
                    self._cache[key] = table
                    self._cache_at[key] = time.time()
            return table

    def _read_cache(self, key: Any) -> Optional[Dict[str, dict]]:
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and (time.time() - self._cache_at.get(key, 0.0)) < self._cache_ttl:
                return cached
        return None

    def _key_lock(self, key: Any) -> threading.Lock:
        with self._lock:
            lock = self._inflight.get(key)
            if lock is None:
                lock = threading.Lock()
                self._inflight[key] = lock
            return lock

    def _throttle(self) -> None:
        with self._throttle_lock:
            wait = self._min_interval - (time.time() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.time()

    def _get_json(self, url: str, params: Optional[dict] = None) -> Any:
        self._throttle()
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------- TWSE T86 (上市)
    def _fetch_twse(self, ad_date: Optional[str]) -> Dict[str, dict]:
        params = {"response": "json", "selectType": "ALLBUT0999"}
        if ad_date:
            params["date"] = ad_date
        payload = self._get_json(_T86_URL, params)
        if not isinstance(payload, dict) or payload.get("stat") != "OK":
            return {}
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            return {}
        idx = self._t86_index_map(payload.get("fields"))
        if idx is None:  # header missing or a core column renamed/removed -> fail-open
            logger.info("[tw-inst] T86 fields header missing/renamed -> fail-open")
            return {}
        payload_date = self._norm_ad_date(payload.get("date")) or ad_date
        table: Dict[str, dict] = {}
        for row in rows:
            record = self._parse_t86_row(row, payload_date, idx)
            if record is not None:
                table[record["stock_code"]] = record
        return table

    @staticmethod
    def _t86_index_map(fields: Any) -> Optional[Dict[str, int]]:
        """Map each core T86 column NAME to its index, or None if any is missing.

        Reading by name (not a fixed index) means a TWSE column rename / reorder
        fails open rather than silently shipping misaligned foreign/trust/dealer
        numbers under stale indices.
        """
        if not isinstance(fields, list):
            return None
        idx: Dict[str, int] = {}
        for name in _T86_CORE:
            try:
                idx[name] = fields.index(name)
            except ValueError:
                return None
        return idx

    @staticmethod
    def _parse_t86_row(
        row: Any, ad_date: Optional[str], idx: Dict[str, int]
    ) -> Optional[dict]:
        if not isinstance(row, (list, tuple)) or any(i >= len(row) for i in idx.values()):
            return None
        if ad_date is None:  # data with no attributable trading date -> fail-open
            return None
        code = str(row[idx[_T86_CODE]]).strip()
        if not code:
            return None
        foreign = _to_int(row[idx[_T86_FOREIGN]])  # 外陸資 (ex 外資自營商)
        trust = _to_int(row[idx[_T86_TRUST]])
        dealer = _to_int(row[idx[_T86_DEALER]])
        total = _to_int(row[idx[_T86_TOTAL]])
        # A None core component means a missing / unparseable column (NOT genuine 0,
        # which parses to 0) -> drop the row so a report never reads a fabricated zero.
        if foreign is None or trust is None or dealer is None:
            return None
        return TwInstitutionalFetcher._build_record(
            code, ad_date, "上市", "TWSE-T86", foreign, trust, dealer, total
        )

    # -------------------------------------------------------------- TPEx (上櫃)
    def _fetch_tpex(self) -> Dict[str, dict]:
        payload = self._get_json(_TPEX_URL)
        if not isinstance(payload, list) or not payload:
            return {}
        table: Dict[str, dict] = {}
        for raw in payload:
            record = self._parse_tpex_row(raw)
            if record is not None:
                table[record["stock_code"]] = record
        return table

    @staticmethod
    def _parse_tpex_row(raw: Any) -> Optional[dict]:
        if not isinstance(raw, dict):
            return None
        code = str(raw.get("SecuritiesCompanyCode", "")).strip()
        if not code:
            return None
        ad_date = minguo_to_ad(raw.get("Date", ""))
        if ad_date is None:  # 民國 date unconvertible -> no attributable day -> fail-open
            return None
        foreign = _to_int(raw.get(_TPEX_FOREIGN_EXCL))  # dealer-excluded foreign
        trust = _to_int(raw.get(_TPEX_TRUST))
        dealer = _to_int(raw.get(_TPEX_DEALER))
        total = _to_int(raw.get(_TPEX_TOTAL))
        # A None core component means a missing / renamed column -> fail-open (never a
        # fabricated 0). Genuine zero activity parses to 0 and is kept.
        if foreign is None or trust is None or dealer is None:
            return None
        return TwInstitutionalFetcher._build_record(
            code, ad_date, "上櫃", "TPEx-OpenAPI", foreign, trust, dealer, total
        )

    # -------------------------------------------------------------- normalize
    @staticmethod
    def _build_record(
        code: str,
        ad_date: Optional[str],
        market_label: str,
        source: str,
        foreign: int,
        trust: int,
        dealer: int,
        total: Optional[int],
    ) -> dict:
        # foreign / trust / dealer are guaranteed non-None by the parsers (a missing
        # component fails the row open upstream), so a genuine 0 is preserved as 0
        # and is never confused with a missing column.
        return {
            "stock_code": code,
            "date": ad_date,
            "market": market_label,
            "source": source,
            "unit": "shares",
            "foreign_net": foreign,
            "trust_net": trust,
            "dealer_net": dealer,
            # Official total when present; otherwise the component sum (kept consistent).
            "total_net": total if total is not None else foreign + trust + dealer,
        }
