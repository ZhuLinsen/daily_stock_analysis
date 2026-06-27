# -*- coding: utf-8 -*-
"""TongHuaShun board/theme provider for the stock workbench MVP."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from data_provider.base import DataFetcherManager, normalize_stock_code

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace("%", "").replace(",", "")
            if not value or value in {"-", "--"}:
                return None
        parsed = float(value)
        return parsed if parsed == parsed else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    parsed = _safe_float(value)
    return int(parsed) if parsed is not None else default


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def _payload(source: str, *, data: Any, error: Optional[str] = None, stale: bool = False) -> Dict[str, Any]:
    return {
        "source": source,
        "stale": stale,
        "error": error,
        "updated_at": _now_iso(),
        "data": data,
    }


def _is_fuyao_stock_code(code: str) -> bool:
    """Fuyao stock snapshot endpoints do not accept ETF/fund codes."""
    return code.startswith(("60", "68", "00", "001", "002", "003", "30", "43", "83", "87", "88", "92"))


class THSProvider:
    """同花顺-oriented board provider with fail-open envelopes."""

    source = "ths"
    fuyao_source = "ths.fuyao"
    fuyao_base_url = "https://fuyao.aicubes.cn"

    def __init__(self, manager: Optional[DataFetcherManager] = None):
        self.manager = manager or DataFetcherManager()
        self.session = requests.Session()

    @property
    def fuyao_api_key(self) -> str:
        for key in ("FUYAO_API_KEY", "THS_FUYAO_API_KEY", "THS_API_KEY"):
            value = os.getenv(key, "").strip()
            if value:
                return value
        return ""

    def fuyao_enabled(self) -> bool:
        return bool(self.fuyao_api_key)

    def get_stock_snapshot(self, symbol: str) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        if not _is_fuyao_stock_code(code):
            return _payload(self.fuyao_source, data=None, error="unsupported_fuyao_stock_code", stale=True)
        thscode = self._to_thscode(code)
        try:
            payload = self._fuyao_get("/api/a-share/prices/snapshot", {"thscodes": thscode}, timeout=3.0)
            rows = self._extract_items(payload)
            if not rows:
                return _payload(self.fuyao_source, data=None, error="empty_snapshot", stale=True)
            item = rows[0]
            price = _safe_float(item.get("last_price") or item.get("current") or item.get("price"))
            change_pct = _safe_float(item.get("price_change_ratio_pct") or item.get("change_pct"))
            change_amount = _safe_float(item.get("price_change") or item.get("change_amount"))
            high = _safe_float(item.get("high_price") or item.get("high"))
            low = _safe_float(item.get("low_price") or item.get("low"))
            pre_close = _safe_float(item.get("prev_price") or item.get("pre_close"))
            amplitude = None
            if high is not None and low is not None and pre_close not in (None, 0):
                amplitude = (high - low) / pre_close * 100
            return _payload(
                self.fuyao_source,
                data={
                    "code": code,
                    "thscode": _text(item.get("thscode") or thscode),
                    "name": _text(item.get("name")),
                    "price": price,
                    "change_pct": change_pct,
                    "change_amount": change_amount,
                    "volume": _safe_float(item.get("volume")),
                    "amount": _safe_float(item.get("turnover") or item.get("amount")),
                    "volume_ratio": _safe_float(item.get("volume_ratio")),
                    "turnover_rate": _safe_float(item.get("turnover_rate")),
                    "amplitude": amplitude,
                    "open": _safe_float(item.get("open_price") or item.get("open")),
                    "high": high,
                    "low": low,
                    "pre_close": pre_close,
                    "pe_ratio": _safe_float(item.get("pe_ratio") or item.get("pe")),
                    "pb_ratio": _safe_float(item.get("pb_ratio") or item.get("pb")),
                    "total_mv": _safe_float(item.get("total_mv") or item.get("total_market_value")),
                    "circ_mv": _safe_float(item.get("circ_mv") or item.get("float_market_value")),
                    "provider_timestamp": self._timestamp_to_iso((payload.get("data") or {}).get("timestamp") if isinstance(payload.get("data"), dict) else None),
                    "fetched_at": _now_iso(),
                },
            )
        except Exception as exc:
            logger.warning("Fuyao stock snapshot failed for %s: %s", code, exc)
            return _payload(self.fuyao_source, data=None, error=str(exc) or type(exc).__name__, stale=True)

    def get_stock_daily_kline(self, symbol: str, *, days: int = 180) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        if not _is_fuyao_stock_code(code):
            return _payload(self.fuyao_source, data=[], error="unsupported_fuyao_stock_code", stale=True)
        thscode = self._to_thscode(code)
        end = int(datetime.now().timestamp() * 1000)
        start = end - max(30, min(days, 3650)) * 24 * 60 * 60 * 1000
        try:
            payload = self._fuyao_get(
                "/api/a-share/prices/historical",
                {"thscode": thscode, "interval": "1d", "start": start, "end": end, "adjust": "forward"},
                timeout=4.0,
            )
            rows = self._normalize_kline_items(self._extract_items(payload))
            return _payload(self.fuyao_source, data=rows, stale=not bool(rows), error=None if rows else "empty_kline")
        except Exception as exc:
            logger.warning("Fuyao stock kline failed for %s: %s", code, exc)
            return _payload(self.fuyao_source, data=[], error=str(exc) or type(exc).__name__, stale=True)

    def get_main_indices(self) -> Dict[str, Any]:
        if not self.fuyao_enabled():
            return _payload(self.fuyao_source, data=[], error="fuyao_api_key_not_configured", stale=True)
        codes = ["000001.SH", "399001.SZ", "399006.SZ"]
        name_map = {"000001.SH": "上证指数", "399001.SZ": "深证成指", "399006.SZ": "创业板指"}
        try:
            payload = self._fuyao_get("/api/a-share-index/prices/snapshot", {"thscodes": ",".join(codes)}, timeout=3.0)
            rows: List[Dict[str, Any]] = []
            for item in self._extract_items(payload):
                thscode = _text(item.get("thscode"))
                current = _safe_float(item.get("last_price") or item.get("current"))
                rows.append({
                    "code": thscode,
                    "name": name_map.get(thscode, _text(item.get("name")) or thscode),
                    "current": current,
                    "change": _safe_float(item.get("price_change") or item.get("change")),
                    "change_pct": _safe_float(item.get("price_change_ratio_pct") or item.get("change_pct")),
                    "amount": _safe_float(item.get("turnover") or item.get("amount")),
                })
            rows.sort(key=lambda row: codes.index(row["code"]) if row.get("code") in codes else 99)
            return _payload(f"{self.fuyao_source}.index-snapshot", data=rows, stale=not bool(rows), error=None if rows else "empty_main_indices")
        except Exception as exc:
            logger.warning("Fuyao main indices failed: %s", exc)
            return _payload(self.fuyao_source, data=[], error=str(exc) or type(exc).__name__, stale=True)

    def get_market_stats(self, *, sample_limit: int = 1000) -> Dict[str, Any]:
        """Return fast market breadth from Fuyao's paged A-share snapshot.

        The Fuyao endpoint can page the whole A-share universe, but a full fetch
        is too slow for interactive dashboard loading. The workbench therefore
        uses a bounded first-page sample and marks it as partial when applicable.
        """
        if not self.fuyao_enabled():
            return _payload(self.fuyao_source, data={}, error="fuyao_api_key_not_configured", stale=True)
        limit = max(100, min(int(sample_limit or 1000), 1200))
        try:
            payload = self._fuyao_get(
                "/api/a-share/prices/snapshot",
                {"limit": limit, "offset": 0},
                timeout=4.0,
            )
            data = payload.get("data") if isinstance(payload, dict) else {}
            rows = self._extract_items(payload)
            up_count = 0
            down_count = 0
            flat_count = 0
            limit_up_count = 0
            limit_down_count = 0
            total_amount = 0.0
            for item in rows:
                change_pct = _safe_float(item.get("price_change_ratio_pct") or item.get("change_pct"))
                change = _safe_float(item.get("price_change") or item.get("change"))
                amount = _safe_float(item.get("turnover") or item.get("amount"))
                if amount is not None:
                    total_amount += amount
                direction = change_pct if change_pct is not None else change
                if direction is None or abs(direction) < 0.000001:
                    flat_count += 1
                elif direction > 0:
                    up_count += 1
                else:
                    down_count += 1
                if change_pct is not None and change_pct >= 9.8:
                    limit_up_count += 1
                if change_pct is not None and change_pct <= -9.8:
                    limit_down_count += 1
            total_count = _safe_int((data or {}).get("total") if isinstance(data, dict) else None, len(rows))
            partial = bool(total_count and len(rows) < total_count)
            return _payload(
                f"{self.fuyao_source}.market-snapshot-sample",
                data={
                    "up_count": up_count,
                    "down_count": down_count,
                    "flat_count": flat_count,
                    "limit_up_count": limit_up_count,
                    "limit_down_count": limit_down_count,
                    "total_amount": total_amount,
                    "sample_size": len(rows),
                    "total_count": total_count,
                    "partial": partial,
                    "estimated": partial,
                },
                stale=partial or not bool(rows),
                error=None if rows else "empty_market_snapshot",
            )
        except Exception as exc:
            logger.warning("Fuyao market stats failed: %s", exc)
            return _payload(self.fuyao_source, data={}, error=str(exc) or type(exc).__name__, stale=True)

    def get_limit_up_pool(self) -> Dict[str, Any]:
        if not self.fuyao_enabled():
            return _payload(self.fuyao_source, data=[], error="fuyao_api_key_not_configured", stale=True)
        try:
            payload = self._fuyao_get(
                "/api/a-share/special-data/limit-up-pool",
                {"page": 1, "size": 50, "sort_field": "limit_up_time", "sort_dir": "desc"},
                timeout=4.0,
            )
            rows = self._normalize_fuyao_limit_up_items(self._extract_items(payload))
            return _payload(f"{self.fuyao_source}.limit-up-pool", data=rows, stale=not bool(rows), error=None if rows else "empty_limit_up_pool")
        except Exception as exc:
            logger.warning("Fuyao limit-up pool failed: %s", exc)
            return _payload(self.fuyao_source, data=[], error=str(exc) or type(exc).__name__, stale=True)

    def get_industry_boards(self) -> Dict[str, Any]:
        try:
            fuyao = self._get_fuyao_boards("industry")
            if fuyao.get("data"):
                return fuyao
            import akshare as ak

            for func_name in ("stock_board_industry_name_ths", "stock_board_industry_name_em"):
                func = getattr(ak, func_name, None)
                if not callable(func):
                    continue
                try:
                    rows = self._normalize_board_frame(func(), board_type="industry")
                    if rows:
                        return _payload(f"{self.source}.{func_name}", data=rows)
                except Exception as call_exc:
                    logger.debug("%s failed: %s", func_name, call_exc)
            top, bottom = self.manager.get_sector_rankings(n=20)
            rows = self._rankings_to_boards(top, bottom, board_type="industry")
            return _payload("manager.sector_rankings", data=rows, stale=not bool(rows), error=None if rows else "empty_industry_boards")
        except Exception as exc:
            logger.warning("THS industry boards failed: %s", exc, exc_info=True)
            return _payload(self.source, data=[], error=str(exc) or type(exc).__name__, stale=True)

    def get_concept_boards(self) -> Dict[str, Any]:
        try:
            fuyao = self._get_fuyao_boards("cn_concept")
            if fuyao.get("data"):
                return fuyao
            import akshare as ak

            for func_name in ("stock_board_concept_name_ths", "stock_board_concept_name_em"):
                func = getattr(ak, func_name, None)
                if not callable(func):
                    continue
                try:
                    rows = self._normalize_board_frame(func(), board_type="concept")
                    if rows:
                        return _payload(f"{self.source}.{func_name}", data=rows)
                except Exception as call_exc:
                    logger.debug("%s failed: %s", func_name, call_exc)
            top, bottom = self.manager.get_concept_rankings(n=20)
            rows = self._rankings_to_boards(top, bottom, board_type="concept")
            return _payload("manager.concept_rankings", data=rows, stale=not bool(rows), error=None if rows else "empty_concept_boards")
        except Exception as exc:
            logger.warning("THS concept boards failed: %s", exc, exc_info=True)
            return _payload(self.source, data=[], error=str(exc) or type(exc).__name__, stale=True)

    def get_industry_constituents(self, board_name: str) -> Dict[str, Any]:
        return self._get_constituents(board_name, board_type="industry")

    def get_concept_constituents(self, concept_name: str) -> Dict[str, Any]:
        return self._get_constituents(concept_name, board_type="concept")

    def infer_stock_themes(self, symbol: str, *, allow_remote: bool = False) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
        if not allow_remote:
            return _payload(
                self.source,
                data={"symbol": code, "industry": [], "concepts": [], "boards": []},
                error="remote_fetch_skipped_for_fast_view",
                stale=True,
            )
        try:
            boards = self.manager.get_belong_boards(code)
            industry = []
            concepts = []
            for item in boards or []:
                name = _text(item.get("name") if isinstance(item, dict) else item)
                if not name:
                    continue
                kind = _text(item.get("type") if isinstance(item, dict) else "")
                if "行业" in kind and name not in industry:
                    industry.append(name)
                elif name not in concepts:
                    concepts.append(name)
            return _payload(
                "manager.belong_boards",
                data={"symbol": code, "industry": industry[:3], "concepts": concepts[:8], "boards": boards or []},
                stale=not bool(boards),
                error=None if boards else "empty_stock_themes",
            )
        except Exception as exc:
            logger.warning("THS infer themes failed for %s: %s", code, exc, exc_info=True)
            return _payload(self.source, data={"symbol": code, "industry": [], "concepts": [], "boards": []}, error=str(exc) or type(exc).__name__, stale=True)

    def _get_constituents(self, name: str, *, board_type: str) -> Dict[str, Any]:
        board_name = _text(name)
        if not board_name:
            return _payload(self.source, data=[], error="board_name_required", stale=True)
        try:
            fuyao = self._get_fuyao_constituents(board_name)
            if fuyao.get("data"):
                return fuyao
            import akshare as ak

            calls = []
            if board_type == "industry":
                calls.extend((
                    ("stock_board_industry_cons_ths", {"symbol": board_name}),
                    ("stock_board_industry_cons_em", {"symbol": board_name}),
                ))
            else:
                calls.extend((
                    ("stock_board_concept_cons_ths", {"symbol": board_name}),
                    ("stock_board_concept_cons_em", {"symbol": board_name}),
                ))

            last_error = ""
            for func_name, kwargs in calls:
                func = getattr(ak, func_name, None)
                if not callable(func):
                    continue
                try:
                    rows = self._normalize_constituent_frame(func(**kwargs))
                    if rows:
                        return _payload(f"{self.source}.{func_name}", data=rows)
                    last_error = "empty constituents"
                except Exception as call_exc:
                    last_error = str(call_exc) or type(call_exc).__name__
                    logger.debug("%s(%s) failed: %s", func_name, kwargs, call_exc)
            return _payload(self.source, data=[], error=last_error or "constituents_unavailable", stale=True)
        except Exception as exc:
            logger.warning("THS constituents failed for %s/%s: %s", board_type, board_name, exc, exc_info=True)
            return _payload(self.source, data=[], error=str(exc) or type(exc).__name__, stale=True)

    def _fuyao_get(self, path: str, params: Dict[str, Any], *, timeout: float = 3.0) -> Dict[str, Any]:
        api_key = self.fuyao_api_key
        if not api_key:
            raise RuntimeError("fuyao_api_key_not_configured")
        response = self.session.get(
            f"{self.fuyao_base_url}{path}",
            params=params,
            headers={"X-api-key": api_key},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("code") not in (None, 0, "0"):
            raise RuntimeError(str(payload.get("message") or payload.get("msg") or f"fuyao_code_{payload.get('code')}"))
        if not isinstance(payload, dict):
            raise RuntimeError("invalid_fuyao_payload")
        return payload

    def _get_fuyao_boards(self, tag: str, *, hydrate_quotes: bool = True) -> Dict[str, Any]:
        if not self.fuyao_enabled():
            return _payload(self.fuyao_source, data=[], error="fuyao_api_key_not_configured", stale=True)
        board_type = "industry" if tag == "industry" else "concept"
        try:
            payload = self._fuyao_get("/api/a-share-index/catalog/ths-index-list", {"tag": tag}, timeout=4.0)
            rows = self._normalize_fuyao_board_items(self._extract_items(payload), board_type=board_type)
            if hydrate_quotes:
                self._hydrate_fuyao_board_quotes(rows)
            return _payload(f"{self.fuyao_source}.ths-index-list", data=rows, stale=not bool(rows), error=None if rows else "empty_boards")
        except Exception as exc:
            logger.warning("Fuyao %s boards failed: %s", board_type, exc)
            return _payload(self.fuyao_source, data=[], error=str(exc) or type(exc).__name__, stale=True)

    def _hydrate_fuyao_board_quotes(self, rows: List[Dict[str, Any]]) -> None:
        codes = [row.get("code") for row in rows[:80] if row.get("code")]
        if not codes:
            return
        try:
            payload = self._fuyao_get("/api/a-share-index/prices/snapshot", {"thscodes": ",".join(codes)}, timeout=4.0)
            quote_map = {str(item.get("thscode") or ""): item for item in self._extract_items(payload) if isinstance(item, dict)}
            for row in rows:
                quote = quote_map.get(str(row.get("code") or ""))
                if not quote:
                    continue
                row["change_pct"] = _safe_float(quote.get("price_change_ratio_pct") or quote.get("change_pct"))
                row["amount"] = _safe_float(quote.get("turnover") or quote.get("amount"))
        except Exception as exc:
            logger.debug("Fuyao board quote hydration failed: %s", exc)

    def _get_fuyao_constituents(self, board_name_or_code: str) -> Dict[str, Any]:
        if not self.fuyao_enabled():
            return _payload(self.fuyao_source, data=[], error="fuyao_api_key_not_configured", stale=True)
        try:
            thscode = board_name_or_code if "." in board_name_or_code else self._resolve_board_thscode(board_name_or_code)
            if not thscode:
                return _payload(self.fuyao_source, data=[], error="board_thscode_not_found", stale=True)
            payload = self._fuyao_get("/api/a-share-index/constituents/ths-stock-list", {"thscode": thscode}, timeout=4.0)
            rows = self._normalize_fuyao_constituent_items(self._extract_items(payload))
            return _payload(f"{self.fuyao_source}.ths-stock-list", data=rows, stale=not bool(rows), error=None if rows else "empty_constituents")
        except Exception as exc:
            logger.warning("Fuyao constituents failed for %s: %s", board_name_or_code, exc)
            return _payload(self.fuyao_source, data=[], error=str(exc) or type(exc).__name__, stale=True)

    def _resolve_board_thscode(self, board_name: str) -> str:
        target = _text(board_name)
        for tag in ("industry", "cn_concept"):
            payload = self._get_fuyao_boards(tag, hydrate_quotes=False)
            for row in payload.get("data") or []:
                if row.get("name") == target:
                    return _text(row.get("code"))
        return ""

    @staticmethod
    def _to_thscode(symbol: str) -> str:
        raw = _text(symbol).upper()
        if "." in raw:
            code, suffix = raw.split(".", 1)
            return f"{code}.{suffix}"
        code = normalize_stock_code(raw)
        if code.startswith(("60", "68", "90")):
            return f"{code}.SH"
        if code.startswith(("00", "001", "002", "003", "30", "20")):
            return f"{code}.SZ"
        if code.startswith(("43", "83", "87", "88", "92")):
            return f"{code}.BJ"
        return f"{code}.SH"

    @staticmethod
    def _extract_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("item", "items", "list", "records", "rows", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            return [data]
        return []

    @staticmethod
    def _timestamp_to_iso(value: Any) -> Optional[str]:
        parsed = _safe_float(value)
        if parsed is None:
            return None
        try:
            if parsed > 10_000_000_000:
                parsed = parsed / 1000
            return datetime.fromtimestamp(parsed).isoformat(timespec="seconds")
        except Exception:
            return None

    @classmethod
    def _normalize_kline_items(cls, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in items:
            date_text = cls._timestamp_to_iso(item.get("date_ms") or item.get("date"))
            rows.append({
                "date": date_text[:10] if date_text else _text(item.get("trade_date") or item.get("date")),
                "open": _safe_float(item.get("open_price") or item.get("open")),
                "high": _safe_float(item.get("high_price") or item.get("high")),
                "low": _safe_float(item.get("low_price") or item.get("low")),
                "close": _safe_float(item.get("close_price") or item.get("close")),
                "volume": _safe_float(item.get("volume")),
                "amount": _safe_float(item.get("turnover") or item.get("amount")),
            })
        return [row for row in rows if row.get("date") and row.get("close") is not None]

    @staticmethod
    def _normalize_fuyao_board_items(items: List[Dict[str, Any]], *, board_type: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in items:
            name = _text(item.get("name") or item.get("index_name") or item.get("ths_index_name"))
            code = _text(item.get("thscode") or item.get("code") or item.get("index_code"))
            if not name or not code:
                continue
            rows.append({
                "name": name,
                "type": board_type,
                "code": code,
                "change_pct": _safe_float(item.get("price_change_ratio_pct") or item.get("change_pct")),
                "amount": _safe_float(item.get("turnover") or item.get("amount")),
                "turnover_rate": _safe_float(item.get("turnover_rate")),
                "leading_stock": _text(item.get("leading_stock") or item.get("lead_stock") or item.get("leader")),
            })
        return rows

    @staticmethod
    def _normalize_fuyao_constituent_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in items:
            code = _text(item.get("ticker") or item.get("code") or item.get("stock_code"))
            thscode = _text(item.get("thscode"))
            name = _text(item.get("name") or item.get("stock_name") or item.get("sec_name"))
            if not code and thscode:
                code = thscode.split(".", 1)[0]
            if not code and not name:
                continue
            rows.append({
                "code": code,
                "thscode": thscode,
                "name": name,
                "price": _safe_float(item.get("last_price") or item.get("price")),
                "change_pct": _safe_float(item.get("price_change_ratio_pct") or item.get("change_pct")),
                "turnover_rate": _safe_float(item.get("turnover_rate")),
                "amount": _safe_float(item.get("turnover") or item.get("amount")),
            })
        return rows

    @staticmethod
    def _normalize_fuyao_limit_up_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in items:
            code = _text(item.get("ticker") or item.get("code"))
            name = _text(item.get("name") or item.get("stock_name"))
            if not code and not name:
                continue
            rows.append({
                "code": code,
                "name": name,
                "price": _safe_float(item.get("last_price") or item.get("price")),
                "change_pct": _safe_float(item.get("price_change_ratio_pct") or item.get("change_pct")),
                "amount": _safe_float(item.get("turnover") or item.get("amount")),
                "turnover_rate": _safe_float(item.get("turnover_rate")),
                "seal_amount": _safe_float(item.get("seal_money")),
                "first_limit_time": _text(item.get("limit_up_time")),
                "last_limit_time": _text(item.get("limit_up_time")),
                "limit_stat": _text(item.get("continue_day_text")),
                "consecutive_boards": _safe_float(item.get("continue_day_cnt")),
                "industry": _text(item.get("limit_up_reason")),
            })
        return rows

    @staticmethod
    def _normalize_board_frame(df: Any, *, board_type: str) -> List[Dict[str, Any]]:
        if df is None or getattr(df, "empty", True):
            return []
        rows: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            name = _text(
                row.get("板块名称")
                or row.get("概念名称")
                or row.get("行业名称")
                or row.get("板块")
                or row.get("name")
            )
            if not name:
                continue
            rows.append({
                "name": name,
                "type": board_type,
                "code": _text(row.get("板块代码") or row.get("代码") or row.get("code")),
                "change_pct": _safe_float(row.get("涨跌幅") or row.get("涨幅") or row.get("change_pct")),
                "amount": _safe_float(row.get("成交额") or row.get("amount")),
                "turnover_rate": _safe_float(row.get("换手率") or row.get("turnover_rate")),
                "leading_stock": _text(row.get("领涨股票") or row.get("领涨股") or row.get("leading_stock")),
            })
        return rows

    @staticmethod
    def _rankings_to_boards(top: List[Dict[str, Any]], bottom: List[Dict[str, Any]], *, board_type: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for bucket, direction in ((top or [], "top"), (bottom or [], "bottom")):
            for item in bucket:
                if not isinstance(item, dict):
                    continue
                name = _text(item.get("name"))
                if not name:
                    continue
                rows.append({
                    "name": name,
                    "type": board_type,
                    "direction": direction,
                    "change_pct": _safe_float(item.get("change_pct")),
                })
        return rows

    @staticmethod
    def _normalize_constituent_frame(df: Any) -> List[Dict[str, Any]]:
        if df is None or getattr(df, "empty", True):
            return []
        rows: List[Dict[str, Any]] = []
        for _, row in df.iterrows():
            code = _text(row.get("代码") or row.get("股票代码") or row.get("证券代码") or row.get("code"))
            name = _text(row.get("名称") or row.get("股票名称") or row.get("name"))
            if not code and not name:
                continue
            rows.append({
                "code": code,
                "name": name,
                "price": _safe_float(row.get("最新价") or row.get("现价") or row.get("price")),
                "change_pct": _safe_float(row.get("涨跌幅") or row.get("涨幅") or row.get("change_pct")),
                "turnover_rate": _safe_float(row.get("换手率") or row.get("turnover_rate")),
                "amount": _safe_float(row.get("成交额") or row.get("amount")),
            })
        return rows
