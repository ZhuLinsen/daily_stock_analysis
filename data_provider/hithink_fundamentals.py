# -*- coding: utf-8 -*-
"""HiThink financial indicators, statements, and valuation snapshots.

These calls stay inside the existing fundamental pipeline. A missing key,
permission error, or empty payload leaves the AkShare bundle in place.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional

from .hithink_fetcher import HiThinkFetcher, HiThinkRequestError

logger = logging.getLogger(__name__)

_INDICATORS_PATH = "/api/a-share/financials/indicators"
_INCOME_PATH = "/api/a-share/financials/income-statements"
_BALANCE_PATH = "/api/a-share/financials/balance-sheets"
_CASH_FLOW_PATH = "/api/a-share/financials/cash-flow-statements"
_VALUATION_PATH = "/api/a-share/valuations/snapshot"
_REPORT_SUFFIX = {"Q1": "1", "Q2": "2", "Q3": "3", "Q4": "4", "FY": "4"}


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _indicator_values(data: Dict[str, Any]) -> Dict[str, Optional[float]]:
    values: Dict[str, Optional[float]] = {}
    abilities = data.get("abilities")
    if not isinstance(abilities, list):
        return values
    for ability in abilities:
        if not isinstance(ability, dict):
            continue
        indicators = ability.get("indicators")
        if not isinstance(indicators, list):
            continue
        for item in indicators:
            if not isinstance(item, dict):
                continue
            index_id = str(item.get("index_id") or "")
            if index_id:
                values[index_id] = _number(item.get("value"))
    return values


def _latest_item(payload: Dict[str, Any]) -> Dict[str, Any]:
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not isinstance(data.get("item"), list):
        raise HiThinkRequestError("HiThink financial statement response is invalid")
    for item in data["item"]:
        if isinstance(item, dict):
            return item
    return {}


def _report_code(item: Dict[str, Any]) -> Optional[str]:
    year = item.get("fiscal_year")
    period = str(item.get("fiscal_period") or "")
    suffix = _REPORT_SUFFIX.get(period)
    if not isinstance(year, int) or suffix is None:
        return None
    return f"{year}-{suffix}"


class HiThinkFundamentalAdapter:
    """Map documented HiThink financial payloads onto the pipeline bundle."""

    def __init__(self, fetcher: HiThinkFetcher) -> None:
        self.fetcher = fetcher

    def get_fundamental_bundle(self, stock_code: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "status": "not_supported",
            "growth": {},
            "earnings": {},
            "institution": {},
            "source_chain": [],
            "errors": [],
        }
        try:
            thscode, _code = self.fetcher._thscode(stock_code)
        except Exception as exc:
            result["errors"].append(str(exc))
            return result

        income = self._latest_statement(_INCOME_PATH, thscode, result)
        if income:
            report_date = self.fetcher._ms_to_date(income.get("period_end_ms"))
            result["earnings"]["income_statement"] = income
            result["earnings"]["financial_report"] = {
                "report_date": report_date,
                "revenue": _number(income.get("operating_income")),
                "net_profit_parent": _number(income.get("parent_holder_net_profit")),
                "operating_cash_flow": None,
                "roe": None,
            }
            result["source_chain"].append("earnings:hithink_income_statement")

        balance = self._latest_statement(_BALANCE_PATH, thscode, result)
        if balance:
            result["earnings"]["balance_sheet"] = balance
            result["source_chain"].append("earnings:hithink_balance_sheet")

        cash_flow = self._latest_statement(_CASH_FLOW_PATH, thscode, result)
        if cash_flow:
            result["earnings"]["cash_flow"] = cash_flow
            report = result["earnings"].get("financial_report")
            if isinstance(report, dict):
                report["operating_cash_flow"] = _number(cash_flow.get("act_cash_flow_net"))
            result["source_chain"].append("earnings:hithink_cash_flow")

        report = _report_code(income) if income else None
        if report:
            indicators = self._indicators(thscode, report, result)
            growth = {
                "revenue_yoy": indicators.get("operating_income_yoy_growth_ratio"),
                "net_profit_yoy": indicators.get("net_profit_yoy_growth_ratio"),
                "roe": indicators.get("index_weighted_avg_roe"),
                "gross_margin": indicators.get("sale_gross_margin"),
            }
            if any(value is not None for value in growth.values()):
                result["growth"] = growth
                financial_report = result["earnings"].get("financial_report")
                if isinstance(financial_report, dict):
                    financial_report["roe"] = growth["roe"]
                result["source_chain"].append("growth:hithink_financial_indicators")

        if result["growth"] or result["earnings"]:
            result["status"] = "partial"
        return result

    def get_valuation(self, stock_code: str) -> Dict[str, Optional[float]]:
        thscode, _code = self.fetcher._thscode(stock_code)
        payload = self.fetcher._request(_VALUATION_PATH, {"thscodes": thscode})
        data = payload.get("data") or {}
        if not isinstance(data, dict) or not isinstance(data.get("item"), list):
            raise HiThinkRequestError("HiThink valuation response is invalid")
        for item in data["item"]:
            if isinstance(item, dict) and str(item.get("thscode") or "").upper() == thscode.upper():
                return {
                    "pe_ratio": _number(item.get("pe_ttm")),
                    "pb_ratio": _number(item.get("pb_mrq")),
                    "pe_mrq": _number(item.get("pe_mrq")),
                    "ps_ttm": _number(item.get("ps_ttm")),
                    "pcf_ttm": _number(item.get("pcf_ttm")),
                }
        return {}

    def _latest_statement(self, path: str, thscode: str, result: Dict[str, Any]) -> Dict[str, Any]:
        try:
            payload = self.fetcher._request(path, {"thscode": thscode, "period": "quarterly", "limit": 1})
            return _latest_item(payload)
        except HiThinkRequestError as exc:
            logger.warning("[HiThinkFetcher] financial statement failed: path=%s code=%s", path, exc.code)
            result["errors"].append(f"{path}:{exc.code or type(exc).__name__}")
            return {}

    def _indicators(self, thscode: str, report: str, result: Dict[str, Any]) -> Dict[str, Optional[float]]:
        try:
            payload = self.fetcher._request(_INDICATORS_PATH, {"thscode": thscode, "report": report})
        except HiThinkRequestError as exc:
            logger.warning("[HiThinkFetcher] financial indicators failed: code=%s", exc.code)
            result["errors"].append(f"indicators:{exc.code or type(exc).__name__}")
            return {}
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            result["errors"].append("indicators:invalid")
            return {}
        return _indicator_values(data)


def supplement_valuation(fetcher: HiThinkFetcher, stock_code: str, payload: Dict[str, Any]) -> None:
    """Fill only missing valuation fields. Existing quote values and nulls stay intact."""
    try:
        snapshot = HiThinkFundamentalAdapter(fetcher).get_valuation(stock_code)
    except Exception as exc:
        logger.info("[HiThinkFetcher] valuation snapshot skipped: %s", exc)
        return
    for key, value in snapshot.items():
        if payload.get(key) is None and value is not None:
            payload[key] = value
