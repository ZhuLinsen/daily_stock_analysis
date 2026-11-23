"""Futu fundamental data adapter for DSA offshore analysis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


class FutuFundamentalAdapter:
    """Normalize read-only Futu OpenD data to DSA's fundamental bundle."""

    def __init__(self, fetcher: Any) -> None:
        self._fetcher = fetcher

    @staticmethod
    def _ok_payload(result: Any) -> Tuple[Optional[Any], Optional[str]]:
        """Unwrap the fetcher's payload-only contract."""
        if result is None:
            return None, "empty Futu response"
        return result, None

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            if value is None or pd.isna(value) or str(value).strip() in {"", "-", "N/A", "nan"}:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _text(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _code(stock_code: str) -> str:
        """Keep DSA's internal HK code; FutuFetcher owns SDK conversion."""
        return stock_code

    @staticmethod
    def _source(name: str, status: str = "ok") -> List[Dict[str, Any]]:
        return [{"provider": f"futu.{name}", "result": status, "duration_ms": 0}]

    def _profile(self, code: str, result: Dict[str, Any]) -> None:
        static_info = self._fetcher.get_stock_basicinfo(code)
        if isinstance(static_info, pd.DataFrame) and not static_info.empty:
            row = static_info.iloc[0]
            result["institution"]["static_info"] = {
                key: row.get(key)
                for key in ("code", "name", "lot_size", "suspension", "listing_date", "exchange_type")
                if row.get(key) is not None
            }
            result["source_chain"].extend(self._source("static_info"))
        elif static_info is None:
            result["errors"].append("static_info:empty Futu response")

        payload, error = self._ok_payload(self._fetcher.get_company_profile(code))
        if error:
            result["errors"].append(f"company_profile:{error}")
            return
        if isinstance(payload, pd.DataFrame) and not payload.empty:
            profile = {
                str(row["name"]): row["value"]
                for _, row in payload.iterrows()
                if "name" in row and "value" in row and self._text(row["name"])
            }
            if profile:
                result["institution"]["company_profile"] = profile
                result["source_chain"].extend(self._source("company_profile"))

    def _financials(self, code: str, result: Dict[str, Any]) -> None:
        statements: Dict[str, Dict[str, Any]] = {}
        for statement_type, name in ((1, "income"), (2, "balance_sheet"), (3, "cash_flow"), (4, "indicators")):
            payload, error = self._ok_payload(
                self._fetcher.get_financials_statements(code, statement_type=statement_type, num=8)
            )
            if error:
                result["errors"].append(f"financials_{name}:{error}")
                continue
            if isinstance(payload, dict):
                statements[name] = payload

        income = statements.get("income", {})
        reports = income.get("report_list") or []
        if not reports:
            return
        latest = reports[0] if isinstance(reports[0], dict) else {}
        items = {item.get("display_name"): item for item in latest.get("item_list", []) if isinstance(item, dict)}

        def item(*names: str) -> Optional[Dict[str, Any]]:
            for name in names:
                if name in items:
                    return items[name]
            return None

        revenue = item("营业总收入", "营业额")
        net_profit = item("归属母公司净利润", "归属普通股股东净利润", "净利润")
        gross_profit = item("毛利")
        revenue_value = self._number((revenue or {}).get("data"))
        net_value = self._number((net_profit or {}).get("data"))
        gross_value = self._number((gross_profit or {}).get("data"))
        growth = {
            "revenue_yoy": self._number((revenue or {}).get("yoy")),
            "net_profit_yoy": self._number((net_profit or {}).get("yoy")),
            "gross_margin": (gross_value / revenue_value * 100.0) if gross_value is not None and revenue_value else None,
        }
        result["growth"].update({key: round(value, 6) if value is not None else None for key, value in growth.items()})

        report = {
            "report_date": latest.get("date_time_str"),
            "period": latest.get("period_text"),
            "currency": latest.get("currency_code") or latest.get("currency_info"),
            "revenue": revenue_value,
            "net_profit_parent": net_value,
            "basic_eps": self._number((item("基本每股收益") or {}).get("data")),
            "gross_profit": gross_value,
        }
        for name, payload in statements.items():
            reports_for_type = payload.get("report_list") or []
            if reports_for_type:
                latest_items = reports_for_type[0].get("item_list", [])
                report[name] = {
                    str(entry.get("display_name")): entry.get("data")
                    for entry in latest_items
                    if isinstance(entry, dict) and entry.get("data") is not None
                }
        result["earnings"]["financial_report"] = report
        result["earnings"]["financial_reports"] = {
            name: payload.get("report_list", []) for name, payload in statements.items()
        }
        result["source_chain"].extend(self._source("financials"))

    def _dividends_and_splits(self, code: str, result: Dict[str, Any]) -> None:
        payload, error = self._ok_payload(self._fetcher.get_corporate_actions_dividends(code))
        if error:
            result["errors"].append(f"dividends:{error}")
        elif isinstance(payload, dict):
            raw_events = payload.get("dividend_list") or []
            events: List[Dict[str, Any]] = []
            ttm_events: List[Dict[str, Any]] = []
            ttm_cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).date().isoformat()
            for raw in raw_events:
                if not isinstance(raw, dict):
                    continue
                ex_date = self._text(raw.get("ex_date") or raw.get("ex_dividend_date"))
                per_share = self._number(raw.get("dividend_per_share"))
                if not ex_date and not per_share:
                    continue
                # Normalize OpenD fields to the repo-wide dividend contract
                # consumed by notification / data_processing / market structure.
                event: Dict[str, Any] = {
                    "event_date": ex_date or self._text(raw.get("record_date")),
                    "ex_dividend_date": ex_date,
                    "record_date": self._text(raw.get("record_date")),
                    "announcement_date": self._text(raw.get("announcement_date")),
                    "cash_dividend_per_share": per_share,
                    "currency": self._text(raw.get("currency")),
                    "statement": self._text(raw.get("statement")),
                    "description": self._text(raw.get("description")),
                }
                if not any(v for v in (event["event_date"], event["cash_dividend_per_share"])):
                    continue
                events.append(event)
                if event["event_date"] and event["event_date"] >= ttm_cutoff:
                    ttm_events.append(event)
            events.sort(key=lambda item: item.get("event_date") or "", reverse=True)
            ttm_cash = (
                sum(float(item["cash_dividend_per_share"]) for item in ttm_events if item.get("cash_dividend_per_share") is not None)
                if ttm_events
                else None
            )
            dividend_payload: Dict[str, Any] = {
                "events": events[:5],
                "ttm_event_count": len(ttm_events),
                "ttm_cash_dividend_per_share": round(ttm_cash, 6) if ttm_cash is not None else None,
                "source": "futu",
            }
            if ttm_cash is not None:
                # Yield needs a price; try a lightweight snapshot if available.
                # FutuFetcher.get_realtime_quote returns a UnifiedRealtimeQuote
                # dataclass (not a dict), so read `price` via getattr to cover
                # both shapes.
                quote, quote_err = self._ok_payload(self._fetcher.get_realtime_quote(code))
                if not quote_err and quote is not None:
                    latest_price = self._number(
                        getattr(quote, "price", None)
                        or (quote.get("price") if isinstance(quote, dict) else None)
                        or (quote.get("last_price") if isinstance(quote, dict) else None)
                    )
                    if latest_price not in (None, 0):
                        dividend_payload["ttm_dividend_yield_pct"] = round(
                            float(ttm_cash) / float(latest_price) * 100.0, 4
                        )
            result["earnings"]["dividend"] = dividend_payload
            result["source_chain"].extend(self._source("dividends"))

        payload, error = self._ok_payload(self._fetcher.get_corporate_actions_stock_splits(code, num=50))
        if error:
            result["errors"].append(f"splits:{error}")
        elif isinstance(payload, dict):
            result["earnings"]["stock_splits"] = payload.get("split_list") or []
            result["source_chain"].extend(self._source("stock_splits"))

    def _capital_flow(self, code: str, result: Dict[str, Any]) -> None:
        try:
            import futu
            period = futu.PeriodType.DAY
        except Exception:
            period = "DAY"
        payload, error = self._ok_payload(
            self._fetcher.get_capital_flow(code, period_type=period, start=None, end=None)
        )
        if error:
            result["errors"].append(f"capital_flow:{error}")
        elif isinstance(payload, pd.DataFrame) and not payload.empty:
            result["capital_flow"] = {
                "rows": payload.to_dict(orient="records"),
                "latest": payload.iloc[-1].to_dict(),
            }
            result["source_chain"].extend(self._source("capital_flow"))

    def _boards(self, code: str, result: Dict[str, Any]) -> None:
        payload, error = self._ok_payload(self._fetcher.get_owner_plate([code]))
        if error:
            result["errors"].append(f"owner_plate:{error}")
        elif isinstance(payload, pd.DataFrame) and not payload.empty:
            # OpenD returns plate_code / plate_name / plate_type; DSA's downstream
            # consumers (notification, board-detail extraction, market structure)
            # only understand the name/type/code contract, so normalize here.
            boards = []
            for _, row in payload.iterrows():
                name = self._text(row.get("plate_name"))
                if not name:
                    continue
                item: Dict[str, Any] = {"name": name}
                code_raw = self._text(row.get("plate_code"))
                if code_raw:
                    item["code"] = code_raw
                type_raw = self._text(row.get("plate_type"))
                if type_raw:
                    item["type"] = type_raw
                boards.append(item)
            result["belong_boards"] = boards
            result["source_chain"].extend(self._source("owner_plate"))

    def get_fundamental_bundle(self, stock_code: str) -> Dict[str, Any]:
        code = self._code(stock_code)
        result: Dict[str, Any] = {
            "status": "not_supported",
            "growth": {},
            "earnings": {},
            "institution": {},
            "capital_flow": {},
            "belong_boards": [],
            "source_chain": [],
            "errors": [],
        }
        try:
            self._profile(code, result)
            self._financials(code, result)
            self._dividends_and_splits(code, result)
            self._capital_flow(code, result)
            self._boards(code, result)
        except Exception as exc:
            result["errors"].append(f"futu_adapter:{type(exc).__name__}:{exc}")
        has_content = any(
            result[key]
            for key in ("growth", "earnings", "institution", "capital_flow", "belong_boards")
        )
        result["status"] = "partial" if has_content else "not_supported"
        return result
