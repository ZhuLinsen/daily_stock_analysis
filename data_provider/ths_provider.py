# -*- coding: utf-8 -*-
"""TongHuaShun board/theme provider for the stock workbench MVP."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

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


class THSProvider:
    """同花顺-oriented board provider with fail-open envelopes."""

    source = "ths"

    def __init__(self, manager: Optional[DataFetcherManager] = None):
        self.manager = manager or DataFetcherManager()

    def get_industry_boards(self) -> Dict[str, Any]:
        try:
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

    def infer_stock_themes(self, symbol: str) -> Dict[str, Any]:
        code = normalize_stock_code(symbol)
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
