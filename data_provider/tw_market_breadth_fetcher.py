# -*- coding: utf-8 -*-
"""TwMarketBreadthFetcher — Taiwan whole-market breadth (涨跌家数 / 涨跌停 / 成交额).

Data-layer only, ``tw``-only, strictly additive. Mirrors ``TwInstitutionalFetcher``'s
fail-open / single-day whole-market cache / circuit-breaker / throttle pattern.

Sources (政府開放資料, 政府資料開放授權條款第 1 版 / OGDL v1, commercial-safe, no key):
  - 上市 TWSE 「每日收盤行情」 MI_INDEX (per-stock 收盤價 / 漲跌價 / 成交金額)
    https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date=YYYYMMDD&type=ALLBUT0999
    (date is 西元 ``YYYYMMDD``; amount/price are comma-grouped strings, 漲跌價 is signed)
  - 上櫃 TPEx per-stock daily close, OpenAPI (English keys; serves latest trading day)
    https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes

Fail-open contract: any network error, rate-limit, empty response, unexpected
shape or missing column yields ``None`` (no data) — it never raises into the
caller, so the market-review main flow is never interrupted.

Units:
  - ``total_amount`` is **raw TWD (元)**, NOT pre-divided by 1e8. Downstream
    rendering (``MarketAnalyzer._format_turnover_value`` tw branch) divides by
    1e9 to produce 「十億新台幣」.
  - 涨跌停 uses a unified ±10%: ``change_pct >= +9.9`` -> limit-up,
    ``change_pct <= -9.9`` -> limit-down. Taiwan has no A-share-style ±20%/±30%
    tiers.

Note: field names are read by NAME (not fixed index) so a rename/reorder fails
open instead of silently shipping misaligned numbers. Verified live 2026-08-13:
- TPEx per-stock close keys are ``Date``/``Close``/``Change``/``TransactionAmount``
  and ``Change`` is a SIGNED price difference (not a percentage).
- TWSE ``MI_INDEX`` now returns ``tables`` (per-stock close in the 「每日收盤行情」
  table); ``漲跌(+/-)`` is an HTML sign and ``漲跌價差`` is the UNSIGNED magnitude.
- 產業分類指數 lives in OpenAPI ``MI_INDEX`` (``指數`` + ``漲跌百分比``), filtered
  to industry indices ending in 「類指數」.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from data_provider.realtime_types import CircuitBreaker
from data_provider.tw_institutional_fetcher import minguo_to_ad

logger = logging.getLogger(__name__)

_TWSE_URL = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
_TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
# TWSE 產業分類指數 via OpenAPI MI_INDEX (verified live 2026-08-13: 267 items,
# 指數 + 漲跌百分比). Filtered to industry indices ending in 類指數.
_TWSE_SECTOR_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# TWSE MI_INDEX (每日收盤行情) column NAMES. Read by name so a rename/reorder
# fails open. 漲跌(+/-) is an HTML sign, 漲跌價差 is the UNSIGNED magnitude;
# 昨收價 = 收盤價 - (sign * 漲跌價差).
_TWSE_CODE = "證券代號"
_TWSE_CLOSE = "收盤價"
_TWSE_SIGN = "漲跌(+/-)"
_TWSE_CHANGE = "漲跌價差"
_TWSE_AMOUNT = "成交金額"
_TWSE_CORE = (_TWSE_CODE, _TWSE_CLOSE, _TWSE_SIGN, _TWSE_CHANGE, _TWSE_AMOUNT)

# TPEx OpenAPI per-stock close keys (English; verified live 2026-08-13). Change
# is a SIGNED price difference (not a percentage), TransactionAmount is raw TWD.
_TPEX_DATE = "Date"
_TPEX_CLOSE = "Close"
_TPEX_CHANGE = "Change"
_TPEX_AMOUNT = "TransactionAmount"

# TWSE 產業分類指數 OpenAPI keys (verified live 2026-08-13).
_TWSE_SECTOR_NAME = "指數"
_TWSE_SECTOR_CHANGE_PCT = "漲跌百分比"

# Unified ±10% limit thresholds ("≈" tolerance of 0.1 percentage point).
_LIMIT_UP_PCT = 9.9
_LIMIT_DOWN_PCT = -9.9


def _to_float(value: Any) -> Optional[float]:
    """Parse a numeric cell to float, preserving sign and stripping comma grouping.

    Empty / ``--`` / ``-`` / ``—`` / non-numeric -> ``None`` (missing, never 0).
    """
    try:
        text = str(value).replace(",", "").replace(" ", "").strip()
    except (TypeError, ValueError):
        return None
    if text in ("", "-", "--", "—"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _extract_sign(value: Any) -> float:
    """Extract the +/- sign from a TWSE HTML cell (e.g. ``<p ...>+</p>``)."""
    text = str(value or "")
    if "+" in text:
        return 1.0
    if "-" in text:
        return -1.0
    return 0.0


def _is_industry_index(name: Any) -> bool:
    """产业分類指數 end in 「類指數」; exclude leverage/inverse/return/thematic."""
    return str(name or "").endswith("類指數")


def _compute_breadth(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-stock ``{change_pct, amount}`` records into market breadth.

    ``change_pct`` is the signed day-over-day percent change (already derived by
    the parsers). Limit-up/down use the unified ±10% thresholds.
    """
    up_count = down_count = flat_count = limit_up_count = limit_down_count = 0
    total_amount = 0.0
    for record in records:
        change_pct = record["change_pct"]
        if change_pct > 0:
            up_count += 1
        elif change_pct < 0:
            down_count += 1
        else:
            flat_count += 1
        if change_pct >= _LIMIT_UP_PCT:
            limit_up_count += 1
        elif change_pct <= _LIMIT_DOWN_PCT:
            limit_down_count += 1
        total_amount += record["amount"]
    return {
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "total_amount": total_amount,
    }


class TwMarketBreadthFetcher:
    """Fetch Taiwan whole-market breadth, ``.TW`` (上市) + ``.TWO`` (上櫃) combined."""

    name = "TwMarketBreadthFetcher"

    def __init__(
        self,
        *,
        cache_ttl_seconds: int = 900,
        min_request_interval: float = 1.8,
        timeout: int = 15,
    ) -> None:
        self._cache_ttl = cache_ttl_seconds
        self._timeout = timeout
        # Single-day whole-market stats cache keyed by 西元 date ("latest" for
        # TPEx, which serves only the latest trading day).
        self._cache: Dict[Any, Dict[str, Any]] = {}
        self._cache_at: Dict[Any, float] = {}
        self._lock = threading.Lock()
        # TWSE/TPEx endpoints have informal rate limits; throttle requests.
        self._min_interval = min_request_interval
        self._last_request_at = 0.0
        self._throttle_lock = threading.Lock()
        # Per-market circuit breaker: when an endpoint is down (>= 3 consecutive
        # failures) skip the network round-trip for ~5 min and fail open.
        self._breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=300.0)

    # ------------------------------------------------------------------ public
    def get_market_stats(self, date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return Taiwan whole-market breadth stats, or ``None`` (fail-open).

        ``date`` (西元 ``YYYYMMDD``) only applies to 上市/TWSE MI_INDEX; 上櫃
        TPEx serves the latest trading day. Returns
        ``{up_count, down_count, flat_count, limit_up_count, limit_down_count,
        total_amount}`` or ``None`` when no market produced data.
        """
        key = ("twse", date or "latest")
        cached = self._read_cache(key)
        if cached is not None:
            return cached

        twse = self._fetch_twse(date)
        tpex = self._fetch_tpex(date)
        records = twse + tpex
        if not records:
            return None

        stats = _compute_breadth(records)
        # 源级完整性：TWSE/TPEx 任一交易所无数据时，宽度只覆盖单一交易所。
        stats["data_quality"] = "ok" if twse and tpex else "partial"
        with self._lock:
            self._cache[key] = stats
            self._cache_at[key] = time.time()
        return stats

    def get_sector_rankings(self, n: int = 5) -> Tuple[List[Dict], List[Dict]]:
        """Return ``(top_sectors, bottom_sectors)`` by 產業分類指數 change_pct.

        Each item is ``{"name": ..., "change_pct": ...}``. ``top`` is descending
        (highest change first), ``bottom`` ascending (most negative first), matching
        the A-share ``get_sector_rankings`` ordering. Fail-open: any error / empty
        response returns ``([], [])``.
        """
        records = self._fetch_sectors()
        if not records:
            return ([], [])
        sorted_records = sorted(records, key=lambda r: r["change_pct"], reverse=True)
        top = [{"name": r["name"], "change_pct": r["change_pct"]} for r in sorted_records[:n]]
        bottom = [
            {"name": r["name"], "change_pct": r["change_pct"]}
            for r in reversed(sorted_records[-n:])
        ]
        return (top, bottom)

    # ---------------------------------------------------------- 產業分類指數
    def _fetch_sectors(self) -> List[Dict[str, Any]]:
        if not self._breaker.is_available("twse_sector"):
            logger.info("[tw-breadth] TWSE sector circuit OPEN -> skip fetch, fail-open")
            return []
        try:
            payload = self._get_json(_TWSE_SECTOR_URL)
        except Exception as exc:  # noqa: BLE001 - fail-open by contract
            self._breaker.record_failure("twse_sector", str(exc))
            logger.info("[tw-breadth] TWSE sector fetch failed: %s", exc)
            return []
        self._breaker.record_success("twse_sector")

        if not isinstance(payload, list) or not payload:
            return []
        records: List[Dict[str, Any]] = []
        for raw in payload:
            record = self._parse_sector_row(raw)
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def _parse_sector_row(raw: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        name = str(raw.get(_TWSE_SECTOR_NAME) or "").strip()
        change_pct = _to_float(raw.get(_TWSE_SECTOR_CHANGE_PCT))
        if not name or change_pct is None or not _is_industry_index(name):
            return None
        return {"name": name, "change_pct": change_pct}

    # ------------------------------------------------------------- TWSE (上市)
    def _fetch_twse(self, date: Optional[str]) -> List[Dict[str, Any]]:
        if not self._breaker.is_available("twse"):
            logger.info("[tw-breadth] TWSE circuit OPEN -> skip fetch, fail-open")
            return []
        params = {"response": "json", "type": "ALLBUT0999"}
        if date:
            params["date"] = date
        try:
            payload = self._get_json(_TWSE_URL, params)
        except Exception as exc:  # noqa: BLE001 - fail-open by contract
            self._breaker.record_failure("twse", str(exc))
            logger.info("[tw-breadth] TWSE fetch failed: %s", exc)
            return []
        self._breaker.record_success("twse")

        if not isinstance(payload, dict) or payload.get("stat") != "OK":
            return []
        table = self._find_daily_close_table(payload.get("tables"))
        if table is None:
            logger.info("[tw-breadth] TWSE 每日收盤行情 table missing -> fail-open")
            return []
        fields = table.get("fields")
        rows = table.get("data")
        if not isinstance(rows, list) or not rows:
            return []
        idx = self._mi_index_map(fields)
        if idx is None:  # a core column renamed/removed -> fail-open
            logger.info("[tw-breadth] TWSE fields header missing/renamed -> fail-open")
            return []
        records: List[Dict[str, Any]] = []
        for row in rows:
            record = self._parse_twse_row(row, idx)
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def _find_daily_close_table(tables: Any) -> Optional[Dict[str, Any]]:
        """Locate the 每日收盤行情 table within the new MI_INDEX ``tables`` payload."""
        if not isinstance(tables, list):
            return None
        for table in tables:
            if isinstance(table, dict) and "每日收盤行情" in str(table.get("title") or ""):
                return table
        return None

    @staticmethod
    def _mi_index_map(fields: Any) -> Optional[Dict[str, int]]:
        """Map each core MI_INDEX column NAME to its index, or None if any missing."""
        if not isinstance(fields, list):
            return None
        idx: Dict[str, int] = {}
        for name in _TWSE_CORE:
            try:
                idx[name] = fields.index(name)
            except ValueError:
                return None
        return idx

    @staticmethod
    def _parse_twse_row(row: Any, idx: Dict[str, int]) -> Optional[Dict[str, Any]]:
        if not isinstance(row, (list, tuple)) or any(i >= len(row) for i in idx.values()):
            return None
        close = _to_float(row[idx[_TWSE_CLOSE]])
        magnitude = _to_float(row[idx[_TWSE_CHANGE]])
        amount = _to_float(row[idx[_TWSE_AMOUNT]])
        if close is None or magnitude is None:
            return None
        change = magnitude * _extract_sign(row[idx[_TWSE_SIGN]])
        return TwMarketBreadthFetcher._derive_record(close, change, amount)

    # -------------------------------------------------------------- TPEx (上櫃)
    def _fetch_tpex(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._breaker.is_available("tpex"):
            logger.info("[tw-breadth] TPEx circuit OPEN -> skip fetch, fail-open")
            return []
        try:
            payload = self._get_json(_TPEX_URL)
        except Exception as exc:  # noqa: BLE001 - fail-open by contract
            self._breaker.record_failure("tpex", str(exc))
            logger.info("[tw-breadth] TPEx fetch failed: %s", exc)
            return []
        self._breaker.record_success("tpex")

        if not isinstance(payload, list) or not payload:
            return []
        # TPEx OpenAPI serves only the LATEST trading day (no date param). If a
        # caller asked for a specific 西元 date, never silently mix a different-day
        # 上櫃 figure into the breadth — skip TPEx so the result stays single-date.
        requested = self._norm_ad_date(date)
        if requested and isinstance(payload[0], dict):
            served = minguo_to_ad(payload[0].get(_TPEX_DATE))
            if served is not None and served != requested:
                logger.info(
                    "[tw-breadth] TPEx served %s != requested %s -> skip TPEx",
                    served, requested,
                )
                return []
        records: List[Dict[str, Any]] = []
        for raw in payload:
            record = self._parse_tpex_row(raw)
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def _parse_tpex_row(raw: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        close = _to_float(raw.get(_TPEX_CLOSE))
        change = _to_float(raw.get(_TPEX_CHANGE))
        amount = _to_float(raw.get(_TPEX_AMOUNT))
        return TwMarketBreadthFetcher._derive_record(close, change, amount)

    @staticmethod
    def _norm_ad_date(date: Any) -> Optional[str]:
        if not date:
            return None
        text = str(date).strip().replace("-", "").replace("/", "")
        return text if (text.isdigit() and len(text) == 8) else None

    # -------------------------------------------------------------- normalize
    @staticmethod
    def _derive_record(
        close: Optional[float],
        change: Optional[float],
        amount: Optional[float],
    ) -> Optional[Dict[str, Any]]:
        """Derive ``change_pct`` from signed close/change; fail-open on missing data.

        ``close`` / ``change`` are guaranteed non-None upstream (missing -> None
        -> row dropped), so a genuine 0 change is preserved and is never confused
        with a missing column. ``prev_close <= 0`` (no attributable base) fails
        open.
        """
        if close is None or change is None:
            return None
        prev_close = close - change
        if prev_close <= 0:
            return None
        change_pct = change / prev_close * 100
        return {"change_pct": change_pct, "amount": amount or 0.0}

    # ------------------------------------------------------------- infra
    def _read_cache(self, key: Any) -> Optional[Dict[str, Any]]:
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and (time.time() - self._cache_at.get(key, 0.0)) < self._cache_ttl:
                return cached
        return None

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
