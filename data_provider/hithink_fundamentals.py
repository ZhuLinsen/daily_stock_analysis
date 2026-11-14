# -*- coding: utf-8 -*-
"""HiThink financial indicators, statements, and valuation snapshots.

These calls stay inside the existing fundamental pipeline. A missing key,
permission error, or empty payload leaves the AkShare bundle in place.
"""

from __future__ import annotations

import copy
import logging
import math
from typing import Any, Dict, Optional

from .base import DataFetchError
from .hithink_fetcher import (
    HiThinkFetcher,
    HiThinkRequestError,
    request_budget,
    request_budget_remaining,
)

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

    def get_fundamental_bundle(
        self,
        stock_code: str,
        deadline: Optional[float] = None,
    ) -> Dict[str, Any]:
        with request_budget(deadline):
            return self._load_fundamental_bundle(stock_code)

    def _same_statement_period(self, statement: Dict[str, Any], anchor: Optional[str]) -> bool:
        if not anchor:
            return False
        return self.fetcher._ms_to_date(statement.get("period_end_ms")) == anchor

    def _budget_exhausted(self, result: Dict[str, Any]) -> bool:
        if "budget_exhausted" in result["errors"]:
            return True
        remaining = request_budget_remaining()
        if remaining is not None and remaining <= 0:
            result["errors"].append("budget_exhausted")
            return True
        return False

    def _load_fundamental_bundle(self, stock_code: str) -> Dict[str, Any]:
        result = empty_fundamental_bundle()
        if not self.fetcher.is_available("fundamental"):
            return result
        if self._budget_exhausted(result):
            return result
        try:
            thscode, _code = self.fetcher._thscode(stock_code)
        except Exception as exc:
            result["errors"].append(str(exc))
            return result

        income = self._latest_statement(_INCOME_PATH, thscode, result)
        balance = self._latest_statement(_BALANCE_PATH, thscode, result) if not self._budget_exhausted(result) else {}
        cash_flow = self._latest_statement(_CASH_FLOW_PATH, thscode, result) if not self._budget_exhausted(result) else {}
        anchor = self.fetcher._ms_to_date(income.get("period_end_ms")) if income else None
        if income and anchor:
            result["earnings"]["income_statement"] = income
            result["earnings"]["financial_report"] = {
                "report_date": anchor,
                "revenue": _number(income.get("operating_income")),
                "net_profit_parent": _number(income.get("parent_holder_net_profit")),
                "operating_cash_flow": None,
                "roe": None,
            }
            result["source_chain"].append("earnings:hithink_income_statement")
        elif income:
            result["errors"].append("period_missing:income_statement")
        if balance and self._same_statement_period(balance, anchor):
            result["earnings"]["balance_sheet"] = balance
            result["source_chain"].append("earnings:hithink_balance_sheet")
        elif balance:
            result["errors"].append("period_mismatch:balance_sheet")
        if cash_flow and self._same_statement_period(cash_flow, anchor):
            result["earnings"]["cash_flow"] = cash_flow
            report = result["earnings"].get("financial_report")
            if isinstance(report, dict):
                report["operating_cash_flow"] = _number(cash_flow.get("act_cash_flow_net"))
            result["source_chain"].append("earnings:hithink_cash_flow")
        elif cash_flow:
            result["errors"].append("period_mismatch:cash_flow")
        if self._budget_exhausted(result):
            return result

        report = _report_code(income) if income and anchor else None
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

    def get_valuation(
        self,
        stock_code: str,
        deadline: Optional[float] = None,
    ) -> Dict[str, Optional[float]]:
        with request_budget(deadline):
            return self._load_valuation(stock_code)

    def _load_valuation(self, stock_code: str) -> Dict[str, Optional[float]]:
        if not self.fetcher.is_available("fundamental"):
            return {}
        remaining = request_budget_remaining()
        if remaining is not None and remaining <= 0:
            return {}
        thscode, _code = self.fetcher._thscode(stock_code)
        try:
            payload = self.fetcher._request(
                _VALUATION_PATH,
                {"thscodes": thscode},
                capability="fundamental",
            )
        except HiThinkRequestError as exc:
            _remember_permission(self.fetcher, exc)
            raise
        except DataFetchError as exc:
            if "budget exhausted" in str(exc):
                return {}
            raise
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
        if not self.fetcher.is_available("fundamental") or self._budget_exhausted(result):
            return {}
        try:
            payload = self.fetcher._request(
                path,
                {"thscode": thscode, "period": "quarterly", "limit": 1},
                capability="fundamental",
            )
            return _latest_item(payload)
        except HiThinkRequestError as exc:
            _remember_permission(self.fetcher, exc)
            logger.warning("[HiThinkFetcher] financial statement failed: path=%s code=%s", path, exc.code)
            result["errors"].append(f"{path}:{exc.code or type(exc).__name__}")
            return {}
        except DataFetchError as exc:
            if "budget exhausted" in str(exc):
                if "budget_exhausted" not in result["errors"]:
                    result["errors"].append("budget_exhausted")
                return {}
            raise

    def _indicators(self, thscode: str, report: str, result: Dict[str, Any]) -> Dict[str, Optional[float]]:
        if not self.fetcher.is_available("fundamental") or self._budget_exhausted(result):
            return {}
        try:
            payload = self.fetcher._request(
                _INDICATORS_PATH,
                {"thscode": thscode, "report": report},
                capability="fundamental",
            )
        except HiThinkRequestError as exc:
            _remember_permission(self.fetcher, exc)
            logger.warning("[HiThinkFetcher] financial indicators failed: code=%s", exc.code)
            result["errors"].append(f"indicators:{exc.code or type(exc).__name__}")
            return {}
        except DataFetchError as exc:
            if "budget exhausted" in str(exc):
                if "budget_exhausted" not in result["errors"]:
                    result["errors"].append("budget_exhausted")
                return {}
            raise
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            result["errors"].append("indicators:invalid")
            return {}
        return _indicator_values(data)


def supplement_valuation(
    fetcher: HiThinkFetcher,
    stock_code: str,
    payload: Dict[str, Any],
    snapshot: Optional[Dict[str, Optional[float]]] = None,
) -> None:
    """Fill only missing valuation fields. Existing quote values and nulls stay intact."""
    if snapshot is None:
        try:
            snapshot = HiThinkFundamentalAdapter(fetcher).get_valuation(stock_code)
        except Exception as exc:
            logger.info("[HiThinkFetcher] valuation snapshot skipped: %s", exc)
            return
    for key, value in snapshot.items():
        if payload.get(key) is None and value is not None:
            payload[key] = value


def empty_fundamental_bundle() -> Dict[str, Any]:
    return {
        "status": "not_supported",
        "growth": {},
        "earnings": {},
        "institution": {},
        "source_chain": [],
        "errors": [],
    }


def merge_fundamental_bundles(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """Fill missing blocks from ``extra`` without mixing report periods.

    AkShare is the base because it owns forecast, quick report, dividend, and
    institution blocks that HiThink does not provide. A HiThink statement is
    copied only when the base has no report of its own, or both reports name
    the same period. Fields that already have a value stay unchanged.
    """
    result = copy.deepcopy(base if isinstance(base, dict) else empty_fundamental_bundle())
    if not isinstance(extra, dict):
        return result
    for key in ("growth", "earnings", "institution", "source_chain", "errors"):
        result.setdefault(key, [] if key in {"source_chain", "errors"} else {})

    base_report = _mapping((base.get("earnings") or {}).get("financial_report") if isinstance(base, dict) else None)
    extra_report = _mapping((extra.get("earnings") or {}).get("financial_report"))
    base_date = base_report.get("report_date") if _report_present(base_report) else None
    extra_date = extra_report.get("report_date") if _report_present(extra_report) else None
    same_period = bool(base_date and extra_date and str(base_date) == str(extra_date))
    base_growth = _mapping(base.get("growth") if isinstance(base, dict) else None)
    base_has_growth = any(_present(value) for value in base_growth.values())
    base_has_report = _report_present(base_report)
    can_share_period = same_period or (not base_has_report and not base_has_growth)

    growth = _mapping(result.get("growth"))
    if can_share_period:
        for key, value in _mapping(extra.get("growth")).items():
            if not _present(growth.get(key)) and _present(value):
                growth[key] = value
    result["growth"] = growth

    earnings = _mapping(result.get("earnings"))
    extra_earnings = _mapping(extra.get("earnings"))
    if can_share_period and not base_has_report and _report_present(extra_report):
        earnings["financial_report"] = copy.deepcopy(extra_report)
    elif same_period and isinstance(earnings.get("financial_report"), dict):
        report = dict(earnings["financial_report"])
        for key, value in extra_report.items():
            if key == "report_date" or _present(report.get(key)) or not _present(value):
                continue
            report[key] = copy.deepcopy(value)
        earnings["financial_report"] = report
    if can_share_period:
        for key in ("income_statement", "balance_sheet", "cash_flow"):
            if not _present(earnings.get(key)) and _present(extra_earnings.get(key)):
                earnings[key] = copy.deepcopy(extra_earnings[key])
    for key in ("forecast_summary", "quick_report_summary", "dividend"):
        if not _present(earnings.get(key)) and _present(extra_earnings.get(key)):
            earnings[key] = copy.deepcopy(extra_earnings[key])
    result["earnings"] = earnings

    institution = _mapping(result.get("institution"))
    for key, value in _mapping(extra.get("institution")).items():
        if not _present(institution.get(key)) and _present(value):
            institution[key] = copy.deepcopy(value)
    result["institution"] = institution

    chain = list(result.get("source_chain") or [])
    for item in extra.get("source_chain") or []:
        if item not in chain:
            chain.append(item)
    result["source_chain"] = chain
    result["errors"] = list(result.get("errors") or []) + list(extra.get("errors") or [])
    has_content = any(_present(result.get(key)) for key in ("growth", "earnings", "institution"))
    result["status"] = "partial" if has_content else "not_supported"
    return result


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != {} and value != []


def _report_present(report: Dict[str, Any]) -> bool:
    return any(key != "report_date" and _present(value) for key, value in report.items()) or _present(
        report.get("report_date")
    )


def _remember_permission(fetcher: HiThinkFetcher, exc: HiThinkRequestError) -> None:
    if exc.permission:
        fetcher._remember_error(str(exc), fundamental_only=True)
